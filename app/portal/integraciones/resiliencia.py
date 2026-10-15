"""Mecanismos de Resiliencia para integraciones externas (Relevo 2).

Provee:
1. CircuitBreaker: Monitorea tasa de fallos técnicos en una ventana móvil y corta llamadas si supera el umbral.
2. Bulkhead: Aísla la concurrencia hacia dependencias externas mediante semáforos con tiempo de espera acotado.
3. Motor de reintentos: Backoff exponencial con full jitter y presupuesto de tiempo estricto (< 60s TTL).

Todos los mecanismos son configurables vía variables de entorno y se instrumentan en Prometheus.
"""
import asyncio
import collections
import random
import time
from typing import Any, Callable, Coroutine, Deque, Tuple

from portal import config
from portal.observabilidad import (
    BREAKER_ESTADO,
    BREAKER_LLAMADAS,
    BREAKER_TRANSICIONES,
    BULKHEAD_EN_USO,
    BULKHEAD_RECHAZOS,
    CREDITO_REINTENTOS,
)


class CircuitBreaker:
    """Implementa el patrón Circuit Breaker con ventana móvil por tiempo e intentos."""

    ESTADO_CERRADO = 0
    ESTADO_ABIERTO = 1
    ESTADO_SEMIABIERTO = 2

    def __init__(self):
        self.estado = self.ESTADO_CERRADO
        self.tiempo_apertura: float = 0.0
        # Ventana deslizante de tuplas (timestamp, exito: bool)
        self.historial: Deque[Tuple[float, bool]] = collections.deque()
        # Contador de llamadas en estado semiabierto
        self.pruebas_semiabierto: int = 0
        self.fallos_semiabierto: int = 0
        self._lock = asyncio.Lock()
        # Métrica inicial
        BREAKER_ESTADO.labels(config.INSTANCIA).set(self.ESTADO_CERRADO)

    def _limpiar_ventana(self, ahora: float) -> None:
        """Descarta muestras fuera de la ventana móvil de tiempo."""
        limite = ahora - config.BREAKER_VENTANA_S
        while self.historial and self.historial[0][0] < limite:
            self.historial.popleft()

    async def antes_de_llamar(self) -> None:
        """Verifica si la llamada está permitida o si el breaker la rechaza."""
        if not config.BREAKER_ACTIVO:
            return

        async with self._lock:
            ahora = time.monotonic()
            if self.estado == self.ESTADO_ABIERTO:
                # Comprobar si venció el tiempo de espera para pasar a semiabierto
                if ahora - self.tiempo_apertura >= config.BREAKER_ESPERA_ABIERTO_S:
                    self.estado = self.ESTADO_SEMIABIERTO
                    self.pruebas_semiabierto = 0
                    self.fallos_semiabierto = 0
                    BREAKER_TRANSICIONES.labels(config.INSTANCIA, "abierto", "semiabierto").inc()
                    BREAKER_ESTADO.labels(config.INSTANCIA).set(self.ESTADO_SEMIABIERTO)
                else:
                    BREAKER_LLAMADAS.labels(config.INSTANCIA, "abierto", "rechazado").inc()
                    from portal.integraciones.credito import CreditoNoDisponible
                    raise CreditoNoDisponible("breaker_abierto")

            if self.estado == self.ESTADO_SEMIABIERTO:
                if self.pruebas_semiabierto >= config.BREAKER_PRUEBAS_SEMIABIERTO:
                    # Se agotaron las pruebas permitidas en esta ventana de prueba
                    BREAKER_LLAMADAS.labels(config.INSTANCIA, "semiabierto", "rechazado").inc()
                    from portal.integraciones.credito import CreditoNoDisponible
                    raise CreditoNoDisponible("breaker_abierto")
                self.pruebas_semiabierto += 1

    async def registrar_resultado(self, exito: bool) -> None:
        """Registra el desenlace técnico de la llamada y actualiza el estado."""
        if not config.BREAKER_ACTIVO:
            return

        async with self._lock:
            ahora = time.monotonic()
            estado_actual_str = ("cerrado" if self.estado == self.ESTADO_CERRADO
                                 else "semiabierto" if self.estado == self.ESTADO_SEMIABIERTO
                                 else "abierto")
            resultado_str = "exito" if exito else "fallo"
            BREAKER_LLAMADAS.labels(config.INSTANCIA, estado_actual_str, resultado_str).inc()

            if self.estado == self.ESTADO_CERRADO:
                self._limpiar_ventana(ahora)
                self.historial.append((ahora, exito))
                total = len(self.historial)
                if total >= config.BREAKER_MIN_LLAMADAS:
                    fallos = sum(1 for _, ok in self.historial if not ok)
                    pct_fallos = (fallos / total) * 100.0
                    if pct_fallos >= config.BREAKER_UMBRAL_FALLOS_PCT:
                        # Abre el circuito
                        self.estado = self.ESTADO_ABIERTO
                        self.tiempo_apertura = ahora
                        self.historial.clear()
                        BREAKER_TRANSICIONES.labels(config.INSTANCIA, "cerrado", "abierto").inc()
                        BREAKER_ESTADO.labels(config.INSTANCIA).set(self.ESTADO_ABIERTO)

            elif self.estado == self.ESTADO_SEMIABIERTO:
                if not exito:
                    self.fallos_semiabierto += 1

                # Si se completaron las pruebas de sondeo
                if self.pruebas_semiabierto >= config.BREAKER_PRUEBAS_SEMIABIERTO:
                    pct_fallos = (self.fallos_semiabierto / self.pruebas_semiabierto) * 100.0
                    if pct_fallos < config.BREAKER_UMBRAL_FALLOS_PCT:
                        # Se recuperó: cierra el circuito
                        self.estado = self.ESTADO_CERRADO
                        self.historial.clear()
                        BREAKER_TRANSICIONES.labels(config.INSTANCIA, "semiabierto", "cerrado").inc()
                        BREAKER_ESTADO.labels(config.INSTANCIA).set(self.ESTADO_CERRADO)
                    else:
                        # Sigue fallando: vuelve a abrir
                        self.estado = self.ESTADO_ABIERTO
                        self.tiempo_apertura = ahora
                        BREAKER_TRANSICIONES.labels(config.INSTANCIA, "semiabierto", "abierto").inc()
                        BREAKER_ESTADO.labels(config.INSTANCIA).set(self.ESTADO_ABIERTO)


class Bulkhead:
    """Implementa aislamiento de concurrencia mediante un semáforo asíncrono con timeout de cola."""

    def __init__(self):
        self._semaforo: asyncio.Semaphore | None = None
        BULKHEAD_EN_USO.labels(config.INSTANCIA).set(0)

    def _obtener_semaforo(self) -> asyncio.Semaphore:
        if self._semaforo is None:
            self._semaforo = asyncio.Semaphore(config.BULKHEAD_MAX_CONCURRENTES)
        return self._semaforo

    async def ejecutar(self, operacion: Callable[[], Coroutine[Any, Any, Any]]) -> Any:
        if not config.BULKHEAD_ACTIVO:
            return await operacion()

        sem = self._obtener_semaforo()
        espera_s = config.BULKHEAD_ESPERA_MS / 1000.0
        try:
            adquirido = await asyncio.wait_for(sem.acquire(), timeout=espera_s)
        except asyncio.TimeoutError:
            BULKHEAD_RECHAZOS.labels(config.INSTANCIA).inc()
            from portal.integraciones.credito import CreditoNoDisponible
            raise CreditoNoDisponible("bulkhead_agotado")

        BULKHEAD_EN_USO.labels(config.INSTANCIA).inc()
        try:
            return await operacion()
        finally:
            sem.release()
            BULKHEAD_EN_USO.labels(config.INSTANCIA).dec()


# Instancias singleton por proceso de la aplicación
_breaker = CircuitBreaker()
_bulkhead = Bulkhead()


def obtener_breaker() -> CircuitBreaker:
    return _breaker


def obtener_bulkhead() -> Bulkhead:
    return _bulkhead


async def ejecutar_con_reintentos(
    fn_intento: Callable[[int], Coroutine[Any, Any, Any]],
    idempotency_key: str | None = None,
) -> Any:
    """Ejecuta una llamada asíncrona aplicando Circuit Breaker, Bulkhead y Reintentos con full jitter."""
    breaker = obtener_breaker()
    bulkhead = obtener_bulkhead()

    max_intentos = (1 + config.REINTENTOS_MAX) if config.REINTENTOS_ACTIVO else 1
    presupuesto_s = config.REINTENTOS_PRESUPUESTO_MS / 1000.0
    inicio_total = time.monotonic()

    ultimo_error: Exception | None = None

    for intento in range(1, max_intentos + 1):
        # 1. Verificar Circuit Breaker antes del intento
        await breaker.antes_de_llamar()

        # 2. Ejecutar a través del Bulkhead
        try:
            async def _ejecutar():
                timeout_intento_s = (config.CREDITO_TIMEOUT_INTENTO_MS / 1000.0
                                    if config.CREDITO_TIMEOUT_INTENTO_MS > 0
                                    else config.CREDITO_TIMEOUT_S)
                return await asyncio.wait_for(fn_intento(intento), timeout=timeout_intento_s)

            resultado = await bulkhead.ejecutar(_ejecutar)
            # Éxito técnico
            await breaker.registrar_resultado(exito=True)
            if intento > 1:
                CREDITO_REINTENTOS.labels(config.INSTANCIA, str(intento), "exito").inc()
            return resultado

        except Exception as e:
            # Fallo técnico
            from portal.integraciones.credito import CreditoNoDisponible
            motivo = str(e)
            if not isinstance(e, CreditoNoDisponible):
                e = CreditoNoDisponible(f"{type(e).__name__}: {motivo}")

            ultimo_error = e

            # Si el fallo vino de rechazo de Breaker o Bulkhead antes de salir, no cuenta como fallo del externo
            if motivo not in ("breaker_abierto", "bulkhead_agotado"):
                await breaker.registrar_resultado(exito=False)

            if intento >= max_intentos or not config.REINTENTOS_ACTIVO:
                break

            # Si falló por breaker o bulkhead saturado, fallar rápido sin reintentar en bucle inútil
            if motivo in ("breaker_abierto", "bulkhead_agotado"):
                break

            # Calcular backoff exponencial con Full Jitter
            techo = min(config.REINTENTOS_TOPE_MS, config.REINTENTOS_BASE_MS * (2 ** (intento - 1)))
            espera_ms = random.uniform(0, float(techo))
            espera_s = espera_ms / 1000.0

            transcurrido = time.monotonic() - inicio_total
            if transcurrido + espera_s > presupuesto_s:
                # Se agotó el presupuesto de tiempo
                CREDITO_REINTENTOS.labels(config.INSTANCIA, str(intento), "presupuesto_agotado").inc()
                raise CreditoNoDisponible("presupuesto_reintentos_agotado") from e

            CREDITO_REINTENTOS.labels(config.INSTANCIA, str(intento), "reintento").inc()
            await asyncio.sleep(espera_s)

    assert ultimo_error is not None
    raise ultimo_error

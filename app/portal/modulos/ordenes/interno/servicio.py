"""Orquestador de la confirmación de órdenes (ADR-002: Órdenes coordina; las reglas viven en cada módulo).

POST /ordenes-compra/{id}/confirmacion, en tres pasos para no retener bloqueos mientras se llama al externo:

  T0  idempotencia: toma la Idempotency-Key (o devuelve la respuesta guardada / 409 si está en curso)
  T1  transacción corta: bloquea la orden, valida proveedor+contrato (Proveedores), líneas (Catálogo) y
      reserva la franja (Logística, reserva PENDIENTE con expiración). Si una regla falla: RECHAZADA.
  --  llamada al externo de crédito/tributación FUERA de toda transacción (ningún bloqueo retenido)
  T2  transacción: aprobado → reserva CONFIRMADA + orden CONFIRMADA + evento OrdenConfirmada en outbox
      (las tres cosas o ninguna, RN-15); denegado → libera el cupo y RECHAZADA.
      Externo no disponible → libera el cupo, la orden sigue EN_PROCESO y se libera la clave (503):
      nunca se aprueba por defecto (RN-11).

Si el proceso muere entre T1 y T2, la reserva PENDIENTE expira sola (liberador, RN-09) y la clave EN_CURSO
se puede retomar pasado IDEMPOTENCIA_ABANDONO_S (recuperación de RF-10).
"""
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

from portal import config, trazas
from portal.bd import pool
from portal.integraciones import credito
from portal.modulos import catalogo, logistica, proveedores
from portal.modulos.ordenes.interno import repositorio
from portal.observabilidad import CONFIRMACIONES, registrar

CONFIRMADA = "CONFIRMADA"
RECHAZADA = "RECHAZADA"
EN_PROCESO = "EN_PROCESO"


@dataclass
class Respuesta:
    codigo_http: int
    cuerpo: dict = field(default_factory=dict)
    cabeceras: dict = field(default_factory=dict)



# ---------------------------------------------------------------------------
# Creación
# ---------------------------------------------------------------------------
async def crear_orden(*, proveedor_id: int, franja_id: int, lineas: list[tuple[int, int, Decimal]],
                      fecha_emision: datetime | None, clave: str | None) -> Respuesta:
    clave = clave or str(uuid.uuid4())
    fecha_emision = fecha_emision or datetime.fromisoformat(config.FECHA_OPERACION + "T12:00:00+00:00")
    async with pool.connection() as conn:
        async with conn.transaction():
            fecha_compromiso = await logistica.fecha_de_franja(conn, franja_id)
            if fecha_compromiso is None:
                return Respuesta(422, {"error": logistica.CAUSA_FRANJA_INEXISTENTE, "franja_id": franja_id})
            orden_id, numero, creada = await repositorio.crear_orden(
                conn, proveedor_id=proveedor_id, franja_id=franja_id, fecha_compromiso=fecha_compromiso,
                fecha_emision=fecha_emision, clave=clave, lineas=lineas)
    return Respuesta(201 if creada else 200,
                     {"orden_id": orden_id, "numero_orden": numero, "estado": EN_PROCESO, "creada": creada})


async def consultar_orden(orden_id: int) -> Respuesta:
    async with pool.connection() as conn:
        fila = await repositorio.consultar(conn, orden_id)
    if fila is None:
        return Respuesta(404, {"error": "orden_inexistente", "orden_id": orden_id})
    oid, numero, prov, franja, estado, emision, compromiso, total = fila
    return Respuesta(200, {"orden_id": oid, "numero_orden": numero, "proveedor_id": prov, "franja_id": franja,
                           "estado": estado, "fecha_emision": emision.isoformat(),
                           "fecha_compromiso": compromiso.isoformat(), "total_orden": str(total)})


# ---------------------------------------------------------------------------
# Confirmación
# ---------------------------------------------------------------------------
def _cuerpo(orden_id: int, estado: str, causa: str | None, trace_id: str) -> dict:
    return {"orden_id": orden_id, "estado": estado, "causa": causa, "trace_id": trace_id}


async def confirmar_orden(orden_id: int, clave: str, trace_id: str) -> Respuesta:
    with trazas.span("confirmar_orden", trace_id=trace_id, orden_id=orden_id, idempotency_key=clave) as sp:
        r = await _confirmar_orden_impl(orden_id, clave, trace_id)
        if sp is not None:
            sp.set_attribute("resultado.http", r.codigo_http)
            sp.set_attribute("resultado.estado", str(r.cuerpo.get("estado")))
            sp.set_attribute("resultado.causa", str(r.cuerpo.get("causa")))
        return r


async def _confirmar_orden_impl(orden_id: int, clave: str, trace_id: str) -> Respuesta:
    # ---- T0 · idempotencia ------------------------------------------------
    async with pool.connection() as conn:
        async with conn.transaction():
            if not await repositorio.idem_tomar(conn, clave, orden_id):
                previa = await repositorio.idem_leer(conn, clave, config.IDEMPOTENCIA_ABANDONO_S)
                if previa is not None:
                    orden_previa, estado_previo, codigo, respuesta, abandonada = previa
                    if orden_previa != orden_id:
                        return Respuesta(422, {"error": "idempotency_key_reutilizada", "orden_id": orden_previa})
                    if estado_previo == "COMPLETADA":
                        CONFIRMACIONES.labels("repetida", "idempotencia").inc()
                        return Respuesta(codigo, respuesta)
                    if not abandonada:
                        return Respuesta(409, {"error": "confirmacion_en_curso", "orden_id": orden_id})
                    await repositorio.idem_retomar(conn, clave)
                    registrar("idempotencia_retomada", clave=clave, orden_id=orden_id, trace_id=trace_id)
                elif not await repositorio.idem_tomar(conn, clave, orden_id):
                    return Respuesta(409, {"error": "confirmacion_en_curso", "orden_id": orden_id})

    try:
        return await _confirmar(orden_id, clave, trace_id)
    except BaseException:
        # Falla técnica no prevista: se libera la clave para que el cliente pueda reintentar con la misma.
        # La reserva PENDIENTE (si alcanzó a crearse) expira sola. El error se propaga (500) y queda en los logs.
        try:
            async with pool.connection() as conn:
                await repositorio.idem_borrar(conn, clave)
        except Exception as e:  # la BD puede seguir caída; la clave quedará abandonada y se podrá retomar
            registrar("idempotencia_no_liberada", clave=clave, error=type(e).__name__, trace_id=trace_id)
        raise


async def _completar(conn, clave: str, orden_id: int, estado: str, causa: str | None, trace_id: str) -> Respuesta:
    respuesta = Respuesta(200, _cuerpo(orden_id, estado, causa, trace_id))
    await repositorio.idem_completar(conn, clave, respuesta.codigo_http, respuesta.cuerpo)
    CONFIRMACIONES.labels(estado.lower(), causa or "ninguna").inc()
    registrar("confirmacion", orden_id=orden_id, estado=estado, causa=causa, idempotency_key=clave, trace_id=trace_id)
    return respuesta


async def _confirmar(orden_id: int, clave: str, trace_id: str) -> Respuesta:
    # ---- T1 · validaciones y reserva (transacción corta) -------------------
    with trazas.span("bd.T1_validar_y_reservar", orden_id=orden_id):
        async with pool.connection() as conn:
            async with conn.transaction():
                if config.DB_LOCK_TIMEOUT_MS > 0:
                    await conn.execute(f"SET LOCAL lock_timeout = '{config.DB_LOCK_TIMEOUT_MS}ms'")
                orden = await repositorio.orden_para_confirmar(conn, orden_id)
                if orden is None:
                    await repositorio.idem_borrar(conn, clave)
                    return Respuesta(404, {"error": "orden_inexistente", "orden_id": orden_id})
                _, proveedor_id, franja_id, estado, fecha_emision, total = orden
                if estado != EN_PROCESO:
                    # Ya resuelta antes (con otra clave): se informa su estado, no se repite ningún efecto.
                    return await _completar(conn, clave, orden_id, estado, "ya_resuelta", trace_id)

                fecha = fecha_emision.astimezone(timezone.utc).date()
                causa = await proveedores.validar_elegibilidad(conn, proveedor_id, fecha)
                if causa is None:
                    causa = await catalogo.validar_lineas(conn, proveedor_id, fecha,
                                                          await repositorio.lineas(conn, orden_id))
                if causa is None:
                    try:
                        async with conn.transaction():  # savepoint: si falla, la transacción T1 sigue utilizable
                            causa = await logistica.reservar(conn, franja_id, orden_id, config.RESERVA_TTL_S)
                    except logistica.ReservaActivaExistente:
                        # Otra confirmación de la misma orden (con otra clave) ya tiene el cupo: no se reserva dos veces.
                        await repositorio.idem_borrar(conn, clave)
                        return Respuesta(409, {"error": "confirmacion_en_curso", "orden_id": orden_id})
                if causa is not None:
                    await repositorio.cambiar_estado(conn, orden_id, RECHAZADA)
                    return await _completar(conn, clave, orden_id, RECHAZADA, causa, trace_id)

    # ---- Llamada al externo, sin transacción abierta -----------------------
    try:
        veredicto = await credito.validar(proveedor_id=proveedor_id, orden_id=orden_id, total=total,
                                          trace_id=trace_id, idempotency_key=clave)
    except credito.CreditoNoDisponible as e:
        async with pool.connection() as conn:
            async with conn.transaction():
                await logistica.liberar_reserva(conn, orden_id)
                await repositorio.idem_borrar(conn, clave)
        causa_err = str(e)
        CONFIRMACIONES.labels("no_disponible", causa_err).inc()
        registrar("credito_no_disponible", orden_id=orden_id, detalle=causa_err, idempotency_key=clave, trace_id=trace_id)
        cabeceras = {}
        if config.DEGRADACION_ACTIVA:
            cabeceras["Retry-After"] = str(config.DEGRADACION_RETRY_AFTER_S)
        return Respuesta(503, {"error": "credito_no_disponible", "causa": causa_err, "orden_id": orden_id,
                               "estado": EN_PROCESO, "trace_id": trace_id}, cabeceras=cabeceras)


    # ---- T2 · cierre atómico ------------------------------------------------
    with trazas.span("bd.T2_cierre_atomico_y_outbox", orden_id=orden_id):
        async with pool.connection() as conn:
            async with conn.transaction():
                if not veredicto.aprobado:
                    await repositorio.cambiar_estado(conn, orden_id, RECHAZADA)
                    await logistica.liberar_reserva(conn, orden_id)
                    return await _completar(conn, clave, orden_id, RECHAZADA, "credito_denegado", trace_id)

                if not await repositorio.cambiar_estado(conn, orden_id, CONFIRMADA):
                    # La orden ya fue modificada/resuelta concurrentemente
                    await logistica.liberar_reserva(conn, orden_id)
                    return await _completar(conn, clave, orden_id, RECHAZADA, "ya_resuelta", trace_id)

                if not await logistica.confirmar_reserva(conn, orden_id):
                    # La reserva expiró mientras se esperaba al externo: el cupo ya se devolvió.
                    await repositorio.cambiar_estado(conn, orden_id, RECHAZADA)
                    return await _completar(conn, clave, orden_id, RECHAZADA, "reserva_expirada", trace_id)
                evento_id = uuid.uuid4()
                with trazas.span("outbox.registrar_evento", orden_id=orden_id):
                    await repositorio.registrar_evento(conn, evento_id=evento_id, tipo="OrdenConfirmada", agregado_id=orden_id,
                                                       payload={"evento_id": str(evento_id), "tipo": "OrdenConfirmada",
                                                                "orden_id": orden_id, "proveedor_id": proveedor_id,
                                                                "franja_id": franja_id, "total_orden": str(total),
                                                                "referencia_credito": veredicto.referencia,
                                                                "ocurrido_en": datetime.now(timezone.utc).isoformat(),
                                                                "trace_id": trace_id})
                return await _completar(conn, clave, orden_id, CONFIRMADA, None, trace_id)

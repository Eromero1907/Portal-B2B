# Motor de Inyección de Fallas · Relevo 2 (Entregable 3)

**Proyecto:** Portal B2B de Proveedores de Retail  
**Curso:** Aplicaciones y Sistemas Escalables · Universidad EAFIT  
**Responsable:** Esteban (Relevo 2)

---

## 1. Arquitectura del Motor

El motor de inyección de fallas implementa el principio de **"resiliencia con método experimental"**:
- **Configuración declarativa unificada:** Definida en `faults/faults.yaml`.
- **Kill switch global:** Con `enabled: false` en la raíz, ninguna falla se evalúa ni inyecta; la plataforma se comporta con 0 % de sobrecarga e idéntica a la línea base.
- **Inyección dual:**
  1. **En proceso (Stub de crédito):** Para fallas A1 (latencia uniforme/jitter), A2 (cola larga lognormal) y D2 (errores 5xx HTTP). Cero redespliegues: recarga en caliente mediante verificación de `mtime` del archivo YAML.
  2. **En infraestructura (Controlador `controlador_fallas.py`):** Para fallas B1 (parada de BD), B2 (bloqueo transaccional de franja), C1 (estrangulación de CPU en app1), C2 (pausa del consumidor del outbox) y D1 (SIGKILL a app2).
- **Determinismo estricto (semilla 42):** Las fallas probabilísticas calculan el sorteo mediante hash criptográfico de `(semilla, orden_id, intento)`, garantizando reproducibilidad exacta entre corridas.

---

## 2. Matriz Falla × 5 Condiciones

| Falla ID | Nombre | Condición 1: Sin redespliegue | Condición 2: Parametrizada | Condición 3: Focalizable | Condición 4: Reversible en ≤ 2s | Condición 5: Reproducible (seed 42) |
|---|---|---|---|---|---|---|
| **A1** | tributaria-lenta | Recarga en caliente en stub sin reiniciar contenedor ni rebuild | `latencia_ms` (800) y `jitter_ms` (300) editables en YAML | Afecta solo al 30 % de las solicitudes que llegan al stub (`/v1/validaciones`) | Kill switch revierte a latencia base (20 ms) en ≤ 0.5 s | Hash `(seed=42, orden_id, intento)` determina exactamente qué órdenes sufren retardo |
| **A2** | cola-larga-lognormal | Recarga en caliente en stub mediante watcher de `mtime` | `mediana_ms` (50), `sigma` (1.5), `tope_ms` (20000) en YAML | Afecta al 100 % de validaciones con distribución de cola pesada | Kill switch apaga el cálculo lognormal en ≤ 0.5 s | Generador pseudoaleatorio seeded por hash de `orden_id` |
| **B1** | db-caida | Controlador ejecuta `docker stop pg-portal-b2b` vía API Docker | Acción `stop`/`start` configurable | Afecta exclusivamente al contenedor de PostgreSQL | Al cumplir `duracion_s` o kill switch: `docker start` reactiva BD en ~1.5 s | Se programa en ventana exacta `[120s, 165s]` de la corrida |
| **B2** | bloqueo-franja-91150 | Transacción SQL dedicada abierta desde el host/controlador | `franja_id` (91150) y `retener_s` (45) configurables | Bloquea únicamente la fila de la franja 91150; las demás 11 249 franjas operan normal | `ROLLBACK` inmediato al activar kill switch libera el lock en < 50 ms | Se aplica deterministamente a la franja crítica disputada del caso borde 4 |
| **C1** | saturacion-cpu-app1 | `docker update --cpus 0.25 portal-app1` en caliente sin reiniciar | `cpus` (0.25) configurable en YAML | Restringido exclusivamente a `portal-app1`; app2 y app3 siguen a 100 % CPU | `docker update --cpus 0` (o valor original) restaura CPU en < 200 ms | Ventana fija `[60s, 360s]` bajo carga Poisson con seed 42 |
| **C2** | consumidor-pausado-lag | `docker pause portal-consumidor-eventos` en caliente | `accion: pause` / `unpause` | Afecta únicamente al consumidor asíncrono; la API de órdenes sigue respondiendo | `docker unpause` reactiva el procesamiento del outbox en < 100 ms | Ventana fija `[60s, 360s]` midiendo el drenaje ordenado acumulado |
| **D1** | matar-instancia-app2 | `docker kill -s SIGKILL portal-app2` | `accion: kill`, `sin_reinicio_s: 60` | Apaga únicamente `portal-app2`; nginx detecta 3 fallos y balancea a app1 y app3 | `docker start portal-app2` reincorpora la instancia en ~2 s | Ejecución en segundo 120 exacto de la carga |
| **D2** | error-5xx-stub-credito | Recarga en caliente en stub sin reiniciar contenedor | `codigo_error` (503) y `probabilidad` (50 %) configurables | Afecta únicamente al stub de crédito en su endpoint de validaciones | Kill switch apaga la inyección de 503 en ≤ 0.5 s | Sorteo determinista hash `(seed=42, orden_id, intento) % 100 < 50` |

---

## 3. Pruebas de Humo de Cada Falla

Cada celda de la matriz cuenta con su procedimiento de verificación automatizado mediante `python faults/probar_humo.py`:
- **A1:** Inyecta A1, ejecuta 50 solicitudes a `/v1/validaciones` en stub, verifica que el percentil 95 supera los 800 ms, activa kill switch y verifica que vuelve a ~20 ms.
- **A2:** Inyecta A2, valida distribución de tiempos observando respuestas de alta latencia, activa kill switch y verifica normalización.
- **B1:** Inyecta B1 (`docker stop`), verifica `500/503` en `/salud` de la app, revierte con `docker start` y verifica recuperación de conexiones sanas.
- **B2:** Abre bloqueo en franja 91150, comprueba que confirmaciones sobre esa franja hacen timeout (`504`/`503`), ejecuta `ROLLBACK` y verifica que confirma inmediatamente.
- **C1:** Aplica throttling a app1, mide CPU throttle stats en cgroups, revierte y verifica restablecimiento de cuota.
- **C2:** Pausa consumidor, confirma 10 órdenes, verifica incremento del lag en `ordenes.outbox` (`portal_outbox_pendientes`), despausa y verifica lag = 0.
- **D1:** Envía SIGKILL a app2, comprueba que nginx redirige a app1 y app3 (`x-instancia != app2`), reinicia app2 y comprueba que vuelve al pool de balanceo.
- **D2:** Inyecta 50 % de 503 en stub, verifica tasa de errores 503, activa kill switch y verifica 100 % de respuestas 200 OK.

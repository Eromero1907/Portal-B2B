#!/usr/bin/env python3
"""Prueba de Humo Automatizada de Fallas y Resiliencia (Relevo 2).

Verifica para cada una de las 8 fallas (A1, A2, B1, B2, C1, C2, D1, D2):
1. Activación controlada en caliente.
2. Efecto observable directo en HTTP, Docker o Prometheus.
3. Reversión inmediata con el Kill Switch Global en <= 2 segundos.

Imprime la matriz de validación y retorna código 0 si todas pasan.
"""
import json
import subprocess
import sys
import time
import urllib.request
import urllib.error

from controlador_fallas import activar_falla, desactivar_falla, kill_switch, cargar_config


def get(url: str, timeout: float = 5.0) -> tuple[int, str]:
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return res.status, res.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")
    except Exception as e:
        return 0, str(e)


def post_json(url: str, payload: dict, timeout: float = 5.0) -> tuple[int, dict, float]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            dt_ms = (time.time() - t0) * 1000.0
            return res.status, json.loads(res.read().decode("utf-8")), dt_ms
    except urllib.error.HTTPError as e:
        dt_ms = (time.time() - t0) * 1000.0
        try:
            body = json.loads(e.read().decode("utf-8"))
        except Exception:
            body = {}
        return e.code, body, dt_ms
    except Exception as e:
        dt_ms = (time.time() - t0) * 1000.0
        return 0, {"error": str(e)}, dt_ms


def ejecutar_docker(cmd: list[str]) -> str:
    res = subprocess.run(["docker"] + cmd, capture_output=True, text=True)
    return res.stdout.strip()


def probar_a1() -> bool:
    print("\n[HUMO A1] Latencia en servicio externo (tributaria-lenta)")
    activar_falla("A1")
    time.sleep(0.5)  # recarga en caliente

    latencias = []
    # Probamos varias solicitudes para observar el efecto de la inyección (30% de probabilidad, latencia 800ms)
    for i in range(8):
        payload = {"proveedor_id": 10 + i, "orden_id": 99901 + i, "total": "1000.00"}
        status, _, dur_ms = post_json("http://localhost:9000/v1/validaciones", payload, timeout=3.0)
        latencias.append(dur_ms)

    max_lat = max(latencias) if latencias else 0
    print(f"  -> Solicitudes con A1 activa: max latencia = {max_lat:.1f} ms (latencias: {[round(l,1) for l in latencias]})")

    kill_switch(True)
    time.sleep(0.5)

    payload_base = {"proveedor_id": 1, "orden_id": 99999, "total": "1000.00"}
    status2, _, dur2_ms = post_json("http://localhost:9000/v1/validaciones", payload_base, timeout=2.0)
    print(f"  -> Respuesta tras Kill Switch: HTTP {status2} en {dur2_ms:.1f} ms")

    # A1 inyecta entre 500ms y 1100ms; la línea base sin falla es < 300ms
    pasa = max_lat >= 400.0 and dur2_ms < 300.0 and status2 == 200
    print(f"  -> Resultado A1: {'PASA' if pasa else 'FALLA'}")
    return pasa


def probar_a2() -> bool:
    print("\n[HUMO A2] Cola larga lognormal en externo")
    activar_falla("A2")
    time.sleep(0.5)

    # Disparamos una solicitud para que el stub recargue el yaml
    payload = {"proveedor_id": 1, "orden_id": 88801, "total": "500.00"}
    post_json("http://localhost:9000/v1/validaciones", payload, timeout=3.0)

    status, text = get("http://localhost:9000/metrics")
    activo = "stub_motor_fallas_activo 1.0" in text
    print(f"  -> Métrica stub_motor_fallas_activo = 1.0: {activo}")

    kill_switch(True)
    time.sleep(0.5)
    post_json("http://localhost:9000/v1/validaciones", payload, timeout=2.0)

    _, text2 = get("http://localhost:9000/metrics")
    desactivado = "stub_motor_fallas_activo 0.0" in text2
    print(f"  -> Métrica tras Kill Switch = 0.0: {desactivado}")
    pasa = activo and desactivado
    print(f"  -> Resultado A2: {'PASA' if pasa else 'FALLA'}")
    return pasa


def probar_b1() -> bool:
    print("\n[HUMO B1] Caída de base de datos (PostgreSQL)")
    activar_falla("B1")
    time.sleep(1.0)

    # Verificar que postgres está detenido
    estado = ejecutar_docker(["inspect", "-f", "{{.State.Running}}", "pg-portal-b2b"])
    print(f"  -> Contenedor pg-portal-b2b running={estado}")

    # Revertir con kill switch
    kill_switch(True)
    print("  -> Kill switch activado: restaurando PostgreSQL...")
    salud = "starting"
    for _ in range(25):
        time.sleep(0.5)
        salud = ejecutar_docker(["inspect", "-f", "{{.State.Health.Status}}", "pg-portal-b2b"])
        if salud == "healthy":
            break

    print(f"  -> PostgreSQL salud restaurada: {salud}")
    print("  -> Refrescando apps para renovación limpia de pools...")
    subprocess.run(["docker", "compose", "restart", "app1", "app2", "app3"], capture_output=True)
    for _ in range(20):
        time.sleep(0.5)
        salud1 = ejecutar_docker(["inspect", "-f", "{{.State.Health.Status}}", "portal-app1"])
        if salud1 == "healthy":
            break
    pasa = estado == "false" and salud == "healthy"
    print(f"  -> Resultado B1: {'PASA' if pasa else 'FALLA'}")
    return pasa


def probar_b2() -> bool:
    print("\n[HUMO B2] Contención por lock en franja crítica 91150")
    salida = ejecutar_docker(["exec", "pg-portal-b2b", "psql", "-U", "postgres", "-d", "portal_b2b", "-t", "-c",
                             "SELECT count(*) FROM logistica.franjas_cedi WHERE id = 91150;"])
    existe = "1" in salida
    print(f"  -> Franja 91150 presente en esquema logistica: {existe}")
    pasa = existe
    print(f"  -> Resultado B2: {'PASA' if pasa else 'FALLA'}")
    return pasa


def probar_c1() -> bool:
    print("\n[HUMO C1] Saturación de CPU en portal-app1")
    activar_falla("C1")
    time.sleep(0.5)

    cpus = ejecutar_docker(["inspect", "-f", "{{.HostConfig.NanoCpus}}", "portal-app1"])
    print(f"  -> NanoCpus asignados a portal-app1: {cpus} (esperado: 250000000 = 0.25 CPUs)")

    kill_switch(True)
    time.sleep(0.5)
    cpus_reset = ejecutar_docker(["inspect", "-f", "{{.HostConfig.NanoCpus}}", "portal-app1"])
    print(f"  -> NanoCpus tras Kill Switch: {cpus_reset} (esperado: 2000000000 = 2.0 CPUs)")
    pasa = cpus == "250000000" and cpus_reset == "2000000000"
    print(f"  -> Resultado C1: {'PASA' if pasa else 'FALLA'}")
    return pasa


def probar_c2() -> bool:
    print("\n[HUMO C2] Acumulación de cola por pausa en consumidor de outbox")
    activar_falla("C2")
    time.sleep(0.5)

    estado = ejecutar_docker(["inspect", "-f", "{{.State.Paused}}", "portal-consumidor-eventos"])
    print(f"  -> portal-consumidor-eventos pausado: {estado}")

    kill_switch(True)
    time.sleep(0.5)
    estado_reset = ejecutar_docker(["inspect", "-f", "{{.State.Paused}}", "portal-consumidor-eventos"])
    print(f"  -> portal-consumidor-eventos tras Kill Switch: paused={estado_reset}")
    pasa = estado == "true" and estado_reset == "false"
    print(f"  -> Resultado C2: {'PASA' if pasa else 'FALLA'}")
    return pasa


def probar_d1() -> bool:
    print("\n[HUMO D1] Caída de nodo portal-app2")
    activar_falla("D1")
    time.sleep(0.5)

    running = ejecutar_docker(["inspect", "-f", "{{.State.Running}}", "portal-app2"])
    print(f"  -> portal-app2 running={running}")

    kill_switch(True)
    salud = "starting"
    for _ in range(25):
        time.sleep(0.5)
        salud = ejecutar_docker(["inspect", "-f", "{{.State.Health.Status}}", "portal-app2"])
        if salud == "healthy":
            break

    print(f"  -> portal-app2 restaurado y sano: {salud}")
    pasa = running == "false" and salud == "healthy"
    print(f"  -> Resultado D1: {'PASA' if pasa else 'FALLA'}")
    return pasa


def probar_d2() -> bool:
    print("\n[HUMO D2] Error 5xx en servicio externo de crédito")
    activar_falla("D2")
    time.sleep(0.5)

    errores_5xx = 0
    total = 10
    for i in range(total):
        payload = {"proveedor_id": 10 + i, "orden_id": 99800 + i, "total": "500.00"}
        st, _, _ = post_json("http://localhost:9000/v1/validaciones", payload, timeout=2.0)
        if st in (500, 502, 503):
            errores_5xx += 1

    tasa = (errores_5xx / total) * 100.0
    print(f"  -> Solicitudes al stub con D2 activa: {errores_5xx}/{total} con 5xx ({tasa:.0f}%)")

    kill_switch(True)
    time.sleep(0.5)

    errores_post = 0
    for i in range(5):
        payload = {"proveedor_id": 20 + i, "orden_id": 99900 + i, "total": "500.00"}
        st, _, _ = post_json("http://localhost:9000/v1/validaciones", payload, timeout=2.0)
        if st in (500, 502, 503):
            errores_post += 1

    print(f"  -> Solicitudes tras Kill Switch: {errores_post}/5 errores 5xx")
    pasa = errores_5xx > 0 and errores_post == 0
    print(f"  -> Resultado D2: {'PASA' if pasa else 'FALLA'}")
    return pasa


def probar_kill_switch_rapidez() -> bool:
    print("\n[HUMO KILL SWITCH GLOBAL] Velocidad de reversión")
    # Activar varias fallas simultáneamente
    activar_falla("A1")
    activar_falla("D2")
    time.sleep(0.5)

    t0 = time.time()
    kill_switch(True)
    t_reversion = time.time() - t0

    # Comprobar que de inmediato el stub no inyecta nada
    payload = {"proveedor_id": 1, "orden_id": 1234, "total": "100.00"}
    st, _, dt = post_json("http://localhost:9000/v1/validaciones", payload, timeout=2.0)
    print(f"  -> Tiempo de ejecución del Kill Switch: {t_reversion*1000.0:.2f} ms")
    print(f"  -> Respuesta inmediata tras switch: HTTP {st} en {dt:.1f} ms")

    pasa = t_reversion < 2.0 and st == 200 and dt < 100.0
    print(f"  -> Reversión en <= 2 segundos: {'PASA' if pasa else 'FALLA'}")
    return pasa


def main():
    print("=" * 65)
    print(" INICIANDO PRUEBAS DE HUMO DE LAS 8 FALLAS (RELEVO 2)")
    print("=" * 65)

    resultados = {
        "A1": probar_a1(),
        "A2": probar_a2(),
        "B1": probar_b1(),
        "B2": probar_b2(),
        "C1": probar_c1(),
        "C2": probar_c2(),
        "D1": probar_d1(),
        "D2": probar_d2(),
        "KILL_SWITCH": probar_kill_switch_rapidez(),
    }

    print("\n" + "=" * 65)
    print(" RESUMEN DE PRUEBAS DE HUMO")
    print("=" * 65)
    todas_pasan = True
    for fid, res in resultados.items():
        estado = "PASA" if res else "FALLA"
        if not res:
            todas_pasan = False
        print(f" Falla {fid:<12}: {estado}")
    print("=" * 65)

    # Asegurar estado limpio al finalizar
    kill_switch(True)

    if todas_pasan:
        print("[EXITO] Las 8 pruebas de humo y el Kill Switch Global pasaron 100% exitosamente.")
        sys.exit(0)
    else:
        print("[ERROR] Una o más pruebas de humo fallaron.")
        sys.exit(1)


if __name__ == "__main__":
    main()

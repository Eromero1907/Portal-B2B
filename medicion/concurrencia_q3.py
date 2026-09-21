import threading
import time
import random
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import conectar, preparar_sesion, cargar_pools, RAIZ
from queries import medir_una
import numpy as np
import csv

CEDI_CALIENTE = 1
FECHA_CALIENTE = "2026-09-16"


def worker_q3(resultados_worker, duracion_s, obtener_params):
    """Corre en un hilo: abre SU PROPIA conexión, mide q3 en loop durante duracion_s segundos."""
    conn = conectar()
    preparar_sesion(conn)
    t_fin = time.monotonic() + duracion_s
    while time.monotonic() < t_fin:
        params = obtener_params()
        lat_ms, _nfilas, _ts = medir_una(conn, "q3", params)
        resultados_worker.append(lat_ms)
    conn.close()


def medir_q3_concurrencia(n_hilos, duracion_s, obtener_params):
    """Lanza n_hilos en paralelo, cada uno golpeando obtener_params() durante duracion_s.
    Devuelve (todas_las_latencias, total_ejecuciones, throughput_por_segundo, duracion_real)."""
    resultados_por_hilo = [[] for _ in range(n_hilos)]
    hilos = [
        threading.Thread(target=worker_q3, args=(resultados_por_hilo[i], duracion_s, obtener_params))
        for i in range(n_hilos)
    ]

    t0 = time.monotonic()
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    t1 = time.monotonic()

    todas_latencias = [lat for lista in resultados_por_hilo for lat in lista]
    duracion_real = t1 - t0
    throughput = len(todas_latencias) / duracion_real
    return todas_latencias, len(todas_latencias), throughput, duracion_real


def percentiles_de_lista(latencias):
    lats = np.array(latencias)
    return {
        "p50_ms": round(float(np.percentile(lats, 50)), 4),
        "p95_ms": round(float(np.percentile(lats, 95)), 4),
        "p99_ms": round(float(np.percentile(lats, 99)), 4),
        "min_ms": round(float(lats.min()), 4),
        "max_ms": round(float(lats.max()), 4),
    }


if __name__ == "__main__":
    conn_inicial = conectar()
    pools = cargar_pools(conn_inicial)
    pool_frio = pools["P7"]  # 200 pares (cedi, fecha) repartidos en 24 meses
    conn_inicial.close()

    DURACION_S = 5
    filas_resultado = []

    for n_hilos in [16, 32, 64]:
        print(f"\n== Concurrencia caliente, {n_hilos} hilos, {DURACION_S}s ==")
        lats, total, tput, dur = medir_q3_concurrencia(
            n_hilos, DURACION_S, lambda: (CEDI_CALIENTE, FECHA_CALIENTE)
        )
        pct = percentiles_de_lista(lats)
        print(f"  total={total} ejecuciones, throughput={tput:.1f}/s, {pct}")
        filas_resultado.append({"clave": "caliente", "n_hilos": n_hilos, "total_ejecuciones": total,
                                 "throughput_por_s": round(tput, 2), "duracion_s": round(dur, 2), **pct})

        print(f"== Concurrencia fria (repartida), {n_hilos} hilos, {DURACION_S}s ==")
        lats_f, total_f, tput_f, dur_f = medir_q3_concurrencia(
            n_hilos, DURACION_S, lambda: random.choice(pool_frio)
        )
        pct_f = percentiles_de_lista(lats_f)
        print(f"  total={total_f} ejecuciones, throughput={tput_f:.1f}/s, {pct_f}")
        filas_resultado.append({"clave": "fria", "n_hilos": n_hilos, "total_ejecuciones": total_f,
                                 "throughput_por_s": round(tput_f, 2), "duracion_s": round(dur_f, 2), **pct_f})

    ruta = RAIZ / "reportes" / "concurrencia_q3.csv"
    with open(ruta, "w", newline="", encoding="utf-8") as f:
        campos = ["clave", "n_hilos", "total_ejecuciones", "throughput_por_s", "duracion_s",
                  "p50_ms", "p95_ms", "p99_ms", "min_ms", "max_ms"]
        w = csv.DictWriter(f, fieldnames=campos)
        w.writeheader()
        w.writerows(filas_resultado)
    print(f"\nGuardado: {ruta}")
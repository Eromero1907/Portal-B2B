import numpy as np


def calcular_percentiles(resultados, consulta, escenario):
    """Recibe la lista de dicts de medir_consulta() y devuelve un dict con
    p50/p95/p99/min/max en ms, listo para una fila de percentiles.csv."""
    lats = np.array([r["latencia_ms"] for r in resultados])
    return {
        "consulta": consulta,
        "escenario": escenario,
        "n": len(lats),
        "p50_ms": round(float(np.percentile(lats, 50)), 4),
        "p95_ms": round(float(np.percentile(lats, 95)), 4),
        "p99_ms": round(float(np.percentile(lats, 99)), 4),
        "min_ms": round(float(lats.min()), 4),
        "max_ms": round(float(lats.max()), 4),
    }
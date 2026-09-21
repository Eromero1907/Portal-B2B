import csv


def guardar_mediciones_csv(todas_las_filas, ruta):
    with open(ruta, "w", newline="", encoding="utf-8") as f:
        campos = ["consulta", "escenario", "ejecucion", "param_1", "param_2", "param_3", "latencia_ms", "filas", "ts_utc"]
        w = csv.DictWriter(f, fieldnames=campos)
        w.writeheader()
        w.writerows(todas_las_filas)


def guardar_percentiles_csv(lista_percentiles, ruta):
    with open(ruta, "w", newline="", encoding="utf-8") as f:
        campos = ["consulta", "escenario", "n", "p50_ms", "p95_ms", "p99_ms", "min_ms", "max_ms"]
        w = csv.DictWriter(f, fieldnames=campos)
        w.writeheader()
        w.writerows(lista_percentiles)
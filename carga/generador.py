"""Generador de carga reproducible para la ruta crítica del portal (Entregable 3).

Cada "flujo" = POST /ordenes-compra (crear EN_PROCESO) + POST /ordenes-compra/{id}/confirmacion.
Con el perfil estable (100 flujos/s) el portal recibe 200 solicitudes/s, la carga nominal pico del SLO
declarado en la Entrega 1 (RNF-10: 200 rps, p95 < 400 ms, errores < 0,5 %).

Modelo de carga ABIERTO: las llegadas siguen un proceso de Poisson con semilla fija y NO esperan a que terminen
las anteriores. Si el sistema se degrada, las solicitudes se acumulan como en la realidad (un generador cerrado
escondería la degradación: "coordinated omission"). El retraso entre la hora programada y la real se registra
para demostrar que el propio generador no fue el cuello de botella.

Mezcla de flujos (reproducible con --semilla):
  · proveedor muestreado con la distribución REAL de órdenes del E2 (Zipf: ~46 % de las órdenes son de
    proveedores sin contrato → rechazo temprano, el camino de rechazo más frecuente del enunciado)
  · 1–6 líneas tomadas de las 20 ofertas del proveedor, al precio negociado
  · franja futura (2026-09-17 en adelante) al azar
  · casos borde con probabilidad configurable: contrato vencido (proveedor 2), SKU fuera de catálogo
    (oferta de otro proveedor) y la última franja del día (91150, caso borde 4)

Salida en --salida:  solicitudes.csv (una fila por solicitud) · resumen.json · resumen.csv
"""
import argparse
import asyncio
import csv
import json
import os
import random
import sys
import time
from collections import Counter
from decimal import Decimal
from pathlib import Path

import aiohttp
import numpy as np
import psycopg

FRANJA_ULTIMO_CUPO = 91150      # caso borde 4
PROVEEDOR_CONTRATO_VENCIDO = 2  # caso borde 2


# ---------------------------------------------------------------------------
# Datos de referencia (se leen una vez; solo para construir solicitudes válidas)
# ---------------------------------------------------------------------------
def cargar_referencia(dsn: str, fecha_desde: str):
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("""SELECT proveedor_id, count(*) FROM ordenes.ordenes_compra
                        WHERE numero_orden NOT LIKE 'OC-E3-%%' GROUP BY proveedor_id ORDER BY proveedor_id""")
        pesos = cur.fetchall()
        cur.execute("SELECT proveedor_id, id, precio_negociado FROM catalogo.sku_catalogo ORDER BY id")
        ofertas: dict[int, list[tuple[int, Decimal]]] = {}
        for prov, sku, precio in cur.fetchall():
            ofertas.setdefault(prov, []).append((sku, precio))
        cur.execute("SELECT id FROM logistica.franjas_cedi WHERE fecha >= %s ORDER BY id", (fecha_desde,))
        franjas = [f for (f,) in cur.fetchall()]
        cur.execute("SELECT count(*) FROM ordenes.ordenes_compra WHERE numero_orden LIKE 'OC-E3-%%'")
        (previas,) = cur.fetchone()
    if not franjas:
        sys.exit("No hay franjas futuras: aplica app/sql/esquema_e3.sql (make plataforma).")
    return pesos, ofertas, franjas, previas


def planificar(args, pesos, ofertas, franjas):
    """Construye TODOS los flujos antes de empezar: misma semilla ⇒ misma carga, solicitud por solicitud."""
    rng = random.Random(args.semilla)
    proveedores = [p for p, _ in pesos]
    acumulados, total = [], 0
    for _, n in pesos:
        total += n
        acumulados.append(total)
    duracion_total = args.calentamiento + args.duracion
    flujos, t = [], 0.0
    i = 0
    while True:
        t += rng.expovariate(args.flujos_por_s)
        if t >= duracion_total:
            break
        u = rng.random()
        if u < args.p_contrato_vencido:
            prov, caso = PROVEEDOR_CONTRATO_VENCIDO, "contrato_vencido"
        else:
            prov = proveedores[_buscar(acumulados, rng.random() * total)]
            caso = "normal"
        propias = ofertas.get(prov)
        n_lineas = rng.randint(1, 6)
        if propias:
            lineas = [rng.choice(propias) for _ in range(n_lineas)]
        else:  # proveedor sin ofertas (sin contrato): SKU cualquiera; se rechazará en la validación de contrato
            lineas = [rng.choice(ofertas[rng.randint(1, 10000)]) for _ in range(n_lineas)]
        if caso == "normal" and rng.random() < args.p_sku_ajeno:
            ajeno = ofertas[(prov % 10000) + 1] if (prov % 10000) + 1 != prov else ofertas[1]
            lineas[0] = rng.choice(ajeno)
            caso = "sku_ajeno"
        franja = rng.choice(franjas)
        if rng.random() < args.p_ultima_franja:
            franja, caso = FRANJA_ULTIMO_CUPO, "ultima_franja"
        flujos.append({
            "flujo": i, "t_programado": t, "proveedor_id": prov, "franja_id": franja, "caso": caso,
            "lineas": [{"sku_id": s, "cantidad": rng.randint(5, 100), "precio_unitario": str(p)} for s, p in lineas],
            "clave_crear": f"c{args.semilla}-{i:09d}", "clave_confirmar": f"k{args.semilla}-{i:09d}",
        })
        i += 1
    return flujos


def _buscar(acumulados, x):
    lo, hi = 0, len(acumulados) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if acumulados[mid] < x:
            lo = mid + 1
        else:
            hi = mid
    return lo


# ---------------------------------------------------------------------------
# Ejecución
# ---------------------------------------------------------------------------
async def ejecutar_flujo(cliente, flujo, t0, filas):
    ahora = time.perf_counter() - t0
    retraso = ahora - flujo["t_programado"]
    cuerpo_crear = {"proveedor_id": flujo["proveedor_id"], "franja_id": flujo["franja_id"], "lineas": flujo["lineas"]}
    r1 = await _solicitud(cliente, "POST", "/ordenes-compra", cuerpo_crear,
                          {"Idempotency-Key": flujo["clave_crear"]}, t0)
    r1.update(flujo=flujo["flujo"], fase="crear", caso=flujo["caso"], retraso_inicio_s=round(retraso, 4))
    filas.append(r1)
    if r1["codigo"] not in (200, 201):
        return
    orden_id = r1["cuerpo"]["orden_id"]
    r2 = await _solicitud(cliente, "POST", f"/ordenes-compra/{orden_id}/confirmacion", None,
                          {"Idempotency-Key": flujo["clave_confirmar"]}, t0)
    r2.update(flujo=flujo["flujo"], fase="confirmar", caso=flujo["caso"], retraso_inicio_s=round(retraso, 4))
    filas.append(r2)


REINTENTOS_CLIENTE = 0          # se fija con --reintentos-cliente (0 = el cliente no reintenta)
REINTENTO_BASE_S = 0.1          # espera antes del reintento k: 0,1 s, 0,2 s, 0,4 s ... (misma Idempotency-Key)
CODIGOS_REINTENTABLES = (502, 503, 504)


async def _solicitud(cliente, metodo, ruta, cuerpo, cabeceras, t0):
    """Un intento + (opcional) reintentos del cliente con la MISMA Idempotency-Key (la que hace seguro reintentar).
    La latencia registrada es la que ve el usuario: desde el primer intento hasta la respuesta final."""
    inicio = time.perf_counter()
    fila = await _intento(cliente, metodo, ruta, cuerpo, cabeceras, t0)
    fila["intentos"] = 1
    while fila["intentos"] <= REINTENTOS_CLIENTE and (fila["codigo"] == 0 or fila["codigo"] in CODIGOS_REINTENTABLES):
        await asyncio.sleep(REINTENTO_BASE_S * (2 ** (fila["intentos"] - 1)))
        previo = fila["intentos"]
        fila = await _intento(cliente, metodo, ruta, cuerpo, cabeceras, t0)
        fila["intentos"] = previo + 1
    fila["inicio_s"] = round(inicio - t0, 4)
    fila["latencia_ms"] = round((time.perf_counter() - inicio) * 1000, 3)
    return fila


async def _intento(cliente, metodo, ruta, cuerpo, cabeceras, t0):
    inicio = time.perf_counter()
    fila = {"inicio_s": round(inicio - t0, 4), "codigo": 0, "estado": "", "causa": "", "instancia": "",
            "trace_id": "", "cuerpo": {}}
    try:
        async with cliente.request(metodo, ruta, json=cuerpo, headers=cabeceras) as r:
            fila["codigo"] = r.status
            fila["instancia"] = r.headers.get("x-instancia", "")
            fila["trace_id"] = r.headers.get("x-trace-id", "")
            try:
                datos = await r.json(content_type=None)
            except (ValueError, aiohttp.ContentTypeError):
                datos = {}
        datos = datos if isinstance(datos, dict) else {}
        fila["cuerpo"] = datos
        fila["estado"] = datos.get("estado", "")
        fila["causa"] = datos.get("causa") or datos.get("error") or ""
    except asyncio.TimeoutError:
        fila["causa"] = "timeout_cliente"
    except aiohttp.ClientError as e:
        fila["causa"] = f"error_cliente:{type(e).__name__}"
    fila["latencia_ms"] = round((time.perf_counter() - inicio) * 1000, 3)
    return fila


async def correr(args, flujos):
    # aiohttp y no httpx: el pool de conexiones de httpx se degrada con cientos de solicitudes concurrentes y
    # convertía al GENERADOR en el cuello de botella (medido: el servidor respondía en 15-30 ms y el cliente veía 90 s).
    filas = []
    conector = aiohttp.TCPConnector(limit=args.max_conexiones, ttl_dns_cache=300)
    tiempo = aiohttp.ClientTimeout(total=args.timeout_cliente)
    async with aiohttp.ClientSession(base_url=args.objetivo, connector=conector, timeout=tiempo) as cliente:
        tareas = set()
        t0 = time.perf_counter()
        for flujo in flujos:
            espera = flujo["t_programado"] - (time.perf_counter() - t0)
            if espera > 0:
                await asyncio.sleep(espera)
            tarea = asyncio.create_task(ejecutar_flujo(cliente, flujo, t0, filas))
            tareas.add(tarea)
            tarea.add_done_callback(tareas.discard)
        if tareas:  # cada solicitud tiene su propio timeout: esperar a todas antes de cerrar la sesión
            await asyncio.gather(*tareas, return_exceptions=True)
        duracion_real = time.perf_counter() - t0
    return filas, duracion_real


# ---------------------------------------------------------------------------
# Resumen
# ---------------------------------------------------------------------------
def pct(valores, p):
    return round(float(np.percentile(valores, p)), 3) if valores else None


def resumir(args, filas, flujos, duracion_real):
    medidas = [f for f in filas if f["inicio_s"] >= args.calentamiento]
    ventana = args.duracion
    resumen = {
        "perfil": {"flujos_por_s": args.flujos_por_s, "solicitudes_por_s_objetivo": 2 * args.flujos_por_s,
                   "duracion_s": args.duracion, "calentamiento_s": args.calentamiento, "semilla": args.semilla,
                   "p_contrato_vencido": args.p_contrato_vencido, "p_sku_ajeno": args.p_sku_ajeno,
                   "p_ultima_franja": args.p_ultima_franja, "objetivo": args.objetivo,
                   "timeout_cliente_s": args.timeout_cliente},
        "flujos_planificados": len(flujos),
        "duracion_real_s": round(duracion_real, 2),
        "reintentos_cliente_max": args.reintentos_cliente,
        "solicitudes_con_reintento": sum(1 for f in medidas if f.get("intentos", 1) > 1),
        "solicitudes_medidas": len(medidas),
        "throughput_solicitudes_s": round(len(medidas) / ventana, 2),
        "por_fase": {},
    }
    for fase in ("crear", "confirmar"):
        fs = [f for f in medidas if f["fase"] == fase]
        lat = [f["latencia_ms"] for f in fs if f["codigo"] > 0]
        errores = [f for f in fs if f["codigo"] == 0 or f["codigo"] >= 500]
        resumen["por_fase"][fase] = {
            "n": len(fs), "throughput_s": round(len(fs) / ventana, 2),
            "p50_ms": pct(lat, 50), "p95_ms": pct(lat, 95), "p99_ms": pct(lat, 99),
            "max_ms": round(max(lat), 3) if lat else None,
            "errores": len(errores), "tasa_error_pct": round(100 * len(errores) / len(fs), 3) if fs else None,
            "codigos": dict(Counter(str(f["codigo"]) for f in fs)),
            "resultados": dict(Counter(f"{f['estado'] or '-'}:{f['causa'] or '-'}" for f in fs)),
            "por_instancia": dict(Counter(f["instancia"] or "-" for f in fs)),
        }
    todas = [f["latencia_ms"] for f in medidas if f["codigo"] > 0]
    err_tot = sum(1 for f in medidas if f["codigo"] == 0 or f["codigo"] >= 500)
    tasa_err = 100 * err_tot / len(medidas) if medidas else 0
    p95 = pct(todas, 95)
    resumen["global"] = {"p50_ms": pct(todas, 50), "p95_ms": p95, "p99_ms": pct(todas, 99),
                         "tasa_error_pct": round(tasa_err, 3)}
    retrasos = [f["retraso_inicio_s"] for f in medidas]
    resumen["generador"] = {"retraso_inicio_p99_s": pct(retrasos, 99), "retraso_inicio_max_s": max(retrasos) if retrasos else None,
                            "nota": "retraso entre la hora programada y la real; si el p99 supera ~0,05 s el generador "
                                    "no sostuvo el ritmo y la corrida no es válida"}
    resumen["slo_rnf10"] = {"p95_menor_400ms": p95 is not None and p95 < 400, "errores_menor_0_5pct": tasa_err < 0.5,
                            "veredicto": "PASA" if (p95 is not None and p95 < 400 and tasa_err < 0.5) else "FALLA"}
    return resumen


def guardar(salida: Path, filas, resumen):
    salida.mkdir(parents=True, exist_ok=True)
    campos = ["flujo", "fase", "caso", "inicio_s", "retraso_inicio_s", "latencia_ms", "codigo", "estado", "causa",
              "instancia", "trace_id", "intentos"]
    with open(salida / "solicitudes.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=campos, extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(filas, key=lambda r: (r["inicio_s"], r["fase"])))
    (salida / "resumen.json").write_text(json.dumps(resumen, indent=2, ensure_ascii=False), encoding="utf-8")
    with open(salida / "resumen.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["fase", "n", "throughput_s", "p50_ms", "p95_ms", "p99_ms", "max_ms", "tasa_error_pct"])
        for fase, d in resumen["por_fase"].items():
            w.writerow([fase, d["n"], d["throughput_s"], d["p50_ms"], d["p95_ms"], d["p99_ms"], d["max_ms"],
                        d["tasa_error_pct"]])
        g = resumen["global"]
        w.writerow(["global", resumen["solicitudes_medidas"], resumen["throughput_solicitudes_s"], g["p50_ms"],
                    g["p95_ms"], g["p99_ms"], "", g["tasa_error_pct"]])


def main():
    ap = argparse.ArgumentParser(description="Generador de carga de la ruta de confirmación")
    ap.add_argument("--objetivo", default=os.environ.get("PORTAL_URL", "http://nginx:80"))
    ap.add_argument("--dsn", default=os.environ.get("BD_DSN", "postgresql://postgres:portal@db:5432/portal_b2b"))
    ap.add_argument("--flujos-por-s", type=float, default=100.0, help="flujos/s (cada flujo = 2 solicitudes)")
    ap.add_argument("--duracion", type=float, default=300.0, help="segundos medidos")
    ap.add_argument("--calentamiento", type=float, default=30.0, help="segundos iniciales no medidos")
    ap.add_argument("--semilla", type=int, default=42)
    ap.add_argument("--p-contrato-vencido", type=float, default=0.005)
    ap.add_argument("--p-sku-ajeno", type=float, default=0.005)
    ap.add_argument("--p-ultima-franja", type=float, default=0.005)
    ap.add_argument("--fecha-desde", default="2026-09-17", help="primera fecha de franjas futuras")
    ap.add_argument("--timeout-cliente", type=float, default=60.0)
    ap.add_argument("--max-conexiones", type=int, default=1000)
    ap.add_argument("--reintentos-cliente", type=int, default=0,
                    help="reintentos del cliente ante 502/503/504/error de conexión, con la misma Idempotency-Key (0 = ninguno)")
    ap.add_argument("--salida", required=True)
    args = ap.parse_args()

    global REINTENTOS_CLIENTE
    REINTENTOS_CLIENTE = args.reintentos_cliente
    pesos, ofertas, franjas, previas = cargar_referencia(args.dsn, args.fecha_desde)
    if previas:
        sys.exit(f"Hay {previas} órdenes de corridas previas: ejecuta `make reset-estado` antes (la carga debe partir "
                 "de un estado conocido).")
    flujos = planificar(args, pesos, ofertas, franjas)
    print(f"Carga planificada: {len(flujos)} flujos ({2 * len(flujos)} solicitudes) a {args.flujos_por_s} flujos/s, "
          f"{args.calentamiento:.0f} s de calentamiento + {args.duracion:.0f} s medidos, semilla {args.semilla}",
          flush=True)
    filas, duracion_real = asyncio.run(correr(args, flujos))
    resumen = resumir(args, filas, flujos, duracion_real)
    guardar(Path(args.salida), filas, resumen)
    print(json.dumps({"global": resumen["global"], "confirmar": resumen["por_fase"]["confirmar"]["p95_ms"],
                      "throughput_s": resumen["throughput_solicitudes_s"], "slo": resumen["slo_rnf10"]["veredicto"],
                      "generador_retraso_p99_s": resumen["generador"]["retraso_inicio_p99_s"]}, ensure_ascii=False))
    print(f"Guardado en {args.salida}")


if __name__ == "__main__":
    main()

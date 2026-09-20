#!/usr/bin/env python3
"""
verificar.py — Suite de verificación automática y auditoría de datos.
Curso: Aplicaciones y Sistemas Escalables — Universidad EAFIT
Autor original: Esteban · Extendido por JJ (verificaciones medidas sobre los CSV, no leídas del manifiesto)

Imprime el reporte exigido por el enunciado (Fase 5) y sale con código 1 si algo FALLA:
  1. Volumen por tabla contra el mínimo exigido (PASA / FALLA).
  2. Sesgo Zipf: % de órdenes del top 1 %, 5 % y 20 % de proveedores (+ parámetros s y q).
  3. Estacionalidad mensual (últimos 60 días, últimos 3 días hábiles del mes) y horaria.
  4. Sesgo del catálogo: % de líneas que concentra el 10 % de los SKU.
  5. Integridad de negocio: RN-02 (contrato vigente), RN-04 (SKU del proveedor), RN-05 (precio negociado),
     franja y fecha_compromiso coherentes.
  6. Los 8 casos borde, localizados y comprobados EN LOS DATOS (no en el manifiesto).
  7. Checksums SHA-256 de determinismo.

Evidencia para las gráficas del documento (CSV) en datos/resultados/:
  zipf_proveedores.csv · ordenes_por_dia.csv · ordenes_por_hora.csv

Uso:
  python3 datos/verificar.py                 # verifica datos/csv
  python3 datos/verificar.py --determinismo  # genera dos veces con --seed 42 y compara checksums
"""

import os
import sys
import csv
import json
import shutil
import hashlib
import argparse
import subprocess
from collections import Counter, defaultdict
from datetime import date, timedelta

MINIMOS_EXIGIDOS = {
    "proveedores.csv": 100000,
    "contratos.csv": 10000,
    "sku_catalogo.csv": 200000,
    "franjas_cedi.csv": 90000,
    "ordenes_compra.csv": 300000,
    "lineas_orden.csv": 1500000,
    "eventos_auditoria.csv": 500000,
}
TOTAL_MINIMO = 2700000

# Tolerancias de aceptación (el enunciado pide: 5 % → 40 %, 1 % → "cerca del 15 %", últimos 3 días hábiles → 25 %,
# 10 % de los SKU → 60 % de las líneas)
TOL = {
    "top1": (12.5, 17.5),
    "top5": (37.0, 43.0),
    "fin_mes": (22.0, 28.0),
    "sku_top10": (55.0, 65.0),
}
DIR_RESULTADOS = os.path.join("datos", "resultados")


class _Tee:
    """Duplica stdout hacia un archivo (UTF-8)."""
    def __init__(self, stream, path):
        self._stream, self._file = stream, open(path, "w", encoding="utf-8")

    def write(self, texto):
        self._stream.write(texto)
        self._file.write(texto)

    def flush(self):
        self._stream.flush()
        self._file.flush()


def calcular_checksum(filepath):
    """SHA-256 en bloques de 64 KB."""
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            sha256.update(chunk)
    return sha256.hexdigest()


def contar_filas_csv(filepath):
    """Cuenta filas omitiendo el encabezado."""
    with open(filepath, "r", encoding="utf-8") as f:
        return max(0, sum(1 for _ in f) - 1)


def leer_csv(path):
    with open(path, "r", encoding="utf-8", newline="") as f:
        yield from csv.DictReader(f)


def ultimos_3_dias_habiles(anio, mes):
    """Conjunto con los últimos 3 días hábiles (lun-vie) del mes."""
    ultimo = (date(anio, mes, 28) + timedelta(days=4))
    ultimo = ultimo - timedelta(days=ultimo.day)
    dias, cur = [], ultimo
    while len(dias) < 3:
        if cur.weekday() < 5:
            dias.append(cur)
        cur -= timedelta(days=1)
    return set(dias)


def veredicto(ok):
    return "PASA" if ok else "FALLA"


def seccion(titulo):
    print("---------------------------------------------------------------------")
    print(titulo)
    print("---------------------------------------------------------------------")


def escribir_csv(nombre, cabecera, filas):
    os.makedirs(DIR_RESULTADOS, exist_ok=True)
    path = os.path.join(DIR_RESULTADOS, nombre)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(cabecera)
        w.writerows(filas)
    return path


# ---------------------------------------------------------------------------
# Determinismo: dos corridas independientes con la misma semilla
# ---------------------------------------------------------------------------
def verificar_determinismo(seed=42, scale="min"):
    print("=====================================================================")
    print(f"DETERMINISMO: dos corridas de generar.py con --seed {seed} --scale {scale}")
    print("=====================================================================")
    dir_a, dir_b = os.path.join("datos", ".det_a"), os.path.join("datos", ".det_b")
    sumas = {}
    try:
        for etiqueta, d in (("A", dir_a), ("B", dir_b)):
            shutil.rmtree(d, ignore_errors=True)
            print(f"  corrida {etiqueta} → {d} ...", flush=True)
            r = subprocess.run([sys.executable, os.path.join("datos", "generar.py"), "--seed", str(seed),
                                "--scale", scale, "--output-dir", d], capture_output=True, text=True)
            if r.returncode != 0:
                print(r.stderr)
                return False
            sumas[etiqueta] = {a: calcular_checksum(os.path.join(d, a)) for a in sorted(MINIMOS_EXIGIDOS)}
            sumas[etiqueta + "_n"] = {a: contar_filas_csv(os.path.join(d, a)) for a in sorted(MINIMOS_EXIGIDOS)}
    finally:
        shutil.rmtree(dir_a, ignore_errors=True)
        shutil.rmtree(dir_b, ignore_errors=True)
    todo_ok = True
    print(f"\n{'archivo':<24} {'filas A':>10} {'filas B':>10}  {'sha256 A (16)':<18} {'sha256 B (16)':<18} resultado")
    for a in sorted(MINIMOS_EXIGIDOS):
        igual = sumas["A"][a] == sumas["B"][a] and sumas["A_n"][a] == sumas["B_n"][a]
        todo_ok &= igual
        print(f"{a:<24} {sumas['A_n'][a]:>10,} {sumas['B_n'][a]:>10,}  {sumas['A'][a][:16]:<18} {sumas['B'][a][:16]:<18} {'IDÉNTICO' if igual else 'DISTINTO'}")
    print(f"\nRESULTADO DETERMINISMO: {veredicto(todo_ok)}")
    return todo_ok


def main():
    ap = argparse.ArgumentParser(description="Verificador de datos del Portal B2B")
    ap.add_argument("--determinismo", action="store_true", help="genera dos veces con --seed 42 y compara checksums")
    args = ap.parse_args()
    if args.determinismo:
        sys.exit(0 if verificar_determinismo() else 1)

    # La salida completa se guarda también en datos/resultados/verificacion.txt (el enunciado pide pegarla en el entregable)
    os.makedirs(DIR_RESULTADOS, exist_ok=True)
    sys.stdout = _Tee(sys.stdout, os.path.join(DIR_RESULTADOS, "verificacion.txt"))

    csv_dir = os.path.join("datos", "csv")
    manifiesto_path = os.path.join("datos", "casos_borde.json")
    parametros_path = os.path.join("datos", "parametros_generacion.json")

    print("=====================================================================")
    print("AUDITORÍA AUTOMÁTICA DE ESCALABILIDAD DE DATOS (VERIFICADOR)")
    print("   Universidad EAFIT · Proyecto Integrador Portal B2B · Entrega 2")
    print("=====================================================================\n")

    if not os.path.exists(csv_dir):
        print(f"ERROR: El directorio {csv_dir} no existe. Ejecuta primero `make generar`.")
        sys.exit(1)

    todos_pasan = True
    params = json.load(open(parametros_path, encoding="utf-8")) if os.path.exists(parametros_path) else {}
    pivote = date.fromisoformat(params.get("fecha_pivote", "2026-09-16"))

    # -----------------------------------------------------------------------
    # 1. Volumen
    # -----------------------------------------------------------------------
    seccion("1. VOLUMEN DEL CONJUNTO POR TABLA (MÍNIMO VS LOGRADO)")
    print(f"{'Entidad / Archivo':<25} | {'Mínimo':>10} | {'Logrado':>10} | {'Veredicto':^9}")
    print("-" * 63)
    conteos, checksums = {}, {}
    for archivo, minimo in MINIMOS_EXIGIDOS.items():
        path = os.path.join(csv_dir, archivo)
        if not os.path.exists(path):
            print(f"{archivo:<25} | {minimo:>10,} | {'NO EXISTE':>10} |   FALLA")
            todos_pasan = False
            continue
        filas = contar_filas_csv(path)
        conteos[archivo] = filas
        checksums[archivo] = calcular_checksum(path)
        pasa = filas >= minimo
        todos_pasan &= pasa
        print(f"{archivo:<25} | {minimo:>10,} | {filas:>10,} | {veredicto(pasa)}")
    if len(conteos) < len(MINIMOS_EXIGIDOS):
        print("\nRESULTADO GLOBAL: FALTAN ARCHIVOS. Ejecuta `make generar`.")
        sys.exit(1)
    total_logrado = sum(conteos.values())
    pasa_total = total_logrado >= TOTAL_MINIMO
    todos_pasan &= pasa_total
    print("-" * 63)
    print(f"{'TOTAL CONJUNTO':<25} | {TOTAL_MINIMO:>10,} | {total_logrado:>10,} | {veredicto(pasa_total)}\n")

    # -----------------------------------------------------------------------
    # Carga de dimensiones (pequeñas) para las verificaciones cruzadas
    # -----------------------------------------------------------------------
    ids_proveedores = set()
    for r in leer_csv(os.path.join(csv_dir, "proveedores.csv")):
        ids_proveedores.add(int(r["id"]))

    contratos = {}          # id -> (proveedor_id, inicio, fin, estado)
    contratos_por_prov = defaultdict(list)
    for r in leer_csv(os.path.join(csv_dir, "contratos.csv")):
        c = (int(r["proveedor_id"]), date.fromisoformat(r["fecha_inicio"]), date.fromisoformat(r["fecha_fin"]), r["estado"])
        contratos[int(r["id"])] = c
        contratos_por_prov[c[0]].append(c)
    num_contratos = len(contratos)
    num_skus = conteos["sku_catalogo.csv"]

    sku_precio, sku_prov = {}, {}
    for r in leer_csv(os.path.join(csv_dir, "sku_catalogo.csv")):
        sku_precio[int(r["id"])] = float(r["precio_negociado"])
        sku_prov[int(r["id"])] = int(r["proveedor_id"])

    franjas = {}            # id -> (cedi, fecha, total, reservada)
    ultima_franja_cedi_dia = {}
    for r in leer_csv(os.path.join(csv_dir, "franjas_cedi.csv")):
        fid = int(r["id"])
        franjas[fid] = (int(r["cedi_id"]), date.fromisoformat(r["fecha"]), int(r["capacidad_total"]), int(r["capacidad_reservada"]))
        ultima_franja_cedi_dia[(int(r["cedi_id"]), r["fecha"])] = fid

    # -----------------------------------------------------------------------
    # Una pasada sobre órdenes
    # -----------------------------------------------------------------------
    ordenes_por_prov = Counter()
    ordenes_por_prov_mes = Counter()
    ordenes_por_dia = Counter()
    ordenes_por_hora = Counter()
    orden_prov = {}
    total_ordenes = 0
    n_confirmadas_ctr = n_confirmadas_vigente = 0
    franja_incoherente = compromiso_incoherente = 0
    for r in leer_csv(os.path.join(csv_dir, "ordenes_compra.csv")):
        oid, pid = int(r["id"]), int(r["proveedor_id"])
        f_em = r["fecha_emision"]
        dia = date.fromisoformat(f_em[:10])
        total_ordenes += 1
        ordenes_por_prov[pid] += 1
        ordenes_por_prov_mes[(pid, f_em[:7])] += 1
        ordenes_por_dia[dia] += 1
        ordenes_por_hora[int(f_em[11:13])] += 1
        orden_prov[oid] = pid
        comp = date.fromisoformat(r["fecha_compromiso"])
        fr = franjas.get(int(r["franja_id"]))
        if fr is None or fr[1] != comp:
            franja_incoherente += 1
        if comp < dia:
            compromiso_incoherente += 1
        if r["estado"] == "CONFIRMADA" and pid in contratos_por_prov:
            n_confirmadas_ctr += 1
            if any(ini <= dia <= fin for (_, ini, fin, _) in contratos_por_prov[pid]):
                n_confirmadas_vigente += 1

    # -----------------------------------------------------------------------
    # 2. Zipf
    # -----------------------------------------------------------------------
    seccion("2. DISTRIBUCIÓN ACUMULADA DE SESGO ZIPF EN PROVEEDORES")
    n_prov = conteos["proveedores.csv"]
    prov_ordenados = ordenes_por_prov.most_common()

    def pct_top(fraccion):
        k = max(1, int(n_prov * fraccion))
        return k, sum(c for _, c in prov_ordenados[:k]), 100.0 * sum(c for _, c in prov_ordenados[:k]) / total_ordenes

    k1, o1, p1 = pct_top(0.01)
    k5, o5, p5 = pct_top(0.05)
    k20, o20, p20 = pct_top(0.20)
    ok1, ok5 = TOL["top1"][0] <= p1 <= TOL["top1"][1], TOL["top5"][0] <= p5 <= TOL["top5"][1]
    todos_pasan &= ok1 and ok5
    print(f"- Top  1% proveedores ({k1:,} prov): {o1:,} órdenes ({p1:.2f}% de la demanda) -> [Objetivo ~15%, tolerancia {TOL['top1'][0]}-{TOL['top1'][1]}%] {veredicto(ok1)}")
    print(f"- Top  5% proveedores ({k5:,} prov): {o5:,} órdenes ({p5:.2f}% de la demanda) -> [Objetivo 40%, tolerancia {TOL['top5'][0]}-{TOL['top5'][1]}%] {veredicto(ok5)}")
    print(f"- Top 20% proveedores ({k20:,} prov): {o20:,} órdenes ({p20:.2f}% de la demanda)")
    z = params.get("zipf_proveedores", {})
    print(f"Parámetros del modelo (datos/parametros_generacion.json): {z.get('modelo', 'Zipf-Mandelbrot')} s={z.get('s', '?')}, q={z.get('q', '?')}")
    print(f"Proveedor más activo: id {prov_ordenados[0][0]} con {prov_ordenados[0][1]:,} órdenes · proveedores con al menos una orden: {len(ordenes_por_prov):,} de {n_prov:,}\n")
    acum, filas_zipf = 0, []
    for rango, (pid, c) in enumerate(prov_ordenados, start=1):
        acum += c
        if rango <= 1000 or rango % 100 == 0 or rango == len(prov_ordenados):
            filas_zipf.append((rango, pid, c, f"{100.0 * acum / total_ordenes:.4f}"))
    escribir_csv("zipf_proveedores.csv", ["rango", "proveedor_id", "ordenes", "acumulado_pct"], filas_zipf)

    # -----------------------------------------------------------------------
    # 3. Estacionalidad
    # -----------------------------------------------------------------------
    seccion("3. ESTACIONALIDAD MENSUAL: ÓRDENES POR DÍA (ÚLTIMOS 60 DÍAS)")
    meses = sorted({(d.year, d.month) for d in ordenes_por_dia})
    dias_fin_mes = set()
    for (a, m) in meses:
        dias_fin_mes |= ultimos_3_dias_habiles(a, m)
    ord_fin_mes = sum(c for d, c in ordenes_por_dia.items() if d in dias_fin_mes)
    pct_fin_mes = 100.0 * ord_fin_mes / total_ordenes
    ultimo_dia = max(ordenes_por_dia)
    ventana = [ultimo_dia - timedelta(days=i) for i in range(59, -1, -1)]
    max_dia = max(ordenes_por_dia[d] for d in ventana) or 1
    for d in ventana:
        c = ordenes_por_dia.get(d, 0)
        marca = "  ◄ últimos 3 días hábiles del mes" if d in dias_fin_mes else ""
        print(f"{d} | {c:>5,} órdenes | {'█' * int(c / max_dia * 35)}{marca}")
    dias_normales = [c for d, c in ordenes_por_dia.items() if d not in dias_fin_mes]
    promedio_normal = sum(dias_normales) / max(1, len(dias_normales))
    promedio_pico = ord_fin_mes / max(1, sum(1 for d in ordenes_por_dia if d in dias_fin_mes))
    ok_fm = TOL["fin_mes"][0] <= pct_fin_mes <= TOL["fin_mes"][1]
    todos_pasan &= ok_fm
    print(f"\nÚltimos 3 días hábiles de cada mes: {ord_fin_mes:,} de {total_ordenes:,} órdenes = {pct_fin_mes:.1f}% "
          f"[Objetivo 25%, tolerancia {TOL['fin_mes'][0]}-{TOL['fin_mes'][1]}%] {veredicto(ok_fm)}")
    print(f"Promedio por día: {promedio_pico:,.0f} órdenes en días de cierre vs {promedio_normal:,.0f} en el resto ({promedio_pico / promedio_normal:.1f}×)\n")
    escribir_csv("ordenes_por_dia.csv", ["fecha", "ordenes", "es_ultimo_3_habiles_mes"],
                 [(d.isoformat(), ordenes_por_dia[d], int(d in dias_fin_mes)) for d in sorted(ordenes_por_dia)])

    print("ESTACIONALIDAD HORARIA (hora UTC de emisión)")
    max_h = max(ordenes_por_hora.values())
    for h in range(24):
        c = ordenes_por_hora.get(h, 0)
        print(f"  {h:02d}:00 | {100.0 * c / total_ordenes:5.1f}% | {c:>7,} | {'█' * int(c / max_h * 35)}")
    pico = sum(ordenes_por_hora.get(h, 0) for h in (8, 9, 10)) * 100.0 / total_ordenes
    noche = sum(ordenes_por_hora.get(h, 0) for h in (22, 23, 0, 1, 2, 3, 4, 5)) * 100.0 / total_ordenes
    ok_h = pico >= 50.0 and noche <= 1.0
    todos_pasan &= ok_h
    print(f"Pico 08:00-10:59: {pico:.1f}% de las órdenes · valle nocturno 22:00-05:59: {noche:.2f}% "
          f"[Objetivo: pico ≥ 50 %, valle ≤ 1 %] {veredicto(ok_h)}\n")
    escribir_csv("ordenes_por_hora.csv", ["hora_utc", "ordenes", "porcentaje"],
                 [(h, ordenes_por_hora.get(h, 0), f"{100.0 * ordenes_por_hora.get(h, 0) / total_ordenes:.3f}") for h in range(24)])

    # -----------------------------------------------------------------------
    # Una pasada sobre líneas
    # -----------------------------------------------------------------------
    lineas_por_orden = Counter()
    lineas_por_sku = Counter()
    total_lineas = 0
    lineas_con_contrato = lineas_sku_propio = 0
    precio_ok = precio_mal = 0
    lineas_cb6 = []
    for r in leer_csv(os.path.join(csv_dir, "lineas_orden.csv")):
        oid, sku = int(r["orden_id"]), int(r["sku_id"])
        total_lineas += 1
        lineas_por_orden[oid] += 1
        lineas_por_sku[sku] += 1
        if abs(float(r["precio_unitario"]) - sku_precio[sku]) < 0.005:
            precio_ok += 1
        else:
            precio_mal += 1
        pid = orden_prov[oid]
        if pid in contratos_por_prov:
            lineas_con_contrato += 1
            if sku_prov[sku] == pid:
                lineas_sku_propio += 1
            else:
                lineas_cb6.append((oid, int(r["id"]), sku))

    # -----------------------------------------------------------------------
    # 4. Sesgo de catálogo
    # -----------------------------------------------------------------------
    seccion("4. SESGO DEL CATÁLOGO: CONCENTRACIÓN DE LÍNEAS POR SKU")
    k_sku = max(1, int(num_skus * 0.10))
    top_sku = sum(c for _, c in lineas_por_sku.most_common(k_sku))
    p_sku = 100.0 * top_sku / total_lineas
    ok_sku = TOL["sku_top10"][0] <= p_sku <= TOL["sku_top10"][1]
    todos_pasan &= ok_sku
    print(f"- El 10% de los SKU ({k_sku:,} de {num_skus:,}) aparece en {top_sku:,} de {total_lineas:,} líneas = {p_sku:.1f}% "
          f"[Objetivo 60%, tolerancia {TOL['sku_top10'][0]}-{TOL['sku_top10'][1]}%] {veredicto(ok_sku)}")
    print(f"- SKU distintos con al menos una línea: {len(lineas_por_sku):,}\n")

    # -----------------------------------------------------------------------
    # 5. Integridad de negocio
    # -----------------------------------------------------------------------
    seccion("5. INTEGRIDAD DE NEGOCIO (RN-02, RN-04, RN-05) Y COHERENCIA DE FRANJAS")
    pct_propio = 100.0 * lineas_sku_propio / max(1, lineas_con_contrato)
    ok_rn04 = len(lineas_cb6) <= 3 and pct_propio >= 99.99
    ok_rn05 = precio_mal == 0
    pct_vig = 100.0 * n_confirmadas_vigente / max(1, n_confirmadas_ctr)
    ok_rn02 = pct_vig >= 99.9
    ok_fr = franja_incoherente == 0 and compromiso_incoherente == 0
    todos_pasan &= ok_rn04 and ok_rn05 and ok_rn02 and ok_fr
    print(f"- RN-04 SKU de la línea es oferta del proveedor de la orden (órdenes de proveedores con contrato): "
          f"{lineas_sku_propio:,} de {lineas_con_contrato:,} ({pct_propio:.3f}%); excepciones sembradas: {len(lineas_cb6)} {veredicto(ok_rn04)}")
    print(f"- RN-05 precio de la línea = precio negociado del SKU: {precio_ok:,} de {total_lineas:,} {veredicto(ok_rn05)}")
    print(f"- RN-02 órdenes CONFIRMADAS con contrato vigente en la fecha de emisión: {n_confirmadas_vigente:,} de {n_confirmadas_ctr:,} ({pct_vig:.3f}%) {veredicto(ok_rn02)}")
    print(f"- Franja reservada existe y su fecha = fecha_compromiso (≥ fecha de emisión): {veredicto(ok_fr)}"
          f" (incoherentes: {franja_incoherente + compromiso_incoherente})\n")

    # -----------------------------------------------------------------------
    # 6. Casos borde comprobados en los datos
    # -----------------------------------------------------------------------
    seccion("6. LOS 8 CASOS BORDE SEMBRADOS, COMPROBADOS EN LOS DATOS")
    resultados = []

    def caso(n, texto, ok):
        resultados.append(ok)
        print(f"Caso {n}: {texto} {veredicto(ok)}")

    oid_max = max(lineas_por_orden, key=lambda o: lineas_por_orden[o])
    caso(1, f"Orden con 300 líneas -> orden_id = {oid_max} ({lineas_por_orden[oid_max]} líneas)", lineas_por_orden[oid_max] == 300)

    c2 = contratos.get(2)
    caso(2, f"Contrato vencido ayer -> contrato_id = 2 (fecha_fin {c2[2]}, estado {c2[3]})",
         c2 is not None and c2[2] == pivote - timedelta(days=1) and c2[3] == "VENCIDO")
    c3 = contratos.get(3)
    caso(3, f"Contrato que vence hoy -> contrato_id = 3 (fecha_fin {c3[2]}, estado {c3[3]})",
         c3 is not None and c3[2] == pivote and c3[3] == "VIGENTE")

    fid = ultima_franja_cedi_dia.get((1, pivote.isoformat()))
    fr = franjas.get(fid)
    caso(4, f"Última franja del día en un CEDI -> franja_id = {fid} (CEDI {fr[0]}, {fr[1]}, capacidad {fr[2]}, ocupadas {fr[3]})",
         fr is not None and fr[2] - fr[3] == 1)

    sin_contrato = [p for p in (55555,) if p in ids_proveedores and p not in contratos_por_prov]
    caso(5, f"Proveedor sin contrato vigente -> proveedor_id = {sin_contrato[0] if sin_contrato else '?'} "
            f"(existe en proveedores, 0 contratos, {ordenes_por_prov.get(55555, 0)} órdenes)", bool(sin_contrato))

    cb6 = [x for x in lineas_cb6 if x[0] == 606]
    caso(6, f"SKU fuera del catálogo del proveedor -> orden_id = 606, línea {cb6[0][1] if cb6 else '?'}, "
            f"sku_id = {cb6[0][2] if cb6 else '?'} (proveedor de la orden: {orden_prov.get(606)})", len(cb6) >= 1)

    hot = [(p, c) for p, c in ordenes_por_prov.items() if c >= 5000]
    caso(7, "Proveedor 'hot' con >= 5 000 órdenes -> " + ", ".join(f"proveedor_id = {p} ({c:,} órdenes)" for p, c in hot), len(hot) >= 1)

    cb8 = [p for p in contratos_por_prov if p == 10 and ordenes_por_prov.get(p, 0) > 0 and ordenes_por_prov_mes.get((p, "2025-06"), 0) == 0]
    caso(8, f"Mes sin órdenes para un proveedor activo -> proveedor_id = 10 (contrato vigente, {ordenes_por_prov.get(10, 0)} órdenes en total, 0 en 2025-06)", bool(cb8))
    todos_pasan &= all(resultados)
    print()

    # -----------------------------------------------------------------------
    # 7. Checksums
    # -----------------------------------------------------------------------
    seccion("7. CHECKSUM SHA-256 DE DETERMINISMO (--seed 42)")
    for arch, csum in checksums.items():
        print(f"{arch:<25}: {csum}")
    print("---------------------------------------------------------------------")
    print("(Para demostrar que dos corridas producen el mismo conjunto: `make determinismo`)")

    print()
    if todos_pasan:
        print("RESULTADO GLOBAL: TODOS LOS CRITERIOS PASAN")
    else:
        print("RESULTADO GLOBAL: EXISTEN CRITERIOS EN FALLA (ver secciones marcadas con FALLA)")
    print(f"Evidencia para gráficas: {DIR_RESULTADOS}/zipf_proveedores.csv, ordenes_por_dia.csv, ordenes_por_hora.csv")
    print("=====================================================================")
    sys.exit(0 if todos_pasan else 1)


if __name__ == "__main__":
    main()

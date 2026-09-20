#!/usr/bin/env python3
"""
generar.py — Generador determinista de datos en streaming para el Portal B2B de Retail.
Curso: Aplicaciones y Sistemas Escalables — Universidad EAFIT
Autor: Esteban (Motor de Generación y Validación de Datos)

Cumple con:
- Streaming directo a disco en CSV (bajo consumo de memoria RAM)
- Determinismo total con parámetro --seed (por defecto 42)
- Resolución aritmética de llaves foráneas (cero consultas a BD)
- Distribución Zipf-Mandelbrot de proveedores (s=1.15, q=1940): 5% concentra ~40%, 1% concentra ~15%
- Sesgo de catálogo: top 10% de SKU concentra ~60% de líneas
- Integridad de negocio: cada línea es una oferta del propio proveedor (RN-04) al precio negociado (RN-05)
- Datos de entrega (fecha_compromiso, fecha_entrega, cantidad_entregada) para OTIF y fill rate
- Estacionalidad mensual: últimos 3 días hábiles concentran el 25% de órdenes
- Estacionalidad horaria: pico 8:00 - 11:00 a.m., valle nocturno
- Siembra determinista de los 8 casos borde con manifiesto JSON
- Optimización de alto rendimiento mediante buffers y f-strings
"""

import os
import sys
import csv
import time
import bisect
import random
import argparse
from datetime import date, timedelta

# ---------------------------------------------------------------------------
# Configuración de escalas de volumen
# ---------------------------------------------------------------------------
SCALES = {
    "dev": {
        "proveedores": 5000,
        "contratos": 600,
        "skus": 10000,
        "franjas_dias": 60,
        "franjas_por_dia_cedi": 10,
        "ordenes": 15000,
        "eventos": 25000,
    },
    "min": {
        "proveedores": 100000,
        "contratos": 10000,
        "skus": 200000,
        "franjas_dias": 730,  # 24 meses
        "franjas_por_dia_cedi": 25,  # 5 CEDIs * 25 * 730 = 91,250 franjas (>= 90,000)
        "ordenes": 300000,
        "eventos": 500000,
    },
    "target": {
        "proveedores": 100000,
        "contratos": 15000,
        "skus": 400000,
        "franjas_dias": 730,  # 24 meses
        "franjas_por_dia_cedi": 42,  # 5 CEDIs * 42 * 730 = 153,300 franjas (>= 150,000)
        "ordenes": 500000,
        "eventos": 800000,
    }
}

# Parámetros estadísticos documentados (calibrados numéricamente: con las 5 250 órdenes forzadas al
# proveedor 1 (caso borde 7) el modelo esperado da top 1 % ≈ 15,0 % · top 5 % ≈ 39,9 % · top 20 % ≈ 68,6 %)
ZIPF_PROV_S = 1.15      # exponente s de Zipf-Mandelbrot sobre proveedores: peso(i) = 1 / (i + q)^s
ZIPF_PROV_Q = 1940      # desplazamiento q (aplana la cabeza de la distribución)
ZIPF_CATALOG_S = 0.80   # Zipf global sobre SKU: solo para líneas de órdenes de proveedores SIN contrato (rechazadas)

# Órdenes de proveedores con contrato: cada línea toma una oferta del PROPIO proveedor (RN-04).
# Con prob. P_OFERTA_POPULAR la oferta sale del 10 % "popular" de las ofertas del proveedor (sesgo de catálogo).
P_OFERTA_POPULAR = 0.57
FRACCION_OFERTAS_POPULARES = 0.10

# Entrega (insumo de OTIF y fill rate, Q4). Fiabilidad por proveedor derivada aritméticamente de su id (sin RNG).
ENTREGA_MAX_RETRASO_DIAS = 5

CATEGORIAS = [
    "Abarrotes", "Lácteos y Huevos", "Carnes y Aves", "Frutas y Verduras",
    "Bebidas y Licores", "Limpieza del Hogar", "Cuidado Personal", "Panadería"
]

CEDIS = [1, 2, 3, 4, 5]


def construir_cdf_zipf(n, s, q=0):
    """Construye una CDF normalizada para muestreo O(log N) con bisect."""
    weights = [1.0 / ((i + q) ** s) for i in range(1, n + 1)]
    h = sum(weights)
    cdf = []
    acum = 0.0
    for w in weights:
        acum += w / h
        cdf.append(acum)
    cdf[-1] = 1.0
    return cdf


def muestrear_zipf(cdf, rng):
    """Muestrea un índice 1-based según la CDF provista."""
    u = rng.random()
    return bisect.bisect_left(cdf, u) + 1


def precio_negociado(sku_id):
    """Precio negociado del SKU: se usa en sku_catalogo.csv y se copia a la línea (RN-05: precio = negociado)."""
    return round(1500.0 + (sku_id % 500) * 150.5, 2)


def oferta_sku(proveedor_id, k, num_contratos):
    """SKU (id) de la k-ésima oferta de un proveedor con contrato: inversa aritmética de
    proveedor_id = ((sku_id - 1) % num_contratos) + 1. Sin consultar la base."""
    return proveedor_id + k * num_contratos


def num_ofertas(proveedor_id, num_skus, num_contratos):
    return (num_skus - proveedor_id) // num_contratos + 1


def fiabilidad(proveedor_id, multiplicador):
    """Probabilidad de cumplimiento del proveedor en [0.72, 0.98], determinista a partir de su id."""
    return 0.72 + 0.26 * (((proveedor_id * multiplicador) % 1000) / 999.0)


def generar_fechas_24_meses(fecha_fin_base, num_dias):
    """Genera lista de fechas retroactivas para la simulación."""
    fechas = [fecha_fin_base - timedelta(days=d) for d in range(num_dias)]
    fechas.reverse()
    return fechas


def es_fin_de_mes_habil(d):
    """Identifica si una fecha cae en los últimos 3 días hábiles del mes."""
    next_month = d.replace(day=28) + timedelta(days=4)
    last_day = next_month - timedelta(days=next_month.day)
    dias_habiles = []
    curr = last_day
    while len(dias_habiles) < 3 and curr.month == d.month:
        if curr.weekday() < 5:
            dias_habiles.append(curr)
        curr -= timedelta(days=1)
    return d in dias_habiles


def main():
    parser = argparse.ArgumentParser(description="Generador masivo de datos para Portal B2B")
    parser.add_argument("--seed", type=int, default=42, help="Semilla para reproducibilidad (def: 42)")
    parser.add_argument("--scale", choices=["dev", "min", "target"], default="min", help="Escala de datos")
    parser.add_argument("--output-dir", default="datos/csv", help="Directorio de salida para CSVs")
    args = parser.parse_args()

    t_inicio = time.time()
    rng = random.Random(args.seed)
    cfg = SCALES[args.scale]
    os.makedirs(args.output_dir, exist_ok=True)

    print("=====================================================================")
    print(f"🚀 INICIANDO GENERACIÓN DE DATOS · ESCALA: {args.scale.upper()} · SEMILLA: {args.seed}")
    print("=====================================================================")

    manifiesto_casos_borde = {}
    metricas_archivos = {}

    fecha_pivote = date(2026, 9, 16)
    fechas_simulacion = generar_fechas_24_meses(fecha_pivote, cfg["franjas_dias"])

    # -----------------------------------------------------------------------
    # 1. GENERACIÓN: proveedores.csv
    # -----------------------------------------------------------------------
    f_prov_path = os.path.join(args.output_dir, "proveedores.csv")
    t0 = time.time()
    num_proveedores = cfg["proveedores"]
    print(f"[1/7] Generando {num_proveedores:,} proveedores en {f_prov_path}...")

    with open(f_prov_path, "w", newline="", encoding="utf-8") as f:
        f.write("id,nit,razon_social,contacto_email,estado,created_at\n")
        lines = []
        for p_id in range(1, num_proveedores + 1):
            nit = f"{900000000 + p_id}-{p_id % 9}"
            razon = f"Proveedor Retail {p_id} S.A.S."
            email = f"contacto@proveedor{p_id}.com"
            estado = "INACTIVO" if p_id > cfg["contratos"] and p_id % 7 == 0 else "ACTIVO"
            created_at = (fecha_pivote - timedelta(days=rng.randint(750, 1000))).isoformat() + "T08:00:00Z"
            lines.append(f"{p_id},{nit},{razon},{email},{estado},{created_at}\n")
            if len(lines) >= 10000:
                f.writelines(lines)
                lines.clear()
        if lines:
            f.writelines(lines)

    metricas_archivos["proveedores.csv"] = {
        "filas": num_proveedores,
        "bytes": os.path.getsize(f_prov_path),
        "segundos": round(time.time() - t0, 2)
    }

    # Caso borde 5: Proveedor sin contrato vigente
    cb5_prov_id = min(55555, num_proveedores) if num_proveedores >= 55555 else num_proveedores
    manifiesto_casos_borde["caso_5_proveedor_sin_contrato"] = {
        "id": 5,
        "descripcion": "Proveedor registrado pero sin contrato de suministro vigente (camino de rechazo)",
        "tabla": "proveedores.proveedores",
        "proveedor_id": cb5_prov_id,
        "condicion": f"El proveedor_id {cb5_prov_id} NO existe en contratos.csv"
    }

    # -----------------------------------------------------------------------
    # 2. GENERACIÓN: contratos.csv
    # -----------------------------------------------------------------------
    f_cont_path = os.path.join(args.output_dir, "contratos.csv")
    t0 = time.time()
    num_contratos = cfg["contratos"]
    print(f"[2/7] Generando {num_contratos:,} contratos en {f_cont_path}...")

    with open(f_cont_path, "w", newline="", encoding="utf-8") as f:
        f.write("id,proveedor_id,numero_contrato,fecha_inicio,fecha_fin,estado,created_at\n")
        lines = []
        for c_id in range(1, num_contratos + 1):
            p_id = c_id
            num_contrato = f"CTR-2026-{c_id:06d}"
            # inicio anterior a la ventana de 24 meses: el contrato cubre todo el histórico de órdenes (RN-02)
            f_ini = fecha_pivote - timedelta(days=rng.randint(740, 900))

            if c_id == 2:
                f_fin = fecha_pivote - timedelta(days=1)
                estado = "VENCIDO"
            elif c_id == 3:
                f_fin = fecha_pivote
                estado = "VIGENTE"
            else:
                f_fin = fecha_pivote + timedelta(days=rng.randint(30, 365))
                estado = "VIGENTE"

            created_at = f_ini.isoformat() + "T00:00:00Z"
            lines.append(f"{c_id},{p_id},{num_contrato},{f_ini.isoformat()},{f_fin.isoformat()},{estado},{created_at}\n")
        f.writelines(lines)

    metricas_archivos["contratos.csv"] = {
        "filas": num_contratos,
        "bytes": os.path.getsize(f_cont_path),
        "segundos": round(time.time() - t0, 2)
    }

    manifiesto_casos_borde["caso_2_contrato_vencido_ayer"] = {
        "id": 2,
        "descripcion": "Contrato de suministro que venció ayer (frontera temporal estricta de validación)",
        "tabla": "proveedores.contratos_suministro",
        "contrato_id": 2,
        "fecha_fin": (fecha_pivote - timedelta(days=1)).isoformat()
    }
    manifiesto_casos_borde["caso_3_contrato_vence_hoy_mediodia"] = {
        "id": 3,
        "descripcion": "Contrato que vence hoy a mediodía (evalúa zona horaria y comparador >= vs >)",
        "tabla": "proveedores.contratos_suministro",
        "contrato_id": 3,
        "fecha_fin": fecha_pivote.isoformat()
    }

    # -----------------------------------------------------------------------
    # 3. GENERACIÓN: sku_catalogo.csv
    # -----------------------------------------------------------------------
    f_sku_path = os.path.join(args.output_dir, "sku_catalogo.csv")
    t0 = time.time()
    num_skus = cfg["skus"]
    print(f"[3/7] Generando {num_skus:,} SKUs en {f_sku_path}...")

    with open(f_sku_path, "w", newline="", encoding="utf-8") as f:
        f.write("id,sku,proveedor_id,nombre_producto,categoria,precio_negociado,vigencia_desde,vigencia_hasta,created_at\n")
        lines = []
        for sku_id in range(1, num_skus + 1):
            sku_code = f"SKU-{sku_id:07d}"
            p_id = ((sku_id - 1) % num_contratos) + 1
            cat = CATEGORIAS[sku_id % len(CATEGORIAS)]
            nombre = f"Producto {cat} Ref {sku_id}"
            precio = precio_negociado(sku_id)
            v_desde = (fecha_pivote - timedelta(days=730)).isoformat()
            v_hasta = (fecha_pivote + timedelta(days=365)).isoformat()
            created_at = v_desde + "T00:00:00Z"
            lines.append(f"{sku_id},{sku_code},{p_id},{nombre},{cat},{precio:.2f},{v_desde},{v_hasta},{created_at}\n")
            if len(lines) >= 10000:
                f.writelines(lines)
                lines.clear()
        if lines:
            f.writelines(lines)

    metricas_archivos["sku_catalogo.csv"] = {
        "filas": num_skus,
        "bytes": os.path.getsize(f_sku_path),
        "segundos": round(time.time() - t0, 2)
    }

    # -----------------------------------------------------------------------
    # 4. GENERACIÓN: franjas_cedi.csv (Cumpliendo >= 90,000 franjas)
    # -----------------------------------------------------------------------
    f_franjas_path = os.path.join(args.output_dir, "franjas_cedi.csv")
    t0 = time.time()
    franjas_por_dia = cfg["franjas_por_dia_cedi"]
    print(f"[4/7] Generando franjas CEDI ({franjas_por_dia} franjas/día/CEDI × 5 CEDIs × {cfg['franjas_dias']} días)...")

    franja_id = 1
    cb4_franja_id = None
    with open(f_franjas_path, "w", newline="", encoding="utf-8") as f:
        f.write("id,cedi_id,fecha,hora_inicio,hora_fin,capacidad_total,capacidad_reservada,created_at\n")
        lines = []
        for f_dia in fechas_simulacion:
            f_str = f_dia.isoformat()
            c_at = f_str + "T00:00:00Z"
            for cedi_id in CEDIS:
                for idx_slot in range(franjas_por_dia):
                    h_start = 6 + (idx_slot % 16)
                    h_end = h_start + 1
                    h_ini = f"{h_start:02d}:00:00"
                    h_fin = f"{h_end:02d}:00:00"
                    cap_total = 10
                    cap_res = rng.randint(2, 8)

                    # Caso Borde 4: Última franja disponible del día en un CEDI
                    if f_dia == fecha_pivote and cedi_id == 1 and idx_slot == franjas_por_dia - 1:
                        cap_res = 9  # Deja exactamente 1 unidad libre
                        cb4_franja_id = franja_id

                    lines.append(f"{franja_id},{cedi_id},{f_str},{h_ini},{h_fin},{cap_total},{cap_res},{c_at}\n")
                    franja_id += 1

                    if len(lines) >= 10000:
                        f.writelines(lines)
                        lines.clear()
        if lines:
            f.writelines(lines)

    total_franjas = franja_id - 1
    metricas_archivos["franjas_cedi.csv"] = {
        "filas": total_franjas,
        "bytes": os.path.getsize(f_franjas_path),
        "segundos": round(time.time() - t0, 2)
    }

    manifiesto_casos_borde["caso_4_ultima_franja_disponible"] = {
        "id": 4,
        "descripcion": "Última franja horaria disponible del día en un CEDI (capacidad_total=10, capacidad_reservada=9)",
        "tabla": "logistica.franjas_cedi",
        "franja_id": cb4_franja_id,
        "cedi_id": 1,
        "fecha": fecha_pivote.isoformat()
    }

    # -----------------------------------------------------------------------
    # 5. CDFs DE SESGO ZIPF Y ESTACIONALIDAD
    # -----------------------------------------------------------------------
    print("-> Precalculando funciones acumuladas (CDF) para Zipf y catálogo...")
    # Zipf sobre todos los proveedores (s=0.92, q=420)
    cdf_proveedores = construir_cdf_zipf(num_proveedores, ZIPF_PROV_S, ZIPF_PROV_Q)
    cdf_skus = construir_cdf_zipf(num_skus, ZIPF_CATALOG_S, 0)

    dias_fin_mes = [d for d in fechas_simulacion if es_fin_de_mes_habil(d)]
    dias_ordinarios = [d for d in fechas_simulacion if not es_fin_de_mes_habil(d)]

    # -----------------------------------------------------------------------
    # 6. GENERACIÓN: ordenes_compra.csv Y lineas_orden.csv
    # -----------------------------------------------------------------------
    f_ord_path = os.path.join(args.output_dir, "ordenes_compra.csv")
    f_lin_path = os.path.join(args.output_dir, "lineas_orden.csv")
    t0 = time.time()
    num_ordenes = cfg["ordenes"]
    print(f"[5/7 y 6/7] Generando {num_ordenes:,} órdenes y sus líneas en streaming...")

    linea_id = 1
    cb1_orden_id = 101
    cb6_orden_id = 606
    cb6_sku_ajeno = None
    cb6_linea_id = None
    cb7_hot_prov_id = 1
    cb8_zero_prov_id = 10
    mes_excluido = (2025, 6)

    conteo_ordenes_por_prov = {}

    # Aritmética de llaves (sin consultar la base):
    #   franja_id = dia_idx * (5 * franjas_por_dia) + (cedi - 1) * franjas_por_dia + slot + 1
    #   sku_id de la k-ésima oferta del proveedor p = p + k * num_contratos
    dias_sim = len(fechas_simulacion)
    inicio_sim = fechas_simulacion[0]
    franjas_por_dia_total = len(CEDIS) * franjas_por_dia
    ofertas_populares = max(1, round(FRACCION_OFERTAS_POPULARES * (num_skus // num_contratos)))

    with open(f_ord_path, "w", newline="", encoding="utf-8") as f_ord, \
         open(f_lin_path, "w", newline="", encoding="utf-8") as f_lin:

        f_ord.write("id,numero_orden,proveedor_id,franja_id,fecha_emision,estado,total_orden,idempotency_key,created_at,fecha_compromiso,fecha_entrega\n")
        f_lin.write("id,orden_id,sku_id,cantidad,precio_unitario,subtotal,cantidad_entregada\n")

        ord_lines = []
        lin_lines = []

        for o_id in range(1, num_ordenes + 1):
            num_orden = f"OC-2026-{o_id:08d}"

            # Caso Borde 7: Asegurar proveedor 1 como Hot (>5000 órdenes)
            if o_id <= 5250:
                p_id = cb7_hot_prov_id
            else:
                p_id = muestrear_zipf(cdf_proveedores, rng)

            # Estacionalidad Mensual
            if rng.random() < 0.25 and dias_fin_mes:
                f_date = rng.choice(dias_fin_mes)
            else:
                f_date = rng.choice(dias_ordinarios)

            # Caso Borde 8
            if p_id == cb8_zero_prov_id and f_date.year == mes_excluido[0] and f_date.month == mes_excluido[1]:
                f_date = f_date.replace(month=7)

            # Estacionalidad Horaria
            if rng.random() < 0.60:
                hora = rng.randint(8, 10)
            elif rng.random() < 0.90:
                hora = rng.randint(11, 18)
            else:
                hora = rng.choice([6, 7, 19, 20, 21])

            minuto = rng.randint(0, 59)
            segundo = rng.randint(0, 59)
            f_emision = f"{f_date.isoformat()}T{hora:02d}:{minuto:02d}:{segundo:02d}Z"

            # La franja reservada cae 1-7 días después de la emisión; la fecha de la franja se copia a la
            # orden como fecha_compromiso (snapshot: evita un JOIN entre esquemas para calcular OTIF).
            dia_idx = (f_date - inicio_sim).days
            comp_idx = min(dia_idx + rng.randint(1, 7), dias_sim - 1)
            franja_fk = comp_idx * franjas_por_dia_total + rng.randrange(franjas_por_dia_total) + 1
            fecha_compromiso = fechas_simulacion[comp_idx]

            # Si el proveedor no tiene contrato vigente (> num_contratos), orden rechazada
            if p_id > num_contratos:
                estado_ord = "RECHAZADA"
            else:
                estado_ord = rng.choice(["CONFIRMADA", "CONFIRMADA", "CONFIRMADA", "EN_PROCESO"])

            idemp_key = f"idemp-{o_id:08d}-{rng.randint(1000, 9999)}"

            # Cantidad de líneas
            if o_id == cb1_orden_id:
                num_lineas = 300
            else:
                u = rng.random()
                if u < 0.70:
                    num_lineas = rng.randint(1, 6)
                elif u < 0.95:
                    num_lineas = rng.randint(7, 15)
                else:
                    num_lineas = rng.randint(16, 35)

            # Entrega (solo órdenes CONFIRMADAS cuya entrega ya ocurrió a la fecha pivote):
            # a tiempo con prob. fiabilidad(p); completa con prob. fiabilidad'(p). Insumo de OTIF y fill rate.
            fecha_entrega = None
            entrega_completa = False
            if estado_ord == "CONFIRMADA":
                retraso = 0 if rng.random() < fiabilidad(p_id, 2654435761) else rng.randint(1, ENTREGA_MAX_RETRASO_DIAS)
                f_ent = fecha_compromiso + timedelta(days=retraso)
                if f_ent <= fecha_pivote:
                    fecha_entrega = f_ent
                    entrega_completa = rng.random() < fiabilidad(p_id, 40503)

            total_orden = 0.0
            n_ofertas = num_ofertas(p_id, num_skus, num_contratos) if p_id <= num_contratos else 0
            n_pop = min(ofertas_populares, n_ofertas)

            for l_idx in range(num_lineas):
                if p_id <= num_contratos:
                    # Proveedor con contrato: la línea es una oferta de SU catálogo negociado (RN-04)
                    if n_pop == n_ofertas or rng.random() < P_OFERTA_POPULAR:
                        k = rng.randrange(n_pop)
                    else:
                        k = n_pop + rng.randrange(n_ofertas - n_pop)
                    sku_fk = oferta_sku(p_id, k, num_contratos)
                else:
                    # Proveedor sin contrato (orden RECHAZADA): no tiene ofertas; SKU global con sesgo Zipf
                    sku_fk = muestrear_zipf(cdf_skus, rng)

                # Caso Borde 6: una línea con SKU de OTRO proveedor (fuera de su catálogo negociado)
                if o_id == cb6_orden_id and l_idx == 0:
                    sku_fk = oferta_sku(p_id % num_contratos + 1, 0, num_contratos)
                    cb6_sku_ajeno = sku_fk
                    cb6_linea_id = linea_id

                cantidad = rng.randint(5, 100)
                precio_unitario = precio_negociado(sku_fk)   # RN-05: precio de la línea = precio negociado
                subtotal = cantidad * precio_unitario
                total_orden += subtotal

                if fecha_entrega is None:
                    cant_entregada = ""
                elif entrega_completa or rng.random() < 0.5:
                    cant_entregada = cantidad
                else:
                    cant_entregada = max(0, int(cantidad * rng.uniform(0.4, 0.95)))

                lin_lines.append(f"{linea_id},{o_id},{sku_fk},{cantidad},{precio_unitario:.2f},{subtotal:.2f},{cant_entregada}\n")
                linea_id += 1

                if len(lin_lines) >= 10000:
                    f_lin.writelines(lin_lines)
                    lin_lines.clear()

            ord_lines.append(f"{o_id},{num_orden},{p_id},{franja_fk},{f_emision},{estado_ord},{total_orden:.2f},{idemp_key},{f_emision},"
                             f"{fecha_compromiso.isoformat()},{fecha_entrega.isoformat() if fecha_entrega else ''}\n")
            conteo_ordenes_por_prov[p_id] = conteo_ordenes_por_prov.get(p_id, 0) + 1

            if len(ord_lines) >= 10000:
                f_ord.writelines(ord_lines)
                ord_lines.clear()

        if lin_lines:
            f_lin.writelines(lin_lines)
        if ord_lines:
            f_ord.writelines(ord_lines)

    total_lineas = linea_id - 1
    metricas_archivos["ordenes_compra.csv"] = {
        "filas": num_ordenes,
        "bytes": os.path.getsize(f_ord_path),
        "segundos": round(time.time() - t0, 2)
    }
    metricas_archivos["lineas_orden.csv"] = {
        "filas": total_lineas,
        "bytes": os.path.getsize(f_lin_path),
        "segundos": round(time.time() - t0, 2)
    }

    manifiesto_casos_borde["caso_1_orden_300_lineas"] = {
        "id": 1,
        "descripcion": "Orden con 300 líneas de detalle (estrés de payload y memoria de transacción)",
        "tabla": "ordenes.ordenes_compra y ordenes.lineas_orden",
        "orden_id": cb1_orden_id,
        "total_lineas": 300
    }
    manifiesto_casos_borde["caso_6_sku_fuera_catalogo"] = {
        "id": 6,
        "descripcion": "SKU fuera del catálogo negociado del proveedor de la orden (camino de rechazo de negocio)",
        "tabla": "ordenes.lineas_orden",
        "orden_id": cb6_orden_id,
        "linea_id": cb6_linea_id,
        "sku_id_ajeno": cb6_sku_ajeno,
        "condicion": "Única línea de una orden con contrato cuyo SKU no es oferta del proveedor de la orden"
    }
    manifiesto_casos_borde["caso_7_proveedor_hot"] = {
        "id": 7,
        "descripcion": "Proveedor 'Hot' con más de 5,000 órdenes de compra (evalúa hot-partitioning y sesgo de caché)",
        "tabla": "proveedores.proveedores y ordenes.ordenes_compra",
        "proveedor_id": cb7_hot_prov_id,
        "ordenes_generadas": conteo_ordenes_por_prov.get(cb7_hot_prov_id, 0)
    }
    manifiesto_casos_borde["caso_8_mes_sin_ordenes"] = {
        "id": 8,
        "descripcion": "Proveedor activo con contrato pero con 0 órdenes en un mes específico (rompe cálculos OTIF)",
        "tabla": "ordenes.ordenes_compra",
        "proveedor_id": cb8_zero_prov_id,
        "mes_sin_ordenes": f"{mes_excluido[0]}-{mes_excluido[1]:02d}"
    }

    # -----------------------------------------------------------------------
    # 7. GENERACIÓN: eventos_auditoria.csv (Optimizado con f-strings)
    # -----------------------------------------------------------------------
    f_evt_path = os.path.join(args.output_dir, "eventos_auditoria.csv")
    t0 = time.time()
    num_eventos = cfg["eventos"]
    print(f"[7/7] Generando {num_eventos:,} eventos de auditoría en {f_evt_path}...")

    tipos_evento = [("OrdenConfirmada", "ordenes"), ("OrdenRechazada", "ordenes"), ("FranjaReservada", "logistica"), ("ContratoRenovado", "proveedores")]
    with open(f_evt_path, "w", newline="", encoding="utf-8") as f:
        f.write("id,fecha_evento,tipo_evento,modulo_origen,entidad_id,payload\n")
        lines = []
        for e_id in range(1, num_eventos + 1):
            f_evt = rng.choice(fechas_simulacion).isoformat() + f"T{rng.randint(8,18):02d}:{rng.randint(0,59):02d}:00Z"
            tipo, modulo = rng.choice(tipos_evento)
            ent_id = rng.randint(1, num_ordenes)
            payload = f'{{"evento_id":{e_id},"tipo":"{tipo}","usuario":"system_b2b","status":"SUCCESS"}}'
            # El JSON contiene comas y comillas: se entrecomilla (RFC 4180) para que COPY ... CSV lo lea como un solo campo
            payload_csv = '"' + payload.replace('"', '""') + '"'
            lines.append(f"{e_id},{f_evt},{tipo},{modulo},{ent_id},{payload_csv}\n")

            if len(lines) >= 10000:
                f.writelines(lines)
                lines.clear()
        if lines:
            f.writelines(lines)

    metricas_archivos["eventos_auditoria.csv"] = {
        "filas": num_eventos,
        "bytes": os.path.getsize(f_evt_path),
        "segundos": round(time.time() - t0, 2)
    }

    # -----------------------------------------------------------------------
    # GUARDAR MANIFIESTO DE CASOS BORDE Y REPORTE
    # -----------------------------------------------------------------------
    import json
    f_json_path = os.path.join("datos", "casos_borde.json")
    with open(f_json_path, "w", encoding="utf-8", newline="\n") as f_json:
        json.dump(dict(sorted(manifiesto_casos_borde.items(), key=lambda kv: kv[1]["id"])),
                  f_json, indent=2, ensure_ascii=False)

    # Parámetros de generación: fuente única para documentar s (Zipf) y reproducir el conjunto
    f_par_path = os.path.join("datos", "parametros_generacion.json")
    with open(f_par_path, "w", encoding="utf-8", newline="\n") as f_par:
        json.dump({
            "seed": args.seed,
            "scale": args.scale,
            "fecha_pivote": fecha_pivote.isoformat(),
            "volumenes": cfg,
            "zipf_proveedores": {"modelo": "Zipf-Mandelbrot", "s": ZIPF_PROV_S, "q": ZIPF_PROV_Q,
                                 "peso": "1 / (rango + q) ** s", "ordenes_forzadas_proveedor_1": 5250},
            "zipf_catalogo_global": {"s": ZIPF_CATALOG_S, "aplica_a": "líneas de órdenes de proveedores sin contrato"},
            "sesgo_catalogo": {"p_oferta_popular": P_OFERTA_POPULAR,
                               "fraccion_ofertas_populares": FRACCION_OFERTAS_POPULARES},
            "entrega": {"max_retraso_dias": ENTREGA_MAX_RETRASO_DIAS,
                        "fiabilidad": "0.72 + 0.26 * ((id * m) % 1000 / 999), m=2654435761 (a tiempo), m=40503 (completa)"},
        }, f_par, indent=2, ensure_ascii=False)

    duracion_total = round(time.time() - t_inicio, 2)
    total_filas = sum(m["filas"] for m in metricas_archivos.values())
    total_bytes = sum(m["bytes"] for m in metricas_archivos.values())

    print("\n=====================================================================")
    print("GENERACIÓN COMPLETADA CON ÉXITO")
    print("=====================================================================")
    print(f"Tiempo total: {duracion_total} s")
    print(f"Total de registros: {total_filas:,} filas")
    print(f"Tamaño en disco: {total_bytes / (1024*1024):.2f} MB")
    print(f"Manifiesto de Casos Borde: {f_json_path}")
    print("---------------------------------------------------------------------")
    for nombre, m in metricas_archivos.items():
        print(f" - {nombre:<25}: {m['filas']:>10,} filas | {m['bytes']/(1024*1024):>6.2f} MB | {m['segundos']:>5.2f} s")
    print("=====================================================================")


if __name__ == "__main__":
    main()

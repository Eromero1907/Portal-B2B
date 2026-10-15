"""Pruebas de aceptación de la plataforma (criterio de "listo" del relevo 1).

Se ejecutan contra nginx (las 3 instancias) y verifican en la base cada efecto de negocio:
  P01  orden válida → CONFIRMADA, 1 reserva CONFIRMADA, 1 evento OrdenConfirmada en outbox, cupo +1
  P02  proveedor sin contrato (caso borde 5: 55555) → RECHAZADA sin_contrato_vigente
  P03  contrato vencido ayer (caso borde 2: proveedor 2) → RECHAZADA
  P04  SKU fuera del catálogo del proveedor (caso borde 6) → RECHAZADA
  P05  precio distinto al negociado (RN-05) → RECHAZADA
  P06  crédito denegado por el externo → RECHAZADA y el cupo se devuelve
  P07  confirmación sin Idempotency-Key → 400
  P08  misma Idempotency-Key en otra orden → 422
  P09  orden inexistente → 404
  P10  RN-13: 50 confirmaciones CONCURRENTES con la misma clave → un solo efecto (1 orden, 1 franja, 1 evento)
  P11  RN-13: 10 claves distintas a la vez sobre la misma orden → un solo efecto
  P12  RN-08: 20 órdenes compiten por el último cupo de la franja 91150 (caso borde 4) → exactamente 1 gana,
       la franja termina en 10/10 y nunca se sobrevende, aunque las atiendan instancias distintas
  P13  el balanceador reparte entre app1, app2 y app3
Requiere estado limpio (make reset-estado). Sale con código 1 si alguna falla.
"""
import asyncio
import json
import os
import sys
from collections import Counter

import httpx
import psycopg

URL = os.environ.get("PORTAL_URL", "http://nginx:80")
DSN = os.environ.get("BD_DSN", "postgresql://postgres:portal@db:5432/portal_b2b")
resultados = []


def verificar(codigo, descripcion, ok, detalle=""):
    resultados.append({"prueba": codigo, "descripcion": descripcion, "resultado": "PASA" if ok else "FALLA",
                       "detalle": detalle})
    print(f"{'PASA ' if ok else 'FALLA'} {codigo} {descripcion}" + (f"  [{detalle}]" if detalle else ""), flush=True)


def credito_deniega(prov):  # misma regla determinista del stub
    return (prov * 2654435761) % 100 < 3


def bd(sql, params=()):
    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def ofertas(prov, n=3):
    return [{"sku_id": s, "cantidad": 10, "precio_unitario": str(p)} for s, p in
            bd("SELECT id, precio_negociado FROM catalogo.sku_catalogo WHERE proveedor_id = %s ORDER BY id LIMIT %s",
               (prov, n))]


async def crear(c, prov, franja, lineas, clave=None):
    h = {"Idempotency-Key": clave} if clave else {}
    r = await c.post("/ordenes-compra", json={"proveedor_id": prov, "franja_id": franja, "lineas": lineas}, headers=h)
    assert r.status_code in (200, 201), r.text
    return r.json()["orden_id"]


async def confirmar(c, orden_id, clave):
    h = {"Idempotency-Key": clave} if clave else {}
    return await c.post(f"/ordenes-compra/{orden_id}/confirmacion", headers=h)


def efectos(orden_id):
    reservas = bd("SELECT estado, count(*) FROM logistica.reservas WHERE orden_id = %s GROUP BY estado", (orden_id,))
    eventos = bd("SELECT count(*) FROM ordenes.outbox WHERE agregado_id = %s", (orden_id,))[0][0]
    estado = bd("SELECT estado FROM ordenes.ordenes_compra WHERE id = %s", (orden_id,))[0][0]
    return dict(reservas), eventos, estado


async def main():
    if bd("SELECT count(*) FROM ordenes.ordenes_compra WHERE numero_orden LIKE 'OC-E3-%%'")[0][0]:
        sys.exit("Estado sucio: ejecuta `make reset-estado` antes de las pruebas.")
    futuras = [f for (f,) in bd("SELECT id FROM logistica.franjas_cedi WHERE fecha >= '2026-09-17' ORDER BY id LIMIT 40")]
    prov_ok = next(p for p in range(9000, 10001) if not credito_deniega(p))
    prov_denegado = next(p for p in range(9000, 10001) if credito_deniega(p))

    async with httpx.AsyncClient(base_url=URL, timeout=60) as c:
        # P01
        franja = futuras[0]
        antes = bd("SELECT capacidad_reservada FROM logistica.franjas_cedi WHERE id = %s", (franja,))[0][0]
        oid = await crear(c, prov_ok, franja, ofertas(prov_ok))
        r = await confirmar(c, oid, "p01")
        res, ev, est = efectos(oid)
        despues = bd("SELECT capacidad_reservada FROM logistica.franjas_cedi WHERE id = %s", (franja,))[0][0]
        verificar("P01", "orden válida se confirma con un solo efecto",
                  r.status_code == 200 and r.json()["estado"] == "CONFIRMADA" and res == {"CONFIRMADA": 1}
                  and ev == 1 and est == "CONFIRMADA" and despues == antes + 1,
                  f"http={r.status_code} reservas={res} eventos={ev} cupo {antes}->{despues}")
        cuerpo_p01 = r.json()

        # P02 – P05
        for codigo, desc, prov, lineas, causa in [
            ("P02", "proveedor sin contrato (55555) se rechaza", 55555, ofertas(prov_ok), "sin_contrato_vigente"),
            ("P03", "contrato vencido ayer (proveedor 2) se rechaza", 2, ofertas(2), "sin_contrato_vigente"),
            ("P04", "SKU fuera del catálogo del proveedor se rechaza", prov_ok, ofertas(prov_ok + 1),
             "sku_fuera_de_catalogo_o_precio"),
            ("P05", "precio distinto al negociado se rechaza", prov_ok,
             [{**l, "precio_unitario": "1.00"} for l in ofertas(prov_ok, 1)], "sku_fuera_de_catalogo_o_precio"),
        ]:
            oid = await crear(c, prov, futuras[1], lineas)
            r = await confirmar(c, oid, f"{codigo.lower()}")
            res, ev, est = efectos(oid)
            verificar(codigo, desc, r.status_code == 200 and r.json()["estado"] == "RECHAZADA"
                      and r.json()["causa"] == causa and not res and ev == 0 and est == "RECHAZADA",
                      f"http={r.status_code} causa={r.json().get('causa')} reservas={res} eventos={ev}")

        # P06
        franja = futuras[2]
        antes = bd("SELECT capacidad_reservada FROM logistica.franjas_cedi WHERE id = %s", (franja,))[0][0]
        oid = await crear(c, prov_denegado, franja, ofertas(prov_denegado))
        r = await confirmar(c, oid, "p06")
        res, ev, est = efectos(oid)
        despues = bd("SELECT capacidad_reservada FROM logistica.franjas_cedi WHERE id = %s", (franja,))[0][0]
        verificar("P06", "crédito denegado: RECHAZADA y el cupo se devuelve",
                  r.json().get("causa") == "credito_denegado" and res == {"LIBERADA": 1} and ev == 0 and despues == antes,
                  f"causa={r.json().get('causa')} reservas={res} cupo {antes}->{despues}")

        # P07 – P09
        oid = await crear(c, prov_ok, futuras[3], ofertas(prov_ok))
        r = await confirmar(c, oid, None)
        verificar("P07", "confirmación sin Idempotency-Key → 400", r.status_code == 400, f"http={r.status_code}")
        r = await confirmar(c, oid, "p01")
        verificar("P08", "clave reutilizada en otra orden → 422", r.status_code == 422, f"http={r.status_code}")
        r = await confirmar(c, 999_999_999, "p09")
        verificar("P09", "orden inexistente → 404", r.status_code == 404, f"http={r.status_code}")

        # P10 · 50 reintentos concurrentes, misma clave
        franja = futuras[4]
        antes = bd("SELECT capacidad_reservada FROM logistica.franjas_cedi WHERE id = %s", (franja,))[0][0]
        oid = await crear(c, prov_ok, franja, ofertas(prov_ok))
        respuestas = await asyncio.gather(*[confirmar(c, oid, "p10-misma-clave") for _ in range(50)])
        codigos = Counter(r.status_code for r in respuestas)
        # después de que todo terminó, 50 reintentos secuenciales deben devolver la MISMA respuesta guardada
        repetidas = [await confirmar(c, oid, "p10-misma-clave") for _ in range(50)]
        cuerpos = {json.dumps(r.json(), sort_keys=True) for r in repetidas}
        res, ev, est = efectos(oid)
        despues = bd("SELECT capacidad_reservada FROM logistica.franjas_cedi WHERE id = %s", (franja,))[0][0]
        verificar("P10", "50 reintentos con la misma clave → una orden, una franja, un evento",
                  set(codigos) <= {200, 409} and res == {"CONFIRMADA": 1} and ev == 1 and est == "CONFIRMADA"
                  and despues == antes + 1 and len(cuerpos) == 1 and all(r.status_code == 200 for r in repetidas),
                  f"concurrentes={dict(codigos)} reservas={res} eventos={ev} cupo {antes}->{despues} "
                  f"respuestas_distintas_tras_completar={len(cuerpos)}")

        # P11 · 10 claves distintas a la vez sobre la misma orden
        oid = await crear(c, prov_ok, futuras[5], ofertas(prov_ok))
        respuestas = await asyncio.gather(*[confirmar(c, oid, f"p11-{i}") for i in range(10)])
        res, ev, est = efectos(oid)
        verificar("P11", "10 claves distintas sobre la misma orden → un solo efecto",
                  res == {"CONFIRMADA": 1} and ev == 1 and est == "CONFIRMADA",
                  f"codigos={dict(Counter(r.status_code for r in respuestas))} reservas={res} eventos={ev}")

        # P12 · el último cupo de la franja 91150, disputado por 20 órdenes a la vez
        (total, reservada), = bd("SELECT capacidad_total, capacidad_reservada FROM logistica.franjas_cedi WHERE id = 91150")
        libres = total - reservada
        oids = [await crear(c, prov_ok, 91150, ofertas(prov_ok)) for _ in range(20)]
        respuestas = await asyncio.gather(*[confirmar(c, o, f"p12-{o}") for o in oids])
        ganadoras = sum(1 for r in respuestas if r.json().get("estado") == "CONFIRMADA")
        sin_cupo = sum(1 for r in respuestas if r.json().get("causa") == "sin_cupo_franja")
        instancias = Counter(r.headers.get("x-instancia") for r in respuestas)
        (final,), = bd("SELECT capacidad_reservada FROM logistica.franjas_cedi WHERE id = 91150")
        verificar("P12", "20 órdenes por el último cupo: gana exactamente 1 y no hay sobreventa",
                  libres == 1 and ganadoras == 1 and sin_cupo == 19 and final == total,
                  f"cupos_libres_antes={libres} ganadoras={ganadoras} sin_cupo={sin_cupo} final={final}/{total} "
                  f"instancias={dict(instancias)}")

        # P13 · reparto del balanceador
        vistas = Counter()
        for _ in range(60):
            vistas[(await c.get("/salud")).headers.get("x-instancia")] += 1
        verificar("P13", "nginx reparte entre las 3 instancias", set(vistas) == {"app1", "app2", "app3"},
                  f"{dict(vistas)}")

    violaciones = bd("SELECT count(*) FROM logistica.franjas_cedi WHERE capacidad_reservada > capacidad_total")[0][0]
    verificar("INV", "invariante reservada ≤ capacidad en todas las franjas", violaciones == 0,
              f"violaciones={violaciones}")

    salida = os.environ.get("SALIDA_PRUEBAS")
    if salida:
        os.makedirs(os.path.dirname(salida) or ".", exist_ok=True)
        with open(salida, "w", encoding="utf-8") as f:
            json.dump({"resultados": resultados, "respuesta_p01": cuerpo_p01}, f, indent=2, ensure_ascii=False)
    fallas = [r for r in resultados if r["resultado"] == "FALLA"]
    print(f"\n{len(resultados) - len(fallas)} de {len(resultados)} pruebas PASAN")
    sys.exit(1 if fallas else 0)


if __name__ == "__main__":
    asyncio.run(main())

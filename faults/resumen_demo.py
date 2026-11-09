"""Resumen de la demo en vivo por ventana: ANTES de inyectar · DURANTE la combinación · DESPUÉS del kill switch.

Lee resultados/demo_<estado>/solicitudes.csv + resumen.json (inicio_epoch del generador) + marcas.json (epoch de la inyección
y del kill switch, escritas por faults/demo_vivo.sh) y escribe resultados/demo_<estado>/ventanas.md. Con los dos estados
medidos escribe además resultados/demo_comparacion.md (estado inicial vs estado final, misma combinación y misma carga).

Por qué por ventana: el promedio de toda la corrida mezcla 35 s de falla con 50 s sanos y esconde el efecto. La rúbrica
pide distinguir recuperación (volver a la línea base al quitar la falla) de corrección (comportarse mejor DURANTE la falla).

  python faults/resumen_demo.py                       # los dos estados que existan
  python faults/resumen_demo.py estado_final_con_resiliencia
Solo biblioteca estándar.
"""
import csv
import json
import sys
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent / "resultados"
ESTADOS = {"estado_inicial_sin_resiliencia": "Estado inicial (sin resiliencia)",
           "estado_final_con_resiliencia": "Estado final (perfil M + umbral 70 % + lock_timeout)"}
MARGEN_S = 2.0  # se descartan 2 s alrededor de cada marca (transición)


def pct(v, p):
    if not v:
        return None
    v = sorted(v)
    k = (len(v) - 1) * p / 100
    i = int(k)
    return v[i] if i + 1 >= len(v) else v[i] + (v[i + 1] - v[i]) * (k - i)


def ventanas(d: Path):
    resumen = json.loads((d / "resumen.json").read_text(encoding="utf-8"))
    marcas = json.loads((d / "marcas.json").read_text(encoding="utf-8"))
    t0 = resumen.get("inicio_epoch") or 0
    calent = resumen["perfil"]["calentamiento_s"]
    fin = calent + resumen["perfil"]["duracion_s"]
    iny, ks = marcas["inyeccion_epoch"] - t0, marcas["kill_switch_epoch"] - t0
    if not t0:
        raise SystemExit(f"{d}: resumen.json sin inicio_epoch (corrida anterior al cambio del generador)")
    return {"antes": (calent, iny - MARGEN_S), "durante": (iny + MARGEN_S, ks), "despues": (ks + MARGEN_S, fin)}, iny, ks


def medir(filas, a, b):
    sel = [f for f in filas if a <= float(f["inicio_s"]) < b]
    conf = [f for f in sel if f["fase"] == "confirmar"]
    err = lambda fs: [f for f in fs if f["codigo"] in ("0", "") or int(f["codigo"]) >= 500]
    lat_g = [float(f["latencia_ms"]) for f in sel]
    lat_c = [float(f["latencia_ms"]) for f in conf]
    causas = Counter(f"{f['codigo']} {f['causa'][:24] or '-'}" for f in err(conf))
    return {"segundos": round(b - a, 1), "n": len(sel), "n_conf": len(conf),
            "err_global_pct": 100 * len(err(sel)) / len(sel) if sel else None,
            "err_conf_pct": 100 * len(err(conf)) / len(conf) if conf else None,
            "p50": pct(lat_g, 50), "p95": pct(lat_g, 95), "p99": pct(lat_g, 99), "max": max(lat_g) if lat_g else None,
            "conf_p95": pct(lat_c, 95), "conf_p99": pct(lat_c, 99), "conf_max": max(lat_c) if lat_c else None,
            "breaker_abierto": sum(1 for f in conf if f["causa"] == "breaker_abierto"),
            "franja_bloqueada": sum(1 for f in conf if f["causa"] == "franja_bloqueada"),
            "causas": causas.most_common(4)}


def f(x, dec=1):
    return "—" if x is None else f"{x:,.{dec}f}".replace(",", " ").replace(".", ",")


def resumir(estado: str):
    d = RAIZ / f"demo_{estado}"
    filas = list(csv.DictReader(open(d / "solicitudes.csv", encoding="utf-8")))
    vs, iny, ks = ventanas(d)
    res = {k: medir(filas, *v) for k, v in vs.items()}
    md = [f"# {ESTADOS.get(estado, estado)} · combinación A1 + D2 + B2 en caliente", "",
          f"Inyección en inicio_s = {iny:.1f} s · kill switch en {ks:.1f} s · se descartan {MARGEN_S:.0f} s en cada transición. "
          "Latencias del cliente en ms; error = 5xx o sin respuesta.", "",
          "| Ventana | s | Solicitudes | % error global | % error confirmar | p50 | p95 | p99 | máx | p99 confirmar | máx confirmar | breaker_abierto | franja_bloqueada |",
          "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for k, r in res.items():
        md.append(f"| {k} | {f(r['segundos'])} | {r['n']} | {f(r['err_global_pct'], 2)} | {f(r['err_conf_pct'], 2)} | "
                  f"{f(r['p50'])} | {f(r['p95'])} | {f(r['p99'])} | {f(r['max'], 0)} | {f(r['conf_p99'])} | {f(r['conf_max'], 0)} | "
                  f"{r['breaker_abierto']} | {r['franja_bloqueada']} |")
    md += ["", "Causas de error en confirmar durante la falla: " +
           (", ".join(f"`{c}` × {n}" for c, n in res["durante"]["causas"]) or "ninguna")]
    (d / "ventanas.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md) + "\n")
    return res


def comparar(ini, fin):
    filas = [("% error global", "err_global_pct", 2), ("% error confirmar", "err_conf_pct", 2), ("p95 global (ms)", "p95", 1),
             ("p99 global (ms)", "p99", 1), ("p99 confirmar (ms)", "conf_p99", 1), ("máx confirmar (ms)", "conf_max", 0),
             ("respuestas breaker_abierto", "breaker_abierto", 0), ("503 franja_bloqueada (lock_timeout)", "franja_bloqueada", 0)]
    md = ["# Demo en vivo · estado inicial vs estado final (misma combinación A1 + D2 + B2, misma carga y semilla)", "",
          "Ventana DURANTE la falla. La comparación válida es esta: el estado final se comporta mejor *mientras* la falla está activa. "
          "Que ambos vuelvan a la línea base después del kill switch es recuperación, no corrección.", "",
          "| Métrica (durante la falla) | Estado inicial | Estado final | Cambio |", "|---|---:|---:|---:|"]
    for nombre, k, dec in filas:
        a, b = ini["durante"][k], fin["durante"][k]
        cambio = "—" if not a or b is None else f"{100 * (b - a) / a:+.0f} %".replace(".", ",")
        md.append(f"| {nombre} | {f(a, dec)} | {f(b, dec)} | {cambio} |")
    md += ["", "| Línea base (antes de inyectar) | Estado inicial | Estado final |", "|---|---:|---:|"]
    for nombre, k, dec in filas[:4]:
        md.append(f"| {nombre} | {f(ini['antes'][k], dec)} | {f(fin['antes'][k], dec)} |")
    md += ["", "SLO RNF-10 (p95 < 400 ms y error < 0,5 %) durante la falla: "
           f"inicial {'CUMPLE' if ini['durante']['p95'] < 400 and ini['durante']['err_global_pct'] < 0.5 else 'NO cumple'}, "
           f"final {'CUMPLE' if fin['durante']['p95'] < 400 and fin['durante']['err_global_pct'] < 0.5 else 'NO cumple'}."]
    (RAIZ / "demo_comparacion.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


def main():
    pedidos = sys.argv[1:] or [e for e in ESTADOS if (RAIZ / f"demo_{e}" / "marcas.json").exists()]
    res = {e: resumir(e) for e in pedidos}
    ini, fin = res.get("estado_inicial_sin_resiliencia"), res.get("estado_final_con_resiliencia")
    if ini is None and fin is not None and (RAIZ / "demo_estado_inicial_sin_resiliencia" / "marcas.json").exists():
        ini = resumir("estado_inicial_sin_resiliencia")
    if fin is None and ini is not None and (RAIZ / "demo_estado_final_con_resiliencia" / "marcas.json").exists():
        fin = resumir("estado_final_con_resiliencia")
    if ini and fin:
        comparar(ini, fin)


if __name__ == "__main__":
    main()

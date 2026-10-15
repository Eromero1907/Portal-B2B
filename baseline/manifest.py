"""Manifest de una corrida de línea base (rúbrica §1: "Configuración: seed, parámetros y versión").

Registra todo lo necesario para reproducir y comparar la corrida: semilla y escala de los datos, conteos por
entidad, versión y parámetros de PostgreSQL, imágenes Docker, configuración de la plataforma, máquina y commit.
Solo biblioteca estándar; consulta la base con datos/psql.sh (psql dentro del contenedor).

  python baseline/manifest.py --salida baseline/corridas/<id> [--nota "texto"]
"""
import argparse
import ctypes
import json
import os
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
TABLAS = ["proveedores.proveedores", "proveedores.contratos_suministro", "catalogo.sku_catalogo",
          "logistica.franjas_cedi", "ordenes.ordenes_compra", "ordenes.lineas_orden", "auditoria.eventos_auditoria"]
PARAMETROS_PG = ["shared_buffers", "work_mem", "effective_cache_size", "max_wal_size", "synchronous_commit", "fsync",
                 "random_page_cost", "max_parallel_workers_per_gather", "track_io_timing", "max_connections",
                 "TimeZone", "jit"]


def _cmd(args, **kw) -> str:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=60, cwd=RAIZ, **kw).stdout.strip()
    except Exception as e:  # noqa: BLE001 — el manifest registra lo que pueda, nunca aborta la corrida
        return f"no_disponible ({type(e).__name__})"


def _bash() -> str:
    return os.environ.get("BASH_BIN") or ("C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else "bash")


def sql(consulta: str) -> str:
    return _cmd([_bash(), "datos/psql.sh", "-X", "-q", "-At", "-F", "|", "-d", "portal_b2b", "-c", consulta],
                env={**os.environ, "MSYS_NO_PATHCONV": "1"})


def maquina() -> dict:
    info = {"sistema": platform.platform(), "python_host": platform.python_version(), "nucleos_logicos": os.cpu_count()}
    if os.name == "nt":
        info["cpu"] = _cmd(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_Processor).Name"])

        class _Mem(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]
        m = _Mem()
        m.dwLength = ctypes.sizeof(_Mem)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        info["ram_gb"] = round(m.ullTotalPhys / 1024 ** 3, 1)
    else:
        try:
            cpu = [l for l in Path("/proc/cpuinfo").read_text().splitlines() if l.startswith("model name")]
            info["cpu"] = cpu[0].split(":", 1)[1].strip() if cpu else platform.processor()
            mem = [l for l in Path("/proc/meminfo").read_text().splitlines() if l.startswith("MemTotal")]
            info["ram_gb"] = round(int(mem[0].split()[1]) / 1024 ** 2, 1) if mem else None
        except OSError:
            info["cpu"] = platform.processor()
    info["docker"] = _cmd(["docker", "version", "--format", "{{.Server.Version}}"])
    info["docker_cpus"] = _cmd(["docker", "info", "--format", "{{.NCPU}}"])
    info["docker_mem_gb"] = _cmd(["docker", "info", "--format", "{{.MemTotal}}"])
    try:
        info["docker_mem_gb"] = round(int(info["docker_mem_gb"]) / 1024 ** 3, 1)
    except ValueError:
        pass
    return info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--salida", required=True)
    ap.add_argument("--nota", default="")
    args = ap.parse_args()
    salida = Path(args.salida)
    salida.mkdir(parents=True, exist_ok=True)

    params_gen = json.loads((RAIZ / "datos" / "parametros_generacion.json").read_text(encoding="utf-8"))
    conteos = {}
    for t in TABLAS:
        v = sql(f"SELECT count(*) FROM {t}")
        conteos[t] = int(v) if v.isdigit() else v
    pg = {"version": sql("SELECT version()")}
    for p in PARAMETROS_PG:
        pg[p] = sql(f"SHOW {p}")
    imagenes = {}
    for contenedor in ["pg-portal-b2b", "portal-app1", "portal-app2", "portal-app3", "portal-nginx",
                       "portal-stub-credito"]:
        imagenes[contenedor] = _cmd(["docker", "inspect", "--format", "{{.Config.Image}} {{.Image}}", contenedor]) or "no_corriendo"
    plataforma = {}
    for contenedor in ["portal-app1", "portal-stub-credito"]:
        env = _cmd(["docker", "inspect", "--format", "{{json .Config.Env}}", contenedor])
        try:
            plataforma[contenedor] = {e.split("=", 1)[0]: e.split("=", 1)[1] for e in json.loads(env)
                                      if e.split("=", 1)[0] in {"BD_POOL_MIN", "BD_POOL_MAX", "BD_POOL_TIMEOUT_S",
                                                                "CREDITO_TIMEOUT_S", "RESERVA_TTL_S", "FECHA_OPERACION",
                                                                "LATENCIA_BASE_MS", "PORCENTAJE_SIN_CUPO"}}
        except (json.JSONDecodeError, TypeError):
            plataforma[contenedor] = "no_corriendo"

    manifest = {
        "corrida": salida.name,
        "fecha_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "nota": args.nota,
        "git": {"commit": _cmd(["git", "rev-parse", "HEAD"]), "rama": _cmd(["git", "rev-parse", "--abbrev-ref", "HEAD"]),
                "cambios_sin_commit": bool(_cmd(["git", "status", "--porcelain"]))},
        "datos": {"semilla": params_gen.get("seed"), "escala": params_gen.get("scale"),
                  "fecha_pivote": params_gen.get("fecha_pivote"), "zipf_proveedores": params_gen.get("zipf_proveedores"),
                  "conteos_por_entidad": conteos},
        "postgresql": pg,
        "imagenes_docker": imagenes,
        "plataforma": plataforma,
        "maquina": maquina(),
        "protocolo": {
            "q1_q5": "medicion/medir.py: 20 de calentamiento + 200 mediciones por consulta y escenario, "
                     "force_custom_plan, latencia en el cliente hasta fetchall(), numpy.percentile lineal",
            "q3_concurrente": "medicion/concurrencia_q3.py, 16/32/64 hilos, DURACION_S por punto",
            "estrategias": "baseline/estrategias.py sobre medicion/benchmark_carga.py (S = 375 199 filas)",
            "ruta_confirmacion": "carga/generador.py, modelo abierto Poisson con semilla",
        },
    }
    (salida / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Manifest → {salida / 'manifest.json'}")


if __name__ == "__main__":
    main()

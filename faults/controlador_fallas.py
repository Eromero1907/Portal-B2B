#!/usr/bin/env python3
"""Controlador de Fallas y Resiliencia (Relevo 2).

Permite orquestar, activar, desactivar y monitorear las 8 fallas del sistema:
- Fallas en proceso (A1, A2, D2): modifican `faults/faults.yaml` con recarga en caliente en el stub.
- Fallas de base de datos (B1, B2): caída temporal de contenedor PostgreSQL o contención con lock en franja 91150.
- Fallas de recursos y cola (C1, C2): estrangulamiento de CPU con Docker o pausa del consumidor de eventos.
- Fallas de caída de instancia (D1): detención/muerte temporal de portal-app2.

Incluye Kill Switch Global (`enabled: false`) y reversión inmediata de infraestructura.
"""
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

import yaml

FAULTS_FILE = Path(__file__).resolve().parent / "faults.yaml"


def cargar_config() -> dict:
    if not FAULTS_FILE.exists():
        raise FileNotFoundError(f"No se encontró {FAULTS_FILE}")
    with open(FAULTS_FILE, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def guardar_config(data: dict) -> None:
    with open(FAULTS_FILE, "w", encoding="utf-8") as f:
        yaml.dump(data, f, sort_keys=False, allow_unicode=True)


def ejecutar_cmd(cmd: list[str], check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def _duracion_falla(falla_id: str, defecto: int = 45) -> int:
    if os.environ.get("FALLA_DURACION_S"):          # lo fija experimento.sh (p. ej. variante lock0 de B2)
        return int(os.environ["FALLA_DURACION_S"])
    for fcfg in cargar_config().get("fallas", []):
        if fcfg.get("id", "").upper() == falla_id:
            return int(fcfg.get("duracion_s", defecto))
    return defecto


def _psql_en_db(sql: str, appname: str, detach: bool = False) -> subprocess.CompletedProcess:
    cmd = ["docker", "exec"] + (["-d"] if detach else []) + [
        "-e", "PGUSER=postgres", "-e", f"PGAPPNAME={appname}", "pg-portal-b2b",
        "psql", "-X", "-q", "-At", "-d", "portal_b2b", "-c", sql]
    return ejecutar_cmd(cmd)


def liberar_bloqueo_b2() -> None:
    """Termina la sesión que retiene el FOR UPDATE de la franja 91150 (ROLLBACK implícito). Idempotente."""
    _psql_en_db("SELECT count(pg_terminate_backend(pid)) FROM pg_stat_activity WHERE application_name = 'falla-B2'",
                "controlador")


def estado_plataforma() -> None:
    cfg = cargar_config()
    activo_ks = cfg.get("enabled", False)
    print("=" * 65)
    print(" ESTADO DEL MOTOR DE FALLAS (faults.yaml)")
    print("=" * 65)
    print(f" Kill Switch Global: {'DESACTIVADO (Fallas activables)' if activo_ks else 'ACTIVADO (Fallas deshabilitadas globalmente)'}")
    print("-" * 65)
    print(f" {'ID':<4} | {'Familia':<10} | {'Activa':<7} | {'Nombre'}")
    print("-" * 65)
    for fcfg in cfg.get("fallas", []):
        fid = fcfg.get("id", "")
        activa = "SI" if fcfg.get("enabled", False) else "NO"
        familia = fcfg.get("familia", "")
        nombre = fcfg.get("nombre", "")
        print(f" {fid:<4} | {familia:<10} | {activa:<7} | {nombre}")
    print("=" * 65)


def activar_falla(falla_id: str) -> None:
    falla_id = falla_id.upper()
    cfg = cargar_config()
    encontrada = False

    # Al activar una falla, aseguramos que el switch global permita fallas
    cfg["enabled"] = True

    for fcfg in cfg.get("fallas", []):
        if fcfg.get("id", "").upper() == falla_id:
            fcfg["enabled"] = True
            encontrada = True
            break

    if not encontrada:
        print(f"Error: Falla '{falla_id}' no encontrada en faults.yaml")
        sys.exit(1)

    guardar_config(cfg)
    print(f"[OK] Falla {falla_id} marcada como ACTIVA en faults.yaml (Kill switch: enabled=true)")

    # Acciones de infraestructura según la falla
    if falla_id == "B1":
        print("  -> Aplicando falla B1 (Infra): deteniendo contenedor pg-portal-b2b...")
        ejecutar_cmd(["docker", "stop", "pg-portal-b2b"])
    elif falla_id == "C1":
        cpus = os.environ.get("C1_CPUS", "0.25")      # variante cpu010 de C1: C1_CPUS=0.10
        print(f"  -> Aplicando falla C1 (Infra): CPU de portal-app1 limitada a {cpus} CPUs...")
        ejecutar_cmd(["docker", "update", "--cpus", cpus, "portal-app1"])
    elif falla_id == "C2":
        print("  -> Aplicando falla C2 (Infra): pausando consumidor de outbox (portal-consumidor-eventos)...")
        ejecutar_cmd(["docker", "pause", "portal-consumidor-eventos"])
    elif falla_id == "D1":
        print("  -> Aplicando falla D1 (Infra): SIGKILL a portal-app2 (docker kill)...")
        ejecutar_cmd(["docker", "kill", "portal-app2"])
    elif falla_id == "B2":
        retener = _duracion_falla("B2") + 10  # margen: el controlador la libera antes con pg_terminate_backend
        print(f"  -> Aplicando falla B2: sesión con SELECT ... FOR UPDATE sobre franjas_cedi id=91150 (hasta {retener} s)...")
        _psql_en_db(f"SELECT id FROM logistica.franjas_cedi WHERE id = 91150 FOR UPDATE; SELECT pg_sleep({retener});",
                    "falla-B2", detach=True)
        time.sleep(1.0)
        r = _psql_en_db("SELECT count(*) FROM pg_locks l JOIN pg_stat_activity a USING (pid) "
                        "WHERE a.application_name = 'falla-B2' AND l.locktype = 'transactionid' AND l.granted", "controlador")
        print(f"  -> Verificación: sesión falla-B2 reteniendo bloqueo = {r.stdout.strip() or '?'} (esperado 1)")


def desactivar_falla(falla_id: str) -> None:
    falla_id = falla_id.upper()
    cfg = cargar_config()
    encontrada = False

    for fcfg in cfg.get("fallas", []):
        if fcfg.get("id", "").upper() == falla_id:
            fcfg["enabled"] = False
            encontrada = True
            break

    if not encontrada:
        print(f"Error: Falla '{falla_id}' no encontrada en faults.yaml")
        sys.exit(1)

    guardar_config(cfg)
    print(f"[OK] Falla {falla_id} marcada como INACTIVA en faults.yaml")

    # Reversión de infraestructura
    if falla_id == "B1":
        print("  -> Revirtiendo B1: iniciando pg-portal-b2b...")
        ejecutar_cmd(["docker", "start", "pg-portal-b2b"])
    elif falla_id == "C1":
        print("  -> Revirtiendo C1: restaurando CPU sin límite en portal-app1...")
        ejecutar_cmd(["docker", "update", "--cpus", "0", "portal-app1"])
    elif falla_id == "C2":
        print("  -> Revirtiendo C2: reanudando portal-consumidor-eventos...")
        ejecutar_cmd(["docker", "unpause", "portal-consumidor-eventos"])
    elif falla_id == "D1":
        print("  -> Revirtiendo D1: reiniciando portal-app2...")
        ejecutar_cmd(["docker", "start", "portal-app2"])
    elif falla_id == "B2":
        print("  -> Revirtiendo B2: terminando la sesión que retiene el bloqueo (ROLLBACK)...")
        liberar_bloqueo_b2()


def kill_switch(activar: bool) -> None:
    """Si activar=True, enciende el kill switch (enabled=false, 0 sobrecarga, sin fallas)."""
    cfg = cargar_config()
    cfg["enabled"] = not activar  # enabled=false apaga todo
    for fcfg in cfg.get("fallas", []):
        if activar:
            fcfg["enabled"] = False
    guardar_config(cfg)

    # Revertir toda infraestructura alterada
    ejecutar_cmd(["docker", "start", "pg-portal-b2b"])
    ejecutar_cmd(["docker", "start", "portal-app2"])
    ejecutar_cmd(["docker", "update", "--cpus", "0", "portal-app1"])
    ejecutar_cmd(["docker", "unpause", "portal-consumidor-eventos"])
    liberar_bloqueo_b2()

    if activar:
        print("[KILL SWITCH ACTIVADO] Fallas deshabilitadas globalmente (enabled=false). Infraestructura restaurada.")
    else:
        print("[KILL SWITCH DESACTIVADO] Inyección de fallas permitida (enabled=true).")


def main():
    parser = argparse.ArgumentParser(description="Controlador de Fallas y Resiliencia")
    sub = parser.add_subparsers(dest="comando")

    sub.add_parser("estado", help="Ver estado de fallas y kill switch")

    p_act = sub.add_parser("activar", help="Activar una falla por ID")
    p_act.add_argument("falla", type=str, help="ID de la falla (A1..D2)")

    p_des = sub.add_parser("desactivar", help="Desactivar una falla por ID")
    p_des.add_argument("falla", type=str, help="ID de la falla (A1..D2)")

    p_ks = sub.add_parser("kill-switch", help="Controlar el Kill Switch Global")
    p_ks.add_argument("accion", choices=["on", "off"], help="'on' para apagar fallas, 'off' para permitirlas")

    sub.add_parser("reset", help="Resetear todo a línea base (apaga todas las fallas)")

    args = parser.parse_args()
    if args.comando == "estado" or not args.comando:
        estado_plataforma()
    elif args.comando == "activar":
        activar_falla(args.falla)
    elif args.comando == "desactivar":
        desactivar_falla(args.falla)
    elif args.comando == "kill-switch":
        kill_switch(args.accion == "on")
    elif args.comando == "reset":
        kill_switch(activar=True)


if __name__ == "__main__":
    main()

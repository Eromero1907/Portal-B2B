import psycopg
from pathlib import Path

CONN_INFO = {
    "host": "localhost",
    "port": 5433,
    "dbname": "portal_b2b",
    "user": "postgres",
    "password": "portal",
}

RAIZ = Path(__file__).resolve().parent.parent  # carpeta Portal-B2B


def conectar():
    conn = psycopg.connect(**CONN_INFO)
    return conn


def preparar_sesion(conn):
    """Carga los PREPARE de consultas.sql y fuerza plan_cache_mode=force_custom_plan."""
    sql_texto = (RAIZ / "datos" / "consultas.sql").read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql_texto)
    conn.commit()


def cargar_pools(conn):
    """Corre los 9 SELECT de parametros.sql y devuelve un dict {P1: [...], P2: [...], ...}."""
    texto = (RAIZ / "datos" / "parametros.sql").read_text(encoding="utf-8")
    bloques = {}
    for parte in texto.split("-- P")[1:]:
        num = parte.split(" ", 1)[0].strip("·").strip()
        select_sql = parte.split("SELECT", 1)[1]
        select_sql = "SELECT" + select_sql.split(";")[0] + ";"
        with conn.cursor() as cur:
            cur.execute(select_sql)
            filas = cur.fetchall()
        bloques[f"P{num}"] = filas
    return bloques
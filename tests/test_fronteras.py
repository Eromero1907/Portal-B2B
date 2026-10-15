"""Fronteras de datos: cada módulo solo escribe SQL contra SU esquema (Entrega 1: un esquema por módulo, sin JOIN
entre esquemas). Complementa a import-linter, que verifica las fronteras de código.

Busca referencias `esquema.tabla` en las cadenas de texto (el SQL) de cada módulo.
"""
import ast
import re
from pathlib import Path

PORTAL = Path(__file__).resolve().parent.parent / "app" / "portal"
ESQUEMAS = {"proveedores", "catalogo", "logistica", "ordenes", "auditoria"}
REFERENCIA = re.compile(r"\b(proveedores|catalogo|logistica|ordenes|auditoria)\.([a-z_][a-z0-9_]*)\b")


def _cadenas(archivo: Path):
    for nodo in ast.walk(ast.parse(archivo.read_text(encoding="utf-8"))):
        if isinstance(nodo, ast.Constant) and isinstance(nodo.value, str):
            yield nodo.value


def _referencias_sql(modulo: str) -> set[str]:
    refs = set()
    for archivo in (PORTAL / "modulos" / modulo).rglob("*.py"):
        for texto in _cadenas(archivo):
            if any(p in texto.upper() for p in ("SELECT", "INSERT", "UPDATE", "DELETE")):
                refs |= {m.group(1) for m in REFERENCIA.finditer(texto)}
    return refs


def test_cada_modulo_solo_toca_su_esquema():
    for modulo in ("proveedores", "catalogo", "logistica", "ordenes"):
        ajenos = _referencias_sql(modulo) - {modulo}
        assert not ajenos, f"el módulo {modulo} escribe SQL contra otros esquemas: {sorted(ajenos)}"


def test_los_modulos_tienen_sql():
    # salvaguarda: si la expresión regular dejara de encontrar SQL, la prueba anterior pasaría en vacío
    for modulo in ("proveedores", "catalogo", "logistica", "ordenes"):
        assert modulo in _referencias_sql(modulo)


def test_fuera_de_los_modulos_no_hay_sql_de_negocio():
    for archivo in PORTAL.rglob("*.py"):
        if "modulos" in archivo.parts:
            continue
        for texto in _cadenas(archivo):
            if any(p in texto.upper() for p in ("SELECT ", "INSERT ", "UPDATE ", "DELETE ")):
                assert not REFERENCIA.search(texto), f"{archivo.name} contiene SQL de negocio: {texto[:80]!r}"

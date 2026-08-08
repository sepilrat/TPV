"""
repositorio_auditoria.py — Acceso a datos de Auditoria de precios.

Se mantiene aparte de repositorio.py para no engordar un archivo de 60 KB,
pero sigue la misma regla: NINGUNA query vive en la UI. Si preferis, el
contenido de este archivo se puede pegar tal cual al final de repositorio.py
y cambiar los imports en auditoria_ui.py.
"""

from db import get_connection
from repositorio import get_productos, get_categorias


DDL_DESCARTES = """
CREATE TABLE IF NOT EXISTS auditoria_descartes (
    clave   TEXT PRIMARY KEY,
    motivo  TEXT,
    fecha   TEXT NOT NULL DEFAULT (datetime('now','localtime'))
)"""


def _asegurar_tablas():
    with get_connection() as conn:
        conn.execute(DDL_DESCARTES)


def get_productos_auditoria() -> list:
    """Productos en el formato que espera auditoria.auditar().

    Traduce los nombres del schema del TPV a los que usa el motor de reglas:
        precio_base   -> precio_venta
        costo_ultimo  -> ultimo_costo
    y agrega el margen heredado de la categoria, que get_productos() no trae.
    """
    margen_por_cat = {}
    id_por_cat = {}
    for c in get_categorias():
        margen_por_cat[c["nombre"]] = c.get("margen_pct")
        id_por_cat[c["nombre"]] = c["id"]

    salida = []
    for p in get_productos():
        cat = p.get("categoria")
        salida.append({
            "id":                   p["id"],
            "codigo":               p.get("codigo"),
            "descripcion":          p.get("descripcion") or "",
            "marca":                p.get("marca") or "",
            "categoria_id":         id_por_cat.get(cat),
            "categoria_nombre":     cat or "",
            "precio_venta":         p.get("precio_base") or 0.0,
            "ultimo_costo":         p.get("costo_ultimo") or None,
            "margen_pct":           p.get("margen_pct"),
            "margen_categoria_pct": margen_por_cat.get(cat),
            "stock":                p.get("stock") or 0.0,
        })
    return salida


def get_descartes() -> list:
    _asegurar_tablas()
    with get_connection() as conn:
        return [r[0] for r in conn.execute("SELECT clave FROM auditoria_descartes")]


def guardar_descarte(clave: str, motivo: str = ""):
    _asegurar_tablas()
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO auditoria_descartes(clave, motivo) VALUES (?, ?)",
            (clave, motivo))


def limpiar_descartes():
    _asegurar_tablas()
    with get_connection() as conn:
        conn.execute("DELETE FROM auditoria_descartes")


def actualizar_precio_base(producto_id: int, precio: float):
    """Solo toca precio_base. No mueve costo ni margen."""
    with get_connection() as conn:
        conn.execute("UPDATE productos SET precio_base = ? WHERE id = ?",
                     (float(precio), int(producto_id)))

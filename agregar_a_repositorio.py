# Agregar esta función a repositorio.py, cerca de buscar_producto_id
# (línea ~315 en la versión pública del repo). No reemplaza a
# buscar_producto_id: esa devuelve UN solo match (para el flujo de
# escanear/escribir código exacto); esta devuelve una LISTA, pensada
# para el dropdown de sugerencias al escribir un nombre parcial.

def buscar_productos_texto(texto: str, limite: int = 8) -> list[dict]:
    """Busca productos activos por nombre parcial o código parcial,
    para autocompletar en un buscador. Prioriza los que EMPIEZAN con
    el texto sobre los que solo lo contienen en el medio."""
    texto = (texto or "").strip()
    if not texto:
        return []
    with get_connection() as conn:
        filas = conn.execute("""
            SELECT id, codigo, descripcion, precio_base, vendido_por_peso
            FROM productos
            WHERE activo = 1
              AND (descripcion LIKE ? OR codigo LIKE ?)
            ORDER BY
              CASE WHEN descripcion LIKE ? THEN 0 ELSE 1 END,
              descripcion
            LIMIT ?
        """, (f"%{texto}%", f"%{texto}%", f"{texto}%", limite)).fetchall()
        return [dict(f) for f in filas]

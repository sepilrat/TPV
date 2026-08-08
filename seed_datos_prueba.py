"""
seed_datos_prueba.py — Carga productos de prueba con códigos de barra
reales de Argentina TPV v2.0

Los códigos de barras de esta lista son REALES y están verificados
en Open Food Facts (world.openfoodfacts.org) — sirven para probar
en serio la búsqueda automática de fotos, las promociones, y la
lista de precios en PDF, ya que van a traer su foto real.

Es IDEMPOTENTE: si corrés el script de nuevo, no duplica productos
que ya existan (los detecta por código de barras y los salta).

Uso:
  .venv\\Scripts\\python.exe seed_datos_prueba.py            → carga los datos
  .venv\\Scripts\\python.exe seed_datos_prueba.py --eliminar → borra SOLO estos productos de prueba
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import inicializar_db, get_connection
import repositorio as r

# ─────────────────────────────────────────────────────────────────────────────
# Productos con código de barras REAL argentino (verificado en Open Food
# Facts) — se pueden vender por unidad y tienen foto real disponible.
# (categoria, descripcion, codigo, precio_venta, costo, stock_inicial)
# ─────────────────────────────────────────────────────────────────────────────
PRODUCTOS_CON_CODIGO = [
    ("Bebidas",  "Coca Cola 1.5L",                       "7790895000430", 1900.00, 1150.00, 24),
    ("Bebidas",  "Coca Cola Zero 1.5L",                  "7790895067556", 1900.00, 1150.00, 18),
    ("Bebidas",  "Cerveza Quilmes 340ml",                "7792798007547",  900.00,  520.00, 48),
    ("Almacen",  "Yerba Mate Taragui 500g",              "7790387110234", 2600.00, 1700.00, 20),
    ("Almacen",  "Aceite Cocinero Girasol 900ml",        "7790070012050", 2100.00, 1350.00, 15),
    ("Lacteos",  "Leche La Serenisima Larga Vida 1L",    "7790742335500", 1350.00,  850.00, 30),
    ("Almacen",  "Fideos Matarazzo 500g",                "7790070336651", 1100.00,  680.00, 25),
]

# Productos vendidos por peso (fiambrería/verdulería) — normalmente NO
# tienen código de barras de fábrica (se pesan en el mostrador), así
# que no van a traer foto automática de Open Food Facts; sirven para
# probar el flujo manual de carga de foto y la cantidad con decimales.
PRODUCTOS_POR_PESO = [
    ("Fiambreria", "Jamon Cocido x kg",     "PESO-JAMON",   6500.00, 4200.00, 5.0),
    ("Verduleria", "Mandioca pelada x kg",  "PESO-MANDIOCA", 1200.00,  600.00, 8.0),
    ("Fiambreria", "Queso Cremoso x kg",    "PESO-QUESO",   8200.00, 5500.00, 3.5),
]

# Promoción de ejemplo (para probar precios/lista de precios con
# escalas): Coca Cola 1.5L con descuento por cantidad.
PROMOS_EJEMPLO = [
    # codigo, cantidad_minima, precio_unitario, descripcion
    ("7790895000430", 6,  1750.00, "Por pack de 6"),
    ("7790895000430", 12, 1650.00, "Mayorista"),
]


MARGENES_CATEGORIA = {
    "Bebidas":     35.0,
    "Almacen":     30.0,
    "Lacteos":     25.0,
    "Fiambreria":  40.0,
    "Verduleria":  45.0,
}


def _obtener_o_crear_categoria(nombre: str) -> int:
    existentes = {c["nombre"]: c["id"] for c in r.get_categorias()}
    if nombre in existentes:
        return existentes[nombre]
    r.guardar_categoria(None, nombre, MARGENES_CATEGORIA.get(nombre, 30.0))
    existentes = {c["nombre"]: c["id"] for c in r.get_categorias()}
    return existentes[nombre]


def cargar():
    inicializar_db()
    creados, saltados = 0, 0

    for cat_nombre, desc, codigo, precio, costo, stock in PRODUCTOS_CON_CODIGO:
        if r.get_producto_por_codigo(codigo):
            print(f"  = Ya existe, salteado: {desc} ({codigo})")
            saltados += 1
            continue
        cat_id = _obtener_o_crear_categoria(cat_nombre)
        pid = r.crear_producto(codigo, desc, cat_id, precio, costo,
                               vendido_por_peso=0)
        r.registrar_lote(pid, None, stock, costo, None,
                         "Carga inicial de datos de prueba")
        print(f"  + Creado: {desc} ({codigo}) — stock {stock}")
        creados += 1

    for cat_nombre, desc, codigo, precio, costo, stock in PRODUCTOS_POR_PESO:
        if r.get_producto_por_codigo(codigo):
            print(f"  = Ya existe, salteado: {desc} ({codigo})")
            saltados += 1
            continue
        cat_id = _obtener_o_crear_categoria(cat_nombre)
        pid = r.crear_producto(codigo, desc, cat_id, precio, costo,
                               vendido_por_peso=1)
        r.registrar_lote(pid, None, stock, costo, None,
                         "Carga inicial de datos de prueba")
        print(f"  + Creado (por peso): {desc} ({codigo}) — stock {stock} kg")
        creados += 1

    for codigo, cant_min, precio_u, desc_promo in PROMOS_EJEMPLO:
        prod = r.get_producto_por_codigo(codigo)
        if not prod:
            continue
        with get_connection() as conn:
            ya_existe = conn.execute(
                "SELECT 1 FROM promociones WHERE producto_id=? AND cantidad_minima=?",
                (prod["id"], cant_min)).fetchone()
        if ya_existe:
            print(f"  = Promo ya existe, salteada: {prod['descripcion']} "
                 f"llevando {cant_min}")
            continue
        r.guardar_promocion(None, prod["id"], cant_min, precio_u,
                           desc_promo, None, None)
        print(f"  + Promo agregada: {prod['descripcion']} — "
             f"llevando {cant_min}: $ {precio_u}")

    print(f"\nListo — {creados} productos nuevos, {saltados} ya existian.")
    print("Los productos con codigo real van a traer su foto sola la\n"
         "primera vez que los abras en Productos > Editar (busca en\n"
         "Open Food Facts en segundo plano).")


def eliminar():
    """Borra SOLO los productos de prueba de esta lista (por su código
    de barras), para poder limpiar después de probar."""
    codigos = ([p[2] for p in PRODUCTOS_CON_CODIGO] +
              [p[2] for p in PRODUCTOS_POR_PESO])
    borrados = 0
    with get_connection() as conn:
        for codigo in codigos:
            prod = conn.execute(
                "SELECT id, descripcion FROM productos WHERE codigo=?",
                (codigo,)).fetchone()
            if not prod:
                continue
            conn.execute("DELETE FROM detalle_ventas_lotes WHERE lote_id IN "
                        "(SELECT id FROM lotes WHERE producto_id=?)", (prod["id"],))
            conn.execute("DELETE FROM ajustes_stock WHERE producto_id=?", (prod["id"],))
            conn.execute("DELETE FROM lotes WHERE producto_id=?", (prod["id"],))
            conn.execute("DELETE FROM promociones WHERE producto_id=?", (prod["id"],))
            conn.execute("DELETE FROM productos WHERE id=?", (prod["id"],))
            print(f"  - Eliminado: {prod['descripcion']}")
            borrados += 1
        conn.commit()
    print(f"\nListo — {borrados} productos de prueba eliminados.")


if __name__ == "__main__":
    if "--eliminar" in sys.argv:
        eliminar()
    else:
        cargar()

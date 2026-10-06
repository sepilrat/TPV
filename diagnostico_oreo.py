"""diagnostico_oreo.py — SOLO LECTURA. No modifica la base.

Uso (desde la carpeta del TPV):
    .venv\\Scripts\\python.exe diagnostico_oreo.py
    .venv\\Scripts\\python.exe diagnostico_oreo.py "mandioca"   (otro producto)
"""
import sqlite3
import sys

busqueda = sys.argv[1] if len(sys.argv) > 1 else "Oreo"

# Abre en modo solo lectura: imposible tocar datos por error.
con = sqlite3.connect("file:tpv2.db?mode=ro", uri=True)
con.row_factory = sqlite3.Row

prods = con.execute(
    "SELECT id, descripcion, precio_base, costo_ultimo, modificado_en "
    "FROM productos WHERE descripcion LIKE ?", (f"%{busqueda}%",)).fetchall()

for p in prods:
    print("=" * 78)
    print(f"#{p['id']}  {p['descripcion']}")
    print(f"  precio_base ahora: {p['precio_base']}   costo_ultimo: "
          f"{p['costo_ultimo']}   modificado_en: {p['modificado_en']}")

    print("\n  LOTES (los 6 mas recientes):")
    for l in con.execute("""
        SELECT l.id, l.fecha_ingreso, l.tipo, l.cantidad, l.cantidad_restante,
               l.costo_unitario, l.notas, pv.nombre AS prov
        FROM lotes l LEFT JOIN proveedores pv ON pv.id = l.proveedor_id
        WHERE l.producto_id = ? ORDER BY l.id DESC LIMIT 6""", (p["id"],)):
        print(f"   lote {l['id']} | {l['fecha_ingreso']} | {l['tipo']} | "
              f"cant {l['cantidad']} | resta {l['cantidad_restante']} | "
              f"costo {l['costo_unitario']} | prov {l['prov']} | "
              f"notas: {l['notas']}")

    print("\n  HISTORIAL DE PRECIOS (ultimos 8):")
    filas = con.execute("""
        SELECT fecha, precio_viejo, precio_nuevo, motivo
        FROM historial_precios WHERE producto_id = ?
        ORDER BY id DESC LIMIT 8""", (p["id"],)).fetchall()
    if not filas:
        print("   (sin registros)")
    for h in filas:
        print(f"   {h['fecha']} | {h['precio_viejo']} -> {h['precio_nuevo']} "
              f"| {h['motivo']}")

con.close()

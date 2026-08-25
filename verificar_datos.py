"""
verificar_datos.py — Busca inconsistencias antes de que se noten vendiendo.

Los problemas que fuimos encontrando de a uno tienen algo en común: el
mismo dato guardado en dos lugares que dejan de coincidir. Esto los busca
todos juntos, para no descubrirlos cuando el margen no cierra.

USO
---
    .venv\\Scripts\\python.exe verificar_datos.py
"""

from db import get_connection


PROBLEMAS = []


def _t(n, titulo):
    print("\n" + "─" * 72)
    print(f"{n}. {titulo}")
    print("─" * 72)


def _ok(txt):
    print(f"   [OK]  {txt}")


def _mal(txt, detalle=None):
    print(f"   [!!]  {txt}")
    PROBLEMAS.append(txt)
    for d in (detalle or [])[:8]:
        print(f"         {d}")
    if detalle and len(detalle) > 8:
        print(f"         ...y {len(detalle) - 8} más")


def main():
    print("=" * 72)
    print("VERIFICACIÓN DE DATOS")
    print("=" * 72)

    with get_connection() as c:

        # ── 0 ────────────────────────────────────────────────────────
        _t(0, "Productos en $ 0 (se regalan al escanearlos)")
        filas = c.execute("""
            SELECT descripcion, codigo, costo_ultimo
            FROM productos
            WHERE COALESCE(activo,1)=1 AND COALESCE(precio_base,0) <= 0
            ORDER BY descripcion
        """).fetchall()
        if filas:
            _mal(f"{len(filas)} producto(s) sin precio: si alguien los "
                 f"escanea, salen gratis",
                 [f"{f[0][:34]:<34} código {f[1] or '—'}"
                  f"   costo {f[2] or 0:,.0f}" for f in filas])
            print("\n         Se corrigen desde el Catálogo, o al escanearlos")
            print("         en la caja: ahora el cartel deja cargar el precio")
            print("         en el momento.")
        else:
            _ok("Ningún producto activo está en $ 0")

        # ── 1 ────────────────────────────────────────────────────────
        _t(1, "Precio por debajo del costo")
        filas = c.execute("""
            SELECT descripcion, precio_base, costo_ultimo
            FROM productos
            WHERE COALESCE(activo,1)=1 AND COALESCE(costo_ultimo,0) > 0
              AND precio_base < costo_ultimo
            ORDER BY (costo_ultimo - precio_base) DESC
        """).fetchall()
        if filas:
            _mal(f"{len(filas)} producto(s) se venden a pérdida",
                 [f"{f[0][:34]:<34} precio {f[1]:>9,.0f}  costo {f[2]:>9,.0f}"
                  for f in filas])
        else:
            _ok("Ningún producto se vende por debajo del costo")

        # ── 2 ────────────────────────────────────────────────────────
        # Que distintos lotes tengan distinto costo es NORMAL: se compró
        # a distinto precio en distintos momentos, y el FIFO existe para
        # eso. Lo sospechoso es el ÚLTIMO lote ingresado con un costo muy
        # distinto al del producto: ahí sí quedó algo mal cargado.
        _t(2, "Último lote con un costo muy distinto al del producto")
        filas = c.execute("""
            SELECT p.descripcion, p.costo_ultimo, l.costo_unitario, l.id,
                   date(l.fecha_ingreso) as ing
            FROM productos p
            JOIN lotes l ON l.id = (
                SELECT id FROM lotes
                WHERE producto_id = p.id AND COALESCE(tipo,'ingreso')='ingreso'
                ORDER BY fecha_ingreso DESC, id DESC LIMIT 1)
            WHERE COALESCE(p.activo,1)=1
              AND COALESCE(p.costo_ultimo,0) > 0
              AND COALESCE(l.costo_unitario,0) > 0
              AND ABS(l.costo_unitario - p.costo_ultimo)
                  / p.costo_ultimo > 0.30
            ORDER BY ABS(l.costo_unitario - p.costo_ultimo) DESC
        """).fetchall()
        if filas:
            _mal(f"{len(filas)} producto(s) donde el último ingreso difiere "
                 f"más de 30% del costo guardado",
                 [f"{f[0][:28]:<28} producto {f[1]:>9,.0f}  "
                  f"último lote ({f[4]}) {f[2]:>9,.0f}" for f in filas])
            print("\n         Uno de los dos está mal. Si el correcto es el")
            print("         del lote: Stock → Ver historial completo →")
            print("         «Editar lote». Si es el del producto, corregilo")
            print("         desde el Catálogo.")
        else:
            _ok("El último ingreso de cada producto coincide con su costo")

        # ── 2b ───────────────────────────────────────────────────────
        _t("2b", "Lotes con stock a costo cero")
        filas = c.execute("""
            SELECT p.descripcion, l.id, l.cantidad_restante
            FROM lotes l JOIN productos p ON p.id = l.producto_id
            WHERE COALESCE(p.activo,1)=1 AND l.cantidad_restante > 0
              AND COALESCE(l.costo_unitario,0) <= 0
        """).fetchall()
        if filas:
            _mal(f"{len(filas)} lote(s) con stock y costo en cero: lo que se "
                 f"venda de ahí figura con 100% de ganancia",
                 [f"{f[0][:34]:<34} lote #{f[1]}  quedan {f[2]:g}"
                  for f in filas])
        else:
            _ok("Todos los lotes con stock tienen su costo cargado")

        # ── 3 ────────────────────────────────────────────────────────
        _t(3, "Costo igual al precio de venta")
        filas = c.execute("""
            SELECT descripcion, precio_base FROM productos
            WHERE COALESCE(activo,1)=1 AND COALESCE(costo_ultimo,0) > 0
              AND ABS(precio_base - costo_ultimo) < 0.01
        """).fetchall()
        if filas:
            _mal(f"{len(filas)} producto(s) con costo = precio: casi seguro "
                 f"se cargó el precio en el campo del costo",
                 [f"{f[0][:34]:<34} ambos en {f[1]:,.0f}" for f in filas])
        else:
            _ok("Ningún producto tiene el costo igual al precio")

        # ── 4 ────────────────────────────────────────────────────────
        # Un 300% es normal en bazar o electronica chica; el problema es
        # el margen NEGATIVO o cercano a cero.
        _t(4, "Márgenes sospechosos")
        filas = c.execute("""
            SELECT descripcion, precio_base, costo_ultimo,
                   (precio_base - costo_ultimo) / costo_ultimo * 100 as m
            FROM productos
            WHERE COALESCE(activo,1)=1 AND COALESCE(costo_ultimo,0) > 0
              AND ((precio_base - costo_ultimo) / costo_ultimo * 100 > 900
                   OR (precio_base - costo_ultimo) / costo_ultimo * 100 < 5)
            ORDER BY m DESC
        """).fetchall()
        if filas:
            _mal(f"{len(filas)} producto(s) con margen menor a 5% o mayor "
                 f"a 900%: revisá el costo",
                 [f"{f[0][:30]:<30} precio {f[1]:>8,.0f}  costo {f[2]:>8,.0f}"
                  f"  margen {f[3]:>7.0f}%" for f in filas])
        else:
            _ok("Todos los márgenes están en un rango razonable")

        # ── 5 ────────────────────────────────────────────────────────
        _t(5, "Stock negativo")
        filas = c.execute("""
            SELECT p.descripcion, SUM(l.cantidad_restante) as st
            FROM productos p JOIN lotes l ON l.producto_id = p.id
            WHERE COALESCE(p.activo,1)=1
            GROUP BY p.id HAVING st < 0
            ORDER BY st
        """).fetchall()
        if filas:
            _mal(f"{len(filas)} producto(s) con stock negativo: se vendió "
                 f"más de lo que había cargado",
                 [f"{f[0][:34]:<34} {f[1]:>8,.1f}" for f in filas])
        else:
            _ok("Ningún stock en negativo")

        # ── 6 ────────────────────────────────────────────────────────
        _t(6, "Promos duplicadas para la misma cantidad")
        filas = c.execute("""
            SELECT p.descripcion, pr.cantidad_minima, COUNT(*) as n
            FROM promociones pr JOIN productos p ON p.id = pr.producto_id
            WHERE pr.activa = 1
            GROUP BY pr.producto_id, pr.cantidad_minima
            HAVING n > 1
        """).fetchall()
        if filas:
            _mal(f"{len(filas)} caso(s) de promos repetidas: la etiqueta "
                 f"muestra precios que se contradicen",
                 [f"{f[0][:34]:<34} llevando {f[1]}: {f[2]} promos"
                  for f in filas])
        else:
            _ok("Sin promos duplicadas")

        # ── 7 ────────────────────────────────────────────────────────
        _t(7, "Promos que no convienen")
        filas = c.execute("""
            SELECT p.descripcion, pr.cantidad_minima, pr.precio_unitario,
                   p.precio_base
            FROM promociones pr JOIN productos p ON p.id = pr.producto_id
            WHERE pr.activa = 1 AND pr.precio_unitario >= p.precio_base
        """).fetchall()
        if filas:
            _mal(f"{len(filas)} promo(s) con precio igual o mayor al normal",
                 [f"{f[0][:30]:<30} x{f[1]} a {f[2]:,.0f} "
                  f"(normal {f[3]:,.0f})" for f in filas])
        else:
            _ok("Todas las promos mejoran el precio")

        # ── 8 ────────────────────────────────────────────────────────
        _t(8, "Códigos de barras repetidos")
        filas = c.execute("""
            SELECT codigo, COUNT(*) as n,
                   GROUP_CONCAT(descripcion, ' | ') as cuales
            FROM productos
            WHERE COALESCE(activo,1)=1 AND codigo IS NOT NULL AND codigo <> ''
            GROUP BY codigo HAVING n > 1
        """).fetchall()
        if filas:
            _mal(f"{len(filas)} código(s) en más de un producto: al escanear "
                 f"puede cobrarse el equivocado",
                 [f"{f[0]:<16} → {str(f[2])[:44]}" for f in filas])
        else:
            _ok("Sin códigos repetidos")

        # ── 9 ────────────────────────────────────────────────────────
        _t(9, "Productos que parecen repetidos")
        filas = c.execute("""
            SELECT LOWER(REPLACE(REPLACE(descripcion,' ',''),'.','')) as clave,
                   COUNT(*) as n, GROUP_CONCAT(descripcion, ' | ') as cuales
            FROM productos WHERE COALESCE(activo,1)=1
            GROUP BY clave HAVING n > 1
        """).fetchall()
        if filas:
            _mal(f"{len(filas)} nombre(s) cargados más de una vez",
                 [str(f[2])[:60] for f in filas])
            print("\n         Se unen con: Catálogo → «🔗 Unificar»")
        else:
            _ok("Sin productos con el mismo nombre")

        # ── 10 ───────────────────────────────────────────────────────
        _t(10, "Recargos por horario en negativo")
        try:
            filas = c.execute("""
                SELECT nombre, porcentaje FROM recargos_horario
                WHERE activo = 1 AND porcentaje < 0
            """).fetchall()
            if filas:
                _mal(f"{len(filas)} recargo(s) activos BAJAN el precio",
                     [f"{f[0][:34]:<34} {f[1]:+.0f}%" for f in filas])
            else:
                _ok("Ningún recargo baja precios")
        except Exception:
            _ok("Sin recargos configurados")

    print("\n" + "=" * 72)
    if PROBLEMAS:
        print(f"{len(PROBLEMAS)} punto(s) para revisar:")
        for p in PROBLEMAS:
            print(f"   · {p}")
    else:
        print("Sin inconsistencias. Los datos están sanos.")
    print("=" * 72)


if __name__ == "__main__":
    main()

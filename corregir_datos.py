"""
corregir_datos.py — Arregla lo que encuentra verificar_datos.py.

El verificador dice QUÉ está mal; este script lo corrige. Va de a un
problema por vez, mostrando el dato y proponiendo un arreglo: nada se
toca sin que lo confirmes.

USO
---
    .venv\\Scripts\\python.exe corregir_datos.py

Antes de empezar hace una copia de la base. Si algo sale mal, se vuelve
con restaurar_backup.py.
"""

import sys

from db import get_connection


def _preguntar(texto, opciones=("s", "n")):
    """Pregunta hasta que la respuesta sea válida."""
    ops = "/".join(opciones)
    while True:
        r = input(f"   {texto} [{ops}]: ").strip().lower()
        if r in opciones:
            return r
        if not r and opciones:
            return opciones[0]


def _titulo(n, txt):
    print()
    print("─" * 70)
    print(f"{n}. {txt}")
    print("─" * 70)


# ─────────────────────────────────────────────────────────────────────
# 1. Lotes con stock y costo en cero
# ─────────────────────────────────────────────────────────────────────
def lotes_costo_cero():
    _titulo(1, "Lotes con stock y costo en cero")
    with get_connection() as conn:
        filas = conn.execute("""
            SELECT l.id, l.producto_id, l.cantidad_restante,
                   p.descripcion, p.costo_ultimo,
                   (SELECT AVG(l2.costo_unitario) FROM lotes l2
                     WHERE l2.producto_id = l.producto_id
                       AND COALESCE(l2.costo_unitario, 0) > 0) as costo_otros
            FROM lotes l JOIN productos p ON p.id = l.producto_id
            WHERE l.cantidad_restante > 0
              AND COALESCE(l.costo_unitario, 0) <= 0
            ORDER BY p.descripcion
        """).fetchall()

    if not filas:
        print("   [OK]  No hay lotes con ese problema.")
        return 0

    print(f"   {len(filas)} lote(s). Lo que se venda de ahí figura con")
    print("   100% de ganancia y ensucia todos los informes.\n")

    arreglados = 0
    for f in filas:
        print(f"   · {f['descripcion'][:44]}")
        print(f"     lote #{f['id']}  ·  quedan {f['cantidad_restante']:g}")

        # Se propone el costo de otros lotes del mismo producto; si no
        # hay, el costo guardado en el producto.
        sugerido = f["costo_otros"] or f["costo_ultimo"] or 0
        if sugerido > 0:
            origen = ("promedio de otros lotes" if f["costo_otros"]
                      else "costo del producto")
            print(f"     Sugerido: $ {sugerido:,.2f}  ({origen})")
            r = _preguntar("¿Uso ese costo? (s = sí, n = escribo otro, "
                           "x = dejar así)", ("s", "n", "x"))
        else:
            print("     No hay con qué calcularlo: hay que escribirlo.")
            r = _preguntar("¿Cargar el costo? (n = sí, x = dejar así)",
                           ("n", "x"))

        if r == "x":
            continue
        if r == "n":
            try:
                sugerido = float(input("     Costo unitario: $ ")
                                 .strip().replace(",", "."))
            except ValueError:
                print("     Valor inválido, se deja como está.")
                continue
        if sugerido <= 0:
            print("     El costo tiene que ser mayor a 0.")
            continue

        with get_connection() as conn:
            conn.execute("UPDATE lotes SET costo_unitario = ? WHERE id = ?",
                         (sugerido, f["id"]))
            conn.commit()
        print(f"     [OK] Lote #{f['id']} a $ {sugerido:,.2f}")
        arreglados += 1
    return arreglados


# ─────────────────────────────────────────────────────────────────────
# 2. Costo del producto desactualizado
# ─────────────────────────────────────────────────────────────────────
def costo_desactualizado():
    _titulo(2, "Costo del producto muy distinto al del último lote")
    with get_connection() as conn:
        filas = conn.execute("""
            SELECT p.id, p.descripcion, p.costo_ultimo, p.precio_base,
                   l.costo_unitario as costo_lote, l.id as lote_id,
                   date(l.fecha_ingreso) as cuando
            FROM productos p
            JOIN lotes l ON l.id = (
                SELECT l2.id FROM lotes l2
                 WHERE l2.producto_id = p.id
                   AND COALESCE(l2.costo_unitario, 0) > 0
                 ORDER BY l2.fecha_ingreso DESC, l2.id DESC LIMIT 1)
            WHERE COALESCE(p.activo, 1) = 1
              AND COALESCE(p.costo_ultimo, 0) > 0
              AND ABS(l.costo_unitario - p.costo_ultimo)
                  > p.costo_ultimo * 0.30
            ORDER BY p.descripcion
        """).fetchall()

    if not filas:
        print("   [OK]  Todos los costos coinciden con su último lote.")
        return 0

    print(f"   {len(filas)} producto(s). Uno de los dos números está mal.\n")
    arreglados = 0
    for f in filas:
        m_viejo = ((f["precio_base"] - f["costo_ultimo"])
                   / f["costo_ultimo"] * 100) if f["costo_ultimo"] else 0
        m_nuevo = ((f["precio_base"] - f["costo_lote"])
                   / f["costo_lote"] * 100) if f["costo_lote"] else 0
        print(f"   · {f['descripcion'][:44]}")
        print(f"     Costo guardado:  $ {f['costo_ultimo']:>12,.2f}   "
              f"→ margen {m_viejo:.0f}%")
        print(f"     Último lote:     $ {f['costo_lote']:>12,.2f}   "
              f"→ margen {m_nuevo:.0f}%   ({f['cuando']})")

        r = _preguntar("¿Uso el del último lote? (s = sí, x = dejar así)",
                       ("s", "x"))
        if r != "s":
            continue
        with get_connection() as conn:
            conn.execute("""UPDATE productos SET costo_ultimo = ?,
                                   modificado_en = datetime('now','localtime')
                             WHERE id = ?""", (f["costo_lote"], f["id"]))
            conn.commit()
        print(f"     [OK] Costo actualizado a $ {f['costo_lote']:,.2f}")
        arreglados += 1
    return arreglados


# ─────────────────────────────────────────────────────────────────────
# 3. Márgenes imposibles
# ─────────────────────────────────────────────────────────────────────
def margenes_raros():
    _titulo(3, "Márgenes imposibles (menos de 5% o más de 900%)")
    with get_connection() as conn:
        filas = conn.execute("""
            SELECT p.id, p.descripcion, p.precio_base, p.costo_ultimo,
                   c.nombre as categoria, c.margen_pct as margen_rubro
            FROM productos p
            LEFT JOIN categorias c ON c.id = p.categoria_id
            WHERE COALESCE(p.activo, 1) = 1
              AND COALESCE(p.costo_ultimo, 0) > 0
              AND p.precio_base > 0
              AND ((p.precio_base - p.costo_ultimo) / p.costo_ultimo * 100
                   < 5
                OR (p.precio_base - p.costo_ultimo) / p.costo_ultimo * 100
                   > 900)
            ORDER BY p.descripcion
        """).fetchall()

    if not filas:
        print("   [OK]  Todos los márgenes son razonables.")
        return 0

    print(f"   {len(filas)} producto(s). Puede ser un costo mal cargado,")
    print("   o puede ser real: hay cosas que se venden con mucho margen.\n")
    arreglados = 0
    for f in filas:
        margen = (f["precio_base"] - f["costo_ultimo"]) / f["costo_ultimo"] * 100
        print(f"   · {f['descripcion'][:44]}")
        print(f"     Precio $ {f['precio_base']:,.2f}   ·   "
              f"Costo $ {f['costo_ultimo']:,.2f}   ·   margen {margen:.0f}%")
        if f["margen_rubro"]:
            costo_seria = f["precio_base"] / (1 + f["margen_rubro"] / 100)
            print(f"     Con el margen de «{f['categoria']}» "
                  f"({f['margen_rubro']:.0f}%), el costo sería "
                  f"$ {costo_seria:,.2f}")

        print("     s = corregir el COSTO      p = corregir el PRECIO")
        print("     x = está bien, dejarlo así")
        r = _preguntar("¿Qué hago?", ("s", "p", "x"))
        if r == "x":
            continue
        campo = "costo_ultimo" if r == "s" else "precio_base"
        etq = "Costo" if r == "s" else "Precio de venta"
        try:
            nuevo = float(input(f"     {etq}: $ ").strip().replace(",", "."))
        except ValueError:
            print("     Valor inválido, se deja como está.")
            continue
        if nuevo <= 0:
            print("     Tiene que ser mayor a 0.")
            continue
        with get_connection() as conn:
            conn.execute(f"""UPDATE productos SET {campo} = ?,
                                    modificado_en = datetime('now','localtime')
                              WHERE id = ?""", (nuevo, f["id"]))
            conn.commit()
        print(f"     [OK] {etq} = $ {nuevo:,.2f}")
        arreglados += 1
    return arreglados


def main():
    print("=" * 70)
    print("CORREGIR LOS DATOS QUE MARCA EL VERIFICADOR")
    print("=" * 70)
    print("\nNada se modifica sin que lo confirmes.")

    # Copia antes de tocar nada: son cambios sobre datos reales.
    try:
        from logger import hacer_backup
        ruta = hacer_backup("antes_de_corregir")
        if ruta:
            import os
            print(f"Copia de seguridad: {os.path.basename(ruta)}")
    except Exception as exc:
        print(f"[!] No se pudo hacer la copia: {exc}")
        if _preguntar("¿Seguir igual?", ("n", "s")) != "s":
            return

    total = 0
    for fn in (lotes_costo_cero, costo_desactualizado, margenes_raros):
        try:
            total += fn()
        except (KeyboardInterrupt, EOFError):
            print("\n\nCancelado. Lo corregido hasta acá ya está guardado.")
            return
        except Exception as exc:
            print(f"   [FALLA] {type(exc).__name__}: {exc}")

    print()
    print("=" * 70)
    print(f"{total} corrección(es) aplicada(s).")
    if total:
        print("\nVolvé a correr verificar_datos.py para ver cómo quedó.")
    print("=" * 70)


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print("\nCancelado.")
        sys.exit(0)

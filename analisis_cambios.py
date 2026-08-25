"""
analisis_cambios.py — Qué operación produjo esos cambios de precio.

Cuando aparecen muchos cambios juntos con motivo vacío, el patrón dice
de dónde vienen: si los precios nuevos son múltiplos redondos fue el
redondeo; si guardan una proporción fija fue un recálculo por margen; y
si no hay patrón, fueron cargados de a uno.

USO
---
    .venv\\Scripts\\python.exe analisis_cambios.py 2026-08-22
"""

import sys
from collections import Counter

from db import get_connection


def main():
    if len(sys.argv) < 2:
        print("Uso: analisis_cambios.py AAAA-MM-DD")
        return
    dia = sys.argv[1]

    with get_connection() as c:
        filas = [dict(r) for r in c.execute("""
            SELECT h.fecha, h.precio_viejo as viejo, h.precio_nuevo as nuevo,
                   p.descripcion, p.costo_ultimo, p.margen_pct,
                   c.nombre as categoria, c.margen_pct as margen_cat
            FROM historial_precios h
            JOIN productos p ON p.id = h.producto_id
            LEFT JOIN categorias c ON c.id = p.categoria_id
            WHERE date(h.fecha) = date(?)
            ORDER BY h.fecha
        """, (dia,)).fetchall()]

    if not filas:
        print(f"Sin cambios el {dia}.")
        return

    print("=" * 70)
    print(f"ANÁLISIS DE LOS {len(filas)} CAMBIOS DEL {dia}")
    print("=" * 70)

    print("\n1. ¿CUÁNDO EXACTAMENTE?")
    minutos = Counter(str(f["fecha"])[11:16] for f in filas)
    seguidos = sorted(minutos.items())
    print(f"   Del {seguidos[0][0]} al {seguidos[-1][0]}")
    picos = [m for m, n in minutos.items() if n >= 3]
    if picos:
        print(f"   Minutos con 3 o más cambios: {len(picos)}")
        print("   Muchos cambios en el mismo minuto = fue una operación")
        print("   masiva, no alguien tecleando de a uno.")
    else:
        print("   Repartidos, ninguno junto. Parece carga de a uno.")

    print("\n2. ¿LOS PRECIOS NUEVOS SON REDONDOS?")
    redondos = {50: 0, 100: 0, 10: 0}
    for f in filas:
        for paso in (100, 50, 10):
            if f["nuevo"] and f["nuevo"] % paso == 0:
                redondos[paso] += 1
                break
    for paso in (100, 50, 10):
        pct = redondos[paso] / len(filas) * 100
        print(f"   múltiplos de {paso:>4}: {redondos[paso]:>4}  ({pct:.0f}%)")
    if sum(redondos.values()) / len(filas) > 0.9:
        print("\n   >90% redondos: casi seguro fue el REDONDEO de precios")
        print("   (Productos → A revisar → «Redondear seleccionados»)")

    print("\n3. ¿HAY UNA PROPORCIÓN FIJA? (recálculo por margen)")
    props = Counter()
    for f in filas:
        if f["viejo"]:
            props[round(f["nuevo"] / f["viejo"], 2)] += 1
    comunes = props.most_common(5)
    for prop, n in comunes:
        print(f"   x{prop:<6} en {n:>3} producto(s)"
              f"   ({(prop - 1) * 100:+.0f}%)")
    if comunes and comunes[0][1] > len(filas) * 0.5:
        print("\n   Más de la mitad con la misma proporción: fue un")
        print("   AUMENTO/DESCUENTO MASIVO por porcentaje.")

    print("\n4. ¿EL PRECIO NUEVO SALE DEL COSTO × MARGEN?")
    coincide = 0
    ejemplos = []
    for f in filas:
        costo = f["costo_ultimo"] or 0
        margen = f["margen_pct"] or f["margen_cat"] or 0
        if costo and margen:
            esperado = costo * (1 + margen / 100)
            if abs(esperado - f["nuevo"]) < max(1.0, f["nuevo"] * 0.02):
                coincide += 1
                if len(ejemplos) < 5:
                    ejemplos.append(
                        f"      {f['descripcion'][:28]:<28} costo "
                        f"{costo:,.0f} × {margen:.0f}% = {esperado:,.0f}"
                        f"  (quedó {f['nuevo']:,.0f})")
    pct = coincide / len(filas) * 100
    print(f"   {coincide} de {len(filas)} ({pct:.0f}%) dan exactamente")
    print("   costo × margen")
    for e in ejemplos:
        print(e)
    if pct > 60:
        print("\n   >60%: fue un RECÁLCULO POR MARGEN.")
        print("   Los que bajaron son productos cuyo COSTO está cargado")
        print("   más bajo de lo real: el recálculo los llevó a ese costo.")

    print("\n5. LOS QUE MÁS BAJARON, CON SU COSTO")
    bajas = sorted((f for f in filas if f["nuevo"] < f["viejo"]),
                   key=lambda f: f["nuevo"] / f["viejo"])[:10]
    print(f"   {'PRODUCTO':<30}{'ANTES':>9}{'AHORA':>9}{'COSTO':>10}"
          f"{'MARGEN QUEDÓ':>14}")
    for f in bajas:
        costo = f["costo_ultimo"] or 0
        m = ((f["nuevo"] - costo) / costo * 100) if costo else 0
        print(f"   {f['descripcion'][:30]:<30}{f['viejo']:>9,.0f}"
              f"{f['nuevo']:>9,.0f}{costo:>10,.0f}{m:>13.0f}%")
    print("\n   Si el margen que quedó es parecido en todos, el precio")
    print("   se recalculó desde el costo. Si algún costo está mal")
    print("   cargado, ese precio quedó mal.")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()

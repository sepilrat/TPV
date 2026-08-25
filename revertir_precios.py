"""
revertir_precios.py — Vuelve atrás los precios de una fecha.

El historial guarda el precio anterior de cada cambio, así que se puede
deshacer. Muestra qué va a hacer ANTES de tocar nada.

USO
---
    .venv\\Scripts\\python.exe revertir_precios.py 2026-08-22
        muestra la lista, no cambia nada

    .venv\\Scripts\\python.exe revertir_precios.py 2026-08-22 --aplicar
        revierte de verdad

    .venv\\Scripts\\python.exe revertir_precios.py 2026-08-22 --aplicar --solo-bajas
        revierte solo los que bajaron (deja las subas)
"""

import sys

from db import get_connection


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    dia = sys.argv[1]
    aplicar = "--aplicar" in sys.argv
    solo_bajas = "--solo-bajas" in sys.argv

    cond = "AND h.precio_nuevo < h.precio_viejo" if solo_bajas else ""

    with get_connection() as c:
        # El primer cambio del día de cada producto tiene el precio que
        # había ANTES de tocarlo. Los cambios intermedios no importan.
        filas = [dict(r) for r in c.execute(f"""
            SELECT h.producto_id, p.descripcion,
                   h.precio_viejo as volver_a,
                   p.precio_base as ahora,
                   MIN(h.fecha) as primera
            FROM historial_precios h
            JOIN productos p ON p.id = h.producto_id
            WHERE date(h.fecha) = date(?) {cond}
            GROUP BY h.producto_id
            ORDER BY p.descripcion
        """, (dia,)).fetchall()]

    if not filas:
        print(f"Sin cambios para revertir el {dia}.")
        return

    # Los que ya están en el precio viejo no hace falta tocarlos
    filas = [f for f in filas
             if abs((f["ahora"] or 0) - (f["volver_a"] or 0)) > 0.01]

    print("=" * 72)
    print(f"REVERTIR PRECIOS DEL {dia}"
          + ("  (solo los que bajaron)" if solo_bajas else ""))
    print("=" * 72)
    print(f"\n{len(filas)} producto(s) volverían a su precio anterior:\n")
    print(f"   {'PRODUCTO':<34}{'AHORA':>11}{'VUELVE A':>12}")
    for f in filas:
        print(f"   {f['descripcion'][:34]:<34}{f['ahora'] or 0:>11,.0f}"
              f"{f['volver_a'] or 0:>12,.0f}")

    if not aplicar:
        print("\n" + "-" * 72)
        print("Esto es solo la vista previa. NO se cambió nada.")
        print("Para aplicarlo de verdad:")
        print(f"    .venv\\Scripts\\python.exe revertir_precios.py {dia} "
              f"--aplicar")
        if not solo_bajas:
            print("\nSolo los que bajaron:")
            print(f"    .venv\\Scripts\\python.exe revertir_precios.py {dia} "
                  f"--aplicar --solo-bajas")
        return

    print("\n¿Seguro? Escribí SI en mayúsculas para confirmar: ", end="")
    if input().strip() != "SI":
        print("Cancelado. No se tocó nada.")
        return

    from repositorio import set_precio_base
    hechos = 0
    for f in filas:
        try:
            set_precio_base(f["producto_id"], f["volver_a"])
            hechos += 1
        except Exception as exc:
            print(f"   [falla] {f['descripcion'][:30]}: {exc}")

    print(f"\n[OK] {hechos} precio(s) restaurados.")
    print("     Quedan registrados en el historial, así que esto también")
    print("     se puede deshacer si hiciera falta.")
    print("\n     Revisá las etiquetas de góndola de esos productos:")
    print("     Productos → Imprimir → Etiquetas pendientes.")


if __name__ == "__main__":
    main()

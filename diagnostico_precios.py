"""
diagnostico_precios.py — Quién está bajando los precios.

Cada cambio de precio queda registrado con su motivo. Esto los lista para
ver el patrón: si es una operación masiva, el redondeo, un recargo, o
alguien editando a mano.

USO
---
    .venv\\Scripts\\python.exe diagnostico_precios.py
    .venv\\Scripts\\python.exe diagnostico_precios.py 30    (últimos 30 días)
"""

import sys
from collections import Counter
from datetime import date, timedelta

from db import get_connection


def _t(txt):
    print("\n" + "─" * 70)
    print(txt)
    print("─" * 70)


def main():
    dias = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    desde = (date.today() - timedelta(days=dias)).isoformat()

    print("=" * 70)
    print(f"CAMBIOS DE PRECIO — últimos {dias} días")
    print("=" * 70)

    with get_connection() as c:
        try:
            total = c.execute(
                "SELECT COUNT(*) FROM historial_precios "
                "WHERE date(fecha) >= date(?)", (desde,)).fetchone()[0]
        except Exception:
            print("\nNo existe la tabla de historial todavía.")
            print("Se crea al abrir el TPV con la versión nueva, y desde ahí")
            print("empieza a registrar. Los cambios anteriores no están.")
            return

        print(f"\nCambios registrados: {total}")
        if not total:
            print("\nNingún cambio en el período. Si igual ves precios")
            print("distintos, el cambio puede venir de:")
            print("   · un RECARGO POR HORARIO activo (Productos → Recargos)")
            print("   · una PROMO que aplica por cantidad")
            print("   · el catálogo web mostrando datos viejos")
            _mostrar_recargos()
            return

        _t("1. ¿Subieron o bajaron?")
        bajas = c.execute("""
            SELECT COUNT(*) FROM historial_precios
            WHERE date(fecha) >= date(?) AND precio_nuevo < precio_viejo
        """, (desde,)).fetchone()[0]
        subas = total - bajas
        print(f"   Bajaron: {bajas}")
        print(f"   Subieron: {subas}")

        _t("2. ¿Por qué motivo?")
        motivos = c.execute("""
            SELECT COALESCE(motivo, '(edición a mano)') as m,
                   COUNT(*) as n,
                   SUM(CASE WHEN precio_nuevo < precio_viejo THEN 1 ELSE 0 END) as bajas
            FROM historial_precios
            WHERE date(fecha) >= date(?)
            GROUP BY m ORDER BY n DESC
        """, (desde,)).fetchall()
        print(f"   {'MOTIVO':<34}{'CAMBIOS':>9}{'DE ESOS, BAJAS':>17}")
        for m in motivos:
            print(f"   {str(m[0])[:34]:<34}{m[1]:>9}{m[2]:>17}")

        _t("3. Las 15 bajas más grandes")
        filas = c.execute("""
            SELECT h.fecha, p.descripcion, h.precio_viejo, h.precio_nuevo,
                   COALESCE(h.motivo, '(a mano)') as motivo
            FROM historial_precios h
            JOIN productos p ON p.id = h.producto_id
            WHERE date(h.fecha) >= date(?) AND h.precio_nuevo < h.precio_viejo
            ORDER BY (h.precio_viejo - h.precio_nuevo) DESC
            LIMIT 15
        """, (desde,)).fetchall()
        if not filas:
            print("   Ninguna baja en el período.")
        else:
            print(f"   {'CUÁNDO':<17}{'PRODUCTO':<26}{'ANTES':>11}"
                  f"{'AHORA':>11}  MOTIVO")
            for f in filas:
                caida = (f[2] - f[3]) / f[2] * 100 if f[2] else 0
                print(f"   {str(f[0])[:16]:<17}{str(f[1])[:26]:<26}"
                      f"{f[2]:>11,.0f}{f[3]:>11,.0f}"
                      f"  {str(f[4])[:22]} ({caida:.0f}%)")

        _t("4. ¿Se repite a la misma hora?")
        horas = Counter()
        for f in c.execute("""
            SELECT fecha FROM historial_precios
            WHERE date(fecha) >= date(?) AND precio_nuevo < precio_viejo
        """, (desde,)):
            try:
                horas[str(f[0])[11:13]] += 1
            except Exception:
                pass
        if horas:
            for h, n in sorted(horas.items()):
                print(f"   {h}:00   {'█' * min(n, 40)} {n}")
            print("\n   Si se concentran en una hora, suele ser algo")
            print("   automático: revisá los recargos por horario.")

    _mostrar_recargos()


def _mostrar_recargos():
    """Con su propia conexión: el bloque de arriba ya la cerró."""
    _t("5. Recargos por horario configurados")
    try:
        with get_connection() as c:
            filas = c.execute("""
                SELECT nombre, porcentaje, dias, hora_desde, hora_hasta, activo
                FROM recargos_horario ORDER BY activo DESC, nombre
            """).fetchall()
    except Exception as exc:
        print(f"   (no se pudo leer: {exc})")
        return
    if not filas:
        print("   Ninguno. No es esto.")
        return
    for f in filas:
        estado = "ACTIVO" if f[5] else "pausado"
        print(f"   [{estado:<7}] {f[0][:28]:<28} {f[1]:+.0f}%  "
              f"días {f[2]}  de {f[3]:02d}:00 a {f[4]:02d}:00")
    print("\n   Un recargo NEGATIVO baja el precio mientras rige.")
    print("   Los precios de lista no se tocan: se calcula al vender.")


if __name__ == "__main__":
    main()

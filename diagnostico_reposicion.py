"""
diagnostico_reposicion.py — Por qué "Venta/día" da cero.

La velocidad de venta sale de cruzar los productos con lo vendido en los
últimos 30 días. Si da cero para todo, el problema está en los datos, no
en el cálculo — y este script dice exactamente dónde.

USO
---
    .venv\\Scripts\\python.exe diagnostico_reposicion.py
"""

from datetime import datetime, timedelta

from db import get_connection


def _titulo(t):
    print("\n" + "─" * 66)
    print(t)
    print("─" * 66)


def main():
    hoy = datetime.now()
    desde = (hoy - timedelta(days=30)).strftime("%Y-%m-%d")

    print("=" * 66)
    print("DIAGNOSTICO — velocidad de venta")
    print("=" * 66)

    with get_connection() as c:
        _titulo("1. ¿Hay ventas registradas?")
        total = c.execute("SELECT COUNT(*) FROM ventas").fetchone()[0]
        print(f"   Ventas en la base: {total}")
        if not total:
            print("   [FALLA] No hay NINGUNA venta registrada.")
            print("           Sin ventas no hay velocidad que medir: el "
                  "informe va a usar el umbral fijo de Config.")
            return

        ult = c.execute(
            "SELECT MAX(fecha) FROM ventas WHERE anulada = 0").fetchone()[0]
        print(f"   Última venta: {ult}")

        recientes = c.execute("""
            SELECT COUNT(*) FROM ventas
            WHERE anulada = 0 AND date(fecha) >= date(?)
        """, (desde,)).fetchone()[0]
        print(f"   Ventas en los últimos 30 días: {recientes}")
        if not recientes:
            print("   [FALLA] Hay ventas, pero NINGUNA en los últimos 30 "
                  "días.")
            print("           El cálculo mira esa ventana. Si el sistema se "
                  "usó y después se dejó de usar, todo da cero.")

        _titulo("2. ¿Las fechas están en un formato que SQLite entiende?")
        malas = c.execute("""
            SELECT COUNT(*) FROM ventas WHERE date(fecha) IS NULL
        """).fetchone()[0]
        muestra = c.execute(
            "SELECT fecha FROM ventas ORDER BY id DESC LIMIT 3").fetchall()
        for m in muestra:
            print(f"   ejemplo: {m[0]!r}")
        if malas:
            print(f"   [FALLA] {malas} venta(s) con fecha ilegible. Esas no "
                  f"se cuentan nunca.")
        else:
            print("   [OK]    Todas las fechas se leen bien.")

        _titulo("3. ¿Las ventas tienen el detalle de productos?")
        det = c.execute("SELECT COUNT(*) FROM detalle_ventas").fetchone()[0]
        sin_det = c.execute("""
            SELECT COUNT(*) FROM ventas v
            WHERE NOT EXISTS (SELECT 1 FROM detalle_ventas dv
                               WHERE dv.venta_id = v.id)
        """).fetchone()[0]
        print(f"   Líneas de detalle: {det}")
        if sin_det:
            print(f"   [FALLA] {sin_det} venta(s) sin ningún producto "
                  f"asociado.")
            print("           El total figura, pero no se sabe QUÉ se "
                  "vendió: esas ventas no aportan a la velocidad.")
        else:
            print("   [OK]    Todas las ventas tienen su detalle.")

        _titulo("4. ¿El detalle apunta a productos que existen?")
        huerfanos = c.execute("""
            SELECT COUNT(*) FROM detalle_ventas dv
            WHERE NOT EXISTS (SELECT 1 FROM productos p WHERE p.id = dv.producto_id)
        """).fetchone()[0]
        if huerfanos:
            print(f"   [FALLA] {huerfanos} línea(s) apuntan a productos que "
                  f"ya no existen.")
        else:
            print("   [OK]    Todo el detalle apunta a productos válidos.")

        _titulo("5. ¿Cuánto se vendió de cada producto? (top 10)")
        filas = c.execute("""
            SELECT p.descripcion,
                   COALESCE(SUM(dv.cantidad), 0) as vendido,
                   COALESCE((SELECT SUM(l.cantidad_restante) FROM lotes l
                              WHERE l.producto_id = p.id), 0) as stock
            FROM productos p
            LEFT JOIN detalle_ventas dv ON dv.producto_id = p.id
            LEFT JOIN ventas v ON v.id = dv.venta_id
                              AND v.anulada = 0
                              AND date(v.fecha) >= date(?)
            WHERE COALESCE(p.activo, 1) = 1
            GROUP BY p.id
            HAVING vendido > 0
            ORDER BY vendido DESC LIMIT 10
        """, (desde,)).fetchall()
        if not filas:
            print("   [FALLA] Ningún producto registra ventas en los últimos "
                  "30 días.")
            print("           Por eso Venta/día y Comprar dan cero para todo.")
        else:
            print(f"   {'PRODUCTO':<34}{'VENDIDO':>10}{'x DIA':>9}{'STOCK':>9}")
            for f in filas:
                print(f"   {f[0][:34]:<34}{f[1]:>10.0f}"
                      f"{f[1]/30:>9.2f}{f[2]:>9.0f}")

        _titulo("6. Productos activos sin ninguna venta en 30 días")
        n = c.execute("""
            SELECT COUNT(*) FROM productos p
            WHERE COALESCE(p.activo, 1) = 1
              AND NOT EXISTS (
                    SELECT 1 FROM detalle_ventas dv
                    JOIN ventas v ON v.id = dv.venta_id
                    WHERE dv.producto_id = p.id AND v.anulada = 0
                      AND date(v.fecha) >= date(?))
        """, (desde,)).fetchone()[0]
        activos = c.execute(
            "SELECT COUNT(*) FROM productos WHERE COALESCE(activo,1)=1"
        ).fetchone()[0]
        print(f"   {n} de {activos} productos activos no se vendieron.")
        if activos and n == activos:
            print("   [FALLA] NINGUN producto se vendió en el período.")
        elif n > activos * 0.8:
            print("   Es normal si el catálogo es grande y variado: la "
                  "mayoría rota poco.")

    print("\n" + "=" * 66)
    print("Si el punto 1 o el 5 fallan, el informe no tiene con qué "
          "calcular\ny cae al umbral fijo de Config. No es un error del "
          "cálculo.")
    print("=" * 66)


if __name__ == "__main__":
    main()

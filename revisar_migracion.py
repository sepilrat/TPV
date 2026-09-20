import sqlite3

for archivo in [
    "tpv2.db",
    "backups/tpv2_2026-09-19_16-42_inicio.db",
    "backups/tpv2_2026-09-19_11-45_inicio.db"
]:
    print("\n" + "="*70)
    print(archivo)
    print("="*70)

    con = sqlite3.connect(archivo)

    tablas = [
        r[0] for r in con.execute("""
            SELECT name
            FROM sqlite_master
            WHERE type='table'
              AND name LIKE '%cliente%'
            ORDER BY name
        """)
    ]

    for tabla in tablas:
        cantidad = con.execute(
            f'SELECT COUNT(*) FROM "{tabla}"'
        ).fetchone()[0]

        print(f"\n{tabla}: {cantidad} registros")

        if cantidad:
            for r in con.execute(f'SELECT * FROM "{tabla}"'):
                print(r)

    con.close()

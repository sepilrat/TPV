import sqlite3

archivos = [
    "tpv2.db",
    "backups/tpv2_2026-09-19_11-45_inicio.db",
    "backups/tpv2_2026-09-19_16-42_inicio.db"
]

for archivo in archivos:
    print("\n" + "="*70)
    print(archivo)
    print("="*70)

    con = sqlite3.connect(archivo)

    print("\nCLIENTES:")
    try:
        for r in con.execute("SELECT * FROM clientes"):
            print(r)
    except Exception as e:
        print("ERROR:", e)

    print("\nCUENTAS CORRIENTES:")
    try:
        for r in con.execute("SELECT * FROM cuentas_corrientes"):
            print(r)
    except Exception as e:
        print("ERROR:", e)

    print("\nULTIMOS MOVIMIENTOS:")
    try:
        for r in con.execute("""
            SELECT *
            FROM movimientos_cuenta
            ORDER BY rowid DESC
            LIMIT 10
        """):
            print(r)
    except Exception as e:
        print("ERROR:", e)

    con.close()

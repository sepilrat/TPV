import sqlite3

for archivo in [
    "tpv2.db",
    "backups/tpv2_2026-09-19_11-45_inicio.db"
]:
    print("\n==============================")
    print(archivo)
    print("==============================")

    con = sqlite3.connect(archivo)

    for r in con.execute("PRAGMA table_info(clientes)"):
        print(r)

    con.close()

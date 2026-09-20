import sqlite3
db="backups/tpv2_2026-09-19_16-42_inicio.db"
con=sqlite3.connect(db)
for t in ["ventas","cuentas_corrientes","movimientos_cuenta"]:
    print("\n"+t)
    for r in con.execute(f"PRAGMA foreign_key_list({t})"):
        print(r)
con.close()

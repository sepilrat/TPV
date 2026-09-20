import sqlite3
import glob

files = (
    glob.glob("*.db")
    + glob.glob("backups/*.db")
    + glob.glob("backups/diarios/*.db")
)

for f in files:
    try:
        con = sqlite3.connect(f)

        cc = con.execute("SELECT COUNT(*) FROM cuentas_corrientes").fetchone()[0]
        mc = con.execute("SELECT COUNT(*) FROM movimientos_cuenta").fetchone()[0]
        cli = con.execute("SELECT COUNT(*) FROM clientes").fetchone()[0]

        con.close()

        print(f"{f} -> clientes: {cli} | cuentas_corrientes: {cc} | movimientos_cuenta: {mc}")

    except Exception as e:
        print(f"{f} -> ERROR: {e}")

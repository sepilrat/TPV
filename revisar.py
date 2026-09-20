import sqlite3
import glob

files = glob.glob("*.db") + glob.glob("backups/*.db") + glob.glob("backups/diarios/*.db")

for f in files:
    try:
        con = sqlite3.connect(f)
        tablas = [x[0] for x in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()]
        con.close()
        print("\n" + f)
        print("  " + ", ".join(tablas))
    except Exception as e:
        print("\n" + f + " ERROR: " + str(e))

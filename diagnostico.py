import sqlite3

db = sqlite3.connect("tpv2.db")

print("=== TABLAS RELACIONADAS CON CLIENTES ===")
for r in db.execute("""
    SELECT name
    FROM sqlite_master
    WHERE type = 'table'
      AND name LIKE '%cliente%'
"""):
    print(r[0])

print("\n=== REFERENCIAS A clientes_old_notnull ===")
for r in db.execute("""
    SELECT name, sql
    FROM sqlite_master
    WHERE type = 'table'
      AND sql LIKE '%clientes_old_notnull%'
"""):
    print("\nTABLA:", r[0])
    print(r[1])

print("\n=== CONTEO DE REGISTROS ===")
for tabla in ("clientes", "clientes_old_notnull"):
    existe = db.execute("""
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table' AND name = ?
    """, (tabla,)).fetchone()

    if existe:
        cantidad = db.execute(
            f"SELECT COUNT(*) FROM {tabla}"
        ).fetchone()[0]
        print(f"{tabla}: {cantidad}")

print("\n=== FOREIGN KEY CHECK ===")
violaciones = db.execute("PRAGMA foreign_key_check").fetchall()
print("TOTAL:", len(violaciones))

db.close()
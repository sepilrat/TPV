import sqlite3

conn = sqlite3.connect("tpv.db")
cur = conn.cursor()

cur.execute("SELECT COUNT(*) FROM catalogo")
print("Cantidad productos:", cur.fetchone()[0])

cur.execute("SELECT * FROM catalogo LIMIT 5")
for row in cur.fetchall():
    print(row)

conn.close()
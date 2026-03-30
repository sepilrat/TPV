import sqlite3

conn = sqlite3.connect("tpv.db")
cur = conn.cursor()

print("Mini consola SQLite (escribí 'exit' para salir)")

while True:
    q = input("SQL> ")

    if q.lower() in ["exit", "quit"]:
        break

    try:
        cur.execute(q)

        if q.strip().lower().startswith("select"):
            rows = cur.fetchall()
            for r in rows:
                print(r)
            print(f"\n{len(rows)} filas\n")
        else:
            conn.commit()
            print("OK")

    except Exception as e:
        print("ERROR:", e)

conn.close()
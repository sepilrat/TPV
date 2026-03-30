import pandas as pd
from db import init_db, get_conn

URL = "https://docs.google.com/spreadsheets/d/1b5XG33E7mqFNyhTwFYMqa103KK1qnybYuiHAFC5dOcE/export?format=csv&gid=1410047793"


def limpiar_precio(v):
    if pd.isna(v):
        return 0
    v = str(v).replace("$", "").replace(",", "").strip()
    return float(v) if v else 0


def migrar():
    df = pd.read_csv(URL)
    df.columns = df.columns.str.strip()

    conn = get_conn()
    cur = conn.cursor()

    for _, row in df.iterrows():
        cur.execute("""
        INSERT OR REPLACE INTO catalogo VALUES (?,?,?,?,?,?,?,?)
        """, (
            str(row.get("Codigo", "")),
            str(row.get("COD_BARRA", "")),
            str(row.get("DESCRIPCION", "")),
            limpiar_precio(row.get("Precio Unit")),
            limpiar_precio(row.get("Precio 3+")),
            limpiar_precio(row.get("Precio Caja")),
            int(row.get("U/CAJA")) if not pd.isna(row.get("U/CAJA")) else 9999,
            str(row.get("LINK IMAGEN", ""))
        ))

    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    migrar()
    print("Base creada y catálogo cargado")
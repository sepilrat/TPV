import pandas as pd
from db import get_conn

URL = "https://docs.google.com/spreadsheets/d/1b5XG33E7mqFNyhTwFYMqa103KK1qnybYuiHAFC5dOcE/export?format=csv&gid=1410047793"


def limpiar_barra(v):
    if pd.isna(v):
        return ""
    s = str(v).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s


def to_float(v):
    if pd.isna(v):
        return 0
    return float(str(v).replace("$", "").replace(",", "").strip() or 0)


def to_int(v):
    if pd.isna(v):
        return 0
    return int(float(v))


df = pd.read_csv(URL)
df.columns = df.columns.str.strip()

conn = get_conn()
cur = conn.cursor()

cur.execute("DELETE FROM catalogo")

for _, r in df.iterrows():

    cur.execute("""
    INSERT INTO catalogo (
        codigo, descripcion, precio_unit,
        precio_3, precio_caja, u_caja,
        cod_barra, link_imagen
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        str(r.get("Codigo", "")),
        str(r.get("DESCRIPCION", "")),
        to_float(r.get("Precio Unit")),
        to_float(r.get("Precio 3+")),
        to_float(r.get("Precio Caja")),
        to_int(r.get("U/CAJA")),
        limpiar_barra(r.get("COD_BARRA")),
        str(r.get("LINK IMAGEN", ""))
    ))

conn.commit()
conn.close()

print("✔ Catalogo importado correctamente")
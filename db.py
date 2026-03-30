import sqlite3

DB = "tpv.db"

def get_conn():
    return sqlite3.connect(DB)

def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.executescript("""
    CREATE TABLE IF NOT EXISTS catalogo (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        codigo TEXT,
        descripcion TEXT,
        precio_unit REAL,
        precio_3 REAL,
        precio_caja REAL,
        u_caja INTEGER,
        cod_barra TEXT,
        link_imagen TEXT
    );

    CREATE TABLE IF NOT EXISTS ventas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fecha TEXT,
        producto TEXT,
        cantidad INTEGER,
        precio REAL,
        total REAL,
        cod_barra TEXT
    );

    CREATE TABLE IF NOT EXISTS stock (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fecha TEXT,
        cod_barra TEXT,
        producto TEXT,
        cantidad INTEGER,
        tipo TEXT
    );

    CREATE TABLE IF NOT EXISTS productos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL,
        codigo_barra TEXT UNIQUE NOT NULL,
        stock INTEGER DEFAULT 0,
        precio REAL DEFAULT 0,
        url_imagen TEXT
    );

    CREATE TABLE IF NOT EXISTS proveedores (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT UNIQUE NOT NULL
    );

    CREATE TABLE IF NOT EXISTS lotes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        producto_id INTEGER NOT NULL,
        proveedor_id INTEGER,
        fecha TEXT NOT NULL,
        cantidad INTEGER NOT NULL,
        cantidad_actual INTEGER NOT NULL,
        fecha_vencimiento TEXT,
        FOREIGN KEY(producto_id) REFERENCES productos(id),
        FOREIGN KEY(proveedor_id) REFERENCES proveedores(id)
    );
    """)

    conn.commit()
    conn.close()
    print("DB lista")

    
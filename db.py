"""
db.py — Base de datos del sistema TPV
Versión 2.0 — Diseño limpio desde cero
"""

import sqlite3
import os
import sys
from datetime import datetime

# Forzar UTF-8 en consola Windows (evita errores con emojis en prints)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB_PATH = os.path.join(os.path.dirname(__file__), "tpv2.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Permite acceder a columnas por nombre
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")  # Mejor rendimiento
    return conn


def inicializar_db():
    conn = get_connection()
    c = conn.cursor()

    # ─────────────────────────────────────────
    # CATEGORÍAS
    # ─────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS categorias (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre      TEXT NOT NULL UNIQUE,
            margen_pct  REAL DEFAULT 30.0,  -- margen de ganancia por defecto (%)
            creado_en   TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    # ─────────────────────────────────────────
    # PROVEEDORES
    # ─────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS proveedores (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre      TEXT NOT NULL,
            telefono    TEXT,
            email       TEXT,
            notas       TEXT,
            activo      INTEGER DEFAULT 1,
            creado_en   TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    # ─────────────────────────────────────────
    # PRODUCTOS
    # ─────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS productos (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo          TEXT NOT NULL UNIQUE,   -- código de barras
            descripcion     TEXT NOT NULL,
            categoria_id    INTEGER REFERENCES categorias(id) ON DELETE SET NULL,
            precio_base     REAL NOT NULL DEFAULT 0.0,  -- precio de venta unitario
            costo_ultimo    REAL DEFAULT 0.0,           -- último costo de compra
            margen_pct      REAL DEFAULT NULL,          -- NULL = heredar margen de categoría
            ignorar_alerta  INTEGER DEFAULT 0,           -- 1 = no alertar stock bajo
            vendido_por_peso INTEGER DEFAULT 0,          -- 1 = admite cantidad decimal (kg)
            marca           TEXT,                        -- marca/fabricante (para ordenar listas)
            imagen_url      TEXT,
            activo          INTEGER DEFAULT 1,
            creado_en       TEXT DEFAULT (datetime('now','localtime')),
            modificado_en   TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    # ─────────────────────────────────────────
    # PROMOCIONES (precios por cantidad, flexibles)
    # ─────────────────────────────────────────
    # Ejemplo: 3 unidades de producto X → $500 c/u
    c.execute("""
        CREATE TABLE IF NOT EXISTS promociones (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            producto_id     INTEGER NOT NULL REFERENCES productos(id) ON DELETE CASCADE,
            cantidad_minima INTEGER NOT NULL,   -- a partir de qué cantidad aplica
            precio_unitario REAL NOT NULL,      -- precio por unidad con la promo
            fecha_desde     TEXT,               -- NULL = sin límite de inicio
            fecha_hasta     TEXT,               -- NULL = sin vencimiento
            activa          INTEGER DEFAULT 1,
            descripcion     TEXT,               -- ej: "Pack x3", "Oferta semana"
            creado_en       TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    # ─────────────────────────────────────────
    # LOTES DE STOCK (ingreso con FIFO)
    # ─────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS lotes (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            producto_id     INTEGER NOT NULL REFERENCES productos(id) ON DELETE CASCADE,
            proveedor_id    INTEGER REFERENCES proveedores(id) ON DELETE SET NULL,
            cantidad        REAL NOT NULL,
            cantidad_restante REAL NOT NULL,    -- para FIFO
            costo_unitario  REAL DEFAULT 0.0,
            fecha_ingreso   TEXT DEFAULT (datetime('now','localtime')),
            fecha_vencimiento TEXT,             -- NULL = no vence
            notas           TEXT,
            tipo            TEXT DEFAULT 'ingreso',   -- 'ingreso' (compra/carga normal) o 'ajuste'
            motivo_ajuste   TEXT                       -- solo si tipo='ajuste': Merma/Rotura/etc
        )
    """)

    # ─────────────────────────────────────────
    # AJUSTES DE STOCK (correcciones: merma, rotura, conteo, error)
    # ─────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS devoluciones (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            venta_id         INTEGER NOT NULL REFERENCES ventas(id) ON DELETE CASCADE,
            sesion_id        INTEGER REFERENCES sesiones_caja(id) ON DELETE SET NULL,
            total            REAL NOT NULL DEFAULT 0,
            motivo           TEXT,
            metodo_reintegro TEXT NOT NULL DEFAULT 'efectivo',
            autorizado_por   TEXT,
            fecha            TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    # ─────────────────────────────────────────
    # PIEZAS
    # Para mercaderia de peso variable (hormas, piezas de fiambre). Un lote
    # agrupa kilos; una pieza es UNA horma concreta, con su peso y su costo.
    # Hace falta porque dos hormas del mismo ingreso pesan distinto y costaron
    # distinto: si el FIFO descuenta del lote mas viejo mientras el cortador
    # esta usando otra horma, el costo imputado a la venta es el equivocado.
    # ─────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS piezas (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            producto_id   INTEGER NOT NULL REFERENCES productos(id) ON DELETE CASCADE,
            lote_id       INTEGER REFERENCES lotes(id) ON DELETE SET NULL,
            etiqueta      TEXT,
            peso_inicial  REAL NOT NULL,
            peso_restante REAL NOT NULL,
            costo_kg      REAL NOT NULL DEFAULT 0,
            merma_pct     REAL NOT NULL DEFAULT 0,
            estado        TEXT NOT NULL DEFAULT 'cerrada',
            vencimiento   TEXT,
            abierta_en    TEXT,
            cerrada_en    TEXT,
            creado_en     TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    c.execute("""
        CREATE INDEX IF NOT EXISTS ix_piezas_producto
            ON piezas(producto_id, estado)
    """)

    # Que pieza se corto en cada venta. Sin esto no se puede saber el costo
    # real de la venta ni cuanto rindio cada horma.
    c.execute("""
        CREATE TABLE IF NOT EXISTS detalle_ventas_piezas (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            detalle_venta_id INTEGER NOT NULL REFERENCES detalle_ventas(id) ON DELETE CASCADE,
            pieza_id         INTEGER NOT NULL REFERENCES piezas(id) ON DELETE RESTRICT,
            cantidad         REAL NOT NULL,
            costo_kg         REAL NOT NULL
        )
    """)

    # ─────────────────────────────────────────
    # PRESENTACIONES
    # Un mismo producto vendido en dos unidades. Ej: caramelos con stock en
    # gramos, que ademas se venden en bolsa cerrada de 800 g con su propio
    # codigo de barras y su propio precio (normalmente mas barato por gramo).
    # El stock es UNO SOLO: vender una bolsa descuenta 800 del granel.
    # ─────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS presentaciones (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            producto_id  INTEGER NOT NULL REFERENCES productos(id) ON DELETE CASCADE,
            codigo       TEXT NOT NULL UNIQUE,
            descripcion  TEXT NOT NULL,
            factor       REAL NOT NULL,
            precio       REAL NOT NULL DEFAULT 0,
            activo       INTEGER NOT NULL DEFAULT 1,
            creado_en    TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    c.execute("""
        CREATE INDEX IF NOT EXISTS ix_present_producto
            ON presentaciones(producto_id)
    """)

    # ─────────────────────────────────────────
    # DEVOLUCIONES (parciales o totales de una venta)
    # ─────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS devoluciones_detalle (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            devolucion_id    INTEGER NOT NULL REFERENCES devoluciones(id) ON DELETE CASCADE,
            detalle_venta_id INTEGER NOT NULL REFERENCES detalle_ventas(id) ON DELETE CASCADE,
            producto_id      INTEGER NOT NULL REFERENCES productos(id) ON DELETE RESTRICT,
            descripcion      TEXT NOT NULL,
            cantidad         REAL NOT NULL,
            monto            REAL NOT NULL
        )
    """)

    c.execute("""
        CREATE INDEX IF NOT EXISTS ix_dev_det_detalle
            ON devoluciones_detalle(detalle_venta_id)
    """)

    # ─────────────────────────────────────────
    # AJUSTES DE STOCK (correcciones: merma, rotura, conteo, error)
    # ─────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS ajustes_stock (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            producto_id       INTEGER NOT NULL REFERENCES productos(id) ON DELETE CASCADE,
            lote_id           INTEGER REFERENCES lotes(id) ON DELETE SET NULL,
            cantidad_anterior REAL NOT NULL,
            cantidad_nueva    REAL NOT NULL,
            diferencia        REAL NOT NULL,       -- nueva - anterior
            motivo            TEXT NOT NULL,       -- Merma / Rotura / Conteo fisico / Error de carga / Otro
            notas             TEXT,
            autorizado_por    TEXT NOT NULL,
            fecha             TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    # ─────────────────────────────────────────
    # SESIONES DE CAJA
    # ─────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS sesiones_caja (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            fondo_inicial   REAL DEFAULT 0.0,
            apertura_en     TEXT DEFAULT (datetime('now','localtime')),
            cierre_en       TEXT,               -- NULL = sesión abierta
            total_efectivo  REAL DEFAULT 0.0,
            total_tarjeta   REAL DEFAULT 0.0,
            total_qr        REAL DEFAULT 0.0,
            total_cuenta_corriente REAL DEFAULT 0.0,
            notas           TEXT,
            cerrada         INTEGER DEFAULT 0
        )
    """)

    # ─────────────────────────────────────────
    # VENTAS (cabecera)
    # ─────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS ventas (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            sesion_id       INTEGER REFERENCES sesiones_caja(id) ON DELETE SET NULL,
            fecha           TEXT DEFAULT (datetime('now','localtime')),
            total           REAL NOT NULL DEFAULT 0.0,
            metodo_pago     TEXT NOT NULL DEFAULT 'efectivo',
            descuento_pct   REAL DEFAULT 0.0,
            descuento_monto REAL DEFAULT 0.0,
            cliente_id      INTEGER REFERENCES clientes(id) ON DELETE SET NULL,
            anulada         INTEGER DEFAULT 0
        )
    """)

    # ─────────────────────────────────────────
    # DETALLE DE VENTAS (ítems por venta)
    # ─────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS detalle_ventas (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            venta_id        INTEGER NOT NULL REFERENCES ventas(id) ON DELETE CASCADE,
            producto_id     INTEGER NOT NULL REFERENCES productos(id) ON DELETE RESTRICT,
            descripcion     TEXT NOT NULL,      -- snapshot del nombre al momento de venta
            cantidad        REAL NOT NULL,
            precio_unitario REAL NOT NULL,      -- precio real cobrado (puede ser promo)
            subtotal        REAL NOT NULL,
            promo_aplicada  INTEGER DEFAULT 0   -- 1 si se aplicó una promoción
        )
    """)

    # ─────────────────────────────────────────
    # MOVIMIENTOS DE CAJA (ingresos/egresos manuales)
    # ─────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS movimientos_caja (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            sesion_id       INTEGER REFERENCES sesiones_caja(id) ON DELETE SET NULL,
            tipo            TEXT NOT NULL,      -- 'ingreso' | 'egreso'
            monto           REAL NOT NULL,
            concepto        TEXT,
            fecha           TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    # ─────────────────────────────────────────
    # ÍNDICES para performance
    # ─────────────────────────────────────────
    c.execute("CREATE INDEX IF NOT EXISTS idx_productos_codigo ON productos(codigo)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_lotes_producto ON lotes(producto_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_lotes_fifo ON lotes(producto_id, fecha_ingreso)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_ventas_fecha ON ventas(fecha)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_ventas_sesion ON ventas(sesion_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_detalle_venta ON detalle_ventas(venta_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_promociones_producto ON promociones(producto_id)")

    # ─────────────────────────────────────────
    # VENDEDORES (comisiones sobre el catálogo web)
    # ─────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS vendedores (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo          TEXT UNIQUE NOT NULL,   -- va en el link (?v=codigo)
            nombre          TEXT NOT NULL,
            usuario         TEXT UNIQUE NOT NULL,   -- para el login de su panel
            password_hash   TEXT NOT NULL,          -- SHA-256, nunca texto plano
            telefono        TEXT,                   -- solo si modo_cobro = 'vendedor'
            comision_pct    REAL NOT NULL DEFAULT 0, -- % sobre el COSTO del producto
            modo_cobro      TEXT NOT NULL DEFAULT 'negocio', -- 'vendedor' o 'negocio'
            activo          INTEGER DEFAULT 1,
            creado_en       TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_vendedores_codigo ON vendedores(codigo)")

    # Migraciones automáticas para DBs existentes
    migraciones = [
        "ALTER TABLE productos ADD COLUMN margen_pct REAL DEFAULT NULL",
        "ALTER TABLE ventas ADD COLUMN cliente_id INTEGER REFERENCES clientes(id)",
        "ALTER TABLE productos ADD COLUMN ignorar_alerta INTEGER DEFAULT 0",
        "ALTER TABLE productos ADD COLUMN vendido_por_peso INTEGER DEFAULT 0",
        "ALTER TABLE productos ADD COLUMN marca TEXT",
        # Dias de aviso de vencimiento propios del producto. NULL = usar el
        # general de Config. Un yogur no necesita el mismo anticipo que una lata.
        "ALTER TABLE productos ADD COLUMN alerta_dias_vto INTEGER DEFAULT NULL",
        "ALTER TABLE lotes ADD COLUMN tipo TEXT DEFAULT 'ingreso'",
        "ALTER TABLE lotes ADD COLUMN motivo_ajuste TEXT",
        "ALTER TABLE ajustes_stock ADD COLUMN lote_id INTEGER REFERENCES lotes(id)",
        """CREATE TABLE IF NOT EXISTS detalle_ventas_lotes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            detalle_venta_id INTEGER NOT NULL,
            lote_id INTEGER NOT NULL,
            cantidad REAL NOT NULL
        )""",
        "ALTER TABLE promociones ADD COLUMN tipo_descuento TEXT DEFAULT 'precio_fijo'",
        "ALTER TABLE promociones ADD COLUMN porcentaje_descuento REAL",
    ]
    for sql in migraciones:
        try:
            c.execute(sql)
            conn.commit()
        except Exception:
            pass  # Columna ya existe


    # ─────────────────────────────────────────────────────────────────────────
    # TRAZABILIDAD LOTE → VENTA
    # ─────────────────────────────────────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS detalle_ventas_lotes (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            detalle_venta_id    INTEGER NOT NULL REFERENCES detalle_ventas(id) ON DELETE CASCADE,
            lote_id             INTEGER NOT NULL REFERENCES lotes(id) ON DELETE RESTRICT,
            cantidad            REAL NOT NULL
        )
    """)
    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_dvl_detalle
        ON detalle_ventas_lotes(detalle_venta_id)
    """)
    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_dvl_lote
        ON detalle_ventas_lotes(lote_id)
    """)

    # ─────────────────────────────────────────────────────────────────────────
    # CLIENTES Y FIADO
    # ─────────────────────────────────────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS clientes (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            dni             TEXT NOT NULL UNIQUE,
            nombre          TEXT NOT NULL,
            telefono        TEXT,
            tope_credito    REAL DEFAULT 0.0,
            activo          INTEGER DEFAULT 1,
            creado_en       TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS cuentas_corrientes (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id      INTEGER NOT NULL REFERENCES clientes(id),
            saldo_actual    REAL DEFAULT 0.0,
            ultima_actualizacion TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS movimientos_cuenta (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id      INTEGER NOT NULL REFERENCES clientes(id),
            tipo            TEXT NOT NULL,  -- 'fiado' | 'pago'
            monto           REAL NOT NULL,
            venta_id        INTEGER REFERENCES ventas(id),
            concepto        TEXT,
            autorizado_por  TEXT,
            fecha           TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    c.execute("CREATE INDEX IF NOT EXISTS idx_clientes_dni ON clientes(dni)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_movimientos_cliente ON movimientos_cuenta(cliente_id)")

    conn.commit()
    conn.close()
    print(f"[OK] Base de datos inicializada en: {DB_PATH}")


# ─────────────────────────────────────────────────────────────────────────────
# FUNCIONES DE STOCK
# ─────────────────────────────────────────────────────────────────────────────

def get_stock_total(producto_id: int) -> float:
    """Devuelve el stock total disponible de un producto."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(cantidad_restante), 0) FROM lotes WHERE producto_id = ?",
            (producto_id,)
        ).fetchone()
        return row[0]


def descontar_stock_fifo(producto_id: int, cantidad: float,
                         conn=None, detalle_venta_id: int = None) -> bool:
    """
    Descuenta stock usando FIFO (lote más antiguo primero).
    Si se pasa detalle_venta_id, registra la trazabilidad lote→venta.
    Retorna True si había stock suficiente, False si no.
    """
    cerrar = conn is None
    if conn is None:
        conn = get_connection()

    try:
        lotes = conn.execute("""
            SELECT id, cantidad_restante
            FROM lotes
            WHERE producto_id = ? AND cantidad_restante > 0
            ORDER BY fecha_ingreso ASC
        """, (producto_id,)).fetchall()

        total_disponible = sum(l["cantidad_restante"] for l in lotes)
        if total_disponible < cantidad:
            return False

        restante = cantidad
        for lote in lotes:
            if restante <= 0:
                break
            usado = min(lote["cantidad_restante"], restante)
            conn.execute(
                "UPDATE lotes SET cantidad_restante = cantidad_restante - ? WHERE id = ?",
                (usado, lote["id"])
            )
            # Registrar trazabilidad si viene de una venta
            if detalle_venta_id:
                conn.execute("""
                    INSERT INTO detalle_ventas_lotes
                        (detalle_venta_id, lote_id, cantidad)
                    VALUES (?,?,?)
                """, (detalle_venta_id, lote["id"], usado))
            restante -= usado

        if cerrar:
            conn.commit()
        return True

    except Exception as e:
        if cerrar:
            conn.rollback()
        raise e
    finally:
        if cerrar:
            conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# FUNCIONES DE PRODUCTOS
# ─────────────────────────────────────────────────────────────────────────────

def buscar_producto_por_codigo(codigo: str) -> dict | None:
    """Busca un producto por código de barras. Retorna dict o None."""
    with get_connection() as conn:
        row = conn.execute("""
            SELECT p.*, c.nombre as categoria_nombre, c.margen_pct
            FROM productos p
            LEFT JOIN categorias c ON p.categoria_id = c.id
            WHERE p.codigo = ? AND p.activo = 1
        """, (codigo,)).fetchone()
        return dict(row) if row else None


def get_precio_con_promo(producto_id: int, cantidad: float) -> tuple[float, bool]:
    """
    Retorna (precio_unitario, promo_aplicada).
    Busca la mejor promoción vigente para la cantidad dada.
    """
    hoy = datetime.now().strftime("%Y-%m-%d")
    with get_connection() as conn:
        # Busca la promo activa más conveniente (mayor descuento) para esa cantidad
        promo = conn.execute("""
            SELECT precio_unitario
            FROM promociones
            WHERE producto_id = ?
              AND cantidad_minima <= ?
              AND activa = 1
              AND (fecha_desde IS NULL OR fecha_desde <= ?)
              AND (fecha_hasta IS NULL OR fecha_hasta >= ?)
            ORDER BY precio_unitario ASC
            LIMIT 1
        """, (producto_id, cantidad, hoy, hoy)).fetchone()

        if promo:
            return promo["precio_unitario"], True

        # Sin promo: precio base
        producto = conn.execute(
            "SELECT precio_base FROM productos WHERE id = ?", (producto_id,)
        ).fetchone()
        return (producto["precio_base"] if producto else 0.0), False


# ─────────────────────────────────────────────────────────────────────────────
# FUNCIONES DE VENTA
# ─────────────────────────────────────────────────────────────────────────────

def registrar_venta(sesion_id: int, items: list[dict], metodo_pago: str,
                    descuento_pct: float = 0.0) -> int | None:
    """
    Registra una venta completa con sus ítems.
    items: lista de dicts con keys: producto_id, descripcion, cantidad, precio_unitario, promo_aplicada
    Retorna el id de la venta creada, o None si falla.
    """
    conn = get_connection()
    try:
        subtotales = [i["cantidad"] * i["precio_unitario"] for i in items]
        total_bruto = sum(subtotales)
        descuento_monto = total_bruto * (descuento_pct / 100)
        total = total_bruto - descuento_monto

        cur = conn.execute("""
            INSERT INTO ventas (sesion_id, total, metodo_pago, descuento_pct, descuento_monto)
            VALUES (?, ?, ?, ?, ?)
        """, (sesion_id, total, metodo_pago, descuento_pct, descuento_monto))
        venta_id = cur.lastrowid

        for item, subtotal in zip(items, subtotales):
            conn.execute("""
                INSERT INTO detalle_ventas
                    (venta_id, producto_id, descripcion, cantidad, precio_unitario, subtotal, promo_aplicada)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                venta_id,
                item["producto_id"],
                item["descripcion"],
                item["cantidad"],
                item["precio_unitario"],
                subtotal,
                item.get("promo_aplicada", 0)
            ))

            # Descontar stock FIFO
            ok = descontar_stock_fifo(item["producto_id"], item["cantidad"], conn=conn)
            if not ok:
                raise ValueError(f"Stock insuficiente para: {item['descripcion']}")

        # Actualizar totales en sesión de caja
        col_metodo = {
            "efectivo": "total_efectivo",
            "tarjeta": "total_tarjeta",
            "qr": "total_qr",
            "cuenta_corriente": "total_cuenta_corriente"
        }.get(metodo_pago, "total_efectivo")

        conn.execute(f"""
            UPDATE sesiones_caja SET {col_metodo} = {col_metodo} + ? WHERE id = ?
        """, (total, sesion_id))

        conn.commit()
        return venta_id

    except Exception as e:
        conn.rollback()
        print(f"❌ Error registrando venta: {e}")
        return None
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# FUNCIONES DE CAJA
# ─────────────────────────────────────────────────────────────────────────────

def abrir_sesion_caja(fondo_inicial: float = 0.0) -> int:
    """Abre una nueva sesión de caja. Retorna el id."""
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO sesiones_caja (fondo_inicial) VALUES (?)", (fondo_inicial,)
        )
        conn.commit()
        return cur.lastrowid


def get_sesion_abierta() -> dict | None:
    """Retorna la sesión de caja abierta actualmente, o None."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM sesiones_caja WHERE cerrada = 0 ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


def cerrar_sesion_caja(sesion_id: int, notas: str = "") -> dict:
    """Cierra la sesión de caja y retorna el resumen."""
    with get_connection() as conn:
        conn.execute("""
            UPDATE sesiones_caja
            SET cerrada = 1,
                cierre_en = datetime('now','localtime'),
                notas = ?
            WHERE id = ?
        """, (notas, sesion_id))
        conn.commit()

        sesion = conn.execute(
            "SELECT * FROM sesiones_caja WHERE id = ?", (sesion_id,)
        ).fetchone()
        return dict(sesion)


if __name__ == "__main__":
    inicializar_db()

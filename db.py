"""
db.py — Base de datos del sistema TPV
Versión 2.0 — Diseño limpio desde cero
"""

import logging
import sqlite3
import os
import sys
from datetime import datetime

# Forzar UTF-8 en consola Windows (evita errores con emojis en prints)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Base de datos. Se puede apuntar a otra con la variable de entorno
# TPV_DB, para probar sin tocar la base real:
#     set TPV_DB=tpv2_prueba.db  &&  python main.py
# El modo prueba se avisa en el titulo de la ventana (ver main.py).
DB_PATH = os.environ.get("TPV_DB") or os.path.join(
    os.path.dirname(__file__), "tpv2.db")
if not os.path.isabs(DB_PATH):
    DB_PATH = os.path.join(os.path.dirname(__file__), DB_PATH)

# Modo prueba: se decide por el NOMBRE de la base, no por la variable de
# entorno. Si la variable no llega al proceso hijo (pasa cuando el TPV se
# abre con pythonw o desde un acceso directo), la franja de advertencia
# no se dibujaba y la ventana de prueba parecia la real: el peor de los
# escenarios posibles.
MODO_PRUEBA = ("prueba" in os.path.basename(DB_PATH).lower()
               or "test" in os.path.basename(DB_PATH).lower()
               or bool(os.environ.get("TPV_DB")))


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

    # Categorias habilitadas para cada vendedor. Si un vendedor no tiene
    # ninguna fila, ve el catalogo completo (es lo esperable al crearlo).
    c.execute("""
        CREATE TABLE IF NOT EXISTS vendedor_categorias (
            vendedor_id  INTEGER NOT NULL REFERENCES vendedores(id) ON DELETE CASCADE,
            categoria_id INTEGER NOT NULL REFERENCES categorias(id) ON DELETE CASCADE,
            PRIMARY KEY (vendedor_id, categoria_id)
        )
    """)

    # ─────────────────────────────────────────
    # BITACORA DE ACCIONES SENSIBLES
    # Quien autorizo cada anulacion, devolucion o ajuste de stock. Sin
    # esto, el arqueo muestra que falta plata pero no por que: una
    # devolucion de $8.000 y un faltante de $8.000 son indistinguibles
    # de un faltante sin explicacion.
    # ─────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS bitacora (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            accion       TEXT NOT NULL,
            detalle      TEXT,
            monto        REAL,
            responsable  TEXT NOT NULL,
            referencia   TEXT,
            fecha        TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    c.execute("""
        CREATE INDEX IF NOT EXISTS ix_bitacora_fecha ON bitacora(fecha)
    """)

    # ─────────────────────────────────────────
    # RECARGOS POR FRANJA HORARIA
    # Ajuste de precio segun dia y hora. dias: string con los numeros de
    # dia separados por coma (0=domingo, como strftime %w).
    # hora_desde > hora_hasta significa que la franja cruza la medianoche
    # (ej: 18:00 a 08:00).
    # categoria_id NULL = se aplica a todo el catalogo.
    # ─────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS recargos_horarios (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre       TEXT NOT NULL,
            porcentaje   REAL NOT NULL,
            dias         TEXT NOT NULL DEFAULT '0,1,2,3,4,5,6',
            hora_desde   INTEGER NOT NULL DEFAULT 0,
            hora_hasta   INTEGER NOT NULL DEFAULT 24,
            categoria_id INTEGER REFERENCES categorias(id) ON DELETE CASCADE,
            activo       INTEGER NOT NULL DEFAULT 1,
            creado_en    TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    # ─────────────────────────────────────────
    # RECARGOS POR HORARIO
    # El local cierra y pasa a atender por ventanilla: cada cliente lleva
    # mas tiempo y no se puede reponer mientras se atiende. El precio
    # nocturno cubre eso. Se guarda como regla, no como precio: si se
    # tocaran los precios reales, al volver al horario normal habria que
    # deshacerlo y cualquier corte de luz dejaria el catalogo mal.
    # ─────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS recargos_horario (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre       TEXT NOT NULL,
            porcentaje   REAL NOT NULL,
            dias         TEXT NOT NULL,      -- '0,1,2,3,4,5,6' (0=lunes)
            hora_desde   INTEGER NOT NULL,   -- 18  => 18:00
            hora_hasta   INTEGER NOT NULL,   -- 8   => 08:00 (cruza medianoche)
            alcance      TEXT NOT NULL DEFAULT 'todo',  -- todo|categorias|productos
            activo       INTEGER NOT NULL DEFAULT 1,
            creado_en    TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS recargo_alcance (
            recargo_id   INTEGER NOT NULL REFERENCES recargos_horario(id) ON DELETE CASCADE,
            categoria_id INTEGER REFERENCES categorias(id) ON DELETE CASCADE,
            producto_id  INTEGER REFERENCES productos(id) ON DELETE CASCADE
        )
    """)
    c.execute("""
        CREATE INDEX IF NOT EXISTS ix_recargo_alcance
            ON recargo_alcance(recargo_id)
    """)

    # ─────────────────────────────────────────
    # LISTAS GUARDADAS
    # La lista de la heladera de bebidas es siempre la misma: lo que
    # cambia son los precios. Rehacer la seleccion cada vez que hay que
    # reimprimir es el trabajo que se quiere evitar.
    # ─────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS listas_guardadas (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre       TEXT NOT NULL UNIQUE,
            titulo       TEXT,
            por_categoria INTEGER NOT NULL DEFAULT 1,
            creado_en    TEXT DEFAULT (datetime('now','localtime')),
            usado_en     TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS lista_items (
            lista_id     INTEGER NOT NULL REFERENCES listas_guardadas(id) ON DELETE CASCADE,
            producto_id  INTEGER NOT NULL REFERENCES productos(id) ON DELETE CASCADE,
            PRIMARY KEY (lista_id, producto_id)
        )
    """)
    # Lineas escritas a mano: el queso vale $20.000 el kilo en el sistema
    # pero en la gondola conviene "$2.000 x 100g". No es un producto
    # distinto ni corresponde tocarle el precio real.
    c.execute("""
        CREATE TABLE IF NOT EXISTS lista_manual (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            lista_id     INTEGER NOT NULL REFERENCES listas_guardadas(id) ON DELETE CASCADE,
            texto        TEXT NOT NULL,
            precio_texto TEXT NOT NULL,
            categoria    TEXT,
            orden        INTEGER DEFAULT 0
        )
    """)

    # Cuando se imprimio la etiqueta de cada producto. Es el dato que
    # de verdad contesta "¿a cual le falta etiqueta?": la fecha de alta
    # solo dice cuando se cargo en el sistema, y un producto puede estar
    # cargado hace meses y recien ahora ir a la gondola.
    try:
        c.execute("ALTER TABLE productos ADD COLUMN etiqueta_impresa TEXT")
    except Exception:
        pass

    # ─────────────────────────────────────────
    # HISTORIAL DE PRECIOS
    # productos.modificado_en se pisa con cualquier cambio y no dice QUE
    # cambio. Para saber que etiquetas reimprimir hace falta el registro
    # de cada cambio de precio con su fecha.
    # ─────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS historial_precios (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            producto_id  INTEGER NOT NULL REFERENCES productos(id) ON DELETE CASCADE,
            precio_viejo REAL,
            precio_nuevo REAL NOT NULL,
            motivo       TEXT,
            fecha        TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    c.execute("""
        CREATE INDEX IF NOT EXISTS ix_hist_precios_fecha
            ON historial_precios(fecha)
    """)

    # ─────────────────────────────────────────
    # LISTA DE COMPRAS
    # Lo que hay que comprar y no sale de la reposicion automatica:
    # bolsas, rollos de ticket, lo que pidio un cliente.
    # ─────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS lista_compras (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            texto        TEXT NOT NULL,
            cantidad     TEXT,
            proveedor    TEXT,
            nota         TEXT,
            comprado     INTEGER NOT NULL DEFAULT 0,
            creado_en    TEXT DEFAULT (datetime('now','localtime')),
            comprado_en  TEXT
        )
    """)
    # Cuantas veces lo pidieron y cuando. Un producto que piden tres
    # clientes distintos es una decision de compra; uno solo puede ser un
    # capricho. Sin llevar la cuenta, las dos cosas se ven igual.
    for _col, _tipo in (("pedidos", "INTEGER DEFAULT 1"),
                        ("ultimo_pedido", "TEXT")):
        try:
            c.execute(f"ALTER TABLE lista_compras ADD COLUMN {_col} {_tipo}")
        except Exception:
            pass

    # ─────────────────────────────────────────
    # COLA DE REVISION
    # Estado de la revision de catalogo: por donde va uno recorriendo los
    # productos. Los que no tienen fila figuran como "sin revisar".
    # ─────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS revision_productos (
            producto_id  INTEGER PRIMARY KEY REFERENCES productos(id) ON DELETE CASCADE,
            estado       TEXT NOT NULL DEFAULT 'pendiente',
            motivo       TEXT,
            notas        TEXT,
            creado_en    TEXT DEFAULT (datetime('now','localtime')),
            revisado_en  TEXT
        )
    """)
    c.execute("""
        CREATE INDEX IF NOT EXISTS ix_revision_estado
            ON revision_productos(estado)
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
        # ARQUEO: lo que se conto fisicamente al cerrar, contra lo que el
        # sistema esperaba. Sin este dato un faltante es invisible.
        "ALTER TABLE sesiones_caja ADD COLUMN efectivo_contado REAL",
        "ALTER TABLE sesiones_caja ADD COLUMN diferencia REAL",
        "ALTER TABLE sesiones_caja ADD COLUMN arqueo_notas TEXT",
        # Como se cobra la comision del vendedor:
        #   'recargo'   -> el cliente ve el precio con la comision sumada;
        #                  el margen del negocio queda intacto.
        #   'descuento' -> el cliente ve el precio de lista y la comision
        #                  sale del margen del negocio.
        "ALTER TABLE vendedores ADD COLUMN modo_comision TEXT DEFAULT 'recargo'",
        # Con que nombre sale el folleto del vendedor. Vacio = su nombre
        # de pila. Sirve para el que revende con marca propia.
        "ALTER TABLE vendedores ADD COLUMN nombre_comercial TEXT",
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

    # Desglose de pagos mixtos. Sin esto, una venta pagada mitad en
    # efectivo y mitad en otra cosa imputaba TODO a efectivo y el arqueo
    # daba un sobrante que nadie podia explicar.
    for _col, _tipo in (("monto_efectivo", "REAL DEFAULT 0"),
                        ("monto_tarjeta",  "REAL DEFAULT 0"),
                        ("monto_qr",       "REAL DEFAULT 0"),
                        ("monto_cta_cte",  "REAL DEFAULT 0")):
        try:
            c.execute(f"ALTER TABLE ventas ADD COLUMN {_col} {_tipo}")
        except Exception:
            pass          # ya existe

    # Ventas anteriores al desglose: se completan desde metodo_pago. Sin
    # esto los informes por medio de pago daban todo en cero para el
    # historico, que es justamente donde estan casi todas las ventas.
    try:
        c.execute("""
            UPDATE ventas
               SET monto_efectivo = CASE WHEN metodo_pago IN ('efectivo','mixto')
                                         THEN total ELSE 0 END,
                   monto_tarjeta  = CASE WHEN metodo_pago = 'tarjeta'
                                         THEN total ELSE 0 END,
                   monto_qr       = CASE WHEN metodo_pago = 'qr'
                                         THEN total ELSE 0 END,
                   monto_cta_cte  = CASE WHEN metodo_pago = 'cuenta_corriente'
                                         THEN total ELSE 0 END
             WHERE COALESCE(monto_efectivo,0) = 0
               AND COALESCE(monto_tarjeta,0)  = 0
               AND COALESCE(monto_qr,0)       = 0
               AND COALESCE(monto_cta_cte,0)  = 0
               AND COALESCE(total,0) > 0
        """)
    except Exception as _e:
        logging.debug(f"No se pudo completar el desglose historico: {_e}")

    # Indices sobre las tablas que crecen con cada venta. Sin estos,
    # buscar los movimientos de un cliente o los de una sesion obliga a
    # recorrer la tabla entera: con pocos meses de uso ya se nota.
    for _idx in (
        "CREATE INDEX IF NOT EXISTS ix_mov_caja_sesion ON movimientos_caja(sesion_id)",
        "CREATE INDEX IF NOT EXISTS ix_mov_cuenta_cliente ON movimientos_cuenta(cliente_id)",
        "CREATE INDEX IF NOT EXISTS ix_cta_cte_cliente ON cuentas_corrientes(cliente_id)",
        "CREATE INDEX IF NOT EXISTS ix_ajustes_producto ON ajustes_stock(producto_id)",
        "CREATE INDEX IF NOT EXISTS ix_devoluciones_venta ON devoluciones(venta_id)",
        "CREATE INDEX IF NOT EXISTS ix_sesiones_cierre ON sesiones_caja(cerrada, cierre_en)",
        "CREATE INDEX IF NOT EXISTS ix_ventas_fecha ON ventas(fecha)",
        "CREATE INDEX IF NOT EXISTS ix_detalle_ventas_venta ON detalle_ventas(venta_id)",
        "CREATE INDEX IF NOT EXISTS ix_detalle_ventas_producto ON detalle_ventas(producto_id)",
        "CREATE INDEX IF NOT EXISTS ix_lotes_producto ON lotes(producto_id, cantidad_restante)",
        "CREATE INDEX IF NOT EXISTS ix_lotes_vencimiento ON lotes(fecha_vencimiento)",
    ):
        try:
            c.execute(_idx)
        except Exception as _e:
            logging.debug(f"No se pudo crear el indice: {_e}")

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
            # Sin stock suficiente hay dos posturas y las dos son validas:
            #   bloquear   -> la venta no se registra (control estricto)
            #   permitir   -> se vende igual y el stock queda en negativo,
            #                 para corregirlo despues con un ajuste
            # En un autoservicio real lo segundo es lo habitual: el stock
            # nunca esta perfecto y frenar la caja con el cliente adelante
            # cuesta mas que el descuadre.
            try:
                from config import cfg
                permitir = cfg().get("permitir_venta_sin_stock", True)
            except Exception:
                permitir = True
            if not permitir:
                return False
            # Se consume lo que haya y el resto queda como faltante: el
            # lote mas viejo absorbe el negativo para que quede rastro.
            if lotes:
                # El lote mas viejo absorbe el faltante: queda en negativo
                # y asi el descuadre se ve en el stock, no se pierde.
                falta = cantidad - total_disponible
                conn.execute(
                    "UPDATE lotes SET cantidad_restante = cantidad_restante - ? "
                    "WHERE id = ?", (falta, lotes[0]["id"]))
                cantidad = total_disponible
            else:
                # Nunca tuvo ingreso: se crea un lote en negativo para que
                # el faltante quede visible en vez de perderse.
                cur = conn.execute("""
                    INSERT INTO lotes (producto_id, cantidad, cantidad_restante,
                                       costo_unitario, tipo, notas)
                    SELECT ?, 0, ?, COALESCE(costo_ultimo, 0), 'ajuste',
                           'Venta sin stock registrado'
                    FROM productos WHERE id = ?
                """, (producto_id, -cantidad, producto_id))
                if detalle_venta_id:
                    conn.execute("""
                        INSERT INTO detalle_ventas_lotes
                            (detalle_venta_id, lote_id, cantidad)
                        VALUES (?,?,?)
                    """, (detalle_venta_id, cur.lastrowid, cantidad))
                if cerrar:
                    conn.commit()
                    conn.close()
                return True

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


def cerrar_sesion_caja(sesion_id: int, notas: str = "",
                       efectivo_contado: float = None,
                       arqueo_notas: str = "") -> dict:
    """Cierra la sesión de caja y retorna el resumen.

    efectivo_contado: lo que hay FISICO en el cajón al cerrar. Se guarda
    junto con la diferencia contra lo esperado. Sin este dato no hay
    arqueo: un faltante por un vuelto mal dado o un cobro no registrado
    no deja ningún rastro y nunca se puede rastrear a un turno.
    """
    with get_connection() as conn:
        diferencia = None
        if efectivo_contado is not None:
            fila = conn.execute(
                "SELECT fondo_inicial, total_efectivo FROM sesiones_caja "
                "WHERE id = ?", (sesion_id,)).fetchone()
            movs = conn.execute("""
                SELECT COALESCE(SUM(CASE WHEN tipo='ingreso' THEN monto
                                         ELSE -monto END), 0)
                FROM movimientos_caja WHERE sesion_id = ?
            """, (sesion_id,)).fetchone()[0]
            esperado = ((fila["fondo_inicial"] or 0)
                        + (fila["total_efectivo"] or 0) + (movs or 0))
            diferencia = round(float(efectivo_contado) - esperado, 2)

        conn.execute("""
            UPDATE sesiones_caja
            SET cerrada = 1,
                cierre_en = datetime('now','localtime'),
                notas = ?,
                efectivo_contado = ?,
                diferencia = ?,
                arqueo_notas = ?
            WHERE id = ?
        """, (notas, efectivo_contado, diferencia, arqueo_notas, sesion_id))
        conn.commit()

        sesion = conn.execute(
            "SELECT * FROM sesiones_caja WHERE id = ?", (sesion_id,)
        ).fetchone()
        return dict(sesion)


if __name__ == "__main__":
    inicializar_db()

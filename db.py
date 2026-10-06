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
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
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
            margen_pct  REAL DEFAULT 30.0,
            creado_en   TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    # ─────────────────────────────────────────
    # PROVEEDORES
    # ─────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS proveedores (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre          TEXT NOT NULL,
            telefono        TEXT,
            email           TEXT,
            notas           TEXT,
            activo          INTEGER DEFAULT 1,
            creado_en       TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    # ─────────────────────────────────────────
    # PRODUCTOS
    # ─────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS productos (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo          TEXT NOT NULL UNIQUE,
            descripcion     TEXT NOT NULL,
            categoria_id    INTEGER REFERENCES categorias(id) ON DELETE SET NULL,
            precio_base     REAL NOT NULL DEFAULT 0.0,
            costo_ultimo    REAL DEFAULT 0.0,
            margen_pct      REAL DEFAULT NULL,
            ignorar_alerta  INTEGER DEFAULT 0,
            vendido_por_peso INTEGER DEFAULT 0,
            marca           TEXT,
            imagen_url      TEXT,
            activo          INTEGER DEFAULT 1,
            creado_en       TEXT DEFAULT (datetime('now','localtime')),
            modificado_en   TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    # ─────────────────────────────────────────
    # PROMOCIONES
    # ─────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS promociones (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            producto_id     INTEGER NOT NULL REFERENCES productos(id) ON DELETE CASCADE,
            cantidad_minima INTEGER NOT NULL,
            precio_unitario REAL NOT NULL,
            fecha_desde     TEXT,
            fecha_hasta     TEXT,
            activa          INTEGER DEFAULT 1,
            descripcion     TEXT,
            creado_en       TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    # ─────────────────────────────────────────
    # PROMOS COMBINABLES
    # ─────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS promo_grupos (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre          TEXT NOT NULL,
            cantidad_minima INTEGER NOT NULL,
            tipo            TEXT NOT NULL DEFAULT 'precio_fijo',
            valor           REAL NOT NULL,
            fecha_desde     TEXT,
            fecha_hasta     TEXT,
            activa          INTEGER NOT NULL DEFAULT 1,
            creado_en       TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS promo_grupo_items (
            grupo_id    INTEGER NOT NULL REFERENCES promo_grupos(id) ON DELETE CASCADE,
            producto_id INTEGER NOT NULL REFERENCES productos(id) ON DELETE CASCADE,
            PRIMARY KEY (grupo_id, producto_id)
        )
    """)

    c.execute("""
        CREATE INDEX IF NOT EXISTS ix_promo_grupo_items_prod
            ON promo_grupo_items(producto_id)
    """)

    # ─────────────────────────────────────────
    # PROMOS COMBO POR CATEGORÍAS
    # ─────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS promo_combos (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre          TEXT NOT NULL,
            valor           REAL NOT NULL,
            fecha_desde     TEXT,
            fecha_hasta     TEXT,
            activa          INTEGER NOT NULL DEFAULT 1,
            creado_en       TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS promo_combo_slots (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            combo_id        INTEGER NOT NULL REFERENCES promo_combos(id) ON DELETE CASCADE,
            orden           INTEGER NOT NULL DEFAULT 0,
            nombre          TEXT NOT NULL,
            cantidad        INTEGER NOT NULL DEFAULT 1
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS promo_combo_slot_items (
            slot_id     INTEGER NOT NULL REFERENCES promo_combo_slots(id) ON DELETE CASCADE,
            producto_id INTEGER NOT NULL REFERENCES productos(id) ON DELETE CASCADE,
            PRIMARY KEY (slot_id, producto_id)
        )
    """)

    c.execute("""
        CREATE INDEX IF NOT EXISTS ix_promo_combo_slot_items_prod
            ON promo_combo_slot_items(producto_id)
    """)

    c.execute("""
        CREATE INDEX IF NOT EXISTS ix_promo_combo_slots_combo
            ON promo_combo_slots(combo_id)
    """)

    # ─────────────────────────────────────────
    # LOTES DE STOCK
    # ─────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS lotes (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            producto_id         INTEGER NOT NULL REFERENCES productos(id) ON DELETE CASCADE,
            proveedor_id        INTEGER REFERENCES proveedores(id) ON DELETE SET NULL,
            cantidad            REAL NOT NULL,
            cantidad_restante   REAL NOT NULL,
            costo_unitario      REAL DEFAULT 0.0,
            fecha_ingreso       TEXT DEFAULT (datetime('now','localtime')),
            fecha_vencimiento   TEXT,
            notas               TEXT,
            tipo                TEXT DEFAULT 'ingreso',
            motivo_ajuste       TEXT
        )
    """)

    # ─────────────────────────────────────────
    # DEVOLUCIONES
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
    # VENDEDORES POR CATEGORÍA
    # ─────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS vendedor_categorias (
            vendedor_id  INTEGER NOT NULL REFERENCES vendedores(id) ON DELETE CASCADE,
            categoria_id INTEGER NOT NULL REFERENCES categorias(id) ON DELETE CASCADE,
            PRIMARY KEY (vendedor_id, categoria_id)
        )
    """)

    # ─────────────────────────────────────────
    # BITÁCORA
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
    # ─────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS recargos_horario (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre       TEXT NOT NULL,
            porcentaje   REAL NOT NULL,
            dias         TEXT NOT NULL,
            hora_desde   INTEGER NOT NULL,
            hora_hasta   INTEGER NOT NULL,
            alcance      TEXT NOT NULL DEFAULT 'todo',
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
    # ─────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS listas_guardadas (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre        TEXT NOT NULL UNIQUE,
            titulo        TEXT,
            por_categoria INTEGER NOT NULL DEFAULT 1,
            creado_en     TEXT DEFAULT (datetime('now','localtime')),
            usado_en      TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS lista_items (
            lista_id     INTEGER NOT NULL REFERENCES listas_guardadas(id) ON DELETE CASCADE,
            producto_id  INTEGER NOT NULL REFERENCES productos(id) ON DELETE CASCADE,
            PRIMARY KEY (lista_id, producto_id)
        )
    """)

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

    # ─────────────────────────────────────────
    # MIGRACIONES DE PRODUCTOS
    # ─────────────────────────────────────────
    try:
        c.execute("ALTER TABLE productos ADD COLUMN etiqueta_impresa TEXT")
    except Exception:
        pass

    try:
        c.execute("ALTER TABLE productos ADD COLUMN publicar_web "
                  "INTEGER NOT NULL DEFAULT 1")
    except Exception:
        pass

    # ─────────────────────────────────────────
    # HISTORIAL DE PRECIOS
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

    for _col, _tipo in (("pedidos", "INTEGER DEFAULT 1"),
                        ("ultimo_pedido", "TEXT")):
        try:
            c.execute(f"ALTER TABLE lista_compras ADD COLUMN {_col} {_tipo}")
        except Exception:
            pass

    # ─────────────────────────────────────────
    # COLA DE REVISION
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
    # DEVOLUCIONES DETALLE
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
    # AJUSTES DE STOCK
    # ─────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS ajustes_stock (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            producto_id       INTEGER NOT NULL REFERENCES productos(id) ON DELETE CASCADE,
            lote_id           INTEGER REFERENCES lotes(id) ON DELETE SET NULL,
            cantidad_anterior REAL NOT NULL,
            cantidad_nueva    REAL NOT NULL,
            diferencia        REAL NOT NULL,
            motivo            TEXT NOT NULL,
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
            cierre_en       TEXT,
            total_efectivo  REAL DEFAULT 0.0,
            total_tarjeta   REAL DEFAULT 0.0,
            total_qr        REAL DEFAULT 0.0,
            total_cuenta_corriente REAL DEFAULT 0.0,
            notas           TEXT,
            cerrada         INTEGER DEFAULT 0
        )
    """)

    # ─────────────────────────────────────────
    # VENTAS
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
    # DETALLE DE VENTAS
    # ─────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS detalle_ventas (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            venta_id        INTEGER NOT NULL REFERENCES ventas(id) ON DELETE CASCADE,
            producto_id     INTEGER NOT NULL REFERENCES productos(id) ON DELETE RESTRICT,
            descripcion     TEXT NOT NULL,
            cantidad        REAL NOT NULL,
            precio_unitario REAL NOT NULL,
            subtotal        REAL NOT NULL,
            promo_aplicada  INTEGER DEFAULT 0
        )
    """)

    # ─────────────────────────────────────────
    # MOVIMIENTOS DE CAJA
    # ─────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS movimientos_caja (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            sesion_id       INTEGER REFERENCES sesiones_caja(id) ON DELETE SET NULL,
            tipo            TEXT NOT NULL,
            monto           REAL NOT NULL,
            concepto        TEXT,
            fecha            TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    # ─────────────────────────────────────────
    # ÍNDICES
    # ─────────────────────────────────────────
    c.execute("CREATE INDEX IF NOT EXISTS idx_productos_codigo ON productos(codigo)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_lotes_producto ON lotes(producto_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_lotes_fifo ON lotes(producto_id, fecha_ingreso)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_ventas_fecha ON ventas(fecha)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_ventas_sesion ON ventas(sesion_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_detalle_venta ON detalle_ventas(venta_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_promociones_producto ON promociones(producto_id)")

    # ─────────────────────────────────────────
    # VENDEDORES
    # ─────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS vendedores (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo          TEXT UNIQUE NOT NULL,
            nombre          TEXT NOT NULL,
            usuario         TEXT UNIQUE NOT NULL,
            password_hash   TEXT NOT NULL,
            telefono        TEXT,
            comision_pct    REAL NOT NULL DEFAULT 0,
            modo_cobro      TEXT NOT NULL DEFAULT 'negocio',
            activo          INTEGER DEFAULT 1,
            creado_en       TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    c.execute("CREATE INDEX IF NOT EXISTS idx_vendedores_codigo ON vendedores(codigo)")

    # ─────────────────────────────────────────
    # MIGRACIONES AUTOMÁTICAS
    # ─────────────────────────────────────────
    migraciones = [
        "ALTER TABLE productos ADD COLUMN margen_pct REAL DEFAULT NULL",
        "ALTER TABLE ventas ADD COLUMN cliente_id INTEGER REFERENCES clientes(id)",
        "ALTER TABLE productos ADD COLUMN ignorar_alerta INTEGER DEFAULT 0",
        "ALTER TABLE productos ADD COLUMN vendido_por_peso INTEGER DEFAULT 0",
        "ALTER TABLE productos ADD COLUMN marca TEXT",
        "ALTER TABLE productos ADD COLUMN alerta_dias_vto INTEGER DEFAULT NULL",
        "ALTER TABLE sesiones_caja ADD COLUMN efectivo_contado REAL",
        "ALTER TABLE sesiones_caja ADD COLUMN diferencia REAL",
        "ALTER TABLE sesiones_caja ADD COLUMN arqueo_notas TEXT",
        "ALTER TABLE vendedores ADD COLUMN modo_comision TEXT DEFAULT 'recargo'",
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
        "ALTER TABLE productos ADD COLUMN fraccionable INTEGER DEFAULT 0",
        "ALTER TABLE productos ADD COLUMN alerta_stock_umbral INTEGER DEFAULT NULL",
        "ALTER TABLE categorias ADD COLUMN alerta_stock_umbral INTEGER DEFAULT NULL",
        "ALTER TABLE productos ADD COLUMN web_fraccion_gramos INTEGER DEFAULT NULL",
        "ALTER TABLE productos ADD COLUMN controla_stock INTEGER DEFAULT 1",
    ]

    for sql in migraciones:
        try:
            c.execute(sql)
            conn.commit()
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────────────────
    # REPARACIÓN DE clientes_old_notnull
    # ─────────────────────────────────────────────────────────────────────────
    tablas_hoy = {r[0] for r in c.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}

    if "clientes_old_notnull" in tablas_hoy:
        fk_estaban_on = c.execute(
            "PRAGMA foreign_keys").fetchone()[0]

        conn.commit()

        c.execute("PRAGMA foreign_keys = OFF")

        # IMPORTANTE:
        # Evita que SQLite modifique automáticamente las referencias de
        # otras tablas cuando una tabla es renombrada temporalmente.
        # Sin esto, al hacer:
        #
        #     ALTER TABLE ventas RENAME TO ventas_tmp_repar
        #
        # SQLite puede modificar referencias de otras tablas para apuntar
        # al nombre temporal. Luego se elimina la tabla temporal y queda
        # una FK rota.
        c.execute("PRAGMA legacy_alter_table = ON")

        try:
            c.execute("BEGIN")

            # Recuperar clientes que pudieran existir solamente en
            # clientes_old_notnull.
            cols_cli = [
                r[1] for r in
                c.execute("PRAGMA table_info(clientes_old_notnull)")
            ]
            cols_cli_sql = ", ".join(cols_cli)

            c.execute(f"""
                INSERT OR IGNORE INTO clientes ({cols_cli_sql})
                SELECT {cols_cli_sql}
                FROM clientes_old_notnull
            """)

            # Detectar todas las tablas cuyo esquema todavía referencia
            # clientes_old_notnull.
            afectadas = [
                (row[0], row[1])
                for row in c.execute(
                    "SELECT name, sql FROM sqlite_master "
                    "WHERE type='table' AND sql LIKE '%clientes_old_notnull%'"
                ).fetchall()
                if row[0] != "clientes_old_notnull"
            ]

            indices_por_tabla = {}

            for tabla, _ in afectadas:
                indices_por_tabla[tabla] = [
                    r[0]
                    for r in c.execute(
                        "SELECT sql FROM sqlite_master "
                        "WHERE type='index' "
                        "AND tbl_name=? "
                        "AND sql IS NOT NULL",
                        (tabla,)
                    ).fetchall()
                ]

            for tabla, sql_original in afectadas:
                cols = [
                    r[1]
                    for r in c.execute(
                        f"PRAGMA table_info({tabla})"
                    )
                ]

                cols_sql = ", ".join(cols)

                sql_corregido = sql_original.replace(
                    "clientes_old_notnull",
                    "clientes"
                )

                # Con legacy_alter_table=ON, este rename no debe
                # reescribir FKs de otras tablas hacia el nombre temporal.
                c.execute(
                    f"ALTER TABLE {tabla} RENAME TO {tabla}_tmp_repar"
                )

                c.execute(sql_corregido)

                c.execute(f"""
                    INSERT INTO {tabla} ({cols_sql})
                    SELECT {cols_sql}
                    FROM {tabla}_tmp_repar
                """)

                c.execute(f"DROP TABLE {tabla}_tmp_repar")

                for idx_sql in indices_por_tabla.get(tabla, []):
                    c.execute(idx_sql)

            c.execute("DROP TABLE clientes_old_notnull")

            violaciones = c.execute(
                "PRAGMA foreign_key_check"
            ).fetchall()

            if violaciones:
                raise sqlite3.IntegrityError(
                    f"foreign_key_check encontró {len(violaciones)} "
                    "inconsistencias al reparar clientes_old_notnull: "
                    f"{violaciones[:5]}"
                )

            conn.commit()

        except Exception:
            conn.rollback()
            raise

        finally:
            # Devolver SQLite a su comportamiento normal.
            c.execute("PRAGMA legacy_alter_table = OFF")

            if fk_estaban_on:
                c.execute("PRAGMA foreign_keys = ON")

    # ─────────────────────────────────────────────────────────────────────────
    # MIGRACIÓN: clientes.dni DE NOT NULL A NULLABLE
    # ─────────────────────────────────────────────────────────────────────────
    dni_col = next(
        (
            r for r in c.execute("PRAGMA table_info(clientes)")
            if r[1] == "dni"
        ),
        None
    )

    if dni_col and dni_col[3]:
        fk_estaban_on = c.execute(
            "PRAGMA foreign_keys"
        ).fetchone()[0]

        conn.commit()

        c.execute("PRAGMA foreign_keys = OFF")

        try:
            c.execute("BEGIN")

            c.execute("""
                CREATE TABLE clientes_new (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    dni             TEXT UNIQUE,
                    nombre          TEXT NOT NULL,
                    telefono        TEXT,
                    tope_credito    REAL DEFAULT 0.0,
                    activo          INTEGER DEFAULT 1,
                    creado_en       TEXT DEFAULT (datetime('now','localtime'))
                )
            """)

            c.execute("""
                INSERT INTO clientes_new (
                    id,
                    dni,
                    nombre,
                    telefono,
                    tope_credito,
                    activo,
                    creado_en
                )
                SELECT
                    id,
                    dni,
                    nombre,
                    telefono,
                    tope_credito,
                    activo,
                    creado_en
                FROM clientes
            """)

            c.execute("DROP TABLE clientes")
            c.execute("ALTER TABLE clientes_new RENAME TO clientes")

            violaciones = c.execute(
                "PRAGMA foreign_key_check"
            ).fetchall()

            if violaciones:
                raise sqlite3.IntegrityError(
                    f"foreign_key_check encontró {len(violaciones)} "
                    "inconsistencias tras migrar clientes.dni"
                )

            conn.commit()

        except Exception:
            conn.rollback()
            raise

        finally:
            if fk_estaban_on:
                c.execute("PRAGMA foreign_keys = ON")

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
            dni             TEXT UNIQUE,
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
            tipo            TEXT NOT NULL,
            monto           REAL NOT NULL,
            venta_id        INTEGER REFERENCES ventas(id),
            concepto        TEXT,
            autorizado_por  TEXT,
            fecha           TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_clientes_dni ON clientes(dni)"
    )

    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_movimientos_cliente "
        "ON movimientos_cuenta(cliente_id)"
    )

    # ─────────────────────────────────────────────────────────────────────────
    # DESGLOSE DE PAGOS MIXTOS
    # ─────────────────────────────────────────────────────────────────────────
    for _col, _tipo in (
        ("monto_efectivo", "REAL DEFAULT 0"),
        ("monto_tarjeta",  "REAL DEFAULT 0"),
        ("monto_qr",       "REAL DEFAULT 0"),
        ("monto_cta_cte",  "REAL DEFAULT 0")
    ):
        try:
            c.execute(
                f"ALTER TABLE ventas ADD COLUMN {_col} {_tipo}"
            )
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────────────────
    # CUPONES: un monto en $ para gastar en una categoria hasta una fecha
    # ─────────────────────────────────────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS cupones (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo         TEXT NOT NULL UNIQUE,
            monto          REAL NOT NULL,
            monto_restante REAL NOT NULL,
            categoria_id   INTEGER REFERENCES categorias(id) ON DELETE SET NULL,
            categoria_nombre TEXT,
            fecha_desde    TEXT,
            fecha_hasta    TEXT NOT NULL,
            permite_saldo  INTEGER DEFAULT 0,
            nota           TEXT,
            anulado        INTEGER DEFAULT 0,
            motivo_anulacion TEXT,
            creado_en      TEXT DEFAULT (datetime('now','localtime')),
            creado_por     TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS cupones_usos (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            cupon_id   INTEGER NOT NULL REFERENCES cupones(id) ON DELETE CASCADE,
            venta_id   INTEGER NOT NULL REFERENCES ventas(id) ON DELETE CASCADE,
            monto      REAL NOT NULL,
            consumido  REAL NOT NULL,
            fecha      TEXT DEFAULT (datetime('now','localtime')),
            revertido  INTEGER DEFAULT 0
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_cupones_usos_venta ON cupones_usos(venta_id)")
    for _col, _tipo in (("cupon_id", "INTEGER"), ("cupon_monto", "REAL DEFAULT 0")):
        try:
            c.execute(f"ALTER TABLE ventas ADD COLUMN {_col} {_tipo}")
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────────────────
    # COMPLETAR DESGLOSE HISTÓRICO
    # ─────────────────────────────────────────────────────────────────────────
    try:
        c.execute("""
            UPDATE ventas
               SET monto_efectivo =
                       CASE
                           WHEN metodo_pago IN ('efectivo','mixto')
                           THEN total
                           ELSE 0
                       END,
                   monto_tarjeta =
                       CASE
                           WHEN metodo_pago = 'tarjeta'
                           THEN total
                           ELSE 0
                       END,
                   monto_qr =
                       CASE
                           WHEN metodo_pago = 'qr'
                           THEN total
                           ELSE 0
                       END,
                   monto_cta_cte =
                       CASE
                           WHEN metodo_pago = 'cuenta_corriente'
                           THEN total
                           ELSE 0
                       END
             WHERE COALESCE(monto_efectivo,0) = 0
               AND COALESCE(monto_tarjeta,0)  = 0
               AND COALESCE(monto_qr,0)       = 0
               AND COALESCE(monto_cta_cte,0)  = 0
               AND COALESCE(total,0) > 0
        """)
    except Exception as _e:
        logging.debug(
            f"No se pudo completar el desglose historico: {_e}"
        )

    # ─────────────────────────────────────────────────────────────────────────
    # ÍNDICES ADICIONALES
    # ─────────────────────────────────────────────────────────────────────────
    for _idx in (
        "CREATE INDEX IF NOT EXISTS ix_mov_caja_sesion "
        "ON movimientos_caja(sesion_id)",

        "CREATE INDEX IF NOT EXISTS ix_mov_cuenta_cliente "
        "ON movimientos_cuenta(cliente_id)",

        "CREATE INDEX IF NOT EXISTS ix_cta_cte_cliente "
        "ON cuentas_corrientes(cliente_id)",

        "CREATE INDEX IF NOT EXISTS ix_ajustes_producto "
        "ON ajustes_stock(producto_id)",

        "CREATE INDEX IF NOT EXISTS ix_devoluciones_venta "
        "ON devoluciones(venta_id)",

        "CREATE INDEX IF NOT EXISTS ix_sesiones_cierre "
        "ON sesiones_caja(cerrada, cierre_en)",

        "CREATE INDEX IF NOT EXISTS ix_ventas_fecha "
        "ON ventas(fecha)",

        "CREATE INDEX IF NOT EXISTS ix_detalle_ventas_venta "
        "ON detalle_ventas(venta_id)",

        "CREATE INDEX IF NOT EXISTS ix_detalle_ventas_producto "
        "ON detalle_ventas(producto_id)",

        "CREATE INDEX IF NOT EXISTS ix_lotes_producto "
        "ON lotes(producto_id, cantidad_restante)",

        "CREATE INDEX IF NOT EXISTS ix_lotes_vencimiento "
        "ON lotes(fecha_vencimiento)",
    ):
        try:
            c.execute(_idx)
        except Exception as _e:
            logging.debug(
                f"No se pudo crear el indice: {_e}"
            )

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
            "SELECT COALESCE(SUM(cantidad_restante), 0) "
            "FROM lotes WHERE producto_id = ?",
            (producto_id,)
        ).fetchone()

        return row[0]


def descontar_stock_fifo(
    producto_id: int,
    cantidad: float,
    conn=None,
    detalle_venta_id: int = None
) -> bool:
    """
    Descuenta stock usando FIFO (lote más antiguo primero).
    Si se pasa detalle_venta_id, registra la trazabilidad lote→venta.
    Retorna True si había stock suficiente, False si no.
    """
    cerrar = conn is None

    if conn is None:
        conn = get_connection()

    try:
        # Productos sin control de stock no generan lotes ni ajuste.
        fila_ctrl = conn.execute(
            "SELECT COALESCE(controla_stock, 1) "
            "FROM productos WHERE id = ?",
            (producto_id,)
        ).fetchone()

        if fila_ctrl and not fila_ctrl[0]:
            if cerrar:
                conn.close()
            return True

        lotes = conn.execute("""
            SELECT id, cantidad_restante
            FROM lotes
            WHERE producto_id = ? AND cantidad_restante > 0
            ORDER BY fecha_ingreso ASC
        """, (producto_id,)).fetchall()

        total_disponible = sum(
            l["cantidad_restante"] for l in lotes
        )

        if total_disponible < cantidad:
            try:
                from config import cfg
                permitir = cfg().get(
                    "permitir_venta_sin_stock",
                    True
                )
            except Exception:
                permitir = True

            if not permitir:
                return False

            if lotes:
                falta = cantidad - total_disponible

                conn.execute(
                    "UPDATE lotes "
                    "SET cantidad_restante = cantidad_restante - ? "
                    "WHERE id = ?",
                    (falta, lotes[0]["id"])
                )

                cantidad = total_disponible

            else:
                cur = conn.execute("""
                    INSERT INTO lotes (
                        producto_id,
                        cantidad,
                        cantidad_restante,
                        costo_unitario,
                        tipo,
                        notas
                    )
                    SELECT
                        ?,
                        0,
                        ?,
                        COALESCE(costo_ultimo, 0),
                        'ajuste',
                        'Venta sin stock registrado'
                    FROM productos
                    WHERE id = ?
                """, (
                    producto_id,
                    -cantidad,
                    producto_id
                ))

                if detalle_venta_id:
                    conn.execute("""
                        INSERT INTO detalle_ventas_lotes (
                            detalle_venta_id,
                            lote_id,
                            cantidad
                        )
                        VALUES (?,?,?)
                    """, (
                        detalle_venta_id,
                        cur.lastrowid,
                        cantidad
                    ))

                if cerrar:
                    conn.commit()
                    conn.close()

                return True

        restante = cantidad

        for lote in lotes:
            if restante <= 0:
                break

            usado = min(
                lote["cantidad_restante"],
                restante
            )

            conn.execute(
                "UPDATE lotes "
                "SET cantidad_restante = cantidad_restante - ? "
                "WHERE id = ?",
                (usado, lote["id"])
            )

            if detalle_venta_id:
                conn.execute("""
                    INSERT INTO detalle_ventas_lotes (
                        detalle_venta_id,
                        lote_id,
                        cantidad
                    )
                    VALUES (?,?,?)
                """, (
                    detalle_venta_id,
                    lote["id"],
                    usado
                ))

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
            SELECT
                p.*,
                c.nombre as categoria_nombre,
                c.margen_pct
            FROM productos p
            LEFT JOIN categorias c
                ON p.categoria_id = c.id
            WHERE p.codigo = ?
              AND p.activo = 1
        """, (codigo,)).fetchone()

        return dict(row) if row else None


def get_precio_con_promo(
    producto_id: int,
    cantidad: float
) -> tuple[float, bool]:
    """
    Retorna (precio_unitario, promo_aplicada).
    Busca la mejor promoción vigente.
    """
    hoy = datetime.now().strftime("%Y-%m-%d")

    with get_connection() as conn:
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
        """, (
            producto_id,
            cantidad,
            hoy,
            hoy
        )).fetchone()

        if promo:
            return promo["precio_unitario"], True

        producto = conn.execute(
            "SELECT precio_base FROM productos WHERE id = ?",
            (producto_id,)
        ).fetchone()

        return (
            producto["precio_base"] if producto else 0.0,
            False
        )


# ─────────────────────────────────────────────────────────────────────────────
# FUNCIONES DE VENTA
# ─────────────────────────────────────────────────────────────────────────────

def registrar_venta(
    sesion_id: int,
    items: list[dict],
    metodo_pago: str,
    descuento_pct: float = 0.0
) -> int | None:
    """
    Registra una venta completa con sus ítems.
    """
    conn = get_connection()

    try:
        subtotales = [
            i["cantidad"] * i["precio_unitario"]
            for i in items
        ]

        total_bruto = sum(subtotales)
        descuento_monto = (
            total_bruto * (descuento_pct / 100)
        )
        total = total_bruto - descuento_monto

        cur = conn.execute("""
            INSERT INTO ventas (
                sesion_id,
                total,
                metodo_pago,
                descuento_pct,
                descuento_monto
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            sesion_id,
            total,
            metodo_pago,
            descuento_pct,
            descuento_monto
        ))

        venta_id = cur.lastrowid

        for item, subtotal in zip(items, subtotales):
            conn.execute("""
                INSERT INTO detalle_ventas (
                    venta_id,
                    producto_id,
                    descripcion,
                    cantidad,
                    precio_unitario,
                    subtotal,
                    promo_aplicada
                )
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

            ok = descontar_stock_fifo(
                item["producto_id"],
                item["cantidad"],
                conn=conn
            )

            if not ok:
                raise ValueError(
                    f"Stock insuficiente para: {item['descripcion']}"
                )

        col_metodo = {
            "efectivo": "total_efectivo",
            "tarjeta": "total_tarjeta",
            "qr": "total_qr",
            "cuenta_corriente": "total_cuenta_corriente"
        }.get(
            metodo_pago,
            "total_efectivo"
        )

        conn.execute(
            f"""
            UPDATE sesiones_caja
            SET {col_metodo} = {col_metodo} + ?
            WHERE id = ?
            """,
            (total, sesion_id)
        )

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

def abrir_sesion_caja(
    fondo_inicial: float = 0.0
) -> int:
    """Abre una nueva sesión de caja."""
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO sesiones_caja (fondo_inicial) VALUES (?)",
            (fondo_inicial,)
        )

        conn.commit()

        return cur.lastrowid


def get_sesion_abierta() -> dict | None:
    """Retorna la sesión de caja abierta actualmente."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM sesiones_caja "
            "WHERE cerrada = 0 "
            "ORDER BY id DESC "
            "LIMIT 1"
        ).fetchone()

        return dict(row) if row else None


def cerrar_sesion_caja(
    sesion_id: int,
    notas: str = "",
    efectivo_contado: float = None,
    arqueo_notas: str = ""
) -> dict:
    """Cierra la sesión de caja y retorna el resumen."""

    with get_connection() as conn:
        diferencia = None

        if efectivo_contado is not None:
            fila = conn.execute(
                "SELECT fondo_inicial, total_efectivo "
                "FROM sesiones_caja "
                "WHERE id = ?",
                (sesion_id,)
            ).fetchone()

            # total_efectivo ya incluye los movimientos manuales y las
            # devoluciones en efectivo (ver efectivo_esperado en
            # repositorio.py, que tiene que dar el mismo numero).
            esperado = (
                (fila["fondo_inicial"] or 0)
                + (fila["total_efectivo"] or 0)
            )

            diferencia = round(
                float(efectivo_contado) - esperado,
                2
            )

        conn.execute("""
            UPDATE sesiones_caja
            SET cerrada = 1,
                cierre_en = datetime('now','localtime'),
                notas = ?,
                efectivo_contado = ?,
                diferencia = ?,
                arqueo_notas = ?
            WHERE id = ?
        """, (
            notas,
            efectivo_contado,
            diferencia,
            arqueo_notas,
            sesion_id
        ))

        conn.commit()

        sesion = conn.execute(
            "SELECT * FROM sesiones_caja WHERE id = ?",
            (sesion_id,)
        ).fetchone()

        return dict(sesion)


if __name__ == "__main__":
    inicializar_db()
from db import get_conn
from datetime import datetime


def obtener_producto_id(cod_barra):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT id FROM catalogo WHERE cod_barra = ?
    """, (cod_barra,))

    row = cur.fetchone()
    conn.close()

    return row[0] if row else None


def obtener_stock(producto_id):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT SUM(cantidad_actual)
        FROM lotes
        WHERE producto_id = ?
    """, (producto_id,))

    result = cur.fetchone()
    conn.close()

    return result[0] if result and result[0] else 0


def descontar_stock(producto_id, cantidad):

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, cantidad_actual
        FROM lotes
        WHERE producto_id = ?
        AND cantidad_actual > 0
        ORDER BY fecha ASC
    """, (producto_id,))

    lotes = cur.fetchall()

    restante = cantidad

    for lote_id, stock in lotes:

        if restante <= 0:
            break

        usar = min(stock, restante)

        cur.execute("""
            UPDATE lotes
            SET cantidad_actual = cantidad_actual - ?
            WHERE id = ?
        """, (usar, lote_id))

        restante -= usar

    conn.commit()
    conn.close()

    return restante <= 0


def guardar_venta(items):

    conn = get_conn()
    cur = conn.cursor()

    fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for item in items:

        producto, cant, precio, total, cod_barra = item

        producto_id = obtener_producto_id(cod_barra)

        if not producto_id:
            conn.close()
            raise Exception(f"Producto no encontrado: {cod_barra}")

        stock_actual = obtener_stock(producto_id)

        if stock_actual < cant:
            conn.close()
            raise Exception(f"Stock insuficiente para {producto}")

        ok = descontar_stock(producto_id, cant)

        if not ok:
            conn.close()
            raise Exception(f"No se pudo descontar stock")

        cur.execute("""
            INSERT INTO ventas (fecha, producto, cantidad, precio, total, cod_barra)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (fecha, producto, cant, precio, total, cod_barra))

        # ✅ NUEVO
        cur.execute("""
            UPDATE catalogo
            SET fecha_ultima_venta = ?
            WHERE cod_barra = ?
        """, (fecha, cod_barra))

    conn.commit()
    conn.close()
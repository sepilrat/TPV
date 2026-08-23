"""
repositorio.py — Capa de acceso a datos centralizada TPV v2.0
Toda query a la DB pasa por acá. Los módulos UI no tocan get_connection directamente.
"""

import logging
from db import get_connection, descontar_stock_fifo
from datetime import datetime
import hashlib


# ─────────────────────────────────────────────────────────────────────────────
# PRODUCTOS
# ─────────────────────────────────────────────────────────────────────────────

def get_producto_por_codigo(codigo: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("""
            SELECT p.*, c.nombre as categoria_nombre, c.margen_pct
            FROM productos p
            LEFT JOIN categorias c ON p.categoria_id = c.id
            WHERE p.codigo = ? AND p.activo = 1
        """, (codigo,)).fetchone()
        return dict(row) if row else None


# ─────────────────────────────────────────────────────────────────────────────
# PRESENTACIONES (mismo stock, dos formas de venderlo)
# ─────────────────────────────────────────────────────────────────────────────

def get_presentacion_por_codigo(codigo: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("""
            SELECT pr.*, p.descripcion as producto_descripcion,
                   p.vendido_por_peso, p.precio_base
            FROM presentaciones pr
            JOIN productos p ON p.id = pr.producto_id
            WHERE pr.codigo = ? AND pr.activo = 1 AND p.activo = 1
        """, (codigo,)).fetchone()
        return dict(row) if row else None


def get_presentaciones(producto_id: int) -> list:
    with get_connection() as conn:
        return [dict(r) for r in conn.execute("""
            SELECT * FROM presentaciones
            WHERE producto_id = ? AND activo = 1
            ORDER BY factor
        """, (producto_id,)).fetchall()]


def crear_presentacion(producto_id, codigo, descripcion, factor, precio) -> dict:
    codigo = (codigo or "").strip()
    if not codigo:
        raise ValueError("La presentacion necesita su propio codigo de barras")
    if float(factor) <= 0:
        raise ValueError("El factor tiene que ser mayor a cero")
    if get_producto_por_codigo(codigo):
        raise ValueError(f"El codigo {codigo} ya es de un producto")
    with get_connection() as conn:
        cur = conn.execute("""
            INSERT INTO presentaciones (producto_id, codigo, descripcion, factor, precio)
            VALUES (?,?,?,?,?)
        """, (producto_id, codigo, descripcion, float(factor), float(precio)))
        return dict(conn.execute("SELECT * FROM presentaciones WHERE id=?",
                                 (cur.lastrowid,)).fetchone())


def actualizar_presentacion(pres_id, descripcion=None, factor=None, precio=None):
    sets, params = [], []
    for col, val in (("descripcion", descripcion), ("factor", factor),
                     ("precio", precio)):
        if val is not None:
            sets.append(f"{col}=?"); params.append(val)
    if not sets:
        return
    params.append(pres_id)
    with get_connection() as conn:
        conn.execute(f"UPDATE presentaciones SET {', '.join(sets)} WHERE id=?", params)


def eliminar_presentacion(pres_id):
    with get_connection() as conn:
        conn.execute("UPDATE presentaciones SET activo=0 WHERE id=?", (pres_id,))


def resolver_codigo(codigo: str) -> dict | None:
    """Resuelve un codigo escaneado a producto + cantidad + precio.

    Devuelve el producto con dos claves extra:
        _cantidad_sugerida : cuanto agregar al carrito (1, o el factor)
        _presentacion      : dict de la presentacion, o None

    Asi escanear la bolsa de 800 g agrega 800 g y no 1 g, y usa el precio
    de la bolsa en vez del precio por gramo.
    """
    prod = get_producto_por_codigo(codigo)
    if prod:
        prod["_cantidad_sugerida"] = 1.0
        prod["_presentacion"] = None
        return prod

    pres = get_presentacion_por_codigo(codigo)
    if not pres:
        return None

    prod = get_producto_completo(pres["producto_id"])
    if not prod:
        return None
    prod["_cantidad_sugerida"] = float(pres["factor"])
    prod["_presentacion"] = pres
    return prod


def describir_stock(producto_id: int) -> str:
    """Traduce el stock a como esta fisicamente en la gondola.

    El stock se guarda en la unidad chica (el caramelo), porque es la unica
    que permite vender de las dos formas sin descuadrar. Pero "1630 unidades"
    no responde la pregunta que uno se hace mirando el estante, que es
    cuantas bolsas cerradas quedan. Esto lo reparte:

        1630 unidades  ->  "9 bolsas 800 g cerradas + 136 sueltos"
    """
    stock = get_stock_producto(producto_id)
    presentaciones = get_presentaciones(producto_id)
    if not presentaciones:
        return f"{stock:g}"

    # Se usa la presentacion mas grande como "bulto" de referencia.
    pres = max(presentaciones, key=lambda p: p["factor"])
    factor = float(pres["factor"] or 0)
    if factor <= 0:
        return f"{stock:g}"

    enteros = int(stock // factor)
    sueltos = stock - enteros * factor
    partes = []
    if enteros:
        partes.append(f"{enteros} {pres['descripcion']}"
                      + (" cerradas" if enteros > 1 else " cerrada"))
    if sueltos > 1e-9:
        partes.append(f"{sueltos:g} sueltos")
    if not partes:
        return "sin stock"
    return " + ".join(partes) + f"  ({stock:g} en total)"


def get_proveedores_ultimo_por_producto() -> dict:
    """
    Proveedor del último ingreso real (tipo='ingreso', no ajustes) de
    cada producto — para mostrar en la sync a Sheets (hoja Interno).
    Un producto puede haberse repuesto con proveedores distintos a lo
    largo del tiempo; esto devuelve el más reciente, mismo criterio
    que costo_ultimo. Retorna {producto_id: nombre_proveedor}.
    """
    with get_connection() as conn:
        filas = conn.execute("""
            SELECT p.id as producto_id, pv.nombre as proveedor
            FROM productos p
            LEFT JOIN lotes l ON l.id = (
                SELECT l2.id FROM lotes l2
                WHERE l2.producto_id = p.id
                  AND l2.tipo = 'ingreso'
                  AND l2.proveedor_id IS NOT NULL
                ORDER BY l2.fecha_ingreso DESC, l2.id DESC
                LIMIT 1
            )
            LEFT JOIN proveedores pv ON l.proveedor_id = pv.id
        """).fetchall()
        return {f["producto_id"]: f["proveedor"] for f in filas if f["proveedor"]}


def get_productos(filtro="", categoria_id=None, solo_activos=True) -> list:
    q = """
        SELECT p.id, p.codigo, p.descripcion, c.nombre as categoria,
               p.precio_base, p.costo_ultimo, p.margen_pct, p.activo,
               p.ignorar_alerta, p.vendido_por_peso, p.imagen_url, p.marca,
               COALESCE(p.publicar_web, 1) as publicar_web,
               COALESCE(SUM(l.cantidad_restante), 0) as stock,
               ROUND((p.precio_base - p.costo_ultimo)
                     / NULLIF(p.costo_ultimo, 0) * 100, 1) as margen
        FROM productos p
        LEFT JOIN categorias c ON p.categoria_id = c.id
        LEFT JOIN lotes l ON l.producto_id = p.id
        WHERE 1=1
    """
    params = []
    if solo_activos:
        q += " AND p.activo = 1"
    if filtro:
        q += " AND (p.descripcion LIKE ? OR p.codigo LIKE ?)"
        params += [f"%{filtro}%", f"%{filtro}%"]
    if categoria_id:
        q += " AND p.categoria_id = ?"
        params.append(categoria_id)
    q += " GROUP BY p.id ORDER BY p.descripcion"
    with get_connection() as conn:
        return [dict(r) for r in conn.execute(q, params).fetchall()]


def crear_producto(codigo, descripcion, categoria_id, precio_base, costo,
                   vendido_por_peso=0, marca=None) -> int:
    """Crea el producto. Sin codigo escaneable, le genera uno propio.

    Un producto que nace sin codigo hay que buscarlo por nombre en cada
    venta hasta que alguien se acuerde de arreglarlo. Generarlo en el
    alta cierra el circuito de una: se crea, se imprime la etiqueta y ya
    se escanea.
    """
    precio_base = redondear_precio(precio_base)
    codigo = (codigo or "").strip()
    generar = not es_ean_valido(codigo)

    with get_connection() as conn:
        cur = conn.execute("""
            INSERT INTO productos
                (codigo, descripcion, categoria_id, precio_base, costo_ultimo,
                 vendido_por_peso, marca)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (codigo or f"_tmp_{descripcion[:20]}_{datetime.now():%H%M%S%f}",
              descripcion, categoria_id, precio_base, costo,
              int(bool(vendido_por_peso)), (marca or "").strip() or None))
        pid = cur.lastrowid
        conn.commit()

    if generar:
        # Se hace despues del INSERT porque el codigo se arma con el id,
        # y asi el mismo producto siempre tiene el mismo codigo.
        try:
            nuevo = asignar_codigo_interno(pid)
            logging.info(f"Producto {pid} sin codigo escaneable: se le "
                         f"genero {nuevo}")
        except Exception as e:
            logging.warning(f"No se pudo generar codigo para {pid}: {e}")
    return pid


def actualizar_producto(pid, descripcion, codigo, categoria_id,
                        precio_base, costo_ultimo=None, margen_pct=None,
                        vendido_por_peso=0, imagen_url=None, marca=None):
    # El redondeo es una regla del negocio, no una accion aparte: si
    # se aplica solo en algunas pantallas, el catalogo termina mitad
    # redondeado y mitad con decimales.
    precio_base = redondear_precio(precio_base)
    with get_connection() as conn:
        _anotar_cambio_precio(conn, pid, precio_base)
        conn.execute("""
            UPDATE productos
            SET descripcion=?, codigo=?, categoria_id=?, precio_base=?,
                costo_ultimo=COALESCE(?, costo_ultimo), margen_pct=?,
                vendido_por_peso=?, imagen_url=?, marca=?,
                modificado_en=datetime('now','localtime')
            WHERE id=?
        """, (descripcion, codigo, categoria_id, precio_base, costo_ultimo,
              margen_pct, int(bool(vendido_por_peso)), imagen_url,
              (marca or "").strip() or None, pid))
        conn.commit()


def actualizar_imagen_producto(pid, imagen_url):
    """Guarda solo la imagen del producto, sin tocar el resto de los
    campos — usado por la búsqueda automática de fotos (individual y
    masiva) para persistir apenas encuentra una, sin pasar por el
    formulario completo de edición."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE productos SET imagen_url=?, "
            "modificado_en=datetime('now','localtime') WHERE id=?",
            (imagen_url, pid))
        conn.commit()


def toggle_producto_activo(pid, activo: int):
    with get_connection() as conn:
        conn.execute("UPDATE productos SET activo=? WHERE id=?", (activo, pid))
        conn.commit()


def buscar_producto_id(texto: str) -> tuple[int | None, str | None]:
    """Busca por código exacto o nombre parcial. Retorna (id, descripcion)."""
    with get_connection() as conn:
        row = conn.execute("""
            SELECT id, descripcion FROM productos
            WHERE (codigo=? OR descripcion LIKE ?) AND activo=1
            LIMIT 1
        """, (texto, f"%{texto}%")).fetchone()
        return (row["id"], row["descripcion"]) if row else (None, None)


# ─────────────────────────────────────────────────────────────────────────────
# STOCK
# ─────────────────────────────────────────────────────────────────────────────

def get_stock_producto(producto_id: int) -> float:
    with get_connection() as conn:
        row = conn.execute("""
            SELECT COALESCE(SUM(cantidad_restante), 0) as stock
            FROM lotes WHERE producto_id = ?
        """, (producto_id,)).fetchone()
        return row["stock"]


def ajustar_stock(producto_id: int, cantidad_nueva: float, motivo: str,
                  autorizado_por: str, notas: str = "") -> float:
    """
    Corrige el stock total de un producto a `cantidad_nueva`, dejando
    registro en ajustes_stock (motivo, autorizado_por, historial).

    Si la cantidad_nueva es mayor al stock actual, crea un lote nuevo
    (tipo "ajuste") por la diferencia, usando el costo_ultimo del
    producto. Si es menor, descuenta de los lotes existentes por FIFO
    (mismo criterio que una venta). Retorna la diferencia aplicada
    (positiva si sumó, negativa si restó).
    """
    with get_connection() as conn:
        stock_actual = conn.execute("""
            SELECT COALESCE(SUM(cantidad_restante), 0) as stock
            FROM lotes WHERE producto_id = ?
        """, (producto_id,)).fetchone()["stock"]

        diferencia = round(cantidad_nueva - stock_actual, 3)
        lote_id = None

        if diferencia > 0:
            costo = conn.execute(
                "SELECT costo_ultimo FROM productos WHERE id = ?",
                (producto_id,)
            ).fetchone()["costo_ultimo"] or 0.0
            cur = conn.execute("""
                INSERT INTO lotes
                    (producto_id, proveedor_id, cantidad, cantidad_restante,
                     costo_unitario, notas, tipo, motivo_ajuste)
                VALUES (?, NULL, ?, ?, ?, ?, 'ajuste', ?)
            """, (producto_id, diferencia, diferencia, costo,
                  f"Ajuste de stock: {motivo}", motivo))
            lote_id = cur.lastrowid

        elif diferencia < 0:
            restante = -diferencia
            lotes = conn.execute("""
                SELECT id, cantidad_restante FROM lotes
                WHERE producto_id = ? AND cantidad_restante > 0
                ORDER BY fecha_ingreso ASC
            """, (producto_id,)).fetchall()
            for lote in lotes:
                if restante <= 0:
                    break
                usado = min(lote["cantidad_restante"], restante)
                conn.execute(
                    "UPDATE lotes SET cantidad_restante = cantidad_restante - ? WHERE id = ?",
                    (usado, lote["id"])
                )
                restante -= usado

        conn.execute("""
            INSERT INTO ajustes_stock
                (producto_id, lote_id, cantidad_anterior, cantidad_nueva,
                 diferencia, motivo, notas, autorizado_por)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (producto_id, lote_id, stock_actual, cantidad_nueva, diferencia,
              motivo, notas.strip() or None, autorizado_por))
        conn.commit()
        return diferencia


def abrir_pieza_entera(producto_entero_id: int, producto_fraccionado_id: int,
                       peso: float, autorizado_por: str = "",
                       notas: str = "") -> dict:
    """Pasa una horma del producto entero al fraccionado.

    Es la operacion que falta cuando se lleva entero y fraccionado como dos
    productos distintos: al abrir una horma para el mostrador, esos kilos
    dejan de estar disponibles como pieza entera. Sin esto, el entero sigue
    diciendo que hay 3 hormas cuando quedan 2, y el fraccionado vende en
    negativo desde el primer corte.

    Descuenta por FIFO del entero y crea un lote en el fraccionado con el
    COSTO REAL de los lotes consumidos, no con el costo_ultimo: si la ultima
    compra fue mas cara, imputarla a una horma vieja infla el costo del
    mostrador y ensucia el margen.
    """
    peso = round(float(peso), 3)
    if peso <= 0:
        raise ValueError("El peso tiene que ser mayor a cero")
    if producto_entero_id == producto_fraccionado_id:
        raise ValueError("El producto entero y el fraccionado no pueden ser el mismo")

    conn = get_connection()
    try:
        disponible = conn.execute("""
            SELECT COALESCE(SUM(cantidad_restante), 0) FROM lotes WHERE producto_id = ?
        """, (producto_entero_id,)).fetchone()[0]
        if peso > disponible + 1e-6:
            raise ValueError(
                f"Solo hay {disponible:.3f} kg como pieza entera, "
                f"no alcanzan para abrir {peso:.3f} kg")

        # FIFO sobre el entero, guardando el costo de cada lote consumido
        restante, costo_total = peso, 0.0
        for lote in conn.execute("""
                SELECT id, cantidad_restante, costo_unitario FROM lotes
                WHERE producto_id = ? AND cantidad_restante > 0
                ORDER BY fecha_ingreso ASC, id ASC
        """, (producto_entero_id,)).fetchall():
            if restante <= 1e-9:
                break
            usado = min(lote["cantidad_restante"], restante)
            conn.execute(
                "UPDATE lotes SET cantidad_restante = cantidad_restante - ? WHERE id = ?",
                (usado, lote["id"]))
            costo_total += usado * (lote["costo_unitario"] or 0)
            restante -= usado

        costo_kg = costo_total / peso if peso else 0.0

        cur = conn.execute("""
            INSERT INTO lotes (producto_id, proveedor_id, cantidad,
                               cantidad_restante, costo_unitario, tipo, notas)
            VALUES (?, NULL, ?, ?, ?, 'ingreso', ?)
        """, (producto_fraccionado_id, peso, peso, costo_kg,
              notas or f"Horma abierta: {peso:.3f} kg desde pieza entera"))
        lote_nuevo = cur.lastrowid

        conn.execute("""
            UPDATE productos SET costo_ultimo = ?,
                   modificado_en = datetime('now','localtime')
            WHERE id = ?
        """, (costo_kg, producto_fraccionado_id))

        # Queda asentado de los dos lados, para que el historial lo explique
        for pid, ant, nue, dif, txt in (
                (producto_entero_id, disponible, disponible - peso, -peso,
                 f"Horma abierta para fraccionar ({peso:.3f} kg)"),
                (producto_fraccionado_id, None, None, peso,
                 f"Ingreso por horma abierta ({peso:.3f} kg a ${costo_kg:,.2f}/kg)")):
            if ant is None:
                ant = conn.execute("""
                    SELECT COALESCE(SUM(cantidad_restante), 0) FROM lotes
                    WHERE producto_id = ? AND id != ?
                """, (pid, lote_nuevo)).fetchone()[0]
                nue = ant + peso
            conn.execute("""
                INSERT INTO ajustes_stock
                    (producto_id, lote_id, cantidad_anterior, cantidad_nueva,
                     diferencia, motivo, notas, autorizado_por)
                VALUES (?,?,?,?,?,?,?,?)
            """, (pid, lote_nuevo if dif > 0 else None, ant, nue, dif,
                  "Fraccionamiento", txt,
                  # NOT NULL en la tabla: sin autorizacion explicita queda
                  # constancia de que lo hizo el sistema, no un usuario.
                  autorizado_por or "sistema"))

        conn.commit()
        return {"peso": peso, "costo_kg": costo_kg,
                "costo_total": costo_total, "lote_id": lote_nuevo,
                "restante_entero": disponible - peso}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_historial_ajustes(producto_id: int = None, limit: int = 100) -> list:
    with get_connection() as conn:
        if producto_id:
            filas = conn.execute("""
                SELECT a.*, p.descripcion, p.codigo
                FROM ajustes_stock a
                JOIN productos p ON p.id = a.producto_id
                WHERE a.producto_id = ?
                ORDER BY a.fecha DESC LIMIT ?
            """, (producto_id, limit)).fetchall()
        else:
            filas = conn.execute("""
                SELECT a.*, p.descripcion, p.codigo
                FROM ajustes_stock a
                JOIN productos p ON p.id = a.producto_id
                ORDER BY a.fecha DESC LIMIT ?
            """, (limit,)).fetchall()
        return [dict(r) for r in filas]


def get_reposicion(dias_historial=30, dias_cobertura=14,
                   solo_faltantes=True) -> list:
    """Que comprar, calculado por velocidad de venta y no por un umbral fijo.

    "Stock bajo" con un numero fijo para todo el catalogo no sirve: 5
    unidades de algo que se vende 20 por dia es una urgencia, y 5 de algo
    que sale uno por mes es sobrestock. Lo que importa es cuantos DIAS
    dura lo que hay.

    dias_historial: sobre cuantos dias se mide la velocidad de venta.
    dias_cobertura: para cuantos dias se quiere tener stock.
    """
    from datetime import timedelta
    hasta = datetime.now()
    desde = (hasta - timedelta(days=dias_historial)).strftime("%Y-%m-%d")

    with get_connection() as conn:
        filas = [dict(r) for r in conn.execute("""
            SELECT p.id, p.codigo, p.descripcion, p.marca, p.precio_base,
                   p.costo_ultimo, p.vendido_por_peso,
                   c.nombre as categoria,
                   COALESCE((SELECT SUM(l.cantidad_restante) FROM lotes l
                              WHERE l.producto_id = p.id), 0) as stock,
                   COALESCE((SELECT SUM(dv.cantidad)
                               FROM detalle_ventas dv
                               JOIN ventas v ON v.id = dv.venta_id
                              WHERE dv.producto_id = p.id
                                AND v.anulada = 0
                                AND date(v.fecha) >= date(?)), 0) as vendido,
                   (SELECT pv.nombre FROM lotes l
                      LEFT JOIN proveedores pv ON pv.id = l.proveedor_id
                     WHERE l.producto_id = p.id AND pv.nombre IS NOT NULL
                  ORDER BY l.fecha_ingreso DESC LIMIT 1) as proveedor
            FROM productos p
            LEFT JOIN categorias c ON c.id = p.categoria_id
            WHERE COALESCE(p.activo, 1) = 1
              AND COALESCE(p.ignorar_alerta, 0) = 0
        """, (desde,)).fetchall()]

    salida = []
    for f in filas:
        por_dia = (f["vendido"] or 0) / dias_historial
        stock = f["stock"] or 0
        if por_dia > 0:
            dias = stock / por_dia
        else:
            # Sin ventas en el periodo no hay velocidad que medir. Se
            # marca aparte en vez de inventar un numero.
            dias = None
        sugerido = max(0.0, por_dia * dias_cobertura - stock) if por_dia > 0 else 0.0
        if f["vendido_por_peso"]:
            sugerido = round(sugerido, 3)
        else:
            sugerido = float(int(sugerido + 0.999))   # unidades enteras

        f["por_dia"] = por_dia
        f["dias_stock"] = dias
        f["sugerido"] = sugerido
        f["costo_reposicion"] = sugerido * (f["costo_ultimo"] or 0)
        # Quedarse sin stock es urgente aunque no haya ventas recientes:
        # justamente puede estar en cero PORQUE no hay que vender. Antes
        # esos productos caian en "sin ventas" y desaparecian del aviso.
        if stock <= 0:
            f["urgencia"] = "sin stock"
        elif dias is None:
            f["urgencia"] = "sin ventas"
        elif dias <= 3:
            f["urgencia"] = "urgente"
        elif dias <= dias_cobertura:
            f["urgencia"] = "reponer"
        else:
            f["urgencia"] = "ok"

        if solo_faltantes and f["urgencia"] in ("ok", "sin ventas"):
            continue
        salida.append(f)

    orden = {"sin stock": 0, "urgente": 1, "reponer": 2, "ok": 3, "sin ventas": 4}
    salida.sort(key=lambda x: (orden[x["urgencia"]],
                               x["dias_stock"] if x["dias_stock"] is not None else 999))
    return salida


def get_stock_muerto(dias=90, minimo_valor=0.0) -> list:
    """Plata parada: lo que tiene stock y no rota.

    Es el reverso de get_reposicion(). Alla se ve que falta; aca, que
    sobra. Un producto con 30 unidades y cero ventas en 90 dias es
    capital dormido en gondola, y no aparece en ninguna alerta porque
    justamente NO se esta agotando.

    Devuelve cada producto con:
        dias_sin_vender   dias desde la ultima venta (None = nunca se vendio)
        capital           stock x costo, o sea la plata inmovilizada
        vendido_periodo   unidades vendidas en la ventana
    """
    from datetime import timedelta
    hoy = datetime.now()
    desde = (hoy - timedelta(days=dias)).strftime("%Y-%m-%d")

    with get_connection() as conn:
        filas = [dict(r) for r in conn.execute("""
            SELECT p.id, p.codigo, p.descripcion, p.marca, p.precio_base,
                   p.costo_ultimo, c.nombre as categoria,
                   COALESCE((SELECT SUM(l.cantidad_restante) FROM lotes l
                              WHERE l.producto_id = p.id), 0) as stock,
                   COALESCE((SELECT SUM(dv.cantidad) FROM detalle_ventas dv
                               JOIN ventas v ON v.id = dv.venta_id
                              WHERE dv.producto_id = p.id AND v.anulada = 0
                                AND date(v.fecha) >= date(?)), 0) as vendido,
                   (SELECT MAX(v.fecha) FROM detalle_ventas dv
                      JOIN ventas v ON v.id = dv.venta_id
                     WHERE dv.producto_id = p.id AND v.anulada = 0) as ultima_venta,
                   (SELECT MIN(l.fecha_ingreso) FROM lotes l
                     WHERE l.producto_id = p.id AND l.cantidad_restante > 0)
                       as ingreso_mas_viejo
            FROM productos p
            LEFT JOIN categorias c ON c.id = p.categoria_id
            WHERE COALESCE(p.activo, 1) = 1
        """, (desde,)).fetchall()]

    salida = []
    for f in filas:
        if (f["stock"] or 0) <= 0 or (f["vendido"] or 0) > 0:
            continue          # sin stock no hay plata parada; si vendio, rota

        if f["ultima_venta"]:
            try:
                ult = datetime.strptime(f["ultima_venta"][:10], "%Y-%m-%d")
                f["dias_sin_vender"] = (hoy - ult).days
            except ValueError:
                f["dias_sin_vender"] = None
        else:
            f["dias_sin_vender"] = None      # nunca se vendio

        f["capital"] = (f["stock"] or 0) * (f["costo_ultimo"] or 0)
        f["vendido_periodo"] = f["vendido"] or 0
        if f["capital"] < minimo_valor:
            continue
        salida.append(f)

    # Primero donde hay mas plata atrapada: es donde conviene actuar
    salida.sort(key=lambda x: -x["capital"])
    return salida


def valor_inventario() -> dict:
    """Cuanta plata hay en gondola, a costo y a precio de venta."""
    with get_connection() as conn:
        r = conn.execute("""
            SELECT COUNT(DISTINCT p.id) as productos,
                   COALESCE(SUM(l.cantidad_restante * l.costo_unitario), 0) as costo,
                   COALESCE(SUM(l.cantidad_restante * p.precio_base), 0) as venta
            FROM lotes l
            JOIN productos p ON p.id = l.producto_id
            WHERE l.cantidad_restante > 0 AND COALESCE(p.activo, 1) = 1
        """).fetchone()
    return {"productos": r["productos"], "costo": r["costo"] or 0.0,
            "venta": r["venta"] or 0.0}


def get_informe_stock(solo_criticos=False, umbral=None) -> list:
    """
    Devuelve el stock de productos activos, ordenado de MENOR a MAYOR
    stock (los más urgentes primero). Si solo_criticos=True, filtra
    solo los que están por debajo del umbral configurado.
    """
    if umbral is None:
        try:
            from config import cfg
            umbral = cfg().get("stock_alerta_umbral", 5)
        except Exception:
            umbral = 5

    q = """
        SELECT p.id, p.codigo, p.descripcion, c.nombre as categoria,
               p.vendido_por_peso,
               COALESCE(SUM(l.cantidad_restante), 0) as stock
        FROM productos p
        LEFT JOIN categorias c ON p.categoria_id = c.id
        LEFT JOIN lotes l ON l.producto_id = p.id
        WHERE p.activo = 1
    """
    if solo_criticos:
        q += " AND p.ignorar_alerta = 0 GROUP BY p.id HAVING stock < ?"
        params = (umbral,)
    else:
        q += " GROUP BY p.id"
        params = ()
    q += " ORDER BY stock ASC, p.descripcion ASC"

    with get_connection() as conn:
        filas = [dict(r) for r in conn.execute(q, params).fetchall()]
    for f in filas:
        f["critico"] = f["stock"] < umbral
    return filas


def get_lotes_recientes(limit=50) -> list:
    with get_connection() as conn:
        return [dict(r) for r in conn.execute("""
            SELECT l.id, p.descripcion, p.codigo,
                   l.cantidad, l.cantidad_restante,
                   l.costo_unitario, l.fecha_ingreso,
                   l.fecha_vencimiento, pv.nombre as proveedor,
                   l.tipo, l.motivo_ajuste
            FROM lotes l
            JOIN productos p ON l.producto_id = p.id
            LEFT JOIN proveedores pv ON l.proveedor_id = pv.id
            ORDER BY l.fecha_ingreso DESC LIMIT ?
        """, (limit,)).fetchall()]


def buscar_lotes(texto="", desde=None, hasta=None, proveedor_id=None,
                 tipo=None, solo_con_stock=False, limit=1000) -> list:
    """Historico completo de ingresos, con filtros.

    get_lotes_recientes() corta en los ultimos 50 y sin filtros: sirve para
    la vista del dia, pero no para buscar cuando entro algo hace tres meses
    ni para reconstruir que se le compro a un proveedor.

    texto matchea contra descripcion, codigo, proveedor y notas del lote.
    """
    cond, params = ["1=1"], []

    t = (texto or "").strip()
    if t:
        like = f"%{t}%"
        cond.append("(p.descripcion LIKE ? OR p.codigo LIKE ? OR "
                    "pv.nombre LIKE ? OR l.notas LIKE ?)")
        params += [like, like, like, like]
    if desde:
        cond.append("date(l.fecha_ingreso) >= date(?)"); params.append(desde)
    if hasta:
        cond.append("date(l.fecha_ingreso) <= date(?)"); params.append(hasta)
    if proveedor_id:
        cond.append("l.proveedor_id = ?"); params.append(proveedor_id)
    if tipo:
        cond.append("COALESCE(l.tipo,'ingreso') = ?"); params.append(tipo)
    if solo_con_stock:
        cond.append("l.cantidad_restante > 0")
    params.append(limit)

    with get_connection() as conn:
        return [dict(r) for r in conn.execute(f"""
            SELECT l.id, l.producto_id, p.descripcion, p.codigo,
                   p.precio_base, p.costo_ultimo,
                   l.cantidad, l.cantidad_restante, l.costo_unitario,
                   l.cantidad * l.costo_unitario as costo_total,
                   l.fecha_ingreso, l.fecha_vencimiento, l.notas,
                   pv.nombre as proveedor, l.tipo, l.motivo_ajuste
            FROM lotes l
            JOIN productos p ON l.producto_id = p.id
            LEFT JOIN proveedores pv ON l.proveedor_id = pv.id
            WHERE {" AND ".join(cond)}
            ORDER BY l.fecha_ingreso DESC, l.id DESC
            LIMIT ?
        """, params).fetchall()]


def resumen_lotes(lotes: list) -> dict:
    """Totales del listado que se esta viendo, para el pie de la tabla."""
    ingresos = [l for l in lotes if (l.get("tipo") or "ingreso") == "ingreso"]
    return {
        "cantidad": len(lotes),
        "unidades": sum(l["cantidad"] or 0 for l in ingresos),
        "invertido": sum((l["cantidad"] or 0) * (l["costo_unitario"] or 0)
                         for l in ingresos),
        "en_stock": sum((l["cantidad_restante"] or 0) * (l["costo_unitario"] or 0)
                        for l in lotes),
    }


def get_stock_critico(umbral=None) -> list:
    if umbral is None:
        try:
            from config import cfg
            umbral = cfg().get("stock_alerta_umbral", 5)
        except Exception:
            umbral = 5
    with get_connection() as conn:
        return [dict(r) for r in conn.execute("""
            SELECT p.id, p.descripcion, p.codigo,
                   COALESCE(SUM(l.cantidad_restante), 0) as stock,
                   p.precio_base, p.ignorar_alerta
            FROM productos p
            LEFT JOIN lotes l ON l.producto_id = p.id
            WHERE p.activo = 1 AND p.ignorar_alerta = 0
            GROUP BY p.id
            HAVING stock < ?
            ORDER BY stock ASC
        """, (umbral,)).fetchall()]


def get_resumen_stock_por_categoria() -> list:
    """
    Para el Dashboard: cantidad de productos activos, stock total (en
    unidades) y valor de ese stock (a costo y a precio de venta),
    agrupado por categoría. Incluye "Sin categoría" si corresponde.
    """
    with get_connection() as conn:
        return [dict(r) for r in conn.execute("""
            SELECT
                COALESCE(c.nombre, 'Sin categoría') as categoria,
                COUNT(DISTINCT p.id) as cant_productos,
                COALESCE(SUM(st.stock), 0) as stock_total,
                COALESCE(SUM(st.stock * p.costo_ultimo), 0) as valor_costo,
                COALESCE(SUM(st.stock * p.precio_base), 0) as valor_venta
            FROM productos p
            LEFT JOIN categorias c ON p.categoria_id = c.id
            LEFT JOIN (
                SELECT producto_id, SUM(cantidad_restante) as stock
                FROM lotes GROUP BY producto_id
            ) st ON st.producto_id = p.id
            WHERE p.activo = 1
            GROUP BY c.id, c.nombre
            ORDER BY categoria
        """).fetchall()]


def toggle_ignorar_alerta(pid: int, valor: int):
    """Activa o desactiva la alerta de stock bajo para un producto."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE productos SET ignorar_alerta=? WHERE id=?", (valor, pid))
        conn.commit()


def redondear_precio(precio: float, paso: int = None, modo: str = None) -> float:
    """Redondea al multiplo configurado.

    modo:
      "cercano" — al multiplo mas proximo. Con paso 100: 1.440 baja a 1.400
                  y 1.460 sube a 1.500. Justo la mitad sube.
      "arriba"  — siempre al siguiente multiplo. Nunca se pierde margen,
                  pero puede empujar bastante los precios bajos.
      "abajo"   — siempre al multiplo anterior. Deja precios prolijos y
                  algo mas baratos, a costa de resignar margen.

    paso=0 (o la config en 0) devuelve el precio tal cual.
    """
    import math
    if paso is None or modo is None:
        try:
            from config import cfg
            c = cfg()
            if paso is None:
                paso = c.get("redondeo_precios", 0)
            if modo is None:
                modo = c.get("redondeo_modo", "cercano")
        except Exception:
            paso = paso if paso is not None else 0
            modo = modo or "cercano"

    paso = int(paso or 0)
    if paso <= 0:
        return round(float(precio), 2)

    valor = float(precio)
    if modo == "arriba":
        return float(math.ceil(valor / paso) * paso)
    if modo == "abajo":
        return float(math.floor(valor / paso) * paso)

    # cercano: la mitad exacta sube, que es lo habitual en precios
    return float(math.floor(valor / paso + 0.5) * paso)


def redondear_todos_los_precios(paso: int = None, solo_activos: bool = True,
                                modo: str = None) -> dict:
    """Aplica el redondeo a todo el catalogo. Devuelve el detalle de cambios."""
    cond = "WHERE COALESCE(activo,1)=1" if solo_activos else ""
    cambios = []
    with get_connection() as conn:
        filas = conn.execute(
            f"SELECT id, descripcion, precio_base FROM productos {cond}").fetchall()
        for f in filas:
            viejo = float(f["precio_base"] or 0)
            if viejo <= 0:
                continue
            nuevo = redondear_precio(viejo, paso, modo)
            if abs(nuevo - viejo) < 0.005:
                continue
            conn.execute("""UPDATE productos SET precio_base=?,
                            modificado_en=datetime('now','localtime') WHERE id=?""",
                         (nuevo, f["id"]))
            cambios.append({"id": f["id"], "descripcion": f["descripcion"],
                            "anterior": viejo, "nuevo": nuevo,
                            "diferencia": nuevo - viejo})
        conn.commit()
    return {"cambiados": len(cambios), "revisados": len(filas), "detalle": cambios}


def calcular_precio_por_margen(costo: float, producto_id: int) -> float:
    """
    Calcula el precio de venta usando el margen del producto.
    Si el producto no tiene margen propio, usa el de su categoría.
    """
    with get_connection() as conn:
        row = conn.execute("""
            SELECT p.margen_pct, c.margen_pct as cat_margen
            FROM productos p
            LEFT JOIN categorias c ON p.categoria_id = c.id
            WHERE p.id = ?
        """, (producto_id,)).fetchone()
    if not row:
        return redondear_precio(costo * 1.30)
    margen = row["margen_pct"] if row["margen_pct"] is not None else (row["cat_margen"] or 30.0)
    return redondear_precio(costo * (1 + margen / 100))


def evaluar_cambio_costo(producto_id: int, costo_nuevo: float) -> dict:
    """
    Compara el costo nuevo contra el actual del producto SIN tocar la
    base — para que la UI pueda decidir/preguntar antes de guardar el
    lote. Devuelve:
      costo_anterior, costo_nuevo, precio_actual, precio_sugerido,
      direccion ("subio" / "bajo" / "igual")
    """
    with get_connection() as conn:
        prod = conn.execute(
            "SELECT costo_ultimo, precio_base FROM productos WHERE id=?",
            (producto_id,)
        ).fetchone()
    costo_anterior = prod["costo_ultimo"] if prod else 0.0
    precio_actual  = prod["precio_base"] if prod else 0.0
    precio_sugerido = calcular_precio_por_margen(costo_nuevo, producto_id)
    if costo_nuevo > costo_anterior:
        direccion = "subio"
    elif costo_nuevo < costo_anterior:
        direccion = "bajo"
    else:
        direccion = "igual"
    # Stock que queda del costo VIEJO. Es el dato que decide: con FIFO
    # ese stock se vende primero, asi que bajar el precio ahora significa
    # venderlo con el margen (o la perdida) del costo nuevo.
    with get_connection() as conn:
        stock_viejo = conn.execute(
            "SELECT COALESCE(SUM(cantidad_restante), 0) FROM lotes "
            "WHERE producto_id = ? AND cantidad_restante > 0",
            (producto_id,)).fetchone()[0] or 0.0

    def _margen(precio, costo):
        return ((precio - costo) / costo * 100) if costo else 0.0

    return {
        "costo_anterior": costo_anterior, "costo_nuevo": costo_nuevo,
        "precio_actual": precio_actual, "precio_sugerido": precio_sugerido,
        "direccion": direccion,
        "stock_viejo": stock_viejo,
        "margen_si_no_toca": _margen(precio_actual, costo_nuevo),
        "margen_sugerido": _margen(precio_sugerido, costo_nuevo),
        # Vender el stock viejo al precio nuevo puede dar perdida
        "bajo_costo_viejo": (precio_sugerido < costo_anterior
                             and stock_viejo > 0),
        "perdida_por_unidad": max(0.0, costo_anterior - precio_sugerido),
    }


def registrar_lote(producto_id, proveedor_id, cantidad,
                   costo, vencimiento, notas,
                   nuevo_precio_venta: float | None = None) -> tuple[int, float | None]:
    """
    Registra un lote. nuevo_precio_venta lo decide quien llama (típicamente
    tras mostrarle a el usuario evaluar_cambio_costo() y, si el costo
    bajó, preguntarle si quiere mantener el precio de venta o actualizarlo).
    Si viene con un valor, el precio de venta se actualiza a eso; si es
    None, el precio de venta queda tal cual estaba.
    Retorna (lote_id, precio_aplicado) — precio_aplicado es None si no
    se tocó el precio.
    """
    with get_connection() as conn:
        cur = conn.execute("""
            INSERT INTO lotes
                (producto_id, proveedor_id, cantidad, cantidad_restante,
                 costo_unitario, fecha_vencimiento, notas, tipo)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'ingreso')
        """, (producto_id, proveedor_id, cantidad, cantidad,
              costo, vencimiento or None, notas or None))

        if nuevo_precio_venta is not None:
            conn.execute("""
                UPDATE productos
                SET costo_ultimo=?, precio_base=?,
                    modificado_en=datetime('now','localtime')
                WHERE id=?
            """, (costo, nuevo_precio_venta, producto_id))
        else:
            conn.execute("""
                UPDATE productos
                SET costo_ultimo=?, modificado_en=datetime('now','localtime')
                WHERE id=?
            """, (costo, producto_id))

        conn.commit()
        return cur.lastrowid, nuevo_precio_venta


# Cuantos dias hacia atras se siguen reportando los lotes ya vencidos.
VENCIDOS_HACIA_ATRAS = 60


def get_vencimientos_proximos(dias=None) -> list:
    """Lotes por vencer, respetando los dias de aviso de CADA producto.

    El anticipo que necesita cada cosa es distinto: un yogur hay que
    liquidarlo con dos dias, una lata se puede mirar con treinta. Por eso
    productos.alerta_dias_vto pisa el general de Config cuando esta cargado.

    Si se pasa `dias` explicito, ese valor manda para todos (lo usa el
    informe cuando uno quiere mirar una ventana puntual).
    """
    from datetime import timedelta
    general = dias
    if general is None:
        try:
            from config import cfg
            general = cfg().get("stock_alerta_dias_vto", 7)
        except Exception:
            general = 7

    # Se mira tambien HACIA ATRAS: lo ya vencido es lo mas urgente que hay
    # (no se puede vender y ocupa gondola), y filtrando desde hoy quedaba
    # invisible justo lo que habia que sacar primero.
    desde = (datetime.now() - timedelta(days=VENCIDOS_HACIA_ATRAS)).strftime("%Y-%m-%d")
    # Se consulta con la ventana mas ancha posible y se filtra despues por
    # producto: es una sola query en vez de una por producto.
    with get_connection() as conn:
        tope = conn.execute(
            "SELECT COALESCE(MAX(alerta_dias_vto), 0) FROM productos").fetchone()[0]
        ventana = max(int(general), int(tope or 0))
        hasta = (datetime.now() + timedelta(days=ventana)).strftime("%Y-%m-%d")
        filas = [dict(r) for r in conn.execute("""
            SELECT p.id as producto_id, p.descripcion, p.codigo,
                   p.alerta_dias_vto, p.precio_base, p.vendido_por_peso,
                   l.fecha_vencimiento,
                   SUM(l.cantidad_restante) as stock
            FROM lotes l
            JOIN productos p ON l.producto_id = p.id
            WHERE l.fecha_vencimiento BETWEEN ? AND ?
              AND l.cantidad_restante > 0
              AND COALESCE(p.activo, 1) = 1
            GROUP BY p.id, l.fecha_vencimiento
            ORDER BY l.fecha_vencimiento
        """, (desde, hasta)).fetchall()]

    hoy_d = datetime.now().date()
    salida = []
    for f in filas:
        umbral = f["alerta_dias_vto"] if dias is None and f["alerta_dias_vto"] else general
        try:
            vence = datetime.strptime(f["fecha_vencimiento"], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue
        restan = (vence - hoy_d).days
        if restan <= umbral:
            f["dias_restantes"] = restan
            f["umbral_usado"] = umbral
            f["valor_en_riesgo"] = (f["stock"] or 0) * (f["precio_base"] or 0)
            salida.append(f)
    return sorted(salida, key=lambda x: x["dias_restantes"])


def set_alerta_vto_producto(producto_id: int, dias):
    """dias=None vuelve al valor general de Config."""
    with get_connection() as conn:
        conn.execute("UPDATE productos SET alerta_dias_vto=? WHERE id=?",
                     (int(dias) if dias not in (None, "") else None, producto_id))


# ─────────────────────────────────────────────────────────────────────────────
# CATEGORÍAS
# ─────────────────────────────────────────────────────────────────────────────

def get_categorias() -> list:
    with get_connection() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT id, nombre, margen_pct FROM categorias ORDER BY nombre"
        ).fetchall()]


def guardar_categoria(cid, nombre, margen):
    with get_connection() as conn:
        if cid:
            conn.execute(
                "UPDATE categorias SET nombre=?, margen_pct=? WHERE id=?",
                (nombre, margen, cid))
        else:
            conn.execute(
                "INSERT INTO categorias (nombre, margen_pct) VALUES (?,?)",
                (nombre, margen))
        conn.commit()


def eliminar_categoria(cid):
    with get_connection() as conn:
        conn.execute(
            "UPDATE productos SET categoria_id=NULL WHERE categoria_id=?", (cid,))
        conn.execute("DELETE FROM categorias WHERE id=?", (cid,))
        conn.commit()


# ─────────────────────────────────────────────────────────────────────────────
# PROVEEDORES
# ─────────────────────────────────────────────────────────────────────────────

def get_proveedores() -> list:
    with get_connection() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT id, nombre FROM proveedores WHERE activo=1 ORDER BY nombre"
        ).fetchall()]


def crear_proveedor(nombre: str) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO proveedores (nombre) VALUES (?)", (nombre,))
        conn.commit()
        return cur.lastrowid


def resumen_cobranzas(desde, hasta) -> dict:
    """Lo vendido, lo cobrado por metodo y lo que queda pendiente.

    Son tres preguntas distintas que se confunden todo el tiempo:
      - cuanto VENDI (facturado, entre o no la plata)
      - cuanto ENTRO por cada medio (incluye pagos de deudas viejas)
      - cuanto me DEBEN todavia
    """
    with get_connection() as conn:
        v = dict(conn.execute("""
            SELECT COUNT(*)                          as tickets,
                   COALESCE(SUM(total), 0)           as facturado,
                   COALESCE(SUM(monto_efectivo), 0)  as efectivo,
                   COALESCE(SUM(monto_tarjeta), 0)   as tarjeta,
                   COALESCE(SUM(monto_qr), 0)        as qr,
                   COALESCE(SUM(monto_cta_cte), 0)   as fiado
            FROM ventas
            WHERE date(fecha) BETWEEN ? AND ? AND anulada = 0
        """, (desde, hasta)).fetchone())

        # Costo de lo vendido, para la ganancia del periodo
        v["costo"] = conn.execute("""
            SELECT COALESCE(SUM(dvl.cantidad * l.costo_unitario), 0)
            FROM detalle_ventas_lotes dvl
            JOIN lotes l ON l.id = dvl.lote_id
            JOIN detalle_ventas dv ON dv.id = dvl.detalle_venta_id
            JOIN ventas ve ON ve.id = dv.venta_id
            WHERE date(ve.fecha) BETWEEN ? AND ? AND ve.anulada = 0
        """, (desde, hasta)).fetchone()[0] or 0

        # Pagos de cuenta corriente recibidos en el periodo: plata que
        # entra hoy por ventas de antes.
        v["cobros_cta_cte"] = conn.execute("""
            SELECT COALESCE(SUM(ABS(monto)), 0)
            FROM movimientos_cuenta
            WHERE tipo = 'pago' AND date(fecha) BETWEEN ? AND ?
        """, (desde, hasta)).fetchone()[0] or 0

        v["deuda_total"] = conn.execute(
            "SELECT COALESCE(SUM(saldo_actual), 0) FROM cuentas_corrientes"
        ).fetchone()[0] or 0

        v["clientes_con_deuda"] = conn.execute(
            "SELECT COUNT(*) FROM cuentas_corrientes WHERE saldo_actual > 0.01"
        ).fetchone()[0] or 0

        # Devoluciones pagadas en efectivo: salieron del cajon
        v["devoluciones"] = conn.execute("""
            SELECT COALESCE(SUM(total), 0) FROM devoluciones
            WHERE date(fecha) BETWEEN ? AND ?
        """, (desde, hasta)).fetchone()[0] or 0

    v["ganancia"] = v["facturado"] - v["costo"]
    # Control: las partes tienen que sumar el total facturado. Si no, hay
    # ventas sin desglose y los numeros por metodo estan incompletos.
    v["suma_medios"] = v["efectivo"] + v["tarjeta"] + v["qr"] + v["fiado"]
    v["descuadre"] = v["facturado"] - v["suma_medios"]
    # Lo que realmente entro: las ventas al contado + los pagos de deuda
    v["cobrado"] = (v["efectivo"] + v["tarjeta"] + v["qr"]
                    + v["cobros_cta_cte"])
    v["pct_cobrado"] = (v["cobrado"] / v["facturado"] * 100
                        if v["facturado"] else 0.0)
    return v


def ganancia_cobrada(desde, hasta) -> dict:
    """Separa lo facturado de lo efectivamente COBRADO.

    La rentabilidad muestra lo vendido, sin importar si entro la plata.
    Una venta fiada suma ganancia el dia que se hace, pero el dinero
    llega despues — o no llega.
    """
    with get_connection() as conn:
        v = conn.execute("""
            SELECT COALESCE(SUM(total), 0)          as facturado,
                   COALESCE(SUM(monto_efectivo), 0) as efectivo,
                   COALESCE(SUM(monto_tarjeta), 0)  as tarjeta,
                   COALESCE(SUM(monto_qr), 0)       as qr,
                   COALESCE(SUM(monto_cta_cte), 0)  as fiado
            FROM ventas
            WHERE date(fecha) BETWEEN ? AND ? AND anulada = 0
        """, (desde, hasta)).fetchone()
        # Pagos de deuda vieja que entraron en el periodo: es plata que
        # cobras hoy por ventas de antes.
        cobros = conn.execute("""
            SELECT COALESCE(SUM(ABS(monto)), 0)
            FROM movimientos_cuenta
            WHERE tipo = 'pago' AND date(fecha) BETWEEN ? AND ?
        """, (desde, hasta)).fetchone()[0] or 0
        deuda = conn.execute(
            "SELECT COALESCE(SUM(saldo_actual), 0) FROM cuentas_corrientes"
        ).fetchone()[0] or 0

    v = dict(v)
    v["cobros_de_deuda_vieja"] = cobros
    # Lo que realmente entro: las ventas cobradas al contado + los pagos
    # de deuda anterior. Lo fiado de este periodo NO cuenta.
    v["cobrado"] = v["efectivo"] + v["tarjeta"] + v["qr"] + cobros
    v["por_cobrar_total"] = deuda
    return v


def lotes_de_producto_vendidos(producto_id: int, desde=None, hasta=None) -> list:
    """De que lotes salio lo que se vendio de un producto.

    Sirve cuando el informe muestra un costo que uno ya corrigio: por
    FIFO la venta pudo salir de un lote VIEJO, y corregir el lote nuevo
    no cambia nada del historico.
    """
    cond, params = ["dv.producto_id = ?"], [producto_id]
    if desde:
        cond.append("date(v.fecha) >= date(?)"); params.append(desde)
    if hasta:
        cond.append("date(v.fecha) <= date(?)"); params.append(hasta)
    with get_connection() as conn:
        return [dict(r) for r in conn.execute(f"""
            SELECT l.id as lote_id, l.costo_unitario, l.fecha_ingreso,
                   SUM(dvl.cantidad) as unidades,
                   SUM(dvl.cantidad * l.costo_unitario) as costo_total,
                   COUNT(DISTINCT v.id) as ventas
            FROM detalle_ventas_lotes dvl
            JOIN detalle_ventas dv ON dv.id = dvl.detalle_venta_id
            JOIN ventas v ON v.id = dv.venta_id
            JOIN lotes l ON l.id = dvl.lote_id
            WHERE {" AND ".join(cond)} AND v.anulada = 0
            GROUP BY l.id
            ORDER BY l.fecha_ingreso
        """, params).fetchall()]


def lotes_descuadrados(solo_con_stock=False) -> list:
    """Lotes cuyo costo no coincide con el costo actual del producto.

    El costo vive en dos lugares: productos.costo_ultimo (lo que muestra
    el catalogo) y lotes.costo_unitario (de donde sale la rentabilidad).
    Corregir el producto desde Editar NO toca los lotes ya cargados, asi
    que quedan diciendo cosas distintas y la ganancia informada es la del
    lote, no la que uno ve en el catalogo.
    """
    cond = "AND l.cantidad_restante > 0" if solo_con_stock else ""
    with get_connection() as conn:
        return [dict(r) for r in conn.execute(f"""
            SELECT l.id as lote_id, l.producto_id, p.descripcion, p.codigo,
                   p.precio_base, p.costo_ultimo,
                   l.costo_unitario, l.cantidad, l.cantidad_restante,
                   l.fecha_ingreso,
                   COALESCE((SELECT SUM(dvl.cantidad)
                               FROM detalle_ventas_lotes dvl
                              WHERE dvl.lote_id = l.id), 0) as vendido
            FROM lotes l
            JOIN productos p ON p.id = l.producto_id
            WHERE COALESCE(p.activo, 1) = 1
              AND COALESCE(p.costo_ultimo, 0) > 0
              AND COALESCE(l.costo_unitario, 0) > 0
              AND ABS(l.costo_unitario - p.costo_ultimo) > 0.01
              {cond}
            ORDER BY ABS(l.costo_unitario - p.costo_ultimo) DESC
        """).fetchall()]


def corregir_costo_lote(lote_id: int, costo_nuevo: float,
                        responsable: str = "", nota: str = "") -> dict:
    """Corrige el costo de un lote ya cargado.

    Poner el precio de venta en el campo "costo unitario" al ingresar
    stock es un error facil de cometer y dificil de ver: el producto
    sigue mostrando su costo_ultimo correcto, pero la rentabilidad de
    todo lo vendido de ese lote sale en cero.

    Corregir el lote recalcula la ganancia de las ventas YA hechas,
    porque el informe lee el costo del lote, no una copia.
    """
    costo_nuevo = float(costo_nuevo)
    if costo_nuevo < 0:
        raise ValueError("El costo no puede ser negativo.")

    with get_connection() as conn:
        lote = conn.execute("""
            SELECT l.*, p.descripcion, p.precio_base
            FROM lotes l JOIN productos p ON p.id = l.producto_id
            WHERE l.id = ?
        """, (lote_id,)).fetchone()
        if not lote:
            raise ValueError("El lote no existe.")
        lote = dict(lote)

        # Cuanto de ese lote ya se vendio: es la ganancia que se corrige
        vendido = conn.execute("""
            SELECT COALESCE(SUM(cantidad), 0) FROM detalle_ventas_lotes
            WHERE lote_id = ?
        """, (lote_id,)).fetchone()[0] or 0

        conn.execute("UPDATE lotes SET costo_unitario = ? WHERE id = ?",
                     (costo_nuevo, lote_id))

        # Si es el ingreso mas reciente del producto, tambien se corrige
        # el costo_ultimo: si no, el proximo calculo de precio usaria el
        # valor equivocado.
        ultimo = conn.execute("""
            SELECT id FROM lotes WHERE producto_id = ?
            ORDER BY fecha_ingreso DESC, id DESC LIMIT 1
        """, (lote["producto_id"],)).fetchone()
        toco_costo_ultimo = bool(ultimo and ultimo["id"] == lote_id)
        if toco_costo_ultimo:
            conn.execute("""UPDATE productos SET costo_ultimo = ?,
                            modificado_en = datetime('now','localtime')
                            WHERE id = ?""", (costo_nuevo, lote["producto_id"]))
        conn.commit()

    viejo = float(lote["costo_unitario"] or 0)
    registrar_bitacora(
        "Correccion de costo", responsable or "sin identificar",
        f"{lote['descripcion']}: lote #{lote_id} de $ {viejo:,.2f} a "
        f"$ {costo_nuevo:,.2f}" + (f" — {nota}" if nota else ""),
        abs(costo_nuevo - viejo) * (lote["cantidad"] or 0), lote_id)

    return {
        "descripcion": lote["descripcion"],
        "costo_viejo": viejo, "costo_nuevo": costo_nuevo,
        "unidades_vendidas": vendido,
        "ganancia_corregida": (viejo - costo_nuevo) * vendido,
        "toco_costo_ultimo": toco_costo_ultimo,
        "precio_base": lote["precio_base"],
    }


def alinear_lotes_con_producto(producto_id: int, solo_con_stock=True) -> int:
    """Pone el costo del producto en sus lotes. Devuelve cuantos cambio.

    solo_con_stock=True por defecto: los lotes agotados representan
    compras reales que ya pasaron, y reescribirles el costo falsearia la
    ganancia historica de esas ventas.
    """
    with get_connection() as conn:
        costo = conn.execute(
            "SELECT costo_ultimo FROM productos WHERE id = ?",
            (producto_id,)).fetchone()
        if not costo or not costo["costo_ultimo"]:
            return 0
        cond = "AND cantidad_restante > 0" if solo_con_stock else ""
        cur = conn.execute(f"""
            UPDATE lotes SET costo_unitario = ?
            WHERE producto_id = ?
              AND ABS(COALESCE(costo_unitario, 0) - ?) > 0.01
              {cond}
        """, (costo["costo_ultimo"], producto_id, costo["costo_ultimo"]))
        conn.commit()
        return cur.rowcount


def actualizar_lote(lote_id: int, cantidad=None, costo=None,
                    proveedor_id="sin_cambio", fecha_vencimiento="sin_cambio",
                    notas="sin_cambio", responsable="") -> dict:
    """Edita un lote completo en una sola operacion.

    Hasta ahora habia una pantalla para el vencimiento y otra para el
    costo, y la cantidad no se podia tocar en ningun lado: para corregir
    un ingreso mal cargado habia que ajustar el stock y volver a
    ingresarlo.

    Devuelve un resumen de lo que cambio, para el aviso y la bitacora.
    """
    with get_connection() as conn:
        lote = conn.execute("""
            SELECT l.*, p.descripcion FROM lotes l
            JOIN productos p ON p.id = l.producto_id
            WHERE l.id = ?
        """, (lote_id,)).fetchone()
        if not lote:
            raise ValueError("El lote no existe.")
        lote = dict(lote)

        vendido = conn.execute("""
            SELECT COALESCE(SUM(cantidad), 0) FROM detalle_ventas_lotes
            WHERE lote_id = ?
        """, (lote_id,)).fetchone()[0] or 0

        cambios, sets, params = [], [], []

        if cantidad is not None:
            cantidad = float(cantidad)
            if cantidad < vendido:
                raise ValueError(
                    f"Ya se vendieron {vendido:g} unidades de este lote: "
                    f"la cantidad no puede ser menor que eso.")
            viejo = float(lote["cantidad"] or 0)
            if abs(cantidad - viejo) > 0.0001:
                # El restante se mueve junto con la cantidad: si no, se
                # descuadra el stock disponible.
                nuevo_rest = float(lote["cantidad_restante"] or 0) + (cantidad - viejo)
                sets += ["cantidad = ?", "cantidad_restante = ?"]
                params += [cantidad, max(0.0, nuevo_rest)]
                cambios.append(f"cantidad {viejo:g} → {cantidad:g}")

        if costo is not None:
            costo = float(costo)
            if costo < 0:
                raise ValueError("El costo no puede ser negativo.")
            viejo = float(lote["costo_unitario"] or 0)
            if abs(costo - viejo) > 0.005:
                sets.append("costo_unitario = ?")
                params.append(costo)
                cambios.append(f"costo $ {viejo:,.2f} → $ {costo:,.2f}")

        if proveedor_id != "sin_cambio":
            sets.append("proveedor_id = ?")
            params.append(proveedor_id)
            cambios.append("proveedor")

        if fecha_vencimiento != "sin_cambio":
            sets.append("fecha_vencimiento = ?")
            params.append(fecha_vencimiento or None)
            cambios.append(f"vencimiento → {fecha_vencimiento or 'sin fecha'}")

        if notas != "sin_cambio":
            sets.append("notas = ?")
            params.append(notas or None)
            cambios.append("notas")

        if sets:
            conn.execute(f"UPDATE lotes SET {', '.join(sets)} WHERE id = ?",
                         params + [lote_id])

            # Si se toco el costo y es el ingreso mas reciente, el costo
            # del producto tambien: si no, el proximo precio sale mal.
            if costo is not None:
                ult = conn.execute("""
                    SELECT id FROM lotes WHERE producto_id = ?
                    ORDER BY fecha_ingreso DESC, id DESC LIMIT 1
                """, (lote["producto_id"],)).fetchone()
                if ult and ult["id"] == lote_id:
                    conn.execute("""UPDATE productos SET costo_ultimo = ?,
                                    modificado_en = datetime('now','localtime')
                                    WHERE id = ?""",
                                 (costo, lote["producto_id"]))
            conn.commit()

    if cambios:
        registrar_bitacora(
            "Edicion de lote", responsable or "sin identificar",
            f"{lote['descripcion']}: lote #{lote_id} — " + ", ".join(cambios),
            0, lote_id)

    return {"descripcion": lote["descripcion"], "cambios": cambios,
            "vendido": vendido}


def actualizar_vencimiento_lote(lote_id: int, fecha) -> str | None:
    """Corrige el vencimiento de un lote ya cargado.

    Acepta 'AAAA-MM-DD' o 'DD/MM/AAAA'. fecha vacia o None lo deja sin
    vencimiento (para productos que no vencen, o cuando se cargo de mas).
    Devuelve la fecha guardada en formato ISO, o None.
    """
    texto = (str(fecha) if fecha is not None else "").strip()
    if not texto:
        with get_connection() as conn:
            conn.execute("UPDATE lotes SET fecha_vencimiento=NULL WHERE id=?",
                         (lote_id,))
            conn.commit()
        return None

    iso = None
    for formato in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y"):
        try:
            iso = datetime.strptime(texto, formato).strftime("%Y-%m-%d")
            break
        except ValueError:
            continue
    if not iso:
        raise ValueError(f"No entiendo la fecha «{texto}». Usá DD/MM/AAAA.")

    with get_connection() as conn:
        conn.execute("UPDATE lotes SET fecha_vencimiento=? WHERE id=?",
                     (iso, lote_id))
        conn.commit()
    return iso


def actualizar_proveedor_lote(lote_id: int, proveedor_id: int | None):
    """
    Corrige el proveedor de un lote ya cargado (por si te equivocaste
    al elegirlo en Ingreso de Stock). proveedor_id=None lo deja sin
    proveedor asignado.
    """
    with get_connection() as conn:
        conn.execute(
            "UPDATE lotes SET proveedor_id=? WHERE id=?",
            (proveedor_id, lote_id))
        conn.commit()


# ─────────────────────────────────────────────────────────────────────────────
# PRECIOS Y PROMOCIONES
# ─────────────────────────────────────────────────────────────────────────────

def get_promociones_activas_por_producto() -> dict:
    """
    Todas las promociones vigentes (activas y dentro de fecha) agrupadas
    por producto_id, para mandar al catálogo web — así la página de
    pedidos puede calcular el precio con descuento ella sola apenas
    el cliente llega a la cantidad mínima, sin pedirle nada al TPV.
    Retorna {producto_id: [{"cantidad_minima", "tipo_descuento",
    "porcentaje_descuento", "precio_unitario"}, ...]}.
    """
    hoy = datetime.now().strftime("%Y-%m-%d")
    with get_connection() as conn:
        filas = conn.execute("""
            SELECT producto_id, cantidad_minima, tipo_descuento,
                   porcentaje_descuento, precio_unitario
            FROM promociones
            WHERE activa = 1
              AND (fecha_desde IS NULL OR fecha_desde <= ?)
              AND (fecha_hasta IS NULL OR fecha_hasta >= ?)
        """, (hoy, hoy)).fetchall()
        agrupadas = {}
        for f in filas:
            agrupadas.setdefault(f["producto_id"], []).append({
                "cantidad_minima": f["cantidad_minima"],
                "tipo_descuento": f["tipo_descuento"] or "precio_fijo",
                "porcentaje_descuento": f["porcentaje_descuento"],
                "precio_unitario": f["precio_unitario"],
            })
        return agrupadas


# ─────────────────────────────────────────────────────────────────────────────
# PROMOS COMBINABLES — "llevando 3 gaseosas cualquiera"
# ─────────────────────────────────────────────────────────────────────────────

def guardar_promo_grupo(gid, nombre, cantidad_minima, tipo, valor,
                        producto_ids, fecha_desde=None, fecha_hasta=None,
                        activa=True) -> int:
    """Crea o edita un grupo de promo combinable."""
    if int(cantidad_minima) < 2:
        raise ValueError("La cantidad mínima tiene que ser 2 o más.")
    if len(producto_ids) < 2:
        raise ValueError("Un grupo combinable necesita al menos 2 productos.")

    with get_connection() as conn:
        if gid:
            conn.execute("""
                UPDATE promo_grupos
                   SET nombre=?, cantidad_minima=?, tipo=?, valor=?,
                       fecha_desde=?, fecha_hasta=?, activa=?
                 WHERE id=?
            """, (nombre.strip(), int(cantidad_minima), tipo, float(valor),
                  fecha_desde, fecha_hasta, int(bool(activa)), gid))
            conn.execute("DELETE FROM promo_grupo_items WHERE grupo_id=?", (gid,))
        else:
            cur = conn.execute("""
                INSERT INTO promo_grupos
                    (nombre, cantidad_minima, tipo, valor,
                     fecha_desde, fecha_hasta, activa)
                VALUES (?,?,?,?,?,?,?)
            """, (nombre.strip(), int(cantidad_minima), tipo, float(valor),
                  fecha_desde, fecha_hasta, int(bool(activa))))
            gid = cur.lastrowid
        for pid in producto_ids:
            conn.execute("INSERT OR IGNORE INTO promo_grupo_items "
                         "(grupo_id, producto_id) VALUES (?,?)", (gid, int(pid)))
        conn.commit()
    return gid


def get_promo_grupos(solo_activos=False) -> list:
    cond = "WHERE activa = 1" if solo_activos else ""
    with get_connection() as conn:
        grupos = [dict(r) for r in conn.execute(
            f"SELECT * FROM promo_grupos {cond} ORDER BY nombre").fetchall()]
        for g in grupos:
            g["productos"] = [dict(r) for r in conn.execute("""
                SELECT p.id, p.descripcion, p.codigo, p.precio_base
                FROM promo_grupo_items i
                JOIN productos p ON p.id = i.producto_id
                WHERE i.grupo_id = ?
                ORDER BY p.descripcion
            """, (g["id"],)).fetchall()]
    return grupos


def borrar_promo_grupo(gid):
    with get_connection() as conn:
        conn.execute("DELETE FROM promo_grupos WHERE id=?", (gid,))
        conn.commit()


def aplicar_promos_combinables(carrito: list) -> list:
    """Aplica las promos de grupo al carrito y devuelve los avisos.

    Cuenta cuantas unidades del grupo hay en TODO el carrito, sin importar
    como se repartan entre productos: 1 Coca + 1 Sprite + 1 Fanta son 3
    unidades y la promo aplica igual que 3 Cocas.

    Modifica el carrito en el lugar. Devuelve una lista de textos para
    mostrarle al cajero que promo entro.
    """
    hoy = datetime.now().strftime("%Y-%m-%d")
    grupos = [g for g in get_promo_grupos(solo_activos=True)
              if (not g["fecha_desde"] or g["fecha_desde"] <= hoy)
              and (not g["fecha_hasta"] or g["fecha_hasta"] >= hoy)]
    if not grupos:
        return []

    avisos = []
    # De mayor a menor exigencia: si un carrito califica para dos grupos,
    # gana el que pide mas unidades, que es el mejor descuento.
    for g in sorted(grupos, key=lambda x: -x["cantidad_minima"]):
        ids = {p["id"] for p in g["productos"]}
        items = [i for i in carrito
                 if i.get("producto_id") in ids and not i.get("_promo_grupo")]
        total_un = sum(i["cantidad"] for i in items)
        if total_un < g["cantidad_minima"]:
            continue

        ahorro = 0.0
        for i in items:
            base = float(i["precio_unitario"])
            if g["tipo"] == "descuento_pct":
                nuevo = base * (1 - float(g["valor"]) / 100)
            else:
                nuevo = float(g["valor"])
            # Nunca se sube el precio: si el producto ya estaba mas barato
            # que la promo, se respeta el precio que ya tenia.
            if nuevo >= base:
                continue
            ahorro += (base - nuevo) * i["cantidad"]
            i["precio_unitario"] = nuevo
            i["subtotal"] = nuevo * i["cantidad"]
            i["promo_aplicada"] = True
            i["_promo_grupo"] = g["id"]

        if ahorro > 0:
            avisos.append(f"{g['nombre']}: {total_un:g} unidades — "
                          f"ahorra $ {ahorro:,.2f}")
    return avisos


def promo_grupo_faltante(carrito: list) -> list:
    """Grupos a los que les falta poco para entrar.

    Sirve para avisarle al cajero "con una mas entra la promo": es una
    venta extra que se pierde solo porque nadie lo dijo.
    """
    hoy = datetime.now().strftime("%Y-%m-%d")
    out = []
    for g in get_promo_grupos(solo_activos=True):
        if g["fecha_desde"] and g["fecha_desde"] > hoy:
            continue
        if g["fecha_hasta"] and g["fecha_hasta"] < hoy:
            continue
        ids = {p["id"] for p in g["productos"]}
        total = sum(i["cantidad"] for i in carrito
                    if i.get("producto_id") in ids)
        falta = g["cantidad_minima"] - total
        if 0 < falta <= 2 and total > 0:
            out.append({"nombre": g["nombre"], "falta": falta,
                        "cantidad_minima": g["cantidad_minima"]})
    return out


def get_precio_con_promo(producto_id: int, cantidad: float) -> tuple[float, bool]:
    """Retorna (precio_unitario, promo_aplicada). Si hay varias promos
    aplicables por la cantidad, usa la que dé el precio más bajo —
    tanto para promos de precio fijo como de % de descuento (el %
    se calcula siempre sobre el precio_base actual del producto, así
    que si cambiás el precio de lista, la promo de % se ajusta sola)."""
    hoy = datetime.now().strftime("%Y-%m-%d")
    with get_connection() as conn:
        prod = conn.execute(
            "SELECT id, precio_base, categoria_id FROM productos WHERE id=?",
            (producto_id,)).fetchone()
        precio_base = prod["precio_base"] if prod else 0.0

    # El recargo por horario se aplica ANTES de las promos: la promo es
    # un descuento sobre lo que vale el producto en ese momento, no
    # sobre el precio de otro horario.
    if prod:
        precio_base, _regla = aplicar_recargo(precio_base, dict(prod))

    with get_connection() as conn:

        promos = conn.execute("""
            SELECT tipo_descuento, porcentaje_descuento, precio_unitario
            FROM promociones
            WHERE producto_id = ?
              AND cantidad_minima <= ?
              AND activa = 1
              AND (fecha_desde IS NULL OR fecha_desde <= ?)
              AND (fecha_hasta IS NULL OR fecha_hasta >= ?)
        """, (producto_id, cantidad, hoy, hoy)).fetchall()

        if not promos:
            return precio_base, False

        mejor_precio = None
        for pr in promos:
            if pr["tipo_descuento"] == "porcentaje" and pr["porcentaje_descuento"] is not None:
                precio_promo = round(precio_base * (1 - pr["porcentaje_descuento"] / 100), 2)
            else:
                precio_promo = pr["precio_unitario"]
            if mejor_precio is None or precio_promo < mejor_precio:
                mejor_precio = precio_promo

        return mejor_precio, True


def get_promociones() -> list:
    with get_connection() as conn:
        return [dict(r) for r in conn.execute("""
            SELECT pr.id, p.descripcion, p.codigo,
                   pr.cantidad_minima, pr.precio_unitario,
                   pr.tipo_descuento, pr.porcentaje_descuento,
                   pr.descripcion as detalle,
                   pr.fecha_desde, pr.fecha_hasta, pr.activa
            FROM promociones pr
            JOIN productos p ON pr.producto_id = p.id
            ORDER BY pr.activa DESC, p.descripcion
        """).fetchall()]


def guardar_promocion(pid, producto_id, cant_min, precio,
                      descripcion, fecha_desde, fecha_hasta,
                      tipo_descuento="precio_fijo", porcentaje=None):
    """
    tipo_descuento: "precio_fijo" (precio ya viene calculado) o
    "porcentaje" (precio es solo un valor de referencia calculado al
    guardar, para mostrar en el listado — el precio real de venta se
    recalcula siempre en get_precio_con_promo contra el precio_base
    vigente del producto, usando porcentaje).
    """
    with get_connection() as conn:
        if pid:
            conn.execute("""
                UPDATE promociones
                SET producto_id=?, cantidad_minima=?, precio_unitario=?,
                    tipo_descuento=?, porcentaje_descuento=?,
                    descripcion=?, fecha_desde=?, fecha_hasta=?
                WHERE id=?
            """, (producto_id, cant_min, precio, tipo_descuento, porcentaje,
                  descripcion, fecha_desde or None, fecha_hasta or None, pid))
        else:
            conn.execute("""
                INSERT INTO promociones
                    (producto_id, cantidad_minima, precio_unitario,
                     tipo_descuento, porcentaje_descuento,
                     descripcion, fecha_desde, fecha_hasta)
                VALUES (?,?,?,?,?,?,?,?)
            """, (producto_id, cant_min, precio, tipo_descuento, porcentaje,
                  descripcion, fecha_desde or None, fecha_hasta or None))
        conn.commit()


def toggle_promocion(pid, activa: int):
    with get_connection() as conn:
        conn.execute("UPDATE promociones SET activa=? WHERE id=?", (activa, pid))
        conn.commit()


def eliminar_promocion(pid):
    with get_connection() as conn:
        conn.execute("DELETE FROM promociones WHERE id=?", (pid,))
        conn.commit()


def actualizar_precio(pid, nuevo_precio):
    nuevo_precio = redondear_precio(nuevo_precio)
    with get_connection() as conn:
        _anotar_cambio_precio(conn, pid, nuevo_precio)
        conn.execute("""
            UPDATE productos SET precio_base=?,
            modificado_en=datetime('now','localtime') WHERE id=?
        """, (nuevo_precio, pid))
        conn.commit()


# ─────────────────────────────────────────────────────────────────────────────
# CODIGOS DE BARRAS PROPIOS
# ─────────────────────────────────────────────────────────────────────────────

# Prefijo 2xx: el estandar EAN reserva 200-299 para uso interno de cada
# comercio. Nunca choca con un codigo de fabrica, asi que se puede
# imprimir y escanear como cualquier otro producto.
PREFIJO_INTERNO = "200"


def _digito_ean13(doce: str) -> str:
    """Digito verificador de un EAN-13. Sin esto el scanner lo rechaza."""
    suma = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(doce))
    return str((10 - suma % 10) % 10)


def _digito_ean8(siete: str) -> str:
    """Digito verificador de un EAN-8. Los pesos van al reves que en el 13."""
    suma = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(siete))
    return str((10 - suma % 10) % 10)


def es_ean_valido(codigo: str) -> bool:
    """True si el codigo se puede escanear tal cual esta.

    Contempla EAN-13, EAN-8 (muy comun en golosinas y productos chicos:
    alfajores, turrones, obleas) y UPC-A de 12 digitos. Validar solo el
    13 hacia que codigos de fabrica perfectamente buenos figuraran como
    "sin codigo" y estuvieran a un clic de ser reemplazados.
    """
    c = "".join(ch for ch in str(codigo or "") if ch.isdigit())
    if len(c) == 13:
        return _digito_ean13(c[:12]) == c[12]
    if len(c) == 8:
        return _digito_ean8(c[:7]) == c[7]
    if len(c) == 12:
        # UPC-A: se valida como EAN-13 con un cero adelante
        return _digito_ean13(("0" + c)[:12]) == c[11]
    return False


def generar_codigo_interno(producto_id: int = None) -> str:
    """Devuelve un EAN-13 propio, listo para imprimir y escanear.

    Se arma con el prefijo interno + el id del producto (o el proximo
    numero libre) + el digito verificador. Usar el id lo hace estable:
    el mismo producto siempre tiene el mismo codigo.
    """
    with get_connection() as conn:
        if producto_id is None:
            producto_id = (conn.execute(
                "SELECT COALESCE(MAX(id), 0) + 1 FROM productos").fetchone()[0])
        base = f"{PREFIJO_INTERNO}{int(producto_id):09d}"[:12]
        codigo = base + _digito_ean13(base)
        # Colision (poco probable, pero el id pudo reusarse): se corre al
        # siguiente libre en vez de pisar otro producto
        intentos = 0
        while conn.execute("SELECT 1 FROM productos WHERE codigo = ?",
                           (codigo,)).fetchone() and intentos < 50:
            producto_id += 1
            base = f"{PREFIJO_INTERNO}{int(producto_id):09d}"[:12]
            codigo = base + _digito_ean13(base)
            intentos += 1
    return codigo


def productos_sin_codigo_valido() -> list:
    """Productos cuyo codigo no se puede escanear.

    Sin codigo, o con uno inventado a mano (QCREM-FRAC, "monopatinverde"
    y similares): la etiqueta sale sin codigo de barras legible y hay que
    buscarlos por nombre en cada venta.

    NO incluye los que tienen un EAN valido de fabrica, sea de 13, 12 u
    8 digitos.
    """
    with get_connection() as conn:
        filas = [dict(r) for r in conn.execute("""
            SELECT id, codigo, descripcion, marca, precio_base,
                   vendido_por_peso
            FROM productos WHERE COALESCE(activo, 1) = 1
            ORDER BY descripcion
        """).fetchall()]
    return [f for f in filas if not es_ean_valido(f["codigo"])]


def asignar_codigo_interno(producto_id: int) -> str:
    codigo = generar_codigo_interno(producto_id)
    with get_connection() as conn:
        conn.execute("""UPDATE productos SET codigo = ?,
                        modificado_en = datetime('now','localtime')
                        WHERE id = ?""", (codigo, producto_id))
        conn.commit()
    return codigo


# ─────────────────────────────────────────────────────────────────────────────
# RECARGOS POR HORARIO
# ─────────────────────────────────────────────────────────────────────────────

DIAS_SEMANA = ("Lunes", "Martes", "Miercoles", "Jueves", "Viernes",
               "Sabado", "Domingo")


def guardar_recargo(rid, nombre, porcentaje, dias, hora_desde, hora_hasta,
                    alcance="todo", categoria_ids=None, producto_ids=None,
                    activo=True) -> int:
    """Crea o edita una regla de recargo. dias: lista de 0..6 (0=lunes)."""
    dias_txt = ",".join(str(int(d)) for d in sorted(set(dias)))
    with get_connection() as conn:
        if rid:
            conn.execute("""
                UPDATE recargos_horario
                SET nombre=?, porcentaje=?, dias=?, hora_desde=?, hora_hasta=?,
                    alcance=?, activo=?
                WHERE id=?
            """, (nombre, float(porcentaje), dias_txt, int(hora_desde),
                  int(hora_hasta), alcance, int(bool(activo)), rid))
        else:
            cur = conn.execute("""
                INSERT INTO recargos_horario
                    (nombre, porcentaje, dias, hora_desde, hora_hasta,
                     alcance, activo)
                VALUES (?,?,?,?,?,?,?)
            """, (nombre, float(porcentaje), dias_txt, int(hora_desde),
                  int(hora_hasta), alcance, int(bool(activo))))
            rid = cur.lastrowid

        conn.execute("DELETE FROM recargo_alcance WHERE recargo_id=?", (rid,))
        for cid in (categoria_ids or []):
            conn.execute("INSERT INTO recargo_alcance (recargo_id, categoria_id) "
                         "VALUES (?,?)", (rid, int(cid)))
        for pid in (producto_ids or []):
            conn.execute("INSERT INTO recargo_alcance (recargo_id, producto_id) "
                         "VALUES (?,?)", (rid, int(pid)))
        conn.commit()
    return rid


def get_recargos(solo_activos=False) -> list:
    cond = "WHERE activo = 1" if solo_activos else ""
    with get_connection() as conn:
        filas = [dict(r) for r in conn.execute(
            f"SELECT * FROM recargos_horario {cond} ORDER BY nombre").fetchall()]
        for f in filas:
            f["categoria_ids"] = [r[0] for r in conn.execute(
                "SELECT categoria_id FROM recargo_alcance "
                "WHERE recargo_id=? AND categoria_id IS NOT NULL", (f["id"],))]
            f["producto_ids"] = [r[0] for r in conn.execute(
                "SELECT producto_id FROM recargo_alcance "
                "WHERE recargo_id=? AND producto_id IS NOT NULL", (f["id"],))]
    return filas


def eliminar_recargo(rid):
    with get_connection() as conn:
        conn.execute("DELETE FROM recargos_horario WHERE id=?", (rid,))
        conn.commit()


def _recargo_rige(r, momento=None) -> bool:
    """Si la regla esta vigente en ese momento.

    Contempla el cruce de medianoche: 18 a 8 significa "de las 18 de HOY
    a las 8 de MAÑANA", asi que a la 1 AM del martes rige la regla que
    arranco el lunes 18.
    """
    momento = momento or datetime.now()
    h = momento.hour
    dias = {int(d) for d in str(r["dias"]).split(",") if d.strip().isdigit()}
    hoy = momento.weekday()          # 0 = lunes, igual que la tabla
    ayer = (hoy - 1) % 7
    desde, hasta = int(r["hora_desde"]), int(r["hora_hasta"])

    if desde == hasta:
        return hoy in dias           # todo el dia
    if desde < hasta:
        return hoy in dias and desde <= h < hasta
    # Cruza medianoche: el tramo de la madrugada pertenece al dia anterior
    if h >= desde:
        return hoy in dias
    if h < hasta:
        return ayer in dias
    return False


def _recargo_alcanza(r, producto) -> bool:
    if r["alcance"] == "todo":
        return True
    if r["alcance"] == "categorias":
        return producto.get("categoria_id") in set(r["categoria_ids"])
    return producto.get("id") in set(r["producto_ids"])


def recargo_vigente(producto=None, momento=None) -> dict | None:
    """La regla que rige ahora para ese producto, o None.

    Si hay varias, gana la de MAYOR porcentaje: es la mas especifica que
    alguien configuro a proposito.
    """
    candidatas = [r for r in get_recargos(solo_activos=True)
                  if _recargo_rige(r, momento)
                  and (producto is None or _recargo_alcanza(r, producto))]
    if not candidatas:
        return None
    return max(candidatas, key=lambda r: r["porcentaje"])


def aplicar_recargo(precio, producto=None, momento=None) -> tuple[float, dict]:
    """Devuelve (precio_final, regla_aplicada|None).

    El precio de lista NO se toca en la base: el recargo se calcula al
    vender. Tocar los precios reales obligaria a deshacerlo al volver al
    horario normal, y un corte de luz en el medio dejaria el catalogo mal.
    """
    r = recargo_vigente(producto, momento)
    if not r:
        return float(precio), None
    final = float(precio) * (1 + float(r["porcentaje"]) / 100)
    return redondear_precio(final), r


def duplicar_producto(producto_id: int, descripcion_nueva: str,
                      codigo_nuevo: str = "") -> int:
    """Crea un producto copiando todo salvo el nombre y el codigo.

    Cargar la sexta variedad de la misma marca obliga hoy a repetir a
    mano categoria, marca, precio, costo, margen y si va por peso. Copiar
    y cambiar lo que difiere es una operacion, no seis.

    El stock NO se copia: el producto nuevo arranca en cero, que es lo
    correcto — todavia no entro ninguno.
    """
    with get_connection() as conn:
        orig = conn.execute(
            "SELECT * FROM productos WHERE id = ?", (producto_id,)).fetchone()
        if not orig:
            raise ValueError("El producto a copiar no existe.")
        orig = dict(orig)

    nuevo_id = crear_producto(
        codigo_nuevo, descripcion_nueva, orig.get("categoria_id"),
        orig.get("precio_base") or 0, orig.get("costo_ultimo") or 0,
        orig.get("vendido_por_peso") or 0, orig.get("marca"))

    # margen_pct y alerta no van en crear_producto: se copian aparte
    with get_connection() as conn:
        conn.execute("""
            UPDATE productos
               SET margen_pct = ?, alerta_dias_vto = ?,
                   ignorar_alerta = ?
             WHERE id = ?
        """, (orig.get("margen_pct"), orig.get("alerta_dias_vto"),
              orig.get("ignorar_alerta") or 0, nuevo_id))
        conn.commit()
    return nuevo_id


def toggle_publicar_web(ids, publicar=None) -> int:
    """Marca o desmarca productos para el catalogo web.

    publicar=None invierte el valor actual de cada uno.
    """
    ids = [ids] if isinstance(ids, int) else list(ids)
    if not ids:
        return 0
    marcas = ",".join("?" * len(ids))
    with get_connection() as conn:
        if publicar is None:
            cur = conn.execute(f"""
                UPDATE productos
                   SET publicar_web = CASE WHEN COALESCE(publicar_web,1)=1
                                           THEN 0 ELSE 1 END
                 WHERE id IN ({marcas})
            """, ids)
        else:
            cur = conn.execute(
                f"UPDATE productos SET publicar_web = ? WHERE id IN ({marcas})",
                [int(bool(publicar))] + ids)
        conn.commit()
        return cur.rowcount


def productos_bajo_costo(ids=None) -> list:
    """Productos cuyo precio de venta quedo por debajo del costo.

    Se usa para avisar ANTES de guardar un precio: vender bajo costo
    puede ser deliberado (liquidar algo por vencer), pero por descuido
    es plata que se pierde en cada venta sin que nada lo marque.
    """
    cond, params = ["COALESCE(p.activo,1)=1",
                    "COALESCE(p.costo_ultimo,0) > 0",
                    "p.precio_base < p.costo_ultimo"], []
    if ids:
        cond.append("p.id IN (%s)" % ",".join("?" * len(ids)))
        params += list(ids)
    with get_connection() as conn:
        return [dict(r) for r in conn.execute(f"""
            SELECT p.id, p.codigo, p.descripcion, p.precio_base,
                   p.costo_ultimo,
                   (p.costo_ultimo - p.precio_base) as perdida_unidad
            FROM productos p
            WHERE {" AND ".join(cond)}
            ORDER BY perdida_unidad DESC
        """, params).fetchall()]


def _anotar_cambios_masivos(conn, ids, motivo):
    """Anota el cambio de cada producto de una operacion masiva."""
    for pid in ids:
        try:
            nuevo = conn.execute(
                "SELECT precio_base FROM productos WHERE id = ?",
                (pid,)).fetchone()
            if nuevo:
                _anotar_cambio_precio(conn, pid, nuevo["precio_base"], motivo)
        except Exception:
            pass


def _redondear_ids(conn, ids):
    """Aplica el redondeo configurado a los productos indicados."""
    paso = 0
    try:
        from config import cfg
        paso = int(cfg().get("redondeo_precios", 0) or 0)
        modo = str(cfg().get("redondeo_modo", "cercano"))
    except Exception:
        modo = "cercano"
    if paso <= 0:
        return
    marcas = ",".join("?" * len(ids))
    filas = conn.execute(
        f"SELECT id, precio_base FROM productos WHERE id IN ({marcas})",
        ids).fetchall()
    for f in filas:
        nuevo = redondear_precio(f["precio_base"] or 0, paso, modo)
        if abs(nuevo - (f["precio_base"] or 0)) >= 0.005:
            conn.execute("UPDATE productos SET precio_base=? WHERE id=?",
                         (nuevo, f["id"]))


def aplicar_aumento_bulk(ids: list, pct: float):
    with get_connection() as conn:
        # El precio viejo se guarda ANTES del UPDATE: despues
        # ya se perdio y el historial quedaria sin el origen.
        _previos = {r["id"]: r["precio_base"] for r in conn.execute(
            "SELECT id, precio_base FROM productos WHERE id IN (%s)"
            % ",".join("?" * len(ids)), ids)}
        conn.execute(f"""
            UPDATE productos SET
                precio_base = ROUND(precio_base * (1 + ? / 100.0), 2),
                modificado_en = datetime('now','localtime')
            WHERE id IN ({','.join('?'*len(ids))})
        """, [pct] + ids)
        _redondear_ids(conn, ids)
        # Historial: se compara contra el precio previo ya guardado
        for _pid, _viejo in _previos.items():
            _nuevo = conn.execute(
                "SELECT precio_base FROM productos WHERE id = ?",
                (_pid,)).fetchone()
            if _nuevo and abs((_nuevo["precio_base"] or 0) - (_viejo or 0)) >= 0.005:
                conn.execute("""
                    INSERT INTO historial_precios
                        (producto_id, precio_viejo, precio_nuevo, motivo)
                    VALUES (?,?,?,?)
                """, (_pid, _viejo, _nuevo["precio_base"], "Cambio masivo"))
        conn.commit()


def aplicar_margen_nuevo_bulk(ids: list, margen_pct: float):
    """
    Fija margen_pct = margen_pct (margen PROPIO, ya no hereda de la
    categoría) y recalcula precio_base = costo x (1 + margen%) para
    los productos dados. A diferencia de aplicar_margen_bulk (que usa
    el margen que cada producto YA tenía), esta cambia el margen en
    sí para todos los seleccionados.
    """
    with get_connection() as conn:
        # El precio viejo se guarda ANTES del UPDATE: despues
        # ya se perdio y el historial quedaria sin el origen.
        _previos = {r["id"]: r["precio_base"] for r in conn.execute(
            "SELECT id, precio_base FROM productos WHERE id IN (%s)"
            % ",".join("?" * len(ids)), ids)}
        conn.execute(f"""
            UPDATE productos SET
                margen_pct = ?,
                precio_base = CASE WHEN costo_ultimo > 0
                    THEN ROUND(costo_ultimo * (1 + ? / 100.0), 2)
                    ELSE precio_base END,
                modificado_en = datetime('now','localtime')
            WHERE id IN ({','.join('?'*len(ids))})
        """, [margen_pct, margen_pct] + ids)
        _redondear_ids(conn, ids)
        # Historial: se compara contra el precio previo ya guardado
        for _pid, _viejo in _previos.items():
            _nuevo = conn.execute(
                "SELECT precio_base FROM productos WHERE id = ?",
                (_pid,)).fetchone()
            if _nuevo and abs((_nuevo["precio_base"] or 0) - (_viejo or 0)) >= 0.005:
                conn.execute("""
                    INSERT INTO historial_precios
                        (producto_id, precio_viejo, precio_nuevo, motivo)
                    VALUES (?,?,?,?)
                """, (_pid, _viejo, _nuevo["precio_base"], "Cambio masivo"))
        conn.commit()


def aplicar_margen_bulk(ids: list):
    """
    Recalcula precio_base = costo x (1 + margen%) para los productos
    dados, usando el margen PROPIO del producto si tiene uno, o el de
    su categoría si no (igual criterio que calcular_precio_por_margen).
    """
    with get_connection() as conn:
        # El precio viejo se guarda ANTES del UPDATE: despues
        # ya se perdio y el historial quedaria sin el origen.
        _previos = {r["id"]: r["precio_base"] for r in conn.execute(
            "SELECT id, precio_base FROM productos WHERE id IN (%s)"
            % ",".join("?" * len(ids)), ids)}
        conn.execute(f"""
            UPDATE productos SET
                precio_base = ROUND(costo_ultimo * (1 + COALESCE(
                    productos.margen_pct,
                    (SELECT margen_pct FROM categorias
                     WHERE id = productos.categoria_id),
                    30.0
                ) / 100.0), 2),
                modificado_en = datetime('now','localtime')
            WHERE id IN ({','.join('?'*len(ids))}) AND costo_ultimo > 0
        """, ids)
        _redondear_ids(conn, ids)
        # Historial: se compara contra el precio previo ya guardado
        for _pid, _viejo in _previos.items():
            _nuevo = conn.execute(
                "SELECT precio_base FROM productos WHERE id = ?",
                (_pid,)).fetchone()
            if _nuevo and abs((_nuevo["precio_base"] or 0) - (_viejo or 0)) >= 0.005:
                conn.execute("""
                    INSERT INTO historial_precios
                        (producto_id, precio_viejo, precio_nuevo, motivo)
                    VALUES (?,?,?,?)
                """, (_pid, _viejo, _nuevo["precio_base"], "Cambio masivo"))
        conn.commit()


def diagnostico_recalculo_categoria(categoria_id: int) -> dict:
    """
    Cuenta, SIN tocar nada, cuántos productos activos hay en la
    categoría y en qué situación está cada uno respecto al recálculo:
    heredan el margen (se van a actualizar), tienen margen propio
    (no se tocan), o no tienen costo cargado (no se puede calcular
    nada sin costo). Se usa para explicar el resultado del recálculo
    ANTES de aplicarlo — evita el "no pasó nada" sin explicación.
    """
    with get_connection() as conn:
        total = conn.execute(
            "SELECT COUNT(*) as n FROM productos WHERE categoria_id=? AND activo=1",
            (categoria_id,)).fetchone()["n"]
        heredan = conn.execute("""
            SELECT COUNT(*) as n FROM productos
            WHERE categoria_id=? AND activo=1
              AND margen_pct IS NULL AND costo_ultimo > 0
        """, (categoria_id,)).fetchone()["n"]
        margen_propio = conn.execute("""
            SELECT COUNT(*) as n FROM productos
            WHERE categoria_id=? AND activo=1 AND margen_pct IS NOT NULL
        """, (categoria_id,)).fetchone()["n"]
        sin_costo = conn.execute("""
            SELECT COUNT(*) as n FROM productos
            WHERE categoria_id=? AND activo=1
              AND margen_pct IS NULL AND (costo_ultimo IS NULL OR costo_ultimo <= 0)
        """, (categoria_id,)).fetchone()["n"]
    return {"total": total, "heredan": heredan,
            "margen_propio": margen_propio, "sin_costo": sin_costo}


def recalcular_precios_categoria(categoria_id: int) -> int:
    """
    Recalcula el precio de venta de los productos ACTIVOS de una
    categoría que heredan su margen (no tienen uno propio), usando el
    margen ACTUAL de la categoría. Los que tienen margen propio no se
    tocan (siguen con su propio %, no el de la categoría).
    Se usa después de cambiar el margen de una categoría — si no, el
    cambio queda "guardado" pero no se refleja en ningún precio hasta
    el próximo ingreso de stock con cambio de costo.
    Devuelve la cantidad de productos actualizados.
    """
    with get_connection() as conn:
        cur = conn.execute("""
            UPDATE productos SET
                precio_base = ROUND(costo_ultimo * (1 + (
                    SELECT margen_pct FROM categorias WHERE id = ?
                ) / 100.0), 2),
                modificado_en = datetime('now','localtime')
            WHERE categoria_id = ? AND activo = 1
              AND margen_pct IS NULL AND costo_ultimo > 0
        """, (categoria_id, categoria_id))
        conn.commit()
        return cur.rowcount


def aplicar_promocion_bulk(ids: list, escalas: list[tuple[int, float]],
                           descripcion: str, fecha_desde: str | None,
                           fecha_hasta: str | None) -> int:
    """
    Aplica descuentos por % sobre el precio de lista a varios productos
    de una — "todos", "algunos" o "una categoría", según lo que venga
    en ids. Admite VARIAS escalas por cantidad en la misma pasada, ej:
    [(3, 5), (20, 10)] = "llevando 3 o más, 5% off; llevando 20 o más,
    10% off". Se guarda como promociones normales (precio_unitario ya
    con el descuento aplicado), reutilizando el mismo motor de
    promociones que ya usa la venta para elegir el mejor precio.
    Si un producto ya tenía una promo con esa MISMA cantidad_minima
    (activa) se ACTUALIZA en vez de duplicarla; si no, se crea una
    nueva. Devuelve la cantidad de promociones creadas/actualizadas.
    """
    if not ids or not escalas:
        return 0
    with get_connection() as conn:
        filas = conn.execute(f"""
            SELECT id, precio_base FROM productos
            WHERE id IN ({','.join('?'*len(ids))})
        """, ids).fetchall()

        cants = sorted({int(c) for c, _ in escalas})
        existentes = {(r["producto_id"], r["cantidad_minima"]): r["id"]
                     for r in conn.execute(f"""
            SELECT id, producto_id, cantidad_minima FROM promociones
            WHERE producto_id IN ({','.join('?'*len(ids))})
              AND cantidad_minima IN ({','.join('?'*len(cants))}) AND activa = 1
        """, ids + cants).fetchall()}

        afectados = 0
        for f in filas:
            for cant_min, pct in escalas:
                cant_min = int(cant_min)
                precio_promo = round(f["precio_base"] * (1 - pct / 100.0), 2)
                desc_final = descripcion or f"Llevando {cant_min}"
                promo_id = existentes.get((f["id"], cant_min))
                if promo_id:
                    conn.execute("""
                        UPDATE promociones
                        SET precio_unitario=?, descripcion=?,
                            fecha_desde=?, fecha_hasta=?
                        WHERE id=?
                    """, (precio_promo, desc_final, fecha_desde or None,
                          fecha_hasta or None, promo_id))
                else:
                    conn.execute("""
                        INSERT INTO promociones
                            (producto_id, cantidad_minima, precio_unitario,
                             descripcion, fecha_desde, fecha_hasta)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (f["id"], cant_min, precio_promo, desc_final,
                          fecha_desde or None, fecha_hasta or None))
                afectados += 1
        conn.commit()
        return afectados


# ─────────────────────────────────────────────────────────────────────────────
# VENTAS
# ─────────────────────────────────────────────────────────────────────────────

def validar_stock_carrito(items) -> list:
    """Que items del carrito no tienen stock suficiente.

    Se usa ANTES de cobrar: descubrirlo cuando ya se conto la plata
    obliga a rehacer la venta con el cliente esperando.

    Devuelve [{"descripcion", "pedido", "disponible"}] — vacio si esta ok.
    """
    faltantes = []
    # Un mismo producto puede estar en dos lineas (granel + presentacion)
    pedido = {}
    for it in items:
        pid = it.get("producto_id")
        if pid:
            pedido[pid] = pedido.get(pid, 0) + float(it.get("cantidad") or 0)

    with get_connection() as conn:
        for pid, cant in pedido.items():
            r = conn.execute("""
                SELECT p.descripcion, p.vendido_por_peso,
                       COALESCE((SELECT SUM(l.cantidad_restante) FROM lotes l
                                  WHERE l.producto_id = p.id), 0) as stock
                FROM productos p WHERE p.id = ?
            """, (pid,)).fetchone()
            if not r:
                continue
            # Margen de 1 g / 1 milesimo para no trabar por redondeo
            if cant > (r["stock"] or 0) + 0.001:
                faltantes.append({
                    "descripcion": r["descripcion"],
                    "pedido": cant, "disponible": r["stock"] or 0,
                    "por_peso": bool(r["vendido_por_peso"]),
                })
    return faltantes


def registrar_venta(sesion_id, items, metodo_pago,
                    descuento_pct=0.0, cliente_id=None,
                    desglose=None) -> int | None:
    """Registra la venta.

    desglose: dict opcional {"efectivo":0, "tarjeta":0, "qr":0,
    "cta_cte":0} para pagos repartidos entre varios medios. Sin el, todo
    el total va al metodo indicado en metodo_pago.
    """
    conn = get_connection()
    try:
        subtotales   = [i["cantidad"] * i["precio_unitario"] for i in items]
        total_bruto  = sum(subtotales)
        desc_monto   = total_bruto * (descuento_pct / 100)
        total        = total_bruto - desc_monto

        # Sin desglose, todo el total va al metodo elegido: asi las
        # ventas de un solo medio siguen cuadrando igual.
        _d = {k: float(v) for k, v in (desglose or {}).items() if v}
        if not _d:
            _clave = {"efectivo": "efectivo", "tarjeta": "tarjeta",
                      "qr": "qr", "cuenta_corriente": "cta_cte"}.get(
                          metodo_pago, "efectivo")
            _d = {_clave: total}

        cur = conn.execute("""
            INSERT INTO ventas
                (sesion_id, total, metodo_pago, descuento_pct,
                 descuento_monto, cliente_id,
                 monto_efectivo, monto_tarjeta, monto_qr, monto_cta_cte)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (sesion_id, total, metodo_pago, descuento_pct,
              desc_monto, cliente_id,
              _d.get("efectivo", 0), _d.get("tarjeta", 0),
              _d.get("qr", 0), _d.get("cta_cte", 0)))
        venta_id = cur.lastrowid

        for item, sub in zip(items, subtotales):
            cur_det = conn.execute("""
                INSERT INTO detalle_ventas
                    (venta_id, producto_id, descripcion, cantidad,
                     precio_unitario, subtotal, promo_aplicada)
                VALUES (?,?,?,?,?,?,?)
            """, (venta_id, item["producto_id"], item["descripcion"],
                  item["cantidad"], item["precio_unitario"],
                  sub, item.get("promo_aplicada", 0)))

            ok = descontar_stock_fifo(
                item["producto_id"], item["cantidad"],
                conn=conn, detalle_venta_id=cur_det.lastrowid)
            if not ok:
                raise ValueError(f"Stock insuficiente: {item['descripcion']}")

        # Cada parte del pago va a SU columna. Antes el mixto sumaba todo
        # a efectivo y el arqueo mostraba un sobrante inexplicable; con un
        # pago parcial, todo iba a cuenta corriente y la plata que si
        # entro al cajon no aparecia en ningun lado.
        for _clave, _col in (("efectivo", "total_efectivo"),
                             ("tarjeta",  "total_tarjeta"),
                             ("qr",       "total_qr"),
                             ("cta_cte",  "total_cuenta_corriente")):
            _monto = float(_d.get(_clave, 0) or 0)
            if _monto:
                conn.execute(
                    f"UPDATE sesiones_caja SET {_col} = {_col} + ? WHERE id=?",
                    (_monto, sesion_id))

        conn.commit()
        return venta_id

    except Exception as e:
        conn.rollback()
        import logging
        logging.error(f"Error registrando venta: {e}")
        # El motivo NO se traga: "no se pudo registrar la venta" no le
        # sirve a nadie con un cliente esperando. Quien llama decide como
        # mostrarlo, pero tiene que saber que producto fallo.
        raise
    finally:
        conn.close()


def get_ventas_sesion(sesion_id) -> list:
    with get_connection() as conn:
        return [dict(r) for r in conn.execute("""
            SELECT v.id, v.fecha, v.total, v.metodo_pago,
                   v.descuento_pct, v.anulada, COUNT(d.id) as items
            FROM ventas v
            LEFT JOIN detalle_ventas d ON d.venta_id = v.id
            WHERE v.sesion_id = ?
            GROUP BY v.id ORDER BY v.fecha DESC
        """, (sesion_id,)).fetchall()]


def anular_venta(venta_id: int) -> bool:
    with get_connection() as conn:
        v = conn.execute("""
            SELECT anulada, sesion_id, total, metodo_pago, cliente_id,
                   monto_efectivo, monto_tarjeta, monto_qr, monto_cta_cte
            FROM ventas WHERE id=?
        """, (venta_id,)).fetchone()
        if not v or v["anulada"]:
            return False

        conn.execute("UPDATE ventas SET anulada=1 WHERE id=?", (venta_id,))

        # Se descuenta de la MISMA columna donde entro. Antes todo se
        # restaba de efectivo sin mirar como se habia pagado: anular una
        # venta de cuenta corriente dejaba el efectivo en negativo.
        _d = {"efectivo": v["monto_efectivo"] or 0,
              "tarjeta": v["monto_tarjeta"] or 0,
              "qr": v["monto_qr"] or 0,
              "cta_cte": v["monto_cta_cte"] or 0}
        if not any(_d.values()):
            # Venta vieja, anterior al desglose: se usa el metodo de pago
            _clave = {"efectivo": "efectivo", "tarjeta": "tarjeta",
                      "qr": "qr", "cuenta_corriente": "cta_cte",
                      "mixto": "efectivo"}.get(v["metodo_pago"], "efectivo")
            _d = {_clave: v["total"]}
        for _k, _col in (("efectivo", "total_efectivo"),
                         ("tarjeta", "total_tarjeta"),
                         ("qr", "total_qr"),
                         ("cta_cte", "total_cuenta_corriente")):
            if _d.get(_k):
                conn.execute(
                    f"UPDATE sesiones_caja SET {_col} = {_col} - ? WHERE id=?",
                    (_d[_k], v["sesion_id"]))

        # Lo que habia quedado fiado deja de deberse
        if _d.get("cta_cte") and v["cliente_id"]:
            conn.execute("""
                UPDATE cuentas_corrientes
                   SET saldo_actual = saldo_actual - ?
                 WHERE cliente_id = ?
            """, (_d["cta_cte"], v["cliente_id"]))
            conn.execute("""
                INSERT INTO movimientos_cuenta
                    (cliente_id, tipo, monto, concepto, venta_id)
                VALUES (?,'ajuste',?,?,?)
            """, (v["cliente_id"], -_d["cta_cte"],
                  f"Anulacion de la venta #{venta_id}", venta_id))

        items = conn.execute("""
            SELECT producto_id, cantidad FROM detalle_ventas WHERE venta_id=?
        """, (venta_id,)).fetchall()

        for item in items:
            conn.execute("""
                INSERT INTO lotes
                    (producto_id, cantidad, cantidad_restante,
                     costo_unitario, notas)
                SELECT ?, ?, ?, costo_ultimo,
                       'Devolucion venta #' || ?
                FROM productos WHERE id=?
            """, (item["producto_id"], item["cantidad"], item["cantidad"],
                  venta_id, item["producto_id"]))

        conn.commit()
        return True


# ─────────────────────────────────────────────────────────────────────────────
# DEVOLUCIONES
# ─────────────────────────────────────────────────────────────────────────────

def get_venta_para_devolver(venta_id: int) -> dict | None:
    """Venta + items con lo ya devuelto, para no permitir devolver de mas."""
    with get_connection() as conn:
        v = conn.execute("""
            SELECT v.*, c.nombre as cliente_nombre, c.dni as cliente_dni
            FROM ventas v LEFT JOIN clientes c ON c.id = v.cliente_id
            WHERE v.id = ?
        """, (venta_id,)).fetchone()
        if not v:
            return None
        venta = dict(v)
        venta["items"] = [dict(r) for r in conn.execute("""
            SELECT dv.id as detalle_id, dv.producto_id, dv.descripcion,
                   dv.cantidad, dv.precio_unitario, dv.subtotal,
                   COALESCE((SELECT SUM(dd.cantidad) FROM devoluciones_detalle dd
                              WHERE dd.detalle_venta_id = dv.id), 0) as ya_devuelto
            FROM detalle_ventas dv
            WHERE dv.venta_id = ?
            ORDER BY dv.id
        """, (venta_id,)).fetchall()]
        for it in venta["items"]:
            it["devolvible"] = it["cantidad"] - it["ya_devuelto"]
        return venta


def _reponer_stock_a_lotes_originales(conn, detalle_venta_id: int, cantidad: float):
    """Devuelve la mercaderia a los MISMOS lotes de los que salio.

    Es lo que preserva la rentabilidad: si se crea un lote nuevo con el
    costo de hoy, una devolucion de mercaderia comprada barata entra al
    inventario cara y ensucia el margen de todas las ventas siguientes.
    Se repone en orden inverso al consumo (ultimo lote tocado, primero).
    """
    restante = cantidad
    filas = conn.execute("""
        SELECT dvl.lote_id, dvl.cantidad
        FROM detalle_ventas_lotes dvl
        WHERE dvl.detalle_venta_id = ?
        ORDER BY dvl.id DESC
    """, (detalle_venta_id,)).fetchall()

    for f in filas:
        if restante <= 0:
            break
        devuelve = min(restante, f["cantidad"])
        conn.execute("""
            UPDATE lotes SET cantidad_restante = cantidad_restante + ?
            WHERE id = ?
        """, (devuelve, f["lote_id"]))
        restante -= devuelve

    if restante > 0:
        # Venta vieja sin trazabilidad de lotes: no hay a donde devolver.
        # Se crea uno al costo actual y se deja constancia de por que.
        prod = conn.execute("""
            SELECT p.id, p.costo_ultimo FROM detalle_ventas dv
            JOIN productos p ON p.id = dv.producto_id WHERE dv.id = ?
        """, (detalle_venta_id,)).fetchone()
        if prod:
            conn.execute("""
                INSERT INTO lotes (producto_id, cantidad, cantidad_restante,
                                   costo_unitario, notas)
                VALUES (?,?,?,?,?)
            """, (prod["id"], restante, restante, prod["costo_ultimo"] or 0,
                  "Devolucion sin lote de origen (venta anterior al detalle por lote)"))
    return cantidad - restante


def registrar_devolucion(venta_id: int, sesion_id: int, items: list,
                         motivo: str = "", metodo_reintegro: str = "efectivo",
                         autorizado_por: str = None) -> int | None:
    """Devolucion parcial o total.

    items: [{"detalle_id": int, "cantidad": float}]  — solo lo que vuelve.
    metodo_reintegro: 'efectivo' | 'cuenta_corriente' | 'sin_reintegro'

    Hace las cuatro cosas que tienen que pasar juntas o ninguna:
      1. repone stock a los lotes originales
      2. descuenta el monto del total de la sesion de caja
      3. deja el egreso asentado en movimientos_caja (para que cierre el arqueo)
      4. si fue a cuenta corriente, baja el saldo del cliente
    """
    if not items:
        return None
    conn = get_connection()
    try:
        v = conn.execute(
            "SELECT anulada, metodo_pago, cliente_id, descuento_pct "
            "FROM ventas WHERE id=?", (venta_id,)).fetchone()
        if not v or v["anulada"]:
            return None
        desc_pct = v["descuento_pct"] or 0.0

        cur = conn.execute("""
            INSERT INTO devoluciones
                (venta_id, sesion_id, total, motivo, metodo_reintegro, autorizado_por)
            VALUES (?,?,?,?,?,?)
        """, (venta_id, sesion_id, 0.0, motivo, metodo_reintegro, autorizado_por))
        dev_id = cur.lastrowid

        total = 0.0
        for it in items:
            det = conn.execute("""
                SELECT dv.id, dv.producto_id, dv.descripcion, dv.cantidad,
                       dv.precio_unitario,
                       COALESCE((SELECT SUM(dd.cantidad) FROM devoluciones_detalle dd
                                  WHERE dd.detalle_venta_id = dv.id), 0) as ya
                FROM detalle_ventas dv WHERE dv.id = ? AND dv.venta_id = ?
            """, (it["detalle_id"], venta_id)).fetchone()
            if not det:
                raise ValueError(f"El item {it['detalle_id']} no es de esta venta")

            cant = float(it["cantidad"])
            disponible = det["cantidad"] - det["ya"]
            if cant <= 0 or cant > disponible + 1e-9:
                raise ValueError(
                    f"{det['descripcion']}: se quieren devolver {cant} "
                    f"pero solo quedan {disponible} sin devolver")

            # El reintegro respeta el descuento que se aplico en la venta.
            monto = cant * det["precio_unitario"] * (1 - desc_pct / 100)
            total += monto

            conn.execute("""
                INSERT INTO devoluciones_detalle
                    (devolucion_id, detalle_venta_id, producto_id,
                     descripcion, cantidad, monto)
                VALUES (?,?,?,?,?,?)
            """, (dev_id, det["id"], det["producto_id"], det["descripcion"],
                  cant, monto))

            _reponer_stock_a_lotes_originales(conn, det["id"], cant)

        conn.execute("UPDATE devoluciones SET total=? WHERE id=?", (total, dev_id))

        if metodo_reintegro != "sin_reintegro":
            # Sale de donde se REINTEGRA, no de donde entro la venta: si
            # se devuelve en efectivo, el cajon pierde efectivo aunque la
            # compra original haya sido con tarjeta.
            col = {
                "efectivo":         "total_efectivo",
                "tarjeta":          "total_tarjeta",
                "qr":               "total_qr",
                "cuenta_corriente": "total_cuenta_corriente",
            }.get(metodo_reintegro, "total_efectivo")
            conn.execute(
                f"UPDATE sesiones_caja SET {col} = {col} - ? WHERE id=?",
                (total, sesion_id))

        if metodo_reintegro == "efectivo":
            conn.execute("""
                INSERT INTO movimientos_caja (sesion_id, tipo, monto, concepto)
                VALUES (?,'egreso',?,?)
            """, (sesion_id, total, f"Devolucion venta #{venta_id}"))

        elif metodo_reintegro == "cuenta_corriente":
            if not v["cliente_id"]:
                raise ValueError("La venta no tiene cliente: no se puede "
                                 "acreditar en cuenta corriente")
            conn.execute("""
                UPDATE cuentas_corrientes
                SET saldo_actual = saldo_actual - ?,
                    ultima_actualizacion = datetime('now','localtime')
                WHERE cliente_id = ?
            """, (total, v["cliente_id"]))
            conn.execute("""
                INSERT INTO movimientos_cuenta
                    (cliente_id, tipo, monto, venta_id, concepto, autorizado_por)
                VALUES (?,'pago',?,?,?,?)
            """, (v["cliente_id"], total, venta_id,
                  f"Devolucion venta #{venta_id}", autorizado_por))

        # Si se devolvio todo, la venta queda anulada.
        pendiente = conn.execute("""
            SELECT SUM(dv.cantidad) - COALESCE(SUM(
                (SELECT SUM(dd.cantidad) FROM devoluciones_detalle dd
                  WHERE dd.detalle_venta_id = dv.id)), 0)
            FROM detalle_ventas dv WHERE dv.venta_id = ?
        """, (venta_id,)).fetchone()[0]
        if pendiente is not None and pendiente <= 1e-9:
            conn.execute("UPDATE ventas SET anulada=1 WHERE id=?", (venta_id,))

        conn.commit()
        return dev_id

    except Exception as e:
        conn.rollback()
        logging.error(f"Error registrando devolucion de venta {venta_id}: {e}")
        raise
    finally:
        conn.close()


def efectivo_esperado(sesion_id: int) -> dict:
    """Cuanta plata TIENE que haber en el cajon ahora mismo.

    fondo inicial + ventas en efectivo + ingresos manuales - egresos.
    Las ventas con tarjeta, QR o cuenta corriente NO cuentan: no entra
    plata al cajon. Confundir el total de la sesion con el efectivo es
    el error clasico que hace parecer que falta plata todos los dias.
    """
    with get_connection() as conn:
        s = conn.execute("SELECT fondo_inicial, total_efectivo "
                         "FROM sesiones_caja WHERE id = ?", (sesion_id,)).fetchone()
        if not s:
            return {}
        movs = conn.execute("""
            SELECT COALESCE(SUM(CASE WHEN tipo='ingreso' THEN monto ELSE 0 END), 0),
                   COALESCE(SUM(CASE WHEN tipo='egreso'  THEN monto ELSE 0 END), 0)
            FROM movimientos_caja WHERE sesion_id = ?
        """, (sesion_id,)).fetchone()

    fondo = s["fondo_inicial"] or 0.0
    ventas = s["total_efectivo"] or 0.0
    ingresos, egresos = movs[0] or 0.0, movs[1] or 0.0
    return {
        "fondo_inicial": fondo,
        "ventas_efectivo": ventas,
        "ingresos_manuales": ingresos,
        "egresos": egresos,
        "esperado": round(fondo + ventas + ingresos - egresos, 2),
    }


def get_arqueos(desde=None, hasta=None, limit=60) -> list:
    """Historial de cierres con su diferencia, para ver si hay un patron."""
    cond, params = ["cerrada = 1"], []
    if desde:
        cond.append("date(cierre_en) >= date(?)"); params.append(desde)
    if hasta:
        cond.append("date(cierre_en) <= date(?)"); params.append(hasta)
    params.append(limit)
    with get_connection() as conn:
        return [dict(r) for r in conn.execute(f"""
            SELECT id, apertura_en, cierre_en, fondo_inicial, total_efectivo,
                   efectivo_contado, diferencia, arqueo_notas, notas
            FROM sesiones_caja
            WHERE {" AND ".join(cond)}
            ORDER BY cierre_en DESC LIMIT ?
        """, params).fetchall()]


def buscar_ventas(texto="", desde=None, hasta=None, solo_devolvibles=True,
                  limite=200) -> list:
    """Busca ventas para devolver, sin depender de la sesion abierta.

    texto matchea contra: numero de ticket, nombre o DNI del cliente, y
    descripcion de cualquier producto de la venta. Asi el cliente puede
    llegar con el ticket, con el nombre, o solo diciendo que se llevo.
    """
    cond, params = ["1=1"], []

    if solo_devolvibles:
        cond.append("v.anulada = 0")

    if desde:
        cond.append("date(v.fecha) >= date(?)"); params.append(desde)
    if hasta:
        cond.append("date(v.fecha) <= date(?)"); params.append(hasta)

    t = (texto or "").strip()
    if t:
        like = f"%{t}%"
        solo_num = t.lstrip("#").strip()
        sub = ["c.nombre LIKE ?", "c.dni LIKE ?",
               "EXISTS (SELECT 1 FROM detalle_ventas dx "
               "WHERE dx.venta_id = v.id AND dx.descripcion LIKE ?)"]
        params += [like, like, like]
        if solo_num.replace(".", "").isdigit():
            sub.append("v.id = ?"); params.append(int(float(solo_num)))
            # Tolerancia de $1: el cajero recuerda "cuatro mil cuatrocientos
            # cincuenta", no los centavos.
            sub.append("ABS(v.total - ?) <= 1.0"); params.append(float(solo_num))
        cond.append("(" + " OR ".join(sub) + ")")

    params.append(limite)
    with get_connection() as conn:
        ventas = [dict(r) for r in conn.execute(f"""
            SELECT v.id, v.fecha, v.total, v.metodo_pago, v.descuento_pct,
                   v.anulada, c.nombre as cliente_nombre,
                   (SELECT COUNT(*) FROM detalle_ventas dv WHERE dv.venta_id = v.id)
                       as items,
                   (SELECT GROUP_CONCAT(dv.descripcion, ' · ')
                      FROM detalle_ventas dv WHERE dv.venta_id = v.id)
                       as productos,
                   COALESCE((SELECT SUM(dd.cantidad) FROM devoluciones_detalle dd
                              JOIN detalle_ventas dv2 ON dv2.id = dd.detalle_venta_id
                             WHERE dv2.venta_id = v.id), 0) as unidades_devueltas,
                   (SELECT SUM(dv.cantidad) FROM detalle_ventas dv
                     WHERE dv.venta_id = v.id) as unidades
            FROM ventas v
            LEFT JOIN clientes c ON c.id = v.cliente_id
            WHERE {" AND ".join(cond)}
            ORDER BY v.fecha DESC
            LIMIT ?
        """, params).fetchall()]

    if solo_devolvibles:
        ventas = [v for v in ventas
                  if (v["unidades"] or 0) - (v["unidades_devueltas"] or 0) > 1e-9]
    return ventas


def get_devoluciones(desde=None, hasta=None, venta_id=None) -> list:
    cond, params = ["1=1"], []
    if venta_id:
        cond.append("d.venta_id = ?"); params.append(venta_id)
    if desde:
        cond.append("date(d.fecha) >= date(?)"); params.append(desde)
    if hasta:
        cond.append("date(d.fecha) <= date(?)"); params.append(hasta)
    with get_connection() as conn:
        return [dict(r) for r in conn.execute(f"""
            SELECT d.*, c.nombre as cliente_nombre,
                   (SELECT COUNT(*) FROM devoluciones_detalle dd
                     WHERE dd.devolucion_id = d.id) as items
            FROM devoluciones d
            LEFT JOIN ventas v ON v.id = d.venta_id
            LEFT JOIN clientes c ON c.id = v.cliente_id
            WHERE {" AND ".join(cond)}
            ORDER BY d.fecha DESC
        """, params).fetchall()]


# ─────────────────────────────────────────────────────────────────────────────
# CAJA
# ─────────────────────────────────────────────────────────────────────────────

def get_resumen_sesion(sesion_id) -> dict:
    with get_connection() as conn:
        sesion  = dict(conn.execute(
            "SELECT * FROM sesiones_caja WHERE id=?", (sesion_id,)
        ).fetchone())
        ventas  = dict(conn.execute("""
            SELECT COUNT(*) as cant, COALESCE(SUM(total),0) as total
            FROM ventas WHERE sesion_id=? AND anulada=0
        """, (sesion_id,)).fetchone())
        movs    = [dict(r) for r in conn.execute("""
            SELECT tipo, monto, concepto, fecha
            FROM movimientos_caja WHERE sesion_id=?
            ORDER BY fecha DESC
        """, (sesion_id,)).fetchall()]
    return {"sesion": sesion, "ventas": ventas, "movimientos": movs}


def registrar_movimiento(sesion_id, tipo, monto, concepto):
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO movimientos_caja (sesion_id, tipo, monto, concepto)
            VALUES (?,?,?,?)
        """, (sesion_id, tipo, monto, concepto))
        delta = monto if tipo == "ingreso" else -monto
        conn.execute("""
            UPDATE sesiones_caja SET total_efectivo = total_efectivo + ?
            WHERE id=?
        """, (delta, sesion_id))
        conn.commit()


def get_historial_sesiones(limit=30) -> list:
    with get_connection() as conn:
        return [dict(r) for r in conn.execute("""
            SELECT s.id, s.apertura_en, s.cierre_en, s.fondo_inicial,
                   s.total_efectivo, s.total_tarjeta,
                   s.total_qr, s.total_cuenta_corriente,
                   (s.total_efectivo + s.total_tarjeta +
                    s.total_qr + s.total_cuenta_corriente) as total_general,
                   COUNT(v.id) as cant_ventas, s.notas
            FROM sesiones_caja s
            LEFT JOIN ventas v ON v.sesion_id=s.id AND v.anulada=0
            WHERE s.cerrada=1
            GROUP BY s.id ORDER BY s.id DESC LIMIT ?
        """, (limit,)).fetchall()]


# ─────────────────────────────────────────────────────────────────────────────
# INFORMES
# ─────────────────────────────────────────────────────────────────────────────

def get_ventas_periodo(desde, hasta) -> dict:
    with get_connection() as conn:
        return dict(conn.execute("""
            SELECT COUNT(*) as cant,
                   COALESCE(SUM(total),0) as total,
                   COALESCE(AVG(total),0) as promedio
            FROM ventas
            WHERE date(fecha) BETWEEN ? AND ? AND anulada=0
        """, (desde, hasta)).fetchone())


def comparar_periodos(desde, hasta) -> dict:
    """El periodo elegido contra el anterior de la MISMA duracion.

    Un numero solo no dice nada: "vendi $2.400.000" puede ser bueno o
    malo. Y con inflacion, comparar solo pesos tampoco alcanza — por eso
    se comparan tambien las unidades y la cantidad de tickets, que no se
    inflan solos.
    """
    from datetime import datetime as _dt, timedelta
    d1 = _dt.strptime(desde, "%Y-%m-%d").date()
    d2 = _dt.strptime(hasta, "%Y-%m-%d").date()
    dias = (d2 - d1).days + 1
    ant_hasta = d1 - timedelta(days=1)
    ant_desde = ant_hasta - timedelta(days=dias - 1)

    def _medir(a, b):
        with get_connection() as conn:
            v = conn.execute("""
                SELECT COUNT(*) as tickets,
                       COALESCE(SUM(total), 0) as facturado,
                       COALESCE(AVG(total), 0) as ticket_prom
                FROM ventas
                WHERE date(fecha) BETWEEN ? AND ? AND anulada = 0
            """, (a.isoformat(), b.isoformat())).fetchone()
            u = conn.execute("""
                SELECT COALESCE(SUM(dv.cantidad), 0) as unidades,
                       COUNT(DISTINCT dv.producto_id) as productos
                FROM detalle_ventas dv
                JOIN ventas ve ON ve.id = dv.venta_id
                WHERE date(ve.fecha) BETWEEN ? AND ? AND ve.anulada = 0
            """, (a.isoformat(), b.isoformat())).fetchone()
        return {**dict(v), **dict(u), "desde": a.isoformat(), "hasta": b.isoformat()}

    act = _medir(d1, d2)
    ant = _medir(ant_desde, ant_hasta)

    def _var(clave):
        base = ant.get(clave) or 0
        nuevo = act.get(clave) or 0
        if not base:
            return None            # sin base no hay porcentaje que valga
        return (nuevo - base) / base * 100

    return {
        "dias": dias, "actual": act, "anterior": ant,
        "var": {k: _var(k) for k in
                ("tickets", "facturado", "ticket_prom", "unidades", "productos")},
    }


def get_ventas_por_hora(desde, hasta) -> list:
    """Ventas agrupadas por hora del dia.

    La hora ya se guarda en ventas.fecha desde siempre y nadie la usaba.
    Sirve para saber cuando hace falta gente en el mostrador y cuando
    conviene una promo para llenar los huecos.
    """
    with get_connection() as conn:
        filas = {int(r["h"]): dict(r) for r in conn.execute("""
            SELECT CAST(strftime('%H', fecha) AS INTEGER) as h,
                   COUNT(*) as tickets,
                   COALESCE(SUM(total), 0) as facturado
            FROM ventas
            WHERE date(fecha) BETWEEN ? AND ? AND anulada = 0
            GROUP BY h
        """, (desde, hasta)).fetchall()}
    # Todas las horas, incluso las vacias: los huecos son informacion
    return [filas.get(h, {"h": h, "tickets": 0, "facturado": 0.0})
            for h in range(24)]


def get_ventas_por_dia_semana(desde, hasta) -> list:
    """Ventas por dia de la semana. 0 = domingo en SQLite."""
    nombres = ["Domingo", "Lunes", "Martes", "Miercoles", "Jueves",
               "Viernes", "Sabado"]
    with get_connection() as conn:
        filas = {int(r["d"]): dict(r) for r in conn.execute("""
            SELECT CAST(strftime('%w', fecha) AS INTEGER) as d,
                   COUNT(*) as tickets,
                   COALESCE(SUM(total), 0) as facturado,
                   COUNT(DISTINCT date(fecha)) as dias_contados
            FROM ventas
            WHERE date(fecha) BETWEEN ? AND ? AND anulada = 0
            GROUP BY d
        """, (desde, hasta)).fetchall()}
    salida = []
    for d in range(7):
        f = filas.get(d, {"tickets": 0, "facturado": 0.0, "dias_contados": 0})
        n = f.get("dias_contados") or 0
        salida.append({
            "dia": nombres[d], "tickets": f["tickets"],
            "facturado": f["facturado"], "dias_contados": n,
            # Promedio por jornada: sin esto, un periodo con 5 lunes y 4
            # martes hace parecer que el lunes vende mas
            "promedio_dia": (f["facturado"] / n) if n else 0.0,
        })
    # Se muestra de lunes a domingo, que es como uno piensa la semana
    return salida[1:] + salida[:1]


def productos_que_se_venden_juntos(desde, hasta, minimo_tickets=5,
                                   limite=40) -> dict:
    """Que productos aparecen en el MISMO ticket.

    Sirve para tres cosas concretas: armar combos que ya se venden solos,
    ubicar la gondola, y saber que venta cruzada se pierde cuando falta
    uno de los dos.

    minimo_tickets: pares que aparecieron juntos menos veces que esto se
    descartan. Sin ese piso, dos tickets casuales parecen un patron.

    Devuelve {"pares": [...], "tickets": n, "confiable": bool}.
    """
    with get_connection() as conn:
        # Solo tickets con 2+ productos distintos: uno solo no dice nada
        filas = conn.execute("""
            SELECT dv.venta_id, dv.producto_id, p.descripcion
            FROM detalle_ventas dv
            JOIN ventas v ON v.id = dv.venta_id
            JOIN productos p ON p.id = dv.producto_id
            WHERE date(v.fecha) BETWEEN ? AND ? AND v.anulada = 0
        """, (desde, hasta)).fetchall()

    por_ticket = {}
    nombres = {}
    for r in filas:
        nombres[r["producto_id"]] = r["descripcion"]
        por_ticket.setdefault(r["venta_id"], set()).add(r["producto_id"])

    canastas = [s for s in por_ticket.values() if len(s) > 1]
    veces_solo = {}
    for pids in por_ticket.values():
        for pid in pids:
            veces_solo[pid] = veces_solo.get(pid, 0) + 1

    juntos = {}
    for pids in canastas:
        ordenados = sorted(pids)
        for i, a in enumerate(ordenados):
            for b in ordenados[i + 1:]:
                juntos[(a, b)] = juntos.get((a, b), 0) + 1

    pares = []
    for (a, b), n in juntos.items():
        if n < minimo_tickets:
            continue
        # Se informa en las DOS direcciones porque no son lo mismo:
        # "el que lleva pan lleva fiambre" puede ser 80% y al reves 30%.
        pares.append({
            "a": nombres.get(a, "?"), "b": nombres.get(b, "?"),
            "juntos": n,
            "veces_a": veces_solo.get(a, 0), "veces_b": veces_solo.get(b, 0),
            "pct_a": n / veces_solo[a] * 100 if veces_solo.get(a) else 0,
            "pct_b": n / veces_solo[b] * 100 if veces_solo.get(b) else 0,
        })
    pares.sort(key=lambda x: -x["juntos"])

    return {
        "pares": pares[:limite],
        "tickets": len(por_ticket),
        "canastas": len(canastas),
        # Con pocos tickets los porcentajes son ruido: se avisa en vez de
        # dejar que alguien decida sobre humo.
        "confiable": len(canastas) >= 100,
    }


def get_ventas_por_dia(desde, hasta) -> list:
    with get_connection() as conn:
        return [dict(r) for r in conn.execute("""
            SELECT date(fecha) as dia, COUNT(*) as cant,
                   COALESCE(SUM(total),0) as total
            FROM ventas
            WHERE date(fecha) BETWEEN ? AND ? AND anulada=0
            GROUP BY dia ORDER BY dia
        """, (desde, hasta)).fetchall()]


def get_ventas_por_metodo(desde, hasta) -> list:
    with get_connection() as conn:
        return [dict(r) for r in conn.execute("""
            SELECT metodo_pago, COUNT(*) as cant,
                   COALESCE(SUM(total),0) as total
            FROM ventas
            WHERE date(fecha) BETWEEN ? AND ? AND anulada=0
            GROUP BY metodo_pago ORDER BY total DESC
        """, (desde, hasta)).fetchall()]


def get_top_productos(desde, hasta, limit=20) -> list:
    with get_connection() as conn:
        return [dict(r) for r in conn.execute("""
            SELECT p.descripcion, p.codigo,
                   SUM(d.cantidad) as cant_vendida,
                   SUM(d.subtotal) as total_vendido
            FROM detalle_ventas d
            JOIN ventas v ON d.venta_id = v.id
            JOIN productos p ON d.producto_id = p.id
            WHERE date(v.fecha) BETWEEN ? AND ? AND v.anulada=0
            GROUP BY d.producto_id
            ORDER BY cant_vendida DESC LIMIT ?
        """, (desde, hasta, limit)).fetchall()]


def get_margen_por_categoria(desde, hasta) -> list:
    with get_connection() as conn:
        return [dict(r) for r in conn.execute("""
            SELECT c.nombre,
                   SUM(d.subtotal) as venta_total,
                   SUM(d.cantidad * p.costo_ultimo) as costo_total
            FROM detalle_ventas d
            JOIN ventas v ON d.venta_id = v.id
            JOIN productos p ON d.producto_id = p.id
            LEFT JOIN categorias c ON p.categoria_id = c.id
            WHERE date(v.fecha) BETWEEN ? AND ? AND v.anulada=0
            GROUP BY p.categoria_id ORDER BY venta_total DESC
        """, (desde, hasta)).fetchall()]


# ─────────────────────────────────────────────────────────────────────────────
# QUERIES ADICIONALES (migradas desde UI)
# ─────────────────────────────────────────────────────────────────────────────

def get_conteo_productos_por_categoria() -> dict:
    """Retorna {categoria_id: cantidad_productos}"""
    with get_connection() as conn:
        return {r[0]: r[1] for r in conn.execute("""
            SELECT categoria_id, COUNT(*) FROM productos
            WHERE activo=1 GROUP BY categoria_id
        """).fetchall()}


def get_categoria_por_id(cid: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM categorias WHERE id=?", (cid,)
        ).fetchone()
        return dict(row) if row else None


def get_producto_completo(pid: int) -> dict | None:
    """Producto con nombre de categoría incluido."""
    with get_connection() as conn:
        row = conn.execute("""
            SELECT p.*, c.nombre as cat_nombre
            FROM productos p
            LEFT JOIN categorias c ON p.categoria_id = c.id
            WHERE p.id=?
        """, (pid,)).fetchone()
        return dict(row) if row else None


def get_promocion_por_id(pid: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM promociones WHERE id=?", (pid,)
        ).fetchone()
        return dict(row) if row else None


def get_codigo_producto(pid: int) -> str | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT codigo FROM productos WHERE id=?", (pid,)
        ).fetchone()
        return row["codigo"] if row else None


def get_movimientos_sesion(sesion_id: int) -> list:
    with get_connection() as conn:
        return [dict(r) for r in conn.execute("""
            SELECT tipo, monto, concepto, fecha
            FROM movimientos_caja WHERE sesion_id=?
            ORDER BY fecha DESC
        """, (sesion_id,)).fetchall()]


# ─────────────────────────────────────────────────────────────────────────────
# FIADO — CLIENTES Y CUENTAS CORRIENTES
# ─────────────────────────────────────────────────────────────────────────────

def get_cliente_por_dni(dni: str) -> dict | None:
    """Busca cliente por DNI. Retorna dict con saldo incluido o None."""
    with get_connection() as conn:
        row = conn.execute("""
            SELECT c.*, COALESCE(cc.saldo_actual, 0) as saldo_actual
            FROM clientes c
            LEFT JOIN cuentas_corrientes cc ON cc.cliente_id = c.id
            WHERE c.dni = ? AND c.activo = 1
        """, (dni,)).fetchone()
        return dict(row) if row else None


def buscar_clientes_por_nombre(texto: str) -> list:
    """Busca clientes por coincidencia parcial de nombre (para cuando
    no se tiene el DNI a mano). Retorna lista con saldo incluido."""
    with get_connection() as conn:
        return [dict(r) for r in conn.execute("""
            SELECT c.*, COALESCE(cc.saldo_actual, 0) as saldo_actual
            FROM clientes c
            LEFT JOIN cuentas_corrientes cc ON cc.cliente_id = c.id
            WHERE c.activo = 1 AND c.nombre LIKE ?
            ORDER BY c.nombre LIMIT 20
        """, (f"%{texto.strip()}%",)).fetchall()]


def buscar_clientes(texto: str) -> list:
    """Busca clientes por nombre O por DNI, parcial en ambos casos.

    Sirve para el punto de venta, donde el cliente puede decir el nombre y
    no acordarse del DNI, o dictar solo los ultimos digitos. Ordena por
    nombre y limita a 20 para que la lista siga siendo elegible de un vistazo.
    """
    t = (texto or "").strip()
    if not t:
        return []
    solo_num = t.replace(".", "").replace("-", "").replace(" ", "")
    with get_connection() as conn:
        return [dict(r) for r in conn.execute("""
            SELECT c.*, COALESCE(cc.saldo_actual, 0) as saldo_actual
            FROM clientes c
            LEFT JOIN cuentas_corrientes cc ON cc.cliente_id = c.id
            WHERE c.activo = 1
              AND (c.nombre LIKE ? OR REPLACE(REPLACE(c.dni,'.',''),'-','') LIKE ?)
            ORDER BY c.nombre LIMIT 20
        """, (f"%{t}%", f"%{solo_num}%")).fetchall()]


def crear_cliente(dni, nombre, telefono, tope_credito) -> dict:
    """Crea cliente y su cuenta corriente. Retorna el cliente completo."""
    with get_connection() as conn:
        cur = conn.execute("""
            INSERT INTO clientes (dni, nombre, telefono, tope_credito)
            VALUES (?,?,?,?)
        """, (dni, nombre, telefono or None, tope_credito))
        cid = cur.lastrowid
        conn.execute(
            "INSERT INTO cuentas_corrientes (cliente_id, saldo_actual) VALUES (?,0)",
            (cid,))
        conn.commit()
    return get_cliente_por_dni(dni)


def actualizar_cliente(cid, nombre, telefono, tope_credito):
    with get_connection() as conn:
        conn.execute("""
            UPDATE clientes SET nombre=?, telefono=?, tope_credito=?
            WHERE id=?
        """, (nombre, telefono, tope_credito, cid))
        conn.commit()


def actualizar_saldo_cliente(cliente_id: int, monto: float,
                              tipo="cuenta_corriente", venta_id=None,
                              concepto=None, autorizado_por=None):
    """
    Actualiza el saldo de la cuenta corriente de un cliente.
    tipo='cuenta_corriente' suma al saldo (debe más).
    tipo='pago'  resta al saldo (pagó).
    """
    with get_connection() as conn:
        delta = monto if tipo == "cuenta_corriente" else -monto
        conn.execute("""
            UPDATE cuentas_corrientes
            SET saldo_actual = saldo_actual + ?,
                ultima_actualizacion = datetime('now','localtime')
            WHERE cliente_id = ?
        """, (delta, cliente_id))
        conn.execute("""
            INSERT INTO movimientos_cuenta
                (cliente_id, tipo, monto, venta_id, concepto, autorizado_por)
            VALUES (?,?,?,?,?,?)
        """, (cliente_id, tipo, monto, venta_id, concepto, autorizado_por))
        conn.commit()


def get_venta_completa(venta_id: int) -> dict | None:
    """Todo lo de un ticket: cabecera, items y como se pago.

    Es lo que hace falta para responder "¿que se llevo en esta venta?"
    tres dias despues, sin tener el ticket de papel.
    """
    with get_connection() as conn:
        v = conn.execute("""
            SELECT v.*, c.nombre as cliente, c.dni as cliente_dni
            FROM ventas v
            LEFT JOIN clientes c ON c.id = v.cliente_id
            WHERE v.id = ?
        """, (venta_id,)).fetchone()
        if not v:
            return None
        v = dict(v)
        v["items"] = [dict(r) for r in conn.execute("""
            SELECT dv.descripcion, dv.cantidad, dv.precio_unitario,
                   dv.subtotal, dv.promo_aplicada,
                   p.codigo, p.vendido_por_peso,
                   COALESCE((SELECT SUM(dvl.cantidad * l.costo_unitario)
                               FROM detalle_ventas_lotes dvl
                               JOIN lotes l ON l.id = dvl.lote_id
                              WHERE dvl.detalle_venta_id = dv.id), 0) as costo
            FROM detalle_ventas dv
            LEFT JOIN productos p ON p.id = dv.producto_id
            WHERE dv.venta_id = ?
            ORDER BY dv.id
        """, (venta_id,)).fetchall()]
        v["devoluciones"] = [dict(r) for r in conn.execute("""
            SELECT id, fecha, motivo, total, metodo_reintegro
            FROM devoluciones WHERE venta_id = ?
        """, (venta_id,)).fetchall()]
    v["costo_total"] = sum(i["costo"] or 0 for i in v["items"])
    v["ganancia"] = (v["total"] or 0) - v["costo_total"]
    return v


def buscar_tickets(desde=None, hasta=None, texto="", metodo=None,
                   incluir_anuladas=True, limite=300) -> list:
    """Tickets del periodo. texto busca por numero o por producto.

    Distinta de buscar_ventas(), que la usa el modulo de devoluciones con
    otra firma y otros filtros.
    """
    cond, params = ["1=1"], []
    if desde:
        cond.append("date(v.fecha) >= date(?)"); params.append(desde)
    if hasta:
        cond.append("date(v.fecha) <= date(?)"); params.append(hasta)
    if metodo:
        cond.append("v.metodo_pago = ?"); params.append(metodo)
    if not incluir_anuladas:
        cond.append("v.anulada = 0")
    if texto:
        t = texto.strip()
        if t.isdigit():
            cond.append("(v.id = ? OR EXISTS (SELECT 1 FROM detalle_ventas dv "
                        "WHERE dv.venta_id = v.id AND dv.descripcion LIKE ?))")
            params += [int(t), f"%{t}%"]
        else:
            cond.append("EXISTS (SELECT 1 FROM detalle_ventas dv "
                        "WHERE dv.venta_id = v.id AND dv.descripcion LIKE ?)")
            params.append(f"%{t}%")
    params.append(limite)
    with get_connection() as conn:
        return [dict(r) for r in conn.execute(f"""
            SELECT v.id, v.fecha, v.total, v.metodo_pago, v.anulada,
                   v.descuento_pct, v.cliente_id,
                   v.monto_efectivo, v.monto_tarjeta, v.monto_qr,
                   v.monto_cta_cte,
                   c.nombre as cliente,
                   (SELECT COUNT(*) FROM detalle_ventas dv
                     WHERE dv.venta_id = v.id) as items,
                   (SELECT GROUP_CONCAT(dv.descripcion, ', ')
                      FROM detalle_ventas dv WHERE dv.venta_id = v.id) as productos
            FROM ventas v
            LEFT JOIN clientes c ON c.id = v.cliente_id
            WHERE {" AND ".join(cond)}
            ORDER BY v.fecha DESC, v.id DESC
            LIMIT ?
        """, params).fetchall()]


def get_detalle_venta(venta_id: int) -> list:
    """Productos comprados en una venta puntual — para justificar un
    cargo de cuenta corriente mostrando qué se llevó el cliente."""
    with get_connection() as conn:
        return [dict(r) for r in conn.execute("""
            SELECT descripcion, cantidad, precio_unitario, subtotal, promo_aplicada
            FROM detalle_ventas
            WHERE venta_id = ?
            ORDER BY id
        """, (venta_id,)).fetchall()]


def get_movimientos_cliente(cliente_id: int) -> list:
    with get_connection() as conn:
        return [dict(r) for r in conn.execute("""
            SELECT tipo, monto, concepto, autorizado_por, fecha, venta_id
            FROM movimientos_cuenta
            WHERE cliente_id = ?
            ORDER BY fecha DESC
        """, (cliente_id,)).fetchall()]


def get_todos_clientes() -> list:
    with get_connection() as conn:
        return [dict(r) for r in conn.execute("""
            SELECT c.id, c.dni, c.nombre, c.telefono, c.tope_credito,
                   COALESCE(cc.saldo_actual, 0) as saldo_actual,
                   (c.tope_credito - COALESCE(cc.saldo_actual, 0)) as disponible
            FROM clientes c
            LEFT JOIN cuentas_corrientes cc ON cc.cliente_id = c.id
            WHERE c.activo = 1
            ORDER BY c.nombre
        """).fetchall()]


def registrar_pago_cuenta_corriente(cliente_id: int, monto: float, autorizado_por: str):
    """Registra un pago parcial o total de la deuda."""
    actualizar_saldo_cliente(
        cliente_id, monto,
        tipo="pago",
        concepto="Pago de deuda",
        autorizado_por=autorizado_por
    )


# ─────────────────────────────────────────────────────────────────────────────
# RENTABILIDAD
# ─────────────────────────────────────────────────────────────────────────────

def get_rentabilidad_productos(desde, hasta) -> list:
    """
    Rentabilidad real por producto en el período.
    Cruza detalle_ventas con detalle_ventas_lotes para obtener
    el costo real por unidad vendida de cada lote.
    """
    with get_connection() as conn:
        return [dict(r) for r in conn.execute("""
            SELECT
                p.descripcion,
                p.codigo,
                c.nombre as categoria,
                p.id                                      as producto_id,
                SUM(dv.cantidad)                          as unidades,
                SUM(dv.subtotal)                          as ingreso_total,
                SUM(dvl.cantidad * l.costo_unitario)      as costo_total,
                SUM(dv.subtotal)
                    - SUM(dvl.cantidad * l.costo_unitario) as ganancia,
                -- Margen real SOBRE COSTO: misma base que margen_pct y que el
                -- teorico, para que las dos columnas sean comparables.
                ROUND(
                    (SUM(dv.subtotal)
                        - SUM(dvl.cantidad * l.costo_unitario))
                    / NULLIF(SUM(dvl.cantidad * l.costo_unitario), 0) * 100
                , 1)                                      as margen_real_pct,
                -- Margen SOBRE VENTA: que porcion de cada peso facturado queda.
                -- Es la base correcta para restar IIBB y comisiones, que se
                -- calculan sobre la venta y no sobre el costo.
                ROUND(
                    (SUM(dv.subtotal)
                        - SUM(dvl.cantidad * l.costo_unitario))
                    / NULLIF(SUM(dv.subtotal), 0) * 100
                , 1)                                      as margen_venta_pct,
                ROUND(
                    (p.precio_base - p.costo_ultimo)
                    / NULLIF(p.costo_ultimo, 0) * 100
                , 1)                                      as margen_teorico_pct
            FROM detalle_ventas dv
            JOIN ventas v          ON dv.venta_id     = v.id
            JOIN productos p       ON dv.producto_id  = p.id
            LEFT JOIN categorias c ON p.categoria_id  = c.id
            LEFT JOIN detalle_ventas_lotes dvl ON dvl.detalle_venta_id = dv.id
            LEFT JOIN lotes l      ON dvl.lote_id     = l.id
            WHERE date(v.fecha) BETWEEN ? AND ? AND v.anulada = 0
            GROUP BY dv.producto_id
            ORDER BY ganancia DESC
        """, (desde, hasta)).fetchall()]


def get_rentabilidad_lotes(desde, hasta) -> list:
    """
    Rentabilidad real por lote en el período.
    Muestra cuánto se vendió de cada lote y cuánto quedó sin vender.
    """
    with get_connection() as conn:
        return [dict(r) for r in conn.execute("""
            SELECT
                l.id                                        as lote_id,
                p.descripcion,
                p.codigo,
                pv.nombre                                   as proveedor,
                l.tipo,
                l.motivo_ajuste,
                l.fecha_ingreso,
                l.fecha_vencimiento,
                l.cantidad                                  as cantidad_ingresada,
                l.cantidad_restante                         as cantidad_disponible,
                l.costo_unitario,
                COALESCE(SUM(dvl.cantidad), 0)              as unidades_vendidas,
                ROUND(l.cantidad - l.cantidad_restante
                    - COALESCE(SUM(dvl.cantidad), 0), 3)    as cantidad_ajustada,
                COALESCE(SUM(dvl.cantidad * dv.precio_unitario), 0) as ingreso_lote,
                COALESCE(SUM(dvl.cantidad * l.costo_unitario), 0)   as costo_vendido,
                COALESCE(SUM(dvl.cantidad * dv.precio_unitario), 0)
                    - COALESCE(SUM(dvl.cantidad * l.costo_unitario), 0) as ganancia_lote,
                ROUND(
                    (COALESCE(SUM(dvl.cantidad * dv.precio_unitario), 0)
                        - COALESCE(SUM(dvl.cantidad * l.costo_unitario), 0))
                    / NULLIF(SUM(dvl.cantidad * dv.precio_unitario), 1) * 100
                , 1)                                        as margen_pct
            FROM lotes l
            JOIN productos p           ON l.producto_id   = p.id
            LEFT JOIN proveedores pv   ON l.proveedor_id  = pv.id
            LEFT JOIN detalle_ventas_lotes dvl ON dvl.lote_id = l.id
            LEFT JOIN detalle_ventas dv ON dvl.detalle_venta_id = dv.id
            LEFT JOIN ventas v         ON dv.venta_id = v.id
                AND date(v.fecha) BETWEEN ? AND ?
                AND v.anulada = 0
            WHERE date(l.fecha_ingreso) <= ?
            GROUP BY l.id
            ORDER BY l.fecha_ingreso DESC
        """, (desde, hasta, hasta)).fetchall()]


def eliminar_producto_si_posible(pid: int) -> tuple[bool, str]:
    """
    Intenta eliminar un producto físicamente.
    - Si tiene ventas históricas → no se puede, retorna (False, motivo)
    - Si tiene stock restante → advierte pero permite si el usuario confirmó
    - Si no tiene nada → elimina todo (producto + lotes + promociones)
    Retorna (exito, mensaje)
    """
    with get_connection() as conn:
        # Verificar ventas históricas
        ventas = conn.execute("""
            SELECT COUNT(*) as n FROM detalle_ventas
            WHERE producto_id = ?
        """, (pid,)).fetchone()["n"]

        if ventas > 0:
            return False, (f"El producto tiene {ventas} ventas registradas en el historial.\n"
                           "No se puede eliminar para preservar los informes.")

        # Verificar stock restante
        stock = conn.execute("""
            SELECT COALESCE(SUM(cantidad_restante), 0) as s FROM lotes
            WHERE producto_id = ?
        """, (pid,)).fetchone()["s"]

        if stock > 0:
            return False, (f"El producto tiene {stock:.0f} unidades en stock.\n"
                           "Primero ajusta el stock a cero.")

        # Sin historial ni stock — eliminar
        conn.execute("DELETE FROM promociones WHERE producto_id=?", (pid,))
        conn.execute("DELETE FROM lotes WHERE producto_id=?", (pid,))
        conn.execute("DELETE FROM productos WHERE id=?", (pid,))
        conn.commit()
        return True, "Producto eliminado."


# ─────────────────────────────────────────────────────────────────────────────
# VENDEDORES (comisiones sobre el catálogo web)
# ─────────────────────────────────────────────────────────────────────────────

def hash_password(texto_plano: str) -> str:
    """
    SHA-256 en hex. Nunca se guarda ni se manda una contraseña en
    texto plano — ni acá, ni al sincronizar al Sheet, ni en el login
    del panel del vendedor (que hashea del mismo modo y compara).
    """
    return hashlib.sha256(texto_plano.encode("utf-8")).hexdigest()


def get_vendedores() -> list:
    with get_connection() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM vendedores ORDER BY activo DESC, nombre"
        ).fetchall()]


def get_vendedor_por_id(vid: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM vendedores WHERE id=?", (vid,)).fetchone()
        return dict(row) if row else None


def productos_para_vendedor(productos: list, vendedor_id) -> tuple[list, float]:
    """Adapta una lista de productos al precio y al surtido de un vendedor.

    Devuelve (productos_ajustados, comision_pct).

    - Si el vendedor tiene categorias asignadas, filtra a esas.
    - Si su modo_comision es "recargo", suma costo x comision% al
      precio_base y deja el recargo por unidad en la clave "_recargo",
      para que las promos de precio fijo tambien lo incluyan.
    - Si es "descuento", los precios quedan como estan: el cliente paga
      lo mismo y la comision sale del margen del negocio.

    vendedor_id None devuelve la lista intacta (lista general).
    """
    if not vendedor_id:
        return list(productos), 0.0

    with get_connection() as conn:
        v = conn.execute("SELECT * FROM vendedores WHERE id=?",
                         (vendedor_id,)).fetchone()
    if not v:
        return list(productos), 0.0
    v = dict(v)

    permitidas = set(get_categorias_vendedor(vendedor_id))
    if permitidas:
        nombres = {c["nombre"] for c in get_categorias() if c["id"] in permitidas}
        productos = [p for p in productos if (p.get("categoria") or "") in nombres]

    comision = float(v.get("comision_pct") or 0)
    recarga = str(v.get("modo_comision") or "recargo").lower() == "recargo"

    salida = []
    for p in productos:
        q = dict(p)
        recargo = (float(q.get("costo_ultimo") or 0) * comision / 100) if recarga else 0.0
        if recargo:
            q["precio_base"] = round(float(q.get("precio_base") or 0) + recargo, 2)
        q["_recargo"] = recargo
        salida.append(q)
    return salida, comision


# ─────────────────────────────────────────────────────────────────────────────
# COLA DE REVISION — lista de trabajo de productos
# ─────────────────────────────────────────────────────────────────────────────

MOTIVOS_REVISION = ("Precio", "Costo", "Categoria", "Foto", "Descripcion",
                    "Stock", "Otro")


def marcar_para_revisar(producto_ids, motivo="Otro", notas="") -> int:
    """Agrega productos a la cola. Si ya estaban, los vuelve a pendiente.

    Devuelve cuantos quedaron pendientes.
    """
    ids = [producto_ids] if isinstance(producto_ids, int) else list(producto_ids)
    if not ids:
        return 0
    with get_connection() as conn:
        for pid in ids:
            conn.execute("""
                INSERT INTO revision_productos (producto_id, estado, motivo, notas)
                VALUES (?, 'pendiente', ?, ?)
                ON CONFLICT(producto_id) DO UPDATE SET
                    estado = 'pendiente',
                    motivo = excluded.motivo,
                    notas = excluded.notas,
                    creado_en = datetime('now','localtime'),
                    revisado_en = NULL
            """, (int(pid), motivo, notas))
        conn.commit()
    return len(ids)


def cambiar_estado_revision(producto_ids, estado, notas=None):
    """estado: 'pendiente' | 'revisado' | 'descartado'."""
    ids = [producto_ids] if isinstance(producto_ids, int) else list(producto_ids)
    if not ids:
        return
    with get_connection() as conn:
        for pid in ids:
            conn.execute("""
                UPDATE revision_productos
                SET estado = ?,
                    revisado_en = CASE WHEN ? = 'pendiente' THEN NULL
                                       ELSE datetime('now','localtime') END,
                    notas = COALESCE(?, notas)
                WHERE producto_id = ?
            """, (estado, estado, notas, int(pid)))
        conn.commit()


def quitar_de_revision(producto_ids):
    ids = [producto_ids] if isinstance(producto_ids, int) else list(producto_ids)
    with get_connection() as conn:
        for pid in ids:
            conn.execute("DELETE FROM revision_productos WHERE producto_id = ?",
                         (int(pid),))
        conn.commit()


# ─────────────────────────────────────────────────────────────────────────────
# LISTAS GUARDADAS — selecciones que se reusan
# ─────────────────────────────────────────────────────────────────────────────

def guardar_lista(nombre, producto_ids, titulo="", por_categoria=True) -> int:
    """Crea o pisa una lista con ese nombre.

    Se guardan los IDS, no los precios: al volver a imprimirla toma los
    precios de hoy. Guardar los precios obligaria a actualizarlos a mano
    y la lista quedaria mintiendo.
    """
    nombre = nombre.strip()
    if not nombre:
        raise ValueError("La lista necesita un nombre.")
    with get_connection() as conn:
        fila = conn.execute("SELECT id FROM listas_guardadas WHERE nombre = ?",
                            (nombre,)).fetchone()
        if fila:
            lid = fila["id"]
            conn.execute("""UPDATE listas_guardadas
                            SET titulo = ?, por_categoria = ?
                            WHERE id = ?""",
                         (titulo or None, int(bool(por_categoria)), lid))
            conn.execute("DELETE FROM lista_items WHERE lista_id = ?", (lid,))
        else:
            cur = conn.execute("""
                INSERT INTO listas_guardadas (nombre, titulo, por_categoria)
                VALUES (?,?,?)
            """, (nombre, titulo or None, int(bool(por_categoria))))
            lid = cur.lastrowid
        for pid in producto_ids:
            conn.execute("INSERT OR IGNORE INTO lista_items (lista_id, "
                         "producto_id) VALUES (?,?)", (lid, int(pid)))
        conn.commit()
    return lid


def agregar_linea_manual(lista_id, texto, precio_texto, categoria="") -> int:
    """Una linea escrita a mano dentro de una lista guardada.

    El precio va como TEXTO, no como numero: la gracia es poder escribir
    "$ 2.000 x 100g" o "2x1", que no son un importe.
    """
    with get_connection() as conn:
        cur = conn.execute("""
            INSERT INTO lista_manual (lista_id, texto, precio_texto, categoria)
            VALUES (?,?,?,?)
        """, (lista_id, texto.strip(), precio_texto.strip(),
              (categoria or "").strip() or None))
        conn.commit()
        return cur.lastrowid


def get_lineas_manuales(lista_id) -> list:
    with get_connection() as conn:
        return [dict(r) for r in conn.execute("""
            SELECT * FROM lista_manual WHERE lista_id = ?
            ORDER BY categoria IS NULL, categoria, orden, id
        """, (lista_id,)).fetchall()]


def borrar_linea_manual(linea_id):
    with get_connection() as conn:
        conn.execute("DELETE FROM lista_manual WHERE id = ?", (linea_id,))
        conn.commit()


def get_listas_guardadas() -> list:
    with get_connection() as conn:
        return [dict(r) for r in conn.execute("""
            SELECT l.*,
                   (SELECT COUNT(*) FROM lista_items i
                     WHERE i.lista_id = l.id) as items
            FROM listas_guardadas l
            ORDER BY l.usado_en IS NULL, l.usado_en DESC, l.nombre
        """).fetchall()]


def get_lista(lista_id) -> dict | None:
    """La lista con sus productos, ya con los precios de HOY."""
    with get_connection() as conn:
        cab = conn.execute("SELECT * FROM listas_guardadas WHERE id = ?",
                           (lista_id,)).fetchone()
        if not cab:
            return None
        cab = dict(cab)
        cab["productos"] = [dict(r) for r in conn.execute("""
            SELECT p.*, c.nombre as categoria,
                   COALESCE((SELECT SUM(l.cantidad_restante) FROM lotes l
                              WHERE l.producto_id = p.id), 0) as stock
            FROM lista_items i
            JOIN productos p ON p.id = i.producto_id
            LEFT JOIN categorias c ON c.id = p.categoria_id
            WHERE i.lista_id = ? AND COALESCE(p.activo, 1) = 1
            ORDER BY c.nombre, p.descripcion
        """, (lista_id,)).fetchall()]
        cab["manuales"] = [dict(r) for r in conn.execute("""
            SELECT * FROM lista_manual WHERE lista_id = ?
            ORDER BY categoria IS NULL, categoria, orden, id
        """, (lista_id,)).fetchall()]
    return cab


def marcar_lista_usada(lista_id):
    with get_connection() as conn:
        conn.execute("""UPDATE listas_guardadas
                        SET usado_en = datetime('now','localtime')
                        WHERE id = ?""", (lista_id,))
        conn.commit()


def borrar_lista(lista_id):
    with get_connection() as conn:
        conn.execute("DELETE FROM listas_guardadas WHERE id = ?", (lista_id,))
        conn.commit()


# ─────────────────────────────────────────────────────────────────────────────
# LISTA DE COMPRAS — lo que hay que comprar y no sale de la reposicion
# ─────────────────────────────────────────────────────────────────────────────

def agregar_a_comprar(texto, cantidad="", proveedor="", nota="") -> dict:
    """Anota un pedido. Si ya estaba, suma una marca en vez de duplicar.

    Lo que importa de un producto que no se vende todavia es cuantas
    personas lo pidieron: tres pedidos distintos justifican traerlo, uno
    solo puede ser un capricho. Con lineas repetidas eso no se ve.
    """
    texto = texto.strip()
    with get_connection() as conn:
        # Se busca sin distinguir mayusculas ni acentos de mas
        ya = conn.execute("""
            SELECT id, pedidos FROM lista_compras
            WHERE comprado = 0 AND LOWER(TRIM(texto)) = LOWER(TRIM(?))
        """, (texto,)).fetchone()
        if ya:
            n = (ya["pedidos"] or 1) + 1
            conn.execute("""
                UPDATE lista_compras
                   SET pedidos = ?,
                       ultimo_pedido = datetime('now','localtime'),
                       nota = COALESCE(NULLIF(?, ''), nota),
                       proveedor = COALESCE(proveedor, NULLIF(?, ''))
                 WHERE id = ?
            """, (n, (nota or "").strip(), (proveedor or "").strip(), ya["id"]))
            conn.commit()
            return {"id": ya["id"], "pedidos": n, "repetido": True}

        cur = conn.execute("""
            INSERT INTO lista_compras
                (texto, cantidad, proveedor, nota, pedidos, ultimo_pedido)
            VALUES (?,?,?,?,1,datetime('now','localtime'))
        """, (texto, (cantidad or "").strip() or None,
              (proveedor or "").strip() or None, (nota or "").strip() or None))
        conn.commit()
        return {"id": cur.lastrowid, "pedidos": 1, "repetido": False}


def get_lista_compras(incluir_comprados=False) -> list:
    """Los pedidos, primero los más pedidos: son los que más urgen."""
    cond = "" if incluir_comprados else "WHERE comprado = 0"
    with get_connection() as conn:
        return [dict(r) for r in conn.execute(f"""
            SELECT *, COALESCE(pedidos, 1) as veces
            FROM lista_compras {cond}
            ORDER BY comprado, COALESCE(pedidos,1) DESC, creado_en
        """).fetchall()]


def marcar_comprado(ids, comprado=True):
    ids = [ids] if isinstance(ids, int) else list(ids)
    if not ids:
        return
    marcas = ",".join("?" * len(ids))
    with get_connection() as conn:
        conn.execute(f"""
            UPDATE lista_compras
               SET comprado = ?,
                   comprado_en = CASE WHEN ? = 1
                                      THEN datetime('now','localtime')
                                      ELSE NULL END
             WHERE id IN ({marcas})
        """, [int(bool(comprado)), int(bool(comprado))] + ids)
        conn.commit()


def borrar_de_compras(ids):
    ids = [ids] if isinstance(ids, int) else list(ids)
    if not ids:
        return
    with get_connection() as conn:
        conn.execute("DELETE FROM lista_compras WHERE id IN (%s)"
                     % ",".join("?" * len(ids)), ids)
        conn.commit()


def limpiar_comprados() -> int:
    """Saca de la lista lo ya comprado. Devuelve cuantos se borraron."""
    with get_connection() as conn:
        n = conn.execute("DELETE FROM lista_compras WHERE comprado = 1").rowcount
        conn.commit()
        return n


def _anotar_cambio_precio(conn, producto_id, precio_nuevo, motivo=""):
    """Deja constancia del cambio si el precio realmente cambio.

    Se llama con la conexion abierta de quien esta escribiendo, para que
    entre en la misma transaccion: si la actualizacion falla, el
    historial no queda mintiendo.
    """
    try:
        viejo = conn.execute(
            "SELECT precio_base FROM productos WHERE id = ?",
            (producto_id,)).fetchone()
        viejo = float(viejo["precio_base"] or 0) if viejo else 0.0
        if abs(float(precio_nuevo) - viejo) < 0.005:
            return                      # no cambio: no se anota
        conn.execute("""
            INSERT INTO historial_precios
                (producto_id, precio_viejo, precio_nuevo, motivo)
            VALUES (?,?,?,?)
        """, (producto_id, viejo, float(precio_nuevo), motivo or None))
    except Exception as e:
        logging.debug(f"No se pudo anotar el cambio de precio: {e}")


def marcar_etiquetas_impresas(producto_ids):
    """Deja constancia de que se imprimio la etiqueta de esos productos."""
    ids = list(producto_ids)
    if not ids:
        return
    with get_connection() as conn:
        conn.execute("""
            UPDATE productos
               SET etiqueta_impresa = datetime('now','localtime')
             WHERE id IN (%s)
        """ % ",".join("?" * len(ids)), ids)
        conn.commit()


def etiquetas_pendientes(desde=None, hasta=None, incluir_nuevos=True,
                         incluir_cambios=True) -> list:
    """Qué etiquetas de góndola hay que imprimir.

    Junta las dos razones por las que una etiqueta queda desactualizada:
    el producto es nuevo y nunca tuvo, o le cambió el precio. Son la
    misma tarea — imprimir y salir a pegar — y separarlas obliga a
    recorrer la góndola dos veces.
    """
    salida = []

    if incluir_cambios:
        for c in precios_cambiados(desde, hasta):
            c["motivo_etiqueta"] = "cambió de precio"
            c["es_nuevo"] = False
            salida.append(c)

    if incluir_nuevos:
        # "Nuevo" = nunca se le imprimio la etiqueta. La fecha de alta se
        # usa solo como filtro de periodo, pero un producto cargado hace
        # meses que nunca se etiqueto sigue estando pendiente.
        cond = ["COALESCE(p.activo, 1) = 1", "p.etiqueta_impresa IS NULL"]
        params = []
        if desde:
            cond.append("date(p.creado_en) >= date(?)"); params.append(desde)
        if hasta:
            cond.append("date(p.creado_en) <= date(?)"); params.append(hasta)
        with get_connection() as conn:
            nuevos = [dict(r) for r in conn.execute(f"""
                SELECT p.id as producto_id, p.descripcion, p.codigo,
                       p.precio_base, p.categoria_id, p.creado_en as fecha,
                       c.nombre as categoria
                FROM productos p
                LEFT JOIN categorias c ON c.id = p.categoria_id
                WHERE {" AND ".join(cond)}
                ORDER BY p.creado_en DESC
            """, params).fetchall()]
        # Un producto nuevo que ademas cambio de precio aparece una vez:
        # la etiqueta es una sola.
        ya = {x["producto_id"] for x in salida}
        for n in nuevos:
            if n["producto_id"] in ya:
                continue
            n["precio_viejo"] = None
            n["precio_nuevo"] = n["precio_base"]
            n["variacion_pct"] = None
            n["motivo_etiqueta"] = "producto nuevo"
            n["es_nuevo"] = True
            salida.append(n)

    salida.sort(key=lambda x: (x.get("fecha") or ""), reverse=True)
    return salida


def precios_cambiados(desde=None, hasta=None, solo_ultimo=True) -> list:
    """Productos que cambiaron de precio en el periodo.

    Es la lista de etiquetas a reimprimir: si el precio de gondola no
    coincide con el de la caja, el cliente lo nota antes que uno.

    solo_ultimo: un producto que cambio tres veces aparece una sola vez,
    con el precio final. Para reimprimir importa el actual, no cada paso.
    """
    cond, params = ["1=1"], []
    if desde:
        cond.append("date(h.fecha) >= date(?)"); params.append(desde)
    if hasta:
        cond.append("date(h.fecha) <= date(?)"); params.append(hasta)

    with get_connection() as conn:
        filas = [dict(r) for r in conn.execute(f"""
            SELECT h.id, h.producto_id, h.precio_viejo, h.precio_nuevo,
                   h.motivo, h.fecha,
                   p.descripcion, p.codigo, p.precio_base, p.categoria_id,
                   c.nombre as categoria,
                   COALESCE(p.activo, 1) as activo
            FROM historial_precios h
            JOIN productos p ON p.id = h.producto_id
            LEFT JOIN categorias c ON c.id = p.categoria_id
            WHERE {" AND ".join(cond)}
            ORDER BY h.fecha DESC, h.id DESC
        """, params).fetchall()]

    if not solo_ultimo:
        return filas
    vistos, out = set(), []
    for f in filas:
        if f["producto_id"] in vistos:
            continue
        vistos.add(f["producto_id"])
        f["variacion_pct"] = (
            (f["precio_nuevo"] - f["precio_viejo"]) / f["precio_viejo"] * 100
            if f["precio_viejo"] else None)
        out.append(f)
    return out


def set_precio_base(producto_id: int, precio: float):
    """Cambia solo el precio de venta. No toca costo ni margen."""
    precio = redondear_precio(precio)
    with get_connection() as conn:
        _anotar_cambio_precio(conn, producto_id, precio)
        conn.execute("""UPDATE productos SET precio_base = ?,
                        modificado_en = datetime('now','localtime')
                        WHERE id = ?""", (float(precio), int(producto_id)))
        conn.commit()


def get_productos_revision(estado=None, categoria_id=None, filtro="") -> list:
    """TODOS los productos con su estado de revision.

    Los que nunca se tocaron figuran como 'sin revisar': la revision es
    un recorrido completo del catalogo, no una lista aparte. Lo que uno
    necesita saber es por donde va, no que aparto.
    """
    cond, params = ["COALESCE(p.activo, 1) = 1"], []
    if filtro:
        cond.append("(p.descripcion LIKE ? OR p.codigo LIKE ? OR p.marca LIKE ?)")
        like = f"%{filtro}%"
        params += [like, like, like]
    if categoria_id:
        cond.append("p.categoria_id = ?"); params.append(categoria_id)
    if estado == "sin_revisar":
        cond.append("(r.estado IS NULL OR r.estado = 'pendiente')")
    elif estado == "revisado":
        cond.append("r.estado = 'revisado'")

    with get_connection() as conn:
        return [dict(x) for x in conn.execute(f"""
            SELECT p.id as producto_id, p.codigo, p.descripcion, p.marca,
                   p.precio_base, p.costo_ultimo, p.categoria_id,
                   c.nombre as categoria,
                   COALESCE(r.estado, 'sin revisar') as estado,
                   r.notas, r.revisado_en,
                   (SELECT COALESCE(SUM(cantidad_restante), 0) FROM lotes l
                     WHERE l.producto_id = p.id) as stock
            FROM productos p
            LEFT JOIN categorias c ON c.id = p.categoria_id
            LEFT JOIN revision_productos r ON r.producto_id = p.id
            WHERE {" AND ".join(cond)}
            ORDER BY c.nombre, p.descripcion
        """, params).fetchall()]


def progreso_revision() -> dict:
    """Cuantos del catalogo activo ya se revisaron."""
    with get_connection() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM productos WHERE COALESCE(activo,1)=1"
        ).fetchone()[0]
        hechos = conn.execute("""
            SELECT COUNT(*) FROM revision_productos r
            JOIN productos p ON p.id = r.producto_id
            WHERE r.estado = 'revisado' AND COALESCE(p.activo,1)=1
        """).fetchone()[0]
    return {"total": total, "revisados": hechos,
            "pendientes": total - hechos,
            "pct": (hechos / total * 100) if total else 0.0}


def reiniciar_revision(categoria_id=None) -> int:
    """Arranca una revision nueva. Devuelve cuantos volvieron a pendiente.

    categoria_id acota el reinicio a un rubro: lo normal es revisar por
    sector y querer repasar solo ese, no perder el avance de todo el
    catalogo.
    """
    with get_connection() as conn:
        if categoria_id:
            n = conn.execute("""
                DELETE FROM revision_productos
                WHERE producto_id IN (SELECT id FROM productos
                                       WHERE categoria_id = ?)
            """, (categoria_id,)).rowcount
        else:
            n = conn.execute("DELETE FROM revision_productos").rowcount
        conn.commit()
    return n


def get_revision(estado=None) -> list:
    """Cola de revision con los datos del producto para poder decidir."""
    cond, params = ["1=1"], []
    if estado:
        cond.append("r.estado = ?"); params.append(estado)
    with get_connection() as conn:
        return [dict(x) for x in conn.execute(f"""
            SELECT r.producto_id, r.estado, r.motivo, r.notas,
                   r.creado_en, r.revisado_en,
                   p.codigo, p.descripcion, p.marca, p.precio_base,
                   p.costo_ultimo, p.imagen_url, c.nombre as categoria,
                   (SELECT COALESCE(SUM(cantidad_restante), 0) FROM lotes l
                     WHERE l.producto_id = p.id) as stock
            FROM revision_productos r
            JOIN productos p ON p.id = r.producto_id
            LEFT JOIN categorias c ON c.id = p.categoria_id
            WHERE {" AND ".join(cond)}
            ORDER BY (r.estado = 'pendiente') DESC, r.creado_en DESC
        """, params).fetchall()]


def contar_revision_pendiente() -> int:
    with get_connection() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM revision_productos WHERE estado='pendiente'"
        ).fetchone()[0]


# ─────────────────────────────────────────────────────────────────────────────
# BITACORA — quien autorizo cada accion sensible
# ─────────────────────────────────────────────────────────────────────────────

def registrar_bitacora(accion, responsable, detalle="", monto=None,
                       referencia=None):
    """Deja constancia de una accion que mueve plata o stock.

    No es un log tecnico: es lo que permite explicar una diferencia de
    caja tres dias despues. Se guarda quien la autorizo, cuanto y sobre
    que.
    """
    try:
        with get_connection() as conn:
            conn.execute("""
                INSERT INTO bitacora (accion, detalle, monto, responsable,
                                      referencia)
                VALUES (?,?,?,?,?)
            """, (accion, detalle, monto, responsable or "sin identificar",
                  str(referencia) if referencia is not None else None))
            conn.commit()
    except Exception as e:
        # Nunca frenar la operacion por no poder registrarla
        logging.warning(f"No se pudo escribir en la bitacora: {e}")


def get_bitacora(desde=None, hasta=None, accion=None, limite=300) -> list:
    cond, params = ["1=1"], []
    if desde:
        cond.append("date(fecha) >= date(?)"); params.append(desde)
    if hasta:
        cond.append("date(fecha) <= date(?)"); params.append(hasta)
    if accion:
        cond.append("accion = ?"); params.append(accion)
    params.append(limite)
    with get_connection() as conn:
        return [dict(r) for r in conn.execute(f"""
            SELECT * FROM bitacora WHERE {" AND ".join(cond)}
            ORDER BY fecha DESC LIMIT ?
        """, params).fetchall()]


def get_vendedor_por_codigo(codigo: str) -> dict | None:
    with get_connection() as conn:
        r = conn.execute("SELECT * FROM vendedores WHERE codigo=?",
                         (str(codigo).strip(),)).fetchone()
        return dict(r) if r else None


def get_categorias_vendedor(vendedor_id: int) -> list:
    """IDs de categorias habilitadas. Lista vacia = ve todo el catalogo."""
    with get_connection() as conn:
        return [r[0] for r in conn.execute(
            "SELECT categoria_id FROM vendedor_categorias WHERE vendedor_id=?",
            (vendedor_id,))]


def set_categorias_vendedor(vendedor_id: int, categoria_ids: list):
    """Reemplaza el set completo. Lista vacia = habilita todo."""
    with get_connection() as conn:
        conn.execute("DELETE FROM vendedor_categorias WHERE vendedor_id=?",
                     (vendedor_id,))
        for cid in set(categoria_ids or []):
            conn.execute("INSERT OR IGNORE INTO vendedor_categorias "
                         "(vendedor_id, categoria_id) VALUES (?,?)",
                         (vendedor_id, int(cid)))
        conn.commit()


def guardar_vendedor(vid, codigo, nombre, usuario, password_plano,
                     telefono, comision_pct, modo_cobro,
                     modo_comision="recargo",
                     nombre_comercial="") -> tuple[bool, str]:
    """
    password_plano: si es None/vacío al EDITAR, se mantiene la
    contraseña que ya tenía (no se pisa). Al crear uno nuevo es
    obligatoria. Retorna (ok, mensaje_de_error_o_vacio).
    """
    codigo = codigo.strip().lower()
    usuario = usuario.strip().lower()
    if not codigo or not nombre.strip() or not usuario:
        return False, "Código, nombre y usuario son obligatorios."

    with get_connection() as conn:
        dup = conn.execute(
            "SELECT id FROM vendedores WHERE (codigo=? OR usuario=?) AND id IS NOT ?",
            (codigo, usuario, vid or 0)
        ).fetchone()
        if dup:
            return False, "Ya existe otro vendedor con ese código o usuario."

        if vid:
            if password_plano:
                conn.execute("""
                    UPDATE vendedores
                    SET codigo=?, nombre=?, usuario=?, password_hash=?,
                        telefono=?, comision_pct=?, modo_cobro=?,
                        modo_comision=?, nombre_comercial=?
                    WHERE id=?
                """, (codigo, nombre.strip(), usuario, hash_password(password_plano),
                      telefono.strip(), comision_pct, modo_cobro,
                      modo_comision, (nombre_comercial or "").strip(), vid))
            else:
                conn.execute("""
                    UPDATE vendedores
                    SET codigo=?, nombre=?, usuario=?,
                        telefono=?, comision_pct=?, modo_cobro=?,
                        modo_comision=?, nombre_comercial=?
                    WHERE id=?
                """, (codigo, nombre.strip(), usuario,
                      telefono.strip(), comision_pct, modo_cobro,
                      modo_comision, (nombre_comercial or "").strip(), vid))
        else:
            if not password_plano:
                return False, "La contraseña es obligatoria para un vendedor nuevo."
            conn.execute("""
                INSERT INTO vendedores
                    (codigo, nombre, usuario, password_hash, telefono,
                     comision_pct, modo_cobro, modo_comision, nombre_comercial)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (codigo, nombre.strip(), usuario, hash_password(password_plano),
                  telefono.strip(), comision_pct, modo_cobro, modo_comision,
                  (nombre_comercial or "").strip()))
        conn.commit()
        return True, ""


def toggle_vendedor(vid: int, activo: int):
    with get_connection() as conn:
        conn.execute("UPDATE vendedores SET activo=? WHERE id=?", (activo, vid))
        conn.commit()


def eliminar_vendedor(vid: int):
    with get_connection() as conn:
        conn.execute("DELETE FROM vendedores WHERE id=?", (vid,))
        conn.commit()

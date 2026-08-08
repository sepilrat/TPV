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


# ─────────────────────────────────────────────────────────────────────────────
# PIEZAS (mercaderia de peso variable: hormas, piezas de fiambre)
# ─────────────────────────────────────────────────────────────────────────────

def registrar_piezas(producto_id, piezas, proveedor_id=None, notas="") -> dict:
    """Ingresa varias piezas en un mismo lote, cada una con SU peso y costo.

    piezas: [{"peso": 3.850, "costo_kg": 10416.67, "etiqueta": "H-001",
              "vencimiento": "2026-09-15", "merma_pct": 4.0}, ...]

    Crea un lote por los kilos totales (para que el stock global siga
    cuadrando) y una fila en piezas por cada horma. El lote sirve para el
    total; la pieza es la que manda a la hora de imputar costo.
    """
    if not piezas:
        raise ValueError("No se cargo ninguna pieza")

    total_kg = sum(float(p["peso"]) for p in piezas)
    if total_kg <= 0:
        raise ValueError("El peso total tiene que ser mayor a cero")
    costo_prom = sum(float(p["peso"]) * float(p.get("costo_kg") or 0)
                     for p in piezas) / total_kg

    conn = get_connection()
    try:
        cur = conn.execute("""
            INSERT INTO lotes (producto_id, proveedor_id, cantidad,
                               cantidad_restante, costo_unitario, tipo, notas)
            VALUES (?,?,?,?,?,'ingreso',?)
        """, (producto_id, proveedor_id, total_kg, total_kg, costo_prom,
              notas or f"{len(piezas)} pieza(s) de peso variable"))
        lote_id = cur.lastrowid

        ids = []
        for i, pz in enumerate(piezas, start=1):
            peso = float(pz["peso"])
            etiqueta = (pz.get("etiqueta") or "").strip() or None
            c2 = conn.execute("""
                INSERT INTO piezas (producto_id, lote_id, etiqueta, peso_inicial,
                                    peso_restante, costo_kg, merma_pct,
                                    estado, vencimiento)
                VALUES (?,?,?,?,?,?,?,'cerrada',?)
            """, (producto_id, lote_id, etiqueta, peso, peso,
                  float(pz.get("costo_kg") or 0), float(pz.get("merma_pct") or 0),
                  pz.get("vencimiento")))
            pid = c2.lastrowid
            if not etiqueta:
                conn.execute("UPDATE piezas SET etiqueta=? WHERE id=?",
                             (f"#{pid}", pid))
            ids.append(pid)

        conn.execute("""
            UPDATE productos SET costo_ultimo=?,
                   modificado_en=datetime('now','localtime')
            WHERE id=?
        """, (costo_prom, producto_id))
        conn.commit()
        return {"lote_id": lote_id, "pieza_ids": ids,
                "total_kg": total_kg, "costo_promedio": costo_prom}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_piezas(producto_id=None, estados=("cerrada", "abierta")) -> list:
    cond, params = ["p.peso_restante > 0.0001"], []
    if producto_id:
        cond.append("p.producto_id = ?"); params.append(producto_id)
    if estados:
        cond.append("p.estado IN (%s)" % ",".join("?" * len(estados)))
        params += list(estados)
    with get_connection() as conn:
        return [dict(r) for r in conn.execute(f"""
            SELECT p.*, pr.descripcion as producto_descripcion
            FROM piezas p JOIN productos pr ON pr.id = p.producto_id
            WHERE {" AND ".join(cond)}
            ORDER BY (p.estado='abierta') DESC, p.vencimiento IS NULL,
                     p.vencimiento, p.id
        """, params).fetchall()]


def get_pieza_activa(producto_id) -> dict | None:
    """La pieza que se esta cortando ahora. None si no hay ninguna abierta."""
    abiertas = get_piezas(producto_id, estados=("abierta",))
    return abiertas[0] if abiertas else None


def abrir_pieza(pieza_id) -> dict:
    with get_connection() as conn:
        conn.execute("""
            UPDATE piezas SET estado='abierta',
                   abierta_en=COALESCE(abierta_en, datetime('now','localtime'))
            WHERE id=? AND estado='cerrada'
        """, (pieza_id,))
        return dict(conn.execute("SELECT * FROM piezas WHERE id=?",
                                 (pieza_id,)).fetchone())


def consumir_pieza(pieza_id, cantidad, detalle_venta_id=None) -> dict:
    """Descuenta kilos de UNA pieza concreta y deja el rastro del costo.

    No usa FIFO: el cortador elige de que horma corta, y el costo que se
    imputa es el de esa horma. Es la unica forma de que la rentabilidad
    refleje lo que paso de verdad.
    """
    cantidad = float(cantidad)
    conn = get_connection()
    try:
        pz = conn.execute("SELECT * FROM piezas WHERE id=?", (pieza_id,)).fetchone()
        if not pz:
            raise ValueError("La pieza no existe")
        if cantidad <= 0:
            raise ValueError("La cantidad tiene que ser mayor a cero")
        if cantidad > pz["peso_restante"] + 1e-6:
            raise ValueError(
                f"La pieza {pz['etiqueta']} tiene {pz['peso_restante']:.3f} kg, "
                f"no alcanzan para {cantidad:.3f} kg")

        restante = pz["peso_restante"] - cantidad
        estado = "terminada" if restante <= 1e-6 else "abierta"
        conn.execute("""
            UPDATE piezas
            SET peso_restante=?, estado=?,
                abierta_en=COALESCE(abierta_en, datetime('now','localtime')),
                cerrada_en=CASE WHEN ?='terminada'
                                THEN datetime('now','localtime') ELSE cerrada_en END
            WHERE id=?
        """, (max(0.0, restante), estado, estado, pieza_id))

        if detalle_venta_id:
            conn.execute("""
                INSERT INTO detalle_ventas_piezas
                    (detalle_venta_id, pieza_id, cantidad, costo_kg)
                VALUES (?,?,?,?)
            """, (detalle_venta_id, pieza_id, cantidad, pz["costo_kg"]))

        conn.commit()
        return {"pieza_id": pieza_id, "restante": max(0.0, restante),
                "estado": estado, "costo_kg": pz["costo_kg"],
                "costo_total": cantidad * pz["costo_kg"]}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def rendimiento_pieza(pieza_id) -> dict | None:
    """Cuanto rindio realmente una horma ya terminada.

    Compara el peso que se cargo contra el que se llego a vender. La
    diferencia es la merma REAL, que es el numero que sirve para calibrar
    el porcentaje estimado de la proxima compra.
    """
    with get_connection() as conn:
        pz = conn.execute("SELECT * FROM piezas WHERE id=?", (pieza_id,)).fetchone()
        if not pz:
            return None
        vendido = conn.execute("""
            SELECT COALESCE(SUM(cantidad), 0) FROM detalle_ventas_piezas
            WHERE pieza_id = ?
        """, (pieza_id,)).fetchone()[0]

    inicial = pz["peso_inicial"]
    merma_real = inicial - vendido - pz["peso_restante"]
    return {
        "etiqueta": pz["etiqueta"],
        "peso_inicial": inicial,
        "vendido": vendido,
        "restante": pz["peso_restante"],
        "merma_real_kg": merma_real,
        "merma_real_pct": (merma_real / inicial * 100) if inicial else 0,
        "merma_estimada_pct": pz["merma_pct"],
        "estado": pz["estado"],
    }


def describir_stock(producto_id: int) -> str:
    """Traduce el stock a como esta fisicamente en la gondola.

    El stock se guarda en la unidad chica (el caramelo), porque es la unica
    que permite vender de las dos formas sin descuadrar. Pero "1630 unidades"
    no responde la pregunta que uno se hace mirando el estante, que es
    cuantas bolsas cerradas quedan. Esto lo reparte:

        1630 unidades  ->  "9 bolsas 800 g cerradas + 136 sueltos"
    """
    stock = get_stock_producto(producto_id)

    # Peso variable: lo que importa no son los kilos totales sino cuantas
    # piezas cerradas quedan y cuanto le queda a la que esta abierta.
    piezas = get_piezas(producto_id)
    if piezas:
        cerradas = [p for p in piezas if p["estado"] == "cerrada"]
        abiertas = [p for p in piezas if p["estado"] == "abierta"]
        partes = []
        if cerradas:
            kg = sum(p["peso_restante"] for p in cerradas)
            partes.append(f"{len(cerradas)} pieza{'s' if len(cerradas) > 1 else ''} "
                          f"cerrada{'s' if len(cerradas) > 1 else ''} ({kg:.3f} kg)")
        for p in abiertas:
            partes.append(f"{p['etiqueta']} abierta con {p['peso_restante']:.3f} kg")
        return " + ".join(partes) if partes else "sin stock"

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
    with get_connection() as conn:
        cur = conn.execute("""
            INSERT INTO productos
                (codigo, descripcion, categoria_id, precio_base, costo_ultimo,
                 vendido_por_peso, marca)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (codigo, descripcion, categoria_id, precio_base, costo,
              int(bool(vendido_por_peso)), (marca or "").strip() or None))
        conn.commit()
        return cur.lastrowid


def actualizar_producto(pid, descripcion, codigo, categoria_id,
                        precio_base, costo_ultimo=None, margen_pct=None,
                        vendido_por_peso=0, imagen_url=None, marca=None):
    with get_connection() as conn:
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
                  "Apertura de horma", txt, autorizado_por or None))

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
            SELECT p.descripcion, p.codigo,
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


def redondear_precio(precio: float, paso: int = None) -> float:
    """Redondea SIEMPRE hacia arriba al multiplo configurado.

    Hacia arriba y no al mas cercano: redondear para abajo es regalar
    margen en cada venta. La diferencia por unidad es centavos, pero sobre
    miles de tickets no lo es.

    paso=0 (o None con la config en 0) devuelve el precio tal cual.
    """
    import math
    if paso is None:
        try:
            from config import cfg
            paso = cfg().get("redondeo_precios", 0)
        except Exception:
            paso = 0
    paso = int(paso or 0)
    if paso <= 0:
        return round(float(precio), 2)
    return float(math.ceil(float(precio) / paso) * paso)


def redondear_todos_los_precios(paso: int = None, solo_activos: bool = True) -> dict:
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
            nuevo = redondear_precio(viejo, paso)
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
    return {
        "costo_anterior": costo_anterior, "costo_nuevo": costo_nuevo,
        "precio_actual": precio_actual, "precio_sugerido": precio_sugerido,
        "direccion": direccion,
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


def get_precio_con_promo(producto_id: int, cantidad: float) -> tuple[float, bool]:
    """Retorna (precio_unitario, promo_aplicada). Si hay varias promos
    aplicables por la cantidad, usa la que dé el precio más bajo —
    tanto para promos de precio fijo como de % de descuento (el %
    se calcula siempre sobre el precio_base actual del producto, así
    que si cambiás el precio de lista, la promo de % se ajusta sola)."""
    hoy = datetime.now().strftime("%Y-%m-%d")
    with get_connection() as conn:
        prod = conn.execute(
            "SELECT precio_base FROM productos WHERE id=?", (producto_id,)
        ).fetchone()
        precio_base = prod["precio_base"] if prod else 0.0

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
    with get_connection() as conn:
        conn.execute("""
            UPDATE productos SET precio_base=?,
            modificado_en=datetime('now','localtime') WHERE id=?
        """, (nuevo_precio, pid))
        conn.commit()


def aplicar_aumento_bulk(ids: list, pct: float):
    with get_connection() as conn:
        conn.execute(f"""
            UPDATE productos SET
                precio_base = ROUND(precio_base * (1 + ? / 100.0), 2),
                modificado_en = datetime('now','localtime')
            WHERE id IN ({','.join('?'*len(ids))})
        """, [pct] + ids)
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
        conn.execute(f"""
            UPDATE productos SET
                margen_pct = ?,
                precio_base = CASE WHEN costo_ultimo > 0
                    THEN ROUND(costo_ultimo * (1 + ? / 100.0), 2)
                    ELSE precio_base END,
                modificado_en = datetime('now','localtime')
            WHERE id IN ({','.join('?'*len(ids))})
        """, [margen_pct, margen_pct] + ids)
        conn.commit()


def aplicar_margen_bulk(ids: list):
    """
    Recalcula precio_base = costo x (1 + margen%) para los productos
    dados, usando el margen PROPIO del producto si tiene uno, o el de
    su categoría si no (igual criterio que calcular_precio_por_margen).
    """
    with get_connection() as conn:
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

def registrar_venta(sesion_id, items, metodo_pago,
                    descuento_pct=0.0, cliente_id=None) -> int | None:
    conn = get_connection()
    try:
        subtotales   = [i["cantidad"] * i["precio_unitario"] for i in items]
        total_bruto  = sum(subtotales)
        desc_monto   = total_bruto * (descuento_pct / 100)
        total        = total_bruto - desc_monto

        cur = conn.execute("""
            INSERT INTO ventas
                (sesion_id, total, metodo_pago, descuento_pct,
                 descuento_monto, cliente_id)
            VALUES (?,?,?,?,?,?)
        """, (sesion_id, total, metodo_pago, descuento_pct,
              desc_monto, cliente_id))
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

        col = {
            "efectivo":         "total_efectivo",
            "tarjeta":          "total_tarjeta",
            "qr":               "total_qr",
            "cuenta_corriente": "total_cuenta_corriente",
            "mixto":            "total_efectivo",
        }.get(metodo_pago, "total_efectivo")

        conn.execute(f"""
            UPDATE sesiones_caja SET {col} = {col} + ? WHERE id=?
        """, (total, sesion_id))

        conn.commit()
        return venta_id

    except Exception as e:
        conn.rollback()
        import logging
        logging.error(f"Error registrando venta: {e}")
        return None
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
        v = conn.execute(
            "SELECT anulada, sesion_id, total, metodo_pago FROM ventas WHERE id=?",
            (venta_id,)
        ).fetchone()
        if not v or v["anulada"]:
            return False

        conn.execute("UPDATE ventas SET anulada=1 WHERE id=?", (venta_id,))

        col = {
            "efectivo":         "total_efectivo",
            "tarjeta":          "total_tarjeta",
            "qr":               "total_qr",
            "cuenta_corriente": "total_cuenta_corriente",
            "mixto":            "total_efectivo",
        }.get(v["metodo_pago"], "total_efectivo")
        conn.execute(f"""
            UPDATE sesiones_caja SET {col} = {col} - ? WHERE id=?
        """, (v["total"], v["sesion_id"]))

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
            col = {
                "efectivo":         "total_efectivo",
                "tarjeta":          "total_tarjeta",
                "qr":               "total_qr",
                "cuenta_corriente": "total_cuenta_corriente",
                "mixto":            "total_efectivo",
            }.get(v["metodo_pago"], "total_efectivo")
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


def guardar_vendedor(vid, codigo, nombre, usuario, password_plano,
                     telefono, comision_pct, modo_cobro) -> tuple[bool, str]:
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
                        telefono=?, comision_pct=?, modo_cobro=?
                    WHERE id=?
                """, (codigo, nombre.strip(), usuario, hash_password(password_plano),
                      telefono.strip(), comision_pct, modo_cobro, vid))
            else:
                conn.execute("""
                    UPDATE vendedores
                    SET codigo=?, nombre=?, usuario=?,
                        telefono=?, comision_pct=?, modo_cobro=?
                    WHERE id=?
                """, (codigo, nombre.strip(), usuario,
                      telefono.strip(), comision_pct, modo_cobro, vid))
        else:
            if not password_plano:
                return False, "La contraseña es obligatoria para un vendedor nuevo."
            conn.execute("""
                INSERT INTO vendedores
                    (codigo, nombre, usuario, password_hash, telefono,
                     comision_pct, modo_cobro)
                VALUES (?,?,?,?,?,?,?)
            """, (codigo, nombre.strip(), usuario, hash_password(password_plano),
                  telefono.strip(), comision_pct, modo_cobro))
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

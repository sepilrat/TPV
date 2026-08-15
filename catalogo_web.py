"""
catalogo_web.py — Sincroniza el catálogo (productos activos + precios)
hacia una Google Sheet, para que la página de pedidos de clientes
siempre lea precios actuales sin cargar nada a mano.
TPV v2.0

Requiere tener desplegada la Apps Script Web App (ver
apps_script_catalogo.gs) y su URL cargada en Config > Catálogo web.
"""
import logging
import json
import urllib.request
import urllib.error

TIMEOUT = 15
LADO_MINIATURA = 160   # px — chico a propósito, Google Sheets limita
                       # cada celda a 50.000 caracteres


def _imagen_para_sync(imagen_url: str) -> tuple[str, str | None]:
    """
    Convierte la foto de un producto (sea una URL externa o una
    guardada localmente en esta compu) a una miniatura CUADRADA de
    tamaño fijo, con relleno de fondo si la foto original no es
    cuadrada — la misma técnica que ya usa el catálogo de escritorio
    (imagenes.cargar_thumbnail) para que ninguna foto quede recortada
    ni salga de un tamaño distinto a las demás.
    Devuelve (data_uri, motivo_de_error). Si no hay foto para este
    producto, devuelve ("", None) — no es un error, simplemente no
    tiene. Se procesan también las URLs externas (no solo las
    locales) para que el catálogo entero quede parejo.
    """
    if not imagen_url:
        return "", None
    import imagenes
    from PIL import Image
    import io
    import base64

    data = imagenes._resolver_bytes(imagen_url)
    if not data:
        return "", f"no se pudo descargar/abrir '{imagen_url}'"
    try:
        img = Image.open(io.BytesIO(data)).convert("RGB")
        img.thumbnail((LADO_MINIATURA, LADO_MINIATURA), Image.LANCZOS)

        lienzo = Image.new("RGB", (LADO_MINIATURA, LADO_MINIATURA), (243, 244, 246))
        offset = ((LADO_MINIATURA - img.width) // 2, (LADO_MINIATURA - img.height) // 2)
        lienzo.paste(img, offset)

        buf = io.BytesIO()
        lienzo.save(buf, "JPEG", quality=70)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{b64}", None
    except Exception as e:
        return "", f"error procesando '{imagen_url}': {e}"


def sincronizar(url: str = None) -> tuple[bool, str]:
    """
    Manda a la Apps Script Web App, en una sola pasada:
      - "productos": el catálogo público (para la página de pedidos
        de clientes) → hoja "Catalogo".
      - "productos_interno": lo mismo pero con costo, margen y stock
        incluidos → hoja "Interno". Esta hoja NUNCA se expone en la
        página de pedidos (esa página solo lee "Catalogo") — es para
        abrir la Sheet vos mismo desde el celular y ver esos datos.
    Retorna (ok, mensaje).
    """
    if url is None:
        from config import cfg
        url = cfg().get("catalogo_web_url", "")
    url = (url or "").strip()
    if not url:
        return False, ("No hay una URL de sincronización configurada. "
                       "Andá a Config > Catálogo web.")

    from repositorio import get_productos, get_proveedores_ultimo_por_producto, get_promociones_activas_por_producto
    base = [p for p in get_productos(solo_activos=True)
           if p["precio_base"] and p["precio_base"] > 0]
    proveedores = get_proveedores_ultimo_por_producto()
    promos_por_producto = get_promociones_activas_por_producto()

    con_foto_asignada = 0
    con_foto_convertida = 0
    errores = []
    productos = []
    productos_interno = []
    for p in base:
        imagen_url_raw = p.get("imagen_url")
        if imagen_url_raw:
            con_foto_asignada += 1
        imagen_final, motivo_error = _imagen_para_sync(imagen_url_raw)
        if imagen_final:
            con_foto_convertida += 1
        elif motivo_error:
            errores.append(f"{p['descripcion']}: {motivo_error}")
        # Formato compacto [tipo, cant_minima, valor] — "p" = %, "f" =
        # precio fijo — para que entre chico en la celda del Sheet.
        promos_compactas = [
            ["p" if pr["tipo_descuento"] == "porcentaje" else "f",
             pr["cantidad_minima"],
             pr["porcentaje_descuento"] if pr["tipo_descuento"] == "porcentaje" else pr["precio_unitario"]]
            for pr in promos_por_producto.get(p["id"], [])
        ]
        productos.append({
            "codigo": p["codigo"],
            "descripcion": p["descripcion"],
            "marca": p.get("marca") or "",
            "categoria": p.get("categoria") or "",
            "precio": p["precio_base"],
            "stock": p.get("stock") or 0,
            "promos": json.dumps(promos_compactas) if promos_compactas else "",
            "imagen": imagen_final,
        })
        productos_interno.append({
            "codigo": p["codigo"],
            "descripcion": p["descripcion"],
            "marca": p.get("marca") or "",
            "categoria": p.get("categoria") or "",
            "costo": p.get("costo_ultimo") or 0,
            "precio": p["precio_base"],
            "margen": p.get("margen") if p.get("margen") is not None else "",
            "stock": p.get("stock") or 0,
            "proveedor": proveedores.get(p["id"], ""),
        })

    payload = json.dumps({
        "productos": productos,
        "productos_interno": productos_interno,
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload, method="POST",
        headers={"Content-Type": "application/json"})

    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            cuerpo = resp.read().decode("utf-8", errors="ignore")
    except urllib.error.HTTPError as e:
        return False, f"Error HTTP {e.code} — revisá que la Web App esté bien publicada."
    except urllib.error.URLError as e:
        return False, f"No se pudo conectar: {e.reason}"
    except Exception as e:
        return False, f"Error inesperado: {e}"

    try:
        data = json.loads(cuerpo)
    except ValueError:
        return False, (f"Respuesta inesperada del servicio "
                       f"(¿la URL es la de la Web App, no la del Sheet?): "
                       f"{cuerpo[:200]}")

    if data.get("ok"):
        if con_foto_asignada == 0:
            detalle = " — ningún producto tiene foto asignada en el TPV todavía."
        elif con_foto_convertida == con_foto_asignada:
            detalle = f" — {con_foto_convertida} foto(s) incluida(s), todas bien."
        else:
            detalle = (f" — {con_foto_convertida} de {con_foto_asignada} foto(s) "
                      f"incluida(s). Fallaron: " + "; ".join(errores[:5]))
        # Queda registrado para poder avisar si alguien reparte un link de
        # vendedor sin haber subido nunca el catalogo.
        try:
            from config import set as cfg_set
            from datetime import datetime as _dt
            cfg_set("catalogo_web_ultima_sync",
                    _dt.now().strftime("%Y-%m-%d %H:%M"))
            cfg_set("catalogo_web_ultima_cantidad", int(data.get("cantidad", 0)))
        except Exception as e:
            logging.debug(f"No se pudo registrar la fecha de sincronizacion: {e}")
        return True, f"Sincronizados {data.get('cantidad', 0)} producto(s).{detalle}"
    return False, f"El servicio devolvió un error: {data.get('error', '(sin detalle)')}"


def sincronizar_stock(url: str = None) -> tuple[bool, str]:
    """
    Versión liviana de sincronizar(): manda {codigo: {stock, precio,
    promos}} de los productos activos, sin procesar ninguna foto.
    Se dispara sola después de cada venta cobrada (para el stock) y
    después de cualquier cambio de precio, margen o promo (ver
    sincronizar_stock_en_segundo_plano) — así la página de pedidos
    nunca queda desactualizada esperando una sincronización completa
    manual. Para fotos/descripciones nuevas sigue estando sincronizar().
    """
    if url is None:
        from config import cfg
        url = cfg().get("catalogo_web_url", "")
    url = (url or "").strip()
    if not url:
        return False, "No hay una URL de sincronización configurada."

    from repositorio import get_productos, get_promociones_activas_por_producto
    base = [p for p in get_productos(solo_activos=True)
           if p["precio_base"] and p["precio_base"] > 0]
    promos_por_producto = get_promociones_activas_por_producto()

    datos = {}
    for p in base:
        promos_compactas = [
            ["p" if pr["tipo_descuento"] == "porcentaje" else "f",
             pr["cantidad_minima"],
             pr["porcentaje_descuento"] if pr["tipo_descuento"] == "porcentaje" else pr["precio_unitario"]]
            for pr in promos_por_producto.get(p["id"], [])
        ]
        datos[p["codigo"]] = {
            "stock": p.get("stock") or 0,
            "precio": p["precio_base"],
            "promos": json.dumps(promos_compactas) if promos_compactas else "",
        }

    payload = json.dumps({
        "accion": "actualizar_stock",
        "datos": datos,
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload, method="POST",
        headers={"Content-Type": "application/json"})

    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            cuerpo = resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        return False, f"No se pudo sincronizar: {e}"

    try:
        data = json.loads(cuerpo)
    except ValueError:
        return False, f"Respuesta inesperada del servicio: {cuerpo[:200]}"

    if data.get("ok"):
        return True, (f"Actualizado ({data.get('actualizados', 0)} producto(s) de "
                      f"{data.get('recibidos', '?')} enviados; "
                      f"{data.get('sin_match', 0)} sin coincidencia en la hoja).")
    return False, f"El servicio devolvió un error: {data.get('error', '(sin detalle)')}"


def sincronizar_vendedores(url: str = None) -> tuple[bool, str]:
    """
    Manda la lista completa de vendedores (con password_hash YA
    calculado del lado de acá — nunca viaja una contraseña en texto
    plano) a la hoja "Vendedores". La reescribe entera cada vez,
    igual que sincronizar() con el catálogo.
    """
    if url is None:
        from config import cfg
        url = cfg().get("catalogo_web_url", "")
    url = (url or "").strip()
    if not url:
        return False, "No hay una URL de sincronización configurada."

    from repositorio import (get_vendedores, get_categorias,
                             get_categorias_vendedor)
    vendedores = [{
        "codigo": v["codigo"],
        "nombre": v["nombre"],
        "usuario": v["usuario"],
        "password_hash": v["password_hash"],
        "telefono": v.get("telefono") or "",
        "comision_pct": v["comision_pct"],
        "modo_cobro": v["modo_cobro"],
        "modo_comision": v["modo_comision"] if "modo_comision" in v.keys()
                         else "recargo",
        # Categorias habilitadas, separadas por "|". Vacio = ve todo.
        "categorias": "|".join(
            c["nombre"] for c in get_categorias()
            if c["id"] in set(get_categorias_vendedor(v["id"]))),
        "activo": bool(v["activo"]),
    } for v in get_vendedores()]

    payload = json.dumps({
        "accion": "sincronizar_vendedores",
        "vendedores": vendedores,
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload, method="POST",
        headers={"Content-Type": "application/json"})

    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            cuerpo = resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        return False, f"No se pudo sincronizar vendedores: {e}"

    try:
        data = json.loads(cuerpo)
    except ValueError:
        return False, f"Respuesta inesperada del servicio: {cuerpo[:200]}"

    if data.get("ok"):
        return True, f"{data.get('cantidad', 0)} vendedor(es) sincronizado(s)."
    return False, f"El servicio devolvió un error: {data.get('error', '(sin detalle)')}"


def obtener_resumen_vendedores(url: str = None) -> tuple[bool, list | str]:
    """
    Trae de la hoja "Pedidos" el resumen de pedidos y comisiones
    agrupado por vendedor. Retorna (True, lista_de_dicts) o
    (False, mensaje_de_error).
    """
    if url is None:
        from config import cfg
        url = cfg().get("catalogo_web_url", "")
    url = (url or "").strip()
    if not url:
        return False, "No hay una URL de sincronización configurada."

    payload = json.dumps({"accion": "resumen_vendedores"}).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload, method="POST",
        headers={"Content-Type": "application/json"})

    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            cuerpo = resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        return False, f"No se pudo traer el resumen: {e}"

    try:
        data = json.loads(cuerpo)
    except ValueError:
        return False, f"Respuesta inesperada del servicio: {cuerpo[:200]}"

    if data.get("ok"):
        return True, data.get("resumen", [])
    return False, f"El servicio devolvió un error: {data.get('error', '(sin detalle)')}"


def sincronizar_stock_en_segundo_plano():
    """
    Dispara sincronizar_stock() en un hilo aparte, sin bloquear la UI
    ni interrumpir el flujo del usuario — se llama después de
    cualquier venta, cambio de precio, margen o promo. Si falla (sin
    internet, sin URL configurada, etc.) queda solo logueado, nunca
    se muestra como error en pantalla — el cambio local ya se guardó
    igual, esto es solo mantener la web al día.
    """
    from config import cfg
    url = (cfg().get("catalogo_web_url", "") or "").strip()
    if not url:
        return

    def _tarea():
        import logging
        try:
            ok, msg = sincronizar_stock(url)
            if ok:
                logging.info(f"Sync catálogo web: {msg}")
            else:
                logging.warning(f"No se pudo sincronizar el catálogo web: {msg}")
        except Exception as e:
            logging.warning(f"Error sincronizando catálogo web: {e}")

    import threading
    threading.Thread(target=_tarea, daemon=True).start()

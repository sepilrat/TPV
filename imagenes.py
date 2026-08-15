"""
imagenes.py — Manejo de fotos de producto TPV v2.0
Soporta imagen local (se copia a imagenes_productos/) o URL externa.
Usado por productos_ui.py (cargar/ver foto) y ventas_ui.py (miniatura
en el listado de "elegir producto").
"""

import os
import io
import logging
import urllib.request

from PIL import Image, ImageTk

CARPETA_IMAGENES = os.path.join(os.path.dirname(__file__), "imagenes_productos")
EXTENSIONES_VALIDAS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")
MAX_LADO_GUARDADO = 800   # px — al guardar localmente, para no ocupar de más
# Timeout corto: una foto no puede frenar la caja. Y en la grilla ni
# siquiera se intenta bajar (ver PERMITIR_DESCARGA_URL): con 28 productos
# apuntando a un sitio lento, la pantalla tardaba casi 2 minutos en
# dibujarse.
TIMEOUT_URL = 4

# Cuando esta en False, las fotos por URL no se descargan: se muestran
# como "sin foto". Se pone en True a proposito al usar el boton
# "Guardar fotos localmente", que es cuando uno SI quiere esperar.
PERMITIR_DESCARGA_URL = False
# Miniaturas ya generadas, por (url, tamaño): evita releer del disco y
# redimensionar en cada repintado de la grilla.
_cache_thumbs = {}


def es_url(valor: str) -> bool:
    return bool(valor) and valor.strip().lower().startswith(("http://", "https://"))


def guardar_imagen_local(producto_id: int, ruta_origen: str) -> str:
    """
    Copia (y redimensiona si hace falta) una imagen elegida por archivo
    a imagenes_productos/{id}.jpg. Devuelve la ruta relativa a guardar
    en productos.imagen_url. Lanza excepción si el archivo no es una
    imagen válida.
    """
    os.makedirs(CARPETA_IMAGENES, exist_ok=True)
    img = Image.open(ruta_origen)
    img = img.convert("RGB")
    if max(img.size) > MAX_LADO_GUARDADO:
        img.thumbnail((MAX_LADO_GUARDADO, MAX_LADO_GUARDADO), Image.LANCZOS)

    nombre = f"{producto_id}.jpg"
    destino = os.path.join(CARPETA_IMAGENES, nombre)
    img.save(destino, "JPEG", quality=85)

    rel = os.path.join("imagenes_productos", nombre)
    invalidar_cache(rel)
    return rel


def ya_esta_en_carpeta(imagen_url: str) -> bool:
    """True si la imagen ya vive dentro de imagenes_productos/."""
    if not imagen_url or es_url(imagen_url):
        return False
    try:
        ruta = imagen_url if os.path.isabs(imagen_url) else os.path.join(
            os.path.dirname(__file__), imagen_url)
        return os.path.commonpath([os.path.abspath(ruta),
                                   os.path.abspath(CARPETA_IMAGENES)]) == \
               os.path.abspath(CARPETA_IMAGENES)
    except (ValueError, OSError):
        return False


def productos_con_foto_externa(solo_rotas=False) -> list:
    """Productos cuya foto es una URL, o sea que depende de internet.

    solo_rotas: ademas verifica que la URL responda. Tarda (una consulta
    por producto) pero es lo que permite limpiar solo las que ya no
    sirven, sin tocar las que todavia andan.
    """
    from repositorio import get_productos
    externas = [p for p in get_productos(solo_activos=False)
                if p.get("imagen_url") and es_url(p["imagen_url"])]
    if not solo_rotas:
        return externas

    rotas = []
    for prod in externas:
        try:
            req = urllib.request.Request(
                prod["imagen_url"], method="HEAD",
                headers={"User-Agent": "Mozilla/5.0"})
            urllib.request.urlopen(req, timeout=TIMEOUT_URL)
        except Exception:
            rotas.append(prod)
    return rotas


def descargar_fotos_externas(progreso=None, producto_ids=None) -> dict:
    """Baja a imagenes_productos/ las fotos que hoy son una URL.

    Son fotos elegidas a mano, no basura automatica: hay que
    conservarlas. Pero mientras vivan en un sitio ajeno se descargan
    cada vez que se dibuja la lista, cuelgan la pantalla si el sitio
    esta lento, y desaparecen el dia que las borren de alla.

    progreso: callable(hecho, total, descripcion) para la barra.
    Devuelve {"total", "ok", "errores": [str]}.
    """
    from repositorio import actualizar_imagen_producto
    todas = productos_con_foto_externa()
    if producto_ids is not None:
        ids = set(producto_ids)
        todas = [p for p in todas if p["id"] in ids]

    global PERMITIR_DESCARGA_URL
    anterior = PERMITIR_DESCARGA_URL
    PERMITIR_DESCARGA_URL = True     # acá SÍ se quiere esperar la descarga
    ok, errores = 0, []
    for i, prod in enumerate(todas, start=1):
        if progreso:
            progreso(i, len(todas), prod.get("descripcion", ""))
        try:
            rel = guardar_imagen_desde_url(prod["id"], prod["imagen_url"])
            actualizar_imagen_producto(prod["id"], rel)
            _URLS_FALLIDAS.discard(prod["imagen_url"])
            ok += 1
        except Exception as e:
            errores.append(f"{prod.get('descripcion', '?')[:38]}: {e}")
            logging.warning(f"No se pudo bajar la foto de "
                            f"{prod.get('descripcion', prod['id'])}: {e}")
    PERMITIR_DESCARGA_URL = anterior
    return {"total": len(todas), "ok": ok, "errores": errores}


def quitar_fotos_externas(producto_ids=None, solo_rotas=False) -> dict:
    """Deja sin foto a los productos que la tenian por URL.

    Una URL de un sitio ajeno no es una foto propia: se descarga cada
    vez que se dibuja la grilla, traba la pantalla si el sitio esta
    lento, y desaparece el dia que la borren de alla. Vaciarlas deja el
    producto listo para cargarle una foto de verdad.
    """
    from repositorio import actualizar_imagen_producto
    if producto_ids is None:
        objetivo = [p["id"] for p in productos_con_foto_externa(solo_rotas)]
    else:
        objetivo = list(producto_ids)
    for pid in objetivo:
        actualizar_imagen_producto(pid, None)
    return {"quitadas": len(objetivo)}


def incorporar_imagen(producto_id: int, origen: str) -> tuple[str, str]:
    """Deja la imagen dentro del sistema, venga de donde venga.

    origen puede ser una URL o la ruta a un archivo del disco. En los dos
    casos termina copiada en imagenes_productos/{id}.jpg, que es lo que
    hace que la foto siga estando aunque se borre el original o se caiga
    el sitio de donde salio.

    Devuelve (ruta_relativa, que_paso).
    """
    if not origen:
        raise ValueError("No hay ninguna imagen para incorporar.")

    if es_url(origen):
        return guardar_imagen_desde_url(producto_id, origen), "descargada"

    if ya_esta_en_carpeta(origen):
        return origen, "ya_estaba"

    ruta = origen if os.path.isabs(origen) else os.path.join(
        os.path.dirname(__file__), origen)
    if not os.path.isfile(ruta):
        raise ValueError(f"No se encontro el archivo:\n{origen}")
    return guardar_imagen_local(producto_id, ruta), "copiada"


def guardar_imagen_desde_url(producto_id: int, url: str) -> str:
    """
    Descarga una imagen desde una URL (ej: la que trajo Open Food
    Facts, o una que el usuario encontró buscando en internet) y la
    guarda localmente igual que guardar_imagen_local — para no
    depender de que ese sitio externo siga disponible más adelante.
    Lanza excepción si no se pudo descargar o no es una imagen válida.
    """
    data = _resolver_bytes(url)
    if not data:
        raise ValueError("No se pudo descargar la imagen de esa URL.")

    os.makedirs(CARPETA_IMAGENES, exist_ok=True)
    img = Image.open(io.BytesIO(data)).convert("RGB")
    if max(img.size) > MAX_LADO_GUARDADO:
        img.thumbnail((MAX_LADO_GUARDADO, MAX_LADO_GUARDADO), Image.LANCZOS)

    nombre = f"{producto_id}.jpg"
    destino = os.path.join(CARPETA_IMAGENES, nombre)
    img.save(destino, "JPEG", quality=85)

    rel = os.path.join("imagenes_productos", nombre)
    invalidar_cache(rel)
    return rel


def eliminar_imagen_local(producto_id: int):
    """
    Borra del disco la foto guardada localmente de un producto
    (imagenes_productos/{id}.jpg), si existe. No hace nada si el
    producto nunca tuvo una foto guardada localmente (por ejemplo,
    si su foto siempre fue una URL externa). Se usa cuando se
    reemplaza una foto local por una URL, se quita la foto, o se
    elimina el producto — para no dejar archivos huérfanos.
    """
    ruta = os.path.join(CARPETA_IMAGENES, f"{producto_id}.jpg")
    if os.path.exists(ruta):
        try:
            os.remove(ruta)
        except OSError as e:
            logging.warning(f"No se pudo borrar la imagen local del "
                            f"producto {producto_id}: {e}")
    invalidar_cache(os.path.join("imagenes_productos", f"{producto_id}.jpg"))


def invalidar_cache(imagen_url: str):
    """Saca del cache las miniaturas de esa imagen (para que se vea
    el cambio inmediatamente después de reemplazarla)."""
    claves = [k for k in _cache_thumbs if k[0] == imagen_url]
    for k in claves:
        del _cache_thumbs[k]


# URLs que fallaron: no se reintentan en toda la sesion. Sin esto, una
# grilla con 20 fotos rotas cuelga la pantalla 20 x TIMEOUT segundos, y
# vuelve a colgarla en cada refresco.
_URLS_FALLIDAS = set()


def _resolver_bytes(imagen_url: str) -> bytes | None:
    if not imagen_url:
        return None
    if imagen_url in _URLS_FALLIDAS:
        return None
    # Dibujar una lista no puede depender de internet: se muestra sin
    # foto y listo. Bajarlas es una accion explicita del usuario.
    if es_url(imagen_url) and not PERMITIR_DESCARGA_URL:
        return None
    try:
        if es_url(imagen_url):
            req = urllib.request.Request(
                imagen_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=TIMEOUT_URL) as resp:
                return resp.read()
        else:
            ruta = imagen_url
            if not os.path.isabs(ruta):
                ruta = os.path.join(os.path.dirname(__file__), ruta)
            if not os.path.exists(ruta):
                return None
            with open(ruta, "rb") as f:
                return f.read()
    except Exception as e:
        if es_url(imagen_url):
            _URLS_FALLIDAS.add(imagen_url)
            logging.warning(
                f"No se pudo bajar la foto de '{imagen_url}': {e}. "
                f"No se reintenta hasta reiniciar. Para que no dependa de "
                f"internet, guardala localmente desde Productos → Editar.")
        else:
            logging.warning(f"No se pudo cargar imagen '{imagen_url}': {e}")
        return None


def cargar_imagen_pil(imagen_url: str):
    """
    Como cargar_thumbnail pero devuelve un PIL.Image crudo (sin
    convertir a ImageTk), para usar en contextos que no son Tkinter
    — por ejemplo, al armar un PDF con reportlab. None si no hay
    imagen o no se pudo cargar.
    """
    data = _resolver_bytes(imagen_url)
    if not data:
        return None
    try:
        img = Image.open(io.BytesIO(data)).convert("RGB")
        return img
    except Exception as e:
        logging.warning(f"No se pudo procesar imagen '{imagen_url}': {e}")
        return None


def cargar_thumbnail(imagen_url: str, size=(64, 64), fondo=(243, 244, 246)):
    """
    Devuelve un ImageTk.PhotoImage listo para usar en un Label/Treeview,
    o None si no hay imagen o no se pudo cargar. Cachea en memoria por
    (imagen_url, size) para no repetir descarga/lectura de disco.

    SIEMPRE devuelve una imagen del tamaño EXACTO pedido (cuadrado,
    centrada, con relleno de fondo si la foto original no es cuadrada)
    — nunca un tamaño distinto según la proporción de la foto. Si no,
    en una tabla quedan íconos de ancho/alto distinto entre filas, se
    ven desprolijos y en Tkinter pueden pisar el texto de al lado.

    IMPORTANTE: quien lo use debe guardar una referencia (ej. en un
    atributo self.algo o en un dict de la instancia) porque Tkinter no
    retiene el PhotoImage solo — si no, Python lo recolecta y la
    imagen desaparece de la UI.
    """
    if not imagen_url:
        return None
    clave = (imagen_url, size)
    if clave in _cache_thumbs:
        return _cache_thumbs[clave]

    data = _resolver_bytes(imagen_url)
    if not data:
        return None
    try:
        img = Image.open(io.BytesIO(data))
        img = img.convert("RGB")
        img.thumbnail(size, Image.LANCZOS)

        lienzo = Image.new("RGB", size, fondo)
        offset = ((size[0] - img.width) // 2, (size[1] - img.height) // 2)
        lienzo.paste(img, offset)

        foto = ImageTk.PhotoImage(lienzo)
        _cache_thumbs[clave] = foto
        return foto
    except Exception as e:
        logging.warning(f"No se pudo procesar imagen '{imagen_url}': {e}")
        return None

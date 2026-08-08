"""
imagenes.py — Manejo de fotos de producto TPV v2.0
Soporta imagen local (se copia a imagenes_productos/) o URL externa.
Usado por productos_ui.py (cargar/ver foto) y ventas_ui.py (miniatura
en el listado de "elegir producto").
"""

import os
import io
import json
import logging
import re
import urllib.request

from PIL import Image, ImageTk

CARPETA_IMAGENES = os.path.join(os.path.dirname(__file__), "imagenes_productos")
EXTENSIONES_VALIDAS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")
MAX_LADO_GUARDADO = 800   # px — al guardar localmente, para no ocupar de más
TIMEOUT_URL = 6           # segundos
OFF_URL = "https://world.openfoodfacts.org/api/v2/product/{codigo}.json"


def _a_resolucion_completa(url: str) -> str:
    """
    Open Food Facts devuelve en image_*_url una versión reducida a
    400px (pensada para mostrar en apps chicas). La foto original tal
    cual la subieron — mucho mejor calidad — vive en el mismo servidor
    con el mismo nombre de archivo, solo que con "full" en vez del
    tamaño en píxeles: ".../front_es.4.400.jpg" -> ".../front_es.4.full.jpg"
    Si la URL no tiene ese patrón (formato inesperado), se devuelve
    igual que llegó, sin romper nada.
    """
    if not url:
        return url
    return re.sub(r"\.\d+\.jpg(\?.*)?$", r".full.jpg\1", url)

# Cache en memoria de miniaturas ya cargadas (evita releer/redescargar
# la misma imagen varias veces en la misma sesión).
_cache_thumbs = {}


def probar_conexion_openfoodfacts() -> tuple[bool, str]:
    """
    Prueba rápida de conectividad contra Open Food Facts (con un
    código que sabemos que existe). Se usa antes de una búsqueda
    masiva para avisar de entrada si hay un problema de red/firewall,
    en vez de recorrer todo el catálogo fallando en silencio.
    Retorna (ok, mensaje).
    """
    try:
        url = OFF_URL.format(codigo="7790895000430")  # Coca Cola 1.5L, existe
        req = urllib.request.Request(url, headers={"User-Agent": "TPV-Arai/1.0"})
        with urllib.request.urlopen(req, timeout=TIMEOUT_URL) as resp:
            json.loads(resp.read().decode("utf-8"))
        return True, "OK"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def buscar_fotos_openfoodfacts(codigo_barras: str) -> list[tuple[str, str]]:
    """
    Busca las fotos disponibles del producto en Open Food Facts (base
    de datos colaborativa, gratuita, sin API key) usando el código de
    barras. OFF suele tener más de una foto por producto (frente,
    empaque, ingredientes, tabla nutricional) — devuelve todas las que
    haya como lista de (etiqueta, url), en orden de relevancia. Lista
    vacía si el producto no está en la base o no tiene fotos.
    """
    codigo_barras = (codigo_barras or "").strip()
    if not codigo_barras or not codigo_barras.isdigit():
        return []
    try:
        url = OFF_URL.format(codigo=codigo_barras)
        req = urllib.request.Request(url, headers={"User-Agent": "TPV-Arai/1.0"})
        with urllib.request.urlopen(req, timeout=TIMEOUT_URL) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("status") != 1:
            return []
        p = data.get("product", {})
        candidatas = [
            ("Frente",            p.get("image_front_url") or p.get("image_url")),
            ("Empaque",           p.get("image_packaging_url")),
            ("Ingredientes",      p.get("image_ingredients_url")),
            ("Tabla nutricional", p.get("image_nutrition_url")),
        ]
        vistas = set()
        resultado = []
        for etiqueta, u in candidatas:
            if u and u not in vistas:
                vistas.add(u)
                resultado.append((etiqueta, _a_resolucion_completa(u)))
        return resultado
    except Exception as e:
        logging.warning(f"Open Food Facts: error buscando '{codigo_barras}': {e}")
        return []


def buscar_foto_openfoodfacts(codigo_barras: str) -> str | None:
    """Compatibilidad: devuelve solo la primera foto encontrada (la de
    frente si existe). Preferir buscar_fotos_openfoodfacts() para
    poder elegir entre varias."""
    fotos = buscar_fotos_openfoodfacts(codigo_barras)
    return fotos[0][1] if fotos else None


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


def _resolver_bytes(imagen_url: str) -> bytes | None:
    if not imagen_url:
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

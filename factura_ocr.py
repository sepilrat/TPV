"""
factura_ocr.py — Lectura de facturas de proveedor por OCR TPV v2.0

Usa Tesseract OCR (gratis, motor local, sin costo por uso) para leer
una foto de factura y separar cantidad / descripción / precio por
línea de producto.

IMPORTANTE: el OCR nunca es 100% exacto — sobre todo con fotos
sacadas con el celular (ángulo, luz, enfoque). El resultado de este
módulo SIEMPRE tiene que pasar por una revisión humana antes de
cargarse a la base (ver factura_ui.py) — nunca se debe insertar
directo sin confirmar.

Requiere tener instalado Tesseract OCR (el programa, no solo la
librería de Python):
  Windows: instalador de UB-Mannheim
           https://github.com/UB-Mannheim/tesseract/wiki
           (marcar el idioma "Spanish" al instalar)
  pip install pytesseract
"""

import re

TESSERACT_LANG = "spa"


def _tesseract_disponible() -> tuple[bool, str]:
    try:
        import pytesseract
        version = pytesseract.get_tesseract_version()
        return True, str(version)
    except ImportError:
        return False, "Falta instalar el paquete pytesseract (pip install pytesseract)."
    except Exception as e:
        return False, (
            "No se encontró el programa Tesseract OCR instalado. "
            "Descargalo de https://github.com/UB-Mannheim/tesseract/wiki "
            f"(detalle: {e})")


def _detectar_angulo_rotacion(img_gray, rango=6, paso=0.5):
    """
    Detecta el ángulo de rotación de una foto (nunca sale perfecta a
    mano) probando distintos ángulos y viendo con cuál las líneas de
    texto quedan mejor alineadas horizontalmente (más "picos" nítidos
    al sumar píxeles oscuros por fila). Sin esto, cualquier inclinación
    hace que las columnas de la derecha en una fila queden más arriba
    o abajo que las de la izquierda, y se rompe el agrupado por fila.
    """
    import numpy as np
    from PIL import Image

    arr = np.array(img_gray)
    binaria = (arr < 140).astype("uint8") * 255
    base = Image.fromarray(binaria)

    mejor_angulo, mejor_score = 0.0, -1.0
    angulo = -rango
    while angulo <= rango:
        rotada = base.rotate(angulo, expand=True, fillcolor=0)
        proyeccion = np.array(rotada).sum(axis=1)
        score = proyeccion.var()
        if score > mejor_score:
            mejor_score = score
            mejor_angulo = angulo
        angulo += paso
    return mejor_angulo


def _preprocesar_imagen(ruta_imagen):
    """Mejora una foto de celular para que el OCR lea mejor: corrige
    la rotación, pasa a escala de grises, más contraste, más
    nitidez, y la agranda si es chica."""
    from PIL import Image, ImageOps, ImageEnhance

    img = Image.open(ruta_imagen)
    # Corregir orientación según metadata EXIF (fotos de celular)
    img = ImageOps.exif_transpose(img)
    g = ImageOps.grayscale(img)

    angulo = _detectar_angulo_rotacion(g)
    if abs(angulo) >= 0.5:
        g = g.rotate(angulo, expand=True, fillcolor=255)

    g = ImageOps.autocontrast(g, cutoff=1)
    g = ImageEnhance.Sharpness(g).enhance(1.8)
    g = ImageEnhance.Contrast(g).enhance(1.3)
    if max(g.size) < 2200:
        factor = 2200 / max(g.size)
        g = g.resize((int(g.width * factor), int(g.height * factor)),
                     Image.LANCZOS)
    return g


def _agrupar_filas(datos_ocr, tol_y=14):
    """Agrupa las palabras detectadas por el OCR en filas, según su
    posición vertical (la tabla de la factura no siempre viene
    perfectamente recta, por eso la tolerancia)."""
    n = len(datos_ocr["text"])
    palabras = []
    for i in range(n):
        t = datos_ocr["text"][i].strip()
        if not t:
            continue
        try:
            conf = float(datos_ocr["conf"][i])
        except (ValueError, TypeError):
            conf = -1
        if conf != -1 and conf < 25:
            continue   # descartar palabras que el OCR leyó con muy poca confianza
        palabras.append({
            "texto": t,
            "top": datos_ocr["top"][i],
            "left": datos_ocr["left"][i],
        })
    palabras.sort(key=lambda p: p["top"])

    filas, fila, ultimo_top = [], [], None
    for p in palabras:
        if ultimo_top is not None and abs(p["top"] - ultimo_top) > tol_y:
            filas.append(fila)
            fila = []
        fila.append(p)
        ultimo_top = p["top"]
    if fila:
        filas.append(fila)
    return [sorted(f, key=lambda x: x["left"]) for f in filas]


_RE_NUMERO = re.compile(r"^-?\d[\d.,]*$")


def _es_numero(txt: str) -> bool:
    return bool(_RE_NUMERO.match(txt.strip()))


def _a_float(txt: str):
    t = txt.strip()
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".")   # formato AR: miles con punto, decimales con coma
    elif "," in t:
        t = t.replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def _parsear_filas(filas) -> list[dict]:
    """
    Intenta separar cada fila en cantidad / descripción / precio
    unitario / subtotal. Una fila "parece" una línea de producto si
    tiene al menos 2 números (cantidad + al menos un precio) — las
    filas de encabezado, totales sueltos, o datos del proveedor
    normalmente no cumplen esto y quedan afuera solas.
    """
    items = []
    for fila in filas:
        textos = [p["texto"] for p in fila]
        idx_num = [i for i, t in enumerate(textos) if _es_numero(t)]
        if len(idx_num) < 2:
            continue

        cant_idx = idx_num[0]
        precio_idx = idx_num[-2]
        subtotal_idx = idx_num[-1]
        if precio_idx <= cant_idx:
            continue

        descripcion = " ".join(textos[cant_idx + 1:precio_idx]).strip()
        if not descripcion:
            continue

        cantidad = _a_float(textos[cant_idx])
        precio_unitario = _a_float(textos[precio_idx])
        subtotal = _a_float(textos[subtotal_idx]) if subtotal_idx != precio_idx else None

        if not cantidad or cantidad <= 0:
            continue

        items.append({
            "cantidad": cantidad,
            "descripcion": descripcion,
            "precio_unitario": precio_unitario,
            "subtotal": subtotal,
        })
    return items


def extraer_lineas_factura(ruta_imagen: str) -> list[dict]:
    """
    Punto de entrada principal: recibe la ruta de la foto de la
    factura, devuelve una lista de posibles líneas de producto
    (cantidad, descripción, precio_unitario, subtotal) — SIN
    confirmar contra el catálogo todavía, eso lo hace factura_ui.py.
    Puede devolver líneas mal separadas o vacío si el OCR no
    encuentra nada parecido a una tabla — siempre hay que revisar.
    """
    ok, detalle = _tesseract_disponible()
    if not ok:
        raise RuntimeError(detalle)

    import pytesseract

    img = _preprocesar_imagen(ruta_imagen)
    datos = pytesseract.image_to_data(
        img, lang=TESSERACT_LANG, output_type=pytesseract.Output.DICT)
    filas = _agrupar_filas(datos)
    return _parsear_filas(filas)

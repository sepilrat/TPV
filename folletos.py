"""
folletos.py — Ingesta y analisis de folletos de ofertas para TPV Arai.

El usuario suelta PDFs o fotos en una carpeta (o los baja solo desde Vital) y
el modulo devuelve productos con precio, listos para revision humana antes de
tocar la base. Mismo patron que factura_ui.py: NADA se guarda sin confirmar.

POR QUE NO ALCANZA CON EXTRAER EL TEXTO
---------------------------------------
Un folleto es una grilla de celdas, no un documento lineal. Si extraes el texto
en orden de lectura te queda una sopa donde el precio de un producto termina
pegado a la descripcion del de al lado. Por eso el parseo es ESPACIAL: se
anclan los precios (numeros grandes, tipografia mas alta de la pagina) y se
captura la descripcion por cercania geometrica alrededor de cada ancla.

CALIBRACION
-----------
Los umbrales de CALIBRACION estan puestos a ojo y hay que ajustarlos contra
folletos reales. Correr diagnosticar() sobre un folleto ANTES de confiar en la
extraccion: dice si el PDF trae texto, cuantas anclas de precio detecta y como
quedaron los primeros bloques.

DEPENDENCIA NUEVA
-----------------
PyMuPDF (import fitz). Una sola rueda, sin binario externo: lee texto con
coordenadas Y rasteriza para OCR. Reemplaza a pdfplumber + poppler.
    uv pip install pymupdf
Si no esta instalado, el modulo cae automaticamente a OCR con Tesseract, que
ya usa factura_ocr.py.
"""

from __future__ import annotations

import os
import re
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone

try:
    import fitz  # PyMuPDF
    HAY_FITZ = True
except ImportError:
    HAY_FITZ = False

# Rutas donde el instalador de UB-Mannheim deja tesseract.exe en Windows.
# Es habitual que quede instalado pero fuera del PATH: en ese caso pytesseract
# falla aunque el programa este. Lo buscamos antes de dar por perdido el OCR.
_RUTAS_TESSERACT = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
    os.path.expandvars(r"%USERPROFILE%\AppData\Local\Tesseract-OCR\tesseract.exe"),
)


def _intentar_ubicar_tesseract() -> str:
    """Si tesseract.exe existe en una ruta conocida, apuntar pytesseract ahi."""
    try:
        import pytesseract
    except ImportError:
        return ""
    # Primero la ruta guardada por buscar_tesseract.py: si el instalador
    # lo dejo en un lugar raro, es la unica que lo encuentra.
    rutas = []
    try:
        from config import cfg
        guardada = (cfg().get("tesseract_ruta") or "").strip()
        if guardada:
            rutas.append(guardada)
    except Exception:
        pass
    rutas.extend(_RUTAS_TESSERACT)

    for ruta in rutas:
        if ruta and os.path.isfile(ruta):
            pytesseract.pytesseract.tesseract_cmd = ruta
            try:
                pytesseract.get_tesseract_version()
                return ruta
            except Exception:
                continue
    return ""


def diagnostico_dependencias() -> dict:
    """Que hay y que falta, con el comando exacto para instalarlo.

    Mismo criterio que factura_ocr._tesseract_disponible(): imports en
    diferido y mensajes que distinguen el paquete de Python del programa.
    """
    d = {}
    try:
        __import__("fitz")
        d["pymupdf"] = (True, "")
    except ImportError:
        d["pymupdf"] = (False, "uv pip install pymupdf   (para leer PDFs)")

    try:
        __import__("PIL.Image")
        d["pillow"] = (True, "")
    except ImportError:
        d["pillow"] = (False, "uv pip install pillow   (para leer imagenes)")

    try:
        import pytesseract
        d["pytesseract"] = (True, "")
        try:
            v = pytesseract.get_tesseract_version()
            d["tesseract"] = (True, str(v))
        except Exception as e:
            ruta = _intentar_ubicar_tesseract()
            if ruta:
                d["tesseract"] = (True, f"encontrado fuera del PATH en {ruta}")
            else:
                d["tesseract"] = (False,
                                  "Falta el PROGRAMA Tesseract, que se instala aparte "
                                  "(no con pip). Bajalo de "
                                  "https://github.com/UB-Mannheim/tesseract/wiki "
                                  "y marca el idioma Spanish al instalar. "
                                  f"Detalle tecnico: {e}")
    except ImportError:
        d["pytesseract"] = (False, "uv pip install pytesseract")
        d["tesseract"] = (False, "Depende de pytesseract")
    return d


def _cargar_ocr():
    """Devuelve (Image, pytesseract, Output) o levanta con el motivo exacto."""
    faltan = [msg for ok, msg in
              (diagnostico_dependencias()[k] for k in ("pillow", "pytesseract", "tesseract"))
              if not ok]
    if faltan:
        raise RuntimeError("Para leer imagenes o PDFs escaneados falta:\n\n  - "
                           + "\n  - ".join(faltan))
    from PIL import Image
    import pytesseract
    from pytesseract import Output
    return Image, pytesseract, Output


def _hay_ocr() -> bool:
    try:
        _cargar_ocr()
        return True
    except Exception:
        return False


CALIBRACION = {
    # Un token cuenta como precio si su altura supera la mediana de la pagina
    # por este factor. En folletos el precio es la tipografia mas grande.
    "factor_altura_precio": 1.35,
    # Radio maximo de captura de descripcion, como fraccion de la distancia
    # mediana entre precios vecinos. Es un tope: cada palabra va SIEMPRE al
    # ancla mas cercana, nunca a varias.
    "radio_captura": 1.10,
    # Las celdas de folleto son mas altas que anchas y la descripcion va
    # arriba/abajo del precio, no al costado. Penalizar el eje horizontal
    # evita robarle palabras al producto de al lado.
    "peso_horizontal": 2.2,
    # Precio minimo plausible: descarta "2x1", numeracion de pagina, gramajes.
    "precio_minimo": 100.0,
    "precio_maximo": 2_000_000.0,
    # OCR: confianza minima por palabra (0-100).
    "conf_minima_ocr": 45,
    # DPI de rasterizado para OCR.
    "dpi_ocr": 200,
}

EXTENSIONES = (".pdf", ".jpg", ".jpeg", ".png", ".webp")


def requisitos_de(path: str) -> list:
    """Que dependencias faltan para ESTE archivo. Lista vacia = se puede leer.

    Un PDF con capa de texto solo necesita PyMuPDF. Una imagen necesita OCR.
    Por eso el chequeo es por archivo y no por lote: que falte Tesseract no
    tiene por que impedir leer los PDFs de la misma carpeta.
    """
    dep = diagnostico_dependencias()
    falta_ocr = [dep[k][1] for k in ("pillow", "pytesseract", "tesseract")
                 if not dep[k][0]]

    if os.path.splitext(path)[1].lower() != ".pdf":
        return falta_ocr

    if not dep["pymupdf"][0]:
        return [dep["pymupdf"][1]]
    if not falta_ocr:
        return []          # con OCR disponible cualquier PDF se puede leer

    # Sin OCR, solo sirven los PDFs con capa de texto. La mayoria de los
    # folletos de mayorista son de diseno, exportados aplanados: no la tienen.
    # Conviene averiguarlo aca y no fallar recien al abrirlo.
    return [] if tiene_capa_de_texto(path) else [
        "Este PDF es de diseno (paginas como imagen), no trae texto, "
        "asi que necesita OCR igual que una foto."] + falta_ocr


def tiene_capa_de_texto(path: str) -> bool:
    """True si del texto embebido del PDF salen precios."""
    try:
        import fitz
    except ImportError:
        return False
    try:
        doc = fitz.open(path)
    except Exception:
        return False
    try:
        for page in doc:
            palabras = [Palabra(w[0], w[1], w[2], w[3], w[4])
                        for w in page.get_text("words") if w[4].strip()]
            if palabras and detectar_anclas(
                    _fusionar_precios_partidos(palabras, CALIBRACION), CALIBRACION):
                return True
        return False
    finally:
        doc.close()


# --------------------------------------------------------------------------
# Modelo
# --------------------------------------------------------------------------

@dataclass
class Palabra:
    x0: float
    y0: float
    x1: float
    y1: float
    texto: str
    conf: float = 100.0

    @property
    def alto(self) -> float:
        return self.y1 - self.y0

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2


@dataclass
class ItemFolleto:
    descripcion: str
    precio: float
    pagina: int
    fuente: str = ""
    archivo: str = ""
    bulto: str = ""              # "x 12 un", "bulto cerrado", si aparece
    confianza: float = 0.0       # 0..1, que tan limpio salio el bloque
    producto_id: int | None = None
    similitud: float | None = None
    crudo: list = field(default_factory=list)


# --------------------------------------------------------------------------
# Extraccion de palabras con coordenadas
# --------------------------------------------------------------------------

def _palabras_pdf_texto(path: str):
    """Devuelve {pagina: [Palabra]} usando la capa de texto del PDF."""
    doc = fitz.open(path)
    paginas = {}
    for n, page in enumerate(doc, start=1):
        palabras = [Palabra(w[0], w[1], w[2], w[3], w[4])
                    for w in page.get_text("words") if w[4].strip()]
        if palabras:
            paginas[n] = palabras
    doc.close()
    return paginas


def _palabras_ocr_imagen(img, conf_min: float):
    _Image, pytesseract, Output = _cargar_ocr()
    datos = pytesseract.image_to_data(img, lang="spa", output_type=Output.DICT)
    palabras = []
    for i, txt in enumerate(datos["text"]):
        txt = (txt or "").strip()
        if not txt:
            continue
        try:
            conf = float(datos["conf"][i])
        except (TypeError, ValueError):
            conf = -1.0
        if conf < conf_min:
            continue
        x, y = datos["left"][i], datos["top"][i]
        w, h = datos["width"][i], datos["height"][i]
        palabras.append(Palabra(x, y, x + w, y + h, txt, conf))
    return palabras


def _palabras_pdf_ocr(path: str, cal: dict):
    Image, _pt, _o = _cargar_ocr()
    doc = fitz.open(path)
    paginas = {}
    zoom = cal["dpi_ocr"] / 72.0
    for n, page in enumerate(doc, start=1):
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        palabras = _palabras_ocr_imagen(img, cal["conf_minima_ocr"])
        if palabras:
            paginas[n] = palabras
    doc.close()
    return paginas


def extraer_palabras(path: str, cal: dict | None = None):
    """Devuelve (paginas, metodo). metodo: 'texto' | 'ocr' | 'ocr-imagen'."""
    cal = {**CALIBRACION, **(cal or {})}
    ext = os.path.splitext(path)[1].lower()

    if ext == ".pdf":
        if not HAY_FITZ:
            raise RuntimeError(
                "Falta PyMuPDF para leer PDFs. Instalar con: uv pip install pymupdf")
        paginas = _palabras_pdf_texto(path)
        # Criterio: la capa de texto sirve si de ella salen precios. Contar
        # palabras no alcanza — un folleto de pocas celdas tiene poco texto
        # pero perfectamente legible, y mandarlo a OCR es peor y mas lento.
        if paginas and any(detectar_anclas(_fusionar_precios_partidos(v, cal), cal)
                           for v in paginas.values()):
            return paginas, "texto"
        return _palabras_pdf_ocr(path, cal), "ocr"

    Image, _pt, _o = _cargar_ocr()
    return {1: _palabras_ocr_imagen(Image.open(path), cal["conf_minima_ocr"])}, "ocr-imagen"


# --------------------------------------------------------------------------
# Deteccion de precios
# --------------------------------------------------------------------------

# "$1.799,90"  "1.799,90"  "$ 1799"  "1799,90"
_RE_PRECIO = re.compile(r"^\$?\s*(\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:,\d{1,2})?)$")
_RE_BULTO = re.compile(
    r"(bulto|x\s*\d{1,3}\s*(un|u|unid|kg|lt|l)\b|c/u|cada\s*uno)", re.IGNORECASE)


def _a_precio(txt: str, cal: dict):
    m = _RE_PRECIO.match((txt or "").strip())
    if not m:
        return None
    v = m.group(1).replace(".", "").replace(",", ".")
    try:
        val = float(v)
    except ValueError:
        return None
    if not (cal["precio_minimo"] <= val <= cal["precio_maximo"]):
        return None
    return val


def _fusionar_precios_partidos(palabras, cal):
    """Junta '$', '1.799' y ',90' cuando el PDF los devuelve separados."""
    palabras = sorted(palabras, key=lambda w: (round(w.cy, 1), w.x0))
    salida, i = [], 0
    while i < len(palabras):
        w = palabras[i]
        if w.texto.strip() == "$" and i + 1 < len(palabras):
            sig = palabras[i + 1]
            if abs(sig.cy - w.cy) < w.alto and sig.x0 - w.x1 < w.alto * 2:
                salida.append(Palabra(w.x0, min(w.y0, sig.y0), sig.x1,
                                      max(w.y1, sig.y1),
                                      "$" + sig.texto, min(w.conf, sig.conf)))
                i += 2
                continue
        salida.append(w)
        i += 1
    return salida


def detectar_anclas(palabras, cal):
    """Palabras que son precios y ademas tienen tipografia grande."""
    if not palabras:
        return []
    alturas = [w.alto for w in palabras if w.alto > 0]
    if not alturas:
        return []
    corte = statistics.median(alturas) * cal["factor_altura_precio"]
    anclas = []
    for w in palabras:
        val = _a_precio(w.texto, cal)
        if val is not None and w.alto >= corte:
            anclas.append((w, val))
    # Si la tipografia no discrimina (folletos muy planos), aceptar todo precio
    if not anclas:
        anclas = [(w, v) for w in palabras
                  if (v := _a_precio(w.texto, cal)) is not None]
    return anclas


def _radio(anclas, cal, ancho_pagina):
    if len(anclas) < 2:
        return ancho_pagina * 0.35
    dists = []
    for i, (a, _) in enumerate(anclas):
        mejor = None
        for j, (b, _) in enumerate(anclas):
            if i == j:
                continue
            d = ((a.cx - b.cx) ** 2 + (a.cy - b.cy) ** 2) ** 0.5
            if mejor is None or d < mejor:
                mejor = d
        if mejor:
            dists.append(mejor)
    if not dists:
        return ancho_pagina * 0.35
    return statistics.median(dists) * cal["radio_captura"]


# --------------------------------------------------------------------------
# Armado de bloques producto
# --------------------------------------------------------------------------

def analizar_pagina(palabras, pagina, cal):
    palabras = _fusionar_precios_partidos(palabras, cal)
    anclas = detectar_anclas(palabras, cal)
    if not anclas:
        return []

    ancho = max(w.x1 for w in palabras) - min(w.x0 for w in palabras) or 1.0
    radio = _radio(anclas, cal, ancho)
    ids_ancla = {id(w) for w, _ in anclas}

    # Asignacion exclusiva: cada palabra va al ancla mas cercana y a una sola.
    peso = cal["peso_horizontal"]

    def _dist(w, a):
        return (((w.cx - a.cx) * peso) ** 2 + (w.cy - a.cy) ** 2) ** 0.5

    reparto = {i: [] for i in range(len(anclas))}
    for w in palabras:
        if id(w) in ids_ancla:
            continue
        mejor_i, mejor_d = None, None
        for i, (a, _) in enumerate(anclas):
            d = _dist(w, a)
            if mejor_d is None or d < mejor_d:
                mejor_i, mejor_d = i, d
        if mejor_i is not None and mejor_d <= radio:
            reparto[mejor_i].append((mejor_d, w))

    items = []
    for i, (ancla, valor) in enumerate(anclas):
        cercanas = reparto[i]
        if not cercanas:
            continue
        cercanas.sort(key=lambda t: (round(t[1].cy, 1), t[1].x0))
        tokens = [w.texto for _, w in cercanas]
        desc = re.sub(r"\s+", " ", " ".join(tokens)).strip(" -.,")

        bulto = ""
        mb = _RE_BULTO.search(desc)
        if mb:
            bulto = mb.group(0)

        letras = sum(c.isalpha() for c in desc)
        conf = min(1.0, letras / 25.0) * (0.5 if len(desc) > 140 else 1.0)
        conf *= min(1.0, statistics.mean(w.conf for _, w in cercanas) / 100.0)

        items.append(ItemFolleto(descripcion=desc, precio=valor, pagina=pagina,
                                 bulto=bulto, confianza=round(conf, 2),
                                 crudo=tokens))
    return items


def analizar(path: str, fuente: str = "", cal: dict | None = None):
    """Analiza un folleto completo. Devuelve (items, info)."""
    cal = {**CALIBRACION, **(cal or {})}
    paginas, metodo = extraer_palabras(path, cal)
    items = []
    for n, palabras in sorted(paginas.items()):
        for it in analizar_pagina(palabras, n, cal):
            it.fuente = fuente or _fuente_desde_nombre(path)
            it.archivo = os.path.basename(path)
            items.append(it)
    info = {
        "metodo": metodo,
        "paginas": len(paginas),
        "palabras": sum(len(v) for v in paginas.values()),
        "items": len(items),
        "fecha": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
    }
    return items, info


def _fuente_desde_nombre(path: str) -> str:
    n = os.path.basename(path).lower()
    for clave in ("vital", "maxiconsumo", "masmelos", "carrefour", "diarco", "yaguar"):
        if clave in n:
            return clave
    return "desconocida"


# --------------------------------------------------------------------------
# Carpeta vigilada (el TPV ya vive en Dropbox: sirve igual que Drive)
# --------------------------------------------------------------------------

def listar_pendientes(carpeta: str, ya_procesados=()):
    """Archivos de folleto sin procesar. ya_procesados: iterable de nombres."""
    if not os.path.isdir(carpeta):
        return []
    hechos = set(ya_procesados)
    out = []
    for nombre in sorted(os.listdir(carpeta)):
        if nombre.startswith(".") or nombre in hechos:
            continue
        if os.path.splitext(nombre)[1].lower() in EXTENSIONES:
            out.append(os.path.join(carpeta, nombre))
    return out


# --------------------------------------------------------------------------
# Diagnostico: correr esto ANTES de confiar en la extraccion
# --------------------------------------------------------------------------

def diagnosticar(path: str, muestra: int = 12, cal: dict | None = None):
    cal = {**CALIBRACION, **(cal or {})}
    print(f"Archivo: {os.path.basename(path)}")
    print(f"Tamano : {os.path.getsize(path) / 1_048_576:.1f} MB")
    try:
        paginas, metodo = extraer_palabras(path, cal)
    except Exception as exc:
        print(f"ERROR extrayendo: {type(exc).__name__}: {exc}")
        return
    total = sum(len(v) for v in paginas.values())
    print(f"Metodo : {metodo}   ({'capa de texto' if metodo == 'texto' else 'OCR'})")
    print(f"Paginas: {len(paginas)}   Palabras: {total}")
    if metodo != "texto":
        print("  OJO: sin capa de texto. El OCR sobre folleto de diseno suele "
              "fallar en tipografias decorativas. Revisar item por item.")
    for n, palabras in sorted(paginas.items()):
        anclas = detectar_anclas(_fusionar_precios_partidos(palabras, cal), cal)
        print(f"  pag {n}: {len(palabras)} palabras, {len(anclas)} anclas de precio")
    items, info = analizar(path, cal=cal)
    print(f"\nItems detectados: {info['items']}")
    if items:
        prom = statistics.mean(i.confianza for i in items)
        print(f"Confianza promedio: {prom:.2f}   "
              f"(bajo 0.5 = recalibrar antes de usar)")
    print(f"\nPrimeros {muestra}:")
    for it in items[:muestra]:
        print(f"  ${it.precio:>12,.2f}  [conf {it.confianza:.2f}]  "
              f"{it.descripcion[:70]}")
    print("\nSi la descripcion viene mezclada con la del producto de al lado, "
          "bajar 'radio_captura'. Si viene cortada, subirlo.")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        diagnosticar(sys.argv[1])
    else:
        print(__doc__)
        for nombre, (ok, msg) in diagnostico_dependencias().items():
            print(f"  {'[OK]  ' if ok else '[FALTA]'} {nombre:<12} {msg}")
        print("Uso: python folletos.py <ruta_al_folleto.pdf>")

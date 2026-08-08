"""
fuentes.py — Precios de referencia externos para TPV Arai.

Un adaptador por mayorista. Cada uno es independiente: si uno falla o esta
caido, los demas siguen. El boton "Actualizar precios" corre todos los
automaticos y deja los manuales marcados como vencidos.

ESTADO REAL DE CADA FUENTE (verificado 06/08/2026):

    carrefour   AUTOMATICO   VTEX expone /api/catalog_system/pub/products/search
                             en JSON publico. Es la fuente mas confiable.
    maxiconsumo  FRAGIL      Magento, precios publicos por sucursal en la URL.
                             Hay que parsear HTML: se rompe si tocan el template.
    vital        MANUAL      Precios detras de login de cliente.
    masmelos     MANUAL      El catalogo vive en secure.sig2k.com (plataforma
                             de terceros) con login. masmelos.com.ar es solo
                             el sitio institucional, no tiene precios.

Para vital y masmelos: importar_csv(). Automatizar un login ajeno suele violar
los terminos de uso y expone la cuenta de cliente a bloqueo.

ADVERTENCIA: los adaptadores de red de este archivo NO pudieron probarse
contra los sitios reales al escribirlos. Correr autotest() antes de confiar.
"""

from __future__ import annotations

import csv
import json
import os
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher

TIMEOUT = 20
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
PAUSA_ENTRE_PEDIDOS = 1.2  # segundos, para no golpear los sitios


# --------------------------------------------------------------------------
# Schema (migracion para db.py)
# --------------------------------------------------------------------------

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS precios_referencia (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    producto_id       INTEGER REFERENCES productos(id) ON DELETE CASCADE,
    fuente            TEXT    NOT NULL,
    descripcion_fuente TEXT   NOT NULL,
    precio            REAL    NOT NULL,
    es_oferta         INTEGER NOT NULL DEFAULT 0,
    similitud         REAL,
    url               TEXT,
    fecha             TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_precios_ref_prod
    ON precios_referencia(producto_id, fuente, fecha);

CREATE TABLE IF NOT EXISTS fuentes_estado (
    fuente        TEXT PRIMARY KEY,
    ultima_corrida TEXT,
    ok            INTEGER NOT NULL DEFAULT 0,
    encontrados   INTEGER NOT NULL DEFAULT 0,
    mensaje       TEXT
);
"""


@dataclass
class PrecioRef:
    fuente: str
    descripcion_fuente: str
    precio: float
    es_oferta: bool = False
    url: str = ""
    producto_id: int | None = None
    similitud: float | None = None


def _ahora() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _get(url: str, headers: dict | None = None) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read()


def _a_float(txt: str):
    """'$ 1.799,90' -> 1799.90. Devuelve None si no hay numero."""
    m = re.search(r"(\d[\d.]*,\d{2}|\d[\d.]*\.\d{2}|\d+)", txt or "")
    if not m:
        return None
    v = m.group(1)
    if "," in v:
        v = v.replace(".", "").replace(",", ".")
    elif v.count(".") > 1:
        v = v.replace(".", "")
    try:
        return float(v)
    except ValueError:
        return None


# --------------------------------------------------------------------------
# Adaptador: Maxi Carrefour (VTEX) — AUTOMATICO
# --------------------------------------------------------------------------

CARREFOUR_BASE = "https://www.carrefour.com.ar"


def buscar_carrefour(termino: str, limite: int = 5):
    url = (f"{CARREFOUR_BASE}/api/catalog_system/pub/products/search"
           f"?ft={urllib.parse.quote(termino)}&_from=0&_to={max(0, limite - 1)}")
    datos = json.loads(_get(url, {"Accept": "application/json"}))
    out = []
    for prod in datos:
        for item in prod.get("items", []):
            for oferta in item.get("sellers", []):
                co = (oferta.get("commertialOffer") or {})
                precio = co.get("Price") or co.get("ListPrice")
                if not precio:
                    continue
                lista = co.get("ListPrice") or precio
                out.append(PrecioRef(
                    fuente="carrefour",
                    descripcion_fuente=prod.get("productName", ""),
                    precio=float(precio),
                    es_oferta=float(precio) < float(lista) * 0.995,
                    url=f"{CARREFOUR_BASE}/{prod.get('linkText','')}/p",
                ))
                break
            break
    return out


# --------------------------------------------------------------------------
# Adaptador: Maxiconsumo (Magento) — FRAGIL
# --------------------------------------------------------------------------

MAXI_BASE = "https://www.maxiconsumo.com"
MAXI_SUCURSAL = "sucursal_moreno"

_RE_MAXI_ITEM = re.compile(
    r'class="product-item-link"[^>]*href="([^"]+)"[^>]*>\s*(.*?)\s*</a>(.*?)'
    r'(?=class="product-item-link"|</ol>)', re.S)
_RE_MAXI_PRECIO = re.compile(r'data-price-amount="([\d.]+)"')


def buscar_maxiconsumo(termino: str, limite: int = 5):
    url = (f"{MAXI_BASE}/{MAXI_SUCURSAL}/catalogsearch/result/"
           f"?q={urllib.parse.quote(termino)}")
    html = _get(url).decode("utf-8", "replace")
    out = []
    for href, nombre, bloque in _RE_MAXI_ITEM.findall(html)[:limite]:
        precios = [float(p) for p in _RE_MAXI_PRECIO.findall(bloque)]
        if not precios:
            continue
        out.append(PrecioRef(
            fuente="maxiconsumo",
            descripcion_fuente=re.sub(r"\s+", " ", nombre).strip(),
            precio=min(precios),          # el menor es el de bulto cerrado
            es_oferta=False,
            url=href,
        ))
    return out


# --------------------------------------------------------------------------
# Fuentes manuales: Vital y MasMelos
# --------------------------------------------------------------------------

FUENTES_MANUALES = {
    "vital": "Precios detras de login de cliente. Exportar el pedido a CSV.",
    "masmelos": ("Catalogo en secure.sig2k.com con login. Descargar la lista "
                 "desde Pedidos Web y guardarla como CSV."),
}


def importar_csv(path: str, fuente: str, col_desc="descripcion", col_precio="precio"):
    """Importa una lista descargada a mano. Acepta ; o , como separador."""
    out = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        muestra = fh.read(4096)
        fh.seek(0)
        try:
            dial = csv.Sniffer().sniff(muestra, delimiters=";,\t")
        except csv.Error:
            dial = csv.excel
        for fila in csv.DictReader(fh, dialect=dial):
            claves = {k.strip().lower(): v for k, v in fila.items() if k}
            desc = claves.get(col_desc) or ""
            precio = _a_float(claves.get(col_precio) or "")
            if desc and precio:
                out.append(PrecioRef(fuente=fuente,
                                     descripcion_fuente=desc.strip(),
                                     precio=precio))
    return out


# --------------------------------------------------------------------------
# Matching contra el catalogo propio
# --------------------------------------------------------------------------

def _norm(t: str) -> str:
    t = (t or "").lower()
    t = t.translate(str.maketrans("áéíóúàèìòùäëïöüñ", "aeiouaeiouaeioun"))
    return re.sub(r"[^a-z0-9 ]+", " ", t)


def emparejar(refs, productos, umbral=0.62):
    """Asigna producto_id a cada PrecioRef por similitud de descripcion."""
    catalogo = [(p, _norm(p.get("descripcion", ""))) for p in productos]
    asignados = []
    for ref in refs:
        objetivo = _norm(ref.descripcion_fuente)
        mejor, score = None, 0.0
        for prod, norm_desc in catalogo:
            s = SequenceMatcher(None, objetivo, norm_desc).ratio()
            if s > score:
                mejor, score = prod, s
        if mejor and score >= umbral:
            ref.producto_id = mejor["id"]
            ref.similitud = round(score, 3)
            asignados.append(ref)
    return asignados


# --------------------------------------------------------------------------
# Entry point del boton "Actualizar precios"
# --------------------------------------------------------------------------

ADAPTADORES = {
    "carrefour": buscar_carrefour,
    "maxiconsumo": buscar_maxiconsumo,
}


def actualizar(productos, fuentes=None, progreso=None, max_productos=None):
    """Corre los adaptadores automaticos. Devuelve (refs, estado_por_fuente).

    productos: los mismos dicts que usa auditoria.auditar().
    progreso:  callable(hecho, total, texto) para la barra de la UI.
    max_productos: limite para no disparar cientos de pedidos de una.

    NO escribe en base: devuelve los resultados para que los guarde
    repositorio.guardar_precios_referencia().
    """
    fuentes = list(fuentes or ADAPTADORES)
    objetivo = [p for p in productos if p.get("descripcion")]
    if max_productos:
        objetivo = objetivo[:max_productos]

    refs, estado = [], {}
    total = len(fuentes) * len(objetivo)
    hecho = 0

    for nombre in fuentes:
        adaptador = ADAPTADORES.get(nombre)
        if adaptador is None:
            estado[nombre] = {"ok": False, "encontrados": 0,
                              "mensaje": FUENTES_MANUALES.get(
                                  nombre, "Fuente desconocida"),
                              "ultima_corrida": _ahora()}
            continue

        encontrados, fallos, ultimo_error = 0, 0, ""
        for prod in objetivo:
            hecho += 1
            if progreso:
                progreso(hecho, total, f"{nombre}: {prod['descripcion'][:40]}")
            try:
                hallados = adaptador(prod["descripcion"], limite=3)
            except Exception as exc:              # red, HTML cambiado, rate limit
                fallos += 1
                ultimo_error = f"{type(exc).__name__}: {exc}"
                if fallos >= 5:
                    break
                continue
            for r in emparejar(hallados, [prod]):
                refs.append(r)
                encontrados += 1
            time.sleep(PAUSA_ENTRE_PEDIDOS)

        estado[nombre] = {
            "ok": fallos < 5,
            "encontrados": encontrados,
            "mensaje": ultimo_error or f"{encontrados} precios actualizados",
            "ultima_corrida": _ahora(),
        }
    return refs, estado


def autotest(termino="aceite girasol 900"):
    """Prueba cada adaptador contra el sitio real. Correr antes de confiar."""
    for nombre, fn in ADAPTADORES.items():
        try:
            res = fn(termino, limite=3)
            print(f"[OK]    {nombre}: {len(res)} resultados")
            for r in res[:3]:
                print(f"          {r.precio:>12,.2f}  {r.descripcion_fuente[:60]}")
        except Exception as exc:
            print(f"[FALLA] {nombre}: {type(exc).__name__}: {exc}")
    for nombre, motivo in FUENTES_MANUALES.items():
        print(f"[MANUAL] {nombre}: {motivo}")


if __name__ == "__main__":
    autotest()


# --------------------------------------------------------------------------
# Descarga de folletos por URL
# --------------------------------------------------------------------------

VITAL_OFERTAS = "https://www.vital.com.ar/ofertas/"
SUCURSALES_VITAL = (
    "Abasto", "Avellaneda", "Bahía Blanca", "Burzaco", "El Talar", "La Plata",
    "Laferrere", "Loma Hermosa", "Malvinas Argentinas", "Mar del Plata",
    "Moreno", "Neuquén", "Pilar", "Posadas", "Quilmes", "Resistencia",
    "Salta", "San Justo", "Santa Fe", "Villa Ortúzar",
)

_RE_PDF_VITAL = re.compile(
    r'href="(https://www\.vital\.com\.ar/wp-content/uploads/folletos/[^"]+?\.pdf)[^"]*"')
_RE_TITULO_VITAL = re.compile(r"<h6[^>]*>(.*?)</h6>", re.S | re.I)


def descargar_archivo(url: str, carpeta: str, nombre: str = "") -> str:
    """Baja un PDF o imagen a la carpeta de folletos. Devuelve la ruta local."""
    os.makedirs(carpeta, exist_ok=True)
    limpia = url.split("?")[0]
    if not nombre:
        nombre = os.path.basename(limpia) or "folleto.pdf"
    if not os.path.splitext(nombre)[1]:
        nombre += ".pdf"
    nombre = re.sub(r"[^\w.\- ]+", "_", nombre)
    destino = os.path.join(carpeta, nombre)

    datos = _get(url)
    if datos[:4] not in (b"%PDF",) and not _parece_imagen(datos):
        raise ValueError("Lo que descargo no es un PDF ni una imagen. "
                         "Revisar que el link apunte al archivo y no a una pagina.")
    with open(destino, "wb") as fh:
        fh.write(datos)
    return destino


def _parece_imagen(b: bytes) -> bool:
    return (b[:3] == b"\xff\xd8\xff" or b[:8] == b"\x89PNG\r\n\x1a\n"
            or b[:4] == b"RIFF" or b[:6] in (b"GIF87a", b"GIF89a"))


def listar_folletos_vital(sucursal: str = "Moreno"):
    """Devuelve [(titulo, url_pdf)] de la pagina publica de ofertas de Vital.

    NOTA: la pagina abre en Abasto por defecto. El selector de sucursal parece
    manejarse del lado del cliente; se intenta con cookie y con parametro, pero
    NO esta verificado que devuelva folletos distintos por sucursal. Comparar
    contra lo que muestra el navegador antes de confiar.
    """
    base = {"Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "es-AR,es;q=0.9",
            "Referer": "https://www.vital.com.ar/"}
    intentos = []
    if sucursal:
        suc = urllib.parse.quote(sucursal)
        intentos.append((VITAL_OFERTAS + "?sucursal=" + suc,
                         {**base, "Cookie": f"sucursal={suc}"}))
    intentos.append((VITAL_OFERTAS, base))     # sin sucursal: la pagina por defecto

    html, ultimo = "", None
    for url, headers in intentos:
        try:
            html = _get(url, headers).decode("utf-8", "replace")
            if _RE_PDF_VITAL.search(html):
                break
        except Exception as exc:
            ultimo = exc
    if not html:
        raise ultimo or RuntimeError("No hubo respuesta de vital.com.ar")

    urls, vistas = [], set()
    for u in _RE_PDF_VITAL.findall(html):
        if u not in vistas:
            vistas.add(u)
            urls.append(u)
    titulos = [re.sub(r"<[^>]+>", "", t).strip() for t in _RE_TITULO_VITAL.findall(html)]
    salida = []
    for i, u in enumerate(urls):
        titulo = titulos[i] if i < len(titulos) else os.path.basename(u)
        salida.append((titulo or os.path.basename(u), u))
    return salida

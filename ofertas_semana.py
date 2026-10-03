"""
ofertas_semana.py — Flyer "Ofertas de la semana" (grilla de hasta 9 productos).

Una sola imagen PNG lista para mandar por WhatsApp o imprimir: titulo,
leyenda "valido hasta", cartel opcional de descuento en efectivo, una
tarjeta por producto (foto, precio, unidad y nombre) y pie con los datos
del negocio.

Los precios son los que hoy muestra el sistema (precio de lista o promo
vigente, la misma logica de etiquetas/folleto/placas). El cartel de
descuento es SOLO informativo: no modifica ningun precio de la imagen.

Formatos:
    a4       1240 x 1754 — para imprimir o mandar como imagen
    story    1080 x 1920 — estado de WhatsApp / historias
"""

import logging
import os
from datetime import date, datetime, timedelta
from math import cos, pi, sin

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

import imagenes
from config import cfg
from etiquetas import _get_precios_producto
from placas import _ancho, _envolver, _fuente, _guardar, _hex, _mezclar

FORMATOS_OFERTAS = {
    "a4":    (1240, 1754),
    "story": (1080, 1920),
}
MAX_PRODUCTOS = 9
_S = 2   # factor de supersampling: las formas se dibujan al doble y se reducen

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre"]

_AMARILLO = (245, 197, 66)
_TINTA = (31, 24, 20)

# Impact viene con Windows y es condensada y pesada, parecida a la del
# diseno de referencia. Si no esta, cae a Arial Bold / DejaVu Bold.
_IMPACT = ("impact.ttf", "Impact.ttf",
           "/usr/share/fonts/truetype/msttcorefonts/Impact.ttf")
_cache_fuentes = {}


def _titulo(size):
    if size not in _cache_fuentes:
        f = None
        for nombre in _IMPACT:
            try:
                f = ImageFont.truetype(nombre, size)
                break
            except (OSError, IOError):
                continue
        _cache_fuentes[size] = f or _fuente(size, True)
    return _cache_fuentes[size]


def _fuente_ajustada(texto, ancho_max, size_max, size_min, fn=_titulo):
    """Mayor cuerpo (entre size_max y size_min) con el que el texto entra."""
    d = ImageDraw.Draw(Image.new("RGB", (4, 4)))
    size = size_max
    while size > size_min:
        f = fn(size)
        if _ancho(d, texto, f) <= ancho_max:
            return f
        size -= 2
    return fn(size_min)


# ── Formato ───────────────────────────────────────────────────────────────

def _fmt_precio(valor):
    """$2.000 (sin decimales) o $2.899,10 (con centavos), estilo argentino."""
    v = round(float(valor), 2)
    if abs(v - round(v)) < 0.005:
        return "$" + f"{int(round(v)):,}".replace(",", ".")
    s = f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return "$" + s


def fecha_sugerida():
    """Proximo domingo (o hoy si es domingo)."""
    hoy = date.today()
    return hoy + timedelta(days=(6 - hoy.weekday()) % 7)


def parsear_fecha(texto):
    """dd/mm/aaaa o dd/mm (año actual). Devuelve date o None si no se entiende."""
    t = (texto or "").strip().replace("-", "/").replace(".", "/")
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(t, fmt).date()
        except ValueError:
            pass
    try:
        return datetime.strptime(t + f"/{date.today().year}", "%d/%m/%Y").date()
    except ValueError:
        return None


def _leyenda_validez(fecha):
    return f"VÁLIDO HASTA EL {fecha.day} DE {MESES[fecha.month - 1].upper()}"


MODOS_PRECIO = {
    "Precio de lista (sin promos)":            "lista",
    "Precio de 1 unidad (con promo directa)":  "unitario",
    "El más barato (con promos por cantidad)": "cantidad",
}


def _datos_precio(prod, modo="unitario"):
    """(precio, cantidad) que muestra el flyer. Nunca elige solo una cantidad.

    lista:    precio_base, ignora toda promocion.
    unitario: lo que paga quien lleva 1 unidad (promo directa si hay, si no
              el de lista). No muestra jamas "a partir de N".
    cantidad: el escalon mas barato por unidad; si es por cantidad, la
              tarjeta lo aclara con "a partir de N".
    """
    base = float(prod["precio_base"]) + float(prod.get("_recargo", 0.0))
    if modo == "lista":
        return base, 1
    precios = _get_precios_producto(prod["id"], prod["precio_base"],
                                    prod.get("_recargo", 0.0))
    if not precios:
        return base, 1
    if modo == "cantidad":
        p = precios[0]
        return float(p["precio"]), int(p["cantidad"])
    unitarios = [p for p in precios if int(p["cantidad"]) == 1]
    if unitarios:
        return float(min(p["precio"] for p in unitarios)), 1
    return base, 1


# ── Imagenes ──────────────────────────────────────────────────────────────

TAM_FOTO = {
    "Normal":                    "normal",
    "Grande":                    "grande",
    "Muy grande (foto arriba)":  "muy_grande",
}
_PCT_FOTO = {"normal": 0.40, "grande": 0.52}   # ancho de la foto en la tarjeta


def _a_rgb_blanco(img):
    """RGB; si la imagen tiene transparencia se apoya sobre blanco (no negro)."""
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        base = Image.new("RGB", rgba.size, (255, 255, 255))
        base.paste(rgba, mask=rgba.getchannel("A"))
        return base
    return img.convert("RGB")


def _recortar_blanco(img, umbral=14, margen=0.03):
    """Saca los margenes blancos de una foto de producto.

    Muchas fotos traen el producto chico en medio de un lienzo blanco:
    al recortarlo, el mismo producto ocupa mucho mas lugar en la tarjeta.
    Si la foto no tiene margen blanco (o el recorte dejaria casi nada),
    se devuelve igual.
    """
    dif = ImageChops.difference(img, Image.new("RGB", img.size, (255, 255, 255)))
    caja = dif.convert("L").point(lambda v: 255 if v > umbral else 0).getbbox()
    if not caja:
        return img
    x0, y0, x1, y1 = caja
    if (x1 - x0) * (y1 - y0) < 0.03 * img.width * img.height:
        return img
    mx_, my_ = int((x1 - x0) * margen) + 1, int((y1 - y0) * margen) + 1
    return img.crop((max(0, x0 - mx_), max(0, y0 - my_),
                     min(img.width, x1 + mx_), min(img.height, y1 + my_)))


def _cubrir(img, w, h, foco_y=0.5):
    """Escala y recorta la imagen para llenar w x h (sin deformar)."""
    esc = max(w / img.width, h / img.height)
    nuevo = (max(w, int(img.width * esc + 0.5)), max(h, int(img.height * esc + 0.5)))
    img = img.resize(nuevo, Image.LANCZOS)
    x0 = (nuevo[0] - w) // 2
    y0 = int((nuevo[1] - h) * foco_y)
    return img.crop((x0, y0, x0 + w, y0 + h))


def _foto_en_caja(prod, ancho, alto, recortar):
    """Foto del producto contenida (sin recortar el producto) en ancho x alto."""
    marco = Image.new("RGB", (ancho, alto), (255, 255, 255))
    img = imagenes.cargar_imagen_pil(prod.get("imagen_url"))
    if img:
        img = _a_rgb_blanco(img)
        if recortar:
            img = _recortar_blanco(img)
        esc = min(ancho / img.width, alto / img.height)
        nuevo = (max(1, int(img.width * esc)), max(1, int(img.height * esc)))
        img = img.resize(nuevo, Image.LANCZOS)
        marco.paste(img, ((ancho - nuevo[0]) // 2, (alto - nuevo[1]) // 2))
    return marco


def _pegar_marco(placa, marco, x, y, radio=12):
    w, h = marco.size
    mask = Image.new("L", (w * _S, h * _S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w * _S, h * _S],
                                           radius=radio * _S, fill=255)
    placa.paste(marco, (x, y), mask.resize((w, h), Image.LANCZOS))


# ── Formas (se dibujan al doble de tamaño) ────────────────────────────────

def _pts(puntos):
    return [(int(x * _S), int(y * _S)) for x, y in puntos]


def _rr(d, caja, radio, **kw):
    x0, y0, x1, y1 = caja
    d.rounded_rectangle([x0 * _S, y0 * _S, x1 * _S, y1 * _S],
                        radius=radio * _S, **kw)


def _circulo(d, cx, cy, r, **kw):
    d.ellipse([(cx - r) * _S, (cy - r) * _S, (cx + r) * _S, (cy + r) * _S], **kw)


def _sello(cx, cy, r, lobulos=26, onda=0.045):
    """Puntos de un circulo con borde ondulado (el cartel del descuento)."""
    pts = []
    for i in range(lobulos * 12):
        a = 2 * pi * i / (lobulos * 12)
        rr = r * (1 + onda * cos(lobulos * a))
        pts.append((cx + rr * cos(a), cy + rr * sin(a)))
    return pts


def _carrito(d, x, y, color, grosor=8):
    """Carrito de compras simple; (x, y) es la esquina superior izquierda."""
    linea = [(x, y), (x + 18, y), (x + 36, y + 62), (x + 100, y + 62),
             (x + 116, y + 20), (x + 26, y + 20)]
    d.line(_pts(linea), fill=color, width=grosor * _S, joint="curve")
    _circulo(d, x + 44, y + 84, 9, fill=color)
    _circulo(d, x + 92, y + 84, 9, fill=color)


# ══════════════════════════════════════════════════════════════════════════
# Generador
# ══════════════════════════════════════════════════════════════════════════

def generar_flyer_ofertas(productos, titulo="OFERTAS", subtitulo="DE LA SEMANA",
                          valido_hasta=None, descuento_pct=0, texto_boton="",
                          formato="a4", carpeta=None, modo_precio="unitario",
                          foto_fondo=None, tam_foto="normal", recortar_blanco=True):
    """Genera el flyer y devuelve la ruta del PNG.

    productos:     de 1 a 9 dicts de producto (como los de get_productos)
    valido_hasta:  date o None (sin leyenda)
    descuento_pct: > 0 muestra el cartel "-N% pagando en efectivo"
    texto_boton:   texto de la pildora del pie ("" = sin pildora ni carrito)
    modo_precio:   "lista" | "unitario" | "cantidad" (ver _datos_precio)
    foto_fondo:    ruta de una foto para el encabezado (None = encabezado liso)
    tam_foto:      "normal" | "grande" | "muy_grande" (foto arriba del texto)
    recortar_blanco: saca los margenes blancos de las fotos de producto
    """
    n = len(productos)
    if not 1 <= n <= MAX_PRODUCTOS:
        raise ValueError(f"El flyer lleva entre 1 y {MAX_PRODUCTOS} productos")

    W, H = FORMATOS_OFERTAS.get(formato, FORMATOS_OFERTAS["a4"])
    c = cfg()
    rojo = _mezclar(_hex(c.get("folleto_color_precio"), "#DC2626"), (0, 0, 0), 0.18)
    rojo_osc = _mezclar(rojo, (0, 0, 0), 0.22)
    blanco = (255, 255, 255)

    fondo_img = None
    if foto_fondo:
        try:
            fondo_img = _a_rgb_blanco(Image.open(foto_fondo))
        except Exception as e:
            raise ValueError(f"No se pudo abrir la foto de fondo: {e}")

    # ── Medidas ──────────────────────────────────────────────────────────
    hh = int(H * (0.30 if fondo_img else 0.27))   # alto del encabezado
    fh = int(H * 0.085)                      # alto del pie
    mx = int(W * 0.07)
    gap_h = int(W * 0.03)
    gap_v = int(H * 0.02)
    gy0 = hh + int(H * 0.04)
    gy1 = H - fh - int(H * 0.035)
    cw = (W - 2 * mx - 2 * gap_h) // 3
    filas = (n + 2) // 3
    vertical = tam_foto == "muy_grande"
    if vertical:    # foto arriba: tarjetas mas altas, se aprovecha el lugar libre
        ch = min((gy1 - gy0 - (filas - 1) * gap_v) // filas, int(H * 0.215))
    else:
        ch = min((gy1 - gy0 - 2 * gap_v) // 3, int(H * 0.165))
    alto_bloque = filas * ch + (filas - 1) * gap_v
    by0 = gy0 + (gy1 - gy0 - alto_bloque) // 2
    pad = 14
    pct_foto = _PCT_FOTO.get(tam_foto, 0.40) - (0.04 if W < 1200 else 0)
    pw = int(cw * pct_foto)                  # ancho de la foto dentro de la tarjeta

    # Tamaños de texto que condicionan formas: se miden antes de dibujar
    f_tit = _fuente_ajustada(titulo.upper(), int(W * 0.52), int(H * 0.115), 60) if titulo else None
    f_sub = _fuente_ajustada(subtitulo.upper(), int(W * (0.40 if fondo_img else 0.50)),
                             int(H * 0.05), 30) if subtitulo else None
    f_val = None
    leyenda = _leyenda_validez(valido_hasta) if valido_hasta else ""
    if leyenda:
        f_val = _fuente_ajustada(leyenda, int(W * 0.50), int(H * 0.026), 20)
    dummy = ImageDraw.Draw(Image.new("RGB", (4, 4)))

    # Posiciones verticales del encabezado
    y_tit = int(H * 0.035)
    y_sub = y_tit + (int(f_tit.size * 1.12) if f_tit else 0)
    y_cinta = y_sub + (int(f_sub.size * 1.25) if f_sub else 0) + int(H * 0.012)

    # ── Capa de formas al doble de tamaño ────────────────────────────────
    big = Image.new("RGB", (W * _S, H * _S), _AMARILLO)
    d = ImageDraw.Draw(big)

    # Franja roja inferior en diagonal (el amarillo queda arriba)
    d.polygon(_pts([(0, gy0 + (gy1 - gy0) * 0.52), (W, gy0 + (gy1 - gy0) * 0.40),
                    (W, H), (0, H)]), fill=rojo)
    # Encabezado rojo con borde inferior en diagonal
    d.polygon(_pts([(0, 0), (W, 0), (W, hh - int(H * 0.025)), (0, hh)]), fill=rojo)
    if fondo_img:
        # La foto ocupa la derecha del encabezado y el rojo la tapa en
        # diagonal por la izquierda, donde va el titulo.
        rx0 = int(W * 0.40)
        foto = _cubrir(fondo_img, (W - rx0) * _S, hh * _S, foco_y=0.4)
        mask = Image.new("L", big.size, 0)
        ImageDraw.Draw(mask).polygon(
            _pts([(0, 0), (W, 0), (W, hh - int(H * 0.025)), (0, hh)]), fill=255)
        capa = Image.new("RGB", big.size, rojo)
        capa.paste(foto, (rx0 * _S, 0))
        big.paste(capa, (0, 0), mask)
        yb = lambda x: hh - int(H * 0.025) * x / W
        d.polygon(_pts([(0, 0), (0.64 * W, 0), (0.46 * W, yb(0.46 * W)), (0, hh)]),
                  fill=rojo)
    # Pie blanco con punta al centro
    d.polygon(_pts([(0, H - fh + 26), (W / 2, H - fh), (W, H - fh + 26),
                    (W, H), (0, H)]), fill=blanco)

    # Cinta de validez (cola de golondrina)
    cinta = None
    if leyenda:
        tw = _ancho(dummy, leyenda, f_val)
        ch_c = int(f_val.size * 2.0)
        cx0, cy0 = mx - 12, y_cinta
        cinta = (cx0, cy0, cx0 + tw + 90, cy0 + ch_c)
        mid, nt = cy0 + ch_c / 2, 26
        d.polygon(_pts([(cinta[0], cy0), (cinta[2], cy0), (cinta[2] - nt, mid),
                        (cinta[2], cy0 + ch_c), (cinta[0], cy0 + ch_c),
                        (cinta[0] + nt, mid)]),
                  fill=_AMARILLO, outline=rojo_osc, width=5 * _S)

    # Tarjetas: primero las sombras (una sola capa difuminada)
    cajas = []
    for i in range(n):
        fila, col = divmod(i, 3)
        en_fila = min(3, n - fila * 3)
        x_ini = mx + (3 - en_fila) * (cw + gap_h) // 2     # centra la ultima fila
        x0 = x_ini + col * (cw + gap_h)
        y0 = by0 + fila * (ch + gap_v)
        cajas.append((x0, y0, x0 + cw, y0 + ch))
    sombra = Image.new("RGBA", big.size, (0, 0, 0, 0))
    ds = ImageDraw.Draw(sombra)
    for (x0, y0, x1, y1) in cajas:
        ds.rounded_rectangle([x0 * _S, (y0 + 7) * _S, x1 * _S, (y1 + 7) * _S],
                             radius=22 * _S, fill=(0, 0, 0, 80))
    sombra = sombra.filter(ImageFilter.GaussianBlur(9 * _S))
    big = Image.alpha_composite(big.convert("RGBA"), sombra).convert("RGB")
    d = ImageDraw.Draw(big)
    for caja in cajas:
        _rr(d, caja, 22, fill=blanco)

    # Cartel de descuento en efectivo
    sello = None
    if descuento_pct and descuento_pct > 0:
        R = int(W * 0.115)
        cx, cy = W - mx - R + 12, hh - int(R * 0.55)
        sello = (cx, cy, R)
        d.polygon(_pts(_sello(cx, cy, R)), fill=rojo_osc)
        _circulo(d, cx, cy, int(R * 0.88), outline=blanco, width=3 * _S)

    # Pie: carrito + pildora + puntos de contacto
    pie_y = H - fh + 26 + (fh - 26) // 2
    pildora = None
    if texto_boton:
        f_btn = _fuente_ajustada(texto_boton.upper(), int(W * 0.26), int(fh * 0.34), 18)
        tw = _ancho(dummy, texto_boton.upper(), f_btn)
        px0 = mx + 130
        pildora = (px0, pie_y - int(fh * 0.24), px0 + tw + 70, pie_y + int(fh * 0.24), f_btn)
        _rr(d, pildora[:4], int(fh * 0.24), fill=rojo)
        _carrito(d, mx, pie_y - 42, rojo)

    contactos = [t for t in (c.get("negocio_telefono"), c.get("negocio_web"),
                             c.get("negocio_direccion")) if t and str(t).strip()]
    x_cont = int(W * 0.56)
    f_cont = _fuente_ajustada(max(contactos, key=len), W - mx - x_cont - 36,
                              int(fh * 0.20), 14, fn=lambda s: _fuente(s, True)) if contactos else None
    sep = int(fh * 0.26) if len(contactos) == 3 else int(fh * 0.30)
    y_cont0 = pie_y - (len(contactos) * sep) // 2 + 4
    for i in range(len(contactos)):
        _circulo(d, x_cont + 10, y_cont0 + i * sep + sep // 2 - 2, 10, fill=rojo)

    # ── Se reduce y se dibuja lo que lleva texto o fotos ─────────────────
    placa = big.resize((W, H), Image.LANCZOS)
    dr = ImageDraw.Draw(placa)

    if titulo:
        dr.text((mx, y_tit), titulo.upper(), font=f_tit, fill=blanco)
    if subtitulo:
        dr.text((mx + 4, y_sub), subtitulo.upper(), font=f_sub, fill=blanco)
    if cinta:
        tw = _ancho(dr, leyenda, f_val)
        bb = dr.textbbox((0, 0), leyenda, font=f_val)
        dr.text(((cinta[0] + cinta[2] - tw) / 2,
                 (cinta[1] + cinta[3]) / 2 - (bb[1] + bb[3]) / 2),
                leyenda, font=f_val, fill=_TINTA)

    # Logo (o nombre) arriba a la derecha
    _logo_o_nombre(placa, dr, W, mx, int(H * 0.03), int(H * 0.085),
                   rojo if fondo_img else blanco, plato=bool(fondo_img))

    if sello:
        cx, cy, R = sello
        f_pct = _fuente_ajustada(f"-{int(descuento_pct)}%", int(R * 1.3), int(R * 0.75), 30)
        t = f"-{int(descuento_pct)}%"
        dr.text((cx - _ancho(dr, t, f_pct) / 2, cy - R * 0.50), t, font=f_pct, fill=blanco)
        f_s = _fuente(max(16, int(R * 0.15)), True)
        for k, linea in enumerate(("PAGANDO EN", "EFECTIVO")):
            dr.text((cx - _ancho(dr, linea, f_s) / 2, cy + R * 0.30 + k * f_s.size * 1.2),
                    linea, font=f_s, fill=blanco)

    # Tarjetas de producto
    for prod, (x0, y0, x1, y1) in zip(productos, cajas):
        _tarjeta(placa, dr, prod, x0, y0, x1, y1, pad, pw, rojo, modo_precio,
                 vertical, recortar_blanco)

    # Pie
    if pildora:
        px0, py0, px1, py1, f_btn = pildora
        t = texto_boton.upper()
        bb = dr.textbbox((0, 0), t, font=f_btn)
        dr.text(((px0 + px1 - _ancho(dr, t, f_btn)) / 2,
                 (py0 + py1) / 2 - (bb[1] + bb[3]) / 2), t, font=f_btn, fill=_AMARILLO)
    for i, t in enumerate(contactos):
        bb = dr.textbbox((0, 0), str(t), font=f_cont)
        dr.text((x_cont + 30, y_cont0 + i * sep + sep // 2 - 2 - (bb[1] + bb[3]) / 2),
                str(t), font=f_cont, fill=_TINTA)

    return _guardar(placa, "ofertas_semana", carpeta)


def _logo_o_nombre(placa, dr, W, mx, y, alto_max, color, plato=False):
    c = cfg()
    logo = c.get("negocio_logo_path")
    if logo and os.path.isfile(logo):
        try:
            lg = Image.open(logo).convert("RGBA")
            esc = min(alto_max / lg.height, int(W * 0.26) / lg.width)
            lg = lg.resize((max(1, int(lg.width * esc)), max(1, int(lg.height * esc))),
                           Image.LANCZOS)
            mask = Image.new("L", lg.size, 0)
            ImageDraw.Draw(mask).rounded_rectangle([0, 0, lg.width, lg.height],
                                                   radius=14, fill=255)
            lg.putalpha(Image.composite(lg.getchannel("A"), mask, mask))
            if plato:   # sobre una foto el logo necesita un fondo propio
                dr.rounded_rectangle([W - mx - lg.width - 12, y - 10,
                                      W - mx + 12, y + lg.height + 10],
                                     radius=18, fill=(255, 255, 255))
            placa.paste(lg, (W - mx - lg.width, y), lg)
            return
        except Exception as e:
            logging.warning(f"No se pudo poner el logo en el flyer: {e}")
    nombre = (c.get("negocio_nombre") or "").strip()
    if nombre:
        f = _fuente_ajustada(nombre.upper(), int(W * 0.30), int(alto_max * 0.6), 22)
        tw = _ancho(dr, nombre.upper(), f)
        if plato:
            dr.rounded_rectangle([W - mx - tw - 18, y - 4, W - mx + 18,
                                  y + f.size * 1.2 + 12], radius=16,
                                 fill=(255, 255, 255))
        dr.text((W - mx - tw, y + 8), nombre.upper(), font=f, fill=color)


def _textos_tarjeta(prod, modo):
    precio, cant = _datos_precio(prod, modo)
    if prod.get("vendido_por_peso"):
        unidad = "x kg"
    elif cant > 1:
        unidad = f"c/u a partir de {cant}"
    else:
        unidad = "c/u"
    return _fmt_precio(precio), unidad, (prod.get("descripcion") or "").strip()


def _tarjeta(placa, dr, prod, x0, y0, x1, y1, pad, pw, rojo, modo="unitario",
             vertical=False, recortar=True):
    """Foto a la izquierda; precio, unidad y nombre a la derecha."""
    if vertical:
        return _tarjeta_vertical(placa, dr, prod, x0, y0, x1, y1, pad, rojo,
                                 modo, recortar)
    ph = (y1 - y0) - 2 * pad
    fx, fy = x0 + pad, y0 + pad
    _pegar_marco(placa, _foto_en_caja(prod, pw, ph, recortar), fx, fy)

    tx = fx + pw + 14
    tw = x1 - pad - tx
    txt, unidad, nombre = _textos_tarjeta(prod, modo)

    f_p = _fuente_ajustada(txt, tw, int(ph * 0.30), 14)
    y = fy - 2
    dr.text((tx, y), txt, font=f_p, fill=rojo)
    y += int(f_p.size * 1.12)

    f_u = _fuente_ajustada(unidad, tw, 24, 14, fn=lambda s: _fuente(s, True))
    dr.text((tx, y), unidad, font=f_u, fill=_TINTA)
    y += int(f_u.size * 1.5)

    # Nombre: hasta 3 lineas, achicando el cuerpo hasta que entre
    size = 24
    while True:
        f_n = _fuente(size, False)
        lineas = _envolver(dr, nombre, f_n, tw)
        if (len(lineas) <= 3 and y + len(lineas) * size * 1.2 <= fy + ph) or size <= 14:
            break
        size -= 1
    if len(lineas) > 3:     # no se corta a la mitad: se marca con "…"
        l3 = lineas[2]
        while l3 and _ancho(dr, l3 + "…", f_n) > tw:
            l3 = l3[:-1]
        lineas = lineas[:2] + [l3.rstrip() + "…"]
    for linea in lineas[:3]:
        dr.text((tx, y), linea, font=f_n, fill=(75, 70, 68))
        y += int(size * 1.2)


def _tarjeta_vertical(placa, dr, prod, x0, y0, x1, y1, pad, rojo, modo, recortar):
    """Foto grande arriba, ocupando todo el ancho; precio y nombre abajo."""
    fx, fy = x0 + pad, y0 + pad
    tw = (x1 - x0) - 2 * pad
    ph = (y1 - y0) - 2 * pad
    txt, unidad, nombre = _textos_tarjeta(prod, modo)

    f_p = _fuente_ajustada(txt, int(tw * 0.62), int(ph * 0.21), 14)
    w_p = _ancho(dr, txt, f_p)
    resto = tw - w_p - 10
    junto = False
    f_u = _fuente_ajustada(unidad, max(resto, 1), 22, 13, fn=lambda s: _fuente(s, True))
    if resto >= 60 and _ancho(dr, unidad, f_u) <= resto:
        junto = True
    else:
        f_u = _fuente_ajustada(unidad, tw, 22, 13, fn=lambda s: _fuente(s, True))
    alto_precio = int(f_p.size * 1.12) + (0 if junto else int(f_u.size * 1.3))

    # El nombre se achica hasta dejar la mitad de la tarjeta a la foto
    size = 22
    while True:
        f_n = _fuente(size, False)
        lineas = _envolver(dr, nombre, f_n, tw)
        n_l = min(len(lineas), 2)
        alto_foto = ph - alto_precio - 4 - int(n_l * size * 1.2) - 8
        if (len(lineas) <= 2 and alto_foto >= ph * 0.5) or size <= 14:
            break
        size -= 1
    if len(lineas) > 2:
        l2 = lineas[1]
        while l2 and _ancho(dr, l2 + "…", f_n) > tw:
            l2 = l2[:-1]
        lineas = [lineas[0], l2.rstrip() + "…"]
    alto_foto = max(40, alto_foto)

    _pegar_marco(placa, _foto_en_caja(prod, tw, alto_foto, recortar), fx, fy)

    y = fy + alto_foto + 6
    dr.text((fx, y - 2), txt, font=f_p, fill=rojo)
    if junto:
        dr.text((fx + w_p + 10, y + f_p.size * 1.12 - f_u.size * 1.3),
                unidad, font=f_u, fill=_TINTA)
        y += int(f_p.size * 1.12) + 4
    else:
        y += int(f_p.size * 1.12)
        dr.text((fx, y), unidad, font=f_u, fill=_TINTA)
        y += int(f_u.size * 1.3) + 4
    for linea in lineas[:2]:
        dr.text((fx, y), linea, font=f_n, fill=(75, 70, 68))
        y += int(size * 1.2)


# ══════════════════════════════════════════════════════════════════════════
# SELECTOR (UI)
# ══════════════════════════════════════════════════════════════════════════

def abrir_selector_ofertas(parent):
    """Elegir hasta 9 productos y generar el flyer de ofertas de la semana."""
    import tkinter as tk
    from tkinter import ttk, messagebox, filedialog
    from styles import C, F, btn, lbl, card
    from repositorio import get_productos, get_categorias

    d = tk.Toplevel(parent)
    d.title("Ofertas de la semana")
    d.configure(bg=C.bg)
    d.grab_set()
    sw, sh = d.winfo_screenwidth(), d.winfo_screenheight()
    w, h = min(900, sw - 60), min(700, sh - 60)
    d.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")
    d.columnconfigure(0, weight=1)
    d.rowconfigure(6, weight=1)

    def _boton(parent_, texto, variante, comando):
        b = btn(parent_, texto, variante=variante, comando=comando)
        # Enter tambien activa el boton cuando tiene el foco
        b.configure(takefocus=1)
        b.bind("<Return>", lambda e: (b.invoke(), "break")[1])
        return b

    def _entry(parent_, var, ancho):
        return tk.Entry(parent_, textvariable=var, font=F.normal, width=ancho,
                        bg=C.superficie, fg=C.texto, relief="solid", bd=1)

    hdr = tk.Frame(d, bg=C.bg)
    hdr.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 4))
    lbl(hdr, "Ofertas de la semana", variante="titulo").pack(side="left")
    lbl(hdr, f"Flyer con hasta {MAX_PRODUCTOS} productos (3 por fila)",
        variante="suave").pack(side="left", padx=12)

    # Textos del flyer
    f1 = tk.Frame(d, bg=C.bg)
    f1.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 4))
    v_tit = tk.StringVar(value="OFERTAS")
    v_sub = tk.StringVar(value="DE LA SEMANA")
    v_fecha = tk.StringVar(value=fecha_sugerida().strftime("%d/%m/%Y"))
    lbl(f1, "Título:").pack(side="left")
    _entry(f1, v_tit, 14).pack(side="left", padx=(4, 10), ipady=3)
    lbl(f1, "Subtítulo:").pack(side="left")
    _entry(f1, v_sub, 16).pack(side="left", padx=(4, 10), ipady=3)
    lbl(f1, "Válido hasta:").pack(side="left")
    _entry(f1, v_fecha, 11).pack(side="left", padx=(4, 4), ipady=3)
    lbl(f1, "(dd/mm/aaaa, vacío = sin leyenda)", variante="suave").pack(side="left")

    f2 = tk.Frame(d, bg=C.bg)
    f2.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 4))
    v_desc = tk.StringVar(value="")
    v_btn = tk.StringVar(value="PEDÍ POR WHATSAPP")
    var_fmt = tk.StringVar(value="a4")
    lbl(f2, "Cartel % efectivo:").pack(side="left")
    _entry(f2, v_desc, 5).pack(side="left", padx=(4, 2), ipady=3)
    lbl(f2, "(vacío = sin cartel; no cambia los precios)",
        variante="suave").pack(side="left", padx=(0, 10))
    lbl(f2, "Botón del pie:").pack(side="left")
    _entry(f2, v_btn, 20).pack(side="left", padx=(4, 10), ipady=3)
    lbl(f2, "Formato:").pack(side="left")
    ttk.Combobox(f2, textvariable=var_fmt, width=8, state="readonly",
                 values=list(FORMATOS_OFERTAS)).pack(side="left", padx=4)

    # Que precio se imprime: el flyer nunca elige solo
    f3 = tk.Frame(d, bg=C.bg)
    f3.grid(row=3, column=0, sticky="ew", padx=12, pady=(0, 4))
    var_modo = tk.StringVar(value="Precio de 1 unidad (con promo directa)")
    lbl(f3, "Precio a mostrar:").pack(side="left")
    cb_modo = ttk.Combobox(f3, textvariable=var_modo, width=40, state="readonly",
                           values=list(MODOS_PRECIO))
    cb_modo.pack(side="left", padx=(4, 10))
    lbl(f3, "(la columna \"En flyer\" muestra lo que se va a imprimir)",
        variante="suave").pack(side="left")

    # Foto del encabezado y tamaño de las fotos de producto
    import config as _config
    f4 = tk.Frame(d, bg=C.bg)
    f4.grid(row=4, column=0, sticky="ew", padx=12, pady=(0, 4))
    _guardada = _config.get("flyer_foto_fondo", "") or ""
    var_fondo = tk.StringVar(value=_guardada if os.path.isfile(_guardada) else "")
    lbl(f4, "Foto de fondo:").pack(side="left")
    _entry(f4, var_fondo, 28).pack(side="left", padx=(4, 4), ipady=3)

    def _elegir_fondo():
        ruta = filedialog.askopenfilename(
            parent=d, title="Foto para el encabezado del flyer",
            filetypes=[("Imágenes", "*.jpg *.jpeg *.png *.webp"), ("Todos", "*.*")])
        if ruta:
            var_fondo.set(ruta)

    _boton(f4, "Elegir…", "neutro", _elegir_fondo).pack(side="left", padx=2)
    _boton(f4, "Quitar", "neutro", lambda: var_fondo.set("")).pack(side="left", padx=(2, 12))
    lbl(f4, "Fotos de producto:").pack(side="left")
    _tam_g = _config.get("flyer_tam_foto", "normal")
    var_tam = tk.StringVar(value=next((k for k, v in TAM_FOTO.items() if v == _tam_g),
                                      "Normal"))
    ttk.Combobox(f4, textvariable=var_tam, width=24, state="readonly",
                 values=list(TAM_FOTO)).pack(side="left", padx=(4, 8))
    var_rec = tk.BooleanVar(value=True)
    tk.Checkbutton(f4, text="Recortar márgenes blancos", variable=var_rec, bg=C.bg,
                   fg=C.texto, font=F.normal, selectcolor=C.bg,
                   activebackground=C.bg).pack(side="left")

    # Filtros
    bar = tk.Frame(d, bg=C.bg)
    bar.grid(row=5, column=0, sticky="ew", padx=12, pady=(4, 6))
    lbl(bar, "Buscar:").pack(side="left", padx=(0, 6))
    e_busc = tk.Entry(bar, font=F.normal, width=20, bg=C.superficie,
                      fg=C.texto, relief="solid", bd=1)
    e_busc.pack(side="left", ipady=5)
    lbl(bar, "Categoria:").pack(side="left", padx=(14, 6))
    _cats = [{"id": None, "nombre": "Todas"}] + list(get_categorias())
    var_cat = tk.StringVar(value="Todas")
    cb_cat = ttk.Combobox(bar, textvariable=var_cat, width=20, state="readonly",
                          values=[c_["nombre"] for c_ in _cats])
    cb_cat.pack(side="left")
    var_foto = tk.BooleanVar(value=True)
    tk.Checkbutton(bar, text="Solo con foto", variable=var_foto, bg=C.bg,
                   fg=C.texto, font=F.normal, selectcolor=C.bg,
                   activebackground=C.bg).pack(side="left", padx=(14, 0))
    var_promo = tk.BooleanVar(value=False)
    tk.Checkbutton(bar, text="Solo con promo vigente", variable=var_promo, bg=C.bg,
                   fg=C.texto, font=F.normal, selectcolor=C.bg,
                   activebackground=C.bg).pack(side="left", padx=(10, 0))

    COLS = [("sel", "", 30, "center"), ("desc", "Producto", 320, "w"),
            ("marca", "Marca", 120, "w"), ("precio", "Precio", 100, "e"),
            ("promo", "Promo", 60, "center"), ("flyer", "En flyer", 150, "e"),
            ("foto", "Foto", 50, "center")]
    f_tabla = card(d)
    f_tabla.grid(row=6, column=0, sticky="nsew", padx=12, pady=(0, 6))
    f_tabla.columnconfigure(0, weight=1)
    f_tabla.rowconfigure(0, weight=1)
    tree = ttk.Treeview(f_tabla, columns=[c_[0] for c_ in COLS], show="headings")
    for cid, head, anc, al in COLS:
        tree.heading(cid, text=head, anchor="w")
        tree.column(cid, width=anc, anchor=al, minwidth=30)
    sb = ttk.Scrollbar(f_tabla, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=sb.set)
    tree.grid(row=0, column=0, sticky="nsew")
    sb.grid(row=0, column=1, sticky="ns")

    seleccionados, todos = {}, {}   # seleccionados conserva el orden de elección

    def _tiene_promo(p):
        precios = _get_precios_producto(p["id"], p["precio_base"])
        return (len(precios) > 1 or int(precios[0]["cantidad"]) > 1
                or abs(float(precios[0]["precio"]) - float(p["precio_base"])) > 0.005)

    def _modo():
        return MODOS_PRECIO[var_modo.get()]

    def _txt_flyer(p):
        precio, cant = _datos_precio(p, _modo())
        return _fmt_precio(precio) + (f"  (desde {cant})" if cant > 1 else "")

    def cargar(*_a):
        tree.delete(*tree.get_children())
        cat_id = _cats[[c_["nombre"] for c_ in _cats].index(var_cat.get())]["id"]
        for p in get_productos(filtro=e_busc.get().strip(), categoria_id=cat_id):
            if var_foto.get() and not p.get("imagen_url"):
                continue
            promo = _tiene_promo(p)
            if var_promo.get() and not promo:
                continue
            todos[str(p["id"])] = p
            tree.insert("", "end", iid=str(p["id"]), values=(
                "x" if str(p["id"]) in seleccionados else "",
                p["descripcion"], p.get("marca") or "—",
                f"$ {p['precio_base']:,.2f}", "Sí" if promo else "—",
                _txt_flyer(p), "Sí" if p.get("imagen_url") else "—"))
        _actualizar()

    def _click(ev):
        iid = tree.identify_row(ev.y)
        if not iid or tree.identify_column(ev.x) != "#1":
            return
        if iid in seleccionados:
            del seleccionados[iid]
            tree.set(iid, "sel", "")
        else:
            if len(seleccionados) >= MAX_PRODUCTOS:
                messagebox.showinfo("Ofertas", f"El flyer lleva hasta "
                                    f"{MAX_PRODUCTOS} productos.", parent=d)
                return
            seleccionados[iid] = True
            tree.set(iid, "sel", "x")
        _actualizar()

    tree.bind("<ButtonRelease-1>", _click)
    e_busc.bind("<KeyRelease>", cargar)
    cb_cat.bind("<<ComboboxSelected>>", cargar)
    var_foto.trace_add("write", cargar)
    var_promo.trace_add("write", cargar)
    cb_modo.bind("<<ComboboxSelected>>", cargar)

    bot = tk.Frame(d, bg=C.bg)
    bot.grid(row=7, column=0, sticky="ew", padx=12, pady=(0, 12))
    lbl_sel = lbl(bot, "", variante="suave")
    lbl_sel.pack(side="left")

    def _actualizar():
        lbl_sel.config(text=f"{len(seleccionados)} de {MAX_PRODUCTOS} elegidos   ·   "
                            f"{len(tree.get_children())} en pantalla")

    def _marcar_visibles():
        for iid in tree.get_children():
            if iid in seleccionados:
                continue
            if len(seleccionados) >= MAX_PRODUCTOS:
                break
            seleccionados[iid] = True
            tree.set(iid, "sel", "x")
        _actualizar()

    def _desmarcar():
        seleccionados.clear()
        for iid in tree.get_children():
            tree.set(iid, "sel", "")
        _actualizar()

    def _generar():
        prods = [todos[i] for i in seleccionados if i in todos]
        if not prods:
            messagebox.showinfo("Ofertas", "Elegí al menos un producto.", parent=d)
            return
        fecha = None
        if v_fecha.get().strip():
            fecha = parsear_fecha(v_fecha.get())
            if not fecha:
                messagebox.showwarning("Ofertas", "No entiendo la fecha. "
                                       "Usá dd/mm/aaaa, por ejemplo 04/10/2026.", parent=d)
                return
        pct = 0
        if v_desc.get().strip():
            try:
                pct = float(v_desc.get().strip().replace(",", ".").rstrip("%"))
            except ValueError:
                pct = -1
            if not 0 < pct < 100:
                messagebox.showwarning("Ofertas", "El % de efectivo tiene que ser un "
                                       "número entre 1 y 99.", parent=d)
                return
        fondo = var_fondo.get().strip()
        if fondo and not os.path.isfile(fondo):
            messagebox.showwarning("Ofertas", "No encuentro la foto de fondo:\n"
                                   f"{fondo}", parent=d)
            return
        carpeta = filedialog.askdirectory(parent=d, title="¿Dónde guardo el flyer?")
        if not carpeta:
            return
        try:
            ruta = generar_flyer_ofertas(prods, v_tit.get().strip(), v_sub.get().strip(),
                                         fecha, pct, v_btn.get().strip(),
                                         var_fmt.get(), carpeta,
                                         modo_precio=_modo(),
                                         foto_fondo=fondo or None,
                                         tam_foto=TAM_FOTO[var_tam.get()],
                                         recortar_blanco=var_rec.get())
        except Exception as exc:
            logging.warning(f"No se pudo generar el flyer de ofertas: {exc}")
            messagebox.showwarning("Ofertas", f"No se pudo generar:\n{exc}", parent=d)
            return
        try:    # se recuerdan la foto y el tamaño para la proxima vez
            _config.set("flyer_foto_fondo", fondo)
            _config.set("flyer_tam_foto", TAM_FOTO[var_tam.get()])
        except Exception as e:
            logging.warning(f"No se pudo guardar la preferencia del flyer: {e}")
        messagebox.showinfo("Ofertas", f"Flyer guardado:\n{ruta}", parent=d)
        try:
            os.startfile(carpeta)          # Windows: abre la carpeta
        except Exception:
            pass

    _boton(bot, "Marcar los visibles", "neutro", _marcar_visibles).pack(side="left", padx=(12, 4))
    _boton(bot, "Desmarcar todo", "neutro", _desmarcar).pack(side="left")
    _boton(bot, "Generar flyer", "exito", _generar).pack(side="right")

    cargar()
    e_busc.focus_set()

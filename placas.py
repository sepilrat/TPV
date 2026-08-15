"""
placas.py — Placas individuales para estados de WhatsApp / Instagram.

Misma informacion que el folleto (foto, marca, descripcion, precio y
escalas por cantidad) pero una imagen por producto, o una por combo,
lista para subir a un estado.

Se generan como PNG en una carpeta, para elegirlas desde el celular.

Formatos:
    story    1080 x 1920  — estado de WhatsApp e historias de Instagram
    cuadrado 1080 x 1080  — publicacion de feed
"""

import logging
import os
import re
from datetime import datetime

from PIL import Image, ImageDraw, ImageFilter, ImageFont

import imagenes
from config import cfg
from etiquetas import _get_precios_producto


FORMATOS = {
    "story":    (1080, 1920),
    "cuadrado": (1080, 1080),
}

CARPETA_PLACAS = os.path.join(os.path.dirname(__file__), "placas")


# ── Tipografias ───────────────────────────────────────────────────────────
# Se prueban las de Windows primero; si no estan, PIL cae a la default,
# que es fea pero no rompe la generacion.
_FUENTES_BOLD = ("arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
_FUENTES_REG = ("arial.ttf", "Arial.ttf", "DejaVuSans.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")


def _fuente(size, bold=True):
    for nombre in (_FUENTES_BOLD if bold else _FUENTES_REG):
        try:
            return ImageFont.truetype(nombre, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def _hex(valor, defecto):
    v = (valor or "").strip() or defecto
    if not v.startswith("#"):
        v = "#" + v
    try:
        return tuple(int(v[i:i+2], 16) for i in (1, 3, 5))
    except ValueError:
        return tuple(int(defecto[i:i+2], 16) for i in (1, 3, 5))


def _ancho(draw, texto, fuente):
    caja = draw.textbbox((0, 0), texto, font=fuente)
    return caja[2] - caja[0]


def _envolver(draw, texto, fuente, ancho_max):
    lineas, linea = [], ""
    for palabra in texto.split():
        prueba = (linea + " " + palabra).strip()
        if _ancho(draw, prueba, fuente) <= ancho_max:
            linea = prueba
        else:
            if linea:
                lineas.append(linea)
            linea = palabra
    if linea:
        lineas.append(linea)
    return lineas


def _texto_ajustado(draw, texto, ancho_max, size_max, size_min, bold=True,
                    max_lineas=2):
    """Baja el cuerpo hasta que el texto entra en max_lineas."""
    size = size_max
    while size > size_min:
        f = _fuente(size, bold)
        lineas = _envolver(draw, texto, f, ancho_max)
        if len(lineas) <= max_lineas:
            return f, lineas
        size -= 4
    f = _fuente(size_min, bold)
    lineas = _envolver(draw, texto, f, ancho_max)[:max_lineas]
    if lineas:
        lineas[-1] = lineas[-1][:-1] + "…"
    return f, lineas


def _mezclar(color, con, factor):
    """Aclara u oscurece un color mezclandolo con otro."""
    return tuple(int(c + (o - c) * factor) for c, o in zip(color, con))


def _sombra(placa, caja, radio=28, desenfoque=18, alpha=52, desplazamiento=10):
    """Sombra suave debajo de una caja. Da profundidad sin ensuciar."""
    capa = Image.new("RGBA", placa.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(capa)
    x0, y0, x1, y1 = caja
    d.rounded_rectangle([x0, y0 + desplazamiento, x1, y1 + desplazamiento],
                        radius=radio, fill=(0, 0, 0, alpha))
    capa = capa.filter(ImageFilter.GaussianBlur(desenfoque))
    placa.paste(Image.alpha_composite(placa.convert("RGBA"), capa).convert("RGB"),
                (0, 0))


def _fondo_decorado(placa, draw, ancho, alto, color_marca):
    """Marco, esquina diagonal y banda de pie.

    Una placa lisa sobre blanco se pierde entre los estados de los
    demas. El marco y la diagonal le dan identidad sin tapar el
    producto, que es lo unico que tiene que mirarse.
    """
    suave = _mezclar(color_marca, (255, 255, 255), 0.90)
    medio = _mezclar(color_marca, (255, 255, 255), 0.55)

    # Fondo levemente tenido, para que la tarjeta blanca de la foto
    # se despegue del fondo
    draw.rectangle([0, 0, ancho, alto], fill=suave)

    # Cuna diagonal arriba a la derecha
    draw.polygon([(ancho, 0), (ancho, int(alto * 0.16)),
                  (int(ancho * 0.52), 0)], fill=medio)
    draw.polygon([(ancho, 0), (ancho, int(alto * 0.09)),
                  (int(ancho * 0.72), 0)], fill=color_marca)

    # Banda de pie
    alto_banda = int(alto * 0.055)
    draw.rectangle([0, alto - alto_banda, ancho, alto], fill=color_marca)

    # Marco
    draw.rounded_rectangle([14, 14, ancho - 14, alto - 14], radius=26,
                           outline=color_marca, width=6)
    return alto_banda


def _pegar_foto(placa, prod, caja, tarjeta=False):
    """Pega la foto centrada dentro de la caja (x0, y0, x1, y1).

    tarjeta=True la apoya sobre un rectangulo blanco con sombra: sirve
    para las fotos con fondo blanco, que sin eso se funden con el
    fondo de la placa y el producto queda flotando.
    """
    x0, y0, x1, y1 = caja
    ancho, alto = x1 - x0, y1 - y0
    if tarjeta:
        _sombra(placa, (x0 - 16, y0 - 16, x1 + 16, y1 + 16))
        # Borde tenue: sin el, una foto de producto con fondo blanco
        # (la mayoria) se funde con la tarjeta y no se ve donde termina.
        ImageDraw.Draw(placa).rounded_rectangle(
            [x0 - 16, y0 - 16, x1 + 16, y1 + 16], radius=22,
            fill=(255, 255, 255), outline=(228, 230, 236), width=2)
    img = imagenes.cargar_imagen_pil(prod.get("imagen_url"))
    if not img:
        d = ImageDraw.Draw(placa)
        d.rounded_rectangle(caja, radius=14, fill=(243, 244, 246))
        f = _fuente(40, False)
        t = "sin foto"
        d.text((x0 + (ancho - _ancho(d, t, f)) / 2, y0 + alto / 2 - 20),
               t, font=f, fill=(156, 163, 175))
        return
    img = img.convert("RGB")
    escala = min(ancho / img.width, alto / img.height)
    nuevo = (max(1, int(img.width * escala)), max(1, int(img.height * escala)))
    img = img.resize(nuevo, Image.LANCZOS)
    placa.paste(img, (x0 + (ancho - nuevo[0]) // 2, y0 + (alto - nuevo[1]) // 2))


def _cartel_precio(draw, texto, centro_x, y, ancho_max, color, alto=None,
                   placa=None):
    """Dibuja el precio dentro de una caja redondeada. Devuelve el alto usado."""
    size = 96
    f = _fuente(size, True)
    while _ancho(draw, texto, f) > ancho_max - 80 and size > 34:
        size -= 4
        f = _fuente(size, True)
    w = _ancho(draw, texto, f)
    caja_w = min(ancho_max, w + 80)
    caja_h = alto or int(size * 1.7)
    x0 = centro_x - caja_w // 2
    if placa is not None:
        _sombra(placa, (x0, y, x0 + caja_w, y + caja_h),
                radio=caja_h // 4, desenfoque=14, alpha=70, desplazamiento=8)
        draw = ImageDraw.Draw(placa)
    draw.rounded_rectangle([x0, y, x0 + caja_w, y + caja_h],
                           radius=caja_h // 4, fill=color)
    caja = draw.textbbox((0, 0), texto, font=f)
    draw.text((centro_x - w / 2, y + (caja_h - (caja[3] - caja[1])) / 2 - caja[1]),
              texto, font=f, fill=(255, 255, 255))
    return caja_h


def _encabezado(placa, draw, ancho, color_marca, vendedor=None):
    """Con vendedor, la placa sale con SU nombre y sin el logo propio.

    Es una placa que el revendedor sube a su estado: si lleva el nombre
    y el logo del mayorista, el cliente le escribe al mayorista y el
    vendedor pierde la venta que salio a buscar.
    """
    c = cfg()
    y = 46
    if vendedor:
        # Sin nombre ni logo: el vendedor la sube a su propio estado,
        # donde su nombre ya esta arriba. Repetirlo solo roba espacio
        # al producto, que es lo unico que hay que mirar.
        # Se deja aire igual para que la diagonal se vea completa.
        return y + 78
    logo = c.get("negocio_logo_path")
    if logo and os.path.isfile(logo):
        try:
            lg = Image.open(logo).convert("RGBA")
            alto_logo = 130
            lg = lg.resize((int(lg.width * alto_logo / lg.height), alto_logo),
                           Image.LANCZOS)
            placa.paste(lg, ((ancho - lg.width) // 2, y), lg)
            return y + alto_logo + 24
        except Exception as e:
            logging.warning(f"No se pudo poner el logo en la placa: {e}")
    nombre = c.get("negocio_nombre") or ""
    if nombre:
        f = _fuente(56, True)
        draw.text(((ancho - _ancho(draw, nombre, f)) / 2, y), nombre,
                  font=f, fill=color_marca)
        return y + 90
    return y


def _pie(draw, ancho, alto, color_marca, vendedor=None):
    c = cfg()
    if vendedor:
        datos = [d for d in (vendedor.get("telefono"),) if d]
    else:
        datos = [d for d in (c.get("negocio_telefono"), c.get("negocio_direccion"))
                 if d]
    if not datos:
        return
    # El texto se achica hasta entrar, y si aun asi no entra se parte en
    # dos lineas. Antes salia a cuerpo fijo y una direccion larga se
    # cortaba por los DOS lados (el texto va centrado), asi que se perdia
    # tanto el principio del telefono como el final de la direccion.
    alto_banda = int(alto * 0.055)
    disponible = ancho - 40
    partes = [str(d).strip() for d in datos if str(d).strip()]

    size = 36
    f = _fuente(size, True)
    txt = "   ·   ".join(partes)
    while _ancho(draw, txt, f) > disponible and size > 20:
        size -= 2
        f = _fuente(size, True)

    if _ancho(draw, txt, f) <= disponible or len(partes) < 2:
        draw.text(((ancho - _ancho(draw, txt, f)) / 2,
                   alto - alto_banda + (alto_banda - size * 1.2) / 2),
                  txt, font=f, fill=(255, 255, 255))
        return

    # Dos lineas: telefono arriba, direccion abajo
    size = 30
    f = _fuente(size, True)
    l1, l2 = partes[0], "   ·   ".join(partes[1:])
    while max(_ancho(draw, l1, f), _ancho(draw, l2, f)) > disponible and size > 16:
        size -= 2
        f = _fuente(size, True)
    # Si la segunda linea sigue sin entrar, se recorta ahi (no en el medio)
    while _ancho(draw, l2, f) > disponible and len(l2) > 8:
        l2 = l2[:-2]
    if l2 != "   ·   ".join(partes[1:]):
        l2 = l2.rstrip() + "…"
    y0 = alto - alto_banda + (alto_banda - size * 2.3) / 2
    for i, linea in enumerate((l1, l2)):
        draw.text(((ancho - _ancho(draw, linea, f)) / 2, y0 + i * size * 1.15),
                  linea, font=f, fill=(255, 255, 255))


def _precio_txt(prod):
    """Precio principal y las escalas por cantidad, como en el folleto.

    prod["precio_base"] ya viene con el recargo del vendedor aplicado
    (ver repositorio.productos_para_vendedor); "_recargo" es el monto
    por unidad, que hay que sumarle tambien a las promos de precio fijo.
    """
    precios = _get_precios_producto(prod["id"], prod["precio_base"],
                                    prod.get("_recargo", 0.0))
    if not precios:
        precios = [{"precio": prod["precio_base"], "cantidad": 1}]
    principal = precios[0]
    unidad = "x Kg" if prod.get("vendido_por_peso") else "c/u"
    cant = int(principal["cantidad"])
    txt = f"$ {principal['precio']:,.0f} {unidad}"
    extra = ""
    if cant > 1:
        extra = f"llevando {cant}"
    resto = [f"x{int(t['cantidad'])}: $ {t['precio']:,.0f}" for t in precios[1:3]]
    return txt, extra, resto


# ══════════════════════════════════════════════════════════════════════════
# Placa de UN producto
# ══════════════════════════════════════════════════════════════════════════

def generar_placa(prod, formato="story", carpeta=None, vendedor=None):
    ancho, alto = FORMATOS.get(formato, FORMATOS["story"])
    c = cfg()
    color_marca = _hex(c.get("folleto_color"), "#2451B0")
    color_precio = _hex(c.get("folleto_color_precio"), "#DC2626")

    placa = Image.new("RGB", (ancho, alto), (255, 255, 255))
    draw = ImageDraw.Draw(placa)
    alto_banda = _fondo_decorado(placa, draw, ancho, alto, color_marca)
    draw = ImageDraw.Draw(placa)

    y = _encabezado(placa, draw, ancho, color_marca, vendedor)
    draw = ImageDraw.Draw(placa)

    margen = 84
    ancho_util = ancho - 2 * margen
    alto_foto = int(alto * (0.42 if formato == "story" else 0.38))
    _pegar_foto(placa, prod, (margen, y, ancho - margen, y + alto_foto),
                tarjeta=True)
    draw = ImageDraw.Draw(placa)
    y += alto_foto + 56

    precio, extra, resto = _precio_txt(prod)
    if extra:
        f = _fuente(44, True)
        draw.text(((ancho - _ancho(draw, extra, f)) / 2, y), extra.upper(),
                  font=f, fill=color_precio)
        y += 60
    y += _cartel_precio(draw, precio, ancho // 2, y, ancho_util, color_precio,
                        placa=placa) + 34
    draw = ImageDraw.Draw(placa)

    if resto:
        f = _fuente(40, True)
        t = "     ".join(resto)
        draw.text(((ancho - _ancho(draw, t, f)) / 2, y), t,
                  font=f, fill=_mezclar(color_marca, (0, 0, 0), 0.25))
        y += 62

    if prod.get("marca"):
        f = _fuente(54, True)
        t = prod["marca"].upper()
        draw.text(((ancho - _ancho(draw, t, f)) / 2, y), t,
                  font=f, fill=color_marca)
        y += 72

    tope_texto = alto - alto_banda - 40
    # Se prueba con 3 lineas; si no entra, hasta 4 con cuerpo mas chico
    # antes de recortar. Una descripcion cortada en la gondola no dice
    # ni la medida ni el color, que es lo que decide la compra.
    f, lineas = _texto_ajustado(draw, (prod.get("descripcion") or "").upper(),
                                ancho_util, 52, 30, True, max_lineas=3)
    if len(lineas) * (f.size + 12) > tope_texto - y:
        f, lineas = _texto_ajustado(draw, (prod.get("descripcion") or "").upper(),
                                    ancho_util, 40, 22, True, max_lineas=4)
    for linea in lineas:
        if y + f.size > tope_texto:
            break
        draw.text(((ancho - _ancho(draw, linea, f)) / 2, y), linea,
                  font=f, fill=(17, 24, 39))
        y += f.size + 12

    _pie(draw, ancho, alto, color_marca, vendedor)
    return _guardar(placa, prod.get("descripcion") or f"producto_{prod['id']}",
                    carpeta)


# ══════════════════════════════════════════════════════════════════════════
# Placa de COMBO (2 a 4 productos)
# ══════════════════════════════════════════════════════════════════════════

def generar_placa_combo(productos, titulo="COMBO", formato="story",
                        carpeta=None, precio_combo=None, vendedor=None):
    if not 2 <= len(productos) <= 4:
        raise ValueError("Un combo lleva entre 2 y 4 productos")

    ancho, alto = FORMATOS.get(formato, FORMATOS["story"])
    c = cfg()
    color_marca = _hex(c.get("folleto_color"), "#2451B0")
    color_precio = _hex(c.get("folleto_color_precio"), "#DC2626")

    placa = Image.new("RGB", (ancho, alto), (255, 255, 255))
    draw = ImageDraw.Draw(placa)
    alto_banda = _fondo_decorado(placa, draw, ancho, alto, color_marca)
    draw = ImageDraw.Draw(placa)
    y = _encabezado(placa, draw, ancho, color_marca, vendedor)
    draw = ImageDraw.Draw(placa)

    if titulo:
        f = _fuente(72, True)
        draw.text(((ancho - _ancho(draw, titulo.upper(), f)) / 2, y),
                  titulo.upper(), font=f, fill=color_precio)
        y += 110

    margen = 60
    cols = 2 if len(productos) > 1 else 1
    filas = (len(productos) + cols - 1) // cols
    # Se reserva el bloque de precio de abajo antes de repartir las celdas
    alto_precio = 260 if precio_combo else 60
    alto_grilla = alto - y - alto_precio - 120 - alto_banda
    celda_w = (ancho - 2 * margen) // cols
    celda_h = alto_grilla // filas

    for i, prod in enumerate(productos):
        cx = margen + (i % cols) * celda_w
        cy = y + (i // cols) * celda_h
        _pegar_foto(placa, prod, (cx + 26, cy + 12, cx + celda_w - 26,
                                  cy + celda_h - 96), tarjeta=True)
        draw = ImageDraw.Draw(placa)
        f, lineas = _texto_ajustado(draw, (prod.get("descripcion") or "").upper(),
                                    celda_w - 28, 34, 20, True, max_lineas=2)
        ty = cy + celda_h - 84
        for linea in lineas:
            draw.text((cx + (celda_w - _ancho(draw, linea, f)) / 2, ty),
                      linea, font=f, fill=(17, 24, 39))
            ty += f.size + 6

    y += alto_grilla + 40
    if precio_combo:
        f = _fuente(46, True)
        t = "LLEVANDO LOS %d" % len(productos)
        draw.text(((ancho - _ancho(draw, t, f)) / 2, y), t,
                  font=f, fill=color_precio)
        y += 64
        _cartel_precio(draw, f"$ {float(precio_combo):,.0f}", ancho // 2, y,
                       ancho - 2 * margen, color_precio, placa=placa)
        draw = ImageDraw.Draw(placa)

    _pie(draw, ancho, alto, color_marca, vendedor)
    return _guardar(placa, titulo or "combo", carpeta)


# ══════════════════════════════════════════════════════════════════════════

def _guardar(placa, nombre_base, carpeta=None):
    carpeta = carpeta or CARPETA_PLACAS
    os.makedirs(carpeta, exist_ok=True)
    slug = re.sub(r"[^\w\- ]+", "", nombre_base).strip().replace(" ", "_")[:48]
    stamp = datetime.now().strftime("%Y%m%d")
    ruta = os.path.join(carpeta, f"{stamp}_{slug or 'placa'}.png")
    n = 2
    while os.path.exists(ruta):
        ruta = os.path.join(carpeta, f"{stamp}_{slug or 'placa'}_{n}.png")
        n += 1
    placa.save(ruta, "PNG", optimize=True)
    return ruta


def generar_varias(productos, formato="story", carpeta=None, vendedor=None):
    """Una placa por producto. Devuelve (rutas, errores)."""
    rutas, errores = [], []
    for prod in productos:
        try:
            rutas.append(generar_placa(prod, formato, carpeta, vendedor))
        except Exception as e:
            errores.append(f"{prod.get('descripcion', '?')}: {e}")
            logging.warning(f"No se pudo generar la placa: {e}")
    return rutas, errores


# ══════════════════════════════════════════════════════════════════════════
# SELECTOR (UI)
# ══════════════════════════════════════════════════════════════════════════

def abrir_selector_placas(parent):
    """Elegir productos y generar las placas para estados."""
    import tkinter as tk
    from tkinter import ttk, messagebox, filedialog
    from styles import C, F, btn, lbl, card
    from repositorio import (get_productos, get_categorias, get_vendedores,
                             productos_para_vendedor)

    d = tk.Toplevel(parent)
    d.title("Placas para estados")
    d.configure(bg=C.bg)
    d.grab_set()
    sw, sh = d.winfo_screenwidth(), d.winfo_screenheight()
    w, h = min(860, sw - 60), min(620, sh - 60)
    d.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
    d.columnconfigure(0, weight=1)
    d.rowconfigure(3, weight=1)

    hdr = tk.Frame(d, bg=C.bg)
    hdr.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 4))
    lbl(hdr, "Placas para estados", variante="titulo").pack(side="left")
    lbl(hdr, "Una imagen por producto, o una de combo",
        variante="suave").pack(side="left", padx=12)

    opts = tk.Frame(d, bg=C.bg)
    opts.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 6))
    lbl(opts, "Formato:").pack(side="left")
    var_fmt = tk.StringVar(value="story")
    ttk.Combobox(opts, textvariable=var_fmt, width=26, state="readonly",
                 values=["story", "cuadrado"]).pack(side="left", padx=6)
    lbl(opts, "story = estado de WhatsApp (1080x1920)   ·   "
              "cuadrado = feed (1080x1080)", variante="suave").pack(side="left", padx=8)

    bar = tk.Frame(d, bg=C.bg)
    bar.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 6))
    lbl(bar, "Buscar:").pack(side="left", padx=(0, 6))
    e_busc = tk.Entry(bar, font=F.normal, width=22, bg=C.superficie,
                      fg=C.texto, relief="solid", bd=1)
    e_busc.pack(side="left", ipady=5)
    lbl(bar, "Categoria:").pack(side="left", padx=(14, 6))
    _cats = [{"id": None, "nombre": "Todas"}] + list(get_categorias())
    var_cat = tk.StringVar(value="Todas")
    cb_cat = ttk.Combobox(bar, textvariable=var_cat, width=20, state="readonly",
                          values=[c["nombre"] for c in _cats])
    cb_cat.pack(side="left")
    # Placas con los precios y el encabezado de un vendedor: las sube a
    # SU estado, asi que no pueden llevar el nombre del mayorista.
    lbl(bar, "Precios de:").pack(side="left", padx=(14, 6))
    _vends = [{"id": None, "nombre": "Lista general (precios propios)"}] + [
        dict(v) for v in get_vendedores() if v["activo"]]
    var_vend = tk.StringVar(value=_vends[0]["nombre"])
    cb_vend = ttk.Combobox(bar, textvariable=var_vend, width=24, state="readonly",
                           values=[v["nombre"] for v in _vends])
    cb_vend.pack(side="left")

    def _vendedor():
        v = _vends[[x["nombre"] for x in _vends].index(var_vend.get())]
        return v if v.get("id") else None

    var_foto = tk.BooleanVar(value=True)
    tk.Checkbutton(bar, text="Solo con foto", variable=var_foto, bg=C.bg,
                   fg=C.texto, font=F.normal, selectcolor=C.bg,
                   activebackground=C.bg).pack(side="left", padx=(14, 0))

    COLS = [("sel", "", 30, "center"), ("desc", "Producto", 300, "w"),
            ("marca", "Marca", 120, "w"), ("precio", "Precio", 95, "e"),
            ("foto", "Foto", 50, "center")]
    f_tabla = card(d)
    f_tabla.grid(row=3, column=0, sticky="nsew", padx=12, pady=(0, 6))
    f_tabla.columnconfigure(0, weight=1)
    f_tabla.rowconfigure(0, weight=1)
    tree = ttk.Treeview(f_tabla, columns=[c[0] for c in COLS], show="headings")
    for cid, head, anc, al in COLS:
        tree.heading(cid, text=head, anchor="w")
        tree.column(cid, width=anc, anchor=al, minwidth=30)
    sb = ttk.Scrollbar(f_tabla, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=sb.set)
    tree.grid(row=0, column=0, sticky="nsew")
    sb.grid(row=0, column=1, sticky="ns")

    seleccionados, todos = {}, {}

    def cargar(*_a):
        tree.delete(*tree.get_children())
        cat_id = _cats[[c["nombre"] for c in _cats].index(var_cat.get())]["id"]
        vend = _vendedor()
        lista, _com = productos_para_vendedor(
            get_productos(filtro=e_busc.get().strip(), categoria_id=cat_id),
            vend["id"] if vend else None)
        for p in lista:
            if var_foto.get() and not p.get("imagen_url"):
                continue
            todos[str(p["id"])] = p
            tree.insert("", "end", iid=str(p["id"]), values=(
                "x" if str(p["id"]) in seleccionados else "",
                p["descripcion"], p.get("marca") or "—",
                f"$ {p['precio_base']:,.2f}",
                "Sí" if p.get("imagen_url") else "—"))
        _actualizar()

    def _click(ev):
        iid = tree.identify_row(ev.y)
        if not iid or tree.identify_column(ev.x) != "#1":
            return
        if iid in seleccionados:
            del seleccionados[iid]
            tree.set(iid, "sel", "")
        else:
            seleccionados[iid] = True
            tree.set(iid, "sel", "x")
        _actualizar()

    tree.bind("<ButtonRelease-1>", _click)
    e_busc.bind("<KeyRelease>", cargar)
    cb_cat.bind("<<ComboboxSelected>>", cargar)
    cb_vend.bind("<<ComboboxSelected>>", cargar)
    var_foto.trace_add("write", cargar)

    bot = tk.Frame(d, bg=C.bg)
    bot.grid(row=4, column=0, sticky="ew", padx=12, pady=(0, 12))
    lbl_sel = lbl(bot, "", variante="suave")
    lbl_sel.pack(side="left")

    def _actualizar():
        n = len(seleccionados)
        lbl_sel.config(text=f"{n} seleccionado{'s' if n != 1 else ''}   ·   "
                            f"{len(tree.get_children())} en pantalla")

    def _elegidos():
        return [todos[i] for i in seleccionados if i in todos]

    def _carpeta_destino():
        ruta = filedialog.askdirectory(
            title="¿Dónde guardo las placas?", parent=d,
            initialdir=CARPETA_PLACAS if os.path.isdir(CARPETA_PLACAS) else None)
        return ruta or None

    def _individuales():
        prods = _elegidos()
        if not prods:
            messagebox.showinfo("Placas", "Elegí al menos un producto.", parent=d)
            return
        carpeta = _carpeta_destino()
        if not carpeta:
            return
        rutas, errores = generar_varias(prods, var_fmt.get(), carpeta,
                                        vendedor=_vendedor())
        msg = f"{len(rutas)} placa(s) guardadas en:\n{carpeta}"
        if errores:
            msg += "\n\nFallaron:\n  - " + "\n  - ".join(errores[:4])
        messagebox.showinfo("Placas", msg, parent=d)
        try:
            os.startfile(carpeta)          # Windows: abre la carpeta
        except Exception:
            pass

    def _combo():
        prods = _elegidos()
        if not 2 <= len(prods) <= 4:
            messagebox.showinfo(
                "Combo", "Un combo lleva entre 2 y 4 productos.\n\n"
                f"Tenés {len(prods)} seleccionado(s).", parent=d)
            return

        top = tk.Toplevel(d)
        top.title("Combo")
        top.configure(bg=C.superficie)
        top.grab_set()
        top.geometry("420x250")
        lbl(top, "Datos del combo", variante="titulo",
            bg=C.superficie).pack(anchor="w", padx=18, pady=(16, 2))
        suma = sum(p["precio_base"] for p in prods)
        lbl(top, f"{len(prods)} productos   ·   por separado suman $ {suma:,.2f}",
            variante="suave", bg=C.superficie).pack(anchor="w", padx=18)

        lbl(top, "Título", variante="suave", bg=C.superficie).pack(
            anchor="w", padx=18, pady=(12, 2))
        v_tit = tk.StringVar(value="COMBO")
        tk.Entry(top, textvariable=v_tit, font=F.normal, bg=C.bg, fg=C.texto,
                 relief="solid", bd=1).pack(fill="x", padx=18, ipady=4)

        lbl(top, "Precio del combo (vacío = no se muestra)", variante="suave",
            bg=C.superficie).pack(anchor="w", padx=18, pady=(10, 2))
        v_precio = tk.StringVar()
        tk.Entry(top, textvariable=v_precio, font=F.normal, justify="center",
                 bg=C.bg, fg=C.texto, relief="solid", bd=1).pack(
            fill="x", padx=18, ipady=4)

        def crear():
            precio = None
            txt = v_precio.get().strip().replace(",", ".")
            if txt:
                try:
                    precio = float(txt)
                except ValueError:
                    messagebox.showwarning("Combo", "El precio no es un número.",
                                           parent=top)
                    return
            top.destroy()
            carpeta = _carpeta_destino()
            if not carpeta:
                return
            try:
                ruta = generar_placa_combo(prods, v_tit.get().strip() or "COMBO",
                                           var_fmt.get(), carpeta, precio,
                                           vendedor=_vendedor())
            except Exception as exc:
                messagebox.showwarning("Combo", str(exc), parent=d)
                return
            messagebox.showinfo("Combo", f"Placa guardada:\n{ruta}", parent=d)
            try:
                os.startfile(carpeta)
            except Exception:
                pass

        fb = tk.Frame(top, bg=C.superficie)
        fb.pack(pady=16)
        btn(fb, "Generar", variante="exito", comando=crear).pack(side="left", padx=4)
        btn(fb, "Cancelar", variante="neutro",
            comando=top.destroy).pack(side="left", padx=4)

    btn(bot, "Marcar los visibles", variante="neutro",
        comando=lambda: [seleccionados.update({i: True}) or tree.set(i, "sel", "x")
                         for i in tree.get_children()] and _actualizar()
        ).pack(side="left", padx=(12, 4))
    btn(bot, "Desmarcar todo", variante="neutro",
        comando=lambda: (seleccionados.clear(),
                         [tree.set(i, "sel", "") for i in tree.get_children()],
                         _actualizar())).pack(side="left")
    btn(bot, "Placa de combo", variante="neutro",
        comando=_combo).pack(side="right", padx=(6, 0))
    btn(bot, "Generar placas", variante="exito",
        comando=_individuales).pack(side="right")

    cargar()
    e_busc.focus_set()

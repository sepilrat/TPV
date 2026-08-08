"""
folleto_precios.py — Folleto de ofertas estilo mayorista TPV v2.0

Complementa a lista_precios.py (que es un listado compacto, una línea
por producto). Este es el formato tipo folleto/circular: grid de 4
columnas, foto grande, precio en un cartel superpuesto sobre la
imagen — como los folletos de mayoristas de barrio. Por defecto
agrupado por categoría (una categoría por página/sección), con opción
de consolidar todos los productos juntos sin separar por categoría.
Borde de página y acentos del encabezado en un color configurable
(Config → Negocio → Color del folleto). Los datos de la empresa
(nombre, dirección, teléfono, web, logo) salen de Config → Negocio.
"""

import os
import tempfile
import logging
from datetime import datetime

from config import cfg
from repositorio import get_productos
from etiquetas import _get_precios_producto
import imagenes


def generar_pdf_folleto(productos: list[dict], ruta_salida: str = None,
                        agrupar_por_categoria: bool = True) -> str | None:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.pdfgen import canvas
        from reportlab.lib import colors
        from reportlab.lib.utils import ImageReader
    except ImportError as e:
        logging.error(f"reportlab error de importacion: {e}")
        return None

    if not productos:
        return None
    if not ruta_salida:
        nombre = f"folleto_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
        ruta_salida = os.path.join(tempfile.gettempdir(), nombre)

    c_cfg = cfg()
    ancho_pagina, alto_pagina = A4
    margen_ext = 6 * mm    # separación entre el borde de color y el borde de la hoja
    margen     = 14 * mm   # margen del contenido, adentro del borde
    alto_hdr   = 50 * mm
    cols       = 4
    ancho_util = ancho_pagina - 2 * margen
    cel_ancho  = ancho_util / cols
    alto_fila  = 68 * mm

    try:
        color_marca = colors.HexColor(c_cfg.get("folleto_color") or "#2451B0")
    except Exception:
        color_marca = colors.HexColor("#2451B0")
    try:
        color_precio = colors.HexColor(c_cfg.get("folleto_color_precio") or "#DC2626")
    except Exception:
        color_precio = colors.HexColor("#DC2626")

    # Orden: si se agrupa por categoría, esa es la clave principal (para
    # que cada página muestre una sola categoría); si se consolida todo,
    # se ignora la categoría y se ordena solo por marca y descripción.
    if agrupar_por_categoria:
        productos = sorted(productos, key=lambda p: (
            (p.get("categoria") or "Sin categoría").lower(),
            (p.get("marca") or "").lower(),
            p["descripcion"].lower()))
    else:
        productos = sorted(productos, key=lambda p: (
            (p.get("marca") or "").lower(),
            p["descripcion"].lower()))

    cv = canvas.Canvas(ruta_salida, pagesize=A4)

    def _borde():
        cv.setStrokeColor(color_marca)
        cv.setLineWidth(2.2)
        cv.roundRect(margen_ext, margen_ext,
                    ancho_pagina - 2*margen_ext, alto_pagina - 2*margen_ext,
                    3*mm, stroke=1, fill=0)

    def _header(titulo_seccion):
        _borde()
        y_top = alto_pagina - margen
        y_linea = y_top - alto_hdr

        # Sin banda de color de fondo: encabezado sobre blanco liso,
        # logo grande y centrado arriba de todo.
        y = y_top
        logo_path = c_cfg.get("negocio_logo_path")
        if logo_path and os.path.exists(logo_path):
            try:
                img_reader = ImageReader(logo_path)
                iw, ih = img_reader.getSize()
                logo_alto = 24 * mm
                logo_ancho = logo_alto * (iw / ih)
                max_ancho_logo = (ancho_pagina - 2*margen) * 0.55
                if logo_ancho > max_ancho_logo:
                    logo_ancho = max_ancho_logo
                    logo_alto = logo_ancho * (ih / iw)
                logo_x = (ancho_pagina - logo_ancho) / 2
                cv.drawImage(img_reader, logo_x, y - logo_alto,
                            width=logo_ancho, height=logo_alto,
                            preserveAspectRatio=True, mask='auto')
                y -= logo_alto + 3*mm
            except Exception as e:
                logging.warning(f"No se pudo dibujar el logo: {e}")
                y -= 4*mm
        else:
            y -= 4*mm

        cv.setFont("Helvetica-Bold", 12)
        cv.setFillColor(color_marca)
        cv.drawCentredString(ancho_pagina/2, y, c_cfg.get("negocio_nombre") or "")
        y -= 5.5*mm

        titulo_promo = c_cfg.get("folleto_titulo") or ""
        if titulo_promo:
            cv.setFont("Helvetica-Bold", 15)
            cv.setFillColor(colors.black)
            cv.drawCentredString(ancho_pagina/2, y, titulo_promo.upper())
            y -= 6.5*mm

        datos = [d for d in [
            c_cfg.get("negocio_web"),
            c_cfg.get("negocio_direccion"),
            c_cfg.get("negocio_telefono"),
        ] if d]
        if datos:
            cv.setFont("Helvetica", 8)
            cv.setFillColor(colors.HexColor("#555555"))
            cv.drawCentredString(ancho_pagina/2, y, "     ".join(datos))
        cv.setFillColor(colors.black)

        if titulo_seccion:
            cv.setFont("Helvetica-Bold", 13)
            cv.setFillColor(color_marca)
            cv.drawString(margen, y_linea + 3*mm, titulo_seccion.upper())
            cv.setFillColor(colors.black)

        # Línea gruesa de color, separando el encabezado del contenido
        cv.setStrokeColor(color_marca)
        cv.setLineWidth(1.6)
        cv.line(margen, y_linea, ancho_pagina - margen, y_linea)

    if agrupar_por_categoria:
        categoria_actual = None
        y = None
        col = 0
        for prod in productos:
            cat = prod.get("categoria") or "Sin categoría"
            if cat != categoria_actual:
                if categoria_actual is not None:
                    cv.showPage()
                categoria_actual = cat
                _header(categoria_actual)
                y = alto_pagina - margen - alto_hdr
                col = 0
            if col == 0 and y - alto_fila < margen_ext + 6*mm:
                cv.showPage()
                _header(categoria_actual)
                y = alto_pagina - margen - alto_hdr
            x = margen + col * cel_ancho
            _dibujar_celda_folleto(cv, prod, x, y - alto_fila, cel_ancho,
                                  alto_fila, color_marca, color_precio)
            col += 1
            if col >= cols:
                col = 0
                y -= alto_fila
                cv.setStrokeColor(colors.HexColor("#DADADA"))
                cv.setLineWidth(0.5)
                cv.line(margen, y, ancho_pagina - margen, y)
    else:
        # Modo consolidado: todos los productos juntos, sin separar
        # por categoría — un único título genérico ("Ofertas").
        _header("Ofertas")
        y = alto_pagina - margen - alto_hdr
        col = 0
        for prod in productos:
            if col == 0 and y - alto_fila < margen_ext + 6*mm:
                cv.showPage()
                _header("Ofertas")
                y = alto_pagina - margen - alto_hdr
            x = margen + col * cel_ancho
            _dibujar_celda_folleto(cv, prod, x, y - alto_fila, cel_ancho,
                                  alto_fila, color_marca, color_precio)
            col += 1
            if col >= cols:
                col = 0
                y -= alto_fila
                cv.setStrokeColor(colors.HexColor("#DADADA"))
                cv.setLineWidth(0.5)
                cv.line(margen, y, ancho_pagina - margen, y)

    cv.save()
    return ruta_salida


def _dibujar_celda_folleto(cv, prod, x, y, ancho, alto, color_marca, color_precio):
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader

    pad = 3 * mm

    # ── Foto grande, centrada arriba de la celda ────────────────────
    foto_lado = min(ancho - 2*pad, alto * 0.58)
    foto_x = x + (ancho - foto_lado) / 2
    foto_y = y + alto - foto_lado - 3*mm

    img_pil = imagenes.cargar_imagen_pil(prod.get("imagen_url"))
    if img_pil:
        try:
            cv.drawImage(ImageReader(img_pil), foto_x, foto_y,
                        width=foto_lado, height=foto_lado,
                        preserveAspectRatio=True, anchor='c', mask='auto')
        except Exception as e:
            logging.warning(f"No se pudo dibujar imagen en folleto: {e}")
            img_pil = None
    if not img_pil:
        cv.setFillColor(colors.HexColor("#F3F4F6"))
        cv.rect(foto_x, foto_y, foto_lado, foto_lado, fill=1, stroke=0)
        cv.setFillColor(colors.HexColor("#9CA3AF"))
        cv.setFont("Helvetica", 7)
        cv.drawCentredString(foto_x + foto_lado/2, foto_y + foto_lado/2, "sin foto")
        cv.setFillColor(colors.black)

    # ── Precio: cartel superpuesto en la esquina inf. derecha de la foto.
    # La más barata va primero, grande, indicando la cantidad necesaria
    # (ej "$1,650 x12"); el resto de las escalas se listan más chico
    # debajo, para no perder la promoción como pasaba antes ──────────
    precios = _get_precios_producto(prod["id"], prod["precio_base"])
    if not precios:
        precios = [{"precio": prod["precio_base"], "cantidad": 1, "label": "Precio unitario"}]

    principal = precios[0]
    cant_principal = int(principal["cantidad"])
    unidad_txt = "x Kg" if prod.get("vendido_por_peso") else "c/u"
    precio_txt = f"$ {principal['precio']:,.0f} {unidad_txt}"

    fuente_precio, size_precio = "Helvetica-Bold", 14
    ancho_max_badge = ancho - 2*pad
    txt_w = cv.stringWidth(precio_txt, fuente_precio, size_precio)
    while txt_w + 6*mm > ancho_max_badge and size_precio > 9:
        size_precio -= 0.5
        txt_w = cv.stringWidth(precio_txt, fuente_precio, size_precio)
    badge_w = min(ancho_max_badge, txt_w + 6*mm)
    badge_h = 8*mm
    badge_x = foto_x + foto_lado - badge_w * 0.55
    badge_x = max(x + pad, min(badge_x, x + ancho - pad - badge_w))
    # Antes el cartel se superponía sobre la parte de abajo de la foto
    # (quedaba raro contra fondos de producto con mucho detalle). Ahora
    # va debajo, sin tocarla.
    badge_y = foto_y - badge_h - 2*mm

    # Tag vertical "LLEVANDO N", al costado izquierdo del cartel de
    # precio, con el texto leyéndose de abajo hacia arriba — SOLO
    # letras, sin caja de fondo. Solo aparece si hay una promoción por
    # cantidad; un producto sin promo no lo necesita.
    if cant_principal > 1:
        tag_w = 6.5 * mm
        # Ahora que el precio va debajo de la foto (ya no superpuesto),
        # el tag acompaña el bloque foto+precio completo — si solo
        # tomara el alto del badge no entraría el texto rotado.
        tag_h = (foto_y + foto_lado) - badge_y
        tag_texto = f"LLEVANDO {cant_principal}"
        tag_x = badge_x - tag_w - 1.5*mm
        tag_y = badge_y

        if tag_x < x + pad:
            corrimiento = (x + pad) - tag_x
            tag_x += corrimiento
            badge_x = min(badge_x + corrimiento, x + ancho - pad - badge_w)

        cv.saveState()
        cv.setFillColor(color_marca)
        fuente_tag, size_tag = "Helvetica-Bold", 9
        while (cv.stringWidth(tag_texto, fuente_tag, size_tag) > tag_h - 3*mm
              and size_tag > 5):
            size_tag -= 0.5
        cv.setFont(fuente_tag, size_tag)
        cv.translate(tag_x + tag_w/2, tag_y + tag_h/2)
        cv.rotate(90)
        cv.drawCentredString(0, -size_tag*0.32, tag_texto)
        cv.restoreState()
        cv.setFillColor(colors.black)

    cv.setFillColor(color_precio)
    cv.roundRect(badge_x, badge_y, badge_w, badge_h, 1.6*mm, fill=1, stroke=0)
    cv.setFillColor(colors.white)
    cv.setFont(fuente_precio, size_precio)
    cv.drawCentredString(badge_x + badge_w/2, badge_y + badge_h/2 - size_precio*0.35,
                        precio_txt)
    cv.setFillColor(colors.black)

    y_bajo = badge_y - 6*mm

    # Resto de las escalas (si hay), debajo del cartel principal
    resto = precios[1:]
    if resto:
        partes = [f"x{int(t['cantidad'])}: $ {t['precio']:,.0f}" for t in resto[:2]]
        if len(resto) > 2:
            partes.append(f"+{len(resto)-2}")
        extra_txt = "   ·   ".join(partes)
        cv.setFont("Helvetica-Bold", 8.5)
        cv.setFillColor(colors.HexColor("#444444"))
        cv.drawRightString(badge_x + badge_w, y_bajo, extra_txt)
        cv.setFillColor(colors.black)
        y_bajo -= 4.2*mm

    # Código del producto, debajo — salvo que sea un código provisorio
    # interno, o que el usuario haya desactivado mostrarlo en Config
    codigo = prod.get("codigo") or ""
    mostrar_codigo = cfg().get("folleto_mostrar_codigo", True)
    if mostrar_codigo and codigo and not codigo.startswith(("FACT-", "PESO-")):
        cv.setFont("Helvetica", 8)
        cv.setFillColor(colors.HexColor("#666666"))
        cv.drawRightString(badge_x + badge_w, y_bajo, codigo)
        cv.setFillColor(colors.black)
        y_texto = y_bajo - 6.5*mm
    else:
        y_texto = y_bajo

    # ── Marca + descripción, alineadas a la izquierda de la celda ───
    texto_x = x + pad
    texto_ancho = ancho - 2*pad

    if prod.get("marca"):
        cv.setFont("Helvetica-Bold", 15)
        cv.setFillColor(color_marca)
        marca_txt = prod["marca"].upper()
        while cv.stringWidth(marca_txt, "Helvetica-Bold", 15) > texto_ancho and len(marca_txt) > 3:
            marca_txt = marca_txt[:-1]
        cv.drawString(texto_x, y_texto, marca_txt)
        cv.setFillColor(colors.black)
        y_texto -= 4.5*mm

    cv.setFont("Helvetica-Bold", 10)
    palabras = prod["descripcion"].upper().split()
    lineas, linea = [], ""
    for palabra in palabras:
        prueba = (linea + " " + palabra).strip()
        if cv.stringWidth(prueba, "Helvetica-Bold", 10) <= texto_ancho:
            linea = prueba
        else:
            if linea:
                lineas.append(linea)
            linea = palabra
    if linea:
        lineas.append(linea)
    for l in lineas[:2]:
        if y_texto < y + pad:
            break
        cv.drawString(texto_x, y_texto, l)
        y_texto -= 4.3*mm


# ─────────────────────────────────────────────────────────────────────────────
# SELECTOR (UI) — mismo patrón que lista_precios.py
# ─────────────────────────────────────────────────────────────────────────────

def abrir_selector_folleto(parent):
    """Diálogo para elegir qué productos incluir y generar el folleto PDF."""
    import sys
    import tkinter as tk
    from tkinter import ttk, messagebox
    from styles import C, F, btn, lbl, card

    d = tk.Toplevel(parent)
    d.title("Exportar folleto de ofertas")
    d.resizable(True, True)
    d.configure(bg=C.bg)
    d.grab_set()
    sw, sh = d.winfo_screenwidth(), d.winfo_screenheight()
    w, h = min(820, sw-60), min(600, sh-60)
    d.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
    d.columnconfigure(0, weight=1)
    d.rowconfigure(3, weight=1)

    hdr = tk.Frame(d, bg=C.bg)
    hdr.grid(row=0, column=0, sticky="ew", padx=12, pady=(12,4))
    lbl(hdr, "Exportar folleto de ofertas", variante="titulo").pack(side="left")
    lbl(hdr, "Foto grande + precio en cartel, estilo mayorista",
        variante="suave").pack(side="left", padx=12)

    var_consolidar = tk.BooleanVar(value=False)
    chk_consolidar = tk.Checkbutton(
        d, text="Consolidar todos los productos juntos (sin separar por categoría)",
        variable=var_consolidar, bg=C.bg, fg=C.texto, font=F.normal,
        selectcolor=C.bg, anchor="w")
    chk_consolidar.grid(row=1, column=0, sticky="w", padx=12, pady=(0,4))

    bar = tk.Frame(d, bg=C.bg)
    bar.grid(row=2, column=0, sticky="ew", padx=12, pady=(0,6))
    lbl(bar, "Buscar:").pack(side="left", padx=(0,6))
    entry_buscar = tk.Entry(bar, font=F.normal, width=28,
                            bg=C.superficie, fg=C.texto, relief="solid", bd=1)
    entry_buscar.pack(side="left", ipady=5)

    COLS = [
        ("sel",    "",           30,  "center"),
        ("codigo", "Codigo",     90,  "w"),
        ("desc",   "Producto",  260,  "w"),
        ("precio", "Precio u.",  85,  "e"),
        ("categoria", "Categoria", 120, "w"),
        ("foto",   "Foto",       50,  "center"),
    ]

    f_tabla = card(d)
    f_tabla.grid(row=3, column=0, sticky="nsew", padx=12, pady=(0,6))
    f_tabla.columnconfigure(0, weight=1)
    f_tabla.rowconfigure(0, weight=1)

    tree = ttk.Treeview(f_tabla, columns=[c[0] for c in COLS],
                       show="headings", selectmode="browse")
    for col_id, header, ancho, anchor in COLS:
        tree.heading(col_id, text=header, anchor="w")
        tree.column(col_id, width=ancho, anchor=anchor, minwidth=30)
    sb = ttk.Scrollbar(f_tabla, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=sb.set)
    tree.grid(row=0, column=0, sticky="nsew")
    sb.grid(row=0, column=1, sticky="ns")

    seleccionados = {}
    todos_prods   = {}

    def cargar(filtro=""):
        for r in tree.get_children():
            tree.delete(r)
        for p in get_productos(filtro=filtro):
            todos_prods[p["codigo"]] = p
            sel = "x" if p["codigo"] in seleccionados else ""
            tree.insert("", "end", iid=p["codigo"], values=(
                sel, p["codigo"], p["descripcion"],
                f"$ {p['precio_base']:,.2f}", p.get("categoria") or "—",
                "Sí" if p.get("imagen_url") else "—",
            ))

    cargar()
    entry_buscar.bind("<KeyRelease>",
                      lambda e: cargar(entry_buscar.get().strip()))

    def _on_click(event):
        iid = tree.identify_row(event.y)
        col = tree.identify_column(event.x)
        if not iid or col != "#1":
            return
        if iid in seleccionados:
            del seleccionados[iid]
            tree.set(iid, "sel", "")
        else:
            seleccionados[iid] = True
            tree.set(iid, "sel", "x")
        _actualizar_lbl()

    tree.bind("<ButtonRelease-1>", _on_click)

    bot = tk.Frame(d, bg=C.bg)
    bot.grid(row=4, column=0, sticky="ew", padx=12, pady=(0,12))

    lbl_sel = lbl(bot, "Ninguno seleccionado", variante="suave")
    lbl_sel.pack(side="left")

    def _actualizar_lbl():
        n = len(seleccionados)
        lbl_sel.config(text=f"{n} producto{'s' if n != 1 else ''} seleccionado{'s' if n != 1 else ''}"
                      if n else "Ninguno seleccionado")

    def _sel_todo():
        for iid in tree.get_children():
            seleccionados[iid] = True
            tree.set(iid, "sel", "x")
        _actualizar_lbl()

    def _desel_todo():
        seleccionados.clear()
        for iid in tree.get_children():
            tree.set(iid, "sel", "")
        _actualizar_lbl()

    btn(bot, "Todo", variante="neutro", comando=_sel_todo).pack(side="left", padx=(12,4))
    btn(bot, "Nada", variante="neutro", comando=_desel_todo).pack(side="left")

    def generar():
        if not seleccionados:
            messagebox.showinfo("Atencion",
                "Selecciona al menos un producto.", parent=d)
            return
        prods = [todos_prods[cod] for cod in seleccionados if cod in todos_prods]

        d.config(cursor="wait")
        d.update()
        ruta = generar_pdf_folleto(prods, agrupar_por_categoria=not var_consolidar.get())
        d.config(cursor="")

        if ruta:
            if sys.platform == "win32":
                os.startfile(ruta)
            messagebox.showinfo("Listo",
                f"Folleto generado y abierto.\n{ruta}", parent=d)
            d.destroy()
        else:
            messagebox.showerror("Error",
                "No se pudo generar el PDF.\n"
                "Instala reportlab: pip install reportlab", parent=d)

    btn(bot, "🗞️ Generar folleto", variante="exito",
        comando=generar).pack(side="right")
    btn(bot, "Cancelar", variante="neutro",
        comando=d.destroy).pack(side="right", padx=(0,8))

"""
lista_precios.py — Exportación de la lista de precios en PDF TPV v2.0

Genera un catálogo tipo mayorista: foto del producto (si tiene),
nombre, precio, y las promociones por cantidad vigentes si existen
(ej: "Llevando 3: $X c/u"), reutilizando la misma lógica de precios
que ya usan las etiquetas de góndola (etiquetas.py).
"""

import os
import sys
import tempfile
import logging
from datetime import datetime

from config import cfg
from repositorio import get_productos
from etiquetas import _get_precios_producto
import imagenes


# ─────────────────────────────────────────────────────────────────────────────
# GENERACIÓN PDF
# ─────────────────────────────────────────────────────────────────────────────

def generar_pdf_lista_precios(productos: list[dict],
                              ruta_salida: str = None) -> str | None:
    """
    Genera el PDF de la lista de precios para los productos dados.
    Una línea por producto (más si tiene varias escalas de precio por
    cantidad — cada escala en su propia línea, alineadas, la más
    barata destacada), agrupados por categoría, marca y descripción.
    Retorna la ruta del PDF, o None si falla.
    """
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.pdfgen import canvas
        from reportlab.lib import colors
    except ImportError as e:
        logging.error(f"reportlab error de importacion: {e}")
        return None

    if not productos:
        return None

    if not ruta_salida:
        nombre = f"lista_precios_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
        ruta_salida = os.path.join(tempfile.gettempdir(), nombre)

    c_cfg = cfg()
    ancho_pagina, alto_pagina = A4
    margen        = 14 * mm
    alto_hdr       = 14 * mm
    alto_fila_base = 13 * mm
    alto_por_tier  = 4.6 * mm
    alto_cat       = 7 * mm
    ancho_util = ancho_pagina - 2 * margen

    def _altura_fila(n_tiers):
        if n_tiers <= 1:
            return alto_fila_base
        return max(alto_fila_base, n_tiers * alto_por_tier + 3 * mm)

    # Orden: categoría, luego marca, luego descripción.
    productos = sorted(productos, key=lambda p: (
        (p.get("categoria") or "Sin categoría").lower(),
        (p.get("marca") or "").lower(),
        p["descripcion"].lower()))

    cv = canvas.Canvas(ruta_salida, pagesize=A4)

    def _header():
        cv.setFont("Helvetica-Bold", 15)
        cv.drawString(margen, alto_pagina - margen,
                      c_cfg.get("negocio_nombre") or "Lista de precios")
        cv.setFont("Helvetica", 8)
        cv.setFillColor(colors.grey)
        cv.drawRightString(ancho_pagina - margen, alto_pagina - margen,
                          f"Generado: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
        cv.setStrokeColor(colors.HexColor("#CCCCCC"))
        cv.line(margen, alto_pagina - margen - 3*mm,
               ancho_pagina - margen, alto_pagina - margen - 3*mm)
        cv.setFillColor(colors.black)

    _header()
    y = alto_pagina - margen - alto_hdr
    categoria_actual = None

    for prod in productos:
        cat = prod.get("categoria") or "Sin categoría"
        precios = _get_precios_producto(prod["id"], prod["precio_base"],
                                            prod.get("_recargo", 0.0))
        alto_prod = _altura_fila(len(precios))

        necesita = alto_prod + (alto_cat if cat != categoria_actual else 0)
        if y - necesita < margen:
            cv.showPage()
            _header()
            y = alto_pagina - margen - alto_hdr
            categoria_actual = None   # repetir encabezado de categoria en la pagina nueva

        if cat != categoria_actual:
            y -= alto_cat
            cv.setFillColor(colors.HexColor("#EEF2FF"))
            cv.rect(margen, y, ancho_util, alto_cat, fill=1, stroke=0)
            cv.setFillColor(colors.HexColor("#3730A3"))
            cv.setFont("Helvetica-Bold", 10)
            cv.drawString(margen + 2*mm, y + 2*mm, cat.upper())
            cv.setFillColor(colors.black)
            categoria_actual = cat

        y -= alto_prod
        _dibujar_fila(cv, prod, precios, margen, y, ancho_util, alto_prod,
                     alto_fila_base)

    cv.save()
    return ruta_salida


def _dibujar_fila(cv, prod, precios, x, y, ancho, alto, alto_fila_base):
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader

    pad = 1.5 * mm
    ancho_precios = 34 * mm   # columna de precio de ancho fijo: todo alineado entre filas

    cv.setStrokeColor(colors.HexColor("#E2E5ED"))
    cv.line(x, y, x + ancho, y)

    # ── Foto chica, cuadrada, a la izquierda — siempre el mismo
    # tamaño (no crece aunque la fila sea más alta por varias
    # escalas de precio), centrada verticalmente en la fila ─────────
    foto_lado = alto_fila_base - 2 * pad
    foto_x = x + pad
    foto_y = y + (alto - foto_lado) / 2

    img_pil = imagenes.cargar_imagen_pil(prod.get("imagen_url"))
    if img_pil:
        try:
            cv.drawImage(ImageReader(img_pil), foto_x, foto_y,
                        width=foto_lado, height=foto_lado,
                        preserveAspectRatio=True, anchor='c', mask='auto')
        except Exception as e:
            logging.warning(f"No se pudo dibujar imagen en PDF: {e}")
            img_pil = None
    if not img_pil:
        cv.setFillColor(colors.HexColor("#F3F4F6"))
        cv.rect(foto_x, foto_y, foto_lado, foto_lado, fill=1, stroke=0)
        cv.setFillColor(colors.HexColor("#9CA3AF"))
        cv.setFont("Helvetica", 5)
        cv.drawCentredString(foto_x + foto_lado/2, foto_y + foto_lado/2, "s/foto")
        cv.setFillColor(colors.black)

    # ── Precio(s): columna de ancho fijo a la derecha, una escala
    # por línea, alineadas, la más barata (siempre precios[0]) grande
    # y destacada arriba ─────────────────────────────────────────────
    unidad = "/kg" if prod.get("vendido_por_peso") else " c/u"
    precio_x_fin = x + ancho - pad
    label_x = precio_x_fin - ancho_precios + 1*mm

    if len(precios) <= 1:
        precio_txt = f"$ {prod['precio_base']:,.2f}{unidad}"
        cv.setFont("Helvetica-Bold", 10)
        cv.setFillColor(colors.HexColor("#1D4ED8"))
        cv.drawRightString(precio_x_fin, y + alto/2 - 1.3*mm, precio_txt)
        cv.setFillColor(colors.black)
    else:
        alto_bloque = len(precios) * 4.3*mm
        y_linea = y + alto/2 + alto_bloque/2 - 3*mm
        for i, p in enumerate(precios):
            es_principal = (i == 0)
            cant_txt = f"x{int(p['cantidad'])}" if p["cantidad"] > 1 else "x1"
            precio_txt = f"$ {p['precio']:,.2f}"
            if es_principal:
                cv.setFont("Helvetica-Bold", 10)
                cv.setFillColor(colors.HexColor("#1D4ED8"))
            else:
                cv.setFont("Helvetica", 8)
                cv.setFillColor(colors.HexColor("#555555"))
            cv.drawString(label_x, y_linea, cant_txt)
            cv.drawRightString(precio_x_fin, y_linea, precio_txt)
            cv.setFillColor(colors.black)
            y_linea -= 4.3*mm if es_principal else 4.0*mm

    # ── Descripción: a la izquierda de la foto, con todo el ancho
    # disponible hasta donde empieza la columna de precios,
    # centrada verticalmente en la fila ──────────────────────────────
    texto_x = foto_x + foto_lado + 2.5*mm
    texto_ancho = (precio_x_fin - ancho_precios - 3*mm) - texto_x

    nombre = prod["descripcion"]
    if prod.get("marca"):
        nombre = f"{prod['marca']} — {nombre}"
    fuente, size = "Helvetica-Bold", 10
    while cv.stringWidth(nombre, fuente, size) > texto_ancho and size > 6:
        size -= 0.5
    if cv.stringWidth(nombre, fuente, size) > texto_ancho:
        while nombre and cv.stringWidth(nombre + "…", fuente, size) > texto_ancho:
            nombre = nombre[:-1]
        nombre += "…"
    cv.setFont(fuente, size)
    cv.drawString(texto_x, y + alto/2 - 1.3*mm, nombre)


# ─────────────────────────────────────────────────────────────────────────────
# SELECTOR (UI)
# ─────────────────────────────────────────────────────────────────────────────

def abrir_selector_lista_precios(parent):
    """Diálogo para elegir qué productos incluir y generar el PDF."""
    import tkinter as tk
    from tkinter import ttk, messagebox
    from styles import C, F, btn, lbl, card

    d = tk.Toplevel(parent)
    d.title("Exportar lista de precios")
    d.resizable(True, True)
    d.configure(bg=C.bg)
    d.grab_set()
    sw, sh = d.winfo_screenwidth(), d.winfo_screenheight()
    w, h = min(820, sw-60), min(600, sh-60)
    d.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
    d.columnconfigure(0, weight=1)
    d.rowconfigure(2, weight=1)

    hdr = tk.Frame(d, bg=C.bg)
    hdr.grid(row=0, column=0, sticky="ew", padx=12, pady=(12,4))
    lbl(hdr, "Exportar lista de precios", variante="titulo").pack(side="left")
    lbl(hdr, "Incluye foto y promociones vigentes de cada producto",
        variante="suave").pack(side="left", padx=12)

    bar = tk.Frame(d, bg=C.bg)
    bar.grid(row=1, column=0, sticky="ew", padx=12, pady=(0,6))
    lbl(bar, "Buscar:").pack(side="left", padx=(0,6))
    entry_buscar = tk.Entry(bar, font=F.normal, width=28,
                            bg=C.superficie, fg=C.texto, relief="solid", bd=1)
    entry_buscar.pack(side="left", ipady=5)

    # ── Lista de precios de un vendedor ───────────────────────────────
    # Un vendedor con comision "recargo" tiene SU propia lista: precio
    # normal + costo x comision%, y solo sus categorias habilitadas.
    from repositorio import get_vendedores, productos_para_vendedor
    _vends = [{"id": None, "nombre": "Lista general (precios propios)"}] + [
        dict(v) for v in get_vendedores() if v["activo"]]
    lbl(bar, "Precios de:").pack(side="left", padx=(14, 6))
    var_vend = tk.StringVar(value=_vends[0]["nombre"])
    combo_vend = ttk.Combobox(bar, textvariable=var_vend, width=26,
                              state="readonly",
                              values=[v["nombre"] for v in _vends])
    combo_vend.pack(side="left")

    def _vendedor_elegido():
        return _vends[[v["nombre"] for v in _vends].index(var_vend.get())]["id"]

    # Filtro por categoria y por foto, igual que en el folleto: una lista
    # de precios suele ser de un rubro, no del catalogo entero.
    from repositorio import get_categorias
    lbl(bar, "Categoria:").pack(side="left", padx=(14, 6))
    _cats = [{"id": None, "nombre": "Todas"}] + list(get_categorias())
    var_cat = tk.StringVar(value="Todas")
    combo_cat = ttk.Combobox(bar, textvariable=var_cat, width=20,
                             state="readonly",
                             values=[c["nombre"] for c in _cats])
    combo_cat.pack(side="left")

    var_solo_foto = tk.BooleanVar(value=False)
    tk.Checkbutton(bar, text="Solo con foto", variable=var_solo_foto,
                   bg=C.bg, fg=C.texto, font=F.normal, selectcolor=C.bg,
                   activebackground=C.bg).pack(side="left", padx=(14, 0))

    COLS = [
        ("sel",    "",           30,  "center"),
        ("codigo", "Codigo",     90,  "w"),
        ("desc",   "Producto",  260,  "w"),
        ("precio", "Precio u.",  85,  "e"),
        ("promos", "Promos",    180,  "w"),
        ("foto",   "Foto",       50,  "center"),
    ]

    f_tabla = card(d)
    f_tabla.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0,6))
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

    seleccionados = {}   # codigo -> True
    todos_prods   = {}   # codigo -> dict

    def _resumen_promos(prod_id, precio_base, recargo=0.0):
        precios = _get_precios_producto(prod_id, precio_base, recargo)
        if len(precios) <= 1:
            return "—"
        return "  |  ".join(f"x{p['cantidad']} ${p['precio']:,.0f}" for p in precios)

    def cargar(filtro=""):
        for r in tree.get_children():
            tree.delete(r)
        cat_id = _cats[[c["nombre"] for c in _cats].index(var_cat.get())]["id"]
        lista, _com = productos_para_vendedor(
            get_productos(filtro=filtro, categoria_id=cat_id),
            _vendedor_elegido())
        for p in lista:
            if var_solo_foto.get() and not p.get("imagen_url"):
                continue
            todos_prods[p["codigo"]] = p
            sel = "x" if p["codigo"] in seleccionados else ""
            promos = _resumen_promos(p["id"], p["precio_base"],
                                     p.get("_recargo", 0.0))
            tree.insert("", "end", iid=p["codigo"], values=(
                sel, p["codigo"], p["descripcion"],
                f"$ {p['precio_base']:,.2f}", promos,
                "Sí" if p.get("imagen_url") else "—",
            ))

    cargar()
    entry_buscar.bind("<KeyRelease>",
                      lambda e: cargar(entry_buscar.get().strip()))
    def _recargar(*_a):
        cargar(entry_buscar.get().strip())
        _actualizar_lbl()

    combo_vend.bind("<<ComboboxSelected>>", _recargar)
    combo_cat.bind("<<ComboboxSelected>>", _recargar)
    var_solo_foto.trace_add("write", _recargar)

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
    bot.grid(row=3, column=0, sticky="ew", padx=12, pady=(0,12))

    lbl_sel = lbl(bot, "Ninguno seleccionado", variante="suave")
    lbl_sel.pack(side="left")

    def _actualizar_lbl():
        n = len(seleccionados)
        base = (f"{n} producto{'s' if n != 1 else ''} seleccionado{'s' if n != 1 else ''}"
                if n else "Ninguno seleccionado")
        lbl_sel.config(text=f"{base}   ·   {len(tree.get_children())} en pantalla")

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

    # "Todo" marcaba lo visible, pero con filtros activos el nombre
    # hacia pensar que marcaba el catalogo entero.
    btn(bot, "Marcar los visibles", variante="neutro",
        comando=_sel_todo).pack(side="left", padx=(12,4))
    btn(bot, "Desmarcar todo", variante="neutro",
        comando=_desel_todo).pack(side="left")

    def generar():
        if not seleccionados:
            messagebox.showinfo("Atencion",
                "Selecciona al menos un producto.", parent=d)
            return
        prods = [todos_prods[cod] for cod in seleccionados if cod in todos_prods]

        d.config(cursor="wait")
        d.update()
        ruta = generar_pdf_lista_precios(prods)
        d.config(cursor="")

        if ruta:
            if sys.platform == "win32":
                os.startfile(ruta)
            # Igual que en el folleto: se queda abierto para poder
            # generar la lista de otro vendedor sin rearmar todo.
            messagebox.showinfo("Listo",
                f"PDF generado y abierto.\n{ruta}\n\n"
                "La ventana queda abierta por si querés generar otra "
                "(por ejemplo, con los precios de otro vendedor).",
                parent=d)
        else:
            messagebox.showerror("Error",
                "No se pudo generar el PDF.\n"
                "Instala reportlab: pip install reportlab", parent=d)

    btn(bot, "📄 Generar PDF", variante="exito",
        comando=generar).pack(side="right")
    btn(bot, "Cerrar", variante="neutro",
        comando=d.destroy).pack(side="right", padx=(0,8))

"""
etiquetas.py — Etiquetas de góndola estilo mayorista TPV v2.0

Formato:
  - Nombre del producto
  - Precio MAS BARATO grande (con su promocion: "Llevando 10")
  - Precios secundarios mas chicos (llevando 3, llevando 1)
  - Si precio unico: solo ese en grande
  - Codigo de barras al pie

Configuracion en config.py: etiqueta_ancho_mm, etiqueta_alto_mm, etc.
"""

import os
import sys
import tempfile
import logging
from datetime import datetime
from config import cfg
from repositorio import get_productos
from db import get_connection


# ─────────────────────────────────────────────────────────────────────────────
# DATOS
# ─────────────────────────────────────────────────────────────────────────────

def _get_precios_producto(producto_id: int, precio_base: float) -> list[dict]:
    """
    Retorna lista de precios ordenados de menor a mayor precio unitario.
    Incluye precio base y todas las promos vigentes.
    Formato: [{"precio": float, "cantidad": int, "label": str}]
    """
    hoy = datetime.now().strftime("%Y-%m-%d")
    with get_connection() as conn:
        promos = conn.execute("""
            SELECT cantidad_minima, precio_unitario
            FROM promociones
            WHERE producto_id = ? AND activa = 1
              AND (fecha_desde IS NULL OR fecha_desde <= ?)
              AND (fecha_hasta IS NULL OR fecha_hasta >= ?)
            ORDER BY precio_unitario ASC
        """, (producto_id, hoy, hoy)).fetchall()

    precios = []

    # Agregar promos
    for p in promos:
        precios.append({
            "precio":   p["precio_unitario"],
            "cantidad": p["cantidad_minima"],
            "label":    f"Llevando {p['cantidad_minima']}",
        })

    # Agregar precio base si no hay promo con cant=1 o es distinto
    cantidades_existentes = {p["cantidad"] for p in precios}
    if 1 not in cantidades_existentes:
        precios.append({
            "precio":   precio_base,
            "cantidad": 1,
            "label":    "Precio unitario",
        })

    # Ordenar de menor a mayor precio (el más barato primero)
    precios.sort(key=lambda x: x["precio"])
    return precios


# ─────────────────────────────────────────────────────────────────────────────
# GENERACIÓN PDF
# ─────────────────────────────────────────────────────────────────────────────

def generar_pdf_etiquetas(productos: list[dict],
                           ruta_salida: str = None) -> str | None:
    """
    Genera PDF con etiquetas estilo mayorista.
    Retorna ruta del PDF o None si falla.
    """
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.pdfgen import canvas
    except ImportError as e:
        logging.error(f"reportlab error de importacion: {e}")
        return None
    except Exception as e:
        logging.error(f"Error inesperado al importar reportlab: {e}")
        return None

    c    = cfg()
    ancho = c["etiqueta_ancho_mm"] * mm
    alto  = c["etiqueta_alto_mm"]  * mm
    cols  = c["etiqueta_cols"]
    filas = c["etiqueta_filas"]
    espacio = c.get("etiqueta_espacio_mm", 0) * mm
    margen_y = c.get("etiqueta_margen_arriba_mm", 10) * mm

    ancho_paso = ancho + espacio    # lo que avanza cada columna
    alto_paso  = alto + margen_y    # lo que avanza cada fila — el mismo
                                     # espacio "de arriba" se repite entre
                                     # TODAS las filas, no solo antes de
                                     # la primera

    margen_x = (A4[0] - (cols * ancho + (cols - 1) * espacio)) / 2

    if not ruta_salida:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        ruta_salida = os.path.join(
            tempfile.gettempdir(), f"etiquetas_{ts}.pdf")

    cv = canvas.Canvas(ruta_salida, pagesize=A4)
    pg_ancho, pg_alto = A4

    idx = 0
    while idx < len(productos):
        for fila in range(filas):
            for col in range(cols):
                if idx >= len(productos):
                    break
                prod = productos[idx]
                idx += 1
                x = margen_x + col * ancho_paso
                y = pg_alto - margen_y - fila * alto_paso - alto
                _dibujar_etiqueta(cv, prod, x, y, ancho, alto)

        if idx < len(productos):
            cv.showPage()

    cv.save()
    return ruta_salida


def _dibujar_etiqueta(cv, prod, x, y, ancho, alto):
    """
    Layout estilo mayorista en zonas:
      1. Header oscuro — nombre del producto destacado
      2. Cuerpo — label promo izq | precio principal der
      3. Franja gris — precios secundarios
      4. Pie — código de barras
    """
    from reportlab.lib.units import mm
    from reportlab.lib import colors

    c      = cfg()
    pad    = 2 * mm
    sym    = c["moneda_simbolo"]

    fn_nombre = c.get("etiqueta_font_nombre",     18)
    fn_label  = c.get("etiqueta_font_label",       9)
    fn_precio = c.get("etiqueta_font_precio",     22)
    fn_sec    = c.get("etiqueta_font_secundario", 11)
    fn_codigo = c.get("etiqueta_font_codigo",     12)

    precios = _get_precios_producto(prod["id"], prod["precio_base"])
    # precios[0] = más barato (promo principal), último = precio unitario

    # ── Alturas de zonas ─────────────────────────────────────────────────────
    # Zonas proporcionales al alto total
    header_h = alto * 0.28   # 28% — nombre
    pie_h    = alto * 0.28   # 28% — barcode
    franja_h = alto * 0.18   # 18% — precios secundarios
    cuerpo_h = alto * 0.26   # 26% — precio principal

    y_header = y + alto - header_h
    y_cuerpo = y_header - cuerpo_h
    y_franja = y_cuerpo - franja_h
    y_pie    = y

    # ── 1. Header — fondo oscuro, nombre blanco ───────────────────────────────
    cv.setFillColor(colors.HexColor("#1E293B"))
    cv.rect(x, y_header, ancho, header_h, fill=1, stroke=0)

    nombre = prod.get("nombre_generico") or prod.get("descripcion", "")
    cv.setFont("Helvetica-Bold", fn_nombre)
    max_chars = int((ancho - 2*pad) / max(1, fn_nombre * 0.55))
    if len(nombre) > max_chars:
        nombre = nombre[:max_chars-2] + ".."
    cv.setFillColor(colors.white)
    cv.drawString(x + pad,
                  y_header + (header_h - fn_nombre * 0.35 * mm) / 2,
                  nombre.upper())

    # ── 2. Cuerpo — label izquierda, precio derecha ───────────────────────────
    cv.setFillColor(colors.white)
    cv.rect(x, y_cuerpo, ancho, cuerpo_h, fill=1, stroke=0)

    mejor = precios[0]
    precio_str = f"{sym} {mejor['precio']:,.2f} c/u"

    # Label promo (solo si hay promo — cantidad > 1)
    if mejor["cantidad"] > 1:
        cv.setFont("Helvetica-Bold", fn_label)
        cv.setFillColor(colors.HexColor("#374151"))
        cv.drawString(x + pad,
                      y_cuerpo + cuerpo_h - fn_label * 0.4 * mm - pad,
                      mejor["label"].upper())

    # Precio grande — alineado a la derecha
    cv.setFont("Helvetica-Bold", fn_precio)
    cv.setFillColor(colors.black)
    pw = cv.stringWidth(precio_str, "Helvetica-Bold", fn_precio)
    cv.drawString(x + ancho - pw - pad,
                  y_cuerpo + (cuerpo_h - fn_precio * 0.35 * mm) / 2,
                  precio_str)

    # Borde entre header y cuerpo
    cv.setStrokeColor(colors.HexColor("#CBD5E1"))
    cv.setLineWidth(0.3)
    cv.line(x, y_header, x + ancho, y_header)

    # ── 3. Franja — precios secundarios ──────────────────────────────────────
    cv.setFillColor(colors.HexColor("#F1F5F9"))
    cv.rect(x, y_franja, ancho, franja_h, fill=1, stroke=0)

    # Mostrar precios secundarios separados por |
    sec_items = []
    for p in precios[1:]:
        sec_items.append(f"{p['label']}: {sym} {p['precio']:,.2f}")

    sec_txt = "   |   ".join(sec_items) if sec_items else ""
    if sec_txt:
        cv.setFont("Helvetica", fn_sec)
        cv.setFillColor(colors.HexColor("#475569"))
        # Centrar en la franja
        sw = cv.stringWidth(sec_txt, "Helvetica", fn_sec)
        sx = x + (ancho - sw) / 2
        cv.drawString(sx,
                      y_franja + (franja_h - fn_sec * 0.35 * mm) / 2,
                      sec_txt)

    # ── 4. Pie — código de barras ─────────────────────────────────────────────
    cv.setFillColor(colors.white)
    cv.rect(x, y_pie, ancho, pie_h, fill=1, stroke=0)

    codigo = "" if prod.get("nombre_generico") else prod.get("codigo", "")
    if codigo:
        try:
            from reportlab.graphics.barcode import code128
            from reportlab.pdfbase.pdfmetrics import getAscent
            bc_ancho = ancho - 2 * pad
            bc_alto  = pie_h - 2 * mm
            n_barras = len(codigo) * 11 + 35
            bar_w    = max(0.5, min(1.0, bc_ancho / n_barras))

            # El texto legible (humanReadable) se dibuja POR DEBAJO del
            # origen del barcode (y=0 local), no adentro de barHeight.
            # Hay que calcular ese alto para: (1) no pasarnos con barHeight
            # y (2) subir el origen lo justo para que el texto no se corra
            # afuera de la etiqueta cuando la fuente es grande.
            font_codigo_nombre = "Courier"  # fuente por defecto de Code128
            texto_alto = 1.07 * getAscent(font_codigo_nombre) * fn_codigo / 1000.0

            bc = code128.Code128(
                codigo,
                barWidth=bar_w,
                barHeight=max(6*mm, bc_alto - texto_alto),
                humanReadable=True,
                fontSize=fn_codigo,
                quiet=False,
            )
            bc_w = bc.width
            bc_x = x + pad + max(0, (bc_ancho - bc_w) / 2)
            bc_y = y_pie + 1 * mm + texto_alto

            # El barcode NO fija su propio color: usa el fillColor que tenga
            # el canvas en ese momento. Como arriba se pintó el fondo del pie
            # en blanco, hay que volver a negro antes de dibujarlo o queda
            # invisible (blanco sobre blanco), aunque no tire ninguna excepción.
            cv.setFillColor(colors.black)
            bc.drawOn(cv, bc_x, bc_y)
        except Exception as _e:
            logging.error(f"Barcode error: {_e}")
            cv.setFillColor(colors.black)
            cv.drawCentredString(x + ancho / 2,
                                  y_pie + pie_h / 2, codigo)

    # ── Borde exterior ────────────────────────────────────────────────────────
    cv.setStrokeColor(colors.HexColor("#94A3B8"))
    cv.setLineWidth(0.5)
    cv.rect(x, y, ancho, alto, fill=0, stroke=1)
    # Línea franja superior
    cv.setLineWidth(0.3)
    cv.line(x, y_cuerpo, x + ancho, y_cuerpo)
    cv.line(x, y_franja, x + ancho, y_franja)
    cv.line(x, y_pie + pie_h, x + ancho, y_pie + pie_h)


def _font_size_para_ancho(cv, texto, ancho_max, size_max, size_min):
    """Calcula el tamaño de fuente más grande que entre en el ancho dado."""
    for size in range(size_max, size_min - 1, -1):
        w = cv.stringWidth(texto, "Helvetica-Bold", size)
        if w <= ancho_max:
            return size
    return size_min


# ─────────────────────────────────────────────────────────────────────────────
# UI — Selector de productos
# ─────────────────────────────────────────────────────────────────────────────

def abrir_selector_etiquetas(parent, productos_presel=None):
    """
    Diálogo para seleccionar productos y cantidad de etiquetas.
    productos_presel: lista de dicts de productos a pre-seleccionar.
    """
    import tkinter as tk
    from tkinter import ttk, messagebox, simpledialog
    from styles import C, F, btn, lbl, card

    d = tk.Toplevel(parent)
    d.title("Etiquetas de gondola")
    d.resizable(True, True)
    d.configure(bg=C.bg)
    d.grab_set()
    sw, sh = d.winfo_screenwidth(), d.winfo_screenheight()
    w, h = min(900, sw-60), min(640, sh-60)
    d.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
    d.columnconfigure(0, weight=1)
    d.rowconfigure(2, weight=1)

    # Header
    hdr = tk.Frame(d, bg=C.bg)
    hdr.grid(row=0, column=0, sticky="ew", padx=12, pady=(12,4))
    lbl(hdr, "Etiquetas de gondola", variante="titulo").pack(side="left")
    lbl(hdr, "Selecciona productos — click en cantidad para editarla, "
             "click en el nombre para ponerle un nombre genérico",
        variante="suave").pack(side="left", padx=12)

    # Filtro
    bar = tk.Frame(d, bg=C.bg)
    bar.grid(row=1, column=0, sticky="ew", padx=12, pady=(0,6))
    lbl(bar, "Buscar:").pack(side="left", padx=(0,6))
    entry_buscar = tk.Entry(bar, font=F.normal, width=28,
                             bg=C.superficie, fg=C.texto,
                             relief="solid", bd=1)
    entry_buscar.pack(side="left", ipady=5)

    # Tabla
    COLS = [
        ("sel",    "",            30,  "center"),
        ("codigo", "Codigo",      90,  "w"),
        ("desc",   "Producto",   260,  "w"),
        ("precio", "Precio u.",   85,  "e"),
        ("promos", "Promos",     160,  "w"),
        ("cant",   "Etiquetas",   70,  "e"),
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

    cantidades  = {}   # codigo → int
    todos_prods = {}   # codigo → dict
    nombres_genericos = {}   # codigo → texto personalizado para la etiqueta

    def _resumen_promos(prod_id, precio_base):
        precios = _get_precios_producto(prod_id, precio_base)
        if len(precios) <= 1:
            return "Precio unico"
        partes = []
        for p in precios:
            partes.append(f"x{p['cantidad']} ${p['precio']:,.0f}")
        return "  |  ".join(partes)

    def cargar(filtro=""):
        for r in tree.get_children():
            tree.delete(r)
        for p in get_productos(filtro=filtro):
            todos_prods[p["codigo"]] = p
            cant   = cantidades.get(p["codigo"], 1)
            sel    = "x" if p["codigo"] in cantidades else ""
            promos = _resumen_promos(p["id"], p["precio_base"])
            desc_mostrada = nombres_genericos.get(p["codigo"], p["descripcion"])
            if p["codigo"] in nombres_genericos:
                desc_mostrada += " ✎"
            tree.insert("", "end", iid=p["codigo"], values=(
                sel,
                p["codigo"],
                desc_mostrada,
                f"$ {p['precio_base']:,.2f}",
                promos,
                str(cant) if p["codigo"] in cantidades else "",
            ))

        # Pre-seleccionar si vinieron productos
        if productos_presel:
            for p in productos_presel:
                cod = p.get("codigo")
                if cod and cod in todos_prods:
                    cantidades[cod] = 1
                    tree.set(cod, "sel", "x")
                    tree.set(cod, "cant", "1")

    cargar()
    entry_buscar.bind("<KeyRelease>",
                      lambda e: cargar(entry_buscar.get().strip()))

    # Interacción
    def _on_click(event):
        iid = tree.identify_row(event.y)
        col = tree.identify_column(event.x)
        if not iid:
            return
        if col == "#1":   # toggle selección
            if iid in cantidades:
                del cantidades[iid]
                tree.set(iid, "sel",  "")
                tree.set(iid, "cant", "")
            else:
                cantidades[iid] = 1
                tree.set(iid, "sel",  "x")
                tree.set(iid, "cant", "1")
            _actualizar_lbl()
        elif col == "#6":  # editar cantidad
            val = simpledialog.askinteger(
                "Cantidad", "Cuantas etiquetas?",
                initialvalue=cantidades.get(iid, 1),
                minvalue=1, maxvalue=999, parent=d)
            if val:
                cantidades[iid] = val
                tree.set(iid, "sel",  "x")
                tree.set(iid, "cant", str(val))
            _actualizar_lbl()
        elif col == "#3":  # nombre generico para la etiqueta
            if iid not in cantidades:
                return  # solo tiene sentido para productos ya seleccionados
            actual = nombres_genericos.get(iid, todos_prods[iid]["descripcion"])
            val = simpledialog.askstring(
                "Nombre para la etiqueta",
                "Texto a mostrar en esta etiqueta (no cambia el producto,\n"
                "solo lo que se imprime — útil para agrupar variedades bajo\n"
                "un mismo precio, ej: \"Shampoo Sedal 300ml\"):",
                initialvalue=actual, parent=d)
            if val is None:
                return
            val = val.strip()
            if val and val != todos_prods[iid]["descripcion"]:
                nombres_genericos[iid] = val
                tree.set(iid, "desc", val + " ✎")
            else:
                nombres_genericos.pop(iid, None)
                tree.set(iid, "desc", todos_prods[iid]["descripcion"])

    tree.bind("<ButtonRelease-1>", _on_click)

    # Barra inferior
    bot = tk.Frame(d, bg=C.bg)
    bot.grid(row=3, column=0, sticky="ew", padx=12, pady=(0,12))

    lbl_sel = lbl(bot, "Ninguno seleccionado", variante="suave")
    lbl_sel.pack(side="left")

    def _actualizar_lbl():
        n = len(cantidades)
        tot = sum(cantidades.values())
        if n:
            lbl_sel.config(
                text=f"{n} producto{'s' if n>1 else ''} — {tot} etiqueta{'s' if tot>1 else ''}")
        else:
            lbl_sel.config(text="Ninguno seleccionado")

    def _sel_todo():
        for iid in tree.get_children():
            cantidades[iid] = cantidades.get(iid, 1)
            tree.set(iid, "sel",  "x")
            tree.set(iid, "cant", str(cantidades[iid]))
        _actualizar_lbl()

    def _desel_todo():
        cantidades.clear()
        for iid in tree.get_children():
            tree.set(iid, "sel",  "")
            tree.set(iid, "cant", "")
        _actualizar_lbl()

    btn(bot, "Todo", variante="neutro", comando=_sel_todo).pack(side="left", padx=(0,4))
    btn(bot, "Nada", variante="neutro", comando=_desel_todo).pack(side="left")

    def generar():
        if not cantidades:
            messagebox.showinfo("Atencion",
                "Selecciona al menos un producto.", parent=d)
            return
        # Expandir según cantidades
        prods_exp = []
        for cod, cant in cantidades.items():
            p = todos_prods.get(cod)
            if p:
                if cod in nombres_genericos:
                    p = dict(p)  # copia — no tocar el producto real en memoria
                    p["nombre_generico"] = nombres_genericos[cod]
                for _ in range(cant):
                    prods_exp.append(p)

        ruta = generar_pdf_etiquetas(prods_exp)
        if ruta:
            if sys.platform == "win32":
                os.startfile(ruta)
            messagebox.showinfo("Listo",
                f"PDF generado y abierto.\n{ruta}", parent=d)
            d.destroy()
        else:
            messagebox.showerror("Error",
                "No se pudo generar el PDF.\n"
                "Instala reportlab: pip install reportlab", parent=d)

    btn(bot, "Generar PDF", variante="exito",
        comando=generar).pack(side="right")
    btn(bot, "Cancelar", variante="neutro",
        comando=d.destroy).pack(side="right", padx=(0,8))

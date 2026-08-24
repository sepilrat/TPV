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

def _get_precios_producto(producto_id: int, precio_base: float,
                          recargo: float = 0.0) -> list[dict]:
    """
    Retorna lista de precios ordenados de menor a mayor precio unitario.
    Incluye precio base y todas las promos vigentes.
    Formato: [{"precio": float, "cantidad": int, "label": str}]

    recargo: monto fijo por unidad que se suma a TODOS los escalones
    (comision de un vendedor). Tiene que aplicarse tambien a las promos
    de precio fijo: si no, el escalon "x6: $3.900" saldria sin la
    comision y el vendedor terminaria vendiendo a perdida propia.
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
            "precio":   p["precio_unitario"] + recargo,
            "cantidad": p["cantidad_minima"],
            "label":    f"Llevando {p['cantidad_minima']}",
        })

    # Agregar precio base si no hay promo con cant=1 o es distinto
    cantidades_existentes = {p["cantidad"] for p in precios}
    if 1 not in cantidades_existentes:
        precios.append({
            "precio":   precio_base,   # ya viene con el recargo aplicado
            "cantidad": 1,
            "label":    "Precio unitario",
        })

    # Una sola linea por cantidad: si hay dos promos cargadas para la
    # misma cantidad, la etiqueta mostraba las dos con precios distintos.
    # Se queda la mas barata, que es la que aplica en la caja.
    mejor_por_cant = {}
    for _p in precios:
        _c = _p["cantidad"]
        if _c not in mejor_por_cant or _p["precio"] < mejor_por_cant[_c]["precio"]:
            mejor_por_cant[_c] = _p
    precios = list(mejor_por_cant.values())

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

    # Las etiquetas van PEGADAS en vertical: se cortan con guillotina o
    # tijera por la linea, y un espacio entre filas obliga a hacer dos
    # cortes por etiqueta en vez de uno. El separador horizontal si se
    # respeta (viene de las planchas autoadhesivas).
    # Con las etiquetas pegadas, cada linea sirve para las dos de al
    # lado: 1 corte vertical parte toda la hoja y 4 horizontales la
    # terminan. Con separacion hay que cortar dos veces por linea (una
    # de cada lado) y hacen falta 9. El separador solo tiene sentido en
    # planchas autoadhesivas troqueladas.
    if c.get("etiqueta_pegadas", True):
        espacio = 0
    ancho_paso = ancho + espacio
    alto_paso  = alto

    # Cuantas filas ENTRAN de verdad en la hoja. Antes se usaba el numero
    # de Config sin verificar: si alto x filas pasaba los 297 mm del A4,
    # la ultima fila salia cortada al medio y no habia forma de darse
    # cuenta hasta imprimir.
    margen_abajo = 8 * mm
    filas_que_entran = int((A4[1] - margen_y - margen_abajo) // alto_paso)
    if filas_que_entran < 1:
        filas_que_entran = 1
    if filas > filas_que_entran:
        logging.warning(
            f"Config pide {filas} filas de {alto/mm:.0f} mm, pero en A4 "
            f"entran {filas_que_entran}. Se usan {filas_que_entran} para "
            f"que no salgan cortadas.")
    filas = min(filas, filas_que_entran)

    # Margen lateral: centrado, pero nunca menor al minimo. Muchas
    # impresoras hogareñas no imprimen los ultimos milimetros del borde,
    # asi que con etiquetas anchas las guias de corte (y a veces el borde
    # de la etiqueta) se perdian. Si no entran, se achica la etiqueta.
    min_lateral = c.get("etiqueta_margen_lateral_mm", 12) * mm
    ocupado = cols * ancho + (cols - 1) * espacio
    disponible = A4[0] - 2 * min_lateral
    if ocupado > disponible:
        # Se reparte el faltante entre las columnas en vez de imprimir
        # pegado al borde
        ancho = (disponible - (cols - 1) * espacio) / cols
        ocupado = cols * ancho + (cols - 1) * espacio
        logging.warning(
            f"Las etiquetas no entran con {min_lateral/mm:.0f} mm de margen "
            f"lateral: se achican a {ancho/mm:.1f} mm de ancho.")
        ancho_paso = ancho + espacio
    margen_x = (A4[0] - ocupado) / 2

    if not ruta_salida:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        ruta_salida = os.path.join(
            tempfile.gettempdir(), f"etiquetas_{ts}.pdf")

    cv = canvas.Canvas(ruta_salida, pagesize=A4)
    pg_ancho, pg_alto = A4

    def _guias(n_filas_dibujadas):
        """Marcas de corte en los bordes: cortar a ojo sale torcido."""
        if not c.get("etiqueta_guias_corte", True):
            return
        cv.setStrokeColorRGB(0.75, 0.75, 0.75)
        cv.setLineWidth(0.4)
        largo = 4 * mm
        for col in range(cols + 1):
            x = margen_x + col * ancho_paso - (espacio / 2 if col and col < cols else 0)
            if col == cols:
                x = margen_x + (cols - 1) * ancho_paso + ancho
            y0 = pg_alto - margen_y
            y1 = y0 - n_filas_dibujadas * alto_paso
            cv.line(x, y0, x, y0 + largo)          # arriba
            cv.line(x, y1, x, y1 - largo)          # abajo
        for fila in range(n_filas_dibujadas + 1):
            y = pg_alto - margen_y - fila * alto_paso
            x0 = margen_x
            x1 = margen_x + (cols - 1) * ancho_paso + ancho
            cv.line(x0 - largo, y, x0, y)
            cv.line(x1, y, x1 + largo, y)

    idx = 0
    while idx < len(productos):
        dibujadas = 0
        for fila in range(filas):
            for col in range(cols):
                if idx >= len(productos):
                    break
                prod = productos[idx]
                idx += 1
                x = margen_x + col * ancho_paso
                y = pg_alto - margen_y - fila * alto_paso - alto
                _dibujar_etiqueta(cv, prod, x, y, ancho, alto)
                dibujadas = fila + 1

        _guias(dibujadas)
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

    # Texto de precio escrito a mano: el queso vale $20.000 el kilo pero
    # en la gondola conviene "$ 2.000 los 100g". No es otro producto ni
    # corresponde tocarle el precio real.
    if prod.get("_precio_texto"):
        precios = [{"precio": None, "cantidad": 1, "label": "",
                    "texto": prod["_precio_texto"]}]
    else:
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
    # Texto a mano si lo hay: se imprime tal cual, sin formatear
    precio_str = (mejor.get("texto")
                  or f"{sym} {mejor['precio']:,.2f} c/u")

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

def aprovechamiento_hoja(cfg_dict=None) -> dict:
    """Cuanto de la hoja se usa y que alto convendria.

    Con el alto por defecto quedaba casi un quinto de la hoja en blanco
    abajo: son etiquetas que se dejan de imprimir en cada tanda.
    """
    from config import cfg as _cfg
    c = cfg_dict or _cfg()
    A4_ALTO, A4_ANCHO = 297, 210
    margen_ab = 8

    alto = float(c.get("etiqueta_alto_mm", 45))
    ancho = float(c.get("etiqueta_ancho_mm", 95))
    cols = int(c.get("etiqueta_cols", 2))
    marg = float(c.get("etiqueta_margen_arriba_mm", 10))
    lat = float(c.get("etiqueta_margen_lateral_mm", 12))

    util = A4_ALTO - marg - margen_ab
    filas = max(1, int(util // alto))
    sobra = util - filas * alto

    # Alturas que aprovechan mejor. No se baja de 28 mm: abajo de eso el
    # precio deja de leerse desde el pasillo, que es para lo que sirve.
    opciones = []
    for f in range(filas, filas + 6):
        a = util / f
        if a < 28:
            break
        opciones.append({"filas": f, "alto": a, "por_hoja": f * cols})

    return {
        "filas_actuales": filas,
        "por_hoja": filas * cols,
        "sobra_mm": sobra,
        "pct_desperdiciado": (sobra + marg) / A4_ALTO * 100,
        "opciones": opciones,
        "cols_max": max(1, int((A4_ANCHO - 2 * lat) // ancho)),
        "ancho_max": (A4_ANCHO - 2 * lat) / cols,
    }


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

    # Filtro por categoria: las etiquetas de gondola se reponen por
    # sector (la gondola de limpieza, la de almacen), no de a todo el
    # catalogo junto.
    from repositorio import get_categorias
    lbl(bar, "Categoria:").pack(side="left", padx=(14, 6))
    _cats = [{"id": None, "nombre": "Todas"}] + list(get_categorias())
    var_cat = tk.StringVar(value="Todas")
    combo_cat = ttk.Combobox(bar, textvariable=var_cat, width=20,
                             state="readonly",
                             values=[c["nombre"] for c in _cats])
    combo_cat.pack(side="left")

    var_con_stock = tk.BooleanVar(value=False)
    tk.Checkbutton(bar, text="Solo con stock", variable=var_con_stock,
                   bg=C.bg, fg=C.texto, font=F.normal, selectcolor=C.bg,
                   activebackground=C.bg).pack(side="left", padx=(14, 0))

    # Filtro por lo que necesita etiqueta nueva: productos recién dados
    # de alta o con el precio cambiado. Es la razón habitual por la que
    # uno abre esta pantalla.
    lbl(bar, "Mostrar:").pack(side="left", padx=(14, 4))
    var_pend = tk.StringVar(value="Todos")
    combo_pend = ttk.Combobox(
        bar, textvariable=var_pend, width=22, state="readonly",
        values=("Todos", "Nuevos y con precio nuevo", "Solo nuevos",
                "Solo precio cambiado", "Nunca etiquetados"))
    combo_pend.pack(side="left")
    lbl(bar, "en los últimos").pack(side="left", padx=(8, 4))
    var_dias = tk.StringVar(value="7")
    ttk.Combobox(bar, textvariable=var_dias, width=5, state="readonly",
                 values=("1", "3", "7", "15", "30")).pack(side="left")
    lbl(bar, "días").pack(side="left", padx=(4, 0))

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
        cat_id = _cats[[c["nombre"] for c in _cats].index(var_cat.get())]["id"]

        # IDs que necesitan etiqueta nueva, si se pidió ese filtro
        ids_pend = None
        modo = var_pend.get()
        if modo != "Todos":
            from datetime import date, timedelta
            from repositorio import etiquetas_pendientes
            desde = (date.today()
                     - timedelta(days=int(var_dias.get() or 7))).isoformat()
            try:
                if modo == "Nunca etiquetados":
                    # Sin filtro de fecha: lo que importa es que nunca se
                    # imprimio, no cuando se cargo.
                    from repositorio import get_connection as _gc
                    with _gc() as _c:
                        ids_pend = {r[0] for r in _c.execute(
                            "SELECT id FROM productos "
                            "WHERE COALESCE(activo,1)=1 "
                            "AND etiqueta_impresa IS NULL")}
                else:
                    pend = etiquetas_pendientes(
                        desde, date.today().isoformat(),
                        incluir_nuevos=modo != "Solo precio cambiado",
                        incluir_cambios=modo != "Solo nuevos")
                    ids_pend = {x["producto_id"] for x in pend}
            except Exception:
                ids_pend = set()

        for p in get_productos(filtro=filtro, categoria_id=cat_id):
            if ids_pend is not None and p["id"] not in ids_pend:
                continue
            if var_con_stock.get() and (p.get("stock") or 0) <= 0:
                continue
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
    def _recargar(*_a):
        cargar(entry_buscar.get().strip())
        _actualizar_lbl()

    combo_cat.bind("<<ComboboxSelected>>", _recargar)
    combo_pend.bind("<<ComboboxSelected>>", _recargar)
    var_dias.trace_add("write", _recargar)
    var_con_stock.trace_add("write", _recargar)

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

    # Ediciones a mano: {producto_id: {"texto":…, "precio_texto":…}}
    ediciones = {}

    def _editar_etiqueta(event=None):
        """Cambia el texto y el precio de UNA etiqueta, sin tocar el
        producto: el queso sigue valiendo $20.000 el kilo en la caja,
        pero el cartel dice «$ 2.000 los 100g»."""
        sel = tree.selection() or ([tree.identify_row(event.y)] if event else [])
        iid = sel[0] if sel else None
        if not iid:
            return
        # El iid del árbol es el CODIGO del producto, no su id
        prod = todos_prods.get(iid)
        if not prod:
            return
        ed = ediciones.get(iid, {})

        top = tk.Toplevel(d)
        top.title("Editar etiqueta")
        top.configure(bg=C.superficie)
        top.grab_set()
        top.geometry("470x330")

        lbl(top, "Editar esta etiqueta", variante="titulo",
            bg=C.superficie).pack(anchor="w", padx=18, pady=(16, 2))
        lbl(top, f"Producto: {prod['descripcion'][:40]}   ·   "
                 f"$ {prod.get('precio_base') or 0:,.2f}",
            variante="suave", bg=C.superficie).pack(anchor="w", padx=18)
        lbl(top, "Cambia solo lo que se imprime. El precio del producto no "
                 "se toca.", variante="suave",
            bg=C.superficie).pack(anchor="w", padx=18, pady=(6, 0))

        lbl(top, "Texto de la etiqueta", variante="suave",
            bg=C.superficie).pack(anchor="w", padx=18, pady=(12, 2))
        v_txt = tk.StringVar(value=ed.get("texto") or prod["descripcion"])
        e_txt = tk.Entry(top, textvariable=v_txt, font=F.normal, bg=C.bg,
                         fg=C.texto, relief="solid", bd=1)
        e_txt.pack(fill="x", padx=18, ipady=5)

        lbl(top, "Precio a imprimir (ej: «$ 2.000 los 100g»)",
            variante="suave", bg=C.superficie).pack(anchor="w", padx=18,
                                                     pady=(10, 2))
        v_pre = tk.StringVar(value=ed.get("precio_texto") or "")
        tk.Entry(top, textvariable=v_pre, font=F.subtitulo, justify="center",
                 bg=C.bg, fg=C.texto, relief="solid", bd=1).pack(
            fill="x", padx=18, ipady=5)
        lbl(top, "Vacío = el precio normal del producto", variante="suave",
            bg=C.superficie).pack(anchor="w", padx=18, pady=(4, 0))

        def ok(_ev=None):
            cambios = {}
            if v_txt.get().strip() and v_txt.get().strip() != prod["descripcion"]:
                cambios["texto"] = v_txt.get().strip()
            if v_pre.get().strip():
                cambios["precio_texto"] = v_pre.get().strip()
            if cambios:
                ediciones[iid] = cambios
                # Se marca sola: si uno la editó, la quiere imprimir
                cantidades.setdefault(prod["codigo"], 1)
            else:
                ediciones.pop(iid, None)
            top.destroy()
            cargar(entry_buscar.get().strip())

        e_txt.bind("<Return>", ok)
        top.bind("<Escape>", lambda ev: top.destroy())
        fb = tk.Frame(top, bg=C.superficie)
        fb.pack(side="bottom", pady=14)
        btn(fb, "Guardar  (Enter)", variante="exito", comando=ok).pack(
            side="left", padx=4)
        btn(fb, "Quitar cambios", variante="neutro",
            comando=lambda: (ediciones.pop(iid, None), top.destroy(),
                             cargar(entry_buscar.get().strip()))).pack(
            side="left", padx=4)
        btn(fb, "Cancelar", variante="neutro",
            comando=top.destroy).pack(side="left", padx=4)
        e_txt.focus_set()
        e_txt.icursor("end")

    tree.bind("<ButtonRelease-1>", _on_click)
    tree.bind("<Double-1>", _editar_etiqueta)
    tree.tag_configure("editada", background=C.ok_flash)

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

    # Con filtros activos, "Todo" hacia pensar que marcaba el catalogo entero
    def _aprovechar():
        """Muestra cuanto se desperdicia y deja arreglarlo en el momento."""
        from config import set as cfg_set
        r = aprovechamiento_hoja()
        if r["pct_desperdiciado"] < 8:
            messagebox.showinfo(
                "Aprovechamiento",
                f"La hoja está bien aprovechada: entran {r['por_hoja']} "
                f"etiquetas y sobran {r['sobra_mm']:.0f} mm.", parent=d)
            return

        opciones = [o for o in r["opciones"] if o["por_hoja"] > r["por_hoja"]]
        if not opciones:
            messagebox.showinfo(
                "Aprovechamiento",
                f"Entran {r['por_hoja']} etiquetas y sobran "
                f"{r['sobra_mm']:.0f} mm, pero achicarlas más dejaría el "
                "precio ilegible desde el pasillo.", parent=d)
            return

        mejor = opciones[0]
        gana = mejor["por_hoja"] - r["por_hoja"]
        if messagebox.askyesno(
                "Se puede aprovechar mejor",
                f"Hoy entran {r['por_hoja']} etiquetas por hoja y quedan "
                f"{r['sobra_mm']:.0f} mm sin usar abajo "
                f"({r['pct_desperdiciado']:.0f}% de la hoja).\n\n"
                f"Bajando el alto de {cfg().get('etiqueta_alto_mm')} mm a "
                f"{mejor['alto']:.0f} mm entran {mejor['por_hoja']} "
                f"({gana} más por hoja).\n\n"
                "¿Lo aplico? Podés volver a cambiarlo en Config → "
                "Etiquetas de góndola.", parent=d):
            cfg_set("etiqueta_alto_mm", int(mejor["alto"]))
            cfg_set("etiqueta_filas", mejor["filas"])
            messagebox.showinfo(
                "Listo",
                f"Ahora entran {mejor['por_hoja']} etiquetas por hoja.\n\n"
                "Generá el PDF para verlo.", parent=d)

    btn(bot, "📐 Aprovechar la hoja", variante="neutro",
        comando=_aprovechar).pack(side="left", padx=(0,10))
    btn(bot, "Marcar los visibles", variante="neutro",
        comando=_sel_todo).pack(side="left", padx=(0,4))
    btn(bot, "Desmarcar todo", variante="neutro",
        comando=_desel_todo).pack(side="left")

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
                ed = ediciones.get(cod, {})
                if cod in nombres_genericos or ed:
                    p = dict(p)  # copia — no tocar el producto real en memoria
                    if cod in nombres_genericos:
                        p["nombre_generico"] = nombres_genericos[cod]
                    if ed.get("texto"):
                        p["nombre_generico"] = ed["texto"]
                    if ed.get("precio_texto"):
                        p["_precio_texto"] = ed["precio_texto"]
                for _ in range(cant):
                    prods_exp.append(p)

        # Queda registrado que ya tienen etiqueta: asi el filtro "nunca
        # etiquetados" sirve de verdad la proxima vez.
        try:
            from repositorio import marcar_etiquetas_impresas
            marcar_etiquetas_impresas({p["id"] for p in prods_exp})
        except Exception as _e:
            logging.debug(f"No se pudo marcar las etiquetas impresas: {_e}")

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

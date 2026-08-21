"""
lista_compacta.py — Lista de precios para pegar en la exhibidora.

Distinta de lista_precios.py, que es la lista de mostrador con fotos y
promos: esta es para que el cliente la lea desde el pasillo, parado
frente a la heladera de bebidas.

Criterio: que entren todas en una hoja, ajustando el tamaño de letra —
pero con un piso. Abajo de ese piso no se lee desde un metro, así que
conviene una segunda hoja antes que una lista ilegible.
"""

import logging
import os
import tkinter as tk
from datetime import datetime
from tkinter import ttk, messagebox

from styles import C, F, btn, lbl, tabla, toast
from config import cfg
from repositorio import (get_productos, get_categorias, guardar_lista,
                         get_listas_guardadas, get_lista, borrar_lista,
                         marcar_lista_usada, agregar_linea_manual)

# Piso de legibilidad: abajo de 11 pt no se lee a un metro. Si con eso
# no entra, se usan dos hojas.
FUENTE_MIN = 11
# Techo: arriba de 15 pt no se gana legibilidad, solo se desperdicia
# papel. Con pocos productos la lista queda arriba de la hoja y listo —
# estirar 5 productos a toda una pagina se ve mal y no sirve mas.
FUENTE_MAX = 15
# La fila apenas mas alta que la letra: el interlineado grande separa
# visualmente el nombre de su propio precio y obliga a barrer la hoja.
ALTO_FILA_MAX = 7.5 * 2.83465    # 7.5 mm en puntos


def generar_pdf_compacto(productos, titulo="", subtitulo="",
                         columnas=None, ruta=None,
                         por_categoria=False, manuales=None) -> str:
    """PDF de precios sin fotos.

    por_categoria: agrupa con un encabezado por rubro. Sirve cuando la
    lista mezcla cosas distintas; para una sola heladera de bebidas no
    hace falta.
    """
    # Las líneas escritas a mano se tratan como un producto más: entran
    # en el mismo orden y en el mismo agrupado por rubro.
    productos = [dict(p) for p in productos]
    for m in (manuales or []):
        productos.append({
            "descripcion": m["texto"],
            "precio_base": None,           # el precio va como texto
            "_precio_texto": m["precio_texto"],
            "categoria": m.get("categoria") or "Otros",
        })

    if por_categoria:
        # Se ordena por categoria y se insertan filas-titulo. El resto
        # del dibujo las trata como una fila mas, sin precio.
        grupos = {}
        for p in productos:
            grupos.setdefault(p.get("categoria") or "Otros", []).append(p)
        ordenados = []
        for cat in sorted(grupos):
            ordenados.append({"_titulo": cat})
            ordenados.extend(sorted(grupos[cat],
                                    key=lambda x: x["descripcion"]))
        productos = ordenados

    return _generar_pdf(productos, titulo, subtitulo, columnas, ruta,
                        cortar_por_titulo=por_categoria)


# Ancho mínimo de columna. Con menos, los nombres se recortan tanto que
# dos productos distintos quedan iguales en el papel y parece que faltan.
ANCHO_COL_MIN = 78 * 2.83465     # 78 mm en puntos


def _generar_pdf(productos, titulo="", subtitulo="",
                 columnas=None, ruta=None, cortar_por_titulo=False) -> str:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas as rl_canvas

    c = cfg()
    if not ruta:
        carpeta = c.get("carpeta_salida") or os.path.expanduser("~/Desktop")
        os.makedirs(carpeta, exist_ok=True)
        ruta = os.path.join(
            carpeta, f"precios_{datetime.now():%Y%m%d_%H%M}.pdf")

    ancho_pag, alto_pag = A4
    margen = 12 * mm
    ancho_util = ancho_pag - 2 * margen

    # Espacio del encabezado y el pie
    alto_cab = 30 * mm if titulo else 14 * mm
    alto_pie = 8 * mm
    alto_util = alto_pag - alto_cab - alto_pie - margen

    n = len(productos)
    if not n:
        raise ValueError("No hay productos seleccionados.")

    # Se busca la combinación más grande que entre en UNA hoja. Si
    # ninguna entra respetando el piso de legibilidad, se reparte en
    # varias hojas con la fuente mínima.
    # Se elige de afuera hacia adentro: primero cuantas columnas, y con
    # eso cuantas filas entran de verdad en la hoja. Antes se calculaba
    # al reves (filas = todos los productos) y al topear el alto de fila
    # el resultado decia que entraban 231 en una hoja.
    # Cuántas columnas caben sin que los nombres se vuelvan ilegibles
    cols_max = max(1, int(ancho_util // ANCHO_COL_MIN))
    mejor = None
    for cols in ([columnas] if columnas else range(1, cols_max + 1)):
        # Alto de fila que haria entrar TODO en una hoja con esas columnas
        filas_necesarias = -(-n // cols)
        alto_ideal = alto_util / filas_necesarias
        # Nunca mas alto de lo necesario ni mas chico que lo legible
        alto_fila = min(alto_ideal, ALTO_FILA_MAX)
        fuente = min(FUENTE_MAX, alto_fila * 0.62)
        if fuente < FUENTE_MIN:
            continue                       # con estas columnas no se lee
        filas_por_col = max(1, int(alto_util // alto_fila))
        entra_todo = filas_por_col * cols >= n
        cand = {"cols": cols, "fuente": fuente, "alto_fila": alto_fila,
                "filas": filas_por_col, "entra_todo": entra_todo,
                "hojas": -(-n // (filas_por_col * cols))}
        # Primero se busca que entre en una hoja; entre las que entran,
        # gana la de menos columnas (se lee mejor de lejos).
        if mejor is None:
            mejor = cand
        elif cand["hojas"] < mejor["hojas"]:
            mejor = cand
        elif cand["hojas"] == mejor["hojas"] and cand["cols"] < mejor["cols"]:
            mejor = cand

    if mejor is None:
        # No entra con letra legible: fuente minima y las hojas que hagan
        # falta, pero SIN pasarse del ancho minimo de columna — recortar
        # los nombres hace que dos productos distintos queden iguales.
        cols = columnas or cols_max
        alto_fila = FUENTE_MIN / 0.62
        filas_por_col = max(1, int(alto_util // alto_fila))
        mejor = {"cols": cols, "fuente": FUENTE_MIN, "alto_fila": alto_fila,
                 "filas": filas_por_col,
                 "hojas": -(-n // (filas_por_col * cols))}

    if mejor.get("hojas", 1) > 1:
        logging.info(
            f"Lista compacta: {n} productos en {mejor['hojas']} hoja(s) "
            f"con letra de {mejor['fuente']:.0f} pt.")

    cols, fuente = mejor["cols"], mejor["fuente"]
    alto_fila, filas_por_col = mejor["alto_fila"], mejor["filas"]
    por_hoja = cols * filas_por_col
    ancho_col = ancho_util / cols

    cv = rl_canvas.Canvas(ruta, pagesize=A4)
    idx = 0
    pagina = 0
    while idx < n:
        pagina += 1
        y_tope = alto_pag - margen

        if titulo:
            cv.setFillColorRGB(0.08, 0.09, 0.06)
            cv.rect(margen, y_tope - 16 * mm, ancho_util, 16 * mm, fill=1, stroke=0)
            cv.setFillColorRGB(1, 1, 1)
            cv.setFont("Helvetica-Bold", 15)
            cv.drawString(margen + 6 * mm, y_tope - 10 * mm, titulo[:46])
            if subtitulo:
                cv.setFont("Helvetica", 9)
                cv.drawRightString(margen + ancho_util - 6 * mm,
                                   y_tope - 10 * mm, subtitulo[:40])

        y0 = alto_pag - alto_cab
        for col in range(cols):
            x = margen + col * ancho_col
            for fila in range(filas_por_col):
                if idx >= n:
                    break

                # Un encabezado de rubro no puede quedar solo al pie de
                # la columna, ni el rubro partirse dejando dos productos
                # arriba y el resto en la columna siguiente.
                if (cortar_por_titulo and productos[idx].get("_titulo")
                        and fila > filas_por_col - 3
                        and col < cols - 1):
                    break
                p = productos[idx]
                idx += 1
                y = y0 - fila * alto_fila

                # Fila de encabezado de categoría
                if p.get("_titulo"):
                    cv.setFillColorRGB(0.85, 0.87, 0.83)
                    cv.rect(x, y - alto_fila, ancho_col - 4 * mm, alto_fila,
                            fill=1, stroke=0)
                    cv.setFillColorRGB(0.11, 0.11, 0.09)
                    cv.setFont("Helvetica-Bold", max(8, fuente * 0.8))
                    cv.drawString(x + 3 * mm,
                                  y - alto_fila + alto_fila * 0.32,
                                  p["_titulo"][:30].upper())
                    continue

                # Fondo alternado: guía la vista en listas largas
                if fila % 2 == 0:
                    cv.setFillColorRGB(0.96, 0.96, 0.94)
                    cv.rect(x, y - alto_fila, ancho_col - 4 * mm, alto_fila,
                            fill=1, stroke=0)

                cv.setFillColorRGB(0.11, 0.11, 0.09)
                precio_txt = (p.get("_precio_texto")
                              or f"$ {p['precio_base']:,.0f}")
                cv.setFont("Helvetica-Bold", fuente)
                ancho_precio = cv.stringWidth(precio_txt, "Helvetica-Bold", fuente)

                # El nombre se recorta a lo que sobra: el precio nunca se
                # pisa ni se corta, es lo que el cliente viene a leer.
                disponible = ancho_col - ancho_precio - 12 * mm
                nombre = p["descripcion"]
                cv.setFont("Helvetica", fuente)
                if cv.stringWidth(nombre, "Helvetica", fuente) > disponible:
                    # Con "…" queda claro que el nombre sigue, en vez de
                    # parecer otro producto con el mismo nombre corto.
                    while (cv.stringWidth(nombre + "…", "Helvetica", fuente)
                           > disponible and len(nombre) > 4):
                        nombre = nombre[:-1]
                    nombre += "…"

                base = y - alto_fila + (alto_fila - fuente * 0.35) / 2
                cv.drawString(x + 3 * mm, base, nombre)
                cv.setFont("Helvetica-Bold", fuente)
                cv.drawRightString(x + ancho_col - 6 * mm, base, precio_txt)

        cv.setFont("Helvetica", 7)
        cv.setFillColorRGB(0.45, 0.45, 0.42)
        pie = f"Actualizado {datetime.now():%d/%m/%Y}"
        if n > por_hoja:
            pie += f"   ·   hoja {pagina} de {-(-n // por_hoja)}"
        cv.drawString(margen, margen - 2 * mm, pie)

        if idx < n:
            cv.showPage()

    cv.save()
    return ruta


def _pedir_nombre(parent, sugerido=""):
    """Nombre de la lista. Con uno existente, la pisa."""
    d = tk.Toplevel(parent)
    d.title("Guardar lista")
    d.configure(bg=C.superficie)
    d.grab_set()
    d.geometry("420x190")
    lbl(d, "¿Cómo se llama esta lista?", variante="titulo",
        bg=C.superficie).pack(anchor="w", padx=18, pady=(16, 2))
    lbl(d, "Ej: «Heladera bebidas», «Góndola limpieza»", variante="suave",
        bg=C.superficie).pack(anchor="w", padx=18)
    v = tk.StringVar(value=sugerido)
    e = tk.Entry(d, textvariable=v, font=F.normal, bg=C.bg, fg=C.texto,
                 relief="solid", bd=1)
    e.pack(fill="x", padx=18, ipady=5, pady=(12, 0))
    e.focus_set()
    e.select_range(0, "end")
    res = [None]

    def ok(_ev=None):
        if v.get().strip():
            res[0] = v.get().strip()
            d.destroy()

    e.bind("<Return>", ok)
    d.bind("<Escape>", lambda ev: d.destroy())
    pie = tk.Frame(d, bg=C.superficie)
    pie.pack(side="bottom", pady=14)
    btn(pie, "Guardar  (Enter)", variante="exito", comando=ok).pack(
        side="left", padx=4)
    btn(pie, "Cancelar", variante="neutro", comando=d.destroy).pack(
        side="left", padx=4)
    parent.wait_window(d)
    return res[0]


def abrir_selector_lista_compacta(parent):
    """Elegir productos y generar la lista para la exhibidora."""
    d = tk.Toplevel(parent)
    d.title("Lista compacta para exhibidora")
    d.configure(bg=C.superficie)
    d.grab_set()
    w, h = 760, min(660, d.winfo_screenheight() - 90)
    sw, sh = d.winfo_screenwidth(), d.winfo_screenheight()
    d.geometry(f"{w}x{h}+{(sw-w)//2}+{max(0,(sh-h)//2)}")

    lbl(d, "Lista compacta", variante="titulo",
        bg=C.superficie).pack(anchor="w", padx=18, pady=(16, 2))
    lbl(d, "Sin fotos, letra grande, para pegar en la heladera o la "
           "góndola. El tamaño se ajusta solo para que entren en una hoja.",
        variante="suave", bg=C.superficie).pack(anchor="w", padx=18)

    # El pie va primero y anclado abajo, para que la tabla no lo empuje
    pie = tk.Frame(d, bg=C.superficie)
    pie.pack(side="bottom", fill="x", pady=12)

    # Listas guardadas: la de la heladera es siempre la misma, lo que
    # cambia son los precios. Se guardan los productos, no los precios.
    f_lst = tk.Frame(d, bg=C.acento, padx=12, pady=8)
    f_lst.pack(fill="x", padx=18, pady=(12, 0))
    lbl(f_lst, "Lista guardada:", variante="suave",
        bg=C.acento).pack(side="left")
    v_lista = tk.StringVar(value="— nueva —")
    cb_lista = ttk.Combobox(f_lst, textvariable=v_lista, width=26,
                            state="readonly")
    cb_lista.pack(side="left", padx=6)

    bar = tk.Frame(d, bg=C.superficie)
    bar.pack(fill="x", padx=18, pady=(12, 6))
    lbl(bar, "Título:", variante="suave", bg=C.superficie).pack(side="left")
    v_titulo = tk.StringVar(value="BEBIDAS")
    tk.Entry(bar, textvariable=v_titulo, width=22, font=F.normal, bg=C.bg,
             fg=C.texto, relief="solid", bd=1).pack(side="left", padx=6)

    lbl(bar, "Categoría:", variante="suave", bg=C.superficie).pack(
        side="left", padx=(12, 4))
    cats = [{"id": None, "nombre": "Todas"}] + list(get_categorias())
    v_cat = tk.StringVar(value="Todas")
    cb = ttk.Combobox(bar, textvariable=v_cat, width=18, state="readonly",
                      values=[c["nombre"] for c in cats])
    cb.pack(side="left")

    v_stock = tk.BooleanVar(value=True)
    tk.Checkbutton(bar, text="Solo con stock", variable=v_stock,
                   bg=C.superficie, fg=C.texto, font=F.normal,
                   selectcolor=C.superficie,
                   activebackground=C.superficie).pack(side="left", padx=12)

    # Viene tildado: agrupar por rubro es lo que sirve en una lista
    # general, y con una sola categoría no molesta (queda un solo título).
    v_porcat = tk.BooleanVar(value=True)
    tk.Checkbutton(bar, text="Agrupar por categoría", variable=v_porcat,
                   bg=C.superficie, fg=C.texto, font=("Segoe UI", 10, "bold"),
                   selectcolor=C.superficie,
                   activebackground=C.superficie).pack(side="left", padx=(12, 0))

    bar2 = tk.Frame(d, bg=C.superficie)
    bar2.pack(fill="x", padx=18, pady=(0, 6))
    lbl(bar2, "Buscar:", variante="suave", bg=C.superficie).pack(side="left")
    v_busq = tk.StringVar()
    e_b = tk.Entry(bar2, textvariable=v_busq, width=24, font=F.normal,
                   bg=C.bg, fg=C.texto, relief="solid", bd=1)
    e_b.pack(side="left", padx=6)

    COLS = [("sel", "", 34, "center"), ("desc", "Producto", 330, "w"),
            ("cat", "Categoría", 150, "w"), ("precio", "Precio", 110, "e")]
    frame_t, tree = tabla(d, COLS, altura=13)
    frame_t.pack(fill="both", expand=True, padx=18)

    # marcados guarda ids; elegidos_dict guarda el producto completo, para
    # no depender de que siga visible con el filtro puesto.
    filas, marcados = [], set()
    # Renglones escritos a mano: "$ 2.000 x 100g" no es un producto ni
    # corresponde tocarle el precio real al queso.
    manuales = []

    def cargar(*_a):
        cat_id = cats[[c["nombre"] for c in cats].index(v_cat.get())]["id"]
        filas.clear()
        filas.extend(get_productos(filtro=v_busq.get().strip(),
                                   categoria_id=cat_id))
        if v_stock.get():
            filas[:] = [p for p in filas if (p.get("stock") or 0) > 0]
        tree.delete(*tree.get_children())
        for i, p in enumerate(filas):
            tree.insert("", "end", iid=str(i), values=(
                "☑" if p["id"] in marcados else "☐",
                p["descripcion"][:48], p.get("categoria") or "—",
                f"$ {p['precio_base']:,.2f}"))
        _contar()

    def _contar():
        n = len(marcados) + len(manuales)
        visibles = sum(1 for p in filas if p["id"] in marcados)
        ocultos = n - visibles
        # Se anticipa cuántas hojas van a salir: evita la sorpresa de
        # mandar a imprimir cinco hojas sin querer.
        aviso = ""
        if n:
            if n <= 30:
                aviso = "   ·   entra en 1 hoja con letra grande"
            elif n <= 90:
                aviso = "   ·   entra en 1 hoja"
            else:
                aviso = f"   ·   van a salir varias hojas ({n} productos)"
        txt = f"{n} producto(s) seleccionados"
        if ocultos:
            # Sin esto uno cambia de categoría, ve la lista en blanco y
            # cree que perdió la selección anterior.
            txt += f" ({ocultos} de otras categorías)"
        if manuales:
            txt += f" + {len(manuales)} renglón(es) a mano"
        lbl_sel.config(text=txt + aviso)

    def _click(ev):
        iid = tree.identify_row(ev.y)
        if not iid:
            return
        p = filas[int(iid)]
        marcados.discard(p["id"]) if p["id"] in marcados else marcados.add(p["id"])
        tree.set(iid, "sel", "☑" if p["id"] in marcados else "☐")
        _contar()

    tree.bind("<Button-1>", _click)
    cb.bind("<<ComboboxSelected>>", cargar)
    e_b.bind("<KeyRelease>", cargar)
    v_stock.trace_add("write", cargar)

    lbl_sel = lbl(pie, "", variante="suave", bg=C.superficie)
    lbl_sel.pack(side="left", padx=18)

    def _marcar_visibles():
        for p in filas:
            marcados.add(p["id"])
        cargar()

    def _desmarcar():
        marcados.clear()
        cargar()

    def _renglon_manual():
        """Agrega un renglón con texto y precio libres."""
        top = tk.Toplevel(d)
        top.title("Renglón a mano")
        top.configure(bg=C.superficie)
        top.grab_set()
        top.geometry("470x330")

        lbl(top, "Renglón escrito a mano", variante="titulo",
            bg=C.superficie).pack(anchor="w", padx=18, pady=(16, 2))
        lbl(top, "Para lo que no sale del catálogo: «$ 2.000 x 100g», "
                 "«2x1 los martes», una promo.", variante="suave",
            bg=C.superficie).pack(anchor="w", padx=18)

        lbl(top, "Texto (lo que se lee a la izquierda)", variante="suave",
            bg=C.superficie).pack(anchor="w", padx=18, pady=(14, 2))
        v_txt = tk.StringVar()
        e_txt = tk.Entry(top, textvariable=v_txt, font=F.normal, bg=C.bg,
                         fg=C.texto, relief="solid", bd=1)
        e_txt.pack(fill="x", padx=18, ipady=5)
        e_txt.focus_set()

        lbl(top, "Precio (tal cual se imprime)", variante="suave",
            bg=C.superficie).pack(anchor="w", padx=18, pady=(10, 2))
        v_pre = tk.StringVar()
        tk.Entry(top, textvariable=v_pre, font=F.subtitulo, justify="center",
                 bg=C.bg, fg=C.texto, relief="solid", bd=1).pack(
            fill="x", padx=18, ipady=5)

        lbl(top, "Categoría (para agruparlo)", variante="suave",
            bg=C.superficie).pack(anchor="w", padx=18, pady=(10, 2))
        v_c = tk.StringVar(value=v_cat.get() if v_cat.get() != "Todas" else "")
        ttk.Combobox(top, textvariable=v_c, state="normal",
                     values=[c["nombre"] for c in cats
                             if c["nombre"] != "Todas"]).pack(fill="x", padx=18)

        def ok(_ev=None):
            if not v_txt.get().strip() or not v_pre.get().strip():
                messagebox.showwarning("Renglón", "Completá el texto y el "
                                                  "precio.", parent=top)
                return
            manuales.append({"texto": v_txt.get().strip(),
                             "precio_texto": v_pre.get().strip(),
                             "categoria": v_c.get().strip() or None})
            top.destroy()
            _contar()
            toast(parent, f"Renglón agregado: {v_txt.get().strip()[:24]}")

        top.bind("<Return>", ok)
        top.bind("<Escape>", lambda ev: top.destroy())
        fb = tk.Frame(top, bg=C.superficie)
        fb.pack(side="bottom", pady=14)
        btn(fb, "Agregar  (Enter)", variante="exito", comando=ok).pack(
            side="left", padx=4)
        btn(fb, "Ver los agregados", variante="neutro",
            comando=lambda: _ver_manuales(top)).pack(side="left", padx=4)
        btn(fb, "Cerrar", variante="neutro", comando=top.destroy).pack(
            side="left", padx=4)

    def _ver_manuales(padre):
        if not manuales:
            messagebox.showinfo("Renglones", "Todavía no agregaste ninguno.",
                                parent=padre)
            return
        txt = "\n".join(f"  · {m['texto']}   →   {m['precio_texto']}"
                         for m in manuales)
        if messagebox.askyesno(
                "Renglones a mano",
                f"{len(manuales)} renglón(es):\n\n{txt}\n\n"
                "¿Los borro todos?", parent=padre):
            manuales.clear()
            _contar()

    def _generar():
        # Se buscan en TODO el catalogo, no en lo que dejo el filtro
        # actual: con el "or" anterior, si quedaba alguno visible se
        # perdian todos los marcados en otras categorias.
        elegidos = [p for p in get_productos(solo_activos=False)
                    if p["id"] in marcados]
        if not elegidos and not manuales:
            messagebox.showinfo("Lista compacta",
                                "Marcá al menos un producto.", parent=d)
            return
        # Se ordena por categoría y nombre: si después se agrupa, el
        # orden ya viene bien; si no, queda alfabético dentro del rubro.
        elegidos.sort(key=lambda p: ((p.get("categoria") or "zzz").lower(),
                                     p["descripcion"].lower()))
        try:
            ruta = generar_pdf_compacto(
                elegidos, v_titulo.get().strip(), "",
                por_categoria=v_porcat.get(), manuales=manuales)
        except Exception as exc:
            messagebox.showerror("Lista compacta",
                                 f"No se pudo generar:\n{exc}", parent=d)
            return
        try:
            os.startfile(ruta)
        except Exception:
            messagebox.showinfo("Listo", f"PDF generado:\n{ruta}", parent=d)
        toast(parent, "Lista generada")

    btn(pie, "Generar PDF", variante="exito",
        comando=_generar).pack(side="right", padx=(6, 18))
    btn(pie, "Desmarcar todo", variante="neutro",
        comando=_desmarcar).pack(side="right", padx=4)
    btn(pie, "Marcar los visibles", variante="neutro",
        comando=_marcar_visibles).pack(side="right", padx=4)
    btn(pie, "✏️ Renglón a mano", variante="neutro",
        comando=lambda: _renglon_manual()).pack(side="right", padx=4)

    # ── Listas guardadas ──────────────────────────────────────────────

    _listas = []

    def _recargar_combo(seleccionar=None):
        _listas.clear()
        try:
            _listas.extend(get_listas_guardadas())
        except Exception:
            pass
        cb_lista.config(values=["— nueva —"] +
                        [f"{l['nombre']} ({l['items']})" for l in _listas])
        if seleccionar:
            for l in _listas:
                if l["id"] == seleccionar:
                    v_lista.set(f"{l['nombre']} ({l['items']})")
                    return
        v_lista.set("— nueva —")

    def _lista_actual():
        i = cb_lista.current()
        return _listas[i - 1] if i > 0 else None

    def _abrir_lista(*_a):
        l = _lista_actual()
        if not l:
            return
        datos = get_lista(l["id"])
        if not datos:
            return
        marcados.clear()
        marcados.update(p["id"] for p in datos["productos"])
        manuales.clear()
        manuales.extend({"texto": m["texto"],
                         "precio_texto": m["precio_texto"],
                         "categoria": m.get("categoria")}
                        for m in datos.get("manuales", []))
        if datos.get("titulo"):
            v_titulo.set(datos["titulo"])
        v_porcat.set(bool(datos.get("por_categoria", 1)))
        # Se muestra todo el catálogo: así se ve qué está marcado y se
        # puede agregar o sacar sin perder el resto de la selección.
        v_cat.set("Todas")
        v_stock.set(False)
        v_busq.set("")
        cargar()
        marcar_lista_usada(l["id"])
        faltan = len(datos["productos"]) - len(marcados)
        toast(parent, f"«{l['nombre']}»: {len(marcados)} producto(s)"
                      + (f" — {faltan} ya no existen" if faltan > 0 else ""))

    def _guardar_lista():
        if not marcados:
            messagebox.showinfo("Guardar lista",
                                "Marcá los productos antes de guardar.",
                                parent=d)
            return
        actual = _lista_actual()
        nombre = _pedir_nombre(d, actual["nombre"] if actual else
                               v_titulo.get().strip().title())
        if not nombre:
            return
        try:
            lid = guardar_lista(nombre, list(marcados),
                                v_titulo.get().strip(), v_porcat.get())
            # Los renglones a mano se guardan con la lista: son parte de
            # ella, no algo que haya que reescribir cada vez.
            for m in manuales:
                agregar_linea_manual(lid, m["texto"], m["precio_texto"],
                                     m.get("categoria") or "")
        except Exception as exc:
            messagebox.showerror("Guardar lista", str(exc), parent=d)
            return
        _recargar_combo(lid)
        toast(parent, f"Lista «{nombre}» guardada con {len(marcados)} "
                      f"producto(s)")

    def _borrar_lista():
        l = _lista_actual()
        if not l:
            messagebox.showinfo("Listas", "Elegí una lista guardada.",
                                parent=d)
            return
        if messagebox.askyesno("Borrar lista",
                               f"¿Borrar la lista «{l['nombre']}»?\n\n"
                               "Los productos no se tocan.", parent=d):
            borrar_lista(l["id"])
            _recargar_combo()

    cb_lista.bind("<<ComboboxSelected>>", _abrir_lista)
    btn(f_lst, "💾 Guardar", variante="exito",
        comando=_guardar_lista).pack(side="left", padx=4)
    btn(f_lst, "🗑", variante="neutro",
        comando=_borrar_lista).pack(side="left")
    lbl(f_lst, "Al abrir una lista se toman los precios de hoy.",
        variante="suave", bg=C.acento).pack(side="left", padx=12)

    _recargar_combo()
    cargar()
    parent.wait_window(d)

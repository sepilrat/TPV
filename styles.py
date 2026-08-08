"""
styles.py — Sistema de diseño centralizado TPV v2.0
Importar desde cualquier módulo: from styles import C, F, btn, lbl, card, tabla, toast
"""

import tkinter as tk
from tkinter import ttk


# ─────────────────────────────────────────────────────────────────────────────
# C — COLORES
# ─────────────────────────────────────────────────────────────────────────────
class C:
    bg          = "#F5F6FA"
    superficie  = "#FFFFFF"
    borde       = "#E2E5ED"
    primario    = "#2563EB"
    primario_h  = "#1D4ED8"
    exito       = "#16A34A"
    exito_h     = "#15803D"
    peligro     = "#DC2626"
    peligro_h   = "#B91C1C"
    advertencia = "#D97706"
    texto       = "#111827"
    texto_suave = "#6B7280"
    blanco      = "#FFFFFF"
    seleccion   = "#EFF6FF"
    acento      = "#DBEAFE"
    ok_flash    = "#DCFCE7"
    err_flash   = "#FEE2E2"
    # Sub-tabs de Productos — color distintivo
    productos_tab = "#F0F7FF"


# ─────────────────────────────────────────────────────────────────────────────
# F — FUENTES
# ─────────────────────────────────────────────────────────────────────────────
class F:
    titulo    = ("Segoe UI", 13, "bold")
    subtitulo = ("Segoe UI", 11, "bold")
    normal    = ("Segoe UI", 10)
    pequeña   = ("Segoe UI", 9)
    mono      = ("Consolas", 10)
    total     = ("Segoe UI", 28, "bold")
    boton     = ("Segoe UI", 10, "bold")
    # Datos en tabla: más grande y bold para mejor legibilidad
    tabla_dato    = ("Segoe UI", 10, "bold")
    tabla_header  = ("Segoe UI", 9)


# ─────────────────────────────────────────────────────────────────────────────
# S — APLICAR ESTILOS TTK
# ─────────────────────────────────────────────────────────────────────────────
def aplicar_tema():
    s = ttk.Style()
    s.theme_use("clam")

    s.configure(".", background=C.bg, foreground=C.texto,
                 font=F.normal, borderwidth=0)
    s.configure("TFrame", background=C.bg)

    # Notebook principal
    s.configure("TNotebook", background=C.bg, borderwidth=0,
                 tabmargins=[0, 0, 0, 0])
    s.configure("TNotebook.Tab", background=C.bg,
                 foreground=C.texto_suave, font=F.subtitulo,
                 padding=[20, 10], borderwidth=0)
    s.map("TNotebook.Tab",
          background=[("selected", C.superficie)],
          foreground=[("selected", C.primario)])

    # Notebook secundario (sub-tabs dentro de Productos)
    s.configure("Productos.TNotebook", background=C.productos_tab,
                 borderwidth=0, tabmargins=[0, 0, 0, 0])
    s.configure("Productos.TNotebook.Tab",
                 background=C.productos_tab,
                 foreground=C.texto_suave,
                 font=F.normal,
                 padding=[16, 8], borderwidth=0)
    s.map("Productos.TNotebook.Tab",
          background=[("selected", C.superficie)],
          foreground=[("selected", C.primario)])

    s.configure("TLabel", background=C.bg, foreground=C.texto, font=F.normal)

    s.configure("TEntry", fieldbackground=C.superficie, foreground=C.texto,
                bordercolor=C.borde, insertcolor=C.primario,
                font=F.normal, padding=6)
    s.map("TEntry", bordercolor=[("focus", C.primario)])

    # Treeview — datos legibles, separadores visibles, zebra
    s.configure("Treeview",
                background=C.superficie,
                foreground=C.texto,
                fieldbackground=C.superficie,
                rowheight=34,
                borderwidth=1,
                relief="solid",
                font=F.tabla_dato)
    s.configure("Treeview.Heading",
                background="#E8ECF4",
                foreground=C.texto,
                font=F.tabla_header,
                borderwidth=1,
                relief="ridge",
                padding=[8, 7])
    s.map("Treeview",
          background=[("selected", C.seleccion)],
          foreground=[("selected", C.primario)])

    # Variante con fila más alta, para tablas con miniatura de foto
    # (con_iconos=True en tabla()) — si no, la imagen queda recortada.
    s.configure("ConFotos.Treeview",
                background=C.superficie,
                foreground=C.texto,
                fieldbackground=C.superficie,
                rowheight=56,
                borderwidth=1,
                relief="solid",
                font=F.tabla_dato)
    s.map("ConFotos.Treeview",
          background=[("selected", C.seleccion)],
          foreground=[("selected", C.primario)])

    # arrowsize=0 colapsaba la scrollbar ENTERA a 1px de ancho (en el tema
    # "clam", el grosor del trough/thumb depende de arrowsize, no solo el
    # tamaño de las flechas) — quedaba invisible e imposible de arrastrar.
    # Se define un layout sin flechas (para mantener el look limpio) pero
    # con arrowsize>0 para que el grosor real de la barra sea usable.
    s.layout("Vertical.TScrollbar", [
        ("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [
            ("Vertical.Scrollbar.thumb", {"sticky": "nswe"})
        ]})
    ])
    s.configure("TScrollbar", background=C.borde, troughcolor=C.bg,
                borderwidth=0, arrowsize=14)
    s.configure("TSeparator", background=C.borde)
    s.configure("TCombobox", fieldbackground=C.superficie,
                foreground=C.texto, arrowcolor=C.texto_suave, padding=6)

    # Los Combobox de ttk cambian su VALOR solo con pasar la rueda del
    # mouse por encima — comportamiento nativo de Windows, no algo que
    # pusimos nosotros. Es un problema real dentro de un panel con
    # scroll: al bajar para scrollear la pantalla, si el mouse pasa por
    # arriba de un combo (ej "Categoria"), el combo cambiaba de valor
    # solo, en vez de (o además de) scrollear. bind_class pisa el
    # binding nativo para TODOS los Combobox de la app de una — la
    # rueda ahora siempre scrollea el panel que lo contiene, nunca
    # cambia el valor.
    def _combo_rueda_scrollea_no_cambia(e):
        w = e.widget.master
        while w is not None:
            if isinstance(w, tk.Canvas):
                w.yview_scroll(int(-1 * (e.delta / 120)), "units")
                break
            w = w.master
        return "break"

    root = tk._default_root
    if root:
        root.bind_class("TCombobox", "<MouseWheel>", _combo_rueda_scrollea_no_cambia)


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

_BTN = {
    "primario": (C.primario,  C.primario_h, C.blanco),
    "exito":    (C.exito,     C.exito_h,    C.blanco),
    "peligro":  (C.peligro,   C.peligro_h,  C.blanco),
    "neutro":   (C.borde,     "#CDD0D8",    C.texto),
    "acento":   (C.acento,    C.seleccion,  C.primario),
}

def btn(parent, texto, variante="primario", comando=None, **kw):
    bg, hover, fg = _BTN.get(variante, _BTN["neutro"])
    b = tk.Button(parent, text=texto, font=F.boton, bg=bg, fg=fg,
                  relief="flat", cursor="hand2", padx=14, pady=8,
                  command=comando, **kw)
    b.bind("<Enter>", lambda e: b.config(bg=hover))
    b.bind("<Leave>", lambda e: b.config(bg=bg))
    return b


def lbl(parent, texto, variante="normal", **kw):
    cfg = {
        "normal":    dict(font=F.normal,    fg=C.texto,       bg=C.bg),
        "titulo":    dict(font=F.titulo,    fg=C.texto,       bg=C.bg),
        "subtitulo": dict(font=F.subtitulo, fg=C.texto,       bg=C.bg),
        "suave":     dict(font=F.pequeña,   fg=C.texto_suave, bg=C.bg),
        "total":     dict(font=F.total,     fg=C.primario,    bg=C.superficie),
        "badge":     dict(font=F.pequeña,   fg=C.primario,    bg=C.acento),
        "info":      dict(font=F.pequeña,   fg=C.blanco,      bg=C.primario),
    }.get(variante, {})
    cfg.update(kw)
    return tk.Label(parent, text=texto, **cfg)


def header_seccion(parent, titulo, descripcion, bg=None):
    """
    Encabezado de sección con título y descripción explicativa.
    Usar al inicio de cada módulo/tab para orientar al usuario.
    """
    bg = bg or C.bg
    f = tk.Frame(parent, bg=bg)
    tk.Label(f, text=titulo, font=F.titulo, bg=bg,
             fg=C.texto).pack(side="left", padx=(0, 12))
    tk.Label(f, text=descripcion, font=F.pequeña, bg=C.acento,
             fg=C.primario, padx=8, pady=3).pack(side="left")
    return f


def card(parent, **kw):
    return tk.Frame(parent, bg=C.superficie,
                    highlightbackground=C.borde,
                    highlightthickness=1, **kw)


def separador(parent, orient="horizontal", padx=0, pady=8):
    sep = ttk.Separator(parent, orient=orient)
    sep.pack(fill="x" if orient == "horizontal" else "y",
             padx=padx, pady=pady)
    return sep


def tabla(parent, columnas: list[tuple], altura=15, scroll_y=True, con_iconos=False):
    """
    Crea un Treeview listo para usar.
    columnas: lista de (id, header, ancho, anchor)
    anchor: 'w' para texto, 'e' para numeros, 'center' para estado
    con_iconos: True habilita la columna de icono (#0) para poder pasar
    image=... en tree.insert(...) — por ejemplo, miniaturas de producto.
    Retorna (frame, tree)
    """
    frame = card(parent)
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(0, weight=1)

    ids  = [c[0] for c in columnas]
    tree = ttk.Treeview(frame, columns=ids,
                        show=("tree headings" if con_iconos else "headings"),
                        selectmode="browse", height=altura,
                        style=("ConFotos.Treeview" if con_iconos else "Treeview"))
    if con_iconos:
        tree.column("#0", width=52, minwidth=52, stretch=False)

    for col_id, header, ancho, anchor in columnas:
        tree.heading(col_id, text=header, anchor="w")
        tree.column(col_id, width=ancho, minwidth=40, anchor=anchor)

    tree.grid(row=0, column=0, sticky="nsew")

    if scroll_y:
        sb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        sb.grid(row=0, column=1, sticky="ns")

    return frame, tree


def entry(parent, ancho=20, fuente=None, **kw):
    return tk.Entry(parent, width=ancho, font=fuente or F.normal,
                    bg=C.superficie, fg=C.texto,
                    insertbackground=C.primario,
                    relief="solid", bd=1, **kw)


def toast(parent, mensaje, error=False, duracion=2000):
    color = C.peligro if error else C.exito
    t = tk.Label(parent, text=f"  {mensaje}  ", font=F.normal,
                 bg=color, fg=C.blanco, padx=12, pady=8)
    t.place(relx=0.5, rely=0.95, anchor="center")
    parent.after(duracion, t.destroy)


def scrollable(parent, bg=None):
    """
    Frame con scrollbar vertical. Usar cuando el contenido puede
    exceder la altura de la pantalla (formularios, paneles laterales).
    Retorna (outer_frame, inner_frame) — inner_frame es donde se agrega contenido.
    """
    bg = bg or C.bg
    outer = tk.Frame(parent, bg=bg)
    outer.columnconfigure(0, weight=1)
    outer.rowconfigure(0, weight=1)

    canvas = tk.Canvas(outer, bg=bg, highlightthickness=0, borderwidth=0)
    sb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=sb.set)

    canvas.grid(row=0, column=0, sticky="nsew")
    sb.grid(row=0, column=1, sticky="ns")

    inner = tk.Frame(canvas, bg=bg)
    win_id = canvas.create_window((0, 0), window=inner, anchor="nw")

    def _on_inner_resize(e):
        canvas.configure(scrollregion=canvas.bbox("all"))
        canvas.itemconfig(win_id, width=canvas.winfo_width())

    def _on_canvas_resize(e):
        canvas.itemconfig(win_id, width=e.width)

    inner.bind("<Configure>", _on_inner_resize)
    canvas.bind("<Configure>", _on_canvas_resize)

    # Scroll con rueda del mouse.
    # Intento previo (bind/unbind en <Enter>/<Leave> del canvas) NO funciona:
    # el canvas está lleno de widgets hijos reales (Entry, Button, Frame), y
    # apenas el mouse pasa sobre cualquiera de ellos, técnicamente "sale" del
    # canvas y "entra" al hijo — <Leave> se dispara todo el tiempo y el bind
    # queda desactivado en la práctica.
    # Antes de eso, el código usaba canvas.bind_all() a secas — bind_all es
    # global y esta app crea varios scrollable() al iniciar (Config, Caja,
    # Stock, etc.), así que cada uno pisaba el bind del anterior.
    # Solución: bind_all con add="+" (se suman los handlers en vez de
    # reemplazarse) y cada handler chequea, subiendo por e.widget.master,
    # si el evento ocurrió dentro de SU propia jerarquía antes de scrollear.
    def _mousewheel(e):
        w = e.widget
        while w is not None:
            if w == canvas:
                canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
                return
            w = w.master

    canvas.bind_all("<MouseWheel>", _mousewheel, add="+")

    return outer, inner

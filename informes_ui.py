"""
informes_ui.py — Dashboard e informes TPV v2.0
"""

import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime, timedelta
from styles import (C, F, btn, lbl, card, tabla, toast,
                    header_seccion, scrollable)
from repositorio import (get_ventas_periodo, get_ventas_por_dia,
                         get_ventas_por_metodo, get_top_productos,
                         get_margen_por_categoria, get_vencimientos_proximos, get_rentabilidad_productos,
                         get_rentabilidad_lotes, get_resumen_stock_por_categoria)

# ─────────────────────────────────────────────────────────────────────────────
# Helpers DB
# ─────────────────────────────────────────────────────────────────────────────

def _fmt_cant(v):
    """Formatea cantidad: entera sin decimales, fraccionaria con hasta
    3 decimales (para productos vendidos por peso)."""
    v = float(v)
    if v == int(v):
        return str(int(v))
    return f"{v:.3f}".rstrip("0").rstrip(".")


COLS_TOP = [
    ("desc",   "Producto",    260, "w"),
    ("codigo", "Codigo",       90, "w"),
    ("cant",   "Und. vendidas",90, "e"),
    ("total",  "Total $",      90, "e"),
]

COLS_STOCK = [
    ("desc",   "Producto",   220, "w"),
    ("stock",  "Stock",       65, "e"),
    ("dia",    "Venta/día",   80, "e"),
    ("dura",   "Dura",        85, "e"),
    ("comprar","Comprar",     80, "e"),
]

COLS_VENCE = [
    ("desc",  "Producto",    260, "w"),
    ("vence", "Vencimiento",  90, "w"),
    ("stock", "Stock",        60, "e"),
]

COLS_CATSTOCK = [
    ("cat",     "Categoria",         180, "w"),
    ("cant",    "Productos",          90, "e"),
    ("stock",   "Stock (u.)",         90, "e"),
    ("costo",   "Valor a costo",     120, "e"),
    ("venta",   "Valor a venta",     120, "e"),
]

COLS_DIAS = [
    ("dia",   "Fecha",        100, "w"),
    ("cant",  "Ventas",        60, "e"),
    ("total", "Total $",       90, "e"),
]

COLS_METODO = [
    ("metodo", "Metodo",      110, "w"),
    ("cant",   "Ventas",       60, "e"),
    ("total",  "Total $",      90, "e"),
    ("pct",    "%",            50, "e"),
]

COLS_MARGEN = [
    ("cat",    "Categoria",   160, "w"),
    ("venta",  "Venta $",      90, "e"),
    ("costo",  "Costo $",      90, "e"),
    ("margen", "Margen $",     90, "e"),
    ("pct",    "Margen %",     70, "e"),
]


COLS_RENT_PROD = [
    ("desc",      "Producto",      220, "w"),
    ("categoria", "Categoria",     100, "w"),
    ("unidades",  "Unid.",          60, "e"),
    ("ingreso",   "Ingreso $",      90, "e"),
    ("costo",     "Costo $",        90, "e"),
    ("ganancia",  "Ganancia $",     90, "e"),
    ("margen_r",  "Real s/costo %", 100, "e"),
    ("margen_t",  "Teorico s/costo %", 115, "e"),
    ("brecha",    "Brecha",          80, "e"),
    ("margen_v",  "Real s/venta %",  100, "e"),
]

COLS_RENT_LOTE = [
    ("desc",      "Producto",      170, "w"),
    ("proveedor", "Proveedor",     100, "w"),
    ("ingreso_f", "Ingreso",        80, "w"),
    ("costo_u",   "Costo u.",       70, "e"),
    ("ingresadas","Ingresadas",      70, "e"),
    ("vendidas",  "Vendidas",        65, "e"),
    ("ajustado",  "Ajustado",        65, "e"),
    ("restantes", "Restantes",       65, "e"),
    ("ganancia",  "Ganancia $",      85, "e"),
    ("margen",    "Margen %",        70, "e"),
]

class InformesUI(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._build()
        self.refrescar()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build(self):
        # Panel de control del negocio: ventas, productos más vendidos,
        # márgenes por categoría, stock crítico y vencimientos próximos.
        header_seccion(self, "Informes y Dashboard",
            "Ventas, productos, margenes, stock y vencimientos").pack(
            fill="x", padx=12, pady=(8,4))

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=12, pady=12)

        tabs = [
            ("  Dashboard  ",   self._build_dashboard),
            ("  Ventas  ",      self._build_ventas),
            ("  Productos  ",   self._build_productos),
            ("  Stock  ",       self._build_stock),
            ("  Rentabilidad ", self._build_rentabilidad),
            ("  Cuando vendo ", self._build_cuando),
            ("  Se venden juntos ", self._build_juntos),
            ("  Cobranzas ", self._build_cobranzas),
        ]
        for nombre, builder in tabs:
            f = ttk.Frame(nb)
            nb.add(f, text=nombre)
            builder(f)
        nb.bind("<<NotebookTabChanged>>", self._on_tab_interno)

    # ── Filtro de fechas (compartido) ─────────────────────────────────────────

    def _filtro_fechas(self, parent, comando):
        """Barra de filtro de periodo reutilizable."""
        bar = tk.Frame(parent, bg=C.bg)

        hoy   = datetime.now()
        presets = [
            ("Hoy",         hoy.strftime("%Y-%m-%d"),
                            hoy.strftime("%Y-%m-%d")),
            ("Esta semana", (hoy - timedelta(days=hoy.weekday())).strftime("%Y-%m-%d"),
                            hoy.strftime("%Y-%m-%d")),
            ("Este mes",    hoy.strftime("%Y-%m-01"),
                            hoy.strftime("%Y-%m-%d")),
            ("Ultimos 30",  (hoy - timedelta(days=30)).strftime("%Y-%m-%d"),
                            hoy.strftime("%Y-%m-%d")),
            ("Ultimos 90",  (hoy - timedelta(days=90)).strftime("%Y-%m-%d"),
                            hoy.strftime("%Y-%m-%d")),
        ]

        lbl(bar, "Desde:").pack(side="left", padx=(0,4))
        entry_desde = tk.Entry(bar, width=11, font=F.normal, bg=C.superficie,
                                fg=C.texto, relief="solid", bd=1, justify="center")
        entry_desde.insert(0, hoy.strftime("%Y-%m-01"))
        entry_desde.pack(side="left", ipady=4)

        lbl(bar, "Hasta:").pack(side="left", padx=(10,4))
        entry_hasta = tk.Entry(bar, width=11, font=F.normal, bg=C.superficie,
                                fg=C.texto, relief="solid", bd=1, justify="center")
        entry_hasta.insert(0, hoy.strftime("%Y-%m-%d"))
        entry_hasta.pack(side="left", ipady=4)

        def aplicar():
            comando(entry_desde.get().strip(), entry_hasta.get().strip())

        btn(bar, "Aplicar", variante="primario", comando=aplicar).pack(side="left", padx=8)

        for label, desde, hasta in presets:
            def _cmd(d=desde, h=hasta):
                entry_desde.delete(0, "end"); entry_desde.insert(0, d)
                entry_hasta.delete(0, "end"); entry_hasta.insert(0, h)
                comando(d, h)
            btn(bar, label, variante="neutro", comando=_cmd).pack(side="left", padx=2)

        return bar, entry_desde, entry_hasta

    # ── Tab Dashboard ─────────────────────────────────────────────────────────

    def _build_dashboard(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)

        outer, s = scrollable(parent, bg=C.bg)
        outer.grid(row=0, column=0, sticky="nsew")
        s.columnconfigure(0, weight=1)
        s.columnconfigure(1, weight=1)

        # KPIs — fila superior
        self.frame_kpis = tk.Frame(s, bg=C.bg)
        self.frame_kpis.grid(row=0, column=0, columnspan=2,
                              sticky="ew", pady=(0,8))

        self.kpis = {}
        for i, (key, titulo) in enumerate([
            ("hoy_total",   "Ventas hoy"),
            ("hoy_cant",    "Transacciones hoy"),
            ("mes_total",   "Ventas este mes"),
            ("ticket_prom", "Ticket promedio"),
        ]):
            c = card(self.frame_kpis)
            c.pack(side="left", fill="both", expand=True, padx=(0 if i==0 else 8, 0))
            lbl(c, titulo, variante="suave", bg=C.superficie).pack(
                anchor="w", padx=16, pady=(14,2))
            val = tk.Label(c, text="—", font=("Segoe UI", 18, "bold"),
                           bg=C.superficie, fg=C.primario)
            val.pack(anchor="w", padx=16, pady=(0,14))
            self.kpis[key] = val

        # Segunda fila de KPIs — foto del valor de la mercadería en stock
        self.frame_kpis2 = tk.Frame(s, bg=C.bg)
        self.frame_kpis2.grid(row=1, column=0, columnspan=2,
                               sticky="ew", pady=(0,8))
        for i, (key, titulo, color) in enumerate([
            ("stock_productos", "Productos activos",        C.texto),
            ("stock_costo",     "Valor stock (a costo)",     C.texto),
            ("stock_venta",     "Valor stock (a venta)",     C.primario),
            ("stock_ganancia",  "Ganancia potencial (venta − costo)", C.exito),
        ]):
            c = card(self.frame_kpis2)
            c.pack(side="left", fill="both", expand=True, padx=(0 if i==0 else 8, 0))
            lbl(c, titulo, variante="suave", bg=C.superficie).pack(
                anchor="w", padx=16, pady=(14,2))
            val = tk.Label(c, text="—", font=("Segoe UI", 18, "bold"),
                           bg=C.superficie, fg=color)
            val.pack(anchor="w", padx=16, pady=(0,14))
            self.kpis[key] = val

        # Top productos — izquierda con etiqueta
        f_izq = tk.Frame(s, bg=C.bg)
        f_izq.grid(row=2, column=0, sticky="nsew", padx=(0,8))
        f_izq.columnconfigure(0, weight=1)
        f_izq.rowconfigure(1, weight=1)
        lbl(f_izq, "Productos mas vendidos este mes", variante="subtitulo",
            fg=C.primario).grid(row=0, column=0, sticky="w", pady=(0,4))
        frame_top, self.tree_dash_top = tabla(f_izq, COLS_TOP, altura=8)
        frame_top.grid(row=1, column=0, sticky="nsew")

        # Panel derecho — PanedWindow vertical para dividir stock y vencimientos
        der = ttk.PanedWindow(s, orient="vertical", height=380)
        der.grid(row=2, column=1, sticky="nsew")

        # Panel stock critico
        f_sc = tk.Frame(der, bg=C.bg)
        f_sc.columnconfigure(0, weight=1)
        f_sc.rowconfigure(1, weight=1)
        lbl(f_sc, "Se está por acabar", variante="subtitulo",
            fg=C.peligro).grid(row=0, column=0, sticky="w", pady=(0,4))
        frame_sc, self.tree_dash_critico = tabla(f_sc, COLS_STOCK, altura=6)
        frame_sc.grid(row=1, column=0, sticky="nsew")
        self.tree_dash_critico.tag_configure("critico", foreground=C.peligro)
        der.add(f_sc, weight=1)

        # Panel vencimientos
        f_vv = tk.Frame(der, bg=C.bg)
        f_vv.columnconfigure(0, weight=1)
        f_vv.rowconfigure(1, weight=1)
        lbl(f_vv, "Proximos vencimientos", variante="subtitulo",
            fg=C.advertencia).grid(row=0, column=0, sticky="w", pady=(4,4))
        frame_vv, self.tree_dash_vence = tabla(f_vv, COLS_VENCE, altura=6)
        frame_vv.grid(row=1, column=0, sticky="nsew")
        self.tree_dash_vence.tag_configure("urgente", foreground=C.peligro)
        der.add(f_vv, weight=1)

        # Productos y stock por categoria — fila completa abajo
        f_cat = tk.Frame(s, bg=C.bg)
        f_cat.grid(row=3, column=0, columnspan=2, sticky="nsew", pady=(8,0))
        f_cat.columnconfigure(0, weight=1)
        lbl(f_cat, "Productos y stock por categoria", variante="subtitulo",
            fg=C.primario).grid(row=0, column=0, sticky="w", pady=(0,4))
        frame_cat, self.tree_dash_cat = tabla(f_cat, COLS_CATSTOCK, altura=8)
        frame_cat.grid(row=1, column=0, sticky="nsew")
        self.tree_dash_cat.tag_configure("total", font=F.boton)

        btn(s, "Actualizar dashboard", variante="neutro",
            comando=self.refrescar).grid(row=4, column=0, columnspan=2,
                                          sticky="w", pady=(8,10))

    # ── Tab Ventas ────────────────────────────────────────────────────────────

    def _build_ventas(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(2, weight=1)

        bar, self.v_desde, self.v_hasta = self._filtro_fechas(
            parent, self._refrescar_ventas)
        bar.grid(row=0, column=0, sticky="ew", pady=(0,8))

        # Resumen
        self.frame_resumen_v = tk.Frame(parent, bg=C.bg)
        self.frame_resumen_v.grid(row=1, column=0, sticky="ew", pady=(0,8))

        self.resumen_kpis = {}
        for key, titulo in [("total","Total"), ("cant","Ventas"), ("prom","Ticket prom.")]:
            c = card(self.frame_resumen_v)
            c.pack(side="left", padx=(0,8))
            lbl(c, titulo, variante="suave", bg=C.superficie).pack(
                anchor="w", padx=14, pady=(10,2))
            val = tk.Label(c, text="—", font=F.subtitulo,
                           bg=C.superficie, fg=C.primario)
            val.pack(anchor="w", padx=14, pady=(0,10))
            self.resumen_kpis[key] = val

        # Tabs internos: por dia / por método / por categoría
        nb2 = ttk.Notebook(parent)
        nb2.grid(row=2, column=0, sticky="nsew")

        f_dias   = ttk.Frame(nb2)
        f_metodo = ttk.Frame(nb2)
        f_margen = ttk.Frame(nb2)
        nb2.add(f_dias,   text="  Por dia  ")
        nb2.add(f_metodo, text="  Por metodo de pago  ")
        nb2.add(f_margen, text="  Margen por categoria  ")

        for f, attr, cols in [
            (f_dias,   "tree_dias",   COLS_DIAS),
            (f_metodo, "tree_metodo", COLS_METODO),
            (f_margen, "tree_margen", COLS_MARGEN),
        ]:
            f.columnconfigure(0, weight=1)
            f.rowconfigure(0, weight=1)
            frame_t, tree = tabla(f, cols)
            frame_t.grid(row=0, column=0, sticky="nsew")
            setattr(self, attr, tree)

    # ── Tab Productos ─────────────────────────────────────────────────────────

    def _build_productos(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)

        bar, self.p_desde, self.p_hasta = self._filtro_fechas(
            parent, self._refrescar_top)
        bar.grid(row=0, column=0, sticky="ew", pady=(0,8))

        frame_t, self.tree_top = tabla(parent, COLS_TOP)
        frame_t.grid(row=1, column=0, sticky="nsew")

    # ── Tab Stock ─────────────────────────────────────────────────────────────

    def _build_stock(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=1)
        parent.rowconfigure(1, weight=1)

        # Antes era "< 5 unidades" para todo el catálogo: 5 de algo que
        # sale 20 por día es una urgencia, y 5 de algo que sale uno por
        # mes es sobrestock. Ahora mide cuántos DÍAS dura.
        lbl(parent, "Se está por acabar (por velocidad de venta)",
            variante="subtitulo",
            fg=C.peligro).grid(row=0, column=0, sticky="w", pady=(0,4))
        self.lbl_stock_modo = lbl(parent, "", variante="suave")
        self.lbl_stock_modo.grid(row=3, column=0, sticky="w", pady=(4, 0))
        lbl(parent, "Vencimientos proximos (30 dias)", variante="subtitulo",
            fg=C.advertencia).grid(row=0, column=1, sticky="w", pady=(0,4), padx=(8,0))

        frame_sc, self.tree_stock_critico = tabla(parent, COLS_STOCK)
        frame_sc.grid(row=1, column=0, sticky="nsew", padx=(0,8))
        # Silenciar de a uno con 64 productos en la lista es media hora:
        # se marcan varios con Ctrl o Shift, o todos con Ctrl+A.
        self.tree_stock_critico.configure(selectmode="extended")
        self.tree_stock_critico.bind("<Control-a>", self._sel_todo_stock)
        self.tree_stock_critico.bind("<Control-A>", self._sel_todo_stock)
        self.tree_stock_critico.tag_configure("critico", foreground=C.peligro)
        self.tree_stock_critico.tag_configure("sindatos",
                                              foreground=C.texto_suave)

        frame_vv, self.tree_stock_vence = tabla(parent, COLS_VENCE)
        frame_vv.grid(row=1, column=1, sticky="nsew")
        self.tree_stock_vence.tag_configure("urgente", foreground=C.peligro)

        # Hay productos que siempre estan "bajos" porque se reponen a
        # diario: sin poder silenciarlos, el aviso se vuelve ruido y se
        # deja de mirar.
        f_acc = tk.Frame(parent, bg=C.bg)
        f_acc.grid(row=2, column=0, sticky="w", pady=(8, 0))
        btn(f_acc, "Actualizar", variante="neutro",
            comando=self._refrescar_stock).pack(side="left")
        btn(f_acc, "☑ Seleccionar todo", variante="neutro",
            comando=self._sel_todo_stock).pack(side="left", padx=6)
        btn(f_acc, "🔕  No avisar de estos", variante="neutro",
            comando=self._silenciar_stock).pack(side="left", padx=6)
        btn(parent, "📧 Enviar informe por email ahora", variante="primario",
            comando=self._enviar_informe_stock).grid(
            row=2, column=1, sticky="e", pady=(8,0))

    def _enviar_informe_stock(self):
        from impresion import enviar_informe_stock
        ok, msg = enviar_informe_stock()
        if ok:
            messagebox.showinfo("Informe de stock", msg, parent=self)
        else:
            messagebox.showwarning("Informe de stock", msg, parent=self)

    # ── Tab Rentabilidad ──────────────────────────────────────────────────────

    def _build_rentabilidad(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(2, weight=1)

        bar, self.r_desde, self.r_hasta = self._filtro_fechas(
            parent, self._refrescar_rentabilidad)
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        # KPIs rápidos
        self.frame_kpis_rent = tk.Frame(parent, bg=C.bg)
        self.frame_kpis_rent.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        self.kpis_rent = {}
        for key, titulo in [
            ("ganancia_total", "Ganancia total"),
            ("margen_prom",    "Margen promedio"),
            ("mejor_prod",     "Producto mas rentable"),
            ("peor_prod",      "Menor margen"),
            # La ganancia es de lo VENDIDO. Lo fiado todavia no entro al
            # cajon, y sin este dato uno cree que tiene plata que no tiene.
            ("cobrado",        "De eso, cobrado"),
        ]:
            c = card(self.frame_kpis_rent)
            c.pack(side="left", fill="both", expand=True, padx=(0, 8))
            lbl(c, titulo, variante="suave", bg=C.superficie).pack(
                anchor="w", padx=14, pady=(10,2))
            val = tk.Label(c, text="—", font=F.subtitulo,
                           bg=C.superficie, fg=C.primario)
            val.pack(anchor="w", padx=14, pady=(0,10))
            self.kpis_rent[key] = val

        # Sub-tabs: por producto / por lote
        nb = ttk.Notebook(parent)
        nb.grid(row=2, column=0, sticky="nsew")

        f_prod = ttk.Frame(nb)
        f_lote = ttk.Frame(nb)
        nb.add(f_prod, text="  Por producto  ")
        nb.add(f_lote, text="  Por lote  ")

        f_prod.columnconfigure(0, weight=1)
        f_prod.rowconfigure(0, weight=1)
        frame_p, self.tree_rent_prod = tabla(f_prod, COLS_RENT_PROD)
        frame_p.grid(row=0, column=0, sticky="nsew")
        # Doble clic: de que lotes salio lo vendido. Es la respuesta a
        # "corregi el costo y el informe sigue mostrando el viejo": por
        # FIFO la venta pudo salir de un lote anterior.
        self.tree_rent_prod.bind("<Double-1>",
                                 lambda e: self._ver_lotes_vendidos())
        self.tree_rent_prod.tag_configure("perdida", foreground=C.peligro)
        self.tree_rent_prod.tag_configure("bajo",    foreground=C.advertencia)

        f_lote.columnconfigure(0, weight=1)
        f_lote.rowconfigure(0, weight=1)
        frame_l, self.tree_rent_lote = tabla(f_lote, COLS_RENT_LOTE)
        frame_l.grid(row=0, column=0, sticky="nsew")
        self.tree_rent_lote.tag_configure("perdida", foreground=C.peligro)
        self.tree_rent_lote.tag_configure("sin_ventas", foreground=C.texto_suave)

    # ── Refrescar ─────────────────────────────────────────────────────────────

    def refrescar(self):
        self._refrescar_dashboard()
        self._refrescar_stock()

    def _rango_por_defecto(self):
        """Ultimos 30 dias: el periodo que mejor muestra un patron."""
        hoy = datetime.now()
        return ((hoy - timedelta(days=29)).strftime("%Y-%m-%d"),
                hoy.strftime("%Y-%m-%d"))

    def _on_tab_interno(self, event):
        """Refresca automáticamente al cambiar de tab interno."""
        tab = event.widget.tab(event.widget.select(), "text").strip()
        metodos = {
            "Dashboard":    self._refrescar_dashboard,
            "Ventas":       lambda: self._refrescar_ventas(
                                self.v_desde.get(), self.v_hasta.get()),
            "Productos":    lambda: self._refrescar_top(
                                self.p_desde.get(), self.p_hasta.get()),
            "Stock":        self._refrescar_stock,
            "Rentabilidad": lambda: self._refrescar_rentabilidad(
                                self.r_desde.get(), self.r_hasta.get()),
            "Cuando vendo": lambda: self._refrescar_cuando(
                                self.c_desde.get(), self.c_hasta.get()),
            "Se venden juntos": lambda: self._refrescar_juntos(
                                self.j_desde.get(), self.j_hasta.get()),
            "Cobranzas": lambda: self._refrescar_cobranzas(
                                self.cb_desde.get(), self.cb_hasta.get()),
        }
        fn = metodos.get(tab)
        if fn:
            self.after(50, fn)

    def _actualizar_cobrado(self, desde, hasta):
        """Cuánto de lo facturado entró de verdad."""
        from repositorio import ganancia_cobrada
        try:
            r = ganancia_cobrada(desde, hasta)
        except Exception:
            return
        w = self.kpis_rent.get("cobrado")
        if w is None:
            return
        if r["fiado"]:
            w.config(text=f"$ {r['cobrado']:,.2f}", fg=C.advertencia)
        else:
            w.config(text=f"$ {r['cobrado']:,.2f}", fg=C.exito)
        # El detalle va en el subtítulo de la tarjeta, si existe
        sub = getattr(self, "lbl_cobrado_det", None)
        if sub is not None:
            if r["fiado"]:
                sub.config(text=(f"quedan $ {r['fiado']:,.2f} fiados de este "
                                 f"período · deuda total "
                                 f"$ {r['por_cobrar_total']:,.2f}"))
            else:
                sub.config(text="todo cobrado en el período")

    def _ver_lotes_vendidos(self):
        """Muestra de qué lotes salió lo vendido de ese producto."""
        from repositorio import lotes_de_producto_vendidos, get_producto_completo
        sel = self.tree_rent_prod.selection()
        if not sel:
            return
        try:
            pid = int(sel[0])
        except ValueError:
            return
        prod = get_producto_completo(pid)
        lotes = lotes_de_producto_vendidos(pid, self.r_desde.get(),
                                           self.r_hasta.get())
        if not lotes:
            return

        d = tk.Toplevel(self)
        d.title("De qué lotes salió")
        d.configure(bg=C.superficie)
        d.grab_set()
        w, h = 560, 340
        sw, sh = d.winfo_screenwidth(), d.winfo_screenheight()
        d.geometry(f"{w}x{h}+{(sw-w)//2}+{max(0,(sh-h)//2)}")

        lbl(d, (prod or {}).get("descripcion", "")[:44], variante="titulo",
            bg=C.superficie).pack(anchor="w", padx=18, pady=(16, 2))
        lbl(d, "El costo del informe sale de estos lotes, no del costo "
               "actual del producto.", variante="suave",
            bg=C.superficie).pack(anchor="w", padx=18)

        cols = [("lote", "Lote", 80, "e"), ("ing", "Ingresó", 110, "w"),
                ("un", "Unidades", 90, "e"), ("costo", "Costo u.", 100, "e"),
                ("tot", "Costo total", 110, "e")]
        frame_t, tv = tabla(d, cols, altura=8)
        frame_t.pack(fill="both", expand=True, padx=18, pady=(10, 6))
        costo_act = float((prod or {}).get("costo_ultimo") or 0)
        tv.tag_configure("viejo", foreground=C.advertencia)
        for l in lotes:
            distinto = costo_act and abs(l["costo_unitario"] - costo_act) > 0.01
            tv.insert("", "end", tags=("viejo",) if distinto else (), values=(
                f"#{l['lote_id']}", (l["fecha_ingreso"] or "")[:10],
                f"{l['unidades']:g}", f"$ {l['costo_unitario']:,.2f}",
                f"$ {l['costo_total']:,.2f}"))

        distintos = [l for l in lotes
                     if costo_act and abs(l["costo_unitario"] - costo_act) > 0.01]
        if distintos:
            tk.Label(d, bg=C.acento, fg=C.texto, font=F.pequeña, wraplength=500,
                     justify="left", padx=14, pady=10, anchor="w",
                     text=(f"El producto hoy cuesta $ {costo_act:,.2f}, pero "
                           f"{len(distintos)} de estos lotes tienen otro costo. "
                           f"Si corregiste el costo hace poco, corregí también "
                           f"esos lotes desde Stock → Ver historial completo.")
                     ).pack(fill="x", padx=18)

        btn(d, "Cerrar", variante="neutro",
            comando=d.destroy).pack(side="bottom", pady=12)
        d.bind("<Escape>", lambda ev: d.destroy())

    def _refrescar_rentabilidad(self, desde=None, hasta=None):
        from datetime import datetime
        hoy = datetime.now().strftime("%Y-%m-%d")
        mes = datetime.now().strftime("%Y-%m-01")
        desde = desde or mes
        hasta = hasta or hoy

        # ── Por producto ───────────────────────────────────────────────────
        for r in self.tree_rent_prod.get_children():
            self.tree_rent_prod.delete(r)

        prods = get_rentabilidad_productos(desde, hasta)
        total_ganancia = 0
        margenes = []

        for p in prods:
            gan  = p["ganancia"] or 0
            mr   = p["margen_real_pct"] or 0
            mt   = p["margen_teorico_pct"] or 0
            total_ganancia += gan
            if p["ingreso_total"]: margenes.append(mr)

            mv = p.get("margen_venta_pct") or 0
            brecha = mr - mt if mt else 0
            tag = "perdida" if gan < 0 else ("bajo" if mr < 10 else "")
            self.tree_rent_prod.insert("", "end", iid=str(p["producto_id"]),
                                       values=(
                p["descripcion"],
                p["categoria"] or "—",
                _fmt_cant(p['unidades']),
                f"$ {p['ingreso_total']:,.2f}",
                f"$ {p['costo_total']:,.2f}",
                f"$ {gan:,.2f}",
                f"{mr:.1f}%",
                f"{mt:.1f}%",
                f"{brecha:+.1f} pts" if mt else "—",
                f"{mv:.1f}%",
            ), tags=(tag,) if tag else ())

        # KPIs
        margen_prom = sum(margenes)/len(margenes) if margenes else 0
        mejor = prods[0]["descripcion"][:20] if prods else "—"
        peor  = min(prods, key=lambda x: x["margen_real_pct"] or 0)["descripcion"][:20] if prods else "—"
        self.kpis_rent["ganancia_total"].config(text=f"$ {total_ganancia:,.2f}")
        self._actualizar_cobrado(desde, hasta)
        self.kpis_rent["margen_prom"].config(text=f"{margen_prom:.1f}%")
        self.kpis_rent["mejor_prod"].config(text=mejor)
        self.kpis_rent["peor_prod"].config(text=peor)

        # ── Por lote ───────────────────────────────────────────────────────
        for r in self.tree_rent_lote.get_children():
            self.tree_rent_lote.delete(r)

        for l in get_rentabilidad_lotes(desde, hasta):
            gan = l["ganancia_lote"] or 0
            tag = "perdida"   if gan < 0 else                   "sin_ventas" if l["unidades_vendidas"] == 0 else ""
            self.tree_rent_lote.insert("", "end", values=(
                l["descripcion"],
                f"Ajuste ({l['motivo_ajuste']})" if l.get("tipo") == "ajuste"
                    else (l["proveedor"] or "—"),
                l["fecha_ingreso"][:10] if l["fecha_ingreso"] else "—",
                f"$ {l['costo_unitario']:,.2f}",
                _fmt_cant(l['cantidad_ingresada']),
                _fmt_cant(l['unidades_vendidas']),
                _fmt_cant(l['cantidad_ajustada']) if l['cantidad_ajustada'] else "—",
                _fmt_cant(l['cantidad_disponible']),
                f"$ {gan:,.2f}",
                f"{l['margen_pct'] or 0:.1f}%",
            ), tags=(tag,) if tag else ())

    def _refrescar_dashboard(self):
        hoy  = datetime.now().strftime("%Y-%m-%d")
        mes  = datetime.now().strftime("%Y-%m-01")

        r_hoy = get_ventas_periodo(hoy, hoy)
        r_mes = get_ventas_periodo(mes, hoy)

        self.kpis["hoy_total"].config(  text=f"$ {r_hoy['total']:,.2f}")
        self.kpis["hoy_cant"].config(   text=str(r_hoy["cant"]))
        self.kpis["mes_total"].config(  text=f"$ {r_mes['total']:,.2f}")
        prom = r_mes["total"] / r_mes["cant"] if r_mes["cant"] else 0
        self.kpis["ticket_prom"].config(text=f"$ {prom:,.2f}")

        # Productos y valor de stock por categoria
        for r in self.tree_dash_cat.get_children():
            self.tree_dash_cat.delete(r)
        resumen_cat = get_resumen_stock_por_categoria()
        tot_prod  = sum(c["cant_productos"] for c in resumen_cat)
        tot_stock = sum(c["stock_total"]    for c in resumen_cat)
        tot_costo = sum(c["valor_costo"]    for c in resumen_cat)
        tot_venta = sum(c["valor_venta"]    for c in resumen_cat)
        for c in resumen_cat:
            self.tree_dash_cat.insert("", "end", values=(
                c["categoria"], c["cant_productos"],
                _fmt_cant(c["stock_total"]),
                f"$ {c['valor_costo']:,.2f}",
                f"$ {c['valor_venta']:,.2f}",
            ))
        if resumen_cat:
            self.tree_dash_cat.insert("", "end", values=(
                "TOTAL", tot_prod, _fmt_cant(tot_stock),
                f"$ {tot_costo:,.2f}", f"$ {tot_venta:,.2f}",
            ), tags=("total",))

        self.kpis["stock_productos"].config(text=str(tot_prod))
        self.kpis["stock_costo"].config(    text=f"$ {tot_costo:,.2f}")
        self.kpis["stock_venta"].config(    text=f"$ {tot_venta:,.2f}")
        self.kpis["stock_ganancia"].config( text=f"$ {tot_venta - tot_costo:,.2f}")

        # Top 8 del mes
        for r in self.tree_dash_top.get_children():
            self.tree_dash_top.delete(r)
        for p in get_top_productos(mes, hoy, 8):
            self.tree_dash_top.insert("", "end", values=(
                p["descripcion"], p["codigo"],
                _fmt_cant(p['cant_vendida']),
                f"$ {p['total_vendido']:,.2f}",
            ))

        # Se está por acabar. Mismo criterio que la solapa Stock: por
        # velocidad de venta, no por un umbral fijo para todo el catálogo.
        from repositorio import get_reposicion
        for r in self.tree_dash_critico.get_children():
            self.tree_dash_critico.delete(r)
        try:
            _todos = get_reposicion(30, 14, solo_faltantes=False)
        except Exception:
            _todos = []
        try:
            from config import cfg
            _umbral = float(cfg().get("stock_alerta_umbral", 5) or 5)
        except Exception:
            _umbral = 5
        # Mismo criterio que la solapa Stock: lo que se acaba segun el
        # ritmo de venta, mas lo que esta bajo aunque no haya historial.
        urgentes = [x for x in _todos
                    if x["urgencia"] in ("sin stock", "urgente")]
        _ya = {x["id"] for x in urgentes}
        urgentes += sorted(
            (x for x in _todos if x["id"] not in _ya
             and x["urgencia"] == "sin ventas" and 0 < x["stock"] <= _umbral),
            key=lambda x: x["stock"])
        for f in urgentes[:12]:
            if f["urgencia"] == "sin stock":
                dura = "SIN STOCK"
            elif f["dias_stock"] is None:
                dura = "sin datos"
            else:
                dura = f"{f['dias_stock']:.1f} d"
            self.tree_dash_critico.insert("", "end", values=(
                f["descripcion"][:38], f"{f['stock']:g}",
                f"{f['por_dia']:.2f}", dura,
                f"{f['sugerido']:g}" if f["sugerido"] else "—",
            ), tags=("critico",))

        # Vencimientos
        for r in self.tree_dash_vence.get_children():
            self.tree_dash_vence.delete(r)
        hoy_dt = datetime.now()
        for v in get_vencimientos_proximos(30):
            dias = (datetime.strptime(v["fecha_vencimiento"], "%Y-%m-%d") - hoy_dt).days
            tags = ("urgente",) if dias <= 7 else ()
            self.tree_dash_vence.insert("", "end", values=(
                v["descripcion"],
                v["fecha_vencimiento"],
                _fmt_cant(v['stock']),
            ), tags=tags)

    def _refrescar_ventas(self, desde, hasta):
        r = get_ventas_periodo(desde, hasta)
        self.resumen_kpis["total"].config(text=f"$ {r['total']:,.2f}")
        self.resumen_kpis["cant"].config( text=str(r["cant"]))
        prom = r["total"] / r["cant"] if r["cant"] else 0
        self.resumen_kpis["prom"].config( text=f"$ {prom:,.2f}")

        # Por dia
        for row in self.tree_dias.get_children():
            self.tree_dias.delete(row)
        for d in get_ventas_por_dia(desde, hasta):
            self.tree_dias.insert("", "end", values=(
                d["dia"], d["cant"], f"$ {d['total']:,.2f}"))

        # Por método
        for row in self.tree_metodo.get_children():
            self.tree_metodo.delete(row)
        total_gral = r["total"] or 1
        for m in get_ventas_por_metodo(desde, hasta):
            pct = m["total"] / total_gral * 100
            self.tree_metodo.insert("", "end", values=(
                m["metodo_pago"].capitalize(),
                m["cant"],
                f"$ {m['total']:,.2f}",
                f"{pct:.1f}%",
            ))

        # Margen por categoría
        for row in self.tree_margen.get_children():
            self.tree_margen.delete(row)
        for m in get_margen_por_categoria(desde, hasta):
            margen = m["venta_total"] - m["costo_total"]
            pct    = margen / m["venta_total"] * 100 if m["venta_total"] else 0
            self.tree_margen.insert("", "end", values=(
                m["nombre"] or "Sin categoria",
                f"$ {m['venta_total']:,.2f}",
                f"$ {m['costo_total']:,.2f}",
                f"$ {margen:,.2f}",
                f"{pct:.1f}%",
            ))

    def _refrescar_top(self, desde, hasta):
        for r in self.tree_top.get_children():
            self.tree_top.delete(r)
        for p in get_top_productos(desde, hasta, 20):
            self.tree_top.insert("", "end", values=(
                p["descripcion"], p["codigo"],
                _fmt_cant(p['cant_vendida']),
                f"$ {p['total_vendido']:,.2f}",
            ))

    def _sel_todo_stock(self, event=None):
        """Selecciona todo lo que se ve en la lista de stock crítico."""
        hijos = self.tree_stock_critico.get_children()
        self.tree_stock_critico.selection_set(hijos)
        if hijos:
            self.tree_stock_critico.focus(hijos[0])
        return "break"

    def _silenciar_stock(self):
        """Saca de la alerta los productos elegidos."""
        from repositorio import toggle_ignorar_alerta
        sel = self.tree_stock_critico.selection()
        if not sel:
            messagebox.showinfo(
                "Alerta de stock",
                "Elegí uno o varios productos.\n\n"
                "Con Ctrl o Shift marcás varios, y con Ctrl+A todos.",
                parent=self)
            return

        nombres = [self.tree_stock_critico.item(i)["values"][0] for i in sel]
        muestra = "\n".join(f"  · {n}" for n in nombres[:10])
        extra = f"\n  ...y {len(nombres) - 10} más" if len(nombres) > 10 else ""

        if not messagebox.askyesno(
                "No avisar más",
                f"{len(sel)} producto(s) dejan de aparecer en las alertas de "
                f"stock bajo, acá y en el aviso diario por mail:\n\n"
                f"{muestra}{extra}\n\n"
                "El stock se sigue contando igual: solo se deja de avisar.\n\n"
                "Para reactivarlos: Productos → Catálogo → "
                "«Alerta stock ON/OFF».\n\n¿Los silencio?", parent=self):
            return

        hechos = 0
        for iid in sel:
            try:
                toggle_ignorar_alerta(int(iid), 1)
                hechos += 1
            except Exception:
                pass
        toast(self, f"{hechos} producto(s) fuera de la alerta")
        self._refrescar_stock()

    def _refrescar_stock(self):
        from repositorio import get_reposicion
        for r in self.tree_stock_critico.get_children():
            self.tree_stock_critico.delete(r)
        try:
            todos = get_reposicion(30, 14, solo_faltantes=False)
        except Exception:
            todos = []
        try:
            from config import cfg
            umbral = float(cfg().get("stock_alerta_umbral", 5) or 5)
        except Exception:
            umbral = 5

        # Se muestran DOS cosas a la vez, porque responden a preguntas
        # distintas: los que se van a acabar segun lo que se vende, y los
        # que estan bajos aunque todavia no haya historial. En un negocio
        # nuevo casi todo cae en el segundo grupo, y esperar 30 dias de
        # datos para avisar no sirve de nada.
        con_velocidad = [x for x in todos
                         if x["urgencia"] in ("sin stock", "urgente", "reponer")]
        ids_ya = {x["id"] for x in con_velocidad}
        sin_datos = [x for x in todos
                     if x["id"] not in ids_ya
                     and x["urgencia"] == "sin ventas"
                     and 0 < x["stock"] <= umbral]
        sin_datos.sort(key=lambda x: x["stock"])
        faltantes = con_velocidad + sin_datos

        if sin_datos and con_velocidad:
            self.lbl_stock_modo.config(
                text=(f"Los primeros {len(con_velocidad)} salen del ritmo de "
                      f"venta. Los otros {len(sin_datos)} todavía no tienen "
                      f"ventas registradas: se muestran por tener "
                      f"{umbral:g} unidades o menos."))
        elif sin_datos:
            self.lbl_stock_modo.config(
                text=(f"Todavía no hay ventas suficientes para medir el "
                      f"ritmo: se muestran los que tienen {umbral:g} "
                      f"unidades o menos."))
        else:
            self.lbl_stock_modo.config(text="")

        for f in faltantes:
            if f["urgencia"] == "sin stock":
                dura = "SIN STOCK"
            elif f["dias_stock"] is None:
                # Sin ventas no se puede estimar: se dice, no se inventa
                dura = "sin datos"
            else:
                dura = f"{f['dias_stock']:.1f} d"
            self.tree_stock_critico.insert(
                "", "end", iid=str(f["id"]),
                # Gris los que no tienen historial: estan en la lista por
                # el umbral, no porque el sistema sepa que se acaban.
                tags=("critico",) if f["urgencia"] in ("sin stock", "urgente")
                     else ("sindatos",) if f["dias_stock"] is None
                     else (),
                values=(f["descripcion"][:38], f"{f['stock']:g}",
                        f"{f['por_dia']:.2f}", dura,
                        f"{f['sugerido']:g}" if f["sugerido"] else "—"))

        for r in self.tree_stock_vence.get_children():
            self.tree_stock_vence.delete(r)
        hoy_dt = datetime.now()
        for v in get_vencimientos_proximos(30):
            dias = (datetime.strptime(v["fecha_vencimiento"], "%Y-%m-%d") - hoy_dt).days
            tags = ("urgente",) if dias <= 7 else ()
            self.tree_stock_vence.insert("", "end", values=(
                v["descripcion"],
                v["fecha_vencimiento"],
                _fmt_cant(v['stock']),
            ), tags=tags)


# ══════════════════════════════════════════════════════════════════════════
# Tab "Cuándo vendo" — comparación de períodos y ventas por hora
# ══════════════════════════════════════════════════════════════════════════

def _build_cuando(self, parent):
    """Comparacion contra el periodo anterior y ventas por hora/dia.

    Un numero solo no dice si vendiste bien: "$2.400.000" puede ser
    excelente o pesimo. Y la hora ya estaba guardada en ventas.fecha
    desde siempre, sin que nadie la mirara.
    """
    parent.columnconfigure(0, weight=1)
    # Solo la fila de los paneles se estira: la barra y la comparación
    # tienen alto natural y no deben crecer.
    parent.rowconfigure(0, weight=0)
    parent.rowconfigure(1, weight=0)
    parent.rowconfigure(2, weight=1)

    bar, self.c_desde, self.c_hasta = self._filtro_fechas(
        parent, self._refrescar_cuando)
    bar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
    # Arranca en los ultimos 30 dias: un mes suelto no alcanza para ver
    # un patron de horarios.
    d0, h0 = self._rango_por_defecto()
    self.c_desde.delete(0, "end"); self.c_desde.insert(0, d0)
    self.c_hasta.delete(0, "end"); self.c_hasta.insert(0, h0)

    # ── Comparación vs período anterior ──────────────────────────────
    # En una fila de cajitas y no en una grilla de 5 filas: ocupaba tanto
    # alto que empujaba los paneles de abajo fuera de la pantalla.
    card_cmp = card(parent)
    card_cmp.grid(row=1, column=0, sticky="ew", pady=(0, 8))
    self.lbl_cmp_titulo = lbl(card_cmp, "", variante="suave",
                              bg=C.superficie)
    self.lbl_cmp_titulo.pack(anchor="w", padx=14, pady=(8, 4))

    fila = tk.Frame(card_cmp, bg=C.superficie)
    fila.pack(fill="x", padx=14, pady=(0, 8))
    self._cmp_filas = {}
    for i, (clave, etq) in enumerate((
            ("facturado", "Facturado"), ("tickets", "Tickets"),
            ("unidades", "Unidades"), ("ticket_prom", "Ticket promedio"))):
        fila.columnconfigure(i, weight=1)
        caja = tk.Frame(fila, bg=C.superficie)
        caja.grid(row=0, column=i, sticky="ew", padx=(0, 10))
        tk.Label(caja, text=etq, bg=C.superficie, fg=C.texto_suave,
                 font=F.pequeña, anchor="w").pack(anchor="w")
        l_act = tk.Label(caja, text="—", bg=C.superficie, fg=C.texto,
                         font=F.subtitulo, anchor="w")
        l_act.pack(anchor="w")
        l_var = tk.Label(caja, text="", bg=C.superficie, font=F.pequeña,
                         anchor="w")
        l_var.pack(anchor="w")
        l_ant = tk.Label(caja, text="", bg=C.superficie, fg=C.texto_suave,
                         font=F.pequeña, anchor="w")
        l_ant.pack(anchor="w")
        self._cmp_filas[clave] = (l_act, l_ant, l_var)

    # Aprovechar el aire de la tarjeta de comparación con datos que no
    # están en ningún otro informe.
    self.lbl_cmp_extra = lbl(card_cmp, "", variante="suave", bg=C.superficie)
    self.lbl_cmp_extra.pack(anchor="w", padx=14, pady=(0, 10))

    # ── Por hora y por día ───────────────────────────────────────────
    cont = tk.Frame(parent, bg=C.bg)
    cont.grid(row=2, column=0, sticky="nsew")
    cont.columnconfigure(0, weight=3)
    cont.columnconfigure(1, weight=2)
    cont.rowconfigure(0, weight=1)

    izq = card(cont)
    izq.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
    lbl(izq, "A qué hora vendés", variante="subtitulo",
        bg=C.superficie).pack(anchor="w", padx=16, pady=(12, 2))
    lbl(izq, "Las horas sin ventas también se muestran: los huecos "
             "son información.", variante="suave",
        bg=C.superficie).pack(anchor="w", padx=16)
    # Con alto fijo de 16 lineas las ultimas horas quedaban cortadas y
    # no habia forma de verlas: ahora se estira y ademas tiene scroll.
    cont_h = tk.Frame(izq, bg=C.superficie)
    cont_h.pack(fill="both", expand=True, padx=16, pady=(8, 14))
    # height es el MINIMO que pide el widget: aunque el contenedor no
    # llegue a estirarlo, las 14 lineas (las horas con venta de un
    # autoservicio) se ven sin scrollear.
    self.txt_horas = tk.Text(cont_h, font=F.mono, bg=C.superficie,
                             fg=C.texto, relief="flat", height=14, wrap="none")
    sb_h = ttk.Scrollbar(cont_h, orient="vertical",
                         command=self.txt_horas.yview)
    self.txt_horas.configure(yscrollcommand=sb_h.set)
    self.txt_horas.pack(side="left", fill="both", expand=True)
    sb_h.pack(side="right", fill="y")

    der = card(cont)
    der.grid(row=0, column=1, sticky="nsew")
    lbl(der, "Qué día vendés más", variante="subtitulo",
        bg=C.superficie).pack(anchor="w", padx=16, pady=(12, 2))
    lbl(der, "Promedio por jornada, no total: un período con 5 lunes y "
             "4 martes haría parecer que el lunes vende más.",
        variante="suave", bg=C.superficie).pack(anchor="w", padx=16)
    self.txt_dias = tk.Text(der, font=F.mono, bg=C.superficie, fg=C.texto,
                            relief="flat", height=8, wrap="none")   # 7 días
    self.txt_dias.pack(fill="both", expand=True, padx=16, pady=(8, 14))


def _refrescar_cuando(self, desde, hasta):
    from repositorio import (comparar_periodos, get_ventas_por_hora,
                             get_ventas_por_dia_semana)
    self._cuando_rango = (desde, hasta)
    try:
        cmp_ = comparar_periodos(desde, hasta)
        horas = get_ventas_por_hora(desde, hasta)
        dias = get_ventas_por_dia_semana(desde, hasta)
    except Exception as exc:
        self.lbl_cmp_titulo.config(text=f"No se pudo calcular: {exc}")
        return

    a, b = cmp_["anterior"], cmp_["actual"]
    self.lbl_cmp_titulo.config(
        text=(f"{b['desde']} a {b['hasta']} ({cmp_['dias']} días) "
              f"contra {a['desde']} a {a['hasta']}"))

    def _fmt(clave, valor):
        if clave in ("facturado", "ticket_prom"):
            return f"$ {valor:,.2f}"
        return f"{valor:g}"

    for clave, (l_act, l_ant, l_var) in self._cmp_filas.items():
        l_act.config(text=_fmt(clave, cmp_["actual"][clave]))
        var = cmp_["var"][clave]
        if var is None:
            l_var.config(text="sin período anterior", fg=C.texto_suave)
            l_ant.config(text="")
        else:
            l_var.config(text=f"{var:+.1f}%",
                         fg=C.exito if var >= 0 else C.peligro)
            l_ant.config(text=f"antes {_fmt(clave, cmp_['anterior'][clave])}")

    # Lo que no se ve en ningún otro lado: cuánto se vende por día
    # abierto y cuántas unidades entran en cada ticket.
    jornadas = sum(d["dias_contados"] for d in dias)
    por_jornada = (b["facturado"] / jornadas) if jornadas else 0
    unid_ticket = (b["unidades"] / b["tickets"]) if b["tickets"] else 0
    pico = max(horas, key=lambda x: x["facturado"]) if horas else None
    extra = (f"Promedio por jornada: $ {por_jornada:,.2f}   ·   "
             f"{unid_ticket:.1f} unidades por ticket   ·   "
             f"{jornadas} jornada(s) con ventas")
    if pico and pico["facturado"]:
        extra += f"   ·   hora pico: {pico['h']:02d}:00"
    self.lbl_cmp_extra.config(text=extra)

    # Barras de texto: se leen igual que un gráfico y no dependen de
    # ninguna librería de dibujo.
    self.txt_horas.config(state="normal")
    self.txt_horas.delete("1.0", "end")
    con_venta = [h for h in horas if h["tickets"]]
    if not con_venta:
        self.txt_horas.insert("end", "Sin ventas en el período.")
    else:
        maxf = max(h["facturado"] for h in horas) or 1
        h_ini = max(0, min(h["h"] for h in con_venta) - 1)
        h_fin = min(23, max(h["h"] for h in con_venta) + 1)
        pico = max(con_venta, key=lambda x: x["facturado"])
        for h in horas[h_ini:h_fin + 1]:
            barra = "█" * int(h["facturado"] / maxf * 26)
            marca = "  ← pico" if h["h"] == pico["h"] else ""
            self.txt_horas.insert(
                "end", f"{h['h']:02d}:00  {h['tickets']:>4} tk  "
                       f"$ {h['facturado']:>10,.0f}  {barra}{marca}\n")
    self.txt_horas.config(state="disabled")

    self.txt_dias.config(state="normal")
    self.txt_dias.delete("1.0", "end")
    maxd = max((d["promedio_dia"] for d in dias), default=0) or 1
    for d in dias:
        barra = "█" * int(d["promedio_dia"] / maxd * 14)
        self.txt_dias.insert(
            "end", f"{d['dia'][:9]:<10} $ {d['promedio_dia']:>9,.0f}  {barra}\n")
    self.txt_dias.config(state="disabled")


InformesUI._build_cuando = _build_cuando
InformesUI._refrescar_cuando = _refrescar_cuando


# ══════════════════════════════════════════════════════════════════════════
# Tab "Se venden juntos" — análisis de canasta
# ══════════════════════════════════════════════════════════════════════════

COLS_JUNTOS = [
    ("a",      "Producto",          230, "w"),
    ("b",      "Se lleva con",      230, "w"),
    ("juntos", "Veces juntos",      100, "e"),
    ("pct_a",  "De los que llevan A", 150, "e"),
    ("pct_b",  "De los que llevan B", 150, "e"),
]


def _build_juntos(self, parent):
    """Qué productos aparecen en el mismo ticket.

    Sirve para armar combos que ya se venden solos, ubicar la góndola,
    y saber qué venta cruzada se pierde cuando falta uno de los dos.
    """
    parent.columnconfigure(0, weight=1)
    parent.rowconfigure(3, weight=1)

    bar, self.j_desde, self.j_hasta = self._filtro_fechas(
        parent, self._refrescar_juntos)
    bar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
    d0, h0 = self._rango_por_defecto()
    self.j_desde.delete(0, "end"); self.j_desde.insert(0, d0)
    self.j_hasta.delete(0, "end"); self.j_hasta.insert(0, h0)

    self.lbl_j_aviso = lbl(parent, "", variante="suave")
    self.lbl_j_aviso.grid(row=1, column=0, sticky="w", pady=(0, 6))

    lbl(parent, "«De los que llevan A» es cuántas veces, sobre el total de "
                "tickets con ese producto, también se llevó el otro. Las dos "
                "direcciones no son lo mismo.",
        variante="suave").grid(row=2, column=0, sticky="w", pady=(0, 6))

    frame_t, self.tree_juntos = tabla(parent, COLS_JUNTOS)
    frame_t.grid(row=3, column=0, sticky="nsew")
    self.tree_juntos.tag_configure("fuerte", background=C.ok_flash)

    self.lbl_j_pie = lbl(parent, "", variante="suave")
    self.lbl_j_pie.grid(row=4, column=0, sticky="w", pady=(6, 0))


def _refrescar_juntos(self, desde, hasta):
    from repositorio import productos_que_se_venden_juntos
    try:
        r = productos_que_se_venden_juntos(desde, hasta)
    except Exception as exc:
        self.lbl_j_aviso.config(text=f"No se pudo calcular: {exc}")
        return

    self.tree_juntos.delete(*self.tree_juntos.get_children())
    for p in r["pares"]:
        # Se resalta cuando la relación es fuerte en alguna dirección:
        # esos son los pares que sirven para un combo o para la góndola.
        fuerte = max(p["pct_a"], p["pct_b"]) >= 50
        self.tree_juntos.insert(
            "", "end", tags=("fuerte",) if fuerte else (), values=(
                p["a"][:40], p["b"][:40], p["juntos"],
                f"{p['pct_a']:.0f}%", f"{p['pct_b']:.0f}%"))

    if not r["canastas"]:
        self.lbl_j_aviso.config(
            text="No hay tickets con más de un producto en este período.",
            foreground=C.texto_suave)
    elif not r["confiable"]:
        # Con pocos tickets los porcentajes son casualidad, no patrón
        self.lbl_j_aviso.config(
            text=(f"⚠ Solo {r['canastas']} tickets con 2 o más productos. "
                  f"Con menos de 100 los porcentajes son ruido: tomalo como "
                  f"orientativo y volvé a mirarlo con más historial."),
            foreground=C.peligro)
    else:
        self.lbl_j_aviso.config(
            text=f"{r['canastas']} tickets con 2 o más productos.",
            foreground=C.texto_suave)

    n = len(r["pares"])
    fuertes = sum(1 for p in r["pares"] if max(p["pct_a"], p["pct_b"]) >= 50)
    self.lbl_j_pie.config(
        text=(f"{n} par(es) que se repiten   ·   {fuertes} con relación "
              f"fuerte (más del 50%) — esos son los que sirven para un "
              f"combo o para acercarlos en la góndola"))


InformesUI._build_juntos = _build_juntos
InformesUI._refrescar_juntos = _refrescar_juntos


# ══════════════════════════════════════════════════════════════════════════
# Tab "Cobranzas" — vendido, cobrado por método y pendiente
# ══════════════════════════════════════════════════════════════════════════

def _build_cobranzas(self, parent):
    """Tres preguntas que se confunden todo el tiempo.

    Cuánto vendí (entre o no la plata), cuánto entró por cada medio, y
    cuánto me deben todavía.
    """
    parent.columnconfigure(0, weight=1)
    parent.rowconfigure(0, weight=0)
    parent.rowconfigure(1, weight=1)

    bar, self.cb_desde, self.cb_hasta = self._filtro_fechas(
        parent, self._refrescar_cobranzas)
    bar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
    d0, h0 = self._rango_por_defecto()
    self.cb_desde.delete(0, "end"); self.cb_desde.insert(0, d0)
    self.cb_hasta.delete(0, "end"); self.cb_hasta.insert(0, h0)

    cont = tk.Frame(parent, bg=C.bg)
    cont.grid(row=1, column=0, sticky="nsew")
    for i in range(3):
        cont.columnconfigure(i, weight=1)
    cont.rowconfigure(0, weight=1)

    self._cb_lbl = {}

    def _panel(col, titulo, filas, color_total=None):
        card_ = card(cont)
        card_.grid(row=0, column=col, sticky="nsew", padx=(0, 8) if col < 2 else 0)
        lbl(card_, titulo, variante="subtitulo",
            bg=C.superficie).pack(anchor="w", padx=16, pady=(14, 8))
        for clave, etq, destacar in filas:
            f = tk.Frame(card_, bg=C.superficie)
            f.pack(fill="x", padx=16, pady=(0, 6 if destacar else 2))
            tk.Label(f, text=etq, bg=C.superficie,
                     fg=C.texto if destacar else C.texto_suave,
                     font=F.normal if destacar else F.pequeña,
                     anchor="w").pack(side="left")
            v = tk.Label(f, text="—", bg=C.superficie,
                         fg=color_total if destacar else C.texto,
                         font=F.subtitulo if destacar else F.normal,
                         anchor="e")
            v.pack(side="right")
            self._cb_lbl[clave] = v
            if destacar:
                ttk.Separator(card_, orient="horizontal").pack(
                    fill="x", padx=16, pady=(2, 8))
        return card_

    _panel(0, "Vendido", [
        ("tickets",   "Tickets",              False),
        ("costo",     "Costo de lo vendido",  False),
        ("ganancia",  "Ganancia",             False),
        ("facturado", "TOTAL FACTURADO",      True)],
        color_total=C.texto)

    _panel(1, "Cobrado", [
        ("efectivo",       "Efectivo",              False),
        ("tarjeta",        "Tarjeta",               False),
        ("qr",             "QR",                    False),
        ("cobros_cta_cte", "Pagos de cta. corriente", False),
        ("cobrado",        "TOTAL COBRADO",         True)],
        color_total=C.exito)

    _panel(2, "Pendiente de cobrar", [
        ("fiado",       "Fiado en este período",  False),
        ("clientes",    "Clientes que deben",     False),
        ("deuda_total", "DEUDA TOTAL",            True)],
        color_total=C.peligro)

    self.lbl_cb_pie = lbl(parent, "", variante="suave")
    self.lbl_cb_pie.grid(row=2, column=0, sticky="w", pady=(10, 0))


def _refrescar_cobranzas(self, desde, hasta):
    from repositorio import resumen_cobranzas
    try:
        r = resumen_cobranzas(desde, hasta)
    except Exception as exc:
        self.lbl_cb_pie.config(text=f"No se pudo calcular: {exc}")
        return

    def _set(clave, valor, plata=True):
        w = self._cb_lbl.get(clave)
        if w is not None:
            w.config(text=f"$ {valor:,.2f}" if plata else f"{valor:g}")

    for k in ("facturado", "costo", "ganancia", "efectivo", "tarjeta", "qr",
              "cobros_cta_cte", "cobrado", "fiado", "deuda_total"):
        _set(k, r[k])
    _set("tickets", r["tickets"], plata=False)
    _set("clientes", r["clientes_con_deuda"], plata=False)

    # El porcentaje cobrado es el número que resume todo: dice cuánto de
    # lo que vendiste realmente entró.
    # Si las partes no suman el total, los números por método están
    # incompletos: mostrarlos sin avisar sería peor que no mostrarlos.
    if abs(r.get("descuadre", 0)) > 1:
        self.lbl_cb_pie.config(
            text=(f"⚠  Los métodos de pago suman $ {r['suma_medios']:,.2f} "
                  f"pero se facturaron $ {r['facturado']:,.2f}. Faltan "
                  f"$ {r['descuadre']:,.2f} sin identificar — son ventas "
                  f"anteriores a que el sistema guardara el detalle. "
                  f"Reiniciá el TPV para completarlas."),
            foreground=C.peligro)
        return

    txt = (f"Cobraste el {r['pct_cobrado']:.0f}% de lo facturado en el "
           f"período.")
    if r["fiado"]:
        txt += (f"   Quedaron $ {r['fiado']:,.2f} fiados, que se suman a la "
                f"deuda acumulada.")
    if r["devoluciones"]:
        txt += f"   Devoluciones del período: $ {r['devoluciones']:,.2f}."
    self.lbl_cb_pie.config(text=txt, foreground=C.texto_suave)


InformesUI._build_cobranzas = _build_cobranzas
InformesUI._refrescar_cobranzas = _refrescar_cobranzas

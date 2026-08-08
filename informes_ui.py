"""
informes_ui.py — Dashboard e informes TPV v2.0
"""

import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime, timedelta
from styles import C, F, btn, lbl, card, tabla, header_seccion, scrollable
from repositorio import (get_ventas_periodo, get_ventas_por_dia,
                         get_ventas_por_metodo, get_top_productos,
                         get_margen_por_categoria, get_stock_critico,
                         get_vencimientos_proximos, get_rentabilidad_productos,
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
    ("desc",   "Producto",   260, "w"),
    ("codigo", "Codigo",      90, "w"),
    ("stock",  "Stock",       60, "e"),
    ("precio", "Precio",      80, "e"),
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
        lbl(f_sc, "Stock critico", variante="subtitulo",
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

        lbl(parent, "Stock critico (< 5 u.)", variante="subtitulo",
            fg=C.peligro).grid(row=0, column=0, sticky="w", pady=(0,4))
        lbl(parent, "Vencimientos proximos (30 dias)", variante="subtitulo",
            fg=C.advertencia).grid(row=0, column=1, sticky="w", pady=(0,4), padx=(8,0))

        frame_sc, self.tree_stock_critico = tabla(parent, COLS_STOCK)
        frame_sc.grid(row=1, column=0, sticky="nsew", padx=(0,8))
        self.tree_stock_critico.tag_configure("critico", foreground=C.peligro)

        frame_vv, self.tree_stock_vence = tabla(parent, COLS_VENCE)
        frame_vv.grid(row=1, column=1, sticky="nsew")
        self.tree_stock_vence.tag_configure("urgente", foreground=C.peligro)

        btn(parent, "Actualizar", variante="neutro",
            comando=self._refrescar_stock).grid(row=2, column=0, columnspan=2,
                                                  sticky="w", pady=(8,0))
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
        }
        fn = metodos.get(tab)
        if fn:
            self.after(50, fn)

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
            self.tree_rent_prod.insert("", "end", values=(
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

        # Stock critico
        for r in self.tree_dash_critico.get_children():
            self.tree_dash_critico.delete(r)
        for s in get_stock_critico():
            self.tree_dash_critico.insert("", "end", values=(
                s["descripcion"], s["codigo"],
                _fmt_cant(s['stock']),
                f"$ {s['precio_base']:,.2f}",
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

    def _refrescar_stock(self):
        for r in self.tree_stock_critico.get_children():
            self.tree_stock_critico.delete(r)
        for s in get_stock_critico():
            self.tree_stock_critico.insert("", "end", values=(
                s["descripcion"], s["codigo"],
                _fmt_cant(s['stock']),
                f"$ {s['precio_base']:,.2f}",
            ), tags=("critico",))

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

"""
precios_ui.py — Gestión de precios y promociones TPV v2.0
Actualización masiva + promociones flexibles por cantidad
"""

import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
from styles import C, F, btn, lbl, card, tabla, toast, header_seccion, scrollable
from repositorio import (get_productos, get_categorias, get_promociones,
                         guardar_promocion, toggle_promocion, eliminar_promocion,
                         actualizar_precio, aplicar_aumento_bulk,
                         aplicar_margen_nuevo_bulk,
                         aplicar_margen_bulk, aplicar_promocion_bulk,
                         get_promocion_por_id, get_codigo_producto)

# ─────────────────────────────────────────────────────────────────────────────
# Helpers DB
# ─────────────────────────────────────────────────────────────────────────────

COLS_PRECIOS = [
    ("sel",      "",            30,  "center"),
    ("codigo",   "Codigo",      90,  "w"),
    ("desc",     "Descripcion", 240, "w"),
    ("categoria","Categoria",   100, "w"),
    ("costo",    "Costo",        80, "e"),
    ("precio",   "Precio",       80, "e"),
    ("margen",   "Margen %",     70, "e"),
]

COLS_PROMOS = [
    ("desc",    "Producto",     200, "w"),
    ("detalle", "Descripcion",  140, "w"),
    ("cant",    "Desde cant.",   80, "e"),
    ("precio",  "Precio/Desc.",  85, "e"),
    ("desde",   "Desde",         80, "w"),
    ("hasta",   "Hasta",         80, "w"),
    ("activa",  "Activa",        55, "center"),
]

def _centrar(d, w, h):
    sw = d.winfo_screenwidth()
    sh = d.winfo_screenheight()
    # Si el diálogo es más alto/ancho que la pantalla, antes quedaba con
    # la barra de título arriba del área visible — imposible de bajar.
    margen = 40
    w = min(w, sw - 20)
    h = min(h, sh - margen)
    x = max(0, (sw - w) // 2)
    y = max(0, (sh - h) // 2)
    d.geometry(f"{w}x{h}+{x}+{y}")

class PreciosUI(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._cat_map = {}
        self._seleccionados = set()   # ids seleccionados para bulk
        self._promo_sel_id = None
        self._build()
        self._refrescar()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build(self):
        # Gestión de precios de venta, márgenes y promociones por cantidad.
        # Las promociones se aplican automáticamente al momento de vender.
        header_seccion(self, "Precios y Promociones",
            "Actualiza precios, margenes y promociones por cantidad").pack(
            fill="x", padx=12, pady=(8,0))

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=12, pady=12)

        f_precios = ttk.Frame(nb)
        f_promos  = ttk.Frame(nb)
        nb.add(f_precios, text="  Actualizar precios  ")
        nb.add(f_promos,  text="  Promociones  ")

        self._build_precios(f_precios)
        self._build_promos(f_promos)

    # ── Tab Precios ───────────────────────────────────────────────────────────

    def _build_precios(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)

        # Filtros
        bar = tk.Frame(parent, bg=C.bg)
        bar.grid(row=0, column=0, sticky="ew", pady=(0,8))

        lbl(bar, "Buscar:").pack(side="left", padx=(0,6))
        self.entry_buscar = tk.Entry(bar, font=F.normal, width=24,
                                      bg=C.superficie, fg=C.texto,
                                      insertbackground=C.primario,
                                      relief="solid", bd=1)
        self.entry_buscar.pack(side="left", ipady=5)
        self.entry_buscar.bind("<KeyRelease>", lambda e: self._refrescar_tabla())

        lbl(bar, "Cat:").pack(side="left", padx=(12,4))
        self.combo_cat = ttk.Combobox(bar, font=F.normal, width=14, state="readonly")
        self.combo_cat.pack(side="left")
        self.combo_cat.bind("<<ComboboxSelected>>", lambda e: self._refrescar_tabla())

        btn(bar, "Selec. todo", variante="neutro",
            comando=self._sel_todo).pack(side="left", padx=8)
        btn(bar, "Desel. todo", variante="neutro",
            comando=self._desel_todo).pack(side="left")

        lbl(bar, "Seleccionados:", variante="suave").pack(side="left", padx=(12,4))
        self.lbl_sel = lbl(bar, "0", variante="badge")
        self.lbl_sel.pack(side="left")

        # Tabla
        frame_t, self.tree_p = tabla(parent, COLS_PRECIOS)
        frame_t.grid(row=1, column=0, sticky="nsew")
        self.tree_p.bind("<ButtonRelease-1>", self._on_click_tabla)
        self.tree_p.bind("<Double-1>",        self._editar_precio_inline)

        # Panel de acciones bulk
        bulk = card(parent)
        bulk.grid(row=2, column=0, sticky="ew", pady=(8,0))
        bulk.columnconfigure(3, weight=1)

        lbl(bulk, "Aumento %", variante="suave",
            bg=C.superficie).grid(row=0, column=0, padx=(16,4), pady=12)
        self.entry_pct = tk.Entry(bulk, width=7, justify="center", font=F.normal,
                                   bg=C.superficie, fg=C.texto,
                                   relief="solid", bd=1)
        self.entry_pct.insert(0, "10")
        self.entry_pct.grid(row=0, column=1, pady=12, ipady=5)

        btn(bulk, "Aplicar a seleccionados", variante="primario",
            comando=self._aplicar_aumento).grid(row=0, column=2, padx=8, pady=8)

        btn(bulk, "Recalcular por margen de categoria",
            variante="neutro",
            comando=self._aplicar_margen).grid(row=0, column=3, padx=(0,8), pady=8)

        btn(bulk, "Editar precio", variante="neutro",
            comando=self._editar_precio_inline).grid(row=0, column=4, padx=(0,16), pady=8)

    # ── Tab Promociones ───────────────────────────────────────────────────────

    def _build_promos(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)

        # Tabla
        frame_t, self.tree_pr = tabla(parent, COLS_PROMOS)
        frame_t.grid(row=0, column=0, sticky="nsew", pady=(0,8))
        self.tree_pr.bind("<<TreeviewSelect>>", self._on_sel_promo)

        # Acciones
        # DOS filas: ocho botones en una sola no entraban a lo ancho y
        # los ultimos quedaban cortados fuera de la pantalla (asi se
        # habia "perdido" el de Placas y el de Actualizar).
        # Arriba lo que opera sobre las promociones; abajo, lo que
        # exporta hacia afuera.
        ac = tk.Frame(parent, bg=C.bg)
        ac.grid(row=1, column=0, sticky="ew")

        btn(ac, "➕  Nueva promocion",  variante="exito",   comando=self._nueva_promo).pack(side="left")
        btn(ac, "✏️  Editar",           variante="primario", comando=self._editar_promo).pack(side="left", padx=6)
        btn(ac, "📊  Promoción masiva", variante="exito",
            comando=self._dialogo_promocion_masiva).pack(side="left", padx=6)
        btn(ac, "⏸  Pausar/Activar",   variante="neutro",   comando=self._toggle_promo).pack(side="left")
        btn(ac, "🗑  Eliminar",         variante="peligro",  comando=self._eliminar_promo).pack(side="left", padx=6)
        btn(ac, "🔄  Actualizar",       variante="neutro",   comando=self._refrescar_promos).pack(side="right")

        ac2 = tk.Frame(parent, bg=C.bg)
        ac2.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        lbl(ac2, "Exportar:", variante="suave").pack(side="left", padx=(0, 8))
        btn(ac2, "📄  Lista de precios", variante="neutro",
            comando=self._exportar_lista_precios).pack(side="left", padx=(0, 6))
        btn(ac2, "🗞️  Folleto de ofertas", variante="neutro",
            comando=self._exportar_folleto).pack(side="left", padx=6)
        btn(ac2, "📱  Placas para estados", variante="neutro",
            comando=self._placas_estados).pack(side="left", padx=6)

    def _avisar_bajo_costo(self, ids, parent=None):
        """Avisa si alguna operacion masiva dejo precios bajo costo.

        En masa no se puede preguntar antes producto por producto, pero
        callarlo es peor: quedarian vendiendose a perdida sin que nada
        lo marque.
        """
        from repositorio import productos_bajo_costo
        try:
            malos = productos_bajo_costo(ids)
        except Exception:
            return
        if not malos:
            return
        detalle = "\n".join(
            f"  · {m['descripcion'][:34]}: se vende a $ {m['precio_base']:,.2f} "
            f"y cuesta $ {m['costo_ultimo']:,.2f}" for m in malos[:8])
        extra = f"\n  ...y {len(malos) - 8} más" if len(malos) > 8 else ""
        messagebox.showwarning(
            "Quedaron precios bajo costo",
            f"{len(malos)} producto(s) quedaron por debajo de su costo:\n\n"
            f"{detalle}{extra}\n\n"
            "Revisalos en Productos → A revisar, o volvé a fijarles el precio.",
            parent=parent or self)

    def _exportar_lista_precios(self):
        from lista_precios import abrir_selector_lista_precios
        abrir_selector_lista_precios(self)

    def _exportar_folleto(self):
        from folleto_precios import abrir_selector_folleto
        abrir_selector_folleto(self)

    def _placas_estados(self):
        """Imagenes sueltas por producto o combo, para estados y feed."""
        from placas import abrir_selector_placas
        abrir_selector_placas(self)

    # ── Datos ─────────────────────────────────────────────────────────────────

    def refrescar(self):
        self._refrescar()

    def _refrescar(self):
        cats = get_categorias()
        self._cat_map = {r["nombre"]: r["id"] for r in cats}
        self.combo_cat["values"] = ["(Todas)"] + list(self._cat_map.keys())
        if not self.combo_cat.get():
            self.combo_cat.set("(Todas)")
        self._refrescar_tabla()
        self._refrescar_promos()

    def _refrescar_tabla(self):
        filtro = self.entry_buscar.get().strip()
        cat_nombre = self.combo_cat.get()
        cat_id = self._cat_map.get(cat_nombre)
        self._seleccionados.clear()
        self.lbl_sel.config(text="0")

        for r in self.tree_p.get_children():
            self.tree_p.delete(r)

        self._filas = {}   # iid → row dict
        for p in get_productos(filtro, cat_id):
            iid = str(p["id"])
            self.tree_p.insert("", "end", iid=iid, values=(
                "",
                p["codigo"],
                p["descripcion"],
                p["categoria"] or "—",
                f"$ {p['costo_ultimo']:,.2f}",
                f"$ {p['precio_base']:,.2f}",
                f"{p['margen'] or 0:.1f}%",
            ))
            self._filas[iid] = dict(p)

    def _refrescar_promos(self):
        for r in self.tree_pr.get_children():
            self.tree_pr.delete(r)
        for pr in get_promociones():
            if pr.get("tipo_descuento") == "porcentaje":
                col_precio = f"-{pr.get('porcentaje_descuento') or 0:.1f}%"
            else:
                col_precio = f"$ {pr['precio_unitario']:,.2f}"
            self.tree_pr.insert("", "end", iid=str(pr["id"]), values=(
                pr["descripcion"],
                pr["detalle"] or "—",
                f"x {pr['cantidad_minima']}",
                col_precio,
                pr["fecha_desde"] or "—",
                pr["fecha_hasta"] or "—",
                "Si" if pr["activa"] else "No",
            ), tags=("activa",) if pr["activa"] else ("inactiva",))
        self.tree_pr.tag_configure("activa",   foreground=C.exito)
        self.tree_pr.tag_configure("inactiva", foreground=C.texto_suave)

    # ── Selección bulk ────────────────────────────────────────────────────────

    def _on_click_tabla(self, event):
        iid = self.tree_p.identify_row(event.y)
        if not iid:
            return
        col = self.tree_p.identify_column(event.x)
        if col == "#1":   # columna checkbox
            if iid in self._seleccionados:
                self._seleccionados.discard(iid)
                self.tree_p.set(iid, "sel", "")
            else:
                self._seleccionados.add(iid)
                self.tree_p.set(iid, "sel", "x")
            self.lbl_sel.config(text=str(len(self._seleccionados)))

    def _sel_todo(self):
        self._seleccionados = set(self.tree_p.get_children())
        for iid in self._seleccionados:
            self.tree_p.set(iid, "sel", "x")
        self.lbl_sel.config(text=str(len(self._seleccionados)))

    def _desel_todo(self):
        for iid in self._seleccionados:
            self.tree_p.set(iid, "sel", "")
        self._seleccionados.clear()
        self.lbl_sel.config(text="0")

    # ── Acciones precios ──────────────────────────────────────────────────────

    def _aplicar_aumento(self):
        if not self._seleccionados:
            messagebox.showinfo("Atención", "Selecciona productos con la columna de la izquierda.", parent=self)
            return
        try:
            pct = float(self.entry_pct.get().replace(",", "."))
        except ValueError:
            messagebox.showwarning("Error", "Porcentaje invalido.", parent=self)
            return
        ids = [int(i) for i in self._seleccionados]
        # Un aumento masivo toca el precio de decenas de productos: si
        # sale mal no hay "deshacer", solo volver a calcularlo al reves.
        from fiado_ui import pedir_autorizacion
        responsable = pedir_autorizacion(
            self, f"Aplicar {pct:+g}% a {len(ids)} producto(s).")
        if not responsable:
            return

        if messagebox.askyesno("Confirmar",
                                f"Aplicar +{pct}% a {len(ids)} productos?", parent=self):
            aplicar_aumento_bulk(ids, pct)
            from repositorio import registrar_bitacora
            registrar_bitacora("Aumento masivo de precios", responsable,
                               f"{pct:+g}% sobre {len(ids)} producto(s)")
            toast(self, f"Precios actualizados (+{pct}%)")
            import catalogo_web
            catalogo_web.sincronizar_stock_en_segundo_plano()
            self._refrescar_tabla()

    def _aplicar_margen(self):
        if not self._seleccionados:
            messagebox.showinfo("Atención", "Selecciona productos primero.", parent=self)
            return
        ids = [int(i) for i in self._seleccionados]
        # Un aumento masivo toca el precio de decenas de productos: si
        # sale mal no hay "deshacer", solo volver a calcularlo al reves.
        from fiado_ui import pedir_autorizacion
        responsable = pedir_autorizacion(
            self, f"Recalcular por margen {len(ids)} producto(s).")
        if not responsable:
            return

        if messagebox.askyesno("Confirmar",
                                f"Recalcular precio por margen de categoria para {len(ids)} productos?\n"
                                "El precio = costo x (1 + margen%)", parent=self):
            aplicar_margen_bulk(ids)
            from repositorio import registrar_bitacora
            registrar_bitacora("Recalculo por margen", responsable,
                               f"{len(ids)} producto(s)")
            toast(self, "Precios recalculados por margen")
            import catalogo_web
            catalogo_web.sincronizar_stock_en_segundo_plano()
            self._refrescar_tabla()

    def _dialogo_promocion_masiva(self):
        """
        Aplica un descuento por % sobre el precio de lista a varios
        productos a la vez, con 3 formas de elegir a quiénes:
        todos los productos activos, una categoría entera, o elegir
        productos puntuales de una lista (Ctrl/Shift+click).
        """
        d = tk.Toplevel(self)
        d.title("Promoción masiva")
        _centrar(d, 540, 640)
        d.configure(bg=C.superficie)
        d.grab_set()
        d.columnconfigure(0, weight=1)
        d.rowconfigure(0, weight=1)

        outer, s = scrollable(d, bg=C.superficie)
        outer.grid(row=0, column=0, sticky="nsew")

        lbl(s, "Promoción masiva por descuento", variante="titulo",
            bg=C.superficie).pack(pady=(20,4), padx=20, anchor="w")
        lbl(s, "Aplica un % de descuento sobre el precio de lista a "
              "varios productos a la vez. El precio de venta con "
              "promo = precio de lista − %.",
            variante="suave", bg=C.superficie,
            wraplength=480, justify="left").pack(padx=20, anchor="w", pady=(0,14))

        # ── Cómo elegir los productos ────────────────────────────────
        modo = tk.StringVar(value="todos")
        f_modo = tk.Frame(s, bg=C.superficie)
        f_modo.pack(fill="x", padx=20, pady=(0,4))
        for texto, val in [("Todos los productos activos", "todos"),
                           ("Una categoría", "categoria"),
                           ("Elegir productos de la lista", "elegir")]:
            tk.Radiobutton(f_modo, text=texto, variable=modo, value=val,
                          bg=C.superficie, font=F.normal, anchor="w",
                          command=lambda: _actualizar_modo()).pack(
                fill="x", anchor="w")

        cats = get_categorias()
        cat_map = {c["nombre"]: c["id"] for c in cats}
        combo_cat = ttk.Combobox(s, font=F.normal, state="readonly",
                                 values=list(cat_map.keys()))
        if cats:
            combo_cat.current(0)

        f_lista = card(s)
        lbl_lista_ayuda = lbl(
            f_lista, "Ctrl+click (o Shift+click) para elegir varios",
            variante="suave", bg=C.superficie)
        f_lista.columnconfigure(0, weight=1)
        tree_multi = ttk.Treeview(f_lista, columns=("desc","cat","precio"),
                                  show="headings", height=9,
                                  selectmode="extended")
        tree_multi.heading("desc", text="Producto")
        tree_multi.heading("cat", text="Categoria")
        tree_multi.heading("precio", text="Precio")
        tree_multi.column("desc", width=230, anchor="w")
        tree_multi.column("cat", width=110, anchor="w")
        tree_multi.column("precio", width=80, anchor="e")
        sb_multi = ttk.Scrollbar(f_lista, orient="vertical",
                                 command=tree_multi.yview)
        tree_multi.configure(yscrollcommand=sb_multi.set)

        todos_productos = get_productos(solo_activos=True)
        for p in todos_productos:
            tree_multi.insert("", "end", iid=str(p["id"]),
                              values=(p["descripcion"], p.get("categoria") or "—",
                                      f"$ {p['precio_base']:,.2f}"))

        def _actualizar_modo():
            combo_cat.pack_forget()
            f_lista.pack_forget()
            lbl_lista_ayuda.grid_forget()
            tree_multi.grid_forget()
            sb_multi.grid_forget()
            if modo.get() == "categoria":
                combo_cat.pack(fill="x", padx=20, pady=(4,10), ipady=3)
            elif modo.get() == "elegir":
                lbl_lista_ayuda.grid(row=0, column=0, columnspan=2,
                                     sticky="w", padx=4, pady=(4,0))
                tree_multi.grid(row=1, column=0, sticky="nsew", padx=(4,0), pady=4)
                sb_multi.grid(row=1, column=1, sticky="ns", pady=4)
                f_lista.pack(fill="both", expand=True, padx=20, pady=(4,10))

        _actualizar_modo()

        lbl(s, "Descuento % *", variante="suave", bg=C.superficie).pack(
            padx=20, anchor="w")
        e_pct = tk.Entry(s, font=F.normal, bg=C.superficie, fg=C.texto,
                         insertbackground=C.primario, relief="solid", bd=1)
        e_pct.insert(0, "10")
        e_pct.pack(fill="x", padx=20, ipady=5, pady=(2,10))

        lbl(s, "Descripción (ej: Oferta del mes)", variante="suave",
            bg=C.superficie).pack(padx=20, anchor="w")
        e_desc = tk.Entry(s, font=F.normal, bg=C.superficie, fg=C.texto,
                          insertbackground=C.primario, relief="solid", bd=1)
        e_desc.pack(fill="x", padx=20, ipady=5, pady=(2,10))

        lbl(s, "Válida hasta (AAAA-MM-DD, opcional)", variante="suave",
            bg=C.superficie).pack(padx=20, anchor="w")
        e_hasta = tk.Entry(s, font=F.normal, bg=C.superficie, fg=C.texto,
                           insertbackground=C.primario, relief="solid", bd=1)
        e_hasta.pack(fill="x", padx=20, ipady=5, pady=(2,4))

        def _aplicar():
            if modo.get() == "todos":
                ids = [p["id"] for p in todos_productos]
            elif modo.get() == "categoria":
                cat_nombre = combo_cat.get()
                cat_id = cat_map.get(cat_nombre)
                if not cat_id:
                    messagebox.showinfo("Atención", "Elegí una categoría.",
                                        parent=d)
                    return
                ids = [p["id"] for p in todos_productos
                      if p.get("categoria") == cat_nombre]
            else:
                ids = [int(i) for i in tree_multi.selection()]
                if not ids:
                    messagebox.showinfo(
                        "Atención",
                        "Elegí uno o más productos de la lista "
                        "(Ctrl+click para varios).", parent=d)
                    return

            if not ids:
                messagebox.showinfo("Atención",
                                    "No hay productos para esa selección.",
                                    parent=d)
                return

            try:
                pct = float(e_pct.get().replace(",", "."))
                if not (0 < pct < 100):
                    raise ValueError
            except ValueError:
                messagebox.showwarning(
                    "Error", "El descuento tiene que ser un número entre "
                    "0 y 100.", parent=d)
                return

            hasta = e_hasta.get().strip() or None
            if hasta:
                try:
                    datetime.strptime(hasta, "%Y-%m-%d")
                except ValueError:
                    messagebox.showwarning(
                        "Error", f"Fecha inválida: {hasta}", parent=d)
                    return

            desc = e_desc.get().strip() or f"Descuento {pct:g}%"

            if not messagebox.askyesno(
                    "Confirmar",
                    f"Aplicar {pct:g}% de descuento a {len(ids)} producto(s)?",
                    parent=d):
                return

            n = aplicar_promocion_bulk(ids, pct, desc, None, hasta)
            d.destroy()
            toast(self, f"Promoción aplicada a {n} producto(s)")
            import catalogo_web
            catalogo_web.sincronizar_stock_en_segundo_plano()
            self._refrescar_promos()

        btn(d, "Aplicar promoción", variante="exito", comando=_aplicar).grid(
            row=1, column=0, sticky="ew", padx=20, pady=16)

    def _editar_precio_inline(self, event=None):
        # Doble click en una fila puntual -> esa fila sola (con o sin
        # tildes marcadas, es una edición rápida de un solo producto).
        # Botón "Editar precio" (event=None) -> todos los tildados con
        # la columna de la izquierda, que es lo mismo que usan los
        # demás botones de acá abajo (antes usaba tree_p.selection(),
        # que es la fila resaltada nomás, no los tildados — por eso
        # con varios seleccionados solo tomaba uno).
        if event is not None:
            iid = self.tree_p.identify_row(event.y)
            ids_sel = [iid] if iid else []
        else:
            ids_sel = list(self._seleccionados)

        if not ids_sel:
            messagebox.showinfo("Atencion", "Selecciona uno o más productos con la columna de la izquierda.", parent=self)
            return
        prods = [self._filas.get(i) for i in ids_sel]
        prods = [p for p in prods if p]
        if not prods:
            return

        d = tk.Toplevel(self)
        d.title("Editar precio")
        _centrar(d, 400, 320)
        d.resizable(True, True)
        d.configure(bg=C.superficie)
        d.grab_set()

        if len(prods) == 1:
            lbl(d, prods[0]["descripcion"], variante="subtitulo",
                bg=C.superficie, wraplength=320).pack(pady=(16,2), padx=20, anchor="w")
            lbl(d, f"Costo actual: $ {prods[0]['costo_ultimo']:,.2f}", variante="suave",
                bg=C.superficie).pack(padx=20, anchor="w")
        else:
            lbl(d, f"{len(prods)} productos seleccionados", variante="subtitulo",
                bg=C.superficie).pack(pady=(16,2), padx=20, anchor="w")

        tipo = tk.StringVar(value="fijo")
        f_tipo = tk.Frame(d, bg=C.superficie)
        f_tipo.pack(fill="x", padx=20, pady=(10,0))

        f_valor = tk.Frame(d, bg=C.superficie)
        f_valor.pack(pady=10, padx=20, fill="x")

        lbl_campo = lbl(f_valor, "Nuevo precio $", bg=C.superficie)
        lbl_campo.pack(side="left")
        e = tk.Entry(f_valor, width=10, justify="right", font=("Segoe UI", 12),
                     bg=C.superficie, fg=C.texto, relief="solid", bd=1)
        if len(prods) == 1:
            e.insert(0, f"{prods[0]['precio_base']:.2f}")
        e.pack(side="left", padx=8, ipady=4)
        e.focus_set()
        e.select_range(0, "end")

        def _cambiar_tipo():
            if tipo.get() == "fijo":
                lbl_campo.config(text="Nuevo precio $")
                e.delete(0, "end")
                if len(prods) == 1:
                    e.insert(0, f"{prods[0]['precio_base']:.2f}")
            elif tipo.get() == "porcentaje":
                lbl_campo.config(text="Ajuste % (ej: 10 o -5)")
                e.delete(0, "end")
            else:
                lbl_campo.config(text="Margen % sobre el costo")
                e.delete(0, "end")
                if len(prods) == 1 and prods[0].get("margen_pct") is not None:
                    e.insert(0, f"{prods[0]['margen_pct']:.1f}")

        tk.Radiobutton(f_tipo, text="Precio fijo (mismo $ para todos)", variable=tipo,
                      value="fijo", bg=C.superficie, font=F.normal, anchor="w",
                      command=_cambiar_tipo).pack(fill="x", anchor="w")
        tk.Radiobutton(f_tipo, text="Ajuste % sobre el precio actual de cada uno",
                      variable=tipo, value="porcentaje",
                      bg=C.superficie, font=F.normal, anchor="w",
                      command=_cambiar_tipo).pack(fill="x", anchor="w")
        tk.Radiobutton(f_tipo, text="Margen % sobre el costo (fija el margen propio\n"
                      "y recalcula el precio de cada uno)",
                      variable=tipo, value="margen",
                      bg=C.superficie, font=F.normal, anchor="w", justify="left",
                      command=_cambiar_tipo).pack(fill="x", anchor="w")

        def ok(event=None):
            try:
                valor = float(e.get().replace(",", "."))
            except ValueError:
                messagebox.showwarning("Error", "Valor inválido.", parent=d)
                return

            if tipo.get() == "fijo":
                if valor <= 0:
                    messagebox.showwarning("Error", "El precio debe ser mayor a 0.", parent=d)
                    return
                # Vender bajo costo puede ser deliberado (liquidar algo por
                # vencer), pero por descuido es plata que se pierde en cada
                # venta sin que nada lo marque.
                bajo = [p for p in prods
                        if (p.get("costo_ultimo") or 0) > 0
                        and valor < p["costo_ultimo"]]
                if bajo:
                    if len(bajo) == 1:
                        b = bajo[0]
                        det = (f"«{b['descripcion']}» cuesta "
                               f"$ {b['costo_ultimo']:,.2f} y lo estás "
                               f"poniendo a $ {valor:,.2f}.\n\n"
                               f"Perdés $ {b['costo_ultimo'] - valor:,.2f} "
                               f"en cada unidad que vendas.")
                    else:
                        peor = max(bajo, key=lambda x: x["costo_ultimo"])
                        det = (f"{len(bajo)} de {len(prods)} productos quedan "
                               f"por debajo de su costo.\n\n"
                               f"El peor: «{peor['descripcion']}», cuesta "
                               f"$ {peor['costo_ultimo']:,.2f}.")
                    if not messagebox.askyesno(
                            "Precio por debajo del costo", det +
                            "\n\n¿Guardar igual?", parent=d):
                        return
                for p in prods:
                    actualizar_precio(p["id"], valor)
                msg = f"Precio actualizado a $ {valor:,.2f}" if len(prods) == 1 \
                    else f"{len(prods)} productos actualizados a $ {valor:,.2f}"
            elif tipo.get() == "porcentaje":
                ids = [p["id"] for p in prods]
                aplicar_aumento_bulk(ids, valor)
                self._avisar_bajo_costo(ids, d)
                signo = "+" if valor >= 0 else ""
                msg = f"Ajuste de {signo}{valor}% aplicado a {len(prods)} producto(s)"
            else:
                if valor < 0:
                    messagebox.showwarning("Error", "El margen no puede ser negativo.", parent=d)
                    return
                ids = [p["id"] for p in prods]
                sin_costo = [p for p in prods if not p.get("costo_ultimo")]
                aplicar_margen_nuevo_bulk(ids, valor)
                self._avisar_bajo_costo(ids, d)
                msg = f"Margen fijado en {valor}% para {len(prods)} producto(s)"
                if sin_costo:
                    msg += f" ({len(sin_costo)} sin costo cargado, no se les pudo recalcular el precio)"

            d.destroy()
            toast(self, msg)
            import catalogo_web
            catalogo_web.sincronizar_stock_en_segundo_plano()
            self._refrescar_tabla()

        e.bind("<Return>", ok)
        btn(d, "Guardar", variante="exito", comando=ok).pack(pady=(0,16))

    # ── Acciones promociones ──────────────────────────────────────────────────

    def _on_sel_promo(self, event):
        sel = self.tree_pr.selection()
        self._promo_sel_id = int(sel[0]) if sel else None

    def _nueva_promo(self):
        self._dialogo_promo(None)

    def _editar_promo(self):
        if not self._promo_sel_id:
            messagebox.showinfo("Atencion", "Selecciona una promocion.", parent=self)
            return
        promo = get_promocion_por_id(self._promo_sel_id)
        if promo:
            self._dialogo_promo(promo)

    def _dialogo_promo(self, promo=None):
        d = tk.Toplevel(self)
        d.title("Promocion" if promo else "Nueva promocion")
        _centrar(d, 460, 620)
        d.resizable(True, True)
        d.configure(bg=C.superficie)
        d.grab_set()
        d.columnconfigure(0, weight=1)
        d.rowconfigure(0, weight=1)

        outer, s = scrollable(d, bg=C.superficie)
        outer.grid(row=0, column=0, sticky="nsew")

        lbl(s, "Promocion por cantidad", variante="titulo",
            bg=C.superficie).pack(pady=(20,4), padx=20, anchor="w")
        lbl(s, "Ej: x3 unidades a $500 c/u — se aplica automaticamente al scanear",
            variante="suave", bg=C.superficie,
            wraplength=400).pack(padx=20, anchor="w", pady=(0,10))

        # ── Buscador de producto (con lista de resultados, no texto libre) ──
        lbl(s, "Producto *", variante="suave", bg=C.superficie).pack(
            padx=20, anchor="w")
        e_buscar = tk.Entry(s, font=F.normal, bg=C.superficie, fg=C.texto,
                            insertbackground=C.primario, relief="solid", bd=1)
        e_buscar.pack(fill="x", padx=20, ipady=5, pady=(2,4))

        f_resultados = card(s)
        f_resultados.pack(fill="x", padx=20)
        f_resultados.columnconfigure(0, weight=1)
        tree_prod = ttk.Treeview(f_resultados, columns=("codigo","desc"),
                                 show="headings", height=4, selectmode="browse")
        tree_prod.heading("codigo", text="Codigo")
        tree_prod.heading("desc", text="Producto")
        tree_prod.column("codigo", width=100, anchor="w")
        tree_prod.column("desc", width=260, anchor="w")
        tree_prod.grid(row=0, column=0, sticky="nsew", padx=(4,0), pady=4)
        sb_prod = ttk.Scrollbar(f_resultados, orient="vertical", command=tree_prod.yview)
        tree_prod.configure(yscrollcommand=sb_prod.set)
        sb_prod.grid(row=0, column=1, sticky="ns", pady=4)

        lbl_elegido = lbl(s, "Ningún producto elegido todavía",
                          variante="suave", bg=C.superficie)
        lbl_elegido.pack(padx=20, anchor="w", pady=(2,10))

        self._prod_promo_id = None
        self._prod_promo_map = {}

        def _buscar(evento=None):
            for r in tree_prod.get_children():
                tree_prod.delete(r)
            self._prod_promo_map.clear()
            texto = e_buscar.get().strip()
            if not texto:
                return
            for p in get_productos(filtro=texto)[:20]:
                self._prod_promo_map[p["codigo"]] = p
                tree_prod.insert("", "end", iid=p["codigo"],
                                values=(p["codigo"], p["descripcion"]))

        def _elegir(evento=None):
            sel = tree_prod.selection()
            if not sel:
                return
            p = self._prod_promo_map.get(sel[0])
            if p:
                self._prod_promo_id = p["id"]
                lbl_elegido.configure(
                    text=f"Producto elegido: {p['descripcion']} ({p['codigo']})",
                    fg=C.exito)

        e_buscar.bind("<KeyRelease>", _buscar)
        tree_prod.bind("<<TreeviewSelect>>", _elegir)
        tree_prod.bind("<Double-1>", _elegir)

        campos = [
            ("Descripcion (ej: Pack x3)",    "entry_pr_desc",  ""),
            ("Cantidad minima *",             "entry_pr_cant",  "3"),
        ]

        for label, attr, default in campos:
            lbl(s, label, variante="suave", bg=C.superficie).pack(
                padx=20, anchor="w", pady=(6,0))
            e = tk.Entry(s, font=F.normal, bg=C.superficie, fg=C.texto,
                         insertbackground=C.primario, relief="solid", bd=1)
            if promo:
                if attr == "entry_pr_desc":   e.insert(0, promo["descripcion"] or "")
                elif attr == "entry_pr_cant":   e.insert(0, str(promo["cantidad_minima"]))
            else:
                e.insert(0, default)
            e.pack(fill="x", padx=20, ipady=5, pady=(2,0))
            setattr(self, attr, e)

        # -- Tipo de descuento: precio fijo por unidad, o % sobre el
        #    precio de lista. El % se recalcula solo si mas adelante
        #    cambias el precio del producto.
        tipo_valor_inicial = "porcentaje" if (promo and promo.get("tipo_descuento") == "porcentaje") else "precio_fijo"
        self._tipo_promo = tk.StringVar(value=tipo_valor_inicial)

        lbl(s, "Tipo de descuento *", variante="suave", bg=C.superficie).pack(
            padx=20, anchor="w", pady=(10,0))
        f_tipo = tk.Frame(s, bg=C.superficie)
        f_tipo.pack(fill="x", padx=20, pady=(2,0))

        f_precio_fijo = tk.Frame(s, bg=C.superficie)
        f_porcentaje = tk.Frame(s, bg=C.superficie)

        lbl(f_precio_fijo, "Precio por unidad *", variante="suave",
            bg=C.superficie).pack(anchor="w")
        e_precio = tk.Entry(f_precio_fijo, font=F.normal, bg=C.superficie, fg=C.texto,
                            insertbackground=C.primario, relief="solid", bd=1)
        e_precio.pack(fill="x", ipady=5, pady=(2,0))
        self.entry_pr_precio = e_precio

        lbl(f_porcentaje, "% de descuento sobre el precio de lista *",
            variante="suave", bg=C.superficie).pack(anchor="w")
        e_pct = tk.Entry(f_porcentaje, font=F.normal, bg=C.superficie, fg=C.texto,
                         insertbackground=C.primario, relief="solid", bd=1)
        e_pct.pack(fill="x", ipady=5, pady=(2,0))
        self.entry_pr_pct = e_pct

        if promo:
            if promo.get("tipo_descuento") == "porcentaje":
                e_pct.insert(0, f"{promo.get('porcentaje_descuento') or 0:.2f}")
            else:
                e_precio.insert(0, f"{promo['precio_unitario']:.2f}")

        def _mostrar_tipo(*_a):
            if self._tipo_promo.get() == "porcentaje":
                f_precio_fijo.pack_forget()
                f_porcentaje.pack(fill="x", padx=20, pady=(8,0))
            else:
                f_porcentaje.pack_forget()
                f_precio_fijo.pack(fill="x", padx=20, pady=(8,0))

        tk.Radiobutton(f_tipo, text="Precio fijo por unidad", variable=self._tipo_promo,
                      value="precio_fijo", bg=C.superficie, font=F.normal, anchor="w",
                      command=_mostrar_tipo).pack(fill="x", anchor="w")
        tk.Radiobutton(f_tipo, text="% de descuento (ej: llevando 3 o mas, 5% off)",
                      variable=self._tipo_promo, value="porcentaje",
                      bg=C.superficie, font=F.normal, anchor="w",
                      command=_mostrar_tipo).pack(fill="x", anchor="w")

        _mostrar_tipo()

        campos_fecha = [
            ("Fecha desde (AAAA-MM-DD)",      "entry_pr_desde", ""),
            ("Fecha hasta (AAAA-MM-DD)",      "entry_pr_hasta", ""),
        ]
        for label, attr, default in campos_fecha:
            lbl(s, label, variante="suave", bg=C.superficie).pack(
                padx=20, anchor="w", pady=(10,0))
            e = tk.Entry(s, font=F.normal, bg=C.superficie, fg=C.texto,
                         insertbackground=C.primario, relief="solid", bd=1)
            if promo:
                if attr == "entry_pr_desde":  e.insert(0, promo["fecha_desde"] or "")
                elif attr == "entry_pr_hasta":  e.insert(0, promo["fecha_hasta"] or "")
            else:
                e.insert(0, default)
            e.pack(fill="x", padx=20, ipady=5, pady=(2,0))
            setattr(self, attr, e)

        if promo:
            # Precargar el producto ya asociado a esta promoción
            codigo_actual = get_codigo_producto(promo["producto_id"])
            desc_actual = None
            for p in get_productos(filtro=codigo_actual or ""):
                if p["id"] == promo["producto_id"]:
                    desc_actual = p["descripcion"]
                    break
            self._prod_promo_id = promo["producto_id"]
            if codigo_actual:
                e_buscar.insert(0, codigo_actual)
            lbl_elegido.configure(
                text=f"Producto elegido: {desc_actual or '(sin cambios)'} "
                    f"({codigo_actual or '?'})", fg=C.exito)

        def guardar(event=None):
            pid = self._prod_promo_id
            if not pid:
                messagebox.showwarning(
                    "Error",
                    "Buscá el producto por código o nombre y elegilo de la "
                    "lista antes de guardar.", parent=d)
                return
            try:
                cant = int(self.entry_pr_cant.get())
                if cant <= 0: raise ValueError
            except ValueError:
                messagebox.showwarning("Error", "Cantidad debe ser un numero valido.", parent=d)
                return

            tipo = self._tipo_promo.get()
            porcentaje = None
            if tipo == "porcentaje":
                try:
                    porcentaje = float(self.entry_pr_pct.get().replace(",", "."))
                    if not (0 < porcentaje < 100): raise ValueError
                except ValueError:
                    messagebox.showwarning(
                        "Error", "El % de descuento debe ser un numero entre 0 y 100.", parent=d)
                    return
                from repositorio import get_producto_completo
                prod = get_producto_completo(pid)
                precio_base = prod["precio_base"] if prod else 0.0
                precio = round(precio_base * (1 - porcentaje / 100), 2)
            else:
                try:
                    precio = float(self.entry_pr_precio.get().replace(",", "."))
                    if precio <= 0: raise ValueError
                except ValueError:
                    messagebox.showwarning("Error", "El precio debe ser un numero valido.", parent=d)
                    return

            desde = self.entry_pr_desde.get().strip() or None
            hasta = self.entry_pr_hasta.get().strip() or None
            for fecha in [f for f in [desde, hasta] if f]:
                try:    datetime.strptime(fecha, "%Y-%m-%d")
                except ValueError: messagebox.showwarning("Error", f"Fecha invalida: {fecha}", parent=d); return

            guardar_promocion(
                promo["id"] if promo else None,
                pid, cant, precio,
                self.entry_pr_desc.get().strip(),
                desde, hasta,
                tipo_descuento=tipo, porcentaje=porcentaje,
            )
            d.destroy()
            toast(self, "Promocion guardada")
            import catalogo_web
            catalogo_web.sincronizar_stock_en_segundo_plano()
            self._refrescar_promos()

        btn(d, "Guardar promocion", variante="exito", comando=guardar).grid(
            row=1, column=0, sticky="ew", padx=20, pady=16)

    def _toggle_promo(self):
        if not self._promo_sel_id:
            messagebox.showinfo("Atencion", "Selecciona una promocion.", parent=self)
            return
        promo = get_promocion_por_id(self._promo_sel_id)
        if promo:
            toggle_promocion(self._promo_sel_id, 0 if promo["activa"] else 1)
            import catalogo_web
            catalogo_web.sincronizar_stock_en_segundo_plano()
            self._refrescar_promos()

    def _eliminar_promo(self):
        if not self._promo_sel_id:
            messagebox.showinfo("Atencion", "Selecciona una promocion.", parent=self)
            return
        if messagebox.askyesno("Eliminar", "Eliminar esta promocion?", parent=self):
            eliminar_promocion(self._promo_sel_id)
            self._promo_sel_id = None
            toast(self, "Promocion eliminada")
            import catalogo_web
            catalogo_web.sincronizar_stock_en_segundo_plano()
            self._refrescar_promos()

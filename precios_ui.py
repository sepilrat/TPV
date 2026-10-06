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
                         aplicar_margen_bulk, get_promocion_por_id, get_codigo_producto,
                         modificar_promociones_bulk,
                         margen_sobre_costo, margen_promocion, costo_real_producto,
                         margen_minimo_promo_pct, desactivar_promos_obsoletas)

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
    ("sel",     "",              30,  "center"),
    ("desc",    "Producto",     190, "w"),
    ("detalle", "Descripcion",  130, "w"),
    ("cant",    "Desde cant.",   80, "e"),
    ("precio",  "Precio/Desc.",  85, "e"),
    ("margen",  "Margen s/costo", 150, "e"),
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
        self._seleccionados = set()   # ids seleccionados para bulk (precios)
        self._promo_sel_id = None
        self._promos_seleccionadas = set()   # ids seleccionados para bulk (promos)
        self._promos_filas = {}              # iid -> promo dict (para filtrar)
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
        f_cupones = ttk.Frame(nb)
        nb.add(f_precios, text="  Actualizar precios  ")
        nb.add(f_promos,  text="  Promociones  ")
        nb.add(f_cupones, text="  Cupones  ")

        self._build_precios(f_precios)
        self._build_promos(f_promos)
        self._build_cupones(f_cupones)

    # ── Tab Cupones ───────────────────────────────────────────────────────────

    _ESTADO_CUPON = {"activo": "Activo", "usado": "Usado", "vencido": "Vencido",
                     "anulado": "Anulado", "todavia_no": "Aún no vale"}

    def _build_cupones(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)

        bar = tk.Frame(parent, bg=C.bg)
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        btn(bar, "➕  Nuevo cupón", variante="exito",
            comando=self._dialogo_cupon).pack(side="left")
        btn(bar, "📋  Copiar para WhatsApp", variante="neutro",
            comando=self._copiar_cupon).pack(side="left", padx=(8, 0))
        btn(bar, "🚫  Anular", variante="peligro",
            comando=self._anular_cupon).pack(side="left", padx=(8, 0))
        self._solo_vigentes = tk.BooleanVar(value=True)
        tk.Checkbutton(bar, text="Solo los vigentes", variable=self._solo_vigentes,
                       bg=C.bg, fg=C.texto, font=F.normal, selectcolor=C.bg,
                       activebackground=C.bg, command=self._refrescar_cupones
                       ).pack(side="left", padx=(16, 0))
        self.lbl_cupones = lbl(bar, "", variante="suave")
        self.lbl_cupones.pack(side="right")

        cols = [("codigo", "Código", 110, "w"), ("categoria", "Categoría", 150, "w"),
                ("monto", "Monto", 90, "e"), ("resta", "Resta", 90, "e"),
                ("hasta", "Vence", 90, "center"), ("estado", "Estado", 100, "center"),
                ("saldo", "Saldo", 60, "center"), ("nota", "Nota", 220, "w")]
        frame_t, self.tree_cup = tabla(parent, cols, altura=14)
        frame_t.grid(row=1, column=0, sticky="nsew")
        self.tree_cup.tag_configure("activo", foreground=C.exito)
        self.tree_cup.tag_configure("usado", foreground=C.texto_suave)
        self.tree_cup.tag_configure("vencido", foreground=C.advertencia)
        self.tree_cup.tag_configure("anulado", foreground=C.peligro)
        self.tree_cup.tag_configure("todavia_no", foreground=C.primario)
        self.tree_cup.bind("<Double-1>", lambda e: self._copiar_cupon())
        self._cupones_filas = {}
        self._refrescar_cupones()

    def _refrescar_cupones(self):
        from repositorio import listar_cupones
        for r in self.tree_cup.get_children():
            self.tree_cup.delete(r)
        self._cupones_filas = {}
        todos = listar_cupones()
        n_act = sum(1 for c in todos if c["estado"] == "activo")
        pend = sum(c["monto_restante"] for c in todos if c["estado"] == "activo")
        for c in todos:
            if self._solo_vigentes.get() and c["estado"] not in ("activo", "todavia_no"):
                continue
            hasta = c["fecha_hasta"][:10]
            self.tree_cup.insert("", "end", iid=str(c["id"]), tags=(c["estado"],), values=(
                c["codigo"], c["categoria"], f"$ {c['monto']:,.2f}",
                f"$ {c['monto_restante']:,.2f}",
                f"{hasta[8:10]}/{hasta[5:7]}/{hasta[:4]}",
                self._ESTADO_CUPON[c["estado"]], "sí" if c["permite_saldo"] else "no",
                c["nota"] or ""))
            self._cupones_filas[str(c["id"])] = c
        self.lbl_cupones.config(
            text=f"{n_act} vigente(s) · $ {pend:,.2f} comprometidos en cupones")

    def _cupon_elegido(self):
        sel = self.tree_cup.selection()
        if not sel:
            messagebox.showinfo("Cupones", "Elegí un cupón de la lista.", parent=self)
            return None
        return self._cupones_filas.get(sel[0])

    def _copiar_cupon(self):
        c = self._cupon_elegido()
        if not c:
            return
        from repositorio import texto_cupon
        from config import cfg
        self.clipboard_clear()
        self.clipboard_append(texto_cupon(c, cfg().get("negocio_nombre") or ""))
        toast(self, "Texto del cupón copiado: pegalo en WhatsApp")

    def _anular_cupon(self):
        c = self._cupon_elegido()
        if not c:
            return
        if c["estado"] in ("anulado", "usado"):
            messagebox.showinfo("Cupones", f"Ese cupón ya está {c['estado']}.", parent=self)
            return
        if not messagebox.askyesno(
                "Anular cupón",
                f"¿Anular el cupón {c['codigo']} (quedan $ {c['monto_restante']:,.2f})?\n\n"
                "Deja de valer desde ya. Lo que ya se usó no cambia.",
                icon="warning", default="no", parent=self):
            return
        from fiado_ui import pedir_autorizacion
        from repositorio import anular_cupon, registrar_bitacora
        resp = pedir_autorizacion(self, "Anular un cupón requiere autorización del responsable.")
        if not resp:
            return
        anular_cupon(c["id"], f"Anulado por {resp}")
        registrar_bitacora("Cupón anulado", resp,
                           f"{c['codigo']} (restaban $ {c['monto_restante']:,.2f})")
        toast(self, f"Cupón {c['codigo']} anulado")
        self._refrescar_cupones()

    def _dialogo_cupon(self):
        from datetime import date, timedelta
        from repositorio import crear_cupon, get_categorias, texto_cupon
        from config import cfg
        d = tk.Toplevel(self)
        d.title("Nuevo cupón")
        d.configure(bg=C.superficie)
        d.grab_set()
        _centrar(d, 440, 520)
        lbl(d, "Nuevo cupón", variante="titulo", bg=C.superficie).pack(
            anchor="w", padx=20, pady=(16, 2))
        tk.Label(d, bg=C.superficie, fg=C.texto_suave, font=F.pequeña, justify="left",
                 wraplength=400, anchor="w",
                 text="Un monto en $ que el cliente gasta comprando productos de una "
                      "categoría, hasta una fecha."
                 ).pack(fill="x", padx=20)

        def campo(texto, ancho=None):
            lbl(d, texto, variante="suave", bg=C.superficie).pack(anchor="w", padx=20, pady=(10, 0))
            e = tk.Entry(d, font=F.normal, bg=C.superficie, fg=C.texto, relief="solid", bd=1)
            e.pack(fill="x", padx=20, ipady=4)
            return e

        e_monto = campo("Monto del cupón ($)")
        lbl(d, "Categoría en la que se puede usar", variante="suave",
            bg=C.superficie).pack(anchor="w", padx=20, pady=(10, 0))
        cats = get_categorias()
        nombres = ["(cualquier producto)"] + [c["nombre"] for c in cats]
        v_cat = tk.StringVar(value=nombres[0])
        ttk.Combobox(d, textvariable=v_cat, values=nombres, state="readonly").pack(
            fill="x", padx=20, ipady=3)
        e_hasta = campo("Válido hasta (dd/mm/aaaa)")
        e_hasta.insert(0, (date.today() + timedelta(days=30)).strftime("%d/%m/%Y"))
        e_nota = campo("Nota (para quién es, opcional)")
        e_cod = campo("Código (vacío = se genera solo)")
        v_saldo = tk.BooleanVar(value=False)
        tk.Checkbutton(d, text="Permitir usar el saldo en otra compra", variable=v_saldo,
                       bg=C.superficie, fg=C.texto, font=F.normal, selectcolor=C.superficie,
                       activebackground=C.superficie).pack(anchor="w", padx=18, pady=(10, 0))
        tk.Label(d, bg=C.superficie, fg=C.texto_suave, font=F.pequeña, justify="left",
                 wraplength=400, anchor="w",
                 text="Si no se tilda, el cupón se usa en una sola compra: aunque gaste "
                      "menos que el monto, el resto se pierde."
                 ).pack(fill="x", padx=20)
        e_monto.focus_set()

        def parse_monto(t):
            t = t.strip().replace("$", "").replace(" ", "")
            if "," in t:
                t = t.replace(".", "").replace(",", ".")
            elif t.count(".") > 1 or (t.count(".") == 1 and len(t.rsplit(".", 1)[1]) == 3):
                t = t.replace(".", "")
            return float(t)

        def crear():
            try:
                monto = parse_monto(e_monto.get())
            except ValueError:
                messagebox.showwarning("Cupón", "El monto no es un número.", parent=d)
                return
            from datetime import datetime as _dt
            t = e_hasta.get().strip().replace("-", "/").replace(".", "/")
            hasta = None
            for fmt in ("%d/%m/%Y", "%d/%m/%y"):
                try:
                    hasta = _dt.strptime(t, fmt).strftime("%Y-%m-%d")
                    break
                except ValueError:
                    pass
            if not hasta:
                messagebox.showwarning("Cupón", "La fecha no es válida. Usá dd/mm/aaaa.", parent=d)
                return
            cat_id = None
            if v_cat.get() != nombres[0]:
                cat_id = next(c["id"] for c in cats if c["nombre"] == v_cat.get())
            try:
                c = crear_cupon(monto, cat_id, hasta, codigo=e_cod.get() or None,
                                permite_saldo=v_saldo.get(), nota=e_nota.get())
            except ValueError as exc:
                messagebox.showwarning("Cupón", str(exc), parent=d)
                return
            d.destroy()
            self._refrescar_cupones()
            if self.tree_cup.exists(str(c["id"])):
                self.tree_cup.selection_set(str(c["id"]))
            self.clipboard_clear()
            self.clipboard_append(texto_cupon(c, cfg().get("negocio_nombre") or ""))
            messagebox.showinfo(
                "Cupón creado",
                f"Código: {c['codigo']}\n\nEl texto para mandar por WhatsApp ya quedó "
                "copiado: pegalo en el chat.", parent=self)

        e_cod.bind("<Return>", lambda e: crear())
        pie = tk.Frame(d, bg=C.superficie)
        pie.pack(pady=14)
        btn(pie, "Crear cupón", variante="exito", comando=crear).pack(side="left", padx=6)
        btn(pie, "Cancelar", variante="neutro", comando=d.destroy).pack(side="left", padx=6)

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
        parent.rowconfigure(1, weight=1)

        # Filtros — mismo patron que la pestaña de Precios: buscar +
        # selec./desel. todo, para no tener que ir clickeando promo por
        # promo cuando hay muchas.
        bar = tk.Frame(parent, bg=C.bg)
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 6))

        lbl(bar, "Buscar:").pack(side="left", padx=(0, 6))
        self.entry_buscar_promo = tk.Entry(bar, font=F.normal, width=24,
                                           bg=C.superficie, fg=C.texto,
                                           insertbackground=C.primario,
                                           relief="solid", bd=1)
        self.entry_buscar_promo.pack(side="left", ipady=5)
        self.entry_buscar_promo.bind(
            "<KeyRelease>", lambda e: self._refrescar_promos())

        btn(bar, "Selec. todo", variante="neutro",
            comando=self._promos_sel_todo).pack(side="left", padx=(12, 0))
        btn(bar, "Desel. todo", variante="neutro",
            comando=self._promos_desel_todo).pack(side="left", padx=6)

        lbl(bar, "Seleccionadas:", variante="suave").pack(
            side="left", padx=(12, 4))
        self.lbl_sel_promo = lbl(bar, "0", variante="badge")
        self.lbl_sel_promo.pack(side="left")

        self._solo_problemas = tk.BooleanVar(value=False)
        tk.Checkbutton(bar, text="Solo con problemas de margen",
                       variable=self._solo_problemas, bg=C.bg, fg=C.texto,
                       font=F.normal, selectcolor=C.bg, activebackground=C.bg,
                       command=self._refrescar_promos).pack(side="left", padx=(14, 0))
        self.lbl_alerta_promos = tk.Label(bar, text="", bg=C.bg, font=F.normal)
        self.lbl_alerta_promos.pack(side="left", padx=(14, 0))
        self.btn_apagar_obsoletas = btn(bar, "Apagar las que no convienen",
                                        variante="peligro",
                                        comando=self._apagar_promos_obsoletas)

        # Tabla
        frame_t, self.tree_pr = tabla(parent, COLS_PROMOS)
        frame_t.grid(row=1, column=0, sticky="nsew", pady=(0, 8))
        self.tree_pr.bind("<ButtonRelease-1>", self._on_click_tabla_promo)
        self.tree_pr.bind("<Double-1>", lambda e: self._editar_promo())

        # Acciones
        # DOS filas: ocho botones en una sola no entraban a lo ancho y
        # los ultimos quedaban cortados fuera de la pantalla (asi se
        # habia "perdido" el de Placas y el de Actualizar).
        # Arriba lo que opera sobre las promociones; abajo, lo que
        # exporta hacia afuera.
        ac = tk.Frame(parent, bg=C.bg)
        ac.grid(row=2, column=0, sticky="ew")

        btn(ac, "➕  Nueva promocion",  variante="exito",   comando=self._nueva_promo).pack(side="left")
        btn(ac, "✏️  Editar",           variante="primario", comando=self._editar_promo).pack(side="left", padx=6)
        btn(ac, "📊  Promoción masiva", variante="exito",
            comando=self._dialogo_promocion_masiva).pack(side="left", padx=6)
        btn(ac, "⏸  Pausar/Activar",   variante="neutro",   comando=self._toggle_promo).pack(side="left")
        btn(ac, "🗑  Eliminar",         variante="peligro",  comando=self._eliminar_promo).pack(side="left", padx=6)
        btn(ac, "🔄  Actualizar",       variante="neutro",   comando=self._refrescar_promos).pack(side="right")

        # Panel de modificacion masiva: pensado para cuando ya hay
        # muchas promos cargadas y hay que ajustarlas a todas juntas
        # (por ejemplo, subir un 5% mas de descuento a las que ya
        # tenian, o poner el mismo precio fijo a varias a la vez).
        bulk_pr = card(parent)
        bulk_pr.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        bulk_pr.columnconfigure(6, weight=1)

        lbl(bulk_pr, "Sobre las seleccionadas:", variante="suave",
            bg=C.superficie).grid(row=0, column=0, padx=(16, 8), pady=12, sticky="w")

        lbl(bulk_pr, "Sumar puntos % de desc.", variante="suave",
            bg=C.superficie).grid(row=0, column=1, padx=(0, 4))
        self.entry_promo_sumar = tk.Entry(bulk_pr, width=6, justify="center",
                                          font=F.normal, bg=C.superficie,
                                          fg=C.texto, relief="solid", bd=1)
        self.entry_promo_sumar.insert(0, "5")
        self.entry_promo_sumar.grid(row=0, column=2, ipady=5)
        btn(bulk_pr, "Aplicar", variante="primario",
            comando=self._promos_sumar_pct).grid(row=0, column=3, padx=(4, 12))

        lbl(bulk_pr, "Fijar precio $", variante="suave",
            bg=C.superficie).grid(row=0, column=4, padx=(0, 4))
        self.entry_promo_precio = tk.Entry(bulk_pr, width=9, justify="center",
                                           font=F.normal, bg=C.superficie,
                                           fg=C.texto, relief="solid", bd=1)
        self.entry_promo_precio.grid(row=0, column=5, ipady=5)
        btn(bulk_pr, "Aplicar", variante="primario",
            comando=self._promos_fijar_precio).grid(row=0, column=6, padx=(4, 8), sticky="w")
        btn(bulk_pr, "Pasar a % …", variante="neutro",
            comando=self._promos_a_porcentaje).grid(row=0, column=7, padx=(8, 12), sticky="e")

        ac2 = tk.Frame(parent, bg=C.bg)
        ac2.grid(row=4, column=0, sticky="ew", pady=(6, 0))
        lbl(ac2, "Exportar:", variante="suave").pack(side="left", padx=(0, 8))
        btn(ac2, "📄  Lista de precios", variante="neutro",
            comando=self._exportar_lista_precios).pack(side="left", padx=(0, 6))
        btn(ac2, "🗞️  Folleto de ofertas", variante="neutro",
            comando=self._exportar_folleto).pack(side="left", padx=6)
        btn(ac2, "📱  Placas para estados", variante="neutro",
            comando=self._placas_estados).pack(side="left", padx=6)
        btn(ac2, "🛒  Ofertas de la semana", variante="neutro",
            comando=self._ofertas_semana).pack(side="left", padx=6)

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

    def _ofertas_semana(self):
        """Flyer 'Ofertas de la semana' (hasta 9 productos) en PNG."""
        from ofertas_semana import abrir_selector_ofertas
        abrir_selector_ofertas(self)

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

    @staticmethod
    def _es_obsoleta(pr):
        """Precio fijo que ya no mejora el precio de lista (se bajo el precio)."""
        return (pr.get("tipo_descuento") != "porcentaje"
                and float(pr["precio_unitario"] or 0) >= float(pr["precio_base"] or 0) - 0.005)

    def _apagar_promos_obsoletas(self):
        from repositorio import promos_obsoletas
        obs = promos_obsoletas()
        if not obs:
            return
        lineas = [f"• {o['descripcion'][:34]}: x{o['cantidad_minima']} a "
                  f"$ {o['precio_promo']:,.2f} (el producto está a $ {o['precio_base']:,.2f})"
                  for o in obs[:10]]
        if len(obs) > 10:
            lineas.append(f"… y {len(obs) - 10} más")
        if not messagebox.askyesno(
                "Apagar promociones que no convienen",
                f"Estas {len(obs)} promociones tienen un precio igual o MÁS ALTO que el "
                "precio normal del producto:\n\n" + "\n".join(lineas) +
                "\n\nSe apagan (no se borran): podés editarlas y volver a activarlas "
                "con el precio correcto.\n\n¿Apagarlas?", parent=self):
            return
        n = desactivar_promos_obsoletas([o["id"] for o in obs])
        toast(self, f"{n} promoción(es) apagada(s)")
        self._refrescar_promos()

    @staticmethod
    def _txt_margen(m):
        if m["nivel"] == "sin_costo":
            return "sin costo cargado"
        signo = "-" if m["margen"] < 0 else ""
        txt = (f"{signo}$ {abs(m['margen']):,.2f}  ({m['pct']:+.1f}%)")
        return ("⚠ " + txt) if m["nivel"] in ("perdida", "bajo") else txt

    def _refrescar_promos(self):
        filtro = self.entry_buscar_promo.get().strip().lower()
        solo_prob = self._solo_problemas.get()
        self._promos_seleccionadas.clear()
        self.lbl_sel_promo.config(text="0")
        for r in self.tree_pr.get_children():
            self.tree_pr.delete(r)
        self._promos_filas = {}
        n_perdida = n_bajo = n_obsoletas = 0
        for pr in get_promociones():
            if filtro and filtro not in (
                    f"{pr['descripcion']} {pr['codigo']} "
                    f"{pr['detalle'] or ''}").lower():
                continue
            m = margen_promocion(pr)
            obsoleta = bool(pr["activa"]) and self._es_obsoleta(pr)
            if obsoleta:
                n_obsoletas += 1
            if pr["activa"] and m["nivel"] == "perdida":
                n_perdida += 1
            elif pr["activa"] and m["nivel"] == "bajo":
                n_bajo += 1
            if solo_prob and not obsoleta and m["nivel"] not in ("perdida", "bajo"):
                continue
            if pr.get("tipo_descuento") == "porcentaje":
                col_precio = f"-{pr.get('porcentaje_descuento') or 0:.1f}%"
            else:
                col_precio = f"$ {pr['precio_unitario']:,.2f}"
            if not pr["activa"]:
                tag = "inactiva"
            elif obsoleta:
                tag = "obsoleta"
            else:
                tag = {"perdida": "perdida", "bajo": "bajo",
                       "sin_costo": "sin_costo"}.get(m["nivel"], "activa")
            iid = str(pr["id"])
            self.tree_pr.insert("", "end", iid=iid, values=(
                "",
                pr["descripcion"],
                pr["detalle"] or "—",
                f"x {pr['cantidad_minima']}",
                col_precio,
                ("⚠ NO CONVIENE: igual o más cara que el precio normal"
                 if obsoleta else self._txt_margen(m)),
                pr["fecha_desde"] or "—",
                pr["fecha_hasta"] or "—",
                "Si" if pr["activa"] else "No",
            ), tags=(tag,))
            self._promos_filas[iid] = pr
        self.tree_pr.tag_configure("activa",    foreground=C.exito)
        self.tree_pr.tag_configure("inactiva",  foreground=C.texto_suave)
        self.tree_pr.tag_configure("perdida",   foreground=C.peligro)
        self.tree_pr.tag_configure("obsoleta",  foreground=C.peligro)
        self.tree_pr.tag_configure("bajo",      foreground=C.advertencia)
        self.tree_pr.tag_configure("sin_costo", foreground=C.texto_suave)
        if n_obsoletas:
            self.lbl_alerta_promos.config(
                text=f"⚠ {n_obsoletas} promo(s) activa(s) NO CONVIENEN: salen igual o "
                     "más caras que el precio normal (la caja no las aplica)",
                fg=C.peligro)
            self.btn_apagar_obsoletas.pack(side="left", padx=(10, 0))
        elif n_perdida:
            self.btn_apagar_obsoletas.pack_forget()
            self.lbl_alerta_promos.config(
                text=f"⚠ {n_perdida} promo(s) activa(s) venden BAJO COSTO"
                     + (f"  ·  {n_bajo} con margen bajo" if n_bajo else ""),
                fg=C.peligro)
        elif n_bajo:
            self.btn_apagar_obsoletas.pack_forget()
            self.lbl_alerta_promos.config(
                text=f"⚠ {n_bajo} promo(s) activa(s) con margen bajo "
                     f"(menos de {margen_minimo_promo_pct():g}%)", fg=C.advertencia)
        else:
            self.btn_apagar_obsoletas.pack_forget()
            self.lbl_alerta_promos.config(text="", fg=C.exito)

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
        # Buscador: con cientos de productos, elegir de a uno scrolleando
        # la lista entera es impracticable.
        f_busq = tk.Frame(f_lista, bg=C.superficie)
        v_busq = tk.StringVar()
        e_busq = tk.Entry(f_busq, textvariable=v_busq, font=F.normal,
                          bg=C.bg, fg=C.texto, relief="solid", bd=1)
        e_busq.pack(side="left", fill="x", expand=True, ipady=3)
        lbl_lista_ayuda = lbl(
            f_lista, "Buscá y usá «Elegir los visibles» — o Ctrl+click "
                     "para elegir de a uno",
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

        def _llenar_lista(*_a):
            """Filtra por texto sin perder lo que ya estaba elegido."""
            elegidos = set(tree_multi.selection())
            q = v_busq.get().strip().lower()
            partes = [x for x in q.split() if x]
            tree_multi.delete(*tree_multi.get_children())
            for p in todos_productos:
                if partes:
                    txt = (f"{p['descripcion']} {p.get('marca') or ''} "
                           f"{p.get('categoria') or ''} "
                           f"{p.get('codigo') or ''}").lower()
                    if not all(x in txt for x in partes):
                        continue
                tree_multi.insert("", "end", iid=str(p["id"]),
                                  values=(p["descripcion"],
                                          p.get("categoria") or "—",
                                          f"$ {p['precio_base']:,.2f}"))
            # Lo elegido se mantiene aunque el filtro lo oculte y vuelva
            vivos = [i for i in elegidos if tree_multi.exists(i)]
            if vivos:
                tree_multi.selection_set(vivos)

        def _elegir_visibles():
            tree_multi.selection_add(*tree_multi.get_children())

        btn(f_busq, "☑ Elegir los visibles", variante="neutro",
            comando=_elegir_visibles).pack(side="left", padx=6)
        btn(f_busq, "Ninguno", variante="neutro",
            comando=lambda: tree_multi.selection_remove(
                *tree_multi.selection())).pack(side="left")
        v_busq.trace_add("write", _llenar_lista)
        _llenar_lista()

        def _actualizar_modo():
            combo_cat.pack_forget()
            f_lista.pack_forget()
            f_busq.grid_forget()
            lbl_lista_ayuda.grid_forget()
            tree_multi.grid_forget()
            sb_multi.grid_forget()
            if modo.get() == "categoria":
                combo_cat.pack(fill="x", padx=20, pady=(4,10), ipady=3)
            elif modo.get() == "elegir":
                f_busq.grid(row=0, column=0, columnspan=2, sticky="ew",
                            padx=4, pady=(4, 2))
                lbl_lista_ayuda.grid(row=1, column=0, columnspan=2,
                                     sticky="w", padx=4)
                tree_multi.grid(row=2, column=0, sticky="nsew",
                                padx=(4,0), pady=4)
                sb_multi.grid(row=2, column=1, sticky="ns", pady=4)
                f_lista.rowconfigure(2, weight=1)
                f_lista.pack(fill="both", expand=True, padx=20, pady=(4,10))

        _actualizar_modo()

        # Tres formas de armar la promo. El precio fijo es el que faltaba:
        # "llevando 3, a $3.200 cada uno" no se puede expresar con un %.
        _TIPOS = {"pct": "Descuento %",
                  "monto": "Descuento en $ por unidad",
                  "fijo": "Precio fijo por unidad"}
        lbl(s, "Desde cuántas unidades *", variante="suave",
            bg=C.superficie).pack(padx=20, anchor="w")
        v_cant = tk.StringVar(value="3")
        tk.Entry(s, textvariable=v_cant, font=F.normal, bg=C.superficie,
                 fg=C.texto, relief="solid", bd=1).pack(
            fill="x", padx=20, ipady=5, pady=(2, 10))

        lbl(s, "¿Cómo se calcula? *", variante="suave",
            bg=C.superficie).pack(padx=20, anchor="w")
        v_tipo = tk.StringVar(value=_TIPOS["pct"])
        ttk.Combobox(s, textvariable=v_tipo, font=F.normal, state="readonly",
                     values=tuple(_TIPOS.values())).pack(
            fill="x", padx=20, pady=(2, 8), ipady=3)

        lbl_valor = lbl(s, "Descuento % *", variante="suave", bg=C.superficie)
        lbl_valor.pack(padx=20, anchor="w")
        e_pct = tk.Entry(s, font=F.normal, bg=C.superficie, fg=C.texto,
                         insertbackground=C.primario, relief="solid", bd=1)
        e_pct.insert(0, "10")
        e_pct.pack(fill="x", padx=20, ipady=5, pady=(2,10))

        def _cambio_tipo(*_a):
            t = v_tipo.get()
            if t == _TIPOS["pct"]:
                lbl_valor.config(text="Descuento % *")
            elif t == _TIPOS["monto"]:
                lbl_valor.config(text="Cuántos $ menos por unidad *")
            else:
                lbl_valor.config(text="Precio final por unidad *")

        v_tipo.trace_add("write", _cambio_tipo)

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

            _tipo = {v: k for k, v in _TIPOS.items()}.get(v_tipo.get(), "pct")
            try:
                pct = float(e_pct.get().replace(",", "."))
                if pct <= 0:
                    raise ValueError
                if _tipo == "pct" and pct >= 100:
                    raise ValueError
            except ValueError:
                messagebox.showwarning(
                    "Error",
                    "El descuento tiene que ser un número entre 0 y 100."
                    if _tipo == "pct" else "Poné un importe mayor a 0.",
                    parent=d)
                return

            hasta = e_hasta.get().strip() or None
            if hasta:
                try:
                    datetime.strptime(hasta, "%Y-%m-%d")
                except ValueError:
                    messagebox.showwarning(
                        "Error", f"Fecha inválida: {hasta}", parent=d)
                    return

            _txt = ({"pct": f"{pct:g}% de descuento",
                     "monto": f"$ {pct:,.2f} menos por unidad",
                     "fijo": f"precio fijo de $ {pct:,.2f}"})[_tipo]
            desc = e_desc.get().strip() or _txt.capitalize()

            from repositorio import simular_promo_masiva
            sim = simular_promo_masiva(ids, _tipo, pct)
            perdidas = sorted((m for m in sim if m["nivel"] == "perdida"),
                              key=lambda m: m["margen"])
            bajos = [m for m in sim if m["nivel"] == "bajo"]
            sin_costo = [m for m in sim if m["nivel"] == "sin_costo"]
            aviso = ""
            if perdidas:
                peor = perdidas[0]
                aviso += (f"\n\n⚠ {len(perdidas)} producto(s) quedarían POR DEBAJO "
                          f"DEL COSTO. El peor: «{peor['descripcion']}», a "
                          f"$ {peor['precio']:,.2f} con costo $ {peor['costo']:,.2f} "
                          f"(perdés $ {-peor['margen']:,.2f} por unidad).")
            if bajos:
                aviso += (f"\n\n⚠ {len(bajos)} con margen bajo (menos de "
                          f"{margen_minimo_promo_pct():g}% sobre el costo).")
            if sin_costo:
                aviso += (f"\n\n{len(sin_costo)} no tienen costo cargado: "
                          "no se pudo chequear su margen.")
            if not messagebox.askyesno(
                    "⚠ Confirmar" if perdidas else "Confirmar",
                    f"Aplicar {_txt} a {len(ids)} producto(s)?" + aviso +
                    ("\n\n¿Aplicarla igual?" if perdidas else ""),
                    icon="warning" if (perdidas or bajos) else "question",
                    default="no" if perdidas else "yes",
                    parent=d):
                return

            from repositorio import aplicar_promocion_bulk_tipo
            n = aplicar_promocion_bulk_tipo(ids, [(int(v_cant.get() or 1), pct)],
                                            desc, None, hasta, _tipo)
            if n < len(ids):
                messagebox.showinfo(
                    "Promoción",
                    f"Se aplicó a {n} de {len(ids)} producto(s).\n\n"
                    f"Los que quedaron afuera ya valen eso o menos: una "
                    f"promo que no baja el precio no se guarda.",
                    parent=d)
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

    def _on_click_tabla_promo(self, event):
        iid = self.tree_pr.identify_row(event.y)
        if not iid:
            return
        col = self.tree_pr.identify_column(event.x)
        if col == "#1":   # columna checkbox
            if iid in self._promos_seleccionadas:
                self._promos_seleccionadas.discard(iid)
                self.tree_pr.set(iid, "sel", "")
            else:
                self._promos_seleccionadas.add(iid)
                self.tree_pr.set(iid, "sel", "x")
            self.lbl_sel_promo.config(text=str(len(self._promos_seleccionadas)))
        else:
            # Click fuera del checkbox: selecciona esa fila sola, para
            # que Editar / Pausar / Eliminar sigan operando de a una
            # como antes.
            self._promo_sel_id = int(iid)

    def _promos_sel_todo(self):
        self._promos_seleccionadas = set(self.tree_pr.get_children())
        for iid in self._promos_seleccionadas:
            self.tree_pr.set(iid, "sel", "x")
        self.lbl_sel_promo.config(text=str(len(self._promos_seleccionadas)))

    def _promos_desel_todo(self):
        for iid in self._promos_seleccionadas:
            self.tree_pr.set(iid, "sel", "")
        self._promos_seleccionadas.clear()
        self.lbl_sel_promo.config(text="0")

    def _confirmar_bajo_costo(self, ids, modo, valor):
        """Si el cambio deja promos bajo costo, lo avisa y pide confirmar.

        Devuelve True si se puede seguir (no hay problema o el usuario insiste).
        """
        perdidas = []
        for i in ids:
            pr = self._promos_filas.get(str(i))
            if not pr:
                continue
            if modo == "sumar_pct":
                if pr.get("tipo_descuento") != "porcentaje":
                    continue
                pct = max(0.0, float(pr.get("porcentaje_descuento") or 0) + valor)
                precio = round(float(pr["precio_base"]) * (1 - pct / 100), 2)
            else:
                precio = float(valor)
            m = margen_sobre_costo(precio, costo_real_producto(pr["producto_id"]))
            if m["nivel"] == "perdida":
                perdidas.append((pr["descripcion"], precio, m))
        if not perdidas:
            return True
        lineas = [f"• {desc}: a $ {p:,.2f} (costo $ {m['costo']:,.2f}, "
                  f"perdés $ {-m['margen']:,.2f} por unidad)"
                  for desc, p, m in perdidas[:8]]
        if len(perdidas) > 8:
            lineas.append(f"… y {len(perdidas) - 8} más")
        return messagebox.askyesno(
            "⚠ Quedarían bajo costo",
            f"Con este cambio {len(perdidas)} promoción(es) venderían POR DEBAJO "
            "DEL COSTO:\n\n" + "\n".join(lineas) +
            "\n\n¿Aplicarlo igual?",
            icon="warning", default="no", parent=self)

    def _promos_sumar_pct(self):
        if not self._promos_seleccionadas:
            messagebox.showinfo("Atención", "Selecciona promociones con la columna de la izquierda.", parent=self)
            return
        try:
            pts = float(self.entry_promo_sumar.get().replace(",", "."))
        except ValueError:
            messagebox.showwarning("Error", "El valor no es un número.", parent=self)
            return
        ids = [int(i) for i in self._promos_seleccionadas]
        from fiado_ui import pedir_autorizacion
        responsable = pedir_autorizacion(
            self, f"Sumar {pts:+g} pts a {len(ids)} promoción(es).")
        if not responsable:
            return
        if not self._confirmar_bajo_costo(ids, "sumar_pct", pts):
            return
        if not messagebox.askyesno(
                "Confirmar",
                f"Sumar {pts:+g} puntos de descuento a {len(ids)} "
                "promoción(es)?\n\nSolo afecta a las que son por "
                "porcentaje; las de precio fijo no se tocan.",
                parent=self):
            return
        n = modificar_promociones_bulk(ids, "sumar_pct", pts)
        from repositorio import registrar_bitacora
        registrar_bitacora("Modificación masiva de promociones",
                           responsable, f"{pts:+g} pts sobre {n} promoción(es)")
        toast(self, f"{n} promoción(es) actualizada(s)")
        self._refrescar_promos()

    def _promos_fijar_precio(self):
        if not self._promos_seleccionadas:
            messagebox.showinfo("Atención", "Selecciona promociones con la columna de la izquierda.", parent=self)
            return
        try:
            precio = float(self.entry_promo_precio.get().replace(",", "."))
            if precio <= 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning(
                "Error", "El precio tiene que ser un número mayor a $0.",
                parent=self)
            return
        ids = [int(i) for i in self._promos_seleccionadas]
        from fiado_ui import pedir_autorizacion
        responsable = pedir_autorizacion(
            self, f"Fijar $ {precio:,.2f} en {len(ids)} promoción(es).")
        if not responsable:
            return
        if not self._confirmar_bajo_costo(ids, "precio_fijo", precio):
            return
        if not messagebox.askyesno(
                "Confirmar",
                f"Fijar el precio promocional en $ {precio:,.2f} para "
                f"{len(ids)} promoción(es)?\n\nLas que eran por "
                "porcentaje pasan a ser de precio fijo.",
                parent=self):
            return
        n = modificar_promociones_bulk(ids, "precio_fijo", precio)
        from repositorio import registrar_bitacora
        registrar_bitacora("Modificación masiva de promociones",
                           responsable, f"precio fijo $ {precio:,.2f} sobre {n} promoción(es)")
        toast(self, f"{n} promoción(es) actualizada(s)")
        self._refrescar_promos()

    def _promos_a_porcentaje(self):
        """Pasa promos de precio fijo a porcentaje (con vista previa)."""
        if not self._promos_seleccionadas:
            messagebox.showinfo(
                "Atención", "Seleccioná promociones con la columna de la izquierda "
                "(o usá «seleccionar todo»).", parent=self)
            return
        from repositorio import convertir_promos_a_porcentaje, registrar_bitacora
        ids = [int(i) for i in self._promos_seleccionadas]
        previa = convertir_promos_a_porcentaje(ids)
        if not any(p["estado"] != "ya_es_pct" for p in previa):
            messagebox.showinfo("Pasar a %", "Todas las elegidas ya son por porcentaje.",
                                parent=self)
            return

        d = tk.Toplevel(self)
        d.title("Pasar promociones a porcentaje")
        d.configure(bg=C.superficie)
        d.grab_set()
        _centrar(d, 760, 560)
        lbl(d, "Pasar a porcentaje", variante="titulo", bg=C.superficie).pack(
            anchor="w", padx=16, pady=(14, 2))
        tk.Label(d, bg=C.superficie, fg=C.texto_suave, font=F.normal, justify="left",
                 wraplength=720, anchor="w",
                 text="Una promo por % sigue al precio de lista: si bajás o subís el "
                      "producto, la promo se ajusta sola. Las de precio fijo no. "
                      "Si dejás el campo vacío, cada promo conserva el descuento que "
                      "tiene HOY; eso solo es correcto si el producto no cambió de "
                      "precio desde que la cargaste. Si no estás seguro, poné vos el %."
                 ).pack(fill="x", padx=16)
        fila = tk.Frame(d, bg=C.superficie)
        fila.pack(fill="x", padx=16, pady=8)
        lbl(fila, "% para todas (vacío = el descuento actual de cada una):",
            variante="suave", bg=C.superficie).pack(side="left")
        e_pct = tk.Entry(fila, width=7, justify="center", font=F.normal,
                         bg=C.superficie, fg=C.texto, relief="solid", bd=1)
        e_pct.pack(side="left", padx=6, ipady=4)

        cols = [("producto", "Producto", 260, "w"), ("cant", "Desde", 55, "e"),
                ("promo", "Promo hoy", 90, "e"), ("normal", "Normal", 90, "e"),
                ("pct", "Quedaría", 80, "e"), ("estado", "Estado", 130, "w")]
        frame_t, tree = tabla(d, cols, altura=12)
        frame_t.pack(fill="both", expand=True, padx=16, pady=(0, 6))
        tree.tag_configure("ok", foreground=C.exito)
        tree.tag_configure("ya", foreground=C.texto_suave)
        tree.tag_configure("sin", foreground=C.peligro)
        lbl_res = lbl(d, "", variante="suave", bg=C.superficie)
        lbl_res.pack(anchor="w", padx=16)

        estado_txt = {"ok": "se convierte", "ya_es_pct": "ya es %",
                      "sin_pct": "falta indicar el %"}

        def _pct_ingresado():
            t = e_pct.get().strip().replace(",", ".").rstrip("%")
            if not t:
                return None
            try:
                v = float(t)
            except ValueError:
                raise ValueError("El porcentaje no es un número.")
            if not 0 < v < 100:
                raise ValueError("El porcentaje tiene que estar entre 0 y 100.")
            return v

        def _vista(*_a):
            try:
                pct = _pct_ingresado()
            except ValueError as exc:
                lbl_res.config(text=str(exc), fg=C.peligro)
                return None
            items = convertir_promos_a_porcentaje(ids, pct)
            for r in tree.get_children():
                tree.delete(r)
            for it in items:
                tag = {"ok": "ok", "ya_es_pct": "ya", "sin_pct": "sin"}[it["estado"]]
                tree.insert("", "end", values=(
                    it["descripcion"], f"x {it['cantidad_minima']}",
                    f"$ {it['precio_promo']:,.2f}", f"$ {it['precio_base']:,.2f}",
                    f"{it['pct']:.2f}%" if it["pct"] is not None else "—",
                    estado_txt[it["estado"]]), tags=(tag,))
            n_ok = sum(1 for i in items if i["estado"] == "ok")
            n_sin = sum(1 for i in items if i["estado"] == "sin_pct")
            lbl_res.config(
                text=f"{n_ok} se convierten"
                     + (f"  ·  {n_sin} no se pueden: ya no mejoran el precio normal, "
                        "poné un % arriba" if n_sin else ""),
                fg=C.peligro if n_sin else C.exito)
            return items

        e_pct.bind("<KeyRelease>", _vista)
        _vista()

        def convertir():
            try:
                pct = _pct_ingresado()
            except ValueError as exc:
                messagebox.showwarning("Error", str(exc), parent=d)
                return
            items = convertir_promos_a_porcentaje(ids, pct)
            n_ok = sum(1 for i in items if i["estado"] == "ok")
            if not n_ok:
                messagebox.showinfo("Pasar a %", "No hay ninguna promoción para convertir. "
                                    "Poné un porcentaje.", parent=d)
                return
            from fiado_ui import pedir_autorizacion
            resp = pedir_autorizacion(d, f"Pasar {n_ok} promoción(es) a porcentaje.")
            if not resp:
                return
            convertir_promos_a_porcentaje(ids, pct, aplicar=True)
            registrar_bitacora("Promociones pasadas a porcentaje", resp,
                               f"{n_ok} promoción(es)"
                               + (f" al {pct:g}%" if pct else " con su descuento actual"))
            d.destroy()
            toast(self, f"{n_ok} promoción(es) pasadas a porcentaje")
            self._refrescar_promos()

        pie = tk.Frame(d, bg=C.superficie)
        pie.pack(pady=(4, 14))
        btn(pie, "Convertir", variante="exito", comando=convertir).pack(side="left", padx=6)
        btn(pie, "Cancelar", variante="neutro", comando=d.destroy).pack(side="left", padx=6)

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
        self._actualizar_margen_promo = None

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
                _f = getattr(self, "_actualizar_margen_promo", None)
                if _f:
                    _f()

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

        # Margen en vivo, para ver cuanto queda ANTES de guardar
        lbl_margen = tk.Label(f_tipo, text="", bg=C.superficie, font=F.normal,
                              justify="left", wraplength=400, anchor="w")
        lbl_margen.pack(fill="x", anchor="w", pady=(8, 0))

        def _actualizar_margen(*_a):
            pid_ = self._prod_promo_id
            if not pid_:
                lbl_margen.config(text="Elegí un producto para ver el margen.",
                                  fg=C.texto_suave)
                return
            from repositorio import get_producto_completo
            prod_ = get_producto_completo(pid_) or {}
            base_ = float(prod_.get("precio_base") or 0)
            try:
                if self._tipo_promo.get() == "porcentaje":
                    pct_ = float(e_pct.get().replace(",", "."))
                    if not (0 < pct_ < 100):
                        raise ValueError
                    precio_ = round(base_ * (1 - pct_ / 100), 2)
                else:
                    precio_ = float(e_precio.get().replace(",", "."))
                    if precio_ <= 0:
                        raise ValueError
            except ValueError:
                lbl_margen.config(text="", fg=C.texto_suave)
                return
            m_ = margen_sobre_costo(precio_, costo_real_producto(pid_))
            if m_["nivel"] == "sin_costo":
                lbl_margen.config(
                    text=f"Precio de venta $ {precio_:,.2f}. Este producto no tiene "
                         "costo cargado: no se puede calcular el margen.",
                    fg=C.advertencia)
            elif m_["nivel"] == "perdida":
                lbl_margen.config(
                    text=f"⚠ VENDÉS BAJO COSTO: a $ {precio_:,.2f} con costo "
                         f"$ {m_['costo']:,.2f} perdés $ {-m_['margen']:,.2f} por "
                         f"unidad ({-m_['pct']:.1f}% por debajo del costo).",
                    fg=C.peligro)
            elif m_["nivel"] == "bajo":
                lbl_margen.config(
                    text=f"⚠ Margen muy bajo: a $ {precio_:,.2f} con costo "
                         f"$ {m_['costo']:,.2f} ganás $ {m_['margen']:,.2f} por "
                         f"unidad ({m_['pct']:.1f}% sobre el costo; el mínimo "
                         f"recomendado es {margen_minimo_promo_pct():g}%).",
                    fg=C.advertencia)
            else:
                lbl_margen.config(
                    text=f"Margen: a $ {precio_:,.2f} con costo $ {m_['costo']:,.2f} "
                         f"ganás $ {m_['margen']:,.2f} por unidad "
                         f"({m_['pct']:.1f}% sobre el costo).",
                    fg=C.exito)

        e_precio.bind("<KeyRelease>", _actualizar_margen)
        e_pct.bind("<KeyRelease>", _actualizar_margen)
        self._tipo_promo.trace_add("write", _actualizar_margen)
        self._actualizar_margen_promo = _actualizar_margen

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
            _actualizar_margen()

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

            m_ = margen_sobre_costo(precio, costo_real_producto(pid))
            if m_["nivel"] == "perdida":
                if not messagebox.askyesno(
                        "⚠ Vendés bajo costo",
                        f"A $ {precio:,.2f} por unidad (costo $ {m_['costo']:,.2f}) "
                        f"perdés $ {-m_['margen']:,.2f} en cada unidad que se "
                        "venda con esta promoción.\n\n¿Guardarla igual?",
                        icon="warning", default="no", parent=d):
                    return
            elif m_["nivel"] == "bajo":
                if not messagebox.askyesno(
                        "Margen muy bajo",
                        f"A $ {precio:,.2f} por unidad (costo $ {m_['costo']:,.2f}) "
                        f"ganás solo $ {m_['margen']:,.2f} ({m_['pct']:.1f}% sobre "
                        f"el costo). El mínimo recomendado es "
                        f"{margen_minimo_promo_pct():g}%.\n\n¿Guardarla igual?",
                        icon="warning", default="no", parent=d):
                    return

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
        """Elimina las promos TILDADAS (columna de la izquierda); si no hay
        ninguna tildada, la fila que esta elegida."""
        if self._promos_seleccionadas:
            return self._eliminar_promos_tildadas()
        if not self._promo_sel_id:
            messagebox.showinfo(
                "Atencion", "Elegí una promoción (clic en la fila) o tildá varias con la "
                "columna de la izquierda.", parent=self)
            return
        if messagebox.askyesno("Eliminar", "Eliminar esta promocion?", parent=self):
            eliminar_promocion(self._promo_sel_id)
            self._promo_sel_id = None
            toast(self, "Promocion eliminada")
            import catalogo_web
            catalogo_web.sincronizar_stock_en_segundo_plano()
            self._refrescar_promos()

    def _eliminar_promos_tildadas(self):
        from repositorio import eliminar_promociones_bulk, registrar_bitacora
        ids = [int(i) for i in self._promos_seleccionadas]
        total = len(get_promociones())
        todas = len(ids) >= total
        if not messagebox.askyesno(
                "Eliminar promociones",
                (f"Vas a eliminar TODAS las promociones ({len(ids)})."
                 if todas else f"Vas a eliminar {len(ids)} promoción(es).")
                + "\n\nNo se puede deshacer, pero antes se guarda un archivo con cómo "
                  "estaban (producto, cantidad, % y precio) para que puedas volver a "
                  "cargarlas.\n\n¿Eliminar?",
                icon="warning", default="no", parent=self):
            return
        from fiado_ui import pedir_autorizacion
        responsable = pedir_autorizacion(
            self, f"Eliminar {len(ids)} promoción(es).")
        if not responsable:
            return
        try:
            n, ruta = eliminar_promociones_bulk(ids)
        except Exception as exc:
            messagebox.showwarning(
                "Eliminar", f"No se eliminó nada:\n{exc}", parent=self)
            return
        registrar_bitacora("Eliminación masiva de promociones", responsable,
                           f"{n} promoción(es); respaldo: {ruta}")
        self._promo_sel_id = None
        try:
            import catalogo_web
            catalogo_web.sincronizar_stock_en_segundo_plano()
        except Exception:
            pass
        self._refrescar_promos()
        messagebox.showinfo(
            "Eliminar", f"Se eliminaron {n} promoción(es).\n\nRespaldo guardado en:\n{ruta}",
            parent=self)

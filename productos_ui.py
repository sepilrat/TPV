"""
productos_ui.py — Gestión de productos y categorías TPV v2.0
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import threading
import os
import sys
import subprocess
import imagenes
from styles import C, F, btn, lbl, card, tabla, toast, header_seccion, scrollable
from repositorio import (get_productos, get_categorias, guardar_categoria,
                         eliminar_categoria, actualizar_producto,
                         toggle_producto_activo, get_conteo_productos_por_categoria,
                         get_categoria_por_id, get_producto_completo,
                         toggle_ignorar_alerta, get_stock_producto,
                         ajustar_stock, get_historial_ajustes,
                         eliminar_producto_si_posible, recalcular_precios_categoria,
                         diagnostico_recalculo_categoria)
from fiado_ui import pedir_autorizacion

MOTIVOS_AJUSTE = ["Merma", "Rotura", "Conteo físico", "Error de carga", "Otro"]

# ─────────────────────────────────────────────────────────────────────────────
# Helpers DB
# ─────────────────────────────────────────────────────────────────────────────

COLS_PROD = [
    ("codigo",    "Codigo",      100, "w"),
    ("desc",      "Descripcion", 210, "w"),
    ("marca",     "Marca",        90, "w"),
    ("categoria", "Categoria",    95, "w"),
    ("precio",    "Precio",       80, "e"),
    ("costo",     "Costo",        80, "e"),
    ("margen",    "Margen %",     70, "e"),
    ("venta",     "Venta",        60, "center"),
    ("stock",     "Stock",        60, "e"),
    ("alerta",    "Alerta",       55, "center"),
]

COLS_CAT = [
    ("nombre",  "Categoria", 200, "w"),
    ("margen",  "Margen %",   80, "e"),
    ("prods",   "Productos",  80, "e"),
]

def _centrar(d, w, h):
    sw = d.winfo_screenwidth()
    sh = d.winfo_screenheight()
    # Si el diálogo es más alto/ancho que la pantalla, antes quedaba
    # con parte de la ventana (incluida la barra de título, de donde
    # se arrastra) arriba del área visible — imposible de bajar. Ahora
    # se limita el tamaño a la pantalla (dejando margen para la barra
    # de tareas) y la posición nunca es negativa. El contenido de estos
    # diálogos ya usa scrollable(), así que si queda más bajo de lo que
    # entra, aparece un scroll en vez de cortarse.
    margen = 40
    w = min(w, sw - 20)
    h = min(h, sh - margen)
    x = max(0, (sw - w) // 2)
    y = max(0, (sh - h) // 2)
    d.geometry(f"{w}x{h}+{x}+{y}")


def _fmt_cant(v):
    """Formatea cantidad: entera sin decimales, fraccionaria con hasta
    3 decimales (para productos vendidos por peso)."""
    v = float(v)
    if v == int(v):
        return str(int(v))
    return f"{v:.3f}".rstrip("0").rstrip(".")

class ProductosUI(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._cat_map = {}   # nombre → id
        self._prod_sel = None
        self._build()
        self._refrescar()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build(self):
        # Tabs internos: Productos / Categorías
        # Muestra el catálogo completo de productos y categorías.
        # Desde acá se crean, editan y desactivan productos.
        # El código de barras es el identificador principal de cada producto.
        header_seccion(self, "Catalogo de Productos",
            "Alta, edicion y baja de productos y categorias").pack(
            fill="x", padx=12, pady=(8,0))

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=12, pady=12)

        f_prod = ttk.Frame(nb)
        f_cat  = ttk.Frame(nb)
        nb.add(f_prod, text="  Productos  ")
        nb.add(f_cat,  text="  Categorías  ")

        self._build_productos(f_prod)
        self._build_categorias(f_cat)

    # ── Tab Productos ─────────────────────────────────────────────────────────

    def _build_productos(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)

        # Barra de búsqueda y filtros
        bar = tk.Frame(parent, bg=C.bg)
        bar.grid(row=0, column=0, sticky="ew", pady=(0,8))

        lbl(bar, "Buscar:").pack(side="left", padx=(0,6))
        self.entry_buscar = tk.Entry(bar, font=F.normal, width=28,
                                      bg=C.superficie, fg=C.texto,
                                      insertbackground=C.primario,
                                      relief="solid", bd=1)
        self.entry_buscar.pack(side="left", ipady=5)
        self.entry_buscar.bind("<KeyRelease>", lambda e: self._refrescar_productos())

        lbl(bar, "Categoría:").pack(side="left", padx=(16,6))
        self.combo_filtro_cat = ttk.Combobox(bar, font=F.normal, width=16, state="readonly")
        self.combo_filtro_cat.pack(side="left")
        self.combo_filtro_cat.bind("<<ComboboxSelected>>", lambda e: self._refrescar_productos())

        self.var_inactivos = tk.BooleanVar(value=False)
        tk.Checkbutton(bar, text="Mostrar inactivos",
                       variable=self.var_inactivos,
                       bg=C.bg, fg=C.texto, font=F.normal,
                       command=self._refrescar_productos).pack(side="left", padx=(16,4))

        btn(bar, "Limpiar", variante="neutro",
            comando=self._limpiar_filtros).pack(side="left", padx=8)
        btn(bar, "🔄 Actualizar", variante="neutro",
            comando=self._refrescar).pack(side="right")

        # Tabla
        frame_t, self.tree_prod = tabla(parent, COLS_PROD, con_iconos=True)
        frame_t.grid(row=1, column=0, sticky="nsew")
        self.tree_prod.bind("<Double-1>", self._editar_producto)
        self.tree_prod.tag_configure("sin_alerta", foreground=C.texto_suave, font=("Segoe UI", 10))
        self.tree_prod.tag_configure("inactivo",   foreground=C.texto_suave,
                                     font=("Segoe UI", 10, "overstrike"))
        self.tree_prod.bind("<<TreeviewSelect>>", self._on_sel_prod)

        # Acciones
        ac = tk.Frame(parent, bg=C.bg)
        ac.grid(row=2, column=0, sticky="ew", pady=(8,0))
        btn(ac, "Editar",          variante="primario", comando=self._editar_producto).pack(side="left")
        btn(ac, "Activar/Desactivar", variante="peligro", comando=self._toggle_activo).pack(side="left", padx=6)
        btn(ac, "Eliminar",           variante="peligro",  comando=self._eliminar).pack(side="left", padx=6)
        btn(ac, "Alerta stock ON/OFF", variante="neutro",
            comando=self._toggle_alerta).pack(side="left", padx=6)
        btn(ac, "Ajustar stock", variante="neutro",
            comando=self._ajustar_stock).pack(side="left", padx=6)
        btn(ac, "Vencimientos", variante="neutro",
            comando=self._vencimientos_producto).pack(side="left", padx=6)
        btn(ac, "Redondear precios", variante="neutro",
            comando=self._redondear_precios).pack(side="left", padx=6)
        btn(ac, "Abrir horma", variante="neutro",
            comando=self._abrir_horma).pack(side="left", padx=6)
        btn(ac, "Presentaciones", variante="neutro",
            comando=self._presentaciones).pack(side="left", padx=6)
        btn(ac, "Historial ajustes", variante="neutro",
            comando=self._historial_ajustes).pack(side="left", padx=6)
        btn(ac, "Etiquetas", variante="neutro",
            comando=self._imprimir_etiquetas).pack(side="left", padx=6)
        lbl(ac, "Doble click para editar", variante="suave").pack(side="right")

    # ── Tab Categorías ────────────────────────────────────────────────────────

    def _build_categorias(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=0)
        parent.rowconfigure(0, weight=1)

        # Tabla categorías
        frame_t, self.tree_cat = tabla(parent, COLS_CAT, altura=15)
        frame_t.grid(row=0, column=0, sticky="nsew", padx=(0,12))
        self.tree_cat.bind("<<TreeviewSelect>>", self._on_sel_cat)

        # Formulario categoría
        form = card(parent)
        form.grid(row=0, column=1, sticky="nsew", ipadx=8)
        form.columnconfigure(0, weight=1)

        lbl(form, "Categoría", variante="titulo",
            bg=C.superficie).grid(row=0, column=0, sticky="w", padx=16, pady=(16,8))

        campos_cat = [("Nombre *", "entry_cat_nombre"), ("Margen % *", "entry_cat_margen")]
        for i, (label, attr) in enumerate(campos_cat):
            lbl(form, label, variante="suave",
                bg=C.superficie).grid(row=i*2+1, column=0, sticky="w", padx=16, pady=(4,0))
            e = tk.Entry(form, font=F.normal, bg=C.superficie, fg=C.texto,
                         insertbackground=C.primario, relief="solid", bd=1)
            e.grid(row=i*2+2, column=0, sticky="ew", padx=16, pady=(2,0), ipady=6)
            setattr(self, attr, e)

        btn(form, "💾  Guardar", variante="exito",
            comando=self._guardar_cat).grid(row=5, column=0, sticky="ew",
                                             padx=16, pady=(16,4))
        btn(form, "➕  Nueva", variante="primario",
            comando=self._nueva_cat).grid(row=6, column=0, sticky="ew",
                                           padx=16, pady=(0,4))
        btn(form, "🗑  Eliminar", variante="peligro",
            comando=self._eliminar_cat).grid(row=7, column=0, sticky="ew",
                                              padx=16, pady=(0,16))

        self._cat_sel_id = None

        # Acciones tabla
        ac = tk.Frame(parent, bg=C.bg)
        ac.grid(row=1, column=0, sticky="ew", pady=(8,0))
        btn(ac, "🔄 Actualizar", variante="neutro",
            comando=self._refrescar_categorias).pack(side="left")

    # ── Datos ─────────────────────────────────────────────────────────────────

    def refrescar(self):
        self._refrescar()

    def _refrescar(self):
        self._refrescar_productos()
        self._refrescar_categorias()

    def _refrescar_productos(self):
        filtro = self.entry_buscar.get().strip()
        cat_nombre = self.combo_filtro_cat.get()
        cat_id = self._cat_map.get(cat_nombre)

        for r in self.tree_prod.get_children():
            self.tree_prod.delete(r)
        self.tree_prod._thumbs = []

        solo_activos = not self.var_inactivos.get()
        for p in get_productos(filtro, cat_id, solo_activos=solo_activos):
            margen = ((p["precio_base"] - p["costo_ultimo"]) / p["costo_ultimo"] * 100
                      if p["costo_ultimo"] else 0)
            sin_alerta = bool(p.get("ignorar_alerta"))
            inactivo   = not bool(p.get("activo", 1))
            tag = "inactivo" if inactivo else ("sin_alerta" if sin_alerta else "")
            foto = imagenes.cargar_thumbnail(p.get("imagen_url"), size=(48, 48))
            if foto:
                self.tree_prod._thumbs.append(foto)
            self.tree_prod.insert("", "end", iid=str(p["id"]),
                tags=(tag,) if tag else (), image=(foto or ""),
                values=(
                    p["codigo"],
                    p["descripcion"],
                    p.get("marca") or "—",
                    p["categoria"] or "—",
                    f"$ {p['precio_base']:,.2f}",
                    f"$ {p['costo_ultimo']:,.2f}",
                    f"{margen:.1f}%",
                    "Kg" if p.get("vendido_por_peso") else "Un",
                    _fmt_cant(p['stock']),
                    "OFF" if sin_alerta else "ON",
                ))

    def _refrescar_categorias(self):
        cats = get_categorias()
        self._cat_map = {r["nombre"]: r["id"] for r in cats}

        self.combo_filtro_cat["values"] = ["(Todas)"] + list(self._cat_map.keys())
        if not self.combo_filtro_cat.get():
            self.combo_filtro_cat.set("(Todas)")

        conteos = get_conteo_productos_por_categoria()

        for r in self.tree_cat.get_children():
            self.tree_cat.delete(r)

        for c in cats:
            margen_txt = (f"{c['margen_pct']:.1f}%"
                         if c["margen_pct"] is not None else "— (heredado)")
            self.tree_cat.insert("", "end", iid=str(c["id"]), values=(
                c["nombre"],
                margen_txt,
                conteos.get(c["id"], 0),
            ))

    def _limpiar_filtros(self):
        self.entry_buscar.delete(0, "end")
        self.combo_filtro_cat.set("(Todas)")
        self._refrescar_productos()

    # ── Selección ─────────────────────────────────────────────────────────────

    def _on_sel_prod(self, event):
        sel = self.tree_prod.selection()
        self._prod_sel = int(sel[0]) if sel else None

    def _on_sel_cat(self, event):
        sel = self.tree_cat.selection()
        if not sel:
            return
        self._cat_sel_id = int(sel[0])
        c = get_categoria_por_id(self._cat_sel_id)
        if c:
            self.entry_cat_nombre.delete(0, "end")
            self.entry_cat_nombre.insert(0, c["nombre"])
            self.entry_cat_margen.delete(0, "end")
            if c["margen_pct"] is not None:
                self.entry_cat_margen.insert(0, str(c["margen_pct"]))

    # ── Acciones productos ────────────────────────────────────────────────────

    def _imprimir_etiquetas(self):
        """Abre el selector de etiquetas de gondola."""
        from etiquetas import abrir_selector_etiquetas
        abrir_selector_etiquetas(self)

    def _toggle_alerta(self):
        pid = self._prod_sel
        if not pid:
            messagebox.showinfo("Atencion", "Selecciona un producto.", parent=self)
            return
        prod = get_producto_completo(pid)
        if not prod:
            return
        # ignorar_alerta=1 significa alerta OFF, =0 significa alerta ON
        actualmente_ignorando = bool(prod.get("ignorar_alerta"))
        nuevo_valor = 0 if actualmente_ignorando else 1
        toggle_ignorar_alerta(pid, nuevo_valor)
        if nuevo_valor == 1:
            msg = (f"Alerta desactivada para: {prod['descripcion']}\n"
                   "(no aparecera en alertas de stock bajo)")
        else:
            msg = (f"Alerta activada para: {prod['descripcion']}\n"
                   "(aparecera en alertas de stock bajo)")
        messagebox.showinfo("Alerta de stock", msg, parent=self)
        self._refrescar_productos()

    def _ajustar_stock(self):
        pid = self._prod_sel
        if not pid:
            messagebox.showinfo("Atención", "Seleccioná un producto primero.", parent=self)
            return
        prod = get_producto_completo(pid)
        if not prod:
            return
        stock_actual = get_stock_producto(pid)

        d = tk.Toplevel(self)
        d.title("Ajustar stock")
        _centrar(d, 400, 430)
        d.resizable(False, False)
        d.configure(bg=C.superficie)
        d.grab_set()

        lbl(d, "Ajustar stock", variante="titulo",
            bg=C.superficie).pack(pady=(20,4), padx=20, anchor="w")
        lbl(d, prod["descripcion"], variante="suave",
            bg=C.superficie).pack(padx=20, anchor="w")
        lbl(d, f"Stock actual: {_fmt_cant(stock_actual)} u.",
            variante="suave", bg=C.superficie).pack(padx=20, anchor="w", pady=(0,8))

        lbl(d, "Cantidad correcta (nuevo total)", variante="suave",
            bg=C.superficie).pack(padx=20, anchor="w", pady=(8,0))
        e_cant = tk.Entry(d, font=F.normal, bg=C.superficie, fg=C.texto,
                          insertbackground=C.primario, relief="solid", bd=1)
        e_cant.insert(0, _fmt_cant(stock_actual))
        e_cant.pack(fill="x", padx=20, ipady=6, pady=(2,0))

        lbl(d, "Motivo", variante="suave", bg=C.superficie).pack(
            padx=20, anchor="w", pady=(10,0))
        combo_motivo = ttk.Combobox(d, font=F.normal, state="readonly",
                                    values=MOTIVOS_AJUSTE)
        combo_motivo.set(MOTIVOS_AJUSTE[0])
        combo_motivo.pack(fill="x", padx=20, pady=(2,0))

        lbl(d, "Notas (opcional)", variante="suave", bg=C.superficie).pack(
            padx=20, anchor="w", pady=(10,0))
        e_notas = tk.Entry(d, font=F.normal, bg=C.superficie, fg=C.texto,
                           insertbackground=C.primario, relief="solid", bd=1)
        e_notas.pack(fill="x", padx=20, ipady=6, pady=(2,0))

        def confirmar(event=None):
            try:
                nueva = float(e_cant.get().replace(",", "."))
                if nueva < 0: raise ValueError
            except ValueError:
                messagebox.showwarning("Error", "Cantidad inválida.", parent=d)
                return
            if nueva == stock_actual:
                messagebox.showinfo("Sin cambios",
                                    "La cantidad es igual al stock actual.", parent=d)
                return
            if not bool(prod.get("vendido_por_peso")) and nueva != int(nueva):
                messagebox.showwarning(
                    "Atención",
                    "Este producto se vende por unidad — la cantidad debe ser entera.",
                    parent=d)
                return

            responsable = pedir_autorizacion(
                d, f"Ajustar el stock de \"{prod['descripcion']}\" de "
                   f"{_fmt_cant(stock_actual)} a {_fmt_cant(nueva)} unidades.")
            if not responsable:
                return

            ajustar_stock(pid, nueva, combo_motivo.get(),
                         responsable, e_notas.get().strip())
            d.destroy()
            toast(self, "✅  Stock ajustado")
            self._refrescar_productos()

        e_cant.bind("<Return>", confirmar)
        btn(d, "Confirmar ajuste", variante="exito", comando=confirmar).pack(
            fill="x", padx=20, pady=20)
        e_cant.focus_set()
        e_cant.select_range(0, "end")

    def _historial_ajustes(self):
        pid = self._prod_sel
        prod = get_producto_completo(pid) if pid else None

        d = tk.Toplevel(self)
        d.title("Historial de ajustes de stock")
        _centrar(d, 720, 420)
        d.configure(bg=C.bg)
        d.grab_set()
        d.columnconfigure(0, weight=1)
        d.rowconfigure(1, weight=1)

        titulo = (f"Ajustes de: {prod['descripcion']}" if prod
                  else "Últimos ajustes de stock (todos los productos)")
        lbl(d, titulo, variante="titulo", bg=C.bg).grid(
            row=0, column=0, sticky="w", padx=12, pady=(12,4))

        cols = [
            ("fecha",    "Fecha",       130, "w"),
            ("producto", "Producto",    170, "w"),
            ("anterior", "Antes",        70, "e"),
            ("nueva",    "Después",      70, "e"),
            ("dif",      "Diferencia",   80, "e"),
            ("motivo",   "Motivo",      100, "w"),
            ("autorizo", "Autorizó",    100, "w"),
            ("notas",    "Notas",       150, "w"),
        ]
        frame_t, tree = tabla(d, cols)
        frame_t.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0,12))

        for a in get_historial_ajustes(pid, limit=200):
            dif = a["diferencia"]
            tree.insert("", "end", values=(
                a["fecha"][:16] if a["fecha"] else "—",
                a["descripcion"],
                _fmt_cant(a["cantidad_anterior"]),
                _fmt_cant(a["cantidad_nueva"]),
                f"{'+' if dif > 0 else ''}{_fmt_cant(dif)}",
                a["motivo"],
                a["autorizado_por"],
                a["notas"] or "",
            ))

    def _vencimientos_producto(self):
        """Lotes de ESTE producto, para corregirles el vencimiento.

        Hasta ahora la fecha solo se podia tocar desde Stock, buscando el
        lote entre todos los ingresos. Desde el producto es donde uno la
        busca cuando ve una alerta rara.
        """
        if not self._prod_sel:
            messagebox.showinfo("Atención", "Seleccioná un producto primero.",
                                parent=self)
            return
        from historial_lotes_ui import dialogo_lotes_producto
        dialogo_lotes_producto(self, self._prod_sel)
        self.refrescar()

    def _redondear_precios(self):
        """Aplica el redondeo configurado a todo el catalogo, de una."""
        from config import cfg
        from repositorio import redondear_todos_los_precios
        paso = int(cfg().get("redondeo_precios", 0) or 0)
        if paso <= 0:
            messagebox.showinfo(
                "Redondear precios",
                "El redondeo esta en 0 (desactivado).\n\n"
                "Elegí el múltiplo en Config → Redondeo de precios "
                "(1, 10, 50 o 100) y volvé a intentar.", parent=self)
            return
        if not messagebox.askyesno(
                "Redondear precios",
                f"Se van a redondear TODOS los precios activos hacia arriba, "
                f"a múltiplos de ${paso}.\n\n"
                "Siempre para arriba, así no se pierde margen.\n\n"
                "¿Confirmás?", parent=self):
            return
        r = redondear_todos_los_precios(paso)
        if not r["cambiados"]:
            messagebox.showinfo("Redondear precios",
                                f"Los {r['revisados']} precios ya estaban redondos.",
                                parent=self)
            return
        muestra = "\n".join(
            f"  {c['descripcion'][:32]}:  ${c['anterior']:,.2f} → ${c['nuevo']:,.2f}"
            for c in r["detalle"][:8])
        extra = f"\n  ...y {r['cambiados'] - 8} mas" if r["cambiados"] > 8 else ""
        messagebox.showinfo(
            "Redondear precios",
            f"{r['cambiados']} de {r['revisados']} precios actualizados:\n\n"
            + muestra + extra, parent=self)
        self.refrescar()

    def _abrir_horma(self):
        """Pasa kilos del producto entero al fraccionado."""
        if not self._prod_sel:
            messagebox.showinfo("Atención", "Seleccioná el producto ENTERO.",
                                parent=self)
            return
        from abrir_horma_ui import dialogo_abrir_horma
        dialogo_abrir_horma(self, self._prod_sel, on_ok=self.refrescar)

    def _presentaciones(self):
        """Mismo producto, otra unidad de venta (ej: granel + bolsa cerrada)."""
        if not self._prod_sel:
            messagebox.showinfo("Atención", "Seleccioná un producto primero.",
                                parent=self)
            return
        from presentaciones_ui import dialogo_presentaciones
        dialogo_presentaciones(self, self._prod_sel)
        self.refrescar()

    def _editar_producto(self, event=None):
        pid = self._prod_sel
        if not pid:
            messagebox.showinfo("Atención", "Seleccioná un producto primero.", parent=self)
            return

        prod = get_producto_completo(pid)
        if not prod:
            return

        d = tk.Toplevel(self)
        d.title("Editar producto")
        _centrar(d, 520, 990)
        d.resizable(True, True)
        d.configure(bg=C.superficie)
        d.grab_set()
        d.columnconfigure(0, weight=1)
        d.rowconfigure(1, weight=1)

        lbl(d, "Editar producto", variante="titulo",
            bg=C.superficie).grid(row=0, column=0, sticky="w",
                                   padx=20, pady=(20,4))

        outer, s = scrollable(d, bg=C.superficie)
        outer.grid(row=1, column=0, sticky="nsew")

        campos = [
            ("Descripción",      prod["descripcion"]),
            ("Marca",            prod.get("marca") or ""),
            ("Código",           prod["codigo"]),
            ("Precio de venta",  f"{prod['precio_base']:.2f}"),
            ("Costo último",     f"{prod['costo_ultimo']:.2f}"),
            ("Margen % propio (vacío = heredar de categoría)",
                "" if prod["margen_pct"] is None else f"{prod['margen_pct']:.1f}"),
        ]
        entries = {}
        for label, valor in campos:
            lbl(s, label, variante="suave", bg=C.superficie).pack(
                padx=20, anchor="w", pady=(8,0))
            e = tk.Entry(s, font=F.normal, bg=C.superficie, fg=C.texto,
                         insertbackground=C.primario, relief="solid", bd=1)
            e.insert(0, valor)
            e.pack(fill="x", padx=20, ipady=6, pady=(2,0))
            entries[label] = e

        lbl(s, "Categoría", variante="suave", bg=C.superficie).pack(
            padx=20, anchor="w", pady=(8,0))
        combo = ttk.Combobox(s, font=F.normal, state="readonly",
                              values=list(self._cat_map.keys()))
        combo.set(prod["cat_nombre"] or "")
        combo.pack(fill="x", padx=20, pady=(2,0))

        # El precio de venta se recalcula solo cuando cambiás el margen
        # propio (o el costo) — antes había que acordarse de tipear el
        # precio nuevo a mano, y si no, el margen quedaba guardado pero
        # el precio seguía siendo el viejo, sin ningún aviso.
        e_margen = entries["Margen % propio (vacío = heredar de categoría)"]
        e_costo = entries["Costo último"]
        e_precio = entries["Precio de venta"]

        # Si el usuario tipea el precio a mano (no un recalculo nuestro),
        # se respeta tal cual al guardar. Se distingue con KeyRelease en
        # vez de simplemente "cambió el texto": .delete()+.insert() (lo
        # que hace _recalcular_precio) NO dispara KeyRelease, solo lo
        # hace que el usuario realmente escriba ahí.
        precio_manual = {"valor": False}
        e_precio.bind("<KeyRelease>", lambda e: precio_manual.__setitem__("valor", True))

        def _margen_para_calculo():
            """(margen, error) — error es un string para mostrar, o None."""
            margen_txt = e_margen.get().strip()
            if margen_txt:
                try:
                    return float(margen_txt.replace(",", ".")), None
                except ValueError:
                    return None, "Margen inválido."
            cat_id_actual = self._cat_map.get(combo.get())
            cat_actual = get_categoria_por_id(cat_id_actual) if cat_id_actual else None
            margen = (cat_actual["margen_pct"]
                     if cat_actual and cat_actual["margen_pct"] is not None else 30.0)
            return margen, None

        def _recalcular_precio(event=None):
            try:
                costo = float(e_costo.get().strip().replace(",", "."))
            except ValueError:
                return
            margen, error = _margen_para_calculo()
            if error:
                return
            nuevo_precio = round(costo * (1 + margen / 100), 2)
            e_precio.delete(0, "end")
            e_precio.insert(0, f"{nuevo_precio:.2f}")
            precio_manual["valor"] = False  # esto es un recalculo, no algo que tipeó el usuario

        e_margen.bind("<FocusOut>", _recalcular_precio)
        e_margen.bind("<Return>", _recalcular_precio)
        e_margen.bind("<KeyRelease>", _recalcular_precio)
        e_costo.bind("<FocusOut>", _recalcular_precio)
        e_costo.bind("<Return>", _recalcular_precio)
        e_costo.bind("<KeyRelease>", _recalcular_precio)
        lbl(s, "El precio de venta se recalcula solo con el margen y el costo "
              "de arriba — si querés un precio distinto, escribilo después de "
              "tocar estos dos campos.",
            variante="suave", bg=C.superficie,
            wraplength=460, justify="left").pack(padx=20, anchor="w", pady=(2,0))

        var_peso = tk.BooleanVar(value=bool(prod.get("vendido_por_peso")))
        chk_peso = tk.Checkbutton(
            s, text="Vendido por peso (admite cantidad decimal, ej: 0,500 kg)",
            variable=var_peso, bg=C.superficie, fg=C.texto,
            selectcolor=C.superficie, font=F.normal, anchor="w")
        chk_peso.pack(fill="x", padx=20, pady=(10,0))

        # ── Foto del producto ────────────────────────────────────────
        lbl(s, "Foto del producto", variante="suave", bg=C.superficie).pack(
            padx=20, anchor="w", pady=(14,4))

        estado_img = {"url": prod.get("imagen_url") or ""}
        TAM_PREVIEW = 340

        lbl_preview = tk.Label(s, bg=C.borde, width=14, height=7,
                               text="Sin foto", font=F.normal, fg=C.texto_suave)
        lbl_preview.pack(padx=20, anchor="w")

        def _refrescar_preview():
            foto = imagenes.cargar_thumbnail(estado_img["url"],
                                             size=(TAM_PREVIEW, TAM_PREVIEW))
            if foto:
                lbl_preview.configure(image=foto, text="",
                                      width=TAM_PREVIEW, height=TAM_PREVIEW)
                lbl_preview.image = foto   # evita que Tkinter lo recolecte
            else:
                lbl_preview.configure(
                    image="", text=("Sin foto" if not estado_img["url"] else "No se\npudo cargar"),
                    width=14, height=7)
                lbl_preview.image = None

        botones_foto = tk.Frame(s, bg=C.superficie)
        botones_foto.pack(fill="x", padx=20, pady=(8,0))

        def _elegir_archivo():
            ruta = filedialog.askopenfilename(
                parent=d, title="Elegir foto del producto",
                filetypes=[("Imagenes", "*.jpg *.jpeg *.png *.gif *.webp *.bmp")])
            if not ruta:
                return
            try:
                rel = imagenes.guardar_imagen_local(pid, ruta)
                estado_img["url"] = rel
                _refrescar_preview()
            except Exception as e:
                messagebox.showwarning(
                    "Error", f"No se pudo cargar la imagen: {e}", parent=d)

        def _quitar_foto():
            estado_img["url"] = ""
            _refrescar_preview()

        _reloj_clipboard = {"activo": False, "ultimo": None}
        EXT_IMAGEN = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")

        def _leer_clipboard():
            try:
                return d.clipboard_get()
            except tk.TclError:
                return None

        def _parece_url_imagen(texto):
            if not texto or len(texto) > 500 or not imagenes.es_url(texto):
                return False
            return texto.strip().split("?")[0].lower().endswith(EXT_IMAGEN)

        def _revisar_clipboard():
            if not d.winfo_exists() or not _reloj_clipboard["activo"]:
                return
            contenido = _leer_clipboard()
            if contenido != _reloj_clipboard["ultimo"]:
                _reloj_clipboard["ultimo"] = contenido
                if _parece_url_imagen(contenido):
                    _reloj_clipboard["activo"] = False   # ya se aplico, no seguir escuchando
                    e_url.delete(0, "end")
                    e_url.insert(0, contenido)
                    estado_img["url"] = contenido
                    _refrescar_preview()
                    toast(self, "📋 Foto tomada del portapapeles")
                    return
            d.after(600, _revisar_clipboard)

        def _iniciar_deteccion_clipboard():
            _reloj_clipboard["activo"] = True
            _reloj_clipboard["ultimo"] = _leer_clipboard()
            _revisar_clipboard()

        def _buscar_en_internet_fallback(motivo=None):
            """
            Buscar en el navegador de siempre + detectar la URL copiada
            solo. Se usa si el buscador embebido no está disponible en
            esta compu (falta instalar pywebview, o no está el Edge
            WebView2 Runtime de Windows).
            """
            import webbrowser
            from urllib.parse import quote
            desc = entries["Descripción"].get().strip() or prod["descripcion"]
            if motivo:
                messagebox.showinfo(
                    "Buscador embebido no disponible",
                    f"{motivo}\n\nSe abre en el navegador como antes — "
                    "copiá la dirección de la foto y volvé a esta ventana, "
                    "se carga sola.", parent=d)
            webbrowser.open(f"https://www.google.com/search?tbm=isch&q={quote(desc)}")
            _iniciar_deteccion_clipboard()
            toast(self, "🌐 Copiá la dirección de la imagen — se carga sola al volver")

        def _buscar_fotos_embebido():
            desc = entries["Descripción"].get().strip() or prod["descripcion"]
            if not desc:
                messagebox.showinfo(
                    "Buscar fotos", "Escribí primero una descripción para buscar.",
                    parent=d)
                return
            btn_buscar.configure(state="disabled", text="🔍 Buscando... elegí una foto en la ventana")
            ruta_script = os.path.join(os.path.dirname(__file__), "buscador_fotos.py")

            def _trabajar():
                url, error = "", None
                try:
                    resultado = subprocess.run(
                        [sys.executable, ruta_script, desc],
                        capture_output=True, text=True, timeout=300)
                    salida = resultado.stdout.strip()
                    url = salida.splitlines()[-1].strip() if salida else ""
                    if resultado.returncode != 0 and not url:
                        error = (resultado.stderr.strip().splitlines()[-1]
                                if resultado.stderr.strip() else "Error desconocido")
                except FileNotFoundError:
                    error = "No se encontró buscador_fotos.py"
                except Exception as e:
                    error = str(e)

                def _aplicar():
                    if not d.winfo_exists():
                        return
                    btn_buscar.configure(state="normal", text="🔍 Buscar fotos")
                    if error:
                        _buscar_en_internet_fallback(
                            f"No se pudo abrir la ventana de búsqueda "
                            f"({error}).\n\nProbá instalando: pip install pywebview")
                        return
                    if url and imagenes.es_url(url):
                        e_url.delete(0, "end")
                        e_url.insert(0, url)
                        estado_img["url"] = url
                        _refrescar_preview()
                        toast(self, "✅  Foto elegida")
                d.after(0, _aplicar)

            threading.Thread(target=_trabajar, daemon=True).start()

        btn(botones_foto, "📁 Elegir archivo...", variante="neutro",
            comando=_elegir_archivo).pack(fill="x", pady=(0,4))
        btn_buscar = btn(botones_foto, "🔍 Buscar fotos", variante="neutro",
            comando=_buscar_fotos_embebido)
        btn_buscar.pack(fill="x", pady=(0,4))
        btn(botones_foto, "✕ Quitar foto", variante="neutro",
            comando=_quitar_foto).pack(fill="x")

        fila_url = tk.Frame(s, bg=C.superficie)
        fila_url.pack(fill="x", padx=20, pady=(8,0))
        e_url = tk.Entry(fila_url, font=F.normal, bg=C.superficie, fg=C.texto,
                         insertbackground=C.primario, relief="solid", bd=1)
        if imagenes.es_url(estado_img["url"]):
            e_url.insert(0, estado_img["url"])
        e_url.pack(side="left", fill="x", expand=True, ipady=4)

        def _usar_url():
            url = e_url.get().strip()
            if not url:
                return
            if not imagenes.es_url(url):
                messagebox.showwarning(
                    "Error", "Tiene que empezar con http:// o https://", parent=d)
                return
            estado_img["url"] = url
            _refrescar_preview()

        def _descargar_localmente():
            url = estado_img["url"] or e_url.get().strip()
            if not imagenes.es_url(url):
                messagebox.showinfo(
                    "Guardar localmente",
                    "Esto es para guardar en tu compu una foto que está "
                    "puesta como link (URL). Ahora mismo no hay ninguna "
                    "URL cargada para descargar.", parent=d)
                return
            try:
                rel = imagenes.guardar_imagen_desde_url(pid, url)
                estado_img["url"] = rel
                e_url.delete(0, "end")
                _refrescar_preview()
                toast(self, "✅  Foto descargada y guardada en tu compu")
            except Exception as e:
                messagebox.showwarning(
                    "Error", f"No se pudo descargar la imagen: {e}", parent=d)

        btn(fila_url, "Usar URL", variante="neutro",
            comando=_usar_url).pack(side="left", padx=(6,0))
        btn(fila_url, "📥 Guardar localmente", variante="neutro",
            comando=_descargar_localmente).pack(side="left", padx=(6,0))

        _refrescar_preview()

        # Estado y alerta se manejan con los botones dedicados de la lista,
        # se muestran acá solo a modo informativo.
        estado_txt = ("Activo" if prod.get("activo") else "Inactivo")
        alerta_txt = ("desactivada" if prod.get("ignorar_alerta") else "activada")
        lbl(s, f"Estado: {estado_txt}  —  Alerta de stock bajo: {alerta_txt}\n"
               "(se cambian con los botones \"Activar/Desactivar\" y \"Alerta\" de la lista)",
            variante="suave", bg=C.superficie, justify="left").pack(
            padx=20, anchor="w", pady=(12,4))

        def guardar(event=None):
            try:
                costo = float(entries["Costo último"].get().replace(",", "."))
                if costo < 0: raise ValueError
            except ValueError:
                messagebox.showwarning("Error", "Costo inválido.", parent=d)
                return
            margen_txt = entries["Margen % propio (vacío = heredar de categoría)"].get().strip()
            if margen_txt:
                try:
                    margen = float(margen_txt.replace(",", "."))
                    if margen < 0: raise ValueError
                except ValueError:
                    messagebox.showwarning(
                        "Error",
                        "Margen inválido. Dejalo vacío para heredar el de la categoría.",
                        parent=d)
                    return
            else:
                margen = None

            # El precio se recalcula ACÁ (no confiamos en que el
            # recalculo automático del margen/costo haya llegado a
            # dispararse a tiempo) — salvo que el usuario haya tipeado
            # un precio distinto a mano, en cuyo caso se respeta ese.
            precio_txt = entries["Precio de venta"].get().strip()
            if precio_manual["valor"] and precio_txt:
                try:
                    precio = float(precio_txt.replace(",", "."))
                    if precio <= 0: raise ValueError
                except ValueError:
                    messagebox.showwarning("Error", "Precio inválido.", parent=d)
                    return
            else:
                margen_calculo, error = _margen_para_calculo()
                if error:
                    messagebox.showwarning("Error", error, parent=d)
                    return
                precio = round(costo * (1 + margen_calculo / 100), 2)

            cat_id = self._cat_map.get(combo.get())

            # Si el producto tenía una foto guardada localmente y ahora
            # se está reemplazando por otra cosa (una URL, o se quitó),
            # borramos el archivo viejo para no dejarlo huérfano en
            # imagenes_productos/.
            url_original = prod.get("imagen_url") or ""
            url_final = estado_img["url"] or ""
            if (url_original and not imagenes.es_url(url_original)
                    and url_original != url_final):
                imagenes.eliminar_imagen_local(pid)

            actualizar_producto(
                pid,
                entries["Descripción"].get().strip(),
                entries["Código"].get().strip(),
                cat_id,
                precio,
                costo_ultimo=costo,
                margen_pct=margen,
                vendido_por_peso=var_peso.get(),
                imagen_url=estado_img["url"] or None,
                marca=entries["Marca"].get().strip(),
            )
            import catalogo_web
            catalogo_web.sincronizar_stock_en_segundo_plano()
            d.destroy()
            toast(self, "✅  Producto actualizado")
            self._refrescar_productos()

        btn(d, "💾  Guardar cambios", variante="exito", comando=guardar).grid(
            row=2, column=0, sticky="ew", padx=20, pady=20)
        entries["Descripción"].focus_set()

    def _toggle_activo(self):
        pid = self._prod_sel
        if not pid:
            messagebox.showinfo("Atencion", "Selecciona un producto.", parent=self)
            return
        prod = get_producto_completo(pid)
        if not prod: return
        if prod["activo"]:
            if messagebox.askyesno("Desactivar",
                "Desactivar este producto?\nNo aparecera en ventas ni alertas.",
                parent=self):
                toggle_producto_activo(pid, 0)
                toast(self, "Producto desactivado")
        else:
            toggle_producto_activo(pid, 1)
            toast(self, "Producto reactivado")
        self._refrescar_productos()

    def _eliminar(self):
        pid = self._prod_sel
        if not pid:
            messagebox.showinfo("Atencion", "Selecciona un producto.", parent=self)
            return
        prod = get_producto_completo(pid)
        if not prod: return
        ok, motivo = eliminar_producto_si_posible(pid)
        if ok:
            imagenes.eliminar_imagen_local(pid)
            messagebox.showinfo("Eliminado", "Producto eliminado correctamente.", parent=self)
            self._prod_sel = None
            self._refrescar_productos()
        else:
            messagebox.showwarning("No se puede eliminar",
                f"{motivo}\n\nPodes desactivarlo en su lugar.", parent=self)

    # ── Acciones categorías ───────────────────────────────────────────────────

    def _guardar_cat(self):
        nombre = self.entry_cat_nombre.get().strip()
        try:
            margen = float(self.entry_cat_margen.get().replace(",", "."))
        except ValueError:
            messagebox.showwarning("Error", "Margen inválido.", parent=self)
            return
        if not nombre:
            messagebox.showwarning("Error", "Ingresá un nombre.", parent=self)
            return

        cat_id = self._cat_sel_id
        margen_cambio = False
        if cat_id:
            cat_actual = get_categoria_por_id(cat_id)
            if cat_actual and cat_actual["margen_pct"] != margen:
                margen_cambio = True

        guardar_categoria(cat_id, nombre, margen)
        toast(self, "✅  Categoría guardada")

        # Cambiar el margen de la categoría NO recalcula solo los
        # precios ya cargados (el margen solo se usa al crear un
        # producto nuevo o cuando cambia el costo) — por eso "subo el
        # margen y no se ve en ningún lado". Se ofrece acá mismo, con
        # el diagnóstico de antemano para que no quede un "no pasó
        # nada" sin explicación (ej: si todos los productos de esta
        # categoría ya tienen su propio margen cargado, el recálculo
        # legítimamente no cambia nada).
        if margen_cambio:
            diag = diagnostico_recalculo_categoria(cat_id)
            if diag["total"] == 0:
                messagebox.showinfo(
                    "Margen actualizado",
                    f"Guardado. Por ahora \"{nombre}\" no tiene ningún "
                    f"producto activo cargado, así que no hay nada para "
                    f"recalcular todavía.", parent=self)
            elif diag["heredan"] == 0:
                messagebox.showinfo(
                    "Margen actualizado",
                    f"Guardado el nuevo margen ({margen:g}%).\n\n"
                    f"No se recalculó ningún precio: de los "
                    f"{diag['total']} producto(s) activos de \"{nombre}\", "
                    f"{diag['margen_propio']} tienen su propio margen "
                    f"cargado (no usan el de la categoría)"
                    + (f" y {diag['sin_costo']} no tienen costo cargado"
                      if diag["sin_costo"] else "")
                    + (
                        "\n\nPara que el nuevo margen se refleje en esos "
                        "productos, cambiales el margen propio a vacío en "
                        "Editar producto (así vuelven a heredar el de la "
                        "categoría), o cargales el costo si no lo tienen."
                    ),
                    parent=self)
            elif messagebox.askyesno(
                    "Margen actualizado",
                    f"Cambiaste el margen de \"{nombre}\" a {margen:g}%.\n\n"
                    f"Esto afecta a {diag['heredan']} de los "
                    f"{diag['total']} producto(s) activos de la categoría "
                    f"(el resto tiene margen propio y no se toca).\n\n"
                    f"¿Recalcular esos {diag['heredan']} precio(s) ahora?",
                    parent=self):
                n = recalcular_precios_categoria(cat_id)
                messagebox.showinfo(
                    "Listo", f"Precio recalculado en {n} producto(s).",
                    parent=self)
                self._refrescar_productos()

        self._cat_sel_id = None
        self._refrescar_categorias()

    def _nueva_cat(self):
        self._cat_sel_id = None
        self.entry_cat_nombre.delete(0, "end")
        self.entry_cat_margen.delete(0, "end")
        self.entry_cat_margen.insert(0, "30")
        self.entry_cat_nombre.focus_set()

    def _eliminar_cat(self):
        if not self._cat_sel_id:
            messagebox.showinfo("Atención", "Seleccioná una categoría.", parent=self)
            return
        if messagebox.askyesno("Eliminar",
                                "¿Eliminar esta categoría? Los productos quedarán sin categoría.",
                                parent=self):
            eliminar_categoria(self._cat_sel_id)
            self._cat_sel_id = None
            self._nueva_cat()
            toast(self, "Categoría eliminada")
            self._refrescar()

"""
productos_ui.py — Gestión de productos y categorías TPV v2.0
"""

import logging
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
        # Va arriba, junto a los filtros: seleccionar todo es una accion
        # sobre la LISTA (lo que dejo el filtro), no sobre un producto.
        btn(bar, "☑  Seleccionar todo", variante="neutro",
            comando=self._seleccionar_todo_prod).pack(side="left", padx=4)
        btn(bar, "🔢  Códigos propios", variante="neutro",
            comando=self._codigos_propios).pack(side="left", padx=4)
        # Aviso visible cuando hay fotos que dependen de internet: antes
        # el problema solo aparecia en el log, que nadie mira.
        self.lbl_fotos_url = lbl(bar, "", variante="suave")
        self.lbl_fotos_url.pack(side="left", padx=(12, 0))
        btn(bar, "🔄 Actualizar", variante="neutro",
            comando=self._refrescar).pack(side="right")

        # Tabla
        frame_t, self.tree_prod = tabla(parent, COLS_PROD, con_iconos=True)
        # Varios a la vez: marcar para revisar suele hacerse en tanda
        # (todos los que quedaron sin costo, todos los de una categoria).
        self.tree_prod.configure(selectmode="extended")
        # Ctrl+A selecciona lo que se ve, respetando el filtro activo:
        # con un filtro puesto, "todo" es lo filtrado, no el catalogo entero.
        self.tree_prod.bind("<Control-a>", self._seleccionar_todo_prod)
        self.tree_prod.bind("<Control-A>", self._seleccionar_todo_prod)
        frame_t.grid(row=1, column=0, sticky="nsew")
        self.tree_prod.bind("<Double-1>", self._editar_producto)
        self.tree_prod.tag_configure("sin_alerta", foreground=C.texto_suave, font=("Segoe UI", 10))
        self.tree_prod.tag_configure("inactivo",   foreground=C.texto_suave,
                                     font=("Segoe UI", 10, "overstrike"))
        self.tree_prod.bind("<<TreeviewSelect>>", self._on_sel_prod)

        # Acciones en DOS filas: once botones en una sola no entraban a
        # lo ancho y los ultimos quedaban cortados fuera de la pantalla
        # (asi se habia "perdido" el de Etiquetas).
        # Arriba lo que toca el producto; abajo, stock y salidas.
        ac = tk.Frame(parent, bg=C.bg)
        ac.grid(row=2, column=0, sticky="ew", pady=(8,0))
        btn(ac, "Editar",          variante="primario", comando=self._editar_producto).pack(side="left")
        btn(ac, "Activar/Desactivar", variante="peligro", comando=self._toggle_activo).pack(side="left", padx=6)
        btn(ac, "Eliminar",           variante="peligro",  comando=self._eliminar).pack(side="left", padx=6)
        btn(ac, "Presentaciones", variante="neutro",
            comando=self._presentaciones).pack(side="left", padx=6)
        btn(ac, "Redondear precios", variante="neutro",
            comando=self._redondear_precios).pack(side="left", padx=6)
        btn(ac, "📌  Marcar para revisar", variante="neutro",
            comando=self._marcar_revisar).pack(side="left", padx=6)
        btn(ac, "⧉  Duplicar", variante="neutro",
            comando=self._duplicar).pack(side="left", padx=6)
        # Todo lo que termina en papel, junto: eran botones sueltos
        # repartidos entre dos filas y la fila se salia de la pantalla.
        self.btn_imprimir = btn(ac, "🖨  Imprimir…", variante="exito",
                                comando=self._menu_imprimir)
        self.btn_imprimir.pack(side="right")
        lbl(ac, "Doble click para editar", variante="suave").pack(side="right", padx=(12, 0))

        ac2 = tk.Frame(parent, bg=C.bg)
        ac2.grid(row=3, column=0, sticky="ew", pady=(6,0))
        lbl(ac2, "Stock:", variante="suave").pack(side="left", padx=(0, 8))
        btn(ac2, "Ajustar stock", variante="neutro",
            comando=self._ajustar_stock).pack(side="left", padx=(0, 6))
        btn(ac2, "Historial ajustes", variante="neutro",
            comando=self._historial_ajustes).pack(side="left", padx=6)
        btn(ac2, "Vencimientos", variante="neutro",
            comando=self._vencimientos_producto).pack(side="left", padx=6)
        btn(ac2, "Alerta stock ON/OFF", variante="neutro",
            comando=self._toggle_alerta).pack(side="left", padx=6)
        btn(ac2, "Fraccionar", variante="neutro",
            comando=self._abrir_horma).pack(side="left", padx=6)
        btn(ac2, "🖼  Guardar fotos localmente", variante="neutro",
            comando=self._fotos_externas).pack(side="right")

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
        self._chequear_fotos_url()
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
            # Ademas del historial de ajustes, va a la bitacora: ahi se
            # ve junto con anulaciones y devoluciones al explicar un
            # descuadre.
            from repositorio import registrar_bitacora
            dif = nueva - stock_actual
            registrar_bitacora(
                "Ajuste de stock", responsable,
                f"{prod['descripcion']}: {_fmt_cant(stock_actual)} → "
                f"{_fmt_cant(nueva)} ({dif:+g}) — {combo_motivo.get()}",
                abs(dif) * (prod.get("costo_ultimo") or 0), pid)
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

    def _seleccionar_todo_prod(self, event=None):
        """Selecciona las filas VISIBLES (las que dejo el filtro)."""
        hijos = self.tree_prod.get_children()
        self.tree_prod.selection_set(hijos)
        if hijos:
            self.tree_prod.focus(hijos[0])
        return "break"

    def _menu_imprimir(self, event=None):
        """Todo lo que sale en papel, en un solo lugar."""
        m = tk.Menu(self, tearoff=0, font=F.normal,
                    bg=C.superficie, fg=C.texto,
                    activebackground=C.acento, activeforeground=C.texto)
        m.add_command(label="🏷   Etiquetas de góndola   (con código de barras)",
                      command=self._imprimir_etiquetas)
        m.add_command(label="📋   Lista para exhibidora   (sin fotos, letra grande)",
                      command=self._lista_compacta)
        m.add_command(label="🆕   Etiquetas pendientes   (nuevos y cambios de precio)",
                      command=self._etiquetas_pendientes)
        m.add_separator()
        m.add_command(label="📄   Lista de precios   (con fotos y promos)",
                      command=self._lista_precios)
        m.add_command(label="📰   Folleto de ofertas",
                      command=self._folleto)
        m.add_command(label="🖼   Placas para redes",
                      command=self._placas)

        # Debajo del botón, no donde esté el mouse: así siempre aparece
        # en el mismo lugar.
        b = self.btn_imprimir if hasattr(self, "btn_imprimir") else None
        if b is not None:
            m.tk_popup(b.winfo_rootx(),
                       b.winfo_rooty() + b.winfo_height())
        else:
            m.tk_popup(self.winfo_pointerx(), self.winfo_pointery())

    def _lista_precios(self):
        try:
            from lista_precios import abrir_selector_lista_precios
            abrir_selector_lista_precios(self)
        except Exception as exc:
            messagebox.showerror("Lista de precios", str(exc), parent=self)

    def _folleto(self):
        try:
            from folleto_precios import abrir_selector_folleto
            abrir_selector_folleto(self)
        except Exception as exc:
            messagebox.showerror("Folleto", str(exc), parent=self)

    def _placas(self):
        try:
            from placas import abrir_selector_placas
            abrir_selector_placas(self)
        except Exception as exc:
            messagebox.showerror("Placas", str(exc), parent=self)

    def _etiquetas_pendientes(self):
        """Productos nuevos y con precio cambiado, para imprimir su etiqueta."""
        from etiquetas_pendientes_ui import abrir_etiquetas_pendientes
        abrir_etiquetas_pendientes(self)

    def _lista_compacta(self):
        """Lista sin fotos para pegar en la heladera o la góndola."""
        from lista_compacta import abrir_selector_lista_compacta
        abrir_selector_lista_compacta(self)

    def _codigos_propios(self):
        """Genera codigos de barras propios para lo que no tiene.

        Un producto con codigo inventado ("QCREM-FRAC") no se puede
        escanear: la etiqueta sale sin codigo legible y en cada venta
        hay que buscarlo por nombre. Con un EAN-13 del rango interno
        (200-299, reservado por el estandar) se imprime y funciona como
        cualquier producto de fabrica.
        """
        from repositorio import productos_sin_codigo_valido, asignar_codigo_interno
        pendientes = productos_sin_codigo_valido()
        if not pendientes:
            messagebox.showinfo(
                "Códigos propios",
                "Todos los productos tienen un código de barras válido.",
                parent=self)
            return

        def _motivo(cod):
            """Por que ese codigo no sirve. Verlo evita reemplazar uno bueno."""
            c = "".join(ch for ch in str(cod or "") if ch.isdigit())
            if not cod:
                return "sin código"
            if not c:
                return f"«{cod}» no es numérico"
            if len(c) not in (8, 12, 13):
                return f"«{cod}» tiene {len(c)} dígitos (no es EAN)"
            return f"«{cod}» tiene el dígito verificador mal"

        muestra = "\n".join(
            f"  · {p['descripcion'][:34]}  —  {_motivo(p['codigo'])}"
            for p in pendientes[:10])
        extra = (f"\n  ...y {len(pendientes) - 10} más"
                 if len(pendientes) > 10 else "")

        if not messagebox.askyesno(
                "Códigos propios",
                f"{len(pendientes)} producto(s) no tienen un código que se "
                f"pueda escanear:\n\n{muestra}{extra}\n\n"
                "Se les va a generar un código EAN-13 propio (empieza en "
                "200, que el estándar reserva para uso interno y nunca "
                "choca con uno de fábrica).\n\n"
                "Los que ya tienen un código de fábrica válido — de 13, 12 "
                "u 8 dígitos — no aparecen acá y no se tocan.\n\n"
                "Después imprimí sus etiquetas y quedan listos para "
                "escanear.\n\n¿Los genero?", parent=self):
            return

        hechos = []
        for p in pendientes:
            try:
                hechos.append((p["descripcion"], asignar_codigo_interno(p["id"])))
            except Exception as exc:
                logging.warning(f"No se pudo asignar codigo a {p['id']}: {exc}")

        det = "\n".join(f"  {d[:34]}: {c}" for d, c in hechos[:10])
        mas = f"\n  ...y {len(hechos) - 10} más" if len(hechos) > 10 else ""
        messagebox.showinfo(
            "Códigos propios",
            f"{len(hechos)} código(s) generados:\n\n{det}{mas}\n\n"
            "Imprimí las etiquetas desde «🏷 Etiquetas de góndola» para "
            "poder escanearlos.", parent=self)
        self._refrescar()

    def _chequear_fotos_url(self):
        """Cuenta las fotos que apuntan a internet y lo muestra."""
        try:
            import imagenes
            n = len(imagenes.productos_con_foto_externa())
        except Exception:
            return
        if n:
            self.lbl_fotos_url.config(
                text=(f"⚠ {n} producto(s) sin foto propia — "
                      f"clic acá para resolverlo"), cursor="hand2")
            self.lbl_fotos_url.bind("<Button-1>",
                                    lambda e: self._fotos_externas())
        else:
            self.lbl_fotos_url.config(text="", cursor="")

    def _fotos_externas(self):
        """Baja a la carpeta del sistema las fotos que hoy son una URL.

        Son fotos elegidas a mano: se conservan, no se borran. Lo que se
        arregla es que dejen de depender de un sitio ajeno, que es lo que
        cuelga la pantalla cuando responde lento.
        """
        import imagenes
        externas = imagenes.productos_con_foto_externa()
        if not externas:
            messagebox.showinfo(
                "Fotos por URL",
                "Todas las fotos ya están guardadas en la carpeta del "
                "sistema. No hay ninguna que dependa de internet.",
                parent=self)
            return

        # Dos salidas reales: intentar bajarlas, o dejarlos sin foto para
        # cargarles una propia. Las fotos externas no se muestran en la
        # grilla, asi que dejarlas como estan no es una opcion util.
        resp = messagebox.askyesnocancel(
            "Fotos por URL",
            f"{len(externas)} producto(s) tienen la foto apuntando a un "
            f"sitio de internet. Esas fotos NO se muestran en la lista: "
            f"bajarlas en cada repintado trababa la pantalla.\n\n"
            f"SÍ  → intentar descargarlas ahora ({len(externas)} descargas, "
            f"puede tardar y muchas pueden fallar si el sitio no responde).\n\n"
            f"NO  → dejar esos productos sin foto, para cargarles una propia "
            f"con «Buscar fotos» o subiendo la tuya.\n\n"
            f"CANCELAR → no hacer nada.", parent=self)

        if resp is None:
            return
        if resp is False:
            if not messagebox.askyesno(
                    "Quitar las fotos por URL",
                    f"Se les va a quitar la foto a {len(externas)} "
                    f"producto(s).\n\nEl producto no se toca: solo queda "
                    f"sin foto, listo para cargarle una propia.\n\n"
                    "¿Confirmás?", parent=self):
                return
            r = imagenes.quitar_fotos_externas()
            toast(self, f"{r['quitadas']} producto(s) quedaron sin foto")
            self._refrescar()
            return

        # Ventana de progreso: con decenas de fotos, sin esto la app
        # parece colgada varios minutos.
        prog = tk.Toplevel(self)
        prog.title("Guardando fotos")
        prog.configure(bg=C.superficie)
        prog.grab_set()
        prog.geometry("460x150")
        lbl(prog, "Descargando fotos…", variante="titulo",
            bg=C.superficie).pack(anchor="w", padx=18, pady=(16, 4))
        barra = ttk.Progressbar(prog, mode="determinate",
                                maximum=len(externas))
        barra.pack(fill="x", padx=18)
        lbl_act = tk.Label(prog, text="", bg=C.superficie, fg=C.texto_suave,
                           font=F.pequeña, anchor="w")
        lbl_act.pack(fill="x", padx=18, pady=(8, 0))

        def _avance(hecho, total, desc):
            barra["value"] = hecho
            lbl_act.config(text=f"{hecho} de {total} — {desc[:44]}")
            prog.update_idletasks()

        try:
            r = imagenes.descargar_fotos_externas(progreso=_avance)
        except Exception as exc:
            prog.destroy()
            messagebox.showerror("Fotos por URL", f"Falló la descarga:\n{exc}",
                                 parent=self)
            return
        prog.destroy()

        msg = f"{r['ok']} de {r['total']} foto(s) guardadas en la carpeta."
        if r["errores"]:
            detalle = "\n".join(f"  · {e}" for e in r["errores"][:6])
            extra = (f"\n  ...y {len(r['errores']) - 6} más"
                     if len(r["errores"]) > 6 else "")
            msg += (f"\n\nNo se pudieron bajar {len(r['errores'])}:\n\n"
                    f"{detalle}{extra}\n\n"
                    "Esas siguen apuntando a internet. Si el sitio ya las "
                    "borró, cargales una foto propia desde Editar producto.")
        messagebox.showinfo("Fotos por URL", msg, parent=self)
        # La cache de fallidas guarda las que ya no responden: se limpia
        # para que un reintento posterior valga la pena.
        imagenes._URLS_FALLIDAS.clear()
        self._refrescar()

    def _duplicar(self):
        """Copia un producto para dar de alta otra variedad o tamaño.

        Todo viene precargado del original: cargando diez variedades
        seguidas, lo único que cambia es el nombre y la cantidad. Al
        guardar registra el ingreso de stock, así el producto queda
        listo para vender sin pasar por otra pantalla.
        """
        from repositorio import (duplicar_producto, registrar_lote,
                                 get_categorias, get_proveedores)
        pid = self._prod_sel
        if not pid:
            messagebox.showinfo("Duplicar", "Elegí un producto de la lista.",
                                parent=self)
            return
        orig = get_producto_completo(pid)
        if not orig:
            return

        d = tk.Toplevel(self)
        d.title("Duplicar producto")
        d.configure(bg=C.superficie)
        d.grab_set()
        _centrar(d, 520, min(620, d.winfo_screenheight() - 90))

        lbl(d, "Duplicar producto", variante="titulo",
            bg=C.superficie).pack(anchor="w", padx=18, pady=(16, 2))
        lbl(d, f"Copia de: {orig['descripcion'][:42]}", variante="suave",
            bg=C.superficie).pack(anchor="w", padx=18)

        # El pie primero y anclado abajo, para que el cuerpo no lo empuje
        pie = tk.Frame(d, bg=C.superficie)
        pie.pack(side="bottom", fill="x", pady=14)

        cuerpo = tk.Frame(d, bg=C.superficie)
        cuerpo.pack(fill="both", expand=True, padx=18, pady=(10, 0))

        def _campo(etq, valor, ancho=None):
            lbl(cuerpo, etq, variante="suave", bg=C.superficie).pack(
                anchor="w", pady=(8, 2))
            v = tk.StringVar(value="" if valor is None else str(valor))
            e = tk.Entry(cuerpo, textvariable=v, font=F.normal, bg=C.bg,
                         fg=C.texto, relief="solid", bd=1)
            e.pack(fill="x", ipady=4)
            return v, e

        v_desc, e_desc = _campo("Nombre del producto nuevo",
                                orig["descripcion"])
        v_cod, _ = _campo("Código de barras (vacío = se genera uno propio)", "")

        # Categoría y marca copiadas, editables
        lbl(cuerpo, "Categoría", variante="suave", bg=C.superficie).pack(
            anchor="w", pady=(8, 2))
        cats = get_categorias()
        v_cat = tk.StringVar(value=next(
            (c["nombre"] for c in cats if c["id"] == orig.get("categoria_id")),
            cats[0]["nombre"] if cats else ""))
        ttk.Combobox(cuerpo, textvariable=v_cat, state="readonly",
                     values=[c["nombre"] for c in cats]).pack(fill="x")

        v_marca, _ = _campo("Marca", orig.get("marca") or "")

        # Costo y precio en una fila
        f3 = tk.Frame(cuerpo, bg=C.superficie)
        f3.pack(fill="x", pady=(8, 0))
        f3.columnconfigure(0, weight=1)
        f3.columnconfigure(1, weight=1)
        vals = {}
        for i, (etq, clave, val) in enumerate((
                ("Costo", "costo", orig.get("costo_ultimo") or 0),
                ("Precio de venta", "precio", orig.get("precio_base") or 0))):
            tk.Label(f3, text=etq, bg=C.superficie, fg=C.texto_suave,
                     font=F.pequeña, anchor="w").grid(row=0, column=i,
                                                      sticky="w")
            v = tk.StringVar(value=f"{float(val):.2f}")
            tk.Entry(f3, textvariable=v, font=F.normal, justify="center",
                     bg=C.bg, fg=C.texto, relief="solid", bd=1).grid(
                row=1, column=i, sticky="ew", padx=(0, 8), ipady=4)
            vals[clave] = v

        # Stock inicial: es lo que se viene a cargar
        por_peso = bool(orig.get("vendido_por_peso"))
        f4 = tk.Frame(cuerpo, bg=C.acento, padx=12, pady=10)
        f4.pack(fill="x", pady=(12, 0))
        tk.Label(f4, text=("¿Cuántos kg entraron?" if por_peso
                           else "¿Cuántas unidades entraron?"),
                 bg=C.acento, fg=C.texto, font=F.normal,
                 anchor="w").pack(anchor="w")
        v_cant = tk.StringVar(value="")
        e_cant = tk.Entry(f4, textvariable=v_cant, font=F.subtitulo,
                          justify="center", bg=C.bg, fg=C.texto,
                          relief="solid", bd=1)
        e_cant.pack(fill="x", ipady=5, pady=(4, 0))
        tk.Label(f4, text="Vacío = se crea sin stock", bg=C.acento,
                 fg=C.texto_suave, font=F.pequeña,
                 anchor="w").pack(anchor="w", pady=(4, 0))

        # Proveedor, copiado del último ingreso del original
        lbl(cuerpo, "Proveedor", variante="suave", bg=C.superficie).pack(
            anchor="w", pady=(8, 2))
        try:
            provs = [{"id": None, "nombre": "—"}] + list(get_proveedores())
        except Exception:
            provs = [{"id": None, "nombre": "—"}]
        v_prov = tk.StringVar(value="—")
        ttk.Combobox(cuerpo, textvariable=v_prov, state="readonly",
                     values=[p["nombre"] for p in provs]).pack(fill="x")

        v_vence, _ = _campo("Vencimiento (DD/MM/AAAA, opcional)", "")

        def guardar(_ev=None, seguir=False):
            desc = v_desc.get().strip()
            if not desc:
                messagebox.showwarning("Duplicar", "Poné un nombre.", parent=d)
                return
            if desc == orig["descripcion"]:
                messagebox.showwarning(
                    "Duplicar", "El nombre es igual al original.\n\n"
                    "Cambiá la variedad o el tamaño para distinguirlos.",
                    parent=d)
                return
            try:
                costo = float(vals["costo"].get().replace(",", "."))
                precio = float(vals["precio"].get().replace(",", "."))
            except ValueError:
                messagebox.showwarning("Duplicar", "El costo o el precio no "
                                                   "son números.", parent=d)
                return
            cant = 0.0
            txt = v_cant.get().strip().replace(",", ".")
            if txt:
                try:
                    cant = float(txt)
                except ValueError:
                    messagebox.showwarning("Duplicar", "La cantidad no es un "
                                                       "número.", parent=d)
                    return
                if cant < 0:
                    messagebox.showwarning("Duplicar", "La cantidad no puede "
                                                       "ser negativa.", parent=d)
                    return

            try:
                nuevo = duplicar_producto(pid, desc, v_cod.get().strip())
            except Exception as exc:
                messagebox.showerror("Duplicar", str(exc), parent=d)
                return

            # Categoría, marca, costo y precio pueden haberse editado
            cat_id = next((c["id"] for c in cats if c["nombre"] == v_cat.get()),
                          orig.get("categoria_id"))
            try:
                actualizar_producto(
                    nuevo, desc, None, cat_id, precio, costo,
                    orig.get("margen_pct"),
                    int(bool(orig.get("vendido_por_peso"))),
                    None, v_marca.get().strip())
            except Exception:
                pass

            # El ingreso de stock, con el mismo costo
            if cant > 0:
                prov_id = next((p["id"] for p in provs
                                if p["nombre"] == v_prov.get()), None)
                vence = v_vence.get().strip() or None
                if vence:
                    # Se acepta DD/MM/AAAA, que es como lo escribe uno,
                    # y se guarda como AAAA-MM-DD, que es lo que entiende
                    # la base.
                    from datetime import datetime as _dt
                    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y"):
                        try:
                            vence = _dt.strptime(vence, fmt).strftime("%Y-%m-%d")
                            break
                        except ValueError:
                            continue
                    else:
                        vence = None
                try:
                    registrar_lote(nuevo, prov_id, cant, costo, vence,
                                   "Alta por duplicado")
                except Exception as exc:
                    messagebox.showwarning(
                        "Duplicar",
                        f"El producto se creó, pero no se pudo cargar el "
                        f"stock:\n{exc}", parent=d)

            d.destroy()
            self._refrescar_productos()
            self._prod_sel = nuevo
            try:
                self.tree_prod.selection_set(str(nuevo))
                self.tree_prod.see(str(nuevo))
            except Exception:
                pass
            unidad = "kg" if por_peso else "u."
            toast(self, (f"«{desc[:26]}» creado con {cant:g} {unidad}"
                         if cant else f"«{desc[:26]}» creado sin stock"))
            if seguir:
                # Otra variedad del MISMO original: se vuelve a abrir con
                # todo cargado, que es el caso de dar de alta diez seguidas.
                self._prod_sel = pid
                self.after(80, self._duplicar)

        d.bind("<Return>", guardar)
        d.bind("<Escape>", lambda ev: d.destroy())
        btn(pie, "Guardar  (Enter)", variante="exito",
            comando=guardar).pack(side="left", padx=(18, 6))
        btn(pie, "Guardar y otra variedad", variante="primario",
            comando=lambda: guardar(seguir=True)).pack(side="left", padx=6)
        btn(pie, "Cancelar", variante="neutro",
            comando=d.destroy).pack(side="left")

        e_desc.focus_set()
        # El cursor al final: lo que cambia suele ser la última palabra
        e_desc.icursor("end")
        e_desc.xview_moveto(1)

    def _marcar_revisar(self):
        """Manda los productos seleccionados a la cola de revision.

        Acepta varios: lo normal es detectar un problema mirando la
        lista (varios sin costo, varios de una categoria dudosa) y
        querer marcarlos todos de una.
        """
        sel = self.tree_prod.selection()
        ids = [int(i) for i in sel] if sel else (
            [self._prod_sel] if self._prod_sel else [])
        if not ids:
            messagebox.showinfo("Atención", "Seleccioná al menos un producto.",
                                parent=self)
            return
        desc = ""
        if len(ids) == 1:
            from repositorio import get_producto_completo
            desc = (get_producto_completo(ids[0]) or {}).get("descripcion", "")
        from revision_ui import dialogo_marcar
        if dialogo_marcar(self, ids, desc):
            toast(self, f"{len(ids)} producto(s) marcado(s) — mirá la solapa "
                        f"«A revisar»")

    def _redondear_precios(self):
        """Toca el precio de TODO el catalogo de una."""
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
        modo = str(cfg().get("redondeo_modo", "cercano")).lower()
        explica = {
            "cercano": (f"al múltiplo de ${paso} más cercano: menos de la mitad "
                        f"baja, más de la mitad sube"),
            "arriba":  f"siempre al siguiente múltiplo de ${paso} (nunca baja)",
            "abajo":   f"siempre al múltiplo de ${paso} anterior (nunca sube)",
        }.get(modo, f"al múltiplo de ${paso} más cercano")
        if not messagebox.askyesno(
                "Redondear precios",
                f"Se van a redondear TODOS los precios activos {explica}.\n\n"
                "¿Confirmás?", parent=self):
            return
        r = redondear_todos_los_precios(paso, modo=modo)
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
        # Acotado a la pantalla: con 990 px fijos el boton Guardar
        # quedaba abajo del borde en cualquier notebook.
        _centrar(d, 520, min(990, d.winfo_screenheight() - 90))
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
                        # Se baja en el momento: guardar la URL dejaba la
                        # foto colgada de un sitio ajeno, y esas no se
                        # muestran en la grilla.
                        try:
                            imagenes.PERMITIR_DESCARGA_URL = True
                            rel = imagenes.guardar_imagen_desde_url(pid, url)
                            estado_img["url"] = rel
                            e_url.delete(0, "end")
                            toast(self, "✅  Foto guardada")
                        except Exception as exc:
                            messagebox.showwarning(
                                "No se pudo bajar la foto",
                                f"{exc}\n\nProbá con otra imagen de la "
                                "búsqueda.", parent=d)
                            return
                        finally:
                            imagenes.PERMITIR_DESCARGA_URL = False
                        _refrescar_preview()
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
            """Baja la foto y la guarda local. Guardar la URL cruda hacia
            que la foto dependiera de un sitio ajeno: no se mostraba en la
            grilla y desaparecia el dia que la borraran de alla."""
            url = e_url.get().strip()
            if not url:
                return
            if not imagenes.es_url(url):
                messagebox.showwarning(
                    "Error", "Tiene que empezar con http:// o https://", parent=d)
                return
            d.config(cursor="watch"); d.update_idletasks()
            try:
                imagenes.PERMITIR_DESCARGA_URL = True
                rel = imagenes.guardar_imagen_desde_url(pid, url)
            except Exception as exc:
                messagebox.showwarning(
                    "No se pudo bajar la foto",
                    f"{exc}\n\nProbá con otra imagen, o descargala a tu "
                    "compu y usá «Guardar localmente».", parent=d)
                return
            finally:
                imagenes.PERMITIR_DESCARGA_URL = False
                d.config(cursor="")
            estado_img["url"] = rel
            e_url.delete(0, "end")
            _refrescar_preview()
            toast(self, "✅  Foto guardada en la carpeta del sistema")

        def _descargar_localmente():
            # Deja la foto dentro de imagenes_productos/ venga de donde
            # venga: una URL, un archivo suelto del disco, o eligiendo uno
            # ahora. Antes solo servia para URLs y con una foto local ya
            # cargada no hacia nada.
            origen = e_url.get().strip() or estado_img["url"]

            if not origen:
                ruta = filedialog.askopenfilename(
                    title="Elegí la foto del producto",
                    filetypes=[("Imágenes", "*.jpg *.jpeg *.png *.webp *.bmp"),
                               ("Todos", "*.*")], parent=d)
                if not ruta:
                    return
                origen = ruta

            try:
                rel, que_paso = imagenes.incorporar_imagen(pid, origen)
            except Exception as e:
                messagebox.showwarning(
                    "Guardar localmente",
                    f"No se pudo guardar la imagen:\n\n{e}", parent=d)
                return

            if que_paso == "ya_estaba":
                messagebox.showinfo(
                    "Guardar localmente",
                    "Esta foto ya está guardada en la carpeta del sistema.\n\n"
                    f"{rel}", parent=d)
                return

            estado_img["url"] = rel
            e_url.delete(0, "end")
            _refrescar_preview()
            toast(self, "✅  Foto guardada en la carpeta del sistema"
                        if que_paso == "copiada"
                        else "✅  Foto descargada y guardada")

        btn(fila_url, "Bajar y usar", variante="primario",
            comando=_usar_url).pack(side="left", padx=(6,0))
        btn(fila_url, "📁 Desde mi compu", variante="neutro",
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

            # Vender bajo costo puede ser deliberado (liquidar algo por
            # vencer), pero por descuido es plata que se pierde en cada
            # venta sin que nada lo marque.
            if costo and precio < costo:
                if not messagebox.askyesno(
                        "Precio por debajo del costo",
                        f"El precio ($ {precio:,.2f}) queda por debajo del "
                        f"costo ($ {costo:,.2f}).\n\n"
                        f"Perdés $ {costo - precio:,.2f} en cada unidad que "
                        f"vendas.\n\n¿Guardar igual?", parent=d):
                    entries["Precio de venta"].focus_set()
                    entries["Precio de venta"].select_range(0, "end")
                    return

            # El costo vive en DOS lugares: acá y en cada lote. La
            # rentabilidad lee el lote, así que corregir sólo el producto
            # deja el informe mostrando la ganancia vieja.
            costo_previo = float(prod.get("costo_ultimo") or 0)
            hay_que_alinear = costo and abs(costo - costo_previo) > 0.01

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

            # Si cambió el costo, los lotes que quedan en stock siguen
            # con el viejo y la rentabilidad los sigue usando.
            if hay_que_alinear:
                from repositorio import lotes_descuadrados, alinear_lotes_con_producto
                pendientes = [x for x in lotes_descuadrados(solo_con_stock=True)
                              if x["producto_id"] == pid]
                if pendientes:
                    unidades = sum(x["cantidad_restante"] for x in pendientes)
                    if messagebox.askyesno(
                            "Costo de los lotes en stock",
                            f"Cambiaste el costo a $ {costo:,.2f}, pero "
                            f"{len(pendientes)} lote(s) con stock "
                            f"({unidades:g} unidad(es)) siguen cargados con "
                            f"$ {pendientes[0]['costo_unitario']:,.2f}.\n\n"
                            "La rentabilidad se calcula con el costo del "
                            "lote, así que si no se corrigen, el informe va "
                            "a seguir mostrando la ganancia vieja.\n\n"
                            "¿Les pongo el costo nuevo?\n\n"
                            "(Los lotes ya agotados no se tocan: esas "
                            "compras ya pasaron.)", parent=self):
                        n = alinear_lotes_con_producto(pid)
                        toast(self, f"{n} lote(s) alineados al costo nuevo")
                        self._refrescar_productos()
                        return
            toast(self, "✅  Producto actualizado")
            self._refrescar_productos()

        pie = tk.Frame(d, bg=C.superficie)
        pie.grid(row=2, column=0, sticky="ew", padx=20, pady=(10, 16))
        pie.columnconfigure(0, weight=1)
        btn(pie, "💾  Guardar cambios  (Enter)", variante="exito",
            comando=guardar).grid(row=0, column=0, sticky="ew")
        lbl(pie, "Esc cancela", variante="suave", bg=C.superficie).grid(
            row=1, column=0, pady=(6, 0))

        # Enter guarda, salvo en los campos de texto libre: ahi se escribe
        # y un Enter de mas guardaria lo que hubiera quedado tipeado.
        _texto_libre = [entries["Descripción"], entries["Marca"]]

        def _enter(_ev=None):
            if d.focus_get() in _texto_libre:
                e_precio.focus_set()
                e_precio.select_range(0, "end")
                return "break"
            return guardar()

        d.bind("<Return>", _enter)
        d.bind("<KP_Enter>", _enter)
        d.bind("<Escape>", lambda ev: d.destroy())

        # El foco NO va en la descripcion: arrancaba con el texto
        # seleccionado y cualquier tecla lo reemplazaba entero.
        e_precio.focus_set()
        e_precio.select_range(0, "end")

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
        """Eliminar un producto borra su historial de ventas asociado."""
        pid = self._prod_sel
        if not pid:
            messagebox.showinfo("Atencion", "Selecciona un producto.", parent=self)
            return
        prod = get_producto_completo(pid)
        if not prod: return

        from fiado_ui import pedir_autorizacion
        responsable = pedir_autorizacion(
            self, f"Eliminar «{prod['descripcion']}» del catálogo.")
        if not responsable:
            return

        ok, motivo = eliminar_producto_si_posible(pid)
        if ok:
            from repositorio import registrar_bitacora
            registrar_bitacora("Eliminacion de producto", responsable,
                               f"{prod['descripcion']} (cod {prod.get('codigo') or '—'})",
                               None, pid)
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

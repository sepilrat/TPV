"""
ingreso_ui.py — Ingreso de stock TPV v2.0
Lotes con proveedor, costo y vencimiento. FIFO automático.
"""

import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
import threading
import logging
import os
import sys
import subprocess
import imagenes
from styles import C, F, btn, lbl, card, tabla, toast, header_seccion, scrollable
from repositorio import (get_proveedores, get_categorias, crear_proveedor,
                         crear_producto, registrar_lote, get_lotes_recientes,
                         evaluar_cambio_costo, actualizar_proveedor_lote,
                         get_stock_critico, get_stock_producto,
                         get_producto_por_codigo, actualizar_imagen_producto)

# ─────────────────────────────────────────────────────────────────────────────
# Helpers DB locales
# ─────────────────────────────────────────────────────────────────────────────

COLS_LOTES = [
    ("desc",     "Producto",    200, "w"),
    ("codigo",   "Codigo",       90, "w"),
    ("tipo",     "Tipo",         90, "w"),
    ("cant",     "Ingresado",    75, "e"),
    ("restante", "Disponible",   75, "e"),
    ("costo",    "Costo u.",     80, "e"),
    ("prov",     "Proveedor",   100, "w"),
    ("fecha",    "Ingreso",      90, "w"),
    ("vence",    "Vencimiento",  90, "w"),
]

COLS_CRITICO = [
    ("desc",   "Producto", 280, "w"),
    ("codigo", "Codigo",    90, "w"),
    ("stock",  "Stock",     60, "e"),
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


def _fmt_cant(v):
    """Formatea cantidad: entera sin decimales, fraccionaria con hasta
    3 decimales (para productos vendidos por peso)."""
    v = float(v)
    if v == int(v):
        return str(int(v))
    return f"{v:.3f}".rstrip("0").rstrip(".")

class IngresoUI(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._producto_actual = None
        self._foto_nueva_url = None
        self._build()
        self.refrescar()


    def refrescar(self):
        self._refrescar_lotes()
        self._refrescar_critico()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build(self):
        # Registra el ingreso de mercadería por lotes.
        # Escanea el código, carga cantidad, costo y vencimiento.
        # El stock se descuenta automáticamente al vender (método FIFO).
        header_seccion(self, "Ingreso de Stock",
            "Registra lotes de mercaderia con costo y vencimiento — FIFO"
        ).pack(fill="x", padx=12, pady=(8,4))

        barra_factura = tk.Frame(self, bg=C.bg)
        barra_factura.pack(fill="x", padx=12, pady=(0,4))
        btn(barra_factura, "📷  Importar factura (foto)", variante="neutro",
            comando=self._importar_factura).pack(side="left")

        self._contenedor = tk.Frame(self, bg=C.bg)
        self._contenedor.pack(fill="both", expand=True)
        self._contenedor.columnconfigure(0, weight=2)
        self._contenedor.columnconfigure(1, weight=3)
        self._contenedor.rowconfigure(0, weight=1)
        self._panel_form()
        self._panel_tablas()

    def _importar_factura(self):
        from factura_ui import abrir_importar_factura
        abrir_importar_factura(self)

    def _panel_form(self):
        """
        Panel izquierdo — layout compacto en grilla 2x para entrar en una pantalla.
        Fila 1: Codigo + Buscar
        Fila 2: Info producto
        Fila 3: Cantidad | Costo
        Fila 4: Vencimiento | Proveedor
        Fila 5: Notas
        Fila 6: (precio + cat — solo prod nuevo)
        Fila 7: Boton guardar
        """
        outer, p = scrollable(self._contenedor)
        outer.grid(row=0, column=0, sticky="nsew", padx=(12,6), pady=12)
        p.columnconfigure(0, weight=1)
        p.columnconfigure(1, weight=1)

        # ── Fila 0: Scanner ───────────────────────────────────
        c_scan = card(p)
        c_scan.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0,6))
        c_scan.columnconfigure(0, weight=1)

        lbl(c_scan, "Codigo de barras", variante="suave",
            bg=C.superficie).grid(row=0, column=0, columnspan=2,
                                   sticky="w", padx=12, pady=(8,2))
        self.entry_codigo = tk.Entry(c_scan, font=("Segoe UI", 13),
                                      bg=C.superficie, fg=C.texto,
                                      insertbackground=C.primario,
                                      relief="solid", bd=1)
        self.entry_codigo.grid(row=1, column=0, sticky="ew",
                                padx=(12,4), pady=(0,10), ipady=8)
        self.entry_codigo.bind("<Return>", self._buscar_producto)
        btn(c_scan, "Buscar", variante="primario",
            comando=self._buscar_producto).grid(row=1, column=1,
                                                padx=(0,12), pady=(0,10))

        # ── Fila 1: Info producto ─────────────────────────────
        self.frame_info = tk.Frame(p, bg=C.bg)
        self.frame_info.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0,4))
        self.lbl_info = lbl(self.frame_info, "", variante="suave")
        self.lbl_info.pack(anchor="w")
        self.btn_editar_nombre = btn(
            self.frame_info, "✏️  Corregir nombre o precio", variante="neutro",
            comando=lambda: self._editar_producto_actual())

        # ── Formulario compacto ───────────────────────────────
        self.card_form = card(p)
        self.card_form.grid(row=2, column=0, columnspan=2, sticky="nsew")
        self.card_form.columnconfigure(0, weight=1)
        self.card_form.columnconfigure(1, weight=1)
        p.rowconfigure(2, weight=1)

        def _lbl(parent, texto, row, col, colspan=1):
            lbl(parent, texto, variante="suave", bg=C.superficie).grid(
                row=row, column=col, columnspan=colspan,
                sticky="w", padx=(12,4), pady=(6,0))

        def _entry(parent, row, col, default="", colspan=1):
            e = tk.Entry(parent, font=F.normal, bg=C.superficie, fg=C.texto,
                         insertbackground=C.primario, relief="solid", bd=1)
            e.insert(0, default)
            e.grid(row=row, column=col, columnspan=colspan,
                   sticky="ew", padx=(12,4), pady=(2,0), ipady=5)
            return e

        def _placeholder(entry, texto):
            """
            Texto de referencia gris (ej "0.00", "AAAA-MM-DD") que se borra
            solo al tocar el campo, en vez de tener que seleccionarlo y
            borrarlo a mano. Si lo dejan vacío al salir, vuelve a aparecer.
            """
            def _mostrar():
                entry.delete(0, "end")
                entry.insert(0, texto)
                entry.config(fg=C.texto_suave)

            def _focus_in(e):
                if entry.get() == texto and str(entry.cget("fg")) == C.texto_suave:
                    entry.delete(0, "end")
                    entry.config(fg=C.texto)

            def _focus_out(e):
                if not entry.get().strip():
                    _mostrar()

            entry._mostrar_placeholder = _mostrar
            entry._texto_placeholder = texto
            # add="+" para no pisar binds que ya tenga el campo: sin esto,
            # cualquier <FocusIn> definido antes se perdia en silencio.
            entry.bind("<FocusIn>", _focus_in, add="+")
            entry.bind("<FocusOut>", _focus_out, add="+")
            _mostrar()

        # Cantidad | Costo
        _lbl(self.card_form, "Cantidad *",      0, 0)
        _lbl(self.card_form, "Costo unitario *",0, 1)
        self.entry_cantidad = _entry(self.card_form, 1, 0, "1")
        self.entry_costo    = _entry(self.card_form, 1, 1, "")
        _placeholder(self.entry_costo, "0.00")

        # En el ticket del mayorista figura el TOTAL de la linea, no el
        # unitario: "12 un. x $2.220 = $26.640". Tener que dividir a mano
        # es donde se cuelan los costos mal cargados.
        # Va en su propia fila, ocupando el ancho: meterlo como tercera
        # columna corria todos los campos de abajo.
        f_tot = tk.Frame(self.card_form, bg=C.superficie)
        f_tot.grid(row=2, column=0, columnspan=2, sticky="ew",
                   padx=(12, 4), pady=(2, 4))
        tk.Label(f_tot, text="¿El ticket muestra el total?", bg=C.superficie,
                 fg=C.texto_suave, font=F.pequeña).pack(side="left")
        self.entry_total_linea = tk.Entry(f_tot, font=F.normal, width=12,
                                          bg=C.bg, fg=C.texto,
                                          relief="solid", bd=1)
        self.entry_total_linea.pack(side="left", padx=6, ipady=2)
        _placeholder(self.entry_total_linea, "14000.00")


        def _desde_total(*_a):
            """Total ÷ cantidad = unitario. Se recalcula al escribir."""
            # El placeholder es texto real dentro del Entry. En vez de
            # adivinar por color (que no distingue "escrito" de "aun con
            # placeholder"), se compara contra el texto del placeholder.
            e_tot = self.entry_total_linea
            txt = e_tot.get().strip().replace(",", ".")
            if not txt or txt == getattr(e_tot, "_texto_placeholder", None):
                return
            try:
                total = float(txt)
                cant = float((self.entry_cantidad.get() or "1")
                             .strip().replace(",", "."))
            except ValueError:
                return
            if cant <= 0 or total <= 0:
                return
            unit = total / cant
            self.entry_costo.delete(0, "end")
            self.entry_costo.insert(0, f"{unit:.2f}")
            self.entry_costo.config(fg=C.texto)


        self.entry_total_linea.bind("<KeyRelease>", _desde_total, add="+")
        self.entry_cantidad.bind("<KeyRelease>", _desde_total, add="+")


        # Vencimiento | Proveedor
        _lbl(self.card_form, "Vencimiento",  3, 0)
        _lbl(self.card_form, "Proveedor",    3, 1)
        self.entry_vence = _entry(self.card_form, 4, 0, "")
        _placeholder(self.entry_vence, "DD/MM/AAAA")

        def _formatear_fecha_vence(event=None):
            # Si hay una tecla de control (flechas, tab, etc.) no hacer nada
            if event is not None and event.keysym in (
                    "Tab", "Shift_L", "Shift_R", "Left", "Right", "Up", "Down",
                    "Control_L", "Control_R"):
                return
            entry = self.entry_vence
            texto = entry.get()
            # No tocar mientras se muestra el placeholder gris
            if texto == "DD/MM/AAAA" and str(entry.cget("fg")) == C.texto_suave:
                return
            solo_digitos = "".join(c for c in texto if c.isdigit())[:8]
            partes = []
            if solo_digitos:
                partes.append(solo_digitos[0:2])
            if len(solo_digitos) > 2:
                partes.append(solo_digitos[2:4])
            if len(solo_digitos) > 4:
                partes.append(solo_digitos[4:8])
            nuevo = "/".join(partes)
            if nuevo != texto:
                entry.delete(0, "end")
                entry.insert(0, nuevo)

        self.entry_vence.bind("<KeyRelease>", _formatear_fecha_vence)

        f_prov = tk.Frame(self.card_form, bg=C.superficie)
        f_prov.grid(row=4, column=1, sticky="ew", padx=(12,4), pady=(2,0))
        f_prov.columnconfigure(0, weight=1, minsize=130)
        self.combo_prov = ttk.Combobox(f_prov, font=F.normal, state="readonly")
        self.combo_prov.grid(row=0, column=0, sticky="ew", ipady=4)
        btn(f_prov, "+", variante="neutro",
            comando=self._nuevo_proveedor).grid(row=0, column=1, padx=(4,0))

        # Notas
        _lbl(self.card_form, "Notas", 5, 0, colspan=2)
        self.entry_notas = _entry(self.card_form, 6, 0, "", colspan=2)

        # Precio + Categoria (solo producto nuevo) — oculto por defecto
        self.frame_precio = tk.Frame(self.card_form, bg=C.superficie)
        self.frame_precio.columnconfigure(0, weight=1)
        self.frame_precio.columnconfigure(1, weight=1)

        lbl(self.frame_precio, "Precio de venta (vacio = margen de cat.)", variante="suave",
            bg=C.superficie).grid(row=0, column=0, sticky="w", padx=(12,4), pady=(6,0))
        lbl(self.frame_precio, "Categoria", variante="suave",
            bg=C.superficie).grid(row=0, column=1, sticky="w", padx=(12,4), pady=(6,0))

        self.entry_precio = tk.Entry(self.frame_precio, font=F.normal,
                                      bg=C.superficie, fg=C.texto,
                                      insertbackground=C.primario,
                                      relief="solid", bd=1)
        self.entry_precio.insert(0, "0.00")
        self.entry_precio.grid(row=1, column=0, sticky="ew",
                                padx=(12,4), pady=(2,0), ipady=5)

        # Categoria con boton + Nueva
        f_cat = tk.Frame(self.frame_precio, bg=C.superficie)
        f_cat.grid(row=1, column=1, sticky="ew", padx=(12,4), pady=(2,6))
        # minsize: sin esto el boton "+ Nueva" se come el ancho y el
        # combo queda mostrando cuatro letras del nombre de la categoria.
        f_cat.columnconfigure(0, weight=1, minsize=130)

        self.combo_cat = ttk.Combobox(f_cat, font=F.normal, state="readonly",
                                      width=16)
        self.combo_cat.grid(row=0, column=0, sticky="ew", ipady=4)

        btn(f_cat, "+", variante="neutro",
            comando=self._nueva_categoria).grid(row=0, column=1, padx=(4,0))

        self.var_peso = tk.BooleanVar(value=False)
        tk.Checkbutton(
            self.frame_precio,
            text="Vendido por peso (admite cantidad decimal, ej: 0,500 kg)",
            variable=self.var_peso, bg=C.superficie, fg=C.texto,
            selectcolor=C.superficie, font=F.normal, anchor="w"
        ).grid(row=2, column=0, columnspan=2, sticky="w", padx=(12,4), pady=(4,6))

        # Foto del producto nuevo — buscador embebido, mismo que en
        # Editar producto. Ya NO se busca sola en Open Food Facts al
        # crear el producto (traía fotos de mala calidad, un tipo
        # sosteniendo el producto, fondos malos, etc.)
        self.btn_foto_nueva = btn(
            self.frame_precio, "🔍 Buscar fotos", variante="neutro",
            comando=self._buscar_fotos_producto_nuevo)
        self.btn_foto_nueva.grid(row=3, column=0, sticky="ew",
                                 padx=(12,4), pady=(0,6))
        self.lbl_foto_nueva = lbl(
            self.frame_precio, "", variante="suave", bg=C.superficie)
        self.lbl_foto_nueva.grid(row=3, column=1, sticky="w", padx=(12,4), pady=(0,6))

        # Botón guardar
        btn(self.card_form, "Registrar ingreso   (F4 o Enter)",
            variante="exito",
            comando=self._guardar).grid(row=8, column=0, columnspan=2,
                                         sticky="ew", padx=12, pady=(12, 2))
        lbl(self.card_form,
            "F2 código   ·   F4 registrar   ·   F6 limpiar   ·   "
            "F7 corregir producto   ·   F8 historial",
            variante="suave").grid(row=9, column=0, columnspan=2,
                                   sticky="w", padx=12, pady=(0, 10))

        self._cargar_combos()
        self._toggle_precio(False)
        # Al final: los binds necesitan que los campos ya existan.
        self._atajos()

    def _panel_tablas(self):
        p = tk.Frame(self._contenedor, bg=C.bg)
        p.grid(row=0, column=1, sticky="nsew", padx=(6,12), pady=12)
        p.columnconfigure(0, weight=1)
        p.rowconfigure(1, weight=3)
        p.rowconfigure(4, weight=1)

        # Lotes recientes
        lbl(p, "Últimos ingresos", variante="titulo").grid(
            row=0, column=0, sticky="w", pady=(0,6))

        frame_l, self.tree_lotes = tabla(p, COLS_LOTES)
        frame_l.grid(row=1, column=0, sticky="nsew")
        self.tree_lotes.bind("<Double-1>", self._editar_proveedor_lote)
        lbl(p, "Doble click en un ingreso para corregir el proveedor",
            variante="suave").grid(row=2, column=0, sticky="w", pady=(4,0))

        acc_l = tk.Frame(p, bg=C.bg)
        acc_l.grid(row=3, column=0, sticky="w", pady=(6,12))   # fila propia
        btn(acc_l, "🔄  Actualizar", variante="neutro",
            comando=self._refrescar_lotes).pack(side="left")
        btn(acc_l, "Corregir vencimiento", variante="neutro",
            comando=self._editar_vencimiento_lote).pack(side="left", padx=6)
        btn(acc_l, "Ver historial completo", variante="primario",
            comando=self._historial_lotes).pack(side="left")

        # Stock crítico — solo visible si hay productos bajo umbral
        self.frame_critico_cont = tk.Frame(p, bg=C.bg)
        self.frame_critico_cont.grid(row=4, column=0, columnspan=2,
                                      sticky="nsew", pady=(0,0))
        self.frame_critico_cont.columnconfigure(0, weight=1)
        self.frame_critico_cont.rowconfigure(1, weight=1)

        self.lbl_critico_titulo = lbl(self.frame_critico_cont,
            "Stock critico (< 5 u.)", variante="subtitulo",
            fg=C.advertencia)
        self.lbl_critico_titulo.grid(row=0, column=0, sticky="w", pady=(8,4))

        frame_c, self.tree_critico = tabla(self.frame_critico_cont,
                                            COLS_CRITICO, altura=5)
        frame_c.grid(row=1, column=0, sticky="nsew")

        self.lbl_sin_critico = lbl(self.frame_critico_cont,
            "Sin productos con stock bajo", variante="suave",
            fg=C.texto_suave)

    # ── Lógica ────────────────────────────────────────────────────────────────

    def _cargar_combos(self):
        provs = get_proveedores()
        self._prov_map = {r["nombre"]: r["id"] for r in provs}
        self.combo_prov["values"] = list(self._prov_map.keys())
        if self._prov_map:
            self.combo_prov.current(0)

        cats = get_categorias()
        self._cat_map = {r["nombre"]: r["id"] for r in cats}
        self.combo_cat["values"] = list(self._cat_map.keys())
        if self._cat_map:
            self.combo_cat.current(0)

    def _buscar_producto(self, event=None):
        codigo = self.entry_codigo.get().strip()
        if not codigo:
            return

        prod = get_producto_por_codigo(codigo)

        if prod:
            self._producto_actual = prod
            stock = get_stock_producto(prod["id"])
            self.lbl_info.config(
                text=f"✓ {prod['descripcion']}  |  Stock actual: {_fmt_cant(stock)} u.  |  Precio: $ {prod['precio_base']:,.2f}",
                fg=C.exito,
            )
            # Al recibir mercadería es cuando uno nota que el nombre está
            # mal escrito o le falta el gramaje. Tener que ir al catálogo
            # a corregirlo hace que nadie lo corrija nunca.
            self.btn_editar_nombre.pack(anchor="w", pady=(4, 0))
            self._toggle_precio(False)
        else:
            self._producto_actual = None
            self.btn_editar_nombre.pack_forget()
            self.lbl_info.config(
                text="Producto nuevo — completá descripción y precio de venta",
                fg=C.advertencia,
            )
            self._toggle_precio(True)
            self._dialogo_nuevo_producto(codigo)

        self.entry_cantidad.focus_set()
        self.entry_cantidad.select_range(0, "end")

    def _atajos(self):
        """Circuito completo de teclado para cargar mercadería.

        Recibir un pedido son decenas de items seguidos: soltar el
        teclado para buscar el mouse en cada uno cuesta más que toda la
        carga junta.

        El recorrido natural queda encadenado con Enter:
            código → cantidad → costo (o total) → Enter registra
        """
        raiz = self.winfo_toplevel()

        def _si_visible(fn):
            """Las F son del toplevel: solo actúan si esta pantalla se ve."""
            def _wrap(ev=None):
                if not self.winfo_ismapped():
                    return None
                fn()
                return "break"
            return _wrap

        for tecla, accion in (
                ("<F2>",  lambda: (self.entry_codigo.focus_set(),
                                   self.entry_codigo.select_range(0, "end"))),
                ("<F4>",  lambda: self._guardar()),
                ("<F6>",  lambda: self._limpiar()),
                ("<F7>",  lambda: (self._editar_producto_actual()
                                   if self._producto_actual else None)),
                ("<F8>",  lambda: self._historial_lotes())):
            raiz.bind(tecla, _si_visible(accion), add="+")

        # Enter encadena el recorrido: cada campo lleva al siguiente y el
        # último registra, sin tocar el mouse en ningún momento.
        self.entry_cantidad.bind(
            "<Return>", lambda e: (self.entry_costo.focus_set(),
                                   self.entry_costo.select_range(0, "end"),
                                   "break")[-1])
        self.entry_costo.bind("<Return>", lambda e: self._guardar())
        self.entry_total_linea.bind("<Return>", lambda e: self._guardar())

    def _editar_producto_actual(self):
        """Corrige el nombre y el precio sin salir del ingreso."""
        from repositorio import get_producto_completo, actualizar_producto
        prod = self._producto_actual
        if not prod:
            return
        p = get_producto_completo(prod["id"])
        if not p:
            return

        d = tk.Toplevel(self)
        d.title("Corregir producto")
        d.configure(bg=C.superficie)
        d.grab_set()
        _centrar(d, 470, 300)

        lbl(d, "Corregir producto", variante="titulo",
            bg=C.superficie).pack(anchor="w", padx=18, pady=(16, 2))
        lbl(d, f"Código {p.get('codigo') or '—'}", variante="suave",
            bg=C.superficie).pack(anchor="w", padx=18)

        lbl(d, "Descripción", variante="suave", bg=C.superficie).pack(
            anchor="w", padx=18, pady=(14, 2))
        v_desc = tk.StringVar(value=p["descripcion"])
        e_d = tk.Entry(d, textvariable=v_desc, font=F.normal, bg=C.bg,
                       fg=C.texto, relief="solid", bd=1)
        e_d.pack(fill="x", padx=18, ipady=5)

        lbl(d, "Precio de venta", variante="suave", bg=C.superficie).pack(
            anchor="w", padx=18, pady=(12, 2))
        v_pre = tk.StringVar(value=f"{p.get('precio_base') or 0:.2f}")
        e_p = tk.Entry(d, textvariable=v_pre, font=F.subtitulo,
                       justify="center", bg=C.bg, fg=C.texto,
                       relief="solid", bd=1)
        e_p.pack(fill="x", padx=18, ipady=5)

        def guardar(_ev=None):
            desc = v_desc.get().strip()
            if not desc:
                messagebox.showwarning("Corregir", "La descripción no puede "
                                                   "quedar vacía.", parent=d)
                return
            try:
                precio = float(v_pre.get().replace(",", "."))
            except ValueError:
                messagebox.showwarning("Corregir", "El precio no es un "
                                                   "número.", parent=d)
                return
            costo = float(p.get("costo_ultimo") or 0)
            if costo and precio < costo:
                if not messagebox.askyesno(
                        "Precio bajo costo",
                        f"$ {precio:,.2f} queda por debajo del costo "
                        f"($ {costo:,.2f}).\n\n¿Guardar igual?", parent=d):
                    return
            try:
                actualizar_producto(
                    p["id"], desc, p.get("codigo"), p.get("categoria_id"),
                    precio, costo, p.get("margen_pct"),
                    p.get("vendido_por_peso") or 0, p.get("imagen_url"),
                    p.get("marca"))
            except Exception as exc:
                messagebox.showerror("Corregir", str(exc), parent=d)
                return
            d.destroy()
            # Se relee para mostrar el nombre y el precio ya corregidos
            self._producto_actual = get_producto_completo(p["id"])
            stock = get_stock_producto(p["id"])
            self.lbl_info.config(
                text=(f"✓ {desc}  |  Stock actual: {_fmt_cant(stock)} u.  |  "
                      f"Precio: $ {self._producto_actual['precio_base']:,.2f}"),
                fg=C.exito)
            toast(self, "Producto corregido")

        # Enter desde el precio guarda; desde la descripción pasa al precio
        e_p.bind("<Return>", guardar)
        e_d.bind("<Return>", lambda ev: (e_p.focus_set(),
                                          e_p.select_range(0, "end"), "break")[-1])
        d.bind("<Escape>", lambda ev: d.destroy())

        pie = tk.Frame(d, bg=C.superficie)
        pie.pack(side="bottom", pady=14)
        btn(pie, "Guardar", variante="exito", comando=guardar).pack(
            side="left", padx=4)
        btn(pie, "Cancelar  (Esc)", variante="neutro",
            comando=d.destroy).pack(side="left", padx=4)

        e_d.focus_set()
        e_d.icursor("end")

    def _toggle_precio(self, mostrar):
        if mostrar:
            self.frame_precio.grid(row=7, column=0, columnspan=2,
                                   sticky="ew", in_=self.card_form)
        else:
            self.frame_precio.grid_remove()

    def _dialogo_nuevo_producto(self, codigo):
        """Pide descripcion (y marca) para un producto nuevo antes de continuar."""
        d = tk.Toplevel(self)
        d.title("Producto nuevo")
        d.resizable(True, False)
        d.configure(bg=C.superficie)
        d.grab_set()
        _centrar(d, 400, 240)

        lbl(d, f"Codigo: {codigo}", variante="subtitulo",
            bg=C.superficie).pack(pady=(16,4), padx=20, anchor="w")
        lbl(d, "Descripcion del producto", variante="suave",
            bg=C.superficie).pack(padx=20, anchor="w")

        e = tk.Entry(d, font=F.normal, bg=C.superficie, fg=C.texto,
                     relief="solid", bd=1)
        e.pack(fill="x", padx=20, pady=(4,10), ipady=6)
        e.focus_set()

        lbl(d, "Marca (opcional)", variante="suave",
            bg=C.superficie).pack(padx=20, anchor="w")
        e_marca = tk.Entry(d, font=F.normal, bg=C.superficie, fg=C.texto,
                           relief="solid", bd=1)
        e_marca.pack(fill="x", padx=20, pady=(4,12), ipady=6)

        self._desc_nuevo = ""
        self._marca_nueva = ""

        def ok(event=None):
            self._desc_nuevo = e.get().strip()
            self._marca_nueva = e_marca.get().strip()
            d.destroy()

        e.bind("<Return>", lambda ev: e_marca.focus_set())
        e_marca.bind("<Return>", ok)
        btn(d, "Continuar", variante="primario", comando=ok).pack()
        self.wait_window(d)

    def _nueva_categoria(self):
        """Alta rapida de categoria desde el formulario de Stock."""
        d = tk.Toplevel(self)
        d.title("Nueva categoria")
        d.resizable(True, False)
        d.configure(bg=C.superficie)
        d.grab_set()
        _centrar(d, 360, 260)

        lbl(d, "Nueva categoria", variante="subtitulo",
            bg=C.superficie).pack(pady=(16,4), padx=20, anchor="w")

        lbl(d, "Nombre *", variante="suave",
            bg=C.superficie).pack(padx=20, anchor="w")
        e_nombre = tk.Entry(d, font=F.normal, bg=C.superficie, fg=C.texto,
                             relief="solid", bd=1)
        e_nombre.pack(fill="x", padx=20, ipady=6, pady=(2,8))
        e_nombre.focus_set()

        lbl(d, "Margen %", variante="suave",
            bg=C.superficie).pack(padx=20, anchor="w")
        e_margen = tk.Entry(d, font=F.normal, bg=C.superficie, fg=C.texto,
                             relief="solid", bd=1)
        e_margen.insert(0, "30")
        e_margen.pack(fill="x", padx=20, ipady=6, pady=(2,4))

        lbl(d, "Si no ingresas precio, se calcula: costo x (1 + margen%)",
            variante="suave", bg=C.superficie,
            fg=C.texto_suave, wraplength=320,
            justify="left").pack(padx=20, anchor="w", pady=(0,8))

        def guardar(event=None):
            nombre = e_nombre.get().strip()
            if not nombre:
                messagebox.showwarning("Error", "Ingresa un nombre.", parent=d)
                return
            try:
                margen = float(e_margen.get().replace(",", "."))
            except ValueError:
                margen = 30.0
            from repositorio import guardar_categoria
            guardar_categoria(None, nombre, margen)
            self._cargar_combos()
            self.combo_cat.set(nombre)
            d.destroy()

        e_margen.bind("<Return>", guardar)
        btn(d, "Guardar categoria", variante="exito",
            comando=guardar).pack(fill="x", padx=20, pady=(0,16))

    def _nuevo_proveedor(self):
        d = tk.Toplevel(self)
        d.title("Nuevo proveedor")
        d.resizable(True, True)
        d.configure(bg=C.superficie)
        d.grab_set()
        _centrar(d, 360, 170)

        lbl(d, "Nombre del proveedor", variante="subtitulo",
            bg=C.superficie).pack(pady=(20,6), padx=20, anchor="w")
        e = tk.Entry(d, font=F.normal, bg=C.superficie, fg=C.texto,
                     relief="solid", bd=1)
        e.pack(fill="x", padx=20, pady=(0,12), ipady=6)
        e.focus_set()

        def ok(event=None):
            nombre = e.get().strip()
            if not nombre: return
            pid = crear_proveedor(nombre)
            self._prov_map[nombre] = pid
            self.combo_prov["values"] = list(self._prov_map.keys())
            self.combo_prov.set(nombre)
            d.destroy()

        e.bind("<Return>", ok)
        btn(d, "Guardar", variante="primario", comando=ok).pack()

    def _guardar(self):
        codigo = self.entry_codigo.get().strip()
        if not codigo:
            messagebox.showwarning("Atención", "Ingresá un código de producto.", parent=self)
            return

        # Validar cantidad y costo
        try:
            cantidad = float(self.entry_cantidad.get().replace(",", "."))
            costo    = float(self.entry_costo.get().replace(",", "."))
            if cantidad <= 0 or costo < 0: raise ValueError
        except ValueError:
            messagebox.showwarning("Atención", "Cantidad y costo deben ser números válidos.", parent=self)
            return

        es_peso = (bool(self._producto_actual.get("vendido_por_peso"))
                   if self._producto_actual else self.var_peso.get())
        if not es_peso and cantidad != int(cantidad):
            messagebox.showwarning(
                "Atención",
                "Este producto se vende por unidad — la cantidad debe ser entera.\n"
                "Si corresponde, marcá \"Vendido por peso\" para admitir decimales.",
                parent=self)
            return

        # Vencimiento (opcional)
        vence_ingresado = self.entry_vence.get().strip()
        if vence_ingresado in ("DD/MM/AAAA", ""):
            vence = None
        else:
            try:
                vence = datetime.strptime(vence_ingresado, "%d/%m/%Y").strftime("%Y-%m-%d")
            except ValueError:
                messagebox.showwarning("Atención", "Fecha inválida. Formato: DD/MM/AAAA", parent=self)
                return

        notas = self.entry_notas.get().strip()

        # Proveedor
        prov_nombre = self.combo_prov.get()
        prov_id = self._prov_map.get(prov_nombre)

        # Producto nuevo o existente
        if self._producto_actual:
            prod_id = self._producto_actual["id"]
        else:
            # Crear producto nuevo
            desc = getattr(self, "_desc_nuevo", "").strip()
            if not desc:
                messagebox.showwarning("Atencion",
                    "Falta la descripcion del producto.", parent=self)
                return
            try:
                precio_str = self.entry_precio.get().replace(",", ".").strip()
                precio = float(precio_str) if precio_str and precio_str != "0.00" else 0.0
            except ValueError:
                precio = 0.0
            # Si no puso precio, calcular por margen de categoría
            if precio <= 0:
                cat_id_temp = self._cat_map.get(self.combo_cat.get())
                if cat_id_temp:
                    from repositorio import get_categorias
                    cats = {c["id"]: c for c in get_categorias()}
                    margen = cats.get(cat_id_temp, {}).get("margen_pct", 30.0)
                    precio = round(costo * (1 + margen / 100), 2)
                else:
                    precio = round(costo * 1.30, 2)

            cat_nombre = self.combo_cat.get()
            cat_id = self._cat_map.get(cat_nombre)
            prod_id = crear_producto(codigo, desc, cat_id, precio, costo,
                                      vendido_por_peso=self.var_peso.get(),
                                      marca=getattr(self, "_marca_nueva", ""))

        # La foto elegida en "Buscar fotos" se guarda para el producto
        # sea nuevo o ya existente (antes, si el producto ya existía,
        # esta parte no se ejecutaba nunca y la foto se perdía). Se
        # descarga a la compu de una — no se deja como link externo,
        # que puede vencer o dejar de andar — mismo mecanismo que
        # "Guardar localmente" en Editar producto.
        if self._foto_nueva_url:
            try:
                ruta_local = imagenes.guardar_imagen_desde_url(prod_id, self._foto_nueva_url)
                actualizar_imagen_producto(prod_id, ruta_local)
            except Exception as e:
                logging.warning(f"No se pudo descargar la foto localmente: {e}")
                # Si falla la descarga, mejor guardar el link que perder la foto del todo.
                actualizar_imagen_producto(prod_id, self._foto_nueva_url)

        # Registrar lote — si el costo subió, se recalcula el precio
        # solo (como ya venía funcionando). Si bajó, se pregunta antes
        # de tocarlo: puede que el usuario quiera mantener el precio
        # de venta actual (guardar más margen) en vez de bajarlo.
        info = evaluar_cambio_costo(prod_id, costo)
        nuevo_precio_venta = None
        if info["direccion"] == "subio":
            nuevo_precio_venta = info["precio_sugerido"]
        elif (info["direccion"] == "bajo"
              and round(info["precio_sugerido"], 2) != round(info["precio_actual"], 2)):
            nuevo_precio_venta = None

            # El cartel muestra los tres datos que realmente deciden:
            # cuanto stock viejo queda (FIFO lo vende primero), que margen
            # se tiene si no se toca nada, y si bajar el precio dejaria el
            # stock viejo vendiendose por debajo de su costo.
            texto = [
                f"El costo bajó de $ {info['costo_anterior']:,.2f} "
                f"a $ {info['costo_nuevo']:,.2f}.",
                "",
                f"Si NO tocás nada:   $ {info['precio_actual']:,.2f}"
                f"   →  margen {info['margen_si_no_toca']:.1f}%",
                f"Si bajás el precio: $ {info['precio_sugerido']:,.2f}"
                f"   →  margen {info['margen_sugerido']:.1f}%",
            ]

            if info["stock_viejo"] > 0:
                texto += ["",
                          f"Te quedan {info['stock_viejo']:g} unidad(es) compradas "
                          f"al costo viejo de $ {info['costo_anterior']:,.2f}."]
                if info["bajo_costo_viejo"]:
                    perdida = info["perdida_por_unidad"]
                    total = perdida * info["stock_viejo"]
                    texto += [
                        "",
                        "⚠  CUIDADO: el precio nuevo queda POR DEBAJO de ese "
                        "costo viejo.",
                        f"Como el stock sale por orden de llegada, perderías "
                        f"$ {perdida:,.2f} por unidad",
                        f"hasta agotarlo: $ {total:,.2f} en total.",
                    ]
                else:
                    texto += ["Esas unidades se venderían con el margen nuevo, "
                              "no con el que tenían."]

            texto += ["", "¿Bajás el precio de venta ahora?",
                      "(si decís que no, se mantiene el precio actual)"]

            titulo = ("El costo bajó — ojo con el stock viejo"
                      if info["bajo_costo_viejo"] else "El costo bajó")
            if messagebox.askyesno(titulo, "\n".join(texto), parent=self):
                nuevo_precio_venta = info["precio_sugerido"]

        _, precio_aplicado = registrar_lote(
            prod_id, prov_id, cantidad, costo, vence, notas,
            nuevo_precio_venta=nuevo_precio_venta)

        if precio_aplicado is not None:
            messagebox.showinfo(
                "Precio actualizado",
                f"Precio de venta actualizado a: $ {precio_aplicado:,.2f}\n"
                f"(según margen del producto o categoría)",
                parent=self
            )
        toast(self, f"Ingreso OK — {_fmt_cant(cantidad)} u.")

        self._limpiar()
        self._refrescar_lotes()
        self._refrescar_critico()
        self.entry_codigo.focus_set()

    def _buscar_fotos_producto_nuevo(self):
        """
        Buscador de fotos embebido para el producto que se está por
        crear — mismo mecanismo que en Editar producto (ventana aparte
        con pywebview, click en la foto y listo). Como el producto
        todavía no existe en la base en este punto, la URL elegida se
        guarda en self._foto_nueva_url y se aplica recién después de
        crear el producto en _guardar().
        """
        desc = self._desc_nuevo or self.entry_codigo.get().strip()
        if not desc:
            messagebox.showinfo(
                "Buscar fotos",
                "Escribí primero una descripción para buscar.", parent=self)
            return

        self.btn_foto_nueva.configure(
            state="disabled", text="Buscando... elegí una foto en la ventana")
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
                if not self.winfo_exists():
                    return
                self.btn_foto_nueva.configure(state="normal", text="🔍 Buscar fotos")
                if error:
                    messagebox.showwarning(
                        "Buscador de fotos",
                        f"No se pudo abrir la ventana de búsqueda ({error}).\n\n"
                        f"Probá instalando: pip install pywebview", parent=self)
                    return
                if url and imagenes.es_url(url):
                    self._foto_nueva_url = url
                    self.lbl_foto_nueva.config(text="✅  Foto elegida", fg=C.exito)
            try:
                self.after(0, _aplicar)
            except tk.TclError as e:
                # Normal si cerraron la ventana mientras bajaba la foto.
                logging.debug(f"Ventana cerrada antes de aplicar la foto: {e}")

        threading.Thread(target=_trabajar, daemon=True).start()

    def _limpiar(self):
        self._producto_actual = None
        self._desc_nuevo = ""
        self._marca_nueva = ""
        self._foto_nueva_url = None
        self.lbl_foto_nueva.config(text="")
        self.var_peso.set(False)
        self.entry_codigo.delete(0, "end")
        self.entry_cantidad.delete(0, "end")
        self.entry_cantidad.insert(0, "1")
        self.entry_costo._mostrar_placeholder()
        self.entry_total_linea.delete(0, "end")
        self.entry_total_linea._mostrar_placeholder()
        self.entry_vence._mostrar_placeholder()
        self.entry_notas.delete(0, "end")
        self.entry_precio.delete(0, "end")
        self.entry_precio.insert(0, "0.00")
        self.lbl_info.config(text="", fg=C.texto_suave)
        self.btn_editar_nombre.pack_forget()
        self._toggle_precio(False)

    def _refrescar_lotes(self):
        for r in self.tree_lotes.get_children():
            self.tree_lotes.delete(r)
        for r in get_lotes_recientes():
            if r.get("tipo") == "ajuste":
                tipo_txt = f"Ajuste ({r['motivo_ajuste']})" if r.get("motivo_ajuste") else "Ajuste"
            else:
                tipo_txt = "Ingreso"
            self.tree_lotes.insert("", "end", iid=str(r["id"]), values=(
                r["descripcion"],
                r["codigo"],
                tipo_txt,
                _fmt_cant(r['cantidad']),
                _fmt_cant(r['cantidad_restante']),
                f"$ {r['costo_unitario']:,.2f}",
                r["proveedor"] or "—",
                r["fecha_ingreso"][:10] if r["fecha_ingreso"] else "—",
                r["fecha_vencimiento"] or "—",
            ))

    def _historial_lotes(self):
        """Todos los ingresos, no solo los ultimos 50."""
        from historial_lotes_ui import dialogo_historial_lotes
        dialogo_historial_lotes(self)

    def _editar_vencimiento_lote(self, event=None):
        """Corrige el vencimiento de un lote ya cargado.

        Hasta ahora la fecha se escribia una sola vez al ingresar el lote y
        despues no habia forma de tocarla: un error de tipeo se quedaba ahi
        para siempre, disparando alertas falsas o —peor— callando las reales.
        """
        sel = self.tree_lotes.selection()
        if not sel:
            messagebox.showinfo("Vencimiento",
                                "Seleccioná un ingreso de la lista.", parent=self)
            return
        lote_id = int(sel[0])
        valores = self.tree_lotes.item(sel[0])["values"]
        descripcion, actual = valores[0], valores[8]

        d = tk.Toplevel(self)
        d.title("Corregir vencimiento")
        _centrar(d, 420, 250)
        d.configure(bg=C.superficie)
        d.resizable(False, False)
        d.grab_set()

        lbl(d, descripcion, variante="titulo", bg=C.superficie).pack(
            anchor="w", padx=20, pady=(18, 2))
        lbl(d, f"Vencimiento actual: {actual}", variante="suave",
            bg=C.superficie).pack(anchor="w", padx=20)

        lbl(d, "Nueva fecha (DD/MM/AAAA — vacío = sin vencimiento)",
            variante="suave", bg=C.superficie).pack(anchor="w", padx=20,
                                                    pady=(14, 4))
        var = tk.StringVar()
        if actual and actual != "—":
            try:
                var.set(datetime.strptime(actual, "%Y-%m-%d").strftime("%d/%m/%Y"))
            except ValueError:
                var.set(actual)
        e = tk.Entry(d, textvariable=var, font=F.normal, justify="center",
                     bg=C.superficie, fg=C.texto, relief="solid", bd=1)
        e.pack(padx=20, fill="x", ipady=5)
        e.focus_set()
        e.select_range(0, "end")

        def guardar(_ev=None):
            from repositorio import actualizar_vencimiento_lote
            try:
                nueva = actualizar_vencimiento_lote(lote_id, var.get())
            except ValueError as exc:
                messagebox.showwarning("Vencimiento", str(exc), parent=d)
                return
            d.destroy()
            self._refrescar_lotes()
            toast(self, f"Vencimiento actualizado: {nueva or 'sin vencimiento'}")

        e.bind("<Return>", guardar)
        d.bind("<Escape>", lambda ev: d.destroy())

        fb = tk.Frame(d, bg=C.superficie)
        fb.pack(pady=18)
        btn(fb, "Guardar", variante="exito", comando=guardar).pack(side="left", padx=4)
        btn(fb, "Cancelar", variante="neutro", comando=d.destroy).pack(side="left", padx=4)

    def _editar_proveedor_lote(self, event=None):
        sel = self.tree_lotes.selection()
        if not sel:
            return
        lote_id = int(sel[0])
        valores = self.tree_lotes.item(sel[0])["values"]
        descripcion, prov_actual = valores[0], valores[6]

        d = tk.Toplevel(self)
        d.title("Corregir proveedor")
        _centrar(d, 380, 220)
        d.configure(bg=C.superficie)
        d.resizable(False, False)
        d.grab_set()

        lbl(d, descripcion, variante="titulo", bg=C.superficie).pack(
            pady=(20,4), padx=20, anchor="w")
        lbl(d, f"Proveedor actual: {prov_actual}", variante="suave",
            bg=C.superficie).pack(padx=20, anchor="w", pady=(0,12))

        lbl(d, "Proveedor correcto", variante="suave", bg=C.superficie).pack(
            padx=20, anchor="w")
        prov_map = {r["nombre"]: r["id"] for r in get_proveedores()}
        combo = ttk.Combobox(d, font=F.normal, state="readonly",
                             values=["(sin proveedor)"] + list(prov_map.keys()))
        combo.pack(fill="x", padx=20, pady=(2,14), ipady=4)
        if prov_actual in prov_map:
            combo.set(prov_actual)
        else:
            combo.current(0)

        def _guardar():
            elegido = combo.get()
            nuevo_id = prov_map.get(elegido)  # None si "(sin proveedor)"
            actualizar_proveedor_lote(lote_id, nuevo_id)
            d.destroy()
            toast(self, "✅  Proveedor corregido")
            self._refrescar_lotes()

        btn(d, "Guardar", variante="exito", comando=_guardar).pack(
            fill="x", padx=20, pady=(0,20))

    def _refrescar_critico(self):
        for r in self.tree_critico.get_children():
            self.tree_critico.delete(r)
        criticos = get_stock_critico()
        for r in criticos:
            self.tree_critico.insert("", "end", values=(
                r["descripcion"],
                r["codigo"],
                _fmt_cant(r['stock']),
            ), tags=("critico",))
        self.tree_critico.tag_configure("critico", foreground=C.peligro)

        # Mostrar tabla o mensaje según si hay criticos
        if criticos:
            self.lbl_sin_critico.grid_forget()
            self.tree_critico.master.grid()
            self.lbl_critico_titulo.grid()
        else:
            self.tree_critico.master.grid_remove()
            self.lbl_critico_titulo.grid_remove()
            self.lbl_sin_critico.grid(row=0, column=0, sticky="w", pady=(8,4))

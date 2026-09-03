"""
ingreso_ui.py — Ingreso de stock TPV v2.0
Lotes con proveedor, costo y vencimiento. FIFO automático.
"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading
import logging
import os
import sys
import subprocess
import imagenes
from styles import C, F, btn, lbl, card, tabla, toast, header_seccion, scrollable
from repositorio import (get_proveedores, get_categorias, crear_proveedor,
                         crear_producto, registrar_lote, get_lotes_recientes,
                         evaluar_cambio_costo, get_stock_critico, get_stock_producto,
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


def _unidad(prod):
    """kg o u. Mostrar "u." en algo que se vende por peso confunde al
    cargar: 4.093 unidades y 4.093 kg son cosas muy distintas."""
    return "kg" if (prod or {}).get("vendido_por_peso") else "u."


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

        lbl(c_scan, "Codigo de barras  ·  o escribí el nombre",
            variante="suave",
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
            w = lbl(parent, texto, variante="suave", bg=C.superficie)
            w.grid(row=row, column=col, columnspan=colspan,
                   sticky="w", padx=(12,4), pady=(6,0))
            return w

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
                else:
                    # Lo que haya queda seleccionado: sin esto hay que
                    # borrar el "0.00" a mano en cada producto de cada
                    # ingreso. Va en after() porque el foco todavia no
                    # termino de asentarse.
                    entry.after(1, lambda: entry.select_range(0, "end"))

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
        self.lbl_cantidad = _lbl(self.card_form, "Cantidad *", 0, 0)
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
        _placeholder(self.entry_vence, "DD/MM/AA")

        def _formatear_fecha_vence(event=None):
            # Si hay una tecla de control (flechas, tab, etc.) no hacer nada
            if event is not None and event.keysym in (
                    "Tab", "Shift_L", "Shift_R", "Left", "Right", "Up", "Down",
                    "Control_L", "Control_R"):
                return
            entry = self.entry_vence
            texto = entry.get()
            # No tocar mientras se muestra el placeholder gris
            if texto == "DD/MM/AA" and str(entry.cget("fg")) == C.texto_suave:
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
        self.lbl_margen_info = lbl(self.frame_precio, "", variante="suave")
        self.lbl_margen_info.grid(row=2, column=0, columnspan=2, sticky="w",
                                  padx=12, pady=(0, 4))

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
        # Fuera de frame_precio: ese panel se esconde con los productos
        # que ya existen, y la foto hace falta igual.
        f_foto = tk.Frame(self.card_form, bg=C.superficie)
        f_foto.grid(row=10, column=0, columnspan=2, sticky="ew",
                    padx=(12, 4), pady=(0, 6))
        self.btn_foto_nueva = btn(
            f_foto, "🔍 Buscar fotos", variante="neutro",
            comando=self._buscar_fotos_producto_nuevo)
        self.btn_foto_nueva.pack(side="left")
        self.lbl_foto_nueva = lbl(f_foto, "", variante="suave",
                                  bg=C.superficie)
        self.lbl_foto_nueva.pack(side="left", padx=12)

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

        # Los campos numericos se seleccionan enteros al enfocarlos: sin
        # esto hay que borrar el "0.00" a mano antes de escribir, en cada
        # producto de cada ingreso.
        def _seleccionar_todo(ev):
            w = ev.widget

            def _hacer():
                try:
                    w.select_range(0, "end")
                    w.icursor("end")
                except Exception:
                    pass

            # after(): el placeholder y el foco terminan de asentarse
            # despues del evento, y una seleccion hecha antes se pierde.
            w.after(30, _hacer)

        for _campo in (self.entry_cantidad, self.entry_costo,
                       self.entry_precio, self.entry_total_linea):
            _campo.bind("<FocusIn>", _seleccionar_todo, add="+")

        # Producto nuevo: al elegir la categoria (o tipear el costo) el
        # precio de venta sale solo con el margen del rubro. Pensar el
        # precio de cada producto con el proveedor esperando es lo que
        # hace lenta la carga.
        def _sugerir_precio(*_a):
            if self._producto_actual:
                return          # producto existente: no se toca su precio
            try:
                costo = float(self.entry_costo.get().strip().replace(",", "."))
            except ValueError:
                return
            if costo <= 0:
                return
            cat = self.combo_cat.get().strip()
            margen = getattr(self, "_cat_margen", {}).get(cat)
            if margen is None:
                from config import cfg
                margen = float(cfg().get("margen_default", 30) or 30)
            from repositorio import redondear_precio
            sugerido = redondear_precio(costo * (1 + float(margen) / 100))
            actual = self.entry_precio.get().strip()
            # No se pisa un precio escrito a mano
            if actual in ("", "0.00", "0") or actual == getattr(
                    self, "_precio_sugerido_prev", None):
                self.entry_precio.delete(0, "end")
                self.entry_precio.insert(0, f"{sugerido:.2f}")
                self._precio_sugerido_prev = f"{sugerido:.2f}"
                self.lbl_margen_info.config(
                    text=f"margen {float(margen):.0f}% de «{cat or 'general'}»")

        self.combo_cat.bind("<<ComboboxSelected>>", _sugerir_precio)
        self.entry_costo.bind("<FocusOut>", _sugerir_precio, add="+")
        self.entry_costo.bind("<Return>", _sugerir_precio, add="+")

        self._cargar_combos()
        self._toggle_precio(False)

        # La mercaderia llega por rubro: si el remito trae doce cosas de
        # almacen, la categoria del anterior acierta once veces.
        self._ultima_cat = None
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
        self.tree_lotes.bind("<Double-1>", self._editar_lote)
        lbl(p, "Doble clic en un ingreso para corregirlo "
               "(cantidad, costo, proveedor, vencimiento)",
            variante="suave").grid(row=2, column=0, sticky="w", pady=(4,0))

        acc_l = tk.Frame(p, bg=C.bg)
        acc_l.grid(row=3, column=0, sticky="w", pady=(6,12))   # fila propia
        btn(acc_l, "🔄  Actualizar", variante="neutro",
            comando=self._refrescar_lotes).pack(side="left")
        btn(acc_l, "✏️  Editar lote", variante="neutro",
            comando=self._editar_lote).pack(side="left", padx=6)
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
        # El margen de cada rubro, para sugerir el precio de venta
        self._cat_margen = {r["nombre"]: r.get("margen_pct") for r in cats}
        self.combo_cat["values"] = list(self._cat_map.keys())
        if self._cat_map:
            self.combo_cat.current(0)

    def _buscar_producto(self, event=None):
        codigo = self.entry_codigo.get().strip()
        if not codigo:
            return

        prod = get_producto_por_codigo(codigo)

        # Si no es un codigo, se busca por nombre: al recibir mercaderia
        # no siempre se tiene el codigo a mano, y muchos productos
        # (fraccionados, granel) directamente no vienen etiquetados.
        if not prod and len(codigo) >= 3:
            from repositorio import get_productos
            try:
                candidatos = get_productos(filtro=codigo)
            except Exception:
                candidatos = []
            if len(candidatos) == 1:
                prod = get_producto_por_codigo(candidatos[0]["codigo"])
            elif candidatos:
                elegido = self._elegir_producto(candidatos, codigo)
                if elegido:
                    prod = get_producto_por_codigo(elegido["codigo"])
                else:
                    return self.entry_codigo.focus_set()

        if prod:
            self._producto_actual = prod
            stock = get_stock_producto(prod["id"])
            self.lbl_info.config(
                text=(f"✓ {prod['descripcion']}  |  Stock actual: "
                      f"{_fmt_cant(stock)} {_unidad(prod)}  |  Precio: "
                      f"$ {prod['precio_base']:,.2f} por {_unidad(prod)}"),
                fg=C.exito,
            )
            # Al recibir mercadería es cuando uno nota que el nombre está
            # mal escrito o le falta el gramaje. Tener que ir al catálogo
            # a corregirlo hace que nadie lo corrija nunca.
            self.btn_editar_nombre.config(text="✏️  Corregir nombre o precio")
            self.btn_editar_nombre.pack(anchor="w", pady=(4, 0))
            self.lbl_cantidad.config(
                text=("Cantidad en kg *" if prod.get("vendido_por_peso")
                      else "Cantidad *"))
            self._toggle_precio(False)
        else:
            self._producto_actual = None
            self.lbl_cantidad.config(text="Cantidad *")
            # Producto nuevo: el nombre se puede seguir corrigiendo hasta
            # guardar. Antes habia que guardarlo mal e ir al catalogo.
            self.btn_editar_nombre.config(text="✏️  Corregir nombre o marca")
            self.btn_editar_nombre.pack(anchor="w", pady=(4, 0))
            # Se repite la categoria del producto anterior
            if getattr(self, "_ultima_cat", None) and not self.combo_cat.get():
                self.combo_cat.set(self._ultima_cat)
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

    def _elegir_producto(self, candidatos, texto):
        """Lista los productos que coinciden con lo escrito."""
        d = tk.Toplevel(self)
        d.title("Elegir producto")
        d.configure(bg=C.superficie)
        d.grab_set()
        _centrar(d, 560, 420)

        lbl(d, f'Productos que coinciden con "{texto}"', variante="titulo",
            bg=C.superficie).pack(anchor="w", padx=18, pady=(16, 2))
        lbl(d, "Doble clic o Enter para elegir.", variante="suave",
            bg=C.superficie).pack(anchor="w", padx=18)

        cols = [("desc", "Producto", 260, "w"), ("cod", "Código", 130, "w"),
                ("stock", "Stock", 70, "e"), ("precio", "Precio", 90, "e")]
        frame_t, tv = tabla(d, cols, altura=11)
        frame_t.pack(fill="both", expand=True, padx=18, pady=(10, 6))
        for i, c in enumerate(candidatos[:80]):
            tv.insert("", "end", iid=str(i), values=(
                c["descripcion"][:40], c.get("codigo") or "—",
                f"{c.get('stock') or 0:g}",
                f"$ {c.get('precio_base') or 0:,.2f}"))

        res = [None]

        def elegir(_ev=None):
            sel = tv.selection()
            if sel:
                res[0] = candidatos[int(sel[0])]
                d.destroy()

        tv.bind("<Double-1>", elegir)
        tv.bind("<Return>", elegir)
        d.bind("<Escape>", lambda ev: d.destroy())
        pie = tk.Frame(d, bg=C.superficie)
        pie.pack(side="bottom", pady=12)
        btn(pie, "Elegir  (Enter)", variante="exito",
            comando=elegir).pack(side="left", padx=4)
        btn(pie, "Cancelar", variante="neutro",
            comando=d.destroy).pack(side="left", padx=4)

        if tv.get_children():
            tv.selection_set("0")
            tv.focus_set()
        self.wait_window(d)
        return res[0]

    def _editar_producto_actual(self):
        """Corrige el nombre y el precio sin salir del ingreso.

        Si el producto todavia no existe (recien escaneado), reabre el
        dialogo de alta con lo que ya se habia escrito: corregir un
        nombre mal tipeado no puede obligar a guardar y volver.
        """
        if not self._producto_actual:
            self._dialogo_nuevo_producto(
                self.entry_codigo.get().strip(),
                desc_inicial=getattr(self, "_desc_nuevo", ""),
                marca_inicial=getattr(self, "_marca_nueva", ""))
            return

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
                text=(f"✓ {desc}  |  Stock actual: {_fmt_cant(stock)} "
                      f"{_unidad(self._producto_actual)}  |  "
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
        """El panel de precio/categoría solo va en productos nuevos.

        El botón de la foto vive ahí adentro pero se necesita SIEMPRE:
        recibir mercadería es cuando uno tiene el producto en la mano
        para sacarle una foto. Se saca del panel y queda aparte.
        """
        if mostrar:
            self.frame_precio.grid(row=7, column=0, columnspan=2,
                                   sticky="ew", in_=self.card_form)
        else:
            self.frame_precio.grid_remove()

    def _dialogo_nuevo_producto(self, codigo, desc_inicial="",
                                marca_inicial=""):
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
        if desc_inicial:
            e.insert(0, desc_inicial)
            e.select_range(0, "end")
        e.focus_set()

        lbl(d, "Marca (opcional)", variante="suave",
            bg=C.superficie).pack(padx=20, anchor="w")
        e_marca = tk.Entry(d, font=F.normal, bg=C.superficie, fg=C.texto,
                           relief="solid", bd=1)
        e_marca.pack(fill="x", padx=20, pady=(4,12), ipady=6)
        if marca_inicial:
            e_marca.insert(0, marca_inicial)

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
        if vence_ingresado in ("DD/MM/AA", "DD/MM/AAAA", ""):
            vence = None
        else:
            from repositorio import parsear_fecha
            vence = parsear_fecha(vence_ingresado)
            if not vence:
                messagebox.showwarning(
                    "Atención",
                    "No entiendo esa fecha.\n\n"
                    "Podés escribirla como 15/03/27, 15/03/2027, "
                    "15-3-27 o 150327.", parent=self)
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
                # Se guarda el link para no perder la foto del todo, pero
                # se AVISA: guardado en silencio, uno cree que la foto
                # quedó y despues aparece rota en el catalogo.
                actualizar_imagen_producto(prod_id, self._foto_nueva_url)
                self._foto_fallo = str(e)

        # Se pregunta SIEMPRE antes de tocar el precio de venta, suba o
        # baje el costo. Antes, si subia, se cambiaba solo y recien
        # despues avisaba: uno cargaba mercaderia y salia con otros
        # precios en la gondola sin haberlo decidido.
        info = evaluar_cambio_costo(prod_id, costo)
        nuevo_precio_venta = None
        if (info["direccion"] == "subio"
                and round(info["precio_sugerido"], 2)
                    != round(info["precio_actual"], 2)):
            _margen_act = ((info["precio_actual"] - costo) / costo * 100
                           if costo else 0)
            if messagebox.askyesno(
                    "El costo subió",
                    f"El costo pasó de $ {info['costo_anterior']:,.2f} "
                    f"a $ {costo:,.2f}.\n\n"
                    f"Precio actual:    $ {info['precio_actual']:,.2f}   "
                    f"(margen {_margen_act:.0f}%)\n"
                    f"Precio sugerido:  $ {info['precio_sugerido']:,.2f}\n\n"
                    f"¿Actualizo el precio de venta?\n"
                    f"(si decís que no, se mantiene el actual)",
                    parent=self, default="yes"):
                nuevo_precio_venta = info["precio_sugerido"]
        elif (info["direccion"] == "bajo"
              and round(info["precio_sugerido"], 2) != round(info["precio_actual"], 2)):
            nuevo_precio_venta = None

            # El cartel muestra los tres datos que realmente deciden:
            # cuanto stock viejo queda (FIFO lo vende primero), que margen
            # se tiene si no se toca nada, y si bajar el precio dejaria el
            # stock viejo vendiendose por debajo de su costo.
            # El precio sugerido sale del margen del rubro, asi que
            # puede SUBIR aunque el costo haya bajado. Decir "si bajás el
            # precio" cuando en realidad sube es lo que confundia.
            _sug = info["precio_sugerido"]
            _act = info["precio_actual"]
            _verbo = "subir" if _sug > _act else "bajar"
            _dif = abs(_sug - _act)

            texto = [
                f"El costo bajó de $ {info['costo_anterior']:,.2f} "
                f"a $ {info['costo_nuevo']:,.2f}.",
                "",
                f"Dejarlo como está:  $ {_act:,.2f}"
                f"   →  te queda {info['margen_si_no_toca']:.0f}% de margen",
                f"{_verbo.capitalize()}lo a:          $ {_sug:,.2f}"
                f"   →  te queda {info['margen_sugerido']:.0f}% de margen",
                "",
                f"({_verbo} $ {_dif:,.2f}, que es el margen "
                f"de la categoría)",
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
                    texto += ["Esas unidades se venderían con el margen "
                              "nuevo, no con el que tenían."]

            texto += ["", f"¿{_verbo.capitalize()} el precio de venta "
                          f"a $ {_sug:,.2f}?",
                      f"(si decís que no, queda en $ {_act:,.2f})"]

            titulo = ("El costo bajó — ojo con el stock viejo"
                      if info["bajo_costo_viejo"]
                      else f"El costo bajó — ¿{_verbo} el precio?")
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
        # Si la alerta estaba silenciada, se ofrece reactivarla: se
        # silencia cuando un producto no se va a reponer, y al reponerlo
        # queda mudo justamente cuando vuelve a hacer falta.
        try:
            if (self._producto_actual
                    and self._producto_actual.get("ignorar_alerta")):
                if messagebox.askyesno(
                        "Alerta de stock",
                        f"«{self._producto_actual['descripcion'][:38]}» tiene "
                        f"la alerta de stock bajo SILENCIADA.\n\n"
                        f"Como estás reponiendo, ¿la vuelvo a activar?",
                        parent=self, default="yes"):
                    from repositorio import set_ignorar_alerta
                    set_ignorar_alerta(prod_id, False)
                    toast(self, "Alerta de stock reactivada")
        except Exception as exc:
            logging.debug(f"No se pudo revisar la alerta de stock: {exc}")

        if not self._producto_actual:
            self._ultima_cat = self.combo_cat.get().strip() or None

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
                    self.lbl_foto_nueva.config(text="✅  Foto elegida",
                                               fg=C.exito)
                else:
                    # Antes se descartaba en silencio: uno elegia una foto,
                    # no pasaba nada visible, y al guardar el producto
                    # quedaba sin imagen sin que nadie supiera por que.
                    self.lbl_foto_nueva.config(
                        text="⚠ No se pudo tomar esa foto — probá con otra",
                        fg=C.peligro)
                    if url:
                        logging.warning(f"Foto descartada, URL rara: {url[:80]}")
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
        _fallo = getattr(self, "_foto_fallo", None)
        if _fallo:
            self._foto_fallo = None
            messagebox.showwarning(
                "La foto no se pudo bajar",
                f"El stock se registró bien, pero la foto quedó como link "
                f"externo y puede no verse.\n\n{_fallo}\n\n"
                f"Podés probar otra foto desde Catálogo → Editar producto.",
                parent=self)

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

    def _editar_lote(self, event=None):
        """Abre el editor completo del lote seleccionado.

        Antes había un botón solo para el vencimiento y el doble clic
        corregía solo el proveedor. Es el mismo editor que usa el
        historial completo: cantidad, costo, proveedor, vencimiento y
        notas en un solo lugar.
        """
        sel = self.tree_lotes.selection()
        if not sel:
            messagebox.showinfo("Editar lote",
                                "Seleccioná un ingreso de la lista.",
                                parent=self)
            return
        lote_id = int(sel[0])

        from repositorio import get_lotes_recientes
        filas = {int(l["id"]): dict(l) for l in get_lotes_recientes(200)}
        if lote_id not in filas:
            messagebox.showinfo("Editar lote",
                                "No se encontró ese lote.", parent=self)
            return

        from historial_lotes_ui import editar_lote_dialogo
        editar_lote_dialogo(self, self.tree_lotes, filas,
                            self._refrescar_lotes)

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

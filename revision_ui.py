"""
revision_ui.py — Solapa "A revisar" del grupo Productos.

Es una revision de campaña: se recorre TODO el catalogo, se corrige lo
que haga falta y se va marcando lo hecho. La pantalla lleva la cuenta de
por donde va.

No es una lista aparte de productos apartados: eso obligaba a mandarlos
a otro lado y volver, y no dejaba ver cuanto faltaba del total.

El flujo pensado es: filtrar "sin revisar", doble clic en el primero,
corregir el precio, Enter — y sigue solo en el siguiente.
"""

import tkinter as tk
from tkinter import ttk, messagebox

from styles import C, F, btn, lbl, tabla, toast
from repositorio import (get_productos_revision, progreso_revision,
                         cambiar_estado_revision, marcar_para_revisar,
                         reiniciar_revision, get_categorias,
                         get_producto_completo, actualizar_producto,
                         redondear_precio)
from config import cfg


COLS = [
    ("estado",  "Estado",     92,  "w"),
    ("codigo",  "Codigo",     120, "w"),
    ("desc",    "Producto",   250, "w"),
    ("cat",     "Categoria",  120, "w"),
    ("costo",   "Costo",      95,  "e"),
    ("precio",  "Precio",     95,  "e"),
    ("margen",  "Margen",     75,  "e"),
    ("stock",   "Stock",      65,  "e"),
    ("nota",    "Nota",       170, "w"),
]


class RevisionUI(ttk.Frame):

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._filas = []
        self._construir()
        self.after(120, self.refrescar)

    def _construir(self):
        cab = tk.Frame(self, bg=C.bg)
        cab.pack(fill="x", padx=12, pady=(10, 2))
        lbl(cab, "Revisión de precios", variante="titulo").pack(side="left")
        self.lbl_prog = lbl(cab, "", variante="subtitulo")
        self.lbl_prog.pack(side="right")

        # Barra de progreso: es lo que hace llevadera una tarea larga
        self.barra_prog = ttk.Progressbar(self, mode="determinate", maximum=100)
        self.barra_prog.pack(fill="x", padx=12, pady=(4, 2))

        lbl(self, "Doble clic para editar el producto. Enter guarda, lo "
                  "marca como revisado y abre el siguiente.",
            variante="suave").pack(anchor="w", padx=12)

        barra = tk.Frame(self, bg=C.bg)
        barra.pack(fill="x", padx=12, pady=(8, 6))

        lbl(barra, "Ver:", variante="suave").pack(side="left")
        self.filtro = tk.StringVar(value="sin_revisar")
        cb = ttk.Combobox(barra, textvariable=self.filtro, width=13,
                          state="readonly",
                          values=("sin_revisar", "revisado", "todos"))
        cb.pack(side="left", padx=6)
        cb.bind("<<ComboboxSelected>>", lambda e: self.refrescar())

        lbl(barra, "Categoria:", variante="suave").pack(side="left", padx=(12, 4))
        self._cats = [{"id": None, "nombre": "Todas"}] + list(get_categorias())
        self.var_cat = tk.StringVar(value="Todas")
        cbc = ttk.Combobox(barra, textvariable=self.var_cat, width=18,
                           state="readonly",
                           values=[c["nombre"] for c in self._cats])
        cbc.pack(side="left")
        cbc.bind("<<ComboboxSelected>>", lambda e: self.refrescar())

        lbl(barra, "Buscar:", variante="suave").pack(side="left", padx=(12, 4))
        self.var_busq = tk.StringVar()
        e = tk.Entry(barra, textvariable=self.var_busq, width=20, font=F.normal,
                     bg=C.superficie, fg=C.texto, relief="solid", bd=1)
        e.pack(side="left")
        e.bind("<KeyRelease>", lambda ev: self.refrescar())

        btn(barra, "☑ Seleccionar todo", variante="neutro",
            comando=self._seleccionar_todo).pack(side="left", padx=10)
        btn(barra, "Actualizar", variante="neutro",
            comando=self.refrescar).pack(side="right")

        cont = tk.Frame(self, bg=C.bg)
        cont.pack(fill="both", expand=True, padx=12)
        frame_t, self.tree = tabla(cont, COLS, altura=16)
        frame_t.pack(fill="both", expand=True)
        self.tree.configure(selectmode="extended")
        self.tree.tag_configure("revisado", background=C.ok_flash)
        self.tree.tag_configure("sincosto", foreground=C.peligro)
        self.tree.bind("<Double-1>", lambda e: self._editar())
        self.tree.bind("<Return>", lambda e: self._editar())
        self.tree.bind("<Control-a>", self._seleccionar_todo)
        self.tree.bind("<Control-A>", self._seleccionar_todo)

        ac = tk.Frame(self, bg=C.bg)
        ac.pack(fill="x", padx=12, pady=(8, 10))
        btn(ac, "✓  Marcar como revisado", variante="exito",
            comando=lambda: self._cambiar("revisado")).pack(side="left")
        btn(ac, "Volver a sin revisar", variante="neutro",
            comando=lambda: self._cambiar("pendiente")).pack(side="left", padx=6)
        btn(ac, "✎  Editar producto", variante="primario",
            comando=self._editar).pack(side="left", padx=6)
        btn(ac, "↺  Redondear seleccionados", variante="neutro",
            comando=self._redondear_seleccion).pack(side="left", padx=6)
        btn(ac, "🗑  Sacar de la revisión", variante="neutro",
            comando=self._sacar_de_revision).pack(side="left", padx=6)
        self.btn_reiniciar = btn(ac, "Volver a revisar todo",
                                 variante="peligro", comando=self._reiniciar)
        self.btn_reiniciar.pack(side="right")

    # ── Datos ─────────────────────────────────────────────────────────

    def refrescar(self):
        estado = self.filtro.get()
        cat_id = self._cats[[c["nombre"] for c in self._cats]
                            .index(self.var_cat.get())]["id"]
        try:
            self._filas = get_productos_revision(
                None if estado == "todos" else estado,
                cat_id, self.var_busq.get().strip())
            prog = progreso_revision()
        except Exception as exc:
            messagebox.showerror("Revisión", f"No se pudo leer:\n{exc}",
                                 parent=self)
            return

        self.tree.delete(*self.tree.get_children())
        for i, r in enumerate(self._filas):
            costo = r["costo_ultimo"] or 0
            precio = r["precio_base"] or 0
            margen = ((precio - costo) / costo * 100) if costo else None
            tags = []
            if r["estado"] == "revisado":
                tags.append("revisado")
            elif not costo:
                tags.append("sincosto")
            self.tree.insert("", "end", iid=str(i), tags=tuple(tags), values=(
                "✓ revisado" if r["estado"] == "revisado" else "sin revisar",
                r["codigo"] or "—",
                r["descripcion"][:44],
                r["categoria"] or "—",
                f"$ {costo:,.2f}" if costo else "sin costo",
                f"$ {precio:,.2f}",
                f"{margen:.1f}%" if margen is not None else "—",
                f"{r['stock']:g}",
                (r["notas"] or "")[:32]))

        # El botón dice sobre qué va a actuar: con una categoría filtrada
        # reiniciar todo el catálogo sería una sorpresa desagradable.
        cat = self.var_cat.get()
        self.btn_reiniciar.config(
            text=("Volver a revisar todo" if cat == "Todas"
                  else f"Volver a revisar «{cat[:18]}»"))

        self.barra_prog["value"] = prog["pct"]
        self.lbl_prog.config(
            text=(f"{prog['revisados']} de {prog['total']} revisados "
                  f"({prog['pct']:.0f}%)   ·   {prog['pendientes']} pendientes"))

    def _seleccionar_todo(self, event=None):
        hijos = self.tree.get_children()
        self.tree.selection_set(hijos)
        if hijos:
            self.tree.focus(hijos[0])
        return "break"

    def _seleccionados(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Revisión", "Elegí al menos un producto.",
                                parent=self)
            return []
        return [self._filas[int(i)]["producto_id"] for i in sel]

    def _cambiar(self, estado):
        ids = self._seleccionados()
        if not ids:
            return
        # Los que nunca se tocaron no tienen fila todavia
        marcar_para_revisar(ids, "Precio", "")
        cambiar_estado_revision(ids, estado)
        toast(self, f"{len(ids)} producto(s) → "
                    f"{'revisado' if estado == 'revisado' else 'sin revisar'}")
        self.refrescar()

    def _redondear_seleccion(self):
        """Redondea el precio de los productos elegidos, sin abrir cada uno.

        Sirve para el paso final de una revision: se recorrio todo, se
        ajustaron los precios, y quedan con decimales feos.
        """
        from repositorio import set_precio_base
        paso = int(cfg().get("redondeo_precios", 0) or 0)
        if paso <= 0:
            messagebox.showinfo(
                "Redondear",
                "El redondeo está en 0 (desactivado).\n\n"
                "Elegí el múltiplo en Config → Redondeo de precios.",
                parent=self)
            return
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Redondear", "Elegí al menos un producto.",
                                parent=self)
            return
        modo = str(cfg().get("redondeo_modo", "cercano"))
        filas = [self._filas[int(i)] for i in sel]
        cambios = []
        for r in filas:
            viejo = float(r["precio_base"] or 0)
            nuevo = redondear_precio(viejo, paso, modo)
            if viejo > 0 and abs(nuevo - viejo) >= 0.005:
                cambios.append((r, viejo, nuevo))

        if not cambios:
            messagebox.showinfo("Redondear",
                                f"Los {len(filas)} precios ya están redondos.",
                                parent=self)
            return

        muestra = "\n".join(
            f"  {r['descripcion'][:30]}:  $ {vi:,.2f} → $ {nu:,.2f}"
            for r, vi, nu in cambios[:8])
        extra = f"\n  ...y {len(cambios) - 8} más" if len(cambios) > 8 else ""
        if not messagebox.askyesno(
                "Redondear precios",
                f"{len(cambios)} de {len(filas)} precios cambian, a múltiplos "
                f"de ${paso} (modo {modo}):\n\n{muestra}{extra}\n\n¿Confirmás?",
                parent=self):
            return

        for r, _vi, nuevo in cambios:
            set_precio_base(r["producto_id"], nuevo)
        toast(self, f"{len(cambios)} precio(s) redondeado(s)")
        self.refrescar()

    def _sacar_de_revision(self):
        """Borra el registro de los elegidos: vuelven a 'sin revisar'.

        Es lo mismo que "volver a pendiente" pero sin dejar rastro (ni
        motivo ni nota vieja). Sirve para limpiar antes de empezar una
        ronda nueva marcando desde el Catálogo.
        """
        from repositorio import quitar_de_revision
        ids = self._seleccionados()
        if not ids:
            return
        if not messagebox.askyesno(
                "Sacar de la revisión",
                f"Se borra el registro de revisión de {len(ids)} "
                f"producto(s): vuelven a figurar como 'sin revisar' y se "
                f"pierden sus notas.\n\n"
                "Los productos y sus precios no se tocan.\n\n¿Seguro?",
                parent=self):
            return
        quitar_de_revision(ids)
        toast(self, f"{len(ids)} producto(s) sacados de la revisión")
        self.refrescar()

    def _reiniciar(self):
        """Vuelve a 'sin revisar'. Respeta la categoría filtrada.

        Reiniciar TODO cuando uno solo quiere repasar un rubro hace
        perder el avance del resto del catálogo.
        """
        cat_id = self._cats[[c["nombre"] for c in self._cats]
                            .index(self.var_cat.get())]["id"]
        cat_nombre = self.var_cat.get()

        if cat_id:
            texto = (f"Los productos de «{cat_nombre}» vuelven a "
                     f"'sin revisar'.\n\nEl resto del catálogo no se toca.")
        else:
            texto = ("TODO el catálogo vuelve a 'sin revisar'.\n\n"
                     "Si solo querés repasar un rubro, elegí primero esa "
                     "categoría en el filtro de arriba.")

        if messagebox.askyesno(
                "Volver a revisar", texto +
                "\n\nLos precios NO se tocan: solo se borra el registro de "
                "qué revisaste.\n\n¿Seguro?", parent=self):
            n = reiniciar_revision(cat_id)
            toast(self, f"{n} producto(s) vuelven a estar sin revisar")
            self.refrescar()

    # ── Edición en el lugar ───────────────────────────────────────────

    def _editar(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Revisión", "Elegí un producto.", parent=self)
            return
        self._abrir_editor(int(sel[0]))

    def _abrir_editor(self, idx):
        """Editor completo del producto, encadenado.

        Enter guarda, marca revisado y abre el siguiente pendiente: la
        revision se hace de a cientos, y volver a la lista entre uno y
        otro duplica el trabajo.
        """
        if idx >= len(self._filas):
            return
        pid = self._filas[idx]["producto_id"]
        prod = get_producto_completo(pid)
        if not prod:
            return

        d = tk.Toplevel(self)
        d.title("Revisar producto")
        d.configure(bg=C.superficie)
        d.grab_set()
        w = 520
        h = min(660, d.winfo_screenheight() - 120)
        sw, sh = d.winfo_screenwidth(), d.winfo_screenheight()
        d.geometry(f"{w}x{h}+{(sw-w)//2}+{max(0,(sh-h)//2)}")

        cab = tk.Frame(d, bg=C.superficie)
        cab.pack(fill="x", padx=18, pady=(14, 2))
        lbl(cab, f"{idx + 1} de {len(self._filas)}", variante="suave",
            bg=C.superficie).pack(side="right")
        lbl(cab, prod["descripcion"][:38], variante="titulo",
            bg=C.superficie).pack(side="left")
        lbl(d, f"stock {self._filas[idx]['stock']:g}", variante="suave",
            bg=C.superficie).pack(anchor="w", padx=18)

        cuerpo = tk.Frame(d, bg=C.superficie)
        cuerpo.pack(fill="both", expand=True, padx=18, pady=(10, 0))
        cuerpo.columnconfigure(1, weight=1)

        v = {}

        def _campo(fila, etiqueta, clave, valor, ancho=None):
            tk.Label(cuerpo, text=etiqueta, bg=C.superficie, fg=C.texto_suave,
                     font=F.pequeña, anchor="w").grid(row=fila * 2, column=0,
                                                      columnspan=2, sticky="w",
                                                      pady=(8, 1))
            var = tk.StringVar(value="" if valor is None else str(valor))
            ent = tk.Entry(cuerpo, textvariable=var, font=F.normal,
                           bg=C.bg, fg=C.texto, relief="solid", bd=1)
            ent.grid(row=fila * 2 + 1, column=0, columnspan=2, sticky="ew",
                     ipady=4)
            v[clave] = var
            return ent

        e_desc = _campo(0, "Descripción", "descripcion", prod["descripcion"])
        desc_original = prod["descripcion"]
        _campo(1, "Código de barras", "codigo", prod.get("codigo") or "")
        _campo(2, "Marca", "marca", prod.get("marca") or "")

        # Categoría
        tk.Label(cuerpo, text="Categoría", bg=C.superficie, fg=C.texto_suave,
                 font=F.pequeña, anchor="w").grid(row=5, column=0, columnspan=2,
                                                  sticky="w", pady=(8, 1))
        cats = get_categorias()
        v_cat = tk.StringVar(value=next(
            (c["nombre"] for c in cats if c["id"] == prod.get("categoria_id")),
            cats[0]["nombre"] if cats else ""))
        ttk.Combobox(cuerpo, textvariable=v_cat, state="readonly",
                     values=[c["nombre"] for c in cats]).grid(
            row=6, column=0, columnspan=2, sticky="ew", pady=(1, 0))

        # Costo, precio y margen: los tres se recalculan entre si
        f3 = tk.Frame(cuerpo, bg=C.superficie)
        f3.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(10, 0))

        # El margen que se muestra es el REAL (precio contra costo), no
        # productos.margen_pct: esa columna suele estar vacia porque el
        # producto hereda el margen de su categoria, y el campo salia en
        # blanco justo cuando es el dato que uno viene a mirar.
        _costo_ini = float(prod.get("costo_ultimo") or 0)
        _precio_ini = float(prod.get("precio_base") or 0)
        _margen_ini = ((_precio_ini - _costo_ini) / _costo_ini * 100
                       if _costo_ini else None)

        for i, (etq, clave, val) in enumerate((
                ("Costo", "costo", _costo_ini),
                ("Precio de venta", "precio", _precio_ini),
                ("Margen %", "margen", _margen_ini))):
            f3.columnconfigure(i, weight=1)
            tk.Label(f3, text=etq, bg=C.superficie, fg=C.texto_suave,
                     font=F.pequeña, anchor="w").grid(row=0, column=i,
                                                      sticky="w", padx=(0, 6))
            var = tk.StringVar(value="" if val in (None, "") else f"{float(val):.2f}")
            ent3 = tk.Entry(f3, textvariable=var, font=F.normal, justify="center",
                            bg=C.bg, fg=C.texto, relief="solid", bd=1)
            ent3.grid(row=1, column=i, sticky="ew", padx=(0, 6), ipady=4)
            v[clave] = var
            if clave == "precio":
                e_precio = ent3

        # Margen objetivo (el del producto o el heredado de la categoria):
        # sirve para ver de un vistazo si este producto se corrio de lo
        # que uno se propuso para el rubro.
        _obj = prod.get("margen_pct")
        if _obj is None:
            _obj = next((c.get("margen_pct") for c in cats
                         if c["id"] == prod.get("categoria_id")), None)
        if _obj is not None:
            texto_obj = f"Margen objetivo del rubro: {float(_obj):.1f}%"
            if _margen_ini is not None:
                dif = _margen_ini - float(_obj)
                texto_obj += f"   ·   este está {dif:+.1f} pts"
            tk.Label(cuerpo, text=texto_obj, bg=C.superficie,
                     fg=C.texto_suave, font=F.pequeña, anchor="w").grid(
                row=8, column=0, columnspan=2, sticky="w", pady=(6, 0))

        v_peso = tk.BooleanVar(value=bool(prod.get("vendido_por_peso")))
        tk.Checkbutton(cuerpo, text="Vendido por peso", variable=v_peso,
                       bg=C.superficie, fg=C.texto, font=F.normal,
                       selectcolor=C.superficie,
                       activebackground=C.superficie).grid(
            row=9, column=0, columnspan=2, sticky="w", pady=(10, 0))

        _campo(5, "Nota de revisión", "nota", self._filas[idx]["notas"] or "")

        paso_red = int(cfg().get("redondeo_precios", 0) or 0)
        modo_red = str(cfg().get("redondeo_modo", "cercano"))

        aviso = tk.Label(d, text="", bg=C.superficie, font=F.pequeña, anchor="w")
        aviso.pack(fill="x", padx=18, pady=(8, 0))

        # ── Recalculo entre costo / precio / margen ────────────────────
        recalculando = [False]

        def _num(clave):
            try:
                return float((v[clave].get() or "").replace(",", "."))
            except ValueError:
                return None

        def _al_cambiar_precio(*_a):
            """Precio → margen. Es lo que uno toca mirando la competencia."""
            if recalculando[0]:
                return
            costo, precio = _num("costo"), _num("precio")
            if costo and precio is not None:
                recalculando[0] = True
                v["margen"].set(f"{(precio - costo) / costo * 100:.2f}")
                recalculando[0] = False
            _pintar_aviso()

        def _al_cambiar_margen(*_a):
            """Margen → precio. NO vuelve a escribir en el campo margen.

            Antes se recalculaba el margen tras redondear el precio y se
            reescribia en el mismo campo: mientras uno tipeaba o borraba,
            el numero saltaba solo. El redondeo se aplica al guardar, no
            mientras se escribe.
            """
            if recalculando[0]:
                return
            costo, margen = _num("costo"), _num("margen")
            if costo and margen is not None:
                recalculando[0] = True
                v["precio"].set(f"{costo * (1 + margen / 100):.2f}")
                recalculando[0] = False
            _pintar_aviso()

        def _pintar_aviso(*_a):
            costo, precio = _num("costo"), _num("precio")
            if precio is not None and precio < (costo or 0):
                aviso.config(text=f"⚠  El precio queda por debajo del costo "
                                  f"(perdés $ {costo - precio:,.2f} por unidad).",
                             fg=C.peligro)
                return
            if not costo:
                aviso.config(text="Sin costo cargado: no se puede calcular margen.",
                             fg=C.advertencia)
                return
            # Se avisa a que va a quedar al guardar, sin tocar los campos:
            # tocarlos mientras se escribe hace saltar el numero.
            if paso_red > 0 and precio is not None:
                red = redondear_precio(precio, paso_red, modo_red)
                if abs(red - precio) >= 0.005:
                    m = (red - costo) / costo * 100
                    aviso.config(
                        text=f"Al guardar se redondea a $ {red:,.2f} "
                             f"(margen {m:.1f}%)", fg=C.texto_suave)
                    return
            aviso.config(text="", fg=C.texto)

        v["precio"].trace_add("write", _al_cambiar_precio)
        v["margen"].trace_add("write", _al_cambiar_margen)
        v["costo"].trace_add("write", _al_cambiar_precio)
        _pintar_aviso()

        # ── Guardar ───────────────────────────────────────────────────
        def guardar(_ev=None, seguir=True):
            desc = v["descripcion"].get().strip()
            if not desc:
                messagebox.showwarning("Revisión", "La descripción no puede "
                                                   "quedar vacía.", parent=d)
                return
            # Un cambio brusco de descripcion casi siempre es un tecleo
            # accidental sobre el texto seleccionado, no una correccion.
            if desc != desc_original and (
                    len(desc) < 4 or len(desc) < len(desc_original) / 2):
                if not messagebox.askyesno(
                        "¿Seguro?",
                        f"La descripción cambia de:\n\n"
                        f"   «{desc_original}»\n\na:\n\n   «{desc}»\n\n"
                        "Parece un tecleo accidental. ¿Guardar igual?",
                        parent=d):
                    v["descripcion"].set(desc_original)
                    e_desc.focus_set()
                    return
            precio = _num("precio")
            if precio is None:
                messagebox.showwarning("Revisión", "El precio no es un número.",
                                       parent=d)
                return
            costo = _num("costo")
            if costo is not None and precio < costo:
                if not messagebox.askyesno(
                        "Precio bajo costo",
                        f"El precio ($ {precio:,.2f}) queda por debajo del "
                        f"costo ($ {costo:,.2f}).\n\n¿Guardar igual?",
                        parent=d):
                    return

            # Regla: el precio se guarda siempre redondeado segun Config.
            if paso_red > 0:
                precio = redondear_precio(precio, paso_red, modo_red)

            cat_id = next((c["id"] for c in cats if c["nombre"] == v_cat.get()),
                          prod.get("categoria_id"))
            try:
                actualizar_producto(
                    pid, desc, v["codigo"].get().strip() or None, cat_id,
                    precio, costo, _num("margen"),
                    int(v_peso.get()), prod.get("imagen_url"),
                    v["marca"].get().strip())
            except Exception as exc:
                messagebox.showerror("Revisión", f"No se pudo guardar:\n{exc}",
                                     parent=d)
                return

            nota = v["nota"].get().strip()
            marcar_para_revisar(pid, "Precio", nota)
            cambiar_estado_revision(pid, "revisado", nota)
            d.destroy()
            self.refrescar()
            if seguir:
                self._siguiente_pendiente(idx)

        # Enter guarda desde cualquier campo MENOS la descripcion: ahi
        # se escribe texto y un Enter de mas guardaba lo que hubiera
        # quedado tipeado, sin volver a mirarlo.
        def _enter(ev=None):
            if d.focus_get() is e_desc:
                e_precio.focus_set()
                e_precio.select_range(0, "end")
                return "break"
            return guardar()

        d.bind("<Return>", _enter)
        d.bind("<KP_Enter>", _enter)
        d.bind("<Escape>", lambda ev: d.destroy())

        pie = tk.Frame(d, bg=C.superficie)
        pie.pack(side="bottom", fill="x", pady=14)
        btn(pie, "Guardar y seguir  (Enter)", variante="exito",
            comando=guardar).pack(side="left", padx=(18, 6))
        btn(pie, "Guardar y cerrar", variante="neutro",
            comando=lambda: guardar(seguir=False)).pack(side="left", padx=6)
        btn(pie, "Cancelar  (Esc)", variante="neutro",
            comando=d.destroy).pack(side="left")

        # El foco NO va en la descripcion: arrancaba con el texto
        # seleccionado y cualquier tecla lo reemplazaba entero. Se
        # revisan precios, asi que el foco arranca ahi.
        e_precio.focus_set()
        e_precio.select_range(0, "end")

    def _siguiente_pendiente(self, idx_anterior):
        """Abre el siguiente sin revisar, para no volver a la lista cada vez."""
        hijos = self.tree.get_children()
        if not hijos:
            toast(self, "¡Listo! No quedan productos con este filtro.")
            return
        destino = min(idx_anterior, len(hijos) - 1)
        iid = str(destino)
        if iid not in hijos:
            iid = hijos[0]
        self.tree.selection_set(iid)
        self.tree.see(iid)
        self.after(60, lambda: self._abrir_editor(int(iid)))


# ══════════════════════════════════════════════════════════════════════════
# Diálogo para marcar productos — se usa desde Catálogo y desde Auditoría
# ══════════════════════════════════════════════════════════════════════════

def dialogo_marcar(parent, producto_ids, descripcion_corta=""):
    """Pide motivo y nota, y manda los productos a la cola de revisión.

    Si alguno ya estaba revisado, vuelve a pendiente: marcar algo de
    nuevo es justamente decir "esto hay que volver a mirarlo".

    Devuelve True si se marcaron.
    """
    from repositorio import marcar_para_revisar, get_revision, MOTIVOS_REVISION

    ids = [producto_ids] if isinstance(producto_ids, int) else list(producto_ids)
    if not ids:
        messagebox.showinfo("A revisar", "Elegí al menos un producto.",
                            parent=parent)
        return False

    d = tk.Toplevel(parent)
    d.title("Marcar para revisar")
    d.configure(bg=C.superficie)
    d.grab_set()
    w, h = 470, 320
    sw, sh = d.winfo_screenwidth(), d.winfo_screenheight()
    d.geometry(f"{w}x{h}+{(sw-w)//2}+{max(0,(sh-h)//2)}")

    lbl(d, "Marcar para revisar", variante="titulo",
        bg=C.superficie).pack(anchor="w", padx=18, pady=(16, 2))
    detalle = (descripcion_corta if len(ids) == 1 and descripcion_corta
               else f"{len(ids)} producto(s) seleccionado(s)")
    lbl(d, detalle[:52], variante="suave",
        bg=C.superficie).pack(anchor="w", padx=18)

    # Si alguno ya estaba revisado, se avisa: vuelve a pendiente, que es
    # la intención, pero conviene verlo antes de confirmar.
    try:
        ya = {r["producto_id"]: r["estado"] for r in get_revision()}
    except Exception:
        ya = {}
    revisados = [i for i in ids if ya.get(i) == "revisado"]
    if revisados:
        lbl(d, f"⚠ {len(revisados)} ya estaba(n) revisado(s): vuelven a "
               f"pendiente.", variante="suave",
            bg=C.superficie).pack(anchor="w", padx=18, pady=(8, 0))

    lbl(d, "¿Qué hay que revisar?", variante="suave", bg=C.superficie).pack(
        anchor="w", padx=18, pady=(14, 2))
    v_motivo = tk.StringVar(value=MOTIVOS_REVISION[0])
    ttk.Combobox(d, textvariable=v_motivo, values=list(MOTIVOS_REVISION),
                 state="readonly").pack(fill="x", padx=18)

    lbl(d, "Nota (opcional)", variante="suave", bg=C.superficie).pack(
        anchor="w", padx=18, pady=(12, 2))
    v_nota = tk.StringVar()
    e = tk.Entry(d, textvariable=v_nota, font=F.normal, bg=C.bg, fg=C.texto,
                 relief="solid", bd=1)
    e.pack(fill="x", padx=18, ipady=5)
    e.focus_set()

    hecho = [False]

    def guardar(_ev=None):
        marcar_para_revisar(ids, v_motivo.get(), v_nota.get().strip())
        hecho[0] = True
        d.destroy()

    e.bind("<Return>", guardar)
    d.bind("<Escape>", lambda ev: d.destroy())

    fb = tk.Frame(d, bg=C.superficie)
    fb.pack(side="bottom", pady=16)
    btn(fb, "Marcar  (Enter)", variante="exito",
        comando=guardar).pack(side="left", padx=4)
    btn(fb, "Cancelar", variante="neutro", comando=d.destroy).pack(side="left", padx=4)

    parent.wait_window(d)
    return hecho[0]

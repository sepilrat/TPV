"""
factura_ui.py — Importar factura de proveedor desde una foto TPV v2.0

Flujo: elegís la foto → OCR en segundo plano → se revisa CADA línea
una por una (cantidad/descripción/precio editables + a qué producto
del catálogo corresponde, o si es nuevo) → recién al final, con todo
confirmado, se carga a la base (stock + productos nuevos si hacen
falta). Nunca se inserta nada sin que el usuario lo haya confirmado
línea por línea.
"""

import logging
import threading
import difflib
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog

from styles import C, F, btn, lbl, card, scrollable
from factura_ocr import FORMATOS_FACTURA
from repositorio import (get_productos, get_proveedores, crear_proveedor,
                         crear_producto, registrar_lote, get_categorias,
                         evaluar_cambio_costo, set_formato_factura_proveedor,
                         parsear_fecha, get_producto_por_codigo)


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


def _mejores_coincidencias(descripcion_ocr, productos, top=4, umbral=0.5):
    """Busca los productos del catálogo cuyo nombre se parece más al
    texto que leyó el OCR (comparación difusa, no exacta — el OCR
    rara vez transcribe el nombre exactamente como está cargado)."""
    objetivo = descripcion_ocr.lower().strip()
    puntuados = []
    for p in productos:
        score = difflib.SequenceMatcher(
            None, objetivo, p["descripcion"].lower()).ratio()
        if score >= umbral:
            puntuados.append((score, p))
    puntuados.sort(key=lambda x: -x[0])
    return [p for _, p in puntuados[:top]]


def abrir_importar_factura(parent):
    ruta = filedialog.askopenfilename(
        parent=parent, title="Elegir foto de la factura",
        filetypes=[("Imagenes", "*.jpg *.jpeg *.png *.webp *.bmp *.heic")])
    if not ruta:
        return

    # Primero, a qué proveedor corresponde esta factura
    proveedor_id, formato = _pedir_proveedor(parent)
    if proveedor_id is False:
        return   # cancelado

    d = tk.Toplevel(parent)
    d.title("Leyendo factura...")
    _centrar(d, 420, 150)
    d.configure(bg=C.superficie)
    d.resizable(False, False)
    d.grab_set()
    d.protocol("WM_DELETE_WINDOW", lambda: None)

    lbl(d, "Leyendo la factura...", variante="titulo",
        bg=C.superficie).pack(pady=(24,6), padx=20, anchor="w")
    lbl(d, "Puede tardar unos segundos, sobre todo la primera vez.",
        variante="suave", bg=C.superficie).pack(padx=20, anchor="w")
    barra = ttk.Progressbar(d, mode="indeterminate")
    barra.pack(fill="x", padx=20, pady=20)
    barra.start(12)

    resultado = {"lineas": None, "error": None}

    def _trabajar():
        try:
            import factura_ocr
            resultado["lineas"] = factura_ocr.extraer_lineas_factura(
                ruta, formato=formato)
        except ModuleNotFoundError as e:
            falta = e.name or str(e)
            resultado["error"] = (
                f"Falta instalar una libreria para leer la factura "
                f"({falta}).\n\nDesde una consola, corré:\n\n"
                f"    pip install pytesseract pillow numpy\n\n"
                f"y volvé a intentar.")
        except Exception as e:
            resultado["error"] = str(e)

        def _seguir():
            if not d.winfo_exists():
                return
            d.destroy()
            if resultado["error"]:
                messagebox.showerror(
                    "No se pudo leer la factura",
                    resultado["error"], parent=parent)
                return
            lineas = resultado["lineas"] or []
            if not lineas:
                messagebox.showinfo(
                    "Sin resultados",
                    "No se encontró ninguna línea de producto reconocible "
                    "en la foto. Probá con mejor luz, más derecha, y que "
                    "se vea clara la tabla de cantidad/descripción/precio.",
                    parent=parent)
                return
            _revisar_tabla(parent, lineas, proveedor_id)
        try:
            d.after(0, _seguir)
        except tk.TclError as e:
            logging.debug(f"Dialogo cerrado antes de procesar la factura: {e}")

    threading.Thread(target=_trabajar, daemon=True).start()


def _pedir_proveedor(parent):
    """Devuelve (proveedor_id, formato) elegidos, o (False, None) si
    se canceló todo el importado."""
    proveedores = get_proveedores()
    mapa = {p["nombre"]: p for p in proveedores}

    d = tk.Toplevel(parent)
    d.title("¿De qué proveedor es esta factura?")
    _centrar(d, 420, 260)
    d.configure(bg=C.superficie)
    d.resizable(False, False)
    d.grab_set()

    lbl(d, "Proveedor de la factura", variante="titulo",
        bg=C.superficie).pack(pady=(20,8), padx=20, anchor="w")

    f = tk.Frame(d, bg=C.superficie)
    f.pack(fill="x", padx=20)
    combo = ttk.Combobox(f, font=F.normal, state="readonly",
                         values=list(mapa.keys()))
    combo.pack(side="left", fill="x", expand=True, ipady=4)
    if proveedores:
        combo.current(0)

    lbl(d, "¿Cómo vienen las columnas en SUS facturas?", variante="suave",
        bg=C.superficie).pack(padx=20, anchor="w", pady=(14,2))
    combo_formato = ttk.Combobox(d, font=F.normal, state="readonly",
                                 values=list(FORMATOS_FACTURA.values()))
    combo_formato.pack(padx=20, fill="x", ipady=4)

    claves_formato = list(FORMATOS_FACTURA.keys())

    def _cargar_formato(*_):
        p = mapa.get(combo.get())
        clave = (p or {}).get("formato_factura") or claves_formato[0]
        if clave not in claves_formato:
            clave = claves_formato[0]
        combo_formato.current(claves_formato.index(clave))

    combo.bind("<<ComboboxSelected>>", _cargar_formato)
    _cargar_formato()

    def _nuevo():
        nombre = simpledialog.askstring(
            "Nuevo proveedor", "Nombre del proveedor:", parent=d)
        if nombre and nombre.strip():
            pid = crear_proveedor(nombre.strip())
            mapa[nombre.strip()] = {"id": pid, "nombre": nombre.strip(),
                                    "formato_factura": claves_formato[0]}
            combo["values"] = list(mapa.keys())
            combo.set(nombre.strip())
            _cargar_formato()

    btn(f, "+ Nuevo", variante="neutro", comando=_nuevo).pack(side="left", padx=(6,0))

    resultado = {"id": False, "formato": None}

    def _continuar():
        p = mapa.get(combo.get())
        if not p:
            resultado["id"] = None
            resultado["formato"] = claves_formato[0]
            d.destroy()
            return
        formato = claves_formato[combo_formato.current()] \
            if combo_formato.current() >= 0 else claves_formato[0]
        if formato != p.get("formato_factura"):
            set_formato_factura_proveedor(p["id"], formato)
        resultado["id"] = p["id"]
        resultado["formato"] = formato
        d.destroy()

    def _cancelar():
        resultado["id"] = False
        d.destroy()

    btn(d, "Continuar", variante="primario", comando=_continuar).pack(
        pady=(20,6), padx=20, fill="x")
    btn(d, "Cancelar", variante="neutro", comando=_cancelar).pack(
        padx=20, fill="x")

    d.wait_window()
    return resultado["id"], resultado["formato"]


def _buscar_producto(parent, productos):
    """Buscador manual sobre TODO el catálogo — para cuando la
    coincidencia automática no encuentra el producto (descripción de
    la factura muy distinta a como está cargado, o por debajo del
    umbral de parecido). Devuelve el producto elegido o None."""
    d = tk.Toplevel(parent)
    d.title("Buscar producto")
    _centrar(d, 420, 460)
    d.configure(bg=C.superficie)
    d.grab_set()

    lbl(d, "Buscar producto", variante="titulo",
        bg=C.superficie).pack(pady=(16,4), padx=16, anchor="w")

    e_buscar = tk.Entry(d, font=F.normal, bg=C.superficie, fg=C.texto,
                        relief="solid", bd=1)
    e_buscar.pack(fill="x", padx=16, ipady=6)
    e_buscar.focus_set()

    f_lista = tk.Frame(d, bg=C.superficie)
    f_lista.pack(fill="both", expand=True, padx=16, pady=(10,10))
    scroll = tk.Scrollbar(f_lista)
    scroll.pack(side="right", fill="y")
    lista = tk.Listbox(f_lista, font=F.normal, activestyle="none",
                       yscrollcommand=scroll.set)
    lista.pack(side="left", fill="both", expand=True)
    scroll.config(command=lista.yview)

    ordenados = sorted(productos, key=lambda p: p["descripcion"].lower())

    def _refrescar(*_):
        filtro = e_buscar.get().strip().lower()
        lista.delete(0, "end")
        mostrados = [p for p in ordenados
                    if filtro in p["descripcion"].lower()] if filtro else ordenados
        for p in mostrados[:200]:
            lista.insert("end", f"{p['descripcion']}  (stock: {p.get('stock', 0):.0f})")
        lista._mostrados = mostrados

    lista._mostrados = ordenados
    e_buscar.bind("<KeyRelease>", _refrescar)
    _refrescar()

    resultado = {"producto": None}

    def _elegir(event=None):
        sel = lista.curselection()
        if not sel:
            return
        resultado["producto"] = lista._mostrados[sel[0]]
        d.destroy()

    lista.bind("<Double-1>", _elegir)
    e_buscar.bind("<Return>", lambda e: (
        _elegir() if lista.size() == 1 or lista.curselection() else None))

    bot = tk.Frame(d, bg=C.superficie)
    bot.pack(fill="x", padx=16, pady=(0,14))
    btn(bot, "Cancelar", variante="neutro", comando=d.destroy).pack(side="left")
    btn(bot, "Elegir", variante="primario", comando=_elegir).pack(side="right")

    d.wait_window()
    return resultado["producto"]


def _revisar_lineas(parent, lineas, proveedor_id):
    """Wizard: una línea a la vez. Al terminar todas, muestra un
    resumen y recién ahí escribe en la base."""
    productos_catalogo = get_productos(solo_activos=True)
    decisiones = []   # se va llenando: dict por línea ya resuelta
    cats = get_categorias()
    cat_map = {c["nombre"]: c["id"] for c in cats}
    # Se recuerda la última categoría elegida — una factura suele traer
    # productos de un solo rubro, así que arranca precargada de la
    # línea anterior en vez de forzar a elegirla de nuevo 36 veces.
    ultima_cat = {"nombre": next(iter(cat_map), None)}

    d = tk.Toplevel(parent)
    d.title("Revisar factura")
    _centrar(d, 620, 700)
    d.configure(bg=C.bg)
    d.resizable(True, True)
    d.grab_set()

    estado = {"i": 0}

    cont = tk.Frame(d, bg=C.bg)
    cont.pack(fill="both", expand=True)

    def _limpiar():
        for w in cont.winfo_children():
            w.destroy()

    def _mostrar_linea():
        _limpiar()
        i = estado["i"]
        if i >= len(lineas):
            d.destroy()
            _mostrar_resumen(parent, decisiones, proveedor_id)
            return

        linea = lineas[i]
        lbl(cont, f"Línea {i+1} de {len(lineas)}", variante="suave",
            bg=C.bg).pack(anchor="w", padx=20, pady=(16,2))

        f_datos = card(cont)
        f_datos.pack(fill="x", padx=20, pady=(0,10))

        campos = {}
        for etiqueta, clave, valor in [
            ("Cantidad",         "cantidad",        str(linea["cantidad"])),
            ("Descripción (según la factura)", "descripcion", linea["descripcion"]),
            ("Precio unitario",  "precio_unitario",
                "" if linea["precio_unitario"] is None else str(linea["precio_unitario"])),
        ]:
            lbl(f_datos, etiqueta, variante="suave", bg=C.superficie).pack(
                padx=14, anchor="w", pady=(10,0))
            e = tk.Entry(f_datos, font=F.normal, bg=C.superficie, fg=C.texto,
                        relief="solid", bd=1)
            e.insert(0, valor)
            e.pack(fill="x", padx=14, pady=(2,4), ipady=5)
            campos[clave] = e

        lbl(f_datos, "Vencimiento (opcional)", variante="suave",
            bg=C.superficie).pack(padx=14, anchor="w", pady=(6,0))
        e_venc = tk.Entry(f_datos, font=F.normal, bg=C.superficie, fg=C.texto,
                          relief="solid", bd=1)
        e_venc.pack(fill="x", padx=14, pady=(2,4), ipady=5)

        combo_categoria = None
        if cat_map:
            lbl(f_datos, "Categoría (se usa solo si es producto nuevo)",
                variante="suave", bg=C.superficie).pack(
                padx=14, anchor="w", pady=(6,0))
            combo_categoria = ttk.Combobox(f_datos, font=F.normal,
                                           state="readonly",
                                           values=list(cat_map.keys()))
            combo_categoria.pack(fill="x", padx=14, pady=(2,10), ipady=3)
            if ultima_cat["nombre"] in cat_map:
                combo_categoria.set(ultima_cat["nombre"])
            elif cat_map:
                combo_categoria.current(0)

        lbl(cont, "¿A cuál de estos productos de tu catálogo corresponde?",
            variante="suave", bg=C.bg).pack(anchor="w", padx=20, pady=(6,4))

        f_matches = tk.Frame(cont, bg=C.bg)
        f_matches.pack(fill="x", padx=20)

        elegido = {"producto_id": None, "es_nuevo": False}

        candidatos = _mejores_coincidencias(linea["descripcion"], productos_catalogo)

        botones_candidatos = []

        def _resaltar(widget_activo):
            for w in botones_candidatos:
                w.configure(bg=C.superficie, fg=C.texto)
            widget_activo.configure(bg=C.primario, fg="white")

        if candidatos:
            for p in candidatos:
                b = tk.Button(
                    f_matches, text=f"{p['descripcion']}  (stock: {p.get('stock', 0):.0f})",
                    font=F.normal, bg=C.superficie, fg=C.texto, relief="solid",
                    bd=1, anchor="w", padx=10, pady=6, cursor="hand2")
                b.configure(command=lambda pid=p["id"], bw=b: (
                    elegido.__setitem__("producto_id", pid),
                    elegido.__setitem__("es_nuevo", False),
                    _resaltar(bw)))
                b.pack(fill="x", pady=2)
                botones_candidatos.append(b)
        else:
            lbl(f_matches, "No se encontró nada parecido en tu catálogo.",
                variante="suave", bg=C.bg).pack(anchor="w")

        def _es_nuevo():
            elegido["producto_id"] = None
            elegido["es_nuevo"] = True
            for w in botones_candidatos:
                w.configure(bg=C.superficie, fg=C.texto)
            b_nuevo.configure(bg=C.exito, fg="white")

        b_nuevo = tk.Button(
            f_matches, text="➕  Ninguno — es un producto nuevo",
            font=F.normal, bg=C.superficie, fg=C.texto, relief="solid",
            bd=1, anchor="w", padx=10, pady=6, cursor="hand2",
            command=_es_nuevo)
        b_nuevo.pack(fill="x", pady=(6,2))
        botones_candidatos.append(b_nuevo)

        b_buscar = None

        def _buscar():
            prod = _buscar_producto(d, productos_catalogo)
            if not prod:
                return
            elegido["producto_id"] = prod["id"]
            elegido["es_nuevo"] = False
            for w in botones_candidatos:
                w.configure(bg=C.superficie, fg=C.texto)
            b_buscar.configure(
                bg=C.primario, fg="white",
                text=f"🔍  {prod['descripcion']}  (stock: {prod.get('stock', 0):.0f})")

        b_buscar = tk.Button(
            f_matches, text="🔍  Buscar otro producto en el catálogo...",
            font=F.normal, bg=C.superficie, fg=C.texto, relief="solid",
            bd=1, anchor="w", padx=10, pady=6, cursor="hand2",
            command=_buscar)
        b_buscar.pack(fill="x", pady=(2,2))
        botones_candidatos.append(b_buscar)

        bot = tk.Frame(cont, bg=C.bg)
        bot.pack(fill="x", padx=20, pady=14)

        def _descartar():
            estado["i"] += 1
            _mostrar_linea()

        def _siguiente():
            try:
                cantidad = float(campos["cantidad"].get().replace(",", "."))
                if cantidad <= 0: raise ValueError
            except ValueError:
                messagebox.showwarning("Atención", "Cantidad inválida.", parent=d)
                return
            try:
                precio_txt = campos["precio_unitario"].get().strip()
                precio = float(precio_txt.replace(",", ".")) if precio_txt else 0.0
            except ValueError:
                messagebox.showwarning("Atención", "Precio inválido.", parent=d)
                return
            descripcion = campos["descripcion"].get().strip()
            if not descripcion:
                messagebox.showwarning("Atención", "Falta la descripción.", parent=d)
                return
            if elegido["producto_id"] is None and not elegido["es_nuevo"]:
                messagebox.showwarning(
                    "Atención",
                    "Elegí a qué producto corresponde esta línea, o marcá "
                    "\"es un producto nuevo\".", parent=d)
                return

            vence_txt = e_venc.get().strip()
            vencimiento = None
            if vence_txt:
                vencimiento = parsear_fecha(vence_txt)
                if not vencimiento:
                    messagebox.showwarning(
                        "Atención",
                        "No entiendo esa fecha de vencimiento.\n\n"
                        "Podés escribirla como 15/03/27, 15/03/2027, "
                        "15-3-27 o 150327, o dejarla vacía.", parent=d)
                    return

            categoria_id = None
            if combo_categoria is not None and combo_categoria.get():
                ultima_cat["nombre"] = combo_categoria.get()
                categoria_id = cat_map.get(combo_categoria.get())

            decisiones.append({
                "cantidad": cantidad,
                "descripcion": descripcion,
                "precio_unitario": precio,
                "producto_id": elegido["producto_id"],
                "es_nuevo": elegido["es_nuevo"],
                "vencimiento": vencimiento,
                "categoria_id": categoria_id,
            })
            estado["i"] += 1
            _mostrar_linea()

        btn(bot, "Descartar esta línea", variante="neutro",
            comando=_descartar).pack(side="left")
        btn(bot, "Siguiente →", variante="primario",
            comando=_siguiente).pack(side="right")

    _mostrar_linea()


def _revisar_tabla(parent, lineas, proveedor_id):
    """Pantalla única con TODAS las líneas de la factura en una tabla
    editable — cantidad, descripción, precio, código de barras, a qué
    producto corresponde, categoría (si es nuevo), vencimiento, y si
    se vende por peso o es fraccionable. Cada línea se puede cargar
    de a una con su propio botón "✓", o todas juntas (las que sigan
    tildadas) con el botón "Confirmar" de abajo."""
    productos_catalogo = get_productos(solo_activos=True)
    cats = get_categorias()
    cat_map = {c["nombre"]: c["id"] for c in cats}
    cat_margen = {c["nombre"]: c.get("margen_pct") for c in cats}
    nombres_cat = list(cat_map.keys())

    d = tk.Toplevel(parent)
    d.title("Revisar factura completa")
    _centrar(d, 1460, 720)
    d.configure(bg=C.bg)
    d.resizable(True, True)
    d.grab_set()

    lbl(d, f"Factura — {len(lineas)} línea(s) detectada(s)",
        variante="titulo", bg=C.bg).pack(anchor="w", padx=16, pady=(12,2))
    lbl(d, "Revisá y corregí lo que haga falta. \"✓\" carga esa línea sola; "
          "\"Confirmar\" carga todas las que sigan tildadas.",
        variante="suave", bg=C.bg).pack(anchor="w", padx=16, pady=(0,8))

    outer, inner = scrollable(d, bg=C.bg)
    outer.pack(fill="both", expand=True, padx=16, pady=(0,8))

    encabezados = ["Incluir", "Cant.", "Descripción", "Precio unit.",
                  "Código de barras", "Producto del catálogo",
                  "Categoría (si es nuevo)", "Precio de venta (si es nuevo)",
                  "Vencimiento", "Peso", "Fracc.", ""]
    for col, texto in enumerate(encabezados):
        lbl(inner, texto, variante="suave", bg=C.bg).grid(
            row=0, column=col, padx=4, pady=(0,6), sticky="w")

    def _bind_autoformato_fecha(entry):
        """DD/MM/AA a medida que se tipea — mismo comportamiento que
        el vencimiento en Ingreso de Stock."""
        def _formatear(event=None):
            if event is not None and event.keysym in (
                    "Tab", "Shift_L", "Shift_R", "Left", "Right",
                    "Up", "Down", "Control_L", "Control_R"):
                return
            texto = entry.get()
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
        entry.bind("<KeyRelease>", _formatear)

    resumen = {"creados": 0, "sumados": 0, "fallidos": []}
    filas_ui = []

    for i, linea in enumerate(lineas):
        r = i + 1

        var_incluir = tk.BooleanVar(value=True)
        chk_incluir = tk.Checkbutton(inner, variable=var_incluir, bg=C.bg)
        chk_incluir.grid(row=r, column=0, padx=4, pady=3)

        e_cant = tk.Entry(inner, font=F.normal, width=6, relief="solid", bd=1)
        e_cant.insert(0, str(linea["cantidad"]))
        e_cant.grid(row=r, column=1, padx=4, pady=3)

        e_desc = tk.Entry(inner, font=F.normal, width=28, relief="solid", bd=1)
        e_desc.insert(0, linea["descripcion"])
        e_desc.grid(row=r, column=2, padx=4, pady=3)

        e_precio = tk.Entry(inner, font=F.normal, width=10, relief="solid", bd=1)
        e_precio.insert(0, "" if linea["precio_unitario"] is None
                        else str(linea["precio_unitario"]))
        e_precio.grid(row=r, column=3, padx=4, pady=3)

        # Coincidencia automática con umbral alto — si no hay una
        # coincidencia bastante segura, se asume nuevo en vez de
        # arriesgar a mezclar stock con el producto equivocado.
        candidatos = _mejores_coincidencias(
            linea["descripcion"], productos_catalogo, top=1, umbral=0.72)
        match_inicial = candidatos[0] if candidatos else None
        estado_prod = {
            "producto_id": match_inicial["id"] if match_inicial else None,
            "es_nuevo": match_inicial is None,
            "codigo": None,
        }

        e_codigo = tk.Entry(inner, font=F.normal, width=13, relief="solid", bd=1)
        if match_inicial:
            e_codigo.insert(0, match_inicial.get("codigo") or "")
        e_codigo.grid(row=r, column=4, padx=4, pady=3)

        f_prod = tk.Frame(inner, bg=C.bg)
        f_prod.grid(row=r, column=5, padx=4, pady=3, sticky="w")
        lbl_prod = tk.Label(
            f_prod, font=F.normal, bg=C.bg,
            fg=(C.texto if match_inicial else C.exito),
            text=(match_inicial["descripcion"] if match_inicial else "🆕 nuevo"),
            width=22, anchor="w")
        lbl_prod.pack(side="left")

        def _leer_codigo(event=None, estado_prod=estado_prod,
                         lbl_prod=lbl_prod, e_codigo=e_codigo):
            codigo = e_codigo.get().strip()
            if not codigo:
                return
            prod = get_producto_por_codigo(codigo)
            if prod:
                estado_prod["producto_id"] = prod["id"]
                estado_prod["es_nuevo"] = False
                estado_prod["codigo"] = codigo
                lbl_prod.configure(text=prod["descripcion"], fg=C.texto)
            else:
                # No existe ese código todavía — se toma como producto
                # nuevo y ese mismo código se usa al crearlo (en vez
                # del provisorio FACT-xxxx), así ya queda con su
                # código de barras real.
                estado_prod["producto_id"] = None
                estado_prod["es_nuevo"] = True
                estado_prod["codigo"] = codigo
                lbl_prod.configure(
                    text="🆕 nuevo (código no existe)", fg=C.exito)

        e_codigo.bind("<Return>", _leer_codigo)
        e_codigo.bind("<FocusOut>", _leer_codigo)

        def _elegir_producto(estado_prod=estado_prod, lbl_prod=lbl_prod,
                             e_codigo=e_codigo):
            prod = _buscar_producto(d, productos_catalogo)
            if prod:
                estado_prod["producto_id"] = prod["id"]
                estado_prod["es_nuevo"] = False
                lbl_prod.configure(text=prod["descripcion"], fg=C.texto)
                e_codigo.delete(0, "end")
                e_codigo.insert(0, prod.get("codigo") or "")

        b_buscar = tk.Button(f_prod, text="🔍", font=F.normal,
                             command=_elegir_producto, relief="flat",
                             bg=C.superficie, cursor="hand2", padx=6)
        b_buscar.pack(side="left", padx=(4,0))

        def _marcar_nuevo(estado_prod=estado_prod, lbl_prod=lbl_prod):
            estado_prod["producto_id"] = None
            estado_prod["es_nuevo"] = True
            lbl_prod.configure(text="🆕 nuevo", fg=C.exito)

        b_nuevo = tk.Button(f_prod, text="🆕", font=F.normal,
                           command=_marcar_nuevo, relief="flat",
                           bg=C.superficie, cursor="hand2", padx=6)
        b_nuevo.pack(side="left", padx=(2,0))

        combo_cat = ttk.Combobox(inner, font=F.normal, state="readonly",
                                 values=nombres_cat, width=16)
        if nombres_cat:
            combo_cat.current(0)
        combo_cat.grid(row=r, column=6, padx=4, pady=3)

        e_pventa = tk.Entry(inner, font=F.normal, width=10, relief="solid", bd=1)
        e_pventa.grid(row=r, column=7, padx=4, pady=3)
        ultimo_sugerido = {"valor": None}

        def _sugerir_pventa(event=None, e_precio=e_precio,
                            combo_cat=combo_cat, e_pventa=e_pventa,
                            ultimo_sugerido=ultimo_sugerido):
            try:
                costo = float(e_precio.get().strip().replace(",", "."))
            except ValueError:
                return
            if costo <= 0:
                return
            margen = cat_margen.get(combo_cat.get())
            if margen is None:
                from config import cfg
                margen = float(cfg().get("margen_default", 30) or 30)
            from repositorio import redondear_precio
            sugerido = redondear_precio(costo * (1 + float(margen) / 100))
            actual = e_pventa.get().strip()
            # No se pisa un precio que ya se escribió a mano
            if actual in ("", f"{ultimo_sugerido['valor']:.2f}"
                         if ultimo_sugerido["valor"] is not None else ""):
                e_pventa.delete(0, "end")
                e_pventa.insert(0, f"{sugerido:.2f}")
                ultimo_sugerido["valor"] = sugerido

        e_precio.bind("<FocusOut>", _sugerir_pventa, add="+")
        e_precio.bind("<Return>", _sugerir_pventa, add="+")
        combo_cat.bind("<<ComboboxSelected>>", _sugerir_pventa, add="+")
        _sugerir_pventa()

        e_venc = tk.Entry(inner, font=F.normal, width=9, relief="solid", bd=1)
        e_venc.grid(row=r, column=8, padx=4, pady=3)
        _bind_autoformato_fecha(e_venc)

        var_peso = tk.BooleanVar(value=False)
        chk_peso = tk.Checkbutton(inner, variable=var_peso, bg=C.bg)
        chk_peso.grid(row=r, column=9, padx=4, pady=3)

        var_fracc = tk.BooleanVar(value=False)
        chk_fracc = tk.Checkbutton(inner, variable=var_fracc, bg=C.bg)
        chk_fracc.grid(row=r, column=10, padx=4, pady=3)

        f = {
            "var_incluir": var_incluir, "chk_incluir": chk_incluir,
            "e_cant": e_cant, "e_desc": e_desc, "e_precio": e_precio,
            "e_codigo": e_codigo, "estado_prod": estado_prod,
            "combo_cat": combo_cat, "e_pventa": e_pventa, "e_venc": e_venc,
            "var_peso": var_peso, "chk_peso": chk_peso,
            "var_fracc": var_fracc, "chk_fracc": chk_fracc,
            "b_buscar": b_buscar, "b_nuevo": b_nuevo,
            "lbl_prod": lbl_prod, "procesada": False,
        }

        def _confirmar_fila(f=f):
            dec = _leer_decision(f)
            if dec is None:
                return
            if _procesar_decision(dec):
                f["procesada"] = True
                f["var_incluir"].set(False)
                for w in (f["chk_incluir"], f["e_cant"], f["e_desc"],
                         f["e_precio"], f["e_codigo"], f["combo_cat"],
                         f["e_pventa"], f["e_venc"], f["chk_peso"],
                         f["chk_fracc"], f["b_buscar"], f["b_nuevo"],
                         f["b_confirmar"]):
                    try:
                        w.configure(state="disabled")
                    except tk.TclError:
                        pass
                f["lbl_prod"].configure(
                    text="✔ cargado — " + f["lbl_prod"].cget("text"),
                    fg=C.exito)

        b_confirmar = tk.Button(inner, text="✓", font=F.normal,
                               command=_confirmar_fila, relief="flat",
                               bg=C.exito, fg="white", cursor="hand2",
                               padx=8)
        b_confirmar.grid(row=r, column=11, padx=4, pady=3)
        f["b_confirmar"] = b_confirmar

        filas_ui.append(f)

    def _leer_decision(f):
        """Valida los datos de UNA fila y devuelve el dict listo para
        procesar, o None si algo está mal (y ya avisó con un cartel)."""
        descripcion = f["e_desc"].get().strip()
        try:
            cantidad = float(f["e_cant"].get().replace(",", "."))
            if cantidad <= 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning(
                "Atención",
                f"Cantidad inválida en: \"{descripcion or '(sin descripción)'}\"",
                parent=d)
            return None
        if not descripcion:
            messagebox.showwarning(
                "Atención", "Falta la descripción de un renglón.", parent=d)
            return None
        try:
            precio_txt = f["e_precio"].get().strip()
            precio = float(precio_txt.replace(",", ".")) if precio_txt else 0.0
        except ValueError:
            messagebox.showwarning(
                "Atención", f"Precio inválido en: \"{descripcion}\"", parent=d)
            return None
        if (f["estado_prod"]["producto_id"] is None
                and not f["estado_prod"]["es_nuevo"]):
            messagebox.showwarning(
                "Atención",
                f"Falta indicar el producto de: \"{descripcion}\"", parent=d)
            return None

        vence_txt = f["e_venc"].get().strip()
        vencimiento = None
        if vence_txt:
            vencimiento = parsear_fecha(vence_txt)
            if not vencimiento:
                messagebox.showwarning(
                    "Atención",
                    f"No entiendo el vencimiento de \"{descripcion}\": "
                    f"\"{vence_txt}\".\n\nUsá ddmmaa (ej: 150327), "
                    f"dd/mm/aa, o dejalo vacío.", parent=d)
                return None

        categoria_id = (cat_map.get(f["combo_cat"].get())
                       if f["combo_cat"].get() else None)

        precio_venta = None
        pventa_txt = f["e_pventa"].get().strip()
        if pventa_txt:
            try:
                precio_venta = float(pventa_txt.replace(",", "."))
            except ValueError:
                messagebox.showwarning(
                    "Atención",
                    f"Precio de venta inválido en: \"{descripcion}\"", parent=d)
                return None

        return {
            "cantidad": cantidad, "descripcion": descripcion,
            "precio_unitario": precio,
            "precio_venta": precio_venta,
            "producto_id": f["estado_prod"]["producto_id"],
            "es_nuevo": f["estado_prod"]["es_nuevo"],
            "codigo": f["estado_prod"].get("codigo"),
            "vencimiento": vencimiento, "categoria_id": categoria_id,
            "vendido_por_peso": f["var_peso"].get(),
            "fraccionable": f["var_fracc"].get(),
        }

    def _procesar_decision(dec):
        """Crea el producto si hace falta y registra el lote. Devuelve
        True si salió bien; si falla, avisa en el log y en resumen
        ['fallidos'] sin cortar el resto de la importación."""
        import uuid
        try:
            if dec["es_nuevo"]:
                if dec.get("precio_venta"):
                    precio_venta = dec["precio_venta"]
                else:
                    margen = cat_margen.get(
                        next((n for n, cid in cat_map.items()
                             if cid == dec.get("categoria_id")), None))
                    if margen is None:
                        from config import cfg
                        margen = float(cfg().get("margen_default", 30) or 30)
                    from repositorio import redondear_precio
                    precio_venta = redondear_precio(
                        dec["precio_unitario"] * (1 + float(margen) / 100))
                # Si se escaneó/tipeó un código que no existe en la
                # base, se usa ese código real en vez del provisorio
                # FACT-xxxx.
                codigo = dec.get("codigo") or \
                    f"FACT-{uuid.uuid4().hex[:8].upper()}"
                pid = crear_producto(
                    codigo=codigo, descripcion=dec["descripcion"],
                    categoria_id=dec.get("categoria_id"),
                    precio_base=precio_venta, costo=dec["precio_unitario"],
                    vendido_por_peso=dec["vendido_por_peso"],
                    fraccionable=dec["fraccionable"])
            else:
                pid = dec["producto_id"]

            nuevo_precio_venta = None
            if not dec["es_nuevo"]:
                info = evaluar_cambio_costo(pid, dec["precio_unitario"])
                if info["direccion"] == "subio":
                    nuevo_precio_venta = info["precio_sugerido"]
                elif (info["direccion"] == "bajo"
                      and round(info["precio_sugerido"], 2) != round(info["precio_actual"], 2)):
                    if messagebox.askyesno(
                            "El costo bajó",
                            f"{dec['descripcion']}: el costo bajó de "
                            f"$ {info['costo_anterior']:,.2f} a "
                            f"$ {info['costo_nuevo']:,.2f}.\n\n"
                            f"Precio de venta actual: $ {info['precio_actual']:,.2f}\n"
                            f"Precio sugerido (mismo margen): "
                            f"$ {info['precio_sugerido']:,.2f}\n\n"
                            f"¿Actualizar el precio de venta?",
                            parent=d):
                        nuevo_precio_venta = info["precio_sugerido"]

            registrar_lote(pid, proveedor_id, dec["cantidad"],
                          dec["precio_unitario"], dec.get("vencimiento"),
                          "Importado desde foto de factura (OCR)",
                          nuevo_precio_venta=nuevo_precio_venta)
            if dec["es_nuevo"]:
                resumen["creados"] += 1
            else:
                resumen["sumados"] += 1
            return True
        except Exception as e:
            resumen["fallidos"].append(dec["descripcion"])
            logging.warning(
                f"No se pudo cargar \"{dec['descripcion']}\" desde la "
                f"factura: {e}")
            return False

    pie = tk.Frame(d, bg=C.bg)
    pie.pack(fill="x", padx=16, pady=(0,14))

    def _cerrar_con_resumen():
        d.destroy()
        for metodo in ("_refrescar_lotes", "_refrescar_critico"):
            if hasattr(parent, metodo):
                try:
                    getattr(parent, metodo)()
                except Exception as e:
                    # La factura se importo bien, pero la pantalla queda
                    # mostrando datos viejos.
                    logging.warning(f"Factura importada pero {metodo}() fallo: "
                                    f"{e}. Refresca la pestana a mano.")
        fallidos = resumen["fallidos"]
        messagebox.showinfo(
            "Importar factura",
            f"Listo — {resumen['sumados']} producto(s) sumaron stock y "
            f"{resumen['creados']} producto(s) nuevo(s) se crearon."
            + (f"\n\n⚠ {len(fallidos)} línea(s) no se pudieron cargar:\n"
               + "\n".join(f"• {desc}" for desc in fallidos)
               if fallidos else ""),
            parent=parent)

    def _confirmar_resto():
        pendientes = [f for f in filas_ui
                     if not f["procesada"] and f["var_incluir"].get()]
        if not pendientes:
            if resumen["creados"] or resumen["sumados"]:
                _cerrar_con_resumen()
            else:
                messagebox.showinfo(
                    "Importar factura",
                    "No quedó ningún renglón tildado para cargar.", parent=d)
            return

        decisiones = []
        for f in pendientes:
            dec = _leer_decision(f)
            if dec is None:
                return   # ya avisó cuál línea está mal
            decisiones.append((f, dec))

        for f, dec in decisiones:
            _procesar_decision(dec)

        _cerrar_con_resumen()

    btn(pie, "Cancelar", variante="neutro", comando=d.destroy).pack(
        side="right", padx=(6,0))
    btn(pie, "Confirmar todo lo que sigue tildado", variante="primario",
        comando=_confirmar_resto).pack(side="right")


def _mostrar_resumen(parent, decisiones, proveedor_id):
    if not decisiones:
        messagebox.showinfo(
            "Importar factura",
            "No quedó ninguna línea para cargar (se descartaron todas).",
            parent=parent)
        return

    nuevos = [d for d in decisiones if d["es_nuevo"]]
    existentes = [d for d in decisiones if not d["es_nuevo"]]

    d = tk.Toplevel(parent)
    d.title("Confirmar importación")
    _centrar(d, 480, 560)
    d.configure(bg=C.superficie)
    d.resizable(True, True)
    d.grab_set()

    lbl(d, "Confirmar importación", variante="titulo",
        bg=C.superficie).pack(pady=(20,8), padx=20, anchor="w")
    lbl(d, f"• {len(existentes)} línea(s) van a sumar stock a productos "
          f"que ya tenés\n"
          f"• {len(nuevos)} producto(s) nuevo(s) se van a crear\n"
          f"(categoría y vencimiento ya se cargaron línea por línea)",
        variante="suave", bg=C.superficie, justify="left").pack(
        padx=20, anchor="w")

    f_lista = card(d)
    f_lista.pack(fill="both", expand=True, padx=20, pady=(14,14))
    txt = tk.Text(f_lista, font=F.normal, bg=C.superficie, fg=C.texto,
                  relief="flat", wrap="word", height=14)
    txt.pack(fill="both", expand=True, padx=8, pady=8)
    for dec in decisiones:
        marca = "🆕 NUEVO" if dec["es_nuevo"] else "✓ existente"
        venc = f"  vto:{dec['vencimiento']}" if dec.get("vencimiento") else ""
        txt.insert("end",
            f"{marca} — {dec['descripcion']}  x{dec['cantidad']:.0f}  "
            f"$ {dec['precio_unitario']:,.2f}{venc}\n")
    txt.configure(state="disabled")

    def _confirmar():
        import uuid
        creados, sumados = 0, 0

        for dec in decisiones:
            if dec["es_nuevo"]:
                precio_venta = round(dec["precio_unitario"] * 1.30, 2)
                # La factura no suele traer el código de barras interno
                # del producto — se genera uno provisorio único (el
                # campo es obligatorio y único en la base). Se puede
                # cambiar después desde Catálogo > Editar si aparece
                # el código real.
                codigo_provisorio = f"FACT-{uuid.uuid4().hex[:8].upper()}"
                pid = crear_producto(
                    codigo=codigo_provisorio, descripcion=dec["descripcion"],
                    categoria_id=dec.get("categoria_id"), precio_base=precio_venta,
                    costo=dec["precio_unitario"])
                creados += 1
            else:
                pid = dec["producto_id"]
                sumados += 1

            nuevo_precio_venta = None
            if not dec["es_nuevo"]:
                info = evaluar_cambio_costo(pid, dec["precio_unitario"])
                if info["direccion"] == "subio":
                    nuevo_precio_venta = info["precio_sugerido"]
                elif (info["direccion"] == "bajo"
                      and round(info["precio_sugerido"], 2) != round(info["precio_actual"], 2)):
                    if messagebox.askyesno(
                            "El costo bajó",
                            f"{dec['descripcion']}: el costo bajó de "
                            f"$ {info['costo_anterior']:,.2f} a "
                            f"$ {info['costo_nuevo']:,.2f}.\n\n"
                            f"Precio de venta actual: $ {info['precio_actual']:,.2f}\n"
                            f"Precio sugerido (mismo margen): "
                            f"$ {info['precio_sugerido']:,.2f}\n\n"
                            f"¿Actualizar el precio de venta?",
                            parent=d):
                        nuevo_precio_venta = info["precio_sugerido"]

            registrar_lote(pid, proveedor_id, dec["cantidad"],
                          dec["precio_unitario"], dec.get("vencimiento"),
                          "Importado desde foto de factura (OCR)",
                          nuevo_precio_venta=nuevo_precio_venta)

        d.destroy()
        for metodo in ("_refrescar_lotes", "_refrescar_critico"):
            if hasattr(parent, metodo):
                try:
                    getattr(parent, metodo)()
                except Exception as e:
                    # La factura se importo bien, pero la pantalla queda
                    # mostrando datos viejos.
                    logging.warning(f"Factura importada pero {metodo}() fallo: "
                                    f"{e}. Refresca la pestana a mano.")
        messagebox.showinfo(
            "Listo",
            f"Importación completa: {sumados} producto(s) con stock sumado, "
            f"{creados} producto(s) nuevo(s) creados.\n\n"
            "Los productos nuevos quedaron con un precio de venta "
            "estimado (costo +30%) y un código provisorio (FACT-XXXX) "
            "— revisalos en Catálogo y poné el código de barras real "
            "si lo tienen.",
            parent=parent)

    btn(d, "✅  Confirmar y cargar todo", variante="exito",
        comando=_confirmar).pack(padx=20, pady=(0,8), fill="x")
    btn(d, "Cancelar (no cargar nada)", variante="neutro",
        comando=d.destroy).pack(padx=20, pady=(0,20), fill="x")

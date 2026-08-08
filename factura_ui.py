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

from styles import C, F, btn, lbl, card
from repositorio import (get_productos, get_proveedores, crear_proveedor,
                         crear_producto, registrar_lote, get_categorias,
                         evaluar_cambio_costo)


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
    proveedor_id = _pedir_proveedor(parent)
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
            resultado["lineas"] = factura_ocr.extraer_lineas_factura(ruta)
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
            _revisar_lineas(parent, lineas, proveedor_id)
        try:
            d.after(0, _seguir)
        except tk.TclError as e:
            logging.debug(f"Dialogo cerrado antes de procesar la factura: {e}")

    threading.Thread(target=_trabajar, daemon=True).start()


def _pedir_proveedor(parent):
    """Devuelve el id del proveedor elegido, None si no corresponde
    a ninguno cargado, o False si se canceló todo el importado."""
    proveedores = get_proveedores()
    mapa = {p["nombre"]: p["id"] for p in proveedores}

    d = tk.Toplevel(parent)
    d.title("¿De qué proveedor es esta factura?")
    _centrar(d, 380, 190)
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

    def _nuevo():
        nombre = simpledialog.askstring(
            "Nuevo proveedor", "Nombre del proveedor:", parent=d)
        if nombre and nombre.strip():
            pid = crear_proveedor(nombre.strip())
            mapa[nombre.strip()] = pid
            combo["values"] = list(mapa.keys())
            combo.set(nombre.strip())

    btn(f, "+ Nuevo", variante="neutro", comando=_nuevo).pack(side="left", padx=(6,0))

    resultado = {"id": False}

    def _continuar():
        resultado["id"] = mapa.get(combo.get())
        d.destroy()

    def _cancelar():
        resultado["id"] = False
        d.destroy()

    btn(d, "Continuar", variante="primario", comando=_continuar).pack(
        pady=(20,6), padx=20, fill="x")
    btn(d, "Cancelar", variante="neutro", comando=_cancelar).pack(
        padx=20, fill="x")

    d.wait_window()
    return resultado["id"]


def _revisar_lineas(parent, lineas, proveedor_id):
    """Wizard: una línea a la vez. Al terminar todas, muestra un
    resumen y recién ahí escribe en la base."""
    productos_catalogo = get_productos(solo_activos=True)
    decisiones = []   # se va llenando: dict por línea ya resuelta

    d = tk.Toplevel(parent)
    d.title("Revisar factura")
    _centrar(d, 620, 560)
    d.configure(bg=C.bg)
    d.resizable(False, False)
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

        bot = tk.Frame(d, bg=C.bg)
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

            decisiones.append({
                "cantidad": cantidad,
                "descripcion": descripcion,
                "precio_unitario": precio,
                "producto_id": elegido["producto_id"],
                "es_nuevo": elegido["es_nuevo"],
            })
            estado["i"] += 1
            _mostrar_linea()

        btn(bot, "Descartar esta línea", variante="neutro",
            comando=_descartar).pack(side="left")
        btn(bot, "Siguiente →", variante="primario",
            comando=_siguiente).pack(side="right")

    _mostrar_linea()


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
    _centrar(d, 480, 460)
    d.configure(bg=C.superficie)
    d.resizable(False, False)
    d.grab_set()

    lbl(d, "Confirmar importación", variante="titulo",
        bg=C.superficie).pack(pady=(20,8), padx=20, anchor="w")
    lbl(d, f"• {len(existentes)} línea(s) van a sumar stock a productos "
          f"que ya tenés\n"
          f"• {len(nuevos)} producto(s) nuevo(s) se van a crear",
        variante="suave", bg=C.superficie, justify="left").pack(
        padx=20, anchor="w")

    f_lista = card(d)
    f_lista.pack(fill="both", expand=True, padx=20, pady=(14,8))
    txt = tk.Text(f_lista, font=F.normal, bg=C.superficie, fg=C.texto,
                  relief="flat", wrap="word", height=10)
    txt.pack(fill="both", expand=True, padx=8, pady=8)
    for dec in decisiones:
        marca = "🆕 NUEVO" if dec["es_nuevo"] else "✓ existente"
        txt.insert("end",
            f"{marca} — {dec['descripcion']}  x{dec['cantidad']:.0f}  "
            f"$ {dec['precio_unitario']:,.2f}\n")
    txt.configure(state="disabled")

    # Categoría para los productos NUEVOS de esta factura — antes se
    # asignaba en silencio la primera categoría de la base (cats[0]),
    # sin importar qué fueran los productos. Ahora lo elige el usuario;
    # una factura suele ser de un solo rubro, así que se aplica la
    # misma categoría a todos los nuevos de esta tanda.
    combo_cat = None
    cats = get_categorias()
    cat_map = {c["nombre"]: c["id"] for c in cats}
    if nuevos and cat_map:
        lbl(d, "Categoría para los productos nuevos:", variante="suave",
            bg=C.superficie).pack(padx=20, anchor="w")
        combo_cat = ttk.Combobox(d, font=F.normal, state="readonly",
                                 values=list(cat_map.keys()))
        combo_cat.pack(fill="x", padx=20, pady=(2,10), ipady=4)
        combo_cat.current(0)

    def _confirmar():
        import uuid
        creados, sumados = 0, 0
        cat_default = cat_map.get(combo_cat.get()) if combo_cat else None

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
                    categoria_id=cat_default, precio_base=precio_venta,
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
                          dec["precio_unitario"], None,
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

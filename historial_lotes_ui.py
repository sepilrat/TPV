"""
historial_lotes_ui.py — Historico completo de ingresos de mercaderia.

La lista de "Ultimos ingresos" de la pantalla de Stock muestra 50 y sin
filtros: sirve para ver lo del dia, no para buscar cuando entro algo hace
tres meses ni para reconstruir que se le compro a un proveedor.
"""

import datetime
import tkinter as tk
from tkinter import ttk, messagebox

from styles import C, F, btn, lbl
from repositorio import (buscar_lotes, resumen_lotes, get_proveedores,
                         actualizar_vencimiento_lote)


def dialogo_historial_lotes(parent):
    d = tk.Toplevel(parent)
    d.title("Historial de ingresos")
    d.configure(bg=C.superficie)
    w, h = 1100, 620
    sw, sh = d.winfo_screenwidth(), d.winfo_screenheight()
    d.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 2)}")

    lbl(d, "Historial de ingresos", variante="titulo", bg=C.superficie).pack(
        anchor="w", padx=20, pady=(16, 2))
    lbl(d, "Todos los lotes cargados. Doble clic para corregir el vencimiento.",
        variante="suave", bg=C.superficie).pack(anchor="w", padx=20)

    # ── Filtros ───────────────────────────────────────────────────────────
    barra = tk.Frame(d, bg=C.superficie)
    barra.pack(fill="x", padx=20, pady=10)

    lbl(barra, "Buscar:", variante="suave", bg=C.superficie).pack(side="left")
    v_texto = tk.StringVar()
    e = tk.Entry(barra, textvariable=v_texto, width=26, font=F.normal,
                 bg=C.bg, fg=C.texto, relief="solid", bd=1)
    e.pack(side="left", padx=6)

    lbl(barra, "Desde:", variante="suave", bg=C.superficie).pack(side="left", padx=(10, 3))
    v_desde = tk.StringVar()
    tk.Entry(barra, textvariable=v_desde, width=11, font=F.normal, justify="center",
             bg=C.bg, fg=C.texto, relief="solid", bd=1).pack(side="left")

    lbl(barra, "Hasta:", variante="suave", bg=C.superficie).pack(side="left", padx=(8, 3))
    v_hasta = tk.StringVar()
    tk.Entry(barra, textvariable=v_hasta, width=11, font=F.normal, justify="center",
             bg=C.bg, fg=C.texto, relief="solid", bd=1).pack(side="left")

    lbl(barra, "Proveedor:", variante="suave", bg=C.superficie).pack(side="left", padx=(10, 3))
    provs = [{"id": None, "nombre": "Todos"}] + list(get_proveedores())
    v_prov = tk.StringVar(value="Todos")
    ttk.Combobox(barra, textvariable=v_prov, width=18, state="readonly",
                 values=[p["nombre"] for p in provs]).pack(side="left")

    v_stock = tk.BooleanVar(value=False)
    tk.Checkbutton(barra, text="Solo con stock", variable=v_stock, bg=C.superficie,
                   fg=C.texto, font=F.normal, activebackground=C.superficie,
                   selectcolor=C.superficie).pack(side="left", padx=10)

    # ── Tabla ─────────────────────────────────────────────────────────────
    cont = tk.Frame(d, bg=C.superficie)
    cont.pack(fill="both", expand=True, padx=20)

    cols = ("fecha", "producto", "tipo", "cant", "resta", "costo",
            "total", "prov", "vence")
    tv = ttk.Treeview(cont, columns=cols, show="headings")
    for c_, t_, w_, a_ in (("fecha", "Fecha", 90, "w"),
                           ("producto", "Producto", 230, "w"),
                           ("tipo", "Tipo", 110, "w"),
                           ("cant", "Cantidad", 80, "e"),
                           ("resta", "Queda", 80, "e"),
                           ("costo", "Costo unit.", 100, "e"),
                           ("total", "Total", 110, "e"),
                           ("prov", "Proveedor", 130, "w"),
                           ("vence", "Vence", 95, "w")):
        tv.heading(c_, text=t_)
        tv.column(c_, width=w_, anchor=a_)
    tv.tag_configure("agotado", foreground=C.texto_suave)
    tv.tag_configure("ajuste", background=C.acento)
    # Costo del lote != costo del producto: la rentabilidad usa el del
    # lote, asi que el descuadre hace que el informe mienta.
    tv.tag_configure("costo_raro", background=C.err_flash)

    sb = ttk.Scrollbar(cont, orient="vertical", command=tv.yview)
    tv.configure(yscrollcommand=sb.set)
    tv.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")

    lbl_pie = tk.Label(d, text="", font=F.normal, bg=C.acento, fg=C.texto,
                       anchor="w", padx=14, pady=8)
    lbl_pie.pack(fill="x", padx=20, pady=(8, 0))

    filas = []

    def _buscar(*_a):
        tv.delete(*tv.get_children())
        filas.clear()
        prov_id = provs[[p["nombre"] for p in provs].index(v_prov.get())]["id"]
        try:
            filas.extend(buscar_lotes(
                v_texto.get(), desde=v_desde.get().strip() or None,
                hasta=v_hasta.get().strip() or None, proveedor_id=prov_id,
                solo_con_stock=v_stock.get()))
        except Exception as exc:
            lbl_pie.config(text=f"Error en la busqueda: {exc}")
            return

        for i, l in enumerate(filas):
            tipo = l.get("tipo") or "ingreso"
            tipo_txt = (f"Ajuste ({l['motivo_ajuste']})"
                        if tipo == "ajuste" and l.get("motivo_ajuste")
                        else tipo.capitalize())
            tags = []
            if tipo == "ajuste":
                tags.append("ajuste")
            elif (l["cantidad_restante"] or 0) <= 0:
                tags.append("agotado")
            # El costo del lote no coincide con el del producto: la
            # rentabilidad usa el del lote y el informe queda mintiendo.
            _cu = float(l.get("costo_unitario") or 0)
            _cp = float(l.get("costo_ultimo") or 0)
            if _cu and _cp and abs(_cu - _cp) > 0.01:
                tags.append("costo_raro")
            tv.insert("", "end", iid=str(i), tags=tuple(tags), values=(
                (l["fecha_ingreso"] or "")[:10],
                l["descripcion"][:40],
                tipo_txt,
                f"{l['cantidad']:g}",
                f"{l['cantidad_restante']:g}",
                f"$ {l['costo_unitario']:,.2f}",
                f"$ {(l['cantidad'] or 0) * (l['costo_unitario'] or 0):,.2f}",
                l["proveedor"] or "—",
                l["fecha_vencimiento"] or "—"))

        r = resumen_lotes(filas)
        lbl_pie.config(
            text=(f"{r['cantidad']} lote(s)   ·   {r['unidades']:g} unidades "
                  f"ingresadas   ·   invertido $ {r['invertido']:,.2f}   ·   "
                  f"todavia en stock $ {r['en_stock']:,.2f}"))

    def _editar_vto(_ev=None):
        sel = tv.selection()
        if not sel:
            return
        lote = filas[int(sel[0])]
        actual = lote["fecha_vencimiento"] or ""
        try:
            ini = (datetime.datetime.strptime(actual, "%Y-%m-%d").strftime("%d/%m/%Y")
                   if actual else "")
        except ValueError:
            ini = actual

        top = tk.Toplevel(d)
        top.title("Corregir vencimiento")
        top.configure(bg=C.superficie)
        top.grab_set()
        top.geometry("400x210")
        lbl(top, lote["descripcion"][:44], variante="titulo",
            bg=C.superficie).pack(anchor="w", padx=18, pady=(16, 2))
        lbl(top, f"Ingresado el {(lote['fecha_ingreso'] or '')[:10]}   ·   "
                 f"vence: {actual or 'sin vencimiento'}",
            variante="suave", bg=C.superficie).pack(anchor="w", padx=18)
        lbl(top, "Nueva fecha (DD/MM/AAAA — vacío = sin vencimiento)",
            variante="suave", bg=C.superficie).pack(anchor="w", padx=18, pady=(12, 4))
        var = tk.StringVar(value=ini)
        ent = tk.Entry(top, textvariable=var, font=F.normal, justify="center",
                       bg=C.bg, fg=C.texto, relief="solid", bd=1)
        ent.pack(fill="x", padx=18, ipady=5)
        ent.focus_set()
        ent.select_range(0, "end")

        def guardar(_e=None):
            try:
                actualizar_vencimiento_lote(lote["id"], var.get())
            except ValueError as exc:
                messagebox.showwarning("Vencimiento", str(exc), parent=top)
                return
            top.destroy()
            _buscar()

        ent.bind("<Return>", guardar)
        top.bind("<Escape>", lambda e: top.destroy())
        fb = tk.Frame(top, bg=C.superficie)
        fb.pack(pady=16)
        btn(fb, "Guardar", variante="exito", comando=guardar).pack(side="left", padx=4)
        btn(fb, "Cancelar", variante="neutro", comando=top.destroy).pack(side="left", padx=4)

    tv.bind("<Double-1>", _editar_vto)
    for var in (v_texto, v_desde, v_hasta, v_prov):
        var.trace_add("write", _buscar)
    v_stock.trace_add("write", _buscar)

    pie = tk.Frame(d, bg=C.superficie)
    pie.pack(side="bottom", fill="x", pady=(8, 14))
    btn(pie, "Ultimos 30 dias", variante="neutro",
        comando=lambda: v_desde.set(
            (datetime.date.today() - datetime.timedelta(days=30)).isoformat())
        ).pack(side="left", padx=(20, 6))
    btn(pie, "💲 Corregir costo", variante="primario",
        comando=lambda: corregir_costo_dialogo(d, tv, filas, _buscar)).pack(
        side="left", padx=6)
    btn(pie, "Ver todo", variante="neutro",
        comando=lambda: (v_desde.set(""), v_hasta.set(""), v_texto.set(""),
                         v_prov.set("Todos"))).pack(side="left")
    btn(pie, "Cerrar", variante="neutro", comando=d.destroy).pack(side="right", padx=20)

    _buscar()
    e.focus_set()


# ══════════════════════════════════════════════════════════════════════════
# Lotes de un producto puntual
# ══════════════════════════════════════════════════════════════════════════

def dialogo_lotes_producto(parent, producto_id: int):
    """Los lotes de UN producto, con el vencimiento editable en el momento.

    Es el atajo que falta cuando llega una alerta de vencimiento rara: uno
    va al producto, no al historial general de ingresos.
    """
    from repositorio import get_producto_completo

    prod = get_producto_completo(producto_id)
    if not prod:
        return

    d = tk.Toplevel(parent)
    d.title(f"Vencimientos — {prod['descripcion']}")
    d.configure(bg=C.superficie)
    d.grab_set()
    w, h = 760, 460
    sw, sh = d.winfo_screenwidth(), d.winfo_screenheight()
    d.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 2)}")

    lbl(d, prod["descripcion"], variante="titulo", bg=C.superficie).pack(
        anchor="w", padx=20, pady=(16, 2))
    lbl(d, "Doble clic en un lote para corregirle el vencimiento",
        variante="suave", bg=C.superficie).pack(anchor="w", padx=20)

    cols = ("fecha", "cant", "resta", "costo", "prov", "vence", "estado")
    tv = ttk.Treeview(d, columns=cols, show="headings", height=12)
    for c_, t_, w_, a_ in (("fecha", "Ingresado", 95, "w"),
                           ("cant", "Cantidad", 80, "e"),
                           ("resta", "Queda", 80, "e"),
                           ("costo", "Costo unit.", 100, "e"),
                           ("prov", "Proveedor", 130, "w"),
                           ("vence", "Vence", 100, "w"),
                           ("estado", "Estado", 130, "w")):
        tv.heading(c_, text=t_)
        tv.column(c_, width=w_, anchor=a_)
    tv.tag_configure("agotado", foreground=C.texto_suave)
    tv.tag_configure("vencido", background=C.err_flash, foreground=C.peligro)
    tv.tag_configure("porvencer", background=C.acento)
    tv.pack(fill="both", expand=True, padx=20, pady=8)

    filas = []

    def _cargar():
        tv.delete(*tv.get_children())
        filas.clear()
        filas.extend(buscar_lotes(proveedor_id=None, limit=500))
        propios = [l for l in filas if l["producto_id"] == producto_id]
        filas.clear()
        filas.extend(propios)
        hoy = datetime.date.today()
        for i, l in enumerate(propios):
            estado, tag = "", ""
            if (l["cantidad_restante"] or 0) <= 0:
                estado, tag = "agotado", "agotado"
            elif l["fecha_vencimiento"]:
                try:
                    v = datetime.datetime.strptime(
                        l["fecha_vencimiento"], "%Y-%m-%d").date()
                    dias = (v - hoy).days
                    if dias < 0:
                        estado, tag = f"VENCIDO hace {-dias} d", "vencido"
                    elif dias == 0:
                        estado, tag = "vence HOY", "vencido"
                    elif dias <= 15:
                        estado, tag = f"vence en {dias} d", "porvencer"
                    else:
                        estado = f"vence en {dias} d"
                except ValueError:
                    estado = "fecha ilegible"
            else:
                estado = "sin vencimiento"
            # Costo igual al precio de venta: casi siempre es que se
            # cargo el precio en el campo del costo.
            _pv = float(l.get("precio_base") or 0)
            _cu = float(l.get("costo_unitario") or 0)
            if _pv and _cu and abs(_pv - _cu) < 0.01:
                tag = "costo_raro"
            tv.insert("", "end", iid=str(i), tags=(tag,) if tag else (), values=(
                (l["fecha_ingreso"] or "")[:10],
                f"{l['cantidad']:g}", f"{l['cantidad_restante']:g}",
                f"$ {l['costo_unitario']:,.2f}", l["proveedor"] or "—",
                l["fecha_vencimiento"] or "—", estado))

    def _editar(_ev=None):
        sel = tv.selection()
        if not sel:
            messagebox.showinfo("Vencimiento", "Elegí un lote de la lista.",
                                parent=d)
            return
        lote = filas[int(sel[0])]
        actual = lote["fecha_vencimiento"] or ""
        try:
            ini = (datetime.datetime.strptime(actual, "%Y-%m-%d").strftime("%d/%m/%Y")
                   if actual else "")
        except ValueError:
            ini = actual

        top = tk.Toplevel(d)
        top.title("Corregir vencimiento")
        top.configure(bg=C.superficie)
        top.grab_set()
        top.geometry("400x200")
        lbl(top, f"Lote ingresado el {(lote['fecha_ingreso'] or '')[:10]}",
            variante="titulo", bg=C.superficie).pack(anchor="w", padx=18,
                                                     pady=(16, 2))
        lbl(top, f"Vence: {actual or 'sin vencimiento'}", variante="suave",
            bg=C.superficie).pack(anchor="w", padx=18)
        lbl(top, "Nueva fecha (DD/MM/AAAA — vacío = sin vencimiento)",
            variante="suave", bg=C.superficie).pack(anchor="w", padx=18,
                                                    pady=(12, 4))
        var = tk.StringVar(value=ini)
        ent = tk.Entry(top, textvariable=var, font=F.normal, justify="center",
                       bg=C.bg, fg=C.texto, relief="solid", bd=1)
        ent.pack(fill="x", padx=18, ipady=5)
        ent.focus_set()
        ent.select_range(0, "end")

        def guardar(_e=None):
            try:
                actualizar_vencimiento_lote(lote["id"], var.get())
            except ValueError as exc:
                messagebox.showwarning("Vencimiento", str(exc), parent=top)
                return
            top.destroy()
            _cargar()

        ent.bind("<Return>", guardar)
        top.bind("<Escape>", lambda e: top.destroy())
        fb = tk.Frame(top, bg=C.superficie)
        fb.pack(pady=16)
        btn(fb, "Guardar", variante="exito", comando=guardar).pack(side="left", padx=4)
        btn(fb, "Cancelar", variante="neutro", comando=top.destroy).pack(side="left", padx=4)

    # Los lotes con costo == precio de venta se resaltan: casi siempre
    # es que se cargo el precio en el campo del costo.
    tv.tag_configure("costo_raro", background=C.err_flash)

    tv.bind("<Double-1>", _editar)

    _corregir_costo = lambda ev=None: corregir_costo_dialogo(d, tv, filas, _cargar)

    pie = tk.Frame(d, bg=C.superficie)
    pie.pack(side="bottom", fill="x", pady=(0, 14))
    btn(pie, "Corregir vencimiento", variante="exito",
        comando=_editar).pack(side="left", padx=(20, 6))
    btn(pie, "💲 Corregir costo", variante="primario",
        comando=_corregir_costo).pack(side="left", padx=6)
    btn(pie, "Cerrar", variante="neutro", comando=d.destroy).pack(side="right", padx=20)

    _cargar()
    parent.wait_window(d)


def corregir_costo_dialogo(d, tv, filas, al_terminar=None):
    """Corrige el costo de un lote mal cargado.

    Poner el precio de venta en el campo "costo unitario" al ingresar
    stock es facil de hacer y dificil de ver: el producto sigue
    mostrando su costo correcto, pero la rentabilidad de todo lo
    vendido de ese lote sale en cero.
    """
    from repositorio import corregir_costo_lote
    from fiado_ui import pedir_autorizacion
    sel = tv.selection()
    if not sel:
        messagebox.showinfo("Costo", "Elegí un lote de la lista.", parent=d)
        return
    lote = filas[int(sel[0])]
    actual = float(lote.get("costo_unitario") or 0)
    precio = float(lote.get("precio_base") or 0)

    top = tk.Toplevel(d)
    top.title("Corregir costo del lote")
    top.configure(bg=C.superficie)
    top.grab_set()
    top.geometry("470x340")

    lbl(top, lote.get("descripcion", "")[:44], variante="titulo",
        bg=C.superficie).pack(anchor="w", padx=18, pady=(16, 2))
    lbl(top, f"Lote del {(lote.get('fecha_ingreso') or '')[:10]}   ·   "
             f"{lote.get('cantidad', 0):g} unidad(es)",
        variante="suave", bg=C.superficie).pack(anchor="w", padx=18)

    info = tk.Frame(top, bg=C.acento, padx=14, pady=10)
    info.pack(fill="x", padx=18, pady=(12, 8))
    tk.Label(info, text=f"Costo cargado: $ {actual:,.2f}", bg=C.acento,
             fg=C.texto, font=F.normal, anchor="w").pack(anchor="w")
    tk.Label(info, text=f"Precio de venta: $ {precio:,.2f}", bg=C.acento,
             fg=C.texto, font=F.normal, anchor="w").pack(anchor="w")
    if precio and abs(actual - precio) < 0.01:
        tk.Label(info, text="⚠  El costo es igual al precio de venta: "
                            "casi seguro se cargó el precio por error.",
                 bg=C.acento, fg=C.peligro, font=F.pequeña, anchor="w",
                 wraplength=400, justify="left").pack(anchor="w",
                                                      pady=(6, 0))

    lbl(top, "Costo real por unidad", variante="suave",
        bg=C.superficie).pack(anchor="w", padx=18, pady=(6, 2))
    v_costo = tk.StringVar(value=f"{actual:.2f}")
    e = tk.Entry(top, textvariable=v_costo, font=F.total, justify="center",
                 bg=C.bg, fg=C.texto, relief="solid", bd=1)
    e.pack(fill="x", padx=18, ipady=6)
    e.focus_set()
    e.select_range(0, "end")

    lbl_m = tk.Label(top, text="", bg=C.superficie, fg=C.texto_suave,
                     font=F.pequeña, anchor="w")
    lbl_m.pack(fill="x", padx=18, pady=(6, 0))

    def _margen(*_a):
        try:
            c = float(v_costo.get().replace(",", "."))
        except ValueError:
            lbl_m.config(text="")
            return
        if c > 0 and precio:
            lbl_m.config(text=f"Margen con ese costo: "
                              f"{(precio - c) / c * 100:.1f}%",
                         fg=C.peligro if precio < c else C.texto_suave)
    v_costo.trace_add("write", _margen)
    _margen()

    def guardar(_e=None):
        try:
            nuevo = float(v_costo.get().replace(",", "."))
        except ValueError:
            messagebox.showwarning("Costo", "No es un número.", parent=top)
            return
        resp = pedir_autorizacion(
            top, "Corregir el costo cambia la ganancia ya informada.")
        if not resp:
            return
        try:
            r = corregir_costo_lote(lote["id"], nuevo, resp)
        except Exception as exc:
            messagebox.showerror("Costo", str(exc), parent=top)
            return
        top.destroy()
        msg = (f"Costo corregido: $ {r['costo_viejo']:,.2f} → "
               f"$ {r['costo_nuevo']:,.2f}")
        if r["unidades_vendidas"]:
            msg += (f"\n\nSe recalculó la ganancia de "
                    f"{r['unidades_vendidas']:g} unidad(es) ya vendidas: "
                    f"{'+' if r['ganancia_corregida'] >= 0 else ''}"
                    f"$ {r['ganancia_corregida']:,.2f}")
        if r["toco_costo_ultimo"]:
            msg += "\n\nTambién se actualizó el costo del producto."
        messagebox.showinfo("Listo", msg, parent=d)
        al_terminar() if al_terminar else None

    e.bind("<Return>", guardar)
    top.bind("<Escape>", lambda ev: top.destroy())
    fb = tk.Frame(top, bg=C.superficie)
    fb.pack(side="bottom", pady=14)
    btn(fb, "Guardar  (Enter)", variante="exito",
        comando=guardar).pack(side="left", padx=4)
    btn(fb, "Cancelar", variante="neutro",
        comando=top.destroy).pack(side="left", padx=4)

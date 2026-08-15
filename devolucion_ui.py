"""
devolucion_ui.py — Dialogo de devolucion parcial o total de una venta.

Se abre desde Caja > Caja actual, con una venta seleccionada.

Se separa de caja_ui.py porque la misma pantalla sirve tambien desde el
historial y, mas adelante, desde un buscador de tickets.
"""

import datetime
import tkinter as tk
from tkinter import ttk, messagebox

from styles import C, F, btn, lbl
from repositorio import (get_venta_para_devolver, registrar_devolucion,
                         buscar_ventas)


MOTIVOS = ("Producto fallado", "No era lo que queria", "Se arrepintio",
           "Error de cobro", "Vencido o en mal estado", "Otro")

REINTEGROS = {
    "Devolver efectivo":        "efectivo",
    "Acreditar en su cuenta":   "cuenta_corriente",
    "Sin reintegro (cambio)":   "sin_reintegro",
}


def buscar_venta_a_devolver(parent):
    """Buscador de ventas. Devuelve el venta_id elegido, o None.

    No depende de la sesion abierta: el cliente puede volver dias despues.
    """
    d = tk.Toplevel(parent)
    d.title("Buscar la venta a devolver")
    d.configure(bg=C.superficie)
    d.grab_set()
    w, h = 900, 520
    sw, sh = d.winfo_screenwidth(), d.winfo_screenheight()
    d.geometry(f"{w}x{h}+{(sw - w) // 2}+{max(0, (sh - h) // 2)}")

    lbl(d, "Buscar la venta", variante="titulo", bg=C.superficie).pack(
        anchor="w", padx=20, pady=(16, 2))
    lbl(d, "Numero de ticket, nombre o DNI del cliente, un producto que se "
           "llevo, o el monto total", variante="suave", bg=C.superficie).pack(
        anchor="w", padx=20)

    barra = tk.Frame(d, bg=C.superficie)
    barra.pack(fill="x", padx=20, pady=10)
    v_texto = tk.StringVar()
    e = tk.Entry(barra, textvariable=v_texto, width=40, font=F.normal,
                 bg=C.bg, fg=C.texto, relief="solid", bd=1)
    e.pack(side="left")
    lbl(barra, "Desde:", variante="suave", bg=C.superficie).pack(side="left", padx=(14, 4))
    v_desde = tk.StringVar(
        value=(datetime.date.today() - datetime.timedelta(days=7)).isoformat())
    tk.Entry(barra, textvariable=v_desde, width=12, font=F.normal, justify="center",
             bg=C.bg, fg=C.texto, relief="solid", bd=1).pack(side="left")

    cols = ("id", "fecha", "cliente", "items", "total", "productos")
    tv = ttk.Treeview(d, columns=cols, show="headings", height=14)
    for c_, t_, w_ in (("id", "Ticket", 70), ("fecha", "Fecha y hora", 140),
                       ("cliente", "Cliente", 150), ("items", "Items", 55),
                       ("total", "Total", 100), ("productos", "Que se llevo", 350)):
        tv.heading(c_, text=t_)
        tv.column(c_, width=w_, anchor="w")
    sb = ttk.Scrollbar(d, orient="vertical", command=tv.yview)
    tv.configure(yscrollcommand=sb.set)
    tv.pack(side="left", fill="both", expand=True, padx=(20, 0), pady=4)
    sb.pack(side="left", fill="y", padx=(0, 20), pady=4)

    lbl_pie = tk.Label(d, text="", font=F.normal, bg=C.superficie,
                       fg=C.texto_suave, anchor="w", padx=20)
    resultados = []

    def _buscar(*_a):
        tv.delete(*tv.get_children())
        resultados.clear()
        try:
            desde = v_desde.get().strip() or None
            resultados.extend(buscar_ventas(v_texto.get(), desde=desde))
        except Exception as exc:
            lbl_pie.config(text=f"Error buscando: {exc}")
            return
        for i, v in enumerate(resultados):
            devueltas = v["unidades_devueltas"] or 0
            prod = (v["productos"] or "")[:70]
            if devueltas:
                prod = f"[{devueltas:g} ya devueltas]  {prod}"
            tv.insert("", "end", iid=str(i), values=(
                f"#{v['id']}", (v["fecha"] or "")[:16],
                v["cliente_nombre"] or "—", f"{v['items']}",
                f"$ {v['total']:,.2f}", prod))
        lbl_pie.config(text=f"{len(resultados)} venta(s) con items sin devolver")
        if resultados:
            tv.selection_set("0")

    elegido = [None]

    def _aceptar(_e=None):
        sel = tv.selection()
        if sel:
            elegido[0] = resultados[int(sel[0])]["id"]
            d.destroy()

    tv.bind("<Double-1>", _aceptar)
    tv.bind("<Return>", _aceptar)
    e.bind("<Return>", lambda ev: _buscar())
    v_texto.trace_add("write", lambda *a: _buscar())
    d.bind("<Escape>", lambda ev: d.destroy())

    lbl_pie.pack(fill="x")
    pie = tk.Frame(d, bg=C.superficie)
    pie.pack(fill="x", pady=(4, 14))
    btn(pie, "Devolver de esta venta", variante="exito",
        comando=_aceptar).pack(side="left", padx=(20, 6))
    btn(pie, "Cancelar", variante="neutro", comando=d.destroy).pack(side="left")

    _buscar()
    e.focus_set()
    parent.wait_window(d)
    return elegido[0]


def dialogo_devolucion(parent, venta_id: int, sesion_id: int):
    """Devuelve el id de la devolucion registrada, o None si se cancelo."""
    venta = get_venta_para_devolver(venta_id)
    if not venta:
        messagebox.showwarning("Devolucion", "No se encontro la venta.", parent=parent)
        return None
    if venta.get("anulada"):
        messagebox.showwarning("Devolucion",
                               f"La venta #{venta_id} esta anulada: no se puede "
                               "devolver nada de ella.", parent=parent)
        return None

    devolvibles = [i for i in venta["items"] if i["devolvible"] > 0]
    if not devolvibles:
        messagebox.showinfo("Devolucion",
                            f"Ya se devolvio todo lo de la venta #{venta_id}.",
                            parent=parent)
        return None

    d = tk.Toplevel(parent)
    d.title(f"Devolucion — venta #{venta_id}")
    d.configure(bg=C.superficie)
    d.grab_set()
    w, h = 760, min(560, 330 + 30 * len(devolvibles))
    sw, sh = d.winfo_screenwidth(), d.winfo_screenheight()
    d.geometry(f"{w}x{h}+{(sw - w) // 2}+{max(0, (sh - h) // 2)}")

    # ── Encabezado ────────────────────────────────────────────────────────
    cab = tk.Frame(d, bg=C.superficie)
    cab.pack(fill="x", padx=20, pady=(16, 4))
    lbl(cab, f"Devolucion de la venta #{venta_id}", variante="titulo",
        bg=C.superficie).pack(side="left")

    desc_pct = venta.get("descuento_pct") or 0
    detalle = f"Pago: {venta.get('metodo_pago', '—')}"
    if venta.get("cliente_nombre"):
        detalle += f"   ·   Cliente: {venta['cliente_nombre']}"
    if desc_pct:
        detalle += f"   ·   La venta tuvo {desc_pct:g}% de descuento"
    lbl(d, detalle, variante="suave", bg=C.superficie).pack(anchor="w", padx=20)

    lbl(d, "Escribi cuantas unidades vuelven de cada producto (0 = no se devuelve)",
        variante="suave", bg=C.superficie).pack(anchor="w", padx=20, pady=(8, 2))

    # ── Grilla de items ───────────────────────────────────────────────────
    cont = tk.Frame(d, bg=C.superficie, highlightthickness=1,
                    highlightbackground=C.borde)
    cont.pack(fill="both", expand=True, padx=20, pady=4)

    enc = tk.Frame(cont, bg=C.acento)
    enc.pack(fill="x")
    for texto, ancho in (("Producto", 34), ("Vendido", 9), ("Ya devuelto", 12),
                         ("Puede volver", 13), ("Devolver", 10)):
        tk.Label(enc, text=texto, font=F.tabla_header, bg=C.acento, fg=C.texto,
                 width=ancho, anchor="w", padx=4, pady=6).pack(side="left")

    filas = []
    for it in devolvibles:
        f = tk.Frame(cont, bg=C.superficie)
        f.pack(fill="x", pady=1)
        tk.Label(f, text=it["descripcion"][:40], font=F.normal, bg=C.superficie,
                 fg=C.texto, width=34, anchor="w", padx=4).pack(side="left")
        for val, ancho in ((f"{it['cantidad']:g}", 9),
                           (f"{it['ya_devuelto']:g}", 12),
                           (f"{it['devolvible']:g}", 13)):
            tk.Label(f, text=val, font=F.normal, bg=C.superficie, fg=C.texto,
                     width=ancho, anchor="w", padx=4).pack(side="left")
        var = tk.StringVar(value="0")
        e = tk.Entry(f, textvariable=var, width=8, font=F.normal, justify="center",
                     bg=C.bg, fg=C.texto, relief="solid", bd=1)
        e.pack(side="left", padx=4)
        filas.append((it, var, e))

    # ── Total en vivo ─────────────────────────────────────────────────────
    lbl_total = tk.Label(d, text="A reintegrar: $ 0,00", font=F.total,
                         bg=C.superficie, fg=C.texto, anchor="e")
    lbl_total.pack(fill="x", padx=20, pady=(8, 2))

    def _seleccion():
        """Lee la grilla. Devuelve (items, total, error)."""
        items, total = [], 0.0
        for it, var, _e in filas:
            txt = (var.get() or "0").strip().replace(",", ".")
            if txt in ("", "0"):
                continue
            try:
                cant = float(txt)
            except ValueError:
                return [], 0.0, f"'{txt}' no es un numero ({it['descripcion'][:30]})"
            if cant < 0:
                return [], 0.0, f"Cantidad negativa en {it['descripcion'][:30]}"
            if cant > it["devolvible"] + 1e-9:
                return [], 0.0, (f"{it['descripcion'][:30]}: solo pueden volver "
                                 f"{it['devolvible']:g}, pediste {cant:g}")
            total += cant * it["precio_unitario"] * (1 - desc_pct / 100)
            items.append({"detalle_id": it["detalle_id"], "cantidad": cant})
        return items, total, ""

    def _recalcular(*_a):
        items, total, err = _seleccion()
        if err:
            lbl_total.config(text=err, fg=C.peligro)
        else:
            lbl_total.config(text=f"A reintegrar: $ {total:,.2f}", fg=C.texto)

    for _it, var, _e in filas:
        var.trace_add("write", _recalcular)

    def _todo():
        for it, var, _e in filas:
            var.set(f"{it['devolvible']:g}")

    # ── Motivo y forma de reintegro ───────────────────────────────────────
    opts = tk.Frame(d, bg=C.superficie)
    opts.pack(fill="x", padx=20, pady=(4, 8))

    lbl(opts, "Motivo:", variante="suave", bg=C.superficie).pack(side="left")
    v_motivo = tk.StringVar(value=MOTIVOS[0])
    ttk.Combobox(opts, textvariable=v_motivo, values=MOTIVOS, width=22,
                 state="readonly").pack(side="left", padx=(4, 16))

    lbl(opts, "Reintegro:", variante="suave", bg=C.superficie).pack(side="left")
    v_reint = tk.StringVar(value="Devolver efectivo")
    opciones = list(REINTEGROS)
    if not venta.get("cliente_id"):
        opciones.remove("Acreditar en su cuenta")
    ttk.Combobox(opts, textvariable=v_reint, values=opciones, width=22,
                 state="readonly").pack(side="left", padx=4)

    btn(opts, "Devolver todo", variante="neutro", comando=_todo).pack(side="right")

    resultado = [None]

    def _confirmar():
        items, total, err = _seleccion()
        if err:
            messagebox.showwarning("Devolucion", err, parent=d)
            return
        if not items:
            messagebox.showinfo("Devolucion",
                                "No cargaste ninguna cantidad a devolver.", parent=d)
            return
        metodo = REINTEGROS[v_reint.get()]
        texto_metodo = {
            "efectivo": f"Salen $ {total:,.2f} de la caja.",
            "cuenta_corriente": f"Se le descuentan $ {total:,.2f} de la cuenta.",
            "sin_reintegro": "No se devuelve plata (cambio de mercaderia).",
        }[metodo]
        # Devolver saca plata del cajon: hace falta autorizacion y que
        # quede registrado quien la dio.
        from fiado_ui import pedir_autorizacion
        responsable = pedir_autorizacion(
            d, f"Devolver $ {total:,.2f} requiere autorizacion.")
        if not responsable:
            return

        if not messagebox.askyesno(
                "Confirmar devolucion",
                f"{len(items)} producto(s) vuelven al stock.\n\n{texto_metodo}\n\n"
                f"Motivo: {v_motivo.get()}\n\nConfirmas?", parent=d):
            return
        try:
            dev_id = registrar_devolucion(
                venta_id, sesion_id, items,
                motivo=v_motivo.get(), metodo_reintegro=metodo,
                autorizado_por=responsable)
        except Exception as exc:
            messagebox.showerror("Devolucion",
                                 f"No se pudo registrar:\n\n{exc}\n\n"
                                 "No se modifico nada.", parent=d)
            return
        if not dev_id:
            messagebox.showerror("Devolucion",
                                 "No se pudo registrar la devolucion.", parent=d)
            return
        from repositorio import registrar_bitacora
        registrar_bitacora(
            "Devolucion", responsable,
            f"Venta #{venta_id} — {len(items)} item(s) — {v_motivo.get()} "
            f"({metodo})", total, venta_id)
        resultado[0] = dev_id
        d.destroy()

    pie = tk.Frame(d, bg=C.superficie)
    pie.pack(fill="x", pady=(0, 14))
    btn(pie, "Confirmar devolucion", variante="exito",
        comando=_confirmar).pack(side="left", padx=(20, 6))
    btn(pie, "Cancelar", variante="neutro", comando=d.destroy).pack(side="left")

    if filas:
        filas[0][2].focus_set()
    d.bind("<Escape>", lambda e: d.destroy())
    parent.wait_window(d)
    return resultado[0]

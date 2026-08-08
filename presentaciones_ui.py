"""
presentaciones_ui.py — Presentaciones de un producto.

Una presentacion es el MISMO producto vendido en otra unidad, con su propio
codigo de barras y su propio precio. Caso tipico: caramelos con stock en
gramos que ademas se venden en bolsa cerrada de 800 g.

El stock es uno solo. Vender una bolsa descuenta 800 del granel, asi que
nunca se descuadra ni hay que hacer conversiones a mano.
"""

import tkinter as tk
from tkinter import ttk, messagebox

from styles import C, F, btn, lbl
from repositorio import (get_presentaciones, crear_presentacion,
                         eliminar_presentacion, get_producto_completo,
                         get_stock_producto)


def dialogo_presentaciones(parent, producto_id: int):
    prod = get_producto_completo(producto_id)
    if not prod:
        return

    d = tk.Toplevel(parent)
    d.title(f"Presentaciones — {prod['descripcion']}")
    d.configure(bg=C.superficie)
    d.grab_set()
    w, h = 720, 480
    sw, sh = d.winfo_screenwidth(), d.winfo_screenheight()
    d.geometry(f"{w}x{h}+{(sw - w) // 2}+{max(0, (sh - h) // 2)}")

    por_peso = bool(prod.get("vendido_por_peso"))
    unidad = "g / kg" if por_peso else "unidades"

    lbl(d, prod["descripcion"], variante="titulo", bg=C.superficie).pack(
        anchor="w", padx=20, pady=(16, 2))
    lbl(d, f"Stock: {get_stock_producto(producto_id):g} {unidad}   ·   "
           f"Precio suelto: $ {prod.get('precio_base', 0):,.4f} por {unidad.split()[0]}",
        variante="suave", bg=C.superficie).pack(anchor="w", padx=20)

    if not por_peso:
        aviso = tk.Label(
            d, bg=C.err_flash, fg=C.peligro, font=F.normal, justify="left",
            padx=14, pady=10, anchor="w",
            text=("Este producto NO esta marcado como vendido por peso.\\n"
                  "Las presentaciones se pensaron para granel (gramos, kilos).\\n"
                  "Podes usarlas igual para packs (ej: caja de 12), pero revisa\\n"
                  "que el stock este cargado en la unidad chica."))
        aviso.pack(fill="x", padx=20, pady=8)

    lbl(d, "Al escanear el codigo de una presentacion, el TPV agrega su "
           "cantidad y cobra su precio.", variante="suave",
        bg=C.superficie).pack(anchor="w", padx=20, pady=(10, 4))

    cols = ("codigo", "descripcion", "factor", "precio", "unitario", "vs")
    tv = ttk.Treeview(d, columns=cols, show="headings", height=7)
    for c_, t_, w_ in (("codigo", "Codigo de barras", 140),
                       ("descripcion", "Presentacion", 140),
                       ("factor", f"Equivale a ({unidad.split()[0]})", 120),
                       ("precio", "Precio", 95),
                       ("unitario", f"Por {unidad.split()[0]}", 95),
                       ("vs", "vs suelto", 90)):
        tv.heading(c_, text=t_)
        tv.column(c_, width=w_, anchor="w")
    tv.pack(fill="both", expand=True, padx=20, pady=4)

    def _recargar():
        tv.delete(*tv.get_children())
        base = float(prod.get("precio_base") or 0)
        for pr in get_presentaciones(producto_id):
            unit = pr["precio"] / pr["factor"] if pr["factor"] else 0
            if base > 0:
                dif = (unit / base - 1) * 100
                vs = f"{dif:+.0f}%"
            else:
                vs = "—"
            tv.insert("", "end", iid=str(pr["id"]), values=(
                pr["codigo"], pr["descripcion"], f"{pr['factor']:g}",
                f"$ {pr['precio']:,.2f}", f"$ {unit:,.4f}", vs))

    # ── Alta ──────────────────────────────────────────────────────────────
    alta = tk.LabelFrame(d, text=" Nueva presentacion ", bg=C.superficie,
                         fg=C.texto, font=F.normal, padx=12, pady=10)
    alta.pack(fill="x", padx=20, pady=(8, 4))

    campos = {}
    for i, (clave, etiqueta, ancho, ph) in enumerate((
            ("codigo", "Codigo de barras", 18, "escanealo aca"),
            ("descripcion", "Nombre", 16, "bolsa 800 g"),
            ("factor", f"Equivale a ({unidad.split()[0]})", 10, "800"),
            ("precio", "Precio de venta", 10, "850.00"))):
        tk.Label(alta, text=etiqueta, bg=C.superficie, fg=C.texto_suave,
                 font=F.pequeña).grid(row=0, column=i, sticky="w", padx=4)
        var = tk.StringVar()
        e = tk.Entry(alta, textvariable=var, width=ancho, font=F.normal,
                     bg=C.bg, fg=C.texto, relief="solid", bd=1)
        e.grid(row=1, column=i, padx=4)
        campos[clave] = var

    lbl_calc = tk.Label(alta, text="", bg=C.superficie, fg=C.texto_suave,
                        font=F.pequeña, anchor="w")
    lbl_calc.grid(row=2, column=0, columnspan=5, sticky="w", pady=(6, 0))

    def _preview(*_a):
        try:
            f = float((campos["factor"].get() or "0").replace(",", "."))
            p = float((campos["precio"].get() or "0").replace(",", "."))
        except ValueError:
            lbl_calc.config(text="")
            return
        if f <= 0 or p <= 0:
            lbl_calc.config(text="")
            return
        base = float(prod.get("precio_base") or 0)
        unit = p / f
        txt = f"Queda a $ {unit:,.4f} por {unidad.split()[0]}"
        if base > 0:
            dif = (unit / base - 1) * 100
            suelto = base * f
            txt += (f"   ·   suelto costaria $ {suelto:,.2f}   "
                    f"·   {'mas barato' if dif < 0 else 'mas caro'} {abs(dif):.0f}%")
        lbl_calc.config(text=txt)

    for v in campos.values():
        v.trace_add("write", _preview)

    def _agregar():
        try:
            crear_presentacion(
                producto_id,
                campos["codigo"].get().strip(),
                campos["descripcion"].get().strip() or "presentacion",
                float((campos["factor"].get() or "0").replace(",", ".")),
                float((campos["precio"].get() or "0").replace(",", ".")))
        except ValueError as exc:
            messagebox.showwarning("Presentaciones", str(exc), parent=d)
            return
        except Exception as exc:
            msg = str(exc)
            if "UNIQUE" in msg:
                msg = "Ese codigo de barras ya esta en uso."
            messagebox.showerror("Presentaciones", msg, parent=d)
            return
        for v in campos.values():
            v.set("")
        lbl_calc.config(text="")
        _recargar()

    btn(alta, "Agregar", variante="exito", comando=_agregar).grid(
        row=1, column=4, padx=(12, 0))

    def _borrar():
        sel = tv.selection()
        if not sel:
            return
        if messagebox.askyesno("Presentaciones",
                               "Eliminar esta presentacion?\\n\\n"
                               "Las ventas ya hechas no se tocan.", parent=d):
            eliminar_presentacion(int(sel[0]))
            _recargar()

    pie = tk.Frame(d, bg=C.superficie)
    pie.pack(fill="x", pady=(4, 14))
    btn(pie, "Eliminar seleccionada", variante="peligro",
        comando=_borrar).pack(side="left", padx=(20, 6))
    btn(pie, "Listo", variante="neutro", comando=d.destroy).pack(side="right", padx=20)

    _recargar()
    d.bind("<Escape>", lambda e: d.destroy())
    parent.wait_window(d)

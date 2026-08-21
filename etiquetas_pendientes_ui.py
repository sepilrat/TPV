"""
etiquetas_pendientes_ui.py — Qué etiquetas de góndola hay que imprimir.

Dos razones por las que una etiqueta queda vieja, y son la misma tarea:
el producto es nuevo y nunca tuvo, o le cambió el precio. Separarlas
obligaría a recorrer la góndola dos veces.
"""

import datetime
import tkinter as tk
from tkinter import messagebox

from styles import C, F, btn, lbl, tabla
from repositorio import etiquetas_pendientes, get_productos


COLS = [
    ("motivo", "Por qué",     110, "w"),
    ("desc",   "Producto",    260, "w"),
    ("cat",    "Categoría",   130, "w"),
    ("antes",  "Antes",       100, "e"),
    ("ahora",  "Ahora",       100, "e"),
    ("var",    "Variación",    90, "e"),
    ("fecha",  "Cuándo",      120, "w"),
]


def abrir_etiquetas_pendientes(parent):
    d = tk.Toplevel(parent)
    d.title("Etiquetas pendientes")
    d.configure(bg=C.superficie)
    d.grab_set()
    w, h = 900, min(600, d.winfo_screenheight() - 90)
    sw, sh = d.winfo_screenwidth(), d.winfo_screenheight()
    d.geometry(f"{w}x{h}+{(sw-w)//2}+{max(0,(sh-h)//2)}")

    lbl(d, "Etiquetas pendientes", variante="titulo",
        bg=C.superficie).pack(anchor="w", padx=18, pady=(16, 2))
    lbl(d, "Productos nuevos y los que cambiaron de precio: las dos razones "
           "por las que una etiqueta de góndola queda vieja.",
        variante="suave", bg=C.superficie).pack(anchor="w", padx=18)

    # El pie primero y anclado abajo, para que la tabla no lo empuje
    pie = tk.Frame(d, bg=C.superficie)
    pie.pack(side="bottom", fill="x", pady=12)

    bar = tk.Frame(d, bg=C.superficie)
    bar.pack(fill="x", padx=18, pady=(12, 6))
    hoy = datetime.date.today()
    lbl(bar, "Desde:", variante="suave", bg=C.superficie).pack(side="left")
    v_desde = tk.StringVar(value=hoy.isoformat())
    tk.Entry(bar, textvariable=v_desde, width=11, font=F.normal, bg=C.bg,
             fg=C.texto, relief="solid", bd=1).pack(side="left", padx=4)
    lbl(bar, "Hasta:", variante="suave", bg=C.superficie).pack(side="left",
                                                                padx=(8, 0))
    v_hasta = tk.StringVar(value=hoy.isoformat())
    tk.Entry(bar, textvariable=v_hasta, width=11, font=F.normal, bg=C.bg,
             fg=C.texto, relief="solid", bd=1).pack(side="left", padx=4)

    v_nuevos = tk.BooleanVar(value=True)
    v_cambios = tk.BooleanVar(value=True)

    filas = []

    def refrescar(*_a):
        filas.clear()
        try:
            filas.extend(etiquetas_pendientes(
                v_desde.get().strip(), v_hasta.get().strip(),
                incluir_nuevos=v_nuevos.get(),
                incluir_cambios=v_cambios.get()))
        except Exception as exc:
            messagebox.showerror("Etiquetas", f"No se pudo leer:\n{exc}",
                                 parent=d)
            return
        tv.delete(*tv.get_children())
        for i, c in enumerate(filas):
            var = c.get("variacion_pct")
            if c.get("es_nuevo"):
                txt_var, tag = "—", "nuevo"
            elif var is None:
                txt_var, tag = "—", ""
            else:
                txt_var = f"{var:+.1f}%"
                tag = "subio" if var > 0 else "bajo"
            tv.insert("", "end", iid=str(i), tags=(tag,) if tag else (),
                      values=(
                          "🆕 nuevo" if c.get("es_nuevo") else "precio",
                          c["descripcion"][:40], c.get("categoria") or "—",
                          (f"$ {c['precio_viejo']:,.2f}"
                           if c.get("precio_viejo") else "—"),
                          f"$ {c['precio_nuevo']:,.2f}", txt_var,
                          (c["fecha"] or "")[:16]))
        nuevos = sum(1 for c in filas if c.get("es_nuevo"))
        lbl_pie.config(
            text=(f"{len(filas)} etiqueta(s):  {nuevos} nuevo(s) · "
                  f"{len(filas) - nuevos} cambio(s) de precio"
                  if filas else "Nada para imprimir en el período"))

    def _rango(dias):
        v_desde.set((hoy - datetime.timedelta(days=dias)).isoformat())
        v_hasta.set(hoy.isoformat())
        refrescar()

    for txt, dias in (("Hoy", 0), ("7 días", 6), ("30 días", 29)):
        btn(bar, txt, variante="neutro",
            comando=lambda x=dias: _rango(x)).pack(side="left", padx=2)

    tk.Checkbutton(bar, text="Nuevos", variable=v_nuevos, bg=C.superficie,
                   fg=C.texto, font=F.normal, selectcolor=C.superficie,
                   activebackground=C.superficie,
                   command=refrescar).pack(side="left", padx=(14, 0))
    tk.Checkbutton(bar, text="Cambios de precio", variable=v_cambios,
                   bg=C.superficie, fg=C.texto, font=F.normal,
                   selectcolor=C.superficie, activebackground=C.superficie,
                   command=refrescar).pack(side="left")
    btn(bar, "Actualizar", variante="neutro",
        comando=refrescar).pack(side="right")

    frame_t, tv = tabla(d, COLS, altura=14)
    frame_t.pack(fill="both", expand=True, padx=18)
    tv.configure(selectmode="extended")
    tv.tag_configure("subio", foreground=C.peligro)
    tv.tag_configure("bajo", foreground=C.exito)
    tv.tag_configure("nuevo", background=C.ok_flash)

    def _sel_todo(event=None):
        tv.selection_set(tv.get_children())
        return "break"

    tv.bind("<Control-a>", _sel_todo)
    tv.bind("<Control-A>", _sel_todo)

    def _imprimir():
        sel = tv.selection()
        elegidos = [filas[int(i)] for i in sel] if sel else filas
        if not elegidos:
            messagebox.showinfo("Etiquetas", "No hay nada para imprimir.",
                                parent=d)
            return
        if not sel and not messagebox.askyesno(
                "Etiquetas",
                f"No marcaste ninguno: ¿imprimo las {len(elegidos)} "
                f"etiquetas?", parent=d):
            return
        ids = {c["producto_id"] for c in elegidos}
        presel = [p for p in get_productos() if p["id"] in ids]
        d.destroy()
        from etiquetas import abrir_selector_etiquetas
        abrir_selector_etiquetas(parent, productos_presel=presel)

    lbl_pie = lbl(pie, "", variante="suave", bg=C.superficie)
    btn(pie, "🏷  Imprimir estas etiquetas", variante="exito",
        comando=_imprimir).pack(side="left", padx=(18, 6))
    btn(pie, "☑ Seleccionar todo", variante="neutro",
        comando=_sel_todo).pack(side="left", padx=4)
    btn(pie, "Cerrar", variante="neutro",
        comando=d.destroy).pack(side="right", padx=18)
    lbl_pie.pack(side="left", padx=12)

    d.bind("<Escape>", lambda ev: d.destroy())
    _rango(6)
    parent.wait_window(d)

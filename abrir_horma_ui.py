"""
abrir_horma_ui.py — Pasa una pieza entera al producto fraccionado.

Cuando el entero y el fraccionado se llevan como dos productos distintos
(cada uno con su codigo y su precio por kilo), abrir una horma para el
mostrador tiene que mover esos kilos de un producto al otro. Si no, el
entero sigue contando hormas que ya no estan y el fraccionado vende en
negativo desde el primer corte.

Se abre desde Productos, con el producto ENTERO seleccionado.
"""

import tkinter as tk
from tkinter import ttk, messagebox

from styles import C, F, btn, lbl
from repositorio import (get_productos, get_stock_producto,
                         get_producto_completo, abrir_pieza_entera)


def _parecidos(prod, todos):
    """Candidatos a ser el fraccionado del mismo articulo.

    Se ordenan por palabras en comun con la descripcion del entero, asi el
    combo aparece con el correcto elegido y no hay que buscarlo.
    """
    def norm(t):
        t = (t or "").lower().translate(
            str.maketrans("áéíóúñ", "aeioun"))
        return set(p for p in t.replace(",", " ").split() if len(p) > 2)

    base = norm(prod["descripcion"]) - {"horma", "entero", "entera", "pieza"}
    otros = [p for p in todos if p["id"] != prod["id"]]
    return sorted(otros, key=lambda p: -len(base & norm(p["descripcion"])))


def dialogo_abrir_horma(parent, producto_entero_id: int, on_ok=None):
    prod = get_producto_completo(producto_entero_id)
    if not prod:
        return

    stock = get_stock_producto(producto_entero_id)
    if stock <= 0:
        messagebox.showinfo("Abrir horma",
                            f"No hay stock de {prod['descripcion']}.",
                            parent=parent)
        return

    candidatos = _parecidos(prod, get_productos())
    if not candidatos:
        messagebox.showwarning("Abrir horma",
                               "No hay otro producto al que pasar los kilos.",
                               parent=parent)
        return

    d = tk.Toplevel(parent)
    d.title("Abrir horma")
    d.configure(bg=C.superficie)
    d.grab_set()
    w, h = 620, 440
    sw, sh = d.winfo_screenwidth(), d.winfo_screenheight()
    d.geometry(f"{w}x{h}+{(sw - w) // 2}+{max(0, (sh - h) // 2)}")

    lbl(d, "Abrir horma para fraccionar", variante="titulo",
        bg=C.superficie).pack(anchor="w", padx=20, pady=(16, 2))
    lbl(d, f"Sale de: {prod['descripcion']}   ·   hay {stock:.3f} kg",
        variante="suave", bg=C.superficie).pack(anchor="w", padx=20)

    f = tk.Frame(d, bg=C.superficie)
    f.pack(fill="x", padx=20, pady=16)

    tk.Label(f, text="Pasa a", bg=C.superficie, fg=C.texto, font=F.normal,
             anchor="w", width=22).grid(row=0, column=0, sticky="w", pady=6)
    nombres = [f"{p['descripcion']}" for p in candidatos]
    v_destino = tk.StringVar(value=nombres[0])
    ttk.Combobox(f, textvariable=v_destino, values=nombres, width=34,
                 state="readonly").grid(row=0, column=1, columnspan=2,
                                        sticky="w", padx=6)

    tk.Label(f, text="Peso de la horma (kg)", bg=C.superficie, fg=C.texto,
             font=F.normal, anchor="w", width=22).grid(row=1, column=0,
                                                       sticky="w", pady=6)
    v_peso = tk.StringVar()
    tk.Entry(f, textvariable=v_peso, width=12, font=F.normal, justify="center",
             bg=C.bg, fg=C.texto, relief="solid", bd=1).grid(row=1, column=1,
                                                             padx=6)

    lbl_bal = tk.Label(f, text="", bg=C.superficie, fg=C.texto_suave,
                       font=F.pequeña)
    lbl_bal.grid(row=1, column=3, sticky="w", padx=6)

    def _pesar():
        try:
            from balanza import leer_peso
        except ImportError:
            lbl_bal.config(text="balanza no disponible")
            return
        peso, msg = leer_peso()
        if peso is None:
            lbl_bal.config(text=f"balanza: {msg}")
            return
        v_peso.set(f"{peso:.3f}")
        lbl_bal.config(text="leido de la balanza")

    btn(f, "Pesar", variante="neutro", comando=_pesar).grid(row=1, column=2,
                                                            padx=4)

    caja = tk.Frame(d, bg=C.acento, padx=16, pady=14)
    caja.pack(fill="x", padx=20)
    lbl_res = tk.Label(caja, text="Poné la horma en la balanza", bg=C.acento,
                       fg=C.texto, font=F.total, anchor="w", justify="left")
    lbl_res.pack(fill="x")
    lbl_det = tk.Label(caja, text="", bg=C.acento, fg=C.texto_suave,
                       font=F.pequeña, anchor="w", justify="left")
    lbl_det.pack(fill="x", pady=(8, 0))

    def _destino():
        return candidatos[nombres.index(v_destino.get())]

    def _calcular(*_a):
        try:
            peso = float((v_peso.get() or "0").replace(",", "."))
        except ValueError:
            peso = -1
        if peso <= 0:
            lbl_res.config(text="Poné la horma en la balanza")
            lbl_det.config(text="")
            return
        if peso > stock + 1e-6:
            lbl_res.config(text=f"No hay tanto: quedan {stock:.3f} kg")
            lbl_det.config(text="")
            return
        dest = _destino()
        lbl_res.config(text=f"{peso:.3f} kg pasan a «{dest['descripcion']}»")
        lbl_det.config(
            text=(f"Entero: {stock:.3f} → {stock - peso:.3f} kg\n"
                  f"El costo por kilo se arrastra de los lotes que se consumen, "
                  f"no del ultimo precio de compra."))

    v_peso.trace_add("write", _calcular)
    v_destino.trace_add("write", _calcular)

    def _confirmar():
        try:
            peso = float((v_peso.get() or "0").replace(",", "."))
        except ValueError:
            messagebox.showwarning("Abrir horma", "El peso no es un numero.",
                                   parent=d)
            return
        dest = _destino()
        try:
            r = abrir_pieza_entera(producto_entero_id, dest["id"], peso)
        except ValueError as exc:
            messagebox.showwarning("Abrir horma", str(exc), parent=d)
            return
        except Exception as exc:
            messagebox.showerror("Abrir horma",
                                 f"No se pudo hacer el traspaso:\n\n{exc}\n\n"
                                 "No se modifico nada.", parent=d)
            return
        messagebox.showinfo(
            "Abrir horma",
            f"{r['peso']:.3f} kg pasaron a «{dest['descripcion']}»\n\n"
            f"Costo arrastrado: $ {r['costo_kg']:,.2f} /kg\n"
            f"Quedan {r['restante_entero']:.3f} kg como pieza entera.",
            parent=d)
        if on_ok:
            on_ok()
        d.destroy()

    lbl(d, "Cargá el peso que marca la balanza, sin descontar corteza. "
           "La merma se ve sola al terminar la horma.",
        variante="suave", bg=C.superficie).pack(anchor="w", padx=20, pady=(12, 0))

    pie = tk.Frame(d, bg=C.superficie)
    pie.pack(fill="x", pady=(12, 14))
    btn(pie, "Abrir horma", variante="exito",
        comando=_confirmar).pack(side="left", padx=(20, 6))
    btn(pie, "Cancelar", variante="neutro", comando=d.destroy).pack(side="left")

    _calcular()
    d.bind("<Escape>", lambda e: d.destroy())
    parent.wait_window(d)

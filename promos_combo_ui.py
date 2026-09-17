"""
promos_combo_ui.py — Combos por pasos: "1 de estos jabones + 1 de estos
suavizantes = precio fijo".

Distinto de promos_grupo_ui.py (unidades intercambiables de UN pool): acá
hay varios "pasos" (categorías) y hay que llevar 1 (o más) de CADA paso.
El cliente elige cualquier producto dentro de cada paso, pero tiene que
completar todos los pasos para que el combo entre.
"""

import datetime
import tkinter as tk
from tkinter import ttk, messagebox

from styles import C, F, btn, lbl, tabla, toast, scrollable
from repositorio import (guardar_promo_combo, get_promo_combos,
                         borrar_promo_combo, get_productos, get_categorias,
                         margen_promo_combo)


COLS = [
    ("nombre", "Combo",        220, "w"),
    ("precio", "Precio",       110, "e"),
    ("pasos",  "Pasos",         60, "e"),
    ("vig",    "Vigencia",     170, "w"),
    ("estado", "Estado",        90, "w"),
]


class PromosComboUI(ttk.Frame):

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._filas = []
        self._construir()
        self.after(120, self.refrescar)

    def _construir(self):
        cab = tk.Frame(self, bg=C.bg)
        cab.pack(fill="x", padx=12, pady=(10, 2))
        lbl(cab, "Combos por pasos", variante="titulo").pack(side="left")
        self.lbl_cont = lbl(cab, "", variante="subtitulo")
        self.lbl_cont.pack(side="right")

        lbl(self, "Ej: 1 de estos 5 jabones en polvo + 1 de estos "
                  "suavizantes (el que sea) = precio fijo. El cliente "
                  "elige libremente dentro de cada paso.",
            variante="suave").pack(anchor="w", padx=12)

        pie = tk.Frame(self, bg=C.bg)
        pie.pack(side="bottom", fill="x", padx=12, pady=(8, 10))
        btn(pie, "➕  Nuevo combo", variante="exito",
            comando=lambda: self._dialogo(None)).pack(side="left")
        btn(pie, "✏️  Editar", variante="primario",
            comando=self._editar).pack(side="left", padx=6)
        btn(pie, "⏸  Activar / Pausar", variante="neutro",
            comando=self._toggle).pack(side="left", padx=6)
        btn(pie, "🗑  Eliminar", variante="peligro",
            comando=self._eliminar).pack(side="right")

        cont = tk.Frame(self, bg=C.bg)
        cont.pack(fill="both", expand=True, padx=12, pady=(8, 0))
        frame_t, self.tree = tabla(cont, COLS, altura=12)
        frame_t.pack(fill="both", expand=True)
        self.tree.tag_configure("pausada", foreground=C.texto_suave)
        self.tree.tag_configure("vencida", foreground=C.peligro)
        self.tree.bind("<Double-1>", lambda e: self._editar())

    def refrescar(self):
        if not self.winfo_exists():
            return
        try:
            self._filas = get_promo_combos()
        except Exception as exc:
            messagebox.showerror("Combos", f"No se pudo leer:\n{exc}",
                                 parent=self)
            return

        hoy = datetime.date.today().isoformat()
        self.tree.delete(*self.tree.get_children())
        for i, c in enumerate(self._filas):
            vig = "siempre"
            if c["fecha_desde"] or c["fecha_hasta"]:
                vig = f"{c['fecha_desde'] or '…'} a {c['fecha_hasta'] or '…'}"

            vencida = bool(c["fecha_hasta"] and c["fecha_hasta"] < hoy)
            if not c["activa"]:
                estado, tag = "pausada", "pausada"
            elif vencida:
                estado, tag = "vencida", "vencida"
            else:
                estado, tag = "activa", ""

            self.tree.insert("", "end", iid=str(i),
                             tags=(tag,) if tag else (),
                             values=(c["nombre"][:32],
                                     f"$ {c['valor']:,.2f}",
                                     len(c["slots"]), vig, estado))

        activas = sum(1 for c in self._filas
                      if c["activa"]
                      and not (c["fecha_hasta"] and c["fecha_hasta"] < hoy))
        try:
            self.lbl_cont.config(text=f"{len(self._filas)} combo(s) · "
                                      f"{activas} activo(s)")
        except tk.TclError:
            pass

    def _sel(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Combos", "Elegí un combo de la lista.",
                                parent=self)
            return None
        return self._filas[int(sel[0])]

    def _editar(self):
        c = self._sel()
        if c:
            self._dialogo(c)

    def _toggle(self):
        c = self._sel()
        if not c:
            return
        slots = [{"nombre": s["nombre"], "cantidad": s["cantidad"],
                  "producto_ids": [p["id"] for p in s["productos"]]}
                 for s in c["slots"]]
        guardar_promo_combo(c["id"], c["nombre"], c["valor"], slots,
                            c["fecha_desde"], c["fecha_hasta"],
                            activa=not c["activa"])
        self.refrescar()

    def _eliminar(self):
        c = self._sel()
        if not c:
            return
        if messagebox.askyesno("Eliminar",
                               f"¿Eliminar el combo «{c['nombre']}»?\n\n"
                               "Los productos no se tocan.", parent=self):
            borrar_promo_combo(c["id"])
            self.refrescar()

    # ── Alta / edición ────────────────────────────────────────────────

    def _dialogo(self, c):
        d = tk.Toplevel(self)
        d.title("Editar combo" if c else "Nuevo combo por pasos")
        d.configure(bg=C.superficie)
        d.grab_set()
        w = 760
        h = min(700, d.winfo_screenheight() - 80)
        sw, sh = d.winfo_screenwidth(), d.winfo_screenheight()
        d.geometry(f"{w}x{h}+{(sw-w)//2}+{max(0,(sh-h)//2)}")

        lbl(d, "Combo por pasos", variante="titulo",
            bg=C.superficie).pack(anchor="w", padx=18, pady=(16, 2))
        lbl(d, "Armá cada paso (ej: «Jabón en polvo») y elegí qué "
               "productos entran en ese paso. El cliente completa el "
               "combo llevando la cantidad pedida de CADA paso.",
            variante="suave", bg=C.superficie).pack(anchor="w", padx=18)

        pie = tk.Frame(d, bg=C.superficie)
        pie.pack(side="bottom", fill="x", pady=14)

        # ── Datos del combo ───────────────────────────────────────────
        datos = tk.Frame(d, bg=C.superficie)
        datos.pack(fill="x", padx=18, pady=(12, 6))

        lbl(datos, "Nombre del combo (lo ve el cajero)", variante="suave",
            bg=C.superficie).pack(anchor="w")
        v_nombre = tk.StringVar(value=c["nombre"] if c else "")
        e_nom = tk.Entry(datos, textvariable=v_nombre, font=F.normal,
                         bg=C.bg, fg=C.texto, relief="solid", bd=1)
        e_nom.pack(fill="x", ipady=4)

        f2 = tk.Frame(datos, bg=C.superficie)
        f2.pack(fill="x", pady=(10, 0))
        lbl(f2, "Precio total del combo:  $", variante="suave",
            bg=C.superficie).pack(side="left")
        v_valor = tk.StringVar(value=f"{c['valor']:g}" if c else "")
        tk.Entry(f2, textvariable=v_valor, font=F.subtitulo, width=10,
                 justify="center", bg=C.bg, fg=C.texto, relief="solid",
                 bd=1).pack(side="left", ipady=3, padx=6)

        f3 = tk.Frame(datos, bg=C.superficie)
        f3.pack(fill="x", pady=(10, 0))
        lbl(f3, "Vigencia (opcional):", variante="suave",
            bg=C.superficie).pack(side="left")
        lbl(f3, "desde", variante="suave", bg=C.superficie).pack(side="left",
                                                                  padx=(8, 2))
        v_desde = tk.StringVar(value=(c and c["fecha_desde"]) or "")
        tk.Entry(f3, textvariable=v_desde, width=12, font=F.normal, bg=C.bg,
                 fg=C.texto, relief="solid", bd=1).pack(side="left")
        lbl(f3, "hasta", variante="suave", bg=C.superficie).pack(side="left",
                                                                  padx=(8, 2))
        v_hasta = tk.StringVar(value=(c and c["fecha_hasta"]) or "")
        tk.Entry(f3, textvariable=v_hasta, width=12, font=F.normal, bg=C.bg,
                 fg=C.texto, relief="solid", bd=1).pack(side="left")
        lbl(f3, "  (AAAA-MM-DD, vacío = siempre)", variante="suave",
            bg=C.superficie).pack(side="left")

        lbl_margen = lbl(datos, "", variante="suave", bg=C.superficie)
        lbl_margen.pack(anchor="w", pady=(8, 0))

        # ── Pasos del combo ─────────────────────────────────────────
        barra = tk.Frame(d, bg=C.superficie)
        barra.pack(fill="x", padx=18, pady=(14, 4))
        lbl(barra, "Pasos del combo", variante="subtitulo",
            bg=C.superficie).pack(side="left")

        outer, cont_slots = scrollable(d, bg=C.superficie)
        outer.pack(fill="both", expand=True, padx=18, pady=(0, 4))

        cats = [{"id": None, "nombre": "Todas"}] + list(get_categorias())
        slots_data = []   # lista de dicts: nombre_var, cantidad_var,
                          # producto_ids(set), frame, lbl_count

        def _actualizar_margen(*_a):
            try:
                valor = float(v_valor.get().replace(",", "."))
            except ValueError:
                lbl_margen.config(text="")
                return
            slots_ok = [s for s in slots_data if s["producto_ids"]]
            if valor <= 0 or len(slots_ok) < 2:
                lbl_margen.config(text="")
                return
            slots_arg = [{"cantidad": s["cantidad_var"].get() or "1",
                          "producto_ids": list(s["producto_ids"])}
                         for s in slots_ok]
            try:
                slots_arg = [{"cantidad": int(s["cantidad"]),
                              "producto_ids": s["producto_ids"]}
                             for s in slots_arg]
            except ValueError:
                lbl_margen.config(text="")
                return
            m = margen_promo_combo(slots_arg, valor)
            if not m:
                lbl_margen.config(
                    text="(el margen no se puede estimar — falta costo "
                         "cargado en los productos de algún paso)")
                return
            if abs(m["margen_min"] - m["margen_max"]) < 0.01:
                lbl_margen.config(
                    text=f"Margen del combo: $ {m['margen_min']:,.2f} "
                         f"({m['pct_min']:.1f}%)",
                    fg=(C.exito if m["margen_min"] >= 0 else C.peligro))
            else:
                lbl_margen.config(
                    text=f"Margen del combo (según qué se lleve de cada "
                         f"paso): de $ {m['margen_min']:,.2f} "
                         f"({m['pct_min']:.1f}%) a $ {m['margen_max']:,.2f} "
                         f"({m['pct_max']:.1f}%)",
                    fg=(C.exito if m["margen_min"] >= 0 else C.advertencia))

        v_valor.trace_add("write", lambda *a: _actualizar_margen())

        def _elegir_productos(slot):
            """Sub-diálogo para marcar productos de UN paso puntual."""
            e = tk.Toplevel(d)
            e.title(f"Productos — {slot['nombre_var'].get() or 'paso'}")
            e.configure(bg=C.superficie)
            e.grab_set()
            ew, eh = 640, min(560, e.winfo_screenheight() - 80)
            esw, esh = e.winfo_screenwidth(), e.winfo_screenheight()
            e.geometry(f"{ew}x{eh}+{(esw-ew)//2}+{max(0,(esh-eh)//2)}")

            filtro = tk.Frame(e, bg=C.superficie)
            filtro.pack(fill="x", padx=14, pady=(14, 6))
            v_busq = tk.StringVar()
            tk.Entry(filtro, textvariable=v_busq, width=22, font=F.normal,
                     bg=C.bg, fg=C.texto, relief="solid",
                     bd=1).pack(side="left", ipady=3)
            v_cat = tk.StringVar(value="Todas")
            cb = ttk.Combobox(filtro, textvariable=v_cat, width=18,
                              state="readonly",
                              values=[cc["nombre"] for cc in cats])
            cb.pack(side="left", padx=6)
            lbl_n = lbl(filtro, "", variante="suave", bg=C.superficie)
            lbl_n.pack(side="right")

            cols = [("sel", "", 34, "center"),
                    ("desc", "Producto", 280, "w"),
                    ("cat", "Categoría", 130, "w"),
                    ("precio", "Precio", 90, "e")]
            frame_t, tv = tabla(e, cols, altura=13)
            frame_t.pack(fill="both", expand=True, padx=14)

            marcados = set(slot["producto_ids"])
            filas = []

            def _n():
                lbl_n.config(text=f"{len(marcados)} elegido(s)")

            def cargar(*_a):
                cat_id = cats[[cc["nombre"] for cc in cats]
                              .index(v_cat.get())]["id"]
                filas.clear()
                filas.extend(get_productos(filtro=v_busq.get().strip(),
                                           categoria_id=cat_id))
                tv.delete(*tv.get_children())
                for i, p in enumerate(filas):
                    tv.insert("", "end", iid=str(i), values=(
                        "☑" if p["id"] in marcados else "☐",
                        p["descripcion"][:42], p.get("categoria") or "—",
                        f"$ {p['precio_base']:,.2f}"))
                _n()

            def _click(ev):
                iid = tv.identify_row(ev.y)
                if not iid:
                    return
                p = filas[int(iid)]
                if p["id"] in marcados:
                    marcados.discard(p["id"])
                else:
                    marcados.add(p["id"])
                tv.set(iid, "sel", "☑" if p["id"] in marcados else "☐")
                _n()

            tv.bind("<Button-1>", _click)
            cb.bind("<<ComboboxSelected>>", cargar)
            v_busq.trace_add("write", lambda *a: cargar())

            pie_e = tk.Frame(e, bg=C.superficie)
            pie_e.pack(fill="x", pady=10)

            def _guardar_sel():
                slot["producto_ids"] = marcados
                slot["lbl_count"].config(
                    text=f"{len(marcados)} producto(s) elegido(s)"
                         if marcados else "Sin productos — tocá para elegir")
                e.destroy()
                _actualizar_margen()

            btn(pie_e, "Listo", variante="exito",
                comando=_guardar_sel).pack(side="left", padx=(14, 6))
            btn(pie_e, "Cancelar", variante="neutro",
                comando=e.destroy).pack(side="left")
            e.bind("<Escape>", lambda ev: e.destroy())
            cargar()

        def _agregar_slot(nombre_ini="", cantidad_ini="1",
                          producto_ids_ini=None):
            fila = tk.Frame(cont_slots, bg=C.bg,
                            highlightbackground=C.borde,
                            highlightthickness=1)
            fila.pack(fill="x", pady=4, ipady=6)

            slot = {"producto_ids": set(producto_ids_ini or []),
                   "frame": fila}

            l1 = tk.Frame(fila, bg=C.bg)
            l1.pack(fill="x", padx=10, pady=(4, 2))
            lbl(l1, "Paso:", variante="suave", bg=C.bg).pack(side="left")
            v_nom_slot = tk.StringVar(value=nombre_ini)
            slot["nombre_var"] = v_nom_slot
            tk.Entry(l1, textvariable=v_nom_slot, font=F.normal, width=26,
                     bg=C.superficie, fg=C.texto, relief="solid",
                     bd=1).pack(side="left", padx=6, ipady=2)
            lbl(l1, "Cantidad:", variante="suave", bg=C.bg).pack(side="left",
                                                                 padx=(12, 0))
            v_cant_slot = tk.StringVar(value=str(cantidad_ini))
            slot["cantidad_var"] = v_cant_slot
            tk.Entry(l1, textvariable=v_cant_slot, font=F.normal, width=4,
                     justify="center", bg=C.superficie, fg=C.texto,
                     relief="solid", bd=1).pack(side="left", padx=6)
            btn(l1, "🗑", variante="peligro",
                comando=lambda: _quitar_slot(slot)).pack(side="right")

            l2 = tk.Frame(fila, bg=C.bg)
            l2.pack(fill="x", padx=10, pady=(0, 2))
            n0 = len(slot["producto_ids"])
            lbl_count = lbl(
                l2, (f"{n0} producto(s) elegido(s)" if n0
                     else "Sin productos — tocá para elegir"),
                variante="suave", bg=C.bg)
            lbl_count.pack(side="left")
            slot["lbl_count"] = lbl_count
            btn(l2, "Elegir productos", variante="neutro",
                comando=lambda: _elegir_productos(slot)).pack(side="right")

            v_cant_slot.trace_add("write", lambda *a: _actualizar_margen())
            slots_data.append(slot)
            _actualizar_margen()

        def _quitar_slot(slot):
            if len(slots_data) <= 2:
                messagebox.showwarning(
                    "Combo", "Un combo necesita al menos 2 pasos.",
                    parent=d)
                return
            slot["frame"].destroy()
            slots_data.remove(slot)
            _actualizar_margen()

        btn(d, "+ Agregar paso", variante="neutro",
            comando=lambda: _agregar_slot()).pack(
            anchor="w", padx=18, pady=(2, 10))

        if c:
            for s in c["slots"]:
                _agregar_slot(s["nombre"], s["cantidad"],
                             [p["id"] for p in s["productos"]])
        else:
            _agregar_slot()
            _agregar_slot()

        def guardar(_ev=None):
            nombre = v_nombre.get().strip()
            if not nombre:
                messagebox.showwarning("Combo", "Poné un nombre.", parent=d)
                return
            try:
                valor = float(v_valor.get().replace(",", "."))
            except ValueError:
                messagebox.showwarning("Combo", "El precio no es un "
                                                "número.", parent=d)
                return
            slots = []
            for s in slots_data:
                try:
                    cant = int(s["cantidad_var"].get())
                except ValueError:
                    messagebox.showwarning(
                        "Combo", f"La cantidad de «{s['nombre_var'].get()}» "
                                f"no es un número.", parent=d)
                    return
                slots.append({"nombre": s["nombre_var"].get(),
                             "cantidad": cant,
                             "producto_ids": list(s["producto_ids"])})
            try:
                guardar_promo_combo(
                    c["id"] if c else None, nombre, valor, slots,
                    v_desde.get().strip() or None,
                    v_hasta.get().strip() or None,
                    activa=c["activa"] if c else True)
            except ValueError as exc:
                messagebox.showwarning("Combo", str(exc), parent=d)
                return
            except Exception as exc:
                messagebox.showerror("Combo", str(exc), parent=d)
                return
            d.destroy()
            self.refrescar()
            toast(self, f"«{nombre}» guardado con {len(slots)} pasos")

        d.bind("<Escape>", lambda ev: d.destroy())
        btn(pie, "Guardar", variante="exito",
            comando=guardar).pack(side="left", padx=(18, 6))
        btn(pie, "Cancelar  (Esc)", variante="neutro",
            comando=d.destroy).pack(side="left")

        e_nom.focus_set()

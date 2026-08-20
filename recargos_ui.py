"""
recargos_ui.py — Recargos por día y horario.

Cuando el local cierra y pasa a atender por ventanilla, cada cliente
lleva más tiempo y no se puede reponer mientras se atiende. El precio
nocturno cubre eso.

Se guarda como REGLA, no como precio: los precios de lista no se tocan.
Si se tocaran, al volver al horario normal habría que deshacerlo, y un
corte de luz en el medio dejaría el catálogo mal.
"""

import tkinter as tk
from tkinter import ttk, messagebox

from styles import C, F, btn, lbl, tabla, toast
from repositorio import (get_recargos, guardar_recargo, eliminar_recargo,
                         recargo_vigente, get_categorias, DIAS_SEMANA)


COLS = [
    ("nombre",  "Nombre",       170, "w"),
    ("pct",     "Recargo",       85, "e"),
    ("dias",    "Días",         200, "w"),
    ("horario", "Horario",      130, "w"),
    ("alcance", "Se aplica a",  190, "w"),
    ("estado",  "Estado",        95, "w"),
]


class RecargosUI(ttk.Frame):

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._filas = []
        self._construir()
        self.after(120, self.refrescar)

    def _construir(self):
        cab = tk.Frame(self, bg=C.bg)
        cab.pack(fill="x", padx=12, pady=(10, 2))
        lbl(cab, "Recargos por horario", variante="titulo").pack(side="left")
        self.lbl_ahora = lbl(cab, "", variante="subtitulo")
        self.lbl_ahora.pack(side="right")

        lbl(self, "Los precios de lista NO se tocan: el recargo se calcula al "
                  "vender. Al terminar la franja, los precios vuelven solos.",
            variante="suave").pack(anchor="w", padx=12)

        # La barra de acciones se empaqueta ANTES que la tabla y anclada
        # abajo: si va despues, la tabla se estira y la empuja fuera de
        # la ventana. Los botones quedaban invisibles.
        ac = tk.Frame(self, bg=C.bg)
        ac.pack(side="bottom", fill="x", padx=12, pady=(8, 10))

        cont = tk.Frame(self, bg=C.bg)
        cont.pack(fill="both", expand=True, padx=12, pady=(8, 0))
        frame_t, self.tree = tabla(cont, COLS, altura=10)
        frame_t.pack(fill="both", expand=True)
        self.tree.tag_configure("vigente", background=C.ok_flash)
        self.tree.tag_configure("inactivo", foreground=C.texto_suave)
        self.tree.bind("<Double-1>", lambda e: self._editar())

        btn(ac, "➕  Nuevo recargo", variante="exito",
            comando=lambda: self._dialogo(None)).pack(side="left")
        btn(ac, "✏️  Editar", variante="primario",
            comando=self._editar).pack(side="left", padx=6)
        btn(ac, "⏸  Activar / Pausar", variante="neutro",
            comando=self._toggle).pack(side="left", padx=6)
        btn(ac, "🗑  Eliminar", variante="peligro",
            comando=self._eliminar).pack(side="right")

    # ── Datos ─────────────────────────────────────────────────────────

    def refrescar(self):
        try:
            self._filas = get_recargos()
            vigente = recargo_vigente()
        except Exception as exc:
            messagebox.showerror("Recargos", f"No se pudo leer:\n{exc}",
                                 parent=self)
            return

        cats = {c["id"]: c["nombre"] for c in get_categorias()}
        self.tree.delete(*self.tree.get_children())
        for i, r in enumerate(self._filas):
            dias = [int(d) for d in str(r["dias"]).split(",") if d.strip()]
            txt_dias = self._texto_dias(dias)
            d, h = int(r["hora_desde"]), int(r["hora_hasta"])
            horario = "todo el día" if d == h else f"{d:02d}:00 a {h:02d}:00"
            if r["alcance"] == "todo":
                alc = "todo el catálogo"
            elif r["alcance"] == "categorias":
                nombres = [cats.get(c, "?") for c in r["categoria_ids"]]
                alc = ", ".join(nombres)[:34] or "sin categorías"
            else:
                alc = f"{len(r['producto_ids'])} producto(s)"

            es_vigente = vigente and vigente["id"] == r["id"]
            tag = ("vigente" if es_vigente
                   else ("inactivo" if not r["activo"] else ""))
            estado = ("RIGIENDO AHORA" if es_vigente
                      else ("activo" if r["activo"] else "pausado"))
            self.tree.insert("", "end", iid=str(i), tags=(tag,) if tag else (),
                             values=(r["nombre"], f"+{r['porcentaje']:g}%",
                                     txt_dias, horario, alc, estado))

        if vigente:
            self.lbl_ahora.config(
                text=(f"Ahora mismo: +{vigente['porcentaje']:g}% "
                      f"({vigente['nombre']})"), foreground=C.exito)
        else:
            self.lbl_ahora.config(text="Ahora mismo: sin recargo",
                                  foreground=C.texto_suave)

    @staticmethod
    def _texto_dias(dias):
        """'Lunes a sábado' en vez de listar los seis."""
        if not dias:
            return "—"
        if len(dias) == 7:
            return "todos los días"
        ordenados = sorted(dias)
        # Rango corrido: se escribe como rango
        if ordenados == list(range(ordenados[0], ordenados[-1] + 1)) and len(ordenados) > 2:
            return f"{DIAS_SEMANA[ordenados[0]]} a {DIAS_SEMANA[ordenados[-1]]}"
        return ", ".join(DIAS_SEMANA[d][:3] for d in ordenados)

    def _sel(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Recargos", "Elegí una regla de la lista.",
                                parent=self)
            return None
        return self._filas[int(sel[0])]

    def _editar(self):
        r = self._sel()
        if r:
            self._dialogo(r)

    def _toggle(self):
        r = self._sel()
        if not r:
            return
        guardar_recargo(r["id"], r["nombre"], r["porcentaje"],
                        [int(d) for d in str(r["dias"]).split(",") if d.strip()],
                        r["hora_desde"], r["hora_hasta"], r["alcance"],
                        r["categoria_ids"], r["producto_ids"],
                        activo=not r["activo"])
        self.refrescar()

    def _eliminar(self):
        r = self._sel()
        if not r:
            return
        if messagebox.askyesno("Eliminar",
                               f"Eliminar la regla «{r['nombre']}»?\n\n"
                               "Los precios de lista no se tocan.", parent=self):
            eliminar_recargo(r["id"])
            self.refrescar()

    # ── Alta / edición ────────────────────────────────────────────────

    def _dialogo(self, r):
        d = tk.Toplevel(self)
        d.title("Editar recargo" if r else "Nuevo recargo")
        d.configure(bg=C.superficie)
        d.grab_set()
        w = 520
        h = min(620, d.winfo_screenheight() - 100)
        sw, sh = d.winfo_screenwidth(), d.winfo_screenheight()
        d.geometry(f"{w}x{h}+{(sw-w)//2}+{max(0,(sh-h)//2)}")
        lbl(d, "Recargo por horario", variante="titulo",
            bg=C.superficie).pack(anchor="w", padx=18, pady=(16, 6))

        # El pie va PRIMERO y anclado abajo: si se empaqueta despues, el
        # cuerpo se estira y lo empuja fuera de la ventana.
        pie = tk.Frame(d, bg=C.superficie)
        pie.pack(side="bottom", fill="x", pady=14)

        from styles import scrollable
        outer, cuerpo = scrollable(d, bg=C.superficie)
        outer.pack(fill="both", expand=True, padx=18)

        lbl(cuerpo, "Nombre (lo ve solo el sistema)", variante="suave",
            bg=C.superficie).pack(anchor="w", pady=(4, 2))
        v_nombre = tk.StringVar(value=r["nombre"] if r else "Ventanilla noche")
        tk.Entry(cuerpo, textvariable=v_nombre, font=F.normal, bg=C.bg,
                 fg=C.texto, relief="solid", bd=1).pack(fill="x", ipady=4)

        lbl(cuerpo, "Porcentaje de recargo", variante="suave",
            bg=C.superficie).pack(anchor="w", pady=(12, 2))
        f_pct = tk.Frame(cuerpo, bg=C.superficie)
        f_pct.pack(fill="x")
        v_pct = tk.StringVar(value=f"{r['porcentaje']:g}" if r else "15")
        # Ancho fijo: a 28pt y ocupando toda la fila, el campo quedaba de
        # media pantalla para escribir dos digitos.
        e_pct = tk.Entry(f_pct, textvariable=v_pct, font=F.subtitulo,
                         justify="center", width=7, bg=C.bg, fg=C.texto,
                         relief="solid", bd=1)
        e_pct.pack(side="left", ipady=5)
        lbl(f_pct, "%", variante="subtitulo", bg=C.superficie).pack(
            side="left", padx=(6, 0))

        lbl(cuerpo, "Días", variante="suave",
            bg=C.superficie).pack(anchor="w", pady=(12, 2))
        f_dias = tk.Frame(cuerpo, bg=C.superficie)
        f_dias.pack(fill="x")
        dias_act = ({int(x) for x in str(r["dias"]).split(",") if x.strip()}
                    if r else {0, 1, 2, 3, 4, 5})
        vars_dias = {}
        for i, nom in enumerate(DIAS_SEMANA):
            v = tk.BooleanVar(value=i in dias_act)
            vars_dias[i] = v
            tk.Checkbutton(f_dias, text=nom[:3], variable=v, bg=C.superficie,
                           fg=C.texto, font=F.normal, selectcolor=C.superficie,
                           activebackground=C.superficie).grid(
                row=0, column=i, padx=2)

        lbl(cuerpo, "Horario", variante="suave",
            bg=C.superficie).pack(anchor="w", pady=(12, 2))
        f_hs = tk.Frame(cuerpo, bg=C.superficie)
        f_hs.pack(fill="x")
        v_todo_dia = tk.BooleanVar(
            value=bool(r) and int(r["hora_desde"]) == int(r["hora_hasta"]))
        horas = [f"{i:02d}:00" for i in range(24)]
        lbl(f_hs, "desde", variante="suave", bg=C.superficie).pack(side="left")
        v_desde = tk.StringVar(value=f"{int(r['hora_desde']):02d}:00" if r else "18:00")
        cb_desde = ttk.Combobox(f_hs, textvariable=v_desde, values=horas,
                                width=7, state="readonly")
        cb_desde.pack(side="left", padx=6)
        lbl(f_hs, "hasta", variante="suave", bg=C.superficie).pack(side="left")
        v_hasta = tk.StringVar(value=f"{int(r['hora_hasta']):02d}:00" if r else "08:00")
        cb_hasta = ttk.Combobox(f_hs, textvariable=v_hasta, values=horas,
                                width=7, state="readonly")
        cb_hasta.pack(side="left", padx=6)

        def _toggle_todo_dia(*_a):
            """«Todo el día» es desde=hasta. Se ofrece como casilla porque
            poner 00:00 a 00:00 a mano no es evidente."""
            if v_todo_dia.get():
                v_desde.set("00:00"); v_hasta.set("00:00")
            for cb in (cb_desde, cb_hasta):
                cb.config(state="disabled" if v_todo_dia.get() else "readonly")
            # _hint se define mas abajo: se llama diferido para no
            # depender del orden de definicion.
            d.after(1, lambda: _hint())

        tk.Checkbutton(f_hs, text="todo el día", variable=v_todo_dia,
                       bg=C.superficie, fg=C.texto, font=F.normal,
                       selectcolor=C.superficie, activebackground=C.superficie,
                       command=_toggle_todo_dia).pack(side="left", padx=(12, 0))

        lbl_hint = tk.Label(cuerpo, text="", bg=C.superficie, fg=C.texto_suave,
                            font=F.pequeña, anchor="w", justify="left",
                            wraplength=460)
        lbl_hint.pack(fill="x", pady=(6, 0))

        lbl(cuerpo, "Se aplica a", variante="suave",
            bg=C.superficie).pack(anchor="w", pady=(12, 2))
        v_alcance = tk.StringVar(value=r["alcance"] if r else "todo")
        for val, txt in (("todo", "Todo el catálogo"),
                         ("categorias", "Solo algunas categorías")):
            tk.Radiobutton(cuerpo, text=txt, variable=v_alcance, value=val,
                           bg=C.superficie, fg=C.texto, font=F.normal,
                           anchor="w", selectcolor=C.superficie,
                           activebackground=C.superficie).pack(fill="x")

        cats = get_categorias()
        f_cats = tk.Frame(cuerpo, bg=C.superficie, highlightthickness=1,
                          highlightbackground=C.borde)
        f_cats.pack(fill="x", pady=(4, 0))
        cats_act = set(r["categoria_ids"]) if r else set()
        vars_cats = {}
        for i, cat in enumerate(cats):
            v = tk.BooleanVar(value=cat["id"] in cats_act)
            vars_cats[cat["id"]] = v
            tk.Checkbutton(f_cats, text=cat["nombre"][:22], variable=v,
                           bg=C.superficie, fg=C.texto, font=F.normal,
                           anchor="w", selectcolor=C.superficie,
                           activebackground=C.superficie).grid(
                row=i // 2, column=i % 2, sticky="w", padx=6, pady=1)

        def _hint(*_a):
            """Traduce la regla a una frase, para no equivocarse de horario."""
            try:
                hd = int(v_desde.get()[:2]); hh = int(v_hasta.get()[:2])
            except ValueError:
                return
            dias = [i for i, v in vars_dias.items() if v.get()]
            if not dias:
                lbl_hint.config(text="Elegí al menos un día.", fg=C.peligro)
                return
            nombres = self._texto_dias(dias)
            if hd == hh:
                txt = f"Rige {nombres.lower()}, todo el día."
            elif hd < hh:
                txt = f"Rige {nombres.lower()} de {hd:02d}:00 a {hh:02d}:00."
            else:
                txt = (f"Rige {nombres.lower()} desde las {hd:02d}:00 hasta "
                       f"las {hh:02d}:00 del día siguiente.")
            try:
                pct = float(v_pct.get().replace(",", "."))
                txt += f"  Un producto de $ 1.000 pasa a $ {1000*(1+pct/100):,.0f}."
            except ValueError:
                pass
            lbl_hint.config(text=txt, fg=C.texto_suave)

        for v in (v_desde, v_hasta, v_pct):
            v.trace_add("write", _hint)
        for v in vars_dias.values():
            v.trace_add("write", _hint)
        _hint()

        def guardar(_ev=None):
            nombre = v_nombre.get().strip()
            if not nombre:
                messagebox.showwarning("Recargo", "Poné un nombre.", parent=d)
                return
            try:
                pct = float(v_pct.get().replace(",", "."))
            except ValueError:
                messagebox.showwarning("Recargo", "El porcentaje no es un "
                                                  "número.", parent=d)
                return
            dias = [i for i, v in vars_dias.items() if v.get()]
            if not dias:
                messagebox.showwarning("Recargo", "Elegí al menos un día.",
                                       parent=d)
                return
            alcance = v_alcance.get()
            elegidas = [cid for cid, v in vars_cats.items() if v.get()]
            if alcance == "categorias" and not elegidas:
                messagebox.showwarning(
                    "Recargo", "Elegiste «solo algunas categorías» pero no "
                               "marcaste ninguna.", parent=d)
                return

            guardar_recargo(r["id"] if r else None, nombre, pct, dias,
                            int(v_desde.get()[:2]), int(v_hasta.get()[:2]),
                            alcance, elegidas, [],
                            activo=r["activo"] if r else True)
            d.destroy()
            self.refrescar()
            toast(self, "Recargo guardado")

        d.bind("<Return>", guardar)
        d.bind("<Escape>", lambda ev: d.destroy())

        btn(pie, "Guardar  (Enter)", variante="exito",
            comando=guardar).pack(side="left", padx=(18, 6))
        btn(pie, "Cancelar  (Esc)", variante="neutro",
            comando=d.destroy).pack(side="left")

        e_pct.focus_set()
        e_pct.select_range(0, "end")

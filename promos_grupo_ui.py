"""
promos_grupo_ui.py — Promos combinables: "3 gaseosas cualquiera".

Las promociones normales son por producto: "llevando 3 yerbas Taragüí".
Un grupo permite que el cliente mezcle — 1 Coca + 1 Sprite + 1 Fanta son
3 unidades y la promo aplica igual. Sin esto habría que cargar una promo
por cada combinación posible.
"""

import datetime
import tkinter as tk
from tkinter import ttk, messagebox

from styles import C, F, btn, lbl, tabla, toast
from repositorio import (guardar_promo_grupo, get_promo_grupos,
                         borrar_promo_grupo, get_productos, get_categorias)


COLS = [
    ("nombre", "Promo",        200, "w"),
    ("min",    "Desde",         70, "e"),
    ("precio", "Precio/desc.", 120, "e"),
    ("prods",  "Productos",     90, "e"),
    ("vig",    "Vigencia",     170, "w"),
    ("estado", "Estado",        90, "w"),
]


class PromosGrupoUI(ttk.Frame):

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._filas = []
        self._construir()
        self.after(120, self.refrescar)

    def _construir(self):
        cab = tk.Frame(self, bg=C.bg)
        cab.pack(fill="x", padx=12, pady=(10, 2))
        lbl(cab, "Promos combinables", variante="titulo").pack(side="left")
        self.lbl_cont = lbl(cab, "", variante="subtitulo")
        self.lbl_cont.pack(side="right")

        lbl(self, "El cliente puede mezclar productos del grupo: 1 Coca + "
                  "1 Sprite + 1 Fanta cuentan como 3 y la promo entra igual.",
            variante="suave").pack(anchor="w", padx=12)

        # El pie primero y anclado abajo, para que la tabla no lo empuje
        pie = tk.Frame(self, bg=C.bg)
        pie.pack(side="bottom", fill="x", padx=12, pady=(8, 10))
        btn(pie, "➕  Nueva promo", variante="exito",
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
        try:
            self._filas = get_promo_grupos()
        except Exception as exc:
            messagebox.showerror("Promos", f"No se pudo leer:\n{exc}",
                                 parent=self)
            return

        hoy = datetime.date.today().isoformat()
        self.tree.delete(*self.tree.get_children())
        for i, g in enumerate(self._filas):
            if g["tipo"] == "descuento_pct":
                precio = f"-{g['valor']:g}%"
            elif g["tipo"] == "descuento_monto":
                precio = f"-$ {g['valor']:,.2f} c/u"
            else:
                precio = f"$ {g['valor']:,.2f} c/u"

            vig = "siempre"
            if g["fecha_desde"] or g["fecha_hasta"]:
                vig = f"{g['fecha_desde'] or '…'} a {g['fecha_hasta'] or '…'}"

            vencida = bool(g["fecha_hasta"] and g["fecha_hasta"] < hoy)
            if not g["activa"]:
                estado, tag = "pausada", "pausada"
            elif vencida:
                estado, tag = "vencida", "vencida"
            else:
                estado, tag = "activa", ""

            self.tree.insert("", "end", iid=str(i),
                             tags=(tag,) if tag else (),
                             values=(g["nombre"][:30],
                                     f"{g['cantidad_minima']} u.", precio,
                                     len(g["productos"]), vig, estado))

        activas = sum(1 for g in self._filas
                      if g["activa"]
                      and not (g["fecha_hasta"] and g["fecha_hasta"] < hoy))
        self.lbl_cont.config(text=f"{len(self._filas)} promo(s) · "
                                  f"{activas} activa(s)")

    def _sel(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Promos", "Elegí una promo de la lista.",
                                parent=self)
            return None
        return self._filas[int(sel[0])]

    def _editar(self):
        g = self._sel()
        if g:
            self._dialogo(g)

    def _toggle(self):
        g = self._sel()
        if not g:
            return
        guardar_promo_grupo(g["id"], g["nombre"], g["cantidad_minima"],
                            g["tipo"], g["valor"],
                            [p["id"] for p in g["productos"]],
                            g["fecha_desde"], g["fecha_hasta"],
                            activa=not g["activa"])
        self.refrescar()

    def _eliminar(self):
        g = self._sel()
        if not g:
            return
        if messagebox.askyesno("Eliminar",
                               f"¿Eliminar «{g['nombre']}»?\n\n"
                               "Los productos no se tocan.", parent=self):
            borrar_promo_grupo(g["id"])
            self.refrescar()

    # ── Alta / edición ────────────────────────────────────────────────

    def _dialogo(self, g):
        d = tk.Toplevel(self)
        d.title("Editar promo" if g else "Nueva promo combinable")
        d.configure(bg=C.superficie)
        d.grab_set()
        w = 720
        h = min(660, d.winfo_screenheight() - 80)
        sw, sh = d.winfo_screenwidth(), d.winfo_screenheight()
        d.geometry(f"{w}x{h}+{(sw-w)//2}+{max(0,(sh-h)//2)}")

        lbl(d, "Promo combinable", variante="titulo",
            bg=C.superficie).pack(anchor="w", padx=18, pady=(16, 2))
        lbl(d, "Elegí los productos que se pueden mezclar y desde cuántas "
               "unidades entra la promo.", variante="suave",
            bg=C.superficie).pack(anchor="w", padx=18)

        pie = tk.Frame(d, bg=C.superficie)
        pie.pack(side="bottom", fill="x", pady=14)

        # ── Datos de la promo ─────────────────────────────────────────
        datos = tk.Frame(d, bg=C.superficie)
        datos.pack(fill="x", padx=18, pady=(12, 6))

        lbl(datos, "Nombre (lo ve el cajero)", variante="suave",
            bg=C.superficie).pack(anchor="w")
        v_nombre = tk.StringVar(value=g["nombre"] if g else "")
        e_nom = tk.Entry(datos, textvariable=v_nombre, font=F.normal, bg=C.bg,
                         fg=C.texto, relief="solid", bd=1)
        e_nom.pack(fill="x", ipady=4)

        f2 = tk.Frame(datos, bg=C.superficie)
        f2.pack(fill="x", pady=(10, 0))

        lbl(f2, "Desde", variante="suave", bg=C.superficie).pack(side="left")
        v_min = tk.StringVar(value=str(g["cantidad_minima"]) if g else "3")
        tk.Entry(f2, textvariable=v_min, font=F.subtitulo, width=5,
                 justify="center", bg=C.bg, fg=C.texto, relief="solid",
                 bd=1).pack(side="left", padx=6, ipady=3)
        lbl(f2, "unidades combinadas", variante="suave",
            bg=C.superficie).pack(side="left")

        lbl(f2, "     Precio:", variante="suave",
            bg=C.superficie).pack(side="left")
        _tipos = {"precio_fijo": "Precio fijo por unidad",
                  "descuento_pct": "Descuento %",
                  "descuento_monto": "Descuento en $ por unidad"}
        v_tipo = tk.StringVar(
            value=_tipos.get(g["tipo"] if g else "", "Precio fijo por unidad"))
        cb_tipo = ttk.Combobox(f2, textvariable=v_tipo, width=26,
                               state="readonly",
                               values=tuple(_tipos.values()))
        cb_tipo.pack(side="left", padx=6)
        v_valor = tk.StringVar(value=f"{g['valor']:g}" if g else "")
        tk.Entry(f2, textvariable=v_valor, font=F.subtitulo, width=10,
                 justify="center", bg=C.bg, fg=C.texto, relief="solid",
                 bd=1).pack(side="left", ipady=3)

        f3 = tk.Frame(datos, bg=C.superficie)
        f3.pack(fill="x", pady=(10, 0))
        lbl(f3, "Vigencia (opcional):", variante="suave",
            bg=C.superficie).pack(side="left")
        lbl(f3, "desde", variante="suave", bg=C.superficie).pack(side="left",
                                                                  padx=(8, 2))
        v_desde = tk.StringVar(value=(g and g["fecha_desde"]) or "")
        tk.Entry(f3, textvariable=v_desde, width=12, font=F.normal, bg=C.bg,
                 fg=C.texto, relief="solid", bd=1).pack(side="left")
        lbl(f3, "hasta", variante="suave", bg=C.superficie).pack(side="left",
                                                                  padx=(8, 2))
        v_hasta = tk.StringVar(value=(g and g["fecha_hasta"]) or "")
        tk.Entry(f3, textvariable=v_hasta, width=12, font=F.normal, bg=C.bg,
                 fg=C.texto, relief="solid", bd=1).pack(side="left")
        lbl(f3, "  (AAAA-MM-DD, vacío = siempre)", variante="suave",
            bg=C.superficie).pack(side="left")

        # ── Selección de productos ────────────────────────────────────
        barra = tk.Frame(d, bg=C.superficie)
        barra.pack(fill="x", padx=18, pady=(14, 4))
        lbl(barra, "Productos del grupo", variante="subtitulo",
            bg=C.superficie).pack(side="left")
        self._lbl_sel = lbl(barra, "", variante="suave", bg=C.superficie)
        self._lbl_sel.pack(side="right")

        filtro = tk.Frame(d, bg=C.superficie)
        filtro.pack(fill="x", padx=18, pady=(0, 6))
        v_busq = tk.StringVar()
        e_b = tk.Entry(filtro, textvariable=v_busq, width=24, font=F.normal,
                       bg=C.bg, fg=C.texto, relief="solid", bd=1)
        e_b.pack(side="left", ipady=3)
        cats = [{"id": None, "nombre": "Todas"}] + list(get_categorias())
        v_cat = tk.StringVar(value="Todas")
        cb = ttk.Combobox(filtro, textvariable=v_cat, width=20,
                          state="readonly",
                          values=[c["nombre"] for c in cats])
        cb.pack(side="left", padx=6)
        btn(filtro, "☑ Marcar los visibles", variante="neutro",
            comando=lambda: _marcar_visibles()).pack(side="left", padx=4)
        btn(filtro, "Desmarcar todo", variante="neutro",
            comando=lambda: _desmarcar()).pack(side="left")
        # Con el catalogo entero cargado hay que poder revisar QUE quedo
        # elegido sin scrollear todo.
        v_solo_marcados = tk.BooleanVar(value=False)
        tk.Checkbutton(filtro, text="Ver solo los elegidos",
                       variable=v_solo_marcados, bg=C.superficie,
                       fg=C.texto, font=F.normal, selectcolor=C.superficie,
                       activebackground=C.superficie).pack(side="left",
                                                            padx=(12, 0))

        cols = [("sel", "", 34, "center"), ("desc", "Producto", 300, "w"),
                ("cat", "Categoría", 140, "w"), ("precio", "Precio", 100, "e")]
        frame_t, tv = tabla(d, cols, altura=10)
        frame_t.pack(fill="both", expand=True, padx=18)

        marcados = {p["id"] for p in g["productos"]} if g else set()
        filas = []

        def cargar(*_a):
            cat_id = cats[[c["nombre"] for c in cats].index(v_cat.get())]["id"]
            filas.clear()
            filas.extend(get_productos(filtro=v_busq.get().strip(),
                                       categoria_id=cat_id))
            if v_solo_marcados.get():
                filas[:] = [p for p in filas if p["id"] in marcados]
            tv.delete(*tv.get_children())
            for i, p in enumerate(filas):
                tv.insert("", "end", iid=str(i), values=(
                    "☑" if p["id"] in marcados else "☐",
                    p["descripcion"][:44], p.get("categoria") or "—",
                    f"$ {p['precio_base']:,.2f}"))
            _contar()

        def _contar():
            n = len(marcados)
            self._lbl_sel.config(
                text=(f"{n} producto(s) en el grupo"
                      if n >= 2
                      else "Elegí al menos 2 productos"))

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
            _contar()

        def _marcar_visibles():
            for p in filas:
                marcados.add(p["id"])
            cargar()

        def _desmarcar():
            marcados.clear()
            cargar()

        tv.bind("<Button-1>", _click)
        cb.bind("<<ComboboxSelected>>", cargar)
        # trace en vez de KeyRelease: el bind se dispara ANTES de que la
        # tecla entre en la variable, asi que la lista quedaba una letra
        # atras — se veian 9 productos y al marcar aparecian 4.
        v_busq.trace_add("write", lambda *a: cargar())
        v_solo_marcados.trace_add("write", lambda *a: cargar())

        def guardar(_ev=None):
            nombre = v_nombre.get().strip()
            if not nombre:
                messagebox.showwarning("Promo", "Poné un nombre.", parent=d)
                return
            try:
                minimo = int(v_min.get())
                valor = float(v_valor.get().replace(",", "."))
            except ValueError:
                messagebox.showwarning("Promo", "La cantidad o el precio no "
                                                "son números.", parent=d)
                return
            tipo = {v: k for k, v in _tipos.items()}.get(v_tipo.get(),
                                                          "precio_fijo")
            if tipo == "descuento_pct" and not (0 < valor < 100):
                messagebox.showwarning("Promo", "El descuento tiene que "
                                                "estar entre 1 y 99%.",
                                       parent=d)
                return
            if tipo == "precio_fijo" and len(marcados) > 1:
                # Un precio fijo unico sobre productos de distinto valor
                # deja sin descuento a lo barato: conviene avisarlo antes
                # de que salga mal en la caja.
                from repositorio import get_productos as _gp
                precios = [p["precio_base"] for p in _gp()
                           if p["id"] in marcados and p["precio_base"]]
                if precios and (max(precios) - min(precios)) > max(precios) * 0.3:
                    if not messagebox.askyesno(
                            "Precio fijo",
                            f"Los productos del grupo van de "
                            f"$ {min(precios):,.0f} a $ {max(precios):,.0f}.\n\n"
                            f"Con precio fijo, los más baratos no van a "
                            f"tener descuento.\n\n"
                            f"¿Preferís «Descuento en $ por unidad»?\n\n"
                            f"Sí = cambio el tipo   ·   No = dejo precio fijo",
                            parent=d, default="yes"):
                        pass
                    else:
                        v_tipo.set(_tipos["descuento_monto"])
                        return
            try:
                guardar_promo_grupo(
                    g["id"] if g else None, nombre, minimo, tipo, valor,
                    list(marcados), v_desde.get().strip() or None,
                    v_hasta.get().strip() or None,
                    activa=g["activa"] if g else True)
            except ValueError as exc:
                messagebox.showwarning("Promo", str(exc), parent=d)
                return
            except Exception as exc:
                messagebox.showerror("Promo", str(exc), parent=d)
                return
            d.destroy()
            self.refrescar()
            toast(self, f"«{nombre}» guardada con {len(marcados)} productos")

        d.bind("<Escape>", lambda ev: d.destroy())
        btn(pie, "Guardar", variante="exito",
            comando=guardar).pack(side="left", padx=(18, 6))
        btn(pie, "Cancelar  (Esc)", variante="neutro",
            comando=d.destroy).pack(side="left")

        cargar()
        e_nom.focus_set()

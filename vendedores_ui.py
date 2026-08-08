"""
vendedores_ui.py — Vendedores y comisiones del catálogo web TPV v2.0
Cada vendedor tiene un link propio (?v=codigo) que marca el precio
con su comisión (calculada sobre el costo) y le da acceso a un panel
propio (usuario/contraseña) donde ve sus pedidos y comisiones.
"""

import tkinter as tk
from tkinter import ttk, messagebox
from styles import C, F, btn, lbl, card, tabla, toast, header_seccion
from repositorio import (get_vendedores, get_vendedor_por_id, guardar_vendedor,
                         toggle_vendedor, eliminar_vendedor)

COLS_VENDEDORES = [
    ("codigo",   "Código",        90,  "w"),
    ("nombre",   "Nombre",        160, "w"),
    ("usuario",  "Usuario",       110, "w"),
    ("telefono", "Teléfono",      120, "w"),
    ("comision", "Comisión %",    80,  "e"),
    ("cobro",    "Cobra",         80,  "center"),
    ("activo",   "Activo",        60,  "center"),
]

COLS_RESUMEN = [
    ("vendedor",  "Vendedor",       140, "w"),
    ("pedidos",   "Pedidos",         70, "e"),
    ("total",     "Total vendido",  110, "e"),
    ("comision",  "Comisión",       100, "e"),
]


def _centrar(d, w, h):
    sw = d.winfo_screenwidth()
    sh = d.winfo_screenheight()
    margen = 40
    w = min(w, sw - 20)
    h = min(h, sh - margen)
    x = max(0, (sw - w) // 2)
    y = max(0, (sh - h) // 2)
    d.geometry(f"{w}x{h}+{x}+{y}")


class VendedoresUI(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._vend_sel_id = None
        self._build()
        self._refrescar()

    # ── Layout ────────────────────────────────────────────────────────────

    def _build(self):
        header_seccion(self, "Vendedores y comisiones",
            "Cada vendedor tiene un link propio (?v=código) — la comisión "
            "se calcula sobre el costo, arriba de tu precio normal.").pack(
            fill="x", padx=12, pady=(8,0))

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=12, pady=12)

        f_vend = ttk.Frame(nb)
        f_res  = ttk.Frame(nb)
        nb.add(f_vend, text="  Vendedores  ")
        nb.add(f_res,  text="  Pedidos y comisiones  ")

        self._build_vendedores(f_vend)
        self._build_resumen(f_res)

    def _build_vendedores(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)

        bar = tk.Frame(parent, bg=C.bg)
        bar.grid(row=0, column=0, sticky="ew", pady=(0,8))
        btn(bar, "➕  Nuevo vendedor", variante="exito",
            comando=self._nuevo_vendedor).pack(side="left", padx=(0,6))
        btn(bar, "✏️  Editar", variante="neutro",
            comando=self._editar_vendedor).pack(side="left", padx=(0,6))
        btn(bar, "🔁  Activar/Desactivar", variante="neutro",
            comando=self._toggle_vendedor).pack(side="left", padx=(0,6))
        btn(bar, "🗑️  Eliminar", variante="peligro",
            comando=self._eliminar_vendedor).pack(side="left", padx=(0,6))
        btn(bar, "🔗  Copiar link", variante="neutro",
            comando=self._copiar_link).pack(side="left", padx=(0,6))
        btn(bar, "☁️  Sincronizar al Sheet", variante="primario",
            comando=self._sincronizar).pack(side="right")

        frame_t, self.tree_v = tabla(parent, COLS_VENDEDORES)
        frame_t.grid(row=1, column=0, sticky="nsew")
        self.tree_v.bind("<<TreeviewSelect>>", self._on_sel)
        self.tree_v.bind("<Double-1>", lambda e: self._editar_vendedor())

    def _build_resumen(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)

        bar = tk.Frame(parent, bg=C.bg)
        bar.grid(row=0, column=0, sticky="ew", pady=(0,8))
        lbl(bar, "Trae los pedidos registrados desde la página web y suma "
                "comisiones por vendedor.", variante="suave").pack(side="left")
        btn(bar, "🔄  Traer pedidos y comisiones", variante="primario",
            comando=self._traer_resumen).pack(side="right")

        frame_t, self.tree_r = tabla(parent, COLS_RESUMEN)
        frame_t.grid(row=1, column=0, sticky="nsew")

        self.lbl_resumen_estado = lbl(parent, "", variante="suave")
        self.lbl_resumen_estado.grid(row=2, column=0, sticky="w", pady=(6,0))

    # ── Lógica — Vendedores ─────────────────────────────────────────────────

    def _refrescar(self):
        for r in self.tree_v.get_children():
            self.tree_v.delete(r)
        for v in get_vendedores():
            self.tree_v.insert("", "end", iid=str(v["id"]), values=(
                v["codigo"],
                v["nombre"],
                v["usuario"],
                v["telefono"] or "—",
                f"{v['comision_pct']:.1f}%",
                "Vendedor" if v["modo_cobro"] == "vendedor" else "Negocio",
                "Sí" if v["activo"] else "No",
            ), tags=("activo",) if v["activo"] else ("inactivo",))
        self.tree_v.tag_configure("activo",   foreground=C.exito)
        self.tree_v.tag_configure("inactivo", foreground=C.texto_suave)

    def _on_sel(self, event=None):
        sel = self.tree_v.selection()
        self._vend_sel_id = int(sel[0]) if sel else None

    def _nuevo_vendedor(self):
        self._dialogo_vendedor()

    def _editar_vendedor(self):
        if not self._vend_sel_id:
            messagebox.showinfo("Atención", "Seleccioná un vendedor.", parent=self)
            return
        v = get_vendedor_por_id(self._vend_sel_id)
        if v:
            self._dialogo_vendedor(v)

    def _toggle_vendedor(self):
        if not self._vend_sel_id:
            messagebox.showinfo("Atención", "Seleccioná un vendedor.", parent=self)
            return
        v = get_vendedor_por_id(self._vend_sel_id)
        if v:
            toggle_vendedor(self._vend_sel_id, 0 if v["activo"] else 1)
            self._sincronizar(silencioso=True)
            self._refrescar()

    def _eliminar_vendedor(self):
        if not self._vend_sel_id:
            messagebox.showinfo("Atención", "Seleccioná un vendedor.", parent=self)
            return
        v = get_vendedor_por_id(self._vend_sel_id)
        if not v:
            return
        if messagebox.askyesno(
                "Eliminar",
                f"¿Eliminar a {v['nombre']}? Su link va a dejar de funcionar.\n"
                f"(Los pedidos que ya se registraron con él quedan igual, "
                f"esto no los borra.)", parent=self):
            eliminar_vendedor(self._vend_sel_id)
            self._vend_sel_id = None
            toast(self, "Vendedor eliminado")
            self._sincronizar(silencioso=True)
            self._refrescar()

    def _copiar_link(self):
        if not self._vend_sel_id:
            messagebox.showinfo("Atención", "Seleccioná un vendedor.", parent=self)
            return
        v = get_vendedor_por_id(self._vend_sel_id)
        if not v:
            return
        from config import cfg
        url = (cfg().get("catalogo_web_url", "") or "").strip()
        if not url:
            messagebox.showwarning(
                "Atención",
                "Primero cargá la URL del catálogo web en Config.", parent=self)
            return
        link = f"{url}?v={v['codigo']}"
        self.clipboard_clear()
        self.clipboard_append(link)
        toast(self, f"Link de {v['nombre']} copiado")

    def _dialogo_vendedor(self, vend=None):
        d = tk.Toplevel(self)
        d.title("Editar vendedor" if vend else "Nuevo vendedor")
        _centrar(d, 420, 480)
        d.resizable(True, True)
        d.configure(bg=C.superficie)
        d.grab_set()

        s = tk.Frame(d, bg=C.superficie)
        s.pack(fill="both", expand=True)

        campos = [
            ("Código (para el link, sin espacios)", "entry_v_codigo", ""),
            ("Nombre",                                "entry_v_nombre", ""),
            ("Usuario (para su panel)",               "entry_v_usuario", ""),
            ("Contraseña" + (" (dejar vacío = no cambiar)" if vend else ""),
                                                       "entry_v_pass", ""),
            ("Teléfono (solo si cobra él directo)",    "entry_v_tel", ""),
            ("Comisión % sobre el costo",              "entry_v_comision", "10"),
        ]
        for label, attr, default in campos:
            lbl(s, label, variante="suave", bg=C.superficie).pack(
                padx=20, anchor="w", pady=(8,0))
            es_pass = attr == "entry_v_pass"
            e = tk.Entry(s, font=F.normal, bg=C.superficie, fg=C.texto,
                         insertbackground=C.primario, relief="solid", bd=1,
                         show="•" if es_pass else "")
            if vend and not es_pass:
                if attr == "entry_v_codigo":  e.insert(0, vend["codigo"])
                elif attr == "entry_v_nombre": e.insert(0, vend["nombre"])
                elif attr == "entry_v_usuario": e.insert(0, vend["usuario"])
                elif attr == "entry_v_tel":    e.insert(0, vend["telefono"] or "")
                elif attr == "entry_v_comision": e.insert(0, f"{vend['comision_pct']:.1f}")
            elif not vend:
                e.insert(0, default)
            e.pack(fill="x", padx=20, ipady=5, pady=(2,0))
            setattr(self, attr, e)

        lbl(s, "Cómo cobra el cliente final *", variante="suave",
            bg=C.superficie).pack(padx=20, anchor="w", pady=(10,0))
        modo = tk.StringVar(value=(vend["modo_cobro"] if vend else "negocio"))
        f_modo = tk.Frame(s, bg=C.superficie)
        f_modo.pack(fill="x", padx=20, pady=(2,0))
        tk.Radiobutton(f_modo, text="Te paga a vos (como siempre) — vos le liquidás la comisión aparte",
                      variable=modo, value="negocio", bg=C.superficie,
                      font=F.normal, anchor="w", justify="left",
                      wraplength=360).pack(fill="x", anchor="w")
        tk.Radiobutton(f_modo, text="Cobra él directo (hace falta el teléfono de arriba)",
                      variable=modo, value="vendedor", bg=C.superficie,
                      font=F.normal, anchor="w", justify="left",
                      wraplength=360).pack(fill="x", anchor="w")

        lbl(s, "El precio que ve el cliente en el link de este vendedor "
              "es tu precio normal + (costo × comisión%). El cliente paga "
              "esa diferencia — no sale de tu margen.",
            variante="suave", bg=C.superficie, wraplength=380,
            justify="left").pack(padx=20, anchor="w", pady=(10,0))

        def guardar(event=None):
            codigo = self.entry_v_codigo.get().strip()
            nombre = self.entry_v_nombre.get().strip()
            usuario = self.entry_v_usuario.get().strip()
            password = self.entry_v_pass.get()
            telefono = self.entry_v_tel.get().strip()
            try:
                comision = float(self.entry_v_comision.get().replace(",", "."))
                if comision < 0: raise ValueError
            except ValueError:
                messagebox.showwarning("Error", "Comisión inválida.", parent=d)
                return
            if modo.get() == "vendedor" and not telefono:
                messagebox.showwarning(
                    "Error",
                    "Si cobra él directo, hace falta su teléfono.", parent=d)
                return

            ok, error = guardar_vendedor(
                vend["id"] if vend else None,
                codigo, nombre, usuario, password,
                telefono, comision, modo.get())
            if not ok:
                messagebox.showwarning("Error", error, parent=d)
                return

            d.destroy()
            toast(self, "Vendedor guardado")
            self._sincronizar(silencioso=True)
            self._refrescar()

        btn(s, "💾  Guardar", variante="exito", comando=guardar).pack(pady=16)

    def _sincronizar(self, silencioso=False):
        import catalogo_web
        ok, msg = catalogo_web.sincronizar_vendedores()
        if not silencioso:
            if ok:
                toast(self, msg)
            else:
                messagebox.showwarning("Sincronización", msg, parent=self)

    # ── Lógica — Resumen de pedidos y comisiones ────────────────────────────

    def _traer_resumen(self):
        for r in self.tree_r.get_children():
            self.tree_r.delete(r)
        self.lbl_resumen_estado.config(text="Buscando...", fg=C.texto_suave)
        self.update_idletasks()

        import catalogo_web
        ok, datos_o_error = catalogo_web.obtener_resumen_vendedores()
        if not ok:
            self.lbl_resumen_estado.config(text=datos_o_error, fg=C.peligro)
            return

        if not datos_o_error:
            self.lbl_resumen_estado.config(
                text="Todavía no hay pedidos registrados con vendedor.",
                fg=C.texto_suave)
            return

        total_com = 0.0
        for fila in datos_o_error:
            self.tree_r.insert("", "end", values=(
                fila["nombre"],
                fila["cantidad_pedidos"],
                f"$ {fila['total']:,.2f}",
                f"$ {fila['comision']:,.2f}",
            ))
            total_com += fila["comision"]
        self.lbl_resumen_estado.config(
            text=f"Comisiones totales pendientes de liquidar: $ {total_com:,.2f}",
            fg=C.exito)

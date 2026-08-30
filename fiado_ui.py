"""
fiado_ui.py — Módulo de Fiado TPV v2.0

Flujo en venta:
  1. Cajero selecciona "Fiado" → se abre dialogo_fiado()
  2. Ingresa DNI del cliente (scanner o teclado)
  3. Si no existe → formulario de alta (requiere clave de responsable)
  4. Si existe → muestra saldo y disponible
  5. Valida que no supere el tope antes de cobrar

FiadoUI: pantalla de gestión completa (clientes, cuentas, pagos)
  Accesible desde el tab Caja → sub-tab Fiado
  Los pagos y cambios de tope requieren clave de responsable.
"""

import tkinter as tk
from tkinter import ttk, messagebox
from styles import C, F, btn, lbl, card, tabla, toast, header_seccion
from repositorio import (get_cliente_por_dni, crear_cliente, actualizar_cliente,
                         get_todos_clientes, get_movimientos_cliente,
                         registrar_pago_cuenta_corriente,
                         buscar_clientes_por_nombre, get_detalle_venta)

# Clave del responsable — en producción esto debería estar en DB con hash
# Por ahora es configurable acá
CLAVE_RESPONSABLE = "1234"

COLS_CLIENTES = [
    ("dni",        "DNI",         90,  "w"),
    ("nombre",     "Nombre",     180,  "w"),
    ("telefono",   "Telefono",   100,  "w"),
    ("tope",       "Tope $",      90,  "e"),
    ("saldo",      "Saldo $",     90,  "e"),
    ("disponible", "Disponible",  90,  "e"),
]

COLS_MOVS = [
    ("tipo",    "Tipo",     70,  "w"),
    ("monto",   "Monto",    90,  "e"),
    ("concepto","Concepto", 200, "w"),
    ("autori",  "Autorizo", 100, "w"),
    ("fecha",   "Fecha",    120, "w"),
]


# ─────────────────────────────────────────────────────────────────────────────
# AUTORIZACIÓN
# ─────────────────────────────────────────────────────────────────────────────

def pedir_autorizacion(parent, mensaje="Esta accion requiere autorizacion del responsable.") -> str | None:
    """
    Muestra diálogo de clave del responsable.
    Retorna el nombre del responsable si la clave es correcta, None si cancela.
    """
    d = tk.Toplevel(parent)
    d.title("Autorizacion requerida")
    d.resizable(False, False)
    d.configure(bg=C.superficie)
    d.grab_set()
    w, h = 360, 220
    sw, sh = d.winfo_screenwidth(), d.winfo_screenheight()
    d.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

    # Icono de advertencia visual
    tk.Label(d, text="Autorizacion requerida", font=F.titulo,
             bg=C.advertencia, fg=C.blanco,
             pady=10).pack(fill="x")

    lbl(d, mensaje, variante="suave", bg=C.superficie,
        wraplength=320).pack(pady=(12, 4), padx=20)

    lbl(d, "Nombre del responsable:", variante="suave",
        bg=C.superficie).pack(padx=20, anchor="w")
    e_nombre = tk.Entry(d, font=F.normal, bg=C.superficie, fg=C.texto,
                         relief="solid", bd=1)
    e_nombre.pack(fill="x", padx=20, ipady=5, pady=(2, 6))
    e_nombre.focus_set()

    lbl(d, "Clave:", variante="suave", bg=C.superficie).pack(padx=20, anchor="w")
    e_clave = tk.Entry(d, font=F.normal, bg=C.superficie, fg=C.texto,
                        relief="solid", bd=1, show="*")
    e_clave.pack(fill="x", padx=20, ipady=5, pady=(2, 8))

    result = [None]

    def confirmar(event=None):
        nombre = e_nombre.get().strip()
        clave  = e_clave.get().strip()
        if not nombre:
            messagebox.showwarning("Error", "Ingresa el nombre del responsable.", parent=d)
            return
        if clave != CLAVE_RESPONSABLE:
            messagebox.showerror("Clave incorrecta",
                "La clave ingresada no es correcta.", parent=d)
            e_clave.delete(0, "end")
            e_clave.focus_set()
            return
        result[0] = nombre
        d.destroy()

    e_clave.bind("<Return>", confirmar)
    btn(d, "Autorizar", variante="exito", comando=confirmar).pack(pady=(0, 12))

    parent.wait_window(d)
    return result[0]


# ─────────────────────────────────────────────────────────────────────────────
# DIÁLOGO DE FIADO EN VENTA
# ─────────────────────────────────────────────────────────────────────────────

def dialogo_fiado(parent) -> dict | None:
    """
    Diálogo que se abre al seleccionar "Fiado" en venta.
    Retorna dict del cliente o None si cancela.
    """
    d = tk.Toplevel(parent)
    d.title("Cuenta Corriente")
    d.resizable(True, True)
    d.configure(bg=C.superficie)
    d.grab_set()
    w, h = 420, 420
    sw, sh = d.winfo_screenwidth(), d.winfo_screenheight()
    d.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

    lbl(d, "Cuenta Corriente", variante="titulo",
        bg=C.superficie).pack(pady=(20, 4), padx=20, anchor="w")
    lbl(d, "Ingresa el DNI del cliente (o escanea el codigo del DNI)",
        variante="suave", bg=C.superficie).pack(padx=20, anchor="w")

    # Campo DNI
    f_dni = tk.Frame(d, bg=C.superficie)
    f_dni.pack(fill="x", padx=20, pady=(10, 0))
    lbl(f_dni, "DNI:", bg=C.superficie).pack(side="left")
    e_dni = tk.Entry(f_dni, font=("Segoe UI", 14), width=15,
                      bg=C.superficie, fg=C.texto,
                      insertbackground=C.primario,
                      relief="solid", bd=1, justify="center")
    e_dni.pack(side="left", padx=8, ipady=6)
    e_dni.focus_set()

    # O buscar por nombre (si no se tiene el DNI a mano)
    lbl(d, "— o por nombre —", variante="suave",
        bg=C.superficie).pack(padx=20, anchor="w", pady=(12, 0))
    f_nombre = tk.Frame(d, bg=C.superficie)
    f_nombre.pack(fill="x", padx=20, pady=(4, 0))
    e_nombre = tk.Entry(f_nombre, font=("Segoe UI", 12),
                         bg=C.superficie, fg=C.texto,
                         insertbackground=C.primario, relief="solid", bd=1)
    e_nombre.pack(side="left", fill="x", expand=True, ipady=5)

    # Lista de coincidencias por nombre (oculta hasta que haga falta)
    frame_lista = tk.Frame(d, bg=C.superficie)
    lista_nombres = tk.Listbox(frame_lista, font=F.normal, height=4,
                                bg=C.superficie, fg=C.texto,
                                relief="solid", bd=1, activestyle="none")
    lista_nombres.pack(fill="both", expand=True)
    coincidencias = []

    # Panel de resultado
    frame_result = tk.Frame(d, bg=C.acento)
    lbl_result = lbl(frame_result, "", variante="suave",
                      bg=C.acento, fg=C.primario, padx=12, pady=8,
                      wraplength=360)
    lbl_result.pack(anchor="w")

    result = [None]

    def _mostrar_cliente(cliente):
        frame_lista.pack_forget()
        saldo = cliente["saldo_actual"]
        tope  = cliente["tope_credito"]
        disp  = tope - saldo
        color = C.exito if disp > 0 else C.peligro
        lbl_result.config(
            text=f"{cliente['nombre']}\n"
                 f"Saldo: $ {saldo:,.2f}  |  "
                 f"Tope: $ {tope:,.2f}  |  "
                 f"Disponible: $ {disp:,.2f}",
            fg=color)
        frame_result.pack(fill="x", padx=20, pady=(8, 0))
        result[0] = cliente

    def buscar(event=None):
        dni = e_dni.get().strip().replace(".", "").replace("-", "")
        if not dni:
            return
        frame_lista.pack_forget()
        cliente = get_cliente_por_dni(dni)
        if cliente:
            _mostrar_cliente(cliente)
        else:
            # No existe — pedir autorización para dar de alta
            lbl_result.config(
                text=f"DNI {dni} no registrado. Se abrira el alta de cliente.",
                fg=C.advertencia)
            frame_result.pack(fill="x", padx=20, pady=(8, 0))
            d.after(800, lambda: _alta_cliente(d, dni, result))

    def buscar_por_nombre(event=None):
        texto = e_nombre.get().strip()
        if not texto:
            return
        frame_result.pack_forget()
        coincidencias.clear()
        coincidencias.extend(buscar_clientes_por_nombre(texto))
        lista_nombres.delete(0, "end")
        if not coincidencias:
            lista_nombres.insert("end", "  Sin resultados")
            frame_lista.pack(fill="x", padx=20, pady=(6, 0))
            return
        for c in coincidencias:
            saldo = c["saldo_actual"]
            lista_nombres.insert(
                "end", f"  {c['nombre']}  (DNI {c['dni']} — saldo $ {saldo:,.2f})")
        frame_lista.pack(fill="x", padx=20, pady=(6, 0))

    def _elegir_de_lista(event=None):
        sel = lista_nombres.curselection()
        if not sel or not coincidencias:
            return
        idx = sel[0]
        if idx < len(coincidencias):
            _mostrar_cliente(coincidencias[idx])

    lista_nombres.bind("<<ListboxSelect>>", _elegir_de_lista)
    lista_nombres.bind("<Double-1>", lambda e: (confirmar() if result[0] else None))

    def _alta_cliente(parent_d, dni, result_ref):
        responsable = pedir_autorizacion(
            parent_d,
            "Dar de alta un cliente nuevo requiere autorizacion.")
        if not responsable:
            return
        _dialogo_alta(parent_d, dni, responsable, result_ref)

    def confirmar():
        if result[0]:
            d.destroy()
        else:
            buscar()

    e_dni.bind("<Return>", buscar)
    e_nombre.bind("<Return>", buscar_por_nombre)
    btn(f_nombre, "Buscar", variante="primario",
        comando=buscar_por_nombre).pack(side="left", padx=(8,0))

    frame_btns = tk.Frame(d, bg=C.superficie)
    frame_btns.pack(pady=(16, 16), side="bottom")
    btn(frame_btns, "Buscar (DNI)", variante="primario", comando=buscar).pack(side="left", padx=4)
    btn(frame_btns, "Confirmar", variante="exito",    comando=confirmar).pack(side="left", padx=4)
    btn(frame_btns, "Cancelar",  variante="neutro",
        comando=d.destroy).pack(side="left", padx=4)

    parent.wait_window(d)
    return result[0]


def _dialogo_alta(parent, dni, responsable, result_ref,
                  nombre_inicial=""):
    """Formulario de alta de cliente nuevo."""
    d = tk.Toplevel(parent)
    d.title("Alta de cliente")
    d.resizable(True, True)
    d.configure(bg=C.superficie)
    d.grab_set()
    w, h = 380, 280
    sw, sh = d.winfo_screenwidth(), d.winfo_screenheight()
    d.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

    lbl(d, "Alta de cliente nuevo", variante="titulo",
        bg=C.superficie).pack(pady=(16, 4), padx=20, anchor="w")
    lbl(d, f"Autorizado por: {responsable}", variante="suave",
        bg=C.superficie, fg=C.exito).pack(padx=20, anchor="w", pady=(0, 8))

    campos = [
        ("Nombre completo *", "e_nombre", ""),
        ("Telefono",          "e_tel",    ""),
        ("Tope de credito $ *","e_tope",  "0"),
    ]
    entries = {}
    for label, key, default in campos:
        lbl(d, label, variante="suave", bg=C.superficie).pack(padx=20, anchor="w", pady=(4,0))
        e = tk.Entry(d, font=F.normal, bg=C.superficie, fg=C.texto,
                      insertbackground=C.primario, relief="solid", bd=1)
        e.insert(0, default)
        e.pack(fill="x", padx=20, ipady=5, pady=(2,0))
        entries[key] = e

    # Pre-cargar DNI
    lbl(d, f"DNI: {dni}", variante="suave", bg=C.superficie,
        fg=C.texto_suave).pack(padx=20, anchor="w", pady=(8, 0))

    # El nombre viene precargado si se lo escribio en el buscador: no
    # tiene sentido hacerlo tipear dos veces con el cliente esperando.
    if nombre_inicial:
        entries["e_nombre"].delete(0, "end")
        entries["e_nombre"].insert(0, nombre_inicial)

    entries["e_nombre"].focus_set()
    entries["e_nombre"].select_range(0, "end")

    def guardar(event=None):
        nombre = entries["e_nombre"].get().strip()
        tel    = entries["e_tel"].get().strip()
        try:
            tope = float(entries["e_tope"].get().replace(",", "."))
            if tope < 0: raise ValueError
        except ValueError:
            messagebox.showwarning("Error", "Tope invalido.", parent=d)
            return
        if not nombre:
            messagebox.showwarning("Error", "Ingresa el nombre.", parent=d)
            return
        cliente = crear_cliente(dni, nombre, tel, tope)
        result_ref[0] = cliente
        d.destroy()

    btn(d, "Guardar cliente", variante="exito", comando=guardar).pack(
        fill="x", padx=20, pady=12)


# ─────────────────────────────────────────────────────────────────────────────
# PANTALLA DE GESTIÓN DE FIADO
# ─────────────────────────────────────────────────────────────────────────────

class FiadoUI(ttk.Frame):
    """
    Pantalla de gestión completa de cuentas fiadas.
    Muestra todos los clientes, su saldo y movimientos.
    Los pagos y cambios de tope requieren clave de responsable.
    """

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._cliente_sel = None
        self._movs_venta_id = {}
        self._build()
        self.refrescar()

    def _build(self):
        header_seccion(
            self, "Cuentas Corrientes",
            "Gestion de credito de clientes — pagos y cambios de tope requieren autorizacion"
        ).pack(fill="x", padx=12, pady=(8, 4))

        # Contenedor separado para evitar conflicto pack/grid
        self._cont = tk.Frame(self, bg=C.bg)
        self._cont.pack(fill="both", expand=True)
        self._cont.columnconfigure(0, weight=2)
        self._cont.columnconfigure(1, weight=1)
        self._cont.rowconfigure(0, weight=1)

        # ── Tabla de clientes (con buscador arriba) ─────────────────────────
        f_izq = tk.Frame(self._cont, bg=C.bg)
        f_izq.grid(row=0, column=0, sticky="nsew", padx=(12, 6), pady=(0, 12))
        f_izq.columnconfigure(0, weight=1)
        f_izq.rowconfigure(1, weight=1)

        f_buscar = tk.Frame(f_izq, bg=C.bg)
        f_buscar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        lbl(f_buscar, "Buscar:").pack(side="left", padx=(0, 6))
        self.entry_buscar_cli = tk.Entry(f_buscar, font=F.normal,
                                          bg=C.superficie, fg=C.texto,
                                          insertbackground=C.primario,
                                          relief="solid", bd=1)
        self.entry_buscar_cli.pack(side="left", fill="x", expand=True, ipady=4)
        self.entry_buscar_cli.bind("<KeyRelease>", lambda e: self._refrescar_clientes())
        lbl(f_buscar, "por DNI o nombre", variante="suave").pack(side="left", padx=(6, 0))

        frame_t, self.tree_cli = tabla(f_izq, COLS_CLIENTES)
        frame_t.grid(row=1, column=0, sticky="nsew")
        self.tree_cli.bind("<<TreeviewSelect>>", self._on_sel_cliente)
        self.tree_cli.tag_configure("deuda",    foreground=C.peligro)
        self.tree_cli.tag_configure("sin_deuda",foreground=C.exito)
        self.tree_cli.tag_configure("limite",   foreground=C.advertencia)

        # ── Panel derecho ─────────────────────────────────────────────────────
        der = tk.Frame(self._cont, bg=C.bg)
        der.grid(row=0, column=1, sticky="nsew", padx=(6, 12), pady=(0, 12))
        der.columnconfigure(0, weight=1)
        # La tabla de movimientos (fila 2) es la que se estira.
        # Antes el rotulo "Movimientos del cliente" estaba en la fila 0,
        # la misma que la tarjeta de Acciones: se dibujaban uno encima
        # del otro y la tabla quedaba aplastada contra el borde.
        der.rowconfigure(2, weight=1)

        # Acciones
        ac = card(der)
        ac.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ac.columnconfigure(0, weight=1)

        lbl(ac, "Acciones", variante="subtitulo",
            bg=C.superficie).grid(row=0, column=0, sticky="w", padx=16, pady=(12, 6))

        btn(ac, "Registrar pago", variante="exito",
            comando=self._registrar_pago).grid(
            row=1, column=0, sticky="ew", padx=16, pady=4)
        btn(ac, "Editar cliente / tope", variante="primario",
            comando=self._editar_cliente).grid(
            row=2, column=0, sticky="ew", padx=16, pady=4)
        btn(ac, "Ver movimientos", variante="neutro",
            comando=self._ver_movimientos).grid(
            row=3, column=0, sticky="ew", padx=16, pady=4)
        btn(ac, "📱 Recordatorio WhatsApp", variante="neutro",
            comando=self._recordatorio_whatsapp).grid(
            row=4, column=0, sticky="ew", padx=16, pady=4)
        btn(ac, "📱 Recordatorios masivos", variante="neutro",
            comando=self._recordatorios_masivos).grid(
            row=5, column=0, sticky="ew", padx=16, pady=(4, 16))

        # Movimientos del cliente seleccionado
        lbl(der, "Movimientos del cliente", variante="subtitulo").grid(
            row=1, column=0, sticky="w", pady=(8, 4))

        frame_m, self.tree_movs = tabla(der, COLS_MOVS, altura=10)
        frame_m.grid(row=2, column=0, sticky="nsew")
        self.tree_movs.tag_configure("cuenta_corriente", foreground=C.peligro)
        self.tree_movs.tag_configure("pago",  foreground=C.exito)
        self.tree_movs.bind("<Double-1>", self._ver_detalle_movimiento)
        lbl(der, "Doble click en un cargo para ver qué productos justifican ese importe",
            variante="suave").grid(row=3, column=0, sticky="w", pady=(4,0))

        # Barra acciones inferior
        ac2 = tk.Frame(self._cont, bg=C.bg)
        ac2.grid(row=1, column=0, columnspan=2, sticky="ew", padx=12, pady=(0, 8))
        btn(ac2, "Actualizar", variante="neutro",
            comando=self.refrescar).pack(side="left")

    # ── Datos ─────────────────────────────────────────────────────────────────

    def refrescar(self):
        self._refrescar_clientes()
        if self._cliente_sel:
            self._refrescar_movimientos(self._cliente_sel["id"])

    def _refrescar_clientes(self):
        for r in self.tree_cli.get_children():
            self.tree_cli.delete(r)
        texto = self.entry_buscar_cli.get().strip().lower()
        for c in get_todos_clientes():
            if texto and texto not in c["nombre"].lower() and texto not in c["dni"].lower():
                continue
            saldo = c["saldo_actual"]
            disp  = c["disponible"]
            if saldo <= 0:
                tag = "sin_deuda"
            elif disp <= 0:
                tag = "limite"
            else:
                tag = "deuda"
            self.tree_cli.insert("", "end", iid=str(c["id"]), values=(
                c["dni"],
                c["nombre"],
                c["telefono"] or "—",
                f"$ {c['tope_credito']:,.2f}",
                f"$ {saldo:,.2f}",
                f"$ {disp:,.2f}",
            ), tags=(tag,))

    def _refrescar_movimientos(self, cliente_id):
        for r in self.tree_movs.get_children():
            self.tree_movs.delete(r)
        self._movs_venta_id = {}
        for m in get_movimientos_cliente(cliente_id):
            iid = self.tree_movs.insert("", "end", values=(
                m["tipo"].capitalize(),
                f"$ {m['monto']:,.2f}",
                m["concepto"] or "—",
                m["autorizado_por"] or "—",
                m["fecha"][:16] if m["fecha"] else "—",
            ), tags=(m["tipo"],))
            if m.get("venta_id"):
                self._movs_venta_id[iid] = m["venta_id"]

    def _on_sel_cliente(self, event):
        sel = self.tree_cli.selection()
        if not sel: return
        cid = int(sel[0])
        clientes = get_todos_clientes()
        self._cliente_sel = next((c for c in clientes if c["id"] == cid), None)
        if self._cliente_sel:
            self._refrescar_movimientos(cid)

    def _recordatorio_whatsapp(self):
        if not self._cliente_sel:
            messagebox.showinfo("Atencion",
                "Selecciona un cliente primero.", parent=self)
            return
        c = self._cliente_sel
        if not c.get("telefono"):
            messagebox.showwarning(
                "Sin teléfono",
                f"{c['nombre']} no tiene un teléfono cargado — "
                "agregalo con \"Editar cliente / tope\".", parent=self)
            return

        from config import cfg
        negocio = cfg().get("negocio_nombre") or "el negocio"
        saldo = c.get("saldo_actual", 0) or 0
        mensaje = (
            f"Hola {c['nombre']}! Te escribimos de {negocio} para "
            f"recordarte que tenés un saldo pendiente de $ {saldo:,.2f} "
            f"en tu cuenta corriente. ¡Gracias!"
        )

        d = tk.Toplevel(self)
        d.title("Recordatorio por WhatsApp")
        w, h = 420, 300
        sw, sh = d.winfo_screenwidth(), d.winfo_screenheight()
        d.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
        d.configure(bg=C.superficie)
        d.grab_set()

        lbl(d, f"Mensaje para {c['nombre']}", variante="titulo",
            bg=C.superficie).pack(pady=(16,6), padx=16, anchor="w")
        lbl(d, "Lo podés editar antes de abrirlo en WhatsApp:",
            variante="suave", bg=C.superficie).pack(padx=16, anchor="w")

        txt = tk.Text(d, font=F.normal, bg=C.superficie, fg=C.texto,
                      relief="solid", bd=1, wrap="word", height=6)
        txt.insert("1.0", mensaje)
        txt.pack(fill="both", expand=True, padx=16, pady=(6,12))

        def _abrir():
            from impresion import abrir_whatsapp
            texto_final = txt.get("1.0", "end").strip()
            ok, msg = abrir_whatsapp(c["telefono"], texto_final)
            if ok:
                d.destroy()
            else:
                messagebox.showwarning("Atencion", msg, parent=d)

        btn(d, "📱 Abrir en WhatsApp", variante="exito",
            comando=_abrir).pack(padx=16, pady=(0,16), fill="x")

    def _recordatorios_masivos(self):
        deudores = [c for c in get_todos_clientes()
                   if (c.get("saldo_actual") or 0) > 0]
        if not deudores:
            messagebox.showinfo("Recordatorios masivos",
                "No hay clientes con saldo pendiente.", parent=self)
            return

        d = tk.Toplevel(self)
        d.title("Recordatorios masivos por WhatsApp")
        w, h = 640, 480
        sw, sh = d.winfo_screenwidth(), d.winfo_screenheight()
        d.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
        d.configure(bg=C.bg)
        d.grab_set()

        lbl(d, "Elegí a quién mandarle recordatorio", variante="titulo",
            bg=C.bg).pack(padx=16, pady=(16,4), anchor="w")
        lbl(d, "Después vas a poder revisar y editar cada mensaje antes de abrirlo",
            variante="suave", bg=C.bg).pack(padx=16, anchor="w", pady=(0,8))

        f_tabla = card(d)
        f_tabla.pack(fill="both", expand=True, padx=16, pady=(0,8))
        f_tabla.columnconfigure(0, weight=1)
        f_tabla.rowconfigure(0, weight=1)

        cols_sel = [("sel","",30,"center"),("nombre","Cliente",180,"w"),
                   ("saldo","Saldo",100,"e"),("tel","Telefono",120,"w")]
        tree = ttk.Treeview(f_tabla, columns=[c[0] for c in cols_sel],
                           show="headings", selectmode="browse")
        for cid, header, ancho, anchor in cols_sel:
            tree.heading(cid, text=header, anchor="w")
            tree.column(cid, width=ancho, anchor=anchor, minwidth=30)
        sb = ttk.Scrollbar(f_tabla, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")

        seleccionados = {}
        por_id = {}
        for c in deudores:
            por_id[str(c["id"])] = c
            con_tel = bool(c.get("telefono"))
            if con_tel:
                seleccionados[str(c["id"])] = True
            tree.insert("", "end", iid=str(c["id"]), values=(
                "x" if con_tel else "",
                c["nombre"],
                f"$ {c['saldo_actual']:,.2f}",
                c.get("telefono") or "— sin teléfono —",
            ))

        def _on_click(event):
            iid = tree.identify_row(event.y)
            col = tree.identify_column(event.x)
            if not iid or col != "#1":
                return
            if not por_id[iid].get("telefono"):
                messagebox.showinfo("Sin teléfono",
                    "Este cliente no tiene teléfono cargado.", parent=d)
                return
            if iid in seleccionados:
                del seleccionados[iid]
                tree.set(iid, "sel", "")
            else:
                seleccionados[iid] = True
                tree.set(iid, "sel", "x")
            _actualizar_cant()

        bot = tk.Frame(d, bg=C.bg)
        bot.pack(fill="x", padx=16, pady=(0,16))
        lbl_cant = lbl(bot, "", variante="suave")
        lbl_cant.pack(side="left")

        def _actualizar_cant():
            n = len(seleccionados)
            lbl_cant.config(text=f"{n} cliente{'s' if n != 1 else ''} seleccionado{'s' if n != 1 else ''}")
        _actualizar_cant()
        tree.bind("<ButtonRelease-1>", _on_click)

        def _empezar():
            elegidos = [por_id[cid] for cid in seleccionados if cid in por_id]
            if not elegidos:
                messagebox.showinfo("Atencion",
                    "Selecciona al menos un cliente.", parent=d)
                return
            d.destroy()
            self._wizard_recordatorios(elegidos, 0)

        btn(bot, "Comenzar →", variante="exito",
            comando=_empezar).pack(side="right")
        btn(bot, "Cancelar", variante="neutro",
            comando=d.destroy).pack(side="right", padx=(0,8))

    def _wizard_recordatorios(self, clientes, indice):
        if indice >= len(clientes):
            messagebox.showinfo("Recordatorios masivos",
                "Listo — se recorrieron todos los clientes seleccionados.",
                parent=self)
            return

        c = clientes[indice]
        from config import cfg
        negocio = cfg().get("negocio_nombre") or "el negocio"
        saldo = c.get("saldo_actual", 0) or 0
        mensaje = (
            f"Hola {c['nombre']}! Te escribimos de {negocio} para "
            f"recordarte que tenés un saldo pendiente de $ {saldo:,.2f} "
            f"en tu cuenta corriente. ¡Gracias!"
        )

        d = tk.Toplevel(self)
        d.title(f"Recordatorio {indice+1} de {len(clientes)}")
        w, h = 440, 320
        sw, sh = d.winfo_screenwidth(), d.winfo_screenheight()
        d.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
        d.configure(bg=C.superficie)
        d.grab_set()

        lbl(d, f"{indice+1} de {len(clientes)} — {c['nombre']}",
            variante="titulo", bg=C.superficie).pack(pady=(16,4), padx=16, anchor="w")
        lbl(d, "Revisá o editá el mensaje antes de abrirlo:",
            variante="suave", bg=C.superficie).pack(padx=16, anchor="w")

        txt = tk.Text(d, font=F.normal, bg=C.superficie, fg=C.texto,
                      relief="solid", bd=1, wrap="word", height=6)
        txt.insert("1.0", mensaje)
        txt.pack(fill="both", expand=True, padx=16, pady=(6,10))

        bot = tk.Frame(d, bg=C.superficie)
        bot.pack(fill="x", padx=16, pady=(0,16))

        def _saltear():
            d.destroy()
            self._wizard_recordatorios(clientes, indice + 1)

        def _enviar_siguiente():
            from impresion import abrir_whatsapp
            texto_final = txt.get("1.0", "end").strip()
            ok, msg = abrir_whatsapp(c["telefono"], texto_final)
            if not ok:
                messagebox.showwarning("Atencion", msg, parent=d)
                return
            d.destroy()
            self._wizard_recordatorios(clientes, indice + 1)

        btn(bot, "Saltear", variante="neutro",
            comando=_saltear).pack(side="left")
        btn(bot, "📱 Enviar y siguiente →", variante="exito",
            comando=_enviar_siguiente).pack(side="right")

    # ── Acciones ──────────────────────────────────────────────────────────────

    def _registrar_pago(self):
        if not self._cliente_sel:
            messagebox.showinfo("Atencion",
                "Selecciona un cliente primero.", parent=self)
            return

        responsable = pedir_autorizacion(
            self, "Registrar un pago requiere autorizacion del responsable.")
        if not responsable:
            return

        c = self._cliente_sel
        d = tk.Toplevel(self)
        d.title("Registrar pago")
        d.resizable(True, False)
        d.configure(bg=C.superficie)
        d.grab_set()
        w, h = 360, 230
        sw, sh = d.winfo_screenwidth(), d.winfo_screenheight()
        d.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

        lbl(d, f"Pago de {c['nombre']}", variante="titulo",
            bg=C.superficie).pack(pady=(16, 4), padx=20, anchor="w")
        lbl(d, f"Saldo actual: $ {c['saldo_actual']:,.2f}",
            variante="suave", bg=C.superficie,
            fg=C.peligro).pack(padx=20, anchor="w")

        lbl(d, "Monto del pago $", variante="suave",
            bg=C.superficie).pack(padx=20, anchor="w", pady=(12, 0))
        e = tk.Entry(d, font=("Segoe UI", 14), justify="right",
                      bg=C.superficie, fg=C.texto,
                      relief="solid", bd=1)
        e.insert(0, f"{c['saldo_actual']:.2f}")
        e.pack(fill="x", padx=20, ipady=6, pady=(2, 12))
        e.focus_set()
        e.select_range(0, "end")

        def guardar(event=None):
            try:
                monto = float(e.get().replace(",", "."))
                if monto <= 0: raise ValueError
            except ValueError:
                messagebox.showwarning("Error", "Monto invalido.", parent=d)
                return
            registrar_pago_cuenta_corriente(c["id"], monto, responsable)
            d.destroy()
            toast(self, f"Pago de $ {monto:,.2f} registrado para {c['nombre']}")
            self.refrescar()

        e.bind("<Return>", guardar)
        btn(d, "Registrar pago", variante="exito", comando=guardar).pack(
            fill="x", padx=20, pady=(0, 16))

    def _editar_cliente(self):
        if not self._cliente_sel:
            messagebox.showinfo("Atencion",
                "Selecciona un cliente primero.", parent=self)
            return

        responsable = pedir_autorizacion(
            self, "Editar datos o tope de credito requiere autorizacion.")
        if not responsable:
            return

        c = self._cliente_sel
        d = tk.Toplevel(self)
        d.title("Editar cliente")
        d.resizable(True, True)
        d.configure(bg=C.superficie)
        d.grab_set()
        w, h = 380, 260
        sw, sh = d.winfo_screenwidth(), d.winfo_screenheight()
        d.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

        lbl(d, f"Editar — {c['nombre']}", variante="titulo",
            bg=C.superficie).pack(pady=(16, 4), padx=20, anchor="w")
        lbl(d, f"Autorizado por: {responsable}", variante="suave",
            bg=C.superficie, fg=C.exito).pack(padx=20, anchor="w")

        campos = [
            ("Nombre", c["nombre"]),
            ("Telefono", c.get("telefono") or ""),
            ("Tope de credito $", f"{c['tope_credito']:.2f}"),
        ]
        entries = {}
        for label, val in campos:
            lbl(d, label, variante="suave",
                bg=C.superficie).pack(padx=20, anchor="w", pady=(8, 0))
            e = tk.Entry(d, font=F.normal, bg=C.superficie, fg=C.texto,
                          insertbackground=C.primario, relief="solid", bd=1)
            e.insert(0, val)
            e.pack(fill="x", padx=20, ipady=5, pady=(2, 0))
            entries[label] = e

        def guardar(event=None):
            nombre = entries["Nombre"].get().strip()
            tel    = entries["Telefono"].get().strip()
            try:
                tope = float(entries["Tope de credito $"].get().replace(",", "."))
                if tope < 0: raise ValueError
            except ValueError:
                messagebox.showwarning("Error", "Tope invalido.", parent=d)
                return
            if not nombre:
                messagebox.showwarning("Error", "Ingresa el nombre.", parent=d)
                return
            actualizar_cliente(c["id"], nombre, tel, tope)
            d.destroy()
            toast(self, "Cliente actualizado")
            self.refrescar()

        btn(d, "Guardar", variante="exito", comando=guardar).pack(
            fill="x", padx=20, pady=12)

    def _ver_detalle_movimiento(self, event=None):
        sel = self.tree_movs.selection()
        if not sel:
            return
        venta_id = self._movs_venta_id.get(sel[0])
        if not venta_id:
            messagebox.showinfo(
                "Sin detalle",
                "Este movimiento no tiene una venta asociada con productos "
                "(por ejemplo, es un pago o un ajuste manual).", parent=self)
            return
        self._mostrar_detalle_venta(venta_id)

    def _mostrar_detalle_venta(self, venta_id):
        items = get_detalle_venta(venta_id)
        d = tk.Toplevel(self)
        d.title(f"Productos — Venta #{venta_id}")
        w, h = 480, 420
        sw, sh = d.winfo_screenwidth(), d.winfo_screenheight()
        d.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
        d.configure(bg=C.superficie)
        d.grab_set()

        lbl(d, f"Productos de la venta #{venta_id}", variante="titulo",
            bg=C.superficie).pack(pady=(16,4), padx=20, anchor="w")

        cols = [
            ("desc",  "Producto",  240, "w"),
            ("cant",  "Cant.",      60, "e"),
            ("precio","Precio u.",  90, "e"),
            ("sub",   "Subtotal",   90, "e"),
        ]
        frame_t, tree = tabla(d, cols, altura=12)
        frame_t.pack(fill="both", expand=True, padx=20, pady=(4,8))

        total = 0.0
        for it in items:
            tree.insert("", "end", values=(
                it["descripcion"] + (" 🏷️" if it["promo_aplicada"] else ""),
                f"{it['cantidad']:g}",
                f"$ {it['precio_unitario']:,.2f}",
                f"$ {it['subtotal']:,.2f}",
            ))
            total += it["subtotal"]

        lbl(d, f"Total: $ {total:,.2f}", variante="subtitulo",
            bg=C.superficie).pack(padx=20, anchor="e", pady=(0,4))
        btn(d, "Cerrar", variante="neutro", comando=d.destroy).pack(pady=(4,16))

    def _ver_movimientos(self):
        if not self._cliente_sel:
            messagebox.showinfo("Atencion",
                "Selecciona un cliente primero.", parent=self)
            return

        cliente = self._cliente_sel
        movs = get_movimientos_cliente(cliente["id"])

        d = tk.Toplevel(self)
        d.title(f"Movimientos — {cliente['nombre']}")
        w, h = 620, 480
        sw, sh = d.winfo_screenwidth(), d.winfo_screenheight()
        d.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
        d.configure(bg=C.superficie)
        d.grab_set()

        lbl(d, f"{cliente['nombre']} — Saldo: $ {cliente['saldo_actual']:,.2f}",
            variante="titulo", bg=C.superficie).pack(pady=(16,4), padx=20, anchor="w")
        lbl(d, "Doble click en un cargo para ver los productos que lo justifican",
            variante="suave", bg=C.superficie).pack(padx=20, anchor="w")

        frame_t, tree = tabla(d, COLS_MOVS, altura=15)
        frame_t.pack(fill="both", expand=True, padx=20, pady=(8,8))
        tree.tag_configure("cuenta_corriente", foreground=C.peligro)
        tree.tag_configure("pago", foreground=C.exito)

        ventas_por_fila = {}
        for m in movs:
            iid = tree.insert("", "end", values=(
                m["tipo"].capitalize(),
                f"$ {m['monto']:,.2f}",
                m["concepto"] or "—",
                m["autorizado_por"] or "—",
                m["fecha"][:16] if m["fecha"] else "—",
            ), tags=(m["tipo"],))
            if m.get("venta_id"):
                ventas_por_fila[iid] = m["venta_id"]

        def _doble_click(event=None):
            sel = tree.selection()
            if not sel:
                return
            venta_id = ventas_por_fila.get(sel[0])
            if venta_id:
                self._mostrar_detalle_venta(venta_id)

        tree.bind("<Double-1>", _doble_click)
        btn(d, "Cerrar", variante="neutro", comando=d.destroy).pack(pady=(0,16))


# ══════════════════════════════════════════════════════════════════════════
# Selector de cliente reutilizable (lo usa ventas_ui en el cobro)
# ══════════════════════════════════════════════════════════════════════════

def elegir_cliente(parent, coincidencias, titulo="Elegi el cliente"):
    """Lista nombre + DNI + saldo + disponible para seleccionar uno.

    Devuelve el dict del cliente elegido, o None si se cancela.
    """
    d = tk.Toplevel(parent)
    d.title(titulo)
    d.configure(bg=C.superficie)
    d.grab_set()
    w, h = 560, min(150 + 26 * len(coincidencias), 480)
    sw, sh = d.winfo_screenwidth(), d.winfo_screenheight()
    d.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

    lbl(d, f"{len(coincidencias)} clientes coinciden", variante="titulo",
        bg=C.superficie).pack(anchor="w", padx=20, pady=(16, 2))
    lbl(d, "Doble clic o Enter para elegir", variante="suave",
        bg=C.superficie).pack(anchor="w", padx=20)

    cols = ("nombre", "dni", "saldo", "disponible")
    tv = ttk.Treeview(d, columns=cols, show="headings",
                      height=min(len(coincidencias), 12))
    for c_, t_, w_ in (("nombre", "Nombre", 230), ("dni", "DNI", 110),
                       ("saldo", "Saldo", 105), ("disponible", "Disponible", 105)):
        tv.heading(c_, text=t_)
        tv.column(c_, width=w_, anchor="w")
    for i, c in enumerate(coincidencias):
        disp = (c.get("tope_credito") or 0) - (c.get("saldo_actual") or 0)
        tv.insert("", "end", iid=str(i), values=(
            c.get("nombre", ""), c.get("dni", ""),
            f"$ {c.get('saldo_actual', 0):,.2f}", f"$ {disp:,.2f}"))
    tv.pack(fill="both", expand=True, padx=20, pady=10)
    if coincidencias:
        tv.selection_set("0")
        tv.focus("0")
    tv.focus_set()

    elegido = [None]

    def aceptar(event=None):
        sel = tv.selection()
        if sel:
            elegido[0] = coincidencias[int(sel[0])]
            d.destroy()

    tv.bind("<Double-1>", aceptar)
    tv.bind("<Return>", aceptar)
    d.bind("<Escape>", lambda e: d.destroy())

    fb = tk.Frame(d, bg=C.superficie)
    fb.pack(pady=(0, 14))
    btn(fb, "Elegir", variante="exito", comando=aceptar).pack(side="left", padx=4)
    btn(fb, "Cancelar", variante="neutro", comando=d.destroy).pack(side="left", padx=4)

    parent.wait_window(d)
    return elegido[0]


def resolver_cliente(parent, texto):
    """DNI exacto, o busqueda por nombre/DNI parcial con lista para elegir.

    Devuelve (cliente | None, motivo) donde motivo es:
        "ok"        encontrado
        "vacio"     no se escribio nada
        "ninguno"   no hubo coincidencias
        "cancelo"   habia varias y se cerro el selector sin elegir
    """
    from repositorio import get_cliente_por_dni, buscar_clientes

    t = (texto or "").strip()
    if not t:
        return None, "vacio"

    limpio = t.replace(".", "").replace("-", "").replace(" ", "")
    if limpio.isdigit():
        c = get_cliente_por_dni(limpio)
        if c:
            return c, "ok"

    coincidencias = buscar_clientes(t)
    if not coincidencias:
        return None, "ninguno"
    if len(coincidencias) == 1:
        return coincidencias[0], "ok"

    elegido = elegir_cliente(parent, coincidencias)
    return (elegido, "ok") if elegido else (None, "cancelo")

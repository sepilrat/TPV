"""
caja_ui.py — Gestión de caja TPV v2.0
Fixes: stock correcto al anular, movimientos en historial,
       notas visibles, alineación izquierda, refresh automático
"""

import logging
import tkinter as tk
from tkinter import ttk, messagebox
from styles import C, F, btn, lbl, card, tabla, toast, header_seccion, scrollable
from db import get_sesion_abierta, cerrar_sesion_caja
from repositorio import (get_resumen_sesion, get_ventas_sesion,
                         get_historial_sesiones, registrar_movimiento,
                         anular_venta, get_movimientos_sesion)

# ─────────────────────────────────────────────────────────────────────────────
# Helpers DB
# ─────────────────────────────────────────────────────────────────────────────

COLS_VENTAS = [
    ("id",     "#",       50,  "w"),
    ("hora",   "Hora",    70,  "w"),
    ("items",  "Items",   50,  "e"),
    ("metodo", "Metodo",  110, "w"),
    ("desc",   "Desc %",  60,  "e"),
    ("total",  "Total",   90,  "e"),
    ("estado", "Estado",  70,  "w"),
]

COLS_HIST = [
    ("id",       "#",        45,  "w"),
    ("apertura", "Apertura", 130, "w"),
    ("cierre",   "Cierre",   130, "w"),
    ("ventas",   "Ventas",   55,  "e"),
    ("efectivo", "Efectivo", 90,  "e"),
    ("tarjeta",  "Tarjeta",  90,  "e"),
    ("qr",       "QR",       75,  "e"),
    ("cta",      "Cta.Cte",  80,  "e"),
    ("total",    "Total",    90,  "e"),
    ("contado",  "Contado",  90,  "e"),
    ("dif",      "Dif.",     85,  "e"),
    ("notas",    "Notas",    150, "w"),
]

COLS_MOVS = [
    ("tipo",     "Tipo",     70,  "w"),
    ("monto",    "Monto",    90,  "e"),
    ("concepto", "Concepto", 200, "w"),
    ("fecha",    "Fecha",    120, "w"),
]

class CajaUI(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._build()
        self.refrescar()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build(self):
        # Resumen de la sesión de caja actual: ventas, métodos de pago y totales.
        # Desde acá se registran ingresos/egresos manuales y se cierra la caja.
        # El historial muestra todas las sesiones cerradas anteriores.
        header_seccion(self, "Gestion de Caja",
            "Sesion actual, movimientos manuales, cierre e historial").pack(
            fill="x", padx=12, pady=(8,4))

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=12, pady=12)

        f_actual    = ttk.Frame(self.nb)
        f_movs      = ttk.Frame(self.nb)
        f_historial = ttk.Frame(self.nb)
        self.nb.add(f_actual,    text="  Caja actual  ")
        self.nb.add(f_movs,      text="  Movimientos  ")
        self.nb.add(f_historial, text="  Historial  ")

        self._build_actual(f_actual)
        self._build_movimientos(f_movs)
        self._build_historial(f_historial)

        f_bitacora = ttk.Frame(self.nb)
        self.nb.add(f_bitacora, text="  Bitacora  ")
        self._build_bitacora(f_bitacora)

        # Refresh automático al cambiar de tab
        self.nb.bind("<<NotebookTabChanged>>", lambda e: self.refrescar())

    # ── Tab caja actual ───────────────────────────────────────────────────────

    def _build_actual(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=2)
        parent.rowconfigure(0, weight=1)

        # ── Panel izquierdo — scrollable para pantallas chicas ──────────────
        outer_izq, izq = scrollable(parent, bg=C.bg)
        outer_izq.grid(row=0, column=0, sticky="nsew", padx=(0,8))
        izq.columnconfigure(0, weight=1)

        # Resumen
        c_res = card(izq)
        c_res.grid(row=0, column=0, sticky="ew")
        c_res.columnconfigure(0, weight=1)

        lbl(c_res, "Resumen de caja", variante="titulo",
            bg=C.superficie).grid(row=0, column=0, sticky="w", padx=16, pady=(16,8))
        self.lbl_sesion_info = lbl(c_res, "", variante="suave", bg=C.superficie)
        self.lbl_sesion_info.grid(row=1, column=0, sticky="w", padx=16)

        self.frame_totales = tk.Frame(c_res, bg=C.superficie)
        self.frame_totales.grid(row=2, column=0, sticky="ew", padx=16, pady=8)
        self.frame_totales.columnconfigure(1, weight=1)

        ttk.Separator(c_res, orient="horizontal").grid(
            row=3, column=0, sticky="ew", padx=16)

        ft = tk.Frame(c_res, bg=C.superficie)
        ft.grid(row=4, column=0, sticky="ew", padx=16, pady=(8,4))
        lbl(ft, "TOTAL RECAUDADO", variante="suave", bg=C.superficie).pack(anchor="w")
        self.lbl_total_gral = tk.Label(ft, text="$ 0,00",
                                        font=("Segoe UI", 20, "bold"),
                                        bg=C.superficie, fg=C.primario)
        self.lbl_total_gral.pack(anchor="w")

        fc = tk.Frame(c_res, bg=C.superficie)
        fc.grid(row=5, column=0, sticky="ew", padx=16, pady=(0,16))
        lbl(fc, "Ventas:", variante="suave", bg=C.superficie).pack(side="left")
        self.lbl_cant_ventas = lbl(fc, "0", variante="suave", bg=C.superficie, padx=4)
        self.lbl_cant_ventas.pack(side="left")
        lbl(fc, "  Ticket prom:", variante="suave", bg=C.superficie).pack(side="left")
        self.lbl_ticket_prom = lbl(fc, "$ 0,00", variante="suave", bg=C.superficie, padx=4)
        self.lbl_ticket_prom.pack(side="left")

        # Movimiento rápido
        ttk.Separator(izq, orient="horizontal").grid(
            row=1, column=0, sticky="ew", pady=8)

        c_mov = card(izq)
        c_mov.grid(row=2, column=0, sticky="ew")
        c_mov.columnconfigure(0, weight=1)

        lbl(c_mov, "Movimiento manual", variante="subtitulo",
            bg=C.superficie).grid(row=0, column=0, columnspan=2,
                                   sticky="w", padx=16, pady=(12,6))

        lbl(c_mov, "Concepto", variante="suave",
            bg=C.superficie).grid(row=1, column=0, columnspan=2,
                                   sticky="w", padx=16)
        self.entry_concepto = tk.Entry(c_mov, font=F.normal, bg=C.superficie,
                                        fg=C.texto, insertbackground=C.primario,
                                        relief="solid", bd=1)
        self.entry_concepto.grid(row=2, column=0, columnspan=2, sticky="ew",
                                  padx=16, pady=(2,6), ipady=5)

        lbl(c_mov, "Monto $", variante="suave",
            bg=C.superficie).grid(row=3, column=0, sticky="w", padx=(16,4))
        self.entry_monto_mov = tk.Entry(c_mov, width=10, font=F.normal,
                                         bg=C.superficie, fg=C.texto,
                                         insertbackground=C.primario,
                                         relief="solid", bd=1, justify="right")
        self.entry_monto_mov.grid(row=3, column=1, sticky="ew", padx=(4,16), ipady=5)

        fb = tk.Frame(c_mov, bg=C.superficie)
        fb.grid(row=4, column=0, columnspan=2, sticky="ew", padx=16, pady=(8,16))
        btn(fb, "Ingreso", variante="exito",
            comando=lambda: self._mov_manual("ingreso")).pack(side="left")
        btn(fb, "Egreso", variante="peligro",
            comando=lambda: self._mov_manual("egreso")).pack(side="left", padx=6)

        # Cierre
        ttk.Separator(izq, orient="horizontal").grid(
            row=3, column=0, sticky="ew", pady=8)

        c_cierre = card(izq)
        c_cierre.grid(row=4, column=0, sticky="ew")
        c_cierre.columnconfigure(0, weight=1)

        lbl(c_cierre, "Notas del cierre", variante="suave",
            bg=C.superficie).grid(row=0, column=0, sticky="w", padx=16, pady=(12,2))
        self.entry_notas_cierre = tk.Entry(c_cierre, font=F.normal,
                                            bg=C.superficie, fg=C.texto,
                                            insertbackground=C.primario,
                                            relief="solid", bd=1)
        self.entry_notas_cierre.grid(row=1, column=0, sticky="ew",
                                      padx=16, pady=(0,12), ipady=5)

        self.btn_cerrar = tk.Button(c_cierre, text="CERRAR CAJA",
                                     font=("Segoe UI", 12, "bold"),
                                     bg=C.peligro, fg=C.blanco,
                                     relief="flat", cursor="hand2",
                                     pady=10, command=self._cerrar_caja)
        self.btn_cerrar.grid(row=2, column=0, sticky="ew", padx=16, pady=(0,16))
        self.btn_cerrar.bind("<Enter>", lambda e: self.btn_cerrar.config(bg=C.peligro_h))
        self.btn_cerrar.bind("<Leave>", lambda e: self.btn_cerrar.config(bg=C.peligro))

        # ── Panel derecho: ventas ─────────────────────────────────────────────
        der = tk.Frame(parent, bg=C.bg)
        der.grid(row=0, column=1, sticky="nsew")
        der.columnconfigure(0, weight=1)
        der.rowconfigure(1, weight=1)

        lbl(der, "Ventas de esta sesion", variante="subtitulo").grid(
            row=0, column=0, sticky="w", pady=(0,6))

        frame_t, self.tree_ventas = tabla(der, COLS_VENTAS)
        frame_t.grid(row=1, column=0, sticky="nsew")
        self.tree_ventas.tag_configure("anulada",
            foreground=C.texto_suave,
            font=(*F.pequeña[:2], "overstrike"))

        ac = tk.Frame(der, bg=C.bg)
        ac.grid(row=2, column=0, sticky="ew", pady=(6,0))
        btn(ac, "Devolver items", variante="exito",
            comando=self._devolver).pack(side="left", padx=4)
        btn(ac, "Anular venta", variante="peligro",
            comando=self._anular_venta).pack(side="left")
        btn(ac, "Actualizar", variante="neutro",
            comando=self.refrescar).pack(side="right")

    # ── Tab movimientos ───────────────────────────────────────────────────────

    def _build_movimientos(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)

        frame_t, self.tree_movs = tabla(parent, COLS_MOVS)
        frame_t.grid(row=0, column=0, sticky="nsew", pady=(0,8))
        self.tree_movs.tag_configure("ingreso", foreground=C.exito)
        self.tree_movs.tag_configure("egreso",  foreground=C.peligro)

        btn(parent, "Actualizar", variante="neutro",
            comando=self._refrescar_movimientos).grid(
            row=1, column=0, sticky="w")

    # ── Tab historial ─────────────────────────────────────────────────────────

    def _build_historial(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)

        frame_t, self.tree_hist = tabla(parent, COLS_HIST)
        frame_t.grid(row=0, column=0, sticky="nsew", pady=(0,8))
        self.tree_hist.tag_configure("falta", background=C.err_flash,
                                     foreground=C.peligro)
        self.tree_hist.tag_configure("sobra", background=C.advertencia)
        self.tree_hist.tag_configure("cuadra", background=C.ok_flash)
        self.tree_hist.tag_configure("sinarqueo", foreground=C.texto_suave)

        self.lbl_arqueo = lbl(parent, "", variante="suave")
        self.lbl_arqueo.grid(row=2, column=0, sticky="w", pady=(6, 0))

        btn(parent, "Actualizar", variante="neutro",
            comando=self._refrescar_historial).grid(
            row=1, column=0, sticky="w")

    # ── Datos ─────────────────────────────────────────────────────────────────

    def refrescar(self):
        self._refrescar_actual()
        self._refrescar_movimientos()
        self._refrescar_historial()
        self._refrescar_bitacora()

    def _refrescar_actual(self):
        sesion = get_sesion_abierta()
        if not sesion:
            self.lbl_sesion_info.config(text="No hay sesion abierta.")
            self.lbl_total_gral.config(text="$ 0,00")
            return

        sid = sesion["id"]
        _res = get_resumen_sesion(sid)
        resumen, ventas_res, _movs = _res["sesion"], _res["ventas"], _res["movimientos"]

        apertura = resumen.get("apertura_en", "")[:16]
        self.lbl_sesion_info.config(
            text=f"Sesion #{sid}  |  Abierta: {apertura}  |  Fondo: $ {resumen['fondo_inicial']:,.2f}")

        # Totales por método
        for w in self.frame_totales.winfo_children():
            w.destroy()

        metodos = [
            ("Efectivo",       resumen["total_efectivo"]),
            ("Tarjeta",        resumen["total_tarjeta"]),
            ("QR",             resumen["total_qr"]),
            ("Cta. Corriente", resumen["total_cuenta_corriente"]),
        ]
        for i, (nombre, total) in enumerate(metodos):
            lbl(self.frame_totales, f"{nombre}:", variante="suave",
                bg=C.superficie).grid(row=i, column=0, sticky="w", pady=1)
            lbl(self.frame_totales, f"$ {total:,.2f}", variante="suave",
                bg=C.superficie).grid(row=i, column=1, sticky="w", padx=16, pady=1)

        total_gral = sum(t for _, t in metodos)
        self.lbl_total_gral.config(text=f"$ {total_gral:,.2f}")

        cant   = ventas_res["cant"] or 0
        total_v = ventas_res["total"] or 0
        prom   = total_v / cant if cant else 0
        self.lbl_cant_ventas.config(text=str(cant))
        self.lbl_ticket_prom.config(text=f"$ {prom:,.2f}")

        # Tabla ventas
        for r in self.tree_ventas.get_children():
            self.tree_ventas.delete(r)
        for v in get_ventas_sesion(sid):
            hora = v["fecha"][11:16] if v["fecha"] else ""
            tags = ("anulada",) if v["anulada"] else ()
            self.tree_ventas.insert("", "end", iid=str(v["id"]), values=(
                v["id"], hora, v["items"],
                v["metodo_pago"].capitalize(),
                f"{v['descuento_pct']:.0f}%" if v["descuento_pct"] else "—",
                f"$ {v['total']:,.2f}",
                "ANULADA" if v["anulada"] else "OK",
            ), tags=tags)

    def _refrescar_movimientos(self):
        for r in self.tree_movs.get_children():
            self.tree_movs.delete(r)
        sesion = get_sesion_abierta()
        if not sesion:
            return
        movs = get_movimientos_sesion(sesion["id"])
        for m in movs:
            self.tree_movs.insert("", "end", values=(
                m["tipo"].capitalize(),
                f"$ {m['monto']:,.2f}",
                m["concepto"] or "—",
                m["fecha"][:16] if m["fecha"] else "—",
            ), tags=(m["tipo"],))

    def _refrescar_historial(self):
        for r in self.tree_hist.get_children():
            self.tree_hist.delete(r)
        # Arqueo por sesion: sin esto no se ve si el faltante es de un
        # dia suelto o un patron que se repite.
        from repositorio import get_arqueos
        arq = {a["id"]: a for a in get_arqueos(limit=200)}
        for s in get_historial_sesiones():
            a = arq.get(s["id"], {})
            contado = a.get("efectivo_contado")
            dif = a.get("diferencia")
            if contado is None:
                txt_cont, txt_dif, tag = "sin arqueo", "—", "sinarqueo"
            else:
                txt_cont = f"$ {contado:,.2f}"
                if abs(dif or 0) < 0.01:
                    txt_dif, tag = "✓", "cuadra"
                else:
                    txt_dif = f"$ {dif:,.2f}"
                    tag = "falta" if dif < 0 else "sobra"
            self.tree_hist.insert("", "end", tags=(tag,), values=(
                s["id"],
                s["apertura_en"][:16] if s["apertura_en"] else "—",
                s["cierre_en"][:16]   if s["cierre_en"]   else "—",
                s["cant_ventas"],
                f"$ {s['total_efectivo']:,.2f}",
                f"$ {s['total_tarjeta']:,.2f}",
                f"$ {s['total_qr']:,.2f}",
                f"$ {s['total_cuenta_corriente']:,.2f}",
                f"$ {s['total_general']:,.2f}",
                txt_cont,
                txt_dif,
                (a.get("arqueo_notas") or s["notas"] or "—"),
            ))

        cerradas = [a for a in arq.values() if a.get("diferencia") is not None]
        if cerradas:
            faltantes = [a["diferencia"] for a in cerradas if a["diferencia"] < -0.01]
            neto = sum(a["diferencia"] for a in cerradas)
            self.lbl_arqueo.config(
                text=(f"{len(cerradas)} cierre(s) con arqueo   ·   "
                      f"{len(faltantes)} con faltante   ·   "
                      f"acumulado: $ {neto:,.2f}"))
        else:
            self.lbl_arqueo.config(
                text="Todavía no hay cierres con arqueo. Al cerrar la caja, "
                     "cargá cuánto contaste para empezar a llevar el control.")

    # ── Tab bitacora ──────────────────────────────────────────────────────────

    def _build_bitacora(self, parent):
        """Quien autorizo cada accion que movio plata o stock.

        Es lo que permite explicar una diferencia de caja: sin esto, un
        faltante de $8.000 y una devolucion de $8.000 son indistinguibles.
        """
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)

        bar = tk.Frame(parent, bg=C.bg)
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        lbl(bar, "Ver:", variante="suave").pack(side="left")
        self.v_bit_accion = tk.StringVar(value="Todas")
        self.cb_bit = ttk.Combobox(bar, textvariable=self.v_bit_accion,
                                   width=26, state="readonly",
                                   values=("Todas",))
        self.cb_bit.pack(side="left", padx=6)
        self.cb_bit.bind("<<ComboboxSelected>>", lambda e: self._refrescar_bitacora())
        btn(bar, "Actualizar", variante="neutro",
            comando=self._refrescar_bitacora).pack(side="right")

        COLS_BIT = [
            ("fecha",  "Fecha",        130, "w"),
            ("accion", "Accion",       190, "w"),
            ("resp",   "Autorizo",     140, "w"),
            ("monto",  "Monto",        110, "e"),
            ("det",    "Detalle",      420, "w"),
        ]
        frame_t, self.tree_bit = tabla(parent, COLS_BIT)
        frame_t.grid(row=1, column=0, sticky="nsew")
        self.tree_bit.tag_configure("plata", background=C.err_flash)

        self.lbl_bit = lbl(parent, "", variante="suave")
        self.lbl_bit.grid(row=2, column=0, sticky="w", pady=(6, 0))

    def _refrescar_bitacora(self):
        from repositorio import get_bitacora
        filtro = getattr(self, "v_bit_accion", None)
        accion = filtro.get() if filtro else "Todas"
        try:
            filas = get_bitacora(accion=None if accion == "Todas" else accion)
            todas = get_bitacora()
        except Exception as exc:
            self.lbl_bit.config(text=f"No se pudo leer la bitacora: {exc}")
            return

        self.cb_bit.config(values=["Todas"] + sorted({b["accion"] for b in todas}))
        self.tree_bit.delete(*self.tree_bit.get_children())
        for b in filas:
            # Las que mueven plata van resaltadas: son las que hay que
            # mirar cuando el arqueo no cuadra.
            tag = "plata" if b["accion"] in ("Anulacion de venta",
                                             "Devolucion") else ""
            self.tree_bit.insert("", "end", tags=(tag,) if tag else (), values=(
                (b["fecha"] or "")[:16], b["accion"], b["responsable"],
                f"$ {b['monto']:,.2f}" if b["monto"] else "—",
                (b["detalle"] or "")[:70]))

        plata = sum(b["monto"] or 0 for b in filas
                    if b["accion"] in ("Anulacion de venta", "Devolucion"))
        self.lbl_bit.config(
            text=(f"{len(filas)} accion(es)   ·   "
                  f"$ {plata:,.2f} en anulaciones y devoluciones"))

    # ── Acciones ──────────────────────────────────────────────────────────────

    def _mov_manual(self, tipo):
        concepto = self.entry_concepto.get().strip()
        try:
            monto = float(self.entry_monto_mov.get().replace(",", "."))
            if monto <= 0: raise ValueError
        except ValueError:
            messagebox.showwarning("Error", "Ingresa un monto valido.", parent=self)
            return

        sesion = get_sesion_abierta()
        if not sesion:
            messagebox.showwarning("Error", "No hay sesion abierta.", parent=self)
            return

        registrar_movimiento(sesion["id"], tipo, monto, concepto)
        self.entry_concepto.delete(0, "end")
        self.entry_monto_mov.delete(0, "end")
        toast(self, f"{'Ingreso' if tipo == 'ingreso' else 'Egreso'}: $ {monto:,.2f}")
        self.refrescar()

    def _cerrar_caja(self):
        """Cierre CON arqueo: se cuenta la plata antes de cerrar.

        Antes el cierre solo mostraba lo que el sistema creia y pedia
        confirmar. Un faltante por un vuelto mal dado o un cobro no
        registrado no dejaba rastro y nunca se podia rastrear a un turno.
        """
        sesion = get_sesion_abierta()
        if not sesion:
            messagebox.showinfo("Info", "No hay sesion abierta.", parent=self)
            return

        sid = sesion["id"]
        _res = get_resumen_sesion(sid)
        resumen, ventas_res = _res["sesion"], _res["ventas"]
        total = (resumen["total_efectivo"] + resumen["total_tarjeta"] +
                 resumen["total_qr"]       + resumen["total_cuenta_corriente"])

        from repositorio import efectivo_esperado
        ef = efectivo_esperado(sid)

        d = tk.Toplevel(self)
        d.title(f"Cerrar caja — sesion #{sid}")
        d.configure(bg=C.superficie)
        d.grab_set()
        w, h = 500, 620
        sw, sh = d.winfo_screenwidth(), d.winfo_screenheight()
        d.geometry(f"{w}x{h}+{(sw-w)//2}+{max(0,(sh-h)//2)}")

        lbl(d, f"Cierre de caja — sesion #{sid}", variante="titulo",
            bg=C.superficie).pack(anchor="w", padx=20, pady=(16, 2))
        lbl(d, f"{ventas_res['cant'] or 0} ventas   ·   total $ {total:,.2f}",
            variante="suave", bg=C.superficie).pack(anchor="w", padx=20)

        # ── Desglose de lo que TIENE que haber en el cajon ────────────
        caja = tk.Frame(d, bg=C.acento, padx=16, pady=12)
        caja.pack(fill="x", padx=20, pady=(14, 8))
        lbl(caja, "Efectivo que deberia haber en el cajon", variante="suave",
            bg=C.acento).pack(anchor="w")
        for etiqueta, valor in (
                ("Fondo inicial", ef["fondo_inicial"]),
                ("Ventas en efectivo", ef["ventas_efectivo"]),
                ("Ingresos manuales", ef["ingresos_manuales"]),
                ("Egresos", -ef["egresos"])):
            if valor:
                f = tk.Frame(caja, bg=C.acento)
                f.pack(fill="x")
                tk.Label(f, text=etiqueta, bg=C.acento, fg=C.texto,
                         font=F.normal, anchor="w").pack(side="left")
                tk.Label(f, text=f"$ {valor:,.2f}", bg=C.acento, fg=C.texto,
                         font=F.normal, anchor="e").pack(side="right")
        tk.Frame(caja, bg=C.texto_suave, height=1).pack(fill="x", pady=6)
        fe = tk.Frame(caja, bg=C.acento)
        fe.pack(fill="x")
        tk.Label(fe, text="ESPERADO", bg=C.acento, fg=C.texto,
                 font=F.total, anchor="w").pack(side="left")
        tk.Label(fe, text=f"$ {ef['esperado']:,.2f}", bg=C.acento, fg=C.texto,
                 font=F.total, anchor="e").pack(side="right")

        lbl(d, "Los otros medios de pago no entran acá: con tarjeta, QR o "
               "cuenta corriente no entra plata al cajón.",
            variante="suave", bg=C.superficie).pack(anchor="w", padx=20)

        # ── Conteo ────────────────────────────────────────────────────
        lbl(d, "¿Cuánto contaste?", variante="subtitulo",
            bg=C.superficie).pack(anchor="w", padx=20, pady=(14, 2))
        v_contado = tk.StringVar()
        tk.Entry(d, textvariable=v_contado, font=F.total, justify="center",
                 bg=C.bg, fg=C.texto, relief="solid", bd=1).pack(
            fill="x", padx=20, ipady=8)

        lbl_dif = tk.Label(d, text="", font=F.total, bg=C.superficie,
                           anchor="center")
        lbl_dif.pack(fill="x", padx=20, pady=(10, 0))

        def _calcular(*_a):
            txt = v_contado.get().strip().replace(",", ".")
            if not txt:
                lbl_dif.config(text="", bg=C.superficie)
                return
            try:
                dif = round(float(txt) - ef["esperado"], 2)
            except ValueError:
                lbl_dif.config(text="No es un número", fg=C.peligro,
                               bg=C.superficie)
                return
            if abs(dif) < 0.01:
                lbl_dif.config(text="✓  Cuadra exacto", fg=C.exito, bg=C.ok_flash)
            elif dif > 0:
                lbl_dif.config(text=f"Sobran $ {dif:,.2f}", fg=C.texto,
                               bg=C.advertencia)
            else:
                lbl_dif.config(text=f"Faltan $ {abs(dif):,.2f}", fg=C.peligro,
                               bg=C.err_flash)

        v_contado.trace_add("write", _calcular)

        lbl(d, "Nota del arqueo (si hay diferencia, por qué)",
            variante="suave", bg=C.superficie).pack(anchor="w", padx=20,
                                                    pady=(12, 2))
        v_nota = tk.StringVar()
        tk.Entry(d, textvariable=v_nota, font=F.normal, bg=C.bg, fg=C.texto,
                 relief="solid", bd=1).pack(fill="x", padx=20, ipady=5)

        def _confirmar():
            txt = v_contado.get().strip().replace(",", ".")
            contado = None
            if txt:
                try:
                    contado = float(txt)
                except ValueError:
                    messagebox.showwarning("Cerrar caja",
                                           "El monto contado no es un número.",
                                           parent=d)
                    return
            else:
                if not messagebox.askyesno(
                        "Sin arqueo",
                        "No cargaste cuánto contaste.\n\n"
                        "La caja se va a cerrar sin arqueo: si falta o sobra "
                        "plata, no va a quedar registro de hoy.\n\n"
                        "¿Cerrar igual?", parent=d):
                    return

            dif = (round(contado - ef["esperado"], 2)
                   if contado is not None else None)
            if dif is not None and abs(dif) >= 0.01:
                estado = "sobran" if dif > 0 else "faltan"
                if not messagebox.askyesno(
                        "Confirmar diferencia",
                        f"Contaste $ {contado:,.2f} y el sistema esperaba "
                        f"$ {ef['esperado']:,.2f}.\n\n"
                        f"{estado.upper()} $ {abs(dif):,.2f}.\n\n"
                        "¿Cerrar así?", parent=d):
                    return

            d.destroy()
            notas = self.entry_notas_cierre.get().strip()
            cerrar_sesion_caja(sid, notas, contado, v_nota.get().strip())
            from logger import hacer_backup
            hacer_backup("cierre_caja")

            # Aviso diario: si no salio en todo el dia, este es el ultimo
            # momento util para enterarse de lo que hay que reponer manana.
            from config import cfg
            if cfg().get("aviso_diario_al_cerrar_caja"):
                import threading

                def _avisar():
                    try:
                        from impresion import enviar_aviso_diario
                        enviar_aviso_diario("cierre de caja")
                    except Exception as exc:
                        logging.warning(f"Aviso diario al cerrar: {exc}")

                threading.Thread(target=_avisar, daemon=True).start()
            extra = ""
            if dif is not None:
                extra = ("\nArqueo: cuadra exacto." if abs(dif) < 0.01
                         else f"\nArqueo: diferencia de $ {dif:,.2f}.")
            messagebox.showinfo("Caja cerrada",
                f"Sesion #{sid} cerrada.{extra}\n\n"
                "Reinicia la aplicacion para abrir una nueva sesion.",
                parent=self)
            self.btn_cerrar.config(state="disabled")
            self.refrescar()

        pie = tk.Frame(d, bg=C.superficie)
        pie.pack(side="bottom", fill="x", pady=16)
        btn(pie, "Cerrar caja", variante="peligro",
            comando=_confirmar).pack(side="left", padx=(20, 6))
        btn(pie, "Cancelar", variante="neutro",
            comando=d.destroy).pack(side="left")

    def _devolver(self):
        """Devolucion parcial: vuelven algunos items, no toda la venta."""
        ses = get_sesion_abierta()
        if not ses:
            messagebox.showwarning(
                "Devolucion",
                "No hay caja abierta. Abri la caja para poder devolver.",
                parent=self)
            return
        from devolucion_ui import dialogo_devolucion, buscar_venta_a_devolver
        # Si hay una venta marcada en la lista se usa esa; si no, se busca.
        # El cliente suele volver dias despues, cuando esa venta ya no esta
        # en la sesion actual.
        sel = self.tree_ventas.selection()
        venta_id = int(sel[0]) if sel else buscar_venta_a_devolver(self)
        if not venta_id:
            return
        dev_id = dialogo_devolucion(self, venta_id, ses["id"])
        if dev_id:
            toast(self, f"Devolucion #{dev_id} registrada — stock repuesto")
            self.refrescar()

    def _anular_venta(self):
        sel = self.tree_ventas.selection()
        if not sel:
            messagebox.showinfo("Atencion", "Selecciona una venta.", parent=self)
            return
        vid = int(sel[0])
        # Anular saca la venta de la caja: sin autorizacion ni registro,
        # un faltante en el arqueo es indistinguible de un robo.
        from fiado_ui import pedir_autorizacion
        responsable = pedir_autorizacion(
            self, f"Anular la venta #{vid} requiere autorizacion.")
        if not responsable:
            return

        if not messagebox.askyesno("Anular venta",
                                    f"Anular venta #{vid}?\nSe restaurara el stock.",
                                    parent=self):
            return
        # El monto se lee ANTES de anular: despues queda en cero
        monto = 0.0
        try:
            monto = float(self.tree_ventas.item(sel[0])["values"][5]
                          .replace("$", "").replace(".", "").replace(",", "."))
        except (ValueError, IndexError, AttributeError):
            pass

        ok = anular_venta(vid)
        if ok:
            from repositorio import registrar_bitacora
            registrar_bitacora("Anulacion de venta", responsable,
                               f"Venta #{vid} anulada, stock restaurado",
                               monto or None, vid)
        if ok:
            toast(self, f"Venta #{vid} anulada — stock restaurado")
        else:
            messagebox.showwarning("Error", "La venta ya estaba anulada.", parent=self)
        self.refrescar()

"""
caja_ui.py — Gestión de caja TPV v2.0
Fixes: stock correcto al anular, movimientos en historial,
       notas visibles, alineación izquierda, refresh automático
"""

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

        btn(parent, "Actualizar", variante="neutro",
            comando=self._refrescar_historial).grid(
            row=1, column=0, sticky="w")

    # ── Datos ─────────────────────────────────────────────────────────────────

    def refrescar(self):
        self._refrescar_actual()
        self._refrescar_movimientos()
        self._refrescar_historial()

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
        for s in get_historial_sesiones():
            self.tree_hist.insert("", "end", values=(
                s["id"],
                s["apertura_en"][:16] if s["apertura_en"] else "—",
                s["cierre_en"][:16]   if s["cierre_en"]   else "—",
                s["cant_ventas"],
                f"$ {s['total_efectivo']:,.2f}",
                f"$ {s['total_tarjeta']:,.2f}",
                f"$ {s['total_qr']:,.2f}",
                f"$ {s['total_cuenta_corriente']:,.2f}",
                f"$ {s['total_general']:,.2f}",
                s["notas"] or "—",
            ))

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
        sesion = get_sesion_abierta()
        if not sesion:
            messagebox.showinfo("Info", "No hay sesion abierta.", parent=self)
            return

        sid = sesion["id"]
        _res = get_resumen_sesion(sid)
        resumen, ventas_res = _res["sesion"], _res["ventas"]
        total = (resumen["total_efectivo"] + resumen["total_tarjeta"] +
                 resumen["total_qr"]       + resumen["total_cuenta_corriente"])

        msg = (
            f"Resumen sesion #{sid}\n\n"
            f"Efectivo:        $ {resumen['total_efectivo']:,.2f}\n"
            f"Tarjeta:         $ {resumen['total_tarjeta']:,.2f}\n"
            f"QR:              $ {resumen['total_qr']:,.2f}\n"
            f"Cta. Corriente:  $ {resumen['total_cuenta_corriente']:,.2f}\n"
            f"{'─'*34}\n"
            f"TOTAL:           $ {total:,.2f}\n\n"
            f"Ventas: {ventas_res['cant'] or 0}\n\n"
            f"Confirmar cierre?"
        )
        if not messagebox.askyesno("Cerrar caja", msg, parent=self):
            return

        notas = self.entry_notas_cierre.get().strip()
        cerrar_sesion_caja(sid, notas)
        from logger import hacer_backup
        hacer_backup("cierre_caja")
        messagebox.showinfo("Caja cerrada",
            f"Sesion #{sid} cerrada.\nReinicia la aplicacion para abrir una nueva sesion.",
            parent=self)
        self.btn_cerrar.config(state="disabled")
        self.refrescar()

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
        if not messagebox.askyesno("Anular venta",
                                    f"Anular venta #{vid}?\nSe restaurara el stock.",
                                    parent=self):
            return
        ok = anular_venta(vid)
        if ok:
            toast(self, f"Venta #{vid} anulada — stock restaurado")
        else:
            messagebox.showwarning("Error", "La venta ya estaba anulada.", parent=self)
        self.refrescar()

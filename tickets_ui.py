"""
tickets_ui.py — Buscar tickets y ver qué se vendió en cada uno.

Responde "¿qué se llevó en esta venta?" tres días después, sin tener el
ticket de papel. Antes el detalle solo se veía desde Fiado, y únicamente
para clientes con cuenta corriente.
"""

import datetime
import tkinter as tk
from tkinter import ttk, messagebox

from styles import C, F, btn, lbl, tabla
from repositorio import buscar_tickets, get_venta_completa


COLS = [
    ("id",      "Ticket",      75,  "e"),
    ("fecha",   "Fecha",       130, "w"),
    ("items",   "Ítems",       60,  "e"),
    ("total",   "Total",       105, "e"),
    ("metodo",  "Pago",        130, "w"),
    ("cliente", "Cliente",     140, "w"),
    ("prods",   "Productos",   330, "w"),
]

METODOS = {
    "efectivo": "Efectivo", "tarjeta": "Tarjeta", "qr": "QR",
    "mixto": "Mixto", "cuenta_corriente": "Cuenta corriente",
}


class TicketsUI(ttk.Frame):

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._filas = []
        self._construir()
        self.after(120, self.refrescar)

    def _construir(self):
        cab = tk.Frame(self, bg=C.bg)
        cab.pack(fill="x", padx=12, pady=(10, 2))
        lbl(cab, "Tickets", variante="titulo").pack(side="left")
        self.lbl_tot = lbl(cab, "", variante="subtitulo")
        self.lbl_tot.pack(side="right")

        lbl(self, "Doble clic en un ticket para ver qué se llevó, a qué "
                  "precio y cuánto pesó.", variante="suave").pack(
            anchor="w", padx=12)

        # El pie va primero y anclado abajo: si se empaqueta después, la
        # tabla se estira y lo empuja fuera de la ventana.
        pie = tk.Frame(self, bg=C.bg)
        pie.pack(side="bottom", fill="x", padx=12, pady=(6, 10))
        btn(pie, "🧾  Ver detalle", variante="primario",
            comando=self._ver_detalle).pack(side="left")
        self.lbl_pie = lbl(pie, "", variante="suave")
        self.lbl_pie.pack(side="left", padx=12)

        bar = tk.Frame(self, bg=C.bg)
        bar.pack(fill="x", padx=12, pady=(8, 6))

        hoy = datetime.date.today()
        lbl(bar, "Desde:", variante="suave").pack(side="left")
        self.v_desde = tk.StringVar(value=hoy.isoformat())
        tk.Entry(bar, textvariable=self.v_desde, width=11, font=F.normal,
                 bg=C.superficie, fg=C.texto, relief="solid",
                 bd=1).pack(side="left", padx=4)
        lbl(bar, "Hasta:", variante="suave").pack(side="left", padx=(8, 0))
        self.v_hasta = tk.StringVar(value=hoy.isoformat())
        tk.Entry(bar, textvariable=self.v_hasta, width=11, font=F.normal,
                 bg=C.superficie, fg=C.texto, relief="solid",
                 bd=1).pack(side="left", padx=4)

        for txt, dias in (("Hoy", 0), ("7 días", 6), ("30 días", 29)):
            btn(bar, txt, variante="neutro",
                comando=lambda d=dias: self._rango(d)).pack(side="left", padx=2)

        lbl(bar, "Buscar:", variante="suave").pack(side="left", padx=(12, 4))
        self.v_texto = tk.StringVar()
        e = tk.Entry(bar, textvariable=self.v_texto, width=22, font=F.normal,
                     bg=C.superficie, fg=C.texto, relief="solid", bd=1)
        e.pack(side="left")
        e.bind("<Return>", lambda ev: self.refrescar())
        lbl(bar, "(N° de ticket o producto)",
            variante="suave").pack(side="left", padx=6)
        btn(bar, "Actualizar", variante="neutro",
            comando=self.refrescar).pack(side="right")

        cont = tk.Frame(self, bg=C.bg)
        cont.pack(fill="both", expand=True, padx=12)
        frame_t, self.tree = tabla(cont, COLS, altura=16)
        frame_t.pack(fill="both", expand=True)
        self.tree.tag_configure("anulada", foreground=C.peligro)
        self.tree.bind("<Double-1>", lambda e: self._ver_detalle())
        self.tree.bind("<Return>", lambda e: self._ver_detalle())

    def _rango(self, dias):
        hoy = datetime.date.today()
        self.v_desde.set((hoy - datetime.timedelta(days=dias)).isoformat())
        self.v_hasta.set(hoy.isoformat())
        self.refrescar()

    def refrescar(self):
        # La pantalla puede destruirse entre el after() y su ejecucion:
        # sin esta guarda Tk tira "invalid command name" en bucle.
        if not self.winfo_exists():
            return
        try:
            self._filas = buscar_tickets(
                self.v_desde.get().strip() or None,
                self.v_hasta.get().strip() or None,
                self.v_texto.get().strip())
        except Exception as exc:
            messagebox.showerror("Tickets", f"No se pudo buscar:\n{exc}",
                                 parent=self)
            return

        self.tree.delete(*self.tree.get_children())
        total = 0.0
        for i, t in enumerate(self._filas):
            metodo = METODOS.get(t["metodo_pago"], t["metodo_pago"])
            # Un pago repartido se muestra como tal: "Efectivo + fiado"
            # dice más que "Cuenta corriente" a secas.
            partes = [n for n, k in (("Efectivo", "monto_efectivo"),
                                     ("Tarjeta", "monto_tarjeta"),
                                     ("QR", "monto_qr"),
                                     ("fiado", "monto_cta_cte"))
                      if (t.get(k) or 0) > 0]
            if len(partes) > 1:
                metodo = " + ".join(partes)
            if not t["anulada"]:
                total += t["total"] or 0
            self.tree.insert(
                "", "end", iid=str(i),
                tags=("anulada",) if t["anulada"] else (),
                values=(
                    f"#{t['id']}" + (" ANUL." if t["anulada"] else ""),
                    (t["fecha"] or "")[:16], t["items"],
                    f"$ {t['total']:,.2f}", metodo,
                    (t["cliente"] or "—")[:20],
                    (t["productos"] or "")[:60]))

        self.lbl_tot.config(text=f"{len(self._filas)} ticket(s)   ·   "
                                 f"$ {total:,.2f}")
        anuladas = sum(1 for t in self._filas if t["anulada"])
        self.lbl_pie.config(
            text=(f"{anuladas} anulada(s) — no suman al total"
                  if anuladas else ""))

    def _ver_detalle(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Tickets", "Elegí un ticket de la lista.",
                                parent=self)
            return
        self._dialogo_detalle(self._filas[int(sel[0])]["id"])

    def _dialogo_detalle(self, venta_id):
        v = get_venta_completa(venta_id)
        if not v:
            return

        d = tk.Toplevel(self)
        d.title(f"Ticket #{venta_id}")
        d.configure(bg=C.superficie)
        d.grab_set()
        w = 620
        h = min(600, d.winfo_screenheight() - 100)
        sw, sh = d.winfo_screenwidth(), d.winfo_screenheight()
        d.geometry(f"{w}x{h}+{(sw-w)//2}+{max(0,(sh-h)//2)}")

        cab = tk.Frame(d, bg=C.superficie)
        cab.pack(fill="x", padx=18, pady=(16, 2))
        lbl(cab, f"Ticket #{venta_id}", variante="titulo",
            bg=C.superficie).pack(side="left")
        if v.get("anulada"):
            tk.Label(cab, text="  ANULADA  ", bg=C.peligro, fg=C.blanco,
                     font=F.subtitulo).pack(side="right")
        lbl(d, (v.get("fecha") or "")[:16]
               + (f"   ·   {v['cliente']}" if v.get("cliente") else ""),
            variante="suave", bg=C.superficie).pack(anchor="w", padx=18)

        pie = tk.Frame(d, bg=C.superficie)
        pie.pack(side="bottom", fill="x", pady=12)
        btn(pie, "Cerrar", variante="neutro",
            comando=d.destroy).pack(side="left", padx=18)

        def _reimprimir():
            from impresion import previsualizar_ticket
            previsualizar_ticket(d, venta_id)

        btn(pie, "🖨️  Reimprimir ticket", variante="primario",
            comando=_reimprimir).pack(side="left", padx=6)

        cols = [
            ("desc",   "Producto",   240, "w"),
            ("cant",   "Cant.",       80, "e"),
            ("precio", "Precio u.",   95, "e"),
            ("sub",    "Subtotal",   100, "e"),
        ]
        frame_t, tree = tabla(d, cols, altura=10)
        frame_t.pack(fill="both", expand=True, padx=18, pady=(10, 6))
        tree.tag_configure("promo", background=C.ok_flash)
        for it in v["items"]:
            cant = it["cantidad"]
            # Los de peso con 3 decimales y su unidad: "2" y "2 kg" son
            # cosas distintas cuando uno revisa qué se vendió.
            if it.get("vendido_por_peso"):
                txt_cant = f"{cant:.3f}".rstrip("0").rstrip(".") + " kg"
            else:
                txt_cant = f"{cant:g}"
            tree.insert("", "end",
                        tags=("promo",) if it.get("promo_aplicada") else (),
                        values=(it["descripcion"][:40], txt_cant,
                                f"$ {it['precio_unitario']:,.2f}",
                                f"$ {it['subtotal']:,.2f}"))

        res = tk.Frame(d, bg=C.acento, padx=16, pady=10)
        res.pack(fill="x", padx=18)
        lineas = []
        if v.get("descuento_pct"):
            lineas.append(f"Descuento aplicado: {v['descuento_pct']:g}%")
        # Cómo se pagó. En un pago repartido esto es lo que importa.
        pagos = [f"{n}: $ {v.get(k) or 0:,.2f}"
                 for n, k in (("Efectivo", "monto_efectivo"),
                              ("Tarjeta", "monto_tarjeta"),
                              ("QR", "monto_qr"),
                              ("Quedó fiado", "monto_cta_cte"))
                 if (v.get(k) or 0) > 0]
        lineas.append("   ·   ".join(pagos) if pagos
                      else METODOS.get(v["metodo_pago"], v["metodo_pago"]))
        lineas.append(f"Costo: $ {v['costo_total']:,.2f}   ·   "
                      f"Ganancia: $ {v['ganancia']:,.2f}")
        for txt in lineas:
            tk.Label(res, text=txt, bg=C.acento, fg=C.texto, font=F.normal,
                     anchor="w").pack(anchor="w")
        tk.Label(res, text=f"TOTAL:  $ {v['total']:,.2f}", bg=C.acento,
                 fg=C.texto, font=F.subtitulo, anchor="w").pack(
            anchor="w", pady=(4, 0))

        if v["devoluciones"]:
            dev = tk.Frame(d, bg=C.err_flash, padx=16, pady=8)
            dev.pack(fill="x", padx=18, pady=(6, 0))
            for x in v["devoluciones"]:
                tk.Label(dev, bg=C.err_flash, fg=C.peligro, font=F.pequeña,
                         anchor="w",
                         text=(f"Devolución del {(x['fecha'] or '')[:10]}: "
                               f"$ {x['total']:,.2f} — {x['motivo'] or ''}")
                         ).pack(anchor="w")

        d.bind("<Escape>", lambda ev: d.destroy())

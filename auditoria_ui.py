"""
auditoria_ui.py — Solapa "Auditoria" del grupo Productos.

Sigue la convencion del resto de los modulos del TPV:
    class XxxUI(ttk.Frame) con __init__(self, parent, app) y refrescar().
Se registran en main.py dentro de _construir_subtabs_productos().

Auditoria: corre auditoria.py contra el catalogo y lista los problemas de
precio (bajo costo, margen flojo, dispersion, escala invertida, variantes
dispares, categoria equivocada).

"""

import os
import re
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from styles import C, F, lbl, btn
import auditoria
import repositorio_auditoria as repo_aud



COLOR_SEV = {"CRITICO": "#FEE2E2", "ALTO": "#FEF3C7", "REVISAR": "#F3F4F6"}
_RE_PRECIO_SUG = re.compile(r"\$\s?([\d.]+,\d{2})")


# ══════════════════════════════════════════════════════════════════════════
# Solapa Auditoria
# ══════════════════════════════════════════════════════════════════════════

class AuditoriaUI(ttk.Frame):

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.hallazgos = []
        self._construir()
        self.after(150, self.refrescar)

    def _construir(self):
        cab = tk.Frame(self, bg=C.bg)
        cab.pack(fill="x", padx=12, pady=(10, 6))

        lbl(cab, "Auditoria de precios", variante="titulo").pack(side="left")
        self.lbl_resumen = lbl(cab, "", variante="subtitulo")
        self.lbl_resumen.pack(side="right")

        barra = tk.Frame(self, bg=C.bg)
        barra.pack(fill="x", padx=12, pady=(0, 8))
        btn(barra, "Actualizar", comando=self.refrescar).pack(side="left")
        btn(barra, "Aplicar precio sugerido", variante="exito",
            comando=self._aplicar).pack(side="left", padx=6)
        btn(barra, "No avisar mas", variante="neutro",
            comando=self._descartar).pack(side="left")
        btn(barra, "📌 Marcar para revisar", variante="neutro",
            comando=self._marcar_revisar).pack(side="left", padx=6)

        lbl(barra, "Ver:", variante="suave").pack(side="left", padx=(18, 4))
        self.filtro = tk.StringVar(value="TODOS")
        cb = ttk.Combobox(barra, textvariable=self.filtro, width=10, state="readonly",
                          values=("TODOS", "CRITICO", "ALTO", "REVISAR"))
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda e: self._pintar())

        cont = tk.Frame(self, bg=C.bg)
        cont.pack(fill="both", expand=True, padx=12, pady=(0, 10))

        cols = ("sev", "producto", "detalle", "sugerencia")
        self.tree = ttk.Treeview(cont, columns=cols, show="headings")
        for c_, t_, w_ in (("sev", "Severidad", 90), ("producto", "Producto", 250),
                           ("detalle", "Que pasa", 560), ("sugerencia", "Sugerencia", 250)):
            self.tree.heading(c_, text=t_)
            self.tree.column(c_, width=w_, anchor="w")
        for sev, color in COLOR_SEV.items():
            self.tree.tag_configure(sev, background=color)

        sb = ttk.Scrollbar(cont, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda e: self._detalle())

        self.lbl_pie = lbl(self, "", variante="suave")
        self.lbl_pie.pack(fill="x", padx=12, pady=(0, 8))

    # ── datos ──────────────────────────────────────────────────────────────

    def refrescar(self):
        # La pantalla puede destruirse entre el after() y su ejecucion:
        # sin esta guarda Tk tira "invalid command name" en bucle.
        if not self.winfo_exists():
            return
        try:
            productos = repo_aud.get_productos_auditoria()
            descartes = repo_aud.get_descartes()
        except Exception as exc:
            messagebox.showerror("Auditoria", f"No se pudo leer el catalogo:\n{exc}")
            return
        self.hallazgos = auditoria.ordenar(auditoria.auditar(productos, descartes))
        sin_costo = sum(1 for p in productos if not p.get("ultimo_costo"))
        sin_cont = len(auditoria.sin_contenido(productos))
        self.lbl_pie.config(
            text=(f"{len(productos)} productos analizados   ·   "
                  f"{sin_costo} sin costo cargado (no entran en las reglas de margen)   ·   "
                  f"{sin_cont} sin contenido reconocible (no entran en las de tamano)"))
        self._pintar()

    def _pintar(self):
        self.tree.delete(*self.tree.get_children())
        f = self.filtro.get()
        for i, h in enumerate(self.hallazgos):
            if f != "TODOS" and h.severidad != f:
                continue
            self.tree.insert("", "end", iid=str(i), tags=(h.severidad,),
                             values=(h.severidad, h.descripcion_corta,
                                     h.detalle, h.sugerencia))
        r = auditoria.resumen(self.hallazgos)
        self.lbl_resumen.config(
            text=f"{r['CRITICO']} criticos   ·   {r['ALTO']} altos   ·   {r['REVISAR']} a revisar")

    def _sel(self):
        s = self.tree.selection()
        return self.hallazgos[int(s[0])] if s else None

    def _detalle(self):
        h = self._sel()
        if h:
            messagebox.showinfo(h.descripcion_corta,
                                f"{h.severidad} — {h.regla}\n\n{h.detalle}\n\n{h.sugerencia}")

    def _aplicar(self):
        h = self._sel()
        if not h:
            messagebox.showinfo("Auditoria", "Elegi una fila primero.")
            return
        m = _RE_PRECIO_SUG.search(h.sugerencia or "")
        if not m:
            messagebox.showinfo("Auditoria",
                                "Este hallazgo no propone un precio concreto.\n"
                                "Corregilo desde Productos > Precios.")
            return
        nuevo = float(m.group(1).replace(".", "").replace(",", "."))
        if not messagebox.askyesno("Aplicar precio",
                                   f"{h.descripcion_corta}\n\nNuevo precio: ${nuevo:,.2f}\n\n"
                                   "Se actualiza precio_base. El costo y el margen no se tocan."):
            return
        try:
            repo_aud.actualizar_precio_base(h.producto_id, nuevo)
        except Exception as exc:
            messagebox.showerror("Auditoria", f"No se pudo guardar:\n{exc}")
            return
        self.refrescar()
        m_prec = getattr(self.app, "modulos", {}).get("Precios")
        if m_prec and hasattr(m_prec, "refrescar"):
            m_prec.refrescar()

    def _marcar_revisar(self):
        """Un hallazgo que no se resuelve ahora va a la cola de revision.

        Descartarlo lo silencia para siempre; esto lo deja anotado para
        volver, que es lo que uno quiere cuando el problema es real pero
        no es el momento de arreglarlo.
        """
        h = self._sel()
        if not h:
            messagebox.showinfo("Auditoria", "Elegi una fila primero.", parent=self)
            return
        from revision_ui import dialogo_marcar
        if dialogo_marcar(self, h.producto_id, h.descripcion_corta):
            messagebox.showinfo("Auditoria",
                                "Anotado en Productos → A revisar.", parent=self)

    def _descartar(self):
        h = self._sel()
        if not h:
            return
        if messagebox.askyesno("No avisar mas",
                               f"Dejar de avisar sobre:\n\n{h.descripcion_corta}\n({h.regla})"):
            repo_aud.guardar_descarte(h.clave_descarte, "revisado desde la solapa")
            self.refrescar()

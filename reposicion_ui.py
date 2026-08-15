"""
reposicion_ui.py — Solapa "Reposición" del grupo Productos.

Que comprar, calculado por velocidad de venta.

"Stock bajo" con un umbral fijo para todo el catalogo no sirve: 5
unidades de algo que sale 20 por dia es una urgencia y 5 de algo que sale
uno por mes es sobrestock. Lo que importa es cuantos DIAS dura lo que
hay, y eso sale de cruzar el stock con lo que se vendio.
"""

import datetime
import os
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from styles import C, F, btn, lbl, tabla, toast
from repositorio import get_reposicion, get_stock_muerto, valor_inventario


COLS = [
    ("urg",     "Estado",      95,  "w"),
    ("desc",    "Producto",    240, "w"),
    ("prov",    "Proveedor",   120, "w"),
    ("stock",   "Stock",       75,  "e"),
    ("pordia",  "Venta/día",   85,  "e"),
    ("dias",    "Dura (días)", 90,  "e"),
    ("sug",     "Comprar",     85,  "e"),
    ("costo",   "Te cuesta",   105, "e"),
]


COLS_MUERTO = [
    ("desc",    "Producto",      250, "w"),
    ("cat",     "Categoria",     120, "w"),
    ("stock",   "Stock",          80, "e"),
    ("costo",   "Costo unit.",   100, "e"),
    ("capital", "Plata parada",  115, "e"),
    ("sinvta",  "Sin vender",    120, "w"),
    ("desde",   "Ingresó",       100, "w"),
]


class ReposicionUI(ttk.Frame):
    """Dos caras del mismo problema: que falta comprar y que sobra."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._filas = []
        self._muerto = []
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True)
        self._tab_rep = ttk.Frame(nb)
        self._tab_muerto = ttk.Frame(nb)
        nb.add(self._tab_rep, text="  Qué reponer  ")
        nb.add(self._tab_muerto, text="  Plata parada  ")
        self._construir()
        self._construir_muerto()
        nb.bind("<<NotebookTabChanged>>", lambda e: self.refrescar())
        self.after(150, self.refrescar)

    def _construir(self):
        raiz = self._tab_rep
        cab = tk.Frame(raiz, bg=C.bg)
        cab.pack(fill="x", padx=12, pady=(10, 2))
        lbl(cab, "Qué reponer", variante="titulo").pack(side="left")
        self.lbl_total = lbl(cab, "", variante="subtitulo")
        self.lbl_total.pack(side="right")

        lbl(raiz, "Calculado con lo que se vendió, no con un umbral fijo: "
                  "importa cuántos días dura el stock, no cuántas unidades hay.",
            variante="suave").pack(anchor="w", padx=12)

        barra = tk.Frame(raiz, bg=C.bg)
        barra.pack(fill="x", padx=12, pady=(8, 6))

        lbl(barra, "Ventas de los últimos", variante="suave").pack(side="left")
        self.v_hist = tk.StringVar(value="30")
        ttk.Combobox(barra, textvariable=self.v_hist, width=5, state="readonly",
                     values=("7", "15", "30", "60", "90")).pack(side="left", padx=4)
        lbl(barra, "días   ·   quiero stock para", variante="suave").pack(side="left")
        self.v_cob = tk.StringVar(value="14")
        ttk.Combobox(barra, textvariable=self.v_cob, width=5, state="readonly",
                     values=("7", "14", "21", "30", "45")).pack(side="left", padx=4)
        lbl(barra, "días", variante="suave").pack(side="left")

        self.v_todos = tk.BooleanVar(value=False)
        tk.Checkbutton(barra, text="Ver también los que están bien",
                       variable=self.v_todos, bg=C.bg, fg=C.texto, font=F.normal,
                       selectcolor=C.bg, activebackground=C.bg,
                       command=self.refrescar).pack(side="left", padx=16)

        lbl(barra, "Proveedor:", variante="suave").pack(side="left", padx=(8, 4))
        self.v_prov = tk.StringVar(value="Todos")
        self.cb_prov = ttk.Combobox(barra, textvariable=self.v_prov, width=18,
                                    state="readonly", values=("Todos",))
        self.cb_prov.pack(side="left")
        self.cb_prov.bind("<<ComboboxSelected>>", lambda e: self._pintar())

        btn(barra, "Actualizar", variante="neutro",
            comando=self.refrescar).pack(side="right")

        for v in (self.v_hist, self.v_cob):
            v.trace_add("write", lambda *a: self.refrescar())

        cont = tk.Frame(raiz, bg=C.bg)
        cont.pack(fill="both", expand=True, padx=12)
        frame_t, self.tree = tabla(cont, COLS, altura=16)
        frame_t.pack(fill="both", expand=True)
        self.tree.tag_configure("sin stock", background=C.err_flash,
                                foreground=C.peligro)
        self.tree.tag_configure("urgente", background=C.advertencia)
        self.tree.tag_configure("reponer", background=C.acento)
        self.tree.tag_configure("sin ventas", foreground=C.texto_suave)

        self.lbl_pie = lbl(raiz, "", variante="suave")
        self.lbl_pie.pack(fill="x", padx=12, pady=(6, 0))

        ac = tk.Frame(raiz, bg=C.bg)
        ac.pack(fill="x", padx=12, pady=(6, 10))
        btn(ac, "📄  Exportar lista de compra", variante="exito",
            comando=self._exportar).pack(side="left")
        btn(ac, "📋  Copiar para WhatsApp", variante="neutro",
            comando=self._copiar).pack(side="left", padx=6)

    # ── Datos ─────────────────────────────────────────────────────────

    def refrescar(self):
        try:
            hist = int(self.v_hist.get() or 30)
            cob = int(self.v_cob.get() or 14)
        except ValueError:
            return
        try:
            self._filas = get_reposicion(hist, cob,
                                         solo_faltantes=not self.v_todos.get())
        except Exception as exc:
            messagebox.showerror("Reposición", f"No se pudo calcular:\n{exc}",
                                 parent=self)
            return

        self._refrescar_muerto()

        provs = sorted({f["proveedor"] for f in self._filas if f["proveedor"]})
        self.cb_prov.config(values=["Todos"] + provs)
        if self.v_prov.get() not in ["Todos"] + provs:
            self.v_prov.set("Todos")
        self._pintar()

    def _visibles(self):
        prov = self.v_prov.get()
        if prov == "Todos":
            return self._filas
        return [f for f in self._filas if f["proveedor"] == prov]

    def _pintar(self):
        filas = self._visibles()
        self.tree.delete(*self.tree.get_children())
        for i, r in enumerate(filas):
            dias = ("—" if r["dias_stock"] is None
                    else f"{r['dias_stock']:.1f}")
            self.tree.insert("", "end", iid=str(i), tags=(r["urgencia"],), values=(
                r["urgencia"],
                r["descripcion"][:42],
                r["proveedor"] or "—",
                f"{r['stock']:g}",
                f"{r['por_dia']:.2f}",
                dias,
                f"{r['sugerido']:g}" if r["sugerido"] else "—",
                f"$ {r['costo_reposicion']:,.2f}" if r["costo_reposicion"] else "—"))

        total = sum(r["costo_reposicion"] for r in filas)
        urgentes = [r for r in filas if r["urgencia"] in ("sin stock", "urgente")]
        sin_costo = [r for r in filas if r["sugerido"] and not r["costo_ultimo"]]
        self.lbl_total.config(text=f"Invertir: $ {total:,.2f}")
        pie = (f"{len(filas)} producto(s)   ·   {len(urgentes)} urgente(s)")
        if sin_costo:
            pie += (f"   ·   {len(sin_costo)} sin costo cargado "
                    f"(no suman al total)")
        self.lbl_pie.config(text=pie)

    # ── Salidas ───────────────────────────────────────────────────────

    def _texto_lista(self):
        filas = [f for f in self._visibles() if f["sugerido"]]
        if not filas:
            return None
        prov = self.v_prov.get()
        hoy = datetime.date.today().strftime("%d/%m/%Y")
        lineas = [f"Pedido {hoy}" + (f" — {prov}" if prov != "Todos" else ""), ""]
        por_prov = {}
        for f in filas:
            por_prov.setdefault(f["proveedor"] or "Sin proveedor", []).append(f)
        total = 0.0
        for nombre in sorted(por_prov):
            if prov == "Todos":
                lineas.append(f"*{nombre}*")
            for f in sorted(por_prov[nombre], key=lambda x: x["descripcion"]):
                lineas.append(f"  {f['sugerido']:g} x {f['descripcion']}")
                total += f["costo_reposicion"]
            lineas.append("")
        lineas.append(f"Estimado: $ {total:,.2f}")
        return "\n".join(lineas)

    def _copiar(self):
        txt = self._texto_lista()
        if not txt:
            messagebox.showinfo("Reposición", "No hay nada para reponer.",
                                parent=self)
            return
        self.clipboard_clear()
        self.clipboard_append(txt)
        toast(self, "Lista copiada — pegala en el WhatsApp del proveedor")

    def _exportar(self):
        filas = [f for f in self._visibles() if f["sugerido"]]
        if not filas:
            messagebox.showinfo("Reposición", "No hay nada para reponer.",
                                parent=self)
            return
        ruta = filedialog.asksaveasfilename(
            title="Guardar lista de compra", defaultextension=".csv",
            initialfile=f"reposicion_{datetime.date.today():%Y%m%d}.csv",
            filetypes=[("CSV", "*.csv")], parent=self)
        if not ruta:
            return
        import csv
        try:
            # utf-8-sig para que Excel no rompa los acentos
            with open(ruta, "w", newline="", encoding="utf-8-sig") as fh:
                wr = csv.writer(fh, delimiter=";")
                wr.writerow(["Proveedor", "Codigo", "Producto", "Stock",
                             "Venta por dia", "Dias que dura", "Comprar",
                             "Costo unitario", "Costo total"])
                for f in sorted(filas, key=lambda x: (x["proveedor"] or "",
                                                      x["descripcion"])):
                    wr.writerow([
                        f["proveedor"] or "", f["codigo"] or "", f["descripcion"],
                        f"{f['stock']:g}", f"{f['por_dia']:.2f}",
                        "" if f["dias_stock"] is None else f"{f['dias_stock']:.1f}",
                        f"{f['sugerido']:g}",
                        f"{f['costo_ultimo'] or 0:.2f}",
                        f"{f['costo_reposicion']:.2f}"])
        except Exception as exc:
            messagebox.showerror("Reposición", f"No se pudo guardar:\n{exc}",
                                 parent=self)
            return
        messagebox.showinfo("Reposición", f"Lista guardada:\n{ruta}", parent=self)
        try:
            os.startfile(os.path.dirname(ruta))
        except Exception:
            pass

    # ══════════════════════════════════════════════════════════════════
    # Plata parada — el reverso: lo que hay y no rota
    # ══════════════════════════════════════════════════════════════════

    def _construir_muerto(self):
        raiz = self._tab_muerto
        cab = tk.Frame(raiz, bg=C.bg)
        cab.pack(fill="x", padx=12, pady=(10, 2))
        lbl(cab, "Plata parada", variante="titulo").pack(side="left")
        self.lbl_cap = lbl(cab, "", variante="subtitulo")
        self.lbl_cap.pack(side="right")

        lbl(raiz, "Productos con stock que no se vendieron en el período. "
                  "No aparecen en ninguna alerta justamente porque no se "
                  "agotan: es capital dormido en góndola.",
            variante="suave").pack(anchor="w", padx=12)

        barra = tk.Frame(raiz, bg=C.bg)
        barra.pack(fill="x", padx=12, pady=(8, 6))
        lbl(barra, "Sin vender hace más de", variante="suave").pack(side="left")
        self.v_dias_m = tk.StringVar(value="90")
        ttk.Combobox(barra, textvariable=self.v_dias_m, width=5, state="readonly",
                     values=("30", "60", "90", "120", "180")).pack(side="left", padx=4)
        lbl(barra, "días   ·   con al menos", variante="suave").pack(side="left")
        self.v_min = tk.StringVar(value="0")
        ttk.Combobox(barra, textvariable=self.v_min, width=8, state="readonly",
                     values=("0", "5000", "10000", "50000")).pack(side="left", padx=4)
        lbl(barra, "$ parados", variante="suave").pack(side="left")
        btn(barra, "Actualizar", variante="neutro",
            comando=self._refrescar_muerto).pack(side="right")
        for v in (self.v_dias_m, self.v_min):
            v.trace_add("write", lambda *a: self._refrescar_muerto())

        cont = tk.Frame(raiz, bg=C.bg)
        cont.pack(fill="both", expand=True, padx=12)
        frame_t, self.tree_m = tabla(cont, COLS_MUERTO, altura=15)
        frame_t.pack(fill="both", expand=True)
        self.tree_m.tag_configure("nunca", background=C.err_flash)
        self.tree_m.tag_configure("viejo", background=C.advertencia)

        self.lbl_pie_m = lbl(raiz, "", variante="suave")
        self.lbl_pie_m.pack(fill="x", padx=12, pady=(6, 0))

        ac = tk.Frame(raiz, bg=C.bg)
        ac.pack(fill="x", padx=12, pady=(6, 10))
        btn(ac, "📌  Marcar para revisar", variante="exito",
            comando=self._marcar_revisar).pack(side="left")
        btn(ac, "📄  Exportar", variante="neutro",
            comando=self._exportar_muerto).pack(side="left", padx=6)

    def _refrescar_muerto(self):
        try:
            dias = int(self.v_dias_m.get() or 90)
            minimo = float(self.v_min.get() or 0)
        except ValueError:
            return
        try:
            self._muerto = get_stock_muerto(dias, minimo)
            inv = valor_inventario()
        except Exception as exc:
            messagebox.showerror("Plata parada", f"No se pudo calcular:\n{exc}",
                                 parent=self)
            return

        self.tree_m.delete(*self.tree_m.get_children())
        for i, r in enumerate(self._muerto):
            if r["dias_sin_vender"] is None:
                sinvta, tag = "nunca se vendió", "nunca"
            else:
                sinvta = f"hace {r['dias_sin_vender']} días"
                tag = "viejo" if r["dias_sin_vender"] > 180 else ""
            self.tree_m.insert("", "end", iid=str(i), tags=(tag,) if tag else (),
                               values=(
                r["descripcion"][:42], r["categoria"] or "—",
                f"{r['stock']:g}",
                f"$ {r['costo_ultimo'] or 0:,.2f}",
                f"$ {r['capital']:,.2f}",
                sinvta,
                (r["ingreso_mas_viejo"] or "")[:10]))

        parado = sum(r["capital"] for r in self._muerto)
        pct = (parado / inv["costo"] * 100) if inv["costo"] else 0
        self.lbl_cap.config(text=f"Dormido: $ {parado:,.2f}")
        self.lbl_pie_m.config(
            text=(f"{len(self._muerto)} producto(s)   ·   "
                  f"{pct:.0f}% del inventario, que vale $ {inv['costo']:,.2f} "
                  f"a costo y $ {inv['venta']:,.2f} a precio de venta"))

    def _sel_muerto(self):
        sel = self.tree_m.selection()
        if not sel:
            messagebox.showinfo("Plata parada", "Elegí al menos un producto.",
                                parent=self)
            return []
        return [self._muerto[int(i)] for i in sel]

    def _marcar_revisar(self):
        """Manda a la cola de revisión: liquidar, rematar o dejar de reponer."""
        filas = self._sel_muerto()
        if not filas:
            return
        from revision_ui import dialogo_marcar
        ids = [f["id"] for f in filas]
        desc = filas[0]["descripcion"] if len(filas) == 1 else ""
        if dialogo_marcar(self, ids, desc):
            toast(self, f"{len(ids)} producto(s) → Productos → A revisar")

    def _exportar_muerto(self):
        if not self._muerto:
            messagebox.showinfo("Plata parada", "No hay nada para exportar.",
                                parent=self)
            return
        ruta = filedialog.asksaveasfilename(
            title="Guardar", defaultextension=".csv",
            initialfile=f"plata_parada_{datetime.date.today():%Y%m%d}.csv",
            filetypes=[("CSV", "*.csv")], parent=self)
        if not ruta:
            return
        import csv
        try:
            with open(ruta, "w", newline="", encoding="utf-8-sig") as fh:
                wr = csv.writer(fh, delimiter=";")
                wr.writerow(["Producto", "Codigo", "Categoria", "Stock",
                             "Costo unitario", "Plata parada",
                             "Dias sin vender", "Ingreso mas viejo"])
                for r in self._muerto:
                    wr.writerow([
                        r["descripcion"], r["codigo"] or "", r["categoria"] or "",
                        f"{r['stock']:g}", f"{r['costo_ultimo'] or 0:.2f}",
                        f"{r['capital']:.2f}",
                        "" if r["dias_sin_vender"] is None else r["dias_sin_vender"],
                        (r["ingreso_mas_viejo"] or "")[:10]])
        except Exception as exc:
            messagebox.showerror("Plata parada", f"No se pudo guardar:\n{exc}",
                                 parent=self)
            return
        messagebox.showinfo("Plata parada", f"Guardado:\n{ruta}", parent=self)

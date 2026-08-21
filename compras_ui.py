"""
compras_ui.py — Lo que hay que comprar y no sale de la reposición.

Pedidos de clientes, insumos, cosas que se acordaron de paso: lo que no
tiene stock que medir porque nunca se compró.

Las etiquetas pendientes viven en Productos → Imprimir, con el resto de
las impresiones.
"""

import tkinter as tk
from tkinter import ttk, messagebox

from styles import C, F, btn, lbl, tabla, toast
from repositorio import (agregar_a_comprar, get_lista_compras,
                         marcar_comprado, borrar_de_compras,
                         limpiar_comprados)


COLS_LISTA = [
    ("ok",     "",            34,  "center"),
    ("texto",  "Qué comprar", 300, "w"),
    ("cant",   "Cantidad",    110, "w"),
    ("prov",   "Proveedor",   150, "w"),
    ("nota",   "Nota",        220, "w"),
]


class ComprasUI(ttk.Frame):

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._filas = []
        # Una sola pantalla: el notebook de una solapa era ruido visual
        # heredado de cuando esto tenía también las etiquetas.
        self._tab_lista = self
        self._construir_lista()
        self.after(150, self.refrescar)

    # ══════════════════════════════════════════════════════════════════
    # Para comprar
    # ══════════════════════════════════════════════════════════════════

    def _construir_lista(self):
        raiz = self._tab_lista
        cab = tk.Frame(raiz, bg=C.bg)
        cab.pack(fill="x", padx=12, pady=(10, 2))
        lbl(cab, "Para comprar", variante="titulo").pack(side="left")
        self.lbl_cont = lbl(cab, "", variante="subtitulo")
        self.lbl_cont.pack(side="right")

        lbl(raiz, "Lo que no sale de la reposición automática: bolsas, "
                  "rollos, lo que pidió un cliente. Clic en la primera "
                  "columna para tildar.", variante="suave").pack(
            anchor="w", padx=12)

        # El pie anclado abajo antes que la tabla, para que no lo empuje
        pie = tk.Frame(raiz, bg=C.bg)
        pie.pack(side="bottom", fill="x", padx=12, pady=(6, 10))
        btn(pie, "🗑  Quitar", variante="neutro",
            comando=self._quitar).pack(side="left")
        btn(pie, "Limpiar comprados", variante="neutro",
            comando=self._limpiar).pack(side="left", padx=6)
        btn(pie, "📋  Copiar para WhatsApp", variante="primario",
            comando=self._copiar).pack(side="right")

        alta = tk.Frame(raiz, bg=C.superficie, padx=12, pady=10,
                        highlightthickness=1, highlightbackground=C.borde)
        alta.pack(fill="x", padx=12, pady=(8, 6))
        alta.columnconfigure(0, weight=3)
        alta.columnconfigure(1, weight=1)
        alta.columnconfigure(2, weight=2)

        for i, etq in enumerate(("Qué comprar", "Cantidad", "Proveedor")):
            tk.Label(alta, text=etq, bg=C.superficie, fg=C.texto_suave,
                     font=F.pequeña, anchor="w").grid(row=0, column=i,
                                                      sticky="w", padx=(0, 8))
        self.v_texto = tk.StringVar()
        self.v_cant = tk.StringVar()
        self.v_prov = tk.StringVar()
        self.e_texto = tk.Entry(alta, textvariable=self.v_texto, font=F.normal,
                                bg=C.bg, fg=C.texto, relief="solid", bd=1)
        self.e_texto.grid(row=1, column=0, sticky="ew", padx=(0, 8), ipady=4)
        tk.Entry(alta, textvariable=self.v_cant, font=F.normal, bg=C.bg,
                 fg=C.texto, relief="solid", bd=1).grid(
            row=1, column=1, sticky="ew", padx=(0, 8), ipady=4)
        tk.Entry(alta, textvariable=self.v_prov, font=F.normal, bg=C.bg,
                 fg=C.texto, relief="solid", bd=1).grid(
            row=1, column=2, sticky="ew", padx=(0, 8), ipady=4)
        btn(alta, "➕ Anotar", variante="exito",
            comando=self._agregar).grid(row=1, column=3, padx=(4, 0))

        # Enter desde cualquier campo anota: se cargan varios seguidos
        for w in (self.e_texto,):
            w.bind("<Return>", lambda e: self._agregar())

        cont = tk.Frame(raiz, bg=C.bg)
        cont.pack(fill="both", expand=True, padx=12)
        frame_t, self.tree = tabla(cont, COLS_LISTA, altura=13)
        frame_t.pack(fill="both", expand=True)
        self.tree.configure(selectmode="extended")
        self.tree.tag_configure("comprado", foreground=C.texto_suave)
        self.tree.bind("<Button-1>", self._click)

    def _agregar(self):
        txt = self.v_texto.get().strip()
        if not txt:
            self.e_texto.focus_set()
            return
        agregar_a_comprar(txt, self.v_cant.get(), self.v_prov.get())
        self.v_texto.set("")
        self.v_cant.set("")
        # El proveedor NO se limpia: cargando varias cosas del mismo
        # proveedor, repetirlo cada vez es puro tecleo.
        self.e_texto.focus_set()
        self.refrescar()

    def _click(self, ev):
        """Clic en la primera columna: tilda o destilda."""
        if self.tree.identify_column(ev.x) != "#1":
            return
        iid = self.tree.identify_row(ev.y)
        if not iid:
            return
        f = self._filas[int(iid)]
        marcar_comprado(f["id"], not f["comprado"])
        self.refrescar()

    def _sel_ids(self):
        return [self._filas[int(i)]["id"] for i in self.tree.selection()]

    def _quitar(self):
        ids = self._sel_ids()
        if not ids:
            messagebox.showinfo("Para comprar", "Elegí uno o varios.",
                                parent=self)
            return
        borrar_de_compras(ids)
        self.refrescar()

    def _limpiar(self):
        n = limpiar_comprados()
        toast(self, f"{n} ítem(s) comprados salieron de la lista")
        self.refrescar()

    def _copiar(self):
        pendientes = [f for f in self._filas if not f["comprado"]]
        if not pendientes:
            messagebox.showinfo("Para comprar", "No hay nada pendiente.",
                                parent=self)
            return
        # Agrupado por proveedor: así se manda un mensaje a cada uno
        por_prov = {}
        for f in pendientes:
            por_prov.setdefault(f["proveedor"] or "Sin proveedor", []).append(f)
        lineas = []
        for prov in sorted(por_prov):
            if len(por_prov) > 1:
                lineas.append(f"*{prov}*")
            for f in por_prov[prov]:
                cant = f"{f['cantidad']} " if f["cantidad"] else ""
                lineas.append(f"  {cant}{f['texto']}")
            lineas.append("")
        self.clipboard_clear()
        self.clipboard_append("\n".join(lineas).strip())
        toast(self, "Lista copiada")

    # ══════════════════════════════════════════════════════════════════

    def refrescar(self):
        try:
            self._filas = get_lista_compras(incluir_comprados=True)
        except Exception as exc:
            messagebox.showerror("Para comprar", f"No se pudo leer:\n{exc}",
                                 parent=self)
            return
        self.tree.delete(*self.tree.get_children())
        for i, f in enumerate(self._filas):
            self.tree.insert(
                "", "end", iid=str(i),
                tags=("comprado",) if f["comprado"] else (), values=(
                    "☑" if f["comprado"] else "☐",
                    f["texto"][:44], f.get("cantidad") or "",
                    f.get("proveedor") or "—", f.get("nota") or ""))
        pend = sum(1 for f in self._filas if not f["comprado"])
        self.lbl_cont.config(
            text=(f"{pend} pendiente(s)" if pend else "Todo comprado"))


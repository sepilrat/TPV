import tkinter as tk
from tkinter import ttk
import sqlite3

DB = "tpv.db"


def get_conn():
    return sqlite3.connect(DB)


class ProductosUI:

    def __init__(self, root):

        self.root = root

        frame = ttk.Frame(root, padding=10)
        frame.pack(fill="both", expand=True)

        # =========================
        # BUSCAR
        # =========================
        self.buscar = ttk.Entry(frame)
        self.buscar.pack(fill="x", pady=5)
        self.buscar.bind("<KeyRelease>", self.filtrar)

        # =========================
        # TABLA
        # =========================
        self.tree = ttk.Treeview(
            frame,
            columns=("desc", "precio"),
            show="headings"
        )

        self.tree.heading("desc", text="Descripción")
        self.tree.heading("precio", text="Precio")

        self.tree.column("desc", width=300)
        self.tree.column("precio", width=100, anchor="center")

        self.tree.pack(fill="both", expand=True)

        # doble click editar
        self.tree.bind("<Double-1>", self.editar_celda)

        self.entry_edit = None

        self.cargar_datos()

    # =========================
    # CARGAR
    # =========================

    def cargar_datos(self):

        for i in self.tree.get_children():
            self.tree.delete(i)

        conn = get_conn()
        cur = conn.cursor()

        cur.execute("SELECT id, descripcion, precio_unit FROM catalogo")

        for row in cur.fetchall():
            self.tree.insert("", tk.END, iid=row[0], values=(row[1], row[2]))

        conn.close()

    # =========================
    # FILTRAR
    # =========================

    def filtrar(self, event=None):

        texto = self.buscar.get()

        for i in self.tree.get_children():
            self.tree.delete(i)

        conn = get_conn()
        cur = conn.cursor()

        cur.execute("""
            SELECT id, descripcion, precio_unit
            FROM catalogo
            WHERE descripcion LIKE ?
        """, (f"%{texto}%",))

        for row in cur.fetchall():
            self.tree.insert("", tk.END, iid=row[0], values=(row[1], row[2]))

        conn.close()

    # =========================
    # EDITAR CELDA
    # =========================

    def editar_celda(self, event):

        item = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)

        # solo columna precio (#2)
        if col != "#2":
            return

        x, y, width, height = self.tree.bbox(item, col)

        valor_actual = self.tree.item(item, "values")[1]

        self.entry_edit = tk.Entry(self.tree)
        self.entry_edit.place(x=x, y=y, width=width, height=height)

        self.entry_edit.insert(0, valor_actual)
        self.entry_edit.focus()

        self.entry_edit.bind("<Return>", lambda e: self.guardar_edicion(item))
        self.entry_edit.bind("<Escape>", lambda e: self.cancelar_edicion())

    # =========================
    # GUARDAR EDICION
    # =========================

    def guardar_edicion(self, item):

        nuevo_valor = self.entry_edit.get()

        try:
            precio = float(nuevo_valor)
        except:
            self.cancelar_edicion()
            return

        producto_id = int(item)

        conn = get_conn()
        cur = conn.cursor()

        cur.execute("""
            UPDATE catalogo
            SET precio_unit = ?
            WHERE id = ?
        """, (precio, producto_id))

        conn.commit()
        conn.close()

        # actualizar UI
        valores = list(self.tree.item(item, "values"))
        valores[1] = precio
        self.tree.item(item, values=valores)

        self.entry_edit.destroy()
        self.entry_edit = None

    # =========================
    # CANCELAR
    # =========================

    def cancelar_edicion(self):

        if self.entry_edit:
            self.entry_edit.destroy()
            self.entry_edit = None
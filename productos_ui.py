import tkinter as tk
from tkinter import ttk
import sqlite3

DB = "tpv.db"


def get_conn():
    return sqlite3.connect(DB)


class ProductosUI:

    def __init__(self, root):

        self.root = root
        self.producto_id = None

        frame = ttk.Frame(root, padding=20)
        frame.pack(fill="both", expand=True)

        # =========================
        # BUSCAR
        # =========================
        self.buscar = ttk.Entry(frame)
        self.buscar.pack(fill="x", pady=5)
        self.buscar.bind("<KeyRelease>", self.filtrar)

        # =========================
        # LISTA
        # =========================
        self.tree = ttk.Treeview(frame, columns=("id", "desc", "precio"), show="headings")

        self.tree.heading("id", text="ID")
        self.tree.heading("desc", text="Descripción")
        self.tree.heading("precio", text="Precio")

        self.tree.pack(fill="both", expand=True, pady=10)

        self.tree.bind("<<TreeviewSelect>>", self.seleccionar)

        # =========================
        # EDICION
        # =========================
        edit = ttk.Frame(frame)
        edit.pack(fill="x", pady=10)

        ttk.Label(edit, text="Precio").grid(row=0, column=0, padx=5)

        self.precio = ttk.Entry(edit)
        self.precio.grid(row=0, column=1, padx=5)

        ttk.Button(edit, text="Guardar", command=self.guardar).grid(row=0, column=2, padx=5)

        # cargar datos
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
            self.tree.insert("", tk.END, values=row)

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
            self.tree.insert("", tk.END, values=row)

        conn.close()

    # =========================
    # SELECCIONAR
    # =========================

    def seleccionar(self, event):

        selected = self.tree.selection()

        if not selected:
            return

        item = self.tree.item(selected[0])
        datos = item["values"]

        self.producto_id = datos[0]

        self.precio.delete(0, tk.END)
        self.precio.insert(0, datos[2])

    # =========================
    # GUARDAR
    # =========================

    def guardar(self):

        if not self.producto_id:
            return

        try:
            precio = float(self.precio.get())
        except:
            return

        conn = get_conn()
        cur = conn.cursor()

        cur.execute("""
            UPDATE catalogo
            SET precio_unit = ?
            WHERE id = ?
        """, (precio, self.producto_id))

        conn.commit()
        conn.close()

        self.cargar_datos()
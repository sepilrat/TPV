import tkinter as tk
from tkinter import ttk
import sqlite3
from datetime import datetime, timedelta

DB = "tpv.db"


def get_conn():
    return sqlite3.connect(DB)


class StockReport:

    def __init__(self, root):

        frame = ttk.Frame(root, padding=10)
        frame.pack(fill="both", expand=True)

        # PARAMETROS
        top = ttk.Frame(frame)
        top.pack(fill="x")

        ttk.Label(top, text="Stock mínimo global").grid(row=0, column=0)
        self.min_stock = ttk.Entry(top, width=10)
        self.min_stock.insert(0, "5")
        self.min_stock.grid(row=0, column=1)

        ttk.Label(top, text="Días vencimiento").grid(row=0, column=2)
        self.dias = ttk.Entry(top, width=10)
        self.dias.insert(0, "7")
        self.dias.grid(row=0, column=3)

        ttk.Button(top, text="Actualizar", command=self.cargar).grid(row=0, column=4, padx=10)

        # TABLA
        self.tree = ttk.Treeview(frame, columns=("prod", "stock", "venc"), show="headings")
        self.tree.heading("prod", text="Producto")
        self.tree.heading("stock", text="Stock")
        self.tree.heading("venc", text="Vencimiento cercano")

        self.tree.pack(fill="both", expand=True)

        self.tree.tag_configure("critico", background="#ffcccc")
        self.tree.tag_configure("vencer", background="#ffe5b4")

        self.cargar()

    def cargar(self):

        self.tree.delete(*self.tree.get_children())

        min_stock = int(self.min_stock.get() or 5)
        dias = int(self.dias.get() or 7)

        limite = datetime.now() + timedelta(days=dias)

        conn = get_conn()
        cur = conn.cursor()

        cur.execute("""
            SELECT c.descripcion,
                   SUM(l.cantidad_actual),
                   MIN(l.fecha_vencimiento)
            FROM catalogo c
            LEFT JOIN lotes l ON l.producto_id = c.id
            GROUP BY c.id
        """)

        for desc, stock, venc in cur.fetchall():

            stock = stock or 0
            tag = ""

            if stock <= min_stock:
                tag = "critico"

            if venc:
                try:
                    fecha_v = datetime.strptime(venc, "%Y-%m-%d")
                    if fecha_v <= limite:
                        tag = "vencer"
                except:
                    pass

            self.tree.insert("", "end", values=(desc, stock, venc), tags=(tag,))

        conn.close()
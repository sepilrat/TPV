import tkinter as tk
from tkinter import ttk
import sqlite3
from datetime import datetime, timedelta

DB = "tpv.db"

def get_conn():
    return sqlite3.connect(DB)


class VentasReport:

    def __init__(self, root):

        frame = ttk.Frame(root, padding=10)
        frame.pack(fill="both", expand=True)

        top = ttk.Frame(frame)
        top.pack(fill="x")

        ttk.Label(top, text="Período (días)").grid(row=0, column=0)

        self.dias = ttk.Entry(top, width=10)
        self.dias.insert(0, "7")
        self.dias.grid(row=0, column=1)

        ttk.Button(top, text="Actualizar", command=self.cargar).grid(row=0, column=2)

        self.tree = ttk.Treeview(
            frame,
            columns=("prod","vend","stock","rotacion","margen"),
            show="headings"
        )

        self.tree.heading("prod", text="Producto")
        self.tree.heading("vend", text="Vendidos")
        self.tree.heading("stock", text="Stock")
        self.tree.heading("rotacion", text="Rotación")
        self.tree.heading("margen", text="Margen %")

        self.tree.pack(fill="both", expand=True)

        self.cargar()

    def cargar(self):

        self.tree.delete(*self.tree.get_children())

        dias = int(self.dias.get() or 7)
        desde = datetime.now() - timedelta(days=dias)

        conn = get_conn()
        cur = conn.cursor()

        cur.execute("""
            SELECT c.id, c.descripcion, c.precio_unit, c.costo_ultimo,
                   COALESCE(SUM(v.cantidad),0)
            FROM catalogo c
            LEFT JOIN ventas v ON v.producto = c.descripcion
            AND v.fecha >= ?
            GROUP BY c.id
        """, (desde.strftime("%Y-%m-%d"),))

        for pid, desc, precio, costo, vendidos in cur.fetchall():

            # stock
            cur.execute("SELECT COALESCE(SUM(cantidad_actual),0) FROM lotes WHERE producto_id=?", (pid,))
            stock = cur.fetchone()[0]

            rotacion = round(vendidos / stock, 2) if stock else 0

            margen = 0
            if precio and costo:
                margen = round(((precio - costo) / precio) * 100, 1)

            self.tree.insert(
                "",
                "end",
                values=(desc, vendidos, stock, rotacion, margen)
            )

        conn.close()
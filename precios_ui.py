import tkinter as tk
from tkinter import ttk, messagebox
import sqlite3

DB = "tpv.db"


def get_conn():
    return sqlite3.connect(DB)


class PreciosUI:

    def __init__(self, root):

        frame = ttk.Frame(root, padding=20)
        frame.pack(fill="both", expand=True)

        # =========================
        # MARGEN SOBRE COSTO
        # =========================
        ttk.Label(frame, text="Margen sobre costo (%)").grid(row=0, column=0, sticky="w")

        self.margen = ttk.Entry(frame)
        self.margen.insert(0, "30")
        self.margen.grid(row=0, column=1)

        ttk.Button(frame, text="Aplicar margen", command=self.aplicar_margen)\
            .grid(row=0, column=2, padx=10)

        # =========================
        # AUMENTO GLOBAL
        # =========================
        ttk.Label(frame, text="Aumento global (%)").grid(row=1, column=0, sticky="w")

        self.aumento = ttk.Entry(frame)
        self.aumento.insert(0, "10")
        self.aumento.grid(row=1, column=1)

        ttk.Button(frame, text="Aplicar aumento", command=self.aplicar_aumento)\
            .grid(row=1, column=2, padx=10)

        # =========================
        # INFO
        # =========================
        self.info = ttk.Label(frame, text="")
        self.info.grid(row=2, column=0, columnspan=3, pady=10)

    # =========================
    # LOGICA
    # =========================

    def aplicar_margen(self):

        try:
            margen = float(self.margen.get()) / 100
        except:
            return

        conn = get_conn()
        cur = conn.cursor()

        cur.execute("""
            UPDATE catalogo
            SET precio_unit = costo_ultimo * (1 + ?)
            WHERE costo_ultimo > 0
        """, (margen,))

        conn.commit()
        conn.close()

        self.info.config(text="✔ Precios actualizados por margen", foreground="green")

    def aplicar_aumento(self):

        try:
            aumento = float(self.aumento.get()) / 100
        except:
            return

        conn = get_conn()
        cur = conn.cursor()

        cur.execute("""
            UPDATE catalogo
            SET precio_unit = precio_unit * (1 + ?)
        """, (aumento,))

        conn.commit()
        conn.close()

        self.info.config(text="✔ Aumento aplicado", foreground="green")
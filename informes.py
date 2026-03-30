import tkinter as tk
from tkinter import ttk

import informes_stock
import informes_ventas


class InformesApp:

    def __init__(self, root):

        win = root
        notebook = ttk.Notebook(win)
        notebook.pack(fill="both", expand=True)

        tab_stock = tk.Frame(notebook)
        tab_ventas = tk.Frame(notebook)

        notebook.add(tab_stock, text="Stock")
        notebook.add(tab_ventas, text="Ventas")

        informes_stock.StockReport(tab_stock)
        informes_ventas.VentasReport(tab_ventas)
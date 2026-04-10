import tkinter as tk
from tkinter import ttk
from db import init_db
from ventas_ui import TPV
import ingreso
import informes_dashboard
import productos_ui
import precios_ui
class App:

    def __init__(self, root):

        root.title("TPV")
        root.geometry("1200x650")

        notebook = ttk.Notebook(root)
        notebook.pack(fill="both", expand=True)

        # VENTA
        tab_venta = tk.Frame(notebook)
        notebook.add(tab_venta, text="Venta")
        TPV(tab_venta)

        # PRODUCTOS
        tab_prod = tk.Frame(notebook)
        notebook.add(tab_prod, text="Productos")
        self.productos = productos_ui.ProductosUI(tab_prod)

        # STOCK
        tab_stock = tk.Frame(notebook)
        notebook.add(tab_stock, text="Stock")
        ingreso.IngresoStockApp(tab_stock)

        # PRECIOS
        tab_precios = tk.Frame(notebook)
        notebook.add(tab_precios, text="Precios")
        precios_ui.PreciosUI(tab_precios)
        # INFORMES
        tab_inf = tk.Frame(notebook)
        notebook.add(tab_inf, text="Informes")
        informes_dashboard.Dashboard(tab_inf)
        notebook.bind("<<NotebookTabChanged>>", self.on_tab_change)

    def on_tab_change(self, event):
     tab = event.widget.tab(event.widget.index("current"))["text"]
     if tab == "Productos":
            self.productos.cargar_datos()

def mostrar_alertas(root):

    import sqlite3
    from datetime import datetime, timedelta

    conn = sqlite3.connect("tpv.db")
    cur = conn.cursor()

    criticos = 0
    vencer = 0

    limite = datetime.now() + timedelta(days=7)

    cur.execute("SELECT id FROM catalogo")

    for (pid,) in cur.fetchall():

        cur.execute("SELECT COALESCE(SUM(cantidad_actual),0) FROM lotes WHERE producto_id=?", (pid,))
        stock = cur.fetchone()[0]

        if stock <= 0:
            criticos += 1

        cur.execute("""
            SELECT fecha_vencimiento
            FROM lotes
            WHERE producto_id=? AND fecha_vencimiento IS NOT NULL
            ORDER BY fecha_vencimiento ASC
            LIMIT 1
        """, (pid,))

        row = cur.fetchone()

        if row:
            try:
                if datetime.strptime(row[0], "%Y-%m-%d") <= limite:
                    vencer += 1
            except:
                pass

    conn.close()

    if criticos or vencer:
        win = tk.Toplevel(root)
        win.title("Alertas")

        msg = f"Críticos: {criticos}\nPor vencer: {vencer}"

        tk.Label(win, text=msg, font=("Arial", 12)).pack(padx=20, pady=20)

    
        
if __name__ == "__main__":
    init_db()
    root = tk.Tk()
    App(root)
    root.mainloop()
    mostrar_alertas
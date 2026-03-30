import tkinter as tk
from tkinter import ttk
import sqlite3
from datetime import datetime
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

DB = "tpv.db"

def get_conn():
    return sqlite3.connect(DB)


class Dashboard:

    def __init__(self, root):

        container = tk.Frame(root)
        container.pack(fill="both", expand=True)

        # ===============================
        # MENU LATERAL
        # ===============================
        menu = tk.Frame(container, width=200, bg="#2c3e50")
        menu.pack(side="left", fill="y")

        # ===============================
        # PANEL PRINCIPAL
        # ===============================
        self.panel = tk.Frame(container)
        self.panel.pack(side="right", fill="both", expand=True)

        def limpiar():
            for w in self.panel.winfo_children():
                w.destroy()

        # ===============================
        # DASHBOARD
        # ===============================
        def dashboard():

            limpiar()

            conn = get_conn()
            cur = conn.cursor()

            hoy = datetime.now().strftime("%Y-%m-%d")

            # ventas hoy
            cur.execute("""
                SELECT SUM(total) FROM ventas
                WHERE date(fecha)=?
            """, (hoy,))
            ventas_hoy = cur.fetchone()[0] or 0

            # ventas mes
            cur.execute("""
                SELECT SUM(total) FROM ventas
                WHERE strftime('%m',fecha)=strftime('%m','now')
            """)
            ventas_mes = cur.fetchone()[0] or 0

            # tickets
            cur.execute("""
                SELECT COUNT(DISTINCT fecha) FROM ventas
            """)
            tickets = cur.fetchone()[0] or 0

            ticket_prom = ventas_mes / tickets if tickets else 0

            conn.close()

            f = tk.Frame(self.panel)
            f.pack(pady=40)

            def card(titulo, valor):
                c = tk.Frame(f, bd=1, relief="solid", padx=20, pady=20, bg="white")
                c.pack(side="left", padx=10)

                tk.Label(c, text=titulo, bg="white").pack()
                tk.Label(c, text=f"$ {valor:,.0f}", font=("Arial", 18, "bold"), bg="white").pack()

            card("Ventas hoy", ventas_hoy)
            card("Ventas mes", ventas_mes)
            card("Ticket promedio", ticket_prom)
            card("Tickets", tickets)

        # ===============================
        # VENTAS POR DIA
        # ===============================
        def ventas_dia():

            limpiar()

            conn = get_conn()
            cur = conn.cursor()

            cur.execute("""
                SELECT date(fecha), SUM(total)
                FROM ventas
                GROUP BY date(fecha)
            """)

            data = cur.fetchall()
            conn.close()

            fechas = [x[0] for x in data]
            valores = [x[1] for x in data]

            fig = plt.Figure(figsize=(8, 4))
            ax = fig.add_subplot(111)

            ax.bar(fechas, valores)
            ax.set_title("Ventas por día")

            canvas = FigureCanvasTkAgg(fig, self.panel)
            canvas.get_tk_widget().pack(fill="both", expand=True)

        # ===============================
        # TOP PRODUCTOS
        # ===============================
        def top_productos():

            limpiar()

            conn = get_conn()
            cur = conn.cursor()

            cur.execute("""
                SELECT producto, SUM(cantidad)
                FROM ventas
                GROUP BY producto
                ORDER BY SUM(cantidad) DESC
                LIMIT 30
            """)

            rows = cur.fetchall()
            conn.close()

            tree = ttk.Treeview(self.panel, columns=("p", "c"), show="headings")
            tree.heading("p", text="Producto")
            tree.heading("c", text="Cantidad")

            tree.pack(fill="both", expand=True)

            for r in rows:
                tree.insert("", tk.END, values=r)

        # ===============================
        # STOCK CRITICO
        # ===============================
        def stock_critico():

            limpiar()

            conn = get_conn()
            cur = conn.cursor()

            cur.execute("""
                SELECT c.descripcion, COALESCE(SUM(l.cantidad_actual),0)
                FROM catalogo c
                LEFT JOIN lotes l ON l.producto_id=c.id
                GROUP BY c.id
                HAVING SUM(l.cantidad_actual) <= 5
            """)

            rows = cur.fetchall()
            conn.close()

            tree = ttk.Treeview(self.panel, columns=("p", "s"), show="headings")
            tree.heading("p", text="Producto")
            tree.heading("s", text="Stock")

            tree.pack(fill="both", expand=True)

            for r in rows:
                tree.insert("", tk.END, values=r)

        # ===============================
        # BOTONES
        # ===============================
        def boton(txt, cmd):

            b = tk.Button(
                menu,
                text=txt,
                command=cmd,
                bg="#34495e",
                fg="white",
                relief="flat",
                height=2
            )
            b.pack(fill="x", pady=2)

        tk.Label(
            menu,
            text="INFORMES",
            bg="#2c3e50",
            fg="white",
            font=("Arial", 12, "bold")
        ).pack(pady=10)

        boton("Dashboard", dashboard)
        boton("Ventas por día", ventas_dia)
        boton("Top productos", top_productos)
        boton("Stock crítico", stock_critico)

        dashboard()
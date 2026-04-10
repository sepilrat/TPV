from modelo import guardar_venta, obtener_stock
from impresion import imprimir_ticket, listar_impresoras

import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox
import requests
from PIL import Image, ImageTk
from io import BytesIO
import winsound


# =========================
# DB
# =========================

def get_conn():
    return sqlite3.connect("tpv.db")


def buscar_producto_por_barra(codigo):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM catalogo WHERE cod_barra=?", (codigo,))
    row = cur.fetchone()
    conn.close()
    return row


def buscar_producto_por_codigo(codigo):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM catalogo WHERE codigo LIKE ?", (f"%{codigo}%",))
    rows = cur.fetchall()
    conn.close()
    return rows


def buscar_producto_por_texto(texto):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM catalogo WHERE descripcion LIKE ?", (f"%{texto}%",))
    rows = cur.fetchall()
    conn.close()
    return rows


# =========================
# LOGICA
# =========================

def limpiar_precio(v):
    return float(v) if v else 0


def calcular_precio(prod, cant):
    return limpiar_precio(prod[3])
    

# =========================
# APP
# =========================

class TPV:

    def __init__(self, root):

        self.root = root
        self.producto = None

        # ===== LAYOUT =====
        main = tk.Frame(root)
        main.pack(fill="both", expand=True, padx=10, pady=10)

        left = tk.Frame(main)
        left.pack(side="left", fill="both", expand=True)

        right = tk.Frame(main, width=300)
        right.pack(side="right", fill="y")

        # ===== INPUTS =====
        top = tk.Frame(left)
        top.pack(pady=10, anchor="w")

        def fila(label, row):
            tk.Label(top, text=label, width=15, anchor="w").grid(row=row, column=0, padx=5, pady=5)

        fila("Código Barras", 0)
        fila("Código Interno", 1)
        fila("Búsqueda", 2)

        self.e_barra = tk.Entry(top, font=("Arial", 14), width=25)
        self.e_codigo = tk.Entry(top, font=("Arial", 14), width=25)
        self.e_busqueda = tk.Entry(top, font=("Arial", 14), width=25)

        self.e_barra.grid(row=0, column=1)
        self.e_codigo.grid(row=1, column=1)
        self.e_busqueda.grid(row=2, column=1)

        self.e_barra.bind("<Return>", self.buscar_barra)
        self.e_codigo.bind("<Return>", self.buscar_codigo)
        self.e_busqueda.bind("<Return>", self.buscar_texto)

        # ===== CANTIDAD =====
        cant_frame = tk.Frame(left)
        cant_frame.pack(pady=5, anchor="w")

        tk.Label(cant_frame, text="Cantidad", width=15).grid(row=0, column=0)

        self.e_cant = tk.Entry(cant_frame, font=("Arial", 16), width=10)
        self.e_cant.grid(row=0, column=1)
        self.e_cant.insert(0, "1")
        self.e_cant.bind("<Return>", self.agregar)

        # ===== GRID =====
        columnas = ("producto", "cant", "precio", "total")
        self.tree = ttk.Treeview(left, columns=columnas, show="headings", height=15)

        for col in columnas:
            self.tree.heading(col, text=col.capitalize())

        self.tree.pack(fill="both", expand=True, pady=10)

        # ===== BOTONES =====
        btns = tk.Frame(left)
        btns.pack()

        tk.Button(btns, text="Eliminar", command=self.eliminar).grid(row=0, column=0, padx=10)
        tk.Button(btns, text="Cerrar Venta", command=self.cerrar_venta).grid(row=0, column=1, padx=10)

        self.total_label = tk.Label(left, text="TOTAL $ 0.00", font=("Arial", 28))
        self.total_label.pack(pady=10)

        # ===== PANEL DERECHO =====

        tk.Label(right, text="Impresora").pack(pady=5)

        self.impresoras = listar_impresoras()
        self.impresora_sel = tk.StringVar()
        self.impresora_sel.set(self.impresoras[0])

        tk.OptionMenu(right, self.impresora_sel, *self.impresoras).pack()

        tk.Label(right, text="Producto", font=("Arial", 14)).pack(pady=10)

        self.img = tk.Label(right)
        self.img.pack()

        self.desc_label = tk.Label(
            right,
            text="",
            font=("Arial", 14, "bold"),
            wraplength=250,
            justify="center"
        )
        self.desc_label.pack(pady=10)

        self.stock_label = tk.Label(
            right,
            text="Stock: 0",
            font=("Arial", 12),
            fg="blue"
        )
        self.stock_label.pack()

        self.e_barra.focus()

    # =========================
    # CORE
    # =========================

    def agregar_o_sumar(self, desc, cant, precio, prod):

        for item in self.tree.get_children():
            v = self.tree.item(item)["values"]

            if v[0] == desc:
                nueva = int(v[1]) + cant
                precio_unit = calcular_precio(prod, nueva)
                total = round(nueva * precio_unit, 2)
                self.tree.item(item, values=(desc, nueva, precio_unit, total))
                return

        total = round(cant * precio, 2)
        self.tree.insert("", tk.END, values=(desc, cant, precio, total))

    def recalcular_total(self):
        total = sum(float(self.tree.item(i)["values"][3]) for i in self.tree.get_children())
        self.total_label.config(text=f"TOTAL $ {total:,.2f}")

    def limpiar_campos(self):
        self.e_barra.delete(0, tk.END)
        self.e_codigo.delete(0, tk.END)
        self.e_busqueda.delete(0, tk.END)
        self.e_cant.delete(0, tk.END)

    # =========================
    # BUSQUEDA
    # =========================

    def mostrar_producto_info(self):

        self.desc_label.config(text=self.producto[2])

        stock = obtener_stock(self.producto[0])

        if stock <= 0:
            color = "red"
        elif stock < 5:
            color = "orange"
        else:
            color = "green"

        self.stock_label.config(text=f"Stock: {stock}", fg=color)

    def buscar_barra(self, event):

        codigo = self.e_barra.get().strip()
        cant = int(self.e_cant.get() or 1)

        prod = buscar_producto_por_barra(codigo)

        if not prod:
            return

        stock = obtener_stock(prod[0])

        if stock <= 0:
            messagebox.showerror("Stock", "❌ SIN STOCK")
            winsound.Beep(400, 300)
            return

        self.producto = prod
        self.mostrar_imagen()
        self.mostrar_producto_info()

        precio = calcular_precio(prod, cant)

        self.agregar_o_sumar(prod[2], cant, precio, prod)

        winsound.Beep(1000, 100)

        self.recalcular_total()
        self.limpiar_campos()

    def buscar_codigo(self, event):
        self.popup(buscar_producto_por_codigo(self.e_codigo.get()))

    def buscar_texto(self, event):
        self.popup(buscar_producto_por_texto(self.e_busqueda.get()))

    def popup(self, rows):

        if not rows:
            return

        win = tk.Toplevel(self.root)
        lista = tk.Listbox(win, width=80)
        lista.pack(fill="both", expand=True)

        for r in rows:
            lista.insert(tk.END, f"{r[1]} - {r[2]}")

        win.grab_set()
        lista.focus_set()
        lista.selection_set(0)

        def elegir(event=None):
            sel = lista.get(lista.curselection())
            codigo = sel.split(" - ")[0]

            prod = buscar_producto_por_codigo(codigo)[0]

            self.producto = prod
            self.mostrar_imagen()
            self.mostrar_producto_info()

            self.e_cant.delete(0, tk.END)
            self.e_cant.insert(0, "1")

            win.destroy()

        lista.bind("<Return>", elegir)
        lista.bind("<Double-Button-1>", elegir)

    # =========================
    # ACCIONES
    # =========================

    def agregar(self, event):

        if not self.producto:
            return

        cant = int(self.e_cant.get())

        stock = obtener_stock(self.producto[0])

        if stock < cant:
            messagebox.showerror("Stock", "❌ SIN STOCK SUFICIENTE")
            winsound.Beep(400, 300)
            return

        precio = calcular_precio(self.producto, cant)

        self.agregar_o_sumar(self.producto[2], cant, precio, self.producto)

        self.recalcular_total()
        self.limpiar_campos()

    def eliminar(self):
        for i in self.tree.selection():
            self.tree.delete(i)
        self.recalcular_total()

    def cerrar_venta(self):

        items = []
        total = 0

        for i in self.tree.get_children():

            v = self.tree.item(i)["values"]
            desc, cant, precio, total_item = v

            row = buscar_producto_por_texto(desc)[0]
            producto_id = row[0]

            stock = obtener_stock(producto_id)

        
        if stock < int(cant):
            messagebox.showerror(
                "Stock",
                f"Sin stock suficiente para:\n{desc}\nStock: {stock}"
            )
            return

        items.append((desc, int(cant), float(precio), float(total_item), row[7]))
        total += float(total_item)

   
        try:
            guardar_venta(items)
        except Exception as e:
            messagebox.showerror("Error", str(e))
            return

        imprimir_ticket(items, total, impresora=self.impresora_sel.get())

        messagebox.showinfo("Venta", f"Total: ${total:,.2f}")

        self.tree.delete(*self.tree.get_children())
        self.total_label.config(text="TOTAL $ 0.00")
    # =========================
    # IMAGEN
    # =========================

    def mostrar_imagen(self):

        try:
            url = self.producto[8]

            if not url:
                self.img.configure(image="")
                return

            r = requests.get(url, headers={"User-Agent": "Mozilla"}, timeout=3)

            img = Image.open(BytesIO(r.content)).convert("RGB")
            img.thumbnail((250, 250))

            self.photo = ImageTk.PhotoImage(img)

            self.img.configure(image=self.photo)
            self.img.image = self.photo

        except:
            self.img.configure(image="")
            self.img.image = None
import tkinter as tk
from tkinter import ttk
import sqlite3
from datetime import datetime
import requests

DB = "tpv.db"


def get_conn():
    return sqlite3.connect(DB)


def buscar_producto(codigo):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM catalogo WHERE cod_barra=?", (codigo,))
    row = cur.fetchone()
    conn.close()
    return row


def insertar_producto(data):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO catalogo 
        (codigo, descripcion, precio_unit, precio_3, precio_caja, unidades_caja, cod_barra)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, data)

    conn.commit()
    conn.close()


def buscar_producto_api(cod_barra):
    try:
        url = f"https://world.openfoodfacts.org/api/v0/product/{cod_barra}.json"
        r = requests.get(url, timeout=3)
        data = r.json()

        if data["status"] == 1:
            return {
                "descripcion": data["product"].get("product_name", "")
            }
    except:
        pass

    return None


def registrar_lote(producto_id, proveedor_id, cantidad, precio, vencimiento):

    conn = get_conn()
    cur = conn.cursor()

    fecha = datetime.now().strftime("%Y-%m-%d %H:%M")

    cur.execute("""
        INSERT INTO lotes 
        (producto_id, proveedor_id, fecha, cantidad, cantidad_actual, precio_compra, fecha_vencimiento)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (producto_id, proveedor_id, fecha, cantidad, cantidad, precio, vencimiento))

    conn.commit()
    conn.close()


def obtener_stock_total(producto_id):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT SUM(cantidad_actual) FROM lotes WHERE producto_id=?", (producto_id,))
    total = cur.fetchone()[0]

    conn.close()
    return total or 0


class IngresoStockApp:

    def __init__(self, root):

        self.root = root

        frame = ttk.Frame(root, padding=20)
        frame.pack(fill="both", expand=True)

        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="Código").grid(row=0, column=0, sticky="w")
        self.codigo = ttk.Entry(frame)
        self.codigo.grid(row=0, column=1, sticky="ew")
        self.codigo.bind("<Return>", self.buscar)

        ttk.Label(frame, text="Descripción").grid(row=1, column=0, sticky="w")
        self.desc = ttk.Entry(frame)
        self.desc.grid(row=1, column=1, sticky="ew")

        ttk.Label(frame, text="Cantidad").grid(row=2, column=0, sticky="w")
        self.cantidad = ttk.Entry(frame)
        self.cantidad.insert(0, "1")
        self.cantidad.grid(row=2, column=1, sticky="ew")

        ttk.Label(frame, text="Precio compra").grid(row=3, column=0, sticky="w")
        self.precio = ttk.Entry(frame)
        self.precio.grid(row=3, column=1, sticky="ew")

        ttk.Label(frame, text="Proveedor").grid(row=4, column=0, sticky="w")
        self.proveedor = ttk.Combobox(frame)
        self.proveedor["values"] = self.obtener_proveedores()
        self.proveedor.grid(row=4, column=1, sticky="ew")

        ttk.Label(frame, text="Vencimiento (YYYY-MM-DD)").grid(row=5, column=0, sticky="w")
        self.venc = ttk.Entry(frame)
        self.venc.grid(row=5, column=1, sticky="ew")

        ttk.Button(frame, text="Guardar", command=self.guardar).grid(row=6, column=0, columnspan=2, pady=5)
        ttk.Button(frame, text="Ver stock", command=self.ver_stock).grid(row=7, column=0, columnspan=2)

        self.info = ttk.Label(frame, text="")
        self.info.grid(row=8, column=0, columnspan=2)

    def buscar(self, e=None):

        codigo = self.codigo.get()
        producto = buscar_producto(codigo)

        if producto:
            self.desc.delete(0, tk.END)
            self.desc.insert(0, producto[2])
            self.info.config(text="✔ Producto existente", foreground="green")
            return

        datos = buscar_producto_api(codigo)

        if datos and datos.get("descripcion"):
            self.desc.delete(0, tk.END)
            self.desc.insert(0, datos["descripcion"])
            self.info.config(text="✔ Datos desde API", foreground="green")
        else:
            self.desc.delete(0, tk.END)
            self.info.config(text="⚠ No encontrado (API/local)", foreground="orange")

    def guardar(self):

        codigo = self.codigo.get()
        desc = self.desc.get()

        try:
            cantidad = int(self.cantidad.get() or 1)
        except:
            return

        try:
            precio = float(self.precio.get() or 0)
        except:
            precio = 0

        proveedor_nombre = self.proveedor.get()
        proveedor_id = self.obtener_o_crear_proveedor(proveedor_nombre)

        venc = self.venc.get() or None

        # VALIDACIÓN VENCIMIENTO
        if venc:
            try:
                fecha_v = datetime.strptime(venc, "%Y-%m-%d")
                if fecha_v.date() < datetime.now().date():
                    self.info.config(text="❌ Producto vencido", foreground="red")
                    return
            except:
                self.info.config(text="❌ Fecha inválida (YYYY-MM-DD)", foreground="red")
                return

        producto = buscar_producto(codigo)

        if not producto:
            insertar_producto((codigo, desc, 0, 0, 0, 1, codigo))
            producto = buscar_producto(codigo)

        
        registrar_lote(producto[0], proveedor_id, cantidad, precio, venc)
        # guardar último costo
        conn = get_conn()
        cur = conn.cursor()

        cur.execute("""
        UPDATE catalogo
        SET costo_ultimo = ?
        WHERE id = ?
        """, (precio, producto[0]))

        conn.commit()
        conn.close()
        stock = obtener_stock_total(producto[0])

        self.info.config(text=f"{desc} | Stock: {stock}", foreground="green")

        self.codigo.delete(0, tk.END)
        self.desc.delete(0, tk.END)
        self.precio.delete(0, tk.END)
        self.proveedor.set("")
        self.venc.delete(0, tk.END)
        self.cantidad.delete(0, tk.END)
        self.cantidad.insert(0, "1")
        self.codigo.focus()

    def ver_stock(self):

        win = tk.Toplevel(self.root)
        win.title("Stock")

        frame = ttk.Frame(win, padding=10)
        frame.pack(fill="both", expand=True)

        #  BUSCADOR
        ttk.Label(frame, text="Buscar").pack(anchor="w")
        buscador = ttk.Entry(frame)
        buscador.pack(fill="x")

        #  GRID
        tree = ttk.Treeview(frame, columns=("prod", "stock"), show="headings")
        tree.heading("prod", text="Producto")
        tree.heading("stock", text="Stock")
        tree.pack(fill="both", expand=True)

        tree.tag_configure("critico", background="#ffcccc")
        tree.tag_configure("bajo", background="#fff3cd")

        def cargar(filtro=""):

            tree.delete(*tree.get_children())

            conn = get_conn()
            cur = conn.cursor()

            cur.execute("""
                SELECT c.descripcion, SUM(l.cantidad_actual)
                FROM catalogo c
                LEFT JOIN lotes l ON l.producto_id = c.id
                WHERE c.descripcion LIKE ?
                GROUP BY c.id
                ORDER BY c.descripcion
            """, (f"%{filtro}%",))

            for desc, stock in cur.fetchall():

                stock = stock or 0

                if stock == 0:
                    tag = "critico"
                elif stock < 5:
                    tag = "bajo"
                else:
                    tag = ""

                tree.insert("", "end", values=(desc, stock), tags=(tag,))

            conn.close()

        #  filtro en vivo
        def on_key(e):
            cargar(buscador.get())

        buscador.bind("<KeyRelease>", on_key)

        # carga inicial
        cargar()

    def obtener_proveedores(self):
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT nombre FROM proveedores ORDER BY nombre")
        data = [r[0] for r in cur.fetchall()]
        conn.close()
        return data

    def obtener_o_crear_proveedor(self, nombre):
        if not nombre:
            return None

        conn = get_conn()
        cur = conn.cursor()

        cur.execute("SELECT id FROM proveedores WHERE nombre=?", (nombre,))
        row = cur.fetchone()

        if row:
            pid = row[0]
        else:
            cur.execute("INSERT INTO proveedores (nombre) VALUES (?)", (nombre,))
            pid = cur.lastrowid

        conn.commit()
        conn.close()
        return pid
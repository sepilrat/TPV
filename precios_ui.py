import tkinter as tk
from tkinter import ttk
import sqlite3

DB = "tpv.db"


def get_conn():
    return sqlite3.connect(DB)


class PreciosUI:

    def __init__(self, root):

        frame = ttk.Frame(root, padding=10)
        frame.pack(fill="both", expand=True)

        # CONTROLES
        ttk.Label(frame, text="Margen sobre costo (%)").grid(row=0, column=0)
        self.margen = ttk.Entry(frame)
        self.margen.insert(0, "30")
        self.margen.grid(row=0, column=1)

        ttk.Button(frame, text="Aplicar margen", command=self.aplicar_margen).grid(row=0, column=2)

        ttk.Label(frame, text="Aumento (%)").grid(row=1, column=0)
        self.aumento = ttk.Entry(frame)
        self.aumento.insert(0, "10")
        self.aumento.grid(row=1, column=1)

        ttk.Button(frame, text="Aplicar aumento", command=self.aplicar_aumento).grid(row=1, column=2)

        # FILTROS
        ttk.Label(frame, text="Categoría").grid(row=2, column=0)
        self.categoria = ttk.Combobox(frame)
        self.categoria["values"] = self.obtener_categorias()
        self.categoria.grid(row=2, column=1)

        ttk.Label(frame, text="Buscar").grid(row=3, column=0)
        self.buscar = ttk.Entry(frame)
        self.buscar.grid(row=3, column=1)
        self.buscar.bind("<KeyRelease>", self.filtrar)

        # TABLA
        self.tree = ttk.Treeview(frame, columns=("desc", "precio", "costo", "margen"), show="headings")

        self.tree.heading("desc", text="Producto")
        self.tree.heading("precio", text="Precio")
        self.tree.heading("costo", text="Costo")
        self.tree.heading("margen", text="Margen %")

        self.tree.grid(row=4, column=0, columnspan=3, sticky="nsew")

        frame.rowconfigure(4, weight=1)
        frame.columnconfigure(1, weight=1)

        # BOTONES
        ttk.Button(frame, text="Aplicar a seleccion", command=self.aplicar_seleccion).grid(row=5, column=0)
        ttk.Button(frame, text="Aplicar a filtrados", command=self.aplicar_filtrados).grid(row=5, column=1)
        ttk.Button(frame, text="Aplicar a todos", command=self.aplicar_todos).grid(row=5, column=2)

        self.tree.bind("<Double-1>", self.editar_celda)
        self.cargar()

    # =========================
    # DATA
    # =========================

    def obtener_categorias(self):
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT nombre FROM categorias")
        data = [r[0] for r in cur.fetchall()]
        conn.close()
        return data

    def calcular_margen(self, precio, costo):
        try:
            if costo and costo > 0:
                return round((precio / costo - 1) * 100, 2)
        except:
            pass
        return 0

    def cargar(self):

        self.tree.delete(*self.tree.get_children())

        conn = get_conn()
        cur = conn.cursor()

        cur.execute("SELECT id, descripcion, precio_unit, costo_ultimo FROM catalogo")

        for row in cur.fetchall():
            margen = self.calcular_margen(row[2], row[3])
            self.tree.insert("", "end", iid=row[0], values=(row[1], row[2], row[3], margen))

        conn.close()

    def filtrar(self, event=None):

        texto = self.buscar.get()
        categoria = self.categoria.get()

        self.tree.delete(*self.tree.get_children())

        conn = get_conn()
        cur = conn.cursor()

        query = """
        SELECT c.id, c.descripcion, c.precio_unit, c.costo_ultimo
        FROM catalogo c
        LEFT JOIN categorias cat ON cat.id = c.categoria_id
        WHERE c.descripcion LIKE ?
        """
        params = [f"%{texto}%"]

        if categoria:
            query += " AND cat.nombre = ?"
            params.append(categoria)

        cur.execute(query, params)

        for row in cur.fetchall():
            margen = self.calcular_margen(row[2], row[3])
            self.tree.insert("", "end", iid=row[0], values=(row[1], row[2], row[3], margen))

        conn.close()

    # =========================
    # LOGICA
    # =========================

    def get_factor(self):
        try:
            aumento = float(self.aumento.get()) / 100
            return 1 + aumento
        except:
            return 1

    def aplicar_aumento(self):
        factor = self.get_factor()

        conn = get_conn()
        cur = conn.cursor()

        cur.execute("UPDATE catalogo SET precio_unit = precio_unit * ?", (factor,))

        conn.commit()
        conn.close()

        self.cargar()

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
        """, (margen,))

        conn.commit()
        conn.close()

        self.cargar()

    def aplicar_seleccion(self):
        factor = self.get_factor()

        conn = get_conn()
        cur = conn.cursor()

        for item in self.tree.selection():
            cur.execute("UPDATE catalogo SET precio_unit = precio_unit * ? WHERE id = ?", (factor, int(item)))

        conn.commit()
        conn.close()

        self.cargar()

    def aplicar_filtrados(self):
        factor = self.get_factor()

        conn = get_conn()
        cur = conn.cursor()

        for item in self.tree.get_children():
            cur.execute("UPDATE catalogo SET precio_unit = precio_unit * ? WHERE id = ?", (factor, int(item)))

        conn.commit()
        conn.close()

        self.cargar()

    def aplicar_todos(self):
        self.aplicar_aumento()
    
    def editar_celda(self, event):

        item = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)

        if col != "#4":  # columna margen
            return

        x, y, width, height = self.tree.bbox(item, col)

        valor_actual = self.tree.item(item, "values")[3]

        entry = tk.Entry(self.tree)
        entry.place(x=x, y=y, width=width, height=height)

        entry.insert(0, valor_actual)
        entry.focus()

        def guardar(event=None):
            try:
                margen = float(entry.get()) / 100
            except:
                entry.destroy()
                return

            conn = get_conn()
            cur = conn.cursor()

            # obtener costo
            cur.execute("SELECT costo_ultimo FROM catalogo WHERE id = ?", (int(item),))
            costo = cur.fetchone()[0]

            nuevo_precio = costo * (1 + margen)

            cur.execute("""
            UPDATE catalogo
            SET precio_unit = ?
            WHERE id = ?
            """, (nuevo_precio, int(item)))

            conn.commit()
            conn.close()

            entry.destroy()
            self.cargar()

        entry.bind("<Return>", guardar)
        entry.bind("<Escape>", lambda e: entry.destroy())
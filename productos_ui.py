import tkinter as tk
from tkinter import ttk
import sqlite3

DB = "tpv.db"


def get_conn():
    return sqlite3.connect(DB)


class ProductosUI:

    def __init__(self, root):

        self.root = root

        frame = ttk.Frame(root, padding=10)
        frame.pack(fill="both", expand=True)

        # =========================
        # BUSCAR
        # =========================
        self.buscar = ttk.Entry(frame)
        self.buscar.pack(fill="x", pady=5)
        self.buscar.bind("<KeyRelease>", self.filtrar)

        # =========================
        # TABLA
        # =========================
        self.tree = ttk.Treeview(
            frame,
            columns=("desc", "precio", "categoria"),
            show="headings"
        )

        self.tree.heading("desc", text="Descripción")
        self.tree.heading("precio", text="Precio")
        self.tree.heading("categoria", text="Categoría")

        self.tree.column("desc", width=300)
        self.tree.column("precio", width=100, anchor="center")
        self.tree.column("categoria", width=150, anchor="center")

        self.tree.pack(fill="both", expand=True)

        # doble click editar
        self.tree.bind("<Double-1>", self.editar_celda)

        self.entry_edit = None

        self.cargar_datos()

    # =========================
    # CARGAR
    # =========================

    def cargar_datos(self):

        self.tree.delete(*self.tree.get_children())

        conn = get_conn()
        cur = conn.cursor()

        cur.execute("""
        SELECT c.id, c.descripcion, c.precio_unit, COALESCE(cat.nombre,'')
        FROM catalogo c
        LEFT JOIN categorias cat ON cat.id = c.categoria_id
        """)

        for row in cur.fetchall():
            self.tree.insert("", tk.END, iid=row[0], values=(row[1], row[2], row[3]))

        conn.close()

    # =========================
    # FILTRAR
    # =========================

    def filtrar(self, event=None):

        texto = self.buscar.get()

        self.tree.delete(*self.tree.get_children())

        conn = get_conn()
        cur = conn.cursor()

        cur.execute("""
        SELECT c.id, c.descripcion, c.precio_unit, COALESCE(cat.nombre,'')
        FROM catalogo c
        LEFT JOIN categorias cat ON cat.id = c.categoria_id
        WHERE c.descripcion LIKE ?
        """, (f"%{texto}%",))

        for row in cur.fetchall():
            self.tree.insert("", tk.END, iid=row[0], values=(row[1], row[2], row[3]))

        conn.close()

    # =========================
    # CATEGORIAS
    # =========================

    def obtener_categorias(self):
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT id, nombre FROM categorias")
        data = cur.fetchall()
        conn.close()
        return data

    # =========================
    # EDITAR CELDA
    # =========================

    def editar_celda(self, event):

        item = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)

        if not item:
            return

        x, y, width, height = self.tree.bbox(item, col)

        # =========================
        # EDITAR PRECIO (#2)
        # =========================
        if col == "#2":

            valor_actual = self.tree.item(item, "values")[1]

            self.entry_edit = tk.Entry(self.tree)
            self.entry_edit.place(x=x, y=y, width=width, height=height)

            self.entry_edit.insert(0, valor_actual)
            self.entry_edit.focus()

            def guardar_precio(event=None):
                try:
                    precio = float(self.entry_edit.get())
                except:
                    self.cancelar_edicion()
                    return

                conn = get_conn()
                cur = conn.cursor()

                cur.execute("""
                    UPDATE catalogo
                    SET precio_unit = ?
                    WHERE id = ?
                """, (precio, int(item)))

                conn.commit()
                conn.close()

                valores = list(self.tree.item(item, "values"))
                valores[1] = precio
                self.tree.item(item, values=valores)

                self.entry_edit.destroy()
                self.entry_edit = None

            self.entry_edit.bind("<Return>", guardar_precio)
            self.entry_edit.bind("<Escape>", lambda e: self.cancelar_edicion())

        # =========================
        # EDITAR CATEGORIA (#3)
        # =========================
        elif col == "#3":

            categorias = self.obtener_categorias()

            combo = ttk.Combobox(self.tree)
            combo["values"] = [c[1] for c in categorias]

            combo.place(x=x, y=y, width=width, height=height)
            combo.focus()

            def guardar_categoria(event=None):
                nombre = combo.get()

                for cid, cname in categorias:
                    if cname == nombre:

                        conn = get_conn()
                        cur = conn.cursor()

                        cur.execute("""
                            UPDATE catalogo
                            SET categoria_id = ?
                            WHERE id = ?
                        """, (cid, int(item)))

                        conn.commit()
                        conn.close()

                        valores = list(self.tree.item(item, "values"))
                        valores[2] = nombre
                        self.tree.item(item, values=valores)

                        combo.destroy()
                        return

            combo.bind("<<ComboboxSelected>>", guardar_categoria)
            combo.bind("<Return>", guardar_categoria)
            combo.bind("<Escape>", lambda e: combo.destroy())

    # =========================
    # CANCELAR
    # =========================

    def cancelar_edicion(self):

        if self.entry_edit:
            self.entry_edit.destroy()
            self.entry_edit = None
class ProductosUI:

    def __init__(self, root):

        frame = ttk.Frame(root, padding=20)
        frame.pack(fill="both", expand=True)

        # búsqueda
        self.buscar = ttk.Entry(frame)
        self.buscar.pack(fill="x")
        self.buscar.bind("<KeyRelease>", self.filtrar)

        # lista
        self.tree = ttk.Treeview(frame, columns=("desc", "precio"), show="headings")
        self.tree.heading("desc", text="Descripción")
        self.tree.heading("precio", text="Precio")

        self.tree.pack(fill="both", expand=True)

        self.tree.bind("<<TreeviewSelect>>", self.cargar)

        # edición
        self.precio = ttk.Entry(frame)
        self.precio.pack()

        ttk.Button(frame, text="Guardar", command=self.guardar).pack()

        self.cargar_datos()
"""
ventas_ui.py — Módulo de ventas TPV v2.0
Layout adaptable por resolución de pantalla.
Soporta: efectivo, tarjeta, mixto, QR, cuenta corriente, cuenta corriente.
"""

import tkinter as tk
from tkinter import ttk, messagebox
import logging
import sys
import imagenes
from styles import C, F, btn, lbl, card, tabla, toast, header_seccion, scrollable
from repositorio import (resolver_codigo, get_precio_con_promo,
                         registrar_venta, get_stock_producto, get_productos)

METODOS_PAGO = [
    ("Efectivo",         "efectivo"),
    ("Tarjeta",          "tarjeta"),
    ("Mixto Ef+Tarj",    "mixto"),
    ("Parte y fía",      "mixto_cta"),
    ("QR",               "qr"),
    ("Cuenta Corriente", "cuenta_corriente"),
]

# Los tres de todos los dias, a un clic. El resto entra por "Otras
# formas": mostrar seis botones para usar siempre los mismos tres
# ocupa la mitad del panel y hace mas lento lo frecuente.
METODOS_FRECUENTES = ["efectivo", "qr", "cuenta_corriente"]

COLS_CARRITO = [
    ("desc",   "Producto",  300, "w"),
    ("cant",   "Cant.",      60, "e"),
    ("precio", "Precio",     85, "e"),
    ("sub",    "Subtotal",   85, "e"),
    ("promo",  "Promo",      50, "center"),
]


def _centrar_dialogo(d, w, h):
    sw = d.winfo_screenwidth()
    sh = d.winfo_screenheight()
    # Si el diálogo es más alto/ancho que la pantalla, antes quedaba con
    # la barra de título arriba del área visible — imposible de bajar.
    margen = 40
    w = min(w, sw - 20)
    h = min(h, sh - margen)
    x = max(0, (sw - w) // 2)
    y = max(0, (sh - h) // 2)
    d.geometry(f"{w}x{h}+{x}+{y}")


def _parse_cantidad(txt):
    """
    Parsea una cantidad ingresada por el usuario, aceptando decimales
    (con . o , como separador) para productos vendidos por peso.
    Retorna un float > 0, o None si no es válido.
    """
    try:
        val = float(txt.replace(",", "."))
    except (ValueError, AttributeError):
        return None
    return val if val > 0 else None


def _fmt_cant(v):
    """Formatea una cantidad: entera sin decimales, fraccionaria con
    hasta 3 decimales (sin ceros de más) — ej: 3 -> '3', 0.5 -> '0.5'."""
    v = float(v)
    if v == int(v):
        return str(int(v))
    return f"{v:.3f}".rstrip("0").rstrip(".")


class VentasUI(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app   = app
        self.carrito       = []
        self.cant_pendiente = None
        self.metodo        = tk.StringVar(value="efectivo")
        self._cliente_cta = None   # dict con datos del cliente fiado
        self._build()
        self._atajos()
        self._chequear_recargo()
        self.after(2000, self._vigilar_foco)
        self._instalar_captura_scanner()
        self.after(2500, self._rescatar_codigo_perdido)
        self.after(100, self.foco_scanner)

    def _chequear_recargo(self):
        """Cartel cuando rige un recargo por horario.

        El cajero tiene que saber que los precios que ve son los de la
        franja, no los de lista: si no, ante un reclamo no sabe que
        contestar.
        """
        try:
            from repositorio import recargo_vigente
            r = recargo_vigente()
        except Exception:
            r = None
        if r:
            self.lbl_recargo.config(
                text=(f"  ⏰  Rige «{r['nombre']}»: +{r['porcentaje']:g}% "
                      f"sobre los precios de lista  "))
            self.lbl_recargo.grid(row=3, column=0, sticky="ew", pady=(0, 6))
        else:
            self.lbl_recargo.grid_forget()
        # Se vuelve a mirar cada 5 minutos: la franja arranca sola
        self.after(300000, self._chequear_recargo)

    def _atajos(self):
        """Teclas de función para la caja.

        En el mostrador con cola atrás, soltar el teclado para buscar el
        mouse cuesta segundos en cada venta. Las F van al toplevel para
        que anden con el foco en cualquier campo, incluido el scanner.
        """
        # F12 (cobrar) ya estaba enganchado desde antes en _build: no se
        # duplica acá para no llamar dos veces a _cobrar.
        raiz = self.winfo_toplevel()

        def _si_visible(fn):
            """Las F se enganchan al toplevel, asi que llegan estando en
            cualquier pantalla. Sin esta guarda, F4 disparaba la balanza
            desde Stock y F2 pisaba el atajo de la pantalla que se veia.
            """
            def _wrap(ev=None):
                if not self.winfo_ismapped():
                    return None
                fn(ev)
                return "break"
            return _wrap

        for tecla, fn in (
                ("<F1>",     self._ayuda_atajos),
                ("<F2>",     lambda e: self.foco_scanner()),
                ("<F3>",     self._atajo_cantidad),
                ("<F4>",     lambda e: self._leer_balanza()),
                ("<F6>",     lambda e: self._nueva_venta()),
                ("<Delete>", self._atajo_quitar)):
            raiz.bind(tecla, _si_visible(fn), add="+")

    def _atajo_cantidad(self, event=None):
        """Pone el foco para tipear la cantidad del proximo escaneo."""
        self.entry_scan.delete(0, "end")
        self.entry_scan.focus_set()
        toast(self, "Escribí la cantidad y después escaneá el producto")
        return "break"

    def _atajo_quitar(self, event=None):
        """Supr saca del carrito el item seleccionado.

        Si se esta escribiendo en un campo con texto, Supr borra letras
        y no toca el carrito. El scanner es la excepcion: ahi el foco
        vive siempre, y si esta vacio Supr tiene que sacar del carrito.
        """
        foco = self.focus_get()
        if isinstance(foco, (tk.Entry, ttk.Entry)):
            en_scanner = foco is getattr(self, "entry_scan", None)
            if not en_scanner or foco.get().strip():
                return None      # hay texto para borrar: se respeta
        if not self.tree.selection():
            toast(self, "Elegí primero un ítem del carrito", error=True)
            return "break"
        self._quitar()
        return "break"

    def _ayuda_atajos(self, event=None):
        messagebox.showinfo(
            "Atajos de teclado",
            "F12   Cobrar\n"
            "F2    Volver al lector de código\n"
            "F3    Escribir una cantidad antes de escanear\n"
            "F4    Leer la balanza\n"
            "F6    Venta nueva (vacía el carrito)\n"
            "Supr  Sacar del carrito el ítem seleccionado\n\n"
            "F1    Esta ayuda\n\n"
            "También podés escribir la cantidad y un punto antes de "
            "escanear: 3. o 0,500*", parent=self)
        return "break"

    # ── Construcción adaptable ────────────────────────────────────────────────

    def _build(self):
        header_seccion(
            self, "Venta",
            "Escanea, o busca por nombre/codigo — cantidad con . o * antes (ej: 3. o 0,500*)  —  F12 cobrar  ·  F1 atajos"
        ).pack(fill="x", padx=12, pady=(8, 4))

        self._cont = tk.Frame(self, bg=C.bg)
        self._cont.pack(fill="both", expand=True)

        # Detectar resolución después del render para obtener valor correcto
        # Por defecto layout horizontal (dos columnas)
        self._modo_chico = False
        self._cont.columnconfigure(0, weight=3)
        self._cont.columnconfigure(1, weight=2)
        self._cont.rowconfigure(0, weight=1)
        self._panel_carrito(self._cont, row=0, col=0)
        self._panel_cobro(self._cont,   row=0, col=1)

        # Re-evaluar layout real después de que la ventana esté visible
        self.after(200, self._adaptar_layout)

    def _adaptar_layout(self):
        """Ajusta proporciones según resolución real de pantalla."""
        sw = self.winfo_screenwidth()
        # Solo aplicar modo chico si es realmente una pantalla chica
        if sw > 0 and sw <= 1366 and not self._modo_chico:
            self._modo_chico = True
            # En pantallas chicas ajustar pesos — carrito más grande
            self._cont.columnconfigure(0, weight=4)
            self._cont.columnconfigure(1, weight=2)

    def _panel_carrito(self, parent, row, col):
        p = tk.Frame(parent, bg=C.bg)
        p.grid(row=row, column=col, sticky="nsew",
               padx=(12, 6 if col == 0 else 12),
               pady=(0 if row > 0 else 12, 6 if row == 0 else 12))
        p.columnconfigure(0, weight=1)
        p.rowconfigure(1, weight=1)

        # Aviso de recargo por horario. Se crea siempre y se muestra solo
        # cuando rige: el cajero tiene que saber que los precios que ve
        # no son los de lista.
        self.lbl_promo_grupo = tk.Label(
            p, text="", bg=C.exito, fg=C.blanco,
            font=("Segoe UI", 10, "bold"), pady=5)

        self.lbl_recargo = tk.Label(
            p, text="", bg=C.advertencia, fg=C.blanco,
            font=("Segoe UI", 10, "bold"), pady=5)

        # Qué suele llevar el cliente junto con lo que ya tiene. Con
        # público de paso, subir el ticket promedio es la palanca: el
        # informe de "se venden juntos" existe hace rato, pero nadie lo
        # mira mientras cobra.
        self.lbl_sugerencias = tk.Label(
            p, text="", bg="#1E3A5F", fg=C.blanco,
            font=("Segoe UI", 10), pady=6, anchor="w", justify="left")

        # Scanner
        scan = card(p)
        scan.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        scan.columnconfigure(1, weight=1)

        self.lbl_cant = tk.Label(scan, text="x1", font=F.subtitulo,
                                  bg=C.acento, fg=C.primario,
                                  padx=10, pady=8, width=4)
        self.lbl_cant.grid(row=0, column=0, sticky="ns")

        self.entry_scan = tk.Entry(scan, font=("Segoe UI", 13),
                                    bg=C.superficie, fg=C.texto,
                                    insertbackground=C.primario,
                                    relief="flat", bd=0)
        self.entry_scan.grid(row=0, column=1, sticky="ew", padx=12, ipady=8)
        self.entry_scan.bind("<Return>",     self._on_enter)
        self.entry_scan.bind("<KeyRelease>", self._on_key)

        lbl(scan, "Escanea o escribe nombre/codigo — 3. o 0,500* = cantidad (admite decimales)",
            variante="suave", bg=C.superficie).grid(row=0, column=2, padx=(0, 8))

        self.btn_balanza = btn(scan, "⚖️ Balanza", variante="neutro",
                               comando=self._leer_balanza)
        self.btn_balanza.grid(row=0, column=3, padx=(0, 8))

        # Tabla
        frame_t, self.tree = tabla(p, COLS_CARRITO)
        # La columna del arbol (#0) muestra la miniatura; las filas se
        # agrandan para que entre sin recortarse.
        self.tree.configure(show="tree headings")
        # 72px para una miniatura de 50: el resto es margen, si no la
        # foto queda pegada al nombre del producto.
        self.tree.column("#0", width=72, minwidth=72, stretch=False,
                         anchor="center")
        try:
            # La fila tiene que ser mas alta que la miniatura, si no Tk
            # la recorta por arriba y por abajo.
            ttk.Style().configure("Treeview", rowheight=56)
        except Exception:
            pass
        frame_t.grid(row=1, column=0, sticky="nsew")
        self.tree.bind("<Delete>",   self._quitar)
        self.tree.bind("<Double-1>", self._editar_cant)

        # Acciones
        ac = tk.Frame(p, bg=C.bg)
        ac.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        btn(ac, "Quitar",          variante="peligro", comando=self._quitar).pack(side="left")
        btn(ac, "Editar cantidad", variante="neutro",  comando=self._editar_cant).pack(side="left", padx=6)
        btn(ac, "Nueva venta",     variante="neutro",  comando=self._nueva_venta).pack(side="right")

    def _panel_cobro(self, parent, row, col):
        # Contenedor externo con borde
        p = card(parent)
        p.grid(row=row, column=col, sticky="nsew",
               padx=(6, 12), pady=(0 if row > 0 else 12, 12))
        p.columnconfigure(0, weight=1)
        p.rowconfigure(0, weight=1)
        p.rowconfigure(1, weight=0)  # botón cobrar fijo

        # Área scrollable
        scroll_outer, s = scrollable(p, bg=C.superficie)
        scroll_outer.grid(row=0, column=0, sticky="nsew")
        s.columnconfigure(0, weight=1)

        # Total
        font_total = ("Segoe UI", 20 if self._modo_chico else 28, "bold")
        f = tk.Frame(s, bg=C.superficie)
        f.pack(fill="x", padx=16, pady=(16, 6))
        lbl(f, "TOTAL", variante="suave", bg=C.superficie).pack(anchor="w")
        self.lbl_total = tk.Label(f, text="$ 0,00", font=font_total,
                                   bg=C.superficie, fg=C.primario)
        self.lbl_total.pack(anchor="w")
        self.lbl_items = lbl(f, "0 items", variante="suave", bg=C.superficie)
        self.lbl_items.pack(anchor="w")

        # Cliente fiado (oculto por defecto)
        self.frame_cliente = tk.Frame(s, bg=C.acento)
        self.lbl_cliente = lbl(self.frame_cliente, "", variante="suave",
                                bg=C.acento, fg=C.primario, padx=12, pady=4)
        self.lbl_cliente.pack(anchor="w")

        ttk.Separator(s, orient="horizontal").pack(fill="x", padx=16, pady=6)

        # Métodos de pago
        fp = tk.Frame(s, bg=C.superficie)
        fp.pack(fill="x", padx=16)
        lbl(fp, "Metodo de pago", variante="subtitulo",
            bg=C.superficie).pack(anchor="w", pady=(0, 4))

        # En modo chico: botones en grid 2 columnas para ahorrar espacio
        if self._modo_chico:
            grid_f = tk.Frame(fp, bg=C.superficie)
            grid_f.pack(fill="x")
            grid_f.columnconfigure(0, weight=1)
            grid_f.columnconfigure(1, weight=1)
            self.btns_pago = {}
            frecuentes = [(l, v) for l, v in METODOS_PAGO
                          if v in METODOS_FRECUENTES]
            for i, (label, valor) in enumerate(frecuentes):
                b = tk.Button(grid_f, text=label, font=F.pequeña,
                              relief="flat", cursor="hand2", pady=5,
                              command=lambda v=valor: self._sel_metodo(v))
                b.grid(row=i//2, column=i%2, sticky="ew", padx=2, pady=2)
                self.btns_pago[valor] = b
            b = tk.Button(grid_f, text="Otras formas…", font=F.pequeña,
                          relief="flat", cursor="hand2", pady=5,
                          command=self._dialogo_otros_metodos)
            b.grid(row=len(frecuentes)//2, column=len(frecuentes)%2,
                   sticky="ew", padx=2, pady=2)
        else:
            self.btns_pago = {}
            for label, valor in METODOS_PAGO:
                if valor not in METODOS_FRECUENTES:
                    continue
                b = tk.Button(fp, text=label, font=F.normal, relief="flat",
                              cursor="hand2", padx=12, pady=6, anchor="w",
                              command=lambda v=valor: self._sel_metodo(v))
                b.pack(fill="x", pady=1)
                self.btns_pago[valor] = b
            self.btn_otros = tk.Button(
                fp, text="Otras formas de pago…", font=F.normal,
                relief="flat", cursor="hand2", padx=12, pady=6, anchor="w",
                fg=C.texto_suave, command=self._dialogo_otros_metodos)
            self.btn_otros.pack(fill="x", pady=(6, 1))

        # Panel efectivo — recibido / vuelto
        self.frame_efectivo = tk.Frame(fp, bg=C.acento)
        lbl(self.frame_efectivo, "Recibí $", variante="suave",
            bg=C.acento).pack(side="left", padx=(8, 4))
        self.entry_recibido = tk.Entry(
            self.frame_efectivo, width=9, justify="right",
            font=F.normal, bg=C.superficie, fg=C.texto,
            relief="solid", bd=1)
        self.entry_recibido.pack(side="left", ipady=4, pady=6)
        self.entry_recibido.bind("<KeyRelease>", self._on_recibido_key)
        self.lbl_vuelto = lbl(self.frame_efectivo, "", variante="suave",
                              bg=C.acento, padx=8)
        self.lbl_vuelto.pack(side="left")

        # Panel mixto
        self.frame_mixto = tk.Frame(fp, bg=C.acento)
        lbl(self.frame_mixto, "Efectivo $", variante="suave",
            bg=C.acento).pack(side="left", padx=(8, 4))
        self.entry_efectivo_mixto = tk.Entry(
            self.frame_mixto, width=9, justify="right",
            font=F.normal, bg=C.superficie, fg=C.texto,
            relief="solid", bd=1)
        self.entry_efectivo_mixto.pack(side="left", ipady=4, pady=6)
        self.entry_efectivo_mixto.bind("<KeyRelease>", self._on_mixto_key)
        self.lbl_resto = lbl(self.frame_mixto, "", variante="suave",
                              bg=C.acento, padx=8)
        self.lbl_resto.pack(side="left")

        self._sel_metodo("efectivo")

        ttk.Separator(s, orient="horizontal").pack(fill="x", padx=16, pady=6)

        # Descuento
        fd = tk.Frame(s, bg=C.superficie)
        fd.pack(fill="x", padx=16)
        lbl(fd, "Descuento", variante="suave", bg=C.superficie).pack(side="left")
        self.entry_desc = tk.Entry(fd, width=8, justify="center",
                                    font=F.normal, bg=C.superficie,
                                    fg=C.texto, relief="solid", bd=1)
        self.entry_desc.insert(0, "0")
        self.entry_desc.pack(side="left", padx=8)
        self.entry_desc.bind("<KeyRelease>", lambda e: self._actualizar_totales())

        # % o $: redondear "$500 de descuento" a un porcentaje da numeros
        # con decimales que despues no cierran contra lo que se cobro.
        self.desc_modo = tk.StringVar(value="%")
        for txt in ("%", "$"):
            tk.Radiobutton(fd, text=txt, variable=self.desc_modo, value=txt,
                           bg=C.superficie, fg=C.texto, font=F.normal,
                           selectcolor=C.superficie,
                           activebackground=C.superficie,
                           command=self._actualizar_totales).pack(side="left")

        ttk.Separator(s, orient="horizontal").pack(fill="x", padx=16, pady=6)

        # Promos activas
        self.frame_promos = tk.Frame(s, bg=C.superficie)
        self.frame_promos.pack(fill="x", padx=16, pady=(0, 8))

        # ── Botón COBRAR fijo abajo — compacto para no tapar contenido ─────
        fc = tk.Frame(p, bg=C.superficie,
                      highlightbackground=C.borde, highlightthickness=1)
        fc.grid(row=1, column=0, sticky="ew")

        self.btn_cobrar = tk.Button(
            fc, text="COBRAR  (F12)",
            font=("Segoe UI", 11, "bold"),
            bg=C.exito, fg=C.blanco, relief="flat", cursor="hand2",
            pady=8, command=self._cobrar)
        self.btn_cobrar.pack(fill="x", padx=8, pady=6)
        self.btn_cobrar.bind("<Enter>", lambda e: self.btn_cobrar.config(bg=C.exito_h))
        self.btn_cobrar.bind("<Leave>", lambda e: self.btn_cobrar.config(bg=C.exito))
        # bind_all captura la tecla en TODA la app, incluso dentro de un
        # dialogo abierto: F12 llegaba a cobrar desde cualquier pantalla.
        self.winfo_toplevel().bind(
            "<F12>",
            lambda e: (self._cobrar(), "break")[1] if self.winfo_ismapped()
            else None, add="+")

    # ── Scanner ───────────────────────────────────────────────────────────────

    def foco_scanner(self):
        self.entry_scan.focus_set()
        # El cursor al final: si quedo texto a medias, lo que se escanee
        # despues se pega atras y el codigo sale mal.
        try:
            self.entry_scan.icursor("end")
        except Exception:
            pass

    def _instalar_captura_scanner(self):
        """El escaneo tiene prioridad sobre todo lo demás.

        Regla: en la pantalla de venta, un código escaneado SIEMPRE se
        registra, esté donde esté el foco. Un producto que no entra al
        carrito se va sin cobrar, y eso es peor que cualquier molestia
        de tipeo.

        Cómo se distingue un lector de una persona: el lector manda las
        teclas a menos de 50 ms una de otra. Apenas se detecta ese
        ritmo, TODO lo que sigue va al campo del scanner hasta el Enter,
        y el campo donde estaba el foco se deja como estaba.
        """
        import time as _t
        self._ult_tecla = [0.0]
        self._en_scaneo = [False]
        # Contenido de cada campo antes de la última tecla: sirve para
        # deshacer los caracteres que alcanzaron a caer ahí.
        self._valor_previo = {}

        def _recordar(ev):
            w = ev.widget
            if isinstance(w, (tk.Entry, ttk.Entry)) and not self._en_scaneo[0]:
                try:
                    self._valor_previo[str(w)] = w.get()
                except Exception:
                    pass

        self.winfo_toplevel().bind("<KeyRelease>", _recordar, add="+")

        def _tecla(ev):
            if not self.winfo_ismapped():
                return
            # Con un diálogo abierto el teclado es de él: ahí se está
            # confirmando un cobro o cargando un peso.
            if self._hay_dialogo_abierto():
                # Y se corta el escaneo en curso: si el diálogo se abrió
                # en el medio, la marca quedaba en True para siempre y el
                # escaneo SIGUIENTE mandaba las teclas a un scanner que
                # ya no tenía el foco — el producto no se registraba.
                self._en_scaneo[0] = False
                return

            foco = self.focus_get()
            if foco is self.entry_scan:
                self._en_scaneo[0] = False
                return          # ya está donde tiene que estar

            ahora = _t.time()
            delta = ahora - self._ult_tecla[0]
            self._ult_tecla[0] = ahora

            # Fin del escaneo: Enter, o una pausa larga
            if ev.keysym in ("Return", "KP_Enter"):
                if self._en_scaneo[0]:
                    self._en_scaneo[0] = False
                    if getattr(self, "_timer_scan", None):
                        try:
                            self.after_cancel(self._timer_scan)
                        except Exception:
                            pass
                        self._timer_scan = None
                    self.entry_scan.focus_set()
                    self._on_enter(None)
                    return "break"
                return
            if delta > 0.3:
                self._en_scaneo[0] = False

            if len(ev.char) != 1 or not ev.char.isprintable():
                return

            # Una vez dentro del escaneo, TODAS las teclas van al scanner
            # hasta el Enter — sin volver a medir tiempos. Si se midiera
            # cada tecla, una demora del lector partiría el código al
            # medio y el producto no se registraría.
            if self._en_scaneo[0]:
                self.entry_scan.insert("end", ev.char)
                self.entry_scan.icursor("end")
                # Red de seguridad: si el lector no manda Enter (algunos
                # no lo mandan, o se pierde), a los 400 ms de silencio se
                # procesa igual. Un codigo escrito y nunca registrado es
                # exactamente el producto que se va sin cobrar.
                if getattr(self, "_timer_scan", None):
                    try:
                        self.after_cancel(self._timer_scan)
                    except Exception:
                        pass
                self._timer_scan = self.after(400, self._cerrar_scaneo)
                return "break"

            # Dos teclas a menos de 50ms: arrancó un escaneo
            if delta < 0.05:
                self._en_scaneo[0] = True
                # Las teclas que ya cayeron en el otro campo se deshacen
                try:
                    prev = self._valor_previo.get(str(foco))
                    if prev is not None and foco.get() != prev:
                        foco.delete(0, "end")
                        foco.insert(0, prev)
                except Exception:
                    pass
                # El código arranca limpio, con el carácter anterior y
                # este: los dos son parte del código.
                anterior = getattr(self, "_char_previo", "")
                self.entry_scan.delete(0, "end")
                self.entry_scan.insert(0, anterior + ev.char)
                self.entry_scan.focus_set()
                self.entry_scan.icursor("end")
                return "break"

            # Todavía no se sabe si es lector o persona: se guarda el
            # carácter por si la próxima tecla llega rápido.
            self._char_previo = ev.char

        # bindtags: se crea una etiqueta propia y se la pone PRIMERA en
        # los campos de esta pantalla. Un bind normal en el toplevel corre
        # DESPUES del widget —la tecla ya se escribio— y el "break" llega
        # tarde: por eso quedaba basura en el descuento.
        raiz = self.winfo_toplevel()
        raiz.bind_class("ScanPrio", "<Key>", _tecla)

        def _priorizar(w):
            # TODO widget que pueda tener el foco, no solo los campos de
            # texto: con el foco en la tabla del carrito el escaneo no
            # llegaba, y ese es el lugar donde queda el foco despues de
            # tocar una fila para editarla o quitarla.
            try:
                tags = list(w.bindtags())
                if "ScanPrio" not in tags:
                    w.bindtags(("ScanPrio",) + tuple(tags))
            except Exception:
                pass
            for hijo in w.winfo_children():
                _priorizar(hijo)

        _priorizar(self)
        # Los campos creados despues (dialogos que se cierran, filas que
        # se repintan) tambien tienen que quedar cubiertos.
        self.after(1500, lambda: _priorizar(self))

    def _cerrar_scaneo(self):
        """Procesa un código que quedó escrito sin Enter."""
        self._timer_scan = None
        if not getattr(self, "_en_scaneo", [False])[0]:
            return
        self._en_scaneo[0] = False
        if len(self.entry_scan.get().strip()) >= 3:
            self.entry_scan.focus_set()
            self._on_enter(None)

    def _rescatar_codigo_perdido(self):
        """Última red: un código que quedó tipeado en otro campo.

        Si por lo que sea la captura no llegó a tiempo, en algún campo va
        a quedar un número largo que no tiene sentido ahí: un descuento
        de 13 dígitos es un código de barras, no un descuento. Se lo saca
        de ahí y se lo registra.
        """
        try:
            # Con un diálogo abierto no se toca nada: el importe que se
            # está escribiendo ahí no es un código perdido.
            if self.winfo_ismapped() and not self._hay_dialogo_abierto():
                for campo in (self.entry_desc, getattr(self, "entry_recibido",
                                                       None)):
                    if campo is None:
                        continue
                    txt = campo.get().strip()
                    # 8 dígitos o más en un campo de importe: es un código
                    if len(txt) >= 8 and txt.isdigit():
                        campo.delete(0, "end")
                        campo.insert(0, "0")
                        self.entry_scan.delete(0, "end")
                        self.entry_scan.insert(0, txt)
                        self.entry_scan.focus_set()
                        self._on_enter(None)
                        break
        except Exception:
            pass
        self.after(700, self._rescatar_codigo_perdido)

    def _al_cerrar_dialogo(self):
        """Deja la caja lista después de cualquier diálogo.

        El foco se reclama VARIAS veces con un retardo: al destruir una
        ventana modal, Tk devuelve el foco por su cuenta un instante
        después y pisa el focus_set() inmediato. Con un solo intento el
        scanner queda sin foco y el producto siguiente no se registra.
        """
        try:
            if hasattr(self, "_en_scaneo"):
                self._en_scaneo[0] = False
            self.entry_scan.delete(0, "end")
        except Exception:
            pass

        def _reclamar(intento=0):
            try:
                if not self.winfo_exists() or not self.winfo_ismapped():
                    return
                if self._hay_dialogo_abierto():
                    return          # se abrió otro encima
                if self.focus_get() is not self.entry_scan:
                    self.entry_scan.focus_force()
                    self.entry_scan.icursor("end")
            except Exception:
                pass
            if intento < 4:
                self.after(80, lambda: _reclamar(intento + 1))

        _reclamar()

    def _hay_dialogo_abierto(self):
        """¿Hay una ventana encima esperando algo?

        Los diálogos cuelgan de distintos padres: el de peso es hijo de
        esta pantalla, otros del toplevel. Buscar en un solo lado hacía
        que el vigilante le robara el foco al diálogo de peso mientras
        se escribía la cantidad.
        """
        try:
            for padre in (self, self.winfo_toplevel()):
                for w in padre.winfo_children():
                    if isinstance(w, tk.Toplevel) and w.winfo_ismapped():
                        return True
        except Exception:
            pass
        return False

    def _vigilar_foco(self):
        """Red de seguridad: devuelve el foco al scanner solo.

        Hay veinte caminos que llaman a foco_scanner() y alcanza con que
        uno se olvide para que el cajero escanee contra la nada. Esto lo
        corrige aunque el camino falle.

        No se toca el foco si el cajero esta escribiendo en otro campo de
        la pantalla (cantidad, descuento) ni si hay un dialogo abierto:
        seria peor robarle el teclado en medio de una carga.
        """
        try:
            if self.winfo_ismapped():
                foco = self.focus_get()
                # Si el foco quedo en un campo de OTRA pantalla, el lector
                # escribe ahi y la venta no se registra aunque suene el
                # beep. Solo se respetan los campos de ESTA pantalla.
                if foco is not None and not str(foco).startswith(str(self)):
                    foco = None
                # Ningun foco, o el foco quedo en un widget que no acepta
                # texto (un boton, la tabla): el scanner no llegaria.
                # La lista de resultados y la tabla del carrito TAMBIEN
                # son foco valido: sin esto, al buscar un producto por
                # nombre el foco se lo robaba el scanner cada segundo y
                # medio — la pantalla titilaba y no se podia elegir nada.
                if foco is None or not isinstance(
                        foco, (tk.Entry, tk.Text, tk.Listbox, tk.Spinbox,
                               ttk.Combobox, ttk.Entry, ttk.Treeview)):
                    # Solo si no hay ventana modal encima
                    if not self._hay_dialogo_abierto():
                        # Si el scanner tiene texto viejo de un escaneo
                        # que se perdio, se limpia: dejarlo hace que el
                        # proximo codigo se pegue atras y no exista.
                        actual = self.entry_scan.get().strip()
                        if actual and actual == getattr(self, "_txt_previo", None):
                            self.entry_scan.delete(0, "end")
                        self._txt_previo = actual
                        self.entry_scan.focus_set()
        except Exception:
            pass
        # Cada 4 segundos alcanza: es una red de seguridad para cuando un
        # camino se olvida de devolver el foco, no algo que deba correr
        # encima del cajero mientras escribe.
        self.after(4000, self._vigilar_foco)

    def _leer_balanza(self):
        """
        Pide el peso a la balanza y lo deja cargado como cantidad
        pendiente — el mismo mecanismo que "3." o "0,500*" tipeado a
        mano. Después solo hay que escanear/escribir el producto.
        """
        from config import cfg
        if not cfg().get("balanza_activa"):
            messagebox.showinfo(
                "Balanza",
                "La balanza no está activada todavía.\n\n"
                "Andá a Config > Balanza para activarla y configurar "
                "el puerto (COM).", parent=self)
            return self.foco_scanner()

        import balanza
        self.btn_balanza.configure(state="disabled", text="Leyendo...")
        self.update_idletasks()
        peso, msg = balanza.leer_peso()
        self.btn_balanza.configure(state="normal", text="⚖️ Balanza")

        if peso is not None:
            self.cant_pendiente = round(peso, 3)
            self.lbl_cant.config(text=f"x{_fmt_cant(self.cant_pendiente)}")
        elif msg == "inestable":
            toast(self, "Balanza: el peso está inestable, esperá un "
                        "instante y probá de nuevo", error=True)
        else:
            messagebox.showwarning("Balanza", msg, parent=self)
        return self.foco_scanner()

    def _on_key(self, event):
        txt = self.entry_scan.get().strip()
        if txt and txt[-1] in (".", "*"):
            numero = txt[:-1]
            val = _parse_cantidad(numero)
            if val:
                self.cant_pendiente = val
                self.lbl_cant.config(text=f"x{_fmt_cant(val)}")
                self.entry_scan.delete(0, "end")
            return
        self.lbl_cant.config(
            text=f"x{_fmt_cant(self.cant_pendiente)}" if self.cant_pendiente else "x1")

    def _on_enter(self, event):
        if hasattr(self, "_en_scaneo"):
            self._en_scaneo[0] = False
        txt = self.entry_scan.get().strip()
        self.entry_scan.delete(0, "end")
        if not txt:
            return self.foco_scanner()
        if txt[-1] in (".", "*"):
            numero = txt[:-1]
            val = _parse_cantidad(numero)
            if val:
                self.cant_pendiente = val
                self.lbl_cant.config(text=f"x{_fmt_cant(val)}")
            return self.foco_scanner()
        self._agregar(txt)

    def _agregar(self, codigo):
        # resolver_codigo tambien reconoce presentaciones: el codigo de la
        # bolsa de 800 g devuelve el producto a granel con la cantidad y el
        # precio de la bolsa, en vez de 1 gramo a precio de gramo.
        prod = resolver_codigo(codigo)

        if not prod:
            # No matcheo como codigo exacto (caso tipico del lector de
            # codigo de barras) — probamos como busqueda por nombre o
            # codigo parcial, igual que en la pantalla de productos.
            # Siempre mostramos el listado para confirmar, aunque haya
            # un solo resultado: un match parcial puede no ser el
            # producto correcto (ej. falta la variedad/marca exacta).
            candidatos = get_productos(filtro=codigo)
            if candidatos:
                prod = self._elegir_producto(candidatos, codigo)
                if not prod:
                    return self.foco_scanner()

        # Precio en cero: el producto existe pero se regalaria. Se avisa
        # con la misma fuerza que si no existiera, porque la consecuencia
        # es la misma — el cliente se lo lleva sin pagarlo.
        # Vender por debajo del costo es plata que se pierde en cada
        # unidad. Se avisa ACA, en la caja, no al dia siguiente por mail.
        if prod and (prod.get("precio_base") or 0) > 0:
            try:
                from repositorio import costo_real_producto
                _costo = costo_real_producto(prod["id"])
            except Exception:
                _costo = 0
            _precio = float(prod.get("precio_base") or 0)
            if _costo > 0 and _precio < _costo:
                if not self._confirmar_perdida(prod, _precio, _costo):
                    return self.foco_scanner()

        if prod and not (prod.get("precio_base") or 0) > 0:
            self._flash(error=True)
            self._alertar_precio_cero(prod)
            return self.foco_scanner()

        if not prod:
            # Un toast se va solo y en el ritmo de la caja nadie lo mira:
            # el producto se termina yendo sin cobrar. Esto FRENA hasta
            # que alguien lo cierre a proposito.
            self._flash(error=True)
            self._alertar_no_encontrado(codigo)
            return self.foco_scanner()
        # Sin stock se AVISA, no se frena: hay productos que se venden
        # sin haber pasado nunca por ingreso de stock, y dejar al cliente
        # esperando en la caja por eso es peor que el descuadre.
        # El aviso concreto (cuanto queda) sale mas abajo, ya con la
        # cantidad calculada.

        pres = prod.get("_presentacion")
        # Si escanearon una bolsa cerrada, cada "unidad" son N gramos.
        factor = float(prod.get("_cantidad_sugerida") or 1)
        cant = (self.cant_pendiente or 1) * factor
        es_peso = bool(prod.get("vendido_por_peso"))

        # Producto por peso sin cantidad tipeada: hay que preguntar. Antes
        # entraba 1 kg por defecto, que casi nunca es lo que el cliente
        # se lleva — y si el cajero no lo notaba, se cobraba mal.
        # Una presentacion cerrada (una bolsa con su EAN) no se pesa: ya
        # trae su peso en el factor.
        precio_ajustado = None
        if es_peso and self.cant_pendiente is None and not pres:
            peso, precio_ajustado = self._pedir_peso(prod)
            if peso is None:
                self.cant_pendiente = None
                self.lbl_cant.config(text="x1")
                return self.foco_scanner()
            cant = peso

        if not es_peso and cant != int(cant):
            self._flash(error=True)
            toast(self,
                  f"{prod['descripcion']}: se vende por unidad, "
                  "la cantidad debe ser entera", error=True)
            self.cant_pendiente = None
            self.lbl_cant.config(text="x1")
            return self.foco_scanner()

        # Las presentaciones van en su propia linea del carrito: tienen otro
        # precio unitario, asi que no se pueden fusionar con el granel.
        clave_pres = pres["id"] if pres else None
        existente = next((i for i in self.carrito
                          if i["producto_id"] == prod["id"]
                          and i.get("presentacion_id") == clave_pres), None)
        cant_total = (existente["cantidad"] if existente else 0) + cant

        # El stock se AVISA aca, no se bloquea: hay productos que se
        # venden sin haber pasado nunca por ingreso de stock (los que se
        # cargaron a mano, los que se reponen sin registrar), y frenar la
        # venta por eso deja al cliente esperando en la caja.
        # Bloquear seria peor que el problema que resuelve.
        try:
            disponible = float(get_stock_producto(prod["id"]) or 0)
        except Exception:
            disponible = None
        if disponible is not None and cant_total > disponible + 0.001:
            unidad = "kg" if es_peso else "u"
            if disponible <= 0:
                aviso = f"⚠ {prod['descripcion']}: sin stock registrado"
            else:
                aviso = (f"⚠ {prod['descripcion']}: quedan {disponible:g} "
                         f"{unidad} y llevás {cant_total:g}")
            toast(self, aviso, error=True)

        if pres:
            # Precio fijo de la bolsa, prorrateado por gramo para que el
            # subtotal y el descuento de stock sigan cuadrando.
            precio = float(pres["precio"]) / factor
            promo = None
        else:
            precio, promo = get_precio_con_promo(prod["id"], cant_total)
            # Importe tipeado a mano: manda sobre el precio de lista, para
            # que el ticket diga el numero que se cobro y no uno redondeado
            # dos centavos abajo.
            if precio_ajustado:
                precio = precio_ajustado
                promo = None

        if existente:
            existente.update(cantidad=cant_total, precio_unitario=precio,
                             promo_aplicada=promo, subtotal=cant_total * precio)
        else:
            self.carrito.append(dict(
                producto_id=prod["id"],
                descripcion=(f"{prod['descripcion']} — {pres['descripcion']}"
                             if pres else prod["descripcion"]),
                cantidad=cant_total, precio_unitario=precio,
                promo_aplicada=promo, subtotal=cant_total * precio,
                vendido_por_peso=es_peso,
                presentacion_id=clave_pres))

        self.cant_pendiente = None
        self.lbl_cant.config(text="x1")
        # Las promos combinables se recalculan sobre TODO el carrito: al
        # agregar la tercera gaseosa, las dos anteriores tambien bajan.
        self._aplicar_promos_grupo()
        self._flash()
        self._actualizar_tabla()
        self._actualizar_totales()
        self.foco_scanner()

    def _confirmar_perdida(self, prod, precio, costo):
        """Avisa que ese producto se vende por debajo del costo.

        No lo prohibe: a veces se liquida algo a proposito. Pero tiene
        que ser una decision, no un descuido — y hasta ahora se enteraba
        al dia siguiente por el mail, con la venta ya hecha.
        """
        try:
            if sys.platform == "win32":
                import winsound
                winsound.Beep(420, 220)
            else:
                self.bell()
        except Exception:
            pass

        perdida = costo - precio
        d = tk.Toplevel(self)
        d.title("Se vende a pérdida")
        d.configure(bg=C.peligro)
        d.grab_set()
        d.transient(self.winfo_toplevel())
        w, h = 560, 330
        sw, sh = d.winfo_screenwidth(), d.winfo_screenheight()
        d.geometry(f"{w}x{h}+{(sw-w)//2}+{max(0,(sh-h)//3)}")

        tk.Label(d, text="⚠", bg=C.peligro, fg=C.blanco,
                 font=("Segoe UI", 40, "bold")).pack(pady=(14, 0))
        tk.Label(d, text="ESTE PRODUCTO SE VENDE A PÉRDIDA",
                 bg=C.peligro, fg=C.blanco,
                 font=("Segoe UI", 15, "bold")).pack()
        tk.Label(d, text=prod["descripcion"][:46], bg=C.peligro,
                 fg=C.blanco, font=("Segoe UI", 12)).pack(pady=(6, 0))
        tk.Label(d,
                 text=(f"Precio  $ {precio:,.2f}          "
                       f"Costo  $ {costo:,.2f}\n"
                       f"Se pierden $ {perdida:,.2f} por unidad"),
                 bg=C.peligro, fg=C.blanco, font=("Segoe UI", 12),
                 justify="center").pack(pady=(10, 0))

        res = {"seguir": False}

        def _corregir():
            """Se puede arreglar acá mismo: el cliente está esperando."""
            d.destroy()
            top = tk.Toplevel(self)
            top.title("Corregir precio")
            top.configure(bg=C.superficie)
            top.grab_set()
            top.geometry("420x220")
            lbl(top, prod["descripcion"][:40], variante="titulo",
                bg=C.superficie).pack(anchor="w", padx=18, pady=(16, 2))
            lbl(top, f"Costo actual: $ {costo:,.2f}", variante="suave",
                bg=C.superficie).pack(anchor="w", padx=18)
            v = tk.StringVar(value=f"{costo * 1.3:.2f}")
            e = tk.Entry(top, textvariable=v, font=F.subtitulo,
                         justify="center", bg=C.bg, fg=C.texto,
                         relief="solid", bd=1)
            e.pack(fill="x", padx=18, pady=(12, 4), ipady=5)
            lbl(top, "Sugerido: costo + 30%", variante="suave",
                bg=C.superficie).pack(anchor="w", padx=18)

            def ok(_ev=None):
                try:
                    nuevo = float(v.get().replace(",", "."))
                except ValueError:
                    return
                if nuevo <= 0:
                    return
                from repositorio import set_precio_base
                set_precio_base(prod["id"], nuevo)
                top.destroy()
                toast(self, f"Precio corregido: $ {nuevo:,.2f}. "
                            f"Escaneá de nuevo.")
                self.foco_scanner()

            e.bind("<Return>", ok)
            fb = tk.Frame(top, bg=C.superficie)
            fb.pack(side="bottom", pady=14)
            btn(fb, "Guardar  (Enter)", variante="exito",
                comando=ok).pack(side="left", padx=6)
            btn(fb, "Cancelar", variante="neutro",
                comando=top.destroy).pack(side="left")
            e.focus_set()
            e.select_range(0, "end")

        def _vender():
            res["seguir"] = True
            d.destroy()

        pie = tk.Frame(d, bg=C.peligro)
        pie.pack(side="bottom", pady=16)
        b1 = tk.Button(pie, text="Corregir el precio", command=_corregir,
                       font=("Segoe UI", 11, "bold"), bg=C.blanco,
                       fg=C.peligro, relief="flat", padx=16, pady=6,
                       cursor="hand2")
        b1.pack(side="left", padx=6)
        tk.Button(pie, text="Vender igual", command=_vender,
                  font=("Segoe UI", 11), bg=C.peligro, fg=C.blanco,
                  relief="solid", bd=1, padx=14, pady=6,
                  cursor="hand2").pack(side="left", padx=6)

        # Enter = corregir: lo mas probable es que sea un error
        d.bind("<Return>", lambda e: _corregir())
        d.bind("<Escape>", lambda e: d.destroy())
        b1.focus_set()
        self.wait_window(d)
        self._al_cerrar_dialogo()
        return res["seguir"]

    def _alertar_precio_cero(self, prod):
        """El producto existe pero está en $0: no se puede vender así."""
        try:
            if sys.platform == "win32":
                import winsound
                winsound.Beep(420, 250)
                winsound.Beep(300, 350)
            else:
                self.bell()
        except Exception:
            pass

        d = tk.Toplevel(self)
        d.title("Producto sin precio")
        d.configure(bg=C.peligro)
        d.grab_set()
        d.transient(self.winfo_toplevel())
        w, h = 540, 310
        sw, sh = d.winfo_screenwidth(), d.winfo_screenheight()
        d.geometry(f"{w}x{h}+{(sw-w)//2}+{max(0,(sh-h)//3)}")

        tk.Label(d, text="⚠", bg=C.peligro, fg=C.blanco,
                 font=("Segoe UI", 42, "bold")).pack(pady=(16, 0))
        tk.Label(d, text="ESTE PRODUCTO ESTÁ EN $ 0", bg=C.peligro,
                 fg=C.blanco, font=("Segoe UI", 16, "bold")).pack()
        tk.Label(d, text=prod["descripcion"][:44], bg=C.peligro, fg=C.blanco,
                 font=("Segoe UI", 12)).pack(pady=(6, 0))
        tk.Label(d, text="NO se agregó a la venta.\n"
                         "Poné el precio antes de venderlo.",
                 bg=C.peligro, fg=C.blanco, font=("Segoe UI", 11),
                 justify="center").pack(pady=(12, 0))

        v_precio = tk.StringVar()
        f = tk.Frame(d, bg=C.peligro)
        f.pack(pady=(10, 0))
        tk.Label(f, text="Precio:  $", bg=C.peligro, fg=C.blanco,
                 font=("Segoe UI", 12)).pack(side="left")
        e = tk.Entry(f, textvariable=v_precio, font=("Segoe UI", 15, "bold"),
                     width=10, justify="center", relief="flat")
        e.pack(side="left", padx=6, ipady=3)

        def guardar(_ev=None):
            """Se puede resolver acá mismo: el cliente está esperando."""
            try:
                nuevo = float(v_precio.get().replace(",", "."))
            except ValueError:
                return
            if nuevo <= 0:
                return
            try:
                from repositorio import set_precio_base
                set_precio_base(prod["id"], nuevo)
            except Exception:
                return
            d.destroy()
            toast(self, f"Precio cargado: $ {nuevo:,.2f}. Escaneá de nuevo.")
            self.foco_scanner()

        def cerrar(_ev=None):
            d.destroy()
            self.foco_scanner()

        e.bind("<Return>", guardar)
        d.bind("<Escape>", cerrar)
        pie = tk.Frame(d, bg=C.peligro)
        pie.pack(side="bottom", pady=16)
        tk.Button(pie, text="Guardar precio  (Enter)", command=guardar,
                  font=("Segoe UI", 11, "bold"), bg=C.blanco, fg=C.peligro,
                  relief="flat", padx=16, pady=6,
                  cursor="hand2").pack(side="left", padx=6)
        tk.Button(pie, text="Cancelar  (Esc)", command=cerrar,
                  font=("Segoe UI", 11), bg=C.peligro, fg=C.blanco,
                  relief="solid", bd=1, padx=14, pady=6,
                  cursor="hand2").pack(side="left", padx=6)
        e.focus_set()

    def _alertar_no_encontrado(self, codigo):
        """Cartel que frena la venta: el producto no está en el sistema.

        Tres avisos a la vez porque en la caja se mira poco: sonido,
        pantalla roja y un botón que hay que apretar. Si esto pasara
        desapercibido, el cliente se lleva el producto sin pagarlo.
        """
        # Sonido: es lo único que se percibe sin mirar la pantalla
        try:
            if sys.platform == "win32":
                import winsound
                # Dos tonos graves: distintos del beep del lector, que es
                # agudo y corto. Se tiene que oír "mal".
                winsound.Beep(420, 250)
                winsound.Beep(300, 350)
            else:
                self.bell()
        except Exception:
            try:
                self.bell()
            except Exception:
                pass

        d = tk.Toplevel(self)
        d.title("Producto no encontrado")
        d.configure(bg=C.peligro)
        d.grab_set()
        d.transient(self.winfo_toplevel())
        w, h = 520, 300
        sw, sh = d.winfo_screenwidth(), d.winfo_screenheight()
        d.geometry(f"{w}x{h}+{(sw-w)//2}+{max(0,(sh-h)//3)}")

        tk.Label(d, text="⚠", bg=C.peligro, fg=C.blanco,
                 font=("Segoe UI", 44, "bold")).pack(pady=(18, 0))
        tk.Label(d, text="ESTE PRODUCTO NO ESTÁ CARGADO",
                 bg=C.peligro, fg=C.blanco,
                 font=("Segoe UI", 16, "bold")).pack()
        tk.Label(d, text=f"Código: {codigo}", bg=C.peligro, fg=C.blanco,
                 font=("Segoe UI", 13)).pack(pady=(6, 0))
        tk.Label(d, text="NO se agregó a la venta.\n"
                         "Si el cliente lo lleva, cobralo aparte "
                         "o cargalo primero.",
                 bg=C.peligro, fg=C.blanco, font=("Segoe UI", 11),
                 justify="center").pack(pady=(12, 0))

        def cerrar(_ev=None):
            d.destroy()
            self.foco_scanner()

        def anotarlo():
            """Lo deja en la lista de compras para cargarlo después.

            En medio de la caja no se puede parar a dar de alta un
            producto, pero si no queda anotado se olvida y vuelve a pasar
            lo mismo mañana.
            """
            try:
                from repositorio import agregar_a_comprar
                agregar_a_comprar(f"CARGAR AL SISTEMA — código {codigo}",
                                  "", "", "Escaneado en caja, no existía")
                d.destroy()
                toast(self, "Anotado en «Comprar» para cargarlo después")
            except Exception:
                d.destroy()
            self.foco_scanner()

        pie = tk.Frame(d, bg=C.peligro)
        pie.pack(side="bottom", pady=18)
        b1 = tk.Button(pie, text="Entendido  (Enter)", command=cerrar,
                       font=("Segoe UI", 11, "bold"), bg=C.blanco,
                       fg=C.peligro, relief="flat", padx=18, pady=6,
                       cursor="hand2")
        b1.pack(side="left", padx=6)
        tk.Button(pie, text="Anotar para cargarlo", command=anotarlo,
                  font=("Segoe UI", 11), bg=C.peligro, fg=C.blanco,
                  relief="solid", bd=1, padx=14, pady=6,
                  cursor="hand2").pack(side="left", padx=6)

        d.bind("<Return>", cerrar)
        d.bind("<Escape>", cerrar)
        b1.focus_set()

    def _dialogo_otros_metodos(self):
        """Las formas de pago que se usan de vez en cuando."""
        d = tk.Toplevel(self)
        d.title("Otras formas de pago")
        d.configure(bg=C.superficie)
        d.grab_set()
        _centrar_dialogo(d, 380, 300)

        lbl(d, "Otras formas de pago", variante="titulo",
            bg=C.superficie).pack(anchor="w", padx=18, pady=(16, 10))

        def elegir(valor):
            d.destroy()
            self._sel_metodo(valor)

        for label, valor in METODOS_PAGO:
            if valor in METODOS_FRECUENTES:
                continue
            tk.Button(d, text=label, font=F.normal, relief="solid", bd=1,
                      cursor="hand2", pady=9, bg=C.bg, fg=C.texto,
                      command=lambda v=valor: elegir(v)).pack(
                fill="x", padx=18, pady=3)

        btn(d, "Cancelar", variante="neutro",
            comando=d.destroy).pack(pady=(14, 0))
        d.bind("<Escape>", lambda e: d.destroy())

    def _mostrar_sugerencias(self):
        """Ofrece lo que suele acompañar a lo que ya está en el carrito.

        Va en un hilo porque consulta el historial: bloquear la caja
        medio segundo por una sugerencia no vale la pena.
        """
        if not self.carrito:
            self.lbl_sugerencias.grid_forget()
            return
        ids = [i["producto_id"] for i in self.carrito if i.get("producto_id")]
        if not ids:
            return

        resultado = {"sug": None}

        def _trabajo():
            try:
                from repositorio import sugerencias_para
                resultado["sug"] = sugerencias_para(ids)
            except Exception as exc:
                logging.debug(f"No se pudieron calcular sugerencias: {exc}")

        def _esperar():
            # after() desde el hilo secundario rompe Tk; se consulta el
            # resultado desde el hilo principal.
            if hilo.is_alive():
                self.after(60, _esperar)
                return
            if resultado["sug"] is not None:
                _pintar(resultado["sug"])

        def _pintar(sug):
            if not self.winfo_exists() or not self.carrito:
                return
            # Menos del 25% no es un patrón, es ruido: sugerir cualquier
            # cosa hace que el cajero deje de mirar el cartel.
            fuertes = [x for x in sug if x["pct"] >= 25][:2]
            if not fuertes:
                self.lbl_sugerencias.grid_forget()
                return
            partes = [f"{x['descripcion'][:26]} (${x['precio']:,.0f})"
                      for x in fuertes]
            self.lbl_sugerencias.config(
                text="  💡  Suelen llevar también:  " + "   ·   ".join(partes))
            self.lbl_sugerencias.grid(row=5, column=0, sticky="ew",
                                      pady=(0, 4))

        import threading
        hilo = threading.Thread(target=_trabajo, daemon=True)
        hilo.start()
        self.after(60, _esperar)

    def _aplicar_promos_grupo(self):
        """Recalcula las promos combinables sobre todo el carrito."""
        from repositorio import (aplicar_promos_combinables,
                                 promo_grupo_faltante, get_precio_con_promo)
        # Se vuelve al precio base antes de recalcular: si no, al sacar un
        # producto del carrito los demas quedarian con el precio de promo.
        for i in self.carrito:
            if i.pop("_promo_grupo", None) is not None:
                pid = i.get("producto_id")
                if pid:
                    precio, promo = get_precio_con_promo(pid, i["cantidad"])
                    i["precio_unitario"] = precio
                    i["subtotal"] = precio * i["cantidad"]
                    i["promo_aplicada"] = promo
        try:
            avisos = aplicar_promos_combinables(self.carrito)
            faltan = promo_grupo_faltante(self.carrito)
        except Exception:
            return
        # "Con una mas entra la promo" es una venta que se pierde solo
        # porque nadie lo dijo.
        txt = "   ·   ".join(avisos)
        if faltan:
            f = faltan[0]
            extra = (f"Con {f['falta']:g} más entra «{f['nombre']}»")
            txt = f"{txt}   ·   {extra}" if txt else extra

        # Promos del PRODUCTO (no del grupo): "llevando 3 sale $3.200".
        # Es lo que hay que decirle al cliente en el momento, porque el
        # no tiene como enterarse.
        if not txt:
            from repositorio import promo_cercana
            for i in self.carrito:
                pid = i.get("producto_id")
                if not pid:
                    continue
                try:
                    pc = promo_cercana(pid, i["cantidad"])
                except Exception:
                    continue
                if pc:
                    txt = (f"Con {pc['falta']:g} más de "
                           f"«{i['descripcion'][:22]}» → "
                           f"$ {pc['precio_promo']:,.0f} c/u "
                           f"(lleva {pc['cantidad_minima']:g})")
                    break
        if hasattr(self, "lbl_promo_grupo"):
            self.lbl_promo_grupo.config(
                text=f"  🏷  {txt}  " if txt else "",
                # Verde = la promo YA entro. Naranja = falta poco, hay que
                # ofrecerla. Sin el naranja el aviso pasa desapercibido.
                bg=C.exito if avisos else C.advertencia)
            if txt:
                self.lbl_promo_grupo.grid(row=4, column=0, sticky="ew",
                                          pady=(0, 6))
            else:
                self.lbl_promo_grupo.grid_forget()

    def _pedir_peso(self, prod):
        """Pide el peso de un producto que se vende por kilo.

        Devuelve los kg, o None si se cancelo. El campo arranca vacio a
        proposito: un valor precargado se acepta sin mirar, y cobrar
        1 kg cuando el cliente lleva 300 g es plata regalada en cada
        venta.
        """
        d = tk.Toplevel(self)
        d.title("Peso")
        # Al destruirse, el foco vuelve al scanner. Es la red directa:
        # si algo se cierra por un camino que no pasa por wait_window,
        # igual queda la caja lista para el proximo producto.
        d.bind("<Destroy>",
               lambda e: (e.widget is d) and self.after(60,
                                                        self._al_cerrar_dialogo))
        d.configure(bg=C.superficie)
        d.transient(self.winfo_toplevel())
        d.grab_set()
        _centrar_dialogo(d, 430, 300)

        lbl(d, prod["descripcion"][:40], variante="subtitulo",
            bg=C.superficie).pack(anchor="w", padx=18, pady=(14, 0))
        precio_kg = float(prod.get("precio_base") or 0)
        stock_disp = 0.0
        try:
            from repositorio import get_stock_producto
            stock_disp = float(get_stock_producto(prod["id"]) or 0)
        except Exception:
            pass
        lbl(d, f"$ {precio_kg:,.2f} por kg   ·   hay {stock_disp:g} kg",
            variante="suave", bg=C.superficie).pack(anchor="w", padx=18)

        lbl(d, "Peso en kg", variante="suave", bg=C.superficie).pack(
            anchor="w", padx=18, pady=(12, 2))
        v_peso = tk.StringVar()
        f_in = tk.Frame(d, bg=C.superficie)
        f_in.pack(fill="x", padx=18)
        e = tk.Entry(f_in, textvariable=v_peso, font=F.total, justify="center",
                     bg=C.bg, fg=C.texto, relief="solid", bd=1)
        e.pack(side="left", fill="x", expand=True, ipady=8)
        e.focus_set()

        lbl_bal = tk.Label(d, text="", bg=C.superficie, fg=C.texto_suave,
                           font=F.pequeña, anchor="w")
        lbl_bal.pack(fill="x", padx=18, pady=(3, 0))

        # Muchas balanzas de mostrador ya muestran el importe: tipear el
        # peso obliga a rehacer la cuenta al reves. Se puede cargar
        # cualquiera de los dos y el otro se completa solo.
        f_imp = tk.Frame(d, bg=C.superficie)
        f_imp.pack(fill="x", padx=18, pady=(10, 0))
        lbl(f_imp, "…o el importe  $", variante="suave",
            bg=C.superficie).pack(side="left")
        v_importe = tk.StringVar()
        e_imp = tk.Entry(f_imp, textvariable=v_importe, font=F.subtitulo,
                         justify="center", width=12, bg=C.bg, fg=C.texto,
                         relief="solid", bd=1)
        e_imp.pack(side="left", padx=6, ipady=3)

        def _pesar():
            try:
                import balanza
            except ImportError:
                lbl_bal.config(text="No se pudo usar la balanza.")
                return
            peso, msg = balanza.leer_peso()
            if peso is None:
                lbl_bal.config(text=f"Balanza: {msg}")
                return
            v_peso.set(f"{peso:.3f}")
            lbl_bal.config(text="Leído de la balanza")

        btn(f_in, "Pesar", variante="primario", comando=_pesar).pack(
            side="left", padx=(8, 0))

        # El subtotal en vivo: es lo que el cajero le canta al cliente.
        # Va en DOS labels: el importe grande y el mensaje chico. Con
        # todo a 28pt, un texto como "Poné el peso o usá la balanza" se
        # salia de la ventana.
        caja_sub = tk.Frame(d, bg=C.acento)
        caja_sub.pack(fill="x", padx=18, pady=(10, 0))
        lbl_sub = tk.Label(caja_sub, text="", bg=C.acento, fg=C.texto,
                           font=F.total, pady=(6))
        lbl_sub.pack(fill="x")
        lbl_msg = tk.Label(caja_sub, text="", bg=C.acento, fg=C.texto_suave,
                           font=F.normal, wraplength=380, pady=4)
        lbl_msg.pack(fill="x")

        def _pintar(importe="", mensaje="", error=False):
            fondo = C.err_flash if error else C.acento
            caja_sub.config(bg=fondo)
            lbl_sub.config(text=importe, bg=fondo,
                           fg=C.peligro if error else C.texto)
            lbl_msg.config(text=mensaje, bg=fondo,
                           fg=C.peligro if error else C.texto_suave)

        def _calcular(*_a):
            txt = (v_peso.get() or "").strip().replace(",", ".")
            try:
                kg = float(txt)
            except ValueError:
                _pintar("—", "Poné el peso o usá la balanza")
                return
            if kg <= 0:
                _pintar("—", "El peso tiene que ser mayor a cero")
                return
            if stock_disp and kg > stock_disp + 0.001:
                _pintar(f"{kg:.3f} kg", f"Solo hay {stock_disp:g} kg",
                        error=True)
                return
            _pintar(f"$ {kg * precio_kg:,.2f}", f"{kg:.3f} kg")

        # Cada campo completa al otro. El flag evita el rebote infinito
        # de "peso escribe importe, importe escribe peso".
        _recalc = [False]
        # Importe tipeado a mano: cuando esta, el subtotal es EXACTAMENTE
        # ese numero y el precio por kg se ajusta para que cierre.
        _importe_exacto = [None]

        def _desde_peso(*_a):
            if _recalc[0]:
                return
            _calcular()
            try:
                kg = float((v_peso.get() or "").strip().replace(",", "."))
            except ValueError:
                return
            if kg > 0 and precio_kg:
                _recalc[0] = True
                v_importe.set(f"{kg * precio_kg:.2f}")
                _recalc[0] = False

        def _desde_importe(*_a):
            if _recalc[0]:
                return
            txt = (v_importe.get() or "").strip().replace(",", ".")
            if not txt:
                return
            try:
                imp = float(txt)
            except ValueError:
                return
            if imp > 0 and precio_kg:
                _recalc[0] = True
                # 3 decimales: es la precision de una balanza de gramos
                v_peso.set(f"{imp / precio_kg:.3f}")
                _recalc[0] = False
                # El importe escrito MANDA: si se recalcula desde los kg
                # redondeados, $7.300 se convierten en $7.297,50 y esos
                # $2,50 se pierden en cada venta por peso.
                _importe_exacto[0] = imp
                _pintar(f"$ {imp:,.2f}",
                        f"{imp / precio_kg:.3f} kg · importe exacto")
                return

        # Al tocar el peso se vuelve al calculo normal: el importe exacto
        # solo rige mientras no se corrija el peso a mano.
        def _limpiar_exacto(*_a):
            if not _recalc[0]:
                _importe_exacto[0] = None

        v_peso.trace_add("write", _limpiar_exacto)
        v_peso.trace_add("write", _desde_peso)
        v_importe.trace_add("write", _desde_importe)
        _calcular()

        resultado = [None, None]     # [kg, precio_ajustado]

        def aceptar(_ev=None):
            txt = (v_peso.get() or "").strip().replace(",", ".")
            try:
                kg = float(txt)
            except ValueError:
                lbl_bal.config(text="Escribí un peso válido.")
                return
            if kg <= 0:
                lbl_bal.config(text="El peso tiene que ser mayor a cero.")
                return
            if stock_disp and kg > stock_disp + 0.001:
                lbl_bal.config(text=f"No hay tanto: quedan {stock_disp:g} kg.")
                return
            # Si se tipeó el importe, el precio por kg se ajusta para que
            # kg × precio dé EXACTAMENTE ese importe. Es la única forma de
            # que el ticket diga 7.300 y no 7.297,50.
            if _importe_exacto[0] and kg > 0:
                resultado[1] = round(_importe_exacto[0] / kg, 4)
            resultado[0] = kg
            d.destroy()

        e.bind("<Return>", aceptar)
        e_imp.bind("<Return>", aceptar)
        d.bind("<Escape>", lambda ev: d.destroy())

        pie = tk.Frame(d, bg=C.superficie)
        pie.pack(side="bottom", fill="x", pady=14)
        btn(pie, "Agregar  (Enter)", variante="exito",
            comando=aceptar).pack(side="left", padx=(18, 6))
        btn(pie, "Cancelar  (Esc)", variante="neutro",
            comando=d.destroy).pack(side="left")

        self.wait_window(d)
        self._al_cerrar_dialogo()
        return resultado[0], resultado[1]

    def _elegir_producto(self, candidatos, texto_buscado):
        """
        Muestra una lista de productos que matchean la busqueda por nombre
        y deja elegir uno con doble click, Enter, o Escape para cancelar.
        Retorna el dict del producto elegido o None si se cancelo.
        """
        d = tk.Toplevel(self)
        d.title("Elegir producto")
        d.configure(bg=C.bg)
        d.transient(self.winfo_toplevel())
        d.grab_set()
        w, h = 560, 380
        _centrar_dialogo(d, w, h)
        d.columnconfigure(0, weight=1)
        d.rowconfigure(1, weight=1)

        lbl(d, f'Resultados para "{texto_buscado}" — Enter o doble click para elegir',
            variante="suave").grid(row=0, column=0, sticky="w", padx=12, pady=(12, 4))

        cols = [
            ("codigo", "Codigo",     100, "w"),
            ("desc",   "Producto",   260, "w"),
            ("precio", "Precio",      90, "e"),
            ("stock",  "Stock",       60, "e"),
        ]
        frame_t, tree = tabla(d, cols, con_iconos=True)
        frame_t.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 8))

        # Referencias a las miniaturas: si no se guardan en algún lado,
        # Tkinter las recolecta y las imágenes desaparecen de la tabla.
        tree._thumbs = []

        por_codigo = {}
        for p in candidatos:
            por_codigo[p["codigo"]] = p
            foto = imagenes.cargar_thumbnail(p.get("imagen_url"), size=(48, 48))
            if foto:
                tree._thumbs.append(foto)
            tree.insert("", "end", iid=p["codigo"], image=(foto or ""), values=(
                p["codigo"], p["descripcion"],
                f"$ {p['precio_base']:,.2f}", p.get("stock", "")))

        hijos = tree.get_children()
        if hijos:
            tree.selection_set(hijos[0])
            tree.focus(hijos[0])

        resultado = {"prod": None}

        def _confirmar(event=None):
            sel = tree.selection()
            if sel:
                resultado["prod"] = por_codigo.get(sel[0])
            d.destroy()

        def _cancelar(event=None):
            d.destroy()

        tree.bind("<Double-1>", _confirmar)
        tree.bind("<Return>",   _confirmar)
        d.bind("<Escape>",      _cancelar)

        bot = tk.Frame(d, bg=C.bg)
        bot.grid(row=2, column=0, sticky="e", padx=12, pady=(0, 12))
        btn(bot, "Elegir",   variante="primario", comando=_confirmar).pack(side="right")
        btn(bot, "Cancelar", variante="neutro",   comando=_cancelar).pack(side="right", padx=(0, 8))

        tree.focus_set()
        d.wait_window()
        return resultado["prod"]

    # ── Tabla ─────────────────────────────────────────────────────────────────

    def _actualizar_tabla(self):
        for r in self.tree.get_children():
            self.tree.delete(r)
        # Las imagenes se guardan mientras la fila exista: si se las deja
        # ir, Tk las descarta y el renglon queda sin foto.
        self._imgs_carrito = []
        import imagenes
        for i in self.carrito:
            img = None
            try:
                if i.get("producto_id"):
                    from repositorio import get_producto_completo
                    prod = get_producto_completo(i["producto_id"])
                    img = imagenes.cargar_thumbnail(
                        (prod or {}).get("imagen_url"), (50, 50))
            except Exception:
                img = None
            if img is not None:
                self._imgs_carrito.append(img)
            self.tree.insert("", "end", image=img or "", values=(
                i["descripcion"],
                _fmt_cant(i['cantidad']),
                f"$ {i['precio_unitario']:,.2f}",
                f"$ {i['subtotal']:,.2f}",
                "[P]" if i["promo_aplicada"] else "",
            ))
        kids = self.tree.get_children()
        if kids:
            self.tree.see(kids[-1])
        # Acá y no al agregar: así también se recalcula al quitar un
        # item o cambiar una cantidad. Si no, queda sugiriendo algo por
        # un producto que ya no está en el carrito.
        self._mostrar_sugerencias()

    def _texto_descuento(self, desc_pct):
        """El descuento tal como se cargó: en $ o en %."""
        bruto = sum(i["subtotal"] for i in self.carrito)
        monto = self._descuento_monto(bruto)
        if getattr(self, "desc_modo", None) and self.desc_modo.get() == "$":
            return f"  —  Descuento $ {monto:,.2f}"
        return f"  —  Descuento {desc_pct:.1f}%  ($ {monto:,.2f})"

    def _descuento_monto(self, bruto):
        """Cuántos pesos de descuento, sea que se cargó en % o en $."""
        try:
            valor = float((self.entry_desc.get() or "0").replace(",", "."))
        except ValueError:
            return 0.0
        if valor <= 0:
            return 0.0
        if getattr(self, "desc_modo", None) and self.desc_modo.get() == "$":
            # Nunca mas que el total: un descuento mayor daria total
            # negativo y la caja quedaria pidiendo plata.
            return min(valor, bruto)
        return bruto * min(valor, 100.0) / 100

    def _actualizar_totales(self):
        bruto      = sum(i["subtotal"] for i in self.carrito)
        desc_monto = self._descuento_monto(bruto)
        total      = max(0.0, bruto - desc_monto)
        n_items    = sum(i["cantidad"] for i in self.carrito)

        self.lbl_total.config(text=f"$ {total:,.2f}")
        self.lbl_items.config(
            text=f"{_fmt_cant(n_items)} item{'s' if n_items != 1 else ''}")

        for w in self.frame_promos.winfo_children():
            w.destroy()
        promos = [i for i in self.carrito if i["promo_aplicada"]]
        if promos:
            lbl(self.frame_promos, "Promociones:", variante="suave",
                bg=C.superficie, fg=C.advertencia).pack(anchor="w")
            for p in promos:
                lbl(self.frame_promos,
                    f"  {p['descripcion']} x{_fmt_cant(p['cantidad'])}",
                    variante="suave", bg=C.superficie).pack(anchor="w")

        if self.metodo.get() == "mixto":
            self._on_mixto_key(None)

    # ── Métodos de pago ───────────────────────────────────────────────────────

    def _sel_metodo(self, metodo):
        self.metodo.set(metodo)
        for v, b in self.btns_pago.items():
            if v == metodo:
                b.config(bg=C.acento, fg=C.primario, font=F.boton)
            else:
                b.config(bg=C.superficie, fg=C.texto,
                         font=F.pequeña if self._modo_chico else F.normal)

        # Si se eligio uno de los poco frecuentes no hay boton que se
        # marque: el nombre va en "Otras formas" para que se vea que
        # metodo esta activo.
        if hasattr(self, "btn_otros"):
            if metodo in METODOS_FRECUENTES:
                self.btn_otros.config(text="Otras formas de pago…",
                                      bg=C.superficie, fg=C.texto_suave)
            else:
                etq = next((l for l, v in METODOS_PAGO if v == metodo),
                           metodo)
                self.btn_otros.config(text=f"▸ {etq}", bg=C.acento,
                                      fg=C.primario)

        # Mostrar/ocultar panel efectivo (recibido/vuelto)
        if metodo == "efectivo":
            self.frame_efectivo.pack(fill="x", pady=(4, 0))
            self.entry_recibido.delete(0, "end")
            self.lbl_vuelto.config(text="")
            self.entry_recibido.focus_set()
        else:
            self.frame_efectivo.pack_forget()

        # Mostrar/ocultar panel mixto
        if metodo == "mixto":
            self.frame_mixto.pack(fill="x", pady=(4, 0))
            self.entry_efectivo_mixto.delete(0, "end")
            self.lbl_resto.config(text="")
            self.entry_efectivo_mixto.focus_set()
        else:
            self.frame_mixto.pack_forget()

        # Mostrar/ocultar panel fiado
        if metodo == "cuenta_corriente":
            self._iniciar_cta_cte()
        else:
            self._cliente_cta = None
            self.frame_cliente.pack_forget()

    def _on_recibido_key(self, event):
        bruto = sum(i["subtotal"] for i in self.carrito)
        desc_monto = self._descuento_monto(bruto)
        total = max(0.0, bruto - desc_monto)
        try:
            recibido = float(self.entry_recibido.get().replace(",", "."))
            vuelto = recibido - total
            if vuelto < 0:
                self.lbl_vuelto.config(
                    text=f"Falta: $ {abs(vuelto):,.2f}", fg=C.peligro)
            else:
                self.lbl_vuelto.config(
                    text=f"Vuelto: $ {vuelto:,.2f}", fg=C.exito)
        except ValueError:
            self.lbl_vuelto.config(text="")

    def _on_mixto_key(self, event):
        bruto = sum(i["subtotal"] for i in self.carrito)
        desc_monto = self._descuento_monto(bruto)
        total = max(0.0, bruto - desc_monto)
        try:
            efectivo = float(self.entry_efectivo_mixto.get().replace(",", "."))
            resto = total - efectivo
            if resto < 0:
                self.lbl_resto.config(
                    text=f"Vuelto: $ {abs(resto):,.2f}", fg=C.exito)
            else:
                self.lbl_resto.config(
                    text=f"Tarjeta: $ {resto:,.2f}", fg=C.texto)
        except ValueError:
            self.lbl_resto.config(text="")

    # ── Fiado ─────────────────────────────────────────────────────────────────

    def _iniciar_cta_cte(self):
        """Pide DNI, busca o crea cliente, valida tope."""
        from fiado_ui import dialogo_cta_cte as dialogo_cta_cte
        cliente = dialogo_cta_cte(self)
        if not cliente:
            # Canceló — volver a efectivo
            self._sel_metodo("efectivo")
            return
        self._cliente_cta = cliente
        saldo    = cliente.get("saldo_actual", 0)
        tope     = cliente.get("tope_credito", 0)
        self.lbl_cliente.config(
            text=f"Cta. Cte.: {cliente['nombre']}  |  "
                 f"Saldo: $ {saldo:,.2f}  |  "
                 f"Disponible: $ {tope - saldo:,.2f}")
        self.frame_cliente.pack(fill="x", padx=16, pady=(4, 0))

    # ── Acciones ──────────────────────────────────────────────────────────────

    def _quitar(self, event=None):
        sel = self.tree.selection()
        if not sel: return
        del self.carrito[self.tree.index(sel[0])]
        # Al sacar un producto la promo puede dejar de aplicar: hay que
        # recalcular o los que quedan siguen con el precio promocional.
        self._aplicar_promos_grupo()
        self._actualizar_tabla()
        self._actualizar_totales()
        self.foco_scanner()

    def _editar_cant(self, event=None):
        sel = self.tree.selection()
        if not sel: return
        item = self.carrito[self.tree.index(sel[0])]

        d = tk.Toplevel(self)
        d.title("Editar cantidad")
        d.resizable(True, False)
        d.configure(bg=C.superficie)
        d.grab_set()
        _centrar_dialogo(d, 300, 155)

        lbl(d, item["descripcion"], variante="subtitulo",
            bg=C.superficie, wraplength=260).pack(pady=(16, 4), padx=16)
        f = tk.Frame(d, bg=C.superficie)
        f.pack(pady=8)
        lbl(f, "Cantidad:", bg=C.superficie).pack(side="left")
        e = tk.Entry(f, width=8, justify="center", font=("Segoe UI", 12),
                     bg=C.superficie, fg=C.texto, relief="solid", bd=1)
        e.insert(0, _fmt_cant(item["cantidad"]))
        e.pack(side="left", padx=8)
        e.focus_set()
        e.select_range(0, "end")

        def ok(event=None):
            try:
                nueva = float(e.get().replace(",", "."))
                if nueva <= 0: raise ValueError
            except (ValueError, TypeError): return
            if not item.get("vendido_por_peso") and nueva != int(nueva):
                messagebox.showwarning(
                    "Atención",
                    f"{item['descripcion']} se vende por unidad — "
                    "la cantidad debe ser entera.", parent=d)
                return
            precio, promo = get_precio_con_promo(item["producto_id"], nueva)
            item.update(cantidad=nueva, precio_unitario=precio,
                        promo_aplicada=promo, subtotal=nueva * precio)
            d.destroy()
            self._actualizar_tabla()
            self._actualizar_totales()
            self.foco_scanner()

        e.bind("<Return>", ok)
        btn(d, "Confirmar", variante="primario", comando=ok).pack(pady=(0, 16))

    def _sincronizar_stock_en_segundo_plano(self):
        """
        Actualiza stock/precio/promos en la página de pedidos después
        de cada venta, sin bloquear la caja. No procesa fotos (eso lo
        sigue haciendo la sincronización completa manual desde
        Config) — así nunca se ofrece algo que ya no hay.
        """
        import catalogo_web
        catalogo_web.sincronizar_stock_en_segundo_plano()

    def _cobrar(self):
        if not self.carrito:
            toast(self, "El carrito esta vacio", error=True)
            return self.foco_scanner()

        bruto      = sum(i["subtotal"] for i in self.carrito)
        desc_monto = self._descuento_monto(bruto)
        total      = max(0.0, bruto - desc_monto)
        # La venta guarda el descuento como PORCENTAJE: se convierte el
        # importe a su equivalente para no cambiar el historico ni los
        # informes que ya lo leen asi.
        desc_pct   = (desc_monto / bruto * 100) if bruto else 0.0
        metodo = self.metodo.get()
        # Reparto del pago entre medios. None = todo al metodo elegido.
        desglose = None

        # Efectivo / Tarjeta / QR → confirmar directo
        if metodo in ("efectivo", "tarjeta", "qr"):
            label = next((l for l, v in METODOS_PAGO if v == metodo), metodo)
            texto_confirmar = f"Total: $ {total:,.2f}\nMetodo: {label}"
            if desc_monto:
                if self.desc_modo.get() == "$":
                    texto_confirmar += f"\nDescuento: $ {desc_monto:,.2f}"
                else:
                    texto_confirmar += (f"\nDescuento: {desc_pct:.1f}%  "
                                        f"($ {desc_monto:,.2f})")
            if metodo == "efectivo":
                try:
                    recibido = float(self.entry_recibido.get().replace(",", "."))
                    if recibido >= total:
                        texto_confirmar += (f"\nRecibe: $ {recibido:,.2f}"
                                           f"\nVuelto: $ {recibido - total:,.2f}")
                except ValueError:
                    pass
            # default="yes": Enter confirma. Es lo que se hace en el 99%
            # de las ventas y ahorra mover la mano al mouse.
            if not messagebox.askyesno(
                    "Confirmar cobro",
                    f"{texto_confirmar}\n\nConfirmar?",
                    parent=self, default="yes"):
                return self.foco_scanner()
            metodo_db  = metodo
            cliente_id = None

        # Mixto → popup solo con campo de monto efectivo
        elif metodo == "mixto":
            resultado = self._dialogo_mixto(total)
            if not resultado:
                return self.foco_scanner()
            metodo_db  = "mixto"
            cliente_id = None
            desglose = {"efectivo": resultado.get("efectivo", 0),
                        "tarjeta": resultado.get("tarjeta", 0)}

        # Paga una parte ahora y el resto queda fiado
        elif metodo == "mixto_cta":
            r = self._dialogo_parte_y_fia(total)
            if not r:
                return self.foco_scanner()
            metodo_db  = "cuenta_corriente"
            cliente_id = r["cliente"]["id"]
            desglose = {r["medio"]: r["paga"], "cta_cte": r["fia"]}

        # Cuenta Corriente → popup solo con DNI
        elif metodo == "cuenta_corriente":
            cliente = self._dialogo_cuenta_corriente(total)
            if not cliente:
                return self.foco_scanner()
            metodo_db  = "cuenta_corriente"
            cliente_id = cliente["id"]

        else:
            metodo_db  = metodo
            cliente_id = None

        # ── Registrar ─────────────────────────────────────────────────────────
        try:
            vid = registrar_venta(
                self.app.sesion_id, self.carrito,
                metodo_db, desc_pct, cliente_id=cliente_id,
                desglose=desglose)
        except Exception as exc:
            messagebox.showerror("No se pudo cobrar",
                                 self._detalle_error_venta(exc), parent=self)
            self.foco_scanner()
            return

        if vid:
            # Lo que queda fiado va a la cuenta del cliente. En un pago
            # repartido eso NO es el total: es solo la parte no cubierta.
            deuda = (desglose or {}).get("cta_cte") if desglose else None
            if deuda is None and metodo_db == "cuenta_corriente":
                deuda = total
            if deuda and cliente_id:
                from repositorio import actualizar_saldo_cliente
                actualizar_saldo_cliente(
                    cliente_id, deuda, venta_id=vid,
                    concepto=f"Venta #{vid}"
                            + (f" (pagó $ {total - deuda:,.2f})"
                               if deuda < total else ""))
            # Sincro liviana de stock hacia la página de pedidos, en
            # segundo plano — no toca fotos, y si falla (sin internet,
            # sin URL configurada, etc.) no debe afectar la venta que
            # ya se registró en la base local.
            self._sincronizar_stock_en_segundo_plano()
            toast(self, f"Venta #{vid} — $ {total:,.2f}")
            # Preguntar si imprimir ticket
            self._ofrecer_ticket(vid)
            self._nueva_venta()
        else:
            messagebox.showerror("Error",
                "No se pudo registrar la venta.", parent=self)
            self.foco_scanner()

    def _detalle_error_venta(self, exc):
        """Traduce el error de registrar_venta a algo accionable."""
        texto = str(exc)
        if "Stock insuficiente" in texto:
            prod = texto.split(":", 1)[-1].strip()
            return (f"No alcanza el stock de «{prod}».\n\n"
                    "Puede que se haya vendido desde otra caja mientras "
                    "armabas esta venta.\n\n"
                    "Sacalo del carrito o ajustá la cantidad.")
        return f"No se pudo registrar la venta.\n\nDetalle: {texto}"

    def _dialogo_cobro(self, total: float, desc_pct: float) -> dict | None:
        """
        Diálogo de cobro completo. Siempre visible, independiente del layout.
        Retorna dict con metodo, cliente_id, etc. o None si cancela.
        """
        d = tk.Toplevel(self)
        d.title("Confirmar cobro")
        d.resizable(True, True)
        d.configure(bg=C.superficie)
        d.grab_set()
        sw, sh = d.winfo_screenwidth(), d.winfo_screenheight()
        w = min(420, sw - 40)
        h = min(520, sh - 80)
        d.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

        result = [None]
        metodo_var = tk.StringVar(value="efectivo")
        cliente_cta = [self._cliente_cta]  # usar el que ya estaba si hay

        # ── Scroll contenedor ────────────────────────────────────────────────
        from styles import scrollable
        outer, s = scrollable(d, bg=C.superficie)
        outer.pack(fill="both", expand=True)

        # Total
        tk.Label(s, text=f"$ {total:,.2f}",
                 font=("Segoe UI", 26, "bold"),
                 bg=C.superficie, fg=C.primario).pack(pady=(20, 0))
        lbl(s, f"{_fmt_cant(sum(i['cantidad'] for i in self.carrito))} items"
            # Se muestra como se cargo: si se puso "$500", ver "3,7%" en
            # el cartel confunde al cajero y al cliente.
            + (self._texto_descuento(desc_pct) if desc_pct else ""),
            variante="suave", bg=C.superficie).pack()

        ttk.Separator(s, orient="horizontal").pack(fill="x", padx=20, pady=12)

        # Métodos de pago
        lbl(s, "Metodo de pago", variante="subtitulo",
            bg=C.superficie).pack(padx=20, anchor="w", pady=(0, 6))

        frame_met = tk.Frame(s, bg=C.superficie)
        frame_met.pack(fill="x", padx=20)
        frame_met.columnconfigure(0, weight=1)
        frame_met.columnconfigure(1, weight=1)

        btns_met = {}
        for i, (label, valor) in enumerate(METODOS_PAGO):
            b = tk.Button(frame_met, text=label, font=F.normal,
                          relief="flat", cursor="hand2", pady=8,
                          command=lambda v=valor: _sel(v))
            b.grid(row=i//2, column=i%2, sticky="ew", padx=3, pady=3)
            btns_met[valor] = b

        def _sel(v):
            metodo_var.set(v)
            for val, bb in btns_met.items():
                if val == v:
                    bb.config(bg=C.acento, fg=C.primario, font=F.boton)
                else:
                    bb.config(bg=C.borde, fg=C.texto, font=F.normal)
            frame_mixto.pack_forget()
            frame_cta.pack_forget()
            if v == "mixto":
                frame_mixto.pack(fill="x", padx=20, pady=(4, 0))
                entry_ef.focus_set()
            elif v == "cuenta_corriente":
                frame_cta.pack(fill="x", padx=20, pady=(4, 0))
                _actualizar_cta()

        # Panel mixto
        frame_mixto = tk.Frame(s, bg=C.acento)
        lbl(frame_mixto, "Efectivo $", variante="suave",
            bg=C.acento).pack(side="left", padx=(8, 4))
        entry_ef = tk.Entry(frame_mixto, width=10, justify="right",
                             font=F.normal, bg=C.superficie, fg=C.texto,
                             relief="solid", bd=1)
        entry_ef.pack(side="left", ipady=4, pady=6)
        lbl_resto_d = lbl(frame_mixto, "", variante="suave",
                           bg=C.acento, padx=8)
        lbl_resto_d.pack(side="left")

        def _on_ef_key(event=None):
            try:
                ef = float(entry_ef.get().replace(",", "."))
                resto = total - ef
                if resto < 0:
                    lbl_resto_d.config(text=f"Vuelto: $ {abs(resto):,.2f}", fg=C.exito)
                else:
                    lbl_resto_d.config(text=f"Tarjeta: $ {resto:,.2f}", fg=C.texto)
            except ValueError:
                lbl_resto_d.config(text="")
        entry_ef.bind("<KeyRelease>", _on_ef_key)

        # Panel fiado
        # Panel cuenta corriente — campo DNI inline
        frame_cta = tk.Frame(s, bg=C.acento)

        f_dni = tk.Frame(frame_cta, bg=C.acento)
        f_dni.pack(fill="x", padx=8, pady=(8,4))
        lbl(f_dni, "DNI o nombre:", variante="suave", bg=C.acento).pack(side="left")
        entry_dni_cta = tk.Entry(f_dni, width=22, font=("Segoe UI", 12),
                                  bg=C.superficie,
                                  fg=C.texto, relief="solid", bd=1)
        entry_dni_cta.pack(side="left", padx=(6,4), ipady=5)
        tk.Button(f_dni, text="Buscar", font=F.boton,
                  bg=C.primario, fg=C.blanco, relief="flat",
                  cursor="hand2", padx=10,
                  command=lambda: _buscar_cta()).pack(side="left")
        entry_dni_cta.bind("<Return>", lambda e: _buscar_cta())

        lbl_cta = lbl(frame_cta, "Escribi el DNI o el nombre y presiona Buscar o Enter",
                       variante="suave", bg=C.acento, fg=C.advertencia,
                       padx=12, pady=4, wraplength=340)
        lbl_cta.pack(anchor="w", pady=(0,8))

        def _actualizar_cta():
            c = cliente_cta[0]
            if c:
                disp = c["tope_credito"] - c["saldo_actual"]
                lbl_cta.config(
                    text=f"{c['nombre']}  |  "
                         f"Saldo: $ {c['saldo_actual']:,.2f}  |  "
                         f"Disponible: $ {disp:,.2f}",
                    fg=C.primario if disp > 0 else C.peligro)
            else:
                lbl_cta.config(
                    text="Cliente no encontrado — probá con el nombre",
                    fg=C.peligro)

        def _buscar_cta():
            texto = entry_dni_cta.get().strip()
            if not texto:
                return
            from fiado_ui import resolver_cliente
            c, motivo = resolver_cliente(d, texto)
            if c:
                cliente_cta[0] = c
                entry_dni_cta.delete(0, "end")
                entry_dni_cta.insert(0, c.get("nombre", ""))
                _actualizar_cta()
                return
            if motivo == "cancelo":
                return
            # Sin coincidencias: solo ofrecer alta si lo escrito parece un DNI
            if texto.replace(".", "").replace("-", "").replace(" ", "").isdigit():
                from fiado_ui import dialogo_cta_cte
                c = dialogo_cta_cte(d)
                if c:
                    cliente_cta[0] = c
                    entry_dni_cta.delete(0, "end")
                    entry_dni_cta.insert(0, c.get("nombre", ""))
                    _actualizar_cta()
            else:
                lbl_cta.config(text=f"Ningun cliente coincide con \u201c{texto}\u201d",
                               fg=C.peligro)

        _sel("efectivo")

        ttk.Separator(s, orient="horizontal").pack(fill="x", padx=20, pady=12)

        # ── Botones ──────────────────────────────────────────────────────────
        fb = tk.Frame(d, bg=C.superficie,
                      highlightbackground=C.borde, highlightthickness=1)
        fb.pack(fill="x", side="bottom")
        fb.columnconfigure(0, weight=1)
        fb.columnconfigure(1, weight=1)

        def confirmar():
            metodo = metodo_var.get()

            if metodo == "mixto":
                try:
                    ef = float(entry_ef.get().replace(",", "."))
                    if ef <= 0: raise ValueError
                except ValueError:
                    messagebox.showwarning("Error",
                        "Ingresa el monto en efectivo.", parent=d)
                    return

            elif metodo == "cuenta_corriente":
                if not cliente_cta[0]:
                    messagebox.showwarning("Error",
                        "Busca un cliente antes de confirmar.", parent=d)
                    return
                c     = cliente_cta[0]
                saldo = c.get("saldo_actual", 0)
                tope  = c.get("tope_credito", 0)
                if saldo + total > tope:
                    msg = (f"{c['nombre']}\n"
                           f"Saldo: $ {saldo:,.2f}\n"
                           f"Compra: $ {total:,.2f}\n"
                           f"Tope: $ {tope:,.2f}\n\n"
                           f"Supera por $ {saldo+total-tope:,.2f}")
                    messagebox.showerror("Tope superado", msg, parent=d)
                    return

            result[0] = {
                "metodo":     metodo,
                "cliente_id": cliente_cta[0]["id"] if metodo == "cuenta_corriente" and cliente_cta[0] else None,
            }
            d.destroy()

        tk.Button(fb, text="COBRAR", font=("Segoe UI", 13, "bold"),
                  bg=C.exito, fg=C.blanco, relief="flat",
                  cursor="hand2", pady=14,
                  command=confirmar).grid(row=0, column=0, sticky="ew",
                                          padx=(12,4), pady=10)
        tk.Button(fb, text="Cancelar", font=F.boton,
                  bg=C.borde, fg=C.texto, relief="flat",
                  cursor="hand2", pady=14,
                  command=d.destroy).grid(row=0, column=1, sticky="ew",
                                           padx=(4,12), pady=10)

        d.bind("<Return>", lambda e: confirmar())
        self.wait_window(d)
        self._al_cerrar_dialogo()
        return result[0]


    def _dialogo_mixto(self, total: float) -> dict | None:
        """Popup simple: solo pide el monto en efectivo, calcula el resto en tarjeta."""
        d = tk.Toplevel(self)
        d.title("Pago Mixto")
        d.resizable(False, False)
        d.configure(bg=C.superficie)
        d.grab_set()
        sw, sh = d.winfo_screenwidth(), d.winfo_screenheight()
        w, h = 340, 220
        d.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

        tk.Label(d, text=f"$ {total:,.2f}", font=("Segoe UI", 22, "bold"),
                 bg=C.superficie, fg=C.primario).pack(pady=(20, 4))
        lbl(d, "Pago mixto — Efectivo + Tarjeta",
            variante="suave", bg=C.superficie).pack()

        f = tk.Frame(d, bg=C.superficie)
        f.pack(pady=12, padx=20, fill="x")
        lbl(f, "Efectivo $", bg=C.superficie).pack(side="left")
        e = tk.Entry(f, width=10, justify="right", font=("Segoe UI", 13),
                     bg=C.superficie, fg=C.texto, relief="solid", bd=1)
        e.pack(side="left", padx=8, ipady=5)
        lbl_r = lbl(f, "", variante="suave", bg=C.superficie)
        lbl_r.pack(side="left")

        def _calc(event=None):
            try:
                ef = float(e.get().replace(",", "."))
                resto = total - ef
                if resto < 0:
                    lbl_r.config(text=f"Vuelto: $ {abs(resto):,.2f}", fg=C.exito)
                else:
                    lbl_r.config(text=f"Tarjeta: $ {resto:,.2f}", fg=C.texto)
            except ValueError:
                lbl_r.config(text="")
        e.bind("<KeyRelease>", _calc)
        e.focus_set()

        result = [None]
        def confirmar(event=None):
            try:
                ef = float(e.get().replace(",", "."))
                if ef <= 0: raise ValueError
            except ValueError:
                messagebox.showwarning("Error", "Ingresa un monto valido.", parent=d)
                return
            result[0] = {"efectivo": ef, "tarjeta": max(0, total - ef)}
            d.destroy()

        e.bind("<Return>", confirmar)
        fb = tk.Frame(d, bg=C.superficie)
        fb.pack(fill="x", padx=20)
        btn(fb, "Confirmar", variante="exito", comando=confirmar).pack(side="left")
        btn(fb, "Cancelar",  variante="neutro", comando=d.destroy).pack(side="left", padx=8)

        self.wait_window(d)
        self._al_cerrar_dialogo()
        return result[0]

    def _dialogo_parte_y_fia(self, total: float) -> dict | None:
        """Paga una parte ahora y el resto queda en su cuenta.

        Es lo que pasa cuando el cliente no le alcanza: deja lo que tiene
        y se lleva la mercaderia. Antes habia que elegir entre cobrarle
        todo o fiarle todo, y la diferencia se anotaba en un papel.

        Devuelve {"cliente", "medio", "paga", "fia"} o None.
        """
        cliente = self._dialogo_cuenta_corriente(total)
        if not cliente:
            return None

        d = tk.Toplevel(self)
        d.title("Paga una parte")
        d.configure(bg=C.superficie)
        d.transient(self.winfo_toplevel())
        d.grab_set()
        _centrar_dialogo(d, 460, 380)

        lbl(d, cliente.get("nombre", "")[:36], variante="titulo",
            bg=C.superficie).pack(anchor="w", padx=20, pady=(16, 2))
        saldo = float(cliente.get("saldo_actual") or 0)
        lbl(d, f"Total de la compra: $ {total:,.2f}"
               + (f"   ·   ya debe $ {saldo:,.2f}" if saldo else ""),
            variante="suave", bg=C.superficie).pack(anchor="w", padx=20)

        lbl(d, "¿Con qué paga la parte de ahora?", variante="suave",
            bg=C.superficie).pack(anchor="w", padx=20, pady=(14, 2))
        v_medio = tk.StringVar(value="efectivo")
        f_m = tk.Frame(d, bg=C.superficie)
        f_m.pack(fill="x", padx=20)
        for val, txt in (("efectivo", "Efectivo"), ("tarjeta", "Tarjeta"),
                         ("qr", "QR")):
            tk.Radiobutton(f_m, text=txt, variable=v_medio, value=val,
                           bg=C.superficie, fg=C.texto, font=F.normal,
                           selectcolor=C.superficie,
                           activebackground=C.superficie).pack(side="left",
                                                                padx=(0, 12))

        lbl(d, "¿Cuánto paga ahora?", variante="suave",
            bg=C.superficie).pack(anchor="w", padx=20, pady=(14, 2))
        v_paga = tk.StringVar()
        e = tk.Entry(d, textvariable=v_paga, font=F.total, justify="center",
                     bg=C.bg, fg=C.texto, relief="solid", bd=1)
        e.pack(fill="x", padx=20, ipady=6)
        e.focus_set()

        caja = tk.Label(d, text="", bg=C.acento, fg=C.texto, font=F.subtitulo,
                        pady=10)
        caja.pack(fill="x", padx=20, pady=(12, 0))

        def _calc(*_a):
            try:
                paga = float((v_paga.get() or "0").replace(",", "."))
            except ValueError:
                caja.config(text="Poné cuánto entrega", bg=C.acento,
                            fg=C.texto)
                return
            if paga < 0:
                caja.config(text="No puede ser negativo", bg=C.err_flash,
                            fg=C.peligro)
                return
            if paga > total + 0.01:
                caja.config(text=f"Es más que el total ($ {total:,.2f})",
                            bg=C.err_flash, fg=C.peligro)
                return
            fia = total - paga
            caja.config(text=f"Paga $ {paga:,.2f}   ·   queda debiendo "
                             f"$ {fia:,.2f}", bg=C.acento, fg=C.texto)

        v_paga.trace_add("write", _calc)
        _calc()

        res = [None]

        def aceptar(_ev=None):
            try:
                paga = float((v_paga.get() or "").replace(",", "."))
            except ValueError:
                messagebox.showwarning("Pago", "Escribí cuánto paga.",
                                       parent=d)
                return
            if paga < 0 or paga > total + 0.01:
                messagebox.showwarning(
                    "Pago", f"El monto tiene que estar entre $ 0 y "
                            f"$ {total:,.2f}.", parent=d)
                return
            fia = round(total - paga, 2)
            tope = float(cliente.get("tope_credito") or 0)
            if tope and saldo + fia > tope:
                if not messagebox.askyesno(
                        "Supera el tope",
                        f"Con esta compra queda debiendo "
                        f"$ {saldo + fia:,.2f} y su tope es $ {tope:,.2f}."
                        f"\n\n¿Autorizás igual?", parent=d):
                    return
            res[0] = {"cliente": cliente, "medio": v_medio.get(),
                      "paga": round(paga, 2), "fia": fia}
            d.destroy()

        e.bind("<Return>", aceptar)
        d.bind("<Escape>", lambda ev: d.destroy())
        pie = tk.Frame(d, bg=C.superficie)
        pie.pack(side="bottom", pady=16)
        btn(pie, "Confirmar  (Enter)", variante="exito",
            comando=aceptar).pack(side="left", padx=4)
        btn(pie, "Cancelar", variante="neutro",
            comando=d.destroy).pack(side="left", padx=4)

        self.wait_window(d)
        self._al_cerrar_dialogo()
        return res[0]

    def _dialogo_cuenta_corriente(self, total: float) -> dict | None:
        """
        Popup solo para Cuenta Corriente.
        Pide DNI, busca el cliente, valida tope.
        Si no existe ofrece dar de alta con autorización.
        """
        d = tk.Toplevel(self)
        d.title("Cuenta Corriente")
        d.resizable(True, False)
        d.configure(bg=C.superficie)
        d.grab_set()
        sw, sh = d.winfo_screenwidth(), d.winfo_screenheight()
        w, h = 400, 260
        d.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

        tk.Label(d, text=f"$ {total:,.2f}", font=("Segoe UI", 22, "bold"),
                 bg=C.superficie, fg=C.primario).pack(pady=(20, 2))
        lbl(d, "Cuenta Corriente — DNI o nombre del cliente",
            variante="suave", bg=C.superficie).pack()

        # Campo DNI
        f_dni = tk.Frame(d, bg=C.superficie)
        f_dni.pack(fill="x", padx=20, pady=12)
        lbl(f_dni, "Buscar:", bg=C.superficie).pack(side="left")
        e_dni = tk.Entry(f_dni, width=22, font=("Segoe UI", 13),
                          bg=C.superficie, fg=C.texto,
                          relief="solid", bd=1)
        e_dni.pack(side="left", padx=8, ipady=5)
        btn_bus = btn(f_dni, "Buscar", variante="primario",
                      comando=lambda: _buscar())
        btn_bus.pack(side="left")
        e_dni.bind("<Return>", lambda e: _buscar())
        e_dni.focus_set()

        # Info cliente
        lbl_info = lbl(d, "", variante="suave", bg=C.superficie,
                        fg=C.texto_suave, wraplength=360)
        lbl_info.pack(padx=20, anchor="w")

        cliente_ref = [None]

        def _buscar():
            texto = e_dni.get().strip()
            if not texto:
                return
            from fiado_ui import resolver_cliente
            c, motivo = resolver_cliente(d, texto)
            if c:
                cliente_ref[0] = c
                disp  = c["tope_credito"] - c["saldo_actual"]
                color = C.primario if disp >= total else C.peligro
                e_dni.delete(0, "end")
                e_dni.insert(0, c.get("nombre", ""))
                lbl_info.config(
                    text=f"{c['nombre']}  (DNI {c.get('dni','')})  |  "
                         f"Saldo: $ {c['saldo_actual']:,.2f}  |  "
                         f"Disponible: $ {disp:,.2f}",
                    fg=color)
                return
            if motivo == "cancelo":
                return
            cliente_ref[0] = None
            if texto.replace(".", "").replace("-", "").replace(" ", "").isdigit():
                lbl_info.config(
                    text=f"DNI {texto} no registrado. "
                         f"Presiona 'Dar de alta' para registrarlo.",
                    fg=C.advertencia)
                btn_alta.pack(side="left", padx=8)
            else:
                # Tambien se ofrece el alta buscando por NOMBRE: antes solo
                # aparecia con un DNI, y para un cliente nuevo habia que
                # cancelar el cobro e ir a Fiado.
                lbl_info.config(
                    text=f"Ningun cliente coincide con \u201c{texto}\u201d. "
                         f"Presiona 'Dar de alta' para registrarlo.",
                    fg=C.advertencia)
                btn_alta.pack(side="left", padx=8)

        result = [None]

        def confirmar():
            c = cliente_ref[0]
            if not c:
                messagebox.showwarning("Sin cliente",
                    "Busca o registra un cliente primero.", parent=d)
                return
            saldo = c["saldo_actual"]
            tope  = c["tope_credito"]
            if saldo + total > tope:
                messagebox.showerror("Tope superado",
                    f"{c['nombre']}\n"
                    f"Saldo actual: $ {saldo:,.2f}\n"
                    f"Esta compra:  $ {total:,.2f}\n"
                    f"Tope:         $ {tope:,.2f}\n\n"
                    f"Supera el tope por $ {saldo + total - tope:,.2f}",
                    parent=d)
                return
            result[0] = c
            d.destroy()

        def _dar_alta():
            from fiado_ui import pedir_autorizacion, _dialogo_alta
            txt = e_dni.get().strip()
            # Lo escrito puede ser un DNI o un nombre: se manda al campo
            # que corresponde en vez de meter "Juan Perez" en el DNI.
            limpio = txt.replace(".", "").replace("-", "").replace(" ", "")
            if limpio.isdigit():
                dni, nombre = limpio, ""
            else:
                dni, nombre = "", txt

            resp = pedir_autorizacion(d,
                "Registrar un cliente nuevo requiere autorizacion.")
            if not resp:
                return
            alta_result = [None]
            _dialogo_alta(d, dni, resp, alta_result, nombre_inicial=nombre)
            if alta_result[0]:
                c = alta_result[0]
                cliente_ref[0] = c
                e_dni.delete(0, "end")
                e_dni.insert(0, c.get("nombre", ""))
                disp = c.get("tope_credito", 0) - c.get("saldo_actual", 0)
                lbl_info.config(
                    text=f"{c['nombre']} registrado.  |  "
                         f"Disponible: $ {disp:,.2f}",
                    fg=C.exito if disp >= total else C.advertencia)
                btn_alta.pack_forget()

        # Botones
        fb = tk.Frame(d, bg=C.superficie)
        fb.pack(fill="x", padx=20, pady=16)
        btn(fb, "Confirmar", variante="exito",  comando=confirmar).pack(side="left")
        btn(fb, "Cancelar",  variante="neutro",  comando=d.destroy).pack(side="left", padx=8)
        btn_alta = btn(fb, "Dar de alta", variante="advertencia" if hasattr(C, "advertencia") else "neutro",
                       comando=_dar_alta)
        # btn_alta se muestra solo cuando el cliente no existe

        self.wait_window(d)
        self._al_cerrar_dialogo()
        return result[0]

    def _imprimir_post_venta(self, venta_id: int):
        """Imprime y/o ofrece enviar el ticket después de cobrar."""
        from config import cfg
        from impresion import imprimir_ticket

        # Imprimir automáticamente si está configurado
        if cfg()["ticket_auto"] and cfg()["impresora_activa"]:
            ok, msg = imprimir_ticket(venta_id)
            if not ok:
                toast(self, f"Impresora: {msg}", error=True)

        # Botón flotante para enviar por WhatsApp/Email
        if cfg()["whatsapp_activo"] or cfg()["email_activo"]:
            self._mostrar_opciones_envio(venta_id)

    def _mostrar_opciones_envio(self, venta_id: int):
        """Muestra opciones de envío por 5 segundos, desaparece solo."""
        from impresion import previsualizar_ticket
        from config import cfg

        frame = tk.Frame(self, bg=C.primario, padx=8, pady=6)
        frame.place(relx=0.5, rely=0.5, anchor="center")

        lbl(frame, f"Ticket #{venta_id} — Enviar:",
            variante="suave", bg=C.primario, fg=C.blanco).pack(side="left", padx=(0,8))

        if cfg()["whatsapp_activo"]:
            tk.Button(frame, text="WhatsApp", font=F.boton,
                      bg=C.exito, fg=C.blanco, relief="flat",
                      cursor="hand2", padx=10,
                      command=lambda: [frame.destroy(),
                                       self._enviar_wa(venta_id)]).pack(side="left", padx=2)

        if cfg()["email_activo"]:
            tk.Button(frame, text="Email", font=F.boton,
                      bg=C.exito, fg=C.blanco, relief="flat",
                      cursor="hand2", padx=10,
                      command=lambda: [frame.destroy(),
                                       self._enviar_mail(venta_id)]).pack(side="left", padx=2)

        tk.Button(frame, text="Ver ticket", font=F.boton,
                  bg=C.superficie, fg=C.texto, relief="flat",
                  cursor="hand2", padx=10,
                  command=lambda: [frame.destroy(),
                                   previsualizar_ticket(self, venta_id)]).pack(side="left", padx=2)

        tk.Button(frame, text="✕", font=F.boton,
                  bg=C.primario, fg=C.blanco, relief="flat",
                  cursor="hand2",
                  command=frame.destroy).pack(side="left", padx=(4,0))

        # Auto-cerrar en 6 segundos
        self.after(6000, lambda: frame.destroy() if frame.winfo_exists() else None)

    def _enviar_wa(self, venta_id: int):
        from impresion import enviar_whatsapp, _pedir_telefono
        tel = _pedir_telefono(self, "WhatsApp")
        if tel:
            ok, msg = enviar_whatsapp(venta_id, tel)
            toast(self, msg, error=not ok)

    def _enviar_mail(self, venta_id: int):
        from impresion import enviar_email, _pedir_dato
        mail = _pedir_dato(self, "Email", "Direccion de email:")
        if mail:
            ok, msg = enviar_email(venta_id, mail)
            toast(self, msg, error=not ok)

    def _ofrecer_ticket(self, venta_id: int):
        """Pregunta si imprimir ticket. Solo si hay impresora configurada."""
        try:
            from config import cfg as get_cfg
            c = get_cfg()
            if not c.get("impresora_activa", False):
                return
            from tkinter import messagebox
            # default="no": la mayoria de las ventas no lleva ticket, y
            # con F12-Enter-Enter la venta se cierra sin imprimir. Para
            # imprimir hay que decir que si a proposito.
            if messagebox.askyesno(
                    "Ticket",
                    "Imprimir ticket?",
                    parent=self,
                    default="no"):
                from impresion import imprimir_ticket
                ok, msg = imprimir_ticket(venta_id)
                if not ok:
                    toast(self, f"Impresora: {msg}", error=True)
        except Exception as e:
            logging.warning(f"Error al imprimir/enviar ticket (no bloquea la venta): {e}")

    def _nueva_venta(self):
        self.carrito.clear()
        # La foto tambien: si queda, la venta siguiente arranca mostrando
        # un producto que ya se cobro.
        # El cartel de promo se va con la venta: si queda, la venta
        # siguiente arranca ofreciendo algo que ya no esta en el carrito.
        # La sugerencia también se va con la venta: si queda, la próxima
        # arranca ofreciendo algo por un carrito que ya no existe.
        if hasattr(self, "lbl_sugerencias"):
            self.lbl_sugerencias.grid_forget()
        if hasattr(self, "lbl_promo_grupo"):
            self.lbl_promo_grupo.config(text="")
            self.lbl_promo_grupo.grid_forget()
        self.cant_pendiente = None
        self._cliente_cta = None
        self.lbl_cant.config(text="x1")
        self.entry_desc.delete(0, "end")
        self.entry_desc.insert(0, "0")
        # El modo vuelve a %: dejar "$" puesto de la venta anterior es
        # como se cobran de menos $500 sin que nadie lo note.
        if hasattr(self, "desc_modo"):
            self.desc_modo.set("%")
        self._sel_metodo("efectivo")
        self._actualizar_tabla()
        self._actualizar_totales()
        self.foco_scanner()

    def _flash(self, error=False):
        color = C.err_flash if error else C.ok_flash
        self.entry_scan.config(bg=color)
        self.after(300, lambda: self.entry_scan.config(bg=C.superficie))

"""
config_ui.py — Panel de configuración del sistema TPV v2.0
Permite editar todos los parámetros del negocio desde la UI.
"""

import logging
import tkinter as tk
from tkinter import ttk, messagebox
from styles import C, F, btn, card, toast, header_seccion, scrollable
import config as cfg_mod


def _listar_impresoras() -> list[str]:
    """
    Impresoras instaladas en Windows, para elegir de una lista en vez
    de escribir el nombre a mano (tiene que ser EXACTO, así que es
    fácil equivocarse tipeándolo). Si pywin32 no está instalado o no
    es Windows, devuelve una lista vacía — el combo queda usable
    igual, solo sin opciones para elegir.
    """
    try:
        import win32print
        return sorted(p[2] for p in win32print.EnumPrinters(
            win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS))
    except Exception:
        return []


SECCIONES = [
    ("Negocio", [
        ("negocio_nombre",      "Nombre del negocio",      "text"),
        ("negocio_direccion",   "Direccion",               "text"),
        ("negocio_telefono",    "Telefono",                "text"),
        ("negocio_cuit",        "CUIT",                    "text"),
        ("negocio_email",       "Email del negocio",       "text"),
        ("negocio_web",         "Sitio web",               "text"),
        ("negocio_logo_path",   "Ruta al logo (imagen)",   "text"),
        ("negocio_mensaje_pie", "Mensaje pie de ticket",   "text"),
    ]),
    ("Impresora", [
        ("impresora_activa",    "Impresora activa",        "bool"),
        ("impresora_ancho",     "Ancho (caracteres)",      "int"),
        ("impresora_nombre",    "Nombre impresora (vacio = default)", "combo_impresora"),
        ("impresora_puerto",    "Puerto (USB / COM1 / IP)","text"),
        ("impresora_ip",        "IP (si es red)",          "text"),
        ("ticket_auto",         "Imprimir al cobrar automaticamente", "bool"),
    ]),
    ("WhatsApp", [
        ("whatsapp_activo",     "WhatsApp activo",         "bool"),
        ("whatsapp_numero",     "Numero del negocio",      "text"),
    ]),
    ("Email (SMTP)", [
        ("email_activo",        "Email activo",            "bool"),
        ("email_smtp_host",     "Servidor SMTP",           "text"),
        ("email_smtp_port",     "Puerto SMTP",             "int"),
        ("email_usuario",       "Usuario / Email",         "text"),
        ("email_password",      "Contrasena",              "password"),
        ("email_remitente",     "Nombre remitente",        "text"),
    ]),
    ("Stock y Alertas", [
        ("stock_alerta_umbral",   "Umbral stock critico (unidades)", "int"),
        ("stock_alerta_dias_vto", "Dias para alerta de vencimiento", "int"),
    ]),
    ("Informe de stock por email", [
        ("informe_stock_email_activo",        "Envio automatico activo",  "bool"),
        ("informe_stock_email_destinatario",  "Email que lo recibe",      "text"),
        ("informe_stock_email_hora",          "Hora de envio (HH:MM)",    "text"),
        ("informe_stock_email_solo_criticos", "Enviar solo stock critico (no todo el catalogo)", "bool"),
    ]),
    ("Caja y Seguridad", [
        ("caja_clave_responsable", "Clave del responsable", "password"),
        ("caja_requiere_fondo",    "Pedir fondo al abrir caja", "bool"),
    ]),
    ("Etiquetas de gondola", [
        ("etiqueta_ancho_mm",        "Ancho de etiqueta (mm)",         "int"),
        ("etiqueta_alto_mm",         "Alto de etiqueta (mm)",          "int"),
        ("etiqueta_cols",            "Columnas por hoja A4",           "int"),
        ("etiqueta_filas",           "Filas por hoja A4",              "int"),
        ("etiqueta_margen_arriba_mm","Espacio arriba de la hoja (mm)", "int"),
        ("etiqueta_espacio_mm",      "Espacio entre etiquetas (mm)",   "int"),
        ("etiqueta_mostrar_barcode", "Mostrar codigo de barras",       "bool"),
        ("etiqueta_mostrar_promo",   "Mostrar precio promo",           "bool"),
        ("etiqueta_font_nombre",     "Fuente nombre (pt)",             "int"),
        ("etiqueta_font_label",      "Fuente label promo (pt)",        "int"),
        ("etiqueta_font_precio",     "Fuente precio principal (pt)",   "int"),
        ("etiqueta_font_secundario", "Fuente precios secundarios (pt)","int"),
        ("etiqueta_font_codigo",     "Fuente codigo de barras (pt)",   "int"),
    ]),
    ("Folleto de ofertas", [
        ("folleto_color",         "Color del folleto (hex, ej #2451B0)",       "text"),
        ("folleto_color_precio",  "Color del cartel de precio (hex, ej #DC2626)", "text"),
        ("folleto_titulo",        "Titulo del encabezado (ej OFERTAS DE FEBRERO)", "text"),
        ("folleto_mostrar_codigo","Incluir codigo/PLU en el folleto",          "bool"),
    ]),
    ("Vencimientos", [
        ("stock_alerta_dias_vto", "Dias de aviso (general, se puede pisar por producto)", "int"),
        ("vto_email_activo",      "Avisar por email al abrir el TPV",        "bool"),
        ("vto_email_destinatario","Email destinatario",                      "text"),
    ]),
    ("Redondeo de precios", [
        ("redondeo_precios", "Redondear a multiplos de (0 = sin redondeo; 1, 10, 50, 100)", "int"),
    ]),
    ("Balanza", [
        ("balanza_activa",   "Balanza activa",                    "bool"),
        ("balanza_puerto",   "Puerto (ej COM3)",                  "text"),
        ("balanza_baudrate", "Velocidad (baudrate, normalmente 9600)", "int"),
    ]),
    ("Catálogo web (pedidos de clientes)", [
        ("catalogo_web_activo", "Sincronización activa",          "bool"),
        ("catalogo_web_url",    "URL de la Apps Script Web App",  "text"),
    ]),
    ("Sistema", [
        ("moneda_simbolo",    "Simbolo de moneda",         "text"),
        ("backup_automatico", "Backup automatico",         "bool"),
        ("backup_max",        "Maximos backups a conservar","int"),
        ("logs_max",          "Maximos logs a conservar",  "int"),
    ]),
]


class ConfigUI(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._entries = {}
        self._build()
        self._cargar_valores()

    def _build(self):
        header_seccion(
            self, "Configuracion",
            "Ajusta los parametros del negocio, impresora, email y sistema"
        ).pack(fill="x", padx=12, pady=(8, 4))

        # Contenedor principal con scroll
        outer, inner = scrollable(self, bg=C.bg)
        outer.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        inner.columnconfigure(0, weight=1)

        # Una card por sección
        for i, (seccion, campos) in enumerate(SECCIONES):
            c = card(inner)
            c.pack(fill="x", pady=(0, 10))
            c.columnconfigure(1, weight=1)

            # Título de sección
            tk.Label(c, text=seccion, font=F.subtitulo,
                     bg=C.superficie, fg=C.primario,
                     pady=8, padx=16).grid(
                row=0, column=0, columnspan=2, sticky="w")

            ttk.Separator(c, orient="horizontal").grid(
                row=1, column=0, columnspan=2, sticky="ew", padx=16)

            for j, (clave, label, tipo) in enumerate(campos):
                # Label
                tk.Label(c, text=label, font=F.normal,
                         bg=C.superficie, fg=C.texto,
                         anchor="w").grid(
                    row=j+2, column=0, sticky="w",
                    padx=(16, 8), pady=(6, 2))

                # Widget según tipo
                if tipo == "bool":
                    var = tk.BooleanVar()
                    widget = tk.Checkbutton(
                        c, variable=var,
                        bg=C.superficie, activebackground=C.superficie,
                        cursor="hand2")
                    widget.grid(row=j+2, column=1, sticky="w",
                                padx=(0, 16), pady=(6, 2))
                    self._entries[clave] = ("bool", var)

                elif tipo == "password":
                    e = tk.Entry(c, font=F.normal, bg=C.superficie,
                                  fg=C.texto, relief="solid", bd=1,
                                  show="*")
                    e.grid(row=j+2, column=1, sticky="ew",
                           padx=(0, 16), pady=(6, 2), ipady=5)
                    self._entries[clave] = ("text", e)

                elif tipo == "combo_impresora":
                    e = ttk.Combobox(c, font=F.normal, state="readonly",
                                     values=[""] + _listar_impresoras())
                    e.grid(row=j+2, column=1, sticky="ew",
                           padx=(0, 16), pady=(6, 2), ipady=3)
                    self._entries[clave] = ("text", e)

                else:  # text o int
                    e = tk.Entry(c, font=F.normal, bg=C.superficie,
                                  fg=C.texto, relief="solid", bd=1)
                    e.grid(row=j+2, column=1, sticky="ew",
                           padx=(0, 16), pady=(6, 2), ipady=5)
                    self._entries[clave] = (tipo, e)

        # Botones guardar / restaurar
        fb = tk.Frame(inner, bg=C.bg)
        fb.pack(fill="x", pady=(4, 12))
        btn(fb, "Guardar configuracion", variante="exito",
            comando=self._guardar).pack(side="left")
        btn(fb, "Restaurar valores por defecto", variante="neutro",
            comando=self._restaurar).pack(side="left", padx=8)
        btn(fb, "Probar impresora", variante="primario",
            comando=self._probar_impresora).pack(side="right")
        btn(fb, "Imprimir ticket de ejemplo", variante="primario",
            comando=self._imprimir_ticket_prueba).pack(side="right", padx=(0,8))
        btn(fb, "Probar balanza", variante="primario",
            comando=self._probar_balanza).pack(side="right", padx=(0,8))
        btn(fb, "Sincronizar catálogo ahora", variante="primario",
            comando=self._sincronizar_catalogo).pack(side="right", padx=(0,8))

    def _cargar_valores(self):
        c = cfg_mod.cargar()
        for clave, (tipo, widget) in self._entries.items():
            valor = c.get(clave, "")
            if tipo == "bool":
                widget.set(bool(valor))
            elif isinstance(widget, ttk.Combobox):
                # .insert() no tira error en un Combobox "readonly" pero
                # tampoco hace nada — hay que usar .set()
                widget.set(str(valor) if valor is not None else "")
            else:
                widget.delete(0, "end")
                widget.insert(0, str(valor) if valor is not None else "")

    def _guardar(self):
        c = cfg_mod.cargar()
        errores = []
        for clave, (tipo, widget) in self._entries.items():
            if tipo == "bool":
                c[clave] = widget.get()
            elif tipo == "int":
                try:
                    c[clave] = int(widget.get().strip())
                except ValueError:
                    errores.append(f"{clave}: debe ser un numero entero")
            else:
                c[clave] = widget.get().strip()

        if errores:
            messagebox.showwarning("Errores de validacion",
                "\n".join(errores), parent=self)
            return

        cfg_mod.guardar(c)
        cfg_mod.reload()

        # Actualizar clave de responsable en fiado_ui si cambió
        try:
            import fiado_ui
            fiado_ui.CLAVE_RESPONSABLE = c.get("caja_clave_responsable", "1234")
        except Exception as e:
            # Si esto falla, la clave de responsable sigue siendo la vieja
            # aunque la pantalla diga que se guardo.
            logging.warning(f"No se pudo actualizar la clave de responsable "
                            f"en memoria: {e}. Reinicia el TPV para aplicarla.")

        toast(self, "Configuracion guardada")

    def _restaurar(self):
        if messagebox.askyesno("Restaurar",
            "Restaurar todos los valores por defecto?\n"
            "Se perdera la configuracion actual.",
            parent=self):
            cfg_mod.guardar(dict(cfg_mod.DEFAULTS))
            cfg_mod.reload()
            self._cargar_valores()
            toast(self, "Valores restaurados")

    def _probar_impresora(self):
        """Imprime un ticket de prueba — usa lo que está elegido en
        pantalla AHORA MISMO (guardado o no), no lo que haya quedado
        en el archivo de configuración de antes. Si tocás el combo y
        probás sin guardar, prueba igual con lo que ves elegido."""
        c = cfg_mod.cargar()
        w = c["impresora_ancho"]

        _, widget_nombre = self._entries["impresora_nombre"]
        nombre_actual = widget_nombre.get().strip()

        texto = (
            "=" * w + "\n" +
            c["negocio_nombre"].center(w) + "\n" +
            "TICKET DE PRUEBA".center(w) + "\n" +
            "=" * w + "\n" +
            "Si ves esto, la impresora funciona!\n" +
            "=" * w + "\n"
        )

        # Imprimir directo
        import sys
        from impresion import _imprimir_escpos, _imprimir_windows
        ok, msg = _imprimir_escpos(texto, nombre_impresora=nombre_actual)
        if not ok and sys.platform == "win32":
            ok, msg = _imprimir_windows(texto, nombre_impresora=nombre_actual)
        messagebox.showinfo(
            "Prueba de impresora",
            f"{'OK' if ok else 'Error'}: {msg}\n\n"
            f"(si esta impresora no es la que esperabas, acordate de "
            f"tocar \"Guardar configuracion\" para que las ventas "
            f"reales impriman ahí también)",
            parent=self)

    def _imprimir_ticket_prueba(self):
        """Imprime un ticket con formato REAL (encabezado del negocio,
        ítems, promo, total, pie) pero con datos inventados — para ver
        cómo sale un ticket de verdad sin facturar nada. Usa la
        impresora elegida en pantalla ahora mismo, guardada o no."""
        _, widget_nombre = self._entries["impresora_nombre"]
        nombre_actual = widget_nombre.get().strip()

        from impresion import imprimir_ticket_prueba
        ok, msg = imprimir_ticket_prueba(nombre_impresora=nombre_actual)
        messagebox.showinfo(
            "Ticket de ejemplo",
            f"{'OK' if ok else 'Error'}: {msg}",
            parent=self)

    def _probar_balanza(self):
        """Pide el peso una vez y muestra el detalle crudo — para
        confirmar que el puerto/protocolo están bien configurados."""
        c = cfg_mod.cargar()
        import balanza
        resultado = balanza.diagnosticar_balanza(
            puerto=c.get("balanza_puerto"),
            baudrate=c.get("balanza_baudrate"))
        messagebox.showinfo("Prueba de balanza", resultado, parent=self)

    def _sincronizar_catalogo(self):
        """Manda el catálogo actual a la Google Sheet."""
        c = cfg_mod.cargar()
        import catalogo_web
        ok, msg = catalogo_web.sincronizar(c.get("catalogo_web_url"))
        if ok:
            messagebox.showinfo("Catálogo web", msg, parent=self)
        else:
            messagebox.showwarning("Catálogo web", msg, parent=self)

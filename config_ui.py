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
    ("Caja y Seguridad", [
        ("caja_clave_responsable", "Clave del responsable", "password"),
        ("caja_requiere_fondo",    "Pedir fondo al abrir caja", "bool"),
    ]),
    ("Stock, alertas y vencimientos", [
        ("stock_alerta_umbral",      "Umbral de stock critico (unidades)",   "int"),
        ("stock_alerta_dias_vto",    "Días de aviso por vencimiento (se puede pisar por producto)", "int"),
        ("permitir_venta_sin_stock", "Permitir vender sin stock registrado", "bool"),
    ]),
    ("Avisos por email", [
        # Un solo destinatario para TODOS los avisos: tenerlo repetido en
        # tres secciones hacia que uno quedara vacio y el envio fallara.
        ("aviso_diario_destinatario",   "Email(s) que reciben los avisos — separar con comas", "text"),
        ("aviso_diario_activo",         "Activar el aviso diario",              "bool"),
        ("aviso_diario_a_las",          "Mandarlo a una hora fija (recomendado)", "bool"),
        ("aviso_diario_hora",           "¿A qué hora?",                         "hora"),
        ("aviso_diario_dias_cobertura", "Reponer para cuántos días de venta",   "int"),
        ("aviso_diario_al_abrir_app",   "También al abrir el sistema",          "bool"),
        ("aviso_diario_al_abrir_caja",  "También al abrir la caja",             "bool"),
        ("aviso_diario_al_cerrar_caja", "También al cerrar la caja",            "bool"),
        ("aviso_incluir_stock_completo", "Incluir el listado de stock completo", "bool"),
        ("aviso_revisar_datos", "Incluir la revisión de datos (productos en $0, stock negativo…)", "bool"),
        ("aviso_cuando_vendo", "Incluir qué días y horas se vende más",  "bool"),
        ("aviso_top_dias",     "Lo más vendido: de cuántos días (0 = histórico completo)", "int"),
        ("aviso_top_cantidad", "Lo más vendido: cuántos productos mostrar",  "int"),
    ]),
    ("Fotos de productos", [
        ("buscador_fotos", "Buscador (bing / duckduckgo / google)", "text"),
    ]),
    ("Catálogo web", [
        ("catalogo_web_activo",      "Sincronización activa",                "bool"),
        ("catalogo_web_url",         "URL de la Apps Script Web App",        "text"),
        ("catalogo_sync_auto",       "Sincronizar solo, cada tantas horas",  "bool"),
        ("catalogo_sync_cada_horas", "¿Cada cuántas horas?",                 "int"),
        ("web_solo_con_stock",       "Publicar solo lo que tiene stock",     "bool"),
        ("web_solo_con_foto",        "Publicar solo lo que tiene foto",      "bool"),
        ("web_excluir_categorias",   "Categorías que NO se publican",        "categorias"),
    ]),
    ("Etiquetas de gondola", [
        ("etiqueta_ancho_mm",        "Ancho de etiqueta (mm)",         "int"),
        ("etiqueta_alto_mm",         "Alto de etiqueta (mm)",          "int"),
        ("etiqueta_cols",            "Columnas por hoja A4",           "int"),
        ("etiqueta_filas",           "Filas por hoja A4",              "int"),
        ("etiqueta_margen_arriba_mm","Espacio arriba de la hoja (mm)", "int"),
        ("etiqueta_espacio_mm",      "Espacio entre etiquetas (mm)",   "int"),
        ("etiqueta_margen_lateral_mm", "Margen lateral mínimo (mm)",           "int"),
        ("etiqueta_pegadas",     "Etiquetas pegadas entre sí (menos cortes)", "bool"),
        ("etiqueta_guias_corte", "Marcas de corte en los bordes",             "bool"),
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
        ("folleto_titulo",        "Titulo grande centrado (vacio = sin titulo)",  "text"),
        ("folleto_subtitulo",     "Rotulo chico sobre la linea (vacio = sin rotulo)", "text"),
        ("folleto_mostrar_codigo","Incluir codigo/PLU en el folleto",          "bool"),
        ("folleto_foto_pct", "Tamano de la foto (% del alto de cada celda, 25-75)", "int"),
        ("folleto_precio_sobre_foto", "Precio superpuesto sobre la foto (mas lugar para el texto)", "bool"),
        ("folleto_categoria_pagina_nueva",
         "Cada categoria en una hoja nueva (destildado = todo seguido)",       "bool"),
    ]),
    ("Redondeo de precios", [
        ("redondeo_precios", "Redondear a multiplos de (0 = sin redondeo; 1, 10, 50, 100)", "int"),
        ("redondeo_modo", "Modo: cercano / arriba / abajo", "text"),
    ]),
    ("Balanza", [
        ("balanza_activa",   "Balanza activa",                    "bool"),
        ("balanza_puerto",   "Puerto (ej COM3)",                  "text"),
        ("balanza_baudrate", "Velocidad (baudrate, normalmente 9600)", "int"),
    ]),
    ("Sistema", [
        ("moneda_simbolo",    "Simbolo de moneda",         "text"),
        ("backup_automatico", "Backup automatico",         "bool"),
        ("backup_max",        "Maximos backups a conservar","int"),
        ("backup_diario",      "Copia diaria aparte (recomendado)", "bool"),
        ("backup_diario_dias", "Cuántos días de copias diarias guardar", "int"),
        ("logs_max",          "Maximos logs a conservar",  "int"),
    ]),
]


class _SelectorCategorias(tk.Frame):
    """Casillas con las categorías que existen de verdad.

    Guarda IDS, no nombres: renombrar una categoría no rompe el filtro, y
    si se borra una simplemente deja de aparecer.
    """

    def __init__(self, parent):
        super().__init__(parent, bg=C.superficie)
        self._vars = {}
        self._lbl = tk.Label(self, text="", bg=C.superficie, fg=C.texto_suave,
                             font=F.pequeña, anchor="w")
        self._lbl.pack(anchor="w")
        btn(self, "Elegir categorías…", variante="neutro",
            comando=self._abrir).pack(anchor="w", pady=(2, 0))
        self._recargar()

    def _recargar(self):
        from repositorio import get_categorias
        try:
            self._cats = list(get_categorias())
        except Exception:
            self._cats = []
        self._pintar()

    def _pintar(self):
        elegidas = [c["nombre"] for c in self._cats
                    if self._vars.get(c["id"])]
        if not elegidas:
            self._lbl.config(text="Se publican todas", fg=C.texto_suave)
        else:
            txt = ", ".join(elegidas[:3])
            if len(elegidas) > 3:
                txt += f" y {len(elegidas) - 3} más"
            self._lbl.config(text=f"No se publica: {txt}", fg=C.peligro)

    def _abrir(self):
        self._recargar()
        d = tk.Toplevel(self)
        d.title("Categorías que no se publican")
        d.configure(bg=C.superficie)
        d.grab_set()
        d.geometry("420x460")

        tk.Label(d, text="Categorías que NO se publican", bg=C.superficie,
                 fg=C.texto, font=F.titulo, anchor="w").pack(
            anchor="w", padx=18, pady=(16, 2))
        tk.Label(d, text="Lo que quede sin marcar sí se publica.",
                 bg=C.superficie, fg=C.texto_suave, font=F.pequeña,
                 anchor="w").pack(anchor="w", padx=18)

        pie = tk.Frame(d, bg=C.superficie)
        pie.pack(side="bottom", fill="x", pady=14)

        cont = tk.Frame(d, bg=C.superficie, highlightthickness=1,
                        highlightbackground=C.borde)
        cont.pack(fill="both", expand=True, padx=18, pady=(12, 6))
        canvas = tk.Canvas(cont, bg=C.superficie, highlightthickness=0)
        sb = ttk.Scrollbar(cont, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=C.superficie)
        inner.bind("<Configure>", lambda e: canvas.configure(
            scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        temp = {}
        for cat in self._cats:
            v = tk.BooleanVar(value=bool(self._vars.get(cat["id"])))
            temp[cat["id"]] = v
            tk.Checkbutton(inner, text=cat["nombre"][:34], variable=v,
                           bg=C.superficie, fg=C.texto, font=F.normal,
                           anchor="w", selectcolor=C.superficie,
                           activebackground=C.superficie).pack(
                anchor="w", padx=10, pady=1)

        def aceptar():
            self._vars = {k: v.get() for k, v in temp.items()}
            self._pintar()
            d.destroy()

        btn(pie, "Aceptar", variante="exito", comando=aceptar).pack(
            side="left", padx=(18, 6))
        btn(pie, "Cancelar", variante="neutro", comando=d.destroy).pack(
            side="left")
        d.bind("<Escape>", lambda ev: d.destroy())

    def set_seleccion(self, valor):
        """Acepta lista de ids, texto con comas (formato viejo) o vacío."""
        self._recargar()
        self._vars = {}
        if not valor:
            self._pintar()
            return
        if isinstance(valor, str):
            partes = [x.strip() for x in valor.split(",") if x.strip()]
            # Formato viejo: eran NOMBRES. Se convierten a ids una vez.
            por_nombre = {c["nombre"].lower(): c["id"] for c in self._cats}
            for x in partes:
                if x.isdigit():
                    self._vars[int(x)] = True
                elif x.lower() in por_nombre:
                    self._vars[por_nombre[x.lower()]] = True
        else:
            for x in valor:
                try:
                    self._vars[int(x)] = True
                except (TypeError, ValueError):
                    pass
        self._pintar()

    def get_seleccion(self):
        return [cid for cid, marcado in self._vars.items() if marcado]


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

        # La barra de acciones va FUERA del scroll y anclada abajo: con
        # 15 secciones el contenido mide varios miles de px y "Guardar"
        # quedaba al final, invisible salvo que uno bajara todo.
        self._barra_acciones = tk.Frame(self, bg=C.bg)
        self._barra_acciones.pack(side="bottom", fill="x", padx=12, pady=(4, 10))

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

                elif tipo == "categorias":
                    # Se eligen de la lista real: escribir el nombre a
                    # mano se rompe en silencio apenas se renombra una
                    # categoria, y nadie se entera hasta que la pagina
                    # muestra algo que no debia.
                    var = _SelectorCategorias(c)
                    var.grid(row=j+2, column=1, sticky="w",
                             padx=(0, 16), pady=(6, 2))
                    self._entries[clave] = ("categorias", var)

                elif tipo == "hora":
                    # Desplegable con las 24 horas: escribir "0 a 23" a
                    # mano deja lugar a poner "15:30" o "3 PM", que el
                    # sistema no entiende y hace que el aviso no salga.
                    var = tk.StringVar()
                    widget = ttk.Combobox(
                        c, textvariable=var, width=10, state="readonly",
                        values=[f"{h:02d}:00" for h in range(24)])
                    widget.grid(row=j+2, column=1, sticky="w",
                                padx=(0, 16), pady=(6, 2))
                    self._entries[clave] = ("hora", var)

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

        # Botones guardar / restaurar — en la barra fija de abajo
        # Dos filas: siete botones en una sola se salian de la pantalla y
        # el de sincronizar quedaba invisible.
        fb = self._barra_acciones
        btn(fb, "Guardar configuracion", variante="exito",
            comando=self._guardar).pack(side="left")
        btn(fb, "Restaurar valores por defecto", variante="neutro",
            comando=self._restaurar).pack(side="left", padx=8)
        from db import MODO_PRUEBA
        if not MODO_PRUEBA:
            btn(fb, "🧪  Abrir modo prueba", variante="neutro",
                comando=self._abrir_modo_prueba).pack(side="left", padx=8)

        fb2 = tk.Frame(fb.master, bg=fb.cget("bg"))
        fb2.pack(fill="x", pady=(6, 0))
        tk.Label(fb2, text="Probar:", bg=fb.cget("bg"), fg=C.texto_suave,
                 font=F.pequeña).pack(side="left", padx=(0, 6))
        btn(fb2, "🖨 Impresora", variante="primario",
            comando=self._probar_impresora).pack(side="left", padx=(0, 6))
        btn(fb2, "🧾 Ticket de ejemplo", variante="primario",
            comando=self._imprimir_ticket_prueba).pack(side="left", padx=(0, 6))
        btn(fb2, "⚖ Balanza", variante="primario",
            comando=self._probar_balanza).pack(side="left", padx=(0, 6))
        btn(fb2, "✉ Emails", variante="primario",
            comando=self._probar_emails).pack(side="left", padx=(0, 6))
        btn(fb2, "🌐 Sincronizar catálogo web", variante="primario",
            comando=self._sincronizar_catalogo).pack(side="left", padx=(0, 6))

        self.lbl_sync = tk.Label(fb.master, text="", bg=fb.cget("bg"),
                                 fg=C.texto_suave, font=F.pequeña, anchor="w")
        self.lbl_sync.pack(fill="x", pady=(6, 0))
        self._actualizar_estado_sync()

    def _cargar_valores(self):
        c = cfg_mod.cargar()
        for clave, (tipo, widget) in self._entries.items():
            valor = c.get(clave, "")
            if tipo == "bool":
                widget.set(bool(valor))
            elif tipo == "categorias":
                widget.set_seleccion(valor)
            elif tipo == "hora":
                # En la config es un entero; en pantalla se muestra HH:00
                try:
                    h = int(str(valor).split(":")[0])
                except (ValueError, IndexError):
                    h = 21
                widget.set(f"{max(0, min(23, h)):02d}:00")
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
            elif tipo == "categorias":
                # Se guardan los IDS, no los nombres: renombrar una
                # categoria no tiene por que romper el filtro.
                c[clave] = widget.get_seleccion()
            elif tipo == "hora":
                # Se guarda como ENTERO: la comparacion con la hora del
                # reloj tiene que ser numerica.
                try:
                    c[clave] = int(str(widget.get()).split(":")[0])
                except (ValueError, IndexError):
                    errores.append(f"{clave}: elegí una hora de la lista")
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

    def _abrir_modo_prueba(self):
        """Abre una segunda ventana del TPV contra una copia de la base.

        Sin esto habia que acordarse de dos comandos en la consola, y lo
        que uno no usa todos los dias se olvida justo cuando hace falta.
        """
        import os
        import subprocess
        import sys
        from tkinter import messagebox

        base = os.path.dirname(os.path.abspath(__file__))
        copia = os.path.join(base, "tpv2_prueba.db")

        if not os.path.exists(copia):
            if not messagebox.askyesno(
                    "Modo prueba",
                    "No existe todavía la base de prueba.\n\n"
                    "Se va a crear una copia de la base real para poder "
                    "probar sin riesgo. Puede tardar unos segundos.\n\n"
                    "¿La creo?", parent=self):
                return
            try:
                # Se copia con la API de sqlite y no con shutil: la base
                # corre en modo WAL y una copia del archivo dejaria
                # afuera las ultimas operaciones.
                import sqlite3
                from db import DB_PATH
                origen = sqlite3.connect(DB_PATH)
                destino = sqlite3.connect(copia)
                origen.backup(destino)
                destino.close()
                origen.close()
            except Exception as exc:
                messagebox.showerror("Modo prueba",
                                     f"No se pudo crear la copia:\n{exc}",
                                     parent=self)
                return

        entorno = dict(os.environ, TPV_DB="tpv2_prueba.db")

        # Que interprete usar. sys.executable puede ser pythonw.exe (o el
        # propio .exe si algun dia se empaqueta), y con eso el proceso
        # moria sin abrir nada ni avisar. Se prueban candidatos en orden.
        candidatos = []
        venv = os.path.join(base, ".venv", "Scripts", "python.exe")
        if os.path.exists(venv):
            candidatos.append(venv)
        exe = sys.executable or ""
        if exe.lower().endswith("pythonw.exe"):
            candidatos.append(exe[:-len("pythonw.exe")] + "python.exe")
        if exe and exe.lower().endswith((".exe",)) and "python" in exe.lower():
            candidatos.append(exe)
        candidatos += ["python", "python3"]

        proc, usado, errores = None, None, []
        for cand in candidatos:
            try:
                proc = subprocess.Popen(
                    [cand, os.path.join(base, "main.py")],
                    cwd=base, env=entorno,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                usado = cand
                break
            except Exception as exc:
                errores.append(f"{cand}: {exc}")

        if proc is None:
            messagebox.showerror(
                "Modo prueba",
                "No se encontró Python para abrir la segunda ventana.\n\n"
                "Probá con el archivo TPV_MODO_PRUEBA.bat de la carpeta "
                "del sistema.\n\nIntentos:\n  " + "\n  ".join(errores[:4]),
                parent=self)
            return

        # Se espera un momento y se verifica que siga vivo: si murio al
        # arrancar, mostrar "se abrio otra ventana" seria mentira.
        import time
        time.sleep(1.5)
        if proc.poll() is not None:
            salida = ""
            try:
                _o, err = proc.communicate(timeout=2)
                salida = (err or b"").decode("utf-8", "replace")[-600:]
            except Exception:
                pass
            messagebox.showerror(
                "Modo prueba",
                f"La segunda ventana se cerró al arrancar.\n\n"
                f"Interprete: {usado}\n\n{salida or 'Sin detalle.'}",
                parent=self)
            return

        messagebox.showinfo(
            "Modo prueba",
            "Se abrió otra ventana del TPV con una franja roja arriba.\n\n"
            "Esa trabaja sobre la copia: probá lo que quieras.\n"
            "Esta ventana sigue conectada a la base real.\n\n"
            "Para volver a empezar de cero, borrá tpv2_prueba.db.",
            parent=self)

    def _probar_emails(self):
        """Manda cada aviso al instante, sin gastar el envío del día.

        Sin esto hay que esperar a la hora programada para saber si anda,
        y si no llega no se sabe si falló el mail o la programación.
        """
        d = tk.Toplevel(self)
        d.title("Probar los emails")
        d.configure(bg=C.superficie)
        d.grab_set()
        d.geometry("580x430")

        tk.Label(d, text="Probar los emails", bg=C.superficie, fg=C.texto,
                 font=F.titulo, anchor="w").pack(anchor="w", padx=18,
                                                 pady=(16, 2))
        tk.Label(d, text=("Se manda al instante y NO consume el envío "
                          "programado del día."),
                 bg=C.superficie, fg=C.texto_suave, font=F.pequeña,
                 anchor="w").pack(anchor="w", padx=18)

        salida = tk.Text(d, height=10, font=F.mono, bg=C.bg, fg=C.texto,
                         relief="solid", bd=1, wrap="word")
        salida.pack(fill="both", expand=True, padx=18, pady=(12, 8))

        def _log(txt, ok=None):
            marca = "" if ok is None else ("[OK]  " if ok else "[FALLA]  ")
            salida.insert("end", f"{marca}{txt}\n")
            salida.see("end")
            salida.update_idletasks()

        def _probar(nombre, fn):
            _log(f"\n— {nombre} —")
            try:
                ok, msg = fn()
                _log(msg or ("Enviado" if ok else "No se pudo"), ok=ok)
            except Exception as exc:
                _log(f"{type(exc).__name__}: {exc}", ok=False)

        def _aviso():
            from impresion import enviar_aviso_diario
            _probar("Aviso diario (stock, vencimientos y ventas del día)",
                    lambda: enviar_aviso_diario("PRUEBA MANUAL", forzar=True))

        def _vtos():
            from impresion import enviar_alerta_vencimientos
            _probar("Alerta de vencimientos",
                    lambda: enviar_alerta_vencimientos(
                        solo_una_vez_por_dia=False))

        def _stock():
            from impresion import enviar_informe_stock
            _probar("Informe de stock", enviar_informe_stock)

        def _todos():
            salida.delete("1.0", "end")
            _aviso()
            _vtos()
            _stock()
            _log("\nListo. Si alguno falló, revisá la configuración de "
                 "email más arriba.")

        botones = tk.Frame(d, bg=C.superficie)
        botones.pack(fill="x", padx=18)
        btn(botones, "Aviso diario", variante="neutro",
            comando=_aviso).pack(side="left", padx=(0, 4))
        btn(botones, "Vencimientos", variante="neutro",
            comando=_vtos).pack(side="left", padx=4)
        btn(botones, "Informe de stock", variante="neutro",
            comando=_stock).pack(side="left", padx=4)
        btn(botones, "▶  Probar todos", variante="exito",
            comando=_todos).pack(side="left", padx=(12, 0))

        pie = tk.Frame(d, bg=C.superficie)
        pie.pack(side="bottom", fill="x", pady=12)
        btn(pie, "Cerrar", variante="neutro",
            comando=d.destroy).pack(side="right", padx=18)
        d.bind("<Escape>", lambda ev: d.destroy())

        from config import cfg
        dest = cfg().get("aviso_diario_destinatario", "")
        _log(f"Destinatario: {dest or '(sin configurar)'}")
        if not dest:
            _log("Cargá el destinatario en «Aviso diario por email» y "
                 "guardá antes de probar.", ok=False)
        _log("Elegí qué probar.")

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

    def _texto_estado_sync(self):
        """Cuándo se sincronizó y cuándo vuelve a hacerlo.

        Sin esto no hay forma de saber si la página que ven los clientes
        está al día: se descubre cuando alguien pide algo a un precio
        viejo.
        """
        from datetime import datetime, timedelta
        c = cfg_mod.cargar()
        ultima = c.get("_catalogo_sync_ultima") or ""
        if not ultima:
            return ("Todavía no se sincronizó nunca.", C.peligro)

        try:
            prev = datetime.fromisoformat(ultima)
        except ValueError:
            return (f"Última sincronización: {ultima}", C.texto_suave)

        mins = (datetime.now() - prev).total_seconds() / 60
        if mins < 60:
            hace = f"hace {mins:.0f} min"
        elif mins < 60 * 24:
            hace = f"hace {mins/60:.0f} h"
        else:
            hace = f"hace {mins/1440:.0f} días"
        txt = f"Última: {prev.strftime('%d/%m %H:%M')} ({hace})"

        if not c.get("catalogo_sync_auto"):
            return (txt + "  ·  la automática está apagada", C.texto_suave)

        cada = max(1, int(c.get("catalogo_sync_cada_horas", 6) or 6))
        prox = prev + timedelta(hours=cada)
        if prox <= datetime.now():
            # Vencida: o el TPV estuvo cerrado, o la sync viene fallando
            return (txt + "  ·  la próxima ya venció — se hará al abrir "
                          "el TPV", C.advertencia)
        falta = (prox - datetime.now()).total_seconds() / 60
        cuando = (f"en {falta:.0f} min" if falta < 60
                  else f"en {falta/60:.0f} h")
        return (txt + f"  ·  próxima {prox.strftime('%H:%M')} ({cuando})",
                C.texto_suave)

    def _actualizar_estado_sync(self):
        if not hasattr(self, "lbl_sync"):
            return
        try:
            txt, color = self._texto_estado_sync()
            self.lbl_sync.config(text=txt, fg=color)
        except Exception:
            pass
        # Se refresca solo: el "hace 5 min" envejece mientras la pantalla
        # queda abierta.
        self.after(60000, self._actualizar_estado_sync)

    def _sincronizar_catalogo(self):
        """Manda el catálogo actual a la Google Sheet."""
        c = cfg_mod.cargar()
        import catalogo_web
        ok, msg = catalogo_web.sincronizar(c.get("catalogo_web_url"))
        if ok:
            from datetime import datetime
            cfg_mod.set("_catalogo_sync_ultima",
                        datetime.now().isoformat(timespec="seconds"))
            self._actualizar_estado_sync()
        if ok:
            messagebox.showinfo("Catálogo web", msg, parent=self)
        else:
            messagebox.showwarning("Catálogo web", msg, parent=self)

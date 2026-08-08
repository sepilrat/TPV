"""
impresion.py — Impresión de tickets y envío TPV v2.0
Soporta: térmica ESC/POS, Windows, PDF, WhatsApp, Email
"""

import os
import sys
import tempfile
import logging
from datetime import datetime
from config import cfg
from db import get_connection


# ─────────────────────────────────────────────────────────────────────────────
# GENERACIÓN DEL TICKET EN TEXTO
# ─────────────────────────────────────────────────────────────────────────────

def _linea(char="─", ancho=None):
    return char * (ancho or cfg()["impresora_ancho"])


def _fmt_cant(v):
    """Formatea cantidad: entera sin decimales, fraccionaria con hasta
    3 decimales (para productos vendidos por peso)."""
    v = float(v)
    if v == int(v):
        return str(int(v))
    return f"{v:.3f}".rstrip("0").rstrip(".")

def _centrar(texto, ancho=None):
    return texto.center(ancho or cfg()["impresora_ancho"])

def _col2(izq, der, ancho=None):
    w = ancho or cfg()["impresora_ancho"]
    esp = max(1, w - len(izq) - len(der))
    return izq + " " * esp + der


def generar_texto_ticket(venta_id: int) -> str | None:
    """Genera el texto completo del ticket para una venta."""
    c = cfg()
    with get_connection() as conn:
        venta = conn.execute(
            "SELECT * FROM ventas WHERE id=?", (venta_id,)
        ).fetchone()
        if not venta:
            return None
        items = conn.execute("""
            SELECT descripcion, cantidad, precio_unitario, subtotal, promo_aplicada
            FROM detalle_ventas WHERE venta_id=?
        """, (venta_id,)).fetchall()
        cliente = None
        if venta["cliente_id"]:
            cliente = conn.execute(
                "SELECT nombre, dni FROM clientes WHERE id=?",
                (venta["cliente_id"],)
            ).fetchone()

    w = c["impresora_ancho"]
    L = []

    # Encabezado
    L += [
        _linea("="),
        _centrar(c["negocio_nombre"]),
        _centrar(c["negocio_direccion"]),
        _centrar(f"Tel: {c['negocio_telefono']}"),
        _centrar(f"CUIT: {c['negocio_cuit']}"),
        _linea("="),
        _centrar(f"TICKET #{venta_id}"),
        _centrar(datetime.now().strftime("%d/%m/%Y  %H:%M")),
    ]

    if cliente:
        L.append(_centrar(f"Cliente: {cliente['nombre']} ({cliente['dni']})"))

    L.append(_linea("-"))

    # Ítems
    for item in items:
        nombre = item["descripcion"]
        if len(nombre) > w - 10:
            nombre = nombre[:w-13] + "..."
        promo = " [P]" if item["promo_aplicada"] else ""
        L.append(f"{nombre}{promo}")
        L.append(_col2(
            f"  {_fmt_cant(item['cantidad'])} x {c['moneda_simbolo']} {item['precio_unitario']:,.2f}",
            f"{c['moneda_simbolo']} {item['subtotal']:,.2f}"
        ))

    L.append(_linea("-"))

    # Descuento
    if venta["descuento_pct"] and venta["descuento_pct"] > 0:
        subtotal_bruto = sum(i["subtotal"] for i in items)
        L.append(_col2("Subtotal:", f"{c['moneda_simbolo']} {subtotal_bruto:,.2f}"))
        L.append(_col2(
            f"Descuento ({venta['descuento_pct']:.0f}%):",
            f"- {c['moneda_simbolo']} {venta['descuento_monto']:,.2f}"
        ))
        L.append(_linea("-"))

    # Total y método
    metodo_labels = {
        "efectivo":         "Efectivo",
        "tarjeta":          "Tarjeta",
        "mixto":            "Efectivo + Tarjeta",
        "qr":               "QR / Transferencia",
        "cuenta_corriente": "Cuenta Corriente",
    }
    metodo = metodo_labels.get(venta["metodo_pago"],
                                venta["metodo_pago"].capitalize())

    L += [
        _col2("TOTAL:", f"{c['moneda_simbolo']} {venta['total']:,.2f}"),
        _col2("Pago:", metodo),
        _linea("="),
        _centrar(c["negocio_mensaje_pie"]),
        _linea("="),
        "",  # línea final para corte
    ]

    return "\n".join(L)


def generar_texto_ticket_prueba() -> str:
    """
    Arma un ticket de EJEMPLO con productos y totales inventados,
    usando exactamente el mismo formato que un ticket real (mismo
    ancho configurado, mismo encabezado con los datos del negocio,
    mismo estilo de ítem con promo, mismo pie) — para poder ver cómo
    va a salir un ticket real de verdad, sin necesidad de facturar
    nada.
    """
    c = cfg()
    w = c["impresora_ancho"]
    L = [
        _linea("="),
        _centrar(c["negocio_nombre"]),
        _centrar(c["negocio_direccion"]),
        _centrar(f"Tel: {c['negocio_telefono']}"),
        _centrar(f"CUIT: {c['negocio_cuit']}"),
        _linea("="),
        _centrar("TICKET DE EJEMPLO"),
        _centrar(datetime.now().strftime("%d/%m/%Y  %H:%M")),
        _linea("-"),
    ]

    items_ejemplo = [
        ("Coca Cola 1.5L", 2, 1900.00, False),
        ("Yerba Mate Taragui 500g", 1, 2600.00, True),
        ("Queso Cremoso x Kg", 0.350, 8200.00, False),
    ]
    for nombre, cant, precio, promo in items_ejemplo:
        if len(nombre) > w - 10:
            nombre = nombre[:w-13] + "..."
        etiqueta_promo = " [P]" if promo else ""
        subtotal = cant * precio
        L.append(f"{nombre}{etiqueta_promo}")
        L.append(_col2(
            f"  {_fmt_cant(cant)} x {c['moneda_simbolo']} {precio:,.2f}",
            f"{c['moneda_simbolo']} {subtotal:,.2f}"
        ))

    L.append(_linea("-"))
    total = sum(cant * precio for _, cant, precio, _ in items_ejemplo)
    L += [
        _col2("TOTAL:", f"{c['moneda_simbolo']} {total:,.2f}"),
        _col2("Pago:", "Efectivo"),
        _linea("="),
        _centrar(c["negocio_mensaje_pie"]),
        _linea("="),
        "",
    ]
    return "\n".join(L)


def imprimir_ticket_prueba(nombre_impresora: str = None) -> tuple[bool, str]:
    """
    Imprime el ticket de ejemplo (formato real, datos inventados).
    Mismo camino ESC/POS → Windows → archivo que un ticket real.
    """
    texto = generar_texto_ticket_prueba()
    ok, msg = _imprimir_escpos(texto, nombre_impresora=nombre_impresora)
    if ok:
        return True, msg
    if sys.platform == "win32":
        ok, msg = _imprimir_windows(texto, nombre_doc="Ticket de ejemplo",
                                    nombre_impresora=nombre_impresora)
        if ok:
            return True, msg
    return _imprimir_archivo(texto, 0)


def generar_pdf_ticket(venta_id: int) -> str | None:
    """Genera un PDF del ticket. Retorna la ruta del archivo o None."""
    texto = generar_texto_ticket(venta_id)
    if not texto:
        return None
    try:
        from reportlab.lib.pagesizes import A7
        from reportlab.pdfgen import canvas as pdf_canvas

        ruta = os.path.join(tempfile.gettempdir(), f"ticket_{venta_id}.pdf")
        c = pdf_canvas.Canvas(ruta, pagesize=A7)
        c.setFont("Courier", 8)
        y = A7[1] - 10
        for linea in texto.split("\n"):
            c.drawString(5, y, linea)
            y -= 10
            if y < 10:
                break
        c.save()
        return ruta
    except ImportError:
        # Fallback a .txt si no hay reportlab
        ruta = os.path.join(tempfile.gettempdir(), f"ticket_{venta_id}.txt")
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(texto)
        return ruta
    except Exception as e:
        logging.error(f"Error generando PDF: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# IMPRESIÓN
# ─────────────────────────────────────────────────────────────────────────────

def imprimir_ticket(venta_id: int) -> tuple[bool, str]:
    """
    Imprime el ticket. Intenta ESC/POS → Windows → archivo.
    Retorna (exito, mensaje). Nunca bloquea la venta.
    """
    if not cfg()["impresora_activa"]:
        return True, "Impresora desactivada en configuracion."

    texto = generar_texto_ticket(venta_id)
    if not texto:
        return False, f"Venta #{venta_id} no encontrada."

    # Intento 1: ESC/POS (python-escpos)
    ok, msg = _imprimir_escpos(texto)
    if ok:
        return True, msg

    # Intento 2: Windows (win32print)
    if sys.platform == "win32":
        ok, msg = _imprimir_windows(texto, nombre_doc=f"Ticket #{venta_id}")
        if ok:
            return True, msg

    # Fallback: abrir archivo
    return _imprimir_archivo(texto, venta_id)


def _revisar_ultimo_trabajo(nombre_impresora: str, intentos: int = 8,
                            espera: float = 0.4) -> str | None:
    """
    Después de mandar un trabajo, Windows lo acepta al toque — pero
    eso NO garantiza que se haya impreso de verdad, puede quedar con
    error en la cola un instante después (impresora apagada, sin
    papel, atascada, etc.). Sin esto, el sistema decía "OK" con una
    impresora que ni estaba prendida.
    Espera un ratito reintentando y revisa el estado real del último
    trabajo en la cola de esa impresora. Devuelve una descripción del
    problema si encuentra uno, o None si no vio ningún error en el
    tiempo que esperó — OJO: no es garantía absoluta, si el error
    tarda más en aparecer que lo que esperamos acá, no lo vamos a
    pescar; y si hay otro trabajo de otra fuente metiéndose en el
    medio en esa misma impresora, podría revisar el que no es.
    """
    import time
    try:
        import win32print
    except ImportError:
        return None

    BANDERAS = {
        0x00000002: "error",
        0x00000020: "impresora fuera de línea",
        0x00000040: "sin papel",
        0x00000400: "necesita intervención (revisar la impresora)",
    }
    try:
        hp = win32print.OpenPrinter(nombre_impresora)
    except Exception:
        return None

    try:
        for _ in range(intentos):
            time.sleep(espera)
            try:
                trabajos = win32print.EnumJobs(hp, 0, 999, 1)
            except Exception:
                return None
            if not trabajos:
                continue
            ultimo = trabajos[-1]
            status = ultimo.get("Status", 0)
            problemas = [t for b, t in BANDERAS.items() if status & b]
            if problemas:
                return ", ".join(problemas)
            # PRINTED (0x80) o COMPLETE (0x1000) = terminó bien
            if status & 0x00000080 or status & 0x00001000:
                return None
        return None
    finally:
        win32print.ClosePrinter(hp)


def _imprimir_escpos(texto: str, nombre_impresora: str = None) -> tuple[bool, str]:
    try:
        from escpos.printer import Win32Raw
        nombre = nombre_impresora if nombre_impresora is not None else (cfg()["impresora_nombre"] or None)
        try:
            p = Win32Raw(nombre) if nombre else Win32Raw()
            p.text(texto)
            p.cut()
            nombre_real = nombre or "(predeterminada de Windows)"
            if nombre:
                problema = _revisar_ultimo_trabajo(nombre)
                if problema:
                    return False, (f"Se mandó a '{nombre_real}' pero quedó con "
                                   f"error en la cola de Windows: {problema}")
            return True, f"Impreso via ESC/POS en: {nombre_real}"
        except Exception as e:
            return False, f"ESC/POS error (impresora: {nombre or '(predeterminada)'}): {e}"
    except ImportError:
        return False, "python-escpos no instalado."


def _imprimir_windows(texto: str, nombre_doc: str = "Ticket TPV",
                      nombre_impresora: str = None) -> tuple[bool, str]:
    try:
        import win32print
        if nombre_impresora is not None:
            nombre = nombre_impresora or win32print.GetDefaultPrinter()
        else:
            nombre = cfg()["impresora_nombre"] or win32print.GetDefaultPrinter()
        hp = win32print.OpenPrinter(nombre)
        try:
            win32print.StartDocPrinter(hp, 1, (nombre_doc, None, "RAW"))
            win32print.StartPagePrinter(hp)
            # Este camino (sin python-escpos) manda el texto tal cual,
            # sin ningún comando de control — por eso no cortaba el
            # papel. Se le agrega el corte ESC/POS estándar (GS V 0),
            # con unos renglones de margen antes para que no corte
            # justo encima de la última línea impresa.
            datos = texto.encode("cp1252", errors="replace")
            datos += b"\n\n\n" + b"\x1d\x56\x00"
            win32print.WritePrinter(hp, datos)
            win32print.EndPagePrinter(hp)
            win32print.EndDocPrinter(hp)
        finally:
            win32print.ClosePrinter(hp)

        problema = _revisar_ultimo_trabajo(nombre)
        if problema:
            return False, f"Se mandó a '{nombre}' pero quedó con error en la cola de Windows: {problema}"
        return True, f"Impreso en: {nombre}"
    except ImportError:

        return False, "pywin32 no instalado."
    except Exception as e:
        return False, f"Error Windows: {e}"


def _imprimir_archivo(texto: str, venta_id: int) -> tuple[bool, str]:
    try:
        ruta = os.path.join(tempfile.gettempdir(), f"ticket_{venta_id}.txt")
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(texto)
        if sys.platform == "win32":
            os.startfile(ruta)
        return True, f"Ticket guardado: {ruta}"
    except Exception as e:
        return False, f"Error guardando ticket: {e}"


# ─────────────────────────────────────────────────────────────────────────────
# ENVÍO
# ─────────────────────────────────────────────────────────────────────────────

def abrir_whatsapp(telefono: str, texto: str) -> tuple[bool, str]:
    """
    Abre WhatsApp Web con el texto dado ya escrito, listo para mandar.
    No requiere API ni pago — usa el link wa.me. Como no hay forma de
    mandarlo sin que alguien apriete "Enviar" en el navegador, sirve
    para acciones puntuales (un cliente por vez), no para envíos
    automáticos desatendidos.
    """
    import urllib.parse, webbrowser
    if not telefono or not telefono.strip():
        return False, "El cliente no tiene teléfono cargado."

    # Limpiar teléfono (solo dígitos, agregar código de país si falta)
    tel = "".join(c for c in telefono if c.isdigit())
    if not tel:
        return False, "Teléfono inválido."
    if not tel.startswith("54"):
        tel = "54" + tel  # Argentina por defecto

    msg = urllib.parse.quote(texto)
    url = f"https://wa.me/{tel}?text={msg}"
    webbrowser.open(url)
    return True, "WhatsApp abierto en el navegador."


def enviar_whatsapp(venta_id: int, telefono: str) -> tuple[bool, str]:
    """Abre WhatsApp Web con el ticket como mensaje."""
    texto = generar_texto_ticket(venta_id)
    if not texto:
        return False, "Venta no encontrada."
    return abrir_whatsapp(telefono, texto)


def enviar_email(venta_id: int, destinatario: str) -> tuple[bool, str]:
    """Envía el ticket por email via SMTP."""
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    c = cfg()
    if not c["email_activo"]:
        return False, "Email no configurado."

    texto = generar_texto_ticket(venta_id)
    if not texto:
        return False, "Venta no encontrada."

    try:
        msg = MIMEMultipart()
        msg["From"]    = f"{c['email_remitente']} <{c['email_usuario']}>"
        msg["To"]      = destinatario
        msg["Subject"] = f"Ticket #{venta_id} - {c['negocio_nombre']}"
        msg.attach(MIMEText(texto, "plain", "utf-8"))

        with smtplib.SMTP(c["email_smtp_host"], c["email_smtp_port"]) as s:
            s.starttls()
            s.login(c["email_usuario"], c["email_password"])
            s.send_message(msg)

        return True, f"Email enviado a {destinatario}"
    except Exception as e:
        logging.error(f"Error enviando email: {e}")
        return False, f"Error de email: {e}"


# ─────────────────────────────────────────────────────────────────────────────
# INFORME DE STOCK POR EMAIL (para verlo desde el celular)
# ─────────────────────────────────────────────────────────────────────────────

def generar_html_informe_stock(productos: list, umbral: int) -> str:
    """Arma el cuerpo HTML del informe de stock, ordenado de menor a
    mayor cantidad (los más urgentes primero), con los críticos
    resaltados en rojo — pensado para leerse cómodo desde el celular."""
    filas = []
    for p in productos:
        stock_txt = _fmt_cant(p["stock"])
        color = "#c0392b" if p["critico"] else "#222"
        peso = " kg" if p.get("vendido_por_peso") else " u."
        filas.append(
            f'<tr style="border-bottom:1px solid #eee">'
            f'<td style="padding:6px 8px;color:{color};font-weight:'
            f'{"bold" if p["critico"] else "normal"}">{p["descripcion"]}</td>'
            f'<td style="padding:6px 8px;color:#888;font-size:13px">{p["categoria"] or "—"}</td>'
            f'<td style="padding:6px 8px;text-align:right;color:{color};'
            f'font-weight:{"bold" if p["critico"] else "normal"}">{stock_txt}{peso}</td>'
            f'</tr>'
        )
    cant_criticos = sum(1 for p in productos if p["critico"])
    return f"""
    <html><body style="font-family:Arial,sans-serif;font-size:14px;color:#222">
        <h2 style="margin-bottom:4px">Informe de stock</h2>
        <p style="color:#666;margin-top:0">
            {datetime.now().strftime('%d/%m/%Y %H:%M')} —
            {len(productos)} producto(s), {cant_criticos} por debajo de {umbral} u.
            (marcados en rojo)
        </p>
        <table style="border-collapse:collapse;width:100%;max-width:500px">
            <tr style="background:#f5f5f5;text-align:left">
                <th style="padding:6px 8px">Producto</th>
                <th style="padding:6px 8px">Categoría</th>
                <th style="padding:6px 8px;text-align:right">Stock</th>
            </tr>
            {''.join(filas)}
        </table>
    </body></html>
    """


def enviar_alerta_vencimientos(destinatario: str = None,
                               solo_una_vez_por_dia: bool = True) -> tuple[bool, str]:
    """Manda el listado de lo que esta por vencer.

    Pensado para dispararse al abrir el TPV. El guard de una vez por dia
    existe porque el sistema se abre y se cierra varias veces en la jornada
    y un mail repetido cada vez deja de leerse a la semana.
    """
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    from datetime import date
    from repositorio import get_vencimientos_proximos

    c = cfg()
    if not c.get("vto_email_activo"):
        return False, "Aviso de vencimientos desactivado (Config)."
    if not c.get("email_activo"):
        return False, "Email no configurado en Config → Email (SMTP)."

    destinatario = destinatario or c.get("vto_email_destinatario") \
        or c.get("informe_stock_email_destinatario")
    if not destinatario:
        return False, "Falta el email destinatario (Config → Vencimientos)."

    hoy = date.today().isoformat()
    if solo_una_vez_por_dia and c.get("_vto_email_ultimo_envio") == hoy:
        return False, "El aviso de vencimientos de hoy ya se mando."

    productos = get_vencimientos_proximos()
    if not productos:
        if solo_una_vez_por_dia:
            from config import set as cfg_set
            cfg_set("_vto_email_ultimo_envio", hoy)
        return False, "No hay productos por vencer: no se manda nada."

    vencidos = [p for p in productos if p["dias_restantes"] < 0]
    urgentes = [p for p in productos if 0 <= p["dias_restantes"] <= 2]
    total = sum(p["valor_en_riesgo"] for p in productos)

    filas = []
    for p in productos:
        d = p["dias_restantes"]
        if d < 0:
            cuando, color = f"VENCIDO hace {-d} d", "#DC2626"
        elif d == 0:
            cuando, color = "vence HOY", "#DC2626"
        elif d <= 2:
            cuando, color = f"en {d} d", "#EA580C"
        else:
            cuando, color = f"en {d} d", "#111827"
        filas.append(
            f"<tr><td>{p['descripcion']}</td>"
            f"<td align='right'>{p['stock']:g}</td>"
            f"<td align='right'>$ {p['valor_en_riesgo']:,.2f}</td>"
            f"<td>{p['fecha_vencimiento']}</td>"
            f"<td style='color:{color};font-weight:bold'>{cuando}</td></tr>")

    resumen = f"{len(productos)} producto(s) por vencer"
    if vencidos:
        resumen = f"{len(vencidos)} VENCIDO(S) · " + resumen
    elif urgentes:
        resumen = f"{len(urgentes)} urgente(s) · " + resumen

    html = f"""<html><body style="font-family:Segoe UI,Arial,sans-serif">
      <h2>Vencimientos — {c.get('negocio_nombre', 'TPV')}</h2>
      <p>{resumen}. Valor en riesgo: <b>$ {total:,.2f}</b></p>
      <table border="0" cellpadding="6" cellspacing="0"
             style="border-collapse:collapse;font-size:14px">
        <tr style="background:#DBEAFE">
          <th align="left">Producto</th><th align="right">Stock</th>
          <th align="right">Valor</th><th align="left">Vence</th>
          <th align="left">Cuando</th></tr>
        {''.join(filas)}
      </table>
      <p style="color:#6B7280;font-size:12px">
        Cada producto usa sus propios dias de aviso si los tiene cargados;
        si no, el general de Config.</p>
    </body></html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[{c.get('negocio_nombre', 'TPV')}] {resumen}"
    msg["From"] = f"{c.get('email_remitente', 'TPV')} <{c['email_usuario']}>"
    msg["To"] = destinatario
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        with smtplib.SMTP(c["email_smtp_host"], c["email_smtp_port"], timeout=20) as srv:
            srv.starttls()
            srv.login(c["email_usuario"], c["email_password"])
            srv.send_message(msg)
    except Exception as e:
        return False, f"No se pudo enviar el aviso de vencimientos: {e}"

    if solo_una_vez_por_dia:
        from config import set as cfg_set
        cfg_set("_vto_email_ultimo_envio", hoy)
    return True, f"Aviso de vencimientos enviado a {destinatario} ({resumen})."


def enviar_informe_stock(destinatario: str = None) -> tuple[bool, str]:
    """
    Genera y envía por email el informe de stock (menor a mayor
    cantidad). Usa la config informe_stock_email_* — pensado tanto
    para el botón manual en Informes como para el script automático
    programado con el Task Scheduler de Windows.
    """
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    from repositorio import get_informe_stock

    c = cfg()
    if not c["email_activo"]:
        return False, "Email no configurado en Config → Email (SMTP)."

    destinatario = destinatario or c.get("informe_stock_email_destinatario")
    if not destinatario:
        return False, "Falta el email destinatario (Config → Informe de stock)."

    umbral = c.get("stock_alerta_umbral", 5)
    solo_criticos = c.get("informe_stock_email_solo_criticos", False)
    productos = get_informe_stock(solo_criticos=solo_criticos, umbral=umbral)

    if not productos:
        return False, "No hay productos para incluir en el informe."

    try:
        msg = MIMEMultipart("alternative")
        msg["From"]    = f"{c['email_remitente']} <{c['email_usuario']}>"
        msg["To"]      = destinatario
        msg["Subject"] = f"Informe de stock — {c['negocio_nombre']} — {datetime.now().strftime('%d/%m')}"
        msg.attach(MIMEText(
            generar_html_informe_stock(productos, umbral), "html", "utf-8"))

        with smtplib.SMTP(c["email_smtp_host"], c["email_smtp_port"]) as s:
            s.starttls()
            s.login(c["email_usuario"], c["email_password"])
            s.send_message(msg)

        logging.info(f"Informe de stock enviado a {destinatario} "
                     f"({len(productos)} productos)")
        return True, f"Informe enviado a {destinatario}"
    except Exception as e:
        logging.error(f"Error enviando informe de stock: {e}")
        return False, f"Error de email: {e}"


# ─────────────────────────────────────────────────────────────────────────────
# PREVIEW EN PANTALLA
# ─────────────────────────────────────────────────────────────────────────────

def previsualizar_ticket(parent, venta_id: int):
    """Ventana de preview con opciones de envío."""
    import tkinter as tk
    from styles import C, btn

    texto = generar_texto_ticket(venta_id)
    if not texto:
        import tkinter.messagebox as mb
        mb.showwarning("Error", f"Venta #{venta_id} no encontrada.", parent=parent)
        return

    d = tk.Toplevel(parent)
    d.title(f"Ticket #{venta_id}")
    d.configure(bg=C.superficie)
    d.resizable(True, True)
    sw, sh = d.winfo_screenwidth(), d.winfo_screenheight()
    w, h = 440, 580
    d.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

    # Ticket
    frame_txt = tk.Frame(d, bg="#F5F5F5", padx=12, pady=12)
    frame_txt.pack(fill="both", expand=True, padx=12, pady=(12, 6))

    txt = tk.Text(frame_txt, font=("Courier New", 8),
                  width=cfg()["impresora_ancho"] + 2,
                  bg="#FFFFFF", fg="#000000",
                  relief="solid", bd=1, state="normal")
    txt.insert("1.0", texto)
    txt.config(state="disabled")
    txt.pack(fill="both", expand=True)

    # Botones de acción
    fb = tk.Frame(d, bg=C.superficie)
    fb.pack(fill="x", padx=12, pady=(0, 8))

    btn(fb, "Imprimir", variante="exito",
        comando=lambda: _accion_imprimir(venta_id, d)).pack(side="left", padx=(0,4))

    # WhatsApp
    def _enviar_wa():
        tel_d = _pedir_telefono(d, "WhatsApp")
        if tel_d:
            ok, msg = enviar_whatsapp(venta_id, tel_d)
            _mostrar_resultado(d, ok, msg)

    btn(fb, "WhatsApp", variante="primario",
        comando=_enviar_wa).pack(side="left", padx=4)

    # Email
    def _enviar_mail():
        mail_d = _pedir_dato(d, "Email", "Dirección de email:")
        if mail_d:
            ok, msg = enviar_email(venta_id, mail_d)
            _mostrar_resultado(d, ok, msg)

    btn(fb, "Email", variante="primario",
        comando=_enviar_mail).pack(side="left", padx=4)

    btn(fb, "Cerrar", variante="neutro",
        comando=d.destroy).pack(side="right")


def _accion_imprimir(venta_id, parent):
    ok, msg = imprimir_ticket(venta_id)
    _mostrar_resultado(parent, ok, msg)


def _mostrar_resultado(parent, ok, msg):
    import tkinter.messagebox as mb
    if ok:
        mb.showinfo("OK", msg, parent=parent)
    else:
        mb.showwarning("Error", msg, parent=parent)


def _pedir_telefono(parent, titulo):
    return _pedir_dato(parent, titulo, "Telefono (sin 0 ni 15):")


def _pedir_dato(parent, titulo, label):
    import tkinter as tk
    from styles import C, F, btn
    d = tk.Toplevel(parent)
    d.title(titulo)
    d.resizable(False, False)
    d.configure(bg=C.superficie)
    d.grab_set()
    sw, sh = d.winfo_screenwidth(), d.winfo_screenheight()
    d.geometry(f"300x140+{(sw-300)//2}+{(sh-140)//2}")

    tk.Label(d, text=label, font=F.normal, bg=C.superficie).pack(pady=(16,4), padx=20)
    e = tk.Entry(d, font=F.normal, bg=C.superficie, fg=C.texto,
                  relief="solid", bd=1)
    e.pack(fill="x", padx=20, ipady=6)
    e.focus_set()

    result = [None]
    def ok(event=None):
        result[0] = e.get().strip()
        d.destroy()
    e.bind("<Return>", ok)
    btn(d, "OK", variante="primario", comando=ok).pack(pady=12)
    parent.wait_window(d)
    return result[0] if result[0] else None


if __name__ == "__main__":
    with get_connection() as conn:
        ultima = conn.execute(
            "SELECT id FROM ventas ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if ultima:
        print(generar_texto_ticket(ultima["id"]))
    else:
        print("Sin ventas registradas.")

"""
estado_cuenta.py — Detalle de lo que debe un cliente en cuenta corriente,
ticket por ticket y con el detalle de cada compra.

Todo sale de repositorio.get_tickets_adeudados() (ahi esta la logica de que
ticket debe cuanto); este modulo solo lo presenta:
  - generar_texto_estado_cuenta(): texto para WhatsApp / mail
  - generar_pdf_estado_cuenta():   PDF A4 para imprimir o mandar

Sin tkinter: se puede usar desde scripts o tests.
"""

import logging
import os
import re
import tempfile
from datetime import datetime

from repositorio import get_tickets_adeudados


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

NOTA_PAGOS = ("Los pagos realizados se aplican primero a los tickets más "
              "antiguos.")

def _m(v) -> str:
    return f"$ {float(v or 0):,.2f}"


def _cant(v) -> str:
    return f"{float(v or 0):g}"


def _dia(fecha) -> str:
    try:
        return datetime.strptime((fecha or "")[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return "—"


def _titulo_ticket(t) -> str:
    if t["tipo"] == "ticket":
        return f"Ticket #{t['venta_id']} — {_dia(t['fecha'])}"
    return f"{t['concepto'] or 'Deuda'} — {_dia(t['fecha'])}"


def _lineas_resumen(t) -> list[tuple[str, float]]:
    """Las cuentas de un ticket, solo las que corresponden: (rotulo, importe)."""
    out = []
    pagado_acto = 0.0
    if t["total_ticket"] is not None and t["total_ticket"] - t["fiado"] > 0.005:
        pagado_acto = t["total_ticket"] - t["fiado"]
        out.append(("Total del ticket", t["total_ticket"]))
        out.append(("Pagado en el momento", -pagado_acto))
    if t["ajustes"] < -0.005:
        out.append(("Devoluciones / ajustes", t["ajustes"]))
    if t["pagos"] > 0.005:
        out.append(("Pagos aplicados", -t["pagos"]))
    return out


def _item_texto(it) -> str:
    s = f"{_cant(it['cantidad'])} x {it['descripcion']}"
    if it.get("devuelto"):
        s += f" (devolvió {_cant(it['devuelto'])})"
    return s


def _negocio() -> dict:
    try:
        from config import cfg
        c = cfg()
        return {"nombre": c.get("negocio_nombre") or "",
                "direccion": c.get("negocio_direccion") or "",
                "telefono": c.get("negocio_telefono") or ""}
    except Exception:
        return {"nombre": "", "direccion": "", "telefono": ""}


# ─────────────────────────────────────────────────────────────────────────────
# Texto (WhatsApp / mail)
# ─────────────────────────────────────────────────────────────────────────────

def generar_texto_estado_cuenta(cliente_id: int, con_detalle: bool = True) -> str | None:
    """Texto listo para pegar en WhatsApp. None si el cliente no existe."""
    d = get_tickets_adeudados(cliente_id)
    cli = d["cliente"]
    if not cli:
        return None
    neg = _negocio()
    L = []
    if neg["nombre"]:
        L.append(f"*{neg['nombre']}*")
    L.append(f"Detalle de cuenta corriente de {cli['nombre']}")
    L.append(f"Al {datetime.now().strftime('%d/%m/%Y')}")
    L.append("")

    if not d["tickets"]:
        L.append("No tenés compras pendientes de pago.")
        if d["saldo_a_favor"] > 0.005:
            L.append(f"Tenés un saldo a favor de {_m(d['saldo_a_favor'])}.")
        return "\n".join(L)

    for t in d["tickets"]:
        L.append(f"*{_titulo_ticket(t)}*")
        if con_detalle:
            for it in t["items"]:
                L.append(f"  {_item_texto(it)}  {_m(it['subtotal'])}")
        for rotulo, imp in _lineas_resumen(t):
            L.append(f"  {rotulo}: {'-' if imp < 0 else ''}{_m(abs(imp))}")
        L.append(f"  *Debe: {_m(t['pendiente'])}*")
        L.append("")

    if d["saldo_a_favor"] > 0.005:
        L.append(f"Saldo a favor: {_m(d['saldo_a_favor'])}")
    L.append(f"*TOTAL ADEUDADO: {_m(d['total_pendiente'] - d['saldo_a_favor'])}*")
    if any(t["pagos"] > 0.005 for t in d["tickets"]):
        L.append("")
        L.append(f"_{NOTA_PAGOS}_")
    return "\n".join(L)


# ─────────────────────────────────────────────────────────────────────────────
# PDF
# ─────────────────────────────────────────────────────────────────────────────

def _nombre_archivo(nombre: str) -> str:
    import unicodedata
    sin_tildes = unicodedata.normalize("NFKD", nombre or "").encode("ascii", "ignore").decode()
    base = re.sub(r"[^A-Za-z0-9]+", "_", sin_tildes).strip("_") or "cliente"
    return f"cuenta_corriente_{base}_{datetime.now().strftime('%Y%m%d')}.pdf"


def generar_pdf_estado_cuenta(cliente_id: int, ruta_salida: str = None) -> str | None:
    """PDF A4 con un bloque por ticket. Retorna la ruta, o None si falla."""
    d = get_tickets_adeudados(cliente_id)
    cli = d["cliente"]
    if not cli:
        return None
    try:
        from xml.sax.saxutils import escape
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                        Table, TableStyle, KeepTogether)

        ruta = ruta_salida or os.path.join(tempfile.gettempdir(),
                                           _nombre_archivo(cli["nombre"]))
        neg = _negocio()
        ss = getSampleStyleSheet()
        h1 = ParagraphStyle("h1", parent=ss["Title"], fontSize=16, alignment=0,
                            spaceAfter=2)
        norm = ParagraphStyle("n", parent=ss["Normal"], fontSize=9, leading=11)
        chico = ParagraphStyle("c", parent=norm, fontSize=8,
                               textColor=colors.HexColor("#555555"))
        chico_d = ParagraphStyle("cd", parent=chico, alignment=2)
        gris = colors.HexColor("#E5E7EB")
        rojo = colors.HexColor("#B91C1C")

        doc = SimpleDocTemplate(ruta, pagesize=A4, leftMargin=15 * mm,
                                rightMargin=15 * mm, topMargin=14 * mm,
                                bottomMargin=14 * mm,
                                title=f"Cuenta corriente — {cli['nombre']}")
        W = A4[0] - 30 * mm
        E = []
        E.append(Paragraph(escape(neg["nombre"] or "Cuenta corriente"), h1))
        sub = " · ".join(x for x in (neg["direccion"], neg["telefono"]) if x)
        if sub:
            E.append(Paragraph(escape(sub), chico))
        E.append(Spacer(1, 6))
        E.append(Paragraph(
            f"<b>Detalle de cuenta corriente — {escape(cli['nombre'])}</b>", norm))
        E.append(Paragraph(f"Al {datetime.now().strftime('%d/%m/%Y')}", chico))
        E.append(Spacer(1, 8))

        if not d["tickets"]:
            E.append(Paragraph("No hay compras pendientes de pago.", norm))

        for t in d["tickets"]:
            filas = [[Paragraph(f"<b>{escape(_titulo_ticket(t))}</b>", norm), "", "", ""]]
            filas.append([Paragraph("<b>Producto</b>", chico), Paragraph("<b>Cant.</b>", chico_d),
                          Paragraph("<b>Precio u.</b>", chico_d), Paragraph("<b>Subtotal</b>", chico_d)])
            for it in t["items"]:
                desc = escape(it["descripcion"] or "")
                if it.get("devuelto"):
                    desc += f" <i>(devolvió {_cant(it['devuelto'])})</i>"
                filas.append([Paragraph(desc, norm), _cant(it["cantidad"]),
                              _m(it["precio_unitario"]), _m(it["subtotal"])])
            if not t["items"]:
                filas.append([Paragraph(escape(t["concepto"] or "Deuda cargada a mano"),
                                        norm), "", "", _m(t["fiado"])])
            estilo = [
                ("SPAN", (0, 0), (-1, 0)),
                ("BACKGROUND", (0, 0), (-1, 0), gris),
                ("LINEBELOW", (0, 1), (-1, 1), 0.4, colors.grey),
                ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
            for rotulo, imp in _lineas_resumen(t):
                filas.append([Paragraph(rotulo, chico), "", "",
                              ("-" if imp < 0 else "") + _m(abs(imp))])
                estilo.append(("SPAN", (0, len(filas) - 1), (2, len(filas) - 1)))
                estilo.append(("ALIGN", (0, len(filas) - 1), (0, len(filas) - 1), "RIGHT"))
            filas.append([Paragraph("<b>Debe de este ticket</b>", norm), "", "",
                          Paragraph(f"<b>{_m(t['pendiente'])}</b>", norm)])
            u = len(filas) - 1
            estilo += [("SPAN", (0, u), (2, u)), ("ALIGN", (0, u), (0, u), "RIGHT"),
                       ("LINEABOVE", (0, u), (-1, u), 0.6, colors.black),
                       ("TEXTCOLOR", (3, u), (3, u), rojo)]
            tabla = Table(filas, colWidths=[W * 0.52, W * 0.12, W * 0.18, W * 0.18],
                          repeatRows=0)
            tabla.setStyle(TableStyle(estilo))
            E.append(KeepTogether([tabla, Spacer(1, 8)]))

        total = d["total_pendiente"] - d["saldo_a_favor"]
        E.append(Spacer(1, 4))
        pie = []
        if d["saldo_a_favor"] > 0.005:
            pie.append(["Saldo a favor", _m(d["saldo_a_favor"])])
        pie.append([Paragraph("<b>TOTAL ADEUDADO</b>", ParagraphStyle(
            "t", parent=norm, fontSize=12)), Paragraph(
            f"<b>{_m(total)}</b>", ParagraphStyle(
                "tt", parent=norm, fontSize=12, alignment=2, textColor=rojo))])
        tp = Table(pie, colWidths=[W * 0.7, W * 0.3])
        tp.setStyle(TableStyle([("LINEABOVE", (0, -1), (-1, -1), 1, colors.black),
                                ("ALIGN", (1, 0), (1, -1), "RIGHT")]))
        E.append(tp)
        if any(t["pagos"] > 0.005 for t in d["tickets"]):
            E.append(Spacer(1, 6))
            E.append(Paragraph(NOTA_PAGOS, chico))
        doc.build(E)
        return ruta
    except Exception as e:
        logging.error(f"Error generando PDF de cuenta corriente: {e}")
        return None

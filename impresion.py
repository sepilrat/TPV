from datetime import datetime
def listar_impresoras():

    try:
        import win32print

        impresoras = []

        for p in win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL):
            impresoras.append(p[2])

        # agregar impresora por defecto primero
        default = win32print.GetDefaultPrinter()

        if default in impresoras:
            impresoras.remove(default)
            impresoras.insert(0, default)

        return impresoras

    except:
        # fallback si no está win32print
        return ["Impresora por defecto"]
# =========================
# CONFIG
# =========================

CONFIG = {
    "ancho": 32,  # 32 o 42 según impresora
    "empresa": "AUTOSERVICIO JUAN",
    "direccion": "Tu dirección",
    "cuit": "CUIT: 20-00000000-0",
    "tipo": "termica",  # "termica" o "normal"
    "corte": True,
    "cajon": False  # abrir cajón
}

# =========================
# INTENTO ESC/POS
# =========================

try:
    from escpos.printer import Usb, Network, Serial, Win32Raw
    ESCPOS = True
except:
    ESCPOS = False


# =========================
# FORMATO
# =========================

def centrar(texto, ancho):
    return texto.center(ancho)


def linea(ancho):
    return "-" * ancho


def item_line(desc, cant, total, ancho):
    desc = desc[:20]

    izq = f"{desc} x{cant}"
    der = f"${int(total)}"

    espacios = ancho - len(izq) - len(der)
    if espacios < 1:
        espacios = 1

    return izq + (" " * espacios) + der


def generar_texto(items, total):

    ancho = CONFIG["ancho"]
    l = []

    l.append(centrar(CONFIG["empresa"], ancho))
    l.append(centrar(CONFIG["direccion"], ancho))
    l.append(centrar(CONFIG["cuit"], ancho))
    l.append(centrar(datetime.now().strftime("%d/%m/%Y %H:%M"), ancho))
    l.append(linea(ancho))

    for item in items:
        desc, cant, precio, total_item, _ = item
        l.append(item_line(desc, cant, total_item, ancho))

    l.append(linea(ancho))
    l.append(centrar(f"TOTAL: ${int(total)}", ancho))
    l.append("")
    l.append(centrar("Gracias por su compra", ancho))
    l.append("\n\n")

    return "\n".join(l)


# =========================
# ESC/POS DIRECTO
# =========================

def imprimir_termica(items, total, printer_name=None):

    texto = generar_texto(items, total)

    try:

        # 🟢 Windows RAW (recomendado)
        if printer_name:
            p = Win32Raw(printer_name)
        else:
            p = Win32Raw()

        p.set(align="center", bold=True, width=2, height=2)
        p.text(CONFIG["empresa"] + "\n")

        p.set(align="center", bold=False, width=1, height=1)
        p.text(CONFIG["direccion"] + "\n")
        p.text(CONFIG["cuit"] + "\n")
        p.text(datetime.now().strftime("%d/%m/%Y %H:%M") + "\n")

        p.text(linea(CONFIG["ancho"]) + "\n")

        p.set(align="left")

        for item in items:
            desc, cant, precio, total_item, _ = item
            p.text(item_line(desc, cant, total_item, CONFIG["ancho"]) + "\n")

        p.text(linea(CONFIG["ancho"]) + "\n")

        p.set(align="center", width=2, height=2)
        p.text(f"TOTAL: ${int(total)}\n")

        p.set(align="center", width=1, height=1)
        p.text("\nGracias por su compra\n\n")

        # abrir cajón
        if CONFIG["cajon"]:
            p.cashdraw(2)

        # cortar papel
        if CONFIG["corte"]:
            p.cut()

        p.close()

    except Exception as e:
        print("Error ESC/POS:", e)
        print(texto)


# =========================
# FALLBACK WINDOWS
# =========================

def imprimir_windows(items, total):

    texto = generar_texto(items, total)

    archivo = "ticket.txt"

    with open(archivo, "w", encoding="utf-8") as f:
        f.write(texto)

    import os
    os.startfile(archivo, "print")


# =========================
# MAIN
# =========================

def imprimir_ticket(items, total, impresora=None):

    if CONFIG["tipo"] == "termica" and ESCPOS:
        imprimir_termica(items, total, impresora)
    else:
        imprimir_windows(items, total)
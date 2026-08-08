"""
diagnostico_email.py — Por que no llega el mail.

Correlo en la carpeta del TPV:

    .venv\\Scripts\\python.exe diagnostico_email.py

Revisa la cadena entera y se detiene en el primer eslabon roto, diciendo
que hay que tocar. Con --enviar manda ademas los mails de prueba.
"""

import os
import sys
import socket
import smtplib
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

OK, MAL, AVISO = "[OK]   ", "[FALLA]", "[AVISO]"


def _t(titulo):
    print(f"\n{'─' * 66}\n{titulo}\n{'─' * 66}")


def revisar():
    from config import cfg, CONFIG_PATH
    c = cfg()
    problemas = []

    _t("1. Configuracion de email (Config → Email SMTP)")
    print(f"   archivo: {CONFIG_PATH}")

    if not c.get("email_activo"):
        print(f"{MAL} 'Email activo' esta DESTILDADO.")
        print("        → Config → Email (SMTP) → tildar 'Email activo'.")
        print("        Sin esto no sale NINGUN mail: ni stock ni vencimientos.")
        problemas.append("email_activo")
    else:
        print(f"{OK} Email activo")

    for clave, etiqueta in (("email_smtp_host", "Servidor SMTP"),
                            ("email_smtp_port", "Puerto"),
                            ("email_usuario", "Usuario"),
                            ("email_password", "Contrasena")):
        val = c.get(clave)
        if not val:
            print(f"{MAL} Falta {etiqueta} ({clave})")
            problemas.append(clave)
        elif clave == "email_password":
            print(f"{OK} {etiqueta}: {'*' * min(len(str(val)), 16)} "
                  f"({len(str(val))} caracteres)")
        else:
            print(f"{OK} {etiqueta}: {val}")

    # Gmail: la contrasena normal no sirve desde 2022

    passwd = str(c.get("email_password") or "")
    if "gmail" in str(c.get("email_smtp_host", "")).lower() and passwd:
        limpia = passwd.replace(" ", "")
        if len(limpia) != 16:
            print(f"{AVISO} Gmail NO acepta tu contrasena normal desde 2022.")
            print("        Necesitas una 'Contrasena de aplicacion' de 16 letras:")
            print("        myaccount.google.com → Seguridad → Verificacion en 2 pasos")
            print("        → Contrasenas de aplicaciones. Se pega SIN espacios.")
            problemas.append("gmail_app_password")
        else:
            print(f"{OK} La contrasena tiene formato de clave de aplicacion (16)")

    _t("2. Destinatarios")
    dest_vto = c.get("vto_email_destinatario") or c.get("informe_stock_email_destinatario")
    dest_stock = c.get("informe_stock_email_destinatario")
    for etiqueta, valor, clave in (
            ("Vencimientos", dest_vto, "vto_email_destinatario"),
            ("Informe de stock", dest_stock, "informe_stock_email_destinatario")):
        if valor:
            print(f"{OK} {etiqueta}: {valor}")
        else:
            print(f"{MAL} {etiqueta}: SIN DESTINATARIO ({clave})")
            problemas.append(clave)

    _t("3. Interruptores de cada aviso")
    if c.get("vto_email_activo"):
        print(f"{OK} Vencimientos por email: ACTIVO")
    else:
        print(f"{MAL} Vencimientos por email: DESACTIVADO")
        print("        → Config → Vencimientos → 'Avisar por email al abrir el TPV'")
        problemas.append("vto_email_activo")

    if c.get("informe_stock_email_activo"):
        print(f"{OK} Informe de stock por email: ACTIVO")
    else:
        print(f"{MAL} Informe de stock por email: DESACTIVADO")
        print("        → Config → Informe de stock por email")
        problemas.append("informe_stock_email_activo")

    ultimo = c.get("_vto_email_ultimo_envio")
    if ultimo == date.today().isoformat():
        print(f"{AVISO} El aviso de vencimientos de HOY ya se marco como enviado.")
        print("        Por eso no vuelve a salir aunque reabras el TPV.")
        print("        Para probar de nuevo: correr este script con --enviar")

    _t("4. Hay algo para avisar?")
    try:
        from repositorio import get_vencimientos_proximos, get_informe_stock
        vtos = get_vencimientos_proximos()
        if vtos:
            print(f"{OK} {len(vtos)} producto(s) por vencer:")
            for v in vtos[:5]:
                d = v["dias_restantes"]
                est = "VENCIDO" if d < 0 else ("HOY" if d == 0 else f"en {d} d")
                print(f"        {v['descripcion'][:34]:<36} {est}")
        else:
            print(f"{AVISO} No hay nada por vencer: el mail NO se manda aunque")
            print("        este todo bien configurado. No es un error.")

        stock = get_informe_stock(
            solo_criticos=c.get("informe_stock_email_solo_criticos", False),
            umbral=c.get("stock_alerta_umbral", 5))
        print(f"{OK} Informe de stock: {len(stock)} producto(s) a reportar")
    except Exception as e:
        print(f"{MAL} No se pudo consultar la base: {e}")
        problemas.append("base")

    _t("5. Conexion real al servidor")
    host = c.get("email_smtp_host")
    port = int(c.get("email_smtp_port") or 587)
    if not host:
        print(f"{MAL} Sin servidor configurado, no se puede probar.")
    else:
        try:
            socket.create_connection((host, port), timeout=10).close()
            print(f"{OK} Se llega a {host}:{port}")
        except Exception as e:
            print(f"{MAL} No se llega a {host}:{port} → {e}")
            print("        Suele ser el firewall, el antivirus o el puerto bloqueado")
            print("        por el proveedor de internet. Probar puerto 465 o 587.")
            problemas.append("red")
            return problemas

        if c.get("email_usuario") and c.get("email_password"):
            try:
                with smtplib.SMTP(host, port, timeout=20) as srv:
                    srv.starttls()
                    srv.login(c["email_usuario"], c["email_password"])
                print(f"{OK} Usuario y contrasena aceptados por el servidor")
            except smtplib.SMTPAuthenticationError as e:
                print(f"{MAL} El servidor RECHAZO usuario/contrasena.")
                print(f"        {e.smtp_error.decode('utf-8', 'ignore')[:150]}")
                print("        En Gmail: hace falta clave de aplicacion, no la comun.")
                problemas.append("login")
            except Exception as e:
                print(f"{MAL} Fallo el saludo con el servidor: {e}")
                problemas.append("smtp")

    return problemas


def enviar_pruebas():
    _t("6. Envio de prueba")
    from impresion import enviar_alerta_vencimientos, enviar_informe_stock
    ok, msg = enviar_alerta_vencimientos(solo_una_vez_por_dia=False)
    print(f"{OK if ok else MAL} Vencimientos: {msg}")
    ok2, msg2 = enviar_informe_stock()
    print(f"{OK if ok2 else MAL} Informe de stock: {msg2}")


if __name__ == "__main__":
    print("DIAGNOSTICO DE EMAIL — TPV")
    problemas = revisar()

    if "--enviar" in sys.argv:
        enviar_pruebas()

    _t("RESUMEN")
    if not problemas:
        print(f"{OK} La configuracion esta completa y el servidor responde.")
        print("       Si igual no llega, mira la carpeta de SPAM del destinatario.")
        print("       Para forzar un envio ahora:  python diagnostico_email.py --enviar")
    else:
        print(f"{MAL} {len(problemas)} problema(s): " + ", ".join(problemas))
        print("       Arreglalos de arriba hacia abajo: el primero suele")
        print("       explicar todos los demas.")

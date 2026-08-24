"""
crear_acceso_directo.py — Pone el TPV en el escritorio y en el menú Inicio.

Se corre UNA vez. Después el sistema se abre con doble clic, sin pasar
por Visual Studio ni por la consola.

USO
---
    .venv\\Scripts\\python.exe crear_acceso_directo.py

Opcional: --inicio-automatico  para que arranque solo al prender la PC.
"""

import os
import sys


CARPETA = os.path.normpath(os.path.dirname(os.path.abspath(__file__)))
BAT = os.path.join(CARPETA, "TPV.bat")
BAT_PRUEBA = os.path.join(CARPETA, "TPV_MODO_PRUEBA.bat")


def _icono():
    """Un .ico de la carpeta, si hay. Si no, el de Python."""
    for nombre in ("tpv.ico", "arai.ico", "icono.ico", "logo.ico"):
        ruta = os.path.join(CARPETA, nombre)
        if os.path.exists(ruta):
            return ruta
    # El ejecutable de Python trae su propio ícono
    return sys.executable


def _crear(destino, nombre, objetivo, descripcion, icono=None):
    """Crea un .lnk usando el COM de Windows.

    Se usa pywin32 si está; si no, un script de PowerShell — que viene
    con Windows y no necesita instalar nada.
    """
    # normpath: sin esto la ruta queda con barras mezcladas al armar el
    # comando de PowerShell, que es fragil con las comillas.
    # Barras invertidas siempre: el comando de PowerShell es fragil con
    # las rutas mezcladas.
    lnk = os.path.join(destino, f"{nombre}.lnk").replace("/", "\\")
    objetivo = objetivo.replace("/", "\\")
    try:
        import win32com.client
        shell = win32com.client.Dispatch("WScript.Shell")
        acceso = shell.CreateShortCut(lnk)
        acceso.TargetPath = objetivo
        acceso.WorkingDirectory = CARPETA
        acceso.Description = descripcion
        acceso.IconLocation = icono or _icono()
        # Minimizada: el .bat abre la app y no aporta nada verlo
        acceso.WindowStyle = 7
        acceso.save()
        return lnk
    except ImportError:
        pass

    import subprocess
    ps = (
        f"$s = (New-Object -COM WScript.Shell).CreateShortcut('{lnk}');"
        f"$s.TargetPath = '{objetivo}';"
        f"$s.WorkingDirectory = '{CARPETA.replace('/', chr(92))}';"
        f"$s.Description = '{descripcion}';"
        f"$s.IconLocation = '{icono or _icono()}';"
        f"$s.WindowStyle = 7;"
        f"$s.Save()"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                   check=True, capture_output=True)
    return lnk


def main():
    if os.name != "nt":
        print("Esto es para Windows.")
        return

    if not os.path.exists(BAT):
        print(f"[FALLA] No encuentro {BAT}")
        print("        Tiene que estar en la misma carpeta que main.py.")
        return

    escritorio = os.path.join(os.path.expanduser("~"), "Desktop")
    if not os.path.isdir(escritorio):
        # OneDrive se lleva el escritorio a otra carpeta
        alt = os.path.join(os.path.expanduser("~"), "OneDrive", "Escritorio")
        escritorio = alt if os.path.isdir(alt) else os.path.expanduser("~")

    print("=" * 60)
    print("ACCESO DIRECTO AL TPV")
    print("=" * 60)

    hechos = []
    try:
        hechos.append(_crear(escritorio, "TPV Autoservicio", BAT,
                             "Abre el TPV con la base del negocio"))
        print(f"[OK] En el escritorio: {escritorio}")
    except Exception as exc:
        print(f"[FALLA] Escritorio: {exc}")

    # El de prueba también, pero con nombre que no se confunda
    if os.path.exists(BAT_PRUEBA):
        try:
            _crear(escritorio, "TPV (modo prueba)", BAT_PRUEBA,
                   "Abre el TPV contra una copia: no afecta al negocio")
            print("[OK] También el de modo prueba")
        except Exception as exc:
            print(f"[aviso] No se pudo crear el de prueba: {exc}")

    # Menú Inicio: para encontrarlo escribiendo "TPV"
    menu = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows",
                        "Start Menu", "Programs")
    if os.path.isdir(menu):
        try:
            _crear(menu, "TPV Autoservicio", BAT,
                   "Abre el TPV con la base del negocio")
            print("[OK] En el menú Inicio (buscá «TPV»)")
        except Exception as exc:
            print(f"[aviso] Menú Inicio: {exc}")

    if "--inicio-automatico" in sys.argv:
        inicio = os.path.join(os.environ.get("APPDATA", ""), "Microsoft",
                              "Windows", "Start Menu", "Programs", "Startup")
        if os.path.isdir(inicio):
            try:
                _crear(inicio, "TPV Autoservicio", BAT,
                       "Abre el TPV al prender la PC")
                print("[OK] Arranca solo al prender la PC")
            except Exception as exc:
                print(f"[aviso] Inicio automático: {exc}")
    else:
        print("\nPara que arranque solo al prender la PC, correlo así:")
        print("    .venv\\Scripts\\python.exe crear_acceso_directo.py "
              "--inicio-automatico")

    if hechos:
        print("\nListo. Doble clic en «TPV Autoservicio» del escritorio.")
    print("=" * 60)


if __name__ == "__main__":
    main()

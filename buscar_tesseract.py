"""
buscar_tesseract.py — Encontrar dónde quedó instalado Tesseract.

El TPV lo busca en las rutas habituales, pero si el instalador lo dejó
en otro lado, no lo encuentra y el lector de facturas no anda.

Este script lo busca en todo el disco, comprueba que funcione y deja la
ruta guardada para que el TPV la use.

USO
---
    .venv\\Scripts\\python.exe buscar_tesseract.py
"""

import os
import subprocess
import sys

# Carpetas donde tiene sentido buscar. Recorrer C:\ entero tarda
# minutos; estas cubren todos los instaladores conocidos.
_RAICES = [
    r"C:\Program Files",
    r"C:\Program Files (x86)",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs"),
    os.path.expandvars(r"%LOCALAPPDATA%"),
    os.path.expandvars(r"%APPDATA%"),
    os.path.expandvars(r"%USERPROFILE%\Downloads"),
    r"C:\Tesseract-OCR",
    r"C:\tools",
]


def _en_path():
    """¿Está en el PATH? Es como debería estar."""
    try:
        r = subprocess.run(["tesseract", "--version"],
                           capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            return r.stdout.splitlines()[0] if r.stdout else "sí"
    except Exception:
        pass
    return ""


def _buscar_en_disco():
    """Busca tesseract.exe bajo las carpetas conocidas."""
    encontrados = []
    for raiz in _RAICES:
        if not raiz or not os.path.isdir(raiz):
            continue
        for base, dirs, files in os.walk(raiz):
            # No bajar más de lo necesario: los instaladores no
            # esconden el ejecutable diez niveles adentro.
            if base.count(os.sep) - raiz.count(os.sep) > 3:
                dirs[:] = []
                continue
            for f in files:
                if f.lower() == "tesseract.exe":
                    encontrados.append(os.path.join(base, f))
        if encontrados:
            break
    return encontrados


def _probar(ruta):
    """¿Este ejecutable funciona de verdad?"""
    try:
        r = subprocess.run([ruta, "--version"], capture_output=True,
                           text=True, timeout=15)
        if r.returncode == 0:
            return r.stdout.splitlines()[0] if r.stdout else "ok"
    except Exception as exc:
        return f"[falla: {exc}]"
    return ""


def main():
    print("=" * 68)
    print("BUSCAR TESSERACT (lector de facturas)")
    print("=" * 68)

    print("\n1. ¿Está en el PATH?")
    v = _en_path()
    if v:
        print(f"   [OK]  {v}")
        print("\n   El lector de facturas debería funcionar.")
        print("   Si igual falla, cerrá y volvé a abrir el TPV: el PATH")
        print("   se lee al arrancar el programa.")
        return
    print("   [no]  No está en el PATH. Lo busco en el disco…")

    print("\n2. Buscando el ejecutable…")
    rutas = _buscar_en_disco()
    if not rutas:
        print("   [FALTA]  No se encontró tesseract.exe.")
        print("\n   Puede que lo que instalaste sea el paquete de Python")
        print("   (pytesseract) y no el programa. Son dos cosas:")
        print("     · pytesseract → se instala con pip")
        print("     · Tesseract   → es un programa aparte, se descarga de")
        print("       https://github.com/UB-Mannheim/tesseract/wiki")
        return

    print(f"   Encontrado(s) {len(rutas)}:")
    buena = ""
    for r in rutas:
        estado = _probar(r)
        print(f"     {r}")
        print(f"        → {estado or '[no responde]'}")
        if estado and not estado.startswith("[") and not buena:
            buena = r

    if not buena:
        print("\n   [FALTA]  Está el archivo pero no funciona.")
        print("   Probá reinstalarlo desde el instalador oficial.")
        return

    print("\n3. Guardando la ruta para el TPV…")
    try:
        from config import set as cfg_set
        cfg_set("tesseract_ruta", buena)
        print(f"   [OK]  Guardada: {buena}")
        print("\n   Ya podés leer facturas. Si el TPV está abierto,")
        print("   cerralo y volvé a abrirlo.")
    except Exception as exc:
        print(f"   [FALLA]  No se pudo guardar: {exc}")
        print("\n   Ruta encontrada, para cargarla a mano:")
        print(f"   {buena}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelado.")
        sys.exit(0)

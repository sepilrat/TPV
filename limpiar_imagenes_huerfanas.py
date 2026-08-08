"""
limpiar_imagenes_huerfanas.py — TPV v2.0

Recorre imagenes_productos/ y borra los archivos {id}.jpg que quedaron
huérfanos: productos que ya no existen, o que existen pero su
imagen_url actual en la base YA NO apunta a ese archivo local (por
ejemplo, porque se reemplazó la foto local por una URL, o se le sacó
la foto, antes de que existiera la limpieza automática).

Es de UN SOLO USO — para poner al día lo que se acumuló hasta ahora.
De acá en adelante, guardar/eliminar productos ya limpia solo.

Por seguridad, primero MUESTRA qué archivos borraría, y pide
confirmación antes de borrar nada.

Uso:
  python limpiar_imagenes_huerfanas.py            → muestra y pide confirmación
  python limpiar_imagenes_huerfanas.py --si        → borra sin preguntar
"""
import os
import sys

from db import get_connection
from imagenes import CARPETA_IMAGENES


def main():
    confirmar_solo = "--si" not in sys.argv

    if not os.path.isdir(CARPETA_IMAGENES):
        print(f"No existe la carpeta {CARPETA_IMAGENES} — nada que limpiar.")
        return

    with get_connection() as conn:
        filas = conn.execute(
            "SELECT id, imagen_url FROM productos").fetchall()

    # id -> ruta local relativa que SI está en uso ahora mismo
    en_uso = {}
    for f in filas:
        rel = f["imagen_url"] or ""
        if rel.replace("\\", "/").startswith("imagenes_productos/"):
            en_uso[f["id"]] = os.path.basename(rel)

    archivos = [f for f in os.listdir(CARPETA_IMAGENES)
                if f.lower().endswith(".jpg")]

    huerfanos = []
    for nombre in archivos:
        try:
            pid = int(os.path.splitext(nombre)[0])
        except ValueError:
            continue   # nombre raro, no tocarlo
        nombre_en_uso = en_uso.get(pid)
        if nombre_en_uso != nombre:
            huerfanos.append(nombre)

    if not huerfanos:
        print("No se encontraron archivos huérfanos. Todo en orden.")
        return

    print(f"Se encontraron {len(huerfanos)} archivo(s) huérfano(s) en "
          f"{CARPETA_IMAGENES}:\n")
    for nombre in huerfanos:
        ruta = os.path.join(CARPETA_IMAGENES, nombre)
        kb = os.path.getsize(ruta) / 1024
        print(f"  - {nombre}  ({kb:.0f} KB)")

    if confirmar_solo:
        print("\nEsto fue solo una vista previa — no se borró nada.")
        print("Para borrarlos de verdad, corré:")
        print("  python limpiar_imagenes_huerfanas.py --si")
        return

    borrados = 0
    for nombre in huerfanos:
        try:
            os.remove(os.path.join(CARPETA_IMAGENES, nombre))
            borrados += 1
        except OSError as e:
            print(f"  No se pudo borrar {nombre}: {e}")

    print(f"\nListo — se borraron {borrados} de {len(huerfanos)} archivo(s).")


if __name__ == "__main__":
    main()

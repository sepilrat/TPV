"""
restaurar_backup.py — Volver a una copia anterior de la base.

Un backup sin forma fácil de restaurarlo es medio backup: cuando hace
falta, uno está apurado y nervioso.

USO
---
    .venv\\Scripts\\python.exe restaurar_backup.py
        lista las copias disponibles

    .venv\\Scripts\\python.exe restaurar_backup.py 2026-08-25
        restaura la copia de ese día

La base actual NO se borra: se guarda como tpv2_ANTES_DE_RESTAURAR.db
por si la restauración fue un error.
"""

import os
import shutil
import sqlite3
import sys
from datetime import datetime

CARPETA = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(CARPETA, "tpv2.db")
DIARIOS = os.path.join(CARPETA, "backups", "diarios")
BACKUPS = os.path.join(CARPETA, "backups")


def _info(ruta):
    """Cuántos productos y ventas tiene esa copia, para reconocerla."""
    try:
        c = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True)
        prod = c.execute("SELECT COUNT(*) FROM productos").fetchone()[0]
        ven = c.execute("SELECT COUNT(*) FROM ventas").fetchone()[0]
        ult = c.execute("SELECT MAX(fecha) FROM ventas").fetchone()[0] or "—"
        c.close()
        return f"{prod} productos · {ven} ventas · última venta {str(ult)[:16]}"
    except Exception as e:
        return f"(no se pudo leer: {e})"


def _listar():
    copias = []
    for carpeta in (DIARIOS, BACKUPS):
        if not os.path.isdir(carpeta):
            continue
        for f in sorted(os.listdir(carpeta)):
            if f.endswith(".db") and f.startswith("tpv2"):
                ruta = os.path.join(carpeta, f)
                copias.append((ruta, f, os.path.getmtime(ruta)))
    copias.sort(key=lambda x: -x[2])
    return copias


def main():
    print("=" * 70)
    print("RESTAURAR UNA COPIA DE SEGURIDAD")
    print("=" * 70)

    copias = _listar()
    if not copias:
        print("\nNo hay copias todavía.")
        print("Se crean solas al abrir el TPV y al cerrar la caja.")
        return

    if len(sys.argv) < 2:
        print(f"\n{len(copias)} copia(s) disponibles:\n")
        for ruta, nombre, ts in copias[:20]:
            fecha = datetime.fromtimestamp(ts).strftime("%d/%m/%Y %H:%M")
            print(f"   {nombre:<34} {fecha}")
            print(f"   {'':<34} {_info(ruta)}")
        print("\nPara restaurar una, poné parte del nombre:")
        print("    .venv\\Scripts\\python.exe restaurar_backup.py 2026-08-25")
        return

    buscado = sys.argv[1]
    candidatas = [c for c in copias if buscado in c[1]]
    if not candidatas:
        print(f"\nNinguna copia coincide con «{buscado}».")
        print("Corré el script sin argumentos para ver la lista.")
        return
    if len(candidatas) > 1:
        print(f"\nHay {len(candidatas)} copias que coinciden. Sé más preciso:")
        for _, n, _ts in candidatas:
            print(f"   {n}")
        return

    ruta, nombre, ts = candidatas[0]
    print("\nSe va a restaurar:")
    print(f"   {nombre}")
    print(f"   {datetime.fromtimestamp(ts).strftime('%d/%m/%Y %H:%M')}")
    print(f"   {_info(ruta)}")

    if os.path.exists(DB):
        print("\nLa base ACTUAL tiene:")
        print(f"   {_info(DB)}")

    print("\n" + "!" * 70)
    print("Todo lo cargado DESPUÉS de esa copia se pierde.")
    print("La base actual se guarda como tpv2_ANTES_DE_RESTAURAR.db")
    print("!" * 70)
    print("\nEscribí RESTAURAR en mayúsculas para confirmar: ", end="")
    if input().strip() != "RESTAURAR":
        print("Cancelado. No se tocó nada.")
        return

    try:
        if os.path.exists(DB):
            respaldo = os.path.join(CARPETA, "tpv2_ANTES_DE_RESTAURAR.db")
            shutil.copy2(DB, respaldo)
            print(f"\n[OK] Base actual guardada en {os.path.basename(respaldo)}")

        # Los archivos -wal y -shm quedan del modo WAL: si sobreviven a
        # la restauración, SQLite los aplica encima y la copia restaurada
        # queda mezclada con lo viejo.
        for ext in ("-wal", "-shm"):
            aux = DB + ext
            if os.path.exists(aux):
                os.remove(aux)

        shutil.copy2(ruta, DB)
        c = sqlite3.connect(DB)
        estado = c.execute("PRAGMA integrity_check").fetchone()[0]
        c.close()
        if estado != "ok":
            print(f"[FALLA] La base restaurada no pasa el chequeo: {estado}")
            return

        print(f"[OK] Restaurada desde {nombre}")
        print(f"     {_info(DB)}")
        print("\nYa podés abrir el TPV.")
    except Exception as exc:
        print(f"\n[FALLA] {exc}")
        print("La base original sigue en tpv2_ANTES_DE_RESTAURAR.db")


if __name__ == "__main__":
    main()

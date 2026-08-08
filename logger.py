"""
logger.py — Logs y backup automático TPV v2.0
Importar en main.py: from logger import inicializar_logs, hacer_backup
"""

import logging
import os
import sqlite3
from datetime import datetime

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURACIÓN
# ─────────────────────────────────────────────────────────────────────────────

BASE_DIR    = os.path.dirname(__file__)
LOG_DIR     = os.path.join(BASE_DIR, "logs")
BACKUP_DIR  = os.path.join(BASE_DIR, "backups")
DB_PATH     = os.path.join(BASE_DIR, "tpv2.db")
MAX_BACKUPS = 30   # máximo de backups a conservar
MAX_LOGS    = 10   # máximo de archivos de log a conservar


# ─────────────────────────────────────────────────────────────────────────────
# LOGS
# ─────────────────────────────────────────────────────────────────────────────

def inicializar_logs():
    """
    Configura el sistema de logging.
    - Archivo: logs/tpv_AAAA-MM-DD.log
    - Consola: solo WARNING y superiores
    Llamar una sola vez al iniciar la app.
    """
    os.makedirs(LOG_DIR, exist_ok=True)

    hoy      = datetime.now().strftime("%Y-%m-%d")
    log_file = os.path.join(LOG_DIR, f"tpv_{hoy}.log")

    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    # Handler archivo — todo desde DEBUG
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(module)s — %(message)s",
        datefmt="%H:%M:%S"
    ))

    # Handler consola — solo WARNING+
    ch = logging.StreamHandler()
    ch.setLevel(logging.WARNING)
    ch.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))

    logger.addHandler(fh)
    logger.addHandler(ch)

    logging.info(f"Sistema TPV iniciado — log: {log_file}")
    _limpiar_logs_viejos()


def _limpiar_logs_viejos():
    """Borra logs más viejos si hay más de MAX_LOGS."""
    try:
        archivos = sorted(
            [f for f in os.listdir(LOG_DIR) if f.endswith(".log")],
            reverse=True
        )
        for viejo in archivos[MAX_LOGS:]:
            os.remove(os.path.join(LOG_DIR, viejo))
            logging.debug(f"Log viejo eliminado: {viejo}")
    except Exception as e:
        logging.warning(f"No se pudieron limpiar logs viejos: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# BACKUP
# ─────────────────────────────────────────────────────────────────────────────

def hacer_backup(motivo: str = "manual") -> str | None:
    """
    Copia tpv2.db a backups/tpv2_AAAA-MM-DD_HH-MM_motivo.db
    Retorna la ruta del backup o None si falló.
    """
    if not os.path.exists(DB_PATH):
        logging.warning("Backup: base de datos no encontrada.")
        return None

    os.makedirs(BACKUP_DIR, exist_ok=True)

    ts      = datetime.now().strftime("%Y-%m-%d_%H-%M")
    nombre  = f"tpv2_{ts}_{motivo}.db"
    destino = os.path.join(BACKUP_DIR, nombre)

    try:
        # NO usar shutil.copy2: la base corre en modo WAL (db.py), asi que las
        # transacciones recientes viven en tpv2.db-wal. Copiar solo el .db deja
        # afuera lo ultimo, y copiar los tres por separado puede mezclar
        # momentos distintos. La API backup() de sqlite3 escribe un archivo
        # unico y consistente, con la base abierta y sin bloquear la caja.
        origen = sqlite3.connect(DB_PATH)
        try:
            copia = sqlite3.connect(destino)
            try:
                origen.backup(copia)
            finally:
                copia.close()
        finally:
            origen.close()

        # Verificar que lo escrito se pueda abrir y no este corrupto.
        chk = sqlite3.connect(destino)
        try:
            estado = chk.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            chk.close()
        if estado != "ok":
            logging.error(f"Backup {nombre} salio corrupto: {estado}")
            try:
                os.remove(destino)
            except OSError:
                pass
            return None

        logging.info(f"Backup creado y verificado: {nombre}")
        _limpiar_backups_viejos()
        return destino
    except Exception as e:
        logging.error(f"Error creando backup: {e}")
        return None


def _limpiar_backups_viejos():
    """Borra backups más viejos si hay más de MAX_BACKUPS."""
    try:
        archivos = sorted(
            [f for f in os.listdir(BACKUP_DIR) if f.endswith(".db")],
            reverse=True
        )
        for viejo in archivos[MAX_BACKUPS:]:
            os.remove(os.path.join(BACKUP_DIR, viejo))
            logging.debug(f"Backup viejo eliminado: {viejo}")
    except Exception as e:
        logging.warning(f"No se pudieron limpiar backups viejos: {e}")


def get_info_backups() -> list[dict]:
    """Retorna lista de backups disponibles con nombre, fecha y tamaño."""
    if not os.path.exists(BACKUP_DIR):
        return []
    result = []
    for f in sorted(os.listdir(BACKUP_DIR), reverse=True):
        if not f.endswith(".db"):
            continue
        path = os.path.join(BACKUP_DIR, f)
        size = os.path.getsize(path) / 1024  # KB
        result.append({
            "nombre": f,
            "ruta":   path,
            "size_kb": round(size, 1),
            "fecha":  datetime.fromtimestamp(
                os.path.getmtime(path)
            ).strftime("%Y-%m-%d %H:%M"),
        })
    return result

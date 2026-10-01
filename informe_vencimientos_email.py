"""
informe_vencimientos_email.py — Envío automático del aviso de vencimientos por email.

Este script NO abre la interfaz del TPV. Está pensado para ejecutarse
solo, en segundo plano, programado con el Programador de tareas de
Windows — así el informe llega al email todos los días a una hora
fija sin que nadie tenga que abrir el sistema.

Cómo programarlo (una sola vez):
  1. Abrí el "Programador de tareas" de Windows (Task Scheduler).
  2. Crear tarea básica → nombre: "TPV - Vencimientos".
  3. Desencadenador: Diariamente, a la hora que configuraste en
     Config → Avisos por email → Vencimientos: hora.
  4. Acción: Iniciar un programa.
       Programa/script:  C:\\Users\\juampa\\Dropbox\\Sistemas\\TPV\\.venv\\Scripts\\python.exe
       Argumentos:       informe_vencimientos_email.py
       Iniciar en:       C:\\Users\\juampa\\Dropbox\\Sistemas\\TPV
  5. Finalizar. Podés probarla con click derecho → Ejecutar, y revisar
     logs/tpv_AAAA-MM-DD.log para confirmar que se mandó bien.

También podés correrlo a mano en cualquier momento para probar:
  .venv\\Scripts\\python.exe informe_vencimientos_email.py
"""

import os
import sys
import logging

# Asegurar que los imports funcionen sin importar desde dónde se
# lance el script (el Programador de tareas puede usar otro cwd).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from logger import inicializar_logs
from config import cfg
from impresion import enviar_alerta_vencimientos


def main():
    inicializar_logs()
    c = cfg()

    if not c.get("vto_email_activo"):
        logging.info(
            "Vencimientos: envío automático desactivado "
            "(Config → Avisos por email)."
        )
        return 0

    ok, msg = enviar_alerta_vencimientos(solo_una_vez_por_dia=False)
    if ok:
        logging.info(f"Vencimientos: {msg}")
        return 0
    else:
        logging.error(f"Vencimientos: {msg}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

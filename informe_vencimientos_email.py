"""
informe_vencimientos_email.py — Envío automático por email (Vencimientos).

Este script NO abre la interfaz del TPV. Lo dispara el Programador de tareas
de Windows cada 10 minutos con --programado, y en cada corrida lee la HORA DE
ENVÍO que esté en Config: pasada esa hora, manda una vez por día; antes, no
hace nada. Cambiar la hora en el TPV alcanza, sin tocar Windows.

La tarea se crea una sola vez: Config → botón "⏰ Tareas de Windows"
(o doble clic en crear_tareas_programadas.bat).

Probarlo a mano (manda ya y no consume el envío del día):
  .venv\\Scripts\\python.exe informe_vencimientos_email.py
"""

import os
import sys
import logging

# Asegurar que los imports funcionen sin importar desde dónde se
# lance el script (el Programador de tareas puede usar otro cwd).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from logger import inicializar_logs
from config import cfg, set as cfg_set
from impresion import enviar_alerta_vencimientos
from programacion import correr_programado


def main(argv=None):
    return correr_programado(
        sys.argv[1:] if argv is None else argv,
        nombre="Vencimientos",
        clave_activo="vto_email_activo", clave_hora="vto_email_hora",
        clave_envio="_vto_ultimo_envio", clave_intento="_vto_ultimo_intento",
        enviar=lambda: enviar_alerta_vencimientos(solo_una_vez_por_dia=False),
        hora_defecto=(8, 30),
        cfg=cfg, cfg_set=cfg_set, inicializar_logs=inicializar_logs)


if __name__ == "__main__":
    sys.exit(main())

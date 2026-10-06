"""
programacion.py — Envios programados que toman la HORA DE LA CONFIG.

La tarea de Windows corre cada 10 minutos con --programado. En cada corrida el
script pregunta aca "¿toca mandar?": si ya paso la hora de Config y hoy no
salio, manda; si no, sale sin hacer ruido. Asi, cambiar la hora en el TPV
alcanza: no hay que volver a crear la tarea de Windows.
"""
import logging
from datetime import datetime

REINTENTO_MIN = 60     # si un envio falla, no se vuelve a probar antes de una hora


def hora_min(texto, defecto=(21, 30)):
    """"HH:MM" -> (h, m); si esta mal escrita, el valor por defecto."""
    try:
        hh, mm = (int(x) for x in str(texto or "").strip().split(":")[:2])
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return hh, mm
    except ValueError:
        pass
    return defecto


def en_espera_por_fallo(ahora: datetime, ultimo_intento: str) -> bool:
    """True si el ultimo intento fallo hace menos de REINTENTO_MIN minutos."""
    if not ultimo_intento:
        return False
    try:
        previo = datetime.strptime(str(ultimo_intento)[:16], "%Y-%m-%d %H:%M")
    except ValueError:
        return False
    return (ahora - previo).total_seconds() < REINTENTO_MIN * 60


def toca_enviar_hoy(ahora: datetime, hora_cfg: str, ultimo_envio: str,
                    ultimo_intento: str = "", hora_defecto=(21, 30)) -> bool:
    """Informes del estado ACTUAL (stock, vencimientos): uno por dia, pasada la hora."""
    if (ahora.hour, ahora.minute) < hora_min(hora_cfg, hora_defecto):
        return False
    if (ultimo_envio or "") >= ahora.date().isoformat():
        return False
    return not en_espera_por_fallo(ahora, ultimo_intento)


def correr_programado(argv, *, nombre, clave_activo, clave_hora, clave_envio,
                      clave_intento, enviar, hora_defecto, cfg, cfg_set,
                      inicializar_logs):
    """main() comun de los scripts de stock y vencimientos. Devuelve el codigo de salida.

    Con --programado: solo manda si toca (ver toca_enviar_hoy) y no escribe nada
    al log cuando no toca. Sin argumentos (prueba a mano): manda ya y no
    consume el envio del dia.
    """
    programado = "--programado" in argv
    c = cfg()
    ahora = datetime.now()
    if programado:
        if not c.get(clave_activo):
            return 0
        if not toca_enviar_hoy(ahora, c.get(clave_hora), c.get(clave_envio),
                               c.get(clave_intento), hora_defecto):
            return 0
    try:
        inicializar_logs()
    except Exception as exc:
        print(f"No se pudo iniciar el log: {exc}")
    logging.info(f"{nombre}: arranco el envio " + ("programado" if programado else "manual"))
    try:
        if not c.get(clave_activo):
            logging.warning(f"{nombre}: NO se envio porque esta destildado en Config.")
            return 0
        ok, msg = enviar()
        if ok:
            logging.info(f"{nombre}: {msg}")
            if programado:
                cfg_set(clave_envio, ahora.date().isoformat())
                cfg_set(clave_intento, "")
            return 0
        logging.error(f"{nombre}: {msg}")
    except Exception:
        logging.exception(f"{nombre}: error inesperado, NO se envio")
    if programado:
        try:
            cfg_set(clave_intento, datetime.now().strftime("%Y-%m-%d %H:%M"))
        except Exception:
            pass
    return 1

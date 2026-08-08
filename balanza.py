"""
balanza.py — Lectura de peso desde una balanza por puerto serie (RS-232)
TPV v2.0

Implementa el protocolo "Solicitud de peso estable" documentado por
Systel para sus equipos (Clipse, Croma, Bumer, Maya, Flaier, Flaier
Plus, Komba, Nexa, Pilon, Vita, Urbe) — funciona igual en todos esos
modelos, no es específico de la Croma:
  https://soporte.systel-global.com/downloads/Instructivos/Comunicacion-RS232/Protocolo%20de%20comunicaci%C3%B3n%20RS232%20Systel.pdf

Protocolo (resumen):
  PC -> balanza:  1 byte, 0x05 (ENQ) — "pedime el peso"
  balanza -> PC, si el peso está ESTABLE:
      0x02 (STX) + 6 o 7 bytes ASCII con el peso (7 si es negativo,
      con el signo "-" adelante) + 0x03 (ETX) + 1 byte de verificación
      (XOR de todos los bytes anteriores)
  balanza -> PC, si el peso está INESTABLE (se está moviendo/acomodando):
      1 byte, 0x11 — pedido rechazado, hay que reintentar

Requiere pyserial:  pip install pyserial

No se pudo probar contra una balanza física real (este es un entorno
sin hardware conectado) — está implementado siguiendo al pie de la
letra el manual oficial de Systel. Si al probarlo con la balanza real
da un error de parseo, correr diagnosticar_balanza() y mandar el
resultado: con los bytes crudos que devuelve se ajusta al toque.
"""
import logging

ENQ = b"\x05"
STX = 0x02
ETX = 0x03
NAK_INESTABLE = 0x11


def _abrir_puerto(puerto: str, baudrate: int, timeout: float):
    import serial  # pyserial — import acá adentro para no romper si no está instalado
    return serial.Serial(port=puerto, baudrate=baudrate,
                         bytesize=8, parity="N", stopbits=1,
                         timeout=timeout)


def leer_peso(puerto: str = None, baudrate: int = None,
             timeout: float = 1.5) -> tuple[float | None, str]:
    """
    Pide el peso actual a la balanza y lo devuelve.
    Retorna (peso_en_kg, mensaje):
      - (1.234, "OK") si se leyó bien
      - (None, "inestable") si el peso todavía se está acomodando —
        reintentar en un momento
      - (None, "<motivo del error>") si falló la conexión/lectura
    Si no se pasan puerto/baudrate, los toma de la configuración.
    """
    if puerto is None or baudrate is None:
        from config import cfg
        c = cfg()
        puerto = puerto or c.get("balanza_puerto", "COM3")
        baudrate = baudrate or c.get("balanza_baudrate", 9600)

    try:
        ser = _abrir_puerto(puerto, baudrate, timeout)
    except ImportError:
        return None, ("Falta instalar pyserial: pip install pyserial")
    except Exception as e:
        return None, f"No se pudo abrir el puerto {puerto}: {e}"

    try:
        ser.reset_input_buffer()
        ser.write(ENQ)

        primero = ser.read(1)
        if not primero:
            return None, (f"La balanza no respondió (puerto {puerto}, "
                          f"¿está prendida y conectada ahí?)")

        if primero[0] == NAK_INESTABLE:
            return None, "inestable"

        if primero[0] != STX:
            return None, (f"Respuesta inesperada de la balanza "
                          f"(primer byte: {primero.hex()})")

        # Leer hasta encontrar ETX (0x03), con un límite de seguridad
        datos = b""
        for _ in range(16):
            b = ser.read(1)
            if not b:
                return None, "La balanza cortó la transmisión a mitad de camino."
            if b[0] == ETX:
                break
            datos += b
        else:
            return None, "No se encontró el fin de trama (ETX) — revisar protocolo."

        ser.read(1)  # byte de verificación — se lee para vaciar el buffer, no se valida estricto

        texto_peso = datos.decode("ascii", errors="ignore").strip()
        try:
            peso = float(texto_peso)
        except ValueError:
            return None, f"No se pudo interpretar el peso recibido: {texto_peso!r}"

        return peso, "OK"

    except Exception as e:
        return None, f"Error leyendo la balanza: {e}"
    finally:
        try:
            ser.close()
        except Exception as e:
            logging.debug(f"No se pudo cerrar el puerto de la balanza: {e}")


def diagnosticar_balanza(puerto: str = None, baudrate: int = None,
                         timeout: float = 2.0) -> str:
    """
    Pide el peso UNA vez y devuelve un texto con todo lo que se pueda
    ver: los bytes crudos recibidos, y el resultado de intentar
    interpretarlos. Pensado para mandarlo cuando algo no calza — con
    eso se ajusta el parseo sin necesidad de tener la balanza a mano.
    """
    if puerto is None or baudrate is None:
        from config import cfg
        c = cfg()
        puerto = puerto or c.get("balanza_puerto", "COM3")
        baudrate = baudrate or c.get("balanza_baudrate", 9600)

    lineas = [f"Puerto: {puerto}  Baudrate: {baudrate}"]
    try:
        ser = _abrir_puerto(puerto, baudrate, timeout)
    except ImportError:
        return "Falta instalar pyserial: pip install pyserial"
    except Exception as e:
        return f"No se pudo abrir el puerto {puerto}: {e}"

    try:
        ser.reset_input_buffer()
        ser.write(ENQ)
        crudo = ser.read(32)
        lineas.append(f"Bytes crudos recibidos ({len(crudo)}): {crudo!r}")
        lineas.append(f"En hexadecimal: {crudo.hex(' ')}")
        if not crudo:
            lineas.append("→ No llegó nada. Revisar cable, puerto COM y que "
                          "la balanza esté prendida.")
        elif crudo[0] == NAK_INESTABLE:
            lineas.append("→ La balanza dice que el peso está INESTABLE "
                          "(0x11). Normal si se acaba de poner algo en el "
                          "plato — probar de nuevo en un segundo.")
        elif crudo[0] == STX:
            lineas.append("→ Empieza con STX (0x02), como se espera del "
                          "protocolo estándar de Systel.")
        else:
            lineas.append("→ No empieza con STX ni con el código de "
                          "inestable — puede que la balanza esté "
                          "configurada con otro protocolo (Torrey/CAS) "
                          "en vez del estándar Systel.")
    except Exception as e:
        lineas.append(f"Error durante la lectura: {e}")
    finally:
        try:
            ser.close()
        except Exception as e:
            logging.debug(f"No se pudo cerrar el puerto de la balanza: {e}")

    resultado = "\n".join(lineas)
    logging.info(f"Diagnóstico de balanza:\n{resultado}")
    return resultado

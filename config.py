"""
config.py — Configuración central del sistema TPV v2.0
Todos los parámetros editables del negocio y del sistema en un solo lugar.
"""

import logging
import json
import os

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "tpv_config.json")

# ─────────────────────────────────────────────────────────────────────────────
# VALORES POR DEFECTO
# ─────────────────────────────────────────────────────────────────────────────
DEFAULTS = {
    # Datos del negocio
    "negocio_nombre":       "Mayorista Araí",
    "negocio_direccion":    "8 de Diciembre s/n Cuartel V",
    "negocio_telefono":     "11-3436-8603",
    "negocio_cuit":         "20-28463483-0",
    "negocio_email":        "",
    "negocio_web":          "",
    "negocio_logo_path":    "",
    "folleto_color":        "#2451B0",   # color del encabezado/borde del folleto de ofertas (hex)
    "folleto_color_precio": "#DC2626",   # color de fondo del cartel de precio (hex) — más llamativo
    # Ultima subida del catalogo web (solo informativo, lo escribe el sistema)
    "catalogo_web_ultima_sync":     "",
    "catalogo_web_ultima_cantidad": 0,

    "folleto_foto_pct": 58,
    # Cartel de precio superpuesto sobre la foto (libera ~10mm para el texto)
    "folleto_precio_sobre_foto": True,   # % del alto de la celda que ocupa la foto (25-75)
    "folleto_categoria_pagina_nueva": False,  # True = una hoja por categoria
    "folleto_mostrar_codigo": False,     # incluir codigo/PLU en cada producto del folleto
    "folleto_titulo":       "OFERTAS INCREIBLES",  # texto grande centrado. Vacio = no se muestra
    "folleto_subtitulo":    "Ofertas",             # rotulo chico sobre la linea de color. Vacio = no se muestra
    "negocio_mensaje_pie":  "Gracias por su compra!",

    # Impresora térmica
    "impresora_activa":     True,
    "impresora_ancho":      42,          # caracteres por línea (80mm = 42)
    "impresora_nombre":     "",          # vacío = impresora por defecto del sistema
    "impresora_puerto":     "USB",       # USB | COM1 | IP
    "impresora_ip":         "",          # solo si es red/WiFi
    "ticket_auto":          True,        # imprimir automáticamente al cobrar
    "ticket_mostrar_logo":  False,

    # Email (SMTP)
    "email_activo":         False,
    "email_smtp_host":      "smtp.gmail.com",
    "email_smtp_port":      587,
    "email_usuario":        "",
    "email_password":       "",          # se guarda localmente, no se envía
    "email_remitente":      "Mayorista Araí",

    # WhatsApp
    "whatsapp_activo":      True,
    "whatsapp_numero":      "",          # número del negocio (opcional)

    # Stock
    # Vender aunque el stock registrado no alcance. En un autoservicio el
    # stock nunca esta perfecto y frenar la caja cuesta mas que el
    # descuadre: el faltante queda en negativo para corregirlo despues.
    "permitir_venta_sin_stock": True,
    "stock_alerta_umbral":  5,           # unidades mínimas antes de alertar
    "stock_alerta_dias_vto": 7,          # días para alertar vencimientos

    # AVISO DIARIO por email: stock critico + vencimientos, todo junto.
    # Se manda UNA vez por dia, disparado por lo primero que ocurra de
    # los eventos tildados. Asi no depende de una tarea programada de
    # Windows que hay que crear a mano.
    "aviso_diario_activo":          False,
    "aviso_diario_destinatario":    "",
    "aviso_diario_al_abrir_app":    True,
    "aviso_diario_al_abrir_caja":   True,
    "aviso_diario_al_cerrar_caja":  False,
    # Para cuantos dias de venta se quiere tener stock en el mail diario
    "aviso_diario_dias_cobertura":  14,
    "_aviso_diario_ultimo_envio":   "",

    # Aviso de vencimientos por email al abrir el TPV
    "vto_email_activo":        False,
    "vto_email_destinatario":  "",
    "vto_email_max_por_dia":   1,        # no repetir el aviso en el mismo día

    # Redondeo de precios de venta. 0 = sin redondeo.
    # 1 = al peso, 10 = a la decena, 50 y 100 = a esos múltiplos.
    "redondeo_precios":        0,
    # "cercano" = al múltiplo más próximo (menos de la mitad baja, más sube)
    # "arriba"  = siempre al siguiente múltiplo
    # "abajo"   = siempre al múltiplo anterior
    "redondeo_modo":           "cercano",

    # Informe de stock automático por email
    "informe_stock_email_activo":         False,
    "informe_stock_email_destinatario":   "",
    "informe_stock_email_hora":           "08:00",   # HH:MM, 24hs
    "informe_stock_email_solo_criticos":  False,      # False = catálogo completo

    # Caja
    "caja_clave_responsable": "1234",    # clave para operaciones sensibles
    "caja_requiere_fondo":   True,       # pedir fondo al abrir caja

    # Etiquetas de gondola
    "etiqueta_ancho_mm":        95,      # ancho de etiqueta en mm
    "etiqueta_alto_mm":         45,      # alto de etiqueta en mm
    "etiqueta_cols":             2,      # columnas por hoja A4
    "etiqueta_filas":            5,      # filas por hoja A4
    "etiqueta_margen_arriba_mm": 10,     # espacio antes de la primera fila
    # Etiquetas pegadas entre si: 1 corte vertical parte toda la hoja en
    # vez de 2 por columna. Destildar solo para planchas autoadhesivas.
    # Margen lateral minimo. Con menos, las impresoras hogareñas suelen
    # recortar el borde y se pierden las guias de corte.
    "etiqueta_margen_lateral_mm": 12,
    "etiqueta_pegadas":      True,
    "etiqueta_guias_corte":  True,   # marcas en los bordes para cortar derecho
    "etiqueta_espacio_mm":       0,      # espacio entre etiquetas (filas y columnas)
    "etiqueta_mostrar_barcode": True,
    "etiqueta_mostrar_promo":   True,
    "etiqueta_font_nombre":     18,      # pt — nombre del producto
    "etiqueta_font_label":       9,      # pt — label promo (LLEVANDO X)
    "etiqueta_font_precio":     22,      # pt — precio principal
    "etiqueta_font_secundario": 11,      # pt — precios secundarios
    "etiqueta_font_codigo":     12,      # pt — numero de codigo de barras

    # Sistema
    "backup_automatico":    True,
    "backup_max":           30,
    "logs_max":             10,
    "moneda_simbolo":       "$",
    "moneda_separador":     ",",

    # Balanza (peso por puerto serie — Systel Croma y compatibles)
    "balanza_activa":       False,
    "balanza_puerto":       "COM3",   # puerto serie donde está conectada
    "balanza_baudrate":     9600,
    "balanza_protocolo":    "systel_estable",  # ver balanza.py

    # Catálogo web (sincroniza precios a una Google Sheet, para el
    # formulario de pedidos de clientes)
    "catalogo_web_activo":  False,
    "catalogo_web_url":     "",  # URL de la Apps Script Web App (ver apps_script_catalogo.gs)
}


# ─────────────────────────────────────────────────────────────────────────────
# API
# ─────────────────────────────────────────────────────────────────────────────

def cargar() -> dict:
    """Carga la configuración desde archivo. Si no existe, usa defaults."""
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                guardado = json.load(f)
            # Merge: defaults + lo guardado (permite agregar nuevas claves)
            cfg = {**DEFAULTS, **guardado}
            return cfg
        except Exception as e:
            # Config corrupta: se vuelve a los defaults y el usuario pierde
            # TODOS sus ajustes sin enterarse. Tiene que quedar registrado.
            logging.warning(f"config.json ilegible ({e}). Se usan los valores "
                            f"por defecto: se pierden los ajustes guardados.")
    return dict(DEFAULTS)


def guardar(cfg: dict):
    """Persiste la configuración en archivo JSON."""
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def get(clave: str, default=None):
    """Obtiene un valor de configuración."""
    return cargar().get(clave, default)


_cfg = None


def set(clave: str, valor):
    """Actualiza un valor, lo persiste Y refresca la cache en memoria.

    Sin lo ultimo, cambiar un ajuste no tenia efecto hasta reiniciar el TPV:
    guardar() escribia el archivo pero cfg() seguia devolviendo la copia
    vieja que cargo al arrancar.
    """
    datos = cargar()
    datos[clave] = valor
    guardar(datos)
    if _cfg is not None:
        _cfg[clave] = valor   # se muta el dict, no hace falta global


def cfg() -> dict:
    """Retorna la configuración cacheada. Recargar con reload()."""
    global _cfg
    if _cfg is None:
        _cfg = cargar()
    return _cfg


def reload():
    """Fuerza recarga desde archivo."""
    global _cfg
    _cfg = cargar()

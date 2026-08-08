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
    "folleto_mostrar_codigo": False,     # incluir codigo/PLU en cada producto del folleto
    "folleto_titulo":       "OFERTAS INCREIBLES",  # texto grande del encabezado (editable, ej "OFERTAS DE FEBRERO")
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
    "stock_alerta_umbral":  5,           # unidades mínimas antes de alertar
    "stock_alerta_dias_vto": 7,          # días para alertar vencimientos

    # Aviso de vencimientos por email al abrir el TPV
    "vto_email_activo":        False,
    "vto_email_destinatario":  "",
    "vto_email_max_por_dia":   1,        # no repetir el aviso en el mismo día

    # Redondeo de precios de venta. 0 = sin redondeo.
    # 1 = al peso, 10 = a la decena, 50 y 100 = a esos múltiplos.
    # Siempre redondea PARA ARRIBA, para no comerse margen.
    "redondeo_precios":        0,

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


def set(clave: str, valor):
    """Actualiza un valor y lo persiste."""
    cfg = cargar()
    cfg[clave] = valor
    guardar(cfg)


# Instancia global cargada una vez
_cfg = None

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

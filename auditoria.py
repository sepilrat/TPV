"""
auditoria.py — Motor de reglas de auditoria de precios para TPV Arai.

Logica pura: NO importa tkinter y NO ejecuta SQL. Recibe listas de dicts y
devuelve Hallazgos. Toda la lectura de base va por repositorio.py (ver
docstring de auditar() para el contrato de datos que espera).

Uso tipico:

    from repositorio import productos_para_auditoria, descartes_auditoria
    import auditoria

    hallazgos = auditoria.auditar(
        productos_para_auditoria(),
        descartes_auditoria(),
    )
    for h in auditoria.ordenar(hallazgos):
        print(h.severidad, h.regla, h.descripcion_corta)
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from difflib import SequenceMatcher

# --------------------------------------------------------------------------
# Configuracion (override desde tpv_config.json -> seccion "auditoria")
# --------------------------------------------------------------------------

CONFIG_DEFAULT = {
    # R2: cuantos puntos porcentuales por debajo del margen objetivo se tolera
    "margen_tolerancia_pp": 5.0,
    # R2: si el producto no tiene margen objetivo ni lo hereda, se usa este
    "margen_objetivo_fallback": 30.0,
    # R3: dispersion maxima de precio dentro de un grupo homogeneo (%)
    "dispersion_max_pct": 8.0,
    # R3: minimo de productos en el grupo para que la regla aplique
    "dispersion_min_grupo": 2,
    # R4: cuanto mas caro por unidad base puede ser el formato grande (%)
    #     antes de considerarlo un error de carga
    "escala_tolerancia_pct": 3.0,
    # R5: similitud minima de descripcion para considerar dos productos
    #     variantes del mismo (0..1)
    "similitud_variantes": 0.72,
    # R5: diferencia de precio a partir de la cual se reporta (%)
    "variantes_dif_pct": 5.0,
}

SEVERIDADES = {"CRITICO": 0, "ALTO": 1, "REVISAR": 2}


# --------------------------------------------------------------------------
# Hallazgo
# --------------------------------------------------------------------------

@dataclass
class Hallazgo:
    regla: str
    severidad: str            # CRITICO | ALTO | REVISAR
    producto_id: int
    descripcion_corta: str
    detalle: str
    relacionados: list = field(default_factory=list)  # ids de otros productos
    sugerencia: str = ""

    @property
    def clave_descarte(self) -> str:
        """Identifica un hallazgo para poder silenciarlo de forma persistente."""
        return f"{self.regla}:{self.producto_id}"


# --------------------------------------------------------------------------
# Parseo de contenido (900cc, 500g, 1kg, 4x30, x 6 x 24g, 150 unidades...)
# --------------------------------------------------------------------------

_UNIDADES = {
    "g": ("g", 1.0), "gr": ("g", 1.0), "grs": ("g", 1.0), "gramos": ("g", 1.0),
    "kg": ("g", 1000.0), "kgs": ("g", 1000.0), "kilo": ("g", 1000.0),
    "ml": ("ml", 1.0), "cc": ("ml", 1.0), "cm3": ("ml", 1.0),
    "l": ("ml", 1000.0), "lt": ("ml", 1000.0), "lts": ("ml", 1000.0),
    "litro": ("ml", 1000.0), "litros": ("ml", 1000.0),
    "u": ("u", 1.0), "un": ("u", 1.0), "uni": ("u", 1.0), "unid": ("u", 1.0),
    "unidad": ("u", 1.0), "unidades": ("u", 1.0), "rollos": ("u", 1.0),
}

_ALIAS_UNIDADES = "|".join(sorted(_UNIDADES, key=len, reverse=True))

# "3x40", "4 x 30 m", "6 x 24 g"  -> packs (cantidad x contenido)
_RE_PACK = re.compile(
    r"(?<![\d,.])(\d{1,3})\s*[xX]\s*(\d{1,4})(?:[.,](\d+))?\s*(" + _ALIAS_UNIDADES + r")?\b"
)
# "900cc", "1 kg", "500 g", "150 unidades"
_RE_SIMPLE = re.compile(
    r"(?<![\d,.])(\d{1,4})(?:[.,](\d{1,3}))?\s*(" + _ALIAS_UNIDADES + r")\b",
    re.IGNORECASE,
)


def parse_contenido(descripcion: str):
    """Devuelve (cantidad_en_unidad_base, unidad_base) o (None, None).

    unidad_base es 'g', 'ml' o 'u'. Un pack de 4x30 unidades devuelve 120 u.
    Si no puede parsear con confianza devuelve (None, None) para que el
    producto quede marcado como pendiente de completar a mano.
    """
    if not descripcion:
        return (None, None)
    texto = descripcion.lower()

    m = _RE_PACK.search(texto)
    if m:
        packs = int(m.group(1))
        cant = float(m.group(2))
        if m.group(3):
            cant += float("0." + m.group(3))
        alias = m.group(4)
        if alias:
            base, factor = _UNIDADES[alias]
            return (packs * cant * factor, base)
        # "4x30" sin unidad: se asume cantidad de piezas
        return (float(packs * cant), "u")

    m = _RE_SIMPLE.search(texto)
    if m:
        cant = float(m.group(1))
        if m.group(2):
            cant += float("0." + m.group(2))
        base, factor = _UNIDADES[m.group(3).lower()]
        return (cant * factor, base)

    return (None, None)


def contenido_de(prod: dict):
    """Usa las columnas contenido_valor/contenido_unidad si existen; si no, parsea."""
    val = prod.get("contenido_valor")
    uni = prod.get("contenido_unidad")
    if val and uni and uni in _UNIDADES:
        base, factor = _UNIDADES[uni]
        return (float(val) * factor, base)
    return parse_contenido(prod.get("descripcion", ""))


def _precio_por_base(prod: dict):
    cant, base = contenido_de(prod)
    if not cant or not prod.get("precio_venta"):
        return (None, None)
    return (float(prod["precio_venta"]) / cant, base)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _norm(txt: str) -> str:
    txt = (txt or "").lower().strip()
    trans = str.maketrans("áéíóúàèìòùäëïöüñ", "aeiouaeiouaeioun")
    txt = txt.translate(trans)
    return re.sub(r"[^a-z0-9 ]+", " ", txt)


def _marca(prod: dict) -> str:
    return _norm(prod.get("marca", ""))


def _similitud(a: str, b: str) -> float:
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def _margen_real(prod: dict):
    costo = prod.get("ultimo_costo")
    precio = prod.get("precio_venta")
    if not costo or not precio or costo <= 0:
        return None
    return (float(precio) - float(costo)) / float(costo) * 100.0


def _margen_objetivo(prod: dict, cfg: dict) -> float:
    for k in ("margen_pct", "margen_categoria_pct"):
        v = prod.get(k)
        if v is not None:
            return float(v)
    return float(cfg["margen_objetivo_fallback"])


def _money(v) -> str:
    return f"${float(v):,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")


# --------------------------------------------------------------------------
# R1 - Precio por debajo del costo de reposicion
# --------------------------------------------------------------------------

def regla_precio_bajo_costo(productos, cfg):
    out = []
    for p in productos:
        costo, precio = p.get("ultimo_costo"), p.get("precio_venta")
        if not costo or not precio:
            continue
        if float(precio) < float(costo):
            perdida = float(costo) - float(precio)
            out.append(Hallazgo(
                regla="R1_bajo_costo",
                severidad="CRITICO",
                producto_id=p["id"],
                descripcion_corta=p["descripcion"],
                detalle=(f"Se vende a {_money(precio)} y reponerlo cuesta "
                         f"{_money(costo)}. Perdes {_money(perdida)} por unidad "
                         f"vendida, antes de impuestos y comisiones."),
                sugerencia=(f"Precio minimo para no perder: {_money(costo)}. "
                            f"Con margen objetivo: "
                            f"{_money(float(costo) * (1 + _margen_objetivo(p, cfg) / 100))}"),
            ))
    return out


# --------------------------------------------------------------------------
# R2 - Margen por debajo del objetivo
# --------------------------------------------------------------------------

def regla_margen_bajo(productos, cfg):
    out = []
    tol = float(cfg["margen_tolerancia_pp"])
    for p in productos:
        real = _margen_real(p)
        if real is None or real < 0:
            continue  # negativo lo agarra R1
        obj = _margen_objetivo(p, cfg)
        if real < obj - tol:
            costo = float(p["ultimo_costo"])
            out.append(Hallazgo(
                regla="R2_margen_bajo",
                severidad="ALTO",
                producto_id=p["id"],
                descripcion_corta=p["descripcion"],
                detalle=(f"Margen real {real:.1f}% contra un objetivo de "
                         f"{obj:.1f}%. Faltan {obj - real:.1f} puntos."),
                sugerencia=f"Precio para llegar al objetivo: {_money(costo * (1 + obj / 100))}",
            ))
    return out


# --------------------------------------------------------------------------
# R3 - Dispersion de precio dentro de un grupo homogeneo
# --------------------------------------------------------------------------

def _tipo(prod: dict) -> str:
    """Primer token significativo: 'fideos', 'arroz', 'harina', 'lavandina'...

    Evita que R3 compare productos distintos de la misma marca y tamano
    (arroz Marolio 1kg contra harina Marolio 1kg, por ejemplo).
    """
    marca_tokens = set(_marca(prod).split())
    for t in _norm(prod.get("descripcion", "")).split():
        if t.isdigit() or t in _UNIDADES or t in marca_tokens or len(t) < 3:
            continue
        if re.match(r"^\d", t):
            continue
        return t
    return ""


def regla_dispersion_grupo(productos, cfg):
    grupos = {}
    for p in productos:
        cant, base = contenido_de(p)
        if not cant or not p.get("precio_venta") or not _marca(p):
            continue
        clave = (_marca(p), p.get("categoria_id"), _tipo(p), base, round(cant, 2))
        grupos.setdefault(clave, []).append(p)

    out = []
    umbral = float(cfg["dispersion_max_pct"])
    minimo = int(cfg["dispersion_min_grupo"])
    for clave, miembros in grupos.items():
        if len(miembros) < minimo:
            continue
        precios = [float(m["precio_venta"]) for m in miembros]
        if min(precios) <= 0:
            continue
        spread = (max(precios) - min(precios)) / min(precios) * 100.0
        if spread <= umbral:
            continue
        mediana = statistics.median(precios)
        marca, _cat, _tip, base, cant = clave
        for m in miembros:
            precio = float(m["precio_venta"])
            desvio = (precio - mediana) / mediana * 100.0
            if abs(desvio) < umbral / 2:
                continue
            out.append(Hallazgo(
                regla="R3_dispersion",
                severidad="ALTO" if abs(desvio) > umbral else "REVISAR",
                producto_id=m["id"],
                descripcion_corta=m["descripcion"],
                detalle=(f"{marca.title()} {cant:g}{base}: {len(miembros)} productos "
                         f"del mismo formato con precios entre {_money(min(precios))} "
                         f"y {_money(max(precios))} (spread {spread:.1f}%). "
                         f"Este esta {desvio:+.1f}% contra la mediana."),
                relacionados=[x["id"] for x in miembros if x["id"] != m["id"]],
                sugerencia=f"Mediana del grupo: {_money(mediana)}",
            ))
    return out


# --------------------------------------------------------------------------
# R4 - Escala de tamano invertida / mismo precio distinto contenido
# --------------------------------------------------------------------------

def _familia(prod: dict) -> str:
    """Tokens de la descripcion sin numeros ni unidades, para agrupar formatos."""
    tokens = _norm(prod.get("descripcion", "")).split()
    limpio = [t for t in tokens
              if not t.isdigit() and t not in _UNIDADES and not re.match(r"^\d", t)]
    return " ".join(limpio[:4])


def regla_escala_invertida(productos, cfg):
    familias = {}
    for p in productos:
        cant, base = contenido_de(p)
        if not cant or not p.get("precio_venta") or not _marca(p):
            continue
        familias.setdefault((_marca(p), base, _familia(p)), []).append((cant, p))

    out = []
    tol = float(cfg["escala_tolerancia_pct"])
    for (marca, base, fam), items in familias.items():
        if len(items) < 2:
            continue
        items.sort(key=lambda t: t[0])
        for i in range(len(items) - 1):
            cant_chico, chico = items[i]
            cant_grande, grande = items[i + 1]
            if cant_grande <= cant_chico:
                continue
            p_chico = float(chico["precio_venta"])
            p_grande = float(grande["precio_venta"])

            if abs(p_grande - p_chico) < 0.01:
                out.append(Hallazgo(
                    regla="R4_mismo_precio",
                    severidad="ALTO",
                    producto_id=grande["id"],
                    descripcion_corta=grande["descripcion"],
                    detalle=(f"Mismo precio ({_money(p_grande)}) que "
                             f"'{chico['descripcion']}', que trae "
                             f"{cant_chico:g}{base} contra {cant_grande:g}{base}."),
                    relacionados=[chico["id"]],
                    sugerencia="Revisar cual de los dos quedo mal cargado.",
                ))
                continue

            unit_chico = p_chico / cant_chico
            unit_grande = p_grande / cant_grande
            if unit_grande > unit_chico * (1 + tol / 100):
                exceso = (unit_grande / unit_chico - 1) * 100
                esperado = unit_chico * cant_grande
                out.append(Hallazgo(
                    regla="R4_escala_invertida",
                    severidad="CRITICO" if exceso > 40 else "ALTO",
                    producto_id=grande["id"],
                    descripcion_corta=grande["descripcion"],
                    detalle=(f"El formato de {cant_grande:g}{base} sale "
                             f"{exceso:.1f}% mas caro por {base} que el de "
                             f"{cant_chico:g}{base} ('{chico['descripcion']}'). "
                             f"El formato grande nunca deberia ser mas caro por unidad."),
                    relacionados=[chico["id"]],
                    sugerencia=(f"A igual precio por {base} seria {_money(esperado)} "
                                f"o menos (hoy {_money(p_grande)})."),
                ))
    return out


# --------------------------------------------------------------------------
# R5 - Variantes del mismo producto con precios distintos
# --------------------------------------------------------------------------

def regla_variantes_dispares(productos, cfg):
    por_marca = {}
    for p in productos:
        if _marca(p) and p.get("precio_venta"):
            por_marca.setdefault(_marca(p), []).append(p)

    out, vistos = [], set()
    sim_min = float(cfg["similitud_variantes"])
    dif_min = float(cfg["variantes_dif_pct"])
    for marca, items in por_marca.items():
        for i, a in enumerate(items):
            cant_a, base_a = contenido_de(a)
            for b in items[i + 1:]:
                cant_b, base_b = contenido_de(b)
                # mismo contenido (o ambos sin parsear) y descripciones parecidas
                if base_a != base_b:
                    continue
                if cant_a and cant_b and abs(cant_a - cant_b) > 0.01:
                    continue
                if _similitud(a["descripcion"], b["descripcion"]) < sim_min:
                    continue
                pa, pb = float(a["precio_venta"]), float(b["precio_venta"])
                if min(pa, pb) <= 0:
                    continue
                dif = abs(pa - pb) / min(pa, pb) * 100
                if dif < dif_min:
                    continue
                par = tuple(sorted((a["id"], b["id"])))
                if par in vistos:
                    continue
                vistos.add(par)
                caro, barato = (a, b) if pa > pb else (b, a)
                cruza_cat = a.get("categoria_id") != b.get("categoria_id")
                out.append(Hallazgo(
                    regla="R5_variantes",
                    severidad="ALTO" if cruza_cat else "REVISAR",
                    producto_id=caro["id"],
                    descripcion_corta=caro["descripcion"],
                    detalle=(f"Misma marca y mismo contenido que "
                             f"'{barato['descripcion']}' pero {dif:.1f}% mas caro "
                             f"({_money(caro['precio_venta'])} contra "
                             f"{_money(barato['precio_venta'])})."
                             + (" Ademas estan en categorias distintas."
                                if cruza_cat else "")),
                    relacionados=[barato["id"]],
                    sugerencia="Unificar precio salvo que el costo sea realmente distinto.",
                ))
    return out


# --------------------------------------------------------------------------
# R6 - Alimento cargado en categoria no alimentaria
# --------------------------------------------------------------------------

_PALABRAS_ALIMENTO = (
    "yerba", "fideo", "tallarin", "mostachol", "spaguetti", "spaghetti", "codito",
    "dedalito", "caracol", "arroz", "harina", "azucar", "aceite", "vinagre",
    "galletita", "galletitas", "bizcocho", "magdalena", "pure", "tomate",
    "mermelada", "durazno", "arveja", "lenteja", "polenta", "pan rallado",
    "cafe", "te", "mate", "cacao", "leche", "queso", "atun", "pate", "picadillo",
    "mayonesa", "ketchup", "mostaza", "sal", "cereal",
    "alfajor", "chocolate", "oblea", "pepas", "surtido", "club social", "kesita",
)
_CATEGORIAS_NO_ALIMENTO = ("limpieza", "perfumeria", "cuidado personal",
                           "insecticida", "bazar", "textil", "hogar")


def regla_categoria_atipica(productos, cfg):
    out = []
    for p in productos:
        cat = _norm(p.get("categoria_nombre", ""))
        if not any(c in cat for c in _CATEGORIAS_NO_ALIMENTO):
            continue
        desc = _norm(p.get("descripcion", ""))
        golpes = [w for w in _PALABRAS_ALIMENTO
                  if re.search(r"\b" + re.escape(w.strip()) + r"\b", desc)]
        if not golpes:
            continue
        out.append(Hallazgo(
            regla="R6_categoria",
            severidad="REVISAR",
            producto_id=p["id"],
            descripcion_corta=p["descripcion"],
            detalle=(f"Parece un alimento ('{golpes[0].strip()}') pero esta "
                     f"cargado en la categoria '{p.get('categoria_nombre')}'."),
            sugerencia="Mover a la categoria de almacen correspondiente.",
        ))
    return out


# --------------------------------------------------------------------------
# Orquestador
# --------------------------------------------------------------------------

REGLAS = (
    regla_precio_bajo_costo,
    regla_margen_bajo,
    regla_dispersion_grupo,
    regla_escala_invertida,
    regla_variantes_dispares,
    regla_categoria_atipica,
)


def auditar(productos, descartes=(), config=None):
    """Corre todas las reglas y devuelve la lista de Hallazgos vigentes.

    productos: lista de dicts con estas claves (las opcionales pueden faltar
    o venir en None; las reglas que las necesiten se saltean solas):

        id                    int      obligatoria
        descripcion           str      obligatoria
        precio_venta          float    obligatoria
        marca                 str
        categoria_id          int
        categoria_nombre      str
        ultimo_costo          float    costo del ULTIMO lote ingresado,
                                       no el costo FIFO del lote en curso
        margen_pct            float    margen objetivo del producto
        margen_categoria_pct  float    margen objetivo heredado de la categoria
        contenido_valor       float    opcional, si no se parsea la descripcion
        contenido_unidad      str      'g' | 'kg' | 'ml' | 'l' | 'cc' | 'u'

    descartes: iterable de claves "regla:producto_id" ya revisadas y aceptadas.
    """
    cfg = dict(CONFIG_DEFAULT)
    if config:
        cfg.update({k: v for k, v in config.items() if k in CONFIG_DEFAULT})

    silenciados = set(descartes)
    hallazgos = []
    for regla in REGLAS:
        for h in regla(productos, cfg):
            if h.clave_descarte not in silenciados:
                hallazgos.append(h)
    return hallazgos


def ordenar(hallazgos):
    return sorted(hallazgos, key=lambda h: (SEVERIDADES.get(h.severidad, 9),
                                            h.regla, h.descripcion_corta))


def resumen(hallazgos):
    """Conteo por severidad, para el asunto del mail y el badge de la pestana."""
    r = {"CRITICO": 0, "ALTO": 0, "REVISAR": 0}
    for h in hallazgos:
        r[h.severidad] = r.get(h.severidad, 0) + 1
    return r


def sin_contenido(productos):
    """Productos cuyo contenido no se pudo parsear: R3 y R4 no los cubren."""
    return [p for p in productos if contenido_de(p) == (None, None)]

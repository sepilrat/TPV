"""
whatsapp_catalogo.py — Exportar catálogo en formato Meta (CSV) TPV v2.0

Genera el archivo CSV con las columnas exactas que pide Meta Commerce
Manager para subir/sincronizar un catálogo de productos, que después
se puede conectar a WhatsApp Business (WhatsApp Manager → Catalog
linking) para que el cliente navegue el catálogo y arme su pedido
directo desde el chat.

IMPORTANTE — dos limitaciones reales a tener en cuenta:
  1. Las fotos tienen que estar en una URL pública de internet.
     Las fotos guardadas LOCALMENTE (imagenes_productos/) no sirven
     acá, Meta no puede leer un archivo de tu compu. Si un producto
     no tiene foto en URL pública, esa columna queda vacía y Meta
     puede rechazar esa fila.
  2. Meta pide un campo "link" (a una página del producto) que no
     tenemos porque no hay sitio web — se usa la web del negocio si
     está cargada en Config, y si no, un link de WhatsApp al propio
     número como alternativa razonable.

La app gratuita de WhatsApp Business por sí sola NO importa este CSV
directamente — hay que crear un catálogo en Meta Commerce Manager
(business.facebook.com/commerce, gratis) subiendo este archivo, y
después conectarlo a tu cuenta de WhatsApp Business desde ahí.
"""

import os
import csv
import tempfile
import logging
from datetime import datetime

from config import cfg
from repositorio import get_productos
from etiquetas import _get_precios_producto
import imagenes


CAMPOS_META = [
    "id", "title", "description", "availability", "condition",
    "price", "link", "image_link", "brand",
]


def _link_generico(c_cfg: dict) -> str:
    web = (c_cfg.get("negocio_web") or "").strip()
    if web:
        return web if web.startswith("http") else f"https://{web}"
    tel = "".join(ch for ch in (c_cfg.get("negocio_telefono") or "") if ch.isdigit())
    if tel:
        if not tel.startswith("54"):
            tel = "54" + tel
        return f"https://wa.me/{tel}"
    return ""


def _etiqueta_tier(label: str, cantidad) -> str:
    """Convierte el label interno ('Llevando 6', 'Precio unitario') a
    algo más claro para el cliente en el catálogo ('Pack x6', 'Unidad')."""
    if label == "Precio unitario" or cantidad == 1:
        return "Unidad"
    return f"Pack x{int(cantidad)}"


def generar_csv_catalogo(productos: list[dict], ruta_salida: str = None) -> tuple[str, list[str]]:
    """
    Genera el CSV en formato Meta. Retorna (ruta_del_archivo,
    lista_de_avisos) — avisos son productos que van a quedar sin foto
    válida (URL local o sin foto) para que el usuario sepa cuáles
    revisar antes de subir el catálogo.

    IMPORTANTE sobre precios: el catálogo de Meta/WhatsApp solo admite
    UN precio por cada fila — no existe el concepto de "comprando más,
    pagás menos por unidad" que sí tenemos en el TPV (promociones por
    cantidad). Para no perder esa información, un producto CON
    escalas de precio (ej: unidad / pack x6 / pack x12) genera VARIAS
    filas en el catálogo, una por escala, cada una como si fuera un
    producto aparte (ej: "Coca Cola 1.5L — Unidad" $1900,
    "Coca Cola 1.5L — Pack x6" $1750 c/u) — así el cliente elige
    directamente la escala que le conviene, en vez de perderla.
    Un producto SIN escalas (precio único) genera una sola fila, igual
    que antes.
    """
    if not productos:
        return None, []

    if not ruta_salida:
        nombre = f"catalogo_whatsapp_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
        ruta_salida = os.path.join(tempfile.gettempdir(), nombre)

    c_cfg = cfg()
    link_generico = _link_generico(c_cfg)
    moneda = c_cfg.get("moneda_codigo_iso") or "ARS"

    avisos = []

    with open(ruta_salida, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CAMPOS_META)
        writer.writeheader()

        for p in productos:
            imagen_url = p.get("imagen_url") or ""
            if not imagen_url or not imagenes.es_url(imagen_url):
                avisos.append(p["descripcion"])
                imagen_url = ""

            nombre_prod = p["descripcion"]
            marca = p.get("marca") or ""
            if marca and marca.lower() not in nombre_prod.lower():
                nombre_prod = f"{marca} {nombre_prod}"

            base = {
                "availability": "in stock" if (p.get("stock") or 0) > 0 else "out of stock",
                "condition":    "new",
                "link":         link_generico,
                "image_link":   imagen_url,
                "brand":        p.get("marca") or c_cfg.get("negocio_nombre") or "",
            }

            precios = _get_precios_producto(p["id"], p["precio_base"])

            if len(precios) <= 1:
                writer.writerow({
                    **base,
                    "id":          p["codigo"],
                    "title":       nombre_prod[:150],
                    "description": p["descripcion"][:5000],
                    "price":       f"{p['precio_base']:.2f} {moneda}",
                })
            else:
                for tier in precios:
                    etiqueta = _etiqueta_tier(tier["label"], tier["cantidad"])
                    desc = p["descripcion"]
                    if tier["cantidad"] > 1:
                        desc += f" — Precio por pack de {int(tier['cantidad'])} unidades (c/u)"
                    writer.writerow({
                        **base,
                        "id":          f"{p['codigo']}-C{int(tier['cantidad'])}",
                        "title":       f"{nombre_prod} — {etiqueta}"[:150],
                        "description": desc[:5000],
                        "price":       f"{tier['precio']:.2f} {moneda}",
                    })

    return ruta_salida, avisos


# ─────────────────────────────────────────────────────────────────────────────
# SELECTOR (UI)
# ─────────────────────────────────────────────────────────────────────────────

def abrir_selector_catalogo_whatsapp(parent):
    """Diálogo para elegir qué productos incluir y generar el CSV."""
    import sys
    import tkinter as tk
    from tkinter import ttk, messagebox
    from styles import C, F, btn, lbl, card

    d = tk.Toplevel(parent)
    d.title("Exportar catálogo para WhatsApp/Meta")
    d.resizable(True, True)
    d.configure(bg=C.bg)
    d.grab_set()
    sw, sh = d.winfo_screenwidth(), d.winfo_screenheight()
    w, h = min(820, sw-60), min(600, sh-60)
    d.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
    d.columnconfigure(0, weight=1)
    d.rowconfigure(2, weight=1)

    hdr = tk.Frame(d, bg=C.bg)
    hdr.grid(row=0, column=0, sticky="ew", padx=12, pady=(12,4))
    lbl(hdr, "Exportar catálogo para WhatsApp/Meta", variante="titulo").pack(side="left")

    lbl(d, "Genera un CSV para subir a Meta Commerce Manager y conectarlo a tu "
          "WhatsApp Business. Las fotos guardadas localmente no se pueden usar "
          "acá — solo las que están como URL pública. Si un producto tiene "
          "varias escalas de precio (unidad/pack), se listan como productos "
          "separados para que el cliente elija la cantidad que le conviene.",
        variante="suave", wraplength=700, justify="left").grid(
        row=1, column=0, sticky="w", padx=12, pady=(0,6))

    bar = tk.Frame(d, bg=C.bg)
    bar.grid(row=2, column=0, sticky="ew", padx=12, pady=(0,6))
    lbl(bar, "Buscar:").pack(side="left", padx=(0,6))
    entry_buscar = tk.Entry(bar, font=F.normal, width=28,
                            bg=C.superficie, fg=C.texto, relief="solid", bd=1)
    entry_buscar.pack(side="left", ipady=5)

    COLS = [
        ("sel",    "",           30,  "center"),
        ("codigo", "Codigo",     90,  "w"),
        ("desc",   "Producto",  250,  "w"),
        ("precio", "Precio",     85,  "e"),
        ("foto",   "Foto URL",   70,  "center"),
    ]

    f_tabla = card(d)
    f_tabla.grid(row=3, column=0, sticky="nsew", padx=12, pady=(0,6))
    f_tabla.columnconfigure(0, weight=1)
    f_tabla.rowconfigure(0, weight=1)
    d.rowconfigure(3, weight=1)

    tree = ttk.Treeview(f_tabla, columns=[c[0] for c in COLS],
                       show="headings", selectmode="browse")
    for col_id, header, ancho, anchor in COLS:
        tree.heading(col_id, text=header, anchor="w")
        tree.column(col_id, width=ancho, anchor=anchor, minwidth=30)
    sb = ttk.Scrollbar(f_tabla, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=sb.set)
    tree.grid(row=0, column=0, sticky="nsew")
    sb.grid(row=0, column=1, sticky="ns")

    seleccionados = {}
    todos_prods   = {}

    def cargar(filtro=""):
        for r in tree.get_children():
            tree.delete(r)
        for p in get_productos(filtro=filtro):
            todos_prods[p["codigo"]] = p
            sel = "x" if p["codigo"] in seleccionados else ""
            foto_ok = "Sí" if (p.get("imagen_url") and imagenes.es_url(p["imagen_url"])) else "—"
            tree.insert("", "end", iid=p["codigo"], values=(
                sel, p["codigo"], p["descripcion"],
                f"$ {p['precio_base']:,.2f}", foto_ok,
            ))

    cargar()
    entry_buscar.bind("<KeyRelease>",
                      lambda e: cargar(entry_buscar.get().strip()))

    def _on_click(event):
        iid = tree.identify_row(event.y)
        col = tree.identify_column(event.x)
        if not iid or col != "#1":
            return
        if iid in seleccionados:
            del seleccionados[iid]
            tree.set(iid, "sel", "")
        else:
            seleccionados[iid] = True
            tree.set(iid, "sel", "x")
        _actualizar_lbl()

    tree.bind("<ButtonRelease-1>", _on_click)

    bot = tk.Frame(d, bg=C.bg)
    bot.grid(row=4, column=0, sticky="ew", padx=12, pady=(0,12))

    lbl_sel = lbl(bot, "Ninguno seleccionado", variante="suave")
    lbl_sel.pack(side="left")

    def _actualizar_lbl():
        n = len(seleccionados)
        lbl_sel.config(text=f"{n} producto{'s' if n != 1 else ''} seleccionado{'s' if n != 1 else ''}"
                      if n else "Ninguno seleccionado")

    def _sel_todo():
        for iid in tree.get_children():
            seleccionados[iid] = True
            tree.set(iid, "sel", "x")
        _actualizar_lbl()

    def _desel_todo():
        seleccionados.clear()
        for iid in tree.get_children():
            tree.set(iid, "sel", "")
        _actualizar_lbl()

    btn(bot, "Todo", variante="neutro", comando=_sel_todo).pack(side="left", padx=(12,4))
    btn(bot, "Nada", variante="neutro", comando=_desel_todo).pack(side="left")

    def generar():
        if not seleccionados:
            messagebox.showinfo("Atencion",
                "Selecciona al menos un producto.", parent=d)
            return
        prods = [todos_prods[cod] for cod in seleccionados if cod in todos_prods]

        d.config(cursor="wait")
        d.update()
        ruta, avisos = generar_csv_catalogo(prods)
        d.config(cursor="")

        if ruta:
            if sys.platform == "win32":
                os.startfile(ruta)
            msg = f"CSV generado y abierto.\n{ruta}"
            if avisos:
                listado = "\n".join(f"  • {n}" for n in avisos[:10])
                extra = f"\n  ... y {len(avisos)-10} más" if len(avisos) > 10 else ""
                msg += (f"\n\n⚠️ {len(avisos)} producto(s) sin foto pública "
                       f"(quedan sin imagen en el catálogo):\n{listado}{extra}")
            messagebox.showinfo("Listo", msg, parent=d)
            d.destroy()
        else:
            messagebox.showerror("Error", "No se pudo generar el archivo.", parent=d)

    btn(bot, "📱 Generar CSV", variante="exito",
        comando=generar).pack(side="right")
    btn(bot, "Cancelar", variante="neutro",
        comando=d.destroy).pack(side="right", padx=(0,8))

"""
auditoria_ui.py — Solapas "Auditoria" y "Ofertas" del grupo Productos.

Sigue la convencion del resto de los modulos del TPV:
    class XxxUI(ttk.Frame) con __init__(self, parent, app) y refrescar().
Se registran en main.py dentro de _construir_subtabs_productos().

Auditoria: corre auditoria.py contra el catalogo y lista los problemas de
precio (bajo costo, margen flojo, dispersion, escala invertida, variantes
dispares, categoria equivocada).

Ofertas: levanta folletos de mayoristas (PDF o foto) desde una carpeta y
cruza los precios contra el catalogo propio. Nada se guarda sin confirmar.
"""

import os
import re
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from styles import C, F, lbl, btn
import auditoria
import repositorio_auditoria as repo_aud

try:
    import fuentes
    HAY_FUENTES = True
except Exception:
    HAY_FUENTES = False

try:
    import folletos
    HAY_FOLLETOS, ERROR_FOLLETOS = True, ""
except Exception as _e:
    HAY_FOLLETOS, ERROR_FOLLETOS = False, f"{type(_e).__name__}: {_e}"


COLOR_SEV = {"CRITICO": "#FEE2E2", "ALTO": "#FEF3C7", "REVISAR": "#F3F4F6"}
_RE_PRECIO_SUG = re.compile(r"\$\s?([\d.]+,\d{2})")


# ══════════════════════════════════════════════════════════════════════════
# Solapa Auditoria
# ══════════════════════════════════════════════════════════════════════════

class AuditoriaUI(ttk.Frame):

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.hallazgos = []
        self._construir()
        self.after(150, self.refrescar)

    def _construir(self):
        cab = tk.Frame(self, bg=C.bg)
        cab.pack(fill="x", padx=12, pady=(10, 6))

        lbl(cab, "Auditoria de precios", variante="titulo").pack(side="left")
        self.lbl_resumen = lbl(cab, "", variante="subtitulo")
        self.lbl_resumen.pack(side="right")

        barra = tk.Frame(self, bg=C.bg)
        barra.pack(fill="x", padx=12, pady=(0, 8))
        btn(barra, "Actualizar", comando=self.refrescar).pack(side="left")
        btn(barra, "Aplicar precio sugerido", variante="exito",
            comando=self._aplicar).pack(side="left", padx=6)
        btn(barra, "No avisar mas", variante="neutro",
            comando=self._descartar).pack(side="left")

        lbl(barra, "Ver:", variante="suave").pack(side="left", padx=(18, 4))
        self.filtro = tk.StringVar(value="TODOS")
        cb = ttk.Combobox(barra, textvariable=self.filtro, width=10, state="readonly",
                          values=("TODOS", "CRITICO", "ALTO", "REVISAR"))
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda e: self._pintar())

        cont = tk.Frame(self, bg=C.bg)
        cont.pack(fill="both", expand=True, padx=12, pady=(0, 10))

        cols = ("sev", "producto", "detalle", "sugerencia")
        self.tree = ttk.Treeview(cont, columns=cols, show="headings")
        for c_, t_, w_ in (("sev", "Severidad", 90), ("producto", "Producto", 250),
                           ("detalle", "Que pasa", 560), ("sugerencia", "Sugerencia", 250)):
            self.tree.heading(c_, text=t_)
            self.tree.column(c_, width=w_, anchor="w")
        for sev, color in COLOR_SEV.items():
            self.tree.tag_configure(sev, background=color)

        sb = ttk.Scrollbar(cont, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda e: self._detalle())

        self.lbl_pie = lbl(self, "", variante="suave")
        self.lbl_pie.pack(fill="x", padx=12, pady=(0, 8))

    # ── datos ──────────────────────────────────────────────────────────────

    def refrescar(self):
        try:
            productos = repo_aud.get_productos_auditoria()
            descartes = repo_aud.get_descartes()
        except Exception as exc:
            messagebox.showerror("Auditoria", f"No se pudo leer el catalogo:\n{exc}")
            return
        self.hallazgos = auditoria.ordenar(auditoria.auditar(productos, descartes))
        sin_costo = sum(1 for p in productos if not p.get("ultimo_costo"))
        sin_cont = len(auditoria.sin_contenido(productos))
        self.lbl_pie.config(
            text=(f"{len(productos)} productos analizados   ·   "
                  f"{sin_costo} sin costo cargado (no entran en las reglas de margen)   ·   "
                  f"{sin_cont} sin contenido reconocible (no entran en las de tamano)"))
        self._pintar()

    def _pintar(self):
        self.tree.delete(*self.tree.get_children())
        f = self.filtro.get()
        for i, h in enumerate(self.hallazgos):
            if f != "TODOS" and h.severidad != f:
                continue
            self.tree.insert("", "end", iid=str(i), tags=(h.severidad,),
                             values=(h.severidad, h.descripcion_corta,
                                     h.detalle, h.sugerencia))
        r = auditoria.resumen(self.hallazgos)
        self.lbl_resumen.config(
            text=f"{r['CRITICO']} criticos   ·   {r['ALTO']} altos   ·   {r['REVISAR']} a revisar")

    def _sel(self):
        s = self.tree.selection()
        return self.hallazgos[int(s[0])] if s else None

    def _detalle(self):
        h = self._sel()
        if h:
            messagebox.showinfo(h.descripcion_corta,
                                f"{h.severidad} — {h.regla}\n\n{h.detalle}\n\n{h.sugerencia}")

    def _aplicar(self):
        h = self._sel()
        if not h:
            messagebox.showinfo("Auditoria", "Elegi una fila primero.")
            return
        m = _RE_PRECIO_SUG.search(h.sugerencia or "")
        if not m:
            messagebox.showinfo("Auditoria",
                                "Este hallazgo no propone un precio concreto.\n"
                                "Corregilo desde Productos > Precios.")
            return
        nuevo = float(m.group(1).replace(".", "").replace(",", "."))
        if not messagebox.askyesno("Aplicar precio",
                                   f"{h.descripcion_corta}\n\nNuevo precio: ${nuevo:,.2f}\n\n"
                                   "Se actualiza precio_base. El costo y el margen no se tocan."):
            return
        try:
            repo_aud.actualizar_precio_base(h.producto_id, nuevo)
        except Exception as exc:
            messagebox.showerror("Auditoria", f"No se pudo guardar:\n{exc}")
            return
        self.refrescar()
        m_prec = getattr(self.app, "modulos", {}).get("Precios")
        if m_prec and hasattr(m_prec, "refrescar"):
            m_prec.refrescar()

    def _descartar(self):
        h = self._sel()
        if not h:
            return
        if messagebox.askyesno("No avisar mas",
                               f"Dejar de avisar sobre:\n\n{h.descripcion_corta}\n({h.regla})"):
            repo_aud.guardar_descarte(h.clave_descarte, "revisado desde la solapa")
            self.refrescar()


# ══════════════════════════════════════════════════════════════════════════
# Solapa Ofertas (folletos de mayoristas)
# ══════════════════════════════════════════════════════════════════════════

class OfertasUI(ttk.Frame):

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.items = []
        self._omitidos = 0
        self._acumulado = {}   # producto_id -> [(fuente, archivo, precio)]
        self._productos = []
        self._construir()

    def _construir(self):
        cab = tk.Frame(self, bg=C.bg)
        cab.pack(fill="x", padx=12, pady=(10, 6))
        lbl(cab, "Ofertas de mayoristas", variante="titulo").pack(side="left")
        lbl(cab, "  El precio del folleto se compara contra tu costo, no contra tu precio de venta",
            variante="suave").pack(side="left", padx=8)
        self.lbl_estado = tk.Label(self, text="Elegi la carpeta donde dejas los folletos.",
                                   font=F.normal, bg=C.acento, fg=C.texto,
                                   anchor="w", padx=12, pady=6)
        self.lbl_estado.pack(fill="x", padx=12, pady=(0, 6))

        if not HAY_FOLLETOS:
            aviso = tk.Frame(self, bg=C.err_flash, padx=16, pady=16)
            aviso.pack(fill="x", padx=12, pady=10)
            tk.Label(aviso, justify="left", bg=C.err_flash, fg=C.peligro, font=F.normal,
                     text=("No se pudo cargar el lector de folletos.\n\n"
                           f"  {ERROR_FOLLETOS}\n\n"
                           "Para leer PDFs hace falta PyMuPDF:\n"
                           "    uv pip install pymupdf")).pack(anchor="w")
            return

        barra = tk.Frame(self, bg=C.bg)
        barra.pack(fill="x", padx=12, pady=(0, 8))
        lbl(barra, "Carpeta:", variante="suave").pack(side="left")
        self.carpeta = tk.StringVar()
        tk.Entry(barra, textvariable=self.carpeta, width=52, font=F.normal,
                 bg=C.superficie, fg=C.texto, relief="solid", bd=1).pack(side="left", padx=6)
        btn(barra, "Elegir...", variante="neutro", comando=self._elegir).pack(side="left")
        btn(barra, "Buscar nuevos", comando=self._listar).pack(side="left", padx=6)

        barra2 = tk.Frame(self, bg=C.bg)
        barra2.pack(fill="x", padx=12, pady=(0, 8))
        lbl(barra2, "Link:", variante="suave").pack(side="left")
        self.url = tk.StringVar()
        e_url = tk.Entry(barra2, textvariable=self.url, width=52, font=F.normal,
                         bg=C.superficie, fg=C.texto, relief="solid", bd=1)
        e_url.pack(side="left", padx=6)
        e_url.bind("<Return>", lambda ev: self._bajar_url())
        btn(barra2, "Descargar", comando=self._bajar_url).pack(side="left")
        btn(barra2, "Traer folletos de Vital", variante="neutro",
            comando=self._folletos_vital).pack(side="left", padx=6)
        lbl(barra2, "Sucursal:", variante="suave").pack(side="left", padx=(10, 4))
        self.sucursal = tk.StringVar(value="Moreno")
        ttk.Combobox(barra2, textvariable=self.sucursal, width=16, state="readonly",
                     values=fuentes.SUCURSALES_VITAL if HAY_FUENTES else ("Moreno",)
                     ).pack(side="left")

        cont = tk.Frame(self, bg=C.bg)
        cont.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        izq = tk.Frame(cont, bg=C.bg)
        izq.pack(side="left", fill="y")
        lbl(izq, "Folletos en la carpeta", variante="subtitulo").pack(anchor="w")

        # Los botones van ANTES que la lista: asi quedan siempre visibles
        # aunque la lista crezca. (Antes se iban abajo de la pantalla.)
        btn(izq, "Comparar TODOS los folletos", variante="exito",
            comando=self._analizar_todos).pack(fill="x", pady=(4, 2))
        btn(izq, "Analizar solo el seleccionado", variante="neutro",
            comando=self._analizar).pack(fill="x", pady=2)
        btn(izq, "Diagnosticar seleccionado", variante="neutro",
            comando=self._diagnosticar).pack(fill="x", pady=(2, 6))

        self.lista = tk.Listbox(izq, width=32, height=10, font=F.normal,
                                selectmode="extended", bg=C.superficie,
                                fg=C.texto, relief="solid", bd=1)
        self.lista.pack(fill="both", expand=True)

        der = tk.Frame(cont, bg=C.bg)
        der.pack(side="left", fill="both", expand=True, padx=(12, 0))
        enc = tk.Frame(der, bg=C.bg)
        enc.pack(fill="x")
        lbl(enc, "Precios detectados", variante="subtitulo").pack(side="left")
        self.vista = tk.StringVar(value="Por folleto")
        cbv = ttk.Combobox(enc, textvariable=self.vista, width=22, state="readonly",
                           values=("Por folleto", "Comparar mayoristas"))
        cbv.pack(side="right")
        cbv.bind("<<ComboboxSelected>>", lambda e: self._repintar())
        self.tree = ttk.Treeview(der, show="headings")
        self._cols_folleto()
        self.tree.tag_configure("conviene", background=C.ok_flash)
        self.tree.tag_configure("caro", background=C.err_flash)
        self.tree.tag_configure("sincosto", background=C.acento)
        sb = ttk.Scrollbar(der, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True, pady=4)
        sb.pack(side="right", fill="y")


    def _estado(self, texto, tipo="info"):
        colores = {"info": (C.acento, C.texto), "ok": (C.ok_flash, C.texto),
                   "error": (C.err_flash, C.peligro), "trabajando": (C.advertencia, C.blanco)}
        bg, fg = colores.get(tipo, colores["info"])
        self.lbl_estado.config(text=texto, bg=bg, fg=fg)

    def refrescar(self):
        if HAY_FOLLETOS and self.carpeta.get():
            self._listar()

    def _elegir(self):
        d = filedialog.askdirectory(title="Carpeta de folletos de ofertas")
        if d:
            self.carpeta.set(d)
            self._listar()

    def _listar(self):
        self.lista.delete(0, "end")
        for ruta in folletos.listar_pendientes(self.carpeta.get()):
            self.lista.insert("end", os.path.basename(ruta))
        self._estado(f"{self.lista.size()} folleto(s) en la carpeta.")

    def _ruta(self):
        s = self.lista.curselection()
        if not s:
            messagebox.showinfo("Ofertas", "Elegi un folleto de la lista.")
            return None
        return os.path.join(self.carpeta.get(), self.lista.get(s[0]))

    def _analizar(self):
        ruta = self._ruta()
        if not ruta:
            return
        faltan = folletos.requisitos_de(ruta)
        if faltan:
            self._estado("Falta software para leer este archivo.", "error")
            messagebox.showerror(
                "Ofertas",
                f"Para leer {os.path.basename(ruta)} falta:\n\n  - "
                + "\n\n  - ".join(faltan))
            return
        self._estado("Analizando... si necesita OCR puede tardar un rato.", "trabajando")
        threading.Thread(target=self._trabajo, args=(ruta,), daemon=True).start()

    def _trabajo(self, ruta):
        try:
            self._productos = repo_aud.get_productos_auditoria()
            items, info = folletos.analizar(ruta)
            for it in items:
                cand = _emparejar(it, self._productos)
                if cand:
                    it.producto_id, it.similitud = cand[0]["id"], cand[1]
                    it.crudo = [cand[0]]
        except Exception as exc:
            msg = f"{type(exc).__name__}: {exc}"
            self.after(0, lambda m=msg: messagebox.showerror("Ofertas", m))
            self.after(0, lambda: self._estado("Fallo el analisis.", "error"))
            return
        self.after(0, lambda: self._mostrar(items, info))

    def _mostrar(self, items, info):
        self.items = items
        self.vista.set("Por folleto")
        self._pintar_folleto(items)
        self._pie_folleto(items, info)

    _COLS_FOLLETO = (("oferta", "Oferta (lo que pago)", 130),
                     ("folleto", "Descripcion en el folleto", 250),
                     ("propio", "Mi producto", 220),
                     ("costo", "Mi costo hoy", 105),
                     ("ahorro", "Ahorro", 85),
                     ("precio", "Mi precio", 100),
                     ("margen", "Margen si compro", 120))

    def _cols_folleto(self):
        self.tree.configure(columns=[c for c, _t, _w in self._COLS_FOLLETO])
        for c_, t_, w_ in self._COLS_FOLLETO:
            self.tree.heading(c_, text=t_)
            self.tree.column(c_, width=w_, anchor="w")

    def _pintar_folleto(self, items):
        self._cols_folleto()
        self.tree.delete(*self.tree.get_children())
        conviene = sin_costo = 0

        for it in items:
            if not it.producto_id:
                self.tree.insert("", "end", values=(
                    f"${it.precio:,.2f}", it.descripcion[:70],
                    "— sin coincidencia —", "", "", "", ""))
                continue

            p = it.crudo[0]
            costo = float(p.get("ultimo_costo") or 0)
            precio = float(p.get("precio_venta") or 0)

            # El precio del folleto es un COSTO: lo que pagarias por reponer.
            if costo > 0:
                delta = (it.precio / costo - 1) * 100
                ahorro = f"{-delta:+.0f}%"
                tag = "conviene" if delta < -1 else ("caro" if delta > 1 else "")
                if delta < -1:
                    conviene += 1
                costo_txt = f"${costo:,.2f}"
            else:
                ahorro, tag, costo_txt = "—", "sincosto", "sin costo"
                sin_costo += 1

            # Margen que te quedaria comprando a ese precio de folleto
            margen = (f"{(precio / it.precio - 1) * 100:+.1f}%"
                      if precio and it.precio else "")

            self.tree.insert("", "end", tags=(tag,), values=(
                f"${it.precio:,.2f}", it.descripcion[:70], p["descripcion"][:60],
                costo_txt, ahorro, f"${precio:,.2f}" if precio else "", margen))

    def _pie_folleto(self, items, info):
        conviene = sum(1 for i in items if i.producto_id and i.crudo
                       and float(i.crudo[0].get("ultimo_costo") or 0) > i.precio)
        sin_costo = sum(1 for i in items if i.producto_id and i.crudo
                        and not i.crudo[0].get("ultimo_costo"))
        cruzan = sum(1 for i in items if i.producto_id)
        extra = f" · {conviene} mas baratos que tu costo actual" if conviene else ""
        extra += f" · {sin_costo} sin costo cargado para comparar" if sin_costo else ""
        self._estado(
            (f"{info['items']} precios detectados por {info['metodo']} en "
                  f"{info['paginas']} pagina(s) · {cruzan} cruzan con tu catalogo"
                  f"{extra} · nada se guardo todavia"))

    def _separar_legibles(self, rutas):
        """Divide en (se pueden leer, no se pueden) segun lo instalado.

        Por archivo, no por lote: que falte Tesseract bloquea las imagenes
        pero no los PDFs, y viceversa.
        """
        ok, bloqueados = [], []
        for r in rutas:
            faltan = folletos.requisitos_de(r)
            (ok if not faltan else bloqueados).append(
                r if not faltan else (r, faltan))
        return ok, bloqueados

    def _analizar_todos(self):
        rutas = folletos.listar_pendientes(self.carpeta.get())
        if not rutas:
            self._estado("No hay folletos en la carpeta.", "error")
            messagebox.showinfo("Ofertas",
                                f"No hay folletos en:\n{self.carpeta.get() or '(sin carpeta)'}\n\n"
                                "Se aceptan .pdf, .jpg, .png y .webp.")
            return

        legibles, bloqueados = self._separar_legibles(rutas)

        if not legibles:
            motivos = sorted({m for _r, ms in bloqueados for m in ms})
            self._estado("No hay nada que se pueda leer con lo que esta instalado.",
                         "error")
            messagebox.showerror(
                "Ofertas",
                f"Ninguno de los {len(rutas)} archivos se puede leer todavia.\n\n"
                "Falta:\n\n  - " + "\n\n  - ".join(motivos))
            return

        if bloqueados:
            nombres = ", ".join(os.path.basename(r) for r, _ in bloqueados[:4])
            messagebox.showwarning(
                "Ofertas",
                f"Se van a leer {len(legibles)} de {len(rutas)} archivos.\n\n"
                f"Quedan afuera por falta de OCR: {nombres}\n\n"
                + bloqueados[0][1][0])

        rutas = legibles
        self._acumulado = {}
        self.items = []
        self.vista.set("Comparar mayoristas")
        self._estado(f"Analizando {len(rutas)} folleto(s)... esto puede tardar.", "trabajando")
        self._omitidos = len(bloqueados)
        threading.Thread(target=self._trabajo_todos, args=(rutas,), daemon=True).start()

    def _trabajo_todos(self, rutas):
        try:
            self._productos = repo_aud.get_productos_auditoria()
        except Exception as exc:
            msg = f"No se pudo leer el catalogo:\n\n{type(exc).__name__}: {exc}"
            self.after(0, lambda m=msg: messagebox.showerror("Ofertas", m))
            self.after(0, lambda: self._estado("No se pudo leer el catalogo.", "error"))
            return
        todos, errores, leidos = [], [], 0
        for ruta in rutas:
            nombre = os.path.basename(ruta)
            self.after(0, lambda n=nombre: self._estado(f"Leyendo {n}...", "trabajando"))
            try:
                items, _info = folletos.analizar(ruta)
            except Exception as exc:
                errores.append(f"{nombre}: {exc}")
                continue
            leidos += 1
            for it in items:
                cand = _emparejar(it, self._productos)
                if cand:
                    it.producto_id, it.similitud = cand[0]["id"], cand[1]
                    it.crudo = [cand[0]]
                    self._acumulado.setdefault(it.producto_id, []).append(
                        (it.fuente, it.archivo, it.precio))
            todos.extend(items)
        self.after(0, lambda: self._fin_todos(todos, leidos, len(rutas), errores))

    def _fin_todos(self, items, leidos, total, errores):
        self.items = items
        self._repintar()

        if leidos == 0:
            self._estado(f"No se pudo leer ninguno de los {total} folletos.", "error")
            messagebox.showerror(
                "Ofertas",
                f"No se pudo leer ninguno de los {total} folletos.\n\nMotivos:\n\n  - "
                + "\n  - ".join(errores[:6]))
            return

        if not self._acumulado:
            self._estado(f"{leidos} de {total} folletos leidos · {len(items)} precios "
                         f"detectados · NINGUNO coincide con productos de tu catalogo.",
                         "error")
            messagebox.showinfo(
                "Ofertas",
                f"Se leyeron {len(items)} precios pero ninguno cruzo con tu catalogo.\n\n"
                "Suele pasar cuando las descripciones del folleto y las tuyas son muy "
                "distintas, o cuando el folleto es de rubros que no vendes.\n\n"
                "Pasa a la vista 'Por folleto' para ver que se detecto.")
            return

        txt = (f"{leidos} de {total} folletos leidos · {len(items)} precios · "
               f"{len(self._acumulado)} productos tuyos con al menos una oferta")
        if errores:
            txt += "  |  fallaron: " + "; ".join(e.split(":")[0] for e in errores[:3])
        self._estado(txt, "ok")

    def _repintar(self):
        if self.vista.get().startswith("Comparar") and self._acumulado:
            self._pintar_comparativa()
        elif self.items:
            self._pintar_folleto(self.items)

    # ── Vista comparativa entre mayoristas ────────────────────────────────

    def _pintar_comparativa(self):
        for c_ in self.tree["columns"]:
            self.tree.heading(c_, text="")
        cols = ("producto", "costo", "mejor", "fuente", "ahorro", "resto", "n")
        self.tree.configure(columns=cols)
        for c_, t_, w_ in (("producto", "Mi producto", 240),
                           ("costo", "Mi costo hoy", 105),
                           ("mejor", "Mejor oferta", 110),
                           ("fuente", "Donde", 190),
                           ("ahorro", "Ahorro", 85),
                           ("resto", "Otras ofertas", 190),
                           ("n", "Fuentes", 70)):
            self.tree.heading(c_, text=t_)
            self.tree.column(c_, width=w_, anchor="w")
        self.tree.delete(*self.tree.get_children())

        por_id = {p["id"]: p for p in self._productos}
        filas = []
        for pid, ofertas in self._acumulado.items():
            p = por_id.get(pid)
            if not p:
                continue
            ofertas = sorted(ofertas, key=lambda t: t[2])
            fuente, archivo, mejor = ofertas[0]
            costo = float(p.get("ultimo_costo") or 0)
            delta = (mejor / costo - 1) * 100 if costo > 0 else None
            filas.append((delta if delta is not None else 999, p, ofertas, costo, mejor,
                          fuente, archivo))
        filas.sort(key=lambda t: t[0])   # lo que mas conviene, primero

        for delta, p, ofertas, costo, mejor, fuente, archivo in filas:
            resto = "  ·  ".join(f"{f or '?'} ${pr:,.0f}" for f, _a, pr in ofertas[1:3])
            if costo > 0:
                ahorro, tag = f"{-delta:+.0f}%", ("conviene" if delta < -1 else
                                                  ("caro" if delta > 1 else ""))
                costo_txt = f"${costo:,.2f}"
            else:
                ahorro, tag, costo_txt = "—", "sincosto", "sin costo"
            donde = f"{fuente or '?'} · {archivo[:22]}"
            self.tree.insert("", "end", tags=(tag,), values=(
                p["descripcion"][:60], costo_txt, f"${mejor:,.2f}", donde,
                ahorro, resto, len(ofertas)))

    # ── Descarga ───────────────────────────────────────────────────────────

    def _carpeta_o_pedir(self):
        """La carpeta destino. Si no hay ninguna elegida, la pide."""
        if self.carpeta.get():
            return self.carpeta.get()
        d = filedialog.askdirectory(title="Donde guardar los folletos descargados")
        if d:
            self.carpeta.set(d)
        return d or None

    def _bajar_url(self, url=None, titulo=""):
        if not HAY_FUENTES:
            messagebox.showerror("Ofertas", "No se pudo cargar fuentes.py")
            return
        url = (url or self.url.get()).strip()
        if not url.lower().startswith(("http://", "https://")):
            messagebox.showinfo("Ofertas",
                                "Pega el link directo al PDF o a la imagen.\n\n"
                                "En la pagina de Vital es el boton 'Descargar' de "
                                "cada folleto: boton derecho, copiar direccion.")
            return
        carpeta = self._carpeta_o_pedir()
        if not carpeta:
            return
        self._estado(f"Descargando {url[:70]}...", "trabajando")
        threading.Thread(target=self._bajar_trabajo,
                         args=(url, carpeta, titulo), daemon=True).start()

    def _bajar_trabajo(self, url, carpeta, titulo):
        try:
            nombre = ""
            if titulo:
                nombre = re.sub(r"[^\w.\- ]+", "_", titulo)[:60] + ".pdf"
            ruta = fuentes.descargar_archivo(url, carpeta, nombre)
        except Exception as exc:
            msg = (f"No se pudo descargar:\n\n{type(exc).__name__}: {exc}\n\n"
                   "Si falla, bajalo con el navegador y dejalo en la carpeta.")
            self.after(0, lambda m=msg: messagebox.showerror("Ofertas", m))
            self.after(0, lambda: self._estado("Fallo la descarga.", "error"))
            return
        self.after(0, lambda: self._tras_bajar(ruta))

    def _tras_bajar(self, ruta):
        self.url.set("")
        self._listar()
        nombre = os.path.basename(ruta)
        for i in range(self.lista.size()):
            if self.lista.get(i) == nombre:
                self.lista.selection_clear(0, "end")
                self.lista.selection_set(i)
                self.lista.see(i)
                break
        self._estado(f"Descargado: {nombre} — dale a Comparar TODOS.", "ok")

    def _folletos_vital(self):
        if not HAY_FUENTES:
            return
        if not self._carpeta_o_pedir():
            return
        self._estado("Consultando la pagina de ofertas de Vital...", "trabajando")
        threading.Thread(target=self._vital_trabajo, daemon=True).start()

    def _vital_trabajo(self):
        try:
            items = fuentes.listar_folletos_vital(self.sucursal.get())
            if not items:
                raise ValueError("La pagina respondio pero no se encontro ningun PDF. "
                                 "Puede que hayan cambiado el HTML.")
        except Exception as exc:
            detalle = f"{type(exc).__name__}: {exc}"
            self.after(0, lambda d=detalle: self._vital_fallback(d))
            return
        self.after(0, lambda: self._elegir_vital(items))

    def _vital_fallback(self, detalle):
        """Si la descarga automatica falla, abrir el navegador es el plan B."""
        self._estado("No se pudo consultar Vital automaticamente.", "error")
        abrir = messagebox.askyesno(
            "Ofertas",
            f"No se pudo leer la pagina de Vital.\n\n{detalle}\n\n"
            "Suele pasar si el sitio bloquea pedidos automaticos.\n\n"
            "Plan B: te abro la pagina en el navegador. Ahi hace boton derecho "
            "sobre 'Descargar' de cada folleto, 'Copiar direccion del enlace', "
            "y pegalo en el campo Link.\n\n"
            "Abrir la pagina ahora?")
        if abrir:
            import webbrowser
            webbrowser.open(fuentes.VITAL_OFERTAS)

    def _elegir_vital(self, items):
        if not items:
            messagebox.showinfo("Ofertas", "No se encontraron folletos en la pagina.")
            return
        win = tk.Toplevel(self)
        win.title(f"Folletos de Vital — {self.sucursal.get()}")
        win.configure(bg=C.bg)
        lbl(win, f"{len(items)} folletos publicados", variante="subtitulo").pack(
            anchor="w", padx=14, pady=(12, 2))
        lbl(win, "Elegi cuales bajar (Ctrl para varios)", variante="suave").pack(
            anchor="w", padx=14)
        box = tk.Listbox(win, width=64, height=min(12, len(items)),
                         selectmode="extended", font=F.normal,
                         bg=C.superficie, fg=C.texto, relief="solid", bd=1)
        for titulo, _ in items:
            box.insert("end", titulo)
        box.pack(fill="both", expand=True, padx=14, pady=8)
        box.selection_set(0)

        def bajar():
            elegidos = [items[i] for i in box.curselection()]
            win.destroy()
            for titulo, url in elegidos:
                self._bajar_url(url, titulo)

        btn(win, "Descargar seleccionados", variante="exito",
            comando=bajar).pack(pady=(0, 14))

    def _diagnosticar(self):
        ruta = self._ruta()
        if not ruta:
            return
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            try:
                folletos.diagnosticar(ruta)
            except Exception as exc:
                print(f"ERROR: {exc}")
        win = tk.Toplevel(self)
        win.title(f"Diagnostico — {os.path.basename(ruta)}")
        t = tk.Text(win, width=100, height=30, wrap="none", font=F.mono)
        t.pack(fill="both", expand=True)
        t.insert("1.0", buf.getvalue())
        t.config(state="disabled")


def _emparejar(item, productos, umbral=0.55):
    """Match difuso, pero el contenido manda: nunca cruza un 500g con un 1kg."""
    from difflib import SequenceMatcher

    def norm(t):
        t = (t or "").lower().translate(
            str.maketrans("aeiouaeiouaeioun", "aeiouaeiouaeioun"))
        return re.sub(r"[^a-z0-9 ]+", " ", t)

    cant_f, base_f = auditoria.parse_contenido(item.descripcion)
    objetivo = norm(item.descripcion)
    mejor, score = None, 0.0
    for p in productos:
        cant_p, base_p = auditoria.contenido_de(p)
        if cant_f and cant_p:
            if base_f != base_p or abs(cant_f - cant_p) > 0.01:
                continue
        s = SequenceMatcher(None, objetivo, norm(p.get("descripcion", ""))).ratio()
        if s > score:
            mejor, score = p, s
    return (mejor, round(score, 3)) if mejor and score >= umbral else None

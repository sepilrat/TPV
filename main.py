"""
main.py — Punto de entrada TPV v2.0
Estructura de tabs:
  🛒 Venta
  📦 Productos  (sub-tabs: Catalogo / Precios / Stock / Reposicion / A revisar / Auditoria / Ofertas)
  🗃 Caja
  📊 Informes
"""

import os
import logging
import tkinter as tk
from tkinter import ttk
from styles import C, aplicar_tema, lbl, btn
from db import inicializar_db, get_sesion_abierta, abrir_sesion_caja
from logger import inicializar_logs, hacer_backup
from repositorio import get_stock_critico, get_vencimientos_proximos


class AppTPV(tk.Tk):
    def __init__(self):
        super().__init__()
        # En modo prueba tiene que ser IMPOSIBLE confundirse: si uno
        # carga ventas de prueba creyendo que es la base real, o al
        # reves, el desastre no se deshace.
        from db import MODO_PRUEBA, DB_PATH
        if MODO_PRUEBA:
            self.title(f"TPV — MODO PRUEBA — {os.path.basename(DB_PATH)}")
        else:
            self.title("TPV — Punto de Venta")
        self.geometry("1100x700")
        self.minsize(900, 600)
        self.configure(bg=C.bg)

        inicializar_logs()
        inicializar_db()
        aplicar_tema()
        hacer_backup("inicio")
        self._aviso_diario("apertura del sistema", "aviso_diario_al_abrir_app")

        self.sesion_id = self._verificar_sesion()
        self._construir_header()
        self._construir_tabs()
        self.after(500, self._mostrar_alertas)

    # ── Sesión de caja ────────────────────────────────────────────────────────

    def _verificar_sesion(self):
        sesion = get_sesion_abierta()
        return sesion["id"] if sesion else self._dialogo_apertura()

    def _dialogo_apertura(self):
        d = tk.Toplevel(self)
        d.title("Apertura de caja")
        d.resizable(True, False)
        d.configure(bg=C.superficie)
        d.grab_set()
        w, h = 360, 210
        d.geometry(f"{w}x{h}+{(d.winfo_screenwidth()-w)//2}+{(d.winfo_screenheight()-h)//2}")

        lbl(d, "Apertura de caja",      variante="titulo", bg=C.superficie).pack(pady=(24,2))
        lbl(d, "Ingresa el fondo inicial en efectivo", variante="suave",
            bg=C.superficie).pack()

        frame = tk.Frame(d, bg=C.superficie)
        frame.pack(pady=12)
        lbl(frame, "$", variante="subtitulo", bg=C.superficie).pack(side="left", padx=(0,6))
        e = tk.Entry(frame, width=10, justify="right", font=("Segoe UI", 14),
                     bg=C.superficie, fg=C.texto, relief="solid", bd=1)
        e.insert(0, "0")
        e.pack(side="left")
        e.focus_set()
        e.select_range(0, "end")

        result = [None]
        def confirmar(event=None):
            try:    fondo = float(e.get().replace(",", "."))
            except ValueError: fondo = 0.0
            result[0] = abrir_sesion_caja(fondo)
            self._aviso_diario("apertura de caja", "aviso_diario_al_abrir_caja")
            d.destroy()

        e.bind("<Return>", confirmar)
        btn(d, "Abrir caja", variante="exito", comando=confirmar).pack(pady=(0,16))
        self.wait_window(d)
        if not result[0]:
            result[0] = abrir_sesion_caja(0.0)
            self._aviso_diario("apertura de caja", "aviso_diario_al_abrir_caja")
        return result[0]

    # ── Header ────────────────────────────────────────────────────────────────

    def _aviso_diario(self, motivo, clave_config):
        """Aviso diario por email (stock critico + vencimientos).

        Va en un hilo aparte: si el SMTP tarda o el wifi esta caido, el
        cajero no puede quedarse esperando para empezar a vender.
        """
        import threading
        from config import cfg
        if not cfg().get(clave_config):
            return

        def trabajo():
            try:
                from impresion import enviar_aviso_diario
                ok, msg = enviar_aviso_diario(motivo)
                (logging.info if ok else logging.debug)(f"Aviso diario: {msg}")
            except Exception as e:
                logging.warning(f"No se pudo enviar el aviso diario: {e}")

        threading.Thread(target=trabajo, daemon=True).start()

    def _construir_header(self):
        # Franja imposible de ignorar cuando se trabaja sobre una base
        # de prueba: confundirse de base y cargar ventas reales en la de
        # prueba (o al reves) no se deshace.
        from db import MODO_PRUEBA, DB_PATH
        if MODO_PRUEBA:
            aviso = tk.Label(
                self,
                text=("⚠  MODO PRUEBA — estás usando "
                      f"{os.path.basename(DB_PATH)}, NO la base real.  "
                      "Nada de lo que hagas acá afecta al negocio.  ⚠"),
                bg=C.peligro, fg=C.blanco, font=("Segoe UI", 11, "bold"),
                pady=7)
            aviso.pack(fill="x")

        self._header = tk.Frame(self, bg=C.superficie, height=52)
        self._header.pack(fill="x")
        self._header.pack_propagate(False)
        tk.Frame(self, bg=C.borde, height=1).pack(fill="x")

        lbl(self._header, "TPV Autoservicio", variante="titulo",
            bg=C.superficie).pack(side="left", padx=20)
        # Que base esta en uso. Chiquito pero siempre visible: si alguna
        # vez hay dudas de si se esta en la real o en una copia, se mira
        # aca y se termina la discusion.
        lbl(self._header, os.path.basename(DB_PATH), variante="suave",
            bg=C.superficie).pack(side="left")
        lbl(self._header, f"  Caja #{self.sesion_id}  ", variante="badge",
            padx=8, pady=4).pack(side="right", padx=16, pady=10)

    # ── Tabs ──────────────────────────────────────────────────────────────────

    def _construir_tabs(self):
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True)
        self.modulos = {}

        from ventas_ui    import VentasUI
        from caja_ui      import CajaUI
        from informes_ui  import InformesUI
        from fiado_ui     import FiadoUI
        from vendedores_ui import VendedoresUI
        from config_ui    import ConfigUI

        # Tab Venta
        f_venta = ttk.Frame(nb)
        nb.add(f_venta, text="  Venta  ")
        m = VentasUI(f_venta, self)
        m.pack(fill="both", expand=True)
        self.modulos["Venta"] = m

        # Tab Productos — contenedor con sub-tabs propios
        f_prod = ttk.Frame(nb)
        nb.add(f_prod, text="  Productos  ")
        self._construir_subtabs_productos(f_prod)

        # Tab Caja — con sub-tab Fiado
        f_caja_cont = ttk.Frame(nb)
        nb.add(f_caja_cont, text="  Caja  ")
        nb_caja = ttk.Notebook(f_caja_cont)
        nb_caja.pack(fill="both", expand=True)
        for nombre_c, Clase_c in [
            ("  Caja  ", CajaUI),
            ("  Fiado  ", FiadoUI),
        ]:
            fc = ttk.Frame(nb_caja)
            nb_caja.add(fc, text=nombre_c)
            mc = Clase_c(fc, self)
            mc.pack(fill="both", expand=True)
            self.modulos[nombre_c.strip()] = mc
        nb_caja.bind("<<NotebookTabChanged>>",
            lambda e: self._on_subtab_refresh(e))

        # Tab Informes
        f_inf = ttk.Frame(nb)
        nb.add(f_inf, text="  Informes  ")
        m = InformesUI(f_inf, self)
        m.pack(fill="both", expand=True)
        self.modulos["Informes"] = m

        # Tab Vendedores
        f_vend = ttk.Frame(nb)
        nb.add(f_vend, text="  Vendedores  ")
        m = VendedoresUI(f_vend, self)
        m.pack(fill="both", expand=True)
        self.modulos["Vendedores"] = m

        # Tab Configuracion
        f_cfg = ttk.Frame(nb)
        nb.add(f_cfg, text="  Config  ")
        m = ConfigUI(f_cfg, self)
        m.pack(fill="both", expand=True)
        self.modulos["Config"] = m

        nb.bind("<<NotebookTabChanged>>", self._on_tab)

    def _construir_subtabs_productos(self, parent):
        """
        Sub-tabs del grupo Productos, con estilo visual distintivo.
        Agrupa todo lo relacionado a la gestión de productos:
        Catalogo / Precios / Stock
        """
        # Franja de color para distinguir visualmente el grupo
        franja = tk.Frame(parent, bg=C.primario, height=3)
        franja.pack(fill="x", side="top")

        from productos_ui import ProductosUI
        from precios_ui   import PreciosUI
        from ingreso_ui   import IngresoUI
        from auditoria_ui import AuditoriaUI, OfertasUI
        from revision_ui import RevisionUI
        from reposicion_ui import ReposicionUI
        from recargos_ui import RecargosUI

        nb2 = ttk.Notebook(parent, style="Productos.TNotebook")
        nb2.pack(fill="both", expand=True)

        for nombre, Clase in [
            ("  Catalogo  ",  ProductosUI),
            ("  Precios   ",  PreciosUI),
            ("  Stock     ",  IngresoUI),
            ("  Reposicion",  ReposicionUI),
            ("  Recargos  ",  RecargosUI),
            ("  A revisar ",  RevisionUI),
            ("  Auditoria ",  AuditoriaUI),
            ("  Ofertas   ",  OfertasUI),
        ]:
            f = ttk.Frame(nb2)
            nb2.add(f, text=nombre)
            m = Clase(f, self)
            m.pack(fill="both", expand=True)
            # Guardar con nombre limpio para el refresh
            key = nombre.strip()
            self.modulos[key] = m

        nb2.bind("<<NotebookTabChanged>>", self._on_subtab_productos)

    def _on_tab(self, event):
        tab = event.widget.tab(event.widget.select(), "text").strip()
        # Refresh en Caja e Informes al cambiar
        for key in ["Caja", "Informes"]:
            if key in tab:
                m = self.modulos.get(key)
                if m and hasattr(m, "refrescar"):
                    self.after(50, m.refrescar)
        # Foco en Venta
        if "Venta" in tab:
            m = self.modulos.get("Venta")
            if m and hasattr(m, "foco_scanner"):
                self.after(100, m.foco_scanner)

    def _on_subtab_productos(self, event):
        tab = event.widget.tab(event.widget.select(), "text").strip()
        m = self.modulos.get(tab)
        if m and hasattr(m, "refrescar"):
            self.after(50, m.refrescar)

    def _on_subtab_refresh(self, event):
        tab = event.widget.tab(event.widget.select(), "text").strip()
        m = self.modulos.get(tab)
        if m and hasattr(m, "refrescar"):
            self.after(50, m.refrescar)

    # ── Alertas al inicio ─────────────────────────────────────────────────────

    def _mostrar_alertas(self):
        """Muestra alertas sutiles en el header en lugar de popup bloqueante."""
        criticos   = get_stock_critico(umbral=5)
        vencimientos = get_vencimientos_proximos(dias=7)
        total = len(criticos) + len(vencimientos)
        if total == 0:
            return

        partes = []
        if criticos:
            partes.append(f"{len(criticos)} productos con stock bajo")
        if vencimientos:
            partes.append(f"{len(vencimientos)} proximos a vencer")
        texto = "  ⚠  " + "  |  ".join(partes) + "  — Ver stock"

        self.lbl_alerta = tk.Label(
            self._header,
            text=texto,
            font=("Segoe UI", 9),
            bg=C.advertencia, fg=C.blanco,
            padx=12, pady=4,
            cursor="hand2",
        )
        self.lbl_alerta.pack(side="left", padx=(12, 0), pady=10)
        self.lbl_alerta.bind("<Button-1>", self._ir_a_stock)

    def _ir_a_stock(self, event=None):
        """Navega al tab Productos → sub-tab Stock al hacer click en la alerta."""
        try:
            # Buscar el notebook principal
            for widget in self.winfo_children():
                if isinstance(widget, ttk.Notebook):
                    # Ir al tab Productos
                    for i in range(widget.index("end")):
                        if "Productos" in widget.tab(i, "text"):
                            widget.select(i)
                            # Ir al sub-tab Stock dentro de Productos
                            tab_frame = widget.winfo_children()[i]
                            for w in tab_frame.winfo_children():
                                if isinstance(w, ttk.Notebook):
                                    for j in range(w.index("end")):
                                        if "Stock" in w.tab(j, "text"):
                                            w.select(j)
                            break
        except Exception as e:
            logging.debug(f"No se pudo saltar a la pestana Stock: {e}")


if __name__ == "__main__":
    AppTPV().mainloop()

"""
tests_basicos.py — Pruebas de la logica de plata del TPV (sin pantallas).

Correr antes de cada push:   python tests_basicos.py

Usa una base TEMPORAL (nunca toca tpv2.db), asi que se puede correr cuando sea.
"""
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta

os.environ["TPV_DB"] = os.path.join(tempfile.mkdtemp(), "prueba_tests.db")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db  # noqa: E402
db.inicializar_db()
import repositorio as r  # noqa: E402


class CuentaCorriente(unittest.TestCase):
    def setUp(self):
        self.c = r.crear_cliente(str(id(self))[-8:], "Cliente Test", "1155", 100000)["id"]

    def saldo(self):
        return next(x["saldo_actual"] for x in r.get_todos_clientes() if x["id"] == self.c)

    def test_cargo_manual_suma_y_deja_movimiento(self):
        self.assertEqual(r.registrar_cargo_cuenta_corriente(self.c, 2500.5, "Cuaderno", "t"), 2500.5)
        m = r.get_movimientos_cliente(self.c)[0]
        self.assertEqual((m["tipo"], m["monto"], m["concepto"]), ("cuenta_corriente", 2500.5, "Cuaderno"))

    def test_cargo_rechaza_monto_concepto_y_fecha_invalidos(self):
        for args in ((0, "x"), (-5, "x"), (100, "  ")):
            with self.assertRaises(ValueError):
                r.registrar_cargo_cuenta_corriente(self.c, args[0], args[1], "t")
        with self.assertRaises(ValueError):
            r.registrar_cargo_cuenta_corriente(self.c, 10, "x", "t", "2099-01-01")
        self.assertEqual(self.saldo(), 0)

    def test_fecha_anterior(self):
        r.registrar_cargo_cuenta_corriente(self.c, 100, "Viejo", "t", "2026-01-15")
        self.assertTrue(r.get_movimientos_cliente(self.c)[0]["fecha"].startswith("2026-01-15"))

    def test_anular_cargo_manual_una_sola_vez(self):
        r.registrar_cargo_cuenta_corriente(self.c, 700, "Error", "t")
        mid = r.get_movimientos_cliente(self.c)[0]["id"]
        self.assertEqual(r.anular_cargo_manual(mid, "t"), 0)
        with self.assertRaises(ValueError):
            r.anular_cargo_manual(mid, "t")
        self.assertEqual(self.saldo(), 0)

    def test_un_pago_no_se_anula_como_cargo(self):
        r.registrar_cargo_cuenta_corriente(self.c, 700, "Deuda", "t")
        r.registrar_pago_cuenta_corriente(self.c, 200, "t")
        pago = next(m for m in r.get_movimientos_cliente(self.c) if m["tipo"] == "pago")
        with self.assertRaises(ValueError):
            r.anular_cargo_manual(pago["id"], "t")


class Margen(unittest.TestCase):
    def test_niveles(self):
        self.assertEqual(r.margen_sobre_costo(900, 1000)["nivel"], "perdida")
        self.assertEqual(r.margen_sobre_costo(1050, 1000, 10)["nivel"], "bajo")
        self.assertEqual(r.margen_sobre_costo(1300, 1000, 10)["nivel"], "ok")
        self.assertEqual(r.margen_sobre_costo(900, 0)["nivel"], "sin_costo")

    def test_porcentaje_es_sobre_el_costo(self):
        self.assertAlmostEqual(r.margen_sobre_costo(1300, 1000)["pct"], 30.0)

    def test_simulacion_de_promo_masiva(self):
        pid = r.crear_producto("M1", "Prod margen", None, 1500, 1000)
        sim = r.simular_promo_masiva([pid], "pct", 40)     # 1500 -> 900: pierde
        self.assertEqual(sim[0]["nivel"], "perdida")
        self.assertEqual(r.simular_promo_masiva([pid], "pct", 10)[0]["nivel"], "ok")


class Vendedores(unittest.TestCase):
    def test_codigo_con_espacio_se_rechaza_y_sugiere(self):
        ok, err = r.guardar_vendedor(None, "Lauti Rossi", "Lauti", "lautitest", "x", "", 10, "negocio")
        self.assertFalse(ok)
        self.assertIn("lauti-rossi", err)

    def test_codigo_valido_y_diagnostico_modo_descuento(self):
        r.crear_producto("V1", "Prod vend", None, 1500, 1000)
        ok, _ = r.guardar_vendedor(None, "lauti-t", "Lauti", "lauti_t", "x", "", 10,
                                   "negocio", "descuento", "")
        self.assertTrue(ok)
        d = next(x for x in r.diagnosticar_vendedores() if x["vendedor"]["codigo"] == "lauti-t")
        self.assertTrue(any("PRECIO DE LISTA" in t for _, t in d["problemas"]))
        self.assertAlmostEqual(d["ejemplo"][1], d["ejemplo"][2])      # ve la lista

    def test_recargo_sube_el_precio(self):
        r.crear_producto("V2", "Prod recargo", None, 1500, 1000)
        r.guardar_vendedor(None, "nati-t", "Nati", "nati_t", "x", "", 10, "negocio", "recargo", "")
        d = next(x for x in r.diagnosticar_vendedores() if x["vendedor"]["codigo"] == "nati-t")
        self.assertGreater(d["ejemplo"][2], d["ejemplo"][1])


class PromosVsPrecioDeLista(unittest.TestCase):
    """Bajar el precio de un producto no puede dejar una promo MAS CARA.

    Bug real: producto a $1500 con promo "x12 a $900"; se baja el producto a
    $800 y la promo de precio fijo quedaba en $900, asi que llevar 12 salia
    mas caro que llevar 1.
    """
    def _producto_con_promo(self, cod, base, promo, cant=12):
        pid = r.crear_producto(cod, "Prod " + cod, None, base, 500)
        r.guardar_promocion(None, pid, cant, promo, f"x{cant}", None, None)
        return pid

    def _bajar_precio(self, pid, nuevo):
        with db.get_connection() as c:
            c.execute("UPDATE productos SET precio_base=? WHERE id=?", (nuevo, pid))
            c.commit()

    def test_promo_cara_no_se_aplica_tras_bajar_el_precio(self):
        pid = self._producto_con_promo("PB1", 1500, 900)
        self.assertEqual(r.get_precio_con_promo(pid, 12), (900.0, True))
        self._bajar_precio(pid, 800)
        self.assertEqual(r.get_precio_con_promo(pid, 12), (800.0, False))

    def test_llevar_mas_nunca_sale_mas_caro_por_unidad(self):
        pid = self._producto_con_promo("PB2", 1500, 900)
        self._bajar_precio(pid, 800)
        precios = [r.get_precio_con_promo(pid, q)[0] for q in range(1, 25)]
        self.assertEqual(max(precios), min(precios))     # no hay promo valida: todos a 800
        pid2 = self._producto_con_promo("PB3", 1500, 900)
        precios2 = [r.get_precio_con_promo(pid2, q)[0] for q in range(1, 25)]
        self.assertEqual(precios2, sorted(precios2, reverse=True))   # solo baja o se mantiene

    def test_promo_igual_al_precio_tampoco_cuenta(self):
        pid = self._producto_con_promo("PB4", 1000, 1000)
        self.assertFalse(r.get_precio_con_promo(pid, 12)[1])

    def test_promo_que_si_conviene_sigue_andando(self):
        pid = self._producto_con_promo("PB5", 1500, 1300)
        self.assertEqual(r.get_precio_con_promo(pid, 12), (1300.0, True))

    def test_promo_por_porcentaje_se_ajusta_sola(self):
        pid = r.crear_producto("PB6", "Prod pct", None, 1500, 500)
        r.guardar_promocion(None, pid, 12, 0, "x12 20%", None, None,
                            tipo_descuento="porcentaje", porcentaje=20)
        self.assertEqual(r.get_precio_con_promo(pid, 12), (1200.0, True))
        self._bajar_precio(pid, 800)
        self.assertEqual(r.get_precio_con_promo(pid, 12), (640.0, True))

    def test_etiquetas_y_web_no_muestran_la_promo_vieja(self):
        from etiquetas import _get_precios_producto
        pid = self._producto_con_promo("PB7", 1500, 900)
        self.assertEqual(len(_get_precios_producto(pid, 1500)), 2)
        self._bajar_precio(pid, 800)
        self.assertEqual([p["cantidad"] for p in _get_precios_producto(pid, 800)], [1])
        self.assertNotIn(pid, r.get_promociones_activas_por_producto())

    def test_detectar_y_apagar_obsoletas(self):
        pid = self._producto_con_promo("PB8", 1500, 900)
        self.assertNotIn(pid, [o["producto_id"] for o in r.promos_obsoletas()])
        self._bajar_precio(pid, 800)
        obs = [o for o in r.promos_obsoletas() if o["producto_id"] == pid]
        self.assertEqual(len(obs), 1)
        self.assertEqual(r.desactivar_promos_obsoletas([obs[0]["id"]]), 1)
        self.assertEqual([o for o in r.promos_obsoletas() if o["producto_id"] == pid], [])


class PromosPorPorcentaje(unittest.TestCase):
    """Una promo cargada como % tiene que SEGUIR siendo un %.

    Bug real: la "Promocion masiva" calculaba el precio y lo guardaba como
    precio fijo, sin el porcentaje. Al bajar el producto la promo no se
    movia, y "Sumar puntos %" no la tocaba.
    """
    def _promo(self, pid):
        with db.get_connection() as c:
            return dict(c.execute("SELECT * FROM promociones WHERE producto_id=?", (pid,)).fetchone())

    def _precio(self, pid, nuevo):
        with db.get_connection() as c:
            c.execute("UPDATE productos SET precio_base=? WHERE id=?", (nuevo, pid))
            c.commit()

    def test_masiva_por_tipo_guarda_porcentaje(self):
        pid = r.crear_producto("PP1", "Prod pp1", None, 1000, 400)
        r.aplicar_promocion_bulk_tipo([pid], [(12, 20)], tipo="pct")
        p = self._promo(pid)
        self.assertEqual((p["tipo_descuento"], p["porcentaje_descuento"]), ("porcentaje", 20.0))
        self.assertEqual(r.get_precio_con_promo(pid, 12), (800.0, True))
        self._precio(pid, 500)                                   # baja el producto
        self.assertEqual(r.get_precio_con_promo(pid, 12), (400.0, True))   # la promo lo sigue

    def test_masiva_monto_y_fijo_siguen_siendo_precio_fijo(self):
        a = r.crear_producto("PP2", "Prod pp2", None, 1000, 400)
        b = r.crear_producto("PP3", "Prod pp3", None, 1000, 400)
        r.aplicar_promocion_bulk_tipo([a], [(6, 150)], tipo="monto")
        r.aplicar_promocion_bulk_tipo([b], [(6, 700)], tipo="fijo")
        self.assertEqual(self._promo(a)["tipo_descuento"], "precio_fijo")
        self.assertEqual(self._promo(b)["tipo_descuento"], "precio_fijo")

    def test_masiva_vieja_tambien(self):
        pid = r.crear_producto("PP4", "Prod pp4", None, 1000, 400)
        r.aplicar_promocion_bulk([pid], [(3, 10)], "x3", None, None)
        self.assertEqual(self._promo(pid)["tipo_descuento"], "porcentaje")
        r.aplicar_promocion_bulk([pid], [(3, 25)], "x3", None, None)     # actualiza la misma
        p = self._promo(pid)
        self.assertEqual((p["tipo_descuento"], p["porcentaje_descuento"]), ("porcentaje", 25.0))

    def test_sumar_puntos_ahora_funciona_sobre_las_masivas(self):
        pid = r.crear_producto("PP5", "Prod pp5", None, 1000, 400)
        r.aplicar_promocion_bulk_tipo([pid], [(12, 20)], tipo="pct")
        pr = self._promo(pid)
        self.assertEqual(r.modificar_promociones_bulk([pr["id"]], "sumar_pct", 5), 1)
        self.assertEqual(r.get_precio_con_promo(pid, 12)[0], 750.0)

    def test_etiquetas_calculan_el_porcentaje_con_el_precio_de_hoy(self):
        from etiquetas import _get_precios_producto
        pid = r.crear_producto("PP6", "Prod pp6", None, 1000, 400)
        r.aplicar_promocion_bulk_tipo([pid], [(12, 20)], tipo="pct")
        self._precio(pid, 500)
        precios = {p["cantidad"]: p["precio"] for p in _get_precios_producto(pid, 500)}
        self.assertEqual(precios, {1: 500, 12: 400.0})          # no el 800 guardado
        # con recargo de vendedor: el descuento NO incluye el recargo
        precios = {p["cantidad"]: p["precio"] for p in _get_precios_producto(pid, 550, 50)}
        self.assertEqual(precios, {1: 550, 12: 450.0})

    def test_convertir_existentes_conserva_el_descuento_actual(self):
        pid = r.crear_producto("PP7", "Prod pp7", None, 1000, 400)
        r.guardar_promocion(None, pid, 12, 800.0, "x12", None, None)      # fijo, 20% off hoy
        pid_ = self._promo(pid)["id"]
        prev = r.convertir_promos_a_porcentaje([pid_])
        self.assertEqual((prev[0]["estado"], prev[0]["pct"]), ("ok", 20.0))
        self.assertEqual(self._promo(pid)["tipo_descuento"], "precio_fijo")   # la vista previa no escribe
        r.convertir_promos_a_porcentaje([pid_], aplicar=True)
        self.assertEqual(self._promo(pid)["tipo_descuento"], "porcentaje")
        self._precio(pid, 500)
        self.assertEqual(r.get_precio_con_promo(pid, 12)[0], 400.0)

    def test_convertir_con_porcentaje_explicito_y_obsoletas(self):
        pid = r.crear_producto("PP8", "Prod pp8", None, 1500, 400)
        r.guardar_promocion(None, pid, 12, 900.0, "x12", None, None)
        self._precio(pid, 800)                                            # la promo quedo vieja
        pr_id = self._promo(pid)["id"]
        self.assertEqual(r.convertir_promos_a_porcentaje([pr_id])[0]["estado"], "sin_pct")
        r.convertir_promos_a_porcentaje([pr_id], 40, aplicar=True)
        self.assertEqual(r.get_precio_con_promo(pid, 12), (480.0, True))
        with self.assertRaises(ValueError):
            r.convertir_promos_a_porcentaje([pr_id], 150)

    def test_chequeo_de_datos_no_marca_promos_por_porcentaje(self):
        pid = r.crear_producto("PP9", "Prod pp9", None, 1000, 400)
        r.aplicar_promocion_bulk_tipo([pid], [(12, 20)], tipo="pct")
        self._precio(pid, 500)               # el precio guardado (800) queda > 500 pero es un %
        self.assertNotIn(pid, [o["producto_id"] for o in r.promos_obsoletas()])


class EliminarPromosEnMasa(unittest.TestCase):
    def test_borra_las_elegidas_y_deja_respaldo(self):
        carpeta = tempfile.mkdtemp()
        ids = []
        for k in range(3):
            pid = r.crear_producto(f"EM{k}", f"Prod em{k}", None, 1000, 400)
            r.aplicar_promocion_bulk_tipo([pid], [(12, 20)], tipo="pct")
            with db.get_connection() as c:
                ids.append(c.execute("SELECT id FROM promociones WHERE producto_id=?", (pid,)).fetchone()[0])
        n, ruta = r.eliminar_promociones_bulk(ids[:2], carpeta)
        self.assertEqual(n, 2)
        restantes = [p["id"] for p in r.get_promociones()]
        self.assertNotIn(ids[0], restantes)
        self.assertNotIn(ids[1], restantes)
        self.assertIn(ids[2], restantes)
        txt = open(ruta, encoding="utf-8-sig").read()
        self.assertIn("Prod em0", txt)
        self.assertIn("porcentaje", txt)
        self.assertNotIn("Prod em2", txt)

    def test_si_no_hay_respaldo_no_se_borra(self):
        pid = r.crear_producto("EM9", "Prod em9", None, 1000, 400)
        r.aplicar_promocion_bulk_tipo([pid], [(12, 20)], tipo="pct")
        with db.get_connection() as c:
            pid_ = c.execute("SELECT id FROM promociones WHERE producto_id=?", (pid,)).fetchone()[0]
        archivo = os.path.join(tempfile.mkdtemp(), "no_es_carpeta")
        open(archivo, "w").close()                       # un archivo donde iria la carpeta
        with self.assertRaises(Exception):
            r.eliminar_promociones_bulk([pid_], archivo)
        self.assertIn(pid_, [p["id"] for p in r.get_promociones()])

    def test_lista_vacia(self):
        self.assertEqual(r.eliminar_promociones_bulk([]), (0, None))


class FacturacionPorMail(unittest.TestCase):
    """El mail de facturacion no puede fallar en silencio."""
    def setUp(self):
        import config, impresion, smtplib
        self.impresion, self.smtplib = impresion, smtplib
        self._cfg, self._smtp, self._set = impresion.cfg, smtplib.SMTP, impresion.cfg_set
        self.c = dict(config.cfg())
        self.c.update(email_activo=True, email_smtp_host="smtp.fake.com", email_smtp_port=587,
                      email_usuario="x@fake.com", email_password="p", email_remitente="TPV",
                      negocio_nombre="Test", aviso_diario_destinatario="",
                      informe_facturacion_destinatario="a@fake.com")
        impresion.cfg = lambda: self.c
        impresion.cfg_set = lambda k, v: self.c.__setitem__(k, v)
        self.enviados = []
        outer = self

        class FakeSMTP:
            def __init__(self, *a, **k): pass
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def starttls(self): pass
            def login(self, u, p): pass
            def send_message(self, m): outer.enviados.append(m["To"])
        smtplib.SMTP = FakeSMTP

    def tearDown(self):
        self.impresion.cfg, self.impresion.cfg_set = self._cfg, self._set
        self.smtplib.SMTP = self._smtp

    def test_envia_y_anota_el_dia(self):
        from datetime import date
        ok, _ = self.impresion.enviar_email_facturacion(registrar=True)
        self.assertTrue(ok)
        self.assertEqual(self.enviados, ["a@fake.com"])
        self.assertEqual(self.c["_facturacion_ultimo_envio"], date.today().isoformat())

    def test_una_prueba_no_consume_el_envio_del_dia(self):
        """Probar el mail al mediodia no puede dejar sin enviar el de la noche."""
        ok, _ = self.impresion.enviar_email_facturacion()          # como el boton "Probar"
        self.assertTrue(ok)
        self.assertEqual(self.enviados, ["a@fake.com"])
        self.assertFalse(self.c.get("_facturacion_ultimo_envio"))

    def test_error_en_la_base_se_informa_y_no_revienta(self):
        orig = r.resumen_cobranzas
        r.resumen_cobranzas = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("base bloqueada"))
        try:
            ok, msg = self.impresion.enviar_email_facturacion()
        finally:
            r.resumen_cobranzas = orig
        self.assertFalse(ok)
        self.assertIn("base bloqueada", msg)

    def test_sin_destinatario_o_sin_email_activo_dice_por_que(self):
        self.c["informe_facturacion_destinatario"] = ""
        ok, msg = self.impresion.enviar_email_facturacion()
        self.assertFalse(ok)
        self.assertIn("destinatario", msg.lower())
        self.c["email_activo"] = False
        self.assertIn("Email", self.impresion.enviar_email_facturacion()[1])

    def test_el_script_programado_siempre_deja_registro(self):
        import logging, informe_facturacion_email as ife
        self.c["informe_facturacion_activo"] = False
        ife.cfg = lambda: self.c
        ife.inicializar_logs = lambda: None
        with self.assertLogs(level="WARNING") as cm:
            self.assertEqual(ife.main([]), 0)
        self.assertTrue(any("destildado" in m for m in cm.output))
        self.c["informe_facturacion_activo"] = True
        ife.enviar_email_facturacion = lambda **k: (_ for _ in ()).throw(RuntimeError("boom"))
        with self.assertLogs(level="ERROR") as cm:
            self.assertEqual(ife.main([]), 2)
        self.assertTrue(any("boom" in m for m in cm.output))


class CorridaAtrasadaDeFacturacion(unittest.TestCase):
    """La hora de envio sale de Config en cada corrida (tarea cada 10 minutos)."""
    def _f(self, ahora, hora="21:30", envio="", intento=""):
        from datetime import datetime
        from informe_facturacion_email import fecha_a_enviar
        return fecha_a_enviar(datetime(*ahora), hora, envio, intento)

    def test_no_manda_antes_de_la_hora(self):
        self.assertIsNone(self._f((2026, 10, 4, 15, 0), envio="2026-10-03"))
        self.assertIsNone(self._f((2026, 10, 4, 21, 29), envio="2026-10-03"))

    def test_manda_pasada_la_hora_y_una_sola_vez(self):
        self.assertEqual(self._f((2026, 10, 4, 21, 30), envio="2026-10-03"), "2026-10-04")
        self.assertEqual(self._f((2026, 10, 4, 23, 50), envio="2026-10-03"), "2026-10-04")
        self.assertIsNone(self._f((2026, 10, 4, 21, 40), envio="2026-10-04"))   # ya salio hoy

    def test_cambiar_la_hora_en_config_cambia_cuando_sale(self):
        self.assertIsNone(self._f((2026, 10, 4, 20, 5), hora="21:30", envio="2026-10-03"))
        self.assertEqual(self._f((2026, 10, 4, 20, 5), hora="20:00", envio="2026-10-03"), "2026-10-04")
        self.assertEqual(self._f((2026, 10, 4, 7, 5), hora="07:00", envio="2026-10-03"), "2026-10-04")

    def test_pc_apagada_a_la_noche_manda_el_de_ayer_a_la_manana(self):
        self.assertEqual(self._f((2026, 10, 5, 8, 0), envio="2026-10-03"), "2026-10-04")
        self.assertEqual(self._f((2026, 10, 5, 8, 0), envio=""), "2026-10-04")
        self.assertIsNone(self._f((2026, 10, 5, 8, 0), envio="2026-10-04"))

    def test_si_falla_no_reintenta_en_cada_corrida(self):
        self.assertIsNone(self._f((2026, 10, 4, 22, 0), envio="2026-10-03", intento="2026-10-04 21:40"))
        self.assertEqual(self._f((2026, 10, 4, 22, 41), envio="2026-10-03", intento="2026-10-04 21:40"),
                         "2026-10-04")

    def test_hora_mal_escrita_usa_21_30_y_no_revienta(self):
        self.assertIsNone(self._f((2026, 10, 4, 15, 0), hora="xx", envio="2026-10-03"))
        self.assertEqual(self._f((2026, 10, 4, 22, 0), hora="99:99", envio="2026-10-03"), "2026-10-04")

    def test_main_programado_es_silencioso_cuando_no_toca(self):
        import informe_facturacion_email as ife
        from datetime import datetime
        c = {"informe_facturacion_activo": True, "informe_facturacion_hora": "21:30",
             "_facturacion_ultimo_envio": datetime.now().date().isoformat()}
        ife.cfg = lambda: c
        llamado = []
        ife.enviar_email_facturacion = lambda **k: llamado.append(k) or (True, "ok")
        ife.inicializar_logs = lambda: llamado.append("log")
        self.assertEqual(ife.main(["--programado"]), 0)
        self.assertEqual(llamado, [])                 # ni envia ni toca el log
        c["informe_facturacion_activo"] = False
        self.assertEqual(ife.main(["--programado"]), 0)
        self.assertEqual(llamado, [])

    def test_main_programado_manda_y_en_manual_manda_hoy(self):
        import informe_facturacion_email as ife
        from datetime import datetime
        ahora = datetime.now()
        c = {"informe_facturacion_activo": True,
             "informe_facturacion_hora": "00:00", "_facturacion_ultimo_envio": ""}
        ife.cfg = lambda: c
        ife.cfg_set = lambda k, v: c.__setitem__(k, v)
        ife.inicializar_logs = lambda: None
        llamado = []
        ife.enviar_email_facturacion = lambda **k: llamado.append(k) or (True, "ok")
        self.assertEqual(ife.main(["--programado"]), 0)
        self.assertEqual(llamado, [{"fecha": ahora.date().isoformat(), "registrar": True}])
        llamado.clear()
        self.assertEqual(ife.main([]), 0)             # manual: hoy, sin mirar la hora ni consumir el dia
        self.assertEqual(llamado, [{"fecha": None, "registrar": False}])

    def test_main_programado_anota_el_fallo(self):
        import informe_facturacion_email as ife
        c = {"informe_facturacion_activo": True, "informe_facturacion_hora": "00:00",
             "_facturacion_ultimo_envio": ""}
        ife.cfg = lambda: c
        ife.cfg_set = lambda k, v: c.__setitem__(k, v)
        ife.inicializar_logs = lambda: None
        ife.enviar_email_facturacion = lambda **k: (False, "sin internet")
        self.assertEqual(ife.main(["--programado"]), 1)
        self.assertTrue(c["_facturacion_ultimo_intento"])

    def test_el_ultimo_envio_no_retrocede(self):
        import config, impresion, smtplib
        c = dict(config.cfg())
        c.update(email_activo=True, email_smtp_host="h", email_smtp_port=587, email_usuario="u",
                 email_password="p", email_remitente="T", negocio_nombre="N",
                 informe_facturacion_destinatario="a@b.com", _facturacion_ultimo_envio="2026-10-04")
        o = (impresion.cfg, impresion.cfg_set, smtplib.SMTP)
        impresion.cfg = lambda: c
        impresion.cfg_set = lambda k, v: c.__setitem__(k, v)

        class F:
            def __init__(s, *a, **k): pass
            def __enter__(s): return s
            def __exit__(s, *a): return False
            def starttls(s): pass
            def login(s, u, p): pass
            def send_message(s, m): pass
        smtplib.SMTP = F
        try:
            self.assertTrue(impresion.enviar_email_facturacion(fecha="2026-10-03", registrar=True)[0])
            self.assertEqual(c["_facturacion_ultimo_envio"], "2026-10-04")     # no baja
            self.assertTrue(impresion.enviar_email_facturacion(fecha="2026-10-05", registrar=True)[0])
            self.assertEqual(c["_facturacion_ultimo_envio"], "2026-10-05")
        finally:
            impresion.cfg, impresion.cfg_set, smtplib.SMTP = o


class InformesProgramadosStockYVencimientos(unittest.TestCase):
    """Stock y vencimientos tambien toman la hora de Config en cada corrida."""
    def _correr(self, argv, c, ahora, enviar):
        import programacion as pg
        orig = pg.datetime

        class Reloj(orig):
            @classmethod
            def now(cls, tz=None):
                return ahora
        pg.datetime = Reloj
        try:
            return pg.correr_programado(
                argv, nombre="Prueba", clave_activo="act", clave_hora="hora",
                clave_envio="env", clave_intento="int", enviar=enviar,
                hora_defecto=(8, 0), cfg=lambda: c,
                cfg_set=lambda k, v: c.__setitem__(k, v), inicializar_logs=lambda: None)
        finally:
            pg.datetime = orig

    def test_manda_pasada_la_hora_de_config_y_una_sola_vez(self):
        from datetime import datetime
        c = {"act": True, "hora": "08:00", "env": "", "int": ""}
        llamadas = []
        enviar = lambda: llamadas.append(1) or (True, "ok")
        self.assertEqual(self._correr(["--programado"], c, datetime(2026, 10, 4, 7, 50), enviar), 0)
        self.assertEqual(llamadas, [])                                   # todavia no es la hora
        self.assertEqual(self._correr(["--programado"], c, datetime(2026, 10, 4, 8, 5), enviar), 0)
        self.assertEqual(len(llamadas), 1)
        self.assertEqual(c["env"], "2026-10-04")
        self._correr(["--programado"], c, datetime(2026, 10, 4, 8, 15), enviar)
        self.assertEqual(len(llamadas), 1)                               # ya salio hoy
        self._correr(["--programado"], c, datetime(2026, 10, 5, 9, 0), enviar)
        self.assertEqual(len(llamadas), 2)                               # al dia siguiente, otra vez

    def test_cambiar_la_hora_en_config_alcanza(self):
        from datetime import datetime
        c = {"act": True, "hora": "20:00", "env": "", "int": ""}
        llamadas = []
        enviar = lambda: llamadas.append(1) or (True, "ok")
        self._correr(["--programado"], c, datetime(2026, 10, 4, 10, 0), enviar)
        self.assertEqual(llamadas, [])
        c["hora"] = "09:30"                                              # la cambia en Config
        self._correr(["--programado"], c, datetime(2026, 10, 4, 10, 0), enviar)
        self.assertEqual(len(llamadas), 1)

    def test_pc_prendida_tarde_manda_apenas_prende(self):
        from datetime import datetime
        c = {"act": True, "hora": "08:00", "env": "2026-10-03", "int": ""}
        llamadas = []
        self._correr(["--programado"], c, datetime(2026, 10, 4, 13, 20),
                     lambda: llamadas.append(1) or (True, "ok"))
        self.assertEqual(len(llamadas), 1)

    def test_si_falla_espera_una_hora_y_no_se_marca_como_enviado(self):
        from datetime import datetime
        c = {"act": True, "hora": "08:00", "env": "", "int": ""}
        llamadas = []
        falla = lambda: llamadas.append(1) or (False, "sin internet")
        self.assertEqual(self._correr(["--programado"], c, datetime(2026, 10, 4, 8, 0), falla), 1)
        self.assertEqual(c["env"], "")
        self.assertTrue(c["int"])
        self._correr(["--programado"], c, datetime(2026, 10, 4, 8, 20), falla)
        self.assertEqual(len(llamadas), 1)                               # espera
        self._correr(["--programado"], c, datetime(2026, 10, 4, 9, 5), falla)
        self.assertEqual(len(llamadas), 2)                               # reintenta

    def test_desactivado_o_prueba_manual(self):
        from datetime import datetime
        c = {"act": False, "hora": "08:00", "env": "", "int": ""}
        llamadas = []
        enviar = lambda: llamadas.append(1) or (True, "ok")
        self._correr(["--programado"], c, datetime(2026, 10, 4, 12, 0), enviar)
        self.assertEqual(llamadas, [])
        c["act"] = True
        self._correr([], c, datetime(2026, 10, 4, 7, 0), enviar)          # manual: manda ya
        self.assertEqual(len(llamadas), 1)
        self.assertEqual(c["env"], "")                                   # y no consume el dia

    def test_los_scripts_usan_la_hora_y_las_claves_correctas(self):
        import informe_stock_email as s, informe_vencimientos_email as v
        self.assertTrue(callable(s.main) and callable(v.main))


class DiagnosticoTareas(unittest.TestCase):
    ES = ("Nombre de host:                       PC\r\nNombre de tarea:                      \\TPV - Facturacion\r\n"
          "Estado:                               Listo\r\nTarea que se ejecutar\u00e1:                 "
          "C:\\TPV\\.venv\\Scripts\\pythonw.exe \"C:\\TPV\\informe_facturacion_email.py\"\r\n"
          "\u00daltimo resultado:                      0\r\n\r\n"
          "Nombre de tarea:                      \\Otra cosa\r\nTarea que se ejecutar\u00e1: notepad.exe\r\n")
    EN = ("TaskName:        \\TPV - Stock\nStatus:          Ready\nTask To Run:     python.exe informe_stock_email.py\n"
          "Last Result:     267011\n\nTaskName:        \\Backup\nTask To Run:     robocopy\n")

    def test_encuentra_la_tarea_en_windows_en_espanol_e_ingles(self):
        import diagnostico_email as de
        self.assertEqual(len(de.tareas_de_script(self.ES, "informe_facturacion_email")), 1)
        self.assertEqual(len(de.tareas_de_script(self.EN, "informe_stock_email")), 1)
        resumen = de._resumen_tarea(de.tareas_de_script(self.ES, "informe_facturacion_email")[0])
        self.assertTrue(any(l.startswith("\u00daltimo resultado") for l in resumen))

    def test_distingue_la_tarea_nueva_de_la_vieja(self):
        import diagnostico_email as de
        nueva = self.ES.replace('informe_facturacion_email.py\"', 'informe_facturacion_email.py\" --programado')
        self.assertTrue(de.tarea_sigue_la_hora_de_config(de.tareas_de_script(nueva, "informe_facturacion_email")[0]))
        self.assertFalse(de.tarea_sigue_la_hora_de_config(de.tareas_de_script(self.ES, "informe_facturacion_email")[0]))

    def test_sin_tarea_devuelve_vacio(self):
        import diagnostico_email as de
        self.assertEqual(de.tareas_de_script(self.EN, "informe_facturacion_email"), [])
        self.assertEqual(de.tareas_de_script("", "x"), [])


class Cupones(unittest.TestCase):
    """Un monto en $ para gastar en una categoria hasta una fecha."""
    @classmethod
    def setUpClass(cls):
        with db.get_connection() as c:
            cls.cat_beb = c.execute("INSERT INTO categorias (nombre) VALUES ('Bebidas CUP')").lastrowid
            cls.cat_alm = c.execute("INSERT INTO categorias (nombre) VALUES ('Almacen CUP')").lastrowid
            cls.sesion = c.execute("INSERT INTO sesiones_caja (fondo_inicial) VALUES (0)").lastrowid
            c.commit()

    def _prod(self, cod, cat, precio=1000, stock=50):
        pid = r.crear_producto(cod, "Prod " + cod, cat, precio, precio * 0.5)
        r.ajustar_stock(pid, stock, "test", "t")
        return pid

    def _item(self, pid, cant, precio):
        return {"producto_id": pid, "descripcion": "x", "cantidad": cant,
                "precio_unitario": precio, "promo_aplicada": 0}

    def _mañana(self, dias=7):
        return (date.today() + timedelta(days=dias)).isoformat()

    def _caja(self, col="total_efectivo"):
        with db.get_connection() as c:
            return c.execute(f"SELECT {col} FROM sesiones_caja WHERE id=?", (self.sesion,)).fetchone()[0]

    # ── crear ──
    def test_crear_genera_codigo_y_guarda_todo(self):
        c = r.crear_cupon(500, self.cat_beb, self._mañana(), nota="Para Nati", creado_por="t")
        self.assertRegex(c["codigo"], r"^CUP-[A-Z2-9]{6}$")
        self.assertNotRegex(c["codigo"][4:], r"[01OIL]")
        self.assertEqual((c["monto"], c["monto_restante"], c["estado"], c["categoria_nombre"]),
                         (500, 500, "activo", "Bebidas CUP"))

    def test_crear_valida(self):
        for args in ((0, self.cat_beb, self._mañana()), (-5, self.cat_beb, self._mañana()),
                     (100, self.cat_beb, "2020-01-01"), (100, self.cat_beb, "no-es-fecha"),
                     (100, 99999, self._mañana())):
            with self.assertRaises(ValueError):
                r.crear_cupon(*args)
        with self.assertRaises(ValueError):
            r.crear_cupon(100, None, self._mañana(), codigo="a b")        # espacio
        r.crear_cupon(100, None, self._mañana(), codigo="  promo10 ")
        self.assertIsNotNone(r.get_cupon_por_codigo("PROMO10"))
        with self.assertRaises(ValueError):
            r.crear_cupon(100, None, self._mañana(), codigo="promo10")     # duplicado

    def test_estados(self):
        c = r.crear_cupon(100, None, self._mañana())
        self.assertEqual(r.estado_cupon(c), "activo")
        self.assertEqual(r.estado_cupon(dict(c, fecha_hasta="2020-01-01")), "vencido")
        self.assertEqual(r.estado_cupon(dict(c, monto_restante=0)), "usado")
        self.assertEqual(r.estado_cupon(dict(c, anulado=1)), "anulado")
        self.assertEqual(r.estado_cupon(dict(c, fecha_desde=self._mañana(3))), "todavia_no")
        self.assertTrue(r.anular_cupon(c["id"], "error"))
        self.assertFalse(r.anular_cupon(c["id"]))
        self.assertEqual(r.get_cupon_por_codigo(c["codigo"])["estado"], "anulado")

    # ── cuanto aplica ──
    def test_solo_cuentan_los_productos_de_la_categoria(self):
        beb, alm = self._prod("CU-B1", self.cat_beb), self._prod("CU-A1", self.cat_alm)
        c = r.crear_cupon(5000, self.cat_beb, self._mañana())
        items = [{"producto_id": beb, "subtotal": 800}, {"producto_id": alm, "subtotal": 3000}]
        calc = r.calcular_aplicacion_cupon(c, items)
        self.assertEqual((calc["aplicable"], calc["base"]), (800.0, 800.0))   # no toca el almacen

    def test_no_aplica_mas_que_el_saldo_ni_que_la_compra(self):
        beb = self._prod("CU-B2", self.cat_beb)
        c = r.crear_cupon(300, self.cat_beb, self._mañana())
        self.assertEqual(r.calcular_aplicacion_cupon(c, [{"producto_id": beb, "subtotal": 1000}])["aplicable"], 300)
        self.assertEqual(r.calcular_aplicacion_cupon(c, [{"producto_id": beb, "subtotal": 120}])["aplicable"], 120)

    def test_el_descuento_manual_no_se_cuenta_dos_veces(self):
        beb = self._prod("CU-B3", self.cat_beb)
        c = r.crear_cupon(5000, self.cat_beb, self._mañana())
        calc = r.calcular_aplicacion_cupon(c, [{"producto_id": beb, "subtotal": 1000}], descuento_manual=200)
        self.assertEqual(calc["aplicable"], 800.0)                       # 1000 - 200 de descuento

    def test_sin_productos_de_la_categoria_explica_por_que(self):
        alm = self._prod("CU-A2", self.cat_alm)
        c = r.crear_cupon(500, self.cat_beb, self._mañana())
        calc = r.calcular_aplicacion_cupon(c, [{"producto_id": alm, "subtotal": 900}])
        self.assertEqual(calc["aplicable"], 0)
        self.assertIn("Bebidas CUP", calc["motivo"])

    def test_cupon_de_cualquier_categoria(self):
        a, b = self._prod("CU-X1", self.cat_beb), self._prod("CU-X2", self.cat_alm)
        c = r.crear_cupon(5000, None, self._mañana())
        self.assertEqual(r.calcular_aplicacion_cupon(
            c, [{"producto_id": a, "subtotal": 400}, {"producto_id": b, "subtotal": 600}])["aplicable"], 1000)

    def test_vencido_o_anulado_no_aplican(self):
        beb = self._prod("CU-B4", self.cat_beb)
        c = r.crear_cupon(500, self.cat_beb, self._mañana())
        items = [{"producto_id": beb, "subtotal": 1000}]
        calc = r.calcular_aplicacion_cupon(dict(c, fecha_hasta="2020-01-01"), items)
        self.assertEqual(calc["aplicable"], 0)
        self.assertIn("venció", calc["motivo"])

    # ── en la venta ──
    def test_venta_con_cupon_baja_el_total_y_la_caja(self):
        beb, alm = self._prod("CU-B5", self.cat_beb), self._prod("CU-A3", self.cat_alm)
        c = r.crear_cupon(500, self.cat_beb, self._mañana())
        antes = self._caja()
        vid = r.registrar_venta(self.sesion, [self._item(beb, 1, 1000), self._item(alm, 1, 2000)],
                                "efectivo", 0.0, cupon_id=c["id"])
        with db.get_connection() as cx:
            v = dict(cx.execute("SELECT * FROM ventas WHERE id=?", (vid,)).fetchone())
        self.assertEqual(v["total"], 2500)                                # 3000 - 500
        self.assertEqual((v["cupon_id"], v["cupon_monto"], v["descuento_monto"]), (c["id"], 500, 500))
        self.assertAlmostEqual(v["descuento_pct"], 500 / 3000 * 100)      # un solo % combinado
        self.assertEqual(v["monto_efectivo"], 2500)
        self.assertEqual(self._caja() - antes, 2500)                      # a la caja entra lo cobrado
        cup = r.get_cupon_por_codigo(c["codigo"])
        self.assertEqual((cup["monto_restante"], cup["estado"]), (0, "usado"))

    def test_cupon_de_un_solo_uso_se_consume_entero_aunque_la_compra_sea_menor(self):
        beb = self._prod("CU-B6", self.cat_beb)
        c = r.crear_cupon(500, self.cat_beb, self._mañana())              # sin saldo
        vid = r.registrar_venta(self.sesion, [self._item(beb, 1, 200)], "efectivo", 0.0, cupon_id=c["id"])
        with db.get_connection() as cx:
            self.assertEqual(cx.execute("SELECT total FROM ventas WHERE id=?", (vid,)).fetchone()[0], 0)
        self.assertEqual(r.get_cupon_por_codigo(c["codigo"])["estado"], "usado")

    def test_cupon_con_saldo_queda_disponible(self):
        beb = self._prod("CU-B7", self.cat_beb)
        c = r.crear_cupon(500, self.cat_beb, self._mañana(), permite_saldo=True)
        r.registrar_venta(self.sesion, [self._item(beb, 1, 200)], "efectivo", 0.0, cupon_id=c["id"])
        cup = r.get_cupon_por_codigo(c["codigo"])
        self.assertEqual((cup["monto_restante"], cup["estado"]), (300, "activo"))
        r.registrar_venta(self.sesion, [self._item(beb, 1, 1000)], "efectivo", 0.0, cupon_id=c["id"])
        self.assertEqual(r.get_cupon_por_codigo(c["codigo"])["estado"], "usado")

    def test_no_se_puede_usar_dos_veces_ni_vencido_y_no_deja_rastros(self):
        beb = self._prod("CU-B8", self.cat_beb, stock=10)
        c = r.crear_cupon(500, self.cat_beb, self._mañana())
        r.registrar_venta(self.sesion, [self._item(beb, 1, 1000)], "efectivo", 0.0, cupon_id=c["id"])
        caja, ventas = self._caja(), len(r.get_ventas_sesion(self.sesion))
        with self.assertRaises(ValueError):
            r.registrar_venta(self.sesion, [self._item(beb, 1, 1000)], "efectivo", 0.0, cupon_id=c["id"])
        self.assertEqual(self._caja(), caja)                              # la venta fallida no deja nada
        self.assertEqual(len(r.get_ventas_sesion(self.sesion)), ventas)
        with db.get_connection() as cx:
            self.assertEqual(cx.execute("SELECT COALESCE(SUM(cantidad_restante),0) FROM lotes WHERE producto_id=?", (beb,)).fetchone()[0], 9)

    def test_anular_la_venta_devuelve_el_cupon(self):
        beb = self._prod("CU-B9", self.cat_beb)
        c = r.crear_cupon(500, self.cat_beb, self._mañana())
        vid = r.registrar_venta(self.sesion, [self._item(beb, 1, 1000)], "efectivo", 0.0, cupon_id=c["id"])
        self.assertEqual(r.get_cupon_por_codigo(c["codigo"])["estado"], "usado")
        self.assertTrue(r.anular_venta(vid))
        cup = r.get_cupon_por_codigo(c["codigo"])
        self.assertEqual((cup["monto_restante"], cup["estado"]), (500, "activo"))
        r.registrar_venta(self.sesion, [self._item(beb, 1, 1000)], "efectivo", 0.0, cupon_id=c["id"])  # se puede reusar

    def test_cupon_mas_descuento_manual_y_cuenta_corriente(self):
        beb = self._prod("CU-B10", self.cat_beb)
        c = r.crear_cupon(300, self.cat_beb, self._mañana())
        cli = r.crear_cliente(str(id(self))[-8:], "Cli Cupon", "1", 100000)["id"]
        vid = r.registrar_venta(self.sesion, [self._item(beb, 1, 1000)], "cuenta_corriente",
                                10.0, cliente_id=cli, cupon_id=c["id"])          # 10% + cupon
        with db.get_connection() as cx:
            v = dict(cx.execute("SELECT * FROM ventas WHERE id=?", (vid,)).fetchone())
        self.assertEqual(v["total"], 600)                                  # 1000 - 100 - 300
        self.assertEqual(v["monto_cta_cte"], 600)
        self.assertEqual(next(x["saldo_actual"] for x in r.get_todos_clientes() if x["id"] == cli), 600)

    def test_si_se_borra_la_categoria_el_cupon_no_pasa_a_valer_para_todo(self):
        with db.get_connection() as cx:
            cat = cx.execute("INSERT INTO categorias (nombre) VALUES ('Efimera CUP')").lastrowid
            cx.commit()
        pid = self._prod("CU-E1", cat)
        c = r.crear_cupon(500, cat, self._mañana())
        with db.get_connection() as cx:
            cx.execute("PRAGMA foreign_keys=ON")
            cx.execute("DELETE FROM categorias WHERE id=?", (cat,))
            cx.commit()
        cup = r.get_cupon_por_codigo(c["codigo"])
        self.assertIsNone(cup["categoria_id"])
        calc = r.calcular_aplicacion_cupon(cup, [{"producto_id": pid, "subtotal": 1000}])
        self.assertEqual(calc["aplicable"], 0)
        self.assertIn("ya no existe", calc["motivo"])

    def test_el_ticket_muestra_el_cupon_separado_del_descuento(self):
        import impresion
        beb = self._prod("CU-T1", self.cat_beb)
        c = r.crear_cupon(200, self.cat_beb, self._mañana())
        vid = r.registrar_venta(self.sesion, [self._item(beb, 1, 1000)], "efectivo", 10.0, cupon_id=c["id"])
        txt = impresion.generar_texto_ticket(vid)
        self.assertIn("Descuento (10%)", txt)
        self.assertIn(f"Cupon {c['codigo']}", txt)
        self.assertIn("700.00", txt)                                       # 1000 - 100 - 200

    def test_texto_para_whatsapp(self):
        c = r.crear_cupon(1500, self.cat_beb, "2099-12-31", permite_saldo=True)
        t = r.texto_cupon(c, "Araí")
        for parte in ("1,500", "Bebidas CUP", c["codigo"], "31/12/2099", "Araí", "resto"):
            self.assertIn(parte, t)


class Flyer(unittest.TestCase):
    def test_chequeos(self):
        import ofertas_semana as o
        a = r.crear_producto("F1", "Flyer perdida", None, 1500, 1000)
        r.guardar_promocion(None, a, 1, 900.0, "directa", None, None)
        b = r.crear_producto("F2", "Flyer vence", None, 1500, 1000)
        r.guardar_promocion(None, b, 1, 1300.0, "vence", None,
                            (date.today() + timedelta(days=1)).isoformat())
        prods = [r.get_producto_completo(a), r.get_producto_completo(b)]
        graves, avisos = o.chequear_flyer(prods, "unitario", date.today() + timedelta(days=7))
        self.assertEqual(len(graves), 1)
        self.assertTrue(any("vence" in x for x in avisos))
        self.assertEqual(o.chequear_flyer(prods, "lista")[0], [])


if __name__ == "__main__":
    unittest.main(verbosity=1)

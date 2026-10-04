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

"""
movil_ingreso.py — Servidor local para cargar ingresos de stock desde
el celular, en la misma WiFi que esta PC.

Por que un servidor propio y no una app aparte: el celular necesita
escribir en la MISMA base SQLite que usa el TPV, al instante. Un
servidor HTTPS corriendo acá mismo, en un hilo de fondo, resuelve eso
sin depender de internet ni de un servicio externo — el celular solo
necesita estar en la misma red.

Va por HTTPS (no HTTP) a proposito: la camara del navegador
(getUserMedia) no funciona en iOS/Safari salvo que la pagina se sirva
por HTTPS — no hay forma de evitarlo, es una regla del sistema
operativo, no del navegador. Como no hay forma de conseguir un
certificado "de verdad" para una IP de red local, se genera uno propio
(autofirmado) la primera vez y se reutiliza — ver generar_certificado().
Esto es la UNICA parte del sistema que necesita una libreria de
terceros (pip install cryptography): Python no trae de fabrica ninguna
forma de generar certificados.

El resto sigue con la biblioteca estandar nada mas (nada de Flask). El
escaneo de codigo de barras en el celular usa BarcodeDetector, nativo
del navegador (Chrome/Edge en Android, y Safari en iOS ya con HTTPS) —
si el celular no lo soporta (Android muy viejo), el campo de codigo
sigue andando escribiendo a mano, igual que en la pantalla de
escritorio.
"""
import json
import logging
import os
import socket
import ssl
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

_servidor = None
_hilo = None

CARPETA_CERT = os.path.join(os.path.dirname(__file__), "certs")
RUTA_CERT = os.path.join(CARPETA_CERT, "movil_ingreso.crt")
RUTA_KEY = os.path.join(CARPETA_CERT, "movil_ingreso.key")


def ip_local() -> str:
    """IP de esta PC en la red local, para mostrarle al usuario la URL
    a la que tiene que entrar desde el celular."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def _certificado_sirve_para(ruta_cert: str, ip: str) -> bool:
    """True si el certificado ya guardado sigue siendo valido: no
    vencido y con esta IP incluida. Si la PC cambio de IP (DHCP) el
    certificado viejo no le va a servir a un navegador estricto como
    Safari, aunque siga siendo el mismo archivo — hay que rehacerlo."""
    try:
        from cryptography import x509
        with open(ruta_cert, "rb") as f:
            cert = x509.load_pem_x509_certificate(f.read())
        ahora = datetime.now(timezone.utc)
        if not (cert.not_valid_before_utc < ahora < cert.not_valid_after_utc):
            return False
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        ips_incluidas = {str(v) for v in san.value.get_values_for_type(x509.IPAddress)}
        return ip in ips_incluidas
    except Exception:
        return False


def generar_certificado(ip: str) -> tuple[str, str]:
    """Genera (o reutiliza) un certificado autofirmado para esta IP.

    Necesario porque una IP de red local (192.168.x.x) no puede tener
    un certificado "de verdad" firmado por una entidad reconocida —
    esas solo se emiten para dominios de internet. Sin esto, ningun
    navegador (y mucho menos Safari) va a habilitar la camara.

    OJO con dos reglas de Apple que si no se cumplen, Safari ni
    siquiera ofrece "continuar de todas formas" — directamente no
    conecta, sin ningun aviso claro de por que:
      - La validez no puede superar 398 dias (se usan 397 por las dudas).
      - Tiene que tener keyUsage / extendedKeyUsage(serverAuth) /
        basicConstraints(CA:FALSE) — un certificado autofirmado
        "pelado" sin estas extensiones no alcanza.
    Como la validez es corta a proposito, _certificado_sirve_para()
    se encarga de renovarlo solo cuando haga falta.
    """
    import ipaddress
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    os.makedirs(CARPETA_CERT, exist_ok=True)

    if os.path.exists(RUTA_CERT) and _certificado_sirve_para(RUTA_CERT, ip):
        return RUTA_CERT, RUTA_KEY

    logging.info(f"Generando certificado nuevo para {ip} "
                f"(no había uno, venció, o cambió la IP de la PC)")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nombre = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, ip)])
    ahora = datetime.now(timezone.utc)

    try:
        ip_obj = [x509.IPAddress(ipaddress.ip_address(ip))]
    except ValueError:
        ip_obj = []

    cert = (
        x509.CertificateBuilder()
        .subject_name(nombre)
        .issuer_name(nombre)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(ahora - timedelta(days=1))
        .not_valid_after(ahora + timedelta(days=395))
        .add_extension(
            x509.SubjectAlternativeName(
                ip_obj + [x509.DNSName("localhost")]),
            critical=False)
        .add_extension(
            x509.BasicConstraints(ca=False, path_length=None),
            critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, key_encipherment=True,
                content_commitment=False, data_encipherment=False,
                key_agreement=False, key_cert_sign=False, crl_sign=False,
                encipher_only=False, decipher_only=False),
            critical=True)
        .add_extension(
            x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False)
        .sign(key, hashes.SHA256())
    )

    with open(RUTA_CERT, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    with open(RUTA_KEY, "wb") as f:
        f.write(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption()))
    return RUTA_CERT, RUTA_KEY


def _ok(handler, payload, code=200):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _pin_valido(handler) -> bool:
    from config import cfg
    pin = (cfg().get("movil_ingreso_pin") or "").strip()
    if not pin:
        return True   # sin PIN configurado = sin restriccion (no recomendado)
    qs = parse_qs(urlparse(handler.path).query)
    enviado = handler.headers.get("X-PIN") or (qs.get("pin", [""])[0])
    return enviado == pin


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        logging.debug("movil_ingreso: " + fmt, *args)

    def _leer_json(self):
        largo = int(self.headers.get("Content-Length") or 0)
        crudo = self.rfile.read(largo) if largo else b"{}"
        try:
            return json.loads(crudo.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    def do_GET(self):
        ruta = urlparse(self.path).path
        try:
            if ruta == "/":
                body = _PAGINA.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif ruta == "/api/producto":
                if not _pin_valido(self):
                    return _ok(self, {"error": "PIN incorrecto"}, 401)
                qs = parse_qs(urlparse(self.path).query)
                codigo = (qs.get("codigo", [""])[0]).strip()
                from repositorio import get_producto_por_codigo
                p = get_producto_por_codigo(codigo)
                if not p:
                    return _ok(self, {"existe": False})
                from repositorio import get_stock_producto
                _ok(self, {
                    "existe": True,
                    "id": p["id"],
                    "descripcion": p["descripcion"],
                    "precio_base": p["precio_base"],
                    "costo_ultimo": p.get("costo_ultimo") or 0,
                    "vendido_por_peso": bool(p.get("vendido_por_peso")),
                    "stock_actual": get_stock_producto(p["id"]),
                })
            elif ruta == "/api/categorias":
                if not _pin_valido(self):
                    return _ok(self, {"error": "PIN incorrecto"}, 401)
                from repositorio import get_categorias
                _ok(self, {"categorias": get_categorias()})
            elif ruta == "/certificado.pem":
                # Sin PIN a proposito: hace falta poder bajarlo ANTES
                # de confiar en el sitio. No es informacion sensible,
                # es la parte publica del certificado.
                if not os.path.exists(RUTA_CERT):
                    self.send_response(404)
                    self.end_headers()
                    return
                with open(RUTA_CERT, "rb") as f:
                    body = f.read()
                self.send_response(200)
                # Este content-type es el que hace que Safari, al
                # abrir el link, ofrezca "Instalar perfil" en vez de
                # mostrar el archivo como texto. IMPORTANTE: sin
                # Content-Disposition — con "attachment" ahí, Safari lo
                # trata como una descarga cualquiera y nunca dispara la
                # pantalla nativa de instalar perfil.
                self.send_header("Content-Type", "application/x-x509-ca-cert")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()
        except Exception as e:
            logging.exception("movil_ingreso GET %s", ruta)
            _ok(self, {"error": str(e)}, 500)

    def do_POST(self):
        ruta = urlparse(self.path).path
        try:
            if not _pin_valido(self):
                return _ok(self, {"error": "PIN incorrecto"}, 401)
            datos = self._leer_json()

            if ruta == "/api/evaluar_costo":
                from repositorio import evaluar_cambio_costo
                info = evaluar_cambio_costo(
                    int(datos["producto_id"]), float(datos["costo"]))
                return _ok(self, info)

            if ruta == "/api/ingreso":
                return self._registrar_ingreso(datos)

            self.send_response(404)
            self.end_headers()
        except (KeyError, ValueError, TypeError) as e:
            _ok(self, {"error": f"Datos incompletos o inválidos: {e}"}, 400)
        except Exception as e:
            logging.exception("movil_ingreso POST %s", ruta)
            _ok(self, {"error": str(e)}, 500)

    def _registrar_ingreso(self, datos):
        from repositorio import (get_producto_por_codigo, crear_producto,
                                 registrar_lote, parsear_fecha)

        codigo = (datos.get("codigo") or "").strip()
        if not codigo:
            return _ok(self, {"error": "Falta el código."}, 400)

        cantidad = float(datos["cantidad"])
        costo = float(datos["costo"])
        if cantidad <= 0 or costo < 0:
            return _ok(self, {"error": "Cantidad y costo tienen que ser "
                                        "números válidos."}, 400)

        vence = None
        if datos.get("vencimiento"):
            vence = parsear_fecha(datos["vencimiento"])
            if not vence:
                return _ok(self, {"error": "No entiendo esa fecha de "
                                            "vencimiento."}, 400)

        prod = get_producto_por_codigo(codigo)
        if prod:
            prod_id = prod["id"]
            es_peso = bool(prod.get("vendido_por_peso"))
        else:
            # Producto nuevo: se necesitan estos datos desde el celular.
            desc = (datos.get("descripcion") or "").strip()
            if not desc:
                return _ok(self, {"error": "Ese código no existe en el "
                                            "catálogo. Hace falta la "
                                            "descripción para darlo de "
                                            "alta."}, 400)
            precio = float(datos.get("precio") or 0)
            cat_id = datos.get("categoria_id")
            if precio <= 0:
                from repositorio import get_categorias
                margen = 30.0
                if cat_id:
                    cats = {c["id"]: c for c in get_categorias()}
                    margen = cats.get(int(cat_id), {}).get("margen_pct") or 30.0
                precio = round(costo * (1 + margen / 100), 2)
            es_peso = bool(datos.get("vendido_por_peso"))
            prod_id = crear_producto(
                codigo, desc, int(cat_id) if cat_id else None, precio, costo,
                vendido_por_peso=es_peso,
                marca=(datos.get("marca") or "").strip() or None,
                fraccionable=bool(datos.get("fraccionable")))

        if not es_peso and cantidad != int(cantidad):
            return _ok(self, {"error": "Este producto se vende por unidad "
                                        "— la cantidad debe ser entera."}, 400)

        nuevo_precio = datos.get("nuevo_precio_venta")
        nuevo_precio = float(nuevo_precio) if nuevo_precio else None

        lote_id, _ = registrar_lote(
            prod_id, datos.get("proveedor_id"), cantidad, costo, vence,
            (datos.get("notas") or "") + " (cargado desde el celular)",
            nuevo_precio_venta=nuevo_precio)

        _ok(self, {"ok": True, "producto_id": prod_id, "lote_id": lote_id})


def iniciar_servidor(puerto: int = 8642):
    """Arranca el servidor en un hilo de fondo. Llamar una sola vez,
    al iniciar la app (si esta activo en Config).

    Va por HTTPS: sin esto, la camara no funciona en ningun iPhone
    (ver el docstring del modulo). Si por algun motivo no se puede
    generar el certificado (falta instalar "cryptography", por
    ejemplo), se cae a HTTP plano para que el resto — el formulario,
    el código escrito a mano — siga funcionando igual.
    """
    global _servidor, _hilo
    if _servidor is not None:
        return  # ya esta corriendo

    ip = ip_local()
    contexto = None
    try:
        ruta_cert, ruta_key = generar_certificado(ip)
        contexto = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        contexto.load_cert_chain(ruta_cert, ruta_key)
    except ModuleNotFoundError:
        logging.warning(
            "No está instalada la librería 'cryptography' (pip install "
            "cryptography) — el servidor de ingreso por celular arranca "
            "sin HTTPS. La cámara NO va a funcionar en iPhone así; "
            "escribir el código a mano sigue andando igual.")
    except Exception as e:
        logging.warning(f"No se pudo preparar HTTPS para el servidor de "
                        f"ingreso por celular, arranca sin cifrar: {e}")

    try:
        _servidor = ThreadingHTTPServer(("0.0.0.0", puerto), _Handler)
        if contexto:
            _servidor.socket = contexto.wrap_socket(
                _servidor.socket, server_side=True)
    except OSError as e:
        logging.error(f"No se pudo iniciar el servidor de ingreso "
                      f"por celular en el puerto {puerto}: {e}")
        _servidor = None
        return
    _hilo = threading.Thread(target=_servidor.serve_forever, daemon=True)
    _hilo.start()
    esquema = "https" if contexto else "http"
    logging.info(f"Servidor de ingreso por celular activo en "
                f"{esquema}://{ip}:{puerto}")


def url_servidor(puerto: int = None) -> str:
    """URL completa para mostrarle al usuario — con https:// si el
    servidor efectivamente levantó con certificado."""
    if puerto is None:
        puerto = _servidor.server_port if _servidor else 8642
    esquema = "https" if (_servidor and isinstance(
        getattr(_servidor, "socket", None), ssl.SSLSocket)) else "http"
    return f"{esquema}://{ip_local()}:{puerto}"


def detener_servidor():
    global _servidor, _hilo
    if _servidor:
        _servidor.shutdown()
        _servidor = None
        _hilo = None


_PAGINA = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ingreso de stock</title>
<style>
  :root { color-scheme: light; }
  * { box-sizing: border-box; }
  body { font-family: system-ui, sans-serif; margin: 0; background: #f3f4f6;
         color: #1f2937; }
  header { background: #2451B0; color: #fff; padding: 14px 16px;
           font-weight: 600; font-size: 1.1rem; }
  main { padding: 14px; max-width: 480px; margin: 0 auto; }
  .card { background: #fff; border-radius: 10px; padding: 14px;
          margin-bottom: 12px; box-shadow: 0 1px 3px rgba(0,0,0,.08); }
  label { display: block; font-size: .85rem; color: #6b7280;
          margin: 10px 0 4px; }
  input, select { width: 100%; padding: 10px; font-size: 1rem;
                  border: 1px solid #d1d5db; border-radius: 8px; }
  button { width: 100%; padding: 13px; font-size: 1rem; font-weight: 600;
           border: none; border-radius: 8px; margin-top: 12px; }
  .btn-primario { background: #2451B0; color: #fff; }
  .btn-secundario { background: #e5e7eb; color: #1f2937; }
  .btn-exito { background: #16a34a; color: #fff; }
  #video { width: 100%; border-radius: 8px; display: none; background: #000; }
  .producto-info { background: #eef2ff; border-radius: 8px; padding: 10px;
                    margin-top: 10px; font-size: .95rem; }
  .aviso { background: #fef3c7; border: 1px solid #f59e0b; border-radius: 8px;
           padding: 10px; margin-top: 10px; font-size: .9rem; }
  .error { background: #fee2e2; border: 1px solid #dc2626; color: #991b1b;
           border-radius: 8px; padding: 10px; margin-top: 10px; }
  .oculto { display: none !important; }
  .fila { display: flex; gap: 8px; }
  .fila > div { flex: 1; }
</style>
</head>
<body>
<header>📦 Ingreso de stock — celular</header>
<main>

  <div class="card" id="card-certificado" style="background:#fef9c3">
    <b>¿Primera vez en este celular?</b>
    <p style="font-size:.88rem;margin:6px 0">
      Para que la cámara funcione hace falta instalar y confiar en el
      certificado de este servidor (una sola vez).
      <b>En iPhone:</b> tocá el link de abajo — tiene que aparecer
      directo un cartel de "Perfil descargado" o "Instalar perfil"
      (no hace falta ir a buscar nada en Ajustes/Configuración antes).
      Tocá Instalar, poné tu código del celular si lo pide, y confirmá
      de nuevo. Recién <b>al final</b>, andá a Ajustes/Configuración →
      General → Información (Acerca de) → Confianza de certificados,
      y activá el certificado ahí — ese último paso es el que más se
      salta y sin él Safari lo sigue marcando como no confiable.
    </p>
    <a href="/certificado.pem" style="display:block;text-align:center;
       background:#2451B0;color:#fff;padding:10px;border-radius:8px;
       text-decoration:none;font-weight:600">⬇ Instalar certificado</a>
  </div>

  <div class="card">
    <label>PIN de acceso</label>
    <input id="pin" type="password" inputmode="numeric" placeholder="PIN">
  </div>

  <div class="card">
    <label>Código de barras</label>
    <div class="fila">
      <div><input id="codigo" type="text" placeholder="Escaneá o escribí el código"
                  inputmode="numeric"></div>
    </div>
    <button class="btn-secundario" id="btn-camara">📷 Escanear con la cámara</button>
    <video id="video" playsinline></video>
    <div id="info-producto"></div>
  </div>

  <div class="card oculto" id="card-datos">
    <div class="fila">
      <div>
        <label>Cantidad</label>
        <input id="cantidad" type="number" step="any" inputmode="decimal">
      </div>
      <div>
        <label>Costo unitario ($)</label>
        <input id="costo" type="number" step="any" inputmode="decimal">
      </div>
    </div>
    <label>Vencimiento (opcional)</label>
    <input id="vencimiento" type="text" placeholder="DD/MM/AAAA">
    <label>Notas (opcional)</label>
    <input id="notas" type="text">

    <div id="alta-producto" class="oculto">
      <div class="aviso">Este código no está en el catálogo — se va a crear
        un producto nuevo con estos datos.</div>
      <label>Descripción</label>
      <input id="descripcion" type="text">
      <label>Categoría</label>
      <select id="categoria"></select>
      <label>Precio de venta (vacío = calculado por margen)</label>
      <input id="precio" type="number" step="any" inputmode="decimal">
    </div>

    <div id="cambio-costo"></div>

    <button class="btn-exito" id="btn-guardar">Registrar ingreso</button>
  </div>

  <div id="resultado"></div>

</main>
<script>
const $ = (id) => document.getElementById(id);
let productoActual = null;   // {existe, id, ...} de /api/producto
let nuevoPrecioVenta = null;

function pin() { return $("pin").value.trim(); }

async function api(ruta, opciones = {}) {
  const url = ruta + (ruta.includes("?") ? "&" : "?") + "pin=" + encodeURIComponent(pin());
  const resp = await fetch(url, opciones);
  const json = await resp.json();
  if (!resp.ok) throw new Error(json.error || ("Error " + resp.status));
  return json;
}

async function cargarCategorias() {
  try {
    const r = await api("/api/categorias");
    const sel = $("categoria");
    sel.innerHTML = "";
    for (const c of r.categorias) {
      const o = document.createElement("option");
      o.value = c.id; o.textContent = c.nombre;
      sel.appendChild(o);
    }
  } catch (e) { /* se reintenta cuando haga falta */ }
}

async function buscarProducto() {
  const codigo = $("codigo").value.trim();
  const info = $("info-producto");
  const cardDatos = $("card-datos");
  const altaProducto = $("alta-producto");
  info.innerHTML = "";
  nuevoPrecioVenta = null;
  $("cambio-costo").innerHTML = "";
  if (!codigo) { cardDatos.classList.add("oculto"); return; }

  try {
    productoActual = await api("/api/producto?codigo=" + encodeURIComponent(codigo));
  } catch (e) {
    info.innerHTML = `<div class="error">${e.message}</div>`;
    return;
  }

  cardDatos.classList.remove("oculto");
  if (productoActual.existe) {
    altaProducto.classList.add("oculto");
    info.innerHTML = `<div class="producto-info">
        <b>${productoActual.descripcion}</b><br>
        Precio actual: $ ${productoActual.precio_base.toFixed(2)}
        &nbsp;·&nbsp; Stock: ${productoActual.stock_actual}
        ${productoActual.vendido_por_peso ? " kg" : ""}
      </div>`;
    $("cantidad").step = productoActual.vendido_por_peso ? "any" : "1";
  } else {
    altaProducto.classList.remove("oculto");
    info.innerHTML = "";
    if (!$("categoria").options.length) cargarCategorias();
  }
}

$("codigo").addEventListener("change", buscarProducto);
$("costo").addEventListener("change", async () => {
  $("cambio-costo").innerHTML = "";
  nuevoPrecioVenta = null;
  if (!productoActual || !productoActual.existe) return;
  const costo = parseFloat($("costo").value);
  if (!costo || costo <= 0) return;
  try {
    const info = await api("/api/evaluar_costo", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({producto_id: productoActual.id, costo}),
    });
    if (info.direccion === "igual") return;
    const div = $("cambio-costo");
    if (info.direccion === "subio" &&
        Math.round(info.precio_sugerido*100) !== Math.round(info.precio_actual*100)) {
      div.innerHTML = `<div class="aviso">
          El costo pasó de $ ${info.costo_anterior.toFixed(2)} a $ ${costo.toFixed(2)}.<br>
          Precio actual: $ ${info.precio_actual.toFixed(2)} ·
          Precio sugerido: $ ${info.precio_sugerido.toFixed(2)}<br>
          <label style="margin-top:8px"><input type="checkbox" id="chk-precio" checked>
          Actualizar el precio de venta</label>
        </div>`;
      $("chk-precio").addEventListener("change", (e) => {
        nuevoPrecioVenta = e.target.checked ? info.precio_sugerido : null;
      });
      nuevoPrecioVenta = info.precio_sugerido;
    } else if (info.direccion === "bajo") {
      div.innerHTML = `<div class="aviso">
          El costo bajó a $ ${costo.toFixed(2)}. Precio sugerido:
          $ ${info.precio_sugerido.toFixed(2)} (queda igual si no lo tildás).<br>
          <label style="margin-top:8px"><input type="checkbox" id="chk-precio">
          Actualizar el precio de venta</label>
        </div>`;
      $("chk-precio").addEventListener("change", (e) => {
        nuevoPrecioVenta = e.target.checked ? info.precio_sugerido : null;
      });
    }
  } catch (e) { /* no bloquea el ingreso si esto falla */ }
});

$("btn-guardar").addEventListener("click", async () => {
  const resultado = $("resultado");
  resultado.innerHTML = "";
  const payload = {
    codigo: $("codigo").value.trim(),
    cantidad: $("cantidad").value,
    costo: $("costo").value,
    vencimiento: $("vencimiento").value.trim(),
    notas: $("notas").value.trim(),
    nuevo_precio_venta: nuevoPrecioVenta,
  };
  if (productoActual && !productoActual.existe) {
    payload.descripcion = $("descripcion").value.trim();
    payload.categoria_id = $("categoria").value || null;
    payload.precio = $("precio").value || null;
  }
  try {
    const r = await api("/api/ingreso", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload),
    });
    resultado.innerHTML = `<div class="card" style="background:#dcfce7">
        ✅ Ingreso registrado.</div>`;
    // Limpiar para cargar el siguiente producto
    ["codigo","cantidad","costo","vencimiento","notas","descripcion","precio"]
      .forEach(id => $(id).value = "");
    $("card-datos").classList.add("oculto");
    $("info-producto").innerHTML = "";
    $("codigo").focus();
  } catch (e) {
    resultado.innerHTML = `<div class="error">${e.message}</div>`;
  }
});

// Escaneo con la cámara — BarcodeDetector nativo del navegador. Si el
// telefono no lo tiene (iPhone, Android viejo), el boton avisa y queda
// la opcion de escribir el codigo a mano.
$("btn-camara").addEventListener("click", async () => {
  if (!("BarcodeDetector" in window)) {
    alert("Este navegador no puede escanear código de barras con la "
        + "cámara (pasa en iPhone y algunos Android viejos). "
        + "Escribí el código a mano en el campo de arriba.");
    return;
  }
  const video = $("video");
  video.style.display = "block";
  try {
    const stream = await navigator.mediaDevices.getUserMedia(
      { video: { facingMode: "environment" } });
    video.srcObject = stream;
    await video.play();
    const detector = new BarcodeDetector(
      { formats: ["ean_13", "ean_8", "upc_a", "upc_e", "code_128"] });
    const intervalo = setInterval(async () => {
      try {
        const codigos = await detector.detect(video);
        if (codigos.length) {
          $("codigo").value = codigos[0].rawValue;
          clearInterval(intervalo);
          stream.getTracks().forEach(t => t.stop());
          video.style.display = "none";
          buscarProducto();
        }
      } catch (e) { /* sigue intentando */ }
    }, 400);
  } catch (e) {
    alert("No se pudo abrir la cámara: " + e.message);
    video.style.display = "none";
  }
});
</script>
</body>
</html>
"""

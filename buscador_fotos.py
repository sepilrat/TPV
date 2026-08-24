"""
buscador_fotos.py — Ventana de búsqueda de fotos embebida (Google Imágenes),
para elegir la foto de un producto sin salir a un navegador externo.

Corre como PROCESO APARTE (no se puede embeber en el mismo proceso que la
ventana principal de Tkinter: pywebview exige correr en el hilo principal,
y ese hilo ya lo tiene ocupado la ventana de la app). Al hacer click en una
foto de los resultados, imprime la URL elegida por stdout (última línea) y
cierra la ventana sola.

Uso: python buscador_fotos.py "texto a buscar"
"""
import sys
import webview
from urllib.parse import quote

JS_INTERCEPTAR_CLICKS = """
(function() {
    if (window._tpv_click_instalado) return;
    window._tpv_click_instalado = true;

    // Bing y Google guardan la URL de la foto GRANDE en atributos del
    // enlace que envuelve la miniatura. Si se toma el src del <img> se
    // termina guardando la miniatura de 200px, que en la etiqueta se ve
    // pixelada.
    function urlGrande(el) {
        var a = el.closest('a');
        if (a) {
            // Bing: JSON en el atributo m, con la url en "murl"
            var m = a.getAttribute('m');
            if (m) {
                try {
                    var o = JSON.parse(m.replace(/&quot;/g, '"'));
                    if (o.murl) { return o.murl; }
                } catch (err) { /* sigue con las otras formas */ }
            }
            // Google y otros: la url viene como parametro imgurl
            var href = a.getAttribute('href') || '';
            var mm = href.match(/[?&](imgurl|mediaurl)=([^&]+)/i);
            if (mm) { return decodeURIComponent(mm[2]); }
        }
        var img = el.closest('img') ||
                  (el.querySelector ? el.querySelector('img') : null);
        if (img) {
            // data-src: la url real cuando la imagen todavia no cargo
            return img.getAttribute('data-src') || img.src || '';
        }
        return '';
    }

    function manejar(e) {
        // Se busca hacia arriba desde donde se toco: Bing envuelve cada
        // resultado en varias capas y el click casi nunca cae justo
        // sobre el <img>.
        var nodo = e.target;
        for (var i = 0; i < 6 && nodo; i++) {
            var u = urlGrande(nodo);
            if (u && u.indexOf('http') === 0) {
                e.preventDefault();
                e.stopPropagation();
                window.pywebview.api.elegir_foto(u);
                return;
            }
            nodo = nodo.parentElement;
        }
    }

    // capture=true para llegar antes que el visor propio del buscador,
    // que es el que abria la imagen grande en vez de dejar elegirla.
    document.addEventListener('click', manejar, true);
    document.addEventListener('mousedown', function(e) {
        // Bing abre su visor en mousedown: hay que frenarlo antes
        var nodo = e.target;
        for (var i = 0; i < 6 && nodo; i++) {
            if (urlGrande(nodo)) { e.stopPropagation(); return; }
            nodo = nodo.parentElement;
        }
    }, true);
})();
"""


class API:
    def __init__(self):
        self.elegida = None

    def elegir_foto(self, url):
        self.elegida = url
        webview.windows[0].destroy()


def main():
    query = sys.argv[1] if len(sys.argv) > 1 else ""
    # Google pide captcha apenas detecta que no es un navegador normal, y
    # resolverlo cada vez hace inusable la busqueda. Bing y DuckDuckGo no
    # lo piden, asi que se arranca por ahi y Google queda como ultimo
    # recurso (se puede cambiar con el segundo argumento).
    motor = (sys.argv[2] if len(sys.argv) > 2 else "bing").lower()
    MOTORES = {
        "bing": f"https://www.bing.com/images/search?q={quote(query)}&qft=+filterui:photo-photo",
        "duckduckgo": f"https://duckduckgo.com/?q={quote(query)}&iax=images&ia=images",
        "google": f"https://www.google.com/search?tbm=isch&q={quote(query)}",
    }
    url_busqueda = MOTORES.get(motor, MOTORES["bing"])

    api = API()
    ventana = webview.create_window(
        f"Elegí una foto (click para usarla) — {query}",
        url_busqueda, width=1000, height=750, js_api=api)

    def _inyectar():
        try:
            ventana.evaluate_js(JS_INTERCEPTAR_CLICKS)
        except Exception:
            pass

    ventana.events.loaded += _inyectar
    webview.start()

    if api.elegida:
        print(api.elegida)


if __name__ == "__main__":
    main()

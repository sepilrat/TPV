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
    document.addEventListener('click', function(e) {
        var img = e.target.closest('img');
        if (img && img.src && img.src.indexOf('http') === 0) {
            e.preventDefault();
            e.stopPropagation();
            window.pywebview.api.elegir_foto(img.src);
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
    url_busqueda = f"https://www.google.com/search?tbm=isch&q={quote(query)}"

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

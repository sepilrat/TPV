/**
 * Apps Script para la Google Sheet "Catálogo" — TPV Araí
 *
 * QUÉ HACE (todo con UNA sola URL, sin hosting externo):
 * 1) Recibe el catálogo que le manda el TPV (POST) y lo guarda en la
 *    hoja "Catalogo".
 * 2) Sirve la página del pedido a los clientes (GET normal).
 * 3) Le contesta el catálogo en JSON a la propia página del pedido
 *    (GET con ?catalogo=1) — así no hace falta "publicar como CSV"
 *    por separado.
 *
 * CÓMO INSTALARLO (una sola vez):
 * 1. Crear una Google Sheet nueva y vacía. Nombre, ej "Catálogo Araí".
 * 2. Extensiones > Apps Script.
 * 3. Borrar el código de ejemplo y pegar TODO este archivo (reemplaza
 *    el archivo "Code.gs" que ya viene).
 * 4. En el panel de la izquierda, "+" al lado de "Archivos" > "HTML".
 *    Ponerle de nombre exactamente:  pedido
 *    (sin .html, Apps Script se lo agrega solo)
 * 5. Ahí pegar TODO el contenido del archivo pedido.html que te pasé
 *    aparte.
 * 6. Arriba a la derecha, "Implementar" > "Nueva implementación".
 * 7. Tipo: "Aplicación web".
 *    - Ejecutar como: Yo (tu cuenta)
 *    - Quién tiene acceso: Cualquier usuario
 * 8. "Implementar". Autorizar permisos cuando lo pida.
 * 9. Copiar la URL que te da ("URL de la aplicación web"). ESA URL
 *    sirve para las DOS cosas:
 *      - Pegarla en el TPV, Config > Catálogo web > URL de sincronización.
 *      - Mandarsela a los clientes tal cual, para que hagan su pedido.
 *
 * Cada vez que cambies este código o el HTML, hay que hacer una
 * implementación nueva (Implementar > Gestionar implementaciones >
 * lápiz de editar > Nueva versión) para que se aplique a la URL ya usada.
 */

const NOMBRE_HOJA = "Catalogo";

function doPost(e) {
  try {
    const datos = JSON.parse(e.postData.contents);
    const productos = datos.productos || [];

    const ss = SpreadsheetApp.getActiveSpreadsheet();
    let hoja = ss.getSheetByName(NOMBRE_HOJA);
    if (!hoja) {
      hoja = ss.insertSheet(NOMBRE_HOJA);
    }
    hoja.clear();

    const encabezados = ["codigo", "descripcion", "marca", "categoria", "precio"];
    const filas = [encabezados];
    productos.forEach(function (p) {
      filas.push([
        p.codigo || "",
        p.descripcion || "",
        p.marca || "",
        p.categoria || "",
        p.precio || 0,
      ]);
    });

    hoja.getRange(1, 1, filas.length, encabezados.length).setValues(filas);

    return ContentService
      .createTextOutput(JSON.stringify({ ok: true, cantidad: productos.length }))
      .setMimeType(ContentService.MimeType.JSON);
  } catch (err) {
    return ContentService
      .createTextOutput(JSON.stringify({ ok: false, error: String(err) }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}

function doGet(e) {
  // La propia página del pedido pide el catálogo con ?catalogo=1
  if (e.parameter && e.parameter.catalogo === "1") {
    return responderCatalogoJSON();
  }
  // Cualquier otro GET (el cliente abriendo el link) = la página del pedido
  return HtmlService.createHtmlOutputFromFile("pedido")
    .setTitle("Mayorista Araí — Hacé tu pedido")
    .addMetaTag("viewport", "width=device-width, initial-scale=1")
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

function responderCatalogoJSON() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const hoja = ss.getSheetByName(NOMBRE_HOJA);
  if (!hoja || hoja.getLastRow() < 2) {
    return ContentService
      .createTextOutput(JSON.stringify({ productos: [] }))
      .setMimeType(ContentService.MimeType.JSON);
  }
  const valores = hoja.getDataRange().getValues();
  const encabezados = valores[0].map(function (h) { return String(h).trim().toLowerCase(); });
  const productos = valores.slice(1)
    .filter(function (fila) { return fila[encabezados.indexOf("descripcion")]; })
    .map(function (fila) {
      const obj = {};
      encabezados.forEach(function (h, i) { obj[h] = fila[i]; });
      return obj;
    });
  return ContentService
    .createTextOutput(JSON.stringify({ productos: productos }))
    .setMimeType(ContentService.MimeType.JSON);
}

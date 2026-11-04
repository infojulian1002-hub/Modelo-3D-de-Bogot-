import { writeFileSync } from "node:fs";
const esperar = (ms) => new Promise((r) => setTimeout(r, ms));

const lista = await fetch("http://127.0.0.1:9222/json").then((r) => r.json());
const pagina =
  lista.find((t) => t.type === "page" && t.url.includes("127.0.0.1:8000")) ||
  lista.find((t) => t.type === "page");
if (!pagina) throw new Error("No hay pestaña de página en Edge");
console.log("Pestaña:", pagina.url, pagina.title);

const ws = new WebSocket(pagina.webSocketDebuggerUrl);
let siguienteId = 0;
const pendientes = new Map();
const mensajes = [];

ws.addEventListener("message", (evento) => {
  const mensaje = JSON.parse(evento.data);
  if (mensaje.id) {
    const pendiente = pendientes.get(mensaje.id);
    if (pendiente) {
      pendientes.delete(mensaje.id);
      if (mensaje.error) pendiente.reject(new Error(JSON.stringify(mensaje.error)));
      else pendiente.resolve(mensaje.result);
    }
    return;
  }
  if (mensaje.method === "Runtime.consoleAPICalled") {
    const texto = mensaje.params.args
      .map((a) => a.value ?? a.description ?? a.type)
      .join(" ");
    mensajes.push({ tipo: mensaje.params.type, texto });
  }
  if (mensaje.method === "Runtime.exceptionThrown") {
    mensajes.push({
      tipo: "exception",
      texto: mensaje.params.exceptionDetails?.exception?.description ||
        mensaje.params.exceptionDetails?.text,
    });
  }
  if (mensaje.method === "Log.entryAdded") {
    mensajes.push({
      tipo: mensaje.params.entry.level,
      texto: mensaje.params.entry.text,
      url: mensaje.params.entry.url,
    });
  }
});

function enviar(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = ++siguienteId;
    pendientes.set(id, { resolve, reject });
    ws.send(JSON.stringify({ id, method, params }));
  });
}

await new Promise((resolve, reject) => {
  ws.addEventListener("open", resolve, { once: true });
  ws.addEventListener("error", reject, { once: true });
});

await enviar("Runtime.enable");
await enviar("Log.enable");
await enviar("Page.enable");
await enviar("Page.bringToFront");
await enviar("Page.navigate", { url: "http://127.0.0.1:8000/?v=13&cubo=1" });
await esperar(2000);
mensajes.length = 0;
await esperar(30000);

const evaluacion = await enviar("Runtime.evaluate", {
  expression: `(async () => {
    let estiloHttp = null;
    try { estiloHttp = (await fetch('https://tiles.openfreemap.org/styles/liberty', {cache:'no-store'})).status; }
    catch (e) { estiloHttp = String(e); }
    let indiceHttp = null;
    try { indiceHttp = (await fetch('models/bloques/index.json', {cache:'no-store'})).status; }
    catch (e) { indiceHttp = String(e); }
    const canvas = document.querySelector('#map canvas');
    const mapa = window.__mapa;
    const mul = (m, v) => [
      m[0]*v[0] + m[4]*v[1] + m[8]*v[2] + m[12]*v[3],
      m[1]*v[0] + m[5]*v[1] + m[9]*v[2] + m[13]*v[3],
      m[2]*v[0] + m[6]*v[1] + m[10]*v[2] + m[14]*v[3],
      m[3]*v[0] + m[7]*v[1] + m[11]*v[2] + m[15]*v[3],
    ];
    const centro = mapa?.getCenter?.();
    const mcCentro = centro ? maplibregl.MercatorCoordinate.fromLngLat([centro.lng, centro.lat], 0) : null;
    const mc4 = mcCentro ? [mcCentro.x, mcCentro.y, mcCentro.z, 1] : null;
    const proj = window.__capa?.camera?.projectionMatrix?.elements;
    const sinFlip = window.__projSinFlip;
    let clipCentro = null;
    let clipCentroSinFlip = null;
    if (proj && mc4) {
      const c = mul(proj, mc4);
      clipCentro = [c[0]/c[3], c[1]/c[3], c[2]/c[3]];
    }
    if (sinFlip && mc4) {
      const c = mul(sinFlip, mc4);
      clipCentroSinFlip = [c[0]/c[3], c[1]/c[3], c[2]/c[3]];
    }
    let glbFetch = null;
    try {
      const r = await fetch('models/bloques/bloque_sw.glb', {cache:'no-store'});
      const b = await r.arrayBuffer();
      glbFetch = { status: r.status, bytes: b.byteLength };
    } catch (e) { glbFetch = String(e); }
    let dracoFetch = null;
    try {
      const r = await fetch('https://www.gstatic.com/draco/versioned/decoders/1.5.7/draco_decoder.wasm', {cache:'no-store'});
      dracoFetch = { status: r.status, bytes: (await r.arrayBuffer()).byteLength };
    } catch (e) { dracoFetch = String(e); }
    return {
      glbFetch,
      dracoFetch,
      webgl2: !!document.createElement('canvas').getContext('webgl2'),
      visibilidad: document.visibilityState,
      oculto: document.hidden,
      estiloCargado: mapa?.isStyleLoaded?.(),
      canvas: !!canvas,
      canvasSize: canvas ? [canvas.width, canvas.height] : null,
      cargandoClase: document.querySelector('#cargando')?.className,
      aviso: document.querySelector('#aviso')?.textContent,
      mapaCargado: mapa?.loaded?.(),
      mapaEstilo: mapa?.getStyle?.() ? 'presente' : 'ausente',
      capas: mapa?.getStyle?.()?.layers?.length ?? null,
      tieneTerreno: !!mapa?.getSource?.('terrain'),
      tieneCapaGlb: !!mapa?.getLayer?.('bogota-3d'),
      bloquesCargados: window.__estado?.capa?.bloques?.length ?? null,
      erroresCapa: window.__estado?.capa?.errores ?? null,
      diag: window.__diag ?? null,
      fuentes: mapa?.getStyle?.()?.sources ? Object.keys(mapa.getStyle().sources) : null,
      fuenteBase: (() => {
        try {
          const s = mapa.getSource('openmaptiles');
          return s ? { tipo: s.type, cargada: s.loaded?.(), tiles: s.tiles?.length ?? null } : null;
        } catch (e) { return String(e); }
      })(),
      erroresMapa: window.__erroresMapa ?? null,
      renderInfo: window.__renderInfo ?? null,
      clip: window.__clip ?? null,
      clipCentro,
      clipCentroSinFlip,
      mcCentro: mcCentro ? [mcCentro.x, mcCentro.y, mcCentro.z] : null,
      grupoMatriz: window.__capa?.bloques?.[0]?.grupo?.matrix?.elements ?? null,
      camara: window.__capa?.camera?.projectionMatrix?.elements ?? null,
      centro: mapa?.getCenter?.() ? { lng: mapa.getCenter().lng, lat: mapa.getCenter().lat, zoom: mapa.getZoom() } : null,
      estiloHttp,
      indiceHttp,
      recursos: performance.getEntriesByType('resource')
        .filter((r) => /openfreemap|maplibre|three|glb|sitios|index\\.json/.test(r.name))
        .map((r) => ({
          nombre: r.name.split('/').slice(-2).join('/'),
          url: r.name,
          duracion: Math.round(r.duration),
          bytes: r.transferSize,
          estado: r.responseStatus ?? null,
        }))
    };
  })()`,
  awaitPromise: true,
  returnByValue: true,
});

console.log("=== EVALUACIÓN ===");
console.log(JSON.stringify(evaluacion.result?.value ?? evaluacion, null, 2));

const captura = await enviar("Page.captureScreenshot", { format: "png" });
writeFileSync("data/mapa_diagnostico.png", Buffer.from(captura.data, "base64"));
console.log("Captura guardada en data/mapa_diagnostico.png");
console.log("=== MENSAJES ===");
for (const mensaje of mensajes) {
  console.log(`[${mensaje.tipo}] ${mensaje.texto}${mensaje.url ? ` (${mensaje.url})` : ""}`);
}
ws.close();

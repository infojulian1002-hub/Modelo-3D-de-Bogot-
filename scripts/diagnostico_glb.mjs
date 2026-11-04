const esperar = (ms) => new Promise((r) => setTimeout(r, ms));
const lista = await fetch("http://127.0.0.1:9222/json").then((r) => r.json());
const pagina =
  lista.find((t) => t.type === "page" && t.url.includes("127.0.0.1:8000")) ||
  lista.find((t) => t.type === "page");
if (!pagina) throw new Error("No hay página");

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
    mensajes.push({
      tipo: mensaje.params.type,
      texto: mensaje.params.args.map((a) => a.value ?? a.description ?? a.type).join(" "),
    });
  }
  if (mensaje.method === "Runtime.exceptionThrown") {
    mensajes.push({
      tipo: "exception",
      texto: mensaje.params.exceptionDetails?.exception?.description ||
        mensaje.params.exceptionDetails?.text,
    });
  }
  if (mensaje.method === "Log.entryAdded") {
    mensajes.push({ tipo: mensaje.params.entry.level, texto: mensaje.params.entry.text });
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
await enviar("Page.navigate", { url: "http://127.0.0.1:8000/prueba_glb.html" });
await esperar(2000);
mensajes.length = 0;
await esperar(60000);

const evaluacion = await enviar("Runtime.evaluate", {
  expression: `({
    estado: document.body.dataset.estado || null,
    texto: document.getElementById('estado')?.textContent,
    recursos: performance.getEntriesByType('resource')
      .filter((r) => /glb|draco|gstatic/.test(r.name))
      .map((r) => ({ url: r.name, ms: Math.round(r.duration), bytes: r.transferSize, estado: r.responseStatus ?? null }))
  })`,
  returnByValue: true,
});
console.log(JSON.stringify(evaluacion.result?.value ?? evaluacion, null, 2));
console.log("=== MENSAJES ===");
for (const m of mensajes) console.log(`[${m.tipo}] ${m.texto}`);
ws.close();

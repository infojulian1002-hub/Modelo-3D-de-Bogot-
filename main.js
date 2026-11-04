import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { DRACOLoader } from "three/addons/loaders/DRACOLoader.js";

const CENTRO = [-74.0715, 4.6085];
const BBOX = [-74.085, 4.593, -74.055, 4.625];
const INDICE_MODELO = "models/zona/index.json";
const DRACO_DECODER = "vendor/draco/";
const VISTA_INICIAL = { center: CENTRO, zoom: 13.6, pitch: 58, bearing: 20 };
const REDUCIR_MOVIMIENTO = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

const $ = (id) => document.getElementById(id);
const estado = {
  capa: null,
  sitios: null,
  terreno: true,
  exageracion: 1,
  vueloActivo: false,
  bloquesCargados: 0,
};

function escaparHtml(texto) {
  return String(texto ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

let temporizadorAviso = null;
function mostrarAviso(texto, duracion = 6500) {
  const aviso = $("aviso");
  if (!aviso) return;
  aviso.textContent = texto;
  aviso.hidden = false;
  clearTimeout(temporizadorAviso);
  temporizadorAviso = setTimeout(() => {
    aviso.hidden = true;
  }, duracion);
}

function actualizarCarga(porcentaje, texto) {
  const barra = $("barra-progreso");
  const etiqueta = $("cargando-texto");
  if (barra) barra.style.width = `${Math.max(0, Math.min(100, porcentaje))}%`;
  if (etiqueta && texto) etiqueta.textContent = texto;
}

function ocultarCarga() {
  const capa = $("cargando");
  if (capa) capa.classList.add("oculto");
}

function primerLayer(...ids) {
  return ids.find((id) => map.getLayer(id));
}

/* ------------------------------------------------------------------ */
/* Capa three.js para los bloques GLB                                  */
/* ------------------------------------------------------------------ */

class CapaBogota {
  constructor(opciones = {}) {
    this.id = "bogota-3d";
    this.type = "custom";
    this.renderingMode = "3d";
    this.opciones = opciones;
    this.visible = true;
    this.exageracion = 1;
    this.bloques = [];
    this.errores = [];
    this.map = null;
    this.renderer = null;
    this.scene = null;
    this.camera = null;
  }

  onAdd(map, gl) {
    this.map = map;
    this.camera = new THREE.Camera();
    this.scene = new THREE.Scene();
    this.renderer = new THREE.WebGLRenderer({
      canvas: map.getCanvas(),
      context: gl,
      antialias: true,
    });
    this.renderer.autoClear = false;
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.05;

    const hemi = new THREE.HemisphereLight(0xffffff, 0x5c6a5c, 1.45);
    hemi.position.set(0, 0, 1);
    this.scene.add(hemi);

    const sol = new THREE.DirectionalLight(0xfff4e6, 2.4);
    sol.position.set(-0.6, 0.9, 1.2);
    this.scene.add(sol);

    const relleno = new THREE.AmbientLight(0xffffff, 0.55);
    this.scene.add(relleno);

    this.cargar();
  }

  async cargar() {
    const loader = new GLTFLoader();
    const draco = new DRACOLoader();
    draco.setDecoderPath(DRACO_DECODER);
    loader.setDRACOLoader(draco);

    try {
      const indice = await fetch(INDICE_MODELO, { cache: "no-cache" }).then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status} al leer index.json`);
        return r.json();
      });
      const entradas = Object.entries(indice.bloques || {});
      if (!entradas.length) throw new Error("El índice de bloques está vacío.");

      let completados = 0;
      await Promise.allSettled(
        entradas.map(async ([nombre, info], indice) => {
          try {
            actualizarCarga(10 + (indice / entradas.length) * 75, `Cargando modelo…`);
            const gltf = await loader.loadAsync(info.archivo);
            const grupo = this.crearGrupo(info, gltf);
            this.scene.add(grupo);
            this.bloques.push({ info, grupo });
            completados += 1;
            this.opciones.onProgress?.(completados / entradas.length, nombre);
          } catch (error) {
            console.error(`No se pudo cargar el bloque ${nombre}`, error);
            this.errores.push(`${nombre}: ${error.message || error}`);
            completados += 1;
          }
        }),
      );

      this.aplicarExageracion(this.exageracion);
      this.map?.triggerRepaint();
      this.opciones.onReady?.(this.bloques.length, this.errores);
    } catch (error) {
      console.error("Error cargando el modelo 3D", error);
      this.errores.push(error.message || String(error));
      this.opciones.onReady?.(0, this.errores);
    }
  }

  crearGrupo(info, gltf) {
    const grupo = new THREE.Group();
    grupo.matrixAutoUpdate = false;
    grupo.name = `bloque-${info.origen.lat}-${info.origen.lon}`;

    const modelo = gltf.scene;
    modelo.traverse((objeto) => {
      if (!objeto.isMesh) return;
      objeto.frustumCulled = false;
      objeto.castShadow = false;
      objeto.receiveShadow = false;

      // El GLB no trae normales. Si three.js las deriva en el shader, las coordenadas
      // Mercator (muy pequeñas) las vuelven ruido y salen puntos negros en los techos.
      objeto.geometry = objeto.geometry.toNonIndexed();
      objeto.geometry.computeVertexNormals();

      const nombre = (objeto.name || "").toLowerCase();
      const materiales = Array.isArray(objeto.material) ? objeto.material : [objeto.material];
      for (const material of materiales) {
        if (!material) continue;
        material.flatShading = false;
        material.needsUpdate = true;
        material.metalness = 0.0;
        material.roughness = 0.9;
        if (nombre.includes("via")) {
          material.color.set("#2f2f2f");
          material.side = THREE.DoubleSide;
          material.roughness = 0.95;
        } else if (nombre.includes("agua")) {
          material.color.set("#3d7fae");
          material.side = THREE.DoubleSide;
          material.emissive.set("#3d7fae");
          material.emissiveIntensity = 0.6;
          material.roughness = 0.35;
          material.metalness = 0.1;
        } else if (nombre.includes("verde")) {
          material.color.set("#5e8f4e");
          material.side = THREE.DoubleSide;
          material.emissive.set("#5e8f4e");
          material.emissiveIntensity = 0.6;
          material.roughness = 0.95;
        }
      }
    });

    grupo.add(modelo);
    this.actualizarMatriz(grupo, info);
    return grupo;
  }

  actualizarMatriz(grupo, info) {
    const factor = this.exageracion;
    const origen = info.origen;
    const mc = maplibregl.MercatorCoordinate.fromLngLat([origen.lon, origen.lat], 0);
    const escala = mc.meterInMercatorCoordinateUnits();
    // La matriz de MapLibre no resta la elevación del centro del mapa cuando hay
    // terreno activo: hay que restarla aquí o el modelo queda muy por encima de la cámara.
    const conTerreno = Boolean(this.map?.getTerrain());
    const altura = conTerreno ? origen.z_m * factor - this.map.transform.elevation : 0;

    // T * R_x(90°) * S: el GLB viene Y-up; lo pasamos a X=este, Y=norte, Z=altura.
    // La exageración del terreno se aplica al eje vertical para que los edificios
    // sigan apoyados en el suelo cuando el usuario mueve el control.
    const matriz = new THREE.Matrix4()
      .makeTranslation(mc.x, mc.y, altura * escala)
      // Mercator tiene el eje Y hacia el sur; el modelo, tras la rotación,
      // tiene el eje Y hacia el norte. Invertimos solo ese eje.
      .multiply(new THREE.Matrix4().makeScale(1, -1, 1))
      .multiply(new THREE.Matrix4().makeRotationX(Math.PI / 2))
      .multiply(new THREE.Matrix4().makeScale(escala, escala * factor, escala));

    grupo.matrix.copy(matriz);
    grupo.matrixWorldNeedsUpdate = true;
  }

  aplicarExageracion(factor) {
    this.exageracion = factor;
    for (const { info, grupo } of this.bloques) {
      this.actualizarMatriz(grupo, info);
    }
    this.map?.triggerRepaint();
  }

  setVisible(visible) {
    this.visible = Boolean(visible);
    this.map?.triggerRepaint();
  }

  render(gl, matrix) {
    if (!this.visible || !this.renderer) return;
    for (const { info, grupo } of this.bloques) this.actualizarMatriz(grupo, info);
    this.camera.projectionMatrix = new THREE.Matrix4().fromArray(matrix);
    this.renderer.resetState();
    this.renderer.render(this.scene, this.camera);
  }

  onRemove() {
    for (const { grupo } of this.bloques) {
      this.scene.remove(grupo);
      grupo.traverse((objeto) => {
        if (objeto.isMesh) {
          objeto.geometry?.dispose?.();
          const materiales = Array.isArray(objeto.material) ? objeto.material : [objeto.material];
          for (const material of materiales) material?.dispose?.();
        }
      });
    }
    this.bloques = [];
    this.renderer?.dispose?.();
    this.renderer = null;
  }
}

/* ------------------------------------------------------------------ */
/* Mapa                                                               */
/* ------------------------------------------------------------------ */

if (!window.maplibregl) {
  ocultarCarga();
  mostrarAviso("No se pudo cargar MapLibre. Revisa la conexión a internet.", 12000);
  throw new Error("MapLibre no está disponible");
}

const map = new maplibregl.Map({
  container: "map",
  style: "https://tiles.openfreemap.org/styles/liberty",
  ...VISTA_INICIAL,
  maxPitch: 85,
  antialias: true,
  attributionControl: false,
  maxBounds: [
    [BBOX[0] - 0.08, BBOX[1] - 0.06],
    [BBOX[2] + 0.08, BBOX[3] + 0.06],
  ],
});

map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "bottom-right");
map.addControl(new maplibregl.ScaleControl({ unit: "metric", maxWidth: 120 }), "bottom-left");
map.addControl(
  new maplibregl.AttributionControl({
    compact: true,
    customAttribution:
      'Datos: <a href="https://overturemaps.org/" target="_blank" rel="noopener">Overture Maps</a> · ' +
      '<a href="https://www.openstreetmap.org/" target="_blank" rel="noopener">OpenStreetMap</a> · ' +
      '<a href="https://openfreemap.org/" target="_blank" rel="noopener">OpenFreeMap</a> · ' +
      "DEM: AWS Terrain Tiles",
  }),
  "bottom-right",
);

map.on("error", (evento) => {
  console.warn("MapLibre:", evento?.error || evento);
});

let mapaIniciado = false;

function iniciarMapa() {
  if (mapaIniciado) return;
  mapaIniciado = true;

  // El estilo trae edificios OSM en 3D; nuestro GLB ya cubre el área.
  if (map.getLayer("building-3d")) {
    map.setLayoutProperty("building-3d", "visibility", "none");
  }

  try {
    map.addSource("terrain", {
      type: "raster-dem",
      tiles: ["https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"],
      encoding: "terrarium",
      tileSize: 256,
      maxzoom: 15,
    });
    map.setTerrain({ source: "terrain", exaggeration: estado.exageracion });

    const antesHillshade = primerLayer("building", "road_minor", "water");
    const capaHillshade = {
      id: "hillshade-bogota",
      type: "hillshade",
      source: "terrain",
      paint: {
        "hillshade-exaggeration": 0.32,
        "hillshade-shadow-color": "#4b3f35",
        "hillshade-highlight-color": "#fff7e9",
        "hillshade-accent-color": "#7d6b58",
      },
    };
    if (antesHillshade) map.addLayer(capaHillshade, antesHillshade);
    else map.addLayer(capaHillshade);
  } catch (error) {
    console.error("Error al añadir el terreno", error);
  }

  cargarSitios();
  iniciarModelo();
  conectarControles();
  setTimeout(() => {
    map.resize();
    map.triggerRepaint();
  }, 120);
}

map.on("style.load", iniciarMapa);
map.on("load", iniciarMapa);
if (map.isStyleLoaded()) setTimeout(iniciarMapa, 0);

async function cargarSitios() {
  try {
    const respuesta = await fetch("layers/sitios.geojson", { cache: "no-cache" });
    if (!respuesta.ok) throw new Error(`HTTP ${respuesta.status}`);
    const datos = await respuesta.json();

    map.addSource("sitios", { type: "geojson", data: datos });
    const antes = primerLayer("waterway_line_label", "label_other", "poi_r20");

    const capas = [
      {
        id: "sitios-halo",
        type: "circle",
        source: "sitios",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 11, 6, 15, 14],
          "circle-color": "#e8a87c",
          "circle-opacity": 0.18,
          "circle-blur": 0.6,
        },
      },
      {
        id: "sitios-puntos",
        type: "circle",
        source: "sitios",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 11, 3.5, 15, 6.5],
          "circle-color": "#e8a87c",
          "circle-stroke-color": "#fff7ed",
          "circle-stroke-width": 1.6,
        },
      },
      {
        id: "sitios-etiquetas",
        type: "symbol",
        source: "sitios",
        layout: {
          "text-field": ["get", "nombre"],
          "text-font": ["Noto Sans Regular"],
          "text-size": ["interpolate", ["linear"], ["zoom"], 11, 10, 15, 12.5],
          "text-offset": [0, 1.25],
          "text-anchor": "top",
          "text-optional": true,
          "text-padding": 4,
        },
        paint: {
          "text-color": "#2b2b2b",
          "text-halo-color": "#fffaf1",
          "text-halo-width": 1.6,
        },
      },
    ];

    for (const capa of capas) {
      if (antes) map.addLayer(capa, antes);
      else map.addLayer(capa);
    }

    map.on("click", "sitios-puntos", (evento) => {
      const feature = evento.features?.[0];
      if (!feature) return;
      const p = feature.properties || {};
      const html = `
        <div class="popup-sitio">
          <span class="popup-categoria">${escaparHtml(p.categoria)}</span>
          <strong>${escaparHtml(p.nombre)}</strong>
          <p>${escaparHtml(p.descripcion)}</p>
        </div>`;
      new maplibregl.Popup({ closeButton: true, offset: 14, maxWidth: "280px" })
        .setLngLat(evento.lngLat)
        .setHTML(html)
        .addTo(map);
    });

    map.on("mouseenter", "sitios-puntos", () => {
      map.getCanvas().style.cursor = "pointer";
    });
    map.on("mouseleave", "sitios-puntos", () => {
      map.getCanvas().style.cursor = "";
    });

    estado.sitios = true;
  } catch (error) {
    console.error("No se pudieron cargar los sitios", error);
    mostrarAviso("No se pudieron cargar los sitios de interés.");
  }
}

function iniciarModelo() {
  const capa = new CapaBogota({
    onProgress: (fraccion, nombre) => {
      actualizarCarga(10 + fraccion * 80, "Cargando modelo…");
    },
    onReady: (cargados, errores) => {
      estado.bloquesCargados = cargados;
      actualizarCarga(100, "Modelo listo");
      setTimeout(ocultarCarga, 350);
      if (!cargados) {
        mostrarAviso(
          "No se pudo cargar el modelo GLB. Se activó el respaldo de edificios OSM.",
          12000,
        );
        const osm = $("toggle-osm");
        if (osm) {
          osm.checked = true;
          if (map.getLayer("building-3d")) {
            map.setLayoutProperty("building-3d", "visibility", "visible");
          }
        }
      } else if (errores?.length) {
        mostrarAviso(`Se cargaron ${cargados} bloques; algunos fallaron: ${errores.join(" | ")}`, 10000);
      }
    },
  });

  estado.capa = capa;
  const antes = primerLayer("waterway_line_label", "label_other", "poi_r20");
  try {
    if (antes) map.addLayer(capa, antes);
    else map.addLayer(capa);
  } catch (error) {
    console.error("Error al añadir la capa 3D", error);
    mostrarAviso("No se pudo añadir la capa 3D. Se activó el respaldo OSM.", 12000);
    const osm = $("toggle-osm");
    if (osm) osm.checked = true;
    if (map.getLayer("building-3d")) {
      map.setLayoutProperty("building-3d", "visibility", "visible");
    }
    ocultarCarga();
  }
}

/* ------------------------------------------------------------------ */
/* Controles                                                          */
/* ------------------------------------------------------------------ */

function conectarControles() {
  const toggleModelo = $("toggle-modelo");
  const toggleTerreno = $("toggle-terreno");
  const toggleSitios = $("toggle-sitios");
  const toggleOsm = $("toggle-osm");
  const exageracion = $("exageracion");
  const valorExageracion = $("valor-exageracion");

  toggleModelo?.addEventListener("change", (evento) => {
    estado.capa?.setVisible(evento.target.checked);
  });

  toggleTerreno?.addEventListener("change", (evento) => {
    estado.terreno = evento.target.checked;
    if (estado.terreno) {
      map.setTerrain({ source: "terrain", exaggeration: estado.exageracion });
    } else {
      map.setTerrain(null);
    }
    if (map.getLayer("hillshade-bogota")) {
      map.setLayoutProperty("hillshade-bogota", "visibility", estado.terreno ? "visible" : "none");
    }
  });

  toggleSitios?.addEventListener("change", (evento) => {
    const visibilidad = evento.target.checked ? "visible" : "none";
    for (const id of ["sitios-halo", "sitios-puntos", "sitios-etiquetas"]) {
      if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", visibilidad);
    }
  });

  toggleOsm?.addEventListener("change", (evento) => {
    if (map.getLayer("building-3d")) {
      map.setLayoutProperty("building-3d", "visibility", evento.target.checked ? "visible" : "none");
    }
  });

  exageracion?.addEventListener("input", (evento) => {
    const factor = Number(evento.target.value);
    estado.exageracion = factor;
    if (valorExageracion) valorExageracion.textContent = `${factor.toFixed(1).replace(".", ",")}×`;
    if (estado.terreno) {
      map.setTerrain({ source: "terrain", exaggeration: factor });
    }
    estado.capa?.aplicarExageracion(factor);
  });

  $("btn-sobrevuelo")?.addEventListener("click", volar);
  $("btn-detener")?.addEventListener("click", detenerVuelo);
  $("btn-reset")?.addEventListener("click", (evento) => {
    evento.preventDefault();
    detenerVuelo();
    map.flyTo({
      ...VISTA_INICIAL,
      duration: REDUCIR_MOVIMIENTO ? 0 : 1600,
      essential: true,
    });
  });

  const dialogo = $("video-dialog");
  const video = $("video-sobrevuelo");
  $("btn-video")?.addEventListener("click", () => {
    dialogo?.showModal();
    video?.play().catch(() => {});
  });
  $("cerrar-video")?.addEventListener("click", () => {
    dialogo?.close();
    video?.pause();
  });
  dialogo?.addEventListener("click", (evento) => {
    if (evento.target === dialogo) {
      dialogo.close();
      video?.pause();
    }
  });

  const panel = $("panel");
  const panelToggle = $("panel-toggle");
  panelToggle?.addEventListener("click", () => {
    const oculto = panel?.classList.toggle("oculto");
    panelToggle.setAttribute("aria-expanded", String(!oculto));
  });
}

/* ------------------------------------------------------------------ */
/* Sobrevuelo interactivo                                             */
/* ------------------------------------------------------------------ */

const RUTA_VUELO = [
  { center: [-74.082, 4.597], zoom: 14.6, pitch: 66, bearing: 40, duration: 3500 },
  { center: [-74.076, 4.5985], zoom: 15.6, pitch: 68, bearing: 60, duration: 4000 },
  { center: [-74.0705, 4.6115], zoom: 15.4, pitch: 70, bearing: 20, duration: 4000 },
  { center: [-74.0675, 4.62], zoom: 14.8, pitch: 66, bearing: 140, duration: 4000 },
  { center: [-74.063, 4.606], zoom: 14.4, pitch: 62, bearing: 280, duration: 4500 },
  { ...VISTA_INICIAL, duration: 3500 },
];

async function volar() {
  if (estado.vueloActivo) return;
  estado.vueloActivo = true;
  const btnVolar = $("btn-sobrevuelo");
  const btnDetener = $("btn-detener");
  if (btnVolar) btnVolar.hidden = true;
  if (btnDetener) btnDetener.hidden = false;
  const panel = $("panel");
  if (window.matchMedia("(max-width: 760px)").matches && panel) {
    panel.classList.add("oculto");
  }

  for (const paso of RUTA_VUELO) {
    if (!estado.vueloActivo) break;
    const duracion = REDUCIR_MOVIMIENTO ? 0 : paso.duration;
    await new Promise((resolve) => {
      let resuelto = false;
      const terminar = () => {
        if (resuelto) return;
        resuelto = true;
        map.off("moveend", terminar);
        resolve();
      };
      map.once("moveend", terminar);
      map.flyTo({ ...paso, duration: duracion, essential: true, curve: 1.35 });
      setTimeout(terminar, duracion + 900);
    });
    if (REDUCIR_MOVIMIENTO) await new Promise((r) => setTimeout(r, 900));
  }

  estado.vueloActivo = false;
  if (btnVolar) btnVolar.hidden = false;
  if (btnDetener) btnDetener.hidden = true;
}

function detenerVuelo() {
  if (!estado.vueloActivo) return;
  estado.vueloActivo = false;
  map.stop();
  const btnVolar = $("btn-sobrevuelo");
  const btnDetener = $("btn-detener");
  if (btnVolar) btnVolar.hidden = false;
  if (btnDetener) btnDetener.hidden = true;
}

// Si el estilo o los GLB tardan demasiado, no dejamos la pantalla bloqueada.
setTimeout(() => {
  const capa = $("cargando");
  if (capa && !capa.classList.contains("oculto")) {
    ocultarCarga();
    mostrarAviso(
      "La carga está tardando más de lo esperado. El mapa puede seguir funcionando; revisa la consola si el modelo no aparece.",
      12000,
    );
  }
}, 30000);

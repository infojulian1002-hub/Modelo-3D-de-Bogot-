# Bitácora: uso de OpenCode en el modelo 3D de Bogotá

**Estudiante:** Daniel Felipe Aguirre Pineda
**Herramienta:** OpenCode Desktop y su CLI, versión 2.0.10, en Windows
**Proveedor y modelo:** OpenCode (Zen), DeepSeek V4.1 Flash Free (`opencode/deepseek-v4.1-flash-free`)
**Producto:** [mapa interactivo](https://infojulian1002-hub.github.io/Modelo-3D-de-Bogot-/) · [repositorio](https://github.com/infojulian1002-hub/Modelo-3D-de-Bogot-)

Las cifras de tokens salen de la base de datos local de OpenCode (`~/.local/share/opencode/opencode.db`, tabla `session_v2`). No son estimaciones.

## 1. Cómo se usó OpenCode

### Proveedor y modelo
En el selector de modelos de OpenCode, el proveedor **OpenCode** ofrece modelos marcados como **Gratis**. Se eligió DeepSeek V4.1 Flash Free porque no tiene costo por token y funciona para tareas de código acotadas. También aparecen Beam, Flint 40B, GLM-5.3-Flash, MiMo-V2.6-Flash y Nemotron 3.5 Super VL. El modelo por defecto del proyecto queda en `opencode.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "model": "opencode/deepseek-v4.1-flash-free",
  "small_model": "opencode/nemotron-3.5-lightning-free"
}
```

### Archivos de configuración del proyecto
| Archivo | Para qué sirve |
|---|---|
| `opencode.json` | Define el modelo por defecto. |
| `AGENTS.md` | Reglas que OpenCode lee en cada sesión: respuestas cortas, una tarea por sesión y no abrir carpetas pesadas. |
| `.ignore` | Excluye `data/`, `renders/`, `models/` y `vendor/` de las búsquedas del agente. |
| `.opencode/agents/optimizador-costos.md` | Agente de optimización de costos. |

### Agente de optimización de costos
Es un agente propio, de solo lectura: tiene negados `edit`, `bash` y `webfetch`, y un máximo de 4 pasos. No ejecuta la tarea, sino que devuelve un plan de 5 puntos: modelo, archivos mínimos, pasos, prompt corto y riesgos de consumo.

El flujo es este:
1. Se le pide al agente que planee la tarea.
2. Se copia su prompt corto, se ajusta si hace falta y se envía al agente `build`, en una sesión nueva.

Desde la terminal:

```powershell
opencode run --agent optimizador-costos "Planea la tarea: ... No la ejecutes."
opencode run --agent build --auto "Crea solo este archivo: ..."
```

En OpenCode Desktop, el agente se elige en el selector que está debajo del cuadro de texto, y el consumo se revisa en la pestaña **Contexto**.

## 2. Resultado: consumo real

| Sesión | Fecha | Agente | Entrada | Salida | Razonamiento | Caché leída | Costo |
|---|---|---|---:|---:|---:|---:|---:|
| Modelo 3D de Bogotá con Blender y QGIS (una sola sesión larga) | 2–3 nov | build | 434.479 | 84.006 | 105.942 | 25.331.072 | 0 US$ |
| Workflow GitHub Pages (plan, primer intento) | 3 nov 19:58 | optimizador-costos | 7.428 | 645 | 2.262 | 12.800 | 0 US$ |
| Plan de costos del workflow (segundo intento) | 3 nov 20:01 | optimizador-costos | 6.865 | 521 | 119 | 6.272 | 0 US$ |
| Workflow de GitHub Pages | 3 nov 20:05 | build | 7.059 | 549 | 794 | 8.576 | 0 US$ |
| README | 3 nov 20:18 | build | 7.754 | 512 | 131 | 7.552 | 0 US$ |

**Conclusión:** la sesión larga agotó el cupo gratuito con el mensaje `Free usage limit reached`. Después, con el agente de costos y sesiones de una sola tarea, las cuatro sesiones sumaron 29.106 tokens de entrada, frente a los 434.479 de la sesión larga, y 35.200 de caché leída, frente a más de 25 millones. El costo en dinero fue 0 US$ en todos los casos, porque el modelo es gratuito. El ahorro real es no agotar el cupo.

## 3. Registro cronológico

En cada entrada se indica quién hizo el trabajo: **OpenCode** o **Claude**, un asistente externo que intervino cuando OpenCode se detuvo.

### 2 nov, 23:16 a 3 nov, 05:54: sesión larga
- **Autor:** OpenCode, modelo DeepSeek V4.1 Flash Free, agente Build.
- **Prompt:** el enunciado completo del trabajo y, después, «Mira el repositorio», «Continua» y «Estas tardando mucho, revisa lo que has hecho, si funciona dejalo, y continua».
- **Qué se hizo:**
  - Descarga de datos de Overture y DEM de AWS.
  - Procesamiento en EPSG:3116 (340.056 edificios).
  - Proyecto de QGIS.
  - Escena y bloques GLB en Blender.
  - 96 cuadros de sobrevuelo.
  - Mapa con MapLibre y three.js.
- **Herramientas usadas:** 106 comandos de consola, 87 ediciones, 27 lecturas y 13 escrituras.
- **Problemas:**
  - Dos compactaciones automáticas del contexto.
  - El modelo GLB no aparecía en el navegador. Se intentó diagnosticar durante varios pasos, sin resolverlo.
  - A las 05:54 se agotó el cupo gratuito, con el trabajo sin publicar y sin bitácora.

### 3 nov, 19:50: diagnóstico sin gastar tokens
- **Autor:** Claude.
- **Qué se hizo:** se revisó el estado de la carpeta y las estadísticas de la sesión. Se decidió reducir el área a una zona pequeña y crear el agente de costos.
- **Problema:** agregar la carpeta como proyecto desde la ventana de OpenCode Desktop falló al manejarla de forma remota, y quedó añadida por error la carpeta «Entregable GitHub». Se usó el CLI incluido con la aplicación (`resources/opencode-cli.exe`), que además registró `Bogota-3D` como proyecto.

### 3 nov, 19:58: configuración y plan del workflow
- **Autor:** archivos de configuración por Claude; plan por OpenCode, agente `optimizador-costos`.
- **Prompt:** «Planea la tarea: agregar un workflow de GitHub Actions que publique el mapa en GitHub Pages (...). No la ejecutes.»
- **Resultado:** recomendó un modelo gratuito por ser una tarea mecánica, leer solo lo mínimo, usar `upload-pages-artifact` y `deploy-pages`, y detenerse tras 2 intentos fallidos.
- **Problemas:**
  - El primer intento corrió dos veces porque el puente remoto agotó su tiempo de espera; ese consumo extra está en la tabla.
  - El agente tenía configurado MiMo, pero la sesión registró DeepSeek, así que el campo `model` no se aplicó en ese uso. Se dejó DeepSeek en ambos lados.

### 3 nov, 20:05: workflow de GitHub Pages
- **Autor:** OpenCode, agente Build.
- **Prompt:** el prompt corto propuesto por el agente de costos, ajustado a las rutas finales.
- **Resultado:** `.github/workflows/pages.yml`, escrito al primer intento y sin ejecutar comandos.

### 3 nov, 20:00 a 20:20: zona pequeña y corrección del mapa
- **Autor:** Claude.
- **Zona:** lon −74,085 a −74,055 y lat 4,593 a 4,625 (3,33 × 3,54 km): 19.429 edificios, 330 con altura real y 19.099 estimadas. Script: `scripts/zona_pequena.py`.
- **Causa de que el modelo no se viera:** con terreno activo, la matriz que MapLibre entrega a las capas personalizadas no resta la elevación del centro del mapa, así que el modelo quedaba unos 2.600 m por encima de lo esperado. Se corrigió en `main.js`.
- **Otras correcciones:**
  - Las vías, el agua y las zonas verdes de los bloques antiguos estaban en cota absoluta; en la zona nueva son relativas al origen.
  - El decodificador Draco ahora se sirve desde `vendor/draco/`.
  - Se quitaron los elementos de diagnóstico.
- **Verificación:** prueba en un navegador sin interfaz, con red simulada y terreno plano. El mapa publicado se revisó aparte; ver la sección 5.

### 3 nov, 20:18: README
- **Autor:** OpenCode, agente Build.
- **Prompt:** reescribir solo `README.md`, con los datos ya dados en el mensaje para no leer otros archivos.

### 3 nov, 20:10 en adelante: QGIS y Blender en la zona pequeña
- **Autor:** Claude, ejecutando QGIS 3.42 y Blender 5.2 en el PC.
- **QGIS:** `qgis/zona_centro.qgz` y `docs/renders/zona_mapa_qgis.png`.
- **Blender:** `models/zona/bogota_centro.glb` (0,65 MB), `docs/renders/zona_aerea.png` y el sobrevuelo. Cada cuadro tardó entre 10 y 22 s, así que se renderizó uno de cada dos: 120 cuadros a 12 fps, unos 10 s de video.

## 4. Lecciones para gastar menos
1. Una tarea por sesión: la sesión larga releyó su contexto en cada paso, y por eso acumuló más de 25 millones de tokens de caché.
2. Planear con un agente de solo lectura antes de ejecutar.
3. Dar los datos en el prompt, para que el agente no tenga que leer archivos.
4. Excluir datos y binarios con `.ignore`.
5. Empezar con una zona pequeña y ampliarla solo si funciona.
6. Poner un límite a los reintentos: el diagnóstico del GLB fue la parte más costosa de la sesión y no llegó a resolverse.

## 5. Limitaciones
- Solo 330 de los 19.429 edificios tienen altura real. Las demás son estimaciones según el área de la huella, no datos medidos.
- La zona es pequeña y no cubre toda Bogotá.
- La fusión de edificios, el DEM de 20 m y la simplificación de geometrías no se validaron contra levantamientos de campo.
- Parte del trabajo no se hizo con OpenCode; está marcado en cada entrada.

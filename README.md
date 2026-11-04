# Bogotá 3D

Mapa web 3D del centro de Bogotá (La Candelaria a Monserrate, 3,3 × 3,5 km),
construido con **MapLibre GL JS** y **three.js** sobre un modelo GLB generado en Blender.
Contiene **19.429 edificios** y **3.992 vías**.

## Enlaces

- Sitio: https://infojulian1002-hub.github.io/Modelo-3D-de-Bogot-/
- Repositorio: https://github.com/infojulian1002-hub/Modelo-3D-de-Bogot-

## Datos

- **Overture Maps**: edificios, vías, agua y zonas verdes.
- **AWS Terrain Tiles**: elevación del terreno.
- Base cartográfica: **OpenFreeMap / OpenStreetMap**.

> **Advertencia sobre las alturas**
> Solo **330 edificios** tienen altura real. Los otros **19.099** usan una altura
> estimada a partir del área de la huella: no son datos medidos.

## Flujo de trabajo

1. **QGIS**: revisión de capas (`qgis/zona_centro.qgz`).
2. **`scripts/zona_pequena.py`**: preparación de los datos de la zona.
3. **Blender** (`scripts/generar_blender.py`) con los modos `zona`, `vuelo_zona` y `video`.
4. Exportación a **GLB** y publicación en el **mapa web**.

## Publicación

El despliegue es automático mediante **GitHub Actions**: `.github/workflows/pages.yml`.

## Bitácora

El historial de cambios y pendientes está en `BITACORA.md`.

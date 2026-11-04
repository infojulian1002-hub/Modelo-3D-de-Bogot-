"""Descarga teselas Terrarium de AWS y construye un DEM GeoTIFF para Bogotá.

Uso:
    python scripts/descargar_dem.py
    python scripts/descargar_dem.py --bbox -74.12 4.58 -74.04 4.70 --zoom 15
"""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import numpy as np
import rasterio
import requests
from PIL import Image
from rasterio.transform import from_origin

RAIZ = Path(__file__).resolve().parents[1]
CACHE = RAIZ / "data" / "tiles"
URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"


def lon_a_tile(lon: float, z: int) -> float:
    return (lon + 180.0) / 360.0 * (2**z)


def lat_a_tile(lat: float, z: int) -> float:
    rad = math.radians(lat)
    return (1.0 - math.asinh(math.tan(rad)) / math.pi) / 2.0 * (2**z)


def tile_a_lon(x: float, z: int) -> float:
    return x / (2**z) * 360.0 - 180.0


def tile_a_lat(y: float, z: int) -> float:
    n = math.pi - 2.0 * math.pi * y / (2**z)
    return math.degrees(math.atan(math.sinh(n)))


def descargar_tesela(x: int, y: int, z: int, reintentos: int = 4) -> np.ndarray:
    destino = CACHE / str(z) / str(x) / f"{y}.png"
    destino.parent.mkdir(parents=True, exist_ok=True)

    if not destino.exists():
        for intento in range(1, reintentos + 1):
            try:
                respuesta = requests.get(URL.format(z=z, x=x, y=y), timeout=60)
                respuesta.raise_for_status()
                destino.write_bytes(respuesta.content)
                break
            except Exception as error:  # noqa: BLE001
                if intento == reintentos:
                    raise RuntimeError(f"No se pudo descargar {z}/{x}/{y}") from error
                time.sleep(1.5 * intento)

    imagen = Image.open(destino).convert("RGB")
    rgb = np.asarray(imagen, dtype=np.float32)
    # Terrarium: elevación = (R * 256 + G + B / 256) - 32768
    return (rgb[:, :, 0] * 256.0 + rgb[:, :, 1] + rgb[:, :, 2] / 256.0) - 32768.0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bbox", nargs=4, type=float,
                        default=[-74.12, 4.58, -74.04, 4.70],
                        metavar=("LON_MIN", "LAT_MIN", "LON_MAX", "LAT_MAX"))
    parser.add_argument("--zoom", type=int, default=15)
    args = parser.parse_args()

    lon_min, lat_min, lon_max, lat_max = args.bbox
    z = args.zoom

    x_min = math.floor(lon_a_tile(lon_min, z))
    x_max = math.floor(lon_a_tile(lon_max, z))
    y_min = math.floor(lat_a_tile(lat_max, z))
    y_max = math.floor(lat_a_tile(lat_min, z))

    ancho = (x_max - x_min + 1) * 256
    alto = (y_max - y_min + 1) * 256
    print(f"Teselas {z}: x {x_min}-{x_max}, y {y_min}-{y_max} -> {ancho}x{alto} px")

    dem = np.empty((alto, ancho), dtype=np.float32)
    total = (x_max - x_min + 1) * (y_max - y_min + 1)
    hechas = 0
    for x in range(x_min, x_max + 1):
        for y in range(y_min, y_max + 1):
            fila = (y - y_min) * 256
            columna = (x - x_min) * 256
            dem[fila:fila + 256, columna:columna + 256] = descargar_tesela(x, y, z)
            hechas += 1
            if hechas % 20 == 0 or hechas == total:
                print(f"  {hechas}/{total} teselas")

    oeste = tile_a_lon(x_min, z)
    este = tile_a_lon(x_max + 1, z)
    norte = tile_a_lat(y_min, z)
    sur = tile_a_lat(y_max + 1, z)
    transform = from_origin(oeste, norte, (este - oeste) / ancho, (norte - sur) / alto)

    salida_tif = RAIZ / "data" / "dem.tif"
    with rasterio.open(
        salida_tif,
        "w",
        driver="GTiff",
        height=alto,
        width=ancho,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=transform,
        nodata=-9999.0,
        compress="deflate",
    ) as dst:
        dst.write(dem, 1)

    np.save(RAIZ / "data" / "dem.npy", dem)
    meta = {
        "bbox": [lon_min, lat_min, lon_max, lat_max],
        "zoom": z,
        "tiles": {"x_min": x_min, "x_max": x_max, "y_min": y_min, "y_max": y_max},
        "shape": [alto, ancho],
        "bounds": [oeste, sur, este, norte],
        "elevacion_min_m": float(dem.min()),
        "elevacion_max_m": float(dem.max()),
        "fuente": "AWS Terrain Tiles (Terrarium)",
    }
    (RAIZ / "data" / "dem_meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"DEM guardado: {salida_tif} ({salida_tif.stat().st_size / 1e6:.1f} MB)")
    print(f"Elevación: {dem.min():.1f} m a {dem.max():.1f} m")


if __name__ == "__main__":
    main()

"""Añade centro_3116 a los NPZ para que Blender no dependa de pyproj."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault(
    "PROJ_DATA",
    r"C:\Users\julia\AppData\Local\Programs\Python\Python311\Lib\site-packages\rasterio\proj_data",
)
os.environ.setdefault("PROJ_LIB", os.environ["PROJ_DATA"])

import numpy as np
from pyproj import Transformer

RAIZ = Path(__file__).resolve().parents[1]
archivos = [RAIZ / "data" / "escena_completa.npz", *sorted((RAIZ / "data" / "bloques").glob("*.npz"))]
transformador = Transformer.from_crs(4326, 3116, always_xy=True)
for archivo in archivos:
    datos = dict(np.load(archivo, allow_pickle=False))
    if "centro_3116" in datos:
        continue
    lon, lat = datos["origen"][:2]
    cx, cy = transformador.transform(float(lon), float(lat))
    datos["centro_3116"] = np.array([cx, cy], dtype=np.float64)
    np.savez_compressed(archivo, **datos)
    print(f"{archivo.name}: centro {cx:.1f}, {cy:.1f}")

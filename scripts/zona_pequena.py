"""Recorta los datos ya procesados a una zona pequeña del centro de Bogotá.

Zona: La Candelaria, Santa Fe y Las Nieves hasta Monserrate.
Salidas: data/zona/zona.npz y data/zona/reporte_zona.json
Uso: python scripts/zona_pequena.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from procesar_datos import (  # noqa: E402
    CRS_METRICO, DATA, empaquetar_poligonos, empaquetar_poligonos_z, gpd, lineas_de, np,
    muestrear_terreno, Transformer, box,
)

BBOX_4326 = (-74.085, 4.593, -74.055, 4.625)
MARGEN_TERRENO_M = 1500.0
SALIDA = DATA / "zona"
SALIDA.mkdir(exist_ok=True)


def main() -> None:
    zona = gpd.GeoSeries([box(*BBOX_4326)], crs="EPSG:4326").to_crs(CRS_METRICO).iloc[0]
    xmin, ymin, xmax, ymax = zona.bounds
    caja = (xmin, ymin, xmax, ymax)

    ed = gpd.read_file(DATA / "edificios_3116.gpkg", bbox=caja)
    ed = ed[ed.geometry.centroid.within(zona)].copy()
    vias = gpd.read_file(DATA / "vias_3116.gpkg", bbox=caja).clip(zona)
    agua = gpd.read_file(DATA / "agua_3116.gpkg", bbox=caja).clip(zona)
    verde = gpd.read_file(DATA / "zonas_verdes_3116.gpkg", bbox=caja).clip(zona)
    agua = agua[agua.geometry.geom_type.isin(["Polygon", "MultiPolygon"])]
    verde = verde[verde.geometry.geom_type.isin(["Polygon", "MultiPolygon"])]

    t = np.load(DATA / "terreno_3116.npz")
    tz, tx, ty = t["z"], t["x"], t["y"]
    cols = (tx >= xmin - MARGEN_TERRENO_M) & (tx <= xmax + MARGEN_TERRENO_M)
    filas = (ty >= ymin - MARGEN_TERRENO_M) & (ty <= ymax + MARGEN_TERRENO_M)

    cx, cy = (xmin + xmax) / 2.0, (ymin + ymax) / 2.0
    lon, lat = Transformer.from_crs(CRS_METRICO, 4326, always_xy=True).transform(cx, cy)
    origen_z = float(np.median(ed["base_m"].to_numpy()))
    desplazamiento = np.array([cx, cy], dtype=np.float32)

    ev, eo, _ = empaquetar_poligonos(ed.geometry.to_list())
    ev -= desplazamiento

    vv, vo, vz, va = [], [0], [], []
    for geom, ancho in zip(vias.geometry, vias["ancho_m"]):
        for linea in lineas_de(geom):
            coords = np.asarray(linea.coords, dtype=np.float32)
            if len(coords) < 2:
                continue
            zs = muestrear_terreno(coords[:, 0], coords[:, 1], tz, tx, ty) + 0.4 - origen_z
            vv.extend((coords[:, :2] - desplazamiento).tolist())
            vz.extend(zs.tolist())
            vo.append(len(vv))
            va.append(float(ancho))

    def cotas(capa, extra):
        return [
            float(muestrear_terreno(np.array([g.centroid.x]), np.array([g.centroid.y]), tz, tx, ty)[0])
            + extra - origen_z
            for g in capa.geometry
        ]

    av, ao, az = empaquetar_poligonos_z(agua.geometry.to_list(), cotas(agua, 0.6))
    if len(av):
        av -= desplazamiento
    gv, go, gz = empaquetar_poligonos_z(verde.geometry.to_list(), cotas(verde, 0.3))
    if len(gv):
        gv -= desplazamiento

    np.savez_compressed(
        SALIDA / "zona.npz",
        edificios_vertices=ev, edificios_offsets=eo,
        edificios_bases=(ed["base_m"].to_numpy() - origen_z).astype(np.float32),
        edificios_alturas=ed["altura_m"].to_numpy().astype(np.float32),
        vias_vertices=np.asarray(vv, dtype=np.float32), vias_offsets=np.asarray(vo, dtype=np.int32),
        vias_z=np.asarray(vz, dtype=np.float32), vias_anchos=np.asarray(va, dtype=np.float32),
        agua_vertices=av, agua_offsets=ao, agua_z=az,
        verde_vertices=gv, verde_offsets=go, verde_z=gz,
        origen=np.array([lon, lat, origen_z], dtype=np.float64),
        centro_3116=np.array([cx, cy], dtype=np.float64),
        terreno_z=tz[np.ix_(filas, cols)], terreno_x=tx[cols], terreno_y=ty[filas],
    )
    reporte = {
        "bbox_4326": list(BBOX_4326),
        "origen": {"lat": float(lat), "lon": float(lon), "z_m": origen_z},
        "ancho_km": round((xmax - xmin) / 1000, 2),
        "alto_km": round((ymax - ymin) / 1000, 2),
        "edificios": int(len(ed)),
        "edificios_reales": int((ed.fuente_altura == "real").sum()),
        "edificios_estimadas": int((ed.fuente_altura == "estimada").sum()),
        "altura_max_m": float(ed.altura_m.max()),
        "vias": int(len(vias)),
        "agua": int(len(agua)),
        "zonas_verdes": int(len(verde)),
        "terreno_min_m": float(tz[np.ix_(filas, cols)].min()),
        "terreno_max_m": float(tz[np.ix_(filas, cols)].max()),
    }
    (SALIDA / "reporte_zona.json").write_text(json.dumps(reporte, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(reporte, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()

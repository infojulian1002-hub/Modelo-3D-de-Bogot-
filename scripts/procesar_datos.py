"""Procesa los datos de Overture y el DEM para el modelo 3D de Bogotá.

Salidas principales:
- data/edificios_3116.gpkg
- data/vias_3116.gpkg
- data/agua_3116.gpkg
- data/zonas_verdes_3116.gpkg
- data/terreno_3116.tif / .npz
- data/bloques/bloque_sw.npz, bloque_se.npz, bloque_nw.npz, bloque_ne.npz
- data/escena_completa.npz
- data/reporte_procesamiento.json
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path

# rasterio y pyproj deben usar su propio PROJ, no el de PostgreSQL.
_RASTERIO_PROJ = Path(
    r"C:\Users\julia\AppData\Local\Programs\Python\Python311\Lib\site-packages\rasterio\proj_data"
)
if _RASTERIO_PROJ.exists():
    os.environ["PROJ_DATA"] = str(_RASTERIO_PROJ)
    os.environ["PROJ_LIB"] = str(_RASTERIO_PROJ)

import geopandas as gpd  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import rasterio  # noqa: E402
from pyproj import Transformer  # noqa: E402
from rasterio.transform import from_origin  # noqa: E402
from rasterio.warp import Resampling, calculate_default_transform, reproject  # noqa: E402
from shapely import make_valid  # noqa: E402
from shapely.affinity import translate  # noqa: E402
from shapely.geometry import box  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
DATA = RAIZ / "data"
BLOQUES = DATA / "bloques"
BLOQUES.mkdir(parents=True, exist_ok=True)

BBOX_4326 = (-74.12, 4.58, -74.04, 4.70)
CRS_METRICO = "EPSG:3116"
RES_DEM = 20.0
SIMPLIFICAR_EDIFICIOS = 0.5

CLASES_VIAS = {
    "motorway": 20.0,
    "trunk": 16.0,
    "primary": 13.0,
    "secondary": 10.0,
    "tertiary": 8.0,
    "residential": 5.0,
    "service": 3.5,
    "cycleway": 2.5,
    "footway": 2.0,
}
CLASES_VERDE = {"park", "grass", "pitch", "playground", "garden", "forest", "cemetery"}
CLASES_AGUA_POL = {"water", "pond", "river", "lake", "canal", "swimming_pool", "wastewater"}


def log(texto: str) -> None:
    print(texto, flush=True)


def cargar_dem_4326():
    with rasterio.open(DATA / "dem.tif") as src:
        return src.read(1), src.transform, src.bounds


def muestrear_dem_4326(lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
    dem, transform, _ = cargar_dem_4326()
    alto, ancho = dem.shape
    col = ((lon - transform.c) / transform.a).astype(np.int64)
    fila = ((lat - transform.f) / transform.e).astype(np.int64)
    col = np.clip(col, 0, ancho - 1)
    fila = np.clip(fila, 0, alto - 1)
    return dem[fila, col].astype(np.float32)


def preparar_terreno_3116() -> tuple[np.ndarray, np.ndarray, np.ndarray, tuple[float, float, float, float]]:
    log("Reproyectando DEM a EPSG:3116...")
    with rasterio.open(DATA / "dem.tif") as src:
        transform, ancho, alto = calculate_default_transform(
            src.crs, CRS_METRICO, src.width, src.height, *src.bounds, resolution=RES_DEM
        )
        destino = np.empty((alto, ancho), dtype=np.float32)
        reproject(
            source=rasterio.band(src, 1),
            destination=destino,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=transform,
            dst_crs=CRS_METRICO,
            resampling=Resampling.bilinear,
        )
        perfil = src.profile.copy()
    perfil.update(
        crs=CRS_METRICO,
        transform=transform,
        width=ancho,
        height=alto,
        dtype="float32",
        compress="deflate",
    )
    with rasterio.open(DATA / "terreno_3116.tif", "w", **perfil) as dst:
        dst.write(destino, 1)

    x = transform.c + (np.arange(ancho) + 0.5) * transform.a
    y = transform.f + (np.arange(alto) + 0.5) * transform.e
    np.savez_compressed(
        DATA / "terreno_3116.npz",
        z=destino,
        x=x.astype(np.float64),
        y=y.astype(np.float64),
        bounds=np.array([transform.c, transform.f + transform.e * alto,
                         transform.c + transform.a * ancho, transform.f]),
        res=np.array([transform.a, transform.e]),
    )
    log(f"  terreno {ancho}x{alto} px, {destino.min():.1f}-{destino.max():.1f} m")
    return destino, x, y, (transform.c, transform.f + transform.e * alto,
                           transform.c + transform.a * ancho, transform.f)


def muestrear_terreno(xs: np.ndarray, ys: np.ndarray, terreno: np.ndarray,
                      x: np.ndarray, y: np.ndarray) -> np.ndarray:
    alto, ancho = terreno.shape
    col = np.searchsorted(x, xs).clip(0, ancho - 1)
    fila = np.searchsorted(-y, -ys).clip(0, alto - 1)
    return terreno[fila, col].astype(np.float32)


def factor_id(valor: str) -> float:
    digest = hashlib.sha256(str(valor).encode("utf-8")).hexdigest()[:8]
    return 0.85 + 0.30 * (int(digest, 16) / 0xFFFFFFFF)


def estimar_altura(area: float, identificador: str) -> float:
    area_acotada = min(max(area, 1.0), 9000.0)
    base = 6.0 + 24.0 * math.log(area_acotada) / math.log(9000.0)
    return round(min(max(base * factor_id(identificador), 6.0), 30.0), 1)


def poligonos_de(geom):
    if geom is None or geom.is_empty:
        return []
    if geom.geom_type == "Polygon":
        return [geom]
    if geom.geom_type == "MultiPolygon":
        return list(geom.geoms)
    return []


def lineas_de(geom):
    if geom is None or geom.is_empty:
        return []
    if geom.geom_type == "LineString":
        return [geom]
    if geom.geom_type == "MultiLineString":
        return list(geom.geoms)
    return []


def empaquetar_poligonos(geoms, z_por_geom: np.ndarray | None = None):
    vertices: list[list[float]] = []
    offsets = [0]
    zs: list[float] = []
    for i, geom in enumerate(geoms):
        for poli in poligonos_de(geom):
            coords = np.asarray(poli.exterior.coords, dtype=np.float32)
            if len(coords) < 3:
                continue
            vertices.extend(coords[:, :2].tolist())
            offsets.append(len(vertices))
            if z_por_geom is not None:
                zs.append(float(z_por_geom[i]))
    return (
        np.asarray(vertices, dtype=np.float32),
        np.asarray(offsets, dtype=np.int32),
        np.asarray(zs, dtype=np.float32),
    )


def empaquetar_poligonos_z(geoms, z_por_geom: list[float]):
    """Empaqueta polígonos y asigna una cota a cada polígono resultante."""
    vertices: list[list[float]] = []
    offsets = [0]
    zs: list[float] = []
    for geom, z in zip(geoms, z_por_geom):
        for poli in poligonos_de(geom):
            coords = np.asarray(poli.exterior.coords, dtype=np.float32)
            if len(coords) < 3:
                continue
            vertices.extend(coords[:, :2].tolist())
            offsets.append(len(vertices))
            zs.append(float(z))
    return (
        np.asarray(vertices, dtype=np.float32),
        np.asarray(offsets, dtype=np.int32),
        np.asarray(zs, dtype=np.float32),
    )


def empaquetar_lineas(geoms, z_por_vertice: list[np.ndarray], anchos: np.ndarray):
    vertices: list[list[float]] = []
    offsets = [0]
    zs: list[float] = []
    for geom, zvals in zip(geoms, z_por_vertice):
        for linea in lineas_de(geom):
            coords = np.asarray(linea.coords, dtype=np.float32)
            if len(coords) < 2:
                continue
            vertices.extend(coords[:, :2].tolist())
            zs.extend(np.asarray(zvals, dtype=np.float32).tolist())
            offsets.append(len(vertices))
    return (
        np.asarray(vertices, dtype=np.float32),
        np.asarray(offsets, dtype=np.int32),
        np.asarray(zs, dtype=np.float32),
        np.asarray(anchos, dtype=np.float32),
    )


def main() -> None:
    reporte: dict = {}

    # ------------------------------------------------------------------ DEM
    terreno, tx, ty, tbounds = preparar_terreno_3116()

    # ------------------------------------------------------------ EDIFICIOS
    log("Cargando edificios de Overture...")
    ed = gpd.read_parquet(
        DATA / "overture" / "edificios.parquet",
        columns=["id", "height", "num_floors", "class", "subtype", "geometry"],
    )
    log(f"  {len(ed):,} edificios")

    log("Muestreando elevación y reproyectando...")
    centroides_4326 = ed.geometry.centroid
    base_m = muestrear_dem_4326(
        centroides_4326.x.to_numpy(), centroides_4326.y.to_numpy()
    ) - 1.0
    bbox_3116 = gpd.GeoSeries([box(*BBOX_4326)], crs="EPSG:4326").to_crs(CRS_METRICO).iloc[0]
    ed = ed.set_crs("EPSG:4326", allow_override=True).to_crs(CRS_METRICO)
    ed = ed.clip(bbox_3116)
    ed["base_m"] = base_m[ed.index.to_numpy()]

    # Reparar geometrías inválidas y quedarse con polígonos.
    invalidas = ~ed.geometry.is_valid
    if invalidas.any():
        log(f"  reparando {int(invalidas.sum()):,} geometrías inválidas")
        ed.loc[invalidas, "geometry"] = ed.loc[invalidas, "geometry"].apply(make_valid)
    ed = ed[ed.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
    ed = ed.explode(index_parts=False).reset_index(drop=True)
    ed["area_m2"] = ed.geometry.area
    ed = ed[(ed["area_m2"] >= 8.0) & (ed["area_m2"] <= 50000.0)].copy()

    log("Calculando alturas...")
    alturas = []
    fuentes = []
    for altura, pisos, area, ident in zip(
        ed["height"].to_numpy(), ed["num_floors"].to_numpy(),
        ed["area_m2"].to_numpy(), ed["id"].astype(str).to_numpy()
    ):
        if np.isfinite(altura) and altura >= 2.0:
            alturas.append(float(altura))
            fuentes.append("real")
        elif np.isfinite(pisos) and pisos >= 1:
            alturas.append(float(pisos) * 3.0)
            fuentes.append("real")
        else:
            alturas.append(estimar_altura(float(area), ident))
            fuentes.append("estimada")
    ed["altura_m"] = np.asarray(alturas, dtype=np.float32)
    ed["fuente_altura"] = fuentes
    ed["geometry"] = ed.geometry.simplify(SIMPLIFICAR_EDIFICIOS, preserve_topology=True)
    ed = ed[~ed.geometry.is_empty].copy()

    columnas = ["id", "altura_m", "base_m", "area_m2", "fuente_altura", "class", "subtype", "geometry"]
    ed = ed[columnas]
    log(f"  {len(ed):,} edificios útiles; "
        f"{(ed.fuente_altura == 'real').sum():,} reales y "
        f"{(ed.fuente_altura == 'estimada').sum():,} estimadas")
    ed.to_file(DATA / "edificios_3116.gpkg", driver="GPKG", layer="edificios")

    # ------------------------------------------------------------------ VIAS
    log("Procesando vías...")
    vias = gpd.read_parquet(DATA / "overture" / "vias.parquet",
                            columns=["id", "class", "subtype", "geometry"])
    vias = vias[vias["subtype"] == "road"]
    vias = vias[vias["class"].isin(CLASES_VIAS)]
    vias = vias.set_crs("EPSG:4326", allow_override=True).to_crs(CRS_METRICO)
    vias = vias.clip(gpd.GeoSeries([box(*BBOX_4326)], crs="EPSG:4326").to_crs(CRS_METRICO).iloc[0])
    vias["ancho_m"] = vias["class"].map(CLASES_VIAS).astype(float)
    vias["geometry"] = vias.geometry.simplify(1.0, preserve_topology=True)
    vias = vias[~vias.geometry.is_empty]
    vias.to_file(DATA / "vias_3116.gpkg", driver="GPKG", layer="vias")
    log(f"  {len(vias):,} tramos de vía")

    # ------------------------------------------------------------------ AGUA
    log("Procesando agua...")
    agua = gpd.read_parquet(DATA / "overture" / "agua.parquet",
                            columns=["id", "class", "subtype", "geometry"])
    agua = agua.set_crs("EPSG:4326", allow_override=True).to_crs(CRS_METRICO)
    agua = agua.clip(gpd.GeoSeries([box(*BBOX_4326)], crs="EPSG:4326").to_crs(CRS_METRICO).iloc[0])
    # Ríos y quebradas vienen como líneas: se convierten en franjas de 6 m.
    lineas = agua[agua.geometry.geom_type.isin(["LineString", "MultiLineString"])].copy()
    if len(lineas):
        lineas["geometry"] = lineas.geometry.buffer(6.0)
        agua = gpd.GeoDataFrame(
            pd.concat([agua[~agua.index.isin(lineas.index)], lineas], ignore_index=True),
            crs=CRS_METRICO,
        )
    agua = agua[agua.geometry.geom_type.isin(["Polygon", "MultiPolygon"])]
    agua["geometry"] = agua.geometry.simplify(1.0, preserve_topology=True)
    agua = agua[~agua.geometry.is_empty]
    agua.to_file(DATA / "agua_3116.gpkg", driver="GPKG", layer="agua")
    log(f"  {len(agua):,} cuerpos/cauces de agua")

    # --------------------------------------------------------- ZONAS VERDES
    log("Procesando zonas verdes...")
    verde = gpd.read_parquet(DATA / "overture" / "zonas_verdes.parquet",
                             columns=["id", "class", "subtype", "geometry"])
    verde = verde[verde["class"].isin(CLASES_VERDE)]
    verde = verde.set_crs("EPSG:4326", allow_override=True).to_crs(CRS_METRICO)
    verde = verde.clip(gpd.GeoSeries([box(*BBOX_4326)], crs="EPSG:4326").to_crs(CRS_METRICO).iloc[0])
    verde = verde[verde.geometry.geom_type.isin(["Polygon", "MultiPolygon"])]
    verde["geometry"] = verde.geometry.simplify(1.0, preserve_topology=True)
    verde = verde[~verde.geometry.is_empty]
    verde.to_file(DATA / "zonas_verdes_3116.gpkg", driver="GPKG", layer="zonas_verdes")
    log(f"  {len(verde):,} zonas verdes")

    # ------------------------------------------------------ BLOQUES Y ESCENA
    xmin, ymin, xmax, ymax = ed.total_bounds
    xmed = (xmin + xmax) / 2.0
    ymed = (ymin + ymax) / 2.0
    transformador = Transformer.from_crs(CRS_METRICO, 4326, always_xy=True)

    def bloque(nombre: str, filtro, cx: float, cy: float):
        sub_ed = ed[filtro(ed)].copy()
        sub_vias = vias[filtro(vias)].copy()
        sub_agua = agua[filtro(agua)].copy()
        sub_verde = verde[filtro(verde)].copy()
        if not len(sub_ed):
            return None

        origen_z = float(np.median(sub_ed["base_m"].to_numpy()))
        lon, lat = transformador.transform(cx, cy)

        # Edificios: vértices locales y base relativa al origen.
        ev, eo, _ = empaquetar_poligonos(sub_ed.geometry.to_list())
        ev -= np.array([cx, cy], dtype=np.float32)
        bases = (sub_ed["base_m"].to_numpy() - origen_z).astype(np.float32)
        alturas = sub_ed["altura_m"].to_numpy().astype(np.float32)

        # Vías: muestrear el terreno en cada vértice.
        vv, vo, vz, va = [], [0], [], []
        for geom, ancho in zip(sub_vias.geometry, sub_vias["ancho_m"]):
            for linea in lineas_de(geom):
                coords = np.asarray(linea.coords, dtype=np.float32)
                if len(coords) < 2:
                    continue
                zs = muestrear_terreno(coords[:, 0], coords[:, 1], terreno, tx, ty) + 0.4
                vv.extend((coords[:, :2] - np.array([cx, cy], dtype=np.float32)).tolist())
                vz.extend(zs.tolist())
                vo.append(len(vv))
                va.append(float(ancho))
        vv = np.asarray(vv, dtype=np.float32)
        vo = np.asarray(vo, dtype=np.int32)
        vz = np.asarray(vz, dtype=np.float32)
        va = np.asarray(va, dtype=np.float32)

        # Agua y verde: polígonos planos a la cota del terreno + pequeño offset.
        z_agua = [
            float(muestrear_terreno(np.array([p.centroid.x]), np.array([p.centroid.y]),
                                    terreno, tx, ty)[0]) + 0.6
            for p in sub_agua.geometry
        ]
        av, ao, az = empaquetar_poligonos_z(sub_agua.geometry.to_list(), z_agua)
        if len(av):
            av -= np.array([cx, cy], dtype=np.float32)
        z_verde = [
            float(muestrear_terreno(np.array([p.centroid.x]), np.array([p.centroid.y]),
                                    terreno, tx, ty)[0]) + 0.3
            for p in sub_verde.geometry
        ]
        gv, go, gz = empaquetar_poligonos_z(sub_verde.geometry.to_list(), z_verde)
        if len(gv):
            gv -= np.array([cx, cy], dtype=np.float32)

        np.savez_compressed(
            BLOQUES / f"bloque_{nombre.lower()}.npz",
            edificios_vertices=ev, edificios_offsets=eo,
            edificios_bases=bases, edificios_alturas=alturas,
            vias_vertices=vv, vias_offsets=vo, vias_z=vz, vias_anchos=va,
            agua_vertices=av, agua_offsets=ao, agua_z=az,
            verde_vertices=gv, verde_offsets=go, verde_z=gz,
            origen=np.array([lon, lat, origen_z], dtype=np.float64),
            bbox=np.array([*sub_ed.total_bounds], dtype=np.float64),
        )
        log(f"  bloque {nombre}: {len(sub_ed):,} edificios, {len(sub_vias):,} vías, "
            f"{len(sub_agua):,} agua, {len(sub_verde):,} verde")
        return {
            "nombre": nombre,
            "origen": {"lat": float(lat), "lon": float(lon), "z_m": float(origen_z)},
            "bbox_3116": [float(v) for v in sub_ed.total_bounds],
            "edificios": int(len(sub_ed)),
            "edificios_reales": int((sub_ed.fuente_altura == "real").sum()),
            "edificios_estimadas": int((sub_ed.fuente_altura == "estimada").sum()),
            "vias": int(len(sub_vias)),
            "agua": int(len(sub_agua)),
            "verde": int(len(sub_verde)),
        }

    log("Empaquetando bloques...")
    bloques = []
    for nombre, filtro, cx, cy in [
        ("SW", lambda g: (g.geometry.centroid.x < xmed) & (g.geometry.centroid.y < ymed), (xmin + xmed) / 2, (ymin + ymed) / 2),
        ("SE", lambda g: (g.geometry.centroid.x >= xmed) & (g.geometry.centroid.y < ymed), (xmed + xmax) / 2, (ymin + ymed) / 2),
        ("NW", lambda g: (g.geometry.centroid.x < xmed) & (g.geometry.centroid.y >= ymed), (xmin + xmed) / 2, (ymed + ymax) / 2),
        ("NE", lambda g: (g.geometry.centroid.x >= xmed) & (g.geometry.centroid.y >= ymed), (xmed + xmax) / 2, (ymed + ymax) / 2),
    ]:
        datos = bloque(nombre, filtro, cx, cy)
        if datos:
            bloques.append(datos)

    # Escena completa para el render de Blender.
    log("Empaquetando escena completa...")
    cx, cy = (xmin + xmax) / 2.0, (ymin + ymax) / 2.0
    lon_c, lat_c = transformador.transform(cx, cy)
    origen_z = float(np.median(ed["base_m"].to_numpy()))
    ev, eo, _ = empaquetar_poligonos(ed.geometry.to_list())
    ev -= np.array([cx, cy], dtype=np.float32)

    vv, vo, vz, va = [], [0], [], []
    for geom, ancho in zip(vias.geometry, vias["ancho_m"]):
        for linea in lineas_de(geom):
            coords = np.asarray(linea.coords, dtype=np.float32)
            if len(coords) < 2:
                continue
            zs = muestrear_terreno(coords[:, 0], coords[:, 1], terreno, tx, ty) + 0.4 - origen_z
            vv.extend((coords[:, :2] - np.array([cx, cy], dtype=np.float32)).tolist())
            vz.extend(zs.tolist())
            vo.append(len(vv))
            va.append(float(ancho))

    z_agua = [
        float(muestrear_terreno(np.array([p.centroid.x]), np.array([p.centroid.y]),
                                terreno, tx, ty)[0]) + 0.6 - origen_z
        for p in agua.geometry
    ]
    av, ao, az = empaquetar_poligonos_z(agua.geometry.to_list(), z_agua)
    av -= np.array([cx, cy], dtype=np.float32)
    z_verde = [
        float(muestrear_terreno(np.array([p.centroid.x]), np.array([p.centroid.y]),
                                terreno, tx, ty)[0]) + 0.3 - origen_z
        for p in verde.geometry
    ]
    gv, go, gz = empaquetar_poligonos_z(verde.geometry.to_list(), z_verde)
    gv -= np.array([cx, cy], dtype=np.float32)

    np.savez_compressed(
        DATA / "escena_completa.npz",
        edificios_vertices=ev, edificios_offsets=eo,
        edificios_bases=(ed["base_m"].to_numpy() - origen_z).astype(np.float32),
        edificios_alturas=ed["altura_m"].to_numpy().astype(np.float32),
        vias_vertices=np.asarray(vv, dtype=np.float32),
        vias_offsets=np.asarray(vo, dtype=np.int32),
        vias_z=np.asarray(vz, dtype=np.float32),
        vias_anchos=np.asarray(va, dtype=np.float32),
        agua_vertices=av, agua_offsets=ao, agua_z=az,
        verde_vertices=gv, verde_offsets=go, verde_z=gz,
        origen=np.array([lon_c, lat_c, origen_z], dtype=np.float64),
        terreno_z=terreno,
        terreno_x=tx.astype(np.float64),
        terreno_y=ty.astype(np.float64),
    )

    reporte.update({
        "bbox_4326": list(BBOX_4326),
        "edificios": int(len(ed)),
        "edificios_reales": int((ed.fuente_altura == "real").sum()),
        "edificios_estimadas": int((ed.fuente_altura == "estimada").sum()),
        "altura_min_m": float(ed.altura_m.min()),
        "altura_max_m": float(ed.altura_m.max()),
        "vias": int(len(vias)),
        "agua": int(len(agua)),
        "zonas_verdes": int(len(verde)),
        "bloques": bloques,
        "dem": {"resolucion_m": RES_DEM, "min_m": float(terreno.min()), "max_m": float(terreno.max())},
    })
    (DATA / "reporte_procesamiento.json").write_text(
        json.dumps(reporte, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    log("Listo. Reporte en data/reporte_procesamiento.json")


if __name__ == "__main__":
    main()

"""Crea un proyecto QGIS con las capas del modelo y renderiza una figura 2D.

Uso:
    "C:\\Program Files\\QGIS 3.42.3\\bin\\python-qgis.bat" scripts/crear_qgis.py
"""

from __future__ import annotations

import os
from pathlib import Path

QGIS_PREFIX = r"C:\Program Files\QGIS 3.42.3\apps\qgis"
QGIS_PROJ = r"C:\Program Files\QGIS 3.42.3\share\proj"
os.environ.setdefault("PROJ_DATA", QGIS_PROJ)
os.environ.setdefault("PROJ_LIB", QGIS_PROJ)

from qgis.core import (  # noqa: E402
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsFillSymbol,
    QgsLineSymbol,
    QgsMapRendererParallelJob,
    QgsMapSettings,
    QgsProject,
    QgsRasterLayer,
    QgsRectangle,
    QgsSingleSymbolRenderer,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QSize  # noqa: E402
from qgis.PyQt.QtGui import QColor  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
DATA = RAIZ / "data"
QGIS_DIR = RAIZ / "qgis"
QGIS_DIR.mkdir(exist_ok=True)


def capa_vector(ruta: Path, nombre: str) -> QgsVectorLayer:
    capa = QgsVectorLayer(str(ruta), nombre, "ogr")
    if not capa.isValid():
        raise RuntimeError(f"No se pudo cargar {ruta}")
    return capa


def estilo_relleno(capa: QgsVectorLayer, color: str, borde: str = "#00000000", ancho: float = 0.0):
    simbolo = QgsFillSymbol.createSimple({
        "color": color,
        "outline_color": borde,
        "outline_width": str(ancho),
    })
    capa.setRenderer(QgsSingleSymbolRenderer(simbolo))


def estilo_linea(capa: QgsVectorLayer, color: str, ancho: float):
    simbolo = QgsLineSymbol.createSimple({
        "color": color,
        "width": str(ancho),
        "capstyle": "round",
        "joinstyle": "round",
    })
    capa.setRenderer(QgsSingleSymbolRenderer(simbolo))


def main() -> None:
    qgs = QgsApplication([], False)
    qgs.setPrefixPath(QGIS_PREFIX, True)
    qgs.initQgis()
    try:
        proyecto = QgsProject.instance()
        proyecto.clear()
        proyecto.setCrs(QgsCoordinateReferenceSystem("EPSG:3116"))
        proyecto.setTitle("Bogotá 3D — modelo y mapa base")

        edificios = capa_vector(DATA / "edificios_3116.gpkg", "Edificios (340k)")
        estilo_relleno(edificios, "#e7dfd2", "#9d9486", 0.05)

        vias = capa_vector(DATA / "vias_3116.gpkg", "Vías")
        estilo_linea(vias, "#4a4a4a", 0.35)

        agua = capa_vector(DATA / "agua_3116.gpkg", "Agua")
        estilo_relleno(agua, "#5b9bd5", "#2e6da4", 0.1)

        verde = capa_vector(DATA / "zonas_verdes_3116.gpkg", "Zonas verdes")
        estilo_relleno(verde, "#8fbf7f", "#5f8f52", 0.1)

        terreno = QgsRasterLayer(str(DATA / "terreno_3116.tif"), "DEM (20 m)")
        hillshade = QgsRasterLayer(str(DATA / "hillshade_3116.tif"), "Relieve")
        if not terreno.isValid() or not hillshade.isValid():
            raise RuntimeError("No se pudieron cargar los raster del DEM")

        for capa in (hillshade, terreno, verde, agua, vias, edificios):
            proyecto.addMapLayer(capa)

        # El hillshade se usa como fondo suave; el DEM queda debajo.
        hillshade.setOpacity(0.55)
        terreno.setOpacity(0.55)

        proyecto.write(str(QGIS_DIR / "bogota3d.qgz"))

        # Render 2D para la bitácora.
        settings = QgsMapSettings()
        settings.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:3116"))
        settings.setLayers([edificios, vias, agua, verde, terreno, hillshade])
        settings.setExtent(edificios.extent())
        settings.setOutputSize(QSize(1800, 1350))
        settings.setBackgroundColor(QColor("#f7f3ea"))
        settings.setOutputDpi(150)

        job = QgsMapRendererParallelJob(settings)
        job.start()
        job.waitForFinished()
        imagen = job.renderedImage()
        salida = RAIZ / "docs" / "renders" / "bogota_mapa_qgis.png"
        salida.parent.mkdir(parents=True, exist_ok=True)
        if not imagen.save(str(salida)):
            raise RuntimeError("No se pudo guardar la imagen del mapa")
        print(f"Proyecto: {QGIS_DIR / 'bogota3d.qgz'}")
        print(f"Figura: {salida} ({salida.stat().st_size / 1e6:.1f} MB)")
    finally:
        qgs.exitQgis()


if __name__ == "__main__":
    main()

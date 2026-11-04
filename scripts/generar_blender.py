"""Genera el modelo 3D de Bogotá en Blender y exporta GLB.

Modos:
    blender -b -P scripts/generar_blender.py -- --modo test
    blender -b -P scripts/generar_blender.py -- --modo bloques
    blender -b -P scripts/generar_blender.py -- --modo escena
    blender -b -P scripts/generar_blender.py -- --modo sobrevuelo

El modo `test` construye una muestra pequeña y renderiza un frame para validar
el aspecto y el tiempo. Los modos `bloques` y `escena` generan los entregables.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector

RAIZ = Path(__file__).resolve().parents[1]
DATA = RAIZ / "data"
MODELS = RAIZ / "models"
BLOQUES = MODELS / "bloques"
RENDERS = RAIZ / "docs" / "renders"
FRAMES = RAIZ / "renders" / "frames"
for carpeta in (MODELS, BLOQUES, RENDERS, FRAMES):
    carpeta.mkdir(parents=True, exist_ok=True)

COLORES_ALTURA = [
    "#f2e8d8", "#e6d2b8", "#d8b894", "#c99b72",
    "#b97f56", "#a5623f", "#8a4a31", "#6b3524",
]
COLOR_TERRENO = "#8fa06f"
COLOR_VIA = "#2f2f2f"
COLOR_AGUA = "#3d7fae"
COLOR_VERDE = "#5e8f4e"


def log(texto: str) -> None:
    print(f"[blender] {texto}", flush=True)


def hex_a_rgb(color: str) -> tuple[float, float, float, float]:
    color = color.lstrip("#")
    r, g, b = (int(color[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    return (r, g, b, 1.0)


def crear_material(nombre: str, color: str, rugosidad: float = 0.85):
    mat = bpy.data.materials.new(nombre)
    mat.use_nodes = True
    mat.diffuse_color = hex_a_rgb(color)
    nodos = mat.node_tree.nodes
    principled = nodos.get("Principled BSDF")
    if principled:
        principled.inputs["Base Color"].default_value = hex_a_rgb(color)
        principled.inputs["Roughness"].default_value = rugosidad
    return mat


def crear_material_terreno(nombre: str):
    mat = bpy.data.materials.new(nombre)
    mat.use_nodes = True
    mat.diffuse_color = hex_a_rgb(COLOR_TERRENO)
    nodos = mat.node_tree.nodes
    enlaces = mat.node_tree.links
    principled = nodos.get("Principled BSDF")
    if not principled:
        return mat

    texcoord = nodos.new("ShaderNodeTexCoord")
    separar = nodos.new("ShaderNodeSeparateXYZ")
    ramp = nodos.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.0
    ramp.color_ramp.elements[0].color = hex_a_rgb("#4f6b3f")
    ramp.color_ramp.elements[1].position = 0.35
    ramp.color_ramp.elements[1].color = hex_a_rgb("#8fa86a")
    e2 = ramp.color_ramp.elements.new(0.65)
    e2.color = hex_a_rgb("#b8a888")
    e3 = ramp.color_ramp.elements.new(1.0)
    e3.color = hex_a_rgb("#d0c8bc")
    enlaces.new(texcoord.outputs["Generated"], separar.inputs["Vector"])
    enlaces.new(separar.outputs["Z"], ramp.inputs["Fac"])
    enlaces.new(ramp.outputs["Color"], principled.inputs["Base Color"])
    principled.inputs["Roughness"].default_value = 0.95
    return mat


def limpiar_escena() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def crear_objeto_malla(nombre: str, vertices: np.ndarray, loops: np.ndarray,
                       starts: np.ndarray, totals: np.ndarray,
                       material_indices: np.ndarray | None,
                       materiales: list, suave: bool = False):
    malla = bpy.data.meshes.new(nombre)
    malla.vertices.add(len(vertices))
    malla.vertices.foreach_set("co", vertices.astype(np.float32).ravel())

    malla.loops.add(len(loops))
    malla.loops.foreach_set("vertex_index", loops.astype(np.int32))

    malla.polygons.add(len(starts))
    malla.polygons.foreach_set("loop_start", starts.astype(np.int32))
    malla.polygons.foreach_set("loop_total", totals.astype(np.int32))
    if material_indices is not None:
        malla.polygons.foreach_set("material_index", material_indices.astype(np.int32))
    malla.polygons.foreach_set("use_smooth", np.full(len(starts), suave, dtype=np.bool_))

    for mat in materiales:
        malla.materials.append(mat)

    malla.update()
    malla.validate(verbose=False)
    objeto = bpy.data.objects.new(nombre, malla)
    bpy.context.scene.collection.objects.link(objeto)
    return objeto


def crear_terreno(z: np.ndarray, x: np.ndarray, y: np.ndarray,
                  cx: float, cy: float, origen_z: float, material, paso: int = 2):
    z = z[::paso, ::paso].astype(np.float32) - origen_z
    x = x[::paso].astype(np.float32) - cx
    y = y[::paso].astype(np.float32) - cy
    alto, ancho = z.shape
    xx, yy = np.meshgrid(x, y)
    vertices = np.column_stack([xx.ravel(), yy.ravel(), z.ravel()]).astype(np.float32)

    celdas = (alto - 1) * (ancho - 1)
    loops = np.empty(celdas * 4, dtype=np.int32)
    starts = np.empty(celdas, dtype=np.int32)
    totals = np.full(celdas, 4, dtype=np.int32)
    idx = 0
    for fila in range(alto - 1):
        base = fila * ancho
        siguiente = base + ancho
        for col in range(ancho - 1):
            a = base + col
            loops[idx:idx + 4] = (a, a + 1, siguiente + col + 1, siguiente + col)
            starts[idx // 4] = idx
            idx += 4
    return crear_objeto_malla("Terreno", vertices, loops, starts, totals, None, [material], suave=True)


def crear_edificios(vertices_2d: np.ndarray, offsets: np.ndarray, bases: np.ndarray,
                    alturas: np.ndarray, nombre: str, materiales: list,
                    max_edificios: int | None = None):
    total = len(offsets) - 1
    if max_edificios is not None:
        total = min(total, max_edificios)
    log(f"  construyendo {nombre}: {total:,} edificios")

    anillos = []
    total_n = 0
    for i in range(total):
        anillo = vertices_2d[offsets[i]:offsets[i + 1]]
        if len(anillo) > 1 and np.allclose(anillo[0], anillo[-1]):
            anillo = anillo[:-1]
        if len(anillo) < 3:
            anillo = np.empty((0, 2), dtype=np.float32)
        anillos.append(anillo)
        total_n += len(anillo)

    vertices = np.empty((total_n * 2, 3), dtype=np.float32)
    loops = np.empty(total_n * 5, dtype=np.int32)
    starts = np.empty(total_n * 2, dtype=np.int32)
    totals = np.empty(total_n * 2, dtype=np.int32)
    mats = np.empty(total_n * 2, dtype=np.int32)

    bandas = np.clip(np.digitize(alturas[:total], [6, 9, 12, 18, 25, 40, 60]), 0, 7)

    v_off = 0
    l_off = 0
    f_off = 0
    for i, anillo in enumerate(anillos):
        n = len(anillo)
        if n < 3:
            continue
        base = float(bases[i])
        tope = base + float(alturas[i])
        vertices[v_off:v_off + n, 0:2] = anillo
        vertices[v_off:v_off + n, 2] = base
        vertices[v_off + n:v_off + 2 * n, 0:2] = anillo
        vertices[v_off + n:v_off + 2 * n, 2] = tope

        for j in range(n):
            a = v_off + j
            b = v_off + (j + 1) % n
            c = v_off + n + (j + 1) % n
            d = v_off + n + j
            loops[l_off:l_off + 4] = (a, b, c, d)
            starts[f_off] = l_off
            totals[f_off] = 4
            mats[f_off] = bandas[i]
            l_off += 4
            f_off += 1

        loops[l_off:l_off + n] = np.arange(v_off + n, v_off + 2 * n, dtype=np.int32)
        starts[f_off] = l_off
        totals[f_off] = n
        mats[f_off] = bandas[i]
        l_off += n
        f_off += 1
        v_off += 2 * n

    return crear_objeto_malla(nombre, vertices[:v_off], loops[:l_off], starts[:f_off],
                              totals[:f_off], mats[:f_off], materiales, suave=False)


def crear_vias(vertices_2d: np.ndarray, offsets: np.ndarray, z: np.ndarray,
               anchos: np.ndarray, nombre: str, material, max_tramos: int | None = None):
    total = len(offsets) - 1
    if max_tramos is not None:
        total = min(total, max_tramos)
    log(f"  construyendo {nombre}: {total:,} tramos")

    verts = []
    loops = []
    starts = []
    totals = []
    for i in range(total):
        ini, fin = offsets[i], offsets[i + 1]
        pts = vertices_2d[ini:fin]
        zs = z[ini:fin]
        if len(pts) < 2:
            continue
        ancho = float(anchos[i]) if i < len(anchos) else 4.0
        for j in range(len(pts) - 1):
            p0, p1 = pts[j], pts[j + 1]
            dx, dy = float(p1[0] - p0[0]), float(p1[1] - p0[1])
            largo = math.hypot(dx, dy)
            if largo < 0.01:
                continue
            nx, ny = -dy / largo * ancho / 2.0, dx / largo * ancho / 2.0
            base = len(verts)
            verts.extend([
                (p0[0] + nx, p0[1] + ny, float(zs[j])),
                (p1[0] + nx, p1[1] + ny, float(zs[j + 1])),
                (p1[0] - nx, p1[1] - ny, float(zs[j + 1])),
                (p0[0] - nx, p0[1] - ny, float(zs[j])),
            ])
            starts.append(len(loops))
            totals.append(4)
            loops.extend((base, base + 1, base + 2, base + 3))

    vertices = np.asarray(verts, dtype=np.float32)
    loops = np.asarray(loops, dtype=np.int32)
    starts = np.asarray(starts, dtype=np.int32)
    totals = np.asarray(totals, dtype=np.int32)
    return crear_objeto_malla(nombre, vertices, loops, starts, totals, None, [material], suave=False)


def crear_poligonos_planos(vertices_2d: np.ndarray, offsets: np.ndarray, z: np.ndarray,
                           nombre: str, material, max_poligonos: int | None = None):
    total = len(offsets) - 1
    if max_poligonos is not None:
        total = min(total, max_poligonos)
    log(f"  construyendo {nombre}: {total:,} polígonos")

    verts = []
    loops = []
    starts = []
    totals = []
    for i in range(total):
        anillo = vertices_2d[offsets[i]:offsets[i + 1]]
        if len(anillo) > 1 and np.allclose(anillo[0], anillo[-1]):
            anillo = anillo[:-1]
        if len(anillo) < 3:
            continue
        base = len(verts)
        zi = float(z[i]) if i < len(z) else 0.0
        verts.extend([(float(p[0]), float(p[1]), zi) for p in anillo])
        starts.append(len(loops))
        totals.append(len(anillo))
        loops.extend(range(base, base + len(anillo)))

    vertices = np.asarray(verts, dtype=np.float32)
    loops = np.asarray(loops, dtype=np.int32)
    starts = np.asarray(starts, dtype=np.int32)
    totals = np.asarray(totals, dtype=np.int32)
    return crear_objeto_malla(nombre, vertices, loops, starts, totals, None, [material], suave=False)


def materiales_edificios():
    return [crear_material(f"Edificio_{i+1:02d}", color) for i, color in enumerate(COLORES_ALTURA)]


def agregar_camara_sol():
    escena = bpy.context.scene
    mundo = bpy.data.worlds.new("Mundo Bogotá")
    mundo.use_nodes = True
    fondo = mundo.node_tree.nodes.get("Background")
    if fondo:
        fondo.inputs[0].default_value = (0.72, 0.82, 0.93, 1.0)
        fondo.inputs[1].default_value = 0.35
    escena.world = mundo

    luz = bpy.data.lights.new("Sol", type="SUN")
    luz.energy = 4.5
    luz.angle = math.radians(2.0)
    sol = bpy.data.objects.new("Sol", luz)
    sol.rotation_euler = (math.radians(50), 0.0, math.radians(35))
    escena.collection.objects.link(sol)

    cam_data = bpy.data.cameras.new("Camara")
    cam_data.lens = 35
    cam_data.clip_start = 5
    cam_data.clip_end = 60000
    camara = bpy.data.objects.new("Camara", cam_data)
    escena.collection.objects.link(camara)
    escena.camera = camara
    return camara, sol


def mirar_a(camara, objetivo: Vector):
    direccion = objetivo - camara.location
    camara.rotation_euler = direccion.to_track_quat("-Z", "Y").to_euler()


def configurar_workbench():
    escena = bpy.context.scene
    escena.render.engine = "BLENDER_WORKBENCH"
    escena.render.film_transparent = False
    escena.render.image_settings.file_format = "PNG"
    escena.render.image_settings.color_mode = "RGB"
    escena.view_settings.view_transform = "Standard"
    escena.view_settings.look = "None"
    sombreado = escena.display.shading
    sombreado.light = "STUDIO"
    try:
        sombreado.studio_light = "outdoor.sl"
    except Exception:
        pass
    sombreado.color_type = "MATERIAL"
    sombreado.show_shadows = True
    sombreado.shadow_intensity = 0.55
    sombreado.show_cavity = True
    sombreado.cavity_type = "BOTH"
    sombreado.curvature_ridge_factor = 1.2
    sombreado.curvature_valley_factor = 1.0
    sombreado.show_specular_highlight = False
    sombreado.background_type = "VIEWPORT"
    sombreado.background_color = (0.82, 0.87, 0.92)
    try:
        escena.display.render_aa = "8"
    except Exception:
        pass


def configurar_eevee():
    escena = bpy.context.scene
    escena.render.engine = "BLENDER_EEVEE"
    escena.render.film_transparent = False
    escena.render.image_settings.file_format = "PNG"
    escena.render.image_settings.color_mode = "RGB"
    escena.view_settings.view_transform = "Standard"
    escena.view_settings.look = "None"
    escena.view_settings.exposure = 0.0
    try:
        escena.eevee.taa_render_samples = 32
    except Exception:
        pass
    try:
        escena.eevee.use_gtao = True
        escena.eevee.gtao_distance = 80.0
    except Exception:
        pass


def exportar_glb(objetos, ruta: Path):
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objetos:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objetos[0]
    argumentos = dict(
        filepath=str(ruta),
        export_format="GLB",
        use_selection=True,
        export_apply=True,
        export_yup=True,
        export_draco_mesh_compression_enable=True,
        export_draco_mesh_compression_level=6,
        export_normals=False,
        export_texcoords=False,
        export_materials="EXPORT",
    )
    try:
        bpy.ops.export_scene.gltf(**argumentos)
    except TypeError:
        for clave in ("export_normals", "export_texcoords", "export_materials"):
            argumentos.pop(clave, None)
        bpy.ops.export_scene.gltf(**argumentos)
    log(f"  GLB: {ruta.name} ({ruta.stat().st_size / 1e6:.2f} MB)")


def cargar_npz(ruta: Path):
    return np.load(ruta, allow_pickle=False)


def construir_desde_npz(datos, nombre: str, max_edificios=None, max_vias=None,
                        max_agua=None, max_verde=None):
    mats_edificios = materiales_edificios()
    mat_via = crear_material("Vias", COLOR_VIA)
    mat_agua = crear_material("Agua", COLOR_AGUA, 0.35)
    mat_verde = crear_material("ZonasVerdes", COLOR_VERDE)

    objetos = []
    objetos.append(crear_edificios(
        datos["edificios_vertices"], datos["edificios_offsets"],
        datos["edificios_bases"], datos["edificios_alturas"],
        f"Edificios_{nombre}", mats_edificios, max_edificios,
    ))
    objetos.append(crear_vias(
        datos["vias_vertices"], datos["vias_offsets"], datos["vias_z"],
        datos["vias_anchos"], f"Vias_{nombre}", mat_via, max_vias,
    ))
    if len(datos["agua_vertices"]):
        objetos.append(crear_poligonos_planos(
            datos["agua_vertices"], datos["agua_offsets"], datos["agua_z"],
            f"Agua_{nombre}", mat_agua, max_agua,
        ))
    if len(datos["verde_vertices"]):
        objetos.append(crear_poligonos_planos(
            datos["verde_vertices"], datos["verde_offsets"], datos["verde_z"],
            f"Verdes_{nombre}", mat_verde, max_verde,
        ))
    return objetos


def modo_test() -> None:
    limpiar_escena()
    datos = cargar_npz(DATA / "escena_completa.npz")
    origen = datos["origen"]
    cx, cy = (float(v) for v in datos["centro_3116"])
    mat_terreno = crear_material_terreno("Terreno")
    crear_terreno(datos["terreno_z"], datos["terreno_x"], datos["terreno_y"],
                  cx, cy, float(origen[2]), mat_terreno, paso=4)
    construir_desde_npz(datos, "test", max_edificios=8000, max_vias=3000,
                        max_agua=80, max_verde=200)
    camara, _ = agregar_camara_sol()
    camara.location = Vector((-1500, -7600, 900))
    mirar_a(camara, Vector((-1500, -5800, 0)))
    configurar_workbench()
    escena = bpy.context.scene
    escena.render.resolution_x = 960
    escena.render.resolution_y = 540
    escena.render.resolution_percentage = 100
    salida = DATA / "test_workbench.png"
    escena.render.filepath = str(salida)
    inicio = time.time()
    bpy.ops.render.render(write_still=True)
    log(f"test render: {time.time() - inicio:.1f} s -> {salida}")


def modo_bloques() -> None:
    reporte = json.loads((DATA / "reporte_procesamiento.json").read_text(encoding="utf-8"))
    indice = {"sistema": "x=este, y=norte, z=altura; GLB exportado con Y-up", "bloques": {}}
    for info in reporte["bloques"]:
        nombre = info["nombre"]
        limpiar_escena()
        datos = cargar_npz(DATA / "bloques" / f"bloque_{nombre.lower()}.npz")
        objetos = construir_desde_npz(datos, nombre)
        salida = BLOQUES / f"bloque_{nombre.lower()}.glb"
        exportar_glb(objetos, salida)
        indice["bloques"][nombre] = {
            "archivo": f"models/bloques/bloque_{nombre.lower()}.glb",
            "origen": info["origen"],
            "caja": {
                "lat_min": 4.58 if nombre in ("SW", "SE") else 4.64,
                "lat_max": 4.64 if nombre in ("SW", "SE") else 4.70,
                "lon_min": -74.12 if nombre in ("SW", "NW") else -74.08,
                "lon_max": -74.08 if nombre in ("SW", "NW") else -74.04,
            },
            "edificios": info["edificios"],
            "edificios_reales": info["edificios_reales"],
            "edificios_estimadas": info["edificios_estimadas"],
            "tamano_bytes": salida.stat().st_size,
            "tamano_mb": round(salida.stat().st_size / 1e6, 2),
        }
        log(f"bloque {nombre} exportado")
    (BLOQUES / "index.json").write_text(
        json.dumps(indice, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    log("index.json actualizado")


def modo_escena() -> None:
    limpiar_escena()
    datos = cargar_npz(DATA / "escena_completa.npz")
    origen = datos["origen"]
    cx, cy = (float(v) for v in datos["centro_3116"])

    mat_terreno = crear_material_terreno("Terreno")
    crear_terreno(datos["terreno_z"], datos["terreno_x"], datos["terreno_y"],
                  cx, cy, float(origen[2]), mat_terreno, paso=2)
    objetos = construir_desde_npz(datos, "Bogota")
    camara, _ = agregar_camara_sol()

    # Vista aérea general.
    configurar_eevee()
    escena = bpy.context.scene
    escena.render.resolution_x = 1600
    escena.render.resolution_y = 900
    escena.render.resolution_percentage = 100
    camara.data.lens = 30
    camara.location = Vector((-5200, -7800, 3600))
    mirar_a(camara, Vector((0, 0, 0)))
    escena.render.filepath = str(RENDERS / "bogota_aerea.png")
    log("render aéreo con EEVEE...")
    bpy.ops.render.render(write_still=True)

    # Detalle del centro.
    camara.data.lens = 35
    camara.location = Vector((-2200, -2600, 1400))
    mirar_a(camara, Vector((0, 0, 0)))
    escena.render.filepath = str(RENDERS / "bogota_centro.png")
    log("render centro con EEVEE...")
    bpy.ops.render.render(write_still=True)

    bpy.ops.wm.save_as_mainfile(filepath=str(MODELS / "bogota.blend"))
    exportar_glb(objetos, MODELS / "bogota_completo.glb")
    log("escena guardada en models/bogota.blend")


def modo_sobrevuelo(rapido: bool = False) -> None:
    archivo = MODELS / "bogota.blend"
    if not archivo.exists():
        raise RuntimeError("Primero ejecuta --modo escena para crear models/bogota.blend")
    bpy.ops.wm.open_mainfile(filepath=str(archivo))
    configurar_workbench()
    escena = bpy.context.scene
    escena.render.resolution_x = 960 if rapido else 1280
    escena.render.resolution_y = 540 if rapido else 720
    escena.render.resolution_percentage = 100
    escena.render.fps = 12 if rapido else 24
    escena.frame_start = 1
    escena.frame_end = 96 if rapido else 288

    camara = escena.camera
    objetivo = bpy.data.objects.new("Objetivo", None)
    escena.collection.objects.link(objetivo)
    restriccion = camara.constraints.new("TRACK_TO")
    restriccion.target = objetivo
    restriccion.track_axis = "TRACK_NEGATIVE_Z"
    restriccion.up_axis = "UP_Y"

    # Trayectoria sur -> centro -> norte, con ligera curva hacia el oriente.
    if rapido:
        clave = [
            (1, (-2600, -9800, 2600), (0, -4500, 0)),
            (24, (-1200, -5600, 1700), (0, -500, 0)),
            (48, (400, -1200, 1250), (0, 2600, 0)),
            (72, (1500, 2600, 1350), (0, 5600, 0)),
            (96, (600, 7200, 1900), (0, 9200, 0)),
        ]
    else:
        clave = [
            (1, (-2600, -9800, 2600), (0, -4500, 0)),
            (72, (-1200, -5600, 1700), (0, -500, 0)),
            (144, (400, -1200, 1250), (0, 2600, 0)),
            (216, (1500, 2600, 1350), (0, 5600, 0)),
            (288, (600, 7200, 1900), (0, 9200, 0)),
        ]
    for frame, pos, target in clave:
        camara.location = Vector(pos)
        objetivo.location = Vector(target)
        camara.keyframe_insert(data_path="location", frame=frame)
        objetivo.keyframe_insert(data_path="location", frame=frame)
    for objeto in (camara, objetivo):
        try:
            if objeto.animation_data and objeto.animation_data.action:
                for fcurve in objeto.animation_data.action.fcurves:
                    for punto in fcurve.keyframe_points:
                        punto.interpolation = "BEZIER"
                        punto.easing = "EASE_IN_OUT"
        except Exception as error:  # noqa: BLE001
            log(f"aviso: no se pudo ajustar la interpolación ({error})")

    frames_dir = FRAMES / "rapido" if rapido else FRAMES
    frames_dir.mkdir(parents=True, exist_ok=True)
    inicio = time.time()
    for frame in range(escena.frame_start, escena.frame_end + 1):
        salida = frames_dir / f"frame_{frame:04d}.png"
        if salida.exists() and salida.stat().st_size > 1000:
            continue
        escena.frame_set(frame)
        escena.render.filepath = str(salida)
        bpy.ops.render.render(write_still=True)
        if frame % 24 == 0:
            log(f"  frame {frame}/{escena.frame_end} ({time.time() - inicio:.0f} s)")
    log(f"sobrevuelo renderizado en {time.time() - inicio:.0f} s")


def construir_zona():
    limpiar_escena()
    datos = cargar_npz(DATA / "zona" / "zona.npz")
    origen = datos["origen"]
    cx, cy = (float(v) for v in datos["centro_3116"])
    terreno = crear_terreno(datos["terreno_z"], datos["terreno_x"], datos["terreno_y"],
                            cx, cy, float(origen[2]), crear_material_terreno("Terreno"), paso=1)
    objetos = construir_desde_npz(datos, "Zona")
    camara, _ = agregar_camara_sol()
    return terreno, objetos, camara


def modo_zona() -> None:
    """Genera el GLB del mapa, la escena .blend y una imagen de la zona pequeña."""
    terreno, objetos, camara = construir_zona()
    carpeta = MODELS / "zona"
    carpeta.mkdir(exist_ok=True)
    glb = carpeta / "bogota_centro.glb"
    exportar_glb(objetos, glb)
    reporte = json.loads((DATA / "zona" / "reporte_zona.json").read_text(encoding="utf-8"))
    indice = {
        "sistema": "x=este, y=norte, z=altura; GLB exportado con Y-up",
        "bloques": {
            "CENTRO": {
                "archivo": "models/zona/bogota_centro.glb",
                "origen": reporte["origen"],
                "edificios": reporte["edificios"],
                "tamano_mb": round(glb.stat().st_size / 1e6, 2),
            }
        },
    }
    (carpeta / "index.json").write_text(json.dumps(indice, indent=2, ensure_ascii=False), encoding="utf-8")
    configurar_workbench()
    escena = bpy.context.scene
    escena.render.resolution_x = 1280
    escena.render.resolution_y = 720
    escena.render.resolution_percentage = 100
    camara.location = Vector((-2300, -2700, 1100))
    mirar_a(camara, Vector((0, 200, 100)))
    escena.render.filepath = str(RENDERS / "zona_aerea.png")
    bpy.ops.render.render(write_still=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(carpeta / "bogota_centro.blend"))
    log("zona lista")


CLAVES_VUELO = [
    (1, (-2500, -2700, 1000), (-300, -300, 50)),
    (60, (-1500, -1500, 620), (200, 100, 60)),
    (120, (-700, -300, 480), (500, 900, 80)),
    (180, (300, 1000, 560), (900, 300, 300)),
    (240, (-200, 2300, 900), (900, -300, 500)),
]


def modo_vuelo_zona(prueba: bool = False) -> None:
    """Renderiza el sobrevuelo por cuadros; si se interrumpe, retoma donde quedó."""
    archivo = MODELS / "zona" / "bogota_centro.blend"
    bpy.ops.wm.open_mainfile(filepath=str(archivo))
    configurar_workbench()
    escena = bpy.context.scene
    escena.render.resolution_x = 960
    escena.render.resolution_y = 540
    escena.render.resolution_percentage = 100
    camara = escena.camera
    objetivo = bpy.data.objects.new("Objetivo", None)
    escena.collection.objects.link(objetivo)
    restriccion = camara.constraints.new("TRACK_TO")
    restriccion.target = objetivo
    restriccion.track_axis = "TRACK_NEGATIVE_Z"
    restriccion.up_axis = "UP_Y"
    for frame, pos, target in CLAVES_VUELO:
        camara.location = Vector(pos)
        objetivo.location = Vector(target)
        camara.keyframe_insert(data_path="location", frame=frame)
        objetivo.keyframe_insert(data_path="location", frame=frame)
    carpeta = FRAMES / "zona"
    carpeta.mkdir(parents=True, exist_ok=True)
    cuadros = [1, 60, 120, 180, 240] if prueba else range(1, 241)
    inicio = time.time()
    for frame in cuadros:
        salida = carpeta / f"frame_{frame:04d}.png"
        if salida.exists() and salida.stat().st_size > 1000:
            continue
        escena.frame_set(frame)
        escena.render.filepath = str(salida)
        bpy.ops.render.render(write_still=True)
        log(f"cuadro {frame} ({time.time() - inicio:.0f} s)")
    log("vuelo terminado")


def modo_video() -> None:
    """Une los cuadros de renders/frames/zona en docs/renders/sobrevuelo.mp4."""
    limpiar_escena()
    escena = bpy.context.scene
    carpeta = FRAMES / "zona"
    nombres = sorted(p.name for p in carpeta.glob("frame_*.png"))
    secuencia = escena.sequence_editor_create()
    tira = secuencia.strips.new_image("vuelo", str(carpeta / nombres[0]), 1, 1)
    for nombre in nombres[1:]:
        tira.elements.append(nombre)
    tira.frame_final_duration = len(nombres)
    escena.frame_start = 1
    escena.frame_end = len(nombres)
    escena.render.fps = 24
    escena.render.resolution_x = 960
    escena.render.resolution_y = 540
    escena.render.resolution_percentage = 100
    escena.render.use_sequencer = True
    ajustes = escena.render.image_settings
    if hasattr(ajustes, "media_type"):
        ajustes.media_type = "VIDEO"
    ajustes.file_format = "FFMPEG"
    escena.render.ffmpeg.format = "MPEG4"
    escena.render.ffmpeg.codec = "H264"
    escena.render.ffmpeg.constant_rate_factor = "MEDIUM"
    escena.render.ffmpeg.audio_codec = "NONE"
    escena.render.filepath = str(RENDERS / "sobrevuelo.mp4")
    escena.render.use_file_extension = False
    bpy.ops.render.render(animation=True)
    log("video listo")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--modo", choices=["test", "bloques", "escena", "sobrevuelo", "zona", "vuelo_zona", "video"],
                        default="test")
    parser.add_argument("--rapido", action="store_true")
    parser.add_argument("--prueba", action="store_true")
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    args = parser.parse_args(argv)
    if args.modo == "test":
        modo_test()
    elif args.modo == "bloques":
        modo_bloques()
    elif args.modo == "escena":
        modo_escena()
    elif args.modo == "sobrevuelo":
        modo_sobrevuelo(rapido=args.rapido)
    elif args.modo == "zona":
        modo_zona()
    elif args.modo == "vuelo_zona":
        modo_vuelo_zona(prueba=args.prueba)
    elif args.modo == "video":
        modo_video()


if __name__ == "__main__":
    main()

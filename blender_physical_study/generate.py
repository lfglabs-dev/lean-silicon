#!/usr/bin/env python3
"""Headless Blender 4.x generator for a conceptual leanSilicon die study."""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from inventory import BASE_COMMIT, manifest  # noqa: E402

NOTICE = "CONCEPTUAL · SKY130-INFORMED · NOT GDS/P&R"
OUT = HERE / "artifacts"
CELL_PITCH = 0.205
GRID = 410
DIE = 92.0

COLORS = {
    "logic": (0.04, 0.38, 0.74, 1),
    "mux": (0.92, 0.32, 0.08, 1),
    "sequential": (0.64, 0.18, 0.82, 1),
    "invert": (0.02, 0.66, 0.54, 1),
    "xor": (0.96, 0.66, 0.05, 1),
    "substrate": (0.025, 0.055, 0.08, 1),
    "pad": (0.82, 0.56, 0.12, 1),
    "poly": (0.84, 0.16, 0.12, 1),
    "li1": (0.52, 0.54, 0.58, 1),
    "m1": (0.92, 0.48, 0.10, 1),
    "m2": (0.14, 0.72, 0.88, 1),
    "m3": (0.76, 0.28, 0.92, 1),
    "m4": (0.20, 0.82, 0.46, 1),
    "m5": (0.94, 0.82, 0.16, 1),
}


def material(name, color, metallic=0.0, roughness=0.38, emission=0.0):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = color
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = color
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    if emission:
        bsdf.inputs["Emission Color"].default_value = color
        bsdf.inputs["Emission Strength"].default_value = emission
    return mat


def cube(name, location, scale, mat, bevel=0.0, collection=None):
    bpy.ops.mesh.primitive_cube_add(location=location)
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.append(mat)
    if bevel:
        mod = obj.modifiers.new("soft_edges", "BEVEL")
        mod.width = bevel
        mod.segments = 2
    if collection:
        for current in list(obj.users_collection):
            current.objects.unlink(obj)
        collection.objects.link(obj)
    return obj


def cell_group(cell_type):
    if "DFF" in cell_type:
        return "sequential"
    if "MUX" in cell_type:
        return "mux"
    if "XOR" in cell_type:
        return "xor"
    if "NOT" in cell_type:
        return "invert"
    return "logic"


def make_cell_points(cell_type, count, offset, mat, proto):
    """One mesh vertex per logical cell, rendered as linked cube instances."""
    positions = []
    for index in range(offset, offset + count):
        row, col = divmod(index, GRID)
        x = (col - (GRID - 1) / 2) * CELL_PITCH
        y = (row - (GRID - 1) / 2) * CELL_PITCH
        # Alternating physical-looking rows, deterministically derived only.
        if row % 2:
            x = -x
        positions.append((x, y, 0.82))
    mesh = bpy.data.meshes.new(f"{cell_type}_points")
    mesh.from_pydata(positions, [], [])
    obj = bpy.data.objects.new(f"cells_{cell_type}", mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj["logical_cell_type"] = cell_type
    obj["exact_instance_count"] = count

    nodes = bpy.data.node_groups.new(f"instance_{cell_type}", "GeometryNodeTree")
    nodes.interface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    nodes.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    group_in = nodes.nodes.new("NodeGroupInput")
    group_out = nodes.nodes.new("NodeGroupOutput")
    instance = nodes.nodes.new("GeometryNodeInstanceOnPoints")
    info = nodes.nodes.new("GeometryNodeObjectInfo")
    info.transform_space = "ORIGINAL"
    info.inputs["Object"].default_value = proto
    nodes.links.new(group_in.outputs["Geometry"], instance.inputs["Points"])
    nodes.links.new(info.outputs["Geometry"], instance.inputs["Instance"])
    nodes.links.new(instance.outputs["Instances"], group_out.inputs["Geometry"])
    obj.modifiers.new("exact_cell_instances", "NODES").node_group = nodes
    return obj


def layer_stripes(name, z, color, horizontal, spacing, width, exploded):
    coll = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(coll)
    mat = material(name, color, metallic=0.65, roughness=0.26)
    lift = z + (z * 5.2 if exploded else 0)
    for i in range(-9, 10):
        p = i * spacing
        loc = (0, p, lift) if horizontal else (p, 0, lift)
        scale = (42, width, 0.045) if horizontal else (width, 42, 0.045)
        cube(f"{name}_{i:+03d}", loc, scale, mat, collection=coll)
    coll["conceptual_layer"] = name
    return coll


def add_text(name, body, location, size, mat, align="CENTER"):
    curve = bpy.data.curves.new(name, "FONT")
    curve.body = body
    curve.align_x = align
    curve.align_y = "CENTER"
    curve.size = size
    curve.extrude = 0.012
    obj = bpy.data.objects.new(name, curve)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = location
    obj.data.materials.append(mat)
    return obj


def point_camera(camera, target):
    camera.rotation_euler = (Vector(target) - camera.location).to_track_quat("-Z", "Y").to_euler()


def camera(name, location, target=(0, 0, 4), lens=52):
    data = bpy.data.cameras.new(name)
    data.lens = lens
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = location
    point_camera(obj, target)
    return obj


def attach_notice(cam, text_mat, back_mat):
    backing = cube("render_notice_back", (0, 0, 0), (3.05, 0.25, 0.018), back_mat)
    notice = add_text("render_notice", NOTICE, (0, 0, 0), 0.22, text_mat)
    position_notice(cam)
    return notice, backing


def position_notice(cam):
    """Place overlay geometry in world space just inside the active frustum."""
    specs = (
        ("render_notice_back", (0, -1.48, -10), 0.0),
        ("render_notice", (0, -1.49, -9.94), 0.0),
    )
    for name, location, rotation in specs:
        obj = bpy.data.objects.get(name)
        if obj:
            obj.parent = None
            obj.matrix_world = (
                cam.matrix_world
                @ Matrix.Translation(location)
                @ Matrix.Rotation(rotation, 4, "X")
            )


def setup_scene(exploded=False):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.eevee.taa_render_samples = 4
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = False
    scene.render.resolution_percentage = 100
    scene.render.image_settings.color_depth = "8"
    scene.render.image_settings.compression = 35
    scene.render.fps = 24
    scene.render.fps_base = 1
    scene.world = bpy.data.worlds.new("study_world")
    scene.world.color = (0.006, 0.012, 0.025)
    scene.view_settings.look = "AgX - Medium High Contrast"
    scene.view_settings.exposure = 2.1

    mats = {key: material(key, value) for key, value in COLORS.items()}
    mats["metal"] = material("metal", (0.68, 0.72, 0.76, 1), 0.82, 0.2)
    mats["white"] = material("white_emission", (1, 1, 1, 1), emission=3)
    mats["black"] = material("notice_back", (0.004, 0.006, 0.012, 0.93), roughness=0.8)

    cube("die_substrate", (0, 0, 0), (46, 46, 0.6), mats["substrate"], 0.8)
    cube("active_area", (0, 0, 0.66), (43.2, 43.2, 0.08), mats["logic"], 0.25)

    pad_coll = bpy.data.collections.new("pad_ring")
    scene.collection.children.link(pad_coll)
    pad_positions = []
    for i in range(20):
        p = -40 + i * (80 / 19)
        pad_positions.extend(((p, -44.3, 0.95), (p, 44.3, 0.95), (-44.3, p, 0.95), (44.3, p, 0.95)))
    for index, pos in enumerate(pad_positions):
        scale = (1.25, 0.75, 0.14) if abs(pos[1]) > 44 else (0.75, 1.25, 0.14)
        cube(f"pad_{index:03d}", pos, scale, mats["pad"], 0.16, pad_coll)

    proto_coll = bpy.data.collections.new("cell_prototypes")
    scene.collection.children.link(proto_coll)
    # Geometry Nodes must be able to resolve these linked instance sources.
    # They remain visually absent because their source coordinates are below.
    proto_coll.hide_render = False
    prototypes = {}
    for group in ("logic", "mux", "sequential", "invert", "xor"):
        height = 0.16 if group != "sequential" else 0.25
        prototypes[group] = cube(
            f"prototype_{group}", (0, 0, -10), (0.085, 0.075, height),
            mats[group], 0.018, proto_coll
        )

    inv = manifest()
    offset = 0
    for cell_type, count in inv["cell_types"].items():
        group = cell_group(cell_type)
        make_cell_points(cell_type, count, offset, mats[group], prototypes[group])
        offset += count

    # Abstract—not routed—power straps and clock spine.
    for x in (-39, 0, 39):
        cube(f"power_strap_{x:+03}", (x, 0, 2.0), (0.55, 41.5, 0.12), mats["m5"])
    cube("clock_spine", (0, 0, 2.25), (40.5, 0.28, 0.12), mats["m4"])
    for x in range(-36, 37, 12):
        cube(f"clock_branch_{x:+03}", (x, 0, 2.2), (0.14, 36, 0.08), mats["m4"])

    layer_stripes("poly", 0.20, COLORS["poly"], False, 4.5, 0.08, exploded)
    layer_stripes("LI1", 0.30, COLORS["li1"], True, 4.5, 0.09, exploded)
    for idx, (name, horiz) in enumerate((("M1", False), ("M2", True), ("M3", False), ("M4", True), ("M5", False))):
        layer_stripes(name, 1.05 + idx * 0.18, COLORS[name.lower()], horiz, 4.5 + idx * 0.35, 0.10 + idx * 0.025, exploded)

    add_text("title", "leanSilicon · LOGICAL INVENTORY STUDY", (-44, 47.8, 1.2), 1.9, mats["white"], "LEFT")
    add_text("inventory_label", f"{inv['cell_total']:,} exact logical-cell instances · 16 types", (-44, 45.2, 1.2), 0.9, mats["white"], "LEFT")

    cams = {
        "hero": camera("camera_hero", (112, -120, 105), (0, 0, 2), 56),
        "top": camera("camera_top", (0, 0, 165), (0, 0, 0), 58),
        "closeup": camera("camera_closeup", (42, -58, 27), (20, -18, 1.4), 64),
        "exploded": camera("camera_exploded", (125, -132, 112), (0, 0, 12), 54),
    }
    scene.camera = cams["exploded" if exploded else "hero"]
    attach_notice(scene.camera, mats["white"], mats["black"])

    for name, loc, energy, size, color in (
        ("key", (40, -55, 125), 12500, 38, (1.0, 0.84, 0.68)),
        ("fill", (-90, -20, 65), 7800, 45, (0.46, 0.66, 1.0)),
        ("rim", (15, 90, 100), 14500, 30, (0.30, 0.86, 1.0)),
    ):
        data = bpy.data.lights.new(name, "AREA")
        data.energy, data.shape, data.size, data.color = energy, "DISK", size, color
        obj = bpy.data.objects.new(name, data)
        scene.collection.objects.link(obj)
        obj.location = loc
        point_camera(obj, (0, 0, 0))

    scene["notice"] = NOTICE
    scene["base_commit"] = BASE_COMMIT
    scene["inventory_total"] = inv["cell_total"]
    scene["inventory_source_sha256"] = inv["source_sha256"]
    return scene, cams


def move_notice(old_cam, new_cam):
    position_notice(new_cam)


def render_view(scene, cams, key, filename, width, height, transparent=False):
    old = scene.camera
    scene.camera = cams[key]
    move_notice(old, scene.camera)
    scene.render.resolution_x, scene.render.resolution_y = width, height
    scene.render.film_transparent = transparent
    scene.render.filepath = str(OUT / filename)
    started = time.monotonic()
    bpy.ops.render.render(write_still=True)
    return round(time.monotonic() - started, 3)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--", dest="separator", action="store_true")
    parser.add_argument("--profile", choices=("preview", "all", "scene"), default="all")
    parser.add_argument("--animation", action="store_true")
    args, _ = parser.parse_known_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    OUT.mkdir(exist_ok=True)
    timings = {}

    scene, cams = setup_scene(False)
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT / "lean_silicon_physical_study.blend"))
    if args.profile == "scene":
        return
    if args.profile == "preview":
        scene.eevee.taa_render_samples = 1
        timings["preview_hero.png"] = render_view(scene, cams, "hero", "preview_hero.png", 640, 360)
    else:
        timings["hero_4k.png"] = render_view(scene, cams, "hero", "hero_4k.png", 3840, 2160)
        timings["top_view.png"] = render_view(scene, cams, "top", "top_view.png", 2400, 2400)
        timings["close_up.png"] = render_view(scene, cams, "closeup", "close_up.png", 2560, 1440)
        timings["hero_transparent.png"] = render_view(scene, cams, "hero", "hero_transparent.png", 3840, 2160, True)

        scene, cams = setup_scene(True)
        timings["exploded_stack.png"] = render_view(scene, cams, "exploded", "exploded_stack.png", 3840, 2160)
        if args.animation:
            bpy.ops.wm.open_mainfile(filepath=str(OUT / "lean_silicon_physical_study.blend"))
            scene = bpy.context.scene
            cam = bpy.data.objects["camera_hero"]
            scene.camera = cam
            scene.render.film_transparent = False
            scene.render.resolution_x, scene.render.resolution_y = 1920, 1080
            scene.eevee.taa_render_samples = 1
            scene.render.image_settings.file_format = "FFMPEG"
            scene.render.ffmpeg.format = "MPEG4"
            scene.render.ffmpeg.codec = "H264"
            scene.render.ffmpeg.constant_rate_factor = "MEDIUM"
            scene.render.filepath = str(OUT / "orbit.mp4")
            scene.frame_start, scene.frame_end = 1, 240
            center = Vector((0, 0, 2))
            for frame in range(1, 241):
                angle = 2 * math.pi * (frame - 1) / 239
                cam.location = (132 * math.cos(angle), 132 * math.sin(angle), 88)
                point_camera(cam, center)
                cam.keyframe_insert("location", frame=frame)
                cam.keyframe_insert("rotation_euler", frame=frame)
            started = time.monotonic()
            bpy.ops.render.render(animation=True)
            timings["orbit.mp4"] = round(time.monotonic() - started, 3)

    (OUT / "render_timings.json").write_text(json.dumps(timings, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()

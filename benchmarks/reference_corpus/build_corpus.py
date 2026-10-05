# -*- coding: utf-8 -*-
"""pkg259 Phase 1 -- reference-corpus builder CLI (runs INSIDE Blender).

Thin wrapper per the Phase-0 design doc Sec 4.2: parses arguments, calls the
per-family scene builders in ``benchmarks/blender_parity/scene_library.py``,
saves each as a ``.blend`` under ``benchmarks/reference_corpus/scenes/``, and
writes ``scenes/manifest.json`` (the #729 manifest schema, extended with
``family``/``builder_fn``/``feature_tags``/``assets``/``crops`` per Sec 4.1).

**Coverage-claim rule (binding, design doc Sec 4.1 / Sec 4.4):** a builder's
``tags`` return value is not trusted blindly -- this script cross-checks it
against every SUPPORTED/APPROXIMATED row ``docs/blender_parity/coverage_matrix.json``
assigns to that family (via the Phase-0 allocation table's ``ASSIGN`` map) and
raises loudly if a required row is missing from ``tags``, or if ``tags``
claims a row that does not exist for the family. DROPPED-SILENT rows the
builder marks via ``gap_tags`` become ``gap_card: true`` manifest entries;
every other DROPPED-SILENT row for the family is left OUT of the manifest and
instead reported (grouped by node) so it can be pasted into the corpus
README's gap registry -- see ``--print-gap-registry``.

Usage (run inside Blender, matching render_leg.py's ``--`` convention):
    blender --background --factory-startup --python build_corpus.py -- \
        --families materials_hall textures_mapping \
        --out-dir benchmarks/reference_corpus/scenes
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MATRIX_PATH = REPO_ROOT / "docs" / "blender_parity" / "coverage_matrix.json"
ALLOCATION_SCRIPT = REPO_ROOT / ".astroray_plan" / "docs" / "pkg259-phase0" / "build_allocation_table.py"
SCENE_LIBRARY_DIR = REPO_ROOT / "benchmarks" / "blender_parity"

BUILDERS = {
    "materials_hall": "build_materials_hall_scene",
    "textures_mapping": "build_textures_mapping_scene",
    "lighting_studio": "build_lighting_studio_scene",
    "world_sky_hdri": "build_world_sky_hdri_scene",
    "world_sky_sky": "build_world_sky_sky_scene",
    "geometry_zoo": "build_geometry_zoo_scene",
    "camera_lens": "build_camera_lens_scene",
    "camera_lens_ortho": "build_camera_lens_ortho_scene",   # #845
    "render_settings": "build_render_settings_scene",
    "volumes_smoke": "build_volumes_smoke_scene",   # pkg271
}
RESOLUTIONS = {
    "materials_hall": ("REFERENCE_MATERIALS_HALL_RES", "REFERENCE_MATERIALS_HALL_SAMPLES"),
    "textures_mapping": ("REFERENCE_TEXTURES_MAPPING_RES", "REFERENCE_TEXTURES_MAPPING_SAMPLES"),
    "lighting_studio": ("REFERENCE_LIGHTING_STUDIO_RES", "REFERENCE_LIGHTING_STUDIO_SAMPLES"),
    "world_sky_hdri": ("REFERENCE_WORLD_SKY_RES", "REFERENCE_WORLD_SKY_SAMPLES"),
    "world_sky_sky": ("REFERENCE_WORLD_SKY_RES", "REFERENCE_WORLD_SKY_SAMPLES"),
    "geometry_zoo": ("REFERENCE_GEOMETRY_ZOO_RES", "REFERENCE_GEOMETRY_ZOO_SAMPLES"),
    "camera_lens": ("REFERENCE_CAMERA_LENS_RES", "REFERENCE_CAMERA_LENS_SAMPLES"),
    "camera_lens_ortho": ("REFERENCE_CAMERA_LENS_ORTHO_RES", "REFERENCE_CAMERA_LENS_ORTHO_SAMPLES"),
    "render_settings": ("REFERENCE_RENDER_SETTINGS_RES", "REFERENCE_RENDER_SETTINGS_SAMPLES"),
    "volumes_smoke": ("REFERENCE_VOLUMES_RES", "REFERENCE_VOLUMES_SAMPLES"),
}
# pkg259 Phase 2: world_sky splits into two .blend files sharing one family
# tag (README "Naming and files" -- <family>_<part>.blend, allowed since
# design doc Sec 6.2 item 8) because a Blender scene has exactly one World,
# so "HDRI vs Sky, each against its own Cycles reference" cannot be one
# scene the way lighting_studio's four simultaneous light booths can.
# Scene ids not listed here use their own name as the family (1:1).
FAMILY_OF = {
    "world_sky_hdri": "world_sky",
    "world_sky_sky": "world_sky",
    "volumes_smoke": "volumes",   # pkg271 (scene id != family, like world_sky)
    "camera_lens_ortho": "camera_lens",   # #845: one active camera per scene
}
# The one non-procedural asset Phase 2 uses (design doc Sec 3.2/README asset
# table) -- recorded here so build_corpus.py's manifest carries the same
# licence data as the README instead of a second, driftable copy.
WORLD_SKY_HDRI_ASSET = {
    "path": "benchmarks/reference_corpus/assets/syferfontein_18d_clear_1k.hdr",
    "license": "CC0 1.0",
    "source_url": "https://polyhaven.com/a/syferfontein_18d_clear",
}


def _load_assign_map():
    """Import the Phase-0 allocation script's ``ASSIGN`` dict without adding
    it to sys.path permanently -- it is a one-off design artefact (not a
    shipped module, CLAUDE.md Sec 5b), but its (category, feature) ->
    (primary_family, secondary_families) map is the single source of truth
    for "which family owns this matrix row" and must not be re-derived by
    hand here."""
    spec = importlib.util.spec_from_file_location("pkg259_allocation", ALLOCATION_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # pkg259 Phase 2: SOCKET_OVERRIDE (added by pkg260) reassigns a small
    # number of individual ROWS to a family other than their (category,
    # feature) pair's default -- e.g. World's light_linking_shadow_linking
    # gap-card row belongs to lighting_studio, not world_sky, even though
    # every other World row stays world_sky. Returned alongside ASSIGN so
    # the family-membership check below matches the allocation script's own
    # resolution order exactly instead of silently ignoring per-row overrides.
    return module.ASSIGN, getattr(module, "SOCKET_OVERRIDE", {})


def _primary_family(assign, overrides, row):
    override = overrides.get((row["category"], row["feature"], row["socket_or_prop"]))
    if override is not None:
        return override[0]
    return assign[(row["category"], row["feature"])][0]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _build_one(bpy, scene_id: str, out_dir: Path, assign, overrides, matrix_rows):
    """Build one manifest entry keyed by ``scene_id``. ``scene_id`` is almost
    always the family name itself (materials_hall, textures_mapping,
    lighting_studio); ``world_sky_hdri``/``world_sky_sky`` are the one
    exception (pkg259 Phase 2) -- two ``.blend`` files sharing the
    ``world_sky`` family tag via ``FAMILY_OF``, because a Blender scene has
    exactly one World and "HDRI vs Sky, each against its own Cycles
    reference" cannot be one scene the way lighting_studio's four
    simultaneous light booths can."""
    sys.path.insert(0, str(SCENE_LIBRARY_DIR))
    import scene_library  # noqa: E402

    family = FAMILY_OF.get(scene_id, scene_id)
    builder_name = BUILDERS[scene_id]
    builder = getattr(scene_library, builder_name)
    scene, tags, crops, gap_tags = builder(bpy)

    res_name, samples_name = RESOLUTIONS[scene_id]
    res_x, res_y = getattr(scene_library, res_name)
    samples = getattr(scene_library, samples_name)

    tags_set = set(tags)
    gap_set = set(gap_tags)

    # Every row this family owns as PRIMARY assignment (secondary/cross-tag
    # families are bonus, not a requirement) -- SOCKET_OVERRIDE-resolved, see
    # _primary_family.
    family_rows = [r for r in matrix_rows if _primary_family(assign, overrides, r) == family]
    # ``world_sky`` is intentionally represented by two physical scenes: the
    # HDRI graph and the procedural-Sky graph.  Their union is the family
    # coverage population; requiring each file to contain the other World's
    # mutually-exclusive nodes makes canonical regeneration impossible.
    if scene_id == "world_sky_hdri":
        family_rows = [r for r in family_rows if r["bl_idname"] not in ("ShaderNodeTexSky",)]
    elif scene_id == "world_sky_sky":
        family_rows = [r for r in family_rows if r["bl_idname"] not in (
            "ShaderNodeTexEnvironment", "ShaderNodeMapping", "ShaderNodeTexCoord")]
    # #845: camera_lens likewise splits by projection -- the perspective hero
    # shot cannot show ORTHO, and the ortho grid has no lens/DoF.
    ortho_socks = {"type", "ortho_scale", "shift_x", "shift_y", "sensor_fit",
                   "clip_start", "clip_end"}
    if scene_id == "camera_lens":
        family_rows = [r for r in family_rows if r["socket_or_prop"] not in ("type", "ortho_scale")]
    elif scene_id == "camera_lens_ortho":
        family_rows = [r for r in family_rows if r["socket_or_prop"] in ortho_socks]

    # #996: SUPPORTED/APPROXIMATED rows the scanner credits but no scene wires yet (scenes/proof_pending.json,
    # shrink-only; tests/test_reference_corpus_manifest.py fails a stale entry). Not a tag, not a gap card.
    pending_path = out_dir / "proof_pending.json"
    pending = {(r["bl_idname"], r["socket_or_prop"])
               for r in (json.loads(pending_path.read_text(encoding="utf-8")).get(scene_id, [])
                         if pending_path.is_file() else [])}
    feature_tags = []
    missing = []
    covered_pairs = set()
    for row in family_rows:
        pair = (row["bl_idname"], row["socket_or_prop"])
        if row["classification"] in ("SUPPORTED", "APPROXIMATED"):
            if pair in tags_set:
                feature_tags.append({**{k: row[k] for k in
                                         ("category", "feature", "bl_idname", "socket_or_prop",
                                          "classification")},
                                      "gap_card": False})
                covered_pairs.add(pair)
            elif pair not in pending:
                missing.append(row)
        elif row["classification"] == "DROPPED-SILENT":
            if pair in gap_set:
                feature_tags.append({**{k: row[k] for k in
                                         ("category", "feature", "bl_idname", "socket_or_prop",
                                          "classification")},
                                      "gap_card": True})
                covered_pairs.add(pair)

    if missing:
        lines = "\n".join(f"  {r['bl_idname']} {r['socket_or_prop']} ({r['classification']})"
                           for r in missing)
        raise SystemExit(
            f"[pkg259] {scene_id}: builder does not actively wire "
            f"{len(missing)} required SUPPORTED/APPROXIMATED row(s):\n{lines}\n"
            f"Fix the builder in scene_library.py (wire it, or if it truly "
            f"cannot be demonstrated, this is a design-doc question, not a "
            f"silent skip).")

    stray = tags_set - {(r["bl_idname"], r["socket_or_prop"]) for r in family_rows}
    if stray:
        raise SystemExit(
            f"[pkg259] {scene_id}: builder tags {len(stray)} (bl_idname, socket) "
            f"pair(s) that are not a matrix row assigned to this family "
            f"(typo, or the allocation table needs updating): {sorted(stray)}")

    # DROPPED-SILENT rows NOT made into a gap card in-scene -- these are the
    # ones that belong in the README's gap registry (see --print-gap-registry).
    uncovered_dropped = [r for r in family_rows
                         if r["classification"] == "DROPPED-SILENT"
                         and (r["bl_idname"], r["socket_or_prop"]) not in gap_set]

    scene.render.engine = "CYCLES"
    scene.render.resolution_x = res_x
    scene.render.resolution_y = res_y
    scene.render.resolution_percentage = 100

    out_dir.mkdir(parents=True, exist_ok=True)
    blend_path = out_dir / f"{scene_id}.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))

    # HDRI world halves (pkg259 Phase 2) load their image via an absolute
    # path so the build can read real pixels; now that bpy.data.filepath is
    # the final saved location, rewrite it to the repo-relative "//..." form
    # and re-save so a fresh checkout on another machine resolves it from
    # THIS file's directory -- same pattern render_leg.py's --export-blend
    # path already uses for hdri_exterior_hair (Sec 4.1/README asset table).
    hdri_relpath = scene.get("hdri_relpath")
    assets = []
    if hdri_relpath:
        for img in bpy.data.images:
            if img.source == "FILE":
                img.filepath_raw = hdri_relpath
        bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
        assets = [{**WORLD_SKY_HDRI_ASSET, "sha256": _sha256(REPO_ROOT / WORLD_SKY_HDRI_ASSET["path"])}]

    # pkg271 volumes family: the builder wrote its synthetic .vdb grids into
    # benchmarks/reference_corpus/assets/ (deterministic numpy + Blender's
    # openvdb, no third-party data); point the Volume datablocks at them with a
    # blend-relative "//..." path and record them like the HDRI asset.
    vdb_paths = list(scene.get("volumes_vdb_paths", []))
    if vdb_paths:
        for vol in bpy.data.volumes:
            vol.filepath = bpy.path.relpath(vol.filepath)
        bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
        for vp in vdb_paths:
            rel = Path(vp).resolve().relative_to(REPO_ROOT)
            assets.append({"path": str(rel).replace("\\", "/"),
                           "license": "CC0 1.0 (synthetic, generated by scene_library."
                                      "write_volumes_vdbs)",
                           "source_url": "",
                           "sha256": _sha256(REPO_ROOT / rel)})

    # Reopen-verify (mirrors #729's manifest contract) + collect the census
    # from the REOPENED file, not the in-memory scene, so the manifest
    # reflects exactly what is committed.
    bpy.ops.wm.open_mainfile(filepath=str(blend_path))
    reopened_scene = bpy.context.scene
    obj_counts: dict = {}
    for obj in reopened_scene.objects:
        obj_counts[obj.type] = obj_counts.get(obj.type, 0) + 1
    node_ids = set()
    for mat in bpy.data.materials:
        if mat.use_nodes and mat.node_tree:
            node_ids.update(n.bl_idname for n in mat.node_tree.nodes)
    if reopened_scene.world and reopened_scene.world.use_nodes and reopened_scene.world.node_tree:
        node_ids.update(n.bl_idname for n in reopened_scene.world.node_tree.nodes)
    # pkg259 Phase 2: lighting_studio's SPOT booth carries a light node-tree
    # (ShaderNodeTexIES -> ShaderNodeEmission -> ShaderNodeOutputLight) --
    # Phase 1 never needed light node trees, so this loop is new.
    for light in bpy.data.lights:
        if getattr(light, "use_nodes", False) and light.node_tree:
            node_ids.update(n.bl_idname for n in light.node_tree.nodes)
    tri_count = 0
    curve_count = 0
    curve_point_count = 0
    for obj in reopened_scene.objects:
        if obj.type == "MESH":
            for poly in obj.data.polygons:
                tri_count += max(0, len(poly.vertices) - 2)
        elif obj.type == "CURVES":
            # pkg259 Phase 3: geometry_zoo is the first family after
            # hdri_exterior_hair (#729) to carry real Curves geometry --
            # Phase 1/2 hardcoded these fields to 0 since no family had any.
            curve_count += len(obj.data.curves)
            curve_point_count += len(obj.data.points)
    reopen_verified = bool(node_ids) and reopened_scene.camera is not None

    manifest_entry = {
        "family": family,
        "builder_fn": builder_name,
        "blend_path": str(blend_path.relative_to(REPO_ROOT)).replace("\\", "/"),
        "sha256": _sha256(blend_path),
        "settings": {
            "res_x": res_x, "res_y": res_y, "samples": samples,
            "saved_default_engine": "CYCLES",
        },
        "reopen_verified": reopen_verified,
        "triangle_count": tri_count,
        "curve_count": curve_count,
        "curve_point_count": curve_point_count,
        "object_counts": obj_counts,
        "node_ids": sorted(node_ids),
        "feature_tags": feature_tags,
        "assets": assets,
        "crops": crops,
    }
    # Gate-(c) metadata is emitted only by a scene that declares a role.  It
    # travels through the saved/reopened scene, never a side-channel manifest edit.
    gate_c = reopened_scene.get("gate_c")
    if gate_c is not None:
        def _plain(value):
            if hasattr(value, "keys"):
                return {str(key): _plain(value[key]) for key in value}
            if isinstance(value, (list, tuple)):
                return [_plain(item) for item in value]
            if isinstance(value, (str, int, float, bool)) or value is None:
                return value
            # Blender ID-property arrays are not Python lists after reopen.
            if type(value).__name__ == "IDPropertyArray":
                return [_plain(value[index]) for index in range(len(value))]
            if hasattr(value, "__iter__"):
                return [_plain(item) for item in value]
            raise ValueError(f"{scene_id}: gate_c metadata is not JSON-compatible ({type(value).__name__})")
        manifest_entry["gate_c"] = _plain(gate_c)
    return manifest_entry, uncovered_dropped


# --------------------------------------------------------------------------- #
# pkg284 Phase 1 -- corpus v2 (eight Cycles-parity scenes, one per transport
# feature). ``python build_corpus.py -- --families v2_light_tree ...``.
# Builders import the showcase scaffolding (benchmarks/blender_showcase/
# showcase.py) rather than copying it. ROIs are projected from world points
# through the scene camera so they follow the geometry (manifest ``crops``:
# normalised [x0, y0, x1, y1], row 0 = TOP, same as v1).
# --------------------------------------------------------------------------- #
V2_GATE_SPP = 64
V2_REFERENCE_SPP = 1024
V2_SEED = 278
V2_ASSETS = REPO_ROOT / "benchmarks" / "reference_corpus" / "assets"
V2_NO_GATE = ("v2_viewport",)
# pkg296 (#833): the volumes_mesh family is gated by its own test
# (tests/test_pkg296_mesh_volume_boundary.py, bands from volumes_mesh_bands.py),
# not by gates_v2.toml -- see _vm_* below.


def _load_showcase(addon_dir):
    sys.path.insert(0, str(REPO_ROOT / "benchmarks" / "blender_showcase"))
    import showcase  # noqa: E402  (imports bpy; only valid inside Blender)
    if addon_dir:
        showcase._bootstrap_addon(addon_dir)
    return showcase


class _Rois:
    """Collects ROIs as (world point, half-width as a fraction of image width)."""

    def __init__(self, scene):
        self.scene, self.items, self.notes = scene, {}, {}

    def add(self, name, point, hw, divergence=None):
        self.items[name] = (tuple(point), hw)
        if divergence:
            self.notes[name] = divergence

    def add_rect(self, name, rect, divergence=None):
        self.items[name] = ("rect", rect)
        if divergence:
            self.notes[name] = divergence

    def project(self):
        from bpy_extras.object_utils import world_to_camera_view
        from mathutils import Vector
        import bpy
        bpy.context.view_layer.update()
        sc, cam = self.scene, self.scene.camera
        aspect = sc.render.resolution_x / sc.render.resolution_y
        out = {}
        for name, (pt, hw) in self.items.items():
            if pt == "rect":
                out[name] = [round(c, 4) for c in hw]
                continue
            u, v, _ = world_to_camera_view(sc, cam, Vector(pt))
            cx, cy, hh = u, 1.0 - v, hw * aspect
            r = [cx - hw, cy - hh, cx + hw, cy + hh]
            r = [round(min(max(c, 0.0), 1.0), 4) for c in r]
            if r[2] - r[0] < 0.005 or r[3] - r[1] < 0.005:
                raise SystemExit(f"[pkg284] ROI {name!r} is off-frame: {r}")
            out[name] = r
        return out


def _v2_setup(sc, res, samples=V2_GATE_SPP, bounces=12):
    scene = sc._reset()
    sc._render_defaults(scene, samples=samples, max_bounces=bounces)
    _v2_finish(scene, res)
    return scene


def _v2_finish(scene, res):
    """Fixed-seed, adaptive-off, denoise-off, Standard view (spec Key decisions)."""
    scene.render.resolution_x, scene.render.resolution_y = res
    scene.cycles.samples = V2_GATE_SPP
    scene.cycles.seed = V2_SEED
    scene.cycles.use_animated_seed = False
    scene.cycles.use_denoising = False
    scene.cycles.use_adaptive_sampling = False
    scene.view_settings.view_transform = "Standard"


def _emitter(sc, sl, bpy, name, loc, size, strength, color=(1.0, 1.0, 1.0), sphere=False):
    if sphere:
        obj = sc._uv_sphere(name, loc, size, seg=32, rings=16)
    else:
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=loc)
        obj = bpy.context.active_object
        obj.name = name
        obj.scale = (size, size, size)
    mat, nt, emit, out = sl._emission_card_material(bpy, name + "Mat", strength)
    sl._sock(emit.inputs, "Color").default_value = (*color, 1.0)
    sc._assign(obj, mat)
    return obj


def _v2_light_tree(bpy, sc, sl, addon_dir):
    """Interior: 6 unequal mesh emitters + point + area(spread 45) + sun through a
    skylight + a closed emissive sphere (#886). Gates light tree / MIS / dedicated
    lamps / closed-emitter sampling (#763, #851, #859, #886)."""
    res = (320, 180)
    scene = _v2_setup(sc, res)
    sc._world((0.0, 0.0, 0.0), 0.0)
    grey = sc._principled("Wall", (0.72, 0.72, 0.70), rough=1.0)
    red = sc._principled("WallL", (0.65, 0.12, 0.10), rough=1.0)
    green = sc._principled("WallR", (0.12, 0.55, 0.15), rough=1.0)
    floor = sc._principled("Floor", (0.55, 0.53, 0.50), rough=0.9)
    sc._box("Floor", (0, 2.0, -0.05), (6.2, 6.2, 0.1), floor)
    sc._box("Back", (0, 5.05, 1.5), (6.2, 0.1, 3.2), grey)
    sc._box("Front", (0, -1.05, 1.5), (6.2, 0.1, 3.2), grey)
    sc._box("Left", (-3.05, 2.0, 1.5), (0.1, 6.2, 3.2), red)
    sc._box("Right", (3.05, 2.0, 1.5), (0.1, 6.2, 3.2), green)
    # Ceiling with a 0.8 m skylight hole at (-0.6, 3.0); room is y in [-1, 5].
    hx, hy, hs = -0.6, 3.0, 0.8
    sc._box("CeilL", ((-3.1 + hx - hs / 2) / 2, 2.0, 3.05), (hx - hs / 2 + 3.1, 6.2, 0.1), grey)
    sc._box("CeilR", ((3.1 + hx + hs / 2) / 2, 2.0, 3.05), (3.1 - hx - hs / 2, 6.2, 0.1), grey)
    sc._box("CeilF", (hx, (-1.1 + hy - hs / 2) / 2, 3.05), (hs, hy - hs / 2 + 1.1, 0.1), grey)
    sc._box("CeilB", (hx, (5.1 + hy + hs / 2) / 2, 3.05), (hs, 5.1 - hy - hs / 2, 0.1), grey)

    pend = [(-1.8, 1.6, 2.0, (1.0, 0.85, 0.65)), (-1.6, 3.9, 4.0, (1.0, 1.0, 1.0)),
            (0.4, 1.2, 8.0, (0.7, 0.85, 1.0)), (2.2, 4.2, 16.0, (1.0, 0.7, 0.5)),
            (-0.4, 4.7, 32.0, (1.0, 1.0, 0.9)), (1.7, 3.3, 64.0, (0.75, 0.9, 1.0))]
    for i, (x, y, s, c) in enumerate(pend):
        _emitter(sc, sl, bpy, f"Pendant{i}", (x, y, 2.3), 0.2, s, c)
    _emitter(sc, sl, bpy, "ClosedEmitter", (2.4, 2.4, 0.3), 0.3, 6.0, (1.0, 0.95, 0.85), sphere=True)
    sc._light("Point", "POINT", (2.3, 1.6, 2.0), (2.3, 1.6, 0.0), 40.0, shadow_soft_size=0.05)
    sc._light("Area", "AREA", (-2.2, 2.6, 2.95), (-2.2, 2.6, 0.0), 15.0,
              shape="SQUARE", size=0.6, spread=math.radians(45.0))
    sc._light("Sun", "SUN", (hx, hy, 6.0), (hx + 2.18, hy, 0.0), 1.5,
              color=(1.0, 0.95, 0.85), angle=math.radians(0.5))
    sc._camera((0.0, -0.95, 1.6), (0.0, 3.0, 0.7), lens=17.0)

    r = _Rois(scene)
    r.add("floor_under_pendant_dim", (-1.8, 1.6, 0.0), 0.04)
    r.add("floor_under_pendant_bright", (1.7, 3.3, 0.0), 0.04)
    r.add("floor_under_point", (2.3, 1.6, 0.0), 0.04)
    r.add("floor_under_area", (-2.2, 2.6, 0.0), 0.04)
    r.add("floor_sun_patch", (hx + 3.0 * math.tan(math.radians(20.0)), hy, 0.0), 0.04)
    r.add("back_wall", (0.0, 5.0, 1.5), 0.08)
    r.add("emitter_bright_face", (1.7, 3.3, 2.3), 0.015)
    r.add("emitter_dim_face", (-1.8, 1.6, 2.3), 0.015)
    r.add("closed_emitter_sphere", (2.4, 2.4, 0.3), 0.025)
    tags = ["light_tree", "mis_emitters", "dedicated_lamps", "spot_area_spread", "sun",
            "closed_emitter#886", "colour_bleed"]
    return scene, res, r, tags, []


def _rel_asset(name):
    return "//../assets/" + name


def _v2_media(bpy, sc, sl, addon_dir):
    """Fog box (sunk 0.1 m BELOW the floor, #926) + smoke VDB + fire (blackbody) + two
    mesh emitters inside the medium + a lamp behind. Gates #912/#913/#884/#922."""
    res = (320, 180)
    scene = _v2_setup(sc, res, bounces=8)
    scene.cycles.volume_bounces = 4
    sc._world((0.01, 0.012, 0.02), 1.0)
    sc._cyclorama("Ground", (0.12, 0.11, 0.1), rough=0.9, y_back=6.0, height=8.0)
    size = 2.4  # the committed v1 VDBs are 64^3 at voxel 2.4/64
    smoke = sl._principled_volume_material(bpy, "Smoke", density=10.0,
                                           color=(0.6, 0.62, 0.66), anisotropy=0.4)
    fire = sl._principled_volume_material(bpy, "Fire", density=3.0, color=(0.2, 0.19, 0.18),
                                          anisotropy=0.2, blackbody=3.0, temperature=3000.0)
    smoke_c, fire_c = (1.0, -1.6), (-2.2, -1.6)
    sl._volume_object(bpy, scene, "Smoke", _rel_asset("volumes_smoke_plume.vdb"),
                      (smoke_c[0] - size / 2, smoke_c[1] - size / 2, 0.0), smoke)
    sl._volume_object(bpy, scene, "Fire", _rel_asset("volumes_fire.vdb"),
                      (fire_c[0] - size / 2, fire_c[1] - size / 2, 0.0), fire)
    # Fog slab behind the plumes; bottom 0.1 m below the floor (no coincident faces).
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0.0, 3.8, 2.4))
    fog = bpy.context.active_object
    fog.name = "Fog"
    fog.scale = (12.0, 3.4, 5.0)
    fmat, nt, out = sl._bare_material(bpy, "FogMat")
    pv = nt.nodes.new("ShaderNodeVolumePrincipled")
    sl._sock(pv.inputs, "Density").default_value = 0.08
    sl._sock(pv.inputs, "Anisotropy").default_value = 0.5
    nt.links.new(pv.outputs[0], sl._sock(out.inputs, "Volume"))
    sc._assign(fog, fmat)
    # Two mesh emitters inside the fog.
    _emitter(sc, sl, bpy, "FogLampWarm", (-1.6, 3.3, 1.3), 0.15, 60.0, (1.0, 0.6, 0.3), sphere=True)
    _emitter(sc, sl, bpy, "FogLampCool", (2.6, 3.6, 2.0), 0.12, 60.0, (0.5, 0.7, 1.0), sphere=True)
    sc._light("Shaft", "SPOT", (2.5, 5.5, 7.5), (-0.5, 2.5, 0.0), 12000.0,
              color=(0.6, 0.75, 1.0), shadow_soft_size=0.05,
              spot_size=math.radians(22.0), spot_blend=0.3)
    sc._light("Rim", "AREA", (4.5, 1.0, 4.0), (0.8, 0.0, 1.2), 400.0,
              color=(0.8, 0.9, 1.0), size=1.5)
    sc._camera((0.0, -8.0, 1.5), (0.0, 0.0, 1.6), lens=30.0)

    r = _Rois(scene)
    r.add("fire_core", (fire_c[0], fire_c[1], 0.6), 0.05)
    r.add("smoke_plume", (smoke_c[0], smoke_c[1], 1.2), 0.05)
    r.add("shaft", (0.6, 3.7, 2.6), 0.05)
    r.add("fog_floor_lit", (-0.5, 2.5, 0.0), 0.05)
    r.add("emitter_warm_glow", (-1.6, 3.3, 1.3), 0.03)
    r.add("emitter_cool_glow", (2.6, 3.6, 2.0), 0.03)
    tags = ["heterogeneous_volume", "principled_volume_blackbody", "fog_box_sunk#926",
            "emitters_in_medium", "spot_shaft", "delta_ratio_tracking"]
    assets = ["volumes_smoke_plume.vdb", "volumes_fire.vdb"]
    return scene, res, r, tags, assets


def _v2_dispersion_caustics(bpy, sc, sl, addon_dir):
    """Showcase glass (SF11 prism + Sellmeier sphere) under the windowed sun AND a
    caustic spot (pkg287). Cycles has no dispersion: the Sellmeier node is Astroray-only."""
    res = (320, 180)
    scene = sc.build_glass()
    _v2_finish(scene, res)
    # Tight cone on the sphere only (half-angle ~5 deg at 4.6 m) so the floor outside the
    # sphere stays dark and the spot caustic (pkg287) is not buried under a direct pool.
    spot = sc._light("CausticSpot", "SPOT", (3.6, -3.2, 3.4), (1.4, -0.4, 0.5), 400.0,
                     color=(1.0, 0.97, 0.92), shadow_soft_size=0.03,
                     spot_size=math.radians(11.5), spot_blend=0.05)
    spot.data.cycles.is_caustics_light = True
    r = _Rois(scene)
    caustic = ("Documented divergence (owner 2026-09-29): Cycles has no dispersion and no "
               "sun/spot caustics through glass; Astroray adds them (caustic boost 1.0 after "
               "Batch AK). Phase 2 pins the Astroray-side expectation, this is not a failure.")
    r.add("prism_sun_caustic_floor", (1.9, -0.35, 0.0), 0.04, divergence=caustic)
    r.add("beam_through_prism", (-0.4, 0.3, 0.6), 0.04,
          divergence="Sellmeier SF11 (dispersive) vs Cycles constant-IOR Glass BSDF: colour fringes differ.")
    r.add("sphere_limb", (1.77, -0.26, 0.5), 0.02)
    r.add("sphere_spot_caustic_floor", (1.0, 0.1, 0.0), 0.04, divergence=caustic)
    r.add_rect("background_firefly", [0.65, 0.05, 0.85, 0.228])
    tags = ["dispersion_sellmeier", "sun_caustics", "spot_caustics#910", "glass_bsdf",
            "photon_firefly_bg"]
    return scene, res, r, tags, []


def _v2_sky_sun(bpy, sc, sl, addon_dir):
    """Showcase Nishita sky with a 4 deg sun, chrome ball, diffuse ground."""
    res = (320, 180)
    scene = sc.build_sky()
    _v2_finish(scene, res)
    sky = next(n for n in scene.world.node_tree.nodes if n.type == "TEX_SKY")
    sky.sun_size = math.radians(4.0)
    r = _Rois(scene)
    r.add("sun_disc", (0.0, 60.0, 4.2), 0.02)
    r.add("sun_glow", (0.0, 60.0, 9.0), 0.05)
    r.add("sky_upper", (0.0, 60.0, 17.0), 0.06)
    r.add_rect("ground_foreground", [0.25, 0.80, 0.75, 0.97])  # spans several shadow stripes
    # Pillar-base/chrome-rim ROI. Fixed rect = the old projected ROI (-1.0, 2.55, 0.7 +/- 0.02) minus
    # its last pixel row: the 1024 spp Cycles reference holds one caustic firefly there (row 136,
    # col 127: r 1.62 vs 0.08 neighbours) worth +6 % r / +3 % g of the 169-pixel mean (#1070).
    r.add_rect("chrome_reflection", [0.378, 0.6891, 0.418, 0.756])
    # Sky-lit stone face (a white-sphere ROI was dropped: sun -> chrome -> white is a
    # reflective caustic whose 64 spp Cycles scatter exceeded 70 %).
    r.add_rect("stone_sky_lit_face", [0.345, 0.52, 0.39, 0.80])
    tags = ["nishita_sky", "sun_disc_4deg", "sky_nee", "chrome_env_reflection", "diffuse_ground"]
    return scene, res, r, tags, []


def _v2_thin_film_metals(bpy, sc, sl, addon_dir):
    """Gold, copper, titanium films at three thicknesses, rough-glass thin film (#783)."""
    res = (320, 180)
    scene = _v2_setup(sc, res, bounces=16)
    sc._world((0.03, 0.03, 0.035), 1.0)
    sc._cyclorama("Sweep", (0.035, 0.035, 0.04), rough=0.3, y_back=3.0)
    ti, ti_edge = (0.55, 0.52, 0.5), (0.7, 0.68, 0.66)
    row = [("Gold", sc._metallic("Gold", (1.0, 0.78, 0.34), (1.0, 0.9, 0.6))),
           ("Copper", sc._metallic("Copper", (0.96, 0.55, 0.42), (1.0, 0.75, 0.6)))]
    for nm in (160.0, 260.0, 380.0):
        row.append((f"Ti{int(nm)}", sc._metallic(f"Ti{int(nm)}", ti, ti_edge, rough=0.12,
                                                  film_nm=nm, film_ior=2.4)))
    row.append(("RoughGlassFilm", sc._principled("RoughGlassFilm", (1, 1, 1), rough=0.25, IOR=1.5,
                                                 Transmission_Weight=1.0,
                                                 Thin_Film_Thickness=400.0, Thin_Film_IOR=1.5)))
    n = len(row)
    r = _Rois(scene)
    for i, (label, mat) in enumerate(row):
        x = (i - (n - 1) / 2) * 1.05
        sc._assign(sc._uv_sphere(label, (x, 0.0, 0.45), 0.45), mat)
        r.add(f"sphere_{label}", (x, 0.0, 0.45), 0.04)
    sc._light("Key", "AREA", (-3.0, -3.0, 4.5), (0.0, 0.5, 0.6), 900.0,
              color=(1.0, 0.97, 0.92), shape="RECTANGLE", size=3.0, size_y=1.5)
    sc._light("Strip", "AREA", (4.0, 1.5, 2.5), (0.0, 0.5, 0.8), 500.0,
              color=(0.85, 0.92, 1.0), shape="RECTANGLE", size=0.4, size_y=3.0)
    sc._light("Fill", "AREA", (1.0, -5.0, 1.0), (0.0, 0.5, 0.6), 120.0, size=3.0)
    sc._camera((0.0, -7.5, 1.7), (0.0, 0.6, 0.85), lens=40.0)
    tags = ["metallic_f82_conductor", "thin_film_metal", "thin_film_rough_glass#783",
            "area_light_soft"]
    return scene, res, r, tags, []


def _v2_textures_opvm(bpy, sc, sl, addon_dir):
    """Print table of proof cards: image + Noise/Voronoi/Wave/Checker (#881, #890),
    Mapping before and after a non-affine warp (#891), Metallic/Roughness programs
    incl. inside a Mix Shader (#889). Texture cards are Emission so each ROI reads
    the texel evaluation alone."""
    res = (480, 270)
    scene = _v2_setup(sc, res, bounces=8)
    sc._world((0.02, 0.02, 0.025), 1.0)
    N = sl._sock
    c1, c2 = (0.9, 0.85, 0.2, 1.0), (0.1, 0.15, 0.6, 1.0)

    def card_material(name, build):
        mat, nt, emit, out = sl._emission_card_material(bpy, name, 1.0)
        tc = nt.nodes.new("ShaderNodeTexCoord")
        nt.links.new(build(nt, tc), N(emit.inputs, "Color"))
        return mat

    def tex(nt, idname, tc, **props):
        node = nt.nodes.new(idname)
        for k, v in props.items():
            setattr(node, k, v)
        nt.links.new(N(tc.outputs, "UV"), N(node.inputs, "Vector"))
        return node

    def image_card(nt, tc):
        img = bpy.data.images.new("V2Stripes", 64, 64)
        img.pixels = sl._make_stripe_image_pixels(64, 64)
        img.pack()
        node = nt.nodes.new("ShaderNodeTexImage")
        node.image = img
        node.interpolation = "Closest"
        nt.links.new(N(tc.outputs, "UV"), N(node.inputs, "Vector"))
        return N(node.outputs, "Color")

    def noise_card(nt, tc):
        n = tex(nt, "ShaderNodeTexNoise", tc)
        N(n.inputs, "Scale").default_value = 6.0
        return N(n.outputs, "Color")

    def voronoi_card(nt, tc):
        n = tex(nt, "ShaderNodeTexVoronoi", tc)
        N(n.inputs, "Scale").default_value = 5.0
        return N(n.outputs, "Color")

    def wave_card(nt, tc):
        n = tex(nt, "ShaderNodeTexWave", tc)
        N(n.inputs, "Scale").default_value = 4.0
        N(n.inputs, "Distortion").default_value = 3.0
        return N(n.outputs, "Color")

    def checker_card(nt, tc):
        n = tex(nt, "ShaderNodeTexChecker", tc)
        N(n.inputs, "Scale").default_value = 6.0
        N(n.inputs, "Color1").default_value = c1
        N(n.inputs, "Color2").default_value = c2
        return N(n.outputs, "Color")

    def _map_checker(nt, vec_out):
        m = nt.nodes.new("ShaderNodeMapping")
        N(m.inputs, "Scale").default_value = (5.0, 3.0, 1.0)
        N(m.inputs, "Rotation").default_value = (0.0, 0.0, math.radians(20.0))
        nt.links.new(vec_out, N(m.inputs, "Vector"))
        c = nt.nodes.new("ShaderNodeTexChecker")
        N(c.inputs, "Scale").default_value = 1.0
        N(c.inputs, "Color1").default_value = c1
        N(c.inputs, "Color2").default_value = c2
        nt.links.new(N(m.outputs, "Vector"), N(c.inputs, "Vector"))
        return N(c.outputs, "Color")

    def mapping_before(nt, tc):
        return _map_checker(nt, N(tc.outputs, "UV"))

    def mapping_after_warp(nt, tc):
        # Noise-driven non-affine warp of the vector, THEN Mapping, THEN Checker.
        nz = tex(nt, "ShaderNodeTexNoise", tc)
        N(nz.inputs, "Scale").default_value = 3.0
        scl = nt.nodes.new("ShaderNodeVectorMath")
        scl.operation = "SCALE"
        N(scl.inputs, "Scale").default_value = 0.35
        nt.links.new(N(nz.outputs, "Color"), scl.inputs[0])
        add = nt.nodes.new("ShaderNodeVectorMath")
        add.operation = "ADD"
        nt.links.new(N(tc.outputs, "UV"), add.inputs[0])
        nt.links.new(N(scl.outputs, "Vector"), add.inputs[1])
        return _map_checker(nt, N(add.outputs, "Vector"))

    def voronoi_edge_card(nt, tc):
        n = tex(nt, "ShaderNodeTexVoronoi", tc, feature="DISTANCE_TO_EDGE")
        N(n.inputs, "Scale").default_value = 5.0
        ramp = nt.nodes.new("ShaderNodeValToRGB")
        nt.links.new(N(n.outputs, "Distance"), N(ramp.inputs, "Fac"))
        return N(ramp.outputs, "Color")

    cards = [("Image", image_card), ("Noise", noise_card), ("Voronoi", voronoi_card),
             ("Wave", wave_card), ("Checker", checker_card),
             ("MapBeforeWarp", mapping_before), ("MapAfterWarp", mapping_after_warp),
             ("VoronoiEdge", voronoi_edge_card)]
    r = _Rois(scene)
    for i, (name, fn) in enumerate(cards):
        col, row = i % 4, i // 4
        x, z = (col - 1.5) * 1.1, 3.0 - row * 1.1
        bpy.ops.mesh.primitive_plane_add(size=0.95, location=(x, 0.0, z))
        obj = bpy.context.active_object
        obj.name = "Card" + name
        obj.rotation_euler = (math.radians(90.0), 0.0, 0.0)
        sc._assign(obj, card_material(name + "Mat", fn))
        r.add("card_" + name, (x, 0.0, z), 0.045)

    # Row 3: spheres carrying Metallic / Roughness programs (Principled, lit).
    def prog_sphere(name, x, build):
        obj = sc._uv_sphere(name, (x, 0.0, 0.6), 0.45, seg=48, rings=24)
        mat, nt, out = sl._bare_material(bpy, name + "Mat")
        tc = nt.nodes.new("ShaderNodeTexCoord")
        nt.links.new(build(nt, tc), N(out.inputs, "Surface"))
        sc._assign(obj, mat)
        r.add("sphere_" + name, (x, 0.0, 0.6), 0.035)

    def principled(nt):
        p = nt.nodes.new("ShaderNodeBsdfPrincipled")
        N(p.inputs, "Base Color").default_value = (0.9, 0.55, 0.3, 1.0)
        return p

    def metallic_prog(nt, tc):
        p = principled(nt)
        n = tex(nt, "ShaderNodeTexChecker", tc)
        N(n.inputs, "Scale").default_value = 6.0
        N(p.inputs, "Roughness").default_value = 0.25
        nt.links.new(N(n.outputs, "Fac"), N(p.inputs, "Metallic"))
        return N(p.outputs, "BSDF")

    def roughness_prog(nt, tc):
        p = principled(nt)
        N(p.inputs, "Metallic").default_value = 1.0
        n = tex(nt, "ShaderNodeTexNoise", tc)
        N(n.inputs, "Scale").default_value = 5.0
        nt.links.new(N(n.outputs, "Fac"), N(p.inputs, "Roughness"))
        return N(p.outputs, "BSDF")

    def mix_prog(nt, tc):
        a, b = principled(nt), principled(nt)
        N(a.inputs, "Metallic").default_value = 1.0
        N(a.inputs, "Roughness").default_value = 0.15
        N(b.inputs, "Metallic").default_value = 0.0
        N(b.inputs, "Roughness").default_value = 0.7
        n = tex(nt, "ShaderNodeTexVoronoi", tc)
        N(n.inputs, "Scale").default_value = 4.0
        mix = nt.nodes.new("ShaderNodeMixShader")
        nt.links.new(N(n.outputs, "Distance"), mix.inputs[0])
        nt.links.new(N(a.outputs, "BSDF"), mix.inputs[1])
        nt.links.new(N(b.outputs, "BSDF"), mix.inputs[2])
        return N(mix.outputs, "Shader")

    def plain(nt, tc):
        p = principled(nt)
        N(p.inputs, "Metallic").default_value = 0.5
        N(p.inputs, "Roughness").default_value = 0.35
        return N(p.outputs, "BSDF")

    for i, (name, fn) in enumerate((("MetallicProg", metallic_prog), ("RoughnessProg", roughness_prog),
                                    ("MixShaderProg", mix_prog), ("PlainRef", plain))):
        prog_sphere(name, (i - 1.5) * 1.1, fn)
    sc._light("Key", "AREA", (-2.5, -4.0, 4.5), (0.0, 0.0, 1.0), 450.0, size=3.0)
    sc._light("Fill", "AREA", (3.0, -4.0, 1.5), (0.0, 0.0, 1.0), 200.0, size=3.0)
    sc._camera((0.0, -6.2, 1.8), (0.0, 0.0, 1.8), lens=30.0)
    tags = ["tex_image", "tex_noise#881", "tex_voronoi#881", "tex_wave#890", "tex_checker",
            "mapping_pre_warp", "mapping_post_warp#891", "principled_metallic_program#889",
            "principled_roughness_program#889", "mix_shader_program#889"]
    return scene, res, r, tags, []


def _v2_camera_geometry(bpy, sc, sl, addon_dir):
    """Perspective camera with clip markers (+ an ortho camera object), collection
    instancing incl. a negative-scale copy, hair tuft (#853), a motion-blur vane,
    and a mesh volume (#833). ROIs per specimen."""
    import random
    res = (480, 270)
    scene = _v2_setup(sc, res, bounces=8)
    sc._world((0.03, 0.03, 0.035), 1.0)
    N = sl._sock
    bpy.ops.mesh.primitive_plane_add(size=1.0, location=(0.0, 4.0, 0.0))
    floor = bpy.context.active_object
    floor.name = "Floor"
    floor.scale = (30.0, 40.0, 1.0)
    sc._assign(floor, sc._principled("FloorMat", (0.3, 0.29, 0.27), rough=1.0))
    sc._light("Key", "AREA", (-3.0, -3.5, 5.0), (0.0, 0.0, 0.5), 200.0, size=3.5)
    sc._light("Fill", "AREA", (5.0, -3.0, 3.5), (0.0, 0.0, 0.5), 80.0, size=4.0)
    r = _Rois(scene)

    # --- instancing (positive + negative-scale) ---
    proto_coll = bpy.data.collections.new("RockProto")
    bpy.ops.mesh.primitive_ico_sphere_add(radius=0.22, subdivisions=2, location=(0, 0, 0))
    proto = bpy.context.active_object
    proto.name = "RockPrototype"
    for c in list(proto.users_collection):
        c.objects.unlink(proto)
    proto_coll.objects.link(proto)
    rng = random.Random(2026)
    for v in proto.data.vertices:
        v.co.x += rng.uniform(-0.03, 0.03)
        v.co.y += rng.uniform(-0.03, 0.03)
        v.co.z += rng.uniform(-0.02, 0.05)
    sc._assign(proto, sc._principled("RockMat", (0.42, 0.40, 0.37), rough=0.9))
    for i in range(5):
        t = i / 4.0
        e = bpy.data.objects.new(f"RockInst{i}", None)
        e.instance_type = "COLLECTION"
        e.instance_collection = proto_coll
        e.location = (-2.7 + t * 1.1, 0.1 * math.sin(t * math.pi), 0.22)
        e.rotation_euler = (0.0, 0.0, t * 2.4)
        s = 0.8 + 0.5 * (1.0 - abs(t - 0.5) * 2.0)
        e.scale = (-s, s, s) if i == 4 else (s, s, s)
        scene.collection.objects.link(e)
    r.add("instances", (-2.15, 0.0, 0.25), 0.05)

    # --- hair tuft ---
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.30, location=(-0.8, 0.0, 0.3), segments=32, ring_count=16)
    scalp = bpy.context.active_object
    scalp.name = "Scalp"
    sc._smooth(scalp)
    sc._assign(scalp, sc._principled("ScalpMat", (0.58, 0.46, 0.38), rough=0.6))
    hcurves = sl._build_hair_curves(bpy, scalp, 0.30, 400, 6, seed=77)
    for d in hcurves.attributes["radius"].data:
        d.value = 0.006  # thick enough to resolve at 480 px (builder default 0.0015)
    hair = bpy.data.objects.new("Hair", hcurves)
    scene.collection.objects.link(hair)
    hmat, nt, out = sl._bare_material(bpy, "HairMat")
    hb = nt.nodes.new("ShaderNodeBsdfHairPrincipled")
    N(hb.inputs, "Color").default_value = (0.15, 0.09, 0.05, 1.0)
    N(hb.inputs, "Roughness").default_value = 0.3
    nt.links.new(N(hb.outputs, "BSDF"), N(out.inputs, "Surface"))
    hair.data.materials.append(hmat)
    r.add("hair_tuft", (-0.8, 0.0, 0.45), 0.05)

    # --- motion-blur vane (rotating, blurred) ---
    scene.render.use_motion_blur = True
    scene.render.motion_blur_shutter = 0.6
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0.4, 0.0, 0.55))
    vane = bpy.context.active_object
    vane.name = "VaneBlur"
    vane.scale = (0.05, 0.55, 0.55)
    vane.cycles.use_motion_blur = True
    vane.rotation_euler = (0.0, 0.0, math.radians(-25.0))
    vane.keyframe_insert(data_path="rotation_euler", index=2, frame=0)
    vane.rotation_euler = (0.0, 0.0, math.radians(25.0))
    vane.keyframe_insert(data_path="rotation_euler", index=2, frame=2)
    sc._assign(vane, sc._principled("VaneMat", (0.75, 0.15, 0.12), rough=0.4))
    scene.frame_set(1)
    r.add("motion_vane", (0.4, 0.0, 0.55), 0.05)

    # --- mesh volume, backlit ---
    bpy.ops.mesh.primitive_plane_add(size=1.0, location=(1.7, 1.1, 0.9))
    back = bpy.context.active_object
    back.name = "VolBackdrop"
    back.rotation_euler = (math.radians(90.0), 0.0, 0.0)
    back.scale = (1.4, 1.0, 1.1)
    sc._assign(back, sc._principled("VolBackMat", (0.85, 0.82, 0.72), rough=1.0))
    sc._light("VolBack", "AREA", (1.7, 1.7, 0.9), (1.7, 0.0, 0.9), 250.0, size=1.4)
    bpy.ops.mesh.primitive_cube_add(size=0.7, location=(1.7, 0.35, 0.5))
    vc = bpy.context.active_object
    vc.name = "VolCube"
    vm, nt, out = sl._bare_material(bpy, "VolCubeMat")
    pv = nt.nodes.new("ShaderNodeVolumePrincipled")
    N(pv.inputs, "Color").default_value = (0.55, 0.70, 0.95, 1.0)
    N(pv.inputs, "Density").default_value = 3.0
    N(pv.inputs, "Anisotropy").default_value = 0.35
    nt.links.new(N(pv.outputs, "Volume"), N(out.inputs, "Volume"))
    sc._assign(vc, vm)
    r.add("mesh_volume", (1.7, 0.0, 0.5), 0.045)

    # --- clip markers: posts straddling clip_start / clip_end ---
    # clip_start = 1.0, clip_end = 15.0; camera at y = -5.2. The near post (0.55 m ahead,
    # 3 m tall) would fill the frame centre if clip_start were ignored; the far post
    # (16.5 m) would show above the clipped floor if clip_end were ignored.
    posts = {"near_clipped": (0.0, -4.65, 1.5, 3.0), "far_visible": (-2.6, 5.0, 0.75, 1.5),
             "far_clipped": (-0.9, 11.0, 0.75, 1.5)}
    pmat = sc._principled("PostMat", (0.85, 0.3, 0.1), rough=0.5)
    for name, (x, y, zc, h) in posts.items():
        sc._box("Post_" + name, (x, y, zc), (0.25, 0.25, h), pmat)
    cam = sc._camera((0.0, -5.2, 1.3), (0.0, 0.0, 0.6), lens=30.0)
    cam.data.clip_start = 1.0
    cam.data.clip_end = 15.0
    r.add("post_far_visible", (-2.6, 5.0, 0.75), 0.012)
    r.add("post_far_clipped_region", (-0.9, 11.0, 0.75), 0.012)
    r.add_rect("near_clip_column", [0.47, 0.04, 0.53, 0.145])
    # Ortho camera (named; the perspective camera stays active).
    oc = bpy.data.cameras.new("CamOrtho")
    oc.type = "ORTHO"
    oc.ortho_scale = 6.0
    oc.clip_start, oc.clip_end = 1.0, 15.0
    oo = bpy.data.objects.new("CamOrtho", oc)
    scene.collection.objects.link(oo)
    oo.location = (0.0, -5.2, 1.3)
    sl._look_at(oo, (0.0, 0.0, 0.6))
    scene.camera = cam
    tags = ["camera_clip_perspective#873", "camera_ortho_object", "collection_instancing",
            "negative_scale_instance", "hair_curves#853", "motion_blur", "mesh_volume#833"]
    return scene, res, r, tags, []


def _v2_viewport(bpy, sc, sl, addon_dir):
    """metal_sweep sphere + a ~100k-triangle grid, two named cameras (pkg291 gate (a)
    driver loads this file). No render gate; manifest only."""
    import importlib.util
    import bmesh
    res = (640, 360)
    spec = importlib.util.spec_from_file_location(
        "metal_ab_scenes", REPO_ROOT / "benchmarks" / "cycles-parity" / "metal_ab" / "scenes.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["metal_ab_scenes"] = mod  # @dataclass resolves cls.__module__ here
    spec.loader.exec_module(mod)
    scene = mod.build_metal_scene(bpy, mod.metal_sweep()[0])
    _v2_finish(scene, res)
    n = 224  # 224 x 224 quads -> 100,352 triangles
    me = bpy.data.meshes.new("Grid100k")
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=n, y_segments=n, size=4.0)
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    bm.to_mesh(me)
    bm.free()
    grid = bpy.data.objects.new("Grid100k", me)
    scene.collection.objects.link(grid)
    grid.location = (0.0, 0.0, -1.0)
    grid.data.materials.append(sc._principled("GridMat", (0.5, 0.5, 0.5), rough=0.6))
    for nm, loc, tgt in (("CamHero", (0.0, -4.0, 1.0), (0.0, 0.0, -0.2)),
                         ("CamGrid", (0.0, -6.5, 3.5), (0.0, 0.0, -1.0))):
        cam = sl._add_pinned_camera(bpy, scene, loc, tgt, lens=35.0)
        cam.name = nm
        cam.data.name = nm
    scene.camera = bpy.data.objects["CamHero"]
    tags = ["viewport_metal_sweep", "viewport_100k_tris", "two_named_cameras"]
    return scene, res, _Rois(scene), tags, []


# --------------------------------------------------------------------------- #
# pkg296 (#833) -- volumes_mesh family: mesh-bounded volumes. Every scene is
# lit by emissive meshes only (a backdrop behind the media + a softbox on the
# camera-left), no lamp objects and no diffuse surfaces, so the Cycles/Astroray
# comparison isolates the medium boundary. 256x256, gated per ROI by
# tests/test_pkg296_mesh_volume_boundary.py at volume_bounces 0 and 4.
# --------------------------------------------------------------------------- #
VM_RES = (256, 256)


def _vm_setup(bpy, sc, sl, ortho_scale=None, cam=(0.0, -6.0, 0.0), target=(0.0, 0.0, 0.0),
              lens=50.0, backdrop_y=3.0, softbox=True):
    scene = _v2_setup(sc, VM_RES, bounces=12)
    scene.cycles.volume_bounces = 4
    sc._world((0.0, 0.0, 0.0), 1.0)
    bpy.ops.mesh.primitive_plane_add(size=1.0, location=(0.0, backdrop_y, 0.0))
    back = bpy.context.active_object
    back.name = "Backdrop"
    back.rotation_euler = (math.radians(90.0), 0.0, 0.0)
    back.scale = (12.0, 12.0, 1.0)
    bm, _nt, _e, _o = sl._emission_card_material(bpy, "BackdropMat", 1.0)
    sc._assign(back, bm)
    if softbox:
        bpy.ops.mesh.primitive_plane_add(size=1.0, location=(-3.0, -2.5, 2.5))
        box = bpy.context.active_object
        box.name = "Softbox"
        box.scale = (1.5, 1.5, 1.0)
        import mathutils
        aim = mathutils.Vector((0.0, 0.0, 0.0)) - box.location
        box.rotation_euler = aim.to_track_quat("Z", "Y").to_euler()  # +Z normal faces the media
        bxm, _nt, _e, _o = sl._emission_card_material(bpy, "SoftboxMat", 6.0)
        sc._assign(box, bxm)
    c = sc._camera(cam, target, lens=lens)
    if ortho_scale is not None:
        c.data.type = "ORTHO"
        c.data.ortho_scale = ortho_scale
    return scene


def _vm_volume(bpy, sl, obj, name, density, color, anisotropy=0.0, surface=None):
    mat = sl._principled_volume_material(bpy, name, density=density, color=color,
                                         anisotropy=anisotropy)
    if surface is not None:  # surface + volume on one Material Output (glass shell)
        nt = mat.node_tree
        out = next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL")
        nt.links.new(surface(nt).outputs[0], sl._sock(out.inputs, "Surface"))
    obj.data.materials.clear()
    obj.data.materials.append(mat)
    return obj


def _vm_ico(bpy, name, loc, r, subdiv=3):
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=subdiv, radius=r, location=loc)
    obj = bpy.context.active_object
    obj.name = name
    return obj


def _vm_icosphere(bpy, sc, sl, addon_dir, empty=False):
    """Absorbing+scattering icosphere (subdiv 3) under an ORTHO camera over the
    emissive backdrop. The AABB-minus-sphere corners (aabb_corner*) are the #833
    regression: backdrop there, not the medium."""
    scene = _vm_setup(bpy, sc, sl, ortho_scale=2.6)
    if not empty:
        _vm_volume(bpy, sl, _vm_ico(bpy, "Ico", (0.0, 0.0, 0.0), 1.0), "IcoVol",
                   1.5, (0.9, 0.6, 0.3))
    r = _Rois(scene)
    r.add("centre", (0.0, 0.0, 0.0), 0.05)
    r.add("limb", (0.72, 0.0, 0.0), 0.03)
    r.add("aabb_corner", (0.9, 0.0, 0.9), 0.025)
    r.add("aabb_corner_ll", (-0.9, 0.0, -0.9), 0.025)
    return scene, VM_RES, r, ["mesh_volume#833", "ortho"], []


def _vm_icosphere_empty(bpy, sc, sl, addon_dir):
    """The icosphere scene without the medium (silhouette-mask baseline)."""
    return _vm_icosphere(bpy, sc, sl, addon_dir, empty=True)


def _vm_suzanne(bpy, sc, sl, addon_dir):
    """Suzanne (non-manifold: the eye sockets are holes) as a scattering volume.
    ROIs stay off the eyes (research note: open-mesh divergence)."""
    scene = _vm_setup(bpy, sc, sl, cam=(0.0, -6.0, 0.0), lens=45.0)
    bpy.ops.mesh.primitive_monkey_add(size=2.0, location=(0.0, 0.0, 0.0))
    mk = bpy.context.active_object
    mk.name = "Suzanne"
    _vm_volume(bpy, sl, mk, "SuzanneVol", 2.0, (0.5, 0.8, 0.9))
    r = _Rois(scene)
    r.add("forehead", (0.0, 0.0, 0.62), 0.03)
    r.add("cheek", (0.3, 0.0, -0.2), 0.03)
    r.add("ear", (-1.15, 0.0, 0.25), 0.025)
    r.add("aabb_corner", (1.2, 0.0, -0.8), 0.025)
    return scene, VM_RES, r, ["mesh_volume#833", "open_mesh"], []


def _vm_nested(bpy, sc, sl, addon_dir):
    """A dense absorbing icosphere nested inside a thin scattering sphere
    (stack sum = overlap composite)."""
    scene = _vm_setup(bpy, sc, sl, lens=50.0)
    _vm_volume(bpy, sl, _vm_ico(bpy, "Outer", (0.0, 0.0, 0.0), 1.1), "OuterVol",
               0.6, (0.3, 0.5, 0.9))
    _vm_volume(bpy, sl, _vm_ico(bpy, "Inner", (0.0, 0.0, 0.0), 0.5), "InnerVol",
               4.0, (0.9, 0.4, 0.1))
    r = _Rois(scene)
    r.add("centre", (0.0, -1.0, 0.0), 0.03)
    r.add("shell", (0.85, -0.3, 0.0), 0.025)
    r.add("aabb_corner", (0.95, -1.0, 0.95), 0.02)
    return scene, VM_RES, r, ["mesh_volume#833", "nested_volumes"], []


def _vm_overlap(bpy, sc, sl, addon_dir):
    """Two overlapping icosphere media of different colour (coefficients add)."""
    scene = _vm_setup(bpy, sc, sl, lens=50.0)
    _vm_volume(bpy, sl, _vm_ico(bpy, "Left", (-0.45, 0.0, 0.0), 0.8), "LeftVol",
               1.5, (0.9, 0.3, 0.2))
    _vm_volume(bpy, sl, _vm_ico(bpy, "Right", (0.45, 0.0, 0.0), 0.8), "RightVol",
               1.5, (0.2, 0.4, 0.9))
    r = _Rois(scene)
    r.add("left", (-0.9, -0.8, 0.0), 0.025)
    r.add("overlap", (0.0, -0.8, 0.0), 0.025)
    r.add("right", (0.9, -0.8, 0.0), 0.025)
    r.add("overlap_top", (0.0, -0.5, 0.45), 0.02)
    return scene, VM_RES, r, ["mesh_volume#833", "overlapping_volumes"], []


def _vm_camera_inside(bpy, sc, sl, addon_dir):
    """The camera starts inside a thin fog sphere (Cycles volume-stack init);
    the backdrop lies outside it, so corner rays leave the sphere early."""
    scene = _vm_setup(bpy, sc, sl, cam=(0.0, -1.0, 0.0), target=(0.0, 3.0, 0.0),
                      lens=18.0, backdrop_y=5.0)
    _vm_volume(bpy, sl, _vm_ico(bpy, "Fog", (0.0, 0.0, 0.0), 3.0, subdiv=4), "FogVol",
               0.35, (0.85, 0.85, 0.85))
    r = _Rois(scene)
    r.add("centre", (0.0, 5.0, 0.0), 0.04)
    r.add("mid", (2.5, 5.0, 2.5), 0.03)
    r.add("corner", (4.5, 5.0, 4.5), 0.03)
    return scene, VM_RES, r, ["mesh_volume#833", "camera_inside_volume"], []


def _vm_glass_shell(bpy, sc, sl, addon_dir):
    """A smooth glass sphere whose material also carries a Principled Volume:
    the surface and the medium boundary coincide (spawn-offset case)."""
    scene = _vm_setup(bpy, sc, sl, lens=50.0)
    sph = sc._uv_sphere("Shell", (0.0, 0.0, 0.0), 1.0, seg=64, rings=32)

    def glass(nt):
        g = nt.nodes.new("ShaderNodeBsdfGlass")
        sl._sock(g.inputs, "IOR").default_value = 1.45
        sl._sock(g.inputs, "Roughness").default_value = 0.0
        return g
    _vm_volume(bpy, sl, sph, "ShellVol", 1.5, (0.9, 0.5, 0.2), surface=glass)
    r = _Rois(scene)
    r.add("centre", (0.0, -1.0, 0.0), 0.03)
    r.add("rim", (0.8, -0.5, 0.0), 0.02)
    r.add("outside", (1.4, 0.0, 1.0), 0.03)
    return scene, VM_RES, r, ["mesh_volume#833", "glass_shell_volume"], []


VM_BUILDERS = {
    "vm_icosphere": _vm_icosphere,
    "vm_icosphere_empty": _vm_icosphere_empty,
    "vm_suzanne": _vm_suzanne,
    "vm_nested": _vm_nested,
    "vm_overlap": _vm_overlap,
    "vm_camera_inside": _vm_camera_inside,
    "vm_glass_shell": _vm_glass_shell,
}


# --------------------------------------------------------------------------- #
# pkg310 -- production node-tree corpus (eight prod_* materials). Same harness as
# v2: ``--families prod_car_paint ... --out-dir benchmarks/reference_corpus/production``
# (one Blender process per scene). Each is ONE object (or a small set) on a neutral
# stage lit by sun + area lamp + the CC0 Poly Haven HDRI. Textures are procedural
# (images generated here from numpy, packed into the .blend: no third-party data).
# --------------------------------------------------------------------------- #
PROD_DIR = REPO_ROOT / "benchmarks" / "reference_corpus" / "production"
PROD_RES = (320, 240)
PROD_SPHERE_C, PROD_SPHERE_R = (0.0, 0.0, 0.9), 0.9
PROD_SUN_DIR = (0.55, -0.35, 0.75)  # direction TO the sun
PROD_HDRI = "syferfontein_18d_clear_1k.hdr"


def _pn(nt, idname, **props):
    """New shader node with RNA props set (props first so enum-dependent sockets exist)."""
    node = nt.nodes.new(idname)
    for k, v in props.items():
        setattr(node, k, v)
    return node


def _psock(coll, name):
    for s in coll:
        if getattr(s, "identifier", None) == name or s.name == name:
            return s
    raise KeyError(f"{name!r} not in {[s.identifier for s in coll]}")


def _pset(node, name, value):
    _psock(node.inputs, name).default_value = value


def _pl(nt, out_node, out_name, in_node, in_name):
    """Link ``out_node.outputs[out_name] -> in_node.inputs[in_name]`` (identifier-or-name);
    an int ``in_name`` indexes the inputs (Math / Mix Shader positional sockets)."""
    dst = in_node.inputs[in_name] if isinstance(in_name, int) else _psock(in_node.inputs, in_name)
    nt.links.new(_psock(out_node.outputs, out_name), dst)


def _pmix(nt, a, b, fac, blend="MIX"):
    """RGBA Mix node (Blender 4+/5 ``ShaderNodeMix``); a/b RGBA, fac float defaults."""
    m = _pn(nt, "ShaderNodeMix", data_type="RGBA", blend_type=blend)
    _pset(m, "A_Color", a)
    _pset(m, "B_Color", b)
    _pset(m, "Factor_Float", fac)
    return m


def _pmath(nt, op, a=None, b=None, clamp=False):
    m = _pn(nt, "ShaderNodeMath", operation=op, use_clamp=clamp)
    if a is not None:
        m.inputs[0].default_value = a
    if b is not None:
        m.inputs[1].default_value = b
    return m


def _pramp(nt, stops):
    """Color Ramp with ``stops`` = [(pos, rgba), ...]."""
    r = _pn(nt, "ShaderNodeValToRGB")
    els = r.color_ramp.elements
    while len(els) < len(stops):
        els.new(0.5)
    for el, (pos, col) in zip(els, stops):
        el.position, el.color = pos, col
    return r


def _prod_image(bpy, name, arr, is_data):
    """Pack a HxWx3 float array (row 0 = bottom, Blender convention) as a generated image."""
    import numpy as np
    h, w = arr.shape[:2]
    rgba = np.ones((h, w, 4), dtype=np.float32)
    rgba[:, :, :arr.shape[2]] = arr
    img = bpy.data.images.new(name, w, h, alpha=False, float_buffer=False, is_data=is_data)
    img.colorspace_settings.name = "Non-Color" if is_data else "sRGB"
    img.pixels.foreach_set(rgba.ravel())
    img.pack()
    return img


def _prod_sphere_pt(dx, dz):
    """World point on the camera-facing side of the stage sphere, direction (dx, -1, dz)."""
    d = math.sqrt(dx * dx + 1.0 + dz * dz)
    return tuple(PROD_SPHERE_C[i] + PROD_SPHERE_R * v / d for i, v in enumerate((dx, -1.0, dz)))


def _prod_stage(bpy, sc, sl, res=PROD_RES, floor=True, cam=((0.0, -4.6, 1.5), (0.0, 0.0, 0.85), 45.0),
                hdri_strength=0.3, sun_strength=1.1, area_power=60.0):
    """Neutral stage: HDRI world + sun + area lamp + diffuse floor + camera. Returns scene."""
    scene = _v2_setup(sc, res, bounces=8)
    world = sc._world((0.03, 0.03, 0.03), 1.0)
    wnt = world.node_tree
    img = bpy.data.images.load(str(V2_ASSETS / PROD_HDRI))
    env = _pn(wnt, "ShaderNodeTexEnvironment")
    env.image = img
    bg = next(n for n in wnt.nodes if n.type == "BACKGROUND")
    _pset(bg, "Strength", hdri_strength)
    wnt.links.new(env.outputs["Color"], bg.inputs["Color"])
    sc._light("Sun", "SUN", tuple(6.0 * v for v in PROD_SUN_DIR), (0.0, 0.0, 0.0), sun_strength,
              color=(1.0, 0.96, 0.9), angle=math.radians(0.6))
    sc._light("Area", "AREA", (-3.2, -3.0, 3.2), (0.0, 0.0, 0.9), area_power, size=2.0)
    if floor:
        fl = sc._principled("StageFloor", (0.30, 0.30, 0.29), rough=0.85)
        bpy.ops.mesh.primitive_plane_add(size=40.0, location=(0.0, 0.0, 0.0))
        floor_obj = bpy.context.active_object
        floor_obj.name = "StageFloor"
        sc._assign(floor_obj, fl)
    sc._camera(cam[0], cam[1], lens=cam[2])
    return scene


def _prod_object_sphere(bpy, sc, mat, name="Hero"):
    obj = sc._uv_sphere(name, PROD_SPHERE_C, PROD_SPHERE_R, seg=96, rings=48)
    sc._assign(obj, mat)
    return obj


def _prod_principled(nt, out, **inputs):
    p = _pn(nt, "ShaderNodeBsdfPrincipled")
    for k, v in inputs.items():
        _pset(p, k.replace("_", " "), v)
    nt.links.new(p.outputs["BSDF"], out.inputs["Surface"])
    return p


def _prod_rois(scene, points, hw=0.03):
    r = _Rois(scene)
    for name, (dx, dz) in points.items():
        r.add(name, _prod_sphere_pt(dx, dz), hw)
    return r


def _prod_car_paint(bpy, sc, sl, addon_dir):
    """Principled + coat; Voronoi flake normal (Bump); Layer Weight Facing mixes base and
    flake tint; Fresnel drives Metallic."""
    scene = _prod_stage(bpy, sc, sl)
    mat, nt, out = sl._bare_material(bpy, "CarPaint")
    tc = _pn(nt, "ShaderNodeTexCoord")
    voro = _pn(nt, "ShaderNodeTexVoronoi", feature="F1")
    _pset(voro, "Scale", 90.0)
    _pset(voro, "Randomness", 1.0)
    _pl(nt, tc, "Object", voro, "Vector")
    bump = _pn(nt, "ShaderNodeBump")
    _pset(bump, "Strength", 0.35)
    _pset(bump, "Distance", 0.02)
    _pl(nt, voro, "Distance", bump, "Height")
    lw = _pn(nt, "ShaderNodeLayerWeight")
    _pset(lw, "Blend", 0.35)
    mix = _pmix(nt, (0.55, 0.04, 0.03, 1.0), (0.95, 0.62, 0.2, 1.0), 0.5)
    _pl(nt, lw, "Facing", mix, "Factor_Float")
    fr = _pn(nt, "ShaderNodeFresnel")
    _pset(fr, "IOR", 1.8)
    scale = _pmath(nt, "MULTIPLY", None, 0.6)
    _pl(nt, fr, "Fac", scale, 0)
    p = _prod_principled(nt, out, Roughness=0.32, Coat_Weight=1.0, Coat_Roughness=0.03, Coat_IOR=1.5)
    _pl(nt, mix, "Result_Color", p, "Base Color")
    _pl(nt, scale, "Value", p, "Metallic")
    _pl(nt, bump, "Normal", p, "Normal")
    _prod_object_sphere(bpy, sc, mat)
    r = _prod_rois(scene, {"lit_front": (-0.15, 0.25), "limb_grazing": (0.62, 0.05),
                           "lower_shadowed": (0.1, -0.55), "upper_flake": (-0.4, 0.55)})
    return scene, PROD_RES, r, ["principled_coat", "voronoi_bump_flakes", "layer_weight_facing",
                                "fresnel_node", "mix_rgba"], []


def _prod_wood(bpy, sc, sl, addon_dir):
    """Wave rings + Noise -> Color Ramp -> base colour and roughness; the same scalar chain
    -> Bump. Object coordinates + Mapping."""
    scene = _prod_stage(bpy, sc, sl)
    mat, nt, out = sl._bare_material(bpy, "Wood")
    tc = _pn(nt, "ShaderNodeTexCoord")
    mp = _pn(nt, "ShaderNodeMapping")
    _pset(mp, "Scale", (1.0, 1.0, 3.0))
    _pset(mp, "Rotation", (0.0, math.radians(90.0), 0.0))
    _pl(nt, tc, "Object", mp, "Vector")
    noise = _pn(nt, "ShaderNodeTexNoise")
    _pset(noise, "Scale", 3.5)
    _pset(noise, "Detail", 4.0)
    _pset(noise, "Roughness", 0.55)
    _pl(nt, mp, "Vector", noise, "Vector")
    wave = _pn(nt, "ShaderNodeTexWave", wave_type="RINGS", rings_direction="X", wave_profile="SIN")
    _pset(wave, "Scale", 4.5)
    _pset(wave, "Distortion", 5.0)
    _pset(wave, "Detail", 2.0)
    _pl(nt, mp, "Vector", wave, "Vector")
    noise_w = _pmath(nt, "MULTIPLY", None, 0.65)
    _pl(nt, noise, "Fac", noise_w, 0)
    blend = _pmath(nt, "MULTIPLY_ADD", None, 0.35)  # wave*0.35 + noise*0.65
    _pl(nt, wave, "Fac", blend, 0)
    _pl(nt, noise_w, "Value", blend, 2)
    ramp = _pramp(nt, [(0.25, (0.20, 0.09, 0.03, 1.0)), (0.55, (0.45, 0.24, 0.09, 1.0)),
                       (0.85, (0.70, 0.45, 0.22, 1.0))])
    _pl(nt, blend, "Value", ramp, "Fac")
    rough = _pmath(nt, "MULTIPLY_ADD", None, 0.5)
    rough.inputs[2].default_value = 0.35
    _pl(nt, blend, "Value", rough, 0)
    bump = _pn(nt, "ShaderNodeBump")
    _pset(bump, "Strength", 0.5)
    _pset(bump, "Distance", 0.03)
    _pl(nt, blend, "Value", bump, "Height")
    p = _prod_principled(nt, out, Specular_IOR_Level=0.4)
    _pl(nt, ramp, "Color", p, "Base Color")
    _pl(nt, rough, "Value", p, "Roughness")
    _pl(nt, bump, "Normal", p, "Normal")
    _prod_object_sphere(bpy, sc, mat)
    r = _prod_rois(scene, {"grain_center": (0.0, 0.1), "grain_left": (-0.55, 0.2),
                           "grain_right": (0.5, -0.15), "lower": (-0.1, -0.5)})
    return scene, PROD_RES, r, ["wave_rings_distortion", "noise", "color_ramp_multi", "math_chain",
                                "bump_from_chain", "mapping_rotation", "object_coords"], []


def _prod_marble(bpy, sc, sl, addon_dir):
    """Noise -> Vector Math warp -> Mapping (after the warp) -> Wave bands -> Color Ramp veins."""
    scene = _prod_stage(bpy, sc, sl)
    mat, nt, out = sl._bare_material(bpy, "Marble")
    tc = _pn(nt, "ShaderNodeTexCoord")
    noise = _pn(nt, "ShaderNodeTexNoise")
    _pset(noise, "Scale", 2.5)
    _pset(noise, "Detail", 5.0)
    _pset(noise, "Roughness", 0.6)
    _pl(nt, tc, "Object", noise, "Vector")
    scl = _pn(nt, "ShaderNodeVectorMath", operation="SCALE")
    _pset(scl, "Scale", 0.7)
    _pl(nt, noise, "Color", scl, 0)
    add = _pn(nt, "ShaderNodeVectorMath", operation="ADD")
    _pl(nt, tc, "Object", add, 0)
    _pl(nt, scl, "Vector", add, 1)
    mp = _pn(nt, "ShaderNodeMapping")
    _pset(mp, "Scale", (2.0, 2.0, 2.0))
    _pset(mp, "Rotation", (0.0, 0.0, math.radians(35.0)))
    _pl(nt, add, "Vector", mp, "Vector")
    wave = _pn(nt, "ShaderNodeTexWave", wave_type="BANDS", bands_direction="Y", wave_profile="SAW")
    _pset(wave, "Scale", 2.2)
    _pset(wave, "Distortion", 6.0)
    _pset(wave, "Detail", 3.0)
    _pl(nt, mp, "Vector", wave, "Vector")
    ramp = _pramp(nt, [(0.0, (0.05, 0.05, 0.06, 1.0)), (0.12, (0.55, 0.55, 0.57, 1.0)),
                       (0.55, (0.93, 0.93, 0.92, 1.0)), (1.0, (0.85, 0.85, 0.86, 1.0))])
    _pl(nt, wave, "Fac", ramp, "Fac")
    p = _prod_principled(nt, out, Roughness=0.12, Coat_Weight=0.3)
    _pl(nt, ramp, "Color", p, "Base Color")
    _prod_object_sphere(bpy, sc, mat)
    r = _prod_rois(scene, {"vein_zone": (0.0, 0.15), "left": (-0.55, 0.0), "right": (0.5, 0.25),
                           "lower": (0.05, -0.55)})
    return scene, PROD_RES, r, ["noise_vector_warp", "vector_math_scale_add", "mapping_after_warp",
                                "wave_bands_saw", "color_ramp_4stop", "object_coords"], []


def _prod_pbr_group(bpy, sc, sl, addon_dir):
    """Four packed procedural images (base sRGB; roughness / metallic / normal Non-Color) inside a
    node group with a Tiling input; Mapping; Normal Map chained into Bump."""
    import numpy as np
    n = 128
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float32) / n
    tile = 4
    fx, fy = (xx * tile) % 1.0, (yy * tile) % 1.0
    mortar = ((fx < 0.06) | (fy < 0.06)).astype(np.float32)
    ti, tj = np.floor(xx * tile), np.floor(yy * tile)
    rnd = ((ti * 7 + tj * 13) % 5) / 5.0
    metal_tile = ((ti + tj) % 3 == 0).astype(np.float32)
    base = np.stack([0.55 + 0.25 * rnd, 0.25 + 0.2 * rnd, 0.15 + 0.1 * rnd], axis=-1)
    base = np.where(metal_tile[..., None] > 0, np.array([0.75, 0.72, 0.65], np.float32), base)
    base = np.where(mortar[..., None] > 0, np.array([0.12, 0.12, 0.12], np.float32), base)
    rough = np.where(mortar > 0, 0.9, np.where(metal_tile > 0, 0.25, 0.55 + 0.2 * rnd))
    metal = np.where(mortar > 0, 0.0, metal_tile)
    height = np.where(mortar > 0, 0.0, 1.0) * (0.6 + 0.4 * np.sin(fx * np.pi) * np.sin(fy * np.pi))
    height = height.astype(np.float32)
    gx, gy = np.gradient(height, axis=1) * n * 0.03, np.gradient(height, axis=0) * n * 0.03
    nrm = np.stack([-gx, -gy, np.ones_like(gx)], axis=-1)
    nrm /= np.linalg.norm(nrm, axis=-1, keepdims=True)
    nrm = nrm * 0.5 + 0.5

    def grey(a):
        return np.repeat(a[..., None].astype(np.float32), 3, axis=-1)
    scene = _prod_stage(bpy, sc, sl)  # resets bpy.data (images too): create the textures after it
    imgs = {"base": _prod_image(bpy, "PbrBase", base.astype(np.float32), False),
            "rough": _prod_image(bpy, "PbrRough", grey(rough), True),
            "metal": _prod_image(bpy, "PbrMetal", grey(metal), True),
            "normal": _prod_image(bpy, "PbrNormal", nrm.astype(np.float32), True)}
    grp = bpy.data.node_groups.new("PBRGroup", "ShaderNodeTree")
    grp.interface.new_socket("Shader", in_out="OUTPUT", socket_type="NodeSocketShader")
    grp.interface.new_socket("Tiling", in_out="INPUT", socket_type="NodeSocketFloat").default_value = 3.0
    gi = _pn(grp, "NodeGroupInput")
    go = _pn(grp, "NodeGroupOutput")
    tc = _pn(grp, "ShaderNodeTexCoord")
    mp = _pn(grp, "ShaderNodeMapping")
    _pset(mp, "Rotation", (0.0, 0.0, math.radians(15.0)))
    comb = _pn(grp, "ShaderNodeCombineXYZ")
    _pl(grp, gi, "Tiling", comb, "X")
    _pl(grp, gi, "Tiling", comb, "Y")
    _pset(comb, "Z", 1.0)
    _pl(grp, comb, "Vector", mp, "Scale")
    _pl(grp, tc, "UV", mp, "Vector")
    tex = {}
    for key in ("base", "rough", "metal", "normal"):
        t = _pn(grp, "ShaderNodeTexImage")
        t.image = imgs[key]
        t.interpolation = "Linear"
        _pl(grp, mp, "Vector", t, "Vector")
        tex[key] = t
    nmap = _pn(grp, "ShaderNodeNormalMap", space="TANGENT")
    _pset(nmap, "Strength", 1.0)
    _pl(grp, tex["normal"], "Color", nmap, "Color")
    bump = _pn(grp, "ShaderNodeBump")
    _pset(bump, "Strength", 0.25)
    _pset(bump, "Distance", 0.02)
    _pl(grp, tex["rough"], "Color", bump, "Height")
    _pl(grp, nmap, "Normal", bump, "Normal")
    p = _pn(grp, "ShaderNodeBsdfPrincipled")
    _pl(grp, tex["base"], "Color", p, "Base Color")
    _pl(grp, tex["rough"], "Color", p, "Roughness")
    _pl(grp, tex["metal"], "Color", p, "Metallic")
    _pl(grp, bump, "Normal", p, "Normal")
    grp.links.new(p.outputs["BSDF"], go.inputs["Shader"])
    mat, nt, out = sl._bare_material(bpy, "PbrGroup")
    gn = _pn(nt, "ShaderNodeGroup")
    gn.node_tree = grp
    nt.links.new(gn.outputs["Shader"], out.inputs["Surface"])
    _prod_object_sphere(bpy, sc, mat)
    r = _prod_rois(scene, {"centre": (0.0, 0.05), "left": (-0.5, 0.3), "right": (0.5, -0.1),
                           "lower": (-0.15, -0.5)}, hw=0.035)
    return scene, PROD_RES, r, ["node_group", "tex_image_srgb_and_data", "mapping_uv_rotation",
                                "normal_map_tangent", "bump_chained_on_normal_map"], []


def _prod_shader_stack(bpy, sc, sl, addon_dir):
    """Add Shader( Mix( Mix(Principled metal, Principled paint, Noise mask), Glass, fac ),
    Emission ): three shader levels deep."""
    scene = _prod_stage(bpy, sc, sl)
    mat, nt, out = sl._bare_material(bpy, "ShaderStack")
    tc = _pn(nt, "ShaderNodeTexCoord")
    noise = _pn(nt, "ShaderNodeTexNoise")
    _pset(noise, "Scale", 4.0)
    _pset(noise, "Detail", 3.0)
    _pl(nt, tc, "Object", noise, "Vector")
    metal = _pn(nt, "ShaderNodeBsdfPrincipled")
    _pset(metal, "Base Color", (0.9, 0.62, 0.3, 1.0))
    _pset(metal, "Metallic", 1.0)
    _pset(metal, "Roughness", 0.18)
    paint = _pn(nt, "ShaderNodeBsdfPrincipled")
    _pset(paint, "Base Color", (0.08, 0.25, 0.6, 1.0))
    _pset(paint, "Roughness", 0.4)
    inner = _pn(nt, "ShaderNodeMixShader")
    _pl(nt, noise, "Fac", inner, "Fac")
    nt.links.new(metal.outputs["BSDF"], inner.inputs[1])
    nt.links.new(paint.outputs["BSDF"], inner.inputs[2])
    glass = _pn(nt, "ShaderNodeBsdfGlass")
    _pset(glass, "Color", (0.85, 0.95, 1.0, 1.0))
    _pset(glass, "Roughness", 0.05)
    _pset(glass, "IOR", 1.45)
    gnoise = _pn(nt, "ShaderNodeTexNoise")
    _pset(gnoise, "Scale", 2.0)
    _pl(nt, tc, "Object", gnoise, "Vector")
    gfac = _pramp(nt, [(0.35, (0.0, 0.0, 0.0, 1.0)), (0.65, (0.6, 0.6, 0.6, 1.0))])
    _pl(nt, gnoise, "Fac", gfac, "Fac")
    outer = _pn(nt, "ShaderNodeMixShader")
    _pl(nt, gfac, "Color", outer, "Fac")
    nt.links.new(inner.outputs["Shader"], outer.inputs[1])
    nt.links.new(glass.outputs["BSDF"], outer.inputs[2])
    emit = _pn(nt, "ShaderNodeEmission")
    _pset(emit, "Color", (1.0, 0.35, 0.08, 1.0))
    _pset(emit, "Strength", 0.6)
    add = _pn(nt, "ShaderNodeAddShader")
    nt.links.new(outer.outputs["Shader"], add.inputs[0])
    nt.links.new(emit.outputs["Emission"], add.inputs[1])
    nt.links.new(add.outputs["Shader"], out.inputs["Surface"])
    _prod_object_sphere(bpy, sc, mat)
    r = _prod_rois(scene, {"lit_front": (-0.2, 0.3), "right": (0.5, 0.05), "lower": (0.0, -0.5),
                           "upper_left": (-0.5, 0.5)})
    return scene, PROD_RES, r, ["mix_shader_3_deep", "add_shader_bsdf_emission", "glass_in_stack",
                                "principled_x2", "noise_masks"], []


def _prod_attributes(bpy, sc, sl, addon_dir):
    """Mesh Color Attribute -> Base Color, custom float Attribute -> Roughness, Object Info
    Random -> hue on three linked instances."""
    import bmesh
    scene = _prod_stage(bpy, sc, sl, cam=((0.0, -5.6, 1.4), (0.0, 0.0, 0.7), 38.0))
    me = bpy.data.meshes.new("AttrSphere")
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=64, v_segments=32, radius=0.6)
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = True
    ca = me.color_attributes.new("Col", "FLOAT_COLOR", "POINT")
    ra = me.attributes.new("rough", "FLOAT", "POINT")
    cols, rgh = [], []
    for v in me.vertices:
        x, _y, z = v.co
        stripe = 0.5 + 0.5 * math.sin(9.0 * x + 3.0 * z)
        cols.extend((0.15 + 0.75 * (0.5 + z / 1.2), 0.25 + 0.5 * stripe, 0.85 - 0.6 * (0.5 + z / 1.2), 1.0))
        rgh.append(0.12 + 0.75 * stripe)
    ca.data.foreach_set("color", cols)
    ra.data.foreach_set("value", rgh)
    mat, nt, out = sl._bare_material(bpy, "Attributes")
    vc = _pn(nt, "ShaderNodeVertexColor", layer_name="Col")
    at = _pn(nt, "ShaderNodeAttribute", attribute_type="GEOMETRY", attribute_name="rough")
    oi = _pn(nt, "ShaderNodeObjectInfo")
    hue = _pn(nt, "ShaderNodeHueSaturation")
    shift = _pn(nt, "ShaderNodeMapRange")  # Random 0..1 -> hue 0.25..0.75
    _pset(shift, "To Min", 0.25)
    _pset(shift, "To Max", 0.75)
    _pl(nt, oi, "Random", shift, "Value")
    _pl(nt, shift, "Result", hue, "Hue")
    _pl(nt, vc, "Color", hue, "Color")
    p = _prod_principled(nt, out, Metallic=0.0)
    _pl(nt, hue, "Color", p, "Base Color")
    _pl(nt, at, "Fac", p, "Roughness")
    me.materials.append(mat)
    for i, x in enumerate((-1.5, 0.0, 1.5)):
        o = bpy.data.objects.new(f"Inst{i}", me)
        scene.collection.objects.link(o)
        o.location = (x, 0.0, 0.6)
    r = _Rois(scene)
    for i, x in enumerate((-1.5, 0.0, 1.5)):
        r.add(f"instance{i}", (x - 0.15, -0.55, 0.75), 0.03)
    r.add("instance1_lower", (0.1, -0.55, 0.35), 0.03)
    return scene, PROD_RES, r, ["color_attribute", "attribute_float_geometry", "object_info_random",
                                "hue_saturation", "map_range", "linked_instances"], []


def _prod_light_path(bpy, sc, sl, addon_dir):
    """Is Camera Ray hides an emitter from the camera; Is Shadow Ray makes glass
    shadow-transparent; Ray Length tints the floor."""
    scene = _prod_stage(bpy, sc, sl, floor=False, sun_strength=1.1, area_power=40.0,
                        cam=((0.0, -5.2, 1.6), (0.0, 0.0, 0.7), 42.0))
    floor_mat, fnt, fout = sl._bare_material(bpy, "RayLengthFloor")
    lp = _pn(fnt, "ShaderNodeLightPath")
    rl = _pmath(fnt, "MULTIPLY", None, 0.12, clamp=True)
    _pl(fnt, lp, "Ray Length", rl, 0)
    ramp = _pramp(fnt, [(0.0, (0.75, 0.25, 0.15, 1.0)), (1.0, (0.15, 0.3, 0.75, 1.0))])
    _pl(fnt, rl, "Value", ramp, "Fac")
    fp = _pn(fnt, "ShaderNodeBsdfPrincipled")
    _pset(fp, "Roughness", 0.85)
    _pl(fnt, ramp, "Color", fp, "Base Color")
    fnt.links.new(fp.outputs["BSDF"], fout.inputs["Surface"])
    bpy.ops.mesh.primitive_plane_add(size=40.0, location=(0.0, 0.0, 0.0))
    floor_obj = bpy.context.active_object
    floor_obj.name = "RayLengthFloor"
    sc._assign(floor_obj, floor_mat)
    # glass sphere, shadow-transparent
    gmat, gnt, gout = sl._bare_material(bpy, "ShadowlessGlass")
    lp2 = _pn(gnt, "ShaderNodeLightPath")
    glass = _pn(gnt, "ShaderNodeBsdfGlass")
    _pset(glass, "Color", (0.9, 1.0, 0.95, 1.0))
    _pset(glass, "Roughness", 0.02)
    _pset(glass, "IOR", 1.45)
    trans = _pn(gnt, "ShaderNodeBsdfTransparent")
    mx = _pn(gnt, "ShaderNodeMixShader")
    _pl(gnt, lp2, "Is Shadow Ray", mx, "Fac")
    gnt.links.new(glass.outputs["BSDF"], mx.inputs[1])
    gnt.links.new(trans.outputs["BSDF"], mx.inputs[2])
    gnt.links.new(mx.outputs["Shader"], gout.inputs["Surface"])
    gs = sc._uv_sphere("GlassBall", (-1.0, 0.0, 0.7), 0.7, seg=64, rings=32)
    sc._assign(gs, gmat)
    # hidden emitter (invisible to the camera, still lights the scene)
    emat, ent, eout = sl._bare_material(bpy, "CameraHiddenEmitter")
    lp3 = _pn(ent, "ShaderNodeLightPath")
    em = _pn(ent, "ShaderNodeEmission")
    _pset(em, "Color", (1.0, 0.85, 0.6, 1.0))
    _pset(em, "Strength", 40.0)
    tr = _pn(ent, "ShaderNodeBsdfTransparent")
    mx2 = _pn(ent, "ShaderNodeMixShader")
    _pl(ent, lp3, "Is Camera Ray", mx2, "Fac")
    ent.links.new(em.outputs["Emission"], mx2.inputs[1])
    ent.links.new(tr.outputs["BSDF"], mx2.inputs[2])
    ent.links.new(mx2.outputs["Shader"], eout.inputs["Surface"])
    es = sc._uv_sphere("HiddenEmitter", (1.3, -0.3, 1.5), 0.3, seg=32, rings=16)
    sc._assign(es, emat)
    # a diffuse post next to the emitter so its light is visible on geometry
    pm = sc._principled("Post", (0.6, 0.6, 0.6), rough=0.9)
    sc._box("Post", (1.3, 0.3, 0.7), (0.5, 0.5, 1.4), pm)
    sd = PROD_SUN_DIR
    t = 0.7 / sd[2]  # sun shadow of the glass-ball centre on z=0 (shadow-transparent: light passes)
    r = _Rois(scene)
    r.add("glass_ball_centre", (-1.0, -0.7, 0.7), 0.035)
    r.add("glass_sun_shadow_floor", (-1.0 - sd[0] * t, 0.0 - sd[1] * t, 0.0), 0.04)
    r.add("emitter_hidden_region", (1.3, -0.3, 1.5), 0.035)
    r.add("floor_near", (0.3, -1.0, 0.0), 0.05)
    r.add("floor_far", (0.3, 5.0, 0.0), 0.05)
    return scene, PROD_RES, r, ["light_path_is_camera_ray", "light_path_is_shadow_ray",
                                "light_path_ray_length", "transparent_bsdf", "glass_in_mix"], []


def _prod_curves_geometry(bpy, sc, sl, addon_dir):
    """Noise -> Float Curve -> Map Range -> Math -> Roughness; Noise colour -> RGB Curves; Geometry
    Backfacing + Pointiness -> Mix. Object: a bumpy open bowl (its interior is backfacing)."""
    import bmesh
    import mathutils
    scene = _prod_stage(bpy, sc, sl, cam=((0.0, -4.4, 2.6), (0.0, 0.0, 0.6), 45.0))
    me = bpy.data.meshes.new("Bowl")
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=5, radius=0.9)
    for v in bm.verts:
        n = mathutils.noise.noise(v.co * 3.1) * 0.5 + mathutils.noise.noise(v.co * 7.3) * 0.2
        v.co *= 1.0 + 0.22 * n
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.calc_center_median().z > 0.35], context="FACES")
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = True
    mat, nt, out = sl._bare_material(bpy, "CurvesGeometry")
    tc = _pn(nt, "ShaderNodeTexCoord")
    noise = _pn(nt, "ShaderNodeTexNoise")
    _pset(noise, "Scale", 6.0)
    _pset(noise, "Detail", 4.0)
    _pl(nt, tc, "Object", noise, "Vector")
    fc = _pn(nt, "ShaderNodeFloatCurve")
    c = fc.mapping.curves[0]
    c.points[0].location = (0.0, 0.05)
    c.points[1].location = (1.0, 0.95)
    c.points.new(0.35, 0.1)
    c.points.new(0.65, 0.8)
    fc.mapping.update()
    _pl(nt, noise, "Fac", fc, "Value")
    mr = _pn(nt, "ShaderNodeMapRange")
    _pset(mr, "To Min", 0.15)
    _pset(mr, "To Max", 0.85)
    mr.clamp = True
    _pl(nt, fc, "Value", mr, "Value")
    rmath = _pmath(nt, "POWER", None, 1.3)
    _pl(nt, mr, "Result", rmath, 0)
    rc = _pn(nt, "ShaderNodeRGBCurve")
    cc = rc.mapping.curves[3]  # combined curve: S-shaped contrast
    cc.points[0].location = (0.0, 0.0)
    cc.points[1].location = (1.0, 1.0)
    cc.points.new(0.3, 0.12)
    cc.points.new(0.7, 0.88)
    rc.mapping.update()
    _pl(nt, noise, "Color", rc, "Color")
    geo = _pn(nt, "ShaderNodeNewGeometry")
    pt = _pn(nt, "ShaderNodeMapRange")
    _pset(pt, "From Min", 0.35)
    _pset(pt, "From Max", 0.65)
    pt.clamp = True
    _pl(nt, geo, "Pointiness", pt, "Value")
    tint = _pmix(nt, (0.35, 0.33, 0.30, 1.0), (0.85, 0.55, 0.2, 1.0), 0.0)  # A: rock, B: worn edge
    _pl(nt, pt, "Result", tint, "Factor_Float")
    _pl(nt, rc, "Color", tint, "A_Color")
    inside = _pmix(nt, (0.0, 0.0, 0.0, 1.0), (0.05, 0.4, 0.55, 1.0), 0.0)
    _pl(nt, tint, "Result_Color", inside, "A_Color")
    _pl(nt, geo, "Backfacing", inside, "Factor_Float")
    p = _prod_principled(nt, out)
    _pl(nt, inside, "Result_Color", p, "Base Color")
    _pl(nt, rmath, "Value", p, "Roughness")
    obj = bpy.data.objects.new("Bowl", me)
    scene.collection.objects.link(obj)
    obj.location = (0.0, 0.0, 0.85)
    sc._assign(obj, mat)
    r = _Rois(scene)
    r.add("outer_front", (0.0, -0.9, 0.55), 0.035)
    r.add("outer_upper_rim", (-0.6, -0.65, 1.05), 0.03)
    r.add("inner_backface", (0.0, 0.75, 0.9), 0.04)
    r.add("outer_left", (-0.85, -0.1, 0.5), 0.03)
    return scene, PROD_RES, r, ["float_curve", "map_range_clamp", "math_power", "rgb_curves",
                                "geometry_backfacing", "geometry_pointiness", "mix_rgba"], []


PROD_BUILDERS = {
    "prod_car_paint": _prod_car_paint,
    "prod_wood": _prod_wood,
    "prod_marble": _prod_marble,
    "prod_pbr_group": _prod_pbr_group,
    "prod_shader_stack": _prod_shader_stack,
    "prod_attributes": _prod_attributes,
    "prod_light_path": _prod_light_path,
    "prod_curves_geometry": _prod_curves_geometry,
}


V2_BUILDERS = {
    "v2_light_tree": _v2_light_tree,
    "v2_media": _v2_media,
    "v2_dispersion_caustics": _v2_dispersion_caustics,
    "v2_sky_sun": _v2_sky_sun,
    "v2_thin_film_metals": _v2_thin_film_metals,
    "v2_textures_opvm": _v2_textures_opvm,
    "v2_camera_geometry": _v2_camera_geometry,
    "v2_viewport": _v2_viewport,
    **VM_BUILDERS,  # pkg296
    **PROD_BUILDERS,  # pkg310
}


def _build_v2(bpy, scene_id, out_dir, addon_dir):
    sys.path.insert(0, str(SCENE_LIBRARY_DIR))
    import scene_library as sl  # noqa: E402
    sc = _load_showcase(addon_dir)
    builder = V2_BUILDERS[scene_id]
    scene, res, rois, tags, asset_names = builder(bpy, sc, sl, addon_dir)
    crops = rois.project() if rois.items else {}
    scene.render.engine = "CYCLES"
    scene.render.resolution_percentage = 100
    out_dir.mkdir(parents=True, exist_ok=True)
    blend_path = out_dir / f"{scene_id}.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path), relative_remap=True)
    assets = [{"path": f"benchmarks/reference_corpus/assets/{a}",
               "license": "CC0 1.0 (synthetic, generated by scene_library.write_volumes_vdbs)",
               "source_url": "", "sha256": _sha256(V2_ASSETS / a)} for a in asset_names]
    if scene_id in PROD_BUILDERS:  # pkg310: every prod scene is lit by the CC0 Poly Haven HDRI
        assets.append({**WORLD_SKY_HDRI_ASSET, "sha256": _sha256(V2_ASSETS / PROD_HDRI)})
    bpy.ops.wm.open_mainfile(filepath=str(blend_path))
    rs = bpy.context.scene
    counts, node_ids, tri = {}, set(), 0
    curve_count = curve_points = 0
    for obj in rs.objects:
        counts[obj.type] = counts.get(obj.type, 0) + 1
        if obj.type == "MESH":
            tri += sum(max(0, len(p.vertices) - 2) for p in obj.data.polygons)
        elif obj.type == "CURVES":
            curve_count += len(obj.data.curves)
            curve_points += len(obj.data.points)
    for mat in bpy.data.materials:
        if mat.use_nodes and mat.node_tree:
            node_ids.update(n.bl_idname for n in mat.node_tree.nodes)
    if rs.world and rs.world.use_nodes and rs.world.node_tree:
        node_ids.update(n.bl_idname for n in rs.world.node_tree.nodes)
    return {
        "family": "volumes_mesh" if scene_id in VM_BUILDERS else scene_id,
        "builder_fn": builder.__name__,
        "blend_path": str(blend_path.relative_to(REPO_ROOT)).replace("\\", "/"),
        "sha256": _sha256(blend_path),
        "settings": {"res_x": res[0], "res_y": res[1], "samples": V2_GATE_SPP,
                     "saved_default_engine": "CYCLES"},
        "v2": {"seed": V2_SEED, "spp_gate": V2_GATE_SPP, "spp_reference": V2_REFERENCE_SPP,
               "render_gate": scene_id not in V2_NO_GATE and scene_id not in VM_BUILDERS,
               "v2_tags": tags,
               "divergence": rois.notes,
               "cameras": sorted(o.name for o in rs.objects if o.type == "CAMERA"),
               "blender_version": bpy.app.version_string},
        "reopen_verified": bool(node_ids) and rs.camera is not None,
        "triangle_count": tri,
        "curve_count": curve_count,
        "curve_point_count": curve_points,
        "object_counts": counts,
        "node_ids": sorted(node_ids),
        "feature_tags": [],
        "assets": assets,
        "crops": crops,
    }


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--families", nargs="+", choices=[*BUILDERS, *V2_BUILDERS], default=list(BUILDERS))
    p.add_argument("--addon-dir", default="",
                   help="staged addon dir (__init__.py + astroray*.pyd); needed by v2_dispersion_caustics "
                        "(Sellmeier node). Build ONE v2 scene per Blender process.")
    p.add_argument("--out-dir", default=str(REPO_ROOT / "benchmarks" / "reference_corpus" / "scenes"))
    p.add_argument("--print-gap-registry", action="store_true",
                   help="print each family's uncovered DROPPED-SILENT rows "
                        "as a Markdown table (paste into README.md) and exit")
    args = p.parse_args(argv)
    if any(f in PROD_BUILDERS for f in args.families):  # pkg310: prod_* live in their own manifest
        if not all(f in PROD_BUILDERS for f in args.families):
            p.error("prod_* families cannot be mixed with others (separate manifests)")
        if args.out_dir == p.get_default("out_dir"):  # default -> production/; an explicit --out-dir is honoured
            args.out_dir = str(PROD_DIR)

    import bpy  # noqa: E402  (only valid inside Blender)

    assign, overrides = _load_assign_map()
    matrix_rows = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))

    out_dir = Path(args.out_dir).resolve()
    manifest_path = out_dir / "manifest.json"
    manifest = {"scenes": {}}
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    gap_registry: dict[str, list] = {}
    for scene_id in args.families:
        if scene_id in V2_BUILDERS:
            entry = _build_v2(bpy, scene_id, out_dir, args.addon_dir)
            manifest["scenes"][scene_id] = entry
            print(f"[pkg284] {scene_id}: {len(entry['crops'])} ROIs, "
                  f"triangle_count={entry['triangle_count']}, "
                  f"reopen_verified={entry['reopen_verified']}")
            continue
        entry, uncovered = _build_one(bpy, scene_id, out_dir, assign, overrides, matrix_rows)
        manifest["scenes"][scene_id] = entry
        gap_registry[scene_id] = uncovered
        print(f"[pkg259] {scene_id}: {len(entry['feature_tags'])} feature_tags, "
              f"{len(uncovered)} gap-registry rows, "
              f"triangle_count={entry['triangle_count']}, "
              f"reopen_verified={entry['reopen_verified']}")

    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=False) + "\n", encoding="utf-8", newline="\n")
    print(f"[pkg259] wrote {manifest_path}")

    if not gap_registry:  # v2-only run: nothing to add to the v1 gap registry
        return
    gap_path = out_dir / "gap_registry.json"
    existing_gap = {}
    if gap_path.is_file():
        existing_gap = json.loads(gap_path.read_text(encoding="utf-8"))
    existing_gap.update({
        fam: [{"category": r["category"], "feature": r["feature"], "bl_idname": r["bl_idname"],
               "socket_or_prop": r["socket_or_prop"]} for r in rows]
        for fam, rows in gap_registry.items()
    })
    gap_path.write_text(json.dumps(existing_gap, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(f"[pkg259] wrote {gap_path}")

    if args.print_gap_registry:
        for family, rows in gap_registry.items():
            print(f"\n### {family} gap registry ({len(rows)} DROPPED-SILENT rows)\n")
            by_feat: dict[str, list] = {}
            for r in rows:
                by_feat.setdefault(r["feature"], []).append(r)
            for feat in sorted(by_feat):
                socks = ", ".join(r["socket_or_prop"] for r in by_feat[feat])
                print(f"- `{feat}` (`{by_feat[feat][0]['bl_idname']}`): {socks}")


if __name__ == "__main__":
    main()

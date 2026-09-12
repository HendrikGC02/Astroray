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
    "render_settings": "build_render_settings_scene",
}
RESOLUTIONS = {
    "materials_hall": ("REFERENCE_MATERIALS_HALL_RES", "REFERENCE_MATERIALS_HALL_SAMPLES"),
    "textures_mapping": ("REFERENCE_TEXTURES_MAPPING_RES", "REFERENCE_TEXTURES_MAPPING_SAMPLES"),
    "lighting_studio": ("REFERENCE_LIGHTING_STUDIO_RES", "REFERENCE_LIGHTING_STUDIO_SAMPLES"),
    "world_sky_hdri": ("REFERENCE_WORLD_SKY_RES", "REFERENCE_WORLD_SKY_SAMPLES"),
    "world_sky_sky": ("REFERENCE_WORLD_SKY_RES", "REFERENCE_WORLD_SKY_SAMPLES"),
    "geometry_zoo": ("REFERENCE_GEOMETRY_ZOO_RES", "REFERENCE_GEOMETRY_ZOO_SAMPLES"),
    "camera_lens": ("REFERENCE_CAMERA_LENS_RES", "REFERENCE_CAMERA_LENS_SAMPLES"),
    "render_settings": ("REFERENCE_RENDER_SETTINGS_RES", "REFERENCE_RENDER_SETTINGS_SAMPLES"),
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
            else:
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
    return manifest_entry, uncovered_dropped


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--families", nargs="+", choices=list(BUILDERS), default=list(BUILDERS))
    p.add_argument("--out-dir", default=str(REPO_ROOT / "benchmarks" / "reference_corpus" / "scenes"))
    p.add_argument("--print-gap-registry", action="store_true",
                   help="print each family's uncovered DROPPED-SILENT rows "
                        "as a Markdown table (paste into README.md) and exit")
    args = p.parse_args(argv)

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
        entry, uncovered = _build_one(bpy, scene_id, out_dir, assign, overrides, matrix_rows)
        manifest["scenes"][scene_id] = entry
        gap_registry[scene_id] = uncovered
        print(f"[pkg259] {scene_id}: {len(entry['feature_tags'])} feature_tags, "
              f"{len(uncovered)} gap-registry rows, "
              f"triangle_count={entry['triangle_count']}, "
              f"reopen_verified={entry['reopen_verified']}")

    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    print(f"[pkg259] wrote {manifest_path}")

    gap_path = out_dir / "gap_registry.json"
    existing_gap = {}
    if gap_path.is_file():
        existing_gap = json.loads(gap_path.read_text(encoding="utf-8"))
    existing_gap.update({
        fam: [{"category": r["category"], "feature": r["feature"], "bl_idname": r["bl_idname"],
               "socket_or_prop": r["socket_or_prop"]} for r in rows]
        for fam, rows in gap_registry.items()
    })
    gap_path.write_text(json.dumps(existing_gap, indent=2, sort_keys=True) + "\n", encoding="utf-8")
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

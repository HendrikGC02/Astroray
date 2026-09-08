"""pkg259 Phase 0 — one-off allocation-table generator.

Reads docs/blender_parity/coverage_matrix.json (the Phase-A feature
universe: 527 rows, one per Blender node/light/camera/render/world
socket-or-prop) and assigns every (category, feature) pair to a primary
scene family from the pkg259 spec's seven families, with optional
secondary families for features that are meaningfully exercised in more
than one scene.

This is a Phase-0 design artefact, not a shipped tool — it is not
registered in scripts/README.md and is not the coverage_report.py the
spec asks build_corpus.py's future Phase 4 to write (that one joins
*rendered* manifests against the matrix; this one only proves every
matrix row has a family home so Phase 1-3 builders have a checklist).

Usage: python .astroray_plan/docs/pkg259-phase0/build_allocation_table.py
Output: prints a Markdown table per family to stdout AND writes
        .astroray_plan/docs/pkg259-phase0/allocation_table.md
"""
from __future__ import annotations

import collections
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MATRIX_PATH = ROOT / "docs" / "blender_parity" / "coverage_matrix.json"
OUT_PATH = Path(__file__).resolve().parent / "allocation_table.md"

FAMILIES = [
    "materials_hall",
    "textures_mapping",
    "lighting_studio",
    "world_sky",
    "geometry_zoo",
    "camera_lens",
    "render_settings",
]

# (category, feature) -> (primary_family, [secondary_families])
# Every distinct (category, feature) pair observed in the matrix MUST
# appear here; the script asserts this and lists anything missing.
ASSIGN: dict[tuple[str, str], tuple[str, list[str]]] = {
    # --- materials_hall: every BSDF / closure / material-graph terminus ---
    ("shader_node", "ADD_SHADER"): ("materials_hall", []),
    ("shader_node", "BSDF_DIFFUSE"): ("materials_hall", []),
    ("shader_node", "BSDF_GLASS"): ("materials_hall", []),
    ("shader_node", "BSDF_GLOSSY"): ("materials_hall", []),
    ("shader_node", "BSDF_HAIR"): ("materials_hall", ["geometry_zoo"]),
    ("shader_node", "BSDF_HAIR_PRINCIPLED"): ("materials_hall", ["geometry_zoo"]),
    ("shader_node", "BSDF_METALLIC"): ("materials_hall", []),
    ("shader_node", "BSDF_PRINCIPLED"): ("materials_hall", []),
    ("shader_node", "BSDF_RAY_PORTAL"): ("materials_hall", []),
    ("shader_node", "BSDF_REFRACTION"): ("materials_hall", []),
    ("shader_node", "BSDF_SHEEN"): ("materials_hall", []),
    ("shader_node", "BSDF_TOON"): ("materials_hall", []),
    ("shader_node", "BSDF_TRANSLUCENT"): ("materials_hall", []),
    ("shader_node", "BSDF_TRANSPARENT"): ("materials_hall", []),
    ("shader_node", "EEVEE_SPECULAR"): ("materials_hall", []),
    ("shader_node", "EMISSION"): ("materials_hall", []),
    ("shader_node", "HOLDOUT"): ("materials_hall", []),
    ("shader_node", "MIX_SHADER"): ("materials_hall", []),
    ("shader_node", "SHADERTORGB"): ("materials_hall", []),
    ("shader_node", "SUBSURFACE_SCATTERING"): ("materials_hall", []),
    ("shader_node", "WAVELENGTH"): ("materials_hall", []),
    ("shader_node", "BLACKBODY"): ("materials_hall", []),
    ("shader_node", "MATERIAL_RAYCAST"): ("materials_hall", []),
    ("shader_node", "OUTPUT_MATERIAL"): ("materials_hall", []),
    ("shader_node", "SCRIPT"): ("materials_hall", []),

    # --- geometry_zoo: volumes (shader-graph side), hair/instancing/modifiers
    #     covered visually but NOT matrix-tracked (no scene-graph category
    #     exists in coverage_matrix.json yet -- see doc "known matrix gap") ---
    ("shader_node", "PRINCIPLED_VOLUME"): ("geometry_zoo", ["materials_hall"]),
    ("shader_node", "VOLUME_SCATTER"): ("geometry_zoo", ["materials_hall"]),
    ("shader_node", "VOLUME_ABSORPTION"): ("geometry_zoo", ["materials_hall"]),
    ("shader_node", "VOLUME_COEFFICIENTS"): ("geometry_zoo", ["materials_hall"]),

    # --- textures_mapping: image/procedural textures, mapping/UV,
    #     bump/normal/displacement, and the utility/converter node graph
    #     plumbing that every textured material leans on ---
    ("shader_node", "TEX_BRICK"): ("textures_mapping", []),
    ("shader_node", "TEX_CHECKER"): ("textures_mapping", []),
    ("shader_node", "TEX_COORD"): ("textures_mapping", []),
    ("shader_node", "TEX_GABOR"): ("textures_mapping", []),
    ("shader_node", "TEX_GRADIENT"): ("textures_mapping", []),
    ("shader_node", "TEX_IMAGE"): ("textures_mapping", []),
    ("shader_node", "TEX_MAGIC"): ("textures_mapping", []),
    ("shader_node", "TEX_NOISE"): ("textures_mapping", []),
    ("shader_node", "TEX_VORONOI"): ("textures_mapping", []),
    ("shader_node", "TEX_WAVE"): ("textures_mapping", []),
    ("shader_node", "TEX_WHITE_NOISE"): ("textures_mapping", []),
    ("shader_node", "MAPPING"): ("textures_mapping", []),
    ("shader_node", "UVMAP"): ("textures_mapping", []),
    ("shader_node", "TANGENT"): ("textures_mapping", []),
    ("shader_node", "NORMAL"): ("textures_mapping", []),
    ("shader_node", "NORMAL_MAP"): ("textures_mapping", []),
    ("shader_node", "BUMP"): ("textures_mapping", []),
    ("shader_node", "DISPLACEMENT"): ("textures_mapping", ["geometry_zoo"]),
    ("shader_node", "VECTOR_DISPLACEMENT"): ("textures_mapping", ["geometry_zoo"]),
    ("shader_node", "MATH"): ("textures_mapping", []),
    ("shader_node", "VECT_MATH"): ("textures_mapping", []),
    ("shader_node", "MAP_RANGE"): ("textures_mapping", []),
    ("shader_node", "CLAMP"): ("textures_mapping", []),
    ("shader_node", "MIX"): ("textures_mapping", []),
    ("shader_node", "MIX_RGB"): ("textures_mapping", []),
    ("shader_node", "COMBINE_COLOR"): ("textures_mapping", []),
    ("shader_node", "COMBXYZ"): ("textures_mapping", []),
    ("shader_node", "SEPXYZ"): ("textures_mapping", []),
    ("shader_node", "SEPARATE_COLOR"): ("textures_mapping", []),
    ("shader_node", "CURVE_FLOAT"): ("textures_mapping", []),
    ("shader_node", "CURVE_RGB"): ("textures_mapping", []),
    ("shader_node", "CURVE_VEC"): ("textures_mapping", []),
    ("shader_node", "VALTORGB"): ("textures_mapping", []),
    ("shader_node", "BRIGHTCONTRAST"): ("textures_mapping", []),
    ("shader_node", "GAMMA"): ("textures_mapping", []),
    ("shader_node", "HUE_SAT"): ("textures_mapping", []),
    ("shader_node", "INVERT"): ("textures_mapping", []),
    ("shader_node", "RGBTOBW"): ("textures_mapping", []),
    ("shader_node", "VECTOR_ROTATE"): ("textures_mapping", []),
    ("shader_node", "VECT_TRANSFORM"): ("textures_mapping", []),
    ("shader_node", "SQUEEZE"): ("textures_mapping", []),
    ("shader_node", "LAYER_WEIGHT"): ("textures_mapping", []),
    ("shader_node", "FRESNEL"): ("textures_mapping", []),
    ("shader_node", "LIGHT_FALLOFF"): ("textures_mapping", []),
    ("shader_node", "AMBIENT_OCCLUSION"): ("textures_mapping", []),
    ("shader_node", "ATTRIBUTE"): ("textures_mapping", []),
    ("shader_node", "BEVEL"): ("textures_mapping", []),
    ("shader_node", "ShaderNodeRadialTiling"): ("textures_mapping", []),
    ("shader_node", "WIREFRAME"): ("textures_mapping", []),

    # --- world_sky: HDRI, Sky texture, world background, world node tree ---
    ("shader_node", "TEX_SKY"): ("world_sky", []),
    ("shader_node", "TEX_ENVIRONMENT"): ("world_sky", ["materials_hall"]),
    ("shader_node", "BACKGROUND"): ("world_sky", []),
    ("shader_node", "OUTPUT_WORLD"): ("world_sky", []),
    ("world", "World"): ("world_sky", []),

    # --- lighting_studio: light datablocks + IES + light-group output ---
    ("light", "POINT"): ("lighting_studio", []),
    ("light", "SUN"): ("lighting_studio", []),
    ("light", "SPOT"): ("lighting_studio", []),
    ("light", "AREA"): ("lighting_studio", []),
    ("shader_node", "TEX_IES"): ("lighting_studio", ["textures_mapping"]),
    ("shader_node", "OUTPUT_LIGHT"): ("lighting_studio", []),

    # --- camera_lens: camera datablock ---
    ("camera", "Camera"): ("camera_lens", []),

    # --- render_settings: engine/render props + AOV/Freestyle outputs.
    #     Freestyle (OUTPUT_LINESTYLE + UVALONGSTROKE) grouped together here
    #     per Astra's brainstorm critique: "Freestyle is a separate
    #     line-rendering/output integration case, not another material
    #     closure" (see reference-corpus-design-2026-09.md Sec 5) ---
    ("render_settings", "RenderSettings"): ("render_settings", []),
    ("shader_node", "OUTPUT_AOV"): ("render_settings", []),
    ("shader_node", "OUTPUT_LINESTYLE"): ("render_settings", []),
    ("shader_node", "UVALONGSTROKE"): ("render_settings", []),

    # --- pkg260 scanner extension (2026-09-08): object / image_property /
    #     input_node categories, per the pkg260 brief's family assignments ---
    # object: instancing, modifier presence, motion blur, smooth/auto-smooth
    # shading, Curves objects -- exactly the geometry_zoo "known matrix gap"
    # this design doc's Sec1.5 flagged before pkg260 existed.
    ("object", "Object"): ("geometry_zoo", []),
    # image_property: Image/TexImage sub-properties -- textures_mapping per
    # the brief (same family as TEX_IMAGE itself, Row 3).
    ("image_property", "Image"): ("textures_mapping", []),
    ("image_property", "ShaderNodeTexImage"): ("textures_mapping", []),
    # input_node: shader input/source nodes. Light Path / Object Info /
    # Geometry -> textures_mapping per the brief (converter-node role, Row 5);
    # Attribute / Color Attribute join the same family as their existing
    # shader_node/ATTRIBUTE property-row sibling (already textures_mapping
    # above). Hair Info is the one judgment call the brief left open: it is
    # a hair-material-graph input (feeds hair BSDF params), not a generic
    # converter, so it follows BSDF_HAIR/BSDF_HAIR_PRINCIPLED's own cross-tag
    # pattern above (geometry_zoo primary, materials_hall secondary) rather
    # than textures_mapping.
    ("input_node", "NEW_GEOMETRY"): ("textures_mapping", []),
    ("input_node", "OBJECT_INFO"): ("textures_mapping", []),
    ("input_node", "LIGHT_PATH"): ("textures_mapping", []),
    ("input_node", "ATTRIBUTE"): ("textures_mapping", []),
    ("input_node", "VERTEX_COLOR"): ("textures_mapping", []),
    ("input_node", "HAIR_INFO"): ("geometry_zoo", ["materials_hall"]),
}

# pkg260: per-ROW override for the rare case where two rows sharing one
# (category, feature) tuple genuinely belong in different families. Checked
# BEFORE the (category, feature)-level ASSIGN above. Today: World's other row
# (use_nodes) stays world_sky per ASSIGN; the light-linking/shadow-linking
# gap card is a lighting_studio concern per the pkg259 design doc Sec1.3 and
# the pkg260 brief, not a world_sky one.
SOCKET_OVERRIDE: dict[tuple[str, str, str], tuple[str, list[str]]] = {
    ("world", "World", "light_linking_shadow_linking"): ("lighting_studio", []),
}


def main() -> None:
    rows = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
    print(f"total rows: {len(rows)}")

    observed = {(r["category"], r["feature"]) for r in rows}
    missing = observed - ASSIGN.keys()
    if missing:
        raise SystemExit(f"UNMAPPED (category, feature) pairs: {sorted(missing)}")
    extra = ASSIGN.keys() - observed
    if extra:
        raise SystemExit(f"ASSIGN has stale entries not in matrix: {sorted(extra)}")

    by_family: dict[str, list[dict]] = collections.defaultdict(list)
    for r in rows:
        override = SOCKET_OVERRIDE.get((r["category"], r["feature"], r["socket_or_prop"]))
        if override is not None:
            primary, secondary = override
        else:
            primary, secondary = ASSIGN[(r["category"], r["feature"])]
        by_family[primary].append(r)

    totals = {}
    lines: list[str] = []
    lines.append("# pkg259 Phase 0 — generated feature allocation table\n")
    lines.append(
        "Generated by `.astroray_plan/docs/pkg259-phase0/build_allocation_table.py` "
        "from `docs/blender_parity/coverage_matrix.json` "
        f"({len(rows)} rows). Do not hand-edit; re-run the script.\n"
    )

    grand_status = collections.Counter()
    for family in FAMILIES:
        frows = by_family.get(family, [])
        status = collections.Counter(r["classification"] for r in frows)
        grand_status.update(status)
        totals[family] = (len(frows), dict(status))
        lines.append(f"\n## {family}  ({len(frows)} rows)\n")
        lines.append(f"SUPPORTED {status['SUPPORTED']} / APPROXIMATED "
                      f"{status['APPROXIMATED']} / DROPPED-SILENT "
                      f"{status['DROPPED-SILENT']}\n")
        lines.append("| Node / category | bl_idname | sockets/props (status) |")
        lines.append("|---|---|---|")
        by_feat: dict[str, list[dict]] = collections.defaultdict(list)
        for r in frows:
            by_feat[r["feature"]].append(r)
        for feat in sorted(by_feat):
            frs = by_feat[feat]
            bl = frs[0]["bl_idname"]
            socks = "; ".join(
                f"{r['socket_or_prop']} [{r['classification']}]" for r in frs
            )
            lines.append(f"| {feat} | {bl} | {socks} |")

    lines.append("\n## Totals\n")
    lines.append(f"Grand total rows: {sum(n for n, _ in totals.values())} "
                  f"(matrix has {len(rows)})")
    lines.append(f"SUPPORTED {grand_status['SUPPORTED']} / "
                  f"APPROXIMATED {grand_status['APPROXIMATED']} / "
                  f"DROPPED-SILENT {grand_status['DROPPED-SILENT']}")
    lines.append("\n| family | rows | SUPPORTED | APPROXIMATED | DROPPED-SILENT |")
    lines.append("|---|---|---|---|---|")
    for family in FAMILIES:
        n, status = totals[family]
        lines.append(f"| {family} | {n} | {status.get('SUPPORTED',0)} | "
                      f"{status.get('APPROXIMATED',0)} | "
                      f"{status.get('DROPPED-SILENT',0)} |")

    out = "\n".join(lines) + "\n"
    OUT_PATH.write_text(out, encoding="utf-8")
    print(f"wrote {OUT_PATH} ({len(out)} chars)")
    print(f"SUPPORTED {grand_status['SUPPORTED']} / APPROXIMATED "
          f"{grand_status['APPROXIMATED']} / DROPPED-SILENT "
          f"{grand_status['DROPPED-SILENT']}")


if __name__ == "__main__":
    main()

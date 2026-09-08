"""pkg260 -- coverage-matrix scanner extension acceptance gate.

Runs entirely on the COMMITTED `docs/blender_parity/coverage_matrix.json` --
no Blender, no astroray import. The headless regeneration itself (the
reproduce block in `.astroray_plan/docs/blender-coverage-reaudit-2026-09.md`)
is a separate, manual step; this file only proves the checked-in artefact has
the shape the pkg260 spec asks for and stays that way as the addon evolves.

Before this package: `scripts/generate_blender_parity_matrix.py` enumerated
only `shader_node` / `light` / `camera` / `render_settings` / `world` rows
(527 total) and had 13 (category, feature, bl_idname, socket_or_prop) key
collisions (Map Range's float/vector variants, Mix's per-data-type A/B/
Factor, Math/Vector Math/Add Shader/Mix Shader's positional sockets, Tex
Gabor's 2D/3D Orientation). After: three new categories (`object`,
`image_property`, `input_node`), 4 new camera rows, 1 new world gap-card row,
and every duplicate key disambiguated by a stable Blender-socket-identifier
suffix -- 586 rows, zero duplicate keys.
"""
import json
from collections import Counter
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MATRIX_PATH = REPO_ROOT / "docs" / "blender_parity" / "coverage_matrix.json"


@pytest.fixture(scope="module")
def matrix_rows():
    return json.loads(MATRIX_PATH.read_text(encoding="utf-8"))


def _row_key(row):
    return (row["category"], row["feature"], row["bl_idname"], row["socket_or_prop"])


# ---------------------------------------------------------------------------
# Total row count -- pinned. Update this number (and the delta note below)
# only when a deliberate scanner change adds/removes/renames rows; re-derive
# it by re-running the headless reproduce block and re-reading
# docs/blender_parity/coverage_matrix.json's new length.
#
# 586 = 527 (pre-pkg260 baseline, pkg229 re-audit 2026-09) + 59 pkg260 rows:
#   +4  camera   (focus_distance, focus_object, ortho_scale, sensor_fit)
#   +1  world    (light_linking_shadow_linking gap card)
#   +6  object   (instance_type, instance_collection, modifiers,
#                 use_motion_blur, split_normals, type:CURVES)
#   +6  image_property (colorspace_settings.name, alpha_mode,
#                 source==TILED, TexImage interpolation/extension/projection)
#   +42 input_node (Geometry 9 + Object Info 6 + Attribute 4 +
#                 Color Attribute 2 + Hair Info 6 + Light Path 15)
# The duplicate-key collapse renames 23 existing rows' keys (adds a stable
# [identifier] suffix) but does not change the total row count -- it was
# already 527 including the literal duplicates.
# ---------------------------------------------------------------------------
EXPECTED_TOTAL_ROWS = 586


def test_total_row_count_pinned(matrix_rows):
    assert len(matrix_rows) == EXPECTED_TOTAL_ROWS, (
        f"coverage_matrix.json has {len(matrix_rows)} rows, expected "
        f"{EXPECTED_TOTAL_ROWS}. If this is a deliberate scanner change, "
        "update EXPECTED_TOTAL_ROWS and the delta comment above it.")


def test_zero_duplicate_row_keys(matrix_rows):
    counts = Counter(_row_key(r) for r in matrix_rows)
    dups = {k: v for k, v in counts.items() if v > 1}
    assert not dups, f"duplicate (category,feature,bl_idname,socket_or_prop) keys found: {dups}"


# ---------------------------------------------------------------------------
# object category
# ---------------------------------------------------------------------------

OBJECT_ROW_KEYS = {
    ("object", "Object", "", "instance_type"),
    ("object", "Object", "", "instance_collection"),
    ("object", "Object", "", "modifiers"),
    ("object", "Object", "", "use_motion_blur"),
    ("object", "Object", "", "split_normals"),
    ("object", "Object", "", "type:CURVES"),
}

OBJECT_SUPPORTED = {
    ("object", "Object", "", "instance_type"),
    ("object", "Object", "", "modifiers"),
    ("object", "Object", "", "use_motion_blur"),
    ("object", "Object", "", "split_normals"),
    ("object", "Object", "", "type:CURVES"),
}


def test_object_category_rows_present(matrix_rows):
    present = {_row_key(r) for r in matrix_rows if r["category"] == "object"}
    assert present == OBJECT_ROW_KEYS


def test_object_category_classifications(matrix_rows):
    by_key = {_row_key(r): r["classification"] for r in matrix_rows if r["category"] == "object"}
    for key in OBJECT_ROW_KEYS:
        expected = "SUPPORTED" if key in OBJECT_SUPPORTED else "DROPPED-SILENT"
        assert by_key[key] == expected, f"{key}: expected {expected}, got {by_key[key]}"


# ---------------------------------------------------------------------------
# image_property category -- all DROPPED-SILENT (confirmed zero addon reads)
# ---------------------------------------------------------------------------

IMAGE_PROPERTY_ROW_KEYS = {
    ("image_property", "Image", "", "colorspace_settings.name"),
    ("image_property", "Image", "", "alpha_mode"),
    ("image_property", "Image", "", "source==TILED (UDIM)"),
    ("image_property", "ShaderNodeTexImage", "ShaderNodeTexImage", "interpolation"),
    ("image_property", "ShaderNodeTexImage", "ShaderNodeTexImage", "extension"),
    ("image_property", "ShaderNodeTexImage", "ShaderNodeTexImage", "projection"),
}


def test_image_property_category_rows_present(matrix_rows):
    present = {_row_key(r) for r in matrix_rows if r["category"] == "image_property"}
    assert present == IMAGE_PROPERTY_ROW_KEYS


def test_image_property_all_dropped_silent(matrix_rows):
    rows = [r for r in matrix_rows if r["category"] == "image_property"]
    assert len(rows) == 6
    for r in rows:
        assert r["classification"] == "DROPPED-SILENT", r


# ---------------------------------------------------------------------------
# input_node category -- outputs of Geometry, Object Info, Attribute, Color
# Attribute, Hair Info, Light Path. All DROPPED-SILENT (zero dispatch
# literals for these ntypes anywhere in the addon).
# ---------------------------------------------------------------------------

INPUT_NODE_FEATURE_OUTPUT_COUNTS = {
    "NEW_GEOMETRY": 9,
    "OBJECT_INFO": 6,
    "ATTRIBUTE": 4,
    "VERTEX_COLOR": 2,
    "HAIR_INFO": 6,
    "LIGHT_PATH": 15,
}


def test_input_node_category_features_and_counts(matrix_rows):
    rows = [r for r in matrix_rows if r["category"] == "input_node"]
    by_feature = Counter(r["feature"] for r in rows)
    assert dict(by_feature) == INPUT_NODE_FEATURE_OUTPUT_COUNTS
    assert len(rows) == sum(INPUT_NODE_FEATURE_OUTPUT_COUNTS.values()) == 42


def test_input_node_socket_prefix_is_output(matrix_rows):
    rows = [r for r in matrix_rows if r["category"] == "input_node"]
    assert rows, "expected input_node rows"
    for r in rows:
        assert r["socket_or_prop"].startswith("output:"), r


def test_input_node_all_dropped_silent(matrix_rows):
    """Zero addon evidence today (confirmed by both the AST scanner and a
    manual source grep for these six ntype literals) -- if a future package
    wires one of these nodes up, classify_shader_node's reuse in the scanner
    will flip the relevant row(s) to SUPPORTED/APPROXIMATED automatically and
    this assertion (not the row set) is what should then change."""
    rows = [r for r in matrix_rows if r["category"] == "input_node"]
    for r in rows:
        assert r["classification"] == "DROPPED-SILENT", r


# ---------------------------------------------------------------------------
# camera category additions (design doc Sec1.6 "unscanned" props)
# ---------------------------------------------------------------------------

def test_camera_new_rows_present_and_classified(matrix_rows):
    by_key = {
        _row_key(r): r["classification"]
        for r in matrix_rows if r["category"] == "camera"
    }
    expected = {
        ("camera", "Camera", "", "focus_distance"): "SUPPORTED",
        ("camera", "Camera", "", "focus_object"): "SUPPORTED",
        ("camera", "Camera", "", "sensor_fit"): "SUPPORTED",
        ("camera", "Camera", "", "ortho_scale"): "DROPPED-SILENT",
    }
    for key, cls in expected.items():
        assert key in by_key, key
        assert by_key[key] == cls, f"{key}: expected {cls}, got {by_key[key]}"


# ---------------------------------------------------------------------------
# world gap card -- light linking / shadow linking (owner decision 2026-09-08)
# ---------------------------------------------------------------------------

def test_world_light_linking_gap_card_present(matrix_rows):
    rows = [r for r in matrix_rows if r["category"] == "world"]
    key = ("world", "World", "", "light_linking_shadow_linking")
    by_key = {_row_key(r): r for r in rows}
    assert key in by_key
    assert by_key[key]["classification"] == "DROPPED-SILENT"
    # Exactly one gap-card row, not per-object rows.
    assert sum(1 for r in rows if r["socket_or_prop"] == "light_linking_shadow_linking") == 1


# ---------------------------------------------------------------------------
# Duplicate-collapse: 13 pre-existing key-collision groups now disambiguated
# by a stable [identifier] suffix. Every one of these must exist and be
# unique; the un-suffixed sibling (identifier == name) must still exist too.
# ---------------------------------------------------------------------------

DUPLICATE_COLLAPSE_SUFFIXED_KEYS = {
    ("shader_node", "ADD_SHADER", "ShaderNodeAddShader", "input:Shader[Shader_001]"),
    ("shader_node", "MIX_SHADER", "ShaderNodeMixShader", "input:Shader[Shader_001]"),
    ("shader_node", "MATH", "ShaderNodeMath", "input:Value[Value_001]"),
    ("shader_node", "MATH", "ShaderNodeMath", "input:Value[Value_002]"),
    ("shader_node", "VECT_MATH", "ShaderNodeVectorMath", "input:Vector[Vector_001]"),
    ("shader_node", "VECT_MATH", "ShaderNodeVectorMath", "input:Vector[Vector_002]"),
    ("shader_node", "MAP_RANGE", "ShaderNodeMapRange", "input:From Min[From_Min_FLOAT3]"),
    ("shader_node", "MAP_RANGE", "ShaderNodeMapRange", "input:From Max[From_Max_FLOAT3]"),
    ("shader_node", "MAP_RANGE", "ShaderNodeMapRange", "input:To Min[To_Min_FLOAT3]"),
    ("shader_node", "MAP_RANGE", "ShaderNodeMapRange", "input:To Max[To_Max_FLOAT3]"),
    ("shader_node", "MAP_RANGE", "ShaderNodeMapRange", "input:Steps[Steps_FLOAT3]"),
    ("shader_node", "MIX", "ShaderNodeMix", "input:Factor[Factor_Float]"),
    ("shader_node", "MIX", "ShaderNodeMix", "input:Factor[Factor_Vector]"),
    ("shader_node", "MIX", "ShaderNodeMix", "input:A[A_Float]"),
    ("shader_node", "MIX", "ShaderNodeMix", "input:A[A_Vector]"),
    ("shader_node", "MIX", "ShaderNodeMix", "input:A[A_Color]"),
    ("shader_node", "MIX", "ShaderNodeMix", "input:A[A_Rotation]"),
    ("shader_node", "MIX", "ShaderNodeMix", "input:B[B_Float]"),
    ("shader_node", "MIX", "ShaderNodeMix", "input:B[B_Vector]"),
    ("shader_node", "MIX", "ShaderNodeMix", "input:B[B_Color]"),
    ("shader_node", "MIX", "ShaderNodeMix", "input:B[B_Rotation]"),
    ("shader_node", "TEX_GABOR", "ShaderNodeTexGabor", "input:Orientation[Orientation 2D]"),
    ("shader_node", "TEX_GABOR", "ShaderNodeTexGabor", "input:Orientation[Orientation 3D]"),
}

# The at-most-one bare (un-suffixed) key that survives per group -- MIX's
# Factor/A/B and TEX_GABOR's Orientation have NO member whose identifier
# equals the bare name, so those four bare keys do not exist any more.
DUPLICATE_COLLAPSE_SURVIVING_BARE_KEYS = {
    ("shader_node", "ADD_SHADER", "ShaderNodeAddShader", "input:Shader"),
    ("shader_node", "MIX_SHADER", "ShaderNodeMixShader", "input:Shader"),
    ("shader_node", "MATH", "ShaderNodeMath", "input:Value"),
    ("shader_node", "VECT_MATH", "ShaderNodeVectorMath", "input:Vector"),
    ("shader_node", "MAP_RANGE", "ShaderNodeMapRange", "input:From Min"),
    ("shader_node", "MAP_RANGE", "ShaderNodeMapRange", "input:From Max"),
    ("shader_node", "MAP_RANGE", "ShaderNodeMapRange", "input:To Min"),
    ("shader_node", "MAP_RANGE", "ShaderNodeMapRange", "input:To Max"),
    ("shader_node", "MAP_RANGE", "ShaderNodeMapRange", "input:Steps"),
}

DUPLICATE_COLLAPSE_VANISHED_BARE_KEYS = {
    ("shader_node", "MIX", "ShaderNodeMix", "input:Factor"),
    ("shader_node", "MIX", "ShaderNodeMix", "input:A"),
    ("shader_node", "MIX", "ShaderNodeMix", "input:B"),
    ("shader_node", "TEX_GABOR", "ShaderNodeTexGabor", "input:Orientation"),
}


def test_duplicate_collapse_suffixed_keys_present(matrix_rows):
    all_keys = {_row_key(r) for r in matrix_rows}
    missing = DUPLICATE_COLLAPSE_SUFFIXED_KEYS - all_keys
    assert not missing, f"missing suffixed duplicate-collapse keys: {missing}"


def test_duplicate_collapse_bare_keys(matrix_rows):
    all_keys = {_row_key(r) for r in matrix_rows}
    missing_survivors = DUPLICATE_COLLAPSE_SURVIVING_BARE_KEYS - all_keys
    assert not missing_survivors, f"expected bare keys missing: {missing_survivors}"
    still_present = DUPLICATE_COLLAPSE_VANISHED_BARE_KEYS & all_keys
    assert not still_present, (
        f"these bare keys should have been fully renamed away (no member's "
        f"identifier equals the bare name): {still_present}")


# ---------------------------------------------------------------------------
# pkg257 hand-verified DISPLACEMENT hook -- must still apply unchanged.
# ---------------------------------------------------------------------------

def test_pkg257_displacement_evidence_still_applies(matrix_rows):
    disp_rows = {r["socket_or_prop"]: r["classification"]
                 for r in matrix_rows
                 if r["category"] == "shader_node" and r["feature"] == "DISPLACEMENT"}
    assert disp_rows == {
        "input:Height": "APPROXIMATED",
        "input:Midlevel": "APPROXIMATED",
        "input:Scale": "APPROXIMATED",
        "input:Normal": "DROPPED-SILENT",
        "prop:space": "DROPPED-SILENT",
    }

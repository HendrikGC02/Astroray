# -*- coding: utf-8 -*-
"""North-star gate (c) - pinned reference-scene corpus integrity check.

Verifies the three .blend files required by
``.astroray_plan/docs/north-star-and-integration-gate-2026-09-07.md`` section
2(c) are present under ``benchmarks/blender_parity/scenes/`` and that
``manifest.json``'s recorded SHA-256 matches each committed file byte-for-byte.
No Blender/GPU needed - this only reads files and hashes bytes, so it runs
everywhere (CI included), the way the harness's other pure tests do (see
tests/test_blender_parity_harness.py).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCENES_DIR = REPO_ROOT / "benchmarks" / "blender_parity" / "scenes"
MANIFEST_PATH = SCENES_DIR / "manifest.json"

EXPECTED_SCENE_IDS = ("cornell_interior", "material_zoo", "hdri_exterior_hair")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def manifest() -> dict:
    if not MANIFEST_PATH.is_file():
        pytest.skip(f"manifest not found at {MANIFEST_PATH}")
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def test_manifest_lists_all_three_scenes(manifest):
    assert set(manifest["scenes"].keys()) == set(EXPECTED_SCENE_IDS)


@pytest.mark.parametrize("scene_id", EXPECTED_SCENE_IDS)
def test_blend_file_exists(scene_id):
    blend_path = SCENES_DIR / f"{scene_id}.blend"
    assert blend_path.is_file(), f"missing {blend_path}"


@pytest.mark.parametrize("scene_id", EXPECTED_SCENE_IDS)
def test_manifest_sha256_matches_committed_blend(manifest, scene_id):
    entry = manifest["scenes"][scene_id]
    blend_path = REPO_ROOT / entry["blend_path"]
    assert blend_path.is_file(), f"manifest references missing file {blend_path}"
    assert _sha256(blend_path) == entry["sha256"], (
        f"{scene_id}.blend on disk does not match the SHA-256 pinned in "
        f"manifest.json - re-export (harness.py --export-blend) and re-commit "
        f"both together")


@pytest.mark.parametrize("scene_id", EXPECTED_SCENE_IDS)
def test_manifest_records_pinned_settings(manifest, scene_id):
    settings = manifest["scenes"][scene_id]["settings"]
    assert settings["res_x"] > 0 and settings["res_y"] > 0
    assert settings["samples"] == 64  # task-pinned spp for all three scenes


@pytest.mark.parametrize("scene_id", EXPECTED_SCENE_IDS)
def test_manifest_records_triangle_count(manifest, scene_id):
    entry = manifest["scenes"][scene_id]
    assert isinstance(entry["triangle_count"], int) and entry["triangle_count"] > 0


@pytest.mark.parametrize("scene_id", EXPECTED_SCENE_IDS)
def test_manifest_records_node_ids(manifest, scene_id):
    entry = manifest["scenes"][scene_id]
    assert entry["node_ids"], f"{scene_id} manifest entry has an empty node_ids list"


def test_hdri_exterior_hair_has_curves_geometry(manifest):
    entry = manifest["scenes"]["hdri_exterior_hair"]
    assert entry["curve_count"] >= 2000
    assert entry["object_counts"].get("CURVES", 0) >= 1


def test_material_zoo_has_texture_nodes(manifest):
    node_ids = set(manifest["scenes"]["material_zoo"]["node_ids"])
    assert "ShaderNodeTexChecker" in node_ids
    assert "ShaderNodeTexImage" in node_ids
    assert "ShaderNodeNormalMap" in node_ids


def test_hdri_exterior_hair_has_environment_node(manifest):
    node_ids = set(manifest["scenes"]["hdri_exterior_hair"]["node_ids"])
    assert "ShaderNodeTexEnvironment" in node_ids

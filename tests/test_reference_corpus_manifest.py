# -*- coding: utf-8 -*-
"""pkg259 Phase 1 - reference-corpus manifest integrity (design doc Sec 4.4).

Covers the two scenes that exist this phase (``materials_hall``,
``textures_mapping``). The Blender-dependent tests skip cleanly when Blender
5.2 is absent (mirrors ``tests/test_dev_loop_smoke.py``'s local-host-gate
pattern) so CI, which has no Blender, stays green; the pure tests always run.

The full-corpus ``test_zero_uncovered_supported_or_approximated`` (every
matrix row proven, across all seven families) is Phase 4 -- deliberately not
added here, per the pkg259p1 lane brief.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CORPUS_DIR = REPO_ROOT / "benchmarks" / "reference_corpus"
SCENES_DIR = CORPUS_DIR / "scenes"
MANIFEST_PATH = SCENES_DIR / "manifest.json"
MATRIX_PATH = REPO_ROOT / "docs" / "blender_parity" / "coverage_matrix.json"
ALLOCATION_SCRIPT = REPO_ROOT / ".astroray_plan" / "docs" / "pkg259-phase0" / "build_allocation_table.py"

PHASE1_FAMILIES = ("materials_hall", "textures_mapping")

BLENDER = Path("C:/Program Files/Blender Foundation/Blender 5.2/blender.exe")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def manifest() -> dict:
    if not MANIFEST_PATH.is_file():
        pytest.skip(f"corpus manifest not found at {MANIFEST_PATH} - run build_corpus.py")
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def matrix_rows() -> list[dict]:
    return json.loads(MATRIX_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def assign_map():
    import importlib.util
    spec = importlib.util.spec_from_file_location("pkg259_allocation_test", ALLOCATION_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ASSIGN


# --------------------------------------------------------------------------- #
# Blender-dependent (skip cleanly without Blender 5.2)
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("family", PHASE1_FAMILIES)
def test_every_blend_reopens_and_sha_matches(manifest, family):
    if not BLENDER.exists():
        pytest.skip("Blender 5.2 not installed - local-host gate")
    entry = manifest["scenes"].get(family)
    if entry is None:
        pytest.skip(f"{family} not yet in manifest")
    blend_path = REPO_ROOT / entry["blend_path"]
    assert blend_path.is_file(), f"manifest references missing file {blend_path}"
    assert _sha256(blend_path) == entry["sha256"], (
        f"{family}.blend on disk does not match the SHA-256 pinned in "
        f"manifest.json - re-run build_corpus.py and re-commit both together")
    assert entry["reopen_verified"] is True

    script = f"""
import bpy
bpy.ops.wm.open_mainfile(filepath=r'{blend_path}')
scene = bpy.context.scene
assert scene.camera is not None, "no camera after reopen"
print("PKG259_REOPEN_OK")
"""
    proc = subprocess.run(
        [str(BLENDER), "-b", "--factory-startup", "--python-expr", script],
        capture_output=True, text=True, timeout=120,
    )
    assert "PKG259_REOPEN_OK" in proc.stdout, (
        f"reopen failed for {family}:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")


@pytest.mark.parametrize("family", PHASE1_FAMILIES)
def test_manifest_node_ids_match_file(manifest, family):
    if not BLENDER.exists():
        pytest.skip("Blender 5.2 not installed - local-host gate")
    entry = manifest["scenes"].get(family)
    if entry is None:
        pytest.skip(f"{family} not yet in manifest")
    blend_path = REPO_ROOT / entry["blend_path"]

    script = f"""
import bpy, json
bpy.ops.wm.open_mainfile(filepath=r'{blend_path}')
scene = bpy.context.scene
node_ids = set()
for mat in bpy.data.materials:
    if mat.use_nodes and mat.node_tree:
        node_ids.update(n.bl_idname for n in mat.node_tree.nodes)
if scene.world and scene.world.use_nodes and scene.world.node_tree:
    node_ids.update(n.bl_idname for n in scene.world.node_tree.nodes)
print("PKG259_NODE_IDS " + json.dumps(sorted(node_ids)))
"""
    proc = subprocess.run(
        [str(BLENDER), "-b", "--factory-startup", "--python-expr", script],
        capture_output=True, text=True, timeout=120,
    )
    marker = "PKG259_NODE_IDS "
    line = next((l for l in proc.stdout.splitlines() if l.startswith(marker)), None)
    assert line is not None, f"no node-id report for {family}:\n{proc.stdout}\n{proc.stderr}"
    actual = set(json.loads(line[len(marker):]))
    assert actual == set(entry["node_ids"]), (
        f"{family} manifest node_ids drifted from the committed .blend "
        f"(missing from manifest: {actual - set(entry['node_ids'])}, "
        f"stale in manifest: {set(entry['node_ids']) - actual})")


# --------------------------------------------------------------------------- #
# Pure tests (no Blender needed)
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("family", PHASE1_FAMILIES)
def test_family_declared_features_present_in_scene(manifest, family):
    entry = manifest["scenes"].get(family)
    if entry is None:
        pytest.skip(f"{family} not yet in manifest")
    node_ids = set(entry["node_ids"])
    for tag in entry["feature_tags"]:
        assert tag["bl_idname"] in node_ids, (
            f"{family} claims coverage for {tag['bl_idname']}/{tag['socket_or_prop']} "
            f"but that node type never appears in the scene's node_ids")


def test_phase1_families_cover_their_allocated_rows(manifest, matrix_rows, assign_map):
    """Every SUPPORTED/APPROXIMATED row the allocation table assigns to a
    Phase-1 family appears in that scene's feature_tags; every DROPPED-SILENT
    row is either gap-carded in feature_tags or listed in the README's gap
    registry (docs/... Sec 4.4's acceptance test, Phase-1-scoped per the lane
    brief: only the two families that exist this phase)."""
    readme_text = (CORPUS_DIR / "README.md").read_text(encoding="utf-8")
    gap_registry_path = SCENES_DIR / "gap_registry.json"
    gap_registry = {}
    if gap_registry_path.is_file():
        gap_registry = json.loads(gap_registry_path.read_text(encoding="utf-8"))

    for family in PHASE1_FAMILIES:
        entry = manifest["scenes"].get(family)
        if entry is None:
            pytest.skip(f"{family} not yet in manifest")
        tagged = {(t["bl_idname"], t["socket_or_prop"]) for t in entry["feature_tags"]
                  if not t["gap_card"]}
        gap_carded = {(t["bl_idname"], t["socket_or_prop"]) for t in entry["feature_tags"]
                      if t["gap_card"]}

        family_rows = [r for r in matrix_rows
                       if assign_map[(r["category"], r["feature"])][0] == family]
        missing_required = [
            r for r in family_rows
            if r["classification"] in ("SUPPORTED", "APPROXIMATED")
            and (r["bl_idname"], r["socket_or_prop"]) not in tagged
        ]
        assert not missing_required, (
            f"{family}: {len(missing_required)} SUPPORTED/APPROXIMATED row(s) "
            f"not covered: {missing_required[:5]}...")

        dropped_rows = [r for r in family_rows if r["classification"] == "DROPPED-SILENT"]
        family_gap_pairs = {(r["bl_idname"], r["socket_or_prop"])
                             for r in gap_registry.get(family, [])}
        uncovered_dropped = [
            r for r in dropped_rows
            if (r["bl_idname"], r["socket_or_prop"]) not in gap_carded
            and (r["bl_idname"], r["socket_or_prop"]) not in family_gap_pairs
        ]
        # Every DROPPED-SILENT row must at minimum be traceable to its owning
        # node in the README (gap_registry.json is generated straight from
        # the README's source data, so also sanity-check the node name shows
        # up in the prose registry as a defence against a stale README).
        for r in uncovered_dropped:
            assert r["feature"] in readme_text or r["bl_idname"] in readme_text, (
                f"{family}: DROPPED-SILENT row {r['bl_idname']}/{r['socket_or_prop']} "
                f"is neither gap-carded nor in the README gap registry")


@pytest.mark.parametrize("family", PHASE1_FAMILIES)
def test_crops_are_valid_normalised_rects(manifest, family):
    """``crops`` (Phase-1-polish, design doc Sec 1.1) is generated by each
    scene builder's own camera/FOV math (``scene_library._crop_rect``) and
    cross-checked here for the shape ``report_tools.py`` and a future
    ``coverage_report.py`` rely on: every entry a 4-tuple
    ``[x0, y0, x1, y1]`` inside [0, 1] with x0 < x1 and y0 < y1."""
    entry = manifest["scenes"].get(family)
    if entry is None:
        pytest.skip(f"{family} not yet in manifest")
    crops = entry.get("crops", {})
    assert crops, f"{family}: manifest has no crops entries"
    for name, rect in crops.items():
        assert len(rect) == 4, f"{family}/{name}: crop rect must be [x0, y0, x1, y1], got {rect}"
        x0, y0, x1, y1 = rect
        for v in (x0, y0, x1, y1):
            assert 0.0 <= v <= 1.0, f"{family}/{name}: crop coordinate {v} outside [0, 1]"
        assert x0 < x1, f"{family}/{name}: crop x0 >= x1 ({rect})"
        assert y0 < y1, f"{family}/{name}: crop y0 >= y1 ({rect})"


def test_report_tools_crops_match_manifest_alcoves():
    """``report_tools.crop_image`` (the Phase-1-polish per-alcove crop path)
    correctly slices a normalised rect out of an image, using materials_hall's
    real manifest rects rather than a synthetic example."""
    pytest.importorskip("PIL")
    from PIL import Image

    sys.path.insert(0, str(REPO_ROOT))
    from benchmarks.reference_corpus import report_tools

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    crops = manifest["scenes"]["materials_hall"]["crops"]
    im = Image.new("RGB", (960, 176), (0, 0, 0))
    for name, rect in crops.items():
        cropped = report_tools.crop_image(im, rect)
        x0, y0, x1, y1 = rect
        expected_w = round(x1 * im.width) - round(x0 * im.width)
        expected_h = round(y1 * im.height) - round(y0 * im.height)
        assert cropped.size == (expected_w, expected_h), (
            f"crop {name}: expected {(expected_w, expected_h)}, got {cropped.size}")

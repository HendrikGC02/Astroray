"""pkg176 Stage 0 — validate the settings mapping table's shape and coverage.

CPU/collection-level only: this exercises the inert data module
``blender_addon/settings_map.py`` and cross-checks it against the pkg119 Phase A
coverage matrix. No Blender, no engine, no GPU.

It also mechanically enforces the two Route-2 hard rules the table itself must
honour (dcc-integration-decision-2026-08 §6): the translator-side data module
must NOT import ``bpy`` (rule 1), and its neutral targets must not name Blender
datablocks (rule 2, spot-checked).
"""

import json
import pathlib

import pytest

_ADDON = pathlib.Path(__file__).resolve().parents[1] / "blender_addon"
_MATRIX = pathlib.Path(__file__).resolve().parents[1] / "docs" / "blender_parity" / "coverage_matrix.json"


def _load_module():
    """Import settings_map.py directly from blender_addon/ without importing the
    addon package (which would pull in bpy)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "pkg176_settings_map", _ADDON / "settings_map.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sm = _load_module()


def test_table_nonempty():
    assert len(sm.MAPPING) >= 60, "steering-wheel table should cover the core native surface"


def test_every_row_shape_valid():
    for e in sm.MAPPING:
        assert e.status in sm.STATUS_VALUES, f"{e.native_prop}: bad status {e.status!r}"
        assert e.pkg119a in sm.PKG119A_VALUES, f"{e.native_prop}: bad pkg119a {e.pkg119a!r}"
        assert e.category, f"{e.native_prop}: empty category"
        # A row must name at least one side of the correspondence.
        assert e.native_prop or e.cycles_path or e.custom_prop, "row names nothing"
        # astroray-only rows have no direct/approximated engine claim of a native
        # 1:1; every non-dropped, non-astroray row must name a neutral target.
        if e.status in ("direct", "approximated"):
            assert e.neutral_param and e.neutral_param != "(none)", (
                f"{e.native_prop}: {e.status} row must name a neutral engine target"
            )
        if e.status == "dropped":
            assert e.neutral_param == "(none)", (
                f"{e.native_prop}: dropped row must have no engine target"
            )


def test_source_has_no_bpy_import():
    """Route-2 rule 1: the translator-side data module must not import bpy."""
    src = (_ADDON / "settings_map.py").read_text(encoding="utf-8")
    for line in src.splitlines():
        stripped = line.strip()
        assert not stripped.startswith("import bpy"), "settings_map must not import bpy"
        assert not stripped.startswith("from bpy"), "settings_map must not import bpy"


def test_neutral_targets_are_host_neutral():
    """Route-2 rule 2 (spot-check): neutral targets name engine session surface
    (Renderer setters / render() args / neutral phrases), never a bpy datablock."""
    for e in sm.MAPPING:
        if e.status in ("direct", "approximated"):
            assert "scene.cycles" not in e.neutral_param, e.native_prop
            assert "custom_raytracer" not in e.neutral_param, e.native_prop


def test_status_counts_reported(capsys):
    counts = {s: len(sm.by_status(s)) for s in sm.STATUS_VALUES}
    total = sum(counts.values())
    assert total == len(sm.MAPPING)
    print(f"pkg176 Stage-0 mapping status counts: {counts} (total {total})")


@pytest.mark.skipif(not _MATRIX.exists(), reason="pkg119-A coverage matrix not present")
def test_render_settings_fully_covered_vs_pkg119a():
    """Every allow-listed render_settings row in the pkg119-A matrix must be
    represented in the mapping table (the render/sampling/light_paths/film/
    denoising steering wheel). This is the coverage contract for Stage 1."""
    matrix = json.loads(_MATRIX.read_text(encoding="utf-8"))
    native_props_in_map = {e.native_prop for e in sm.MAPPING}

    missing = []
    for row in matrix:
        if row.get("category") != "render_settings":
            continue
        prop = row.get("socket_or_prop")
        if prop not in native_props_in_map:
            missing.append(prop)

    assert not missing, f"render_settings props not in mapping table: {missing}"


@pytest.mark.skipif(not _MATRIX.exists(), reason="pkg119-A coverage matrix not present")
def test_settings_natives_covered_vs_pkg119a():
    """Camera / light / world native props from pkg119-A are represented too."""
    matrix = json.loads(_MATRIX.read_text(encoding="utf-8"))
    native_props_in_map = {e.native_prop for e in sm.MAPPING}

    missing = []
    for row in matrix:
        if row.get("category") not in ("camera", "light", "world"):
            continue
        prop = row.get("socket_or_prop")
        if prop not in native_props_in_map:
            missing.append((row.get("category"), prop))

    assert not missing, f"camera/light/world props not in mapping table: {missing}"

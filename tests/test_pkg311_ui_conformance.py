"""pkg311: Blender-native UI conformance (headless Blender).

The host pytest process never imports bpy. It spawns one
``blender --background --factory-startup`` running tests/pkg311_ui_leg.py
(addon registered from the source tree; no engine .pyd needed, this is UI only)
and asserts on the JSON the leg writes. Skipped when Blender is not installed.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
LEG = REPO / "tests" / "pkg311_ui_leg.py"


def _find_blender() -> str | None:
    env = os.environ.get("BLENDER_EXE")
    if env and Path(env).exists():
        return env
    found = shutil.which("blender")
    if found:
        return found
    base = Path("C:/Program Files/Blender Foundation")
    if base.exists():
        cands = sorted(base.glob("Blender 5.*/blender.exe"), reverse=True)
        if cands:
            return str(cands[0])
    return None


@pytest.fixture(scope="module")
def leg(tmp_path_factory):
    exe = _find_blender()
    if exe is None:
        pytest.skip("Blender 5.x not installed")
    out = tmp_path_factory.mktemp("pkg311") / "leg.json"
    proc = subprocess.run(
        [exe, "--background", "--factory-startup", "--python", str(LEG), "--", str(out)],
        capture_output=True, text=True, timeout=300)
    assert out.exists(), f"leg wrote no results\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}"
    return json.loads(out.read_text(encoding="utf-8"))


def _ok(leg, name):
    r = leg[name]
    assert r["ok"], r.get("error")
    return r["data"]


def test_engine_registers(leg):
    assert _ok(leg, "engine_selected") == "CUSTOM_RAYTRACER"


def test_every_astroray_property_has_a_description(leg):
    d = _ok(leg, "property_descriptions")
    assert d["checked"] > 60 and d["structs"] >= 5  # guard against a vacuous pass
    assert d["missing"] == []


def test_add_menu_is_categorised_and_resolves(leg):
    d = _ok(leg, "add_menu_categories")
    assert d["top_ops"] == ["AstrorayOutputNode"]
    assert [label for _mt, label in d["menus"]] == [
        "Spectral Sources", "Spectral Modifiers", "Response", "Hints"]
    assert d["unresolved"] == []
    # every registered native node type is reachable from the menu
    assert d["n_types"] == d["n_registered_node_types"]


def test_black_hole_subpanels(leg):
    d = _ok(leg, "black_hole_subpanels")
    assert set(d["parents"].values()) == {"OBJECT_PT_astroray_black_hole"}
    assert sorted(d["parents"]) == sorted(
        f"OBJECT_PT_astroray_black_hole_{s}"
        for s in ("mass_spin", "disk", "adaf", "jet", "observer"))
    assert d["not_drawn"] == []  # the split lost no control
    assert d["mass_spin_props"] == ["mass", "spin"]


def test_black_hole_and_sampling_presets_round_trip(leg):
    d = _ok(leg, "presets_round_trip")
    assert d["bh_files"] == ["M87_star.py", "Sgr_A_star.py", "Stellar_mass_HMXB_Cyg_X-1.py"]
    for name, res in d["applied"].items():
        assert res["ret"] == ["FINISHED"], name
        assert res["match"], (name, res["got"])
    assert d["unresolved"] == [] and d["render_unresolved"] == []
    assert d["render_files"] == ["Draft.py", "Final.py", "Preview.py"]
    assert d["draft"] == [16, 8] and d["final"] == [1024, 64]


def test_preset_files_cite_a_doi():
    for f in (REPO / "blender_addon" / "presets" / "astroray_black_hole").glob("*.py"):
        assert "doi:10." in f.read_text(encoding="utf-8"), f.name


def test_node_status_line(leg):
    d = _ok(leg, "node_status_line")
    assert d["unwired"] == [["Unwired: no effect", "INFO"]]
    assert d["wired"] == []  # used by the converter -> no status line
    assert d["behind_mix"][0][1] == "ERROR"
    # The UI's reachable set is exactly the converter's dispatch set.
    assert d["status_idnames"] == d["converter_idnames"]


def test_unregister_is_clean(leg):
    assert _ok(leg, "unregister_clean")["left"] == []


def test_presets_packaged():
    text = (REPO / "scripts" / "build" / "build_blender_addon.py").read_text(encoding="utf-8")
    assert '"presets"' in text
    assert (REPO / "blender_addon" / "presets" / "astroray_black_hole" / "M87_star.py").exists()

"""Batch A item 1 (owner-approved 2026-09-11) — Spot/Point IES export.

Checks:
1. Stub-bpy: `_resolve_ies_path` finds the ShaderNodeTexIES node wired into the
   light node tree. INTERNAL text -> a temp .ies file whose content matches the
   datablock; EXTERNAL -> the resolved filepath; a disconnected node is ignored
   (mirrors Cycles).
2. Engine: an IES profile actually modulates a SPOT light's floor pattern — the
   asymmetric wall-washer (peaks off-nadir) dims the nadir vs a plain cone.
3. Normalization constant: the Cycles candela->Watt factor (util/ies.cpp) is
   4*pi/177.83; recorded here as the parity reference for our peak-normalized
   IESProfile (see .astroray_plan/docs/ies-normalization-research.md).
"""
import math
import os
import sys
import types
from pathlib import Path

import numpy as np
import pytest

from _batch_a_stub import load_addon


REPO_ROOT = Path(__file__).resolve().parents[1]
_BP = REPO_ROOT / "benchmarks" / "blender_parity"
if str(_BP) not in sys.path:
    sys.path.insert(0, str(_BP))


def _out_socket(linked):
    return types.SimpleNamespace(is_linked=linked)


def _ies_node(mode, text=None, filepath="", linked=True):
    ies_db = None
    if text is not None:
        ies_db = types.SimpleNamespace(name="StudioIES", as_string=lambda: text)
    return types.SimpleNamespace(
        type='TEX_IES', mode=mode, filepath=filepath, ies=ies_db,
        outputs=[_out_socket(linked)])


def _light_with_nodes(*nodes):
    node_tree = types.SimpleNamespace(nodes=list(nodes))
    return types.SimpleNamespace(node_tree=node_tree)


# --------------------------------------------------------------------------- #
# 1. Stub-bpy resolution.
# --------------------------------------------------------------------------- #
def test_internal_ies_written_to_temp_file(monkeypatch):
    addon = load_addon(monkeypatch, "ies_internal")
    engine = addon.CustomRaytracerRenderEngine()
    content = "IESNA:LM-63-2002\nTILT=NONE\n1 -1 1.0 2 1 1 2 0 0 0\n1 1 1\n0 90\n0\n1.0 0.5\n"
    light = _light_with_nodes(_ies_node('INTERNAL', text=content))
    path = engine._resolve_ies_path(light)
    assert path and os.path.exists(path), path
    assert path.lower().endswith(".ies")
    with open(path, encoding="utf-8") as fh:
        assert fh.read() == content
    # Stable name keyed by content hash: a second call returns the same path.
    assert engine._resolve_ies_path(light) == path


def test_external_ies_returns_abspath(monkeypatch):
    addon = load_addon(monkeypatch, "ies_external")
    engine = addon.CustomRaytracerRenderEngine()
    light = _light_with_nodes(_ies_node('EXTERNAL', filepath="/abs/fixture.ies"))
    # bpy.path.abspath is stubbed as identity.
    assert engine._resolve_ies_path(light) == "/abs/fixture.ies"


def test_disconnected_ies_is_ignored(monkeypatch):
    addon = load_addon(monkeypatch, "ies_disc")
    engine = addon.CustomRaytracerRenderEngine()
    light = _light_with_nodes(_ies_node('INTERNAL', text="x", linked=False))
    assert engine._resolve_ies_path(light) == ""


def test_no_node_tree_returns_empty(monkeypatch):
    addon = load_addon(monkeypatch, "ies_none")
    engine = addon.CustomRaytracerRenderEngine()
    light = types.SimpleNamespace(node_tree=None)
    assert engine._resolve_ies_path(light) == ""


# --------------------------------------------------------------------------- #
# 2. Engine: IES modulates a SPOT booth.
# --------------------------------------------------------------------------- #
def _spot_floor_mean(ies_file):
    import base_helpers as bh
    r = bh.create_renderer()
    r.set_seed(4242)
    floor = r.create_material('lambertian', [0.8, 0.8, 0.8], {})
    # 4x4 floor at y=-1 (two triangles).
    r.add_triangle([-2, -1, -2], [2, -1, -2], [2, -1, 2], floor)
    r.add_triangle([-2, -1, -2], [2, -1, 2], [-2, -1, 2], floor)
    emission = {'mode': 'rgb', 'color': [1.0, 1.0, 1.0]}
    r.add_spot_light_dedicated([0, 2, 0], [0, -1, 0], 0.2, 0.9,
                               emission, 60.0, 0.0, ies_file, 0, 0)
    r.set_background_color([0.0, 0.0, 0.0])
    # Top-down camera onto the floor.
    bh.setup_camera(r, look_from=[0, 3, 0.001], look_at=[0, -1, 0],
                    vup=[0, 0, -1], vfov=60, width=80, height=80)
    img = bh.render_image(r, samples=64, max_depth=3, apply_gamma=False)
    cy, cx = img.shape[0] // 2, img.shape[1] // 2
    centre = float(np.mean(img[cy - 6:cy + 6, cx - 6:cx + 6]))
    total = float(np.mean(img))
    return centre, total


@pytest.mark.serial
def test_ies_changes_spot_floor_pattern(tmp_path):
    from scene_library import _ies_wall_washer_lm63
    ies_path = tmp_path / "wall_washer.ies"
    ies_path.write_text(_ies_wall_washer_lm63(), encoding="utf-8")

    c_plain, t_plain = _spot_floor_mean("")
    c_ies, t_ies = _spot_floor_mean(str(ies_path))

    # The wall-washer peaks off-nadir (v0=65 deg), so the nadir/centre must be
    # relatively dimmer under IES than under the plain uniform cone.
    assert t_plain > 0 and t_ies > 0, (t_plain, t_ies)
    ratio_plain = c_plain / t_plain
    ratio_ies = c_ies / t_ies
    assert ratio_ies < ratio_plain, (ratio_plain, ratio_ies)


# --------------------------------------------------------------------------- #
# 3. Normalization constant (parity reference).
# --------------------------------------------------------------------------- #
def test_cycles_ies_candela_to_watt_constant():
    # Cycles util/ies.cpp: factor *= 0.0706650768394 == 4*pi / 177.83
    # (D65 luminous efficacy 177.83 lm/W; the 4*pi converts Watt/sr -> Watt).
    assert 4.0 * math.pi / 177.83 == pytest.approx(0.0706650768394, abs=1e-12)

"""#1038 - the Blender Glass BSDF tints BOTH lobes by Color (Cycles
svm/closure.h GGX_GLASS: fresnel->tint = {color, color}), not Principled's
specular_tint / sqrt(base_color) split.

The addon encodes Glass into the native 'principled' params as
specular_tint = Color, base_color = Color^2 (see
.astroray_plan/docs/issue1038-glass-tint-research.md). Two layers:

  1. addon mapping (stub bpy, no engine): the recorded create_material args;
  2. engine truth (CPU, needs astroray): the recorded params rendered as a
     smooth sphere in a white furnace must match the analytic slab series
     L = cF + c^2 (1-F)^2 / (1 - cF) at the centre (R = cF, T = c(1-F) per
     interface). Before the fix (reflection untinted, transmission sqrt(c)) the red
     channel read F + c(1-F) = 0.807 vs 0.641 for c = 0.8.
"""

from __future__ import annotations

import numpy as np
import pytest

from runtime_setup import configure_test_imports

configure_test_imports()

from test_pkg119c_degradation import (  # noqa: E402
    _Node, _RecordingRenderer, _Socket, _engine, _load_blender_addon)

try:
    import astroray  # noqa: E402
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

# Mild tint: the spectral path upsamples Color per interface, so a SATURATED colour
# (e.g. 0.6) deviates from the RGB product c^2 by several % (JH nonlinearity, inherent
# to spectral rendering; uniform-grey tints match to <0.3 %).
COLOR = (0.8, 0.9, 1.0)
IOR = 1.45


def _glass_create_args(monkeypatch, color, native=True):
    addon = _load_blender_addon(monkeypatch)
    engine = _engine(addon)
    engine._use_native_principled_flag = native
    renderer = _RecordingRenderer()
    glass = _Node(ntype="BSDF_GLASS", bl_idname="ShaderNodeBsdfGlass",
                  inputs={
                      'Color': _Socket(default=(*color, 1.0)),
                      'Roughness': _Socket(default=0.0),
                      'IOR': _Socket(default=IOR),
                  })
    engine.convert_shader_node(glass, renderer, node_tree=None)
    assert len(renderer.created_materials) == 1
    return renderer.created_materials[0]


def test_glass_native_encoding_is_color_on_both_lobes(monkeypatch):
    mat_type, base, params = _glass_create_args(monkeypatch, COLOR)
    assert mat_type == "principled"
    # transmission tint = sqrt(base_color) must equal Color; reflection tint = specular_tint
    assert np.allclose(np.sqrt(base), COLOR, atol=1e-6)
    assert np.allclose(params["specular_tint"], COLOR, atol=1e-6)
    assert params["transmission_weight"] == 1.0


def test_glass_legacy_disney_route_unchanged(monkeypatch):
    # The non-native fallback is preserved byte-for-byte: untouched colour.
    spec_color = [0.8, 0.9, 1.0]
    addon = _load_blender_addon(monkeypatch)
    engine = _engine(addon)
    engine._use_native_principled_flag = False
    renderer = _RecordingRenderer()
    glass = _Node(ntype="BSDF_GLASS", bl_idname="ShaderNodeBsdfGlass",
                  inputs={'Color': _Socket(default=(*spec_color, 1.0)),
                          'Roughness': _Socket(default=0.0),
                          'IOR': _Socket(default=IOR)})
    engine.convert_shader_node(glass, renderer, node_tree=None)
    _, base, params = renderer.created_materials[0]
    assert base == spec_color
    assert "specular_tint" not in params


def _fresnel0(ior):
    return ((ior - 1.0) / (ior + 1.0)) ** 2


@pytest.mark.skipif(not AVAILABLE, reason="astroray not built")
def test_glass_sphere_centre_matches_cycles_tint_series(monkeypatch):
    _, base, params = _glass_create_args(monkeypatch, COLOR)
    params = {k: v for k, v in params.items()
              if k in ("transmission_weight", "ior", "roughness", "specular_tint")}
    r = astroray.Renderer()
    r.set_background_color([1.0, 1.0, 1.0])
    r.set_integrator("path_tracer")
    mid = r.create_material("principled", base, params)
    r.add_sphere([0.0, 0.0, 0.0], 1.0, mid)
    r.setup_camera([0, 0, 4], [0, 0, 0], [0, 1, 0], 40.0, 1.0, 0.0, 4.0, 64, 64)
    r.set_seed(11)
    img = np.asarray(r.render(256, 32, None, False), dtype=np.float32).reshape(64, 64, 3)
    centre = img[28:36, 28:36].reshape(-1, 3).mean(axis=0)

    f = _fresnel0(IOR)
    c = np.array(COLOR)
    expected = c * f + c * c * (1.0 - f) ** 2 / (1.0 - c * f)
    ratio = centre / expected
    assert np.all(np.abs(ratio - 1.0) < 0.03), (centre, expected, ratio)

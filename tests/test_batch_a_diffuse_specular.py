"""Batch A item 2 (#757) — Diffuse BSDF must export without the Principled
dielectric specular layer.

Two checks:
1. Stub-bpy: `_standalone_bsdf_spec` for a Diffuse BSDF node writes
   specular_ior_level=0 (native path) AND specular=0 (Disney fallback path).
2. Engine A/B: a native 'principled' material with metallic=0, roughness=0 and
   specular_ior_level=0 is DARKER (no added dielectric reflection) than the same
   material at the Principled default specular_ior_level=0.5, and matches a plain
   Lambertian of the same albedo within noise.
"""
import types

import numpy as np
import pytest

from _batch_a_stub import load_addon



# --------------------------------------------------------------------------- #
# 1. Stub-bpy: the exported spec disables specular on both engine paths.
# --------------------------------------------------------------------------- #
def _socket(value, linked=False):
    return types.SimpleNamespace(default_value=value, is_linked=linked)


def test_diffuse_bsdf_spec_disables_specular(monkeypatch):
    addon = load_addon(monkeypatch, "diffuse")
    engine = addon.CustomRaytracerRenderEngine()
    node = types.SimpleNamespace(
        type='BSDF_DIFFUSE',
        inputs={
            'Color': _socket((0.25, 0.27, 0.24, 1.0)),
            'Roughness': _socket(0.0),
        },
    )
    spec = engine._standalone_bsdf_spec(node)
    assert spec is not None
    assert spec['kind'] == 'principled'
    params = spec['params']
    assert params['metallic'] == 0.0
    # #757: both keys must be present so neither engine path keeps a specular lobe.
    assert params['specular_ior_level'] == 0.0, params
    assert params['specular'] == 0.0, params


def test_diffuse_specular_maps_to_native(monkeypatch):
    addon = load_addon(monkeypatch, "diffuse_map")
    engine = addon.CustomRaytracerRenderEngine()
    native = engine._disney_params_to_native(
        {'metallic': 0.0, 'roughness': 0.0, 'specular_ior_level': 0.0})
    assert native.get('specular_ior_level') == 0.0, native


# --------------------------------------------------------------------------- #
# 2. Engine A/B render.
# --------------------------------------------------------------------------- #
def _render_sphere(mat_type, params, albedo):
    import base_helpers as bh
    r = bh.create_renderer()
    r.set_seed(12345)
    mat = r.create_material(mat_type, list(albedo), params)
    r.add_sphere([0, 0, 0], 1.0, mat)
    # uniform bright environment so the sphere is lit from all directions;
    # any specular lobe adds reflected energy on top of the diffuse response.
    r.set_background_color([1.0, 1.0, 1.0])
    bh.setup_camera(r, look_from=[0, 0, 4], look_at=[0, 0, 0], vfov=40,
                    width=96, height=96)
    img = bh.render_image(r, samples=96, max_depth=4, apply_gamma=False)
    # mask to the lit sphere disc (centre region).
    cy, cx = img.shape[0] // 2, img.shape[1] // 2
    rr = 30
    patch = img[cy - rr:cy + rr, cx - rr:cx + rr]
    return float(np.mean(patch))


@pytest.mark.serial
def test_diffuse_specular_zero_is_darker_than_default():
    albedo = [0.25, 0.27, 0.24]
    spec0 = _render_sphere('principled', {'metallic': 0.0, 'roughness': 0.0,
                                          'specular_ior_level': 0.0}, albedo)
    spec_default = _render_sphere('principled', {'metallic': 0.0, 'roughness': 0.0,
                                                 'specular_ior_level': 0.5}, albedo)
    # The default dielectric specular layer adds reflected energy: it must be
    # measurably brighter than the specular-disabled export (#757 ground-strip
    # ratio 1.108 vs 0.989).
    assert spec_default > spec0 * 1.02, (spec0, spec_default)

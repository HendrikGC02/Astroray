"""#1099 - a Cycles Emission shader emits from BOTH faces; Astroray's 'light' did not.

textures_mapping floats Emission proof cards 0.55 above the table, facing up.
Cycles lights the table below them (the Emission closure ignores the face); the
engine's 'light'/'emission' material is front-face-only, so the table around the
checker card read 0.84/0.91/0.94 of Cycles on CPU and GPU. Rendering the same
scene with every card flipped made Astroray match Cycles (floor 0.0283 vs 0.0283)
while Cycles itself was unchanged.

Fix: the addon lowers an Emission node to 'light' with ``two_sided=1`` (a one-sided
emitter in Cycles needs a Mix with Geometry > Backfacing); the plugin default and
the direct 'light' API stay front-face-only (tests/test_pkg294 etc. rely on it).

Engine tests: a floor lit only by an emitter quad whose FRONT faces away from it.
Cycles manual / source: Emission shader is two-sided; "Front/Back/Front & Back"
emission-sampling options only steer light-tree sampling.
"""
import numpy as np
import pytest

from tests.test_issue762_emission_texture import (
    _checker_node,
    _emission_node,
    _load_blender_addon,
    _RecordingRenderer,
)


@pytest.fixture(scope="module")
def astroray_mod():
    try:
        import astroray
        return astroray
    except ImportError as e:
        pytest.skip(f"astroray module not available: {e}")


def _floor_mean(mod, params, emitter_faces_floor, textured=False, gpu=False, spp=128):
    r = mod.Renderer()
    if gpu:
        r.set_integrator("path_tracer")
        r.set_use_gpu(True)
    else:
        r.set_integrator_param("enable_nee", 1)
        r.set_integrator("multiwavelength_path_tracer")
    white = r.create_material("lambertian", [0.8, 0.8, 0.8], {})
    params = dict(params)
    if textured:
        img = np.tile(np.array([1.0, 0.5, 0.25], dtype=np.float32), (4, 4, 1))
        r.load_texture("emit_1099", img, 4, 4, "UV")
        params["texture"] = "emit_1099"
    light = r.create_material("light", [1.0, 1.0, 1.0], params)
    e = 4.0
    r.add_triangle([-e, -1, -e], [e, -1, -e], [e, -1, e], white)
    r.add_triangle([-e, -1, -e], [e, -1, e], [-e, -1, e], white)
    le = 1.2
    quad = [([-le, 1.5, -le], [le, 1.5, -le], [le, 1.5, le]),
            ([-le, 1.5, -le], [le, 1.5, le], [-le, 1.5, le])]
    for a, b, c in quad:   # this winding faces DOWN (the floor); reversed faces up
        if emitter_faces_floor:
            r.add_triangle(a, b, c, light)
        else:
            r.add_triangle(a, c, b, light)
    r.setup_camera(look_from=[0, 0.5, 0.01], look_at=[0, -1, 0], vup=[0, 0, -1],
                   vfov=50, aspect_ratio=1.0, aperture=0.0, focus_dist=2.0,
                   width=64, height=64)
    px = np.asarray(r.render(spp, 6, None, False)).reshape(64, 64, 3)
    return px[24:40, 24:40].reshape(-1, 3).mean(axis=0)


@pytest.mark.cpu
@pytest.mark.parametrize("textured", [False, True])
def test_two_sided_light_lights_floor_from_its_back_face(astroray_mod, textured):
    ref = _floor_mean(astroray_mod, {"intensity": 15.0}, True, textured)
    one = _floor_mean(astroray_mod, {"intensity": 15.0}, False, textured)
    two = _floor_mean(astroray_mod, {"intensity": 15.0, "two_sided": 1.0}, False, textured)
    assert ref[0] > 1e-3, ref
    assert one[0] < 0.05 * ref[0], f"default light must stay front-face-only: {one} vs {ref}"
    np.testing.assert_allclose(two, ref, rtol=0.15, err_msg="two_sided back-face light != front-face light")


@pytest.mark.gpu
@pytest.mark.parametrize("textured", [False, True])
def test_gpu_two_sided_light_lights_floor_from_its_back_face(astroray_mod, textured):
    if not getattr(astroray_mod.Renderer(), "gpu_available", False):
        pytest.skip("CUDA not compiled / no GPU (CI has no GPU)")
    ref = _floor_mean(astroray_mod, {"intensity": 15.0}, True, textured, gpu=True)
    one = _floor_mean(astroray_mod, {"intensity": 15.0}, False, textured, gpu=True)
    two = _floor_mean(astroray_mod, {"intensity": 15.0, "two_sided": 1.0}, False, textured, gpu=True)
    assert ref[0] > 1e-3, ref
    assert one[0] < 0.05 * ref[0], f"default GPU light must stay front-face-only: {one} vs {ref}"
    np.testing.assert_allclose(two, ref, rtol=0.15)


@pytest.mark.parametrize("textured", [False, True])
def test_addon_lowers_emission_node_to_two_sided_light(monkeypatch, textured):
    addon = _load_blender_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    renderer = _RecordingRenderer()
    node = _emission_node(color_link=_checker_node() if textured else None, strength=3.0)
    spec = engine._shader_spec_from_node(node, renderer, node_tree=None)
    engine._create_material_from_shader_spec(spec, renderer)
    mat_type, _color, params = renderer.created_materials[0]
    assert mat_type == "light"
    assert params.get("two_sided") == 1.0, params

"""#988 — a native Principled with a per-texel Base Color keeps every lobe.

Before #988 the addon routed a textured Base Color through ``lambertian``
(specular / coat / metallic / roughness programs lost). The engine now carries the
texture on the Principled's own base-colour slot (``base_color_texture`` param ->
``SCALAR_BASE_COLOR``): CPU ``PrincipledPlugin::substituted()`` writes the texel
into the base colour, the GPU ``<HasProgram>`` shade block overrides a local
material copy.
"""
import numpy as np
import pytest

astroray = pytest.importorskip("astroray")

_BASE = [0.2, 0.5, 0.8]
_PARAMS = {"metallic": 0.35, "roughness": 0.3, "specular_ior_level": 0.5, "coat_weight": 0.4}


def _uniform_checker(r, name, rgb):
    # A checker whose two colours are equal is a uniform texture (any coordinate).
    r.create_procedural_texture(name, "checker", list(rgb) + list(rgb) + [4.0], "UV")


def test_uniform_texture_equals_constant_base_color():
    """Every lobe sees the texel: a uniform texture == the same constant base."""
    r = astroray.Renderer()
    _uniform_checker(r, "u988", _BASE)
    const = r.create_material("principled", _BASE, dict(_PARAMS))
    tex = r.create_material("principled", [0.9, 0.9, 0.9],
                            dict(_PARAMS, base_color_texture="u988"))
    lam = r.create_material("lambertian", [0.9, 0.9, 0.9], {"texture": "u988"})
    n = [0.0, 1.0, 0.0]
    pairs = [([0.3, 0.9, 0.1], [-0.3, 0.9, -0.1]),   # near-mirror: specular + coat
             ([0.0, 1.0, 0.0], [0.6, 0.7, 0.2]),
             ([0.8, 0.3, 0.0], [-0.7, 0.4, 0.1])]
    spec_gap = 0.0
    for wo, wi in pairs:
        a = np.array(r.eval_material(const, wo, wi, n))
        b = np.array(r.eval_material(tex, wo, wi, n))
        np.testing.assert_allclose(b, a, rtol=1e-5, atol=1e-7)
        spec_gap = max(spec_gap, float(np.abs(b - np.array(r.eval_material(lam, wo, wi, n))).max()))
    # Non-vacuity: the textured Principled is NOT the textured Lambertian.
    assert spec_gap > 0.05, spec_gap


def _scene(r, use_gpu, textured_lambertian=False):
    from base_helpers import setup_camera
    if use_gpu:
        r.set_use_gpu(True)
    r.set_seed(7)
    r.set_background_color([0.05, 0.05, 0.05])
    r.create_procedural_texture("chk988", "checker",
                                [0.9, 0.2, 0.1, 0.1, 0.3, 0.9, 4.0], "UV")
    if textured_lambertian:
        mat = r.create_material("lambertian", [0.8, 0.8, 0.8], {"texture": "chk988"})
    else:
        mat = r.create_material("principled", [0.8, 0.8, 0.8],
                                {"metallic": 1.0, "roughness": 0.25,
                                 "base_color_texture": "chk988"})
    A, B, C, D = [-1, -1, 0], [1, -1, 0], [1, 1, 0], [-1, 1, 0]
    n = [0, 0, 1]
    r.add_triangle_layers(A, B, C, mat, {"UVMap": [[0, 0], [1, 0], [1, 1]]}, n, n, n)
    r.add_triangle_layers(A, C, D, mat, {"UVMap": [[0, 0], [1, 1], [0, 1]]}, n, n, n)
    light = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 20.0})
    r.add_sphere([0.0, 0.0, 2.2], 0.35, light)
    setup_camera(r, look_from=[0, 0, 3], look_at=[0, 0, 0], vup=[0, 1, 0],
                 vfov=45, width=64, height=64)


def _has_cuda_gpu(r):
    return bool(astroray.__features__.get("cuda", False)) and bool(getattr(r, "gpu_available", False))


@pytest.mark.gpu
def test_gpu_textured_principled_parity_and_not_lambertian():
    from base_helpers import create_renderer, render_image
    rg = create_renderer()
    if not _has_cuda_gpu(rg):
        pytest.skip("No CUDA GPU")
    _scene(rg, use_gpu=True)
    gpu = render_image(rg, samples=128, max_depth=3, apply_gamma=False)
    rc = create_renderer()
    _scene(rc, use_gpu=False)
    cpu = render_image(rc, samples=128, max_depth=3, apply_gamma=False)
    rl = create_renderer()
    _scene(rl, use_gpu=True, textured_lambertian=True)
    lam = render_image(rl, samples=128, max_depth=3, apply_gamma=False)
    gm = gpu.reshape(-1, 3).mean(axis=0)
    cm = cpu.reshape(-1, 3).mean(axis=0)
    lm = lam.reshape(-1, 3).mean(axis=0)
    assert cm.mean() > 0.01 and gm.mean() > 0.01, (cm, gm)
    ratio = gm / np.maximum(cm, 1e-6)
    assert np.all((ratio > 0.85) & (ratio < 1.18)), f"CPU/GPU ratio {ratio}; cpu={cm} gpu={gm}"
    # The per-texel checker survives (red vs blue cells) on the GPU.
    assert gpu[..., 0].max() - gpu[..., 0].min() > 0.05
    # A metal is not a diffuse surface: the GPU image differs from the textured lambertian.
    assert np.abs(gm - lm).max() > 0.2 * lm.max(), (gm, lm)

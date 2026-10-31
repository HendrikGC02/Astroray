"""#1180 / #1186 -- emission on Add / Mix leaves of any type, Principled emission x alpha,
CPU ReSTIR-DI continuing through emissive surfaces that have a BSDF.

* #1180: GPU used to bake an Add / Mix tree's emission only into a closure-graph Principled
  first leaf, so Add(lambertian, emissive) / Add(glass, emissive) uploaded as the plain BSDF
  and a scene lit by such walls was black (CPU keeps the emission).
* #1186.1: Cycles applies `emission * weight` after `weight *= alpha`
  (kernel/svm/closure.h, v5.2.0); a half-transparent emissive Principled glows at half
  strength. Astroray added the full emission on both backends.
* #1186.2: CPU ReSTIR-DI broke at every emissive hit; since #995 the path tracers continue
  through emissive surfaces with a BSDF (Material::hasBSDF).
GPU legs run on the RTX box (skipped without CUDA).
"""
from __future__ import annotations

import numpy as np
import pytest
from runtime_setup import configure_test_imports

configure_test_imports()

try:
    import astroray
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")

BACKENDS = [pytest.param("cpu"),
            pytest.param("gpu", marks=[pytest.mark.gpu, pytest.mark.serial])]
DIFFUSE = {"roughness": 1.0, "metallic": 0.0, "specular_ior_level": 0.0,
           "coat_weight": 0.0, "sheen_weight": 0.0}


def _renderer(backend):
    r = astroray.Renderer()
    if backend == "gpu":
        if not astroray.__features__.get("cuda", False):
            pytest.skip("CUDA feature not in this build")
        try:
            r.set_use_gpu(True)
        except Exception as e:  # noqa: BLE001 - CPU-only build
            pytest.skip(f"GPU unavailable: {e}")
        if not getattr(r, "gpu_available", False):
            pytest.skip("gpu_available is False")
    else:
        r.set_use_gpu(False)
    r.set_seed(1180)
    r.set_adaptive_sampling(False)
    return r


def _wall(backend, make, bg, spp=32, depth=4):
    """Mean of the centre of a big wall facing the camera."""
    r = _renderer(backend)
    r.set_background_color(bg)
    r.setup_camera([0, 0, 3], [0, 0, 0], [0, 1, 0], 20.0, 1.0, 0.0, 3.0, 24, 24)
    r.add_triangle([-20, -20, 0], [20, -20, 0], [0, 20, 0], make(r))
    img = np.asarray(r.render(spp, depth, None, False), dtype=np.float64)
    return img[9:15, 9:15].reshape(-1, 3).mean(0)


def _closed_box_mean(backend, mat, spp=16):
    r = _renderer(backend)
    c = [np.array([x, y, z], float) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
    for a, b, cc, d in ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)):
        for tri in ((a, b, cc), (a, cc, d)):
            v0, v1, v2 = (c[i] for i in tri)
            if np.dot(np.cross(v1 - v0, v2 - v0), -(v0 + v1 + v2)) < 0:   # wind inward
                v1, v2 = v2, v1
            r.add_triangle(v0.tolist(), v1.tolist(), v2.tolist(), mat(r))
    r.set_background_color([0.0, 0.0, 0.0])
    r.setup_camera([0, 0, 0], [0, 0, -1], [0, 1, 0], 60.0, 1.0, 0.0, 6.0, 32, 32)
    r.set_integrator("path_tracer")
    return float(np.asarray(r.render(spp, 64, None, False), dtype=np.float64).mean())


def _add_lambertian_emissive(r):
    return r.create_add_material(r.create_material("lambertian", [0.5, 0.5, 0.5], {}),
                                 r.create_material("emissive", [1.0, 1.0, 1.0], {}))


# ---- #1180 ---------------------------------------------------------------------------
@pytest.mark.parametrize("backend", BACKENDS)
def test_closed_box_add_lambertian_emissive(backend):
    """The issue's repro: rho 0.5, Le 1 -> L = Le / (1 - rho) = 2 (CPU 2.000, GPU was 0.000)."""
    m = _closed_box_mean(backend, _add_lambertian_emissive)
    assert abs(m - 2.0) < 0.04, (backend, m)


@pytest.mark.parametrize("backend", BACKENDS)
def test_add_lambertian_emissive_wall_keeps_bsdf_and_emission(backend):
    """White sky: L = 0.5 * 1 (lambertian) + 0.4 (emission)."""
    def make(r):
        return r.create_add_material(r.create_material("lambertian", [0.5, 0.5, 0.5], {}),
                                     r.create_material("emissive", [1.0, 1.0, 1.0], {"intensity": 0.4}))
    got = _wall(backend, make, [1.0, 1.0, 1.0], spp=64)
    np.testing.assert_allclose(got, [0.9, 0.9, 0.9], rtol=0.05)


@pytest.mark.parametrize("backend", BACKENDS)
def test_add_glass_emissive_wall_emits(backend):
    """Black sky behind a glass pane: nothing but the emission is visible (E = 0.6)."""
    def make(r):
        return r.create_add_material(
            r.create_material("dielectric", [1.0, 1.0, 1.0], {"ior": 1.5}),
            r.create_material("emissive", [1.0, 0.5, 0.25], {"intensity": 0.6}))
    got = _wall(backend, make, [0.0, 0.0, 0.0])
    np.testing.assert_allclose(got, [0.6, 0.3, 0.15], rtol=0.05)


# ---- #1186.1 -------------------------------------------------------------------------
def _glow(r, alpha, **extra):
    p = dict(DIFFUSE, emission_color=[1.0, 0.6, 0.2], emission_strength=2.0, alpha=alpha)
    p.update(extra)
    return r.create_material("principled", [0.0, 0.0, 0.0], p)


@pytest.mark.parametrize("backend", BACKENDS)
def test_principled_emission_is_weighted_by_alpha(backend):
    """Camera view of the emitter itself (black base colour, black sky): L = E * alpha."""
    full = _wall(backend, lambda r: _glow(r, 1.0), [0.0, 0.0, 0.0])
    half = _wall(backend, lambda r: _glow(r, 0.5), [0.0, 0.0, 0.0])
    np.testing.assert_allclose(full, [2.0, 1.2, 0.4], rtol=0.03)
    np.testing.assert_allclose(half / full, [0.5, 0.5, 0.5], rtol=0.03)


def _lit_floor(backend, alpha, second_light=False):
    """A diffuse floor lit only by a downward alpha-emitter quad above it (out of view),
    plus (second_light) a fixed emitter beside it so the power CDF has two entries."""
    r = _renderer(backend)
    r.set_background_color([0.0, 0.0, 0.0])
    r.setup_camera([0, 0.6, 3], [0, 0, 0], [0, 1, 0], 30.0, 1.0, 0.0, 3.0, 32, 32)
    r.set_integrator("path_tracer")
    floor = r.create_material("principled", [0.5, 0.5, 0.5], DIFFUSE)
    r.add_triangle([-10, 0, -10], [-10, 0, 10], [10, 0, 10], floor)
    r.add_triangle([-10, 0, -10], [10, 0, 10], [10, 0, -10], floor)
    glow = _glow(r, alpha)
    r.add_triangle([-0.5, 1, -0.5], [0.5, 1, -0.5], [0.5, 1, 0.5], glow)
    r.add_triangle([-0.5, 1, -0.5], [0.5, 1, 0.5], [-0.5, 1, 0.5], glow)
    if second_light:   # out of view (26 deg off axis), two-sided
        lamp = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 3.0, "two_sided": 1.0})
        r.add_triangle([1.5, 1, -0.5], [2.5, 1, -0.5], [2.5, 1, 0.5], lamp)
        r.add_triangle([1.5, 1, -0.5], [2.5, 1, 0.5], [1.5, 1, 0.5], lamp)
    img = np.asarray(r.render(128, 2, None, False), dtype=np.float64)
    return img.reshape(-1, 3).mean(0)


@pytest.mark.parametrize("backend", BACKENDS)
def test_light_sampler_power_follows_alpha(backend):
    """Light seen by the floor through NEE: the sampled emitter and the evaluated emission agree."""
    full = _lit_floor(backend, 1.0)
    half = _lit_floor(backend, 0.5)
    assert full.min() > 0.01, full
    np.testing.assert_allclose(half / full, [0.5, 0.5, 0.5], rtol=0.06)


@pytest.mark.parametrize("backend", BACKENDS)
def test_light_power_cdf_with_two_lights_follows_alpha(backend):
    """Two emitters: the alpha light's selection probability comes from its (alpha-scaled)
    host power, its radiance from the device emission; a mismatch biases the sum. The
    alpha-0 emitter is not emissive at all, so it isolates the second lamp."""
    lamp = _lit_floor(backend, 0.0, second_light=True)
    full = _lit_floor(backend, 1.0, second_light=True)
    half = _lit_floor(backend, 0.5, second_light=True)
    assert lamp.min() > 0.005 and (full - lamp).min() > 0.01, (lamp, full)
    np.testing.assert_allclose(half - lamp, 0.5 * (full - lamp), rtol=0.08)


# ---- #1180 trees: constant-Fac Mix, non-Principled / emissive leaf 0 --------------------------
def _mix_lambertian_emissive(r):
    return r.create_mix_material(r.create_material("lambertian", [0.4, 0.4, 0.4], {}),
                                 r.create_material("emissive", [1.0, 1.0, 1.0], {"intensity": 0.5}),
                                 0.25)


def _mix_leaf0(kind, params):
    def make(r):
        return r.create_mix_material(r.create_material(kind, [0.6, 0.5, 0.4], params),
                                     r.create_material("emissive", [1.0, 1.0, 1.0], {"intensity": 0.5}),
                                     0.25)
    return make


def test_cpu_mix_lambertian_emissive_wall():
    """Mix(0.25; lambertian 0.4, Emission 0.5) under a white sky: 0.75 * 0.4 + 0.25 * 0.5."""
    got = _wall("cpu", _mix_lambertian_emissive, [1.0, 1.0, 1.0], spp=64)
    np.testing.assert_allclose(got, [0.425] * 3, rtol=0.05)


@pytest.mark.gpu
@pytest.mark.serial
@pytest.mark.parametrize("kind,params", [("lambertian", {}), ("metal", {"roughness": 0.3}),
                                          ("disney", {"roughness": 0.6})])
def test_gpu_mix_tree_with_non_principled_leaf0_matches_cpu(kind, params):
    """The tree emission (0.25 * 0.5) rides leaf 0 whatever its type: GPU == CPU."""
    make = _mix_leaf0(kind, params)
    cpu = _wall("cpu", make, [1.0, 1.0, 1.0], spp=96)
    assert cpu.min() > 0.125 + 0.05, cpu            # emission + a lit lobe
    gpu = _wall("gpu", make, [1.0, 1.0, 1.0], spp=96)
    np.testing.assert_allclose(gpu, cpu, rtol=0.06)


@pytest.mark.parametrize("backend", BACKENDS)
def test_emissive_principled_leaf0_plus_second_emitter_sums(backend):
    """Leaf 0 is an emissive Principled and the tree emits too: the tree's summed emission
    replaces leaf 0's own (white sky): 0.3 albedo + 0.4 own + 0.3 emitter = 1.0."""
    def make(r):
        glow = r.create_material("principled", [0.3, 0.3, 0.3], dict(
            DIFFUSE, emission_color=[1.0, 1.0, 1.0], emission_strength=0.4))
        return r.create_add_material(glow, r.create_material(
            "emissive", [1.0, 1.0, 1.0], {"intensity": 0.3}))
    np.testing.assert_allclose(_wall(backend, make, [1.0, 1.0, 1.0], spp=64), [1.0] * 3, rtol=0.05)


def test_cpu_mix_alpha_principled_emission_is_alpha_weighted():
    """Mix(0.25; glow alpha 0.5, black diffuse), black sky: 0.75 * (E * alpha) = 0.75 for E = 2."""
    def make(r):
        return r.create_mix_material(
            _glow(r, 0.5, emission_color=[1.0, 1.0, 1.0]),
            r.create_material("principled", [0.0, 0.0, 0.0], DIFFUSE), 0.25)
    np.testing.assert_allclose(_wall("cpu", make, [0.0, 0.0, 0.0]), [0.75] * 3, rtol=0.04)


# ---- #1186.2 -------------------------------------------------------------------------
def _sphere_scene(integrator):
    r = astroray.Renderer()
    r.set_use_gpu(False)
    r.set_seed(1186)
    r.set_adaptive_sampling(False)
    r.set_background_color([0.0, 0.0, 0.0])
    r.setup_camera([0, 0, 4.2], [0, 0, 0], [0, 1, 0], 30.0, 1.0, 0.0, 4.2, 32, 32)
    if integrator == "restir-di":
        r.set_integrator_param("use_temporal", 0)
        r.set_integrator_param("use_spatial", 0)
    r.set_integrator(integrator)
    mat = r.create_material("principled", [0.6, 0.6, 0.6], dict(
        DIFFUSE, emission_color=[1.0, 1.0, 1.0], emission_strength=0.3))
    r.add_sphere([0, 0, 0], 1.0, mat)
    light = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 14.0, "two_sided": 1.0})
    r.add_triangle([2.2, -1.5, 0.5], [2.2, 1.5, 0.5], [2.2, 1.5, 3.5], light)   # beside the view
    r.add_triangle([2.2, -1.5, 0.5], [2.2, 1.5, 3.5], [2.2, -1.5, 3.5], light)
    return r


def test_cpu_restir_continues_through_emissive_surface_with_bsdf():
    """Emissive-plus-diffuse sphere lit by a quad: ReSTIR matches the path tracer (it used
    to show the sphere's own emission, 0.3, only)."""
    ref = np.asarray(_sphere_scene("path_tracer").render(256, 1, None, False), dtype=np.float64)
    got = np.asarray(_sphere_scene("restir-di").render(64, 1, None, False), dtype=np.float64)
    sl = (slice(12, 20), slice(12, 20))
    a, b = ref[sl].reshape(-1, 3).mean(0), got[sl].reshape(-1, 3).mean(0)
    assert a.min() > 0.5, a                       # emission 0.3 + a lit diffuse sphere
    np.testing.assert_allclose(b, a, rtol=0.06)

"""#886: a closed emissive mesh must not darken the BSDF-hit MIS weight.

LightSampler::pdfValue used to sum the pdf of every emitter triangle on the
BSDF ray, so a closed mesh also counted the back-side triangles it occludes:
lp too large, w_B too small, NEE-on darker than NEE-off and power != tree
(pre-fix CPU, this scene: power -1.25 %, tree -0.43 % vs NEE off). #912 made
pdfValue take the hit emitter only (Cycles
light_sample_mis_weight_forward_surface); this pins the #886 gate.

Gate (issue #886): closed emissive sphere mesh; NEE on (power, tree) vs NEE
off frame means within 0.1 %, five seeds each.
"""
import math

import numpy as np
import pytest
from runtime_setup import configure_test_imports

configure_test_imports()

astroray = pytest.importorskip("astroray")

_RES = 48
_SEEDS = range(1, 6)


def _sphere_tris(c, rad, nu=16, nv=12):
    def p(i, j):
        th, ph = math.pi * j / nv, 2 * math.pi * i / nu
        return [c[0] + rad * math.sin(th) * math.cos(ph), c[1] + rad * math.cos(th),
                c[2] + rad * math.sin(th) * math.sin(ph)]
    tris = []
    for j in range(nv):
        for i in range(nu):
            a, b, cc, d = p(i, j), p(i + 1, j), p(i + 1, j + 1), p(i, j + 1)
            if j > 0:
                tris.append((a, b, cc))
            if j < nv - 1:
                tris.append((a, cc, d))
    return tris


def _mean(gpu, nee, sampler, spp):
    ms = []
    for seed in _SEEDS:
        r = astroray.Renderer()
        if gpu:
            try:
                r.set_use_gpu(True)
            except Exception as e:  # noqa: BLE001 - CPU-only build
                pytest.skip("GPU unavailable: %s" % e)
            if not getattr(r, "gpu_available", False):
                pytest.skip("gpu_available is False")
        elif hasattr(r, "set_use_gpu"):
            r.set_use_gpu(False)
        r.set_integrator("path_tracer")
        r.set_adaptive_sampling(False)
        r.set_light_nee(nee)
        r.set_light_sampler(sampler)
        r.set_background_color([0.0, 0.0, 0.0])
        w = r.create_material("lambertian", [0.7, 0.7, 0.7], {})
        for a, b, c, d in (([-4, 0, -4], [-4, 0, 4], [4, 0, 4], [4, 0, -4]),
                           ([-4, 0, -2], [4, 0, -2], [4, 4, -2], [-4, 4, -2])):
            r.add_triangle(a, b, c, w)
            r.add_triangle(a, c, d, w)
        em = r.create_material("light", [1.0, 0.9, 0.7], {"intensity": 4.0})
        for t in _sphere_tris([0.0, 1.0, 0.0], 0.35):
            r.add_triangle(*t, em)
        r.setup_camera(look_from=[0, 1.5, 5], look_at=[0, 0.8, 0], vup=[0, 1, 0], vfov=45.0,
                       aspect_ratio=1.0, aperture=0.0, focus_dist=5.0, width=_RES, height=_RES)
        r.set_seed(seed)
        ms.append(np.asarray(r.render(spp, 6, None, False), dtype=np.float64).mean())
    return float(np.mean(ms))


@pytest.fixture(scope="module")
def cpu_nee_off():
    # The noisy leg: 5 x 4096 spp puts its SEM near 0.05 %.
    return _mean(False, False, "power", 4096)


@pytest.mark.cpu
@pytest.mark.parametrize("sampler", ["power", "tree"])
def test_886_cpu_closed_emitter_nee_on_matches_off(cpu_nee_off, sampler):
    on = _mean(False, True, sampler, 1024)
    assert abs(on / cpu_nee_off - 1.0) < 1e-3, f"{sampler}: on={on} off={cpu_nee_off}"


@pytest.mark.gpu
@pytest.mark.parametrize("sampler", ["power", "tree"])
def test_886_gpu_closed_emitter_matches_cpu_nee_off(cpu_nee_off, sampler):
    on = _mean(True, True, sampler, 1024)
    assert abs(on / cpu_nee_off - 1.0) < 1e-3, f"gpu {sampler}: on={on} cpu_off={cpu_nee_off}"

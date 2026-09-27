"""pkg292 / #862 follow-up: the CPU wavefront oracle must not leak HitRecord
fields across bounces.

advance_one_bounce (src/cpu/wavefront/path_kernel.cpp) used to reuse one
HitRecord per path. Primitives write only the fields they own, so a textured
triangle's named UV layers survived into a later sphere hit. Here the floor
carries a named layer "Alt" pinned to the RED texel; the sphere's texture reads
"Alt", which a sphere does not have, so it must fall back to its own UVs (half
red, half green). With the leak, sphere hits reached via the floor read the
floor's "Alt" UV and turn red. Oracle vs production (fresh HitRecord per bounce)
on green/red: leaking build 0.975; fixed 0.995-1.002 over 6 seeds.
"""
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

N, SPP, DEPTH, SEED = 32, 64, 4, 1234


def _renderer():
    r = astroray.Renderer()
    # 2x1 image: texel 0 red, texel 1 green.
    r.load_texture("leak_rg", [0.9, 0.05, 0.05, 0.05, 0.9, 0.05], 2, 1, "UV")
    r.set_texture_uv_layer("leak_rg", "Alt")
    sph = r.create_material("lambertian", [1, 1, 1], {"texture": "leak_rg"})
    floor = r.create_material("lambertian", [0.8, 0.8, 0.8], {})
    red_uv = [[0.25, 0.5]] * 3
    for tri in (([-4, -1, -4], [4, -1, 4], [4, -1, -4]), ([-4, -1, -4], [-4, -1, 4], [4, -1, 4])):
        r.add_triangle_layers(tri[0], tri[1], tri[2], floor,
                              {"UVMap": [[0, 0], [1, 0], [0, 1]], "Alt": red_uv})
    r.add_sphere([0.0, 0.0, 0.0], 1.0, sph)
    r.setup_camera(look_from=[0, 3, 4], look_at=[0, -0.5, 0], vup=[0, 1, 0], vfov=50,
                   aspect_ratio=1.0, aperture=0.0, focus_dist=5.0, width=N, height=N)
    r.set_background_color([1.0, 1.0, 1.0])
    r.set_seed(SEED)
    r.set_integrator_param("max_depth", DEPTH)
    r.set_integrator("path_tracer")
    r.render(1, 1, None, False)
    return r


def test_oracle_does_not_leak_uv_layers_across_bounces():
    oracle = np.asarray(astroray.reference_pt_wavefront_render(_renderer(), SPP, DEPTH, SEED, False),
                        dtype=np.float64).reshape(-1, 3).mean(0)
    r = _renderer()
    if hasattr(r, "set_use_gpu"):
        r.set_use_gpu(False)
    prod = np.asarray(r.render(SPP, DEPTH, None, False), dtype=np.float64).reshape(-1, 3).mean(0)
    rel = (oracle[1] / oracle[0]) / (prod[1] / prod[0])
    print(f"[pkg292 leak] oracle {oracle.round(4)} production {prod.round(4)} "
          f"green/red rel {rel:.4f}")
    assert abs(rel - 1.0) <= 0.012, (oracle, prod, rel)

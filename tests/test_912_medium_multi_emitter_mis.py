"""#912: emission-hit MIS must use the pdf of the emitter actually hit.

Scene (issue #912): camera z=5 looking -z inside a scattering medium; emissive
quads green (depth 5), blue (depth 9.5, +-6), red (off-view, depth 1) and white
(depth 11, +-8, hidden behind blue). A phase-sampled ray that hits blue also
crosses white's plane; the CPU reverse NEE pdf summed white's pdf too, so w_B
was too small and the image ~17 % dark (NEE on). The GPU already used the hit
emitter only (gpu_reconstruct_light_pdf; Cycles
light_sample_mis_weight_forward_surface).

Independent reference: NEE off (pure phase-sampled path tracing, w_B = 1) has
no light pdf at all, so NEE on must match it. Gate: per-channel means within
+-5 % (pkg271 convention), same for GPU vs the CPU NEE-off reference.
"""
import numpy as np
import pytest
from runtime_setup import configure_test_imports

configure_test_imports()

astroray = pytest.importorskip("astroray")

_RES = 32
_SPP = 64
_SEEDS = (1, 2)
_RTOL = 0.05


def _quad(r, z, h, mat):
    r.add_triangle([-h, -h, z], [h, -h, z], [h, h, z], mat)
    r.add_triangle([-h, -h, z], [h, h, z], [-h, h, z], mat)


def _scene(gpu, medium, nee):
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
    r.set_background_color([0.0, 0.0, 0.0])

    def light(c):
        return r.create_material("light", c, {"intensity": 1.0})

    _quad(r, 0.0, 0.5, light([0.0, 1.0, 0.0]))
    _quad(r, -4.5, 6.0, light([0.0, 0.0, 1.0]))
    red = light([1.0, 0.0, 0.0])
    r.add_triangle([0.4, -1, 4.0], [2.4, -1, 4.0], [2.4, 1, 4.0], red)
    r.add_triangle([0.4, -1, 4.0], [2.4, 1, 4.0], [0.4, 1, 4.0], red)
    _quad(r, -6.0, 8.0, light([1.0, 1.0, 1.0]))
    if medium == "fog":
        r.set_world_volume(0.15, [1.0, 1.0, 1.0], 0.0, 0.5)
    else:
        r.add_homogeneous_medium([-3, -3, -3], [3, 3, 7], 0.15, [0.8, 0.8, 0.8])
    r.setup_camera(look_from=[0, 0, 5], look_at=[0, 0, 0], vup=[0, 1, 0], vfov=40.0,
                   aspect_ratio=1.0, aperture=0.0, focus_dist=5.0, width=_RES, height=_RES)
    return r


def _mean(gpu, medium, nee):
    ms = []
    for s in _SEEDS:
        r = _scene(gpu, medium, nee)
        r.set_seed(s)
        img = np.asarray(r.render(_SPP, 8, None, False), dtype=np.float64)
        ms.append(img.reshape(_RES, _RES, 3).mean(axis=(0, 1)))
    return np.mean(ms, axis=0)


# Red is a small off-view emitter (noisiest); gate G and B, where the bias lives.
@pytest.mark.cpu
@pytest.mark.parametrize("medium", ["fog", "box"])
def test_912_cpu_nee_matches_nee_off(medium):
    on = _mean(False, medium, True)
    off = _mean(False, medium, False)
    np.testing.assert_allclose(on[1:], off[1:], rtol=_RTOL, err_msg=f"{medium} on={on} off={off}")


@pytest.mark.gpu
@pytest.mark.parametrize("medium", ["fog", "box"])
def test_912_gpu_matches_cpu_nee_off(medium):
    gpu = _mean(True, medium, True)
    ref = _mean(False, medium, False)
    np.testing.assert_allclose(gpu[1:], ref[1:], rtol=_RTOL, err_msg=f"{medium} gpu={gpu} ref={ref}")

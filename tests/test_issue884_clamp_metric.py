"""#884 — Blender's sample_clamp_* limit means what it means in Cycles.

Cycles scales the user limit by 3 (scene/integrator.cpp) and clamps a
contribution when reduce_add(fabs(RGB)) exceeds it (kernel/film/light_passes.h
film_clamp_light): a per-channel-average limit. Astroray clamped on XYZ Y, so a
saturated blue contribution passed at 4.6x the limit and a green one was cut at
0.47x. Now the spectral contribution's XYZ is taken to linear Rec.709 and
(R+G+B)/3 is compared (Renderer::clampMetricRGB / gpu_clampContribMW).

Gate: a directly visible emitter (emission hit at bounce 0 -> clamp_direct)
with clamp 0.5. Cycles: white (1.5, 1.5, 1.5) -> 0.5 each; pure blue
(0, 0, 3) -> blue 1.5; pure green (0, 1, 0) -> unchanged. Clamping each
hero-wavelength sample removes a little more than clamping the noiseless colour
(the per-sample metric scatters around its mean), so the clamped blue reads
below Cycles: 1.34 CPU on main cb70daa3 (after the #1020 exact film matrix; 1.42
before it). Band 0.80-1.10 of 1.5; the Y metric gave 3.0 (2.0x) for blue and
0.70 for green.
"""
from __future__ import annotations

import numpy as np
import pytest
from runtime_setup import configure_test_imports

configure_test_imports()
astroray = pytest.importorskip("astroray")


def _render(backend, rgb, clamp_direct):
    r = astroray.Renderer()
    if backend == "gpu":
        if not (astroray.__features__.get("cuda", False) and r.gpu_available):
            pytest.skip("CUDA GPU not available on this machine")
        r.set_use_gpu(True)
        r.set_wavelength_range(380.0, 780.0)
        r.set_output_mode("srgb")
    else:
        r.set_use_gpu(False)
    r.set_integrator("path_tracer")
    r.set_adaptive_sampling(False)
    r.set_background_color([0.0, 0.0, 0.0])
    m = r.create_material("light", list(rgb), {"intensity": 1.0})
    r.add_triangle([-5, 5, -5], [5, 5, -5], [5, 5, 5], m)
    r.add_triangle([-5, 5, -5], [5, 5, 5], [-5, 5, 5], m)
    r.set_clamp_direct(clamp_direct)
    r.set_clamp_indirect(0.0)
    r.setup_camera([0, 0, 0], [0, 1, 0], [0, 0, 1], 30.0, 1.0, 0.0, 5.0, 16, 16)
    r.set_seed(884)
    img = np.asarray(r.render(64, 4, None, False), dtype=np.float64)
    return img.reshape(16, 16, 3).mean(axis=(0, 1))


@pytest.mark.parametrize("backend", ["cpu", "gpu"])
def test_884_clamp_is_per_channel_average_like_cycles(backend):
    white = _render(backend, (1.5, 1.5, 1.5), 0.5)
    assert np.allclose(white, 0.5, rtol=0.05), white
    blue = _render(backend, (0.0, 0.0, 3.0), 0.5)
    assert 0.80 < blue[2] / 1.5 < 1.10, blue
    green_off = _render(backend, (0.0, 1.0, 0.0), 0.0)
    green = _render(backend, (0.0, 1.0, 0.0), 0.5)
    assert abs(green[1] / green_off[1] - 1.0) < 0.01, (green, green_off)

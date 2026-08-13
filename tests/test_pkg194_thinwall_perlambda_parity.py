"""pkg194 Item 2 — thin-wall glass R'/T' evaluated per-lambda native (CPU + GPU twin).

Thin-wall (`thin_wall=1`) glass computes the analytic reflect/transmit split R'/T'.
pkg178 evaluated it per-RGB-channel then upsampled the baked weight; pkg194 evaluates
the Beer absorption base(lambda)^(-1/cos_theta_t), the specular-tint f0 and (with a
film) the iridescence sensitivity per WAVELENGTH (pkg163/pkg182 discipline). Because
base^p is nonlinear in base, upsample(base^p) != upsample(base)^p — the per-lambda
form is the correct one.

* Parity: CPU (spectral path_tracer) vs GPU (wavefront) on a coloured thin-wall sphere
  — both legs now evaluate R'/T' per-lambda, so the twins must agree.
* Furnace: a near-white thin-wall sphere in a uniform white environment conserves
  energy — rendered LINEAR (apply_gamma clamps and can never see energy GAIN) with an
  explicit UPPER bound (memory gamma-furnace-cannot-detect-energy-gain).
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
_HAS_CUDA = AVAILABLE and astroray.__features__.get("cuda", False)

WIDTH = HEIGHT = 48
SAMPLES = 256
MAX_DEPTH = 8
SEED = 194002
BACKGROUND = [0.50, 0.50, 0.50]
RATIO_LOW, RATIO_HIGH = 0.95, 1.05

# Coloured thin-wall glass (base tint drives the per-lambda Beer absorption).
COLOUR_CASES = [
    ("thinwall_amber_r0.05", [0.85, 0.55, 0.25],
     {"thin_wall": 1.0, "transmission_weight": 1.0, "ior": 1.5, "roughness": 0.05}),
    ("thinwall_teal_r0.25", [0.25, 0.70, 0.65],
     {"thin_wall": 1.0, "transmission_weight": 1.0, "ior": 1.5, "roughness": 0.25}),
]


def _render(use_gpu, base, params, gamma=False):
    r = astroray.Renderer()
    r.set_background_color(BACKGROUND)
    mat = r.create_material("principled", base, params)
    r.add_sphere([0.0, 0.0, 0.0], 0.9, mat)
    r.setup_camera([0.0, 0.0, 1.35], [0.0, 0.0, 0.0], [0.0, 1.0, 0.0],
                   60.0, WIDTH / HEIGHT, 0.0, 1.35, WIDTH, HEIGHT)
    r.set_integrator("path_tracer")
    r.set_integrator_param("max_depth", MAX_DEPTH)
    if use_gpu:
        r.set_use_gpu(True)
    r.set_seed(SEED)
    return np.asarray(r.render(SAMPLES, MAX_DEPTH, None, gamma), dtype=np.float64)


@pytest.mark.skipif(not _HAS_CUDA, reason="CUDA not in this build (LEAD runs on RTX)")
@pytest.mark.parametrize("label,base,params", COLOUR_CASES, ids=[c[0] for c in COLOUR_CASES])
def test_pkg194_item2_thinwall_gpu_cpu_parity(label, base, params):
    gpu = _render(True, base, params)
    cpu = _render(False, base, params)
    assert np.all(np.isfinite(gpu)) and np.all(np.isfinite(cpu))
    print(f"\n[pkg194 Item 2 thin-wall per-lambda parity] case={label}")
    for c, ch in enumerate("RGB"):
        cm, gm = float(cpu[..., c].mean()), float(gpu[..., c].mean())
        cmed, gmed = float(np.median(cpu[..., c])), float(np.median(gpu[..., c]))
        mr = gm / cm if cm > 1e-8 else float("nan")
        medr = gmed / cmed if cmed > 1e-8 else float("nan")
        print(f"  {ch}: mean cpu={cm:.5f} gpu={gm:.5f} ratio={mr:.4f} | "
              f"median ratio={medr:.4f}")
        assert RATIO_LOW <= mr <= RATIO_HIGH, (
            f"{label} channel {ch} MEAN ratio {mr:.4f} outside band")
        assert RATIO_LOW <= medr <= RATIO_HIGH, (
            f"{label} channel {ch} MEDIAN ratio {medr:.4f} outside band")


def test_pkg194_item2_thinwall_furnace_energy_bounded():
    """Near-white thin-wall glass in a white furnace: no energy gain (linear, upper-bounded)."""
    base = [0.98, 0.98, 0.98]
    params = {"thin_wall": 1.0, "transmission_weight": 1.0, "ior": 1.5, "roughness": 0.1}
    cpu = _render(False, base, params, gamma=False)
    assert np.all(np.isfinite(cpu))
    mean = float(cpu.mean())
    ref = float(np.mean(BACKGROUND))
    ratio = mean / ref
    print(f"\n[pkg194 Item 2 thin-wall furnace] mean={mean:.5f} ref={ref:.5f} ratio={ratio:.4f}")
    # A passive (non-emissive) thin-wall glass cannot ADD energy: bounded above.
    assert ratio <= 1.03, f"thin-wall furnace GAINED energy: ratio {ratio:.4f} > 1.03"
    # And it should not go black (a per-lambda R'/T' sign/normalisation bug would).
    assert ratio >= 0.70, f"thin-wall furnace too dark: ratio {ratio:.4f} < 0.70"

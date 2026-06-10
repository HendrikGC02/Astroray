"""pkg108 BUG-16 probe: Principled Subsurface scattering responds to weight.

Reported behaviour (audit 2026-05-16): subsurface_weight / subsurface_radius
on a Principled BSDF may not reach the C++ Disney implementation — toggling
them produces no visible difference.

This test exercises the hypothesis: render the same thick (radius 0.6)
diffuse-ish sphere twice, once with subsurface_weight=0 and once with
subsurface_weight=1.0 + subsurface_radius=[0.3, 0.3, 0.3]. The two
renders should differ measurably; if they're pixel-identical the bug
is confirmed.

The Disney material is created directly here (not through the Blender
addon's Principled-BSDF routing) so this probes the *core* material
implementation, not the addon glue. A separate addon-side test would
be needed if the addon-routed path is what's broken in BUG-16.
"""

from __future__ import annotations

import sys
import numpy as np
import pytest

from runtime_setup import configure_test_imports

configure_test_imports()

try:
    import astroray  # noqa: E402
    AVAILABLE = True
except ImportError:
    AVAILABLE = False


pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")


WIDTH = 96
HEIGHT = 96
SAMPLES = 64
MAX_DEPTH = 6


def _render_with_subsurface(subsurface_weight, subsurface_radius=None, use_gpu=False):
    """Render a thick translucent sphere with the given subsurface params."""
    r = astroray.Renderer()
    r.set_integrator("path_tracer")
    r.set_background_color([0.0, 0.0, 0.0])
    r.set_seed(31)
    if use_gpu:
        r.set_use_gpu(True)

    # Bright back-light so light has to travel through the sphere to reach the camera.
    # This is the geometry that makes subsurface scattering visible: light enters
    # the back of the sphere, scatters inside (if subsurface is on), exits the
    # front toward the camera.
    light = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 35.0})
    r.add_sphere([0.0, 0.0, -2.0], 0.4, light)

    # Floor for visual anchor.
    floor = r.create_material("lambertian", [0.5, 0.5, 0.5], {})
    r.add_triangle([-3, -1, -3], [3, -1, -3], [3, -1, 3], floor)
    r.add_triangle([-3, -1, -3], [3, -1, 3], [-3, -1, 3], floor)

    # Disney sphere with subsurface params.
    params = {
        "roughness": 0.5,
        "metallic": 0.0,
        "specular": 0.5,
        "subsurface": float(subsurface_weight),
    }
    if subsurface_radius is not None:
        params["subsurface_radius"] = list(subsurface_radius)
    mat = r.create_material("disney", [0.95, 0.85, 0.75], params)
    r.add_sphere([0.0, 0.0, 0.0], 0.6, mat)

    r.setup_camera(
        [0.0, 0.4, 2.4], [0.0, 0.0, 0.0], [0.0, 1.0, 0.0],
        32.0,
        WIDTH / HEIGHT,
        0.0,
        2.4,
        WIDTH, HEIGHT,
    )
    return np.asarray(r.render(SAMPLES, MAX_DEPTH, None, True), dtype=np.float32)


def _assert_subsurface_responds(use_gpu):
    no_sss = _render_with_subsurface(subsurface_weight=0.0, use_gpu=use_gpu)
    with_sss = _render_with_subsurface(
        subsurface_weight=1.0, subsurface_radius=[0.3, 0.3, 0.3],
        use_gpu=use_gpu)

    # Sample the sphere region (centre half of frame).
    h, w, _ = no_sss.shape
    cy0, cy1 = h // 4, 3 * h // 4
    cx0, cx1 = w // 4, 3 * w // 4

    no_sss_mean = no_sss[cy0:cy1, cx0:cx1].mean(axis=(0, 1))
    with_sss_mean = with_sss[cy0:cy1, cx0:cx1].mean(axis=(0, 1))

    # The two renders should differ in mean per-channel by at least 1%
    # (a generous threshold — a real subsurface effect should change
    # the apparent transmission/scattering significantly).
    diff = np.abs(no_sss_mean - with_sss_mean)
    rel_diff = diff / (no_sss_mean + 1e-4)

    max_rel_diff = float(rel_diff.max())
    backend = "GPU" if use_gpu else "CPU"
    assert max_rel_diff > 0.01, (
        f"[{backend}] subsurface_weight=0 vs 1 produces identical (<1% diff) renders.\n"
        f"  no_sss mean per channel:   {no_sss_mean}\n"
        f"  with_sss mean per channel: {with_sss_mean}\n"
        f"  max relative diff:         {max_rel_diff:.4f}\n"
        f"This confirms BUG-16: subsurface_weight is plumbed but ignored "
        f"by the renderer."
    )


def test_subsurface_weight_changes_rendered_output():
    """subsurface_weight=0 vs 1 with non-zero radius must differ measurably."""
    _assert_subsurface_responds(use_gpu=False)


@pytest.mark.skipif(
    AVAILABLE and not astroray.__features__.get("cuda", False),
    reason="CUDA feature not in this build — GPU half of BUG-16 needs the RTX box",
)
def test_subsurface_weight_changes_rendered_output_gpu():
    """GPU half of BUG-16: gpu_disney_eval previously never read mat.subsurface,
    so subsurface_weight was a silent no-op on the CUDA backend while the CPU
    responded (CPU fix: PR #375). This is the regression gate for the GPU mirror
    of the Burley 2012 §5.3 Hanrahan-Krueger mix."""
    _assert_subsurface_responds(use_gpu=True)

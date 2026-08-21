#!/usr/bin/env python
"""pkg67 — flat-space perf gate and baseline capture.

Spec: .astroray_plan/packages/pkg67-metric-aware-path-tracer.md

Option α of pkg67 makes no changes to the flat-space hot path: it only
adds MinkowskiMetric, SampledWavelengths.redshift, and the frequencyShift
field on GRSpectralResult. None of these are queried during a flat
render. The perf gate ("flat render mean wall-time delta ≤ 5%") is
therefore a sanity check that the binary size / static-init footprint of
the new symbols did not perturb anything.

Usage:
    python benchmarks/pkg67_flat_perf.py --capture-baseline
        Render the reference scene at the worktree's HEAD and write the
        result to tests/reference/pkg67_flat_baseline_256.png.

    python benchmarks/pkg67_flat_perf.py --perf
        Render the scene N=5 times and print the mean wall-time.
"""

import argparse
import os
import sys
import time

REFERENCE_PNG = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tests", "reference", "pkg67_flat_baseline_256.png",
)

WIDTH = 256
HEIGHT = 256
SAMPLES = 16
MAX_DEPTH = 4
SEED = 17


def _make_scene(astroray):
    """Construct a small flat-space scene."""
    r = astroray.Renderer()
    r.set_integrator("path_tracer")
    # pkg206 §5 re-baseline: pkg67's contract is bit-identity (SSIM >= 0.999)
    # against a committed reference PNG, and this flat scene is achromatic —
    # luminance-weighted hero importance sampling only changes the NOISE
    # realization here, not the expected image, but it breaks bit-identity.
    # Per the pkg206 triage, keep the flat/GR baseline on the UNIFORM sampler
    # (hero_importance=0) so the existing reference stays valid without a
    # re-render. Dispersion scenes (test_spectral_prism) keep the default ON.
    r.set_integrator_param("hero_importance", 0)
    r.setup_camera(
        look_from=[0.0, 0.5, 3.0],
        look_at=[0.0, 0.0, 0.0],
        vup=[0.0, 1.0, 0.0],
        vfov=40.0,
        aspect_ratio=float(WIDTH) / HEIGHT,
        aperture=0.0,
        focus_dist=3.0,
        width=WIDTH,
        height=HEIGHT,
    )
    diffuse = r.create_material("lambertian", [0.8, 0.8, 0.8], {})
    r.add_sphere([0.0, 0.0, 0.0], 0.5, diffuse)
    r.set_background_color([0.5, 0.7, 1.0])
    return r


def render_baseline(astroray):
    """Render the reference flat scene and return an (H, W, 3) float32
    ndarray in [0, 1]. Used by test_pkg67_flat_regression."""
    import numpy as np
    r = _make_scene(astroray)
    r.set_seed(SEED)
    img = np.asarray(r.render(SAMPLES, MAX_DEPTH, None, True), dtype=np.float32)
    return img


def capture_baseline(astroray):
    import numpy as np
    from PIL import Image
    img = render_baseline(astroray)
    os.makedirs(os.path.dirname(REFERENCE_PNG), exist_ok=True)
    out = (np.clip(img, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
    Image.fromarray(out, mode="RGB").save(REFERENCE_PNG)
    print(f"wrote {REFERENCE_PNG} ({out.shape})")


def measure_perf(astroray, n=5):
    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        render_baseline(astroray)
        times.append(time.perf_counter() - t0)
    mean = sum(times) / len(times)
    print(f"N={n} mean={mean*1000:.1f} ms min={min(times)*1000:.1f} max={max(times)*1000:.1f}")
    return mean


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--capture-baseline", action="store_true")
    ap.add_argument("--perf", action="store_true")
    ap.add_argument("-n", type=int, default=5)
    args = ap.parse_args(argv)

    try:
        import astroray
    except ImportError as e:
        print(f"astroray module not available: {e}", file=sys.stderr)
        return 2

    if args.capture_baseline:
        capture_baseline(astroray)
    if args.perf:
        measure_perf(astroray, args.n)
    return 0


if __name__ == "__main__":
    sys.exit(main())

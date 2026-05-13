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
    """Construct a small flat-space scene. Uses the prism-reference
    helper layout (Cornell-ish three-wall box + a sphere) since it's
    already in the suite and known to render."""
    r = astroray.Renderer()
    r.set_resolution(WIDTH, HEIGHT)
    r.set_camera_position(0.0, 0.5, 3.0)
    r.set_camera_target(0.0, 0.0, 0.0)
    # The exact material composition is not load-bearing — the perf gate
    # only cares about timing the integrator on a flat scene.
    diffuse = r.add_lambertian_material(0.8, 0.8, 0.8)
    r.add_sphere(0.0, 0.0, 0.0, 0.5, diffuse)
    return r


def render_baseline(astroray):
    """Render the reference flat scene and return an (H, W, 3) float32
    ndarray in [0, 1]. Used by test_pkg67_flat_regression."""
    import numpy as np
    r = _make_scene(astroray)
    r.set_seed(SEED)
    img = np.asarray(r.render(SAMPLES, MAX_DEPTH, None, True), dtype=np.float32)
    # Renderer returns linear RGB in [0, 1] already
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

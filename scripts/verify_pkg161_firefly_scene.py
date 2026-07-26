#!/usr/bin/env python
"""pkg161 -- measure and calibrate the firefly-window gate scene.

The scene's EMITTER_INTENSITY / EMITTER_RADIUS in tests/scenes/firefly_window.py
are ANALYTIC DESIGN TARGETS: they were derived from the tuning model in that
module's docstring by an implementer with no GPU access who ran no renders.
This script replaces them with measurements, and prints the exact constants to
paste back.

It reports, in one pass:

  1. the tail statistic pkg161 is specified against (peak / p99.9, linear);
  2. both halves of pkg157's un-skipped firefly gate at the limit that gate
     uses (clampIndirect = p99.9 of unclamped luminance) -- whether the clamp
     BINDS, and what it costs in total energy;
  3. pkg161 contract item 4 -- whether pkg144's headline "clampIndirect = 10 ->
     < 0.02% brightness delta" reproduces on a scene that actually has
     fireflies, or is scene-specific as suspected;
  4. corrected EMITTER_INTENSITY / EMITTER_RADIUS, solved from the tuning model.

Usage (RTX box, from the repo root):

    python scripts/verify_pkg161_firefly_scene.py

    python scripts/verify_pkg161_firefly_scene.py --cpu        # CPU leg too
    python scripts/verify_pkg161_firefly_scene.py --intensity 5000 --radius 0.004
    python scripts/verify_pkg161_firefly_scene.py --spp 128 --width 640 --height 480

Everything is rendered LINEAR (apply_gamma=False). render()'s 4th positional
argument defaults to True and clamps to [0, 1] before the 1/2.2 power
(module/blender_module.cpp:1803-1811), which annihilates exactly the outliers
being measured here.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = ROOT / "tests"
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from runtime_setup import configure_test_imports  # noqa: E402

configure_test_imports()

import astroray  # noqa: E402
import scenes.firefly_window as firefly  # noqa: E402


#: Design targets the corrections below solve for. Chosen inside the window set
#: by pkg161 contract item 2 (ratio >= 10) and pkg157's energy half (< 2%):
#: 3x margin on the ratio, 2x margin on the energy cost.
TARGET_RATIO = 30.0
TARGET_ENERGY_SHARE = 0.010


def render(*, use_gpu, width, height, samples, seed, radius, intensity,
           clamp_indirect=0.0):
    r = astroray.Renderer()
    if use_gpu:
        r.set_use_gpu(True)
    r.set_integrator("path_tracer")
    firefly.build_scene(r, emitter_radius=radius, emitter_intensity=intensity)
    firefly.setup_camera(r, width, height)
    r.set_seed(seed)
    r.set_clamp_direct(0.0)
    r.set_clamp_indirect(clamp_indirect)
    return np.asarray(r.render(samples, firefly.MAX_DEPTH, None, False))


def clamp_effect(unclamped_lum, clamped_lum):
    delta_max = float(np.max(np.abs(clamped_lum - unclamped_lum)))
    m0 = float(unclamped_lum.mean())
    m1 = float(clamped_lum.mean())
    return delta_max, m0, m1, abs(m1 - m0) / max(m0, 1e-8)


def run(label, *, use_gpu, width, height, samples, seed, radius, intensity):
    print(f"\n=== {label} "
          f"({width}x{height} @ {samples} spp, depth {firefly.MAX_DEPTH}, "
          f"seed {seed}) ===")
    print(f"    emitter radius={radius:.6g}  intensity={intensity:.6g}")

    px = render(use_gpu=use_gpu, width=width, height=height, samples=samples,
                seed=seed, radius=radius, intensity=intensity)
    if not np.isfinite(px).all():
        print("    !! render contains NaN/Inf -- everything below is invalid")
    st = firefly.tail_stats(px)
    lum = firefly.luminance(px)

    ff_frac = st["n_fireflies"] / st["n_pixels"]
    print(f"    mean       = {st['mean']:.6g}")
    print(f"    p99.9      = {st['p99_9']:.6g}")
    print(f"    peak       = {st['peak']:.6g}")
    print(f"    TAIL RATIO = {st['ratio']:.4g}x        "
          f"(pkg161 bar: >= 10x; library before pkg161: 1.04x-1.82x)")
    print(f"    fireflies  = {st['n_fireflies']} / {st['n_pixels']} "
          f"({100.0 * ff_frac:.4f}% of pixels; must stay under 0.1000%)")

    # --- pkg157's un-skipped gate, at the limit that gate derives ------------
    limit = st["p99_9"]
    clamped = render(use_gpu=use_gpu, width=width, height=height,
                     samples=samples, seed=seed, radius=radius,
                     intensity=intensity, clamp_indirect=limit)
    d_max, m0, m1, rel = clamp_effect(lum, firefly.luminance(clamped))
    print(f"\n    pkg157 gate, clampIndirect = p99.9 = {limit:.6g}")
    print(f"      half 1 BINDS   : max|delta| = {d_max:.6g}   "
          f"(needs > 1e-05)   -> {'PASS' if d_max > 1e-5 else 'FAIL'}")
    print(f"      half 2 ENERGY  : mean {m0:.6g} -> {m1:.6g}, "
          f"rel = {100.0 * rel:.4f}%   (needs < 2%)   "
          f"-> {'PASS' if rel < 2e-2 else 'FAIL'}")

    # --- pkg161 contract item 4: does pkg144's headline "10" reproduce? ------
    c10 = render(use_gpu=use_gpu, width=width, height=height, samples=samples,
                 seed=seed, radius=radius, intensity=intensity,
                 clamp_indirect=10.0)
    d10, n0, n1, rel10 = clamp_effect(lum, firefly.luminance(c10))
    print(f"\n    pkg161 item 4: clampIndirect = 10 (pkg144's headline constant)")
    print(f"      max|delta| = {d10:.6g}    mean {n0:.6g} -> {n1:.6g}, "
          f"rel = {100.0 * rel10:.4f}%   (pkg144 claimed < 0.02%)")
    if d10 <= 1e-5:
        print("      -> does NOT bind on this scene: 10 sits above every "
              "indirect contribution here, so the '< 0.02%' headline is "
              "satisfied vacuously. Restate pkg144 item 3 scene-relatively.")

    # --- corrected constants -------------------------------------------------
    print("\n    --- calibration ---")
    if st["n_fireflies"] == 0:
        print("    NO FIREFLIES. The tail ratio above is meaningless.")
        print(f"    -> raise EMITTER_RADIUS ~3x (count ~ r_e^2): "
              f"{radius * 3.0:.6g}, keep intensity, re-run.")
        return st
    if ff_frac >= 0.001:
        shrink = (0.0003 / ff_frac) ** 0.5
        print("    TOO MANY FIREFLIES: the 99.9th percentile is itself a "
              "firefly, so the ratio understates the tail.")
        print(f"    -> lower EMITTER_RADIUS to {radius * shrink:.6g} "
              f"(count ~ r_e^2), keep intensity, re-run.")
        return st

    # ratio ~ L_e / spp  ->  scale intensity directly.
    new_intensity = intensity * (TARGET_RATIO / st["ratio"])
    # energy share s ~ r_e^2 * L_e  ->  hold s at target after the intensity move.
    ratio_of_shares = TARGET_ENERGY_SHARE / max(rel, 1e-9)
    new_radius = radius * ((ratio_of_shares * (intensity / new_intensity)) ** 0.5)
    print(f"    measured ratio {st['ratio']:.4g}x, energy share "
          f"{100.0 * rel:.4f}%  ->  targets {TARGET_RATIO:.0f}x / "
          f"{100.0 * TARGET_ENERGY_SHARE:.2f}%")
    print(f"    EMITTER_INTENSITY = {new_intensity:.6g}   "
          f"(was {intensity:.6g})")
    print(f"    EMITTER_RADIUS    = {new_radius:.6g}   (was {radius:.6g})")
    print("    (the two knobs are independent: intensity sets the ratio, "
          "radius sets the count. One iteration should converge.)")
    return st


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cpu", action="store_true",
                    help="also run the CPU leg (scenes.firefly_window's CPU_* "
                         "config with the enlarged CPU emitter)")
    ap.add_argument("--gpu-only", action="store_true",
                    help="skip the GPU leg if CUDA is unavailable instead of failing")
    ap.add_argument("--width", type=int, default=firefly.WIDTH)
    ap.add_argument("--height", type=int, default=firefly.HEIGHT)
    ap.add_argument("--spp", type=int, default=firefly.SAMPLES)
    ap.add_argument("--seed", type=int, default=firefly.SEED)
    ap.add_argument("--radius", type=float, default=firefly.EMITTER_RADIUS)
    ap.add_argument("--intensity", type=float, default=firefly.EMITTER_INTENSITY)
    args = ap.parse_args()

    has_cuda = astroray.__features__.get("cuda", False)
    print(f"astroray: {astroray.__file__}")
    print(f"cuda feature: {has_cuda}")

    if has_cuda:
        run("GPU wavefront", use_gpu=True, width=args.width, height=args.height,
            samples=args.spp, seed=args.seed, radius=args.radius,
            intensity=args.intensity)
    elif not args.gpu_only:
        print("\n!! no CUDA in this build -- skipping the GPU leg. The pkg157 "
              "gate numbers can only be produced on the RTX box.")

    if args.cpu or not has_cuda:
        run("CPU", use_gpu=False,
            width=firefly.CPU_WIDTH, height=firefly.CPU_HEIGHT,
            samples=firefly.CPU_SAMPLES, seed=args.seed,
            radius=args.radius * firefly.CPU_EMITTER_RADIUS_SCALE,
            intensity=args.intensity)


if __name__ == "__main__":
    main()

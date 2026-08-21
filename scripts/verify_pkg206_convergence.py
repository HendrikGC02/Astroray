#!/usr/bin/env python
"""pkg206 — convergence A/B: uniform vs luminance-weighted hero-wavelength
importance sampling on a dispersive-caustic scene.

One-off package-verification harness (deleted when pkg206 closes; the PR +
STATUS.md hold the evidence — scripts/README.md one-off convention). NOT a fork
of scripts/diagnostics/convergence_tracker.py: that script has no sampler A/B, no
dispersive-prism scene, no chromatic-noise metric, and no JSON output — none of
which it covers.

What it does:
  * Renders the dispersive triangular-glass prism (tests/scenes/prism_reference,
    Sellmeier BK7) at a sweep of spp {4,16,64,256,1024}, LINEAR (no gamma),
    seed-pinned, under BOTH samplers:
        A = uniform      (set_integrator_param('hero_importance', 0))
        B = importance   (set_integrator_param('hero_importance', 1), default)
  * Builds a high-spp reference (independent seed) PER sampler so each leg is
    measured against its own unbiased fixed point (the two converge to the same
    image up to MC noise — the unbiasedness gate; the A/B compares NOISE, not
    bias).
  * Emits per-spp RMSE-vs-reference and a chromatic-noise metric (mean per-pixel
    RGB channel standard deviation of the residual = colour noise) to JSON +
    CSV, so the parent can plot the convergence curves.

Unbiasedness cross-check emitted alongside: mean linear RGB of the converged
uniform vs importance references (a near-neutral match ⇒ unbiased; a green cast
⇒ the companion-pdf bias the pkg67/PR#627 triage warned about).

Usage:
    python scripts/verify_pkg206_convergence.py \
        [--spp 4,16,64,256,1024] [--ref-spp 4096] [--size 96] \
        [--out test_results/pkg206/] [--seed 17]

Requires a built astroray extension (parent builds + runs; the implementer
cannot build CUDA on this machine).
"""

from __future__ import annotations

import argparse
import json
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
from scenes.prism_reference import make_prism_scene  # noqa: E402


def _render(spp: int, size: int, seed: int, importance: bool) -> np.ndarray:
    """Render the dispersive prism at `spp`, LINEAR, with the chosen sampler."""
    r = make_prism_scene(astroray, dispersive=True)
    # make_prism_scene calls set_integrator("path_tracer"); set the A/B param
    # AFTER so it is threaded into the integrator's ParamDict on the next render.
    r.set_integrator("path_tracer")
    r.set_integrator_param("hero_importance", 1 if importance else 0)
    r.set_seed(seed)
    # 4th positional arg = applyGamma; MUST be False (linear) for a noise/energy
    # metric — gamma clamps to [0,1] and hides energy differences.
    return np.asarray(r.render(spp, 10, None, False), dtype=np.float32)


def _rmse(img: np.ndarray, ref: np.ndarray) -> float:
    return float(np.sqrt(np.mean((img - ref) ** 2)))


def _chromatic_noise(img: np.ndarray, ref: np.ndarray) -> float:
    """Mean over pixels of the per-pixel std across RGB of the residual — a
    proxy for colour (chromatic) noise: achromatic noise cancels in the channel
    std, chromatic noise does not."""
    resid = img - ref
    return float(np.mean(np.std(resid, axis=2)))


def run(spp_levels, ref_spp, size, out_dir, seed):
    out_dir.mkdir(parents=True, exist_ok=True)
    results = {"scene": "dispersive_prism_bk7", "size": size, "seed": seed,
               "ref_spp": ref_spp, "pyd": astroray.__file__, "legs": {}}

    refs = {}
    for name, importance in (("uniform", False), ("importance", True)):
        print(f"[pkg206] reference {name} @ {ref_spp} spp ...", flush=True)
        refs[name] = _render(ref_spp, size, seed + 1, importance)
        rows = []
        for spp in spp_levels:
            print(f"[pkg206] {name} @ {spp} spp ...", flush=True)
            img = _render(spp, size, seed, importance)
            rows.append({
                "spp": spp,
                "rmse": _rmse(img, refs[name]),
                "chromatic_noise": _chromatic_noise(img, refs[name]),
            })
        results["legs"][name] = rows

    # Unbiasedness cross-check: mean linear RGB of the two converged references.
    mu_u = refs["uniform"].reshape(-1, 3).mean(axis=0)
    mu_i = refs["importance"].reshape(-1, 3).mean(axis=0)
    results["reference_mean_rgb"] = {
        "uniform": mu_u.tolist(),
        "importance": mu_i.tolist(),
        "abs_diff": np.abs(mu_u - mu_i).tolist(),
        "rel_diff": (np.abs(mu_u - mu_i) / (mu_u + 1e-6)).tolist(),
    }

    (out_dir / "pkg206_convergence.json").write_text(json.dumps(results, indent=2))
    # Flat CSV for quick plotting.
    csv_lines = ["sampler,spp,rmse,chromatic_noise"]
    for name in ("uniform", "importance"):
        for row in results["legs"][name]:
            csv_lines.append(f"{name},{row['spp']},{row['rmse']:.8f},"
                             f"{row['chromatic_noise']:.8f}")
    (out_dir / "pkg206_convergence.csv").write_text("\n".join(csv_lines) + "\n")

    # Console summary.
    print("\n[pkg206] RMSE / chromatic-noise vs per-sampler reference:")
    print(f"{'spp':>6}  {'uni RMSE':>10}  {'imp RMSE':>10}  "
          f"{'uni chroma':>11}  {'imp chroma':>11}")
    ur = {r['spp']: r for r in results['legs']['uniform']}
    ir = {r['spp']: r for r in results['legs']['importance']}
    for spp in spp_levels:
        print(f"{spp:>6}  {ur[spp]['rmse']:>10.6f}  {ir[spp]['rmse']:>10.6f}  "
              f"{ur[spp]['chromatic_noise']:>11.6f}  "
              f"{ir[spp]['chromatic_noise']:>11.6f}")
    print(f"\n[pkg206] converged mean RGB  uniform={mu_u}  importance={mu_i}")
    print(f"[pkg206] |diff|={np.abs(mu_u - mu_i)}  (near-zero ⇒ unbiased)")
    print(f"[pkg206] outputs: {out_dir}")
    return results


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spp", default="4,16,64,256,1024",
                    help="comma-separated spp sweep")
    ap.add_argument("--ref-spp", type=int, default=4096)
    ap.add_argument("--size", type=int, default=96)
    ap.add_argument("--seed", type=int, default=17)
    ap.add_argument("--out", type=Path, default=ROOT / "test_results" / "pkg206")
    args = ap.parse_args()
    spp_levels = [int(s) for s in args.spp.split(",") if s.strip()]
    run(spp_levels, args.ref_spp, args.size, args.out, args.seed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""pkg178 Stage 4 PR-2 — conductor (metallic) thin-film hue-sweep harness.

Renders the Astroray-CPU leg of the conductor iridescence hue trajectory: a
metallic Principled sphere under a uniform environment, swept over
thin_film_thickness x thin_film_ior. For each cell it records the per-channel
LINEAR mean radiance over the sphere ROI and the circular-mean hue angle
(benchmarks.reference_bank.metrics.hue_spread), then writes a JSON + CSV table
and a hue-angle-vs-thickness curve the LEAD diffs against Blender 5.2 Cycles.

LEAD-DEFERRED: this authors the ASTRORAY side only. The vs-Cycles-5.2 verdict
(rendering the Cycles oracle leg, the per-channel mean-ratio bands, and the
refbank 5.2-blessed refs for these scenes) is the lead's on-hardware step — it
needs the oracle, which is not available to the PR-2 implementer. The scene here
is the plan §4 "conductor" row of the hue-trajectory sweep (thickness {100, 200,
400, 800, 1500, 3000}nm x film IOR {1.2, 1.5, 1.8}).

One command:
    python benchmarks/cycles-parity/thin_film/conductor_hue_sweep.py \
        --out test_results/pkg178_conductor_hue --res 128 --samples 256
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

# repo root = .../Astroray ; this file is at benchmarks/cycles-parity/thin_film
_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "tests"))

# Imports below run AFTER the sys.path setup above (build-dir bootstrap), so the
# module block is intentionally interleaved with configure_test_imports().
from runtime_setup import configure_test_imports

configure_test_imports()

import astroray
from benchmarks.reference_bank.metrics.hue_spread import _rgb_to_hue

# plan §4 conductor hue-trajectory grid.
THICKNESSES_NM = [100.0, 200.0, 400.0, 800.0, 1500.0, 3000.0]
FILM_IORS = [1.2, 1.5, 1.8]
# Neutral-ish metal base so the iridescence hue is the dominant chroma signal.
BASE_COLOR = [0.9, 0.9, 0.9]


def _render(thickness_nm: float, film_ior: float, res: int, samples: int, seed: int) -> np.ndarray:
    r = astroray.Renderer()
    r.set_use_gpu(False)  # CPU leg — GPU thin film is PR-3
    r.set_background_color([1.0, 1.0, 1.0])
    params = {
        "ior": 1.5,
        "roughness": 0.08,
        "metallic": 1.0,
        "transmission_weight": 0.0,
        "thin_film_thickness": thickness_nm,
        "thin_film_ior": film_ior,
    }
    mid = r.create_material("principled", list(BASE_COLOR), params)
    r.add_sphere([0.0, 0.0, 0.0], 1.0, mid)
    r.set_integrator("path_tracer")
    r.setup_camera([0, 0, 4], [0, 0, 0], [0, 1, 0], 40.0, 1.0, 0.0, 4.0, res, res)
    r.set_seed(seed)
    # render(spp, depth, denoiser, apply_gamma) — LINEAR (apply_gamma=False).
    img = np.asarray(r.render(samples, 16, None, False), dtype=np.float32).reshape(res, res, 3)
    return img


def _sphere_roi(img: np.ndarray) -> np.ndarray:
    """Central square ROI covering the sphere (camera is centered on it)."""
    h, w, _ = img.shape
    y0, y1 = int(h * 0.25), int(h * 0.75)
    x0, x1 = int(w * 0.25), int(w * 0.75)
    return img[y0:y1, x0:x1]


def _hue_angle_deg(roi: np.ndarray) -> float:
    mx = roi.max()
    rgb_n = roi / mx if mx > 0 else roi
    hue = _rgb_to_hue(rgb_n)
    h = hue[~np.isnan(hue)]
    if h.size < 4:
        return float("nan")
    z = np.exp(1j * h)
    return float((np.angle(z.mean()) % (2 * np.pi)) * 180.0 / np.pi)


def run(out_dir: str, res: int, samples: int) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    seed = 7
    for d in THICKNESSES_NM:
        for fior in FILM_IORS:
            img = _render(d, fior, res, samples, seed)
            roi = _sphere_roi(img)
            mean_rgb = roi.reshape(-1, 3).mean(axis=0)
            rows.append({
                "thickness_nm": d,
                "film_ior": fior,
                "mean_r": float(mean_rgb[0]),
                "mean_g": float(mean_rgb[1]),
                "mean_b": float(mean_rgb[2]),
                "hue_angle_deg": _hue_angle_deg(roi),
            })
            np.save(out / f"astroray_cpu_d{int(d)}_ior{fior}.npy", img)

    result = {
        "engine": "astroray_cpu",
        "note": "vs-Cycles-5.2 comparison is LEAD-DEFERRED (needs the oracle)",
        "base_color": BASE_COLOR,
        "res": res,
        "samples": samples,
        "rows": rows,
    }
    (out / "conductor_hue_sweep.json").write_text(json.dumps(result, indent=2))
    with (out / "conductor_hue_sweep.csv").open("w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        wr.writeheader()
        wr.writerows(rows)
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="test_results/pkg178_conductor_hue")
    ap.add_argument("--res", type=int, default=128)
    ap.add_argument("--samples", type=int, default=256)
    args = ap.parse_args()
    result = run(args.out, args.res, args.samples)
    print(f"[pkg178-conductor-hue] wrote {len(result['rows'])} cells to {args.out}")
    for row in result["rows"]:
        print("  d={thickness_nm:>6.0f}nm ior={film_ior:.1f}  "
              "RGB=({mean_r:.4f},{mean_g:.4f},{mean_b:.4f})  hue={hue_angle_deg:.1f}deg".format(**row))


if __name__ == "__main__":
    main()

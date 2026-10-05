"""pkg317: noise-aware candidates for gate (c) "do two backends converge to the same image?".

Study code only: nothing here is wired into ``gate_manifest.py`` or any threshold.
Inputs are *stacks* of independent-seed renders, shape (N, H, W, 3) linear float32.

Candidates (spec section "Candidates measured"):
  1. ``welch_verdict``       per-tile Welch t-test, family-wise error controlled
  2. ``ssim_ceiling_verdict`` SSIM(X, Y) vs the same-backend seed-pair SSIM ceiling
  3. ``ssim_box_verdict``    SSIM on k x k box-downsampled images
  4. ``ssim_mean_verdict``   SSIM of the N-seed mean images
  5. ``roi_ratio_verdict``   existing gate: per-ROI channel mean ratio within +-5 %
  0. ``ssim_gate_verdict``   existing gate: per-ROI SSIM >= 0.95 on one seed pair

Welch test: Jung, Hanika, Dachsbacher 2020, "Detecting Bias in Monte Carlo Renderers
using Welch's t-test", JCGT 9(2) (https://cg.ivd.kit.edu/welch.php), implemented from
the paper's Sec. 3-4 with scipy.stats; the paper's code is not vendored (licence
unstated).  Paper: one Welch sample = the sum of one MC sample per pixel of a tile
(CLT makes it normal); two-tailed Welch t with Welch-Satterthwaite df per tile and
colour channel; p-values analysed as a colour map and a histogram (uniform under H0).
Here one Welch sample = the tile mean of one independent-seed render (a sum of
tile_px * spp MC samples, normal by the same argument), N samples per backend.
Multiple testing: the paper reads the p-value histogram; we add Holm-Bonferroni
(FWER) and Benjamini-Hochberg (FDR), standard procedures.
Mitsuba 3 ``src/render/tests/test_renders.py`` (BSD-3) is the precedent for a z-test
render gate; not reused.
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path

import numpy as np
from scipy import ndimage, stats

SSIM_MIN = 0.95          # the gate's SSIM threshold
ROI_RATIO_MAX = 0.05     # the gate's +-5 % ROI channel-mean band
CEILING_TOL = 0.01       # study choice: cross-pair SSIM may sit this far below the ceiling


# ------------------------------------------------------------------ Welch tile test

def tile_means(stack: np.ndarray, tile: int = 8) -> np.ndarray:
    """(N,H,W,C) -> (N,H//tile,W//tile,C) per-render tile means (incomplete tiles dropped)."""
    n, h, w, c = stack.shape
    th, tw = h // tile, w // tile
    return stack[:, :th * tile, :tw * tile].reshape(n, th, tile, tw, tile, c).mean(axis=(2, 4))


def welch_tiles(a: np.ndarray, b: np.ndarray, tile: int = 8, delta_rel: float = 0.0) -> dict:
    """Per tile and channel Welch test of mean(a) == mean(b).

    ``delta_rel`` > 0 tests the practical-equivalence null |mean_a - mean_b| <= delta_rel*|mean|
    (one-sided test that the bias exceeds the margin).  Tiles with zero variance on both sides
    are deterministic: p = 1 when equal, 0 when not.  Returns arrays shaped (th, tw, C).
    """
    ma, mb = tile_means(a, tile), tile_means(b, tile)
    na, nb = len(ma), len(mb)
    mean_a, mean_b = ma.mean(0), mb.mean(0)
    va, vb = ma.var(0, ddof=1) / na, mb.var(0, ddof=1) / nb
    se = np.sqrt(va + vb)
    diff = mean_a - mean_b
    ref = 0.5 * (np.abs(mean_a) + np.abs(mean_b))
    with np.errstate(divide="ignore", invalid="ignore"):
        eff = np.abs(diff) - delta_rel * ref
        t = np.where(se > 0, eff / se, np.where(eff > 0, np.inf, 0.0))
        df = np.where(se > 0, se ** 4 / (va ** 2 / (na - 1) + vb ** 2 / (nb - 1)), np.inf)
        sf = stats.t.sf(t, df)
    p = np.clip(sf if delta_rel > 0 else 2 * sf, 0.0, 1.0)
    degenerate = (se == 0) & (diff == 0)
    p = np.where(degenerate, 1.0, p)
    with np.errstate(divide="ignore", invalid="ignore"):
        rel = np.where(ref > 0, diff / ref, 0.0)
    return {"p": p, "t": t, "rel_diff": rel, "degenerate": degenerate, "mean_a": mean_a, "mean_b": mean_b}


def holm(p: np.ndarray, alpha: float) -> np.ndarray:
    """Holm-Bonferroni step-down: boolean reject mask (FWER <= alpha)."""
    flat = p.ravel()
    order = np.argsort(flat)
    m = len(flat)
    reject = np.zeros(m, bool)
    for rank, idx in enumerate(order):
        if flat[idx] <= alpha / (m - rank):
            reject[idx] = True
        else:
            break
    return reject.reshape(p.shape)


def benjamini_hochberg(p: np.ndarray, q: float) -> np.ndarray:
    """BH step-up: boolean reject mask (FDR <= q)."""
    flat = p.ravel()
    m = len(flat)
    order = np.argsort(flat)
    ok = flat[order] <= q * (np.arange(1, m + 1) / m)
    k = np.nonzero(ok)[0].max() + 1 if ok.any() else 0
    reject = np.zeros(m, bool)
    reject[order[:k]] = True
    return reject.reshape(p.shape)


def welch_verdict(x: np.ndarray, y: np.ndarray, *, alpha: float = 0.05, tile: int = 8,
                  delta_rel: float = 0.0) -> dict:
    """Candidate 1.  pass = Holm rejects no tile/channel test at family-wise ``alpha``."""
    r = welch_tiles(x, y, tile, delta_rel)
    live = ~r["degenerate"]
    p = r["p"][live]
    if p.size == 0:
        return {"pass": True, "n_tests": 0, "n_reject_holm": 0, "n_reject_bh": 0, "min_p": 1.0,
                "ks_p": 1.0, "frac_p_lt_alpha": 0.0, "max_rel_bias_rejected": 0.0, "mean_rel_diff": 0.0}
    rej = holm(p, alpha)
    rej_bh = benjamini_hochberg(p, alpha)
    rel = r["rel_diff"][live]
    # Jung 2020 histogram view: p-values are uniform under H0 (delta_rel == 0 only).
    ks_p = float(stats.kstest(p, "uniform").pvalue) if delta_rel == 0 else float("nan")
    return {"pass": not rej.any(), "n_tests": int(p.size), "n_reject_holm": int(rej.sum()),
            "n_reject_bh": int(rej_bh.sum()), "min_p": float(p.min()), "ks_p": ks_p,
            "frac_p_lt_alpha": float((p < alpha).mean()),
            "max_rel_bias_rejected": float(np.abs(rel[rej]).max()) if rej.any() else 0.0,
            "mean_rel_diff": float(rel.mean())}


# ------------------------------------------------------------------ SSIM family

def roi_slices(roi, shape) -> tuple[slice, slice]:
    """Gate ROI [x0, y0, x1, y1] fractions -> (rows, cols), as harness.run_gate_c_trio."""
    h, w = shape[:2]
    return slice(int(roi[1] * h), int(roi[3] * h)), slice(int(roi[0] * w), int(roi[2] * w))


def ssim(a: np.ndarray, b: np.ndarray, roi=None) -> float:
    from benchmarks.reference_bank.metrics import compute_ssim
    if roi is not None:
        rows, cols = roi_slices(roi, a.shape)
        a, b = a[rows, cols], b[rows, cols]
    return float(compute_ssim(a, b)[0])


def box_down(img: np.ndarray, k: int) -> np.ndarray:
    h, w = img.shape[0] // k * k, img.shape[1] // k * k
    return img[:h, :w].reshape(h // k, k, w // k, k, -1).mean(axis=(1, 3))


def _min_roi_ssim(a, b, rois) -> float:
    return min(ssim(a, b, r) for r in rois.values())


def ssim_gate_verdict(x, y, rois) -> dict:
    """Candidate 0 (existing gate): per-ROI SSIM >= 0.95, matched seed pairs (x[i], y[i])."""
    vals = [_min_roi_ssim(x[i], y[i], rois) for i in range(min(len(x), len(y)))]
    return {"pass": all(v >= SSIM_MIN for v in vals), "stat": float(np.mean(vals)), "pass_frac": float(np.mean([v >= SSIM_MIN for v in vals])),
            "per_pair": vals}


def ssim_ceiling_verdict(x, y, rois, tol: float = CEILING_TOL) -> dict:
    """Candidate 2: cross-backend pair SSIM vs the same-backend seed-pair ceiling.
    pass = mean cross SSIM >= min(mean within-x, mean within-y) - tol."""
    def within(s):
        return [_min_roi_ssim(s[i], s[j], rois) for i, j in itertools.combinations(range(len(s)), 2)]
    cross = [_min_roi_ssim(x[i], y[j], rois) for i in range(len(x)) for j in range(len(y))]
    ceiling = min(float(np.mean(within(x))), float(np.mean(within(y))))
    return {"pass": float(np.mean(cross)) >= ceiling - tol, "stat": float(np.mean(cross)), "ceiling": ceiling}


def ssim_box_verdict(x, y, rois, k: int = 4) -> dict:
    """Candidate 3: gate SSIM on k x k box-downsampled matched seed pairs."""
    vals = []
    for i in range(min(len(x), len(y))):
        a, b = box_down(x[i], k), box_down(y[i], k)
        vals.append(min(ssim(a, b, r) for r in rois.values()))
    return {"pass": all(v >= SSIM_MIN for v in vals), "stat": float(np.mean(vals)), "pass_frac": float(np.mean([v >= SSIM_MIN for v in vals]))}


def ssim_mean_verdict(x, y, rois) -> dict:
    """Candidate 4: gate SSIM on the N-seed mean images (equivalent to N x spp)."""
    v = _min_roi_ssim(x.mean(0), y.mean(0), rois)
    return {"pass": v >= SSIM_MIN, "stat": v}


def roi_ratio_gap(a: np.ndarray, b: np.ndarray, roi) -> float:
    rows, cols = roi_slices(roi, a.shape)
    ma, mb = a[rows, cols].reshape(-1, a.shape[-1]).mean(0), b[rows, cols].reshape(-1, b.shape[-1]).mean(0)
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(mb > 0, ma / mb, np.where(ma > 0, np.inf, 1.0))
    return float(np.abs(ratio - 1).max())


def roi_ratio_verdict(x, y, rois) -> dict:
    """Candidate 5 (existing gate): per-ROI channel-mean ratio within +-5 %, on the N-seed means."""
    gap = max(roi_ratio_gap(x.mean(0), y.mean(0), r) for r in rois.values())
    return {"pass": gap <= ROI_RATIO_MAX, "stat": gap}


# ------------------------------------------------------------------ positive controls

def inject_gain(stack, gain=0.98):
    return stack * np.float32(gain)


def inject_roi_shift(stack, roi, frac=0.03):
    out = stack.copy()
    rows, cols = roi_slices(roi, stack.shape[1:])
    out[:, rows, cols] *= np.float32(1 + frac)
    return out


def inject_shift_px(stack, px=1):
    return np.roll(stack, px, axis=2)


def inject_blur(stack, sigma=1.0):
    return ndimage.gaussian_filter(stack, sigma=(0, sigma, sigma, 0), mode="nearest")


def injected_controls(gpu: np.ndarray, rois: dict) -> dict[str, np.ndarray]:
    first = next(iter(rois.values()))
    return {"gain_0.98": inject_gain(gpu), "roi_shift_3pct": inject_roi_shift(gpu, first),
            "shift_1px": inject_shift_px(gpu), "blur_1px": inject_blur(gpu)}


# ------------------------------------------------------------------ study driver

CANDIDATES = {
    "gate_ssim(existing)": lambda x, y, r: ssim_gate_verdict(x, y, r),
    "roi_ratio(existing)": lambda x, y, r: roi_ratio_verdict(x, y, r),
    "welch_tiles": lambda x, y, r: welch_verdict(x, y),
    "welch_tiles_margin1pct": lambda x, y, r: welch_verdict(x, y, delta_rel=0.01),
    "ssim_vs_ceiling": lambda x, y, r: ssim_ceiling_verdict(x, y, r),
    "ssim_box4": lambda x, y, r: ssim_box_verdict(x, y, r),
    "ssim_of_mean": lambda x, y, r: ssim_mean_verdict(x, y, r),
}


def half_splits(n: int):
    """All distinct splits of n seeds into two halves (n even)."""
    first = range(n)
    for a in itertools.combinations(first, n // 2):
        if 0 in a:
            yield list(a), [i for i in first if i not in a]


def run_candidates(x, y, rois) -> dict:
    return {name: fn(x, y, rois) for name, fn in CANDIDATES.items()}


def load_stack(files: list[Path]) -> np.ndarray:
    return np.stack([np.load(f) for f in files]).astype(np.float32)


def seed_files(leg_dir: Path) -> list[Path]:
    return sorted(leg_dir.glob("s*.npy"), key=lambda p: int(p.stem[1:]))


def _summary(v: dict) -> str:
    keys = ("n_reject_holm", "min_p") if "n_reject_holm" in v else ("stat",)
    return "PASS" if v["pass"] else "FAIL" + " " + " ".join(f"{k}={v[k]:.3g}" for k in keys if k in v)


def study(legs: Path, freeze: dict, out: Path, *, tile: int = 8) -> dict:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out.mkdir(parents=True, exist_ok=True)
    result: dict = {"roles": {}}
    sheet_rows = []
    for role, item in freeze["roles"].items():
        rid = role.replace(":", "_")
        rois = item["rois"]
        cpu = load_stack(seed_files(legs / f"{rid}_cpu_baseline"))
        gpu = load_stack(seed_files(legs / f"{rid}_gpu_baseline"))
        entry: dict = {"n_cpu": len(cpu), "n_gpu": len(gpu), "real": run_candidates(cpu, gpu, rois),
                       "negative": {}, "positive": {}}
        panels = {"real CPU vs GPU": welch_tiles(cpu, gpu, tile)["p"]}
        # negative controls: same backend, independent seeds, all half splits (n/2 vs n/2)
        for name, stack in (("cpu_vs_cpu", cpu), ("gpu_vs_gpu", gpu)):
            rows = []
            for a, b in half_splits(len(stack)):
                rows.append(run_candidates(stack[a], stack[b], rois))
            entry["negative"][name] = {
                "n_splits": len(rows),
                "pass_frac": {c: float(np.mean([r[c]["pass"] for r in rows])) for c in CANDIDATES}}
            a, b = next(half_splits(len(stack)))
            panels[f"null {name}"] = welch_tiles(stack[a], stack[b], tile)["p"]
        # positive controls (injected defects on the GPU stack, plus the rendered feature-off legs)
        controls = injected_controls(gpu, rois)
        for kind in ("hair_off", "hdri_off", "checker_flat"):
            d = legs / f"{rid}_gpu_{kind}"
            if d.is_dir() and seed_files(d):
                controls[kind] = load_stack(seed_files(d))
        for name, ctl in controls.items():
            entry["positive"][name] = run_candidates(cpu, ctl, rois)
            panels[name] = welch_tiles(cpu, ctl, tile)["p"]
        # cost: render seconds per leg
        meta = [json.loads(f.with_suffix(".json").read_text()) for f in seed_files(legs / f"{rid}_cpu_baseline")]
        gmeta = [json.loads(f.with_suffix(".json").read_text()) for f in seed_files(legs / f"{rid}_gpu_baseline")]
        entry["render_s_per_leg"] = {"cpu": float(np.mean([m["render_s"] for m in meta])),
                                     "gpu": float(np.mean([m["render_s"] for m in gmeta]))}
        result["roles"][role] = entry
        sheet_rows.append((role, panels))

    cols = max(len(p) for _, p in sheet_rows)
    fig, axes = plt.subplots(len(sheet_rows), cols, figsize=(2.6 * cols, 2.0 * len(sheet_rows)), squeeze=False)
    for r, (role, panels) in enumerate(sheet_rows):
        for c in range(cols):
            ax = axes[r][c]
            ax.axis("off")
            if c < len(panels):
                name, p = list(panels.items())[c]
                im = ax.imshow(-np.log10(np.clip(p, 1e-12, 1)).min(axis=-1), vmin=0, vmax=6, cmap="magma")
                ax.set_title(name, fontsize=6)
                if c == 0:
                    ax.text(0, -0.25, role, transform=ax.transAxes, fontsize=7)
    fig.colorbar(im, ax=axes, shrink=0.6, label="-log10(min-channel p) per 8x8 tile")
    fig.savefig(out / "welch_pvalue_maps.png", dpi=110)
    plt.close(fig)
    (out / "study.json").write_text(json.dumps(result, indent=1, default=float), encoding="utf-8")
    return result


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--legs", type=Path, required=True, help="seed_legs directory written by harness --seeds")
    p.add_argument("--freeze", type=Path, required=True, help="gate_c.freeze.json (roles + ROIs)")
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args(argv)
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    res = study(args.legs, json.loads(args.freeze.read_text(encoding="utf-8")), args.out)
    for role, e in res["roles"].items():
        print(role, {k: _summary(v) for k, v in e["real"].items()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

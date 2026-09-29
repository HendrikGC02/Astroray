"""pkg294 Phase 0 table: ROI mean band + variance per config (normal Python).

  python analyze.py <run_root> <rois.json>

<run_root>/renders64/<scene>_<variant>_<tree>_s<seed>.npy (64 spp, 3 seeds) is
required; <run_root>/renders_1spp (1 spp, 12 seeds) and renders_clamp
(sample_clamp_indirect=10, 64 spp) add columns when present. Per config: ROI
mean of Rec.709 luminance; MC sigma of the multi-seed mean from the per-pixel
across-seed variance (pixels independent); relVar = mean per-pixel
across-seed variance / mean^2. z = (mean - baseline ar0) / combined sigma;
the mean-preservation band is |z| <= 3. The 1-spp column is the per-sample
estimator variance (no within-pixel QMC stratification for either engine).
One-off verification script; delete when pkg294 closes.
"""
import glob
import json
import re
import sys
from pathlib import Path

import numpy as np

W = np.array([0.2126, 0.7152, 0.0722], dtype=np.float64)


def load(d, tag, box):
    y0, y1, x0, x1 = box
    files = sorted(glob.glob(str(Path(d) / f"{tag}_s*.npy")))
    if not files:
        return None
    return np.stack([np.load(f)[y0:y1, x0:x1].astype(np.float64) @ W for f in files])


def stats(stack):
    n = stack.shape[0]
    m = stack.mean()
    pvar = stack.var(axis=0, ddof=1)
    sigma = np.sqrt(pvar.sum()) / pvar.size / np.sqrt(n)
    return m, sigma, pvar.mean() / (m * m)


def main():
    root = Path(sys.argv[1])
    rois = json.loads(Path(sys.argv[2]).read_text())
    d64, d1, dc = root / "renders64", root / "renders_1spp", root / "renders_clamp"
    tags = sorted({re.sub(r"_s\d+\.npy$", "", Path(f).name) for f in glob.glob(str(d64 / "*_s*.npy"))})
    print("| scene | tree | variant | ROI mean +- sigma | z vs ar0 | relVar 64spp | x Cycles | "
          "per-sample relVar (1 spp) | x Cycles | clamp-10 removed |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for scene, r in rois.items():
        box = r["cube"]
        for tree in ("on", "off"):
            base, cy = f"{scene}_ar0_{tree}", f"{scene}_cy_{tree}"
            if base not in tags or cy not in tags:
                continue
            bm, bs, _ = stats(load(d64, base, box))
            _, _, cv = stats(load(d64, cy, box))
            c1 = load(d1, cy, box)
            cv1 = stats(c1)[2] if c1 is not None else None
            order = [cy, base] + sorted(t for t in tags if re.fullmatch(rf"{scene}_[A-Za-z0-9]+_{tree}", t)
                                        and t not in (cy, base))
            for tag in order:
                m, s, v = stats(load(d64, tag, box))
                z = (m - bm) / np.hypot(s, bs)
                s1 = load(d1, tag, box)
                v1 = f"{stats(s1)[2]:.3f}" if s1 is not None else "-"
                x1 = f"{stats(s1)[2] / cv1:.2f}" if (s1 is not None and cv1) else "-"
                sc = load(dc, tag, box)
                rem = f"{1.0 - sc.mean() / load(d64, tag, box).mean():+.4f}" if sc is not None else "-"
                variant = tag[len(scene) + 1:-(len(tree) + 1)]
                print(f"| {scene} | {tree} | {variant} | {m:.4f} +- {s:.4f} | {z:+.2f} | {v:.5f} | "
                      f"{v / cv:.2f} | {v1} | {x1} | {rem} |")


main()

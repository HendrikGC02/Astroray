"""pkg206 — turn the convergence JSON into presentation graphs + before/after
prism image examples (uniform vs luminance-weighted importance hero sampling).
One-off; deleted when pkg206 closes."""
import os, sys, json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from runtime_setup import configure_test_imports
configure_test_imports()
import astroray
sys.path.insert(0, str(ROOT / "tests"))
from scenes.prism_reference import make_prism_scene

OUT = ROOT / "test_results" / "pkg206"

# long-format CSV: sampler,spp,rmse,chromatic_noise
import csv
U, I = {}, {}
with open(OUT / "pkg206_convergence.csv") as f:
    for row in csv.DictReader(f):
        d = U if row["sampler"] == "uniform" else I
        d[int(row["spp"])] = (float(row["rmse"]), float(row["chromatic_noise"]))
spp = sorted(U)
uR = [U[s][0] for s in spp]; uC = [U[s][1] for s in spp]
iR = [I[s][0] for s in spp]; iC = [I[s][1] for s in spp]

# ---------- FIGURE 1: convergence curves ----------
fig, ax = plt.subplots(1, 2, figsize=(12, 4.6))
for a, (yU, yI, title, ylab) in zip(ax, [
        (uR, iR, "RMSE vs reference", "RMSE (linear)"),
        (uC, iC, "Chromatic noise vs reference", "mean per-pixel RGB residual std")]):
    a.loglog(spp, yU, "o-", color="#d29922", lw=2, ms=7, label="uniform hero-λ")
    a.loglog(spp, yI, "o-", color="#58a6ff", lw=2, ms=7, label="luminance-weighted importance")
    a.set_xlabel("samples per pixel"); a.set_ylabel(ylab); a.set_title(title)
    a.grid(True, which="both", alpha=0.25); a.legend()
    for x, u, i in zip(spp, yU, yI):
        a.annotate(f"-{(1-i/u)*100:.0f}%", (x, i), textcoords="offset points",
                   xytext=(0,-14), ha="center", fontsize=8, color="#58a6ff")
fig.suptitle("pkg206 — luminance-weighted hero-wavelength importance sampling · dispersive BK7 prism (CPU, linear, seed-pinned)", fontsize=11)
fig.tight_layout()
p1 = OUT / "pkg206_convergence_plot.png"; fig.savefig(p1, dpi=130); plt.close(fig)
print("wrote", p1)

# ---------- FIGURE 2: before/after image examples ----------
def render(spp, seed, importance):
    r = make_prism_scene(astroray, dispersive=True)
    r.set_integrator_param("hero_importance", 1 if importance else 0)
    r.set_seed(seed)
    flat = np.asarray(r.render(spp, 10, None, False), dtype=np.float32)
    n = int(round((flat.size // 3) ** 0.5))
    return flat.reshape(n, n, 3)

SPP = 64
uni = render(SPP, 17, False)
imp = render(SPP, 17, True)
ref = render(2048, 18, True)
def tone(x):
    x = np.clip(x, 0, None); x = x / max(x.max(), 1e-6)
    return np.power(np.clip(x,0,1), 1/2.2)
fig, ax = plt.subplots(1, 3, figsize=(12, 4.4))
for a, img, t in zip(ax, [uni, imp, ref],
                     [f"uniform hero-λ · {SPP} spp", f"importance hero-λ · {SPP} spp", "reference · 2048 spp"]):
    a.imshow(tone(img)); a.set_title(t, fontsize=11); a.axis("off")
fig.suptitle("pkg206 — dispersive prism at equal spp: importance sampling has visibly less chromatic (colour) noise", fontsize=11)
fig.tight_layout()
p2 = OUT / "pkg206_prism_comparison.png"; fig.savefig(p2, dpi=130); plt.close(fig)
print("wrote", p2)
print("done")

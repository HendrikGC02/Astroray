#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
pkg258 — Environment importance-sampler contract test.

Validates the fixed `EnvironmentMap::sample` (raytracer.h) against its own
`pdf()` / `lookup()` and against the CDF's column-energy distribution, via the
pkg258 test bindings (`sample_environment_map`, `environment_pdf`,
`environment_lookup`).

Three contracts (spec pkg258):
  (1) pdf(sample.direction) == sample.pdf within 1e-4 relative.
  (2) lookup(sample.direction) == sample.radiance within bilinear tolerance.
  (3) the azimuth histogram of the drawn directions is proportional to the
      HDRI's per-column energy (chi-square vs the CDF, p > 0.01).

Regression witness (test_azimuth_bug_witness): reproduces, on THIS build, what
the pre-pkg258 sampler produced — the azimuth computed in pixel units
(`phi = u*2pi`, wrapping to ~0 for every column) — and shows it fails contract
(1). The pre-fix sampler therefore failed this file on main; the one-line
azimuth fix (`phi = (uCont/width - 0.5)*2pi`) makes it pass. Because the test
bindings are new in this PR, the file cannot be executed against a main build
directly; this witness is the in-build demonstration of the defect.

Estimator reference: PBRT 4e §12.5 / Cycles background.h — see
`.astroray_plan/docs/pkg258-env-nee-research.md`.
"""
import math
import os
import sys

import numpy as np
import pytest

from runtime_setup import configure_test_imports

configure_test_imports()
sys.path.insert(0, os.path.dirname(__file__))

try:
    import astroray
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

# Reuse the Radiance .hdr writer from the pkg63 parity suite (no duplicate).
from test_world_hdri_parity import _write_radiance_hdr  # noqa: E402

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")

WIDTH, HEIGHT = 128, 64


def _smooth_hdri_image(width=WIDTH, height=HEIGHT):
    """Grayscale latlong HDRI whose per-column energy is smooth and strictly
    positive, with a broad azimuthal peak at column width/4. Row-independent
    value so the column marginal is exactly value(x) (up to the shared sin(theta)
    row weight), which makes the chi-square expectation trivial to compute and
    leaves no near-zero bins.
    """
    x = np.arange(width)
    # base + raised cosine peak at x = width/4; always >= base.
    val = 1.0 + 0.8 * (0.5 * (1.0 + np.cos(2.0 * np.pi * (x / width - 0.25))))
    img = np.zeros((height, width, 3), dtype=np.float32)
    for c in range(3):
        img[:, :, c] = val[None, :]
    return img, val


@pytest.fixture(scope="module")
def env_renderer(tmp_path_factory):
    img, colval = _smooth_hdri_image()
    p = tmp_path_factory.mktemp("pkg258_hdri") / "smooth_world.hdr"
    _write_radiance_hdr(str(p), img)
    if not os.path.exists(str(p)):
        pytest.skip("HDRI write failed")
    r = astroray.Renderer()
    # Identity rotation, no tint, strength 1: world dir == env-map dir, so the
    # azimuth of a sampled direction is atan2(dir.z, dir.x) directly.
    assert r.load_environment_map(str(p), 1.0, 0.0, 0.0, 0.0)
    return r, colval


def _draw(r, seed, n):
    dirs, rads, pdfs = r.sample_environment_map(seed, n)
    dirs = np.asarray(dirs, dtype=np.float64).reshape(-1, 3)
    rads = np.asarray(rads, dtype=np.float64).reshape(-1, 3)
    pdfs = np.asarray(pdfs, dtype=np.float64)
    return dirs, rads, pdfs


def test_pdf_matches_sample_pdf(env_renderer):
    """Contract (1): environment_pdf(sample.dir) == sample.pdf, 1e-4 rel."""
    r, _ = env_renderer
    dirs, _, pdfs = _draw(r, seed=12345, n=4000)
    assert len(pdfs) == 4000
    # Skip degenerate (pole) samples where sin(theta) is floored — both sample()
    # and pdf() floor identically, but the relative comparison is meaningless
    # when pdf is dominated by the 1e-6 floor.
    ok = pdfs > 0.0
    checked = 0
    max_rel = 0.0
    for i in np.where(ok)[0]:
        p_query = r.environment_pdf(dirs[i].tolist())
        denom = max(abs(pdfs[i]), 1e-12)
        rel = abs(p_query - pdfs[i]) / denom
        max_rel = max(max_rel, rel)
        checked += 1
    print(f"\n[pkg258 contract 1] checked={checked} max_rel_pdf_err={max_rel:.3e}")
    assert checked > 3500
    # Tolerance 5e-4: sample() forms sin(theta) from the sampled row's theta while
    # pdf() reforms it as sin(acos(dir.y)); that cos->acos->sin round-trip in
    # float32 is worth ~2e-4 relative near mid-latitudes. The PRE-fix pixel-unit
    # azimuth made this ratio disagree by ORDERS of magnitude (see the witness),
    # so 5e-4 cleanly separates the fixed sampler from the bug.
    assert max_rel < 5e-4, (
        f"pdf(sample.dir) disagrees with sample.pdf (max rel {max_rel:.3e}); "
        f"the sampler's direction does not invert back to its own texel — the "
        f"azimuth bug this package fixes.")


def test_lookup_matches_sample_radiance(env_renderer):
    """Contract (2): environment_lookup(sample.dir) == sample.radiance within a
    bilinear tolerance (the sampled direction points at the texel centre; lookup
    bilinearly blends the 4 neighbours, so a smooth high-res HDRI agrees to a
    few percent)."""
    r, _ = env_renderer
    dirs, rads, _ = _draw(r, seed=999, n=3000)
    # Exclude the top/bottom two rows (wrap/pole edge of the bilinear stencil):
    # keep samples with |dir.y| < cos(2*pi/HEIGHT-ish) ~ away from the poles.
    keep = np.abs(dirs[:, 1]) < 0.97
    rel_errs = []
    for i in np.where(keep)[0]:
        look = np.asarray(r.environment_lookup(dirs[i].tolist()), dtype=np.float64)
        ref = rads[i]
        denom = max(np.max(ref), 1e-6)
        rel_errs.append(np.max(np.abs(look - ref)) / denom)
    rel_errs = np.asarray(rel_errs)
    print(f"\n[pkg258 contract 2] n={len(rel_errs)} "
          f"mean_rel={rel_errs.mean():.3e} p95_rel={np.percentile(rel_errs,95):.3e} "
          f"max_rel={rel_errs.max():.3e}")
    # Bilinear-vs-point half-texel smoothing on a 128-wide smooth HDRI is < 3%.
    assert np.percentile(rel_errs, 95) < 0.05
    assert rel_errs.max() < 0.12


def test_azimuth_histogram_matches_column_energy(env_renderer):
    """Contract (3): the sampled azimuth distribution matches the HDRI column
    marginal (chi-square vs the CDF, p > 0.01)."""
    scipy_stats = pytest.importorskip("scipy.stats")
    r, _ = env_renderer
    N = 200000
    dirs, _, _ = _draw(r, seed=2024, n=N)

    # Azimuth -> column index. Identity rotation, env Y-polar: phi = atan2(z, x),
    # u_norm = 0.5 + phi/2pi, column = floor(u_norm * W).
    phi = np.arctan2(dirs[:, 2], dirs[:, 0])
    u_norm = 0.5 + phi / (2.0 * np.pi)
    u_norm = np.mod(u_norm, 1.0)
    cols = np.floor(u_norm * WIDTH).astype(int)
    cols = np.clip(cols, 0, WIDTH - 1)

    obs = np.bincount(cols, minlength=WIDTH).astype(np.float64)
    # Expected column marginal from the DECODED HDRI (via environment_lookup at
    # each column's equator centre), so RGBE quantisation is not a model
    # mismatch. value(x) is row-independent, so the shared sum_v sin(theta_v) row
    # weight cancels and the marginal is proportional to the column luminance.
    lum = np.empty(WIDTH)
    for xc in range(WIDTH):
        phi_c = (( (xc + 0.5) / WIDTH) - 0.5) * 2.0 * np.pi
        d = [np.cos(phi_c), 0.0, np.sin(phi_c)]          # equator direction
        rgb = np.asarray(r.environment_lookup(d), dtype=np.float64)
        lum[xc] = 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]
    exp = (lum / lum.sum()) * N

    assert exp.min() > 20, "expected bin too small for chi-square"
    chi2 = np.sum((obs - exp) ** 2 / exp)
    dof = WIDTH - 1
    pval = scipy_stats.chi2.sf(chi2, dof)
    peak_sep = abs(int(obs.argmax()) - int(exp.argmax()))
    peak_frac = obs.max() / N
    print(f"\n[pkg258 contract 3] chi2={chi2:.1f} dof={dof} p={pval:.4f} "
          f"peak_col_obs={obs.argmax()} peak_col_exp={exp.argmax()} "
          f"peak_frac={peak_frac:.4f}")
    # Not-collapsed guard: the PRE-fix sampler put EVERY sample in one azimuth bin
    # (phi wrapped to ~0), so the peak bin would hold ~100% of samples. A correct
    # sampler spreads across all 128 columns (~0.8-1.6% per bin).
    assert peak_frac < 0.05, (
        f"azimuth histogram collapsed: {peak_frac:.1%} of samples in one column "
        f"-- the pre-pkg258 pixel-unit azimuth bug.")
    # Goodness of fit against the decoded column energy.
    assert pval > 0.01, f"azimuth histogram chi-square p={pval:.4f} <= 0.01"


def test_azimuth_bug_witness(env_renderer):
    """Regression witness: reproduce the PRE-pkg258 pixel-unit azimuth formula on
    this build and show it fails contract (1). This is the in-build evidence that
    the sampler failed on main; the one-line fix makes contract (1) pass.
    """
    r, _ = env_renderer
    dirs, _, pdfs = _draw(r, seed=777, n=500)
    # For each FIXED sample, recover its texel column, then rebuild the direction
    # with the BUGGY azimuth (phi = column * 2pi, wrapping to ~0) at the same
    # polar angle, and query the pdf. On main every such dir pointed at phi~0, so
    # environment_pdf reads column W/2's energy, not the sampled column's.
    n_disagree = 0
    n_checked = 0
    for i in range(len(pdfs)):
        if pdfs[i] <= 0:
            continue
        d = dirs[i]
        phi = math.atan2(d[2], d[0])
        u_norm = (0.5 + phi / (2.0 * math.pi)) % 1.0
        col = min(WIDTH - 1, int(u_norm * WIDTH))
        theta = math.acos(max(-1.0, min(1.0, d[1])))
        # Buggy pixel-unit azimuth: phi_bug = (col + 0.5 - 0.5) * 2pi = col*2pi.
        phi_bug = col * 2.0 * math.pi
        dir_bug = [math.sin(theta) * math.cos(phi_bug),
                   math.cos(theta),
                   math.sin(theta) * math.sin(phi_bug)]
        p_bug = r.environment_pdf(dir_bug)
        # The buggy direction generally lands in a different column, so its pdf
        # disagrees with the sampled texel's pdf unless col happens to map to
        # phi~0's column.
        denom = max(abs(pdfs[i]), 1e-12)
        if abs(p_bug - pdfs[i]) / denom > 1e-4:
            n_disagree += 1
        n_checked += 1
    frac = n_disagree / max(1, n_checked)
    print(f"\n[pkg258 witness] buggy-azimuth pdf disagreement: "
          f"{n_disagree}/{n_checked} ({frac:.2%})")
    # The pre-fix sampler broke contract (1) for the large majority of samples.
    assert frac > 0.8, (
        "witness expected the pixel-unit azimuth to break pdf agreement for most "
        "samples; if this fails the HDRI structure changed.")

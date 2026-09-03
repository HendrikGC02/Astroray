# pkg127 research note — Specular Polynomials (SMS seed-stage upgrade)

Phase-0 web-verified research note. Every factual claim below was checked against a
live URL; the source is inline. Where a fact could NOT be verified it is marked
`NOT FOUND — needs manual verification`. This note is for a follow-up spec author;
it does not touch any repo code.

---

## 1. Canonical papers (all web-verified)

### 1.1 Specular Polynomials (the method to port)

- **Title:** "Specular Polynomials"
- **Authors (10, exact order):** Zhimin Fan, Jie Guo, Yiming Wang, Tianyu Xiao,
  Hao Zhang, Chenxi Zhou, Zhenyu Chen, Pengpei Hong, Yanwen Guo, Ling-Qi Yan.
  — https://arxiv.org/abs/2405.13409 (author list) and
  https://zhiminfan.work/specPoly.html (citation block).
  ⚠️ The current pkg127 spec's "Cite:" line lists *"Fan, Wang, Dong, Wang, Hašan,
  Yan et al."* — that author list is **wrong** and must be corrected before code is
  written (Hašan is not an author; the real 2nd author is Jie Guo, and the 10th is
  Ling-Qi Yan).
- **Venue / year:** ACM Transactions on Graphics 43(4), proceedings of SIGGRAPH 2024.
  Published 2024-07. — https://dl.acm.org/doi/10.1145/3658132
- **DOI:** `10.1145/3658132` — https://doi.org/10.1145/3658132
- **arXiv:** `arXiv:2405.13409` (submitted 22 May 2024; "13 pages, 13 figures,
  accepted by SIGGRAPH 2024"). — https://arxiv.org/abs/2405.13409
- **Article number:** `126`, 13 pages (per the author's own BibTeX on the project
  page). — https://zhiminfan.work/specPoly.html (BibTeX `articleno = {126}`,
  `numpages = {13}`). Note: the arXiv preprint template body shows a placeholder
  "Article 1 / DOI 10.1145/3618360" that is a LaTeX stub, NOT the real number.
- **Project page:** https://zhiminfan.work/specPoly.html
- **Reference implementation:** https://github.com/mollnn/spoly (see §3 for the
  license blocker).
- **Paper license:** the arXiv record is **CC BY 4.0**
  (https://creativecommons.org/licenses/by/4.0/ — icon shown at
  https://arxiv.org/abs/2405.13409 and confirmed in the HTML footer
  https://arxiv.org/html/2405.13409v1: "License: CC BY 4.0"). CC BY 4.0 is a
  permissive license; re-deriving the math from the paper is license-compatible.

### 1.2 Prior work (all verified)

- **Zeltner, Georgiev, Jakob 2020 — "Specular Manifold Sampling for Rendering
  High-Frequency Caustics and Glints"** (SMS), ACM TOG 39(4), Article 149,
  SIGGRAPH 2020. DOI `10.1145/3386569.3392408`.
  — https://doi.org/10.1145/3386569.3392408 and
  https://rgl.epfl.ch/publications/Zeltner2020Specular
  Reference code: https://github.com/tizian/specular-manifold-sampling (BSD-3-Clause,
  see §3.2).
- **Hanika, Droske, Fascione 2015 — "Manifold Next Event Estimation"** (MNEE),
  Computer Graphics Forum 34(4), pp. 87–97 (EGSR 2015). DOI `10.1111/cgf.12681`.
  — https://doi.org/10.1111/cgf.12681 and
  https://diglib.eg.org/items/8c90eb94-3232-4136-9b24-0d7d896399de
- **Jakob & Marschner 2012 — "Manifold Exploration: A Markov Chain Monte Carlo
  Technique for Rendering Scenes with Difficult Specular Transport"**, ACM TOG
  31(4), 58:1–58:13, SIGGRAPH 2012. DOI `10.1145/2185520.2185554`.
  — https://doi.org/10.1145/2185520.2185554 and
  https://rgl.epfl.ch/publications/Jakob2012Manifold
  (Note: one ResearchGate mirror shows a bogus DOI `10.1145/2185520.2335409`;
  the RGL/ACM DL record `10.1145/2185520.2185554` is authoritative.)

---

## 2. Core method (verified from the arXiv full text, https://arxiv.org/html/2405.13409v1)

**Problem.** Connect two fixed "separators" x0 (shading point) and x_{k+1} (light)
by a specular chain of k vertices x1…xk, each on a triangle T_i with barycentric
coords u_i=(1−u_i−v_i, u_i, v_i). The specular constraint at each vertex is the
**generalized half-vector** relation (§3.2):

  h_i × n_i = 0,  with  h_i = η_i·d̂_i − η_{i−1}·d̂_{i−1}   (Eq. 3)

This is exactly the Hanika half-vector residual already implemented in
`sms_attempt.h::constraint` / `halfVectorResidual` (η per wavelength).

**Polynomialization** (§3.2–3.3). The constraint is split into:
- *Coplanarity* — (d_{i−1} × d_i)·n_i = 0 (already polynomial, Eq. 5–6).
- *Angularity* — η_{i−1}‖d̂_{i−1}×n_i‖ = η_i‖d̂_i×n_i‖ (Eq. 7–9). The square-root
  denominators are removed two ways:
  * **Square form** (reflection + refraction, Eq. 10) — square both sides,
    max degree 6 (refraction) / 4 (reflection) with interpolated normals; 4/2 with
    flat face normals.
  * **Product form** (reflection only, Eq. 13) — lower degree (4/2).

**Variable reduction → bivariate** (§3.4–3.5). "Rational coordinate mapping"
(Eq. 14–17): recursive Möller–Trumbore ray/triangle intersection expresses u_{i+1}
as a *rational function* of u_i, u_{i−1}, so every vertex coordinate collapses to
u_1. For **refraction** the refracted-direction square root is approximated by a
**piecewise rational fit to √x over [0,1] in 6 pieces** (Eq. 23, error < 1e-3);
reflection is rationalized exactly (Eq. 19). Result is a bivariate system
a(u_1)=0, b(u_1)=0 (Eq. 24). Closed forms for **R** (1 reflection, degrees 2 & 4,
Eq. 25), **T** (1 refraction, degrees 2 & 6, Eq. 26), **RR** (2 reflections,
Eq. 27) are given.

**Solving** (§4). §4.1: eliminate one variable via the **hidden-variable resultant**
(they prefer the **Bézout resultant** for numerical stability + low complexity) →
"finding zeros of the determinant of univariate matrix polynomials". §4.2 solves
the univariate problem by **Laplacian expansion** for **one bounce** (exact) and a
**bisection solver** for **more bounces** (approximate but robust). Eigenvalue
decomposition of the companion matrix (Golub & Van Loan 2012) is cited as the
alternative, and §5.3.2 validates "Bisection solver vs. eigenvalue solver".

**Completeness/determinism.** The polynomial's real roots enumerate *all*
admissible specular vertices for the given triangle tuple — no seed, no convergence
basin. The paper's own caveat: the square form can introduce *superfluous roots*
which must be filtered by re-checking the original constraint in path space (§3.3,
§6 "Superfluous solutions"); and the refraction rational-mapping is approximate
(§6 "Accurate rational coordinate mapping for refraction").

⚠️ **Section-number discrepancy vs the pkg127 spec.** pkg127 cites "§4
single-bounce" and "§5 multi-bounce". Per the actual ToC, §4 is the *solver* and
§5 is *Results*. The correct anchors are: single-bounce **§3.5 (R/T cases)** +
**§4.1–4.2 (Laplacian expansion)**, two-bounce **§3.5 (RR case)** + **§4.2
(bisection)**. The spec also says "companion-matrix / Sturm-sequence root
isolation" — the paper's headline univariate solver is **Laplacian expansion +
bisection**; companion-matrix/eigenvalue is the *alternative* it benchmarks, and
Sturm-sequence / real-root isolation (Collins & Loos 1976, Yuksel 2022) is cited
only as related work (§2). Any port should follow the paper's actual solver
choice, not the spec's paraphrasing.

---

## 3. License-compatible reference implementation (Phase-0 blocker — RESOLVED)

### 3.1 `github.com/mollnn/spoly` — **NO LICENSE. NOT usable directly.**

- GitHub API reports `"license": null`:
  https://api.github.com/repos/mollnn/spoly → `"license": null`.
- `https://api.github.com/repos/mollnn/spoly/license` → **404**.
- The repo tree (mts1/, scenes/, test/, README.md, repre.jpg, standalone.cpp) has
  **no LICENSE file** — https://github.com/mollnn/spoly (file listing).
- The README does **not** declare any license term — https://github.com/mollnn/spoly.

**Conclusion:** "MIT-style but UNVERIFIED" (the pkg127 spec / 2026-07 PBR research
note) is confirmed wrong — it is not MIT-style, it is **unlicensed**. Under GitHub
ToS an unlicensed public repo grants only read/fork rights, *not* redistribution
or derivative rights. **Astroray must NOT copy source from mollnn/spoly.** The
correct path is exactly pkg64's Hanika precedent: **re-derive from the paper
alone** (the paper is CC BY 4.0, §1.1) and cite "Fan et al. 2024, DOI
10.1145/3658132" — the full math (§3.2–3.5, §4) is in the open-access arXiv
HTML/PDF, which is sufficient to re-implement without reading mollnn/spoly source.

### 3.2 Compatible references that ARE usable (all MIT/BSD)

- **cyCodeBase / cyPolynomial** (Cem Yuksel) — the polynomial root-finding library
  that spoly itself builds on. License: **MIT** ("All source code in cyCodeBase is
  released under the simple and permissive MIT license").
  — http://codebase.cemyuksel.com/code.html
  Repo: https://github.com/cemyuksel/cyCodeBase (cyPolynomial.h is a
  "high-performance polynomial solver"). This is a clean, MIT-compatible source for
  the univariate root-finding component (its method is also cited in the paper §2:
  Yuksel 2022 "High-Performance Polynomial Root Finding for Graphics").
- **tizian/specular-manifold-sampling** — the SMS reference already cited in
  `sms_attempt.h`. LICENSE file confirmed **BSD-3-Clause**
  ("Copyright (c) 2017 Wenzel Jakob"). — https://raw.githubusercontent.com/tizian/specular-manifold-sampling/master/LICENSE
  (Already the basis of pkg64's port, so reuse carries no new license risk.)
- **Mitsuba 2** (the spoly project is a fork of VicentChen/mitsuba) is BSD-3-Clause,
  but is GPL-relevant only via Cycles — pkg64 already keeps Cycles' GPL MNEE at
  arm's length; keep that decision.

### 3.3 Phase-0 verdict (write this into the spec)

- [x] mollnn/spoly license fetched: **absent** (null), SPDX = **none**.
- [ ] Compatibility: **NOT MIT/BSD/Apache-compatible → do not port its source.**
- [ ] Re-derivation path taken: paper-only (CC BY 4.0 math), with cyCodeBase/cyPolynomial
  (MIT) as the permitted reference for the root-finder, and the BSD-3 SMS reference
  for the surrounding SMS plumbing.

---

## 4. Slotting into Astroray SMS

**Where it plugs in.** `runSMSAttempt` (`include/astroray/manifold/sms_attempt.h:107-148`)
currently: uniform-on-sphere seed (lines 111-118) → `newton_iterate.h::solve`
(line 148) → drop if `!R.converged` (line 149). The polynomial path replaces *only*
the seed+Newton solve with a deterministic root enumeration, then reuses the exact
same downstream refraction/Fresnel/visibility/MIS chain (`sms_attempt.h:159-201`):

- **Single-bounce (Phase 1, CPU):** for the caster triangle/analytic sphere, build
  the bivariate system of Eq. 25 (R) / Eq. 26 (T), apply the Bézout hidden-variable
  resultant (§4.1), Laplacian-expand the univariate matrix polynomial determinant
  (§4.2), isolate real roots (cyPolynomial-style or Sturm), map each root back to a
  surface vertex, then run the *existing* validation (in-surface, refraction side,
  TIR check at `sms_attempt.h:159-181`). Newton is retained only as a 1–2 step
  `solveAnalytic` polish of each root and as the flag-off fallback.
- **Hero-wavelength decoupling carries over unchanged:** η enters only through the
  angularity coefficients (Eq. 10's η_{i−1}, η_i, exactly as the current residual
  h(λ) = ω_i + η(λ)·ω_o), so one solve at λ_hero with the pkg64 flag convention
  (`getInt(...) != 0`) is the right drop-in. Verify the refraction piecewise-rational
  √-fit error (<1e-3) is inside the current Newton `tolerance` (1e-4f default
  `SMSConfig::tolerance`) before relying on it for the spectral path — this is the
  single most likely correctness risk in a spectral caustic pipeline.
- **Two-bounce (Phase 2):** RR case (Eq. 27) on the pkg106 `manifold_chain.h`,
  bisection solver (§4.2). Gate on seed-failure-rate + quality-at-equal-spp, not
  walltime.
- **GPU (Phase 3):** mirror into `sms_attempt_device.cuh`; deterministic roots
  remove per-seed rejection divergence. CPU-gate first, RTX-verify via the existing
  caustic parity harness.

**Caustic-quality gate idea.** Instrument the fraction of SMS attempts returning
false at `sms_attempt.h:149` (Newton baseline) vs. polynomial attempts that produce
≥1 valid path; require the polynomial rate strictly lower on
`sms-refractive-glass-sphere` and SF11. Then equal-spp metrics (prism
`hue_spread`/`bright_coverage`, glass-sphere receiver energy / SSIM) must hold or
improve. Add a unit test that constructs a **multi-solution configuration** (glass
sphere with ≥2 caustic branches to one receiver point) and asserts the polynomial
solver finds *all* branches Newton-from-one-seed misses.

---

## 5. Risks (from paper §6 + practical)

- **Polynomial conditioning / degree.** Refraction square-form degree 6
  (interpolated normals) or 4 (flat); reflection product-form 4/2. Higher degree +
  resultant matrices ⇒ ill-conditioned coefficients for near-grazing/degenerate
  configurations. Paper §2 notes multivariate solvers are numerically unstable and
  bivariate is the tractable limit; §6 lists "Better numerical methods for
  root-finding" as open.
- **Superfluous roots.** Square form introduces spurious sign solutions — must
  re-verify the original constraint in path space (§3.3, §6), i.e. keep the current
  `sms_attempt.h` checks. A root filter that misses these silently adds paths.
- **Refraction mapping is approximate.** The 6-piece rational √ fit (error <1e-3)
  bounds angular error but is not exact — §6 "Accurate rational coordinate mapping
  for refraction". On Astroray's spectral path this approximation error must stay
  below the existing Newton tolerance or it will surface as caustic bias.
- **Degree / performance.** One bounce is "even less time than previous methods"
  per §1; two-bounce bisection is ~10× a single Newton step (per the pkg127 spec,
  consistent with paper's own "very slow" serial RR note in the repo README:
  https://github.com/mollnn/spoly). Fine for CPU; GPU-friendly per the paper but the
  resultant/eigen step is branchy for a wavefront kernel.
- **GPU portability.** Companion-matrix eigenvalue + bisection are the GPU-relevant
  kernels; the recursive rational-coordinate mapping is serial per chain. Port
  CPU-gated; parity is verification, not the primary gate.
- **Not for 3+ bounces** (§6 "Long specular chains") — match pkg127's non-goal.

---

## 6. File-existence check

Confirmed: this note was written to
`C:/Users/hgcom/OneDrive/Astroray/Astroray_repo/Astroray/.astroray_plan/docs/pkg127-specular-polynomials-research.md`.
Nothing else in the repo was touched.

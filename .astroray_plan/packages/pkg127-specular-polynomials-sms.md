# pkg127 — Specular Polynomials for SMS seed finding (deterministic, Newton-free seeds)

**Pillar:** 3 (light transport / caustics) + 2 (spectral core)
**Track:** A (CPU-first seed-stage upgrade with numerical caustic-quality gates; the GPU/wavefront SMS mirror is RTX-verified against the CPU result)
**Status:** open — spec DETAILED 2026-09-03 from a web-verified research note (`.astroray_plan/docs/pkg127-specular-polynomials-research.md`, every citation checked against a live URL). Ready to dispatch (Claude/careful tier). The highest-value *bounded* caustics-quality upgrade on the roadmap.
**Estimated effort:** L — single-bounce polynomial solver + seed-stage integration, then the two-bounce extension; a license phase-0, a paper re-derivation, and a before/after seed-failure measurement.
**Depends on:** **pkg64** (SMS folded into the default spectral path — DONE; this upgrades its seed stage), **pkg106** (multi-vertex manifold-chain foundation — the two-bounce leg uses `include/astroray/manifold/manifold_chain.h`). No hard blocker: a flag-gated drop-in on landed code, Newton seeding stays the fallback.

---

## Goal

Replace SMS's **random-init Newton seed** (uniform-on-sphere start → iterate → drop
on non-convergence) with the **deterministic all-roots polynomial seed** of Fan et
al. 2024: reformulate the specular-chain half-vector constraint as a polynomial
system whose **real roots enumerate every admissible specular vertex** for a given
triangle tuple — no seed, no convergence basin, no missed caustic branches. Newton
is retained only as (a) a 1–2 step polish of each root and (b) the flag-off fallback.

**Why now.** SMS-from-one-Newton-seed silently misses caustic branches when a
receiver point has multiple specular connections (a glass sphere focusing ≥2
paths to one point), producing grainy/incomplete caustics that no amount of spp
fixes. The polynomial solver finds *all* branches deterministically — a bounded,
high-value quality upgrade on the already-landed SMS path, flag-gated so it can
never regress the fleet.

---

## Citations (web-verified 2026-09-03 — the prior spec's cite line was WRONG)

- **Fan, Guo, Wang, Xiao, Zhang, Zhou, Chen, Hong, Guo, Yan 2024 — "Specular
  Polynomials."** ACM TOG 43(4) (SIGGRAPH 2024), Article 126, 13 pp.
  **DOI 10.1145/3658132** · arXiv:2405.13409 · project https://zhiminfan.work/specPoly.html.
  ⚠️ The prior filing's "Fan, Wang, Dong, Wang, Hašan, Yan et al." is **incorrect** —
  Hašan is not an author; the authors are Zhimin **Fan**, Jie **Guo**, … Ling-Qi
  **Yan** (10 total). Use the corrected list + DOI above in all code citations.
- **Zeltner, Georgiev, Jakob 2020 — "Specular Manifold Sampling"** (SMS), ACM TOG
  39(4) Art. 149. DOI 10.1145/3386569.3392408. Ref code
  `github.com/tizian/specular-manifold-sampling` (**BSD-3-Clause**, already the
  basis of pkg64).
- **Hanika, Droske, Fascione 2015 — "Manifold Next Event Estimation"** (MNEE),
  CGF 34(4) 87–97. DOI 10.1111/cgf.12681. (The half-vector residual Astroray
  already implements.)
- **Jakob & Marschner 2012 — "Manifold Exploration."** ACM TOG 31(4) 58. DOI
  10.1145/2185520.2185554.

## License phase-0 (RESOLVED — do NOT copy the paper's reference code)

- `github.com/mollnn/spoly` (the paper's supplemental code) is **UNLICENSED** —
  GitHub API `"license": null`, no LICENSE file, README declares no terms. Under
  GitHub ToS an unlicensed public repo grants read/fork only, **not** derivative
  rights. The prior note's "MIT-style but unverified" is confirmed **wrong**.
  **Astroray must not copy source from mollnn/spoly.**
- **Path taken (pkg64's Hanika precedent): re-derive the math from the paper
  alone** — it is **CC BY 4.0** (open-access arXiv), which permits re-derivation +
  a `DOI 10.1145/3658132` citation. Permitted supporting references:
  - **cyCodeBase / `cyPolynomial.h`** (Cem Yuksel) — **MIT** — for the univariate
    real-root solver (the paper cites Yuksel 2022; spoly itself builds on it).
    http://codebase.cemyuksel.com/code.html
  - **tizian/specular-manifold-sampling** — **BSD-3-Clause** — the SMS plumbing
    already in `sms_attempt.h`.

---

## Algorithm (implementation altitude — from arXiv:2405.13409 full text)

Connect fixed separators x0 (shading point) and x_{k+1} (light) by a specular
chain x1…xk on triangles T_i. Per-vertex constraint = the **generalized
half-vector** relation `h_i × n_i = 0`, `h_i = η_i·d̂_i − η_{i−1}·d̂_{i−1}` (paper
Eq. 3) — **exactly** the residual in `sms_attempt.h::halfVectorResidual` (η per
wavelength).

1. **Polynomialize the constraint** (§3.2–3.3): split into *coplanarity*
   `(d_{i−1}×d_i)·n_i = 0` (already polynomial) + *angularity*
   `η_{i−1}‖d̂_{i−1}×n_i‖ = η_i‖d̂_i×n_i‖`; remove the √ via the **square form**
   (reflection+refraction, max degree 6 refraction / 4 reflection with interpolated
   normals; 4/2 flat) — the paper's general choice — or the lower-degree **product
   form** (reflection only, 4/2).
2. **Reduce to bivariate** (§3.4–3.5): "rational coordinate mapping" expresses each
   u_{i+1} as a rational function of u_i,u_{i−1} via recursive Möller–Trumbore, so
   the whole chain collapses to u_1. Refraction's refracted-direction √ is a
   **6-piece piecewise-rational fit to √x on [0,1]** (Eq. 23, error < 1e-3);
   reflection is exact (Eq. 19). Closed forms are given for **R** (Eq. 25),
   **T** (Eq. 26), **RR** (Eq. 27).
3. **Solve** (§4): eliminate one variable via the **Bézout hidden-variable
   resultant** (their stability/complexity choice) → zeros of the determinant of a
   univariate matrix polynomial; solve the univariate problem by **Laplacian
   expansion for one bounce (exact)** and a **bisection solver for two bounces**.
   (Companion-matrix eigenvalue decomposition is the benchmarked *alternative*, not
   the headline method — the prior spec's "companion-matrix/Sturm" paraphrase is
   corrected here.)
4. **Completeness + superfluous roots.** The real roots enumerate *all* admissible
   specular vertices — no seed. BUT the square form can introduce **superfluous
   roots** (spurious sign solutions) that MUST be filtered by re-checking the
   original constraint in path space (§3.3, §6) — i.e. keep the existing
   in-surface / refraction-side / TIR checks.

> **Spec-anchor correction (from the note):** the prior filing cited "§4
> single-bounce / §5 multi-bounce". Per the real ToC, §4 = the solver, §5 =
> Results. Correct anchors: single-bounce **§3.5 (R/T) + §4.1–4.2**; two-bounce
> **§3.5 (RR) + §4.2 (bisection)**.

---

## Astroray integration (file:line anchors)

`runSMSAttempt` (`include/astroray/manifold/sms_attempt.h:107-148`) today: uniform
seed (:111-118) → `newton_iterate.h::solve` (:148) → drop on `!R.converged`
(:149). The polynomial path replaces **only the seed+solve**; it reuses the exact
downstream refraction/Fresnel/visibility/MIS chain (:159-201) unchanged.

- **Phase 1 — single-bounce, CPU (the core deliverable).** For the caster
  triangle / analytic sphere, build the bivariate system (Eq. 25 R / Eq. 26 T),
  Bézout resultant (§4.1), Laplacian-expand the determinant (§4.2), isolate real
  roots with the **MIT cyPolynomial** solver, map each root → surface vertex, run
  the **existing** validation (`sms_attempt.h:159-181`). Newton = 1–2 step polish +
  flag-off fallback. Flag convention per pkg64 (`p.getInt("sms_polynomial_seed",0)!=0`),
  default OFF ⇒ byte-identical to current SMS.
- **Hero-wavelength decoupling carries over unchanged:** η enters only through the
  angularity coefficients, so one solve at λ_hero (pkg64 convention) is the drop-in.
  **Verify** the 6-piece rational √-fit error (<1e-3) is inside the current Newton
  `SMSConfig::tolerance` (1e-4f) before trusting it on the spectral path — this is
  the single biggest correctness risk in a spectral caustic pipeline.
- **Phase 2 — two-bounce (CPU).** RR case (Eq. 27) on `manifold_chain.h`, bisection
  solver (§4.2). Gate on seed-failure-rate + equal-spp quality, NOT walltime.
- **Phase 3 — GPU.** Mirror into `sms_attempt_device.cuh`; deterministic roots
  remove per-seed rejection divergence. CPU-gate first, then RTX-verify via the
  existing caustic parity harness. The resultant/eigen step is branchy for a
  wavefront kernel — treat GPU as verification, not the primary gate; defer if it
  perturbs the register budget.

---

## Acceptance gates

1. **Seed-completeness (the headline).** A new unit test builds a **multi-solution
   configuration** (glass sphere with ≥2 caustic branches to one receiver point)
   and asserts the polynomial solver returns **all** branches that Newton-from-one-
   seed misses.
2. **Seed-failure-rate down.** Fraction of SMS attempts returning false at
   `sms_attempt.h:149` (Newton baseline) must be strictly lower for the polynomial
   path on `sms-refractive-glass-sphere` and SF11.
3. **Equal-spp caustic quality holds or improves.** Prism `hue_spread` /
   `bright_coverage`, glass-sphere receiver energy / SSIM — LINEAR EXR, seed-pinned.
4. **Superfluous-root safety.** Assert no spurious paths pass validation (the
   path-space re-check catches all square-form artifacts); furnace / energy on a
   non-caustic scene unchanged.
5. **Flag-off byte-identical.** `sms_polynomial_seed=0` produces the current SMS
   result bit-for-bit (CPU) / within-MC (GPU) — the fleet never pays.

---

## Risks (paper §6 + practical)

- **Conditioning / degree.** Refraction square-form degree 6 (interp normals) / 4
  (flat) + resultant matrices ⇒ ill-conditioned for near-grazing/degenerate
  configs; the paper flags "better numerical root-finding" as open.
- **Refraction mapping is approximate** (6-piece √ fit, <1e-3) — must stay under
  the Newton tolerance or it surfaces as caustic bias on the spectral path.
- **Superfluous roots** — keep the path-space re-check; a lax filter silently adds
  energy.
- **Perf.** One bounce is faster than Newton-from-seed; two-bounce bisection ~10× a
  Newton step (fine on CPU). GPU resultant/eigen is branchy.
- **Non-goal: 3+ bounce chains** (paper §6 "long specular chains") — out of scope.

## Non-goals
- No GPU-primary path in Phase 1–2 (CPU-gated; GPU is Phase 3 verification).
- No copying mollnn/spoly source (unlicensed — re-derive from the CC-BY paper).
- No 3+ specular bounces.

## Routing
Claude / careful tier (license judgment, math re-derivation, caustic-quality gate,
register/ABI on the GPU leg). The cite/research phase is DONE (web-verified note).

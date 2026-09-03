# pkg127 — Specular Polynomials for SMS seed finding (deterministic, Newton-free seeds)

**Pillar:** 3 (light transport / caustics) + 2 (spectral core)
**Track:** A (CPU-first seed-stage upgrade with numerical caustic-quality gates; the GPU/wavefront SMS mirror is RTX-verified against the CPU result)
**Codex-paste-ready:** no (research-grade algorithm port with a license-verification gate, a math re-derivation from the paper, and a caustic-quality acceptance bar — needs judgment at each step, not a mechanical patch)
**Status:** open — spec DETAILED 2026-09-03 from a web-verified research note (`.astroray_plan/docs/pkg127-specular-polynomials-research.md`, every citation checked against a live URL). Ready to dispatch (Claude/careful tier). The highest-value *bounded* caustics-quality upgrade on the roadmap (per `.astroray_plan/docs/2026-07-pbr-advances-research.md` headline finding 1).
**Estimated effort:** L — single-bounce polynomial solver + integration into the existing seed stage, then the two-bounce extension; a license phase-0, a paper re-derivation, and a before/after seed-failure measurement.
**Depends on:** **pkg64** (SMS folded into the default spectral path — DONE; this upgrades its seed stage) and **pkg106** (multi-vertex MNEE/manifold-chain foundation — the two-bounce leg builds on `include/astroray/manifold/manifold_chain.h`). No hard blocker: a flag-gated drop-in on landed code, Newton seeding stays the fallback.

---

## Goal

**Before:** Astroray's caustics come from Specular Manifold Sampling (SMS, Zeltner
2020) folded into the default spectral path tracer (pkg64). Seed finding is a
**stochastic-seed + Newton-solve** loop: `runSMSAttempt`
(`include/astroray/manifold/sms_attempt.h:107-148`) draws a **uniform-on-sphere**
seed on the caster (`nSeed`, :111-118, Zeltner 2020 §4.4), then Newton-iterates to
convergence (`include/astroray/manifold/newton_iterate.h::solve`, called at
`sms_attempt.h:148`). A non-converging seed is dropped —
`if (!R.converged) return false;` (`sms_attempt.h:149`). Two failure modes the
Specular Polynomials paper was written to kill:

1. **Divergence from a bad seed.** Newton has a finite convergence basin; a seed
   outside it diverges or stalls (`newton_iterate.h:106-107` bails on a singular
   Jacobian, `:82` on non-convergence within `maxIterations`). On triangulated
   casters the basin shrinks further because ±h finite-difference steps cross
   triangle edges into neighbours with different normals (the pkg106
   SMS-fails-on-triangles failure, `newton_iterate.h:121-131`); the
   analytic-Jacobian path (`solveAnalytic`, `:151`) mitigates but doesn't eliminate it.
2. **One solution per seed.** Each seed reaches at most one manifold vertex.
   Admissible paths whose vertices sit in a different basin are missed unless a
   *different* seed happens to land near them — so multi-solution configurations (a
   glass sphere focusing several caustic branches to one receiver point, an SF11
   prism) need many seeds and still under-sample, showing up as seed-failure waste
   and residual caustic noise.

**After:** The SMS seed stage finds specular-chain solutions by **deterministic
polynomial root-finding** (Fan et al. SIGGRAPH 2024) instead of a stochastic-seed
Newton search. For the **single-bounce** case the reflection/refraction constraint
becomes a univariate polynomial whose **real roots enumerate every admissible
manifold vertex — no seed, no divergence, every branch found in one solve**. For
**two bounces** a bivariate system is reduced by the hidden-variable resultant to
univariate root-finding, robust where Newton's basin fails. Newton is retained only
as an optional root-polish/fallback behind a flag. Caustic quality on the refbank
glass/prism scenes is **equal-or-better at equal spp**, and the measured
**seed-failure rate drops**.

---

## Context — why this is the top caustics upgrade

The 2026-07-17 PBR sweep ranked four independent 2023–2026 specular/caustic lines
and put Specular Polynomials first for Astroray specifically: *"a targeted drop-in
upgrade for the SMS seed-finding stage (pkg64/pkg106 lineage) … the highest-value
bounded upgrade to what we already have"*
(`.astroray_plan/docs/2026-07-pbr-advances-research.md` finding 1). Bounded because
it replaces exactly one stage — seed finding — inside a shipping integrator, not a
new subsystem (unlike ReSTIR-PT or path guiding). The visual payoff is directly on
the owner's showcase scenes: `prism-bk7-collimated`, `prism-sf11-collimated`,
`sms-refractive-glass-sphere` — the journal-article caustic figures. Deterministic
root-finding is also the natural GPU fit: no per-seed rejection divergence.

---

## Citations (web-verified 2026-09-03 — the prior filing's cite line was WRONG)

- **Fan, Guo, Wang, Xiao, Zhang, Zhou, Chen, Hong, Guo, Yan 2024 — "Specular
  Polynomials."** ACM TOG 43(4) (SIGGRAPH 2024), Article 126, 13 pp.
  **DOI 10.1145/3658132** · arXiv:2405.13409 · https://zhiminfan.work/specPoly.html.
  ⚠️ The prior filing's "Fan, Wang, Dong, Wang, Hašan, Yan et al." is **incorrect** —
  Hašan is not an author; the authors are Zhimin **Fan**, Jie **Guo**, … Ling-Qi
  **Yan** (10 total). Use the corrected list + DOI in all code citations.
- **Zeltner, Georgiev, Jakob 2020 — "Specular Manifold Sampling"** (SMS), ACM TOG
  39(4) Art. 149. DOI 10.1145/3386569.3392408. Ref code
  `github.com/tizian/specular-manifold-sampling` (**BSD-3-Clause**, already the basis
  of pkg64).
- **Hanika, Droske, Fascione 2015 — "Manifold Next Event Estimation"** (MNEE), CGF
  34(4) 87–97. DOI 10.1111/cgf.12681. (The half-vector residual Astroray implements.)
- **Jakob & Marschner 2012 — "Manifold Exploration."** ACM TOG 31(4) 58. DOI
  10.1145/2185520.2185554.

---

## Fix plan (cite — no inventions, CLAUDE.md §6)

### Phase 0 — license verification (RESOLVED here; re-confirm at port)

- `github.com/mollnn/spoly` (the paper's supplemental code) is **UNLICENSED** —
  GitHub API `"license": null`, no LICENSE file, README declares no terms. Under
  GitHub ToS an unlicensed public repo grants read/fork only, **not** derivative
  rights. The 2026-07 note's "MIT-style — VERIFY" is confirmed **wrong: it is
  unlicensed. Astroray must NOT copy source from mollnn/spoly.**
- **Path taken (pkg64's Hanika precedent): re-derive the math from the paper alone**
  — the paper is **CC BY 4.0** (open-access arXiv:2405.13409 carries the full math),
  which permits re-derivation + a `DOI 10.1145/3658132` citation. Permitted
  supporting references:
  - **cyCodeBase / `cyPolynomial.h`** (Cem Yuksel) — **MIT** — for the univariate
    real-root solver (the paper cites Yuksel 2022; spoly itself builds on it).
    http://codebase.cemyuksel.com/code.html
  - **tizian/specular-manifold-sampling** — **BSD-3-Clause** — the SMS plumbing
    already in `sms_attempt.h`.
- [ ] Re-confirm the mollnn/spoly LICENSE state at implementation time (still absent)
      and record the SPDX + decision in the research note; if it ever gains a
      compatible license, cyPolynomial-first re-derivation still stands.

### Phase 1 — single-bounce polynomial seed finding (CPU first)

- Reformulate the single-vertex constraint currently solved by Newton
  (`sms_attempt.h::halfVectorResidual`, `h(λ) = ω_i + η(λ)·ω_o`, ~:124-128) as the
  paper's polynomial system (§3.2–3.5). Split the half-vector constraint into
  *coplanarity* `(d_{i−1}×d_i)·n_i = 0` (already polynomial, Eq. 5–6) + *angularity*
  `η_{i−1}‖d̂_{i−1}×n_i‖ = η_i‖d̂_i×n_i‖`; remove the √ with the **square form**
  (reflection+refraction, degree 6 refraction / 4 reflection with interpolated
  normals; 4/2 flat, Eq. 10) or the lower-degree **product form** (reflection only,
  Eq. 13). The refracted-direction √ is a **6-piece piecewise-rational fit to √x on
  [0,1]** (Eq. 23, error < 1e-3); reflection is exact (Eq. 19). Closed forms: **R**
  (Eq. 25), **T** (Eq. 26).
- **Solve** (§4): Bézout hidden-variable resultant → zeros of the determinant of a
  univariate matrix polynomial; **Laplacian expansion (exact) for one bounce**;
  isolate real roots with the **MIT `cyPolynomial`** solver. Map each root → surface
  vertex; validate with the *existing* in-surface / refraction-side / TIR checks
  (`sms_attempt.h:159-181`). **Companion-matrix eigenvalue is the paper's benchmarked
  alternative, not the headline solver** (correcting the prior spec's paraphrase).
- **Superfluous roots:** the square form introduces spurious sign solutions (§3.3,
  §6) — the path-space re-check MUST filter them; a lax filter silently adds energy.
- **Flag-gated** (pkg64 convention, `p.getInt("sms_polynomial_seed",0) != 0`),
  default OFF ⇒ current uniform-seed Newton stays the fallback until the gates prove
  the replacement. **Hero-wavelength decoupling carries over unchanged:** η enters
  only through the angularity coefficients, so one solve per ray at `λ_hero`, written
  to the hero channel — same as today. Retain Newton as an optional 1–2 step
  `solveAnalytic` polish of each root (root-finding gives the basin; Newton polishes
  the last digits).
- **Verify** the 6-piece √-fit error (<1e-3) is inside the current
  `SMSConfig::tolerance` (1e-4f) before trusting it on the spectral path — the single
  biggest correctness risk in a spectral caustic pipeline.

### Phase 2 — two-bounce (build on the pkg106 manifold chain)

- Extend to the two-vertex chain (`include/astroray/manifold/manifold_chain.h`,
  pkg106) via the **RR closed form (Eq. 27)** + the hidden-variable resultant, solved
  by the paper's **bisection solver (§4.2)**. Largest robustness win over Newton
  (multi-solution glass-sphere / double-refraction prism). Two-bounce bisection ~10×
  a single Newton step (paper) — **gate on quality-at-equal-spp and seed-failure-rate,
  NOT solver walltime.**

### Phase 3 — GPU/wavefront mirror

- Mirror the single-bounce solver into `include/astroray/manifold/sms_attempt_device.cuh`
  and RTX-verify against the CPU result via the caustic parity harness
  (`tests/test_gpu_caustic_parity.py`, `tests/test_pkg64_gpu_sms_attempt_unit.py`).
  Deterministic roots remove per-seed rejection divergence — a natural GPU fit — but
  keep the port CPU-gated first; GPU parity is verification, not the primary gate. The
  resultant/eigen step is branchy for a wavefront kernel; if it perturbs the REG:254
  shade/SMS register budget, isolate or defer.

---

## Acceptance criteria

- [ ] **Phase 0 license recorded:** mollnn/spoly LICENSE state (absent) + SPDX +
      compatibility decision written into
      `.astroray_plan/docs/pkg127-specular-polynomials-research.md`; the paper-only
      re-derivation path is the one taken (no source copied under an absent license).
- [ ] **Single-bounce exact:** the polynomial solver enumerates all admissible
      single-bounce manifold vertices on the analytic glass-sphere caster; a unit test
      confirms it finds solutions Newton-from-uniform-seed misses on a **multi-solution
      configuration** (≥2 caustic branches to one receiver point).
- [ ] **Caustic-quality gates equal-or-better at equal spp:** `prism-bk7-collimated`,
      `prism-sf11-collimated`, `sms-refractive-glass-sphere`
      (`benchmarks/reference_bank/scenes/*/gates.toml`) hold or improve (prism
      `hue_spread`/`bright_coverage`; glass-sphere receiver energy / SSIM) at the same
      spp as current Newton seeding — no regression on `sms-reflective-metal-sphere`.
      LINEAR EXR, seed-pinned.
- [ ] **Seed-failure rate measured before/after (headline quantitative gate):**
      instrument the valid-path fraction (the `return false` drop rate at
      `sms_attempt.h:149`) on glass-sphere + SF11; the polynomial rate must be
      **strictly lower** than the Newton baseline.
- [ ] **Superfluous-root safety:** no spurious path passes validation (the path-space
      re-check catches all square-form artifacts); furnace/energy on a non-caustic
      scene unchanged.
- [ ] **Two-bounce lands second:** the RR resultant + bisection solver passes a
      double-refraction convergence unit test where Newton stalls; a distinct phase so
      single-bounce ships first.
- [ ] **No regression with the flag off:** default integrator (flag off) is bit-equal
      to the pre-pkg127 SMS path — `tests/test_sms_caustic_validation.py`,
      `tests/test_sms_caustic_spectral.py`, `tests/test_glass_sphere_caustic.py`,
      `tests/test_prism_caustic_rainbow.py` unchanged.
- [ ] **GPU parity:** wavefront single-bounce solver matches the CPU result on
      `tests/test_gpu_caustic_parity.py`; RTX-verified.
- [ ] **Citations in code:** every polynomial-solver call site cites "Fan et al. 2024
      (Specular Polynomials) §3.5/§4, DOI 10.1145/3658132" + the license-verified
      provenance (paper-derived; cyPolynomial MIT for the root-finder), per CLAUDE.md §6.

---

## Non-goals

- **Not a replacement for SMS as a whole.** Upgrades the **seed-finding stage** only;
  the refraction/Fresnel/visibility/MIS chain (`sms_attempt.h:159-201`) is untouched,
  Newton stays as an optional root-polish + flagged fallback.
- **Not the forward light-tracing prism path** (pkg106 `light_tracer_caustic`). This
  targets the camera-side SMS seed stage (`runSMSAttempt`).
- **Not three-plus bounces** (paper §6 "long specular chains") — single-bounce first,
  two-bounce second.
- **Not ReSTIR / partitioned SMS** (Hong et al. 2025, research finding 2 — presupposes
  pkg55-C ReSTIR reservoirs; separate later package).
- **Not glint rendering.** Out of scope, as in pkg64.
- **Do NOT copy mollnn/spoly source** (unlicensed — re-derive from the CC-BY paper).
- **No invented root-finder** — port the published method, cite it, verify its license
  (CLAUDE.md §6).

---

## Provenance

Filed from the **2026-07-17 PBR-advances research sweep**
(`.astroray_plan/docs/2026-07-pbr-advances-research.md`, finding 1, verified 3-0),
which ranked Specular Polynomials the top directly-adoptable caustics upgrade for
Astroray's existing SMS pipeline and flagged the mollnn/spoly license as needing
verification at port. Detailed 2026-09-03 from a **web-verified phase-0 research
note** (`pkg127-specular-polynomials-research.md`) — deepseek-v4-pro via the opencode
`architect` agent (webfetch+websearch) under a strict web-verify-or-NOT-FOUND
contract, then this spec by Claude — which corrected the author citation, resolved
the license (mollnn/spoly unlicensed → paper re-derivation + MIT cyPolynomial), and
fixed the paper §-anchors. Grounded against the live SMS seed stage
(`include/astroray/manifold/sms_attempt.h` + `newton_iterate.h`) from pkg64 (SMS in
the default path) and pkg106 (multi-vertex manifold chain). Owner context: the prism
rainbow and glass-sphere caustic are journal-article caustic figures and
spectral-showcase scenes — deterministic, exact seed finding is what makes them clean
at production spp.

---

## Progress

- [ ] Phase 0 — mollnn/spoly license re-confirmed absent; paper-only re-derivation +
      MIT cyPolynomial recorded.
- [ ] Phase 1 — single-bounce univariate polynomial solver (Bézout resultant +
      Laplacian expansion + cyPolynomial), CPU, behind a flag; Newton retained as
      root-polish/fallback.
- [ ] Phase 2 — two-bounce RR resultant + bisection on the pkg106 manifold chain.
- [ ] Phase 3 — GPU/wavefront mirror; caustic parity RTX-verified.
- [ ] Seed-failure-rate before/after measured on glass-sphere + SF11.

---

## Lessons

*(Fill in after the package is done.)*

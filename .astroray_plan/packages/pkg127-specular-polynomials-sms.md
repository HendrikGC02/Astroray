# pkg127 — Specular Polynomials for SMS seed finding (deterministic, Newton-free seeds)

**Pillar:** 3 (light transport / caustics) + 2 (spectral core)
**Track:** A (CPU-first seed-stage upgrade with numerical caustic-quality gates; the GPU/wavefront SMS mirror is RTX-verified against the CPU result)
**Codex-paste-ready:** no (research-grade algorithm port with a license-verification gate, a math re-derivation from the paper, and a caustic-quality acceptance bar — needs judgment at each step, not a mechanical patch)
**Status:** still-open — never implemented; no specular-polynomial/SMS-seed code in the repo, only the spec-filing PR #491. Was: open — the highest-value bounded caustics-quality upgrade on the roadmap (per `.astroray_plan/docs/2026-07-pbr-advances-research.md` headline finding 1)
**Estimated effort:** L (single-bounce polynomial solver + integration into the existing seed stage, then the two-bounce extension; a license phase-0, a paper re-derivation, and a before/after seed-failure measurement)
**Depends on:** **pkg64** (SMS folded into the default spectral path — DONE; this package upgrades its seed stage) and **pkg106** (multi-vertex MNEE/manifold-chain foundation — the two-bounce leg builds on `include/astroray/manifold/manifold_chain.h`). No hard blocker: this is a drop-in upgrade to landed code, gated behind a flag so the current Newton seeding stays the fallback.

---

## Goal

**Before:** Astroray's caustics come from Specular Manifold Sampling (SMS, Zeltner
2020) folded into the default spectral path tracer (pkg64). Seed finding is a
**stochastic-seed + Newton-solve** loop: `runSMSAttempt`
(`include/astroray/manifold/sms_attempt.h:107-148`) draws a **uniform-on-sphere**
seed on the caster (`nSeed`, lines 111-118, Zeltner 2020 §4.4), then runs
Newton iteration to convergence
(`include/astroray/manifold/newton_iterate.h::solve`, called at
`sms_attempt.h:148`). A seed that does not converge is simply dropped —
`if (!R.converged) return false;` (`sms_attempt.h:149`). This has the two failure
modes the Specular Polynomials paper was written to kill:

1. **Divergence from a bad seed.** Newton has a finite convergence basin; a seed
   outside it diverges or stalls (`newton_iterate.h:106-107` bails on a singular
   Jacobian, `:82` on non-convergence within `maxIterations`). On triangulated
   casters the basin shrinks further because ±h finite-difference steps cross
   triangle edges into neighbours with different normals (the pkg106
   SMS-fails-on-triangles failure, documented at `newton_iterate.h:121-131`); the
   analytic-Jacobian path (`solveAnalytic`, `newton_iterate.h:151`) mitigates but
   does not eliminate the basin problem.
2. **One solution per seed.** Each seed can reach at most one manifold vertex.
   Admissible specular paths whose vertices sit in a different basin are missed
   unless a *different* seed happens to land near them — so multi-solution
   configurations (a glass sphere focusing several caustic branches to one
   receiver point, an SF11 prism with strong dispersion) need many seeds and still
   under-sample, showing up as seed-failure waste and residual caustic noise.

**After:** The SMS seed stage finds specular-chain solutions by **deterministic
polynomial root-finding** (Specular Polynomials, Fan et al. SIGGRAPH 2024) instead
of a stochastic-seed Newton search. For the **single-bounce** case the reflection/
refraction constraint is reformulated as a univariate polynomial whose **real roots
enumerate every admissible manifold vertex exactly** — no seed, no divergence,
every solution branch found in one solve. For **two bounces** a bivariate system is
reduced by the hidden-variable resultant to univariate root-finding, robust where
Newton's basin fails (the paper reports the two-bounce GPU solver is ~10× the cost
of a single Newton step but far more robust). Newton is retained only as an optional
refinement/fallback behind a flag. Caustic quality on the refbank glass/prism scenes
is **equal-or-better at equal spp**, and the measured **seed-failure rate drops**.

---

## Context — why this is the top caustics upgrade

The 2026-07-17 PBR sweep ranked four independent 2023–2026 lines of specular/caustic
transport work and put Specular Polynomials first for Astroray specifically:
*"a targeted drop-in upgrade for the SMS seed-finding stage (pkg64/pkg106
lineage)"* and, in the adoption recommendation, *"the highest-value bounded upgrade
to what we already have"*
(`.astroray_plan/docs/2026-07-pbr-advances-research.md` finding 1 + §"Adoption
recommendation"). It is bounded because it replaces exactly one stage — seed finding
— inside an integrator that already ships, rather than adding a new subsystem
(unlike ReSTIR-PT, path guiding, or the Gaussian photon guiding on the horizon
list). The visual payoff is directly on the owner's showcase scenes: the prism
rainbow (`prism-bk7-collimated`, `prism-sf11-collimated`) and the glass-sphere
caustic (`sms-refractive-glass-sphere`), which are the journal article's caustic
figures. Deterministic root-finding is also the natural fit for the wavefront GPU
kernel: no per-seed rejection divergence.

---

## Fix plan (cite — no inventions, CLAUDE.md §6)

### Phase 0 — license verification (blocking, do first)

The reference implementation is **github.com/mollnn/spoly**. The research doc lists
its license as **"MIT-style" but explicitly UNVERIFIED**
(`2026-07-pbr-advances-research.md` finding 1: *"MIT-style — VERIFY"*). Before any
code is written or any source line is read for porting:

- [ ] Fetch the actual `LICENSE` file from `github.com/mollnn/spoly` and record the
      exact license text + SPDX identifier in the research note.
- [ ] Confirm compatibility with Astroray's MIT license (MIT/BSD-3/Apache-2.0/
      MPL-2.0/public-domain are fine; GPL is **not** — mirror the pkg64 decision that
      kept Cycles' GPL MNEE at arm's length and re-derived from the paper instead).
- [ ] If the license is incompatible or absent, **stop and re-derive from the paper
      alone** (arXiv:2405.13409 carries the full math), exactly as pkg64 did for the
      Hanika spectral extension. Do not copy source under an unverified license.

**Cite:** Fan, Wang, Dong, Wang, Hašan, Yan et al., "Specular Polynomials",
SIGGRAPH 2024, ACM ToG, **DOI 10.1145/3658132**, **arXiv:2405.13409**. Reference
impl **github.com/mollnn/spoly** (license per phase 0).

### Phase 1 — single-bounce polynomial seed finding (CPU first)

- Reformulate the single-vertex specular constraint currently solved by Newton
  (`sms_attempt.h::constraint`, the Hanika half-vector residual
  `h(λ) = ω_i + η(λ)·ω_o` at `sms_attempt.h:124-128`) as the paper's polynomial
  system: rational coordinate mapping of the caster surface parameterisation →
  univariate polynomial whose real roots are the admissible manifold vertices
  (Specular Polynomials §4, single-bounce case). Solve for **all** real roots
  (robust companion-matrix / Sturm-sequence root isolation), then map each root back
  to a surface vertex and validate it (in-surface, correct refraction side, not
  TIR) with the existing checks (`sms_attempt.h:159-181`).
- Wire this behind a new integrator flag (mirror the pkg64 `spectral_newton` toggle
  convention, read via `getInt(...) != 0` per the pkg64 Phase-2 lesson) so the
  current uniform-seed Newton path stays the default fallback until the gates prove
  the replacement. Keep the per-wavelength η dispatch: the polynomial coefficients
  depend on `η(λ_hero)` exactly as the residual does today, so the hero-wavelength
  decoupling (pkg64 Phase-2 lesson) carries over unchanged — one solve per ray at
  `λ_hero`, contribution written to the hero spectral channel.
- Retain Newton as an **optional refinement** of each polynomial root (one or two
  steps of the existing `newton_iterate.h::solveAnalytic`) to polish floating-point
  root error to the existing `tolerance` — the paper notes root-finding gives the
  basin, a Newton polish gives the last digits.

### Phase 2 — two-bounce (build on the pkg106 manifold chain)

- Extend to the two-vertex chain (`include/astroray/manifold/manifold_chain.h`,
  pkg106) using the paper's **hidden-variable resultant**: eliminate one vertex
  parameter to reduce the bivariate constraint system to univariate root-finding
  (Specular Polynomials §5, multi-bounce). This is where the robustness win over
  Newton is largest (multi-solution glass-sphere and double-refraction prism paths).
- Budget accordingly: the paper measures the two-bounce GPU solver at ~10× a single
  Newton step but far more robust. Gate on **quality-at-equal-spp and
  seed-failure-rate**, not raw solver walltime — the point is fewer wasted samples
  and lower caustic variance per spp.

### Phase 3 — GPU/wavefront mirror

- Mirror the single-bounce solver into the device SMS path
  (`include/astroray/manifold/sms_attempt_device.cuh`) and RTX-verify against the
  CPU result via the existing caustic parity harness
  (`tests/test_gpu_caustic_parity.py`, `tests/test_pkg64_gpu_sms_attempt_unit.py`).
  Deterministic root-finding removes the per-seed rejection divergence that hurts
  wavefront occupancy, so this is a natural GPU fit — but keep the port CPU-gated
  first; GPU parity is verification, not the primary gate.

---

## Acceptance criteria

- [ ] **Phase 0 license recorded:** `github.com/mollnn/spoly` license fetched,
      SPDX identifier + compatibility decision written into
      `.astroray_plan/docs/specular-polynomials-research.md`; if incompatible, the
      note records the paper-only re-derivation path taken instead (no source
      copied under an unverified license).
- [ ] **Single-bounce exact:** the polynomial solver enumerates all admissible
      single-bounce manifold vertices on the analytic glass-sphere caster; a unit
      test confirms it finds solutions Newton-from-uniform-seed misses on a
      multi-solution configuration.
- [ ] **Caustic-quality gates equal-or-better at equal spp:** `prism-bk7-collimated`,
      `prism-sf11-collimated`, and `sms-refractive-glass-sphere` reference-bank gates
      (`benchmarks/reference_bank/scenes/*/gates.toml`) hold or improve their metrics
      (prism `hue_spread`/`bright_coverage`; glass-sphere receiver energy / SSIM) at
      the same spp as the current Newton seeding — no regression on
      `sms-reflective-metal-sphere` (single-bounce reflective).
- [ ] **Seed-failure rate measured before/after:** instrument the fraction of SMS
      attempts that reach a valid path (the current `return false` drop rate at
      `sms_attempt.h:149`) on the glass-sphere and SF11 scenes; report the Newton
      baseline and the polynomial rate. The polynomial rate must be **lower**
      (fewer wasted attempts per valid path) — this is the headline quantitative gate.
- [ ] **Two-bounce lands second:** the hidden-variable resultant two-bounce solver
      passes a double-refraction convergence unit test where Newton stalls; gated as
      a distinct phase so single-bounce can ship first.
- [ ] **No regression with the flag off:** default integrator (flag off) is bit-equal
      to the pre-pkg127 SMS path — `tests/test_sms_caustic_validation.py`,
      `tests/test_sms_caustic_spectral.py`, `tests/test_glass_sphere_caustic.py`,
      `tests/test_prism_caustic_rainbow.py` unchanged.
- [ ] **GPU parity:** wavefront single-bounce solver matches the CPU result on
      `tests/test_gpu_caustic_parity.py`; RTX-verified.
- [ ] **Citations in code:** every polynomial-solver call site cites
      "Fan et al. 2024 (Specular Polynomials) §4/§5, DOI 10.1145/3658132" and the
      license-verified provenance of any borrowed structure, per CLAUDE.md §6.

---

## Non-goals

- **Not a replacement for SMS as a whole.** This upgrades the **seed-finding stage**
  only. The refraction, Fresnel, visibility, and MIS-composition chain
  (`sms_attempt.h:159-201`) is untouched; Newton stays as an optional root-polish and
  a flagged fallback.
- **Not the forward light-tracing prism path.** pkg106 ships the triangulated-prism
  rainbow via `light_tracer_caustic`; that integrator is out of scope. This package
  targets the camera-side SMS seed stage (`runSMSAttempt`).
- **Not three-plus bounces.** Single-bounce first, two-bounce second, as the paper
  and the research doc scope it. Higher-order chains are a follow-up if the
  resultant approach proves tractable at that order.
- **Not ReSTIR / partitioned SMS.** The Hong et al. 2025 Partitioned-SMS+ReSTIR line
  (research finding 2) presupposes ReSTIR reservoir infrastructure from pkg55
  Phase C; it is a separate, later package.
- **Not glint rendering.** SMS supports rough normal-mapped glints; out of scope
  here, as in pkg64.
- **No new caustic algorithm.** CLAUDE.md §6: port the published method, cite it,
  verify its license — do not invent a root-finder.

---

## Provenance

Filed from the **2026-07-17 PBR-advances research sweep**
(`.astroray_plan/docs/2026-07-pbr-advances-research.md`, finding 1, verified 3-0),
which ranked Specular Polynomials the top directly-adoptable caustics upgrade for
Astroray's existing SMS pipeline and flagged the mollnn/spoly license as needing
verification at port. Grounded against the live SMS seed stage
(`include/astroray/manifold/sms_attempt.h` + `newton_iterate.h`) delivered by pkg64
(SMS in the default path) and pkg106 (multi-vertex manifold chain). Owner context:
the prism rainbow and glass-sphere caustic are journal-article caustic figures and
spectral-showcase scenes — deterministic, exact seed finding is what makes them
clean at production spp.

---

## Progress

- [ ] Phase 0 — mollnn/spoly license fetched + recorded; compatibility decided.
- [ ] Phase 1 — single-bounce univariate polynomial solver, CPU, behind a flag;
      Newton retained as root-polish/fallback.
- [ ] Phase 2 — two-bounce hidden-variable resultant on the pkg106 manifold chain.
- [ ] Phase 3 — GPU/wavefront mirror; caustic parity RTX-verified.
- [ ] Seed-failure-rate before/after measured on glass-sphere + SF11.
- [ ] Research note `.astroray_plan/docs/specular-polynomials-research.md` written
      (paper + DOI/arXiv, license decision, the exact math reproduced).

---

## Lessons

*(Fill in after the package is done.)*

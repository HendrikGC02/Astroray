# Astroray Next Stage Report

**Date:** 2026-05-16 (Round 9 closed — Round 10 planning)
**Prepared by:** Claude (Anthropic Code, Opus 4.7)
**Scope:** Round 9 closeout + Round 10 recommended set.

> Strategic gate: **RELEASED 2026-05-10** by pkg56 Phase C; Pillar 4
> has been actively shipping since. Strategy in
> [`ROADMAP.md`](ROADMAP.md), status in [`STATUS.md`](STATUS.md).

---

## 1. Current state (one screen)

**Done in Round 9 (6 PRs merged, 2026-05-15):**

- **pkg91 integrator parameter lifecycle** (PR #290) — Fork A.1 + B.1:
  `Integrator::setMaxDepth(int)` virtual + integrator rebuild on
  `set_integrator_param`. Closes Q1 (`Renderer.render(max_depth=N)`
  silently ignored under integrators) + Q2 (`set_integrator_param`
  after `set_integrator` no-op). 4 tests pass; post-construction param
  change verified (3.6% brightness diff).
- **pkg47 FITS data loader** (PR #292) — FITS I/O wrapper + FITSTexture
  plugin + CMake gate `ASTRORAY_ENABLE_FITS` (default OFF). FITSVolume
  registration + test deferred to pkg48 per owner ruling. Pillar 4 →
  ~45%.
- **pkg87 split** (PR #293) — owner decision: original pkg87 Cryptomatte
  spec superseded; split into **pkg87a** (infrastructure), **pkg87b**
  (integrator integration), **pkg87c** (Blender acceptance). All three
  specs on main.
- **pkg92 GPU wavefront RNG foundation** (PR #291) — PCG32 keyed by
  `(pixel, sample, dim)`; equivalence test passes at 64 spp (per-channel
  mean ratios within 5%). PractRand statistical gate CI-enforced;
  stream-disjointness threshold 0.03 @1024 with documented 1/√N
  rationale; TestU01 documented unbuildable on MinGW → PractRand
  substituted per owner decision.
- **pkg89 Phase A — dedicated Light objects** (PR #294) — Light
  interface + 5 types + integrator wiring. G6/G9 pass; G8 spectral
  fidelity 0.41% < 1% threshold; MinGW large-struct heap-corruption fix
  re-applied. Full-scene G8 + G1–G5 explicitly Phase B (Blender addon).
  Unblocks pkg86 Light Tree accessors.
- **pkg55-B' Session 2c — CPU wavefront skeleton** (PR #297) — EXACT
  bit-identity **by shared-kernel construction**: one per-bounce kernel
  called by both `reference_pt_wavefront` and the `cpu_wavefront`
  driver; max abs diff exactly 0.0 across all 5 snapshot stages on
  1 spp Lambertian Cornell, verified MinGW + Linux-GCC CI; production
  codegen byte-unchanged; scaffold `-ffp-contract=off` is a documented
  guard only.

**Doc-pass corrections (Round 9 closeout):**

- **pkg85-D** flipped open → done (PR #283, 2026-05-14 — GPU XYZ→sRGB
  ordering fix; `test_gpu_cpu_ssim_hdri` SSIM 0.9793 ≥ 0.97 gate). Spec
  had lagged at `open`.
- **Flake issue [#298](https://github.com/HendrikGC02/Astroray/issues/298)
  filed** — ReSTIR `test_spatial_reduces_mse` MC-noise strict-inequality
  flake (distinct from #276); recommend seed-pin or tolerance.

**Open doc PRs (context, not round-work):**

- **#295** — Blender addon bug triage + root-cause analysis
  (`.astroray_plan/docs/blender-addon-bug-triage-2026-05-15.md`).
  Addon-bug fixes are **owner-gated** on review + the forthcoming
  architect first-principles plan.
- **#296** — pkg55-B Session 2c technique review (first-principles).
  Feeds the two-tier-gate re-derivation owed before the CUDA port.

**HELD on branch (do not merge):**

- **pkg55 Phase B** (origin/pkg55-phase-b, NOT merged) — superseded by
  the Phase B' CPU-first restart on main; reference only.

**Carried / deferred (stable across rounds):**

| Pkg | Effort | Notes |
|---|---|---|
| pkg76 CSV | ~½ day RTX | Classroom / Junkshop / BMW27 baseline rows |
| pkg45 / pkg46 | weeks each | CLOUDY / HII region (Pillar 4) — after pkg44 |
| pkg48 / 49 | weeks each | HDF5 / SPH loaders (pkg48 also owns deferred FITSVolume registration) |
| pkg50 / 51 | weeks each | Weak lensing / telescope post-process (late Pillar 4) |

---

## 2. Recommended next deployable set (Round 10)

**Round 9 complete (2026-05-16).** 6 PRs merged: pkg91, pkg47,
pkg87-split, pkg92, pkg89 Phase A, pkg55-B' Session 2c.

**Round 10 priorities** (based on unblock graph and payback):

**Top priority (should land first):**

- **pkg55-B' Sessions 3..N — growing-oracle expansion.** With the CPU
  wavefront skeleton bit-identical to `reference_pt_wavefront` by
  shared-kernel construction (Session 2c, PR #297), grow both the
  wavefront and the two reference PTs across the remaining material
  types (metal, dielectric, disney, thin_glass, diffuse_light,
  closure_graph). **Flag:** the spec's program-wide "bit-identity gates
  each port" line **must be re-derived into a two-tier gate** (exact
  CPU↔CPU / bounded+SSIM CPU↔GPU) **before any CUDA-port session
  begins**. The open pkg55-2c technique review (PR #296) feeds this
  re-derivation; do not start a CUDA session until it is resolved.
- **Blender addon bug remediation.** Triage is PR #295 /
  `.astroray_plan/docs/blender-addon-bug-triage-2026-05-15.md`. Fixes
  are **owner-gated** on review of the triage + the forthcoming
  architect first-principles plan. Queued as the second top-priority
  track; do not dispatch fix PRs until the owner clears the plan.

**Second tier (unblocked):**

- **pkg44 ADAF** (Pillar 4) — same VolumetricEmission interface;
  unblocked since Round 8. ~2 weeks.
- **pkg89 Phase B** (Blender addon for dedicated lights) — full-scene
  G8 + G1–G5; the Phase A interface landed PR #294.

**Third tier:**

- **pkg86 Light Tree** — pkg89 Phase A now ships
  `Light::orientationCone()` + `power()` accessors.
- **pkg87a / pkg87b / pkg87c** Cryptomatte — independent; pkg87a is on a
  branch awaiting review per its spec; pkg87b/pkg87c follow.
- **pkg76 CSV** — Classroom / Junkshop / BMW27 parity rows on RTX
  (~½ day).
- **pkg64-gpu Phase 1** — GPU SMS caustics, megakernel target
  (acknowledged pkg55-C will re-port).

**Known flakes (not blocking):**

- **Issue [#298](https://github.com/HendrikGC02/Astroray/issues/298)** —
  ReSTIR `test_spatial_reduces_mse` MC-noise on a strict inequality;
  recommend a seed-pin or a tolerance/seed-averaging margin.
- **Issue #276** — `test_disney_clearcoat_adds_gloss` chronic flake +
  suspected clearcoat correctness defect; owner triage recommended.

**Owner decision needed before /dispatch-next:**

- Round 10 direction: continue the inherited backlog (pkg55-B'
  expansion + Pillar 4) as default vs prioritising the Blender addon
  remediation track once the architect first-principles plan lands.

---

## 3. Drop-in prompts per agent

### 3.1 Claude Code (Track A) — pkg55-B' Session 3 (growing oracle)

```
You are Claude Code on the RTX box. pkg55-B' Session 2c landed the CPU
wavefront skeleton bit-identical to reference_pt_wavefront by
shared-kernel construction (PR #297).

Read first:
  - .astroray_plan/packages/pkg55-wavefront-soa-refactor.md (Phase B'
    Sessions 3..N + the two-tier-gate NOTE)
  - src/cpu/wavefront/path_kernel.{h,cpp} (the single shared per-bounce
    kernel) + cpu_wavefront_state.{h,cpp}
  - tests/wavefront_diff/ (per-stage diff harness)
  - PR #296 (pkg55-2c technique review — informs the two-tier gate)

Goal: extend the shared kernel + both reference PTs to the next
material type per the spec's growing-oracle order (metal first). Keep
EXACT bit-identity CPU↔CPU via the shared kernel. Grow the trip-wire +
equivalence test scenes alongside.

Do NOT start any CUDA-port session: the spec's "bit-identity gates each
port" line must first be re-derived into a two-tier gate (exact
CPU↔CPU / bounded+SSIM CPU↔GPU). That re-derivation is a separate
architect task gated on PR #296 review.

Constraints: CLAUDE.md 1,2,3,6. Production codegen must stay
byte-unchanged.

When done: pkg55 spec Session 3 status + PR ref + diff numbers.
```

### 3.2 Architect — two-tier gate re-derivation (gated on PR #296)

```
You are the project architect. Before any pkg55-B' CUDA-port session,
the program-wide "bit-identity gates each port" line must be re-derived
into a TWO-TIER gate.

Read first:
  - PR #296 (pkg55-2c technique review, first-principles)
  - .astroray_plan/packages/pkg55-wavefront-soa-refactor.md (Sessions
    N+2..M + the round-closeout NOTE)

Deliver: a spec amendment defining (a) EXACT bit-identity for CPU↔CPU
diffs (shared-kernel construction, as Session 2c demonstrated), and
(b) a bounded + SSIM gate for CPU↔GPU diffs with concrete thresholds
and rationale (host↔device toolchain / FP-contraction / transcendental
divergence makes exact host↔device bit-identity unrealistic).

When done: doc-only PR amending the pkg55 spec; STATUS known-issues
note resolved.
```

### 3.3 Architect — Blender addon remediation plan (owner-gated)

```
You are the project architect. PR #295 filed the Blender addon bug
triage. The owner has NOT yet cleared fixes.

Read first:
  - PR #295 / .astroray_plan/docs/blender-addon-bug-triage-2026-05-15.md

Deliver: a first-principles remediation plan (root-cause grouping,
fix sequencing, package boundaries) for owner review. Do NOT open fix
PRs; this is a planning artifact only until the owner clears it.
```

### 3.4 Codex (main directory) — pkg44 ADAF accretion model

```
You are Codex in the main Astroray directory. pkg43 + pkg47 landed.
pkg44 is next: ADAF on the same VolumetricEmission interface.

Read first:
  - .astroray_plan/packages/pkg44-adaf.md (paste-ready spec)
  - pkg42 + pkg43 plugin sources (the pattern pkg44 mirrors)
  - .astroray_plan/docs/accretion-emission-research.md

Goal: implement ADAF per the spec. Cite Narayan & Yi 1994,
Yuan & Narayan 2014, plus whatever the spec adds. Build on the
VolumetricEmission interface; do not widen unless required.

Constraints: CLAUDE.md 1,2,3,6. DO NOT change pkg40–43/47 code.

When done: pkg44 spec status -> done + PR + numbers. PR titled
"feat(pkg44): ADAF accretion model".
```

### 3.5 Codex (RTX hardware, small) — pkg76 CSV rows

```
You are Codex on the RTX 5070 Ti box. Small ~½-day follow-up.

Read first:
  - benchmarks/cycles-parity/README.md + scripts/run_parity.py
  - .astroray_plan/packages/pkg76-blend-importer-parity-scope.md Lessons

Procedure: populate the .blend cache; run scripts/run_parity.py for
Classroom + Junkshop + BMW27 vs Cycles-CPU EXR at the manifest's
reference SPP. Acceptance per spec: SSIM ≥ 0.85.

Output: rows appended to the dated parity CSV.

Constraints: CLAUDE.md 1,4. Doc + CSV only; no source touched.

When done: PR titled
"verify(pkg76): Classroom/Junkshop/BMW27 parity rows on RTX".
```

---

## 4. Coordination

**File-touching map:**

| Session | Files |
|---|---|
| pkg55-B' Session 3 | `src/cpu/wavefront/*`, `tests/wavefront_diff/*`, growing test scenes, pkg55 spec, STATUS.md |
| two-tier gate amendment | pkg55 spec only (doc) |
| addon remediation plan | new doc under `.astroray_plan/docs/` (doc) |
| pkg44 | new `plugins/emitters/adaf.cpp`, new tests, pkg44 spec, STATUS.md |
| pkg89 Phase B | Blender addon files, pkg89 spec, STATUS.md |
| pkg76 CSV | parity CSV, pkg76 spec Lessons, STATUS.md |

**Conflict points:**

1. **`STATUS.md`** — multiple sessions touch it; rebase + manual
   resolution as always.
2. **pkg55 wavefront CPU sources** — single-owner (Track A); no
   cross-track contention while Phase B' is CPU-only.
3. **Per-emitter plugin files** — pkg44 lands in its own file.
   Conflict-free.

**Recommended merge order:** two-tier-gate amendment (doc, unblocks
later CUDA sessions) → pkg44 (Pillar 4) → pkg55-B' Session 3 → pkg89
Phase B → pkg76 CSV.

---

## 5. After Round 10 lands

When Round 10 closes:

- **pkg55-B' growing-oracle** has at least the metal (and likely
  dielectric/disney) shade kernels bit-identical CPU↔CPU; the two-tier
  gate is re-derived so the CUDA-port sessions can begin in Round 11.
- **Blender addon remediation plan** is owner-cleared (or explicitly
  deferred) — fixes can be scheduled.
- **pkg44** done — Pillar 4 has four emission models (synchrotron, slim
  disk, ADAF, thermal/blackbody); real astrophysical scenes are
  composable. Pillar 4 ~50%.
- **pkg89 Phase B** done — dedicated lights usable from the Blender
  addon end-to-end; pkg86 Light Tree fully unblocked.

Bump this report when the two-tier-gate amendment lands or when the
Blender addon remediation plan is owner-cleared — those are the next
major queue movements.

# Astroray Next Stage Report

**Date:** 2026-05-14 (post-Round-7 — pkg82/pkg83/pkg84/pkg67 landed; pkg55-B held on branch for architectural review; pkg85 follow-up filed)
**Prepared by:** Claude (Anthropic Code, Sonnet 4.5 in Max 5x)
**Scope:** Round 8. Round 7 closed on a smaller deployable set than
originally planned: four small packages shipped (pkg82 variance, pkg83
accumulation, pkg84 pre-warm, pkg67 GR spectral unification Option α),
plus pkg64-gpu spec filed. **pkg55 Phase B is HELD on origin/pkg55-phase-b**
with cascading radiance accounting bugs (Bug 1 fixed, Bugs 2+3 regressed
21× brightness post-attempted-fix). Round 8 is shaped by:

(a) **pkg55-B architectural review** — unblocking decision: debug-spiral-
    more, restart from clean baseline, or wait for pkg55-C wavefront/
    megakernel decision. This is the critical path blocker.

(b) **pkg85 test-harness CUDA state leak** — bisect tests 360–369 to find
    the leaking test; fix teardown. ~½ day RTX.

(c) **pkg64-gpu implementation** — GPU SMS caustics port (~2-3 weeks, AoS
    megakernel target). Blocked behind pkg55-B architectural review (if
    the review decides to abandon the wavefront path near-term, pkg64-gpu's
    megakernel target is validated; if the review decides to continue
    debugging pkg55-B, pkg64-gpu waits).

(d) **Pillar 4 continuation** — pkg43 (slim disk) + pkg44 (ADAF), in
    series, on the VolumetricEmission interface pkg42 established.

> Strategic gate: **RELEASED 2026-05-10** by pkg56 Phase C; Pillar 4
> has been actively shipping since. Strategy in
> [`ROADMAP.md`](ROADMAP.md), status in [`STATUS.md`](STATUS.md).

---

## 1. Current state (one screen)

**Done since the previous report (Round 7 closure):**

- **pkg82 variance characterisation** (PR #261, 2026-05-13) — gate
  re-baselined 0.999→0.998 based on measured cross-build delta 0.0006.
  Intra-binary perfect determinism (20 runs, stddev=0). Closes issue
  #237. Establishes project-wide methodology for numerical gate
  tightening.
- **pkg83 progressive accumulation** (PR #259, 2026-05-13) — viewport
  accumulator continues across pure camera transforms (pan/orbit/dolly).
  `spp_trace = [1,2,3,4,5,6,7,8]` measured on CPU + CUDA. Substantive
  changes (focal length, DoF, lens shift, aperture) still reset
  correctly. Cites Cycles `BlenderSession::reset` (Apache-2.0).
- **pkg84 CUDA kernel pre-warm** (PR #260, 2026-05-13) — first CUDA
  frame 83.3 ms (was 12,079 ms cold). **145× improvement** vs pkg81
  baseline. Cites Cycles `reserve_local_memory` pattern (Apache-2.0).
- **pkg67 GR spectral unification** (PR #262, 2026-05-13, Option α) —
  `MinkowskiMetric` + `SampledWavelengths::redshift(g)` +
  `GRSpectralResult::frequencyShift`. All 9 unit tests + flat
  regression + Schwarzschild deflection passing. Ratifies existing
  `BlackHole`-as-`Hittable` + `isGRObject()` dispatch architecture
  (not the literal Metric-step-in-hot-loop design the spec described).
- **pkg64-gpu spec filed** (PR #258, docs-only) — GPU SMS port spec;
  targets AoS megakernel (not wavefront); 4 fork-point decisions baked
  in via architect review; register-pressure baseline from pkg82
  referenced.

**HELD on branch:**

- **pkg55 Phase B** (origin/pkg55-phase-b, NOT merged) — cascading
  wavefront radiance accounting bugs. Bug 1 (`path_alive` initialization)
  fixed in commit 15d98f0. Material-type guards on all 7 shade kernels
  landed in 15d98f0. Bugs 2+3 (sample accumulation order + NEE×throughput)
  attempted fix REGRESSED from 2.5× brightness vs megakernel pre-fix to
  21× brightness post-fix. Needs deeper architectural review, not another
  piecemeal fix. Flagged for architect.

**New follow-up filed:**

- **pkg85 test-harness CUDA state leak** — `pytest tests/ --ignore=tests/test_wavefront_parity.py`
  crashes at test #370 with illegal memory access at `cuda_renderer.cu:81`;
  same test in isolation passes cleanly. Bisect candidate range: tests
  360–369. Spec filed at `.astroray_plan/packages/pkg85-test-harness-cuda-state-leak.md`.

**Open pickup pool (Round 8 + Round 9):**

| Pkg | Title | Effort | Status |
|---|---|---|---|
| **pkg55-B architectural review** | Unblocking decision for wavefront radiance bugs — debug-spiral, clean restart, or wait for pkg55-C? | ~1 session (architect) | **Critical path blocker for pkg64-gpu and any wavefront work.** |
| **pkg85** | Test-harness CUDA state leak bisect + fix | ~½ day on RTX | Ready to implement; bisect tests 360–369, fix teardown |
| **pkg64-gpu** | GPU SMS caustics port (megakernel target) | ~2-3 weeks | Spec ready (PR #258); blocked on pkg55-B architectural review outcome |
| **pkg43** | Slim disk accretion model (Pillar 4) | ~2 weeks | Codex-paste-ready spec; pkg42 VolumetricEmission interface available |
| **pkg44** | ADAF accretion model (Pillar 4) | ~2 weeks | After pkg43 (same Codex serialisation as Round 6's pkg42→pkg43→pkg44 plan) |
| pkg76 CSV | Classroom / Junkshop / BMW27 baseline rows on RTX | ~½ day on RTX | Carried from Round 6/7; pkg73 fixed → denoiser path is healthy → numbers are now meaningful |
| pkg55 Phase C | Megakernel removal | ~3 weeks | After Phase B (if Phase B ships); or independent track if architectural review decides to abandon wavefront near-term |
| pkg45 / pkg46 | CLOUDY emissivity tables / HII region emission (Pillar 4) | weeks each | After pkg43+pkg44; specs already paste-ready |
| pkg47 / 48 / 49 | FITS / HDF5 / SPH loaders (Pillar 4 data import) | weeks each | Optional Round 8+ side track; specs queued |
| pkg79 (tiny) | ReSTIR `test_spatial_reduces_mse` flake (margin 0.000004) | ~½ day | Surfaced by PR #236 CI; recurring noise-floor failure |
| pkg50 / 51 | Weak lensing / synthetic telescope post-process (Pillar 4) | weeks each | Late-Pillar-4; deferred behind pkg43–48 |

---

## 2. Recommended next deployable set (Round 8)

Three sessions, with a critical unblocking decision up front:

| # | Agent | Worktree / location | Package | Effort |
|---|---|---|---|---|
| **0** | **Architect (project owner)** | origin/pkg55-phase-b | **pkg55-B architectural review** — diagnose cascading radiance bugs; decide: (a) continue debugging bugs 2+3, (b) restart Phase B from clean baseline, (c) abandon wavefront near-term and lean on megakernel + pkg64-gpu. | ~1 session |
| 1 | Codex (RTX) | main directory | **pkg85** test-harness CUDA state leak bisect + fix | ~½ day |
| 2 | Codex (conditional on #0 outcome) | main directory | **pkg64-gpu** implementation (if #0 = (c) or early (b) restart validates megakernel target; otherwise wait) | ~2-3 weeks |
| 3 | Codex | main directory | **pkg43 slim disk accretion model** (Pillar 4) | ~2 weeks |
| 4 | Codex (after #3) | main directory | **pkg44 ADAF accretion model** (Pillar 4) | ~2 weeks |
| 5 | Codex (RTX, small) | hardware | **pkg76 CSV** Classroom/Junkshop/BMW27 rows | ~½ day |

Session 0 is the critical path. Its outcome determines whether pkg64-gpu
proceeds now (if megakernel target is validated) or waits (if wavefront
work continues).

Sessions 1, 3, 5 are independent and can run in parallel. Session 4 chains
after 3. Session 2 is conditional on session 0's outcome.

Round 8 closes when:
- pkg55-B architectural review complete (decision documented, next steps
  clear)
- pkg85 merged (full pytest sweep completes without CUDA crashes)
- pkg43 + pkg44 merged (Pillar 4 has 4 emission models: synchrotron +
  slim disk + ADAF + thermal/blackbody)
- pkg76 CSV done (pkg71 baseline 4 rows wide)
- pkg64-gpu: either merged (if unblocked by review) or re-scoped/deferred
  based on review outcome

Then **Round 9** picks up:
- If pkg55-B continues: Phase B completion (per review decision) followed
  by Phase C megakernel removal
- If pkg55-B is abandoned/restarted: pkg64-gpu as the GPU SMS win, plus
  Pillar 4 continuation (pkg45 CLOUDY, pkg46 HII region)
- Optional data loaders (pkg47/48/49) if astrophysical scene scope is the
  next constraint

---

## 3. Drop-in prompts per agent

### 3.0 Architect (project owner) — pkg55-B architectural review

```
You are the project architect. pkg55 Phase B (wavefront per-material
shade kernels) is HELD on origin/pkg55-phase-b with cascading radiance
accounting bugs.

Read first:
  - .astroray_plan/packages/pkg55-wavefront-soa-refactor.md (full spec;
    Phase B section)
  - git log origin/pkg55-phase-b (Bug 1 fix + material-type guards in
    15d98f0; Bugs 2+3 attempted fix regressed 2.5× → 21× brightness)
  - git diff origin/main...origin/pkg55-phase-b (full delta on branch)
  - benchmarks/wavefront/ (if baseline.json exists on branch)

Context:
  - Bug 1 (`path_alive` initialization): FIXED in codex session (15d98f0).
  - Material-type guards on all 7 shade kernels: LANDED (15d98f0).
  - Bug 2 (sample accumulation order) + Bug 3 (NEE×throughput): attempted
    fix REGRESSED from 2.5× brightness vs megakernel pre-fix to 21×
    brightness post-fix.
  - The regressed state is the current HEAD of origin/pkg55-phase-b.

Your task: decide the next step.

Options:
  (a) **Continue debugging bugs 2+3.** Diagnose the regression (why did
      the attempted fix make it worse?), propose a surgical fix, and
      commit to seeing Phase B through to the viewport-parity gate.
      Timeline: weeks (Phase B is ~4-6 weeks total; bugs 2+3 are in the
      middle of that range).
  (b) **Restart Phase B from a clean baseline.** The cascading-bug
      pattern suggests the initial SoA refactor introduced subtle state-
      management issues. Start over from the Phase A.1 SoA scaffold
      (which is bit-identical to the megakernel and gated-tested) with a
      cleaner architectural plan. Timeline: weeks (same as (a), but with
      less debugging spiral).
  (c) **Abandon wavefront near-term and lean on the megakernel.** pkg64-
      gpu targets the AoS megakernel (per PR #258 spec); pkg82 has
      established register-pressure baseline measurement; the megakernel
      is a known-working path. Ship pkg64-gpu on megakernel; defer
      wavefront to a future round when the architectural clarity is
      higher. Timeline for pkg64-gpu: ~2-3 weeks.

Document your decision in a comment on the pkg55-phase-b branch or in a
new issue, then communicate the next step to Codex.

Outputs:
  - Decision: (a), (b), or (c) with rationale
  - If (a): diagnosis of the bugs 2+3 regression + proposed fix
  - If (b): architectural plan for the clean restart
  - If (c): confirmation that pkg64-gpu proceeds on megakernel, and
    wavefront work is deferred to Round 9+ with a clearer plan
```

### 3.1 Codex (RTX hardware) — pkg85 test-harness CUDA state leak

```
You are Codex on the RTX 5070 Ti box. Small ~½-day bisect + fix.

Read first:
  - .astroray_plan/packages/pkg85-test-harness-cuda-state-leak.md
  - tests/conftest.py (pytest fixtures for Renderer teardown)
  - cuda_renderer.cu:81 (the crash site)

Reproducer: `pytest tests/ --ignore=tests/test_wavefront_parity.py -x`
crashes at test #370 (`test_visible_band_cpu_gpu_ssim`) with illegal
memory access. Same test in isolation passes cleanly. The leak is in
tests 360–369.

Procedure:
  1. Binary search tests 360–369 to find the leaking test.
  2. Diagnose: missing `del renderer`? Missing `cudaDeviceReset()` in
     fixture teardown? OptiX denoiser state not torn down?
  3. Fix: add explicit teardown to the leaking test's fixture or test body.

Acceptance:
  - Full `pytest tests/` sweep completes without CUDA crashes.
  - Leaking test identified and documented in pkg85 Lessons.
  - No regression: isolated test still passes after fix.

Constraints:
  - CLAUDE.md sections 1, 2, 3.
  - Fix only the minimal teardown gap; do not refactor unrelated fixtures.

When done:
  - pkg85 spec status -> "done" + PR ref + leaking test name.
  - PR titled "fix(pkg85): test-harness CUDA state leak (test #NNN)".
```

### 3.2 Codex (main directory, conditional on architect review) — pkg64-gpu GPU SMS caustics

```
You are Codex in the main Astroray directory. pkg64-gpu is the GPU port
of pkg64 spectral SMS caustics, targeting the AoS megakernel (not
wavefront).

**IMPORTANT:** This package is BLOCKED on the pkg55-B architectural
review (session 3.0). Only proceed if:
  - The architect's decision is (c) "lean on megakernel", OR
  - The architect's decision is (b) "clean restart" and explicitly
    validates the megakernel target for pkg64-gpu, OR
  - The project owner explicitly approves pkg64-gpu to proceed in
    parallel with pkg55-B debugging.

If blocked, STOP and wait for the architect's decision.

Read first (if unblocked):
  - .astroray_plan/packages/pkg64-gpu-spectral-caustics.md (spec)
  - .astroray_plan/packages/pkg64-spectral-caustics.md (CPU reference)
  - include/astroray/manifold/sms_attempt.h (shared SMS header)
  - src/gpu/path_trace_kernel.cu (megakernel integration site)
  - src/gpu/multiwavelength_kernel.cu (megakernel integration site)

Goal: port the CPU SMS attempt to the GPU megakernel. Mirror the CPU's
per-bounce SMS hook, gated by `use_refractive_caustics` AND per-object
`is_caustic_caster`. Add `bool isCausticCaster` to device hittable,
mirrored from CPU at `uploadScene` time.

Acceptance gates (per spec):
  - Receiver-energy ratio >= 1.10x
  - PSNR floor delta >= -0.5 dB
  - Empty-hook cost <= 5%
  - GPU/CPU SSIM parity >= 0.97
  - Speedup floor >= 5x vs CPU SMS

Constraints:
  - CLAUDE.md sections 1, 2, 3, 6.
  - Cite Zeltner 2020 §4.2 + Hanika 2015 §4 (same as CPU).
  - Do not touch pkg55 wavefront code; that is a follow-up if pkg55-C
    removes the megakernel.
  - Do not re-implement CPU SMS; only port.

When done:
  - pkg64-gpu spec status -> "done" + PR ref + measured numbers.
  - PR titled "feat(pkg64-gpu): GPU SMS caustics (megakernel)".
```

### 3.3 Codex (main directory) — pkg43 slim disk accretion model

```
You are Codex working in the main Astroray directory. pkg42
synchrotron emission shipped 2026-05-11 (PR #245). pkg43 is next:
the slim disk accretion model on the same VolumetricEmission
interface.

Read first:
  - .astroray_plan/packages/pkg43-slim-disk.md (paste-ready spec)
  - .astroray_plan/packages/pkg42-synchrotron-jets.md (the
    interface pkg43 calls into)
  - .astroray_plan/docs/accretion-emission-research.md (research
    note covering pkg42–44)
  - plugins/emitters/synchrotron_jet.cpp (the pattern pkg43
    mirrors structurally)

Goal: implement the slim disk model per the spec. Cite the
canonical references (Abramowicz et al. 1988 / Sadowski 2009 /
the references the spec lists). Build on the
VolumetricEmission interface from pkg42 — don't widen it unless
the spec calls for it.

Constraints:
  - CLAUDE.md sections 1, 2, 3, 6.
  - Pillar 4 — cite the slim-disk papers per the spec. Reference
    renderers (RAPTOR/ipole/GYOTO) are read-only references, not
    mirrored.
  - DO NOT change pkg40 / pkg41 / pkg42 code. pkg43 is purely
    additive on top of the existing interface.

When done:
  - pkg43 spec status -> "done" with PR ref + measured numbers.
  - PR titled "feat(pkg43): slim disk accretion model".
```

### 3.4 Codex (main directory, after #3) — pkg44 ADAF accretion model

```
You are Codex in the main Astroray directory. pkg43 just landed.
pkg44 is next: ADAF (advection-dominated accretion flow) on the
same interface.

Read first:
  - .astroray_plan/packages/pkg44-adaf.md (paste-ready spec)
  - pkg42 + pkg43 plugin sources (the pattern pkg44 mirrors)
  - .astroray_plan/docs/accretion-emission-research.md

Goal: implement ADAF per the spec. Cite Narayan & Yi 1994,
Yuan & Narayan 2014, plus whatever the spec adds. Build on the
VolumetricEmission interface; do not widen unless required.

Constraints:
  - CLAUDE.md sections 1, 2, 3, 6.
  - DO NOT change pkg40 / pkg41 / pkg42 / pkg43 code.

When done:
  - pkg44 spec status -> "done" + PR + numbers.
  - PR titled "feat(pkg44): ADAF accretion model".
```

### 3.5 Codex (RTX hardware, small) — pkg76 CSV Classroom/Junkshop/BMW27 rows

```
You are Codex on the RTX 5070 Ti box. Small ~½-day follow-up from
Round 6/7.

Read first:
  - benchmarks/cycles-parity/README.md + scripts/run_parity.py
  - .astroray_plan/packages/pkg76-blend-importer-parity-scope.md
    Lessons

Procedure: populate the .blend cache; run scripts/run_parity.py
for Classroom + Junkshop + BMW27 vs Cycles-CPU EXR at the
manifest's reference SPP. Acceptance per spec: SSIM ≥ 0.85
(parity-scope, not Cornell's 0.95).

Output: rows appended to benchmarks/cycles-parity/results.csv
(or whichever dated CSV the harness writes).

Constraints:
  - CLAUDE.md sections 1, 4.
  - Doc + CSV changes only; no source touched.
  - Report which channel drove any miss without re-baselining.

When done:
  - PR titled "verify(pkg76): Classroom/Junkshop/BMW27 parity rows on RTX".
```

---

## 4. Coordination

**File-touching map:**

| Session | Files |
|---|---|
| pkg55-B review | origin/pkg55-phase-b branch; no main-tree conflicts during review |
| pkg85 | tests/conftest.py or the leaking test file, pkg85 spec, STATUS.md |
| pkg64-gpu (conditional) | new `src/gpu/manifold/` or inline in megakernel, `include/astroray/gpu_types.h` (add `isCausticCaster`), `src/gpu/scene_upload.cu`, new tests, pkg64-gpu spec, STATUS.md |
| pkg43 | new `plugins/emitters/slim_disk.cpp`, new tests, pkg43 spec, STATUS.md |
| pkg44 | new `plugins/emitters/adaf.cpp`, new tests, pkg44 spec, STATUS.md |
| pkg76 CSV | `benchmarks/cycles-parity/results.csv`, pkg76 spec Lessons, STATUS.md |

**Conflict points:**

1. **`STATUS.md`** — five sessions touch it (pkg85, pkg64-gpu, pkg43,
   pkg44, pkg76). Same merge race as always; rebase + manual resolution.
2. **Per-emitter plugin files** — pkg43 and pkg44 land in different
   files. Conflict-free.
3. **`src/gpu/`** — pkg64-gpu is the only GPU-touching package (if it
   proceeds). Conflict-free.

**Recommended merge order:** pkg85 (small, fixes CI flake) → pkg76 CSV
(small, RTX-only) → pkg43 (medium, Pillar 4) → pkg44 (medium, after
pkg43) → pkg64-gpu last (if unblocked; largest GPU work).

---

## 5. After Round 8 lands

When Round 8 closes:

- **pkg55-B architectural review complete** — next steps clear (either
  continue Phase B debugging, restart Phase B, or lean on megakernel +
  defer wavefront).
- **pkg85** done — full pytest sweep completes without CUDA crashes.
- **pkg43 + pkg44** done — Pillar 4 has four emission models
  (synchrotron, slim disk, ADAF, thermal/blackbody). Real astrophysical
  scenes become composable.
- **pkg76 CSV** done — pkg71 baseline 4 rows wide (Cornell + Classroom +
  Junkshop + BMW27).
- **pkg64-gpu**: either done (if unblocked by review) or re-scoped based
  on review outcome.

Then **Round 9**:

- If pkg55-B continues: **Phase B completion** (per review decision)
  followed by **Phase C megakernel removal** (~3 weeks).
- If pkg55-B is abandoned/restarted: **pkg64-gpu** as the GPU SMS win
  (if not already done in Round 8), plus Pillar 4 continuation (**pkg45
  CLOUDY emissivity tables** + **pkg46 HII region emission**).
- Optional Codex side track: **pkg47 / pkg48 / pkg49** (FITS / HDF5 /
  SPH loaders) — the data-import pillar of Pillar 4 starts.

After Round 9:

- Pillar 4 has the full emission-model trio plus data-import groundwork.
  Real astrophysical scenes (synchrotron jet around a Kerr metric, slim-
  disk accretion onto a Schwarzschild metric, ADAF flow, etc.) are
  renderable end-to-end.
- If pkg55 Phase B+C shipped: wavefront is the production CUDA path,
  megakernel is gone.
- If pkg64-gpu shipped on megakernel: GPU users have rainbow caustics;
  wavefront migration is a future architectural exercise.

Bump this report when the pkg55-B architectural review completes or when
pkg44 lands — those are the next major queue movements.

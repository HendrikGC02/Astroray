# Astroray Next Stage Report

**Date:** 2026-05-14 (Round 8 mid-cycle sync #2 — implementation wave in progress)
**Prepared by:** Claude (Anthropic Code, Sonnet 4.5 in Max 5x)
**Scope:** Round 8 implementation wave. The **Round 8 doc/spec/research wave** landed on main (8 PRs, 2026-05-14 sync #1); the **implementation wave has started** (7 PRs merged since sync #1, 2026-05-14 sync #2):
- **pkg43 slim disk** (PR #271) — Abramowicz 1988 / Sadowski 2009, 14/14 tests pass
- **pkg88 + pkg89 spec promotion** (PR #273) — DRAFT specs promoted to real specs with owner answers
- **pkg38-light-source-spectra** (PR #274) — 7 SPDs filed, unblocks pkg89 Phase A
- **pkg85-C gate cleared** (PR #278) — 901 passed, 0 CUDA crashes; GPU/CPU BVH misalignment + material-lowering bugs fixed
- **Repo cleanup** (PR #275, #277) — moved measurement scripts, autouse GC fixture wrapped
- **Direct pushes** (ec28667, 4ae14d7, eff21fd, 28ea478) — handoff notes, dispatch queue, CLAUDE.md sections, `/pkg-ship` skill

**Round 8 continues.** The dispatch queue
(`.astroray_plan/docs/round8-dispatch-queue.md`) is the authoritative
pickup order; this report summarizes the updated state.

> Strategic gate: **RELEASED 2026-05-10** by pkg56 Phase C; Pillar 4
> has been actively shipping since. Strategy in
> [`ROADMAP.md`](ROADMAP.md), status in [`STATUS.md`](STATUS.md).

---

## 1. Current state (one screen)

**Done since the previous report (Round 8 implementation wave — 7 PRs merged 2026-05-14 sync #2):**

- **pkg43 slim disk accretion model** (PR #271, 2026-05-14) — Abramowicz 1988 / Sadowski 2009 advective slim-disk model implemented. Includes `SampledWavelengths::fromLambdas` factory addition to `spectrum.h`. Units fix: r_s → r_g convention. Spec measurement-corrected: 1.62e8 K → 7.45e6 K at canonical point (9M, mdot=1). 14/14 slim-disk tests pass, no pkg42 regression. **Pillar 4 now 40% complete** (pkg40 + pkg41 + pkg42 + pkg43 done).
- **pkg88 + pkg89 spec promotion** (PR #273, 2026-05-14) — DRAFT specs promoted to real specs after architect spec-promotion pass + owner answers locked in. **pkg88**: box-shutter only, scene-wide steps, Cycles default 0.5 frame center, single consistent stratification policy. **pkg89**: extended 4-mode emission UX with blackbody+color-as-filter, RGB upsample, MeasuredSPD presets, Composite. DRAFT files deleted. Both specs now **open** and ready to dispatch.
- **pkg38-light-source-spectra amendment spec** (PR #274, 2026-05-14) — 7 SPDs: CIE F2/F3 fluorescent (CIE 15:2018), LED 3000/5000/6500K (CIE 224:2017 LED-B3/B4/B5 + LSPDD fallback), sodium vapor + mercury vapor (NIST ASD). All public-domain / CC. Unblocks pkg89 Phase A `EmissionSpectrum::MeasuredSPD` preset buttons. Status **open**, ready to implement, ~½ day.
- **pkg85-C closes pkg85 spec gate** (PR #278, 2026-05-14) — **901 passed, 0 CUDA illegal-access crashes** on the full sweep. Two root causes fixed: (1) GPU/CPU BVH primitive-array index misalignment — `scene_upload.cu` silently dropped non-{Triangle,Sphere} primitives but CPU BVH was built from full scene; localized via compute-sanitizer as 1-byte OOB read at +8 past 8-byte allocation; fixed by introducing `GPRIM_SKIP` placeholder. (2) World-only GPU render rejected with "Scene not uploaded" — gate fixed to `(!d_bvhNodes && !envMap.loaded)`. Material contact sheet now renders cleanly at 480×480 / 1024 spp. **pkg85-D filed** as new follow-up (HDRI world-only SSIM parity bug surfaced once the original blockers cleared).
- **Repo cleanup + robustness** (PR #275 + #277, 2026-05-14) — moved 3 dev measurement scripts to `dev/measurement-scripts/` (`sitecustomize.py` correctly kept at root for Windows DLL discovery bootstrap); wrapped autouse GC fixture cleanup in try/except so cleanup exceptions don't surface as test teardown ERROR.
- **Direct pushes** (ec28667, 4ae14d7, eff21fd, 28ea478, 2026-05-14) — pkg43 handoff notes restoration after stash drop, round8 dispatch queue + owner answers, CLAUDE.md Shell Conventions + Build & Verification + PR & Git Workflow sections, `/pkg-ship` skill + design notes codification.

**Hardware verification headline (RTX 5070 Ti, commit 063bd42 + later):**
- 910/911 pytest passed (1 known ReSTIR spatial MSE flake; pkg85 gate cleared)
- Build 4m20s, 52 MB, all features enabled (CUDA + OptiX + OIDN + tcnn + WAVEFRONT_INTERSECT)
- Caustics rendered at 8192 spp (prism + glass + line emitter, clean — note pkg64 is CPU-only currently)
- Material contact sheet rendered at 854×480 / 1024 spp with --gpu (24 materials distinct, clean)
- AOV passes + convergence grid produced cleanly

**Previous report (Round 8 doc/spec wave — 8 PRs merged 2026-05-14 sync #1):**
- Round 8 strategy pass (PR #263) — architect assessment; pkg55-B fork decision → CPU-first restart
- pkg55 Phase B' amendment (PR #266) — CPU-first restart spec now authoritative; 8 design decisions
- pkg86 Light Tree spec (PR #265) — open, ready after pkg89 Phase A
- pkg87 Cryptomatte spec (PR #264) — open, independent
- pkg88 motion blur research + DRAFT spec (PR #267) — now promoted to real spec (see above)
- pkg89 dedicated lights research + DRAFT spec (PR #269) — now promoted to real spec (see above)
- pkg85 partial fix (PR #268) — conftest + cuda_renderer robustness; spec gate NOT met; full audit landed as pkg85-B (see pkg85-C above for gate closure)
- round8-dispatch-queue.md (direct push 4ae14d7) — owner's session-close answers

**HELD on branch (do not merge):**

- **pkg55 Phase B** (origin/pkg55-phase-b, NOT merged) — cascading
  wavefront radiance bugs (2.5× → 21× brightness regression). **Phase B'
  restart** (CPU-first methodical rebuild) is now the authoritative path
  forward on main per PR #266.

**Open pickup pool (from dispatch queue):**

**Open pickup pool (from dispatch queue — see `.astroray_plan/docs/round8-dispatch-queue.md` for authoritative ordering):**

**Session 1 (next) — parallel-safe, max 3 implementers + N doc agents:**

| Track | Type | Effort | Notes |
|---|---|---|---|
| **pkg38-light-source-spectra** | implementer | ~½ day | Spec on main (PR #274); 7 SPDs; unblocks pkg89 Phase A |
| **pkg55-B Phase B' Session 2+** | implementer (CPU-only) | ~1-2 weeks | Spec now authoritative on main; brief should quote 8 design decisions verbatim; worktree `pkg55-restart` exists |
| **pkg89 Phase A** | implementer | ~2-3 weeks Phase A | Spec promoted (PR #273); Light interface + 5 type stubs + emission UX; blocked on pkg38-light-source-spectra implementation |
| **pkg85-D** | implementer (RTX) | ~½ day | HDRI world-only GPU/CPU SSIM parity (≈0.35 vs 0.97 gate); spec on main |

**Session 2 (assumes Session 1 lands):**

| Track | Type | Effort | Notes |
|---|---|---|---|
| **pkg44 ADAF** | implementer | ~2 weeks | After pkg43 ✓; same VolumetricEmission interface, handle-based API |
| **pkg89 Phase A continued** | implementer | — | After pkg38-light-source-spectra lands; Light types + emission interface + addon wiring |
| **pkg87 Cryptomatte** | implementer | ~2-3 weeks | Spec on main (PR #264); independent; highest compositor-side Cycles-parity gap |
| **pkg88 Phase A** | implementer | ~1-2 weeks | Camera motion blur; spec promoted (PR #273); ready to implement |
| **pkg64-gpu Phase 1** | implementer (CUDA) | ~2-3 weeks | Megakernel target; acknowledged pkg55-C will re-port; owner's call on timing |

**Session 3+ (depends on earlier):**

| Track | Effort | Notes |
|---|---|---|
| **pkg86 Light Tree** | ~3 weeks | After pkg89 Phase A ships `Light::orientationCone()` + `Light::power()` |
| **pkg55-B Phase B' Session 3+** | ~weeks | Continued CPU wavefront + diff harness expansion |
| **Issue #276 / pkg90** | TBD | `test_disney_clearcoat_adds_gloss` chronic flake + suspected clearcoat correctness defect; when prioritized |

**Carried / deferred:**

| Pkg | Effort | Notes |
|---|---|---|
| pkg76 CSV | ~½ day RTX | Classroom / Junkshop / BMW27 baseline rows |
| pkg79 | ~½ day | ReSTIR `test_spatial_reduces_mse` flake |
| pkg45 / pkg46 | weeks each | CLOUDY / HII region (Pillar 4) — after pkg43+pkg44 |
| pkg47 / 48 / 49 | weeks each | FITS / HDF5 / SPH loaders (optional) |
| pkg50 / 51 | weeks each | Weak lensing / telescope post-process (late Pillar 4) |

---

## 2. Recommended next deployable set (Round 8 implementation wave)

**Authoritative source:** `.astroray_plan/docs/round8-dispatch-queue.md`

This report summarizes; the dispatch queue is the pickup order.

**Session 1 (next session):**
- pkg38-light-source-spectra (7 SPDs; unblocks pkg89 Phase A)
- pkg55-B Phase B' Session 2+ (CPU wavefront; 8 design decisions)
- pkg89 Phase A (Light interface + 5 type stubs; after pkg38-light-source-spectra)
- pkg85-D (HDRI world-only SSIM parity; RTX verifier)

**Session 2 (assumes Session 1 lands):**
- pkg44 ADAF (after pkg43 ✓)
- pkg89 Phase A continued (after pkg38-light-source-spectra lands)
- pkg87 Cryptomatte (independent)
- pkg88 Phase A (camera motion blur)
- pkg64-gpu Phase 1 (megakernel target; owner's call on timing)

**Session 3+ (depends on earlier):**
- pkg86 Light Tree (after pkg89 Phase A)
- pkg55-B Phase B' Session 3+
- pkg85-B full audit (when prioritized)

Round 8 closes when:
- **pkg55-B Phase B' CPU reference** landed (bit-identical to CPU
  path_tracer) + Session 1 of CUDA port started or complete
- **pkg43 + pkg44** merged (Pillar 4 has 4 emission models)
- **pkg89 Phase A** merged (Light interface + 5 types; pkg86 unblocked)
- **pkg87 Cryptomatte** merged (highest compositor-side gap closed)
- pkg64-gpu: either merged (megakernel target) or staged for next round
- pkg85-B: spec filed; full audit may carry to Round 9

Then **Round 9** picks up:
- pkg55-B Phase B' Session 2+ (staged CUDA port one kernel at a time)
- pkg86 Light Tree (unblocked by pkg89)
- Pillar 4 continuation (pkg45 CLOUDY, pkg46 HII region)
- Optional data loaders (pkg47/48/49) if astrophysical scene scope is the
  next constraint

---

## 3. Drop-in prompts per agent

**Note:** The prompts below are **outdated** as of 2026-05-14. The
Round 8 doc/spec wave has landed; authoritative pickup order and briefs
are in `.astroray_plan/docs/round8-dispatch-queue.md`. The dispatch
queue references updated specs (pkg55-B Phase B' amendment, pkg86/87
filed, pkg88/89 DRAFT) and owner-answered design questions. **Use the
dispatch queue, not these prompts, for next-session pickup.**

### 3.0 Architect (project owner) — pkg55-B architectural review [SUPERSEDED BY DISPATCH QUEUE]

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

# Astroray Next Stage Report

**Date:** 2026-05-10 (post-Round-5 — pkg76 + pkg55-A + pkg41 + pkg73-diag + verifier set all landed; Pillar 4 actively shipping)
**Prepared by:** Claude (Anthropic Code, Sonnet 4.5 in Max 5x)
**Scope:** Round 6. Round 5 closed cleanly: the strategic gate
released mid-round (pkg56 Phase C), the .blend importer landed
(pkg76), wavefront baselines exist (pkg55 Phase A), the first
Pillar-4 deliverable shipped (pkg41 Kerr validation), and the pkg73
defect was localised (instrumentation in #241; awaiting RTX capture).
Round 6 prioritises (a) closing the pkg73 defect, (b) extending
Pillar 4 with pkg42–44, (c) starting the wavefront SoA migration
proper (pkg55 Phase A.1 → B).

> Strategic gate released **2026-05-10** (PR #233). Pillar 4
> active. Strategy in [`ROADMAP.md`](ROADMAP.md), status in
> [`STATUS.md`](STATUS.md).

---

## 1. Current state (one screen)

**Done since the previous report (Round 5 closure):**

- **pkg76** Astroray `.blend` importer shipped — offline SDNA-walking
  Python reader (no `bpy` runtime), `tools/blend_import/{sdna,
  reader, scene_builder, blend_to_astroray}.py`, returns
  `astroray.Scene`. Roundtrip passes on `synthetic_min.blend`
  (1 cube + 1 sun + 1 camera + Principled BSDF). PR #240. The
  three deferred CSV rows (Classroom / Junkshop / BMW27) need a
  reference run on the RTX box and are queued as a Round 6
  follow-up.
- **pkg55 Phase A** wavefront baseline instrumentation shipped —
  `ASTRORAY_PROFILE=1`-gated CUDA events + NVTX, baseline.json
  populated for `cornell_diffuse` + `cornell_glass`. Headline
  measurement: **158 regs/thread, 1 active block/SM** at the 256-
  thread launch — exactly the Laine 2013 occupancy cliff the SoA
  refactor is meant to relieve. PR #238.
- **pkg41** Kerr metric validation harness shipped — first Pillar-4
  deliverable post-gate. 39 tests for BPT 1972 / Chandrasekhar
  analytic quantities + null circular photon residuals + Kerr a=0
  vs Schwarzschild identity + shadow-contour image-plane regression.
  Bardeen/Chandrasekhar references, no GPL/CeCILL code mirrored.
  PR #236.
- **pkg73 diag** instrumentation shipped — `[pkg73-diag]` stderr
  prints in `Camera::snapshotForMotion`, `renderFrame` entry, and
  `OptiXDenoiser::execute` so the next RTX run produces a decision-
  tree-resolvable signal for the 0% inter-frame variance reduction
  defect. Static analysis in PR #241 ruled out logic bugs in the
  chain — root cause needs hardware evidence. PR #241.
- **pkg64-3 hardware verifier (rebuild)** — the previous verifier
  pass (PR #235) hit a stale `.pyd` predating PR #230's
  `scene_object_count` binding; the rebuild pass (#239) captured
  the actual numbers: **SMS receiver-energy ratio 1.18× ✅**, **PSNR
  floor +0.26 dB ✅**, **per-bounce overhead 2.0 % ✅**. All three
  Phase 3 gates met on RTX 5070 Ti.
- **pkg73 + pkg64-3 verifier (initial pass)** — honest doc-only
  record of the 0% pkg73 result and pkg64-3 stale-build block. The
  audit trail is preserved (PR #235 + #239 stack), not overwritten.
- **pkg78** verifier ran the spec's branch logic correctly — the
  re-baseline precondition did **not** hold (CPU/GPU output bit-
  identical pre/post pkg75), so the gate floor was **not** lowered
  and the drift was filed as defect [#237](https://github.com/HendrikGC02/Astroray/issues/237).
  Investigation now needs a bisect to find the actual breaking
  commit (pkg54c gate currently fails at SSIM 0.998629 vs floor
  0.999).

**Open pickup pool (Round 6 + Round 7):**

| Pkg | Title | Effort | Status |
|---|---|---|---|
| **pkg73 fix** | TEMPORAL_AOV upgrade branch never fires on RTX | ~½ day after diag | Diag instrumentation on `main` (PR #241); needs hardware capture + 1 fix iteration |
| **pkg42** | Synchrotron emission (Pillar 4) | ~2 weeks | Codex-paste-ready spec |
| **pkg43** | Slim disk model (Pillar 4) | ~2 weeks | Codex-paste-ready spec |
| **pkg44** | ADAF model (Pillar 4) | ~2 weeks | Codex-paste-ready spec |
| **pkg55** Phase A.1 | SoA infra + intersect queue | ~1–2 weeks | Renamed in spec by PR #238; first real refactor before Phase B |
| pkg55 Phase B | Per-material shade kernels | 4–6 weeks | After A.1 |
| pkg55 Phase C | Megakernel removal | 2–4 weeks | After B |
| pkg76 CSV | Classroom / Junkshop / BMW27 baseline rows | ~½ day on RTX | After pkg73 fix (so denoiser path is healthy for parity numbers) |
| pkg78 bisect | Find the commit that drifted SSIM 0.999263 → 0.998629 | ~½ day on RTX | Tracking issue [#237](https://github.com/HendrikGC02/Astroray/issues/237) |
| pkg79 (new, tiny) | ReSTIR `test_spatial_reduces_mse` flake (margin 0.000004; widen seed averaging or assertion) | ~½ day | Surfaced by PR #236 CI; recurring noise-floor failure |
| pkg47 / 48 / 49 | FITS / HDF5 / SPH loaders (Pillar 4 data import) | weeks each | Codex-paste-ready specs queued; deferred behind pkg42–44 |
| pkg67 | Metric-aware path tracer | ~1 month | Unblocks once pkg40 + pkg55 maturity in place |

---

## 2. Recommended next deployable set (Round 6)

Six sessions, parallel-safe:

| # | Agent | Worktree / location | Package | Effort |
|---|---|---|---|---|
| 1 | CUDA verifier | hardware | **pkg73 diag capture** — run #241's instrumented build on RTX 5070 Ti, post `[pkg73-diag]` stderr to PR #241 | ~15 min |
| 2 | Claude tech (after #1) | `pkg73-fix` (new) | **pkg73 fix** — apply the obvious fix the diag points to; re-run; clear ≥30% gate | ~½ day |
| 3 | Claude tech | `pkg55-phase-a1` (new) | pkg55 Phase A.1 — SoA infra + intersect queue | ~1–2 weeks |
| 4 | Codex | main directory | **pkg42 synchrotron emission** (Pillar 4) | ~2 weeks |
| 5 | Codex (after #4) | main directory | pkg78 bisect (#237) — find the SSIM-drift commit + report | ~½ day |
| 6 | Codex (after #5) | main directory | pkg76 CSV — populate Classroom / Junkshop / BMW27 rows on RTX | ~½ day |

Sessions 1, 3, 4 spawn at once. Session 2 starts the moment #1
posts. Sessions 5 and 6 chain after #4 because Codex serializes in
the main directory; both are short follow-ups that fit in one
Codex sitting after pkg42 lands.

The ReSTIR flake (pkg79) is small enough to fold into whichever
session is least busy; if it keeps biting CI, file as a tiny
standalone Codex pickup.

Round 6 closes when:
- pkg73 fix merged + gate clears on RTX (the denoiser story is
  finally fully closed)
- pkg42 merged (second Pillar-4 deliverable)
- pkg55 Phase A.1 merged (SoA scaffolding in tree; Phase B
  unblocked)
- pkg78 bisect comment posted on #237 with first-bad commit
- pkg76 CSV rows populated (real Classroom / Junkshop / BMW27
  parity numbers)

Then **Round 7** runs pkg43 + pkg44 in series (Codex), pkg55
Phase B (Claude tech, the migration proper), and the next two
Pillar-4 follow-ups (likely pkg47 FITS loader if any astrophysics
data import is wanted, otherwise more synchrotron / disk geometry).

---

## 3. Drop-in prompts per agent

### 3.1 CUDA verifier (hardware) — pkg73 diag capture

```
You are the CUDA verifier on the RTX 5070 Ti / Windows MSVC box.
PR #241 landed `[pkg73-diag]` stderr instrumentation in
`Camera::snapshotForMotion`, `Renderer::renderFrame` entry, and
`OptiXDenoiser::execute` to localise the 0 % inter-frame variance
reduction defect. The fix session (3.2) is blocked on this signal.

Step 1 — sync main + clean rebuild:
  git checkout main && git pull --ff-only
  cmake --build --preset windows-tcnn-vs-release
  (or build_cuda equivalent)

Step 2 — run the failing tests with -s (so stderr is captured):
  python scripts/dev/run_tests.py --build-dir build_cuda --
    tests/test_optix_denoiser_temporal.py
  -v -s --tb=short 2>&1 | tee test_results/pkg73-diag/run.log

Step 3 — post the captured `[pkg73-diag]` lines as a comment on
PR #241 (the now-merged diag PR). Per-frame, in render order, raw.
Do NOT trim; the fix session needs the full signal — motion buf
pointer, non-zero count, abs-max, hasPrevCamera, prevOrigin — for
each frame to discriminate among:

  (a) motion buffer pointer mismatch (snapshot/execute see different
      ptr)
  (b) buffer populated with zeros (snapshot ran, but motion-write
      site never fired)
  (c) buffer populated, non-zero, but `desiredKind` selection
      branch never taken (test methodology issue)

Step 4 — also re-record the test pass/fail summary (5 tests, prior
result was 3 pass / 2 fail). Append to the same comment.

Constraints:
  - Doc + comment only. No source touched.
  - Do NOT relax the ≥30 % gate.
  - If rebuild errors before producing any [pkg73-diag] lines,
    post the build/run failure verbatim and STOP.
```

### 3.2 Claude tech (worktree `pkg73-fix`, after 3.1) — pkg73 fix

```
You are Claude Code in worktree .claude/worktrees/pkg73-fix,
branched from current main. The CUDA verifier just posted the
[pkg73-diag] hardware capture as a comment on PR #241. Read
it, identify the failing branch (a/b/c per the diag prompt),
fix the root cause, re-verify on RTX.

Read first:
  - The verifier's [pkg73-diag] comment on PR #241
  - plugins/passes/optix_denoiser.cpp (the execute() short-
    circuit; the printf landed there is your starting point)
  - include/raytracer.h::Camera::snapshotForMotion() and
    Renderer::renderFrame() entry (the other two diag sites)
  - tests/test_optix_denoiser_temporal.py
  - PR #241's body (the static-analysis trail that ruled out
    obvious logic bugs)

Decision tree from diag output:
  - hasPrevCamera=0 on frame 2  → snapshot lifecycle bug
    (probably setup_camera bridge); fix in module/blender_module.cpp
  - hasPrevCamera=1, motion_nonzero_count=0 → motion-write site
    never fires; fix in include/raytracer.h render loop
  - hasPrevCamera=1, motion_nonzero_count>0, motion_buf=NULL in
    execute() → Framebuffer::buffer("motion") not registered at
    pass time; fix in include/raytracer.h Framebuffer
  - All non-zero but desiredKind never TEMPORAL_AOV → kind-
    selection logic in execute(); fix locally
  - All non-zero AND desiredKind=TEMPORAL_AOV but rms_t==rms_a →
    test methodology issue (denoiser ran but pkg70 also got the
    benefit somehow); fix in tests/test_optix_denoiser_temporal.py

Step 1 — diagnose (write down which branch fired in PR body).
Step 2 — fix the root cause. ONE fix. Surgical.
Step 3 — REMOVE the [pkg73-diag] prints (they were marked
"remove after fix" with date; do it now).
Step 4 — request a re-run from the verifier or run the gate
test yourself if a CUDA build is available.

Constraints:
  - CLAUDE.md sections 1, 2, 3, 6.
  - Do NOT relax the ≥30 % gate.
  - Do NOT add a "force temporal mode" flag — the gate that only
    upgrades on real motion is correct design.
  - DO NOT consult Cycles MNEE source (wrong concern); pkg73
    reference is intern/cycles/device/optix/device_impl.cpp
    (Apache-2.0).
  - If diagnosis points at the test methodology rather than the
    pass, fix the test — call it out clearly in the PR body.

When done:
  - Append "Defect fix 2026-05-XX" section to pkg73 spec with
    measured numbers (must clear ≥30 %).
  - PR titled "fix(pkg73): TEMPORAL_AOV upgrade branch never
    fired on hardware (root cause: <one-line>)".
```

### 3.3 Claude tech (worktree `pkg55-phase-a1`) — SoA infra + intersect queue

```
You are Claude Code in worktree .claude/worktrees/pkg55-phase-a1,
branched from current main. Phase A landed in PR #238 (gated
profiling, baseline.json populated, 158 regs/thread + 1 block/SM
documented as the cliff). Phase A.1 is the first real refactor
toward wavefront — drop in the SoA path-state buffer + an
intersect queue, BEHIND a build-time flag so the AoS megakernel
remains the default and bit-identical.

Read first:
  - .astroray_plan/packages/pkg55-wavefront-soa-refactor.md
    (the full spec; Phase A.1 was carved out of the original
    Phase A in PR #238)
  - src/gpu/profile.h + the ScopedTimer/NvtxRange + Aggregator
    machinery from PR #238 (re-use it)
  - src/gpu/path_trace_kernel.cu (the AoS megakernel's launchers
    are now wrapped in ScopedTimer; Phase A.1 adds parallel SoA
    launchers)
  - benchmarks/wavefront/baseline.json (the numbers Phase A.1
    must not regress)

Phase A.1 goal:
  1. SoA path-state struct(s) for primary + secondary ray state
     (origin, direction, throughput, pdf, depth, RNG state).
     One CUDA-friendly layout per Laine 2013 §4 + PBRT v4
     wavefront integrator.
  2. An intersect queue: enqueue rays from launch, dequeue in
     a separate kernel that does only intersection. Behind
     `-DASTRORAY_WAVEFRONT_INTERSECT=ON` (default OFF).
  3. Smoke test that the SoA intersect path produces bit-
     identical first-hit positions to the AoS megakernel on
     the Cornell baseline. Behaviour parity is the gate; perf
     numbers come in Phase B.
  4. Re-run benchmarks/wavefront_baseline.py with the flag both
     ways; record both columns in baseline.json.

References (Apache-2.0, mirrorable with citation):
  - mmp/pbrt-v4 src/pbrt/wavefront/* — the canonical wavefront
    integrator architecture in C++/CUDA. Cite per-kernel.
  - intern/cycles/kernel/integrator/state.h — Cycles' SoA
    IntegratorState; cite for the field layout.
  - Laine, Karras, Aila — "Megakernels Considered Harmful:
    Wavefront Path Tracing on GPUs" (HPG 2013) §4. Already
    cited in pkg55 spec.

Constraints:
  - CLAUDE.md sections 2, 3, 6.
  - Default build path UNCHANGED — production renders see no
    SoA code unless the flag is on.
  - Do NOT touch the integrator interface or any plugin.
  - Bit-identical AoS output gated by CI.

When done:
  - pkg55 Phase A.1 subsection in the spec filled with measured
    numbers + bit-identity proof.
  - PR titled "feat(pkg55-A.1): SoA path state + intersect queue
    (gated)".
```

### 3.4 Codex (main directory) — pkg42 synchrotron emission

```
You are Codex working in the main Astroray directory. The
strategic gate released; pkg41 (Kerr validation) shipped first
out of the Pillar-4 queue. pkg42 is next: synchrotron emission
on top of the Kerr metric.

Read first:
  - .astroray_plan/packages/pkg42-synchrotron-emission.md (paste-
    ready spec)
  - .astroray_plan/packages/pkg40-kerr-metric.md + pkg41 spec for
    the metric-tensor + analytic-quantity surface pkg42 calls
    into.
  - The relevant src/ Kerr code paths.

Goal: implement synchrotron emission as a plugin emitter (or
volume contribution per the spec) that consumes the Kerr metric
quantities. Validate against the spec's reference (likely
Pandya 2016 fitting formulae or the GR-MHD synchrotron papers
the spec cites).

Constraints:
  - CLAUDE.md sections 1, 2, 3, 6.
  - This is Pillar 4 — cite the synchrotron / GRMHD papers per
    the spec; check license fence on any reference renderer
    consulted (RAPTOR/ipole/GYOTO are reference only, not
    mirrored).
  - DO NOT change pkg40/pkg41 code.

When done:
  - pkg42 spec status -> "implemented".
  - PR titled "feat(pkg42): synchrotron emission".
```

### 3.5 Codex (main directory, after #4) — pkg78 bisect for #237

```
You are Codex investigating issue #237: the pkg54c visible-band
SSIM drifted from 0.999263 (originally measured in pkg54c) to
0.998629 (current HEAD). The pkg78 verifier (pre-Round-6) proved
bit-identical CPU+GPU output between pre-pkg75 (fcbbbf2) and
HEAD, so the drift PRE-DATES pkg75.

Read first:
  - https://github.com/HendrikGC02/Astroray/issues/237 (the
    defect filing)
  - .astroray_plan/packages/pkg54c-spectral-rgb-jakob-hanika.md
    — find the commit hash that originally reported 0.999263
    (this is the GOOD anchor)
  - tests/test_gpu_multiwavelength.py::test_visible_band_cpu_gpu_ssim

Procedure:
  1. From the pkg54c spec, find the GOOD commit (where
     0.999263 was first measured).
  2. Use `fcbbbf2` (pre-pkg75) as the BAD end — already
     proven to drift below 0.999.
  3. git bisect start fcbbbf2 <good>
  4. At each probe: rebuild CUDA module, run the visible-band
     test in isolation, mark good (≥0.999) or bad (<0.999).
  5. Report the first-bad commit + its diff.

  If the first-bad commit is a deliberate integrator change with
  a justified reason: comment on #237 with the diagnosis +
  open a follow-up issue to discuss whether to re-baseline the
  gate or revert. Do NOT touch the gate in this PR.

  If unintended regression: comment on #237 with the finding
  and STOP — fix is a separate PR.

Constraints:
  - CLAUDE.md sections 1, 4.
  - Do NOT change the gate value.
  - If the bisect range is large (>30 commits), narrow with a
    midpoint probe at a pkg54-related commit first.

When done:
  - Comment on #237 with first-bad commit hash + one-line
    diagnosis.
  - No PR (or doc-only PR if the bisect log is long enough to
    warrant a Lessons append).
```

### 3.6 Codex (main directory, after #5) — pkg76 CSV row population

```
You are Codex on the RTX 5070 Ti box. pkg76 (PR #240) shipped
the .blend importer code path but explicitly deferred the three
new parity-baseline CSV rows because they need a reference run
on real hardware. With pkg73 fixed and the denoiser path healthy
again, run them now.

Read first:
  - benchmarks/cycles-parity/README.md
  - benchmarks/cycles-parity/scenes/manifest.toml (Monster is
    correctly dropped; Classroom / Junkshop / BMW27 are the
    targets)
  - scripts/run_parity.py (the harness; pkg76 wired the
    importer in)
  - .astroray_plan/packages/pkg76-blend-importer-parity-scope.md
    "Lessons" section

Step 1 — populate the .blend cache if not already there
(`benchmarks/cycles-parity/scenes/cache/`).

Step 2 — run scripts/run_parity.py for each of Classroom,
Junkshop, BMW27 against Cycles-CPU EXR reference at the
manifest's reference SPP. Acceptance per spec: SSIM ≥ 0.85
(parity-scope, not Cornell's 0.95).

Step 3 — append rows to benchmarks/cycles-parity/results.csv
(or whichever dated CSV the harness writes). Commit them.

Step 4 — if any of the three scenes fails the 0.85 gate,
report which channel(s) (geometry / material / light /
camera) drove the miss. Do NOT re-baseline the gate.

Constraints:
  - CLAUDE.md sections 1, 4.
  - Doc + CSV + no source touched.
  - PR titled "verify(pkg76): Classroom/Junkshop/BMW27 parity
    rows on RTX".
```

---

## 4. Coordination

**File-touching map** (zero hard collisions):

| Session | Files |
|---|---|
| pkg73 diag capture | comment on PR #241; doc-only Lessons append to pkg73 spec |
| pkg73 fix | `plugins/passes/optix_denoiser.cpp` (+ remove diag prints), `include/raytracer.h` (remove diag prints), maybe `module/blender_module.cpp`, pkg73 spec, STATUS.md |
| pkg55 Phase A.1 | new `src/gpu/wavefront/*.cu` + headers, `src/gpu/path_trace_kernel.cu` (alt launcher behind flag), CMake guard, new test, `benchmarks/wavefront/baseline.json` (extra column), pkg55 spec, STATUS.md |
| pkg42 synchrotron | new `plugins/emitters/synchrotron.cpp` (or volumes), maybe Kerr-side accessors, new tests, pkg42 spec, STATUS.md |
| pkg78 bisect | comment on #237; possibly doc-only PR with bisect log |
| pkg76 CSV | `benchmarks/cycles-parity/results.csv` only |

**Conflict points:**

1. **`STATUS.md`** — three sessions touch it (pkg73 fix, pkg55-A.1,
   pkg42). Same merge race as before; rebase + manual STATUS.md
   resolution preserving all rows.
2. **`include/raytracer.h`** — pkg73 fix removes the diag prints;
   pkg55 Phase A.1 may add SoA-side hooks. Different sections, but
   worth a sanity diff at merge.
3. **`plugins/passes/optix_denoiser.cpp`** — only pkg73 fix touches
   it. Conflict-free.

**Recommended merge order:** pkg73 diag capture (comment, no PR) →
pkg73 fix (small, gate-closing) → pkg78 bisect (small) → pkg76 CSV
(doc/data only) → pkg55 Phase A.1 (medium, CI must show bit-
identical AoS path) → **pkg42 last** (largest, Pillar 4).

---

## 5. After Round 6 lands

When Round 6 closes:

- **pkg73** fully done; the entire denoiser story (pkg33 → pkg68 →
  pkg69 → pkg70 → pkg72 → pkg73) is closed.
- **pkg55 Phase A.1** done; SoA path-state + intersect queue in
  tree behind a flag. Phase B's per-material shade-kernel work has
  a real scaffolding to build on.
- **pkg42** done; second Pillar-4 deliverable shipped. Synchrotron
  emission available on Kerr backgrounds.
- **pkg76 CSV** populated; the 5-scene parity baseline is finally
  4 rows wide (Cornell + Classroom + Junkshop + BMW27; Monster
  correctly dropped).
- **#237** diagnosed; either a re-baseline conversation opens with
  hard data, or a real regression has a fix path.

Then **Round 7**:

- **Codex** continues Pillar 4 — pkg43 (slim disk) + pkg44 (ADAF)
  in series.
- **Claude tech** picks up **pkg55 Phase B** — the per-material
  shade kernel split (the place the 158 regs/thread cliff
  actually breaks).
- Optional Codex side track: pkg47/48/49 (FITS / HDF5 / SPH
  loaders) once the dust settles on the emission-model trio.

After Round 7:

- Pillar 4 has three emission models (synchrotron, slim disk,
  ADAF) + Kerr metric + validation. Real astrophysical scenes
  become renderable end-to-end.
- pkg55 Phase B reduces register pressure measurably; baseline.json
  shows two columns (AoS megakernel vs SoA per-material), and the
  cliff documented in PR #238 is the comparison anchor.
- Pillar 5 essentially feature-complete; remaining work is the
  ongoing-opportunistic polish bullets in `production.md`.

Bump this report when pkg73 fix lands or when pkg42 lands —
those are the next major queue movements.

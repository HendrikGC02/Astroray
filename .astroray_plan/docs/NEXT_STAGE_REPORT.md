# Astroray Next Stage Report

**Date:** 2026-05-10 (post-Round-4 — pkg73 + pkg56-B + pkg64-3 + pkg76-spec + pkg72/pkg64-2 verifier all landed)
**Prepared by:** Claude (Anthropic Code, Sonnet 4.5 in Max 5x)
**Scope:** Round 5 prompts. Round 4 closed the OptiX temporal denoiser
(pkg73), the Blender uploadScene split (pkg56 Phase B), folded SMS into
the default integrator (pkg64 Phase 3), filed the Astroray .blend
importer spec (pkg76), and re-baselined pkg72 + pkg64-2 on hardware.
Round 5 is **the gate-release round**: when pkg56 Phase C lands,
**Pillar 4 thaws**.

> Strategic gate (one item left): Pillar 4 (astrophysics) remains
> parked. pkg64 Phase 3 ✅ done, pkg56 Phase B ✅ done. **pkg56
> Phase C is the only remaining gate.** Strategy in
> [`ROADMAP.md`](ROADMAP.md), status in [`STATUS.md`](STATUS.md).

---

## 1. Current state (one screen)

**Done since the previous report (Round 4):**

- **pkg73** OptiX TEMPORAL_AOV denoiser shipped — `OPTIX_DENOISER_MODEL_KIND_TEMPORAL_AOV`
  upgrade path with motion + albedo + normal guides, prev-output ping-
  pong, destroy-and-recreate handle on kind transition. Static cameras
  fall back to AOV cleanly (no prev-output memory cost). PR #228.
  Cycles `intern/cycles/device/optix/device_impl.cpp` Apache-2.0
  consulted as design reference. Hardware verifier still pending.
- **pkg56 Phase B** uploadScene split — `uploadGeometry`,
  `uploadMaterials`, `uploadLights`, `uploadEnvironment` per-domain
  bindings + `update_object_transform` BVH-refit fast path. Cycles
  `intern/cycles/blender/sync.cpp` Apache-2.0 cited for the per-domain
  pattern. PR #229. **Phase A baseline 129.92 → 183.30 ms** as the
  measurement target for Phase C.
- **pkg64 Phase 3** SMS folded into default `path_tracer` — shared
  `astroray::manifold::runSMSAttempt` helper at
  `include/astroray/manifold/sms_attempt.h`, per-bounce hook through
  `Renderer::pathTraceSpectral` as a `std::function<...>`, per-object
  `is_caustic_caster` opt-in (Cycles UX mirror), Blender addon
  checkbox, MIS-disjoint additive combination with NEE. PR #230.
  Phase 1 + 2 acceptance tests still pass — refactor is provably
  behaviour-preserving.
- **pkg76 spec** filed — Astroray `.blend` importer (parity scope only),
  unblocks 3 of the 5 pkg71 baseline scenes. Drops the UDIM monster
  from the manifest (Cycles itself errors "no camera" on
  `udim-monster.blend`). PR #227.
- **pkg72 + pkg64-2 hardware verifier** re-baselined on RTX 5070 Ti /
  Windows MSVC `build_cuda`: **6/6 motion-vector tests pass in 0.19 s**;
  pure-translation pan shows **100 % of hit pixels with `motion.x > 0`**
  and exact-zero motion on sky pixels (OptiX flow contract confirmed
  end-to-end). pkg64-2 spectral SMS PSNR delta **+8.83 dB matches
  implementer baseline to 0.00 dB**. PR #226.
- Test bootstrap: `tests/runtime_setup.py` deduped
  `os.add_dll_directory` calls — pytest collection went from
  "0 collected, 11 errors" → **801 collected**. PR #225.

**Open Pillar 5 (the Round 5 + Round 6 pickup pool):**

| Pkg | Title | Effort | Status |
|---|---|---|---|
| **pkg56** Phase C | depsgraph-driven dispatch | ~2–3 weeks | After Phase B (now landed) — **the gate** |
| **pkg76** impl | Astroray .blend importer | ~1–2 weeks | Spec landed (PR #227); ready to implement |
| **pkg74** Phase 3 | Interactive HTML dashboard + weekly CI | ~3 days | Phases 1 + 2 done; **carryover from Round 4** (Codex did not get to it) |
| **pkg55** Phase A | Wavefront SoA instrumentation | ~1 week | Deferred until pkg56 + pkg64 measurable baselines exist — both now exist |
| pkg73 verifier | OptiX TEMPORAL_AOV CUDA hardware re-baseline | ~1 hour | Post-pkg73 follow-up |
| pkg64-3 verifier | Default-integrator SMS PSNR + walltime on RTX | ~1 hour | Post-pkg64-3 follow-up |
| pkg78 (new) | pkg54c SSIM gate re-baseline (post-pkg75 detail-preservation drift, 0.999263 → 0.9986 at spp=8192) | ~½ day | Surfaced post-pkg75 verifier; visual diff confirmation gate |
| pkg55 Phases B + C | Wavefront SoA migration proper | 8–12 weeks | After Phase A measured baselines |
| pkg67 | Metric-aware path tracer | ~1 month | Research-blocked (Pillar-4-coupled; revisit when astrophysics thaws) |

**Pillar 4 (about to thaw):** pkg40 Kerr metric done; pkg41 Kerr
validation Codex-paste-ready; pkg42–51 specs queued. **Do NOT spawn
Pillar 4 sessions in Round 5.** The gate releases mid-Round-5 the
moment **pkg56 Phase C** lands.

---

## 2. Recommended next deployable set (Round 5)

Six sessions, all parallel-safe:

| # | Agent | Worktree / location | Package | Effort |
|---|---|---|---|---|
| 1 | Claude tech | `pkg56-phase-c` (new) | pkg56 Phase C — depsgraph-driven dispatch on top of Phase B uploaders | ~2–3 weeks |
| 2 | Claude tech | `pkg76-impl` (new) | pkg76 — Astroray .blend importer (parity scope) | ~1–2 weeks |
| 3 | Claude tech | `pkg55-phase-a` (new) | pkg55 Phase A — wavefront SoA instrumentation pass (no behaviour change, only measurement plumbing) | ~1 week |
| 4 | Codex | main directory | pkg74 Phase 3 — interactive HTML dashboard + weekly self-hosted CI workflow (Round 4 carryover) | ~3 days |
| 5 | Codex (after #4 lands) | main directory | pkg78 — pkg54c SSIM gate re-baseline + visual diff gate vs pkg75 reference | ~½ day |
| 6 | CUDA verifier | hardware | re-baseline pkg73 OptiX TEMPORAL_AOV inter-frame variance + pkg64-3 default-integrator SMS PSNR + walltime on RTX 5070 Ti | ~1 hour |

Sessions 1, 2, 3, 6 spawn at once. Session 4 starts immediately;
session 5 follows 4 (Codex serializes in the main directory).

**Mid-round milestone:** when session 1 (pkg56 Phase C) lands, the
strategic gate releases. From that point forward, Pillar 4 sessions
are spawnable. Codex can pick up pkg41 (Kerr validation) the moment
pkg56-C is on `main`.

Round 5 closes when:
- pkg56 Phase C merged (depsgraph dispatch + ≤5 ms idle frame gate hit) **— gate releases here**
- pkg76 implementation merged (Classroom / Junkshop / BMW27 pkg71 rows possible)
- pkg55 Phase A merged (wavefront baselines measured; Phases B + C unblocked)
- pkg74 Phase 3 merged (showcase has interactive HTML + weekly CI run)
- pkg78 verified or closed (pkg54c gate re-set against post-pkg75 reality)
- pkg73 + pkg64-3 hardware-verified

Then **Round 6** is the first post-gate round: Codex picks up Pillar 4
(pkg41 Kerr validation, then pkg42 / 43 / 44 specs). Claude tech picks
up pkg55 Phase B (the wavefront SoA migration proper begins).

---

## 3. Drop-in prompts per agent

### 3.1 Claude tech (worktree `pkg56-phase-c`) — depsgraph-driven dispatch

```
You are Claude Code in worktree .claude/worktrees/pkg56-phase-c,
branched from current main. Implement pkg56 Phase C end to end.
Phase B landed in PR #229 — uploadScene is now split into
uploadGeometry / uploadMaterials / uploadLights / uploadEnvironment
+ update_object_transform (BVH refit fast path). Phase A baseline:
183.30 ms / frame on a 99k-tri scene; idle frame target ≤ 5 ms.

Read first:
  - .astroray_plan/packages/pkg56-blender-incremental-sync.md
    (full spec, all three phases)
  - module/blender_module.cpp — Phase B per-domain uploaders +
    transform-refit fast path (the dispatch targets)
  - blender_addon/__init__.py — Phase A instrumentation hooks +
    persistent viewport renderer (pkg52)
  - tests/test_pkg56_phase_b_uploaders.py — the contract Phase B
    established
  - tests/test_pkg52_persistent_viewport.py — viewport lifecycle

Phase C goal: drive the per-domain uploaders from Blender's depsgraph
update events (depsgraph_update_post + view_update + view_draw) so
that idle frames perform zero work and per-domain edits perform only
the matching uploader. Acceptance: idle frame ≤ 5 ms wall on the
99k-tri Phase A scene.

Reference (Apache-2.0, mirrorable with citation):
  - intern/cycles/blender/sync.cpp — BlenderSync::sync_recalc loop
    (the canonical depsgraph-bit→domain dispatch).
  - intern/cycles/blender/session.cpp — BlenderSession::view_update /
    view_draw integration with the persistent session.
  - https://docs.blender.org/api/current/bpy.types.Depsgraph.html
    (read fully — DepsgraphUpdate.id, .is_updated_geometry,
    .is_updated_transform, .is_updated_shading flags are the dispatch
    keys we need).

Implementation outline:

  1. blender_addon/__init__.py — PersistentViewport:
     - Subscribe depsgraph_update_post on viewport start, unsubscribe
       on stop.
     - Per DepsgraphUpdate, dispatch:
         is_updated_transform only      -> update_object_transform()
         is_updated_geometry            -> uploadGeometry(obj)
         is_updated_shading             -> uploadMaterials(obj)
         id is bpy.types.Light          -> uploadLights()
         id is bpy.types.World          -> uploadEnvironment()
       (multiple bits set => union of dispatches, deduped).
     - Coalesce within a single view_update tick (don't double-upload
       a mesh if both geometry + shading bits fire on it).
  2. module/blender_module.cpp — expose any small additional
     bindings the dispatcher needs (e.g. an `apply_pending_uploads()`
     finaliser if we batch). DO NOT add new uploader entry points
     beyond Phase B's set unless the depsgraph flags genuinely
     require one.
  3. tests/test_pkg56_phase_c_dispatch.py — new:
     - Construct a synthetic Blender scene; trigger each kind of
       update; assert the matching binding was called and others
       were not. Use a mock binding wrapper rather than running real
       CUDA.
     - Idle test: subscribe + tick view_update with no scene change;
       assert zero uploader calls.
     - Coalescing test: emit geometry + shading bits in the same
       depsgraph cycle on one mesh; assert geometry uploader runs
       once + materials uploader runs once.
  4. benchmarks/viewport/pkg56_phase_c.py — new bench:
     - Run the Phase A 99k-tri scene through the persistent
       viewport; emit idle ticks; record wall time per frame.
     - Acceptance gate: idle frame ≤ 5 ms p99, transform-only edit
       ≤ 20 ms p99.

Constraints:
  - CLAUDE.md sections 2, 3, 6.
  - Re-use Phase B uploaders verbatim — do not refactor them.
  - DO NOT touch the GPU side (cuda_renderer.cu uploader bodies);
    Phase C is dispatch only.
  - The Blender addon must remain importable without bpy
    (ASTRORAY_IMPORT_NO_BLENDER=1 path); guard depsgraph
    subscriptions accordingly.
  - Keep the viewport addon backward-compatible with users on
    Blender 4.x (not just 5.1) — depsgraph_update_post API has been
    stable since 2.80.

When done:
  - pkg56 spec Phase C subsection updated with measured numbers +
    Lessons.
  - STATUS.md: pkg56 Phase C row updated. Strategic-gate banner
    updated to note the gate has released.
  - ROADMAP.md: pillar-4 thaw notice added.
  - Open PR titled "feat(pkg56-C): depsgraph-driven dispatch + ≤5ms
    idle frame gate met".
```

### 3.2 Claude tech (worktree `pkg76-impl`) — Astroray .blend importer

```
You are Claude Code in worktree .claude/worktrees/pkg76-impl,
branched from current main. Implement pkg76 end to end. The spec
landed in PR #227.

Read first:
  - .astroray_plan/packages/pkg76-blend-importer-parity-scope.md
    (the full spec, including the parity-scope cap and the explicit
    Cycles features we DO NOT implement)
  - .astroray_plan/docs/blend-importer-research.md (license analysis,
    parser pick: blender_python_io / bpy in --background)
  - blender_addon/__init__.py (the existing convert_objects path —
    same Astroray-side data model the importer must produce)
  - benchmarks/cycles_parity/run.py (the pkg71 driver; the importer
    feeds it)

Goal: produce `scripts/parity/import_blend.py` that takes a
`.blend` path + a parity-scope manifest entry, runs `blender
--background --python` to extract scene data, and writes a JSON
scene description that the existing pkg71 harness consumes to
produce a comparable Astroray render. Acceptance: Classroom,
Junkshop, BMW27 pkg71 rows produce SSIM numbers vs Cycles-CPU EXR.

Constraints (from spec):
  - Parity-scope only: Principled BSDF (subset), point/area/sun
    lights, world env, camera. No volumes, no hair, no SSS, no
    UDIMs (the dropped monster scene's blocker).
  - DO NOT depend on bpy at runtime in the addon path — bpy is only
    invoked from the import script as a subprocess.
  - Cite all Cycles parity-mapping decisions in code comments
    ("matches intern/cycles/blender/shader.cpp:set_principled_*").
  - CLAUDE.md sections 2, 3, 6.

When done:
  - pkg76 spec status -> "implemented".
  - benchmarks/cycles_parity/results.csv extended with at least 3
    new rows.
  - PR titled "feat(pkg76): Astroray .blend importer (parity scope)".
```

### 3.3 Claude tech (worktree `pkg55-phase-a`) — wavefront SoA instrumentation

```
You are Claude Code in worktree .claude/worktrees/pkg55-phase-a,
branched from current main. Implement pkg55 Phase A.

Read first:
  - .astroray_plan/packages/pkg55-wavefront-soa.md (full spec)
  - src/gpu/cuda_renderer.cu (current AoS path — the measurement
    target)
  - benchmarks/showcase/* (existing perf-stats infrastructure
    pkg74 ships — re-use it)

Phase A is INSTRUMENTATION ONLY. No SoA conversion, no kernel
splits, no behaviour change. Goal: produce a per-bounce, per-
warp, per-kernel timing + occupancy + register-pressure dump for
the current AoS megakernel that Phases B + C will compare against.

Implementation outline:
  1. CUDA events around each major kernel section in cuda_renderer.cu
     (intersection, shading, NEE, accumulation). Conditional on
     ASTRORAY_PROFILE=1 env var so production renders pay nothing.
  2. NVTX ranges for nsight-compute consumption.
  3. Python harness benchmarks/wavefront_baseline.py that runs the
     Cornell + Classroom (post-pkg76) scenes at fixed spp and
     records results in benchmarks/wavefront/baseline.json.
  4. Acceptance: baseline.json populated with measured numbers for
     at least 2 scenes; the data is what Phases B + C must beat.

Reference (Apache-2.0):
  - intern/cycles/device/cuda/queue.cpp — Cycles' wavefront queue
    instrumentation pattern. Cite, do not copy code yet.
  - PBRT v4 wavefront integrator profiler hooks.

Constraints:
  - Zero behaviour change. CI must show bit-identical outputs for
    the ASTRORAY_PROFILE=0 default path.
  - CLAUDE.md sections 2, 3, 6.

When done:
  - pkg55 Phase A subsection in the spec filled with measured numbers.
  - PR titled "feat(pkg55-A): wavefront SoA baseline instrumentation".
```

### 3.4 Codex (main directory) — pkg74 Phase 3 (Round 4 carryover)

```
You are Codex working in the main Astroray directory. pkg74
Phase 3 is the carryover from Round 4 (Codex did not reach it).

Read first:
  - .astroray_plan/packages/pkg74-showcase-framework.md (Phase 3
    section — interactive HTML + weekly CI)
  - benchmarks/showcase/render_showcase.py (the Phase 1+2 driver)
  - benchmarks/showcase/results/*.json (the stat coverage Phase 2
    produces)

Goal:
  1. benchmarks/showcase/html_index.py — rewrite the static index
     into a single self-contained HTML file with collapsible
     sections, per-scene RMSE plots inlined as base64 PNGs, sortable
     stat tables. No JS framework dependency — vanilla HTML +
     <details> + minimal CSS. PBRT-style.
  2. .github/workflows/showcase.yml — weekly self-hosted runner
     workflow that runs render_showcase.py + html_index.py and
     publishes the artefact zip. Schedule: Sundays 03:00 UTC.
  3. tests/test_pkg74_phase3_html.py — render to a tmpdir, assert
     the HTML file exists, parses as HTML, contains all expected
     scene names.

Constraints:
  - CLAUDE.md sections 2, 3.
  - The workflow must NOT block on missing self-hosted runner — gate
    the schedule on a repo variable so it noops on forks.

When done:
  - pkg74 status -> "done (all phases)".
  - PR titled "feat(pkg74-3): interactive HTML showcase + weekly CI".
```

### 3.5 Codex (main directory, after #4) — pkg78 SSIM gate re-baseline

```
You are Codex in the main Astroray directory. pkg78 is a small
follow-up surfaced by the post-pkg75 verifier run.

Symptom: pkg54c gate drifted from SSIM 0.999263 to 0.9986 at
spp=8192 against the visible-band reference. The drift coincides
with pkg75 (one-line `r.normal = rec.normal` fix in
plugins/integrators/spectral_path_tracer.cpp::sampleFull) — the
same detail-preservation mechanism documented in PR #223 for the
OIDN noise-ratio metric.

Read first:
  - .astroray_plan/packages/pkg54c-spectral-rgb-jakob-hanika.md
    (the gate definition)
  - PR #219 + #223 (the pkg75 fix and noise-ratio re-baseline)
  - tests/test_spectral_visible_band.py (the gate test)

Goal:
  1. Render the current spp=8192 visible-band reference with HEAD
     and visually compare against the saved reference. Confirm the
     drop is detail preservation (sharper, not noisier).
  2. If confirmed: re-save the reference + drop the gate floor to
     0.998. Document in the spec that the previous reference was
     pre-pkg75.
  3. If NOT confirmed: file pkg78 as a real defect and STOP — do
     not change the gate.

Constraints:
  - CLAUDE.md sections 1, 3, 4. This is a gate-tightening decision,
     so verification before the gate change is mandatory.

When done:
  - PR titled either "verify(pkg78): pkg54c SSIM re-baseline post-pkg75"
    (re-save case) or "fix(pkg78): pkg54c regression investigation"
    (real defect case).
```

### 3.6 CUDA verifier (hardware session) — pkg73 + pkg64-3 RTX re-baseline

```
You are the CUDA verifier on the RTX 5070 Ti / Windows MSVC
build_cuda branch. Run the following on real hardware and append
Lessons-style sections to the relevant package specs.

  1. tests/test_optix_denoiser_temporal.py — full run against the
     OptiX 9.1.0 + CUDA 12.8 build. Record:
       - inter-frame variance reduction pkg73 (TEMPORAL_AOV) vs
         pkg70 (AOV) on the 10-frame camera-pan sequence.
       - first-frame fallback behaviour (no prev-output buffer).
       - kind-transition reset (HDR -> AOV -> TEMPORAL_AOV cycle).
     Acceptance: ≥30% inter-frame variance reduction per pkg73 spec.
     Append section "Hardware verification 2026-05-10" to
     .astroray_plan/packages/pkg73-optix-temporal-denoiser.md.

  2. tests/test_pkg64_phase3_default_integrator.py +
     tests/test_pkg64_phase3_no_regression.py — full run.
     Record:
       - SMS receiver-energy ratio (≥1.10× the no-caustics baseline).
       - per-bounce walltime overhead with empty hook (≤5%).
       - PSNR floor non-regression (≥-0.5 dB).
     Append section "Phase 3 hardware verification 2026-05-10" to
     .astroray_plan/packages/pkg64-spectral-caustics.md.

Constraints:
  - Doc-only PR. No source touched.
  - PR titled "verify(pkg73, pkg64-3): hardware re-baseline".
```

---

## 4. Coordination

**File-touching map** (zero hard collisions across sessions):

| Session | Files |
|---|---|
| pkg56 Phase C | `blender_addon/__init__.py` (depsgraph subscribers), `module/blender_module.cpp` (small finaliser only), new tests, new bench, pkg56 spec, STATUS.md, ROADMAP.md (pillar-4 thaw notice) |
| pkg76 impl | new `scripts/parity/import_blend.py`, `benchmarks/cycles_parity/run.py` (importer hookup), `benchmarks/cycles_parity/results.csv`, pkg76 spec, STATUS.md |
| pkg55 Phase A | `src/gpu/cuda_renderer.cu` (instrumentation only, gated), new `benchmarks/wavefront_baseline.py`, pkg55 spec, STATUS.md |
| pkg74 Phase 3 | `benchmarks/showcase/html_index.py` (rewrite), new `.github/workflows/showcase.yml`, new test, pkg74 spec, STATUS.md |
| pkg78 verifier | reference PNG re-save in `tests/reference/` + pkg54c spec note (or no change if defect path) |
| pkg73 + pkg64-3 verifier | doc-only Lessons appends to pkg73 + pkg64 specs |

**Three real conflict points to watch:**

1. **`STATUS.md`** — six sessions all touch it. Same three-way merge
   race we keep hitting. Mitigation: rebase + manual STATUS.md
   resolution preserving all rows; verifier sweep PR if rows drop.

2. **`blender_addon/__init__.py`** — pkg56 Phase C is the only Round 5
   session that touches the addon (depsgraph subscribers). pkg64-3's
   addon checkbox already landed in PR #230 on a different code path
   (per-object panel). Should be conflict-free, but worth a sanity
   diff at merge time.

3. **`src/gpu/cuda_renderer.cu`** — pkg55 Phase A adds gated CUDA
   events / NVTX ranges. pkg56 Phase C explicitly does NOT touch the
   GPU side. Conflict-free.

**Recommended merge order:** pkg78 (smallest, doc-only or tiny ref
re-save) → pkg73+pkg64-3 verifier (doc-only) → pkg74 Phase 3 (Codex,
3 days) → pkg55 Phase A (no behaviour change, low risk) → pkg76 impl
(medium) → **pkg56 Phase C last** (largest delta, gate-releasing —
the round closes when this lands).

---

## 5. After Round 5 lands

When this round lands:

- **pkg56** done end-to-end (Phases A + B + C). Viewport idle ≤ 5 ms.
- **pkg64** done end-to-end (Phases 1 + 2 + 3). Caustics on by
  default through MIS, opt-in per-object UX matches Cycles.
- **pkg74** done end-to-end (Phases 1 + 2 + 3). Showcase self-
  publishes weekly; HTML dashboard ships.
- **pkg76** implementation done. Classroom / Junkshop / BMW27 pkg71
  rows have measured Astroray-vs-Cycles SSIM numbers.
- **pkg55 Phase A** done. Wavefront baselines measured; Phases B + C
  unblocked with concrete numbers to beat.
- **pkg73 + pkg64-3** hardware-verified.
- **pkg78** resolved (gate re-baselined or real defect filed).
- **Strategic gate released. Pillar 4 thaws.**

Then **Round 6** is the first post-gate round:

- **Codex** picks up **pkg41 Kerr validation** (already paste-ready,
  gated only by the freeze) and starts the pkg42 / 43 / 44
  paste-ready specs in parallel.
- **Claude tech** picks up **pkg55 Phase B** (the wavefront SoA
  migration proper begins — multi-month, but unlocks measurable GPU
  parity claims with Cycles X for the eventual paper).
- **pkg67 metric-aware path tracer** unblocks once pkg40 + pkg55
  maturity is in place.

After Round 6:

- Pillar 4 actively shipping (pkg41 + early pkg42–44).
- pkg55 Phase B in progress (wavefront SoA refactor).
- Pillar 5 essentially feature-complete; remaining work is the
  ongoing-opportunistic polish bullets in `production.md`.

Bump this report when pkg56 Phase C lands — that is the gate-release
event and the next major queue movement.

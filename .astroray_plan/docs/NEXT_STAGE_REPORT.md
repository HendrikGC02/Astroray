# Astroray Next Stage Report

**Date:** 2026-08-02 (§2/§3 refreshed by the architect at the 2026-08-01→02 overnight round close; §1 still describes the 2026-07-26 state — the 2026-08-02 dayrun standup + closeout will rewrite it)
**Prepared by:** Claude (Anthropic Code) — updated after the 2026-07-25 evening
→ 2026-07-26 round (6 PRs, #525–#530, no open PRs at closeout).
**Scope:** post-2026-07-26 next stage. **pkg55 Phase C is fully COMPLETE**
(PR #524 deleted both megakernels; the wavefront is the only GPU path). This
round shipped the first wave of follow-up work that PR #524 created: restored
GPU features the deletion silently dropped (firefly clamps, cryptomatte, a
phantom-overload class) and a real energy-conservation bug fix (plain
`metal`). **The active pool is now GPU/CPU spectral-parity + transport
correctness follow-ups**, not a single named arc — see §2.

> Strategic gate: **RELEASED 2026-05-10** by pkg56 Phase C. Strategy in
> [`ROADMAP.md`](ROADMAP.md), full status in [`STATUS.md`](STATUS.md) (the
> 2026-07-25 → 2026-07-26 round is authoritative for the current state).

---

## 1. Current state (one screen)

- **pkg55 is fully COMPLETE.** Both megakernels are deleted (PR #524,
  2026-07-25); the wavefront is the sole GPU render path. This round's 6 PRs
  are all downstream cleanup of that deletion.
- **Restored capabilities the deletion had silently dropped:** **pkg157**
  wavefront firefly clamps (PR #526 — cross-binary no-op 2.48e-07 relative,
  ~40× inside the 1e-5 convention); **pkg159** GPU cryptomatte (PR #529 —
  cross-path IoU 0.964–0.984 vs 0.85, discriminating). **pkg161** (PR #530)
  built the firefly-bearing gate scene needed to un-skip pkg157's suppression
  clause — `firefly_window` measures 22.85× peak/p99.9 vs a ≥10× target.
- **A real energy-conservation bug was found and fixed, not just a "GPU too
  dark" ticket:** **pkg160** (PR #527) — plain `metal` (`gpu_metal_eval`, a
  different function from Disney metal) omitted a CPU multiscatter term;
  Step-0 table comparison then proved the *CPU* term was the physically wrong
  one (256-sample hemisphere LUT can't resolve a narrow GGX lobe). Owner chose
  to fix the CPU, which turned out to be **creating energy** (white-furnace
  linear up to 1.77×) — a defect a gamma-rendered furnace test structurally
  could never detect (new memory `gamma-furnace-cannot-detect-energy-gain`).
  Fixed by routing plain metal through the same Kulla & Conty compensation
  `disney.cpp` already ships. Ships the plain-metal GPU/CPU parity gate that
  never existed. One owner-approved exception remains (roughness 0.9,
  asymmetric band `[0.95, 1.10]`), owned by new spec **pkg163**.
- **pkg162** (PR #528) closed the phantom-`launchStageInit`-overload class
  found by pkg157's CI failure: 4 instances found, 4 fixed. No dedicated
  package spec exists for pkg162 — tracked in STATUS.md + the standup docs.
- **pkg88-B** (PR #525) — object motion blur addon bake; independent
  (different-model) review caught a bug all 13 of the PR's own tests missed
  (CENTER swept half the arc, END silently disabled object blur). A real
  headless-Blender run then found a **pre-existing pkg88-A defect**: camera
  motion blur has failed outright in real Blender since it shipped
  (`clear()` wipes the camera before `set_camera_motion_blur()` runs) —
  fixed in the same PR; `scripts/verify_pkg88b_blender.py` is now a permanent
  real-host regression guard.
- **Two investigations closed without shipping code, by design:** **pkg155
  Phase 1** confirmed the ~5× GPU absolute slowdown on a corrected metric
  (total GPU ms/render) and convicted the shade stage (221 regs/thread, 1
  block/SM, recovery target ≤128). The **sm_120 build-config lever was ruled
  out with numbers** — native AOT is 1.68–1.80× SLOWER than the current
  sm_89-JIT build, so the register problem is intrinsic to the kernel, not a
  build artifact.
- **Structural constraint carried forward:** `src/gpu/wavefront/stage_advance.cu`
  is shared by pkg156, pkg120 (pkg157 and pkg159 are now done, dropping out
  of the conflict set) — these two cannot run as parallel implementer
  worktrees; serialize through one lane.
- **Still open for owner decision (carried forward, none block dispatch):**
  tightening the GPU/CPU parity bands project-wide (several as loose as
  `[0.4, 2.5]`); the `MAX_GLOSSY_PARITY_MSE` re-pin is already an open branch
  `pkg164-glossy-mse-repin`, **PR #532** — **the team-lead owns
  landing it, do not re-dispatch pkg164 work**; deleting the dead
  `stage_shade_metal.cu` (declaration + definition, no call site); orphaned
  worktree directories OneDrive won't release (disk hygiene only).
- **Blender 5.1 is installed on this machine.** Real-host verification caught
  two real bugs this round alone (pkg88-A/B) that every mocked-`bpy` suite
  missed — treat real-Blender checks as mandatory for any addon-facing PR,
  not optional polish.
- **Next autonomous work: GPU-gated + RTX-verifiable, all dispatchable now.**
  pkg163 → pkg158 → pkg156/pkg120 (serialize) → pkg150 → pkg88-D → pkg119-B/C.
  pkg155 Phase 2 is an opportunistic GPU-lock gap-filler (not compile-only —
  needs the GPU at every bisect point). pkg153 (env-gate disposition) remains
  in flight with the gate-failure-reviewer. Pillar 4 (pkg45/46/48/49/50/51 +
  pkg107) stays ON PAUSE per owner directive 2026-06-08.

---

## 2. Deployable set (prioritized — refreshed 2026-08-02 at overnight close)

The 2026-08-01→02 overnight cleared the entire previous §2 top set (pkg163
#533, pkg158 #535 closed Outcome A, pkg120 #534, pkg156 investigated →
decomposed, pkg150 → STOP that filed pkg167) and the linear-furnace
conversion (pkg166) exposed + fixed a cascade of shipped energy bugs (pkg169
#540 transmission gain, pkg170 #542 opaque-Disney 2× gain, plus the pkg172
epsilon conviction). **The strategic picture changed: the queue below is
correctness-cascade completion first, new breadth second.** Grep `^Status:`
in each spec before dispatch (memory `orchestrator-next-stage-report-stale`);
tonight's in-flight items (#541, pkg166's PR if unmerged) may have moved.

**Resolve first (in flight at close):**

0. **PR #541 (pkg168 Step 2)** — blocked at close on a wavefront perf-gate
   FAIL with A/B/C attribution running. Resolve the attribution verdict and
   land or disposition #541 before anything else: **pkg173 depends on it**,
   and pkg168's done-pending-merge status is conditional on it.

**Main set:**

1. **pkg172 effect (A) — universal `f/(pdf+1e-3)` throughput-epsilon loss**
   (`pkg172-triangle-transport-bias.md`, verdict section). CONVICTED
   (analytic 2π·ε = 0.628%/bounce, confirmed by the 1e-6 probe reading
   exactly 0.500); hits ALL legs. Fix is the guarded-pdf rejection form
   (pbrt-v4, cited), **never** a smaller additive epsilon. **SUPERVISED
   SLOT** — it brightens every diffuse bounce everywhere, so the PR carries
   an impact sweep + coordinated re-pin batch with per-pin justifications
   and architect sign-off. Highest correctness value in the pool; wrong
   package to run unattended.
2. **pkg173 — bounce-1 geometry-sampling parity**
   (`pkg173-bounce1-geometry-sampling-parity.md`, RTX-gated, blocked on
   #541). Two scalar EXPECTATION offsets (GPU escape rate +6%,
   throughput-per-escape +5.5% at 8192 spp — systematic, not RNG-stream
   noise) with discrete suspects (continuation-ray offset/t_min/BVH epsilon;
   pixel-filter/jitter distribution). **Owns pkg156's 0.998 restoration**,
   with an evidence-gated fallback if both parities land and SSIM still
   falls short.
3. **pkg167 — Disney dielectric reflection-lobe multiscatter compensation +
   bundled pkg150 dead-sample fix**
   (`pkg167-disney-dielectric-reflection-multiscatter.md`, M). Unblocks the
   pkg150 revert AND owns retiring pkg169's quarantined furnace cell (CPU
   ior1.5/R=1.0 = 0.903). Kulla-Conty/Turquin family; mirror the in-repo
   pkg60/pkg160/pkg163 pattern. Ordered: compensation green FIRST, then the
   preserved dead-sample diff on top, one PR, two commits.
4. **pkg165 — Disney-metal uniform ~5–8% GPU-dim diagnosis**
   (`pkg165-disney-metal-uniform-dim-residual.md`, S diagnosis). Step 1 is
   the 2×2 material×scene matrix that un-confounds the sign flip vs pkg163's
   plain-metal +1.5–2%. In-band, not urgent — but cheap and it feeds the
   parity-band-tightening owner decision.
5. **pkg129 (NARROWED 2026-08-02) — live-Cycles rough-metal A/B + heritage
   supersession note** (`pkg129-turquin-multiscatter-luts.md`, S). The
   original LUT-port premise is superseded (tables are already Cycles' own);
   the A/B is the strongest external check and feeds the same band-tightening
   decision. Conviction-path port only fires with architect sign-off.

**Opportunistic / backlog:**

6. **pkg171 — CPU-only-integrator-on-GPU explicit guard** (S, backlog tier).
7. **pkg155 Phase 2** — combined pkg153+pkg155 bisect, GPU-lock gap-filler
   only (needs the GPU at every point; active-PR HW gates always outrank).
   NOTE: pkg168's Step-1 exoneration of the JH tables and pkg172's epsilon
   conviction are new anchors for pkg153's suspect-1B arc — re-read
   `pkg153-pkg155-combined-bisect-protocol-2026-07-25.md` against them
   before burning bisect points.
8. **pkg153 — env-gates disposition** — still IN FLIGHT with the
   gate-failure-reviewer; its spec now carries the pkg168/pkg172 cross-links.
   Do not blind-fix; do not re-dispatch while its reviewer holds it.

**Not this round:**

- **Pillar 4** (pkg45/46/48/49/50/51 + pkg107) — PAUSED per owner directive.
- **pkg88-D, pkg119-B/C** — still valid, deliberately deferred behind the
  correctness cascade; re-enter the top set once pkg172(A)/pkg173/pkg167
  clear.
- **pkg121-B, pkg122, pkg126–137** — filed, un-dispatched, unchanged.

**Standing decisions owed to the owner (carried, none block dispatch):**
project-wide GPU/CPU parity-band tightening (pkg160/pkg163/pkg165/pkg129 all
feed it); deleting dead `stage_shade_metal.cu`; the two flaky xfails
(`test_pkg64_gpu_phase3_prism_psnr_floor`,
`test_disable_reflective_caustics_reduces_mirror_caustic_outliers`) still
want `strict=True`-or-retire.

---

## 3. Drop-in prompt for the next session

The authoritative instructions live with the owner. In short: **resolve #541's
perf-gate attribution first** (pkg173 and pkg168's closeout hang on it), then
work §2 top-down, one mergeable PR per package, full local test +
stale-call-site sweep before each push. **pkg172 effect (A) is the priority
item but SUPERVISED** — its coordinated gate re-pin batch (every diffuse
bounce brightens ~0.63%) needs architect sign-off per pin; do not run it
unattended. **pkg173** (after #541) is the surgical pkg156-closer and safe
for an autonomous lane. **pkg167** is the biggest self-contained M-item:
compensation first, dead-sample diff second, one PR two commits, furnace
linear floor+ceiling at every step. **pkg165 Step 1** and **pkg129-narrowed**
are cheap S-diagnostics that feed the owner's parity-band-tightening
decision — good second-lane fillers. Rules that earned their place tonight:
**energy gates render LINEAR with an upper bound** (three shipped energy-GAIN
bugs were invisible to gamma furnaces until pkg166); **state the `.pyd` mtime
next to every probe A/B number** (a revert-without-rebuild manufactured a
false oracle-exemption mid-diagnosis tonight); **mirror the CONDITION, not
just the term, in every CPU→GPU port** (pkg120's naive-mode regression);
**upsample the ASSET, apply scalar transport factors outside the upsample**
(pkg163/pkg168 class rule, twice confirmed); **expectations are
RNG-stream-independent** — a converged mean/count offset is a defect, never
"stream noise" (pkg172/pkg173). Cite per CLAUDE.md §6 (`/cite-algorithm`)
for any weight-formula change.

---

## 4. Coordination

- **One PR per package**, doc-only closeouts auto-merge on green CI (pr-reviewer
  doc-only rule). Source PRs need the independent-review SIGN-OFF/BLOCK gate (pkg98)
  before push — **this round it caught two real bugs the implementer's own
  tests missed** (pkg88-B's wrong-pose bug, pkg160's original CPU-vs-GPU
  framing before Step 0 flipped which side was wrong).
- **`src/gpu/wavefront/stage_advance.cu` is a serialization point.** pkg156
  and pkg120 both edit it this round (pkg157/pkg159 are done and out of the
  conflict set) — run them in one lane, never as parallel implementer
  worktrees.
- **CI is blind to GPU correctness** — a green CI is necessary but not
  sufficient for any glass/caustic/GR/ReSTIR/wavefront/metal change. Do not
  declare a round clean on CI green alone; run the full RTX hardware sweep at
  closeout (memory: `ci_has_no_gpu_runtime_blindspot`).
- **`apply_gamma=True` (the `render_image()` default) cannot detect energy
  GAIN** — it clamps to [0,1], so a furnace test rendered with gamma reads a
  comfortable "pass" even at 4× the incident light. pkg160 was invisible for
  exactly this reason. Render energy gates **linear**, and assert an upper
  bound, not just a floor (memory: `gamma-furnace-cannot-detect-energy-gain`).
- **A textual sweep of C++ signatures is worthless unless it strips comments
  first** — commas inside parameter comments produce false-positive
  mismatches (pkg162's own methodology note, caught before it filed a false
  regression against already-merged code).
- **The GPU wavefront is NOT run-to-run bit-exact** (parallel atomic
  accumulation, ~1.19e-07–2e-7 floor). Gate wavefront correctness at the
  1e-5 Monte-Carlo convention, NOT exact equality — pkg157's own spec
  contract initially demanded byte-identity and had to be amended on
  measured evidence.
- **A green suite is weak evidence unless something in the loop is
  independent of whoever wrote the code** — this round's pattern: a
  different model (pkg88-B), a real host (pkg88-A blocker), two compiled
  binaries (pkg157's cross-binary gate), and a real GPU (pkg160's Step-0
  table dump) each caught a bug that in-process tests could not.
- **Watch the shadow-`.pyd` trap** — verify `astroray.__file__` resolves to
  the canonical `build_cuda/Release/` path before trusting any GPU number,
  and check `.pyd` mtime vs HEAD (memory: `stale_pyd_locations`).
- **Visual check is mandatory for caustic/dispersion/rough-glass/metal
  renders** — both `hue_spread`/`bright_coverage` and per-channel ratio gates
  can look fine on the wrong image; eyeball the PNG (memory:
  `general-photon-loop-needs-solid-glass`).
- **Grep `^Status:` (or `**Status:**`) in the spec before dispatching** — this
  report's §2 prose can go stale vs the spec header, which is authoritative
  for done/open (memory: `orchestrator-next-stage-report-stale`).
- **`build_cuda_worktree.bat` now inherits `CUDA_PATH`** (fixed this round,
  `609d70f`) instead of hardcoding v12.6 — worktree and main-checkout builds
  use the same compiler again. No longer a live risk.
- **Cite papers/reference repos per CLAUDE.md §6** for any new algorithm —
  pkg160's fix is a direct port of `disney.cpp`'s existing Kulla & Conty
  compensation (already cited to Cycles `microfacet_ggx_preserve_energy`,
  BSD-3-Clause), not a new derivation; keep that discipline for pkg163/pkg158.

---

## 5. After the round

- Flip any landed spec `Status:` lines to `done (PR #N, date — headline
  numbers)`. If a package has no dedicated spec file (e.g. pkg162, a small
  follow-up ticket), record it in STATUS.md/ROADMAP.md instead of inventing
  a spec.
- Update STATUS.md (new round section + the next pickup queue), ROADMAP.md
  (round-closeout entry + pillar long-tail), and rewrite this report's §1/§2
  for the next round.
- Run the RTX hardware sweep; re-confirm all merged PRs hold on hardware
  (firefly clamps, cryptomatte, plain-metal parity, object motion blur).
  Record the full test-suite state (passed/failed/skipped/xfailed/xpassed
  counts).
- Do not bulk-promote flaky xfails to live tests — `test_pkg64_gpu_phase3_prism_psnr_floor`
  and `test_disable_reflective_caustics_reduces_mirror_caustic_outliers` moved
  between xfailed/xpassed across three runs this round; either mark
  `strict=True` deliberately or leave as-is, but do not promote on a lucky run.
- Open ONE doc PR for the closeout; it is doc-only and auto-merge eligible.

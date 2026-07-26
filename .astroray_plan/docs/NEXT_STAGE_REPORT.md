# Astroray Next Stage Report

**Date:** 2026-07-26 (round closeout — overnight 2026-07-25 → day 2026-07-26)
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
  `pkg164-glossy-mse-repin` on origin (no PR yet) — **the team-lead owns
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

## 2. Deployable set (prioritized)

Ordered by value × overnight-shippability. CI is **Linux/CPU only** —
GPU-gated items must be RTX-verified at closeout. All items below are
grep-verified `open`/`dispatchable` in their spec's `**Status:**` header as
of this closeout (memory: `orchestrator-next-stage-report-stale`).

1. **pkg163 — spectral-vs-RGB GGX compensation colour-space parity**
   (`.astroray_plan/packages/pkg163-metal-spectral-compensation-colorspace-parity.md`,
   RTX-gated). CPU computes metal energy compensation per-wavelength, GPU
   per-RGB-channel-then-upsample; they agree only for flat spectra. Owns
   **retiring pkg160's roughness-0.9 asymmetric-band exception** — schedule
   before that exception ossifies into permanence. Worst measured error today
   is 7.2% at grazing chromatic r=0.9; not urgent-tier but load-bearing for
   gate hygiene. Dispatchable now (pkg160 merged, its precondition).
2. **pkg158 — GPU Disney-metal remainder reconciliation, Step 0**
   (`pkg158-gpu-metal-remainder-reconciliation.md`, RTX-gated, S effort).
   Two credible measurements of the near-delta Disney-metal GPU/CPU ratio
   disagree (0.60–0.77 vs ~1.0) and must be reconciled on a **post-pkg160
   SHA** (pkg160 changed the shared metal energy-compensation baseline this
   reconciliation reads). Scope-fenced away from pkg160/pkg163 — do not fold.
3. **pkg156 — wavefront visible-naive brightness residual**
   (`pkg156-wavefront-naive-bounce2-brightness-residual.md`, RTX-gated).
   ~1–1.5% deterministic residual onsetting at bounce 2; owns the
   `test_visible_band_cpu_gpu_ssim` re-pin (0.998→0.995) — that gate may only
   return to 0.998 through this package, never by silent re-tightening.
   **Shares `stage_advance.cu` with pkg120 — serialize, do not run parallel.**
4. **pkg120 — two-sided MIS for the spectral integrator**
   (`pkg120-two-sided-mis-spectral.md`, CPU-gated on CI, wavefront leg
   RTX-verify). Restores the BSDF-ray-hits-emitter MIS term; lands in exactly
   two places now (CPU `pathTraceSpectral` + wavefront `stage_advance.cu`)
   since #524 collapsed four candidate sites to two. **Shares
   `stage_advance.cu` with pkg156 — serialize.**
5. **pkg150 — Disney dielectric VNDF reflection: same-hemisphere masking**
   (`pkg150-disney-dielectric-vndf-hemisphere-masking.md`). Precondition MET
   — the pkg151→pkg154→pkg149 chain (#519/#521/#522) is on main, so this
   package's re-baseline has a real sampler to measure against.
6. **pkg88-D — wavefront motion blur hook**
   (`pkg88-motion-blur.md`, Phase D). DISPATCHABLE, scope reworded for a
   wavefront-only world — `path_time`/`d_motionVerts` threading already
   landed under pkg55-C4/C.0, so likely a smaller remaining scope
   (init-time shutter-time sampling + parity re-baselining) than the original
   estimate; read the "Phase D — wavefront-only reword" addendum first.
7. **pkg119-B/C — Blender differential parity harness + stale-socket fixes**
   (`pkg119-blender-parity-program.md`). Phase A (the coverage matrix) is
   done; Phase B builds the differential harness and lands the 20 stale-socket
   addon fixes the matrix already found; Phase C is graceful-degradation
   policy.

**Opportunistic / lower-priority:**

8. **pkg155 Phase 2** — the combined pkg153+pkg155 bisect
   (`.astroray_plan/docs/pkg153-pkg155-combined-bisect-protocol-2026-07-25.md`).
   **No longer compile-only** — the protocol correction this round proved
   `-Xptxas -v` counts are meaningless under `-rdc=true`, so every bisect
   point needs a real GPU build+run. Run as a gap-filler (~1–1.5 GPU-hours
   across 2–3 nights) when no active-PR HW verification needs the lock; HW
   gates for real PRs always outrank it.
9. **pkg153 — wavefront_diff env-gates disposition** — investigation IN
   FLIGHT with the gate-failure-reviewer (dispatched 2026-07-25), this spec
   is its formal owner. Check its status before dispatching new work in the
   same gate family; do not blind-fix or relax gates without conviction.

**Not this round:**

- **pkg164** (`MAX_GLOSSY_PARITY_MSE` 0.04 → 0.006 re-pin) — already an open
  branch `pkg164-glossy-mse-repin` on origin, no PR yet. **The team-lead owns
  landing it — do not re-dispatch.**
- **Pillar 4** (pkg45/46/48/49/50/51 + pkg107) — PAUSED per owner directive
  2026-06-08. Do not pick up.
- **pkg121-B, pkg122 follow-ons, pkg126–137 platform/material candidates** —
  all still filed and un-dispatched from the 2026-07-20 sweep; lower priority
  than the wavefront-parity pool above until it clears.

**Note on test suite:** post-merge full-suite sweep on the RTX 5070 Ti:
**4 failed / 1531 passed / 69 skipped** — the 4 failures are the standing
known exceptions (`test_blender_parity_matrix_generation` OneDrive `rmtree`
flake + the three pkg153-quarantined env-scene ratio gates), **+25 passing**
from pkg157+pkg88-B landing together with no regressions. pkg160's own
full-suite run after: **4 failed / 1563 passed** (same four exceptions,
+32 from pkg160). Two xfails are flaky between runs
(`test_pkg64_gpu_phase3_prism_psnr_floor`,
`test_disable_reflective_caustics_reduces_mirror_caustic_outliers`) — flagged
as wanting `strict=True` or retirement, not actioned this round.

---

## 3. Drop-in prompt for the next session

The authoritative overnight instructions live with the owner (the "overnight
ship-packages" prompt). In short: **work the §2 set top-down, one mergeable
PR per package, full local test + stale-call-site sweep before each push,
poll CI then `gh pr merge --squash --delete-branch`.** **Start with pkg163**
(closes the gate-hygiene exception pkg160 left open) **then pkg158** (small,
S effort, unblocks the Disney-metal reconciliation that's been open since
pkg152). **pkg156 and pkg120 share `stage_advance.cu` — run them serially in
one lane, not as parallel worktrees**, in either order (neither hard-depends
on the other, but pkg120's MIS term is more architecturally load-bearing so
it is the safer one to land first). Then **pkg150** (precondition met) →
**pkg88-D** (re-scoped, check the wavefront-only reword addendum first) →
**pkg119-B/C**. If a slot frees and no active PR needs the GPU lock, spend it
on **pkg155 Phase 2** (one build+profile per bisect point, ~1–1.5 GPU-hours
total). **Verify with a real headless Blender run for any addon-facing
change** — this round found two real bugs (pkg88-A/B) that every mocked-`bpy`
suite missed; `scripts/verify_pkg88b_blender.py` is now the pattern to
extend. Cite papers per CLAUDE.md §6 for any new algorithm
(`/cite-algorithm`).

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

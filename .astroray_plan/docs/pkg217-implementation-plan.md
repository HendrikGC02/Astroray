# pkg217 — GPU wavefront caustic integration: IMPLEMENTATION PLAN

**Tier:** written by Opus (plan); to be executed by a sonnet-5 package-implementer.
**Status:** plan — not yet implemented.
**Grounding:** `.astroray_plan/docs/pkg217-wavefront-caustic-integration-research.md`
(architecture, decided) + `.astroray_plan/docs/caustics-research.md` (algorithm/licensing,
settled at pkg64). Read both before starting. `cite-algorithm` still runs at dispatch.

## Goal (acceptance in one line)
A diffuse receiver behind a glass **sphere** caster, lit by a delta light, renders a
**bright caustic** on the GPU wavefront instead of a **black shadow** — matching the CPU
SMS path and qualitatively matching Cycles Shadow Caustics. Register-neutral for the
existing shade/light kernels.

## The mechanism (why it's black today, what fixes it)
Today: receiver→delta-light connection is ordinary NEE; the shadow ray hits the glass,
throughput→0, floor = black shadow. Fix = at the light-sample stage, for a lane whose
sampled light is a caustic light AND the scene has ≥1 caster, (a) SUPPRESS the ordinary
shadow ray (the `PATH_MNEE_SUCCESS`-style cull) and (b) route the lane to a NEW caustic
stage that runs the existing device SMS solve receiver→caster→light and adds the
manifold contribution. Get the cull wrong → either keep the black (culled, no
contribution) or double-count (not culled + contribution). This is the #1 risk.

## Files

### CREATE `src/gpu/wavefront/stage_caustic_connect.cu` (+ decl in gpu_wavefront_state.h)
- A new `__global__ void stageCausticConnectKernel(...)` with its OWN register file
  (this is the whole point — the SMS Newton live state must NOT spill into
  `stageShadeBucketedKernel`, which is pinned REG:254).
- It consumes a caustic work queue (lanes flagged by the light-sample stage) and for
  each: build `GSMSCaster` (sphere) + `GSMSConfig` from the caster's `GSphere` and the
  receiver hit; call `runSMSAttemptDevice(...)` from
  `include/astroray/manifold/sms_attempt_device.cuh` (DO NOT re-derive — it's
  monomorphized for the sphere caster, exactly the owner's repro). On success, add the
  per-λ manifold contribution to the path throughput/output; on failure, add nothing
  (brute-force PT remains the silent fallback — do NOT re-emit the ordinary shadow ray).
- Contribution is classified **indirect** (not direct) — deliberately unlike Cycles
  T96992.
- Host launcher `void launchStageCausticConnect(...)` following the
  `launchStageLightSample_SessionN4` signature style.

### MODIFY `src/gpu/wavefront/stage_light_sample.cu`
- In `stageLightSampleKernel` (~line 213), BEFORE emitting the shadow ray (~line 280):
  add the predicate. If `c_hasCaustics` (new host-set constant) AND the sampled light is
  a caustic/delta light AND the scene has casters: push this lane's index into the
  caustic work queue and `continue` WITHOUT enqueuing the ordinary shadow ray (the cull).
  Otherwise behave exactly as today.
- Keep this to a single predicate + one queue push. No SMS math here (that lives in the
  new stage). This keeps `stageLightSampleKernel`'s register footprint essentially
  unchanged — verify with the probe.

### MODIFY the render loop (`src/gpu/wavefront/gpu_wavefront_snapshot.cu` and the
production path in `module/blender_module.cpp` / `cuda_renderer.cu`)
- Host-side gate: compute `hasCaustics = (scene has ≥1 GSphere with isCausticCaster)`
  from the upload result (the flag already crosses upload — pkg64-gpu Phase 1). Publish
  it into a `__constant__` (mirror the `c_wfTexBinding` / `setWavefrontTextureBinding`
  pattern — a `setWavefrontCausticBinding` that carries the caustic-light list + config).
- Launch `stageCausticConnect` ONLY when `hasCaustics` — for the 99% of scenes with no
  caster, skip the launch entirely (zero cost). This is the register-safety guarantee:
  no caster scenes never touch the new kernel.

### CREATE tests
- `tests/test_pkg217_gpu_caustic.py`:
  - **Not-black gate:** glass sphere caster + delta light + diffuse floor. Assert the
    caustic-region mean radiance exceeds the pre-change black-shadow baseline by a stated
    factor (e.g. ≥5×), AND the lit-pool region OUTSIDE the caster shadow is unchanged vs
    a no-caster render within MC noise (no energy added elsewhere — the double-count
    guard).
  - **CPU/GPU parity:** the same scene on CPU (existing SMS path) vs GPU, per-channel
    mean-ratio near 1.0 (independent RNG → use mean-ratio, NOT SSIM — memory
    ssim-wrong-gate-for-independent-rng).
  - **Dispersion (if a solid closed prism/sphere with outward normals is used):** visual
    hue-spread + bright-coverage on the caustic, NOT just variance (memory
    general-photon-loop-needs-solid-glass). If only a sphere caster is wired this round,
    a monochrome caustic gate is acceptable; note dispersion-caustic as follow-up.
- Use the REAL pybind API (`astroray.Renderer`, `load_texture`, etc.) and RUN the tests —
  paste real output. (Two implementers this session shipped tests against invented APIs.)

## HARD GATES (acceptance)
1. **Register gate (HARD).** `cuobjdump -res-usage` post-build: `stageShadeBucketedKernel`
   and `stageLightSampleKernel` REG/STACK histograms UNCHANGED vs main (the new SMS state
   is in a SEPARATE kernel). If any shared/inlined code is touched, isolate behind
   `template<bool HasCaustics>` so `<false>` is byte-identical. Paste before/after numbers.
2. **Not-black + no-double-count** (the two-sided test above).
3. **CPU/GPU parity** mean-ratio near 1.0 on the caustic scene.
4. Build clean: fresh `.pyd`, sm_120 (`cuobjdump --list-elf`), ABI canary green. Build via
   `build_cuda_worktree.bat "<sibling-worktree-path>" <FULL-40-char-sha>` from PowerShell
   (NOT cmd/c; full sha — guard string-matches).

## Scope / non-goals
- **Sphere casters only** this round (the device solver is monomorphized for spheres, and
  it's the owner's repro). Mesh/prism casters and the two-bounce robustness upgrade are
  **pkg127** (Specular Polynomials) — do NOT couple; consume the current seed stage.
- Do NOT touch the CPU SMS path (pkg64) — it's the parity oracle.
- World-volume-through-caustic (fog) is a known separate gap — out of scope.

## Citations to lock (cite-algorithm at dispatch)
- Zeltner, Georgiev, Jakob, "Specular Manifold Sampling…", SIGGRAPH 2020 (the method;
  BSD-3 skeleton already in-tree via pkg64).
- Hanika et al., "Manifold Next Event Estimation", EGSR 2015 (per-λ Newton + the
  connection-at-light-sample + NEE-cull ARCHITECTURE, mirrored from Cycles' behaviour;
  GPL kernel NOT copied — architecture borrow only).
- Cycles `1fb0247497` / T94120 (visual parity oracle only).

## Risks (from the research note)
- **NEE cull correctness** (#1) — the two-sided not-black/no-double-count test is the
  distinguishing diagnostic.
- **Salt-and-pepper false positive** on any dispersion gate — require solid closed
  geometry + outward normals + a visual check, not a bare variance metric.

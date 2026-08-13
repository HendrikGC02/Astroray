# pkg198 — GPU wavefront light-path-expression render passes (diffuse/glossy/transmission direct+indirect, emission, environment)

**Pillar:** 5 / integration-first (also 3 — CPU↔GPU parity)
**Track:** A
**Status:** open (filed 2026-08-13 — GPU-parity vetted set; **probe-first, may park**)
**Estimated effort:** L (register-hostile — the up-front probe decides whether it ships at all)
**Depends on:** pkg197 (first-hit guide AOVs — land it first; its register probe tells us how
much headroom the shade kernel has before this heavier accumulation is even attempted);
[[wavefront-shade-kernels-register-saturated]]; [[closure-graph-lobe-count-spills-fused-kernel]].

---

## Why this exists (verified line refs, current `main`)

Astroray has a full Cycles-style render-pass registry — `PASS_DIFFUSE_DIRECT`,
`PASS_DIFFUSE_INDIRECT`, `PASS_GLOSSY_*`, `PASS_TRANSMISSION_*`, `PASS_VOLUME_*`,
`PASS_EMISSION`, `PASS_ENVIRONMENT`, `PASS_AO`, `PASS_SHADOW` — exposed to Python
(`module/blender_module.cpp:2202-2218`) and filled per-sample by the **CPU** render loop
(`include/raytracer.h:3121-3213`, `passColor[...]` accumulation → `cam.renderPassBuffers`).

The **GPU wavefront path fills none of them.** `cuda_wavefront_render`
(`module/blender_module.cpp:1836-1846`) returns only the beauty RGB; no `.cu` file writes
`renderPassBuffers` (grep-verified). So every compositor workflow that relies on light-path
AOVs — per-pass denoise, relight, per-lobe colour grade, emission/environment isolation —
silently returns black on the (default) GPU backend, while working on CPU. This is the
second half of the "GPU AOV/render-pass" parity gap (pkg197 owns the cheap first-hit-guide
half).

## The hard part — this is register-hostile, and may not be worth it

Unlike pkg197's one-shot first-hit guides, light-path passes require **per-path, per-lobe
accumulators carried through every bounce**: each contribution must be tagged
diffuse/glossy/transmission × direct/indirect and splatted to the right pass, with the
direct/indirect split tracked across the path and the first-bounce lobe category remembered.
That is on the order of 8-10 extra `Vec3` (or spectral) accumulators of **live per-path
state** in the exact kernel that is already pinned at **REG 254 / STACK 3608 / CONSTANT[0]
1700** (`stageShadeBucketedKernel<…>`, `src/gpu/wavefront/stage_advance.cu:1105`). Adding
per-hit live state is precisely the class of change that spilled the fused shade kernel +52%
before ([[closure-graph-lobe-count-spills-fused-kernel]], [[wavefront-shade-kernels-register-saturated]]).

**This package is therefore probe-first and explicitly may-park** (the pkg194 discipline).

## MANDATORY FIRST STEP — decide feasibility before building

1. **Design the pass-accumulation layout** citing Cycles' film pass model
   (`intern/cycles/kernel/film/`, `integrator/shade_surface.h`, Apache-2.0 — how it tags
   `PASS_DIFFUSE_DIRECT` etc. and carries the light-path flags). Do NOT invent an
   accumulation scheme (CLAUDE.md §6 / [[cite-algorithm]]).
2. **Register probe the minimal version** — carry the pass accumulators as SoA global-memory
   scatter (per-pixel pass buffers written incrementally per bounce) rather than live
   registers, so the shade kernel holds pointers, not 10 accumulators. Build native-sm_120,
   read `stageShadeBucketedKernel<false,false,false,false>` STACK/REG/CONSTANT via `cuobjdump`.
   HARD gate: the pass-less fleet specialization stays **3608 / 254 / 1700** (isolate behind a
   compile-time `HasAOVPasses` axis — the pkg184/pkg189 if-constexpr pattern — so scenes that
   don't request passes pay nothing).
3. **If even the global-scatter form spills the pass-less specialization or regresses
   non-AOV perf, STOP and report.** The value (a compositor power-user feature) does not
   justify a fleet-wide regression on every render. Acceptable outcomes: (a) ships isolated
   behind the compile-time axis with zero pass-less regression; (b) parks with the cuobjdump
   evidence and a recommendation.

## Scope (only if the probe clears)

- Fill `PASS_DIFFUSE_DIRECT/INDIRECT`, `PASS_GLOSSY_DIRECT/INDIRECT`,
  `PASS_TRANSMISSION_DIRECT/INDIRECT`, `PASS_EMISSION`, `PASS_ENVIRONMENT` on the wavefront,
  matching CPU semantics (`include/raytracer.h:3121-3161`) so CPU↔GPU passes agree.
- `PASS_AO` / `PASS_SHADOW` are secondary; include only if free within the same accumulation
  pass. `PASS_VOLUME_*` is out of scope until GPU volumes exist (**pkg199**).
- Copy-back the pass buffers alongside the beauty/guide plumbing established by pkg197 — one
  path, do not fork.

## Acceptance criteria

- [ ] Probe reported FIRST: `stageShadeBucketedKernel<false,false,false,false>` stays
      **3608 / 254 / 1700** with passes isolated behind a compile-time axis (cuobjdump
      evidence), OR a documented park.
- [ ] Enabled passes match the CPU render within a tight per-channel band on a scene with
      distinct diffuse/glossy/transmission/emission/environment content (CPU↔GPU pass parity
      test); the beauty must still equal the sum of the lit passes (energy closure check).
- [ ] Non-AOV GPU renders show **no perf regression** (min-of-N, burn-in —
      [[gpu-perf-ab-clock-drift]]) vs the pkg197 baseline.
- [ ] Headless Blender 5.1: the light-path passes populate on the GPU backend and round-trip
      through the compositor / EXR.
- [ ] **RTX 5070 Ti hardware gate** ([[ci_has_no_gpu_runtime_blindspot]]), bound to HEAD.

## Hard non-goals

- **No lobe-array shrink or shared live-state widening** to buy register room (pkg178/pkg184).
- **No volume passes** until pkg199 lands GPU volumes.
- **No cryptomatte rework** (already GPU-wired, pkg159) and **no first-hit guide AOVs**
  (pkg197) — this package is the light-path split only.
- **Do not force it to ship.** A clean park with evidence is a valid, expected outcome.

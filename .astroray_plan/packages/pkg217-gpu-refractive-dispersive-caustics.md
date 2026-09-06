# pkg217 — GPU refractive / dispersive caustics (glass casts a bright caustic, not a black shadow)

**Pillar:** 3 (light transport / spectral rendering)
**Track:** A
**Status:** done, Path A (PR #TBD, 2026-08-23) — root-cause was addon wiring, not a missing GPU caustic mechanism. See "CORRECTION" below.
**Depends on:** TBD
**Priority:** NOT top — owner (2026-08-21) explicitly deprioritised: "not necessarily #1 if there are more pressing things or older packages waiting their turn." Sequence behind the existing backlog; this is a real feature, not a quick fix.
**Estimated effort:** revised down to S (addon Python wiring; no CUDA kernel change) — see CORRECTION. Original "L / register-hostile" estimate was based on a false premise.
**Research note:** [`../docs/pkg217-wavefront-caustic-integration-research.md`](../docs/pkg217-wavefront-caustic-integration-research.md) — READ FIRST (corrected 2026-08-23).

## CORRECTION (2026-08-23, package-implementer — READ THIS FIRST)

The "Refinement" section below and the linked implementation plan
(`.astroray_plan/docs/pkg217-implementation-plan.md`) are **factually wrong**
about the architecture and were NOT implemented. Kept for record; do not
build the `stage_caustic_connect.cu` / NEE-cull design they describe.

**Actual root cause:** the GPU wavefront already has a fully-wired, tested
photon-map caustic pipeline (pkg113): `buildCausticAim` +
`astroray::photon::gpu::cuda_photon_caustic_build` in
`src/gpu/wavefront/gpu_wavefront_snapshot.cu`, gathered at the primary
receiver hit, verified by the PASSING (non-xfail)
`tests/test_gpu_caustic_parity.py::test_gpu_glass_sphere_caustic_parity`.
This pipeline is gated by `Renderer::usePhotonCaustics` (`include/raytracer.h`)
— a renderer-level master switch **separate** from the per-object
`is_caustic_caster` flag. The Blender addon wired the per-object flag
(`set_object_caustic_caster`) but **never called
`renderer.set_use_photon_caustics(True)`**, so the existing, working pipeline
was silently gated off for every Blender scene, producing exactly the
owner's black-shadow repro. `scripts/pkg200_honour_matrix.py` already
documented this exact trap ("GPU caustics gate on a SEPARATE
usePhotonCaustics... the Blender addon does not read the native toggle").

**Fix (Path A):** `blender_addon/__init__.py` (`convert_scene`) and
`blender_addon/exporter.py` (`sync_viewport_scene`) now call
`renderer.set_use_photon_caustics(True)` whenever any object in the
depsgraph has `astroray_object.is_caustic_caster == True`, else `False`
(pre-pass stays off — zero cost — for the common no-caster scene). No CUDA
kernel change. See `tests/test_pkg217_addon_photon_caustic_wiring.py`.

The GPU wavefront **SMS-NEE-cull architecture** described below (a new
`stage_caustic_connect.cu` running `sms_attempt_device.cuh` per-lane, gated
by an NEE cull in `stage_light_sample.cu`) remains a legitimate **future
quality enhancement** (SMS caustics are sharper / lower-variance than
forward photon mapping for point-like casters) but is NOT needed to fix the
repro and was explicitly NOT built this round — building it would have been
redundant with the existing photon pipeline and risked double-counting.
File a fresh package if/when that quality upgrade is prioritised.

## Refinement (2026-08-23 architect planning pass — SUPERSEDED, see CORRECTION above)

This section documents the (incorrect) premise the original plan was built on,
kept for historical record only:

This is a **wiring problem, not a new algorithm.** The engine already has the
caustic machinery; the GPU wavefront just never invokes it:
- CPU SMS caustics = **DONE** (pkg64, `include/astroray/manifold/sms_attempt.h`).
- Device SMS solver header **exists** (`manifold/sms_attempt_device.cuh`).
- `GSphere.isCausticCaster` **already crosses CPU→GPU** (pkg64-gpu Phase 1, probe
  `src/gpu/pkg64_sms_probe.cu`). pkg64-gpu is `superseded` because full wiring was
  deferred as register-hostile.
- **The gap (INCORRECT — see CORRECTION):** `src/gpu/wavefront/stage_light_sample.cu`
  has no caustic path, so a receiver behind glass does ordinary NEE, the shadow ray
  hits the glass, throughput → 0 = black shadow. This ignored the already-wired
  pkg113 photon-map pre-pass in the SAME `cuda_wavefront_render` function.

**Chosen integration (defuses the register problem) — NOT BUILT, see CORRECTION:**
1. **A separate `stage_caustic_connect.cu` kernel**, launched *only* when the scene
   has ≥1 caster (host-side gate — zero cost, zero register change for caster-free
   scenes). The SMS Newton live state lives in this kernel's own register file, NOT
   spilled into `stageShadeBucketed` (REG:254). This is the whole reason to pick a
   separate stage over an inline branch.
2. **Ordinary-NEE cull** (Cycles `PATH_MNEE_SUCCESS` pattern, architecture borrow
   only): when the sampled light is a delta caustic light and casters exist, route
   the lane to the caustic stage instead of emitting the doomed shadow ray. One
   lane-flag bit. Getting this wrong = keep-black (cull too much, no fallback) or
   double-count (cull too little). Keep brute-force PT as silent fallback; classify
   caustic contribution as INDIRECT (unlike Cycles' T96992 bug).
3. **Reuse `sms_attempt_device.cuh`** — do NOT re-derive the solver, and do NOT
   couple to pkg127 (the Specular-Polynomials seed upgrade lands later independently).
4. Spectral dispersion comes for free (per-hero-λ manifold solve; leverages pkg206).

## Goal

A delta light (spot / sun, radius 0) refracting through a glass caustic-caster onto a
diffuse surface currently produces a **fully black shadow** on the GPU wavefront —
the refracted energy is dropped. Make it produce a **caustic** (a bright refracted
light patch), and — because Astroray is spectral — a **dispersion-coloured** caustic
through a Sellmeier prism. Match Cycles' "Shadow Caustics" behaviour.

## Context (reproduced 2026-08-21 via the live Blender MCP)

- Scene: white diffuse floor + closed Sellmeier-glass prism (`is_caustic_caster = True`,
  wired correctly via the Astroray Output node) + a collimated delta spot straight down.
- GPU render: the spot lights the floor (bright pool, 76% lit) but the prism casts a
  **pure-black shadow** — zero transmitted light, no caustic, no dispersion on the floor.
  Direct-VIEW dispersion (camera looking *through* the glass) DOES work; only the
  projected caustic is missing.
- Root cause: a unidirectional path tracer cannot connect a diffuse hit through glass to
  a delta light by ordinary NEE (the light is occluded by the glass) or by BSDF sampling
  (can't randomly hit a delta light through refraction). It needs a dedicated caustic
  method. Astroray has a caustic-caster flag (pkg64, SMS-style, Cycles Shadow-Caustics
  parallel) and the addon sets it, but **the GPU wavefront does not act on it** — caustic
  handling is the register-hostile work deferred in prior rounds (see memory
  `wavefront-shade-kernels-register-saturated`, `closure-graph-lobe-count-spills-the-fused-kernel`,
  and the pkg200 honour-matrix rows `caustics_reflective`/`caustics_refractive` → "genuinely
  register-hostile, deferred to Stage 3").
- CPU status unknown here: the same scene was ALSO black on CPU, but for a DIFFERENT
  reason (the tree-light-sampler-over-empty-list bug, fixed separately 2026-08-21). Re-assess
  the CPU refractive-caustic path once that fix lands — CPU may already support SMS caustics
  and only need verification.

## Specification (sketch — refine at dispatch)

1. **Invoke `cite-algorithm` BEFORE writing code** (CLAUDE.md §6). Candidate methods:
   - **Specular Manifold Sampling** (Zeltner, Georgiev, Jakob 2020) — Cycles' Shadow
     Caustics is a restricted SMS; the caustic-caster flag already mirrors its opt-in.
   - **Manifold Next-Event Estimation** (Hanika, Droske, Fascione 2015).
   - Cycles `integrator/shadow_catcher`/`shade_surface` shadow-caustics path as the parity
     reference. Save a research note to `.astroray_plan/docs/`.
2. Wire the caustic path into the GPU wavefront behind the existing per-object
   `is_caustic_caster` flag, so only opted-in casters pay the cost. MUST clear a register
   probe first (spec-gate like pkg198/pkg199) — the shade kernels are pinned at REG:254;
   any per-hit caustic state that spills tanks non-caustic perf. Isolate via
   `template<bool HasCaustics>` if-constexpr, do NOT bloat the shared kernel.
3. Spectral: the refracted caustic must carry per-λ bending so a Sellmeier prism throws a
   dispersion-coloured caustic (leverages pkg206 hero-λ importance sampling for convergence).
4. CPU/GPU parity: byte-mirrored where feasible; the caustic is a visual gate, not a
   bit-exact one (independent MC streams — per-channel mean-ratio, not SSIM).

## Acceptance criteria

- [ ] Glass prism + collimated delta spot + diffuse floor: the floor under the prism shows a
      BRIGHT caustic patch (not a black shadow) on GPU. Assert mean linear radiance in the
      caustic region > a black-shadow baseline by a stated factor.
- [ ] Sellmeier prism caustic is dispersion-coloured (hue spread in the caustic region;
      guard against salt-and-pepper false positives — visually inspect, memory
      `general-photon-loop-needs-solid-glass`).
- [ ] Non-caustic scenes show NO measurable perf regression (register probe green; the
      caustic path is off unless a caster opts in).
- [ ] CPU parity: the CPU caustic matches GPU within a per-channel mean-ratio band.
- [ ] Cycles Shadow-Caustics parity scene (glass sphere/prism over a floor) — qualitative
      match on caustic shape/brightness.
- [ ] CI green on all matrix jobs.

## Reference

- Blender MCP repro session 2026-08-21 (this file's Context).
- Memory: `wavefront-shade-kernels-register-saturated`, `closure-graph-lobe-count-spills-the-fused-kernel`,
  `general-photon-loop-needs-solid-glass`, `gpu-dielectric-lowers-to-closure-graph`.
- pkg64 (caustic-caster flag), pkg200 honour matrix (caustics_reflective/refractive rows).

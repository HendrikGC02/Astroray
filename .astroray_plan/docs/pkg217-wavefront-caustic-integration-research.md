# pkg217 — GPU wavefront caustic integration research note

**Date:** 2026-08-23
**Author:** architect planning pass (goal-capture).
**Policy:** [CLAUDE.md §6](../../CLAUDE.md) — no invented algorithms. This note
selects an approach and its citations; `cite-algorithm` still runs at dispatch.
**Builds on:** [`caustics-research.md`](caustics-research.md) (the original pkg64
MNEE/SMS literature pass — read it first; the algorithm choice was settled there).

---

## CORRECTION (2026-08-23, package-implementer, verified by the plan's own author)

This note's central claim — "the GPU wavefront simply never invokes [the caustic
machinery]" — is **wrong**. `src/gpu/wavefront/gpu_wavefront_snapshot.cu`
(`cuda_wavefront_render`) already runs a complete, tested forward photon-map
caustic pre-pass (pkg113: `buildCausticAim` + `cuda_photon_caustic_build`,
gathered at the shade stage), gated by `Renderer::usePhotonCaustics` — a
switch the Blender addon never set. See the corrected pkg217 spec for the
full finding and the fix actually shipped (addon wiring only, no CUDA
change). The SMS/NEE-cull architecture this note recommends below remains a
plausible FUTURE quality upgrade over forward photon mapping, but was not
needed for the repro and was not built. Read this note's remainder as
"what SMS-NEE-cull would look like if we ever want it," not as an accurate
description of the current gap.

---

## The key reframing

pkg217 is **not** "invent GPU caustics." The engine already has the caustic
machinery; the GPU wavefront simply never invokes it. Evidence gathered this pass:

- **CPU SMS caustics: DONE** (pkg64, `include/astroray/manifold/sms_attempt.h`,
  `newton_iterate.h`, `mesh_attempt.h`). Prism-accurate spectral caustics work on CPU.
- **Device SMS header exists:** `include/astroray/manifold/sms_attempt_device.cuh`,
  `mesh_attempt.h` is device-compilable.
- **The caster flag already crosses CPU→GPU:** `GSphere.isCausticCaster` survives
  scene upload (pkg64-gpu Phase 1, verified by `src/gpu/pkg64_sms_probe.cu` — a
  probe harness, *not* a production path). pkg64-gpu is marked **superseded**
  because the full wavefront wiring was deferred as register-hostile.
- **The gap:** `src/gpu/wavefront/stage_light_sample.cu` and
  `stage_shade_lambertian.cu` contain **no caustic/SMS reference** (grep confirms
  only `stage_advance.cu` / snapshot mention it, incidentally). So a diffuse
  receiver behind glass connects to the delta light by ordinary NEE, the glass
  occludes the shadow ray, throughput → 0, and the floor renders a **black
  shadow**. Exactly the owner's 2026-08-21 Blender-MCP repro.

So the work is: **wire the existing device SMS solve into a wavefront caustic
connection, gated by `isCausticCaster`, without spilling the REG:254 shade kernels.**

## Cycles' reference behaviour (parity target)

Cycles' "Shadow Caustics" is **MNEE** (Manifold Next Event Estimation, Hanika et
al. 2015), contributed by Reality Labs, inserted **at the light-sampling stage**
(commit `1fb0247497`, task T94120). Mechanics worth mirroring for parity:

- MNEE is a **specialised NEE connection**: from a receiver shading point, through
  a refractive caster, to a caustic-flagged light, solved on the specular manifold.
- A **cascading flag mechanism** (`PATH_MNEE_SUCCESS`) *culls ordinary NEE* to
  caustic lights for rays that should resolve through MNEE — MNEE becomes the *only*
  connection technique receiver→caster→light. This is the design detail that turns
  the black shadow into a caustic: you must both (a) add the manifold connection AND
  (b) suppress the doomed ordinary shadow ray, else you double-count or keep the
  black.
- On MNEE success Cycles disables path regularization (roughness blur) downstream.
- Known Cycles limitations to *not* replicate blindly: MNEE caustics are
  mis-classified as direct light (T96992) and there is no fallback when the walk
  fails (T96991). Astroray should classify caustic contribution as indirect and
  keep brute-force PT as the silent fallback.

**Astroray uses SMS, not MNEE**, for licensing reasons already litigated in
`caustics-research.md` (Cycles MNEE is Apache-2.0-mirror-able but the project chose
the BSD-3 SMS skeleton + per-λ Newton). That is fine: SMS and MNEE solve the same
specular-manifold constraint; Cycles is the *visual* parity oracle, not the code
source. The wavefront integration pattern (connection at light-sample stage +
ordinary-NEE culling through casters) is an *architecture-level* borrow, not code.

## Recommended wavefront integration

1. **New optional stage, not a fatter shade kernel.** Add a
   `stage_caustic_connect.cu` that runs *only* when the scene has ≥1 caster
   (host-side gate: skip the launch entirely otherwise — zero cost for the 99% of
   scenes with no caster). This sidesteps the REG:254 problem: the SMS Newton
   solve's live state lives in a *separate* kernel with its own register file, not
   spilled into `stageShadeBucketed`.
2. **Per-receiver-hit predicate.** In the existing light-sample stage, when the
   sampled light is a delta caustic light AND the scene has casters, route that
   lane to the caustic stage instead of emitting an ordinary shadow ray (the
   `PATH_MNEE_SUCCESS`-style cull). Keep this to a single lane-flag bit.
3. **Reuse `sms_attempt_device.cuh`.** Do not re-derive the solver. The device
   header exists; the two-bounce robustness upgrade is **pkg127** (Specular
   Polynomials) — file pkg217 to consume whatever seed stage is current and let
   pkg127 improve it later. Do not couple them.
4. **Spectral:** the manifold constraint is per-λ (Sellmeier), so the caustic is
   dispersion-coloured for free once the solve runs per hero-λ. Leverage pkg206
   hero-λ importance sampling for convergence (already merged).
5. **Register gate is a HARD acceptance gate** (memory
   `wavefront-shade-kernels-register-saturated`): probe `stageShadeBucketed` /
   `stageAdvance` REG count *unchanged* after the change (the new kernel is
   separate, so this should hold trivially — that is the whole point of choosing a
   separate stage over an inline branch). Use `cuobjdump` post-link + template
   `<bool HasCaustics>` if any shared code is touched.

## Effort / risk

- **Effort:** L. The solver exists; the work is wavefront plumbing (a new stage,
  a lane predicate, queue management) + the NEE-cull + spectral verification +
  CPU/GPU parity gate. Register-hostile *only if* implemented as an inline branch —
  the separate-stage design defuses that.
- **Top risk:** the ordinary-NEE cull. Get it wrong and you either keep the black
  shadow (cull too much, no fallback) or double-count (cull too little). The
  distinguishing test: caustic-region radiance must exceed the black-shadow
  baseline by a stated factor AND the lit-pool region outside the caster shadow
  must be unchanged vs pre-change (no energy added elsewhere).
- **Second risk:** salt-and-pepper false-positive on the dispersion gate (memory
  `general-photon-loop-needs-solid-glass`) — require a solid closed prism with
  outward normals and a visual hue-spread + bright-coverage check, not just a
  variance metric.

## Citations to lock at dispatch
- Zeltner, Georgiev, Jakob, "Specular Manifold Sampling for Rendering
  High-Frequency Caustics and Glints", SIGGRAPH 2020 (Astroray's method; BSD-3 ref
  code skeleton already in-tree via pkg64).
- Hanika, Droske, Manakov, "Manifold Next Event Estimation", EGSR 2015, DOI
  10.1111/cgf.12681 (per-λ Newton math + Cycles parity architecture).
- Cycles `1fb0247497` shadow-caustics commit + T94120 (parity oracle; architecture
  borrow only — GPL kernel not mirrored).
- Fan et al., "Specular Polynomials", SIGGRAPH 2024 (deferred seed upgrade = pkg127).

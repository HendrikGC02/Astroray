# pkg199 — GPU wavefront world volume (homogeneous world medium)

**Pillar:** 5 / integration-first (also 3 — CPU↔GPU parity)
**Track:** A
**Status:** Stage 1 done (PR #611, 2026-08-14 — GPU wavefront homogeneous-world
Beer-Lambert absorption at CPU parity; furnace Tr matches analytic exp(-σ·d) to
<0.02; shade kernel byte-identical REG 254/STACK 3352/CONST 1700). Stage 2 open
(spec-only below — full scattering medium).
**Estimated effort:** Stage 1 M (landed); Stage 2 XL (new scattering subsystem).
**Depends on:** pkg55-C7 wavefront dispatch; [[wavefront-shade-kernels-register-saturated]].

---

## PREMISE CORRECTION (2026-08-14, git-archaeology — supersedes the original filing)

The original spec claimed the CPU "has a working homogeneous world volume … with
Beer-Lambert transmittance … and Henyey-Greenstein anisotropy
(`include/raytracer.h:2110-2255`)" and asked to port HG in-scatter + distance
sampling + NEE-through-medium to the GPU "matching the CPU model exactly." Verified
against HEAD `f965f93`, **that premise was false**:

- There was **no** Henyey-Greenstein phase function, **no** in-scatter, **no**
  distance sampling, **no** NEE-through-medium anywhere in the CPU integrator —
  and there never had been. `worldVolumeAnisotropy` was stored by `setWorldVolume`
  and **read by no render code in the entire git history**.
- The only volume code was `Renderer::worldTransmittance(distance)`
  (`raytracer.h:2159`) — pure Beer-Lambert **absorption** `exp(-σ_t·t)`,
  `σ_t = worldVolumeColor·worldVolumeDensity`.
- That function was **dead code**: repo-wide it appeared only at its definition —
  **zero call sites**. World volume was added in pkg25 (`245d1fa`) wired into the
  **legacy RGB integrator** (3 roles: NEE emission, MIS BSDF-emission, throughput).
  pkg14 (`90ebb31`) **deleted the legacy RGB integrator wholesale**, removing all
  three call sites; they were never ported to the spectral path tracer that is now
  the default. So the CPU rendered fog scenes as **vacuum**, exactly like the GPU.

**Coordinator decision (staged Option B, 2026-08-13):** re-wiring absorption into
the spectral tracer *completes an orphaned feature* (the deletion targeted the RGB
integrator, not world volumes) — sign-off granted. Absorption-only is a strict
subset of the full scattering medium, so the work is **staged**: Stage 1 (below)
lands absorption at CPU↔GPU parity; Stage 2 (below) adds the scattering medium.

Research + design detail: `.astroray_plan/docs/pkg199-world-volume-research.md`.

---

## Stage 1 — homogeneous world absorption (LANDED, this PR)

Bring the **homogeneous world volume as Beer-Lambert absorption** to the GPU
wavefront, at parity with the CPU spectral path tracer (which is re-wired the same
way in the same PR — completing the pkg14-orphaned feature).

**Model (pinned identically on CPU and GPU):** throughput carries per-λ
transmittance `Tr[λ] = exp(-σ_t[λ]·d)` over each traversed segment, with
`σ_t[λ] = upsample_reflectance(worldVolumeColor)[λ] · worldVolumeDensity`.
Spectral discipline: **upsample the colour (JH albedo LUT / GSPEC_RGB_ALBEDO),
then Beer-Lambert per-λ — never upsample the product.** Three roles:

1. **Free-flight** `Tr(rec.t)` on each surface hit (CPU `pathTraceSpectral`; GPU
   `intersectPathSlot` with SoA throughput write-back). Attenuates emission and
   carries the fog into NEE + later bounces.
2. **NEE / shadow ray** `Tr(ls.distance)`/`Tr(s.maxDist)` (CPU NEE block; GPU
   `stageShadowKernel`).
3. **Lamp-MIS emission** `Tr(lh.t)`/`Tr(lampT)` (dedicated lamp closer than the
   surface).

Env-miss (infinite segment) is not attenuated — the mirror-able choice for an env
at infinity and consistent CPU/GPU. `worldVolumeAnisotropy` stays **inert**
(reserved for Stage 2).

**NEE distance + distant/infinite-light convention (hw-611 fix):** role 2
attenuates by the **true geometric vertex→light distance**, never the shadow-ray
occlusion tMax — the GPU NEE sampler sets `maxDist = 1e30` as an occlusion
sentinel for **sphere-primitive** and **distant** lights, and feeding that into
`exp(-σ·d)` collapsed every fogged NEE-to-sphere contribution to a density-
independent near-black (the hw-611 regression). The GPU now carries a separate
`geomDist` (NEE lane 14: ray-sphere near-hit distance for spheres, sampled-point
distance for triangle/point/spot/area) and the CPU uses the already-geometric
`ls.distance`. **Distant / infinite lights** (`DistantLight`,
`ls.distance = FLT_MAX`; GPU `geomDist = 0`) are treated **like env-miss —
NON-attenuated** (`Tr = 1`), both backends guarding `distance ≥ 1e18` (real
sun-through-atmosphere is Stage-2+ territory).

**Register-gate design (satisfied):** all volume transmittance lives in the
**non-pinned** intersect + shadow-resolve stages, gated at runtime by a
`__constant__ GWorldVolume c_worldVolume` symbol. The REG-254-saturated
`stageShadeBucketedKernel` is **not modified at all** → byte-identical by
construction (verified via cuobjdump on the native-sm_120 `.pyd`: all-false
specialization **REG 254 / STACK 3352 / CONSTANT[0] 1700**, unchanged). No 5th
template axis — cleaner than the literal "compile-time HasWorldVolume axis"
suggestion and satisfies its goal; the pkg197 guide-AOV precedent (write from the
intersect stage to keep the shade kernel byte-identical).

### Stage 1 acceptance criteria — all met

- [x] GPU wavefront renders the homogeneous world volume (transmittance +
      NEE-through-medium absorption), **matching the CPU render**: per-channel
      CPU↔GPU mean-ratio on a coloured fog scene = **[1.029, 1.029, 1.043]**
      (within the independent-MC band). Analytic white-fog furnace: GPU Tr matches
      `exp(-σ·d)` to **<0.0002** at dist∈{5,10}, dens∈{0.1,0.2}.
- [x] `__gpu_features__["volumes"]` flips **true** (homogeneous-world absorption
      only; honesty comment scopes out in-scatter/heterogeneous). Guard test
      `test_pkg186_gpu_features_guard` updated (volumes off GPU_DROPPED).
- [x] Vacuum (no world volume) GPU renders unchanged — density-0 == no-volume
      within the GPU atomic-nondeterminism floor; shade kernel byte-identical
      (cuobjdump).
- [x] Un-xfailed the two `test_world_volume_*` fog tests (they now pass on both
      backends).
- [x] RTX 5070 Ti visual confirmation: `pkg199_gpu_fog_{clear,dense}.png` — a
      receding row of spheres fades into the medium with distance (darker +
      desaturated), no god-rays (absorption only, as claimed).

### Stage 1 explicit non-goals (unchanged)

- No in-scatter / HG phase (Stage 2). No heterogeneous / object volumes, no
  `add_volume` scattering (emissive-proxy behaviour stays as-is). No black-hole /
  Pillar-4 volumetric emission ([[pillar4-on-pause]]). No `PASS_VOLUME_*`.
- The opt-in caustic integrator (`pathTraceSpectralCaustic`), the CPU wavefront
  reference (`src/cpu/wavefront/path_kernel.cpp`), and the ReSTIR GPU path do NOT
  carry world-volume absorption in Stage 1 (they use different stages/kernels that
  do not read `c_worldVolume`); the production megakernel-CPU ↔ GPU-wavefront pair
  is the parity target. A follow-up can extend them if needed.

---

## Stage 2 — full scattering medium (SPEC-ONLY; do NOT implement here; XL)

Add genuine volumetric scattering to the homogeneous world medium: **HG in-scatter,
analytic exponential distance sampling of a scatter event, and NEE-through-medium
(phase/light MIS)** — delivering god-rays / light shafts. **CPU FIRST** (the
spectral path tracer has no medium-interaction loop today — Stage 1 only added
absorption multiplies), **then mirror on the GPU wavefront.**

### Estimator (cite — do NOT invent)

- **PBRT-v4** §14.2 volumetric path tracing (`SampleLd` through media,
  `HomogeneousMedium` sampling), §11.3 media, `HGPhaseFunction`; Henyey &
  Greenstein 1941 for the phase function. Reference `src/pbrt/media.cpp`,
  `src/pbrt/cpu/integrators.cpp` (BSD, license-compatible).
- **Cycles** `intern/cycles/kernel/integrator/volume.h` `volume_integrate` /
  `volume_shader_sample` (Apache-2.0) — the Blender-facing reference for
  homogeneous scatter + equiangular/distance sampling + phase MIS.
- Homogeneous → analytic exponential free-flight distance sampling
  `t = -ln(1-ξ)/σ_t` (no delta-tracking needed; that is a heterogeneous-grid
  concern for a later package).

### Register-budget plan (pinned at spec time)

A medium-scatter interaction needs live state the REG-254 shade kernel cannot
absorb: the sampled scatter distance vs surface `t` decision, a phase-function
sample, a phase pdf, and a shadow connection carrying per-segment transmittance.
**Do NOT fold this into `stageShadeBucketedKernel`.** Add a **dedicated
volume-scatter wavefront stage** (its own kernel, scheduled between intersect and
shade): it decides scatter-vs-surface from the sampled free-flight distance,
performs the phase-sampled NEE (parking a shadow sample like the surface NEE does),
and emits the continuation ray from the scatter point. The shade kernel stays
untouched (Stage 1's byte-identity carries forward). Snapshot semantics: pin the
scatter-point `ray_origin` capture moment identically on CPU and GPU at design time
([[wavefront-snapshot-semantics-class-of-bug]]).

### Stage 2 acceptance (for the future package)

- CPU spectral tracer gains a homogeneous medium-interaction loop (scatter event +
  HG phase + NEE-through-medium), validated vs a PBRT/analytic single-scatter
  reference; then GPU wavefront mirror at CPU↔GPU parity on a god-ray scene.
- `worldVolumeAnisotropy` becomes live (HG `g`), with a forward/back-scatter
  visual gate.
- Register gate: shade kernel unchanged; the new volume-scatter kernel's footprint
  reported via cuobjdump.
- Heterogeneous / object volumes / delta-tracking remain OUT (a later package).

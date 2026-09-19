# pkg276 — IES × spot composition parity and GPU wavefront IES modulation

**Pillar:** 3
**Track:** A
**Status:** in-progress — batchP lane, 2026-09-19
**Estimated effort:** 2 sessions (~6 h)
**Depends on:** none

---

## Goal

Before: the CPU spot composition `intensity * 1/(4π) * falloff * angleFalloff *
iesModulation` (`src/lights/spot_light.cpp:97`) is unverified against Cycles'
`spot_light_attenuation` (`kernel/light/spot.h`) times the IES shader output
(`svm/ies.h` -> `util/ies.h::kernel_ies_interp`), and the GPU wavefront applies
NO IES modulation at all — `GDedicatedLight` (`include/astroray/gpu_types.h:933`)
carries no IES slot, so an IES SPOT renders as a plain cone on GPU. After: a
controlled single-spot A/B pins the CPU radial profile per annulus within 5 % of
Cycles per channel (and, where the cylinder is localised, fixes the diverging
factor), and the GPU wavefront applies the same IES modulation behind a
`template<bool HasIES>` axis while every `HasIES=false` kernel stays
byte-identical and `stageShadeBucketedKernel` stays REG 254.

---

## Context

Serves Pillar 3 (Cycles parity). #814 Residual 2 reports the pkg259
`lighting_studio` SPOT+IES backdrop ratio Astroray/Cycles 0.024, but the same
sheet has POINT 0.52, AREA 0.21 and SUN 0.995 — three non-IES booths are also
dim, so that scene cannot attribute the deficit to IES composition. The absolute
candela scale (`4*pi/177.83`) is already Cycles-exact
(`ies-normalization-research.md`, Batch J item 2), so the open questions are the
multiplicative order and cone parameterisation, plus the explicit GPU gap. Left
unfixed, GPU renders of IES lights silently differ from CPU and from Cycles.

---

## Evidence

- 2026-09-14: #814 comment — `lighting_studio` backdrop ratios Astroray/Cycles
  POINT 0.52, SUN 0.995, SPOT+IES 0.024, AREA 0.21; three non-IES booths dim, so
  the studio scene is inconclusive and a controlled A/B is required.
- 2026-09-13: `.astroray_plan/docs/ies-normalization-research.md` — absolute
  candela model implemented; "**GPU gap (explicit, not silently shipped):** IES is
  CPU-only."
- 2026-09: `src/lights/spot_light.cpp:191` and `point_light.cpp:155` — "IES
  modulation not mirrored on the GPU in v1 (follow-up)."
- 2026-09: grep -i "ies" over `src/gpu` and `include/astroray/gpu_types.h`
  returns no IES field/lookup; `GDedicatedLight` has `cosInner/cosOuter` but no
  profile index.
- 2026-09: Cycles `scene/light.cpp` — `spot_smooth = 1/((1 - cos_half_spot_angle)
  * smooth)`; `kernel/light/spot.h` — `spot_light_attenuation` uses that field.

---

## Reference

- Cycles (Apache-2.0): `intern/cycles/kernel/light/spot.h::spot_light_attenuation`
  (`smoothstepf((ray.z - spot->cos_half_spot_angle) * spot->spot_smooth)`);
  `intern/cycles/scene/light.cpp` (`spot_smooth` derivation);
  `intern/cycles/kernel/svm/ies.h::svm_node_ies` (`fac = strength *
  kernel_ies_interp(kg, slot, h_angle, v_angle)`, with `v_angle =
  safe_acosf(-vector.z)`, `h_angle = atan2f(vector.x, vector.y) + M_PI_F`);
  `intern/cycles/kernel/util/ies.h::kernel_ies_interp` (cubic out-of-range clamp,
  deg/rad table);
  `intern/cycles/kernel/light/common.h` (`LightSample` / `LightEval.eval_fac`,
  the field the IES shader output multiplies).
- Astroray: `src/lights/spot_light.cpp` (`angleFalloff`, `sampleLi`,
  `fillDeviceParams`), `src/lights/point_light.cpp`;
  `include/raytracer.h` (`IESProfile::loadFromFile:162`, `sample:249`);
  `include/astroray/gpu_types.h` (`GDedicatedLight:933`, `GNEESample:857`);
  `src/gpu/gpu_nee.cuh` (`gpu_dedicated_sample` ~:180, `gpu_nee_resolve` ~:672);
  `src/gpu/wavefront/stage_light_sample.cu`, `stage_advance.cu`;
  `src/gpu/gpu_spectral_tables.h` / `.cu` (constant-table upload pattern);
  `src/gpu/cuda_renderer.cu`.
- Corpus: `benchmarks/blender_parity/scene_library.py::_ies_wall_washer_lm63`
  (:1953, synthetic LM-63-2002 generator) and `build_lighting_studio_scene`
  (:2003); `benchmarks/reference_corpus/README.md` (:276).
- Round notes: `.astroray_plan/docs/ies-normalization-research.md`,
  `pkg259-phase2-ies-format-research.md`; memory
  `gpu-wavefront-nee-occlusion-deferred-stage`,
  `shade-axis-side-table-avoids-spill`, `noinline-runtime-flag-avoids-shade-spill`;
  `docs/agent-context/renderer-internals.md` §register ceiling (REG 254).

---

## Prerequisites

- [ ] Build passes on main; CPU `astroray*.pyd` newer than HEAD before any CPU
      number is quoted.
- [ ] `build_cuda/astroray.cp313-win_amd64.pyd` newer than HEAD and the project
      GPU lock held for every CUDA build and GPU gate run.
- [ ] `cite-algorithm` note saved to
      `.astroray_plan/docs/pkg276-ies-spot-research.md` before changing
      composition or GPU sampling (Cycles function citations recorded).
- [ ] `cuobjdump` on PATH for the REG / byte-identity gate.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `tests/test_pkg276_ies_spot_profile.py` | CPU radial-profile gate: render the controlled single-spot A/B and compare the centre-to-edge per-channel radial profile against an analytic numpy evaluation of the SAME LM-63 table times the Cycles `spot_light_attenuation` formula, within 5 % per annulus above the noise floor. |
| `tests/test_pkg276_gpu_ies_parity.py` | GPU-marked ROI gate: same scene rendered on CPU and GPU; per-channel ROI mean ratio within 3 %. |
| `.astroray_plan/docs/pkg276-ies-spot-research.md` | `cite-algorithm` note: exact Cycles compositions, chosen cone/angle mapping, and the measured radial tables. |

### Files to modify

| File | What changes |
|---|---|
| `src/lights/spot_light.cpp` | Only the factor the A/B localises: `angleFalloff` cone mapping (`spot_size`/`spot_blend` -> `cosInner/cosOuter`) and/or `iesModulation` composition, to match `spot_light_attenuation` x `kernel_ies_interp`; cite the exact Cycles functions. |
| `include/raytracer.h` | `IESProfile::sample` interpolation / angle convention only if the A/B localises a lookup divergence; the `4*pi/177.83` scale is untouched. |
| `include/astroray/gpu_types.h` | Add one IES profile index to `GDedicatedLight` and a side-table entry struct; no change to the existing field meanings. |
| `src/gpu/gpu_nee.cuh` | `gpu_dedicated_sample`: apply `kernel_ies_interp`-equivalent modulation to `dedGeoScale` for `GDED_POINT`/`GDED_SPOT` behind a `HasIES` axis. |
| `src/gpu/wavefront/stage_light_sample.cu` | Carry the same `HasIES` axis on the wavefront light-sample path so no call site silently drops the modulation. |
| `src/gpu/wavefront/stage_advance.cu` | `template<bool HasIES>` axis / side-table wiring; `stageShadeBucketedKernel` REG must stay 254. |
| `src/gpu/gpu_spectral_tables.h` | Declare the `__constant__` IES side table + upload entry (pkg218 emission-profile-table pattern). |
| `src/gpu/gpu_spectral_tables.cu` | Define the IES side table and its host-callable upload. |
| `src/gpu/cuda_renderer.cu` | Upload IES tables once per scene alongside the existing profile/emission tables. |
| `module/blender_module.cpp` | Binding only if the CPU probe needs to read a loaded table through the module; otherwise untouched. |

### Key design decisions

- **Composition is multiplicative, as in Cycles.** Cycles' light shader output
  `fac = strength * kernel_ies_interp(h_angle, v_angle)` multiplies the light's
  `eval_fac`, which already carries `spot_light_attenuation`. Astroray's
  `intensity * 1/(4π) * falloff * angleFalloff * iesModulation` is the same
  product, so only a localised scalar divergence is changed — do not restructure
  the composition speculatively.
- **Match the Cycles cone parameterisation, not the ad-hoc one.** Cycles uses
  `smoothstepf((ray.z - cos_half_spot_angle) * spot_smooth)` with
  `spot_smooth = 1/((1 - cos_half_spot_angle) * smooth)`; Astroray currently
  uses `t = (cosTheta - cosOuter)/(cosInner - cosOuter)`. The A/B decides whether
  the Blender `spot_size`/`spot_blend` -> `cosInner/cosOuter` mapping reproduces
  the Cycles field; if not, adopt the Cycles field.
- **Angle convention must be pinned.** Cycles evaluates IES in the light-local
  frame (`v_angle = acos(-vector.z)`, `h_angle = atan2(x, y) + π`); Astroray
  builds an orthonormal basis off `axis_`. A radial profile cannot detect an
  azimuth mirror, so the test also checks the asymmetric synthetic profile's
  azimuthal lobe, not just the radial mean.
- **`template<bool HasIES>` axis, byte-identical off path.** Every affected
  kernel gets the axis; the `HasIES=false` specializations must be byte-identical
  to main by `cuobjdump`, following the pkg253 `stageShadowKernel<*,false>`
  precedent and `shade-axis-side-table-avoids-spill`. Verify with `cuobjdump`
  before/after and report STACK, not just a clean compile.
- **Constant side table, not a per-light branch.** Upload IES tables once into a
  `__constant__` side table (pkg218 `g_emissionProfileTable` layout) and carry a
  single index on `GDedicatedLight`; reserve a separate profile cap from
  `G_MAX_PROFILES`. If the table exceeds the constant budget, fall back to a
  texture read behind the same axis rather than enlarging the hot struct.
- **Deferred shadow stage risk.** The wavefront resolves NEE occlusion in the
  deferred shadow stage (memory `gpu-wavefront-nee-occlusion-deferred-stage`). IES
  is a directional factor on emission, so fold it into `dedGeoScale` in the
  SAMPLE stage (where the dedicated light is sampled) and carry nothing new
  across the A -> B -> C split; check every `gpu_dedicated_sample` call site,
  including paths that skip dedicated lights.

#### Controlled single-spot A/B

- One SPOT light, one synthetic LM-63 profile (reuse
  `_ies_wall_washer_lm63()` or a radially parametrised synthetic table),
  `spot_size = 60°`, `spot_blend = 0.15`, aimed straight down at a single grey
  Lambertian plane, no other light, black world, fixed top-down camera.
- Measure the radial profile centre-to-edge, per channel (R, G, B), binned into
  annuli; the Astroray CPU / Cycles per-annulus ratio must lie in [0.95, 1.05]
  above the noise floor. 60°/0.15 puts several annuli inside the smoothstep blend
  plus a full core and a zero outside.
- The same synthetic LM-63 and the same `spot_size`/`spot_blend` feed both
  engines; the analytic numpy reference uses the same table interpolation and the
  Cycles `spot_light_attenuation` formula.

#### GPU leg design constraints

- Tables uploaded as a `__constant__` side table or texture behind the
  `template<bool HasIES>` axis; the fleet stays byte-identical for
  `HasIES=false`.
- Shared `stageShadeBucketedKernel` REG must stay 254 — `cuobjdump` before/after
  on every changed shade specialization; STACK growth reported.
- The wavefront skips dedicated lights in places, so audit each
  `stage_light_sample.cu` / `gpu_dedicated_sample` call site against memory
  `gpu-wavefront-nee-occlusion-deferred-stage` before trusting the parity number.

---

## Acceptance criteria

- [ ] CPU controlled single-spot A/B radial profile per-annulus per-channel ratio
      vs Cycles within 5 % per annulus above the noise floor —
      `tests/test_pkg276_ies_spot_profile.py` green.
- [ ] The CPU gate compares against an analytic numpy evaluation of the same
      LM-63 table x Cycles `spot_light_attenuation`, not a second render.
- [ ] `tests/test_pkg276_gpu_ies_parity.py` GPU-marked, GPU/CPU ROI mean ratio
      within 3 % per channel, green on the RTX 5070 Ti.
- [ ] GPU render of an IES SPOT shows a modulated beam, not a plain cone
      (qualitative visual inspection by a visual-capable agent).
- [ ] ~~`stageShadeBucketedKernel` REG stays 254 / 0 spill, and all `HasIES=false`
      specializations are `cuobjdump` byte-identical to main.~~ **Amended (lead,
      2026-09-20):** the GPU leg uses a runtime `__constant__` IES flag + a
      `__noinline__` IES evaluation (pkg224 pattern), not a `template<bool HasIES>`
      axis — the axis doubles the 128-way shade fleet and `stage_advance.cu` compile
      time on every build (owner: builds are the biggest time sink). New gate: every
      shade specialization keeps REG 254 and the STACK of the Batch P baseline build
      (627bfe67), kernels not touched stay `cuobjdump` byte-identical, and a non-IES
      perf A/B (burn-in + min-of-N) is within noise. If REG or STACK moves, fall back
      to the template axis.
- [ ] Existing `tests/test_batch_a_ies_export.py` and non-IES dedicated-light
      parity suites stay green.
- [ ] Before/after renders saved under `test_results/` and inspected.
- [ ] `cite-algorithm` note saved under
      `.astroray_plan/docs/pkg276-ies-spot-research.md`.

---

## Non-goals

- Do not change the absolute photometry scale `4*pi/177.83`
  (`kCandelaToWatt = 0.0706650768394`), and do not re-introduce
  peak-normalisation.
- No new light types.
- No area-light IES.
- Do not change the unified light CDF, light selection, or MIS weighting.
  **Exception (lead, 2026-09-20):** radius-0 point/spot NEE weight 1 (Batch P commit
  0c6d888b) — an energy-loss bug found by the controlled A/B (0.910x / 0.722x /
  0.397x vs analytic for 1 / 2 / 4 lamps), Cycles gives such lamps no MIS
  (`surface_shader_bsdf_eval`). Reviewed by cycles-parity.
- No threshold relaxation on any existing parity gate.
- Do not change the Cycles-exact non-IES light radiometry (pkg122).

---

## Progress

- [ ] Step 1 — save the cite note, build the controlled single-spot A/B, and
      measure the CPU radial profile vs Cycles to localise any diverging factor.
- [ ] Step 2 — fix the localised CPU composition and land the analytic CPU gate.
- [ ] Step 3 — implement the GPU leg behind `template<bool HasIES>`, upload the
      IES side table, and run the GPU parity + REG/byte-identity gates.

---

## Lessons

*(Fill in after the package is done.)*

What was harder than expected? What would you do differently? What
should the next agent know before starting a similar package?

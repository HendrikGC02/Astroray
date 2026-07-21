# pkg122 — Dedicated-light energy calibration (re-derive wattage→radiance against Cycles, per-type)

**Pillar:** 3 (light transport / emitter energy correctness)
**Track:** A (CPU-first re-derivation with a live headless-Cycles A/B oracle; GPU dedicated-light path verified on RTX once pkg89 GAP-1 lands)
**Codex-paste-ready:** no (multi-type physical re-derivation against a live external oracle, one cross-cutting convention adjudication, and an owner-reserved reference-bank re-bless list — needs judgment at each step, not a mechanical patch)
**Status:** in review — **implementation on branch `pkg122-light-energy-calibration` (PR pending)**. Defects 1–3 (AREA solid-angle-pdf measure, POINT/SPOT `1/(4π)` intensity, BLACKBODY photopic normalization) + DISTANT irradiance fix re-derived against Cycles `kernel/light/{area,point,spot,distant}.h` + `scene/light.cpp` (research note: `.astroray_plan/docs/pkg122-light-energy-calibration-research.md`); GPU `gpu_nee.cuh` mirrored for parity; regression gates in `tests/test_pkg122_light_energy_calibration.py`. **Defect 4 (RGBIlluminant vs RGBUnbounded) deliberately DEFERRED** — needs a live-Cycles A/B build (implementer has no MSVC vcvars) and is owner-reserved (moves the reference bank). Team-lead builds, runs the gates, RTX-verifies GPU==CPU, and produces the re-bless deltas.
**Estimated effort:** M–L (four coupled energy defects across `AreaLight`/`PointLight`/blackbody + one convention decision that cross-cuts materials/env/reference-bank; each fix is small but each must be re-derived and validated against a live Cycles render, not guessed)
**Depends on:** **pkg89 GAP-1** — the dedicated-light GPU-upload PR (branch `feat/pkg89-dedicated-light-gpu`). Until dedicated lights are actually resident on the GPU, the wavefront leg has nothing to calibrate; GAP-1 must land so the GPU path evaluates the same `EmissionSpectrum` / `sampleLi` energy that this package fixes on the CPU. Land order: GAP-1 → pkg122.

---

## Context — this is the root cause of the standing "addon renders dimmer than Cycles" complaint

The owner's long-standing complaint that Astroray renders **dimmer than Cycles** — first quantified in the **pkg115 texture-grid finding**, re-confirmed **2026-06-12**, and root-caused on **2026-07-19** by the pkg89 GAP-2 energy audit — traces directly to the dedicated-light energy path, not to the integrator or the tonemap. The audit measured each dedicated light type against a Cycles-calibrated reference and found the errors are **large, type-specific, and in opposite directions**, so no single global brightness knob can reconcile them:

- Dedicated **AREA** light renders **0.13×** the Cycles-calibrated geometry area light at equal wattage (dim), and the error is **size-dependent**.
- Dedicated **POINT** light renders **~3.6× brighter** than the analytic value (bright).
- **BLACKBODY** emission is **~14× too bright** and chromatically **blue** at 6500 K.

This package closes that complaint at its source: re-derive each type's wattage→radiance against the Cycles kernel with a **live headless-Cycles A/B render as the oracle**, fix the measure bug, fix the blackbody normalization, and adjudicate the emission-spectrum convention once for all emitter paths.

---

## Goal

**Before:** The pkg89 dedicated-light types each compute wattage→radiance with an
ad-hoc chain of factors (`intensity × normalizeFactor × kM1PiF × geometricFactor`,
`src/lights/area_light.cpp:88-90`, `src/lights/point_light.cpp:77-79`) that was
tuned per-type during Phase B to pass individual gates (G4 intensity 100→320, G2
D65 <12% with a TODO), never re-derived as a coherent radiometric pipeline. The
result is measurably wrong per-type and in different directions (see Context):
AreaLight is dim and size-dependent, PointLight is bright, blackbody is bright-and-blue.
The emission-spectrum convention (`RGBIlluminantSpectrum` vs `RGBUnboundedSpectrum`)
is **unresolved and self-contradictory in the tree** — the 2026-05-21 parity
reviewer recommended `RGBUnboundedSpectrum` for emitters
(`.astroray_plan/docs/pkg89-phase-b-cycles-parity-2026-05-21.md:128-131`), while
the live `evalRGB` comment rejected that as "over-broad" and kept
`RGBIlluminantSpectrum` (`src/emission_spectrum.cpp:104-115`).

**After:** Each dedicated light type's wattage→radiance is **re-derived against the
corresponding Cycles kernel file** and validated so a dedicated light at a given
Blender wattage produces the **same image-plane radiance as Cycles** (and as the
Cycles-calibrated geometry-emitter path) to within a tight tolerance, **for all
light sizes**. Specifically: the `AreaLight::sampleLi` measure bug is fixed so the
error is size-**independent** and ≈ 1.0×; PointLight matches the analytic
`ρP/(4π²d²)`; blackbody carries the pkg89 Q11 photopic-luminance normalization and
is neither 14× bright nor blue at 6500 K; and the emission-spectrum convention is
**decided once** and applied consistently across every emitter path
(`EmissionSpectrum::evalRGB`, materials, env), with the affected reference-bank
scenes explicitly enumerated for owner re-blessing.

---

## Root cause — the four defects, stated precisely (from the GAP-2 audit, 2026-07-19)

Full findings: `.astroray_plan/docs/pkg89-energy-audit-2026-07.md` (lands in the
in-flight pkg89 PR on `feat/pkg89-dedicated-light-gpu`). Harness config for the
measurements below: pkg115 grid — area light size 3, energy 300, height 3.

### Defect 1 — AreaLight: solid-angle / pdf-measure sampling bias (size-dependent, 0.13×)

`AreaLight::sampleLi` (`src/lights/area_light.cpp:52-104`) folds a **solid-angle
geometric factor** `cosθ_light / dist²` into the emission
(`geometricFactor`, line 84; applied line 90) **but returns a pure area-measure
pdf** `1 / area_` (line 103), with no area→solid-angle conversion
(`pdf_ω = pdf_A · dist² / cosθ_light`). The two measures are mixed. This is
**not** a missing constant: the measured error is **0.13× at size 3** and
**collapses to ~1.4× for a small, far light** — a signature that the two
conventions agree only in the small-solid-angle limit and diverge as the light's
solid angle grows. A global multiplier cannot fix a size-dependent ratio; the fix
is to make the pdf and the geometric term use **one consistent measure**, matching
Cycles `area_light_sample`. Note the interaction with `normalizeFactor_ = 1/area`
(`src/light.cpp:15-24`, applied at `area_light.cpp:49`): re-derivation must treat
`normalizeFactor_`, `kM1PiF`, `geometricFactor`, and the pdf measure as **one
system**, not four independently-tuned knobs.

### Defect 2 — PointLight: ~3.6× too bright vs analytic ρP/(4π²d²)

`PointLight::sampleLi` (`src/lights/point_light.cpp:77-79`, pdf = 1.0 for the delta
case, line 96) produces radiance `emission · intensity · normalizeFactor · kM1PiF ·
(1/dist²)`, i.e. two separate 1/π factors (`normalizeFactor_ = 1/π` from
`computeNormalizeFactor(1.0, true)`, line 27; plus `kM1PiF`, line 77). Measured
**~3.6× brighter** than the analytic `ρP/(4π²d²)`. This is the **opposite
direction** from Defect 1 — confirming no global brightness factor reconciles the
two. The 2026-05-21 parity note (lines 103-104) had said the point light *omitted*
`M_1_PI_F`; Phase B then *added* `kM1PiF`, and the light is now over-bright — so
the current factor stack over-corrected and must be re-derived against Cycles
`point_light_sample`, not nudged again.

### Defect 3 — Blackbody: ~14× too bright and blue at 6500 K (missing Q11 normalization)

`EmissionSpectrum::evalBlackbody` (`src/emission_spectrum.cpp:74-101`) returns raw
Planck radiance scaled by `1e9` (W/(m²·sr·m) → per-nm, line 88) with **no photopic
normalization**, and a **white-tint short-circuit** (lines 79-92) that returns the
bare Planck curve when `tint_rgb == (1,1,1)`. The pkg89 **Q11 resolution**
(spec §"Q11 (owner-confirmed)") called for `normalize = true` to divide by the
**integrated photopic luminance** (Cycles `light_normalize_factor`), so the
artist's intensity slider is perceptually stable across temperature. That
normalization was never implemented for the blackbody path —
`computeNormalizeFactor` (`src/light.cpp:15-24`) only does **geometric** 1/area
normalization, not the photopic-luminance normalization Q11 specified. Result:
**~14× too bright**, and **blue at 6500 K** because raw Planck radiance in
W/(m²·sr·nm) is short-wavelength-weighted relative to a luminance-normalized SPD.

### Defect 4 — Unresolved emission-spectrum convention (RGBIlluminant vs RGBUnbounded)

`EmissionSpectrum::evalRGB` (`src/emission_spectrum.cpp:111-115`) uses
`RGBIlluminantSpectrum` (D65-weighted). The 2026-05-21 parity reviewer explicitly
recommended replacing it with `RGBUnboundedSpectrum` for emitters, matching PBRT-v4
`DiffuseAreaLight` (no D65 factor)
(`pkg89-phase-b-cycles-parity-2026-05-21.md:127-131`, open question lines 223-225).
The live `evalRGB` comment (`src/emission_spectrum.cpp:104-110`) **rejected** that
change as "over-broad" — it would drop point/background/spot-rgb illuminance ~3×
and break G5/G4. The two references **disagree**, and the choice **cross-cuts**:
`RGBUnboundedSpectrum` vs `RGBIlluminantSpectrum` changes every RGB-mode emitter,
and the same convention question touches material-color upsampling and env-map
emission. It must be **adjudicated once**, with the reference-bank impact measured —
not toggled per-gate. This is the highest-risk item because it can move the
**12/13-passing Cycles-parity reference bank**.

---

## Fix plan (cite — no inventions, CLAUDE.md §6)

**The oracle is a live headless-Cycles A/B render, not the geometry-emitter proxy.**
Each type's target radiance is measured by rendering the *same* scene in headless
Cycles at equal wattage/geometry and comparing image-plane radiance. The
geometry-area-light path (pkg115 harness) may be used as a fast secondary check but
is **not** the gate oracle — it is itself only Cycles-*calibrated*, and Defect 1 is
partly a story about that proxy disagreeing with Cycles as size grows.

### A. Re-derive AreaLight against `kernel/light/area.h` (fix the measure bug)

- Mirror Cycles `area_light_sample` (`intern/cycles/kernel/light/area.h`,
  Apache-2.0): sample the area, then return the pdf in the **same measure** the
  integrator consumes. Either (i) keep emission in radiance and return a
  **solid-angle** pdf `pdf_A · dist² / cosθ_light`, or (ii) keep the area-measure
  pdf and drop the `dist²/cosθ` from the throughput — whichever matches how
  `LightList::sample` consumers divide. Pick the convention Cycles uses and make
  the whole chain consistent. **Verify size-independence:** the fixed error ratio
  must be ≈ 1.0× at size 3 **and** for the small-far light (the two configs that
  bracket the size-dependent bias today).
- Cite the exact Cycles function and the eval-factor line
  (`intern/cycles/scene/light.cpp` `eval_fac = invarea * M_1_PI_F`) in the code and
  reconcile it with `normalizeFactor_`/`kM1PiF` as one derivation.

### B. Re-derive PointLight against `kernel/light/point.h`

- Mirror Cycles `point_light_sample` / `point_light_eval`
  (`intern/cycles/kernel/light/point.h`, Apache-2.0) and its `eval_fac`. Establish
  which single 1/π belongs in the chain; the current double factor
  (`normalizeFactor_` = 1/π **and** `kM1PiF`) is the likely source of the ~3.6×.
  Validate against both the analytic `ρP/(4π²d²)` and the live-Cycles point-light
  A/B.
- **SpotLight and DistantLight:** re-derive against `kernel/light/spot.h` and
  `kernel/light/distant.h` in the same pass and confirm they were not left with an
  analogous factor bug (the audit focused on area/point/blackbody; spot/distant
  share the `computeNormalizeFactor` + `kM1PiF` stack and must be checked, not
  assumed correct).

### C. Blackbody photopic normalization (implement pkg89 Q11)

- Add the photopic-luminance normalization Q11 specified: divide the Planck SPD by
  its integrated photopic luminance so a `normalize = true` blackbody has stable
  perceived intensity across temperature. Cite Cycles
  `scene/light.cpp::light_normalize_factor` (Apache-2.0). This must run **on the
  white-tint path too** — the short-circuit (`emission_spectrum.cpp:79-92`)
  currently skips normalization entirely, which is why the bare-Planck case is the
  worst offender. Target: 6500 K blackbody is neutral (matches D65 chromaticity
  within the G2 tolerance) and not ~14× bright.

### D. Adjudicate the emission-spectrum convention **once** (Defect 4)

- Decide `RGBIlluminantSpectrum` vs `RGBUnboundedSpectrum` for emitters by
  measuring **both** against live Cycles for an RGB-mode emitter, and apply the
  winner uniformly across `evalRGB` and any other emitter RGB path. Reference
  PBRT-v4 `DiffuseAreaLight` (Apache-2.0) and Cycles' emitter color handling. If
  the answer differs from the material-color convention, document **why** emission
  and reflectance legitimately use different upsamples (the D65 weighting is
  correct for reflectance, contested for emission — the reviewer's point at
  `pkg89-phase-b-cycles-parity-2026-05-21.md:106-109`).
- Because this can move the reference bank, treat the decision as owner-visible:
  land the code behind the enumerated re-bless list in the next section rather than
  silently re-blessing.

### E. Live-Cycles A/B calibration harness + gates

- Build a small headless-Cycles A/B harness (or extend the pkg115 grid harness) that
  renders each dedicated light type and its Cycles equivalent at equal
  wattage/geometry and reports the image-plane radiance ratio. Gate each type at
  ratio ∈ a tight band (e.g. [0.97, 1.03]) **and** assert size-independence for the
  area light (ratio at size 3 and at the small-far config agree within tolerance).
- CPU-first; the wavefront/GPU dedicated-light leg is verified on RTX against the
  CPU result once pkg89 GAP-1 makes dedicated lights GPU-resident.

---

## Reference-bank re-blessing (owner-reserved — explicit list)

Per repo convention, **re-blessing reference images is owner-reserved**. This
package changes emitter energy and (pending Defect 4) possibly the emission-color
convention, so it will shift reference outputs. The implementer must **not**
re-bless; instead, produce this owner-visible list with before/after ratios and
hand it to the owner:

- [ ] Every scene in the **Cycles-parity reference bank** whose output moves
      (start from the 12/13-passing set; enumerate exactly which of the 13 shift
      and by how much).
- [ ] pkg89 gate scenes affected by the energy change: **G1** (dedicated-lights
      zoo, one per type), **G2** (blackbody D65 chromaticity), **G4** (spot cone
      center intensity — Phase B set this to 320 via the now-suspect factor stack),
      **G5** (point hard shadow).
- [ ] The **pkg115 texture-grid** reference (the scene that first surfaced the
      "dimmer than Cycles" complaint) — expected to move toward Cycles.
- [ ] Any **material** or **env** reference that moves **if** Defect 4 changes the
      shared RGB-emission convention (only if D's decision touches non-light paths).

Deliver the list with measured deltas; owner decides which to re-bless.

---

## Acceptance criteria

- [ ] AreaLight measure bug fixed against Cycles `area_light.h`: live-Cycles A/B
      ratio ≈ 1.0× **and size-independent** (size-3 and small-far configs agree),
      replacing today's 0.13× / 1.4× spread.
- [ ] PointLight re-derived against Cycles `point_light.h`: matches analytic
      `ρP/(4π²d²)` and live-Cycles A/B within tolerance (removes the ~3.6×).
- [ ] SpotLight + DistantLight re-derived in the same pass and confirmed
      calibrated (not assumed correct).
- [ ] Blackbody photopic normalization (pkg89 Q11) implemented incl. the white-tint
      path: 6500 K is neutral (G2 tolerance) and not ~14× bright.
- [ ] Emission-spectrum convention (Defect 4) adjudicated **once** against live
      Cycles + PBRT-v4 and applied uniformly across all emitter RGB paths; rationale
      for any emission-vs-reflectance divergence documented in code.
- [ ] Live-Cycles A/B calibration harness + per-type gates land (CPU-gated,
      CI-runnable); wavefront/GPU dedicated-light leg RTX-verified against CPU once
      GAP-1 is in.
- [ ] Owner-visible reference-bank re-bless list produced with measured deltas
      (implementer does **not** re-bless).
- [ ] Research/citation note in `.astroray_plan/docs/` recording the per-type Cycles
      derivations (`area.h`/`point.h`/`spot.h`/`distant.h` + `light_normalize_factor`),
      pinned commit SHA, and the Defect-4 decision with evidence.

---

## Non-goals

- **Not a global brightness knob.** The audit proved the errors are per-type and
  opposite-signed; a single multiplier is explicitly rejected.
- **Not the integrator / MIS.** BSDF-side MIS is pkg120; this package is emitter
  **energy**, not transport weighting. If a residual gap survives after
  calibration, hand it to pkg120, don't re-tune emitters to mask it.
- **Not new light types or new sampling strategies.** Uses the existing
  `Light` types and `LightList` interface; only the energy/measure/normalization
  math changes.
- **Not re-blessing reference images.** Owner-reserved; this package only produces
  the list.
- **Not the tonemap / exposure pipeline.** The "dimmer than Cycles" complaint is
  root-caused to emitter energy here; display transform is out of scope.
- **Not Phase-C mesh-emitter unification** (pkg89 Phase C). Emissive-`Material`
  faces keep their existing path.

---

## Provenance

Filed from the **pkg89 GAP-2 CPU energy-scale audit (2026-07-19)**
(`.astroray_plan/docs/pkg89-energy-audit-2026-07.md`, landing in the in-flight
pkg89 PR on `feat/pkg89-dedicated-light-gpu`). The audit measured each dedicated
light type against a Cycles-calibrated reference (pkg115 harness) and found:
AreaLight 0.13× and size-dependent (→ a solid-angle/pdf-measure bias in
`AreaLight::sampleLi`, not a constant); PointLight ~3.6× bright; blackbody ~14×
bright and blue at 6500 K (missing the pkg89 Q11 photopic normalization); and an
unresolved `RGBIlluminantSpectrum` vs `RGBUnboundedSpectrum` emission convention
where the 2026-05-21 parity reviewer and the live `evalRGB` comment disagree. This
package directly attacks the owner's standing **"addon renders dimmer than Cycles"**
complaint (pkg115 texture-grid finding, re-confirmed 2026-06-12, root-caused
2026-07-19). Depends on pkg89 GAP-1 (dedicated-light GPU upload) landing first.

---

## Progress

- [x] A — AreaLight measure re-derivation (`area.h`): plain-radiance emission +
      solid-angle pdf `dist²/(area·cosθ)` (was area-measure `1/area`, breaking MIS).
      Size-independence gated in `test_area_light_size_independence`; live-Cycles
      ratio pending team-lead build.
- [x] B — PointLight re-derivation (`point.h`): intensity `I = P/(4π)` (was `P/π`,
      the 4× ≈ audit's 3.59×). SpotLight re-derived (same `1/(4π)`, delta pdf; was
      `1/π`+`1/coneSA`). DistantLight re-derived (carry radiance `S/Ω`; was `Ω×` too
      dim ≈ black sun).
- [x] C — Blackbody photopic normalization (Q11): divide by integrated luminance;
      applied on the white-tint path too. `test_blackbody_temperature_stability`.
- [ ] D — Emission-spectrum convention: **DEFERRED** (needs live-Cycles build +
      owner re-bless). Analysis in the research note; `evalRGB` left as `RGBIlluminant`.
- [~] E — Per-type CPU gates land (`tests/test_pkg122_light_energy_calibration.py`).
      GPU `gpu_nee.cuh` mirrored; RTX GPU==CPU verify + live-Cycles A/B are the
      team-lead's post-build step (implementer cannot build the `.pyd`/CUDA).
- [ ] Owner re-bless list — enumerated qualitatively in the research note; measured
      deltas require the build (implementer does NOT re-bless).

---

## Lessons

*(Fill in after the package is done.)*

# pkg89 — Dedicated Light Objects — SPEC

**Pillar:** 3 (light transport)
**Track:** A
**Status:** spec promoted from DRAFT (architect spec-promotion pass,
  2026-05-14). 12 design forks from the research note resolved or
  surfaced to owner; the four owner-blocking questions (Q1, Q6, Q7,
  Q11) were already owner-answered per the round8-dispatch-queue and
  are recorded here as confirmed. See "Design decisions" + "Owner-
  preference questions deferred to owner". Ready to dispatch once the
  one remaining owner-preference question is answered.
**Estimated effort:** 3–4 weeks across two phases (A: interface +
  types + integrator wiring, B: Blender addon migration). Phase C
  (mesh-emitter unification) is a separate future package.
**Depends on:** none for Phase A. pkg86 (Light Tree) is **parallel** —
  either order is safe (see research §6.3). pkg88 (motion blur) is
  **parallel** — research §10 Q9 punts the `time` parameter to
  whichever package lands second (architect-resolved below).
**Composes with:** pkg86 directly (provides `Light::orientationCone()`,
  `Light::power()`, `Light::bounds()` for Conty 2018 metric); pkg88
  via the time-coupling resolution in Q9 below.

---

## Goal

**Before:** Astroray models every light as emissive geometry — a
`Hittable` (Sphere, Triangle, `AreaLightShape`, `SpotLightSphere`,
`DistantLight`) with an emissive `Material`. Seven light-related
virtuals (`emittedRadiance`, `directionFalloff`, `pdfValue`, `random`,
`isLight`, `isInfiniteLight`, `emittedRadiance(normal, toPoint)`)
live on `Hittable`, carried as no-op overrides by every non-emissive
primitive. Blender POINT lights have **no first-class representation**
— the addon fakes them as 0.1-m emissive spheres
(`blender_addon/__init__.py:3289-3298`). Spectral emission is
per-`Material`, forcing one `Material` instance per Blender light.
The pkg86 Light Tree's Conty 2018 importance metric needs per-cluster
orientation cones — a Light-level concept that today must be
synthesized from material + geometry + `directionFalloff`. **And** —
the audit surfaced an existing bug: `LightList::sample` collapses
emission to RGB before downstream code re-upsamples to spectral,
silently losing spectral fidelity.

**After:** A first-class `astroray::Light` interface (sibling to
`Hittable`, not derived from it) with five concrete types — Point,
Spot, Distant, Area, Background — each carrying its own spectral
emission (Blackbody / measured-SPD / RGB-upsample / composite) and
emission-direction profile (isotropic / cone+IES / sun-disk /
Lambertian-with-spread / envmap-CDF). `LightSample` extends to carry
`SampledSpectrum emission_spec` alongside the existing RGB `emission`
(ReSTIR contract preserved). pkg86's Conty 2018 metric reads
`Light::orientationCone()` and `Light::power()` directly. Blender's
POINT light becomes an actual isotropic point. Two area lights at
2700 K and 6500 K stop needing two `Material` instances. The RGB-
collapse bug is fixed end-to-end.

---

## Reference

Comprehensive research note:
[.astroray_plan/docs/dedicated-lights-research.md](../docs/dedicated-lights-research.md)

That note is the primary algorithmic source of truth. Key cross-
references:

- §2.2 — the audit-discovered RGB-collapse bug.
- §4.1 — the proposed `Light` interface.
- §5 — per-type emission direction profiles.
- §6.3 — pkg86 dovetail.
- §10 — twelve design forks (resolved below).
- §12 — decision summary (one-line per fork).

---

## Phase list

| Phase | Scope | Effort | Blocking |
|---|---|---|---|
| **A** | **Interface + 5 dedicated types.** `include/astroray/light.h` with `Light` virtual; `PointLight`, `SpotLight`, `DistantLight`, `AreaLight`, `BackgroundLight` implementations; `EmissionSpectrum` composable; `LightSample.emission_spec` field; `LightList::sample` signature widens to `(pt, normal, lambdas, gen)`; five integrators updated in one PR. | 2–3 weeks | none |
| **B** | **Blender addon migration.** New `add_point_light` binding (no more `add_sphere(0.1)` hack); existing `add_sun_light` / `add_area_light` / `add_spot_light` bindings refactored to accept `EmissionSpectrum` parameters (blackbody temperature *or* RGB). | 1 week | A |
| **C** | **(out of scope)** Wrap emissive triangles into `TriangleAreaLight` under the hood; `DiffuseLight` / `Emissive` materials become thin shims. | separate package | A, B |

Recommended landing order: A → B. Phase C follows up only if measured
demand surfaces.

---

## Non-goals

- **GPU port.** `pkg89-GPU` is the explicit follow-up: mirror Cycles'
  tagged-union `KernelLight` and a flat device array. Phase split
  mirrors pkg64 → pkg64-gpu. pkg89 itself is CPU-only.
- **GoniometricLight and ProjectionLight.** PBRT-v4 supports both;
  Cycles does not. File as `pkg89-goniometric` follow-up if artist
  demand surfaces.
- **PortalImageInfiniteLight.** Out of scope; pkg14's envmap CDF
  already importance-samples background light adequately.
- **Removing the emissive-`Material` codepath.** `DiffuseLightPlugin`
  and `EmissivePlugin` materials continue to work for artist-authored
  emission shaders on mesh faces. Unification is Phase C.
- **Adaptive `area_light_spread_clamp_light` (Cycles).** Variance-
  reducing visibility-cone-intersection sampling. Astroray v1 keeps
  the simpler emission-side `spread` cone gate. File as
  `pkg89-spread-tightening` if needed.
- **Light-source motion blur.** Resolved by Q9 below.
- **TM-30 light source quality metrics.** Out of scope.
- **Camera DoF coupling with `DistantLight` / `SpotLight`.** Documented,
  not solved. See Q8.
- **Touching `Hittable`'s seven light-related virtuals.** They stay
  in v1; removing them is Phase C surface area.

---

## Design decisions (forks from research §10)

This section resolves all twelve forks from research §10. The four
owner-blocking questions (Q1, Q6, Q7, Q11) were already owner-answered
per the round8-dispatch-queue; they are recorded here as confirmed.
The remaining eight are resolved by architect or surfaced to owner.

### Q1 (owner-confirmed). Polymorphic `vector<unique_ptr<Light>>` vs `variant`

**Confirmed: `std::vector<std::unique_ptr<Light>>` for CPU.** PBRT-v4
pattern. Extensible, clean. Heap allocation per light is fine — light
counts per scene are O(10) to O(10⁴), not the hot path. GPU mirror
(`pkg89-GPU` follow-up) will use a tagged-union POD à la Cycles
`KernelLight` because GPU side needs flat-array, no-virtual access.

- Reference: PBRT-v4 `src/pbrt/lights.h` (Apache-2.0); Cycles
  `intern/cycles/scene/light.h` for the eventual GPU mirror shape.

### Q2. `TriangleAreaLight` area cached at construction vs recomputed

**Resolved by architect: cached at construction.** Triangle vertices
are immutable post-build in the static-scene case; in the motion-blur
case (pkg88), area is time-varying but only over the small shutter
window — caching the central-time area is the correct trade-off
(matches Cycles' static-area assumption in motion-aware NEE). When
pkg88 lands, the cached area covers the typical case; revisit only
if highly-anisotropic-deformation lights surface as a problem.

- Reference: Cycles `kernel/light/triangle.h` `triangle_light_sample`
  computes area on-the-fly per intersection, but the *importance CDF*
  uses cached per-triangle area (`object_volume_pass`). We mirror the
  CDF caching.

### Q3. IES parse eager vs lazy

**Resolved by architect: eager (at scene-upload time).** IES files
are < 10 KB each, parse takes < 1 ms, and a scene's IES file list is
known at upload. Astroray's existing `IESProfile::loadFromFile`
already loads eagerly. Lazy parsing would add a dispatch branch at
the leaf sampling path for zero practical benefit.

- Reference: research note §10 recommendation; Astroray
  `include/raytracer.h:102` (existing parser).

### Q4. `BackgroundLight` and `DistantLight` coexist or one supersedes

**Resolved by architect: coexist.** Cycles convention. A sun + sky
scene needs both (Distant for the sun disk, Background for the
sky envmap). Treating them as separate types matches the Blender data
model (`light.type == 'SUN'` vs `world.use_nodes` environment shader)
and lets the importance-sample logic stay distinct (cone-sample for
Distant, marginal-CDF for Background).

- Reference: Cycles `kernel/light/distant.h` + `kernel/light/background.h`.

### Q5. `SpectralProfile::reflectance(λ)` reused for emission or new `emission(λ)` alias

**Resolved by architect: add a thin inline `emission(λ)` alias that
forwards to `reflectance(λ)`, with documentation.** The
`SpectralProfile` curve database stores curve *shapes*; the same
shape can represent reflectance (when applied to a BSDF) or relative
SPD (when applied to emission). The interpretation is per-caller. An
explicit `emission(λ)` alias makes the call site self-documenting; a
header comment in `spectral_profile.h` records the dual-interpretation
contract. One inline method, no extra cost.

- Reference: research note §4.2 mode 2.

### Q6 (owner-confirmed). `LightSample` extends vs replaces RGB `emission`

**Confirmed: extend.** Add `SampledSpectrum emission_spec` next to
the existing RGB `emission`. ReSTIR's `targetLuminanceRGB()` path
(`include/astroray/restir/light_sample.h:66`) depends on the RGB
field; replacing it would break ReSTIR. The two fields are kept
consistent inside `Light::sampleLi` (compute `emission_spec` first,
derive `emission` via `emission_spec.toXYZ(lambdas) → XYZtoRGB`).
Memory cost: 16 B per `LightSample`; negligible.

- Reference: research note §4.3 + §2.5.

### Q7 (owner-confirmed). `LightList::sample` signature break: one-PR vs overload

**Confirmed: one-PR sweep across all five integrators.** Mechanical
change. Five call sites:

- `multiwavelength_path_tracer`
- `spectral_path_tracer`
- `restir_di`
- `neural_cache`
- `caustic_path_tracer` (and `sms_caustic_path_tracer`)

Every changed line traces to "carry spectral emission and shading
normal through NEE" — surgical-change rule (CLAUDE.md §3) holds.

- Reference: research note §6.2 + §10 Q7.

### Q8. Camera DoF interaction with `DistantLight` / `SpotLight`

**Resolved by architect: document, don't solve.** Cycles ships a
lens-coupled-spot path tracer behavior (the spot beam is refracted
through the camera lens at primary hit). PBRT-v4 doesn't. Astroray
v1 documents the limitation in `Light::sampleLi`'s doxygen and ships
the simpler "spot beam is straight in world space" behavior. File as
`pkg89-lens-lights` follow-up if shot demand surfaces.

- Reference: research note §10 Q8.

### Q9. Motion blur (pkg88) coupling — does `Light` get a `time` field?

**Resolved by architect: no `time` field in pkg89 v1. The
integration point is per-package-landing-order:**

- **If pkg89 lands first** (current Round 8 plan): `Light::sampleLi`
  signature is `(shadingPoint, shadingNormal, lambdas, gen)` without
  `time`. When pkg88 lands, pkg88's PR widens the signature to add a
  `float time` parameter. The two-package coordination is recorded
  in pkg88's cross-package notes.
- **If pkg88 lands first**: pkg88's PR widens the existing
  `Hittable::random` / `LightList::sample` signatures with `time`;
  pkg89's `Light::sampleLi` is born with the `time` parameter.

This is a coordinated change either way; the architect-pass
confirmation is that *neither package needs to wait for the other to
ship*. The package landing second absorbs the signature widening.

- Reference: pkg88 spec "Cross-package notes"; research note §10 Q9.

### Q10. `EmissionSpectrum::Composite` for gel filters

**Resolved by architect: compose at construction, not first-class.**
Multiply the SPD shape by the gel transmission curve once at
`EmissionSpectrum::composeWith()` time, store the product. Avoids a
dispatch branch per `sampleLi`. The composite *kind* is internally
just `ProfileSPD` (the product is a new SPD); no new dispatch enum
needed.

- Reference: research note §10 Q10.

### Q11 (owner-confirmed). Cycles per-light `normalize` flag

**Confirmed: implement, default `true` (Cycles parity).** Blackbody-
temperature lights produce raw radiance in W/(m²·sr·m) that scales
wildly with temperature; `normalize = true` divides by the integrated
photopic luminance so the artist's "intensity" slider behaves
intuitively. Cycles defaults to `true` for this reason. Implementer
judgment for the exact integration math — Cycles
`light_normalize_factor()` is the reference.

- Reference: Cycles `scene/light.cpp::light_normalize_factor`;
  research note §10 Q11.

### Q12. `IESProfile` on `PointLight` (Cycles) or only on `SpotLight`

**Resolved by architect: allow on both.** Cycles convention.
`PointLight` with IES is the "exposed bulb" use case; `SpotLight`
with IES is the "fixture beam shape" use case. Both are physically
meaningful. The orientation cone for `PointLight + IES` widens to
full-sphere (the IES profile is the direction modulation, not a
cone restriction). One extra optional field on `PointLight` — cheap.

- Reference: Cycles `kernel/light/point.h::point_light_eval` reads
  `KernelLight::ies_offset` regardless of light type.

---

## Owner-preference questions deferred to owner

The four originally-blocking questions (Q1, Q6, Q7, Q11) are already
owner-answered. One **new** owner-preference question surfaced during
the architect pass:

### Q-Owner-1 (new): Default spectral-emission model for Blender lights

When the Blender addon converts a `bpy.types.Light` to an Astroray
dedicated light, it must pick an `EmissionSpectrum` kind. Three
candidate defaults:

- **Blackbody from `light.color_temperature`** (Blender 5.x exposes
  this on POINT/SPOT/SUN/AREA). If the user set a temperature, use
  blackbody; else fall back to RGB. Most physical, most Cycles-like
  for cinematic workflows.
- **RGB-upsample from `light.color`** always (Jakob–Hanika
  upsample). Simplest, matches the addon's current factoring.
- **Composite: blackbody × RGB tint** when both are set. Most
  flexible but defies "pick one default" — most renderers don't ship
  this dual-mode.

**Architect recommendation:** option 1 — blackbody when `color_temperature`
is set on the Blender light, RGB-upsample otherwise. Matches Cycles'
behavior when the user toggles "Blackbody" in the shader graph.

**Question for owner:** option 1 (blackbody-when-temperature-set), or
option 2 (RGB-always)?

**Owner answer:** _________________

(Other potential owner-preference forks — units exposed to Blender
users for `light.energy`, exact normalize formula sign convention —
are deferred to the implementer; they're below the architect-pass
threshold and have unambiguous Cycles-parity answers.)

---

## Architect-pass addendum (delta from research note)

The research note (764 lines, 2026-05-14) is sound. Two observations
from the architect pass:

1. **The audit-discovered RGB-collapse bug (research §2.2) is real
   and is fixed end-to-end by Q6's resolution.** The
   `LightList::sample` → integrator path currently round-trips
   `SampledSpectrum → RGB → SampledSpectrum`, losing spectral
   information. Carrying `emission_spec` through `LightSample`
   closes the loop. The implementer should add a regression gate
   (G8 in research §7) that verifies the `targetLuminance(lambdas)`
   computed from `emission_spec` matches the round-tripped
   `targetLuminanceRGB()` to within 1 % at 1000 samples on a
   blackbody-illuminant scene.

2. **No 13th fork surfaced.** The research note's twelve questions
   plus the one owner-preference question above cover the design
   surface completely. Implementer can dispatch immediately after
   Q-Owner-1 is answered.

3. **Mitsuba 3 has no light-tree / dedicated-lights infrastructure
   either** (it dropped many production features 0.6 → 3.0). The
   active references are **Cycles** (Apache-2.0, primary mirror) and
   **PBRT-v4** (Apache-2.0, design citation). Confirmed via
   WebSearch 2026-05-14.

---

## Cross-package notes

- **pkg86 (Light Tree).** Direct consumer. `LightTree::build` reads
  `Light::power(lambdas)`, `Light::orientationCone()`,
  `Light::bounds()`. For emissive `Hittable`-based lights still in
  the tree, `LightList` wraps them in a shim that synthesizes these
  accessors from `boundingBox()` / `luminance(emittedRadiance())` /
  normal-or-axis (research note §6.3).
- **pkg88 (Motion Blur).** See Q9. No `time` field in v1; absorbed by
  whichever of pkg88 / pkg89 lands second.
- **pkg55 (Wavefront).** Unaffected. Wavefront NEE stage reads the
  same `LightList::sample` interface; the widened signature is a
  source-only change.
- **pkg64 / pkg64-gpu (existing).** `pkg89-GPU` follow-up will mirror
  this pattern: CPU virtual + GPU tagged-union.

---

## Specification (files to create / modify, by phase)

### Phase A — Interface + types + integrator wiring

| File | Change |
|---|---|
| `include/astroray/light.h` (NEW) | `Light` abstract base + `OrientationCone` struct + per-light common fields (`castShadow`, `useMIS`, `useCaustics`, `maxBounces`, `normalize`). |
| `include/astroray/lights/point_light.h` (NEW) | `PointLight` with optional `radius`, optional `IESProfile*`. |
| `include/astroray/lights/spot_light.h` (NEW) | `SpotLight` with cone (`innerAngle`, `outerAngle`), optional `IESProfile*`. |
| `include/astroray/lights/distant_light.h` (NEW) | `DistantLight` with `axis` + `angularDiameter`. |
| `include/astroray/lights/area_light.h` (NEW) | `AreaLight` with shape (rect/disk/ellipse) + `spread`. |
| `include/astroray/lights/background_light.h` (NEW) | `BackgroundLight` wrapping `EnvironmentMap`. |
| `include/astroray/emission_spectrum.h` (NEW) | `EmissionSpectrum` composable (Blackbody / ProfileSPD / RGB / Composite-as-product). |
| `include/astroray/spectral_profile.h` (MODIFY) | Add inline `emission(λ)` alias forwarding to `reflectance(λ)`; document dual-interpretation. |
| `include/raytracer.h` (LightList) | Add `std::vector<std::unique_ptr<Light>> dedicatedLights`; unify power CDF over both kinds; `addLight()` accessor; `lightAt(i) → std::variant<const Hittable*, const Light*>`. |
| `include/raytracer.h` (LightSample) | Add `astroray::SampledSpectrum emission_spec` field. |
| `include/raytracer.h` (LightList::sample) | Widen signature: `sample(pt, normal, lambdas, gen)`. |
| `src/integrators/multiwavelength_path_tracer.cpp` | Update NEE call site to pass `(rec.point, rec.normal, lambdas, gen)`; consume `ls.emission_spec`. |
| `src/integrators/spectral_path_tracer.cpp` | Same. |
| `src/integrators/restir_di/*.cpp` | Same; verify ReSTIR `targetLuminanceRGB()` is unchanged. |
| `src/integrators/neural_cache/*.cpp` | Same. |
| `src/integrators/caustic_path_tracer.cpp` + `sms_caustic_path_tracer.cpp` | Same. |
| `tests/lights/test_dedicated_lights_zoo.py` (NEW) | One scene per type; SSIM / spectral correctness regression. |

### Phase B — Blender addon migration

| File | Change |
|---|---|
| `blender_addon/__init__.py` (`convert_scene`) | Replace `add_sphere(0.1)` for POINT with `add_point_light(position, radius=light.shadow_soft_size, emission=...)`. Refactor `add_sun_light` / `add_area_light` / `add_spot_light` bindings to accept `EmissionSpectrum` (blackbody temperature or RGB; chosen per Q-Owner-1). |
| `module/blender_module.cpp` | Bind new `add_point_light`; update existing `add_*_light` signatures. |
| `blender_addon/__init__.py` (UI) | Optional: expose color-temperature override if Blender doesn't already (5.x mostly does). |

---

## Validation gates (research §7 verified)

| Gate | What | Pass condition |
|---|---|---|
| **G1** | Render `tests/scenes/dedicated_lights_zoo.py` — one of each type | SSIM ≥ 0.98 vs reference. |
| **G2** | Blackbody spectral correctness | `EmissionSpectrum::fromBlackbody(6500, 1.0)` mean XYZ matches D65 within 1 %. |
| **G3** | IES profile correctness | Standard IES file; candela distribution matches within 5 % at 8 sample angles. |
| **G4** | Spot cone falloff | Inner-cone intensity ∝ `cos²(θ)/r²`; outside outer cone = 0. |
| **G5** | POINT light isotropy regression | Hard shadows possible from `radius=0` POINT (previously impossible with the 0.1 m sphere hack). |
| **G6** | No regression on `DiffuseLight` mesh emission | Existing emissive-mesh tests pass unchanged. |
| **G7** | pkg86 composability | LightTree over mixed dedicated + emissive scene shows ≥ 2× variance reduction on `many_lights.py` (matches pkg86's own gate). |
| **G8** | ReSTIR target-weight stability | `targetLuminanceRGB()` matches `targetLuminance(lambdas)` round-trip within 1 % at 1000 samples. (This is the RGB-collapse-bug regression gate.) |
| **G9** | `LightList::sample` signature break is clean | `rg "lights\.sample\(" -t cpp` shows zero call sites with the old signature. |

---

## License fence (research §8 verified)

| Source | License | Use |
|---|---|---|
| Cycles `intern/cycles/scene/light.{h,cpp}`, `kernel/light/{point,spot,area,distant,background,triangle}.h` | Apache-2.0 | Mirror sampling math, cone attenuation, IES integration. Pin commit SHA in `THIRD_PARTY_LICENSES.md`. |
| PBRT-v4 `src/pbrt/lights.{h,cpp}` | Apache-2.0 | Second opinion on interface shape; cite §12 in code comments. |
| IES LM-63-2019 | Public standard | Astroray's `IESProfile` already implements; no license issue. |
| Astroray pkg38 spectral profiles | In-tree | Reuse `SpectralProfile` for measured-SPD emission. |
| Planck blackbody | Public-domain physics | Already implemented in `spectral.h:15`. |

---

## Effort estimate (research §11 confirmed)

| Phase | Scope | Effort |
|---|---|---|
| **A** | Interface + 5 types + `emission_spec` + 5-integrator NEE update + unit tests | **2–3 weeks** |
| **B** | Blender addon migration | **1 week** |
| **C** | (out of scope) `TriangleAreaLight` unification | separate package |
| **Total pkg89** | | **3–4 weeks** |

Critical-path risk: the 5-integrator signature widening in Phase A.
Mitigation: G6 + G8 regression gates; single-implementer dispatch.

---

## When this spec is ready to dispatch

When Q-Owner-1 (default spectral-emission model for Blender lights)
is answered in this conversation and the answer is edited into the
spec body above. No further architect pass required. Owner-confirmed
blocking forks Q1, Q6, Q7, Q11 are already recorded.

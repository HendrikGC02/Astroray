# pkg89 — Dedicated Light Objects — DRAFT

**Pillar:** 3 (light transport)
**Track:** A
**Status:** research signed off — **not yet ready to implement**
  (research note exists, §10 design questions unresolved). The `-DRAFT`
  suffix signals this. A real `pkg89-dedicated-lights.md` spec gets
  filed once an implementer is about to be dispatched and the §10 forks
  are resolved.
**Estimated effort:** 3-4 weeks across two phases (A: interface +
  types + integrator wiring, B: Blender addon migration). Phase C
  (mesh-emitter unification) is a separate future package.
**Depends on:** none for Phase A. pkg86 (Light Tree) is **parallel** —
  either order is safe (see research §6.3). pkg88 (motion blur) is
  **parallel** — research §10 Q9 punts the `time` parameter to whichever
  package lands second.

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
synthesized from material + geometry + `directionFalloff`.

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
2700 K and 6500 K stop needing two `Material` instances.

---

## Reference

Comprehensive research note:
[.astroray_plan/docs/dedicated-lights-research.md](../docs/dedicated-lights-research.md)

That note is the primary design artifact for this package. It covers
the existing-architecture audit (§2), the proposed `Light` interface
(§4.1), per-type emission direction profiles (§5), integration with
`LightList` / pkg86 / ReSTIR / Blender addon (§6), validation gates
(§7), license fence (§8), and the twelve unresolved design questions
(§10). Read it in full before writing the real pkg89 spec.

Key cross-references from that note:
- §2.2 — the audit-discovered bug where `LightList::sample` collapses
  emission to RGB and lets downstream re-upsample, instead of carrying
  `SampledSpectrum` end-to-end.
- §6.3 — pkg86 dovetail. pkg86's non-goal #2 explicitly anticipated
  this re-scope.
- §10 — twelve design forks. **This draft cannot be promoted to a
  real spec until Q1, Q6, Q7, Q11 are decided** (the rest can be
  resolved in PR review).

---

## Phase list

The full plan from research §6.6 + §11:

| Phase | Scope | Effort | Blocking |
|---|---|---|---|
| **A** | **Interface + 5 dedicated types.** `include/astroray/light.h` with `Light` virtual; `PointLight`, `SpotLight`, `DistantLight`, `AreaLight`, `BackgroundLight` implementations; `EmissionSpectrum` composable; `LightSample.emission_spec` field; `LightList::sample` signature widens to `(pt, normal, lambdas, gen)`; five integrators updated in one PR. | 2-3 weeks | none |
| **B** | **Blender addon migration.** New `add_point_light` binding (no more `add_sphere(0.1)` hack); existing `add_sun_light` / `add_area_light` / `add_spot_light` bindings refactored to accept `EmissionSpectrum` parameters (blackbody temperature *or* RGB). Addon reads `light.color`, `light.energy`, and where exposed `light.color_temperature` / `light.cycles.blackbody`. | 1 week | A |
| **C** | **(out of scope)** Wrap emissive triangles into `TriangleAreaLight` under the hood; `DiffuseLight` / `Emissive` materials become thin shims. | separate package | A, B |

Recommended landing order: A → B. Phase C as a follow-up if warranted
after measuring the addon migration cleanup.

---

## Non-goals

This package does **not** do any of the following. Each is a hard
stop; escalate before expanding scope.

- **GPU port.** pkg89-GPU is the explicit follow-up: mirror Cycles'
  tagged-union `KernelLight` and add a flat array on the device side.
  Phase split mirrors pkg64 → pkg64-gpu. pkg89 itself is CPU-only.
- **GoniometricLight and ProjectionLight.** PBRT-v4 supports both;
  Cycles does not. Niche; file as `pkg89-goniometric` follow-up if
  artist demand surfaces.
- **PortalImageInfiniteLight.** HDRI portals. Out of scope; pkg14's
  envmap CDF already importance-samples background light adequately
  for our scenes.
- **Removing the emissive-`Material` codepath.** `DiffuseLightPlugin`
  and `EmissivePlugin` materials continue to work for artist-authored
  emission shaders on mesh faces. Unification is Phase C, separate
  package.
- **Adaptive `area_light_spread_clamp_light` (Cycles).** The
  variance-reducing visibility-cone-intersection sampling. Astroray
  v1 keeps the simpler emission-side `spread` cone gate
  (`AreaLightShape::emittedRadiance(normal, toPoint)` style). File as
  `pkg89-spread-tightening` if needed after measurement.
- **Light-source motion blur as a separate path.** If pkg88 lands
  first, the `Light` interface gains a `time` parameter via that PR.
  If pkg89 lands first, the `Light::sampleLi` signature is
  time-agnostic in v1 and `pkg89-motion` is the follow-up. See
  research §10 Q9.
- **TM-30 light source quality metrics.** pkg89 ships spectral
  emission machinery; quality-metric reporting is out of scope.
- **Camera DoF coupling with `DistantLight` / `SpotLight`.**
  Cycles ships a lens-coupled-spot path. Astroray documents but does
  not solve in pkg89. Possible `pkg89-lens-lights` follow-up.
- **Touching `Hittable`'s seven light-related virtuals.** They stay.
  Removing them is Phase C surface area.

---

## Open design questions (must be resolved before implementing)

Copied from research §10 verbatim — the real pkg89 spec must pick one
answer per row and justify the call. The four **bold** rows are the
ones that block promoting this DRAFT to a real spec; the rest can be
resolved in PR review.

| # | Question |
|---|---|
| **Q1** | Polymorphic `vector<unique_ptr<Light>>` vs `variant<PointLight, ...>` for the CPU collection. |
| Q2 | `TriangleAreaLight` area cached at construction or recomputed. |
| Q3 | IES parse eager vs lazy. |
| Q4 | `BackgroundLight` and `DistantLight` coexist or one supersedes. |
| Q5 | `SpectralProfile::reflectance(λ)` reused for emission or new `emission(λ)` alias added. |
| **Q6** | `LightSample` extends with `SampledSpectrum emission_spec` or replaces RGB `emission`. |
| **Q7** | `LightList::sample` signature break — one-PR sweep across five integrators, or overload-and-migrate. |
| Q8 | Camera DoF interaction with `DistantLight` / `SpotLight`. |
| Q9 | Motion blur (pkg88) coupling — does `Light` get a `time` field in v1. |
| Q10 | `EmissionSpectrum::Composite` for gel filters: 1st-class type or compose-at-construction. |
| **Q11** | Cycles per-light `normalize` flag (radiometric vs photometric). |
| Q12 | `IESProfile` allowed on `PointLight` (Cycles convention) or only on `SpotLight`. |

See research note §10 for recommended answers and rationale per item.

---

## When this draft becomes a real spec

When all of the following are true:

- pkg86 (Light Tree) is at least design-frozen, so Phase A's
  `Light::orientationCone()` / `Light::power()` accessor shapes can
  be aligned to pkg86's exact consumer needs.
- An implementer is available to start work in the next round.
- §10 questions Q1, Q6, Q7, Q11 have agreed answers (the rest can be
  resolved in PR review).
- The Round `NEXT_STAGE_REPORT` has dedicated lights in the
  deployable set.

At that point: copy this draft to `pkg89-dedicated-lights.md` (no
`-DRAFT` suffix), fill in the `## Specification` "Files to create"
and "Files to modify" tables phase-by-phase using the integration
points listed in research §6, and resolve §10 questions inline.

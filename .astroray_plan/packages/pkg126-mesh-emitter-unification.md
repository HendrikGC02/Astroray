# pkg126 — Mesh-emitter unification (pkg89 Phase C: one sampling interface for dedicated + emissive-geometry lights)

**Pillar:** 3 (light transport / emitter architecture)
**Track:** A (CPU-first interface unification, gated on no-regression against the existing emissive-mesh + dedicated-light suites; GPU mirror follows the established CPU-virtual → GPU-tagged-union pattern)
**Codex-paste-ready:** no (a cross-cutting interface unification touching every integrator's NEE call site and the `Hittable` light-virtual surface — a re-architecture requiring judgement and staged verification, not a mechanical patch)
**Status:** open — **UNBLOCKED 2026-07-24** (the pkg122 dependency is satisfied: PR #500 merged 2026-07-21 as `2b18a1d`, energy/convention contract calibrated and frozen; Defect-4 emission-spectrum convention adjudicated in pkg142/#512 — keep `RGBIlluminant` D65). NOT queued for the 2026-07-24 overnight run: L-effort cross-cutting re-architecture (five integrators + `Hittable` virtuals + GPU mirror) with a no-visible-change outcome — wrong shape for an unattended night; needs a dedicated day arc.
**Estimated effort:** L (unify two light-sampling paths under one interface across five integrators + the light-tree + the GPU mirror, while keeping every existing emissive-mesh and dedicated-light gate green — a large, staged change)
**Depends on:** **pkg122 (dedicated-light energy calibration)**. Both the dedicated lights and the emissive-geometry `diffuse_light` material currently emit through the **same disputed `RGBIlluminantSpectrum` convention** (energy audit: "Both the dedicated lights and the geometry `diffuse_light` material emit through `RGBIlluminantSpectrum`"). pkg122 re-derives each dedicated type's wattage→radiance **and adjudicates that emission-spectrum convention once** (pkg122 Defect 4). Unifying the two sampling paths **before** that convention is settled would bake an un-calibrated, possibly-wrong energy contract into the unified interface. Land order: pkg122 → pkg126. **Composes with pkg86** (Light Tree) — the unified interface must keep feeding `Light::power()`/`orientationCone()`/`bounds()` to the Conty 2018 metric.

---

## Context — the long-deferred pkg89 Phase C

pkg89 shipped a first-class `astroray::Light` interface (Phase A, PR #294) and the
Blender addon migration (Phase B, PR #317), and uploaded dedicated lights to the GPU
(GAP 1, PR #489). Its **Phase C was explicitly carved out as a separate future
package** from the start:

- pkg89 spec Phase list, row C: *"Wrap emissive triangles into `TriangleAreaLight`
  under the hood; `DiffuseLight` / `Emissive` materials become thin shims"* —
  marked **"(out of scope) … separate package"** (`pkg89-dedicated-lights.md:76`).
- pkg89 Non-goals: *"Removing the emissive-`Material` codepath. `DiffuseLightPlugin`
  and `EmissivePlugin` materials continue to work … Unification is Phase C"*
  (`pkg89-dedicated-lights.md:92-95`).
- pkg89 Non-goals: *"Touching `Hittable`'s seven light-related virtuals. They stay
  in v1; removing them is Phase C surface area"* (`pkg89-dedicated-lights.md:105-106`).

This package is that Phase C.

---

## Goal

**Before:** Astroray samples lights through **two parallel paths** that NEE code
must handle separately. `LightList` carries both an emissive-**geometry** list —
`std::vector<...> lights` of `Hittable`s with an emissive `Material`
(`include/raytracer.h:1241` region) — and a dedicated-**Light** list —
`std::vector<std::unique_ptr<astroray::Light>> dedicatedLights`
(`include/raytracer.h:1243`), added via `addLight` (`:1276`), exposed via
`getDedicatedLights` (`:1313`). Emissive geometry is sampled through seven
light-related virtuals bolted onto **every** `Hittable`, emissive or not —
`pdfValue`, `isLight`, `emittedRadiance()`, `directionFalloff`, and the
`emittedRadiance(lightNormal, toPointDir)` overload
(`include/raytracer.h:762-768`) — carried as no-op overrides by every non-emissive
primitive. Dedicated lights are sampled through `Light::sampleLi`. NEE, MIS,
light-tree traversal, and the GPU mirror all straddle both representations.

**After:** Emissive geometry is wrapped, under the hood, as first-class `Light`
objects (a `TriangleAreaLight` / mesh-emitter `Light` around emissive triangles),
so **all** NEE sampling goes through the single `Light` interface. `DiffuseLight`
and `Emissive` materials become **thin shims** that register a wrapping `Light` at
scene-build time instead of driving a separate `Hittable`-virtual sampling path. The
seven `Hittable` light virtuals are retired (or reduced to the minimum the BVH-hit
emission-lookup genuinely needs). `LightList::sample`, the light tree, the five
integrators, and the GPU tagged-union all see **one** light kind. No visible change
to any render: every existing emissive-mesh and dedicated-light gate stays green,
now served through the unified path.

---

## Root cause — why two paths is a standing liability

The dual representation is the reason several recent packages had to do their work
*twice* or reason about *both* sides:

- The pkg89 GAP-2 energy audit had to compare dedicated AREA vs the **geometry**
  `AreaLightShape` emitter as separate calibration targets, and found they disagree
  (dedicated 0.13× the geometry path) partly *because* they are different code
  (`pkg89-energy-audit-2026-07.md`, Measurement 1).
- pkg120's two-sided MIS must reconstruct `lightPdf_hit` for a BSDF-ray that hits an
  emitter — and that emitter can be either kind, so the pdf reconstruction has to
  match **both** the `Hittable::pdfValue` path and the `Light` selection pdf.
- The light tree (pkg86) already had to wrap emissive `Hittable`s in a shim that
  synthesizes `power()`/`orientationCone()`/`bounds()` from geometry
  (pkg89 spec "Cross-package notes"). Unification makes that shim the *only* path.

Unifying collapses these into one sampling contract, one pdf, one energy
calibration surface, and one GPU mirror — which is exactly why it must wait for
pkg122 to fix and freeze the energy/convention contract first.

---

## Fix plan (cite — no inventions, CLAUDE.md §6)

### A. A mesh-emitter `Light` wrapping emissive triangles

Introduce a `TriangleAreaLight` (or mesh-emitter) `Light` type that samples an
emissive triangle by area and returns a `LightSample` in the same measure and with
the same `emission_spec` contract as the pkg89 dedicated `AreaLight`. Cache
per-triangle area at construction (pkg89 Q2 resolution:
`pkg89-dedicated-lights.md:127-140`, "cached at construction … we mirror the CDF
caching"). Emission comes from the triangle's emissive `Material`, evaluated through
the **pkg122-adjudicated** emission-spectrum convention (not re-litigated here).

**Cite:** Cycles `intern/cycles/kernel/light/triangle.h` `triangle_light_sample`
(Apache-2.0) — the canonical emissive-triangle area sample and its area→solid-angle
pdf; the pkg89 spec already names this as the Q2 reference
(`pkg89-dedicated-lights.md:137-140`). PBRT-v4 `src/pbrt/lights.h`
`DiffuseAreaLight` (Apache-2.0) as the interface second opinion. Reuse the pkg122
`AreaLight` measure derivation so the mesh emitter and the dedicated area light use
**one** area→solid-angle pdf (the whole point of unification).

### B. `DiffuseLight` / `Emissive` materials become thin shims

At scene build, an emissive `Material` (`plugins/materials/diffuse_light.cpp`,
`plugins/materials/emissive.cpp`) registers a wrapping mesh-emitter `Light` for its
faces via `LightList::addLight` (`include/raytracer.h:1276`) instead of relying on
the `Hittable` light-virtual path. The material still evaluates emission when a BSDF
ray *hits* the surface directly (camera/specular emission lookup), but **NEE
sampling** of that emitter goes through the `Light`. Keep the materials working —
pkg89 Non-goals kept them functional; Phase C makes them shims, not deletions of the
emission-on-hit behavior.

### C. Retire the seven `Hittable` light virtuals

Once all NEE sampling is via `Light`, remove (or reduce to the minimum the
BVH-hit-emission path needs) the light virtuals at `include/raytracer.h:762-768`
(`pdfValue`, `isLight`, `emittedRadiance()`, `directionFalloff`,
`emittedRadiance(lightNormal, toPointDir)`). This is the "Phase C surface area" pkg89
deferred (`pkg89-dedicated-lights.md:105-106`). Do a repo-wide sweep for each
retired virtual before removing it (CLAUDE.md build/verification rule) — these are
overridden as no-ops across many primitives, so the sweep confirms no caller depends
on the emissive branch outside the emitter path.

### D. Unify `LightList::sample`, the light tree, and the five integrators

`LightList::sample` and the power CDF already span both kinds
(`include/raytracer.h:1309` `empty()` checks both lists); collapse the sampling body
so it iterates one unified light collection. The light tree keeps reading
`Light::power()`/`orientationCone()`/`bounds()` (pkg86 composability — now the
mesh emitters expose these natively instead of via a synthesized shim). Update the
five integrator NEE call sites pkg89 Phase A already touched
(`multiwavelength_path_tracer`, `spectral_path_tracer`, `restir_di`, `neural_cache`,
`caustic`/`sms_caustic` — pkg89 spec Q7, `pkg89-dedicated-lights.md:190-204`) so they
consume the unified `LightSample`. Preserve the ReSTIR RGB `emission` field contract
(pkg89 Q6).

### E. GPU mirror

Mirror the mesh-emitter into the GPU dedicated-light tagged union established by
pkg89 GAP-1 (`GDedicatedLight` POD + device `sampleLi`, PR #489). The unified CPU
`sampleLi` is the oracle; assert GPU==CPU parity on a mixed dedicated + emissive-mesh
scene (the pkg89 GAP-1 parity harness already measures AREA/POINT ratios — extend it
with a mesh emitter). Follow the pkg64 → pkg64-gpu CPU-virtual → GPU-tagged-union
pattern pkg89 cites (`pkg89-dedicated-lights.md:85-87`).

---

## Acceptance criteria

- [ ] Mesh-emitter `Light` (emissive-triangle wrapper) exists, samples by area with
      a cached per-triangle area, and returns a `LightSample` in the **same measure
      and emission-convention as the pkg122-calibrated `AreaLight`** (one pdf, one
      energy contract).
- [ ] `DiffuseLight` / `Emissive` materials are thin shims: NEE samples the wrapping
      `Light`; direct BSDF-hit emission still evaluates through the material.
- [ ] The seven `Hittable` light virtuals (`raytracer.h:762-768`) are retired or
      minimized, with a repo-wide call-site sweep proving no orphaned caller.
- [ ] `LightList::sample`, the light tree, and all five integrator NEE sites consume
      one unified light collection; ReSTIR RGB `emission` contract preserved.
- [ ] GPU mesh-emitter mirrors the CPU `sampleLi`; GPU==CPU parity on a mixed
      dedicated + emissive-mesh scene.
- [ ] **No render regression:** the existing emissive-mesh suite (pkg89 G6,
      `test_emissive_spectral_emits`) and the dedicated-light suite (G1–G5) stay
      green through the unified path; the light-tree variance-reduction gate (pkg86
      G7) holds on a mixed scene.
- [ ] Research/citation note in `.astroray_plan/docs/` recording the Cycles
      `triangle.h` / PBRT-v4 `DiffuseAreaLight` derivations (pinned SHA) and the
      unified-interface design.

---

## Non-goals

- **Not emitter energy calibration.** That is **pkg122**, which must land first;
  pkg126 consumes pkg122's calibrated measure + emission convention and must not
  re-tune energy. If a unified-path energy discrepancy appears, it is a pkg122
  calibration bug to hand back, not a pkg126 re-tune.
- **Not the two-sided MIS change.** pkg120 adds the BSDF-side leg; pkg126 must keep
  the unified `lightPdf` reconstruction consistent with whatever pkg120 landed, but
  does not itself change MIS weighting.
- **Not new light types or new sampling strategies.** Only unifies the existing
  emissive-geometry and dedicated-`Light` paths under one interface.
- **Not removing the emission-on-hit material behavior.** A BSDF ray that hits an
  emissive face still gets its `Le` from the material; only the **NEE sampling** of
  that emitter moves to the `Light` interface.
- **Not GoniometricLight / ProjectionLight / portal lights.** Those remain pkg89
  follow-ups (`pkg89-dedicated-lights.md` Non-goals) independent of unification.
- **Not re-blessing reference images.** If the unified path shifts any reference
  beyond noise, produce an owner-visible list (as pkg122 does); do not re-bless.

---

## Provenance

Filed as **pkg89 Phase C**, deferred from the start of pkg89 as a "separate future
package, unfiled" (`pkg89-dedicated-lights.md:76, 92-95, 105-106`). The unification
target — wrap emissive triangles as `Light`, make `DiffuseLight`/`Emissive`
materials shims, retire the `Hittable` light virtuals — is specified there. The
dependency on pkg122 is grounded in the pkg89 GAP-2 energy audit
(`.astroray_plan/docs/pkg89-energy-audit-2026-07.md`), which found the dedicated and
geometry `diffuse_light` emitters share the disputed `RGBIlluminantSpectrum`
convention that pkg122 adjudicates: the energy/convention contract must be frozen
before the two sampling paths are merged into one.

---

## Progress

- [ ] A — mesh-emitter `Light` (emissive-triangle wrapper), cached area, pkg122 measure.
- [ ] B — `DiffuseLight` / `Emissive` materials as thin shims registering the wrapper.
- [ ] C — retire/minimize the seven `Hittable` light virtuals; call-site sweep.
- [ ] D — unify `LightList::sample` + light tree + five integrator NEE sites.
- [ ] E — GPU mesh-emitter mirror; GPU==CPU parity on a mixed scene.

---

## Lessons

*(Fill in after the package is done.)*

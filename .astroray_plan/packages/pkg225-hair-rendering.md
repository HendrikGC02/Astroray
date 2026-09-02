# pkg225 — Hair and Fur Rendering

**Pillar:** 3
**Track:** A
**Status:** open — **Stage 1 (CPU curve geometry) + Stage 2 (CPU Principled
Hair BSDF, Chiang 2016) LANDED.** Stage 2 (2026-09-03): `include/astroray/
hair_bsdf.h` (Mp/Np/Ap/logistic/Fresnel + σ_a helpers, header-only STL-free hot
path for GPU reuse) + `plugins/materials/principled_hair.cpp` (R/TT/TRT+residual,
three σ_a parametrizations, view-dependent tangent frame from `uvTangent`,
h=2·hair_v−1, coat→R-roughness, pbrt cuticle-tilt), CPU eval/pdf/sample +
evalSpectral + overridden sampleSpectral. Gate `tests/test_pkg225_hair_bsdf.py`
9/9: energy conservation ρ≤1 across β_m∈{0.1,0.3,0.6,1.0}, absorption-darkens,
per-channel colour response, eval finite/≥0, non-curve regression guard, and a
spectral-path render smoke. Stages 3–6 (GPU, spectral melanin, addon) remain
open. Stage-1 landed via PR #670,
2026-09-02. The pbrt-v3-ported `CurveSegment`/`CurveStrip` (`include/astroray/
curves.h`), `add_curves_bulk` ingest, and the analytic parity gate
(`tests/test_pkg225_curve_intersect.py`, 7/7) are merged. The 2026-08-31 "4/7,
bug localized to curves.h" handoff was wrong on the mechanism — a standalone
native harness proved the intersection math correct; the failures were
test-harness bugs (degenerate camera up-vector, broken oblique geometry, a
normal check that ignored `setFaceNormal`'s sign convention) plus an unfilled
position AOV. See `.astroray_plan/docs/pkg225-curve-intersect-research.md`
"ROOT CAUSE — CORRECTED". Stages 2–6 (hair BSDF, GPU leg, spectral melanin)
remain open.
**Estimated effort:** 6–8 sessions (~18–24 h), staged
**Depends on:** pkg55 (wavefront SoA), pkg36 (closure graph — GPU BSDF lowering)

---

## Goal

Before: Astroray has zero hair/curve support. Blender hair objects are either
silently skipped or auto-meshed into a coarse polygon soup with no
hair-specific shading. The `Principled Hair BSDF` and `Hair BSDF` nodes
are DROPPED-SILENT in the coverage matrix. Fur-bearing characters and
creatures — a staple of production rendering — cannot be rendered.

After: Astroray renders Blender `Curves` objects (and legacy particle-system
hair) as native curve primitives on both CPU and GPU, shaded with a
physically-based hair BSDF (Chiang 2016 / d'Eon 2011). The spectral
pipeline exploits per-wavelength melanin absorption for ground-truth hair
colour that RGB renderers approximate. The addon exports hair from Blender's
geometry-nodes hair system and surfaces all Cycles hair settings through
native panels.

---

## Context

Hair rendering is the single largest missing geometry class. Every Blender
scene with characters, animals, or vegetation that uses particle hair or
geometry-nodes curves currently produces either missing geometry or a
polygon-soup fallback with wrong shading. The round-8 strategy pass rated
it "Medium-High for studio workflows" and estimated ~6 weeks.

The owner's directive (2026-08-29): "I don't see any point in half-assing
it — a proper implementation of it all needs to be done." Features should
be built future-aware: astrophysical dust filaments and nebular structure
(Pillar 4) will reuse the same curve-primitive infrastructure.

This package does NOT depend on pkg219 (per-texel shader eval) — the Hair
BSDF is a self-contained closure, not a node-graph consumer.

---

## Reference

### Geometry — ray-curve intersection

- **Cycles `kernel/geom/curve_intersect.h`** (Apache-2.0, Blender
  Foundation): ribbon (camera-facing flat strip) and thick (swept-circle
  cross-section) intersection. Astroray's primary reference implementation.
- **Phantom Ray-Hair Intersector** — Reshetov 2017, HPG: analytic
  ray-cylinder test, basis for Cycles' thick-curve path.
- **Embree curve primitives** (Apache-2.0, Intel): flat-ribbon, round,
  normal-oriented; Hermite/B-spline/Catmull-Rom/linear basis.
  Reference-quality but Astroray's CPU path uses its own BVH, so the
  Embree math is a cross-check, not a runtime dependency.
- **OptiX built-in curves** (NVIDIA, proprietary API — used via public
  `optixBuiltinISModuleGet`): hardware-accelerated curve intersection on
  RTX. Cycles uses this on the OptiX backend. Astroray currently has no
  OptiX geometry — evaluate feasibility vs. a custom CUDA intersector in
  Stage 3's design session.

### BSDF — hair scattering

- **d'Eon, Francois, Lacewell 2011** — "An Energy-Conserving Hair
  Reflectance Model": the foundational dielectric-cylinder longitudinal /
  azimuthal decomposition (R, TT, TRT lobes).
- **Chiang et al. 2016** — "A Practical and Controllable Hair and Fur
  Model" (Disney/Weta): the artist-friendly parameterisation
  (roughness, melanin/colour, coat, offset) that Cycles' `Principled Hair
  BSDF` implements. The target model for this package.
- **Huang et al. 2022** — "A Practical Near-Field Hair Scattering Model":
  near-field R/TT/TRT/TRRT with azimuthal roughness, adopted by Cycles
  2025+. Implement if Cycles' current `bsdf_hair_principled.h` uses it;
  otherwise file as a follow-up.
- **Cycles `closure/bsdf_hair_principled.h`** (Apache-2.0): reference
  eval/sample/pdf for the Principled Hair BSDF. Astroray should match
  Cycles' parameterisation so the addon can use Blender's native sockets
  with no remapping.
- **Cycles `closure/bsdf_hair.h`** (Apache-2.0): the simpler
  Kajiya-Kay-based Hair BSDF (the `ShaderNodeBsdfHair` node). Lower
  priority than Principled Hair but required for coverage-matrix
  completeness.

### Spectral — melanin absorption

- **Eumelanin/pheomelanin absorption cross-sections**: Alaluf et al. 2002
  ("Ethnic Variation in Melanin Content and Composition in Photoexposed
  and Photoprotected Sites"); Jacques 2013 ("Optical properties of
  biological tissues: a review", Phys. Med. Biol.). Standard biophysics
  data.
- Astroray's hero-wavelength 4λ pipeline can evaluate melanin absorption
  per-wavelength natively, producing ground-truth spectral hair colour
  without the RGB-space melanin mapping Cycles uses. This is the package's
  spectral-advantage deliverable.

---

## Prerequisites

- [ ] Build passes on main.
- [ ] pkg55 (wavefront SoA) is complete (curve intersection must wire into
      the wavefront intersect stage).
- [ ] The plugin/shape registry (`ShapeRegistry` in `register.h`) is
      operational — curves register as a new `Hittable`-derived type.

---

## Specification

### Stage 1 — CPU curve geometry primitive

**Goal:** A `CurveSegment` (or `Curve`) shape plugin that ray-traces cubic
Catmull-Rom curve segments with swept-circle cross-section (thick mode) on
the CPU path tracer. Ribbon mode is a stretch goal for Stage 1 but
required by Stage 3.

**Files to create:**

| File | Purpose |
|---|---|
| `plugins/shapes/curve_segment.cpp` | `CurveSegment : Hittable` — ray-thick-curve intersection (Reshetov 2017 / Cycles `curve_intersect.h`). One segment = 4 control points + per-endpoint radius. Returns `HitRecord` with parametric `u` along curve and `v` around azimuth. |
| `include/astroray/curves.h` | `CurveStrip` helper: a sequence of control points defining one strand, plus `buildCurveSegments()` that emits `CurveSegment` objects into a BVH. Catmull-Rom basis (Blender's default). |
| `tests/test_pkg225_curve_intersect.py` | Ray-curve intersection correctness: straight cylinder (known analytic solution), curved strand, miss, tangent-grazing, endcap. |

**Files to modify:**

| File | What changes |
|---|---|
| `include/astroray/shapes.h` | Forward-declare `CurveSegment`; add to the shape list comment block. |
| `include/astroray/register.h` | Register `"curve_segment"` in `ShapeRegistry`. |
| `include/raytracer.h` | `add_curves(...)` bulk API for the Python binding — accepts flat arrays of control-point positions and radii (mirrors `add_triangles_bulk` pattern). |
| `bindings.cpp` (or equivalent) | Expose `add_curves` to Python. |

**Key design decisions:**

- **Basis:** Catmull-Rom cubic (Blender's `Curves` data-block default).
  The segment takes 4 control points; boundary handling (phantom points
  at strand endpoints) follows Cycles' convention.
- **Cross-section:** swept circle (radius interpolated linearly along
  the segment). Provides physically correct self-shadowing and silhouette.
- **BVH integration:** curve segments are `Hittable` objects, added to the
  existing `BVHAccel` the same way triangles are. Each segment has its own
  AABB (tight, oriented along the curve hull + radius). For dense hair
  (100k+ strands × 4+ segments each), this is the performance-critical
  path — profile and consider a two-level strand-then-segment BVH if the
  flat BVH is too slow. This is an implementation-time decision, not a
  spec-time one.
- **HitRecord extensions:** `u` (parametric position along the strand,
  0→1) and `v` (azimuthal angle around the cross-section) are needed by
  the hair BSDF for cuticle tilt and tangent computation. Store these in
  `HitRecord` — add `float hair_u, hair_v` fields if they don't fit
  existing members. The tangent vector (∂p/∂u) is computed from the curve
  derivative at the hit point.

### Stage 2 — Principled Hair BSDF (CPU)

**Goal:** A `principled_hair` material plugin that implements the Chiang
2016 hair scattering model on the CPU, matching Cycles' `Principled Hair
BSDF` node's parameterisation.

**Files to create:**

| File | Purpose |
|---|---|
| `plugins/materials/principled_hair.cpp` | `PrincipledHair : Material` — eval/sample/pdf for the R (reflection), TT (transmission), TRT (internal reflection) lobes. Inputs: Color or Melanin (eumelanin + pheomelanin concentrations), Roughness (longitudinal + azimuthal), IOR (default 1.55), Offset (cuticle tilt), Coat, Random (per-strand colour variation). |
| `include/astroray/hair_bsdf.h` | Shared math: Gaussian detector `Mp` (longitudinal), `Np` (azimuthal), absorption `sigma_a` from melanin or direct colour, Fresnel for dielectric cylinder geometry. Cited from d'Eon 2011 / Chiang 2016. |
| `tests/test_pkg225_hair_bsdf.py` | White-furnace energy conservation (≤1.0 for all roughness/IOR combos), reciprocity, chi²-plausible sample/pdf consistency, melanin→colour mapping cross-check vs published data. |

**Files to modify:**

| File | What changes |
|---|---|
| `include/astroray/register.h` | Register `"principled_hair"` in `MaterialRegistry`. |

**Key design decisions:**

- **Lobe decomposition:** R + TT + TRT minimum. TRRT+ (higher-order
  internal reflections) as an optional residual energy term — follow
  Cycles' choice on whether to include it (recent Cycles does).
- **Melanin parameterisation:** two-float (eumelanin, pheomelanin) →
  volumetric absorption σ_a via the Beer-Lambert law through the fibre
  cross-section. The "Color" input mode bypasses melanin and sets σ_a
  directly from a user-chosen colour (Cycles' `CLOSURE_BSDF_HAIR_PRINCIPLED_ID`
  with `parametrization == NODE_PRINCIPLED_HAIR_REFLECTANCE`). Both modes
  must work.
- **Tangent frame:** the hair BSDF expects a local frame built from the
  curve tangent (∂p/∂u from Stage 1), not the surface normal. The material's
  `scatter()` / `eval()` must receive the tangent — either via `HitRecord`
  directly or via a tangent passed alongside the normal. Follow the pattern
  that requires the least disruption to the existing `Material` interface.
- **Spectral readiness:** Stage 2 operates in RGB (σ_a computed from RGB
  colour). Stage 5 replaces the RGB σ_a with per-wavelength melanin
  absorption. The code structure should make this swap surgical — σ_a
  computation is isolated behind a function boundary, not inlined into the
  lobe math.

### Stage 3 — GPU curve geometry

**Goal:** Curve primitives render on the GPU wavefront path tracer. This is
the register-pressure-sensitive stage.

**Files to create:**

| File | Purpose |
|---|---|
| `include/astroray/gpu_curve_intersect.cuh` | `__device__` ray-curve intersection, matching Stage 1's CPU math. Ribbon mode (camera-facing quad strip — cheaper, lower quality) and thick mode (swept circle). |
| `tests/test_pkg225_gpu_curves.py` | GPU vs CPU curve-intersection parity: per-pixel mean-ratio gate on a multi-strand test scene. |

**Files to modify:**

| File | What changes |
|---|---|
| `include/astroray/gpu_types.h` | `GCurveSegment` struct: 4× `GVec3` control points + 2× `float` radii + `uint32_t materialHash`. Add `GCurveStrand` (start index + segment count) if the GPU BVH needs strand-level nodes. |
| `src/gpu/scene_upload.cu` | Upload curve segments alongside triangles. New device arrays (`d_curveSegments`, `d_curveStrands`). |
| `include/astroray/gpu_scene_upload.h` | Declare the new device arrays + `uploadCurves()` entry point. |
| `src/gpu/wavefront/stage_intersect.cu` (or equivalent) | Add curve intersection to the wavefront intersect stage. **Register probe required** — if the curve intersection branch spills the intersect kernel, isolate with `template<bool HasCurves>`. |

**Key design decisions:**

- **OptiX vs custom CUDA:** evaluate OptiX built-in curves
  (`OPTIX_BUILD_INPUT_TYPE_CURVES`) if Astroray adds an OptiX BVH backend
  (currently it uses a custom CUDA BVH). If OptiX is not viable in the
  current architecture, implement a custom AABB-based BVH traversal with
  the `gpu_curve_intersect.cuh` analytic test inside the leaf. Document the
  decision and revisit if OptiX becomes available.
- **Ribbon vs thick on GPU:** ribbon mode (camera-facing quad) is
  substantially cheaper on GPU (2D intersection, no transcendental math).
  Default to ribbon for viewport; thick for F12. Expose as a setting.
- **BVH structure:** curves enter the same TLAS as triangles (each curve
  segment has an AABB leaf). Two-level (BLAS per strand, TLAS over strands)
  is the perf target for dense hair but is an implementation-time decision
  gated by measured traversal cost.

### Stage 4 — GPU Hair BSDF

**Goal:** Principled Hair BSDF evaluates on the GPU wavefront shade kernel.

**Files to modify:**

| File | What changes |
|---|---|
| `include/astroray/gpu_materials.h` | Add `GMAT_HAIR_PRINCIPLED` to the material type enum. Add `GHairParams` struct (roughness, IOR, offset, melanin_e, melanin_p, colour, coat, random, parametrisation mode). |
| `src/gpu/wavefront/stage_shade_bucketed.cu` | Hair BSDF eval/sample/pdf in the shade kernel. **Register probe required.** If it spills, isolate with `template<bool HasHair>` (follows the `HasPrincipled` D4 pattern from pkg178). |
| `src/gpu/scene_upload.cu` | Upload hair material parameters into the `GMaterial` table. |

**Key design decisions:**

- **Closure-graph lowering:** if pkg36's closure graph is available, lower
  the hair BSDF to closure-graph lobes the same way Disney/Principled
  does. If not, the hair BSDF can be a standalone `GMAT_HAIR_PRINCIPLED`
  branch in the shade kernel — a separate code path, not forced through
  the closure graph.
- **Template isolation:** the `HasHair` axis is mandatory if register
  probing shows ANY spill from adding the hair lobe math. Non-hair scenes
  must pay zero register cost. This is the same discipline as
  `HasPrincipled` (pkg178 D4).
- **Per-strand random:** the BSDF needs a per-strand random float for
  colour variation. Upload as part of `GCurveSegment` (one extra float per
  segment) — the shade kernel reads it from the hit geometry, not from
  the material table.

### Stage 5 — Spectral melanin absorption

**Goal:** Astroray's spectral pipeline evaluates melanin absorption
per-wavelength, producing ground-truth spectral hair colour that RGB
renderers can only approximate.

**Files to create:**

| File | Purpose |
|---|---|
| `include/astroray/hair_melanin_spectral.h` | `SampledSpectrum melaninAbsorption(float eumelanin, float pheomelanin, const SampledWavelengths& lambda)` — per-wavelength volumetric absorption coefficient from published cross-section data (Jacques 2013 / Alaluf 2002). Cited, with the spectral data table embedded or loaded from a data file. |
| `tests/test_pkg225_spectral_hair.py` | Cross-check: melanin absorption at known wavelengths vs published values. Spectral render of dark/light/red hair vs RGB-mode render — the spectral render should show narrower, more saturated absorption features (qualitative, documented with rendered images). |

**Files to modify:**

| File | What changes |
|---|---|
| `plugins/materials/principled_hair.cpp` | When the renderer is in spectral mode, call `melaninAbsorption()` instead of the RGB→σ_a mapping. The `SampledSpectrum` σ_a feeds directly into the Beer-Lambert absorption inside each lobe — no upsampling round-trip needed. |
| GPU equivalent (Stage 4 files) | Mirror the spectral path on GPU — the `SampledWavelengths` hero-wavelength tuple feeds into the same `melaninAbsorption()` device function. |

**Key design decisions:**

- **No Jakob-Hanika round-trip:** the whole point of spectral melanin is
  to avoid the RGB → JH upsample → per-λ absorption → JH downsample chain
  that loses the spectral structure of melanin. The absorption coefficient
  is computed directly from physical cross-sections at the sampled
  wavelengths.
- **Backward compat:** when the renderer is in RGB mode (non-spectral),
  the Stage 2 RGB σ_a path remains unchanged. The spectral path is an
  upgrade, not a replacement.
- **Data source:** use published molar extinction coefficients for
  eumelanin and pheomelanin. Cite the paper and embed the data as a
  header-level lookup table (the spectral profiles system in
  `data/spectral_profiles/` already has a `hair_dark` entry — integrate
  with that infrastructure if appropriate).

### Stage 6 — Addon integration

**Goal:** Blender users can create hair objects (geometry-nodes curves or
legacy particle hair), assign Principled Hair BSDF materials, adjust all
Cycles-panel settings, and render with Astroray — no manual workarounds.

**Files to modify:**

| File | What changes |
|---|---|
| `blender_addon/__init__.py` | (1) Export path: detect `Curves` data-blocks in `depsgraph.object_instances`, extract control points + radii via `foreach_get`, call `renderer.add_curves(...)`. Handle legacy `ParticleSystem` hair by converting to the curves API (Blender 5.x provides this). (2) Shader translation: handle `ShaderNodeBsdfHairPrincipled` and `ShaderNodeBsdfHair` nodes — map sockets to `principled_hair` / `hair_bsdf` material parameters. (3) Settings: expose Cycles' Curves panel (Shape: ribbon/thick, Subdivisions, Viewport Display) through the native Astroray settings, following the pkg176 panel pattern. |
| `blender_addon/_bulk_geometry.py` | `extract_curves_bulk()` function — batch extraction of curve control points + radii using `foreach_get`, matching the pattern of `extract_triangles_bulk()`. |
| `docs/blender_parity/coverage_matrix.json` | Flip `BSDF_HAIR` and `BSDF_HAIR_PRINCIPLED` entries from `DROPPED-SILENT` to `SUPPORTED`. |

---

## Acceptance criteria

- [ ] **Stage 1:** A single curved hair strand renders correctly on CPU —
      visible silhouette, self-shadow, smooth shading along the curve.
      `test_pkg225_curve_intersect.py` all green.
- [ ] **Stage 2:** A sphere covered in 1000 hair strands renders with
      physically plausible hair shading (R highlight, TT transmission,
      TRT back-lighting). White-furnace energy ≤ 1.0 for all tested
      roughness/IOR. `test_pkg225_hair_bsdf.py` all green.
- [ ] **Stage 3:** GPU curve rendering matches CPU within the Monte-Carlo
      parity convention (per-channel mean-ratio within [0.95, 1.05] at
      64 spp). `cuobjdump` register probe: intersect kernel REG unchanged
      for scenes without curves.
- [ ] **Stage 4:** GPU hair BSDF matches CPU hair rendering within parity
      convention. `cuobjdump` probe: shade kernel REG unchanged for
      non-hair materials (template isolation verified).
- [ ] **Stage 5:** Spectral-mode melanin render of a dark-hair strand
      shows narrower absorption features than the equivalent RGB-mode
      render (documented with side-by-side images). Absorption at 500 nm,
      600 nm, 700 nm matches published eumelanin cross-section data to
      within 10%.
- [ ] **Stage 6:** A Blender scene with geometry-nodes hair + Principled
      Hair BSDF material renders correctly via the addon (headless
      Blender verification). Coverage matrix updated.
- [ ] **Cross-stage:** existing test suite (non-hair scenes) shows zero
      regressions at every stage boundary. Fleet renders byte-identical
      for scenes without curves.

---

## Non-goals

- **Fur grooming tools.** Astroray is a renderer, not a grooming DCC.
  Blender provides the grooming; Astroray renders the result.
- **Grease Pencil curves.** Different data model, different rendering
  intent. Separate package if ever needed.
- **Motion blur on curves.** Deformation motion blur for hair is a
  separate, large scope (temporal BVH rebuild per subframe). File as a
  follow-up package.
- **Volumetric scattering inside hair fibres.** The Chiang 2016 model uses
  an absorption approximation (Beer-Lambert through the fibre
  cross-section), not volumetric path tracing inside the fibre. Full
  volumetric fibre scattering (Zinke & Weber 2007) is a research-grade
  extension, not production scope.
- **Principled Hair v2 / near-field.** Huang 2022 near-field model is a
  follow-up if Cycles adopts it as the default. Stage 2 targets Chiang
  2016, which is Cycles' current shipping model.

---

## Progress

- [ ] Spec filed (this file).
- [ ] Stage 1: CPU curve geometry primitive.
- [ ] Stage 2: Principled Hair BSDF (CPU).
- [ ] Stage 3: GPU curve geometry.
- [ ] Stage 4: GPU Hair BSDF.
- [ ] Stage 5: Spectral melanin absorption.
- [ ] Stage 6: Addon integration.

---

## Lessons

*(Fill in after the package is done.)*

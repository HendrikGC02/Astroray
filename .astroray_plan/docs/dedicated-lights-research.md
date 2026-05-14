# Dedicated Lights — Research Note (pkg89)

**Status:** research draft for pkg89 (dedicated Light objects with spectral
emission and emission direction profiles).
**Author:** dispatched research agent, 2026-05-14.
**Branch:** `docs/pkg89-dedicated-lights-research`.
**Companion spec:** `.astroray_plan/packages/pkg89-dedicated-lights-DRAFT.md`.
**Authority for implementation:** **this document**. The draft spec is a
pointer; this note is the algorithmic and architectural source of truth
(CLAUDE.md §6).

This note is the design artifact for pkg89. It is **not** an implementation
spec. The DRAFT spec next to it lists phases and non-goals; the actual
files-to-create / files-to-modify tables get written when the §10 open
questions are decided.

---

## §1 — Problem statement

### 1.1 Today

Astroray treats lights as **emissive geometry**: a `Hittable` (Sphere,
Triangle, AreaLightShape, SpotLightSphere, DistantLight) carrying a
`Material` whose `isEmissive()` returns true and whose
`emittedSpectral(rec, lambdas)` returns a non-zero `SampledSpectrum`. The
`LightList` collection (`include/raytracer.h:1180-1233`) holds
`std::shared_ptr<Hittable>` pointers and samples them with a
power-weighted CDF (`luminance · area`).

Concretely, the existing dedicated-ish classes are:

| Class | File | Role |
|---|---|---|
| `DistantLight` | `include/raytracer.h:745-827` | Sun-disk angular emitter (cone sampling). |
| `SpotLightSphere` | `include/raytracer.h:829-904` | Sphere-shaped emitter with cone falloff + optional IES. |
| `AreaLightShape` | `include/raytracer.h:906-1036` | Rectangle / disk / ellipse area light with `spread` cone gate. |
| `Sphere` (with IES) | `include/astroray/shapes.h` | Generic sphere; can act as a light when its material is emissive. |
| `Triangle` | `include/astroray/shapes.h` | Mesh triangle; emissive-material triangles act as triangle lights. |
| `IESProfile` | `include/raytracer.h:102` | LM-63-2019 candela-table reader (parses; bilinear-interpolates). |
| `DiffuseLightPlugin` | `plugins/materials/diffuse_light.cpp` | Front-face emissive material. |
| `EmissivePlugin` | `plugins/materials/emissive.cpp` | Two-sided emissive material. |

The Blender addon (`blender_addon/__init__.py:3281-3340`) iterates
depsgraph objects of `type == 'LIGHT'` and routes each one to the
appropriate `add_*_light` binding:

- `'SUN'` → `addSunLight` → `DistantLight`.
- `'AREA'` → `addAreaLight` → `AreaLightShape`.
- `'SPOT'` → `addSpotLight` → `SpotLightSphere` (with IES path).
- `'POINT'` → **`add_sphere(radius=0.1)`** — *not* a dedicated PointLight;
  faked as a tiny emissive sphere. This is the loudest concrete gap.

### 1.2 What's broken

- **No first-class Light interface.** Every "light" is a `Hittable` with
  an emissive `Material` stapled to it. Light sampling concerns
  (`pdfValue`, `random`, `directionFalloff`, `emittedRadiance`) sit on
  the `Hittable` base class — every non-emissive `Sphere` or `Triangle`
  carries no-op overrides of these. Mixing.
- **No isotropic point light.** Blender POINT lights become 0.1 m
  emissive spheres. Wrong falloff, wrong PDF, wrong area scaling,
  shadow penumbra is sphere-geometry-dependent.
- **Spectral emission is per-`Material`, not per-Light.** A scene
  cannot have two area-light *fixtures* (different blackbody
  temperatures) sharing the same emissive `Material` — each fixture
  needs its own `Material` instance. The Blender addon sidesteps this
  with `create_material('light', list(light.color), {'intensity': ...})`
  per Blender Light object, which works but is the wrong factoring.
- **No first-class emission-direction profile.** `directionFalloff` is
  a `Hittable` virtual that returns 1.0 by default and is overridden
  on `SpotLightSphere` (cone + IES) and `DistantLight` (1/Ω). There is
  no abstraction for "this light has a candela distribution" decoupled
  from its geometry.
- **Light Tree (pkg86) composability.** pkg86's spec explicitly says
  in its non-goals: *"Do not change the Light / Hittable::isLight
  interface… if the Conty importance metric strictly requires data
  not already computable from boundingBox, emittedRadiance, and
  directionFalloff, surface that in the Phase 1 research note for
  re-scoping."* The Conty 2018 importance metric needs **emission
  power, bounding box, and orientation cone (θ_o, θ_e)** per light
  cluster. The orientation cone is a per-Light concept that today
  must be inferred from material + geometry + `directionFalloff`. A
  first-class `Light` with an explicit `orientationCone()` accessor
  is the clean fix. pkg86 acknowledges this re-scope hook; pkg89 is
  that re-scope.
- **No Blender-Cycles parity for light controls.** Cycles exposes
  `cast_shadow`, `use_mis`, `use_caustics`, `max_bounces`, `normalize`
  per-light (`scene/light.h`). Astroray exposes none. The
  emissive-material factoring has no place to put them.
- **Goniometric / projection lights are unreachable.** Both are
  per-direction emission textures; cannot be modeled as
  emissive-material-on-geometry without spawning a textured sphere
  facing the right way.

### 1.3 User-facing impact

| Workflow | Today | After pkg89 |
|---|---|---|
| Blender POINT light | Faked sphere, wrong falloff | Correct isotropic point with optional soft-shadow radius. |
| Blender SUN angle slider | Works (DistantLight) | Works; gains correct spectral handle (blackbody temperature). |
| Blender SPOT cone | Works (SpotLightSphere) | Works; cone profile decoupled from sphere geometry. |
| IES candela on POINT | Unreachable (POINT is faked) | Available. |
| Two area lights at 2700 K and 6500 K sharing one shader | One material per light (clutter) | One Light per light; shader-graph independence. |
| Sun + sky atmospheric coupling | Sun via `DistantLight`, sky via `EnvironmentMap` (pkg14) | Same, but unified under a `Light` interface — pkg86 sees both. |
| Light Tree (pkg86) traversal | Power × `boundingBox.area()` only — no orientation factor | Conty 2018 metric: power × inv-r² × orientation cone. |

---

## §2 — Existing-architecture audit (Astroray)

### 2.1 `LightList::sample` signature

```cpp
// include/raytracer.h:472
struct LightSample { Vec3 position, normal, emission; float pdf, distance; };

// include/raytracer.h:1180
class LightList {
    std::vector<std::shared_ptr<Hittable>> lights;
    std::vector<float> powerDist;        // running CDF (sum of luminance·area)
    float totalPower = 0;
public:
    void add(std::shared_ptr<Hittable> l);                  // power-weighted insert
    LightSample sample(const Vec3& pt, std::mt19937& gen) const;
    float pdfValue(const Vec3& pt, const Vec3& dir) const;  // MIS — sums over all lights
    bool empty() const;
    // pkg86 accessors:
    const std::vector<std::shared_ptr<Hittable>>& getLights() const;
    const std::vector<float>& getPowerDist() const;
    float getTotalPower() const;
};
```

The `sample` body (lines 1196-1215) does five things:

1. Sample a light index `idx` from the power CDF.
2. `lights[idx]->random(pt, gen)` — draw a direction toward the light
   from the shading point `pt`.
3. Re-cast as a `Ray(pt, dir)` and `lights[idx]->hit(...)` to recover
   the point/normal — this is the "intersect own primitive to get a
   surface sample" pattern, *not* an explicit `sampleSurface` call.
4. Build the emission: `lights[idx]->emittedRadiance(lightNormal,
   toPoint) * lights[idx]->directionFalloff(toPoint)`.
5. PDF: `lights[idx]->pdfValue(pt, dir) * selPdf`.

This is the chokepoint. Five integrators
(`multiwavelength_path_tracer`, `spectral_path_tracer`, `restir_di`,
`neural_cache`, `caustic_path_tracer` / `sms_caustic_path_tracer`) call
it identically.

### 2.2 NEE consumers

The integrators consume the `LightSample` like this (sample, from
`raytracer.h:2128-2160`):

```cpp
astroray::SampledSpectrum Le_spec = rec.material->emittedSpectral(rec, lambdas);
if (!Le_spec.isZero()) { ... }                       // hit-emission branch
// NEE branch:
LightSample ls = lights.sample(rec.point, gen);
Vec3 wi = (ls.position - rec.point).normalized();
// occlusion test:
bool occluded = hitOccluder && !(shadow.hitObject && shadow.hitObject->isInfiniteLight());
// MIS-weighted contribution:
SampledSpectrum f = mat->evalSpectral(rec, wo, wi, lambdas);
contribution += throughput * f * Le_emission / ls.pdf;
```

Note: `Le_emission` comes from the `emission` field on `LightSample`,
which `LightList::sample` builds as **RGB Vec3** (line 1209). The
integrators then either upsample via `RGBIlluminantSpectrum` (ReSTIR
candidate; `include/astroray/restir/light_sample.h:54-60`) or use it
RGB-only. **This is a parity bug that has been quietly tolerated:** the
emissive-material path produces a `SampledSpectrum` via
`emittedSpectral`, but the `LightList::sample` path collapses to RGB
emission and re-upsamples downstream. pkg89 fixes this by carrying
`SampledSpectrum` through `LightSample` (see §4.3).

### 2.3 `Hittable` light-related virtuals

```cpp
// include/raytracer.h:710-716
virtual float pdfValue(const Vec3& origin, const Vec3& direction) const { return 0; }
virtual Vec3  random(const Vec3& origin, std::mt19937& gen) const { return Vec3(0,1,0); }
virtual bool  isLight() const { return false; }
virtual bool  isInfiniteLight() const { return false; }
virtual Vec3  emittedRadiance() const { return Vec3(0); }
virtual float directionFalloff(const Vec3& dirFromLight) const { return 1.0f; }
virtual Vec3  emittedRadiance(const Vec3& lightNormal, const Vec3& toPointDir) const { return emittedRadiance(); }
```

Seven virtuals on every `Hittable` exist solely to support the
"emissive geometry is a light" pattern. Non-emissive primitives carry
no-op overrides. pkg89 does not delete these — they stay for the
emissive-mesh path (DiffuseLight on Triangle) — but new dedicated
Light types do **not** inherit from `Hittable`.

### 2.4 Spectrum machinery (already present)

- `astroray::SampledWavelengths` / `SampledSpectrum` —
  `include/astroray/spectrum.h:98, 142` (PBRT-shaped, 4 hero
  wavelengths, float).
- `astroray::RGBIlluminantSpectrum` — line 229. Jakob-Hanika upsample
  driven LUT for illuminants (separate from albedo LUT; pkg54c).
- Planck blackbody — `include/astroray/spectral.h:15`:
  ```cpp
  inline ASTRORAY_NOINLINE double planck(double wavelength_nm,
                                         double temperature_K);
  ```
  Returns spectral radiance in `W/(m²·sr·m)`. **Already there.**
- `SpectralProfile` — `include/astroray/spectral_profile.h:17` — owns
  a 5-nm-grid float table loaded from `profiles.bin` (pkg38).
  Read-only after construction. Method:
  `float reflectance(float lambda_nm) const`. Note: the name says
  "reflectance" because the database stores reflectance curves; for
  emission we'd add a sibling `emission(lambda_nm)` accessor that
  forwards to the same lookup (the curve shape is the SPD shape; the
  caller scales by intensity). See §10 Q5.
- `SpectralProfileDatabase` — singleton at line 43, looked up by
  name.

These four primitives compose **without any extension** into the four
spectral emission modes pkg89 needs (§4).

### 2.5 ReSTIR contract

`ReSTIRCandidate` (`include/astroray/restir/light_sample.h:33`) wraps
`LightSample` field-for-field. Any change to `LightSample` propagates
here.

**Constraint for pkg89:** `LightSample`'s shape must continue to be
zero-cost-convertible to `ReSTIRCandidate`. Adding a
`SampledSpectrum emission_spec` field next to the existing RGB
`emission` is acceptable; replacing `emission` outright breaks ReSTIR.
See §6.2.

---

## §3 — Light types in scope for v1

Cycles' types: POINT, SPOT, AREA, DISTANT (sun), BACKGROUND, TRIANGLE.
PBRT-v4's types: PointLight, SpotLight, DistantLight, DiffuseAreaLight,
ProjectionLight, GoniometricLight, UniformInfiniteLight,
ImageInfiniteLight, PortalImageInfiniteLight.

### 3.1 Recommended v1 set (parity with Blender's four native types + env)

| Class | Direction profile | Spectral default | Replaces |
|---|---|---|---|
| `PointLight` | Isotropic (4π); soft-shadow radius optional | Blackbody(T) or RGB | "POINT routed to sphere(0.1)" hack |
| `SpotLight` | Cone (inner+outer angles); optional IES | Blackbody(T) or RGB | `SpotLightSphere` |
| `DistantLight` | Cone (angular diameter); 1/Ω | Blackbody(T)=5778K or RGB | `DistantLight` (renamed/moved) |
| `AreaLight` | Lambertian over rect/disk/ellipse; optional `spread` cone | Blackbody(T) or RGB | `AreaLightShape` |
| `BackgroundLight` | Environment map (already in EnvironmentMap class) | Per-pixel RGB → upsample | `EnvironmentMap` wrapped |

**Out of scope for v1:**

- `GoniometricLight` (per-direction emission texture, lat-long, on a
  point) — niche; defer to pkg89 follow-up.
- `ProjectionLight` (spot light with a slide image) — niche; defer.
- `PortalImageInfiniteLight` (importance-sampled HDRI portals) — out
  of scope; already approximated by pkg14 envmap importance sampling.

### 3.2 Mesh-emitter coexistence

`DiffuseLightPlugin` and `EmissivePlugin` materials **stay**. An
emissive `Triangle` continues to act as a light through the
`LightList` insertion path that already exists (line 1185). The two
worlds compose:

- A Blender artist who assigns an emission shader to a mesh face: still
  works via the material path. The renderer treats the triangle as an
  emissive primitive in BVH traversal and adds it to `LightList` for
  NEE.
- A Blender artist who places a Blender POINT/SPOT/SUN/AREA light:
  routed to the new dedicated Light types.

Phase C (long-horizon, out of scope for pkg89) would wrap emissive
triangles into a `TriangleAreaLight` at scene-upload time and unify
the codepath. **Do not** attempt that in pkg89 — it widens the diff
and risks regressing the existing emissive-mesh tests.

---

## §4 — Spectral emission interface

### 4.1 Proposed API

```cpp
// include/astroray/light.h  (NEW)

namespace astroray {

// First-class light interface. Decoupled from Hittable. Implementations
// own their geometry sampling, direction profile, and spectral emission.
class Light {
public:
    enum class Type {
        Point, Spot, Distant, Area, Background
        // (Goniometric, Projection — pkg89 follow-up)
    };

    virtual ~Light() = default;

    // --- Identity / categorization ---
    virtual Type type() const = 0;
    virtual bool isDelta() const = 0;             // point / distant: yes; area / spot / bg: no
    virtual bool isInfinite() const = 0;          // distant / background: yes

    // --- Sampling (parallel to LightList::sample's existing contract) ---
    // Sample a direction toward this light from a shading point. Returns
    // emission as a SampledSpectrum (fixes the RGB-collapse audit in §2.2).
    virtual LightSample sampleLi(const Vec3& shadingPoint,
                                 const Vec3& shadingNormal,
                                 const SampledWavelengths& lambdas,
                                 std::mt19937& gen) const = 0;

    virtual float pdfLi(const Vec3& shadingPoint,
                        const Vec3& shadingNormal,
                        const Vec3& wi) const = 0;

    // --- Power (for pkg86 light tree node energy) ---
    virtual float power(const SampledWavelengths& lambdas) const = 0;

    // --- Orientation cone (for pkg86 Conty 2018 metric) ---
    // Returns (axis, cos(theta_o), cos(theta_e)). For isotropic lights
    // (point with no IES), returns full-sphere cone. For Distant /
    // Area, returns the emission direction and the half-angle.
    struct OrientationCone { Vec3 axis; float cosThetaO; float cosThetaE; };
    virtual OrientationCone orientationCone() const = 0;

    // --- Bounds (for pkg86 BVH build over lights) ---
    virtual AABB bounds() const = 0;

    // --- Cycles-parity per-light controls ---
    bool castShadow = true;       // Cycles `cast_shadow`
    bool useMIS = true;           // Cycles `use_mis`
    bool useCaustics = false;     // Cycles `use_caustics`
    int  maxBounces = 1024;       // Cycles `max_bounces`
    bool normalize = true;        // Cycles `normalize` — radiometric vs photometric scaling
};

} // namespace astroray
```

### 4.2 Spectral-emission backing

The four modes a `Light`'s emission can be backed by — composable, all
already present in the codebase:

| Mode | Backing type | Construction |
|---|---|---|
| Blackbody | `temperature_K: float` | `planck(λ, T)` evaluated per hero wavelength in `sampleLi` |
| Measured SPD | `const SpectralProfile* spd` + `intensity` | `spd->reflectance(λ) * intensity` (rename `emission(λ)` per §10 Q5) |
| RGB upsample | `RGBIlluminantSpectrum` | `RGBIlluminantSpectrum(rgb).sample(lambdas)` |
| Composite (gel) | `(SPD or RGB or BB) × transmission(λ)` | Multiplicative in `sampleLi` |

The cleanest factoring is to give every `Light` a single member:

```cpp
class EmissionSpectrum {
public:
    enum class Kind { Blackbody, ProfileSPD, RGB, Composite };
    SampledSpectrum eval(const SampledWavelengths& lambdas) const;
    // construction:
    static EmissionSpectrum fromBlackbody(float T, float intensity);
    static EmissionSpectrum fromProfile(const SpectralProfile* p, float intensity);
    static EmissionSpectrum fromRGB(const Vec3& rgb);
    EmissionSpectrum composeWith(const EmissionSpectrum& transmission) const;
};
```

This is a thin shell over the existing primitives — no new spectral
machinery.

### 4.3 The `LightSample` carry-spectrum extension

```cpp
// CURRENT (raytracer.h:472):
struct LightSample { Vec3 position, normal, emission; float pdf, distance; };

// PROPOSED:
struct LightSample {
    Vec3 position, normal;
    Vec3 emission;                          // RGB; kept for legacy + ReSTIR target weight
    astroray::SampledSpectrum emission_spec;// NEW; the true emission used by spectral integrators
    float pdf, distance;
};
```

ReSTIR uses `emission` (RGB) for `targetLuminanceRGB()`
(`include/astroray/restir/light_sample.h:66`). Spectral integrators
use `emission_spec`. The two are kept consistent in `Light::sampleLi`
by computing `emission_spec` first and deriving `emission` via
`emission_spec.toXYZ(lambdas)` → `XYZtoRGB`. Memory cost:
4-float `SampledSpectrum` × 1 = 16 bytes per `LightSample`; negligible.

---

## §5 — Emission direction profiles (per-type details)

### 5.1 `PointLight` (isotropic)

- **Sampling.** Given shading point `pt`, draw direction toward the
  light center `c`. If `radius == 0`: PDF is a δ in solid angle —
  `isDelta() = true`, NEE returns the exact direction with `pdf = 1`
  in the "we picked this delta light" sense; MIS treats it like
  Cycles does (skip BSDF-side MIS weighting). If `radius > 0`:
  visible-sphere-cap cone sampling (Cycles `point_light_sample`,
  spherical variant), PDF in solid angle measure.
- **Cycles reference.** `intern/cycles/kernel/light/point.h` —
  `point_light_sample`, `point_light_eval_from_intersection`. Uses
  `M_1_2PI_F / sin_sqr_to_one_minus_cos(r²/d²)` for the sphere-cap
  PDF.
- **PBRT reference.** `PointLight::SampleLi` —
  `LightType::DeltaPosition`, returns
  `LightLiSample{ I/(p-ctx.p).LengthSquared(), wi, 1, pLight }`.
- **Orientation cone.** Full sphere (`cosThetaO = -1, cosThetaE = 1`).
- **Per-`PointLight` fields.** `Vec3 position; float radius;
  EmissionSpectrum emission;` and optional `IESProfile* ies` (which
  shifts the light from isotropic to direction-dependent — that's the
  Cycles "POINT with IES" case).

### 5.2 `SpotLight` (cone + IES)

- **Cone falloff.** Two angles: `outerAngle` (hard cut) and
  `innerAngle` (full intensity). Cycles smoothstep
  (`spot_light_attenuation`):
  ```
  attenuation = smoothstep((ray.z - cos_half_spot_angle) * spot_smooth)
  ```
  Astroray's `SpotLightSphere::directionFalloff` already does the
  Cycles convention correctly (`include/raytracer.h:896-903`). Port
  verbatim.
- **IES multiplicative.** `attenuation × ies.sample(axis, dir)`.
- **Sampling.** Same as `PointLight` (sample the sphere cap or treat
  as δ if `radius == 0`); attenuation applied to emission. The PDF
  itself does **not** include attenuation — the attenuation modulates
  the emission, not the sampling density. (Cycles convention.)
- **Orientation cone.** `axis = spot direction`, `cosThetaO = cos(0)
  = 1` (axis is the only emitting direction's normal cluster),
  `cosThetaE = cos(outerAngle)`.
- **Per-`SpotLight` fields.** Inherit `PointLight`'s; add `Vec3 axis;
  float outerAngle, innerAngle; IESProfile* ies = nullptr;`.

### 5.3 `DistantLight` (sun-disk)

- **Sampling.** Uniform cone of half-angle `θ_max =
  angularDiameter/2` around `axis`. Astroray's existing
  `DistantLight::random` (`include/raytracer.h:800-809`) is correct.
- **PDF in solid angle:** `1 / (2π(1 − cosθ_max))`. Same line 796.
- **Direction falloff.** None *per se*; the existing `directionFalloff`
  override divides by solid angle so emission stays constant as disk
  size shrinks (line 822-826). Migrate to a `directionPdfScale`
  inside `sampleLi` rather than a separate virtual.
- **Orientation cone.** `axis = -toLightDir`, `cosThetaO = 1`,
  `cosThetaE = cos(θ_max)`.
- **Per-`DistantLight` fields.** `Vec3 axis; float angularDiameter;
  EmissionSpectrum emission;` — usually `Blackbody(5778)` for "sun".
- **Spectral note.** Real-sun rendering inside Astroray uses Pillar 4
  GR. The DistantLight on the addon side is the practical Blender
  Sun light, not the physical-stellar-photosphere one. **Do not
  conflate** — pkg89 ships the photometric DistantLight only.

### 5.4 `AreaLight`

- **Shape variants.** Rectangle (`size_x × size_y`), Disk
  (`radius`), Ellipse (`size_x × size_y`). Triangle is handled as
  emissive geometry, not as an `AreaLight`.
- **Sampling.** Uniform-area on the light surface (Cycles
  `area_light_sample`, Astroray's existing
  `AreaLightShape::random` + `samplePoint`).
- **PDF (solid angle).** `d² / (|cos(θ)| · A)` —
  `AreaLightShape::pdfValue` line 1009-1013 is right.
- **`spread` cone (Cycles parity).** Multiplicative emission gate:
  the light only emits within a cone of half-angle `spread · π/2`
  around the surface normal. Astroray already implements this in
  `AreaLightShape::emittedRadiance(lightNormal, toPointDir)` line
  1025-1035.
- **Cycles `area_light_spread_clamp_light`** is a smarter version
  that **shrinks the sampling distribution** to the visibility-cone
  intersection, improving variance. **Out of scope for pkg89 v1.**
  Surface as `pkg89-spread-tightening` follow-up; the unclamped
  emission-side gate matches existing Astroray behavior.
- **Orientation cone.** `axis = normal`, `cosThetaO = 1`,
  `cosThetaE = cos(spread · π/2)`.
- **Per-`AreaLight` fields.** `Vec3 center, axisU, axisV; float
  halfU, halfV; Shape shape; float spread; EmissionSpectrum emission;`.

### 5.5 `BackgroundLight`

- Wraps `EnvironmentMap` (`include/raytracer.h:1235+`). Mostly a
  rename + interface implementation; **no new sampling math.**
- The marginal-CDF importance sampling already done by
  `EnvironmentMap` becomes `BackgroundLight::sampleLi`. The
  pre-computed total power feeds `power()`. `orientationCone()`
  returns full-sphere; `bounds()` returns world-AABB sentinel.

---

## §6 — Integration with existing systems

### 6.1 `LightList` polymorphism

Two viable designs:

**Option A — `std::vector<std::unique_ptr<Light>>`.** Virtual dispatch.
PBRT-v4 style. Pros: extensible, clean. Cons: heap allocation per
light, no GPU friendliness (but pkg89 is CPU-only; GPU is pkg89-GPU
follow-up).

**Option B — tagged union `std::variant<PointLight, SpotLight, ...>`.**
Cycles style (KernelLight is a tagged C struct). Pros: no heap, GPU
mirror straightforward. Cons: closed type set, switch-dispatch.

**Recommended:** **Option A for CPU** (pkg89 main); **Option B for
GPU** (pkg89-GPU follow-up — mirror Cycles' `KernelLight` exactly).
Two reps, conversion at scene-upload time. Same as pkg86's pattern
(CPU tree + GPU mirror).

### 6.2 Interplay with `Hittable` lights

`LightList` extended:

```cpp
class LightList {
    std::vector<std::shared_ptr<Hittable>> emissiveGeometry;  // existing
    std::vector<std::unique_ptr<Light>>    dedicatedLights;   // NEW
    // unified power CDF over both
    std::vector<float> powerDist;
    float totalPower = 0;
public:
    void addEmissiveGeometry(std::shared_ptr<Hittable> l);    // existing add()
    void addLight(std::unique_ptr<Light> l);                  // NEW
    LightSample sample(const Vec3& pt, const Vec3& n,
                       const SampledWavelengths& lambdas,
                       std::mt19937& gen) const;              // signature widened
    // accessors for pkg86 (light tree consumes both):
    size_t numLights() const;
    std::variant<const Hittable*, const Light*> lightAt(size_t i) const;
};
```

**Signature change.** `sample(pt, gen)` → `sample(pt, n, lambdas, gen)`.
Five integrators call sites get updated; mechanical. The shading
normal `n` and `lambdas` enable spectral and cone-aware sampling.

### 6.3 pkg86 (Light Tree) dovetail

pkg86's spec §3 non-goal #2 says: *"if [Conty's metric] does require
new accessors, surface that in the Phase 1 research note for re-scoping
— do not silently widen the interface."* pkg89 **is** that widening.
The flow:

1. pkg86 Phase 1 research note lists the data it needs per cluster:
   energy, AABB, orientation cone (θ_o, θ_e).
2. pkg89 provides `Light::power()`, `Light::bounds()`,
   `Light::orientationCone()` directly. For emissive geometry, the
   `LightList` wraps each `Hittable` in a shim that synthesizes these
   accessors from `boundingBox`, `luminance(emittedRadiance())`, and
   normal/`directionFalloff`. The shim is per-shape-class but small.
3. pkg86's `LightTree::build(const LightList&)` iterates
   `LightList::numLights()` and `lightAt(i)` — the std::variant
   accessor — and treats both kinds uniformly.

**Sequencing.** pkg86 and pkg89 can land in either order:
- **pkg86 first** (current Round 8 plan): pkg86 reads
  `boundingBox`/`emittedRadiance`/`directionFalloff` from Hittables
  only; pkg89 later swaps the underlying type to `Light*` without
  changing pkg86 traversal — the std::variant accessor hides the
  type.
- **pkg89 first**: pkg86 sees the unified interface from day one.

Either way, **the orientation cone must be derivable from existing
data** when pkg86 lands without pkg89. For `AreaLightShape`,
`SpotLightSphere`, `DistantLight` that's trivial (normal, axis +
outerAngle, axis + angular diameter). For generic emissive `Sphere` /
`Triangle`, the cone is "full sphere" — i.e., the orientation factor
collapses to 1 and the importance metric reduces to energy/r²,
which is still better than Astroray's current power-only sampler.

### 6.4 GPU side (out of scope; pkg89-GPU follow-up)

`gpu_types.h` would gain a `GLight` POD that mirrors Cycles'
`KernelLight` (tagged union with the same five types). Scene upload
(`scene_upload.cu`) walks `LightList::dedicatedLights` and produces a
flat array. **pkg89 v1 is CPU-only.** Adding GPU is a deliberate
follow-up.

### 6.5 Blender addon

The addon (`blender_addon/__init__.py:3281-3340`) **already iterates
all four Blender light types**. Migration is one-for-one:

| Today | After pkg89 |
|---|---|
| `add_sphere(position, 0.1, mat_id, …)` for POINT | `add_point_light(position, radius=light.shadow_soft_size, blackbody=…, ies=…)` |
| `add_sun_light(direction, angle, mat_id)` | `add_distant_light(direction, angle, blackbody=…)` |
| `add_area_light(position, axisU, axisV, sx, sy, shape, mat_id, spread)` | `add_area_light(position, axisU, axisV, sx, sy, shape, blackbody=…, spread=…)` |
| `add_spot_light(position, dir, radius, mat_id, spot_size, spot_blend, ies)` | `add_spot_light(position, dir, radius, blackbody=…, outer=spot_size, blend=spot_blend, ies=…)` |

The addon already pulls `light.color` (RGB) and `light.energy` (W).
For pkg89, also try `light.cycles.blackbody` /
`light.color_temperature` if exposed (Blender 5.x adds this on
some light types).

### 6.6 Migration path (the three-phase plan in the DRAFT spec)

- **Phase A (pkg89 itself, 2-3 weeks).** Add `Light` interface +
  five dedicated types alongside existing `DiffuseLight` /
  `EmissivePlugin` materials and `AreaLightShape` / `SpotLightSphere`
  / `DistantLight` classes. Both routes work. `LightList::sample`
  signature widens; integrators get the spectral emission field.
- **Phase B (pkg89-addon, 1 week).** Convert addon to dedicated
  lights for Blender's Point / Spot / Sun / Area types. Emissive
  meshes (artist-authored emission shaders on faces) keep the
  material path.
- **Phase C (pkg89-unify, out of scope).** Wrap emissive triangles
  into `TriangleAreaLight` under the hood; `DiffuseLight` becomes a
  shim. **File as separate package** — too much refactor surface
  for pkg89.

---

## §7 — Validation gates (suggested for the implementation pkg89)

| Gate | What | Pass condition |
|---|---|---|
| **G1** | Render `tests/scenes/dedicated_lights_zoo.py` — one of each type | Visual inspection + SSIM ≥ 0.98 vs reference. |
| **G2** | Blackbody spectral correctness | A `Light` with `EmissionSpectrum::fromBlackbody(6500, 1.0)` produces a render whose mean XYZ matches the D65 illuminant integrated through the same hero-wavelength path within 1 %. |
| **G3** | IES profile correctness | Load a standard IES file (Eulumdat reference or one of the public BEGA / ERCO profiles); render confirms candela distribution matches expected angular intensity within 5 % at 8 sample angles. |
| **G4** | Spot cone falloff | Render a checkerboard plane lit by a `SpotLight` at `outerAngle ∈ {15°, 30°, 60°}`; intensity in the inner-cone region scales as `cos²(θ)/r²`; outside the outer cone, intensity = 0 modulo BSDF MIS noise floor. |
| **G5** | POINT light isotropy regression | The Blender POINT-light export, previously rendering as a 0.1 m sphere, now renders as an isotropic delta light: shadow penumbra goes from sphere-radius-dependent to 0 when `radius=0`. Visual: hard shadows now possible from POINT. |
| **G6** | No regression on `DiffuseLight` mesh emission | Existing emissive-mesh test suite passes unchanged. |
| **G7** | pkg86 composability | A `LightTree` built over a scene mixing dedicated lights and emissive triangles produces a sampling distribution that recovers the current `PowerLightSampler` baseline within 2σ on a single-light scene (sanity) and exhibits ≥2× variance reduction on the `many_lights.py` scene (the pkg86 gate, but now with mixed Light types). |
| **G8** | ReSTIR target-weight stability | `ReSTIRCandidate::targetLuminanceRGB()` on a candidate produced from a `Light::sampleLi` matches `targetLuminance(lambdas)` within 1 % across 1000 samples (consistency of the dual RGB/spectral emission carrying in `LightSample`). |
| **G9** | `LightList::sample` signature break is rg-clean | `rg "lights\.sample\(" -t cpp` shows zero call sites with the old signature after the migration. |

---

## §8 — License fence (CLAUDE.md §6)

| Source | License | Use |
|---|---|---|
| Cycles `intern/cycles/scene/light.h`, `kernel/light/*.h` | Apache-2.0 | Mirror sampling math, cone attenuation formulas, IES integration pattern. Files copied into `external/cycles_lights/` with original headers; `THIRD_PARTY_LICENSES.md` records commit SHA. |
| PBRT-v4 `src/pbrt/lights.{h,cpp}` | Apache-2.0 | Second opinion on interface shape (LightType, SampleLi, SampleLe split). No verbatim copy needed — the design is well-known. Cite the book §12 in code comments. |
| IES LM-63-2019 | Public standard (ANSI/IES publication; format is documented, not licensed software) | Astroray already has an original `IESProfile` parser (`include/raytracer.h:102`). No license issue. |
| Astroray pkg38 spectral profiles (sodium, mercury, LED, etc.) | In-tree | Reuse `SpectralProfile` for measured SPDs (§4.2 mode 2). |
| Planck blackbody formula | Public-domain physics | `astroray::planck` already implemented in `include/astroray/spectral.h:15`. |

**License re-check needed at pkg89 implementation time.** Specifically
on the exact Cycles upstream commit being mirrored — pin the SHA in
`THIRD_PARTY_LICENSES.md`, identical to what pkg86 does for
`light_tree.cpp`.

---

## §9 — References (external, must verify with WebSearch/WebFetch in implementer's Phase 1)

- **Cycles.** `intern/cycles/scene/light.{h,cpp}`,
  `intern/cycles/kernel/light/{point,spot,area,distant,background,triangle}.h`,
  `intern/cycles/scene/light_tree.{h,cpp}`. Apache-2.0. Confirmed
  reachable as of 2026-05-14 from
  `https://github.com/blender/cycles` (the `raw.githubusercontent.com`
  endpoint serves the files; `distant.h` 404'd at fetch time —
  re-locate at implementation time, it may have been moved or
  renamed since the commit being mirrored). The Astroray
  `DistantLight` already implements the canonical uniform-cone math
  (`raytracer.h:789-826`) so the Cycles reference is not
  load-bearing for that one type.
- **PBRT-v4.** `src/pbrt/lights.h`. Apache-2.0. Confirmed reachable
  at `https://raw.githubusercontent.com/mmp/pbrt-v4/master/src/pbrt/lights.h`.
  Full enum / class shape extracted above (§2 of the WebFetch
  return, captured into §4 of this note).
- **Veach & Guibas 1995** — "Optimally Combining Sampling Techniques
  for Monte Carlo Rendering". MIS, foundational. Use for the
  `LightSample::pdf` definition.
- **Conty Estevez & Kulla 2018** — "Importance Sampling of Many
  Lights with Adaptive Tree Splitting", HPG 2018 / ACM CGI 1(2).
  DOI [10.1145/3233305](https://dl.acm.org/doi/10.1145/3233305).
  PDF mirror at
  [HPG 2018 papers](https://www.highperformancegraphics.org/wp-content/uploads/2018/Papers-Session1/HPG2018_ImportanceSamplingManyLights.pdf).
  pkg86 cites this; pkg89's `orientationCone()` accessor exists to
  feed it.
- **ANSI/IES LM-63-2019** — IES Standard File Format. Public
  standard. Astroray's existing parser is sufficient. ANSI Blog
  overview:
  [blog.ansi.org/ansi/standard-file-photometric-data-ies-lm-63-19/](https://blog.ansi.org/ansi/standard-file-photometric-data-ies-lm-63-19/).
- **ANSI/IES TM-30-20** — light source color rendition (for
  blackbody-vs-measured SPD comparisons in G2). Reference only;
  pkg89 doesn't implement TM-30 metrics.
- **CIE 1964 10° Standard Observer / D65** — already in
  `include/astroray/spectrum.h` (`cieCmf1964_10deg`, `sampleD65`).
  Used directly by G2.

---

## §10 — Open design questions (decide before implementing)

Each row must be answered in the real pkg89 spec before code is
written. Recommended answers in parentheses.

| # | Question | Recommendation |
|---|---|---|
| Q1 | Polymorphic `std::vector<std::unique_ptr<Light>>` vs `std::variant<PointLight, ...>` | **unique_ptr** for CPU (PBRT pattern); **variant**/POD for GPU mirror (Cycles pattern), pkg89-GPU follow-up. |
| Q2 | `TriangleAreaLight` area computed at construction (cached) or per-sample | **Cached.** Triangles are immutable post-build. |
| Q3 | IES parse eager (at scene-upload) vs lazy (first use) | **Eager.** Files are <10 KB; one-shot upload latency invisible. Astroray's parser already loads eagerly via `loadFromFile`. |
| Q4 | `BackgroundLight` and `DistantLight` coexist or supersede | **Coexist.** Cycles convention. A scene with both sun + sky is normal. |
| Q5 | `SpectralProfile::reflectance(λ)` vs new `emission(λ)` alias for SPD-mode emission | **Add a thin `emission(λ)` alias that returns the same value.** Name correctness > one extra inline method. Document in `spectral_profile.h` that for emissive use the curve is interpreted as relative SPD shape. |
| Q6 | `LightSample` extends with `SampledSpectrum emission_spec` or replaces `emission` | **Extend.** ReSTIR's RGB target-weight path depends on the existing field. |
| Q7 | `LightList::sample` signature break: widen all five integrators in one PR vs introduce overload and migrate | **One PR.** Five call sites; mechanical. Surgical-change rule (CLAUDE.md §3) holds — every changed line traces to "carry spectral emission and shading normal through NEE". |
| Q8 | Camera DoF interaction with `DistantLight` / `SpotLight` | **Document, don't solve.** Cycles ships a lens-coupled-spot-light path tracer behavior; Astroray defers. Surface as `pkg89-lens-lights` follow-up if requested. |
| Q9 | Motion blur (pkg88) coupling — does `Light` get a `time` parameter? | **Punt to pkg88 if pkg88 lands first (pkg88 will widen the interface); otherwise, `pkg89-motion` follow-up.** No `time` field in pkg89 v1. |
| Q10 | `EmissionSpectrum::Composite` for gel filters: 1st-class type or compose-at-construction | **Compose at construction.** Multiply the SPD by the transmission curve once, store the product. Saves a dispatch per `sampleLi`. |
| Q11 | Cycles per-light `normalize` flag (radiometric vs photometric scaling) | **Implement** — needed for blackbody-temperature lights to render with intuitive intensity. Default `true` matches Cycles. |
| Q12 | `IESProfile` on `PointLight` (Cycles allows IES on POINT) — extend `PointLight` or only on `SpotLight` | **Allow on both** — Cycles convention. Cheap virtual; orientation cone widens to full-sphere when IES is set. |

---

## §11 — Estimated effort

| Phase | Scope | Effort |
|---|---|---|
| **A** | `Light` interface + 5 dedicated types + `LightSample.emission_spec` + 5-integrator NEE update + unit tests for sampling/PDF/orientation cone | **2-3 weeks** (≈ 40-60 h) |
| **B** | Blender addon migration to dedicated bindings; new `add_point_light` / refactor `add_*_light` to take `EmissionSpectrum` (blackbody temperature or RGB) | **1 week** (≈ 15-20 h) |
| **C** | (out of scope for pkg89) `TriangleAreaLight` unification | **separate package** |

**Total pkg89: 3-4 weeks.** Consistent with Cycles' upstream
"introduce KernelLight tagged union and light-type kernels" diff
landing in roughly that calendar window.

**Critical-path risk.** The signature widening of `LightList::sample`
touches all five integrators in one PR (Q7). The risk is
non-spectral integrators (none currently in tree but historically
the multiwavelength path had RGB fallbacks) silently degrading. The
mitigation is G6 + G8 (regression gates) and dispatching pkg89 to a
single-implementer session rather than fan-out.

---

## §12 — Decision summary (one-line per fork)

1. **Light is its own interface**, sibling to `Hittable`. No
   inheritance.
2. **Five v1 types**: Point, Spot, Distant, Area, Background.
   Goniometric / Projection deferred.
3. **Spectral emission** is a small composable `EmissionSpectrum`
   over Blackbody / SPD / RGB / Composite — all backed by existing
   primitives.
4. **`LightSample.emission_spec`** added next to RGB `emission`;
   ReSTIR contract preserved.
5. **`LightList::sample` signature widens** to take shading normal
   and `SampledWavelengths`. Five-integrator PR.
6. **pkg86 dovetails via `Light::orientationCone()` and
   `Light::power()`** — pkg89 supplies what pkg86's non-goal #2
   anticipated needing.
7. **GPU port is pkg89-GPU follow-up.** Mirror Cycles' tagged-union
   `KernelLight`.
8. **Emissive-material codepath stays** (`DiffuseLight` /
   `Emissive` triangles continue working). Unification is Phase C,
   out of scope.

End of research note.

# Renderer Internals

A technical reference for agents working on this codebase. Covers architecture,
the rendering pipeline, material conventions, and the invariants that caused
every major bug to date. Read this before touching `include/raytracer.h`.

---

## Architecture

Everything lives in two header files — there is no separate compilation of the
renderer itself:

```
include/raytracer.h          Core: Vec3, Ray, HitRecord, all materials,
                             BVH, Camera, LightList, Renderer
include/advanced_features.h  DisneyBRDF, CheckerTexture, TexturedLambertian,
                             Transform, SubsurfaceMaterial
apps/main.cpp                Standalone binary; builds Cornell box or material
                             test scene, writes PPM or PNG
module/blender_module.cpp    pybind11 binding; exposes Renderer/Camera/materials
                             as the `astroray` Python module
```

Both targets include the same headers. The Python module is compiled with
`-flto -fPIC -fvisibility=hidden`; the standalone binary is not.

---

## Key Types

| Type | Where | Notes |
|---|---|---|
| `Vec3` | raytracer.h:20 | Default-constructs to (0,0,0). All float ops. |
| `Ray` | raytracer.h:90 | Constructor normalises direction automatically. |
| `HitRecord` | raytracer.h:100 | Set via `setFaceNormal()` — always call this from geometry `hit()`. Normal, tangent, and bitangent are all filled by `setFaceNormal()`. `isDelta` initialises to false. |
| `BSDFSample` | raytracer.h:152 | Plain struct — **no default initialisation** of `pdf` or `isDelta`. Always set every field explicitly. |
| `LightSample` | raytracer.h:151 | Returned by `LightList::sample()`; `pdf` includes the light-selection probability. |

---

## Rendering Pipeline

### Per-pixel loop (inside `Renderer::render`)

```
for each sample s:
    ray = camera.getRay(u, v, gen)   // u/v are jittered pixel coords
    sCol = pathTrace(ray, maxDepth, gen)
    if luminance(sCol) > 20.0f:      // firefly clamp
        sCol *= 20.0 / luminance(sCol)
    color += sCol

color /= samples
color = pow(clamp(color, 0, 1), 1/2.2)   // gamma, applied ONCE here
cam.pixels[idx] = color
```

Pixels are stored **post-gamma**, clamped to [0,1]. Do not apply gamma again
in test or output code.

### `pathTrace` loop (raytracer.h ~731)

```
throughput = Vec3(1)
wasSpecular = true

for bounce in [0, maxDepth):
    if no hit:
        color += throughput * sky_background   // sky is ALWAYS present
        break

    if hit emissive:
        if bounce==0 or wasSpecular:           // avoid double-counting NEE
            color += throughput * emitted
        break

    if not rec.isDelta:
        color += throughput * sampleDirect()   // NEE contribution

    Russian Roulette after bounce > 3

    bs = material.sample(rec, wo, gen)
    if bs.pdf <= 0: break                      // catches zero/negative pdf

    wasSpecular = bs.isDelta
    throughput *= bs.f / (bs.pdf + 0.001f)    // the +0.001 is a safety guard
    ray = Ray(rec.point, bs.wi)

    if throughput.max() > 10: throughput *= 10/max  // throughput clamp
```

**Important:** emitted light from direct hits is only added when `wasSpecular`
is true or it's the first bounce. On all other bounces, lights are sampled
explicitly via `sampleDirect()`. A hit on a light mid-path with `wasSpecular=false`
is silently ignored — this is intentional to avoid double-counting NEE.

### `sampleDirect` / NEE+MIS (raytracer.h ~703)

Two strategies are combined with power heuristic MIS:

1. **Light sampling**: sample a point on a light, check shadow, evaluate BSDF
   for that direction.
   `direct += f * Le * powerHeuristic(ls.pdf, bsdfPdf) / (ls.pdf + 0.001f)`

2. **BSDF sampling**: call `material.sample()`, trace the ray; if it hits a
   light, add that contribution.
   `direct += bs.f * Le * powerHeuristic(bs.pdf, lightPdf) / (bs.pdf + 0.001f)`

The returned `direct` is already the full combined estimate — **do not multiply
by NdotL again** in the caller. `sampleDirect` is only called when
`!rec.isDelta`. For delta (specular/glass) materials, set `rec.isDelta = true`
inside `sample()` via `const_cast<HitRecord&>(rec).isDelta = true`.

---

## Material Conventions

These are the contracts every material must satisfy. Violating them causes
systematic brightness errors that are very hard to debug.

### `eval(rec, wo, wi)` — BRDF × cosine

Returns **brdf × NdotL** (the cosine is included).
Lambertian: `albedo/π × NdotL`
Metal GGX: `F × D × G / (4 × NdotV)` — cosine not explicitly in formula but
NdotL appears inside G.

The NEE code calls `eval()` and adds the result directly; it must **not**
multiply by NdotL again. The bug fixed 2026-03-15 (double-cosine overexposure)
was exactly that: the NEE branch was multiplying by `abs(wi·normal)` on top of
`eval()`, scaling contribution as NdotL² instead of NdotL.

**Backface guard:** check raw dot products *before* clamping. The correct
pattern:
```cpp
float rawNdotL = rec.normal.dot(wi);
float rawNdotV = rec.normal.dot(wo);
if (rawNdotL <= 0 || rawNdotV <= 0) return Vec3(0);
// Now use rawNdotL / rawNdotV directly — they are guaranteed positive
```
Clamping before the guard (e.g. `std::max(dot, 0.001f)`) makes the guard
permanently dead and allows below-surface directions to return nonzero values.
This was the root cause of Metal's mean=1.0 overexposure.

### `sample(rec, wo, gen)` → BSDFSample

Returns a sampled direction `wi` and the associated weight. Fields:
- `f` — the BRDF×cosine value for `(wo, wi)` (same convention as `eval()`)
- `pdf` — probability density of having sampled `wi`
- `isDelta` — true for perfect mirror/glass; suppresses NEE on the next hit
- `wi` — the sampled direction

**Always initialise all fields.** `BSDFSample s;` leaves `pdf` and `isDelta`
uninitialised (garbage). The pathTrace has `if (bs.pdf <= 0) break` but that
only helps if the garbage is ≤ 0.

**pdf must be consistent with eval.** If the pdf formula uses a different
epsilon placement than the D term in eval, `f/pdf` does not simplify correctly
and you get either a bias or black surfaces. For GGX materials:
```cpp
// eval uses:
float D = a2 / (M_PI * denom * denom + 0.001f);

// sample/pdf must derive from the same D:
float D = a2 / (M_PI * denom * denom + 0.001f);   // same formula
s.pdf = D * NdotH / (4.0f * HdotV);               // canonical Jacobian
```
Do not compute pdf as `a2 * NdotH / (M_PI * denom * denom * 4 * HdotV + 0.001f)` —
the epsilon ends up in a different relative position and the ratio diverges for
low roughness.

### Delta materials (Dielectric)

For stochastic selection between reflection and refraction:
- Select branch with probability `fresnel` (reflect) / `1-fresnel` (refract)
- Set `s.pdf = 1.0f` for both branches
- The stochastic selection *is* the importance sampling — do not divide by
  the branch probability again

Setting `s.pdf = fresnel` (old bug) gives `f/pdf = 1/fresnel ≈ 25×` for glass
near-normal incidence, causing catastrophic overexposure.

### `pdf(rec, wo, wi)`

Used for MIS in `sampleDirect`. Must use the same formula as `sample()`. For
delta materials return `0` — they are excluded from the BSDF-sampling MIS path.

---

## Roughness Thresholds

Metal and DisneyBRDF have a `roughness < 0.08` branch that uses a clean
perfect-mirror path instead of GGX. This exists because for very low roughness
the GGX D term is dominated by the `+0.001f` epsilon, making D/pdf → 0 and
the surface appear black. The threshold was raised from 0.01 to 0.08 after
this was confirmed experimentally.

---

## HitRecord Semantics

`setFaceNormal(ray, outwardNormal)`:
- Flips normal to face the incoming ray (`frontFace` tracks which side was hit)
- Builds orthonormal basis: `tangent`, `bitangent`, `normal`

After `setFaceNormal`:
- `rec.normal` always points toward the incoming ray
- `wo = -ray.direction.normalized()` → `wo.dot(rec.normal) > 0` always
- `rec.tangent` and `rec.bitangent` are valid; GGX sampling uses them to
  transform the half-vector to world space

`rec.isDelta` starts as `false`. Materials set it to `true` inside `sample()`
via `const_cast<HitRecord&>(rec).isDelta = true` when they are perfectly
specular. The renderer checks this immediately before calling `sampleDirect()`.

---

## Camera and Pixel Layout

- `v = 1 - y/(height-1)` in the render loop — row 0 is the **top** of the image
- `cam.pixels` is stored in row-major order: `pixels[y * width + x]`
- Values are post-gamma, [0,1] floats
- `cam.albedoBuffer` and `cam.normalBuffer` hold the first-hit AOVs (used for
  denoising passes)

The standalone `writePPM`/`writePNG` iterates y forward (0→height-1). Do not
reverse the y-loop to compensate for any perceived flip — the render loop
already handles orientation.

---

## Thread Safety

`Renderer::render()` uses `#pragma omp parallel for collapse(2)` over tiles.
Each tile gets its own `std::mt19937` seeded with `std::random_device{}() + tileY*tilesX + tileX`.

The progress callback (third argument to `render()`) is called from **inside
the parallel region**. Passing a callback that touches non-thread-safe state
(e.g. `std::cout`) will cause data races. Pass `nullptr` unless your callback
is explicitly thread-safe (atomic counter, mutex-guarded, etc.).

---

## Scene Conventions

**Cornell box** (scene 1, `buildCornellBox` in apps/main.cpp):
- Box spans ±2 in all axes, camera at z=5.5 looking at origin
- Light: two triangles at y=1.98 (just below ceiling), intensity 15.0
- Three spheres: glass IOR=1.5, Disney roughness=0.3/metallic=0.5, Metal roughness=0.1
- Expected mean pixel brightness post-gamma: ~0.38–0.42 at 64+ spp

**Sky background** is always present: `(Vec3(1)*(1-t) + Vec3(0.5,0.7,1)*t) * 0.2f`.
Open-sky scenes are brighter (~0.4 mean) than Cornell box scenes because the
box walls occlude most of the background. Never assert "no light source = dark
image".

---

## Debugging Brightness Problems

**Systematic overexposure (image too bright or mean=1.0):**
1. Isolate by material: render Cornell box walls + light only, then add each
   sphere type one at a time. The first addition that raises mean significantly
   is the culprit.
2. Check `eval()` backface guard — is it dead because NdotL/V were clamped before
   the `<=0` check?
3. Check for double-cosine — does `sampleDirect` multiply by `abs(wi·normal)`
   after calling `eval()`? (eval already includes the cosine)
4. Check Dielectric pdf — should be 1.0, not `fresnel` or `1-fresnel`.
5. Check `f/pdf` ratio — for GGX, confirm the epsilon in the pdf formula matches
   the epsilon in the D formula used by eval.

**Image too dark / material appears black:**
1. Check roughness threshold — near-mirror materials need the delta path
   (threshold 0.08 for Metal/Disney).
2. Check eval() reflection direction formula — `2*(wo·n)*n - wo` not
   `wo - 2*(wo·n)*n` (the latter equals `-wi`).
3. For NEE, check that delta materials set `rec.isDelta = true` so `sampleDirect`
   is skipped (delta surfaces should not receive NEE).

**Convergence gets worse with more samples (mean increases with SPP):**
This indicates a positive bias per sample. Most likely causes in order of
likelihood: (1) dead backface guard in eval, (2) double-cosine in NEE, (3)
Dielectric pdf set to the Fresnel probability instead of 1.0.

**Standalone and Python binding diverge:**
They compile the same header. If standalone is much brighter, check:
- Progress callback thread safety (should be `nullptr`)
- Default parameter values (`depth`, `adaptive`) — keep them identical
- Any `const_cast` or mutable state that could behave differently under
  different optimisation levels

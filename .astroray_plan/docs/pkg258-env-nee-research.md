# pkg258 — Environment NEE + importance sampling research note

`cite-algorithm` note (CLAUDE.md §6). The estimator is not invented: it is the
PBRT-4e / Cycles infinite-area-light next-event estimator applied to the
already-existing `EnvironmentMap` piecewise-constant CDF. This note records the
formulas, the lat-long Jacobian, the MIS weighting on both legs, the env-vs-lamp
selection choice, and the `worldMaxBounces` gate, with line pointers into the
Astroray code that this PR fixes/wires.

## References (license-checked)

- **PBRT 4e §12.5 "Infinite Area Lights"** — `ImageInfiniteLight::SampleLi`,
  `ImageInfiniteLight::PDF_Li`, `PiecewiseConstant2D::Sample`/`::PDF`
  (pbrt-v4, Apache-2.0, `src/pbrt/lights.cpp`, `src/pbrt/util/sampling.h`).
  The estimator: importance-sample a piecewise-constant 2-D distribution over
  the equirect image weighted by luminance·sinθ, convert the (u,v) sample to a
  direction, and return `L / pdf_solid`. PBRT-4e uses an *equal-area* octahedral
  parameterisation; Astroray (like Cycles' `background_map_*`) uses the
  classic **lat-long / equirectangular** parameterisation, so the Jacobian
  below is the lat-long one, not PBRT's equal-area one.
- **Cycles `intern/cycles/kernel/light/background.h`** (Blender, Apache-2.0):
  `background_map_sample` (marginal-CDF row search → conditional-CDF column
  search → direction), `background_map_pdf` (inverse map + `pdf * res / (2π²
  sinθ)`), `background_light_sample`/`background_light_pdf` (the MIS entry
  points). `intern/cycles/scene/light.cpp::device_update_background` builds the
  CDF (`sample_map_resolution`, luminance·sinθ weights). MIS-compensation
  (`background_portal_*`) is explicitly out of scope (spec Non-goals).
- **Existing Astroray precedent** for lamp NEE + two-sided MIS mirrored here:
  `include/raytracer.h` `pathTraceSpectral` lamp block (NEE leg + the pkg120
  two-sided emissive-hit MIS leg) and `plugins/integrators/
  multiwavelength_path_tracer.cpp` pkg195 Stage A.

## Parameterisation and the CDF (already in the codebase)

`EnvironmentMap::buildCdf()` (raytracer.h) builds exactly the PBRT/Cycles
piecewise-constant 2-D distribution:

- Per texel `(u,v)`: `func(u,v) = luminance(texel) · sin(π (v+0.5)/H)`. The
  `sinθ` factor is the lat-long solid-angle weight (rows near the poles cover
  less solid angle). `luminance` uses the Rec.709 luma of the *pre-strength,
  pre-tint* RGB.
- `marginalFunc[v] = Σ_u func(u,v)`; `marginalCdf` = normalised prefix sum over
  rows. `conditionalCdf[v]` = normalised prefix sum over columns within row v.
- `totalPower = Σ_{u,v} func`.

Sampling (`EnvironmentMap::sample`): draw ξ1,ξ2; `lower_bound` in `marginalCdf`
→ row v; `lower_bound` in `conditionalCdf` row → column u; take the texel
centre `(u+0.5, v+0.5)`.

## Lat-long direction map and its inverse (the azimuth bug this PR fixes)

Env-map space uses **Y as the polar axis**. For pixel centre `(uc, vc)` with
`uc = u+0.5`, `vc = v+0.5`:

    theta = (1 - vc/H) · π          # polar angle, [0, π]
    phi   = (uc/W - 0.5) · 2π       # azimuth, [-π, π]      <-- the fix
    dir_env = (sinθ cosφ, cosθ, sinθ sinφ)
    dir_world = M^T · dir_env       # inverse of the baked env rotation

The inverse map used by `pdf()`/`lookup()`/`evalSpectral()`:

    theta = acos(clamp(dir_env.y, -1, 1))
    phi   = atan2(dir_env.z, dir_env.x)
    u_norm = 0.5 + phi/(2π)   → x = floor(u_norm · W)
    v_norm = 1 - theta/π      → y = floor(v_norm · H)

**Bug (raytracer.h `EnvironmentMap::sample`, gpu_bvh.h `gpu_envmap_sample`):**
the sample computed `phi = (uCont - 0.5) · 2π` with `uCont = u + 0.5` still in
**pixel** units — the `/ W` was missing. So `phi = u · 2π`, which wraps to ≈0
for every integer column: every importance sample pointed at azimuth 0 while
carrying the correct texel's radiance and pdf. `pdf()` used the correct
normalised `u = 0.5 + phi/2π`, so sample() and pdf() disagreed. **Fix:**
`phi = (uCont / width - 0.5) · 2π`, which is the exact inverse of `pdf()`'s
`u_norm → phi` map (including the half-texel: sample uses centre `u+0.5`, pdf
floors `u_norm·W` back to `u`). The polar/v convention was already consistent:
sample `theta = (1 - vc/H)π` inverts pdf's `v_norm = 1 - theta/π` with the same
half-texel offset.

## PDF in solid-angle measure (the lat-long Jacobian)

The piecewise-constant map pdf in (u,v) *unit-square* measure at a texel is

    pdf_uv = func(u,v) · W · H / totalPower

Change of variables from the unit square to the sphere. For lat-long,
`u = (φ/2π)+0.5`, `v = 1 - θ/π`, the map from `(u,v)∈[0,1]²` to directions has
Jacobian |∂(u,v)/∂ω| = 1/(2π · π · sinθ) = 1/(2π² sinθ). Hence

    pdf_solid = pdf_uv / (2π² sinθ)                          (Cycles background_map_pdf)

Both `EnvironmentMap::sample` and `EnvironmentMap::pdf` already implement this
identical `mapPdf / (2π² sinθ)` (with `sinθ` floored at 1e-6). The contract test
asserts `pdf(sample.direction) == sample.pdf` to 1e-4 rel; this holds once the
azimuth fix makes `sample.direction` invert back to the sampled texel.

## MIS on BOTH legs (power heuristic β=2)

Env NEE and BSDF-sampling are two strategies for the same background integral;
combine by the power heuristic (Veach 1997 §9.2; identical form to the existing
lamp NEE and to Cycles `power_heuristic`):

- **NEE leg** (at a non-delta shading vertex, gated on `bounce+1 <=
  worldMaxBounces`): sample the env CDF → `wi, envPdf`; shadow ray to infinity
  through `shadowTransmittance()` (pkg253); contribution
  `throughput · f(wo,wi) · L_env(wi) · w / envPdf · Tr` with
  `w = powerHeuristic(envPdf, bsdfPdf(wo,wi))`.
- **Miss leg** (BSDF-sampled continuation misses all geometry and reaches the
  background): full env radiance when the previous bounce was the camera ray or
  a specular/delta lobe (no NEE competed — unweighted, `w=1`, keeps the
  directly-visible sky exact); otherwise weight by
  `w = powerHeuristic(bsdfPdfPrev, envPdf(dir))`. This is the exact mirror of
  the pkg120 two-sided emissive-hit MIS already in `pathTraceSpectral`.

The two weights sum to ≈1 per background direction ⇒ the white-furnace
(uniform env, albedo 1) integrates to exactly the reflected radiance (1.0), with
no double counting between NEE and miss. `L_env` for the NEE leg is taken from
`evalSpectral(wi)` (bilinear, strength+tint applied) — the SAME function the
miss leg uses — so NEE and miss agree per wavelength (spec requirement).

## Env-vs-lamp selection — CHOICE (open question for review)

Astroray keeps the environment separate from `LightList` (dedicated lamps +
area lights). A background miss ray and a dedicated lamp are geometrically
**disjoint** (a ray either reaches the infinite background or hits a finite
emitter). Therefore this PR treats env NEE and lamp NEE as **two independent,
additive NEE strategies**, each forming its own MIS pair with BSDF sampling —
NOT a single "pick env or lamp" selection. Consequences:

- No `envSelectProb()` selection weight is applied; the dormant
  `envSelectProb()` helper (raytracer.h) stays unused (documented, not deleted).
  Rationale: introducing a 50 % env/lamp selection would *increase* variance on
  scenes that have both a lamp and an HDRI (each strategy fires half as often)
  for no bias benefit, since the strategies already sample disjoint supports.
- This differs from Cycles, which folds the background into a single
  light-selection distribution (light tree / `light_distribution_sample`) and
  picks one light per NEE. Cycles' energy-weighted selection is a *variance*
  optimisation (spend samples where the energy is), not a correctness
  requirement; the additive form here is unbiased and simpler, and matches how
  Astroray already separates `EnvironmentMap` from `LightList`.
- **Open question for the Terra review:** is the additive disjoint-strategy
  estimator acceptable, or does the lead want the Cycles-style single
  energy-weighted selection (which would require putting the background into
  `LightList`/the pkg86 light tree — larger surface, and pkg86 territory)?

## `worldMaxBounces` gate (pkg201)

Mirrors the existing miss gate: env NEE at bounce `b` contributes only if
`b + 1 <= worldMaxBounces` (the NEE sample is one additional bounce of world
light onto the vertex). The miss leg keeps its existing `bounce <=
worldMaxBounces` gate. Default `worldMaxBounces = 1024` (effectively unlimited),
so default renders are unaffected by the gate.

## Files touched by the estimator wiring

- `EnvironmentMap::sample` / `gpu_envmap_sample` — one-line azimuth fix.
- `pathTraceSpectral` (in-header) — NEE block + MIS-weighted miss leg.
- `multiwavelength_path_tracer.cpp` — same, using `evalSpectralExt` for the
  BSDF factor (profile-aware) as the pkg195 lamp block does.
- `src/cpu/wavefront/path_kernel.cpp` — shared-kernel twin (CPU/GPU snapshot
  oracle; RNG draw guarded on `envMap->loaded()` so non-env scenes are
  byte-identical; the GPU wavefront half is a separate PR).
- All gated on a runtime `envNeeEnabled` flag (default ON post-PR;
  `set_env_nee(bool)` for the A/B convergence test).

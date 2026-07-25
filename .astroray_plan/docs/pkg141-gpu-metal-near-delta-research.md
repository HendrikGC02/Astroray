# pkg141 — GPU near-delta Disney-metal over-brightness: root-cause research

> **⚠️ SUPERSESSION NOTE (2026-07-25, architect):** the post-#518 residual
> ratios recorded in this doc (near-delta GPU/CPU 0.60–0.77) are **no longer
> citable as the current state**: after PR #523 (pkg152 compensation-table
> mirror + clearcoat fix) the verifier measured ~1.0 near-delta in a different
> setup. The two measurements are reconciled by **pkg158** (Step 0,
> scene-controlled re-measure with `applyGamma` stated on both legs) — read
> its outcome before citing either number.

**Package:** pkg141-gpu-near-delta-disney-metal-brightness
**Constraint:** Lane B, parallel with a `plugins/materials/disney.cpp` chain
(Lane A). This package does not edit `disney.cpp` at all; every fix below is
in GPU-only / shared-upload code.

## Instrumentation (static code-reading, not a live HW dump)

The spec asked to adjudicate S1 (sample/pdf mixture-pdf convention
asymmetry) vs S2 (GPU closure-graph Disney twin) before fixing. Live
per-event `(f, pdf)` dumps on RTX were not run for this package (parallel-
lane GPU-lock discipline — see memory `cuda_verifier_concurrency` and this
package's explicit instruction to leave all GPU execution to the
hardware-verifier). Instead the mechanism was pinned down by tracing the
exact GPU code path the pkg123 test scene (`disney` material, `metallic=1.0`,
`roughness in {0.0,0.03,0.05,0.1}`, `transmission=0.0`) actually executes,
end to end from CPU material upload to the GPU BSDF dispatch.

### S2 confirmed: the material never reaches `GMAT_DISNEY` at all

`plugins/materials/disney.cpp::closureGraph()` (read-only; not edited)
unconditionally adds a `GGXConductor` closure whenever
`transmission_ < 0.999f`:

```cpp
const float conductorWeight = transmission_ < 0.999f ? 1.0f : 0.0f;
if (conductorWeight > 1e-4f) {
    graph.add(astroray::makeGGXConductorClosure(base, roughness_, conductorWeight));
}
...
if (graph.empty()) {
    graph.add(astroray::makeDiffuseClosure(base, 1.0f));
}
```

The `graph.empty()` fallback means `closureGraph()` is **never** empty for
any Disney material. `src/gpu/scene_upload.cu::convertMaterial` uploads via
the closure-graph path whenever `!graph.empty() && validateClosureGraph(...)`
— which is therefore *always true* for "disney" materials. The direct
`if (gpuType == "disney") { g.type = GMAT_DISNEY; ... }` branch a few lines
below is dead code for every Disney material actually reachable from a
scene (confirmed via `validateClosureGraph`, `src/material_closure.cpp:106`,
which only rejects empty graphs, `None`-type closures, out-of-range
roughness/weight/IOR — a single well-formed `GGXConductor` closure always
passes).

So the pkg123 test's "Disney metal" material uploads as
`GMAT_CLOSURE_GRAPH` with exactly one closure:
`GGXConductor(color=baseColor, roughness=r, metallic=1.0 (hardcoded in
`makeGGXConductorClosure`), weight=1.0)`.

### The closure dispatch picks the wrong BRDF model

`include/astroray/gpu_materials.h::gpu_closure_as_material` (pre-fix) mapped
`GCLOSURE_GGX_CONDUCTOR -> GMAT_METAL` unconditionally:

```cpp
case GCLOSURE_GGX_CONDUCTOR:
    tmp.type = GMAT_METAL;
    tmp.metallic = 1.0f;
    break;
```

`GMAT_METAL` dispatches to `gpu_metal_eval`/`gpu_metal_sample`
(`gpu_materials.h`), which is a byte-faithful GPU mirror of the **standalone**
`plugins/materials/metal.cpp` (`MetalPlugin`) — a different CPU plugin from
`DisneyPlugin`. Both `MetalPlugin::closureGraph()` and `DisneyPlugin::
closureGraph()` emit the identical `GGXConductor` closure shape (same
fields: color/roughness/metallic/weight), so the closure itself carries no
information distinguishing which CPU plugin it came from.

`MetalPlugin`'s own model (both CPU `metal.cpp::eval/sample` and its GPU
mirror `gpu_metal_eval/sample`) has an intentional near-delta shortcut:

```cpp
// metal.cpp / gpu_metal_eval, roughness <= 0.1:
s.f = albedo_;   // FULL albedo, no Fresnel/D/G shaping at all
s.pdf = 1;
s.isDelta = true;
```

This is correct **for MetalPlugin**, because CPU MetalPlugin has the exact
same shortcut (GPU mirrors it faithfully). It is wrong when reused for a
`DisneyPlugin` metallic lobe: `DisneyPlugin::eval()/sample()/pdf()`
(`plugins/materials/disney.cpp`, read-only) **never** special-cases low
roughness — it floors `alpha = max(roughness^2, 0.0064)` and always samples/
evaluates a continuous GGX (`D_GTR2`) lobe with Fresnel-Schlick and Smith-G,
even at `roughness = 0.0`.

Because the GPU render for this material actually executes
`gpu_metal_eval`'s unconditional "reflect 100% of `baseColor`" shortcut
instead of Disney's Fresnel/roughness-shaped GGX, the GPU output is
independent of roughness within `roughness<=0.1` (matches the measured
evidence: GPU mean **byte-identical** — 0.02387 — across all four rows,
while only the CPU mean varies row to row) and is *brighter* than the
correctly-shaped Disney GGX reflectance (no Fresnel attenuation, no
D/G shaping, no energy loss to grazing geometry) — consistent with the
measured 2.7–4.0x GPU/CPU ratio.

### Secondary, stacked bug found while reading `gpu_disney_eval`

Once the dispatch is corrected to actually call `gpu_disney_eval`, a second,
independent bug in that function would still cause residual GPU/CPU
divergence: the specular term carried a stale extra division —

```cpp
// gpu_materials.h (pre-fix)
float Gs = gpu_smithG_GGX(NdotL, a) * gpu_smithG_GGX(NdotV, a);
GVec3 spec = Ds * F * Gs / (4.f * NdotL * NdotV + 0.001f);
```

`gpu_smithG_GGX` is the **combined visibility** form
`G1/(2*NdotV)` (Walter 2007 Eq. 34's `G1` folded with the Cook-Torrance
`1/(4*cosO*cosI)` denominator — this is stated explicitly in the CPU
`smithG_GGX` comment, `plugins/materials/disney.cpp:28-30`, and Kulla &
Conty 2017's "Vis" term / Cycles `bsdf_microfacet.h`'s
`bsdf_microfacet_ggx_D_G` convention use the same folding). So
`Gs = smithG_GGX(NdotL,a)*smithG_GGX(NdotV,a) == G/(4*NdotL*NdotV)` already,
and `spec = Ds*F*Gs` (no further division) is the complete Cook-Torrance
BRDF. Dividing again by `(4*NdotL*NdotV+0.001f)` double-counts that factor
(`spec = D*F*G/(4*NdotL*NdotV)^2`), amplifying the term by
`1/(4*NdotL*NdotV)` whenever `NdotL*NdotV < 0.25` (any grazing/off-normal
hit).

`git log --all -S "Vec3 spec = Ds * F * Gs;" -- plugins/materials/disney.cpp`
shows the CPU side had this exact bug and fixed it:
commit `1df244f` (pkg60 / PR #178, "feat(pkg60): Disney v2 energy
compensation (no-glow materials)"): *"Correct the Disney specular/clearcoat
Smith-G denominator bug found by the furnace grid."* — `plugins/materials/
disney.cpp`'s `spec = Ds*F*Gs / (4*NdotL*NdotV+0.001f)` became
`spec = Ds*F*Gs;` at that commit and has stayed that way since. The GPU
mirror (`gpu_materials.h`) was never updated when PR #178 landed — confirmed
via `git show 1df244f --stat`, which touches only `plugins/materials/
disney.cpp` and no `.h`/`.cu` files.

The identical stale pattern also exists in `gpu_disney_eval`'s clearcoat
term (`ccTerm = ... / (4.f*NdotL*NdotV + 0.001f)`), matching the CPU's own
pre-pkg60 clearcoat formula (also fixed by the same commit, to
`clearcoatTerm = Vec3(clearcoat_ * Dr * Fr * Gr) * 0.25f;`, no divide). This
package does **not** fix the clearcoat term: `mat.clearcoat` is hardcoded to
`0.0f` for every closure-graph-dispatched material
(`gpu_closure_as_material`, unconditional `tmp.clearcoat = 0.0f;`), and the
only other caller of `gpu_disney_eval` (the direct, non-closure-graph
`GMAT_DISNEY` upload path) is dead code per the S2 finding above — so the
clearcoat term is unreachable with a nonzero `clearcoat` today. Left as a
documented, out-of-scope latent bug (comment added at the call site) rather
than touched, per the spec's non-goal "only the metal near-delta defect and
whichever single mechanism the instrumentation convicts."

## References

- Walter, B., Marschner, S. R., Li, H., Torrance, K. E. (2007), "Microfacet
  Models for Refraction through Rough Surfaces", EGSR 2007 — GGX/Trowbridge-
  Reitz NDF (Eq. 33) and Smith masking-shadowing G1 (Eq. 34); already the
  canonical reference cited throughout `disney.cpp`/`gpu_materials.h`.
- Kulla, C., Conty, A. (2017), "Revisiting Physically Based Shading at
  Imageworks", SIGGRAPH 2017 Course Notes — the combined visibility /
  multi-scatter compensation convention already cited in the surrounding
  code (`ggxCompensationFactor`, `ggxDirectionalAlbedo` in `disney.cpp`).
- Cycles `intern/cycles/kernel/closure/bsdf_microfacet.h` (Apache-2.0) —
  production cross-reference for the "Vis" (combined visibility) term
  convention, already the pattern this repo's `smithG_GGX`/`gpu_smithG_GGX`
  comments cite.
- In-repo generator: `plugins/materials/disney.cpp` commit `1df244f`
  (pkg60, PR #178) is the CPU-side fix this package mirrors on the GPU —
  not a new algorithm, a parity restoration.

## Fix summary (GPU-only, no `disney.cpp` edits)

1. `include/astroray/gpu_types.h`: new `GMaterial::disneyMetalConductor`
   bool, stamped at closure-graph upload time.
2. `src/gpu/scene_upload.cu`: stamp the flag from the already-public
   `Material::getGPUTypeName()` in the closure-graph upload branch.
3. `include/astroray/gpu_materials.h`:
   - `gpu_closure_as_material`'s `GCLOSURE_GGX_CONDUCTOR` case: dispatch to
     `GMAT_DISNEY` (continuous, alpha-floored GGX) instead of `GMAT_METAL`
     (near-delta perfect-mirror) when `disneyMetalConductor` is set.
   - `gpu_disney_eval`'s specular term: remove the stale extra
     `/(4*NdotL*NdotV+0.001f)` divide, mirroring CPU commit `1df244f`.

Both the megakernel (`src/gpu/path_trace_kernel.cu`) and wavefront
(`src/gpu/wavefront/stage_advance.cu`) integrators call the same shared
`gpu_material_eval`/`gpu_material_sample`/`gpu_material_pdf` dispatchers in
`gpu_materials.h`, so this fix applies to both legs without separate edits.

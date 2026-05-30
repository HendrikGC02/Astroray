# Glass renders too dark — energy-conservation bug(s) in spectral refraction (2026-05-30)

**Owner report:** glass looks dark in Astroray (both the `samples/Glass.obj` crystal
showcase and, in Blender, a Principled-BSDF glass whenever roughness > 0). A prior
agent dismissed this as "rendering rough glass is hard." It is **not** hard — it's a
quantified, reproducible energy-conservation bug. This doc is the diagnosis so it can
be fixed correctly.

## Method — white furnace

A clear glass **sphere** in a uniform white environment (`set_background_color([1,1,1])`,
no other lights) must render ≈ 1.0: radiance is invariant along a ray however it bends,
so a clear ball is *invisible* in a uniform field. Any deficit is lost energy.
(Lambertian baseline measures 0.985 — the renderer's furnace is otherwise correct.)

```python
r = astroray.Renderer(); r.set_background_color([1,1,1])
m = r.create_material('dielectric', [1,1,1], {'ior': 1.5}); r.add_sphere([0,0,0],1.0,m)
r.set_integrator('path_tracer'); r.setup_camera([0,0,4],[0,0,0],[0,1,0],40,1,0,4,80,80); r.set_seed(7)
img = np.asarray(r.render(64,32,None,True)).reshape(80,80,3)
print(img[28:52,28:52].mean())   # sphere centre; want ~1.0
```

## Bug 1 (PRIMARY, root-caused + verified) — the η² radiance factor nets to a loss

Refraction BSDFs apply the radiance-transport factor `η² = (η_i/η_t)²` (PBRT/Cycles
do this). Over a closed air→glass→air path it **should cancel** (enter ×(1/1.5)²=0.444,
exit ×1.5²=2.25 → 1.0). In Astroray's path tracer it does **not** cancel — the furnace
loss grows with IOR:

| ior | dielectric furnace (WITH η²) | with η² REMOVED |
|-----|------------------------------|-----------------|
| 1.0 | 0.986 | 0.986 |
| 1.1 | 0.839 | 0.986 |
| 1.3 | 0.628 | — |
| 1.5 | **0.511** | 0.985 |
| 2.0 | 0.440 | 0.985 |

**Removing the `eta*eta` factor restores flat 0.985 energy conservation at every IOR**
(depth-independent: identical at maxDepth 4 and 160, so it is not TIR/maxDepth
trapping). This is the dominant cause of the dark `Glass.obj` crystal (it uses the
smooth `dielectric`, roughness 0). Disney *delta* glass (roughness 0) furnaces at 0.97
because its delta path routes `bs.f` through `RGBAlbedoSpectrum`, which clamps the
exit's 2.25 toward 1 — accidentally masking most of the loss.

**Affected sites (CPU + GPU must change together — CI is GPU-blind):**
- CPU `plugins/materials/dielectric.cpp:65` (spectral), `:170` (rgb)
- CPU `plugins/materials/disney.cpp:407` (smooth refract)
- GPU `include/astroray/gpu_materials.h:291`, `:341` (dielectric), `:667` (disney)
- (GPU `:514` is the rough-transmission `etaT²` Jacobian, which cancels in f/pdf — leave.)

**The open question / fork.** Cycles keeps η² *and* conserves energy, so the correct
fix is to find WHY our cancellation breaks (not just delete η², which deviates from the
reference this project mirrors). The non-cancellation mechanism is **not yet pinned**:
enter ×0.444 and exit ×2.25 are each applied at the right interface, Russian roulette
(raytracer.h:2620) is unbiased, and no double-application or throughput clamp was found
in `pathTraceSpectral`. The loss factor (0.85@1.1, 0.52@1.5, 0.45@2.0) doesn't match a
single clean missing factor, so it's an interaction. Two paths:
- **(a) Remove η²** — verified energy-conserving, correct for air↔glass↔air (the common
  case), but omits the radiance factor Cycles/PBRT keep. 6-site CPU+GPU change.
- **(b) Keep η², fix the cancellation** — parity-faithful, but the mechanism is unsolved.
  Needs integrator-side instrumentation (track per-bounce throughput across the
  enter/exit pair on a single furnace ray).

## Bug 2 (SEPARATE, still open) — Disney rough (GGX) transmission loses ~70%

Disney glass: roughness 0 → 0.97; roughness ≥ 0.05 → **~0.30**, flat across roughness
(a constant ~3× deficit that kicks in exactly at the `kDeltaTransmissionRoughness=0.03`
threshold). This is the bug the owner sees in Blender (Principled BSDF, roughness > 0).
It is a *different* mechanism from Bug 1: the rough path's `etaT²` appears in BOTH
`roughTransmissionEval` and `roughTransmissionPdf` (disney.cpp:153/187), so it cancels
in `f/pdf` — η² is not the cause here. The throughput `f/pdf = G·|HdotO|/(|cosO|·NdotH)`
derives to ~1 on paper, yet measures ~0.30. A first hypothesis (the spectral wrapper
clamping `bs.f > 1` via `RGBAlbedoSpectrum`) was tested and did NOT fix it. Needs
per-branch (rough-reflect / rough-refract / smooth-fallback) throughput instrumentation
in `DisneyPlugin::sample`.

## Scene implication

`glass-mesh-caustic` uses `dielectric` (Bug 1), so the crystal body is darkened by Bug
1 (not the rough bug). Once Bug 1 is fixed the crystal brightens. Independently, the
showcase's environment is too bright — dim it so the glass casts a shadow that the
caustic filaments read inside (matches the Cycles reference comp).

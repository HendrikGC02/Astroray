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

## Bug 1 (PRIMARY, FIXED 2026-05-30) — refraction enter/exit ignored `rec.frontFace`

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

### RESOLVED 2026-05-30 — enter/exit used the normal sign instead of `rec.frontFace`

A single-furnace-ray trace (per-bounce throughput) showed the smoking gun: at the
EXIT surface the refraction applied the **entering** η² (×0.444) again instead of
×2.25, so 0.444×0.444 = 0.197 instead of cancelling. The `HitRecord.frontFace`
flag was correctly `false` at the exit, but the dielectric **ignored it** and
detected enter/exit from `sign(wo·rec.normal)` — and `rec.normal` is the
front-facing (`setFaceNormal`'d) shading normal, so `wo·rec.normal` is ALWAYS > 0,
i.e. every hit read as "entering." So η² is correct and KEPT (parity-faithful with
Cycles/PBRT); the bug was enter/exit detection. This is option (b) from the fork.
Disney already keyed off `rec.frontFace`, which is why its delta glass was ~0.97.

**Fix part 1 — key enter/exit off `rec.frontFace`:**
- CPU `plugins/materials/dielectric.cpp` `refractSpectral` + `sample`.
- GPU `include/astroray/gpu_materials.h` `gpu_dielectric_sample` + `_spectral`.
- (Disney CPU+GPU already used `frontFace`; the rough-transmission `etaT²` cancels
  in f/pdf — untouched. So Bug 2 below is unaffected and still open.)

**Fix part 2 — transformed glass: decorators must PRESERVE `rec.frontFace`.**
A *bare* mesh furnaced 0.966 after part 1, but a *scaled* one still 0.388. The
`Translate`/`Scale`/`RotateY` decorators (`include/advanced_features.h`) re-ran
`setFaceNormal` on the inner hit's *already-front-facing* normal, forcing
`rec.frontFace = true` on every transformed hit → refraction read "entering" again.
This silently broke refraction on **all transformed glass** (the Blender addon
transforms every object). Fixed: each decorator transforms the normal direction but
preserves the inner `frontFace` (it already set the normal front-facing, so
`rec.normal = X` replaces `setFaceNormal(ray, X)` with no normal change).

**Verified:** dielectric sphere furnace 0.51 → **0.983** flat across IOR; scaled
`Glass.obj` mesh furnace 0.39 → **0.963**; the crystal renders as clear glass. η²
retained. Full pytest suite re-run as the regression gate (decorator change is
core). GPU mirrors CPU; CPU↔GPU runtime parity needs the RTX `/verify` sweep
(CI is GPU-blind — but `cuda-syntax-check` compiles the GPU header).

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

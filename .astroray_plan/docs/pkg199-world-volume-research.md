# pkg199 — GPU wavefront world volume: research + design note

**Package:** pkg199 (GPU wavefront homogeneous world volume). **Stage 1 = this PR.**
**Author:** package-implementer, 2026-08-13.

## 0. Spec-premise correction (git-archaeology)

The spec as filed claimed the CPU "has a working homogeneous world volume … with
Beer-Lambert transmittance … and Henyey-Greenstein anisotropy
(`include/raytracer.h:2110-2255`)" and asked to port HG in-scatter + distance
sampling + NEE-through-medium to the GPU "matching the CPU model exactly."

Verified against HEAD `f965f93`, this premise is **false**:

- There is **no** Henyey-Greenstein phase function, **no** in-scatter, **no**
  distance sampling, and **no** NEE-through-medium anywhere in the CPU
  integrator — and there never was. `worldVolumeAnisotropy` is stored by
  `setWorldVolume` and **read by no render code in the entire git history**.
- The only volume code is `Renderer::worldTransmittance(distance)`
  (`include/raytracer.h:2159`) — pure Beer-Lambert **absorption**
  `exp(-sigmaT·t)`, `sigmaT = worldVolumeColor·worldVolumeDensity`.
- That function is **dead code**: repo-wide, `worldTransmittance(` appears only
  at its definition — **zero call sites**.

Archaeology: world volume was added in pkg25 (`245d1fa`, "add global world
volume attenuation support"). It wired Beer-Lambert absorption into the **legacy
RGB integrator** in three roles — NEE emission (`f·ls.emission·Tr(ls.distance)`),
MIS BSDF-emission (`bs.f·Le·Tr(bRec.t)`), and throughput
(`throughput *= Tr(rec.t)`). pkg14 (`90ebb31`, "spectral env map atlas … delete
legacy RGB path") **deleted the legacy RGB integrator wholesale**, removing all
three call sites; they were never ported to the spectral path tracer that is now
the default. So the current CPU renders a fog scene as **vacuum**, exactly like
the GPU.

**Coordinator decision (staged Option B):** re-wiring absorption into the
spectral tracer completes an orphaned feature (the deletion targeted the RGB
integrator, not world volumes) — not a reversal of intent; sign-off granted.
Absorption-only (A) is a strict subset of the full scattering medium (B), so we
stage: **Stage 1 (this PR) = Beer-Lambert absorption, CPU re-wire + GPU mirror,
at parity;** Stage 2 = full HG scattering (spec-only below).

## 1. Algorithm sources (CLAUDE.md §6)

Homogeneous-medium Beer-Lambert transmittance is textbook, but cited per the
cite-algorithm rule:

- **PBRT-v4**, Pharr/Jakob/Humphreys, §11.3 "Media" / `HomogeneousMedium`:
  transmittance along a ray segment of length `t` through a medium with
  extinction `sigma_t` is `Tr = exp(-sigma_t · t)` (Beer's law). For an
  absorption-only medium `sigma_t = sigma_a`. (Reference impl `src/pbrt/media.cpp`,
  Apache-2.0-compatible BSD.)
- **Cycles** (`intern/cycles/kernel/integrator/volume.h`, `volume_shader.h`,
  Apache-2.0): homogeneous transmittance `exp(-sigma_t · dt)` accumulated along
  the ray; per-channel (spectral) extinction.

Stage 1 uses **only** the transmittance term — no phase function, no scatter
event sampling. `worldVolumeAnisotropy` stays inert (reserved for Stage 2).

## 2. Spectral discipline (pinned, both backends)

`worldVolumeColor` is a **reflectance-like colour**. Per the JH-nonlinearity rule
([[spectral-upsample-nonlinearity-scaled-bsdf]]) and the coordinator directive:
**upsample the colour, then apply Beer-Lambert per wavelength — never upsample
the product.**

    sigmaColor[λ] = upsample_reflectance(worldVolumeColor)[λ]      // JH albedo LUT
    Tr[λ]         = exp( -max(0, sigmaColor[λ]) · worldVolumeDensity · dist )

- CPU: `RGBAlbedoSpectrum({r,g,b}).sample(lambdas)` (spectrum.h:214, [0,1] LUT).
- GPU: `gpu_rgbToSampledSpectrum(color, lambdas, GSPEC_RGB_ALBEDO)` (same LUT).

Both backends run the **identical** spectral computation, so parity holds by
construction. (This deliberately differs from the deleted legacy RGB
`worldTransmittance`, which computed `exp(-color·density·d)` in RGB; that code is
gone and is *not* the parity target — the spectral form is defined identically on
both sides here.)

## 3. Transmittance semantics — pinned identically on CPU and GPU

Throughput carries transmittance over each traversed ray segment; the final
infinite camera→env segment is **not** attenuated (matches the legacy model, and
is the only mirror-able choice for an env at infinity). Three roles:

1. **Throughput / free-flight (segment `rec.t`).** On a confirmed surface hit,
   `throughput *= Tr(rec.t)` *before* shading that vertex. Attenuates the hit's
   emission and propagates the fog to all later bounces and to the vertex's NEE.
2. **NEE / shadow ray (segment `ls.distance`/`s.maxDist`).** Multiply the NEE
   contribution by `Tr(shadowDistance)` — light travels through the medium from
   the shading vertex to the lamp.
3. **Lamp-MIS emission (segment `lh.t`/`lampT`).** A dedicated lamp intersected
   closer than the surface: attenuate its emission by `Tr(lampDist)`. (Throughput
   is not yet segment-attenuated at this point — the lamp is closer than the
   surface — so this is a direct `Tr(lampDist)` on the lamp emission.)

Env-miss: throughput already carries prior-bounce fog; the current (infinite)
segment adds nothing. Emissive-Hittable hit is covered by role 1 (throughput is
attenuated before `throughput·Le` is added).

## 4. Where it lives in the wavefront (register-gate design)

The REG-254-saturated kernel is `stageShadeBucketedKernel` (16-way
`<HasPrincipled,HasTexture,HasPhotons,HasDispersion>`). Rather than add a 5th
template axis (→ 32 instantiations) to carry volume state into that kernel, all
three roles land in **non-pinned stages**, so the shade kernel is **left byte-for-
byte untouched** — the register gate passes *by construction*. This is the same
move pkg197 made for guide-AOVs (written from the intersect stage precisely to
keep the shade kernel byte-identical, `stage_advance.cu:298-315`):

- Roles 1 & 3 → `intersectPathSlot` (kernel `stageIntersectQueued`). It already
  has `rec.t`, `lampT`, and does the emission/env accumulate. Attenuate emission
  there and write the segment-attenuated throughput back to the per-path SoA so
  the shade stage reads it.
- Role 2 → `stageShadowKernel` (the deferred NEE trace+resolve). It already reads
  `s.maxDist` (nee_f lane 6) and the parked contribution (lanes 7-10); multiply
  by `Tr(maxDist)` there.

Both are gated at **runtime** on a `__constant__ GWorldVolume c_worldVolume`
symbol (published once per frame by `cuda_wavefront_render`, mirroring
`c_wfTexBinding`/`c_wfGuideBinding`). For a vacuum scene `hasVolume==0`, the
branch is not taken, throughput/contrib are untouched → **byte-identical pixels**,
and — because `stageShadeBucketedKernel` is not modified at all — its cuobjdump
footprint stays exactly REG 254 / STACK 3352 / CONSTANT[0] 1700.

> Deviation-with-rationale vs the literal "compile-time HasWorldVolume axis"
> instruction: the instruction is a *means* to the end "shade kernel stays
> byte-identical." Keeping volume code out of the shade kernel entirely achieves
> that end more cleanly (no 16→32 instantiation blow-up, no cuobjdump byte-diff
> to defend) and matches the pkg197 precedent. Reported to the coordinator.

## 5. Stage 2 (spec-only; NOT implemented here)

Full scattering medium — HG in-scatter, analytic exponential distance sampling of
a scatter event, phase-function/light MIS (NEE-through-medium) — CPU **first**
then GPU mirror. Register budget: an in-scatter event needs a medium-interaction
decision + phase sample + a shadow connection with per-segment transmittance;
this is live state the REG-254 shade kernel cannot absorb, so Stage 2 should add a
**dedicated volume-scatter wavefront stage** (its own kernel, between intersect
and shade) rather than folding into `stageShadeBucketed`. Sources: PBRT-v4 §14.2
(volumetric path tracing, `SampleLd` through media), Henyey & Greenstein 1941 /
PBRT `HGPhaseFunction`, Cycles `kernel/integrator/volume.h` `volume_integrate`.
Estimated XL; dispatched separately.

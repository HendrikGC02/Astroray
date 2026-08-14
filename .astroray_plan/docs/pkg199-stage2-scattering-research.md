# pkg199 Stage 2 — homogeneous scattering medium: research + design note

**Package:** pkg199 Stage 2 (full HG scattering world medium). **PR 2a = CPU.**
**Author:** package-implementer, 2026-08-14.

## 0. Scope / premise (confirmed against HEAD 9d6eb98)

Stage 1 (PR #611, landed) added Beer-Lambert **absorption only** to the spectral
path tracer `Renderer::pathTraceSpectral` (`include/raytracer.h`): three
`worldTransmittanceSpectral` multiplies (role 1 free-flight `rec.t`, role 2 NEE
`ls.distance`, role 3 lamp-MIS `lh.t`). There is **no** medium-interaction loop,
**no** distance sampling, **no** HG phase, and `worldVolumeAnisotropy` is stored
but read by no render code. Confirmed by grep. Stage 2 adds the genuine
scattering estimator, CPU first (this note / PR 2a), GPU wavefront mirror in 2b.

## 1. Algorithm sources (CLAUDE.md §6 — cite, do not invent)

- **PBRT-v3** `HomogeneousMedium::Sample` (`src/media/homogeneous.cpp`, BSD /
  license-compatible). Spectral homogeneous medium sampling by **per-channel
  selection**:
  - `channel = min(int(u * nSamples), nSamples-1)`
  - `dist = -log(1 - u) / sigma_t[channel]`
  - `t = min(dist, tMax)`; `sampledMedium = t < tMax`
  - `Tr = exp(-sigma_t * min(t, MaxFloat))` (a SampledSpectrum)
  - `density = sampledMedium ? (sigma_t * Tr) : Tr`
  - `pdf = average over channels of density[i]`  (balance heuristic across the
    per-channel exponential sampling PDFs — this is what makes coloured media
    unbiased)
  - return `sampledMedium ? Tr * sigma_s / pdf : Tr / pdf`
- **PBRT-v3** `HenyeyGreenstein` (`src/core/medium.cpp`) + Henyey & Greenstein
  1941:
  - `PhaseHG(cosTheta, g) = Inv4Pi * (1 - g^2) / (denom * sqrt(denom))`,
    `denom = 1 + g^2 + 2 g cosTheta`
  - `Sample_p(wo, u)`: if `|g|<1e-3` `cosTheta = 1 - 2 u0`; else
    `sqrTerm = (1-g^2)/(1+g-2 g u0)`, `cosTheta = -(1 + g^2 - sqrTerm^2)/(2 g)`;
    `phi = 2 pi u1`; build `wi` in the frame whose z-axis is `wo`
    (`SphericalDirection(sinTheta, cosTheta, phi, v1, v2, wo)`); returns
    `PhaseHG(cosTheta, g)`. HG is perfectly importance-sampled → **pdf == value**,
    so the phase-sampled continuation multiplies throughput by `value/pdf = 1`.
  - `wo` convention: pbrt sets `mi.wo = -ray.d` (points back along the incoming
    ray). Astroray mirrors this: `woMedium = -ray.direction.normalized()`.
  - `CoordinateSystem(v1,v2,v3)` ported for the orthonormal basis.
- **Cycles** `intern/cycles/kernel/integrator/volume.h` (Apache-2.0) — the
  Blender-facing reference for homogeneous scatter + phase MIS; structure cross-
  check only (Astroray uses the pbrt-v3 analytic-homogeneous form, no
  delta-tracking — heterogeneous grids are a later package).

## 2. Parametrization (coordinator-approved Option A)

The world-volume API is `(density, color, anisotropy)` — no scattering
coefficient existed. Add **single-scattering albedo `alpha` ∈ [0,1]**, default 0:

    sigma_t[λ] = upsample_reflectance(color)[λ] · density     (UNCHANGED from Stage 1)
    sigma_s[λ] = alpha · sigma_t[λ]
    sigma_a[λ] = (1 - alpha) · sigma_t[λ]

- `alpha == 0` (default) ⇒ `sigma_s = 0` ⇒ **the scattering estimator is not
  engaged at all** (`mediumScatters = hasWorldVolume && density>0 && alpha>0`);
  the exact Stage-1 deterministic absorption path runs, so every Stage-1 gate is
  byte-identical by construction and consumes the identical RNG stream.
- The "σ_s=0 → Beer-Lambert parity" acceptance criterion is exactly the α=0 case.
- `worldVolumeAnisotropy` becomes live only when α>0 (HG `g`).

## 3. Estimator wiring in `pathTraceSpectral` (snapshot semantics PINNED)

Per bounce, after `bvh->hit`, compute the nearest terminating-event distance
`termT = min(surfaceT, dedicated-lamp t)` (env ⇒ FLT_MAX). When `mediumScatters`:

1. Channel-select + sample free-flight `fdist` (pbrt-v3, §1).
2. `sampledMedium = fdist < termT`.
3. **Scatter (fdist < termT):** throughput `*= Tr * sigma_s / pdf`;
   **scatter point `P = ray.origin + ray.direction * fdist` — THIS is the snapshot
   moment the GPU volume-scatter stage must mirror byte-for-byte** (capture P
   from the *pre-update* ray, before the continuation ray overwrites origin/dir).
   Then medium NEE (phase/light MIS, shadow transmittance `Tr(ls.distance)`) and
   the HG phase-sampled continuation ray from `P`. `continue`.
4. **Reach termT (else):** throughput `*= Tr / pdf`; fall through to the existing
   lamp/env/surface handling with the Stage-1 role-1 multiply SKIPPED (the
   transmittance is already in throughput via the estimator).

`woMedium = -ray.direction.normalized()` is captured **before** the continuation
ray overwrites `ray`. NEE shadow / lamp / env segments keep the analytic
`worldTransmittanceSpectral` (full σ_t) — role 2 unchanged; role 3 drops its
explicit `Tr(lh.t)` in scatter mode because the estimator already applied
`Tr(termT)/pdf` to throughput.

## 4. Light-path passes (pkg198 sum-to-beauty invariant)

`PASS_VOLUME_DIRECT (=9)` / `PASS_VOLUME_INDIRECT (=10)` were reserved. The enum
layout makes `firstCat = 3` (volume) map cleanly: `3*3+0 = VOLUME_DIRECT`,
`3*3+1 = VOLUME_INDIRECT`. Medium NEE at the first interaction →
`PASS_VOLUME_DIRECT` and locks `firstCat = 3`; a deeper scatter →
`PASS_VOLUME_INDIRECT`; all post-scatter surface/emission/env contributions
inherit `firstCat*3+1 = VOLUME_INDIRECT`. Every new `color += c` is paired with
exactly one `addPass`. The render loop now also runs `xyzToLinearSRGB` on the two
volume passes (previously excluded) so Σpasses == beauty holds in linear sRGB.

## 5. GPU mirror (PR 2b — spec only here)

Dedicated `stageVolumeScatterKernel` between `stageIntersectQueued` and
`stageShadeBucketed`; decides scatter-vs-surface from the sampled free-flight
distance, parks a phase-NEE shadow sample (like the surface NEE), emits the
continuation ray from `P`. `stageShadeBucketedKernel` untouched → REG 254 /
STACK 3352 / CONSTANT[0] 1700 byte-identity carries forward. New `GWorldVolume`
fields: `scatter` (α) and `anisotropy` (g). Snapshot moment for `P` pinned in §3.

## 5b. GPU free-flight RNG + intersect register isolation (PR 2b, as built)

**Counter-based free-flight sampler.** The GPU free-flight uniforms (channel pick
+ distance) are drawn by `gpu_freeflightUniform` — an OBJECT-FREE counter-based
hash reusing the exact keying of `WavefrontRNG::GenerateForDimension` (PBRT-v4
`MixBits` = MurmurHash3 finalizer → PCG32 SetSequence → PCG32 XSH-RR, cited),
keyed on `(pixel, sample, seed, salt)` with `salt = G_WF_VOL_DIM_SALT (0xF0000000)
+ bounce·2 + {0,1}` — per-bounce, per-draw, and disjoint from the shade/volume
`WavefrontRNG` dimension range (0..~depth), so the free-flight stream is
decorrelated from all shading draws and does no `rng_dimension` round-trip. **CPU
and GPU free-flight streams are INDEPENDENT** (the CPU draws from its `mt19937`
inline); the CPU↔GPU parity gate is a per-channel mean-ratio at the 1e-5 MC
convention, NOT sample-matched, so independent streams are correct and expected
(measured god-ray parity ratio ≈ [1.004, 0.997, 0.998]).

**Intersect register isolation (`HasWorldScatter` if-constexpr axis).** The
free-flight *decision* must live in `intersectPathSlot` (it owns the
surface-commit + shade-queue bucketing; a purely-additive kernel can't intercept
before them — see spec Stage-2 "premise correction"). But the decision's live-set
adds +3 REG to the intersect kernel (127→130), which at 256 threads/block crosses
128 → 2→1 blocks/SM. A cooled, contention-controlled, interleaved A/B (burn-in to
2887 MHz, min-of-11, three main legs 116.4–116.9 ms @ 2-blocks vs the
always-present form 120.6 ms @ 1-block) measured a **+3.3% fog-free fleet
regression** (mechanistically confirmed by the power-draw split: 2-block ≈ 153–156 W
vs 1-block ≈ 147 W). Four shave attempts (object-free hash, `__noinline__`,
scatter-math-to-volume-kernel, drop-lamp-bound) all stayed at 130 — the +3 is
intrinsic to any inline decision. Resolution: the established fleet-isolation
pattern (pkg178/184/189) — `template<bool HasWorldScatter>` on
`intersectPathSlotT` + `stageIntersectQueuedKernel`, decision block behind
`if constexpr`. The fleet `<false>` (vacuum + absorption-only fog) compiles it OUT
→ **REG 127 / 2 blocks/SM, byte-identical Stage-1** (cooled vacuum 117.3 ms =
+0.5% vs main, within noise); only scattering fog (`scatter>0`) launches `<true>`
(REG 130, but scattering-bound anyway). A non-template `intersectPathSlot`
forwarder (→`<false>`) preserves the cross-TU symbol for the ReSTIR primary +
MIS-audit kernels (both `scatter=0`). This was chosen over the spec's "Option 2"
(volume kernel owns the surface-reached path) — same fleet-clean result, far lower
correctness risk (the scattering logic is unchanged, only compile-gated).

## 6. Addon UI — explicit follow-up

PR 2a/2b expose α only through the python binding
(`set_world_volume(density, color, anisotropy, scatter=0.0)`). Wiring the
single-scattering-albedo control into the Blender addon world-volume UI is a
tracked **follow-up package** (noted in the spec Stage-2 section + PR body).

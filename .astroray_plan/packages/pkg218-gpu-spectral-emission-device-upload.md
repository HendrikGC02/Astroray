# pkg218 — GPU spectral emission: upload emission SPDs to the device (exact CPU↔GPU lamp-colour parity)

**Track:** A
**Status:** in review (PR #667, 2026-08-31 — device SPD table + upload +
wired into all 3 GPU emission-eval sites for dedicated lights (point/spot/
area/distant): immediate NEE resolve, deferred/bucketed production shadow
stage, and direct visibility to BSDF-continuation rays. ReSTIR deferred
(RGB-only reservoirs, not the default path). GMaterial untouched;
material-level "emissive GMaterial mode" from the design section does not
correspond to an actual CPU gap (verified — GCLOSURE_EMISSION is plain RGB
both sides already), scope narrowed accordingly. Regression gate tightened
8%/30%→5%. NOT YET BUILT OR HARDWARE-VERIFIED — implementer had no CUDA
build access; parent must build + run
tests/test_gpu_emission_colour_parity.py on the RTX 5070 Ti and check the
GNEESample/nee_i register-footprint flag in the PR body before merge).
**Estimated effort:** M (new device table + NEE / emissive-hit eval + addon upload wiring; no register-hostile shade-kernel change).
**Depends on:** the `deviceReference` fine-integration fix (same investigation — ships first, this tightens it).

---

## Goal

Before: the GPU renders **all** non-RGB emission (measured-SPD lamps, blackbody,
composite) as an RGB **approximation**. Each dedicated light and emissive
material carries only `emissionRGB` (`EmissionSpectrum::deviceReference`), and
the device upsamples it via `gpu_rgbSpectrumAt(..., GSPEC_RGB_ILLUMINANT)` —
i.e. it renders `RGBIlluminant(rgb)·D65`, never the raw measured SPD. After the
deviceReference fix the **chroma is close** (the reference RGB is now a fine CMF
integral instead of a 4-sample MC), but it still cannot match the CPU's
true-SPD render to within a few %, because:

1. the Jakob–Hanika RGB→spectral round-trip is lossy, and
2. `RGBIlluminant` bakes a **D65 spectral shape** into the emission that the raw
   measured/blackbody SPD does not have.

After this package: non-RGB emission is evaluated **spectrally on the device**
at the render wavelengths, so CPU↔GPU emission colour matches within a few %
(per-channel mean-ratio) for every preset lamp and blackbody temperature.

---

## Context

Root-caused 2026-08-22 (live Blender MCP repro: `led_5000k` point light over a
diffuse cube — CPU R/G≈1.09 correct, GPU R/G≈1.52 salmon; sodium over-orange,
mercury reddish not blue-green). The full trace:

- Dedicated lights: `PointLight::fillDeviceParams` (`src/lights/point_light.cpp:140`)
  → `emission_.deviceReference(out.emissionRGB, out.exactIlluminant)` →
  `GDedicatedLight.emissionRGB` → NEE `gpu_rgbSpectrumAt(dedEmissionRGB, λ,
  ILLUMINANT)` (`src/gpu/gpu_nee.cuh:561`). No profile index on `GDedicatedLight`.
- Emissive geometry: `gpu_material_emitted_spectral` (`include/astroray/gpu_materials.h:3415`)
  = `gpu_rgbToSampledSpectrum(gpu_material_emitted(mat), wl, mat.spectralMode)`,
  also pure RGB.

There is **no spectral-emission path on the GPU at all** — this is a pkg89-era
gap, not a pkg206 (importance-sampling) regression. The deviceReference fix
removes the gross error; this package removes the residual.

The "measured_spd via the raw Renderer API renders BLACK on GPU" symptom is the
same gap surfacing differently: `deviceReference` calls `EmissionSpectrum::eval`,
which needs `load_spectral_profiles()` on the **CPU** at upload; with a device
SPD table the profile must instead be uploaded to the **device**, so wire the
upload through the same path `uploadProfileTable` uses for reflectance.

---

## Design (recommended: one uniform "baked emission SPD" table)

Do **not** add per-mode device evaluators (device planck / device JH-composite —
register-hostile and duplicative). Instead, at scene-upload time evaluate the
`EmissionSpectrum` once on a fixed fine λ-grid and upload the **sampled SPD** as
an emission profile, exactly mirroring the pkg54a reflectance `g_profileTable`
mechanism. This unifies measured / blackbody / composite behind one device
lookup and inherits the CPU's own normalization (blackbody luminance-norm,
composite filter multiply) for free.

1. **Device table.** Add `g_emissionProfileTable[G_MAX_EMISSION_PROFILES *
   G_EMISSION_SAMPLES]` (constant or global mem, mirror `g_profileTable`) +
   `uploadEmissionProfileTable(host, count)` in `gpu_spectral_tables.{h,cu}`.
   Grid: the CMF support (360–830 nm) at a step fine enough that the device
   linear-interp matches the CPU eval to ≪1% (1–2 nm; reuse the reflectance
   `gpu_profile_reflectance` interpolation shape).
2. **Index fields.** Add `int emissionProfileIndex` (−1 = RGB fallback) to
   `GDedicatedLight` and to the emissive `GMaterial` emission mode. Keep
   `emissionRGB` as the fallback for true RGB-mode emission (`exactIlluminant`).
3. **Upload.** In `scene_upload.cu`, for any light/material whose
   `EmissionSpectrum` is **not** RGB mode: sample `EmissionSpectrum::eval` on the
   grid, register it in the emission-profile table, set the index. RGB mode keeps
   the exact `emissionRGB` path (already bit-exact — do not touch it).
4. **Device eval.** `gpu_nee.cuh` `gpu_nee_resolve`: if `emissionProfileIndex>=0`,
   `L_spec[i] = gpu_emission_profile(idx, lambdas.lambda[i]) * dedGeoScale`
   instead of `gpu_rgbSpectrumAt(dedEmissionRGB,…)`. Same substitution in
   `gpu_material_emitted_spectral` for emissive geometry. The stored pdf[i] is
   still consumed only in the final `spectrumToXYZ` at the same lambda[i] —
   unbiased by construction (no eval-vs-pdf skew, the property the whole
   investigation confirmed).
5. **Addon.** Ensure `convert_scene`/`convert_lights` triggers the emission-profile
   upload (fixes the raw-API black-render note).

## Scope guards / footguns

- **Magnitude, not just chroma.** `emissionRGB` scales the NEE radiance via
  `dedGeoScale`; the baked SPD must carry the same integrated magnitude the CPU
  eval produces (blackbody is luminance-normalized to unit Y — verify the device
  path reproduces that, else lamp brightness shifts). Gate energy with an upper
  bound too (`gamma-furnace-cannot-detect-energy-gain`).
- **Blackbody T-sweep** must be covered — it is the **default** emission mode, so
  a chroma shift here changes every default lamp.
- **Line lamps** (sodium ~589 nm, mercury): the 4-sample render MC still applies;
  keep pkg206 importance sampling + the pkg195 uniform-selection CDF fallback.
  See `spectral-profile-edit-footguns` (peak-vs-energy normalization; per-lamp
  A/B across separate processes — `load()` is a process-wide singleton).
- Related device-spectral precedent: `gpu-dielectric-lowers-to-closure-graph`,
  `per-lambda-conductor-thinfilm-equals-rgb-upsample` (RGB↔per-λ deltas can be
  small — measure, don't assume the port is visually large).

---

## Acceptance criteria

- New CPU↔GPU emission-colour parity test (per-channel **mean-ratio**, NOT SSIM —
  independent RNG streams; see `ssim-wrong-gate-for-independent-rng`): a point
  lamp over a diffuse surface, rendered `set_use_gpu(False)` vs `True`, same
  scene/seed/spp. **Every channel within a few % (target ≤5%)** for:
  `led_5000k`, `led_3000k`, `sodium_vapor`, `mercury_vapor`, `cie_f2`, and
  blackbody at 3000 K / 6500 K.
- The loose regression gate shipped with the deviceReference fix is **tightened**
  (or its `xfail`/wide band removed — `xfail-gated-features-must-unxfail`).
- HW-verified on the RTX 5070 Ti (CI has no GPU — `ci_has_no_gpu_runtime_blindspot`);
  visual check that mercury reads blue-green/blue-white and sodium amber-not-red.

## Reference

- Emission model: `include/astroray/emission_spectrum.h` (4 modes), CPU eval
  `src/emission_spectrum.cpp`.
- Device profile-table precedent (pkg54a): `g_profileTable` +
  `gpu_profile_reflectance` + `uploadProfileTable` in
  `src/gpu/gpu_spectral_tables.{h,cu}` and `scene_upload.cu`.
- NEE emission resolve: `src/gpu/gpu_nee.cuh:550-562`. Emissive geometry:
  `include/astroray/gpu_materials.h:3405-3420`; emissive-hit accumulation
  `src/gpu/wavefront/stage_advance.cu:680`.

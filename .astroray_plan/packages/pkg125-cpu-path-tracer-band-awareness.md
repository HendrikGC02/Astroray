# pkg125 — CPU `path_tracer` band awareness (honor `set_wavelength_range`, or reject it loudly)

**Pillar:** 3 (spectral correctness / integrator parity)
**Track:** A (CPU-only reference integrator; runs on CI)
**Codex-paste-ready:** no (a small chip, but it carries one owner-facing design choice — honor vs. reject — that wants a recommendation, not a silent pick)
**Status:** done (PR #499 merged 2026-07-20 — Option A-minimal; CPU `path_tracer` honors `set_wavelength_range`)
**Estimated effort:** S (small — the band-sampling change is a few lines mirroring `multiwavelength_path_tracer`; the larger option (full non-visible NEE reference) is scoped as an explicit stretch, not required)
**Depends on:** none. Independent of the pkg120/122/123/124 chain. Composes with **pkg55 Phase C** (Session C3) — closing this gives the wavefront the band-aware **NEE** CPU reference that C3 recorded as missing.

---

## Context — discovered during pkg55-C3, out of that package's scope

While closing pkg55 Phase C Session C3 (PR #486), the agent re-measured the
multiwavelength paths on a fresh build and corrected a shadow-`.pyd`-contaminated
dossier. The corrected finding
(`.astroray_plan/docs/pkg55-phase-c-plan-2026-07.md` §3, Session C3 status —
"Side finding" and "Coverage gap"):

- The GPU megakernel and the GPU `path_tracer` are **band-aware** (NIR darkens to
  ~1.8e-4, correctly out-of-band-black under D65 gating).
- **The CPU `path_tracer` is NOT band-aware:** it "ignores `wavelength_range`
  (renders NIR as visible RGB, 0.1331)."
- Consequence flagged as a follow-up chip: "**no band-aware NEE CPU reference
  exists** for the wavefront's NEE+luminance+profile-override path — `path_tracer`
  ignores the band, `multiwavelength_path_tracer` is naive [no NEE], and the CPU
  wavefront twin is the RGB Lambertian-Cornell skeleton." C3 explicitly scoped this
  out: "pre-existing CPU-side path_tracer band-unawareness, out of C3 scope."

This package is that follow-up chip.

---

## Root cause (verified in code)

`set_wavelength_range(lambda_min, lambda_max)` stores the band into the integrator
params: `Renderer::setWavelengthRange` sets `integratorParams_["lambda_min"]` /
`["lambda_max"]` (`include/raytracer.h:2160-2162`, bound at
`module/blender_module.cpp:2819`). Only an integrator that **reads those params**
honors the band.

- **`multiwavelength_path_tracer`** reads them —
  `lambdaMin_(p.getFloat("lambda_min", kVisMin))`,
  `lambdaMax_(p.getFloat("lambda_max", kVisMax))`
  (`plugins/integrators/multiwavelength_path_tracer.cpp:44-46`) — and samples
  `SampledWavelengths::sampleUniform(u, lambdaMin_, lambdaMax_)` (`:74-75`), plus
  sets `useLuminanceOutput_` when outside the visible band (`:49`).
- **The CPU `path_tracer`** is `SpectralPathTracer`
  (`plugins/integrators/spectral_path_tracer.cpp`, registered
  `ASTRORAY_REGISTER_INTEGRATOR("path_tracer", SpectralPathTracer)` at `:612`). Its
  render loop samples `SampledWavelengths::sampleUniform(dist01(gen))`
  (`:165-166`) — **no `lambda_min`/`lambda_max` argument**, so it always uses the
  default visible band [`kLambdaMin`, `kLambdaMax`] = [380, 780]
  (`module/blender_module.cpp:3576` confirms the default). It never reads the params
  `set_wavelength_range` wrote. So a user who calls `set_wavelength_range(800, 900)`
  and renders with the default `path_tracer` silently gets a **visible-band render
  mislabeled as NIR** (the measured 0.1331 vs. the correct ~1.8e-4).

The default `SampledWavelengths::sampleUniform(u)` overload defaulting to the
visible band is correct for a visible render; the defect is purely that
`path_tracer` never plumbs the requested band into that call.

---

## Options (present both; recommend one)

**Option A — honor the band (recommended).** Make `SpectralPathTracer` read
`lambda_min`/`lambda_max` from its `ParamDict` (exactly as
`multiwavelength_path_tracer` does) and pass them to `sampleUniform`. This makes the
**NEE + MIS reference integrator** band-aware, which is the piece pkg55-C3 said is
missing: it becomes the band-aware CPU oracle the wavefront's
NEE+luminance+profile-override path can be validated against.

- *Minimal form:* read the two params, thread them into
  `SampledWavelengths::sampleUniform(u, lambdaMin_, lambdaMax_)` at
  `spectral_path_tracer.cpp:165-166`. Out-of-visible wavelengths already resolve
  correctly downstream — materials with a spectral **profile** use it, materials
  without one return 0 outside [380,780] (the honest-black convention already
  implemented in the base material `evalSpectral`, `include/raytracer.h:613-636`),
  and emission/env are D65-gated to zero past 780 nm. So the minimal change is
  genuinely small.
- *Stretch (optional, not required to close the package):* also mirror
  `useLuminanceOutput` (`multiwavelength_path_tracer.cpp:49`) and the Rayleigh-sky
  miss fallback so NIR/UV renders are photometrically presented the same way the
  naive integrator and the wavefront present them. This is the difference between "a
  band-aware NEE reference for parity numbers" (minimal) and "a
  production-quality NIR/UV NEE integrator" (stretch). Recommend shipping minimal
  first; file the stretch as a follow-up if a live NIR-emissive NEE scene is wanted.

**Option B — reject the band loudly.** Keep `path_tracer` visible-only, but when
`lambda_min`/`lambda_max` deviate from the visible band, emit a **loud one-time
warning** ("path_tracer is visible-band only; use multiwavelength_path_tracer for
NIR/UV — the requested [800,900] nm range is ignored, rendering [380,780]").
Cheaper, and honest, but leaves the NEE-band-reference gap open — the wavefront
still has no band-aware NEE CPU oracle.

**Recommendation: Option A (minimal form).** It is barely larger than the warning,
it removes a silent-wrong-output footgun, and it closes the concrete pkg55-C3 gap
(band-aware NEE reference) instead of merely documenting it. Option B is the
fallback only if honoring the band surfaces an unexpected coupling in the NEE path
during implementation; if so, ship B and file A as the follow-up.

---

## Fix plan (cite — no inventions, CLAUDE.md §6)

The reference is **in-tree, same repo**: `multiwavelength_path_tracer.cpp` already
does exactly the band plumbing this package needs. Mirror its param read
(`:44-46`), its `sampleUniform(u, lambdaMin_, lambdaMax_)` call (`:74-75`), and (for
the stretch) its `useLuminanceOutput_` gate (`:49`) into `SpectralPathTracer`
(`spectral_path_tracer.cpp:44-46` constructor region and `:165-166` sampling site).
No external algorithm is involved — this is a plumbing/consistency fix between two
in-repo integrators, so §6 is satisfied by citing the existing
`multiwavelength_path_tracer` as the mirror and the honest-black out-of-band
convention already documented at `include/raytracer.h:613-615`.

### Verification gate

Add a CPU test asserting band awareness on `path_tracer`:

- Render a scene with `set_wavelength_range` set to an NIR band (e.g. [800, 900])
  and assert the out-of-band output is **near-black** (matching the GPU
  `path_tracer`'s measured ~1.8e-4), **not** the visible-RGB 0.1331 it produces
  today. Cross-check against `multiwavelength_path_tracer` on the same scene
  (they should now agree on the band, differing only by NEE presence).
- Visible-band no-regression: a plain visible render is byte-unchanged (the default
  path still samples [380,780]).
- If Option B is chosen instead: assert the warning fires and the render stays
  visible-band.

---

## Acceptance criteria

- [x] `path_tracer` (`SpectralPathTracer`) either **honors** `set_wavelength_range`
      (Option A: reads `lambda_min`/`lambda_max`, samples that band — recommended)
      or **rejects it with a loud warning** (Option B), with the choice recorded.
      **Option A-minimal implemented.**
- [x] Band-awareness test: NIR request renders near-black (not visible-RGB), or (B)
      the warning fires and visible-band is rendered. Cross-checked against
      `multiwavelength_path_tracer`. (`tests/test_pkg125_cpu_path_tracer_band_awareness.py`
      — implemented, not yet run on hardware; no local build available to the
      implementer.)
- [x] Visible-band render byte-unchanged (no regression to the default path).
      Fallback defaults preserved as `astroray::kLambdaMin`/`kLambdaMax` (360/830 nm,
      the actual pre-fix implicit defaults — the spec prose above says "[380, 780]",
      which does not match the real constants in `spectrum.h:26-27`; the
      implementation follows the real constants to guarantee true no-regression).
- [x] If Option A: the out-of-band material convention (profile → profile
      reflectance; no profile → 0) is confirmed to already hold; no new material
      code needed. (Verified: the honest-black outcome for `path_tracer` actually
      comes from `SampledSpectrum::toXYZ`'s CIE CMF projection — `sampleTable()`
      in `src/spectrum.cpp` returns exactly 0 outside [360, 830] — not from the
      `evalSpectralExt`/profile dispatch, which `path_tracer`'s `pathTraceSpectral`
      does not use. No material-side change was needed either way.)
- [x] Signature/call-site sweep: confirm no other caller relied on `path_tracer`
      ignoring the band. (`lambdaMin_`/`lambdaMax_` are private members of a
      single-TU class; constructor signature unchanged; grep swept clean — see PR.)

---

## Non-goals

- **Not the GPU path.** The GPU `path_tracer` is already band-aware (pkg55-C3
  re-measurement); this is CPU-only.
- **Not the wavefront.** Threading the band through the CPU/GPU wavefront twins is
  pkg55 Phase C territory; pkg125 only fixes the megakernel-era CPU reference
  integrator.
- **Not a new spectral pipeline.** Uses the existing `SampledWavelengths`,
  profile-reflectance, and D65-gated emission machinery unchanged.
- **Not the naive `multiwavelength_path_tracer`.** It already honors the band; this
  package brings the **NEE** reference (`path_tracer`) to parity with it, not the
  other way around.
- **Not luminance-output / Rayleigh-sky presentation** in the minimal form — that
  is the explicitly-optional stretch, filed as a follow-up if not shipped here.

---

## Provenance

Filed from the **pkg55 Phase C Session C3 closeout (PR #486, 2026-07-19)**
(`.astroray_plan/docs/pkg55-phase-c-plan-2026-07.md` §3, Session C3 status — the
"Side finding" that re-measured CPU `path_tracer` at NIR = 0.1331 vs the band-aware
GPU ~1.8e-4, and the "Coverage gap (follow-up chip)" noting no band-aware NEE CPU
reference exists). C3 explicitly scoped this out as "pre-existing CPU-side
path_tracer band-unawareness, out of C3 scope." Verified in code:
`spectral_path_tracer.cpp:165-166` samples the default visible band and never reads
the `lambda_min`/`lambda_max` params `set_wavelength_range` writes
(`raytracer.h:2160-2162`), unlike `multiwavelength_path_tracer.cpp:44-46, 74-75`.

---

## Progress

- [x] Decide A vs B (recommend A-minimal); record the choice. **A-minimal chosen**,
      per the spec's own recommendation — no unexpected NEE coupling surfaced.
- [x] Implement the band plumbing (or the loud warning).
      `plugins/integrators/spectral_path_tracer.cpp`: constructor reads
      `lambda_min`/`lambda_max` via `ParamDict::getFloat`, threads them into
      `SampledWavelengths::sampleUniform` at the `sampleFull` call site.
- [x] Band-awareness test + visible-band no-regression.
      `tests/test_pkg125_cpu_path_tracer_band_awareness.py` (4 tests: NIR
      near-black, NIR agreement with `multiwavelength_path_tracer`, default-band
      bit-identity, default-band still non-black sanity check).

---

## Lessons

- The spec's own citation for the "honest black" out-of-band convention
  (`raytracer.h:613-636`, the `evalSpectralExt`/profile-dispatch path) is not
  actually what `path_tracer` uses — `Renderer::pathTraceSpectral` calls the
  base (non-`Ext`) `evalSpectral`/`sampleSpectral`, which have no band gating
  at all. The real mechanism that makes an out-of-visible-band `path_tracer`
  render collapse to near-black is `SampledSpectrum::toXYZ`'s CIE color-matching
  function projection: `sampleTable()` (`src/spectrum.cpp`) returns exactly 0
  for any wavelength outside the baked CMF table's [360, 830] nm support. This
  is arguably more correct for the minimal-form scope (no profile/Ext wiring
  needed at all), but it means the spec's code citation for *why* the fix works
  should be corrected for future readers.
- The spec's default-band prose ("[380, 780]") does not match the actual
  compile-time constants (`kLambdaMin`/`kLambdaMax` = 360/830,
  `spectrum.h:26-27`) that `SampledWavelengths::sampleUniform(u)` used
  implicitly pre-fix. The implementation preserves the REAL constants as the
  `getFloat` fallback so the "byte-unchanged default path" acceptance
  criterion holds against the actual pre-fix binary, not the spec's paraphrase.
- Separately observed (out of scope for this package, noted for a future
  chip): the GPU dispatch path in `module/blender_module.cpp`
  (`cuda_wavefront_render` / megakernel routing) resolves its own
  `lambda_min`/`lambda_max` defaults as 380/780 when unset — a different
  default than the CPU `path_tracer`'s 360/830. This CPU/GPU default-band
  mismatch pre-dates pkg125 and is unaffected by this fix (both sides only
  diverge when the band is left unset, which is not a supported "compare CPU
  vs GPU" configuration in the existing parity tests — they all call
  `set_wavelength_range` explicitly).

# pkg142 — RGB emission convention: RGBIlluminant → RGBUnbounded (Defect 4 adjudication)

**Pillar:** 3 (light transport / emitter energy correctness)
**Track:** A (single cross-cutting convention change with a live headless-Cycles oracle gate + reference-bank re-bless; needs a build + RTX + Blender-5.1, not a mechanical patch)
**Codex-paste-ready:** no (one adjudicated convention flip that cross-cuts CPU/GPU/env/materials and moves the Cycles-parity reference bank; empirical sign/magnitude must be confirmed against a live Cycles A/B, and a fallback branch may be taken — judgment at the gate, not a blind edit)
**Status:** implemented, unverified — PR #511 (2026-07-21) — RGBUnbounded landed repo-wide (CPU `EmissionSpectrum::evalRGB`, GPU `GSPEC_RGB_UNBOUNDED` device mirror, env/world, plus ~20 duplicate CPU emission call sites the spec's grep missed — see PR scope note). Primary/secondary/tertiary gates and reference-bank re-bless NOT run (implementer had no build access) — awaiting team-lead RTX + Blender-5.1 verification.
**Estimated effort:** M (the code change is small and localized; the cost is the build + live-Cycles oracle re-run + RTX GPU==CPU parity + evidence-first reference-bank re-bless)
**Depends on:** pkg122 (PR #500, **merged**) — Defects 1–3 must be in `main` so the residual measured by the oracle is the *clean* emission-lift offset, not confounded by the per-type radiometry bugs. Satisfied.

**Adjudication authority:** owner delegated to the team on 2026-07-21, verbatim:
*"What ever is best and used by other renderers, your call."* Research + adjudication:
`.astroray_plan/docs/defect4-rgb-emission-research.md`.

---

## Context — the last standing piece of the "dimmer/brighter than Cycles" program

pkg122 (PR #500) re-derived the four dedicated-light types' wattage→radiance
against the Cycles kernel and fixed Defects 1–3 (area mixed-measure pdf, point/spot
`1/π`→`1/(4π)`, blackbody photopic normalization). It **deliberately deferred
Defect 4** — the RGB emission-lift convention — because arbitrating it needs a
live-Cycles A/B build (the implementer had no MSVC vcvars) and it moves the
Cycles-calibrated reference bank (was owner-reserved).

With Defects 1–3 landed, the live headless-Cycles oracle
(`scripts/verify_pkg122_cycles_oracle.py`) measures **all four dedicated-light
types 1.07–1.16× brighter than Cycles at equal wattage** on a gray Lambertian
floor. Decoupled pure-Lambertian analytic checks are **0.99×**, so the residual is
**not** radiometry — it is the RGB-emission spectral lift, uniform across all light
types because it lives in the shared `EmissionSpectrum::evalRGB` / albedo pipeline.
The tight Cycles band **[0.97, 1.03] is unreachable until this is resolved.**

---

## Decision (adjudicated)

**Switch the RGB emission lift from `RGBIlluminantSpectrum` (D65-weighted) to
`RGBUnboundedSpectrum` (identity round-trip, no illuminant), on both the CPU
`evalRGB` path and its GPU device mirror.**

### Rationale (full derivation in the research note §2–§4)

- **What the references do.** pbrt-v4 (`SpectrumType::Illuminant` →
  `RGBIlluminantSpectrum`, `src/pbrt/lights.cpp`) and Mitsuba 3 (`srgb_d65`) both
  imprint a **D65 illuminant chromaticity** on RGB lights. **Cycles is RGB-native**:
  `strength` (color × power) is stored as a linear-RGB `float3` and the emitted
  radiance is `strength × eval_fac` — **no spectral upsampling, no D65**
  (`src/scene/light.cpp`, `src/kernel/light/area.h`). pbrt/Mitsuba and Cycles
  **genuinely disagree**, by the spectral-vs-RGB metamerism gap.
- **Which to match.** Astroray's whole quality program is **Cycles parity** — the
  reference bank is Cycles-calibrated, every energy gate is keyed on live-Cycles
  numbers, and the oracle *is* a headless-Cycles A/B. Per the owner directive and
  the parity program, **match Cycles**. `RGBUnbounded` = `scale·sigmoid(rgb/scale)`
  is the **same Jakob-Hanika reflectance-sigmoid family** the floor albedo already
  uses; two same-family spectra multiplied and integrated round-trip to the RGB
  product with minimal crosstalk, reproducing Cycles' `albedo ⊙ light` multiply.
  The D65 tilt on `RGBIlluminant` is exactly the source of the +7–16% offset.
- **Not invented (CLAUDE.md §6).** `RGBUnbounded` is a real pbrt-v4 class
  (`src/pbrt/util/spectrum.h`, Apache-2.0) and **already exists in Astroray**
  (`RGBUnboundedSpectrum`, `src/spectrum.cpp:451-473`). This package re-points the
  emission path at it — no new algorithm.
- **Vindicates pkg89 phase-b.** The 2026-05-21 parity review (Defect 2a) already
  recommended `RGBUnbounded` for emitters; it was over-ridden on a measurement
  confounded by the (now-fixed) Defects 1–3.

### Divergence to document in-code

We deliberately diverge from pbrt-v4/Mitsuba (which keep the D65 illuminant lift
for emitters). A code comment at `evalRGB` must state: *"RGB emission uses the
RGBUnbounded (no-D65) lift to match Cycles' RGB-native light scaling — Astroray's
parity target — rather than the pbrt-v4/Mitsuba RGBIlluminant D65 convention. See
pkg142 / defect4-rgb-emission-research.md."*

---

## Canonical reference (cite in code)

| Concern | File / function | License |
|---|---|---|
| Lift we adopt | pbrt-v4 `RGBUnboundedSpectrum::Sample` (`src/pbrt/util/spectrum.h`) — `scale·rsp(λ)`, no illuminant | Apache-2.0 (verified) |
| Parity target | Cycles `src/scene/light.cpp` (`copy_v3_v3(klight->strength, strength)`), `src/kernel/light/area.h` (`eval_fac = M_1_PI_F·invarea`) — RGB-native, no upsample | Apache-2.0 (verified) |
| In-tree class reused | `astroray::RGBUnboundedSpectrum` (`src/spectrum.cpp:451-473`, `include/astroray/spectrum.h:230`) | project |

License compatibility: both references Apache-2.0, both already relied upon
elsewhere in the tree. No new dependency.

---

## Implementation contract

### CPU
1. `src/emission_spectrum.cpp` `EmissionSpectrum::evalRGB` (lines 187-191): replace
   `RGBIlluminantSpectrum rgbSpectrum(...)` with `RGBUnboundedSpectrum rgbSpectrum(...)`.
   Update the stale block comment (lines 179-186, which argues *for* Illuminant) to
   the divergence note above.
2. **Do not** change `RGBAlbedoSpectrum` (surface reflectance) or the blackbody /
   MeasuredSPD / Composite paths — this is emission-RGB only.

### GPU device mirror (must stay 1:1 with CPU — pkg89 GAP-1 parity is GPU==CPU)
The device lift is `gpu_rgbSpectrumAt` (`include/astroray/gpu_materials.h:90-109`),
selected by a `GSpectralMode`. Today it has `GSPEC_RGB_ILLUMINANT` (scale·JH·D65)
and `GSPEC_RGB_ALBEDO` (JH clamped) but **no UNBOUNDED case**.
3. Add a `GSPEC_RGB_UNBOUNDED` branch to `gpu_rgbSpectrumAt`:
   `scale·gpu_jhEvalSpectrum(normalized, λ)` — identical to the ILLUMINANT branch
   **minus** the `* gpu_sampleD65(λ)` factor. (Add the enum value wherever
   `GSpectralMode` is defined.)
4. Re-point the **emission** call sites from `GSPEC_RGB_ILLUMINANT` to
   `GSPEC_RGB_UNBOUNDED`. Emission sites (grep-confirmed):
   - `src/gpu/gpu_nee.cuh:352-353` (dedicated-light NEE)
   - `src/gpu/path_trace_kernel.cu:549` (mesh emitter `Le`)
   - `src/gpu/multiwavelength_kernel.cu:302` (mesh emitter `Le`)
   - `src/gpu/wavefront/stage_light_sample.cu:151` (wavefront light sample)
   **Scope decision — environment/background:** the env/world color also lifts via
   `GSPEC_RGB_ILLUMINANT` (`gpu_env_spectral.cuh:31,59,80`;
   `path_trace_kernel.cu:437`; `src/lights/background_light.cpp`; CPU
   `background_light.cpp`). The world *is* an emitter, so for internal consistency
   and to keep GPU==CPU, **flip env emission to UNBOUNDED as well** — but this
   widens the reference-bank blast radius (any HDRI/world-lit parity scene). If the
   oracle + refbank evidence shows env parity regresses, the fallback is to keep env
   on ILLUMINANT and flip **only** the dedicated/mesh light paths; record which was
   chosen. Default: flip env too (consistency), verify, pivot on evidence.
5. `EmissionSpectrum::deviceReference` / `src/gpu/scene_upload.cu:194`
   (`g.spectralMode = GSPEC_RGB_ILLUMINANT` for emission): update to the emission
   mode chosen in (4). Keep `GSPEC_RGB_ALBEDO` untouched for reflectance.

### Build (per CLAUDE.md — no "done" without build evidence)
6. Rebuild the CUDA module (`configure_and_build.bat`, `--config Release`; the
   `build_cuda_worktree.bat` Debug footgun is documented in memory). Show `.pyd`
   mtime vs `git log -1 HEAD` and `astroray.__file__` = `build_cuda/Release/` before
   any verification.

---

## Gates (evidence-first — the decision is confirmed by the oracle, not by argument)

**Primary gate — live headless-Cycles A/B oracle.** Copy
`scripts/verify_pkg122_cycles_oracle.py` **into the repo from the `Astroray-pkg122`
worktree** (it currently lives only there — `git add` it under `scripts/`), then run
per type on RTX with Blender 5.1:
```
blender --background --factory-startup --python scripts/verify_pkg122_cycles_oracle.py -- --light-type POINT --out test_results/pkg142
```
for `POINT | AREA | SPOT | SUN`.
- **PASS:** `ratio_astroray_over_cycles` ∈ **[0.97, 1.03]** per channel, all four types.
  (Metric: **per-channel mean-ratio**, NOT SSIM — independent RNG streams make
  windowed SSIM the wrong gate; memory `ssim-wrong-gate-for-independent-rng`.)
- Record before (expect 1.07–1.16) and after for each type/channel.
- Honor the two documented oracle caveats already in the script: SUN camera 5° tilt,
  and the Astroray AREA-light 180°-about-X orientation flip (both are integration
  artifacts orthogonal to this convention — do **not** "fix" them here).

**Secondary gate — GPU==CPU parity.** Re-run the pkg89/pkg122 GPU==CPU dedicated-light
parity check on RTX. The device UNBOUNDED branch must reproduce the CPU `evalRGB`
bit-for-structure (same JH lookup, same scale, D65 dropped on both sides).
Do not run concurrently with another CUDA-heavy verifier (memory
`cuda_verifier_concurrency`).

**Tertiary gate — no radiometry regression.** `tests/test_pkg122_light_energy_calibration.py`
must stay green (this change is chromaticity/level, not per-type geometry).

**Fallback (if the primary gate overshoots to < 0.97, i.e. RGBUnbounded is too dim).**
Do **not** silently retune. Revert `evalRGB` to `RGBIlluminant` and instead add
pbrt's photometric self-normalization `scale /= SpectrumToPhotometric(emit)`
(`src/pbrt/lights.cpp`) — a smaller chromaticity-only correction — and re-run the
oracle. Report which branch landed. (Rationale in research note §5.)

---

## Reference-bank consequence (scoped INTO this package — evidence-first)

Changing the emission lift moves every RGB-emitter scene, so the Cycles-parity
reference bank (**12/13 passing**) may need re-blessing. This is **in scope** and
**capability-available**: Blender 5.1 is installed locally, headless re-bless is
routine (memory `blender-5-1-installed-locally`).

1. **Measure first.** Re-render the parity-bank scenes (and pkg89 G1/G2/G4/G5, the
   pkg115 texture grid) on the new build; diff against the current blessed refs.
   Report per-scene per-channel deltas **before** re-blessing anything.
2. **Re-bless only scenes that move because of this change** and now match Cycles
   *better* (the point of the package). Headless Cycles re-render for the new refs;
   commit refs + a short bless-log noting the measured deltas and that they close
   the +7–16% offset. Scenes expected to move: any using a dedicated light, a
   `diffuse_light` mesh emitter, or (if env flipped) an HDRI/world.
3. If any scene moves the **wrong** way (further from Cycles), stop and report — that
   is a signal to take the env-scope fallback or the photometric-normalization
   fallback above, not to re-bless a regression.

---

## Expected numeric effect

- Dedicated lights (POINT/AREA/SPOT/SUN), equal wattage, gray floor:
  **1.07–1.16× → within [0.97, 1.03]** vs live Cycles (per-channel).
- Pure-Lambertian analytic decoupled check: stays ~0.99× (unaffected — reflectance
  path unchanged).
- Reference bank: 12/13 → re-blessed to reflect the closed offset (target: all
  RGB-emitter parity scenes within band).

---

## Definition of done
- [ ] `evalRGB` + GPU emission mirror on `RGBUnbounded`; stale pro-Illuminant comment replaced with the divergence note + pkg142 cite.
- [ ] `scripts/verify_pkg122_cycles_oracle.py` copied into the repo and committed.
- [ ] Live-Cycles oracle: all four types per-channel ∈ [0.97, 1.03], before/after recorded.
- [ ] GPU==CPU dedicated-light parity re-verified on RTX.
- [ ] `test_pkg122_light_energy_calibration.py` green; build evidence (`.pyd` mtime, `astroray.__file__`) shown.
- [ ] Reference bank re-blessed evidence-first with a measured-delta bless-log; no scene regressed vs Cycles.
- [ ] Which branch landed (primary RGBUnbounded / env-scope choice / photometric fallback) recorded in the PR.

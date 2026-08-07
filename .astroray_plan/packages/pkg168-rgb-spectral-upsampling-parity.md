# pkg168 — CPU↔GPU RGB→spectral upsampling parity: RGBAlbedoSpectrum/RGBIlluminant vs the GPU device tables (owns pkg156's 0.998 restoration)

**Pillar:** 2/3 (spectral core correctness / GPU parity)
**Track:** A (Step 1 is CPU+unit-level and CI-runnable; conviction + fix legs RTX-verified)
**Status:** done (PR #541 merged 2026-08-06, commit bbf2d8c — option A, temp ceiling raise owned by pkg174). **Step 1 (PR #539): tables EXONERATED** — CPU/GPU upsamplers agree to float precision (band-integrated mean ratio 1.000000–1.000004, meanRel 2e-6 albedo / 1e-7 illuminant); evidence `.astroray_plan/docs/pkg168-upsampling-parity-step1.md`. **Step 2 (PR #541): call-structure bug convicted and FIXED**, exactly the fork's second branch: GPU diffuse shaded via `upsample(albedo·cosθ/π)` while CPU does `upsample(albedo)·cosθ/π` — JH upsampling is nonlinear in magnitude, so spectrum SHAPES diverged chroma-dependently (saturated diffuse up to 2.5%/channel; post-fix <0.02%, sphere-isolated per-channel ratios exactly 1.000). Class rule, same as pkg163's: upsample the ASSET; apply scalar transport factors OUTSIDE the upsample. Evidence `.astroray_plan/docs/pkg168-upsampling-parity-step2.md`. **Architect adjudication (2026-08-02) on the headline acceptance item:** the pkg156-scene 0.998 restoration did NOT land here and is REMOVED from this package's definition of done — the decomposition exposed a third, triangle-geometry mechanism (uniform ~0.6% GPU-bright on triangles, achromatic, sphere-clean) that dominates the pkg156 scene. That ownership is TRANSFERRED to **pkg172** (`pkg172-triangle-transport-bias.md`); pkg156's BLOCKED-ON pointer updated accordingly. pkg168's charter (upsampling parity) is complete on its actual scope once #541 merges. **OWNER DECISION on the #541 4-way fork (2026-08-03): option A CONFIRMED** — ship the correctness fix v4 (preserved commit `6ef2c11`), TEMPORARILY raise the wavefront perf ceiling at merge, and file the register-pressure companion package that restores ≤1.0s and reverts the raise — filed as **pkg174** (`pkg174-wavefront-register-pressure-recovery.md`). #541's disposition is therefore: land v4 with the temp ceiling raise in the supervised engine-settlement round (with pkg172(A)); the raise is owned by pkg174 and MUST NOT outlive it.
**Estimated effort:** S (Step 1 unit-level A/B) + S–M for the fix if a table/interpolation divergence is convicted
**Depends on:** PR #537 merged (the pkg120 naive-mode regression fix — pkg156's residual decomposition, this spec's founding evidence, was measured post-#537). Cross-links: **pkg156** (its 0.995→0.998 SSIM restoration is BLOCKED-ON this package), **pkg153** (candidate mechanism for part of its quarantined R-drift — intel relationship, NOT ownership; see Scope fence), **pkg163** (the per-λ-vs-per-RGB class rule; this package is the sibling question — same-color-space legs that should agree but may not).

**Origin:** pkg156 residual decomposition (PR #537 round, 2026-08-02, RTX 5070
Ti). After the pkg120 naive-mode fix, the remaining wavefront visible-naive
divergence is depth-4 GPU/CPU ratio **[1.014, 1.007, 1.014]**, SSIM 0.9955 vs
the aspirational 0.998, channel-asymmetric. Controls that pin it on upsampling:
black background renders identically black on both legs (zero transport from
the light quad — transport structure agrees); a neutral-grey background still
shows the channel-asymmetric ratio. Conclusion: the gap sits where both legs
convert RGB assets to spectra — CPU `RGBAlbedoSpectrum`/`RGBIlluminant`
(Jakob-Hanika) vs the GPU device-side tables (`gpu_rgbToSampledSpectrum`).

Corroborating anchor (pkg153 spec, post-#523 data point): a materials-eval PR
moved the quarantined env-scene R ratio by +3.8 pp with the CPU oracle
unchanged — independent evidence that a GPU material/spectral-eval arc carries
a systematic channel-ordered offset.

---

## Step 1 — decisive unit-level A/B (blocking; no renders)

Both legs claim the same Jakob-Hanika construction. Compare them directly, off
the render path:

1. Dump the CPU side: `RGBAlbedoSpectrum(rgb).sample(lambdas)` and the
   illuminant twin, over a grid of rgb values (include the pkg156 scene's
   actual albedos + primaries + neutral greys) × a dense lambda grid.
2. Dump the GPU side: `gpu_rgbToSampledSpectrum` (and any illuminant-path twin)
   on the SAME (rgb, lambda) grid via a debug binding/kernel (pattern:
   `eval_texture_at_3d` from pkg115, `debug_bsdf_*_batch` from pkg121).
3. Report max/mean per-λ relative error per rgb point, and the per-channel
   structure after integrating against the sensor curves (does the unit-level
   error reproduce the [1.014, 1.007, 1.014] R>G>B≈R signature?).

**Fork:**
- **Divergence found at unit level → convict the source** (table resolution,
  interpolation order, coefficient-fetch quantization, float precision,
  illuminant normalization — enumerate, don't guess) and fix so both legs
  sample the SAME tables the same way. Cite Jakob & Hanika 2019 ("A Low-
  Dimensional Function Space for Efficient Spectral Upsampling") and the
  in-repo canonical implementation; no new algorithm (CLAUDE.md §6).
- **Unit-level parity clean → the gap is in the CALL structure**, not the
  tables (the two legs upsample at different points/frequencies along a path,
  e.g. per-hit vs cached, sum-then-upsample vs upsample-then-sum — the pkg163
  class rule says those do not commute). Localize with the pkg55 per-bounce
  snapshot harness (capture moment pinned at spec time per memory
  `wavefront-snapshot-semantics-class-of-bug`: capture IMMEDIATELY after the
  throughput×albedo update at each bounce, both legs) and re-scope the fix to
  the convicted call site.

## Acceptance

- [ ] Step-1 table published in the research note
      (`.astroray_plan/docs/pkg168-upsampling-parity-step1.md`) with the fork
      verdict and the convicted mechanism.
- [ ] Fix mirrored CPU/GPU (whichever side is wrong moves — determined by the
      conviction, not by "CPU is oracle" reflex; if the CPU side is the
      inaccurate one, that is an owner decision point, precedent pkg160).
- [ ] **pkg156's scene: depth-4 GPU/CPU per-channel ratio within ±0.5% and
      SSIM ≥ 0.998 measured in the fix PR** — restoring pkg156's gate to 0.998
      lands here (or in an immediate follow-up commit with the measurement);
      that is this package's headline definition of done.
- [ ] Report the effect on pkg153's three quarantined env-scene ratios (same
      scene family, before/after) — **as bisect intel for pkg153, which keeps
      gate ownership**. Do not touch those gates here.
- [ ] Standard suites green; any energy-relevant gate runs linear with
      floor+ceiling (pkg166 rules).

## Scope fence

- **pkg153's gates stay pkg153's.** This package is a candidate mechanism for
  PART of the R-drift (the emitter-linked ~4.6 pp discriminator suggests a
  separate co-mechanism in the light-energy arc); pkg153's bisect contract is
  unchanged and consumes this package's result as an anchor. If this fix lands
  and the quarantined ratios move to green, pkg153 closes via its own
  disposition — not silently here.
- Not the emitter wattage→radiance calibration (pkg122 family).
- No gate-band or SSIM-pin changes outside the two named above (pkg156's 0.998
  restoration with measurement; nothing else).

## Provenance

Filed by the architect 2026-08-02 from pkg156's residual decomposition
(PR #537 round) at team-lead request: pkg153 is disposition-only by its own
contract ("if a real regression: file a targeted fix spec"), pkg156 owns a
gate re-pin but not a spectral-core fix — so the upsampling-parity fix had no
owner. pkg156's Status carries the matching BLOCKED-ON marker.

# pkg140 — DistantLight angular_diameter≈0 renders pure black (delta-sun semantics + small-angle cancellation)

**Pillar:** 3 (light transport correctness)
**Track:** A (CPU light code + GPU mirror; CPU-gated tests on CI, GPU leg RTX-verified)
**Codex-paste-ready:** no (delta-light semantics touch sampling, pdf, power-CDF selection, and the light-tree orientation cone together — the pieces must stay consistent)
**Status:** open — dispatchable now (small, engine lane, independent of everything in flight)
**Estimated effort:** S–M (a delta branch mirroring pbrt-v4 + a two-character numerical identity in four sites + the GPU mirror; the care is in keeping sampleLi/pdfLi/power/cone consistent)
**Depends on:** none. Do NOT conflate with pkg122 (energy calibration, in flight) — this is a zero-measure/degenerate-geometry bug, not a scaling bug.

---

## Context — found by the pkg122 hardware verifier (2026-07-20 overnight)

Sweep on both CPU and GPU (identical behavior, evidence in
`Astroray-pkg122/test_results/`):

- `angular_diameter = 0.0` rad → **pure black**
- `angular_diameter = 0.00017` rad → **pure black**
- `angular_diameter = 0.00175` rad and above → correct (~0.99× analytic)

Blender's default sun angle is 0.526°, so realistic scenes never hit this, but
it is a correctness hole for the true-delta sun case (and any tiny-angle sun an
astro scene might legitimately want — e.g. a star at astronomical distance).

## Root cause (verified in code — `src/lights/distant_light.cpp`)

All four sites compute `solidAngle = 2π(1 − cos(halfAngle))` and degenerate
together as `halfAngle → 0`:

1. **`sampleLi` (`:73-75`):** `sample.pdf = 1/solidAngle` → **+inf** at 0 ⇒
   contribution `emission/pdf` = 0. (Note: the direction itself is fine — the
   `angularDiameter_ > 0` guard at `:36` correctly falls back to the exact
   `-axis_` direction; only the pdf is wrong.)
2. **`pdfLi` (`:78-82`):** same `1/solidAngle` → inf.
3. **`power` (`:84-93`):** returns `luminance · intensity · normalizeFactor ·
   solidAngle` → **0** ⇒ the power-CDF light selection gives the light zero
   probability — it is never sampled at all (sufficient for black on its own).
4. **`orientationCone` (`:101-104`):** `fromAxisAngle(-axis_, 0)` — a
   zero-extent cone for the light tree.

**Why 0.00017 rad is ALSO black (float cancellation):** `1.0f − cosf(h)`
suffers catastrophic cancellation: `cos(h) ≈ 1 − h²/2`, and for
`h²/2 < ~6e-8` (i.e. `h ≲ 3.4e-4` rad) `cosf(h)` rounds to exactly `1.0f`, so
`solidAngle == 0.0f` even for a nonzero angle. The sweep matches: diameter
0.00017 (half-angle 8.5e-5) is inside the cancellation zone; 0.00175
(half-angle 8.75e-4, `1−cos ≈ 3.8e-7`) is just outside and renders correctly.

The GPU mirrors the same radiometry (`:106-112`,
`out.cosOuter = cos(angularDiameter_ · 0.5)`) — the device disk pdf has the
same `1 − cosOuter` cancellation, consistent with the verifier's
CPU-and-GPU-identically-black observation.

## Fix plan (cite — no inventions, CLAUDE.md §6)

**A. Small-angle numerical stability (all sites, CPU + GPU).** Replace
`1 − cos(h)` with the identity `2·sin²(h/2)` (exact, and `sinf` has no
cancellation at small arguments). Textbook identity (trivial per CLAUDE.md §6);
this alone fixes the 0 < angle ≲ 7e-4 rad zone in `sampleLi`, `pdfLi`,
`power`, and the GPU `cosOuter`-derived pdf (mirror with
`sinf(h*0.5f)`-based solid angle or equivalent).

**B. True-delta branch for `angular_diameter == 0` — mirror pbrt-v4
`DistantLight`** (`pbrt-v4 src/pbrt/lights.h/.cpp`, Apache-2.0):

- `SampleLi`: fixed direction `-axis_`, **pdf = 1** (delta convention — the
  1-sample estimator divides by 1, contribution is the full radiance; pbrt-v4
  `DistantLight::SampleLi` returns `wi` with `pdf = 1`).
- `PDF_Li`: **return 0** (a delta direction can never be hit by BSDF/solid-angle
  sampling; pbrt-v4 `DistantLight::PDF_Li` returns 0). This also makes the MIS
  weight for the NEE sample come out 1, which is correct for a delta light.
- `power`: must be **nonzero** or the power-CDF starves the light (site 3
  above). pbrt-v4 uses `Phi = π · sceneRadius² · L`; adapt to our selection-CDF
  convention (`luminance · intensity · normalizeFactor · <delta-power
  convention>`) — the absolute scale only matters relative to other lights in
  the CDF, but document the chosen convention and keep it consistent with the
  finite-angle limit (no discontinuity as angle → 0⁺ after fix A: consider
  `max(solidAngle, delta_floor)` vs the pbrt scene-radius form and record the
  choice with the citation).
- `orientationCone`: a zero-`halfAngle` cone about `-axis_` is legitimate for
  the light tree (a delta emitter emits in exactly one direction); verify the
  light-tree importance math does not divide by the cone extent — if it does,
  clamp per the existing light-tree conventions (`pkg86` code) and record it.
- Check `isDelta`/delta-flag plumbing: if `LiSample`/NEE has a delta-light flag
  (as the BSDF side does), set it so MIS treats the sample as delta; if it does
  not exist, the pdf=1/PDF_Li=0 pair achieves the same estimator — do not
  invent new plumbing unless a gate fails without it.

## Verification gates

- [ ] Sweep test (CPU): `angular_diameter ∈ {0.0, 1.7e-4, 1.75e-3, 0.00918
      (Blender default)}` — all render within ~1–2% of the analytic
      direct-lighting value (the 0.99× band the verifier measured for the
      working case); 0.0 and 1.7e-4 are the regression rows (both black today).
- [ ] GPU leg matches CPU at the 1e-5 Monte-Carlo convention on the same sweep
      (RTX-verified — CI is GPU-blind).
- [ ] Continuity: no brightness jump between the delta branch (0.0) and the
      smallest finite angle (1.7e-4) beyond MC noise.
- [ ] Existing sun/distant-light tests + pkg89 parity gates stay green
      (Blender-default 0.526° behavior byte-unchanged is the no-regression
      anchor).
- [ ] Light-selection check: a scene with a delta sun + one area light — both
      contribute (the power-CDF starvation row).

## Non-goals

- **Not energy calibration** (pkg122, in flight — including its blackbody/sun
  magnitudes; this package must not touch `normalizeFactor_` conventions
  beyond the delta-power choice, and must rebase cleanly on pkg122's changes).
- **Not the light tree generally** — only the degenerate-cone interaction if a
  gate exposes it.
- **Not Blender addon changes** — the addon already passes the angle through
  (`__init__.py:3941-3946`).

## Provenance

Filed from the **pkg122 hardware-verifier findings (2026-07-20 overnight)**:
angle sweep 0.0/0.00017 → black, 0.00175+ → ~0.99× analytic, CPU and GPU
identical; evidence in `Astroray-pkg122/test_results/`. Mechanism verified in
code by the architect: `src/lights/distant_light.cpp:73-75, 78-82, 84-93,
101-104` all share the `2π(1−cos(halfAngle))` form (pdf→inf, power→0), and the
float cancellation zone `h ≲ 3.4e-4` rad explains the nonzero-but-black row.
GPU mirror at `:106-112` (`cosOuter`).

## Progress

- [ ] A — `2sin²(h/2)` identity in all CPU sites + GPU mirror.
- [ ] B — delta branch (sampleLi pdf=1, pdfLi=0, nonzero delta power,
      cone/flag audit) with pbrt-v4 citations.
- [ ] Sweep + continuity + selection gates (CPU CI + RTX GPU leg).

## Lessons

*(Fill in after the package is done.)*

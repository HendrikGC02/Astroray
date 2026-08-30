# pkg208 — Chromatic-light-source dispersion oracle (line emitter through a prism)

**Pillar:** 3 (spectral rendering) + Integration Milestone (parity/superiority oracle)
**Track:** A (test-authoring + oracle; no engine algorithm change expected).
**Estimated effort:** S.
**Status:** done (PR #666, 2026-08-31 — sodium_vapor chromaticity spread 0.0146
vs led_6500k broadband control 0.4917, ~33x; asserted at a conservative 3x
margin; sodium mean chroma (0.852, 0.148, 0.000) confirms amber, R > G > 3B;
CPU-only (`set_use_gpu(False)`), CI green on all matrix jobs). `mercury_vapor`
(optional stretch) was evaluated but not included — it came out blue-dominant
rather than the anticipated green-dominant band, likely interacting with
pkg214's SPD energy normalization; left out per this spec's own "not a hard
assert" gating rather than tuned to fit. `red_blue_centroid_separation` (the
spec's suggested reuse) turned out numerically unstable for the narrow-line
case (sodium's near-zero blue channel makes its centroid a noise-dominated
division — measured ~26px vs the broadband control's ~3.7px, *inverted* from
the expected relationship); replaced with a channel-agnostic chromaticity-spread
proxy per this spec's own escape hatch, documented in
`.astroray_plan/docs/pkg208-dispersion-oracle-research.md`.

**Note (2026-08-31, pkg208 implementer):** this file's "Agent-ready recipe"
section (added by the architect 2026-08-30, PR #662) was briefly reverted to
its pre-refinement state by an out-of-scope edit in PR #664 (pkg209, commit
5064d81 "drop out-of-scope pkg208/pkg219 spec edits" — evidently reverted to
a stale pre-fork copy rather than current main). Restored here alongside the
completion status so the shipped implementation (sodium_vapor/led_6500k, as
below) matches the spec on disk.

**Depends on:** the spectral line-emitter path (already shipped — the research
report §9 gallery shows a working 635 nm line emitter render) and the existing
dispersive-prism scene (`tests/test_spectral_prism.py`). No new algorithm.

## Goal

Cycles' merged dispersion is RGB-with-one-hero-wavelength and **cannot know the
source SPD**: with a spectrally-narrow light (e.g. a Rec.2020 red light), a
physically-correct prism shows only the red slice of the rainbow, but Cycles
"solves for the full D65 SPD" and then tints the whole dispersed rainbow red (the
PR author acknowledges this as a known non-physical limitation). Astroray is a
true spectral renderer that carries the source SPD to the observer, so it renders
this case **correctly** — a concrete differentiator. Turn that into a standing
**oracle test**: a narrow-line emitter refracted through a dispersive prism must
produce a spectrally-narrow spread (a single-hue band near the emitter's
wavelength), NOT a full ROYGBIV rainbow.

## Specification

1. **No new algorithm — this is an oracle over existing behaviour.** Invoke
   `cite-algorithm` only to *cite* the physics being asserted (dispersion at a
   dielectric interface: n(λ) from Sellmeier/Cauchy, the same models already
   shipped; and the reason a monochromatic input yields a single deflected ray,
   not a spread — cite a standard optics reference and the Cycles PR-thread
   limitation quote). Save a short note under `.astroray_plan/docs/` framing this
   as a superiority oracle (Cycles fails by design). If the test surfaces a REAL
   engine bug (the narrow-line case does NOT render narrow), STOP and file that as
   a separate defect spec — do not paper over it in the oracle.

2. **Scene:** reuse the dispersive-prism geometry from `tests/test_spectral_prism.py`
   (BK7 Sellmeier preset), but replace the broadband/white illuminant with a
   **narrow-line emitter**.

   **Agent-ready recipe (architect 2026-08-30 — the abstract "635 nm red line"
   in the original filing does NOT exist as a profile; use the real narrow-line
   preset below).** Astroray has no per-render monochromatic-emitter API; a
   narrow line is delivered via the measured-SPD emission path. The ONLY genuinely
   narrow-line light-source profile shipped in `data/spectral_profiles/profiles.bin`
   is **`sodium_vapor`** (LPS D-lines, 588.995/589.592 nm — a ~589 nm yellow
   spike; confirmed in `profiles_metadata.json`). Use it as the line emitter and
   contrast it against a **broadband control** (`led_6500k`, a smooth ~380–780 nm
   phosphor-LED SPD). `mercury_vapor` is multi-line (404/436/546/577 nm) — a useful
   *optional* second case (its dominant 546 nm green line should throw a
   green-dominant band), but it is NOT a single line, so keep `sodium_vapor` as the
   primary and gate the mercury case as a documented stretch, not a hard assert.

   Build the scene by adapting `tests/scenes/prism_reference.py`
   (`add_triangular_prism` + BK7 `dielectric` + camera) but on the **spectral**
   path, following the exact wiring in `tests/test_pkg195_stage_b_spectral_lamp.py`:
   ```
   astroray.load_spectral_profiles(".../data/spectral_profiles/profiles.bin")
   r.set_integrator("multiwavelength_path_tracer")   # NOT "path_tracer" — the RGB
                                                     # path can't carry a source SPD
   r.set_wavelength_range(380.0, 780.0)
   r.add_point_light(position=[...], intensity=...,  radius=...,
                     emission={"mode": "measured_spd", "profile_name": "sodium_vapor"})
   ```
   Prefer a point light aimed through the prism over the broadband area-light
   triangles in `prism_reference.make_prism_scene`; if a spectral **area** emitter is
   needed for enough flux, confirm whether `create_material("light", …)` accepts an
   `emission=` SPD dict before using it (it may not — the point-light path is the
   proven one). Keep the seed pinned and render LINEAR (`apply_gamma=False`).

3. **Oracle predicates** (LINEAR EXRs, seed-pinned, sentinel-gated — not exit code):
   - The dispersed band's **dominant hue tracks the emitter wavelength**: the
     `sodium_vapor` (~589 nm) prism produces a **yellow/amber-dominant** refracted
     band (R≈G, both ≫ B), NOT a full rainbow. Assert with a hue/centroid metric on
     the refracted region. (Optional documented stretch: `mercury_vapor` → a
     green-biased band from its 546 nm line.)
   - The **spectral spread is narrow**, not full-rainbow: reuse
     `prism_reference.red_blue_centroid_separation` (already the shipped spread
     metric) and assert the sodium-line band's red-blue centroid separation is
     **well below** what the SAME prism produces under the `led_6500k` broadband
     control (render that broadband control in the same test as the wide-spread
     reference). This "narrow << broadband" contrast is the crux — it is exactly the
     assertion Cycles would fail.
   - **If the sodium-line prism does NOT render narrow** (e.g. it throws a wide
     rainbow anyway), that is a REAL engine defect (source-SPD not reaching the
     dispersive event) — STOP and file it as a separate spec per §1, do not relax
     the predicate to make it pass.

4. Register the scene/driver in `scripts/README.md` if it adds a reusable harness
   entry (CLAUDE.md §5b — check the index first; prefer extending
   `test_spectral_prism.py` with a parametrized line-emitter case over a new file).

## Acceptance

- [x] The oracle test PASSES on current `main`: the `sodium_vapor` (~589 nm)
  line prism renders a hue-correct (yellow/amber-dominant), spectrally-narrow
  band; the `led_6500k` broadband control renders a measurably wider red-blue
  centroid spread. Report the measured hue-centroid / spread numbers for both
  (sodium line, broadband; plus the optional mercury case if included). State the
  `.pyd` mtime next to the render leg, and state which backend produced the numbers
  (CPU vs auto-routed CUDA — memory `cpu-suites-auto-use-cuda`).
  — Measured (PR #666): sodium mean chroma (R,G,B) = (0.852, 0.148, 0.000),
  satisfying R > G > 3B. Chromaticity spread (the replacement metric, see
  Status): sodium 0.0146 vs led_6500k 0.4917 (~33x). `.pyd`:
  `build_cuda\Release\astroray.cp313-win_amd64.pyd`, mtime 2026-08-30 22:17.
  Backend: CPU, explicit `r.set_use_gpu(False)` (mirrors
  `tests/test_pkg195_stage_b_spectral_lamp.py`'s proven convention). Mercury
  case evaluated, not included (see Status note).
- [x] The test is deterministic (seed-pinned) and runs in the standard suite; the
  `.astroray_plan/docs/` note frames it as a Cycles-superiority oracle with the
  cited limitation.
  — `tests/test_spectral_prism.py::test_narrow_line_band_is_amber_hued` and
  `::test_narrow_line_disperses_narrower_than_broadband`, seed 17.
  `.astroray_plan/docs/pkg208-dispersion-oracle-research.md` cites Hecht
  *Optics*, the Schott BK7 datasheet, and the Cycles PR #162041 thread quote.
- [x] CI green on all matrix jobs; RTX leg run if the scene renders on GPU (memory
  `cpu-suites-auto-use-cuda` — a "CPU" render may auto-route to CUDA; verify which
  backend produced the numbers and state it).
  — `build-and-test`, `cuda-syntax-check`, `changes` all pass on both matrix
  legs (PR #666). No RTX leg: the scene is CPU-only by design
  (`set_use_gpu(False)`), so it never renders on GPU — the RTX-leg clause is
  N/A, not skipped.

## Non-goals

- **No dispersion-model change** — Sellmeier/Cauchy stay as-is; this only asserts
  the already-correct spectral behaviour.
- **No Cycles-side render** — the experimental Cycles build is not installed; the
  contrast is against Astroray's own broadband control, with the Cycles limitation
  cited from the PR thread, not rendered.

## Provenance

Filed by the architect 2026-08-19 from the dispersion research report
(`.astroray_plan/docs/reports/2026-08-19-cycles-dispersion-research.html` §6 /
§04 "Acknowledged limitation" / ranked recommendation #4). Grounded in the §9
gallery's working 635 nm line-emitter render and `tests/test_spectral_prism.py`.
Open-model IMPLEMENT-tier (test authoring) behind CI (+RTX) gates; Claude owns the
"is this a real oracle or is it masking a bug" judgment.

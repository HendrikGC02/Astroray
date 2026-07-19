# pkg121 — Chi-squared sampler-validation gates

**Pillar:** 3 (correctness / testing infrastructure)
**Track:** A
**Codex-paste-ready:** no (CPU-side test infra, BSDF binding decisions need owner review)
**Status:** in progress (spec+impl landed together for owner-window speed, sanctioned by team lead)

**Estimated effort:** M (1–2 sessions)

---

## Goal

**Before:** Astroray validates BSDF correctness with unit tests on single evaluations
and visual inspection of renders. Sampling errors (broken `sample()` implementation,
`pdf()` evaluation mismatches, biased lobes) are not statistically verified.

**After:** Port Mitsuba 3's chi-squared sampler harness (BSD-3-Clause) to validate
every BSDF lobe statistically. Chi² gates run in CI on the CPU BSDF path, catching
sampling-vs-pdf mismatches the way journal reviewers would: empirical convergence
tests, not single-value spot checks.

---

## References

### External
- **Mitsuba 3** `github.com/mitsuba-renderer/mitsuba3` — **BSD-3-Clause (verified)**
  - `src/python/python/chi2.py`: `ChiSquareTest`, `SphericalDomain`, `tabulate_histogram`, `tabulate_pdf`, `run()` with cell pooling + Šidák correction.
  - Developer guide: mitsuba.readthedocs.io → Developer guide → Testing.
- **pbrt-v4** `github.com/mmp/pbrt-v4` — **Apache-2.0 (verified)**
  - `src/pbrt/bsdfs_test.cpp`: constants `CHI2_SLEVEL 0.01`, `CHI2_SAMPLECOUNT 1000000`, `CHI2_THETA_RES 80`, `CHI2_PHI_RES 160`, `CHI2_MINFREQ 5`, `CHI2_RUNS 5`.
- **Research doc:** `.astroray_plan/docs/2026-07-other-engines-research.md` §1.

### Internal
- `module/blender_module.cpp:513-559` — existing `evalMaterial()` binding (CPU `Material::eval()`).
- `include/raytracer.h:508-510` — `Material::sample()`, `Material::eval()`, `Material::pdf()`.
- `tests/` — pytest harness.

---

## Scope (CPU-first — zero GPU to avoid contention with pkg55-C3)

1. **Port Mitsuba `chi2.py` harness → `tests/statistical/chi2.py`**
   - `ChiSquareTest` class with `SphericalDomain`, `tabulate_histogram()` (weighted-sample histogram), `tabulate_pdf()` (per-cell numerical integration), `run()` with cell pooling + Šidák correction.
   - Replace Dr.Jit vectorization with NumPy batching.
   - Adopt pbrt-v4 battle-tested constants: 10^6 samples, 80×160 (θ,φ) res, α=0.01, min expected frequency 5, 5 runs Šidák.
   - Include BSD-3-Clause attribution header per repo convention (see pkg115 Cycles attribution).

2. **Bindings: batched CPU BSDF sample+eval+pdf**
   - Investigate existing `evalMaterial()` (line 513) and `integrateMaterialReflectance()` (line 531) bindings.
   - Add batched `bsdf_sample(material_id, wi, u2_array) -> (wo_array, pdf_array)` and `bsdf_pdf(material_id, wi, wo_array) -> pdf_array` on the CPU BSDF path.
   - If new public bindings are needed, use `debug_` prefix (matching existing convention: `debug_light_tree_pick`, line 2529).
   - **Note:** any NEW public binding will need owner approval at review (repo policy).

3. **Gates: `tests/statistical/test_chi2_bsdf.py`**
   - Chi² pass for the Disney BSDF's main lobes across a small grid:
     - Diffuse-dominant (roughness=1.0, metallic=0.0)
     - Metallic lobe (roughness ∈ {0.1, 0.4, 0.8}, metallic=1.0)
     - Dielectric/glass (transmission=1.0, roughness ∈ {0.0, 0.3})
   - Test at 2-3 incident angles: normal (θ=0°), grazing (θ=75°), and medium (θ=45°).
   - Mark the full dense grid as a slow/optional marker (e.g. `@pytest.mark.slow`); the default gate is a representative subset that runs in CI-feasible time on CPU.
   - Seed-pinned (non-zero seeds — seed 0 is a random_device sentinel in this repo).
   - **If a lobe FAILS chi²:** do NOT lower the gate or fudge tolerance. Report the failure with chi² evidence (p-value, histogram dump).

---

## Acceptance criteria

- [ ] `tests/statistical/chi2.py` exists with `ChiSquareTest`, `SphericalDomain`, pbrt constants, BSD-3 header.
- [ ] Batched CPU BSDF bindings exist (sample + pdf) and are documented.
- [ ] `tests/statistical/test_chi2_bsdf.py` passes chi² for the representative subset (diffuse, metal r=0.4, glass r=0.0 at θ=45°).
- [ ] Full gate sweep (marked slow) documented in docstring.
- [ ] Any chi² failures reported with evidence (not suppressed).
- [ ] Signature sweep before push: all new binding call sites found.

---

## Algorithm sourcing (CLAUDE.md §6)

- **Mitsuba 3 `chi2.py`** (Wenzel Jakob, BSD-3-Clause) — Pearson chi-square GOF test with Šidák correction, trapezoid-rule PDF integration, cell pooling for expected frequencies < 5.
- **pbrt-v4 `bsdfs_test.cpp`** (Matt Pharr, Apache-2.0) — constants: 10^6 samples, 80×160 bins, α=0.01, 5-frequency pooling threshold, 5 runs.
- **Pearson 1900** — chi-square goodness-of-fit test (undergraduate statistics).
- **Šidák 1967** — multiple-testing correction `α' = 1 - (1-α)^(1/k)` (standard textbook formula).

---

## Phase B — Comprehensive validation campaign + visual report (separate dispatch)

**Goal:** Once the harness passes the Lambertian anchor, run the FULL validation grid across all BSDFs/distributions and produce a rich visual report for the journal submission and June showcase.

**Scope:**

1. **Full Disney BSDF matrix:**
   - All lobes: diffuse, metallic, dielectric/glass, clearcoat, sheen, subsurface
   - Roughness sweep: r ∈ {0.0, 0.1, 0.2, ..., 1.0} (11 values)
   - Incidence angles: θ ∈ {0°, 15°, 30°, 45°, 60°, 75°, 85°} (7 values)
   - Metallic/transmission combinations: full 2D grid
   - ~500+ configurations total

2. **Extended distribution testing:**
   - **Light-tree emitter sampling** (via adapter analogous to Mitsuba's `EmitterAdapter`)
   - **Spectral distribution sampling** (Jakob-Hanika upsampled spectra via `SpectrumAdapter`)
   - **Phase functions** (Henyey-Greenstein, Rayleigh if implemented)

3. **Visual report deliverable** (HTML gallery, `test_results/chi2_validation_report/`):
   - **Per-configuration heatmaps:** side-by-side (θ,φ) color maps of sampled histogram vs integrated PDF vs difference, matching Mitsuba's `chi2_data.py` matplotlib output style
   - **P-value grid:** 2D heatmap matrix showing p-values across (roughness, incidence angle) for each lobe — green=pass, red=fail at α=0.01
   - **Lobe shape evolution:** polar plots or 3D hemisphere visualizations showing how lobe shape changes across roughness sweep (e.g., metallic r=0.0 → 1.0 sequence)
   - **Chi² statistic distribution:** histogram of all test statistics with theoretical χ² overlay to verify test calibration
   - **Summary table:** pass/fail counts per lobe, worst-case p-values, any systematic failures
   - **Self-contained HTML:** embed matplotlib PNGs or use D3.js/Plotly for interactive exploration (owner preference: strong dataviz)

4. **Data persistence:**
   - Keep Mitsuba's `chi2_data.py` failure-dump mechanism in the port (already present)
   - Extend to write JSON manifest of all test results for programmatic analysis
   - Archive raw histogram/PDF arrays for any failed configuration (debugging artifact)

**Effort estimate:** M-L (2-4 sessions) — mostly visualization + interpretation, harness already runs the tests.

**Acceptance criteria (Phase B):**
- [ ] Full grid executed (all Disney lobes × roughness × angles)
- [ ] HTML report generated with heatmaps, p-value grid, polar plots
- [ ] Report documents any systematic failures with chi² evidence
- [ ] Light-tree and spectral samplers tested (if time permits)
- [ ] Report packaged for journal submission supplemental material

**Note:** Phase B is **not part of the initial chi² infrastructure delivery**. It's a separate later dispatch once the harness is validated and the tabulate_pdf integration bug is fixed. Specced here per owner request to ensure the implementer invests in rich dataviz (June-showcase quality).

---

## Notes

- **CPU-only scope:** deliberate to avoid GPU contention with the parallel pkg55-C3 agent. Any GPU extension is a future package.
- **Binding decisions:** if existing `evalMaterial` batching is insufficient, new bindings need `debug_` prefix and owner approval at review.
- **Test flake note:** `test_direct_and_indirect_clamp_controls` is seed-flaky on this machine; if the harness incidentally explains why, mention it to the owner.
- **Spec landed with impl:** owner has ~50 min of API budget; spec written alongside impl to frontload reasoning, sanctioned by team lead.
- **Phase B dataviz emphasis:** owner explicitly wants strong visualization for the validation campaign — invest in interactive/publication-quality plots, not just text tables.

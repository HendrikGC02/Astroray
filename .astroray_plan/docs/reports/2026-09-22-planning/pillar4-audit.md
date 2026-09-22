# Pillar 4 spec audit — 2026-09-22 (read-only)

Scope: pkg45/46/48/49/50/51/107 (paused specs) vs. what landed since 2026-06.
North star doc: `.astroray_plan/docs/north-star-and-integration-gate-2026-09-07.md` explicitly
freezes these packages until the exit gate is met (§1 item 1, §3 "does NOT qualify" list).
No unpause signal found anywhere in STATUS.md/ROADMAP.md as of 2026-09-22.

---

## 1. PAUSED specs — status, scope, staleness

### pkg45 — CLOUDY emissivity tables
- Status: paused (owner 2026-06-08). Track B, Python-only, ~3h. No deps.
- Scope: Python preprocessing (`pyCloudy`) generates a 4D `j_ν(ρ,T,U,λ)` lookup table →
  `data/emissivity/hii_emissivity.bin` + metadata JSON. Feeds pkg46.
- Assumes: nothing engine-side; pure offline data-gen script + binary loader format.
- Files: none of the 5 owned files exist yet (`scripts/generate_cloudy_tables.py`,
  `scripts/cloudy_table_format.md`, `data/emissivity/*`, `tests/test_cloudy_tables.py`) — not started.
- Staleness: low direct risk (self-contained format spec), but the spec predates the
  **spectral pipeline + CIE 1931 2° observer fix (#837, PR merged 2026-09-20)**. Any rewrite
  must specify the emissivity table's wavelength grid against the *current* hero-wavelength /
  spectral upsampling convention, not an assumed RGB or arbitrary λ grid. Also predates
  op-VM (pkg230) — if HII emission is meant to be wireable as a shader node later, the table
  sampler should be an op-VM opcode candidate, not hardcoded C++.

### pkg46 — HII Region Emission Plugin
- Status: paused. Track B, ~5h. Depends on pkg42 (done), pkg45 (not started).
- Scope: `plugins/emission/hii_region.cpp` + `include/astroray/emissivity_table.h`, samples
  the pkg45 table per-voxel for Hα/Hβ/[OIII]/[NII] line emission; wires into addon + module.
- Assumes: `EmissionRegistry`/`ASTRORAY_REGISTER_EMISSION` (reserved by pkg42, landed), a
  volumetric density field to sample against.
- Files: none of the 8 owned files exist (`plugins/emission/hii_region.cpp` missing).
- STALENESS — concrete rewrite items:
  1. **Volume architecture changed underneath it.** pkg267-272 (all done, PRs #810/#820/#838,
     Sept 2026) landed `GridMedium`, NanoVDB grids, delta/ratio tracking, volume NEE, and
     spectral-Planck volume emission (pkg270) as the actual volumetric emission path. The
     spec's "each phenomenon is a self-contained plugin sampling a density field" model
     predates this and must be rewritten to plug into `GridMedium`/the Principled-Volume
     emission path instead of inventing a parallel volumetric sampler.
  2. **Emission-line spectral realism**: pkg270 already does spectral-Planck emission with
     per-λ σ; pkg46 should reuse that machinery (deposit line intensity as spectral spikes on
     the existing wavelength-sampling machinery) rather than an RGB line-ratio approximation.
  3. GitHub issue **#144** (open, P1-high) — "spectral nebula emission and reflection media" —
     substantially overlaps pkg46's scope (emission-line volumes + dust scattering) and should
     be reconciled/merged into one spec, not left as two independent trackers.
  4. Depends on op-VM (pkg230, done) for any shader-graph-exposed controls — the 2026-06 spec
     predates op-VM entirely.

### pkg48 — HDF5 & NumPy Simulation Data Loader
- Status: paused. Track B, ~4h. Depends on pkg04 (done), pkg47-fits-loader (done).
- Scope: `SimulationVolume` plugin loads yt-preprocessed `.npy` density/temperature grids and
  HDF5 via HighFive into a `DensityGrid` struct (`include/astroray/density_grid.h`).
- Files: none of the 10 owned files exist. `include/astroray/density_grid.h` missing.
- STALENESS — major:
  1. **The whole premise of a bespoke `DensityGrid`/`SimulationVolume` plugin is now
     redundant with the landed volumes track.** pkg267 (done) added NanoVDB `GridMedium` +
     Blender-native OpenVDB import (owner 2026-09-13 decision: "use Blender's native OpenVDB
     for now" — addon reads `.vdb` via Blender 5.2's bundled `openvdb` module, no engine-side
     `.vdb` reader). A pkg48 rewrite must decide: (a) retire the bespoke HDF5/numpy→DensityGrid
     path and instead document "preprocess simulation → `.vdb` → Blender native import" as the
     supported route, keeping only a thin numpy→VDB *conversion script*, or (b) keep a native
     `.npy`/HDF5 reader only for cases VDB can't represent (irregular AMR, particle data)
     with an explicit rationale. As written today it duplicates machinery that already exists.
  2. Owner directive 2026-09-11: "volume rendering is not a Pillar-4-exclusive... core part of
     any rendering engine" — the volumes track was deliberately pulled out of Pillar 4 and
     shipped early; pkg48 needs to explicitly reference pkg267-272 as prerequisites/superseding
     infrastructure, not treat them as unrelated.

### pkg49 — SPH-to-Volume Conversion
- Status: paused. Track B, ~3h. Depends on pkg48 (not started).
- Scope: Wendland C4 kernel splat of SPH particle data onto a grid (`sph_to_grid.cpp`,
  `sph_kernel.h`, `scripts/sph_to_npy.py`).
- Files: none of the 7 owned files exist.
- Staleness: inherits pkg48's problem — if pkg48 is rewritten to target `.vdb` output instead
  of a bespoke `DensityGrid`, pkg49's "SPH → `.npy` → SimulationVolume" pipeline must target
  "SPH → `.vdb` → Blender OpenVDB import" instead. CLAUDE.md §6 (no invented algorithms) is
  already satisfied — Wendland C4 + Shepard normalization are cited (Monaghan 1992, Westover
  1990 per `pillar4-data-io-research.md`) — that part of the spec survives a rewrite.

### pkg50 — Weak Gravitational Lensing
- Status: paused. Track A (uses GR machinery), ~3h. Depends on pkg06 (unlisted here, assume
  done), pkg40-kerr-metric (done).
- Scope: screen-space deflection pass (`plugins/passes/weak_lensing.cpp`) integrating lensing
  deflection along camera rays and offsetting background samples; cheaper than full GR tracing.
- Files: none of the 7 owned files exist.
- STALENESS:
  1. Predates the **op-VM / GPU wavefront reality**: this is specified as a CPU-only
     screen-space pass (`plugins/passes/`). Given the north star's GPU-first, viewport-first
     mandate and that GPU wavefront (pkg131 adaptive, pkg86 light tree, pkg225 hair, etc.) is
     now the primary render path, a rewrite must specify whether this pass is CPU-only
     (acceptable, cheap) or needs a GPU wavefront stage — currently unstated.
  2. No interaction with the landed spectral pipeline is specified — lensing deflection is
     achromatic in the current spec (fine physically for weak lensing) but should say so
     explicitly given how central spectral correctness now is to the codebase's identity.
  3. Otherwise architecturally sound and small; lowest staleness risk of the GR-adjacent specs.

### pkg51 — Synthetic Telescope Observations
- Status: paused. Track B, ~4h. Depends on pkg06, pkg47-fits-loader (done).
- Scope: post-process pass (`plugins/passes/telescope.cpp`) — wavelength-dependent PSF (FFT
  convolution against a WebbPSF-generated FITS cube) + Gaussian/Poisson/dark-current noise.
- Files: none of the 8 owned files exist.
- STALENESS — significant, this is the biggest rewrite candidate:
  1. **"Wavelength-dependent PSF" now has real machinery to hook into that didn't exist in
     2026-06**: the spectral pipeline (hero-wavelength sampling, CIE 1931 2° observer #837),
     band output provenance (pkg243, still "open — needs architect review", NOT landed) and
     SRF spectral sensors (pkg133, **paused**, not pkg51-blocking-only anymore — north-star §3
     lists pkg133 as depending on pkg51 and both are frozen together). A rewrite should design
     pkg51 and pkg133 as one coherent instrument-pipeline spec (detector QE × filter curve ×
     PSF × noise), since they're sequential stages of the same signal chain and were clearly
     drifting toward duplication.
  2. North star explicitly forbids "calibrated-SI/absolute-radiometric claims" until an
     instrument model exists (§1 item 4) — pkg51's noise model (CCD gain, read noise in e⁻,
     exposure time) is exactly an absolute-radiometric instrument claim. A rewrite must gate
     pkg51 behind pkg243 (raw relative band output + honest provenance) landing first, and
     state that dependency explicitly (currently pkg51 only depends on pkg06/pkg47).

### pkg107 — Parameterize BlackHole `r_obs_M`
- Status: paused. Track A, ~3h, no deps. Small, surgical: expose `r_obs_M` as a constructor/
  Python-binding parameter instead of a hardcoded constant in `include/astroray/black_hole.h`
  and `module/blender_module.cpp::PyRenderer::addBlackHole`.
- Files: `include/astroray/black_hole.h` and `plugins/shapes/black_hole.cpp` both exist (BH
  code has landed via pkg40/42/43/44/99/105) — this is a small parameterization change on top
  of live code, not greenfield.
- Staleness: **lowest of all seven** — no architecture changed underneath it; the observer-
  distance constant is presumably still hardcoded. Cheapest to thaw first if/when Pillar 4
  resumes. Worth an owner ping to confirm it's still wanted as scoped (½ day) rather than
  folded into a broader GR-parameter-exposure pass alongside pkg105's addon panel.

---

## 2. LANDED pre-pause groundwork

| pkg | What exists (files) | Reachable from addon | GPU | Known bugs/limits |
|---|---|---|---|---|
| pkg40 Kerr metric | `plugins/metrics/kerr.cpp`, `plugins/metrics/schwarzschild.cpp`, `include/astroray/metric.h`, `plugins/shapes/black_hole.cpp` (gr_metric.h from the spec was NOT created as a separate file — metric machinery lives in `metric.h`) | Yes, via pkg105 | CPU-only GR integration (spec explicitly calls for double-precision integrator; no CUDA GR path found) | — |
| pkg41 Kerr validation | `tests/test_kerr_validation.py`, GYOTO cross-check references (`tests/reference/kerr/gyoto_a*.png`) | n/a (test-only) | n/a | — |
| pkg42 Synchrotron/jets | `plugins/emission/synchrotron.cpp`, `include/astroray/emission.h` | Yes | Pandya 2016 fits; `EmissionRegistry` established | — |
| pkg43 Slim disk | `plugins/accretion/slim_disk.cpp` | Yes | — | T(9M,mdot=1)=7.45e6K matches Page-Thorne 1974 + Sadowski 2009 (PR #271); 14/14 tests |
| pkg44 ADAF | `plugins/accretion/adaf.cpp` | Yes, via pkg105 | — | **pkg99 fix (PR #335, done)**: removed spurious `exposureScale` mult from volumetric emission (`black_hole.h:362-364`); jet intensity_scale rescaled 1e28→5e13; empirical RTX visual tuning flagged as a *separate, apparently never-done* follow-up — visual quality of the ADAF glow is unverified beyond "should now produce visible glow" |
| pkg47 FITS loader | `include/astroray/fits_io.h`, `plugins/data/fits_loader.cpp` | FITSTexture plugin only; **FITSVolume registration deferred to pkg48**, which is paused — so FITS *volume* loading (as opposed to texture) is incomplete and blocked on a frozen package | n/a (I/O) | CMake gate `ASTRORAY_ENABLE_FITS` |
| pkg67 metric-aware tracer | `include/astroray/metric.h`, `include/astroray/gr_integrator.h`, `plugins/integrators/path_tracer.cpp` | Yes | CPU | **Spec deviation (documented, not a bug)**: literal spec called for a scene-level `GRMetric`/`Renderer::metric_` with per-step virtual dispatch; actual implementation (Option α) instead routes via `BlackHole::isGRObject()` per-object dispatch, runs geodesic integration once per ray segment inside `traceGR*`, and adds `MinkowskiMetric` only for registry symmetry (never invoked on the production flat-space path). Any Pillar-4 rewrite referencing "the metric interface" must use this per-BH-object model, not the spec's literal class diagram. |
| pkg99 ADAF glow fix | `include/astroray/adaf.h`, test/scene changes | Yes | — | done 2026-05-22; empirical RTX visual tuning still open per the package's own note |
| pkg105 Addon BH integration | `blender_addon/__init__.py`, `settings_map.py` (no separate `nodes/black_hole_panel.py` — spec's file layout wasn't followed, functionality folded into the existing addon panel/settings map instead) | Yes — "Pillar 4 Blender surface complete for BH objects" (STATUS.md 2026-05-28) | — | r_obs_M, Kerr spin, ADAF params exposed |

**Does the GR/black-hole path still render?** No fresh evidence found. Last recorded artifact:
STATUS.md 2026-06 closeout — "Reference bank: 12/13 scenes PASS (**GR Kerr 4/4, Schwarzschild
3/3, ADAF 4/4**...)" against `benchmarks/reference_bank/scenes/{gr-kerr-94-faceon,
gr-schwarzschild,adaf-sgrA-faceon}`. Nothing newer references these scenes by name in
STATUS.md's tail. Owner decision **2026-09-19 night** (memory + north-star §7) explicitly asks
for "one black-hole scene if the GR path still renders" as a low-priority README showcase item
— phrased conditionally, implying the owner does *not* currently know/trust that it still
renders after ~3 months of engine churn (spectral pipeline, CIE observer fix, volumes track,
op-VM, wavefront changes) that never re-touched the GR code path. **Recommend a cheap
CPU-only regression run of the three reference-bank GR scenes before any Pillar-4 rewrite
work starts**, since none of the intervening ~300 PRs appear to have exercised this path.

---

## 3. Design docs — architecture summary + contradictions

- **`astrophysics.md`** (209 lines, the Pillar 4 master design doc): defines `GRMetric`
  interface, accretion plugin pattern, synchrotron physics, HII/CLOUDY pipeline, FITS/HDF5/SPH
  import, weak/strong lensing, telescope postprocess. Explicitly out of scope: full numerical
  relativity, full MHD, instrument-calibrated PSFs. **Contradiction with current engine**: §4.5
  describes `SimulationVolume` loading raw `.npy` as the volume-import story; the engine's
  actual, later-landed volume story is Blender-native OpenVDB import (pkg267, owner-decided
  2026-09-13). The doc was never updated to reflect this and should be revised before any pkg48
  rewrite is scoped from it.
- **`pillar4-data-io-research.md`** (491 lines): converges FITS/HDF5/SPH loaders on a common
  `DensityGrid` struct (`include/astroray/density_grid.h`: flat array + nx/ny/nz + bbox +
  field_name) feeding a `SimulationVolume` plugin. Dated 2026-05-10, marked implementation-
  ready pending Windows dependency verification (cfitsio/HighFive). Does not anticipate NanoVDB/
  `GridMedium` at all — same contradiction as above, compounded: two different "volume ingest"
  architectures now exist in doc form (this one, and the landed VDB one), and only the landed
  one has code.
- **`accretion-emission-research.md`** (674 lines): the strongest of the six docs — defines one
  shared radiative-transfer pipeline (plasma state → fluid-frame frequency → synchrotron j_ν/
  α_ν → dI_inv/dλ step with automatic GR redshift, no separate Doppler-boost multiply) that
  pkg42/43/44 all implement. Cites Pandya et al. 2016, Sądowski 2009, Yuan & Narayan 2014;
  cross-validates against ipole (BSD-3) and RAPTOR (GPL, numbers-only). Test scenes A/B/C
  (flat-space plasma sphere → Schwarzschild+slim-disk → Kerr a=0.9+ADAF headline image) map
  directly to the reference-bank scenes cited above. No contradiction found with landed code —
  this is the one Pillar-4 doc that stayed in sync with what shipped, likely because pkg42/43/
  44/99 all landed and closed the loop.
- **`kerr-metric-research.md` + `metric-aware-tracer-research.md`** (279+365 lines): Kerr in
  Boyer-Lindquist with analytic Christoffel symbols, Dormand-Prince RK4/5, ISCO/photon-sphere/
  frame-dragging validation vs Bardeen-Press-Teukolsky 1972. The tracer-unification doc's own
  "Realized architecture" section already documents the Option-α deviation from its own literal
  spec (see §2 pkg67 row above) — this is a doc that correctly self-corrected, a good model for
  how the paused specs should be rewritten (mark deviations explicitly rather than silently).
- **`atomic-line-broadening-research.md`** (119 lines, pkg214 — not in the audited paused set,
  but overlaps pkg46's line-emission need): Gaussian Doppler line profile, FWHM=15nm matched to
  the renderer's 5nm spectral grid (not physical ~0.1nm linewidth), lines merge when closer than
  FWHM. Directly relevant prior art for pkg46's HII line emission — a rewrite of pkg46 should
  reuse this line-deposition convention rather than reinventing one.
- **Issue #144** (open, P1-high, "spectral nebula emission and reflection media"): asks for
  emission-line + dust-scattering volume presets with procedural density variation — this is
  pkg46's scope restated as a GitHub issue independently of the package spec. Should be merged
  into pkg46's rewrite (one spec, cross-referenced, not two trackers for the same feature).
- **Issue #141** (open, P1-high, "diffraction grating / spectral mirror BSDF"): wavelength-
  dependent diffraction orders, no Pillar-4 package currently owns this — see gap list below.

---

## 4. Gaps — north-star science targets with NO package

North star §1: "nebulae, HMXBs, accretion flows, relativistic lensing... instrument-like
observables, photon counts." Cross-referenced against all pkg40-51/99/105/107/130/133/243 etc.:

- **HMXBs (High-Mass X-ray Binaries)** — named explicitly in the north star as a target science
  case. **No package anywhere** covers binary orbital dynamics, X-ray emission from a compact
  companion, or Roche-lobe overflow accretion (Eggleton 1983 is cited in `astrophysics.md`'s
  references list but never turned into a package). pkg43/44 (slim disk/ADAF) give the
  accretion-disk emission physics an HMXB package could reuse, but no spec ties them to a
  binary system.
- **Photon counts / instrument-like observables as a first-class output** — pkg51 (telescope
  postprocess) and pkg133 (SRF sensors) are the closest, but both are frozen and neither
  produces literal photon-count statistics (Poisson noise in pkg51 is additive on a radiance
  image, not a photon-counting detector model). pkg243 (raw band provenance, open/science-lane,
  not frozen) is the actual prerequisite infrastructure but doesn't itself produce photon counts.
- **Diffraction grating / spectral mirror BSDF** (issue #141) — no package; would be a Pillar-4-
  adjacent BSDF, not currently tracked as a `pkgNN`.
- **Relativistic lensing beyond the BH itself** (galaxy-cluster-scale, non-BH lensing) — pkg50
  covers weak lensing generically and mentions "strong lensing inherits from Kerr machinery, no
  extra package" but no package exists for cluster-mass NFW-profile lensing specifically named
  in `astrophysics.md` §4.6 (`plugins/lensing/cluster.cpp` is unowned by any package).

---

## 5. Final table

| package | keep / rewrite / merge / retire | one-line reason |
|---|---|---|
| pkg45 (CLOUDY tables) | keep, minor rewrite | self-contained, low staleness; just re-anchor wavelength grid to CIE 1931 2° / spectral pipeline conventions |
| pkg46 (HII region) | **merge + rewrite** | merge with issue #144; rewrite to sample the landed `GridMedium`/pkg270 spectral-emission path instead of a bespoke density-field sampler |
| pkg48 (HDF5/NumPy loader) | **rewrite** | volumes track (pkg267) shipped a competing, owner-endorsed OpenVDB-native ingest path; decide retire-vs-narrow-scope before touching code |
| pkg49 (SPH-to-volume) | rewrite (follows pkg48) | target `.vdb` output, not the pkg48 `DensityGrid`, once pkg48 is resolved; kernel math itself still valid |
| pkg50 (weak lensing) | keep, minor rewrite | smallest staleness; clarify CPU-only vs GPU-wavefront placement |
| pkg51 (telescope postprocess) | **merge + rewrite** | merge with pkg133 (SRF sensors) into one instrument-pipeline spec; must explicitly depend on pkg243 (no absolute-radiometric claims until it lands) |
| pkg107 (r_obs_M param) | keep as-is | smallest, most concrete, no architecture drift — cheapest to thaw first |
| pkg40/41/42/43/44/47/67/99/105 | keep (already landed) | done; pkg47 has one loose end (FITSVolume registration stuck behind frozen pkg48) |
| N/A — HMXB package | **new spec needed** | named in north star, zero coverage; natural follow-on to pkg43/44 |
| N/A — diffraction grating BSDF (#141) | **new spec needed** | named in north star region (instrument-like observables / spectral realism), zero coverage |
| N/A — cluster/NFW strong lensing | **new spec needed** | named in `astrophysics.md` §4.6, explicitly unowned (`plugins/lensing/cluster.cpp` has no package) |

---

## What's missing from this audit (budget-bounded, ~38 tool calls used)

- Did not independently re-run any GR reference-bank scene (explicitly out of scope — "do NOT
  run GPU tests"; even a CPU run was skipped to stay in budget — flagged as the top recommended
  next action above).
- Did not verify pkg06/pkg34/pkg54/pkg58/pkg39/pkg125 (unlisted dependency packages referenced
  by pkg50/pkg51/pkg243) beyond trusting `deps`/`whatis` output.
- Did not check `CHANGELOG.md` directly for GR-path mentions beyond STATUS.md search.
- pkg214 (atomic line broadening) status (implemented vs still-pending) not fully confirmed —
  research doc says "no blocking issues, implementation plan ready" but did not check if code
  landed; relevant only as prior art for pkg46, not itself in the audited PAUSED set.

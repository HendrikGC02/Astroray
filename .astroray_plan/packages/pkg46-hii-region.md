# pkg46 — HII Region Emission and Reflection Media (merged with #144)

**Pillar:** 4
**Track:** B
**Status:** paused — Pillar 4 (Stage 2, Track N); merged with #144 and rewritten 2026-09-22
**Estimated effort:** 3 sessions (~9 h), two phases
**Depends on:** pkg45, pkg243, pkg267, pkg270

---

## Goal

**Before:** Astroray can transport heterogeneous volumes (pkg267–271) and emit a
spectral Planck continuum from them (pkg270), but it cannot emit atomic lines.
The pkg45 CLOUDY tables exist but no code reads them, and there is no way to feed
per-voxel n_e / T_e / ionisation fields into an emitter.

**After:** Line emission is evaluated inside the existing volume transport:
per-voxel n_e, T_e and ionisation come from `set_volume_grid` arrays or VDB
grids; each line is looked up in the pkg45 table and deposited through the
`GridMedium` / pkg270 spectral-accumulation path with an unbiased
hero-wavelength MIS estimator. Phase 2 adds dust scattering (reflection nebulae,
#144). A Principled-Volume-driven preset renders the result from Blender with no
new UI.

**First measurable deliverable:** the measured quantity is **integrated energy
radiance per line** — the line's total power per unit area per solid angle
[erg s⁻¹ cm⁻² sr⁻¹], integrated over its profile; not photon counts, RGB
values, or a spectral peak height. A dust-free Case-B hydrogen slab at
T_e = 10⁴ K, n_e = 100 cm⁻³ renders an integrated Hα/Hβ = 2.86 within 2 % of the
pinned pkg45 table row for that grid point (Osterbrock & Ferland 2006 Table 4.2;
Storey & Hummer 1995), with stated MC uncertainty, and Hα line radiance scaling
linearly with path length. The Case-B assumption is Lyman lines optically thick
(trapped) and Balmer lines optically thin; linear path-length scaling holds in
that optically-thin Balmer regime.

---

## Context

Line-dominated nebulae are the natural showcase for the spectral renderer: a few
discrete wavelengths carry the colour. Issue #144 asks for emission and
reflection nebula media; this spec merges it into the existing volume lane
instead of a parallel emitter.

The previous pkg46 text assumed its own sampler, its own `VolumetricEmission`
interface (pkg42), and an unvalidated table. The engine has since landed
`GridMedium` traversal (pkg267), delta/ratio tracking + volume NEE (pkg268–269,
271) and spectral Planck emission (pkg270); reuse is the smallest correct path.
Without this, Pillar 4 Track N has no physical line source and the pkg45 tables
stay unused.

---

## Evidence

- 2026-09-22: rewritten in the planning session (stage-plan-2026-09-22.md §4); previous text superseded.
- 2026-09-22: Astra turn-2 review amendments applied (planning session).

---

## Reference

- Design: `.astroray_plan/docs/astrophysics.md §4.4`;
  stage plan `.astroray_plan/docs/stage-plan-2026-09-22.md §4` (Track N)
- Line-profile convention: `.astroray_plan/docs/atomic-line-broadening-research.md`;
  ingest `.astroray_plan/docs/pillar4-data-io-research.md`; sibling GR emission
  conventions `.astroray_plan/docs/accretion-emission-research.md`
- Engine: `include/astroray/volume/grid_medium.h`,
  `include/astroray/volume/volume_transport.h`,
  `include/astroray/volume/volume_emission.h`
- pkg45 table: `scripts/cloudy_table_format.md`, `data/emissivity/hii_emissivity.bin`
- Sampling: pkg206 (luminance hero-λ, `src/spectrum.cpp`); pkg221
  (`.astroray_plan/packages/pkg221-photon-wavelength-spd-importance-sampling.md`)
- External: Wilkie et al. 2014 (hero-wavelength spectral sampling, CGF 33(4),
  EGSR); Armstrong 1967 (JQSRT 7, 61); Osterbrock & Ferland 2006 (Table 4.2);
  Storey & Hummer 1995 (MNRAS 272, 41); Case-B benchmark A&A 2021 (aa40890-21);
  Henyey & Greenstein 1941 (ApJ 93, 70); Draine 2003 (ARA&A 41, 241); issue #144

---

## Prerequisites

- [ ] pkg45 is done: `data/emissivity/hii_emissivity.bin` + metadata committed.
- [ ] pkg267/pkg268 are done: `GridMedium` + delta/ratio tracking (landed).
- [ ] pkg270 is done: per-λ spectral volume emission (landed).
- [ ] pkg243 is open: raw band output + provenance, needed to measure Hα/Hβ
      honestly (this package consumes it, it is not blocked by it).
- [ ] Build passes on main.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `include/astroray/emissivity_table.h` | pkg45 binary-table loader + trilinear (n_e, T_e, log U) interpolation; validates magic/dims against the metadata JSON. |
| `include/astroray/volume/hii_emission.h` | `HIILineEmission`: per-voxel (n_e, T_e, log U) → summed line radiance at λ; line-mixture pdf + energy normalisation. |
| `src/volume/hii_emission.cpp` | Table lookup, Gaussian line profiles, line-mixture pdf construction, MIS support. |
| `tests/test_pkg46_hii_line_emission.py` | Case-B slab ratio, path-length linearity, energy conservation, MIS unbiasedness. |
| `tests/scenes/hii_caseb_slab.py` | Case-B hydrogen slab scene (T_e = 10⁴ K, n_e = 100 cm⁻³). |

### Files to modify

| File | What changes |
|---|---|
| `include/astroray/volume/volume_emission.h` | Add the optional HII line term alongside the constant/blackbody terms. |
| `include/astroray/volume/volume_transport.h` | Evaluate the line term in `emissionAt` at the tracking vertices using the per-voxel fields. |
| `module/blender_module.cpp` | Extend `set_volume_grid` with an optional ionisation-fraction grid and the HII emission params. |
| `blender_addon/exporter.py` | Map the Principled-Volume-driven nebula preset to `set_volume_grid`; no new UI. |
| `CHANGELOG.md` | pkg46 entry. |
| `.astroray_plan/docs/STATUS.md` | Mark pkg46 done at close. |

### Key design decisions

Two phases. Phase 1 is emission-only and is the bounded, testable core; Phase 2
adds dust. Both ride the existing `GridMedium` traversal and the pkg270
accumulation — no parallel ray marcher, no runtime CLOUDY.

#### Line sampling

Narrow lines are missed by the luminance-weighted hero-λ proposal (pkg206,
`SampledWavelengths::sampleImportance`, `src/spectrum.cpp`): Hα's physical width
is ~0.1 nm against the engine grid. Deposit each line as an energy-normalised
Gaussian whose FWHM is matched to the spectral grid, not to the physical
linewidth, following the `_atomic_lines` convention in
`atomic-line-broadening-research.md` (Gaussian = Doppler limit of the Voigt
profile; Armstrong 1967). The line's *area* is the table intensity, so total
power is conserved regardless of the numerical width.

Sampling λ ∝ luminance alone is therefore low-efficiency for line light. Use
multiple importance sampling (balance heuristic) between:

- `p_λ(λ)`: the current hero-wavelength proposal pdf (pkg206), and
- `p_line(λ)`: a mixture over the pkg45 lines, weight ∝ line intensity × its
  Gaussian profile, sampled by picking a line then sampling its profile.

Each contribution is weighted by `p_λ/(p_λ + p_line)` (and the mirror term),
with both pdfs in closed form. This is the hero-wavelength spectral-MIS
construction of Wilkie et al. 2014 and follows the SPD importance-sampling
weight of pkg221. `p_line` is built once per medium from the table; per-voxel
n_e / T_e / log U modulate the mixture weights, not the sampling support.
Unbiasedness is demonstrated by a test, not assumed: a broad flat spectral
response function (uniform-wavelength render) and the MIS render agree within MC noise.

#### Phase 1 emission-only

Optically thin line emission: recombination / collisional emissivities from the
pkg45 table, accumulated along the `GridMedium` traversal exactly like the
pkg270 Planck term (per-unit-length radiance at the tracking vertices). Per-voxel
fields: n_e from the density grid × `density_scale`, T_e from the existing
temperature grid, log U from a new optional ionisation grid (dense array via
`set_volume_grid` or a VDB attribute). Missing grids fall back to scene-level
scalars.

No ionisation solver and no runtime CLOUDY: the fields are inputs and the table
is the physics. Line list and wavelengths: Hα 656.3, Hβ 486.1, Hγ 434.0,
[OIII] 495.9/500.7, [NII] 654.8/658.3, [SII] 671.6 nm (pkg45).

#### Phase 2 dust scattering / reflection nebula

#144's reflection media: add dust extinction and anisotropic scattering to the
same traversal, so a nebula can both emit lines and scatter a nearby star's
light. Scattering reuses the existing `anisotropy` (Henyey-Greenstein 1941)
term; an optional Draine 2003 grain phase function may replace it later. Dust
albedo / extinction are scene inputs — no dust microphysics model. Phase 2 also
delivers #144's diagnostic: a contact-sheet of volume tiles across preset
parameters.

#### Blender surface

No new UI. The addon grows one named preset, "Emission Nebula", that maps a
Principled Volume (or a VDB) onto `set_volume_grid`: the density grid is n_e,
the temperature grid is T_e, plus the optional ionisation attribute and the HII
line strength. Emission colour/strength stay the Principled Volume sockets.
Preset logic lives in `blender_addon/exporter.py`; the user drives it from the
existing volume material, exactly as the pkg270 blackbody path is driven today.

---

## Acceptance criteria

- [ ] First science figure: dust-free Case-B slab (T_e = 10⁴ K, n_e = 100 cm⁻³)
      renders integrated (profile-integrated) energy-radiance Hα/Hβ against the
      pinned pkg45 table row (Storey & Hummer 1995 Case B; ≈ 2.86) — the
      tabulated row for that grid point, not a universal constant. The 2 % is an
      engineering budget: require ≥ 5 seeds and a 95 % confidence interval fully
      inside the ±2 % tolerance.
- [ ] Independent single-line normalisation: for a homogeneous slab of thickness
      L, rendered line radiance equals I_line = j_line · L / (4π), with j_line
      [erg s⁻¹ cm⁻³] the un-normalised line-integrated emissivity; pkg45 stores
      its 4π-normalised form j_line/(4π) [erg s⁻¹ cm⁻³ sr⁻¹]. Catches a missing
      4π or density factor that cancels in the Hα/Hβ ratio.
- [ ] Hα line power scales linearly with slab path length (≤ 2 % residual).
- [ ] Energy conservation: integrated emitted line power equals table
      j × voxel volume within MC noise (floor and ceiling both asserted, linear
      render — see `AGENTS.md` §Furnace/energy tests).
- [ ] Line-sampling estimator is unbiased: identity of the mean under
      luminance-only vs MIS sampling, with lower variance under MIS.
- [ ] Hα/Hβ measured through the pkg243 band output, with provenance recorded.
- [ ] `EmissivityTable` loads `hii_emissivity.bin` and interpolates known grid
      values to the documented tolerance.
- [ ] ≥8 tests cover loading, interpolation, line-profile area, line ratio,
      path-length linearity, energy conservation, MIS unbiasedness, finite
      output.
- [ ] All existing tests pass.

---

## Non-goals

- Do not implement an ionisation/recombination equilibrium solver at runtime.
- Do not run or link CLOUDY at runtime (GPL; pkg45 precomputes the table).
- Do not add a GPU leg in Phase 1 (CPU oracle first; GPU is a follow-up).
- No new Blender UI panel or object type — a preset on the existing volume
  material only.
- Do not model velocity fields or Doppler shifts; lines are at rest-frame λ.
- Do not implement planetary nebulae, HMXB/X-ray microphysics, grating (#141) or
  cluster lensing — those stay deferred candidates.
- Do not add hydrodynamics.

---

## Progress

- [ ] Phase 1: `EmissivityTable` loader + interpolation.
- [ ] Phase 1: `HIILineEmission` evaluator, Gaussian profiles, line-mixture pdf.
- [ ] Phase 1: wire the line term into `VolumeEmission`/`emissionAt` and
      `set_volume_grid` (ionisation grid).
- [ ] Phase 1: Case-B slab scene + Hα/Hβ, path-length and energy tests.
- [ ] Phase 1: Blender preset in `exporter.py`.
- [ ] Phase 2: dust extinction + anisotropic scattering + contact-sheet tiles.
- [ ] Full suite green; update `CHANGELOG.md`, `.astroray_plan/docs/STATUS.md`.

---

## Lessons

*(Fill in after the package is done.)*

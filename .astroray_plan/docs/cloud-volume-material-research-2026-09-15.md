# Cloud-volume material — research note, 2026-09-15 (horizon item, pkg273)

Architect goal-capture for the owner remark of 2026-09-15: a dedicated,
spectral material for physically based cloud VDBs (cumulus / stratus / cirrus /
mixed-phase) produced by the owner's separate cloud-simulation project. Horizon
item: nothing here is scheduled until that simulation is complete. The package
spec is `.astroray_plan/packages/pkg273-cloud-volume-material.md`
(`Status: paused`).

Every citation below names the primary source and, where code would be
mirrored, the licence. "unverified" marks anything I could not check directly
today.

---

## For the owner

Your cloud sim's physical fields (LWC, IWC, N or r_eff, T) are exactly what a
spectral cloud material needs, and the engine's volume track (pkg267–271) is
building the right substrate: NanoVDB grids, null-collision tracking, per-λ σ
via spectral tracking, spectral Planck emission, and a Nishita sky that is
already computed per wavelength internally. What a *cloud* material adds on top
of Principled Volume is (1) coefficients derived from physics instead of an
artist "density" — σ_t(λ) = 3·LWC/(2·ρ_w·r_eff) to a few percent in the visible,
exact tables from Lorenz–Mie when r_eff ≲ 5 λ or absorption matters; (2) a
tabulated, importance-sampled Mie phase function per (r_eff, v_eff, λ) that
reproduces the fogbow (~138–140°), the glory, the corona and the correct
silver-lining width — none of which Henyey–Greenstein can produce; (3) an
ice-habit path using the Yang et al. 2013 / Baum et al. 2014 bulk databases
(CC-BY-4.0) instead of spheres. The honest caveats: in Astroray's current
360–830 nm band water droplets are near-perfect conservative scatterers
(1 − ω0 ~ 1e-7..1e-5), so the "spectral" payoff in the visible is in the phase
function and the illumination, not in extinction; the big spectral extinction
story (1.6 / 2.1 / 3.7 µm bands used for r_eff retrieval) only arrives when the
engine band widens. A path tracer will be an unbiased reference for clouds but
slow: τ = 20–100 clouds need hundreds to thousands of scattering events per path
(Kallweit et al. 2017), so a multi-scatter accelerator (pkg272 fork) becomes a
real need rather than a nicety. Spec filed as pkg273 (paused) with a proposed
VDB grid contract for your sim to export; three questions for you are at the end
of this note.

---

## 0. Scope and where it sits in Astroray

- **Substrate (exists / in flight):** `GridMedium` NanoVDB grid + majorant
  (pkg267, done); delta/ratio tracking, HG phase, Principled Volume σ mapping,
  volume NEE (pkg268, done, PR #810); per-λ σ via spectral/decomposition
  tracking + spectral Planck emission (pkg270, in flight); GPU wavefront hetero
  stage behind `template<bool HasGridVolume>` (pkg269, in flight); passes +
  corpus (pkg271); optional motion-blur-or-multiscatter slot (pkg272).
- **Spectral core:** 4-sample hero quad over 360–830 nm
  (`include/astroray/spectrum.h`, `kLambdaMin/Max`, `kSpectrumSamples = 4`).
- **Sky:** engine-side Nishita (`src/world/nishita_sky.cpp`, #799 Phase 2) —
  single-scattering mode integrates 21 wavelengths 380–780 nm, multiple-
  scattering mode is the 4-wavelength Hillaire/García-Liñán fit; both are
  collapsed to XYZ→RGB before leaving the engine. The sun disc is a dedicated
  distant light with the true angular diameter (#799 part 1).
- **What is missing for clouds:** any material whose coefficients come from
  microphysics rather than an artist density; any phase function other than
  HG/isotropic (`include/astroray/volume/phase.h`); any ice model; any
  r_eff-dependent optics; a spectral (not RGB) sky at the engine boundary.

The north star (`north-star-and-integration-gate-2026-09-07.md` §1) wants
physically meaningful spectra and instrument-like observables; a cloud material
built from LWC / r_eff / IWC is squarely that lane ("science-foundational",
§3) — and unlike the paused Pillar-4 loaders it also serves ordinary production
renders.

---

## 1. Lorenz–Mie scattering for water droplets

**Theory.** A homogeneous sphere of radius r and complex refractive index
m = n − ik in a non-absorbing host, illuminated by a plane wave of wavelength λ,
scatters with the series solution of Lorenz (1890) and Mie (1908). Everything is
a function of the size parameter x = 2πr/λ and m: the efficiencies Q_ext, Q_sca,
Q_abs = Q_ext − Q_sca (cross-section / πr²), the asymmetry parameter g, and the
amplitude functions S1(θ), S2(θ) whose unpolarised intensity
i(θ) = (|S1|² + |S2|²)/2 gives the phase function
p(θ) = i(θ) / (x² Q_sca) normalised over the sphere. The number of series terms
is n_max ≈ x + 4x^{1/3} + 2 (Wiscombe 1980). Cloud droplets (r = 2–30 µm) at
visible λ have x ≈ 15–500, so a single (r, λ) evaluation costs a few hundred
terms per angle — cheap. Textbook: Bohren & Huffman 1983, *Absorption and
Scattering of Light by Small Particles* (Wiley), ch. 4.

**Reference codes (for the tabulation tool, not the render kernel):**

| Code | Source | Licence | Notes |
|---|---|---|---|
| BHMIE | Bohren & Huffman 1983, Appendix A (FORTRAN) | Printed in the book; universally redistributed and treated as public domain, but the book carries no explicit licence — **unverified**. Modern re-packagings: hyperion-rt/bhmie (BSD-2-Clause, Robitaille), bcollist/bhmie C++ (MIT) | Simple, well-understood; loses accuracy for very large x and strongly absorbing m without the Wiscombe fixes |
| MIEV0 / MIEV1 | Wiscombe, "Improved Mie scattering algorithms", *Applied Optics* 19(9), 1505–1509, 1980; NASA GSFC ftp `climate1.gsfc.nasa.gov/wiscombe/Single_Scatt/Homogen_Sphere/Exact_Mie/` | US-government work by a NASA employee — public domain in the US is the usual reading; no licence file — **unverified** | The accuracy standard; includes the Lentz continued-fraction for the logarithmic derivative and the x ≫ 1 stability fixes |
| miepython | scottprahl/miepython (GitHub) | **MIT** (verified 2026-09-15) | Pure Python/Numba; "reproduces established reference results (including Wiscombe's MIEV0)"; computes efficiencies, g, angle-resolved intensities, S1/S2, Mueller matrices. **Recommended for the addon-side table builder** (Blender ships Python + NumPy; Numba optional) |
| PyMieScatt | bsumlin/PyMieScatt; Sumlin, Heinson, Chakrabarty, *JQSRT* 205, 2018 | **MIT** (verified) | Bohren–Huffman based; forward + inverse; size-distribution integrals built in |
| Frisvad, Christensen, Jensen 2007 | "Computing the scattering properties of participating media using Lorenz-Mie theory", *ACM TOG* 26(3) (SIGGRAPH 2007), DOI 10.1145/1276377.1276452 | Paper only; the DTU code page (`people.compute.dtu.dk/jerf/code/phase/`) offers MATLAB/JavaScript for the 2018 inhomogeneous-wave follow-up with **no licence statement** (checked 2026-09-15) — treat as read-only reference | The graphics-side canonical reference: extends Lorenz–Mie to an *absorbing host*, shows the full pipeline number-density distribution → bulk σ_s, σ_a, phase function for renderers (milk, ocean water, etc.), and the bulk-phase-function sampling by size-weighted integration. Its host-medium extension is not needed for air |

**Bulk coefficients from a size distribution** (Frisvad 2007 §4; Bohren &
Huffman ch. 4; Hansen & Travis 1974):

    σ_ext(λ) = ∫ π r² Q_ext(r, λ, m(λ)) n(r) dr
    σ_sca(λ) = ∫ π r² Q_sca(r, λ, m(λ)) n(r) dr
    p(θ, λ)  = ∫ π r² Q_sca(r, λ) p_r(θ, λ) n(r) dr / σ_sca(λ)

with n(r) the droplet number density per unit radius (m⁻³ µm⁻¹). The bulk phase
function is the *scattering-cross-section-weighted* average of the single-sphere
phase functions — this weighting is what smooths the single-sphere ripple and
the supernumerary structure into the observed fogbow.

---

## 2. Droplet size distributions

- **Modified gamma** (Deirmendjian 1969, *Electromagnetic Scattering on
  Spherical Polydispersions*, Elsevier): n(r) = a r^α exp(−b r^γ). The classic
  cumulus model **C1** is α = 6, γ = 1, b = 1.5 µm⁻¹ (mode radius 4 µm,
  r_eff ≈ 6 µm); Deirmendjian's haze/cloud models are still the standard test
  cases in the Mie literature.
- **Gamma distribution in (r_eff, v_eff)** (Hansen & Travis 1974, "Light
  scattering in planetary atmospheres", *Space Sci. Rev.* 16, 527–610):
  n(r) ∝ r^{(1−3v)/v} exp(−r/(r_eff v)), with

      r_eff = ∫ r³ n dr / ∫ r² n dr        (area-weighted mean radius)
      v_eff = ∫ (r − r_eff)² r² n dr / (r_eff² ∫ r² n dr)

  Closed-form moments for this family (derived from the gamma-function moments;
  used by the coefficient formulas below):

      ⟨r²⟩ = r_eff² (1 − v_eff)(1 − 2 v_eff)
      ⟨r³⟩ = r_eff³ (1 − v_eff)(1 − 2 v_eff) = ⟨r²⟩ · r_eff

  Typical v_eff: 0.05–0.2 for water clouds (Hansen & Travis; Miles, Verlinde &
  Clothiaux 2000, *J. Atmos. Sci.* 57, 295–311 compile in-situ r_eff/N/width
  for stratus vs cumulus — **unverified numbers**, cite the paper when the
  presets are built).
- **Log-normal** is the other common cloud-physics choice (parameters r_g, σ_g);
  the table builder should accept both, since the owner's sim may carry either
  (or a full bin-resolved spectrum — see the grid contract in pkg273).
- **Key simplification (Hu & Stamnes 1993):** cloud bulk optics "depend mainly
  on equivalent radius throughout the solar and terrestrial spectrum and are
  insensitive to the details of the droplet size distribution, such as shape,
  skewness, width, and modality" — Hu & Stamnes, "An accurate parameterization
  of the radiative properties of water clouds suitable for use in climate
  models", *J. Climate* 6, 728–742, 1993. So a **2-D table in (r_eff, λ)** with
  a fixed moderate v_eff is adequate for σ_ext, ω0 and g. The *phase function's
  fine structure* (corona rings, supernumerary fogbows, glory ring radii) does
  depend on width, so v_eff is a table axis for the phase, not for the
  coefficients.

---

## 3. Per-λ σ_s / σ_a from LWC and r_eff

**The β = 3·LWC/(2·ρ_w·r_eff) rule and why it is (nearly) exact.** With
N droplets per m³:

    LWC   = (4/3) π ρ_w N ⟨r³⟩                      [kg m⁻³]
    σ_ext = π N ⟨r² Q_ext⟩ ≈ 2 π N ⟨r²⟩              (Q_ext → 2 for x ≫ 1)
    ⇒ σ_ext / LWC = 2π⟨r²⟩ / ((4/3)π ρ_w ⟨r³⟩) = 3 / (2 ρ_w r_eff)

The distribution width cancels *exactly* through r_eff = ⟨r³⟩/⟨r²⟩; the only
approximation is Q_ext ≈ 2 (the "extinction paradox": diffraction contributes a
cross-section equal to the geometric one). Validity: x ≳ 30 (r ≳ 3 µm at
550 nm) where Q_ext oscillates within a few percent of 2 and absorption is
negligible; **it fails** in the thermal IR (r ~ λ, Q_ext ≠ 2, ω0 ≪ 1), for
r_eff ≲ 2 µm (haze, x ~ 10–20, Q_ext up to ~3), and for absorbing particles.
Hu & Stamnes 1993 fit the exact Mie result as σ_ext/LWC = a1 r_eff^{b1} + c1
(plus ω0, g fits) over 2.5–60 µm and both solar and terrestrial spectra — this
is the fallback parameterisation if a full table is not wanted.

**Magnitudes** (ρ_w = 1000 kg m⁻³):

| Cloud | LWC [g m⁻³] | r_eff [µm] | σ_ext [m⁻¹] | mean free path [m] | τ over 1 km |
|---|---|---|---|---|---|
| stratus / stratocumulus | 0.1–0.5 | 5–12 | 0.01–0.15 | 7–100 | 10–150 (typ. τ 10–40 for the actual ~300–500 m depth) |
| cumulus (mediocris/congestus) | 0.3–2 | 8–20 | 0.02–0.4 | 3–50 | 20–400 |
| cirrus (ice, IWC 0.001–0.1 g m⁻³, D_eff 30–100 µm) | — | — | 1e-5–5e-3 | 200–1e5 | 0.05–5 (typ. τ 0.1–3) |

The ice analogue uses ρ_ice = 917 kg m⁻³ and an *effective diameter* defined
from volume and projected area, D_eff = (3/2) V/A (Yang / Baum convention), so
σ_ext ≈ 3·IWC/(ρ_ice·D_eff); Q_ext → 2 holds for large non-spherical particles
too (Mishchenko et al., *Scattering, Absorption, and Emission of Light by Small
Particles*, 2002).

**Absorption and the single-scattering albedo.** For weak absorption
(4π k r/λ ≪ 1) the droplet absorption efficiency is ≈ (4/3)·α_bulk·r with
α_bulk = 4πk/λ the liquid-water absorption coefficient, so

    1 − ω0 ≈ Q_abs / Q_ext ≈ (2/3) α_bulk(λ) r_eff

Liquid water: α_bulk ≈ 0.006 m⁻¹ at 400 nm, ~0.05 m⁻¹ at 550 nm, ~0.6 m⁻¹ at
700 nm, ~2 m⁻¹ at 800 nm (Segelstein 1981 / Pope & Fry 1997 — magnitudes,
**unverified to better than a factor ~2**). For r_eff = 10 µm this gives
1 − ω0 ≈ 4e-8 (400 nm) … 4e-7 (550 nm) … 1.3e-5 (800 nm): **a water cloud in
Astroray's 360–830 nm band is a conservative scatterer to ≤ 1e-5**. After
~1000 scattering events the red end loses ~1 %, which is the faint blue tint of
very thick clouds / glacier ice, and that is the entire visible-band chromatic
extinction effect. The strong spectral structure — the 0.94, 1.14, 1.4, 1.9,
2.7 µm water bands, ω0 dropping to 0.99 at 1.6 µm, 0.95–0.98 at 2.1 µm, and the
thermal-IR regime where clouds are nearly black bodies — lives **outside the
current engine band**. The tables should therefore be built over 0.2–5 µm (or
to 100 µm if the Yang/Baum ice data are adopted) so the material becomes the
IR instrument-simulation asset the north star wants the moment the band widens
(pkg251 / pkg133 lineage), without redoing the physics.

---

## 4. Refractive-index data

| Material | Source | Range | Data licence |
|---|---|---|---|
| Liquid water | Hale & Querry, "Optical constants of water in the 200-nm to 200-µm wavelength region", *Applied Optics* 12, 555–563, 1973 | 0.2–200 µm | Physical data; tabulated in refractiveindex.info (database is **CC0-1.0**, verified 2026-09-15) |
| Liquid water (extended, KK-consistent) | Segelstein, "The complex refractive index of water", M.S. thesis, Univ. Missouri–Kansas City, 1981 | 10 nm – 10 m | Tables at omlc.org (`segelstein81_index.txt`) and refractiveindex.info (CC0) |
| Liquid water (visible absorption, most accurate) | Pope & Fry, *Applied Optics* 36, 8710, 1997 (absorption 380–700 nm) | 380–700 nm | Physical data (**unverified** which database carries it) |
| Ice Ih | Warren & Brandt, "Optical constants of ice from the ultraviolet to the microwave: A revised compilation", *JGR* 113, D14220, 2008, DOI 10.1029/2007JD009744 | 0.044 µm – 2 m | Tables at `atmos.washington.edu/ice_optical_constants/`; also on refractiveindex.info (CC0) |

Dispersion of the real part matters: n_water = 1.343 (400 nm) → 1.333 (589 nm)
→ 1.331 (700 nm) is what shifts the fogbow / rainbow angle with λ and colours
the glory rings. Temperature dependence of n in the visible is ~1e-4 K⁻¹ and can
be ignored; supercooled droplets use the liquid tables.

---

## 5. Ice crystals: habits and what a renderer can honestly do

Ice particles are non-spherical; Mie spheres are wrong for them in the specific
ways that matter visually — spheres give a rainbow-like feature and a glory,
real hexagonal crystals give the 22° and 46° halos (pristine, smooth facets) or
an almost featureless, strongly forward-peaked phase function (roughened
crystals, the common case).

**Databases:**

- Yang, Bi, Baum, Liou, Kattawar, Mishchenko, Cole, "Spectrally consistent
  scattering, absorption, and polarization properties of atmospheric ice
  crystals at wavelengths from 0.2 to 100 µm", *J. Atmos. Sci.* 70, 330–347,
  2013, DOI 10.1175/JAS-D-12-039.1. Single-particle properties for 11 habits
  (droxtals, prolate/oblate spheroids, solid and hollow columns, plates,
  solid/hollow bullet rosettes, 8-column aggregates, small/large plate
  aggregates), three surface-roughness levels (smooth / moderate / severe —
  **unverified** that all three are in the public files), 189 sizes and 445
  wavelengths, computed with ADDA + T-matrix + IGOM. **Version 2 dataset on
  Zenodo, record 5348402, licence CC-BY-4.0 (verified 2026-09-15)**; v2
  improvements per Bi & Yang, *JQSRT* 189, 228–237, 2017.
- Baum, Yang, Heymsfield, Bansemer, Cole, Merrelli, Schmitt, Wang, "Ice cloud
  single-scattering property models with the full phase matrix at wavelengths
  from 0.2 to 100 µm", *JQSRT* 146, 123–139, 2014. **Bulk** models (integrated
  over in-situ size distributions from 11 field campaigns) for 445 wavelengths
  as a function of D_eff: the "General Habit Mixture" (GHM, nine habits), plus
  solid-column and aggregate-only models, all severely roughened. This is the
  cirrus preset a renderer should ship: (σ_ext/IWC, ω0, g, P11(θ)) vs (D_eff, λ).
  Licence of the bulk files: distributed from SSEC/Texas A&M; **unverified** —
  confirm before vendoring (the underlying Yang v2 data are CC-BY-4.0, so
  re-integrating the bulk tables ourselves from the single-particle data is the
  licence-safe fallback).

**What the renderer can honestly do (three tiers):**

1. *Roughened bulk mixture* (default for cirrus / anvil / mixed-phase ice):
   tabulated bulk P11 from Baum GHM per (D_eff, λ). Smooth, no halos — correct
   for most real cirrus, which are roughened/aggregated. Same tabulated-phase
   sampler as droplets; only the table differs.
2. *Pristine habit preset* (hexagonal plates / columns, smooth): tabulated
   P11 from the Yang smooth-surface single-particle data integrated over a
   size distribution. Gives 22°/46° halos as ring structures in the
   randomly-oriented phase function. Physically legitimate only for the rare
   pristine-crystal cases (diamond dust, some thin cirrostratus).
3. *Oriented crystals* (sun dogs, light pillars, circumzenithal arc): requires an
   anisotropic medium whose phase function depends on the incident direction
   relative to a preferred axis (Yang's data are 3-D random orientation only).
   **Out of scope for any version of pkg273**; say so rather than fake it.

**Mixed phase:** the medium is a *mixture* of two particle populations;
σ_ext = σ_water + σ_ice, and the bulk phase function is the σ_sca-weighted mix
(p = (σ_s,w p_w + σ_s,i p_i)/(σ_s,w + σ_s,i)) — this is a per-voxel blend,
cheap to sample by choosing the population with probability ∝ σ_s. The
mixed-phase policy (how the sim partitions condensate, whether it exports the
ice fraction or separate IWC/LWC) is open question 2.

---

## 6. Phase-function representation

**What Mie phase functions look like** for r_eff = 10 µm at 550 nm
(x ≈ 114): g ≈ 0.85–0.87. Roughly half the scattered energy is in the
diffraction peak (first Airy minimum at θ ≈ 1.22 λ/(2r) ≈ 1.9°, the peak itself
is ~1e4 × the isotropic level); a broad geometric-optics plateau; the
**fogbow** (primary rainbow of small drops) at scattering angle ≈ 138–140° —
broad, nearly white, with weak supernumeraries because the drops are small (the
sharp coloured rainbow needs r ≳ 100 µm rain drops); the **glory** at 180° with
coloured rings of angular radius ∝ λ/r (a few degrees for 10 µm drops), a
surface-wave/tunnelling effect that no geometric-optics or HG model contains
(Nussenzveig, *Diffraction Effects in Semiclassical Scattering*, 1992); and the
**corona** — the diffraction rings around the sun through a thin cloud, radius
∝ λ/r, visible only for narrow size distributions (v_eff ≲ 0.05) and thin
optical depth (τ ≲ 1–2). Laven's MiePlot documentation
(`philiplaven.com`) has the standard reference pictures of all of these.

**Why HG / double-HG cannot substitute.** HG (Henyey & Greenstein 1941) is a
one-parameter monotone function of cos θ: no fogbow, no glory, no corona,
diffraction peak too wide and too weak for a given g. Two-term HG / Cornette–
Shanks / Draine mixtures add a back lobe (a "glory-ish" brightening) and a
sharper forward lobe but still no angular *structure* and no λ dependence.
Jendersie & d'Eon, "An Approximate Mie Scattering Function for Fog and Cloud
Rendering", *SIGGRAPH 2023 Talks*, DOI 10.1145/3587421.3595409, fit an
analytic, sampleable HG+Draine mixture to Mie for droplet diameters 5–50 µm
across the visible — the state of the art for a *closed-form* phase; it
captures the fogbow position and a glory-like backscatter for a fixed size but
by construction not the ring structure or its colour. **Cycles has this
model:** the Volume Scatter node's `Mie` phase option (Blender source
`node_shader_volume_scatter.cc`, `SHD_PHASE_MIE`, socket "Diameter" in µm,
default 20, range 0–50; added by Blender PR #123532 — checked 2026-09-15; the
kernel lowers it to HG + Draine closures in `svm/closure.h` per the PR,
**kernel mapping not re-read**). Principled Volume stays HG-only. So the Cycles
cross-check band for pkg273 should be built with *Volume Scatter + Mie*, not
Principled Volume — it is the closest Cycles can get.

**Recommended representation: tabulated bulk phase with inverse-CDF sampling.**

- Table axes: r_eff bin × v_eff bin × λ bin, each a 1-D marginal over θ.
  Non-uniform θ grid (log-spaced near 0° to resolve the diffraction peak,
  ~0.1° there; ~0.5° elsewhere, denser again near the fogbow and 175–180°).
  ~1024–2048 bins per (r_eff, v_eff, λ) row; float32 pdf + CDF; a 16 × 4 × 32
  table is ~2 × 16·4·32·2048·4 B ≈ 33 MB — fine on CPU, a `cudaArray` /
  texture on GPU; or 8-bit-log compress if needed. The size axis can instead
  be the sim's *bin-resolved* spectrum if the sim exports one (then the bulk
  phase is integrated at upload time per voxel class — open question 1).
- Sampling: draw u, binary-search the CDF (or a texture-fetched inverse-CDF
  table for the GPU), interpolate cos θ; pdf = p(θ) from the table. This is the
  standard tabulated-phase approach (Frisvad 2007 §5; pbrt-v4 has no tabulated
  phase but its `PiecewiseLinear`/`PiecewiseConstant1D` samplers are the
  Apache-2.0 template).
- **Hero-wavelength handling.** Each of the 4 wavelengths has its own phase.
  Sample the direction with the hero λ's pdf and evaluate p(θ, λ_i)/p(θ, λ_hero)
  for the secondaries (single-sample spectral MIS as in pbrt-v4's
  wavelength-dependent BSDFs, Wilkie et al. 2014). The ratio is bounded because
  the four Mie phases at nearby λ are similar in shape, so no hero collapse is
  needed except in the corona regime (thin cloud, narrow v_eff) where the ring
  radii differ by λ; there the existing `SampledWavelengths` collapse path is
  the safe fallback.
- **Spatially varying r_eff** means the phase function varies per scattering
  event: the sampler reads the local r_eff bin at the collision point — a
  texture/table index, no new per-hit state in the *surface* shade kernel
  (the GPU volume stage is its own `template<bool>` kernel, pkg269).

**Multiple-scattering smoothing argument (important for cost).** After a
handful of scattering events the angular structure is washed out; only the
first 1–3 orders carry the fogbow/glory/silver-lining signal. A renderer may
therefore switch to a cheap HG with the tabulated g after order k (Frisvad-
style "hybrid"); this is a bias trade the spec keeps as an *option* flag, off
by default (unbiased reference first, north star: correctness > speed).

---

## 7. Multiple scattering in clouds — why the Principled Volume look is wrong

- **Orders of scattering.** With ω0 ≈ 1 and τ = 20–100, a photon undergoes on
  the order of τ² … well beyond hundreds of events before escaping (diffusion:
  transport mfp = mfp/(1−g) ≈ 7 mfp; escape after ~(τ(1−g))² transport steps).
  Kallweit et al. 2017 report thousands of scattering events per path for
  production cumulus; the path tracer's cost per event is a delta-tracking
  free flight plus a phase sample, so unbiased cloud renders are minutes-to-
  hours even on GPU, and `volume_bounces` caps darken the cloud (biased).
- **What the correct solution looks like.** Silver lining = low-order forward
  scattering through the thin edge (needs the true diffraction peak width);
  bright "whiteness" of the body = high-order diffusion (any ω0 ≈ 1 phase gives
  this eventually); dark flat bases = geometry + shadowing, not absorption;
  fogbow/glory on the sunlit face when viewed from the antisolar side (aircraft
  shadow glory). HG with g = 0.85 gets the body roughly right and the edges,
  bows and glory wrong; HG with the artist's g = 0.3–0.6 (what Principled Volume
  users pick to get "brightness" at low bounce counts) is a different medium.
- **Real-time and production approximations, and the honest gap:**
  - Bouthors, Neyret, Max, Bruneton, Crassin, "Interactive multiple anisotropic
    scattering in clouds", *I3D 2008* — precomputed plane-parallel-slab
    collector functions per scattering-order set, GPU shader; captures
    anisotropic MS at interactive rates for a *surface-bounded* cloud.
  - Schneider & Vos, "The Real-time Volumetric Cloudscapes of Horizon Zero
    Dawn", *SIGGRAPH 2015 Advances in Real-Time Rendering* (Nubis) — ray
    march, two-lobe HG, "Beer–Powder" in-scatter heuristic, Wrenninge-style
    multi-scatter octaves. Nubis Evolved (2022/23) refines the same shape.
  - Hillaire, "Physically Based Sky, Atmosphere and Cloud Rendering in
    Frostbite", *SIGGRAPH 2016 course, Physically Based Shading in Theory and
    Practice* — energy-conserving MS approximation (attenuation / contribution /
    eccentricity octaves), two-lobe HG, sky/aerial-perspective coupling; and
    Hillaire 2020 (*CGF* 39(4)) for the scalable atmosphere LUTs.
  - Kallweit, Müller, McWilliams, Gross, Novák, "Deep Scattering: Rendering
    Atmospheric Clouds with Radiance-Predicting Neural Networks", *ACM TOG*
    36(6) (SIGGRAPH Asia 2017), arXiv:1709.05418 — replaces the MS integral
    with an MLP over a hierarchical density descriptor, trained on path-traced
    clouds; explicitly motivated by the cost of Lorenz–Mie + high albedo.
  - Disney Hyperion: Kutz, Habel, Li, Novák, "Spectral and Decomposition
    Tracking for Rendering Heterogeneous Volumes", *ACM TOG* 36(4) (SIGGRAPH
    2017); Burley et al., "The Design and Evolution of Disney's Hyperion
    Renderer", *ACM TOG* 37(3), 2018 — production clouds (Moana) are brute-force
    null-collision path tracing with these trackers plus aggressive
    Russian-roulette and light-sampling machinery; the Moana Island data set
    ports the cloud volume for PBRT.
  - Novák, Georgiev, Hanika, Jarosz, "Monte Carlo Methods for Volumetric Light
    Transport Simulation", *CGF* 37(2) (EG STAR 2018), DOI 10.1111/cgf.13383 —
    the survey of free-path sampling, transmittance estimators and the
    null-collision framework the whole volumes track sits on.
  - **Gap:** the real-time methods trade the phase function, the MS orders and
    often the spectral dimension for frame rate; they cannot produce a fogbow,
    a glory, a corona, or a physically meaningful radiance for an instrument.
    A spectral path tracer produces all of those *in the limit* but at
    orders-of-magnitude cost, so for daily use the cloud material will want an
    accelerator: either a Kallweit-style learned MS (Astroray already has an
    NRC substrate, pkg27) or a diffusion/slab MS approximation (pkg272 fork).
    The right posture is "unbiased reference + an explicitly biased fast mode",
    both behind the same material, gated against each other.

---

## 8. Interplay with spectral tracking (Kutz 2017, pkg270)

- Spectral tracking pays off when σ_t(λ) differs across the hero quad: it
  weights null/real collisions so no wavelength needs its own free flight.
  For water droplets in 360–830 nm, σ_t(λ) varies by only the Q_ext ripple
  (≲ 5 % for r_eff ≥ 5 µm, more for r_eff ≲ 3 µm) and ω0 differs by 1e-5 — the
  majorant is effectively common, and the spectral-tracking weights stay near 1.
  So **for water clouds the spectral cost is nearly free and the spectral
  benefit in extinction is nearly nil in the visible**; the spectral content
  comes from the phase function (§6) and the illumination (§9).
- In absorption bands (IR future band; ice at 1.5/2.0 µm; liquid at 0.94 µm+)
  σ_a(λ) varies by orders of magnitude and spectral tracking is exactly the
  right tool — the pkg270 machinery is what makes the IR story tractable.
- The **majorant** for a cloud grid comes from max(LWC/r_eff) per supervoxel
  (σ_t ∝ LWC/r_eff) — either upload a precomputed σ_t grid (simplest, pkg267
  contract) or bound with max(LWC)/min(r_eff) (looser, more null collisions).
  Decomposition tracking (control + residual) helps the stratus case where the
  medium is nearly homogeneous over large regions.

---

## 9. Atmosphere link: sun, sky, aerosols

- **Illumination spectrum.** The engine's Nishita sky is computed spectrally
  (21 λ, 380–780 nm, single-scattering mode) but exits as RGB and is then
  re-upsampled by the world/HDRI path — a lossy round trip for the *very* thing
  a cloud material would show (sunset reddening through a long atmospheric
  path, blue sky-light on the shadowed side). The owner already flagged the
  per-wavelength sky as a future scientific need (2026-09-11 decision 1); pkg273
  lists a *spectral sky handoff* (keep the per-λ sky radiance for the hero quad)
  as an explicit dependency for the science-grade mode, not for the look mode.
- **Sun disc.** The Mie forward peak is ~1–2° wide; the sun is 0.53°. Corona,
  sun-through-stratus, and the silver lining depend on the sun being a disc
  with the right angular radius, which #799 part 1 already provides (dedicated
  distant light, angular diameter = sun_size). A point/delta sun would be wrong
  here in a visible way.
- **Aerosols and Rayleigh inside the cloud volume** are negligible next to the
  droplets (Rayleigh σ ≈ 1.2e-5 m⁻¹ at 550 nm vs 0.01–0.4 m⁻¹ droplets); they
  matter *between* clouds (aerial perspective) and are the sky model's job.
  If the sim exports an aerosol/haze field, it is just another particle
  population in the §5 mixture with its own Mie table (Deirmendjian haze models,
  Shettle & Fenn 1979 aerosol types).
- **Ground albedo** lights cloud bases from below; that is ordinary surface
  transport and needs nothing new.

---

## 10. What this means for the engine (summary of the pkg273 design)

1. **Material = coefficients from microphysics.** `Astroray Cloud Volume` reads
   LWC (and/or IWC) and r_eff (grid or constant) and produces σ_s(λ, x),
   σ_a(λ, x) from a Mie table (water: computed at addon install / first use with
   miepython, cached as `.npz`; ice: Baum GHM / re-integrated Yang v2 tables,
   vendored under CC-BY-4.0 with attribution). Fast path: the 3·LWC/(2ρ r_eff)
   rule with ω0 from the table.
2. **Phase = tabulated bulk Mie/ice phase** with inverse-CDF sampling, hero-λ
   spectral MIS, per-collision r_eff bin; HG fallback available (for A/B and for
   the biased hybrid after order k).
3. **Transport unchanged in principle:** delta/ratio tracking + spectral
   tracking from pkg268/270; only the σ evaluation and the phase sampler are
   new. GPU: inside the pkg269 `HasGridVolume` stage; tables in texture memory;
   *no* new live state in the shared shade kernel (REG:254 gate).
4. **Gates:** analytic single-scatter checks vs BHMIE/miepython (efficiencies,
   g, phase normalisation ∫p dΩ = 1, fogbow angle 138–140° for r_eff 10 µm at
   550 nm, glory backscatter maximum at 180°, Rayleigh limit p ∝ 1 + cos²θ for
   x → 0); Cycles Volume Scatter+Mie as a *cross-check band*.

---

## 11. Open questions for the owner (real forks)

1. **What does the sim export?** LWC + N (number concentration) + r_eff, or a
   bin-resolved droplet spectrum per voxel? Bin-resolved is the most physical
   (bulk phase integrated per voxel class) but heavy; LWC + r_eff (+ v_eff) is
   the standard remote-sensing parameterisation and what the spec assumes.
2. **Mixed-phase policy:** separate LWC and IWC grids with a habit preset for
   the ice (spec default), or a single condensate grid plus an ice fraction?
   And does the sim carry rain / graupel / snow categories the material should
   treat as extra populations (rain drops r ~ 0.1–1 mm give a *real* rainbow)?
3. **Cycles fallback:** should the addon also drive a Cycles Volume Scatter+Mie
   (Diameter = 2 r_eff) node tree from the same material so a scene stays
   renderable in Cycles — or is Astroray-only acceptable for these volumes?

---

## References (compact)

- Bohren & Huffman 1983, *Absorption and Scattering of Light by Small Particles*, Wiley — BHMIE App. A.
- Wiscombe 1980, *Appl. Opt.* 19, 1505 — MIEV0/MIEV1.
- Frisvad, Christensen, Jensen 2007, *ACM TOG* 26(3), DOI 10.1145/1276377.1276452.
- Hansen & Travis 1974, *Space Sci. Rev.* 16, 527 — r_eff / v_eff.
- Deirmendjian 1969, *Electromagnetic Scattering on Spherical Polydispersions* — C1 etc.
- Hu & Stamnes 1993, *J. Climate* 6, 728 — r_eff parameterisation.
- Hale & Querry 1973, *Appl. Opt.* 12, 555; Segelstein 1981 (M.S. thesis, UMKC); Pope & Fry 1997, *Appl. Opt.* 36, 8710; Warren & Brandt 2008, *JGR* 113, D14220.
- Yang et al. 2013, *J. Atmos. Sci.* 70, 330 (Zenodo 5348402, CC-BY-4.0); Bi & Yang 2017, *JQSRT* 189, 228; Baum et al. 2014, *JQSRT* 146, 123.
- Nussenzveig 1992, *Diffraction Effects in Semiclassical Scattering* — glory.
- Henyey & Greenstein 1941, *ApJ* 93, 70; Jendersie & d'Eon 2023, *SIGGRAPH Talks*, DOI 10.1145/3587421.3595409.
- Bouthors et al. 2008, *I3D*; Schneider & Vos 2015, *SIGGRAPH ARTR*; Hillaire 2016, *SIGGRAPH PBS course*; Hillaire 2020, *CGF* 39(4); Kallweit et al. 2017, *ACM TOG* 36(6); Kutz et al. 2017, *ACM TOG* 36(4); Burley et al. 2018, *ACM TOG* 37(3); Novák et al. 2018, *CGF* 37(2).
- Wilkie et al. 2014, "Hero Wavelength Spectral Sampling", *CGF* 33(4) — spectral MIS.
- Code: miepython (MIT), PyMieScatt (MIT), hyperion-rt/bhmie (BSD-2), pbrt-v4 (Apache-2.0), Cycles `node_shader_volume_scatter.cc` / `svm/closure.h` (Apache-2.0 / GPL for the node editor side — reference only).

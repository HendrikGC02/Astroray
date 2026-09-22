# pkg279 — HMXB Phase 1: prescribed binary geometry and orbital light curve

**Pillar:** 4
**Track:** A
**Status:** paused — Pillar 4 (Stage 2, Track L); filed 2026-09-22
**Estimated effort:** 2 sessions
**Depends on:** pkg280, pkg43

---

## Goal

**Before:** Pillar 4 renders isolated GR sources (Kerr + slim disk / ADAF) with no
binary-system geometry; there is no way to produce an orbital-modulation observable.

**After:** a prescribed circular-orbit high-mass X-ray binary (HMXB) scene — a
Roche-lobe-filling massive donor built from the analytic Roche potential plus a compact
object carrying the existing slim-disk emission (pkg43) — renders a **normalised orbital
light curve** over one period (eclipse + ellipsoidal modulation) from a Blender-driven
CPU render, with the eclipse and ellipsoidal amplitudes checked against their analytic
values.

This validates prescribed occultation geometry only: it does not validate an HMXB
spectrum or any observed system, and there is no universal HMXB eclipse fraction.

---

## Context

Stage 2 Track L is lensing/HMXB (`stage-plan-2026-09-22.md`). Weak-field lensing
(pkg50) is *not* a prerequisite for a binary-system scene, so this is the branch that
carries the L2 observable. The stage plan deliberately bounds it: "prescribed orbital
geometry + explicit emission model; no hydrodynamics". "HMXB system" alone is not an
implementable package, so this spec fixes one geometry and one observable before any
X-ray microphysics is chosen. Without it there is no binary-orbit science deliverable and
no scene that exercises the existing accretion emission in a time-varying configuration.

---

## Evidence

- 2026-09-22: rewritten in the planning session (stage-plan-2026-09-22.md §4); previous text superseded.
- 2026-09-22: Astra turn-2 review amendments applied (planning session).
- 2026-09-22: Codex Terra review defects applied (planning session).

---

## Reference

- Design doc: `.astroray_plan/docs/astrophysics.md §4.2` (accretion models),
  `.astroray_plan/docs/accretion-emission-research.md`.
- Stage plan: `.astroray_plan/docs/stage-plan-2026-09-22.md §3 Track L, §4`.
- External: Eggleton 1983, ApJ 268, 368 — analytic Roche-lobe radius approximation (eq. 2).
- External: Avni & Bahcall 1975, ApJ 197, 675 — analytic ellipsoidal light variations of X-ray binaries.
- External: Morris & Naftilan 1993, ApJ 419, 344 — discrete Fourier series for ellipsoidal variability amplitude.
- External: Kopal 1959, *Close Binary Systems*, Chapman & Hall — geometric contact conditions for circular-orbit eclipses.
- Reuse: `plugins/accretion/slim_disk.cpp` (pkg43, done); `include/astroray/emission.h` (EmissionRegistry).
- Reuse: `benchmarks/reference_bank/` scene layout (pkg104/pkg107).

---

## Prerequisites

- [ ] pkg280 (GR transfer & reference audit) is done — invariant-intensity transfer fixed in `diskEmissionSpectral` and the emission clamp resolved, so the slim-disk source used here is trustworthy.
- [ ] pkg43 (slim disk) is done and tests are green.
- [ ] Build passes on main.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `tests/scenes/hmxb_phase1.py` | Prescribed-geometry HMXB scene builder: donor Roche surface, circular orbit, slim-disk accretor. |
| `tests/scenes/hmxb_control.py` | Dedicated analytic control scene: spherical opaque donor (radius `R_L`) + point emitter on a circular edge-on orbit, rendered through Blender CPU. |
| `benchmarks/reference_bank/scenes/hmxb-lightcurve/scene.py` | Reference-bank scene entry for the orbital light curve (references both the deliverable and the control scene). |
| `benchmarks/reference_bank/scenes/hmxb-lightcurve/gates.toml` | Gate thresholds for the eclipse/ellipsoidal checks. |
| `benchmarks/reference_bank/scenes/hmxb-lightcurve/notes.md` | Geometry, settings, and evidence paths for the reference frame. |
| `scripts/hmxb_lightcurve.py` | Render phase-folded frames over one period, assemble the normalised light curve figure. |

### Files to modify

None.

### Key design decisions

#### Geometry and orbit (prescribed, analytic)

- **Roche-lobe-filling donor over wind-fed.** The donor is a massive star filling its
  Roche lobe; its surface is the analytic Roche equipotential (Kopal potential) and its
  lobe radius uses the Eggleton 1983 approximation `R_L/a = 0.49 q^(2/3) /
  (0.6 q^(2/3) + ln(1 + q^(1/3)))`. Chosen over a wind-fed system because Roche-lobe
  overflow is deterministic and analytic: it gives a large, well-defined occulting body
  and the tidal distortion that produces ellipsoidal modulation, with no need for a
  clumpy-wind or mass-loss model (explicitly out of scope).
- **Prescribed circular orbit.** Inputs: period `P`, semi-major axis `a`, inclination
  `i`, mass ratio `q = M_donor / M_compact`. The donor fills its lobe (`R_donor = R_L`).
  No orbital evolution, eccentricity, or tides beyond the static Roche surface.
- **Compact object uses existing slim-disk emission (pkg43).** No new emission physics
  and no new accretion model. The slim disk is the accretion-disk model of Phase 1.
- **Emission model is explicit and bolometric-per-source.** Each source carries a
  declared emitted spectrum; the light curve is normalised, so absolute calibration is
  not required.

#### First measurable deliverable (L2)

- Produce one phase-folded, **normalised** orbital light curve over one period from a
  Blender-driven CPU render.
- **Normalisation baseline.** Normalise every frame by the mean flux over phases outside
  eclipse (all sampled phases with `|phase − 0.5| > f_eclipse`); that baseline is 1.0 by
  construction, so depth and contact phases are dimensionless. The deliverable and the
  control use the identical baseline.
- **Dedicated analytic control scene (Blender-rendered, required).** A separate scene,
  `tests/scenes/hmxb_control.py`, is rendered through Blender CPU: a spherical opaque
  donor of radius `R_star` (the donor's Roche-lobe radius `R_L` — its volume-equivalent
  radius), a point emitter at the compact object, and a circular edge-on orbit. Its
  measured contacts and depth are compared **directly** to the closed-form solution below.
  The Roche + slim-disk deliverable is *not* the analytic control: it is compared to the
  same closed form only through the flux-based criterion below.
- **Analytic control solution.** Eclipse duration fraction `f_eclipse = arcsin(R_star /
  a) / pi` (e.g. `R_star / a = 0.5` gives `f = 1/6`). For inclination `i < 90 deg` use
  the Kopal 1959 geometric contact condition for a circular orbit; the control contacts
  are the exact geometric contact phases of that condition.
- **Eclipse duration fraction** matches the analytic control **within 2% relative error
  in `f_eclipse`** — a relative tolerance, not `±0.02` of an orbit. Not weakened.
- **Contact detection (reproducible, flux-based).** From the phase-folded normalised curve
  `F(phi)` on the declared phase grid: let `D = 1 − min F` be the mid-eclipse depth. Define
  the partial-contact level `L1 = 1 − D/2` and the full-occultation level `L2 = 1 − 0.95 D`.
  Contacts are the linear-interpolation crossings of those levels on the bracketing
  samples: **1st** = first falling crossing of `L1`, **2nd** = first falling crossing of
  `L2`, **3rd** = last rising crossing of `L2`, **4th** = last rising crossing of `L1`.
  `f_eclipse = phase(4th) − phase(1st)` (total duration including partial phases); ingress
  is `phase(2nd) − phase(1st)`, egress is `phase(4th) − phase(3rd)`. For the point emitter
  `L2` is reached only at the minimum, so 2nd = 3rd within one phase step.
- **Slim-disk emitter contact geometry.** The pkg43 slim disk is a finite-thickness
  volumetric emitter with inner/outer radii, so its projected silhouette is **not**
  assumed to be a circle and no projected radius `R_emit` is used for contacts. Contacts
  for the extended emitter are defined solely by the flux-based criterion above; this
  makes the full-occultation condition reproducible from the sampled curve alone.
- **Eclipse depth tolerance.** Depth `= 1 − min F`, with absolute tolerance `±0.01` in
  normalised flux against the analytic occulted fraction (full for the point control;
  the flux-based `D` for the extended emitter). `(frozen 2026-09-22, lead may adjust)`
- **Ingress/egress phase tolerance.** All four contact phases match the analytic control
  within `±0.005` in orbital phase (absolute). `(frozen 2026-09-22, lead may adjust)`
- **Phase-resolution convergence:** halving the phase step changes `f_eclipse` by
  `< 0.5 %`.
- **Non-eclipsing control run:** at an inclination low enough that no eclipse occurs
  (`R_star` no longer crosses the line of sight), the light curve shows only ellipsoidal
  modulation, with no occultation dip.
- **Uncertainty allocation (frozen 2026-09-22, lead may adjust).** Each phase point is
  rendered with the declared sample count and `N_seed = 5` independent seeds; report the
  mean and the 95% CI (`1.96 × SEM`). The Monte-Carlo CI half-width on `f_eclipse` must be
  `≤ 0.5 %` relative and the phase-grid extraction error `≤ 0.5 %` relative, so the
  combined uncertainty `≤ 1 %` relative is strictly below the 2% acceptance tolerance.
- **Ellipsoidal amplitude** matches the analytic Fourier amplitude (Avni & Bahcall 1975;
  Morris & Naftilan 1993) **within 10%**.
- The figure reports the stated Monte-Carlo 95% CI; CPU is the oracle.

#### Phases

- **Phase 1 (this package):** geometry + eclipse + ellipsoidal modulation; the tolerances
  above.
- **Phase 2 (separate package, not specified here):** X-ray microphysics, wind
  structure, and any hydrodynamics. This package must not pre-empt those choices.

---

## Acceptance criteria

- [ ] `scripts/hmxb_lightcurve.py` renders one period and writes the phase-folded normalised light-curve figure and its raw frame data.
- [ ] The dedicated sphere/point control scene (`tests/scenes/hmxb_control.py`) renders through Blender CPU on a circular edge-on orbit, and its measured contacts and depth match the closed-form solution directly.
- [ ] Eclipse duration fraction is within **2% relative error** of the analytic `f_eclipse = arcsin(R_star/a)/pi` (Kopal 1959 contact condition for `i < 90 deg`).
- [ ] Ingress/egress contact phases are within `±0.005` (absolute orbital phase) and eclipse depth is within `±0.01` (normalised flux) of the analytic control, using the flux-based contact criterion (the extended slim-disk emitter claims no projected-radius geometry).
- [ ] Repeated seeded renders (`N_seed = 5`) give a 95% CI half-width on `f_eclipse` of `≤ 0.5 %` relative, and the combined Monte-Carlo + phase-extraction uncertainty is `≤ 1 %` relative — strictly below the 2% acceptance tolerance.
- [ ] Halving the phase step changes `f_eclipse` by `< 0.5 %`.
- [ ] A non-eclipsing control run shows only ellipsoidal modulation, with no occultation dip.
- [ ] Ellipsoidal amplitude is within 10% of the analytic Fourier amplitude for the declared geometry.
- [ ] The scene builds and renders from `tests/scenes/hmxb_phase1.py` via Blender on the CPU oracle.
- [ ] The reference-bank scene dir has `scene.py`, `gates.toml`, and `notes.md`, and its gates pass.
- [ ] No new xfails.

---

## Non-goals

- Do not add hydrodynamics or MHD.
- Do not choose X-ray microphysics (wind, Comptonisation, spectra) — Phase 2 decides.
- Do not model wind-fed accretion.
- Do not claim absolute flux calibration; the deliverable is a normalised light curve.
- Do not add GPU GR work (stage-plan §1b fixes this lane to CPU).

---

## Progress

- [ ] Fix and record the declared geometry (`P`, `a`, `i`, `q`, donor `T_eff`).
- [ ] Implement the analytic Roche-surface donor and circular-orbit scene in `tests/scenes/hmxb_phase1.py`.
- [ ] Implement and Blender-CPU-render the dedicated sphere/point control scene (`tests/scenes/hmxb_control.py`); compare its contacts directly to the closed-form solution.
- [ ] Wire the pkg43 slim disk as the compact-object emission model.
- [ ] Implement `scripts/hmxb_lightcurve.py` and render the period with `N_seed = 5` independent seeds per phase point.
- [ ] Compute eclipse-duration (relative error in `f_eclipse`), ingress/egress (flux-based contacts), depth, and ellipsoidal-amplitude checks against the analytic values; report the 95% CI and combined uncertainty budget; commit the figure.
- [ ] Run the phase-resolution convergence check and the non-eclipsing inclination control.
- [ ] Register the reference-bank scene and pass its gates.

---

## Lessons

*(Fill in after the package is done.)*

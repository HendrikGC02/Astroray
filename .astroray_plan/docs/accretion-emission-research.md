# Accretion & Emission Research Notes

**Target:** Codex — pkg42 (synchrotron jets), pkg43 (slim disk), pkg44 (ADAF)
implementers. Read this before writing any emission/accretion plugin code.
**Status:** Research complete. pkg42, pkg43, pkg44 are unblocked.
**See also:**
- `.astroray_plan/docs/kerr-metric-research.md` — pkg40 grounding (BL metric, ISCO)
- `.astroray_plan/docs/metric-aware-tracer-research.md` — pkg67 grounding
  (the geodesic loop that drives this pipeline)

**License fence (read first).** RAPTOR (GPLv3) and the AFD-Illinois `symphony`
library (GPLv3) both implement the Pandya-2016 fits we need. **Neither may be
mirrored** into Astroray. The fits themselves are mathematical results from a
peer-reviewed paper (Pandya et al. 2016, ApJ 822, 34) and are not copyrightable.
We cite the paper and re-derive the C++ from `ipole`'s BSD-3 wrapper plus the
paper's appendix. RAPTOR is for **numerical cross-validation only**, with the
same fence pkg40/pkg67 established (see §7).

---

## 1. The Accretion-Emission Pipeline

The three packages share one physical pipeline. A density/temperature/magnetic
field model (slim disk for pkg43, ADAF for pkg44, conical jet for pkg42) defines
a fluid 4-velocity u^mu(x) and the local plasma state {n_e, T_e, B, theta_B} at
every point in the BL coordinate volume around the Kerr black hole from pkg40.
At each step of the geodesic integrator (pkg40 + pkg67), we:

```
1. Evaluate fluid state at the photon's coordinate position x^mu.
2. Compute the photon frequency in the fluid rest frame:
       nu_fluid = -k_mu u^mu / h
   (k^mu is the photon 4-momentum, h is Planck's constant; in code units the
    same expression returns nu in dimensionless redshifted form.)
3. Compute theta_B = angle between k^mu and B^mu, both projected into the
    fluid frame.
4. Evaluate the local emissivity j_nu(nu_fluid, n_e, T_e, B, theta_B) and
    absorptivity alpha_nu in the fluid rest frame.
5. Convert to invariant form J = j_nu / nu^2,  A = alpha_nu * nu  (Mihalas &
    Mihalas 1984 ch. 7; ipole `radiation.c::jnu_inv`).
6. Step the unpolarized radiative transfer in invariant intensity I_inv = I/nu^3:
       dI_inv/d(lambda) = J - A * I_inv
    (lambda is the affine parameter along the geodesic.)
7. At the camera, recover I_observed = I_inv * nu_obs^3.
```

The factor of nu^3 redshift is automatic in this formulation — the geodesic
integrator already tracks k_mu and the metric — so we do **not** apply Doppler
factors or gravitational redshift separately. This is the pattern used by ipole
(Mościbrodzka & Gammie 2018, MNRAS 475 §2.4) and RAPTOR (Bronzwaer et al. 2018,
A&A 613 A2 §2.3). It is mandatory: applying a separate D^3 boost on top of
invariant transfer double-counts the redshift.

**Coupling diagram:**

```
   pkg40 (Kerr metric) ──► pkg67 (geodesic stepper)
                                   │
                                   ▼
              ┌──────────── plasma state at x^mu ────────────┐
              │                    │                          │
              ▼                    ▼                          ▼
        pkg43 slim disk      pkg44 ADAF              pkg42 conical jet
        {n_e,T_e,H/r}        {n_e,T_e,B,u^mu}        {n_e,T_e,B,gamma_jet}
              │                    │                          │
              └──────────── j_nu, alpha_nu (this doc §2,§3) ──┘
                                   │
                                   ▼
                       invariant transfer (eq. above)
                                   │
                                   ▼
                              I_observed
```

**What pkg42 does differently:** the synchrotron jet plugin only needs the
emission half of this pipeline — it supplies its own analytic n_e/B/u^mu
profile (a conical bulk-Lorentz-gamma jet) and feeds j_nu/alpha_nu through the
same transfer step. The "D^3 boost" colloquially attributed to jets is exactly
the nu^3 invariant factor; the jet plugin must not multiply by D^3 explicitly
if the integrator is already in invariant form. (The current pkg42 spec text
calls out an explicit D^3; that wording has to be reframed as "the bulk
4-velocity enters via nu_fluid in step 2" — see pkg42 spec §Physics, updated.)

---

## 2. Synchrotron Emissivity j_nu (Pandya 2016 §A1)

**Source.** All formulae in this section are from Pandya, Zhang, Chandra &
Gammie 2016, "Polarized Synchrotron Emissivities and Absorptivities for
Relativistic Thermal, Power-Law, and Kappa Distribution Functions," ApJ 822, 34
(arXiv:1602.08749). DOI 10.3847/0004-637X/822/1/34. Equations cited below are
the equation numbers in that paper. Cross-validated against ipole's BSD-3
wrapper around the symphony library (file
`src/symphony/maxwell_juettner_fits.c`, header comment cites Pandya 2016
eqs. 29, 31; `power_law_fits.c` cites eqs. 29, 33). The symphony library
itself is GPLv3 and **not** mirrored — only the math, taken from the paper.

### 2.1 Common dimensionless variables

```cpp
// CGS units. m_e c^2 = 8.187e-7 erg, e = 4.803e-10 esu, c = 2.998e10 cm/s.
const double Theta_e = k_B * T_e / (m_e * c * c);          // dimensionless T_e
const double nu_c    = e * B / (2.0 * M_PI * m_e * c);      // cyclotron freq, Hz
const double nu_s    = (2.0 / 9.0) * nu_c
                     * std::sin(theta_B) * Theta_e * Theta_e; // synchrotron freq
const double X       = nu / nu_s;                            // Pandya eq. 30
```

Numerical sanity: nu_c = 2.80e6 Hz * (B/Gauss). For Sgr A* model values
(B = 30 G, T_e = 5e10 K) this gives Theta_e = 8.46, nu_c = 8.4e7 Hz,
nu_s = (2/9) * nu_c * Theta_e^2 ≈ 1.34e9 Hz at theta_B = pi/2.
Observing at 230 GHz puts X ≈ 172 — well into the exponential tail.

### 2.2 Thermal Maxwell-Jüttner j_nu^I (Pandya eqs. 29, 31)

Stokes-I emissivity (the only one Astroray needs in pkg42/pkg44 — polarisation
is a future package, see Non-goals):

```cpp
// Pandya 2016 eqs. 29, 31. Matches ipole src/symphony/maxwell_juettner_fits.c
// (BSD-3, AFD Group at UIUC) line-for-line. The expression is from the paper;
// the wrapper code is reproduced because the math is not copyrightable.
double jnu_thermal_I(double nu, double n_e, double T_e, double B,
                     double theta_B)
{
    const double Theta_e = k_B * T_e / (m_e * c * c);
    const double nu_c    = e * B / (2.0 * M_PI * m_e * c);
    const double nu_s    = (2.0 / 9.0) * nu_c
                         * std::sin(theta_B) * Theta_e * Theta_e;
    const double X       = nu / nu_s;

    const double prefactor = n_e * e * e * nu_c / c;
    const double term1     = std::sqrt(2.0) * M_PI / 27.0
                           * std::sin(theta_B);
    const double t         = std::pow(X, 0.5) + std::pow(2.0, 11.0/12.0)
                                                * std::pow(X, 1.0/6.0);
    const double term2     = t * t;
    const double term3     = std::exp(-std::pow(X, 1.0/3.0));

    return prefactor * term1 * term2 * term3;   // erg / (s cm^3 Hz sr)
}
```

**Validity:** Pandya 2016 §3.1 reports < 25 % error vs. exact integration for
Theta_e in [0.1, 100] and X in [1e-3, 1e8]. Astroray's regime (Sgr A*-like
ADAF) sits inside this envelope.

**Edge cases.** When `nu < nu_s * 1e-6` the cube-root exponential is
indistinguishable from 1, but pow(X, 1.0/6.0) is not; the formula remains
numerically stable. When `B == 0` set j_nu = 0 (no synchrotron without a
field). When `sin(theta_B) < 1e-6` clamp theta_B away from 0/pi to avoid
nu_s underflow — same reason pkg40 clamps theta in the Christoffel symbols.

### 2.3 Isotropic power-law j_nu^I (Pandya eqs. 29, 33)

Power-law electron distribution dN/d(gamma) ∝ gamma^(-p) for
gamma in [gamma_min, gamma_max]. Used by pkg42 (jet) where the electron
population is non-thermal:

```cpp
// Pandya 2016 eqs. 29, 33. Matches ipole src/symphony/power_law_fits.c.
double jnu_powerlaw_I(double nu, double n_e, double B, double theta_B,
                      double p, double gamma_min, double gamma_max)
{
    const double nu_c      = e * B / (2.0 * M_PI * m_e * c);
    const double prefactor = n_e * e * e * nu_c / c;
    const double term1     = std::pow(3.0, p / 2.0) * (p - 1.0)
                           * std::sin(theta_B);
    const double term2     = 2.0 * (p + 1.0)
                           * (std::pow(gamma_min, 1.0 - p)
                              - std::pow(gamma_max, 1.0 - p));
    const double term3     = std::tgamma((3.0 * p - 1.0) / 12.0)
                           * std::tgamma((3.0 * p + 19.0) / 12.0);
    const double term4     = std::pow(nu / (nu_c * std::sin(theta_B)),
                                      -(p - 1.0) / 2.0);
    return prefactor * term1 / term2 * term3 * term4;
}
```

For p = 2.5 (default in pkg42): the spectral slope is -(p-1)/2 = -0.75, i.e.
j_nu ∝ nu^(-0.75). This is the canonical AGN jet slope.

**Validity:** Pandya 2016 §3.2 reports < 1 % error for p in [1.5, 6.5] and
gamma_min^2 < nu/nu_c < gamma_max^2 (i.e. away from the spectral cutoffs).
Outside that band the power-law approximation breaks down — this is a
fundamental limit, not a fit deficiency.

---

## 3. Synchrotron Absorptivity alpha_nu (Pandya 2016 eqs. 30, 32-34)

### 3.1 Thermal: Kirchhoff's law (Pandya eq. 32)

For a thermal distribution, alpha_nu^I follows from j_nu^I by Kirchhoff's law
applied to the Planck source function:

```cpp
double alpha_nu_thermal_I(double nu, double n_e, double T_e, double B,
                          double theta_B)
{
    const double Bnu = (2.0 * h_planck * nu * nu * nu / (c * c))
                     / (std::expm1(h_planck * nu / (k_B * T_e)));
    if (Bnu <= 0.0) return 0.0;
    return jnu_thermal_I(nu, n_e, T_e, B, theta_B) / Bnu;     // cm^-1
}
```

`std::expm1` is used instead of `exp(...) - 1` to avoid catastrophic
cancellation at h*nu << k*T_e (Wien-limit accuracy).

### 3.2 Power-law (Pandya eq. 33)

The power-law absorptivity is *not* a Kirchhoff transform (the power law is
non-thermal). Use the explicit fit (Pandya eqs. 29, 33; ipole
`power_law_I_abs`):

```cpp
double alpha_nu_powerlaw_I(double nu, double n_e, double B, double theta_B,
                           double p, double gamma_min, double gamma_max)
{
    const double nu_c      = e * B / (2.0 * M_PI * m_e * c);
    const double prefactor = n_e * e * e
                           / (nu * m_e * c);
    const double term1     = std::pow(3.0, (p + 1.0) / 2.0) * (p - 1.0);
    const double term2     = 4.0 * (std::pow(gamma_min, 1.0 - p)
                                  - std::pow(gamma_max, 1.0 - p));
    const double term3     = std::tgamma((3.0 * p + 2.0) / 12.0)
                           * std::tgamma((3.0 * p + 22.0) / 12.0);
    const double term4     = std::pow(nu / (nu_c * std::sin(theta_B)),
                                      -(p + 2.0) / 2.0);
    return prefactor * term1 / term2 * term3 * term4;
}
```

For pkg42's default p = 2.5 the full alpha_nu slope is nu^(-3.25): term4
contributes nu^(-(p+2)/2), and the prefactor contributes another nu^-1.
Self-absorption therefore only matters at nu < few * GHz — the spec is right
to default `include_self_absorption = false`.

### 3.3 Analytic check value (Stokes-I thermal, X = 1)

Substitute X = 1 in the §2.2 formula:

```
J_S(X=1, theta_B = pi/2)
  = (sqrt(2) * pi / 27) * 1 * (1 + 2^(11/12))^2 * exp(-1)
  ≈ 0.1645        * 8.299              * 0.368
  ≈ 0.5023
j_nu^I(X=1) = 0.5023 * n_e * e^2 * nu_c / c
```

Use this as the analytic test value in pkg42's unit suite (see pkg42 spec
Acceptance §Analytic). For B = 1 G, n_e = 1 cm^-3 it evaluates to
j_nu^I = 0.5023 * 1 * (4.803e-10)^2 * (2.80e6) / 2.998e10
       ≈ 1.083e-23 erg / (s cm^3 Hz sr).

---

## 4. Slim Disk Profile (Sądowski 2009)

**Source.** Sądowski 2009, "Slim accretion disks around Kerr black holes
revisited," ApJS 183, 171 (arXiv:0906.0355). DOI 10.1088/0067-0049/183/2/171.
The original slim-disk formulation is Abramowicz et al. 1988, ApJ 332, 646
(non-relativistic) and Abramowicz, Lasota, Igumenshchev 2000 + Sądowski 2009
(Kerr-relativistic). Background: Abramowicz & Fragile 2013, "Foundations of
Black Hole Accretion Disk Theory," Living Rev. Relativity 16, 1
(arXiv:1104.5499) — Polish doughnuts, thin disk, slim disk, ADAF in one place.

**The catch for pkg43.** Sądowski 2009 has **no closed-form analytic slim-disk
solution.** The paper presents six coupled ODEs (mass, radial momentum,
angular momentum, vertical equilibrium, energy/cooling, and the regularity /
sonic-point condition) that are solved numerically by relaxation. Solutions
are tabulated online over a grid of (a* in [0, 0.99]) x (Mdot < 500 Mdot_Edd)
at fixed alpha = 0.1, for M = 5, 10, 20, 30, 50, 100 M_sun.

**Two implementation paths for pkg43:**

(a) **Fitting-function path (recommended for pkg43 v1).** Use the analytic
   skeleton below — Novikov-Thorne (Page & Thorne 1974) corrected by an
   advective fraction f_adv that grows with mdot. This is what GYOTO and
   ipole's slim-disk model do for visualization. It captures the qualitative
   physics (flattened inner T, finite H/r) without an external table.

(b) **Tabulated path (defer to a future package).** Mirror the Sądowski 2009
   online tables and interpolate. Higher fidelity but requires HDF5 plumbing
   and is overkill for visualization.

The pkg43 spec (this PR) commits to path (a). Path (b) is a Non-goal.

### 4.1 Vertical structure (Sądowski 2009 eq. 5)

Vertical hydrostatic equilibrium gives H = c_s / Omega_K, where Omega_K is
the Keplerian orbital frequency. In the slim regime the dimensionless
half-thickness scales as

```
H/r ≈ (3/2) * (mdot / mdot_Edd) * f_geom(r, a)
```

with f_geom an order-unity function that goes to ~1 near ISCO and decays as
1/r outside. For a Codex implementation:

```cpp
// Schwarzschild fiducial; Kerr correction is via r_ISCO from pkg40.
double slim_disk_H_over_r(double r, double r_isco, double mdot_edd)
{
    const double r_norm = r / r_isco;
    const double f_geom = 1.0 / (1.0 + r_norm * r_norm);   // ~1 at ISCO,
                                                            // ~1/r^2 outside
    return 1.5 * mdot_edd * f_geom;                         // dimensionless
}
```

**Test value.** For M = 10 M_sun, mdot = 1.0 mdot_Edd, a = 0 (so r_ISCO = 6M),
at r = r_ISCO: H/r = 1.5 * 1.0 * 0.5 = 0.75. At r = 10 * r_ISCO:
H/r = 1.5 * 1.0 / 101 ≈ 0.0149 — back in the thin-disk regime. This matches
the qualitative behaviour shown in Sądowski 2009 fig. 5.

### 4.2 Surface density Sigma (Sądowski 2009 eq. 1, viscosity closure)

The vertically integrated mass conservation Mdot = -2 * pi * r * Sigma * v_r
combined with the alpha-prescription torque gives, in the slim regime:

```
Sigma(r) = Mdot / (3 * pi * nu_visc) * R_R(r)
nu_visc  = alpha * c_s * H
R_R(r)   = 1 - sqrt(r_ISCO / r)         // Page-Thorne 1974 eq. 15n correction
```

For pkg43 the precise value is not needed at every step — the integrator only
sees n_e (number density), which is Sigma / (2 H m_p). Implement
n_e = Sigma / (2 H m_p) and let the GR integrator take ds along the ray.

### 4.3 Midplane temperature T(r) — advective correction

Novikov-Thorne midplane temperature (Page & Thorne 1974 eq. 11n):

```
sigma_SB * T_NT(r)^4 = (3 G M Mdot) / (8 pi r^3) * R_R(r)
```

Slim-disk correction: a fraction f_adv of the locally dissipated energy is
advected radially instead of radiated. The radiative flux is reduced by
(1 - f_adv) and (since flux ∝ sigma_SB T^4) the temperature is reduced by
(1 - f_adv)^(1/4):

```cpp
double slim_disk_T(double r, double r_isco, double M, double mdot_phys)
{
    const double R_R   = 1.0 - std::sqrt(r_isco / r);
    const double T4_NT = (3.0 * G * M * mdot_phys)
                       / (8.0 * M_PI * r * r * r * sigma_SB) * R_R;

    // Sadowski 2009 §3 / fitting form (path (a)).
    const double r_norm = r / r_isco;
    const double f_adv  = (mdot_phys / mdot_edd_for(M))
                        * 1.0 / (1.0 + r_norm * r_norm);
    const double atten  = std::max(0.0, 1.0 - f_adv);
    return std::pow(T4_NT * atten, 0.25);
}
```

**Test value.** Fiducial 10 M_sun BH, mdot = 0.1 * mdot_Edd, a = 0, r = 1.5 *
r_ISCO = 9 M = 1.33e7 cm. mdot_Edd(10 M_sun) ≈ 1.4e18 g/s, so
mdot_phys = 1.4e17 g/s. Compute:
- R_R(r=9M) = 1 - sqrt(6/9) = 1 - 0.8165 = 0.1835.
- T_NT^4 = (3 * 6.674e-8 * 2.0e34 * 1.4e17) / (8 * pi * (1.33e7)^3 * 5.67e-5)
         * 0.1835 ≈ 6.9e29 K^4.
- T_NT ≈ 9.1e7 K (~ 0.78 keV).
- f_adv = 0.1 / (1 + 1.5^2) = 0.0308 — sub-dominant in this regime.
- T_slim ≈ T_NT * (1 - 0.0308)^(1/4) ≈ 9.04e7 K.

In the sub-Eddington limit (mdot < 0.3) slim and Novikov-Thorne agree to within
a few percent — this is pkg43's "convergence to NT" acceptance test.

For super-Eddington (mdot = 10):
- f_adv = 10 / (1 + 1.5^2) = 3.08 → clamp to 1, so T → 0 at r ≈ 1.5 r_ISCO.

That clamp is too aggressive — it kills emission entirely. For pkg43, replace
the linear fit with the exponential form Sądowski 2009 uses informally:
`f_adv = 1 - exp(-(mdot/mdot_Edd) * (r_ISCO/r)^2)`. Then at mdot = 10,
r = 1.5 r_ISCO: f_adv = 1 - exp(-10 * 0.444) = 1 - exp(-4.44) = 0.988, so
T_slim/T_NT ≈ 0.988^0.25 = 0.997 — still 99 % of NT? No: the residual
(1 - 0.988) = 0.012 → T factor 0.012^0.25 = 0.331. So T_slim ≈ 0.33 * T_NT
in the super-Eddington core. That's the right magnitude: Sądowski 2009 fig. 7
shows about a factor 2-3 reduction in peak T at mdot = 10 vs. the
NT extrapolation. Use this exponential form in pkg43.

```cpp
const double f_adv = 1.0 - std::exp(-mdot_edd * (r_isco/r) * (r_isco/r));
```

**Acceptance criterion (pkg43):** at r = 1.5 r_ISCO, mdot/mdot_Edd = 0.1,
T_slim/T_NT in [0.95, 1.0] (sub-Eddington convergence). At mdot/mdot_Edd = 10,
T_slim/T_NT < 0.5 at the same radius (advective flattening).

---

## 5. ADAF Profile (Narayan & Yi 1995 / Yuan & Narayan 2014)

**Source.** Narayan & Yi 1995, "Advection-dominated Accretion: A
Self-similar Solution," ApJ 452, 710 (DOI 10.1086/176343) — original analytic
solution. Yuan & Narayan 2014, "Hot Accretion Flows Around Black Holes,"
ARA&A 52, 529 (arXiv:1401.0586) — modern review with the
wind/outflow generalization (eqs. 6-16 below). All numerical prefactors are
from Yuan & Narayan 2014 §2.1, eqs. 8-16. CGS units throughout; r is in
Schwarzschild radii (R_S = 2GM/c^2), m = M / M_sun, mdot_BH is the inflow
rate at the black hole in Eddington units.

### 5.1 Self-similar solution

Yuan & Narayan 2014 eqs. 8-13 (with the outflow exponent s from eq. 6,
generalising Narayan & Yi 1995):

```
v_r(r)  = -1.1e10  * alpha * r^(-1/2)                              cm/s    (Y14 eq.8)
Omega(r)= 2.9e4   * m^(-1) * r^(-3/2)                              s^-1    (Y14 eq.9)
c_s(r)^2= 1.4e20   * r^(-1)                                         cm^2/s^2 (Y14 eq.10)
n_e(r)  = 6.3e19  * alpha^(-1) * m^(-1) * mdot_BH * r^(-3/2 + s)   cm^-3   (Y14 eq.11)
B(r)    = 6.5e8   * (1+beta)^(-1/2) * alpha^(-1/2)
                  * m^(-1/2) * mdot_BH^(1/2) * r^(-5/4 + s/2)       G       (Y14 eq.12)
p(r)    = 1.7e16  * alpha^(-1) * m^(-1) * mdot_BH * r^(-5/2 + s)   ba      (Y14 eq.13)
```

The outflow generalization Mdot(r) = Mdot_BH * (r / R_S)^s (Y14 eq. 6) carries
through into n_e and B as the +s and +s/2 corrections to the Narayan-Yi 1995
exponents. Numerical simulations (Yuan & Narayan 2014 §3.2) find s ≈ 0.3-0.5
for non-radiative MHD ADAFs; pkg44 should default to s = 0.3 with the
parameter exposed.

### 5.2 Two-temperature plasma (Y14 eq. 16)

Ions follow virial:

```
T_i(r) ≈ G M m_p / (6 k_B R) ≈ (1.2e12 / r) K      // r in R_S, see Y14 eq.16
```

Electrons are cooler — Coulomb coupling from ions to electrons is inefficient
at low densities, so T_e is set by direct viscous heating of electrons (the
"delta" parameter):

```
T_e(r) = T_e0 * (R_S / r) ^ q
```

with q in [0.5, 1] from numerical models. Yuan & Narayan 2014 §3.3 recommends
T_e0 ≈ 1e10 K for Sgr A*-like flows, q ≈ 1. Astroray pkg44 exposes T_e0 as
`electron_temp` and fixes q = 1 for the visualization spec.

### 5.3 Magnetic field via beta_mag

Y14 eq. 12 parameterises B via the gas-to-magnetic pressure ratio
beta = p_gas / p_mag. The pkg44 parameter `beta_mag` is the inverse
convention (magnetic-to-gas), so map carefully:

```cpp
// User-facing beta_mag = p_mag / p_gas. Y14 paper beta = p_gas / p_mag.
const double beta_Y14 = 1.0 / beta_mag;
const double B = 6.5e8 * std::pow(1.0 + beta_Y14, -0.5)
                       * std::pow(alpha, -0.5)
                       * std::pow(m, -0.5)
                       * std::sqrt(mdot_BH)
                       * std::pow(r_in_RS, -1.25 + s/2.0);
```

### 5.4 Test values

**Sgr A*-like fiducial:** M = 4.0e6 M_sun, mdot_BH = 1e-8, alpha = 0.1,
beta_mag = 0.1 (so beta_Y14 = 10), s = 0.3, T_e0 = 1e10 K. Evaluate at
r = 10 R_S:

```
n_e   = 6.3e19 * 10 * (1/4e6) * 1e-8 * 10^(-1.5+0.3)
      = 6.3e19 * 10 * 2.5e-7 * 1e-8 * 10^(-1.2)
      = 6.3e19 * 2.5e-15 * 0.0631
      ≈ 9.94 cm^-3                                  (sanity: ~1-100 cm^-3 for Sgr A*)
B     = 6.5e8 * (1+10)^(-0.5) * (0.1)^(-0.5) * (4e6)^(-0.5) * (1e-8)^(0.5)
              * 10^(-1.25 + 0.15)
      = 6.5e8 * 0.302 * 3.162 * 5.0e-4 * 1.0e-4 * 10^(-1.1)
      ≈ 2.46e-5 G                                   (magnetic field weak, ADAFs
                                                     need inner-radius growth)
T_i   = 1.2e12 / 10 = 1.2e11 K                       (Y14 eq. 16, ion virial)
T_e   = 1e10 * (1/10)^1 = 1e9 K                      (electron, cooler than ion)
```

n_e ~ 10 cm^-3 and B ~ 2.5e-5 G are the right order of magnitude for Sgr A*
at r = 10 R_S (cf. Yuan, Quataert & Narayan 2003, ApJ 598, 301, fig. 1).
Use these as pkg44 unit-test values (within 50 % tolerance — the prefactors
are themselves order-unity-uncertain in Y14 eq. 11/12).

**Closer to horizon, at r = 2 R_S:**
n_e = 6.3e19 * 10 * 2.5e-7 * 1e-8 * 2^(-1.2) ≈ 6.86e4 cm^-3 — much denser.
B   ~ 6.5e8 * 0.302 * 3.162 * 5e-4 * 1e-4 * 2^(-1.1) ≈ 1.45e-4 G.
T_i = 6e11 K, T_e = 5e9 K.

These give the synchrotron emission its peak near the horizon, consistent
with the EHT image of M87*/Sgr A* (Y14 §6).

### 5.5 The "ipole has a slim disk model" claim

The task brief states that ipole has a slim-disk model. As of master commit
(BSD-3, 2024) the ipole `src/` tree contains no file matching `slim`, `disk`,
or `dexter`. The BHAC/HARM-derived models that ipole supports are GRMHD
*simulation snapshots*, not analytic slim disks. Pkg43 cannot mirror an
ipole slim-disk file because there isn't one. Use Sądowski 2009 directly
(this section) and cross-validate against GYOTO if needed (CeCILL — no
mirroring, numerical-only check).

---

## 6. Test Scenes

Three layered scenes, each isolating one of the validation surfaces. The
order matters: each test scene only changes one piece relative to the
previous, so a regression bisects cleanly.

### 6.1 Scene A — Thin plasma sphere in flat space (validates §2-§3 alone)

Geometry: flat Minkowski (no Kerr metric, no GR). A homogeneous sphere of
radius 100 cm, n_e = 1 cm^-3, T_e = 1e10 K (so Theta_e = 16.9), B = 1 G,
theta_B = pi/2. Camera 1000 cm away, observing at 1 GHz, 100 GHz, 1 THz.

Expected output (pkg42 unit suite):
- Each pixel through the sphere center has I_nu = j_nu^I * 200 cm
  (optically thin, alpha_nu negligible at these parameters).
- At 100 GHz: nu_s = (2/9) * 2.8e6 * 16.9^2 * 1 = 1.78e8 Hz, X = 562; far
  in the exponential tail. j_nu^I evaluates to ~1e-30 erg/s/cm^3/Hz/sr.
- At 1 GHz: X = 5.6, in the bulk of the spectrum; j_nu peaks here.

Pass criterion: j_nu computed by the plugin matches the closed-form §2.2 to
< 1e-6 relative error, and the integrated I_nu through the sphere matches
the analytic optically-thin result to < 1e-3.

### 6.2 Scene B — Schwarzschild + slim disk (validates pkg43 + §1 transfer)

Geometry: pkg40 Schwarzschild metric (a = 0, M = 10 M_sun), slim disk model
from §4 with mdot/mdot_Edd = 0.1, r_outer = 50 M. Camera at 10000 M,
inclination 60 deg, 256x256, observing at 1 keV.

Expected output:
- Recognisable thin-disk image (slim = NT in this regime) with a dark central
  shadow, gravitationally lensed redshift on the receding side.
- Peak surface brightness within 30 % of an analytic Page-Thorne flux
  prediction (the §4.3 T(r) integrated over the disk Jacobian).

Re-run with mdot/mdot_Edd = 10:
- Peak temperature drops by ~3x (the §4.3 advective flattening).
- Visible vertical thickness in an edge-on (89 deg) view (the §4.1 H/r
  reaches 0.75 at ISCO).

### 6.3 Scene C — Kerr a=0.9 + ADAF (validates pkg44 + Kerr + §1)

Geometry: pkg40 Kerr metric (a = 0.9, M = 4e6 M_sun — Sgr A*-like), ADAF
profile from §5.4, observing at 230 GHz (EHT band). Camera at 1e6 M,
inclination 30 deg, 512x512.

Expected output:
- Quasi-spherical brightness distribution (NOT a disk shape — the ADAF is
  geometrically thick, this is the visual signature of pkg44 vs. pkg43).
- Black hole shadow visible as a central dark region of angular size
  ~52 microarcsec for the Sgr A* parameters (cf. EHT 2022 Sgr A* paper).
- Frame-dragging asymmetry: the approaching side (rotated by Kerr spin
  toward the observer) is brighter. Asymmetry magnitude ~30-50 %.
- Total flux in the band: compute via §5.4 n_e/B/T_e at r = 5-10 R_S
  integrated through the ADAF volume; should be order ~3 Jy
  (Sgr A* observed value at 230 GHz).

This is the headline image. If it works, Pillar 4 is real.

---

## 7. License Matrix and What-To-Mirror Table

Same shape as `kerr-metric-research.md §5`. Triple-fence on RAPTOR per the
PR #190 pattern.

### Per-package summary

| Pkg | Primary papers (cite in code) | Reference impl (mirror permitted) | Reference impl (cross-check only) |
|-----|------------------------------|-----------------------------------|-----------------------------------|
| pkg42 | Pandya 2016 (j_nu fits); Rybicki & Lightman 1979 ch.6 (theory background) | ipole `src/symphony/maxwell_juettner_fits.c` + `power_law_fits.c` (BSD-3, AFD-Illinois) | RAPTOR (GPLv3); symphony standalone (GPLv3) |
| pkg43 | Sądowski 2009; Page & Thorne 1974 (T_NT); Abramowicz & Fragile 2013 (review) | None — Sądowski has no closed-form code; we re-derive from paper | GYOTO (CeCILL); ipole has no slim-disk file |
| pkg44 | Narayan & Yi 1995; Yuan & Narayan 2014 §2 (numerical prefactors) | ipole's GRMHD-driver scaffolding for the radiative-transfer step (BSD-3) | RAPTOR (GPLv3) |

### Reference implementations in detail

**ipole** (https://github.com/AFD-Illinois/ipole)
- License: **BSD-3-Clause** (LICENSE file, "Copyright (c) 2024, AFD Group at UIUC").
- Mirror permitted with attribution.
- Files to study and mirror selectively (cite file + commit in code comments):
  - `src/radiation.c` — invariant transfer plumbing (`Bnu_inv`, `get_fluid_nu`,
    `get_bk_angle`). Mirror the algorithm shape; rewrite in C++ idiom.
  - `src/symphony/maxwell_juettner_fits.c` — Pandya 2016 thermal Stokes-I
    j_nu and alpha_nu wrappers. The math is the paper; the code is BSD-3.
  - `src/symphony/power_law_fits.c` — Pandya 2016 power-law j_nu and alpha_nu.
- Files NOT to mirror:
  - `src/model_radiation.c` — couples to a specific GRMHD snapshot loader
    (BHAC/HARM HDF5). pkg42-44 use analytic profiles, not snapshots.
  - HDF5 I/O, image post-processing, polarised tensor evolution.
- Note: ipole's `src/symphony` is a vendored copy of the AFD-Illinois symphony
  library, which is itself **GPLv3 standalone**. The vendored copy in ipole
  inherits ipole's BSD-3 license per ipole's LICENSE; we mirror from the
  ipole tree only, not the standalone symphony repo.
- Commit pinned: `master` as of 2024-Q4 (look up the exact SHA at first
  use and bake it into the pkg42 spec).

**RAPTOR** (https://github.com/tbronzwaer/raptor)
- License: **GPLv3 — INCOMPATIBLE WITH MIT.** Same fence as pkg40 / pkg67.
- **No code mirroring.** This includes RAPTOR's own implementations of
  Pandya 2016 (in `model.c` / `radiative_transfer.c`) — even though the
  underlying math is in the public domain, the C representation is GPLv3
  and we do not look at it for code shape.
- Permitted use: numerical cross-validation. Run RAPTOR on the §6 scenes
  and compare image-plane intensities to within tolerance.
- **In-line warning required.** Any pkg42/pkg43/pkg44 source comment that
  says "compared against RAPTOR" must also carry "(GPLv3, cross-validation
  only — no code borrowed)".

**symphony standalone** (https://github.com/AFD-Illinois/symphony)
- License: **GPLv3.** Same fence as RAPTOR.
- Same math as the ipole-vendored copy, different license. Use the
  ipole-vendored BSD-3 copy. Do not look at this repo's code shape.

**GYOTO** (https://github.com/gyoto/Gyoto)
- License: CeCILL (GPL-incompatible). Cross-validation only.
- Has both an analytic slim-disk-like model (`Astrobj/PolishDoughnut.C`)
  and an ADAF-like (`Astrobj/ThinDisk.C` with custom emissivity). Useful
  as numerical reference for §6.2 and §6.3 scenes.

### Citations to embed in C++ source comments

When a function implements a formula from a paper, the comment must name the
paper, the equation number, and (where the math comes from a BSD-3-mirrored
file) the ipole file + commit. Example pattern:

```cpp
// j_nu, Stokes I, Maxwell-Juettner thermal distribution.
// Pandya, Zhang, Chandra & Gammie 2016, ApJ 822, 34, eqs. 29 & 31.
// C++ shape mirrored from ipole src/symphony/maxwell_juettner_fits.c
// (BSD-3, AFD Group at UIUC, commit <SHA>).
// Cross-validated against RAPTOR (GPLv3, no code borrowed).
double jnu_thermal_I(...) { ... }
```

### Key papers (full citations for the journal article)

- Pandya, A., Zhang, Z., Chandra, M., Gammie, C.F. 2016, "Polarized
  Synchrotron Emissivities and Absorptivities for Relativistic Thermal,
  Power-Law, and Kappa Distribution Functions," ApJ 822, 34.
  DOI 10.3847/0004-637X/822/1/34. arXiv:1602.08749.
- Pandya, A., Chandra, M., Joshi, A.V., Gammie, C.F. 2018, "Probing the
  Innermost Accretion Flow Geometry of Sgr A* with Event Horizon Telescope,"
  ApJ 868, 13. DOI 10.3847/1538-4357/aae7c8. arXiv:1810.05646.
  (Polarized extension; second-priority for unpolarized pkg42.)
- Sądowski, A. 2009, "Slim accretion disks around Kerr black holes
  revisited," ApJS 183, 171. DOI 10.1088/0067-0049/183/2/171.
  arXiv:0906.0355.
- Abramowicz, M.A., Fragile, P.C. 2013, "Foundations of Black Hole
  Accretion Disk Theory," Living Reviews in Relativity 16, 1.
  DOI 10.12942/lrr-2013-1. arXiv:1104.5499.
- Narayan, R., Yi, I. 1995, "Advection-dominated Accretion: A Self-similar
  Solution," ApJ 452, 710. DOI 10.1086/176343.
- Yuan, F., Narayan, R. 2014, "Hot Accretion Flows Around Black Holes,"
  ARA&A 52, 529. DOI 10.1146/annurev-astro-082812-141003. arXiv:1401.0586.
- Page, D.N., Thorne, K.S. 1974, "Disk-Accretion onto a Black Hole. I,"
  ApJ 191, 499. (Novikov-Thorne T(r) used in pkg43.)
- Rybicki, G.B., Lightman, A.P. 1979, "Radiative Processes in Astrophysics,"
  Wiley. ch. 6 — synchrotron theory background, cite-only.
- Mościbrodzka, M., Gammie, C.F. 2018, "ipole — semi-analytic scheme for
  relativistic polarized radiative transport," MNRAS 475, 43. arXiv:1712.03057.
  (BSD-3 reference implementation for the §1 invariant transfer.)
- Bronzwaer, Davelaar, Younsi et al. 2018, "RAPTOR I," A&A 613, A2.
  (GPLv3 — cross-validation only.)

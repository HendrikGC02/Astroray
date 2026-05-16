#include "astroray/adaf.h"
#include "astroray/register.h"

// pkg44 ADAF (advection-dominated accretion flow) plugin.
// Physics model:
// - Self-similar solution: Narayan & Yi 1995 power-law profiles in r.
// - Numerical prefactors: Yuan & Narayan 2014 ARA&A §2.1 eqs. 8-16.
// - Two-temperature plasma: T_ion ~ 10^12 K (virial), T_e ~ 10^9-10^11 K.
// - Emission: thermal synchrotron (Pandya 2016, reused from pkg42) + thermal
//   bremsstrahlung (Karzas & Latter 1961 Gaunt factor).
//
// References:
// - Narayan, R., Yi, I. 1995, "Advection-dominated Accretion: A Self-similar
//   Solution," ApJ 452, 710. DOI 10.1086/176343. Original analytic ADAF solution.
// - Yuan, F., Narayan, R. 2014, "Hot Accretion Flows Around Black Holes,"
//   ARA&A 52, 529. DOI 10.1146/annurev-astro-082812-141003. arXiv:1401.0586.
//   Numerical prefactors (eqs. 8-16), outflow exponent s, beta convention.
// - Pandya, A., Zhang, Z., Chandra, M., Gammie, C.F. 2016, ApJ 822, 34.
//   Thermal synchrotron emissivity (Stokes I Maxwell-Jüttner fit, eqs. 29 & 31).
//   Reused from pkg42 synchrotron.h (BSD-3 ipole-derived, GPLv3 RAPTOR not mirrored).
// - Karzas, W.J., Latter, R. 1961, ApJS 6, 167. Gaunt factor for bremsstrahlung.
// - Rybicki, G.B., Lightman, A.P. 1979, "Radiative Processes in Astrophysics,"
//   ch. 5 eq. 5.14b. Bremsstrahlung emissivity formula.
//
// License fence:
// - RAPTOR (GPLv3) implements both Narayan-Yi profile and Pandya 2016 fits.
//   Cross-validation only; no code mirrored. The formulae are public-domain
//   mathematical results from peer-reviewed papers.
// - ipole (BSD-3) provides the invariant transfer scaffolding and the Pandya 2016
//   wrapper (vendored symphony). Mirrored with attribution (see pkg42 and
//   accretion-emission-research.md §7).
// - GYOTO (CeCILL, GPL-incompatible) has ADAF-like models. Cross-check only.
//
// The C++ expressions for Yuan & Narayan 2014 eqs. 8-16 are original, derived
// from the research note .astroray_plan/docs/accretion-emission-research.md §5.

using ADAFPlugin = astroray::adaf::ADAF;

ASTRORAY_REGISTER_EMISSION("adaf", ADAFPlugin)

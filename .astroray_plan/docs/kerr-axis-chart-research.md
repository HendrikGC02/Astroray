# Kerr BL polar-axis singularity: Kerr-Schild chart switch (#897) — Research

## Problem
Boyer-Lindquist (BL) is singular at sin(theta)=0. Near the spin axis
dphi/dlambda ~ L_z/sin^2(theta) is stiff; `integrateGeodesic`'s RK45 sat on its
h=0.001 floor, rejected steps used up `maxSteps` and the ray was reported
captured: a dotted dark column at image x=0 in equatorial views (a=0 and 0.94).
Baseline repro: centre column of a 101^2 equatorial probe shifted 1e-3 world
units off the axis captured 101/101 rows (expected 25-27).

## Paper
- **GRay2:** Chan, Medeiros, Ozel & Psaltis, "GRay2: A General Purpose Geodesic
  Integrator for Kerr Spacetimes", ApJ 867, 59 (2018), DOI:10.3847/1538-4357/aadfe5,
  arXiv:1706.07062. Integrates in Cartesian Kerr-Schild (KS) because BL's pole
  and horizon singularities need special handling and cost accuracy.
- **KS form:** Visser, "The Kerr spacetime: a brief introduction",
  arXiv:0706.0622 (2007), §3: g_{mu nu} = eta + f l l, inverse eta - f l l,
  f = 2Mr^3/(r^4 + a^2 z^2), l = (1, (rx+ay)/(r^2+a^2), (ry-ax)/(r^2+a^2), z/r),
  r^4 - (R^2 - a^2) r^2 - a^2 z^2 = 0.

## Reference implementation
None copied. GRay2's source is used only as the published method; the
Hamiltonian derivatives and the BL<->KS covector transform were derived here.

## What we reproduce
- Chart atlas: BL everywhere (unchanged results), Cartesian KS while
  |sin theta| < 0.1, back to BL above 0.2 (hysteresis). KS step <= 0.1 r so a
  KS leg cannot skip the equatorial disk. Termination/disk logic stays in BL.
- Ingoing KS: X + iY = (r + ia) sin(theta) e^{i(phi + Phi(r))}, Z = r cos(theta),
  t_KS = t + T(r); Phi' = a/Delta, T' = 2Mr/Delta (closed forms in
  `grks::phiShift/timeShift`). Covectors: p_BL = J^T p_KS.
- H = (eta p p - f (l.p)^2)/2; dx/dlambda = eta p - f L l; dp_i = f_,i L^2/2 + f L l_j,i p_j.

## Verification (scratch scripts, 2026-09-25)
- J g_BL^{-1} J^T = eta - f l l to 4e-10 (a=0.94); the other 7 sign
  conventions fail at 1e-2..0.5.
- Analytic KS RHS vs finite differences of H: 1e-10.
- Near-axis ray (theta 0.4 -> 0.06), DOP853 rtol 1e-12: BL vs BL->KS->BL end
  states agree to 3e-8 (a=0) / 8e-8 (a=0.94); L_z drift 1e-9.

## Integration in Astroray
- `include/astroray/gr_integrator.h` (`grks::`, switch in `integrateGeodesic`),
  `Metric::kerrSpin` opt-in (Schwarzschild a=0, Kerr, schwarzschild plugin).
- Tests: `tests/test_issue897_gr_spin_axis.py`; the x=0 exclusion in
  `tests/test_issue896_gr_exit_continuation.py` is removed.

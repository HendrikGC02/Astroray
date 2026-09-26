# Volumetric invariant transport (pkg283) — Research

## Paper
- Rybicki & Lightman 1979, *Radiative Processes in Astrophysics*, §1.4–1.5
  (transfer equation, Kirchhoff α = j/B_ν) and §4.9 (invariants I_ν/ν³,
  j_ν/ν², ν α_ν). ISBN 0-471-82759-2.
- Lindquist 1966, Ann. Phys. 37, 487 (covariant transfer d(I/ν³)/dλ).
- Younsi, Wu & Fuerst 2012, A&A 545, A13, eqs. 29–31 (GR form, ν = −k·u).
- Mościbrodzka & Gammie 2018, MNRAS 475, 43 (ipole).
- Lind & Blandford 1985, ApJ 295, 358: a steady jet brightens as D^{2+α}
  per lab-frame path, a discrete blob as D^{3+α}. Used as a sanity check.

## Reference implementation
- ipole, https://github.com/AFD-Illinois/ipole @ `7f7a482cf91125aeeeb9c431485bba680e8941d7`,
  BSD-3-Clause. It is permissive, so it is compatible with Astroray. No code copied.
  - `src/radiation.c::get_fluid_nu`: ν = −k·u.
  - `src/model_radiation.c::jar_calc_dist`: jI = j_ν/ν², aI = α_ν·ν.
  - `src/ipolarray.c::approximate_solve`: ℐ_f = ℐ_i e^{−Δτ} + (J/A)(1 − e^{−Δτ}),
    with a Taylor branch when Δτ is small.
- GYOTO is GPL-3.0. We did not use it: the analytic slab oracles are enough here.

## What we reproduce
- Invariant intensity ℐ = I_ν/ν³, with dℐ/dλ = J − A ℐ, J = j_ν(ν_em)/ν_em²,
  A = ν_em α_ν(ν_em), ν_em = −k·u. Observed I = ν_obs³ ℐ.
- The Astroray volumetric chord is a straight line in the flat frame of the
  static observer. There, k = ν_obs(1, n̂) with n̂ the propagation direction,
  u = γ(1, β), so ν_em = ν_obs γ(1 − β·n̂), and dλ = ds_lab/ν_obs.
- Front-to-back chord march: I += T·ΔI_seg, T *= e^{−Δτ_seg}. This is exact
  for a piecewise-uniform medium.

## Consequence (double counting)
Per lab-frame length, the optically thin result is ν_obs³ J dλ = g² j(ν_obs/g) ds_lab.
g³ multiplies the fluid-frame intensity j·L_fluid, and L_fluid = ds_lab/g.
The old jet code multiplied D³ by the *lab* path, which counts one extra power of D.

## Deliberately not taken
- There is no geodesic bending of the volumetric chord and no gravitational
  redshift of the volumetric emitters. This limitation predates pkg283: the chord
  is flat. ADAF keeps its existing static fluid (u = ∂_t, g = 1). Orbital or
  inflow velocity would be new ADAF physics, which the spec rules out as a
  non-goal. The transport function takes u, so the tests can drive moving emitters.
- No polarisation and no Faraday terms.

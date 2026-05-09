# Kerr Metric Research Notes

**Target:** Codex — pkg40 implementer. Read this before touching any metric code.
**Status:** Research complete. pkg40 is unblocked.
**See also:** `.astroray_plan/docs/metric-aware-tracer-research.md` (pkg67 grounding)

---

## 1. Coordinate Choice: Boyer-Lindquist (BL)

Two principal coordinate systems exist for the Kerr metric.

**Boyer-Lindquist (BL):** Coordinates (t, r, θ, φ). The metric is diagonal except for
a g_{tφ} cross-term (frame-dragging). All Christoffel symbols have analytic closed-form
expressions. The coordinate system becomes ill-defined at the outer horizon r_+ because
the metric determinant diverges there (Δ → 0). Integration must terminate before
reaching r_+; the existing code uses r < r_+ + 0.5M as the capture condition.

**Kerr-Schild (KS):** Adds a null vector term to flatten the metric at the horizon.
Regular everywhere including through r_+, which makes it preferable for GPU integrators
that want to trace rays all the way to the singularity without artificial capture
thresholds. The metric is more complex: g_{rr} has an off-diagonal t-r coupling, and
the Christoffel symbols are harder to compute analytically.

**Recommendation: use Boyer-Lindquist for pkg40.**

Reasons:
- Both RAPTOR (Bronzwaer et al. 2018) and ipole (Mościbrodzka & Gammie 2018) use BL
  as their primary coordinate system. Our implementation can be directly cross-validated
  against their numerical output.
- Analytic Christoffel symbols reduce per-step cost vs. numerical finite-difference.
- The horizon capture threshold (r < r_+ + 0.5M) already handles the singularity
  cleanly for CPU integration; the pkg40 spec codifies this.
- Kerr-Schild is reserved for a future GPU port (noted in Non-goals of pkg40 spec and
  astrophysics.md §4.1).

GYOTO (Vincent et al. 2011) also defaults to BL with a similar capture strategy, providing
independent cross-validation of this design choice.

---

## 2. Metric Components in Boyer-Lindquist Coordinates

Geometric units throughout: G = c = 1. Spin parameter: a = J/M, with |a| ≤ M.
Thorne's (1974) astrophysical bound is a ≤ 0.998M; the pkg40 spec enforces this.

**Intermediate scalar quantities** (compute once per evaluation):

```
double sigma = r*r + a*a*cos_th*cos_th;          // Σ = r² + a²cos²θ
double delta = r*r - 2.*M*r + a*a;               // Δ = r² - 2Mr + a²
double A_    = (r*r + a*a)*(r*r + a*a)
             - delta * a*a * sin_th*sin_th;        // A = (r²+a²)² - Δa²sin²θ
```

**Covariant metric g_{μν}** — six non-zero entries (five unique values):

```
g_dd[0][0] = -(1. - 2.*M*r / sigma);             // g_{tt}
g_dd[1][1] =  sigma / delta;                      // g_{rr}
g_dd[2][2] =  sigma;                              // g_{θθ}
g_dd[3][3] =  A_ / sigma * sin_th*sin_th;         // g_{φφ}
g_dd[0][3] = -2.*M*a*r * sin_th*sin_th / sigma;   // g_{tφ}
g_dd[3][0] =  g_dd[0][3];                         // g_{φt} = g_{tφ}
```

**Contravariant metric g^{μν}** — also six non-zero entries:

```
g_uu[0][0] = -A_ / (sigma * delta);               // g^{tt}
g_uu[1][1] =  delta / sigma;                      // g^{rr}
g_uu[2][2] =  1. / sigma;                         // g^{θθ}
g_uu[3][3] = (delta - a*a*sin_th*sin_th)
           / (sigma * delta * sin_th*sin_th);      // g^{φφ}
g_uu[0][3] = -2.*M*a*r / (sigma * delta);         // g^{tφ}
g_uu[3][0] =  g_uu[0][3];                         // g^{φt}
```

These are the eight independent metric functions referenced in the pkg40 spec.
Cross-check: substitute a=0. Then g_{tφ} = 0, Δ = r²-2Mr, Σ = r², A = r⁴ — you
recover the Schwarzschild metric in Schwarzschild coordinates.

Source: formulae cross-validated against RAPTOR `metric.c` (GPLv3; math content
is from Kerr 1963, derived textbook result — not copyrightable) and ipole
`src/geometry.c` (BSD-3).

---

## 3. Christoffel Symbols in Boyer-Lindquist Coordinates

The geodesic equation is d²X^α/dλ² = -Γ^α_{μν} (dX^μ/dλ)(dX^ν/dλ).

Define helper variables (re-use the scalars above, plus):

```
double sigma3 = sigma * sigma * sigma;             // Σ³
double s2     = 2.*r*r - sigma;                    // 2r² - Σ  (appears in many terms)
double sin_th = sin(theta),  cos_th = cos(theta);
double sincos = sin_th * cos_th;
```

**20 unique non-zero Christoffel symbols** (Γ^α_{μν} = Γ^α_{νμ} — lower indices
are symmetric, so 32 total entries in the connection array including copies):

```
// --- t index (alpha=0) ---
gamma[0][0][1] =  (r*r + a*a) / (sigma*sigma * delta) * s2;         // Γ^t_{tr}
gamma[0][0][2] = -2.*M*a*a*r * sincos / (sigma*sigma);               // Γ^t_{tθ}
gamma[0][1][3] = -M*a * sin_th*sin_th / (sigma * delta)
               * (2.*r*r/sigma * (r*r + a*a) + r*r - a*a);           // Γ^t_{rφ}
gamma[0][2][3] =  2.*M*a*a*a*r * sin_th*sin_th * sincos / (sigma*sigma); // Γ^t_{θφ}

// --- r index (alpha=1) ---
gamma[1][0][0] =  M * delta / sigma3 * s2;                           // Γ^r_{tt}
gamma[1][1][1] = (M - r) / delta + r / sigma;                        // Γ^r_{rr}
gamma[1][1][2] = -a*a * sincos / sigma;                               // Γ^r_{rθ}
gamma[1][2][2] = -r * delta / sigma;                                  // Γ^r_{θθ}
gamma[1][0][3] = -M*a * delta * sin_th*sin_th / sigma3 * s2;         // Γ^r_{tφ}
gamma[1][3][3] = -delta * sin_th*sin_th / sigma
               * (r - a*a*sin_th*sin_th / (sigma*sigma) * s2);        // Γ^r_{φφ}

// --- theta index (alpha=2) ---
gamma[2][0][0] = -2.*M*a*a*r * sincos / sigma3;                      // Γ^θ_{tt}
gamma[2][1][1] =  a*a * sincos / (sigma * delta);                     // Γ^θ_{rr}
gamma[2][1][2] =  r / sigma;                                          // Γ^θ_{rθ}
gamma[2][2][2] = -a*a * sincos / sigma;                               // Γ^θ_{θθ}
gamma[2][0][3] =  2.*M*a*r*(r*r + a*a) * sincos / sigma3;            // Γ^θ_{tφ}
gamma[2][3][3] = -sincos / sigma3
               * ((r*r+a*a)*A_ - sigma*delta*a*a*sin_th*sin_th);      // Γ^θ_{φφ}

// --- phi index (alpha=3) ---
gamma[3][0][1] =  M*a / (sigma*sigma * delta) * s2;                  // Γ^φ_{tr}
gamma[3][0][2] = -2.*M*a*r * cos_th / (sigma*sigma * sin_th);        // Γ^φ_{tθ}
gamma[3][1][3] =  r/sigma
               - a*a*sin_th*sin_th/(sigma*delta)*(r - M + 2.*r*r/sigma); // Γ^φ_{rφ}
gamma[3][2][3] =  cos_th/sin_th * (1. + 2.*M*a*a*r*sin_th*sin_th/(sigma*sigma)); // Γ^φ_{θφ}
```

**Symmetry copies** (fill before the geodesic integration loop, not inside it):

```
gamma[0][1][0] = gamma[0][0][1];   gamma[0][3][0] = gamma[0][0][3];
gamma[0][2][0] = gamma[0][0][2];   gamma[0][3][1] = gamma[0][1][3];
gamma[0][3][2] = gamma[0][2][3];
gamma[1][3][0] = gamma[1][0][3];   gamma[1][2][1] = gamma[1][1][2];
gamma[2][3][0] = gamma[2][0][3];   gamma[2][2][1] = gamma[2][1][2];
gamma[3][1][0] = gamma[3][0][1];   gamma[3][2][0] = gamma[3][0][2];
gamma[3][3][1] = gamma[3][1][3];   gamma[3][3][2] = gamma[3][2][3];
```

Note on Γ^φ_{tθ}: this term is singular at the poles (sin θ → 0). RAPTOR addresses
this by clamping θ away from 0 and π; do the same in pkg40.

Note on Γ^r_{rr}: the formula above assumes standard (non-log-scale) r coordinate.
RAPTOR uses log(r) for its radial grid — the rfactor correction does not apply to
pkg40 which uses physical Boyer-Lindquist r directly.

Source: formulae derived from Bardeen, Press & Teukolsky 1972 (ApJ 178, 347,
§II); cross-validated against RAPTOR `metric.c` BL branch (commit 08cb9a2) and
ipole `src/geometry.c` (commit 7f7a482). Math content is in the public domain;
no RAPTOR code is mirrored (GPLv3 — see §5).

---

## 4. Analytic Test Values for pkg40

All values below are in geometric units G = c = 1. Source: Bardeen, Press &
Teukolsky 1972 (ApJ 178, 347, hereafter BPT 1972).

### ISCO Radius

The ISCO (innermost stable circular orbit) satisfies the BPT 1972 equations (2.21):

```
Z_1 = 1 + (1 - a*a/(M*M))^(1./3.)
    * ( (1 + a/M)^(1./3.) + (1 - a/M)^(1./3.) )
Z_2 = sqrt( 3.*a*a/(M*M) + Z_1*Z_1 )
r_ISCO_prograde  = M * (3. + Z_2 - sqrt((3. - Z_1)*(3. + Z_1 + 2.*Z_2)))
r_ISCO_retrograde = M * (3. + Z_2 + sqrt((3. - Z_1)*(3. + Z_1 + 2.*Z_2)))
```

Numerical targets for the test suite:

| Spin | r_ISCO (prograde) | r_ISCO (retrograde) |
|------|-------------------|---------------------|
| a=0  | 6.000 M (exact)   | 6.000 M             |
| a=0.998 M | 1.237 M      | 8.995 M             |

Tolerance for pkg41 regression: |r_computed - r_analytic| / r_analytic < 1e-6.

### Photon Sphere Radius

Unstable circular photon orbits (photon sphere) satisfy (BPT 1972, §II):

```
r_ph_prograde  = 2.*M * (1. + cos( 2./3. * acos(-a/M) ))
r_ph_retrograde = 2.*M * (1. + cos( 2./3. * acos(+a/M) ))
```

Numerical targets:

| Spin | r_ph (prograde) | r_ph (retrograde) |
|------|-----------------|-------------------|
| a=0  | 3.000 M (exact) | 3.000 M           |
| a=0.998 M | 1.073 M  | 3.998 M           |

### Frame-Dragging Angular Velocity at the Horizon

The angular velocity of the horizon (equivalently, of ZAMOs at r = r_+):

```
r_plus = M + sqrt(M*M - a*a);                      // outer horizon
Omega_H = a / (r_plus*r_plus + a*a);               // = a / (2*M*r_plus)
```

Target: for a = 0.998M → Ω_H ≈ 0.4694 c/M (i.e., 0.4694 in geometric units).
Derivation: r_+ = M(1 + sqrt(1 - 0.998²)) = 1.0632 M; then
Ω_H = 0.998M / (2M · 1.0632M) = 0.4694 M^{-1}.

This is the angular velocity that photons must co-rotate at to hover at the horizon
(ergosphere effect). A test that checks frame-dragging asymmetry in a rendered image
should see the approaching side of the accretion disk boosted relative to the
receding side, with the asymmetry scale set by Ω_H.

---

## 5. Reference Implementations: Licenses and What to Mirror

### RAPTOR (Bronzwaer et al. 2018 / 2020)

- **Repo:** https://github.com/tbronzwaer/raptor
- **Commit:** `08cb9a2bba526dc7f0ee91e59ff7e178d0e709a1` (master, 2023-08-29)
- **License:** **GPLv3** — NOT MIT (the task brief misstated this; the pkg67 spec
  correctly says GPLv3). GPLv3 is incompatible with Astroray's license. **No code
  mirroring permitted.**
- **What to use it for:** Cross-validation of Christoffel symbol expressions and
  integration output. When in doubt about a sign or factor-of-2, run RAPTOR against
  the same initial conditions and compare photon trajectories.
- **Files to study:** `metric.c` (BL metric + Christoffel symbols), `integrator.c`
  (RK4/RK2/Verlet geodesic driver). The analytic BL connection in `connection_udd`
  (not the numerical `connection_num_udd`) is what to cross-check against.
- **Integrator note:** RAPTOR uses fixed RK4 with an adaptive step size function
  `stepsize()` that scales dl based on coordinate velocity magnitudes. The geodesic
  equation is d²X^μ/dλ² = -Γ^μ_{νρ} k^ν k^ρ where k^μ = dX^μ/dλ.

### ipole (Mościbrodzka & Gammie 2018)

- **Repo:** https://github.com/AFD-Illinois/ipole
- **Commit:** `7f7a482cf91125aeeeb9c431485bba680e8941d7` (master)
- **License:** BSD-3-Clause — mirroring permitted.
- **What to mirror:** Algorithmic content from `src/geodesics.c` (the 2nd-order
  symplectic `push_photon` scheme) and `src/geometry.c` (BL metric in
  `gcov_ks`/`gcov_func`). Always cite the file and commit in code comments.
- **What NOT to mirror:** GRMHD-model coupling, radiation transfer coefficients,
  HDF5 SANE/MAD model loading. Those are domain-specific to GRRMHD disk simulations.
- **Integrator note:** ipole uses a **2nd-order symplectic (leapfrog/Störmer-Verlet)**
  scheme, not RK4: a half-position step, then Christoffel evaluation at the midpoint,
  then a full momentum step. This is more stable than RK4 for Hamiltonian systems with
  no energy input. For pkg40, the pkg40 spec calls for Dormand-Prince RK4/5; implement
  that, but note that ipole's 2nd-order symplectic is a valid cross-validation reference
  — both should trace the same geodesics within tolerance.

### GYOTO (Vincent et al. 2011)

- **Repo:** https://github.com/gyoto/Gyoto
- **License:** CeCILL (GPL-incompatible). **Do NOT mirror code or close paraphrases.**
- **Permitted use:** Numerical cross-validation only. Run GYOTO independently on the
  same scenes and compare photon ring positions, ISCO orbits, frame-dragging asymmetry.
  Where RAPTOR and GYOTO agree, trust the result; where they disagree, flag for review.

### Key Papers to Cite in Code Comments

- Bardeen, Press & Teukolsky 1972. "Rotating black holes: locally nonrotating frames,
  energy extraction, and scalar synchrotron radiation." ApJ 178, 347–369.
  DOI 10.1086/151796. (ISCO and photon sphere formulae.)
- Bronzwaer, Davelaar, Younsi et al. 2018. "RAPTOR I." A&A 613, A2.
  (Null geodesic integration in Kerr; cross-validation source.)
- Mościbrodzka & Gammie 2018. "ipole." MNRAS 475, 43.
  (Covariant polarized ray-tracing; BSD-3 reference implementation.)

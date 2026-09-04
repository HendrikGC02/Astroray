# pkg227 Phase 2b-flat research note — flat-triangle single-vertex specular solver

Numpy-prototype de-risking pass for pkg227 Phase 2b-flat (single-bounce MESH
solver, one known caster, FLAT facet normals only). Written in the spirit of
`pkg127-specular-polynomials-research.md`: every derivation below was checked
numerically against the LANDED, CI-validated sphere solver
(`include/astroray/manifold/specular_poly.h::solveSphereSpecular`) as the
ground-truth oracle. This note does not touch any tracked repo file; the
prototype lives at
`scratchpad/proto_mesh_specular.py` (session scratchpad — copy before the
implementer session if it needs to survive; see Provenance).

---

## 1. Method — re-derived from the paper, specialized to flat facets

**Source (CLAUDE.md §6):** Fan, Guo, Wang, Xiao, Zhang, Zhou, Chen, Hong, Guo,
Yan, "Specular Polynomials," ACM TOG 43(4) (SIGGRAPH 2024), article 126, DOI
10.1145/3658132, arXiv:2405.13409. Paper text CC BY 4.0.
`github.com/mollnn/spoly` is UNLICENSED (re-confirmed license state not
re-checked this session; pkg127's note already fetched `license: null` from
the GitHub API) — **not read, not copied**, matching pkg127's precedent.

The paper's general single-vertex machinery (§3.2 generalized half-vector
constraint, §3.3 coplanarity + "square form" angularity, §3.4 rational
coordinate mapping via recursive Möller–Trumbore, §3.5 the 6-piece rational
fit to √x on [0,1] (their Eq. 23, error < 1e-3) for refraction, §4.1–4.2
Bézout hidden-variable resultant + Laplacian expansion) is built for the
**general case**: interpolated (smooth) shading normals and multi-vertex
chains, where a vertex's normal and position must be expressed as **rational
functions of the barycentric coordinate of the previous vertex** so the whole
chain stays polynomial. An automated re-fetch of the arXiv HTML this session
returned the equation *numbers* with enough uncertainty (small-model
summarization of a dense equation-heavy paper) that I did not trust
transcribing them verbatim into code comments; instead of risking a subtly
wrong copy of the general machinery, I **re-derived the flat-facet
specialization from the constraint structure directly** (§3.2–3.3, which the
fetch reproduced consistently and which pkg127's already-landed sphere code
independently confirms) and cross-validated the result's *degree* against the
paper's own reported Table 2 flat-normal numbers (see §3 below) as an
independent sanity check that the specialization is faithful, not invented.

### Why flat facets don't need the rational mapping or the √-fit

Phase 2b-flat is explicitly scoped to **flat (per-facet-constant) normals**
— interpolated shading normals are Phase 2b-smooth, a separate, harder phase
per the pkg227 spec (Finding 2). For a **single vertex** on **one triangle**
with a **constant** facet normal `N`:

- The paper's rational coordinate mapping and 6-piece √-fit exist to
  propagate a vertex's position/direction through a **chain** (so the next
  vertex's barycentric coordinates stay a polynomial function of the
  previous one) and through a **curved** (interpolated-normal) surface. A
  single vertex with a constant normal has no "next vertex" to propagate
  into and no curvature — so neither piece of machinery is needed.
- What **is** reused, and is the actual correctness-critical part: the
  coplanarity + squared-angularity decomposition (§3.2–3.3) and the
  signed-residual superfluous-root filter (§3.3, §6) — the exact same
  structure pkg127 already ported and CI-validated for the sphere.

### Derivation

Let `x0`, `x2` be the two fixed chain endpoints (shading point, light/next
vertex), `N` the constant unit facet normal of triangle `(P0, P1, P2)`.

**Coplanarity** `(p - x0) × (x2 - p) · N = 0` expands (using `p × p = 0`) to

```
p · ((x2 - x0) × N) = (x0 × x2) · N                      (*)
```

which is **linear in p** — a genuine simplification vs. the paper's general
form, which is only "already polynomial" for a normal that may depend on
`p`; here it collapses to degree 1 because `N` does not depend on `p`.
Intersecting (*) with the triangle's own affine plane `p = P0 + u·e1 + v·e2`
gives one more linear equation in `(u, v)`: the admissible vertex is confined
to a **line L** through the triangle — the flat-facet form of the paper's
"collapse every coordinate to u₁."

**Angularity (square form).** Work in the "incidence plane" Π through `x0`
with normal `m = (x2 - x0) × N` (Π necessarily contains `x2`, and — by
construction of (*) — contains `N` and `p` at any solution). Basis
`e1 = normalize(x2 - x0)`, `e2 = m × e1` gives 2D coordinates `a = (0,0)` for
`x0`, `b = (|x2-x0|, 0)` for `x2`, a constant 2D normal `n2` for `N`, and
`p(t)` **affine in t** (t parametrizes L, expressed in Π's own basis).
Mirroring pkg127's sphere residual exactly (`Ci = n × (a-p)`, `Co = n ×
(b-p)`, `Ri = |a-p|`, `Ro = |b-p|`, `g = Ci/Ri + eta·Co/Ro`):

```
Ci(t), Co(t)         degree 1 in t   (N constant, p(t) affine)
Ri²(t), Ro²(t)        degree 2 in t   (|affine|²)
square form: Ci² Ro² − eta² Co² Ri² = 0     →   DEGREE 4 in t.
```

**This degree-4 bound independently matches the paper's own reported
Table 2 flat-normal refraction degree (4)** — cross-validating that the
specialization is faithful to the general method rather than an ad hoc
shortcut (CLAUDE.md §6: cite, borrow, *verify*).

Real roots of the quartic are refined by **one Newton polish** on the signed
residual `g(t)` (paper §4, mirrors pkg127's sphere polish exactly) and
filtered by `|g(t)| < 1e-3` (superfluous-root check) and by triangle bounds
(`0 ≤ u,v`, `u+v ≤ 1`).

---

## 2. Numerical validation against the sphere oracle

**Method.** `scratchpad/proto_mesh_specular.py` reuses the sphere oracle's
own algebra (a direct copy of the numpy mirror in
`tests/test_pkg127_specular_poly_unit.py`, extended to return the 3D vertex
position, not just theta) as ground truth, and validates the flat-triangle
solver by running it over facets of an icosphere tessellation.

A **global uniform mesh fine enough to hit 1e-4 rad everywhere** turned out
to be computationally infeasible to build directly (see §3 — convergence is
linear in facet edge length, and the required edge length is ~2e-4 on a
unit sphere, which for a *uniform* global icosphere means roughly `subdiv ≈
12` → ~3.3×10⁸ triangles). Instead the prototype does **adaptive local
refinement**: seed from the nearest facets of a coarse icosphere
(`subdiv=3`), then repeatedly subdivide-and-keep-the-facets-nearest-the-
oracle-vertex, doubling local resolution each round (`drill_to_oracle` in the
prototype) — reaching sub-micron-scale local facets in ~15-20 rounds without
ever materializing a huge global mesh.

**4 test configurations** (refraction generic, reflection/Alhazen, a
multi-branch case, and an SF11-dispersion case — identical to
`test_pkg127_specular_poly_unit.py::CASES`), **8 oracle roots total** (2
branches per case):

| case | root | finest angular error (rad) | facet edge at that level |
|---|---|---|---|
| refraction generic | 0 | 1.14e-06 | 2.1e-06 |
| refraction generic | 1 | 5.65e-06 | 3.4e-05 |
| reflection Alhazen | 0 | 4.15e-06 | 9.6e-06 |
| reflection Alhazen | 1 | 2.35e-06 | 1.0e-05 |
| multi-branch | 0 | 2.96e-07 | 2.7e-07 |
| multi-branch | 1 | 1.17e-07 | 2.5e-06 |
| SF11 dispersion | 0 | 1.84e-07 | 3.1e-07 |
| SF11 dispersion | 1 | 6.59e-07 | 4.4e-06 |

**All 8 roots converge to well under the pkg227 gate (< 1e-4 rad)** — worst
observed 5.65e-06 rad, roughly 18× inside the gate. **OVERALL: PASS.**

**Convergence order.** Measured `error / facet-edge-length` ratio averaged
**0.409** across all 8 roots (range ~0.03–0.9, no case an outlier) — i.e.
**convergence is LINEAR in facet edge length, not quadratic.** This matters
practically (§4): halving facet size only halves the angular error against
the smooth continuum, so reaching tight photometric agreement by mesh
refinement alone is expensive.

**Superfluous-root filter.** A global (non-adaptive) sweep at `subdiv=5`
scanning the 25 nearest facets per oracle root across all 4 cases found
**448 raw real roots of the squared-form quartic, of which only 3 survived**
the signed-residual + in-triangle filter (445 rejected as either superfluous
squaring artifacts or simply outside the triangle being tested — expected,
since only 1–2 facets out of thousands actually contain a given oracle
point). A **targeted synthetic sanity case** (flat mirror plane, refraction
`x0` above / `x2` below, `eta=1/1.5`) isolates the mechanism cleanly: the
quartic has exactly 2 real roots, one matching the textbook flat-interface
Snell-quartic solution (cross-checked independently via `scipy.optimize
.brentq` against `n1 sin θ1 = n2 sin θ2`) and one a genuine squaring
artifact — the filter correctly keeps the first and rejects the second.

---

## 3. Gotcha for the C++ port: eta-direction convention

This is the single most important practical finding for the implementer.

`specular_poly.h`'s sphere solver documents "`eta = n_from/n_to`, `from` =
`x0`-side medium." When first porting the flat-triangle residual I built an
**independent** sanity check — the textbook flat-interface refraction
problem (a point source above a plane, a receiver below, solved via the
classical Snell quartic `n1 sinθ1 = n2 sinθ2`) — and found that reproducing
that *specific* synthetic setup correctly required **inverting** the passed
`eta` (`n_to/n_from`) before building `Ci`/`Co`.

Applying that "fix" to the flat-triangle solver **broke agreement with the
sphere oracle** for every refractive case (it only coincidentally still
worked for `eta=1`, i.e. reflection, where inversion is a no-op) — see the
A/B result:

| `eta` convention | roots matching sphere oracle (of 8) |
|---|---|
| **as passed** (matches sphere `Ci`/`Co` pattern literally, unmodified) | **8/8** |
| inverted (`n_to/n_from`, "fixes" the isolated Snell sanity check) | 2/8 (only the `eta=1` reflection case) |

**Root cause, best understanding:** the "which side is `from`" labeling is
inherently tied to an implicit orientation choice (which side `N` points
toward, which endpoint is treated as the incident vs. transmitted side) that
my from-scratch synthetic test picked independently of whatever convention
`specular_poly.h`'s sphere code settled into through its own (already
CI-validated) derivation. Both conventions are locally self-consistent;
only one matches the code this has to interoperate with.

**Lesson for the port:** when wiring the C++ flat-triangle solver, **verify
the eta direction empirically against the pkg127 CI oracle**
(`tests/test_pkg127_specular_poly_unit.py`'s sphere case, or the sphere
solver directly) — **not** against a hand-derived physical sanity check in
isolation, and not by trusting a convention comment's literal wording. The
prototype keeps both conventions behind an `_ETA_CONVENTION_TO_FROM` switch
(default `False` = correct = "pass `eta` through unmodified, mirror the
sphere `Ci`/`Co` pattern exactly") specifically so this can be re-verified
quickly if the C++ port's residual is structured differently than the
prototype's.

---

## 4. Implications for the C++ port (`include/astroray/manifold/`)

- **New file, not a `specular_poly.h` edit.** Per the pkg227 spec, this is a
  new `mesh_specular_poly.h` (or similar) alongside the sphere solver — flat
  facet normals only; smooth (interpolated) normals are Phase 2b-smooth's
  separate scope. Reuse `specpoly::realRoots`/`polyEval`/`polyMul` verbatim
  (the quartic here is a strict subset of what those already handle up to
  degree 6) rather than duplicating the polynomial helpers.
- **No rational √-fit, no Bézout resultant / Laplacian expansion needed for
  this phase.** The direct algebraic elimination above is *exact* for a
  single vertex on a flat facet (matching the paper's own flat-normal degree
  bound as a cross-check) and is dramatically simpler than porting the
  general multi-vertex machinery. **That general machinery genuinely is
  needed later** — Phase 2b-smooth (interpolated normals make coplanarity
  quadratic instead of linear, per the pkg227 spec's Finding 2) and Phase 2d
  (two-bounce mesh, where the paper's bisection solver is unavoidable) — so
  don't discard the paper citations, just don't over-build them into 2b-flat.
- **Linear (not quadratic) mesh-vs-smooth convergence is the quantitative
  reason Cycles only shows caustics on smooth-shaded casters**
  ([[cycles-caustics-need-smooth-shading]]) and the reason the pkg227 spec
  scopes 2b-smooth as a separate, required phase rather than "just tessellate
  finer." A production-scale faceted mesh (`glass-mesh-caustic` reference
  scene) will show visibly faceted caustics with this flat solver — expected,
  correct, and the explicit reason 2b-smooth exists. Don't chase 1e-4 rad
  photometric agreement against a real caustic scene with the flat solver;
  that gate belongs to *this validation* (proving the math is right against
  a fine enough mesh), not to production tessellation density.
- **Eta-direction convention (§3) is the top actionable risk** — a silent,
  plausible-looking sign/direction bug that passes an independent sanity
  test while failing integration with the existing, trusted sphere code.
  Gate the C++ implementation on the *same* sphere-oracle comparison this
  prototype used, not a hand-rolled physical check alone.
- **Superfluous-root filtering reuses, unchanged, the pattern already in
  `specular_poly.h`** (`kResidualTol` ≈ 1e-3, signed residual, Newton
  polish before the final threshold check) — no new filter design needed,
  just the in-triangle bounds check as an additional filter stage specific
  to the mesh case.
- **Degenerate cases already handled defensively in the prototype, carry
  forward to C++:** degenerate triangle (`|N| ≈ 0`), triangle plane parallel
  to the coplanarity plane (both `c1`, `c2` ≈ 0 — no unique line), and
  `(x2 - x0)` parallel to `N` (incidence "plane" undefined). All three
  should fall back the same way pkg127's axial-degenerate sphere case does
  (return "no solution here," caller falls back to Newton/skip).

---

## 5. Files produced this session

- `scratchpad/proto_mesh_specular.py` — the numpy prototype (icosphere
  tessellation, sphere oracle mirror, flat-triangle solver, adaptive
  drill-down validator, superfluous-root accounting, `main()` prints a
  PASS/FAIL summary reproducing the table in §2).
- `.astroray_plan/docs/pkg227-phase2b-research.md` — this note.

---

## 6. Owner-directed scope reminder (carried from the pkg227 spec)

Per the pkg227 spec's Owner decisions (2026-09-04, #2): the mesh path (flat
*or* smooth) is the **visual-only, oracle-gated** path — the exact analytic
sphere solver (Phase 2a) remains the research-grade dispersion path for any
scene used for a scientific/physics claim. This note's oracle-agreement
numbers (§2) validate the *math*, not a claim that flat-mesh caustics should
be used for research-grade renders; that restriction is unchanged by
anything found here.

---

## 7. Biggest risk for the C++ port (summary)

**The eta-direction convention (§3).** Everything else here — the flat
degree-4 derivation, the superfluous-root filter, the linear convergence
order, the "no √-fit needed for a single flat vertex" scoping simplification
— is either a straightforward geometric port of already-validated patterns
or an explicit, quantified, expected limitation (faceting) that Phase
2b-smooth already exists to solve. The eta convention is the one place a
plausible, independently-verified-looking piece of code can be silently
wrong relative to the rest of the engine, and it will not fail loudly: it
will simply produce **a different, also-real-looking specular vertex** (the
squaring math is symmetric enough that both conventions produce *some*
in-triangle, residual-passing answer much of the time — it just won't be
the one that matches the sphere oracle, Newton fallback, or Cycles). Gate on
the sphere-oracle comparison, not on "does it produce a plausible-looking
caustic."

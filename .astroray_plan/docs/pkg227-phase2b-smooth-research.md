# pkg227 Phase 2b-smooth research note — interpolated shading normals

Numpy-prototype de-risking pass for pkg227 Phase 2b-smooth (interpolated/smooth
shading-normal support on the triangle specular solver). Same discipline as the
2b-flat note: every claim checked numerically against the LANDED sphere solver
(`solveSphereSpecular`) as the oracle. Prototype:
`scratchpad/proto_mesh_smooth.py` (session scratchpad).

---

## The question

The pkg227 spec (Finding 2) scopes 2b-smooth as its own phase because interpolated
normals make the shading normal `n̂(u,v) = normalize(n0 + u·(n1-n0) + v·(n2-n0))`
**nonlinear** in the barycentric coords, which (Fan §6) inflates the specular
polynomial degree by ~2 and adds superfluous roots. The open question was whether
Astroray must port that degree-inflated polynomial, or whether a cheaper
realization suffices.

**Tested realization:** (1) enumerate the specular *basins* with the FLAT
degree-4 quartic (Phase 2b-flat, landed), then (2) **Newton-polish** each root on
the flat facet plane using the true interpolated normal — the standard MNEE
half-vector residual (Hanika 2015 / Cycles `mnee.h`), the exact machinery
`manifold_chain.h::solveChain` already implements. Fan §6 itself recommends a
one-step Newton polish after root-finding ("roots give the basin, Newton the
digits").

## Result — the polish reaches the oracle at COARSE tessellation

Validated against the sphere oracle on an icosphere whose per-vertex normals are
the analytic sphere normals (`n_i = normalize(vertex_i)`), so a smooth-shaded
facet reproduces the true sphere normal field to first order. Angular error to the
oracle vertex, **flat solver vs flat-seed+smooth-polish, at 6 subdivision levels**
(≈ 20·4⁶ ≈ 80k-triangle-equivalent local resolution):

| case | root | flat (6lvl) | smooth-polish (6lvl) | gain |
|---|---|---|---|---|
| refraction generic | 0 | MISS (no in-facet root) | 2.22e-06 | — |
| refraction generic | 1 | 4.26e-02 | 1.12e-05 | ×3811 |
| reflection Alhazen | 0 | 4.09e-02 | 2.11e-08 | ×1.9M |
| reflection Alhazen | 1 | 3.07e-02 | 6.50e-08 | ×472k |
| multi-branch | 0 | 9.62e-03 | 3.04e-06 | ×3169 |
| multi-branch | 1 | 1.52e-03 | 1.45e-05 | ×105 |
| SF11 dispersion | 0 | 5.20e-03 | 1.70e-06 | ×3066 |
| SF11 dispersion | 1 | 2.88e-02 | 5.51e-06 | ×5226 |

**All 8 roots reach the < 1e-4 rad gate with the smooth polish** (worst 1.45e-05,
18× inside); the flat solver reaches it on NONE at this tessellation. The polish
even RECOVERS the case where the flat quartic finds no in-facet root at all
(refraction root0: seed the polish from the facet centroid).

**Convergence order.** The interpolated normal deviates from the true (smooth)
normal by O(edge²) at the facet centre, so the smooth-polished vertex converges
**quadratically** in edge length — vs the flat solver's **linear** convergence
(2b-flat note §2). This is exactly why smooth shading reaches the oracle at ~80k
triangles where flat needs ~3e8, and the quantitative reason Cycles only shows
caustics on smooth-shaded casters ([[cycles-caustics-need-smooth-shading]]).

## Conclusion — no degree-inflated resultant needed for 2b-smooth

2b-smooth is a **Newton-polish + smooth-partials wiring on top of 2b-flat**,
reusing the existing MNEE residual/Jacobian machinery — NOT a port of the paper's
higher-degree interpolated-normal polynomial. The flat quartic supplies the
basins (superfluous-root filtering already correct), the smooth Newton supplies
the digits, and `trianglePartialsSmooth` (already in `surface_partials.h`) supplies
the analytic `dn_du/dn_dv` for both the polish Jacobian and the MNEE weight.

## Implications for the C++ port

- **`CausticTri` must carry per-vertex normals.** Today it is `{v0,v1,v2}` only;
  smooth support needs `{n0,n1,n2}` too, and `gatherTriangleCasters` must pull
  them from the `Triangle` (which already stores `setVertexNormals`). Fall back to
  the flat facet normal when a caster has none (flat casters stay faceted — assert
  the prism/flat references don't move).
- **Polish location.** In `runMeshSMSAttemptPoly`, after `solveFlatTriangle
  Specular` returns the candidate vertex, if the caster is smooth-shaded run a
  short Newton polish (≤ ~8 iters) on the MNEE residual with the interpolated
  normal, seeded from the flat root (or the facet centroid if the flat quartic
  found none), staying on the facet plane. Feed the smooth `dn_du/dn_dv` into the
  `ChainVertex` so `chainGeometryTerm` weights the smooth surface.
- **Gate.** A smooth-shaded tessellated glass sphere should match the analytic
  sphere-primitive poly caustic (`runSMSAttemptPoly`) far better than the flat
  mesh does — the render-level twin of the table above. Flat casters unchanged.
- **Damping.** The prototype clamps the (du,dv) Newton step to ±0.5 to stay in the
  facet neighbourhood; the C++ polish should clamp similarly (cf. `solveChain`'s
  `maxStep`). A polished vertex that leaves the facet (u,v bounds) is rejected —
  the flat-facet in-triangle filter already does this.

## Files produced this session

- `scratchpad/proto_mesh_smooth.py` — the prototype (imports the 2b-flat
  prototype's oracle + flat solver; adds the smooth normal, MNEE residual, Newton
  polish, and the flat-vs-smooth drill-down comparison reproducing the table).
- `.astroray_plan/docs/pkg227-phase2b-smooth-research.md` — this note.

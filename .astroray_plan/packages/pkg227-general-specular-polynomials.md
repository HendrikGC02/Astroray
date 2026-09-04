# pkg227 — General Specular Polynomials (any-geometry deterministic caustics)

**Pillar:** 3 (light transport / caustics) + 2 (spectral core)
**Track:** A (CPU-first solver + candidate-generation research, numerical caustic
quality gates, sphere-exact oracle; GPU mirror is RTX-verified against the CPU
result and lands last)
**Status:** APPROVED (owner 2026-09-04) — implementing in order 2a → 2b-flat →
2b-smooth; 2c (M-prune) DEFERRED, 2d/3 follow. See "Owner decisions" below.
**Estimated effort:** XL — spans a cheap exact win (sphere multi-bounce), a
research-grade approximate mesh solver, a whole candidate-generation subsystem
(triangle-tuple pruning), and a GPU mirror. Phased so the first payoff ships
independently.
**Depends on:** **pkg127** (exact single-vertex SPHERE specular-polynomial solver
— LANDED #685; this generalizes it), **pkg106** (multi-vertex MNEE manifold chain
`manifold_chain.h`, `chainGeometryTerm` — the shared deterministic weight), **pkg64**
(SMS folded into the default spectral path). Soft-coupled to **pkg226** (the Newton
sphere-path weight bug) — independent, but both converge the two SMS weighting
schemes onto the single MNEE term.

---

## Goal

**Before.** Astroray's deterministic caustics are **sphere-only**. pkg127 landed an
*exact* single-vertex specular-polynomial solver, but only for analytic sphere
casters (`specular_poly.h::solveSphereSpecular`, wired into the default
`spectral_path_tracer` via `runSMSAttemptPoly`). Everything else falls back to a
**stochastic seed + Newton** search:

- The camera-side SMS connection in the default integrator gathers **sphere casters
  only** (`spectral_path_tracer.cpp:141 gatherSphereCasters`). Triangle-mesh casters
  never get a camera-side deterministic solve.
- The triangle-mesh caustic path (`runMeshSMSAttempt`, `mesh_attempt.h`) is wired
  **only into the opt-in `sms_caustic_path_tracer`**, uses a **single seed ray toward
  the caster centroid** (`seedChainTowardCaster`) + damped Newton — so it finds **at
  most one path per attempt** (the paper's "one solution per seed" miss) and uses
  **flat facet normals** (`trianglePartials`, `dn_du=dn_dv=0`).
- The showcase prism rainbow is produced by a **forward light-tracer**
  (`light_tracer_caustic`), not a camera-side mesh SMS connection at all.

Two consequences: (1) **no deterministic caustics on general geometry** — curved
lenses, faceted glass, and *raindrops rendered as spheres in a multi-bounce rainbow
chain* have no exact solver; (2) **smooth-shaded curved meshes are wrong** — the
Newton mesh path is flat-facet only, so a tessellated sphere/lens produces faceted
caustics, and Cycles only shows caustics on **smooth-shaded** casters (repo fact,
[[cycles-caustics-need-smooth-shading]]).

**After.** Deterministic, spectral specular caustics **on and from any geometry**,
along two complementary tracks that share the pkg127/pkg106 spine:

- **Track S (analytic sphere, exact, cheap).** Extend pkg127's *exact* planar sphere
  solver from one vertex to a **multi-bounce chain** (refract-in → internal-reflect →
  refract-out ≈ 3 specular vertices), giving the **raindrop rainbow** as a closed-form
  low-degree polynomial — no BVH, no tessellation, no faceting, no rational
  approximation. This is also the **numerical oracle** for Track M.
- **Track M (general triangle mesh, approximate, scalable).** Port Fan et al. 2024's
  per-triangle polynomial solver (rational coordinate mapping + hidden-variable
  resultant) to enumerate all admissible specular paths across an arbitrary mesh, with
  **interpolated shading normals**, superseding the stochastic Newton mesh path.

Both are flag-gated behind the existing `sms_specular_poly`; default OFF stays
byte-identical.

---

## Context — the two tracks, what they share, and the hidden cost

The parent (Opus 4.8) established three findings this session that shape the whole
package; each is folded into the phasing below.

### The dominant constraint: the paper does NOT scale with mesh size on its own

The single most important fact from re-reading Fan et al. 2024 (§3.1, §5): **the
polynomial solver is a per-triangle-tuple routine, and the paper explicitly outsources
the choice of *which* triangle tuples to solve to external pruning** — "Existing pruning
techniques (Walter et al. 2009; Wang et al. 2020) can be used to select the triangle
tuples that may contain a specular chain" (§3.1). Their results run the solver "for each
tuple of triangles that passed the pruning … following Wang et al. (2020)" (§5). The
per-tuple cost is degree-bounded (4–16), **independent of mesh size** — but a naïve
Astroray port that solves *every* triangle for *every* shading point is
O(pixels × triangles) polynomial solves, which is catastrophic.

**So "general-mesh caustics" is really two subsystems:**
- **(M-solve)** the per-tuple polynomial solver — the paper's portable contribution;
- **(M-prune)** a **triangle-tuple candidate-generation structure** (Path Cuts /
  hierarchical bounds + interval arithmetic, Wang et al. 2020) that Astroray **does not
  have**. This is a separate research line and the real engineering risk for *arbitrary*
  geometry at production speed.

This reframes the phasing: the cheap exact sphere win (Track S) and the smooth-mesh
*single-caster* solver (M-solve, validated on one known caster) can ship well before the
expensive (M-prune) subsystem, and the owner should decide explicitly whether general
production-speed mesh caustics are wanted now (see Open Decisions).

### Finding 1 — two tracks, shared spine

| Layer | Shared (S + M) | Primitive-specific |
|---|---|---|
| Root finder | `specpoly::realRoots` (Yuksel 2022 derivative-subdivision, degree ≤ ~16) | resultant/bisection driver for higher-degree multi-bounce |
| Deterministic weight | `chainGeometryTerm` (MNEE, `manifold_chain.h`) — one weight for both | per-vertex partials fed in (sphere analytic vs triangle) |
| Downstream validation | visibility / refraction-side / TIR / Fresnel / exit-occlusion (identical to `runSMSAttemptPoly`) | in-surface test (great-circle plane vs `pointInTriangle`) |
| Config | `SMSConfig`, `contribClamp`, `sms_specular_poly` flag | — |
| Coefficient build | — | **exact planar** (sphere, `buildSpherePolyCoeffs`) vs **rational-mapping** (triangle, Fan §3.4–3.5) |
| Candidate generation | — | great-circle plane (sphere, free) vs **triangle-tuple pruning** (mesh, M-prune) |

The sphere track is genuinely cheaper *and* more accurate than meshing a drop: one
primitive, exact closed-form solve, no BVH/enumeration/faceting, no rational √-fit. A
cloud of raindrops is N sphere primitives, each an independent exact solve — the natural
fit. Meshing each drop would multiply triangle count and force the whole M-prune cost
onto a case that has an exact closed form.

### Finding 2 — smooth-shaded meshes are a first-class scope item

`runMeshSMSAttempt` uses `trianglePartials` (`dn_du=dn_dv=0`) — correct for a real
faceted prism, **wrong for any smooth-shaded curved mesh** (faceted caustics).
`surface_partials.h::trianglePartialsSmooth` already computes the interpolated
shading-normal partials but is **not wired in**. Two independent places need the smooth
normal:

1. **The MNEE Jacobian** (`chainEval`) — already consumes `dn_du/dn_dv` generically, so
   the weight side is *ready*; it just needs the smooth partials passed instead of zero.
2. **The polynomial constraint itself** — this is the new hard part. Fan et al. §6
   confirms interpolated normals make `n̂_i` **nonlinear in barycentric coords** (linear
   `n_i` then normalized), which **inflates the polynomial degree by ~2** (Table 2) and
   **adds superfluous roots** via the extra squaring. Matching Cycles on general geometry
   *requires* this: Cycles shows caustics only on smooth casters. This gets its own phase
   (2b-smooth), not a footnote.

### Finding 3 — the spectral / dispersion path and the sphere-as-oracle

pkg127's sphere solve is **exact**; the paper's triangle solve is **approximate** (6-piece
rational fit to √x on [0,1], error < 1e-3, §3.5 Eq. 23). On Astroray's *spectral* path this
approximation interacts with per-λ IOR (the entire point of dispersive caustics). Design:

- **Geometry is λ-independent, coefficients are per-λ.** For both tracks, η enters only the
  **angularity** coefficients; the candidate geometry (great-circle plane for sphere;
  ray-triangle rational mapping for mesh) is wavelength-free. So dispersion = **rebuild the
  angularity coefficients at λ_hero and re-solve**, exactly one solve per ray (hero-λ
  decoupling, unchanged from pkg127). No per-λ geometry re-derivation.
- **The exact sphere solver is the numerical oracle.** Validate the *approximate* mesh
  solver by running it on a **fine sphere-tessellation mesh** and comparing its enumerated
  vertices/caustic against `solveSphereSpecular` on the analytic sphere — the mesh solver's
  rational-fit + interpolated-normal error must stay below the existing Newton tolerance
  (`SMSConfig::tolerance` 1e-4f) after the one-step Newton polish the paper recommends (§6).

---

## Citations (CLAUDE.md §6 — cite, borrow, verify; invoke `cite-algorithm` before code)

- **Fan, Guo, Wang, Xiao, Zhang, Zhou, Chen, Hong, Guo, Yan 2024 — "Specular
  Polynomials."** ACM TOG 43(4) (SIGGRAPH 2024), Article 126, **DOI 10.1145/3658132**,
  arXiv:2405.13409, https://zhiminfan.work/specPoly.html. Paper text **CC BY 4.0**. The
  method to port for Track M. (Author list + DOI already corrected in the pkg127 research
  note; reuse verbatim.)
- **Reference impl `github.com/mollnn/spoly` is UNLICENSED** (GitHub API `license: null`,
  no LICENSE file). **Do NOT copy its source** — re-derive from the CC BY 4.0 paper, as
  pkg127 did. Re-confirm the license state at port time (Phase-0 carry-over).
- **cyCodeBase / `cyPolynomial.h`** (Cem Yuksel) — **MIT** — the derivative-subdivision
  real-root finder already re-expressed in `specular_poly.h::realRoots`; extend, don't
  fork. http://codebase.cemyuksel.com/code.html
- **Walter, Zhao, Holzschuch, Bala 2009 — "Single Scattering in Refractive Media with
  Triangle Mesh Boundaries."** ACM TOG 28(3). DOI 10.1145/1531326.1531398. — triangle
  candidate pruning, the (M-prune) prior art the paper leans on.
- **Wang, Huo, Yan 2020 — "Path Cuts: Efficient Rendering of Pure Specular Light
  Transport."** ACM TOG 39(6) (SIGGRAPH Asia 2020). DOI 10.1145/3414685.3417792. — the
  hierarchical triangle-tuple pruning the paper uses for mesh scalability (M-prune). Check
  its reference-implementation license at port time.
- **Zeltner, Georgiev, Jakob 2020 — SMS** (DOI 10.1145/3386569.3392408, BSD-3 ref) and
  **Hanika, Droske, Fascione 2015 — MNEE** (DOI 10.1111/cgf.12681) — the existing SMS/MNEE
  spine (`sms_attempt.h`, `manifold_chain.h`).

---

## Owner decisions (2026-09-04, RESOLVED)

The owner reviewed the four open decisions and ruled:

1. **Phasing / pruning (Open Decision #1).** APPROVED the recommendation: implement
   in order **2a → 2b-flat → 2b-smooth**; **defer 2c (M-prune)** and 2d/3. Track S
   (raindrop rainbow, exact) + single-caster smooth-mesh solver ship first; the
   production-speed arbitrary-geometry pruning subsystem is gated on a real
   multi-caster/high-poly scene demanding it.
2. **Mesh √-fit accuracy (Open Decision #2).** ACCEPT the paper's approximate
   rational √-fit for the *mesh* path, **conditioned on it not influencing
   scientific results for research-grade simulations.** Interpretation locked for
   implementation: the **exact analytic sphere path (2a) is the research-grade
   dispersion path** (raindrops, journal-figure spheres) and carries no
   approximation; the mesh √-fit is for *general/visual* geometry and MUST stay
   oracle-gated (< `SMSConfig::tolerance` 1e-4 vs `solveSphereSpecular` after the
   Newton polish). Any scene used for a research/scientific claim uses the exact
   sphere solver, not the mesh √-fit — document the approximation prominently where
   the mesh solver is exposed so it is never silently used for a physics result.
3. **Newton mesh fallback (Open Decision #3).** KEEP `runMeshSMSAttempt` as a
   flag-gated fallback through Phase 2d (remove only once the deterministic mesh
   path proves out), per the recommendation.
4. **Depth caps (Open Decision #4).** Sphere cap **3** (primary bow), headroom 4 —
   approved. Mesh cap **2** (paper's feasible limit). Owner asks: expose the mesh
   depth as a **UI/config knob switchable to 3 *if* that is simple and doesn't
   change the core algorithm** — "use best judgement." **Judgement (implementer):**
   the depth *knob* is cheap and will be exposed as a per-object config parameter
   (same mechanism as the sphere-chain depth in 2a), but **actually solving depth-3
   mesh chains is NOT a simple knob** — it is precisely the combinatorial
   tuple-explosion the paper flags (§6) and requires the deferred M-prune subsystem.
   So: the parameter is honored and validated; requesting mesh depth > 2 is
   **clamped to 2 with a one-time warning** until 2c/2d land, at which point the cap
   is raised. This gives the owner the switch now without pretending the algorithm
   supports depth-3 mesh chains before the machinery exists.

## Phasing (each phase has a verifiable success criterion — CLAUDE.md §4)

Ordering rationale: **Track S first** (cheap, exact, independent, a showcase win and the
oracle for Track M), then the **mesh solver on a single known caster** (M-solve + smooth
normals, oracle-gated), then an **owner decision point** before the expensive **pruning
subsystem** (M-prune) and **two-bounce mesh** (M-2), then the **GPU mirror**. Track S and
Phase 2b-smooth are the recommended near-term scope; 2c/2d are gated on the owner wanting
production-speed *arbitrary*-geometry caustics.

### Phase 2a — analytic-sphere MULTI-BOUNCE (the raindrop rainbow) — Track S

Extend the exact planar sphere solver to a specular chain on a single sphere:
**refract-in → internal-reflect → refract-out** (the primary-rainbow ≈ 3 vertices; scope a
cap of 3, headroom to the secondary bow's 4). Key exact-geometry fact to derive and lock:
for a single sphere with fixed x0 and light, the whole chain lies in the **plane through
(x0, light, centre)** — every surface normal passes through the centre, so a path that
starts and ends in that plane with in-plane normals stays in-plane. The multi-bounce chain
therefore reduces to a small system in the per-vertex in-plane angles (one angle per
vertex), collapsed by the hidden-variable resultant to univariate root-finding **with no
rational approximation** — the sphere form of the paper's variable reduction, exact.

- Reuse `realRoots`, the signed-residual superfluous-root filter, the Newton polish, and
  `chainGeometryTerm` (N=2/3) for the weight. Per-λ IOR → per-λ angularity coefficients →
  spatial rainbow, same hero-λ mechanism as `runMeshSMSAttempt`.
- Wire a `runSphereChainAttempt` alongside `runSMSAttemptPoly`; extend `gatherSphereCasters`
  to feed the multi-bounce path when the caster requests a rainbow chain (a per-object depth,
  default 1 = current single-vertex behaviour).
- **Success:** on a glass-sphere / water-drop scene with a collimated light, the solver
  enumerates the internal-reflection rainbow branch(es); a unit test derives the analytic
  primary-bow deviation angle (~138° for water n≈1.33) and asserts the exit ray reaches the
  light to < 1e-4 rad; a new reference scene `raindrop-rainbow` shows a red→violet bow with
  `hue_spread`/`bright_coverage` gates (mirroring the prism gates). Newton-from-one-seed
  misses ≥1 branch the poly finds.
- **Effort:** M. Exact math re-derivation + one integrator hook; no pruning, no rational fit.

### Phase 2b-flat — single-bounce MESH solver, single known caster (M-solve), FLAT normals

Port the paper's per-tuple **single-vertex T/R** solver (§3.3 square form, §3.4–3.5 rational
coordinate mapping, §4.1–4.2 Bézout resultant + Laplacian expansion) for one refractive/
reflective vertex on a **triangle**, using the existing `seedChainFromRay` candidate triangle
(one caster, no global pruning yet). Reuse `realRoots`; add the ray-triangle rational mapping
and the 6-piece √-fit for refraction (Eq. 23), with the paper's one Newton polish.

- **Success (oracle-gated):** run on a **fine sphere-tessellation mesh** and match
  `solveSphereSpecular` on the analytic sphere — enumerated vertices agree to < 1e-4 rad
  after the Newton polish; superfluous (square-form) roots are all filtered by the path-space
  re-check (no spurious energy). Faceted glass-mesh caster produces a caustic on
  `glass-mesh-caustic` (the reference-bank scene shell already exists, gates.toml currently
  empty — this phase blesses it).
- **Effort:** L. First real port of the paper's triangle machinery + √-fit; the biggest
  single-correctness-risk item (spectral rational-fit accuracy) lives here — gate against the
  sphere oracle before trusting it on the spectral path.

### Phase 2b-smooth — interpolated shading-normal support (Finding 2)

Wire `trianglePartialsSmooth` into both the polynomial constraint and the MNEE Jacobian.
Re-derive the coplanarity/angularity coefficients with the **linear-then-normalized** shading
normal (Fan §6): degree grows by ~2, extra superfluous roots appear — the filter must catch
them. `chainEval` already consumes `dn_du/dn_dv`, so the weight side is a wiring change; the
constraint side is new coefficient algebra.

- **Success:** the same tessellated-sphere-mesh caustic now matches the analytic-sphere oracle
  **with smooth shading** (flat-facet artifacts gone); a Cycles-parity scene
  (`smooth-lens-caustic`, new) matches Cycles' smooth-caster caustic within the per-channel
  mean-ratio / SSIM gate. Flat casters unchanged (a real prism stays faceted — assert the
  prism references don't move).
- **Effort:** M–L. Coefficient re-derivation + the superfluous-root filter tightening.

### Phase 2c — triangle-tuple candidate generation / pruning (M-prune) — GATED

Build (or adopt, license-permitting) a **Path-Cuts-class hierarchical triangle-tuple pruning**
structure (Wang et al. 2020 / Walter et al. 2009) so the solver runs only on tuples that may
contain a specular chain — the subsystem that turns "one known caster" into "any geometry at
production speed." Invoke `cite-algorithm`; this is its own research-grade port.

- **Success:** a multi-caster / high-poly scene renders a correct caustic in bounded time that
  scales with pruned-tuple count, **not** pixel×triangle; a stress scene (e.g. faceted glass
  cluster) stays within a walltime budget the owner sets.
- **Effort:** XL, high risk. **This is the phase that determines whether "arbitrary geometry"
  is truly in scope now** — see Open Decisions #1. It can be deferred without blocking Track S
  or the single-caster mesh solver.

### Phase 2d — two-bounce MESH (RR / double-refraction prism) — supersede Newton mesh path

Extend M-solve to the two-vertex chain (Fan Eq. 27 RR / the TT double-refraction case) on the
`manifold_chain.h` chain, using the paper's **bisection solver** (§4.2; explicit coefficient
extraction is infeasible past one bounce — uniform-subdivide [0,1], bisect sign-change
intervals, evaluate the resultant determinant by Gaussian elimination). This replaces
`runMeshSMSAttempt`'s single-seed Newton with deterministic enumeration for the prism.

- **Success:** the SF11 / BK7 prism (`prism-sf11-collimated`, `prism-bk7-collimated`) caustic
  holds or improves at equal spp via the **camera-side deterministic mesh path** (not only the
  forward light-tracer); a double-refraction unit test where Newton-from-one-seed stalls
  converges; seed-failure rate strictly lower than the Newton mesh baseline.
- **Effort:** L–XL. Depends on 2b-flat (+2c for a real multi-caster prism scene).

### Phase 3 — GPU / wavefront mirror

Mirror the solver into the wavefront path. `specular_poly.h` is already STL-free and portable;
Track S (exact, low-degree, planar) mirrors cleanly. Track M's resultant/bisection is branchy
and higher-degree — a register-budget risk on the REG:254 shade fleet
([[wavefront-shade-kernels-register-saturated]]); isolate behind the `__noinline__`
runtime-flag recipe ([[noinline-runtime-flag-avoids-shade-spill]]) or defer. CPU-gate first;
GPU parity is verification, not the primary gate.

- **Success:** wavefront Track S caustic matches the CPU result on the caustic parity harness
  (`tests/test_gpu_caustic_parity.py`); RTX-verified, REG:254 held (cuobjdump post-link).
- **Effort:** M (Track S) / L (Track M).

---

## Validation strategy

- **Sphere-exact-as-oracle (headline).** `solveSphereSpecular` (exact) validates the approximate
  mesh solver on a sphere-tessellation mesh — the single most important correctness gate for the
  spectral path (Finding 3). Lock as a CI unit test alongside
  `tests/test_pkg127_specular_poly_unit.py`.
- **Reference-bank scenes to add/bless:**
  - `raindrop-rainbow` (Track S multi-bounce; new) — `hue_spread` ≥ ~0.7, `bright_coverage`
    band gate, mirroring `prism-bk7-collimated`.
  - `glass-mesh-caustic` (bless the existing empty shell; Phase 2b-flat).
  - `smooth-lens-caustic` (new, Cycles-parity, smooth-shaded curved caster; Phase 2b-smooth).
- **Gate metrics.** Per-channel **mean-ratio** and SSIM≥threshold on caustic ROIs; **NOT windowed
  SSIM for independent MC streams** ([[ssim-wrong-gate-for-independent-rng]]). LINEAR EXR,
  seed-pinned. `hue_spread`/`bright_coverage` for the spectral bows. Superfluous-root safety:
  furnace/energy on a non-caustic scene unchanged.
- **Seed-failure-rate before/after** on the mesh path (the `return 0.0f` drop rate in
  `runMeshSMSAttempt`) — deterministic enumeration must strictly beat the Newton baseline.
- **Regression with flag off:** default (poly OFF) bit-equal to pre-pkg227; the pkg127 sphere
  poly path unchanged.
- **CI has no GPU** — run the RTX caustic sweep at closeout ([[ci_has_no_gpu_runtime_blindspot]]).

---

## Risks & open decisions

### Open decisions the OWNER must make

1. **Is production-speed *arbitrary*-geometry mesh caustics in scope now — i.e. do we build the
   Phase 2c pruning subsystem (M-prune, XL, its own research line)?** The paper's solver does not
   scale without it. **Recommendation: no, not first.** Ship Track S (raindrop rainbow, exact,
   cheap) + Phase 2b (single-caster smooth-mesh solver, oracle-gated) — that already covers curved
   lenses, faceted glass, and the raindrop cloud — and gate 2c/2d on whether a real multi-caster
   high-poly scene actually demands it. This is the biggest fork; it decides the package's size.
2. **Accuracy regime for mesh refraction.** Accept the paper's approximate rational √-fit
   (error < 1e-3 + one Newton polish, validated against the sphere oracle) — or hold mesh to a
   tighter bar? **Recommendation: accept, oracle-gated** — the √-fit error is below
   `SMSConfig::tolerance` after the polish, and the sphere oracle bounds it directly.
3. **Deprecate or keep the Newton mesh path (`runMeshSMSAttempt`)?** **Recommendation: keep as a
   flagged fallback through Phase 2d, remove once the deterministic mesh path proves out** — same
   pattern pkg127 used for the sphere Newton path.
4. **Multi-bounce depth cap.** Track S: 3 (primary bow), optional 4 (secondary). Track M: 2 (paper's
   feasible limit; 3+ is a combinatorial explosion, §6). Confirm 3-sphere / 2-mesh is enough for the
   target scenes.

### Risks

- **Scalability (dominant).** Covered above — mitigated by ordering (Track S + single-caster mesh
  before pruning) and by making 2c an explicit gate.
- **Spectral rational-fit bias.** The approximate mesh refraction on the per-λ path is the top
  correctness risk; the sphere oracle + Newton polish + tolerance check contain it (Finding 3).
- **Superfluous roots / smooth normals.** Square form + interpolated normals both inflate degree and
  add spurious sign roots; the path-space re-check (already in `runSMSAttemptPoly`) must catch every
  one — a lax filter silently adds energy (paper §3.3, §6).
- **Polynomial conditioning.** Degree 6→16 resultants ill-condition near grazing/degenerate configs;
  keep the axial-degenerate → Newton fallback pkg127 already has.
- **GPU register budget.** Track M's branchy resultant/bisection on the REG:254 shade fleet — isolate
  or defer (Phase 3).
- **Two blessed-reference moves.** Any prism/glass reference re-bless must be documented and owner-
  acknowledged, as pkg127 did for `sms-refractive-glass-sphere`.

---

## Non-goals

- **Not a new integrator.** Upgrades the SMS seed/connection stage only; the refraction/Fresnel/
  visibility/MIS chain is untouched, Newton stays as fallback.
- **Not 3+ bounce mesh chains** (paper §6 combinatorial explosion) — 2 for mesh, 3 for sphere.
- **Not ReSTIR / partitioned SMS** (separate later package).
- **Not glint rendering** (out of scope, as pkg64/pkg127).
- **Do NOT copy `mollnn/spoly` source** (unlicensed) — re-derive from the CC BY 4.0 paper.
- **No invented algorithms** — port + cite + verify licenses (CLAUDE.md §6).

---

## Provenance

Scoped 2026-09-04 by the architect (Opus 4.8) at the team-lead's request, immediately after
pkg127 Phase 1 landed (#685). Grounded in a full read of the landed pkg127 solver
(`specular_poly.h`, `runSMSAttemptPoly`), the pkg106 Newton mesh path
(`mesh_attempt.h`, `mesh_caustic.h`, `manifold_chain.h`, `surface_partials.h`), the default
integrator dispatch (`spectral_path_tracer.cpp`), and a re-fetch of Fan et al. 2024
(arXiv:2405.13409) — whose §3.1/§5 pruning-outsourcing is the decisive scalability finding here.
Folds in the parent's three session findings (two-track relationship + raindrop-sphere case;
smooth-shaded meshes as first-class; the spectral rational-fit risk + sphere-as-oracle). Owner
context: the prism rainbow and glass-sphere caustic are journal-figure showcase scenes, and a
raindrop-cloud rainbow is a target render — cheap exact spheres first, general mesh gated on real
demand.

---

## Progress

- [x] Phase 2a — analytic-sphere multi-bounce (raindrop rainbow), Track S.
      Solver `specpoly::solveSphereChain` + `runSphereChainAttempt`, `path_tracer`
      param `sphere_chain_reflections` (0=off default, 1=primary, 2=secondary).
      Gates: `tests/test_pkg227_sphere_chain_unit.py` (numpy oracle, 5/5, CI) +
      `tests/test_pkg227_raindrop_bow.py` (render-level: fires/concentrated/
      chromatic, 3/3). Branch `pkg227-s2a`. See Phase 2a findings below.
- [x] Phase 2b-flat — single-bounce mesh solver on one known caster (M-solve), oracle-gated.
      **LANDED 2026-09-05.** Solver `specpoly::solveFlatTriangleSpecular`
      (`include/astroray/manifold/mesh_specular_poly.h`, exact degree-4 flat-facet
      form) + `runMeshSMSAttemptPoly` (`mesh_attempt.h`), gated in
      `sms_caustic_path_tracer` behind `sms_specular_poly` (+ `spectral_newton=1`,
      the mesh path). Gates: `tests/test_pkg227_mesh_poly_unit.py` (numpy oracle
      vs `solveSphereSpecular`, 3/3, CI, < 1e-4 rad) + `tests/test_pkg227_mesh_
      caustic.py` (render-level, 4/4). Branch `pkg227-s2b-flat`. See Phase 2b-flat
      findings below.
- [ ] Phase 2b-smooth — interpolated shading-normal support (constraint + Jacobian).
- [ ] Phase 2c — triangle-tuple pruning subsystem (M-prune) — GATED on Open Decision #1.
- [ ] Phase 2d — two-bounce mesh, supersede `runMeshSMSAttempt`.
- [ ] Phase 3 — GPU / wavefront mirror; caustic parity RTX-verified.

## Phase 2a findings (2026-09-04)

- **Solver is exact and simpler than scoped.** The sphere's concentric-normal
  symmetry makes the multi-bounce residual DIRECTLY univariate in the entry-point
  angle — the hidden-variable resultant (spec §2a) is unnecessary; a forward-trace
  + sign-change bisection enumerates all branches exactly. Validated to <1e-8 rad
  vs the analytic Descartes bow (i=59.41°, D=137.92° for water).
- **The engine is correct; a single-drop bow is intrinsically a faint, noisy
  caustic.** Camera-side SMS to a directional sun makes the primary bow a thin,
  high-variance caustic band (chain adds real chromatic energy, row-profile ~42%
  concentrated in the 42°-caustic band, both red- and blue-dominant pixels). It
  does NOT render as a clean visible arc at practical spp — the same reason the
  repo renders the PRISM rainbow via a forward light-tracer, not SMS. So the
  Phase 2a gate asserts the **physics** (chain adds chromatic, banded energy vs
  chain-off), NOT a pretty full-frame image. A clean showcase bow needs a forward
  light-tracer or a dense drop cloud — deferred to a publication scene (owner:
  "we can always build a nicer looking scene for publication", physically-honest
  first). No reference-bank scene blessed for 2a (a full-frame single-drop image
  is too faint to gate robustly); the render-level pytest is the gate.

## Phase 2b-flat de-risking (2026-09-04, prototype)

Parallel numpy prototype (`scratchpad/proto_mesh_specular.py`, research note
`.astroray_plan/docs/pkg227-phase2b-research.md`) — PASSES vs the sphere oracle:

- **Flat-facet single-vertex refraction is EXACT degree-4 — no √-fit.** For a
  constant (flat) normal, coplanarity collapses to a LINEAR constraint and the
  squared angularity to a plain degree-4 polynomial in one line-parameter. The
  paper's 6-piece rational √-fit (Eq. 23) is NOT needed for 2b-flat (it's for the
  multi-vertex position propagation in 2d, and interpolated normals in 2b-smooth).
  **This refines Owner Decision #2:** the √-fit "visual-only" concern applies to
  2b-smooth/2d, not 2b-flat, which is research-grade exact. Degree-4 independently
  matches the paper's Table 2 flat-normal degree.
- Oracle agreement <5.65e-6 rad (18× inside the 1e-4 gate) across 4 cases × 2
  branches; superfluous roots filter cleanly (445/448 removed).
- **Convergence is LINEAR in facet edge length (err/edge≈0.41), not quadratic** —
  a globally-uniform mesh fine enough would need ~3e8 triangles. This is the
  quantitative reason smooth normals (2b-smooth) are a REQUIRED separate phase,
  not "just tessellate finer".
- **Implementer gotcha:** pass `eta` UNMODIFIED (mirror `specular_poly.h`'s Ci/Co
  pattern); verify eta direction empirically against the pkg127 CI oracle, never
  an isolated Snell sanity check — the wrong convention is locally self-consistent
  and fails SILENTLY (a different plausible specular point, not an error).
- Port target: new `mesh_specular_poly.h` reusing `specular_poly.h` helpers.

## Phase 2b-flat findings (2026-09-05)

- **Solver ports cleanly and is exact.** `solveFlatTriangleSpecular` is a
  line-for-line C++ port of the validated numpy prototype (degree-4 square form,
  `realRoots` reused from `specular_poly.h`), STL-free. The oracle unit test
  reproduces `solveSphereSpecular` to < 1e-4 rad over an icosphere tessellation
  (3/3). ABI-clean (device path does not include the header).
- **The un-pruned camera-side mesh path is O(pixels × triangles) — it MUST use
  candidate-face selection even for a single caster.** The first cut solved the
  quartic on EVERY caster facet per shading point; on a 320–1280-triangle
  tessellated sphere that hung for hours (the exact O(pixels × triangles) blow-up
  the spec flags as the M-prune motivation, §"dominant constraint"). Fix: cast the
  cheap x0→centroid seed ray (Möller–Trumbore, mirroring
  `seedChainTowardCaster`) and solve the quartic ONLY on the ≤4 faces it crosses.
  Runtime dropped to ~3–4 s/render. This is the flat-facet form of the spec's
  "use the existing `seedChainFromRay` candidate triangle (one caster, no global
  pruning yet)" — pruning to a *global* candidate set across many casters is still
  Phase 2c, but even one caster needs per-shading-point face scoping.
- **Deterministic enumeration decisively beats the Newton mesh path.** On the
  tessellated glass sphere the single-seed Newton path (`runMeshSMSAttempt`)
  converges on ~0.1 % of attempts and collects ~0.1 caustic energy; the poly path
  validates ~100 % of enumerated solutions and collects ~12–15 (≈100×), band
  concentration ~0.62–0.69. The render gate asserts this gap. (The Newton mesh
  path was never actually exercised by any reference scene — both SMS reference
  scenes use analytic spheres — so this is the first camera-side mesh caustic.)
- **`glass-mesh-caustic` was the WRONG scene to bless.** The spec named it as the
  2b-flat reference shell, but it is a FORWARD `light_tracer_caustic` scene whose
  caster is an 18 MB gitignored `samples/Glass.obj` (local-only, never CI). It
  does not use the camera-side poly path at all. Blessing it as-is would lock a
  forward render, not test 2b-flat. So 2b-flat is gated by a self-contained
  procedural-icosphere pytest (no external asset, like the 2a raindrop gate)
  rather than by converting that forward showcase. Left `glass-mesh-caustic`
  untouched as the forward showcase it is; a reference-bank *camera-side* mesh
  scene can be added later if wanted (would need a committed reference.png; still
  local-only to render).
- **Flat facets → faceted caustics, by design.** Convergence to the smooth
  continuum is linear in facet edge length (research note §3), and the
  candidate-face solve only finds a vertex when it lies on a seed-crossed facet —
  so a finer mesh yields fewer per-pixel hits (measured attempts 267k→78k from
  subdiv 1→2) with a sharper but sparser caustic. Smooth-shaded curved casters
  are exactly Phase 2b-smooth's job; the multi-facet fold coverage is Phase 2c.

## Lessons

*(Fill in after the package is done.)*

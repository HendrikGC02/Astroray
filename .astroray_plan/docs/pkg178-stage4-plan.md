# pkg178 Stage 4 implementation plan — Thin Film + Thin Wall (+ pkg128 shared utility)

**Date:** 2026-08-10. **Author:** architect. **Status:** plan for the lead — NOT
dispatched, nothing committed. Companion research note (read first, it carries the
verbatim-verified math + file:line pins):
`.astroray_plan/docs/pkg178-stage4-thinfilm-research.md`.

Reference: blender/blender `main` — `intern/cycles/kernel/closure/bsdf_util.h`
(BSD-3-Clause) `fresnel_iridescence_channel` :499 et al.;
`closure/bsdf_microfacet.h` (BSD-3-Clause) thin-film branches + thin-glass block
:1218–1428; `svm/closure.h` (Apache-2.0) Principled assembly. Paper: Belcour & Barla
2017, TOG 36(4):65, DOI 10.1145/3072959.3073620. Oracle: **Blender 5.2 Cycles** (D1
satisfied).

---

## 0. Design decisions (architect's calls; forks flagged where real)

1. **One shared utility, single-source for CPU and GPU.** New header
   `include/astroray/thin_film_fresnel.h`: pure-math functions (no tables inside),
   qualified `ASTRORAY_TF_FN` (= `__host__ __device__ inline` under NVCC, `inline`
   otherwise). This is the pkg163 byte-mirror discipline for free — one body, two
   legs — and it is the seam pkg128's residual charter (standalone Glass/Metallic +
   showcase) rides later. Do NOT duplicate the math into `gpu_materials.h` as a
   `gpu_pr_*` twin; include the header from both sides.
2. **Sensitivity is a functor, not a branch.** The Airy core takes
   `S(m, OPD) -> {re, im}`:
   - spectral legs: analytic `S = {cos(2π·m·OPD/λ), sin(2π·m·OPD/λ)}` — exact, no
     LUT (pkg128's per-λ design; document the intentional omission of Belcour §4).
   - RGB legs: CIE-sensitivity LUT lookup, mirroring Cycles per-channel for
     like-for-like parity gates.
   Both legs share the SAME truncated m≤3 series (structural identity with Cycles;
   residual O(r123⁴) is negligible — Cycles' own comment). The exact closed-form Airy
   per λ exists but is deliberately NOT used: structural sharing + Cycles parity win;
   note it as a possible future showcase-only flag.
3. **CIE LUT baked to Rec.709 at generation time.** Port
   `table_thin_film_cmf[512][6]` (`scene/shader.tables:1287`, Apache-2.0) and apply
   `compute_thin_film_table`'s XYZ→RGB multiply + DC normalization offline (Astroray's
   working space is fixed Rec.709-linear) → checked-in
   `include/astroray/thin_film_cie_table.h` (512×6 float ≈ 12KB) + GPU upload
   `src/gpu/gpu_thin_film_table.cu` (precedent: `gpu_ggx_tables.cu`; sheen LTC table
   shipping precedent for the header). Delegate-tier grunt with an evidence gate:
   spot-check ≥8 table rows against values recomputed from
   `doc/precompute/thin_film_table.py` + Rec.709 matrix.
4. **Energy compensation unchanged — the no-double-count rule.** Film replaces only
   the single-scatter Fresnel `F`; `energy_compensation.h` (Fss/E/Eavg) keeps the
   FILM-FREE estimates, exactly as Cycles (`microfacet_ggx_preserve_energy` fed
   film-free Fss; `bsdf_microfacet_estimate_albedo` film fallback comments :513/:540).
   Declare in the Stage-0 map as `DIRECT (Cycles-identical approximation)`.
5. **Host-precompute per-material constants.** Gulbrandsen n,k per RGB channel for
   the F82 conductor case depend only on (f0, f82) ⇒ compute in the CPU ctor and in
   `scene_upload.cu` (host side), store in the lobe/`GPrincipledClosure` — Cycles
   recomputes per shade only because its fresnel structs are per-hit. Cuts device
   live-state and code. (Per-λ spectral conductor eval uses the same RGB-channel n,k
   — Cycles has no spectral n,k either; document as APPROXIMATED-equal-to-Cycles.)
6. **Thin Wall lives inside the Principled lobe assembly**, not the legacy
   `thin_glass.cpp` (ad-hoc cone-sampling code — math superseded; file untouched).
   `MaterialClosureType::ThinGlass` GPU closure untouched. New LobeKinds instead
   (see §2). Reconciliation of standalone `thin_glass.cpp` = follow-up, out of scope.
7. **GPU lands inside `template<true>` (HasPrincipled) only** — memory
   `closure-graph-lobe-count-spills-fused-kernel`. Non-principled scenes are
   compile-time isolated; still gate-verified.

## 1. Shared utility — `include/astroray/thin_film_fresnel.h`

Port verbatim (with citations per function, Cycles file:line from the research note):

```cpp
namespace astroray::thinfilm {
struct TFComplex { float re, im; };            // bsdf_util.h:25 complex<float>
// bsdf_util.h:47 — returns {rs^2, rp^2}; outputs cosThetaT (negative) and
// reflection-phase signs {±1, ±1}.
ASTRORAY_TF_FN Vec2f fresnelDielectricPolarized(float cosThetaI, float eta,
                                                float* rCosThetaT, Vec2f* rCosPhi);
// bsdf_util.h:200 — Born-Wolf conductor; F82>=0 selects F82-model magnitude with
// physical phase (see research note §2.2).
ASTRORAY_TF_FN void fresnelConductorPolarized(float cosI, float ambientIor,
    TFComplex conductorIor, float F82, float& Rs, float& Rp,
    TFComplex* phasorS, TFComplex* phasorP);
// bsdf_microfacet.h:86
ASTRORAY_TF_FN void adjustThinFilmIorAtBackface(float& filmIor, float invBulkIor);
// bsdf_util.h:468 — Airy summation, m truncated at 3; SensFn(m, OPD)->TFComplex.
template <typename SensFn>
ASTRORAY_TF_FN float airySummation(float R12, float R23, float OPD,
                                   TFComplex phasor, SensFn&& S);
// bsdf_util.h:499 — the per-channel/per-λ driver (sub-1nm smoothstep blend, top/
// bottom interfaces, OPD = -2*n1*d*cosθ2, S/P average, saturate).
template <bool conductive, typename SensFn>
ASTRORAY_TF_FN float fresnelIridescence(float ambientIor, float thicknessNm,
    float filmIor, float substrateN, float substrateK, float F82,
    float cosTheta1, float* rCosTheta3, SensFn&& S);
// Sensitivity providers:
ASTRORAY_TF_FN TFComplex sensitivitySpectral(int m, float OPD, float lambdaNm);
//   {cos, sin}(2π·m·OPD/λ) — exact single-λ CMF; NO LUT (pkg128 per-λ design).
ASTRORAY_TF_FN TFComplex sensitivityRGB(int m, float OPD, int channel,
                                        const float* table /*512*6, x=2π·OPD/60000*/);
inline constexpr float kThinFilmThicknessCutoff = 0.1f;   // svm/types.h:577
inline constexpr int   kThinFilmTableSize = 512;          // kernel/types.h:37
}
```

Notes: linear-interp `lookup_table_read` clone for the LUT (clamped, like Cycles);
the CPU side uses the static header table, the GPU side gets the device pointer via
the existing table-upload plumbing — pass the pointer in, keep the core table-free.

## 2. Integration — CPU (`plugins/materials/principled.cpp`)

Film active ⇔ `thin_film_thickness > 0.1f`; `thin_film_ior` forced 0 otherwise
(svm/closure.h:301–304). New ctor params: `thin_film_thickness` (nm, default 0),
`thin_film_ior` (default 1.33 — Blender socket default), `subsurface_anisotropy`
(default 0; needed by thin subsurface). `thin_wall` already parsed (:900).

Per-lobe wiring (all in `assembleLobes` + the four evaluators; sampling directions
untouched — the film only changes F):

- **Specular lobe:** activation condition gains `|| thickness > 0.1f` (film forces
  the lobe even at eta==1, svm/closure.h:438). Eval: per channel (RGB) / per λ
  (spectral) `F = fresnelIridescence<false>(1, d, n1, eta, 0, −1, cosθ, nullptr, S)`
  then the F0-rescale block verbatim (bsdf_microfacet.h:284–297; research note
  §2.3). Layering weight (`ggxDirectionalAlbedo`) stays film-free (Cycles albedo
  fallback — declared approximation).
- **Transmission lobe (thick, thin_wall=false):** `F` from
  `fresnelIridescence<false>` with `rCosTheta3` feeding the refraction direction;
  `T = (1−F)·transmission_tint`. Backface: where the code swaps etaI/etaT, also
  `adjustThinFilmIorAtBackface(filmIor, 1/ior)` (svm/closure.h:400–403). R-vs-T lobe
  selection probability uses channel-averaged (RGB) / hero-λ (spectral) F with
  matched eval/pdf normalization — the pkg170 one-sample-MIS discipline; cross-check
  Cycles `bsdf_microfacet_ggx_sample`'s use of the fresnel split before coding.
- **Metallic lobe:** ctor precomputes per-channel `(n,k)` via Gulbrandsen inversion
  (bsdf_microfacet.h:392–399) and `g = fresnel_f82(1/7, f0, b)`; eval per channel:
  `F = fresnelIridescence<true>(1, d, n1, n_ch, k_ch, g_ch, cosθ, nullptr, S)`.
- **Thin Wall (thin_wall=true):**
  - Transmission → two new lobes via a `thinGlassFresnel()` helper porting
    `bsdf_thin_glass_fresnel` (bsdf_microfacet.h:1236): front (r1,t1) via
    generalized-Schlick (+film), back (r2,t2) at (−cosθt, 1/ior) with film-IOR
    backface-adjusted, Beer `c = tint^(−1/cosθt)`, series
    `T' = c·t1·t2/(1−(r2·c)²)`, `R' = r1 + T'·r2·c`.
    `LobeKind::ThinGlassReflect`: GGX reflection, ior=1, constant weight R'.
    `LobeKind::ThinGlassTransmit`: mirrored-reflection lobe (eval/sample against
    `reflect(wi, N)` with N negated) at
    `α_T = saturate(α·sqrt(3.4(η−1)(η−0.5)²/η³))` (:1307); near-specular α_T ⇒ delta
    passthrough `wo = −wi`. Energy compensation: REFLECTION ggx_E tables for both
    (:442–447), not the glass tables.
  - Subsurface → `LobeKind::Translucent` split: diffuse weight `0.5(1−g)`,
    translucent weight `0.5(1+g)` (bsdf_oren_nayar.h:169), Oren-Nayar/EON variants
    when `diffuse_roughness > 0`. Translucent = cosine lobe on the BACK hemisphere.
- **Spectral legs:** `evalSpectral`/`sampleSpectral` per-λ native
  (`sensitivitySpectral`), colours upsampled, scalars per-λ — the pkg163 rule.
  Thickness=0 must be bit-equal to Stage-3 on all four evaluators.

## 3. Integration — GPU (`gpu_materials.h` `<true>` instantiation + upload)

- `GPrincipledClosure` += `thinFilmThickness`, `thinFilmIor`, `thinWall` (float),
  `subsurfaceAnisotropy`, precomputed `filmNK[3]` (n,k per channel) + `filmF82g[3]`
  — host-side in `scene_upload.cu`'s principled arm. No new closure type, closure
  cap unchanged.
- `gpu_pr_assembleLobes`: thin-wall branch (transmission → ThinGlassReflect/Transmit
  lobes; subsurface → diffuse+translucent split); film flags on
  specular/transmission/metallic lobes.
- Eval sites (`gpu_pr_evalLobe`, `gpu_pr_evalLobeSpectral`,
  `gpu_pr_transmissionEval`, sample): call the SAME header functions. RGB leg loops
  channels one at a time (Cycles' own register mitigation — cite the comment);
  spectral leg loops hero wavelengths with the analytic S (no LUT traffic).
- LUT upload: `gpu_thin_film_table.cu` (global-mem table + `lookup` helper,
  `gpu_ggx_tables.cu` precedent), pointer plumbed like the GGX tables.
- **Register/STACK budget (honest estimate):** the per-channel iridescence path
  holds ~20–25 live floats (two polarized Fresnels + 3-term loop + phasors), fully
  inside the `<true>` instantiation ⇒ non-principled kernels are compile-time
  unaffected (still gate-verified). Expect a measurable STACK increase on the
  principled shade kernel — smaller than the Stage-3 +3240B event since this is
  per-channel-serialized flat math, not new lobe array state, and n,k precompute
  removes the inversion. Protocol (unchanged from Stage-2): `cuobjdump` REG **and
  STACK** before/after; non-principled wavefront perf gate hard-green;
  principled-scene perf measured against its own budget. Mitigation ladder if the
  budget blows: (a) `__noinline__` on the device `fresnelIridescence` instantiations
  (pkg174 lever; clock-drift protocol), (b) move principled shading to pkg174's
  designed per-bucket kernel, (c) D4 fork to owner. Verdict: **feasible — go**, with
  (a)/(b) as pre-approved fallbacks and measurement at PR-3.

## 4. Verification (Cycles 5.2 = oracle; linear, floor+ceiling, per-channel ratios)

- **Thickness=0 bit-equality** with Stage-3 outputs, all four CPU evaluators + GPU
  (the no-op guard; also covers the <1nm smoothstep continuity with a 0.5nm case).
- **Hue-trajectory sweep:** thickness {100, 200, 400, 800, 1500, 3000}nm × film IOR
  {1.2, 1.5, 1.8} × {dielectric specular, glass transmission, conductor}: per-scene
  per-channel mean-ratio bands vs Blender 5.2 Cycles (pkg119-B harness rows +
  refbank 5.2-blessed refs for these scenes ONLY — existing 5.1 baselines
  untouched), plus a hue-angle-vs-thickness curve plot (Astroray-RGB vs Cycles)
  as the PR artifact. Spectral-leg hue divergence vs RGB leg recorded, not gated
  (by-construction difference; pkg128 §B).
- **Furnace/energy:** directional-hemispherical reflectance ≤ 1 over
  (thickness × filmIOR × roughness × angle) grid, LINEAR with ceiling (gamma
  furnaces cannot detect gain — pkg166/memory). Thin glass: R'+T' ≤ 1 numerically.
  Backface: front/back furnace pair on a glass slab (the eta² bug-class guard).
- **Sampler:** chi² (pkg121 harness) for the modified glass R/T selection and the
  new ThinGlassTransmit + Translucent lobes.
- **CPU↔GPU parity** per lobe on landing (pkg119b runbook build; OpenMP-OFF pyd for
  addon legs).
- **Thin-wall trio:** paper (white thin subsurface), leaf (colored translucent,
  g>0), window sheet (thin glass smooth+rough) vs Blender 5.2 — visual + per-channel
  ratio; render-level suites, not just consistency gates (memory
  `pr-named-tests-insufficient`).
- Every GPU PR: cuobjdump REG/STACK delta table + non-principled perf gate.

## 5. Addon wiring (Stage-5 extension; PR-5)

Blender Principled sockets → native params (flag-on path only; Disney path
byte-identical):

| Blender socket | ParamDict key | Notes |
|---|---|---|
| `Thin Film Thickness` | `thin_film_thickness` | nm, float/texture-resolved default |
| `Thin Film IOR` | `thin_film_ior` | default 1.33 |
| `Thin Wall` | `thin_wall` | bool socket (5.2) → float 0/1 (existing parse :900) |
| `Subsurface Anisotropy` | `subsurface_anisotropy` | consumed by thin subsurface |

These four come OFF Stage-5's `_NATIVE_PRINCIPLED_UNMAPPED` dropped list (list not
yet in code — Stage-5 not landed; coordinate the constant's name with the Stage-5
implementer at dispatch). `coverage_matrix.json`: flip the two Principled thin-film
cells + thin-wall row DROPPED-SILENT→SUPPORTED; the four Glass/Metallic thin-film
cells stay with pkg128's residual charter (standalone nodes ride
`thin_film_fresnel.h` later — coordinate, don't duplicate). Per-render
still-approximated report line per pkg119-C. Verify socket identifiers against the
local Blender 5.2 python API before hardcoding (5.x renamed sockets before).

## 6. Ordered PR plan (implementer-facing; each gate-listed; lead builds all GPU)

- **PR-1 — shared utility + CPU dielectric thin film (spectral + RGB).**
  Status: DONE on branch `pkg178-thinfilm-pr1` (commit c2b621c, 2026-08-10; not yet
  PR'd/merged — lead to review + run the vs-5.2 hue sweep). `thin_film_fresnel.h`
  (shared host+device core incl. conductor entry for PR-2), `thin_film_cie_table.h`
  (Rec.709-baked, generator doc/precompute/thin_film_table.py + spot-check),
  specular + transmission (both faces, backface film-IOR adjust, F0-rescale). Energy
  comp left film-free; sampler/pdf unchanged. Gates met (CPU, RTX build): thickness-0
  bit-equality byte-identical vs fresh 6d8cdb9 build (spec+glass, maxΔ 0.0); utility
  analytic-phase check vs exact Airy (Δ~1e-6); furnace no-gain sweep; chi² film-ON.
  LEAD-DEFERRED: dielectric/glass hue-trajectory sweep vs Blender 5.2 Cycles (harness
  scene author + comparison run).
- **PR-2 — CPU conductor thin film.** Status: DONE on branch
  `pkg178-thinfilm-pr2` (stacked on pkg178-thinfilm-pr1; commit 7cff9af, 2026-08-10;
  not yet PR'd/merged — lead rebases onto main + runs the vs-5.2 conductor hue
  sweep). Host Gulbrandsen n,k precompute (per-RGB-channel, ctor-time, never
  per-hit), `fresnelIridescenceChannel<true>` on the metallic lobe (RGB leg =
  precomputed n,k + CIE LUT; spectral leg = RGB reflectance upsampled per plan §0.5).
  Sampler/pdf unchanged; energy comp left film-free. Gates met (CPU, RTX build):
  thickness-0 metallic bit-equality byte-identical (maxΔ 0.0); metallic chi² film-ON
  (θ=0,45); furnace no-gain sweep (thickness×film-IOR). LEAD-DEFERRED: conductor
  hue-trajectory sweep vs Blender 5.2 Cycles (harness authored:
  benchmarks/cycles-parity/thin_film/conductor_hue_sweep.py; comparison run needs the
  oracle).
- **PR-3 — GPU twin of PR-1+2.** `GPrincipledClosure` params + upload, LUT upload
  unit, `gpu_pr_*` call sites in `<true>`. Gates: CPU↔GPU per-lobe parity;
  cuobjdump REG+STACK report; non-principled wavefront perf hard gate;
  principled-scene perf budget note; RTX visual sweep.
- **PR-4 — Thin Wall, CPU+GPU.** Status: DONE on branch `pkg178-thinfilm-pr4`
  (stacked on pkg178-thinfilm-pr3; commit 79cb71d, 2026-08-10; not yet PR'd —
  lead rebases onto main + runs the vs-5.2 trio + GPU sweep). thinGlassFresnel +
  ThinGlassReflect/Transmit + Translucent lobes, `subsurface_anisotropy` param,
  GPU twin in the same PR. Struct growth: ONE packed float (thinWallAniso) — GMaterial
  stays 640 B (measured; a 2nd field rounds to 704 B and leaks <false> STACK).
  kMaxPrincipledLobes 8→10 (<true> stack only). Gates met (CPU, RTX build clean):
  default-off within-build bit-equality (glass/specular/subsurface/combined, maxΔ 0.0);
  R'+T' ≤ 1 closed-form over the ior×cos×base×tint grid (peak 1.0); thin-glass furnace
  no-gain (mean 0.99 across roughness×ior, LINEAR); thin-subsurface anisotropy split;
  chi² for ThinGlassReflect/Transmit (SphericalDomain, r∈{0.35,0.6}, θ∈{0,45}) and
  the thin-subsurface diffuse/translucent split (g∈{-0.6,0,0.6}) — all PASS.
  Found+fixed a PRE-EXISTING ggxReflect D-regularizer bug (near-specular reflection
  eval loses energy vs its D_GTR2 pdf → thin glass rendered black; also dims
  Principled metallic/specular at low roughness — flagged to lead, out of scope beyond
  the thin-glass fix). Cross-build vs pre-PR-4: glass byte-exact, other lobes ≤3.5e-6
  FP-reorder (larger principled.cpp TU; those scenes run zero PR-4 logic).
  LEAD-DEFERRED: CUDA cuobjdump REG/STACK <false>/<true>, non-principled perf, GPU
  parity, vs-5.2 paper/leaf/window trio.
- **PR-5 — addon sockets (with/after Stage 5's flag infra).** §5 mapping +
  coverage-matrix flips + pkg119b harness rows for thin film/thin wall.
  Gates: harness diff flag-off/flag-on; zero silently-dropped thin sockets on the
  flagged path; report line per pkg119-C.

Coordination: pkg128's residual charter (Glass/Metallic standalone nodes +
soap-bubble/oil-slick spectral showcase) starts only AFTER PR-3 merges and consumes
`thin_film_fresnel.h` as-is — one utility, zero duplication. Update the pkg128 spec's
"Fix plan A" pointer at Stage-4 close. Implementer test lists above are a floor
(memory `pr-named-tests-insufficient`); PRs touching BSDFs get cycles-parity-reviewer
before merge.

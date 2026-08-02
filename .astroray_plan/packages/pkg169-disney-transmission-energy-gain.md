# pkg169 — Disney Principled TRANSMISSION lobe CREATES energy in the white furnace (CPU at all roughness incl. delta; GPU rough-only, up to 2.3×)

**Pillar:** 2 (BSDF energy conservation — correctness wins over both fidelity and perf)
**Track:** A (RTX-gated for the GPU leg; CPU leg CI-runnable in linear)
**Status:** done (PR #540, 2026-08-02 — `b1da65f`. Both convictions fixed CPU+GPU. Conviction A: delta glass dropped the Fresnel common factor R/T (PBRT-v4 §9.5) + rough transmission missing the incident cosine |N·wi| (Heitz-2018 VNDF). Conviction B: GPU closure-graph reflection-pdf used sign(normal·wo) not rec.frontFace for the exit-side Fresnel → internal-reflection pdf up to ~20× too small (fixed both legs). Furnace after fix (ior 1.5): CPU 0.990/0.990/0.993/0.980/0.926/0.902, GPU 0.992/0.992/0.992/0.986/0.970/0.930; ior 1.33 both legs 0.98–0.99. RTX HW verification PASS. pkg166's 3 xfails removed, un-xfailed under --runxfail per the standing rule. One residual cell (CPU ior1.5 R=1.0 ≈0.90, multiscatter) quarantined to pkg167 per architect verdict. GPU opaque-Disney 2× filed as pkg170.)
**Estimated effort:** M (two independent convictions + mirrored fix + un-xfail)
**Depends on:** nothing open. pkg166 (linear furnace conversion, in flight) discovered it and quarantines the affected cases as `xfail(strict=False)` citing **pkg169** — this package MUST remove those markers in its fix PR (memory `xfail-gated-features-must-unxfail`; verify with `--runxfail`).

**Origin:** pkg166 implementation (2026-08-02). Converting the furnace suites
to linear rendering (the gamma clamp maps 1.78 → 1.000, the exact
`gamma-furnace-cannot-detect-energy-gain` failure mode) immediately exposed a
real energy gain in the Disney Principled transmission lobe. The old gamma
bands `[0.92, 1.03]` were green throughout.

---

## Baseline measurements (cite these; SHA `cf67a92`, RTX 5070 Ti, linear, albedo=1, ior=1.5, white env, deterministic across 32→512 spp)

Disney Principled, transmission lobe, white-furnace linear ratio (1.0 = conserving):

| roughness | CPU | GPU |
|---|---|---|
| 0 / 0.03 (delta) | **1.784** | 0.993 (conserves) |
| 0.1 | 1.099 | 1.098 |
| ... rising monotonically ... | → | → |
| 1.0 | **1.260** | **2.296** |

Controls (same rig, conserving — the defect is Disney-transmission-specific):
plain dielectric 0.994, opaque Disney 0.958.

Determinism across 32→512 spp = structural weight error, not MC noise
(memory `mc-noise-vs-deterministic`).

## The asymmetry that defines the diagnosis structure (two seams, two convictions)

- **CPU gains at ALL roughness INCLUDING delta (1.784 at R=0).** The delta
  path has no microfacet pdf/Jacobian — the only candidates are the
  delta-transmission weight itself: an eta² radiance-scaling factor applied
  where it shouldn't be, a missing 1/eta² counterpart, or a double-application
  across the sample/eval/upsample chain.
- **GPU delta CONSERVES (0.993) but rough gains up to 2.296.** The GPU delta
  leg is healthy, so the GPU defect lives in the rough-transmission microfacet
  weight — at 2.3× this smells like a pdf/Jacobian factor (the Walter 2007
  transmission Jacobian `|wi·m| eta² / (denominator²)` family), not a Fresnel
  or albedo term.
- These are **plausibly two DIFFERENT bugs on two different code paths** (CPU
  Disney transmission vs GPU closure-graph lowering — memory
  `gpu-dielectric-lowers-to-closure-graph`) that must be convicted SEPARATELY.
  Do not assume one mechanism; do not fix one side by mirroring the other
  until each is convicted against the citation.

**Priors — this is the eta²-family, OPPOSITE direction:** PR #404 (GPU delta
refraction eta² albedo-clamped → energy DEFICIT), PR #423 (CPU eta²
albedo-LUT clamp → deficit; memory `rough-glass-residual-is-multiscatter`),
memory `refraction-frontface-bug`. Every prior member was a LOSS because a
clamp ate a legitimate >1 factor; a GAIN suggests the factor applied twice, or
applied without its reciprocal-direction counterpart. Audit every eta²
application point on both legs as step one of each conviction.

## Diagnosis-first contract (blocking order)

1. **Conviction A — CPU delta-transmission weight.** Instrument the delta
   branch (per-event `(f, pdf, throughput)` dump, pkg141 pattern) on the
   furnace scene at R=0. Trace every eta²/1-over-eta² application from
   `sample()`/`sampleSpectral()` through the spectral upsample (PR #423's
   factor-out-the-magnitude path) to the integrator's radiance-transport
   convention (PBRT-v4 §9.5.2 radiance scaling under refraction — whether
   eta² belongs at all depends on the transport-quantity convention; state
   the repo's convention explicitly in the finding). Convict the exact line.
2. **Conviction B — GPU rough-transmission weight.** Same instrumentation on
   the GPU closure-graph rough-transmission branch at R=0.6/1.0. Compare
   term-by-term against Walter et al. 2007 (EGSR), "Microfacet Models for
   Refraction through Rough Surfaces" — eq. 17 (BTDF) + eq. 38 (half-vector
   Jacobian) — and the CPU twin (which gains only ~1.26×, so the two legs
   differ by an additional ~1.8× factor on GPU; find THAT factor first, it is
   the sharpest lead).
3. **Fix with citations** (CLAUDE.md §6 — invoke `cite-algorithm` before any
   weight-formula change; canonical refs: Walter 2007 for microfacet
   transmission, PBRT-v4 §9.5.2 / pbrt `DielectricBxDF` for refraction
   radiance scaling; PR #404/#423 in-repo history for where eta² handling
   lives). CPU and GPU mirrored; the same-hemisphere/frontFace handling
   re-checked against memory `refraction-frontface-bug` while in there.
4. **Un-xfail:** remove pkg166's `xfail(strict=False)` quarantine markers on
   the affected furnace cases in the fix PR; prove with `--runxfail` that the
   cases genuinely pass.

## Acceptance (all linear, floor+ceiling — pkg166 rules; a gamma gate is not evidence here)

- [ ] Disney transmission white furnace at R ∈ {0, 0.03, 0.1, 0.3, 0.6, 1.0},
      ior 1.5, albedo=1: CPU AND GPU within `[0.92, 1.03]` linear (band
      changes only with architect sign-off).
- [ ] Controls unchanged: plain dielectric and opaque Disney stay conserving
      (regression guard that the fix didn't leak into healthy paths).
- [ ] A second ior point (e.g. 1.33) at delta + one rough value, both legs —
      an eta²-family fix that only works at ior 1.5 is not a conviction.
- [ ] pkg166's quarantine xfails removed and passing under `--runxfail`.
- [ ] Finding doc `.astroray_plan/docs/pkg169-transmission-energy-gain-findings.md`
      with both conviction traces, the repo's radiance-transport convention
      statement, and the citation-to-line mapping.

## Non-goals

- Not the multiscatter/compensation family (pkg167 dielectric reflection,
  pkg129 metal) — this is a single-scatter weight defect, orders louder.
- Not re-touching PR #423's albedo-LUT factor-out (verified shipped) unless
  Conviction A lands exactly there — in which case cite it, don't re-derive.
- No gate-band widening ever; the fix moves the renderer to the band, not the
  band to the renderer.

## Provenance

Filed URGENT by the architect 2026-08-02 at team-lead request, mid-pkg166
implementation, so impl-pkg166 can cite the number in its quarantine xfails.
Discovery is itself the pkg166 thesis validated: a gamma furnace structurally
cannot see energy gain; the first linear run found a shipped lobe creating up
to 2.3× energy.

## Hardware verification 2026-08-02

**Hardware/software:** RTX 5070 Ti, driver 610.47, Windows 11 (10.0.26200), CUDA
12.8, OptiX 9.1.0, OIDN 2.4.1. Worktree HEAD pinned at `945e9b8493281687b2c14d159951193b69d171e2` (PR #540), verified before build (contamination guard).

### Gate results (verbatim)

**tests/test_disney_rough_glass_furnace.py --runxfail** (forces the pkg167-owned
quarantine cell to actually run): 5 passed, 1 failed exactly as documented —
`test_disney_rough_glass_furnace_energy_cpu_r1_ior15` measured **0.9017**
(doc says ~0.90/0.903; xfail(strict=False) citing pkg167, not this PR's scope).

Measured values (ior 1.5, direct script call matching the test's `_furnace`):

| roughness | CPU | GPU |
|---|---|---|
| 0.0 (delta) | 0.9897 | 0.9929 |
| 0.03 (delta) | 0.9897 | 0.9929 |
| 0.1 | 0.9930 | 0.9923 |
| 0.3 | 0.9799 | 0.9857 |
| 0.6 | 0.9259 | 0.9699 |
| 1.0 | 0.9017 (quarantined, owned by pkg167) | 0.9298 |

All within claimed bands: CPU 0.9259-0.9930 (spec claimed 0.926-0.993), GPU
0.9298-0.9929 (spec claimed 0.930-0.992).

**Second ior point (1.33), delta + one rough value, both legs:**

| config | value |
|---|---|
| ior 1.33 delta CPU (R=0) | 0.9920 |
| ior 1.33 delta GPU (R=0) | 0.9932 |
| ior 1.33 rough CPU (R=0.6) | 0.9795 |
| ior 1.33 rough GPU (R=0.6) | 0.9921 |

All ≥ 0.980 as required.

**tests/test_dielectric_glass_furnace.py** (plain-dielectric control): 2 passed.
Measured CPU ior {1.0,1.1,1.5,2.0} = 0.9950/0.9958/0.9938/0.9927; GPU =
0.9930/0.9935/0.9930/0.9926. Unchanged from the ~0.993 baseline — the fix did
not leak into the plain-dielectric path.

**tests/statistical/test_chi2_bsdf.py -k disney_glass** (no `--runxfail`):
1 xfailed as documented — `test_chi2_disney_glass[0.3-45]` chi²=34987.970271
(1025 dof), identical to the pre-existing pkg150 quadrature-artifact xfail
reason string. Unaffected by this PR.

**Regression set** (`test_disney_transmission_peak_alignment.py`,
`test_disney_energy_conservation.py`, `test_disney_reflection_not_black.py`,
`test_glass_sphere_caustic.py`): 275 passed, 0 failed.

**tests/test_material_properties.py -k glass**: 3 passed
(`test_glass_transmits_background_color`, `test_glass_ior_changes_appearance`,
`test_glass_less_opaque_than_black`).

**pkg64 prism/GPU-CPU-parity gates** (6 files): 9 passed, 2 xfailed
(pre-existing, undisturbed), 1 xpassed. No new failures.

**pkg160/pkg163 metal parity gates** (closure-graph `pdf()` shared with the
GPU frontFace fix in this PR): 34 passed, 0 failed.
`test_pkg163_metal_spectral_colorspace_parity` GPU/CPU ratios R/G/B =
1.0164/1.0204/1.0159 (neutral), seed-averaged spread 0.0025 (chromatic) — same
shape of numbers as the prior #533 verification; metal path untouched.

### Visual inspection

- `tests/test_glass_sphere_caustic.py` scene (plain dielectric sphere,
  `light_tracer_caustic`, **CPU-only per the test's own docstring**): rendered
  CPU — bright focused caustic spot on the floor, peak luminance 0.500 (gate
  measures ≥0.25), sphere itself dark/near-black from this angle (expected:
  the scene is deliberately dim overall so the caustic dominates). No
  fireflies, no banding. GPU render of this specific CPU-only integrator was
  attempted for completeness and produced a near-black result with no caustic
  spot (max luminance 0.019 vs CPU's 0.500) — this integrator is documented
  CPU-only and is not part of this PR's gate surface; flagging only as a
  known non-target rather than a pkg169 regression.
- Disney glass sphere (`path_tracer`, the code path this PR actually
  touches), rendered CPU vs GPU at roughness {0.0 delta, 0.6, 1.0}, ad-hoc
  scene (sun + floor): CPU and GPU visually match at each roughness — clear
  refraction with a dim specular highlight at R=0 (no black glass), frosted
  transmission at R=0.6, near-fully-diffuse at R=1.0. No fireflies, no
  banding/quantization artifacts, no NaN pixels (checked numerically:
  `np.isnan(img).any() == False` at all 6 renders), no mode regressions.
- `test_results/mat_glass_*.png`, `mat_overexposure_glass.png`,
  `mat_overexposure_disney_glass.png` (from the material-properties test run):
  clean MC noise only, no fireflies, no black glass, consistent transmission
  across IOR 1.2/1.5/2.0.

### Anomalies worth watching

- The `light_tracer_caustic` GPU near-black result above is worth a follow-up
  ticket if GPU support for that integrator is ever claimed — it is currently
  undocumented as GPU-supported and this session found no evidence it works,
  but it is out of scope for pkg169 (which never touches that integrator).

**Verdict: PASS**, bound to `945e9b8493281687b2c14d159951193b69d171e2`. All
declared gates green (matching or better than claimed bands); the one
documented multiscatter quarantine cell measured within the documented ~0.90
value; controls, chi2 xfail, and the metal-parity path are undisturbed;
visual inspection found no regressions on the code path this PR touches.

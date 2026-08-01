# pkg163 — GGX energy compensation computed in different colour spaces: CPU per-wavelength vs GPU per-RGB-then-upsample (metal-only today; owns retiring pkg160's r=0.9 band exception)

**Pillar:** 3 (GPU/CPU spectral parity)
**Track:** A (RTX-gated)
**Status:** in review — direction A implemented (PR pending, 2026-08-01). GPU metal now builds its spectral response per-wavelength (`gpu_metal_eval_spectral`, the device mirror of `MetalPlugin::evalSpectral`), routed through `gpu_material_eval_spectral` / `gpu_material_sample_spectral` for `GMAT_METAL` and the closure-graph conductor lobe. pkg160's r=0.9 [0.95,1.10] band exception retired; decisive neutral-vs-chromatic control added as `tests/test_pkg163_metal_spectral_colorspace_parity.py`. Local CUDA build/RTX verify + shade-stage register measurement (gate 4) PENDING team-lead HW gate. Precondition MET 2026-07-25: pkg160 merged to main as PR #527/`2d5bb27`.
**Estimated effort:** S–M (direction A is a per-λ mirror of an existing 30-line CPU function + a register measurement; direction B is trivial but touches the oracle — see Fix contract)
**Depends on:** pkg160 merged (owner-approved 2026-07-26 with the documented r=0.9 exception). Related: pkg155 (the shade stage is at 221 regs/thread, 1 block/SM — any per-wavelength state added there has a real occupancy cost; this tension is the core design question). Evidence: `test_results/overnight_report_2026-07-25/pkg160_hw_numbers.json`.

**Origin:** pkg160 hardware verification (team-lead, 2026-07-26, RTX 5070 Ti, pkg160 branch, linear output). **Pre-existing architecture, not a pkg160 regression** — before pkg160 the GPU had no compensation term at all, so there was no color-space question to disagree about; a 3.5× missing-term error drowned a 7% color-space error. pkg160 made it visible.

---

## Defect

**CPU and GPU compute the metal spectral response in different colour spaces.**
CPU `MetalPlugin::evalSpectral` (`plugins/materials/metal.cpp:61-90`) is natively
per-wavelength: `F0_λ = albedo_spec_.sample(lambdas)` (Jakob-Hanika spectrum),
per-λ Schlick Fresnel, and `multiScatter_λ = albedo_spec_.sample(lambdas) ·
(Fms · msWeight · 1.3)` with scalar `Fms`. The GPU computes the whole f in
**RGB** (`gpu_metal_eval`, incl. pkg160's mirrored compensation term) and then
upsamples the **sum once** through the Jakob-Hanika LUT
(`gpu_material_sample_spectral`, `include/astroray/gpu_materials.h` — the
`gpu_rgbToSampledSpectrum(s.f, …)` tail). The JH upsample is nonlinear and not
scalar-homogeneous: `JH(a + b) ≠ JH(a) + JH(b)` and `JH(c·a) ≠ c·JH(a)`, so the
two constructions agree **only for a flat (neutral) albedo spectrum**. For a
chromatic albedo they diverge, growing with both roughness (compensation-term
size) and grazing angle.

### Measured (RTX 5070 Ti, pkg160 branch, plain metal, albedo [0.92, 0.78, 0.35], GPU/CPU linear mean ratio)

| roughness | R | G | B |
|---|---|---|---|
| 0.05 | 0.9998 | 1.0000 | 0.9977 |
| 0.30 | 1.0052 | 0.9980 | 1.0040 |
| 0.60 | 1.0247 | 0.9964 | 1.0288 |
| **0.90** | 1.0393 | 1.0137 | **1.0722** |

### The three isolations that pin the mechanism (carry these into any debugging session)

1. **r=0.05 is at parity** (0.9977–1.0000) — the regime where the compensation
   term is inert. A missing or mis-scaled term would diverge there too; this one
   does not. The defect lives in the compensation-dominated regime.
2. **Grazing angle is the amplifier.** Same material, far camera:
   R 1.0052 / G 1.0025 / B 1.0056. Close 60° framing (sphere fills frame):
   R 1.0257 / G 1.0154 / B 1.0743. Chromatic background contributes only ~0.3%.
3. **Decisive — neutral-vs-chromatic control.** Neutral [0.35, 0.35, 0.35] gives
   **B = 1.0074**; chromatic with the SAME B channel value (0.35) gives
   **B = 1.0743**. Same channel value, 10× the divergence; the only variable is
   whether the *other* channels differ. Channel spread collapses 0.0589 → 0.0023
   (25×) on neutral albedo. That is a spectral-upsampling signature and admits no
   other explanation.

---

## Scope survey (architect, 2026-07-26 — checked before scoping, findings differ from the initial "not metal-specific" assumption)

The filing request assumed Disney and glass share the divergence. **They do not
— the CPU↔GPU parity defect is metal-only today.** What the survey found:

1. **Metal — DIVERGES (in scope).** CPU has a native per-λ `evalSpectral`
   (`metal.cpp:61-90`); GPU is RGB-then-upsample. The only material in the tree
   with this asymmetry.
2. **Disney — twins are CONSISTENT (no parity defect).** Disney's CPU
   `evalSpectral` is itself an RGB-upsample fallback:
   `Vec3 rgb = eval(rec, wo, wi); return RGBAlbedoSpectrum({rgb...}).sample(lambdas)`
   (`disney.cpp:689-695`, the "pkg13 fallback" comment). Its
   `ggxCompensationFactor` is per-RGB `Vec3` on CPU (`disney.cpp:96-105`,
   `ggxDarkeningChannel` per channel) and was mirrored per-RGB to the GPU by
   #523 (`gpu_materials.h:904`). Same colour space on both sides → they agree
   with each other. There IS a **shared** per-RGB-vs-per-λ approximation against
   a hypothetical spectral ground truth (the darkening function is nonlinear in
   Fss), but that is a spectral-accuracy note, NOT a CPU/GPU parity defect, and
   it is **out of scope here** (changing it would move the canonical CPU output).
3. **Glass — chromatically neutral by construction (out of scope).**
   `ggxGlassCompensationFactor` returns a **scalar float** derived from the
   colourless `fresnelDielectricFss(etap)` (`disney.cpp:86-94`), applied
   identically on CPU (`:373`) and GPU (`gpu_materials.h:716`). A scalar cannot
   produce a chromatic divergence signature.

**The general class rule (record so it is not re-created):** this divergence
arises exactly when a material has a **native per-wavelength CPU `evalSpectral`
while its GPU twin evaluates RGB and upsamples**. Metal is the only current
member. Any future CPU material gaining a native spectral eval (or any GPU
material gaining one) must land on both sides of the twin in the same colour
space, or add itself to this package's gate.

**Detection heuristic (pkg160 implementer, 2026-07-26 — how the NEXT one gets
caught):** a seam divergence becomes measurable only when a **chromatic,
angle- or roughness-amplified factor** passes through it — pkg160 made this one
visible by pushing a roughness-amplified compensation term through the seam.
Factors that are small, achromatic, or view-independent hide there
indefinitely. Practical test: whenever a new per-lobe factor lands on either
side of a twin, run isolation 3 (neutral-vs-chromatic albedo, same channel
value) at high roughness + grazing framing. It is cheap and decisive — channel
spread that collapses on neutral albedo convicts the seam.

---

## The seam — the defect is metal-only; the DECISION is not (2026-07-26 refinement)

pkg160's implementer sharpened the scoping, and the distinction is load-bearing:

> any solution has to decide **where RGB→spectral upsampling sits relative to
> per-lobe scalar factors**, and that same seam already carries the **Fresnel**
> term in both `gpu_metal_eval` and `MetalPlugin::evalSpectral`, plus Disney's
> compensation and `ggxDirectionalAlbedo`. Metal is where it became measurable
> because pkg160 put a roughness-amplified factor through it, not where it
> lives.

Seam inventory (what already flows through the upsample-position decision):

| Factor | CPU side | GPU side | Twin state |
|---|---|---|---|
| Metal Fresnel + compensation | per-λ (`metal.cpp:79-88`) | per-RGB, summed, upsampled once | **ASYMMETRIC — this package's defect** |
| Disney Fresnel / `ggxCompensationFactor` / `ggxDirectionalAlbedo` | per-RGB (`disney.cpp:96-134`, eval→upsample fallback `:689-695`) | per-RGB (#523 mirror) | symmetric (consistent twins) |
| Glass compensation | scalar, colourless | scalar, colourless | symmetric by construction |

**Binding consequences for the fix (either direction):**

1. **No term-level patches at the seam.** Direction A means mirroring the WHOLE
   `MetalPlugin::evalSpectral` construction — F0 spectrum, per-λ Fresnel, and
   the compensation term move together, exactly as the CPU composes them. Do
   NOT spectralize the compensation factor alone while metal's Fresnel stays
   RGB: that creates a new intra-lobe seam inconsistency inside `gpu_metal_*`
   worse than the one being fixed.
2. **The PR must carry a "seam statement"** (a short section in the PR body):
   where the upsample sits for metal post-fix, and how that position relates to
   the Disney compensation / `ggxDirectionalAlbedo` / glass treatments per the
   policy below — so the reviewer can check global consistency, not just local
   correctness.

**Architect ruling — is a broader colour-pipeline package needed above pkg163?
No, not now; a policy rule replaces it.** The CPU itself is deliberately
heterogeneous at this seam (metal native-spectral, Disney RGB-fallback by the
pkg13 perf-budget decision, dielectric special-cased via the eta² factoring and
the dispersive hero-collapse sampler). The consistency rule that prevents
"metal spectral, neighbours RGB" from being unprincipled is therefore NOT
"everything at the same seam position" — it is:

> **Each material's GPU twin sits at the SAME seam position as its CPU twin.
> The seam position is a per-material, CPU-canonical property.**

Under that rule, direction A is globally consistent (metal's twins both per-λ;
Disney's twins both per-RGB; glass symmetric-scalar), and no umbrella package
is required. **Trigger for revisiting** (file the colour-pipeline package only
then): a spectral-ground-truth gate — not a parity gate — demanding per-λ
Disney (e.g. dispersion or measured-conductor spectra on Disney metallics), or
an owner decision to lift the pkg13 fallback. That package would move canonical
CPU output and must be owner-initiated, not backed into from a parity fix.

---

## Fix contract — the direction decision (the interesting part; do not paper over it)

Two real directions plus a non-option. The tension: parity + spectral fidelity
vs the pkg155 register budget (shade stage at **221 regs/thread, 1 block/SM**;
recovery target ≤128 — pkg155 Phase 1).

- **A — GPU goes per-wavelength for metal (architect recommendation, gated on a
  measured register cost).** Mirror `MetalPlugin::evalSpectral` into a device
  `gpu_metal_eval_spectral` used by `gpu_material_sample_spectral` for
  `GMAT_METAL` (and the closure-graph conductor lobe routed to metal):
  per-λ F0 from the JH albedo coefficients (`gpu_jhLookupCoeffs` already exists
  on device), per-λ Fresnel, `multiScatter_λ = albedo_λ · (Fms · msWeight ·
  1.3)` with the same scalar `Fms`. Sampling/pdf logic unchanged — only the
  f-spectral construction. The arithmetic is on the 4-λ state the kernel already
  carries; the plausible cost is small, **but plausibility is not evidence**:
  measure shade-stage regs/thread before/after via the **runtime profile**
  (static `-Xptxas -v` counts are invalid under `-rdc=true` — pkg155 2026-07-26
  correction). Any material register increase goes to the owner with the number,
  next to pkg155's target — do not trade occupancy for 7% silently.
- **B — CPU metal drops its native per-λ `evalSpectral` to the RGB-upsample
  fallback (the Disney pattern).** Restores parity by making the twins
  consistently approximate. Zero GPU cost, ~5-line change. Costs: it **lowers
  the oracle's spectral accuracy** to match the approximation (philosophically
  backwards for a spectral renderer), touches canonical CPU code, and shifts all
  existing CPU metal spectral renders (re-baseline burden across refbank/tests).
  Take this ONLY as an owner-approved fallback if A's measured register cost is
  material.
- **C — accept RGB and bound the error: NOT viable as scoped.** The bound is
  already measured (1.0722 at the gate scene) and exceeds the standard band, so
  C cannot meet the definition of done below without re-scoping the gate. Listed
  to record why it was rejected, not as an option.

Whichever direction lands, cite: Kulla & Conty 2017 ("Revisiting Physically
Based Shading at Imageworks" — the compensation lineage the code already cites),
the Cycles `microfacet_ggx` energy-preservation lineage
(`bsdf_microfacet.h`, BSD-3-Clause per the pkg124/#501 license correction), and
Jakob & Hanika 2019 ("A Low-Dimensional Function Space for Efficient Spectral
Upsampling" — the upsampler whose nonlinearity is the mechanism). CPU
`metal.cpp` is the canonical mirror source for direction A.

## Gates (definition of done — the exception must retire)

1. **Un-widen pkg160's band exception.** pkg160's plain-metal parity gate merged
   with a documented **roughness-0.9-only** band of `[0.95, 1.10]` (measured
   1.0722) instead of the standard `[0.95, 1.05]`. This package's definition of
   done is **`[0.95, 1.05]` restored at ALL roughnesses** (mean AND median, per
   pkg160's gate design) — the exception is self-retiring, not permanent.
2. **The decisive control becomes a regression test:** neutral `[0.35]³` and
   chromatic `[0.92, 0.78, 0.35]` at r=0.9, grazing framing, both in-band, and
   the chromatic channel spread bounded (neutral measured 0.0023; assert spread
   ≤ 0.01 post-fix).
3. **No regression at r ≤ 0.3** (already at parity — the fix must not perturb
   the compensation-inert regime beyond noise).
4. **If direction A:** shade-stage regs/thread (runtime profile) before/after in
   the PR body; no material growth without explicit owner/pkg155 sign-off.
5. Furnace/energy suites green; build evidence per CLAUDE.md; RTX-verified
   (CI is blind).

## Non-goals

- **Disney's shared per-RGB compensation approximation** — consistent twins, not
  a parity defect; touching it moves the canonical CPU. File separately only if
  a spectral-ground-truth gate ever demands it.
- **Glass compensation** — scalar, colourless, identical on both sides.
- **pkg158's Disney near-delta reconciliation** (different function, different
  question).
- **pkg155's recovery work itself** — this package only owes it a register
  measurement, not a register diet.

## Provenance

Filed by the architect 2026-07-26 from the team-lead's pkg160 hardware
verification (RTX 5070 Ti, pkg160 branch, linear output;
`test_results/overnight_report_2026-07-25/pkg160_hw_numbers.json`), including
the three mechanism isolations recorded verbatim above. Scope survey (Disney
consistent-twins, glass scalar-neutral, metal-only divergence) performed by the
architect against `plugins/materials/disney.cpp:86-135,689-695`,
`plugins/materials/metal.cpp:61-90`, `include/astroray/gpu_materials.h:711-716,
899-904` before scoping — the initial "any chromatic material with compensation"
generalization is NOT borne out by the code; the honest scope is the class rule
in §Scope survey.

## Hardware verification 2026-08-02

**Hardware:** NVIDIA GeForce RTX 5070 Ti. **OS:** Windows 11 Enterprise 10.0.26200.
**CUDA:** v12.8 (`nvcc.exe`). **OptiX:** 9.1.0. **OIDN:** 2.4.1.
Worktree: `.claude/worktrees/pkg163` (branch
`pkg163-spectral-compensation-colorspace-parity`), bound to HEAD
`5a04c2ab76a2b9284e0f0d347674e7e0c1712c08`. Rebuilt clean via
`scriptsuilduild_cuda_worktree.bat` (first invocation via bare `cmd /c`
under the Bash tool produced a false-green banner-only interactive shell, exit
0 with nothing built; re-invoked with `MSYS_NO_PATHCONV=1` to get a real
build). No compiled source changed between 883fe06 (the material fix) and
5a04c2a (this commit, test-file-only); confirmed the loaded `.pyd`
(`build_cuda/astroray.cp313-win_amd64.pyd`, mtime 2026-08-01 23:45:04) is
newer than `include/astroray/gpu_materials.h` (mtime 2026-08-01 23:32:25,
last touched at 883fe06), so it reflects the PR's actual code change.
`astroray.__file__` confirmed to resolve inside the worktree's own
`build_cuda/`.

This run is the first full execution of the amended gate statistic
(2560 spp, 4-seed-averaged chromatic spread, bound unchanged at <=0.01). The
prior head (883fe06) had failed only this sub-assertion at 0.0133 (single
seed, 256 spp).

### Pass/fail table

| Test | Result |
|---|---|
| `test_pkg160_plain_metal_gpu_cpu_parity.py::test_plain_metal_gpu_cpu_parity[0.05]` | **PASSED** |
| `test_pkg160_plain_metal_gpu_cpu_parity.py::test_plain_metal_gpu_cpu_parity[0.15]` | **PASSED** |
| `test_pkg160_plain_metal_gpu_cpu_parity.py::test_plain_metal_gpu_cpu_parity[0.3]` | **PASSED** |
| `test_pkg160_plain_metal_gpu_cpu_parity.py::test_plain_metal_gpu_cpu_parity[0.6]` | **PASSED** |
| `test_pkg160_plain_metal_gpu_cpu_parity.py::test_plain_metal_gpu_cpu_parity[0.9]` | **PASSED** |
| `test_pkg163_metal_spectral_colorspace_parity.py::test_neutral_metal_parity_in_band` | **PASSED** |
| `test_pkg163_metal_spectral_colorspace_parity.py::test_chromatic_metal_parity_in_band_and_spread_bounded` | **PASSED** |

`pytest tests/test_pkg160_plain_metal_gpu_cpu_parity.py tests/test_pkg163_metal_spectral_colorspace_parity.py -v -s --tb=short`
-> **7 passed in 5.57s**.

### Measured numbers (verbatim)

pkg160 plain-metal GPU/CPU parity (band `[0.95, 1.05]` at all roughnesses,
restoring the standard band scoped in this package's Gate 1):

```
roughness=0.05: R ratio(mean/median)=0.9998/0.9999  G=1.0000/0.9996  B=0.9977/0.9974
roughness=0.15: R ratio(mean/median)=0.9999/1.0031  G=1.0007/1.0004  B=0.9983/1.0007
roughness=0.3:  R ratio(mean/median)=0.9989/1.0000  G=1.0028/1.0036  B=0.9948/0.9966
roughness=0.6:  R ratio(mean/median)=1.0100/1.0060  G=1.0052/1.0071  B=1.0085/1.0059
roughness=0.9:  R ratio(mean/median)=1.0153/1.0076  G=1.0171/1.0078  B=1.0112/1.0062
```

pkg163 neutral metal (`[0.35]^3`, r=0.9, grazing framing):

```
GPU/CPU mean ratios R/G/B = 1.0164/1.0204/1.0159, spread=0.0046
```

pkg163 chromatic metal (`[0.92, 0.78, 0.35]`, r=0.9, grazing framing,
2560 spp, 4 seeds):

```
seed=160160: R/G/B = 1.0182/1.0182/1.0187, spread=0.0006
seed=163163: R/G/B = 1.0174/1.0200/1.0149, spread=0.0051
seed=271828: R/G/B = 1.0143/1.0136/1.0148, spread=0.0013
seed=314159: R/G/B = 1.0170/1.0191/1.0200, spread=0.0030
seed-averaged spread = 0.0025 over seeds [160160, 163163, 271828, 314159]
(per-seed [0.0006, 0.0051, 0.0013, 0.0030])
```

Seed-averaged spread 0.0025 is well under the <=0.01 bound in Gate 2, with
per-seed values ranging 0.0006-0.0051 (i.e. even the worst single seed would
have passed the original bound; the 2560 spp + 4-seed averaging resolved
noise in the statistic, not a marginal pass).

### Visual inspection

Both gate files are numeric-only parity assertions (mean/median channel
ratios); neither writes PNGs to `test_results/`, `benchmarks/`, or
`tests/reference/`. No visual inspection artifacts were produced by this run.

### Anomalies

None observed. All roughness bands (0.05 through 0.9) are within
`[0.95, 1.05]` on both mean and median, retiring pkg160's roughness-0.9-only
`[0.95, 1.10]` band exception per this package's Gate 1.

# Other-engines technique sweep — what non-Cycles renderers pioneered (2026-07-19)

**Method:** targeted deep-research pass — six technique families approved by the owner
on 2026-07-19; primary sources fetched (papers, repo file listings, raw source files,
LICENSE files). Licenses marked **verified** were confirmed by fetching the actual
license file; those marked *verify-at-port* rest on repo README/search evidence and
must be re-checked before any code is ported (same rule as the 2026-07 PBR sweep).
This doc is the CLAUDE.md §6 research record for all six families.

## Headline

The immediately-adoptable item is **family 1**: Mitsuba 3's chi-square sampler
validation harness (`chi2.py`, BSD-3) is a self-contained ~600-line Python module that
ports almost directly onto a pybind11-exposed BSDF API — it slots straight into
Astroray's existing gate culture and would statistically validate every sampler we
own (Disney BSDF, light tree, phase functions, spectral distributions). **Family 2**
(LPEs) has a clean, renderer-agnostic BSD-3 reference in OSL's
`liboslexec/{lpeparse,lpexp,automata,accum}` — and the Astroray-unique
emission-mechanism labeling (disk thermal vs synchrotron jet vs lensed starlight) is a
straightforward alphabet extension that no other engine offers. **Families 3–5** each
have one clearly-best open reference (Mitsuba `specfilm`, Cycles host-mapped memory
fallback, Cycles `adaptive_sampling.h` respectively), all license-clean. **Family 6**
is horizon-only, but the GR prior art (Jipole, arXiv:2509.07065) is newer and closer
to us than expected.

---

## 1. Chi-squared sampler validation + statistical BSDF testing (HIGHEST PRIORITY)

### Methodology

Pearson chi-square goodness-of-fit on projected sampling distributions: draw N
samples from `BSDF::sample()`, bin them into a (θ, φ) histogram over the sphere;
independently compute expected bin counts by *numerically integrating* `BSDF::pdf()`
over each spherical-rectangle bin; pool low-expectation cells; compute the χ²
statistic and p-value against a significance level, with multiple-testing correction
(Šidák) since many BSDF configurations are tested. This catches both broken sampling
routines and pdf-evaluation mismatches — exactly the class of bug unit tests on
single values miss.

### Reference implementations

| Source | License | Files |
|---|---|---|
| **Mitsuba 3** `github.com/mitsuba-renderer/mitsuba3` | **BSD-3-Clause (verified** — `LICENSE`, © Wenzel Jakob**)** | `src/python/python/chi2.py`: `ChiSquareTest(domain, sample_func, pdf_func, sample_dim=2, sample_count=1e6, res=101, ires=4)`; methods `tabulate_histogram()` (weighted-sample histogram), `tabulate_pdf()` (trapezoid-rule integration per cell), `run(significance_level, test_count)` (cell pooling, χ² statistic, Šidák correction, dumps `chi2_data.py` visualization on failure). Adapters: `BSDFAdapter`, `EmitterAdapter`, `MicrofacetAdapter`, `PhaseFunctionAdapter`, `SpectrumAdapter`. Domains: `SphericalDomain` ([cos θ, φ] parameterization), `PlanarDomain`, `LineDomain`. Developer-guide page: mitsuba.readthedocs.io → Developer guide → Testing. |
| **pbrt-v4** `github.com/mmp/pbrt-v4` | **Apache-2.0 (verified** — `LICENSE.txt` is the Apache-2.0 text**)** | `src/pbrt/bsdfs_test.cpp`: `Chi2Test(frequencies, expFrequencies, thetaRes, phiRes, sampleCount, minExpFrequency, significanceLevel, numTests)`; `FrequencyTable()` (MC histogram), `IntegrateFrequencyTable()` (expected counts via `AdaptiveSimpson2D`), `Chi2CDF()` via `RLGamma()` (Cephes regularized incomplete gamma). Constants: `CHI2_SLEVEL 0.01`, `CHI2_SAMPLECOUNT 1000000`, `CHI2_THETA_RES 80`, `CHI2_PHI_RES 160`, `CHI2_MINFREQ 5`, `CHI2_RUNS 5`. Tests: `TEST(BSDFSampling, Lambertian)`, `TRCondIso/Aniso`, `TRDielIso/Aniso/IsoInv/AnisoInv`. Companion tests in `samplers_test.cpp`, `lightsamplers_test.cpp`, `shapes_test.cpp`. |

### Fit and porting plan

Astroray already exposes a pybind11 module. The Mitsuba harness is the one to port:
it is pure Python, renderer-agnostic by design (everything goes through
`sample_func`/`pdf_func` callables), and its only Mitsuba dependency is Dr.Jit
vectorization — replaceable with NumPy batching over a batched
`astroray.bsdf_sample(wi, u) -> (wo, pdf, weight)` / `astroray.bsdf_pdf(wi, wo)`
binding. The pbrt-v4 C++ constants (80×160 bins, 10⁶ samples, α=0.01, min expected
frequency 5, Šidák over runs) are the battle-tested parameterization to copy.
`SpectrumAdapter` is a bonus unique to us: it can statistically validate Jakob-Hanika
upsampled spectra sampling and light-spectrum sampling, not just BSDFs.

**Cost: low-moderate (1–2 sessions).** New pytest gate: chi² pass required for every
BSDF lobe config (Disney lobes × roughness grid × incident angles), later extended
to light-tree emitter sampling and phase functions. This is the recommended first
package out of this doc.

---

## 2. Light Path Expressions + light groups

### Grammar / spec

- **Origin:** Heckbert's path regular-expression notation `L(S|D)*E` — P. Heckbert,
  "Adaptive Radiosity Textures for Bidirectional Ray Tracing", SIGGRAPH 1990,
  DOI 10.1145/97879.97895.
- **De-facto open standard:** OSL Light Path Expressions, specified in the
  AcademySoftwareFoundation/OpenShadingLanguage wiki ("OSL Light Path Expressions")
  and implemented in the OSL repo (**BSD-3-Clause, verified** — `LICENSE.md`,
  © Contributors to the OSL project). Grammar: events `C` (camera), `L` (light),
  `O` (emissive object), `B` (background); interactions `R` (reflect), `T`
  (transmit), `V` (volume); scattering modes `D` (diffuse), `G` (glossy), `S`
  (singular), `s` (straight); full event tokens `<TypeMode'label'>` with
  user-defined labels attached to closures (`diffuse(N, "label", "alice")`); regex
  operators `.`, `[]`, `[^]`, `*`, `+`, `?`, `{n,m}`, plus context-aware
  abbreviations (`D` ≡ `<.D>`, `L` ≡ `<L.>`). An LPE is matched against the path's
  event string (e.g. `CSDL`); each matching expression routes that path's
  contribution into an AOV. Arnold and RenderMan document the same grammar
  (Autodesk Arnold "Light Path Expression AOVs"; Pixar RenderMan 26 "Light Path
  Expressions") — both proprietary, cite for semantics only.

### Reference implementations

| Source | License | Files |
|---|---|---|
| **OSL** `github.com/AcademySoftwareFoundation/OpenShadingLanguage` | **BSD-3-Clause (verified)** | `src/liboslexec/lpeparse.{cpp,h}` (parser, ~464 lines), `lpexp.{cpp,h}` (expression AST, ~220 lines), `automata.{cpp,h}` (NFA construction + subset-construction to DFA, ~661 lines), `accum.{cpp,h}` (AOV accumulator driven by DFA states, ~244 lines), test `accum_test.cpp`. This subsystem is deliberately renderer-agnostic — no OSL shading dependency. |
| **appleseed** `github.com/appleseedhq/appleseed` | MIT (*verify-at-port*) | `src/appleseed/renderer/kernel/lighting/lightpathstream.{cpp,h}`, `lightpathrecorder.{cpp,h}` — records full light paths for post-render per-pixel path inspection. Complementary (debugging/visualization), not an LPE matcher. |
| **LuxCoreRender** `github.com/LuxCoreRender/LuxCore` | **Apache-2.0 (verified** — `COPYING.txt`**)** | Light groups ("radiance groups"): each light gets `.id` (materials: `.emission.id`); film keeps one radiance buffer per group; GPU engines support 8 groups. Per-group intensity/color-temperature rescaling *after* render without resampling; per-group pass export. Wiki: "LuxCoreRender Light Groups". |
| **Cycles** `github.com/blender/cycles` | Apache-2.0 (verified in pkg114 research) | Limited `lightgroup` passes — membership-based, no path grammar. |

### Fit — the Astroray angle

Two tiers:

1. **Light groups (tier 1, cheap):** assign an emitter-group id to every light /
   emissive material; wavefront kernels write contributions into per-group
   framebuffers (8 groups like LuxCore is plenty). For Astroray this immediately
   gives **physical-emission-mechanism decomposition**: `disk_thermal`,
   `jet_synchrotron`, `starfield`, `envmap` as separate EXR layers, re-balanceable
   in post for publication figures. No other open engine labels by emission physics.
2. **Full LPE (tier 2):** port OSL's `lpeparse`+`automata` on the host (BSD-3,
   self-contained C++), compile user LPEs to a DFA table uploaded to constant
   memory; each path carries one `uint16` DFA state in the wavefront path-state SoA;
   every scatter/emission event advances `state = dfa[state][event]`; contributions
   at accepting states are routed to the mapped AOVs. Per-path cost is one table
   lookup per bounce — wavefront-friendly, no divergence. Astroray-unique alphabet
   extensions: emission-mechanism event labels (from tier 1 ids) and — beyond LPE —
   a photon-ring winding-number counter (`n=0,1,2` subimages of the black hole),
   which is a trivial extra path-state integer, not a grammar feature.

**Cost:** tier 1 low (≈1 session: emitter id plumbing + per-group buffers + addon
UI); tier 2 moderate-high (2–4 sessions: OSL automata port, DFA upload, path-state
field, AOV routing). Recommend tier 1 first; it delivers 80 % of the journal-figure
value.

---

## 3. Physical camera / sensor simulation in spectral renderers

### Literature

- **Manuka:** Fascione, Hanika, Leone, Droske, Schwarzhaupt, Davidovič, Weidlich,
  Meng, "Manuka: A Batch-Shading Architecture for Spectral Path Tracing in Movie
  Production", ACM TOG 37(3):32, 2018, DOI 10.1145/3182161 (open preprint:
  jo.dreggn.org/home/2018_manuka.pdf). Fully spectral transport with hero-wavelength
  sampling; the sensor is simulated in camera space with measured spectral response
  curves so output is "what the camera saw", not XYZ. Proprietary — literature only.
- **Production spectral imaging course:** "Spectral imaging in production",
  SIGGRAPH 2021 Courses, DOI 10.1145/3450508.3464582 — the consolidated write-up of
  camera spectral response handling in production spectral renderers.
- **Hero wavelength sampling** (already Astroray's basis): Wilkie, Nawaz, Droske,
  Weidlich, Hanika, EGSR 2014, CGF 33(4), DOI 10.1111/cgf.12419.
- **ART (Advanced Rendering Toolkit)**, cgg.mff.cuni.cz/ART — research spectral
  renderer: hero-wavelength path tracing, switchable polarisation, fluorescence
  (bi-spectral), ARTRAW + spectral OpenEXR output. License: **GNU GPL** (per project
  pages; LICENSE file not directly fetched). GPL → **literature/concept reference
  only** for Astroray; do not port code.

### Reference implementation — the one to mirror

| Source | License | Files / mechanism |
|---|---|---|
| **Mitsuba 3 `specfilm`** | **BSD-3-Clause (verified)** | Film plugin taking N named **Sensor Response Functions** as nested `spectrum` plugins (one per output channel); builds a *combined continuous distribution over all SRFs* via inverse-transform sampling and importance-samples path wavelengths from it; outputs a multichannel EXR (channels alphabetical). Docs: mitsuba.readthedocs.io → Plugins → Films. Sensor plugins (`perspective`, `thinlens`, `orthographic`, `radiancemeter`, `irradiancemeter`, `distant`, `batch`) show the sensor-as-plugin architecture. |

### Fit

`specfilm` is precisely the astronomical-detector mechanism: a JWST/NIRCam channel =
filter transmission × detector QE curve as an SRF; Astroray's spectral wavelength
sampler then importance-samples where the instrument is actually sensitive, instead
of uniformly across the band and weighting at the end. This complements (does not
replace) the paused **pkg51** telescope post-process (PSF convolution + Poisson/read
noise stay image-space, per pkg51's design decision 1); SRF importance sampling is
the *render-time* half: correct per-channel photon statistics and far lower spectral
noise in narrow bands. Thin-lens/aperture camera models (Mitsuba `thinlens`) are an
independent low-cost add.

**Cost:** moderate (2–3 sessions) — touches the spectral core's wavelength-sampling
pdf and the film accumulation, both hero-wavelength-aware; the SRF distribution
build itself is simple CDF inversion. Sequence after pkg51 resumes, or fold into a
pkg51-B.

---

## 4. Out-of-core / streaming GPU rendering

Proprietary art (RenderMan XPU, Redshift) is closed; the open, portable-to-pure-CUDA
material is:

| Source | License | What it gives us |
|---|---|---|
| **Cycles device fallback** `github.com/blender/cycles` | Apache-2.0 (verified) | `src/device/cuda/device_impl.cpp`: `shared_alloc()` using `cuMemHostAlloc(CU_MEMHOSTALLOC_DEVICEMAP \| CU_MEMHOSTALLOC_WRITECOMBINED)` (device-mapped pinned host memory), `can_map_host` capability flag, `CU_CTX_LMEM_RESIZE_TO_MAX` + `reserve_local_memory()` to predict headroom before deciding what to spill; texture-migration logic (`move_textures_to_host` in the GPU-device base class — pin exact file at port) moves the least-costly data to host when VRAM is short instead of failing. |
| **NVIDIA OptiX Toolkit — DemandLoading** `github.com/NVIDIA/optix-toolkit` | BSD-3-Clause (per README; *verify `LICENSE.txt` at port*) | Demand-paged CUDA **sparse textures**: launch renders with unresolved pages, kernels record page requests in a device-side request list, host services requests between launches, re-launch. The sparse-texture + request-list machinery is CUDA-level (works without OptiX); demand-loaded *geometry* is OptiX-tied — not portable. |
| **Academic** | — | Jaroš et al., "GPU Accelerated Path Tracing of Massive Scenes", ACM TOG 40(2), 2021, DOI 10.1145/3447807 — out-of-core wavefront path tracing with CPU-memory backing; key observation: **wavefront batching hides host-memory latency**, which is Astroray's architecture. Foundational: Garanzha et al., "Out-of-core GPU ray tracing of complex scenes" (2011). Recent: multi-GPU out-of-core via memory-access analysis (Springer LNCS 2025, 10.1007/978-3-031-85697-6_13); Cal Poly thesis 2022 (priority-scheduled geometry chunk streaming, digitalcommons.calpoly.edu/theses/2491). |

### Fit for a pure-CUDA tracer at 8 GB

Priority order:
1. **Mapped pinned-host fallback (Cycles model)** — low cost, pure CUDA, no
   architecture change: on allocation failure, place the *coldest* large buffers
   (FITS volume grids, photon maps, high-res env maps, texture atlas overflow) in
   device-mapped host memory. Renders slow down instead of dying — the right
   behavior for the 8 GB travel laptop. ~1–2 sessions.
2. **Sparse-texture demand loading (OTK model)** — moderate; only worth it once
   texture-heavy astrophysical scenes (large FITS cubes) actually overflow. 2–4
   sessions, CUDA virtual-memory APIs.
3. **BLAS/geometry streaming** — high cost, research-grade; defer indefinitely
   (astro scenes are volume/texture-heavy, not triangle-heavy).

---

## 5. Adaptive sampling with zero user knobs

### Papers

- Dammertz, Hanika, Keller, Lensch, "A Hierarchical Automatic Stopping Condition for
  Monte Carlo Global Illumination", WSCG 2010 (preprint:
  jo.dreggn.org/home/2009_stopping.pdf) — the per-pixel error metric Cycles cites.
- Christensen et al., "RenderMan: An Advanced Path-Tracing Architecture for Movie
  Rendering", ACM TOG 37(3), 2018, DOI 10.1145/3182162 — production odd/even
  half-buffer variance estimation (Cycles' stated inspiration).
- Christensen, Kensler, Kilpatrick, "Progressive Multi-Jittered Sample Sequences",
  CGF 37(4) / EGSR 2018 — sampling sequences whose every prefix is well-distributed:
  the prerequisite for per-pixel varying sample counts.

### Reference implementation

**Cycles** (Apache-2.0, verified): `src/kernel/film/adaptive_sampling.h` —
`film_adaptive_sampling_convergence_check()` computes, per pixel, the difference
between the full buffer and an auxiliary half-sample buffer:
`error = (|I.x−A.x|+|I.y−A.y|+|I.z−A.z|) · (exposure/samples) / (0.0001 + error_normalize)`
with `error_normalize = sqrt(intensity)` below 1.0 else `intensity` (brightness-
relative noise, per Dammertz §2.1); converged when `error < threshold`. Then
`film_adaptive_sampling_filter_x()` / `_filter_y()` dilate the unconverged mask (two-
pass box filter) so neighborhoods keep sampling together. Scheduling lives in
`src/integrator/render_scheduler.cpp` (check every N samples, minimum-sample floor);
`threshold = 0` triggers an **auto-derived threshold from the sample budget** —
that is the zero-knob mechanism. pbrt-v4's contribution is infrastructure, not a
stopper: `VarianceEstimator<>` (Welford online variance, `src/pbrt/util/math.h`,
book §B.2) — the numerically stable way to track per-pixel variance if we prefer
variance to half-buffers.

### What "no sampling knobs" concretely means for Astroray

Replace `samples = N` semantics with: `max_samples` (safety cap, defaulted high) +
auto noise threshold (Cycles' `threshold=0` derivation) + fixed minimum-sample floor.
Integrator loop: render in waves → run convergence-check kernel → compact the active
pixel list (our wavefront already owns compaction) → stop when all pixels converge or
cap hits. Constraints specific to us: (a) RNG must be progressive-in-samples
(pkg92's sequence choice must have PMJ/Sobol prefix property); (b) the half-buffer
should be scalar luminance, not full spectral, to avoid doubling framebuffer memory
on 8 GB; (c) OIDN interacts fine (Cycles ships the same pairing); (d) the telescope
noise pass (pkg51) is applied after and is unaffected.

**Cost: moderate (2–3 sessions):** one film kernel, scheduler change, addon UI
*removal* rather than addition.

---

## 6. Differentiable rendering (horizon survey — no action)

**Dr.Jit / Mitsuba 3** (both BSD-3-Clause; `github.com/mitsuba-renderer/drjit`):
Jakob, Speierer, Roussel, Vicini, "Dr.Jit: A Just-In-Time Compiler for
Differentiable Rendering", ACM TOG 41(4), 2022, DOI 10.1145/3528223.3530099,
arXiv:2202.01284. Dr.Jit traces Python/C++ rendering code into a specialized IR and
fuses it into data-parallel kernels (LLVM/OptiX backends) with forward- and
reverse-mode AD through loops, polymorphic calls, and ray tracing. The memory
problem of differentiating path tracers was solved in two steps: **radiative
backpropagation** (Nimier-David, Speierer, Ruiz, Jakob, SIGGRAPH 2020) — an adjoint
formulation with O(1) memory but quadratic time in path length — and **path replay
backpropagation** (Vicini, Speierer, Jakob, SIGGRAPH 2021) — linear time, constant
memory, unbiased, by re-simulating each path deterministically during the adjoint
pass. Retro-fitting AD onto Astroray's hand-written CUDA kernels is not
realistic; a Dr.Jit-style engine is a rewrite, not a feature.

For the GR/astro angle, prior art is closer than expected: **Jipole** ("A
Differentiable ipole-based Code for Radiative Transfer in Curved Spacetimes",
arXiv:2509.07065) makes the standard EHT GRRT code differentiable and demonstrates
conjugate-gradient fitting of plasma parameters; **skylight** (Julia) autodiffs
Christoffel symbols from metric coefficients; **Gradus.jl** (MNRAS 2025,
10.1093/mnras/staf1770) is spacetime-agnostic GRRT with AD support; on the inference
side, EHT parameter estimation increasingly uses differentiable or learned forward
models (deep-learning inference in visibility space, arXiv:2504.21840 / MNRAS 2025;
semianalytic differentiable dual-cone proxies for variability studies,
10.3847/2041-8213/ade431). The publishable path for Astroray is therefore *not*
differentiating the renderer, but a small standalone JAX/Dr.Jit mirror of our
geodesic + emission model for observation fitting, validated against Astroray
forward renders. Horizon item; revisit post-article.

---

## Adoption recommendation (mapped to roadmap)

| Rank | Item | Source to port | License | Cost | Roadmap slot |
|---|---|---|---|---|---|
| 1 | Chi² sampler-validation gate | Mitsuba 3 `chi2.py` (+ pbrt-v4 constants) | BSD-3 / Apache-2.0, both verified | 1–2 sessions | New pkg; immediate — extends the gate culture; validates pkg118/pkg55 work retroactively |
| 2 | Light groups by emission mechanism | LuxCore radiance-group model | Apache-2.0 verified | ~1 session | New pkg; before journal-figure production |
| 3 | Zero-knob adaptive sampling | Cycles `kernel/film/adaptive_sampling.h` | Apache-2.0 verified | 2–3 sessions | New pkg; big render-time win on 8 GB hardware |
| 4 | Host-mapped memory fallback | Cycles `device/cuda/device_impl.cpp` | Apache-2.0 verified | 1–2 sessions | New pkg; robustness for FITS/photon-heavy scenes |
| 5 | SRF spectral sensors (detector QE) | Mitsuba 3 `specfilm` | BSD-3 verified | 2–3 sessions | Pair with pkg51 resume (pkg51-B) |
| 6 | Full LPE automata | OSL `liboslexec` LPE subsystem | BSD-3 verified | 2–4 sessions | After light groups, before article figures |
| 7 | Demand-loaded sparse textures | NVIDIA OptiX Toolkit DemandLoading | BSD-3 (*verify*) | 2–4 sessions | Only when texture overflow is observed |
| — | Differentiable rendering | Dr.Jit / Jipole (literature) | BSD-3 | — | Horizon; no package |

## Coverage gaps / verify-before-port

- Manuka preprint PDF exceeded fetch limits — sensor-model details here come from the
  ACM record + secondary sources; skim the PDF §sensor before citing in the article.
- OTK `LICENSE.txt` and appleseed's MIT license asserted from README/search, not
  fetched raw — re-verify at port (appleseed is reference-only anyway).
- Exact file owning Cycles' `move_textures_to_host` (GPU-device base class) needs
  pinning when item 4 is implemented; `shared_alloc` in `device_impl.cpp` is verified.
- ART's GPL status is from project pages, not a LICENSE file; moot since it is
  literature-only for us.
- Jaroš et al. TOG 2021 details taken from abstract-level sources (ACM page 403'd);
  fetch the author preprint if item 7's design leans on it.

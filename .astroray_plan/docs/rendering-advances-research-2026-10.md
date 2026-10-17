# Rendering advances research sweep (2026-10-18)

**Method.** 14 angles. Sonnet 5.5 sweepers surfaced 173 candidate sources.
Haiku 5.5 deep-read 60 of them: 50 fetched, 10 not loaded (403, paywall, size
limit or deferred). Haiku extracted claims from each source. Sonnet 5.5 checked
30 claims with 3 independent voters each: **30 confirmed (all 3/3), 0 refuted**.
About 250 further extracted claims are **unverified** and are marked as such
below. Opus 5.5 wrote this synthesis. The 30-claim cap went to the first
sources in queue order, so voter-verified claims exist only for five angles:
path-guiding/ReSTIR, denoising and CUDA, plus Mitsuba 3.10-dev (competitor
engines) and the Cycles 5.2 no-change claim (Blender roadmap). Most fetches
went through a summarising model, so numbers must be rechecked in the paper
before they go into code or a gate. This is a CLAUDE.md §6 research record.
Licences still need checking against each repo's LICENSE file before any port.

Prior notes this one diffs against: `2026-07-pbr-advances-research.md`,
`2026-07-pbr-advances-research-pass2.md`, `2026-07-other-engines-research.md`,
`research-noise-2026-09-29.md`, `research-performance-2026-09-29.md`,
`comparison-renderers-2026-09-29.md`.

## Headline

| # | Development | Source, date | Status | Moves | Code / licence |
|---|---|---|---|---|---|
| 1 | **The 2026 ReSTIR PT cluster.** ReSTIR PT Enhanced (already in the 07 note, finding 8) is about 2-3x faster than ReSTIR PT. Its reciprocal neighbour selection halves spatial-reuse cost, footprint-based reconnection makes shifts more robust, duplication maps cut correlation, and DI and GI share reservoirs. New 2026 siblings: Stochastic Pairwise MIS (EG 2026), Gradient-domain ReSTIR (EG 2026, RTX 5090, 30 ms at 1080p), ReSTCV control variates (SIGGRAPH 2026 HM), Compatibility-Guided Neighbor Selection (HPG 2026 best paper, tie), Multi-Layer Reservoir Splatting and LoD ReSTIR (SIGGRAPH 2026). ReSTIR PG (SIGGRAPH Asia 2025) was already 07 finding 10. | [lin2026](https://research.nvidia.com/labs/rtr/publication/lin2026restirptenhanced/), I3D May 2026 (page badge, award not named); [cwyman.org](https://cwyman.org/paperList.html); [HPG awards](https://www.highperformancegraphics.org/2026/awards/) | 2-3x, halving and no-code claims confirmed 3/3. The 2-3x has no baseline, GPU or scene stated. The I3D best-paper award is unconfirmed. The rest is unverified. | GPU viewport noise-per-time (the 7-40x gap); builds on pkg20 (done) and supersedes the pkg137 framing | Enhanced: none. [ReSTCV](https://github.com/Hercier/ReSTCV): BSD-3 for "Daqi Lin's ReSTIR PT code" (README) + CC-BY-4.0 for other parts (LICENSE.md), Falcor/D3D12. SPMIS: zip, no licence. |
| 2 | **Cycles 5.2 LTS / 5.3 beta parity targets.** 5.2 (2026-07-14): negative SSS anisotropy (-1 to 1), Random Walk radius rescale (PR#133848, old files get "Random Walk (Legacy)"), Principled Thin Wall, texture cache, OptiX driver floor 575. 5.2 has no spectral, light-sampling or denoiser-algorithm changes (confirmed 3/3). 5.3 beta: anisotropic roughness for Glass and Principled transmission (#163343), a Principled "dispersion" item (#162041), a DLSS viewport denoiser (#153077), viewport paused during final render (#156536), GPU optimisations. | [5.2 Cycles](https://developer.blender.org/docs/release_notes/5.2/cycles/), [5.2 rendering](https://developer.blender.org/docs/release_notes/5.2/rendering/), [5.3 Cycles](https://developer.blender.org/docs/release_notes/5.3/cycles/) | One 5.2 claim confirmed 3/3. The 5.3 items and 5.3's release status are unverified. | Correctness and node coverage (pkg178/pkg253 Principled port); rough glass (pkg265) | Cycles `intern/cycles` Apache-2.0 per memory note `blender-sky-sources-apache-mit-not-gpl`; not verified this sweep (Blender pages state no code licence). Blender itself is GPL |
| 3 | **Mitsuba 3.10-dev: ray offsets and null surfaces.** Fixed 1500/15000-ULP offsets give way to per-intersection error bounds (`p_err`); the backends need about 1-8 ULP. Null-BSDF surfaces (null, mask, thindielectric) stop occluding shadow rays and attenuate them through `eval_null()` via `ray_test_tr`/`ray_intersect_tr`. | [release notes](https://mitsuba.readthedocs.io/en/latest/release_notes.html), dev branch, undated | Both confirmed 3/3. Correction: the shadow ray is attenuated, not passed freely. The "1-8 ULP" is what the backends need, not a measured bound. | Correctness: leaks, self-intersection, alpha-cut and thin-glass NEE, CPU/GPU parity | BSD-3 (verified in the 2026-07 note; PyPI says BSD) |
| 4 | **Real-time product path guiding, and OpenPGL governance.** RCPG uses world-space radiance cascades to sample radiance x BSDF with one sampler. Its PDF can be evaluated for any direction, so it composes with MIS and unbiased ReSTIR. It traces about 2x more paths per pixel than earlier real-time guiding with multi-sample MIS. OpenPGL joined the ASWF sandbox (2026-04-08). It is still pre-1.0 (v0.7.1) and is reported as used by Cycles, V-Ray, Karma and Hyperion (unverified). EGSR 2026 adds "Illumination-Aware Spatial Subdivision for Path Guiding" (Herholz co-author). | [RCPG](https://webpages.tuni.fi/vga/publications/RCPG.html), TOG 46(2), listed as 2027; [DP 2026-04-09](https://digitalproduction.com/2026/04/09/openpgl-joins-aswf/); [EGSR](https://egsr2026.inria.fr/programme/) | RCPG's 3 claims and OpenPGL pre-1.0 confirmed 3/3. Correction: the 2x is throughput, not variance. The user list is unverified. | pkg136 (paused) guiding re-plan; volume and caustic noise tails | RCPG: no code. OpenPGL: Apache-2.0 according to a secondary source only. |
| 5 | **QMC measurement and Owen scrambling.** Owen's RQMC survey (arXiv 2608.17143, 2026-08-17) gives the unbiased replicate variance S^2/R. Student's t intervals had 3 failures in 2400 cases, all at R=5; the bootstrap t had 81. Koksma-Hlawka bounds are loose in practice. Q-ART (C&G 139, Oct 2026) is a base-4 Owen scrambler with a roughly 1 KB LUT. EGSR 2026 has Werner/Hanika/Dachsbacher anisotropic sampling patterns. The Blender 5.2 manual says Blue-Noise "does not reduce overall noise". | [Owen](https://arxiv.org/pdf/2608.17143); [Q-ART](https://www.sciencedirect.com/science/article/abs/pii/S0097849326001524) (403); [manual](https://docs.blender.org/manual/en/latest/render/cycles/render_settings/sampling.html) | All unverified. Q-ART was not read. | pkg297 (QMC, open) and pkg307 (noise-per-time bench) gate statistics; pkg300 register budget | Method only. Q-ART code unknown. |
| 6 | **NanoVDB 13.1.0 (2026-09-16).** ReadAccessor now caches nodes at every requested level; `-DNANOVDB_USE_OLD_ACCESSOR=ON` restores the old behaviour. New `getDimAndActive()` returns step size and active state in one descent. New hostdev `isoCrossing`. `cuda::DeviceBuffer` is deprecated in favour of `cuda::Buffer`. | [OpenVDB changelog](https://www.openvdb.org/documentation/doxygen/changes.html) | Unverified. The changelog says nothing about majorants, so the DDA use is an inference. | pkg269 GPU NanoVDB stage, pkg296 mesh-bounded volumes: per-step cost of heterogeneous media | Apache-2.0 (per the 12.0.0 entry) |
| 7 | **Denoiser baselines shift.** Blender 5.3 plans an OptiX-layered DLSS viewport denoiser "in the fall"; as of 2026-06-03 it was planned, not shipped. The 5.3 notes (#153077) say only "NVIDIA DLSS viewport denoiser" and that it needs an unreleased driver; the "4.5 Ray Reconstruction" version comes only from secondary press. OIDN 2.5.0 adds external-semaphore import (CUDA on Windows and Linux; HIP on Windows). 2.5.1 fixes a leak on a failed shared-buffer import. 2.4.0 adds a CUDA 13 build and drops Volta. 2.3.3 added Blackwell. No OIDN 3, and no temporal input is documented. | [DP 2026-06-03](https://digitalproduction.com/2026/06/03/nvidia-brings-dlss-denoising-to-blender-5-3/); [OIDN releases](https://github.com/RenderKit/oidn/releases) | 10 claims confirmed 3/3. Correction: fast mode applies only to the RT filter without prefiltered aux; otherwise it falls back to balanced. The DLSS version and 5.3 release status are unconfirmed. | Viewport latency gate (p95 < 100 ms); a fair equal-time comparison against the Cycles viewport | OIDN Apache-2.0 (the weights submodule licence is unverified). DLSS proprietary: measure only. |
| 8 | **Astro: GPU line RT and GR polarisation.** Kratos-linerad (arXiv 2608.09340, Aug 2026) iterates level populations with escaping photons on the GPU. It handles PRD with constant-memory tables. Imaging takes two steps: an MC velocity-resolved emissivity pass, then deterministic ray-traced channel maps. KPolaris (2609.26298, 2026-09-22) does open-source GPU GR polarised RT on Kokkos, with fast and slow light, analytic or GRMHD input. Jipole sensitivities (ApJ 1004, 218) compute AD Jacobians of GRMHD images. | [Kratos](https://arxiv.org/abs/2608.09340), [KPolaris](https://arxiv.org/abs/2609.26298), [Jipole](https://arxiv.org/abs/2604.11869) | Unverified, abstracts only | pkg313 spectral data cube (open); Pillar 4 (paused); future Stokes output | No repo URLs found. Papers CC BY 4.0. |

## Per-angle findings

### 1. Path guiding and ReSTIR (13 sources)
- Confirmed 3/3: ReSTIR PT Enhanced is 2-3x faster than ReSTIR PT (already recorded in the 07 note, finding 8). The abstract gives no baseline, GPU or scenes, so it needs an Astroray benchmark.
- Confirmed 3/3: reciprocal neighbour selection halves the spatial-reuse cost. It is one part of the 2-3x, not a halving of the whole frame.
- Confirmed 3/3: the Enhanced page has no code. Correction from the voters: Lin's earlier ReSTIR PT code exists (the 07 note already pointed to github.com/DQLin/ReSTIR_PT, licence to be verified), and ReSTCV's LICENSE.md puts its base, "Daqi Lin's ReSTIR PT code", under BSD-3. Whether that base is DQLin/ReSTIR_PT verbatim is not shown. Only the new enhancements are paper-only.
- Confirmed 3/3: SPMIS draws reuse from many neighbours without bias. Standard spatial reuse degrades after disocclusion. The page gives no numbers.
- Confirmed 3/3: GD-ReSTIR splits the signed gradient target into positive and negative parts, and the paper has no code. Correction: this only matters if Astroray adds a difference estimator, since primal radiance is non-negative.
- Confirmed 3/3: ReSTCV stores an accumulated colour estimate per reservoir, and its repo reports no numbers.
- Confirmed 3/3, RCPG: it does product sampling, its PDF can be evaluated, and it traces about 2x more paths per pixel. Corrections: the "proportional" wording is not the paper's, the 2x is throughput, and the 2027 date is not confirmed.
- Confirmed 3/3: OpenPGL is pre-1.0 (v0.7.1). The GameFromScratch article gives no evidence about Cycles 5.2 guiding either way. The OpenPGL user list (Cycles, V-Ray, Karma, Hyperion) was not voted.
- Unverified: positivization takes the metal-rack MSE from 0.079 to 0.019 at 39.8 ms; edge-aligned reuse reaches 2.2e-4 MSE at 31.3 ms; OpenPGL's V-Ray example runs 50 min without guiding and 34 min with it (vendor figure); the LoD surface-point mapping; Ghost ReSTIR (ACM 403, no content read).
- Refuted: none.

### 2. Denoising and neural caching (11)
- Confirmed 3/3: OIDN 2.5.0 semaphore import, the 2.5.1 leak fix (only for `oidnNewSharedBufferFrom{FD,Win32Handle}` failure paths, so low priority), 2.3.3 Blackwell, and 2.4.0 CUDA 13 / Volta removal. Also: no OIDN 3 on the site or on GitHub, fast mode at about 1.5-2x (RT filter only), no documented temporal input, `cleanAux` (a hint that only helps when aux buffers are converged), and Apache-2.0 (canonical repo RenderKit/oidn).
- Confirmed 3/3: Blender 5.3 adds DLSS RR as an OptiX-layered option aimed at the viewport. It was planned, not shipped, as of 2026-06-03. No numbers are given.
- Unverified: Tom's Hardware's "35% more input, 20% more parameters" did not appear in the fetched text. Neural prefiltered specular caching (arXiv 2610.11702) was not fetched. Klepikov/Hanika/Dachsbacher's reliability-weighted NIRC (Jan 2026) is a snippet only.
- Refuted: none.

### 3. GPU RT hardware and APIs (12)
- Confirmed 3/3: CUDA 13.4 Update 2 is the latest toolkit and ships PTX ISA 9.4. Correction: CUDA 12.8 is PTX 8.7, and the JIT question depends on driver forward-compatibility, not only the ISA number.
- Unverified (CUDA notes): from 13.1 the Windows toolkit no longer bundles the driver. 13.x needs a driver of 580 or later, while 12.x needs 525 or later and below 580. 13.4 corresponds to R615.
- Unverified: OptiX 9.1 lists no cluster (CLAS) changes; those are 9.0. Vulkan deprecates DMM in favour of CLAS. OMM is unchanged since OptiX 7.6. No OptiX 9.2 was found.
- HPG 2026 (titles only): the merged-node BVH paper won best paper (tie). The opacity-micromap compression and animated-geometry papers are relevant to pkg299.

### 4. Spectral and dispersion (11)
- No 2025-26 paper was found on hero-wavelength sampling, spectral MIS, Jakob-Hanika successors or GPU spectral PT.
- Cycles 5.2 stays RGB (confirmed 3/3 under the Blender-roadmap angle, by absence). The claim says nothing about 5.3.
- Unverified: Cycles 5.3 lists Principled "dispersion" (#162041). Caveat: Cycles already had a Dispersion input on Glass and Principled from 4.2 (from memory, not re-fetched), and the Astroray addon already reads a dispersion input (`blender_addon/__init__.py`). Candidate 1's dispersion item is therefore weak until #162041 is read.
- Wave Tracing (Steinberg and Pharr, EG 2026, code at `ssteinberg/wave_tracer`) is a horizon item.

### 5. BSDFs and layered materials (15)
- All unverified.
- OpenPBR 1.1.1 (2026-04-17). Thin film is Belcour-Barla inside Fresnel, defaulting to 0.5 µm and IOR 1.4. Coat uses albedo scaling `f = f_coat + (1-E_coat) f_sub`. Emission is in nits, and the renderer converts it to radiance.
- MRM retroreflection (arXiv 2606.08739, JCGT 15(1)) reflects v about n before a standard microfacet eval. It is in OpenPBR and MaterialX, but was validated against only one measured sample.
- Dupuy (2609.20394) gives a closed form for a quadratic NDF, `f_r = (z_i+z_o)/(pi(1+w_i.w_o))`. It is **not GGX**, contrary to the sweep premise.
- Hybrid neural-microfacet (2608.09604, EGSR 2026): MERL MAE 0.0051 vs GGX 0.0099. It costs 2.94 ms with cooperative vectors against 1.10 ms for GGX at 1080p. It is RGB only, with no code.
- PureSample (SIGGRAPH 2026) learns a BSDF from microgeometry random walks using flow matching. Only the abstract was read.
- Not found: new Cycles hair, sheen or thin-film energy-compensation papers. The SIGGRAPH 2026 height-interdependent Smith multi-bounce paper had no URL.

### 6. Volumes (12)
- All unverified.
- NanoVDB 13.1: see headline 6.
- Blender 5.2 has no volume items. Cycles 5.0 made null scattering the default (sweeper note).
- arXiv 2607.28047 runs delta tracking with RT-core traversal and tensor-core INR queries at 30-40 FPS at 1024² on an RTX 4090. Not transferable.
- 2607.13695 is inverse rendering only.
- Not found: 2026 papers on spectral tracking, firefly control or volume guiding.

### 7. Blender / Cycles roadmap (9)
- See headline 2. Confirmed 3/3: Cycles 5.2 has no spectral, light-sampling or denoiser-algorithm changes.
- Unverified: EEVEE 5.2 may render darker than 5.1 because of energy-conservation fixes, and its Mix node and light passes now match Cycles. In-flight work (2026-09-07 meeting): Cycles anisotropic glass (Weizhen Huang), quaternion and spherical-harmonics attributes (Sharybin), EEVEE Material Lighting Nodes. No light-tree or MULTI_GGX changes in 5.0-5.3.

### 8. Sampling and QMC (12)
- See headline 5. All unverified.
- Blender 5.2 manual: Classic means precomputed Owen-scrambled Sobol tables. Automatic means Blue-Noise plus a first-sample viewport tweak. The time limit counts render time only. Tabulated Sobol, Sobol-Burley and Z-sampler do not appear in the fetched text.
- The blue-noise ReSTIR dithering paper (TVCG, Shi and Xu) returned an empty page.

### 9. Light sampling (14)
- The only in-window primary source is ReSTIR PT Enhanced.
- Unverified: EGSR 2026 "One-more-vertex NEE with Hierarchical Geometry Sampling" and "Guided ReSTIR FG+: Photon Resampling for Large Scenes and Many Lights".
- Blender 5.2 Sky node: Single Scattering, Preetham and Hosek/Wilkie are marked legacy; Multiple Scattering is the only non-legacy type, and Single Scattering is described as an improved Nishita 1993. Sun Disc is Cycles only. The page says nothing on sun-disc sampling. The sweep premise about a 2D importance map is not supported. With research-noise's sky_sun bias ratio of 190 (M6 parity defect), the parity target is Multiple Scattering, not Nishita.
- Blender 5.2 adds world "Cast Shadows" options (voters flagged as lighting-related; unverified).
- Not found: env-map or sun-sky sampling, light-tree or LTC papers from 2025-26.

### 10. Caustics (11)
- All unverified.
- Photon-NRC (I3D Companion 2026) was developed on an **RTX 5070 Ti**. It uses hardware-BVH photon gather with reservoirs, plus tiny-cuda-nn NRC, on Falcor. The LICENSE type was not read.
- Neural Progressive Photon Mapping (EG 2026) and Batch SMS (June 2025) are from snippets only.
- Caustica, a commercial photon-caustics build of Blender 5.2, was not fetched.
- No 2026 path-space regularisation or MNEE paper was found.

### 11. Astro, GR and scivis (14)
- See headline 8. All unverified.
- TARTARUS (2609.08989) is a Numba geodesic integrator (RK, Bulirsch-Stoer, Verlet) with Kerr/NT test cases. No numbers or code.
- `samrht/blackhole-sim` (WebGPU, no licence) switched on 2026-10-08 to Carter equations in Mino time with DP5(4) at tol 1e-5, cutting frame time 25-30% on an RTX 3050 Laptop. It checks CPU/GPU parity with per-case tolerances and bit-exact golden hashes.
- Gap: no 2025-26 GPU data-cube volume rendering.

### 12. Competitor engines (12)
- Confirmed 3/3: Mitsuba 3.10-dev `p_err` and null-BSDF shadow rays (headline 3). The rest is unverified.
- Mitsuba: 3.9.1 (2026-08-07); 3.9.0 added Metal and 8-bit texture-unit fetch; 3.10-dev adds BC4/5/7.
- Oracle-affecting Mitsuba changes (pkg307's oracle; 3.9.1 is installed): 3.9.1 pads environment maps to a minimum size, makes `dr.minimum`/`dr.maximum` propagate NaNs, and (sweep note) removed ray differentials. 3.9.0 keeps 8-bit textures in 8-bit with sRGB decoding in texture units, and makes them non-differentiable. Any of these can move texture and env-map oracle results.
- MoonRay became ASWF-hosted on 2026-05-19. v2026.29.x adds only MaterialX Map shaders, with no BSDF/EDF/VDF, under Apache-2.0.
- Arnold 7.5.0 (2026-03-25) unified the CPU and GPU Gaussian filter (ARNOLD-17059).
- No 2026 notes were found for Karma, V-Ray, Corona, Octane or Redshift.

### 13. Conference lists (13)
- All unverified.
- SIGGRAPH 2026 awards (2026-05-19): best paper Walk on Decomposed Subdomains (PDE); honourable mentions for ReSTCV and gradient-domain MC-PDE reconstruction; test of time for Kalantari 2015.
- EGSR 2026 (1-3 July): guiding, Guided ReSTIR FG+, one-more-vertex NEE, anisotropic patterns, and Correlated Smith Visibility (MAM-MANER workshop).
- I3D 2026: 16 of 41 accepted. Titles not retrieved.
- The full SIGGRAPH 2026 TOC returned 403.

### 14. Neural materials (14)
- All unverified.
- RTXNTC v0.10.0 beta adds OptiX inference. Its D3D12 LinAlg path is "do not ship". The example set is 2.5 MB NTC against 12 MB BCn. Cooperative vectors are claimed 2-4x on Ada/Blackwell. The licence is proprietary.
- Verdict: neural materials and textures are a long-term option. They do not relieve register pressure (pkg300) or rough-glass energy.

## What is new since the 2026-07 and 2026-09 sweeps

| Topic | Prior note said | New in this sweep |
|---|---|---|
| ReSTIR | 07: ReSTIR PT/GRIS roadmap; ReSTIR PT Enhanced 2-3x (finding 8); ReSTIR PG (finding 10); DQLin/ReSTIR_PT code (licence to verify); PSMS-ReSTIR; RTXDI disqualified | Six further 2026 ReSTIR papers (headline 1); one is an HPG best paper (tie). A licence finding for known code: ReSTCV's LICENSE.md puts its Lin ReSTIR PT base under BSD-3. |
| Path guiding | 07: SVO wavefront guiding (finding 7); OpenPGL CPU-oriented (finding 9); 09 noise: pkg136 Stage 1 ~1.3x | RCPG real-time product guiding on GPU; OpenPGL ASWF sandbox; EGSR 2026 subdivision paper. Still no primary evidence of GPU guiding in OpenPGL or Cycles. |
| Microfacet energy | 07-pass2: Turquin albedo scaling via adobe/openpbr-bsdf | OpenPBR bumped to 1.1.1, MRM retroreflection, Dupuy microflake closed form. Nothing displaces Turquin (pkg265 Heitz MS dielectric already landed). |
| Sampling | 09 noise: hero-λ stratification ~75x; pkg297/305; blue noise acquitted; pkg307 5 seeds x 64 spp | The 5.2 manual's own text confirms the blue-noise acquittal. New: the RQMC replicate-variance protocol, Q-ART, EGSR anisotropic patterns. |
| GPU stack | 09 perf: OptiX HW traversal (pkg299), shade REG 254 (pkg300), cooperative vectors, CUDA 13.x ptxas (row 6, rebuild trial approved) | CUDA 13.4 U2 / driver floor 580 / unbundled driver; Cycles OptiX floor 575; HPG merged-node BVH and OMM compression papers |
| Volumes | pkg267/268/269 NanoVDB + majorant DDA (done) | NanoVDB 13.1 accessor fix and `getDimAndActive`; Ghost ReSTIR (poster, unread) |
| Denoising | 07 engines: OIDN mentioned only | OIDN 2.4-2.5.1 details; a DLSS viewport denoiser planned for Cycles 5.3 |
| Cycles parity | Earlier Cycles 4.x/5.1 behaviour | 5.2 SSS anisotropy sign and Random Walk radius rescale; Sky: Multiple Scattering is the only non-legacy type; 5.3 anisotropic rough glass and DLSS |
| Comparison engines | 09: Mitsuba 3.9.1 first, pbrt-v4 second | Mitsuba 3.9.x texture/env-map/NaN changes and 3.10-dev `p_err` and null-transmittance semantics, which can move the oracle. MoonRay is now an Apache-2.0 ASWF engine, but has no MaterialX BSDFs. Arnold 7.5 single CPU/GPU Gaussian filter. |
| Astro | 07 engines: Jipole 2509.07065 | Jipole sensitivities (ApJ 2026), KPolaris, Kratos-linerad, TARTARUS |

## Candidate packages

Ordered by expected value: correctness and fidelity first, then viewport
performance, then noise per time, then astro. Sizes: S < 1 lane-day, M a few
days, L multi-batch. Nothing here is filed yet. Each new package needs a spec
through `file-followup` and must pass `project_index.py lint`; items marked
"amend" go into an existing spec instead.

| # | Name | Technique + citation | Serves | Prerequisite | Size | Licence risk |
|---|---|---|---|---|---|---|
| 1 | Cycles 5.2/5.3 BSDF-input and world parity audit | Negative SSS anisotropy in [-1,1]; Random Walk radius rescale (PR#133848) and the Legacy mode; Glass/Principled transmission anisotropy (#163343); what #162041 changes for dispersion (weak premise until read); Thin Wall semantics (the addon and `material_closure.h` already have it); Sky Texture parity against Multiple Scattering (not Nishita; sky_sun bias ratio 190, research-noise M6) and the Cycles-only Sun Disc; 5.2 world "Cast Shadows" options | Correctness, node coverage | Read the PRs; Blender 5.2/5.3 local install | S | Low (Cycles Apache-2.0 per memory, unverified here; read the Blender-side code only) |
| 2 | Ray-offset error bounds | Per-intersection rounding-error bounds (Mitsuba 3.10-dev `p_err`; pbrt-v4 error-bound offsets), replacing fixed epsilons on CPU and GPU | Correctness (leaks, self-hits, small or large scale), CPU/GPU parity | Inventory current epsilons; coordinate with pkg299 OptiX traversal | M | Low (BSD-3; pbrt-v4 Apache-2.0 per the 07 note) |
| 3 | Null/transparent shadow-ray transmittance audit | Mitsuba 3.10 `ray_test_tr`: attenuate NEE through null, alpha and thin-dielectric surfaces | Correctness (foliage, thin glass), NEE parity with Cycles | Read current CPU/GPU behaviour first; the package may close as "already correct" | S | Low |
| 4 | Amend pkg307 statistics (RQMC replicate variance) | Owen 2026 (arXiv 2608.17143): S^2/R over R ≥ 10 independent scrambles, Student's t intervals, replacing the "each engine's own seed scatter" / 5-seed design; also pin the Mitsuba version given the 3.9.x texture and env-map changes | Noise measurement for pkg297 and pkg307 | pkg307 spec | S (amend) | None (method) |
| 5 | Viewport denoise baseline at p95 | OIDN 2.5.x fast mode (RT filter, no prefilter) + `cleanAux` on Astroray's viewport, against the Cycles 5.3 DLSS viewport denoiser once it ships | Viewport latency gate | Blender 5.3 release + the DLSS driver (both unconfirmed); build OIDN 2.5.1 or later | S | Low (OIDN Apache-2.0; DLSS measured only) |
| 6 | NanoVDB 13.1 bump + one-descent DDA step | ReadAccessor caching fix; `getDimAndActive()` for the majorant marcher; A/B against `NANOVDB_USE_OLD_ACCESSOR` | Volume speed (pkg269/pkg296) | GPU lock; min-of-N timing (clock-drift note) | S-M | Low (Apache-2.0) |
| 7 | Owen-scramble kernel choice for pkg297 GPU | Burley hash vs Q-ART base-4 LUT (C&G 139, 2026): registers and quality | Noise; pkg300 register budget | Get the Q-ART paper (ScienceDirect returned 403) | S spike | Unknown (Q-ART code) |
| 8 | Amend pkg300 Phase 0 (CUDA 13.x inputs) | Fold into research-performance row 6 (owner: CUDA 13 rebuild trial approved). New inputs only: driver floor 580, no bundled driver on Windows (13.1+), PTX 9.4, OIDN 2.4+ CUDA 13 build, OptiX 9.1 compatibility | Speed and toolchain | Do not overlap a CUDA build | S (amend) | None |
| 9 | Amend pkg55 Phase C: ReSTIR PT, viewport only (flagged) | Repeats 07 finding 8. ReSTIR PT Enhanced + Compatibility-Guided or SPMIS neighbours; reads Lin's ReSTIR PT via ReSTCV (BSD-3). Viewport only: research-performance rejects offline ReSTIR PT (no equal-time offline evidence) and research-noise row 10 says viewport only; nothing in this sweep changes that | Viewport noise per time | pkg297 stratification, pkg299 traversal, pkg300 register headroom; pkg20 core | L | Medium (BSD-3 base; enhancements clean-room; SPMIS zip has no licence, so read only) |
| 10 | Guiding re-plan input for pkg136 | The 07 note's choice (finding 7 SVO wavefront guiding on GPU vs finding 9 OpenPGL, CPU-oriented), research-noise row 7 and bet B5 stand, with pkg136 Stage 1 measured at ~1.3x. RCPG (TOG 2027) is the only new GPU option to weigh | Noise tails (caustics, media) | RCPG paper text; OpenPGL LICENSE check | S (amend) | Low/unknown |
| 11 | Volumetric resampling research spike | Ghost ReSTIR (SIGGRAPH 2026 poster) + volume guiding literature, for the pkg306 media tail | Volume fireflies | Get the poster abstract (ACM 403) | S | Unknown |
| 12 | Line-RT channel-map imaging design for pkg313 | Kratos-linerad two-step: cached MC emissivity, then deterministic channel maps | Spectral/astro data cubes | pkg313 Phase 1 lands; Pillar 4 pause lifted for this item | M | Low (method; no code) |
| 13 | GR polarised-transfer oracle scoping | Find the KPolaris repo and licence; define a Stokes cross-check scene; Jipole sensitivity as a future differentiable target | Astro (GR) | pkg67 / Kerr stack | S | Unknown |
| 14 | MRM retroreflective lobe | Reflect v about n before the microfacet eval (JCGT 2026; OpenPBR/MaterialX) | Node coverage only if Blender exposes it; it does not today | An OpenPBR mapping decision (Blender #156437, unread) | S | None (method) |
| 15 | Pixel-filter CPU/GPU parity check | Arnold 7.5.0 single CPU/GPU Gaussian filter (ARNOLD-17059) as precedent; ties to research-noise §4 item 4 (rejection-based Blackman-Harris/Gaussian filter draws) and CPU-as-oracle parity | Correctness, CPU/GPU parity | Read current CPU and GPU filter code | S | None |

Not proposed: neural BRDFs, NTC or PureSample (they add compute to a
register-saturated shade kernel, and RTXNTC is proprietary), gradient-domain
ReSTIR (offline use is open future work), and LoD ReSTIR (no LoD in Astroray).

## Licence table

| Source with code | Repo | Licence | Portable into Apache-2.0-compatible code? |
|---|---|---|---|
| ReSTCV | github.com/Hercier/ReSTCV | BSD-3 for its base ("Daqi Lin's ReSTIR PT code" per README; not shown to be DQLin/ReSTIR_PT verbatim) + CC-BY-4.0 for other parts, per LICENSE.md | Yes, with attribution. Falcor/D3D12, so ideas only, not code. |
| Stochastic Pairwise MIS | NVIDIA project zip | Not stated | No. Read-only until a licence is found. |
| Gradient-domain ReSTIR | github.com/elite-sheep/gradient-restir | Not stated | No. Read-only. |
| Falcor | github.com/NVIDIAGameWorks/Falcor | Not checked this sweep | Check before use |
| Wave Tracing | github.com/ssteinberg/wave_tracer | Not checked | Check before use |
| PSMS-ReSTIR (07 sweep) | github.com/Utah-Graphics-Lab/PSMS-ReSTIR | Falcor BSD-3 (verify the module) | Yes, if verified |
| OpenPGL | github.com/OpenPathGuidingLibrary/openpgl | Apache-2.0 (secondary source only) | Yes, after a LICENSE check |
| OIDN | github.com/RenderKit/oidn | Apache-2.0; oidn-weights submodule unverified | Yes; check the weights and third-party notices |
| DLSS / NGX | proprietary SDK | NVIDIA proprietary | No. Measure only. |
| RTXNTC | github.com/NVIDIA-RTX/RTXNTC | NVIDIA RTX SDK licence (proprietary; forbids open-source subjection) | No |
| Mitsuba 3 / Dr.Jit | github.com/mitsuba-renderer/mitsuba3 | BSD-3 (verified 2026-07; PyPI says BSD) | Yes |
| pbrt-v4 | github.com/mmp/pbrt-v4 | Apache-2.0 per the 07 note; not rechecked this sweep | Yes, after a recheck |
| OpenVDB / NanoVDB | github.com/AcademySoftwareFoundation/openvdb | Apache-2.0 (per the 12.0.0 changelog) | Yes |
| OpenPBR spec | github.com/AcademySoftwareFoundation/OpenPBR | This sweep's fetch found no licence; Apache-2.0 per the 07 note only | Yes, if confirmed |
| adobe/openpbr-bsdf (07) | github.com/adobe/openpbr-bsdf | Apache-2.0 (verified 2026-07) | Yes |
| MoonRay | github.com/dreamworksanimation/openmoonray | Apache-2.0 | Yes |
| MoonRay MaterialX shaders | github.com/OpenMoonRay/materialx_shaders | Not confirmed | Check |
| Photon-NRC | github.com/julcst/photon-nrc | LICENSE.md present, type unread; depends on tiny-cuda-nn (licence unverified) | Check; read-only meanwhile |
| Cycles | projects.blender.org/blender/blender (`intern/cycles`) | Apache-2.0 for Cycles per memory note `blender-sky-sources-apache-mit-not-gpl`, not verified this sweep (Blender pages: code licence not stated; docs CC-BY-SA); Blender GPL (`sky_nishita.h` GPL) | Cycles files yes, per file, after a check; Blender GPL files no (read-only) |
| blackhole-sim | github.com/samrht/blackhole-sim | No LICENSE (all rights reserved) | No. Read-only. |
| Arnold USD | Autodesk arnold-usd | Not checked; Arnold core commercial | Core no |
| KPolaris, Kratos-linerad, TARTARUS, Jipole, Dupuy, MRM, hybrid neural BRDF, PureSample, RCPG, ReSTIR PT Enhanced | none found | Papers CC BY 4.0 or arXiv non-exclusive | Clean-room from the paper, with citation |

## Not covered / limitations

- **Verification cap.** The 30 voter-verified claims come from 5 angles: guiding/ReSTIR, denoising and CUDA, plus the Mitsuba 3.10-dev pair (competitor engines) and the Cycles 5.2 no-change claim (Blender roadmap). All other claims in angles 4-14 are unverified. The sweeper's "refuted" count of 0 says nothing about them.
- **Not fetched (10):** ACM ReSTIR PT Enhanced DOI (Crossref has the abstract), Ghost ReSTIR, the SIGGRAPH 2026 proceedings TOC, Q-ART, TVCG blue-noise ReSTIR, Blender #156437, Tom's Hardware DLSS, arXiv 2610.11702, Caustica, and the PureSample PDF (abstract only). Several NVIDIA PDFs exceeded the 10 MB fetch limit, so no tables were read for SPMIS, LoD ReSTIR or Multi-Layer ReSTIR.
- **Thin angles:** spectral/dispersion (no new papers found), light sampling (one in-window source), volumes (no 2026 firefly or volume-guiding papers), astro data-cube rendering (nothing after 2017), competitor release notes (Karma, V-Ray, Octane, Redshift missing), I3D 2026 titles, Blackwell RT whitepaper, OptiX 9.1 forum (403). Nothing gathered on neural supersampling (XeSS/FSR), RTXDI/RTXPT dates or NVIDIA STBN. pbrt-v4's 2026 changes and commit log were not checked, though it is the second oracle. Only 100k of 273k characters of the SIGGRAPH Asia 2025 list were read, so hair and caustics entries may be missing. The PSMS-ReSTIR project page was fetched but not used. No 2026 release notes for ipole, GYOTO or RAPTOR, and no OptiX/wavefront GR paper. No 2026 paper on calibrating against photographs.
- **Dates.** OIDN and RTXNTC release pages show day and month without a year. The OpenPGL releases page shows no years, so "v0.7.1 current" rests only on the April article. RCPG is listed as 2027. The Blender 5.3 date and release status are inferred. Dr.Jit dates conflict (Zenodo August vs the docs' June 26).
- **Summariser risk.** Most fetches went through a summarising model, so quoted numbers are paraphrase-level. Recheck them before citing in code or gates. The volumes sweeper reported that search summaries wrongly attributed 2026 papers to unrelated ACM URLs, so treat any ACM URL-to-title pairing here as unconfirmed.
- **Not looked up / dropped leads:** the SIGGRAPH 2026 "Height-Interdependent Path Formulation of Multiple Bounces in Smith Microfacet BRDFs", Xi and Iwasaki's area-light moments (SIGGRAPH Asia 2025), ReSTIR PG PDF details, Radiance Caching for Differentiable Path Tracing (TOG 45:4, July 2026), Locality-aware Online Radiance Caching (CGF, August 2026), Xia et al. spectral reconstruction (SIGGRAPH Asia 2025), and arXiv 2608.16730 (per-pixel difficulty by transport mechanism).

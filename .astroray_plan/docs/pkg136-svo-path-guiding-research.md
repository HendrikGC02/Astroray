# pkg136 — SVO path-guiding research note (web-verified)

Source package: `.astroray_plan/packages/pkg136-svo-wavefront-path-guiding.md`.
Purpose: Phase-0 fact base for a follow-up spec writer. Every citation below was
verified by live web search + fetch on 2026-09-03; the source URL is inline.
Nothing here is written from memory.

---

## 1. Canonical papers (titles / authors / venue / DOI — all verified)

### 1a. Müller, Gross, Novák 2017 — "Practical Path Guiding" (SD-tree)
- **Title:** "Practical Path Guiding for Efficient Light-Transport Simulation"
- **Authors:** Thomas Müller (ETH Zürich / Disney Research), Markus Gross (ETH Zürich / Disney Research), Jan Novák (Disney Research)
- **Venue:** Proceedings of the Eurographics Symposium on Rendering (EGSR) 2017, Helsinki; Computer Graphics Forum, vol. 36, no. 4, pp. 91–100
- **DOI:** 10.1111/cgf.13227
- **Sources:** https://cgl.ethz.ch/publications/papers/paperMue17a.php ; https://dl.acm.org/doi/10.1111/cgf.13227 ; https://onlinelibrary.wiley.com/doi/10.1111/cgf.13227
- **Structure confirmed from the abstract (Wiley + ETH pages):** SD-tree = upper binary tree partitioning 3D spatial domain + lower quadtree partitioning 2D directional domain; "adaptive spatio-directional hybrid data structure." Training is iterated reinforcement-learning style, with an automatic budget split between training and rendering. Fully unidirectional, unbiased.

### 1b. Müller 2019 — "Practical Path Guiding in Production" (improvements)
- **IMPORTANT correction to the spec:** there is no 2019 *journal paper* by Müller. The "2019 improvements" are **chapter 10 of the SIGGRAPH 2019 course "Path Guiding in Production"**. The chapter title is «"Practical Path Guiding" in Production».
- **Course authors:** Jiří Vorba, Johannes Hanika, Sebastian Herholz, Thomas Müller, Jaroslav Křivánek, Alexander Keller
- **Venue:** ACM SIGGRAPH 2019 Courses, Article 18, pp. 1–77
- **Course DOI:** 10.1145/3305366.3328091
- **Sources:** https://dl.acm.org/doi/10.1145/3305366.3328091 ; course page https://cgg.mff.cuni.cz/~jirka/path-guiding-in-production/2019/index.htm ; chapter slides https://cgg.mff.cuni.cz/~jirka/path-guiding-in-production/2019/presentations/Guiding_In_Production_Course_s2019-2019-08-07-ppg-in-production.pdf
- **The three improvements (verified from the course abstract + the practical-path-guiding README, see §5):**
  1. inverse-variance-weighted sample combination (discard fewer samples),
  2. spatio-directional filtering / filtered SD-tree splatting (robustness vs high-frequency illumination),
  3. on-line learning of the BSDF:guiding sampling ratio via gradient descent, based on Neural Importance Sampling (Müller, McWilliams, Rousselle, Gross, Novák, "Neural Importance Sampling", ACM ToG 38(5), 2019; DOI 10.1145/3341156 — cited in the course abstract as arXiv:1808.03856).

### 1c. Vorba et al. 2014 — online parametric mixtures
- **Title:** "On-line Learning of Parametric Mixture Models for Light Transport Simulation"
- **Authors:** Jiří Vorba, Ondřej Karlík, Martin Šik (Charles University in Prague); Tobias Ritschel (MPI Informatik, Saarbrücken); Jaroslav Křivánek (Charles University in Prague)
- **Venue:** ACM Transactions on Graphics 33(4) (Proceedings of SIGGRAPH 2014), Article 101, 101:1–101:11
- **DOI:** 10.1145/2601097.2601203
- **Sources:** https://dl.acm.org/doi/10.1145/2601097.2601203 ; author page http://cgg.mff.cuni.cz/~jirka/papers/2014/olpm/index.htm
- **Method (verified from the ACM abstract + author page):** represents the directional sampling distribution as a parametric mixture model (von Mises–Fisher / Gaussian mixtures) trained *on-line* via stepwise EM from an unbounded stream of particles; guides both scattering directions and light emission; enables guided BDPT. Source zip: http://cgg.mff.cuni.cz/~jirka/papers/2014/olpm/olpm2014_source.zip (license NOT stated on the page — see §5).

### 1d. Yalçıner & Akyüz 2024 — the pkg136 target method
- **Title correction to the spec:** the actual journal title is **"Path Guiding for Wavefront Path Tracing: A Memory Efficient Approach for GPU Path Tracers"** (not "SVO-based wavefront path guiding"). "SVO-based wavefront path guiding" is a description, not the paper title.
- **Authors:** Bora Yalçıner, Ahmet Oğuz Akyüz (Middle East Technical University, Computer Engineering Department, Ankara)
- **Venue:** Computers & Graphics, Volume 121 (June 2024), Article 103945
- **DOI (journal):** 10.1016/j.cag.2024.103945
- **arXiv:** arXiv:2405.06997 (v1, submitted 11 May 2024), paper licensed CC BY 4.0 (stated on the arXiv HTML version)
- **Sources:** https://www.sciencedirect.com/science/article/abs/pii/S0097849324000803 ; https://arxiv.org/abs/2405.06997 ; https://arxiv.org/html/2405.06997v1 ; https://dl.acm.org/doi/10.1016/j.cag.2024.103945
- **Method facts verified from the arXiv full text:** a single global sparse voxel octree stores **directionless radiant exitance**; guiding PDF/CDFs are generated **on the fly** via cone-trace queries (hardware-accelerated, OptiX); no persistent per-region directional storage. SVO built via Crassin-style voxelization + Karras Morton-code hierarchy; each SVO node stores two dominant surface normals (k-means, k=2) with separate exitance per normal.

---

## 2. Guiding-structure options: SD-tree vs spatial octree (SVO) + per-leaf directional quadtree

- **SD-tree (PPG, Müller 2017):** a 3D binary spatial tree over the light field + a 2D directional **quadtree** per spatial leaf. Chosen over kd-trees and Gaussian mixtures for straightforward hierarchical sample warping (McCool & Harwood) and robust progressive reinforcement learning. Verified from the ETH/Wiley abstract and the paper PDF (https://studios.disneyresearch.com/wp-content/uploads/2019/03/Practical-Path-Guiding-for-Efficient-Light-Transport-Simulation.pdf).
- **Online parametric mixture (Vorba 2014):** spatial cache of directional GMM/vMF mixtures, progressive stepwise-EM; memory stays bounded because particles need not be retained. Contrasted in Müller 2017 §3 (the SD-tree paper explicitly motivates the binary/quadtree split against GMMs [VKv*14] and kd-trees).
- **Why an SVO specifically (pkg136 target):** the Yalçıner & Akyüz motivation (arXiv full text, §1/§3.2) is *memory*: a directionless scalar (radiant exitance) per voxel is far cheaper than per-region directional distributions, and an octree with Morton-code sorting (Karras) avoids GPU-hostile dynamic memory management ("does not rely on dynamic memory management – an operation that does not suit the GPU architecture"). The spec's headline "~3.96 MiB vs PPG SD-tree 19→37 MiB" is confirmed by **Table 3 of the paper** for the *Sponza* scene (SVO=128³): Ours=3.96 MiB vs Müller et al. SD-tree 19.0 / 26.0 / 37.0 MiB at 16/32/64 training SPP, and Ruppert et al. 3.2 / 5.5 / 20.1 MiB. VeachDoor: 1.26 MiB ours; Bathroom: 2.00 MiB ours.
- **Memory behaviour:** SVO memory is fixed per scene (does not grow with training time), unlike SD-tree/vMF structures which refine and grow. Local radiance fields are *transient* — held in shared memory (max 128×128 ≈ 64 KiB) and released each bounce; only the SVO is persistent. Verified from the arXiv full text §5.3 / Table 3.

---

## 3. Learn-then-sample vs progressive online; MIS combination; bias/variance

- **Vorba 2014 = progressive on-line:** distributions trained from an unbounded particle stream during rendering; guided sampling improves with training passes (their Fig. 1 shows 2/5/30 training passes amortizing quickly). Verified from author page.
- **Müller 2017 = iterative learn-then-sample (reinforcement):** alternate training passes (building SD-tree from samples drawn from the *previous* distribution) with rendering passes; automatically budgets how much time to train vs render to minimize final variance. Verified from the ETH/Wiley abstract.
- **Yalçıner & Akyüz = progressive on-line, on a fixed SVO:** radiant exitance accumulated as paths reach emitters ("UpdateExitance"), then backpropagated along the path; guiding PDFs regenerated each bounce. They add a **sample-combination heuristic** (Eq. 7) that weights early (poorly-trained) samples down; their best variant is **"PT First"** (first sample is pure path-tracing, rest guided). Verified from the arXiv full text §3.7.
- **MIS combination:** all three combine guided sampling with BSDF (and, in the SVO paper, NEE) via multiple importance sampling; Yalçıner & Akyüz additionally offer **product path guiding** (guided field × BSDF) using a two-level hierarchical scheme adapted from Estevez et al. (8×8 BSDF layer over a 128×128 radiance field, warp-per-ray). Verified from the arXiv full text §3.5–3.6.
- **Bias/variance:** the guiding distributions are all treated as unbiased importance densities; Yalçıner & Akyüz floor the radiance field at ε=10⁻² to keep the PDF non-zero where the field is non-zero (unbiasedness constraint), and Gaussian-blur + jitter to kill variance seams. Unbiasedness validated empirically (their Fig. 8, ΔE vs a 150k-sample reference). Verified from the arXiv full text §4/§5.2.

---

## 4. Astroray integration (grounded in the current CUDA wavefront)

Code inspected (not from memory): `src/gpu/wavefront/stage_advance.cu`.

- **Where guided sampling would replace/augment BSDF sampling:** the shade stage is `stageShadeBucketedKernel` (line ~2072), a heavily `if constexpr`-templated kernel (Principled/Textured/Phong/Dispersive × light-pass-AOV flags). The continuation-direction draw happens at `gpu_material_sample_spectral<HasPrincipled>(...)` (line 1601) followed by the next-direction write at lines 1730–1738. NEE is `sampleDirectSpectralMW`. Guided sampling would sit exactly at the line-1601 call site: cone-trace the SVO in shared memory to build a marginal/conditional CDF, sample it, and MIS-combine the guiding PDF with `bss.pdf`.
- **REG:254 shade budget is a hard blocker in the naive placement.** The shade kernel is register-pinned to **REG 254 / STACK ~3352 / CONSTANT[0] 1700** (comments at lines 358, 388, 560, 683, 862, 971; "REGISTER PROBE (PR #620)"; "byte-identical 254/3352/1700"). There is an explicit rule in the file: *"leave the REG:254-saturated shade kernel byte-identical"* — new live state has repeatedly been pushed into the intersect/regen kernels (e.g. the pass-AOV `firstCat` write, line 560–686; shadow/volume/regen code reads behind `passAccum != nullptr`). A cone-trace + 2D PDF/CDF + MIS write will NOT fit in the 254-reg fleet kernel. The spec's "cone-trace inside `stage_advance.cu`" must be reconciled with this — the SVO query + on-the-fly PDF/CDF synthesis is exactly the kind of register-heavy work the file has deliberately kept *out* of the shade stage.
- **GPU SVO-update atomics cost:** the paper's `UpdateExitance(SVO)` is an atomic accumulation into leaf voxels (their Algorithm 1/2 use `AtomicAdd` on leaf node counters). In Astroray this is a scatter of path-exitance contributions across a global octree — cross-warp atomic contention that scales with path count. The paper's profiling (Table 1) shows "Update Exitance" ≈ 4–6.5 ms per sample at 1080p on a 3070 Ti Mobile, and total guiding ≈ 2× pure path-tracing cost (74 ms → ~180 ms for Sponza). That 2× overhead is the price to budget for.
- **CPU-first?** pkg136 is Track A: "SVO build + cone-trace PDF query is CPU-verifiable; the wavefront guiding leg verified on RTX." The cone-trace query + PDF/CDF synthesis is a pure-CUDA/CPU function independent of the RTX BVH (the paper uses OptiX for cone tracing, but Astroray has its own CUDA BVH — the query can be implemented against that BVH, or even CPU-first for the SVO-build/PDF-query gate before the wavefront wiring). The SVO build/update is also CPU-verifiable (voxelize + Morton sort + backprop), so a CPU-first milestone of "build SVO, cone-trace to produce a PDF, MIS-sample" is the natural de-risking path that sidesteps the REG:254 problem until the wavefront integration is designed.

---

## 5. License-compatible reference implementations + risks

### Reference implementations (license verified where stated)
- **practical-path-guiding (author code for Müller 2017 + 2019 improvements):** https://github.com/Tom94/practical-path-guiding — **GPL-3.0** (README + LICENSE). **INCOMPATIBLE** with CLAUDE.md §6 (Apache/BSD/MIT/MPL). It is a Mitsuba integrator + nanogui visualizer; usable as an *algorithmic* reference only, not a port source.
- **OpenPGL (Intel):** https://github.com/OpenPathGuidingLibrary/openpgl (mirror https://github.com/RenderKit/openpgl) — **Apache-2.0** (LICENSE.txt). CPU-oriented (SSE/AVX2/AVX-512); design reference for surface (incident radiance × BSDF cosine lobe) and volume (× single-lobe HG) guiding. Confirmed license + CPU orientation from the repo README and the ASWF TAC filing (https://github.com/AcademySoftwareFoundation/tac/issues/1218).
- **robust-vmm-guiding (Ruppert, Herholz, Lensch, SIGGRAPH 2020, "Robust Fitting of Parallax-Aware Mixtures for Path Guiding", DOI 10.1145/3386569.3392421):** https://github.com/cgtuebingen/robust-vmm-guiding — **GPL-3.0**. Reference only.
- **Vorba 2014 source zip:** http://cgg.mff.cuni.cz/~jirka/papers/2014/olpm/olpm2014_source.zip — **no license stated on the page** → NOT FOUND — needs manual verification before any use.
- **Yalçıner & Akyüz 2024 code:** the paper states "Our source code is publicly available in [36]" but reference [36] is NVIDIA's **Path-Tracing-SDK** (https://github.com/NVIDIAGameWorks/Path-Tracing-SDK, now superseded by https://github.com/NVIDIA-RTX/RTXPT). That SDK is a Falcor/Donut-based real-time path tracer, **not** an SVO path-guiding implementation — the authors' guiding code does not appear to have a dedicated public repository. **Phase-0 conclusion: NO license-compatible public SVO-guiding implementation exists → plan a paper-only port.** The METU PhD thesis (https://open.metu.edu.tr/handle/11511/109165) is CC BY-NC-ND 4.0 (non-commercial + no-derivatives) → also INCOMPATIBLE with §6, and not code anyway.

### Risks
- **GPU SVO cost / atomics:** the 2× path-tracing overhead + ~4–6.5 ms/sample update-atomics cost (paper Table 1) must clear the wavefront perf budget, not just the VRAM budget.
- **REG:254 shade budget (Astroray-specific, hardest risk):** the on-the-fly cone-trace + PDF/CDF + MIS path does not fit the register-pinned shade kernel; it needs its own stage (mirroring the file's own pattern of offloading register-heavy work to intersect/regen) or a product-path-guiding warp-cooperative kernel, which is a larger architectural change than the spec's "inside the shade stage" sketch implies.
- **Paper used OptiX for cone tracing:** Astroray has a custom CUDA BVH (no OptiX inline-RT in shared memory); the cone-trace must be reimplemented against that BVH (or empty-space-skipping SVO traversal, which the paper reports as slower). This is real new code, not a drop-in.

---

## 6. Verification gaps (NOT FOUND — needs manual verification)

- Vorba 2014 `olpm2014_source.zip` license (page states none).
- Whether any third-party (non-author) clean-room SVO-wavefront-guiding implementation exists under a permissive license (searched GitHub topics "svo" / "wavefront" — none matching).
- The exact chapter page range of Müller 2019 within the course notes (sources disagree: ACM Article 18 pp. 1–77 vs course-note chapters 18:35–18:48 vs blog citing pp. 37–50).

---

## 7. Bottom line for the spec writer

1. Fix the target paper title to "Path Guiding for Wavefront Path Tracing: A Memory Efficient Approach for GPU Path Tracers" (Computers & Graphics 121 (2024) 103945, DOI 10.1016/j.cag.2024.103945, arXiv:2405.06997, CC BY 4.0).
2. Phase 0 resolves to **paper-only port**: no permissively-licensed public implementation exists; PPG/robust-vmm-guiding are GPL-3.0 (reference-only); OpenPGL (Apache-2.0) is CPU-only and SD-tree/vMF-based, not the SVO method.
3. The dominant engineering risk is not memory (SVO is ~1.3–4 MiB, confirmed) but **register budget + cone-trace implementation**: the shade kernel is REG:254-pinned and byte-identical, and the paper's cone trace is OptiX-based. Plan a dedicated guiding stage + a CPU-first SVO-build/PDF-query milestone.

---

**File written to:** `.astroray_plan/docs/pkg136-svo-path-guiding-research.md` — confirmed present.

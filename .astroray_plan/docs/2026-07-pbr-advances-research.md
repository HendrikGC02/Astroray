# PBR advances 2023–2026 — research sweep (2026-07-17)

**Method:** deep-research workflow — 5 search angles, 21 primary sources fetched,
89 claims extracted, top 25 adversarially verified with 3 independent voters each
(2/3 refutations kill a claim): **23 confirmed, 2 refuted, 0 unverified**.
Run on the travel laptop; full raw result archived in the session transcript.
This doc is the CLAUDE.md §6 research record for the techniques below — each
still needs its license re-verified against the actual repo before any port.

## Headline

The richest directly-adoptable cluster for Astroray is **specular/caustic
transport** — four independent 2023–2026 lines of work target exactly our
existing SMS + photon-map pipeline. For **path guiding on our CUDA wavefront
architecture**, the SVO-based wavefront guiding paper (Computers & Graphics
2024) is the uniquely-fitted option (OpenPGL remains CPU-oriented). **ReSTIR
PT/GRIS** is the path-space resampling roadmap — with a hard licensing rule:
RTXDI is proprietary and DISQUALIFIED; use the paper + author reference code or
reimplement.

## Confirmed findings (vote margins shown)

### 1. Specular Polynomials — Newton-free SMS seed finding (3-0, high)
Fan et al., SIGGRAPH 2024, ACM ToG, DOI 10.1145/3658132, arXiv:2405.13409.
Reformulates specular constraints as polynomial systems → univariate
root-finding (rational coordinate mapping + hidden-variable resultant).
Deterministic, exact for single bounce, GPU-friendly; kills SMS's
divergence-from-bad-seed and one-solution-per-seed failure modes (two-bounce
GPU solver ~10× slower than a Newton step but far more robust). **Fit:** a
targeted drop-in upgrade for the SMS seed-finding stage (pkg64/pkg106 lineage).
Ref impl: github.com/mollnn/spoly ("MIT-style" — VERIFY). Cost: moderate-high.

### 2. Partitioned SMS + ReSTIR — interactive caustics (3-0, high)
Hong, Duan, Wang, Yuksel, Zeltner, Lin, SIGGRAPH Asia 2025,
DOI 10.1145/3757377.3763927 (co-author = SMS originator Zeltner). Tile-based
sample-space partitioning bounds the Newton manifold walk to a local vicinity +
per-frame prior; ReSTIR spatiotemporal reuse amortizes sample generation.
**Fit:** partitioning alone is a cheaper standalone win for our SMS; the full
method presupposes ReSTIR reservoir infrastructure (finding 8 — and pkg55
Phase C's ReSTIR-to-SoA work is the natural foundation). Ref impl: Falcor 8.0
module github.com/Utah-Graphics-Lab/PSMS-ReSTIR (Falcor BSD-3 — VERIFY module).

### 3. Manifold Path Guiding — importance-sampled specular chains (3-0, high)
Fan et al., ACM ToG 42(6), SIGGRAPH Asia 2023, DOI 10.1145/3618360,
arXiv:2311.12818. First general framework for importance sampling discrete
specular chains; reconstructs energy distributions from historical sub-paths →
seed chains → manifold walks. Up to 40× variance reduction on long specular
chains. Known failure mode (per Specular Polynomials): tiny convergence basins.
Ref impl: github.com/mollnn/manifold-path-guiding (Mitsuba 2 base, BSD-3 —
VERIFY repo). Cost: high (guiding structure + manifold-walk integration).

### 4. Online 3D-Gaussian photon guiding (3-0, high)
Huang, Tanaka, Komura, Kitamura, arXiv:2403.03641 (2024). Global 3D GMM +
adaptive light-cluster sampler guides photon emission; closed-form directional
transform (their Eq. 13) samples emission directions from the guiding
distribution. Beats bound-based/2D-histogram/vMF/MCMC guiding baselines.
**Fit:** augments (not replaces) the pkg109–113 photon-emission stage.
**No confirmed public implementation — likely a paper-only port.** Cost: moderate.

### 5. Position-free Monte Carlo layered BSDFs (3-0, high; pre-window foundational)
Guo, Hašan, Zhao, ACM ToG 37(6), SIGGRAPH Asia 2018, DOI 10.1145/3272127.3275053.
Unbiased arbitrary-layered BSDF, position-free formulation over solid-angle
measures; forward + bidirectional estimators; surface+volumetric layers,
anisotropy, full spatial variation without precomputed discretized BSDFs.
2018 but explicitly extended (not superseded) by 2020–2022 follow-ups.
**Fit:** the rigorous route to true layered materials alongside our Disney BSDF.
Ref impls in Mitsuba-family research code (VERIFY). Cost: high.

### 6. OpenPBR thin-film / coat / fuzz layers (3-0, high — with a refutation caveat)
Portsmouth, Kutz, Hill (Autodesk), arXiv:2512.23696, SIGGRAPH 2025 course
companion. Documents thin-film iridescence, coat (incl. darkening physics), and
fuzz as distinct layer types. OpenPBR spec is Apache-2.0 with a MaterialX
reference implementation. **CAVEAT:** the companion claim that OpenPBR's
slab-layering + statistical mixing is "the mechanism to port for
energy-preserving multiscatter" was REFUTED 0-3 — treat OpenPBR as a documented
feature set for thin-film/coat/fuzz, NOT a multiscatter blueprint.
Cost: moderate for thin-film specifically (self-contained BSDF layer).

### 7. SVO-based wavefront path guiding (3-0 core / 2-1 priority, high)
Yalçıner & Akyüz, Computers & Graphics 121 (2024) 103945, arXiv:2405.06997.
First guiding method designed for a wavefront GPU path tracer: directionless
radiant exitance in one global sparse voxel octree; guiding PDFs/CDFs generated
on-the-fly via cone-trace queries in shared memory — no persistent per-region
PDF storage (fixed ~3.96 MiB SVO vs PPG SD-tree 19→37 MiB). **Fit: the
strongest architectural match to our wavefront kernel + 8–16 GB VRAM budgets.**
No confirmed public repo — VERIFY availability. Cost: moderate.

### 8. ReSTIR PT / GRIS — path-space resampling roadmap (3-0, high)
Lin, Kettunen, Bitterli, Pantaleoni, Yuksel, Wyman, ACM ToG 41(4), SIGGRAPH
2022, DOI 10.1145/3528223.3530158. Generalizes ReSTIR to full path space via
context-aware shift mappings. Unbiased offline recipe: temporal reuse OFF, 32
candidates/px, 3 spatial rounds, 6 neighbors, 10 px radius. 2026 follow-up
("ReSTIR PT Enhanced") reports further 2–3× gains. **LICENSING (verified from
RTXDI LICENSE.txt §4(e)): NVIDIA RTXDI SDK is proprietary — DISQUALIFIED. Use
the paper + github.com/DQLin/ReSTIR_PT (VERIFY its license) or reimplement.**
**Fit:** pkg55 Phase C moves ReSTIR reservoirs into wavefront SoA stages —
GRIS is the citable foundation for doing that properly, and it unlocks
finding 2's interactive caustics. Cost: very high but staged.

### 9. OpenPGL surface + volume guiding (2-1, medium)
Intel, github.com/OpenPathGuidingLibrary/openpgl, Apache-2.0. Guided sampling
on surfaces (learned incident radiance × BSDF cosine lobe) and in volumes
(× single-lobe HG phase) — relevant to accretion-disk volume guiding. CPU-
oriented (Cycles' guiding is CPU-only): a design/algorithm reference for us,
not a GPU drop-in; the SVO method (finding 7) is the wavefront-native choice.

### 10. ReSTIR PG — guiding × resampling fusion (2-1, medium; horizon item)
Zeng et al., SIGGRAPH Asia 2025, DOI 10.1145/3757377.3763813. Extracts guiding
distributions from ReSTIR-resampled paths to seed next-frame candidates.
State-of-the-art target IF we build both ReSTIR-PT and guiding subsystems.
No confirmed open implementation. Least de-risked; watch, don't port yet.

## Refuted claims (recorded so nobody re-imports them)

- "OpenPBR's slab-based layering + statistical mixing is the mechanism to port
  for energy-preserving multiscatter/layered BSDFs" — **0-3**.
- "OpenPGL is … specifically built to integrate path guiding into a renderer
  (directly applicable to a GPU wavefront tracer)" — **0-3** (CPU-oriented;
  purpose framing overstated).

## Coverage gaps (unresearched, NOT disproven — follow-up passes needed)

1. **Hero-wavelength / spectral MIS improvements post-Wilkie 2014** — no
   surviving claims; needs a dedicated pass (matters for our hero-less
   multiwavelength design).
2. **Energy-preserving multiscatter microfacet BSDFs** (Turquin 2019 analytic
   compensation vs Cycles multiscatter GGX vs OpenPBR) — unresolved which
   permissive reference to port; note pkg118 already closed the rough-glass
   energy deficit via the albedo-LUT fix, so this is about *reflection*
   multiscatter parity.
3. **Cycles 4.x/5.x feature specifics** (Sobol-Burley blue-noise sampling,
   light linking, light portals, Principled thin-film) — axis returned no
   verified claims; needs a direct Blender source review (we already have the
   fetch-from-projects.blender.org workflow from pkg115).
4. **Wavefront scheduling since Laine 2013** — only tangentially covered (NVIDIA
   SER whitepaper was fetched but no claim survived ranking); NOTE: SER is an
   OptiX/RTX-API feature, likely inapplicable to our pure-CUDA kernels.

## Adoption recommendation (mapped to the roadmap)

Near-term (compose with existing arcs):
- **pkg55 Phase C** should cite GRIS (finding 8) for the ReSTIR-to-wavefront
  reservoir design — it is the canonical reference for exactly that work.
- **SMS caustics quality chip:** Specular Polynomials seed-finding (finding 1)
  is the highest-value bounded upgrade to what we already have.
- **Thin-film iridescence** (finding 6) is a self-contained, showcase-friendly
  material feature — good medium package after Phase C.

Mid-term: SVO wavefront guiding (finding 7) once Phase C stabilizes the
wavefront as the only pipeline. Partitioned-SMS+ReSTIR (finding 2) after
Phase C's reservoirs exist.

Horizon: Manifold Path Guiding, 3D-Gaussian photon guiding, position-free
layered BSDFs, ReSTIR PG.

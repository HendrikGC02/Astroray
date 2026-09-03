# pkg136 — Path guiding (SD-tree core, CPU-first, GPU wavefront leg)

**Pillar:** 3 (light transport / variance reduction)
**Track:** A (Stage 1 is a CPU-verifiable SD-tree build + guided-sampling gate on CI; Stage 2 wavefront leg verified on RTX)
**Status:** open — spec rewritten 2026-09-03 from the web-verified research note
(`.astroray_plan/docs/pkg136-svo-path-guiding-research.md`). No guiding code in the
repo; supersedes the 2026-07 sketch (PR #492).
**Estimated effort:** L overall (Stage 1 CPU: M, 2–3 sessions; Stage 2 GPU: L, a
dedicated guiding stage + between-iteration build — a multi-session architectural leg).
**Depends on:** pkg55 Phase C (the wavefront is the only GPU pipeline — a moving
target otherwise; Stage 1 CPU has no such dependency and can land first). Composes
with pkg131 (adaptive sampling) and pkg224 (progressive sampler): guiding lowers the
per-sample variance the adaptive stopper measures.

---

## 0. The headline design call (read this first)

The filed name says **SVO** (Yalçıner & Akyüz 2024's sparse-voxel-octree method).
**I am recommending against SVO as the core structure for Astroray, and for an
SD-tree (Müller/Gross/Novák 2017) instead.** This inverts the paper's choice on
purpose, because the paper optimised for a constraint we do not have and pushed cost
into the one place we cannot afford it. Reasoning in §3. Two staging calls:

- **Stage 1 is CPU-only.** Build + guide + prove unbiasedness and variance reduction
  on the CPU integrator (`raytracer.h` `pathTraceSpectral`). This sidesteps the entire
  REG:254 shade-kernel problem, the missing-OptiX cone-trace problem, and the GPU
  build problem *simultaneously*, and still ships real variance-reduction value.
- **Stage 2 is the GPU wavefront leg**, designed with Stage-1 data in hand, using the
  established gated-`__noinline__` side-body pattern
  ([[noinline-runtime-flag-avoids-shade-spill]], [[shade-axis-side-table-avoids-spill]])
  so the REG:254 fleet kernel stays byte-identical when guiding is off.

If the owner wants the SVO memory story specifically, §3 keeps the SVO on-the-fly
cone-trace as the explicit Stage-2 GPU *alternative* to re-evaluate with measured
register cost — but the default core is the SD-tree.

---

## 1. Goal + why

**Before:** Astroray draws continuation directions from the BSDF
(`gpu_material_sample_spectral` on GPU, `Material::sampleSpectral` on CPU) plus NEE for
direct light. On hard indirect transport — light reaching a surface only after
bouncing through a small aperture (Veach door), an accretion-disk glow illuminating a
cavity, bright-envmap contribution through occluders, projected caustics — the BSDF
lobe points paths at directions that carry little incident radiance. Most samples miss
the energy; variance is high; pkg131 adaptive sampling can detect the noise but only
*spends more samples* on it, it cannot redirect them.

**After:** Learn an approximation of the **incident-radiance field** `Li(x, ω)` during
rendering and importance-sample continuation directions from it, **MIS-combined** with
BSDF sampling (so the estimator stays unbiased and never worse than pure-BSDF where the
guide is wrong). This is the standard variance-reduction win of path guiding: on the
paper scenes it is roughly a 2–10× reduction in mean-squared error at fixed sample
count on the hard-transport regions, at ~2× per-sample cost — a net time-to-noise win
where transport is hard, break-even-to-slight-loss where it is easy (hence the guide is
opt-in per render, off by default).

---

## 2. Citations (URL-backed, corrected)

Full fact base with inline source URLs:
`.astroray_plan/docs/pkg136-svo-path-guiding-research.md` (web-verified 2026-09-03).
Corrections below were re-verified against the primary pages while writing this spec.

- **Müller, Gross, Novák 2017 — "Practical Path Guiding for Efficient Light-Transport
  Simulation"** (the SD-tree). T. Müller, M. Gross, J. Novák. *Computer Graphics Forum*
  36(4) (Proc. EGSR 2017), pp. 91–100. **DOI 10.1111/cgf.13227.**
  https://cgl.ethz.ch/publications/papers/paperMue17a.php ·
  https://onlinelibrary.wiley.com/doi/10.1111/cgf.13227 · PDF:
  https://studios.disneyresearch.com/wp-content/uploads/2019/03/Practical-Path-Guiding-for-Efficient-Light-Transport-Simulation.pdf
  Structure confirmed from the ETH page: an **SD-tree** = upper **binary tree over the
  3D spatial domain** + lower **quadtree over the 2D directional domain** per spatial
  leaf; iterative reinforcement-style training with an automatic train/render budget
  split; unidirectional, unbiased. **This is the core algorithm ported here.**

- **"Practical Path Guiding" in Production (2019 improvements).** *Correction to the old
  spec:* there is **no 2019 journal paper**. The improvements are **chapter 10 of the
  SIGGRAPH 2019 course "Path Guiding in Production"** (Vorba, Hanika, Herholz, Müller,
  Křivánek, Keller). *ACM SIGGRAPH 2019 Courses*, Article 18. **Course DOI
  10.1145/3305366.3328091.** https://dl.acm.org/doi/10.1145/3305366.3328091 · course:
  https://cgg.mff.cuni.cz/~jirka/path-guiding-in-production/2019/index.htm
  Three adopted improvements: (i) inverse-variance-weighted sample combination (discard
  fewer training samples), (ii) filtered SD-tree splatting for robustness to
  high-frequency illumination, (iii) online-learned BSDF:guide selection probability.

- **Vorba, Karlík, Šik, Ritschel, Křivánek 2014 — "On-line Learning of Parametric
  Mixture Models for Light Transport Simulation."** *ACM ToG* 33(4) (Proc. SIGGRAPH
  2014), Article 101. **DOI 10.1145/2601097.2601203.**
  https://dl.acm.org/doi/10.1145/2601097.2601203 · author page:
  http://cgg.mff.cuni.cz/~jirka/papers/2014/olpm/index.htm
  Directional distribution as an on-line stepwise-EM-trained vMF/Gaussian mixture; the
  canonical "progressive online update" reference (contrast to Müller's learn-then-
  sample), cited for the update-scheme fork in §4. **Source-zip license: NOT STATED on
  the page → do not use as a code source until verified.**

- **Yalçıner & Akyüz 2024 — "Path Guiding for Wavefront Path Tracing: A Memory Efficient
  Approach for GPU Path Tracers"** (the SVO method; *the old spec's title "SVO-based
  wavefront path guiding" is a description, not the real title*). B. Yalçıner, A. O.
  Akyüz. *Computers & Graphics* 121 (2024), Article 103945. **DOI
  10.1016/j.cag.2024.103945.** arXiv:2405.06997 (**CC BY 4.0**).
  https://arxiv.org/abs/2405.06997 · https://arxiv.org/html/2405.06997v1
  Global SVO of **directionless radiant exitance**; PDF/CDF synthesised **on the fly**
  via **OptiX cone-trace** queries; ~3.96 MiB (Sponza) vs PPG SD-tree 19→37 MiB. Kept
  here as the Stage-2 GPU *alternative*, not the core (§3).

### Reference implementations + licenses (all verified in the note)

| Impl | License | Usable as | Note |
|------|---------|-----------|------|
| **OpenPGL** (Intel/RenderKit) `github.com/RenderKit/openpgl` | **Apache-2.0** | **design + structural reference for the SD-tree/spatial-cache + surface product** | **CPU-only today** (SSE/AVX-512; GPU "planned"); confirmed 2026-09-03. Not a GPU drop-in but the license-clean architectural anchor for Stage 1. |
| practical-path-guiding (Tom94) | GPL-3.0 | **algorithm reference only** | Mitsuba integrator; incompatible with CLAUDE.md §6, no code lift. |
| robust-vmm-guiding (Tübingen) | GPL-3.0 | algorithm reference only | Ruppert 2020 vMF; incompatible. |
| Vorba 2014 source zip | **unstated** | do not use until license verified | §6 gap in the note. |
| Yalçıner SVO code | none (ref [36] is NVIDIA RTXPT, not the guiding code) | — | **No permissively-licensed public SVO-guiding impl exists** → SVO route would be a paper-only port. |

**Sourcing conclusion (CLAUDE.md §6):** invoke `cite-algorithm` before coding. The
SD-tree core is a **clean-room port of Müller 2017 + the 2019 course improvements**,
using **OpenPGL (Apache-2.0) as the structural/design reference** (warp math, spatial
subdivision, sample-combination), never a copy of the GPL PPG source.

---

## 3. The structure decision (the real fork) — SD-tree, not SVO

Both structures represent the same thing (a spatial cache of directional distributions)
and differ in **where they spend cost**. The paper chose SVO to minimise *memory*.
Astroray's binding constraint is not memory — it is the **register-pinned sample-time
hot path** (REG:254, §5). These pull in opposite directions:

| Axis | **SD-tree (PPG 2017)** — recommended | **SVO (Yalçıner 2024)** — filed name |
|------|-------------------------------------|--------------------------------------|
| Directional storage | quadtree CDF stored per spatial leaf | none — directionless scalar exitance per voxel |
| Memory | grows with training; 19→37 MiB (Sponza) | fixed ~1.3–4 MiB |
| **Sample-time cost** | **light: warp a stored quadtree CDF** | **heavy: on-the-fly cone-trace + PDF/CDF synthesis** |
| Cone-trace / RT needed at sample time | **no** | **yes — paper uses OptiX; Astroray has no inline-RT, custom CUDA BVH only** |
| Update cost | atomic splat into quadtree **+ between-iteration tree subdivision** (GPU-hostile) | **atomic-add into fixed voxels** (GPU-friendly, no realloc) |
| Permissive reference | **OpenPGL (Apache-2.0), structural** | none (paper-only port) |
| Unbiasedness / quality track record | extensive (production-proven) | one 2024 paper |

**The call: SD-tree.** Four reasons, in priority order for *this* engine:

1. **Memory is not our constraint.** The SVO's *only* categorical win is ~4 MiB vs
   ~37 MiB. On an 8–16 GB budget both are rounding error. We should not pay elsewhere to
   win a metric we are not short on.
2. **The SVO puts its cost in the worst place we have.** Its sample-time work is an
   on-the-fly cone-trace against the acceleration structure plus PDF/CDF synthesis in
   shared memory — exactly the register-heavy work the REG:254 shade kernel has
   deliberately kept out. And the paper's cone-trace is **OptiX**; Astroray has a custom
   CUDA BVH with no inline-RT-in-shared-memory, so this is substantial new hot-path code,
   not a drop-in. The SD-tree's sample-time cost is a bounded warp of a stored CDF —
   far friendlier to a gated `__noinline__` side-body (§5).
3. **The SD-tree pushes its expensive part where we have slack.** Its cost is the
   between-iteration build/subdivision, which happens *outside* the shade hot path
   (once per training iteration) and, in Stage 1, runs on the CPU entirely. We trade a
   GPU-hot cone-trace for an off-hot-path build.
4. **License + maturity.** OpenPGL gives an Apache-2.0 structural reference; PPG is
   production-proven and its unbiasedness is well understood. The SVO route is a
   paper-only port of a single 2024 method with no clean-room reference.

**Honest counter (why the paper chose SVO):** the SD-tree's build/refine — quadtree
subdivision + spatial-tree rebuild between iterations — is genuinely GPU-hostile
(dynamic memory, the very thing Karras/Morton SVO avoids). That is the SVO's real
strength and it is why the paper picked it for a pure-GPU wavefront. **This spec answers
that by making Stage 1 CPU-only** (build cost is free of GPU concerns) and by deferring
the GPU-build decision to Stage 2 with data. If Stage 2 measurement shows the SD-tree
GPU build/refine is the bottleneck, the SVO on-the-fly path is the pre-vetted fallback —
that is why its cone-trace design stays in this spec rather than being deleted.

**Naming:** the package keeps the id **pkg136** but its subject is **path guiding
(SD-tree)**; "SVO" in the filename is retained only for continuity and is explicitly a
misnomer per this section.

---

## 4. Learn-then-sample vs progressive online; guided+BSDF MIS

**Update scheme — learn-then-sample (Müller 2017), not per-sample online.** Render in
**training iterations** of geometrically growing sample budget (1, 2, 4, 8, … spp).
Each iteration draws samples using the SD-tree learned from the *previous* iteration,
splats their radiance estimates back into a fresh SD-tree, and subdivides. Adopt the
2019 improvements: **inverse-variance-weighted combination** of iterations (keep, don't
discard, earlier iterations weighted by inverse variance) and **filtered splatting**
(box-filter a sample across neighbouring quadtree/spatial nodes for high-frequency
robustness). This maps cleanly onto Astroray's existing wave/iteration loop and pkg131's
progressive budget. Vorba-2014 pure-online stepwise-EM is *not* chosen — it fits a
persistent particle stream better than our iteration-batched wavefront, and vMF fitting
is heavier per update than quadtree splatting; it is cited only as the fork's alternative.

**MIS combination (the unbiasedness backbone).** At a shading point the sampling density
is a convex mixture `p = α·p_guide + (1−α)·p_bsdf`, with the guide/BSDF selection
probability `α` **online-learned** per spatial leaf (2019 improvement iii; start
α=0.5, clamp to [0.1, 0.9] so neither density starves). Each drawn direction is weighted
by the **balance/power heuristic** over `p_guide(ω)` and `p_bsdf(ω)` — the standard
one-sample-MIS combination Astroray already uses for BSDF-vs-NEE. NEE stays a third MIS
technique unchanged. **Unbiasedness constraints:** (a) `p_guide` is floored so it is
non-zero wherever `p_bsdf` is (a positive ε-mixture guarantees full support — same role
as the paper's radiance-field ε=1e−2 floor); (b) training-iteration samples that feed
the *image* are still MIS-weighted, so a badly-trained early guide inflates variance but
never biases the mean; (c) the first sample of each pixel is pure BSDF ("PT-first" per
the SVO paper's best variant), guaranteeing a valid estimate before any guide exists.

---

## 5. Astroray integration (the hard part)

Code anchored in `src/gpu/wavefront/stage_advance.cu` (read 2026-09-03) and
`raytracer.h` (`pathTraceSpectral`).

### Stage 1 — CPU-first (Track A, CI-verifiable, no GPU risk)

The CPU integrator draws its continuation direction from `Material::sampleSpectral`.
Insert the guide there, entirely in host code:

- **Structure:** an `SDTree` host class — binary spatial tree (split on point count per
  node) whose leaves own a directional `DTreeQuadtree` (adaptive quadtree over the
  2D **cylindrical / equal-area** direction mapping the paper uses). Build/refine between
  iterations; no device concerns.
- **Sample hook:** in `pathTraceSpectral`, wrap the BSDF sample: with probability α draw
  `ω` from the leaf's quadtree CDF (hierarchical warp), else from the BSDF; return the
  MIS weight over both PDFs (§4). Splat the resulting path radiance back into the
  training tree on the return sweep (radiance is known once the path terminates —
  accumulate along the path, splat at each vertex, exactly PPG).
- **Iteration driver:** a small scheduler that runs the doubling-budget training loop and
  the inverse-variance image combination. Reuse pkg131's progressive budget plumbing
  where it exists; do not add a new render-loop knob beyond `guiding: on/off`.
- **Gate:** CPU variance-reduction + unbiasedness (§6). This is a complete, shippable
  deliverable on its own.

### Stage 2 — GPU wavefront leg (Track A HW-verified; design with Stage-1 data)

Three device problems, each with its established Astroray pattern:

1. **Sample-time draw vs REG:254 (the hardest constraint).** The BSDF draw is
   `gpu_material_sample_spectral<HasPrincipled>(...)` at **line 1601**, and the next
   direction is written to SoA at **lines 1730–1738**. The shade kernel is pinned
   **REG:254 / STACK ~3352 / CONSTANT 1700** and the file's standing rule is *leave the
   fleet shade kernel byte-identical*. **Do not inline the guided draw here.** Use the
   proven side-body pattern ([[noinline-runtime-flag-avoids-shade-spill]]): put the
   guided-direction draw in a `__device__ __noinline__` function gated on a runtime
   `__constant__` flag `c_wfGuiding`, called in place of the line-1601 sample when the
   flag is set; the off-path fleet kernel must compile byte-identical (verify with the
   cuobjdump REG/STACK probe, as pkg223/pkg224 did). The stored-quadtree warp is a
   bounded read + a handful of comparisons — the register profile that makes the SD-tree
   viable here where the SVO cone-trace would not be. If even the warp spills, fall back
   to a **dedicated guiding stage**: a separate kernel that consumes the alive-pixel SoA,
   draws the guided `ω`, and writes `ray_direction_*` + the MIS-adjusted `path_bsdf_pdf`
   (the file already offloads register-heavy work to intersect/regen kernels this way).
2. **Between-iteration build/update.** The GPU-hostile part (§3). Two options to decide
   with Stage-1 data: **(a)** splat samples to a device buffer, copy back, rebuild the
   SD-tree on the CPU between iterations (simple, a PCIe round-trip per iteration — cheap
   relative to render time at these iteration counts); **(b)** device-side atomic splat
   into a fixed-topology tree with a periodic host-driven subdivision. Start with (a); it
   is correct and unblocks the sample-time leg — the build is not the hot path.
3. **Directional storage side-table.** The quadtree CDFs live in a `__constant__`-bound
   side table indexed by spatial-leaf id, mirroring the `c_wfTexBinding` /
   `c_wfLpBinding` pattern ([[shade-axis-side-table-avoids-spill]]) — never widen
   `GMaterial`/`HitRecord`. The spatial-leaf lookup for a shade point is a bounded binary
   descent from `rec.point`.

**Cost budget to clear:** the paper reports ~2× per-sample time for guiding (Sponza 74→
~180 ms). Stage-2 acceptance must show the SD-tree warp + build fits within a comparable
envelope on the RTX 5070 Ti, *and* that time-to-target-noise on the hard scene beats
unguided despite the per-sample overhead. Perf A/B under the clock-drift protocol
([[gpu-perf-ab-clock-drift]]): burn-in, min-of-N.

---

## 6. Acceptance gates

**Stage 1 (CPU, CI):**
- [ ] `cite-algorithm` note filed; SD-tree core is a clean-room port of Müller 2017 +
      2019 course improvements with OpenPGL (Apache-2.0) as structural reference; no GPL
      code lifted. License decision recorded.
- [ ] **Unbiasedness:** guided CPU render converges to the unguided converged image
      within MC noise on a furnace + on the hard-transport scene — per-channel
      mean-ratio within tolerance (NOT SSIM; [[ssim-wrong-gate-for-independent-rng]]),
      independent RNG streams, high spp.
- [ ] **Variance reduction:** on a hard-indirect reference scene (Veach-door-style small
      aperture, or an accretion-cavity scene), MSE-vs-reference at fixed spp is materially
      lower guided than unguided (target ≥2× MSE reduction on the hard region; report the
      full equal-sample and equal-time curves, don't cherry-pick one spp).
- [ ] **No-worse-off-when-off:** `guiding: off` is byte-identical to current CPU output.
- [ ] **No-harm-when-on-easy:** on a simple direct-lit scene guided MSE is within a small
      factor of unguided (guide must not blow up variance where transport is easy).

**Stage 2 (GPU, RTX HW-verify):**
- [ ] **Fleet kernel byte-identical when off:** cuobjdump REG/STACK probe shows the
      `<…>` fleet shade kernel unchanged (254/3352/1700); guiding-off render bit-identical
      to pre-pkg136 GPU output.
- [ ] **CPU↔GPU wavefront-diff parity** for the guided path (per-channel mean-ratio),
      pinning the same snapshot moment ([[wavefront-snapshot-semantics-class-of-bug]]).
- [ ] **GPU variance reduction** on the hard scene matches the Stage-1 trend; **time-to-
      target-noise beats unguided** despite ~2× per-sample cost; VRAM within budget.
- [ ] Photon-caustic + material regression suites green (guide must not perturb the
      specular/dispersion paths); perf A/B under the clock-drift protocol.

---

## 7. Effort / tier / risks

- **Track A**, two stages. **Stage 1: M** (2–3 sessions) — pure CPU, CI-gated, the
  algorithm de-risk. **Stage 2: L** — a device guiding leg + between-iteration build; a
  multi-session architectural change with an HW gate. **Tier:** Claude-core (last-line
  judgment on REG:254 reachability, unbiasedness, MIS correctness). The research-note
  drafting and the CPU scaffolding can be delegated (evidence-verified), but the shade-
  kernel register work and the parity/gate calls stay on Claude
  ([[delegate-tier-stalls-on-hard-packages]]).
- **Risks:**
  - **(highest) REG:254 sample-time budget.** The single reason SD-tree beats SVO here;
    even the light warp must be proven not to spill the fleet kernel — verify with the
    cuobjdump probe *before* trusting any Stage-2 gate, not after.
  - **GPU SD-tree build/refine is genuinely GPU-hostile.** Mitigated by CPU-first Stage 1
    and the copy-back build (Stage-2 option a); the risk is that build cost dominates at
    high iteration counts — measure early.
  - **Guide can *increase* variance when mistrained** (early iterations, high-frequency
    illumination). Mitigated by PT-first, MIS support-floor, inverse-variance combination,
    filtered splatting — all in §4; the "no-harm-when-on-easy" gate guards it.
  - **No permissive SVO reference exists**, so if Stage 2 forces the SVO fallback it is a
    paper-only port of the cone-trace — re-scope at that point, don't assume the OptiX
    path drops onto the custom BVH.
  - **Directional parameterisation mismatch** (cylindrical vs equal-area) between CPU and
    GPU quadtrees would silently diverge the parity gate — pin the mapping in Stage 1 and
    reuse the exact same warp on GPU.

---

## 8. Non-goals

- **Not ReSTIR-PG** (guiding × spatiotemporal resampling) — a separate subsystem.
- **Not photon/3D-Gaussian emission guiding** — augments the photon stage, out of scope.
- **Not volumetric guiding** (HG-lobe product) — surface guiding first; volumes are a
  follow-up slice once the surface SD-tree lands.
- **Not on by default** — `guiding: off` ships as the default; this is an opt-in
  variance-reduction mode for hard-transport renders.

---

## Provenance

Filed from the PBR-advances 2026-07 sweep as "SVO wavefront path guiding"; **rewritten
2026-09-03** from the web-verified research note
(`.astroray_plan/docs/pkg136-svo-path-guiding-research.md`) after the architect review
concluded the SVO's memory-motivated design fights Astroray's REG:254 sample-time
constraint. Core structure changed to SD-tree (Müller 2017 + 2019 course), CPU-first;
SVO cone-trace retained as the Stage-2 GPU fallback. Owner goal unchanged: variance
reduction on indirect-heavy scenes.

---

## Progress

- [ ] Stage 0 — `cite-algorithm` note + license decision (OpenPGL Apache-2.0 structural
      ref; clean-room PPG port).
- [ ] Stage 1A — host `SDTree` build/refine + iteration driver (learn-then-sample,
      inverse-variance combination, filtered splatting).
- [ ] Stage 1B — CPU guided sampling + guide/BSDF MIS in `pathTraceSpectral`; unbiased +
      variance-reduction gates green on CI.
- [ ] Stage 2A — device directional side-table + gated `__noinline__` guided draw;
      fleet-kernel byte-identical probe.
- [ ] Stage 2B — between-iteration build (copy-back first), CPU↔GPU parity, RTX
      variance + perf gates.

---

## Lessons

*(Fill in after the package is done.)*

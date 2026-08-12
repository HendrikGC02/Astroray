# pkg190 — GPU procedural-texture support (pkg186 slice 2)

**Pillar:** 5 / integration-first
**Track:** A
**Status:** open (filed 2026-08-12 as the pkg186 deferred follow-up; pkg186
PR #590 shipped the IMAGE-texture slice and explicitly deferred procedural
nodes + the pkg119-B procedural reclassification — see pkg186 Lessons
"Deferred to follow-up").
**Estimated effort:** L
**Depends on:** pkg186 (PR #590 — image-texture slice; establishes the
`__constant__ c_wfTexBinding` binding, the `<HasPrincipled,HasTexture>`
template pattern, `gpu_sampleImageTexture`, and the throughput-substitution
fold in `stage_advance.cu`); pkg115 (Blender shader-node texture adoption,
CPU); pkg119-B (Blender differential parity harness — the acceptance signal);
pkg178 (register-pressure isolation pattern).

---

## Symptom

The GPU wavefront path now samples IMAGE textures (pkg186) but still collapses
**every procedural texture node** (Noise / Musgrave / Voronoi / Wave / Gradient /
Checker / Magic / Brick / …) to the material's flat `getAlbedo()`. The CPU
reference evaluates the procedural node per-shade; the GPU sees a single constant
Vec3. Any procedural-textured Blender material renders as flat albedo on GPU with
no warning (the pkg186 `__features__` guard already reports `textures: CPU only`
on the GPU backend, so the user is at least *told* — but the capability is still
missing).

---

## The premise trap — RE-BASELINE pkg119-B BEFORE attributing bugs (read first)

The tempting story is "the 5 residual pkg119-B `TRANSLATION-BUG` entries are
procedural nodes, so procedural GPU support will reclassify them to parity-pass."
**Do not assume this.** The pkg186 implementer and memory
[[pkg119b-harness-runbook]] flag that the earlier TRANSLATION-BUG convictions
(`BSDF_TRANSPARENT`, `world:World`) were **DISPROVEN as SSIM false-positives on
noise-dominated / under-converged scenes** — not flat-albedo texture drops.
Evidence there: per-channel ratios ≈ 1.0, channel means matched Cycles, and SSIM
*climbed with samples* (32→256 spp) — the [[mc-noise-vs-deterministic]] signature
of a convergence-rate difference, not a translation bug. The real pkg119-B fix
was harness triage hardening (route ratio≈1.0 + small-dE + spp-climbing-low-SSIM
to a noise bucket), plus a lit backdrop for degenerate scenes.

**Hard requirement (acceptance-blocking):** before this package attributes ANY
pkg119-B residual to "missing procedural support", **re-baseline pkg119-B with
the noise/under-converged triage fix in place** ([[pkg119b-harness-runbook]]
run recipe: OpenMP-OFF `build_blender_addon_cuda`, `ASTRORAY_PYD_DIR` pointed at
it, absolute out-dir). Classify each of the 5 residuals into: (a) genuine
flat-albedo procedural drop that GPU eval fixes, (b) noise/convergence
false-positive (route to noise bucket, out-of-scope for this package), (c) a
Phase-A intentional-divergence / APPROXIMATED node. Record the split in Lessons.
Only the (a) set is this package's parity payoff — do not chase phantom bugs in
(b)/(c).

---

## Register pressure is the #1 design constraint (read before choosing an approach)

`stageShadeBucketedKernel` / `shadePathSlot` is pinned at **REG:254**
([[wavefront-shade-kernels-register-saturated]]). Porting a Perlin/Musgrave/
Voronoi/Wave evaluator into the shade path means heavy per-hit live state that
**spills ~2KB and tanks perf on the shared kernel** — this is exactly the
pkg178 lobe-array class of regression ([[closure-graph-lobe-count-spills-fused-kernel]]).
An image fetch was one cheap texel read; a procedural node is an arithmetic
kernel with gradients, hash tables, and octave loops.

**The untextured-fleet identity gate is a HARD acceptance criterion.** The
pre-pkg186 baseline for the shared untextured non-principled kernel
`stageShadeBucketedKernel<false,false>`, measured on **native sm_120 post-link**,
is:

> **REG:254  STACK:3608  CONSTANT[0]:1700**

Any procedural-eval design MUST leave this triple bit-identical (pkg186 restored
it after moving the texture pointers to `__constant__`). Measure with
`cuobjdump --dump-resource-usage` on a **native-arch** build — force
`-DASTRORAY_CUDA_ARCHS=native -DCMAKE_CUDA_ARCHITECTURES=native` and verify
`cuobjdump <pyd> -lelf` shows `sm_120` only; a stale arch-52 cache silently
mis-reports (the pkg183 fleet bug; pkg186 mis-read STACK 2640 this way).

### Candidate isolation strategies (genuine forks — pick per measurement, record why)

These are the real axes, not a manufactured menu. Decide by which keeps the
`<false,false>` identity AND holds perf on procedural scenes:

1. **Bake at upload time.** Evaluate the procedural node on the host (or a
   one-shot device pre-pass) into a device texel buffer, then reuse the pkg186
   image-fetch path verbatim (`gpu_sampleImageTexture` + the throughput fold).
   Zero shade-kernel codegen; maps onto the pkg186 `<...,HasTexture>` pattern
   with no new spill. Cost: resolution/quality of the bake, no procedural
   detail beyond the baked grid, and unbounded-domain nodes (world-space noise)
   need a domain/UV convention. This is the strong default for parity-first —
   it is the least register-risk path and reuses the proven pkg186 machinery.
2. **Separate procedural-evaluation stage.** A dedicated wavefront stage that
   evaluates procedural nodes into a per-path scratch albedo BEFORE
   `stageShadeBucketed`, so the shade kernel stays a cheap read. Cost: a new
   SoA field (per-path evaluated color) and a stage launch; must confirm the
   field does not itself spill the shade kernel.
3. **In-shade eval under `template<bool HasProcedural>`.** Follow the pkg186
   `<HasPrincipled,HasTexture>` pattern: gate procedural evaluators behind a
   compile-time bool so untextured/non-procedural scenes `if constexpr`-compile
   them out entirely. Cost: the procedural *specialization* itself will be
   register-heavy and slow — acceptable only if the `<...,false>` fleet kernel
   is provably unchanged AND the procedural specialization's perf is measured
   and acceptable. Highest risk of the three; use only if bake-at-upload cannot
   represent a required node.

Bias toward (1) bake-at-upload unless a specific node family demands live eval;
if you choose (2) or (3), the burden is a measured perf A/B on procedural scenes
plus the identity gate on the untextured kernel.

---

## Also fold in — PR #590 cycles-parity review advisories (from the pkg186 review)

These were raised advisory on PR #590 and deferred with the procedural slice:

1. **Harden the texture-fold divide guard.**
   `src/gpu/wavefront/stage_advance.cu:557` currently does
   `throughput.v[s] *= (d > 1e-8f ? texUp[s] / d : 0.0f)` where
   `d = upsample(baseColor)[s]`. For pkg186's near-gray base colors this is
   benign, but a **saturated / non-gray `baseColor`** (which procedural + textured
   metals will produce) makes `texUp / upsample(baseColor)` a **real per-λ
   spectral bias** — the division skews the exit spectrum, not just guards a
   zero. Fix: clamp the denominator, or divide by a **fixed neutral reference**
   (e.g. a flat-1.0 / D65-gray upsample) rather than the material's own saturated
   base upsample, so the substitution stays an exact albedo swap independent of
   baseColor chroma. State the chosen convention and prove it exact on a
   saturated-base test.
2. **Cover or explicitly exclude RGB-texture × non-visible-band.** The
   `gpu_rgbToSampledSpectrum(texColor, …)` × **`useLuminanceOutput`** (non-visible
   / luminance-only band) combination is **untested** in pkg186. Either add a
   parity leg for it or add an explicit guard + documented exclusion (a comment +
   a test asserting the exclusion path). Do not leave it silently undefined.
3. **Add a `textured_plane` parity scene to `scripts/run_parity.py`.** A
   UV-mapped quad with a low-frequency checker/gradient texture, a diffuse floor,
   and one area light. Oracle is **CPU/GPU per-channel mean-ratio**, never SSIM
   (independent RNG streams; [[ssim-wrong-gate-for-independent-rng]]). Wire it
   into the scene manifest the loader reads (`_load_scenes` / the parity scenes
   TOML), so both the image slice (pkg186) and this procedural slice have a
   standing parity scene. For the procedural half, extend it with a procedural
   (checker/gradient node) variant once GPU eval lands.

---

## Filtering is parity-coupled — record as a constraint

pkg186 shipped **nearest-neighbour** image sampling to match CPU
`ImageTexture::value` (clamp uv→[0,1], flip v, floor to texel) bit-for-bit; a
`cudaTextureObject_t` hardware-bilinear path would DIVERGE from the CPU sampler
and fail the mean-ratio gate. **This coupling is a hard constraint for any baked
procedural buffer too:** if the CPU procedural evaluator is point-sampled, the
GPU bake must be point-sampled at the same grid; if CPU ever gains bilinear
filtering, GPU must follow **in lockstep** in the same change. Do not
unilaterally add GPU filtering. Record this decision explicitly (mirror pkg186's
"Decision 2" note).

---

## Work

1. **Re-baseline pkg119-B first** (premise-trap section). Classify the 5
   residuals into (a) genuine flat-albedo procedural drop / (b) noise
   false-positive / (c) intentional-divergence. Only (a) scopes this package's
   node coverage. Record the split.
2. **Pick the isolation strategy** (bake-at-upload default; separate stage or
   in-shade template only with a measured justification). Implement GPU
   evaluation for the (a)-set procedural node families identified in step 1 —
   do not implement nodes nothing in the parity set exercises.
3. **Wire the fold-guard fix** at `stage_advance.cu:557` (divide by a neutral
   reference / clamp) so the substitution is exact for saturated base colors,
   and prove it on a saturated-base test.
4. **Cover RGB-texture × `useLuminanceOutput`** — parity leg or explicit guarded
   exclusion + test.
5. **Add the `textured_plane` parity scene** to `scripts/run_parity.py` (+ its
   procedural variant) with a per-channel mean-ratio oracle.
6. **Re-run pkg119-B** post-fix and record the (a)-set reclassification
   (before/after counts). A/B the untextured + non-procedural wavefront perf.

## Acceptance criteria

- [ ] **pkg119-B re-baselined with the noise-triage fix BEFORE any bug
      attribution**; the 5 residuals split into (a)/(b)/(c) and recorded. No
      residual is attributed to "missing procedural support" without the
      re-baseline evidence.
- [ ] A procedural-textured material (from the (a)-set) renders its procedural
      pattern — **not flat albedo** — on the GPU wavefront path, gated by a new
      test, and **visually confirmed** (metrics pass on garbage;
      [[general-photon-loop-needs-solid-glass]]).
- [ ] CPU/GPU **per-channel mean-ratio** within band on the procedural scene
      (never SSIM).
- [ ] **Untextured-fleet identity gate (HARD):** native sm_120 post-link
      `cuobjdump` shows `stageShadeBucketedKernel<false,false>` =
      **REG:254 STACK:3608 CONSTANT[0]:1700**, bit-identical to the pkg186
      baseline. No spill on the non-procedural specialization; measured perf A/B
      on procedural scenes recorded.
- [ ] `stage_advance.cu:557` fold-guard divides by a neutral reference /
      clamped denominator; a **saturated-base-color** test proves the albedo
      swap is exact and unbiased.
- [ ] RGB-texture × `useLuminanceOutput` is either covered by a parity leg or
      explicitly guarded + asserted-excluded by a test.
- [ ] `textured_plane` parity scene lives in `scripts/run_parity.py`'s scene
      set with a per-channel mean-ratio oracle.
- [ ] Filtering-parity constraint recorded (nearest to match CPU;
      bilinear only in lockstep with CPU).

## Hard non-goals

- **No CPU-bilinear / GPU-bilinear divergence.** Filtering stays parity-coupled
  and nearest until CPU changes; no unilateral GPU filtering.
- **No node families nothing exercises.** Implement only the (a)-set procedural
  nodes the re-baselined pkg119-B / parity scene actually hit. No speculative
  Perlin/Musgrave/Voronoi coverage "for completeness."
- **No spill on the `<...,false>` fleet kernel.** The identity gate is
  non-negotiable; the procedural cost is paid only by procedural scenes.
- **No SMS-GPU / photon-path work** (that is pkg189's spectral scope);
  the textured photon-caustic receiver stays base-albedo (pkg186 documented
  cut) unless the (a)-set forces it, in which case scope a separate follow-up.
- **No instanced-mesh procedural UV** (object-local barycentrics — same cut
  pkg178/pkg186 took for instanced anisotropy/texture).

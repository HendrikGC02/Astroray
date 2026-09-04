# pkg136 Stage 1B design — wiring the SD-tree guide into `pathTraceSpectral`

Execution design for Stage 1B (the CPU render wiring), written BEFORE touching
`raytracer.h` because that header is `#include`d by 9 `.cu` translation units
(cuda_renderer.cu, stage_advance.cu, gpu_nee.cuh, scene_upload.cu, …), so **every
edit to it triggers the full ~20–30 min CUDA rebuild**. The point of this note is
to get the whole change right in one or two build cycles, not ten.

Builds on the landed Stage-1A data structures (`include/astroray/guiding/dtree.h`,
`sdtree.h`, PR #693) and the de-risk (`pkg136-stage1-derisking.md`). No new
algorithm — Müller 2017 learn-then-sample + guide/BSDF MIS.

---

## 1. The thread-safety unlock: defer splatting

The render loop (`Renderer::render`, raytracer.h ~3677) is `#pragma omp parallel
for` over 16×16 tiles. The guide of the *previous* pass is read-only during a pass
(sampling + pdf are const, thread-safe). The only mutation is building the *next*
pass's tree. Rather than atomic flux (breaks `DTree`'s trivial copy/snapshot and
the `std::vector<DTree>` value semantics) or per-thread trees (memory-heavy merge):

**Threads append radiance records to a thread-local buffer; a single-threaded
splat between passes replays them into the building tree.** `flux` stays a plain
`float`; `SDTree`/`DTree` need NO change. A record is
`struct GuideRecord { float p[3]; float w[3]; float value; }` (28 B). At 512² × avg
path length 4 ≈ 1M records/pass ≈ 28 MB — fine for CPU Stage 1. Serial splat is
just tree descents (fast).

Thread-local buffers: size to `omp_get_max_threads()`, index by
`omp_get_thread_num()`; `pathTraceSpectral` pushes into the buffer for its thread.
Pass the buffer set via the `GuideContext` (below), not TLS globals.

## 2. `GuideContext` — the object threaded through

```cpp
// new: include/astroray/guiding/guide_context.h
struct GuideRecord { float p[3], w[3], value; };
struct GuideContext {
    const SDTree* guide = nullptr;              // previous pass, READ-ONLY (sample/pdf)
    std::vector<std::vector<GuideRecord>>* recordBuffers = nullptr;  // per-thread, WRITE
    float alpha = 0.5f;                         // guide/BSDF MIS selection prob
    bool learning = true;                       // append records this pass?
    bool enabled() const { return guide || recordBuffers; }
};
```

`pathTraceSpectral` takes `const GuideContext* guide = nullptr` (new trailing
param — default null ⇒ **byte-identical**, the no-harm-when-off gate). Renderer
owns the `SDTree` guide, the building `SDTree`, and the record buffers.

## 3. `pathTraceSpectral` changes (raytracer.h ~3162, ~3238, loop bottom)

Two hooks, both gated on `guide && guide->enabled()`:

**(a) Guided continuation sampling** — replace the bare BSDF draw at line 3162:
```
BSDFSampleSpectral bss = rec.material->sampleSpectral(rec, wo, gen, lambdas);
```
with a guide/BSDF one-sample-MIS draw when guiding is on AND this vertex is
non-specular (`!bss.isDelta` — delta lobes are excluded from guiding; the guide
can't represent a distribution the BSDF samples with a Dirac). Concretely:
- With prob `alpha` draw ω from `guide->guide->sampleDir(rec.point, u1, u2)`, else
  draw ω from the BSDF (the existing `sampleSpectral`).
- The continuation direction is ω; evaluate `bss.f_spectral` = BSDF value at ω,
  and the **mixed pdf** `p = alpha·p_guide_sa(ω) + (1-alpha)·p_bsdf(ω)`. Use `p`
  in the throughput divide at 3238 (replaces `bss.pdf`), and store it as
  `bsdfPdfPrev` for the two-sided-MIS emitter term.
- Support floor (unbiasedness): if guiding drew ω but `p_bsdf(ω)==0` (guide sent a
  ray the BSDF can't make, e.g. wrong hemisphere for an opaque surface), keep it —
  `f_spectral` will be 0 there so it contributes nothing but stays unbiased. If the
  BSDF drew ω, `p_bsdf>0` always. `p>0` always because the `alpha`-branch keeps
  `(1-alpha)·p_bsdf` OR the guide term. Guard `p>1e-8`.
- **First sample of each pixel = pure BSDF** ("PT-first", spec §4c): pass
  `alpha=0` on `s==0` so a valid estimate exists before any guide. Simplest: the
  Renderer sets `ctx.alpha=0` for pass 0 (no guide exists yet anyway).

**RESOLVED (audited 2026-09-05):** `Material` already exposes both virtuals —
`evalSpectral(rec, wo, wi, lambdas) -> SampledSpectrum` (the BSDF value f) and
`pdf(rec, wo, wi) -> float` (the solid-angle BSDF pdf) — on lambertian, principled,
etc. So evaluating f and p_bsdf at an externally-chosen ω needs **no new Material
API**; call `rec.material->evalSpectral(rec, wo, wiGuide, lambdas)` and
`rec.material->pdf(rec, wo, wiGuide)`. (Note the existing `evalSpectral` returns
f·… per its material; lambertian returns `albedo·cosθ/π`, i.e. f·cosθ — confirm
per-material whether cosθ is folded in and divide the throughput update
consistently with how the BSDF-sampled branch already does it at 3238.)

**(b) Radiance record on the return sweep.** The integrator is a forward loop
accumulating `color`. Per-vertex incident radiance for the guide =
`L_i(v, ω_v) = (color_final − color_snapshot_after_v) / β_after_v`, scalarised to
luminance. So: at the loop bottom (after the throughput update at 3238, once all of
v's emission+NEE are in `color`), record `{p=rec.point, w=bss.wi,
Csnap=Y(color), betaSnap=Y(throughput)}` into a small per-path vertex list. At path
end, for each vertex: `value = max(0, (Yfinal − Csnap)) / max(betaSnap, 1e-8)` and
push `GuideRecord{p, w, value}` to the thread buffer. Only record non-specular
vertices (guiding excludes delta). `Y(spec) = spec.toXYZ(lambdas).Y`.

Keep the per-path vertex list on the stack (small `std::array` or a reused
thread-local `std::vector` in the ctx to avoid per-path alloc).

## 4. `Renderer::render` restructure (raytracer.h ~3646)

Wrap the existing tile-parallel loop in a training-pass driver:
```
passes = geometric split of maxSamples: 1,2,4,…  (last pass gets the remainder;
         cap #passes ~ log2, e.g. min(K, …) with K≈6 per de-risk)
guide = null; building = SDTree(sceneBounds)
for each pass p with budget spp_p:
    ctx.guide = (p==0? null : &guide); ctx.alpha=(p==0?0:0.5)
    ctx.recordBuffers = &perThreadBufs (cleared)
    <run the existing tile-parallel loop, but for s in [0,spp_p) and pass ctx to
     sampleFull → pathTraceSpectral; accumulate this pass's image into passImage_p>
    // between passes, single-threaded:
    building.resetIteration(); replay all perThreadBufs → building.record(...)
    building.refine(spatialThreshold(p), dirRho)   // threshold grows with pass
    guide = building.snapshot()
combine passImage_p → final (inverse-variance weight, spec §4 / 2019 improvement;
   v1 may start with sample-count weighting and upgrade)
```
`sampleFull` needs to forward `ctx` to `pathTraceSpectral` → add a
`const GuideContext*` param to `Integrator::sampleFull` (default null) and to the
`SampleResult sampleFull(...)` override in every integrator (grep: only a handful).
Cleaner: stash `ctx` on the Renderer (`setGuideContext`) and have the spectral
integrator read `renderer_->guideContext()` in `sampleFull` — avoids touching the
`Integrator` vtable signature and every integrator. **Prefer the Renderer-stashed
context** (smaller blast radius, no ABI change to the integrator interface).

Scene bounds: `bvh->worldBounds()` or the root AABB (check the BVH API).

Spatial threshold schedule (Müller §5.2): split a leaf after it has received
`c·2^(p/2)` samples (`c≈4000` scaled to image size); expose as a constant, tune on
the hard scene.

Gate `guiding` on/off: a Renderer bool (`setGuiding(bool)`) + integrator param
`set_integrator_param("guiding", 0|1)`, default 0. Off ⇒ the pass driver collapses
to a single pass with `ctx=nullptr` ⇒ the exact current code path (byte-identical).

## 5. Gates (spec §6, Stage 1 CPU / CI)

- **Unbiased:** guided vs unguided converged image, per-channel mean-ratio within
  tolerance (NOT SSIM — [[ssim-wrong-gate-for-independent-rng]]), independent RNG,
  high spp. Scene: a furnace + the hard-transport scene.
- **≥2× MSE reduction** on a hard-indirect scene (Veach-door small aperture, or an
  accretion-cavity) at fixed spp; report equal-sample AND equal-time curves.
- **No-harm-when-off:** `guiding:off` byte-identical to current CPU output (hash a
  small render both ways).
- **No-harm-on-easy:** guided MSE within a small factor of unguided on a simple
  direct-lit scene.

Build a hard-transport reference scene under `tests/scenes/` (small emissive
aperture into a box). Reuse an existing furnace scene for unbiasedness.

## 6. Build discipline

- One `Material::evalSpectral` audit BEFORE editing raytracer.h (§3a) — if it's
  missing on any BSDF used by the test scenes, add it first (plugin .cpp, cheap
  rebuild) so the raytracer.h edit compiles first try.
- Batch ALL raytracer.h edits (§3, §4) into one pass, then a single full CUDA
  rebuild. Verify byte-identical-off with a quick CPU render hash BEFORE running
  the variance gates.
- `guiding` touches only the CPU path; GPU stays Stage 2 (deferred). But because
  raytracer.h is device-included, still run the RTX smoke at closeout to prove the
  device build is unperturbed ([[ci_has_no_gpu_runtime_blindspot]]).

## 7. Open question for the owner (non-blocking)

Inverse-variance image combination (2019 improvement i) vs a simpler
sample-count-weighted average for v1. Recommendation: ship v1 with sample-count
weighting (correct, simple), add inverse-variance as a follow-up once the ≥2× gate
is met — it improves the constant, not the correctness.

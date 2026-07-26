# pkg159 — Port cryptomatte accumulation into the wavefront (restore GPU cryptomatte that C7 dropped with the megakernels)

**Pillar:** 3 (GPU feature parity)
**Track:** A (RTX-gated — the GPU crypto buffers can only be verified on hardware)
**Status:** **DONE** — merged as `78e0ae4` (PR #529, 2026-07-26). RTX 5070 Ti verification: 4 gates passed; cross-path Psyop IoU **0.964–0.984 against the 0.85 threshold**. That threshold was the one number never previously exercised cross-path (it was derived CPU-vs-CPU) and it holds with margin — and it demonstrably discriminates, because the GPU leg's values are distinct from the CPU leg's (0.9743 vs 0.9843); had GPU crypto not been written the buffers would be all-zero and IoU ~0, not 0.97. NOT verified and recorded as such: a true cross-binary RED run (the gate file depends on helpers this PR adds, and the standalone probe scene needs `bpy`), and addon-side pass packing of the GPU crypto buffers. Two gate amendments adjudicated in-spec rather than silently weakened.
**Estimated effort:** M — device rank buffers + an ATOMIC insert port + driver threading + copy-back + a revived GPU gate. The concurrency (atomic slot writes) is the non-trivial part; the weight/ID math is a straight mirror of the CPU oracle.
**Depends on:** pkg55-C7/PR #524 (the wavefront is now the only GPU path). Reference material — all already in-tree:
- `include/astroray/cryptomatte.h` — `crypto_insert`, `crypto_sort_ranks`, `crypto_accumulate_shade_point`, `hash_to_float`, `crypto_name_registry` (pkg87a/b; the insert/accumulate helpers are already `__host__ __device__`).
- The deleted megakernel crypto block — recover from `git show 9fa91c8^:src/gpu/path_trace_kernel.cu` lines ~602-629 (the ONLY GPU crypto wiring that ever existed; `multiwavelength_kernel.cu` never had it — pkg87b status).
- The CPU oracle — `Renderer::pathTraceSpectral` (`include/raytracer.h:2576-2602`).

---

## Defect / Motivation

GPU cryptomatte lived **only** in the RGB `path_trace_kernel.cu` megakernel
(pkg87b, PR #344; the spectral `multiwavelength_kernel.cu` and the CPU wavefront
were explicitly deferred out of pkg87b's minimal-PR scope). PR #524 (pkg55-C7)
**deleted both megakernels**. The C7 authors recorded the drop as deliberate —
`src/gpu/cuda_renderer.cu:150-153` and `include/astroray/gpu_renderer.h:82-88`
both say "GPU cryptomatte accumulation is an intentional Phase-C drop; CPU
cryptomatte is the supported path." But "intentional to not port during the
deletion sweep" is not the same as "owned": the result is that the **production
GPU render path (the wavefront) emits empty `crypto_object` / `crypto_material`
buffers**, so the Blender addon's Cryptomatte passes are silently blank on any
GPU render. This is a real feature regression from #524 that no spec owns. This
package restores it in the wavefront.

**Three code-grounded subtleties — this is NOT a copy-paste of the deleted block:**

1. **Concurrency needs atomics (the real work).** The deleted megakernel used
   **one thread per pixel** (each thread looped all spp for that pixel in a
   local loop), so the per-pixel rank read-modify-write was race-free. The
   wavefront keeps **many concurrent path slots mapping to the same pixel**
   (different samples in flight in the pool + slot regeneration), so a plain
   `crypto_insert` into a shared per-pixel rank array is a **data race**. The
   fix must port Cycles' atomic cryptomatte write, not call the non-atomic
   `crypto_insert` from concurrent slots.

2. **Hash encoding — do NOT carry the megakernel's latent bug forward.** The CPU
   oracle stores `objectId = crypto_hash_name(name)` = `hash_to_float(MurmurHash3(name))`
   — the IEEE-754 exponent-guarded bit-reinterpret (`cryptomatte.h:30`). The
   deleted megakernel did `float objectId = tri.objectHash;` where
   `tri.objectHash` is `uint32_t` — an **implicit int→float numeric conversion**,
   NOT `hash_to_float`. So the old GPU crypto IDs did not match the CPU IDs or
   the EXR manifest encoding (`uint32_to_float32`), which means the old GPU
   cryptomatte was effectively unusable by a compositor picker. `scene_upload.cu`
   stores the raw MurmurHash3 `uint32_t` in `GTriangle`/`GSphere.objectHash` /
   `.materialHash` (`gpu_types.h:257-258, 280-281`); the port must apply
   `hash_to_float` to those to match the CPU oracle and the manifest.
   `hash_to_float` is currently a plain `inline` (no `__host__ __device__`
   guard) — either add the guard (trivial) or pre-encode the float host-side.

3. **First-hit semantics — match the CPU oracle, not the megakernel.** The CPU
   records crypto **only at `bounce == 0`** ("Cryptomatte records only the first
   hit", `raytracer.h:2580-2581`). The deleted megakernel accumulated at **every
   bounce** (no bounce gate). These two disagreed. The CPU is the declared
   oracle and the supported path, so the wavefront MUST match CPU: accumulate at
   the primary hit only. Do not reproduce the megakernel's every-bounce
   behaviour.

---

## Fix contract (cite — no inventions, CLAUDE.md §6)

1. **Device rank buffers.** Allocate two per-pixel device float arrays
   (`d_cryptoObjectRanks`, `d_cryptoMaterialRanks`), each sized
   `width * height * cryptomatteDepth * 2` (depth default 6), zeroed at render
   start. Gate all of this on `renderer.getCryptomatteEnabled()` — off by
   default, so default renders pay nothing.

2. **Accumulate in the wavefront shade at the primary hit.** In
   `shadePathSlot` (`src/gpu/wavefront/stage_advance.cu`), at the `bounce == 0`
   shade point **before** the throughput update (the `throughput *= bss.fSpectral …`
   at ~line 565), compute the weight EXACTLY as the CPU oracle does
   (`raytracer.h:2582-2589`): `contrib = throughput · bss.fSpectral` →
   `contrib.toXYZ(lambdas)` → the same D65 XYZ→linear-sRGB matrix → `weight =
   (r + g + b) / 3`. Read `objectId` / `materialId` from the hit primitive's
   uploaded hash via `GPrimitive → index → GTriangle/GSphere.objectHash /
   .materialHash` (mirror the deleted MK block), then apply `hash_to_float` per
   subtlety 2. Insert via the **atomic** port (item 3).

3. **Atomic slot insert (port, do not invent).** Mirror Cycles
   `film_write_cryptomatte_slots` under `__ATOMIC_PASS_WRITE__`
   (`intern/cycles/kernel/film/cryptomatte_passes.h`, Apache-2.0): walk the
   `depth` slots; `atomic_compare_and_swap_float(ranks + slot*2, CRYPTO_ID_NONE,
   id)` to claim an empty slot or detect a matching id, then
   `atomic_add_and_fetch_float(ranks + slot*2 + 1, weight)` to accumulate;
   last-slot overflow bucket as today. Add a `__device__` atomic variant
   alongside the existing serial `crypto_insert` (leave the CPU serial path
   untouched). CAS on a `float` is the standard `int`-reinterpret CAS loop
   (`atomicCAS` on `unsigned int*`) — cite the Cycles atomic helpers.

4. **Sort once, after all samples resolve.** Apply `crypto_sort_ranks`
   (weight-descending) per pixel in a finalize kernel or host-side after
   copy-back — the device twin of Cycles `film_sort_cryptomatte_slots` /
   `film_cryptomatte_post`. Sorting must run once, after accumulation completes,
   never concurrently with inserts.

5. **Copy back to the Camera's buffers.** After render, copy the device rank
   arrays into `Camera::cryptoObjectBuffer` / `cryptoMaterialBuffer`
   (`raytracer.h:1861`) so the existing pass plugin
   (`getPassBuffer("crypto_object"/"crypto_material")`) and the EXR writer see
   them unchanged. NOTE: `cuda_wavefront_render` takes `const Camera&`
   (`src/gpu/wavefront/gpu_wavefront_snapshot.h:157`) — thread the enable flag +
   buffers through the driver signature (or via the non-const `Renderer&` it
   already receives); do not silently `const_cast`.

## Gates

1. **Revive the GPU leg of the crypto acceptance gate LIVE on RTX.**
   `tests/test_cryptomatte_pass.py::test_cryptomatte_iou_roundtrip` (Psyop IoU
   roundtrip, `tests/scenes/cryptomatte_3_objects.py`) must run **against the
   wavefront GPU path**, not only CPU. Absence or xfail of the GPU leg is not
   acceptable evidence (memory `xfail-gated-features-must-unxfail`; verify with
   `--runxfail`).
2. **CPU↔GPU crypto parity.** Same scene + `cryptomatteEnabled`, CPU
   `pathTraceSpectral` vs wavefront crypto buffers: reconstructed per-object
   mattes agree at IoU ≥ the CPU gate's threshold, and the per-pixel float IDs
   (`hash_to_float`) match between legs AND the EXR manifest hex. (This gate is
   what catches subtlety 2 — the old MK would have failed it.)
3. **No-op guarantee.** `cryptomatteEnabled == false` → the wavefront image is
   BYTE-IDENTICAL to pre-pkg159 output and the crypto buffers are all zero.
4. **Determinism under concurrency.** Same seed/spp → identical sorted ranks
   across repeated runs (proves the atomic insert is correct, not racy — a
   non-atomic insert would produce run-to-run rank drift on edge pixels).
5. Build evidence per CLAUDE.md (`.pyd` mtime vs HEAD, canonical
   `build_cuda/Release/` load); RTX hardware verification, CI is blind here.

## Gate amendments — ADJUDICATION ITEMS (owner review, 2026-07-26)

Two clauses in the Gates section above are **unsatisfiable as literally
written**. They were amended during implementation (PR #529) and ratified by
the team lead. Recorded here explicitly so they are read as adjudicated
decisions, not as gates that were quietly weakened.

**Amendment 1 — Gate 3, "BYTE-IDENTICAL".** The clause reads
"`cryptomatteEnabled == false` → the wavefront image is BYTE-IDENTICAL to
pre-pkg159 output". Unsatisfiable *by construction*, for two independent
reasons:
- There is no pre-pkg159 binary to compare against.
- **The wavefront is not bit-identical to itself.** `stageRegenKernel`
  accumulates radiance with `atomicAdd`, so summation order varies run to run.
  Measured by the team lead on consecutive same-seed runs: 29 of 27648 elements
  differ, at 1.19e-07. pkg157's spec carried the identical defective clause and
  was formally amended to the 1e-5 MC convention on 2026-07-26 (same morning);
  this is the same defect, same resolution.

  *Amended to:* crypto-ON vs crypto-OFF at the same seed must match, asserted
  with `max < 1e-3` / `mean < 1e-5`. This is strictly stronger than the intent
  (it proves the added code has no effect on the image) while sitting above the
  atomic-reordering floor. Implemented as
  `test_gpu_crypto_disabled_is_noop`.

**Amendment 2 — Gate 4, "identical sorted ranks".** After the
weight-descending sort, two IDs carrying near-equal weight can legitimately
swap rank between runs, so slot-order identity is not a property the correct
implementation has.

  *Amended to:* compare the order-independent per-pixel `id → weight` mapping.
  The **ID set is compared EXACTLY**; only the weights carry tolerance (1e-4,
  for atomic reassociation). Deliberately not loosened on both axes: the exact
  ID-set half is precisely what a racy insert breaks (two threads both claiming
  an empty slot loses an ID; a non-atomic `+=` loses updates). Implemented as
  `test_gpu_crypto_deterministic_under_concurrency`.

## Structural gap surfaced by this package (not fixed here)

**The GPU render route does not run the pass pipeline at all.** Only
`Renderer::renderFrame` executes `passes_`; the GPU branch of
`PyRenderer::render` (`module/blender_module.cpp`) returns straight from
`cuda_wavefront_render` without constructing a `Framebuffer` or running a
single `Pass`. pkg159 worked around it by reproducing `CryptomattePass`'s
sort + normalise inside the wavefront driver — correct and narrow for this
package (the alternative, wiring `passes_` into the GPU branch, would newly run
denoisers and every AOV pass over buffers the GPU path never fills), but it is
a workaround, not a fix.

This will bite **the next AOV ported to the GPU**, in exactly the way it nearly
bit pkg159: the port lands, the buffer fills, and the post-processing step
silently never runs. Worth its own spec. Explicitly NOT in pkg159's scope.

## Non-goals

- **No new crypto features.** Depth, typenames (object + material only), the
  EXR/manifest format (pkg87a), and the hashing algorithm are all unchanged —
  pkg87a/b's contract is the contract.
- **Not the every-bounce accumulation or the `(float)uint32` ID encoding** of
  the deleted megakernel — both are bugs this port explicitly does NOT carry
  forward (subtleties 2 and 3).
- **Not perf** (pkg155) or the naive bounce-2 residual (pkg156) — but note this
  package touches `stage_advance.cu`, the same file as pkg156/pkg157/pkg120;
  serialize the wavefront-`.cu` lane, do not run these as parallel implementer
  worktrees.
- **Not the ReSTIR GPU driver** (`cuda_wavefront_render_restir`) in v1 — wire
  the standard wavefront driver first; ReSTIR crypto is a follow-up if wanted.

## Provenance

Filed by the architect during the 2026-07-25 → 26 overnight boot. GPU
cryptomatte regressed with PR #524 (pkg55-C7), which deleted the only GPU crypto
wiring (`path_trace_kernel.cu`, pkg87b) and left it unowned
(`cuda_renderer.cu:150-153`, `gpu_renderer.h:82-88`). No prior spec tracks the
restoration.

**Citations (CLAUDE.md §6):**
- Friedman & Jones 2015, "Cryptomatte: Instance ID Mattes" (Psyop, presented
  DigiPro/SIGGRAPH 2015) — spec v1.2.0, BSD-3-Clause
  (https://github.com/Psyop/Cryptomatte). Wire format, manifest, `uint32_to_float32`.
- Cycles `intern/cycles/kernel/film/cryptomatte_passes.h` (Apache-2.0) —
  `film_write_cryptomatte_slots` under `__ATOMIC_PASS_WRITE__`
  (`atomic_compare_and_swap_float` on the id slot + `atomic_add_and_fetch_float`
  on the weight), `film_sort_cryptomatte_slots`, `film_cryptomatte_post`.
- Existing research note `.astroray_plan/docs/cryptomatte-research.md` (extended
  by this package with the "Wavefront port — atomic concurrency" section).

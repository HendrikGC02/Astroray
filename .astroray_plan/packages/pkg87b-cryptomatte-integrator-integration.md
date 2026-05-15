# pkg87b — Cryptomatte Integrator Integration

**Pillar:** 5
**Track:** A
**Status:** open
**Estimated effort:** 1.5–2 weeks (the depth the original spec
understated — per-shade-point accumulation across every integrator,
CPU + GPU)
**Depends on:** pkg87a (hashing, `crypto_insert`, crypto framebuffer
buffers, name plumbing, EXR writer must be merged first)
**Reference research:** `.astroray_plan/docs/cryptomatte-research.md`
(Psyop spec v1.2.0 BSD-3, Friedman & Jones SIGGRAPH 2015; Cycles
`intern/cycles/kernel/film/cryptomatte_passes.h` + `kernel_write_data_passes`
Apache-2.0). Reference it; do not duplicate.

---

## Why this package exists

The original `pkg87-cryptomatte.md` modelled Cryptomatte as a first-hit
AOV ("at every first-hit AND at indirect bounces … call
`crypto_insert`", one bullet in the integrator). That bullet hid the
real work: Psyop-conformant Cryptomatte is a **per-shade-point coverage
histogram** that must be accumulated at *every* shade point along
*every* path, in *every* integrator, on both the CPU and GPU back ends —
exactly where Cycles calls `kernel_write_data_passes` (which invokes the
cryptomatte post step at each shade vertex, not just the camera hit).
This is the part the owner split out on 2026-05-15. pkg87a delivers the
plumbing; this package wires it into the render path.

---

## Goal

**Before:** pkg87a is merged. `crypto_object` / `crypto_material`
framebuffer buffers exist and are zero-filled. `crypto_hash_name()` and
`crypto_insert()` exist and are unit-tested. `GTriangle`/`GSphere` carry
`objectHash`/`materialHash`. **Nothing writes into the crypto buffers.**

**After:** Every integrator that produces a final image accumulates a
per-pixel ranked `(id, weight)` histogram for object names and material
names, where:

- the contribution is written **at every shade point** along the path
  (camera hit *and* every indirect bounce that carries throughput to the
  pixel), mirroring Cycles `kernel_write_data_passes` which is invoked
  per shade vertex;
- `weight = average(throughput · bsdf_eval)` at that vertex — the exact
  Cycles weight model (`kernel/film/cryptomatte_passes.h`), where
  `throughput` is the path throughput *before* the BSDF at this vertex
  and `bsdf_eval` is the evaluated BSDF response; component-wise product,
  averaged over RGB (research note §"Weight Computation");
- `id = crypto_hash_name(name)` resolved from the hit primitive's
  `objectHash` / `materialHash` (already on `GTriangle`/`GSphere` from
  pkg87a) for the GPU path, and from `Hittable::getName()` /
  `Material::getName()` for the CPU path;
- weights are accumulated raw; per-pixel normalisation
  (`Σ weight == 1` on hit pixels, `== 0` on sky) is applied by the
  pkg87c pass plugin at EXR-write time, not in the integrator (matches
  the research note and Cycles, which normalises post-accumulation).

---

## Scope — exact integrator enumeration

The crypto write must land in **every integrator that can be the
configured final-image integrator**, on **both** the CPU plugin path and
the GPU kernel path. Enumerated from `plugins/integrators/`,
`src/gpu/`, and `src/cpu/wavefront/` at spec time (2026-05-15):

### CPU integrator plugins (`plugins/integrators/`)

| File | Registered name | In scope? | Rationale |
|---|---|---|---|
| `spectral_path_tracer.cpp` | `"path_tracer"` | **Yes — primary** | The default production integrator; the main acceptance target. |
| `multiwavelength_path_tracer.cpp` | `"multiwavelength_path_tracer"` | **Yes** | Final-image integrator (spectral); shade points carry object/material identity. |
| `caustic_path_tracer.cpp` | `"caustic_path_tracer"` | **Yes** | Final-image integrator; instrument the primary path-trace shade points (caustic-specific connection vertices follow the same Cycles weight rule). |
| `sms_caustic_path_tracer.cpp` | `"sms_caustic_path_tracer"` | **Yes** | Final-image integrator; same as above for the SMS variant. |
| `restir_di.cpp` | `"restir-di"` | **Yes** | Final-image integrator; accumulate at the resolved shade point after reservoir resampling (use the selected sample's surface identity and its contribution weight). |
| `ambient_occlusion.cpp` | `"ambient_occlusion"` | **Yes (object/material id only)** | Produces a final image; AO has no BSDF chain, so write the first/visible shade point with `weight = visibility-fraction` (coverage), which is the degenerate-but-correct Cycles behaviour for non-lighting integrators. |
| `neural_cache.cpp` | `"neural-cache"` | **Yes** | Final-image integrator; accumulate at the primary shade points the same as `path_tracer`; cache-query bounces inherit the parent vertex throughput. |

All seven `ASTRORAY_REGISTER_INTEGRATOR` entry points must populate the
crypto buffers when the crypto passes are enabled. (Verify the list is
still complete at implementation time: `grep -rn
ASTRORAY_REGISTER_INTEGRATOR plugins/integrators/` — add any integrator
added after this spec.)

### GPU kernels (`src/gpu/`)

| File | In scope? | Rationale |
|---|---|---|
| `path_trace_kernel.cu` | **Yes** | The GPU mirror of `path_tracer`; the per-shade-point write must be added in the device path-trace loop using `GTriangle::objectHash` / `GSphere::objectHash` (already uploaded by pkg87a's `scene_upload.cu`). |
| `multiwavelength_kernel.cu` | **Yes** | GPU spectral integrator; same treatment. |
| `cuda_renderer.cu` | **Yes (orchestration)** | Allocate device crypto buffers, copy back to `Framebuffer::cryptoObjectBuffer/cryptoMaterialBuffer` after the kernel, mirroring the existing AOV copy-back. |

### CPU wavefront reference (`src/cpu/wavefront/`)

| File | In scope? | Rationale |
|---|---|---|
| `reference_pt_wavefront.cpp` / `reference_pt_production.cpp` | **Yes** | These are reference oracles used by the pkg55-B' bit-identity gates. They must accumulate crypto identically to the megakernel CPU path so future CUDA-port parity gates remain meaningful. Coordinate with the pkg55-B' keying contract — do not perturb RNG dimension counts. |

### Shared helper

Add one small CPU/GPU-shared helper (host + `__device__`) that, given a
hit primitive and the current `(throughput, bsdf_eval)`, calls
`crypto_insert` into the pixel's object and material rank arrays. Place
it next to `crypto_insert` in `include/astroray/cryptomatte.h` (mark
`__host__ __device__` so the GPU kernels can reuse it verbatim — this
is the Cycles model: one rank-merge routine shared by all back ends).
Cite Cycles `kernel_write_data_passes` (called at every shade point) and
`kernel/film/cryptomatte_passes.h` (the rank-merge) in the code.

---

## Key design decisions

1. **One shared `__host__ __device__` accumulation routine.** Do not
   fork CPU and GPU rank-merge logic. Cycles uses a single
   `kernel_cryptomatte_post`; divergence here is the classic source of
   CPU/GPU matte mismatch. pkg87a's `crypto_insert` becomes
   `__host__ __device__`.
2. **Write site = every shade vertex, gated by a render flag.** The
   accumulation must be a no-op (early return) when the crypto passes
   are not requested, so the default render path pays ~zero cost. Gate
   on a `bool cryptomatteEnabled` carried alongside the existing pass
   flags, not on buffer-pointer-null checks scattered per integrator.
3. **Weight = `average(throughput · bsdf_eval)` — Cycles-exact.** Do not
   substitute radiance or luminance. The research note §"Weight
   Computation" pins the formula; the Psyop compositor node assumes this
   model after normalisation.
4. **Sky / no-hit contributes nothing.** A path segment that escapes to
   the environment adds no crypto sample; those pixels normalise to
   `Σ weight == 0`, which the pkg87c pass relies on for IoU.
5. **RNG-contract safety for the wavefront oracles.** The crypto write
   must not consume RNG dimensions. It reads already-computed
   `throughput`/`bsdf_eval` and hit identity only. Verify the pkg55-B'
   bit-identity gates still pass after instrumentation
   (`mc-noise-vs-deterministic` memory note: stable per-channel ratios
   ⇒ a non-RNG bug; treat any gate movement as a wiring error, not
   noise).

---

## Acceptance criteria

- [ ] All seven CPU integrators and the GPU path-trace +
      multiwavelength kernels populate `crypto_object` /
      `crypto_material` when crypto is enabled; the buffers are exactly
      zero (every float) when crypto is disabled.
- [ ] **Hand-computed small-scene histogram test.** A deterministic
      scene (e.g. two named quads `A`, `B` with named materials `mA`,
      `mB`, fixed camera, fixed seed, low spp, no environment) where the
      per-pixel coverage is analytically known. For a chosen interior
      pixel on `A` and an edge pixel straddling `A`/`B`, the decoded
      `(id, weight)` ranks match the hand-computed expectation within a
      tight tolerance (rank 0 id == `crypto_hash_name("A")`, weight
      within ε of the analytic coverage; the `A`/`B` edge pixel shows
      both ids with weights summing to ~1 after normalisation). The
      hand computation is written out in the test docstring.
- [ ] **CPU/GPU agreement.** The same scene rendered through
      `path_tracer` (CPU plugin) and `path_trace_kernel.cu` (GPU)
      produces crypto histograms that agree per pixel within a tolerance
      consistent with the existing CPU/GPU image-parity bar (decoded id
      sets identical; weights within the same ε used for the colour
      AOVs).
- [ ] **Multi-bounce coverage.** A scene where a glossy/refractive
      surface reveals a second object only via an indirect bounce: that
      second object's hash appears in the pixel's ranks with non-zero
      weight (proves accumulation is per-shade-point, not first-hit).
- [ ] pkg55-B' bit-identity / reference-oracle gates still pass
      (RNG-contract unperturbed).
- [ ] No regression in existing AOV/denoiser/integrator tests.
- [ ] Default render path (crypto disabled) shows no measurable
      slowdown (the accumulation early-returns).

---

## Non-goals

- No EXR write, no manifest emission, no normalisation here — that is
  the pkg87c pass plugin's job (it consumes these buffers).
- No Blender addon changes (pkg87c).
- No `CryptoAsset` typename.
- Do not change `crypto_insert`'s algorithm — only make it
  `__host__ __device__` and call it from the shade points.
- Do not add light-group AOVs (separate package).

---

## Progress

- [ ] `crypto_insert` + accumulation helper made `__host__ __device__`.
- [ ] `cryptomatteEnabled` render flag plumbed; accumulation early-exits
      when off.
- [ ] CPU: all seven integrators in `plugins/integrators/` instrumented.
- [ ] CPU wavefront reference oracles instrumented; pkg55-B' gates
      re-verified.
- [ ] GPU: `path_trace_kernel.cu` + `multiwavelength_kernel.cu`
      instrumented; `cuda_renderer.cu` copy-back added.
- [ ] Hand-computed small-scene histogram test green.
- [ ] CPU/GPU agreement test green.
- [ ] Multi-bounce coverage test green.
- [ ] Call-site sweep (CLAUDE.md): every changed signature grepped repo-
      wide; tests/mocks/bindings updated.
- [ ] PR opened (depends on pkg87a merged). STATUS.md updated.

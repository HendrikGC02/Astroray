# Cryptomatte Research Notes

**Package:** pkg87a (infrastructure)  
**Date:** 2026-05-22  
**License audit:** All references are Apache-2.0 (Cycles), BSD-3 (Psyop spec), or public domain (smhasher) — compatible with Astroray's license.

---

## Primary References

### Psyop Cryptomatte Specification

- **Title:** Cryptomatte ID Mattes Specification v1.2.0
- **Authors:** Jonah Friedman & Andy Jones, Psyop
- **Presented:** SIGGRAPH 2015
- **Repository:** https://github.com/Psyop/Cryptomatte
- **License:** BSD-3-Clause
- **Specification PDF:** https://github.com/Psyop/Cryptomatte/blob/master/specification/IDmattes_poster.pdf

The Psyop spec defines:
- Wire format: float-encoded MurmurHash3_x86_32 IDs with seed 0
- Per-pixel ranked `(id, weight)` pairs
- EXR header manifest JSON schema
- Channel naming convention: `<typename>00.{R,G,B,A}`, `<typename>01.{R,G,B,A}`, etc.

### Blender Cycles Implementation

- **File:** `intern/cycles/kernel/film/cryptomatte_passes.h`
- **Repository:** https://github.com/blender/blender
- **License:** Apache-2.0
- **What we mirror:**
  - `film_write_cryptomatte_slots()`: per-shade-point `(id, weight)` insertion with duplicate merge
  - `film_sort_cryptomatte_slots()`: weight-descending sort via insertion sort
  - `film_cryptomatte_post()`: post-render sorting call
  - Default depth: 6 ranks (3 EXR layers × 2 id/weight pairs per RGBA quadruple)

Cycles hash API (mentioned in issue tracking):
- Function: `util_murmur_hash3()` → `util_hash_to_float()`
- Standard: MurmurHash3_32, uint32_to_float32 conversion
- Seed: 0 (per Psyop spec)

### alShaders2 hash_to_float

- **File:** `cryptomatte/cryptomatte.h`
- **Repository:** https://github.com/anderslanglands/alShaders2
- **License:** Apache-2.0 (Arnold plugin, Solid Angle/Autodesk)
- **What we mirror:**

```cpp
inline float hash_to_float(uint32_t hash) {
    // if all exponent bits are 0 (subnormals, +zero, -zero) set exponent to 1
    // if all exponent bits are 1 (NaNs, +inf, -inf) set exponent to 254
    uint32_t exponent = hash >> 23 & 255; // extract exponent (8 bits)
    if (exponent == 0 || exponent == 255)
        hash ^= 1 << 23; // toggle bit
    float f;
    std::memcpy(&f, &hash, 4);
    return f;
}
```

**Rationale:** The IEEE 754 exponent-guard ensures the float ID can round-trip through
EXR without hitting subnormal/inf/NaN ranges that compositors may mishandle. This
is the canonical encoding per the Psyop spec ("uint32_to_float32").

### MurmurHash3 Public Domain Implementation

- **File:** `src/MurmurHash3.cpp`
- **Repository:** https://github.com/aappleby/smhasher
- **Author:** Austin Appleby
- **License:** Public domain (author disclaimer in header)
- **What we port:**

```c
void MurmurHash3_x86_32 ( const void * key, int len,
                          uint32_t seed, void * out )
```

Complete function with `fmix32`, `ROTL32`, `getblock32` helpers. ~50 LOC.
Bit-exact reference; no modifications. Seed = 0 for Cryptomatte (per Psyop spec).

---

## Implementation Notes

### Hash Determinism Test Vector

The Psyop spec does not publish test vectors. We will verify determinism by:
1. Hashing a known string (e.g., `"cube_red"`) across multiple calls → same float.
2. Cross-referencing the raw `MurmurHash3_x86_32` output against the canonical smhasher for a fixed key (e.g., ASCII `"hello"`) to prove bit-exactness of the port.

Known reference (from smhasher `KeysetTest.cpp`):
- Key: `"hello"` (5 bytes), seed 0 → hash `0x248bfa47` (from smhasher verification suite)

### Rank-Merge Algorithm (Cycles Mirror)

From `film_write_cryptomatte_slots` (Cycles Apache-2.0):

**Algorithm:**
1. For each slot in the rank array:
   - If slot is empty (`id == ID_NONE`), insert `(id, weight)` and break.
   - If slot matches `id`, accumulate weight and break.
   - If last slot reached, accumulate weight there (overflow bucket).
2. After all insertions complete, sort ranks weight-descending via insertion sort (`film_sort_cryptomatte_slots`).

**Divergence from Cycles:**
- Cycles has `#ifdef __ATOMIC_PASS_WRITE__` for GPU concurrency (atomic CAS + add).
- Astroray pkg87a is CPU-only infrastructure; atomic path not needed yet.
- Astroray pkg87b (integrator integration) will add GPU-side writes; the `__host__ __device__` helper can adopt atomics then if needed.

### Weight Model

Per Cycles (`kernel/film/cryptomatte_passes.h` inline comments):
- `weight = average(throughput · bsdf_eval)`
- Component-wise product of path throughput and BSDF evaluation, averaged over RGB.
- Applied at **every shade point** along the path (camera hit + indirect bounces), not just first hit.
- Weights are raw-accumulated; per-pixel normalisation (`Σ weight == 1` on hit pixels, `== 0` on sky) is post-process (handled by pkg87c pass plugin at EXR-write time).

This weight model is not pkg87a scope (no integrator changes in pkg87a). Documented here for pkg87b reference.

---

## EXR Metadata Schema (Psyop Spec §3)

The EXR header must contain (for each typename, e.g., `CryptoObject`, `CryptoMaterial`):

```
cryptomatte/<hash7>/name       = "<typename>"
cryptomatte/<hash7>/hash       = "MurmurHash3_32"
cryptomatte/<hash7>/conversion = "uint32_to_float32"
cryptomatte/<hash7>/manifest   = "<JSON>"
```

Where:
- `<hash7>` = first 7 hex digits of `MurmurHash3_x86_32("<typename>", seed 0)`.
- `<JSON>` = manifest mapping human-readable names to their hashed float IDs:
  ```json
  {"cube_red": <hash_to_float(MurmurHash3("cube_red"))>, ...}
  ```

The manifest enables compositor pickers (Nuke Cryptomatte node, Blender Cryptomatte node) to list object names and reconstruct per-object mattes.

pkg87a's `src/io/exr_writer.cpp` will accept a `std::map<std::string, std::string>` for header attributes and write them via OpenEXR's `Imf::Header::insert()`.

---

## File Structure (pkg87a Deliverables)

| File | Contract |
|---|---|
| `src/util/murmurhash3.{h,cpp}` | Direct port of `MurmurHash3_x86_32` from smhasher (public domain). Cite Appleby at top. Bit-exact. |
| `include/astroray/cryptomatte.h` | `struct CryptoSample { float id; float weight; }`, `float hash_to_float(uint32_t)` (alShaders2 guard), `float crypto_hash_name(const std::string&)` (MurmurHash3 + hash_to_float), `void crypto_insert(float* ranks, int depth, float id, float weight)` (Cycles rank-merge). |
| `src/io/exr_writer.{h,cpp}` | Thin OpenEXR wrapper: multi-channel float32 write + string header attributes. Scoped to Cryptomatte. |
| `plugins/passes/cryptomatte_pass.cpp` | Pass-plugin skeleton, reads crypto buffers, may be non-functional (no data until pkg87b). |
| `tests/test_cryptomatte_hashing.py` | Infrastructure unit tests (hash determinism, float-encoding guard, rank-merge, manifest JSON schema). |

Modified files: `gpu_types.h` (add `objectHash`/`materialHash`), `raytracer.h` (add `name_` + crypto buffers), `scene_upload.cu` (hash names into GPU structs), `CMakeLists.txt` (OpenEXR + murmurhash3 TU).

---

---

## Wavefront port — atomic concurrency (pkg159, 2026-07-25)

**Context.** PR #524 (pkg55-C7) deleted both megakernels; the wavefront is the
only GPU path and carries NO crypto wiring. GPU crypto lived only in the deleted
`path_trace_kernel.cu` (pkg87b). pkg159 restores it in the wavefront. Recover the
exact deleted call sites from `git show 9fa91c8^:src/gpu/path_trace_kernel.cu`
(crypto block ~lines 602-629).

**Why the old wiring cannot be copy-pasted.** The megakernel used one thread per
pixel (each thread looped all spp locally), so the per-pixel rank
read-modify-write was race-free. The wavefront keeps many concurrent path slots
mapping to the same pixel (samples in flight + slot regen), so a non-atomic
`crypto_insert` into a shared per-pixel array is a data race. Cycles solves this
with an atomic slot write; we mirror it.

### Cycles atomic write path (Apache-2.0)

`intern/cycles/kernel/film/cryptomatte_passes.h`:

```
ccl_device_inline void film_write_cryptomatte_slots(ccl_global float *buffer,
                                                    const int num_slots,
                                                    const float id,
                                                    const float weight)
```

Guarded by `__ATOMIC_PASS_WRITE__`. For each slot the atomic path uses:
- `atomic_compare_and_swap_float(buffer + slot*2, ID_NONE, id)` — atomically
  claims an empty id slot (or detects a matching id already present),
- `atomic_add_and_fetch_float(buffer + slot*2 + 1, weight)` — atomically
  accumulates the weight into the paired element.

Last-slot overflow bucket as in the serial path. Post-render,
`film_sort_cryptomatte_slots` sorts slots weight-descending (called once, after
accumulation, via `film_cryptomatte_post`). On CUDA, `atomic_compare_and_swap_float`
is the standard `int`-reinterpret CAS loop over `atomicCAS(unsigned int*, …)`;
`atomic_add_and_fetch_float` is `atomicAdd(float*, …)`.

### Astroray mapping (pkg159)

- Add a `__device__` atomic variant beside the existing serial `crypto_insert`
  (`include/astroray/cryptomatte.h`); leave the CPU serial path untouched.
- Accumulate in `shadePathSlot` (`src/gpu/wavefront/stage_advance.cu`) at
  `bounce == 0` only (match the CPU oracle `raytracer.h:2581`, which records
  first-hit only — the deleted MK's every-bounce accumulation was a divergence).
- Weight math mirrors CPU `raytracer.h:2582-2589` exactly.
- **ID encoding fix.** Apply `hash_to_float()` to the uploaded `uint32_t`
  `GTriangle/GSphere.objectHash` — the deleted MK did an implicit `float =
  uint32_t` numeric conversion, producing IDs inconsistent with the CPU oracle
  and the `uint32_to_float32` manifest encoding. `hash_to_float` needs a
  `__host__ __device__` guard added (currently plain `inline`), or pre-encode
  the float host-side in `scene_upload.cu`.

### Upstream source, as fetched 2026-07-26 (pkg159 implementation)

Retrieved verbatim from
`https://raw.githubusercontent.com/blender/cycles/main/src/kernel/film/cryptomatte_passes.h`
(SPDX-FileCopyrightText 2018-2022 Blender Foundation, SPDX-License-Identifier
Apache-2.0). This is the exact code `crypto_insert_atomic` mirrors:

```c
ccl_device_inline void film_write_cryptomatte_slots(ccl_global float *buffer,
                                                    const int num_slots,
                                                    const float id,
                                                    const float weight)
{
  kernel_assert(id != ID_NONE);
  if (weight == 0.0f) {
    return;
  }

  for (int slot = 0; slot < num_slots; slot++) {
    ccl_global CryptoPassBufferElement *id_buffer = (ccl_global CryptoPassBufferElement *)buffer;
#ifdef __ATOMIC_PASS_WRITE__
    /* If the loop reaches an empty slot, the ID isn't in any slot yet - so add it! */
    if (id_buffer[slot].x == ID_NONE) {
      /* Use an atomic to claim this slot.
       * If a different thread got here first, try again from this slot on. */
      float old_id = atomic_compare_and_swap_float(buffer + slot * 2, ID_NONE, id);
      if (old_id != ID_NONE && old_id != id) {
        continue;
      }
      atomic_add_and_fetch_float(buffer + slot * 2 + 1, weight);
      break;
    }
    /* If there already is a slot for that ID, add the weight.
     * If no slot was found, add it to the last. */
    else if (id_buffer[slot].x == id || slot == num_slots - 1) {
      atomic_add_and_fetch_float(buffer + slot * 2 + 1, weight);
      break;
    }
#else  /* __ATOMIC_PASS_WRITE__ */
    ...
#endif /* __ATOMIC_PASS_WRITE__ */
  }
}
```

`film_sort_cryptomatte_slots` is an insertion sort, weight-descending, that
early-returns at the first empty slot — i.e. exactly Astroray's existing
`crypto_sort_ranks` (`src/util/cryptomatte.cpp`), which pkg87a already mirrored.
`film_cryptomatte_post` only calls the sort; Cycles normalises at pass-read time
(`film_get_pass_pixel_cryptomatte` divides by the sample scale), which is where
Astroray's `CryptomattePass` normalisation corresponds.

The CUDA atomic helpers, from
`https://raw.githubusercontent.com/blender/cycles/main/src/util/atomic.h`
(Apache-2.0), `#if defined(__KERNEL_CUDA__)` branch:

```c
#define atomic_add_and_fetch_float(p, x) (atomicAdd((float *)(p), (float)(x)) + (float)(x))

ccl_device_inline float atomic_compare_and_swap_float(volatile float *dest,
                                                      const float old_val,
                                                      const float new_val)
{
  union { unsigned int int_value; float float_value; } new_value, prev_value, result;
  prev_value.float_value = old_val;
  new_value.float_value = new_val;
  result.int_value = atomicCAS((unsigned int *)dest, prev_value.int_value, new_value.int_value);
  return result.float_value;
}
```

Astroray's `crypto_atomic_cas_float` uses `__float_as_uint` / `__uint_as_float`
instead of the union (identical semantics, no type-punning UB). The
`+ (float)(x)` of `atomic_add_and_fetch_float` is the fetch-and-return half,
which the caller discards, so the port calls plain `atomicAdd`.

### Decisions this package made that the spec left open

1. **Where the buffers are threaded.** `launchStageShadeBucketed` gains three
   trailing params (`d_cryptoObjectRanks`, `d_cryptoMaterialRanks`,
   `cryptoDepth`), matching how the other driver-owned buffers (`d_nee_f`,
   `d_shadow_queue`, `d_accum_xyz`) are already passed. They are NOT added to
   `GPUWavefrontState`, whose arrays are per-SLOT and allocated by
   `allocateGPUWavefrontState`; the rank arrays are per-PIXEL and driver-owned
   (the same reason `GPUReservoirSoA` was moved out of that struct in pkg55-C6b).
2. **Sort AND normalise happen host-side in the driver after copy-back.** The
   sort is spec item 4. The normalisation is added because the GPU render route
   (`blender_module.cpp`) does not run the pass pipeline at all — only
   `Renderer::renderFrame` does — so `CryptomattePass` never executes on a GPU
   render, and without it the GPU rank weights would be raw sums while the CPU's
   are normalised. The addon always enables cryptomatte and adds the
   "cryptomatte" pass together (`blender_addon/__init__.py:1104-1106`), so the
   CPU leg is always normalised. Both steps are idempotent, so wiring the pass
   pipeline into the GPU route later remains correct.
3. **Known divergence, not fixed here: unnamed primitives.** The CPU oracle
   leaves `objectId = CRYPTO_ID_NONE` when `hitObject->getName()` is empty
   (`raytracer.h:2592`), whereas `scene_upload.cu:253` substitutes a synthetic
   `"Unnamed_Triangle_<n>"` before hashing. So an unnamed object gets a real
   per-primitive ID on GPU and a zero ID on CPU. Neither appears in the manifest
   (the registry only records explicit `set_object_name`/`set_material_name`
   calls), so neither is selectable by a compositor picker. Out of pkg159's
   scope; changing it means either a `hasName` flag on `GTriangle`/`GSphere` or
   changing the CPU's zero-ID behaviour.
4. **ReSTIR is not wired** (`cuda_wavefront_render_restir`), per the spec's
   explicit v1 non-goal. A GPU render with `integrator == "restir-di"` and
   cryptomatte enabled still yields zero buffers.

### License

Cycles atomic path Apache-2.0 (compatible). Psyop spec BSD-3-Clause. No new
external code beyond the Cycles atomic-write mirror.

---

## Sources

- [GitHub - Psyop/Cryptomatte](https://github.com/Psyop/Cryptomatte)
- [Blender Cycles cryptomatte_passes.h](https://projects.blender.org/blender/blender/src/branch/main/intern/cycles/kernel/film/cryptomatte_passes.h)
- [alShaders2 cryptomatte.h](https://github.com/anderslanglands/alShaders2/blob/master/cryptomatte/cryptomatte.h)
- [smhasher MurmurHash3.cpp](https://github.com/aappleby/smhasher/blob/master/src/MurmurHash3.cpp)
- [Blender Developer Issue #81058 - EEVEE Cryptomatte](https://developer.blender.org/T81058)
- [Cryptomatte Wikipedia](https://en.wikipedia.org/wiki/Cryptomatte)

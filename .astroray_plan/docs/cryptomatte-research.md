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

## Sources

- [GitHub - Psyop/Cryptomatte](https://github.com/Psyop/Cryptomatte)
- [Blender Cycles cryptomatte_passes.h](https://projects.blender.org/blender/blender/src/branch/main/intern/cycles/kernel/film/cryptomatte_passes.h)
- [alShaders2 cryptomatte.h](https://github.com/anderslanglands/alShaders2/blob/master/cryptomatte/cryptomatte.h)
- [smhasher MurmurHash3.cpp](https://github.com/aappleby/smhasher/blob/master/src/MurmurHash3.cpp)
- [Blender Developer Issue #81058 - EEVEE Cryptomatte](https://developer.blender.org/T81058)
- [Cryptomatte Wikipedia](https://en.wikipedia.org/wiki/Cryptomatte)

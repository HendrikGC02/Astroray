# pkg87a — Cryptomatte Infrastructure

**Pillar:** 5
**Track:** A
**Status:** open
**Estimated effort:** done on branch — review-only (~0.5 day to verify + open PR)
**Depends on:** none
**Reference research:** `.astroray_plan/docs/cryptomatte-research.md`
(Psyop spec v1.2.0 BSD-3, Friedman & Jones SIGGRAPH 2015; smhasher
MurmurHash3 public domain, Austin Appleby; Cycles
`intern/cycles/kernel/film/cryptomatte_passes.h` Apache-2.0; alShaders2
`hash_to_float`). Do **not** duplicate that note — reference it.

---

## Why this package exists

This is the first of three packages that replace the original
`pkg87-cryptomatte.md`. The original single spec was filed assuming
Cryptomatte was a first-hit AOV capture comparable to the albedo/normal
passes. The implementer discovered that Psyop-conformant Cryptomatte
requires per-shade-point histogram accumulation of `(hashed_name,
coverage)` across **every bounce in 5+ integrators** (CPU + GPU), not a
first-hit write. The owner split the work on 2026-05-15:

- **pkg87a (this):** the hashing + EXR + buffer + name-plumbing
  infrastructure — exactly the code already sitting on the
  `pkg87-cryptomatte` branch.
- **pkg87b:** the per-shade-point integrator integration (the part the
  original spec understated).
- **pkg87c:** the Blender addon registration + the IoU acceptance gate.

This package's deliverable is **the existing `pkg87-cryptomatte`
branch**, committed and turned into its own PR. No new code is written
for pkg87a; its job is to define the contract the branch must satisfy so
a reviewer can sign off on it as a standalone, integrator-free
infrastructure layer.

---

## Goal

**Before:** Astroray has the AOV machinery (albedo, normal, depth,
motion) but no Cryptomatte primitives: no name→hash function, no
per-pixel ranked histogram type, no multi-channel EXR writer, no crypto
framebuffer buffers, and no human-readable names on `Hittable` /
`Material`.

**After:** The infrastructure exists and is unit-tested in isolation:

- `crypto_hash_name()` produces stable, Psyop-conformant float IDs
  (MurmurHash3_x86_32 seed 0 → `hash_to_float` subnormal/inf guard).
- `crypto_insert()` maintains a depth-N ranked `(id, weight)` histogram
  with duplicate-merge + weight-descending order.
- A minimal multi-channel float32 OpenEXR writer with string header
  attributes exists (`src/io/exr_writer.{h,cpp}`).
- `Hittable` and `Material` carry a `name_` string with get/set.
- `GTriangle` / `GSphere` carry `objectHash` + `materialHash`, populated
  at scene upload from those names.
- `Framebuffer` registers `crypto_object` / `crypto_material` buffers
  sized `width*height*depth*2` floats (default depth 6).
- A pass-plugin skeleton (`plugins/passes/cryptomatte_pass.cpp`) is
  registered and compiles.

**Explicitly NOT in this package:** no integrator writes into the crypto
buffers yet (that is pkg87b), and there is no Blender pass registration
or IoU gate (that is pkg87c). The buffers are allocated and zero-filled;
nothing populates them per shade point.

---

## Scope — exactly the `pkg87-cryptomatte` branch

The work is already implemented in the `pkg87-cryptomatte` worktree
(`../Astroray-pkg87`). A reviewer can enumerate it read-only with:

```
git -C ../Astroray-pkg87 status --short
git -C ../Astroray-pkg87 diff --stat HEAD
```

### Files created (must be present, committed)

| File | Contract |
|---|---|
| `src/util/murmurhash3.{h,cpp}` | Direct port of `MurmurHash3_x86_32` from smhasher (public domain). Cited at top of header. Bit-exact with the canonical implementation. |
| `include/astroray/cryptomatte.h` | `struct CryptoSample { float id; float weight; }`; `float hash_to_float(uint32_t)` (alShaders2 subnormal/inf guard — toggle bit 23 when exponent is 0 or 255); `float crypto_hash_name(const std::string&)` (MurmurHash3 seed 0 + `hash_to_float`); `void crypto_insert(float* ranks, int depth, float id, float weight)` mirroring Cycles `kernel_cryptomatte_post` (merge duplicate id, replace min-weight slot, sort weight-descending). |
| `src/io/exr_writer.{h,cpp}` | Thin OpenEXR wrapper: write multi-channel float32 EXR + string header attributes. Scoped to Cryptomatte's needs; not a general AOV writer. Compiled only when `find_package(OpenEXR)` succeeds. |
| `plugins/passes/cryptomatte_pass.cpp` | Pass-plugin skeleton, registered, reads the named crypto buffers. May be a non-functional skeleton at this stage (it has no populated data to consume until pkg87b) but must compile and register. |
| `tests/test_cryptomatte_hashing.py` | Infrastructure unit tests (see Acceptance). |

### Files modified (must show the documented deltas)

| File | Contract |
|---|---|
| `include/astroray/gpu_types.h` | `uint32_t objectHash; uint32_t materialHash;` added to `GTriangle` and `GSphere`. Per original key design decision #4 this brings `GTriangle` to a cache-line-aligned 64 bytes; MinGW large-struct-by-value note still applies (pass `const T&`). |
| `include/raytracer.h` | `std::string name_` + `setName`/`getName` on `Material` and `Hittable`. `Framebuffer` (Camera) gains `cryptoObjectBuffer` / `cryptoMaterialBuffer` (`std::vector<float>`, sized `width*height*cryptomatteDepth*2`) and `int cryptomatteDepth = 6`. `buffer()` returns them for names `"crypto_object"` / `"crypto_material"`. The old placeholder `cryptomatte*Buffer` Vec3 / coverage members are removed. |
| `src/gpu/scene_upload.cu` | At `buildSceneArrays`, hash each primitive's object name and material name via `MurmurHash3_x86_32(... seed 0 ...)` into `gt.objectHash` / `gt.materialHash` (and the sphere equivalents), with `Unnamed_*` fallbacks for empty names. |
| `CMakeLists.txt` | `find_package(OpenEXR CONFIG QUIET)`; gracefully degrade with a STATUS message when absent; add `src/util/murmurhash3.cpp` to `astroray_core_impl`; conditionally add `src/io/exr_writer.cpp` and link the OpenEXR target when found. |

If the branch's diff diverges from the above table, that divergence
must be reconciled (either the spec or the branch corrected) before the
PR merges. The spec is the source of truth for *what infrastructure
should exist*; the branch is the *implementation under review*.

---

## Acceptance criteria

A reviewer signs off pkg87a when, on a clean checkout of the
`pkg87-cryptomatte` branch:

- [ ] The project builds (`astroray_core_impl` + plugins) with the new
      translation units linked. When OpenEXR is present, `exr_writer.cpp`
      compiles and links; when absent, the build still succeeds and the
      STATUS message is emitted (graceful degradation is intentional).
- [ ] `tests/test_cryptomatte_hashing.py` passes:
  - [ ] **Hash determinism:** `crypto_hash_name("cube_red")` returns the
        same float across repeated calls and process restarts; the
        underlying `MurmurHash3_x86_32` matches the canonical smhasher
        output for at least one fixed key (e.g. ASCII `"hello"`).
  - [ ] **Float-encoding guard:** for an input whose raw hash has
        exponent field 0 or 255, `hash_to_float` returns a normal
        (non-subnormal, non-inf, non-NaN) float; round-trip
        `memcpy`-back recovers the toggled bit pattern.
  - [ ] **Rank-merge correctness:** `crypto_insert` over a hand-built
        sequence keeps the top-`depth` weights sorted descending and
        merges duplicate ids by summing weight (compare against a
        hand-computed expected array for depth 6).
  - [ ] **Manifest JSON schema:** the manifest produced for a small
        fixed name set parses as JSON and conforms to the Psyop schema —
        EXR header keys `cryptomatte/<hash7>/{name,hash,conversion,manifest}`
        where `<hash7>` is the first 7 hex digits of
        `MurmurHash3("CryptoObject")`, `conversion == "uint32_to_float32"`,
        `hash == "MurmurHash3_32"`, and every `name` in the manifest
        maps to `crypto_hash_name(name)` (round-trip integrity). This may
        be exercised through the `exr_writer` + a manifest-builder helper
        without any integrator.
- [ ] **No integrator changes.** `git diff origin/main..pkg87-cryptomatte`
      touches none of `plugins/integrators/*`, `src/gpu/path_trace_kernel.cu`,
      `src/gpu/cuda_renderer.cu`, `src/gpu/multiwavelength_kernel.cu`,
      `src/cpu/wavefront/*`, or the GPU wavefront stages. The crypto
      buffers are allocated and zeroed but never written per shade point.
      (Any such change belongs in pkg87b and must be reverted from this
      branch.)
- [ ] No regression in existing AOV/denoiser tests (`albedo_aov`,
      `normal_aov`, `motion_vector_aov`, OIDN/OptiX) — this package adds
      members and TUs but does not change the render path.
- [ ] `.astroray_plan/docs/cryptomatte-research.md` is committed on the
      branch (it currently exists untracked in the worktree).

---

## Non-goals

- No integrator instrumentation (pkg87b).
- No Blender addon pass registration, no UI toggles, no IoU acceptance
  gate (pkg87c).
- No `CryptoAsset` typename (separate future follow-up).
- Do not widen `exr_writer` into a general AOV writer; keep it scoped to
  Cryptomatte.
- Do not optimise the hash propagation (bit-packing / dedup tables); the
  8-bytes-per-primitive cost was accepted in the original design.

---

## Progress

- [ ] Branch `pkg87-cryptomatte` work committed (currently
      working-tree + untracked in `../Astroray-pkg87`).
- [ ] `cryptomatte-research.md` added to the commit.
- [ ] Infra unit tests (hash determinism, float-encoding guard,
      rank-merge, manifest JSON schema) authored and green.
- [ ] Build verified with and without OpenEXR present.
- [ ] Branch diff confirmed to contain zero integrator changes.
- [ ] PR opened (own PR, separate from pkg87b/pkg87c).
- [ ] STATUS.md updated.

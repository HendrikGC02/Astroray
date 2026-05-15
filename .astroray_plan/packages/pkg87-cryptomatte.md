# pkg87 — Cryptomatte Passes

**Pillar:** 5
**Track:** A
**Status:** superseded — split into pkg87a/pkg87b/pkg87c (owner decision 2026-05-15)
**Estimated effort:** 2–3 weeks
**Depends on:** none (independent of pkg55-B and pkg86)

---

## SUPERSEDED — see pkg87a / pkg87b / pkg87c

This single spec is **superseded**. During implementation the agent
discovered the spec understated the integration depth: it modelled
Cryptomatte as a first-hit AOV (one integrator bullet — "at first-hit
and indirect bounces call `crypto_insert`"), but Psyop-conformant
Cryptomatte requires **per-shade-point** histogram accumulation of
`(hashed_name, coverage)` at *every* bounce across *every* integrator
(7 CPU plugins + the GPU path-trace/multiwavelength kernels + the CPU
wavefront reference oracles), exactly where Cycles calls
`kernel_write_data_passes`. That is far more than the original Phase 2
scoping implied. On 2026-05-15 the owner split the work into three
phased, independently-reviewable packages:

- **`pkg87a-cryptomatte-infrastructure.md`** — hashing, EXR manifest
  writer, crypto framebuffer buffers, name plumbing, pass-plugin
  skeleton. Scope = exactly the existing `pkg87-cryptomatte` branch;
  becomes its own PR.
- **`pkg87b-cryptomatte-integrator-integration.md`** — per-shade-point
  `(hash, weight)` accumulation across all integrators (CPU + GPU).
  Depends on pkg87a. This is the part this original spec understated.
- **`pkg87c-cryptomatte-blender-acceptance.md`** — Blender pass
  registration, manifest in RenderResult, UI toggles, IoU ≥ 0.95
  acceptance gate. Depends on pkg87b.

The remainder of this document is retained for historical context and
as the source of the design decisions inherited by the three new specs.
Do not implement from it directly.

---

## Goal

**Before:** Astroray has no way to isolate an individual object or material
in the Blender compositor. The pass system emits AOVs (albedo, normal,
depth, motion, uv_debug) but no per-pixel object-identity information.
Production-style relighting / matte-extraction workflows are impossible.

**After:** Renders include a Cryptomatte pass set
(`CryptoObject*`, `CryptoMaterial*`) — a small fixed-size per-pixel
histogram of `(hashed_name, coverage)` pairs, plus an EXR-header JSON
manifest mapping hash floats back to human-readable names. The standard
Cycles / Karma / Arnold compositor Cryptomatte node picks the passes up
unchanged because we conform to the Psyop spec. Selecting an object in
the compositor reconstructs its mask at ≥ 0.95 IoU vs a ground-truth
isolated render.

---

## Context

Architect's Round 8 strategy pass identified Cryptomatte as one of the
two highest-leverage Cycles-parity wins not gated by pkg55-B (see
`.astroray_plan/docs/round8-strategy-pass.md` §2.3 and §3). The user
goal is "good Cycles parity in Blender — across performance, UI, and
features." Cryptomatte directly closes the largest compositor-side
feature gap: today there is no way to relight or extract per-object
mattes after the render. Cycles ships it; "Cycles parity" requires it.

The Cryptomatte format is an open standard published by Psyop
(BSD-3, ISBA white paper 2015) and is the de-facto interchange format
for object/material/asset mattes across Cycles, Arnold, Karma, V-Ray,
RenderMan, and Redshift. Implementing the spec gives us free
compatibility with every existing DCC compositor.

---

## Reference

### Reference Implementations

| Source | License | What we borrow |
|---|---|---|
| Psyop Cryptomatte specification (`Cryptomatte/specification/cryptomatte_specification.pdf`) | BSD-3-Clause | Wire format: float-encoded MurmurHash3_x86_32 IDs; per-pixel ranked `(id, weight)` pairs; EXR header manifest JSON; channel-naming convention (`<typename>00.{R,G,B,A}`, `<typename>01.{R,G,B,A}`, …). |
| Psyop `Cryptomatte/sample_plugin/cryptomatte_arnold.cpp` | BSD-3-Clause | Per-pixel rank-and-merge algorithm (insert hit, sort by weight, merge same-hash, cap to N ranks). |
| Cycles `intern/cycles/kernel/film/cryptomatte_passes.h` | Apache-2.0 | GPU-friendly write-side: `kernel_cryptomatte_post()` rank-merge, ID-from-shader plumbing, `u_cryptomatte_depth = 6` default. |
| Cycles `intern/cycles/integrator/pass.cpp` (`PASS_CRYPTOMATTE_*`) | Apache-2.0 | Buffer allocation sizes (4 floats × depth-pairs per pixel per typename) and pass registration shape. |
| Cycles `intern/cycles/scene/film.cpp` (`Film::update_passes`, cryptomatte manifest construction) | Apache-2.0 | Manifest JSON shape; EXR header key naming (`cryptomatte/<hash7>/{name,hash,conversion,manifest}`). |
| smhasher `MurmurHash3.cpp` (Austin Appleby) | Public domain | The hash function itself. Direct port; no license entanglement. |

### Research notes

Save to `.astroray_plan/docs/cryptomatte-research.md` before implementation:
- Psyop spec PDF DOI/SHA + ISBA 2015 paper full title.
- License audit (BSD-3 + Apache-2.0 + public-domain — all compatible).
- Exact Cycles source-file line ranges we will mirror.
- Worked example: hash of `"cube"` → `0x...` → reinterpret_cast<float>.

### External URLs

- <https://github.com/Psyop/Cryptomatte>
- <https://github.com/Psyop/Cryptomatte/blob/master/specification/cryptomatte_specification.pdf>
- <https://projects.blender.org/blender/blender/src/branch/main/intern/cycles/kernel/film/cryptomatte_passes.h>
- <https://projects.blender.org/blender/blender/src/branch/main/intern/cycles/integrator/pass.cpp>
- <https://projects.blender.org/blender/blender/src/branch/main/intern/cycles/scene/film.cpp>
- <https://github.com/aappleby/smhasher/blob/master/src/MurmurHash3.cpp>

---

## Prerequisites

- [ ] Build passes on `main` (clean working tree).
- [ ] No active pass-plugin refactor in flight (pkg72 motion-vector pass
      landed; pkg69 albedo pass landed — the AOV machinery is stable).
- [ ] Decision logged: OpenEXR multi-channel write lands inside this
      package's scope (see Key design decision #3).

---

## Specification

### Phase 1 — Hashing + per-pixel ranked accumulator (~1 week)

#### Files to create

| File | Purpose |
|---|---|
| `src/util/murmurhash3.{h,cpp}` | Port of MurmurHash3_x86_32 from smhasher. Header-only is acceptable. Cite Appleby/smhasher at the top of the .h. |
| `include/astroray/cryptomatte.h` | `struct CryptoSample { float id; float weight; };` and `inline float crypto_hash_name(const std::string& s)` wrapping MurmurHash3 + `reinterpret_cast<float>`. Also the rank-merge function `void crypto_insert(CryptoSample* ranks, int depth, float id, float weight)` mirroring Cycles `cryptomatte_post`. |
| `tests/test_cryptomatte_hashing.py` | Sanity tests: (a) known-name → known-hash (use Psyop spec test vectors, e.g. `"hero"` → `0x...`), (b) hash stability across runs, (c) rank-merge keeps the top-N weights and merges duplicates. |

#### Files to modify

| File | What changes |
|---|---|
| `include/astroray/gpu_types.h` | Add `uint32_t objectHash` to `GTriangle` and `GSphere`, and `uint32_t materialHash` to the GPU material struct (or via `materialId → materialHash` lookup table — see Key design decision #4). |
| `src/scene/scene.cpp` (or wherever GPU upload lives) | At scene-upload time, hash each object's name into `objectHash` and each material's name into `materialHash`. Build the host-side hash→name manifest map (per typename). |

### Phase 2 — Multi-channel EXR write + integration (~1 week)

#### Files to create

| File | Purpose |
|---|---|
| `src/io/exr_writer.{h,cpp}` | Thin wrapper around OpenEXR's `Imf::MultiPartOutputFile` or `Imf::OutputFile` with a vector of `Imf::Channel`s. Single entry point: `void write_exr(path, width, height, std::vector<ExrChannel>, std::map<std::string,std::string> header)`. |
| `plugins/passes/cryptomatte_pass.cpp` | `Pass` plugin registered as `cryptomatte_object` and `cryptomatte_material`. Reads `fb.buffer("crypto_object")` / `fb.buffer("crypto_material")` (per-pixel `[id0,w0,id1,w1,…,idN-1,wN-1]` float arrays of length `4*ceil(depth/2)`). Sorts ranks, normalises weights, fills the EXR channels. |
| `tests/scenes/cryptomatte_3_objects.py` | Test scene: three named cubes (`cube_red`, `cube_green`, `cube_blue`) with three named materials (`mat_red`, `mat_green`, `mat_blue`) on a single plane (`floor`). 256×256 render at low spp. |

#### Files to modify

| File | What changes |
|---|---|
| `include/raytracer.h` (`Framebuffer`) | Register `"crypto_object"` and `"crypto_material"` buffers, each sized `width*height*4*ceil(depth/2)` floats. Mirror `motion`/`uv` registration pattern at the existing buffer-name switch. |
| `include/raytracer.h` (integrator hit-write site) | At every first-hit AND at indirect bounces that contribute to the pixel's coverage, call `crypto_insert(ranks_for_pixel, depth, hit.objectHash, weight)` and `crypto_insert(…, hit.materialHash, weight)`. Weight = throughput-weighted contribution-to-pixel (Cycles uses `average(throughput * bsdf_eval)`; mirror exactly). |
| `module/blender_module.cpp` | Add `Renderer.get_cryptomatte_buffer(typename)` returning a zero-copy NumPy view; add the EXR-export Python binding `Renderer.write_cryptomatte_exr(path)`. |
| `CMakeLists.txt` | Add `find_package(OpenEXR REQUIRED)` and link `OpenEXR::OpenEXR Imath::Imath` against the library and the new exr_writer translation unit. |

### Phase 3 — Blender addon + acceptance (~1 week)

#### Files to modify

| File | What changes |
|---|---|
| `blender_addon/__init__.py` | Register the Cryptomatte passes via `RenderEngine.add_pass(name="CryptoObject00", channels=4, chan_id="RGBA", layer=view_layer.name)` (×3 layers for depth=6 — `00`,`01`,`02`). Same for `CryptoMaterial`. Expose `view_layer.use_pass_cryptomatte_object` and `view_layer.use_pass_cryptomatte_material` UI toggles in the Passes panel. |
| `blender_addon/__init__.py` (`update_render_result`) | When the engine finishes a render, fetch the cryptomatte buffers and call `layer.passes["CryptoObject00"].foreach_set(...)` for each EXR layer. Embed the manifest JSON as the standard Cryptomatte metadata key on the render result. |
| `tests/test_cryptomatte_pass.py` | (a) Render `cryptomatte_3_objects.py`. (b) Read the manifest. (c) For each named object, build a mask `selecting hash(name) == ranks[*,0::2]` weighted by `ranks[*,1::2]`. (d) Render a single-object ground-truth scene (only `cube_red`). (e) IoU between extracted mask and ground-truth coverage ≥ 0.95. (f) Repeat for `mat_red`. |

### Key design decisions

1. **Default depth = 6 ranks (3 EXR layers × 2 quadruples).**
   Matches Cycles `u_cryptomatte_depth = 6` and the Psyop spec default.
   Expose `bpy.context.scene.astroray.cryptomatte_depth` as a 2/4/6/8/16
   integer property; 6 is the default. Memory cost at 1080p × depth 6 ×
   2 typenames: `1920*1080*4*3*2*4 bytes = 191 MB`. Acceptable.

2. **v1 typenames = `CryptoObject` + `CryptoMaterial` only.**
   `CryptoAsset` requires asset/collection metadata propagation
   from the Blender addon through the .blend importer (pkg76) into
   the GPU scene. That plumbing is non-trivial and out of scope.
   File `pkg87b-cryptoasset.md` as a follow-up when this lands.

3. **EXR multi-channel write lands in this package.** A grep of
   `plugins/` shows no existing EXR writer — output today is single-
   channel PNG via the colourmap pass. We add a minimal
   `src/io/exr_writer.cpp` (one screenful of OpenEXR `Imf::OutputFile`
   API) here, scoped to Cryptomatte's needs (multi-channel float32, a
   handful of header strings). Future packages can reuse it; we do not
   pre-engineer for them. OpenEXR is BSD-3 (compatible).

4. **GPU hash propagation: add `uint32_t objectHash` + `materialHash`
   to `GTriangle` and `GSphere`.**
   `GTriangle` is currently 13 floats + 1 int = 56 bytes; adding 8
   bytes brings it to 64, which is cache-line-aligned and cheaper, not
   more expensive. Alternative considered: a `materialId → hash` lookup
   table on the device. Rejected because (a) the indirection costs a
   gmem fetch per shade, (b) per-object hashes still need per-primitive
   storage so we'd add the field anyway, (c) `GTriangle` is already the
   right grain. Cite the MinGW large-struct-by-value memory note
   (`mingw_large_struct_byval.md`) — at 64 bytes we are still well past
   the 32-byte threshold, so any host-side pass-by-value of `GTriangle`
   must continue to use `const T&`. No new exposure.

5. **MurmurHash3 from smhasher (public domain).** Direct port of
   `MurmurHash3_x86_32` from Austin Appleby's smhasher repo. ~50 LOC.
   Cite as `// Adapted from smhasher MurmurHash3.cpp (public domain,
   Austin Appleby)` at the top of `murmurhash3.h`. No license entry.

6. **Weight model = `average(throughput · bsdf_eval)`.** Mirror Cycles
   exactly (`kernel/film/cryptomatte_passes.h`, `kernel_write_data_passes`).
   Per-pixel weights are normalised in the pass plugin before EXR
   write so that `Σ weights == 1` per pixel on hit pixels and `== 0`
   on sky pixels. The Psyop compositor node requires the normalised
   sum, not raw radiance.

7. **Acceptance gate: IoU ≥ 0.95 vs ground-truth isolated render.**
   On the 3-object scene, render each object alone (others hidden) at
   the same camera + spp, threshold its alpha to a binary mask, and
   compare to the mask reconstructed by selecting the object's
   hash-float from the Cryptomatte ranks. IoU is the standard
   Cryptomatte-validation metric (Psyop spec §6, "Roundtrip Tests").
   The 0.95 threshold is below the Cycles Cryptomatte regression bar
   (0.97 internally) to leave headroom for early stochasticity at low
   spp — we render at 64 spp for the acceptance scene.

---

## Acceptance criteria

- [ ] `tests/test_cryptomatte_hashing.py` passes: known-name → known-
      hash test vectors match the Psyop spec; rank-merge produces the
      top-N weights sorted descending.
- [ ] `tests/scenes/cryptomatte_3_objects.py` renders without crashing
      at 256×256, depth=6, 64 spp.
- [ ] Output EXR opens in Blender's compositor; the Cryptomatte node
      lists `cube_red`, `cube_green`, `cube_blue` (CryptoObject) and
      `mat_red`, `mat_green`, `mat_blue` (CryptoMaterial) in its
      object picker.
- [ ] For each of the 6 names, the compositor-reconstructed mask has
      IoU ≥ 0.95 vs a single-object ground-truth render at the same
      camera and spp.
- [ ] EXR header contains valid `cryptomatte/<hash7>/{name,hash,
      conversion,manifest}` entries per Psyop spec §3.
- [ ] Manifest JSON parses; every name in the manifest matches the
      MurmurHash3 of itself (round-trip integrity).
- [ ] All existing tests still pass; no regression in `albedo_aov`,
      `motion_vector_aov`, `normal_aov`, or the OIDN/OptiX denoisers.
- [ ] Blender addon shows `Cryptomatte Object` / `Cryptomatte Material`
      checkboxes under View Layer → Passes; toggling them adds/removes
      the passes from `RenderResult.layers[0].passes`.

---

## Non-goals

- Do not add `CryptoAsset` in this package. Asset/collection metadata
  propagation is a separate follow-up (`pkg87b-cryptoasset.md`).
- Do not change the existing `Pass` plugin interface
  (`include/astroray/pass.h`). Cryptomatte fits the existing one-pass-
  reads-named-buffer pattern.
- Do not add light-group AOVs. That is pkg88 (Round 8 follow-up).
- Do not implement motion-blur-aware Cryptomatte. Cycles disables
  Cryptomatte when motion blur is on; we will when motion blur ships.
- Do not pre-engineer the EXR writer for general AOV output. Scope it
  to Cryptomatte's needs; let future packages widen it.
- Do not optimise the hash propagation with bit-packing or per-prim
  hash dedup tables. The 8-byte-per-primitive cost is acceptable.

---

## Progress

- [ ] Phase 1: MurmurHash3 port + `crypto_insert` rank-merge +
      Phase 1 tests.
- [ ] Phase 1: research notes saved to
      `.astroray_plan/docs/cryptomatte-research.md`.
- [ ] Phase 1: `objectHash`/`materialHash` plumbed into `GTriangle` /
      `GSphere` and populated at scene upload.
- [ ] Phase 2: `src/io/exr_writer.cpp` lands with OpenEXR linked.
- [ ] Phase 2: `crypto_object` / `crypto_material` framebuffer buffers
      registered and written from the integrator.
- [ ] Phase 2: `plugins/passes/cryptomatte_pass.cpp` plugin renders
      EXR with manifest header.
- [ ] Phase 2: `Renderer.get_cryptomatte_buffer` / `write_cryptomatte_exr`
      Python bindings.
- [ ] Phase 3: Blender addon registers `CryptoObject00/01/02` and
      `CryptoMaterial00/01/02` passes; manifest metadata embedded in
      render result.
- [ ] Phase 3: `tests/scenes/cryptomatte_3_objects.py` + matching
      ground-truth render harness.
- [ ] Phase 3: IoU ≥ 0.95 verified for all 6 names.
- [ ] STATUS.md updated; PR opened.

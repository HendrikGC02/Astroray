# pkg55 Phase B' — CPU Reference Oracle Design (Session 2)

**Status:** authoritative for Session 2.
**Spec:** `.astroray_plan/packages/pkg55-wavefront-soa-refactor.md` §"Phase B' — Restart".
**Branch:** `pkg55-B-restart`.

This document records all 8 Phase B' design decisions in code-level detail
(file paths, function signatures, RNG draw orders, SoA field lists), plus
the snapshot schema and the growing-oracle lifecycle. It is the engineering
playbook for Session 2. Sessions 3..N extend the same scaffolding.

---

## 1. Spectral oracle, not RGB (decision §1)

The reference path tracers and the CPU wavefront carry `astroray::SampledWavelengths`
and `astroray::SampledSpectrum` end-to-end. RGB only at final XYZ→sRGB conversion in
the test harness.

**Carrier types:**
- Wavelength bundle: `astroray::SampledWavelengths` (4 samples per path,
  `kSpectrumSamples = 4`).
- Radiance / throughput: `astroray::SampledSpectrum` (4 floats).
- Per-pixel output: XYZ tristimulus (`astroray::XYZ`), converted by the caller.

**Lambda sampling.** Stratified hero-λ over the visible band, draw a single uniform
`u01(gen)` and pass to `SampledWavelengths::sampleUniform(u01)`. This matches the
production `SpectralPathTracer::sampleFull` consumption pattern exactly (see
`plugins/integrators/spectral_path_tracer.cpp:107-108`).

---

## 2. RNG keying — two schemes (decisions §2, §3)

Two independent RNG schemes coexist:

### Production-side: tile-shared

`reference_pt_production` mirrors the tile loop in
`include/raytracer.h:2460-2570`:

```cpp
uint32_t baseSeed = renderer.getRenderSeed();  // 0 -> random_device
std::mt19937 gen(baseSeed + static_cast<uint32_t>(tileIdx));
```

Per pixel, per sample, RNG draws in this exact order:
1. `filterSample(gen, dist)`  — 2 draws (default `pixelFilterType=0`, box).
2. `filterSample(gen, dist)`  — 2 more, for v jitter.
3. `cam.getRay(u, v, gen)` — `Vec3::randomInUnitDisk(gen)` (rejection-sampled,
   so variable count; consumes at least 2 draws per accepted sample).
4. `dist01(gen)` — 1 draw for λ stratification, fed to `SampledWavelengths::sampleUniform`.
5. Inside `pathTraceSpectral`: draws for NEE light sampling, BSDF sampling, RR,
   etc. — whatever production consumes.

Steps 1-4 reproduce the integrator-frontend RNG consumption that happens
before `pathTraceSpectral` runs. Step 5 is reproduced by independent transcription
inside `reference_pt_production.cpp` per decision §6 — production
`Renderer::pathTraceSpectral` is not touched and is not called from the reference.

**Why this is bit-exact:** all per-pixel state is reduced from `gen`. As long as
we (a) iterate tiles in the same row-major order and (b) consume RNG draws in
the same order, the per-pixel output is bit-identical.

**Threading.** Production uses `#pragma omp parallel for collapse(2)`. Tiles
are independent (per-tile `gen`), so we can run the reference single-threaded
in the same row-major tile order and still hit bit-identity. We will use
single-threaded execution to keep the trip-wire deterministic in CI.

### Wavefront-side: per-path

`reference_pt_wavefront` and the CPU wavefront use:

```cpp
std::mt19937 gen(hash(pixel_index, sample_index, 0));
```

where `hash` is FNV-1a-32 over the three `uint32` inputs. The `0` is the
RNG-offset reserved for the integrator-frontend draws (filter, lens, λ); future
sessions may introduce additional offsets per Cycles' `rng_pixel + rng_offset`
convention (`intern/cycles/kernel/random.h`).

**Consumption order matches production:** filter (u), filter (v), `randomInUnitDisk`,
λ-u01, then the path-trace loop's draws. The schemes differ only in *seeding*;
the draw order within a sample is identical so that the equivalence test
(`SSIM ≥ 0.99 at 64 spp`) can hold.

---

## 3. Two reference PTs (decision §3)

| File | Seeding | Purpose | Test |
|------|---------|---------|------|
| `src/cpu/wavefront/reference_pt_production.{h,cpp}` | tile-shared | Trip-wire against production drift | bit-exact RGB equality at 1 spp |
| `src/cpu/wavefront/reference_pt_wavefront.{h,cpp}` | per-path | Diff oracle for the CPU wavefront | element-by-element SoA equality at 1 spp |

Both expose a callable C++ entry point + a pybind11 binding under names
`reference_pt_production_render` and `reference_pt_wavefront_render`.

**Signature (both):**

```cpp
struct ReferencePTRender {
    std::vector<float> rgb;     // width*height*3
    std::vector<WavefrontSnapshot> snapshots;  // optional, when enabled
};
ReferencePTRender render(
    Renderer& renderer,
    const Camera& cam,
    int samples,
    int max_depth,
    uint64_t seed,
    bool record_snapshots = false);
```

---

## 4. Scoped oracle: Lambertian-Cornell only (decision §4)

Session 2 feature surface:
- Materials: `lambertian` (BSDF) and `light` / `diffuse_light` (emission only).
- Geometry: triangles (no spheres in Cornell; spheres come in session 3).
- Lights: area lights via NEE (the emissive triangle).
- No env map. No GR objects. No SMS hook. No transparency. No volumes.

If the scene contains any unsupported material, the reference PTs must assert
and abort with a clear error rather than silently rendering wrong output. The
trip-wire test scene (`tests/scenes/lambertian_cornell.py`) is the source of
truth for what "in-scope" means in Session 2.

Sessions 3..N grow this surface incrementally. The reference PTs gain new
material branches in the same PR that adds the corresponding CPU wavefront
shade kernel — never lead, never lag.

---

## 5. Callable driver, not a plugin (decision §5)

The CPU wavefront is exposed via:

```cpp
// src/cpu/wavefront/cpu_wavefront_driver.h
namespace astroray::cpu_wavefront {
std::vector<float> render(
    Renderer& renderer, const Camera& cam,
    int samples, int max_depth, uint64_t seed,
    SnapshotSink* sink = nullptr);  // optional snapshot hook
}
```

and a pybind11 binding `cpu_wavefront_render`. No `Integrator` subclass, no
`ASTRORAY_REGISTER_INTEGRATOR`, no Blender dropdown entry. Plugin registration
happens in the final phase of B' once everything works (per spec §"Phase B'
staged plan" item 6).

---

## 6. Reference PT independence (decision §6)

`reference_pt_production` does NOT call `Renderer::pathTraceSpectral` directly
inside the per-bounce loop — it transcribes the loop independently per spec §6
("a separate file ... not instrumentation hooks on production"). The Session 1
summary §6 is explicit on this:

> Both reference PTs are independent transcriptions ... The trip-wire test
> detects drift via bit-comparison.

**Implication.** `reference_pt_production` must reproduce the production
per-bounce loop's RNG consumption *exactly*. For Session 2's lambertian-only
scope this is tractable: the only RNG draws inside `pathTraceSpectral` for a
lambertian-Cornell scene are
- `lights.sample(rec.point, gen)` (1+ draws — depends on lights count + light's `sample` impl),
- `material->sampleSpectral(rec, wo, gen, lambdas)` (Lambertian: 2 draws for
  cosine-weighted hemisphere, via `Vec3::randomInHemisphere` or equivalent),
- `dist01(gen)` for RR (only when `bounce > rrDepth=3`).

These are tracked in `reference_pt_production.cpp` against the production
source in `include/raytracer.h:2055-2205`, with the spec citation in the file
header and a side-by-side comment table inside the loop.

---

## 7. Snapshot schema (decision §7)

`src/cpu/wavefront/wavefront_snapshot.h` defines:

```cpp
namespace astroray::cpu_wavefront {

enum class SnapshotStage : uint8_t {
    PostInit         = 0,  // primary ray generated, RNG seeded, lambda picked, throughput=1
    PostIntersect    = 1,  // BVH hit record written (or miss flag)
    PostShade        = 2,  // outgoing ray + updated throughput (after BSDF sample)
    PostLightSample  = 3,  // NEE shadow ray + light radiance + MIS weight
    PostRR           = 4,  // Russian roulette decision recorded
};

struct WavefrontSnapshot {
    int pixel_index;
    int sample_index;
    int bounce;
    SnapshotStage stage;

    // Ray state (post-init / post-shade).
    float ray_origin[3];
    float ray_direction[3];

    // Throughput + lambda bundle (always present).
    float throughput[4];      // SampledSpectrum
    float lambdas[4];         // SampledWavelengths

    // Hit record (post-intersect onward).
    int   hit_valid;          // 0 = miss
    float hit_t;
    float hit_point[3];
    float hit_normal[3];
    int   hit_material_id;    // -1 if no material

    // Shade output (post-shade only).
    float bsdf_pdf;
    int   bsdf_is_delta;

    // NEE (post-light-sample only).
    float nee_contribution[4];   // weighted L * f for this sample (XYZ-mapped later)
    float nee_light_pdf;
    float nee_bsdf_pdf_at_dir;
    float nee_mis_weight;

    // RR (post-rr only).
    float rr_prob;
    int   rr_survived;
};

class SnapshotSink {
public:
    virtual ~SnapshotSink() = default;
    virtual void record(const WavefrontSnapshot& s) = 0;
};

}  // namespace astroray::cpu_wavefront
```

The CPU wavefront and both reference PTs emit `WavefrontSnapshot` records at
each stage boundary when a sink is attached. The diff harness compares
snapshot streams produced by `reference_pt_wavefront` vs the CPU wavefront
element-by-element. On first mismatch it reports
`{stage, slot_index, field, expected, got}` clearly and exits.

This is **the** instrument that lets us localize divergence to a single field
at a single stage — without it, "the wavefront doesn't match" is unactionable.
Cite: Cycles `intern/cycles/device/cuda/queue.cpp` paranoid-debug pattern
(Apache-2.0) — kernel queues with debug builds dump per-launch state for
the same reason.

---

## 8. Growing-oracle lifecycle (decision §8)

Both reference PTs and the CPU wavefront grow together. The invariants:

1. **Never lead, never lag.** When the CPU wavefront adds metal in session 3,
   both reference PTs add metal in the same PR. Trip-wire test scene grows;
   equivalence test scene grows.
2. **Per-session scope discipline.** Every PR opens with: "this PR adds
   support for X in {ref_prod, ref_wf, cpu_wf}, plus growth to the test
   scenes." If any one of the three lags, the close-gate diff harness will
   catch it (mismatch on the new field/material) — that *is* the gate.
3. **Stage taxonomy is frozen at Session 2.** Five stages defined in §7. New
   shading effects fit inside `PostShade` (they may add new sub-branches but
   never new stages). Stages added in sessions N+1 (shadow / miss / terminate)
   are appended to `SnapshotStage` enum values >= 5, never reordered.
4. **Schema additivity.** New fields appended to `WavefrontSnapshot` only.
   Never reordered, never renamed. Existing tests keep passing because the
   diff harness reads named fields, not byte offsets. (This matches PBRT-v4's
   `workitems.soa` discipline.)

---

## 9. Success criteria for Session 2

Verbatim from spec §"Phase B' acceptance gates":

> **Session 2:** trip-wire test passes (max abs diff = 0); equivalence test
> passes (SSIM ≥ 0.99); CPU wavefront bit-identical to `reference_pt_wavefront`
> on Lambertian-Cornell at 1 spp.

Mapped to tests:
- `tests/test_pkg55_reference_pt_production_parity.py` → trip-wire (`max_abs_diff == 0`).
- `tests/test_pkg55_reference_pt_oracles_equivalent.py` → equivalence (`SSIM ≥ 0.99`).
- `tests/wavefront_diff/test_cpu_wavefront_lambertian_bit_identity.py` → close gate.

---

## 10. File layout (Session 2)

```
src/cpu/wavefront/
    wavefront_snapshot.h          # shared schema (§7)
    reference_pt_production.h     # tile-shared RNG reference
    reference_pt_production.cpp
    reference_pt_wavefront.h      # per-path RNG reference
    reference_pt_wavefront.cpp
    cpu_wavefront_state.h         # SoA layout (mirrors A.1 IntegratorStateSoA)
    cpu_wavefront_driver.cpp      # callable C++ entry point
    stage_init.cpp                # primary ray generation per slot
    stage_intersect.cpp           # BVH traversal per slot
    stage_shade_lambertian.cpp    # Lambertian BSDF + NEE; material-gated

tests/scenes/lambertian_cornell.py
tests/test_pkg55_reference_pt_production_parity.py
tests/test_pkg55_reference_pt_oracles_equivalent.py
tests/wavefront_diff/
    __init__.py
    harness.py
    test_cpu_wavefront_lambertian_bit_identity.py
```

CMakeLists.txt: add `src/cpu/wavefront/*.cpp` to the `astroray` pybind11 module
(unconditional — pure C++, no CUDA, no toggle needed). Add pybind11 bindings
in `module/blender_module.cpp` for the three callable entry points.

---

## 11. Cycles citations (CLAUDE.md §6)

Apache-2.0. We cite, we do not paste.

| Astroray file | Cycles file | What we mirror |
|---|---|---|
| `cpu_wavefront_state.h` | `intern/cycles/kernel/integrator/state.h` | SoA field names; per-stage state flags |
| `stage_init.cpp` | `intern/cycles/kernel/integrator/init_from_camera.h` | Primary-ray generation per slot; RNG seeded by pixel + sample |
| `stage_intersect.cpp` | `intern/cycles/kernel/integrator/intersect_closest.h` | Closest-hit pattern; write hit record to SoA |
| `stage_shade_lambertian.cpp` | `intern/cycles/kernel/integrator/shade_surface.h` | Per-material shade kernel; gated by material type |
| `wavefront_snapshot.h` | `intern/cycles/device/cuda/queue.cpp` | Paranoid-debug per-launch state dump |
| RNG keying | `intern/cycles/kernel/random.h` | `rng_pixel + rng_offset` convention |
| `reference_pt_*.cpp` | (cite production `pathTraceSpectral` + Cycles `kernel_path.h`) | Reference oracle pattern; PBRT-v4 path-tracer integrator structure |

---

## 12. A.1 ray-normalization checklist item (added per pkg55-B-prime-cuda-gate-derivation)

**Critical subtlety (regressed twice — GPU in Phase A.1, CPU in Session 2c pre-shared-kernel):**

Never `Ray ray(origin, direction)` from SoA scalars in a wavefront stage. The `Ray` constructor normalizes `direction`. If you serialize a ray to SoA and then reconstruct it with `Ray(o, d)` from the SoA floats, the constructor re-normalizes and introduces 1-ulp drift relative to an oracle that normalized exactly once.

**Correct pattern (pkg55 spec lines 156–157, Phase A.1):**
```cpp
// WRONG: re-normalizes on every restore
Ray ray(soa.ray_origin[i], soa.ray_direction[i]);

// CORRECT: restore the already-normalized fields verbatim
Ray ray;  // default-construct
ray.origin = soa.ray_origin[i];
ray.direction = soa.ray_direction[i];  // already normalized once
```

The shared-kernel construction (`path_kernel.h/cpp`) already handles this correctly by carrying the live `Ray` object in `PathState` and serializing/restoring its fields verbatim. This checklist item exists to prevent a future session from re-introducing the bug in a new stage (e.g., shadow/miss/terminate).

**Why this matters:** Phase A.1 discovered this on GPU (`GRay` constructor) and documented the fix in the spec. Session 2c's initial CPU skeleton regressed it (pre-shared-kernel `stage_intersect.cpp:43` and `stage_shade_lambertian.cpp:104` both re-constructed `Ray(o,d)` from SoA). The shared-kernel refactor eliminated the bug by construction, but the pattern must be enforced in any future stage that touches ray SoA.

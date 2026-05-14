# pkg55 Phase B' — Session 2a handoff (2026-05-14)

**Status:** 2a complete pending PR merge. 2b/2c open.

**References:**
- Spec: [`.astroray_plan/packages/pkg55-wavefront-soa-refactor.md`](../packages/pkg55-wavefront-soa-refactor.md) §"Phase B' — Restart"
- Design doc: [`.astroray_plan/docs/pkg55-B-cpu-reference-design.md`](pkg55-B-cpu-reference-design.md) (commit `4e2e223`)
- Session 1 summary: [`.astroray_plan/docs/pkg55-B-restart-session1-summary.md`](pkg55-B-restart-session1-summary.md)
- Branch: `pkg55-B-restart`

## Why Session 2 was split

Original Session 2 packaged six deliverables: design doc, scene, snapshot
schema, build wiring, two reference PTs, CPU wavefront skeleton, three
test suites. Implementer flagged the scope before sinking hours; user
approved Option B (split). The bit-identity close gate now lives at 2c.
The split keeps each PR small enough to review properly.

## What 2a delivered

Four small commits, all on `pkg55-B-restart`:

1. **Lambertian Cornell scene** — `tests/scenes/lambertian_cornell.py`.
   6 Lambertian walls + 1 Lambertian sphere + 1 area light. Camera sits
   inside the box (z = +0.95, vfov 60) looking toward −z so the front
   wall is a bounce surface, not a primary-ray occluder. Verified to
   render via `Renderer.set_integrator("path_tracer")` at 1 / 16 / 64 spp
   on the existing CPU `path_tracer` pipeline (mean radiance ~0.19 at
   64 spp, 16×16). This is the in-scope reference scene for 2b/2c.

2. **`WavefrontSnapshot` header** — `src/cpu/wavefront/wavefront_snapshot.h`.
   Schema verbatim from design doc §7. Five `SnapshotStage` values
   (PostInit, PostIntersect, PostShade, PostLightSample, PostRR), all
   fields per the design doc, plus a `SnapshotSink` virtual interface and
   a concrete `VectorSink` impl. Header-only, namespaced
   `astroray::cpu_wavefront`. Verified to compile clean under
   `-std=c++17 -Wall -Wextra`.

3. **CMake scaffolding** — `CMakeLists.txt`. Added a `file(GLOB
   CONFIGURE_DEPENDS …)` over `src/cpu/wavefront/*.cpp` plus a guarded
   `target_sources(astroray_core_impl PRIVATE …)`. Verified: CMake
   configures clean with the glob empty (no message, no .cpp), and
   auto-picks up a probe `.cpp` when added (status message prints, source
   appears in target). 2b's new files will compile without any further
   CMake edits.

4. **Spec + handoff docs** — spec §"Phase B' staged plan" Session 2
   entry rewritten to the 2a/2b/2c split with explicit deliverables and
   close gates per session. Status row updated. This handoff doc landed.

## What 2b needs to do (explicit deliverables, in order)

1. **`src/cpu/wavefront/reference_pt_production.{h,cpp}`** — independent
   transcription of production `Renderer::pathTraceSpectral` per design
   doc §2 (tile-shared RNG, `mt19937(baseSeed + tileIdx)`) and §6
   (separate file, no instrumentation hooks on production). Emit
   `WavefrontSnapshot` records to an attached `SnapshotSink` at each of
   the five stage boundaries. Lambertian-only scope: assert + abort on
   any non-`{lambertian, light}` material. RNG-draw order documented in
   design doc §2.

2. **`src/cpu/wavefront/reference_pt_wavefront.{h,cpp}`** — same physics,
   per-path RNG seeded via `mt19937(hash(pixel_index, sample_index, 0))`
   with FNV-1a-32 over the three uint32 inputs (design doc §2.
   Wavefront-side). Draw order matches production (filter u, filter v,
   `randomInUnitDisk`, λ-u01, …) so the equivalence test can hold.

3. **pybind11 bindings** — `reference_pt_production_render` and
   `reference_pt_wavefront_render` per design doc §3 signature. Add to
   `module/blender_module.cpp` next to the existing test entry points.

4. **Trip-wire test** — `tests/test_pkg55_reference_pt_production_parity.py`.
   Bit-exact RGB equality (`max_abs_diff == 0`) between
   `reference_pt_production_render` and `Renderer.render` at fixed seed,
   1 spp. Uses `tests/scenes/lambertian_cornell.py`.

5. **Equivalence test** — `tests/test_pkg55_reference_pt_oracles_equivalent.py`.
   SSIM ≥ 0.99 at 64 spp between the two reference PTs. Uses the same
   scene. Validates that the per-path RNG scheme is statistically
   equivalent to tile-shared.

**2b close gate:** both tests pass on Windows (the production target).

**2b out of scope:** CPU wavefront stages, diff harness, plugin
registration, CUDA. Those are 2c and beyond.

## What 2c needs to do

1. **CPU wavefront state header** — `src/cpu/wavefront/cpu_wavefront_state.h`.
   SoA layout mirrors A.1 `IntegratorStateSoA` field set (per design doc
   §11 citation table).

2. **Stage kernels (CPU, per-slot loops)** —
   `src/cpu/wavefront/stage_init.cpp`,
   `src/cpu/wavefront/stage_intersect.cpp`,
   `src/cpu/wavefront/stage_shade_lambertian.cpp`. Each emits a
   `WavefrontSnapshot` to the attached sink at its stage boundary.

3. **Callable driver** — `src/cpu/wavefront/cpu_wavefront_driver.cpp` with
   the signature in design doc §5. pybind11 binding
   `cpu_wavefront_render`.

4. **Per-stage diff harness** — `tests/wavefront_diff/harness.py` plus
   `tests/wavefront_diff/test_cpu_wavefront_lambertian_bit_identity.py`.
   Runs `reference_pt_wavefront` and the CPU wavefront on the same seed,
   pulls both snapshot streams, compares slot-by-slot field-by-field, and
   on first mismatch reports `{stage, slot_index, field, expected, got}`.

**2c close gate (== original Session 2 close gate):** bit-identity of
CPU wavefront vs `reference_pt_wavefront` on Lambertian-only Cornell at
1 spp. Zero mismatched fields across the full snapshot stream.

## Design points 2a's design doc clarified that 2b/2c implementers will need to absorb

1. **Spectral end-to-end.** `SampledWavelengths` + `SampledSpectrum`
   carry through every stage. RGB only at final XYZ→sRGB. Design doc §1.
   Implication for 2b: the reference PT signature returns a `vector<float>`
   of RGB but internally is spectral.

2. **Independent transcription of `pathTraceSpectral`, not instrumentation.**
   Design doc §6. Production `Renderer::pathTraceSpectral` is NOT touched.
   The trip-wire detects drift by bit-comparison; if production changes
   semantics, the trip-wire fires, and 2b's reference PT must follow in
   the same PR (growing-oracle lifecycle, §8).

3. **RNG draw order is the spec.** Design doc §2 documents the exact RNG
   draw sequence for both schemes: filter(u), filter(v), randomInUnitDisk,
   λ-u01, then the path-trace loop's draws. Diverging even one draw
   breaks bit-identity, so 2b must mirror production's draw order
   *exactly*.

4. **Lambertian-only scope is enforced at runtime.** Design doc §4. The
   reference PTs and CPU wavefront assert + abort on any non-in-scope
   material. This is what keeps the trip-wire from firing on noise as
   future shade kernels land.

5. **Snapshot schema is append-only.** Design doc §8.4. New fields go on
   the end. New stages go on the end of `SnapshotStage`. Never reorder.
   This is the invariant that lets the diff harness survive across
   sessions.

## Session 2a PR

Title: `feat(pkg55-B'): Phase B' Session 2a — foundation (design + scene + snapshot header + CMake scaffolding)`.

4 commits, <500 LOC total. See PR body for measured numbers.

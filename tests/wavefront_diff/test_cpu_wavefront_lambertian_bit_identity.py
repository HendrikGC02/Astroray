"""pkg55 Phase B' Session 2c — CPU wavefront bit-identity gate.

Close gate: EXACT bit-identity of the CPU wavefront vs reference_pt_wavefront
on Lambertian-only Cornell at 1 spp — zero mismatched fields across the full
snapshot stream, max abs diff EXACTLY 0.0 for floats, exact for ints, at all
5 stage boundaries (PostInit, PostIntersect, PostShade, PostLightSample,
PostRR), slot-by-slot, field-by-field.

Bit-identity here is BY CONSTRUCTION, not by measured tolerance. The
mechanism (architect PR #296 + Codex convergent recommendation, 2026-05-15):

  * ONE shared per-bounce kernel — src/cpu/wavefront/path_kernel.cpp
    init_path() + advance_one_bounce(). reference_pt_wavefront AND the
    cpu_wavefront driver call the EXACT SAME compiled functions. There is
    exactly one generator of the per-bounce arithmetic (intersect -> shade
    Lambertian -> NEE -> RR -> BSDF sample -> ray advance), not two
    transcriptions.

  * LIVE state carried in the SoA, never reconstructed/replayed:
      - the live WavefrontRNG counter (pixel/sample/dimension/seed) carried
        slot-to-slot — no fresh-RNG construction, no hand-counted dimension
        replay (this eliminated the dominant 8.85e-3 nee_light_pdf
        divergence);
      - the full HitRecord carried per slot — shade never re-traces the BVH;
      - the already-normalized ray direction restored verbatim — never
        renormalized at a stage boundary (Phase A.1 ulp-bug fix, re-applied
        on CPU);
      - throughput / lambdas (+pdfs) / radiance accumulator / alive /
        wasSpecular all carried live.

  * The scaffold -ffp-contract=off CMake flag is a DOCUMENTED DEFENSIVE
    GUARD ONLY (both reviews), not the mechanism. It removes -ffast-math
    FMA-fusion as a confound and documents the FP-env precondition (SSE2,
    consistent rounding, no x87 80-bit intermediates, FTZ/DAZ consistent).
    If the shared kernel were duplicated this flag would not save
    bit-identity.

If this test does not show EXACTLY 0.0 / exact-int, there is still a second
computation path — find and eliminate it. Do NOT loosen the gate or
fabricate a pass.

Spec: .astroray_plan/packages/pkg55-wavefront-soa-refactor.md §"Session 2c".
Design: .astroray_plan/docs/pkg55-B-cpu-reference-design.md §9.
"""

import sys
import os
import numpy as np
import astroray

# Add tests/scenes to path.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scenes"))
import lambertian_cornell


def _build_renderer(width, height, seed, max_depth):
    r = astroray.Renderer()
    lambertian_cornell.build_scene(r)
    lambertian_cornell.setup_camera(r, width=width, height=height)
    r.set_seed(seed)
    # path_tracer reads max_depth from its ParamDict at construction; set the
    # param BEFORE set_integrator. Warmup render triggers the BVH build.
    r.set_integrator_param("max_depth", max_depth)
    r.set_integrator("path_tracer")
    _ = r.render(1, 1, None, False)
    return r


def test_cpu_wavefront_lambertian_bit_identity():
    """EXACT bit-identity gate: CPU wavefront == reference_pt_wavefront, 1 spp.

    Spec close gate (pkg55-wavefront-soa-refactor.md:276): snapshot-stream
    equality, slot-by-slot, field-by-field, at the 5 stage boundaries.
    max_abs_diff must be EXACTLY 0.0 and total_diverging_fields EXACTLY 0.
    """
    WIDTH, HEIGHT = 16, 16
    SEED = 424242
    SPP = 1
    MAX_DEPTH = 8

    r = _build_renderer(WIDTH, HEIGHT, SEED, MAX_DEPTH)

    result = astroray.cpu_wavefront_snapshot_diff(
        r, samples=SPP, max_depth=MAX_DEPTH, seed=SEED)

    bit_identical = result["bit_identical"]
    max_abs_diff = result["max_abs_diff"]
    total_diverging_fields = result["total_diverging_fields"]
    report = result["report"]
    ref_img = result["ref_image"]
    wf_img = result["wf_image"]

    print("\n" + report)

    img_diff = np.abs(ref_img - wf_img)
    print(f"\n[Final image diff (informational, not the gate)]")
    print(f"  Max abs diff: {float(img_diff.max()):.2e}, "
          f"mean abs diff: {float(img_diff.mean()):.2e}")

    # Session 2c close gate — EXACT 0.0 / exact-int. Bit-identity is by
    # construction (shared kernel + carried live state); any non-zero is a
    # surviving second computation path, NOT a tolerance to loosen.
    assert total_diverging_fields == 0, (
        f"Bit-identity gate FAILED: {total_diverging_fields} diverging "
        f"field(s); max abs diff {max_abs_diff:.6e}.\n"
        f"With the shared-kernel construction this MUST be 0 — a non-zero "
        f"means a second computation path survives. Find and eliminate it; "
        f"see the per-stage report above. Do NOT loosen the gate.")
    assert max_abs_diff == 0.0, (
        f"Bit-identity gate FAILED: max abs diff is {max_abs_diff!r}, "
        f"expected EXACTLY 0.0. Structural bug — do NOT loosen the gate.")
    assert bit_identical, (
        "Bit-identity gate FAILED: streams not reported bit-identical "
        "despite zero diffs — diff harness inconsistency.")

    print(f"\n[pkg55-Session2c bit-identity gate] PASS: snapshot stream is "
          f"EXACTLY bit-identical (max diff = {max_abs_diff!r}, "
          f"diverging fields = {total_diverging_fields}) — by construction.")


def test_cpu_wavefront_determinism():
    """Determinism: same seed -> byte-identical snapshot stream across two runs.

    The shared kernel + carried live RNG state must be fully deterministic;
    a second run with the same seed must produce a snapshot stream with zero
    divergence against the first.
    """
    WIDTH, HEIGHT = 16, 16
    SEED = 424242
    SPP = 1
    MAX_DEPTH = 8

    r = _build_renderer(WIDTH, HEIGHT, SEED, MAX_DEPTH)

    # Two independent wavefront-vs-oracle diffs at the same seed. Each diff
    # internally runs the wavefront fresh; identical results across the two
    # invocations demonstrate run-to-run determinism of the wavefront.
    a = astroray.cpu_wavefront_snapshot_diff(r, samples=SPP,
                                             max_depth=MAX_DEPTH, seed=SEED)
    b = astroray.cpu_wavefront_snapshot_diff(r, samples=SPP,
                                             max_depth=MAX_DEPTH, seed=SEED)

    assert np.array_equal(a["wf_image"], b["wf_image"]), (
        "Determinism FAILED: two same-seed wavefront renders differ.")
    assert a["max_abs_diff"] == b["max_abs_diff"] == 0.0, (
        f"Determinism/identity FAILED: run A max diff {a['max_abs_diff']!r}, "
        f"run B max diff {b['max_abs_diff']!r}; both must be exactly 0.0.")

    print("\n[pkg55-Session2c determinism] PASS: same-seed wavefront renders "
          "are byte-identical and both exactly bit-identical to the oracle.")

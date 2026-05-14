"""pkg55 Phase B' Session 2b — trip-wire test for reference_pt_production parity.

Bit-exact RGB equality between reference_pt_production_render and production
Renderer.render at fixed seed, 1 spp. Uses the Lambertian-Cornell test scene.

This is the trip-wire: if production pathTraceSpectral changes semantics
(intentionally or accidentally), this test will fire, and the reference PT
must be updated in the same PR (growing-oracle lifecycle).

Spec: .astroray_plan/packages/pkg55-wavefront-soa-refactor.md §"Phase B'".
Design: .astroray_plan/docs/pkg55-B-cpu-reference-design.md §3, §9.
"""

import pytest
import sys
import os
import numpy as np
import astroray

# Add tests/scenes to path so we can import lambertian_cornell.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "scenes"))
import lambertian_cornell


def test_reference_pt_production_parity():
    """Trip-wire: reference_pt_production_render == Renderer.render (bit-exact)."""
    WIDTH, HEIGHT = 16, 16
    SEED = 424242
    SPP = 1
    MAX_DEPTH = 8

    # Build Lambertian Cornell scene.
    r = astroray.Renderer()
    lambertian_cornell.build_scene(r)
    lambertian_cornell.setup_camera(r, width=WIDTH, height=HEIGHT)
    r.set_seed(SEED)
    r.set_integrator("path_tracer")

    # Production render via Renderer.render.
    prod_img = r.render(samples_per_pixel=SPP, max_depth=MAX_DEPTH,
                        apply_gamma=False)  # keep linear RGB

    # Reference PT render via reference_pt_production_render.
    ref_img = astroray.reference_pt_production_render(
        r, samples=SPP, max_depth=MAX_DEPTH, seed=SEED, record_snapshots=False)

    # Both should be (HEIGHT, WIDTH, 3) float32.
    assert prod_img.shape == (HEIGHT, WIDTH, 3), \
        f"Production image shape {prod_img.shape} != expected ({HEIGHT},{WIDTH},3)"
    assert ref_img.shape == (HEIGHT, WIDTH, 3), \
        f"Reference image shape {ref_img.shape} != expected ({HEIGHT},{WIDTH},3)"

    # Bit-exact comparison (max absolute difference = 0).
    diff = np.abs(prod_img - ref_img)
    max_diff = diff.max()
    if max_diff > 0:
        # Report first mismatch for debugging.
        mismatch = np.unravel_index(diff.argmax(), diff.shape)
        y, x, c = mismatch
        prod_val = prod_img[y, x, c]
        ref_val = ref_img[y, x, c]
        print(f"\n[pkg55-Session2b trip-wire] First mismatch at pixel ({x},{y}) channel {c}:")
        print(f"  Production: {prod_val}")
        print(f"  Reference:  {ref_val}")
        print(f"  Diff:       {diff[y,x,c]}")

    assert max_diff == 0, \
        f"Trip-wire FAILED: max abs diff = {max_diff}. " \
        f"Production pathTraceSpectral diverged from reference_pt_production. " \
        f"Update reference_pt_production.cpp in the same PR (growing-oracle rule)."

    print(f"[pkg55-Session2b trip-wire] PASS: production == reference_pt_production "
          f"at {SPP} spp (max diff = {max_diff})")

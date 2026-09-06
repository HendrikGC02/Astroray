"""pkg253 G1 - shadow-ray transparency for Principled `alpha`.

Ground-truth check before this package started: pkg178 (PR #575, "Principled
alpha as a delta transparent lobe") already gives `alpha` a full CPU+GPU
implementation for BSDF sampling/eval -- see tests/test_pkg178_alpha.py, all
green on main. What pkg178 did NOT touch is the direct NEE shadow-ray test:
include/raytracer.h's `pathTraceSpectral` / `pathTraceSpectralCaustic` did a
purely geometric `bvh->hit(...)` occlusion test with no query of the hit
material at all, so an alpha=0 (fully transparent) Principled surface still
fully blocked the FIRST-hit shadow ray to the light -- a real behavioural gap
vs Cycles' "Transparent Shadows" (an Alpha<1 surface lets (1-alpha) of a
shadow ray's light through instead of unconditionally blocking it), and the
literal gap named in the pkg253 spec (G1 acceptance: "alpha 0 must cast no
shadow").

Isolating this from an ALREADY-WORKING effect: at depth>=3 a diffuse
continuation ray can bounce off the receiver, hit the (alpha<1) occluder as
its OWN vertex, sample the delta transparent lobe there (pkg178 PR-6,
unaffected by this package), and reach the light through it -- a legitimate
*indirect* path that pre-pkg253 already renders correctly. That pathway
would contaminate a naive full-frame brightness comparison at any nontrivial
depth. Every test below uses `depth=1` (receiver hit -> NEE only, no
continuation ray is traced far enough to reach the light) so the measured
delta is attributable ONLY to the direct-NEE shadow-ray fix. Verified by
hand before writing these assertions: at depth=1 on pre-fix `main`, an
alpha=0 occluder darkens the receiver exactly as much as alpha=1 (both
0.2477 in the debug scene) -- proving the bug is real and depth=1 isolates
it; at depth=3 pre-fix, alpha=0 already recovers ~97% of the unoccluded
brightness via the indirect pathway above, which is why depth must be capped
here.

Fix: `Material::shadowAlpha(rec)` (include/raytracer.h, default 1.0 = fully
opaque, unchanged for every material but Principled) is queried at the
shadow-ray hit; the NEE contribution is scaled by `1 - shadowAlpha` instead
of being unconditionally zeroed. `PrincipledMaterial::shadowAlpha` returns
`alpha_` -- the same value the camera-ray delta-transparent lobe already
uses (pkg178 PR-6). Safety property (matching the PR-6 pattern): every
non-Principled material's default `shadowAlpha()==1.0`, and Principled at
alpha=1 also returns 1.0, so `shadowTransmittance` is provably 1.0 or 0.0
exactly as before construction -- every pre-pkg253 render is byte-unaffected.
Scope: SINGLE-occluder attenuation (the shadow ray tests one hit, not a
multi-bounce transparent-shadow chain through several stacked cutouts --
named non-goal, see the pkg253 spec, G1 acceptance).
"""
import numpy as np
import pytest
from runtime_setup import configure_test_imports

configure_test_imports()

try:
    import astroray
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray module not available")


def _render_shadow_scene(occluder_alpha, *, occ_x=0.0, spp=160, depth=1, seed=17,
                         size=48, integrator="path_tracer", use_gpu=False,
                         opaque_backplate=False):
    """A large horizontal receiver lit by a small area light directly above
    (through an optional horizontal occluder quad between them), viewed from
    a low, narrow-FOV, grazing camera angle so the occluder and light are
    OUTSIDE the frustum -- only the occluder's SHADOW on the receiver is ever
    camera-visible. occluder_alpha=None omits the occluder (no-shadow
    control); occ_x shifts the occluder off the light's vertical axis (used
    to prove the occluder has zero effect when it isn't in the shadow path).

    integrator selects the integrator plugin (the shadow-transmittance helper
    is shared across path_tracer / wavefront_path_tracer /
    multiwavelength_path_tracer). use_gpu=True runs the CUDA wavefront pipeline
    (stage_light_sample.cu single-hit attenuation). opaque_backplate=True adds
    a fully-opaque (default-alpha) plate at y=3 -- BEHIND the y=2 occluder along
    the receiver->light shadow ray -- so a transparent front occluder must not
    stop the re-trace: the loop has to reach the opaque plate and fully
    shadow the receiver (pkg253 two-occluder / bounded re-trace case)."""
    r = astroray.Renderer()
    r.set_background_color([0.0, 0.0, 0.0])
    r.set_integrator(integrator)
    if use_gpu:
        r.set_use_gpu(True)

    light = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 120.0})
    # Position (0,4,0), right=(1,0,0), up=(0,0,1) -> normal = right x up =
    # (0,-1,0): emits straight down (add_area_light convention, matches
    # tests/test_python_bindings.py).
    r.add_area_light([0, 4, 0], [1, 0, 0], [0, 0, 1], 1.0, 1.0, "RECTANGLE", light, 1.0)

    receiver = r.create_material("lambertian", [0.8, 0.8, 0.8], {})
    e = 6.0
    # Winding gives normal = (v1-v0) x (v2-v0) = +Y, facing the light/camera.
    r.add_triangle([-e, 0, -e], [e, 0, e], [e, 0, -e], receiver)
    r.add_triangle([-e, 0, -e], [-e, 0, e], [e, 0, e], receiver)

    if occluder_alpha is not None:
        occluder = r.create_material(
            "principled", [0.05, 0.05, 0.05],
            {"alpha": occluder_alpha, "roughness": 1.0})
        oe = 1.0
        r.add_triangle([occ_x - oe, 2, -oe], [occ_x + oe, 2, oe], [occ_x + oe, 2, -oe], occluder)
        r.add_triangle([occ_x - oe, 2, -oe], [occ_x - oe, 2, oe], [occ_x + oe, 2, oe], occluder)

        if opaque_backplate:
            # Fully-opaque plate (default alpha=1.0) at y=3, behind the y=2
            # occluder on the receiver->light shadow ray. A single-hit
            # attenuation would let (1-alpha) through the y=2 occluder; only a
            # bounded re-trace reaches this plate and fully shadows the receiver.
            back = r.create_material("principled", [0.05, 0.05, 0.05], {"roughness": 1.0})
            be = 1.0
            r.add_triangle([occ_x - be, 3, -be], [occ_x + be, 3, be], [occ_x + be, 3, -be], back)
            r.add_triangle([occ_x - be, 3, -be], [occ_x - be, 3, be], [occ_x + be, 3, be], back)

    # Low, narrow-FOV, near-grazing view of the receiver near the origin --
    # both the light (y=4) and the occluder (y=2) sit well outside this
    # frustum (verified empirically: shifting the occluder off-axis to
    # occ_x=6 renders byte-identical to no occluder at all).
    r.setup_camera([9, 0.4, 0], [0, 0, 0], [0, 1, 0], 8.0, 1.0, 0.0, 9.0, size, size)
    r.set_seed(seed)
    img = np.asarray(r.render(spp, depth, None, False), dtype=np.float32).reshape(size, size, 3)
    return img


def _mean_lum(img):
    return float(img.mean())


# ---------------------------------------------------------------------------
# 0. Sanity: the occluder is genuinely OUT of camera view -- shifting it off
#    the light's axis must have zero effect (the camera never sees it
#    directly; only its shadow, if any, could change the render).
# ---------------------------------------------------------------------------

def test_occluder_is_outside_camera_frustum():
    no_occ = _render_shadow_scene(None, seed=5)
    offside = _render_shadow_scene(1.0, occ_x=6.0, seed=5)
    assert np.array_equal(no_occ, offside), (
        "an occluder shifted off the light's shadow axis must render "
        "bit-identical to no occluder -- test scene assumption violated "
        "(the camera can see the occluder directly)")


# ---------------------------------------------------------------------------
# 1. Sanity: the occluder at alpha=1 (opaque) actually darkens the receiver
#    relative to no occluder -- proves the test scene is shadow-sensitive.
# ---------------------------------------------------------------------------

def test_scene_is_shadow_sensitive_at_opaque_alpha():
    no_occ = _mean_lum(_render_shadow_scene(None))
    opaque = _mean_lum(_render_shadow_scene(1.0))
    assert opaque < no_occ * 0.85, (
        f"opaque occluder ({opaque:.4f}) should be meaningfully darker than "
        f"no occluder ({no_occ:.4f}) -- scene isn't shadow-sensitive")


# ---------------------------------------------------------------------------
# 2. THE fix: alpha=0 casts no shadow -- at depth=1 (direct NEE only) the
#    receiver brightness with a fully transparent occluder must match the
#    no-occluder control.
# ---------------------------------------------------------------------------

def test_alpha0_occluder_casts_no_shadow():
    no_occ = _mean_lum(_render_shadow_scene(None, seed=17))
    transparent = _mean_lum(_render_shadow_scene(0.0, seed=17))
    assert transparent > no_occ * 0.92, (
        f"alpha=0 occluder ({transparent:.4f}) should match the unoccluded "
        f"control ({no_occ:.4f}) -- a fully transparent surface must not "
        f"cast a shadow")


# ---------------------------------------------------------------------------
# 3. Monotone in alpha: more opaque -> darker receiver.
# ---------------------------------------------------------------------------

def test_shadow_darkness_monotone_in_alpha():
    c0 = _mean_lum(_render_shadow_scene(0.0, seed=23))
    c05 = _mean_lum(_render_shadow_scene(0.5, seed=23))
    c1 = _mean_lum(_render_shadow_scene(1.0, seed=23))
    assert c0 > c05 > c1, (
        f"receiver brightness not monotone in occluder alpha: "
        f"c0={c0:.4f} c05={c05:.4f} c1={c1:.4f}")


# ---------------------------------------------------------------------------
# 4. Safety: alpha=1 shadow darkness matches the pre-pkg253 (default-alpha)
#    Principled occluder -- the fix must not perturb existing opaque-shadow
#    behaviour (Material::shadowAlpha defaults to 1.0 for every material).
# ---------------------------------------------------------------------------

def test_alpha1_shadow_matches_default_principled_occluder():
    r = astroray.Renderer()
    r.set_background_color([0.0, 0.0, 0.0])
    r.set_integrator("path_tracer")
    light = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 120.0})
    r.add_area_light([0, 4, 0], [1, 0, 0], [0, 0, 1], 1.0, 1.0, "RECTANGLE", light, 1.0)
    receiver = r.create_material("lambertian", [0.8, 0.8, 0.8], {})
    e = 6.0
    r.add_triangle([-e, 0, -e], [e, 0, e], [e, 0, -e], receiver)
    r.add_triangle([-e, 0, -e], [-e, 0, e], [e, 0, e], receiver)
    # No 'alpha' key at all -> PrincipledMaterial defaults alpha_=1.0.
    occluder_default = r.create_material("principled", [0.05, 0.05, 0.05], {"roughness": 1.0})
    oe = 1.0
    r.add_triangle([-oe, 2, -oe], [oe, 2, oe], [oe, 2, -oe], occluder_default)
    r.add_triangle([-oe, 2, -oe], [-oe, 2, oe], [oe, 2, oe], occluder_default)
    r.setup_camera([9, 0.4, 0], [0, 0, 0], [0, 1, 0], 8.0, 1.0, 0.0, 9.0, 48, 48)
    r.set_seed(17)
    img_default = np.asarray(r.render(160, 1, None, False), dtype=np.float32).reshape(48, 48, 3)

    img_alpha1 = _render_shadow_scene(1.0, seed=17)
    assert np.array_equal(img_default, img_alpha1), (
        "explicit alpha=1.0 must render bit-identical to the default "
        "(no 'alpha' key) Principled occluder -- the shadow-ray fix must "
        "not change opaque-material behaviour")


# ---------------------------------------------------------------------------
# 5. Bounded re-trace (two-occluder): a transparent (alpha=0.5) occluder
#    standing in FRONT of an opaque plate must NOT let the receiver escape the
#    shadow -- the shared shadowTransmittance re-trace loop has to continue
#    past the transparent hit, find the opaque plate behind it, and fully
#    shadow the receiver. A single-hit attenuation would wrongly leave the
#    receiver at ~50% brightness. Reference: Cycles integrate_transparent_shadow
#    (intern/cycles/kernel/integrator/shade_shadow.h) accumulates transparency
#    across ALL recorded shadow intersections, not just the nearest.
# ---------------------------------------------------------------------------

def test_transparent_in_front_of_opaque_is_fully_shadowed():
    opaque_single = _mean_lum(_render_shadow_scene(1.0, seed=31))
    half_single = _mean_lum(_render_shadow_scene(0.5, seed=31))
    two_occ = _mean_lum(_render_shadow_scene(0.5, opaque_backplate=True, seed=31))
    # The opaque plate behind the alpha=0.5 occluder must fully shadow the
    # receiver: two-occluder brightness matches the single-opaque shadow, and
    # is clearly darker than the alpha=0.5-only shadow (proving the re-trace
    # reached the plate rather than stopping at the transparent hit).
    assert two_occ < half_single * 0.9, (
        f"transparent-in-front-of-opaque ({two_occ:.4f}) must be much darker "
        f"than the alpha=0.5-only shadow ({half_single:.4f}) -- the re-trace "
        f"loop failed to reach the opaque plate behind the transparent quad")
    assert two_occ < opaque_single * 1.05, (
        f"transparent-in-front-of-opaque ({two_occ:.4f}) should be as dark as "
        f"the single opaque occluder ({opaque_single:.4f}) -- fully shadowed")


# ---------------------------------------------------------------------------
# 6. Cross-integrator parity: the shared helper is wired into the CPU
#    wavefront kernel (path_kernel.cpp / reference_pt_production.cpp) and the
#    multiwavelength tracer, so alpha=0 must cast no shadow there too.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("integrator",
                         ["wavefront_path_tracer", "multiwavelength_path_tracer"])
def test_alpha0_casts_no_shadow_other_integrators(integrator):
    no_occ = _mean_lum(_render_shadow_scene(None, seed=17, integrator=integrator))
    transparent = _mean_lum(_render_shadow_scene(0.0, seed=17, integrator=integrator))
    assert transparent > no_occ * 0.92, (
        f"[{integrator}] alpha=0 occluder ({transparent:.4f}) should match the "
        f"unoccluded control ({no_occ:.4f}) -- a fully transparent surface "
        f"must not cast a shadow")


# ---------------------------------------------------------------------------
# 7. GPU twin (skips without CUDA): stage_light_sample.cu attenuates the light
#    sample by (1-alpha) of the shadow-ray occluder's uploaded material alpha.
#    Single-hit scope on GPU (no re-trace in that stage -- see the .cu header),
#    so this only asserts the alpha=0 no-shadow property, not the two-occluder
#    case.
# ---------------------------------------------------------------------------

@pytest.mark.gpu
def test_alpha0_casts_no_shadow_gpu():
    probe = astroray.Renderer()
    if not probe.gpu_available:
        pytest.skip("CUDA GPU not available")
    no_occ = _mean_lum(_render_shadow_scene(None, seed=17, use_gpu=True))
    transparent = _mean_lum(_render_shadow_scene(0.0, seed=17, use_gpu=True))
    assert transparent > no_occ * 0.90, (
        f"[gpu] alpha=0 occluder ({transparent:.4f}) should match the "
        f"unoccluded control ({no_occ:.4f}) -- a fully transparent surface "
        f"must not cast a shadow on the CUDA wavefront path")

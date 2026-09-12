"""#776 — textured mesh emitters must be evaluated at the sampled light point in
NEE / light-tree, not read as a flat getEmission().

Before #776, `TexturedLight::getEmission()` returned `Vec3(intensity)` (flat
WHITE x intensity) regardless of the emission texture, so the NEE / light-tree
path lit surfaces flat white while BSDF-sampled hits saw the texture colour —
MIS combined two different integrands. This suite builds a RED-textured
emissive plane over a white diffuse floor and asserts:

1. NEE-on lights the floor with the emitter's colour (R >> B), not flat white
   (the exact bug — flat white would give R ≈ B on a neutral floor).
2. Under NEE a red-*textured* emitter lights the floor the same colour as an
   equivalent plain red light (base red, no texture) — #776 makes the NEE path
   evaluate the emission texture at the sampled point (was flat white).
3. GPU: the emitter's texture MEAN (red), not white, is uploaded
   (scene_upload.cu getEmission()); the GPU floor is red-tinted too.

Uses the CPU MultiwavelengthPathTracer, whose `enable_nee` param toggles NEE.
"""
import numpy as np
import pytest


@pytest.fixture(scope="module")
def astroray_mod():
    try:
        import astroray
        return astroray
    except ImportError as e:
        pytest.skip(f"astroray module not available: {e}")


def _floor_scene(r, flat_colour=False):
    """White floor lit only by a downward-facing RED mesh emitter.

    flat_colour=False: emitter is a RED *texture* on a white-base light material
    (the #776 subject). flat_colour=True: an equivalent plain RED light material
    (base colour red, no texture) -- the reference the textured emitter must now
    match under NEE (pre-#776 the textured one lit flat white).
    """
    white = r.create_material("lambertian", [0.8, 0.8, 0.8], {})
    if flat_colour:
        red_light = r.create_material("light", [1.0, 0.0, 0.0],
                                      {"intensity": 15.0})
    else:
        red_img = np.tile(np.array([1.0, 0.0, 0.0], dtype=np.float32), (4, 4, 1))
        r.load_texture("emit_red", red_img, 4, 4, "UV")
        red_light = r.create_material("light", [1.0, 1.0, 1.0],
                                      {"intensity": 15.0, "texture": "emit_red"})
    e = 4.0
    r.add_triangle([-e, -1, -e], [e, -1, -e], [e, -1, e], white)
    r.add_triangle([-e, -1, -e], [e, -1, e], [-e, -1, e], white)
    # Emitter quad at y=+1.5 facing DOWN (geometric normal -y) so its front
    # face illuminates the floor below. emitted()/emittedSpectral() return 0 on
    # the back face, so the opposite winding leaves the floor lit only by
    # ambient (verified 2026-09-13: this winding -> R=2.5, that one -> R=0.07).
    le = 1.2
    r.add_triangle([-le, 1.5, -le], [le, 1.5, -le], [le, 1.5, le], red_light)
    r.add_triangle([-le, 1.5, -le], [le, 1.5, le], [-le, 1.5, le], red_light)


def _render_floor_mean(mod, enable_nee, samples=64, gpu=False, flat_colour=False):
    r = mod.Renderer()
    if gpu:
        r.set_integrator("path_tracer")
        r.set_use_gpu(True)
    else:
        r.set_integrator_param("enable_nee", 1 if enable_nee else 0)
        r.set_integrator("multiwavelength_path_tracer")
    _floor_scene(r, flat_colour=flat_colour)
    r.setup_camera(look_from=[0, 0.5, 0.01], look_at=[0, -1, 0], vup=[0, 0, -1],
                   vfov=50, aspect_ratio=1.0, aperture=0.0, focus_dist=2.0,
                   width=96, height=96)
    px = r.render(samples, 6, None, False)  # linear
    px = np.asarray(px).reshape(96, 96, 3)
    # central floor patch
    c = px[36:60, 36:60].reshape(-1, 3)
    return c.mean(axis=0)


@pytest.mark.cpu
def test_nee_uses_emitter_texture_colour(astroray_mod):
    """NEE-on lights the floor RED (the emitter texture colour), not flat white.
    Flat-white NEE (pre-#776) would give R ~= B on the neutral floor."""
    m = _render_floor_mean(astroray_mod, enable_nee=True, samples=96)
    assert m[0] > 1e-4, f"floor is black, emitter not sampled: {m}"
    assert m[0] > 3.0 * (m[2] + 1e-6), f"floor not red-tinted (flat-white NEE?): {m}"


@pytest.mark.cpu
def test_textured_emitter_matches_flat_colour_under_nee(astroray_mod):
    """#776: under NEE a RED-*textured* emitter (white base) must light the floor
    identically to an equivalent plain RED light (base red, no texture), because
    NEE now evaluates the emission texture at the sampled light point. Pre-#776
    the textured emitter's NEE path saw a flat getEmission() == white x intensity,
    so it lit the floor WHITE while the plain red light lit it RED -- the two
    diverged. (NEE-off is not a valid cross-check here: the
    multiwavelength tracer's naive mode is the pkg156 naive oracle
    (multiwavelength_path_tracer.cpp ~266-286) — emission is taken only on a
    camera / post-specular ray and intentionally dropped on a non-specular
    diffuse hit, so with enable_nee=0 the mesh emitter contributes nothing. That
    is the intended oracle contract, not a bug and unrelated to #776.)"""
    tex = _render_floor_mean(astroray_mod, enable_nee=True, samples=256)
    flat = _render_floor_mean(astroray_mod, enable_nee=True, samples=256,
                              flat_colour=True)
    # both must be strongly red-dominated (the emitter, not ambient)
    assert tex[0] > 3.0 * tex[2] and flat[0] > 3.0 * flat[2], (tex, flat)
    # per-channel agreement within Monte-Carlo noise
    for ch in range(3):
        denom = max(tex[ch], flat[ch], 1e-3)
        assert abs(tex[ch] - flat[ch]) / denom < 0.20, (ch, tex, flat)


@pytest.mark.gpu
def test_gpu_uploads_texture_mean_not_white(astroray_mod):
    """scene_upload.cu uploads getEmission() == texture MEAN (red), not flat
    white (#776). The GPU floor must be red-tinted."""
    m = _render_floor_mean(astroray_mod, enable_nee=True, samples=64, gpu=True)
    assert m[0] > 1e-4, f"GPU floor black: {m}"
    assert m[0] > 3.0 * (m[2] + 1e-6), f"GPU floor not red (white mean uploaded?): {m}"

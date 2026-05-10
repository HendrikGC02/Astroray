"""Tests for pkg73: OptiX TEMPORAL_AOV denoiser mode.

Skips cleanly when OptiX is not compiled in or no CUDA device is visible
at runtime — most CI machines. When OptiX IS available, exercises the
four acceptance scenarios from
.astroray_plan/packages/pkg73-optix-temporal-denoiser.md:

  1. Mode-selection log line: TEMPORAL_AOV is entered on the first frame
     with non-zero motion (verified via captured stdout, mirroring pkg68's
     `[OptiX] Using ...` capture pattern).
  2. Inter-frame variance gate: a camera-pan sequence with the temporal
     mode shows ≥ 30 % less inter-frame pixel variance than a matched
     pkg70 AOV-mode run.
  3. First-frame correctness: with `prev_valid_ == False`, the denoiser
     produces finite output.
  4. Resize invalidates state: changing resolution between frames does
     not crash and the next frame is treated as a first frame.

OptiX SDK + CUDA hardware verification of these tests is pending — they
are written so a verifier session can run them as-is.
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

OPTIX_BUILD = AVAILABLE and bool(
    astroray.__features__.get("optix_denoiser", False) if AVAILABLE else False
)


def _optix_runtime_available() -> bool:
    if not OPTIX_BUILD:
        return False
    try:
        return bool(astroray.gpu_optix_available())
    except Exception:
        return False


OPTIX_AVAILABLE = _optix_runtime_available()


# --- Scene helpers ---------------------------------------------------------

W, H = 96, 96
SAMPLES = 2
DEPTH = 3


def _scene(width: int = W, height: int = H, look_from=(0.0, 0.0, 5.5)):
    """Small Cornell-style scene matching pkg70 tests, but parameterised on
    camera position so we can drive a pan."""
    r = astroray.Renderer()
    r.setup_camera(
        look_from=list(look_from), look_at=[0.0, 0.0, 0.0], vup=[0.0, 1.0, 0.0],
        vfov=40.0, aspect_ratio=width / height, aperture=0.0, focus_dist=5.5,
        width=width, height=height,
    )
    r.set_background_color([0.0, 0.0, 0.0])
    white = r.create_material("lambertian", [0.73, 0.73, 0.73], {})
    red   = r.create_material("lambertian", [0.65, 0.05, 0.05], {})
    light = r.create_material("light",      [1.0, 0.9, 0.8],    {"intensity": 15.0})
    r.add_triangle([-2, -2, -2], [ 2, -2, -2], [ 2, -2,  2], white)
    r.add_triangle([-2, -2, -2], [ 2, -2,  2], [-2, -2,  2], white)
    r.add_triangle([-2, -2, -2], [-2, -2,  2], [-2,  2,  2], red)
    r.add_triangle([-2, -2, -2], [-2,  2,  2], [-2,  2, -2], red)
    r.add_triangle([-0.5, 1.98, -0.5], [0.5, 1.98, -0.5], [0.5, 1.98,  0.5], light)
    r.add_triangle([-0.5, 1.98, -0.5], [0.5, 1.98,  0.5], [-0.5, 1.98, 0.5], light)
    r.add_sphere([0, -1.0, 0], 1.0, white)
    return r


def _pan_camera(r, x: float):
    r.setup_camera(
        look_from=[x, 0.0, 5.5], look_at=[0.0, 0.0, 0.0], vup=[0.0, 1.0, 0.0],
        vfov=40.0, aspect_ratio=W / H, aperture=0.0, focus_dist=5.5,
        width=W, height=H,
    )


# --- Tests -----------------------------------------------------------------


@pytest.mark.skipif(not OPTIX_BUILD, reason="OptiX denoiser not compiled in")
def test_optix_pass_registered_when_compiled_in():
    assert "optix_denoiser" in astroray.pass_registry_names()


@pytest.mark.skipif(not OPTIX_AVAILABLE,
                    reason="OptiX denoiser unavailable at runtime (SDK or CUDA missing)")
def test_temporal_mode_entered_when_motion_present(capfd):
    """Frame 1 has zero motion (no prev camera) -> AOV. Frame 2 after a
    pan has non-zero motion -> denoiser should transition to TEMPORAL_AOV.
    The plugin prints a 'kind=2' (== TEMPORAL_AOV) line on transition."""
    r = _scene()
    r.set_seed(1)
    r.add_pass("optix_denoiser")

    capfd.readouterr()
    r.render(samples_per_pixel=SAMPLES, max_depth=DEPTH)  # frame 1: zero motion -> AOV
    _pan_camera(r, 0.4)
    r.render(samples_per_pixel=SAMPLES, max_depth=DEPTH)  # frame 2: motion -> TEMPORAL_AOV
    captured = capfd.readouterr()
    out = captured.out + captured.err

    assert "TEMPORAL_AOV" in out, (
        f"Expected TEMPORAL_AOV transition log line. Captured:\n{out}"
    )


@pytest.mark.skipif(not OPTIX_AVAILABLE,
                    reason="OptiX denoiser unavailable at runtime (SDK or CUDA missing)")
def test_first_frame_finite_output():
    """First frame after add_pass: prev_valid_ is False, denoiser falls back
    to feeding the noisy beauty as previousOutput. Output must be finite."""
    r = _scene()
    r.set_seed(2)
    r.add_pass("optix_denoiser")
    img = np.array(r.render(samples_per_pixel=SAMPLES, max_depth=DEPTH),
                   dtype=np.float32)
    assert img.shape == (H, W, 3)
    assert np.all(np.isfinite(img))
    assert np.all(img >= 0.0)


@pytest.mark.skipif(not OPTIX_AVAILABLE,
                    reason="OptiX denoiser unavailable at runtime (SDK or CUDA missing)")
def test_resize_does_not_crash():
    """Mid-stream resolution change must invalidate prev-output and produce
    finite output (pkg73 acceptance: 'no crash; the denoiser handle and
    previous-output buffers are reallocated')."""
    r = _scene(width=64, height=64)
    r.set_seed(3)
    r.add_pass("optix_denoiser")
    r.render(samples_per_pixel=SAMPLES, max_depth=DEPTH)
    _pan_camera(r, 0.3)  # introduce motion
    r.render(samples_per_pixel=SAMPLES, max_depth=DEPTH)

    # Now resize.
    r.setup_camera(
        look_from=[0.0, 0.0, 5.5], look_at=[0.0, 0.0, 0.0], vup=[0.0, 1.0, 0.0],
        vfov=40.0, aspect_ratio=1.0, aperture=0.0, focus_dist=5.5,
        width=128, height=128,
    )
    img = np.array(r.render(samples_per_pixel=SAMPLES, max_depth=DEPTH),
                   dtype=np.float32)
    assert img.shape == (128, 128, 3)
    assert np.all(np.isfinite(img))


def _pan_sequence(r, n_frames=10, dx_per_frame=0.05):
    """Render n_frames with the camera panning right by `dx_per_frame` each
    frame. Returns a (n, H, W, 3) float32 array."""
    frames = []
    # Frame 0: no pan applied yet, so motion is zero (matches pkg72 first-frame).
    img0 = np.array(r.render(samples_per_pixel=SAMPLES, max_depth=DEPTH),
                    dtype=np.float32)
    frames.append(img0)
    for i in range(1, n_frames):
        _pan_camera(r, dx_per_frame * i)
        frames.append(np.array(r.render(samples_per_pixel=SAMPLES, max_depth=DEPTH),
                               dtype=np.float32))
    return np.stack(frames, axis=0)


@pytest.mark.skipif(not OPTIX_AVAILABLE,
                    reason="OptiX denoiser unavailable at runtime (SDK or CUDA missing)")
def test_inter_frame_variance_reduction():
    """pkg73 acceptance gate: TEMPORAL_AOV reduces inter-frame pixel variance
    by ≥ 30 % vs pkg70 AOV mode on the same camera-pan sequence.

    The plugin always picks TEMPORAL_AOV when motion is non-zero, so to
    isolate the two modes we construct two passes: the temporal run does
    the full pan; the AOV-mode reference holds the camera static between
    frames so motion stays zero (which keeps the plugin in AOV mode).
    Both runs use the same RNG seed and the same per-frame integrator
    samples, so any variance delta is the temporal accumulation, not
    sampling noise.
    """
    n_frames = 10
    dx = 0.04

    # Temporal run.
    r_t = _scene()
    r_t.set_seed(42)
    r_t.add_pass("optix_denoiser")
    seq_t = _pan_sequence(r_t, n_frames=n_frames, dx_per_frame=dx)

    # AOV reference: same camera positions, but force the plugin to stay
    # in AOV mode by rendering each frame on a fresh Renderer. With no
    # prior render on the renderer, hasPrevCamera is false, the motion
    # buffer stays exactly zero-filled, and the plugin selects AOV (not
    # TEMPORAL_AOV). The earlier "render twice and discard the first"
    # trick was unsound: even with prev == curr camera, projectToPrevPixel
    # produces sub-pixel floating-point dust (~1e-5) which trips the
    # plugin's `srcMotion[i] != 0.0f` gate and silently upgrades the
    # reference run to TEMPORAL_AOV — leaving rms_t == rms_a regardless
    # of how well temporal mode is working. (pkg73 defect-2026-05-10.)
    # Per-frame seed advances independent noise, mirroring the natural RNG
    # advancement of the temporal leg (one renderer + 10 sequential renders
    # = 10 distinct noise realisations). A constant seed across fresh
    # renderers would correlate the noise pattern frame-to-frame, which
    # would cancel in the diff and artificially deflate rms_a.
    seq_a = []
    for i in range(n_frames):
        pose_x = dx * i
        r_a = _scene(look_from=(pose_x, 0.0, 5.5))
        r_a.set_seed(42 + i * 9973)
        r_a.add_pass("optix_denoiser")
        seq_a.append(np.array(r_a.render(samples_per_pixel=SAMPLES, max_depth=DEPTH),
                              dtype=np.float32))
    seq_a = np.stack(seq_a, axis=0)

    # Inter-frame variance over the central frames (skip frame 0 = no prev).
    # For a panning sequence the per-pixel time-series is non-stationary,
    # so we measure first-difference RMS rather than raw variance — this is
    # the standard "boiling" / shimmer proxy and is what pkg73 §Acceptance
    # calls "inter-frame pixel variance".
    def inter_frame_rms(seq):
        diffs = np.diff(seq[1:], axis=0)  # central N-2 differences
        return float(np.sqrt(np.mean(diffs ** 2)))

    rms_t = inter_frame_rms(seq_t)
    rms_a = inter_frame_rms(seq_a)
    print(f"[pkg73] inter-frame RMS: temporal={rms_t:.6f} aov={rms_a:.6f} "
          f"reduction={(1.0 - rms_t / rms_a) * 100.0:.1f}%")

    assert rms_t < rms_a * 0.70, (
        f"pkg73 acceptance gate: TEMPORAL_AOV must reduce inter-frame RMS by "
        f"≥30%, got rms_t={rms_t:.6f} vs rms_a={rms_a:.6f} "
        f"(reduction {(1.0 - rms_t / rms_a) * 100.0:.1f}%)"
    )

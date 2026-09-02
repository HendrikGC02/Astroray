#!/usr/bin/env python
"""pkg219d — scalar parameter textures (op-VM → Roughness), CPU + GPU parity.

Before pkg219d the per-texel op-VM (pkg219a/b/c) drove ONLY Base Color; scalar
BSDF inputs (roughness/metallic/transmission/ior) read a constant-folded float, so
a Blender graph `Image → Map Range → Roughness` could not per-texel-drive
roughness. pkg219d wires the op-VM output into the scalar Disney inputs on BOTH
backends (CPU DisneyPlugin::substituted() + GPU c_wfProgBinding scalar side table),
behind the already-isolated <HasProgram> shade axis.

Scene: a metallic Disney quad lit by a bright headlight point light (near the
camera). A 2×1 image (left texel 0.0, right texel 1.0) drives Roughness through an
op-VM `Image → Map Range[0,1]→[0.3,0.9]` chain, so the LEFT half of the quad renders
at roughness 0.3 and the RIGHT half at 0.9. The headlight specular highlight sits at
the quad centre — the u=0.5 roughness boundary — so the highlight's left half is
sharp (0.3) and its right half broad (0.9); the tests sample each highlight half.

Roughness low end is 0.3, NOT the spec's 0.1: metallic Disney GPU↔CPU parity in the
NEAR-DELTA alpha band (roughness ≲ 0.1) is a PRE-EXISTING, unrelated xfail (pkg123,
~4× GPU/CPU ratio at the 0.0064 alpha floor). 0.3 vs 0.9 keeps a strong roughness
signal while both halves sit in the proven mid/high-roughness parity band.

Gates (per-half REFERENCE COMPARISON — robust to highlight placement): each half of
the op-VM (program) render is compared against the UNIFORM-roughness render of the
value it encodes. Same seed → the matching-roughness half is ~identical while the
mismatched one differs by the real roughness change.
  * test_cpu_roughness_program_drives_specular — CPU: the program's left half is
    closer to a uniform-0.3 render than to uniform-0.9 (and vice-versa for the right),
    i.e. the op-VM roughness reached the DisneyPlugin BSDF.
  * test_gpu_roughness_program_drives_specular — same per-half reproduction on GPU
    (proves the scalar side table + shade override applied on the device).
  * test_cpu_gpu_roughness_parity — per-channel MEAN-RATIO of the CPU vs GPU program
    render within band (gates the byte-mirror; NOT SSIM — independent RNG streams make
    windowed SSIM unreachable at modest spp, [[ssim-wrong-gate-for-independent-rng]]).

GPU-gated: skips when no CUDA device (CI has none); the GPU legs are an RTX-box leg.
"""

import astroray
import numpy as np
import pytest
from base_helpers import create_renderer, render_image, setup_camera

# opcode / sub-op enums (mirror include/astroray/shader_vm.h)
OP_LOAD_TEX, OP_LOAD_CONST, OP_MAP_RANGE = 1, 2, 6
MR_LINEAR = 0


def _has_cuda_gpu(renderer):
    return bool(astroray.__features__.get("cuda", False)) and \
        bool(getattr(renderer, "gpu_available", False))


def _register_roughness_program(renderer):
    """Register the op-VM chain `Image(0|1) → Map Range[0,1]→[0.3,0.9]` and return
    its program-texture name. The 2×1 source image encodes the two regions; the
    program remaps to the roughness range."""
    # 2x1 image: left texel 0.0 (→ roughness 0.3), right texel 1.0 (→ roughness 0.9).
    data = [0.0, 0.0, 0.0,
            1.0, 1.0, 1.0]
    renderer.load_texture("pkg219d_src", data, 2, 1, "UV")
    renderer.create_program_texture("pkg219d_rough", "UV")
    renderer.program_texture_add_input("pkg219d_rough", "pkg219d_src")
    # slot0 = tex; slot1..4 = consts (from_min=0, from_max=1, to_min=0.3, to_max=0.9);
    # slot5 = map_range(LINEAR, value=s0, from_min=s1, from_max=s2, to_min=s3, to_max=s4)
    consts = [0.0, 0.0, 0.0,   # const0 from_min
              1.0, 0.0, 0.0,   # const1 from_max
              0.3, 0.0, 0.0,   # const2 to_min
              0.9, 0.0, 0.0]   # const3 to_max
    code = [OP_LOAD_TEX,   0, 0, 0, 0, 0, 0, 0,
            OP_LOAD_CONST, 1, 0, 0, 0, 0, 0, 0,
            OP_LOAD_CONST, 2, 0, 0, 0, 0, 0, 1,
            OP_LOAD_CONST, 3, 0, 0, 0, 0, 0, 2,
            OP_LOAD_CONST, 4, 0, 0, 0, 0, 0, 3,
            OP_MAP_RANGE,  5, 0, 1, 2, 3, 4, MR_LINEAR]
    renderer.set_program_texture_program("pkg219d_rough", 1, 5, code, consts, [])
    return "pkg219d_rough"


def _build_scene(renderer, *, with_program, roughness=0.5):
    """Metallic Disney quad + headlight point light. `with_program` True → Roughness
    per-texel-driven by the op-VM chain (left 0.3 / right 0.9); False → a UNIFORM
    `roughness` reference (used to check each program half against the constant it
    should reproduce)."""
    # Black background: a metallic mirror reflects the environment, so a non-zero
    # env would wash the whole quad to the (roughness-blurred) env grey and swamp
    # the point-light specular — the ONE thing per-texel roughness controls.
    renderer.set_background_color([0.0, 0.0, 0.0])
    params = {"metallic": 1.0, "roughness": roughness}
    if with_program:
        params["roughness_program"] = _register_roughness_program(renderer)
    mat = renderer.create_material("disney", [0.9, 0.9, 0.9], params)

    # Quad corners (CCW, normal +z) with UVs spanning [0,1]^2: screen-left = u=0.
    A, B = [-1, -1, 0], [1, -1, 0]
    C, D = [1, 1, 0], [-1, 1, 0]
    n = [0, 0, 1]
    renderer.add_triangle_layers(A, B, C, mat, {"UVMap": [[0, 0], [1, 0], [1, 1]]},
                                 n, n, n)
    renderer.add_triangle_layers(A, C, D, mat, {"UVMap": [[0, 0], [1, 1], [0, 1]]},
                                 n, n, n)
    # Headlight: a bright point light near the camera so wi ≈ wo ≈ normal for the
    # whole (symmetric) quad — the specular response then depends only on roughness.
    renderer.add_point_light([0, 0, 2.9], {"mode": "rgb", "color": [1.0, 1.0, 1.0]}, 1000.0, 0.05)
    setup_camera(renderer, look_from=[0, 0, 3], look_at=[0, 0, 0], vup=[0, 1, 0],
                 vfov=45, width=64, height=64)


def _render(*, with_program, use_gpu, roughness=0.5, samples=160):
    r = create_renderer()
    if use_gpu:
        if not _has_cuda_gpu(r):
            pytest.skip("No CUDA GPU — pkg219d GPU leg runs on the RTX box.")
        r.set_use_gpu(True)
    r.set_seed(7)
    _build_scene(r, with_program=with_program, roughness=roughness)
    return render_image(r, samples=samples, max_depth=3, apply_gamma=False)


# The headlight specular highlight (and thus ALL the roughness signal) sits at the
# quad centre (image col ~32) — which is exactly the u=0.5 roughness boundary in
# the program render. So the highlight's LEFT half is roughness 0.3 and its RIGHT
# half is 0.9; sample each half (skipping the ~2px seam) to see the per-texel drive.
def _left(img):
    return img.mean(axis=2)[:, 22:31]    # x<0 half of the highlight → program roughness 0.3


def _right(img):
    return img.mean(axis=2)[:, 33:42]    # x>0 half of the highlight → program roughness 0.9


def _drives_specular(use_gpu):
    """The op-VM roughness reaches the BSDF: each half of the program render must
    match the UNIFORM-roughness render of the value it encodes (left→0.3, right→0.9),
    and NOT the other value. Same seed → the matching-roughness half is ~identical
    while the mismatched one differs by the real roughness change. Robust to where
    the point-light highlight lands (no peak/threshold guessing)."""
    prog = _render(with_program=True, use_gpu=use_gpu)
    u03 = _render(with_program=False, use_gpu=use_gpu, roughness=0.3)
    u09 = _render(with_program=False, use_gpu=use_gpu, roughness=0.9)
    # There must BE a measurable roughness signal in each region, else nothing is gated.
    left_signal = abs(_left(u03).mean() - _left(u09).mean())
    right_signal = abs(_right(u03).mean() - _right(u09).mean())
    assert left_signal > 5e-4 and right_signal > 5e-4, (
        f"no roughness signal in the measured regions (Δleft={left_signal:.5f}, "
        f"Δright={right_signal:.5f}) — scene cannot gate the per-texel drive")
    # Program LEFT half (0.3) closer to uniform-0.3 than to uniform-0.9.
    dl03 = abs(_left(prog).mean() - _left(u03).mean())
    dl09 = abs(_left(prog).mean() - _left(u09).mean())
    assert dl03 < dl09, (
        f"program left half did not reproduce roughness 0.3 (|prog−u03|={dl03:.5f} "
        f"≥ |prog−u09|={dl09:.5f}) — op-VM roughness dropped "
        f"{'on device' if use_gpu else 'on the CPU BSDF'}")
    # Program RIGHT half (0.9) closer to uniform-0.9 than to uniform-0.3.
    dr09 = abs(_right(prog).mean() - _right(u09).mean())
    dr03 = abs(_right(prog).mean() - _right(u03).mean())
    assert dr09 < dr03, (
        f"program right half did not reproduce roughness 0.9 (|prog−u09|={dr09:.5f} "
        f"≥ |prog−u03|={dr03:.5f})")




def test_cpu_roughness_program_drives_specular():
    """CPU: each half of the program render reproduces the uniform-roughness render
    of the value the op-VM encodes (left→0.3, right→0.9) — the op-VM roughness
    reached the DisneyPlugin BSDF."""
    _drives_specular(use_gpu=False)


def test_gpu_roughness_program_drives_specular():
    """GPU: same per-half reproduction — the scalar side table + shade override
    applied on the device (not collapsed to the constant-folded roughness)."""
    _drives_specular(use_gpu=True)


def test_cpu_gpu_roughness_parity():
    """Per-channel mean-ratio of the CPU vs GPU program render within band — gates
    the CPU↔GPU byte-mirror of the scalar op-VM substitution."""
    cpu = _render(with_program=True, use_gpu=False)
    gpu = _render(with_program=True, use_gpu=True)
    cm = np.array([float(cpu[..., c].mean()) for c in range(3)])
    gm = np.array([float(gpu[..., c].mean()) for c in range(3)])
    assert cm.mean() > 0.02, f"CPU reference too dark to gate: {cm}"
    assert gm.mean() > 0.02, f"GPU render too dark to gate: {gm}"
    ratio = gm / np.maximum(cm, 1e-6)
    for c, rc in enumerate(ratio):
        assert 0.80 <= rc <= 1.25, (
            f"channel {c} CPU/GPU mean-ratio {rc:.3f} out of band [0.80,1.25]; "
            f"cpu={cm}, gpu={gm}")

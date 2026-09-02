#!/usr/bin/env python
"""pkg219d — scalar parameter textures (op-VM → Roughness), CPU + GPU parity.

Before pkg219d the per-texel op-VM (pkg219a/b/c) drove ONLY Base Color; scalar
BSDF inputs (roughness/metallic/transmission/ior) read a constant-folded float, so
a Blender graph `Image → Map Range → Roughness` could not per-texel-drive
roughness. pkg219d wires the op-VM output into the scalar Disney inputs on BOTH
backends (CPU DisneyPlugin::substituted() + GPU c_wfProgBinding scalar side table),
behind the already-isolated <HasProgram> shade axis.

Scene: a metallic Disney quad lit by a headlight point light (near the camera, so
the specular half-vector is ≈ the surface normal for every symmetric surface point).
A 2×1 image (left texel 0.0, right texel 1.0) drives Roughness through an op-VM
`Image → Map Range[0,1]→[0.3,0.9]` chain, so the LEFT half renders at roughness 0.3
(sharp, bright near-normal specular) and the RIGHT half at 0.9 (broad, dim). The quad
is left/right symmetric, so the ONLY thing that differs between the halves is the
per-texel roughness.

Roughness low end is 0.3, NOT the spec's 0.1: metallic Disney GPU↔CPU parity in the
NEAR-DELTA alpha band (roughness ≲ 0.1) is a PRE-EXISTING, unrelated xfail (pkg123,
~4× GPU/CPU ratio at the 0.0064 alpha floor). 0.3 vs 0.9 keeps a strong, clearly
directional roughness signal (near-normal GGX peak D ≈ 39 vs 0.49, an ~80× ratio)
while both halves sit in the proven mid/high-roughness parity band.

Gates:
  * test_cpu_roughness_program_drives_specular — CPU: the low-roughness half is
    brighter than the high-roughness half (the op-VM roughness landed in the BSDF),
    AND a uniform-roughness control renders the two halves ~equal (isolates the
    per-texel drive from any left/right lighting asymmetry).
  * test_gpu_roughness_program_drives_specular — same asymmetry on GPU (proves the
    scalar side table + shade override applied on the device, not dropped).
  * test_cpu_gpu_roughness_parity — per-channel MEAN-RATIO of the CPU vs GPU
    program render within band (gates the byte-mirror; NOT SSIM — independent RNG
    streams make windowed SSIM unreachable at modest spp,
    [[ssim-wrong-gate-for-independent-rng]]).

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


def _build_scene(renderer, *, with_program):
    """Metallic Disney quad + headlight point light. `with_program` True → Roughness
    per-texel-driven by the op-VM chain; False → uniform roughness=0.5 control."""
    renderer.set_background_color([0.1, 0.1, 0.1])
    params = {"metallic": 1.0, "roughness": 0.5}
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
    renderer.add_point_light([0, 0, 2.9], [1.0, 1.0, 1.0], 40.0, 0.05)
    setup_camera(renderer, look_from=[0, 0, 3], look_at=[0, 0, 0], vup=[0, 1, 0],
                 vfov=45, width=64, height=64)


def _render(*, with_program, use_gpu, samples=160):
    r = create_renderer()
    if use_gpu:
        if not _has_cuda_gpu(r):
            pytest.skip("No CUDA GPU — pkg219d GPU leg runs on the RTX box.")
        r.set_use_gpu(True)
    r.set_seed(7)
    _build_scene(r, with_program=with_program)
    return render_image(r, samples=samples, max_depth=3, apply_gamma=False)


def _region_means(img):
    """(low_roughness_left, high_roughness_right) mean brightness, seam excluded."""
    gray = img.mean(axis=2)
    left = float(gray[:, 4:28].mean())    # u<0.5 → roughness 0.3
    right = float(gray[:, 36:60].mean())  # u>=0.5 → roughness 0.9
    return left, right


def test_cpu_roughness_program_drives_specular():
    """CPU: the op-VM roughness reaches the Disney BSDF — the low-roughness half is
    a brighter (sharper) headlight specular than the high-roughness half, while a
    uniform-roughness control renders the two halves ~equal."""
    prog = _render(with_program=True, use_gpu=False)
    lo, hi = _region_means(prog)
    assert lo > 0.02, f"scene too dark to gate (low-rough half mean={lo:.4f})"
    assert lo > hi * 1.15, (
        f"low-roughness (0.3) half not brighter than high-roughness (0.9) half — "
        f"op-VM roughness did not reach the CPU BSDF (lo={lo:.4f}, hi={hi:.4f})")
    # Control: uniform roughness → halves near-equal (rules out lighting asymmetry).
    ctrl = _render(with_program=False, use_gpu=False)
    clo, chi = _region_means(ctrl)
    assert abs(clo - chi) < 0.15 * max(clo, chi) + 1e-3, (
        f"uniform-roughness control halves differ too much (lo={clo:.4f}, "
        f"hi={chi:.4f}) — the asymmetry is not from the per-texel roughness")


def test_gpu_roughness_program_drives_specular():
    """GPU: same low>high asymmetry — the scalar side table + shade override applied
    on the device (not collapsed to the constant-folded roughness)."""
    prog = _render(with_program=True, use_gpu=True)
    lo, hi = _region_means(prog)
    assert lo > 0.02, f"GPU scene too dark to gate (low-rough half mean={lo:.4f})"
    assert lo > hi * 1.15, (
        f"GPU low-roughness half not brighter than high-roughness half — op-VM "
        f"roughness dropped on device (lo={lo:.4f}, hi={hi:.4f})")


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

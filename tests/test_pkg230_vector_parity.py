"""pkg230 Phase 2 — CPU/GPU parity render for OP_VEC_MATH / OP_VEC_ROTATE / Mix.

Renders a controlled 2x2 quad textured with an op-VM program (Vector Math ADD
offset, Vector Rotate 90° about Z, and a Mix with a constant) on CPU and GPU and
checks:
  * the VM changes the image vs the plain (no-program) texture, on BOTH backends;
  * GPU matches CPU within MC noise (per-channel mean-ratio).

The GPU leg runs the same shared HD svm_eval inside the <HasProgram=true> shade
specialization; parity is by construction. GPU-gated (CI has no CUDA device).
Saves representative PNGs to test_results/pkg230-p2 for the parent's visual
inspection. Left for the parent to execute after the fresh native rebuild.
"""
import os

import astroray
import numpy as np
import pytest
from base_helpers import create_renderer, render_image, save_image, setup_camera

# opcode enums (mirror include/astroray/shader_vm.h)
OP_LOAD_TEX, OP_LOAD_CONST = 1, 2
OP_MIX, OP_VEC_MATH, OP_VEC_ROTATE = 4, 15, 16
VECMATH_ADD = 0
VECROT_Z_AXIS = 3
MIX_BLEND = 0

_OUT = os.path.join(os.path.dirname(__file__), "..", "test_results", "pkg230-p2")


def _has_cuda_gpu(renderer):
    return bool(astroray.__features__.get("cuda", False)) and \
        bool(getattr(renderer, "gpu_available", False))


def _quad_image():
    img = np.array([
        [[0.8, 0.2, 0.1], [0.1, 0.8, 0.2]],
        [[0.2, 0.1, 0.8], [0.6, 0.6, 0.3]],
    ], dtype=np.float32)
    return img.reshape(-1).tolist(), 2, 2


def _program(kind):
    """Return (num_tex, out_slot, code_flat, consts_flat) for a program texture."""
    if kind == 'vec_math':
        # tex + (0.2, -0.1, 0.05)
        return 1, 2, [
            OP_LOAD_TEX, 0, 0, 0, 0, 0, 0, 0,
            OP_LOAD_CONST, 1, 0, 0, 0, 0, 0, 0,
            OP_VEC_MATH, 2, 0, 1, 0, 0, 0, VECMATH_ADD,
        ], [0.2, -0.1, 0.05]
    if kind == 'vec_rotate':
        # rotate 90° about Z: (r,g,b) -> (-g, r, b)
        return 1, 3, [
            OP_LOAD_TEX, 0, 0, 0, 0, 0, 0, 0,
            OP_LOAD_CONST, 1, 0, 0, 0, 0, 0, 0,      # center (0,0,0)
            OP_LOAD_CONST, 2, 0, 0, 0, 0, 0, 1,      # angle (pi/2 broadcast)
            OP_VEC_ROTATE, 3, 0, 1, 0, 2, 0, VECROT_Z_AXIS,
        ], [0.0, 0.0, 0.0, np.pi / 2, np.pi / 2, np.pi / 2]
    if kind == 'mix':
        # blend tex 60% toward (0.9, 0.1, 0.2)
        return 1, 3, [
            OP_LOAD_TEX, 0, 0, 0, 0, 0, 0, 0,
            OP_LOAD_CONST, 1, 0, 0, 0, 0, 0, 0,      # factor 0.6
            OP_LOAD_CONST, 2, 0, 0, 0, 0, 0, 1,      # color
            OP_MIX, 3, 1, 0, 2, 0, 0, MIX_BLEND,
        ], [0.6, 0.6, 0.6, 0.9, 0.1, 0.2]
    raise ValueError(kind)


def _build_scene(renderer, *, kind):
    renderer.set_background_color([0.5, 0.5, 0.5])
    data, w, h = _quad_image()
    renderer.load_texture("pkg230v_img", data, w, h, "UV")
    ntex, out_slot, code, consts = _program(kind)
    renderer.create_program_texture("pkg230v_prog", "UV")
    renderer.program_texture_add_input("pkg230v_prog", "pkg230v_img")
    renderer.set_program_texture_program("pkg230v_prog", ntex, out_slot, code, consts, [])
    mat = renderer.create_material("lambertian", [1.0, 1.0, 1.0],
                                   {"texture": "pkg230v_prog"})
    A, B = [-1, -1, 0], [1, -1, 0]
    C, D = [1, 1, 0], [-1, 1, 0]
    n = [0, 0, 1]
    renderer.add_triangle_layers(A, B, C, mat, {"UVMap": [[0, 0], [1, 0], [1, 1]]},
                                 n, n, n)
    renderer.add_triangle_layers(A, C, D, mat, {"UVMap": [[0, 0], [1, 1], [0, 1]]},
                                 n, n, n)
    setup_camera(renderer, look_from=[0, 0, 3], look_at=[0, 0, 0], vup=[0, 1, 0],
                 vfov=45, width=64, height=64)


def _render(kind, use_gpu, samples=64, seed=1):
    r = create_renderer()
    if use_gpu:
        if not _has_cuda_gpu(r):
            pytest.skip("No CUDA GPU — pkg230 vector leg runs on the RTX box.")
        r.set_use_gpu(True)
    r.set_seed(seed)
    _build_scene(r, kind=kind)
    return render_image(r, samples=samples, max_depth=2, apply_gamma=False)


@pytest.mark.parametrize("kind", ["vec_math", "vec_rotate", "mix"])
def test_cpu_program_changes_image(kind):
    plain = _render_plain(use_gpu=False)
    prog = _render(kind, use_gpu=False)
    mad = float(np.abs(plain - prog).mean())
    assert mad > 0.02, f"CPU {kind} had no effect (mean|diff|={mad:.4f})"
    save_image(prog, os.path.join(_OUT, f"pkg230_{kind}_cpu.png"))
    np.save(os.path.join(_OUT, f"pkg230_{kind}_cpu.npy"), prog)


@pytest.mark.parametrize("kind", ["vec_math", "vec_rotate", "mix"])
def test_gpu_program_changes_image(kind):
    plain = _render_plain(use_gpu=True)
    prog = _render(kind, use_gpu=True)
    mad = float(np.abs(plain - prog).mean())
    assert mad > 0.02, f"GPU {kind} had no effect (mean|diff|={mad:.4f})"
    save_image(prog, os.path.join(_OUT, f"pkg230_{kind}_gpu.png"))
    np.save(os.path.join(_OUT, f"pkg230_{kind}_gpu.npy"), prog)


@pytest.mark.parametrize("kind", ["vec_math", "vec_rotate", "mix"])
def test_gpu_matches_cpu(kind):
    cpu = _render(kind, use_gpu=False)
    gpu = _render(kind, use_gpu=True)
    for ch in range(3):
        c = float(cpu[..., ch].mean())
        g = float(gpu[..., ch].mean())
        if c < 1e-4:
            continue
        ratio = g / c
        assert 0.95 < ratio < 1.05, f"{kind} channel {ch} CPU/GPU mean-ratio {ratio:.3f}"


def _render_plain(use_gpu):
    r = create_renderer()
    if use_gpu:
        if not _has_cuda_gpu(r):
            pytest.skip("No CUDA GPU — pkg230 vector leg runs on the RTX box.")
        r.set_use_gpu(True)
    r.set_seed(1)
    r.set_background_color([0.5, 0.5, 0.5])
    data, w, h = _quad_image()
    r.load_texture("pkg230v_img", data, w, h, "UV")
    mat = r.create_material("lambertian", [1.0, 1.0, 1.0], {"texture": "pkg230v_img"})
    A, B = [-1, -1, 0], [1, -1, 0]
    C, D = [1, 1, 0], [-1, 1, 0]
    n = [0, 0, 1]
    r.add_triangle_layers(A, B, C, mat, {"UVMap": [[0, 0], [1, 0], [1, 1]]}, n, n, n)
    r.add_triangle_layers(A, C, D, mat, {"UVMap": [[0, 0], [1, 1], [0, 1]]}, n, n, n)
    setup_camera(r, look_from=[0, 0, 3], look_at=[0, 0, 0], vup=[0, 1, 0],
                 vfov=45, width=64, height=64)
    return render_image(r, samples=64, max_depth=2, apply_gamma=False)

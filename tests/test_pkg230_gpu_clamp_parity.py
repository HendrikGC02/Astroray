"""pkg230 — CPU/GPU parity render for the Clamp opcode (OP_CLAMP).

Renders a quad textured with an op-VM Clamp program (MINMAX, max=0.3 so bright
texels are pulled down) on CPU and GPU and checks:
  * the VM changes the image vs the plain (no-program) texture, on BOTH backends;
  * GPU matches CPU within MC noise (per-channel mean-ratio).

The GPU leg runs the same shared HD svm_eval inside the <HasProgram=true> shade
specialization; parity is by construction. GPU-gated (CI has no CUDA device).
"""
import astroray
import numpy as np
import pytest
from base_helpers import create_renderer, render_image, setup_camera

# opcode enums (mirror include/astroray/shader_vm.h)
OP_LOAD_TEX, OP_LOAD_CONST, OP_CLAMP = 1, 2, 14
CLAMP_MINMAX = 0


def _has_cuda_gpu(renderer):
    return bool(astroray.__features__.get("cuda", False)) and \
        bool(getattr(renderer, "gpu_available", False))


def _quad_image():
    img = np.array([
        [[0.9, 0.1, 0.1], [0.1, 0.9, 0.1]],
        [[0.1, 0.1, 0.9], [0.7, 0.7, 0.2]],
    ], dtype=np.float32)
    return img.reshape(-1).tolist(), 2, 2


def _build_scene(renderer, *, with_program):
    renderer.set_background_color([0.5, 0.5, 0.5])
    data, w, h = _quad_image()
    renderer.load_texture("pkg230_img", data, w, h, "UV")
    if with_program:
        renderer.create_program_texture("pkg230_prog", "UV")
        renderer.program_texture_add_input("pkg230_prog", "pkg230_img")
        # slot0=tex; slot1=const min(0.0); slot2=const max(0.3);
        # slot3 = clamp_MINMAX(v=tex.x, min, max)  (scalar, broadcast)
        consts = [0.0, 0.0, 0.0, 0.3, 0.3, 0.3]
        code = [OP_LOAD_TEX, 0, 0, 0, 0, 0, 0, 0,
                OP_LOAD_CONST, 1, 0, 0, 0, 0, 0, 0,
                OP_LOAD_CONST, 2, 0, 0, 0, 0, 0, 1,
                OP_CLAMP, 3, 0, 1, 2, 0, 0, CLAMP_MINMAX]
        renderer.set_program_texture_program("pkg230_prog", 1, 3, code, consts, [])
        tex_ref = "pkg230_prog"
    else:
        tex_ref = "pkg230_img"
    mat = renderer.create_material("lambertian", [1.0, 1.0, 1.0], {"texture": tex_ref})
    A, B = [-1, -1, 0], [1, -1, 0]
    C, D = [1, 1, 0], [-1, 1, 0]
    n = [0, 0, 1]
    renderer.add_triangle_layers(A, B, C, mat, {"UVMap": [[0, 0], [1, 0], [1, 1]]},
                                 n, n, n)
    renderer.add_triangle_layers(A, C, D, mat, {"UVMap": [[0, 0], [1, 1], [0, 1]]},
                                 n, n, n)
    setup_camera(renderer, look_from=[0, 0, 3], look_at=[0, 0, 0], vup=[0, 1, 0],
                 vfov=45, width=64, height=64)


def _render(*, with_program, use_gpu, samples=64, seed=1):
    r = create_renderer()
    if use_gpu:
        if not _has_cuda_gpu(r):
            pytest.skip("No CUDA GPU — pkg230 GPU leg runs on the RTX box.")
        r.set_use_gpu(True)
    r.set_seed(seed)
    _build_scene(r, with_program=with_program)
    return render_image(r, samples=samples, max_depth=2, apply_gamma=False)


def test_cpu_clamp_changes_image():
    plain = _render(with_program=False, use_gpu=False)
    prog = _render(with_program=True, use_gpu=False)
    mad = float(np.abs(plain - prog).mean())
    assert mad > 0.02, f"CPU op-VM Clamp had no effect (mean|diff|={mad:.4f})"


def test_gpu_clamp_changes_image():
    plain = _render(with_program=False, use_gpu=True)
    prog = _render(with_program=True, use_gpu=True)
    mad = float(np.abs(plain - prog).mean())
    assert mad > 0.02, f"GPU op-VM Clamp had no effect (mean|diff|={mad:.4f})"


def test_gpu_matches_cpu_clamp():
    cpu = _render(with_program=True, use_gpu=False)
    gpu = _render(with_program=True, use_gpu=True)
    # per-channel mean-ratio parity (independent MC streams; see memory
    # ssim-wrong-gate-for-independent-rng)
    for ch in range(3):
        c = float(cpu[..., ch].mean())
        g = float(gpu[..., ch].mean())
        if c < 1e-4:
            continue
        ratio = g / c
        assert 0.95 < ratio < 1.05, f"channel {ch} CPU/GPU mean-ratio {ratio:.3f}"

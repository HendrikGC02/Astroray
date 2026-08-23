"""pkg219b — CPU/GPU parity render for the per-texel op-VM.

Renders a quad textured with an op-VM program (Mix-darken of the image with
black at fac 0.5 -> half-brightness, chroma preserved) on CPU and GPU and checks:
  * the VM changes the image vs the plain (no-program) texture, on BOTH backends;
  * GPU matches CPU within MC noise (per-channel mean-ratio).

The GPU leg runs the same shared HD svm_eval inside the <HasProgram=true> shade
specialization; parity is by construction. GPU-gated (CI has no CUDA device).
"""
import astroray
import numpy as np
import pytest
from base_helpers import create_renderer, render_image, setup_camera

# opcode / sub-op enums (mirror include/astroray/shader_vm.h)
OP_LOAD_TEX, OP_LOAD_CONST, OP_MIX = 1, 2, 4
MIX_BLEND = 0


def _has_cuda_gpu(renderer):
    return bool(astroray.__features__.get("cuda", False)) and \
        bool(getattr(renderer, "gpu_available", False))


def _quad_image():
    img = np.array([
        [[0.9, 0.1, 0.1], [0.1, 0.9, 0.1]],
        [[0.1, 0.1, 0.9], [0.9, 0.9, 0.1]],
    ], dtype=np.float32)
    return img.reshape(-1).tolist(), 2, 2


def _build_scene(renderer, *, with_program):
    renderer.set_background_color([0.5, 0.5, 0.5])
    data, w, h = _quad_image()
    renderer.load_texture("pkg219b_img", data, w, h, "UV")
    if with_program:
        renderer.create_program_texture("pkg219b_prog", "UV")
        renderer.program_texture_add_input("pkg219b_prog", "pkg219b_img")
        # slot0=tex; slot1=const fac(0.5); slot2=const black;
        # slot3 = mix(BLEND, fac, tex, black) = tex*0.5
        consts = [0.5, 0.5, 0.5, 0.0, 0.0, 0.0]
        code = [OP_LOAD_TEX, 0, 0, 0, 0, 0, 0, 0,
                OP_LOAD_CONST, 1, 0, 0, 0, 0, 0, 0,
                OP_LOAD_CONST, 2, 0, 0, 0, 0, 0, 1,
                OP_MIX, 3, 1, 0, 2, 0, 0, MIX_BLEND]
        renderer.set_program_texture_program("pkg219b_prog", 1, 3, code, consts, [])
        tex_ref = "pkg219b_prog"
    else:
        tex_ref = "pkg219b_img"
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
            pytest.skip("No CUDA GPU — pkg219b GPU leg runs on the RTX box.")
        r.set_use_gpu(True)
    r.set_seed(seed)
    _build_scene(r, with_program=with_program)
    return render_image(r, samples=samples, max_depth=2, apply_gamma=False)


def test_cpu_program_darkens_image():
    plain = _render(with_program=False, use_gpu=False)
    prog = _render(with_program=True, use_gpu=False)
    mad = float(np.abs(plain - prog).mean())
    assert mad > 0.02, f"CPU op-VM had no effect (mean|diff|={mad:.4f})"


def test_gpu_program_darkens_image():
    plain = _render(with_program=False, use_gpu=True)
    prog = _render(with_program=True, use_gpu=True)
    mad = float(np.abs(plain - prog).mean())
    assert mad > 0.02, f"GPU op-VM had no effect (mean|diff|={mad:.4f})"


def test_cpu_gpu_program_parity():
    cpu = _render(with_program=True, use_gpu=False)
    gpu = _render(with_program=True, use_gpu=True)
    mask = cpu.reshape(-1, 3).mean(axis=1) > 0.02
    c = cpu.reshape(-1, 3)[mask]
    g = gpu.reshape(-1, 3)[mask]
    ratio = g.sum(axis=0) / np.maximum(c.sum(axis=0), 1e-6)
    assert np.allclose(ratio, 1.0, atol=0.03), f"CPU/GPU op-VM parity off: {ratio}"

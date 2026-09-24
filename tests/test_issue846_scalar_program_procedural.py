"""#846 — GPU scalar op-VM programs with a PROCEDURAL input.

Noise (Generated coords) -> Map Range -> Roughness / Metallic / IOR /
Transmission on a Disney quad. The GPU scalar path used to accept only an image
input, so these programs were dropped (constant value) without a report. Now the
scalar input goes through the same upload (image or pkg190 bake) and shade fetch
(gpu_progInputTexel) as base-colour program inputs.

Gate: per-quadrant, per-channel GPU/CPU mean ratio within 3 % (independent RNG
streams -> mean ratio, not SSIM). The CPU leg checks the program changes the
image vs the constant-only material (so a dropped program fails the GPU leg).
GPU legs skip without a CUDA device (CI has none).
"""
import astroray
import numpy as np
import pytest
from base_helpers import create_renderer, render_image, setup_camera

# opcode / sub-op enums (mirror include/astroray/shader_vm.h)
OP_LOAD_TEX, OP_LOAD_CONST, OP_MAP_RANGE = 1, 2, 6
MR_LINEAR = 0

_W = _H = 64
_WINDOW_VFOV = float(np.degrees(2 * np.arctan(0.95 / 3.0)))  # visible [-0.95, 0.95]
_BBOX_MIN = [-1.0, -1.0, -1.3]
_BBOX_SIZE = [2.0, 2.0, 2.0]

# socket -> (program param, constant params, Map Range target [to_min, to_max],
#            point-light position). Constants are far from the mapped range so a
#            dropped program is visible.
_CASES = {
    "roughness": ("roughness_program", {"metallic": 1.0, "roughness": 1.0},
                  (0.3, 0.8), [1.5, 1.0, 2.5]),
    "metallic": ("metallic_program", {"metallic": 1.0, "roughness": 0.5},
                 (0.0, 1.0), [2.0, 1.5, 2.5]),
    "ior": ("ior_program", {"transmission": 1.0, "roughness": 0.4, "ior": 1.1},
            (1.8, 2.8), [0.0, 0.0, 2.9]),
    "transmission": ("transmission_program", {"transmission": 1.0, "roughness": 0.5},
                     (0.0, 1.0), [2.0, 1.5, 2.5]),
}


def _has_cuda_gpu(renderer):
    return bool(astroray.__features__.get("cuda", False)) and \
        bool(getattr(renderer, "gpu_available", False))


def _noise_program(r, name, to_lo, to_hi):
    """Noise (Generated) -> Map Range [0.35, 0.65] -> [to_lo, to_hi]."""
    r.create_procedural_texture(name + "_noise", "noise_perlin",
                                [5.0, 2.0, 0.5, 2.0, 0.0, 1.0, 0.0, 0, 1], "GENERATED")
    r.set_texture_generated_bbox(name + "_noise", _BBOX_MIN, _BBOX_SIZE)
    r.create_program_texture(name, "GENERATED")
    r.program_texture_add_input(name, name + "_noise")
    r.set_texture_generated_bbox(name, _BBOX_MIN, _BBOX_SIZE)
    consts = [0.35, 0.0, 0.0, 0.65, 0.0, 0.0, to_lo, 0.0, 0.0, to_hi, 0.0, 0.0]
    code = [OP_LOAD_TEX,   0, 0, 0, 0, 0, 0, 0,
            OP_LOAD_CONST, 1, 0, 0, 0, 0, 0, 0,
            OP_LOAD_CONST, 2, 0, 0, 0, 0, 0, 1,
            OP_LOAD_CONST, 3, 0, 0, 0, 0, 0, 2,
            OP_LOAD_CONST, 4, 0, 0, 0, 0, 0, 3,
            OP_MAP_RANGE,  5, 0, 1, 2, 3, 4, MR_LINEAR]
    r.set_program_texture_program(name, 1, 5, code, consts, [])


def _render(socket, use_gpu, with_program=True, samples=256):
    param, consts, (lo, hi), light = _CASES[socket]
    r = create_renderer()
    if use_gpu:
        if not _has_cuda_gpu(r):
            pytest.skip("No CUDA GPU — #846 GPU leg runs on the RTX box.")
        r.set_use_gpu(True)
    r.set_seed(1)
    r.set_background_color([0.0, 0.0, 0.0])
    params = dict(consts)
    if with_program:
        _noise_program(r, "p846_" + socket, lo, hi)
        params[param] = "p846_" + socket
    mat = r.create_material("disney", [0.8, 0.5, 0.3], params)
    A, B, C, D = [-1, -1, 0], [1, -1, 0], [1, 1, 0], [-1, 1, 0]
    n = [0, 0, 1]
    r.add_triangle_layers(A, B, C, mat, {"UVMap": [[0, 0], [1, 0], [1, 1]]}, n, n, n)
    r.add_triangle_layers(A, C, D, mat, {"UVMap": [[0, 0], [1, 1], [0, 1]]}, n, n, n)
    r.add_point_light(light, {"mode": "rgb", "color": [1.0, 1.0, 1.0]}, 1000.0, 0.05)
    setup_camera(r, look_from=[0, 0, 3], look_at=[0, 0, 0], vup=[0, 1, 0],
                 vfov=_WINDOW_VFOV, width=_W, height=_H)
    return render_image(r, samples=samples, max_depth=3, apply_gamma=False)


def _quadrants(img):
    H, W = img.shape[:2]
    out = []
    for ya, yb in ((0.05, 0.45), (0.55, 0.95)):
        for xa, xb in ((0.05, 0.45), (0.55, 0.95)):
            roi = img[int(ya * H):int(yb * H), int(xa * W):int(xb * W)]
            out.append(roi.reshape(-1, 3).mean(axis=0))
    return np.array(out)


@pytest.mark.parametrize("socket", sorted(_CASES))
def test_846_cpu_program_changes_image(socket):
    """Scene check: the program visibly changes the CPU render vs the constant."""
    prog = _render(socket, False)
    const = _render(socket, False, with_program=False)
    assert _quadrants(prog).min() > 0.01, f"{socket}: CPU program render too dark to gate"
    rel = np.abs(prog - const).mean() / max(float(const.mean()), 1e-4)
    assert rel > 0.25, f"{socket}: program barely changes the image (rel L1 {rel:.3f})"


@pytest.mark.parametrize("socket", sorted(_CASES))
def test_846_gpu_scalar_procedural_program_parity(socket):
    cpu = _quadrants(_render(socket, False))
    gpu = _quadrants(_render(socket, True))
    ratio = gpu / np.maximum(cpu, 1e-4)
    assert np.allclose(ratio, 1.0, atol=0.03), (
        f"{socket}: GPU/CPU quadrant ratio outside 3 %:\n{ratio}\ncpu={cpu}\ngpu={gpu}")

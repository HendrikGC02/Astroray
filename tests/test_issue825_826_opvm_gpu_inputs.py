"""#825 + #826 — GPU op-VM program inputs.

#825: one ImageTexture used directly (no Mapping) by material A and as the op-VM
child of a ProgramTexture WITH a Mapping by material B. The GPU descriptor was
keyed on the image pointer alone, so the first material uploaded fixed the
Mapping for both. scene_upload.cu now keys it on (image, applied Mapping).

#826: a base-colour program with 2 texture inputs (Noise -> Mix <- Checker; two
images into one Mix) samples both inputs on the GPU (was: flat base colour).

Gate: per-ROI, per-channel GPU/CPU mean ratio within 3 % (independent RNG
streams -> mean ratio, not SSIM). 256 spp: at 64 spp the darkest channels
(~0.03) showed 3.5 % GPU/CPU noise on a correct build; 256 spp measured <= 1.8 %. CPU legs check the scene itself; GPU legs are
GPU-gated (CI has no CUDA device).
"""
import astroray
import numpy as np
import pytest
from base_helpers import create_renderer, render_image, setup_camera

# opcode / sub-op enums (mirror include/astroray/shader_vm.h)
OP_LOAD_TEX, OP_LOAD_CONST, OP_MIX = 1, 2, 4
MIX_BLEND = 0

# 2x2 RGBY image (row 0 = top) and a second, distinct 2x2 image.
_IMG_A = [[[0.9, 0.1, 0.1], [0.1, 0.9, 0.1]],
          [[0.1, 0.1, 0.9], [0.9, 0.9, 0.1]]]
_IMG_B = [[[0.1, 0.5, 0.9], [0.9, 0.5, 0.1]],
          [[0.5, 0.9, 0.1], [0.2, 0.2, 0.2]]]
# Mirror-U Mapping (3x4 row-major): u' = 1 - u.
_MIRROR_U = [-1.0, 0.0, 0.0, 1.0,
             0.0, 1.0, 0.0, 0.0,
             0.0, 0.0, 1.0, 0.0]
_FAC = 0.3  # asymmetric Mix factor: swapping the two inputs is visible

_IDENTITY_PROG = ([OP_LOAD_TEX, 0, 0, 0, 0, 0, 0, 0], [])
# s0 = in0; s1 = in1; s2 = fac; s3 = mix(BLEND, s2, s0, s1) = in0*(1-fac) + in1*fac
_MIX2_PROG = ([OP_LOAD_TEX, 0, 0, 0, 0, 0, 0, 0,
               OP_LOAD_TEX, 1, 0, 0, 0, 0, 0, 1,
               OP_LOAD_CONST, 2, 0, 0, 0, 0, 0, 0,
               OP_MIX, 3, 2, 0, 1, 0, 0, MIX_BLEND],
              [_FAC, _FAC, _FAC])


def _has_cuda_gpu(renderer):
    return bool(astroray.__features__.get("cuda", False)) and \
        bool(getattr(renderer, "gpu_available", False))


def _flat(img):
    return np.asarray(img, dtype=np.float32).reshape(-1).tolist()


def _quad(r, mat, x0, x1, y0=-1.0, y1=1.0):
    A, B, C, D = [x0, y0, 0], [x1, y0, 0], [x1, y1, 0], [x0, y1, 0]
    n = [0, 0, 1]
    r.add_triangle_layers(A, B, C, mat, {"UVMap": [[0, 0], [1, 0], [1, 1]]}, n, n, n)
    r.add_triangle_layers(A, C, D, mat, {"UVMap": [[0, 0], [1, 1], [0, 1]]}, n, n, n)


def _program(r, name, coord, inputs, prog, num_tex):
    code, consts = prog
    r.create_program_texture(name, coord)
    for child in inputs:
        r.program_texture_add_input(name, child)
    r.set_program_texture_program(name, num_tex, 3 if num_tex == 2 else 0,
                                  code, consts, [])


def _render(build, use_gpu, width, height, samples=256):
    r = create_renderer()
    if use_gpu:
        if not _has_cuda_gpu(r):
            pytest.skip("No CUDA GPU — #825/#826 GPU leg runs on the RTX box.")
        r.set_use_gpu(True)
    r.set_seed(1)
    r.set_background_color([0.5, 0.5, 0.5])
    build(r)
    return render_image(r, samples=samples, max_depth=2, apply_gamma=False)


def _quadrant_means(img, x0, x1):
    """Per-channel means of the 4 texel quadrants of the quad spanning pixel
    columns [x0, x1) (20 % margins keep ROIs off texel edges)."""
    H = img.shape[0]
    w = x1 - x0
    out = []
    for ya, yb in ((0.1, 0.4), (0.6, 0.9)):
        for xa, xb in ((0.1, 0.4), (0.6, 0.9)):
            roi = img[int(ya * H):int(yb * H), x0 + int(xa * w):x0 + int(xb * w)]
            out.append(roi.reshape(-1, 3).mean(axis=0))
    return np.array(out)


def _assert_ratio(gpu, cpu, label):
    ratio = gpu / np.maximum(cpu, 1e-4)
    assert np.allclose(ratio, 1.0, atol=0.03), (
        f"{label}: GPU/CPU ROI ratio outside 3 %:\n{ratio}\ncpu={cpu}\ngpu={gpu}")


# --------------------------------------------------------------------------- #
# #825 — direct image (no Mapping) + the same image inside a mirrored program.
# Two quads fill a 2:1 frame. Both layouts fail on main's .pyd (program quad
# wrong with it on the right; both quads wrong with it on the left).
# --------------------------------------------------------------------------- #
_W825, _H825 = 128, 64


def _build_825(program_left):
    def build(r):
        r.load_texture("img825", _flat(_IMG_A), 2, 2, "UV")
        _program(r, "prog825", "UV", ["img825"], _IDENTITY_PROG, 1)
        r.set_texture_mapping_matrix("prog825", _MIRROR_U)
        direct = r.create_material("lambertian", [1.0, 1.0, 1.0], {"texture": "img825"})
        prog = r.create_material("lambertian", [1.0, 1.0, 1.0], {"texture": "prog825"})
        left, right = (prog, direct) if program_left else (direct, prog)
        _quad(r, left, -2.0, 0.0)
        _quad(r, right, 0.0, 2.0)
        # visible window x in [-1.9, 1.9], y in [-0.95, 0.95]
        setup_camera(r, look_from=[0, 0, 3], look_at=[0, 0, 0], vup=[0, 1, 0],
                     vfov=float(np.degrees(2 * np.arctan(0.95 / 3.0))),
                     width=_W825, height=_H825)
    return build


def _halves(img):
    return _quadrant_means(img, 0, _W825 // 2), _quadrant_means(img, _W825 // 2, _W825)


@pytest.mark.parametrize("program_left", [False, True])
def test_825_cpu_program_quad_is_mirrored(program_left):
    """Scene check: on the CPU the program quad shows the image mirrored in u."""
    cpu = _render(_build_825(program_left), False, _W825, _H825)
    left, right = _halves(cpu)
    prog, direct = (left, right) if program_left else (right, left)
    mirrored = direct[[1, 0, 3, 2]]
    assert np.allclose(prog / np.maximum(mirrored, 1e-4), 1.0, atol=0.03), (prog, direct)
    assert not np.allclose(prog, direct, atol=0.05), "mirror had no effect"


@pytest.mark.parametrize("program_left", [False, True])
def test_825_gpu_direct_and_program_descriptors_distinct(program_left):
    cpu = _render(_build_825(program_left), False, _W825, _H825)
    gpu = _render(_build_825(program_left), True, _W825, _H825)
    for side, c, g in zip(("left", "right"), _halves(cpu), _halves(gpu)):
        _assert_ratio(g, c, f"#825 program_left={program_left} {side} quad")


# --------------------------------------------------------------------------- #
# #826 (a) — two images into one Mix, with a mirror Mapping on the program (both
# children must carry the ProgramTexture's Mapping).
# --------------------------------------------------------------------------- #
_W826, _H826 = 64, 64
_WINDOW_VFOV = float(np.degrees(2 * np.arctan(0.95 / 3.0)))  # visible [-0.95, 0.95]


def _build_two_images(r):
    r.load_texture("imgA826", _flat(_IMG_A), 2, 2, "UV")
    r.load_texture("imgB826", _flat(_IMG_B), 2, 2, "UV")
    _program(r, "prog826i", "UV", ["imgA826", "imgB826"], _MIX2_PROG, 2)
    r.set_texture_mapping_matrix("prog826i", _MIRROR_U)
    mat = r.create_material("lambertian", [1.0, 1.0, 1.0], {"texture": "prog826i"})
    _quad(r, mat, -1.0, 1.0)
    setup_camera(r, look_from=[0, 0, 3], look_at=[0, 0, 0], vup=[0, 1, 0],
                 vfov=_WINDOW_VFOV, width=_W826, height=_H826)


def test_826_cpu_two_image_mix_matches_texels():
    """Scene check: the CPU program render matches a plain image whose texels
    are the u-mirrored per-texel mix (1-fac)*A + fac*B (same spectral pipeline,
    so the comparison is texel-for-texel)."""
    mixed = (1 - _FAC) * np.array(_IMG_A) + _FAC * np.array(_IMG_B)
    mixed = mixed[:, ::-1, :]  # mirror U

    def build_ref(r):
        r.load_texture("ref826", _flat(mixed), 2, 2, "UV")
        mat = r.create_material("lambertian", [1.0, 1.0, 1.0], {"texture": "ref826"})
        _quad(r, mat, -1.0, 1.0)
        setup_camera(r, look_from=[0, 0, 3], look_at=[0, 0, 0], vup=[0, 1, 0],
                     vfov=_WINDOW_VFOV, width=_W826, height=_H826)

    cpu = _quadrant_means(_render(_build_two_images, False, _W826, _H826), 0, _W826)
    ref = _quadrant_means(_render(build_ref, False, _W826, _H826), 0, _W826)
    _assert_ratio(cpu, ref, "#826 CPU program vs pre-mixed texels")


def test_826_gpu_two_image_mix_parity():
    cpu = _quadrant_means(_render(_build_two_images, False, _W826, _H826), 0, _W826)
    gpu = _quadrant_means(_render(_build_two_images, True, _W826, _H826), 0, _W826)
    _assert_ratio(gpu, cpu, "#826 two images -> Mix")


# --------------------------------------------------------------------------- #
# #826 (b) — Noise -> Mix <- Checker, Generated coords (pkg190 3-D bakes).
# --------------------------------------------------------------------------- #
_BBOX_MIN = [-1.0, -1.0, -1.3]   # quad z=0 -> g.z = 0.65 (off a checker edge)
_BBOX_SIZE = [2.0, 2.0, 2.0]


def _build_noise_checker(r):
    r.create_procedural_texture("noise826", "noise_perlin",
                                [5.0, 2.0, 0.5, 2.0, 0.0, 1.0, 0.0, 0, 1], "GENERATED")
    r.create_procedural_texture("chk826", "checker",
                                [0.9, 0.1, 0.1, 0.1, 0.1, 0.9, 4.0], "GENERATED")
    for name in ("noise826", "chk826"):
        r.set_texture_generated_bbox(name, _BBOX_MIN, _BBOX_SIZE)
    _program(r, "prog826p", "GENERATED", ["noise826", "chk826"], _MIX2_PROG, 2)
    r.set_texture_generated_bbox("prog826p", _BBOX_MIN, _BBOX_SIZE)
    mat = r.create_material("lambertian", [1.0, 1.0, 1.0], {"texture": "prog826p"})
    _quad(r, mat, -1.0, 1.0)
    setup_camera(r, look_from=[0, 0, 3], look_at=[0, 0, 0], vup=[0, 1, 0],
                 vfov=_WINDOW_VFOV, width=_W826, height=_H826)


def test_826_gpu_noise_mix_checker_parity():
    cpu_img = _render(_build_noise_checker, False, _W826, _H826)
    gpu_img = _render(_build_noise_checker, True, _W826, _H826)
    # Checker cells visible on the GPU (the program was dropped -> flat before).
    red = gpu_img[..., 0]
    assert red.max() - red.min() > 0.1, "GPU Noise->Mix<-Checker render is flat"
    _assert_ratio(gpu_img.reshape(-1, 3).mean(axis=0),
                  cpu_img.reshape(-1, 3).mean(axis=0), "#826 Noise->Mix<-Checker (frame)")
    _assert_ratio(_quadrant_means(gpu_img, 0, _W826), _quadrant_means(cpu_img, 0, _W826),
                  "#826 Noise->Mix<-Checker (quadrants)")


# --------------------------------------------------------------------------- #
# #826 — an input t >= 1 that cannot be sampled at a hit skips the whole texture,
# exactly like an input-0 miss (critic finding: it used to substitute input 0).
# Spheres carry no GPU texture UVs: a single-image program misses input 0; a
# program with a 3-D procedural input 0 and an image input 1 misses input 1.
# Both must render the same (texture skipped). GPU-only: the CPU samples sphere
# UVs, so this is a GPU-internal consistency check.
# --------------------------------------------------------------------------- #
def _build_sphere_miss(r):
    r.load_texture("imgS826", _flat(_IMG_A), 2, 2, "UV")
    r.create_procedural_texture("chkS826", "checker",
                                [0.9, 0.1, 0.1, 0.1, 0.1, 0.9, 4.0], "GENERATED")
    r.set_texture_generated_bbox("chkS826", [-2.2, -1.1, -1.1], [4.4, 2.2, 2.2])
    _program(r, "progS1", "UV", ["imgS826"], _IDENTITY_PROG, 1)
    _program(r, "progS2", "GENERATED", ["chkS826", "imgS826"], _MIX2_PROG, 2)
    r.set_texture_generated_bbox("progS2", [-2.2, -1.1, -1.1], [4.4, 2.2, 2.2])
    single = r.create_material("lambertian", [1.0, 1.0, 1.0], {"texture": "progS1"})
    mixed = r.create_material("lambertian", [1.0, 1.0, 1.0], {"texture": "progS2"})
    r.add_sphere([-1.0, 0.0, 0.0], 0.9, single)
    r.add_sphere([1.0, 0.0, 0.0], 0.9, mixed)
    setup_camera(r, look_from=[0, 0, 6], look_at=[0, 0, 0], vup=[0, 1, 0],
                 vfov=float(np.degrees(2 * np.arctan(1.0 / 6.0))),
                 width=_W825, height=_H825)


def test_826_gpu_input_miss_skips_like_input0():
    gpu = _render(_build_sphere_miss, True, _W825, _H825)
    h, w = gpu.shape[:2]
    # sphere centres at x = -1 / +1 of a [-2, 2] x [-1, 1] window
    roi = lambda cx: gpu[int(0.35 * h):int(0.65 * h),  # noqa: E731
                         int((cx - 0.15) * w):int((cx + 0.15) * w)].reshape(-1, 3).mean(axis=0)
    _assert_ratio(roi(0.75), roi(0.25), "#826 input-1 miss vs input-0 miss (spheres)")

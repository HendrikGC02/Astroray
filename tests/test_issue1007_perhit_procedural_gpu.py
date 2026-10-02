"""#1007 - the GPU evaluates Noise / Wave / Voronoi per hit instead of a 64^3 bake.

#994 baked OBJECT-coordinate procedurals (and pkg190 Generated ones) into a 64^3
nearest-voxel grid; detail finer than a voxel aliased (wood rings, marble veins).
The evaluators now live in include/astroray/procedural_tex.h, shared by the CPU
Texture classes and the GPU shade path (proc_tex_eval.cu), and scene_upload.cu
lowers every Noise / Wave / Voronoi surface texture with Object or Generated
coordinates to a per-hit descriptor.

Scenes: a z=0 quad over [-1,1]^2 under a uniform white world. A lambertian there
has radiance = albedo for every sample, so CPU and GPU agree per pixel up to the
sub-pixel jitter; the patterns are a few pixels per period, i.e. resolved by the
image but finer than a 2/64 voxel (the #994 bake aliased them).
"""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "blender_addon"))
import shader_vm_compiler as C  # noqa: E402

astroray = pytest.importorskip("astroray")

RES = 96
SPP = 64
BBOX_MIN = [-1.0, -1.0, -1.0]
BBOX_SIZE = [2.0, 2.0, 2.0]
LO, HI = (0.1, 0.1, 0.1), (0.9, 0.9, 0.9)
# Wave rings, spherical, sine: period 2*pi/(20*scale) = 0.063 world units at scale 5
# (about 2 voxels of the old bake, 4 px here).
WAVE_RINGS = [1, 0, 3, 0, 5.0, 0.0, 2.0, 1.0, 0.5, 0.0, *LO, *HI]
# Noise: fBM, detail 4, distortion 2 (scale 12: features ~0.05 units).
NOISE = [12.0, 4.0, 0.6, 2.0, 0.0, 1.0, 2.0, 0.0, 1.0]
# Voronoi F1, Euclidean, Color output, scale 14.
VORONOI = [14.0, 1.0, 0, 0, 1.0, *LO, *HI, 0.0, 0.5, 2.0, 0.5, 0.0, 1.0]


# --- minimal duck-typed Blender node model (as tests/test_pkg277_coordinate_program.py) ---
class Sock:
    def __init__(self, name, default=0.0, link=None, type=None):
        self.name = name
        self.default_value = default
        self._link = link
        self.type = type

    @property
    def is_linked(self):
        return self._link is not None

    @property
    def links(self):
        return [self._link] if self._link else []


class Link:
    def __init__(self, from_node, from_socket_name="Vector"):
        self.from_node = from_node
        self.from_socket = type("FS", (), {"name": from_socket_name,
                                           "identifier": from_socket_name})()


class SockList:
    def __init__(self, socks):
        self._socks = socks

    def get(self, name):
        return next((s for s in self._socks if s.name == name), None)

    def __getitem__(self, i):
        return self._socks[i]

    def __len__(self):
        return len(self._socks)

    def __iter__(self):
        return iter(self._socks)


class Node:
    def __init__(self, type, inputs=None, name="", **kw):
        self.type = type
        self.name = name or type
        self.inputs = SockList(inputs or [])
        for k, v in kw.items():
            setattr(self, k, v)


def _mix_program():
    """Mix(0.5, Wave Color, Noise Color): a two-input base-colour program (wood-like)."""
    wave = Node('TEX_WAVE', inputs=[Sock('Vector')])
    noise = Node('TEX_NOISE', inputs=[Sock('Vector')])
    mix = Node('MIX_RGB', blend_type='MIX',
               inputs=[Sock('Fac', 0.5),
                       Sock('Color1', [0, 0, 0], Link(wave, 'Color')),
                       Sock('Color2', [0, 0, 0], Link(noise, 'Color'))])
    return C.compile_chain(Sock('Base Color', [0.5, 0.5, 0.5], Link(mix, 'Color')))


def _sin_warp():
    """TexCoord -> SepXYZ -> x*6 -> Sin -> CombXYZ (pkg277 coordinate program)."""
    coord = Node('TEX_COORD', name='Texture Coordinate')
    sep = Node('SEPXYZ', inputs=[Sock('Vector', (0, 0, 0), Link(coord, 'Object'))])
    mul = Node('MATH', operation='MULTIPLY',
               inputs=[Sock('Value', 0.0, Link(sep, 'X')), Sock('Value_001', 6.0)])
    sin = Node('MATH', operation='SINE',
               inputs=[Sock('Value', 0.0, Link(mul, 'Value')), Sock('Value_001', 0.5)])
    comb = Node('COMBXYZ', inputs=[Sock('X', 0.0, Link(sin, 'Value')),
                                   Sock('Y', 0.0, Link(sep, 'Y')),
                                   Sock('Z', 0.0, Link(sep, 'Z'))])
    c = C.compile_coord_chain(Sock('Vector', (0, 0, 0), Link(comb, 'Vector')))
    return c['out_slot'], c['code_flat'], c['consts_flat']


# Rotation 35 deg about z, scale 1.5: a 3-D Mapping on the program (CPU applies it to p).
_ROT = np.radians(35.0)
MAPPING = [1.5 * np.cos(_ROT), -1.5 * np.sin(_ROT), 0.0, 0.1,
           1.5 * np.sin(_ROT), 1.5 * np.cos(_ROT), 0.0, -0.2,
           0.0, 0.0, 1.5, 0.0]


def _tex_wave_object(r):
    r.create_procedural_texture("w1007", "wave", WAVE_RINGS, "OBJECT")
    return "w1007"


def _tex_noise_generated(r):
    r.create_procedural_texture("n1007", "noise_perlin", NOISE, "GENERATED")
    r.set_texture_generated_bbox("n1007", BBOX_MIN, BBOX_SIZE)
    return "n1007"


def _tex_voronoi_object(r):
    r.create_procedural_texture("v1007", "voronoi", VORONOI, "OBJECT")
    return "v1007"


def _tex_program_object(r):
    # The inputs' own coordinate modes are irrelevant: ProgramTexture samples them at
    # the PROGRAM's resolved (+Mapped) point, on both backends.
    r.create_procedural_texture("pw1007", "wave", WAVE_RINGS)
    r.create_procedural_texture("pn1007", "noise_perlin", NOISE)
    compiled = _mix_program()
    r.create_program_texture("prog1007", "OBJECT")
    r.set_texture_mapping_matrix("prog1007", [float(v) for v in MAPPING])
    r.program_texture_add_input("prog1007", "pw1007")
    r.program_texture_add_input("prog1007", "pn1007")
    r.set_program_texture_program("prog1007", compiled['num_tex'], compiled['out_slot'],
                                  compiled['code_flat'], compiled['consts_flat'],
                                  compiled['ramps_flat'])
    return "prog1007"


def _tex_coordprog_object(r):
    r.create_procedural_texture("cw1007", "wave", WAVE_RINGS)
    out, code, consts = _sin_warp()
    r.create_coord_program_texture("warp1007", "cw1007", "OBJECT", out, code, consts)
    return "warp1007"


def _tex_checker_object(r):
    # No per-hit evaluator for Checker: the 64^3 bake stays, and is reported.
    r.create_procedural_texture("c1007", "checker", [*LO, *HI, 3.0], "OBJECT")
    return "c1007"


CASES = {
    "wave_object": _tex_wave_object,
    "noise_generated": _tex_noise_generated,
    "voronoi_object": _tex_voronoi_object,
    "program_object": _tex_program_object,
    "coordprog_object": _tex_coordprog_object,
}


def _build(r, tex_setup, use_gpu, principled):
    from base_helpers import setup_camera
    r.set_use_gpu(bool(use_gpu))
    r.set_adaptive_sampling(False)
    r.set_seed(11)
    r.set_background_color([1.0, 1.0, 1.0])
    name = tex_setup(r)
    if principled:
        mat = r.create_material("principled", [0.8, 0.8, 0.8],
                                {"roughness": 0.6, "base_color_texture": name})
    else:
        mat = r.create_material("lambertian", [0.8, 0.8, 0.8], {"texture": name})
    A, B, Cc, D = [-1, -1, 0], [1, -1, 0], [1, 1, 0], [-1, 1, 0]
    n = [0, 0, 1]
    r.add_triangle_layers(A, B, Cc, mat, {"UVMap": [[0, 0], [1, 0], [1, 1]]}, n, n, n)
    r.add_triangle_layers(A, Cc, D, mat, {"UVMap": [[0, 0], [1, 1], [0, 1]]}, n, n, n)
    setup_camera(r, look_from=[0, 0, 3.0], look_at=[0, 0, 0], vup=[0, 1, 0],
                 vfov=30.0, width=RES, height=RES)


def _render(tex_setup, use_gpu, principled=False):
    from base_helpers import render_image
    r = astroray.Renderer()
    r.set_integrator("path_tracer")
    if use_gpu and not (astroray.__features__.get("cuda", False)
                        and getattr(r, "gpu_available", False)):
        pytest.skip("No CUDA GPU")
    _build(r, tex_setup, use_gpu, principled)
    return np.asarray(render_image(r, samples=SPP, max_depth=2, apply_gamma=False))


def _save(img, name):
    out = os.environ.get("ISSUE1007_EVIDENCE_DIR")
    if out:
        from base_helpers import save_image
        save_image(np.clip(img, 0, 1) ** (1 / 2.2), os.path.join(out, name))


@pytest.mark.gpu
@pytest.mark.parametrize("case", sorted(CASES))
def test_gpu_perhit_procedural_matches_cpu_per_pixel(case, capfd):
    gpu = _render(CASES[case], True)
    err = capfd.readouterr().err
    cpu = _render(CASES[case], False)
    _save(gpu, f"{case}_gpu.png")
    _save(cpu, f"{case}_cpu.png")
    assert "[#1007] DEGRADED" not in err, err[-800:]
    # The pattern is resolved (not a flat or blurred field) ...
    assert cpu[..., 0].std() > 0.08, cpu[..., 0].std()
    # ... and the GPU draws the same pixels: under a uniform world the lambertian
    # radiance is the albedo, so only sub-pixel jitter separates the two.
    diff = np.abs(gpu - cpu).mean()
    assert diff < 0.02, diff
    ratio = gpu.reshape(-1, 3).mean(0) / np.maximum(cpu.reshape(-1, 3).mean(0), 1e-6)
    assert np.all(np.abs(ratio - 1.0) < 0.02), ratio


@pytest.mark.gpu
@pytest.mark.parametrize("case", ["wave_object", "program_object"])
def test_gpu_perhit_principled_base_matches_cpu(case, capfd):
    # #988 Principled base colour runs through gpu_principledBaseTexel; 8x8 blocks
    # absorb the specular lobe's MC noise.
    gpu = _render(CASES[case], True, principled=True)
    err = capfd.readouterr().err
    cpu = _render(CASES[case], False, principled=True)
    assert "[#1007] DEGRADED" not in err, err[-800:]
    g = gpu.reshape(RES // 8, 8, RES // 8, 8, 3).mean(axis=(1, 3))
    c = cpu.reshape(RES // 8, 8, RES // 8, 8, 3).mean(axis=(1, 3))
    assert np.abs(g - c).mean() < 0.02, np.abs(g - c).mean()


@pytest.mark.gpu
def test_gpu_bake_fallback_is_reported(capfd):
    _render(_tex_checker_object, True)
    err = capfd.readouterr().err
    assert "[#1007] DEGRADED" in err and "Object coordinates" in err, err[-800:]

"""#1174: a Mix Shader whose per-texel Fac reads UV coordinates is mixed per hit on the GPU.

Corpus v2 `v2_textures_opvm` sphere_MixShaderProg (Mix(Principled metal, Principled
dielectric, Voronoi(UV).Distance)) read 0.87 of Cycles on the GPU while the CPU passed.
The closure tree lowered and its Fac graph program uploaded, but scene_upload's UV gate
(classifyUvGate) looked at the Mix node, whose getters follow child A only: the sphere's
triangles uploaded no UVs, the Fac program's UV-mode input missed on every hit (NaN) and
the device kept the constant Fac 0.5. Generated-coordinate Facs (the #995 tests) need no
UVs, so they passed.

Reference (analytic): Lambertian leaves under a uniform white sky of radiance 1 return
L = (1 - fac) albedo_A + fac albedo_B. Twin: the sphere's own tree, GPU vs CPU per block.
"""
import astroray
import numpy as np
import pytest
from base_helpers import create_renderer, render_image, setup_camera

from test_issue818_procedural_opvm import Link, Sock
from test_issue995_closure_mix import _cells, _engine, _VFOV
from test_pkg293_gpu_lobe_programs import _node

_W = _H = 48
RED, BLUE = [0.6, 0.1, 0.1], [0.1, 0.1, 0.6]
C1, C2 = 0.8, 0.3                       # Checker Color1 / Color2 (grey) = Fac per cell


def _uv():
    return Link(_node('TEX_COORD', 'TexCoord'), 'UV')


def _mix(fac_link, a, b):
    return _node('MIX_SHADER', 'Mix', [Sock('Fac', 0.5, fac_link),
                                       Sock('Shader', None, Link(a, 'BSDF')),
                                       Sock('Shader_001', None, Link(b, 'BSDF'))])


def _checker_mix():
    chk = _node('TEX_CHECKER', 'Chk', [Sock('Vector', None, _uv()), Sock('Scale', 2.0),
                                       Sock('Color1', [C1, C1, C1, 1.0]),
                                       Sock('Color2', [C2, C2, C2, 1.0])])
    dif = [_node('BSDF_DIFFUSE', n, [Sock('Color', c + [1.0]), Sock('Roughness', 0.0)])
           for n, c in (('Red', RED), ('Blue', BLUE))]
    return _mix(Link(chk, 'Color'), *dif)


def _sphere_mix():
    """The corpus sphere's tree (build_corpus.py _v2_textures_opvm mix_prog), with
    distinct base colours so the per-texel Fac is visible under a uniform sky."""
    vor = _node('TEX_VORONOI', 'Vor', [Sock('Vector', None, _uv()), Sock('W', 0.0),
                                       Sock('Scale', 4.0), Sock('Detail', 0.0),
                                       Sock('Roughness', 0.5), Sock('Lacunarity', 2.0),
                                       Sock('Smoothness', 1.0), Sock('Exponent', 0.5),
                                       Sock('Randomness', 1.0)],
                feature='F1', distance='EUCLIDEAN', normalize=False, voronoi_dimensions='3D')
    a = _node('BSDF_PRINCIPLED', 'Metal', [Sock('Base Color', [0.9, 0.55, 0.3, 1.0]),
                                           Sock('Metallic', 1.0), Sock('Roughness', 0.15)])
    b = _node('BSDF_PRINCIPLED', 'Dielectric', [Sock('Base Color', [0.1, 0.3, 0.8, 1.0]),
                                                Sock('Metallic', 0.0), Sock('Roughness', 0.7)])
    return _mix(Link(vor, 'Distance'), a, b)


def _render(monkeypatch, tree, use_gpu, samples=192):
    r = create_renderer()
    if use_gpu:
        if not (astroray.__features__.get("cuda", False) and getattr(r, "gpu_available", False)):
            pytest.skip("No CUDA GPU — the #1174 GPU leg runs on the RTX box.")
        r.set_use_gpu(True)
    r.set_seed(5)
    r.set_adaptive_sampling(False)
    r.set_background_color([1.0, 1.0, 1.0])
    eng = _engine(monkeypatch)
    spec = eng._shader_spec_from_node(tree, r, None)
    mat = eng._create_material_from_shader_spec(spec, r)
    assert spec['kind'] == 'mix' and str(spec.get('fac_texture')).startswith('_graph_'), spec
    assert not eng._degradation_report().messages()
    caps = r.get_material_backend_capabilities(mat)
    assert not caps['gpu_approximate'] and '2 closures' in caps['notes'], caps
    A, B, C, D = [-1, -1, 0], [1, -1, 0], [1, 1, 0], [-1, 1, 0]
    n = [0, 0, 1]
    r.add_triangle_layers(A, B, C, mat, {"UVMap": [[0, 0], [1, 0], [1, 1]]}, n, n, n)
    r.add_triangle_layers(A, C, D, mat, {"UVMap": [[0, 0], [1, 1], [0, 1]]}, n, n, n)
    setup_camera(r, look_from=[0, 0, 3], look_at=[0, 0, 0], vup=[0, 1, 0],
                 vfov=_VFOV, width=_W, height=_H)
    return np.asarray(render_image(r, samples=samples, max_depth=4, apply_gamma=False))


@pytest.mark.parametrize("use_gpu", [False, True], ids=["cpu", "gpu"])
def test_uv_checker_fac_matches_analytic(monkeypatch, use_gpu):
    cells = _cells(_render(monkeypatch, _checker_mix(), use_gpu))
    x = (1.0 - C1) * np.array(RED) + C1 * np.array(BLUE)
    y = (1.0 - C2) * np.array(RED) + C2 * np.array(BLUE)
    got = cells[np.argsort(cells[:, 0])]          # the Fac 0.8 cells have the lower red
    want = np.array([x, x, y, y])
    assert np.allclose(got, want, rtol=0.05, atol=0.01), (
        f"{'GPU' if use_gpu else 'CPU'} per-cell radiance != (1-fac) red + fac blue "
        f"(a constant Fac 0.5 gives {0.5 * (np.array(RED) + np.array(BLUE))} everywhere)\n"
        f" got={got}\nwant={want}")


def test_sphere_tree_uv_voronoi_fac_gpu_cpu_twin(monkeypatch):
    gpu = _render(monkeypatch, _sphere_mix(), use_gpu=True, samples=256)
    cpu = _render(monkeypatch, _sphere_mix(), use_gpu=False, samples=256)
    k = _W // 6                                    # 6 x 6 blocks of 8 x 8 px

    def blocks(img):
        return img.reshape(6, k, 6, k, 3).mean(axis=(1, 3)).reshape(-1, 3)

    g, c = blocks(gpu), blocks(cpu)
    # The pattern itself must reach the GPU (constant Fac: near-uniform blocks).
    assert np.std(c[:, 2]) > 0.03, np.std(c[:, 2])
    ratio = g.mean(0) / c.mean(0)
    assert np.allclose(ratio, 1.0, atol=0.03), f"GPU/CPU frame mean {ratio}"
    corr = np.corrcoef(g[:, 2], c[:, 2])[0, 1]
    assert corr > 0.95, f"GPU/CPU per-block blue correlation {corr:.3f}"
    assert np.allclose(g, c, rtol=0.08, atol=0.02), f"max |GPU-CPU| {np.abs(g - c).max():.3f}"

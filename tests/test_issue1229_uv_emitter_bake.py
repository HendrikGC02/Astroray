"""#1229 - v2_textures_opvm CardWave and CardMapAfterWarp fail Welch-1b on GPU only.

Root cause: an emitter's procedural Emission Color is not evaluated per hit on the
GPU (the intersect / shadow kernels carry no evaluator, #962), so scene_upload.cu
bakeProceduralTexId bakes it with the CPU evaluator. A UV-coordinate texture baked
into a 64^2 grid sampled NEAREST (gpu_sampleImageTexture): on a card ~70 px wide
that is about one texel per pixel, so the Wave bands (scale 4 -> 12.7 periods,
distortion 3) and the warped Mapping -> Checker edges are stair-stepped. The CPU
evaluates the same evaluator exactly; the shared op-VM / Wave / Noise math is not
at fault (CPU passes against Cycles). Fix: a UV bake is 1024^2.

Gate: the worst 8x8-tile relative bias per channel of GPU vs CPU (the Welch-1b
tile and its 1 % margin). A noise-free model of the nearest bake on this card
predicts 2.8 % (Wave) / 10 % (warped Checker, red) at 64^2 and 0.2 % / 0.5 % at
1024^2; measured on main 000cd943 (64^2): 3.6 % / 11.4 %.

Cards: the two corpus witnesses' node trees as the addon loads them (bpy stubbed,
real astroray Renderer), on a UV-mapped emission quad at the corpus' pixel density.
GPU-gated: skips without a CUDA device (CI has none) - an RTX-box leg.
"""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(__file__))
from base_helpers import setup_camera
from test_am_nodes_944_945_891 import _checker, _engine, _noise_warp_card
from test_pkg277_coordinate_program import Link, Node, Sock

astroray = pytest.importorskip("astroray")

W = 96
SZ = 0.85      # card edge; at vfov 26 from 2.5 the card spans ~71 px (corpus card: ~73 px)
SPP = 256
WIN = slice(18, 78)


def _wave_card(uv):
    """CardWave: Wave (Bands X, Sine) at UV, Scale 4, Distortion 3, other inputs default."""
    return Node('TEX_WAVE', name='Wave', wave_type='BANDS', bands_direction='X',
                wave_profile='SIN', inputs=[
                    Sock('Vector', (0, 0, 0), Link(uv, 'UV')), Sock('Scale', 4.0),
                    Sock('Distortion', 3.0), Sock('Detail', 2.0), Sock('Detail Scale', 1.0),
                    Sock('Detail Roughness', 0.5), Sock('Phase Offset', 0.0)])


def _load_card(kind, monkeypatch, r):
    eng = _engine(monkeypatch)
    uv = Node('TEX_COORD')
    if kind == "wave":
        node = _wave_card(uv)
        vec = node.inputs.get('Vector')
    else:  # map_after_warp: UV + 0.35 * Noise(UV) -> Mapping -> Checker
        m, _ = _noise_warp_card(uv)
        vec = Sock('Vector', (0, 0, 0), Link(m, 'Vector'))
        node = _checker(vec)
    name = eng.load_procedural_texture(node, r, vector_input=vec)
    assert name, f"{kind}: addon did not load the card texture"
    return name


def _has_cuda_gpu():
    r = astroray.Renderer()
    return bool(astroray.__features__.get("cuda", False)) and bool(getattr(r, "gpu_available", False))


def _render(kind, gpu, monkeypatch):
    r = astroray.Renderer()
    r.set_integrator("path_tracer")
    r.set_adaptive_sampling(False)
    r.set_seed(7)
    if gpu:
        r.set_use_gpu(True)
    r.set_background_color([0.0, 0.0, 0.0])
    tex = _load_card(kind, monkeypatch, r)
    m = r.create_material("light", [1, 1, 1], {"intensity": 1.0, "texture": tex})
    h = SZ / 2
    a, b, c, d = [-h, -h, 0], [h, -h, 0], [h, h, 0], [-h, h, 0]
    n = [0, 0, 1]
    r.add_triangle_layers(a, b, c, m, {"UVMap": [[0, 0], [1, 0], [1, 1]]}, n, n, n)
    r.add_triangle_layers(a, c, d, m, {"UVMap": [[0, 0], [1, 1], [0, 1]]}, n, n, n)
    setup_camera(r, look_from=[0, 0, 2.5], look_at=[0, 0, 0], vup=[0, 1, 0], vfov=26,
                 width=W, height=W)
    px = np.asarray(r.render(SPP, 4, None, False), np.float32).reshape(W, W, 3)
    return px[WIN, WIN]


@pytest.mark.gpu
@pytest.mark.parametrize("kind", ["wave", "map_after_warp"])
def test_uv_emitter_card_gpu_matches_cpu(kind, monkeypatch):
    if not _has_cuda_gpu():
        pytest.skip("No CUDA GPU - #1229 GPU leg runs on the RTX box.")
    cpu, gpu = _render(kind, False, monkeypatch), _render(kind, True, monkeypatch)
    ratio = float(gpu.mean() / cpu.mean())
    rel = float(np.abs(gpu - cpu).mean() / cpu.mean())
    tg, tc = (x[:56, :56].reshape(7, 8, 7, 8, 3).mean(axis=(1, 3)) for x in (gpu, cpu))
    tile = float(np.max(np.abs(tg - tc) / np.maximum(tc, 1e-6)))
    print(f"[#1229] {kind}: ratio {ratio:.4f} px rel|d| {rel:.4f} tile8 max rel bias {tile:.4f}")
    assert 0.98 <= ratio <= 1.02, f"{kind}: GPU/CPU mean ratio {ratio:.4f}"
    assert tile <= 0.01, f"{kind}: worst 8x8-tile GPU/CPU relative bias {tile:.4f} > 1 %"

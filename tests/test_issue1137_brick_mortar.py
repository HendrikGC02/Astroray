"""Issue #1137 -- the addon must export the Brick Texture 'Mortar' socket colour.

It used to read a non-existent 'Color3' socket and silently fell back to black.
  * stub-bpy: the exported mortar params equal the Mortar socket value.
  * CPU render: mortar red vs mortar black differ only in the mortar region.
  * GPU twin (gpu marker): the GPU bakes the same CPU BrickTexture, so same contrast.
"""
import numpy as np
import pytest
import astroray
from base_helpers import create_renderer, render_image, setup_camera
from test_pkg115_addon_texture_translation import _load_blender_addon, _Node, _Socket


def _brick_node(mortar):
    return _Node('TEX_BRICK', inputs={
        'Vector': _Socket(),
        'Color1': _Socket(default=(0.1, 0.1, 0.8, 1.0)),
        'Color2': _Socket(default=(0.1, 0.1, 0.6, 1.0)),
        'Mortar': _Socket(default=mortar),
        'Scale': _Socket(default=4.0),
        'Mortar Size': _Socket(default=0.08),
        'Mortar Smooth': _Socket(default=0.0),
        'Bias': _Socket(default=0.0),
        'Brick Width': _Socket(default=0.5),
        'Row Height': _Socket(default=0.25),
        'Offset': _Socket(default=0.5),
    }, offset_frequency=2, squash=1.0, squash_frequency=2)


def test_exported_mortar_equals_socket(monkeypatch):
    addon = _load_blender_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    calls = []
    rec = type("R", (), {"create_procedural_texture": lambda s, n, t, p, *a: calls.append(list(p)),
                         "set_texture_coord_mode": lambda s, *a: None,
                         "set_texture_uv_transform": lambda s, *a, **k: None})()
    node = _brick_node((0.9, 0.2, 0.1, 1.0))
    engine.load_procedural_texture(node, rec, vector_input=node.inputs['Vector'])
    assert calls[0][6:9] == pytest.approx([0.9, 0.2, 0.1])


def _scene_render(monkeypatch, mortar, use_gpu):
    r = create_renderer()
    if use_gpu:
        if not (astroray.__features__.get("cuda") and getattr(r, "gpu_available", False)):
            pytest.skip("No CUDA GPU")
        r.set_use_gpu(True)
    r.set_seed(1)
    r.set_background_color([0.8, 0.8, 0.8])
    # Same call the addon makes (verified by test_exported_mortar_equals_socket).
    addon = _load_blender_addon(monkeypatch)
    node = _brick_node(mortar)
    names = []
    orig = r.create_procedural_texture
    class Wrap:
        def create_procedural_texture(self, n, t, p, *a):
            names.append(n); return orig(n, t, p, *a)
        def __getattr__(self, k): return getattr(r, k)
    addon.CustomRaytracerRenderEngine().load_procedural_texture(
        node, Wrap(), vector_input=node.inputs['Vector'])
    r.set_texture_generated_bbox(names[0], [-1, -1, -1], [2, 2, 2])
    mat = r.create_material("lambertian", [0.8, 0.8, 0.8], {"texture": names[0]})
    A, B, C, D = [-1, -1, 0], [1, -1, 0], [1, 1, 0], [-1, 1, 0]
    n = [0, 0, 1]
    r.add_triangle_layers(A, B, C, mat, {"UVMap": [[0, 0], [1, 0], [1, 1]]}, n, n, n)
    r.add_triangle_layers(A, C, D, mat, {"UVMap": [[0, 0], [1, 1], [0, 1]]}, n, n, n)
    setup_camera(r, look_from=[0, 0, 3], look_at=[0, 0, 0], vup=[0, 1, 0],
                 vfov=45, width=64, height=64)
    return render_image(r, samples=32, max_depth=2, apply_gamma=False)


def _check(monkeypatch, use_gpu, tag):
    red = _scene_render(monkeypatch, (0.9, 0.05, 0.05, 1.0), use_gpu)
    blk = _scene_render(monkeypatch, (0.0, 0.0, 0.0, 1.0), use_gpu)
    import os
    out = os.environ.get("I1137_EVIDENCE")
    if out:
        from PIL import Image
        for nm, im in (("red", red), ("black", blk)):
            Image.fromarray((np.clip(im, 0, 1) ** (1 / 2.2) * 255).astype(np.uint8)).save(
                os.path.join(out, f"{tag}_mortar_{nm}.png"))
    dr = red[..., 0] - blk[..., 0]
    mask = dr > 0.05                       # mortar pixels
    assert mask.mean() > 0.03, f"mortar red vs black barely differ (frac={mask.mean():.4f})"
    assert dr[mask].mean() > 0.1
    # brick pixels (blue-dominant in both renders) are unaffected by the mortar colour
    brick = (blk[..., 2] > 0.2) & ~mask
    assert brick.mean() > 0.3
    assert np.abs(red[brick] - blk[brick]).mean() < 0.02


def test_cpu_mortar_colour_reaches_render(monkeypatch):
    _check(monkeypatch, False, "cpu")


@pytest.mark.gpu
def test_gpu_mortar_colour_reaches_render(monkeypatch):
    _check(monkeypatch, True, "gpu")

"""pkg115 item 10 - standalone Voronoi factory example (no Blender required).

Demonstrates building a Voronoi-textured material through the public
`create_procedural_texture` factory API and verifies the factory forwards the
full Cycles-parity parameter vector (the same path the Blender addon translator
uses). The parameter layout (module/blender_module.cpp, "voronoi"):

    [scale, randomness, dist_metric, feature, smoothness,
     r1,g1,b1, r2,g2,b2,                       # color_low, color_high
     detail, roughness, lacunarity, exponent, normalize]   # pkg115 item 10

Legacy 5-param + colour scripts (<= 11 values) keep working unchanged; the
trailing detail/roughness/lacunarity/exponent/normalize default off, so a bare
voronoi stays a non-fractal F1.
"""
import os
import numpy as np

from base_helpers import (
    create_renderer, setup_camera, render_image, assert_valid_image,
    save_image, get_output_dir,
)

OUTPUT_DIR = get_output_dir()


def _render_voronoi(params, seed=7, w=72, h=54):
    """Build a single Voronoi-textured sphere via the factory and render it."""
    r = create_renderer()
    r.set_seed(seed)
    r.set_adaptive_sampling(False)
    r.set_background_color([0.0, 0.0, 0.0])
    r.create_procedural_texture("vor", "voronoi", params, "GENERATED")
    mat = r.create_material('lambertian', [1, 1, 1], {'texture': 'vor'})
    light = r.create_material('light', [1, 1, 1], {'intensity': 7.0})
    r.add_sphere([0, 0, 0], 1.0, mat)
    r.add_sphere([0, 4, 2], 0.6, light)
    setup_camera(r, look_from=[0, 0, 4], look_at=[0, 0, 0], vfov=40, width=w, height=h)
    return render_image(r, samples=12)


def test_voronoi_factory_standalone_renders():
    """The factory builds a textured material without Blender and renders it."""
    img = _render_voronoi([6.0, 1.0, 0.0, 0.0, 1.0, 0, 0, 0, 1, 1, 1])
    assert_valid_image(img, 54, 72, min_mean=0.01, label='voronoi_standalone')
    save_image(img, os.path.join(OUTPUT_DIR, 'test_pkg115_voronoi_standalone.png'))


def test_voronoi_factory_forwards_trailing_params():
    """The trailing params (params[11:16]) must reach VoronoiTexture. They are
    read as one block, so proving any one is forwarded proves the tail is.
    `normalize` (params[15]) rescales the whole distance field by ~1/sqrt(3),
    a large albedo change, giving an unambiguous signal through the render."""
    base = [6.0, 1.0, 0.0, 0.0, 1.0, 0, 0, 0, 1, 1, 1]
    img_plain = _render_voronoi(base, seed=7)
    # Control: identical params + same seed -> fully deterministic render, so the
    # per-pixel floor is ~0. Anything clearly above it is a genuine texture change.
    img_plain2 = _render_voronoi(base, seed=7)
    floor = float(np.mean(np.abs(img_plain2 - img_plain)))
    assert floor < 1e-5, f"render not deterministic at fixed seed (floor={floor:.2e})"
    # Only difference vs base: normalize=1 (params[15]); detail stays 0.
    img_norm = _render_voronoi(base + [0.0, 0.5, 2.0, 0.5, 1.0], seed=7)
    assert_valid_image(img_norm, 54, 72, min_mean=0.01, label='voronoi_normalized')
    mad = float(np.mean(np.abs(img_norm - img_plain)))
    # Lambertian shading damps texture contrast, so the absolute MAD is modest,
    # but it is hundreds of times the deterministic floor -- proof the trailing
    # params reach VoronoiTexture (the factory does not drop params[11:16]).
    assert mad > 0.003, (
        f"normalize param had no effect: per-pixel MAD={mad:.4f} (floor={floor:.2e}) "
        f"-- factory may be dropping params[11:16]"
    )

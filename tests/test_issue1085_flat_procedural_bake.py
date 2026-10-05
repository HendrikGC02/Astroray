"""#1085 - procedural swatches on flat geometry differ CPU vs GPU (gate (c)
textures_mapping: structure, a uniform offset, ring phase).

Root cause: an emitter's procedural Emission Color is not evaluated per hit on the
GPU (the intersect / shadow kernels carry no evaluator); scene_upload.cu bakes it
into a 64^3 nearest-voxel cube. A default flat plane has Generated z = 0.5, which
is exactly a voxel FACE of a 64-cell axis, so the bake read the cell centred at
31.5/64: a z-dependent texture (Wave Bands along Z) came out uniformly offset
(measured GPU/CPU mean 0.80), and detail finer than 1/64 of the card aliased
(Magic corr 0.49, Brick 0.69). Fix: a Generated procedural on flat geometry bakes
a 2-layer 512^2 slice at the plane's exact Generated coordinate (the same 262k
evaluations as the cube).

Cards: one flat quad per texture node configuration of the corpus swatches
(textures_mapping.blend parameters, as the addon passes them to
create_procedural_texture), Generated coordinates with the addon's texspace bbox
(a flat axis is a 2-thick slab centred on the plane) and the #847 per-vertex
Generated frame, lit by emission only. Mean ratio and per-pixel correlation of the
GPU render against the CPU (the oracle; Cycles agrees with the CPU on Wave Bands).

GPU-gated: skips without a CUDA device (CI has none) - an RTX-box leg.
"""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent))
from base_helpers import setup_camera  # noqa: E402

astroray = pytest.importorskip("astroray")

W = 96
SZ = 0.85
SPP = 64

# (create_procedural_texture type, params) exactly as blender_addon/__init__.py builds
# them for the textures_mapping.blend swatches.
LEAF = {
    "noise_hetero3d": ("noise_perlin", [8, 4, 0.7, 2.5, 0.3, 1.4, 0.6, 4, 0, 3, 0, 1]),
    "voronoi": ("voronoi", [6, 0.8, 1, 1, 0.3, 0, 0, 0, 1, 1, 1, 2.0, 0.6, 2.2, 2.0, 1, 0]),
    "wave_bands_z_nodist": ("wave", [0, 2, 0, 1, 4, 0.0, 0, 1.0, 0.5, 0.8, 0, 0, 0, 1, 1, 1]),
    "wave_bands_z": ("wave", [0, 2, 0, 1, 4, 1.2, 3, 1.5, 0.6, 0.8, 0, 0, 0, 1, 1, 1]),
    "wave_rings_sph": ("wave", [1, 0, 3, 2, 3, 0, 2, 1, 0.5, 0, 0, 0, 0, 1, 1, 1]),
    "magic": ("magic", [4, 6.0, 2.5, 0, 0, 0, 1, 1, 1]),
    "brick": ("brick", [0.65, 0.25, 0.18, 0.15, 0.1, 0.08, 0, 0, 0, 6.0, 0.08, 0.3, 0.4, 0.4,
                        0.2, 0.5, 2, 1.0, 2]),
}


def _has_cuda_gpu():
    r = astroray.Renderer()
    return bool(astroray.__features__.get("cuda", False)) and bool(getattr(r, "gpu_available", False))


def _render(kind, gpu):
    typ, params = LEAF[kind]
    r = astroray.Renderer()
    r.set_integrator("path_tracer")
    r.set_seed(7)
    if gpu:
        r.set_use_gpu(True)
    r.set_background_color([0.0, 0.0, 0.0])
    r.create_procedural_texture("t", typ, [float(x) for x in params], "GENERATED")
    h = SZ / 2
    r.set_texture_generated_bbox("t", [-h, -h, -1.0], [SZ, SZ, 2.0])
    m = r.create_material("light", [1, 1, 1], {"intensity": 1.6, "texture": "t"})
    a, b, c, d = [-h, -h, 0], [h, -h, 0], [h, h, 0], [-h, h, 0]
    n = [0, 0, 1]
    first = r.scene_object_count()
    r.add_triangle_layers(a, b, c, m, {"UVMap": [[0, 0], [1, 0], [1, 1]]}, n, n, n)
    r.add_triangle_layers(a, c, d, m, {"UVMap": [[0, 0], [1, 1], [0, 1]]}, n, n, n)
    # world -> Generated, (p - loc) * 0.5 / size + 0.5; the flat axis' size is clamped
    # to 1 (BKE_mesh_texspace_calc), so the plane sits at Generated z = 0.5.
    sx = 1.0 / SZ
    r.set_objects_generated_transform(first, r.scene_object_count(),
                                      [sx, 0, 0, 0.5, 0, sx, 0, 0.5, 0, 0, 0, 0.5])
    setup_camera(r, look_from=[0, 0, 2.5], look_at=[0, 0, 0], vup=[0, 1, 0], vfov=26,
                 width=W, height=W)
    px = np.asarray(r.render(SPP, 4, None, False), np.float32).reshape(W, W, 3)
    return px[18:78, 18:78].mean(axis=2)


@pytest.mark.gpu
@pytest.mark.parametrize("kind", sorted(LEAF))
def test_flat_procedural_card_gpu_matches_cpu(kind):
    if not _has_cuda_gpu():
        pytest.skip("No CUDA GPU - #1085 GPU leg runs on the RTX box.")
    cpu, gpu = _render(kind, False), _render(kind, True)
    ratio = gpu.mean() / cpu.mean()
    assert 0.97 <= ratio <= 1.03, f"{kind}: GPU/CPU mean ratio {ratio:.3f}"
    if cpu.std() > 0.02:  # a (near-)uniform card has no structure to correlate
        corr = float(np.corrcoef(cpu.ravel(), gpu.ravel())[0, 1])
        assert corr >= 0.85, f"{kind}: GPU/CPU per-pixel correlation {corr:.3f}"

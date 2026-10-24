"""pkg325: engine-only build of the acceptance scene (same triangles as build_blend.py).

    r = astroray.Renderer(); build(r, w, h); img = render(r, "cpu", spp, cap)
"""
from __future__ import annotations

import math

import numpy as np

from . import scene_geometry as G

GLASS_PARAMS = {"roughness": 0.0, "ior": 1.5, "transmission_weight": 1.0}   # what the addon sends for a Cycles Glass BSDF


def build(r, w: int = G.RES[0], h: int = G.RES[1], world: float = 1.0) -> None:
    r.set_background_color([world, world, world])
    glass_mat = r.create_material("principled", [1.0, 1.0, 1.0], dict(GLASS_PARAMS))
    for m in G.scene_meshes():
        pos = G.to_engine(m.tris)
        nrm = G.to_engine(G.corner_normals(m.tris, m.smooth))
        n = len(pos)
        mat = glass_mat if m.kind == "glass" else r.create_material("lambertian", list(m.color), {})
        r.add_triangles_bulk(pos.astype(np.float32), np.full(n, mat, dtype=np.int32), np.zeros(n, dtype=np.int32), 0,
                             np.zeros((1, n, 3, 2), dtype=np.float32), ["UVMap"], nrm.astype(np.float32))
    ar = w / h
    hfov = 2 * math.atan(G.CAMERA["sensor"] / 2 / G.CAMERA["lens"])
    vfov = 2 * math.atan(math.tan(hfov / 2) / ar)
    eye = G.to_engine(np.array(G.CAMERA["loc"])).tolist()
    tgt = G.to_engine(np.array(G.CAMERA["target"])).tolist()
    r.setup_camera(eye, tgt, [0, 1, 0], math.degrees(vfov), ar, 0.0, 6.0, w, h)


def render(r, backend: str, spp: int, cap: int, seed: int = 325, **kw) -> np.ndarray:
    """backend 'cpu' | 'gpu'. Returns (h, w, 3) float32 linear."""
    r.set_integrator("path_tracer")
    r.set_seed(seed)
    r.set_adaptive_sampling(False)
    if backend == "gpu":
        r.set_use_gpu(False)
        r.render(1, 2, None, False)   # warm-up on CPU (scene build), as the replay tools do
    r.set_use_gpu(backend == "gpu")
    return np.asarray(r.render(spp, cap, None, False, **kw), dtype=np.float32)

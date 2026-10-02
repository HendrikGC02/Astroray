"""pkg300 — the register-budgeted shade kernel equals the pre-pkg300 kernel.

The fleet shade kernel is fully inlined under __maxnreg__(128) (pkg300 Phase 1).
ASTRORAY_SHADE_REFERENCE=1 selects the pre-pkg300 form (out-of-line body, no cap,
stage_shade_reference.cu) for fleet-axis launches. Each scene renders once per
mode in a fresh subprocess (the env is read once per process) at a fixed seed;
the two images must agree per pixel within 1e-5 * max(1, |ref|) (the spec's
1e-5 abs, relative above radiance 1).

Measured 2026-10-02 (128^2, 16 spp): the REFERENCE alone is not reproducible
to 1e-6. The shadow/continuation queues are filled with atomics, so the float
accumulation order into a pixel follows block scheduling. Two reference runs
differ by up to 1.3e-5 abs on emitter pixels (radiance ~19, ~6 ulp) and 9.5e-7
on LDR pixels. Inlining changes FMA contraction, so new vs reference reaches
6.7e-6 abs (1.5e-5 rel, 2 of 49152 values) on closure_graph_cornell, with a
mean signed difference of 3e-10 (no bias).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCENES = ("cornell_simple", "cornell_heavy", "closure_graph_cornell", "principled_spheres")
TOL = 1e-5


def _render(scene: str, out: str) -> None:
    """Child process: render one scene on the GPU and save the linear image."""
    sys.path.insert(0, str(ROOT / "tests"))
    sys.path.insert(0, str(ROOT))
    from runtime_setup import configure_test_imports
    configure_test_imports()
    if scene.startswith("cornell_"):
        sys.argv = [sys.argv[0]]
        sys.path.insert(0, str(ROOT / "benchmarks"))
        import wavefront_baseline as wb
        pos, mid = wb.write_cornell_npy(scene.split("_", 1)[1])
        cfg = {"pos": str(pos), "mid": str(mid), "device": "gpu", "res": 128,
               "spp": 16, "depth": 8, "calls": 1, "save_img": out}
        wb._astro_child(cfg)
        return
    import base_helpers as bh
    r = bh.create_renderer()
    r.set_use_gpu(True)
    if not getattr(r, "gpu_available", False):
        print("PKG300_NO_GPU")
        return
    r.set_seed(300)
    r.set_adaptive_sampling(False)
    if scene == "closure_graph_cornell":
        from scenes import closure_graph_cornell as sc
        sc.build_scene(r)
        sc.setup_camera(r, width=128, height=128)
    else:  # principled_spheres: HasPrincipled=true fleet variant
        r.set_background_color([0.05, 0.05, 0.08])
        floor = r.create_material("lambertian", [0.6, 0.6, 0.6], {})
        r.add_sphere([0.0, -100.5, 0.0], 100.0, floor)
        for k, (col, rough, metal) in enumerate([([0.8, 0.2, 0.1], 0.3, 0.0),
                                                  ([0.9, 0.8, 0.5], 0.2, 1.0),
                                                  ([0.2, 0.5, 0.9], 0.6, 0.0)]):
            m = r.create_material("principled", col, {"roughness": rough, "metallic": metal})
            r.add_sphere([-1.1 + 1.1 * k, 0.0, 0.0], 0.5, m)
        light = r.create_material("light", [1.0, 0.95, 0.9], {"intensity": 6.0})
        r.add_sphere([0.0, 2.5, 1.0], 0.6, light)
        bh.setup_camera(r, look_from=[0, 0.8, 4.0], look_at=[0, 0, 0], vup=[0, 1, 0],
                        vfov=40.0, width=128, height=128)
    img = bh.render_image(r, samples=16, max_depth=8, apply_gamma=False)
    np.save(out, np.asarray(img, dtype=np.float32))
    print("PKG300_OK")


def _run(scene: str, out: Path, reference: bool) -> np.ndarray:
    env = os.environ.copy()
    env.pop("ASTRORAY_SHADE_REFERENCE", None)
    if reference:
        env["ASTRORAY_SHADE_REFERENCE"] = "1"
    proc = subprocess.run([sys.executable, str(Path(__file__).resolve()), scene, str(out)],
                          env=env, capture_output=True, text=True, check=False)
    if "PKG300_NO_GPU" in proc.stdout:
        pytest.skip("gpu_available is False")
    assert proc.returncode == 0 and out.exists(), proc.stderr[-2000:]
    return np.load(out)


@pytest.mark.gpu
@pytest.mark.parametrize("scene", SCENES)
def test_budgeted_shade_matches_reference(scene, tmp_path):
    ref = _run(scene, tmp_path / "ref.npy", reference=True)
    new = _run(scene, tmp_path / "new.npy", reference=False)
    assert ref.shape == new.shape
    assert np.isfinite(new).all()
    assert float(ref.mean()) > 1e-4, "scene rendered black: comparison would be vacuous"
    diff = np.abs(new.astype(np.float64) - ref.astype(np.float64))
    bound = TOL * np.maximum(1.0, np.abs(ref.astype(np.float64)))
    worst = np.unravel_index(int(np.argmax(diff - bound)), diff.shape)
    assert (diff <= bound).all(), json.dumps({
        "scene": scene, "max_abs": float(diff.max()), "at": [int(i) for i in worst],
        "ref": float(ref[worst]), "new": float(new[worst])})


if __name__ == "__main__":
    _render(sys.argv[1], sys.argv[2])

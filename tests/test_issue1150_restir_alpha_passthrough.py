"""#1150 - ReSTIR-DI through a fully transparent (alpha 0) Principled sheet.

A transparent pass is not a bounce (#1033): the path tracer already passes the sheet
for free on both devices. Before the fix
  * CPU ReSTIR-DI spent a bounce on the pass (black at max_depth=0, one indirect
    bounce short at max_depth=1; #1165 terminate-after semantics, so the issue's
    pre-#1165 "max_depth=1" row is max_depth=0 here),
  * GPU ReSTIR-DI shaded the sheet itself (its BSDF is alpha-weighted to 0): black
    at every depth.
Scene: the issue's probe (16x16, lambertian floor + sphere, 6.0 area light, a
full-frame alpha-0 sheet between camera and sphere, seed 7, no ReSTIR reuse).

GPU ReSTIR-DI is direct-lighting only (cuda_wavefront_render_restir ignores
max_depth), so its path-tracer reference is the max_depth=0 render.
"""
import numpy as np
import pytest

astroray = pytest.importorskip("astroray")

W = 16
SPP = 256
REL_TOL = 0.03  # 64-spp seed-to-seed sd is ~0.5-0.9% of the mean; 256 spp halves it


def _gpu_available():
    try:
        return bool(astroray.Renderer().gpu_available)
    except Exception:
        return False


BACKENDS = [
    pytest.param(False, id="cpu"),
    pytest.param(True, id="gpu", marks=[
        pytest.mark.gpu,
        pytest.mark.skipif(not _gpu_available(), reason="CUDA device not available")]),
]


def _mean(integrator, sheet, depth, use_gpu):
    r = astroray.Renderer()
    r.setup_camera([0, 0, 4], [0, 0, 0], [0, 1, 0], 40.0, 1.0, 0.0, 4.0, W, W)
    r.set_background_color([0.0, 0.0, 0.0])
    r.set_seed(7)
    r.set_adaptive_sampling(False)
    if integrator == "restir-di":
        r.set_integrator_param("use_temporal", 0)
        r.set_integrator_param("use_spatial", 0)
    r.set_integrator(integrator)
    g = r.create_material("lambertian", [0.7, 0.7, 0.7], {})
    li = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 6.0})
    sh = r.create_material("principled", [1.0, 1.0, 1.0], {"alpha": 0.0})
    r.add_triangle([-2, -1, -2], [2, -1, -2], [2, -1, 2], g)
    r.add_triangle([-2, -1, -2], [2, -1, 2], [-2, -1, 2], g)
    r.add_sphere([0.0, -0.3, 0.0], 0.6, g)
    if sheet:
        r.add_triangle([-1.5, -1.5, 2.0], [1.5, -1.5, 2.0], [1.5, 1.5, 2.0], sh)
        r.add_triangle([-1.5, -1.5, 2.0], [1.5, 1.5, 2.0], [-1.5, 1.5, 2.0], sh)
    r.add_triangle([-0.5, 1.9, -0.5], [0.5, 1.9, -0.5], [0.5, 1.9, 0.5], li)
    r.add_triangle([-0.5, 1.9, -0.5], [0.5, 1.9, 0.5], [-0.5, 1.9, 0.5], li)
    r.set_use_gpu(use_gpu)
    img = np.asarray(r.render(SPP, depth, None, False), dtype=np.float64)
    assert np.isfinite(img).all()
    return float(img.mean())


@pytest.mark.parametrize("depth", [0, 1, 4])
@pytest.mark.parametrize("sheet", [False, True], ids=["nosheet", "sheet"])
@pytest.mark.parametrize("use_gpu", BACKENDS)
def test_restir_matches_path_tracer_through_alpha0_sheet(use_gpu, sheet, depth):
    ref_depth = 0 if use_gpu else depth  # GPU ReSTIR-DI is direct-only
    ref = _mean("path_tracer", sheet, ref_depth, use_gpu)
    got = _mean("restir-di", sheet, depth, use_gpu)
    print(f"  restir={got:.5f} path_tracer(depth {ref_depth})={ref:.5f}")
    assert ref > 0.02, ref
    assert abs(got - ref) <= REL_TOL * ref, (got, ref)


@pytest.mark.parametrize("depth", [0, 1, 4])
@pytest.mark.parametrize("use_gpu", BACKENDS)
def test_restir_alpha0_sheet_is_free(use_gpu, depth):
    clear = _mean("restir-di", False, depth, use_gpu)
    behind = _mean("restir-di", True, depth, use_gpu)
    print(f"  restir sheet={behind:.5f} no sheet={clear:.5f}")
    assert abs(behind - clear) <= REL_TOL * clear, (behind, clear)

"""#1072: GPU Add Shader sums the closures of its two children (CPU does since #955).

The wavefront shade kernel (HasPrincipled=true) evaluates f = f_A + f_B with the
mixture pdf 0.5 (pdf_A + pdf_B) and a 1/2 child pick (CPU twin: AddMaterial). Child A
uploads at the Add's id; child B is a hidden partner material (GMaterial::addPartner).

CPU tests (capability query, which pairs the GPU can sum) run everywhere; the GPU legs
skip without a CUDA device. Reference scene: a flat wall under a uniform white sky of
radiance 1 returns L = the wall's albedo, so Add(A, B) must render albedo_A + albedo_B
(the tests/test_issue955_add_shader.py scene).
"""
import numpy as np
import pytest

from runtime_setup import configure_test_imports

configure_test_imports()

try:
    import astroray
    HAVE_ENGINE = True
except ImportError:
    HAVE_ENGINE = False

needs_engine = pytest.mark.skipif(not HAVE_ENGINE, reason="astroray module not available")

N = 24
DIFFUSE = {"roughness": 1.0, "specular_ior_level": 0.0}
RED, BLUE = [0.6, 0.1, 0.1], [0.1, 0.1, 0.6]


def _has_cuda(r):
    return bool(astroray.__features__.get("cuda", False)) and bool(getattr(r, "gpu_available", False))


def _wall(make_material, use_gpu, spp=256, seed=5):
    r = astroray.Renderer()
    if use_gpu:
        if not _has_cuda(r):
            pytest.skip("no CUDA GPU: the GPU leg of #1072 runs on the RTX box")
        r.set_use_gpu(True)
    r.set_integrator("path_tracer")
    r.set_background_color([1.0, 1.0, 1.0])
    r.set_seed(seed)
    r.set_adaptive_sampling(False)
    r.setup_camera([0, 0, 3], [0, 0, 0], [0, 1, 0], 20.0, 1.0, 0.0, 3.0, N, N)
    mat = make_material(r)
    r.add_triangle([-20, -20, 0], [20, -20, 0], [0, 20, 0], mat)
    img = np.asarray(r.render(spp, 4, None, False), dtype=np.float32)
    c = N // 2
    return img[c - 3:c + 3, c - 3:c + 3].reshape(-1, 3).mean(axis=0)


def _approx(r, mat):
    return r.get_material_backend_capabilities(mat)["gpu_approximate"]


# ---- which pairs the GPU can sum (engine capability; drives the addon report) ----------
@needs_engine
def test_summable_pairs_are_not_gpu_approximate():
    r = astroray.Renderer()
    diffuse = r.create_material("principled", RED, DIFFUSE)
    glossy = r.create_material("principled", [0.9] * 3, {"metallic": 1.0, "roughness": 0.2})
    smooth = r.create_material("metal", [1, 1, 1], {"roughness": 0.05})  # near-delta lobe
    lam = r.create_material("lambertian", [0.4] * 3, {})
    for a, b in ((diffuse, glossy), (diffuse, smooth), (lam, glossy), (diffuse, diffuse)):
        assert not _approx(r, r.create_add_material(a, b))


@needs_engine
def test_unsummable_children_keep_the_gpu_first_only_report():
    r = astroray.Renderer()
    diffuse = r.create_material("principled", RED, DIFFUSE)
    clear = r.create_material("principled", [0.5] * 3, dict(DIFFUSE, alpha=0.5))
    glow = r.create_material("light", [1, 1, 1], {"intensity": 2.0})
    mirror = r.create_material("mirror", [1, 1, 1], {})   # no GPU lowering at all
    nested = r.create_add_material(diffuse, diffuse)
    for a, b in ((diffuse, clear), (clear, diffuse), (diffuse, glow), (glow, diffuse),
                 (diffuse, mirror), (diffuse, nested)):
        assert _approx(r, r.create_add_material(a, b))


# ---- GPU gate: Add(Diffuse red, Diffuse blue) = (0.7, 0.2, 0.7) ------------------------
def _add(kind_a, col_a, par_a, kind_b, col_b, par_b):
    def make(r):
        a = r.create_material(kind_a, col_a, par_a)
        b = r.create_material(kind_b, col_b, par_b)
        return r.create_add_material(a, b)
    return make


DIFFUSE_PAIR = _add("principled", RED, DIFFUSE, "principled", BLUE, DIFFUSE)
GLOSSY = {"metallic": 1.0, "roughness": 0.2}


@needs_engine
def test_gpu_add_two_diffuse_sums_albedos():
    got = _wall(DIFFUSE_PAIR, use_gpu=True)
    np.testing.assert_allclose(got, [0.7, 0.2, 0.7], rtol=0.06)


@needs_engine
def test_gpu_add_two_diffuse_swapped_order_matches():
    swapped = _add("principled", BLUE, DIFFUSE, "principled", RED, DIFFUSE)
    np.testing.assert_allclose(_wall(swapped, use_gpu=True), [0.7, 0.2, 0.7], rtol=0.06)


@needs_engine
def test_gpu_add_is_not_first_shader_only():
    first = _wall(lambda r: r.create_material("principled", RED, DIFFUSE), use_gpu=True)
    added = _wall(DIFFUSE_PAIR, use_gpu=True)
    assert added[2] > 3.0 * first[2]


@needs_engine
@pytest.mark.parametrize("name,make", [
    ("diffuse+glossy", _add("principled", [0.3] * 3, DIFFUSE, "principled", [0.9] * 3, GLOSSY)),
    ("glossy+diffuse", _add("principled", [0.9] * 3, GLOSSY, "principled", [0.3] * 3, DIFFUSE)),
    ("diffuse+smooth-metal", _add("principled", [0.3] * 3, DIFFUSE, "metal", [1, 1, 1], {"roughness": 0.05})),
])
def test_gpu_add_matches_cpu(name, make):
    cpu = _wall(make, use_gpu=False, spp=256)
    gpu = _wall(make, use_gpu=True, spp=256)
    np.testing.assert_allclose(gpu, cpu, rtol=0.08, err_msg=name)


@needs_engine
def test_gpu_add_diffuse_plus_glossy_exceeds_each_child():
    # Sum, not average: each child alone is below the sum by its partner's albedo.
    diffuse = _wall(lambda r: r.create_material("principled", [0.3] * 3, DIFFUSE), use_gpu=True)
    glossy = _wall(lambda r: r.create_material("principled", [0.9] * 3, GLOSSY), use_gpu=True)
    add = _wall(_add("principled", [0.3] * 3, DIFFUSE, "principled", [0.9] * 3, GLOSSY), use_gpu=True)
    np.testing.assert_allclose(add, diffuse + glossy, rtol=0.08)


@needs_engine
def test_gpu_non_add_material_is_unchanged_by_the_add_path():
    # A plain principled wall next to nothing Add-related must still render its albedo.
    got = _wall(lambda r: r.create_material("principled", RED, DIFFUSE), use_gpu=True)
    np.testing.assert_allclose(got, RED, rtol=0.06)

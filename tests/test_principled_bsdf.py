"""pkg178 Stage 1 — CPU core-lobe gates for the native "principled" material.

Per-lobe white-furnace energy conservation (LINEAR, apply_gamma=False, floor AND
ceiling — pkg166) + a registry-name-resolves / no-silent-fallback test (the
createMaterial ctor-exception-swallow binding gotcha, pkg178 spec). chi² sampler
checks live in tests/statistical/test_chi2_principled.py.

CPU only: GPU (Stage 2) and on-RTX Cycles image-plane parity are DEFERRED to the
building/verifying lead — NOT asserted here.
"""
import numpy as np
import pytest
from runtime_setup import configure_test_imports

configure_test_imports()

try:
    import astroray
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray module not available")


# ---------------------------------------------------------------------------
# Registry-name-resolves + no-silent-fallback (mandatory: createMaterial
# swallows ctor exceptions into a legacy Lambertian fallback).
# ---------------------------------------------------------------------------

def test_principled_in_registry():
    assert "principled" in astroray.material_registry_names()


def test_principled_not_silent_lambertian_fallback():
    """A metallic principled material has a GGX-peaked reflection pdf; a silent
    Lambertian fallback would report the cosine pdf (nl/pi = 0.318 at the peak).
    Query the pdf at the perfect-reflection direction for wo along the normal and
    assert it far exceeds the Lambertian ceiling — proving the real ctor ran."""
    r = astroray.Renderer()
    mat = r.create_material("principled", [0.9, 0.9, 0.9], {"metallic": 1.0, "roughness": 0.3})
    wo = [0.0, 1.0, 0.0]
    wi = np.ascontiguousarray([[0.0, 1.0, 0.0]], dtype=np.float32)  # perfect reflection of wo=normal
    pdf = r.debug_bsdf_pdf_batch(mat, wo, wi)
    assert float(pdf[0]) > 2.0, (
        f"principled metallic reflection pdf at the specular peak = {float(pdf[0]):.3f}; "
        f"a Lambertian silent-fallback would report ~0.318 (createMaterial swallowed the ctor)")


# ---------------------------------------------------------------------------
# White-furnace energy conservation (linear; floor + ceiling).
# ---------------------------------------------------------------------------

def _renderer():
    r = astroray.Renderer()
    r.setup_camera(
        look_from=[0, 0, 5], look_at=[0, 0, 0], vup=[0, 1, 0],
        vfov=45, aspect_ratio=1.0, aperture=0.0, focus_dist=5.0, width=32, height=32)
    r.set_background_color([1.0, 1.0, 1.0])
    r.set_integrator("path_tracer")
    return r


def _mean(mat_type, color, params, samples=48):
    r = _renderer()
    mid = r.create_material(mat_type, color, params)
    r.add_sphere([0, 0, 0], 1.0, mid)
    px = np.array(r.render(samples, 8, None, False), dtype=np.float32)  # linear
    return float(np.mean(px))


def _ratio(color, params, samples=48):
    ref = _mean("lambertian", [1.0, 1.0, 1.0], {}, samples)
    mat = _mean("principled", color, params, samples)
    return mat, ref


def _assert_band(label, mat, ref, floor, ceil=1.05):
    assert mat <= ref * ceil, f"{label} mean={mat:.3f} > {ceil:.2f}x white lambertian {ref:.3f} (energy GAIN)"
    assert mat >= ref * floor, f"{label} mean={mat:.3f} < {floor:.2f}x white lambertian {ref:.3f} (energy LOSS)"


def test_principled_diffuse_lambert_energy_conservation():
    # metallic=0, transmission=0 -> plastic (specular dielectric + Lambert diffuse)
    mat, ref = _ratio([1.0, 1.0, 1.0], {"metallic": 0.0, "roughness": 0.5})
    _assert_band("Principled diffuse/Lambert", mat, ref, floor=0.85)


def test_principled_diffuse_eon_energy_conservation():
    mat, ref = _ratio([1.0, 1.0, 1.0], {"metallic": 0.0, "roughness": 0.5, "diffuse_roughness": 0.8})
    _assert_band("Principled EON diffuse", mat, ref, floor=0.80)


def test_principled_metallic_f82_energy_conservation():
    for roughness in [0.3, 0.6]:
        mat, ref = _ratio([0.9, 0.9, 0.9], {"metallic": 1.0, "roughness": roughness})
        _assert_band(f"Principled metallic(r={roughness})", mat, ref, floor=0.88)


def test_principled_transmission_glass_energy_conservation():
    for roughness in [0.1, 0.4]:
        mat, ref = _ratio([1.0, 1.0, 1.0],
                          {"metallic": 0.0, "transmission_weight": 1.0, "ior": 1.5, "roughness": roughness})
        _assert_band(f"Principled glass(r={roughness})", mat, ref, floor=0.80)


# ---------------------------------------------------------------------------
# pkg178 Stage 3 advanced layers — energy conservation (linear; floor+ceiling).
# ---------------------------------------------------------------------------

def test_principled_coat_energy_conservation():
    # A clear coat over a white diffuse base. The coat reflects + Beer-absorbs;
    # net energy must stay conserved (no gain, bounded loss from coat Fresnel).
    for coat_r in [0.05, 0.3]:
        mat, ref = _ratio([1.0, 1.0, 1.0],
                          {"metallic": 0.0, "roughness": 0.5,
                           "coat_weight": 1.0, "coat_roughness": coat_r, "coat_ior": 1.5})
        _assert_band(f"Principled coat(r={coat_r})", mat, ref, floor=0.80)


def test_principled_coat_tint_absorbs():
    # coat_tint red Beer-absorbs the green reaching the base (tint^(1/cosθ),
    # Cycles svm/closure.h). Compare a red-tinted coat vs an untinted coat on the
    # SAME (white-furnace) scene: the green channel must drop under the red tint,
    # while red is ~unchanged. Relative comparison cancels the shared background.
    def _rgb(coat_tint):
        r = _renderer()
        mid = r.create_material("principled", [1.0, 1.0, 1.0],
                                {"metallic": 0.0, "roughness": 0.5, "coat_weight": 1.0,
                                 "coat_tint": coat_tint})
        r.add_sphere([0, 0, 0], 1.0, mid)
        px = np.array(r.render(48, 8, None, False), dtype=np.float32).reshape(-1, 3)
        # Sphere pixels only: the disk is < the white (sum==3) background.
        sphere = px[px.sum(axis=1) < 2.7]
        return sphere[:, 0].mean(), sphere[:, 1].mean()
    r_red, g_red = _rgb([1.0, 0.2, 0.2])
    r_white, g_white = _rgb([1.0, 1.0, 1.0])
    assert g_red < g_white * 0.85, (
        f"coat_tint red did not Beer-absorb green: g_red={g_red:.3f} g_white={g_white:.3f}")
    assert r_red > g_red * 1.15, f"coat_tint red not redder than green: R={r_red:.3f} G={g_red:.3f}"


def test_principled_sheen_energy_conservation():
    for sheen_r in [0.3, 0.8]:
        mat, ref = _ratio([1.0, 1.0, 1.0],
                          {"metallic": 0.0, "roughness": 0.5,
                           "sheen_weight": 1.0, "sheen_roughness": sheen_r})
        _assert_band(f"Principled sheen(r={sheen_r})", mat, ref, floor=0.80)


def test_principled_subsurface_approx_energy_conservation():
    # Approximate SSS (D2=a) is a Lambertian base-colour stand-in; with weight=1
    # the surface energy tracks the diffuse base (wider declared band vs Cycles).
    mat, ref = _ratio([1.0, 1.0, 1.0],
                      {"metallic": 0.0, "roughness": 0.5, "subsurface_weight": 1.0})
    _assert_band("Principled approx-SSS", mat, ref, floor=0.80)


def test_principled_emission_inside_node():
    # emission_color*emission_strength should self-illuminate on a black bg with
    # no lights; a non-emissive control stays dark.
    def _emit_mean(params):
        r = _renderer()
        r.set_background_color([0.0, 0.0, 0.0])
        mid = r.create_material("principled", [0.0, 0.0, 0.0], params)
        r.add_sphere([0, 0, 0], 1.0, mid)
        return float(np.mean(np.array(r.render(16, 4, None, False), dtype=np.float32)))
    lit = _emit_mean({"emission_color": [1.0, 1.0, 1.0], "emission_strength": 3.0})
    dark = _emit_mean({"emission_color": [0.0, 0.0, 0.0], "emission_strength": 1.0})
    assert lit > 0.1, f"principled emission produced no light (mean={lit:.4f})"
    assert dark < 1e-3, f"non-emissive principled leaked light (mean={dark:.4f})"


def test_principled_stage3_defaults_match_stage1():
    # All Stage-3 weights default to 0 -> assembleLobes must produce the identical
    # Stage-1 core-lobe stack (no regression). Compare the DETERMINISTIC bsdf pdf
    # (render() has no seed arg, so a render comparison would be MC-noisy).
    r = astroray.Renderer()
    base = {"metallic": 0.0, "roughness": 0.5}
    m_a = r.create_material("principled", [0.8, 0.6, 0.4], base)
    m_b = r.create_material("principled", [0.8, 0.6, 0.4],
                            {**base, "coat_weight": 0.0, "sheen_weight": 0.0,
                             "subsurface_weight": 0.0, "emission_strength": 5.0})
    wo = [0.3, 0.9, 0.0]
    wi = np.ascontiguousarray(
        [[0.0, 1.0, 0.0], [0.4, 0.8, 0.2], [-0.3, 0.7, 0.5]], dtype=np.float32).T
    wi = np.ascontiguousarray(wi)
    pa = np.array(r.debug_bsdf_pdf_batch(m_a, wo, wi), dtype=np.float64)
    pb = np.array(r.debug_bsdf_pdf_batch(m_b, wo, wi), dtype=np.float64)
    assert np.allclose(pa, pb, atol=1e-6), f"Stage-3 defaults changed core-lobe pdf: {pa} vs {pb}"


def test_principled_non_negative_finite():
    for params in [
        {"metallic": 0.0, "roughness": 0.4},
        {"metallic": 1.0, "roughness": 0.3},
        {"transmission_weight": 1.0, "ior": 1.5, "roughness": 0.3},
        {"metallic": 0.5, "roughness": 0.3, "diffuse_roughness": 0.5},
    ]:
        r = _renderer()
        mid = r.create_material("principled", [0.8, 0.6, 0.4], params)
        r.add_sphere([0, 0, 0], 1.0, mid)
        px = np.array(r.render(16, 6, None, False), dtype=np.float32)
        assert px.min() >= 0.0, f"principled {params} produced a negative pixel"
        assert np.isfinite(px).all(), f"principled {params} produced a non-finite pixel"

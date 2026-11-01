"""#1227 - Principled Lambert diffuse must not test the view side.

Cycles bsdf_diffuse_eval (Cycles @ Blender v5.2.0, kernel/closure/bsdf_diffuse.h:38-49)
returns max(dot(N, wo_light), 0) / pi and never looks at the view direction. Under a
strong Bump the shading normal N can face away from the camera near a silhouette; Cycles
still shades the diffuse there. Astroray zeroed the lobe when dot(N, view) <= 0, which
darkened the prod_wood Hero rim by 3-10 % (row (b) audit witnesses Bump / Mapping /
Noise / Wave). The plain Lambertian material already followed Cycles.

CPU eval only; the GPU twin (gpu_materials.h gpu_pr_evalLobe / pdfLobe / evalLobeSpectral)
is covered at render level by the prod_wood Hero rim ratio.
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


def _unit(v):
    v = np.asarray(v, dtype=np.float64)
    return list(v / np.linalg.norm(v))


def _eval(mat_type, wo, wi=(0.0, 1.0, 0.0)):
    r = astroray.Renderer()
    mid = r.create_material(mat_type, [0.8, 0.5, 0.2], {"roughness": 0.5})
    return np.asarray(r.eval_material(mid, _unit(wo), _unit(wi), [0.0, 1.0, 0.0]))


def test_principled_diffuse_shades_with_view_below_normal():
    # View just below the shading normal's horizon, light straight along N.
    below = _eval("principled", (1.0, -0.02, 0.0))
    above = _eval("principled", (1.0, 0.02, 0.0))
    assert np.all(below > 0.0), f"diffuse zeroed with the view below N: {below}"
    # Near-continuous across the horizon: only the (small, grazing) specular term drops out.
    # Pre-fix build ef27d80: below = 0, above = (0.206, 0.131, 0.057).
    ratio = below / above
    assert np.all((ratio > 0.5) & (ratio <= 1.05)), f"below {below} vs above {above}"


def test_principled_diffuse_still_needs_light_above_normal():
    assert np.all(_eval("principled", (0.0, 1.0, 0.0), wi=(1.0, -0.1, 0.0)) == 0.0)

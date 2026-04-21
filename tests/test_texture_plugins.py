"""Smoke tests for the nine texture plugins introduced in pkg04."""
import sys
import os
import math

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'build'))

try:
    import astroray
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray module not available")

TEXTURE_TYPES = [
    "checker",
    "noise",
    "gradient",
    "voronoi",
    "brick",
    "musgrave",
    "magic",
    "wave",
    "image",
]


def test_all_textures_in_registry():
    names = astroray.texture_registry_names()
    for t in TEXTURE_TYPES:
        assert t in names, f"'{t}' not in TextureRegistry"


@pytest.mark.parametrize("tex_type,params", [
    ("checker",  {}),
    ("noise",    {}),
    ("gradient", {}),
    ("voronoi",  {}),
    ("brick",    {}),
    ("musgrave", {}),
    ("magic",    {}),
    ("wave",     {}),
    ("image",    {}),  # empty path → pink fallback (1, 0, 1)
])
def test_texture_sample_returns_finite_vec3(tex_type, params):
    r = astroray.Renderer()
    result = r.sample_texture(tex_type, params, 0.5, 0.5)
    assert len(result) == 3, f"{tex_type}: expected 3-component result"
    assert all(math.isfinite(v) for v in result), f"{tex_type}: non-finite value in {result}"


def test_checker_alternates_colors():
    r = astroray.Renderer()
    # sample_texture passes (u,v,u) as the 3D point.
    # sin(10*0.1)^3 > 0 → even;  sin(10*0.4)^3 < 0 → odd.
    c1 = r.sample_texture("checker", {"color1": [1.0, 0.0, 0.0], "color2": [0.0, 0.0, 1.0], "scale": 10.0}, 0.1, 0.1)
    c2 = r.sample_texture("checker", {"color1": [1.0, 0.0, 0.0], "color2": [0.0, 0.0, 1.0], "scale": 10.0}, 0.4, 0.4)
    assert c1 != c2, "checker: different tile regions should produce different colours"


def test_gradient_monotone():
    r = astroray.Renderer()
    v0 = r.sample_texture("gradient", {"color1": [0.0, 0.0, 0.0], "color2": [1.0, 1.0, 1.0], "scale": 1.0}, 0.0, 0.5)
    v1 = r.sample_texture("gradient", {"color1": [0.0, 0.0, 0.0], "color2": [1.0, 1.0, 1.0], "scale": 1.0}, 1.0, 0.5)
    assert v1[0] >= v0[0] - 0.01, "gradient: should increase from u=0 to u=1"


def test_image_empty_path_returns_fallback():
    r = astroray.Renderer()
    result = r.sample_texture("image", {}, 0.5, 0.5)
    assert result == [1.0, 0.0, 1.0], f"image: expected pink fallback [1,0,1], got {result}"

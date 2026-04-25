import os
import re

import pytest


PROCEDURAL_TEXTURE_PLUGIN_FILES = [
    "checker.cpp",
    "noise.cpp",
    "gradient.cpp",
    "voronoi.cpp",
    "brick.cpp",
    "musgrave.cpp",
    "magic.cpp",
    "wave.cpp",
]


@pytest.mark.parametrize("filename", PROCEDURAL_TEXTURE_PLUGIN_FILES)
def test_procedural_texture_plugin_overrides_sample_spectral(filename):
    repo_root = os.path.join(os.path.dirname(__file__), "..")
    path = os.path.join(repo_root, "plugins", "textures", filename)
    with open(path, "r", encoding="utf-8") as f:
        src = f.read()

    assert "sampleSpectral(" in src
    assert "value(uv, p)" in src
    assert "RGBAlbedoSpectrum" in src
    assert ".sample(lambdas)" in src
    assert len(re.findall(r"sampleSpectral\s*\(", src)) == 1

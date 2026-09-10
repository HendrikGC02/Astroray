#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Issue #797 — flat (non-RLE) Radiance .hdr files must decode row-exact.

stb_image's HDR reader takes one of two paths: widths in [8, 32768) go through
the RLE scanline reader, which falls back to a flat read when the first
scanline is not RLE-encoded by jumping back into the flat-read loop
(`goto main_decode_loop`). GCC 15.2 (MinGW-Builds) at -O2/-O3 miscompiled that
abnormal edge: every other row came back as garbage and the rest were shifted
(the pkg256 striped sky). The vendored header now reads the remaining pixels
in a structured loop instead. MSVC and the CI GCC never showed the defect, so
this test is green on those builds before and after; it is the gate for the
MinGW `--backend cpu` addon .pyd (run with ASTRORAY_BUILD_DIR pointing at it).

The probe: a vertical gradient (file row r -> value r + 0.5, all channels) is
loaded with blender_convention=True and read back through `environment_lookup`
along the phi=0 meridian at each data-row centre. Bilinear averaging of two
adjacent rows gives an exact half-integer sequence, so the check is exact.
"""
import math
import os
import sys

import numpy as np
import pytest

from runtime_setup import configure_test_imports

configure_test_imports()
sys.path.insert(0, os.path.dirname(__file__))

try:
    import astroray
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

# Same flat-scanline writer the rest of the HDRI suite uses (no duplicate).
from test_world_hdri_parity import _write_radiance_hdr  # noqa: E402

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")


def _lookup_rows(path, height):
    r = astroray.Renderer()
    assert r.load_environment_map(path, 1.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, True)
    vals = []
    for y in range(height):
        theta = (1.0 - (y + 0.5) / height) * math.pi   # data row y centre
        d = [math.sin(theta), 0.0, math.cos(theta)]      # Blender Z-up, phi = 0
        vals.append(float(r.environment_lookup(d)[0]))
    return np.asarray(vals)


# width 8 is the smallest width that takes stb's RLE-reader path (and hence
# the flat fallback); 64 is a typical small test HDRI.
@pytest.mark.parametrize("width", [8, 64])
def test_flat_hdr_rows_decode_exact(tmp_path, width):
    height = 16
    img = np.zeros((height, width, 3), dtype=np.float32)
    for row in range(height):
        img[row, :, :] = row + 0.5          # exactly representable in RGBE
    p = tmp_path / f"grad_{width}.hdr"
    _write_radiance_hdr(str(p), img)

    got = _lookup_rows(str(p), height)

    # load() flips rows, so data row y holds file row height-1-y; a row-centre
    # probe lands at vFract = 0.5 between data rows y and y+1 (y+1 clamped).
    expected = np.array([(height - 1 - y) for y in range(height - 1)] + [0.5],
                        dtype=np.float64)
    assert np.all(np.isfinite(got)), got
    assert np.allclose(got, expected, atol=1e-4), (got, expected)
    assert np.all(np.diff(got) < 0), got

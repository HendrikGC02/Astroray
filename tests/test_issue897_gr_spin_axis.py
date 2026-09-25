"""#897: camera rays that graze the BH spin axis must not die at the BL pole.

Boyer-Lindquist is singular at sin(theta)=0: near the axis dphi/dlambda ~
L_z/sin^2(theta) got stiff, the RK45 sat on its step floor and rejected steps
used up maxSteps ("captured"), a dotted dark column at image x=0. The
integrator now switches to Cartesian Kerr-Schild near the axis (GRay2, Chan et
al. 2018). Check: an odd-width equatorial view shifted sideways by dx world
units puts the centre column dx from the axis; its captured rows must match the
unshifted column (pre-fix: 1e-3 captured all 101 rows).
"""

import numpy as np
import pytest

helpers = pytest.importorskip("astroray_test_helpers")

N = 101
C = N // 2


def _captured_column(spin, dx):
    raw = helpers.gr_disk_redshift_image(
        [dx, 0.0, 12.0], [dx, 0.0, 0.0], 45.0, N, N, [0.0, 0.0, 0.0],
        5.0, 18.0, 20.0, spin)
    passes = np.asarray(raw, dtype=np.float64).reshape(N, N, 2)[..., 1]
    return passes[:, C] < 0


@pytest.mark.parametrize("spin", [0.0, 0.94])
@pytest.mark.parametrize("dx", [1e-5, 3e-5, 1e-4, 3e-4, 1e-3])
def test_axis_grazing_rays_are_not_captured(spin, dx):
    ref = _captured_column(spin, 0.0)
    col = _captured_column(spin, dx)
    rows = np.flatnonzero(col)
    assert 20 <= ref.sum() <= 30, ref.sum()  # shadow diameter at x=0, ~25 px
    assert rows.size and rows[-1] - rows[0] + 1 == rows.size, f"non-contiguous: {rows}"
    assert np.array_equal(col, ref), (
        f"a={spin} dx={dx}: {int((col & ~ref).sum())} extra captured rows "
        f"{np.flatnonzero(col & ~ref)[:10]}")

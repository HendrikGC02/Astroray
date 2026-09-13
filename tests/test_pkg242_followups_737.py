#!/usr/bin/env python
"""pkg242 Phase 1 pre-review follow-ups (PR #737, issue #737 thread).

Two bounded fixes, each with its own guard:

(a) SCALE-RELATIVE singular-Mapping check. The original test flagged a matrix
    singular when ``|det| < 1e-8`` (absolute), so a legitimate *uniform* scale
    ``s`` below ~0.002 (det = s^3 = 8e-9 < 1e-8) was reported as singular even
    though it is perfectly invertible. The fix compares ``|det|`` against the
    product of the three column norms (normalized determinant in [0,1]), which
    is 1 for an orthogonal frame at ANY scale and ~0 only for a genuinely
    rank-deficient frame. Asserted via ``named_texture_mapping_singular``.

(b) ``valueOffset`` bump gradient under a Mapping. Before the fix, the Mapping
    branch of ``Texture::valueOffset`` offset only the 2-D image sample
    coordinate and left the mapped 3-D point ``mp`` fixed, so p-reading
    procedurals (Noise/Wave/Musgrave/Checker all read ``p`` in the HitRecord
    overload) read an IDENTICAL point for the base and offset finite-difference
    taps and produced a ZERO bump gradient. The fix also moves ``mp`` by
    ``(du,dv,0)``. Asserted via ``texture_value_and_offset`` (the real
    HitRecord ``value()``/``valueOffset()`` path).
"""

import math

import numpy as np
import pytest
from base_helpers import create_renderer


def _affine(scale=(1, 1, 1), rot_z_deg=0.0, offset=(0, 0, 0)):
    sx, sy, sz = scale
    c, s = math.cos(math.radians(rot_z_deg)), math.sin(math.radians(rot_z_deg))
    L = [[c * sx, -s * sy, 0.0],
         [s * sx,  c * sy, 0.0],
         [0.0,     0.0,    sz]]
    ox, oy, oz = offset
    return [L[0][0], L[0][1], L[0][2], ox,
            L[1][0], L[1][1], L[1][2], oy,
            L[2][0], L[2][1], L[2][2], oz]


_GRID = [(float(u), float(v))
         for u in np.linspace(0.07, 0.93, 10)
         for v in np.linspace(0.07, 0.93, 10)]


# ---------------------------------------------------------------------------
# (b) valueOffset bump gradient under a Mapping
# ---------------------------------------------------------------------------
@pytest.mark.cpu
def test_valueoffset_noise_gradient_nonzero_under_mapping():
    """A p-reading procedural (Noise) under a Mapping must produce a NONZERO
    bump gradient: value() at the base tap and valueOffset() at (du,dv) differ.
    Before the #737 fix valueOffset left the mapped 3-D point fixed, so every
    tap read the same point and the gradient was identically zero."""
    r = create_renderer()
    r.set_use_gpu(False)
    name = "pkg242f_noise"
    r.create_procedural_texture(name, "noise", [1.0], "UV")
    r.set_texture_mapping_matrix(name, _affine())  # identity → hasMapping_ true
    du = dv = 0.02
    differ = 0
    for (u, v) in _GRID:
        vals = r.texture_value_and_offset(name, u, v, du, dv)
        base, off = vals[:3], vals[3:]
        if abs(base[0] - off[0]) > 1e-4:
            differ += 1
    assert differ > 90, (
        f"valueOffset gave a ~zero bump gradient under Mapping "
        f"({differ}/100 taps differ) — the #737 zero-gradient bug")


@pytest.mark.cpu
def test_valueoffset_checker_gradient_under_mapping():
    """Checker reads the 3-D point p in the HitRecord overload, so under a
    Mapping its base and offset taps were also identical before the fix. With a
    step large enough to cross a cell boundary the offset tap must be able to
    flip."""
    r = create_renderer()
    r.set_use_gpu(False)
    name = "pkg242f_chk"
    # scale=4 checker: one cell = 0.25 in p; a 0.2 step crosses boundaries often.
    r.create_procedural_texture(
        name, "checker", [0.02, 0.02, 0.02, 0.98, 0.98, 0.98, 4.0], "UV")
    r.set_texture_mapping_matrix(name, _affine())
    flips = 0
    for (u, v) in _GRID:
        vals = r.texture_value_and_offset(name, u, v, 0.2, 0.2)
        base, off = vals[0], vals[3]
        if abs(base - off) > 0.5:
            flips += 1
    assert flips > 0, (
        "checker offset tap never flipped under Mapping — valueOffset still "
        "ignores the 3-D point (#737)")


# ---------------------------------------------------------------------------
# (a) scale-relative singular check
# ---------------------------------------------------------------------------
def _singular(matrix):
    r = create_renderer()
    r.set_use_gpu(False)
    r.create_procedural_texture("pkg242f_sing", "checker",
                                [0, 0, 0, 1, 1, 1, 4.0], "UV")
    r.set_texture_mapping_matrix("pkg242f_sing", matrix)
    return r.named_texture_mapping_singular("pkg242f_sing")


@pytest.mark.cpu
def test_tiny_uniform_scale_not_singular():
    """A uniform scale of 0.001 (det = 1e-9, which the OLD absolute |det|<1e-8
    test flagged) is perfectly invertible and must NOT be reported singular."""
    assert _singular(_affine(scale=(0.001, 0.001, 0.001))) is False


@pytest.mark.cpu
def test_identity_and_anisotropic_scale_not_singular():
    assert _singular(_affine()) is False
    assert _singular(_affine(scale=(2.0, 3.0, 1.0))) is False
    assert _singular(_affine(rot_z_deg=30.0)) is False
    assert _singular(_affine(scale=(-1.0, 1.0, 1.0))) is False  # mirror


@pytest.mark.cpu
def test_rank_deficient_is_singular():
    """A genuinely rank-deficient frame (a zero column, or two parallel
    columns) collapses the coordinate field and MUST be flagged, at any scale."""
    # zero z-column (flattens to a plane)
    flat = _affine(scale=(1.0, 1.0, 0.0))
    assert _singular(flat) is True
    # two identical columns (rank 2): build by hand, row-major 3x4
    parallel = [1.0, 1.0, 0.0, 0.0,
                0.0, 0.0, 1.0, 0.0,
                0.0, 0.0, 0.0, 0.0]  # cols: (1,0,0),(1,0,0),(0,1,0) → c0==c1
    assert _singular(parallel) is True
    # rank-deficient but NOT tiny: scale the whole thing up 1000x — still singular
    big_flat = _affine(scale=(1000.0, 1000.0, 0.0))
    assert _singular(big_flat) is True

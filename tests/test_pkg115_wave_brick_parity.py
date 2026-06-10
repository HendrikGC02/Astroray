"""
pkg115 Stage 2 chunk 3 parity tests: Wave + Brick (audit items 7-8).

Wave texture ported from Blender intern/cycles/kernel/svm/wave.h (Apache-2.0).
Brick texture ported from Blender intern/cycles/kernel/svm/brick.h (Apache-2.0).

Per CLAUDE.md section 6, all formulas cited to exact Cycles files + licenses.
"""
import pytest
import math


def test_wave_bands_x_sine_phase_factor():
    """Wave bands-X sine: phase factor 20.0 (not pi).

    Cycles intern/cycles/kernel/svm/wave.h (Apache-2.0):
      bands-X: n = p.x * 20.0
      sine profile: t = 0.5 + 0.5 * sin(n - pi/2)

    At x=0.1, scale=1, phase_offset=0:
      n = 0.1 * 20 = 2.0
      t = 0.5 + 0.5 * sin(2.0 - pi/2) = 0.5 + 0.5 * sin(2.0 - 1.5708)
        = 0.5 + 0.5 * sin(0.4292) = 0.5 + 0.5 * 0.4161 = 0.7080

    Output color = c1*(1-t) + c2*t.
    For c1=(0,0,0), c2=(1,1,1): output = (0.7080, 0.7080, 0.7080).
    """
    import astroray
    r = astroray.Renderer()

    params = {
        "wave_type": 0,         # Bands
        "bands_direction": 0,   # X
        "profile": 0,           # Sine
        "scale": 1.0,
        "distortion": 0.0,
        "phase_offset": 0.0,
        "color_low": [0.0, 0.0, 0.0],
        "color_high": [1.0, 1.0, 1.0]
    }
    val = r.eval_texture_at_3d("wave", params, 0.1, 0.0, 0.0)
    expected = 0.5 + 0.5 * math.sin(2.0 - math.pi / 2.0)
    assert abs(val[0] - expected) < 0.01, f"Wave bands-X sine at x=0.1: expected {expected}, got {val[0]}"


def test_wave_bands_diagonal():
    """Wave bands diagonal: n = (x + y + z) * 10.0.

    At (0.1, 0.1, 0.1), scale=1, sine profile:
      n = (0.1 + 0.1 + 0.1) * 10 = 3.0
      t = 0.5 + 0.5 * sin(3.0 - pi/2) = 0.5 + 0.5 * sin(1.4292) = 0.5 + 0.5 * 0.9900 = 0.9950
    """
    import astroray
    r = astroray.Renderer()

    params = {
        "wave_type": 0,
        "bands_direction": 3,  # Diagonal
        "profile": 0,
        "scale": 1.0,
        "distortion": 0.0,
        "phase_offset": 0.0,
        "color_low": [0.0, 0.0, 0.0],
        "color_high": [1.0, 1.0, 1.0]
    }
    val = r.eval_texture_at_3d("wave", params, 0.1, 0.1, 0.1)
    expected = 0.5 + 0.5 * math.sin(3.0 - math.pi / 2.0)
    assert abs(val[0] - expected) < 0.01, f"Wave diagonal: expected {expected:.4f}, got {val[0]:.4f}"


def test_wave_rings_spherical():
    """Wave rings spherical: no axis zeroing, n = len(p) * 20.

    At (0.05, 0.0, 0.0), rings spherical, scale=1, sine:
      len = 0.05, n = 0.05 * 20 = 1.0
      t = 0.5 + 0.5 * sin(1.0 - pi/2) = 0.5 + 0.5 * sin(-0.5708) = 0.5 + 0.5 * (-0.5403) = 0.2298

    Compare rings-X (zero x axis): at (0.05, 0.0, 0.0), len((0, 0, 0)) = 0 -> n=0.
      t = 0.5 + 0.5 * sin(-pi/2) = 0.5 + 0.5 * (-1) = 0.0
    These must differ.
    """
    import astroray
    r = astroray.Renderer()

    params_sph = {
        "wave_type": 1,         # Rings
        "rings_direction": 3,   # Spherical
        "profile": 0,
        "scale": 1.0,
        "distortion": 0.0,
        "phase_offset": 0.0,
        "color_low": [0.0, 0.0, 0.0],
        "color_high": [1.0, 1.0, 1.0]
    }
    val_sph = r.eval_texture_at_3d("wave", params_sph, 0.05, 0.0, 0.0)
    expected_sph = 0.5 + 0.5 * math.sin(1.0 - math.pi / 2.0)
    assert abs(val_sph[0] - expected_sph) < 0.01, f"Rings spherical: expected {expected_sph:.4f}, got {val_sph[0]:.4f}"

    params_x = {
        "wave_type": 1,
        "rings_direction": 0,  # X (zero x)
        "profile": 0,
        "scale": 1.0,
        "distortion": 0.0,
        "phase_offset": 0.0,
        "color_low": [0.0, 0.0, 0.0],
        "color_high": [1.0, 1.0, 1.0]
    }
    val_x = r.eval_texture_at_3d("wave", params_x, 0.05, 0.0, 0.0)
    expected_x = 0.5 + 0.5 * math.sin(0.0 - math.pi / 2.0)
    assert abs(val_x[0] - expected_x) < 0.01, f"Rings-X: expected {expected_x:.4f}, got {val_x[0]:.4f}"
    assert abs(val_sph[0] - val_x[0]) > 0.1, "Rings spherical vs X must differ at same point"


def test_wave_profile_saw():
    """Wave saw profile: ascending sawtooth period 2pi.

    Cycles svm/wave.h: saw: frac = n / (2*pi); return frac - floor(frac);
    At n=1.0: frac = 1.0 / 6.283 = 0.1592, t = 0.1592.
    At n=6.0: frac = 6.0 / 6.283 = 0.9549, t = 0.9549.
    """
    import astroray
    r = astroray.Renderer()

    params = {
        "wave_type": 0,
        "bands_direction": 0,  # X
        "profile": 1,          # Saw
        "scale": 1.0,
        "distortion": 0.0,
        "phase_offset": 0.0,
        "color_low": [0.0, 0.0, 0.0],
        "color_high": [1.0, 1.0, 1.0]
    }
    # x=0.05 -> n=0.05*20=1.0
    val1 = r.eval_texture_at_3d("wave", params, 0.05, 0.0, 0.0)
    expected1 = 1.0 / (2.0 * math.pi)
    assert abs(val1[0] - expected1) < 0.01, f"Saw at n=1.0: expected {expected1:.4f}, got {val1[0]:.4f}"

    # x=0.3 -> n=0.3*20=6.0
    val2 = r.eval_texture_at_3d("wave", params, 0.3, 0.0, 0.0)
    expected2 = 6.0 / (2.0 * math.pi) - math.floor(6.0 / (2.0 * math.pi))
    assert abs(val2[0] - expected2) < 0.01, f"Saw at n=6.0: expected {expected2:.4f}, got {val2[0]:.4f}"


def test_wave_profile_triangle():
    """Wave triangle: period 2pi, symmetric.

    Cycles svm/wave.h: frac = n / (2*pi); return abs(frac - floor(frac + 0.5)) * 2.
    At n=pi/2 (quarter period): frac=0.25, frac-floor(0.75)=0.25-0=0.25, abs*2 = 0.5.
    At n=pi: frac=0.5, frac-floor(1.0)=0.5-1=-0.5, abs*2 = 1.0 (peak).
    """
    import astroray
    r = astroray.Renderer()

    params = {
        "wave_type": 0,
        "bands_direction": 0,
        "profile": 2,  # Triangle
        "scale": 1.0,
        "distortion": 0.0,
        "phase_offset": 0.0,
        "color_low": [0.0, 0.0, 0.0],
        "color_high": [1.0, 1.0, 1.0]
    }
    # n = pi -> x = pi/20
    x_peak = math.pi / 20.0
    val_peak = r.eval_texture_at_3d("wave", params, x_peak, 0.0, 0.0)
    assert abs(val_peak[0] - 1.0) < 0.01, f"Triangle peak: expected 1.0, got {val_peak[0]:.4f}"

    # n = pi/2 -> x = pi/40
    x_mid = math.pi / 40.0
    val_mid = r.eval_texture_at_3d("wave", params, x_mid, 0.0, 0.0)
    assert abs(val_mid[0] - 0.5) < 0.01, f"Triangle quarter: expected 0.5, got {val_mid[0]:.4f}"


def test_wave_detail_changes_output():
    """Wave distortion uses real fBM: detail>0 changes output.

    Cycles svm/wave.h: distortion != 0 adds noise_fbm(p*dscale, detail, drough, 2.0, true)*2-1.
    At distortion=0 vs distortion>0 with detail>0, outputs differ.
    """
    import astroray
    r = astroray.Renderer()

    params_no_dist = {
        "wave_type": 0,
        "bands_direction": 0,
        "profile": 0,
        "scale": 1.0,
        "distortion": 0.0,
        "detail": 2.0,
        "detail_scale": 1.0,
        "detail_roughness": 0.5,
        "phase_offset": 0.0,
        "color_low": [0.0, 0.0, 0.0],
        "color_high": [1.0, 1.0, 1.0]
    }
    # Avoid integer lattice (snoise=0); use offset coordinates.
    val_no = r.eval_texture_at_3d("wave", params_no_dist, 0.37, 0.0, 0.0)

    params_with_dist = dict(params_no_dist)
    params_with_dist["distortion"] = 1.0
    val_with = r.eval_texture_at_3d("wave", params_with_dist, 0.37, 0.0, 0.0)

    assert abs(val_no[0] - val_with[0]) > 0.01, f"Distortion>0 must change output: no={val_no[0]:.4f}, with={val_with[0]:.4f}"


def test_wave_phase_offset():
    """Wave phase_offset shifts the pattern.

    At phase_offset=pi, sine output shifts by a half-period.
    """
    import astroray
    r = astroray.Renderer()

    params_zero = {
        "wave_type": 0,
        "bands_direction": 0,
        "profile": 0,
        "scale": 1.0,
        "distortion": 0.0,
        "phase_offset": 0.0,
        "color_low": [0.0, 0.0, 0.0],
        "color_high": [1.0, 1.0, 1.0]
    }
    val_zero = r.eval_texture_at_3d("wave", params_zero, 0.1, 0.0, 0.0)

    params_offset = dict(params_zero)
    params_offset["phase_offset"] = math.pi
    val_offset = r.eval_texture_at_3d("wave", params_offset, 0.1, 0.0, 0.0)

    assert abs(val_zero[0] - val_offset[0]) > 0.1, f"Phase offset pi must shift output: zero={val_zero[0]:.4f}, offset={val_offset[0]:.4f}"


def test_brick_cell_classification():
    """Brick cell classification: known coords map to brick vs mortar.

    Cycles intern/cycles/kernel/svm/brick.h (Apache-2.0):
      rownum = floor(coord.y / row_height)
      bricknum = floor((coord.x + offset) / brick_width)
      min_dist = min(x, y, brick_w - x, row_h - y)
      mortar = (min_dist >= mortar_size) ? 0 : ...

    Default: brick_width=0.5, row_height=0.25, mortar_size=0.02, scale=5.
    At p=(0.1, 0.1, 0.0), scale=1 (not 5): coord=(0.1, 0.1).
      rownum = floor(0.1 / 0.25) = 0.
      offset = (0 % 2) ? 0 : offset_amount*brick_width = 0.5*0.5 = 0.25 (offset_frequency=2).
      bricknum = floor((0.1 + 0.25) / 0.5) = floor(0.7) = 1.
      x = 0.35 - 0.5*1 = -0.15 (negative wrap issue? NO: Cycles computes (coord.x+offset) - brick_w*bricknum = 0.35 - 0.5 = -0.15... Actually coord.x=0.1, offset=0.25, sum=0.35, bricknum=floor(0.35/0.5)=0, x=0.35-0=0.35).

    Recompute: rownum=0, offset=0.25, bricknum=floor((0.1+0.25)/0.5)=floor(0.7)=1, x=0.35-0.5*1=-0.15.
    Wait, that's negative. Cycles code: x = (coord.x + offset) - brick_width * bricknum.
    (0.1+0.25) = 0.35, brick_width=0.5, bricknum=floor(0.35/0.5)=0, x=0.35-0=0.35.

    Actually at row=0 with offset_frequency=2: (rownum % offset_frequency) = 0%2=0, so offset = brick_w*offset_amount = 0.5*0.5=0.25.
    bricknum = floor((0.1+0.25)/0.5) = floor(0.7) = 1.
    x = 0.35 - 0.5*1 = -0.15. Negative x is a wrap issue in the engine port.

    Actually the Cycles code line 37-38:
      x = (coord.x + offset) - brick_width * bricknum
    This can be negative if the modulo wasn't handled. Engine should match verbatim.

    Instead of hand-computing wraparound edge cases, test a known INTERIOR brick point:
    p=(0.3, 0.13, 0.0), scale=1, row_height=0.25, brick_width=0.5, mortar_size=0.02.
      rownum=floor(0.13/0.25)=0, offset=0.25 (row 0 even).
      bricknum=floor((0.3+0.25)/0.5)=floor(1.1)=2.
      x=(0.55 - 0.5*2)=0.55-1.0=-0.45. Negative again.

    The issue is my mental offset logic. Let me re-read Cycles brick.h lines 28-32:
      if (offset_frequency && squash_frequency) {
        brick_width *= (rownum % squash_frequency) ? 1 : squash_amount;
        offset = (rownum % offset_frequency) ? 0 : brick_width * offset_amount;
      }
    For row=0, offset_frequency=2: rownum%2=0 -> offset = brick_width*offset_amount.
    For row=1, rownum%2=1 -> offset=0.

    At row=0, offset=0.25. At row=1, offset=0. So a clean brick center in row 1:
    p=(0.25, 0.38, 0) -> rownum=floor(0.38/0.25)=1, offset=0.
      bricknum=floor(0.25/0.5)=0, x=0.25-0=0.25, y=0.38-0.25*1=0.13.
      min_dist = min(0.25, 0.13, 0.5-0.25=0.25, 0.25-0.13=0.12) = 0.12.
      0.12 >= 0.02 -> brick interior.

    Color1=(0.8,0.8,0.8), Color2=(0.2,0.2,0.2), bias=0.
      hash((1<<16) + (0&0xFFFF)) = hash(65536).
      Without computing the exact hash, output = color1*(1-tint) + color2*tint, tint in [0,1].
      Output should be in [0.2, 0.8] per channel, NOT the mortar color (0,0,0 default).
    """
    import astroray
    r = astroray.Renderer()

    params = {
        "color1": [0.8, 0.8, 0.8],
        "color2": [0.2, 0.2, 0.2],
        "color_mortar": [0.0, 0.0, 0.0],
        "scale": 1.0,
        "mortar_size": 0.02,
        "mortar_smooth": 0.0,
        "bias": 0.0,
        "brick_width": 0.5,
        "row_height": 0.25,
        "offset_amount": 0.5,
        "offset_frequency": 2,
        "squash_amount": 1.0,
        "squash_frequency": 2
    }
    # Brick interior point (row 1, no offset, centered).
    val_brick = r.eval_texture_at_3d("brick", params, 0.25, 0.38, 0.0)
    assert 0.15 < val_brick[0] < 0.85, f"Brick interior: expected [0.2,0.8], got {val_brick[0]:.4f}"
    assert abs(val_brick[0]) > 0.01, f"Brick interior must not be mortar (0,0,0), got {val_brick[0]:.4f}"

    # Mortar point: edge of brick at x near 0.
    val_mortar = r.eval_texture_at_3d("brick", params, 0.01, 0.38, 0.0)
    assert abs(val_mortar[0]) < 0.01, f"Mortar edge: expected 0.0, got {val_mortar[0]:.4f}"


def test_brick_mortar_size_zero():
    """Brick mortar_size=0: no mortar, all brick.

    At mortar_size=0, min_dist >= 0 always -> mortar=0 -> pure brick color.
    """
    import astroray
    r = astroray.Renderer()

    params = {
        "color1": [1.0, 0.0, 0.0],
        "color2": [0.0, 1.0, 0.0],
        "color_mortar": [0.0, 0.0, 1.0],
        "scale": 1.0,
        "mortar_size": 0.0,
        "mortar_smooth": 0.0,
        "bias": 0.0,
        "brick_width": 0.5,
        "row_height": 0.25,
        "offset_amount": 0.5,
        "offset_frequency": 2,
        "squash_amount": 1.0,
        "squash_frequency": 2
    }
    val = r.eval_texture_at_3d("brick", params, 0.0, 0.0, 0.0)
    # mortar_size=0 -> min_dist always >= 0 -> mortar=0 -> output = brick_color.
    # brick_color = color1*(1-tint) + color2*tint. tint from hash is non-zero.
    # Blue component (mortar) must be 0.
    assert abs(val[2]) < 0.01, f"Mortar_size=0: blue (mortar) channel must be 0, got {val[2]:.4f}"
    assert (val[0] > 0.1 or val[1] > 0.1), f"Mortar_size=0: must show brick colors (R or G), got {val}"


def test_brick_bias_shifts_tint():
    """Brick bias shifts the per-brick color tint.

    tint = clamp(hash_result + bias, 0, 1).
    At bias=-0.5, hash outputs near 0.5 shift down; at bias=+0.5, shift up.
    We verify that changing bias changes the output color.
    """
    import astroray
    r = astroray.Renderer()

    params_zero = {
        "color1": [1.0, 1.0, 1.0],
        "color2": [0.0, 0.0, 0.0],
        "color_mortar": [0.5, 0.5, 0.5],
        "scale": 1.0,
        "mortar_size": 0.0,  # No mortar
        "mortar_smooth": 0.0,
        "bias": 0.0,
        "brick_width": 0.5,
        "row_height": 0.25,
        "offset_amount": 0.5,
        "offset_frequency": 2,
        "squash_amount": 1.0,
        "squash_frequency": 2
    }
    val_zero = r.eval_texture_at_3d("brick", params_zero, 0.25, 0.38, 0.0)

    params_plus = dict(params_zero)
    params_plus["bias"] = 0.3
    val_plus = r.eval_texture_at_3d("brick", params_plus, 0.25, 0.38, 0.0)

    params_minus = dict(params_zero)
    params_minus["bias"] = -0.3
    val_minus = r.eval_texture_at_3d("brick", params_minus, 0.25, 0.38, 0.0)

    # Bias shifts tint -> shifts color1/color2 mix. At least one of +/- must differ from zero.
    assert (abs(val_plus[0] - val_zero[0]) > 0.05 or abs(val_minus[0] - val_zero[0]) > 0.05), \
        f"Bias must shift tint: zero={val_zero[0]:.4f}, +bias={val_plus[0]:.4f}, -bias={val_minus[0]:.4f}"


def test_brick_per_brick_variation():
    """Brick per-brick color variation: different bricks have different colors.

    hash((rownum<<16) + (bricknum&0xFFFF)) produces different tints for different cells.
    Sample two brick interiors in different cells; colors must differ.
    """
    import astroray
    r = astroray.Renderer()

    params = {
        "color1": [1.0, 1.0, 1.0],
        "color2": [0.0, 0.0, 0.0],
        "color_mortar": [0.5, 0.5, 0.5],
        "scale": 1.0,
        "mortar_size": 0.0,
        "mortar_smooth": 0.0,
        "bias": 0.0,
        "brick_width": 0.5,
        "row_height": 0.25,
        "offset_amount": 0.5,
        "offset_frequency": 2,
        "squash_amount": 1.0,
        "squash_frequency": 2
    }
    # Brick 1: row=1, brick=0 (center at x=0.25, y=0.38).
    val1 = r.eval_texture_at_3d("brick", params, 0.25, 0.38, 0.0)

    # Brick 2: row=1, brick=1 (center at x=0.75, y=0.38).
    val2 = r.eval_texture_at_3d("brick", params, 0.75, 0.38, 0.0)

    # Different bricks -> different hash -> (usually) different tint.
    # Hash is deterministic but pseudo-random; highly likely to differ.
    assert abs(val1[0] - val2[0]) > 0.01, f"Different bricks must (usually) differ: brick1={val1[0]:.4f}, brick2={val2[0]:.4f}"

    # Same brick, different points within -> same color.
    val1_dup = r.eval_texture_at_3d("brick", params, 0.26, 0.38, 0.0)
    assert abs(val1[0] - val1_dup[0]) < 0.001, f"Same brick interior must have same color: {val1[0]:.4f} vs {val1_dup[0]:.4f}"


def test_brick_mortar_smooth():
    """Brick mortar_smooth: smoothstep transition at mortar edge.

    With mortar_smooth=0, mortar is a hard binary step.
    With mortar_smooth>0, Cycles applies a smoothstep on (1 - min_dist/mortar_size)/mortar_smooth.
    At a point just inside mortar_size, smooth>0 gives a gradient; smooth=0 gives full mortar.
    """
    import astroray
    r = astroray.Renderer()

    params_hard = {
        "color1": [1.0, 1.0, 1.0],
        "color2": [1.0, 1.0, 1.0],
        "color_mortar": [0.0, 0.0, 0.0],
        "scale": 1.0,
        "mortar_size": 0.05,
        "mortar_smooth": 0.0,  # Hard edge
        "bias": 0.0,
        "brick_width": 0.5,
        "row_height": 0.25,
        "offset_amount": 0.5,
        "offset_frequency": 2,
        "squash_amount": 1.0,
        "squash_frequency": 2
    }
    # Point near edge: x=0.04 (min_dist from x=0 is 0.04, less than 0.05 -> mortar).
    val_hard = r.eval_texture_at_3d("brick", params_hard, 0.04, 0.38, 0.0)
    assert abs(val_hard[0]) < 0.01, f"Hard mortar edge: expected 0.0, got {val_hard[0]:.4f}"

    params_smooth = dict(params_hard)
    params_smooth["mortar_smooth"] = 0.1
    val_smooth = r.eval_texture_at_3d("brick", params_smooth, 0.04, 0.38, 0.0)
    # With smoothstep, the edge is not pure 0 or 1, but a blend.
    # At min_dist=0.04, mortar_size=0.05, t=(1-0.04/0.05)/0.1 = (1-0.8)/0.1 = 2.0, clamped to 1.
    # smoothstep(1) = 1 -> full mortar. Actually that's still mortar.
    # Try a point slightly farther: x=0.045, min_dist=0.045.
    val_smooth2 = r.eval_texture_at_3d("brick", params_smooth, 0.045, 0.38, 0.0)
    # t=(1-0.045/0.05)/0.1 = (1-0.9)/0.1 = 1.0, smoothstep(1)=1.
    # Still full mortar. The smoothstep transition happens near min_dist ~ mortar_size.
    # At min_dist=0.04, t=(1-0.8)/0.1=2, clamped to 1 -> smoothstep(1)=1 -> full mortar.
    # At min_dist=0.049, t=(1-0.98)/0.1=0.2, smoothstep(0.2)=0.2^2*(3-2*0.2)=0.04*2.6=0.104.
    val_smooth3 = r.eval_texture_at_3d("brick", params_smooth, 0.049, 0.38, 0.0)
    # mortar = 0.104 -> output = brick*(1-0.104) + mortar*0.104 = 1.0*0.896 + 0.0*0.104 = 0.896.
    # This is a partial blend, not pure brick or pure mortar.
    # Just verify that smooth>0 produces a different value than smooth=0 at this edge.
    val_hard3 = r.eval_texture_at_3d("brick", params_hard, 0.049, 0.38, 0.0)
    # Hard: min_dist=0.049 < 0.05 -> mortar=1 -> pure mortar (0).
    # Smooth: mortar ~ 0.1 -> output ~ 0.9.
    assert abs(val_hard3[0]) < 0.01, f"Hard mortar at 0.049: expected 0.0, got {val_hard3[0]:.4f}"
    assert val_smooth3[0] > 0.5, f"Smooth mortar at 0.049: expected partial blend ~0.9, got {val_smooth3[0]:.4f}"

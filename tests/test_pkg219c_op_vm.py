"""pkg219c — op-VM opcode fill-out: CPU evaluator parity tests.

Each new opcode (HSV, Invert, Gamma, Bright/Contrast, Separate/Combine Color in
RGB+HSV, RGB-to-BW) is exercised by hand-assembling the bytecode, running it
through the CPU ProgramTexture (sample_named_texture), and comparing against an
independent Python transcription of the Cycles SVM formula
(pkg219c-blender-node-opcode-semantics.md; formulas re-verified against Cycles
main src/util/color.h, svm/hsv.h, svm/invert.h, svm/color_util.h,
svm/math_util.h on 2026-08-23).

The runtime VM is the shared HD svm_eval (include/astroray/shader_vm.h), so a
green CPU test is also the GPU evaluator's correctness oracle.
"""
import math

import pytest

astroray = pytest.importorskip("astroray")

# ---- opcode / sub-op enums (mirror include/astroray/shader_vm.h) -----------
(OP_END, OP_LOAD_TEX, OP_LOAD_CONST, OP_MATH, OP_MIX, OP_RAMP, OP_MAP_RANGE,
 OP_HSV, OP_INVERT, OP_GAMMA, OP_BRIGHT_CONTRAST, OP_SEP_COLOR,
 OP_COMBINE_COLOR, OP_RGB_TO_BW) = range(14)
CS_RGB, CS_HSV = 0, 1


def instr(op, out=0, a=0, b=0, c=0, d=0, e=0, imm=0):
    return [op, out, a, b, c, d, e, imm]


def flat(instrs):
    out = []
    for i in instrs:
        out.extend(i)
    return out


def make_solid_input(r, name="in0", value=(0.4, 0.4, 0.4)):
    import numpy as np
    img = np.array(value, dtype="float32").reshape(1, 1, 3).ravel()
    r.load_texture(name, img, 1, 1, "UV")


def sat(x):
    return min(1.0, max(0.0, x))


# ---- Python reference (Cycles util/color.h) --------------------------------
def rgb_to_hsv(rgb):
    r, g, b = rgb
    cmax = max(r, g, b)
    cmin = min(r, g, b)
    cdelta = cmax - cmin
    v = cmax
    if cmax != 0.0:
        s = cdelta / cmax
    else:
        s = 0.0
        h = 0.0
    if s != 0.0:
        cx = (cmax - r) / cdelta
        cy = (cmax - g) / cdelta
        cz = (cmax - b) / cdelta
        if r == cmax:
            h = cz - cy
        elif g == cmax:
            h = 2.0 + cx - cz
        else:
            h = 4.0 + cy - cx
        h /= 6.0
        if h < 0.0:
            h += 1.0
    else:
        h = 0.0
    return [h, s, v]


def hsv_to_rgb(hsv):
    h, s, v = hsv
    if s != 0.0:
        if h == 1.0:
            h = 0.0
        h *= 6.0
        i = math.floor(h)
        f = h - i
        p = v * (1.0 - s)
        q = v * (1.0 - s * f)
        t = v * (1.0 - s * (1.0 - f))
        if i == 0.0:
            return [v, t, p]
        elif i == 1.0:
            return [q, v, p]
        elif i == 2.0:
            return [p, v, t]
        elif i == 3.0:
            return [p, q, v]
        elif i == 4.0:
            return [t, p, v]
        else:
            return [v, p, q]
    return [v, v, v]


# --------------------------------------------------------------------------- #
# 1. Hue/Saturation/Value on a texture
# --------------------------------------------------------------------------- #
def hsv_ref(hue, s, val, fac, color):
    c = rgb_to_hsv(color)
    c[0] = (c[0] + hue + 0.5) % 1.0
    c[1] = sat(c[1] * s)
    c[2] = c[2] * val
    tmp = hsv_to_rgb(c)
    out = [tmp[k] * fac + color[k] * (1.0 - fac) for k in range(3)]
    return [max(0.0, x) for x in out]


def test_hsv_on_texture():
    r = astroray.Renderer()
    color = (0.8, 0.2, 0.3)
    make_solid_input(r, "hsv_img", color)
    r.create_program_texture("hsv_tex", "UV")
    r.program_texture_add_input("hsv_tex", "hsv_img")
    # consts: hue, sat, val, fac (broadcast rgb)
    consts = [0.25, 0.25, 0.25, 1.5, 1.5, 1.5, 0.8, 0.8, 0.8, 1.0, 1.0, 1.0]
    code = flat([
        instr(OP_LOAD_TEX, out=0, imm=0),      # color
        instr(OP_LOAD_CONST, out=1, imm=0),    # hue 0.25
        instr(OP_LOAD_CONST, out=2, imm=1),    # sat 1.5
        instr(OP_LOAD_CONST, out=3, imm=2),    # val 0.8
        instr(OP_LOAD_CONST, out=4, imm=3),    # fac 1.0
        instr(OP_HSV, out=5, a=1, b=2, c=3, d=4, e=0),
    ])
    r.set_program_texture_program("hsv_tex", 1, 5, code, consts, [])
    got = r.sample_named_texture("hsv_tex", 0.5, 0.5)
    want = hsv_ref(0.25, 1.5, 0.8, 1.0, list(color))
    assert got == pytest.approx(want, abs=2e-3), (got, want)


# --------------------------------------------------------------------------- #
# 2. Invert on a texture
# --------------------------------------------------------------------------- #
def test_invert_on_texture():
    r = astroray.Renderer()
    color = (0.2, 0.6, 0.9)
    make_solid_input(r, "inv_img", color)
    r.create_program_texture("inv_tex", "UV")
    r.program_texture_add_input("inv_tex", "inv_img")
    consts = [0.75, 0.75, 0.75]  # fac
    code = flat([
        instr(OP_LOAD_TEX, out=0, imm=0),
        instr(OP_LOAD_CONST, out=1, imm=0),
        instr(OP_INVERT, out=2, a=1, b=0),
    ])
    r.set_program_texture_program("inv_tex", 1, 2, code, consts, [])
    got = r.sample_named_texture("inv_tex", 0.5, 0.5)
    fac = 0.75
    want = [c * (1 - fac) + (1 - c) * fac for c in color]
    assert got == pytest.approx(want, abs=2e-3), (got, want)


# --------------------------------------------------------------------------- #
# 3. Gamma on a texture
# --------------------------------------------------------------------------- #
def test_gamma_on_texture():
    r = astroray.Renderer()
    color = (0.25, 0.5, 0.8)
    make_solid_input(r, "gam_img", color)
    r.create_program_texture("gam_tex", "UV")
    r.program_texture_add_input("gam_tex", "gam_img")
    consts = [2.2, 2.2, 2.2]  # gamma
    code = flat([
        instr(OP_LOAD_TEX, out=0, imm=0),
        instr(OP_LOAD_CONST, out=1, imm=0),
        instr(OP_GAMMA, out=2, a=0, b=1),
    ])
    r.set_program_texture_program("gam_tex", 1, 2, code, consts, [])
    got = r.sample_named_texture("gam_tex", 0.5, 0.5)
    want = [c ** 2.2 for c in color]
    assert got == pytest.approx(want, abs=2e-3), (got, want)


# --------------------------------------------------------------------------- #
# 4. Bright/Contrast on a texture
# --------------------------------------------------------------------------- #
def test_bright_contrast_on_texture():
    r = astroray.Renderer()
    color = (0.3, 0.5, 0.7)
    make_solid_input(r, "bc_img", color)
    r.create_program_texture("bc_tex", "UV")
    r.program_texture_add_input("bc_tex", "bc_img")
    bright, contrast = 0.1, 0.5
    consts = [bright]*3 + [contrast]*3
    code = flat([
        instr(OP_LOAD_TEX, out=0, imm=0),
        instr(OP_LOAD_CONST, out=1, imm=0),  # bright
        instr(OP_LOAD_CONST, out=2, imm=1),  # contrast
        instr(OP_BRIGHT_CONTRAST, out=3, a=0, b=1, c=2),
    ])
    r.set_program_texture_program("bc_tex", 1, 3, code, consts, [])
    got = r.sample_named_texture("bc_tex", 0.5, 0.5)
    a = 1.0 + contrast
    b = bright - contrast * 0.5
    want = [max(a * c + b, 0.0) for c in color]
    assert got == pytest.approx(want, abs=2e-3), (got, want)


# --------------------------------------------------------------------------- #
# 5. Separate/Combine Color round-trip (RGB) — swap G and B channels
# --------------------------------------------------------------------------- #
def test_separate_combine_rgb_roundtrip():
    r = astroray.Renderer()
    color = (0.2, 0.5, 0.9)
    make_solid_input(r, "sc_img", color)
    r.create_program_texture("sc_tex", "UV")
    r.program_texture_add_input("sc_tex", "sc_img")
    # separate RGB -> R,G,B (slots 1,2,3); recombine as (R,B,G) -> swap G/B
    code = flat([
        instr(OP_LOAD_TEX, out=0, imm=0),
        instr(OP_SEP_COLOR, out=1, a=0, imm=CS_RGB * 4 + 0),  # R
        instr(OP_SEP_COLOR, out=2, a=0, imm=CS_RGB * 4 + 1),  # G
        instr(OP_SEP_COLOR, out=3, a=0, imm=CS_RGB * 4 + 2),  # B
        instr(OP_COMBINE_COLOR, out=4, a=1, b=3, c=2, imm=CS_RGB),  # R,B,G
    ])
    r.set_program_texture_program("sc_tex", 1, 4, code, [], [])
    got = r.sample_named_texture("sc_tex", 0.5, 0.5)
    want = [color[0], color[2], color[1]]
    assert got == pytest.approx(want, abs=2e-3), (got, want)


# --------------------------------------------------------------------------- #
# 6. Separate/Combine Color HSV round-trip (identity)
# --------------------------------------------------------------------------- #
def test_separate_combine_hsv_roundtrip():
    r = astroray.Renderer()
    color = (0.7, 0.3, 0.5)
    make_solid_input(r, "hsv2_img", color)
    r.create_program_texture("hsv2_tex", "UV")
    r.program_texture_add_input("hsv2_tex", "hsv2_img")
    code = flat([
        instr(OP_LOAD_TEX, out=0, imm=0),
        instr(OP_SEP_COLOR, out=1, a=0, imm=CS_HSV * 4 + 0),  # H
        instr(OP_SEP_COLOR, out=2, a=0, imm=CS_HSV * 4 + 1),  # S
        instr(OP_SEP_COLOR, out=3, a=0, imm=CS_HSV * 4 + 2),  # V
        instr(OP_COMBINE_COLOR, out=4, a=1, b=2, c=3, imm=CS_HSV),
    ])
    r.set_program_texture_program("hsv2_tex", 1, 4, code, [], [])
    got = r.sample_named_texture("hsv2_tex", 0.5, 0.5)
    # sep-HSV then combine-HSV is an identity round-trip
    assert got == pytest.approx(list(color), abs=2e-3), (got, color)


# --------------------------------------------------------------------------- #
# 7. RGB to BW
# --------------------------------------------------------------------------- #
def test_rgb_to_bw_on_texture():
    r = astroray.Renderer()
    color = (0.4, 0.6, 0.2)
    make_solid_input(r, "bw_img", color)
    r.create_program_texture("bw_tex", "UV")
    r.program_texture_add_input("bw_tex", "bw_img")
    code = flat([
        instr(OP_LOAD_TEX, out=0, imm=0),
        instr(OP_RGB_TO_BW, out=1, a=0),
    ])
    r.set_program_texture_program("bw_tex", 1, 1, code, [], [])
    got = r.sample_named_texture("bw_tex", 0.5, 0.5)
    luma = 0.2126729 * color[0] + 0.7151522 * color[1] + 0.0721750 * color[2]
    assert got == pytest.approx([luma, luma, luma], abs=2e-3), (got, luma)

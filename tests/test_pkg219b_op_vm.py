"""pkg219b — Bounded op-VM core: CPU evaluator parity tests.

Each of the four broken chains the coordinator named (Color Ramp, Mix, Math,
Map Range downstream of a texture) is exercised by hand-assembling the bytecode,
running it through the CPU `ProgramTexture` (sample_named_texture), and comparing
against an independent Python reference of the Cycles formula
(pkg219c-blender-node-opcode-semantics.md).

The runtime VM is the shared HD `svm_eval` (include/astroray/shader_vm.h), so a
green CPU test is also the GPU evaluator's correctness oracle — the GPU leg only
adds plumbing, not new math.
"""
import math
import pytest

astroray = pytest.importorskip("astroray")

# ---- opcode / sub-op enums (mirror include/astroray/shader_vm.h) -----------
OP_END, OP_LOAD_TEX, OP_LOAD_CONST, OP_MATH, OP_MIX, OP_RAMP, OP_MAP_RANGE = range(7)
(MATH_ADD, MATH_SUB, MATH_MUL, MATH_DIV, MATH_MULADD, MATH_POW, MATH_SQRT,
 MATH_ABS, MATH_MIN, MATH_MAX, MATH_FLOOR, MATH_CEIL, MATH_FRACT, MATH_MOD,
 MATH_SNAP, MATH_LESS, MATH_GREATER, MATH_SIGN) = range(18)
(MIX_BLEND, MIX_ADD, MIX_MUL, MIX_SUB, MIX_SCREEN, MIX_DIFF, MIX_DARKEN,
 MIX_LIGHTEN, MIX_OVERLAY) = range(9)
MR_LINEAR, MR_STEPPED, MR_SMOOTHSTEP, MR_SMOOTHERSTEP = range(4)

RAMP_TABLE_SIZE = 256


def instr(op, out=0, a=0, b=0, c=0, d=0, e=0, imm=0):
    return [op, out, a, b, c, d, e, imm]


def flat(instrs):
    out = []
    for i in instrs:
        out.extend(i)
    return out


def make_solid_input(r, name="in0", value=(0.4, 0.4, 0.4)):
    """A 1x1 image texture used as a known op-VM input."""
    import numpy as np
    img = np.array(value, dtype="float32").reshape(1, 1, 3).ravel()
    r.load_texture(name, img, 1, 1, "UV")


def clampf(x, lo, hi):
    return lo if x < lo else (hi if x > hi else x)


def sat(x):
    return clampf(x, 0.0, 1.0)


# --------------------------------------------------------------------------- #
# 1. Color Ramp on a texture  (TexCoord→Image→ColorRamp.Fac→Base Color)
# --------------------------------------------------------------------------- #
def ramp_lookup_ref(table, fac):
    f = sat(fac) * (RAMP_TABLE_SIZE - 1)
    i = int(f)
    i = max(0, min(RAMP_TABLE_SIZE - 1, i))
    t = f - i
    c = list(table[i])
    if t > 0.0 and i < RAMP_TABLE_SIZE - 1:
        c = [c[k] * (1.0 - t) + table[i + 1][k] * t for k in range(3)]
    return c


def build_ramp_table_black_to_red():
    # linear black->red ramp
    table = []
    for s in range(RAMP_TABLE_SIZE):
        t = s / (RAMP_TABLE_SIZE - 1)
        table.append((t, 0.0, 0.0))
    return table


def test_color_ramp_on_texture():
    r = astroray.Renderer()
    # input value drives the Fac (grey 0.4)
    make_solid_input(r, "img", (0.4, 0.4, 0.4))
    r.create_program_texture("ramp_tex", "UV")
    r.program_texture_add_input("ramp_tex", "img")
    table = build_ramp_table_black_to_red()
    ramps_flat = []
    for rgb in table:
        ramps_flat.extend(rgb)
    # slot0 = tex0 ; slot1 = ramp(slot0.x)
    code = flat([
        instr(OP_LOAD_TEX, out=0, imm=0),
        instr(OP_RAMP, out=1, a=0, imm=0),
    ])
    r.set_program_texture_program("ramp_tex", 1, 1, code, [], ramps_flat)
    got = r.sample_named_texture("ramp_tex", 0.5, 0.5)
    want = ramp_lookup_ref(table, 0.4)
    assert got == pytest.approx(want, abs=2e-3), (got, want)
    # black->red at fac 0.4 => red≈0.4, green/blue≈0
    assert got[0] == pytest.approx(0.4, abs=2e-3)
    assert got[1] == pytest.approx(0.0, abs=2e-3)


# --------------------------------------------------------------------------- #
# 2. MixRGB of a texture with a constant colour
# --------------------------------------------------------------------------- #
def test_mix_texture_with_constant():
    r = astroray.Renderer()
    make_solid_input(r, "img2", (0.2, 0.6, 0.8))
    r.create_program_texture("mix_tex", "UV")
    r.program_texture_add_input("mix_tex", "img2")
    # slot0 = tex0 ; slot1 = const fac (0.25) ; slot2 = const red ;
    # slot3 = mix(BLEND, fac=slot1.x, c1=slot0, c2=slot2)
    consts = [0.25, 0.25, 0.25,   1.0, 0.0, 0.0]
    code = flat([
        instr(OP_LOAD_TEX, out=0, imm=0),
        instr(OP_LOAD_CONST, out=1, imm=0),
        instr(OP_LOAD_CONST, out=2, imm=1),
        instr(OP_MIX, out=3, a=1, b=0, c=2, imm=MIX_BLEND),
    ])
    r.set_program_texture_program("mix_tex", 1, 3, code, consts, [])
    got = r.sample_named_texture("mix_tex", 0.5, 0.5)
    fac = 0.25
    c1 = [0.2, 0.6, 0.8]
    c2 = [1.0, 0.0, 0.0]
    want = [c1[k] * (1 - fac) + c2[k] * fac for k in range(3)]
    assert got == pytest.approx(want, abs=2e-3), (got, want)


# --------------------------------------------------------------------------- #
# 3. Math (multiply) driving a factor
# --------------------------------------------------------------------------- #
def test_math_multiply_on_texture():
    r = astroray.Renderer()
    make_solid_input(r, "img3", (0.3, 0.3, 0.3))
    r.create_program_texture("math_tex", "UV")
    r.program_texture_add_input("math_tex", "img3")
    consts = [2.0, 2.0, 2.0]
    # slot2 = slot0.x * slot1.x = 0.3*2 = 0.6 (broadcast to rgb)
    code = flat([
        instr(OP_LOAD_TEX, out=0, imm=0),
        instr(OP_LOAD_CONST, out=1, imm=0),
        instr(OP_MATH, out=2, a=0, b=1, imm=MATH_MUL),
    ])
    r.set_program_texture_program("math_tex", 1, 2, code, consts, [])
    got = r.sample_named_texture("math_tex", 0.5, 0.5)
    assert got == pytest.approx([0.6, 0.6, 0.6], abs=2e-3), got


# --------------------------------------------------------------------------- #
# 4. Map Range (linear) remapping a factor
# --------------------------------------------------------------------------- #
def test_map_range_linear_on_texture():
    r = astroray.Renderer()
    make_solid_input(r, "img4", (0.5, 0.5, 0.5))
    r.create_program_texture("mr_tex", "UV")
    r.program_texture_add_input("mr_tex", "img4")
    # map 0.5 from [0,1] to [0.2, 0.7]  => 0.2 + 0.5*(0.5) = 0.45
    consts = [0.0, 0, 0,  1.0, 0, 0,  0.2, 0, 0,  0.7, 0, 0]
    code = flat([
        instr(OP_LOAD_TEX, out=0, imm=0),
        instr(OP_LOAD_CONST, out=1, imm=0),  # from_min
        instr(OP_LOAD_CONST, out=2, imm=1),  # from_max
        instr(OP_LOAD_CONST, out=3, imm=2),  # to_min
        instr(OP_LOAD_CONST, out=4, imm=3),  # to_max
        instr(OP_MAP_RANGE, out=5, a=0, b=1, c=2, d=3, e=4, imm=MR_LINEAR),
    ])
    r.set_program_texture_program("mr_tex", 1, 5, code, consts, [])
    got = r.sample_named_texture("mr_tex", 0.5, 0.5)
    assert got == pytest.approx([0.45, 0.45, 0.45], abs=2e-3), got


# --------------------------------------------------------------------------- #
# 5. Static bound is respected (host rejects an over-long program)
# --------------------------------------------------------------------------- #
def test_program_too_long_rejected():
    r = astroray.Renderer()
    make_solid_input(r, "img5", (0.5, 0.5, 0.5))
    r.create_program_texture("big_tex", "UV")
    r.program_texture_add_input("big_tex", "img5")
    code = flat([instr(OP_MATH, out=0, a=0, b=0, imm=MATH_ADD) for _ in range(33)])
    with pytest.raises(Exception):
        r.set_program_texture_program("big_tex", 1, 0, code, [], [])

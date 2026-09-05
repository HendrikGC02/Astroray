"""pkg230 Phase 2 — Vector Math (OP_VEC_MATH) + Vector Rotate (OP_VEC_ROTATE) tests.

Two halves, both no-bpy:

  * Compiler half (``test_compile_*`` / ``test_parity_*``): duck-typed Blender
    node chains compiled by shader_vm_compiler; asserts emitted bytecode, enum/
    flag parity with include/astroray/shader_vm.h, and that only the operands an
    op reads are compiled (dead hidden sockets cost no register slot).

  * Eval half (``test_eval_*``): hand-assembled bytecode run through the shared
    HD ``svm_eval`` (via sample_named_texture) and compared against an independent
    Python transcription of the Cycles vector formulas. Pinned Cycles reference:
    intern/cycles/kernel/svm/math_util.h + svm/vector_rotate.h + util/transform.h,
    Apache-2.0, commit adfe2921d5f3c0fe699149bcd9bc347543bbd82e.

The eval half needs the freshly built module (new native opcodes); run with
``-k "not eval"`` until the parent rebuilds.
"""
import math
import os
import re
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "blender_addon"))
import shader_vm_compiler as C

_HEADER = os.path.join(os.path.dirname(__file__), "..", "include", "astroray",
                       "shader_vm.h")


def _renderer():
    # Lazy import: the compiler/parity tests run without the built module; only
    # the eval tests need astroray (which must be freshly rebuilt for opcodes
    # 15/16). importorskip inside the helper skips just the eval test.
    return pytest.importorskip("astroray").Renderer()

# ---- opcode / sub-op enums (mirror include/astroray/shader_vm.h) -----------
OP_LOAD_TEX, OP_LOAD_CONST = 1, 2
OP_MIX, OP_VEC_MATH, OP_VEC_ROTATE = 4, 15, 16


# --------------------------------------------------------------------------- #
# Minimal duck-typed Blender node model (with `enabled` socket metadata)
# --------------------------------------------------------------------------- #
class Sock:
    def __init__(self, name, default=0.0, link=None, enabled=True, type=None):
        self.name = name
        self.type = type
        self.default_value = default
        self._link = link
        self.enabled = enabled

    @property
    def is_linked(self):
        return self._link is not None

    @property
    def links(self):
        return [self._link] if self._link else []


class Link:
    def __init__(self, from_node, from_socket_name="Color", type=None):
        self.from_node = from_node
        self.from_socket = SimpleNamespace(name=from_socket_name, type=type)


class SockList:
    def __init__(self, socks):
        self._socks = socks
        self._by_name = {s.name: s for s in socks}

    def get(self, name):
        return self._by_name.get(name)

    def __getitem__(self, i):
        return self._socks[i]

    def __len__(self):
        return len(self._socks)

    def __iter__(self):
        return iter(self._socks)


class Node:
    def __init__(self, type, inputs=None, **kw):
        self.type = type
        self.inputs = SockList(inputs or [])
        for k, v in kw.items():
            setattr(self, k, v)


def _load_program(r, name, compiled, input_values):
    import numpy as np
    r.create_program_texture(name, "UV")
    for i, node in enumerate(compiled['inputs']):
        tex_name = f"{name}_in{i}"
        val = input_values[id(node)]
        img = np.array(val, dtype="float32").reshape(1, 1, 3).ravel()
        r.load_texture(tex_name, img, 1, 1, "UV")
        r.program_texture_add_input(name, tex_name)
    r.set_program_texture_program(name, compiled['num_tex'], compiled['out_slot'],
                                  compiled['code_flat'], compiled['consts_flat'],
                                  compiled['ramps_flat'])


# --------------------------------------------------------------------------- #
# hand-bytecode helpers
# --------------------------------------------------------------------------- #
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


def _instrs(compiled):
    return [compiled['code_flat'][i:i + 8]
            for i in range(0, len(compiled['code_flat']), 8)]


# --------------------------------------------------------------------------- #
# Independent Python transcription of Cycles vector math (Apache-2.0, pinned
# adfe2921d5f3c0fe699149bcd9bc347543bbd82e). Kept separate from the C++ so the
# expected values are not a restatement of the implementation.
# --------------------------------------------------------------------------- #
def _safe_divide(v, w):
    return [v[i] / w[i] if w[i] != 0.0 else 0.0 for i in range(3)]


def _safe_normalize(v):
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n != 0.0 else list(v)


def _cross(a, b):
    return [a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0]]


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _project(v, p):
    l2 = _dot(p, p)
    if l2 == 0.0:
        return [0.0, 0.0, 0.0]
    f = _dot(v, p) / l2
    return [p[i] * f for i in range(3)]


def _reflect(i, n):
    d = _dot(i, n)
    return [i[k] - 2.0 * d * n[k] for k in range(3)]


def _refract(i, n, eta):
    d = _dot(n, i)
    k = 1.0 - eta * eta * (1.0 - d * d)
    if k < 0.0:
        return [0.0, 0.0, 0.0]
    return [eta * i[j] - (eta * d + math.sqrt(k)) * n[j] for j in range(3)]


def _fmod(a, b):
    return [math.fmod(a[i], b[i]) if b[i] != 0.0 else 0.0 for i in range(3)]


def _wrap(value, mx, mn):
    out = []
    for i in range(3):
        rng = mx[i] - mn[i]
        if rng == 0.0:
            out.append(mn[i])
        else:
            out.append(value[i] - math.floor((value[i] - mn[i]) / rng) * rng)
    return out


def _safe_pow(a, b):
    def sp(x, y):
        if y == 0.0:
            return 1.0
        if x == 0.0:
            return 0.0
        if x < 0.0 and y != math.floor(y):
            return 0.0
        return math.pow(x, y)
    return [sp(a[i], b[i]) for i in range(3)]


def vec_math_ref(op, a, b, c, param1):
    if op == 'ADD':
        return [a[i] + b[i] for i in range(3)]
    if op == 'SUBTRACT':
        return [a[i] - b[i] for i in range(3)]
    if op == 'MULTIPLY':
        return [a[i] * b[i] for i in range(3)]
    if op == 'DIVIDE':
        return _safe_divide(a, b)
    if op == 'CROSS_PRODUCT':
        return _cross(a, b)
    if op == 'PROJECT':
        return _project(a, b)
    if op == 'REFLECT':
        return _reflect(a, _safe_normalize(b))
    if op == 'REFRACT':
        return _refract(a, _safe_normalize(b), param1)
    if op == 'FACEFORWARD':
        return list(a) if _dot(c, b) < 0.0 else [-x for x in a]
    if op == 'MULTIPLY_ADD':
        return [a[i] * b[i] + c[i] for i in range(3)]
    if op == 'DOT_PRODUCT':
        return [_dot(a, b)] * 3
    if op == 'DISTANCE':
        return [math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))] * 3
    if op == 'LENGTH':
        return [math.sqrt(sum(x * x for x in a))] * 3
    if op == 'SCALE':
        return [a[i] * param1 for i in range(3)]
    if op == 'NORMALIZE':
        return _safe_normalize(a)
    if op == 'SNAP':
        return [math.floor(_safe_divide(a, b)[i]) * b[i] for i in range(3)]
    if op == 'ROUND':
        return [math.floor(x + 0.5) for x in a]
    if op == 'FLOOR':
        return [math.floor(x) for x in a]
    if op == 'CEIL':
        return [math.ceil(x) for x in a]
    if op == 'MODULO':
        return _fmod(a, b)
    if op == 'WRAP':
        return _wrap(a, b, c)
    if op == 'FRACTION':
        return [x - math.floor(x) for x in a]
    if op == 'ABSOLUTE':
        return [abs(x) for x in a]
    if op == 'POWER':
        return _safe_pow(a, b)
    if op == 'SIGN':
        return [0.0 if x == 0.0 else (1.0 if x > 0.0 else -1.0) for x in a]
    if op == 'MINIMUM':
        return [min(a[i], b[i]) for i in range(3)]
    if op == 'MAXIMUM':
        return [max(a[i], b[i]) for i in range(3)]
    if op == 'SINE':
        return [math.sin(x) for x in a]
    if op == 'COSINE':
        return [math.cos(x) for x in a]
    if op == 'TANGENT':
        return [math.tan(x) for x in a]
    raise ValueError(op)


def _rotate_around_axis(p, axis, angle):
    ct, st, u = math.cos(angle), math.sin(angle), 1.0 - math.cos(angle)
    x, y, z = axis
    return [
        (ct + u * x * x) * p[0] + (u * x * y - z * st) * p[1] + (u * x * z + y * st) * p[2],
        (u * x * y + z * st) * p[0] + (ct + u * y * y) * p[1] + (u * y * z - x * st) * p[2],
        (u * x * z - y * st) * p[0] + (u * y * z + x * st) * p[1] + (ct + u * z * z) * p[2],
    ]


def _euler_matrix(e):
    cx, cy, cz = math.cos(e[0]), math.cos(e[1]), math.cos(e[2])
    sx, sy, sz = math.sin(e[0]), math.sin(e[1]), math.sin(e[2])
    return [
        [cy * cz, sy * sx * cz - cx * sz, sy * cx * cz + sx * sz],
        [cy * sz, sy * sx * sz + cx * cz, sy * cx * sz - sx * cz],
        [-sy, cy * sx, cy * cx],
    ]


def vec_rotate_ref(rtype, invert, vec, center, axis, angle, rotation):
    if rtype == 'EULER_XYZ':
        R = _euler_matrix(rotation)
        v = [vec[i] - center[i] for i in range(3)]
        if invert:  # transposed rotation matrix (== inverse)
            out = [sum(R[j][i] * v[j] for j in range(3)) for i in range(3)]
        else:
            out = [sum(R[i][j] * v[j] for j in range(3)) for i in range(3)]
        return [out[i] + center[i] for i in range(3)]
    ax = {'X_AXIS': [1, 0, 0], 'Y_AXIS': [0, 1, 0], 'Z_AXIS': [0, 0, 1]}.get(rtype, axis)
    alen = math.sqrt(sum(x * x for x in ax))
    if alen == 0.0:
        return list(vec)
    a = -angle if invert else angle
    axn = [x / alen for x in ax]
    r = _rotate_around_axis([vec[i] - center[i] for i in range(3)], axn, a)
    return [r[i] + center[i] for i in range(3)]


# --------------------------------------------------------------------------- #
# enum / flag parity with the header
# --------------------------------------------------------------------------- #
def test_parity_opcodes_and_flags():
    assert (C.OP_VEC_MATH, C.OP_VEC_ROTATE) == (15, 16)
    assert C.SVM_MIX_UNCLAMP_FACTOR == 0x40
    assert C.VEC_ROTATE_INVERT == 0x08
    with open(_HEADER, "r", encoding="utf-8") as f:
        src = f.read()
    assert re.search(r"OP_VEC_MATH\s*=\s*15", src)
    assert re.search(r"OP_VEC_ROTATE\s*=\s*16", src)
    assert re.search(r"SVM_MIX_UNCLAMP_FACTOR\s*=\s*0x40", src)
    assert re.search(r"VEC_ROTATE_INVERT\s*=\s*0x08", src)
    assert re.search(r"VECROT_AXIS_ANGLE\s*=\s*0", src)


def _header_enum_names(src, enum_name):
    m = re.search(r"enum\s+" + enum_name + r"\s*:\s*unsigned char\s*\{(.*?)\};",
                  src, re.DOTALL)
    assert m, f"enum {enum_name} not found in header"
    body = m.group(1)
    names = re.findall(r"\b([A-Z_][A-Z0-9_]*)\b", body)
    # drop the first explicit "= N" initializer and trailing commas are ignored
    return names


def test_parity_vec_math_enum_order():
    with open(_HEADER, "r", encoding="utf-8") as f:
        src = f.read()
    header_names = _header_enum_names(src, "VecMathOp")
    header_keys = [n[len("VECMATH_"):] for n in header_names]
    assert header_keys == sorted(C.VEC_MATH_OPS, key=lambda k: C.VEC_MATH_OPS[k])
    assert len(header_keys) == 30


def test_parity_vec_rotate_enum_order():
    with open(_HEADER, "r", encoding="utf-8") as f:
        src = f.read()
    header_names = _header_enum_names(src, "VecRotateType")
    header_keys = [n[len("VECROT_"):] for n in header_names]
    assert header_keys == sorted(C.VEC_ROTATE_TYPES, key=lambda k: C.VEC_ROTATE_TYPES[k])
    assert header_keys == ['AXIS_ANGLE', 'X_AXIS', 'Y_AXIS', 'Z_AXIS', 'EULER_XYZ']


# --------------------------------------------------------------------------- #
# compiler: Vector Math
# --------------------------------------------------------------------------- #
def test_compile_vec_math_add_by_position():
    # Duplicate "Vector" sockets must be read BY POSITION, not by name.
    texA = Node('TEX_IMAGE')
    texB = Node('TEX_IMAGE')
    vm = Node('VECT_MATH', operation='ADD',
              inputs=[Sock('Vector', 0.0, Link(texA, 'Color')),
                      Sock('Vector', 0.0, Link(texB, 'Color')),
                      Sock('Vector', 0.0),
                      Sock('Scale', 1.0)])
    base = Sock('Base Color', [0.5, 0.5, 0.5], Link(vm, 'Vector'))
    compiled = C.compile_chain(base)
    assert compiled is not None and compiled['num_tex'] == 2
    assert [id(n) for n in compiled['inputs']] == [id(texA), id(texB)]
    vec = [i for i in _instrs(compiled) if i[0] == C.OP_VEC_MATH]
    assert len(vec) == 1
    _op, _out, a, b, _c, _d, _e, imm = vec[0]
    assert imm == C.VEC_MATH_OPS['ADD']
    assert a != b  # Vector0 and Vector1 routed to different slots


def test_compile_vec_math_only_used_operands():
    # NORMALIZE reads only Vector0. The dead Vector1/Vector2/Scale link to an
    # unsupported node; they must not be compiled (no VMCompileError, no slots).
    tex = Node('TEX_IMAGE')
    weird = Node('BUMP', inputs=[Sock('Height', 0.0, Link(tex, 'Color'))])
    vm = Node('VECT_MATH', operation='NORMALIZE',
              inputs=[Sock('Vector', 0.0, Link(tex, 'Color')),
                      Sock('Vector', 0.0, Link(weird, 'Normal')),
                      Sock('Vector', 0.0, Link(weird, 'Normal')),
                      Sock('Scale', 1.0, Link(weird, 'Normal'))])
    base = Sock('Base Color', [0.5, 0.5, 0.5], Link(vm, 'Vector'))
    compiled = C.compile_chain(base)
    assert compiled is not None
    assert compiled['num_tex'] == 1
    assert len(compiled['code_flat']) == 16  # LOAD_TEX + VEC_MATH only


def test_compile_vec_math_used_subset():
    # MULTIPLY_ADD reads Vector0+Vector1+Vector2 but not Scale (dead Scale links
    # to an unsupported node and must be skipped).
    tex = Node('TEX_IMAGE')
    weird = Node('BUMP', inputs=[Sock('Height', 0.0, Link(tex, 'Color'))])
    vm = Node('VECT_MATH', operation='MULTIPLY_ADD',
              inputs=[Sock('Vector', 0.0, Link(tex, 'Color')),
                      Sock('Vector', 1.0),
                      Sock('Vector', 2.0),
                      Sock('Scale', 1.0, Link(weird, 'Normal'))])
    base = Sock('Base Color', [0.5, 0.5, 0.5], Link(vm, 'Vector'))
    compiled = C.compile_chain(base)
    assert compiled is not None
    # LOAD_TEX + 2 LOAD_CONST (Vector1/Vector2) + VEC_MATH = 4 instrs (32 ints);
    # a compiled Scale would add a 5th.
    assert len(compiled['code_flat']) == 32
    # Instr layout: [op, out, a, b, c, d, e, imm]
    vec = next(i for i in _instrs(compiled) if i[0] == C.OP_VEC_MATH)
    assert vec[3] != 0  # b = Vector1 (compiled)
    assert vec[4] != 0  # c = Vector2 (compiled)
    assert vec[5] == 0  # d = Scale (dead, left unused)


def test_compile_vec_math_unknown_op_raises():
    tex = Node('TEX_IMAGE')
    vm = Node('VECT_MATH', operation='NOPE',
              inputs=[Sock('Vector', 0.0, Link(tex, 'Color'))])
    base = Sock('Base Color', [0.5, 0.5, 0.5], Link(vm, 'Vector'))
    with pytest.raises(C.VMCompileError):
        C.compile_chain(base)


# --------------------------------------------------------------------------- #
# compiler: Vector Rotate
# --------------------------------------------------------------------------- #
def test_compile_vec_rotate_types_and_invert():
    tex = Node('TEX_IMAGE')
    for rtype, want_imm in [('AXIS_ANGLE', 0), ('X_AXIS', 1), ('Y_AXIS', 2),
                            ('Z_AXIS', 3), ('EULER_XYZ', 4)]:
        vr = Node('VECTOR_ROTATE', rotation_type=rtype, invert=False,
                  inputs=[Sock('Vector', 0.0, Link(tex, 'Color')),
                          Sock('Center', [0, 0, 0]),
                          Sock('Axis', [0, 0, 1]),
                          Sock('Angle', 0.0),
                          Sock('Rotation', [0, 0, 0])])
        base = Sock('Base Color', [0.5, 0.5, 0.5], Link(vr, 'Vector'))
        compiled = C.compile_chain(base)
        rot = [i for i in _instrs(compiled) if i[0] == C.OP_VEC_ROTATE]
        assert len(rot) == 1, rtype
        assert rot[0][7] == want_imm, rtype
        vr.invert = True
        compiled_inv = C.compile_chain(base)
        rot_inv = next(i for i in _instrs(compiled_inv) if i[0] == C.OP_VEC_ROTATE)
        assert rot_inv[7] == (want_imm | 0x08), rtype


def test_compile_vec_rotate_operand_routing():
    tex = Node('TEX_IMAGE')
    # EULER_XYZ reads Rotation (index 4) into c, Angle (index 3) is dead.
    vr = Node('VECTOR_ROTATE', rotation_type='EULER_XYZ', invert=False,
              inputs=[Sock('Vector', 0.0, Link(tex, 'Color')),
                      Sock('Center', [0, 0, 0]),
                      Sock('Axis', [1, 0, 0]),
                      Sock('Angle', 1.0),
                      Sock('Rotation', [0, 0, 0])])
    base = Sock('Base Color', [0.5, 0.5, 0.5], Link(vr, 'Vector'))
    compiled = C.compile_chain(base)
    rot = next(i for i in _instrs(compiled) if i[0] == C.OP_VEC_ROTATE)
    # Instr layout: [op, out, a, b, c, d, e, imm]
    assert rot[4] != 0  # c slot carries rotation
    assert rot[5] == 0  # d slot unused (no axis-angle)

    # X/Y/Z axis reads Angle (index 3) into d; the axis slot (c) is unused.
    vr2 = Node('VECTOR_ROTATE', rotation_type='Z_AXIS', invert=False,
               inputs=[Sock('Vector', 0.0, Link(tex, 'Color')),
                       Sock('Center', [0, 0, 0]),
                       Sock('Axis', [1, 0, 0]),
                       Sock('Angle', 0.5),
                       Sock('Rotation', [0, 0, 0])])
    base2 = Sock('Base Color', [0.5, 0.5, 0.5], Link(vr2, 'Vector'))
    compiled2 = C.compile_chain(base2)
    rot2 = next(i for i in _instrs(compiled2) if i[0] == C.OP_VEC_ROTATE)
    assert rot2[4] == 0  # c slot unused
    assert rot2[5] != 0  # d slot carries angle


def test_compile_vec_rotate_unknown_type_raises():
    tex = Node('TEX_IMAGE')
    vr = Node('VECTOR_ROTATE', rotation_type='QUATERNION',
              inputs=[Sock('Vector', 0.0, Link(tex, 'Color'))])
    base = Sock('Base Color', [0.5, 0.5, 0.5], Link(vr, 'Vector'))
    with pytest.raises(C.VMCompileError):
        C.compile_chain(base)


# --------------------------------------------------------------------------- #
# compiler: modern Mix socket selection + factor flag
# --------------------------------------------------------------------------- #
def _modern_mix_rgba(factor, a, b, blend='MIX', clamp_factor=True,
                     clamp_result=False):
    """A real Blender-5.1-shaped ShaderNodeMix: 10 sockets, RGBA enables 0/6/7."""
    tex_a = a if isinstance(a, Node) else None
    tex_b = b if isinstance(b, Node) else None
    return Node('MIX', data_type='RGBA', blend_type=blend,
                clamp_factor=clamp_factor, clamp_result=clamp_result,
                inputs=[
                    Sock('Factor', factor, None, enabled=True),            # 0 float
                    Sock('Factor', factor, None, enabled=False),           # 1 vector
                    Sock('A', 0.0, Link(a, 'Color') if tex_a else None, enabled=False),  # 2 FLOAT
                    Sock('B', 0.0, None, enabled=False),                   # 3 FLOAT
                    Sock('A', 0.0, None, enabled=False),                   # 4 VECTOR
                    Sock('B', 0.0, None, enabled=False),                   # 5 VECTOR
                    Sock('A', 0.0, Link(a, 'Color') if tex_a else None, enabled=True),   # 6 RGBA
                    Sock('B', 0.0, Link(b, 'Color') if tex_b else None, enabled=True),   # 7 RGBA
                    Sock('A', 0.0, None, enabled=False),                   # 8 ROTATION
                    Sock('B', 0.0, None, enabled=False),                   # 9 ROTATION
                ])


def test_compile_mix_selects_enabled_rgba_sockets():
    tex_float_a = Node('TEX_IMAGE')   # linked to the DISABLED float A (index 2)
    tex_rgba_a = Node('TEX_IMAGE')    # linked to the ENABLED rgba A (index 6)
    tex_b = Node('TEX_IMAGE')         # linked to the ENABLED rgba B (index 7)
    mix = _modern_mix_rgba(0.5, tex_rgba_a, tex_b)
    # override the disabled float-A socket to point at tex_float_a
    mix.inputs._socks[2] = Sock('A', 0.0, Link(tex_float_a, 'Color'), enabled=False)
    mix.inputs._by_name = {s.name: s for s in mix.inputs._socks}
    base = Sock('Base Color', [0.5, 0.5, 0.5], Link(mix, 'Result'))
    compiled = C.compile_chain(base)
    assert compiled is not None
    input_ids = [id(n) for n in compiled['inputs']]
    assert id(tex_rgba_a) in input_ids   # enabled A used
    assert id(tex_b) in input_ids        # enabled B used
    assert id(tex_float_a) not in input_ids  # disabled float A ignored


def test_compile_mix_unclamp_factor_flag():
    texA = Node('TEX_IMAGE')
    texB = Node('TEX_IMAGE')
    for clamp_factor, want_bit in [(True, 0), (False, C.SVM_MIX_UNCLAMP_FACTOR)]:
        mix = Node('MIX', data_type='RGBA', blend_type='MIX',
                   clamp_factor=clamp_factor,
                   inputs=[Sock('Factor', 1.5),
                           Sock('A', [0, 0, 0], Link(texA, 'Color')),
                           Sock('B', [1, 1, 1], Link(texB, 'Color'))])
        base = Sock('Base Color', [0.5, 0.5, 0.5], Link(mix, 'Result'))
        compiled = C.compile_chain(base)
        m = next(i for i in _instrs(compiled) if i[0] == C.OP_MIX)
        assert (m[7] & C.SVM_MIX_UNCLAMP_FACTOR) == want_bit, clamp_factor


def test_compile_mix_legacy_never_unclamps():
    tex = Node('TEX_IMAGE')
    mix = Node('MIX_RGB', blend_type='MIX',  # legacy node has no clamp_factor
               inputs=[Sock('Fac', 1.5),
                       Sock('Color1', [0, 0, 0], Link(tex, 'Color')),
                       Sock('Color2', [1, 1, 1])])
    base = Sock('Base Color', [0.5, 0.5, 0.5], Link(mix, 'Color'))
    compiled = C.compile_chain(base)
    m = next(i for i in _instrs(compiled) if i[0] == C.OP_MIX)
    assert (m[7] & C.SVM_MIX_UNCLAMP_FACTOR) == 0


def test_compile_mix_float_uses_linear_ignores_blend():
    # FLOAT data_type: linear mix regardless of the stale blend_type property.
    tex = Node('TEX_IMAGE')
    mix = Node('MIX', data_type='FLOAT', blend_type='ADD',
               inputs=[Sock('Factor', 0.5, None, enabled=True),
                       Sock('A', 0.2, Link(tex, 'Color'), enabled=True),
                       Sock('B', 0.6, None, enabled=True)])
    base = Sock('Base Color', [0.5, 0.5, 0.5], Link(mix, 'Result'))
    compiled = C.compile_chain(base)
    assert compiled is not None
    m = next(i for i in _instrs(compiled) if i[0] == C.OP_MIX)
    assert (m[7] & 0x3F) == C.MIX_OPS['MIX']   # linear, not ADD
    assert (m[7] & C.SVM_MIX_CLAMP_RESULT) == 0  # clamp_result only applies to RGBA


def test_compile_mix_rotation_raises():
    mix = Node('MIX', data_type='ROTATION',
               inputs=[Sock('Factor', 0.5, None, enabled=True),
                       Sock('A', 0.0, None, enabled=True),
                       Sock('B', 0.0, None, enabled=True)])
    base = Sock('Base Color', [0.5, 0.5, 0.5], Link(mix, 'Result'))
    with pytest.raises(C.VMCompileError):
        C.compile_chain(base)


def test_compile_mix_nonuniform_vector_raises():
    mix = Node('MIX', data_type='VECTOR', factor_mode='NON_UNIFORM',
               inputs=[Sock('Factor', 0.5, None, enabled=True),
                       Sock('A', 0.0, None, enabled=True),
                       Sock('B', 0.0, None, enabled=True)])
    base = Sock('Base Color', [0.5, 0.5, 0.5], Link(mix, 'Result'))
    with pytest.raises(C.VMCompileError):
        C.compile_chain(base)


# --------------------------------------------------------------------------- #
# eval: all 30 vector math ops against the independent reference
# --------------------------------------------------------------------------- #
def _run_vec_math(r, name, op, a, b, c, scale):
    make_solid_input(r, name + "_img", a)
    r.create_program_texture(name, "UV")
    r.program_texture_add_input(name, name + "_img")
    consts = list(b) + list(c) + [scale] * 3
    code = flat([
        instr(OP_LOAD_TEX, out=0, imm=0),
        instr(OP_LOAD_CONST, out=1, imm=0),   # b
        instr(OP_LOAD_CONST, out=2, imm=1),   # c
        instr(OP_LOAD_CONST, out=3, imm=2),   # scale (param1)
        instr(OP_VEC_MATH, out=4, a=0, b=1, c=2, d=3, imm=C.VEC_MATH_OPS[op]),
    ])
    r.set_program_texture_program(name, 1, 4, code, consts, [])
    return r.sample_named_texture(name, 0.5, 0.5)


@pytest.mark.parametrize("op", sorted(C.VEC_MATH_OPS))
def test_eval_all_vec_math_ops(op):
    a = (0.7, -0.3, 1.25)
    b = (0.4, 0.8, -0.6)
    c = (0.2, 0.5, 0.9)
    scale = 2.0
    r = _renderer()
    got = _run_vec_math(r, "vm_" + op, op, a, b, c, scale)
    want = vec_math_ref(op, a, b, c, scale)
    assert got == pytest.approx(want, abs=3e-3), (op, got, want)


def test_eval_divide_by_zero():
    r = _renderer()
    got = _run_vec_math(r, "div0", 'DIVIDE', (1.0, 2.0, 3.0), (0.0, 2.0, 0.0),
                        (0, 0, 0), 1.0)
    assert got == pytest.approx([0.0, 1.0, 0.0], abs=1e-6), got


def test_eval_normalize_zero_and_length_distance_dot():
    r = _renderer()
    got = _run_vec_math(r, "norm0", 'NORMALIZE', (0.0, 0.0, 0.0), (0, 0, 0),
                        (0, 0, 0), 1.0)
    assert got == pytest.approx([0.0, 0.0, 0.0], abs=1e-6), got
    got = _run_vec_math(r, "len", 'LENGTH', (3.0, 4.0, 0.0), (0, 0, 0), (0, 0, 0), 1.0)
    assert got == pytest.approx([5.0, 5.0, 5.0], abs=1e-5), got
    got = _run_vec_math(r, "dist", 'DISTANCE', (1.0, 2.0, 3.0), (4.0, 6.0, 3.0),
                        (0, 0, 0), 1.0)
    assert got == pytest.approx([5.0, 5.0, 5.0], abs=1e-5), got
    got = _run_vec_math(r, "dot", 'DOT_PRODUCT', (1.0, 2.0, 3.0), (4.0, 5.0, 6.0),
                        (0, 0, 0), 1.0)
    assert got == pytest.approx([32.0, 32.0, 32.0], abs=1e-5), got


def test_eval_project_and_cross():
    r = _renderer()
    got = _run_vec_math(r, "proj0", 'PROJECT', (1.0, 2.0, 3.0), (0.0, 0.0, 0.0),
                        (0, 0, 0), 1.0)
    assert got == pytest.approx([0.0, 0.0, 0.0], abs=1e-6), got
    got = _run_vec_math(r, "cross", 'CROSS_PRODUCT', (1.0, 0.0, 0.0), (0.0, 1.0, 0.0),
                        (0, 0, 0), 1.0)
    assert got == pytest.approx([0.0, 0.0, 1.0], abs=1e-6), got


def test_eval_modulo_negative_and_wrap():
    r = _renderer()
    got = _run_vec_math(r, "mod", 'MODULO', (-5.0, 5.0, -7.0), (2.0, 2.0, 3.0),
                        (0, 0, 0), 1.0)
    assert got == pytest.approx([-1.0, 1.0, -1.0], abs=1e-5), got
    # wrap(value, max, min): 5.5 -> 1.5, -3.0 -> 1.0, 0.0 -> 0.0 in [min=-2, max=2)
    got = _run_vec_math(r, "wrap", 'WRAP', (5.5, -3.0, 0.0), (2.0, 2.0, 2.0),
                        (-2.0, -2.0, -2.0), 1.0)
    assert got == pytest.approx([1.5, 1.0, 0.0], abs=1e-5), got


def test_eval_reflect_and_refract():
    r = _renderer()
    got = _run_vec_math(r, "refl", 'REFLECT', (1.0, -1.0, 0.0), (0.0, 1.0, 0.0),
                        (0, 0, 0), 1.0)
    assert got == pytest.approx([1.0, 1.0, 0.0], abs=1e-5), got
    # straight-on refract: incident (0,-1,0), normal (0,1,0), eta=1.5 -> (0,-1,0)
    got = _run_vec_math(r, "refr", 'REFRACT', (0.0, -1.0, 0.0), (0.0, 1.0, 0.0),
                        (0, 0, 0), 1.5)
    assert got == pytest.approx([0.0, -1.0, 0.0], abs=1e-5), got
    # TIR: incident perpendicular to normal, eta=1.5 -> k = 1-2.25 < 0 -> zero
    got = _run_vec_math(r, "tir", 'REFRACT', (1.0, 0.0, 0.0), (0.0, 1.0, 0.0),
                        (0, 0, 0), 1.5)
    assert got == pytest.approx([0.0, 0.0, 0.0], abs=1e-6), got


def test_eval_faceforward():
    r = _renderer()
    got = _run_vec_math(r, "ff1", 'FACEFORWARD', (1.0, 2.0, 3.0), (1.0, 0.0, 0.0),
                        (1.0, 0.0, 0.0), 1.0)
    assert got == pytest.approx([-1.0, -2.0, -3.0], abs=1e-5), got
    got = _run_vec_math(r, "ff2", 'FACEFORWARD', (1.0, 2.0, 3.0), (1.0, 0.0, 0.0),
                        (-1.0, 0.0, 0.0), 1.0)
    assert got == pytest.approx([1.0, 2.0, 3.0], abs=1e-5), got


def test_eval_round_floor_ceil_fraction_sign():
    r = _renderer()
    got = _run_vec_math(r, "round", 'ROUND', (1.4, 1.5, -1.5), (0, 0, 0), (0, 0, 0), 1.0)
    assert got == pytest.approx([1.0, 2.0, -1.0], abs=1e-5), got  # floor(x+0.5)
    got = _run_vec_math(r, "floor", 'FLOOR', (1.8, -1.2, 0.5), (0, 0, 0), (0, 0, 0), 1.0)
    assert got == pytest.approx([1.0, -2.0, 0.0], abs=1e-5), got
    got = _run_vec_math(r, "ceil", 'CEIL', (1.8, -1.2, 0.5), (0, 0, 0), (0, 0, 0), 1.0)
    assert got == pytest.approx([2.0, -1.0, 1.0], abs=1e-5), got
    got = _run_vec_math(r, "fract", 'FRACTION', (1.8, -1.2, 0.5), (0, 0, 0), (0, 0, 0), 1.0)
    assert got == pytest.approx([0.8, 0.8, 0.5], abs=1e-5), got
    got = _run_vec_math(r, "sign", 'SIGN', (-3.0, 0.0, 4.0), (0, 0, 0), (0, 0, 0), 1.0)
    assert got == pytest.approx([-1.0, 0.0, 1.0], abs=1e-6), got


def test_eval_scale_multiply_add_power():
    r = _renderer()
    got = _run_vec_math(r, "scale", 'SCALE', (1.0, 2.0, -3.0), (0, 0, 0), (0, 0, 0), 2.5)
    assert got == pytest.approx([2.5, 5.0, -7.5], abs=1e-5), got
    got = _run_vec_math(r, "madd", 'MULTIPLY_ADD', (1.0, 2.0, 3.0), (4.0, 5.0, 6.0),
                        (0.5, -1.0, 2.0), 1.0)
    assert got == pytest.approx([4.5, 9.0, 20.0], abs=1e-5), got
    got = _run_vec_math(r, "pow", 'POWER', (2.0, 4.0, 9.0), (0.5, 0.5, 0.5), (0, 0, 0), 1.0)
    assert got == pytest.approx([math.sqrt(2), 2.0, 3.0], abs=1e-5), got


# --------------------------------------------------------------------------- #
# eval: Vector Rotate
# --------------------------------------------------------------------------- #
def _run_rotate(r, name, rtype, invert, vec, center, axis, angle, rotation):
    make_solid_input(r, name + "_img", vec)
    r.create_program_texture(name, "UV")
    r.program_texture_add_input(name, name + "_img")
    # consts: center(0), axis(1), angle(2), rotation(3)
    consts = list(center) + list(axis) + [angle] * 3 + list(rotation)
    imm = C.VEC_ROTATE_TYPES[rtype] | (0x08 if invert else 0)
    if rtype == 'AXIS_ANGLE':
        code = flat([
            instr(OP_LOAD_TEX, out=0, imm=0),
            instr(OP_LOAD_CONST, out=1, imm=0),
            instr(OP_LOAD_CONST, out=2, imm=1),
            instr(OP_LOAD_CONST, out=3, imm=2),
            instr(OP_VEC_ROTATE, out=4, a=0, b=1, c=2, d=3, imm=imm),
        ])
        out_slot = 4
    elif rtype == 'EULER_XYZ':
        code = flat([
            instr(OP_LOAD_TEX, out=0, imm=0),
            instr(OP_LOAD_CONST, out=1, imm=0),
            instr(OP_LOAD_CONST, out=2, imm=3),
            instr(OP_VEC_ROTATE, out=3, a=0, b=1, c=2, d=0, imm=imm),
        ])
        out_slot = 3
    else:
        code = flat([
            instr(OP_LOAD_TEX, out=0, imm=0),
            instr(OP_LOAD_CONST, out=1, imm=0),   # center
            instr(OP_LOAD_CONST, out=2, imm=2),   # angle (goes in d slot)
            instr(OP_VEC_ROTATE, out=3, a=0, b=1, c=0, d=2, imm=imm),
        ])
        out_slot = 3
    r.set_program_texture_program(name, 1, out_slot, code, consts, [])
    return r.sample_named_texture(name, 0.5, 0.5)


def test_eval_rotate_axis_angle_90_deg():
    r = _renderer()
    got = _run_rotate(r, "raa", 'AXIS_ANGLE', False, (1.0, 0.0, 0.0), (0, 0, 0),
                      (0.0, 0.0, 1.0), math.pi / 2, (0, 0, 0))
    assert got == pytest.approx([0.0, 1.0, 0.0], abs=1e-5), got


def test_eval_rotate_single_axes():
    r = _renderer()
    got = _run_rotate(r, "rx", 'X_AXIS', False, (0.0, 1.0, 0.0), (0, 0, 0),
                      (0, 0, 0), math.pi / 2, (0, 0, 0))
    assert got == pytest.approx([0.0, 0.0, 1.0], abs=1e-5), got
    got = _run_rotate(r, "ry", 'Y_AXIS', False, (1.0, 0.0, 0.0), (0, 0, 0),
                      (0, 0, 0), math.pi / 2, (0, 0, 0))
    assert got == pytest.approx([0.0, 0.0, -1.0], abs=1e-5), got
    got = _run_rotate(r, "rz", 'Z_AXIS', False, (1.0, 0.0, 0.0), (0, 0, 0),
                      (0, 0, 0), math.pi / 2, (0, 0, 0))
    assert got == pytest.approx([0.0, 1.0, 0.0], abs=1e-5), got


def test_eval_rotate_invert_negates_angle():
    r = _renderer()
    # Z-axis 90° then invert -> -90° -> (0,-1,0)
    got = _run_rotate(r, "rzinv", 'Z_AXIS', True, (1.0, 0.0, 0.0), (0, 0, 0),
                      (0, 0, 0), math.pi / 2, (0, 0, 0))
    assert got == pytest.approx([0.0, -1.0, 0.0], abs=1e-5), got
    # axis-angle invert negates the angle too
    got = _run_rotate(r, "aainv", 'AXIS_ANGLE', True, (1.0, 0.0, 0.0), (0, 0, 0),
                      (0.0, 0.0, 1.0), math.pi / 2, (0, 0, 0))
    assert got == pytest.approx([0.0, -1.0, 0.0], abs=1e-5), got


def test_eval_rotate_zero_axis_returns_input():
    r = _renderer()
    got = _run_rotate(r, "zeroax", 'AXIS_ANGLE', False, (1.0, 2.0, 3.0), (0, 0, 0),
                      (0.0, 0.0, 0.0), math.pi / 2, (0, 0, 0))
    assert got == pytest.approx([1.0, 2.0, 3.0], abs=1e-6), got


def test_eval_rotate_nonzero_center():
    r = _renderer()
    # rotate the point (2,0,0) around center (1,0,0) by +90° about Z -> (1,1,0)
    got = _run_rotate(r, "ctr", 'Z_AXIS', False, (2.0, 0.0, 0.0), (1.0, 0.0, 0.0),
                      (0, 0, 0), math.pi / 2, (0, 0, 0))
    assert got == pytest.approx([1.0, 1.0, 0.0], abs=1e-5), got


def test_eval_rotate_euler_single_axis():
    r = _renderer()
    got = _run_rotate(r, "eulz", 'EULER_XYZ', False, (1.0, 0.0, 0.0), (0, 0, 0),
                      (0, 0, 0), 0.0, (0.0, 0.0, math.pi / 2))
    assert got == pytest.approx([0.0, 1.0, 0.0], abs=1e-5), got


def test_eval_rotate_euler_multi_axis_inverse_matrix_oracle():
    import numpy as np
    rotation = (0.3, -0.5, 0.8)   # all three axes nonzero
    vec = (1.0, 0.5, -0.7)
    center = (0.25, -0.4, 0.6)
    # Independent oracle: R = Rz @ Ry @ Rx (Blender XYZ), invert = R^T = R^-1.
    rx, ry, rz = rotation
    Rx = np.array([[1, 0, 0],
                   [0, math.cos(rx), -math.sin(rx)],
                   [0, math.sin(rx), math.cos(rx)]])
    Ry = np.array([[math.cos(ry), 0, math.sin(ry)],
                   [0, 1, 0],
                   [-math.sin(ry), 0, math.cos(ry)]])
    Rz = np.array([[math.cos(rz), -math.sin(rz), 0],
                   [math.sin(rz), math.cos(rz), 0],
                   [0, 0, 1]])
    R = Rz @ Ry @ Rx
    v = np.array(vec) - np.array(center)
    r = _renderer()
    got_fwd = _run_rotate(r, "eulfwd", 'EULER_XYZ', False, vec, center, (0, 0, 0),
                          0.0, rotation)
    assert got_fwd == pytest.approx((R @ v + np.array(center)).tolist(), abs=5e-3), got_fwd
    got_inv = _run_rotate(r, "eulinv", 'EULER_XYZ', True, vec, center, (0, 0, 0),
                          0.0, rotation)
    assert got_inv == pytest.approx((R.T @ v + np.array(center)).tolist(), abs=5e-3), got_inv


# --------------------------------------------------------------------------- #
# eval: dynamic linked operands via the compiler
# --------------------------------------------------------------------------- #
def test_eval_vec_math_linked_operands():
    texA = Node('TEX_IMAGE')
    texB = Node('TEX_IMAGE')
    vm = Node('VECT_MATH', operation='ADD',
              inputs=[Sock('Vector', 0.0, Link(texA, 'Color')),
                      Sock('Vector', 0.0, Link(texB, 'Color')),
                      Sock('Vector', 0.0),
                      Sock('Scale', 1.0)])
    base = Sock('Base Color', [0.5, 0.5, 0.5], Link(vm, 'Vector'))
    compiled = C.compile_chain(base)
    assert compiled is not None and compiled['num_tex'] == 2
    r = _renderer()
    _load_program(r, "vmlink", compiled,
                  {id(texA): (0.1, 0.2, 0.3), id(texB): (0.4, 0.5, 0.6)})
    got = r.sample_named_texture("vmlink", 0.5, 0.5)
    assert got == pytest.approx([0.5, 0.7, 0.9], abs=3e-3), got


# --------------------------------------------------------------------------- #
# eval: Mix factor below zero / above one (default clamped vs unclamped)
# --------------------------------------------------------------------------- #
def _run_mix_factor(factor, unclamp):
    r = _renderer()
    make_solid_input(r, "mf_img", (0.5, 0.5, 0.5))
    r.create_program_texture("mf_tex", "UV")
    r.program_texture_add_input("mf_tex", "mf_img")
    # slot0 = dummy tex; slot1 = factor; slot2 = black; slot3 = white
    consts = [factor, factor, factor, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0]
    imm = C.SVM_MIX_UNCLAMP_FACTOR if unclamp else 0
    code = flat([
        instr(OP_LOAD_TEX, out=0, imm=0),
        instr(OP_LOAD_CONST, out=1, imm=0),
        instr(OP_LOAD_CONST, out=2, imm=1),
        instr(OP_LOAD_CONST, out=3, imm=2),
        instr(OP_MIX, out=4, a=1, b=2, c=3, imm=imm),
    ])
    r.set_program_texture_program("mf_tex", 1, 4, code, consts, [])
    return r.sample_named_texture("mf_tex", 0.5, 0.5)


def test_eval_mix_factor_below_zero_and_above_one():
    # default (clamped): factor -0.5 -> 0 -> black ; 1.5 -> 1 -> white
    assert _run_mix_factor(-0.5, unclamp=False) == pytest.approx([0, 0, 0], abs=1e-6)
    assert _run_mix_factor(1.5, unclamp=False) == pytest.approx([1, 1, 1], abs=1e-6)
    # unclamped: factor passes through -> -0.5 and 1.5
    assert _run_mix_factor(-0.5, unclamp=True) == pytest.approx([-0.5, -0.5, -0.5], abs=1e-6)
    assert _run_mix_factor(1.5, unclamp=True) == pytest.approx([1.5, 1.5, 1.5], abs=1e-6)


@pytest.mark.parametrize("source_type,expected", [
    ("RGBA", 0.2 * 0.2126729 + 0.6 * 0.7151522 + 0.9 * 0.0721750),
    ("VECTOR", (0.2 + 0.6 + 0.9) / 3),
])
def test_eval_compiled_scalar_conversion(source_type, expected):
    tex = Node('TEX_IMAGE')
    # An identity vector operation makes a real image -> vector -> scalar chain.
    node = tex
    if source_type == 'VECTOR':
        node = Node('VECT_MATH', operation='ADD', inputs=[
            Sock('Vector', link=Link(tex, type='RGBA')),
            Sock('Vector', (0, 0, 0))])
    mix = Node('MIX', data_type='FLOAT', blend_type='ADD', inputs=[
        Sock('Factor', 1.0, type='VALUE'),
        Sock('A', 0.0, type='VALUE'),
        Sock('B', link=Link(node, type=source_type), type='VALUE')])
    compiled = C.compile_chain(Sock('Base Color', link=Link(mix, 'Result', type='VALUE')))
    r = _renderer()
    _load_program(r, 'typed_scalar', compiled, {id(tex): (0.2, 0.6, 0.9)})
    assert r.sample_named_texture('typed_scalar', 0.5, 0.5) == pytest.approx([expected] * 3, abs=1e-6)


@pytest.mark.parametrize('rtype', list(C.VEC_ROTATE_TYPES))
@pytest.mark.parametrize('invert', [False, True])
def test_eval_compiled_rotate(rtype, invert):
    tex = Node('TEX_IMAGE')
    node = Node('VECTOR_ROTATE', rotation_type=rtype, invert=invert, inputs=[
        Sock('Vector', link=Link(tex, type='RGBA')),
        Sock('Center', (0, 0, 0)), Sock('Axis', (0, 0, 1)),
        Sock('Angle', math.pi / 2, type='VALUE'),
        Sock('Rotation', (0, 0, math.pi / 2))])
    compiled = C.compile_chain(Sock('Color', link=Link(node, 'Vector', type='VECTOR')))
    r = _renderer()
    _load_program(r, 'compiled_rotate', compiled, {id(tex): (1, 1, 1)})
    expected = {'X_AXIS': (1, -1, 1), 'Y_AXIS': (1, 1, -1)}.get(rtype, (-1, 1, 1))
    if invert:
        expected = {'X_AXIS': (1, 1, -1), 'Y_AXIS': (-1, 1, 1)}.get(rtype, (1, -1, 1))
    assert r.sample_named_texture('compiled_rotate', 0.5, 0.5) == pytest.approx(expected, abs=1e-6)


def test_eval_vector_power_zero_and_negative_bases():
    r = _renderer()
    assert _run_vec_math(r, 'powerzero', 'POWER', (0, 0, -2), (-1, 0, 3), (0, 0, 0), 1) == pytest.approx([0, 1, -8])
    assert _run_vec_math(r, 'powerneg', 'POWER', (-2, -2, -2), (-2, -3, 0.5), (0, 0, 0), 1) == pytest.approx([0.25, -0.125, 0])


def test_compile_indexable_euler_default():
    class EulerDefault:
        # Blender mathutils.Euler has sequence indexing without __iter__.
        def __getitem__(self, index):
            return (0.1, 0.2, 0.3)[index]

    assert C._socket_default_rgb(Sock('Rotation', EulerDefault())) == [0.1, 0.2, 0.3]

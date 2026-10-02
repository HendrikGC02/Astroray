"""pkg314 — shader-graph IR + dynamic value programs.

IR tests (no engine): CSE, dead-code elimination, last-use slot reuse, budgets,
curve baking, opcode parity with include/astroray/shader_graph.h. Engine tests
(CPU, `astroray` importorskip): old op-VM vs graph program value equivalence,
>32 instructions, >2 textures, repeated consumers, warped image coordinates,
#993 (wood Roughness chain) and #992 (Float / RGB Curves, Cycles semantics).
"""
import math
import os
import re
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "blender_addon"))
import shader_vm_compiler as C  # noqa: E402
import shader_graph_ir as G  # noqa: E402

_HEADER = os.path.join(os.path.dirname(__file__), "..", "include", "astroray",
                       "shader_graph.h")


# ---- duck-typed Blender node model -----------------------------------------
class Sock:
    def __init__(self, name, default=0.0, link=None, type=None):
        self.name = name
        self.type = type
        self.default_value = default
        self._link = link

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
        self._by_name = {}
        for s in socks:
            self._by_name.setdefault(s.name, s)

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


def img(name="img", vector=None):
    return Node('TEX_IMAGE', [Sock('Vector', (0.0, 0.0, 0.0), link=vector)], name=name)


def proc(ntype, name):
    return Node(ntype, [Sock('Vector', (0.0, 0.0, 0.0))], name=name)


def link(node, out="Color", type=None):
    return Link(node, out, type)


def math_node(op, a, b=0.0, c=0.0, clamp=False):
    def s(name, v):
        if isinstance(v, Link):
            return Sock(name, 0.0, link=v, type='VALUE')
        return Sock(name, float(v), type='VALUE')
    return Node('MATH', [s('Value', a), s('Value_001', b), s('Value_002', c)],
                operation=op, use_clamp=clamp)


def out_socket(node, out="Value", type='VALUE'):
    return Sock('Roughness', 0.5, link=Link(node, out, None), type=type)


class Ramp:
    def __init__(self, f):
        self._f = f

    def evaluate(self, x):
        return self._f(x)


def ramp_node(fac_link, f):
    return Node('VALTORGB', [Sock('Fac', 0.5, link=fac_link, type='VALUE')],
                color_ramp=Ramp(f))


# ---- curve mapping mock (Blender CurveMapping API subset) --------------------
class CurvePoint:
    def __init__(self, x, y):
        self.location = (x, y)


class CurveMap:
    def __init__(self, pts):
        self.points = [CurvePoint(x, y) for x, y in pts]

    def eval(self, t):  # piecewise linear, horizontal extension
        p = self.points
        if t <= p[0].location[0]:
            return p[0].location[1]
        if t >= p[-1].location[0]:
            return p[-1].location[1]
        for a, b in zip(p, p[1:]):
            if a.location[0] <= t <= b.location[0]:
                u = (t - a.location[0]) / (b.location[0] - a.location[0])
                return a.location[1] + u * (b.location[1] - a.location[1])
        return p[-1].location[1]


class CurveMapping:
    def __init__(self, curves, extend='HORIZONTAL'):
        self.curves = curves
        self.extend = extend
        self.initialized = False

    def initialize(self):
        self.initialized = True

    def update(self):
        pass

    def evaluate(self, curve, t):
        assert self.initialized
        return curve.eval(t)


def float_curve(value_link, pts, fac=1.0, extend='HORIZONTAL'):
    return Node('CURVE_FLOAT', [Sock('Factor', fac, type='VALUE'),
                                Sock('Value', 0.0, link=value_link, type='VALUE')],
                mapping=CurveMapping([CurveMap(pts)], extend))


def rgb_curve(color_link, r, g, b, c, fac=1.0, extend='HORIZONTAL'):
    return Node('CURVE_RGB', [Sock('Fac', fac, type='VALUE'),
                              Sock('Color', (0.0, 0.0, 0.0), link=color_link, type='RGBA')],
                mapping=CurveMapping([CurveMap(r), CurveMap(g), CurveMap(b), CurveMap(c)],
                                     extend))


def _ops(prog):
    code = prog['code']
    return [code[i] for i in range(0, len(code), 9)]


# =========================================================================== #
# IR: opcode parity with the C++ header
# =========================================================================== #
def test_opcode_and_budget_parity_with_header():
    src = open(_HEADER, encoding="utf-8").read()
    for name, val in (('GOP_TEX_NATIVE', G.OP_TEX_NATIVE), ('GOP_TEX_COORD', G.OP_TEX_COORD),
                      ('GOP_GEOM', G.OP_GEOM), ('GOP_CURVE', G.OP_CURVE)):
        assert re.search(r'\b%s\s*=\s*%d\b' % (name, val), src), name
    for name in ('GRAPH_IR_VERSION', 'GRAPH_MAX_SLOTS', 'GRAPH_MAX_INSTR', 'GRAPH_MAX_CONST',
                 'GRAPH_MAX_TABLES', 'GRAPH_MAX_TABLE_SIZE', 'GRAPH_MAX_TEX'):
        m = re.search(r'constexpr int %s\s*=\s*(\d+)' % name, src)
        assert m and int(m.group(1)) == getattr(G, name), name
    assert re.search(r'CURVE_FLOAT\s*=\s*0\s*,\s*CURVE_RGB\s*=\s*1', src)
    assert re.search(r'GEOM_UV\s*=\s*0', src)


# =========================================================================== #
# IR passes
# =========================================================================== #
def _wood_roughness():
    """#993: Wave rings + Noise -> Math x3 -> Ramp -> Roughness (Object coords +
    Mapping are each texture's own coordinate contract)."""
    wave = proc('TEX_WAVE', 'wave')
    noise = proc('TEX_NOISE', 'noise')
    m1 = math_node('MULTIPLY', link(noise, 'Fac'), 0.35)
    m2 = math_node('ADD', link(wave, 'Fac'), link(m1, 'Value'))
    m3 = math_node('POWER', link(m2, 'Value'), 1.7)
    m4 = math_node('MULTIPLY_ADD', link(m3, 'Value'), 0.6, 0.2, clamp=True)
    r = ramp_node(link(m4, 'Value'), lambda x: (0.2 + 0.6 * x, 0.2 + 0.6 * x, 0.2 + 0.6 * x))
    return out_socket(r, 'Color', 'VALUE'), wave, noise


def test_993_wood_chain_exceeds_opvm_but_compiles_to_graph():
    sock, wave, noise = _wood_roughness()
    with pytest.raises(C.VMCompileError, match="VM_MAX_SLOTS"):
        C.compile_chain(sock, allow_leaf=True)
    prog = G.compile_value_program(sock, allow_leaf=True)
    assert prog is not None
    st = prog['stats']
    assert st['textures'] == 2 and prog['inputs'] == [wave, noise]
    assert prog['input_kinds'] == ['native', 'native']
    assert st['slots'] <= 4, st
    assert st['instr'] < st['instr_pre_opt'] or st['instr'] <= 16


def test_cse_merges_repeated_consumers():
    tex = img('a')
    # Math(Math(t*2), Math(t*2)) with two separately built but identical subtrees.
    s1 = math_node('MULTIPLY', link(tex, 'Color', 'RGBA'), 2.0)
    s2 = math_node('MULTIPLY', link(tex, 'Color', 'RGBA'), 2.0)
    top = math_node('ADD', link(s1, 'Value'), link(s2, 'Value'))
    prog = G.compile_value_program(out_socket(top), allow_leaf=True)
    ops = _ops(prog)
    assert ops.count(G.OP_TEX_NATIVE) == 1
    assert ops.count(C.OP_RGB_TO_BW) == 1
    assert ops.count(C.OP_MATH) == 2          # one MULTIPLY (merged) + the ADD
    assert prog['stats']['instr_pre_opt'] > prog['stats']['instr']


def test_long_chain_reuses_slots_beyond_opvm_bounds():
    tex = img('a')
    node = math_node('MULTIPLY', link(tex, 'Color', 'RGBA'), 1.01)
    for i in range(40):
        node = math_node('ADD' if i % 2 else 'MULTIPLY', link(node, 'Value'), 1.0 + 0.01 * i)
    sock = out_socket(node)
    with pytest.raises(C.VMCompileError):
        C.compile_chain(sock, allow_leaf=True)
    prog = G.compile_value_program(sock, allow_leaf=True)
    assert prog['stats']['instr'] > C.VM_MAX_INSTR
    assert prog['stats']['slots'] <= 3


def test_three_textures_and_dead_code():
    a, b, c = img('a'), img('b'), img('c')
    m1 = Node('MIX_RGB', [Sock('Fac', 0.3, type='VALUE'),
                          Sock('Color1', (0, 0, 0), link=link(a)),
                          Sock('Color2', (0, 0, 0), link=link(b))], blend_type='MIX')
    m2 = Node('MIX_RGB', [Sock('Fac', 0.6, type='VALUE'),
                          Sock('Color1', (0, 0, 0), link=link(m1)),
                          Sock('Color2', (0, 0, 0), link=link(c))], blend_type='MULTIPLY')
    prog = G.compile_value_program(Sock('Base Color', (0, 0, 0), link=link(m2)))
    assert prog['stats']['textures'] == 3
    assert len(prog['inputs']) == 3
    with pytest.raises(C.VMCompileError):
        C.compile_chain(Sock('Base Color', (0, 0, 0), link=link(m2)))


def test_budget_is_checked_not_truncated(monkeypatch):
    tex = img('a')
    node = math_node('MULTIPLY', link(tex, 'Color', 'RGBA'), 1.5)
    for i in range(10):
        node = math_node('ADD', link(node, 'Value'), float(i))
    sock = out_socket(node)
    monkeypatch.setattr(G, 'GRAPH_MAX_INSTR', 5)
    with pytest.raises(C.VMCompileError, match="budget exceeded: instructions"):
        G.compile_value_program(sock, allow_leaf=True)


def test_slot_allocation_is_valid_ssa_replay():
    """Replay the allocated program on a symbolic machine: every operand read must
    see the value the SSA program meant (no slot clobbered before its last use)."""
    sock, _, _ = _wood_roughness()
    b = G.IRBuilder()
    out = C.compile_socket(sock, b, 0)
    instrs, out = G._cse_dce(b.instrs, out)
    ssa = [(i.dst, [getattr(i, f) for f in G.operand_fields(i.op, i.sub)]) for i in instrs]
    alloc, out_slot, peak = G.allocate(instrs, out)
    slots = {}
    for (dst, reads), ins in zip(ssa, alloc):
        got = [slots.get(getattr(ins, f)) for f in G.operand_fields(ins.op, ins.sub)]
        assert got == reads
        slots[ins.dst] = dst
    assert slots[out_slot] == out
    assert peak == max(i.dst for i in alloc) + 1


def test_warped_image_coordinate_compiles_into_program():
    tc = Node('TEX_COORD', [])
    warp = Node('VECT_MATH', [Sock('Vector', (0, 0, 0), link=Link(tc, 'UV', 'VECTOR')),
                              Sock('Vector_001', (0, 0, 0)), Sock('Vector_002', (0, 0, 0)),
                              Sock('Scale', 1.0)], operation='SINE')
    image = img('warped', vector=Link(warp, 'Vector', 'VECTOR'))
    plain = img('plain')
    mix = Node('MIX_RGB', [Sock('Fac', 0.5, type='VALUE'),
                           Sock('Color1', (0, 0, 0), link=link(image)),
                           Sock('Color2', (0, 0, 0), link=link(plain))], blend_type='MIX')
    prog = G.compile_value_program(Sock('Base Color', (0, 0, 0), link=link(mix)))
    ops = _ops(prog)
    assert G.OP_GEOM in ops and G.OP_TEX_COORD in ops and G.OP_TEX_NATIVE in ops
    assert prog['input_kinds'] == ['coord', 'native']


def test_non_uv_coordinate_source_in_warp_is_reported():
    tc = Node('TEX_COORD', [])
    warp = Node('VECT_MATH', [Sock('Vector', (0, 0, 0), link=Link(tc, 'Object', 'VECTOR')),
                              Sock('Vector_001', (0, 0, 0)), Sock('Vector_002', (0, 0, 0)),
                              Sock('Scale', 1.0)], operation='SINE')
    image = img('warped', vector=Link(warp, 'Vector', 'VECTOR'))
    with pytest.raises(C.VMCompileError, match="only UV"):
        G.compile_value_program(Sock('Base Color', (0, 0, 0), link=link(image)),
                                allow_leaf=True)


# =========================================================================== #
# #992 curve baking (Cycles curvemapping_*_to_array)
# =========================================================================== #
def test_float_curve_table_matches_cycles_bake():
    tex = img('a')
    pts = [(0.1, 0.0), (0.5, 0.8), (0.9, 1.0)]
    node = float_curve(link(tex, 'Color', 'RGBA'), pts, extend='EXTRAPOLATED')
    prog = G.compile_value_program(out_socket(node), allow_leaf=True)
    size, min_x, range_x, ex = prog['tables'][0]
    assert size == 257 and ex == 1
    assert min_x == pytest.approx(0.1) and range_x == pytest.approx(0.8)
    data = prog['table_data']
    cm = CurveMap(pts)
    for i in (0, 64, 128, 200, 256):
        t = 0.1 + i / 256.0 * 0.8
        assert data[3 * i] == pytest.approx(cm.eval(t))
    assert C.VMCompileError  # op-VM path rejects curves with the historical message
    with pytest.raises(C.VMCompileError, match="unsupported node type in op-VM chain: CURVE_FLOAT"):
        C.compile_chain(out_socket(node), allow_leaf=True)


def test_rgb_curve_composes_combined_curve():
    tex = img('a')
    r = [(0.0, 0.0), (1.0, 0.5)]
    g = [(0.0, 0.0), (1.0, 1.0)]
    b = [(0.0, 1.0), (1.0, 0.0)]
    c = [(0.0, 0.2), (1.0, 0.8)]
    node = rgb_curve(link(tex), r, g, b, c)
    prog = G.compile_value_program(Sock('Base Color', (0, 0, 0), link=link(node)),
                                   allow_leaf=True)
    data = prog['table_data']
    t = 0.5
    ct = CurveMap(c).eval(t)
    assert data[3 * 128 + 0] == pytest.approx(CurveMap(r).eval(ct))
    assert data[3 * 128 + 2] == pytest.approx(CurveMap(b).eval(ct))


# =========================================================================== #
# Engine (CPU) — values
# =========================================================================== #
def _renderer():
    return pytest.importorskip("astroray").Renderer()


def _solid(r, name, rgb):
    import numpy as np
    r.load_texture(name, np.array(rgb, dtype="float32").ravel(), 1, 1, "UV")


def _gradient(r, name, w=8, h=8):
    import numpy as np
    px = []
    for j in range(h):
        for i in range(w):
            px.append(((i + 0.5) / w, (j + 0.5) / h, 0.25))
    r.load_texture(name, np.array(px, dtype="float32").ravel(), w, h, "UV")


def _load_graph(r, name, prog, names):
    tables = [v for t in prog['tables'] for v in t]
    r.create_graph_program_texture(
        name, prog['version'], prog['num_slots'], prog['out_slot'], prog['code'],
        prog['consts'], tables, prog['table_data'],
        [names[id(n)] for n in prog['inputs']],
        [1 if k == 'coord' else 0 for k in prog['input_kinds']])


def _load_opvm(r, name, compiled, names):
    r.create_program_texture(name, "UV")
    for n in compiled['inputs']:
        r.program_texture_add_input(name, names[id(n)])
    r.set_program_texture_program(name, compiled['num_tex'], compiled['out_slot'],
                                  compiled['code_flat'], compiled['consts_flat'],
                                  compiled['ramps_flat'])


def _equivalence_chains():
    """Chains the op-VM represents (one image input), covering every op family."""
    chains = []
    t = img('t')
    chains.append(('math_clamp', math_node('MULTIPLY_ADD', link(t, 'Color', 'RGBA'), 1.7, -0.2,
                                           clamp=True), 'Value', 'VALUE', t))
    chains.append(('ramp', ramp_node(link(t, 'Color', 'RGBA'),
                                     lambda x: (x * x, 1 - x, 0.5 * x)), 'Color', 'RGBA', t))
    hsv = Node('HUE_SAT', [Sock('Hue', 0.3, type='VALUE'), Sock('Saturation', 1.4, type='VALUE'),
                           Sock('Value', 0.9, type='VALUE'), Sock('Fac', 0.8, type='VALUE'),
                           Sock('Color', (0, 0, 0), link=link(t))])
    chains.append(('hsv', hsv, 'Color', 'RGBA', t))
    mr = Node('MAP_RANGE', [Sock('Value', 0.0, link=link(t, 'Color', 'RGBA'), type='VALUE'),
                            Sock('From Min', 0.1, type='VALUE'), Sock('From Max', 0.9, type='VALUE'),
                            Sock('To Min', 0.2, type='VALUE'), Sock('To Max', 0.7, type='VALUE')],
              interpolation_type='SMOOTHERSTEP')
    chains.append(('map_range', mr, 'Result', 'VALUE', t))
    vm = Node('VECT_MATH', [Sock('Vector', (0, 0, 0), link=link(t)),
                            Sock('Vector_001', (0.3, -0.2, 0.9)), Sock('Vector_002', (0, 0, 0)),
                            Sock('Scale', 1.0)], operation='CROSS_PRODUCT')
    chains.append(('vec_cross', vm, 'Vector', 'VECTOR', t))
    sep = Node('SEPARATE_COLOR', [Sock('Color', (0, 0, 0), link=link(t))], mode='HSV')
    chains.append(('sep_hsv', sep, 'Green', 'VALUE', t))
    return chains


@pytest.mark.parametrize("which", range(6))
def test_opvm_vs_graph_cpu_equivalence(which):
    r = _renderer()
    name, node, out_name, stype, tex = _equivalence_chains()[which]
    _gradient(r, "grad")
    names = {id(tex): "grad"}
    sock = Sock('S', 0.0, link=Link(node, out_name, None), type=stype)
    legacy = C.compile_chain(sock, allow_leaf=True)
    graph = G.compile_value_program(sock, allow_leaf=True)
    assert legacy is not None and graph is not None
    _load_opvm(r, "old_" + name, legacy, names)
    _load_graph(r, "new_" + name, graph, names)
    for u in (0.05, 0.3, 0.55, 0.8, 0.97):
        for v in (0.1, 0.45, 0.9):
            a = r.sample_named_texture("old_" + name, u, v)
            b = r.sample_named_texture("new_" + name, u, v)
            assert b == pytest.approx(a, abs=1e-6), (name, u, v)


def _math_ref(op, a, b, c):
    return {'ADD': a + b, 'MULTIPLY': a * b, 'POWER': a ** b if a >= 0 else 0.0,
            'MULTIPLY_ADD': a * b + c}[op]


def test_993_chain_cpu_value_matches_reference():
    r = _renderer()
    sock, wave, noise = _wood_roughness()
    _solid(r, "wave", (0.6, 0.6, 0.6))
    _solid(r, "noise", (0.3, 0.1, 0.9))   # Noise Fac = Color.x
    prog = G.compile_value_program(sock, allow_leaf=True)
    _load_graph(r, "wood", prog, {id(wave): "wave", id(noise): "noise"})
    m1 = 0.3 * 0.35
    m2 = 0.6 + m1
    m3 = m2 ** 1.7
    m4 = min(max(m3 * 0.6 + 0.2, 0.0), 1.0)
    want = 0.2 + 0.6 * m4
    got = r.sample_named_texture("wood", 0.5, 0.5)
    assert got[0] == pytest.approx(want, abs=2e-3)   # 256-entry ramp interpolation


def test_long_chain_cpu_value():
    r = _renderer()
    tex = img('a')
    node = math_node('MULTIPLY', link(tex, 'Color', 'RGBA'), 1.01)
    want_ops = [('MULTIPLY', 1.01)]
    for i in range(40):
        op = 'ADD' if i % 2 else 'MULTIPLY'
        node = math_node(op, link(node, 'Value'), 1.0 + 0.01 * i)
        want_ops.append((op, 1.0 + 0.01 * i))
    _solid(r, "a", (0.5, 0.5, 0.5))
    prog = G.compile_value_program(out_socket(node), allow_leaf=True)
    _load_graph(r, "long", prog, {id(tex): "a"})
    v = 0.2126729 * 0.5 + 0.7151522 * 0.5 + 0.0721750 * 0.5
    for op, k in want_ops:
        v = v * k if op == 'MULTIPLY' else v + k
    assert r.sample_named_texture("long", 0.5, 0.5)[0] == pytest.approx(v, rel=1e-5)


def test_three_texture_cpu_value():
    r = _renderer()
    a, b, c = img('a'), img('b'), img('c')
    m1 = Node('MIX_RGB', [Sock('Fac', 0.3, type='VALUE'),
                          Sock('Color1', (0, 0, 0), link=link(a)),
                          Sock('Color2', (0, 0, 0), link=link(b))], blend_type='MIX')
    m2 = Node('MIX_RGB', [Sock('Fac', 0.6, type='VALUE'),
                          Sock('Color1', (0, 0, 0), link=link(m1)),
                          Sock('Color2', (0, 0, 0), link=link(c))], blend_type='MULTIPLY')
    prog = G.compile_value_program(Sock('Base Color', (0, 0, 0), link=link(m2)))
    cols = {'a': (0.9, 0.1, 0.2), 'b': (0.1, 0.8, 0.3), 'c': (0.5, 0.25, 1.0)}
    for k, v in cols.items():
        _solid(r, k, v)
    _load_graph(r, "three", prog, {id(a): 'a', id(b): 'b', id(c): 'c'})
    got = r.sample_named_texture("three", 0.5, 0.5)
    for i in range(3):
        m = cols['a'][i] * 0.7 + cols['b'][i] * 0.3
        want = m * (0.4 + cols['c'][i] * 0.6)
        assert got[i] == pytest.approx(want, abs=1e-6)


def test_warped_image_coordinate_cpu_value():
    r = _renderer()
    tc = Node('TEX_COORD', [])
    scale = Node('VECT_MATH', [Sock('Vector', (0, 0, 0), link=Link(tc, 'UV', 'VECTOR')),
                               Sock('Vector_001', (0, 0, 0)), Sock('Vector_002', (0, 0, 0)),
                               Sock('Scale', 1.0)], operation='SINE')
    image = img('warped', vector=Link(scale, 'Vector', 'VECTOR'))
    _gradient(r, "grad")
    prog = G.compile_value_program(Sock('Base Color', (0, 0, 0), link=link(image)),
                                   allow_leaf=True)
    _load_graph(r, "warp", prog, {id(image): "grad"})
    for u, v in ((0.2, 0.3), (0.7, 0.9)):
        got = r.sample_named_texture("warp", u, v)
        want = r.sample_named_texture("grad", math.sin(u), math.sin(v))
        assert got == pytest.approx(want, abs=1e-6)


def _cycles_lookup(table, f, extrapolate):
    n = len(table)
    if extrapolate and (f < 0.0 or f > 1.0):
        if f < 0.0:
            t0, dy, f = table[0], table[0] - table[1], -f
        else:
            t0, dy, f = table[-1], table[-1] - table[-2], f - 1.0
        return t0 + dy * f * (n - 1)
    f = min(max(f, 0.0), 1.0) * (n - 1)
    i = min(max(int(f), 0), n - 1)
    t = f - i
    a = table[i]
    if t > 0.0:
        a = (1 - t) * a + t * table[i + 1]
    return a


@pytest.mark.parametrize("extend", ['HORIZONTAL', 'EXTRAPOLATED'])
def test_992_float_curve_cpu_matches_cycles(extend):
    r = _renderer()
    tex = img('a')
    pts = [(0.1, 0.0), (0.5, 0.8), (0.9, 1.0)]
    fac = 0.75
    node = float_curve(link(tex, 'Color', 'RGBA'), pts, fac=fac, extend=extend)
    prog = G.compile_value_program(out_socket(node), allow_leaf=True)
    table = prog['table_data'][0::3]
    for x in (0.02, 0.33, 0.95):
        _solid(r, "v%.2f" % x, (x, x, x))
        _load_graph(r, "fc%.2f" % x, prog, {id(tex): "v%.2f" % x})
        lum = x * (0.2126729 + 0.7151522 + 0.0721750)
        v = _cycles_lookup(table, (lum - 0.1) / 0.8, extend == 'EXTRAPOLATED')
        want = (1 - fac) * lum + fac * v
        assert r.sample_named_texture("fc%.2f" % x, 0.5, 0.5)[0] == pytest.approx(want, abs=1e-5)


def test_992_rgb_curve_cpu_matches_cycles():
    r = _renderer()
    tex = img('a')
    rr = [(0.0, 0.0), (1.0, 0.5)]
    gg = [(0.0, 0.0), (0.5, 0.9), (1.0, 1.0)]
    bb = [(0.0, 1.0), (1.0, 0.0)]
    cc = [(0.0, 0.2), (1.0, 0.8)]
    node = rgb_curve(link(tex), rr, gg, bb, cc, fac=0.6)
    prog = G.compile_value_program(Sock('Base Color', (0, 0, 0), link=link(node)),
                                   allow_leaf=True)
    col = (0.15, 0.55, 0.95)
    _solid(r, "c", col)
    _load_graph(r, "rgbc", prog, {id(tex): "c"})
    data = prog['table_data']
    got = r.sample_named_texture("rgbc", 0.5, 0.5)
    for k in range(3):
        table = data[k::3]
        v = _cycles_lookup(table, col[k], False)
        assert got[k] == pytest.approx(0.4 * col[k] + 0.6 * v, abs=1e-5)


def test_malformed_or_mismatched_program_is_rejected():
    r = _renderer()
    _solid(r, "a", (0.5, 0.5, 0.5))
    tex = img('a')
    prog = G.compile_value_program(out_socket(math_node('ADD', link(tex, 'Color', 'RGBA'), 1.0)),
                                   allow_leaf=True)
    names = {id(tex): "a"}
    bad = dict(prog, version=prog['version'] + 1)
    with pytest.raises(Exception, match="IR version"):
        _load_graph(r, "bad_ver", bad, names)
    bad = dict(prog, num_slots=1, out_slot=3)
    with pytest.raises(Exception, match="rejected"):
        _load_graph(r, "bad_slot", bad, names)
    code = list(prog['code'])
    code[0] = 99
    with pytest.raises(Exception, match="unknown opcode"):
        _load_graph(r, "bad_op", dict(prog, code=code), names)


# =========================================================================== #
# GPU (RTX box): dedicated graph-evaluation kernel vs CPU, and op-VM vs graph
# program on the GPU. Independent RNG streams CPU vs GPU -> per-ROI mean ratio.
# =========================================================================== #
_W, _H = 96, 64


def _has_gpu(r):
    import astroray
    return bool(astroray.__features__.get("cuda", False)) and bool(getattr(r, "gpu_available", False))


def _quad_uv(r, mat):
    A, B, C, D = [-1.5, -1, 0], [1.5, -1, 0], [1.5, 1, 0], [-1.5, 1, 0]
    n = [0, 0, 1]
    r.add_triangle_layers(A, B, C, mat, {"UVMap": [[0, 0], [1, 0], [1, 1]]}, n, n, n)
    r.add_triangle_layers(A, C, D, mat, {"UVMap": [[0, 0], [1, 1], [0, 1]]}, n, n, n)


def _render_scene(build, use_gpu, samples=128):
    from base_helpers import create_renderer, render_image, setup_camera
    r = create_renderer()
    if use_gpu:
        if not _has_gpu(r):
            pytest.skip("no CUDA GPU (RTX-box leg)")
        r.set_use_gpu(True)
    r.set_seed(7)
    r.set_background_color([0.6, 0.6, 0.6])
    build(r)
    setup_camera(r, look_from=[0, 0, 3.2], look_at=[0, 0, 0], vup=[0, 1, 0], vfov=40,
                 width=_W, height=_H)
    return render_image(r, samples=samples, max_depth=3, apply_gamma=False)


def _rois(img):
    H, W = img.shape[:2]
    out = []
    for ya, yb in ((0.25, 0.45), (0.55, 0.75)):
        for xa, xb in ((0.2, 0.35), (0.42, 0.58), (0.65, 0.8)):
            out.append(img[int(ya * H):int(yb * H), int(xa * W):int(xb * W)].reshape(-1, 3).mean(0))
    return __import__('numpy').array(out)


def _assert_rois(a, b, tol, label):
    import numpy as np
    ra, rb = _rois(a), _rois(b)
    ratio = ra / np.maximum(rb, 1e-4)
    assert np.allclose(ratio, 1.0, atol=tol), "%s\n%s\na=%s\nb=%s" % (label, ratio, ra, rb)


def _ramp_chain():
    t = img('t')
    node = ramp_node(link(t, 'Color', 'RGBA'), lambda x: (x, 0.2 + 0.6 * x * x, 1.0 - x))
    return Sock('Base Color', (0, 0, 0), link=Link(node, 'Color', None), type='RGBA'), t


def _build_lambertian(kind):
    def build(r):
        sock, t = _ramp_chain()
        _gradient(r, "grad")
        if kind == 'opvm':
            _load_opvm(r, "bc", C.compile_chain(sock, allow_leaf=True), {id(t): "grad"})
        else:
            _load_graph(r, "bc", G.compile_value_program(sock, allow_leaf=True), {id(t): "grad"})
        mat = r.create_material("lambertian", [1.0, 1.0, 1.0], {"texture": "bc"})
        _quad_uv(r, mat)
    return build


def test_gpu_opvm_vs_graph_lambertian_base_colour():
    """Old-vs-new on the GPU: the same Color Ramp chain as an op-VM program and
    as a graph program (dedicated kernel) render the same image (same seed)."""
    old = _render_scene(_build_lambertian('opvm'), True)
    new = _render_scene(_build_lambertian('graph'), True)
    _assert_rois(new, old, 0.01, "GPU graph vs GPU op-VM")


def test_gpu_vs_cpu_graph_lambertian_base_colour():
    cpu = _render_scene(_build_lambertian('graph'), False)
    gpu = _render_scene(_build_lambertian('graph'), True)
    _assert_rois(gpu, cpu, 0.03, "graph GPU vs CPU")


def _three_tex_metallic_curve(r):
    """Principled: Metallic from 3 images (op-VM cannot: VM_MAX_TEX) and a base
    colour through RGB Curves (#992) — both graph programs."""
    a, b, c = img('a'), img('b'), img('c')
    m1 = Node('MIX_RGB', [Sock('Fac', 0.3, type='VALUE'),
                          Sock('Color1', (0, 0, 0), link=link(a)),
                          Sock('Color2', (0, 0, 0), link=link(b))], blend_type='MIX')
    m2 = Node('MIX_RGB', [Sock('Fac', 0.0, link=link(c, 'Color', 'RGBA'), type='VALUE'),
                          Sock('Color1', (0, 0, 0), link=link(m1)),
                          Sock('Color2', (1, 1, 1))], blend_type='MIX')
    met = G.compile_value_program(Sock('Metallic', 0.0, link=Link(m2, 'Color', 'RGBA'),
                                       type='VALUE'), allow_leaf=True)
    _gradient(r, "ga")
    _solid(r, "sb", (0.9, 0.9, 0.9))
    _gradient(r, "gc", 4, 2)
    _load_graph(r, "met", met, {id(a): "ga", id(b): "sb", id(c): "gc"})
    t = img('t')
    curve = rgb_curve(link(t), [(0, 0.1), (1, 0.9)], [(0, 0), (0.5, 0.8), (1, 1)],
                      [(0, 1), (1, 0)], [(0, 0.2), (1, 0.8)], fac=0.8)
    bc = G.compile_value_program(Sock('Base Color', (0, 0, 0), link=link(curve)),
                                 allow_leaf=True)
    _load_graph(r, "bcc", bc, {id(t): "ga"})
    mat = r.create_material("principled", [0.8, 0.8, 0.8],
                            {"metallic_program": "met", "base_color_texture": "bcc",
                             "roughness": 0.4})
    _quad_uv(r, mat)


def test_gpu_vs_cpu_graph_principled_three_textures_and_curves():
    cpu = _render_scene(_three_tex_metallic_curve, False)
    gpu = _render_scene(_three_tex_metallic_curve, True)
    _assert_rois(gpu, cpu, 0.03, "principled graph programs GPU vs CPU")


def _warped(r):
    tc = Node('TEX_COORD', [])
    warp = Node('VECT_MATH', [Sock('Vector', (0, 0, 0), link=Link(tc, 'UV', 'VECTOR')),
                              Sock('Vector_001', (2.0, 1.0, 1.0)), Sock('Vector_002', (0, 0, 0)),
                              Sock('Scale', 1.0)], operation='MULTIPLY')
    sinw = Node('VECT_MATH', [Sock('Vector', (0, 0, 0), link=Link(warp, 'Vector', 'VECTOR')),
                              Sock('Vector_001', (0, 0, 0)), Sock('Vector_002', (0, 0, 0)),
                              Sock('Scale', 1.0)], operation='SINE')
    image = img('w', vector=Link(sinw, 'Vector', 'VECTOR'))
    p = G.compile_value_program(Sock('Base Color', (0, 0, 0), link=link(image)), allow_leaf=True)
    assert p['input_kinds'] == ['coord']
    _gradient(r, "gw")
    _load_graph(r, "warp", p, {id(image): "gw"})
    mat = r.create_material("lambertian", [1.0, 1.0, 1.0], {"texture": "warp"})
    _quad_uv(r, mat)


def test_gpu_vs_cpu_graph_warped_image_coordinate():
    cpu = _render_scene(_warped, False)
    gpu = _render_scene(_warped, True)
    _assert_rois(gpu, cpu, 0.03, "computed-uv image GPU vs CPU")


# =========================================================================== #
# Shading context = Cycles sd->N (pre-bump). Layer Weight / Fresnel with an
# unlinked Normal read sd->N, which a Bump node does not change (Cycles 5.2 probe:
# ortho top view of a bumped plane with Base Color = Layer Weight.Facing renders
# flat 0). A lambertian under a uniform white world has radiance = albedo, so a
# per-hit Facing program must render the SAME with and without a bump map.
# =========================================================================== #
def _facing_scene(kind, bump):
    def build(r):
        import numpy as np
        lw = Node('LAYER_WEIGHT', [Sock('Blend', 0.5, type='VALUE'), Sock('Normal', (0, 0, 0))])
        sock = Sock('Color', (0, 0, 0), link=Link(lw, 'Facing', 'VALUE'), type='RGBA')
        if kind == 'opvm':
            c = C.compile_chain(sock)
            r.create_program_texture("lwp", "UV")
            r.set_program_texture_program("lwp", 0, c['out_slot'], c['code_flat'],
                                          c['consts_flat'], c['ramps_flat'])
        else:
            _load_graph(r, "lwp", G.compile_value_program(sock), {})
        params = {"texture": "lwp"}
        if bump:
            px = [(1.0 if (i // 4) % 2 else 0.0,) * 3 for j in range(32) for i in range(32)]
            r.load_texture("stripes", np.array(px, dtype="float32").ravel(), 32, 32, "UV")
            params.update({"bump_map_texture": "stripes", "bump_strength": 1.0,
                           "bump_distance": 0.3})
        mat = r.create_material("lambertian", [1.0, 1.0, 1.0], params)
        _quad_uv(r, mat)
    return build


@pytest.mark.parametrize("kind,use_gpu", [
    ('opvm', False), ('graph', False), ('graph', True),
    pytest.param('opvm', True, marks=pytest.mark.xfail(
        strict=True, reason="#1031: GPU lambertian skips a texture-less op-VM program"))])
def test_shading_context_normal_ignores_bump(kind, use_gpu):
    import numpy as np
    flat = _render_scene(_facing_scene(kind, False), use_gpu, samples=32)
    bumped = _render_scene(_facing_scene(kind, True), use_gpu, samples=32)
    assert np.allclose(_rois(bumped), _rois(flat), atol=0.01), (_rois(bumped), _rois(flat))
    # Non-vacuous: the per-hit Facing value is applied (CPU reference; the GPU must
    # match it, which also catches a backend that ignores the program).
    cpu = flat if not use_gpu else _render_scene(_facing_scene(kind, False), False, samples=32)
    assert np.allclose(_rois(flat), _rois(cpu), atol=0.01), (_rois(flat), _rois(cpu))
    assert _rois(cpu).max() - _rois(cpu).min() > 0.01   # facing varies off-centre


# =========================================================================== #
# Validator dataflow (Terra review): def-before-use, decoder parity with the IR.
# =========================================================================== #
def _raw_program(code, num_slots, out_slot, consts=((0.5, 0.5, 0.5),), tables=()):
    return {'version': G.GRAPH_IR_VERSION, 'num_slots': num_slots, 'out_slot': out_slot,
            'code': code, 'consts': [v for c in consts for v in c],
            'tables': [list(t) for t in tables],
            'table_data': [0.0, 0.0, 0.0, 1.0, 1.0, 1.0] * len(tables),
            'inputs': [], 'input_kinds': []}


def test_validator_rejects_undefined_reads_and_empty_programs():
    r = _renderer()
    with pytest.raises(Exception, match="empty program"):
        _load_graph(r, "e", _raw_program([], 1, 0), {})
    # MATH ADD reading slot 1 that nothing wrote
    code = [C.OP_LOAD_CONST, 0, 0, 0, 0, 0, 0, 0, 0,
            C.OP_MATH, 0, 2, 0, 1, 0, 0, 0, 0]
    with pytest.raises(Exception, match="undefined slot"):
        _load_graph(r, "u", _raw_program(code, 3, 2), {})
    with pytest.raises(Exception, match="never written"):
        _load_graph(r, "o", _raw_program(code[:9], 3, 2), {})


def _all_op_subs():
    out = [(C.OP_MATH, s | f) for s in C.MATH_OPS.values() for f in (0, C.SVM_MATH_CLAMP)]
    out += [(C.OP_VEC_MATH, s) for s in C.VEC_MATH_OPS.values()]
    out += [(C.OP_VEC_ROTATE, t | inv) for t in C.VEC_ROTATE_TYPES.values() for inv in (0, 8)]
    out += [(C.OP_SHADING, s) for s in range(4)]
    out += [(op, 0) for op in (C.OP_MIX, C.OP_CLAMP, C.OP_BRIGHT_CONTRAST, C.OP_COMBINE_COLOR,
                               C.OP_MAP_RANGE, C.OP_HSV, C.OP_INVERT, C.OP_GAMMA, C.OP_SEP_COLOR,
                               C.OP_RGB_TO_BW, C.OP_RAMP, G.OP_CURVE)]
    return out


def test_validator_reads_match_ir_operand_fields():
    """The engine accepts a program that defines exactly the fields the IR says an
    op reads (C++ graphOperandReads is a subset of operand_fields) and rejects it
    when one of them is missing (not a strict subset)."""
    r = _renderer()
    slot = {'a': 1, 'b': 2, 'c': 3, 'd': 4, 'e': 5}
    for n, (op, sub) in enumerate(_all_op_subs()):
        fields = G.operand_fields(op, sub)
        tables = [(2, 0.0, 1.0, 0)] if op in (C.OP_RAMP, G.OP_CURVE) else []
        prelude = []
        for f in fields:
            prelude += [C.OP_LOAD_CONST, 0, slot[f], 0, 0, 0, 0, 0, 0]
        ins = [op, sub, 0, 1, 2, 3, 4, 5, 0]
        _load_graph(r, "ok%d" % n, _raw_program(prelude + ins, 6, 0, tables=tables), {})
        if fields:
            with pytest.raises(Exception, match="undefined slot"):
                _load_graph(r, "bad%d" % n, _raw_program(prelude[9:] + ins, 6, 0,
                                                         tables=tables), {})

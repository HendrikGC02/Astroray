"""pkg230 — op-VM Clamp opcode + Math/Mix clamp-flag tests (no bpy required).

Builds duck-typed Blender node chains for the pkg230 utility features (a Clamp
node, and the use_clamp / clamp_factor / clamp_result flags on Math/Mix),
compiles them with shader_vm_compiler, loads the bytecode into the engine, and
verifies the rendered per-texel result via sample_named_texture — which runs the
SAME shared HD svm_eval the GPU shade kernel uses. Also asserts addon<->engine
enum/flag parity against include/astroray/shader_vm.h.
"""
import os
import re
import sys

import pytest

astroray = pytest.importorskip("astroray")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "blender_addon"))
import shader_vm_compiler as C

_HEADER = os.path.join(os.path.dirname(__file__), "..", "include", "astroray",
                       "shader_vm.h")


# ---- minimal duck-typed Blender node model (shared with pkg219c tests) ------
class Sock:
    def __init__(self, name, default=0.0, link=None):
        self.name = name
        self.default_value = default
        self._link = link

    @property
    def is_linked(self):
        return self._link is not None

    @property
    def links(self):
        return [self._link] if self._link else []


class Link:
    def __init__(self, from_node, from_socket_name="Color"):
        self.from_node = from_node
        self.from_socket = type("S", (), {"name": from_socket_name})()


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


def _render(name, compiled, tex, color):
    r = astroray.Renderer()
    _load_program(r, name, compiled, {id(tex): color})
    return r.sample_named_texture(name, 0.5, 0.5)


# --------------------------------------------------------------------------- #
# 1. Clamp node, MINMAX: value above max is clamped down
# --------------------------------------------------------------------------- #
def test_clamp_minmax():
    tex = Node('TEX_IMAGE')
    clamp = Node('CLAMP', clamp_type='MINMAX',
                 inputs=[Sock('Value', 0.0, Link(tex, 'Color')),
                         Sock('Min', 0.2), Sock('Max', 0.7)])
    base = Sock('Roughness', 0.5, Link(clamp, 'Result'))
    compiled = C.compile_chain(base)
    assert compiled is not None
    got = _render("clamp_mm", compiled, tex, (0.9, 0.5, 0.1))  # R=0.9 -> 0.7
    assert got == pytest.approx([0.7, 0.7, 0.7], abs=3e-3), got


# --------------------------------------------------------------------------- #
# 2. Clamp MINMAX vs RANGE differ when min > max (RANGE is order-agnostic)
# --------------------------------------------------------------------------- #
def test_clamp_range_order_agnostic():
    # value 0.5, min=0.7, max=0.2
    for ctype, want in (('MINMAX', 0.2), ('RANGE', 0.5)):
        tex = Node('TEX_IMAGE')
        clamp = Node('CLAMP', clamp_type=ctype,
                     inputs=[Sock('Value', 0.0, Link(tex, 'Color')),
                             Sock('Min', 0.7), Sock('Max', 0.2)])
        base = Sock('Roughness', 0.5, Link(clamp, 'Result'))
        compiled = C.compile_chain(base)
        got = _render(f"clamp_{ctype}", compiled, tex, (0.5, 0.5, 0.5))
        assert got == pytest.approx([want, want, want], abs=3e-3), (ctype, got)


# --------------------------------------------------------------------------- #
# 3. Math use_clamp: result clamped to [0,1]
# --------------------------------------------------------------------------- #
def test_math_use_clamp():
    def build(use_clamp):
        tex = Node('TEX_IMAGE')
        m = Node('MATH', operation='ADD', use_clamp=use_clamp,
                 inputs=[Sock('A', 0.0, Link(tex, 'Color')), Sock('B', 0.8)])
        base = Sock('Roughness', 0.5, Link(m, 'Value'))
        return tex, C.compile_chain(base)

    tex, comp = build(True)
    got = _render("math_clamp_on", comp, tex, (0.5, 0.5, 0.5))  # 1.3 -> 1.0
    assert got == pytest.approx([1.0, 1.0, 1.0], abs=3e-3), got

    tex, comp = build(False)
    got = _render("math_clamp_off", comp, tex, (0.5, 0.5, 0.5))  # 1.3, no clamp
    assert got == pytest.approx([1.3, 1.3, 1.3], abs=3e-3), got


# --------------------------------------------------------------------------- #
# 4. Mix clamp_result (legacy MixRGB use_clamp): output clamped to [0,1]
# --------------------------------------------------------------------------- #
def test_mix_clamp_result():
    def build(clamp):
        tex = Node('TEX_IMAGE')
        mix = Node('MIX_RGB', blend_type='ADD', use_clamp=clamp,
                   inputs=[Sock('Fac', 1.0),
                           Sock('Color1', [0, 0, 0], Link(tex, 'Color')),
                           Sock('Color2', [0.6, 0.6, 0.6])])
        base = Sock('Base Color', [0.5, 0.5, 0.5], Link(mix, 'Color'))
        return tex, C.compile_chain(base)

    tex, comp = build(True)
    got = _render("mix_clamp_on", comp, tex, (0.7, 0.7, 0.7))  # 0.7+0.6=1.3 -> 1.0
    assert got == pytest.approx([1.0, 1.0, 1.0], abs=3e-3), got

    tex, comp = build(False)
    got = _render("mix_clamp_off", comp, tex, (0.7, 0.7, 0.7))  # 1.3
    assert got == pytest.approx([1.3, 1.3, 1.3], abs=3e-3), got


# --------------------------------------------------------------------------- #
# 5. Mix factor is saturated by DEFAULT (modern Mix clamp_factor=True, and legacy
#    MixRGB always). Unclamped factors (modern clamp_factor=False -> the
#    SVM_MIX_UNCLAMP_FACTOR bit, pkg230 Phase 2) are covered in
#    tests/test_pkg230_opvm_vectors.py.
# --------------------------------------------------------------------------- #
def test_mix_factor_default_clamped():
    tex = Node('TEX_IMAGE')
    mix = Node('MIX', blend_type='MIX',
               inputs=[Sock('Factor', 0.0, Link(tex, 'Color')),
                       Sock('A', [0.0, 0.0, 0.0]),
                       Sock('B', [1.0, 1.0, 1.0])])
    base = Sock('Base Color', [0.5, 0.5, 0.5], Link(mix, 'Result'))
    comp = C.compile_chain(base)
    got = _render("mix_fac_sat", comp, tex, (1.5, 1.5, 1.5))  # fac 1.5 -> 1.0
    assert got == pytest.approx([1.0, 1.0, 1.0], abs=3e-3), got


# --------------------------------------------------------------------------- #
# 6. Off-path is byte-identical: a plain Math ADD emits no clamp bit
# --------------------------------------------------------------------------- #
def test_flags_off_emit_no_bits():
    tex = Node('TEX_IMAGE')
    m = Node('MATH', operation='ADD',  # no use_clamp attr at all
             inputs=[Sock('A', 0.0, Link(tex, 'Color')), Sock('B', 0.1)])
    base = Sock('Roughness', 0.5, Link(m, 'Value'))
    comp = C.compile_chain(base)
    math_instrs = [ins for ins in
                   [comp['code_flat'][i:i + 8]
                    for i in range(0, len(comp['code_flat']), 8)]
                   if ins[0] == C.OP_MATH]
    assert math_instrs, comp['code_flat']
    for ins in math_instrs:
        assert ins[7] & C.SVM_MATH_CLAMP == 0, ins  # imm high bit clear


# --------------------------------------------------------------------------- #
# 7. Addon <-> engine enum/flag parity (mirror shader_vm.h exactly)
# --------------------------------------------------------------------------- #
def test_enum_parity_with_header():
    assert (C.OP_CLAMP, C.CLAMP_MINMAX, C.CLAMP_RANGE) == (14, 0, 1)
    assert C.SVM_MATH_CLAMP == 0x80
    assert C.SVM_MIX_CLAMP_RESULT == 0x80
    with open(_HEADER, "r", encoding="utf-8") as f:
        src = f.read()
    assert re.search(r"OP_CLAMP\s*=\s*14", src)
    assert re.search(r"CLAMP_MINMAX\s*=\s*0", src)
    assert re.search(r"SVM_MATH_CLAMP\s*=\s*0x80", src)
    assert re.search(r"SVM_MIX_CLAMP_RESULT\s*=\s*0x80", src)

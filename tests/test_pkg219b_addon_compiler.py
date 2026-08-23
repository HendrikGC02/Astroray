"""pkg219b — addon node-chain compiler round-trip tests (no bpy required).

Builds duck-typed fake Blender node chains for the four broken chains, compiles
them with shader_vm_compiler.compile_chain, loads the emitted bytecode into the
engine, and verifies the rendered per-texel result matches an independent Python
reference. This exercises the compiler AND the shared HD svm_eval together.
"""
import os
import sys
import math
import pytest

astroray = pytest.importorskip("astroray")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "blender_addon"))
import shader_vm_compiler as C  # noqa: E402


# --------------------------------------------------------------------------- #
# Minimal duck-typed Blender node model
# --------------------------------------------------------------------------- #
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
    def __init__(self, from_node, from_socket_name="Value"):
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


class Out:
    def __init__(self, default):
        self.default_value = default


class Node:
    def __init__(self, type, inputs=None, outputs=None, **kw):
        self.type = type
        self.inputs = SockList(inputs or [])
        self.outputs = outputs or [Out(0.0)]
        for k, v in kw.items():
            setattr(self, k, v)


class ColorRamp:
    """Linear black->red ramp for testing (matches ramp.evaluate contract)."""
    def evaluate(self, f):
        f = max(0.0, min(1.0, f))
        return (f, 0.0, 0.0, 1.0)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _load_program(r, name, compiled, input_values):
    """Register a program texture from a compiled chain + per-input RGB values."""
    import numpy as np
    r.create_program_texture(name, "UV")
    for i, node in enumerate(compiled['inputs']):
        tex_name = "%s_in%d" % (name, i)
        val = input_values[id(node)]
        img = np.array(val, dtype="float32").reshape(1, 1, 3).ravel()
        r.load_texture(tex_name, img, 1, 1, "UV")
        r.program_texture_add_input(name, tex_name)
    r.set_program_texture_program(name, compiled['num_tex'], compiled['out_slot'],
                                  compiled['code_flat'], compiled['consts_flat'],
                                  compiled['ramps_flat'])


# --------------------------------------------------------------------------- #
# 1. Color Ramp on a texture
# --------------------------------------------------------------------------- #
def test_compile_color_ramp():
    tex = Node('TEX_IMAGE')
    ramp = Node('VALTORGB',
                inputs=[Sock('Fac', 0.0, Link(tex, 'Color'))],
                color_ramp=ColorRamp())
    base = Sock('Base Color', [0.5, 0.5, 0.5], Link(ramp, 'Color'))
    compiled = C.compile_chain(base)
    assert compiled is not None
    assert compiled['num_tex'] == 1

    r = astroray.Renderer()
    _load_program(r, "cr", compiled, {id(tex): (0.4, 0.4, 0.4)})
    got = r.sample_named_texture("cr", 0.5, 0.5)
    # black->red ramp at fac 0.4 -> (0.4, 0, 0)
    assert got == pytest.approx([0.4, 0.0, 0.0], abs=3e-3), got


# --------------------------------------------------------------------------- #
# 2. Mix of two textures
# --------------------------------------------------------------------------- #
def test_compile_mix_two_textures():
    texA = Node('TEX_IMAGE')
    texB = Node('TEX_IMAGE')
    mix = Node('MIX_RGB', blend_type='MIX',
               inputs=[Sock('Fac', 0.5),
                       Sock('Color1', [0, 0, 0], Link(texA, 'Color')),
                       Sock('Color2', [1, 1, 1], Link(texB, 'Color'))])
    base = Sock('Base Color', [0.5, 0.5, 0.5], Link(mix, 'Color'))
    compiled = C.compile_chain(base)
    assert compiled is not None
    assert compiled['num_tex'] == 2

    r = astroray.Renderer()
    _load_program(r, "mx", compiled,
                  {id(texA): (0.2, 0.4, 0.6), id(texB): (0.8, 0.6, 0.4)})
    got = r.sample_named_texture("mx", 0.5, 0.5)
    fac = 0.5
    want = [0.2*(1-fac) + 0.8*fac, 0.4*(1-fac) + 0.6*fac, 0.6*(1-fac) + 0.4*fac]
    assert got == pytest.approx(want, abs=3e-3), (got, want)


# --------------------------------------------------------------------------- #
# 3. Math (multiply) driving a factor from a texture
# --------------------------------------------------------------------------- #
def test_compile_math_multiply():
    tex = Node('TEX_IMAGE')
    math_node = Node('MATH', operation='MULTIPLY',
                     inputs=[Sock('A', 0.0, Link(tex, 'Color')),
                             Sock('B', 3.0)])
    base = Sock('Roughness', 0.5, Link(math_node, 'Value'))
    compiled = C.compile_chain(base)
    assert compiled is not None

    r = astroray.Renderer()
    _load_program(r, "mth", compiled, {id(tex): (0.2, 0.2, 0.2)})
    got = r.sample_named_texture("mth", 0.5, 0.5)
    assert got == pytest.approx([0.6, 0.6, 0.6], abs=3e-3), got


# --------------------------------------------------------------------------- #
# 4. Map Range on a factor from a texture
# --------------------------------------------------------------------------- #
def test_compile_map_range():
    tex = Node('TEX_IMAGE')
    mr = Node('MAP_RANGE', interpolation_type='LINEAR',
              inputs=[Sock('Value', 0.0, Link(tex, 'Color')),
                      Sock('From Min', 0.0), Sock('From Max', 1.0),
                      Sock('To Min', 0.2), Sock('To Max', 0.7)])
    base = Sock('Roughness', 0.5, Link(mr, 'Value'))
    compiled = C.compile_chain(base)
    assert compiled is not None

    r = astroray.Renderer()
    _load_program(r, "mr", compiled, {id(tex): (0.5, 0.5, 0.5)})
    got = r.sample_named_texture("mr", 0.5, 0.5)
    assert got == pytest.approx([0.45, 0.45, 0.45], abs=3e-3), got


# --------------------------------------------------------------------------- #
# 5. A bare image texture compiles to None (pkg186 path handles it)
# --------------------------------------------------------------------------- #
def test_bare_texture_is_none():
    tex = Node('TEX_IMAGE')
    base = Sock('Base Color', [0.5, 0.5, 0.5], Link(tex, 'Color'))
    assert C.compile_chain(base) is None


# --------------------------------------------------------------------------- #
# 6. Unsupported node -> VMCompileError (caller falls back, no silent grey)
# --------------------------------------------------------------------------- #
def test_unsupported_node_raises():
    tex = Node('TEX_IMAGE')
    weird = Node('BUMP', inputs=[Sock('Height', 0.0, Link(tex, 'Color'))])
    base = Sock('Base Color', [0.5, 0.5, 0.5], Link(weird, 'Normal'))
    with pytest.raises(C.VMCompileError):
        C.compile_chain(base)

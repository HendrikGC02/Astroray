"""pkg219c — addon node-chain compiler round-trip tests (no bpy required).

Builds duck-typed fake Blender node chains for the pkg219c opcodes (HSV, Invert,
Gamma, Bright/Contrast, Separate/Combine Color, RGB-to-BW downstream of a
texture), compiles them with shader_vm_compiler.compile_chain, loads the emitted
bytecode into the engine, and verifies the rendered per-texel result matches an
independent Python reference. Exercises the compiler AND the shared HD svm_eval.
"""
import os
import sys

import pytest

astroray = pytest.importorskip("astroray")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "blender_addon"))
import shader_vm_compiler as C  # noqa: E402

# reuse the op-VM Python reference for HSV
from test_pkg219c_op_vm import hsv_ref  # noqa: E402


# ---- minimal duck-typed Blender node model ---------------------------------
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
# 1. Hue/Saturation/Value on a texture
# --------------------------------------------------------------------------- #
def test_compile_hsv():
    tex = Node('TEX_IMAGE')
    hsv = Node('HUE_SAT',
               inputs=[Sock('Hue', 0.6), Sock('Saturation', 1.3),
                       Sock('Value', 0.9), Sock('Fac', 1.0),
                       Sock('Color', [0, 0, 0], Link(tex, 'Color'))])
    base = Sock('Base Color', [0.5, 0.5, 0.5], Link(hsv, 'Color'))
    compiled = C.compile_chain(base)
    assert compiled is not None and compiled['num_tex'] == 1
    color = (0.7, 0.2, 0.4)
    r = astroray.Renderer()
    _load_program(r, "hsv", compiled, {id(tex): color})
    got = r.sample_named_texture("hsv", 0.5, 0.5)
    want = hsv_ref(0.6, 1.3, 0.9, 1.0, list(color))
    assert got == pytest.approx(want, abs=3e-3), (got, want)


# --------------------------------------------------------------------------- #
# 2. Invert on a texture
# --------------------------------------------------------------------------- #
def test_compile_invert():
    tex = Node('TEX_IMAGE')
    inv = Node('INVERT',
               inputs=[Sock('Fac', 1.0),
                       Sock('Color', [0, 0, 0], Link(tex, 'Color'))])
    base = Sock('Base Color', [0.5, 0.5, 0.5], Link(inv, 'Color'))
    compiled = C.compile_chain(base)
    assert compiled is not None
    color = (0.2, 0.6, 0.9)
    r = astroray.Renderer()
    _load_program(r, "inv", compiled, {id(tex): color})
    got = r.sample_named_texture("inv", 0.5, 0.5)
    want = [1 - c for c in color]  # fac=1 -> full invert
    assert got == pytest.approx(want, abs=3e-3), (got, want)


# --------------------------------------------------------------------------- #
# 3. Gamma on a texture
# --------------------------------------------------------------------------- #
def test_compile_gamma():
    tex = Node('TEX_IMAGE')
    gam = Node('GAMMA',
               inputs=[Sock('Color', [0, 0, 0], Link(tex, 'Color')),
                       Sock('Gamma', 2.0)])
    base = Sock('Base Color', [0.5, 0.5, 0.5], Link(gam, 'Color'))
    compiled = C.compile_chain(base)
    assert compiled is not None
    color = (0.25, 0.5, 0.8)
    r = astroray.Renderer()
    _load_program(r, "gam", compiled, {id(tex): color})
    got = r.sample_named_texture("gam", 0.5, 0.5)
    want = [c ** 2.0 for c in color]
    assert got == pytest.approx(want, abs=3e-3), (got, want)


# --------------------------------------------------------------------------- #
# 4. Bright/Contrast on a texture
# --------------------------------------------------------------------------- #
def test_compile_bright_contrast():
    tex = Node('TEX_IMAGE')
    bc = Node('BRIGHTCONTRAST',
              inputs=[Sock('Color', [0, 0, 0], Link(tex, 'Color')),
                      Sock('Bright', 0.2), Sock('Contrast', 0.4)])
    base = Sock('Base Color', [0.5, 0.5, 0.5], Link(bc, 'Color'))
    compiled = C.compile_chain(base)
    assert compiled is not None
    color = (0.3, 0.5, 0.7)
    r = astroray.Renderer()
    _load_program(r, "bc", compiled, {id(tex): color})
    got = r.sample_named_texture("bc", 0.5, 0.5)
    a, b = 1.0 + 0.4, 0.2 - 0.4 * 0.5
    want = [max(a * c + b, 0.0) for c in color]
    assert got == pytest.approx(want, abs=3e-3), (got, want)


# --------------------------------------------------------------------------- #
# 5. Separate Color (Green) -> Math driving a scalar, from a texture
# --------------------------------------------------------------------------- #
def test_compile_separate_color_green():
    tex = Node('TEX_IMAGE')
    sep = Node('SEPARATE_COLOR', mode='RGB',
               inputs=[Sock('Color', [0, 0, 0], Link(tex, 'Color'))])
    # feed the Green output into a Math*2 node
    mathn = Node('MATH', operation='MULTIPLY',
                 inputs=[Sock('A', 0.0, Link(sep, 'Green')), Sock('B', 2.0)])
    base = Sock('Roughness', 0.5, Link(mathn, 'Value'))
    compiled = C.compile_chain(base)
    assert compiled is not None
    color = (0.2, 0.55, 0.9)
    r = astroray.Renderer()
    _load_program(r, "sep", compiled, {id(tex): color})
    got = r.sample_named_texture("sep", 0.5, 0.5)
    want = color[1] * 2.0  # green * 2
    assert got == pytest.approx([want, want, want], abs=3e-3), (got, want)


# --------------------------------------------------------------------------- #
# 6. Combine Color (RGB) from three separated channels — channel swap
# --------------------------------------------------------------------------- #
def test_compile_combine_color_swap():
    tex = Node('TEX_IMAGE')
    sep = Node('SEPARATE_COLOR', mode='RGB',
               inputs=[Sock('Color', [0, 0, 0], Link(tex, 'Color'))])
    comb = Node('COMBINE_COLOR', mode='RGB',
                inputs=[Sock('Red', 0.0, Link(sep, 'Blue')),   # R <- B
                        Sock('Green', 0.0, Link(sep, 'Green')),
                        Sock('Blue', 0.0, Link(sep, 'Red'))])  # B <- R
    base = Sock('Base Color', [0.5, 0.5, 0.5], Link(comb, 'Color'))
    compiled = C.compile_chain(base)
    assert compiled is not None
    color = (0.2, 0.5, 0.9)
    r = astroray.Renderer()
    _load_program(r, "comb", compiled, {id(tex): color})
    got = r.sample_named_texture("comb", 0.5, 0.5)
    want = [color[2], color[1], color[0]]
    assert got == pytest.approx(want, abs=3e-3), (got, want)


# --------------------------------------------------------------------------- #
# 7. RGB to BW on a texture
# --------------------------------------------------------------------------- #
def test_compile_rgb_to_bw():
    tex = Node('TEX_IMAGE')
    bw = Node('RGB_TO_BW',
              inputs=[Sock('Color', [0, 0, 0], Link(tex, 'Color'))])
    base = Sock('Roughness', 0.5, Link(bw, 'Val'))
    compiled = C.compile_chain(base)
    assert compiled is not None
    color = (0.4, 0.6, 0.2)
    r = astroray.Renderer()
    _load_program(r, "bw", compiled, {id(tex): color})
    got = r.sample_named_texture("bw", 0.5, 0.5)
    luma = 0.2126729 * color[0] + 0.7151522 * color[1] + 0.0721750 * color[2]
    assert got == pytest.approx([luma, luma, luma], abs=3e-3), (got, luma)


# --------------------------------------------------------------------------- #
# 8. Unsupported Separate Color mode (HSL) -> VMCompileError (no silent grey)
# --------------------------------------------------------------------------- #
def test_hsl_mode_raises():
    tex = Node('TEX_IMAGE')
    sep = Node('SEPARATE_COLOR', mode='HSL',
               inputs=[Sock('Color', [0, 0, 0], Link(tex, 'Color'))])
    base = Sock('Base Color', [0.5, 0.5, 0.5], Link(sep, 'Red'))
    with pytest.raises(C.VMCompileError):
        C.compile_chain(base)

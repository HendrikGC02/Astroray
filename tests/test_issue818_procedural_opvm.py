"""issue #818 Item 1 — procedural textures as op-VM inputs.

Before this change the op-VM compiler treated ONLY image textures as input
leaves; a procedural input (Noise / Checker / …) was rejected and the whole
downstream Math / Ramp chain constant-folded to grey (memory
`addon-constant-folds-shader-graph`). These tests cover:

  * the compiler now accepts a procedural node as an OP_LOAD_TEX leaf, and
  * the engine's shared HD svm_eval runs the compiled program over a natively
    sampled procedural child, producing a NON-CONSTANT per-texel result on the
    CPU (the same svm_eval the wavefront GPU shade path runs, so the GPU bake
    path is parity-by-construction).
"""
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "blender_addon"))
import shader_vm_compiler as C  # noqa: E402


# --- minimal duck-typed Blender node model (shared shape with pkg219b tests) --
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


class ColorRamp:
    def evaluate(self, f):
        f = max(0.0, min(1.0, f))
        return (f, 0.0, 0.0, 1.0)


# --------------------------------------------------------------------------- #
# Compiler: a procedural node is a valid input leaf.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("proc_type", sorted(C._PROC_TEX_TYPES))
def test_procedural_leaf_accepted(proc_type):
    proc = Node(proc_type, inputs=[Sock('Vector')])
    math_node = Node('MATH', operation='MULTIPLY',
                     inputs=[Sock('A', 0.0, Link(proc, 'Color')),
                             Sock('B', 2.0)])
    base = Sock('Base Color', [0.5, 0.5, 0.5], Link(math_node, 'Color'))
    compiled = C.compile_chain(base)
    assert compiled is not None
    assert compiled['num_tex'] == 1
    assert compiled['inputs'][0] is proc


def test_noise_math_ramp_headline_chain_compiles():
    # The issue's PRIMARY acceptance topology: Noise -> Math(Multiply) ->
    # Color Ramp -> Base Color.
    noise = Node('TEX_NOISE', inputs=[Sock('Vector')])
    mul = Node('MATH', operation='MULTIPLY',
               inputs=[Sock('A', 0.0, Link(noise, 'Fac')), Sock('B', 2.0)])
    ramp = Node('VALTORGB',
                inputs=[Sock('Fac', 0.0, Link(mul, 'Value'))],
                color_ramp=ColorRamp())
    base = Sock('Base Color', [0.5, 0.5, 0.5], Link(ramp, 'Color'))
    compiled = C.compile_chain(base)
    assert compiled is not None
    assert compiled['num_tex'] == 1
    assert compiled['inputs'][0] is noise
    # OP_LOAD_TEX (op 1) must be present — the procedural is a sampled input.
    ops = [compiled['code_flat'][i] for i in range(0, len(compiled['code_flat']), 8)]
    assert C.OP_LOAD_TEX in ops


def test_bare_procedural_needs_no_vm():
    # A procedural straight into a BSDF socket routes to the native/bake path
    # (get_base_color_texture), NOT the op-VM: compile_chain returns None.
    proc = Node('TEX_CHECKER', inputs=[Sock('Vector')])
    base = Sock('Base Color', [0.5, 0.5, 0.5], Link(proc, 'Color'))
    assert C.compile_chain(base) is None


# --------------------------------------------------------------------------- #
# Engine: svm_eval over a natively sampled procedural child is NON-CONSTANT.
# --------------------------------------------------------------------------- #
def test_engine_program_over_checker_is_nonconstant():
    astroray = pytest.importorskip("astroray")
    # Build: Checker -> Math(Multiply 1.0) -> Base Color, then feed a REAL
    # procedural checker child to the program and sample across UV.
    checker = Node('TEX_CHECKER', inputs=[Sock('Vector')])
    mul = Node('MATH', operation='MULTIPLY',
               inputs=[Sock('A', 0.0, Link(checker, 'Color')), Sock('B', 1.0)])
    base = Sock('Base Color', [0.5, 0.5, 0.5], Link(mul, 'Color'))
    compiled = C.compile_chain(base)
    assert compiled is not None and compiled['num_tex'] == 1

    r = astroray.Renderer()
    # A UV-domain checker so sample_named_texture(u, v) exercises the field.
    r.create_procedural_texture("chk", "checker", [1, 1, 1, 0, 0, 0, 8.0])
    r.set_texture_coord_mode("chk", "UV")
    r.create_program_texture("prog", "UV")
    r.program_texture_add_input("prog", "chk")
    r.set_program_texture_program(
        "prog", compiled['num_tex'], compiled['out_slot'],
        compiled['code_flat'], compiled['consts_flat'], compiled['ramps_flat'])

    samples = []
    for i in range(8):
        u = (i + 0.5) / 8.0
        samples.append(r.sample_named_texture("prog", u, 0.5)[0])
    assert max(samples) - min(samples) > 0.5, samples  # checker toggles 0<->1

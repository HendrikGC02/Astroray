"""#1017 - a procedural op-VM input's Mapping must reach the engine.

prod_wood: Object -> Mapping (rotate 90 deg about Y, scale z 3) -> Wave + Noise -> Math ->
Color Ramp. Both inputs share the Mapping, so the addon hands the ProgramTexture one
coordinate contract. It used to give the program the legacy 2-D transform, which never
moves the point a procedural reads: the Mapping was dropped on the CPU (ProgramTexture
samples its inputs at the program's point) and on the #1007 per-hit GPU path, while the
children carry the full matrix since #945. Now the program carries the 3-D matrix.
"""
import numpy as np

from test_issue818_procedural_opvm import Link, Node, Sock, _load_addon_stub

ROT_Y90 = (0.0, np.radians(90.0), 0.0)
SCALE = (1.0, 1.0, 3.0)


class _RecRenderer:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def rec(*a, **_k):
            self.calls.append((name, a))
            return 1
        return rec


def _wood_socket(mapped):
    tc = Node('TEX_COORD')
    src, out = tc, 'Object'
    if mapped:
        src = Node('MAPPING', vector_type='POINT', inputs=[
            Sock('Vector', (0, 0, 0), Link(tc, 'Object')), Sock('Location', (0, 0, 0)),
            Sock('Rotation', ROT_Y90), Sock('Scale', SCALE)])
        out = 'Vector'
    wave = Node('TEX_WAVE', name='Wave', inputs=[Sock('Vector', (0, 0, 0), Link(src, out))])
    noise = Node('TEX_NOISE', name='Noise', inputs=[Sock('Vector', (0, 0, 0), Link(src, out))])
    mix = Node('MIX_RGB', blend_type='MIX',
               inputs=[Sock('Fac', 0.5),
                       Sock('Color1', [0, 0, 0], Link(wave, 'Color')),
                       Sock('Color2', [0, 0, 0], Link(noise, 'Color'))])
    return Sock('Base Color', [0.5, 0.5, 0.5], Link(mix, 'Color'))


def _export(monkeypatch, mapped):
    addon = _load_addon_stub(monkeypatch)
    eng = addon.CustomRaytracerRenderEngine.__new__(addon.CustomRaytracerRenderEngine)
    eng._current_material_name = "Wood"
    eng._generated_textures_by_material = {}
    sock = _wood_socket(mapped)
    rr = _RecRenderer()
    prog = eng._maybe_build_program_texture(sock, Node('BSDF_PRINCIPLED', inputs=[sock]),
                                            'Base Color', rr)
    assert prog is not None, eng._degradation_report().messages()
    mats = {a[0]: a[1] for n, a in rr.calls if n == 'set_texture_mapping_matrix'}
    legacy = [a for n, a in rr.calls if n == 'set_texture_uv_transform' and a[0] == prog]
    return prog, mats, legacy


def test_program_carries_its_inputs_mapping(monkeypatch):
    prog, mats, legacy = _export(monkeypatch, mapped=True)
    assert prog in mats, mats.keys()
    assert not legacy, legacy
    children = [m for name, m in mats.items() if name != prog]
    assert len(children) == 2
    # The program's matrix is the inputs' own Mapping chain.
    for m in children:
        assert np.allclose(mats[prog], m, atol=0)
    M = np.array(mats[prog]).reshape(3, 4)
    # Blender Mapping POINT: M = Ry(90) @ diag(1, 1, 3) -> x' = 3 z, z' = -x.
    assert np.allclose(M[:, :3], [[0, 0, 3], [0, 1, 0], [-1, 0, 0]], atol=1e-6), M


def test_unmapped_program_has_no_transform(monkeypatch):
    # Identity Mapping exports nothing: the engine sees the exact pre-#1017 calls.
    prog, mats, legacy = _export(monkeypatch, mapped=False)
    assert not mats and not legacy, (mats, legacy)

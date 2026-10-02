"""#881 / #1006 addon export wiring (no Blender, no engine build needed).

#881: a Noise Fac output linked straight into a colour socket must load the grey
Fac variant (fac_only) and pass noise_dimensions / W; the Color output keeps the
Color triple. #1006: materials reading Texture Coordinate > Object are detected
(also inside node groups) and get the world -> object-local affine.
"""
import numpy as np
from test_issue818_procedural_opvm import Link, Node, Sock, _load_addon_stub


class _Recorder:
    def __init__(self):
        self.calls = []

    def create_procedural_texture(self, name, kind, params, *a):
        self.calls.append((name, kind, list(params)))

    def __getattr__(self, _name):
        return lambda *a, **k: 1


def _engine(monkeypatch):
    addon = _load_addon_stub(monkeypatch)
    eng = addon.CustomRaytracerRenderEngine.__new__(addon.CustomRaytracerRenderEngine)
    eng._current_material_name = "M"
    eng._generated_textures_by_material = {}
    return addon, eng


def _noise(dims="3D"):
    return Node('TEX_NOISE', name="Noise", noise_type='FBM', normalize=True,
                noise_dimensions=dims,
                inputs=[Sock('Vector'), Sock('W', 0.25), Sock('Scale', 4.0),
                        Sock('Detail', 2.0), Sock('Roughness', 0.5),
                        Sock('Lacunarity', 2.0), Sock('Distortion', 0.0)])


def _noise_params(monkeypatch, out_socket, dims="3D"):
    _, eng = _engine(monkeypatch)
    rec = _Recorder()
    bsdf = Node('BSDF_DIFFUSE', inputs=[Sock('Color', [0.8, 0.8, 0.8],
                                             Link(_noise(dims), out_socket))])
    _, tex = eng.get_base_color_texture(bsdf, 'Color', rec)
    assert tex is not None
    (_, _, params), = [c for c in rec.calls if c[1] == 'noise_perlin']
    return params


def test_noise_fac_into_colour_loads_grey_variant(monkeypatch):
    for name in ('Fac', 'Factor'):  # Blender 5 labels the Fac output 'Factor'
        params = _noise_params(monkeypatch, name)
        assert params[11] == 1.0, params


def test_noise_color_output_keeps_triple(monkeypatch):
    assert _noise_params(monkeypatch, 'Color')[11] == 0.0


def test_noise_dimensions_and_w_exported(monkeypatch):
    for dims, code in (('1D', 1.0), ('2D', 2.0), ('3D', 3.0), ('4D', 4.0)):
        params = _noise_params(monkeypatch, 'Color', dims)
        assert params[9] == code and params[10] == 0.25, params


def test_object_coord_tree_scan(monkeypatch):
    addon, _ = _engine(monkeypatch)

    class _Outs(dict):
        def get(self, k):
            return dict.get(self, k)

    def tc(linked):
        n = Node('TEX_COORD')
        n.outputs = _Outs(Object=type("O", (), {"is_linked": linked})())
        return n

    def tree(*nodes):
        return type("T", (), {"nodes": list(nodes)})()

    assert addon._tree_uses_object_coords(tree(tc(True)))
    assert not addon._tree_uses_object_coords(tree(tc(False), Node('TEX_NOISE')))
    group = Node('GROUP', node_tree=tree(Node('MATH'), tc(True)))
    assert addon._tree_uses_object_coords(tree(Node('MATH'), group))


def test_object_local_affine_is_the_inverse(monkeypatch):
    addon, _ = _engine(monkeypatch)
    rng = np.random.default_rng(1006)
    m = np.eye(4)
    m[:3, :3] = rng.normal(size=(3, 3)) + 2 * np.eye(3)
    m[:3, 3] = rng.normal(size=3)
    a = np.array(addon._object_local_affine(m.tolist())).reshape(3, 4)
    p = rng.normal(size=3)
    world = m @ np.append(p, 1.0)
    assert np.allclose(a @ world, p, atol=1e-9)
    assert addon._object_local_affine(np.zeros((4, 4)).tolist()) is None


def test_linked_w_is_reported_not_silent(monkeypatch):
    # A linked W (1D / 4D) is read as its default value, as every linked Noise socket
    # is until per-hit socket inputs exist; it must be a reported degradation.
    _, eng = _engine(monkeypatch)
    noise = _noise("4D")
    noise.inputs.get('W')._link = Link(Node('VALUE'), 'Value')
    bsdf = Node('BSDF_DIFFUSE', inputs=[Sock('Color', [0.8, 0.8, 0.8], Link(noise, 'Fac'))])
    eng.get_base_color_texture(bsdf, 'Color', _Recorder())
    assert any("linked W input" in m for m in eng._degradation_report().messages())

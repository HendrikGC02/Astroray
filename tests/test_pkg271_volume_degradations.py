"""pkg271 — the Volume lowering reports the inputs it cannot honour (pkg200 rule).

A linked Principled Volume / Volume Scatter input (a texture or attribute node
driving Density, Color, ...) is lowered to the socket's default value, and a
non-empty Color Attribute is not consumed; both must appear in the degradation
list instead of being dropped silently. Pure addon logic (no Blender).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "blender_addon"))
import volume_export as vol


class _Sock:
    def __init__(self, v, linked=False):
        self.default_value = v
        self.is_linked = linked
        self.links = []


class _Node:
    def __init__(self, type_, bl_idname, inputs):
        self.type = type_
        self.bl_idname = bl_idname
        self.inputs = dict(inputs)


class _Link:
    def __init__(self, n):
        self.from_node = n


class _Mat:
    def __init__(self, node):
        vin = _Sock(None, linked=True)
        vin.links = [_Link(node)]
        out = _Node("OUTPUT_MATERIAL", "ShaderNodeOutputMaterial",
                    {"Volume": vin, "Surface": _Sock(None)})
        out.is_active_output = True

        class NT:
            pass
        self.node_tree = NT()
        self.node_tree.nodes = [out, node]


def _principled(**over):
    socks = {"Color": _Sock((0.8, 0.8, 0.8, 1.0)), "Density": _Sock(1.0),
             "Anisotropy": _Sock(0.0), "Absorption Color": _Sock((1.0, 1.0, 1.0, 1.0)),
             "Color Attribute": _Sock("")}
    socks.update(over)
    return _Node("VOLUME_PRINCIPLED", "ShaderNodeVolumePrincipled", socks)


def test_plain_principled_volume_has_no_degradation():
    pv = vol.principled_volume_from_material(_Mat(_principled()))
    assert pv["degradations"] == []


def test_linked_density_is_reported():
    pv = vol.principled_volume_from_material(_Mat(_principled(Density=_Sock(2.0, linked=True))))
    assert pv["density"] == 2.0
    assert any("'Density' input is linked" in d for d in pv["degradations"]), pv["degradations"]


def test_color_attribute_is_reported():
    pv = vol.principled_volume_from_material(_Mat(_principled(**{"Color Attribute": _Sock("color")})))
    assert any("Color Attribute" in d and "'color'" in d for d in pv["degradations"]), pv["degradations"]


def test_linked_scatter_color_is_reported():
    node = _Node("VOLUME_SCATTER", "ShaderNodeVolumeScatter",
                 {"Color": _Sock((0.8, 0.8, 0.8, 1.0), linked=True), "Density": _Sock(1.0),
                  "Anisotropy": _Sock(0.0)})
    pv = vol.principled_volume_from_material(_Mat(node))
    assert any("'Color' input is linked" in d for d in pv["degradations"]), pv["degradations"]

import types

import numpy as np

from test_blender_view_layers import _load_blender_addon


def test_denoising_data_registers_albedo_and_normal_rgb_passes(monkeypatch):
    class RendererStub:
        pass

    addon = _load_blender_addon(monkeypatch, RendererStub)
    engine = addon.CustomRaytracerRenderEngine()

    registered = []
    engine.register_pass = lambda scene, layer, name, channels, channel_id, kind: registered.append(
        (name, channels, channel_id, kind)
    )

    view_layer = types.SimpleNamespace(
        use_pass_denoising_data=True,
        use_pass_z=False,
        use_pass_mist=False,
        use_pass_position=False,
        use_pass_normal=False,
        use_pass_uv=False,
        use_pass_object_index=False,
        use_pass_material_index=False,
        use_pass_cryptomatte_object=False,
        use_pass_cryptomatte_material=False,
    )

    engine.update_render_passes(types.SimpleNamespace(), view_layer)

    pass_specs = {name: (channels, channel_id) for name, channels, channel_id, _ in registered}
    assert pass_specs["Albedo"] == (3, "RGB")
    assert pass_specs["Normal"] == (3, "RGB")


def test_write_pixels_emits_denoising_albedo_and_normal(monkeypatch):
    class RendererStub:
        def get_albedo_buffer(self):
            return np.full((2, 2, 3), 0.25, dtype=np.float32)

        def get_normal_buffer(self):
            return np.full((2, 2, 3), 0.75, dtype=np.float32)

    addon = _load_blender_addon(monkeypatch, RendererStub)
    engine = addon.CustomRaytracerRenderEngine()

    class RectStub:
        def __init__(self):
            self.values = None

        def foreach_set(self, flat):
            self.values = np.asarray(flat, dtype=np.float32)

    class PassStub:
        def __init__(self):
            self.rect = RectStub()

    passes = {
        "Combined": PassStub(),
        "Albedo": PassStub(),
        "Normal": PassStub(),
    }
    layer = types.SimpleNamespace(passes=passes)
    result = types.SimpleNamespace(layers=[layer])
    engine.begin_result = lambda *_args, **_kwargs: result
    engine.end_result = lambda _result: None

    view_layer = types.SimpleNamespace(use_pass_denoising_data=True)
    pixels = np.zeros((2, 2, 3), dtype=np.float32)
    engine.write_pixels(
        pixels,
        2,
        2,
        renderer=RendererStub(),
        view_layer=view_layer,
        scene=types.SimpleNamespace(),
    )

    assert passes["Albedo"].rect.values.reshape(2, 2, 4)[0, 0, :3].tolist() == [0.25, 0.25, 0.25]
    assert passes["Normal"].rect.values.reshape(2, 2, 4)[0, 0, :3].tolist() == [0.75, 0.75, 0.75]

"""pkg176 Stage 3 - world/light/camera visible-degradation unit tests.

Pure Python, no Blender / engine / GPU. Exercises
``blender_addon.native_settings.report_unsupported_native_controls`` with stub
``scene`` datablocks mirroring the Blender shape (camera.data.*, light.data.*).

Ground truth (owner-ratified Stage-0 table, verified against the engine
bindings): every DROPPED-SILENT world/light/camera control needs NEW engine
capability, so Stage 3 wires ZERO of them and instead makes the steering wheel
stop dropping them SILENTLY. Acceptance covered:
  (a) a user-set DROPPED control the engine can't honour produces a VISIBLE
      WARNING naming it (never silent);
  (b) untouched defaults stay quiet (no per-render warning spam);
  (c) multiple set controls collapse into ONE consolidated report per render;
  (d) report=None falls back to print (headless / script path).
"""

import importlib.util
import pathlib
import sys
import types

import pytest

_ADDON = pathlib.Path(__file__).resolve().parents[1] / "blender_addon"


def _load_native_settings():
    """Load native_settings.py standalone (it does ``from settings_map import
    MAPPING``, so put blender_addon/ on sys.path first; no bpy pulled in)."""
    if str(_ADDON) not in sys.path:
        sys.path.insert(0, str(_ADDON))
    spec = importlib.util.spec_from_file_location(
        "pkg176_native_settings_s3", _ADDON / "native_settings.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ns = _load_native_settings()


# --------------------------------------------------------------------------- #
# stub Blender datablocks
# --------------------------------------------------------------------------- #

def _dof(use_dof=False, aperture_blades=0, aperture_ratio=1.0):
    return types.SimpleNamespace(
        use_dof=use_dof,
        aperture_blades=aperture_blades,
        aperture_ratio=aperture_ratio,
    )


def _camera(cam_type="PERSP", clip_start=0.1, clip_end=1000.0, dof=None):
    return types.SimpleNamespace(
        data=types.SimpleNamespace(
            type=cam_type,
            clip_start=clip_start,
            clip_end=clip_end,
            dof=dof if dof is not None else _dof(),
        )
    )


def _light_obj(name, specular_factor=1.0):
    return types.SimpleNamespace(
        type="LIGHT",
        name=name,
        data=types.SimpleNamespace(specular_factor=specular_factor),
    )


def _scene(camera=None, objects=()):
    return types.SimpleNamespace(
        camera=camera if camera is not None else _camera(),
        objects=list(objects),
    )


def _collect(scene):
    reports = []
    msgs = ns.report_unsupported_native_controls(
        scene, report=lambda tag, m: reports.append((tag, m))
    )
    return msgs, reports


# --------------------------------------------------------------------------- #
# (b) untouched defaults stay quiet
# --------------------------------------------------------------------------- #

def test_default_scene_is_silent():
    msgs, reports = _collect(_scene(objects=[_light_obj("Lamp")]))
    assert msgs == []
    assert reports == []


def test_no_camera_is_silent():
    msgs, reports = _collect(types.SimpleNamespace(camera=None, objects=[]))
    assert msgs == []
    assert reports == []


# --------------------------------------------------------------------------- #
# (a) each user-set DROPPED control produces a visible warning
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("cam_type", ["ORTHO", "PANO"])
def test_non_perspective_camera_warns(cam_type):
    msgs, reports = _collect(_scene(camera=_camera(cam_type=cam_type)))
    assert any(cam_type in m for m in msgs)
    assert len(reports) == 1
    assert reports[0][0] == {'WARNING'}


def test_changed_clip_warns():
    msgs, _ = _collect(_scene(camera=_camera(clip_start=2.0, clip_end=500.0)))
    assert any("clip_start/clip_end" in m for m in msgs)


def test_default_clip_is_silent():
    # default clip must NOT trigger a warning (no per-render spam)
    msgs, _ = _collect(_scene(camera=_camera(clip_start=0.1, clip_end=1000.0)))
    assert msgs == []


def test_polygonal_bokeh_warns_only_with_dof():
    with_dof = _camera(dof=_dof(use_dof=True, aperture_blades=6))
    msgs, _ = _collect(_scene(camera=with_dof))
    assert any("aperture_blades" in m for m in msgs)

    # blades set but DoF off -> not render-affecting -> silent
    no_dof = _camera(dof=_dof(use_dof=False, aperture_blades=6))
    msgs2, _ = _collect(_scene(camera=no_dof))
    assert msgs2 == []


def test_anamorphic_ratio_warns_only_with_dof():
    with_dof = _camera(dof=_dof(use_dof=True, aperture_ratio=2.0))
    msgs, _ = _collect(_scene(camera=with_dof))
    assert any("aperture_ratio" in m for m in msgs)

    no_dof = _camera(dof=_dof(use_dof=False, aperture_ratio=2.0))
    msgs2, _ = _collect(_scene(camera=no_dof))
    assert msgs2 == []


def test_light_specular_factor_warns_and_names_lights():
    scene = _scene(objects=[
        _light_obj("Key", specular_factor=0.5),
        _light_obj("Fill", specular_factor=1.0),   # default -> not named
        _light_obj("Rim", specular_factor=2.0),
    ])
    msgs, _ = _collect(scene)
    spec_msgs = [m for m in msgs if "specular_factor" in m]
    assert len(spec_msgs) == 1
    assert "Key" in spec_msgs[0] and "Rim" in spec_msgs[0]
    assert "Fill" not in spec_msgs[0]


# --------------------------------------------------------------------------- #
# (c) multiple set controls collapse into ONE consolidated report
# --------------------------------------------------------------------------- #

def test_multiple_controls_one_consolidated_report():
    scene = _scene(
        camera=_camera(cam_type="PANO", clip_start=5.0,
                       dof=_dof(use_dof=True, aperture_blades=5, aperture_ratio=1.5)),
        objects=[_light_obj("Key", specular_factor=0.2)],
    )
    _, reports = _collect(scene)
    assert len(reports) == 1                       # exactly one WARNING per render
    joined = reports[0][1]
    for token in ("PANO", "clip_start/clip_end", "aperture_blades",
                  "aperture_ratio", "specular_factor"):
        assert token in joined


# --------------------------------------------------------------------------- #
# (d) report=None falls back to print (headless / direct-call path)
# --------------------------------------------------------------------------- #

def test_report_none_prints(capsys):
    ns.report_unsupported_native_controls(_scene(camera=_camera(cam_type="ORTHO")), report=None)
    out = capsys.readouterr().out
    assert "ORTHO" in out
    assert "not honoured" in out


def test_report_none_default_scene_silent(capsys):
    ns.report_unsupported_native_controls(_scene(objects=[_light_obj("Lamp")]), report=None)
    assert capsys.readouterr().out == ""


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

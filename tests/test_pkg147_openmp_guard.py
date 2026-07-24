"""pkg147: OpenMP-enabled-build guard tests.

Verifies blender_addon._check_openmp_disabled() — the structural guard added
to fix the addon CPU-render hang (device_mode='cpu', >16px): an OpenMP-
enabled .pyd's render() progress callback is invoked from whichever OpenMP
worker thread finishes a tile (raytracer.h's `#pragma omp parallel for`
render loop) and deadlocks against the GIL held by the calling thread for
the whole render() call. build_blender_addon.py always passes
-DASTRORAY_DISABLE_OPENMP=ON, so this only guards ad-hoc/dev builds
(e.g. a raw cmake or configure_and_build.bat run) that get dropped into the
addon directory without going through the packaging script.
"""

import sys
import types
from unittest.mock import patch

import pytest


def _make_stub_bpy():
    """Build minimal stub bpy module for testing blender_addon without real Blender."""
    bpy_module = types.ModuleType("bpy")
    bpy_types_module = types.ModuleType("bpy.types")
    bpy_props_module = types.ModuleType("bpy.props")
    bpy_utils_module = types.ModuleType("bpy.utils")

    class _Base:
        pass

    bpy_types_module.Panel = _Base
    bpy_types_module.Operator = _Base
    bpy_types_module.AddonPreferences = _Base
    bpy_types_module.PropertyGroup = _Base
    bpy_types_module.RenderEngine = _Base
    bpy_types_module.Material = _Base
    bpy_types_module.Scene = _Base
    bpy_types_module.Object = _Base
    bpy_module.types = bpy_types_module

    for name in ("BoolProperty", "IntProperty", "FloatProperty", "StringProperty",
                 "PointerProperty", "FloatVectorProperty", "EnumProperty"):
        setattr(bpy_props_module, name, lambda **_kwargs: None)
    bpy_module.props = bpy_props_module

    registered = []
    bpy_utils_module.register_class = lambda cls: registered.append(cls)
    bpy_utils_module.unregister_class = lambda cls: registered.remove(cls) if cls in registered else None
    bpy_module.utils = bpy_utils_module
    bpy_module.path = types.SimpleNamespace(abspath=lambda p: p)

    mathutils_module = types.ModuleType("mathutils")
    mathutils_module.Vector = lambda values: values

    sys.modules["bpy"] = bpy_module
    sys.modules["bpy.types"] = bpy_types_module
    sys.modules["bpy.props"] = bpy_props_module
    sys.modules["bpy.utils"] = bpy_utils_module
    sys.modules["mathutils"] = mathutils_module

    return bpy_module


def _cleanup_bpy_mock():
    for key in list(sys.modules.keys()):
        if key.startswith("bpy") or key == "blender_addon" or key == "shader_blending":
            del sys.modules[key]


def test_features_dict_has_openmp_key(astroray_module):
    """astroray.__features__ must expose an 'openmp' key (added pkg147) so the
    addon guard has something to check."""
    assert "openmp" in astroray_module.__features__
    assert isinstance(astroray_module.__features__["openmp"], bool)


def test_openmp_enabled_register_raises(astroray_module):
    """When __features__['openmp'] is True, _check_openmp_disabled() raises a
    loud RuntimeError instead of letting register() proceed into the hang."""
    _make_stub_bpy()
    try:
        import blender_addon
        with patch.object(astroray_module, "__features__", {"openmp": True}):
            with patch.object(blender_addon, "RAYTRACER_AVAILABLE", True):
                with pytest.raises(RuntimeError) as exc_info:
                    blender_addon._check_openmp_disabled()
                msg = str(exc_info.value)
                assert "OPENMP" in msg.upper()
                assert "build_blender_addon.py" in msg
    finally:
        _cleanup_bpy_mock()


def test_openmp_disabled_register_succeeds(astroray_module):
    """When __features__['openmp'] is False (the shipped-addon case —
    build_blender_addon.py always passes -DASTRORAY_DISABLE_OPENMP=ON),
    _check_openmp_disabled() is a silent no-op."""
    _make_stub_bpy()
    try:
        import blender_addon
        with patch.object(astroray_module, "__features__", {"openmp": False}):
            with patch.object(blender_addon, "RAYTRACER_AVAILABLE", True):
                blender_addon._check_openmp_disabled()  # should not raise
    finally:
        _cleanup_bpy_mock()


def test_openmp_key_missing_defaults_safe(astroray_module):
    """Older .pyd builds (pre-pkg147) won't have the 'openmp' key at all —
    the guard must default to False (permissive) rather than crash or
    false-positive refuse to load."""
    _make_stub_bpy()
    try:
        import blender_addon
        with patch.object(astroray_module, "__features__", {}):
            with patch.object(blender_addon, "RAYTRACER_AVAILABLE", True):
                blender_addon._check_openmp_disabled()  # should not raise
    finally:
        _cleanup_bpy_mock()


def test_raytracer_unavailable_skips_openmp_guard():
    """If the raytracer module didn't load, the guard silently skips (mirrors
    _check_build_integrity's same-named precedent)."""
    _make_stub_bpy()
    try:
        import blender_addon
        with patch.object(blender_addon, "RAYTRACER_AVAILABLE", False):
            blender_addon._check_openmp_disabled()  # should not raise
    finally:
        _cleanup_bpy_mock()


class _StubSettings:
    device_mode = "gpu"
    wavelength_preset = "visible"
    integrator_type = "path_tracer"


class _StubRenderer:
    gpu_available = True

    def set_use_gpu(self, flag):
        pass


def test_configure_backend_gpu_mode_ignores_openmp(astroray_module):
    """An OpenMP-enabled build must NOT be blocked from registering/rendering
    on GPU — only the CPU path it would actually deadlock is refused (the
    design fork resolved after test_blender_parity_matrix_generation, which
    renders via device_mode='auto'+GPU, regressed under a register()-time
    block)."""
    _make_stub_bpy()
    try:
        import blender_addon
        with patch.object(astroray_module, "__features__", {"openmp": True}):
            settings = _StubSettings()
            settings.device_mode = "gpu"
            result = blender_addon.configure_backend(_StubRenderer(), settings)
            assert result == "gpu"
    finally:
        _cleanup_bpy_mock()


def test_configure_backend_cpu_mode_raises_with_openmp(astroray_module):
    """device_mode='cpu' with an OpenMP-enabled build must raise before any
    render is attempted — this is the actual pkg147 hang trigger."""
    _make_stub_bpy()
    try:
        import blender_addon
        with patch.object(astroray_module, "__features__", {"openmp": True}):
            settings = _StubSettings()
            settings.device_mode = "cpu"
            with pytest.raises(RuntimeError, match="OPENMP"):
                blender_addon.configure_backend(_StubRenderer(), settings)
    finally:
        _cleanup_bpy_mock()

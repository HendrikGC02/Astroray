"""pkg80 — Blender addon must resolve the 'auto' integrator dropdown to a
concrete registered plugin before any C++ call.

Reuses the loader helper from test_blender_backend_policy.py.
"""

import pytest

from test_blender_backend_policy import _load_blender_addon, _make_settings


class _NullRenderer:
    gpu_available = False


def _registry(*, names, gpu_supported_set):
    return {
        "integrator_registry_names": lambda: list(names),
        "integrator_capabilities": lambda n: {
            "gpuSupported": n in gpu_supported_set,
            "gpuFallbackReason": "" if n in gpu_supported_set else "no GPU kernel",
        },
    }


def test_auto_integrator_cpu_returns_registered_name(monkeypatch):
    """integrator='auto' + device_mode='cpu' → first preferred registered name."""
    addon = _load_blender_addon(
        monkeypatch, _NullRenderer,
        extra_astroray_attrs=_registry(
            names=["multiwavelength_path_tracer", "path_tracer", "ambient_occlusion"],
            gpu_supported_set={"path_tracer"},
        ),
    )
    settings = _make_settings(device_mode="cpu", integrator_type="auto")
    assert addon._effective_integrator_name(settings) == "path_tracer"


def test_auto_integrator_gpu_picks_gpu_capable_plugin(monkeypatch):
    """integrator='auto' + device_mode='gpu' (CUDA build) → GPU-capable name."""
    addon = _load_blender_addon(
        monkeypatch, _NullRenderer,
        extra_astroray_attrs=_registry(
            # path_tracer first in preference but lacks GPU here; ambient_occlusion has GPU.
            names=["path_tracer", "ambient_occlusion"],
            gpu_supported_set={"ambient_occlusion"},
        ),
    )
    settings = _make_settings(device_mode="gpu", integrator_type="auto")
    name = addon._effective_integrator_name(settings)
    assert name == "ambient_occlusion"


def test_auto_integrator_gpu_raises_when_no_plugin_supports_gpu(monkeypatch):
    """integrator='auto' + device_mode='gpu' (CPU-only build) → clear RuntimeError."""
    addon = _load_blender_addon(
        monkeypatch, _NullRenderer,
        extra_astroray_attrs=_registry(
            names=["path_tracer", "multiwavelength_path_tracer"],
            gpu_supported_set=set(),
        ),
    )
    settings = _make_settings(device_mode="gpu", integrator_type="auto")
    with pytest.raises(RuntimeError) as exc_info:
        addon._effective_integrator_name(settings)
    msg = str(exc_info.value)
    assert "auto" in msg
    assert "gpu" in msg.lower()


def test_non_auto_integrator_returned_unchanged(monkeypatch):
    """integrator='path_tracer' (any non-auto) → returned verbatim, no registry lookup."""
    calls = {"registry": 0}

    def _registry_names():
        calls["registry"] += 1
        return ["path_tracer"]

    addon = _load_blender_addon(
        monkeypatch, _NullRenderer,
        extra_astroray_attrs={
            "integrator_registry_names": _registry_names,
            "integrator_capabilities": lambda n: {"gpuSupported": True, "gpuFallbackReason": ""},
        },
    )
    settings = _make_settings(device_mode="cpu", integrator_type="path_tracer")
    assert addon._effective_integrator_name(settings) == "path_tracer"
    assert calls["registry"] == 0, "non-auto must not query the registry"

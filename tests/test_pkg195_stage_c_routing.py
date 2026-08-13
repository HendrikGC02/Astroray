"""pkg195 Stage C — addon integrator-routing for Replace-mode spectra (stub-bpy).

A Replace-mode authored spectrum (Drawn / Spectrum Preset / Spectral Profile
source node wired to a Surface) is only consulted per-λ by the multiwavelength
integrator; the default path_tracer never calls evalSpectralExt. render() must
therefore route a visible-band CPU render to the MW integrator when such a
material is present — otherwise the authored reflectance is a visible no-op (the
pkg57 failure Stage C fixes). This test pins the pure routing decision.

GPU keeps its integrator (Replace is CPU-exact; the GPU MW leg is the
light-sampling-blind naive oracle per the enableNEE contract).
"""
from test_blender_backend_policy import _load_blender_addon


class _NullRenderer:
    def __init__(self, *a, **k):
        pass


def _addon(monkeypatch):
    return _load_blender_addon(monkeypatch, _NullRenderer)


def test_route_cpu_visible_replace_switches_to_mw(monkeypatch):
    addon = _addon(monkeypatch)
    assert addon._route_replace_to_mw(
        has_replace_profile=True, is_outside_visible=False,
        active_device="cpu", integrator_name="path_tracer") is True


def test_route_gpu_replace_keeps_integrator(monkeypatch):
    addon = _addon(monkeypatch)
    # GPU: do NOT route to the naive MW oracle (would render darker); degradation
    # report notes the approximation instead.
    assert addon._route_replace_to_mw(
        has_replace_profile=True, is_outside_visible=False,
        active_device="gpu", integrator_name="path_tracer") is False


def test_route_no_replace_profile_keeps_integrator(monkeypatch):
    addon = _addon(monkeypatch)
    assert addon._route_replace_to_mw(
        has_replace_profile=False, is_outside_visible=False,
        active_device="cpu", integrator_name="path_tracer") is False


def test_route_outside_visible_already_mw(monkeypatch):
    addon = _addon(monkeypatch)
    # Non-visible band already selects the MW integrator upstream; no override.
    assert addon._route_replace_to_mw(
        has_replace_profile=True, is_outside_visible=True,
        active_device="cpu", integrator_name="multiwavelength_path_tracer") is False


def test_route_already_mw_no_double_switch(monkeypatch):
    addon = _addon(monkeypatch)
    assert addon._route_replace_to_mw(
        has_replace_profile=True, is_outside_visible=False,
        active_device="cpu", integrator_name="multiwavelength_path_tracer") is False

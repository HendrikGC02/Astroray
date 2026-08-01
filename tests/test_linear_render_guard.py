"""pkg166 — self-tests for the furnace/energy linear-render guard.

These test the guard itself. Their own names deliberately contain neither
"furnace" nor "energy", so the conftest autouse fixture is a no-op for them and
they can exercise `linear_render_guard` directly.
"""
from __future__ import annotations

import pytest

from runtime_setup import configure_test_imports

configure_test_imports()

from _linear_render_guard import linear_render_guard, name_matches, renders_gamma

try:
    import astroray  # noqa: E402
    AVAILABLE = True
except ImportError:
    AVAILABLE = False


def test_name_matches_selects_furnace_and_energy():
    assert name_matches("test_dielectric_glass_furnace_cpu")
    assert name_matches("test_disney_energy_conservation")
    assert name_matches("test_metal_white_furnace_conserves_energy[0.3]")
    assert not name_matches("test_glass_render")
    assert not name_matches("test_scaled_mesh_visible")


def test_renders_gamma_reads_the_apply_gamma_argument():
    # apply_gamma defaults to True when omitted (the whole reason this guard exists)
    assert renders_gamma((64, 32), {}) is True
    assert renders_gamma((64, 32, None), {}) is True
    # explicit positional 4th arg
    assert renders_gamma((64, 32, None, True), {}) is True
    assert renders_gamma((64, 32, None, False), {}) is False
    # explicit keyword
    assert renders_gamma((64, 32), {"apply_gamma": True}) is True
    assert renders_gamma((64, 32), {"apply_gamma": False}) is False


@pytest.mark.skipif(not AVAILABLE, reason="astroray not built")
def test_guard_fires_on_gamma_and_is_silent_on_linear():
    """The guard must FAIL a gamma render and PASS a linear one. A lightweight
    stub stands in for the real render so this needs no GPU: the guard's
    assertion runs before it ever delegates to the wrapped render."""
    renderer_cls = astroray.Renderer
    real_render = renderer_cls.render
    renderer_cls.render = lambda self, *a, **k: "rendered"  # noqa: E731
    try:
        with linear_render_guard("test_fake_furnace"):
            r = astroray.Renderer()
            # Default gamma -> must fire.
            with pytest.raises(AssertionError, match="apply_gamma"):
                r.render(4, 2)
            # Explicit gamma -> must fire.
            with pytest.raises(AssertionError, match="apply_gamma"):
                r.render(4, 2, None, True)
            # Linear -> must be silent (delegates to the stub).
            assert r.render(4, 2, None, False) == "rendered"
            assert r.render(4, 2, apply_gamma=False) == "rendered"
    finally:
        renderer_cls.render = real_render


@pytest.mark.skipif(not AVAILABLE, reason="astroray not built")
def test_guard_restores_render_on_exit():
    renderer_cls = astroray.Renderer
    before = renderer_cls.render
    with linear_render_guard("test_fake_furnace"):
        assert renderer_cls.render is not before
    assert renderer_cls.render is before

"""pkg166 — furnace/energy tests must render LINEAR, enforced at test time.

`Renderer.render(...)`'s `apply_gamma` argument defaults to True, which clamps
output to [0, 1]. A furnace/energy test rendered through gamma can therefore
only ever detect energy LOSS, never GAIN — structurally, not statistically:
pkg160's white-metal conductor created energy up to 4.139 in linear (18,338 of
27,648 pixels above 1.0), yet every gamma-rendered furnace suite read a max of
exactly 1.000000 and stayed green (memory `gamma-furnace-cannot-detect-energy-gain`,
PR #527, 2026-07-26). pkg120 later ADDED energy the same way and sailed through
every shipped furnace suite; only its own purpose-built linear gate caught it
(PR #534 sweep, 2026-08-02).

This module supplies the guard the conftest autouse fixture installs for any
test whose name matches `*furnace*` or `*energy*`: it wraps `Renderer.render`
and FAILS at call time if that render requests gamma. It is not a convention
note — it fires.
"""
from __future__ import annotations

import contextlib

# A test whose name contains any of these renders radiometric quantities where
# the gamma clamp would hide energy gain. Matched as a substring of the pytest
# node name (so parametrized ids like `...[1.5]` still match).
NAME_TAGS = ("furnace", "energy")


def name_matches(node_name: str) -> bool:
    return any(tag in node_name for tag in NAME_TAGS)


def renders_gamma(args: tuple, kwargs: dict) -> bool:
    """True if this Renderer.render(...) call would apply gamma.

    Signature (pybind): render(samples_per_pixel, max_depth,
    progress_callback=None, apply_gamma=True, ...). `args` excludes `self`.
    """
    if "apply_gamma" in kwargs:
        return bool(kwargs["apply_gamma"])
    if len(args) >= 4:  # samples, max_depth, progress_callback, apply_gamma
        return bool(args[3])
    return True  # apply_gamma defaults to True


@contextlib.contextmanager
def linear_render_guard(node_name: str):
    """Wrap `astroray.Renderer.render` so a furnace/energy test that renders
    gamma raises AssertionError at the render call. No-op if astroray is not
    importable (the whole suite is skipped in that case)."""
    try:
        import astroray
    except ImportError:
        yield
        return

    renderer_cls = astroray.Renderer
    original_render = renderer_cls.render

    def guarded_render(self, *args, **kwargs):
        assert not renders_gamma(args, kwargs), (
            f"furnace/energy test '{node_name}' called render(...) with "
            "apply_gamma=True. Furnace/energy tests MUST render linear "
            "(apply_gamma=False): gamma clamps to [0, 1], so a gamma furnace "
            "detects energy LOSS but never GAIN. pkg160's conductor read 4.139 "
            "in linear yet 1.000000 through gamma (pkg166; memory "
            "gamma-furnace-cannot-detect-energy-gain)."
        )
        return original_render(self, *args, **kwargs)

    renderer_cls.render = guarded_render
    try:
        yield
    finally:
        renderer_cls.render = original_render

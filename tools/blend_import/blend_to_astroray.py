"""Public entry point: ``import_blend(path) → astroray.Renderer``.

The spec calls the return type ``astroray.Scene`` as paraphrase; the actual
public API on this codebase is ``astroray.Renderer`` (see
:mod:`blender_addon.__init__` and :mod:`scripts.run_parity` for the existing
Cornell scene construction). The renderer is what downstream pipelines
consume, so populating one matches the intent.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .reader import BlendFile
from .scene_builder import BlendImportWarning, build_scene


def import_blend(path: str | Path,
                 *,
                 strict: bool = False,
                 renderer: Any | None = None,
                 width: int | None = None,
                 height: int | None = None,
                 on_warning: Callable[[str], None] | None = None,
                 stats_out: dict | None = None) -> Any:
    """Build an Astroray Renderer from a .blend file at *path*.

    Parameters
    ----------
    path
        Path to a .blend file (compressed or uncompressed).
    strict
        If True, raise on any parity-scope-unsupported feature instead of
        warning. The pkg71 harness passes False.
    renderer
        Optional pre-constructed renderer to populate. If None, a fresh
        ``astroray.Renderer`` is created (deferred import — only required when
        the caller doesn't bring its own).
    width, height
        Render resolution. If both are provided we call
        ``renderer.setup_camera`` once the scene's camera intrinsics are read.
        Otherwise the caller is responsible for calling setup_camera
        separately (camera intrinsics are available in the returned stats dict
        under the ``"cam_intrinsics"`` key).
    stats_out
        Optional dict; if provided, populated with import statistics
        (objects/triangles/lights/materials counts + cam_intrinsics). This is
        the preferred way to retrieve stats — the renderer-attribute path is
        kept best-effort for the _FakeRenderer test stub but is impossible on
        the real pybind11 ``astroray.Renderer`` (no ``__dict__``).

    Returns
    -------
    The populated renderer.
    """
    if renderer is None:
        import astroray  # deferred — lets unit tests import this module without astroray
        renderer = astroray.Renderer()

    blend = BlendFile.from_path(path)
    stats = build_scene(blend, renderer, strict=strict, on_warning=on_warning)

    intrinsics = stats.get("cam_intrinsics")
    if intrinsics and width and height and hasattr(renderer, "setup_camera"):
        renderer.setup_camera(
            intrinsics["eye"], intrinsics["target"], intrinsics["up"],
            intrinsics["fov"], width / height, intrinsics["near"],
            intrinsics["far"], width, height,
        )

    if stats_out is not None:
        stats_out.clear()
        stats_out.update(stats)

    # Best-effort: stash stats on the renderer for the _FakeRenderer stub
    # (has __dict__) and any pybind11 Renderer that opted into py::dynamic_attr().
    # The real astroray.Renderer has no __dict__, so this silently no-ops there;
    # callers who need stats from the real binding must pass ``stats_out``.
    try:
        renderer._blend_import_stats = stats
    except AttributeError:
        pass
    return renderer


__all__ = ["import_blend", "BlendImportWarning"]

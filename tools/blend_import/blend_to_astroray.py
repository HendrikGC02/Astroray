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
                 on_warning: Callable[[str], None] | None = None) -> Any:
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
        Otherwise the caller is responsible for calling setup_camera with
        ``import_blend_camera_intrinsics`` (returned via the renderer's
        attached ``_cam_intrinsics`` attribute, see below).

    Returns
    -------
    The populated renderer. If the file's camera was decoded, the renderer
    carries an attribute ``_cam_intrinsics`` (a dict with
    eye/target/up/fov/aspect/near/far) so the caller can finish setup_camera
    once a final width/height is known.
    """
    if renderer is None:
        import astroray  # deferred — lets unit tests import this module without astroray
        renderer = astroray.Renderer()

    blend = BlendFile.from_path(path)
    stats = build_scene(blend, renderer, strict=strict, on_warning=on_warning)

    intrinsics = getattr(renderer, "_cam_intrinsics", None)
    if intrinsics and width and height and hasattr(renderer, "setup_camera"):
        renderer.setup_camera(
            intrinsics["eye"], intrinsics["target"], intrinsics["up"],
            intrinsics["fov"], width / height, intrinsics["near"],
            intrinsics["far"], width, height,
        )

    renderer._blend_import_stats = stats
    return renderer


__all__ = ["import_blend", "BlendImportWarning"]

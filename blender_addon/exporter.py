"""Astroray viewport scene exporter and per-domain caches.

Architectural pattern reference (NO code copied):
  - BlendLuxCore export/__init__.py (Exporter, ObjectCache2, MaterialCache,
    CameraCache, WorldCache, Change bitflags)
  - Radeon ProRender addon (view_update → sync_update, datablock-type dispatch)

This module owns the high-level coordination of scene sync and depsgraph-driven
incremental dispatch. The RenderEngine subclass delegates viewport-related calls
here, keeping it a thin shim that focuses on Blender's RenderEngine protocol.

Design:
  - Per-domain cache objects (Camera, Objects, Materials, Lights, World, Config)
    expose `diff(depsgraph) -> bool`.
  - Aggregator ORs `Change` bitflags and applies only the diff.
  - Behavior is IDENTICAL to pkg56 (refactor, not feature change).
  - Datablock-grained granularity (no per-property minimal diffs — RH4 non-goal).

pkg116: This is Phase 1 of the refactor. The Exporter coordinates view_update/
view_draw by calling back into RenderEngine methods (which remain on the engine
for backward compatibility with tests). Future phases can migrate more logic here.
"""

import time
from enum import IntFlag


class Change(IntFlag):
    """Bitflags for scene-change classification. ORed together to represent
    a set of domains that need re-upload."""
    NONE = 0
    ENVIRONMENT = 1 << 0
    MATERIALS = 1 << 1
    LIGHTS = 1 << 2
    GEOMETRY = 1 << 3
    TRANSFORMS = 1 << 4
    BACKEND_CONFIG = 1 << 5
    ACCUMULATION_ONLY = 1 << 6


class Exporter:
    """Viewport scene exporter coordinator. Delegates view_update / view_draw
    coordination while calling back into RenderEngine's implementation methods.

    pkg116 Phase 1: The implementation methods (_apply_depsgraph_updates,
    _sync_viewport_scene, etc.) remain on RenderEngine for backward compatibility
    with tests that call them directly. The Exporter owns the coordination flow.
    """

    def __init__(self, engine):
        """
        Args:
            engine: CustomRaytracerRenderEngine instance
        """
        self.engine = engine

    def view_update(self, context, depsgraph):
        """Coordinate scene sync and render on depsgraph update.
        Delegates to engine methods."""
        # Delegate to the engine's existing implementation
        self.engine._view_update_impl(context, depsgraph)

    def view_draw(self, context, depsgraph):
        """Coordinate camera-change detection and render on draw.
        Delegates to engine methods."""
        # Delegate to the engine's existing implementation
        self.engine._view_draw_impl(context, depsgraph)


# Per-domain cache stubs (pkg116 Phase 1: structure only, no diff logic yet)

class CameraCache:
    """Tracks camera state and detects changes."""
    def __init__(self):
        self._last_hash = None

    def diff(self, depsgraph) -> bool:
        """Check if camera changed. Returns True if upload needed."""
        # pkg116 Phase 1: stub — real implementation in follow-up
        return False


class ObjectsCache:
    """Tracks object geometry and transforms."""
    def __init__(self):
        self._last_ids = set()

    def diff(self, depsgraph) -> bool:
        """Check if objects/geometry changed. Returns True if upload needed."""
        # pkg116 Phase 1: stub — real implementation in follow-up
        return False


class MaterialsCache:
    """Tracks material definitions."""
    def __init__(self):
        self._last_ids = set()

    def diff(self, depsgraph) -> bool:
        """Check if materials changed. Returns True if upload needed."""
        # pkg116 Phase 1: stub — real implementation in follow-up
        return False


class LightsCache:
    """Tracks light sources."""
    def __init__(self):
        self._last_ids = set()

    def diff(self, depsgraph) -> bool:
        """Check if lights changed. Returns True if upload needed."""
        # pkg116 Phase 1: stub — real implementation in follow-up
        return False


class WorldCache:
    """Tracks world/environment settings."""
    def __init__(self):
        self._last_hash = None

    def diff(self, depsgraph) -> bool:
        """Check if world changed. Returns True if upload needed."""
        # pkg116 Phase 1: stub — real implementation in follow-up
        return False


class ConfigCache:
    """Tracks backend configuration (device_mode, etc.)."""
    def __init__(self):
        self._last_config = {}

    def diff(self, depsgraph) -> bool:
        """Check if backend config changed. Returns True if reconfigure needed."""
        # pkg116 Phase 1: stub — real implementation in follow-up
        return False

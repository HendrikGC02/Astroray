"""pkg176 Stage 1 - native Blender/Cycles settings resolution (translation layer).

The exporter drives Astroray from Blender's NATIVE controls. For every setting
the Stage-0 contract (``blender_addon/settings_map.py``) marks ``direct`` and
that still has a shadowing ``custom_raytracer.*`` duplicate, this module resolves
the value the engine session should use:

  1. If the legacy custom duplicate is explicitly set in a saved ``.blend``
     (``is_property_set``), honour it for one release of back-compat and log a
     one-line deprecation/migration note per render.
  2. Otherwise read the native ``scene.cycles.*`` / ``scene.render.*`` property.
  3. If neither is available (a non-Cycles scene / a unit-test stub), leave the
     setting unresolved so behaviour is unchanged (the custom prop is used).

Semantic mismatches (table status ``approximated`` / ``dropped`` / ``astroray-only``)
are deliberately NOT resolved here - they stay custom-only until the engine
honours the native meaning (Stage 1 rule).

Route-2 discipline (dcc-integration-decision-2026-08 §6): this module is the
bpy-facing TRANSLATOR. It reads Blender datablocks and returns a plain read-only
view; it MUST NOT call the engine/session. The neutral values it produces are
handed to the exporter's existing ``renderer.*`` setter calls unchanged, so a
second host reads the same ``settings_map`` policy without importing this file.
"""

from __future__ import annotations

from settings_map import MAPPING


def _direct_aliases():
    """``(native_attr, custom_attr)`` pairs for every DIRECT-mapped setting that
    still has a shadowing ``custom_raytracer.*`` duplicate.

    Derived from the Stage-0 mapping table so ``settings_map.py`` stays the
    single source of truth: adding/removing a ``direct`` row with a custom
    duplicate there changes what the exporter reads here, with no edit needed.
    """
    pairs = []
    for entry in MAPPING:
        if entry.status == "direct" and entry.custom_prop.startswith("custom_raytracer."):
            native_attr = entry.cycles_path.split(".")[-1]
            custom_attr = entry.custom_prop.split(".")[-1]
            pairs.append((native_attr, custom_attr))
    return tuple(pairs)


# The 14 direct-mapped aliases (samples, preview_samples, the light-path depths,
# clamp direct/indirect, filter glossy, reflective/refractive caustics,
# use_denoising). See settings_map.py for the authoritative per-row rationale.
DIRECT_ALIASES = _direct_aliases()


def _custom_is_set(settings, custom_attr):
    """True if the legacy custom duplicate was explicitly written (a saved
    ``.blend`` override). Uses Blender's ``is_property_set`` (the canonical way
    to distinguish an authored value from a registered default); returns False
    under test stubs that don't provide it."""
    is_set = getattr(settings, "is_property_set", None)
    if not callable(is_set):
        return False
    try:
        return bool(is_set(custom_attr))
    except (TypeError, RuntimeError):
        return False


def _log_migration(report, custom_attr, native_attr):
    msg = (
        f"Astroray: legacy custom setting 'custom_raytracer.{custom_attr}' is set "
        f"and overrides native 'scene.cycles.{native_attr}'; this alias is "
        f"deprecated and will be removed - set the value in Blender's native "
        f"panel instead."
    )
    if report is not None:
        try:
            report({'WARNING'}, msg)
            return
        except (TypeError, RuntimeError):
            pass
    print(msg)


class ResolvedSettings:
    """Read-only view over ``scene.custom_raytracer`` where the DIRECT-mapped
    settings are replaced by their resolved native (or legacy-override) values.

    Every other attribute falls through to the underlying custom PropertyGroup,
    so ASTRORAY-ONLY / approximated / dropped settings keep their custom source
    unchanged. Attribute writes (e.g. ``last_render_stats``) reach the real
    settings so existing exporter code needs no changes."""

    __slots__ = ("_resolved", "_settings")

    def __init__(self, settings, resolved):
        object.__setattr__(self, "_settings", settings)
        object.__setattr__(self, "_resolved", resolved)

    def __getattr__(self, name):
        resolved = object.__getattribute__(self, "_resolved")
        if name in resolved:
            return resolved[name]
        return getattr(object.__getattribute__(self, "_settings"), name)

    def __setattr__(self, name, value):
        setattr(object.__getattribute__(self, "_settings"), name, value)


def resolve_native_settings(scene, report=None):
    """Resolve the DIRECT-mapped settings for ``scene`` and return a
    :class:`ResolvedSettings` view.

    ``report`` is an optional Blender ``self.report``-style callback used to
    surface the per-render deprecation note; pass ``None`` on hot paths
    (per-frame viewport draw) to keep resolution silent.
    """
    settings = scene.custom_raytracer
    cycles = getattr(scene, "cycles", None)
    resolved = {}
    for native_attr, custom_attr in DIRECT_ALIASES:
        if _custom_is_set(settings, custom_attr):
            _log_migration(report, custom_attr, native_attr)
            resolved[custom_attr] = getattr(settings, custom_attr)
        elif cycles is not None and hasattr(cycles, native_attr):
            resolved[custom_attr] = getattr(cycles, native_attr)
        # else: leave unresolved -> the proxy falls through to the custom prop,
        # keeping behaviour unchanged on non-Cycles / stub scenes.
    return ResolvedSettings(settings, resolved)

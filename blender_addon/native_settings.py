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


# pkg176 Stage 3: Blender camera factory defaults for the DROPPED-SILENT clip
# controls. We only warn when the user has moved a control OFF its default (i.e.
# is actually steering with it), so untouched scenes stay quiet -- a lightweight
# stand-in for the pkg119-C degradation policy that will generalise this later.
_CAM_CLIP_START_DEFAULT = 0.1
_CAM_CLIP_END_DEFAULT = 1000.0


def report_unsupported_native_controls(scene, report=None, emit=True):
    """Surface, once per render, the DROPPED-SILENT world/light/camera native
    controls the user has set to a render-affecting value the engine cannot
    honour yet.

    Every world/light/camera row the Stage-0 table (``settings_map.py``) marks
    ``dropped`` has a ``(none)`` neutral target: closing those gaps needs new
    engine capability (orthographic/panoramic cameras, near/far clipping,
    polygonal/anamorphic bokeh, per-light specular) and is a follow-up package
    per the pkg176 non-goal. Until then the steering wheel must not drop them
    SILENTLY (Stage 3 clause). This emits ONE consolidated ``WARNING`` per
    render naming the controls the user actually set.

    Route-2 discipline (dcc-integration-decision-2026-08 §6): this is a
    bpy-facing TRANSLATOR check -- it reads Blender datablocks and calls the
    Blender ``report`` UI callback ONLY; it never touches the engine/session.

    ``emit`` (pkg119 Phase C): when False the function only COLLECTS and returns
    the messages without surfacing them itself, so the caller can fold them into
    the consolidated per-render degradation report instead of emitting a second
    parallel warning. Default True keeps the standalone (headless / test) path
    unchanged.

    Returns the list of human-readable messages (also for tests / callers that
    want to log them differently).
    """
    messages = []

    cam = getattr(scene, "camera", None)
    cam_data = getattr(cam, "data", None) if cam is not None else None
    if cam_data is not None:
        cam_type = getattr(cam_data, "type", "PERSP")
        if cam_type != "PERSP":
            messages.append(
                f"camera projection '{cam_type}' (engine renders PERSP only; "
                f"ORTHO/PANO need new engine capability)"
            )
        clip_start = float(getattr(cam_data, "clip_start", _CAM_CLIP_START_DEFAULT))
        clip_end = float(getattr(cam_data, "clip_end", _CAM_CLIP_END_DEFAULT))
        if (abs(clip_start - _CAM_CLIP_START_DEFAULT) > 1e-6 or
                abs(clip_end - _CAM_CLIP_END_DEFAULT) > 1e-3):
            messages.append("camera clip_start/clip_end (near/far clipping ignored)")
        dof = getattr(cam_data, "dof", None)
        if dof is not None and getattr(dof, "use_dof", False):
            if int(getattr(dof, "aperture_blades", 0)) >= 3:
                messages.append(
                    "camera aperture_blades/aperture_rotation "
                    "(polygonal bokeh ignored; circular aperture only)"
                )
            if abs(float(getattr(dof, "aperture_ratio", 1.0)) - 1.0) > 1e-4:
                messages.append("camera aperture_ratio (anamorphic bokeh ignored)")

    spec_lights = []
    for obj in getattr(scene, "objects", []) or []:
        if getattr(obj, "type", None) != "LIGHT":
            continue
        light = getattr(obj, "data", None)
        if light is None:
            continue
        if abs(float(getattr(light, "specular_factor", 1.0)) - 1.0) > 1e-4:
            spec_lights.append(getattr(obj, "name", "<light>"))
    if spec_lights:
        messages.append(
            "light specular_factor on " + ", ".join(spec_lights) +
            " (per-light specular multiplier ignored)"
        )

    if messages and emit:
        summary = (
            "Astroray: these native controls are set but not honoured this "
            "render (see pkg176 Stage-0 mapping): " + "; ".join(messages)
        )
        if report is not None:
            try:
                report({'WARNING'}, summary)
            except (TypeError, RuntimeError):
                print(summary)
        else:
            print(summary)
    return messages


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

"""pkg176 Stage 4 - native Blender/Cycles settings resolution (translation layer).

The exporter drives Astroray from Blender's NATIVE controls. For every setting
the Stage-0 contract (``blender_addon/settings_map.py``) marks ``direct``, this
module resolves the value the engine session should use:

  1. Read the native ``scene.cycles.*`` / ``scene.render.*`` property.
  2. If it is unavailable (a non-Cycles scene - e.g. the Cycles add-on is
     disabled - or a unit-test stub), fall back to ``DIRECT_DEFAULTS`` (the
     engine defaults the retired custom props used to carry) so resolution never
     raises. A test stub that still carries the old custom attribute is left
     unresolved so the proxy falls through to it unchanged.

Stage 4 retired the ``custom_raytracer.*`` duplicates for the ``direct`` rows;
their one-release Stage-1 back-compat window is closed. An old ``.blend`` that
saved one of those props degrades gracefully - Blender drops the unknown member
on load and the native value (or default) is used; nothing hard-crashes.

Semantic mismatches (table status ``approximated`` / ``dropped`` / ``astroray-only``)
are deliberately NOT resolved here - they stay custom-only until the engine
honours the native meaning.

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


# pkg176 Stage 4: last-resort fallback for the retired direct aliases, used ONLY
# when the scene carries no ``cycles`` datablock (Cycles add-on disabled / a
# unit-test stub) so resolution never raises. Values mirror the engine defaults
# the removed custom props used to carry. Keyed by the (former) custom attr name.
DIRECT_DEFAULTS = {
    "samples": 2,
    "preview_samples": 1,
    "max_bounces": 10,
    "diffuse_bounces": 4,
    "glossy_bounces": 4,
    "transmission_bounces": 12,
    "volume_bounces": 0,
    "transparent_bounces": 8,
    "clamp_direct": 0.0,
    "clamp_indirect": 0.0,
    "filter_glossy": 0.0,
    "use_reflective_caustics": True,
    "use_refractive_caustics": True,
    "use_denoising": False,
}


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

    ``report`` is retained for call-site compatibility (final render / viewport
    paths pass ``self.report``) but is unused since Stage 4 removed the
    deprecation/migration note along with the custom aliases it warned about.
    """
    settings = scene.custom_raytracer
    cycles = getattr(scene, "cycles", None)
    resolved = {}
    for native_attr, custom_attr in DIRECT_ALIASES:
        if cycles is not None and hasattr(cycles, native_attr):
            resolved[custom_attr] = getattr(cycles, native_attr)
        elif not hasattr(settings, custom_attr):
            # Retired custom prop AND no native source (Cycles-less scene):
            # fall back to the engine default so nothing hard-crashes.
            resolved[custom_attr] = DIRECT_DEFAULTS[custom_attr]
        # else: settings still carries the attr (a pre-retirement object / test
        # stub) -> leave unresolved so the proxy falls through to it unchanged.
    return ResolvedSettings(settings, resolved)

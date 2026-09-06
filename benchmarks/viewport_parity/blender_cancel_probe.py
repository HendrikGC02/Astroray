# -*- coding: utf-8 -*-
"""pkg241 Phase 0 — final-render (F12) cancel full-stop-floor probe (in Blender).

Measures the CURRENT cancellation behaviour of the final-render path, whose
cooperative-cancel contract this package must fix.

Static evidence (not measured, cited in the design doc):
  * blender_addon/__init__.py:1209 — ``progress_callback`` calls
    ``self.test_break()`` after each tile and returns ``False`` on break.
  * module/blender_module.cpp:2220 — the ``std::function<void(float)>`` progress
    callback DISCARDS that Python return value; ``renderer.render`` (:2227) has
    no cancellation channel.
  * include/raytracer.h:4183 — ``if (progress) progress(...)`` is a void
    fire-and-forget after each tile.
Consequence: an ESC/cancel cannot take effect until the whole ``renderer.render``
call returns. The full-stop latency floor therefore equals the total render time.

``test_break``/``update_progress`` are RNA methods and cannot be monkeypatched
from Python, so this probe measures the achievable, honest number: the wall-time
of one F12 render at the given sample count = the current cancel full-stop floor.
The engine's ``render`` (a plain Python method, __init__.py:1161) is wrapped so
we time exactly the render call Blender drives, on the device set by the driver.

Config injected as ``_PKG241_CANCEL = {"samples": int}``. This request blocks
Blender's main thread for the whole render; the driver uses a long socket timeout.
"""

import sys
import time

import bpy

_CFG = dict(globals().get("_PKG241_CANCEL", {}))
SAMPLES = int(_CFG.get("samples", 32))

addon = sys.modules["bl_ext.user_default.astroray"]
eng_cls = addon.CustomRaytracerRenderEngine

scene = bpy.context.scene
try:
    scene.cycles.samples = SAMPLES
except Exception:
    pass

_timing = {"render_ms": None}
_orig_render = eng_cls.render


def _wrapped_render(self, depsgraph):
    t0 = time.perf_counter()
    try:
        return _orig_render(self, depsgraph)
    finally:
        _timing["render_ms"] = (time.perf_counter() - t0) * 1000.0


eng_cls.render = _wrapped_render
t0 = time.perf_counter()
try:
    bpy.ops.render.render(write_still=False)
finally:
    eng_cls.render = _orig_render
op_ms = (time.perf_counter() - t0) * 1000.0

result = {
    "device_mode": scene.custom_raytracer.device_mode,
    "samples": SAMPLES,
    "resolution": [scene.render.resolution_x, scene.render.resolution_y,
                   scene.render.resolution_percentage],
    # Both are the current cancel full-stop floor: an ESC after the render
    # starts cannot take effect until this whole window elapses.
    "render_ms": _timing["render_ms"],
    "op_render_ms": op_ms,
}

# -*- coding: utf-8 -*-
"""pkg241 Phase 0 — in-Blender viewport/cancellation latency recorder.

This module is *executed inside a live GUI Blender* (5.2) via the Blender Lab
``mcp`` socket bridge (localhost:9876). ``blender_driver.py --mode interactive``
reads this file, prepends a ``_PKG241_CONFIG`` dict, sends the source as one
``execute`` request, then polls ``driver_namespace["_pkg241"]["status"]()`` and
finally fetches ``["results"]``.

Why a timer + draw-handler instead of a modal operator: the bridge already runs
a main-thread timer, and driving the measurement from ``bpy.app.timers`` keeps
every timestamp on Blender's main thread — the same thread that blocks inside
``renderer.render()``. That is exactly what we want to measure: the wall-clock a
real user waits between a viewport edit and the first presented pixels, and the
window during which the main thread is unresponsive to a cancel/ESC.

Instrumentation points (all on the installed addon ``bl_ext.user_default.astroray``):
  * ``CustomRaytracerRenderEngine.view_update`` — depsgraph-driven edits
    (material changes) enter here (exporter.py:651).
  * ``CustomRaytracerRenderEngine.view_draw`` — camera moves (pan/zoom/orbit)
    enter here (exporter.py:724); also blits the cached texture.
  * ``Exporter.render_viewport_frame`` — the single blocking ``renderer.render``
    call (exporter.py:611) reached from both of the above.
  * A ``SpaceView3D`` POST_PIXEL draw handler timestamps each presented redraw.

Event dispatch is timestamped in the timer immediately before the scene edit +
``tag_redraw``; that is the fair zero point for a synthetic driver (it excludes
Blender's own input-event routing, which a socket-driven harness cannot exercise).

State lives in ``bpy.app.driver_namespace["_pkg241"]`` so it survives across the
separate bridge requests used to poll/fetch/teardown.
"""

import math
import time

import bpy
from mathutils import Quaternion


# ``_PKG241_CONFIG`` is injected by the driver before this source runs.
_CFG = dict(globals().get("_PKG241_CONFIG", {}))
EVENT_CLASS = _CFG.get("event_class", "camera")   # 'camera' | 'material'
N_EVENTS = int(_CFG.get("n", 50))
N_REPS = int(_CFG.get("reps", 3))
N_WARMUP = int(_CFG.get("warmup", 5))
ROTATE_DEG = float(_CFG.get("rotate_deg", 1.0))
TICK = float(_CFG.get("tick", 0.05))


def _find_v3d():
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type == "VIEW_3D":
                rv3d = area.spaces.active.region_3d
                return area, rv3d
    return None, None


def _tag_redraw():
    area, _ = _find_v3d()
    if area is not None:
        area.tag_redraw()


def _pick_material():
    """First Principled material with a user, preferred; else any principled."""
    fallback = None
    for mat in bpy.data.materials:
        if not mat.use_nodes:
            continue
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf is None:
            continue
        if mat.users > 0:
            return mat, bsdf
        fallback = fallback or (mat, bsdf)
    return fallback if fallback else (None, None)


def _install():
    import sys

    addon = sys.modules["bl_ext.user_default.astroray"]
    eng_cls = addon.CustomRaytracerRenderEngine
    exporter_cls = addon.exporter.Exporter
    dns = bpy.app.driver_namespace

    # Tear down any prior run cleanly (idempotent re-install).
    prev = dns.get("_pkg241")
    if prev is not None and prev.get("teardown"):
        try:
            prev["teardown"]()
        except Exception as exc:  # pragma: no cover - defensive
            print("[pkg241] prior teardown warn:", exc)

    area, rv3d = _find_v3d()
    mat, bsdf = _pick_material() if EVENT_CLASS == "material" else (None, None)

    S = {
        "cfg": {
            "event_class": EVENT_CLASS, "n": N_EVENTS, "reps": N_REPS,
            "warmup": N_WARMUP, "rotate_deg": ROTATE_DEG,
        },
        "draws": [],          # list[(entry, exit)] view_draw
        "updates": [],        # list[(entry, exit)] view_update
        "renders": [],        # list[(start, end)] render_viewport_frame
        "presents": [],       # list[float] draw-handler POST_PIXEL
        "events": [],         # per measured event dicts
        "phase": "run",
        "idx": 0,             # events dispatched so far (incl warmup)
        "total": N_WARMUP + N_REPS * N_EVENTS,
        "dispatch_ts": None,
        "awaiting": False,
        "done": False,
        "error": None,
        "orig": {
            "view_draw": eng_cls.view_draw,
            "view_update": eng_cls.view_update,
            "render_viewport_frame": exporter_cls.render_viewport_frame,
        },
        "handler": None,
        "material": mat.name if mat else None,
    }
    dns["_pkg241"] = S

    o_draw = S["orig"]["view_draw"]
    o_update = S["orig"]["view_update"]
    o_render = S["orig"]["render_viewport_frame"]

    def w_draw(self, context, depsgraph):
        e = time.perf_counter()
        try:
            return o_draw(self, context, depsgraph)
        finally:
            S["draws"].append((e, time.perf_counter()))

    def w_update(self, context, depsgraph):
        e = time.perf_counter()
        try:
            return o_update(self, context, depsgraph)
        finally:
            S["updates"].append((e, time.perf_counter()))

    def w_render(self, *a, **k):
        e = time.perf_counter()
        try:
            return o_render(self, *a, **k)
        finally:
            S["renders"].append((e, time.perf_counter()))

    eng_cls.view_draw = w_draw
    eng_cls.view_update = w_update
    exporter_cls.render_viewport_frame = w_render

    def present_cb():
        S["presents"].append(time.perf_counter())

    S["handler"] = bpy.types.SpaceView3D.draw_handler_add(
        present_cb, (), "WINDOW", "POST_PIXEL")

    def teardown():
        try:
            eng_cls.view_draw = S["orig"]["view_draw"]
            eng_cls.view_update = S["orig"]["view_update"]
            exporter_cls.render_viewport_frame = S["orig"]["render_viewport_frame"]
        except Exception:
            pass
        if S.get("handler") is not None:
            try:
                bpy.types.SpaceView3D.draw_handler_remove(S["handler"], "WINDOW")
            except Exception:
                pass
            S["handler"] = None

    S["teardown"] = teardown

    def status():
        return {
            "done": S["done"], "error": S["error"], "phase": S["phase"],
            "idx": S["idx"], "total": S["total"],
            "measured": len(S["events"]),
            "n_draws": len(S["draws"]), "n_presents": len(S["presents"]),
        }

    S["status"] = status

    def results():
        return {"cfg": S["cfg"], "material": S["material"],
                "events": S["events"], "done": S["done"], "error": S["error"]}

    S["results"] = results

    # --- event application -------------------------------------------------
    _mat_state = {"toggle": False}

    _cam_state = {"toggle": False}

    def apply_camera():
        # Oscillate +/- ROTATE_DEG around the start pose instead of accumulating,
        # so every event is an equivalent per-edit camera change at a fixed,
        # representative viewpoint. A cumulative sweep would orbit the view into
        # progressively heavier poses and confound edit->present latency with
        # scene-complexity variation across viewpoints.
        _cam_state["toggle"] = not _cam_state["toggle"]
        sign = 1.0 if _cam_state["toggle"] else -1.0
        _, rv = _find_v3d()
        q = Quaternion((0.0, 0.0, 1.0), math.radians(sign * ROTATE_DEG))
        rv.view_rotation = (q @ rv.view_rotation).normalized()

    def apply_material():
        _mat_state["toggle"] = not _mat_state["toggle"]
        v = 0.7 if _mat_state["toggle"] else 0.3
        # Base Color drives a clearly visible re-render; oscillate red channel.
        col = list(bsdf.inputs["Base Color"].default_value)
        col[0] = v
        bsdf.inputs["Base Color"].default_value = col

    apply = apply_material if EVENT_CLASS == "material" else apply_camera

    def _first_after(seq, ts, key=lambda x: x):
        for x in seq:
            if key(x) >= ts:
                return x
        return None

    def _record(ev_idx):
        dts = S["dispatch_ts"]
        draw = _first_after(S["draws"], dts, key=lambda t: t[0])
        upd = _first_after(S["updates"], dts, key=lambda t: t[0])
        rnd = _first_after(S["renders"], dts, key=lambda t: t[0])
        pres = _first_after(S["presents"], dts)
        # engine entry = earliest of the two handler entries after dispatch
        entries = [t[0] for t in (draw, upd) if t is not None]
        entry = min(entries) if entries else None
        row = {
            "idx": ev_idx,
            "warmup": ev_idx < N_WARMUP,
            "present_ms": (pres - dts) * 1000.0 if pres is not None else None,
            "entry_ms": (entry - dts) * 1000.0 if entry is not None else None,
            "render_ms": (rnd[1] - rnd[0]) * 1000.0 if rnd is not None else None,
            "block_ms": (max(draw[1] if draw else 0, upd[1] if upd else 0) - dts) * 1000.0,
        }
        S["events"].append(row)

    def timer():
        if S["done"]:
            return None
        try:
            if S["awaiting"]:
                # Need at least the first present after dispatch to close event.
                pres = _first_after(S["presents"], S["dispatch_ts"])
                if pres is None:
                    return TICK
                _record(S["idx"])
                S["awaiting"] = False
                S["idx"] += 1
                return TICK * 0.5
            if S["idx"] >= S["total"]:
                S["done"] = True
                S["phase"] = "done"
                return None
            S["dispatch_ts"] = time.perf_counter()
            apply()
            _tag_redraw()
            S["awaiting"] = True
            return TICK
        except Exception as exc:
            import traceback
            S["error"] = traceback.format_exc()
            S["done"] = True
            return None

    S["timer"] = timer
    bpy.app.timers.register(timer, first_interval=0.2)
    return {"setup": "ok", "event_class": EVENT_CLASS, "total": S["total"],
            "material": S["material"], "v3d": area is not None}


result = _install()

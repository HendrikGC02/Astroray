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
    # pkg241-p1d: camera events simulate viewport navigation by nudging
    # rv3d.view_rotation, which only moves the view matrix in free-perspective
    # (PERSP) view. If the saved .blend opens in CAMERA view the nudge is inert,
    # _camera_state_hash never changes, and every frame degrades to a full-res
    # full-upload SPP refinement (skip_upload requires camera_changed) — the
    # artifact that made the phase-1 "after" camera leg read as a ~4x regression
    # (start_divisor stuck at 1) while the PERSP "before" leg engaged the nav
    # divisor. Force PERSP so the camera-class measurement exercises real nav.
    if EVENT_CLASS == "camera" and rv3d is not None:
        rv3d.view_perspective = 'PERSP'
        try:
            rv3d.update()
        except Exception:
            pass
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
            # pkg241 Phase 1: snapshot the resolution divisor this chunk rendered
            # at (self is the Exporter instance) so the driver can report the
            # effective interactive-resolution divisor engaged per event class.
            div = getattr(self, "_viewport_render_divisor", None)
            S["renders"].append((e, time.perf_counter(), div))

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
        # pkg241-p1d: recompute the view matrix now so _camera_state_hash sees
        # the move on the very next view_draw (deterministic camera_changed),
        # rather than relying on redraw-timing to flush the lazy recompute.
        try:
            rv.update()
        except Exception:
            pass

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
        # pkg241 Phase 1 stale-frame / double-render guard: count render_viewport_frame
        # calls that both STARTED after dispatch and FINISHED at/before the first
        # present. A material edit's first present must be backed by >= 1 render for
        # THIS edit (renders_before_present == 0 => a stale pre-edit texture was
        # blitted). Present-first also collapses the material double-render from 2 to 1.
        rbp = None
        if pres is not None:
            rbp = sum(1 for r in S["renders"]
                      if r[0] >= dts and r[1] <= pres)
        row = {
            "idx": ev_idx,
            "warmup": ev_idx < N_WARMUP,
            "present_ms": (pres - dts) * 1000.0 if pres is not None else None,
            "entry_ms": (entry - dts) * 1000.0 if entry is not None else None,
            "render_ms": (rnd[1] - rnd[0]) * 1000.0 if rnd is not None else None,
            "block_ms": (max(draw[1] if draw else 0, upd[1] if upd else 0) - dts) * 1000.0,
            "renders_before_present": rbp,
            # divisor of the first chunk rendered for this edit = the coarse
            # starting divisor the interactive-resolution budget engaged.
            "start_divisor": (rnd[2] if rnd is not None and len(rnd) > 2 else None),
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


# ---------------------------------------------------------------------------
# pkg241 Phase 2 — UI event latency while a viewport chunk renders.
#
# Different question from _install() above: not "how long from one edit to
# its presented frame" but "while chunk renders keep happening, how promptly
# can the main thread service anything else" (a UI event, a timer, a redraw).
# A bpy.app.timers callback registered at a fine interval (TICK_S, default
# 5 ms) is itself serviced by exactly the same single-threaded main loop that
# a mouse click or panel redraw would be, so the wall-clock gap between two
# consecutive invocations of that callback is a direct, code-simple proxy for
# "how long would the UI have been unresponsive here" — no synthetic OS input
# injection required.
#
# Idle-window throttling (the Phase 0 finding: bpy.app.timers fire slowly
# while the GUI is idle/unfocused) is avoided structurally, not by injecting
# mouse/keyboard events: every tick's callback body itself dispatches the next
# camera/material edit and calls area.tag_redraw() (the same tag_redraw the
# Phase 0/1 recorder already uses to force activity) before returning, so the
# main thread is never left with nothing scheduled — it is always either
# running this callback or blocked inside the render/redraw that callback
# just triggered. There is therefore no idle gap for Blender's own idle-sleep
# backoff to engage. Warmup ticks (first WARMUP_S seconds) are discarded so
# scene-open/shading-toggle settling never pollutes the measured gaps.
#
# Cross-check against a timer-throttling artifact (as opposed to real
# render-caused blocking): (1) the POST_PIXEL draw-handler timestamp stream
# (`presents`) is recorded throughout — if ticks show large gaps but no
# presents/renders are happening nearby, that would indicate a stalled
# recorder rather than an actively-refining viewport; (2) when the Astroray
# addon is the active engine, `Exporter.render_viewport_frame` is wrapped the
# same way _install() wraps it, so the driver can compute the fraction of
# wall time actually spent inside a render() call and compare it against the
# fraction implied by tick-gap excess — the two should agree when gaps are
# real render blocking. Cycles has no Python-level view_update/view_draw hook
# (it is a native C++ RenderEngine, not a bpy_types.RenderEngine subclass), so
# for a Cycles leg the tick-gap statistic is the whole measurement — which is
# exactly the point: Cycles is expected to keep gaps near TICK_S because its
# viewport session renders off the main thread and view_draw only blits.
def _install_ui_latency():
    import sys

    # The addon may be registered either through the Extensions Platform
    # (bl_ext.user_default.astroray, the normal user-profile install Phase
    # 0/1 used) or via a direct sys.path import as the plain top-level
    # "blender_addon" package (pkg241 Phase 2's isolated-profile bootstrap,
    # scripts/dev/pkg241p2_isolated_bootstrap.py -- a fresh BLENDER_USER_
    # RESOURCES profile has no extension repository registered, so bl_ext.*
    # never resolves there). Try both so this hook works under either.
    addon = (sys.modules.get("bl_ext.user_default.astroray")
             or sys.modules.get("blender_addon"))
    exporter_cls = addon.exporter.Exporter if addon is not None else None
    dns = bpy.app.driver_namespace

    prev = dns.get("_pkg241")
    if prev is not None and prev.get("teardown"):
        try:
            prev["teardown"]()
        except Exception as exc:  # pragma: no cover - defensive
            print("[pkg241] prior teardown warn:", exc)

    area, rv3d = _find_v3d()
    if rv3d is not None:
        rv3d.view_perspective = 'PERSP'
        try:
            rv3d.update()
        except Exception:
            pass
    mat, bsdf = _pick_material()

    duration_s = float(_CFG.get("duration_s", 10.0))
    warmup_s = float(_CFG.get("warmup_s", 2.0))
    tick_s = float(_CFG.get("tick_s", 0.005))

    S = {
        "cfg": {"event_class": "ui_latency", "duration_s": duration_s,
                "warmup_s": warmup_s, "tick_s": tick_s},
        "ticks": [],       # perf_counter() at every timer invocation (post-warmup)
        "renders": [],     # (start, end) render_viewport_frame calls (astroray only)
        "presents": [],    # POST_PIXEL draw-handler timestamps
        "phase": "warmup",
        "t_phase_start": None,
        "done": False,
        "error": None,
        "orig": {},
        "handler": None,
        "material": mat.name if mat else None,
        "engine_has_hooks": exporter_cls is not None,
        # pkg241 Phase 2 A2 spike (§9): generation-tagged lifeline events, filled
        # by the exporter's _spike_event_sink (worker + main thread) when
        # ASTRORAY_VIEWPORT_WORKER=1. Empty on the synchronous path.
        "events": [],           # (name, generation, t_perf_counter, epoch, extra)
        "blitted_gens": set(),  # generations that already produced a first_blit
        "pending_blit_gen": None,
    }
    dns["_pkg241"] = S

    # pkg241 Phase 2 A2 spike (§9 event schema): install the exporter event sink
    # so the off-thread worker's generation-tagged events are captured. list
    # .append is atomic under the GIL, so worker-thread and main-thread appends
    # are safe. The sink also derives the per-generation `first_blit`: the first
    # POST_PIXEL present after a `texture_upload_end` presents that generation.
    exporter_mod = getattr(addon, "exporter", None) if addon is not None else None
    S["exporter_mod"] = exporter_mod
    if exporter_mod is not None:
        S["orig_event_sink"] = getattr(exporter_mod, "_spike_event_sink", None)

        def _event_sink(name, generation, t, epoch, extra):
            S["events"].append((name, generation, t, epoch, dict(extra)))
            if name == "texture_upload_end":
                S["pending_blit_gen"] = generation

        exporter_mod._spike_event_sink = _event_sink

    if exporter_cls is not None:
        o_render = exporter_cls.render_viewport_frame
        S["orig"]["render_viewport_frame"] = o_render

        def w_render(self, *a, **k):
            e = time.perf_counter()
            try:
                return o_render(self, *a, **k)
            finally:
                S["renders"].append((e, time.perf_counter()))

        exporter_cls.render_viewport_frame = w_render

    def present_cb():
        now = time.perf_counter()
        S["presents"].append(now)
        # pkg241 Phase 2 A2 spike (§9): the first present after a texture upload is
        # the first_blit for that generation — the end of the request->blit chain.
        g = S.get("pending_blit_gen")
        if g is not None and g not in S["blitted_gens"]:
            S["blitted_gens"].add(g)
            S["pending_blit_gen"] = None
            S["events"].append(("first_blit", g, now, 0, {}))

    S["handler"] = bpy.types.SpaceView3D.draw_handler_add(
        present_cb, (), "WINDOW", "POST_PIXEL")

    def teardown():
        if exporter_cls is not None and "render_viewport_frame" in S["orig"]:
            try:
                exporter_cls.render_viewport_frame = S["orig"]["render_viewport_frame"]
            except Exception:
                pass
        # pkg241 Phase 2 A2 spike: restore the exporter event sink.
        em = S.get("exporter_mod")
        if em is not None:
            try:
                em._spike_event_sink = S.get("orig_event_sink")
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
        return {"done": S["done"], "error": S["error"], "phase": S["phase"],
                "n_ticks": len(S["ticks"]), "n_renders": len(S["renders"]),
                "n_presents": len(S["presents"])}

    S["status"] = status

    def results():
        return {"cfg": S["cfg"], "material": S["material"],
                "ticks": S["ticks"], "renders": S["renders"],
                "presents": S["presents"], "done": S["done"],
                "error": S["error"], "engine_has_hooks": S["engine_has_hooks"],
                # pkg241 Phase 2 A2 spike (§9): generation-tagged lifeline events.
                "events": S["events"]}

    S["results"] = results

    _mat_state = {"toggle": False}
    _cam_state = {"toggle": False}
    _drive_idx = {"n": 0}
    _last_edit = {"t": None}
    # Cap the edit-dispatch rate at ~50 Hz (comfortably above the 30 fps/33 ms
    # target this metric is graded against). Astroray chunks already take
    # 150+ ms so this never throttles it in practice (dispatch is already
    # paced far slower by the render blocking the main thread); it mainly
    # bounds Cycles, which would otherwise be driven at whatever rate the
    # (unblocked) ticker can reach, closer to a real user's input rate.
    _MIN_EDIT_INTERVAL_S = 0.02

    def _drive_edit():
        # Alternate camera / material edits so both event classes contribute
        # continuous chunk-render pressure (Phase 0/1: a material edit costs
        # ~2x a camera edit) — the owner's complaint is not class-specific.
        now = time.perf_counter()
        if (_last_edit["t"] is not None
                and now - _last_edit["t"] < _MIN_EDIT_INTERVAL_S):
            return
        _last_edit["t"] = now
        _drive_idx["n"] += 1
        if _drive_idx["n"] % 2 == 0 and bsdf is not None:
            _mat_state["toggle"] = not _mat_state["toggle"]
            v = 0.7 if _mat_state["toggle"] else 0.3
            col = list(bsdf.inputs["Base Color"].default_value)
            col[0] = v
            bsdf.inputs["Base Color"].default_value = col
        else:
            _cam_state["toggle"] = not _cam_state["toggle"]
            sign = 1.0 if _cam_state["toggle"] else -1.0
            _, rv = _find_v3d()
            if rv is not None:
                q = Quaternion((0.0, 0.0, 1.0), math.radians(sign * ROTATE_DEG))
                rv.view_rotation = (q @ rv.view_rotation).normalized()
                try:
                    rv.update()
                except Exception:
                    pass
        _tag_redraw()

    def timer():
        if S["done"]:
            return None
        now = time.perf_counter()
        try:
            if S["t_phase_start"] is None:
                S["t_phase_start"] = now
            if S["phase"] == "warmup":
                if now - S["t_phase_start"] >= warmup_s:
                    # Transition tick: flip phase and reset the window, but
                    # don't record this tick itself as a measured sample —
                    # the next tick is the first one timed against the fresh
                    # "run" start, so no stale-elapsed comparison is possible.
                    S["phase"] = "run"
                    S["t_phase_start"] = now
                    S["ticks"] = []
                    S["renders"] = []
                    S["presents"] = []
                    # pkg241 Phase 2 A2 spike: drop warmup lifeline events too.
                    S["events"] = []
                    S["blitted_gens"] = set()
                    S["pending_blit_gen"] = None
                _drive_edit()
                return tick_s
            # phase == "run"
            S["ticks"].append(now)
            if now - S["t_phase_start"] >= duration_s:
                S["done"] = True
                S["phase"] = "done"
                return None
            _drive_edit()
            return tick_s
        except Exception:
            import traceback
            S["error"] = traceback.format_exc()
            S["done"] = True
            return None

    S["timer"] = timer
    bpy.app.timers.register(timer, first_interval=0.05)
    return {"setup": "ok", "event_class": "ui_latency",
            "duration_s": duration_s, "warmup_s": warmup_s, "tick_s": tick_s,
            "material": S["material"], "v3d": area is not None,
            "engine_has_hooks": S["engine_has_hooks"]}


result = (_install_ui_latency() if EVENT_CLASS == "ui_latency" else _install())

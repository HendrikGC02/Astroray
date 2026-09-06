"""Blender startup script: bring up the MCP bridge so agents can drive Blender.

Run by scripts/dev/launch_blender_mcp.ps1 as
    blender.exe --python scripts/dev/blender_mcp_autostart.py

The bridge is the official Blender Lab ``mcp`` extension
(``bl_ext.user_default.mcp``; null-byte-delimited JSON on localhost:9876).
It is what the Claude "Blender" MCP server and Codex's ``blender_mcp`` command
talk to. The community ``blender_mcp`` add-on (ahujasid) also defaults to 9876;
it is NOT started here so the two never collide.

The script enables the extension, pins its port to ASTRORAY_MCP_PORT (default
9876), turns on its autostart preference, and starts the server from a deferred
timer once the UI exists. It never modifies the .blend.
"""
import os
import sys

import bpy

PORT = int(os.environ.get("ASTRORAY_MCP_PORT", "9876"))
PID_FILE = os.environ.get("ASTRORAY_BLENDER_PID_FILE")
EXT_MODULE = "bl_ext.user_default.mcp"


def _log(msg: str) -> None:
    print(f"[blender_mcp_autostart] {msg}", flush=True)


def _enable(module: str) -> bool:
    try:
        bpy.ops.preferences.addon_enable(module=module)
        return True
    except Exception as ex:  # noqa: BLE001 - report, don't crash Blender startup
        _log(f"could not enable {module}: {ex}")
        return False


def _prefs():
    addon = bpy.context.preferences.addons.get(EXT_MODULE)
    return getattr(addon, "preferences", None) if addon else None


def _start_bridge() -> float | None:
    prefs = _prefs()
    if prefs is None:
        _log("mcp extension preferences missing; retrying")
        return 2.0
    if hasattr(prefs, "port"):
        prefs.port = PORT
    if hasattr(prefs, "use_autostart"):
        prefs.use_autostart = True
    try:
        from bl_ext.user_default.mcp import mcp_to_blender_server as srv  # type: ignore

        if srv.is_running():
            _log(f"mcp bridge already running on {PORT}")
            return None
    except Exception:  # noqa: BLE001
        pass
    try:
        bpy.ops.blmcp.server_start()
        _log(f"mcp bridge started on port {PORT}")
    except Exception as ex:  # noqa: BLE001
        _log(f"server_start failed ({ex}); retrying in 3 s")
        return 3.0
    return None


def main() -> None:
    if PID_FILE:
        try:
            with open(PID_FILE, "w", encoding="ascii") as fh:
                fh.write(str(os.getpid()))
        except OSError as ex:
            _log(f"pid file not written: {ex}")
    _enable(EXT_MODULE)
    if not any(k.endswith(".astroray") for k in bpy.context.preferences.addons.keys()):
        _enable("bl_ext.user_default.astroray")
    bpy.app.timers.register(_start_bridge, first_interval=2.0, persistent=True)
    _log(f"Blender {bpy.app.version_string}, pid {os.getpid()}, argv={sys.argv[1:]}")


main()

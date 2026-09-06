"""Blender startup script: bring up the MCP bridges so agents can drive Blender.

Run by scripts/dev/launch_blender_mcp.ps1 as
    blender.exe --python scripts/dev/blender_mcp_autostart.py

Two MCP add-ons exist on this machine and BOTH default to port 9876:
  * community ``blender_mcp`` (ahujasid/blender-mcp; scripts/addons/blender_mcp.py) —
    this is what the ``uvx blender-mcp`` server (Claude's ``mcp__blender__*`` tools)
    connects to. It is started here on ASTRORAY_MCP_PORT (default 9876).
  * official Blender Lab ``mcp`` extension (user_default/mcp) — moved to
    ASTRORAY_MCP_PORT + 1 so the two never collide; its autostart is left as configured.

The community add-on's start operator needs a window context, so it is invoked
from a deferred timer once the UI is up. The script never modifies the .blend.
"""
import os
import sys

import bpy

PORT = int(os.environ.get("ASTRORAY_MCP_PORT", "9876"))
PID_FILE = os.environ.get("ASTRORAY_BLENDER_PID_FILE")


def _log(msg: str) -> None:
    print(f"[blender_mcp_autostart] {msg}", flush=True)


def _enable(module: str) -> bool:
    try:
        bpy.ops.preferences.addon_enable(module=module)
        return True
    except Exception as ex:  # noqa: BLE001 - report, don't crash Blender startup
        _log(f"could not enable {module}: {ex}")
        return False


def _configure_official_extension() -> None:
    """Keep the official 'mcp' extension off the community port."""
    for key, addon in bpy.context.preferences.addons.items():
        if key.endswith(".mcp") or key == "mcp":
            prefs = getattr(addon, "preferences", None)
            if prefs is not None and hasattr(prefs, "port"):
                if prefs.port == PORT:
                    prefs.port = PORT + 1
                    _log(f"official mcp extension moved to port {prefs.port}")
            return


def _start_community_server() -> float | None:
    scene = bpy.context.scene
    if scene is None or not hasattr(scene, "blendermcp_port"):
        _log("community blender_mcp scene props missing; retrying")
        return 1.0
    scene.blendermcp_port = PORT
    if getattr(scene, "blendermcp_server_running", False):
        _log(f"community server already running on {PORT}")
        return None
    try:
        bpy.ops.blendermcp.start_server()
        _log(f"community blender_mcp server started on port {PORT}")
    except Exception as ex:  # noqa: BLE001
        _log(f"start_server failed ({ex}); retrying in 2 s")
        return 2.0
    return None


def main() -> None:
    if PID_FILE:
        try:
            with open(PID_FILE, "w", encoding="ascii") as fh:
                fh.write(str(os.getpid()))
        except OSError as ex:
            _log(f"pid file not written: {ex}")
    _enable("blender_mcp")
    _configure_official_extension()
    # Astroray addon should already be installed as an extension; make sure it is on.
    for key in list(bpy.context.preferences.addons.keys()):
        if key.endswith(".astroray"):
            break
    else:
        _enable("bl_ext.user_default.astroray")
    bpy.app.timers.register(_start_community_server, first_interval=2.0, persistent=True)
    _log(f"Blender {bpy.app.version_string}, pid {os.getpid()}, argv={sys.argv[1:]}")


main()

"""Force the MCP bridge onto ASTRORAY_MCP_PORT (9877): enable, STOP any running
server (saved use_autostart may have bound 9876), set port, start on the target."""
import os, bpy
PORT = int(os.environ.get("ASTRORAY_MCP_PORT", "9877"))
PID_FILE = os.environ.get("ASTRORAY_BLENDER_PID_FILE")
EXT = "bl_ext.user_default.mcp"
def log(m): print(f"[mcp9877] {m}", flush=True)
def _prefs():
    a = bpy.context.preferences.addons.get(EXT)
    return getattr(a, "preferences", None) if a else None
def _rebind():
    p = _prefs()
    if p is None:
        log("prefs missing; retry"); return 2.0
    try:
        from bl_ext.user_default.mcp import mcp_to_blender_server as srv
        if srv.is_running():
            try: bpy.ops.blmcp.server_stop()
            except Exception as e: log(f"stop failed: {e}")
    except Exception as e:
        log(f"srv import: {e}")
    if hasattr(p, "port"): p.port = PORT
    if hasattr(p, "use_autostart"): p.use_autostart = True
    try:
        bpy.ops.blmcp.server_start(); log(f"started on {PORT}")
    except Exception as e:
        log(f"start failed ({e}); retry"); return 3.0
    return None
if PID_FILE:
    try: open(PID_FILE,"w").write(str(os.getpid()))
    except OSError: pass
try: bpy.ops.preferences.addon_enable(module=EXT)
except Exception as e: log(f"enable mcp: {e}")
if not any(k.endswith(".astroray") for k in bpy.context.preferences.addons.keys()):
    try: bpy.ops.preferences.addon_enable(module="bl_ext.user_default.astroray")
    except Exception as e: log(f"enable astroray: {e}")
bpy.app.timers.register(_rebind, first_interval=3.0, persistent=True)
log(f"Blender {bpy.app.version_string} pid {os.getpid()} target {PORT}")

"""pkg57 regression -- native Astroray shader nodes must register() cleanly
under real headless Blender when blender_addon/__init__.py is loaded the way
every headless test in this repo loads it: `importlib.util.spec_from_file_location`
directly on the file, with NO parent package.

Root cause (found via this lane): blender_addon/__init__.py's
`_import_astroray_nodes()` falls back to loading `nodes/__init__.py` the same
way (`spec_from_file_location` + `module_from_spec` + `exec_module`) whenever
the package-relative `from . import nodes` fails -- which it always does when
the addon itself has no parent package, i.e. every headless test in this repo.
`nodes/__init__.py` uses `from __future__ import annotations`, so its
`default_value: FloatVectorProperty(...)` class annotations are unevaluated
strings. Blender's `bpy.utils.register_class` resolves those strings via
`typing.get_type_hints()`, which looks up `sys.modules[cls.__module__]` for
the globalns to eval() them in. Because the fallback loader never inserted its
module into `sys.modules`, that lookup came up empty and `register_class`
raised `NameError: name 'FloatVectorProperty' is not defined` for every node
class (AstrorayOutputNode, SpectralProfile, SpectrumPreset, DrawnSpectrum,
BlackbodySpectrum, SellmeierGlass, IrUvResponse, NrcHint, plus both sockets).

blender_addon/__init__.py's register() swallows this (prints and continues),
so no existing test caught it -- the native nodes were silently absent from
every one of this project's own headless verification runs (test_issue762_*,
test_pkg271_*, etc.), while a normally-installed Blender extension (a real
package with a real `sys.modules` entry) was unaffected. Fixed by registering
the fallback-loaded module into `sys.modules` before `exec_module` runs (same
pattern already used by e.g. tests/test_780_addon_cpu_multithread.py).

This test fails loudly if the addon's own error box (`native_nodes_register_error`)
is set, and functionally probes registration by adding each node type to a
real shader node tree (with the Astroray engine active, matching the nodes'
own poll() gate) -- `bpy.types.<ClassName>` is not a reliable signal for
custom ShaderNode/NodeSocket subclasses on this Blender build, so a plain
getattr() check would miss real failures.

Skips cleanly without Blender or a prior staged CPU addon build.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
# ASTRORAY_ADDON_STAGE_DIR: point at another staged addon, same override as
# tests/test_pkg271_blender_volume_headless.py.
STAGE_DIR = Path(os.environ.get("ASTRORAY_ADDON_STAGE_DIR", str(REPO_ROOT / "dist" / "astroray")))

_SCRIPT = r"""
import sys
import importlib.util

addon_dir = sys.argv[sys.argv.index("--") + 1]
sys.path.insert(0, addon_dir)

import bpy

# Same standalone load every headless test in this repo uses: __init__.py has
# no parent package, so `from . import nodes` inside it must fail and take the
# fallback file-load path -- the exact path that triggered the NameError.
spec = importlib.util.spec_from_file_location(
    "astroray_addon_pkg57_hb", addon_dir + "/__init__.py")
addon = importlib.util.module_from_spec(spec)
spec.loader.exec_module(addon)
addon.register()

failures = []

if addon.native_nodes_register_error is not None:
    failures.append(
        "native_nodes_register_error is set: %r" % (addon.native_nodes_register_error,))

if not addon._ASTRORAY_NODES_AVAILABLE:
    failures.append("astroray_nodes module failed to import at all")

# bpy.types.<ClassName> is NOT a reliable registration signal for custom
# ShaderNode/NodeSocket subclasses on this Blender build -- getattr() misses
# them even when register_class() succeeded and the type is fully usable.
# The real, functional signal is whether the node type can be instantiated in
# a shader node tree (exactly how a user would hit this), gated on the
# Astroray engine being active (the nodes' own poll()).
scene = bpy.context.scene
scene.render.engine = 'CUSTOM_RAYTRACER'
mat = bpy.data.materials.new("Pkg57Probe")
mat.use_nodes = True
nt = mat.node_tree

for idname in (
    "AstrorayShaderNodeSellmeierGlass",
    "AstrorayOutputNode",
    "AstrorayShaderNodeSpectralProfile",
    "AstrorayShaderNodeBlackbodySpectrum",
):
    try:
        nt.nodes.new(idname)
    except RuntimeError as exc:
        failures.append(f"nodes.new({idname!r}) failed: {exc}")

if failures:
    print("FAILURES:")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("[pkg57-HB] ALL PASS")
sys.exit(0)
"""


def _find_blender():
    for candidate in (
        Path(r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"),
        Path(r"C:\Program Files\Blender Foundation\Blender 5.0\blender.exe"),
        Path(r"C:\Program Files\Blender Foundation\Blender 4.3\blender.exe"),
    ):
        if candidate.is_file():
            return candidate
    return None


BLENDER_EXE = _find_blender()


@pytest.mark.skipif(BLENDER_EXE is None, reason="Blender not found at a default install path")
def test_native_nodes_register_under_standalone_addon_load():
    if not (STAGE_DIR / "build_report.json").exists():
        pytest.skip("no prior staged build (run scripts/build/build_blender_addon.py)")

    tmp_script = Path(tempfile.mkstemp(suffix=".py", prefix="pkg57_hb_")[1])
    tmp_script.write_text(_SCRIPT, encoding="utf-8")

    cmd = [
        str(BLENDER_EXE), "--background", "--factory-startup",
        "--python", str(tmp_script), "--", str(STAGE_DIR),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
        print(result.stdout)
        if result.stderr:
            print("STDERR:", result.stderr, file=sys.stderr)
        assert result.returncode == 0, "native shader nodes failed to register headless (see output above)"
        assert "[pkg57-HB] ALL PASS" in result.stdout
    finally:
        try:
            tmp_script.unlink(missing_ok=True)
        except OSError:
            pass

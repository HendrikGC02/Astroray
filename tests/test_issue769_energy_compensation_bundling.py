"""#769 — the addon zip must bundle data/disney_compensation/*.bin.

Regression coverage for the north-star gate (f) scenario: install the
packaged addon on a machine with no source tree. Without the fix,
DisneyEnergyCompensationTables::load() (src/energy_compensation.cpp) falls
back to a compile-time ASTRORAY_DATA_DIR baked into the dev checkout and
fails silently, disabling every Disney/Principled multi-scatter compensation
term at once.

Two checks:
1. Pure-Python, no Blender: the staged addon dir (scripts/build/
   build_blender_addon.py's STAGE_DIR) contains every .bin file
   DisneyEnergyCompensationTables::load() reads, with the expected filename
   list *derived from src/energy_compensation.cpp* (regex over the
   readFloatTable(...) calls), not hand-copied. Skips cleanly if no build has
   been staged yet.
2. Real headless Blender: load the STAGED __init__.py (not the blender_addon/
   source tree) so the addon's own ASTRORAY_DATA_DIR override runs, then call
   astroray.energy_compensation_status() and assert loaded=True with
   data_directory pointing inside the staged addon. Skips cleanly without
   Blender or a prior staged build.
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
STAGE_DIR = REPO_ROOT / "dist" / "astroray"
ENERGY_COMP_SRC = REPO_ROOT / "src" / "energy_compensation.cpp"


def _expected_bin_filenames() -> list[str]:
    """Derive the table filenames DisneyEnergyCompensationTables::load()
    reads directly from its source, not a hand-maintained list."""
    text = ENERGY_COMP_SRC.read_text(encoding="utf-8")
    names = re.findall(r'readFloatTable\(dir / "([^"]+\.bin)"', text)
    assert names, "regex found no readFloatTable(...) calls in energy_compensation.cpp -- source shape changed"
    return names


def test_expected_filenames_match_source_data_dir():
    """Sanity: the derived list matches what ships in data/disney_compensation/
    today, so the regex itself hasn't drifted from the loader."""
    expected = set(_expected_bin_filenames())
    on_disk = {p.name for p in (REPO_ROOT / "data" / "disney_compensation").glob("*.bin")}
    assert expected == on_disk, f"derived != on-disk: derived-only={expected - on_disk}, disk-only={on_disk - expected}"


def test_staged_addon_bundles_every_compensation_table():
    if not (STAGE_DIR / "build_report.json").exists():
        pytest.skip("no prior staged build (run scripts/build/build_blender_addon.py)")
    staged_dir = STAGE_DIR / "data" / "disney_compensation"
    expected = _expected_bin_filenames()
    missing = [name for name in expected if not (staged_dir / name).is_file()]
    assert not missing, f"staged addon missing compensation tables: {missing} (expected under {staged_dir})"


# --------------------------------------------------------------------------- #
# Headless Blender: verify the staged addon actually loads the tables
# --------------------------------------------------------------------------- #

_SCRIPT = r"""
import sys
import importlib.util

addon_dir = sys.argv[sys.argv.index("--") + 1]
sys.path.insert(0, addon_dir)

import bpy
bpy.ops.wm.read_factory_settings(use_empty=True)

spec = importlib.util.spec_from_file_location(
    "astroray_addon_issue769_hb", addon_dir + "/__init__.py")
addon = importlib.util.module_from_spec(spec)
spec.loader.exec_module(addon)

failures = []

if not addon.RAYTRACER_AVAILABLE:
    failures.append("astroray module failed to import from the staged addon")
elif not hasattr(addon.astroray, "energy_compensation_status"):
    failures.append("astroray.energy_compensation_status binding missing (stale .pyd?)")
else:
    status = addon.astroray.energy_compensation_status()
    print("[issue769-HB] energy_compensation_status =", status)
    if not status.get("loaded"):
        failures.append("energy compensation tables not loaded from staged addon: %r" % (status,))
    data_dir = status.get("data_directory", "")
    if addon_dir not in data_dir:
        failures.append(
            "data_directory %r does not point inside the staged addon dir %r "
            "-- ASTRORAY_DATA_DIR override did not take effect" % (data_dir, addon_dir))

if failures:
    print("FAILURES:")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("[issue769-HB] ALL PASS")
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
def test_staged_addon_reports_compensation_tables_loaded_headless():
    if not (STAGE_DIR / "build_report.json").exists():
        pytest.skip("no prior staged build (run scripts/build/build_blender_addon.py)")

    tmp = Path(tempfile.mkstemp(suffix=".py", prefix="issue769_hb_")[1])
    tmp.write_text(_SCRIPT, encoding="utf-8")
    cmd = [
        str(BLENDER_EXE), "--background", "--factory-startup",
        "--python", str(tmp), "--", str(STAGE_DIR),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180, check=False)
        print(result.stdout)
        if result.stderr:
            print("STDERR:", result.stderr, file=sys.stderr)
        assert result.returncode == 0, "headless energy-compensation check failed (see output above)"
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass

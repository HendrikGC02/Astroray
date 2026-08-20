"""pkg175 - unit tests for the dev-loop guards + a local-host smoke gate.

The guard tests are pure (no GPU, no build, no Blender) and always run - they
are the real regression coverage for the four footguns. The smoke test drives
the full ``scripts/dev_addon.ps1 -Smoke -SkipBuild`` loop and SKIPS CLEANLY
when Blender, PowerShell, a prior staged build, or the GPU is absent, so CI
(which has none of those) stays green. This is a local-host gate.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import dev_loop_guards as g

BLENDER = Path("C:/Program Files/Blender Foundation/Blender 5.2/blender.exe")
STAGE_DIR = REPO_ROOT / "dist" / "astroray"


# --------------------------------------------------------------------------- #
# (a) stale-.pyd guard
# --------------------------------------------------------------------------- #

def test_pyd_is_stale_flags_old_module(tmp_path):
    pyd = tmp_path / "astroray.cp313-win_amd64.pyd"
    pyd.write_bytes(b"x")
    mtime = pyd.stat().st_mtime
    # HEAD committed AFTER the .pyd was built -> stale.
    stale, reported = g.pyd_is_stale(pyd, head_epoch=int(mtime) + 1000)
    assert stale is True
    assert reported == pytest.approx(mtime)


def test_pyd_is_stale_passes_fresh_module(tmp_path):
    pyd = tmp_path / "astroray.cp313-win_amd64.pyd"
    pyd.write_bytes(b"x")
    mtime = pyd.stat().st_mtime
    stale, _ = g.pyd_is_stale(pyd, head_epoch=int(mtime) - 1000)
    assert stale is False


def test_pyd_is_stale_missing_is_stale(tmp_path):
    stale, mtime = g.pyd_is_stale(tmp_path / "nope.pyd", head_epoch=0)
    assert stale is True
    assert mtime == 0.0


def test_find_built_pyd_picks_newest(tmp_path):
    old = tmp_path / "astroray.old.pyd"
    new = tmp_path / "astroray.new.pyd"
    old.write_bytes(b"o")
    new.write_bytes(b"n")
    os.utime(old, (1000, 1000))
    os.utime(new, (2000, 2000))
    assert g.find_built_pyd(tmp_path) == new


def test_find_built_pyd_none_when_absent(tmp_path):
    assert g.find_built_pyd(tmp_path) is None


# --------------------------------------------------------------------------- #
# (b) OpenMP-disabled guard
# --------------------------------------------------------------------------- #

def test_openmp_disabled_positive():
    assert g.openmp_disabled_in_flags(
        ["-DUSE_FAST_MATH=ON", "-DASTRORAY_DISABLE_OPENMP=ON"]) is True


def test_openmp_disabled_negative():
    assert g.openmp_disabled_in_flags(["-DUSE_FAST_MATH=ON"]) is False
    assert g.openmp_disabled_in_flags(
        ["-DASTRORAY_DISABLE_OPENMP=OFF"]) is False


def test_openmp_disabled_in_build_report(tmp_path):
    (tmp_path / "build_report.json").write_text(
        '{"cmake_flags": ["-DASTRORAY_DISABLE_OPENMP=ON"]}')
    assert g.openmp_disabled_in_build_report(tmp_path) is True

    (tmp_path / "build_report.json").write_text('{"cmake_flags": []}')
    assert g.openmp_disabled_in_build_report(tmp_path) is False

    with pytest.raises(FileNotFoundError):
        g.openmp_disabled_in_build_report(tmp_path / "missing")


# --------------------------------------------------------------------------- #
# (c) ADDON_FILES allow-list drift guard
# --------------------------------------------------------------------------- #

def test_addon_files_drift_detects_unlisted(tmp_path):
    (tmp_path / "__init__.py").write_text("")
    (tmp_path / "shipped.py").write_text("")
    (tmp_path / "rogue.py").write_text("")
    drift = g.addon_files_drift(
        tmp_path, addon_files=["__init__.py", "shipped.py"], excluded=set())
    assert drift == ["rogue.py"]


def test_addon_files_drift_respects_exclusions(tmp_path):
    (tmp_path / "devonly.py").write_text("")
    drift = g.addon_files_drift(
        tmp_path, addon_files=[], excluded={"devonly.py"})
    assert drift == []


def test_repo_blender_addon_has_no_drift():
    """The real regression: every blender_addon/*.py must be in ADDON_FILES.
    Memory: addon-packaging-file-list - a new module silently missing from the
    allow-list ships a broken addon."""
    addon_files = g._load_addon_files()
    drift = g.addon_files_drift(REPO_ROOT / "blender_addon", addon_files)
    assert drift == [], (
        f"blender_addon/*.py not in ADDON_FILES (add to ADDON_FILES in "
        f"build_blender_addon.py or ADDON_FILES_EXCLUDED): {drift}")


# --------------------------------------------------------------------------- #
# (d) headless-sentinel guard
# --------------------------------------------------------------------------- #

def test_sentinel_passed_true():
    assert g.sentinel_passed("...\nPKG175_SMOKE_RESULT PASS\n", "PKG175_SMOKE_RESULT") is True


def test_sentinel_passed_false_on_fail():
    assert g.sentinel_passed("PKG175_SMOKE_RESULT FAIL\n", "PKG175_SMOKE_RESULT") is False


def test_sentinel_passed_false_when_absent():
    # Exit-0-with-no-sentinel (Blender swallowed a traceback) must NOT pass.
    assert g.sentinel_passed("engine crashed silently\n", "PKG175_SMOKE_RESULT") is False


# --------------------------------------------------------------------------- #
# Local-host smoke gate (skips cleanly without Blender / pwsh / staged build)
# --------------------------------------------------------------------------- #

@pytest.mark.serial
@pytest.mark.gpu
def test_dev_loop_smoke_local_host():
    if not BLENDER.exists():
        pytest.skip("Blender 5.2 not installed - local-host gate")
    pwsh = shutil.which("pwsh") or shutil.which("powershell")
    if pwsh is None:
        pytest.skip("PowerShell not found")
    if not (STAGE_DIR / "build_report.json").exists():
        pytest.skip("no prior staged build (run scripts/dev_addon.ps1 -Smoke once)")

    script = SCRIPTS / "dev_addon.ps1"
    proc = subprocess.run(
        [pwsh, "-NoProfile", "-File", str(script), "-Smoke", "-SkipBuild"],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=900,
        check=False)
    combined = proc.stdout + "\n" + proc.stderr
    assert g.sentinel_passed(combined, "PKG175_SMOKE_RESULT"), (
        "smoke did not report PKG175_SMOKE_RESULT PASS:\n" + combined[-3000:])

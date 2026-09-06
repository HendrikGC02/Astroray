"""pkg175 - unit tests for the dev-loop guards + a local-host smoke gate.

The guard tests are pure (no GPU, no build, no Blender) and always run - they
are the real regression coverage for the four footguns. The smoke test drives
the full ``scripts/dev_addon.ps1 -Smoke -SkipBuild`` loop and SKIPS CLEANLY
when Blender, PowerShell, a prior staged build, or the GPU is absent, so CI
(which has none of those) stays green. This is a local-host gate.
"""
import json
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
def test_dev_loop_smoke_local_host(tmp_path):
    if not BLENDER.exists():
        pytest.skip("Blender 5.2 not installed - local-host gate")
    pwsh = shutil.which("pwsh") or shutil.which("powershell")
    if pwsh is None:
        pytest.skip("PowerShell not found")
    if not (STAGE_DIR / "build_report.json").exists():
        pytest.skip("no prior staged build (run scripts/dev_addon.ps1 -Smoke once)")

    script = SCRIPTS / "dev_addon.ps1"
    proc = subprocess.run(
        [pwsh, "-NoProfile", "-File", str(script), "-Smoke", "-SkipBuild",
         "-SmokeProfileParent", str(tmp_path)],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=900,
        check=False)
    combined = proc.stdout + "\n" + proc.stderr
    assert g.sentinel_passed(combined, "PKG175_SMOKE_RESULT"), (
        "smoke did not report PKG175_SMOKE_RESULT PASS:\n" + combined[-3000:])
    assert proc.returncode == 0, combined[-3000:]
    assert list(tmp_path.iterdir()) == []


@pytest.mark.cpu
@pytest.mark.parametrize("preset_environment", [False, True])
@pytest.mark.parametrize("failure", ["", "register", "render", "escape", "missing", "stage_link", "profile_escape"])
def test_smoke_profile_subprocess_confinement_and_restore(tmp_path, failure, preset_environment):
    pwsh = shutil.which("pwsh") or shutil.which("powershell")
    if pwsh is None:
        pytest.skip("PowerShell unavailable: subprocess confinement untested")
    _run_profile_flow(tmp_path, failure, preset_environment, pwsh)


@pytest.mark.cpu
@pytest.mark.parametrize("mode", ["smoke", "launch"])
@pytest.mark.parametrize("shell_name", ["pwsh", "powershell"])
def test_native_subprocess_argument_compatibility(tmp_path, shell_name, mode):
    shell = shutil.which(shell_name)
    if shell is None:
        pytest.skip(f"{shell_name} unavailable: native argument compatibility untested")
    _run_profile_flow(tmp_path, "", True, shell, mode=mode)


@pytest.mark.cpu
@pytest.mark.parametrize("shell_name", ["pwsh", "powershell"])
@pytest.mark.parametrize("native_exit", [0, 1])
def test_native_stderr_warning_and_exit_gate(tmp_path, shell_name, native_exit):
    shell = shutil.which(shell_name)
    if shell is None:
        pytest.skip(f"{shell_name} unavailable: native stderr handling untested")
    _run_profile_flow(tmp_path, "native_exit" if native_exit else "", True,
                      shell, native_warning=True)


def _run_profile_flow(tmp_path, failure, preset_environment, pwsh, mode="smoke", native_warning=False):
    """Execute the canonical PS flow and installer against a disposable repo.

    Only Blender itself is replaced: the probe reports a controlled extension
    directory and the fake host emits register/render sentinels. Filesystem
    staging, guards, transaction, PowerShell finally and child env are real.
    """
    repo = tmp_path / "repository"
    build_scripts = repo / "scripts" / "build"
    build_scripts.mkdir(parents=True)
    for relative in ["scripts/dev_addon.ps1", "scripts/dev_loop_guards.py",
                     "scripts/build/build_blender_addon.py"]:
        shutil.copy2(REPO_ROOT / relative, repo / relative)
    addon = repo / "blender_addon"
    addon.mkdir()
    (addon / "__init__.py").write_text("# staged addon\n")
    stage = repo / "dist" / "astroray"
    stage.mkdir(parents=True)
    (stage / "build_report.json").write_text(
        '{"cmake_flags": ["-DASTRORAY_DISABLE_OPENMP=ON"]}')
    (stage / "astroray.pyd").write_bytes(b"test native artifact")
    # This replaces discovery at the external Blender boundary only. The
    # production installer and its validation/transaction remain unchanged.
    with (build_scripts / "build_blender_addon.py").open("a") as stream:
        stream.write('''
def blender_user_extensions_dir(blender_exe):
    import json
    values = {k: v for k, v in os.environ.items()
              if k.startswith(("BLENDER_USER_", "ASTRORAY_SMOKE_"))}
    with open(os.environ["PKG236_LOG"], "a") as capture:
        capture.write(json.dumps({"phase": "probe", "env": values}) + "\\n")
    if os.environ.get("PKG236_FAIL") == "escape":
        return Path(os.environ["PKG236_UNRELATED"])
    directory = Path(os.environ["BLENDER_USER_EXTENSIONS"]) / "user_default"
    if os.environ.get("PKG236_FAIL") == "missing" and (directory / "astroray").exists():
        return directory / "missing"
    return directory
''')
    fake_blender = tmp_path / "fake-blender.ps1"
    fake_blender.write_text('''
$capture = @{}
Get-ChildItem Env: | Where-Object {
    $_.Name -like 'BLENDER_USER_*' -or $_.Name -like 'ASTRORAY_SMOKE_*'
} | ForEach-Object { $capture[$_.Name] = $_.Value }
@{ phase = $env:ASTRORAY_SMOKE_MODE; env = $capture } |
    ConvertTo-Json -Compress | Add-Content -LiteralPath $env:PKG236_LOG
if ($env:ASTRORAY_SMOKE_MODE -eq 'register') { $token = 'PKG175_REGISTER_RESULT' }
else { $token = 'PKG175_SMOKE_RESULT' }
if ($env:PKG236_FAIL -eq $env:ASTRORAY_SMOKE_MODE) { Write-Output "$token FAIL" }
else { Write-Output "$token PASS" }
''')
    if native_warning:
        # A real native child is required: Write-Error from a PowerShell-only
        # fake does not reproduce Windows PowerShell NativeCommandError.
        with fake_blender.open("a") as stream:
            stream.write('''
$native = @'
import os, sys
print("DeprecationWarning: native Blender warning", file=sys.stderr)
print("PKG175_REGISTER_RESULT PASS")
sys.exit(1 if os.environ.get("PKG236_FAIL") == "native_exit" else 0)
'@
$native | & $env:PKG236_PYTHON -
''')
    profile_parent = tmp_path / "profiles"
    profile_parent.mkdir()
    if failure == "stage_link":
        payload = repo / "dist" / "payload"
        stage.rename(payload)
        try:
            stage.symlink_to(payload, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("symlink unavailable: PowerShell stage-link confinement untested")
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    sentinel = unrelated / "sentinel.bin"
    sentinel.write_bytes(b"live profile content stays byte identical")
    log = tmp_path / "subprocesses.jsonl"
    restored = tmp_path / "restored.json"
    wrapper = tmp_path / "invoke.ps1"
    wrapper.write_text('''
function Snapshot {
    $snapshot = @{}
    Get-ChildItem Env: | Where-Object {
        $_.Name -like 'BLENDER_USER_*' -or $_.Name -like 'ASTRORAY_SMOKE_*'
    } | ForEach-Object { $snapshot[$_.Name] = $_.Value }
    return $snapshot
}
$ErrorActionPreference = 'Stop'
$before = Snapshot
$failed = $false
try {
    $modeSwitch = @{ Smoke = ($env:PKG236_MODE -eq 'smoke'); Launch = ($env:PKG236_MODE -eq 'launch') }
    & $env:PKG236_SCRIPT @modeSwitch -SkipBuild -Blender $env:PKG236_BLENDER `
        -Python $env:PKG236_PYTHON -SmokeProfileParent $env:PKG236_PROFILES
} catch { Write-Output $_; $failed = $true }
@{ before = $before; after = (Snapshot); errorPreference = "$ErrorActionPreference" } | ConvertTo-Json -Depth 5 |
    Set-Content -LiteralPath $env:PKG236_RESTORED
if ($failed) { exit 1 }
''')
    child_env = os.environ.copy()
    names = ["BLENDER_USER_" + suffix for suffix in
             ["RESOURCES", "EXTENSIONS", "CONFIG", "SCRIPTS", "DATAFILES"]]
    for name in names:
        child_env[name] = str(unrelated)
    child_env.update({"ASTRORAY_SMOKE_MODE": "previous-mode",
                      "ASTRORAY_SMOKE_ADDON_DIR": "previous-addon",
                      "ASTRORAY_SMOKE_EXTRA": "previous-extra",
                      "PKG236_LOG": str(log), "PKG236_FAIL": failure,
                      "PKG236_MODE": mode,
                      "PKG236_UNRELATED": str(unrelated),
                      "PKG236_SCRIPT": str(repo / "scripts/dev_addon.ps1"),
                      "PKG236_BLENDER": str(fake_blender),
                      "PKG236_PYTHON": sys.executable,
                      "PKG236_PROFILES": str(profile_parent),
                      "PKG236_RESTORED": str(restored)})
    if failure == "profile_escape":
        child_env["PKG236_PROFILES"] = str(profile_parent / ".." / "profiles")
    if not preset_environment:
        for name in list(child_env):
            if name.startswith(("BLENDER_USER_", "ASTRORAY_SMOKE_")):
                child_env.pop(name)
    proc = subprocess.run([pwsh, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(wrapper)],
                          cwd=repo, env=child_env, capture_output=True, text=True,
                          timeout=60, check=False)
    output = proc.stdout + proc.stderr
    assert proc.returncode == (1 if failure else 0), output
    restoration = json.loads(restored.read_text(encoding="utf-8-sig"))
    assert restoration["before"] == restoration["after"]
    assert restoration["errorPreference"] == "Stop"
    if native_warning:
        assert "DeprecationWarning: native Blender warning" in output
        assert f"Blender exit code: {1 if failure else 0}" in output
        if failure:
            assert "Blender exited with code 1" in output
    assert sentinel.read_bytes() == b"live profile content stays byte identical"
    if mode == "smoke":
        assert list(unrelated.iterdir()) == [sentinel]
    else:
        assert (unrelated / "user_default" / "astroray" / "astroray.pyd").read_bytes() == b"test native artifact"
    assert list(profile_parent.iterdir()) == []
    if failure in {"stage_link", "profile_escape"}:
        assert not log.exists(), "Blender must not be invoked for an unsafe path"
        return
    records = [json.loads(line) for line in log.read_text(encoding="utf-8-sig").splitlines()]
    assert records
    if mode == "launch":
        assert any(record["phase"] == "probe" for record in records)
        for record in records:
            for name in names:
                assert Path(record["env"][name]) == unrelated
        return
    roots = set()
    for record in records:
        environment = record["env"]
        assert "ASTRORAY_SMOKE_EXTRA" not in environment
        for name in names:
            directory = Path(environment[name])
            assert directory.is_relative_to(profile_parent)
            roots.add(directory.parent)
        if record["phase"] == "render":
            installed = Path(environment["ASTRORAY_SMOKE_ADDON_DIR"])
            assert installed.is_relative_to(profile_parent)
            assert installed.name == "astroray"
    assert len(roots) == 1
    if failure in {"register", "escape", "missing"}:
        assert not any(record["phase"] == "render" for record in records)

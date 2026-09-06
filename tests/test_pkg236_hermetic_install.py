"""pkg236: Hermetic, transactional install_to_blender() tests.

These tests exercise the install path of scripts/build/build_blender_addon.py
without ever invoking Blender: the Blender extensions-dir resolver is
monkeypatched, and STAGE_DIR is pointed at a real temp directory.  They verify
the transactional guarantees (copy-before-mutate, backup, promote, rollback),
path validation (no '..', no reparse points, no escape of allowed_root), and
byte preservation on a locked old target.
"""

import importlib.util
import os
import platform
import shutil
import subprocess
from pathlib import Path

import pytest

# --------------------------------------------------------------------------- #
# Module loading (mirrors test_pkg94_build_integrity_guard.py)
# --------------------------------------------------------------------------- #

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build" / "build_blender_addon.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("build_blender_addon_pkg236", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def bba():
    return _load_module()


def _make_stage(tmp_path: Path) -> Path:
    """Create a minimal stage tree with a couple of files and a subdir."""
    stage = tmp_path / "stage"
    (stage / "sub").mkdir(parents=True)
    (stage / "__init__.py").write_text("init")
    (stage / "astroray.pyd").write_bytes(b"\x00\x01\x02\x03")
    (stage / "sub" / "data.txt").write_text("payload")
    return stage


def _resolver_for(ext_dir: Path):
    """Return a monkeypatchable resolver returning `ext_dir`."""
    def _resolver(blender_exe):
        return ext_dir
    return _resolver


# --------------------------------------------------------------------------- #
# Basic install + promotion
# --------------------------------------------------------------------------- #

def test_install_copies_stage_and_promotes(bba, tmp_path, monkeypatch):
    stage = _make_stage(tmp_path)
    ext_dir = tmp_path / "ext"
    monkeypatch.setattr(bba, "STAGE_DIR", stage)
    monkeypatch.setattr(bba, "blender_user_extensions_dir", _resolver_for(ext_dir))

    assert bba.install_to_blender(Path("blender.exe")) is True

    target = ext_dir / "astroray"
    assert (target / "__init__.py").read_text() == "init"
    assert (target / "astroray.pyd").read_bytes() == b"\x00\x01\x02\x03"
    assert (target / "sub" / "data.txt").read_text() == "payload"
    # No staging/backup litter left behind.
    assert list(ext_dir.iterdir()) == [target]


def test_install_replaces_existing_target(bba, tmp_path, monkeypatch):
    stage = _make_stage(tmp_path)
    ext_dir = tmp_path / "ext"
    target = ext_dir / "astroray"
    target.mkdir(parents=True)
    (target / "old.txt").write_text("old")
    monkeypatch.setattr(bba, "STAGE_DIR", stage)
    monkeypatch.setattr(bba, "blender_user_extensions_dir", _resolver_for(ext_dir))

    assert bba.install_to_blender(Path("blender.exe")) is True
    assert not (target / "old.txt").exists()
    assert (target / "__init__.py").read_text() == "init"


def test_install_returns_false_when_resolver_fails(bba, tmp_path, monkeypatch):
    stage = _make_stage(tmp_path)
    monkeypatch.setattr(bba, "STAGE_DIR", stage)
    monkeypatch.setattr(bba, "blender_user_extensions_dir", lambda be: None)
    assert bba.install_to_blender(Path("blender.exe")) is False


# --------------------------------------------------------------------------- #
# Path validation
# --------------------------------------------------------------------------- #

def test_rejects_dotdot_component(bba, tmp_path, monkeypatch):
    stage = _make_stage(tmp_path)
    ext_dir = tmp_path / "ext"
    # Resolver returns a path containing '..' â€” must be rejected before mutation.
    monkeypatch.setattr(bba, "STAGE_DIR", stage)
    monkeypatch.setattr(
        bba, "blender_user_extensions_dir",
        lambda be: ext_dir / ".." / "escape")
    assert bba.install_to_blender(Path("blender.exe")) is False
    assert not (tmp_path / "escape").exists()


def test_rejects_escape_of_allowed_root(bba, tmp_path, monkeypatch):
    stage = _make_stage(tmp_path)
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    monkeypatch.setattr(bba, "STAGE_DIR", stage)
    monkeypatch.setattr(
        bba, "blender_user_extensions_dir", lambda be: outside)
    assert bba.install_to_blender(Path("blender.exe"), allowed_root=allowed) is False
    assert not outside.exists()


def test_allows_target_within_allowed_root(bba, tmp_path, monkeypatch):
    stage = _make_stage(tmp_path)
    allowed = tmp_path / "allowed"
    ext_dir = allowed / "ext"
    monkeypatch.setattr(bba, "STAGE_DIR", stage)
    monkeypatch.setattr(
        bba, "blender_user_extensions_dir", lambda be: ext_dir)
    assert bba.install_to_blender(Path("blender.exe"), allowed_root=allowed) is True
    assert (ext_dir / "astroray" / "__init__.py").exists()


def test_rejects_reparse_point_in_target_ancestor(bba, tmp_path, monkeypatch):
    stage = _make_stage(tmp_path)
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    try:
        os.symlink(real, link, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not available")
    monkeypatch.setattr(bba, "STAGE_DIR", stage)
    monkeypatch.setattr(
        bba, "blender_user_extensions_dir", lambda be: link)
    assert bba.install_to_blender(Path("blender.exe")) is False
    # Nothing written through the link.
    assert not (real / "astroray").exists()


@pytest.mark.skipif(platform.system() != "Windows", reason="junction is Windows-only")
def test_rejects_junction_in_target_ancestor(bba, tmp_path, monkeypatch):
    stage = _make_stage(tmp_path)
    real = tmp_path / "real"
    real.mkdir()
    junc = tmp_path / "junc"
    pwsh = shutil.which("pwsh") or shutil.which("powershell")
    if not pwsh:
        pytest.skip("PowerShell unavailable for junction creation")
    r = subprocess.run(
        [pwsh, "-NoProfile", "-Command",
         'New-Item -ItemType Junction -Path $env:PKG236_LINK -Target $env:PKG236_REAL'],
        env={**os.environ, "PKG236_LINK": str(junc), "PKG236_REAL": str(real)},
        capture_output=True, text=True, timeout=15, check=False)
    if r.returncode != 0:
        pytest.skip("junction creation unavailable")
    monkeypatch.setattr(bba, "STAGE_DIR", stage)
    monkeypatch.setattr(
        bba, "blender_user_extensions_dir", lambda be: junc)
    assert bba.install_to_blender(Path("blender.exe")) is False
    assert not (real / "astroray").exists()


def test_rejects_reparse_point_in_stage_tree(bba, tmp_path, monkeypatch):
    stage = _make_stage(tmp_path)
    real = tmp_path / "real"
    real.mkdir()
    try:
        os.symlink(real, stage / "evil", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not available")
    ext_dir = tmp_path / "ext"
    monkeypatch.setattr(bba, "STAGE_DIR", stage)
    monkeypatch.setattr(
        bba, "blender_user_extensions_dir", lambda be: ext_dir)
    assert bba.install_to_blender(Path("blender.exe")) is False
    assert not ext_dir.exists()


# --------------------------------------------------------------------------- #
# Transactional guarantees
# --------------------------------------------------------------------------- #

def test_locked_old_target_preserves_bytes(bba, tmp_path, monkeypatch):
    """A locked old target (rename fails) must leave all old bytes intact."""
    stage = _make_stage(tmp_path)
    ext_dir = tmp_path / "ext"
    target = ext_dir / "astroray"
    target.mkdir(parents=True)
    old_bytes = b"precious-old-bytes"
    (target / "module.pyd").write_bytes(old_bytes)
    monkeypatch.setattr(bba, "STAGE_DIR", stage)
    monkeypatch.setattr(bba, "blender_user_extensions_dir", _resolver_for(ext_dir))

    real_rename = os.rename

    def _locked_rename(src, dst):
        # Simulate a locked old target: only the target->backup rename fails.
        if Path(src) == target:
            raise PermissionError(13, "Access is denied (module locked)")
        return real_rename(src, dst)

    monkeypatch.setattr(bba.os, "rename", _locked_rename)

    assert bba.install_to_blender(Path("blender.exe")) is False
    # Old bytes fully preserved, untouched.
    assert (target / "module.pyd").read_bytes() == old_bytes
    # No staging litter left behind.
    assert list(ext_dir.iterdir()) == [target]


def test_promotion_failure_rolls_back(bba, tmp_path, monkeypatch):
    """If promotion fails, the complete old target is restored."""
    stage = _make_stage(tmp_path)
    ext_dir = tmp_path / "ext"
    target = ext_dir / "astroray"
    target.mkdir(parents=True)
    (target / "old.txt").write_text("old-content")
    monkeypatch.setattr(bba, "STAGE_DIR", stage)
    monkeypatch.setattr(bba, "blender_user_extensions_dir", _resolver_for(ext_dir))

    real_rename = os.rename

    def _fail_promote(src, dst):
        # Fail only the staging->target promotion (dst == target and src is staging).
        if Path(dst) == target and ".staging-" in Path(src).name:
            raise OSError("simulated promotion failure")
        return real_rename(src, dst)

    monkeypatch.setattr(bba.os, "rename", _fail_promote)

    assert bba.install_to_blender(Path("blender.exe")) is False
    # Old target restored with its original content.
    assert (target / "old.txt").read_text() == "old-content"
    assert not (target / "__init__.py").exists()


def test_unrelated_sentinel_unchanged(bba, tmp_path, monkeypatch):
    """A sibling file/dir unrelated to the install is never touched."""
    stage = _make_stage(tmp_path)
    ext_dir = tmp_path / "ext"
    ext_dir.mkdir(parents=True)
    sentinel = ext_dir / "unrelated.txt"
    sentinel.write_text("keep-me")
    monkeypatch.setattr(bba, "STAGE_DIR", stage)
    monkeypatch.setattr(bba, "blender_user_extensions_dir", _resolver_for(ext_dir))

    assert bba.install_to_blender(Path("blender.exe")) is True
    assert sentinel.read_text() == "keep-me"
    assert (ext_dir / "astroray" / "__init__.py").exists()


def _tree_bytes(path):
    return {str(p.relative_to(path)): p.read_bytes() for p in path.rglob("*") if p.is_file()}


@pytest.mark.parametrize("failure", ["copy", "promote", "locked", "rollback", "cleanup"])
def test_transaction_failure_evidence_and_complete_bytes(bba, tmp_path, monkeypatch, capsys, failure):
    stage = _make_stage(tmp_path)
    target = tmp_path / "profile" / "extensions" / "astroray"
    (target / "assets").mkdir(parents=True)
    (target / "assets" / "keep.bin").write_bytes(b"asset data")
    (target / "module.pyd").write_bytes(b"old loaded native module")
    (target / "__init__.py").write_bytes(b"old addon")
    old_bytes = _tree_bytes(target)
    sentinel = target.parent / "other-addon.bin"
    sentinel.write_bytes(b"unrelated data")
    monkeypatch.setattr(bba, "STAGE_DIR", stage)
    monkeypatch.setattr(bba, "blender_user_extensions_dir", lambda _: target.parent)
    real_copy = shutil.copytree
    real_rename = os.rename
    real_remove = shutil.rmtree

    def copy(src, dst, *args, **kwargs):
        result = real_copy(src, dst, *args, **kwargs)
        if failure == "copy" and Path(src) == stage:
            raise OSError("injected copy failure after real file writes")
        return result

    def rename(src, dst):
        if (failure == "locked" and Path(src) == target or
            failure in {"promote", "rollback"} and ".staging-" in Path(src).name or
            failure == "rollback" and ".backup-" in Path(src).name):
            raise PermissionError("injected locked rename")
        return real_rename(src, dst)

    def remove(path, *args, **kwargs):
        if failure == "cleanup" and ".backup-" in Path(path).name:
            # Demonstrate why a partially cleaned backup cannot be restored.
            (Path(path) / "__init__.py").unlink()
            raise PermissionError("injected locked backup cleanup")
        return real_remove(path, *args, **kwargs)

    monkeypatch.setattr(bba.shutil, "copytree", copy)
    monkeypatch.setattr(bba.os, "rename", rename)
    monkeypatch.setattr(bba.shutil, "rmtree", remove)
    assert not bba.install_to_blender(Path("blender"), allowed_root=tmp_path / "profile")
    output = capsys.readouterr().out
    assert sentinel.read_bytes() == b"unrelated data"
    if failure in {"copy", "promote", "locked"}:
        assert _tree_bytes(target) == old_bytes
    elif failure == "rollback":
        backup, = target.parent.glob(".astroray.backup-*")
        assert _tree_bytes(backup) == old_bytes
        assert str(backup) in output and "rollback failed" in output
        assert not target.exists()
    else:
        assert _tree_bytes(target) == _tree_bytes(stage)
        backup, = target.parent.glob(".astroray.backup-*")
        assert str(target) in output and str(backup) in output
        assert "Rollback was not attempted" in output


@pytest.mark.parametrize("location", ["stage", "stage_parent", "allowed_root", "old_tree"])
def test_rejects_redirected_roots_and_existing_tree(bba, tmp_path, monkeypatch, location):
    stage = _make_stage(tmp_path)
    profile = tmp_path / "profile"
    target = profile / "extensions" / "astroray"
    target.mkdir(parents=True)
    (target / "old.txt").write_bytes(b"old complete installation")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "sentinel").write_bytes(b"unrelated")
    link = tmp_path / "link"
    destination = {"stage": stage, "stage_parent": tmp_path,
                   "allowed_root": profile, "old_tree": outside}[location]
    if location == "old_tree":
        link = target / "redirect"
    try:
        link.symlink_to(destination, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unavailable: root-link case untested")
    selected_stage = link if location == "stage" else link / "stage" if location == "stage_parent" else stage
    monkeypatch.setattr(bba, "STAGE_DIR", selected_stage)
    monkeypatch.setattr(bba, "blender_user_extensions_dir", lambda _: target.parent)
    assert not bba.install_to_blender(Path("blender"), allowed_root=link if location == "allowed_root" else profile)
    assert (target / "old.txt").read_bytes() == b"old complete installation"
    assert list(profile.glob("extensions/.astroray.*")) == []
    assert (outside / "sentinel").read_bytes() == b"unrelated"


@pytest.mark.parametrize("suffix", ["relative", "..", "trailing.", "trailing ", "file:stream"])
def test_ambiguous_targets_rejected_before_creation(bba, tmp_path, monkeypatch, suffix):
    if suffix in {"trailing.", "trailing ", "file:stream"} and os.name != "nt":
        pytest.skip("Windows path alias case")
    stage = _make_stage(tmp_path)
    root = tmp_path / "profile"
    extension = Path(suffix) if suffix == "relative" else root / suffix
    monkeypatch.setattr(bba, "STAGE_DIR", stage)
    monkeypatch.setattr(bba, "blender_user_extensions_dir", lambda _: extension)
    assert not bba.install_to_blender(Path("blender"), allowed_root=root)
    assert not root.exists()

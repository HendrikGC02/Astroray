#!/usr/bin/env python3
"""pkg175 dev-loop guards — the four memory-backed footguns, made impossible.

These are plain, importable, unit-testable functions used by
``scripts/dev_addon.ps1`` (the one-command Blender dev loop). Each encodes a
failure mode this repo has actually shipped:

  (a) pyd_is_stale            — stale-.pyd (memory: stale_pyd_locations). Refuse
                                to package a ``.pyd`` older than HEAD.
  (b) openmp_disabled_*       — MinGW libgomp deadlocks inside Blender
                                (memory: mingw_openmp_blender_deadlock). Refuse
                                an addon build that was not configured with
                                ``-DASTRORAY_DISABLE_OPENMP=ON``.
  (c) addon_files_drift       — the packaging allow-list drift trap
                                (memory: addon-packaging-file-list). Every
                                ``blender_addon/*.py`` on disk must be in
                                ``ADDON_FILES`` (or explicitly excluded).
  (d) sentinel_passed         — Blender ``--python`` swallows tracebacks and
                                exits 0 (learned in the pkg88b harness). Gate on
                                a printed ``<TOKEN> PASS`` string, never on exit
                                code.

The functions are pure/deterministic and take their inputs explicitly so they
can be unit-tested without a GPU, a build, or Blender. A thin CLI at the bottom
lets the PowerShell driver invoke them and branch on the exit code.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# blender_addon/*.py files that intentionally do NOT ship in the addon zip.
# Empty today — every top-level module is packaged. A new dev-only helper that
# should not ship goes here (and the reason belongs in the commit message).
ADDON_FILES_EXCLUDED: set[str] = set()


# --------------------------------------------------------------------------- #
# (a) stale .pyd guard
# --------------------------------------------------------------------------- #

def head_commit_epoch(repo_root: Path | str = REPO_ROOT) -> int:
    """Return the committer-date (epoch seconds) of HEAD in ``repo_root``."""
    out = subprocess.check_output(
        ["git", "-C", str(repo_root), "log", "-1", "--format=%ct", "HEAD"],
        text=True, timeout=15).strip()
    return int(out)


def pyd_is_stale(pyd_path: Path | str, head_epoch: int) -> tuple[bool, float]:
    """Return (is_stale, pyd_mtime_epoch).

    Stale == the compiled module predates the HEAD commit, i.e. it was built
    from older source. A missing file is treated as stale.
    """
    p = Path(pyd_path)
    if not p.exists():
        return True, 0.0
    mtime = p.stat().st_mtime
    return (mtime < head_epoch), mtime


def find_built_pyd(build_dir: Path | str) -> Path | None:
    """Return the most-recently-built ``astroray*.pyd`` under ``build_dir``."""
    root = Path(build_dir)
    matches: list[Path] = []
    for pattern in ("astroray.*.pyd", "astroray*.pyd", "astroray*.so",
                    "Release/astroray*.pyd"):
        matches += list(root.glob(pattern))
    if not matches:
        return None
    matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return matches[0]


# --------------------------------------------------------------------------- #
# (b) OpenMP-disabled guard
# --------------------------------------------------------------------------- #

def openmp_disabled_in_flags(cmake_flags: list[str]) -> bool:
    """True iff the flag list carries ``-DASTRORAY_DISABLE_OPENMP=ON``."""
    for flag in cmake_flags:
        norm = flag.replace(" ", "").upper()
        if norm == "-DASTRORAY_DISABLE_OPENMP=ON":
            return True
    return False


def openmp_disabled_in_build_report(staged_dir: Path | str) -> bool:
    """Read ``build_report.json`` written by build_blender_addon.py and confirm
    the build was configured with OpenMP off."""
    report = Path(staged_dir) / "build_report.json"
    if not report.exists():
        raise FileNotFoundError(f"no build_report.json in {staged_dir}")
    flags = json.loads(report.read_text()).get("cmake_flags", [])
    return openmp_disabled_in_flags(flags)


# --------------------------------------------------------------------------- #
# (c) ADDON_FILES allow-list drift guard
# --------------------------------------------------------------------------- #

def _load_addon_files(build_script: Path | str | None = None) -> list[str]:
    """Import ADDON_FILES from scripts/build/build_blender_addon.py by path."""
    path = Path(build_script) if build_script else (
        REPO_ROOT / "scripts" / "build" / "build_blender_addon.py")
    spec = importlib.util.spec_from_file_location("_bba_for_guard", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return list(mod.ADDON_FILES)


def addon_files_drift(addon_dir: Path | str,
                      addon_files: list[str],
                      excluded: set[str] | None = None) -> list[str]:
    """Return top-level ``*.py`` files in ``addon_dir`` that are neither in the
    packaging allow-list nor explicitly excluded. Empty list == no drift."""
    excluded = excluded if excluded is not None else ADDON_FILES_EXCLUDED
    allowed = set(addon_files) | set(excluded)
    on_disk = sorted(p.name for p in Path(addon_dir).glob("*.py"))
    return [name for name in on_disk if name not in allowed]


# --------------------------------------------------------------------------- #
# (d) headless-sentinel guard
# --------------------------------------------------------------------------- #

def sentinel_passed(output: str, token: str) -> bool:
    """True iff ``<token> PASS`` appears in ``output`` and ``<token> FAIL`` does
    not. Blender --python exits 0 even on an uncaught traceback, so the printed
    sentinel — not the exit code — is the source of truth."""
    if f"{token} FAIL" in output:
        return False
    return f"{token} PASS" in output


# --------------------------------------------------------------------------- #
# CLI (used by dev_addon.ps1; each subcommand exits 0 on pass, 1 on fail)
# --------------------------------------------------------------------------- #

def _cmd_pyd_fresh(args) -> int:
    build_dir = Path(args.build_dir)
    pyd = Path(args.pyd) if args.pyd else find_built_pyd(build_dir)
    if pyd is None:
        print(f"[guard:pyd] FAIL - no astroray*.pyd found under {build_dir}")
        return 1
    head = head_commit_epoch(args.repo)
    stale, mtime = pyd_is_stale(pyd, head)
    print(f"[guard:pyd] pyd={pyd}")
    print(f"[guard:pyd] pyd_mtime={mtime:.0f}  head_commit_epoch={head}")
    if stale:
        print("[guard:pyd] FAIL - built .pyd is OLDER than HEAD; rebuild before packaging")
        return 1
    print("[guard:pyd] PASS - built .pyd is at/after HEAD")
    return 0


def _cmd_openmp(args) -> int:
    try:
        ok = openmp_disabled_in_build_report(args.staged)
    except FileNotFoundError as exc:
        print(f"[guard:openmp] FAIL - {exc}")
        return 1
    if not ok:
        print("[guard:openmp] FAIL - build was NOT configured with "
              "-DASTRORAY_DISABLE_OPENMP=ON (libgomp deadlocks in Blender)")
        return 1
    print("[guard:openmp] PASS - -DASTRORAY_DISABLE_OPENMP=ON")
    return 0


def _cmd_addon_files(args) -> int:
    addon_dir = Path(args.addon_dir)
    drift = addon_files_drift(addon_dir, _load_addon_files())
    if drift:
        print("[guard:addon-files] FAIL - these blender_addon/*.py are neither "
              "in ADDON_FILES nor excluded:")
        for name in drift:
            print(f"    {name}")
        print("  Add them to ADDON_FILES in scripts/build/build_blender_addon.py "
              "or to ADDON_FILES_EXCLUDED in scripts/dev_loop_guards.py")
        return 1
    print("[guard:addon-files] PASS - every blender_addon/*.py is accounted for")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("pyd-fresh", help="(a) refuse a .pyd older than HEAD")
    p.add_argument("--build-dir", required=True)
    p.add_argument("--pyd", default=None, help="explicit .pyd (else newest in build-dir)")
    p.add_argument("--repo", default=str(REPO_ROOT))
    p.set_defaults(func=_cmd_pyd_fresh)

    p = sub.add_parser("openmp", help="(b) refuse a build without OpenMP off")
    p.add_argument("--staged", required=True, help="staged addon dir (has build_report.json)")
    p.set_defaults(func=_cmd_openmp)

    p = sub.add_parser("addon-files", help="(c) ADDON_FILES allow-list drift")
    p.add_argument("--addon-dir", default=str(REPO_ROOT / "blender_addon"))
    p.set_defaults(func=_cmd_addon_files)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

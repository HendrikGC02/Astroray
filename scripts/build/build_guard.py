"""pkg183 - incremental-build staleness guard.

Guards against ABI-mixed binaries: stale object files compiled against an older
struct layout getting linked with fresh objects. On the OneDrive tree, Ninja's
mtime-based staleness detection is unreliable (OneDrive mangles mtimes), so a
layout-changing commit boundary crossed via branch-switching can silently
produce a binary that access-violates on host-only code (the incident that
motivated this: get_material_backend_capabilities on a lambertian crashed on
every contaminated binary). See pkg183 spec and the
`incremental-build-signature-staleness` memory.

Strategy: hash the layout-critical headers (include/astroray/*.h,
include/raytracer.h) and record that hash + the HEAD SHA in a stamp file next
to the build tree. On the next build, if the header hash changed, the wrapper
force-cleans object files (correctness over speed) instead of trusting mtimes.

Subcommands:
  check --repo-root R --build-dir B
      Emit WIPE (stale objects present that must be force-cleaned) or OK.
      Never exits non-zero for a normal decision; a non-zero exit means the
      guard itself could not run and the caller should warn but continue.

  write --repo-root R --build-dir B --sha S
      Record the current header hash + SHA into <build-dir>/.astroray_build_stamp.
      Call this AFTER a successful configure/build.

  canary --repo-root R [--build-dir D]
      Host-only (<5 s, no GPU) ABI smoke check: import the freshly built
      astroray and run the exact 3-line repro that access-violated on every
      ABI-mixed binary during the 2026-08-11 incident. Reuses
      tests/runtime_setup.py to put the CUDA/OIDN dependency DLL dirs on the
      loader path (the .pyd links _deps DLLs that are not otherwise on PATH).
      Exits 0 on success, 6 if the call raises a Python exception. A hard
      C-level crash (access violation) kills this process with its own non-zero
      code, which the calling wrapper likewise treats as a canary failure.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

STAMP_NAME = ".astroray_build_stamp"


def _layout_headers(repo_root: Path) -> list[Path]:
    """Layout-critical headers whose struct changes must invalidate objects.

    Exactly the set named in the pkg183 spec: every .h under include/astroray/
    plus include/raytracer.h. Sorted for a deterministic hash.
    """
    headers = sorted((repo_root / "include" / "astroray").glob("*.h"))
    rt = repo_root / "include" / "raytracer.h"
    if rt.exists():
        headers.append(rt)
    return headers


def _header_hash(repo_root: Path) -> str:
    h = hashlib.sha256()
    for path in _layout_headers(repo_root):
        rel = path.relative_to(repo_root).as_posix()
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(path.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def _cmd_check(repo_root: Path, build_dir: Path) -> int:
    current = _header_hash(repo_root)
    stamp = build_dir / STAMP_NAME
    cache = build_dir / "CMakeCache.txt"

    # A tree that was never configured has no objects to be stale -> nothing to
    # wipe. Let the wrapper configure + build fresh.
    if not cache.exists():
        print("OK")
        return 0

    if not stamp.exists():
        # Configured build with no stamp = predates this guard; it may already
        # be ABI-mixed. Force-clean once so the first guarded build is trusted.
        print("WIPE")
        return 0

    try:
        recorded = json.loads(stamp.read_text(encoding="utf-8")).get("header_hash", "")
    except (ValueError, OSError):
        print("WIPE")
        return 0

    print("WIPE" if recorded != current else "OK")
    return 0


def _cmd_write(repo_root: Path, build_dir: Path, sha: str) -> int:
    build_dir.mkdir(parents=True, exist_ok=True)
    payload = {"header_hash": _header_hash(repo_root), "sha": sha}
    (build_dir / STAMP_NAME).write_text(json.dumps(payload) + "\n", encoding="utf-8")
    print(f"[pkg183] build stamp written: sha={sha[:12]} header_hash={payload['header_hash'][:12]}")
    return 0


CANARY_EXIT = 6


def _cmd_canary(repo_root: Path, build_dir: str | None) -> int:
    import os
    if build_dir:
        os.environ["ASTRORAY_BUILD_DIR"] = str(Path(build_dir).resolve())
    sys.path.insert(0, str(repo_root / "tests"))
    try:
        import runtime_setup
        runtime_setup.configure_test_imports()
        import astroray
        r = astroray.Renderer()
        m = r.create_material("lambertian", [0.5, 0.5, 0.5], {})
        caps = r.get_material_backend_capabilities(m)
    except Exception as exc:  # noqa: BLE001 - any failure here is a canary trip
        print(f"[pkg183] canary EXCEPTION: {type(exc).__name__}: {exc}")
        return CANARY_EXIT
    print(f"[pkg183] canary caps: {caps}")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="pkg183 incremental-build staleness guard")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_check = sub.add_parser("check")
    p_check.add_argument("--repo-root", required=True)
    p_check.add_argument("--build-dir", required=True)

    p_write = sub.add_parser("write")
    p_write.add_argument("--repo-root", required=True)
    p_write.add_argument("--build-dir", required=True)
    p_write.add_argument("--sha", required=True)

    p_canary = sub.add_parser("canary")
    p_canary.add_argument("--repo-root", required=True)
    p_canary.add_argument("--build-dir", default=None)

    args = parser.parse_args(argv)

    if args.cmd == "canary":
        return _cmd_canary(Path(args.repo_root).resolve(), args.build_dir)

    repo_root = Path(args.repo_root).resolve()
    build_dir = Path(args.build_dir).resolve()

    if args.cmd == "check":
        return _cmd_check(repo_root, build_dir)
    if args.cmd == "write":
        return _cmd_write(repo_root, build_dir, args.sha)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

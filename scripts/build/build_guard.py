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

  arch-verify --pyd-dir D [--expect sm_120]
      GROUND-TRUTH CUDA arch gate (PR #590 incident, 2026-08-12): run
      `cuobjdump --list-elf` on the built astroray*.pyd and fail (exit 7) if the
      embedded cubin arch does not match the expected native arch. This is
      authoritative where the CMakeCache `CMAKE_CUDA_ARCHITECTURES` line is NOT:
      on a Ninja tree the cache can read `52` yet the .pyd embeds `sm_120`
      (CMakeLists' non-cache set() shadows the cache when ASTRORAY_CUDA_ARCHS is
      defined), while in VS-generator worktrees where ASTRORAY_CUDA_ARCHS is
      unset the stale 52 is LIVE — that produced cuobjdump register/stack
      readings (2640) taken on irrelevant compute_52 PTX instead of the true
      sm_120 SASS (3608). Expected arch auto-detects via
      `nvidia-smi --query-gpu=compute_cap`; if that is unavailable it falls back
      to a legacy-sentinel rule (fail when the ONLY embedded arch is pre-Volta,
      e.g. sm_52). Missing cuobjdump downgrades to a warning (never a false
      build failure).

  arch-check --build-dir D
      Fast, advisory-only pre-build read of the CMakeCache
      `CMAKE_CUDA_ARCHITECTURES` line. Prints a heads-up when it looks legacy;
      NEVER gates (the cache line is unreliable — see arch-verify). The
      post-build arch-verify is the gate.
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


ARCH_EXIT = 7


def _find_astroray_pyd(pyd_dir: Path) -> Path | None:
    """Locate the built astroray module .pyd (not astroray_test_helpers).

    Searches the given dir and its Release/ subdir (VS multi-config layout).
    """
    import os
    for base in (pyd_dir, pyd_dir / "Release"):
        if not base.is_dir():
            continue
        for name in sorted(os.listdir(base)):
            low = name.lower()
            if low.startswith("astroray") and low.endswith(".pyd") and "test_helpers" not in low:
                return base / name
    return None


def _detect_native_arch() -> str | None:
    """Local GPU compute capability as an sm_ token, e.g. '12.0' -> 'sm_120'."""
    import subprocess
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=compute_cap", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=15, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    first = (out.stdout or "").strip().splitlines()
    if not first:
        return None
    cc = first[0].strip()  # "12.0"
    if not cc or "." not in cc:
        return None
    major, minor = cc.split(".", 1)
    return f"sm_{major}{minor}"


def _cuobjdump_arches(pyd: Path) -> tuple[set[str], bool]:
    """Return (embedded sm_ arches, cuobjdump_available)."""
    import re
    import subprocess
    try:
        out = subprocess.run(
            ["cuobjdump", "--list-elf", str(pyd)],
            capture_output=True, text=True, timeout=60, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return set(), False
    arches = set(re.findall(r"sm_(\d+)", out.stdout or ""))
    return {f"sm_{a}" for a in arches}, True


def _cmd_arch_verify(pyd_dir: Path, expect: str | None) -> int:
    pyd = _find_astroray_pyd(pyd_dir)
    if pyd is None:
        print(f"[pkg183] arch-verify WARNING: no astroray*.pyd found under {pyd_dir}; skipping")
        return 0

    arches, available = _cuobjdump_arches(pyd)
    if not available:
        print("[pkg183] arch-verify WARNING: cuobjdump not on PATH; skipping arch gate")
        return 0
    if not arches:
        print(f"[pkg183] arch-verify WARNING: no SASS cubin embedded in {pyd.name} "
              "(PTX-only build?); cannot confirm native arch")
        return 0

    expected = expect or _detect_native_arch()
    embedded = ",".join(sorted(arches))

    if expected is None:
        # Could not determine the intended arch. Still catch the exact incident
        # signature: a build whose ONLY embedded arch is legacy (pre-Volta).
        legacy_only = all(int(a[3:]) < 70 for a in arches)
        if legacy_only:
            print(f"[pkg183] arch-verify FAIL: {pyd.name} embeds only legacy arch(es) "
                  f"[{embedded}] (pre-Volta); expected the native GPU arch. "
                  "This is the stale-CMAKE_CUDA_ARCHITECTURES=52 signature.")
            return ARCH_EXIT
        print(f"[pkg183] arch-verify: could not detect native arch (nvidia-smi); "
              f"embedded=[{embedded}], no legacy-only -> accepting")
        return 0

    if expected in arches:
        print(f"[pkg183] arch-verify OK: {pyd.name} embeds {expected} (embedded=[{embedded}])")
        return 0

    print("====================================================================")
    print(f"[pkg183] arch-verify FAIL: {pyd.name} embeds [{embedded}] but the local "
          f"GPU needs {expected}.")
    print("The built binary targets the WRONG CUDA arch (stale/shadowed")
    print("CMAKE_CUDA_ARCHITECTURES). Any cuobjdump register/stack or perf gate")
    print("numbers measured on this .pyd are INVALID (they would reflect JIT'd")
    print(f"PTX, not native {expected} SASS). Reconfigure with")
    print("-DCMAKE_CUDA_ARCHITECTURES=native and rebuild before verifying.")
    print("====================================================================")
    return ARCH_EXIT


def _cmd_arch_check(build_dir: Path) -> int:
    cache = build_dir / "CMakeCache.txt"
    if not cache.exists():
        return 0
    value = ""
    for line in cache.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith(("CMAKE_CUDA_ARCHITECTURES:", "CMAKE_CUDA_ARCHITECTURES=")):
            value = line.split("=", 1)[1].strip() if "=" in line else ""
            break
    tokens = [t for t in value.replace(";", " ").split() if t]
    legacy_only = bool(tokens) and all(t.isdigit() and int(t) < 70 for t in tokens)
    if legacy_only:
        print(f"[pkg183] arch-check ADVISORY: CMakeCache CMAKE_CUDA_ARCHITECTURES={value} "
              "looks legacy. This may be a harmless shadowed cache line (Ninja + "
              "ASTRORAY_CUDA_ARCHS=native) or a live stale arch; the post-build "
              "arch-verify gate is authoritative.")
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

    p_archv = sub.add_parser("arch-verify")
    p_archv.add_argument("--pyd-dir", required=True)
    p_archv.add_argument("--expect", default=None)

    p_archc = sub.add_parser("arch-check")
    p_archc.add_argument("--build-dir", required=True)

    args = parser.parse_args(argv)

    if args.cmd == "canary":
        return _cmd_canary(Path(args.repo_root).resolve(), args.build_dir)
    if args.cmd == "arch-verify":
        return _cmd_arch_verify(Path(args.pyd_dir).resolve(), args.expect)
    if args.cmd == "arch-check":
        return _cmd_arch_check(Path(args.build_dir).resolve())

    repo_root = Path(args.repo_root).resolve()
    build_dir = Path(args.build_dir).resolve()

    if args.cmd == "check":
        return _cmd_check(repo_root, build_dir)
    if args.cmd == "write":
        return _cmd_write(repo_root, build_dir, args.sha)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

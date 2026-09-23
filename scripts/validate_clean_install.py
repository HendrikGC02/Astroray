#!/usr/bin/env python
"""pkg278 gate (f) - clean-machine install capture/validator.

Gate (f) requires a fresh Blender profile, a ZIP installed through Blender's own
extension installer (NOT ``scripts/dev_addon.ps1`` or a source path), on a machine
WITHOUT the build toolchain, followed by one F12 render. Each of the five
mandatory checks is hash-locked to an artifact; a missing or hash-mismatched
check is RED.

This validator never fabricates a clean machine. When it runs on a developer
checkout (a source tree and/or a build toolchain are present) it reports the
machine ``ineligible`` and leaves the checks ``unmeasured`` -- the run must
happen on a genuinely clean host, and the command for that host is printed.

    python scripts/validate_clean_install.py                 # capture/report here
    python scripts/validate_clean_install.py --validate      # validate committed evidence
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import shutil
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE_DIR = REPO_ROOT / "docs" / "blender_parity" / "evidence" / "install-clean-machine"

MANDATORY_CHECKS = (
    "fresh_profile",        # no prior astroray addon / userpref entry
    "zip_identity",         # installed ZIP SHA-256 == recorded build artifact
    "installer_path",       # Blender's extension installer, not dev_addon.ps1/source
    "no_toolchain",         # no build toolchain and no source-tree fallback
    "f12_exit_zero",        # F12 exits 0 and writes the pinned PNG
)

CHECK_ARTIFACTS = {
    "fresh_profile": "profile_fresh.probe.json",
    "zip_identity": "zip_identity.probe.json",
    "installer_path": "installer_path.probe.json",
    "no_toolchain": "host_eligibility.probe.json",
    "f12_exit_zero": "f12_result.probe.json",
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _hex_digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _artifact(ref: Any, evidence_dir: Path, label: str) -> tuple[Path | None, str]:
    if not isinstance(ref, Mapping) or not isinstance(ref.get("path"), str) or not _hex_digest(ref.get("sha256")):
        return None, f"{label} must provide path and lower-case SHA-256"
    path = (evidence_dir / ref["path"]).resolve()
    try:
        path.relative_to(evidence_dir.resolve())
    except ValueError:
        return None, f"{label} escapes evidence directory"
    if not path.is_file():
        return None, f"{label} missing: {ref['path']}"
    if sha256_file(path) != ref["sha256"]:
        return None, f"{label} digest mismatch: {ref['path']}"
    return path, ""


def _valid_png(path: Path) -> bool:
    data = path.read_bytes()
    return (len(data) >= 24 and data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR"
            and int.from_bytes(data[16:20], "big") > 0 and int.from_bytes(data[20:24], "big") > 0)


def detect_toolchain() -> list[str]:
    """Names of build-toolchain programs found on PATH (empty on a clean host)."""
    found = []
    for exe in ("cl", "clang-cl", "cmake", "nvcc", "ninja", "make", "gcc", "g++"):
        if shutil.which(exe):
            found.append(exe)
    return found


def machine_eligibility(repo_root: Path) -> dict[str, Any]:
    """A clean-install run needs no toolchain AND no source-tree fallback."""
    toolchain = detect_toolchain()
    source_markers = [
        (repo_root / "CMakeLists.txt").is_file(),
        (repo_root / "src").is_dir(),
        (repo_root / "include").is_dir(),
        (repo_root / "build_cuda").is_dir(),
    ]
    source_tree = any(source_markers)
    reasons = []
    if toolchain:
        reasons.append(f"build toolchain on PATH: {', '.join(toolchain)}")
    if source_tree:
        reasons.append("source tree / build dir present (source-tree fallback possible)")
    return {
        "eligible": not reasons,
        "toolchain_present": bool(toolchain),
        "toolchain_programs": toolchain,
        "source_tree_present": source_tree,
        "reasons": reasons,
    }


def _check_evidence(name: str, check: Mapping[str, Any], evidence_dir: Path,
                    doc: Mapping[str, Any]) -> tuple[bool, str]:
    path = check.get("evidence_path")
    recorded = str(check.get("evidence_sha256") or "").lower()
    if not path:
        return False, "no evidence_path"
    if not _hex_digest(recorded):
        return False, "missing or malformed evidence_sha256"
    p = Path(path)
    if not p.is_absolute():
        p = evidence_dir / p
    if not p.is_file():
        return False, f"evidence artifact missing: {path}"
    if sha256_file(p) != recorded:
        return False, f"evidence hash mismatch: {path}"
    try:
        probe = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"probe is not structured JSON: {exc}"
    if not isinstance(probe, Mapping) or probe.get("schema") != "pkg278.clean_install_probe.v1":
        return False, "probe schema missing or unsupported"
    if probe.get("check") != name:
        return False, "probe check identity mismatch"
    if name == "fresh_profile":
        good = (probe.get("prior_astroray_addon") is False and probe.get("userpref_astroray") is False
                and isinstance(probe.get("profile_path"), str) and probe["profile_path"].strip()
                and isinstance(probe.get("addons"), list))
    elif name == "zip_identity":
        zip_path, why = _artifact(probe.get("zip"), evidence_dir, "release ZIP")
        good = zip_path is not None and probe.get("zip", {}).get("sha256") == (doc.get("zip") or {}).get("sha256")
        if not good: return False, why or "ZIP identity does not match checks document"
    elif name == "installer_path":
        good = (probe.get("installer") == "blender_extension_installer" and probe.get("installer_result") in ("FINISHED", ["FINISHED"])
                and isinstance(probe.get("installed_module_path"), str) and probe["installed_module_path"].strip()
                and isinstance(probe.get("zip_path"), str) and probe["zip_path"].strip()
                and probe.get("source_path_used") is False)
    elif name == "no_toolchain":
        good = (probe.get("toolchain_programs") == [] and probe.get("source_tree_fallback") is False
                and isinstance(probe.get("checked_path"), str) and probe["checked_path"].strip()
                and isinstance(probe.get("source_roots_checked"), list) and probe["source_roots_checked"] == []
                and isinstance(probe.get("loaded_module_path"), str) and probe["loaded_module_path"].strip())
    else:
        image = probe.get("image")
        image_path, why = _artifact(image, evidence_dir, "F12 image")
        good = (probe.get("exit_code") == 0 and image_path is not None and _valid_png(image_path)
                and isinstance(probe.get("loaded_module_path"), str) and probe["loaded_module_path"].strip())
        if not good: return False, why or "F12 output is not a readable PNG"
    return (True, "") if good else (False, "probe does not establish required condition")


def evaluate(checks_doc: Mapping[str, Any], evidence_dir: Path) -> dict[str, Any]:
    """Compute per-check + overall status from hash-verified artifacts."""
    checks = checks_doc.get("checks") or {}
    results: dict[str, Any] = {}
    for name in MANDATORY_CHECKS:
        entry = checks.get(name)
        if not isinstance(entry, Mapping):
            results[name] = {"pass": False, "status": "unmeasured",
                             "reason": "check absent"}
            continue
        if entry.get("evidence_path") is None:
            results[name] = {"pass": False, "status": "unmeasured",
                             "reason": "check not captured on this machine"}
            continue
        ok, why = _check_evidence(name, entry, evidence_dir, checks_doc)
        results[name] = {"pass": ok, "status": "green" if ok else "red", "reason": why}

    # The path claims must describe one installed extension, not independent
    # booleans captured from unrelated runs.
    if all(results[n]["pass"] for n in ("installer_path", "no_toolchain", "f12_exit_zero")):
        probes: dict[str, Any] = {}
        try:
            for name in ("installer_path", "no_toolchain", "f12_exit_zero"):
                probe_path = evidence_dir / checks[name]["evidence_path"]
                probes[name] = json.loads(probe_path.read_text(encoding="utf-8"))
            installed = probes["installer_path"]["installed_module_path"]
            if any(probes[n]["loaded_module_path"] != installed for n in ("no_toolchain", "f12_exit_zero")):
                results["installer_path"] = {"pass": False, "status": "red", "reason": "installed module path is inconsistent across probes"}
        except (KeyError, OSError, json.JSONDecodeError, TypeError):
            results["installer_path"] = {"pass": False, "status": "red", "reason": "cannot cross-check installed module paths"}

    machine = checks_doc.get("machine") or {}
    # Never trust a hand-set eligibility flag: derive it from captured host probes.
    no_toolchain = results.get("no_toolchain", {}).get("pass") is True
    eligible = no_toolchain and not bool(machine.get("toolchain_present")) and not bool(machine.get("source_tree_present"))
    all_green = all(r["pass"] for r in results.values())
    if not eligible:
        status = "ineligible"
    elif all_green:
        status = "green"
    elif any(r["status"] == "red" for r in results.values()):
        status = "red"
    else:
        status = "unmeasured"
    return {
        "status": status,
        "machine": machine,
        "checks": results,
        "all_green": all_green and eligible,
    }


def build_checks_doc(repo_root: Path, zip_path: Path | None = None,
                     evidence_dir: Path | None = None,
                     probes: Mapping[str, Path] | None = None) -> dict[str, Any]:
    """Capture what is knowable here; leave unmeasured what is not."""
    eligibility = machine_eligibility(repo_root)
    checks: dict[str, Any] = {}
    for name in MANDATORY_CHECKS:
        checks[name] = {"pass": False, "status": "unmeasured",
                        "evidence_path": None, "evidence_sha256": None,
                        "artifact": CHECK_ARTIFACTS[name]}
    doc: dict[str, Any] = {
        "schema": "pkg278.clean_install_checks.v1",
        "generated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "machine": eligibility,
        "zip": {"path": str(zip_path) if zip_path else None,
                "sha256": sha256_file(zip_path) if zip_path and Path(zip_path).is_file() else None},
        "checks": checks,
    }
    for name, probe_path in (probes or {}).items():
        if name not in MANDATORY_CHECKS or not probe_path.is_file():
            continue
        try:
            relative = probe_path.relative_to(evidence_dir or probe_path.parent)
        except ValueError:
            relative = probe_path
        doc["checks"][name] = {"evidence_path": str(relative),
                               "evidence_sha256": sha256_file(probe_path)}
    if not eligibility["eligible"]:
        doc["status"] = "ineligible"
        doc["reason"] = ("this machine is a developer checkout; a clean no-toolchain "
                         "host must run the capture")
    return doc


def write_template(evidence_dir: Path, doc: Mapping[str, Any]) -> Path:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    out = evidence_dir / "checks.json"
    out.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Clean-machine install validator (pkg278 gate f).")
    p.add_argument("--evidence-dir", type=Path, default=DEFAULT_EVIDENCE_DIR)
    p.add_argument("--zip", type=Path, default=None)
    p.add_argument("--probe", action="append", default=[], metavar="CHECK=PATH",
                   help="capture a hash-pinned structured probe (repeatable)")
    p.add_argument("--validate", action="store_true",
                   help="validate the committed checks.json instead of capturing")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    evidence_dir = Path(args.evidence_dir)
    if args.validate:
        checks_path = evidence_dir / "checks.json"
        if not checks_path.is_file():
            print(f"no checks.json at {checks_path}", file=sys.stderr)
            return 2
        doc = json.loads(checks_path.read_text(encoding="utf-8"))
        result = evaluate(doc, evidence_dir)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"clean-install status: {result['status'].upper()}")
            for name, entry in result["checks"].items():
                print(f"  {name}: {entry['status']}"
                      + (f" ({entry['reason']})" if entry["reason"] else ""))
        return 0 if result["status"] == "green" else 1

    probes: dict[str, Path] = {}
    for item in args.probe:
        name, sep, value = item.partition("=")
        if not sep or name not in MANDATORY_CHECKS:
            p.error(f"--probe must be CHECK=PATH for one of: {', '.join(MANDATORY_CHECKS)}")
        probes[name] = Path(value)
    doc = build_checks_doc(REPO_ROOT, args.zip, evidence_dir, probes)
    out = write_template(evidence_dir, doc)
    if args.json:
        print(json.dumps(doc, indent=2))
    else:
        print(f"wrote {out}")
        print(f"machine eligible: {doc['machine']['eligible']}")
        for reason in doc["machine"]["reasons"]:
            print(f"  - {reason}")
        if not doc["machine"]["eligible"]:
            print("This machine CANNOT produce gate (f) evidence. On a clean host run:")
            print("  python scripts/validate_clean_install.py --zip <release.zip> "
                  "--evidence-dir <copied evidence dir>")
    return 0


if __name__ == "__main__":
    sys.exit(main())

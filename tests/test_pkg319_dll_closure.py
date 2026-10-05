"""pkg319: release-ZIP DLL import-closure audit + gate (f) rehearsal rejection.

Pure host-side tests: synthetic PE files (no toolchain, no Blender) for the closure
resolver, and the pkg278 validator for the rehearsal contract.
"""
from __future__ import annotations

import importlib.util
import json
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


BBA = _load("pkg319_bba", ROOT / "scripts" / "build" / "build_blender_addon.py")
VCI = _load("pkg319_vci", ROOT / "scripts" / "validate_clean_install.py")
CAP = _load("pkg319_cap", ROOT / "tests" / "test_pkg278_clean_install_capture.py")


def make_pe(path: Path, imports=(), delay=()):
    """Write a minimal PE32+ whose import / delay-import tables list the given DLL names."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fa, sa = 0x200, 0x1000  # one .idata section: raw 0x200, virtual 0x1000
    names = list(imports) + list(delay)
    blob, name_rva = b"", {}
    desc_size = 20 * (len(imports) + 1) + 32 * (len(delay) + 1)
    for n in names:
        name_rva[n] = sa + desc_size + len(blob)
        blob += n.encode() + b"\0"
    imp = b"".join(struct.pack("<IIIII", 0, 0, 0, name_rva[n], 0) for n in imports) + b"\0" * 20
    dly = b"".join(struct.pack("<IIIIIIII", 1, name_rva[n], 0, 0, 0, 0, 0, 0) for n in delay) + b"\0" * 32
    section = (imp + dly + blob).ljust(0x200, b"\0")
    opt = bytearray(240)
    struct.pack_into("<H", opt, 0, 0x20B)
    struct.pack_into("<II", opt, 112 + 8 * 1, sa, len(imp))
    struct.pack_into("<II", opt, 112 + 8 * 13, sa + len(imp), len(dly))
    coff = struct.pack("<HHIIIHH", 0x8664, 1, 0, 0, 0, 240, 0x2022)
    sec = struct.pack("<8sIIIIIIHHI", b".idata", 0x1000, sa, 0x200, fa, 0, 0, 0, 0, 0x40000040)
    dos = bytearray(64)
    dos[:2] = b"MZ"
    struct.pack_into("<I", dos, 0x3C, 64)
    img = bytes(dos) + b"PE\0\0" + coff + bytes(opt) + sec
    path.write_bytes(img.ljust(fa, b"\0") + section)


@pytest.fixture
def host(tmp_path):
    """Fake System32 + Blender install + a staged addon with a healthy closure."""
    sys32 = tmp_path / "System32"
    for n in ("kernel32.dll", "vcruntime140.dll", "nvcuda.dll"):  # last two: dev-host-only, not OS
        make_pe(sys32 / n)
    blender = tmp_path / "Blender" / "blender.exe"
    blender.parent.mkdir()
    blender.write_bytes(b"")
    make_pe(blender.parent / "python313.dll")
    make_pe(blender.parent / "blender.crt" / "msvcp140.dll")
    stage = tmp_path / "stage"
    make_pe(stage / "astroray.pyd", ["python313.dll", "kernel32.dll", "msvcp140.dll", "helper.dll",
                                     "api-ms-win-crt-runtime-l1-1-0.dll", "oidn_main.dll"])
    make_pe(stage / "helper.dll", ["kernel32.dll"])
    make_pe(stage / "oidn" / "oidn_main.dll", ["kernel32.dll"])
    return stage, blender, sys32


def test_pe_import_reader_static_and_delay(tmp_path):
    make_pe(tmp_path / "x.dll", ["A.dll", "b.dll"], ["Late.dll"])
    assert BBA._pe_imports(tmp_path / "x.dll") == (["a.dll", "b.dll"], ["late.dll"])
    (tmp_path / "junk.dll").write_bytes(b"not a pe")
    assert BBA._pe_imports(tmp_path / "junk.dll") == ([], [])


@pytest.mark.skipif(sys.platform != "win32", reason="reads a real Windows PE")
def test_pe_import_reader_on_real_binary():
    static, _ = BBA._pe_imports(Path(sys.executable))
    assert any(n.startswith(("kernel32", "api-ms-win")) for n in static)


def test_healthy_stage_has_no_missing(host):
    stage, blender, sys32 = host
    assert BBA.check_dll_closure(stage, blender, sys32) == {"missing": [], "advisory": []}


def test_deleting_a_bundled_dll_is_caught_by_name(host):
    stage, blender, sys32 = host
    (stage / "helper.dll").unlink()
    assert BBA.check_dll_closure(stage, blender, sys32)["missing"] == [("astroray.pyd", "helper.dll")]


def test_transitive_dependency_is_checked(host):
    stage, blender, sys32 = host
    make_pe(stage / "helper.dll", ["kernel32.dll", "deep.dll"])
    assert BBA.check_dll_closure(stage, blender, sys32)["missing"] == [("helper.dll", "deep.dll")]


def test_redistributable_in_system32_does_not_mask_a_missing_bundle(host):
    # vcruntime140 / nvcuda sit in this fake System32 but a clean host lacks them.
    stage, blender, sys32 = host
    make_pe(stage / "helper.dll", ["vcruntime140.dll", "nvcuda.dll"])
    assert {d for _, d in BBA.check_dll_closure(stage, blender, sys32)["missing"]} == {"vcruntime140.dll", "nvcuda.dll"}


def test_blender_set_comes_from_its_install_dirs(host):
    stage, blender, sys32 = host
    (blender.parent / "python313.dll").unlink()
    assert BBA.check_dll_closure(stage, blender, sys32)["missing"] == [("astroray.pyd", "python313.dll")]


def test_optional_plugin_misses_are_advisory(host):
    stage, blender, sys32 = host
    make_pe(stage / "oidn" / "OpenImageDenoise_device_cuda.dll", ["kernel32.dll", "gpu_driver.dll"], ["late.dll"])
    res = BBA.check_dll_closure(stage, blender, sys32)
    assert res["missing"] == []
    assert sorted(res["advisory"]) == [("oidn/OpenImageDenoise_device_cuda.dll", "gpu_driver.dll"),
                                       ("oidn/OpenImageDenoise_device_cuda.dll", "late.dll")]


def test_audit_fails_on_missing_dll_and_skips_without_blender(host, monkeypatch):
    stage, blender, sys32 = host
    (stage / "helper.dll").unlink()
    monkeypatch.setattr(BBA.platform, "system", lambda: "Windows")
    monkeypatch.setattr(BBA, "check_dll_closure",
                        lambda s, b, system32=None, _f=BBA.check_dll_closure: _f(s, b, sys32))
    assert BBA.audit_dll_closure(stage, blender) is False
    assert BBA.audit_dll_closure(stage, None) is True  # no Blender: warn and skip


# ---------------------------------------------------------------- rehearsal contract

def _restamp(evidence: Path, doc: dict, name: str, **extra):
    """Edit one probe on disk and re-hash it, as a producer (not a forger) would."""
    path = evidence / VCI.CHECK_ARTIFACTS[name]
    value = json.loads(path.read_text())
    value.update(extra)
    path.write_text(json.dumps(value))
    doc["checks"][name]["evidence_sha256"] = VCI.sha256_file(path)


def test_rehearsal_probe_makes_otherwise_green_evidence_not_green(tmp_path):
    evidence = tmp_path / "e"
    doc, _ = CAP._valid(evidence)
    assert VCI.evaluate(doc, evidence)["status"] == "green"  # control: the fixture is valid
    _restamp(evidence, doc, "f12_exit_zero", rehearsal=True)
    res = VCI.evaluate(doc, evidence)
    assert (res["status"], res["reason"], res["all_green"]) == ("rehearsal", "rehearsal", False)


def test_rehearsal_flag_on_checks_json_alone_is_enough(tmp_path):
    evidence = tmp_path / "e"
    doc, _ = CAP._valid(evidence)
    doc["rehearsal"] = True
    assert VCI.evaluate(doc, evidence)["status"] == "rehearsal"


def test_validate_cli_returns_not_green_for_rehearsal(tmp_path, capsys):
    evidence = tmp_path / "e"
    doc, _ = CAP._valid(evidence)
    doc["rehearsal"] = True
    (evidence / "checks.json").write_text(json.dumps(doc))
    assert VCI.main(["--validate", "--evidence-dir", str(evidence)]) == 1
    assert "REHEARSAL" in capsys.readouterr().out


def test_rehearsal_env_whitelists_and_scrubs_path(tmp_path):
    blender = tmp_path / "Blender" / "blender.exe"
    blender.parent.mkdir()
    blender.write_bytes(b"")
    base = {"SystemRoot": r"C:\Windows", "PATH": r"C:\CUDA\bin;C:\mingw64\bin", "CUDA_PATH": r"C:\CUDA",
            "BLENDER_USER_CONFIG": "x", "OMP_NUM_THREADS": "8", "VCINSTALLDIR": "vs"}
    env = VCI._rehearsal_env(base, blender, no_gpu=False)
    assert env["PATH"].split(";" if sys.platform == "win32" else ":")[1] == str(blender.resolve().parent)
    assert "CUDA" not in env["PATH"] and "mingw" not in env["PATH"]
    assert "CUDA_PATH" not in env and "VCINSTALLDIR" not in env and env["BLENDER_USER_CONFIG"] == "x"
    assert env["PKG278_REHEARSAL"] == "1" and env["PKG278_DEVICE_MODE"] == "cpu" and "CUDA_VISIBLE_DEVICES" not in env
    env = VCI._rehearsal_env(base, blender, no_gpu=True)
    assert env["CUDA_VISIBLE_DEVICES"] == "-1" and env["PKG278_DEVICE_MODE"] == "auto"


def test_rehearse_refuses_the_committed_evidence_dir(capsys):
    with pytest.raises(SystemExit):
        VCI.main(["--capture", "--rehearse", "--blender", "b", "--zip", "z"])  # default evidence dir
    with pytest.raises(SystemExit):
        VCI.main(["--capture", "--rehearse", "--blender", "b", "--zip", "z",
                  "--evidence-dir", str(VCI.DEFAULT_EVIDENCE_DIR / "scratch")])
    with pytest.raises(SystemExit):
        VCI.main(["--validate", "--rehearse"])
    capsys.readouterr()

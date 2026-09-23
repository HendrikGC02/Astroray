"""Pure contract tests for pkg278's portable clean-host producer."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("pkg278_clean", ROOT / "scripts" / "validate_clean_install.py")
VCI = importlib.util.module_from_spec(spec); assert spec.loader; spec.loader.exec_module(VCI)

def _clean_host():
    absent = lambda name: {"path": name, "result": "absent"}
    return {"eligible": True, "path_tools": [{"tool": x, "result": "absent"} for x in VCI.TOOLS],
            "registry": [absent("vs"), absent("sdk"), absent("cuda")],
            "standard_roots": [absent("vs"), absent("sdk"), absent("cuda")],
            "source_markers": [absent("source")]}

def _valid(evidence):
    evidence.mkdir(); profile = (evidence / "isolated_profile").resolve(); extension = profile / "extensions" / "user_default" / "astroray"
    release = evidence / "release.zip"; release.write_bytes(b"zip")
    png = evidence / "f12.png"; png.write_bytes(b"\x89PNG\r\n\x1a\n" + (13).to_bytes(4,"big") + b"IHDR" + (1).to_bytes(4,"big") + (1).to_bytes(4,"big") + b"\x08\x02\x00\x00\x00")
    run = "11111111-1111-1111-1111-111111111111"; digest = VCI.sha256_file(release)
    base = {"schema": VCI.SCHEMA, "run_id": run, "zip_sha256": digest, "profile_root": str(profile)}
    probes = {
      "fresh_profile": {**base,"check":"fresh_profile","fresh":True,"prior_astroray_addon":False,"userpref_astroray":False},
      "zip_identity": {**base,"check":"zip_identity","zip":{"path":"release.zip","sha256":digest}},
      "installer_path": {**base,"check":"installer_path","installed_module_path":str(extension),"source_path_used":False,"command":{"exit_code":0,"argv":["blender","--command","extension","install-file","-r","user_default","-e",str(release.resolve())]},"listing_command":{"argv":["blender","--command","extension","list"]}},
      "no_toolchain": {**base,"check":"no_toolchain",**_clean_host()},
      "f12_exit_zero": {**base,"check":"f12_exit_zero","loaded_module_path":str(extension / "__init__.py"),"installed_module_root":str(extension),"f12_sentinel":"PKG278_CLEAN_F12 PASS","external_command":{"exit_code":0},"image":{"path":"f12.png","sha256":VCI.sha256_file(png)}}}
    checks = {}
    for name, probe in probes.items():
        path = evidence / VCI.CHECK_ARTIFACTS[name]; path.write_text(json.dumps(probe), encoding="utf-8"); checks[name] = {"evidence_path":path.name,"evidence_sha256":VCI.sha256_file(path)}
    return {"schema":VCI.CHECKS_SCHEMA,"run_id":run,"zip":{"path":"release.zip","sha256":digest},"checks":checks,"machine":_clean_host()}, probes

def test_producer_shaped_capture_reduces_green_and_tampering_fails_closed(tmp_path):
    doc, _ = _valid(tmp_path / "evidence")
    assert VCI.evaluate(doc, tmp_path / "evidence")["status"] == "green"
    probe = tmp_path / "evidence" / VCI.CHECK_ARTIFACTS["installer_path"]
    value = json.loads(probe.read_text()); value["command"]["argv"][-1] = "C:/outside.zip"; probe.write_text(json.dumps(value))
    # The signed probe itself changed, so it fails before any caller claim can help.
    assert VCI.evaluate(doc, tmp_path / "evidence")["status"] == "red"

@pytest.mark.parametrize("field,value", [("run_id","stale"), ("profile_root","C:/outside"), ("loaded_module_path","C:/source/astroray/__init__.py")])
def test_linkage_and_import_path_are_not_caller_flags(tmp_path, field, value):
    evidence = tmp_path / "evidence"; doc, _ = _valid(evidence)
    target = "f12_exit_zero" if field == "loaded_module_path" else "fresh_profile"
    path = evidence / VCI.CHECK_ARTIFACTS[target]; probe = json.loads(path.read_text()); probe[field] = value; path.write_text(json.dumps(probe)); doc["checks"][target]["evidence_sha256"] = VCI.sha256_file(path)
    assert VCI.evaluate(doc, evidence)["status"] == "red"

def test_capture_rejects_developer_host_before_any_subprocess(tmp_path, monkeypatch):
    blender = tmp_path / "blender.exe"; blender.write_bytes(b"x"); archive = tmp_path / "release.zip"; archive.write_bytes(b"zip")
    monkeypatch.setattr(VCI, "machine_eligibility", lambda root: {"eligible":False,"reasons":["toolchain"]})
    monkeypatch.setattr(VCI.subprocess, "run", lambda *a, **k: pytest.fail("Blender must not start"))
    with pytest.raises(ValueError, match="ineligible"):
        VCI.capture(blender, archive, tmp_path / "evidence")

def test_capture_uses_exact_cli_and_isolated_profile_with_fake_blender(tmp_path, monkeypatch):
    blender = tmp_path / "blender.exe"; blender.write_bytes(b"x")
    archive = tmp_path / "release.zip"; archive.write_bytes(b"zip")
    monkeypatch.setattr(VCI, "machine_eligibility", lambda root: _clean_host())
    calls = []
    def fake_run(argv, env, **kwargs):
        calls.append((argv, env)); evidence = Path(env["PKG278_EVIDENCE"]); run = env["PKG278_RUN_ID"]; digest = env["PKG278_ZIP_SHA256"]
        base = {"schema":VCI.SCHEMA,"run_id":run,"zip_sha256":digest,"profile_root":str((evidence/"isolated_profile").resolve())}
        if argv[-1] == "profile":
            (evidence / VCI.CHECK_ARTIFACTS["fresh_profile"]).write_text(json.dumps({**base,"check":"fresh_profile","fresh":True,"prior_astroray_addon":False,"userpref_astroray":False}))
            out = "PKG278_CLEAN_PROFILE PASS"
        elif argv[-1] == "render":
            image = evidence / "f12.png"; image.write_bytes(b"\x89PNG\r\n\x1a\n" + (13).to_bytes(4,"big") + b"IHDR" + (1).to_bytes(4,"big") + (1).to_bytes(4,"big") + b"\x08\x02\x00\x00\x00")
            root = (evidence/"isolated_profile"/"extensions"/"user_default"/"astroray").resolve()
            (evidence / VCI.CHECK_ARTIFACTS["f12_exit_zero"]).write_text(json.dumps({**base,"check":"f12_exit_zero","loaded_module_path":str(root/"__init__.py"),"installed_module_root":str(root),"f12_sentinel":"PKG278_CLEAN_F12 PASS","image":{"path":"f12.png","sha256":VCI.sha256_file(image)}}))
            out = "PKG278_CLEAN_F12 PASS"
        else: out = "astroray" if argv[-1] == "list" else "installed"
        return SimpleNamespace(returncode=0, stdout=out)
    monkeypatch.setattr(VCI.subprocess, "run", fake_run)
    result = VCI.capture(blender, archive, tmp_path / "evidence")
    assert result["status"] == "green"
    assert all(key in calls[0][1] for key in ("BLENDER_USER_CONFIG","BLENDER_USER_SCRIPTS","BLENDER_USER_EXTENSIONS","BLENDER_USER_DATAFILES","BLENDER_USER_RESOURCES"))
    assert calls[1][0][1:] == ["--command","extension","install-file","-r","user_default","-e",str((tmp_path/"evidence"/"release.zip").resolve())]
    assert calls[2][0][1:] == ["--command","extension","list"]

def test_profile_environment_has_all_five_paths_and_must_be_fresh(tmp_path):
    env, values = VCI._profile_env(tmp_path / "evidence")
    assert set(values) == {"BLENDER_USER_CONFIG","BLENDER_USER_SCRIPTS","BLENDER_USER_EXTENSIONS","BLENDER_USER_DATAFILES","BLENDER_USER_RESOURCES"}
    assert all(Path(value).is_relative_to(tmp_path / "evidence") for value in values.values())
    (tmp_path / "evidence" / "isolated_profile").mkdir(parents=True)
    with pytest.raises(ValueError, match="already exists"):
        VCI._profile_env(tmp_path / "evidence")

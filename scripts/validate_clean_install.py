#!/usr/bin/env python
"""Capture and reduce pkg278 gate-(f) clean-host evidence."""
from __future__ import annotations

import argparse
import binascii
import datetime as dt
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import uuid
import zlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE_DIR = REPO_ROOT / "docs" / "blender_parity" / "evidence" / "install-clean-machine"
SCHEMA = "pkg278.clean_install_probe.v2"; CHECKS_SCHEMA = "pkg278.clean_install_checks.v2"
MANDATORY_CHECKS = ("fresh_profile", "zip_identity", "installer_path", "no_toolchain", "f12_exit_zero")
CHECK_ARTIFACTS = dict(zip(MANDATORY_CHECKS, ("profile_fresh.probe.json", "zip_identity.probe.json", "installer_path.probe.json", "host_eligibility.probe.json", "f12_result.probe.json")))
TOOLS = ("cl", "clang-cl", "cmake", "nvcc", "ninja", "make", "gcc", "g++")
REGISTRY_KEYS = (r"SOFTWARE\Microsoft\VisualStudio\SxS\VS7", r"SOFTWARE\Microsoft\Windows Kits\Installed Roots", r"SOFTWARE\NVIDIA Corporation\GPU Computing Toolkit\CUDA")
ROOT_NAMES = ("visual_studio", "windows_kits", "cuda")
SOURCE_MARKERS = ("CMakeLists.txt", "src", "include", "build_cuda", "build")
def sha256_file(path: Path) -> str: return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def _hex(x: Any) -> bool: return isinstance(x,str) and len(x)==64 and all(c in "0123456789abcdef" for c in x)
def _write(path: Path, value: Mapping[str,Any]) -> Path: path.write_text(json.dumps(value,indent=2,sort_keys=True),encoding="utf-8"); return path
def _artifact(ref: Any, base: Path, label: str) -> tuple[Path|None,str]:
    if not isinstance(ref,Mapping) or not isinstance(ref.get("path"),str) or not _hex(ref.get("sha256")): return None,f"{label} needs a relative path and SHA-256"
    path=(base/ref["path"]).resolve()
    try: path.relative_to(base.resolve())
    except ValueError: return None,f"{label} escapes evidence directory"
    if not path.is_file(): return None,f"{label} missing"
    if sha256_file(path)!=ref["sha256"]: return None,f"{label} hash mismatch"
    return path,""
def _png(path: Path) -> bool:
    """Validate a complete, zlib-decodable non-interlaced PNG without Pillow."""
    try:
        data = path.read_bytes()
        if data[:8] != b"\x89PNG\r\n\x1a\n": return False
        offset, ihdr, idat, saw_iend = 8, None, bytearray(), False
        while offset < len(data):
            if offset + 12 > len(data): return False
            length = struct.unpack(">I", data[offset:offset + 4])[0]
            if length > len(data) - offset - 12: return False
            kind, payload = data[offset + 4:offset + 8], data[offset + 8:offset + 8 + length]
            if struct.unpack(">I", data[offset + 8 + length:offset + 12 + length])[0] != (binascii.crc32(kind + payload) & 0xffffffff): return False
            offset += 12 + length
            if kind == b"IHDR":
                if ihdr is not None or length != 13: return False
                ihdr = payload
            elif kind == b"IDAT":
                if ihdr is None: return False
                idat.extend(payload)
            elif kind == b"IEND":
                if length or offset != len(data): return False
                saw_iend = True; break
        if ihdr is None or not idat or not saw_iend: return False
        width, height, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", ihdr)
        channels = {0: 1, 2: 3, 4: 2, 6: 4}.get(color)
        if not width or not height or depth != 8 or channels is None or compression or filtering or interlace: return False
        return len(zlib.decompress(bytes(idat))) == height * (1 + width * channels)
    except (OSError, struct.error, zlib.error): return False
def _path_probe(path: Path) -> dict[str,str]:
    try: return {"path":str(path),"result":"present" if path.exists() else "absent"}
    except OSError as exc: return {"path":str(path),"result":"unknown","error":str(exc)}
def _registry_probe() -> list[dict[str,str]]:
    keys = REGISTRY_KEYS
    try:
        import winreg  # type: ignore
    except ImportError as exc: return [{"key":key,"result":"unknown","error":f"winreg unavailable: {exc}"} for key in keys]
    answer=[]
    for key in keys:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,key,0,winreg.KEY_READ|winreg.KEY_WOW64_64KEY) as handle: answer.append({"key":key,"result":"present","values":str(winreg.QueryInfoKey(handle)[1])})
        except FileNotFoundError: answer.append({"key":key,"result":"absent"})
        except OSError as exc: answer.append({"key":key,"result":"unknown","error":str(exc)})
    return answer
def machine_eligibility(repo_root: Path) -> dict[str,Any]:
    path_tools=[{"tool":tool,"path":shutil.which(tool),"result":"present" if shutil.which(tool) else "absent"} for tool in TOOLS]
    roots=[Path(os.environ.get("ProgramFiles",r"C:\Program Files"))/"Microsoft Visual Studio",Path(os.environ.get("ProgramFiles(x86)",r"C:\Program Files (x86)"))/"Windows Kits",Path(os.environ.get("ProgramFiles",r"C:\Program Files"))/"NVIDIA GPU Computing Toolkit"/"CUDA"]
    standard_roots=[{"name": name, **_path_probe(path)} for name, path in zip(ROOT_NAMES, roots)]; registry=_registry_probe(); source_markers=[{"marker": name, **_path_probe(repo_root/name)} for name in SOURCE_MARKERS]
    source_tree=any(x["result"]=="present" for x in source_markers); unknown=any(x["result"]=="unknown" for x in registry+standard_roots+source_markers)
    present=any(x["result"]=="present" for x in path_tools+registry+standard_roots) or source_tree
    reasons=[]
    if present: reasons.append("build toolchain, installed product, standard toolchain root, or source tree detected")
    if unknown: reasons.append("installed-product/root probe is unreadable or unsupported")
    return {"eligible":not present and not unknown,"probe_version":2,"path_tools":path_tools,"registry":registry,"standard_roots":standard_roots,"source_markers":source_markers,"source_tree_present":source_tree,"reasons":reasons}
def _profile_env(evidence: Path) -> tuple[dict[str,str],dict[str,str]]:
    root=evidence/"isolated_profile"; values={"BLENDER_USER_CONFIG":root/"config","BLENDER_USER_SCRIPTS":root/"scripts","BLENDER_USER_EXTENSIONS":root/"extensions","BLENDER_USER_DATAFILES":root/"datafiles","BLENDER_USER_RESOURCES":root/"resources"}
    if root.exists(): raise ValueError("isolated profile root already exists")
    actual={key:str(path.resolve()) for key,path in values.items()}; return {**os.environ,**actual},actual
def _profile_paths_valid(paths: Any, evidence: Path) -> bool:
    root = (evidence / "isolated_profile").resolve()
    expected = {"BLENDER_USER_CONFIG": root / "config", "BLENDER_USER_SCRIPTS": root / "scripts",
                "BLENDER_USER_EXTENSIONS": root / "extensions", "BLENDER_USER_DATAFILES": root / "datafiles",
                "BLENDER_USER_RESOURCES": root / "resources"}
    return isinstance(paths, Mapping) and set(paths) == set(expected) and all(paths[key] == str(value) for key, value in expected.items())
def _clean_inventory(probe: Mapping[str, Any]) -> bool:
    groups = (("path_tools", "tool", TOOLS), ("registry", "key", REGISTRY_KEYS),
              ("standard_roots", "name", ROOT_NAMES), ("source_markers", "marker", SOURCE_MARKERS))
    for field, identity, expected in groups:
        values = probe.get(field)
        if not isinstance(values, list) or [item.get(identity) if isinstance(item, Mapping) else None for item in values] != list(expected): return False
        if any(not isinstance(item, Mapping) or item.get("result") != "absent" for item in values): return False
    return probe.get("eligible") is True and probe.get("source_tree_present") is False
def _log(ref: Any, evidence: Path, label: str, required: str = "") -> tuple[bool, str]:
    path, why = _artifact(ref, evidence, label)
    if path is None: return False, why
    try: text = path.read_text(encoding="utf-8")
    except OSError as exc: return False, str(exc)
    return (not required or required in text), "" if not required or required in text else f"{label} lacks required sentinel/listing"
def _run(argv:list[str],env:Mapping[str,str],log:Path)->dict[str,Any]:
    result=subprocess.run(argv,env=dict(env),text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,check=False); log.write_text(result.stdout or "",encoding="utf-8"); return {"argv":argv,"exit_code":result.returncode,"log":{"path":log.name,"sha256":sha256_file(log)}}
def _payload()->str:
    return r'''import bpy, hashlib, importlib, json, os, sys
from pathlib import Path
root=Path(os.environ["BLENDER_USER_EXTENSIONS"]).resolve(); evidence=Path(os.environ["PKG278_EVIDENCE"]).resolve(); run_id=os.environ["PKG278_RUN_ID"]; zip_sha=os.environ["PKG278_ZIP_SHA256"]
def write(name,value):
 value.update({"schema":"pkg278.clean_install_probe.v2","run_id":run_id,"zip_sha256":zip_sha,"profile_root":str(root.parent)}); (evidence/name).write_text(json.dumps(value,indent=2),encoding="utf-8")
phase=sys.argv[sys.argv.index("--")+1] if "--" in sys.argv else ""
addons=sorted(bpy.context.preferences.addons.keys()); astr=[x for x in addons if x=="astroray" or x.endswith(".astroray")]
if phase=="profile":
 fresh=not astr and (not root.exists() or not any(p.name.lower()=="astroray" for p in root.rglob("*"))); write("profile_fresh.probe.json",{"check":"fresh_profile","profile_paths":{k:os.environ[k] for k in os.environ if k.startswith("BLENDER_USER_")},"addons":addons,"prior_astroray_addon":not not astr,"userpref_astroray":not not astr,"fresh":fresh}); print("PKG278_CLEAN_PROFILE "+("PASS" if fresh else "FAIL")); sys.exit(0 if fresh else 8)
if phase!="render": raise RuntimeError("unknown phase")
bpy.ops.wm.read_factory_settings(use_empty=True)
mod=importlib.import_module("bl_ext.user_default.astroray"); installed=Path(mod.__file__).resolve(); expected=(root/"user_default"/"astroray").resolve()
if expected not in installed.parents: raise RuntimeError("extension imported outside isolated root")
bpy.ops.preferences.addon_enable(module="bl_ext.user_default.astroray")
if "bl_ext.user_default.astroray" not in bpy.context.preferences.addons: raise RuntimeError("isolated extension was not enabled")
scene=bpy.context.scene; scene.render.engine="CUSTOM_RAYTRACER"
if scene.render.engine != "CUSTOM_RAYTRACER": raise RuntimeError("custom render engine was not selected")
scene.render.resolution_x=64; scene.render.resolution_y=64; scene.render.resolution_percentage=100; scene.render.filepath=str(evidence/"f12.png")
bpy.ops.mesh.primitive_cube_add(); bpy.ops.object.light_add(type="POINT",location=(4,-4,5)); bpy.context.object.data.energy=1000; bpy.ops.object.camera_add(location=(7,-7,5)); scene.camera=bpy.context.object; bpy.context.object.rotation_euler=(0.9,0,0.78); bpy.ops.render.render(write_still=True)
image=Path(scene.render.filepath)
if not image.is_file(): raise RuntimeError("F12 did not write PNG")
write("f12_result.probe.json",{"check":"f12_exit_zero","loaded_module_path":str(installed),"installed_module_root":str(expected),"enabled_extension":"bl_ext.user_default.astroray","extension_listing":sorted(x for x in sys.modules if x.endswith("astroray")),"engine_id":scene.render.engine,"image":{"path":image.name,"sha256":hashlib.sha256(image.read_bytes()).hexdigest()},"f12_sentinel":"PKG278_CLEAN_F12 PASS"}); print("PKG278_CLEAN_F12 PASS")
'''
def _ref(path:Path,evidence:Path)->dict[str,str]: return {"path":str(path.relative_to(evidence)),"sha256":sha256_file(path)}
def capture(blender:Path,zip_path:Path,evidence:Path)->dict[str,Any]:
    if not blender.is_file(): raise ValueError("Blender executable is missing")
    if not zip_path.is_file(): raise ValueError("release ZIP is missing")
    if evidence.exists(): raise ValueError("evidence directory must not already exist")
    # In a repository this is the checkout root; in a copied standalone file it
    # is merely the parent directory, which is exactly the source-fallback area
    # that must be absent on an eligible host.
    host=machine_eligibility(REPO_ROOT)
    if not host["eligible"]: raise ValueError("host is ineligible; no Blender subprocess was launched")
    evidence.mkdir(parents=True); run_id=str(uuid.uuid4()); env,profile=_profile_env(evidence); copied=evidence/"release.zip"; shutil.copyfile(zip_path,copied); digest=sha256_file(copied); env.update({"PKG278_EVIDENCE":str(evidence.resolve()),"PKG278_RUN_ID":run_id,"PKG278_ZIP_SHA256":digest}); payload=evidence/"clean_install_probe.py"; payload.write_text(_payload(),encoding="utf-8")
    base={"schema":SCHEMA,"run_id":run_id,"zip_sha256":digest,"profile_root":str((evidence/"isolated_profile").resolve())}; host.update(base); _write(evidence/CHECK_ARTIFACTS["no_toolchain"],{**host,"check":"no_toolchain","loaded_module_path":None})
    pre=_run([str(blender),"--background","--factory-startup","--python",str(payload),"--","profile"],env,evidence/"profile.log")
    if pre["exit_code"]!=0 or "PKG278_CLEAN_PROFILE PASS" not in (evidence/"profile.log").read_text(encoding="utf-8"): raise RuntimeError("fresh isolated-profile probe failed")
    profile_doc=json.loads((evidence/CHECK_ARTIFACTS["fresh_profile"]).read_text(encoding="utf-8")); profile_doc["command"]=pre; _write(evidence/CHECK_ARTIFACTS["fresh_profile"],profile_doc)
    install=_run([str(blender),"--command","extension","install-file","-r","user_default","-e",str(copied)],env,evidence/"installer.log"); listing=_run([str(blender),"--command","extension","list"],env,evidence/"extension-list.log")
    if install["exit_code"]!=0 or listing["exit_code"]!=0 or "astroray" not in (evidence/"extension-list.log").read_text(encoding="utf-8").lower(): raise RuntimeError("extension installer/listing failed")
    installed=str((evidence/"isolated_profile"/"extensions"/"user_default"/"astroray").resolve()); _write(evidence/CHECK_ARTIFACTS["zip_identity"],{**base,"check":"zip_identity","zip":_ref(copied,evidence)}); _write(evidence/CHECK_ARTIFACTS["installer_path"],{**base,"check":"installer_path","installer":"blender_extension_installer","command":install,"listing_command":listing,"installed_module_path":installed,"source_path_used":False,"zip":_ref(copied,evidence)})
    post=_run([str(blender),"--background","--factory-startup","--python",str(payload),"--","render"],env,evidence/"f12.log"); f12=evidence/CHECK_ARTIFACTS["f12_exit_zero"]
    if post["exit_code"]!=0 or not f12.is_file() or "PKG278_CLEAN_F12 PASS" not in (evidence/"f12.log").read_text(encoding="utf-8"): raise RuntimeError("F12 probe failed")
    f12_doc=json.loads(f12.read_text(encoding="utf-8")); f12_doc["external_command"]=post; _write(f12,f12_doc)
    checks={name:{"evidence_path":CHECK_ARTIFACTS[name],"evidence_sha256":sha256_file(evidence/CHECK_ARTIFACTS[name])} for name in MANDATORY_CHECKS}; doc={"schema":CHECKS_SCHEMA,"generated":dt.datetime.now(dt.timezone.utc).isoformat(),"run_id":run_id,"zip":_ref(copied,evidence),"profile":profile,"machine":host,"checks":checks}; _write(evidence/"checks.json",doc); return evaluate(doc,evidence)
def _check(name:str,probe:Mapping[str,Any],doc:Mapping[str,Any],evidence:Path)->tuple[bool,str]:
    common=probe.get("schema")==SCHEMA and probe.get("check")==name and probe.get("run_id")==doc.get("run_id") and probe.get("zip_sha256")==(doc.get("zip") or {}).get("sha256") and probe.get("profile_root")==str((evidence/"isolated_profile").resolve())
    if not common: return False,"probe identity does not bind run/ZIP/profile"
    isolated=str((evidence/"isolated_profile"/"extensions"/"user_default"/"astroray").resolve())
    if name=="fresh_profile":
        command = probe.get("command") or {}
        log_ok, why = _log(command.get("log"), evidence, "profile log", "PKG278_CLEAN_PROFILE PASS")
        good = (probe.get("fresh") is True and probe.get("prior_astroray_addon") is False
                and probe.get("userpref_astroray") is False and _profile_paths_valid(probe.get("profile_paths"), evidence)
                and command.get("exit_code") == 0 and log_ok)
        return good, why or "fresh profile paths/state missing"
    if name=="zip_identity": p,why=_artifact(probe.get("zip"),evidence,"copied ZIP"); return p is not None and probe.get("zip")==doc.get("zip"),why or "ZIP differs"
    if name=="installer_path":
        command=probe.get("command") or {}; argv=command.get("argv") or []; listing=(probe.get("listing_command") or {}).get("argv") or []; expected=["--command","extension","install-file","-r","user_default","-e",str((evidence/"release.zip").resolve())]
        installer_log, why = _log(command.get("log"), evidence, "installer log")
        listing_command = probe.get("listing_command") or {}
        listing_log, listing_why = _log(listing_command.get("log"), evidence, "extension-list log", "astroray")
        good = (command.get("exit_code")==0 and installer_log and argv[1:]==expected
                and listing[1:]==["--command","extension","list"] and listing_command.get("exit_code") == 0 and listing_log
                and probe.get("installed_module_path")==isolated and probe.get("source_path_used") is False)
        return good, why or listing_why or "installer command/path is not the isolated Blender extension install"
    if name=="no_toolchain":
        clean=_clean_inventory(probe); return clean,"host inventory is missing, present, or unknown"
    image,why=_artifact(probe.get("image"),evidence,"F12 image"); command=probe.get("external_command") or {}; log_ok, log_why = _log(command.get("log"), evidence, "F12 log", "PKG278_CLEAN_F12 PASS")
    try: loaded_inside = Path(probe.get("loaded_module_path", "")).resolve().is_relative_to(Path(isolated))
    except OSError: loaded_inside = False
    good = (command.get("exit_code")==0 and log_ok and probe.get("f12_sentinel")=="PKG278_CLEAN_F12 PASS"
            and probe.get("engine_id") == "CUSTOM_RAYTRACER" and probe.get("enabled_extension") == "bl_ext.user_default.astroray"
            and probe.get("installed_module_root")==isolated and loaded_inside and image is not None and _png(image))
    return good, why or log_why or "F12 engine/extension/sentinel/path/image invalid"
def evaluate(doc:Mapping[str,Any],evidence:Path)->dict[str,Any]:
    results={}; probes={}
    for name in MANDATORY_CHECKS:
        entry=(doc.get("checks") or {}).get(name)
        if not isinstance(entry, Mapping) or entry.get("evidence_path") is None:
            results[name]={"pass":False,"status":"unmeasured","reason":"check not captured on this host"}; continue
        ref = {"path": entry.get("evidence_path"), "sha256": entry.get("evidence_sha256")} if isinstance(entry, Mapping) else None
        path,why=_artifact(ref,evidence,name)
        if path is None: results[name]={"pass":False,"status":"unmeasured" if entry is None else "red","reason":why}; continue
        try: probe=json.loads(path.read_text(encoding="utf-8")); probes[name]=probe; ok,why=_check(name,probe,doc,evidence)
        except (OSError,json.JSONDecodeError) as exc: ok,why=False,str(exc)
        results[name]={"pass":ok,"status":"green" if ok else "red","reason":why}
    ids=[p.get("run_id") for p in probes.values()]; linked=len(probes)==5 and len(set(ids))==1 and ids[0]==doc.get("run_id")
    if probes and not linked and "installer_path" in results: results["installer_path"]={"pass":False,"status":"red","reason":"missing, duplicate, stale, or mismatched run ID"}
    green=linked and all(x["pass"] for x in results.values())
    machine = doc.get("machine", {})
    status = "green" if green else ("ineligible" if machine.get("eligible") is False else ("red" if probes else "unmeasured"))
    return {"status":status,"all_green":green,"checks":results,"machine":machine}
def main(argv:list[str]|None=None)->int:
    p=argparse.ArgumentParser(); p.add_argument("--capture",action="store_true"); p.add_argument("--validate",action="store_true"); p.add_argument("--blender",type=Path); p.add_argument("--zip",type=Path); p.add_argument("--evidence-dir",type=Path,default=DEFAULT_EVIDENCE_DIR); p.add_argument("--json",action="store_true"); args=p.parse_args(argv)
    if args.capture==args.validate: p.error("choose exactly one of --capture or --validate")
    try:
        if args.capture:
            if not args.blender or not args.zip: p.error("--capture requires --blender and --zip")
            result=capture(args.blender,args.zip,args.evidence_dir)
        else: result=evaluate(json.loads((args.evidence_dir/"checks.json").read_text(encoding="utf-8")),args.evidence_dir)
    except (OSError,ValueError,RuntimeError,json.JSONDecodeError) as exc: print(f"clean-install: {exc}",file=sys.stderr); return 2
    print(json.dumps(result,indent=2) if args.json else f"clean-install status: {result['status'].upper()}"); return 0 if result["status"]=="green" else 1
if __name__=="__main__": raise SystemExit(main())

# Clean-machine install (Pillar-4 exit gate (f))

Gate (f) is measured only on an eligible Windows machine. It must have no
Astroray checkout, build output, compiler/toolchain, Visual Studio, Windows SDK,
or CUDA toolkit. The capture does not use the owner’s Blender profile.

Copy the release ZIP and `validate_clean_install.py` to a non-source directory.
Use Blender's bundled Python, so the machine needs no separate Python install:

```powershell
$blender = 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe'
$python = 'C:\Program Files\Blender Foundation\Blender 5.2\5.2\python\bin\python.exe'
& $python C:\pkg278-clean\validate_clean_install.py --capture `
  --blender $blender --zip C:\pkg278-clean\astroray-release.zip `
  --evidence-dir C:\pkg278-clean\evidence
& $python C:\pkg278-clean\validate_clean_install.py --validate `
  --evidence-dir C:\pkg278-clean\evidence --json
```

`--capture` first scans PATH, installed-product registry keys, standard Visual
Studio/SDK/CUDA roots, and source-tree markers. A present, unreadable, denied,
or unsupported probe makes the host ineligible or unmeasured and stops before
Blender starts. PATH absence alone is therefore not evidence of a clean host.

For an eligible host, capture creates five isolated `BLENDER_USER_*` roots under
the empty evidence directory, copies and hashes the ZIP, then runs:

1. a fresh-profile Blender probe;
2. `blender --command extension install-file -r user_default -e <copied ZIP>`;
3. `blender --command extension list`;
4. a Blender F12 probe importing only `bl_ext.user_default.astroray`.

The evidence directory contains the five hash-pinned JSON probes, copied ZIP,
installer/list/F12 logs, generated Blender payload, F12 PNG, and `checks.json`.
All share one run ID, copied ZIP digest, and profile identity. `--validate`
rederives the result from those files; hand-written success fields, a stale run,
a source import, an installer command with different arguments, a missing F12
sentinel, or a non-PNG image fails closed.

This developer checkout is ineligible and must never produce gate-(f) evidence.
An eligible-host capture remains an external measurement blocker until it is run.

## Without a clean host (pkg319)

Two checks catch the likely failure classes on a developer machine. Neither is
gate-(f) evidence; row (f) stays unmeasured until an eligible host runs the
capture above.

**ZIP DLL closure (build time).** `build_blender_addon.py` audits the staged
addon before zipping (`--no-check-closure` skips it; `--closure-only [STAGE_DIR]`
audits an existing `dist/astroray` and exits). It reads the PE import tables of
every `.pyd`/`.dll` and fails, naming `binary -> dll`, when a static import is
not satisfied by the stage root or `oidn/`, Blender's own DLLs (`blender.exe`
dir, `blender.crt`, `blender.shared`), an API-set name, or an OS component of
System32. PATH is not searched (extension modules load with
`LOAD_LIBRARY_SEARCH_DEFAULT_DIRS`). VC++ runtime, NVIDIA and AMD driver DLLs in
System32 do not count: a clean host lacks them. Delay-load imports and OIDN /
TBB optional plugins (`OpenImageDenoise_device_*`, `tbbbind*`) are advisory.

**Rehearsal (capture time).**

```powershell
python scripts/validate_clean_install.py --capture --rehearse `
  --blender $blender --zip dist\astroray-<ver>-cuda.zip --evidence-dir C:\scratch\f-rehearsal
# add --rehearse-no-gpu for CUDA_VISIBLE_DEVICES=-1 and device_mode=auto
```

It runs the same capture on this host with fresh `BLENDER_USER_*` roots, a
whitelisted environment (PATH = System32 + Blender only; no CUDA/MinGW/VS), the
CPU device (`--rehearse-no-gpu`: the no-GPU fallback leg), and additionally
asserts the native `astroray` module loaded from the installed extension. Every
artifact is stamped `rehearsal: true`; `--validate` (and the gate manifest)
return status `rehearsal`, never green. The evidence directory must be outside
`docs/blender_parity/evidence/install-clean-machine/`. Keep it on a short path:
an install path over 260 characters makes the Disney compensation tables fail to
load (the longest data file name pushes past MAX_PATH).

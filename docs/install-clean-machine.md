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

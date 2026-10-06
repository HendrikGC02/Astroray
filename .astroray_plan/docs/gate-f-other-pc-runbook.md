# Gate (f) on another PC: runbook

Owner decision 2026-10-06: gate (f) (clean install) is measured on a second PC.

## The second PC must have
- Windows 10/11 x64. An NVIDIA GPU and driver are optional: without one, the addon must fall back to CPU, and that fallback is part of what the gate tests.
- Blender 5.2 installed in the default location.
- **None of these:**
  - Visual Studio or Build Tools
  - Windows Kits
  - the CUDA Toolkit (the driver alone is fine)
  - MinGW, CMake, Ninja, or gcc/clang on PATH
  - an Astroray checkout
- If any of them is present, the script refuses to run (`host is ineligible`). That refusal is how the gate works, not a bug.

## Copy over (USB stick or OneDrive web download, not a synced repo folder)
1. `dist/astroray-4.0.0-cuda.zip`. Use the ZIP from the build of current main, not an older one. Current: build `beda188+20261005T213918Z`, 1.06 GB, SHA-256 `771d2a666f289d889afc4bdec3860cc856bb3bc761f405f5a72d76e234df3cf6` (the same build that measured gate (a) green). On the second PC, check it with `Get-FileHash <zip>`.
2. `scripts/validate_clean_install.py`, on its own. Put it in an empty folder such as `C:\gatef\`, with nothing from the repo next to it.

## Run (PowerShell on the second PC)
```
cd C:\gatef
& "C:\Program Files\Blender Foundation\Blender 5.2\5.2\python\bin\python.exe" validate_clean_install.py --capture --blender "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" --zip C:\gatef\astroray-4.0.0-cuda.zip --evidence-dir C:\gatef\evidence
& "C:\Program Files\Blender Foundation\Blender 5.2\5.2\python\bin\python.exe" validate_clean_install.py --validate --evidence-dir C:\gatef\evidence
```
- The script uses only the standard library, so Blender's bundled Python runs it and no Python install is needed.
- It creates a fresh isolated Blender profile and installs the ZIP through Blender's extension installer.
- It then enables the addon, runs a 64×64 F12 render, and writes hashed probes.
- `--validate` prints GREEN or RED with the reasons.

## Bring back
Copy the whole `C:\gatef\evidence\` folder back to this PC. The lead re-validates it and records the row (f) result in the manifest. Committing the evidence still depends on the evidence-storage decision.

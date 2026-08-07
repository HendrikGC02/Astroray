# Developing Astroray

## Developing the Blender addon

The whole build -> package -> install -> test loop is one command
(`scripts/dev_addon.ps1`, PowerShell). It builds the engine `.pyd` (with
OpenMP off, as Blender requires), packages the addon, runs the safety guards,
installs into Blender 5.1, and then either smoke-tests it headlessly or opens
Blender for you.

```powershell
# Owner: build the addon and open Blender with it enabled
pwsh scripts\dev_addon.ps1 -Launch

# Agent / CI-style: build, install, and headless smoke-render gate
pwsh scripts\dev_addon.ps1 -Smoke

# Fast Python-only iteration (reuse the already-built .pyd)
pwsh scripts\dev_addon.ps1 -Smoke -SkipBuild
```

Useful options: `-Backend cpu|cuda|tcnn` (default `cuda`),
`-Blender <path-to-blender.exe>`, `-Python <path-to-python.exe>`.

### What the loop guards against

Each guard encodes a failure mode this repo has actually shipped
(`scripts/dev_loop_guards.py`):

- **Stale `.pyd`** - refuses to package a compiled module older than `HEAD`
  (you would otherwise test old code).
- **OpenMP left on** - refuses an addon build not configured with
  `-DASTRORAY_DISABLE_OPENMP=ON` (MinGW libgomp deadlocks inside Blender).
- **Allow-list drift** - every `blender_addon/*.py` must be in `ADDON_FILES`
  (in `scripts/build/build_blender_addon.py`) or explicitly excluded, so a new
  module cannot silently fail to ship.
- **Broken `register()`** - registers the *staged* addon in headless Blender
  *before* copying it into Blender's extensions dir, so a broken package is
  never installed.

### Smoke gate

`-Smoke` renders a fixed cheap scene (lit cube + Principled material + camera)
at low spp and asserts the image is non-black, finite, and within a plausible
mean-luminance band. It is a **liveness** gate, not a parity gate. Because
Blender's `--python` exits 0 even on an uncaught traceback, the loop gates on a
printed `PKG175_SMOKE_RESULT PASS` sentinel, never the exit code.

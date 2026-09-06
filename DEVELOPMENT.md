# Developing Astroray

## Developing the Blender addon

The whole build -> package -> install -> test loop is one command
(`scripts/dev_addon.ps1`, PowerShell). It builds the engine `.pyd` (with
OpenMP off, as Blender requires), packages the addon, and runs the safety guards.
The default smoke mode installs and tests under a disposable Blender 5.2
profile. Explicit launch mode installs into the user profile and opens Blender.

```powershell
# Owner: build the addon and open Blender with it enabled
pwsh scripts\dev_addon.ps1 -Launch

# Agent / CI-style: build, install, and headless smoke-render gate
pwsh scripts\dev_addon.ps1 -Smoke

# Fast Python-only iteration (reuse the already-built .pyd)
pwsh scripts\dev_addon.ps1 -Smoke -SkipBuild
```

Useful options: `-Backend cpu|cuda|tcnn|auto` (default `cuda`),
`-Blender <path-to-blender.exe>`, `-Python <path-to-python.exe>`,
`-SmokeProfileParent <existing-parent-dir>` (fresh disposable child profile
for `-Smoke`).

### What the loop guards against

Each guard encodes a failure mode this repo has actually shipped
(`scripts/dev_loop_guards.py`):

- **Stale `.pyd`** - rejects a compiled module older than `HEAD` after a full build
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

`-Smoke` (the default mode) renders a fixed cheap scene (lit cube + Principled
material + camera) at low spp and asserts the image is non-black, finite, and
within a plausible mean-luminance band. It is a **liveness** gate, not a
parity gate. Before any probes or install it creates an **owned disposable
Blender 5.2 profile** — a fresh child of `-SmokeProfileParent` (default: the
system temp dir). All five `BLENDER_USER_*` paths point beneath that child.
The loop restores those variables and every prior `ASTRORAY_SMOKE_*` value in
`finally`, then removes its owned profile. Cleanup failure is reported with the
retained recovery path.

`-Launch` instead installs into the real user profile and opens interactive
Blender with the addon enabled. `-SkipBuild` skips the C++ rebuild but still
re-stages and installs addon Python for the selected mode. `-Smoke -SkipBuild`
uses the isolated profile; `-Launch -SkipBuild` uses the user profile. Neither
guarantees freshness because the stale-`.pyd` guard is skipped.

Because Blender's `--python` exits 0 even on an uncaught traceback, the loop
gates on the printed `PKG175_SMOKE_RESULT PASS` sentinel **plus** a zero
native exit code and the absence of an explicit `FAIL` line; native stderr
warnings remain diagnostics, not gate failures.

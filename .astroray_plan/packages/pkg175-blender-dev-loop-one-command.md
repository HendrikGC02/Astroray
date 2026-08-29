# pkg175 — one-command Blender dev loop: build → package → install → launch → headless smoke-render

**Pillar:** 5
**Track:** A (tooling + real-host verification; smoke render needs the local RTX + Blender 5.1)
**Status:** done (PR #547, 2026-08-07 — one-command dev loop (build → package →
install → launch → headless smoke-render); 150s full rebuild / 5.8s
`-SkipBuild`; guard unit tests green (14/14), lint clean, on-hardware smoke
`RESULT PASS`)
**Estimated effort:** S–M (scripting + hardening of existing pieces, not new machinery)
**Depends on:** nothing hard. Builds on: `build_blender_addon.py` + `ADDON_FILES` (packaging allow-list — memory `addon-packaging-file-list`), `scripts/verify_pkg88b_blender.py` / `verify_pkg114_*_blender.py` / `verify_pkg115_textures_blender.py` (the existing headless real-host patterns), the `-DASTRORAY_DISABLE_OPENMP=ON` addon-build constraint (memory `mingw_openmp_blender_deadlock`), the stale-`.pyd` discipline (memory `stale_pyd_locations`).

## Goal (owner's words, 2026-08-03)

*"Building the addon, installing, launching, and testing it for me is far
too much work."* The whole loop must become one command — for the owner
(interactive Blender comes up with the addon current) and for agents
(headless smoke gate in CI-style runs). Rigorous integration work (pkg176,
pkg119-B/C) is not viable while every iteration costs manual steps.

**After:** one entry point, e.g. `scripts\dev_addon.ps1` (PowerShell —
CLAUDE.md shell conventions), with modes:

- `-Smoke` (default for agents): build engine `.pyd` (addon config:
  OpenMP OFF) → stage/package addon → install into Blender 5.1's addon
  path → launch `blender --background --factory-startup` → run a standard
  smoke scene through `CUSTOM_RAYTRACER` → assert on a printed
  `RESULT PASS` sentinel (NOT exit code — Blender `--python` swallows
  tracebacks and exits 0; the pkg88b harness already learned this) →
  report image stats + `.pyd` mtime vs HEAD.
- `-Launch` (default for the owner): same build+install, then open
  interactive Blender with a test `.blend`.
- `-SkipBuild`: iterate on addon Python only (no C++ rebuild).

## Specification

1. **One script, existing pieces.** Compose, don't reinvent:
   `build_cuda*.bat` for the engine, `build_blender_addon.py` for staging,
   the `verify_pkg*_blender.py` pattern for the headless leg. New logic is
   glue + guards only.
2. **Guards that encode the known footguns** (each is a memory-backed
   failure mode; the script makes them impossible, not documented):
   - refuse to package if the built `.pyd` is older than HEAD (stale-pyd);
   - refuse an addon build without `ASTRORAY_DISABLE_OPENMP=ON`;
   - verify every `blender_addon/*.py` on disk is in `ADDON_FILES` or
     explicitly excluded (the allow-list drift trap);
   - verify staged-dir `register()` in headless Blender before install.
3. **Smoke scene is fixed and cheap:** one standard scene (lit cube +
   Principled material + camera), low spp, asserts non-black + finite +
   plausible mean-luminance band. It is a LIVENESS gate, not a parity
   gate — parity belongs to pkg119-B.
4. **Suite wiring:** a `tests/test_dev_loop_smoke.py` target that invokes
   the script's smoke mode and skips cleanly when Blender is absent (CI
   has no Blender/GPU; this is a local-host gate).
5. **Docs:** a short "developing the addon" section in `DEVELOPMENT.md`
   whose entire content is essentially the one command.

## Acceptance

- [ ] From a clean checkout with a configured `build_cuda`, ONE command
      goes source → installed addon → headless smoke `RESULT PASS`,
      unattended, on the local Blender 5.1 + RTX 5070 Ti.
- [ ] `-Launch` opens interactive Blender with the freshly built addon
      enabled and `CUSTOM_RAYTRACER` selectable (owner-facing check —
      demonstrate once in the PR with a screenshot or log).
- [ ] Each guard in (2) demonstrably fires: a negative test (or logged
      manual demonstration) per guard — a guard that has never fired is
      untested.
- [ ] Loop timing recorded in the PR (full rebuild vs `-SkipBuild`), so the
      milestone has a baseline for "iteration cost".

## Scope fence

- No addon feature/UI changes (pkg176 owns those). No parity metrics
  (pkg119-B owns those). No installer/distribution polish for third
  parties — this is the DEV loop; extensions-platform packaging for users
  is a later, separate concern.

## Provenance

Filed by the architect 2026-08-03 under the owner's integration directive.
The dev-loop pain is the owner's own stated blocker to using the engine in
Blender at all; this package is deliberately first in the milestone.

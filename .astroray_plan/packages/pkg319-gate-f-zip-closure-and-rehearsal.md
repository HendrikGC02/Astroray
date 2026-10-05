# pkg319 — Gate (f) without a clean host: release-ZIP DLL closure audit and a fresh-profile rehearsal

**Pillar:** 5
**Track:** A
**Status:** done — lane f4 batch-f 2026-10-06: closure OK on dist/astroray; CPU + no-GPU rehearsal F12 exit 0; validator returns `rehearsal`; PR pending
**Estimated effort:** 1 session (~3 h), CPU only
**Depends on:** pkg278

---

## Goal

Before: gate (f) is unmeasured because no clean Windows host exists. Nothing checks that the release ZIP carries
every non-system DLL the `.pyd` and its bundled DLLs need; on this machine missing DLLs are masked by the CUDA
toolkit, MinGW and Visual Studio on PATH. The first clean-host run would be the first test.
After: the addon build fails if the staged addon's transitive DLL import closure is not satisfied by (bundled DLLs ∪
Windows system DLLs ∪ Blender's own DLLs). A rehearsal mode runs the gate (f) capture on this host with a fresh
profile, a scrubbed PATH and Blender's extension installer, and labels its output `rehearsal`, which the validator
can never accept as gate evidence.

---

## Context

Gate (f) (pkg278): fresh profile, ZIP through Blender's extension installer, no toolchain, F12. The eligible-host
capture stays an owner-side blocker, but the likely failure classes (missing DLL, source-tree import, installer
path, no-GPU fallback) can be caught now. `build_blender_addon.py` already bundles named families (`vcomp140`,
MinGW runtime, CUDA libs, OIDN) from `objdump` output; nothing checks the closure.

---

## Reference

- `pkg278-exit-gate-instrumentation.md` §Gate (f); `docs/install-clean-machine.md`.
- `scripts/validate_clean_install.py` (capture/validate, five mandatory checks).
- `scripts/build/build_blender_addon.py` `_objdump_deps`, `_bundle_msvc_openmp_dll`, `_bundle_mingw_runtime_dlls`.
- Microsoft, "Dynamic-link library search order" (Win32 docs): the loader's search rules the audit models
  (application dir, `AddDllDirectory`, System32, KnownDLLs; PATH excluded under `LOAD_LIBRARY_SEARCH_DEFAULT_DIRS`).
- Microsoft API-set schema (`api-ms-win-*`, `ext-ms-*` resolve to system DLLs).

---

## Prerequisites

- [ ] A staged CUDA addon (`dist/astroray`) and its ZIP built from main.
- [ ] Blender 5.2 installed locally (rehearsal leg).

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `tests/test_pkg319_dll_closure.py` | Closure resolver on fixtures (missing DLL caught, API-set and KnownDLL resolved); rehearsal evidence rejected by `--validate` |

### Files to modify

| File | What changes |
|---|---|
| `scripts/build/build_blender_addon.py` | `--check-closure` (default on for packaged builds): transitive import closure of the staged `.pyd` and bundled DLLs via `objdump -p`; unresolved names fail the build with the list |
| `scripts/validate_clean_install.py` | `--rehearse`: same capture on an ineligible host with fresh `BLENDER_USER_*` roots and PATH reduced to System32 + Blender; every artifact stamped `rehearsal: true`; `--validate` rejects rehearsal evidence; optional `CUDA_VISIBLE_DEVICES=-1` leg for the no-GPU fallback |
| `docs/install-clean-machine.md` | Document the rehearsal and the closure check |
| `scripts/README.md` | Note the two new modes on the existing entries |

### Key design decisions

- No new script: both features extend the canonical tools (CLAUDE.md §5b).
- System set = System32 contents of this host ∪ the API-set prefixes; Blender set = DLLs next to `blender.exe` of the
  minimum supported Blender. Anything else must be in the ZIP.
- Rehearsal evidence goes to a scratch directory, never `docs/blender_parity/evidence/install-clean-machine/`.
- The F12 rehearsal uses the CPU device by default (no GPU lock); the GPU leg is optional and runs under the lead's lock.

---

## Acceptance criteria

- [x] Closure check passes on the current `dist/astroray` (or lists real missing DLLs, which are then bundled).
- [x] Fixture test: deleting one bundled DLL from a fixture stage makes the check fail naming it.
- [x] Rehearsal: fresh-profile install via `blender --command extension install-file` and F12 exit 0 on CPU;
      the no-GPU leg either renders on CPU or fails with a clear message (recorded).
- [x] `validate_clean_install.py --validate` on rehearsal evidence returns not-green with reason `rehearsal`.
- [x] Committed gate (f) evidence untouched; row (f) stays unmeasured.

---

## Non-goals

- Do not mark gate (f) measured or green from this host.
- Do not enable Windows Sandbox / Hyper-V or install anything (owner-side setup).
- Do not change the five mandatory checks.

---

## Progress

- [x] Closure check + fixture test.
- [x] Rehearsal mode + validator rejection test.
- [x] Rehearsal run log and findings in the PR body.

---

## Lessons

*(Fill in after the package is done.)*

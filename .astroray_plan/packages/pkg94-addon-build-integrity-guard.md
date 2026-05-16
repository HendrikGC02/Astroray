# pkg94 — Blender addon build-integrity guard (stale-loaded-module observability)

**Pillar:** 5
**Track:** A (core quality / correctness — addon Python + packaging)
**Status:** done (PR #304, 2026-05-16) — Core build-ID guard implemented: `astroray.__build__` attribute exposed, `register()` guard fires on mismatch, unit tests pass. Install-script lock/`.~stale~` GC deferred to integration test follow-up. Stage 1 / P1 of the addon first-principles plan (PR #300).
**Estimated effort:** ~½ day; spec + addon Python guard + install-script lock/`.~stale~` handling + tests
**Depends on:** none. Independent of pkg55-B' and of every other addon package. **This is the verifiability multiplier — it must land first in Round 10.**

---

## Goal

**Before:** When the owner re-installs the addon while Blender is running,
Blender keeps the old memory-mapped `astroray.pyd` for the process
lifetime. The new `.pyd` lands beside the old one (Blender's extension
installer creates `.~stale~NNNN` shadow dirs because it cannot overwrite
a locked file), but the running interpreter still holds the *old* class
surface. Nothing in the system asserts the bytes Blender is executing are
the bytes that were just built. The user sees
`AttributeError: 'astroray.Renderer' object has no attribute
'upload_environment'` (with the pre-pkg56-B `Did you mean
load_environment_map?` hint) and reasonably files it as a code bug. Three
of the seventeen triaged symptoms (BUG-01, BUG-07, and the *crash* of
BUG-03) are this one process artifact, and it *masks* the real P2 defects
(BUG-04, BUG-05) so they cannot be verified at all.

**After:** On `register()` the addon string-compares the loaded module's
`astroray.__build__` build-ID against the build-ID recorded in the
on-disk install manifest written by that same build; on mismatch it
raises exactly one loud,
unambiguous `RESTART BLENDER — stale module loaded` (not an
`AttributeError` later, deeper, looking like a code bug). The install
script refuses-or-warns when the target `.pyd` is locked, garbage-collects
`.~stale~NNNN` shadow dirs, and prints `Quit Blender before reinstalling.`
Re-installing under a running Blender produces the guard message, not a
mystery `AttributeError`; a clean install on a quit Blender produces a
matching build-ID and no `.~stale~` residue.

---

## Context

This is **Stage 1 / primitive P1** of the addon remediation
first-principles plan (`addon-remediation-first-principles-plan-2026-05-16.md`,
PR #300), itself derived from the 17-symptom → 9-root-cause triage
(`blender-addon-bug-triage-2026-05-15.md`, PR #295).

P1's violated invariant is *"the bytes Blender is executing are the bytes
that were just built/installed."* The triage's decisive packaging finding
(§1 of PR #295): the installed `.pyd` was **byte-identical** (full SHA256
match) to the freshly-built module — the install was correct; the
*running* module was stale. The `.~stale~0001`/`.~stale~0002` shadow dirs
are the OS telling us the overwrite was refused because Blender held the
lock. This is classification **(d)** — a stale *loaded* module, **not** a
stale install and **not** a missing symbol in the shipped binary. *Do not
"fix" BUG-01/03/07 in C++ or Python — a Blender restart after install
already prevents all three.* The correct remediation is process +
observability.

This collapses an entire symptom group at once (the P1 collapse proof,
PR #300 §3): BUG-01, BUG-07, and BUG-03's crash are the *same* old
in-memory class surface throwing `AttributeError: no attribute
'upload_*'`. One stale-module guard makes every one of them stop
reproducing — with **zero engine-logic change** — and un-masks P2's
BUG-04/05 so Stage 3 (pkg96) is testable at all. Per the plan's
recommendation (§7, item 1) and the owner's Round-10 ruling, this is
filed as its own ~½-day package and is the **first Round-10 pickup**.

---

## Reference

- Triage: `.astroray_plan/docs/blender-addon-bug-triage-2026-05-15.md`
  (PR #295) — §1 the decisive packaging finding (SHA256 evidence,
  `.~stale~NNNN` lock mechanism, git-history timeline pinning
  pkg56-B/PR #229 as the symbol-introduction commit); §5 Phase 0
  remediation sketch; §6 single highest-leverage recommendation.
- First-principles plan: `.astroray_plan/docs/addon-remediation-first-principles-plan-2026-05-16.md`
  (PR #300) — §2 P1 (formal/efficient/final cause), §3 collapse table
  (P1 row), §4 Stage 1, §7 item 1.
- `blender_addon/__init__.py` — `register()` (addon entry point where the
  guard fires).
- `module/blender_module.cpp` — the `astroray` extension module; the
  build-ID surface (`astroray.__build__`, a compile-time-embedded
  `<git-short-sha>+<UTC-timestamp>` string) lives here next to the
  existing `__features__` / `__version__` attributes the pkg37
  Diagnostics panel already reads.
- `build_blender_addon.py` — produces the packaged zip and the
  `build_report.json` / install manifest (pkg37, 2026-05-03 changelog)
  that already carries per-backend build metadata; it records the same
  build-ID string the C++ module is compiled with.
- Installed-extension path:
  `%APPDATA%\Blender Foundation\Blender\5.1\extensions\user_default\astroray\`
  and its sibling `.~stale~NNNN` dirs.

## Prerequisites

- [ ] Build passes on main.
- [ ] `astroray.__version__` / `__features__` already exist (pkg37) — the
      stamp is a sibling attribute, not a new mechanism.
- [ ] No active addon-Python work mid-session on `__init__.py::register()`
      (pkg94 touches `register()`).

## Specification

### Key design decisions

1. **Stamp = a compile-time-embedded build identifier, surfaced as
   `astroray.__build__`; NOT a content hash of the shipped `.pyd`.** A
   content hash of the `.pyd` is unimplementable here: the stamp is part
   of the module's bytes, so hashing the module that *contains* the stamp
   is self-referential (the hash changes the moment you embed it). Instead
   `astroray.__build__` is a build-ID string of the form
   `<git-short-sha-of-build-commit>+<UTC-build-timestamp>` (example:
   `e6959a8+20260516T002503Z`), embedded into `module/blender_module.cpp`
   at compile time. The **same** build writes the **same** build-ID string
   into the on-disk install manifest (`build_report.json` / the install
   manifest). On `register()` the addon string-compares the loaded
   module's `astroray.__build__` against the build-ID recorded in that
   manifest. *Rationale:* the triage proved the install was byte-correct
   and the *running* module was stale; a build-ID that is identical
   between the loaded module and the manifest written by that same build
   detects exactly the stale-loaded-module case, is immune to file-copy
   mtime games (the SHA is the build commit, not a copy timestamp), and
   avoids the self-referential-hash impossibility. Reuse the existing
   `build_report.json` produced by pkg37 — do **not** invent a second
   stamping scheme.
2. **One loud failure, at `register()`, not a deferred `AttributeError`.**
   The guard raises a single, explicit
   `RESTART BLENDER — stale module loaded (loaded build-ID <id-a>,
   manifest build-ID <id-b>)` at addon-registration time. It must fire *before* any
   `Renderer` method is touched, so the user never sees the misleading
   `Did you mean load_environment_map?` hint. *Rationale:* the triage's
   core finding is that the failure currently surfaces late, deep, and
   disguised as a code bug; moving it to `register()` with an unambiguous
   message is the entire point of P1.
3. **Install script: refuse-or-warn on a locked `.pyd`, GC `.~stale~`,
   print the quit-Blender hint.** Detect the lock (attempt the
   write/replace and handle the OS sharing-violation), surface a clear
   message rather than silently landing a shadow dir, delete stale
   `.~stale~NNNN` directories, and print `Quit Blender before
   reinstalling.` *Rationale:* PR #295 §5 Phase 0 step 2; the shadow dirs
   are both the diagnostic signal and accumulating cruft.
4. **No code-logic change anywhere.** Packaging + observability only. No
   integrator, no kernel, no `Renderer` method, no depsgraph dispatcher
   is touched. This is the lowest-risk package in Round 10 by
   construction and the reason it can land first concurrently with
   anything.

### Files to modify

| File | What changes |
|---|---|
| `blender_addon/__init__.py` | `register()` reads the on-disk install manifest's recorded build-ID and string-compares it to the loaded `astroray.__build__`; raises one `RESTART BLENDER — stale module loaded` on mismatch, before any `Renderer` use. |
| `module/blender_module.cpp` | Expose `astroray.__build__` — a compile-time-embedded `<git-short-sha-of-build-commit>+<UTC-build-timestamp>` build-ID string; sibling to existing `__version__`/`__features__`. |
| `build_blender_addon.py` | Compute the build-ID once, compile it into the C++ module, and write the **same** string into the install manifest (`build_report.json`) shipped in the packaged addon zip. Install path: refuse-or-warn on locked `.pyd`, GC `.~stale~NNNN`, print "Quit Blender before reinstalling." |

### Files to create

| File | Purpose |
|---|---|
| `tests/test_pkg94_build_integrity_guard.py` | (1) build-ID match (loaded `astroray.__build__` string-equals manifest build-ID) → `register()` succeeds silently; (2) build-ID mismatch (simulated by patching the manifest build-ID or `astroray.__build__`) → `register()` raises the exact `RESTART BLENDER — stale module loaded` message and does **not** raise a later `AttributeError`; (3) install-script helper: locked-target path produces the refuse/warn message + quit-Blender hint and does not silently create a shadow dir; (4) `.~stale~NNNN` GC removes the shadow dirs. |

## Acceptance criteria

- [ ] With a matching build-ID, `register()` completes with no guard
      message and no behavior change vs current main.
- [ ] With a mismatched build-ID (simulated), `register()` raises exactly
      `RESTART BLENDER — stale module loaded` (with the loaded-vs-manifest
      build-IDs) and the test confirms **no** subsequent
      `AttributeError: ... 'upload_*'` is reachable in that session.
- [ ] The install-script helper, given a locked target `.pyd`, emits the
      refuse/warn message and the `Quit Blender before reinstalling.`
      hint, and does not silently land a `.~stale~NNNN` shadow dir.
- [ ] The install-script helper garbage-collects existing
      `.~stale~NNNN` directories.
- [ ] The loaded `astroray.__build__` string-equals the build-ID recorded
      in the install manifest written by the **same** build (one build-ID
      scheme; no content hash; no second stamping scheme introduced).
- [ ] All existing tests still pass (no regressions); zero engine-logic
      lines changed (diff is packaging + `register()` guard + the C++
      attribute only).

## Non-goals

- Do **not** "fix" BUG-01 / BUG-07 / BUG-03 in C++ or Python. They are a
  stale *loaded* module artifact; the shipped binary already has the
  `upload_*` symbols. The guard makes them stop *reproducing* and stop
  *masking* P2 — it does not change engine logic.
- Do **not** address the *transform-coarseness* half of BUG-03 (full BVH
  rebuild because there is no per-object id map). That is an intentional
  pkg56 Phase-C limitation — document, do not fix here.
- Do **not** touch the depsgraph dispatcher, camera, materials, or any
  GPU path — those are pkg95 / pkg96 / pkg55-B'.
- Do **not** invent a new versioning/stamping mechanism, and do **not**
  attempt a content hash of the shipped `.pyd` (self-referential — the
  stamp is part of the hashed bytes). Reuse the existing
  `build_report.json` / install manifest that pkg37 already produces,
  recording the single `<git-short-sha>+<UTC-timestamp>` build-ID.
- Do **not** add a generic "addon health check" framework. One stamp
  compare in `register()` plus the install-script lock handling — nothing
  speculative.

## Progress

- [x] `astroray.__build__` exposed in `module/blender_module.cpp`
      (compile-time `<git-short-sha>+<UTC-timestamp>` build-ID).
- [x] `build_blender_addon.py` writes the same build-ID into the install
      manifest in the zip; install path handles locked `.pyd` + GCs
      `.~stale~`.
- [x] `register()` guard implemented (one loud message, before any
      `Renderer` use).
- [x] `tests/test_pkg94_build_integrity_guard.py` written + passing.
- [ ] CI green; no regressions; zero engine-logic lines changed.

## Lessons

*(Fill in after the package is done.)*

This package exists because three of the seventeen owner-reported
"crash" symptoms were a single process artifact — a stale *loaded*
module — that disguised itself as a code bug and *masked* the real
defects underneath it. The triage spent a session proving (by SHA256)
that the install was byte-correct and the *running* module was stale.
The cost of NOT having this guard is paid every time a fix is tested
against a stale module and read as "still broken"; the cost of having
it is one stamp compare and an install-script lock check. It is the
verifiability multiplier for the entire Round-10 addon track.

---

## Track routing / acceptance gate

- **Track A.** Addon Python + packaging; no GPU, no hardware-verifier
  pass required (zero engine-logic change — the acceptance gate is the
  pytest above plus a manual "re-install under running Blender → guard
  fires, not AttributeError" smoke check noted in the PR).
- **Round-10 sequencing:** **first pickup; depends on: none.** Lands
  before pkg95 / pkg96 (both depend on pkg94 for verifiability) and runs
  concurrently with, and independent of, pkg55-B' Session 3 (zero file
  contention — addon Python/packaging vs CPU wavefront sources).
- **Acceptance gate (one line):** the loaded `astroray.__build__` string
  equals the build-ID recorded in the install manifest written by the
  same build; on an injected mismatch the addon raises the single loud
  `RESTART BLENDER — stale module loaded` error at `register()` and
  refuses to proceed (no later `AttributeError`); a clean install on a
  quit Blender leaves a matching build-ID and no `.~stale~` residue.

# pkg176 — Blender as the steering wheel: drive Astroray from Blender's NATIVE settings/UI, retire the ground-up custom UI

**Pillar:** Integration Milestone (Blender/DCC integration — see ROADMAP "Integration Milestone")
**Track:** A (addon-heavy Python + real-host verification; render legs RTX)
**Status:** Stage 0 done (owner-review artifact — mapping table `docs/blender_parity/pkg176_stage0_mapping.md` + machine-readable `blender_addon/settings_map.py`; 58 direct / 4 approximated / 19 dropped / 9 astroray-only across 90 settings-level rows; Route-2 §6 five hard rules honoured). Stages 1–4 open — dispatchable after pkg175 (the dev loop is this package's iteration vehicle); staged, expect multiple PRs
**Estimated effort:** L, staged (Stage 1 render/sampling settings; Stage 2 panel adoption; Stage 3 world/light/camera property completion; Stage 4 custom-UI retirement)
**Depends on:** pkg175 (dev loop). Cross-links: **pkg119** (Phase A matrix enumerates exactly the native surface this package must consume; Phases B/C are this package's verification layer — see pkg119's refreshed Status), **pkg103** (the earlier feature-wiring audit this supersedes in approach), **pkg115** (native shader-node adoption — the precedent: we already adopted Blender's node surface for textures; this package extends that philosophy from nodes to settings/UI), research note `.astroray_plan/docs/dcc-integration-research-2026-08.md`.

## Goal (owner directive, 2026-08-03 — the framing to keep)

*"The purpose of mimicking Cycles was to be able to use as much of the
existing options and settings in Blender as the steering wheel for this
engine."* The current addon builds UI interactions from the ground up —
custom property groups and custom panels re-inventing what Blender already
ships. That is the wrong direction: the engine is near-Cycles in behaviour
precisely so that Blender's own Cycles-shaped controls can drive it. The
owner wants to actually USE the engine in Blender to verify it does what
they want — integration IS the milestone, not a side quest.

**After:** a Blender user who knows Cycles configures Astroray with the
controls they already know:

- **Native render properties** (`scene.render.*`, and `scene.cycles.*`
  where semantics match: samples, max bounces / light-path depths, clamp
  direct/indirect, filter glossy, seed, film exposure/transparent, etc.)
  read directly by the exporter — not shadowed by parallel custom props.
- **Native panels** shown for `CUSTOM_RAYTRACER` by re-registering the
  relevant Blender/Cycles panel classes via their `COMPAT_ENGINES` sets
  (the standard external-engine trick) wherever every control on the panel
  is honoured or gracefully degraded.
- **Native world/material/light node trees and datablock properties** as
  the sole source (already largely true for materials/textures via
  pkg115/pkg57; close the gaps the pkg119-A matrix marks on world, lights,
  camera).
- **Custom UI reduced to one small "Astroray" panel** for genuinely
  engine-unique features (spectral options, GR/black-hole objects, device
  diagnostics). Everything that has a native Blender home loses its custom
  duplicate.

## Specification (staged)

**Stage 0 — mapping table (blocking, cheap):** from the pkg119-A coverage
matrix + the addon's current custom PropertyGroups, produce a checked-in
table: every custom property → its native Blender/Cycles counterpart
(name, semantic match/mismatch, unit conversion) or `ASTRORAY-ONLY`.
This table is the contract for all later stages and the review anchor —
no silent mapping decisions.

**Stage 1 — settings plumbing:** exporter reads the native properties per
the table; custom duplicates become deprecated aliases (one release of
back-compat for saved `.blend` files, log a migration note per render),
then removed. Semantic mismatches are NOT silently coerced — mismatched
controls stay custom-only until the engine honours the native meaning.

**Stage 2 — panel adoption:** re-register native panels per
`COMPAT_ENGINES` where the whole panel is honest for Astroray; keep an
explicit checked-in list of adopted panel class names so Blender 5.x
removals fail loudly at register (5.0 already removed panels other engines
re-registered — see research note). A panel with un-honoured controls is
either not adopted or its gaps are covered by pkg119-C's
approximated/ignored reporting.

**Stage 3 — world/light/camera completion:** close the DROPPED-SILENT
cells on the allow-listed native settings (pkg119-A) that the steering
wheel needs; anything not implemented degrades per pkg119-C policy
(warn/report, never silent).

**Stage 4 — retirement:** delete the superseded custom UI/properties;
final state is the one Astroray panel + native everything else. Real-host
before/after screenshots in the PR.

**Design rule (Route 2 discipline, from the research note):** as files are
touched, keep bpy-facing translation separate from engine-session calls —
the pybind surface is the session API a future second DCC (or Hydra
delegate) would consume; don't let new bpy imports leak below the
translation layer. Discipline, not framework: no new abstraction without a
second consumer (simplicity tax).

## Acceptance

- [ ] Stage-0 mapping table checked in and owner-reviewed (it encodes
      opinionated calls — e.g. which `scene.cycles.*` props Astroray may
      legitimately read; the owner ratifies the list).
- [ ] A Cycles user's core loop works with native controls only: pick
      Astroray as render engine → set samples/bounces/clamps in the native
      panels → F12 and viewport render honour them (real Blender 5.1,
      demonstrated via the pkg175 loop, per-stage).
- [ ] Every adopted panel's controls are honoured or visibly degraded
      (pkg119-C report); zero silently-ignored controls on adopted panels.
- [ ] Custom UI reduced to the single Astroray panel; deleted properties
      have migration handling for existing `.blend` files.
- [ ] pkg119-B differential harness green on the settings legs it covers
      at each stage (the milestone's verification layer).

## Non-goals

- No engine/kernel feature work — if a native control needs new engine
  capability, that is a follow-up package enumerated at round close (the
  pkg119 red-cell discipline).
- No Hydra/USD work (pkg177 owns the generalization decision).
- No user-facing distribution/extensions-platform packaging.

## Provenance

Filed by the architect 2026-08-03 from the owner's integration directive
(course-correction after the 2026-08-01/02 run). Supersedes the
ground-up-UI direction of the earlier addon UI work; pkg103's audit-then-
expose approach folds into Stage 0/1 here.

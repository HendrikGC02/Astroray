OpenAI Codex v0.153.4
--------
workdir: C:\Users\hgcom\OneDrive\Astroray\Astroray_repo\Astroray-pkg259
model: gpt-6-astra
provider: openai
approval: never
sandbox: read-only
reasoning effort: xhigh
reasoning summaries: none
session id: 01a07bf2-cf5e-7883-bde4-4f0296b7d36c
--------
user
You are being consulted as a creative collaborator (one read-only session,
no code execution expected) on a render-engine test-asset design problem for
Astroray, a from-scratch Cycles-compatible path tracer with a Blender addon.
Reply in plain text/Markdown; this is a design brainstorm, not a coding task.

## North star (owner-approved, verbatim excerpt)

Astroray's near-term mission is a production-capable Blender/DCC renderer
with Cycles-compatible behavior where applicable and a fast interactive GPU
viewport. Correctness and visual fidelity outrank performance, while
viewport performance is a co-equal product goal. The eventual destination is
research-grade astrophysical simulation and science visualization, but that
pillar is currently paused — this task is pure Blender/Cycles parity work.

Pillar-4 exit gate (b) — shader-socket coverage: frequency-weighted coverage
over a frozen corpus of ~50 Blender scenes, target >=95% weighted coverage
and zero silent drops in corpus scenes. Gate (c): exactly three pinned
`.blend` scenes must render CPU+GPU with no addon exception and pass a
parity check (mean-ratio +-5%, SSIM >=0.95, scene-specific non-vacuity
checks so a black/missing feature cannot silently pass).

## The problem

Today Astroray silently drops many Cycles shader-node sockets and render
settings (translates them as no-ops with no warning) rather than refusing or
warning. Nobody has a systematic way to see this, because every existing
benchmark/parity/smoke scene was hand-picked ad hoc (a "metal_sweep" scene,
three placeholder-quality parity scenes, a single-sphere-per-feature debug
library). We are designing (not yet building) a small, deliberately
*attractive* corpus of Blender reference scenes — the kind the project owner
would put in the project's README — organized into seven families, each one
required to exercise a specific slice of Blender's feature surface so that
EVERY Cycles feature Astroray is meant to support lives in at least one
scene, and every feature it silently drops gets a "gap card" (and, where
cheap, a visible tell in the render itself — e.g. a broken Sky texture
should show as flat black sky, not just an absent warning).

## Owner's composition rules (apply to every scene)

- Don't put a glass sphere flush on a plane — it obscures the caustic; lift
  it slightly, or move the light, and zoom the camera onto the interesting
  part of the frame.
- Reflection/caustic scenes: shade smooth (jagged low-poly meshes read as a
  mess), camera looking down toward the object, light placed further away
  rather than sitting directly on top of the subject.
- Renders that felt "flat and boring" (an old material contact sheet) were
  explicitly criticized; scenes should have real depth/story, not a flat
  grid of spheres on a grey background.
- A 2x2 AOV-passes contact sheet was explicitly praised ("I really like this
  one") — the owner likes multi-panel comparison shots showing different
  passes/settings of the same subject, and asked for MORE passes (depth,
  sample-count heatmap) next time.
- A denoiser before/after comparison was praised but criticized for being
  low-resolution and using a boring scene — reuse a more interesting hero
  shot next time.
- A convergence-vs-spp graph was criticized because its "reference" was also
  the last sample point in the series, making the curve implausibly smooth
  right up to the point it flattens; use an independent, higher-spp
  reference next time.
- A big HDRI 3-sphere "sunset" render was explicitly loved and should not be
  changed.

## The seven scene families and current feature-row allocation

(Row counts are (category, node-socket-or-prop) triples from Astroray's
generated Cycles coverage matrix, 527 total: 114 SUPPORTED / 50 APPROXIMATED
/ 363 DROPPED-SILENT. "DROPPED-SILENT" = Astroray reads the .blend, does not
error, and silently ignores that socket/prop.)

1. **materials_hall** (166 rows: 10 SUPPORTED / 38 APPROXIMATED / 118
   DROPPED-SILENT) — every BSDF/closure Cycles ships (Diffuse, Glossy,
   Glass, Refraction, Principled incl. 21 advanced sub-inputs like coat/
   sheen/subsurface radius, Metallic, Sheen, Toon, Translucent, Transparent,
   Hair BSDF x2, Subsurface Scattering, Ray Portal, Emission, Holdout,
   Add/Mix Shader, spectral Blackbody/Wavelength, OSL Script). Current plan:
   a single continuous corridor/gallery with one alcove per closure family,
   shot as one wide establishing shot plus per-alcove crops, consistent
   studio lighting so BSDF differences read clearly.

2. **textures_mapping** (222 rows: 69 SUPPORTED / 0 APPROXIMATED / 153
   DROPPED-SILENT, the largest family) — procedural textures (Noise,
   Voronoi, Wave, Magic, Gabor, Checker, Brick, Gradient, White Noise),
   coordinate/mapping nodes (Mapping, TexCoord, UVMap), the converter/utility
   node graph (Math, Vector Math, Map Range, Clamp, Mix, ColorRamp, Curves,
   Combine/Separate), and bump/normal-map/true-displacement. Current plan:
   a "sample wall" of illuminated tiles grouped by sub-family under raking
   light, plus one hero object receiving a composite of several textures for
   the README shot.

3. **lighting_studio** (35 rows: 24 SUPPORTED / 0 APPROXIMATED / 11
   DROPPED-SILENT) — Point/Sun/Spot/Area lights and their props (temperature,
   soft-shadow size, spread, spot cone/blend, area shape), IES photometric
   profiles, light-group output. Current plan: a photography-studio still
   life shot four ways (one per light type), 2x2 contact sheet, one light
   fitted with an IES gobo profile so a dropped IES shows as a plain cone
   instead of the intended pattern.

4. **world_sky** (25 rows: 1 SUPPORTED / 0 APPROXIMATED / 24 DROPPED-SILENT)
   — Sky texture (Nishita/Hosek-Wilkie procedural sky, sun disc, turbidity),
   HDRI environment texture, world Background node, rotation/strength.
   Current plan: an open exterior "observation deck" with a reflective/
   refractive hero object, shown once under a working HDRI and once under
   the (currently unsupported) Sky texture so the drop is a literal black
   sky next to its working HDRI twin.

5. **geometry_zoo** (35 matrix rows here are only the volume-shader nodes —
   0 SUPPORTED / 12 APPROXIMATED / 23 DROPPED-SILENT; instancing, hair-as-
   geometry, modifiers, motion blur and smooth/flat/auto-smooth shading are
   NOT currently tracked by the coverage matrix at all, a scanner gap we're
   flagging separately). Current plan: a "cabinet of curiosities" turntable
   — instanced rock scatter, a hair/fur patch, small backlit volume boxes
   (scatter/absorption/coefficients), a smooth-vs-flat-vs-auto-smooth sphere
   trio, a modifier-applied-vs-not pair.

6. **camera_lens** (12 rows: 6 SUPPORTED / 0 APPROXIMATED / 6 DROPPED-SILENT)
   — focal length, sensor, shift, DoF aperture (fstop/blades/rotation/ratio),
   camera type (perspective/ortho/panoramic), clip start/end. Current plan:
   one room shot from four camera rigs (shallow-DoF portrait with bokeh
   shape, orthographic elevation, panoramic establishing shot, a near/far
   clip demonstration), 2x2 grid.

7. **render_settings** (32 rows: 4 SUPPORTED / 0 APPROXIMATED / 28
   DROPPED-SILENT) — samples, adaptive sampling, seed, film exposure/
   transparency, filter width, per-bounce-type depth limits, caustics
   toggles, denoiser, AOV/Cryptomatte/Freestyle output nodes. Current plan:
   not a geometric scene but a settings matrix over one fixed hero shot —
   convergence strip (independent high-spp reference this time), adaptive
   on/off, denoise before/after, film-transparent alpha checker, per-bounce-
   type isolation, a sample-count-heatmap AOV panel, a blank AOV pass next
   to a working depth pass to make the AOV-node drop visible.

## What we want from you

1. **Creative scene concepts per family** that are simultaneously beautiful
   (README-worthy, a story or a place, not a grid of spheres) and rigorous
   (every listed feature genuinely gets exercised, not just implied). Feel
   free to propose a materially different concept for a family if ours is
   weak — we will weigh it, not rubber-stamp it.
2. **Features we may have overlooked** — re-read the family feature lists
   above; is anything mis-scoped, missing an obvious sub-case, or would be
   much better demonstrated in a different family than we put it in?
3. **Ways to make silent drops visible in the rendered image itself** beyond
   the two examples above (black sky, plain cone instead of IES gobo) — the
   goal is a viewer glancing at the render can spot a regression without
   reading a manifest.
4. **A critique of our family-to-feature allocation** — anything that should
   move families, be merged, or split into a phase-2 addition.

Keep it concrete and scene-specific; we have limited render budget so please
bias toward ideas that reuse geometry/lighting across a family's tiles
rather than proposing N unrelated one-off scenes. This is Phase 0 design
only — no scenes will be built from this conversation directly.

hook: SessionStart
hook: SessionStart Completed
codex
I’ll develop the seven families as reusable hero sets with focused feature shots. I’ll use the Astroray index skill to check the planning context and verify Blender-specific details in the official docs.

hook: PreToolUse
hook: PreToolUse Completed
exec
"C:\\Users\\hgcom\\AppData\\Local\\Microsoft\\WindowsApps\\pwsh.exe" -Command "Get-Content -LiteralPath '.agents/skills/astroray-index/SKILL.md', 'KNOWLEDGE.md', '.astroray_plan/docs/STATUS.md', '.astroray_plan/docs/NEXT_STAGE_REPORT.md', '.astroray_plan/docs/ROADMAP.md'" in C:\Users\hgcom\OneDrive\Astroray\Astroray_repo\Astroray-pkg259
 succeeded in 438ms:
---
name: astroray-index
description: Query Astroray's built-in SQLite project index to find package ownership, dependencies, documentation, and existing scripts before broad repository searching or adding tooling.
---

# Astroray project index

Read `KNOWLEDGE.md`, then use the index for repository-routing questions:

```powershell
python scripts/project_index.py query "<topic>"
python scripts/project_index.py owns <path>
python scripts/project_index.py deps pkgNNN
python scripts/project_index.py script "<task>"
python scripts/project_index.py whatis pkgNNN
```

Treat its results as routing evidence. Inspect the returned source, package, or
documentation before changing anything. Compare package status with the live
planning sources and git state before dispatching work.
# Astroray Knowledge Map

Routing index for agents â€” if you need X, go here. The machine-readable
version of this map is `python scripts/project_index.py` (a SQLite index over
packages, docs, tests, and optionally GitHub issues/PRs).

## Planning source of truth

Read these together before choosing work, in this order:

1. `.astroray_plan/docs/STATUS.md` â€” latest factual state.
2. `.astroray_plan/docs/NEXT_STAGE_REPORT.md` â€” current handoff and deployable set.
3. `.astroray_plan/docs/ROADMAP.md` â€” **Current sequencing**, owner priority, and pause directives.

Then check package frontmatter and current git/GitHub state. Old reports and
archived plans are context, not dispatch authority.

## Work packages (one per PR/session)

- `.astroray_plan/packages/*.md` â€” package specs. Frontmatter: Pillar / Track / Status / Estimated effort / Depends on.
- `python scripts/project_index.py deps pkgNNN` â€” a package's dependencies + reverse-dependents.

## Research notes

- `.astroray_plan/docs/*.md` â€” physics / sampling / parity research, named `<topic>-research.md`.

## Search & graph

- `python scripts/project_index.py query "pixel filter"` â€” search packages + docs (word-wise).
- `python scripts/project_index.py owns <path>` â€” which package(s) own a file path, plus their status.
- `python scripts/project_index.py script "<task>"` â€” the canonical script for a task (the CLAUDE.md Â§5b no-duplicate gate; mirrors `scripts/README.md`).
- `python scripts/project_index.py whatis pkgNNN` â€” compact card for one package.
- `python scripts/project_index.py graph --html graph.html` â€” interactive node tree (packages â†” docs â†” files â†” dependencies).

## GitHub

- `gh issue list` / `gh pr list` â€” live state (already authenticated).
- `python scripts/project_index.py gh-sync` â€” pull issues/PRs into the index (network).

## Code & tests

- `include/` â€” header-only core; `src/` â€” implementation; `plugins/` â€” plugin registry; `tests/` â€” pytest coverage.
- Build & test commands: see `AGENTS.md`.

## Rules & drivers

- `AGENTS.md` â€” shared repo contract (read automatically).
- `CLAUDE.md` Â§1â€“Â§6 â€” behavioral rules (Â§6 no-invented-algorithms invokes the `cite-algorithm` skill).
- `.opencode/` â€” opencode agent drivers (opencode is the primary harness; Claude Code is the fallback).
- `.codex/` + `.agents/skills/` â€” Codex project config, lifecycle guards,
  focused subagents, and discoverable workflow/index entry points. Detailed
  shared workflow bodies remain canonical in `.claude/skills/`.
- `$astroray-architect-round` â€” Codex's architect-first autonomous delivery
  workflow; use it to select, dispatch, verify, and close a bounded round.
# Astroray Status

## 2026-09-07 EVENING â€” handoff to the next lead session

Owner decisions (recorded in `north-star-and-integration-gate-2026-09-07.md` Â§7,
evening block): pkg237 residual â†’ **firefly-free parity scene** (0.97 pin kept);
pkg238 **done** (#738); HDRI gap â†’ owner rejects the "Cycles inflated" reading and
suspects Astroray's HDRI importance sampling; next dispatch order delegated to the lead.

**Filed / recorded this evening (docs-only commit to main):**
- **pkg258 HDRI environment NEE + importance sampling** (issue #741, P1). Lead code
  read: *no reachable integrator does environment NEE* (`raytracer.h:3105` says so;
  CPU wavefront, MW tracer and GPU wavefront likewise), the CDF sampler on both
  backends has **zero callers** and a pixel-unit azimuth bug (`phi = (u+0.5-0.5)Â·2Ï€`),
  `envSelectProb()` is dead, `BackgroundLight` is an unconstructed uniform stub.
  pkg63's "env-MIS already wired" progress line corrected. Placed in Round 2.
- **pkg259 Cycles feature-coverage reference scene corpus** â€” owner-requested standard
  scenes (pretty + rigorous) covering every Cycles feature Astroray should support,
  manifest-vs-coverage-matrix test, generated coverage/parity report; Phase 0 design
  brainstorm with Astra. Placed in Round 3 (Phase 0 may start in Round 2).
- **pkg241 Phase 2** â€” owner: the Blender UI still runs at the viewport render's frame
  rate (Cycles decouples them). Off-main-thread viewport session, measurement first
  (UI event latency during a chunk, target p95 â‰¤ 33 ms); comment on #721.
- **pkg237** Progress: the firefly-free scene change specified (test-only).
- HDRI gap diagnosis doc: evening addendum with the owner decision + code read.
- `next-session-prompt-2026-09-07.md` â€” the paste-ready prompt for the next Fable
  lead session (same restrictions: no Fable subagents, Opus 4.8 not 5, Sonnet 5 for
  low-level, opencode grunt via `delegate`, Codex Terra â‰¤4 / Luna free / Astra only
  for the pkg259 brainstorm). Dispatch order: pkg258 â†’ pkg241 1b + Phase 2 metric â†’
  pkg237 scene + pkg255 â†’ pkg259 Phase 0 â†’ fill (pkg242 Ph2, pkg245, pkg254).
- Repo hygiene: six orphaned `.claude/worktrees/*` directories (pruned checkouts
  from the overnight PRs, nothing unique) deleted; weekly-bench validation results
  (`benchmarks/cycles-parity/2026-09-07-*`) committed; KNOWN_ISSUES regenerated;
  index rebuilt; `lint --all` clean.

**Still owner-manual:** paste `tracker/astroray_dashboard.gs` into Apps Script +
`refresh()`; add `spec-lint` to required checks; review ghost GitHub app workflows;
install `dist/astroray-4.0.0-cuda.zip` with Blender closed (live profile has the new
exporter Python, old native module).

**Note for the next session:** `build_cuda/astroray.cp313-win_amd64.pyd` (08:45) is
older than HEAD; only docs + addon Python landed after it, but rebuild before the first
GPU gate.

---


## 2026-09-07 CURRENT â€” Round 1 after the overnight course-correction

Owner decisions 08:30 (recorded in `north-star-and-integration-gate-2026-09-07.md` Â§7):
gate (b) is frequency-weighted; denoise out of the interactive loop; pkg237/238
test-method fixes approved; pkg241 Phase 1 follows Terra's order (present-first â†’
resolution budget â†’ cancellation); pkg255â€“257 filed for Metallic/Sky/Displacement.

**Landed today (after the 07:00 closeout):**
- **#738 pkg237/238** â€” parity gates measure converged parity. pkg238 GREEN
  (field attribution: `lambdas` 13 ULP, geometry 2; `lambdas` now on the p99.9
  relative bound). pkg237 improved 0.769 â†’ 0.9628 with adaptive off + shared
  exposure; still 0.007 under the unchanged 0.97 pin (single-firefly scene
  floor) â€” **owner call pending**: re-pin / more spp / firefly-free scene.
- **#737 + fe1c95c pkg242 Phase 1** â€” one transformed-coordinate contract
  (Mapping rotation/offset/scale/mirror; singular reported) for CPU overloads and
  GPU bake domains, transform-aware bake cache keys. GPU-verified (16 contract
  tests incl. 3 GPU twins, 129 procedural regressions). NOTE: the contract code
  reached main inside docs commit `fe1c95c` (lead `commit -a` while the branch
  was cherry-picked for GPU verification); #737 carries the bit-exact key fix.
- **#736** pkg255 Metallic BSDF, pkg256 Sky texture, pkg257 Displacement specs
  (support-or-warn floors + full ceilings) â€” gate (b) is now reachable on paper.
- **#735** pre-commit hooks read `tool_input.command` and resolve the repo from
  `-C`/`cd`/`cwd` (worktree commits checked against the worktree); 6 hermetic tests.
- **#739 pkg241 Phase 1a** â€” present-first blit + interactive-resolution budget
  (addon Python only). Matched GPU A/B, RTX 5070 Ti, p95 editâ†’present:
  metal_sweep camera 430 â†’ **32 ms**, material 964 â†’ **155 ms**; 100k-tri camera
  169 â†’ **63.5 ms**, material 1495 â†’ **224 ms**. `renders_before_present == 1` on
  all 600 events (no stale frame; material double-render gone). Camera classes
  now meet the p95 â‰¤ 100 ms budget; material edits remain render-bound. The
  earlier "cheap-scene camera regression" was a recorder artifact (camera-view
  scenes ignore the rotation nudge) â€” recorder fixed. MERGED 20:26.
- Addon rebuilt (CUDA, hermetic smoke PASS, `dist/astroray-4.0.0-cuda.zip`);
  the live profile runs the new exporter. Weekly local bench validated
  (parity leg OK; showcase leg fixed to `python -m` in #740, merged); scheduled task `Astroray-WeeklyBench` installed (Sundays 03:00, next 2026-09-13).
- HDRI background gap (0.047 vs 0.121): diagnosis doc claims Cycles' own
  environment importance sampling inflates the reference; lead marked the claim
  **unverified** pending a Cycles black-world geometry probe.

**Open at closeout:** pkg237 residual (owner), pkg253 G1-GPU alpha (deferred
shadow stage), pkg241 Phase 1b (cancellation callback + completion metadata),
pkg242 Phase 2 (real-Blender parity), pkg255â€“257 dispatch.

---


## 2026-09-07 CURRENT â€” overnight course-correction: north star + measurable gate, spec hygiene, debt removal, four lanes

Lead: Claude Fable 5.1 (autonomous, owner-approved plan; usage-limit gap 02:10â€“04:40).
Direction now lives in [`north-star-and-integration-gate-2026-09-07.md`](north-star-and-integration-gate-2026-09-07.md)
(owner-approved north star, **measurable Pillar-4 exit gate**, Round 1â€“4 sequencing;
Terra-reviewed). ROADMAP "Current sequencing" points there; 2026-05â†’08 history archived.
Report: [`reports/2026-09-07-overnight-course-correction.html`](reports/2026-09-07-overnight-course-correction.html).

**Merged (squash):** #719 harness routing sync (tiers.json verifyâ†’glm-5.3, docs grunt
glm-5.3-flash, Codex = CLI reviewer, Blender MCP launcher) Â· #727 **TEMPLATE v2 +
`project_index.py lint`** (E001â€“E018, baseline, pre-commit hook, CI `spec-lint`, Apps
Script parser sync) Â· #718 north star + exit gate Â· #725 fixtures (metal_sweep HDRI path
repaired; two byte-identical placeholder scenes removed; `known_issues_report.py` â†’
`KNOWN_ISSUES.md`) Â· #729 pinned reference-scene corpus for gate (c) Â· **#726 pkg242
UV-less checker fix** (implicit fallback UVs uploaded + `uvAuthored` bit; GPU lum std
0.033â†’0.4228 vs CPU 0.4217; 3/3 GPU tests RTX 5070 Ti) Â· #731 pkg237/238 root-cause
diagnosis Â· #730 spec rewrite pilot (batch E + pkg218b renumber) Â· direct: backlog triage
(10 specs superseded, pkg240/pkg231 deleted, pkg127 flag name), pkg254 filed.

**Also merged before closeout (07:05):** #720 debt removal (5 one-off scripts deleted, 11
entry points registered, orchestrator tick unified, dead scheduled workflows â†’
`weekly_local_bench.ps1`, 4 XPASS xfails removed / 6 strict, 14 stale docs archived) Â·
**#728 pkg253 Principled advanced inputs** (15/21 sockets were already implemented â€” the
audit scanner was blind; real gap = alpha transparent shadows, now a shared
`shadowTransmittance` across every CPU NEE site with a bounded re-trace; **GPU alpha is a
follow-up** â€” the wavefront resolves occlusion in the deferred shadow stage; strict xfail
records it) Â· #732 spec rewrite batches Aâ€“D/F (20 specs; lint baseline 262â†’236) Â·
**#733 pkg241 Phase 0** recorder + measurements + cancellation design (Terra: BLOCK as
written â€” present-first blit + interactive-resolution budget before cancellation code).
**Zero open PRs at closeout.** Index rebuilt (263 packages); graph regenerated.

**Measured (live Blender 5.2, RTX 5070 Ti, editâ†’present p50/p95/p99 ms):** metal_sweep
GPU camera 397/426/454, material 809/882/957; 101 920-tri GPU camera 162/165/170,
material 1351/1379/1405; CPU 11.6 s / 22.4 s. Cancel full-stop floor GPU 1.1 s. Idle
refine 1.3 Hz. The p95 â‰¤ 100 ms target is render-bound, not cancellation-bound â€”
Phase 1 design (bool-returning progress callback, no threads) awaits owner + Terra.

**Bug list started:** issues #721 viewport blocking (P1), #722 native Cycles Device
ignored (P2), #723 missing image dropped silently (P2), #724 clip planes (P3); labels
`addon-bug`/`addon-gap`; `python scripts/dev/known_issues_report.py` regenerates the doc.

**NOT GREEN, diagnosed:** pkg237 = adaptive sampler's colour-blind stop metric leaves a
blue variance floor (two CPU streams SSIM 0.677; 0.962 with adaptive off) + per-image max
normalization; pkg238 = `lambdas` made transcendental by pkg206 (13 ULP). Both fixes are
test-method changes needing owner review. Separate: Astroray CPU HDRI background 0.047 vs
Cycles 0.121 on the new corpus scene (exposure/world-strength suspect).

**Owner actions:** paste `.astroray_plan/tracker/astroray_dashboard.gs` into the Apps
Script project and run `refresh()`; add `spec-lint` to required checks; decide gate (b)
metric + denoise-out-of-loop + pkg237/238 test-method changes; review ghost GitHub app
workflows; install the weekly bench task after one manual run.

---

## 2026-09-06 HISTORICAL â€” rebuilt, installed, ready for pkg241/240 (superseded by 2026-09-07 above)

Owner milestone for the next round: **responsive camera/material edits, reliable
cancellation, and faithful mapped textures**. Start pkg241 with real Blender
measurement, then behavior changes; use pkg240 as a parallel measured CI lane.
Follow the [ready-to-paste agent prompt](archive/next-agent-prompt-pkg241-pkg240.md) and
[full rebuild evidence](rebuild-handoff-2026-09-06.md). Pkg242/245 remain separate
mapped-texture scopes; pkg230b/232/236 are already landed. Pillar 4 stays PAUSED.
The initial clean CUDA all-target build found a stale standalone GPU caller;
pkg250 LANDED in PR #716, merge `37f7343` (03:05:15 UTC). Local gates and
independent SIGN-OFF passed. Both host/CUDA CI runs passed; each host suite had
2176 passed, 283 skipped, 15 xfailed, 4 xpassed. The advisory Cornell reference
smoke remains NOT GREEN (two of three gates passed), tracked under pkg249.
Development ALL_BUILD, both clean addon builds, native/Blender checks and the
installed CUDA addon smoke passed. All 429 non-addon profile files were preserved.
The affine mapping chart passes CPU/GPU/Cycles; the separate UV-less procedural
checker baseline remains NOT GREEN under pkg242. See the report for exact gates.


## 2026-09-06 CURRENT â€” pkg230b and pkg236 landed

- **pkg230b LANDED in PR #708**, merge `8217234b`, 2026-09-06 00:24:49 UTC.
  The owner approved Terra/DeepSeek independent review while Claude is unavailable.
  Terra final source/caller/binding/visual SIGN-OFF passed. PR CI: **2133 passed,
  269 skipped, 15 xfailed, 4 xpassed**; host and CUDA checks passed.
- Local pkg230b evidence remains **101 focused passes**, six real-RNA probe sets,
  **21 CPU/GPU/Cycles render legs** and both isolated package smokes passing.
  Full local suites remain **2370 passed, two reproduced baseline failures**
  (pkg237 HDRI SSIM / pkg238 PostInit ULP); NOT GREEN, neither failure closed.
- **pkg232 already landed #705.** Specs **pkg241â€“248 are filed**, #704/#706/#709;
  filing approval is not implementation approval. Pillar 4 remains PAUSED.
- **pkg236 LANDED #711**, merge `2699b43`; Terra final SIGN-OFF passed.
  Smoke isolation and transactional installation passed 62 focused tests and the
  exact real-Blender local-host test. PowerShell 7 and 5.1 CPU smokes passed;
  all 471 live-profile files remained unchanged. Both CI runs: **2173 passed,
  277 skipped, 15 xfailed, 4 xpassed**; host/CUDA checks passed.
  [Evidence](pkg236-implementation-evidence.md) retains transaction limits and
  the pre-existing non-blocking reference-smoke failure (two gates passed, one
  failed). The advisory is NOT GREEN; pkg249 records the diagnostic follow-up.
- **pkg240 baseline audit landed #712**: host tests occupy 90.1-91.7% of the
  measured host job time. Package remains OPEN; no workflow change or speedup
  claim. Detailed architecture precedes a controlled split-runner trial.
- **Next main feature: pkg241 Phase 0**, completing the existing interactive
  recorder and measuring actual Blender response/cancellation before behavior
  changes. pkg242 then improves procedural mapping; pkg245 covers normal/bump
  provenance. pkg240 CI cost audit is suitable parallel throughput work.
- **Spark CLI access verified** with the installed Codex CLI and current account.
  Bounded Spark workers can run via CLI even though this task's native subagent
  roster lacks Spark. No account/configuration change was required.

See [pkg230b evidence](pkg230b-delivery-evidence.md) and
[round delivery status](round-20260906-delivery-status.md).


---


**2026-09-06 (completed pkg230 Phase 2 record):** pkg230
Phase 2 (30 Vector Math ops, 5 Vector Rotate modes, faithful Mix factor
clamping in the color/scalar op-VM chain) is **LANDED in PR #701**, merged
2026-09-05 17:10 UTC (2026-09-06 Sydney), commit
`b38a7d8471884c43c7aa5a2fd60ddb447c859309`. Independent Claude final SIGN-OFF
covers reviewed source `4035a000f8b45dc549e072ebfd31799f608f1755`.
Both push and PR CI runs passed host build/tests and CUDA syntax checks.
The PR host run recorded 2074 passed, 243 skipped, 15 xfailed, 4 xpassed.
Do not redispatch Phase 2.

- **Evidence-backed gates (concise; full gates/artifacts in
  [pkg230-phase2-delivery-evidence.md](pkg230-phase2-delivery-evidence.md)):**
  - 158 focused pkg219/pkg230 tests passed; 37 harness tests passed; isolated
    Blender dev-loop smoke PASS after live-profile-incident recovery.
  - 15 real-Blender comparison legs = 5 cases across CPU-only Astroray, GPU
    Astroray, and Cycles; max RGB mean-ratio deviation 2.38% vs the 5% gate.
    Astra and independent Claude visual review PASS; charts saved.
  - All 64 non-program shade variants match their recorded baseline resource
    fields. Fleet: REG 254 / STACK 3400 / CONST 1748 / LOCAL 0. The comparison
    measured resources, not complete machine-code byte streams.
  - Original full split run: 2326 passed (1642 CPU + 684 serial), 4 original
    failures. Two environment/sampling failures resolved on rerun (hermetic
    profile smoke; backdrop correct artifact + 256 samples); two baseline
    HDRI/ULP failures remain under pkg237/pkg238. The original full suite is
    NOT green and was NOT wholly rerun.
  - A local bright patch on the backdrop persists on main+feature despite the
    global SSIM pass at 256; pkg239 follow-up #702. No claim of perfect
    baseline/Cycles visual parity.
  - Follow-ups filed separately, all OPEN for architect review before
    implementation, no queue promotion: pkg230b #697, build-latency pkg231
    #698, pkg232â€“235 #699, pkg236â€“238 #700, pkg239 #702.
    This closeout also files pkg240 CI workflow cost audit, separately scoped
    from the renderer change and pkg231 local CUDA rebuild diagnosis.
- **Scope delivered:** 30 Vector Math operations, 5 Vector
  Rotate modes, faithful Mix factor clamping in the color/scalar op-VM chain;
  coordinate chains warn/defer to pkg230b. The verified real-Blender carrier is
  textured Principled with specular zero and Closest filtering â€” not universal
  BSDF/filter coverage.
- **NEXT is OWNER CHOICE** among pkg127 Phase 2, Principled
  advanced-inputs (needs a scoped spec), pkg211 prototype-first-or-park, and
  the pkg136 GPU leg. No autonomous priority promotion; Pillar 4 remains PAUSED.
  Mere filed follow-ups do not preempt owner choice.

---

**2026-09-05 (HISTORICAL / SUPERSEDED â€” see 2026-09-06 above; verified against
`origin/main` at `aecff0d` and merged PRs #676, #681â€“#685, #692â€“#696): pkg225
hair is complete through the Blender addon; pkg127 Phase 1 and pkg136 CPU Stage
1A/1B are landed; pkg229's coverage re-audit is landed; pkg230 Phase 1 (op-VM
utility opcodes) is landed. NEXT = pkg230 Phase 2 (Vector Math/Rotate).**
- **pkg225-S1 â€” CPU ray-curve (hair) intersection â€” LANDED** (PR #670). The
  prior handoff's "bug in curves.h" diagnosis was WRONG: a standalone native
  harness proved the pbrt-ported primitive hits correctly (t / position /
  radial normal). The 4 test failures were TEST-harness bugs (degenerate camera
  up-vector âˆ¥ view dir; broken oblique geometry; a sign-convention normal check)
  + an **unfilled position AOV** (`SpectralPathTracer` never set `r.position` â†’
  `get_position_buffer()` was `Vec3(0)` for every shape â€” fixed). 7/7.
- **pkg225-S2 â€” CPU Principled Hair BSDF (Chiang 2016) â€” LANDED** (PR #673).
  `include/astroray/hair_bsdf.h` (Mp/Np/Ap, header-only STL-free for GPU reuse) +
  `plugins/materials/principled_hair.cpp` (R/TT/TRT+residual, 3 Ïƒ_a
  parametrizations, view-dependent tangent frame from `uvTangent`, h=2Â·hair_vâˆ’1,
  coatâ†’R-roughness). 9/9 gates (energy Ïâ‰¤1 across Î²_m, absorption, colour,
  spectral render smoke). cite-algorithm research note `docs/pkg225-hair-bsdf-
  research.md` (PR #672).
- **pkg225-S3 â€” GPU curve geometry â€” LANDED** (PR #676, merged 2026-09-03). Curves render on
  the GPU wavefront as a `GPRIM_CURVE` BVH leaf (`gpu_curve_intersect.cuh`,
  iterative de Casteljau, ribbon default / thick swept-circle). **Register
  isolation via `template<bool HasCurves>`:** the curve leaf raised the universal
  intersect/shadow kernels for every scene, so it is gated behind `if constexpr`
  â€” non-curve `<â€¦,false>` kernels re-measured byte-identical (intersect 127/616,
  N3 61/272, shadow 108/584, fleet shade 254/3368/1716); only curve scenes launch
  `<â€¦,true>` (158). GPUâ†”CPU curve parity + 25 regression tests pass; cpp-abi-guard
  APPROVE. The `hit_hair_v` SoA lane was added by S4.
- **pkg225-S4/S5/S6 â€” LANDED** (PRs #681â€“#684, merged 2026-09-03/04): GPU
  Principled Hair BSDF, CPU spectral melanin absorption, and Blender Curves /
  Principled Hair addon integration; the S6 multiwavelength NEE regression was
  fixed in #684. The pkg225 package is complete across CPU, GPU, spectral, and
  addon paths.
- **pkg219d â€” scalar parameter textures (op-VM â†’ roughness/metallic/transmission/
  IOR) â€” LANDED** (PR #674). Extends the `c_wfProgBinding` `__constant__` side-
  table + CPU `DisneyPlugin::substituted()`. Register gate byte-identical (fleet
  254/3368/1716); 3/3 CPU+GPU parity; 297 regression; cpp-abi-guard APPROVE;
  **addon clean-rebuilt + headless-Blender node-chain render verified.**
  Known-bounded: metallic/transmission GPU parity approximate (closure lobe-mix
  baked at upload); roughness/IOR exact.
- **pkg210 â€” SUPERSEDED.** Premise stale: all 4 `terminateSecondary()` sites are
  already refraction-gated (dielectric since pkg31, principled since pkg187).
- **pkg180 â€” CLOSED, no engine change.** The systemic ~12â€“20% Cycles-dim does not
  reproduce on the current build â€” common-linear-space A/B: backdrop 1.02 / world
  1.01 / diffuse 0.997 / glossy 1.016 (all in `[0.90,1.10]`). Resolved by the
  intervening dielectric/metal/Principled parity work and/or a since-corrected
  harness view-transform.
- **Method note:** two prior-handoff diagnoses were overturned by first-principle
  checks â€” pkg225-S1 (native harness) and pkg210 (grep sweep) â€” avoiding wasted
  register-hostile rebuilds. Registers: fleet `stageShadeBucketedKernel
  <0,0,0,0,0,0,0>` stays REG:254/STACK:3368/CONSTANT[0]:1716 through all of it.
- **pkg136 Stage 1 variance campaign â€” CONCLUDED (#694), not pending.** â‰¥2Ã— is a
  scene-physics ceiling, not a bug: the de-risked 110Ã— prototype had no NEE, so a
  real NEE integrator caps guiding at the residual-indirect win (~1.3Ã— diffuse
  oracle bound; unlearnable-by-coarse-guide on hard scenes). #694 instead fixed a
  real bug â€” training passes cast full unbiased samples then discarded (3Ã— ray
  waste + high-Î± dark bias) â€” and shipped a genuine **~1.3Ã— equal-cost win** on
  the hard-transport slot scene (moderate/veach â‰¤1Ã—). Warp/MIS confirmed correct
  (`E[1/pdf]=|support|`, not a bug). Full diagnosis:
  `.astroray_plan/docs/pkg136-stage1b-findings.md`.
- **pkg230 Phase 1 â€” LANDED (#696, 2026-09-05).** op-VM Clamp node + Math
  `use_clamp` + Mix `clamp_result` on the shared HD `svm_eval` (CPU+GPU); the
  pkg229 re-audit's #3/#4 items. CI green + RTX HW-verified (GPU parity 3/3;
  `cuobjdump` REG:254 across all 128 shade specializations, no spill). Fixed a
  Cycles-parity bug (`svm_clampf` vs Cycles `min(max())` when min>max). Spec:
  `.astroray_plan/packages/pkg230-opvm-utility-opcodes.md`.
- **Historical pickup on 2026-09-05 (superseded above): pkg230 Phase 2** (spec written,
  not started at that time) â€” Vector Math + Vector Rotate op-VM opcodes +
  faithful Mix `clamp_factor=OFF`; the coordinate-chain-vs-op-VM fork is
  documented in the spec + NEXT_STAGE_REPORT. Then the owner chooses among
  pkg127 Phase 2, Principled advanced-inputs (highest-value single node, L),
  pkg211's prototype-first/park path, and the pkg136 GPU leg. **pkg229 coverage
  re-audit is landed in #695**
  (152 SUPPORTED / 35 APPROX / 340 DROPPED of 527; op-VM scanner blind spot fixed,
  render-verified; ranked backlog in `.astroray_plan/docs/blender-coverage-reaudit-2026-09.md`).

---

**2026-08-30 â†’ 2026-08-31 (OVERNIGHT ROUND â€” 12 PRs merged: pkg131 adaptive
sampling now FULLY DONE across both backends, the pkg208/pkg209/pkg218b spectral/
dispersion cluster closes out, pkg212 fixes a real GPU/CPU wavefront pixel-offset
bug, and pkg219's DONE flip â€” accidentally reverted by an in-flight PR â€” is
restored): the wavefront now compacts converged pixels on the GPU exactly like the
CPU, GPU lamp colour matches the CPU's true SPD (was RGB-approximated), and the
GPU silhouette is pixel-exact vs the CPU megakernel.**
- **pkg131 â€” Zero-knob adaptive sampling â€” NOW FULLY DONE, both backends**
  (PR #659 CPU leg 2026-08-30 + PR #665 GPU leg 2026-08-31). The shared
  `__host__ __device__` Dammertz auto-threshold core (cited to Cycles
  `adaptive_sampling.h`, byte-exact) drives both the CPU per-pixel early-out
  and a GPU wavefront **compacted active-pixel round**: `stageRegenKernel`
  remaps claimed work to `activePixels[w % numActive]` under a gated
  `__constant__ c_wfAdaptive` flag (byte-identical when off), opt-in via
  pkg224's progressive sampler (adaptive needs its prefix property). HW-verified
  RTX 5070 Ti: byte-identical-off, unbiased-on, round loop engages
  (`tests/test_pkg131_adaptive_gpu.py`), wavefront-diff + photon-caustic
  regression green. **Deferred as a follow-up slice (not blocking DONE):**
  sample-count AOV + addon UI knob removal (`samples=N` â†’ `max_samples`).
- **pkg208 â€” chromatic-light-source dispersion oracle DONE** (PR #666 +
  #668) â€” CPU-only oracle test: `sodium_vapor` (narrow-line, ~589 nm)
  chromaticity spread 0.0146 vs `led_6500k` broadband control 0.4917
  (~33x), asserted at a conservative 3x margin; sodium mean chroma
  (0.852, 0.148, 0.000) confirms amber. #668 also restored the spec's
  "Agent-ready recipe" section, which an out-of-scope edit in PR #664 had
  reverted to a stale pre-fork state.
- **pkg209 â€” pkg187 Cauchy parity re-verify + citation refresh DONE**
  (PR #664) â€” refreshed the dispersion WIP wording to the now-merged Cycles
  commit (`f15daf81bf7c...`, PR #162041, merged 2026-08-18) and re-verified
  `cauchyAB`/`gpu_cauchy_ior` character-for-character against the merged
  diff (no divergence); fixed the MNEE citation ("Manakov"â†’"Fascione")
  across `half_vector_constraint.h`/`sms_attempt_device.cuh`/
  `sms_caustic_path_tracer.cpp`. Comment/doc-only, no algorithm change.
- **pkg218b â€” GPU spectral emission device upload DONE** (PR #667) â€”
  closes the "GPU lamp colour is RGB-approximated" gap (memory
  `gpu-emission-is-rgb-approximated`): non-RGB dedicated lights
  (blackbody/measured_spd/composite) now bake their true `EmissionSpectrum`
  onto a device grid (360-830 nm @ 1 nm) and evaluate it directly at render
  wavelengths, instead of one reference-RGB upsample. Global memory, not
  `__constant__` (avoids risking the shared 64 KB constant budget). Traced
  and patched THREE NEE sites the spec's reference list missed (deferred/
  bucketed `stageShadowKernel` resolve, `intersectPathSlot` direct-hit, and
  the volume in-scatter NEE park site) beyond the one the spec named.
  HW-verified: register probe on `stageShadeBucketedKernel` byte-identical
  to the fleet baseline (REG:254/STACK:3368/CONSTANT[0]:1716 â€” the new
  `GNEESample` field is a trivial store, no spill), CPU/GPU emission colour
  parity within 5% across 9 profiles including sodium amber. `GMaterial`
  and ReSTIR (`stage_restir.cu`) untouched by design.
- **pkg212 â€” wavefront ray-gen half-pixel center fix DONE** (PR #663) â€”
  the GPU wavefront silhouette was shifted ~0.4-0.6px right of the CPU
  megakernel (uniform across all pixel filters); wavefront `u`/`v` were
  centered at `px+0.0` instead of `px+0.5`. Fixed at the single true
  source, `generatePrimaryRay` in `src/gpu/wavefront/stage_init.cu` (also
  covers the `initPathSlot` regen path, confirmed NOT a second call site)
  and `init_path` in `src/cpu/wavefront/path_kernel.cpp`; the megakernel
  already used the correct convention, untouched. RTX-verified, silhouette
  edge shift eliminated.
- **pkg207 â€” addon dispersion-socket probe DONE** (PR #658) â€” reads the
  merged Cycles 5.3 socket names (`Transmission Dispersion Scale`/
  `...Abbe Number`), short forms kept as fallback; pure-Python, CI-gate
  only, 4/4 unit tests green.
- **pkg219 â€” per-texel shader-graph evaluator DONE, flip RESTORED** (PR
  #661, tracker-hygiene fix this round) â€” #661 correctly flipped the spec
  to DONE (219a/b/c op-VM core + pkg223/pkg223b normal-perturbation
  landed), but an out-of-scope revert inside PR #664 (`docs(pkg209):
  drop out-of-scope pkg208/pkg219 spec edits`, commit 5064d81) silently
  reverted the pkg219 spec all the way back to its pre-#661 "open" state
  instead of to what was actually on `main` at the time â€” a genuine
  tracker bug, not a real status change. Restored the exact post-#661
  content this round (verified via `git diff <661-sha> -- <file>` == empty
  after restore). The one deliberately out-of-scope acceptance item
  (Math/MapRange driving roughness) is now tracked as its own spec,
  **pkg219d** (below).
- **pkg219d â€” scalar parameter textures FILED, open** (direct-to-main
  commit 5fc01e4, no PR â€” docs-only) â€” the one genuine residual the pkg219
  completion audit surfaced: the op-VM evaluator is complete but its
  program-texture output is wired only to Base Color; roughness/metallic/
  etc. still read constant-folded floats. Register-hostile GPU shade path
  (touches BSDF scalar-parameter eval on both backends); architect to
  detail before dispatch. Real backlog item, kept open.
- **Docs infra:** PR #660 (2026-08-30 status/tracker reconciliation) and
  PR #662 (architect agent-ready specs + overnight routing) â€” both
  docs-only, no code.
- **Fleet register baseline unchanged: `stageShadeBucketedKernel<0,â€¦>`
  REG 254 / STACK 3368 / CONSTANT[0] 1716** â€” pkg131's GPU adaptive round
  and pkg218b's emission-profile lookup are both off the REG:254 frame
  (side-table / trivial-store patterns); re-measure from the actual `.pyd`
  before trusting, per usual.
- **Next pickup (verified against this pass's Status flips):** pkg225-S1
  (hair ray-curve intersection â€” a WIP branch `pkg225-s1-curve-intersect`
  exists, UNVERIFIED/uncompiled, next step is build + analytic-test + math
  review â€” "no half-assing hair"), pkg210 (companion wavelengths on
  specular reflection, register-hostile, Claude-last-line), pkg180
  (systemic Cycles-dim diagnosis, local Blender+RTX), pkg211 (per-bounce
  spectral MIS prototype, research, may park), pkg219d (scalar
  param-textures, architect to detail). Pillar 4 + pkg218-Thread-B stay
  PAUSED. See `NEXT_STAGE_REPORT.md` for the full queue.

**2026-08-30 (pkg207 + pkg131 session 1, PRs #658/#659 â€” plus a spec/tracker
reconciliation pass): the addon dispersion-socket probe now reads the merged
Cycles 5.3 names, and zero-knob adaptive sampling lands its shared core + CPU
leg (GPU leg + addon UI removal remain as follow-ups).**
- **pkg207 DONE** (PR #658) â€” the forward-compat dispersion probe in
  `blender_addon/__init__.py` read the pre-merge WIP socket names
  (`Dispersion Scale`/`Dispersion Abbe Number`); Blender PR #162041 (merged
  2026-08-18) shipped them as `Transmission Dispersion Scale`/`Transmission
  Dispersion Abbe Number`. Fixed to probe the merged names first, short forms
  as a fallback (`put_float`'s existing variadic name-list, no refactor);
  stale "unmerged PR" comment refreshed. Pure-Python, CI-gate only, unit test
  4/4 green.
- **pkg131 session 1 of 3 DONE** (PR #659) â€” ports Cycles' zero-knob adaptive
  sampler (Dammertz 2010 brightness-relative noise metric + auto-derived
  threshold from the sample budget, cited to Cycles `main`) as a shared
  `__host__ __device__` core (`include/astroray/sampling/adaptive_sampling.h`,
  byte-exact vs Cycles' derived values; 8 GB-hardware deviation: scalar-
  luminance half-buffer instead of Cycles' float3 aux), and wires it into the
  **CPU** per-pixel loop (`Renderer::render`), replacing the old uncited
  coefficient-of-variation early-out. Below the min-sample floor the check
  never fires â†’ bit-identical to the non-adaptive render (pinned); above it,
  gated unbiased/bounded. 6 host unit tests + 2 CPU render gates, 63 existing
  regression tests unaffected. **Remaining for pkg131:** the GPU wavefront
  leg (compacted active-pixel round on top of the flat work pool â€” additive,
  byte-identical when off, HW-verify required) and the sample-count AOV +
  addon UI knob removal â€” see the Progress checklist in the spec and
  `.astroray_plan/docs/pkg131-adaptive-sampling-autothreshold-research.md`.
- **Spec/tracker reconciliation** (no code): pkg207 Status flipped openâ†’done
  above. pkg220/pkg221/pkg222 (GPU spectral-caustic quality round, merged
  #644/#645/#646 on 2026-08-25) had their spec `Status:` headers still
  reading "open" â€” flipped to DONE with merge PR/sha; the round itself
  already closed out in STATUS.md on 2026-08-25â†’26, this only fixed the
  stale spec headers that the orchestrator's queue-read depends on (memory
  `orchestrator-next-stage-report-stale`). `NEXT_STAGE_REPORT.md` top handoff
  (stale since 2026-08-29, still pointing at "implement pkg224") rewritten
  for the next pickup.

**2026-08-30 (pkg224 â€” progressive hash-Owen Sobol' sampler for the GPU wavefront,
PR #657 merged 4f919b9): opt-in low-discrepancy sampler at every wavefront RNG draw,
the prerequisite that UNBLOCKS pkg131 (adaptive sampling). Off by default â†’
byte-identical to the PCG32 fleet.**
- **Design (owner-confirmed forks 2026-08-29, followed exactly):** (a) hash-Owen
  Sobol' (Burley 2020 / pbrt-v4 / Cycles `sobol_burley`, all Apache-2.0; direction
  vectors baked from SciPy's Joe-Kuo dataset by `scripts/gen_sobol_matrices.py`,
  verified byte-exact vs `scipy.stats.qmc.Sobol`); (b) opt-in runtime `__constant__`
  flag `c_wfSamplerMode` (NOT a template axis); (c) GPU-only (CPU keeps `std::mt19937`).
- **Register-safe wiring:** one branch in the shared `WavefrontRNG::Uniform()` funnel
  under `#ifdef __CUDA_ARCH__` (covers primary-ray + all shade/NEE draws in a single
  edit; the host/CPU build compiles it away â†’ CPU oracle + `wavefront_diff`
  snapshot-parity untouched). Sobol' body is `__device__ __noinline__` to keep it off
  the REG:254 frame. **Register probe: fleet `stageShadeBucketedKernel` BYTE-IDENTICAL
  across all 128 specializations** â€” zero off-path cost (memory
  `noinline-runtime-flag-avoids-shade-spill`). Exposed as
  `renderer.set_use_progressive_sampler(True)`, published in `cuda_wavefront_render`.
- **Verified:** host suite (scipy byte-exact 64 dims, prefix property, convergence
  slope âˆ’1.45 vs white-noise âˆ’0.5, pixel decorrelation) + GPU suite (OFF==default,
  flag wired, lower flat-region noise) + regressions (pkg92 RNG, pkg186 GPU parity,
  wavefront_diff bit-identity). On a smooth diffuse scene at matched 16 spp:
  **âˆ’39% RMSE, âˆ’28% flat-region noise** vs PCG32.
- **pkg131 UNBLOCKED** (spec Status flipped): turn the sampler on + vary per-pixel
  sample counts against the convergence estimator. Note: making progressive the
  UNCONDITIONAL default (vs on-only-in-adaptive-mode) needs a broad scene-suite sweep
  (structured-artifact / denoiser-interaction check) + a CPU-parity resolution first
  â€” a deliberate follow-up, not automatic.

**2026-08-29 (pkg201-S3 items A+E + pkg223b Bump ROUND â€” 7 PRs merged; shader-node
+ Cycles-parity + honour-matrix advance): three engine features shipped CPU+GPU at
parity with the fleet shade kernel held at REG 254 throughout, plus audits/hygiene
and the pkg224 progressive-sampler spec that unblocks pkg131.**
- **pkg201-S3 item A DONE** (PR #651) â€” Cycles per-type bounce limits
  (diffuse/glossy/transmission) honoured on BOTH backends (they were `(void)`-
  discarded on CPU too; first impl on both, owner option B). CPU `pathTraceSpectral`
  + GPU `shadePathSlot`, OPTION-2 runtime SoA compare. Register probe: REG 254
  unchanged, STACK 3352â†’3360 (+8), CONSTANT[0] 1700â†’1708 (+8, the `per_type_bounce`
  SoA pointer) â€” owner ACCEPTED as perf-neutral (occupancy is register-bound; the
  +8 STACK is untouched in the fleet all-unlimited path). `transparent_max_bounces`
  (needs a BSDF lobe LABEL) and `volume_bounces` (pkg199 cross-ref) PARKED.
- **pkg201-S3 item E DONE** (PR #654) â€” native caustic toggles
  (`caustics_reflective`/`caustics_refractive`) honoured BOTH backends via a sticky
  `hadDiffuseAncestor` flag + a delta-caustic cull (Cycles PATH_RAY_DIFFUSE_ANCESTOR).
  Both toggles default ON â‡’ byte-identical fleet. Register: REG 254, STACK 3360â†’3368,
  CONSTANT[0] 1708â†’1716 (`had_diffuse_ancestor` SoA). Path-traced glass-sphere test:
  refractive-off removes energy + changes pixels, CPU+GPU.
- **pkg201-S3 item C PARKED** â€” filter_glossy: NOT a register spill; materials
  recompute GGX alpha inline at ~4 sites each (no single `sd->closure` mutation point
  like Cycles), so a faithful blur needs a per-material floored-roughness refactor
  Ã—5 materials Ã—2 backends â€” disproportionate to one honour row. Follow-up filed
  (research note + [[pkg201-filter-glossy-alpha-site-sprawl]]).
- **pkg223b Bump node DONE** (PR #655) â€” Blender Bump (heightâ†’normal) honoured
  CPU+GPU at parity via Cycles `svm_node_set_bump` surface-gradient (Mikkelsen 2010)
  on the UV-aligned frame, SHARING the pkg223 `HasNormalPerturb` axis (no new axis).
  Register probe: fleet `<0,â€¦>` byte-identical REG 254 / STACK 3368 / CONSTANT[0]
  1716; shared `<â€¦,true>` absorbed the bump branch with NO spill. Fixed two latent
  bugs: (1) the **UV-upload gate** in `scene_upload.cu` excluded bump-mapped
  materials â†’ bump-only triangles shipped `hasUV=0` â†’ the GPU bump branch silently
  skipped (the entire "GPU bump weak/doesn't scale" symptom); (2) nearest-neighbour
  sampling needs a texel-relative bump `eps`. Addon export was already wired. See
  [[uv-upload-gate-needs-new-normal-perturb-consumers]].
- **Docs/infra:** pkg126â€“137 status audit (PR #648, most still-open + no code;
  pkg128â†’superseded by pkg178, pkg129â†’done), tracker+template hygiene (PR #649,
  18 Pillar-frontmatter fixes + timeline regex in both script mirrors), and
  **pkg224 progressive-sampler spec + research** (PR #656) filed as the pkg131
  unblock. Owner CONFIRMED pkg224 forks: hash-Owen Sobol' / opt-in runtime flag /
  GPU-only first â€” NEXT session implements it.
- **Fleet register baseline now: `stageShadeBucketedKernel<0,â€¦>` REG 254 / STACK
  3368 / CONSTANT[0] 1716** (measure from the actual `.pyd`, don't trust this line).

**2026-08-26 (pkg223 â€” GPU tangent-space NORMAL MAPS, PR #647 merged be7cbec):
normal maps now perturb the shading normal on the GPU wavefront (they were
silently dropped) and the CPU decode is corrected to the UV-aligned frame.**
- **Investigation collapsed the spec's feared scope.** The spec was written blind
  ("cold multi-subsystem build"); in fact the **addon export**
  (`normal_map_texture`/`normal_strength`), the **CPU decode**
  (`NormalMappedPlugin`), and the **UV-aligned tangent infra**
  (`uvTangent`/`gpu_pr_uvAlignedTangent`, pkg178) ALL already existed. The real gap
  was **GPU consumption only** â€” a `NormalMapped` decorator is a CPU `shared_ptr`
  wrapper that doesn't survive `GMaterial` upload, so the device shaded the flat
  normal.
- **Register-safe design (the crux the spec flagged).** Normal-map data
  (`matNormalTexId`/`matNormalStrength`) rides the existing `__constant__`
  `c_wfTexBinding` **side arrays** â€” NOT `GMaterial` â€” so `GMaterial` stays exactly
  640 B and the fleet `<â€¦,false>` shade kernel is byte-identical (the pkg186
  precedent). Perturbation gated behind a 7th `template<bool HasNormalPerturb>`
  axis (64â†’128 shade specializations). **Register probe PASS:** 64 `=false`
  specializations byte-identical to main (REG+STACK), 64 `=true` NO spill (max REG
  254) and NO STACK increase (60 identical, 4 smaller). The register-hostile risk
  the owner asked to invest in **did not materialise** â€” the side-table pattern
  avoided it entirely.
- **Latent CPU bug fixed:** `NormalMappedPlugin` decoded into the ARBITRARY
  `buildOrthonormalBasis` frame, not the UV-aligned `rec.uvTangent` â€” a
  Cycles-incorrect azimuth (relief tilted to a random compass direction). Fixed to
  the UV-aligned Mikk-TSpace frame (`B = signÂ·cross(N,T)`); this is also the GPU
  parity oracle. Also fixed: `scene_upload` only uploaded triangle UVs for
  aniso-Principled / image-textured materials â€” normal-mapped triangles now get
  them too (this was WHY the first GPU render showed zero relief).
- **Verified (RTX 5070 Ti, sm_120):** `test_pkg223_gpu_normal_map.py` (visible
  relief, Strength monotonic, CPU/GPU mean-ratio parity) PASS; no regressions
  (pkg186 texture parity, pkg190 procedural, pkg219a mapping, material plugins);
  CI green (build-and-test + cuda-syntax on GCC â€” no MSVC/GCC divergence despite
  the template-heavy axis). Cite:
  `.astroray_plan/docs/pkg223-normal-map-research.md` (decode/handedness/Strength
  cross-checked vs Cycles `svm_node_normal_map` + Mikk-TSpace).
- **Cost routing:** the cite/research note was delegated to the grunt tier
  (succeeded, no code touched); the register-critical engine change stayed on Opus
  (memory `delegate-tier-stalls-on-hard-packages`).
- **Next-pickup finding:** pkg131 (adaptive sampling) is **BLOCKED on an unmet hard
  prerequisite** â€” the wavefront RNG is PCG32 white-noise, no PMJ/Sobol prefix
  property (memory `pkg131-blocked-on-progressive-sampler`); needs a progressive
  sampler or an architect re-scope first. pkg201 Stage 3 (register-hostile,
  probe-gated) remains the cleanest next register-work pickup. **Bump** is the
  pkg223 follow-up (needs height-texture derivatives; deferred).

**2026-08-25 â†’ 2026-08-26 (GPU SPECTRAL-CAUSTIC QUALITY ROUND â€” 3 PRs merged
#644/#645/#646, architect-led, addressing the owner's two hands-on caustic
observations): the GPU photon caustic now averages down (was frozen), narrow-line
lamps cast emission-line-coloured caustics (was a continuous rainbow), and the
mercury lamp SPD is chromatically correct (was magenta).**
- **Architect planning pass** filed pkg220-223 + refreshed NEXT_STAGE_REPORT; two
  root-cause findings were code-confirmed up front and handed to the architect as
  given (see memory `gpu-caustic-frozen-lattice-and-spd-blind`).
- **pkg220 DONE** (PR #644) â€” per-iteration seed for the GPU photon-caustic
  pre-pass. `kEmitSceneCaustic` keyed its photon jitter only on the thread cell
  index (no seed anywhere down `buildCausticAim`â†’`cuda_photon_caustic_build`), so
  every progressive iteration rebuilt a BYTE-IDENTICAL photon map â€” the caustic
  noise was frozen and could never average. Thread the render seed into the three
  jitter salts (XOR); aim geometry stays deterministic. New camera-noise-free
  seed-decorrelation gate: main 0.020Â·signal (frozen) vs 0.048 (decorrelated),
  same-seed byte-identical; REG:63 pre-pass kernel, shade fleet untouched. HW PASS.
- **pkg221 DONE** (PR #645) â€” importance-sample photon Î» âˆ the light SPD. Photon
  wavelengths were drawn UNIFORMLY over 380-720 nm and deposited pure CMF, never
  weighted by the emitting light's SPD (engine-wide, CPU+GPU) â€” so a sodium lamp
  threw a continuous rainbow. Inverse-CDF sample Î» from the dominant light's SPD
  (built host-side via `LightSampler::sample`, byte-mirrored CPU/GPU, 341-entry CDF
  to `__constant__`); the S/p weight collapses to the constant integral I;
  broadband/no-SPD lights fall back byte-identically. Sodium caustic now AMBER
  (chroma 0.824/0.176/0.000, warm 0.82) vs white 0.01; white-source parity
  unchanged (SSIM 0.977). REG 63â†’70, shade fleet untouched. Cited PBRT-v4 Â§4.5.4.
  HW PASS. **(One CI catch: the `LightSampler&`â†’`LightList` template fix was left
  uncommitted, green locally on MSVC but red on GCC/CI â€” the
  `mingw_local_vs_gcc_ci_divergence` lesson; fixed + re-verified.)**
- **pkg222 DONE** (PR #646) â€” mercury lamp SPD magentaâ†’greenish-white. The stored
  `mercury_vapor` SPD used blue 435.83:1000 >> green 546.07:500, OMITTED the yellow
  576.96/579.07 doublet, and added an unjustified 5% continuum â†’ integrated to a
  magenta-below-locus xyâ‰ˆ(0.314,0.311). Corrected to the NIST Handbook Hg I
  persistent-line intensities (green-dominant + yellow doublet, no continuum) â†’
  greenish-white xyâ‰ˆ(0.335,0.369), Î”xyâ‰ˆ0.01 of the (0.33,0.38) target. Data +
  generator only, no C++ change. Verified: Python chromaticity audit + end-to-end
  GPU render (magentaâ†’green-dominant, visually confirmed) + 28 spectral + 6 GPU
  emission-parity tests; sodium unchanged. Synergises with pkg221.
- **Cost-routing finding** (memory `delegate-tier-stalls-on-hard-packages`): the
  deepseek-v4-pro implement tier wrote the cite/research notes but returned 0-code
  on the hard multi-file changes (pkg221/223) â€” those stayed on Opus. The opencode
  worktree-delegation bug (`--dir` not forwarded â†’ main contamination masked as
  `files_changed:[]`) was root-caused and FIXED (commit c00832c).
- **Still open / next pickup:** pkg223 (Normal Map node â€” addon+CPU+GPU shade
  behind `template<bool HasNormalPerturb>`, register-hostile, Opus-last-line; cheap
  worker filed only the research note). pkg201 Stage 3, pkg131 carried forward.

**2026-08-21 â†’ 2026-08-22 (SPECTRAL MILESTONE + BLENDER-INTEGRATION SWEEP â€”
8 PRs merged, 0 open):** the full spectral milestone landed and shipped in a
fresh Blender addon. **Merged:** pkg213 light-intensity Power slider (#628),
pkg214 sodium/atomic-emission **energy-normalization refix** (#632, supersedes
the #629 mercury-regression HW-FAIL), pkg215 project-index query/freshness
overhaul (#633), pkg206 luminance-weighted hero-wavelength importance sampling
(#634 â€” a Cycles-parity review caught + I fixed a GPU band-bias before ship),
#635 native Astroray nodes now honoured on Blender's stock Material Output,
pkg216 project-index wired into the agents (#636), #637 CPU tree-light-sampler
empty-list black-render fix, #638 GPU preset-lamp red-shift fix (deviceReference
4-sample-MC â†’ CMF-grid integral). Also: knowledge-graph viz fixes + the
committed interactive index graph (`.astroray_plan/project-index-graph.html`),
and the 2026-08-22 run report. A fresh `dist/astroray-4.0.0-cuda.zip` was built
from main and verified headless (engine + 11 panels register). **Filed for
later (open):** pkg217 (GPU refractive/dispersive caustics â€” glass casts a black
shadow; owner-deprioritized), pkg218 (spectral colorimetry fidelity â€” mercury
stored SPD is chromatically magenta not blue-green, + make the CIE observer /
camera response function swappable; Pillar 4), pkg219 (per-texel shader-graph
evaluator â€” the addon constant-folds node trees so Color Ramp / Mix / Mapping /
non-UV coords downstream of a texture silently break; integration-first). Live
Blender-MCP debugging drove most of the bug-finding this session.

**2026-08-19 â†’ 2026-08-21 (in progress, 6 PRs merged #624â€“#628, 1 open #629):
pkg200's last filter-related honour row closes, the pkg198 volume-pass split
closes, a UnicodeEncodeError test-hygiene chip lands, the light-intensity
(Power) slider is exposed in the Astroray panel â€” and the sodium-vapor
emission fix (#629) is HW FAIL, regressing mercury_vapor via peak-normalisation
coupling, with a physics-correct fix in progress on branch `pkg214fix`.**
- **pkg203 DONE** (PR #624, 2026-08-19) â€” Cycles-accurate pixel-filter
  widthâ†’Ïƒ mapping, CPU+GPU byte-mirrored (Ïƒ=width/4 Gaussian, Â±1.5Â·width
  support; BH Â±1.0Â·width support Â±2Â·width offset), cited against Cycles
  `film.cpp` + PBRT-v4 Â§8.8. Closes pkg200's last filter-related
  `pixel_filter_type` HONEST-FAIL row.
- **pkg204 DONE** (PR #625, 2026-08-19) â€” GPU wavefront volume-pass
  direct/indirect split, closing the pkg198 Stage-2 documented limitation:
  a first-interaction bit in the NEE int lane distinguishes a first
  volume scatter (`PASS_VOLUME_DIRECT`) from a deeper one
  (`PASS_VOLUME_INDIRECT`); direct+indirect sum exactly to the combined
  volume beauty (9 DIRECT/10 INDIRECT split measured); shade-kernel
  register HARD gate unchanged.
- **pkg205 DONE** (PR #626, 2026-08-19) â€” UnicodeEncodeError console-test
  hygiene: ASCII-ized `print()` glyphs (Î»â†’lambda, Ï€/Â°â†’pi/deg, âœ“â†’[OK]) in 3
  tests that were crashing under cp1252 before their assertions could run;
  4 passed, 0 UnicodeEncodeError; test-only diff, no engine change.
- **pkg213 DONE** (PR #628, 2026-08-21) â€” light intensity (Power) exposed
  in the Astroray light panel (`layout.prop(light, "energy")`); the engine
  already consumed `light.energy` (pkg176-era wiring), this was UI-surfacing
  only. Render-brighter gate â‰¥1.5Ã— mean linear RGB at 120 vs 30 intensity;
  headless-Blender wiring gate confirms `add_point_light` receives the set
  value end-to-end.
- **pkg214 OPEN, HW FAIL** (PR #629, 2026-08-21) â€” sodium-vapor lamp fix:
  broadened the aliased Na D-doublet to an energy-normalised Gaussian
  (FWHM 15 nm, area-conserving) so the sub-grid line is representable on
  the 5 nm profile grid (blackâ†’amber, R=2.09/G=0.43/B=0.00). HW
  verification FAILED: the same peak-normalisation change regressed
  `mercury_vapor` ~4.5â€“8.6Ã— too bright (coupling through `mat_ls`
  peak-normalisation, not isolated to sodium as the PR claimed). **A
  physics-correct energy-normalisation fix is IN PROGRESS on branch
  `pkg214fix`** â€” do not merge #629 as-is.
- **pkg206 released from hold, IN PROGRESS** (owner, 2026-08-21) â€”
  luminance-weighted hero-wavelength importance sampling. PR #627 (its
  first attempt) was CLOSED CI-red/biased: `test_flat_baseline_ssim` FAILED
  from a stacked realization-change + genuine achromatic-flat green-cast
  bias (companion wavelengths left at `pdf = 1/span` instead of each
  divided by the importance density at its own Î»). Re-dispatched fresh
  with the triage's per-wavelength-pdf correction on branch `pkg206impl*`;
  see the spec's 2026-08-21 triage section for the full root-cause and the
  distinguishing diagnostic for the next attempt.
- **Minor tooling note (not a package):** `project_index` knowledge-graph
  viz fixes landed same window (3D force-graph, orphaned dependency-edge
  resolution, 2D/3D toggle) â€” infra, no spec.
- **Pillar 4 remains PAUSED** â€” no new owner directive this window; the
  unpause decision is still standing open, unchanged.
- **NEXT_STAGE_REPORT.md was stale** (dated 2026-08-15, top pick pkg203
  had already shipped along with pkg204/pkg205) â€” regenerated this pass,
  see that file for the current pickup queue (pkg214fix completion,
  pkg206 re-verification, pkg201 Stage 3, pkg131, and the Pillar 4
  unpause decision still at the top).

**2026-08-14 â†’ 2026-08-15 (round closeout, 9 PRs merged #615â€“#623, no open
PRs at closeout): the GPU wavefront gains real god-rays (full HG scattering,
both backends), a full GPU light-path AOV render-pass mirror, a legacy
`.blend`-importer sun fix, and 3 more settings-honour rows flip PASS â€”
narrowing the "steering wheel drops most settings" gap pkg200 surfaced.**
- **pkg190 follow-up DONE** (PR #615) â€” narrowed the 3D-voxel procedural
  bake to Generated coord-mode only; Object-coord procedurals now degrade
  to a guarded flat-albedo fallback on GPU instead of silently misrendering
  (GPU flat gray 189.76 vs CPU checkerboard 165.29, HW PASS).
- **pkg200 DONE** (PR #616) â€” native-settings F12 pixel-honour matrix: A/B
  driver + real Blender 5.1/5.2 sweep, 8 PASS / 13 HONEST-FAIL / 2
  NEEDS-VISUAL / 2 LIMITATION. Surfaced findings Aâ€“F: the GPU wavefront
  silently drops per-type bounce counts, `filter_glossy`, the pixel
  reconstruction filter, native caustic toggles, and transparent-film alpha
  â€” closed one-by-one by pkg201 below.
- **pkg199 Stage 2 DONE, BOTH backends** (PR #617 CPU, PR #619 GPU) â€” full
  HG in-scatter homogeneous world-volume scattering. CPU (2a): analytic
  single-scatter density-shape match â‰¤0.9%, Î±-linear, forward/back HG
  asymmetry 2.0Ã—/1.48Ã—. GPU (2b, PR #619): `template<bool HasWorldScatter>`
  fleet isolation (dedicated `stageVolumeScatterKernel`, REG 64/STACK 88) â€”
  fog-free scenes stay byte-identical to the Stage-1 fleet
  (`intersect<false>` REG 127/STACK 616 unchanged); god-ray CPUâ†”GPU parity
  [1.0044, 0.9972, 0.9978], forward/back ratio 1.707. The GPU wavefront now
  delivers real god-rays/light shafts, not just absorption. HW PASS both
  PRs.
- **pkg201 Stage 1 DONE** (PR #618) â€” addon settings-honour: fixed the
  `world_max_bounces` read (was reading a nonexistent AO-datablock member,
  always 1024 â†’ now `world.cycles.max_bounces`), HONEST-FAILâ†’PASS ratio
  5.24 on 5.1 and 5.2; reconciled `use_light_tree`'s tri-state-vs-bool
  mismatch (KNOWN-GAPâ†’NEEDS-VISUAL, confirmed honoured); fixed a latent
  `set_light_sampler` crash the reconciliation exposed (UI enum shipped
  `'uniform'`/`'light_tree'`, setter only accepted `'power'`/`'tree'`).
- **pkg201 Stage 2 DONE, 2-of-6 rows shipped** (PR #623) â€” **F-alpha**
  (`film_transparent`): the GPU wavefront now writes real per-pixel alpha
  (background-miss coverage accumulator), alpha A=0.246 vs B=1.000 â€” the
  FIRST implementation of transparent-film alpha anywhere in the engine
  (the CPU path is equally inert, never wired). **`filter_width`** (half
  of Finding D): pixel reconstruction via filter importance sampling in
  `stage_init.cu`, grad ratio 1.0125 > 1.01 threshold. `pixel_filter_type`
  honours the filter in the correct direction but stays HONEST-FAIL at
  0.83% (below the 1% bar) â€” root cause is a `Ïƒ=width/6` mapping narrower
  than Cycles'; the fix is filed as **pkg203** (CPU+GPU parity change,
  deliberately not made in this closeout). Findings **E** (native caustic
  toggles) and **F-glass** (`film_transparent_glass` world-through-glass
  compositing) reclassified: E moved to Stage 3 (register-hostile, the
  path-tracer's own specular-caustic light paths need per-ray history, not
  the pkg113 photon pre-pass which is never enabled in the honour scene);
  F-glass filed as a next-round architect follow-up feature (real
  world-through-glass compositing, not an alpha copy-back). Stage 3 (per-
  type bounce counters + `filter_glossy` + Finding E) stays OPEN,
  probe-gated.
- **pkg198 Stage 2 probe DONE** (PR #620, docs) â€” register-gate PROCEED
  verdict: the light-path-pass partition compiles to zero STACK/register-
  tier change (fleet `<â€¦,false>` shade kernel byte-identical
  254/3352/1700) via a global-scatter design. Cleared the way for the full
  mirror below.
- **pkg198 Stage 2 DONE** (PR #622) â€” full GPU wavefront light-path
  render-pass mirror (diffuse/glossy/transmission direct+indirect,
  emission, environment), `HasLightPassAOVs` fleet-isolation axis. GPU
  sum-to-beauty exact (rel_L1 0.0), CPUâ†”GPU per-pass mean-ratio within
  ~2%, fleet HARD gate re-confirmed on the full-impl `.pyd` (shade
  `<0,0,0,0,0>` 254/3352/1700 + intersect `<false,false>` 127/616; passes
  ON/OFF beauty byte-identical 3.6e-7). **pkg198 is now DONE across both
  stages (CPU classification + GPU mirror).** Volume direct/indirect pass
  split not mirrored (documented limitation, deferred).
- **pkg202 DONE** (PR #621) â€” legacy `add_sun_light` GPU zero-contribution
  fix: converts the legacy hittable `DistantLight` to the pkg89 dedicated-
  distant representation at scene-upload time. GPU sun 0.0â†’0.6333 vs
  analytic ÏÂ·S/Ï€ 0.6366 (== CPU dedicated 0.6345, parity ratio 1.000);
  fixes every `.blend`-importer sun on GPU, no new device code. Also killed
  a dead CDF entry the old GPRIM_SKIP path left behind.
- **Specs filed this round for follow-up:** **pkg203** (Cycles-accurate
  pixel-filter widthâ†’Ïƒ mapping, CPU+GPU parity, closes pkg200's
  `pixel_filter_type` row â€” gated on pkg201 Stage 2, which is now merged,
  open, dispatchable).
- **Known-issue hygiene item (not a regression):** 3 pre-existing test
  failures throw `UnicodeEncodeError` on `print()` of Ï€/âœ“/Î» console
  artifacts under the default cp1252 console encoding â€” a console-output
  bug in the tests themselves, not an engine defect. Fix by forcing UTF-8
  stdout (or dropping the unicode glyphs) in the affected tests; low
  priority, file if picked up.
- **Open follow-ups carried forward:** pkg201 Stage 3 (per-type bounce
  counters, `filter_glossy`, native caustic toggles â€” register-hostile,
  probe-gated), pkg203 (filter Ïƒ parity), pkg131 (zero-knob adaptive
  sampling, wavefront leg), the F-glass transparent-glass world-through-
  compositing follow-up (pkg201-S2 park), the CPU legacy-hittable
  delta-sun `isDelta`/MIS fix surfaced by pkg202's findings (the dedicated
  conversion sidesteps it for the sun case but the underlying legacy-light
  MIS gap is unfixed), pkg198's volume-pass direct/indirect split
  (deferred in #622), the 3-test UnicodeEncodeError hygiene item above,
  and the standing Pillar 4 unpause decision (no new owner directive this
  round).
- **Owner request:** a FRESH ARCHITECT-LED run next session â€” the architect
  plans ahead before dispatching, rather than picking up ad hoc from this
  report's tail pool.
- **Round verification discipline:** every code PR dual-gated (CI +
  independent RTX hardware verification); every landed code PR this round
  reports HW PASS (pkg198-s2 probe and pkg203-filing were docs-only, no HW
  leg needed).

**2026-08-13 â†’ 2026-08-14 (round closeout, 8 PRs merged #605â€“#612, no open
PRs at closeout): viewport navigation goes from a slog to interactive
(5.97â†’18.52 fps, 3.1x combined), Principled tinted-layer/thin-wall spectral
carry closes pkg188's 72% band-error finding, the GPU wavefront gains
denoise-guide AOVs + a working world-volume fog + procedural textures, the
camera-view overlay is now pixel-exact, and pkg195 (spectral node system) is
FULLY COMPLETE across all three stages.**
- **pkg192 DONE** (PR #605) â€” viewport navigation interactivity, Suspect A:
  camera-only orbit/pan/zoom frames skip the per-frame CPU BVH rebuild
  (`skip_upload=True`); GPU 100k-tri 1280x720 min-of-N render 103.98â†’54.68ms,
  frame 167.54â†’118.45ms, **5.97â†’8.44 fps**. HW PASS.
- **pkg196 DONE** (PR #609) â€” Suspect B, layered on pkg192: reduced-res
  viewport nav (divisor N=2, Cycles-style), settle window snaps back to full
  res / hands off to pkg191's progressive loop. Orbit fps **8.36â†’18.52 p50
  (2.2x)**, same harness/scene as pkg192 â€” combined pkg192+pkg196 is
  **5.97â†’18.52 fps (3.1x)**. HW PASS.
- **pkg193 DONE** (PR #607) â€” camera-view overlay alignment: two bugs in
  `_apply_camera` (viewport off-center-frustum terms read from the wrong
  matrix cells; F12 datablock shift missing Blender's film-fit `viewfac`
  scaling). Worst-case corner offset **158â€“223px â†’ 0.00px** across 8
  conditions (17-case gate). Pure-Python addon fix, no `.pyd` rebuild
  needed; CI-gate only (no HW dispatch required).
- **pkg194 DONE** (PR #606) â€” Principled tinted-layer spectral-carry +
  thin-wall per-Î», both pkg188 Finding-C descopes. Register-gate probe
  PASSED (`<false>` byte-identical to main) so both shipped CPU+GPU. Band
  error on the pkg188 tint-over-base cases: **72.46%â†’0.00%**,
  34.93%â†’0.00%, 20.14%â†’0.00%, 5.36%â†’0.00%. HW PASS.
- **pkg197 DONE** (PR #608) â€” GPU wavefront denoise-guide AOVs
  (albedo/normal/depth) captured at the intersect stage (shade kernel
  untouched, byte-identical REG:254/STACK:3352/CONSTANT[0]:1700); also wired
  `applyPasses`/OIDN into the GPU render route for the first time (was
  beauty-only). Denoise A/B: guided edge-MSE 0.001491 vs guideless 0.001621,
  **+8.0% improvement**. GPU renders now actually denoise. HW PASS.
- **pkg199 Stage 1 DONE** (PR #611) â€” GPU wavefront homogeneous-world
  Beer-Lambert absorption, CPU+GPU (also re-wires the CPU spectral tracer,
  which had carried dead volume code since pkg14). Spec premise corrected by
  git-archaeology first: the CPU never had HG in-scatter/NEE-through-medium;
  only dead Beer-Lambert absorption existed. Furnace Tr vs analytic
  `exp(-ÏƒÂ·d)` matches to **<2e-4**; shade kernel byte-identical. **hw-611 HW
  FAIL â†’ FIX â†’ HW PASS**: the sphere-light NEE leg used a 1e30 occlusion
  sentinel as the Beer-Lambert path length, saturating the fog to black;
  fixed to the true geometric NEE distance (commit 6e7bf6d), re-verified HW
  PASS. Stage 2 (full HG scattering medium, XL, CPU-first) filed spec-only,
  open.
- **pkg190 DONE** (PR #612) â€” GPU procedural texture support (checker/brick/
  magic/wave) via 3D-voxel bake-at-upload, reusing the cited CPU evaluators.
  **pkg119-B re-baselined first** (the "5 residual TRANSLATION-BUGs" story
  was stale/false): real set was 4 nodes, all now PASS (TEX_CHECKER
  0.8425â†’0.9512, TEX_BRICK 0.8980â†’0.9158, TEX_MAGIC 0.8358â†’0.9639, TEX_WAVE
  0.8935â†’0.9575) â€” **TRANSLATION-BUG 4â†’0, summary 25â†’30 pass**. Register
  fleet gate: all 16 `stageShadeBucketedKernel` specializations byte-
  identical before/after. **hw-612 HW FAIL â†’ FIX â†’ HW PASS**: `scripts/
  run_parity.py`'s scene-routing guard didn't recognize the new
  `textured_plane` scene (fell through to a no-op leg) and its EXR reader
  (`imageio.v3`) silently truncated to uint8 and zeroed the green channel;
  both fixed (commit b2b42eb), re-verified CPU/GPU mean-ratio **1.0000 /
  0.9996 / 0.9998**.
- **pkg195 Stage C DONE** (PR #610) â€” **pkg195 is now FULLY COMPLETE (all
  three stages, A+B+C)**. `register_spectral_profile` (pointer-stable deque
  storage), Drawn Spectrum node (Blender-native `CurveMapping`, the owner's
  headline "draw exactly which wavelengths" control), Spectrum Preset +
  Blackbody Spectrum nodes + bake-to-profile operator, in-band Replace mode
  (bypasses the Jakob-Hanika RGB round trip, routes to the CPU MW
  integrator), IR/UV Response de-fanged (no more destructive grey-Disney
  promotion), Sellmeier manual B/C read again (silently dropped since
  pkg57). Gate C all green; headless Blender 5.1 end-to-end confirms a
  drawn 550nm bump renders green-dominant (G=0.4396>R=0.2642>B=0.0003);
  manual BK7 vs preset dispersion 0.00% apart; 16/16 A/B+parity gates
  unchanged (GPU degradation documented, not regressed).
- **Specs filed this round:** pkg196/197/198/199 (PR from the prior
  addendum's vetted set) â€” pkg196, pkg197, pkg199 Stage 1 all DONE above;
  **pkg198** (GPU wavefront light-path AOV passes, register-hostile,
  probe-first â€” "may park") remains OPEN.
- **Pre-existing gap surfaced during pkg199 review, not fixed here:** the
  opt-in caustic integrator (`pathTraceSpectralCaustic`) and the CPU
  wavefront reference do not read `c_worldVolume`/world-volume absorption at
  all â€” a caustic render through fog ignores the fog. Documented as a Stage
  1 non-goal in the pkg199 spec; candidate for a follow-up spec, not filed
  yet.
- **Open follow-ups carried forward:** pkg198 (light-path AOV passes),
  pkg199 Stage 2 (full scattering medium, XL, CPU-first), pkg131
  (zero-knob adaptive sampling, wavefront leg), the pkg176-line deep
  per-setting F12 pixel-honour matrix (deferred to a later addon HW
  session, no dedicated spec), and two unfiled follow-up chips: the legacy
  (non-dedicated) `add_sun_light` GPU-dimness finding surfaced during pkg194
  review (pkg89 Phase B's `add_sun_light_dedicated` doesn't reproduce it;
  diagnosis-first, not filed), and an Object-coordinate-mode guard for the
  pkg190 procedural bake (the 3D-voxel bake covers Generated-space nodes
  only per spec scope; Object-coordinate-mode procedural textures have no
  explicit GPU guard/fallback documented â€” could silently misrender if hit).
- **Round verification discipline:** every code PR dual-gated (CI +
  independent RTX hardware verification), two of eight (pkg199, pkg190)
  went through a full HW FAIL â†’ fix â†’ re-verify HW PASS cycle before
  merge.

**2026-08-13 (post-closeout addendum â€” 3 more PRs merged overnight, #601â€“
#603, on top of the round closeout below): CUDA-arch infra root cause
closed, GPU wavefront dispersion goes live, and the HEADLINE lamp-lighting
finding from the closeout below gets fixed for the CPU MW tracer.
Owner-facing wins: lamp-lit NIR/UV renders now work (mean 0.0003â†’0.0709),
sodium lamps render amber from the Blender light panel, and GPU prisms
render real ROYGBIV rainbows.**
- **Infra arch root-cause DONE** (PR #601) â€” closes the three root causes
  behind the 2026-08-12 stale-CUDA-arch incident that pkg183 (below) had
  deliberately left as a follow-up: CMakeLists now sets
  `CMAKE_CUDA_ARCHITECTURES` as `CACHE ... FORCE` (was a non-cache `set()`
  silently shadowing the cache), the VS-generator configure entry point
  (`configure_and_build.bat`) resolves `native` to a real arch via
  `nvidia-smi` (was compiling sm_52 under the VS generator even though the
  cache said sm_120), and `build_blender_addon.py` now injects an explicit
  arch default and re-asserts it on every reconfigure. `cuobjdump
  --list-elf` ground-truth confirms sm_120 on all three build outputs
  (VS-gen, Ninja, addon) post-fix.
- **pkg189 DONE** (PR #603) â€” GPU wavefront hero-Î» dispersion is now LIVE
  for both material families (see the full entry below); closes the
  pkg187 GPU-visible gap and the pre-existing pkg64 dielectric xfail. The
  flat-prism GPU-photon dispersion caustic (still noise) is filed forward
  as an orthogonal follow-up â€” its test went from a vacuous XPASS to an
  honest, owned XFAIL.
- **pkg195 Stage A+B DONE** (PR #602) â€” fixes the HEADLINE ENGINE FINDING
  below for the CPU MW tracer: dedicated-light NEE (spectral, two-sided
  MIS, gated on `enable_nee` mirroring the template integrator) +
  spectral lamp presets in the addon (`spectrum_mode` enum â€” native /
  preset / custom_profile â€” sodium_vapor etc. via `measured_spd`). NIR
  snow-sphere mean 0.0003â†’0.0709 (>0.05 gate), sodium lamp linear RGB
  (0.673, 0.127, 0.000) reads amber, headless Blender 5.1 confirms amber
  sodium vs neutral cie_f2 from the actual light panel UI. Fixed a latent
  bug along the way: a narrow-line SPD (sodium's ~589 nm spike) drove
  `PowerLightSampler`'s power-CDF to a degenerate 0/0 NaN selection pdf,
  silently dropping the lamp â€” now falls back to uniform selection (PBRT
  UniformLightSampler pattern). **Verification arc:** the first HW pass
  FAILED â€” unconditional NEE changed the CPU MW oracle under 3
  CPU-vs-GPU parity gates (SSIM 0.995â†’0.30) â€” fixed by mirroring the
  `enable_nee` condition and pinning `enable_nee=0` on the oracle legs
  (documented Phase-3 contract: GPU MW-leg light sampling is future
  work); all 10 parity gates recovered to historical values, independently
  confirmed. Stage C (`register_spectral_profile` binding, Drawn/Preset/
  Blackbody spectrum nodes, in-band Replace mode, IR/UV de-fang, Sellmeier
  B/C) remains OPEN, independently landable.

**2026-08-12 â†’ 2026-08-13 (day run + overnight, 15 PRs merged #585â€“#599, no
open PRs at closeout): GPU capability-restoration wave (first GPU texture
support, viewport progressive-refinement fix) + two Principled spectral
correctness fixes + a build-integrity guard â€” plus a HEADLINE engine finding
that every lamp-lit NIR/UV render is black end-to-end.**
- **pkg183 DONE** (PR #592, 2026-08-12) â€” stale-object ABI-mixed-binary guard
  (header-hash stamp + force-clean-on-mismatch, <5s host-only ABI canary) in
  all three build wrappers, plus a cuobjdump ground-truth CUDA-arch gate
  (exit codes 6/7) that catches the fleet-wide stale
  `CMAKE_CUDA_ARCHITECTURES=52` CMakeCache class of incident: worktree
  resource-gate readings of STACK 2640 were Maxwell-PTX artifacts, the true
  sm_120 `<false>` baseline is STACK 3608. The root-cause trio (CMakeLists
  non-cache `set()`, `configure_and_build.bat`, `build_blender_addon.py`
  hardcoded arch/Debug revert) is deliberately out of scope â€” queued as an
  infra follow-up PR.
- **pkg185 CLOSED** (PR #589, 2026-08-12) â€” the GPU glass-caustic parity gate
  failure root-caused to the TEST SCENE, not GPU transport: the sun light
  was un-Î©-scaled, driving irradiance to ~19100 and collapsing SSIM to
  0.0101 on 3 legitimate specular fireflies; fixed the test, SSIM
  0.0101â†’0.9606, GPU peak 1007â†’0.41. GPU transport confirmed healthy.
- **pkg186 DONE** (PR #590, 2026-08-12) â€” first GPU image-texture support:
  baked-buffer + nearest fetch, `__constant__ c_wfTexBinding`, after a
  verifier-caught +24B kernel-signature regression was fixed back to exact
  kernel identity (REG:254/STACK:3608/CONSTANT:1700). Backend-aware
  `__gpu_features__` dict â€” the addon Diagnostics panel no longer claims GPU
  textures/volumes/adaptive/GR it doesn't have.
- **pkg182 follow-up DONE** (PR #586, 2026-08-11) â€” per-Î»-native Principled
  conductor thin-film supersedes the RGB-upsample approximation; 17/17 gates
  HW-verified. Measured finding: saturation barely moved (mean
  0.0488â†’0.0499, max 0.1842â†’0.2045) â€” the premise that RGB-upsample
  visibly mutes metal iridescence doesn't hold in the 4-sample
  hero-wavelength pipeline; this is a correctness/consistency win (no JH
  round-trip loss, correct under spectral/colored light), not the
  saturation jump the ticket implied.
- **pkg187 DONE** (PR #593, 2026-08-12) â€” Principled BSDF dispersion,
  CPU-complete (OpenPBR/Cycles-WIP Cauchy fit from IOR+Abbe, cited): prism
  chromatic spread 4.267â†’5.345px, zero-dispersion bit-identical, `<false>`
  shade kernel byte-identical at TRUE sm_120
  (REG:254/STACK:3608/CONSTANT:1700). GPU leg wired but gated on the
  pre-existing pkg189 no-op (hero-Î» refraction never varies IOR on GPU â€”
  the dielectric reference shares the same gap). Two premise corrections:
  no shipped Blender exposes a Dispersion socket (unmerged upstream WIP
  #162041 â€” the addon got a forward-compatible probe); `test_gpu_prism_
  rainbow_parity`'s XPASS was vacuous, xfail retained.
- **pkg189 DONE** (PR #603, 2026-08-13) â€” GPU wavefront hero-Î» dispersion
  enablement. Root cause: the wavefront shade kernel never persisted the
  sampler's `terminateSecondary()` hero-collapse back to the per-path SoA, so
  the mutated Î»-pdfs evaporated each bounce and `spectrumToXYZ` kept summing all
  4 wavelengths (achromatic). Fix: SoA write-back gated by a compile-time
  `HasDispersion` 4th axis (zero REG/STACK â€” `<*,*,*,0>`â‰¡`<*,*,*,1>`, fleet
  `<0,0,0,0>` REG:254/STACK:3352). GPU dispersion now LIVE for BOTH families:
  dielectric BK7 disp/flat **0.5508**, Principled **0.5507** (were ~1.00 no-op),
  CPU/GPU per-channel parity within 4%, visually-confirmed spectral rainbow on a
  glass sphere. `test_pkg64_gpu_cpu_parity` un-xfailed â†’ real mean-ratio gate;
  pkg187 GPU no-op gate flipped to assert live dispersion. Flat-prism *photon*
  caustic still noise (2-face-GPU-photon follow-up â€” orthogonal, out of scope).
- **pkg184 DONE** (PR #597, 2026-08-12) â€” `template<bool HasPhotons>`
  isolation of the photon-caustic k-NN gather (8 kernel instantiations):
  every HasPhotons=false variant strictly below baseline (STACK
  âˆ’128..âˆ’256B), HasPhotons=true variants byte-identical; non-photon
  glass-sphere shade kernel âˆ’2.3% wall vs +0.1% byte-identical control.
- **pkg191 DONE** (PR #598, 2026-08-12) â€” GPU viewport progressive
  refinement: root cause was the GPU dispatch ignoring the
  `renderSeed==0` â†’ fresh-random contract, so every viewport chunk
  rendered IDENTICAL noise. One-spot fix in `blender_module.cpp`;
  MSE-to-256spp 7.0e-4â†’1.3e-5 across iterations, HW-verified.
- **pkg188 DONE** (PR #599, 2026-08-12) â€” Principled film-off transmission
  colour/scalar separation, CPU+GPU (retires the "Stage-3b upsample hack")
  + a weight-path clamp guard. Finding C descoped to new spec pkg194.
  QUANTIFIED residual: `upsample(aÂ·b)` vs `upsample(a)Â·upsample(b)` up to
  ~72% band error on coloured-tint-over-dark-base (0% for the common
  white-tint case) â€” this raises pkg194's priority.
- **pkg175 flipped to done** (PR #547, 2026-08-07 â€” drift-gate fix, its spec
  had stayed "in review" past its own merge): one-command Blender dev loop,
  150s full rebuild / 5.8s `-SkipBuild`, on-hardware smoke `RESULT PASS`.
- **HEADLINE ENGINE FINDING (pkg195 design session, PR #596, 2026-08-12):**
  `multiwavelength_path_tracer` has NO light sampling â€” every lamp-lit
  NIR/UV render is black end-to-end. The profile-selector node is a
  visible-band no-op; the IR/UV response node is destructive.
  Sodium/mercury lamp SPDs are already engine-ready but not exposed. A
  drawn-spectrum node is filed as a genuine differentiator (no other
  renderer has one). pkg195 Phase 1 spec filed, not yet implemented.
- **Specs filed, not yet implemented:** pkg190 (GPU
  procedural textures, pkg186 slice 2, needs a pkg119-B re-baseline first;
  PR #594), pkg192/pkg193 (viewport-addon diagnosis-first specs from owner
  hands-on feedback, PR #595 â€” pkg192 viewport interactivity 3-5fps vs
  Cycles ~30fps, pkg193 camera-view overlay misalignment; pkg191, filed in
  the same PR, landed same round â€” see above), pkg195 Stage C (spectral
  node system remainder â€” register_spectral_profile binding +
  Drawn/Preset/Blackbody nodes + in-band Replace mode + IR/UV de-fang +
  Sellmeier B/C; Stages A+B DONE, see the 2026-08-13 addendum above).
  pkg189 (used to be listed here) is DONE â€” see the 2026-08-13 addendum
  above.
- **Infra, not tied to a package:** `.gitattributes` forces CRLF checkout
  for `.bat`/`.cmd` (PR #585, prevents the class of silent cmd.exe
  mis-parse this repo has hit before); comprehensive repo hygiene sweep
  (PR #587, pre-session â€” dead code/scripts/tests/docs removal, tcnn
  opt-in, guardrails; filed pkg183/184/185).
- **Owner decisions (2026-08-12):** wavefront perf ceiling STAYS at 1.5s
  (ratified, improve opportunistically); overnight autonomous run
  authorized; owner hands-on addon feedback drove pkg191-193 + the
  spectral-node design (pkg195).
- **Round verification discipline:** every code PR dual-gated (CI +
  independent RTX hardware verification); three verifiers serialized via
  the GPU lock overnight.
- **Open follow-ups carried forward:** pkg190, pkg192, pkg193, pkg194
  (priority raised by the 72% finding above), pkg195 Stage C, the
  flat-prism GPU-photon dispersion follow-up (pkg189's #603 honest-xfail),
  the `GLoweredMaterial` by-value prototype re-apply (worktree
  `sad-maxwell`), pkg180 diagnosis. pkg189 and the infra arch root-cause PR
  are DONE â€” see the 2026-08-13 addendum above.

**2026-08-11 (post-Principled-block parity verification + harness band re-pin â€”
CLOSES the last two owed pkg178 items):** thin-film saturation parity vs Blender
5.2 Cycles is VERIFIED and the coordinated pkg119-B/pkg129 band re-pin is DONE;
`use_native_principled` is RATIFIED to production default ON.
- **Thin-film acceptance GREEN.** New identical-scene A/B harness
  `benchmarks/cycles-parity/thin_film/` (both legs render the same translated
  Blender scene through the real addon Principledâ†’native path, incl. #581
  thin-film sockets), swept thickness {100â€“1000 nm} Ã— film-IOR {1.2,1.5,1.8} Ã—
  {dielectric, conductor} on Blender 5.2. **Dielectric** (analytically-exact
  Belcour Fresnel): 18/18 in-band, hue tracks Cycles 6.0Â° mean; the film-IOR=1.5
  cells correctly show ZERO iridescence (film IOR = base IOR). **Conductor**
  (RGB-upsample approx): 18/18 in-band, per-channel RGB chroma EXACT (â‰¤2.09 %),
  hue tracks 10.1Â° mean / 25.4Â° max on saturated cells at dE â‰¤ 1.39 â€” a MUCH
  smaller gap than assumed; the per-Î»-conductor follow-up is now LOW priority.
  Visually confirmed (montage). Details:
  `.astroray_plan/docs/pkg178-thinfilm-parity-findings.md`.
- **Harness band re-pin (toward-Cycles, evidence-clean).** pkg119-B re-run on
  Blender 5.2: 39 features â†’ 25 pass / 1 skip / 13 fail; all 4 dedicated lights
  now PASS (dE â‰¤ 1.6) and BSDF_PRINCIPLED PASSES (SSIM 0.972, dE 1.88). Removed
  the now-stale pkg89 light INTENTIONAL-DIVERGENCE exemptions from `triage.py`
  (pkg181 fixed the dim; a future light regression must surface as a bug). The
  180Â° AREA-flip was already gone (pkg181). pkg129 metal A/B re-run: 12/12 legs
  pass, ratios in [0.857, 1.016] â†’ ceiling tightened 1.15â†’1.05 (energy-GAIN
  guard; floor held 0.85 = binding high-roughness chromatic-blue multiscatter
  residual). Both harnesses' `_find_blender` now prefer Blender 5.2 (pkg178-D1
  oracle). The 5 residual pkg119-B TRANSLATION-BUGs are all procedural texture
  nodes (pre-existing parity gap, unrelated to this round).
- **Stage-5 default RATIFIED.** `use_native_principled` production default ON â€”
  the owner-authorized auto-flip gate (memory `pkg178-repin-and-stage5-autonomy`)
  is satisfied by the green matrix above; the "(experimental)" label is removed.

**2026-08-08 â†’ 2026-08-10 (Principled-BSDF completion run, 17 PRs merged
#566â€“#582): native Cycles-Principled BSDF is COMPLETE (Stages 0â€“5) incl.
thin film/thin wall + Blender native routing â€” headline of the Integration
Milestone arc.**
**pkg178** ships a faithful `"principled"` material plugin, CPU+GPU
byte-mirrored throughout: Stage 0+1 core-lobe scaffold + Stage 2 GPU
closure-graph twin (#566/#567); Stage 3 advanced layers â€” coat (GGX +
coat_ior + coat_tint Beer)/sheen (Zeltner 2022 LTC)/approx-SSS/emission
(#571) behind a new `template<bool HasPrincipled>` D4 shade-path isolation
(#570, closes a +52% fleet-wide non-principled regression permanently â€”
non-principled `<false>` STACK pinned at **3608 B** through every later
stage); CPU UV-aligned tangent plumbing (#572); height-correlated Smith G2
for the reflect lobes (#573, Heitz 2014 â€” every furnace gate moved TOWARD
1.0, e.g. metallic r0.3 0.929â†’0.960); anisotropic GGX Î±xâ‰ Î±y + gated GPU UV
tangent (#574, fixed a real ~4.1%â†’<0.5% iso-continuity discontinuity found
along the way); alpha as a Fable-proven delta transparent lobe (#575,
byte-identical to the pre-existing glass at alpha=1). **Stage 4 â€” thin
film + thin wall** (Belcour-Barla 2017 Airy reflectance, cited Cycles
`bsdf_util.h`/`bsdf_microfacet.h`, BSD-3): shared utility + CPU dielectric
iridescence (#577, thickness-0 EXACT no-op), CPU conductor iridescence
(#578, Gulbrandsen F82â†’(n,k) inversion), GPU twin of both (#579 â€” a
by-value `GMaterial` data leak was caught and fixed mid-PR, keeping
`<false>` at 3608 B), thin wall (thin-glass) + thin subsurface (#580,
combined R+T closed-form geometric series). **Stage 5** routes Blender's
`ShaderNodeBsdfPrincipled` â†’ the native material incl. all Stage-4
thin-film sockets (#581, `use_native_principled` default ON â€” RATIFIED to
production 2026-08-11 once the Cycles-5.2 parity matrix went green, per the
owner's pre-authorization, memory `pkg178-repin-and-stage5-autonomy`; see the
2026-08-11 top entry).
Along the way, Stage 4 PR-4 surfaced a **pre-existing** `ggxReflect`
eval-D/pdf-D regularizer mismatch (`+1e-4` vs unregularized `D_GTR2`) that
made low-roughness Principled metallic/specular near-black (furnace
0.067â†’0.604 at r=0.02) â€” filed and fixed same-day as **pkg182** (PR #582,
eval-only, register-neutral).
**pkg172 effect (A) CLOSED**: the pbrt-v4 guarded-pdf form replaces the
biased `f/(pdf+1e-3)` estimator across CPU path_tracer/wavefront/
multiwavelength (PR #551, closes the universal 0.628%/bounce = `2Ï€Â·Îµ`
energy loss; clearcoat whole-sphere MSE floor re-pinned 5e-5â†’3.5e-5 with
in-test justification, primary specular asserts unaffected), the
`neural_cache`/`restir_di` follow-up legs (#553), and the two remaining GPU
NEE light-pdf sites (#576, register-neutral, no firefly-gate shift). Effect
(B) stays **pkg173**'s separate scope, below the Integration Milestone.
**pkg176 Stages 0â€“4 COMPLETE**: native Blender/Cycles settings, panels, and
world/light/camera properties are now the only steering wheel (PRs
#555/#556/#561/#568) â€” the custom ground-up UI is retired down to one
Astroray-only panel, owner-approved 2026-08-09; 45 unit tests + Blender 5.2
real-host register/headless-smoke PASS.
**pkg181** (dedicated-light visibility to BSDF rays, PR #569, 2026-08-08)
fixed the systemic ~12â€“20% Astroray-vs-Cycles dim AND dark lamp reflections
(mirror-lamp 0.017Ã—â†’~1.00Ã— Cycles) â€” a prerequisite this run's Cycles-
parity numbers rest on.
**pkg179 CLOSED by diagnosis** (owner-ratified Option 2, 2026-08-09): the
"3Ã— dead-sample rate" was a measurement-methodology mislabel, not a sampler
bug; no engine code changed; the Cycles combined-closure design is recorded
for pkg178's Principled dielectric (already reflected in pkg178's shipped
Stage-3/4 design).
**Open follow-ups (not closed, tracked forward, do not re-derive):**
conductor thin-film is an RGB-upsample approximation (metal iridescence
less saturated than Cycles' per-Î»; the dielectric leg is per-Î»-exact) â€”
documented approximation, enhancement-tier, not a defect; the durable
`GLoweredMaterial` by-value-`GMaterial`-copy fix (the recurring data leak
PR #579 and Stage 3 both hit and locally patched around) is prototyped in
worktree `.claude/worktrees/sad-maxwell-ff99d1` (uncommitted, PR-2-based)
and needs re-apply on settled main (memory
`closure-graph-lobe-count-spills-fused-kernel`). The thin-film-vs-Cycles
saturation parity verification + the coordinated pkg119-B/pkg129 harness
band re-pin (reflecting pkg181 + Smith-G + pkg172(A) + thin-film + pkg182
together) is **DONE 2026-08-11** (see the top entry). **Changelog:** pkg178 Stages 0â€“5 COMPLETE
(#566â€“#581), pkg182 filed+fixed (#582), pkg172(A) CLOSED (#551/#553/#576),
pkg176 Stages 0â€“4 COMPLETE (#555/#556/#561/#568), pkg181 DONE (#569),
pkg179 CLOSED by diagnosis. Full detail:
`.astroray_plan/docs/standup/2026-08-06.md`,
`.astroray_plan/docs/standup/2026-08-07.md`, reports
`.astroray_plan/docs/reports/2026-08-07-overnight-supervised.html`,
`.astroray_plan/docs/reports/2026-08-08-principled-bsdf-run.html`,
`.astroray_plan/docs/reports/2026-08-09-principled-stage3-complete.html`.

**2026-08-08 (run â€” dielectric energy chain + Cycles-parity harnesses):**
Landed this run: **pkg167 Part 1** (PR #562, MERGED) â€” Disney dielectric
REFLECTION-lobe multiscatter compensation CPU+GPU, furnace in-band
0.99/0.94/0.93 at r=0.3/0.6/1.0, pkg169 xfail retired. **pkg119 Phase B**
differential parity harness landed + HARDWARE-VALIDATED (PR #550, 26/12/1;
`world:World` + `BSDF_TRANSPARENT` flagged as TRANSLATION-BUG follow-ups).
**pkg129 metal A/B** run on current main (research doc Â§5) â€” **A/B CLEAN, no
application-form divergence; GPU â‰ˆ CPU (marginally brighter)**; conviction-path
LUT port does NOT fire. Two escalations surfaced and filed by the architect this
date: **pkg167 Part 2 was applied, measured, REVERTED, premise falsified** â€”
reflection compensation recovers only +0.009 at r=1.0 (0.476â†’0.485); the masked
~23% below-horizon energy belongs in the TRANSMISSION lobe and the dead-sample
rate is ~3Ã— pkg150's documented figure â†’ filed as **pkg179**
(sampler-diagnosis-then-transmission-redistribution, Track A). A **systemic
~12â€“20% Astroray-vs-Cycles dim** (pkg119-B cells ~0.88, pkg129 metal neutral
r0.9 ~0.93, plain diffuse backdrop ~0.79â€“0.82; uniform + chromatically uniform)
â†’ filed as **pkg180** (diagnosis-first; prime suspect a view-transform-vs-linear
comparison artifact). **pkg165** (Disney-metal GPU-dim) flipped to
**verify-and-close** â€” its premise does not reproduce on current main per the
pkg129 A/B.

**2026-08-06 â†’ 2026-08-07 (workflow restructure + settlement round opens):**
**PR #541 (pkg168 Step 2) MERGED 2026-08-06 (`bbf2d8c`) â€” option A** (owner
confirmed 2026-08-03): correctness v4 shipped with the wavefront perf
ceiling TEMPORARILY raised 1.0â†’1.5s; the revert is owned by **pkg174**
(dispatched 2026-08-07, in flight). pkg174's spec carries a measured
2026-08-07 addendum: the pinâ†’HEAD perf gap is **code accretion**
(0.705â†’1.260s at fixed toolchain), clock-state and toolchain hypotheses
refuted; baseline on the current toolchain is **1.156s**. Infrastructure
restructure landed the same window: local CUDA builds **NMakeâ†’Ninja +
native sm_120 + CUDA 12.8** (cold build 320.7â†’61.1s, `50b1d93`), **sccache**
shared across worktrees (`0ddfa49`), **CI docs-skip** (docs-only pushes now
~11s vs ~17min) + concurrency-cancel + caches, **pytest CPU/GPU split +
xdist** (PR #545, `c2e7bc3`), and the **opencode delegation layer**
(`78b451b`: grunt/implement/verify open-model tiers behind an
evidence-contract wrapper; tierâ†’model map in
`.claude/skills/delegate/config/tiers.json`). Reports:
`.astroray_plan/docs/reports/2026-08-06-restructure.html`.

**2026-08-01 â†’ 2026-08-02 (run closed, 11 PRs merged): pkg163/pkg158/pkg120
overnight; pkg150/pkg166/pkg156/pkg168-Step1/pkg169/pkg170 + pkg172 docs
(#543/#544) during the day.** See
`.astroray_plan/docs/standup/2026-08-01-overnight.md` and
`.astroray_plan/docs/standup/2026-08-02-dayrun.md` (both finalized) for full
detail. **5 real defects fixed** (pkg163 colour-space seam, pkg120's
naive-mode regression caught via pkg156, pkg169's three transmission bugs,
pkg170's opaque-Disney 2Ã— gain, pkg168's diffuse upsample-shape bug) plus
**2 convicted-not-yet-fixed** (pkg172 effect (A), pkg173). **PR #541
(pkg168 Step 2) is PARKED, not merged** â€” correctness verified and preserved
(v4 on branch, `6ef2c11`, unpushed), but blocked on a register-saturation
perf ceiling (`stageAdvance`/`stageShade` at 254 regs; best correct form
1.222s vs the 1.0s ceiling). A 4-way fork (ship+temp-raise /
register-pressure-package-first / permanent-re-pin / structural-hoist) is
documented in #541's PR thread; **decision deferred to the owner â€” top
action item, blocks pkg172(A), pkg173, and pkg168's closeout.** 9 new specs
filed (pkg165â€“pkg173), pkg129 narrowed, `NEXT_STAGE_REPORT.md` refreshed.
Three session-limit freezes noted (~01:35â€“04:00, ~02:13â€“13:30,
~06:25â€“19:50); no corruption at any resumption. **pkg163** spectral-vs-RGB
metal
colour-space parity (PR #533, `b036ac9`) â€” GPU metal now builds per-wavelength
via `gpu_metal_eval_spectral`, retiring pkg160's roughness-0.9-only
`[0.95,1.10]` band exception; standard `[0.95,1.05]` restored at all
roughnesses; decisive chromatic-spread control green at 0.0025 seed-averaged
(bound â‰¤0.01) after an initial single-seed HW FAIL (0.0133) was diagnosed as
MC noise in the statistic and re-measured at 2560 spp Ã— 4 seeds with the bound
unchanged. **pkg158** Step 0 Disney-metal remainder reconciliation (PR #535,
`7c340f6`) â€” Outcome A: the historical 0.60â€“0.77-vs-~1.0 near-delta
discrepancy is SUPERSEDED, both "credible measurements" turn out to be the
same test on different builds; re-measured once on `b036ac93`, near-delta
ratios 0.92â€“0.98 across the full roughness sweep, no cliff, all within
`[0.90,1.10]`. Its out-of-scope finding (a uniform ~5â€“8% Disney-metal GPU-dim,
R>G>B, in-band but unexplained) is filed as **pkg165** (diagnosis-first,
`d02fe07`). **pkg120** two-sided MIS for the spectral integrator (PR #534,
`7495691`) â€” restores the BSDF-ray-hits-emitter MIS term across 4 landing
sites (grew from the spec's 2 via the pkg55 growing-oracle rule); an initial
HW FAIL on its own analytic gate (0.745 vs 0.75) was first diagnosed as a
transport bug, then OVERTURNED by an 8Ã—8-patch-mean-vs-point-oracle control
proving it a steep-gradient sampling artifact â€” confirmed independently by a
different-model review that predicted the patch readings from geometry alone
within 0.002â€“0.024; re-gated at 2Ã—2 patch (band unchanged), HW re-gate PASS
(absolute gate 0.9623, full pkg55 web + wavefront bit-identity + 278 furnace
cases green). That sweep motivated **pkg166** (furnace suites render gamma,
cannot detect energy gain â€” filed `9930802`). **Day 2026-08-02, PR #536:**
**pkg150** closed â€” resolved-by-pkg149. Its charter (VNDF reflection
sampleable at grazing) was found ALREADY MET on main by pkg149 (#522):
measured 5.1% reflection acceptance at glass[0.3-45], sample()/pdf() exact
median match. The planned pbrt-v4 dead-sample fix was built and measured but
deliberately **not shipped** â€” it regresses the white furnace at high
roughness (r=1.0 CPU 0.997â†’0.788), because the legacy delta fallback was
ad-hoc compensating for missing reflection-lobe multi-scatter energy; the
chiÂ² gate's xfail reason was corrected (an ires=4 quadrature artifact is
~90% of the number, not the delta fallback, which is only 2.4%). The fix diff
is preserved at `.astroray_plan/docs/pkg150-deadsample-fix.patch` for
**pkg167** (new spec, `7be3245` â€” dielectric reflection-lobe multi-scatter
compensation, bundled with the dead-sample fix as an ordered two-commit
package). Also filed: **pkg129 narrowed** (`cf67a92` â€” original openpbr-LUT
port premise superseded by pkg160/pkg163; remaining charter is a live-Cycles
rough-metal A/B parity gate, port runs only if that convicts a real
divergence). **PR #538:** **pkg166** done â€” 20 furnace/energy tests converted
to linear (`apply_gamma=False`) with floor+ceiling pairs, every band change
transform-justified or a strengthening (adversarial + independent audit found
zero suspect moves); new autouse naming guard for `*furnace*`/`*energy*` test
names, proven by a negative self-test; a deliberate 1.5Ã— metal energy-gain
mutation was caught at 1.156 > 1.02 by the converted suite (gamma would have
clamped it to ~1.0 and passed). **HEADLINE FINDING:** the linear conversion
exposed a REAL energy-gain defect in Disney Principled glass transmission â€”
CPU 1.784 at delta / 1.10â€“1.26 rough, GPU conserving at delta but 1.10â€“2.30
rough â€” hidden by the gamma clamp for its entire life. Quarantined as 3
`xfail(strict=False)` cases owned by **pkg169** (new spec, `2565455`, **HIGH
priority**; its fix PR must remove the xfail markers). Also filed this cycle:
**pkg168** (RGBâ†’spectral upsampling parity, `99065b1` â€” owns restoring
pkg156's 0.998 gate). **PR #537:** **pkg156** partial fix + escalation â€”
pkg120's two-sided-MIS `w_B` leg was firing unconditionally in naive mode
(`enableNEE=false`), a real regression over-brightening every naive GPU
render with a visible emitter and *worsening* pkg156's bounce-2 residual
rather than fixing it. Gated on `enableNEE` (NEE path byte-unchanged, pkg120's
own gates re-verified green); restores depth-4 SSIM 0.9955, matching the CPU
oracle and the pre-pkg120 wavefront. Gate honestly **kept at 0.995, not
re-pinned to 0.998** â€” the remaining ~1.4% is the RGBâ†’spectral upsampling
parity gap (channel-asymmetric even under a neutral background, the same
mechanism as pkg153's R-drift), BLOCKED-ON pkg168. Independent HW re-verify
PASS: SSIM 0.99549, bit-identity exact, C2 residuals <7.5e-08, visual clean.
Lesson recorded in pkg120's spec: "mirror the CONDITION, not just the term."
**PR #539:** **pkg168 Step 1** done â€” a unit-level CPUâ†”GPU RGBâ†’spectral
upsampler A/B (new underscore debug probes, pkg54d pattern, zero production
callers) returns verdict **TABLES CLEAN**: band-integrated ratios
1.000000â€“1.000004, mean relative error 2e-6, exonerating the LUTs. pkg156's
~1.4% residual is therefore **call-structure, not table content**; Step 2
(per-bounce snapshot harness to localize the bounce-2 onset) is dispatched
separately, and pkg156's 0.998 gate restoration remains blocked on it. Also
this cycle: the pkg169 fork verdict assigned pkg167 the R=1.0/ior1.5
quarantined cell, and filed **pkg170** (new spec â€” GPU opaque Disney
closure-recombination gain, ~2Ã—, HIGH priority: metallic=0/transmission=0 is
the *default* Disney material class, a wider blast radius than pkg169's
transmission-only bug). **PR #540:** **pkg169** done â€” both convictions
fixed CPU+GPU. Conviction A (CPU): delta glass dropped the Fresnel common
factor R/T (PBRT-v4 Â§9.5), and rough transmission omitted the incident
cosine |NÂ·wi| (Heitz 2018 VNDF); furnace R=0 1.784â†’0.990, R=0.1 1.099â†’0.993.
Conviction B (GPU): the closure-graph reflection-pdf used
`sign(normalÂ·wo)` instead of `rec.frontFace` for the exit-side Fresnel,
making internal-reflection pdf up to ~20Ã— too small; furnace R=1.0
2.296â†’0.930. Furnace after fix (ior 1.5): CPU
0.990/0.990/0.993/0.980/0.926/0.902, GPU 0.992/0.992/0.992/0.986/0.970/0.930;
ior 1.33 both legs 0.98â€“0.99. RTX HW verification PASS, with clean glass
visuals CPU+GPU at three roughnesses and a genuine caustic verified present.
pkg166's 3 xfails removed and confirmed clean under `--runxfail`; one
residual cell (CPU ior1.5 R=1.0 â‰ˆ0.90, multi-scatter) quarantined forward to
pkg167 per architect verdict. Pre-existing non-target finding surfaced during
verification: `light_tracer_caustic` (pkg106) is a CPU-only integrator with
no GPU guard and renders silently near-black if forced onto GPU â€” filed by
the architect as **pkg171** (`78218f6`, general CPU-only-integrator/GPU
guard, backlog tier). **PR #542:** **pkg170** done â€” the ~2Ã— energy gain on
**every** opaque Disney GPU material (metallic=0/transmission=0, the default
class) is fixed: `eval` had summed raw lobe weights while the `pdf` summed
normalized selection weights; fix weights each lobe by `wáµ¢/W` (Veach
one-sample MIS). Confirmed by lobe-count arithmetic (metallic sweep: 2 lobes
1.975, 1 lobe 0.988, the difference exactly the extra lobe). Furnace
1.975â†’0.979â€“0.987, all in `[0.92,1.03]`; CPU control and neighbours
byte-unchanged; ships new GPU opaque-Disney furnace coverage closing the gap
that let this survive undetected. RTX HW PASS bound to the exact head,
visuals clean. **pkg168** Step 1 (tables exonerated) landed via PR #539;
**Step 2 fixed the call-structure bug** it forked to (GPU diffuse shaded
`upsample(albedoÂ·cosÎ¸/Ï€)` vs CPU's `upsample(albedo)Â·cosÎ¸/Ï€`; saturated
diffuse divergence up to 2.5%/channel, post-fix <0.02%). Architect
adjudication moved pkg156's 0.998 restoration OFF pkg168's definition of
done: the decomposition exposed a third, triangle-geometry mechanism now
tracked through **pkg172 â†’ pkg173** (below).

**pkg172 final scope (PRs #543/#544, `11e3f6f`/`c1d0cbe`).** The original
"triangle-specific" premise is FALSIFIED. Of the two-effect decomposition,
**(A)** â€” a universal `f/(pdf+1e-3)` epsilon energy loss, ~0.628%/bounce,
confirmed exact via `2Ï€Â·Îµ` arithmetic â€” is CONVICTED and is now pkg172's
**sole remaining scope**; its fix brightens every diffuse render on all
legs and is **DEFERRED to a supervised round** with a coordinated,
architect-signed-off, repo-wide gate re-pin batch (owner action item,
already recorded). **(B)**, the GPU-only residual, is CONVICTED as **(B')**
and TRANSFERRED to new spec **pkg173** (`6261a2c` â€” bounce-1
geometry-sampling parity): with PR #541 present, pkg156's residual is
dominated by bounce-1 escapes, decomposed into a +6% escape-event RATE
difference (BVH continuation-ray visibility) and +5.5%
throughput-per-escape (camera-ray surface distribution) â€” both are
**expectation** mismatches between unbiased legs (RNG streams move
variance, not expectation), hence discrete fixable defects, not noise.
pkg173 now holds pkg156's 0.998 restoration clause, with an evidence-gated
fallback if both scalar parities land and SSIM still falls short. pkg173 is
dispatchable once PR #541 merges (its fix is the floor pkg173 measures
against).

**Process win worth recording:** PR #544's merge caught a **substantive
docs conflict** â€” main's version of the pkg172 diagnosis table was the
*contaminated* one (stale-.pyd data), and the branch's version was
canonical; the pr-merger caught and resolved it correctly rather than
mechanically taking "ours."

**#541 final resolution â€” UPDATE 2026-08-06: MERGED as `bbf2d8c` (option A,
temp ceiling raise; pkg174 owns the revert). The paragraph below is the
2026-08-02 state, kept for history.** A controlled A/B first
convicted its implementation of a 1.6Ã— wavefront perf regression (main HEAD
0.840s â†’ with #541, 1.370s). The restructure attempt converged on the real
root cause: `stageAdvance`/`stageShade` are register-saturated at 254, and
**any** correct per-hit diffuse-upsample distinction spills ~2KB of stack â€”
the best correct in-kernel form measured 1.222s, still short of the 1.0s
ceiling. Correctness itself is solved and preserved (v4 committed locally on
the branch as `6ef2c11`, unpushed, all correctness gates green) â€” the
blocker is purely the perf ceiling. A 4-way fork (ship+temp-raise the
ceiling / land a register-pressure-reduction package first / permanent
gate re-pin / structural hoist of the distinction out of the hot path) is
documented in PR #541's comment thread; **decision deferred to the owner â€”
the top action item, blocking pkg172(A), pkg173, and pkg168's closeout.**

**Architect round-close refresh (`f64610d`):** `NEXT_STAGE_REPORT.md` Â§2/Â§3
requeued for the correctness cascade (in order: #541 resolution, pkg172(A)
supervised, pkg173, pkg167, pkg165, pkg129-narrowed) and five newly-earned
rules recorded. *(Superseded by the 2026-08-03 owner directive â€” Integration
Milestone before Pillar-3 closure â€” and the 2026-08-06/07 restructure; see
the top section and ROADMAP.md "Current sequencing".)*

**Infra note (owner/infra):** two worktrees tonight carried a stale
`CMAKE_CUDA_ARCHITECTURES=52` CMakeCache (repo specifies `75;86;89`) â€” a
systemic worktree build-seeding issue. Verifiers now check this manually
(recorded in memory); `build_cuda_worktree.bat` should validate/purge the
cache automatically.

**2026-07-26 (round closeout, overnight 2026-07-25 â†’ day 2026-07-26): 6 PRs
merged (#525â€“#530), no open PRs at closeout.** First full round entirely
downstream of pkg55 Phase C's finale (PR #524, 2026-07-25 â€” both megakernels
deleted, the wavefront is now the only GPU path): every package this round
either restores a GPU capability the megakernel deletion silently dropped, or
fixes a defect the wavefront-only world finally made visible/gate-able.
Landed: **pkg88-B** object motion blur addon bake (PR #525, `c41d7fb`) â€” also
fixed a PRE-EXISTING pkg88-A blocker that made camera motion blur fail
outright in real Blender since it shipped (`clear()` wiped the camera before
`set_camera_motion_blur()` ran); **pkg157** firefly clamps ported into the
wavefront (PR #526, `b6c3ffb`) â€” cross-binary no-op measured at 2.48e-07
relative to peak, ~40Ã— inside the 1e-5 convention; **pkg160** plain-`metal`
GPU/CPU parity (PR #527, `2d5bb27`) â€” **plain `metal` was creating energy**
(white-furnace linear up to 1.77Ã—, 66% of pixels > 1.0), fixed by replacing an
invented additive multiscatter term with the same Kulla & Conty compensation
`disney.cpp` already shipped, plus the plain-metal parity gate that never
existed; **pkg162** the last phantom `launchStageInit` overload closed (PR
#528, `05b6b49`) â€” 4 of 4 phantom-overload instances now fixed, no dedicated
spec (small follow-up ticket from pkg157's HW verification); **pkg159** GPU
cryptomatte restored in the wavefront (PR #529, `78e0ae4`) â€” cross-path IoU
0.964â€“0.984 vs a 0.85 threshold; **pkg161** firefly-bearing gate scene (PR
#530, `1393b13`) â€” `firefly_window` measures **22.85Ã—** peak/p99.9 tail vs a
â‰¥10Ã— target, un-skips pkg157's suppression gate. Two investigations closed
deliberately without shipping code: **pkg155 Phase 1** confirmed the ~5% GPU
absolute slowdown is really ~5Ã— on the corrected metric (total GPU
kernel-ms/render) and convicted the shade stage (221 regs/thread, 1
block/SM, recovery target â‰¤128); the **sm_120 build-config lever was RULED
OUT with numbers** (native AOT is 1.68â€“1.80Ã— SLOWER than sm_89 JIT â€” the
register problem is intrinsic to the kernel, not a build artifact). Full
detail: `.astroray_plan/docs/standup/2026-07-25-overnight.md`,
`.astroray_plan/docs/standup/2026-07-26-dayrun.md`; round-closeout section
below.

**2026-07-25 (supervised day session): pkg55 COMPLETE â€” Session C7 landed.**
Both megakernels (`src/gpu/path_trace_kernel.cu`,
`src/gpu/multiwavelength_kernel.cu`) are DELETED; the wavefront is the only
GPU render path (every GPU integrator name routes to
`cuda_wavefront_render`; restir-di keeps its dedicated wavefront driver).
Dedicated lights joined wavefront NEE (pkg89 follow-up â€” dedicated-only
scenes rendered BLACK on the wavefront before; now WF/CPU 0.997). GPU
cryptomatte accumulation is an intentional Phase-C drop (CPU cryptomatte is
the supported path); camera-MB GPU (pkg88-A) and SMS-GPU spectral (pkg64,
xfail) are PORT-later follow-ups. Perf: the spec's "â‰¥2Ã— vs Phase-A baseline"
was rescoped by the owner â€” the Phase-A comparator is dead (the megakernel
itself got ~5.7Ã—/launch slower 2026-05â†’07, regs 125â†’188; investigation =
pkg155) â€” final live record 1.48â€“1.54Ã— (median-of-5, pinned in
`benchmarks/wavefront/megakernel_final_2026-07-25.json`), rescoped floor
â‰¥1.40Ã— MET. The overnight 0.90Ã— perf reading was convicted as a
single-sample-harness artifact (pkg153 partial disposition); the three
R-drift ratio gates remain red and pkg153-owned (quarantine). Evidence:
`.astroray_plan/docs/pkg55-c7-day-arc-2026-07-25.md`.

**In progress â€” overnight 2026-07-24 (running, not yet closed out):** see
`.astroray_plan/docs/standup/2026-07-24-overnight.md` for live status.
Overnight 2026-07-23 closed with 5 PRs landed: pkg145 diffuse-under-specular
energy coupling (PR #513, energy-grid worst case 1.20 â†’ 1.004, HW PASS),
pkg146 equal-wattage oracle reconciliation (PR #514, doc-only), pkg144
direct/indirect firefly clamp split (PR #515, HW PASS), pkg138 rough
dielectric reflection lobe in Disney `eval()` (PR #517, partial-scope
adjudicated, HW PASS), pkg148 default-integrator empty-string fix (PR #516,
HW PASS). Worktrees for all five (`Astroray-pkg145/144/138/146/148`) GC'd;
`Astroray-pkg122` kept for oracle evidence, `Astroray-pkg149` kept (holds
unpushed commit `670e583`). The 2026-07-25 tracker-drift audit (`07ac576`)
normalized 30 spec Status labels and identified pkg55-C7 as the next
supervised-day-session item. Overnight 2026-07-24 landed pkg141 GPU
Disney-metal closure routing fix (PR #518, HW nominal-FAIL/adjudicated â€”
failing gates are pre-existing main regressions now owned by pkg153);
pkg151/pkg147 open, HELD by pr-merger for owner approval on CMakeLists
touches. Full round closeout pending.

**Last updated:** 2026-07-20 (Overnight autonomous run on the travel laptop â€” RTX 3000 Ada sm_89, CUDA 13.2, no OptiX SDK. **pkg55 Phase C Sessions C3+C4 landed** (PR #486 non-visible-band + naive-MW wavefront; PR #490 TLAS/instancing + deformation-motion in the wavefront) and **C5 is open-verified** (PR #494 photon caustics, 2/2 gates + 40-test regression green on RTX, not yet merged) â€” Phase C is now 5 of 7 sessions done/verified. **pkg89 GAP-1 landed** (PR #489 â€” dedicated lights uploaded to GPU, Blender-lamp scenes stop rendering DARK on GPU: AREA 0.998 / POINT 0.997 parity) with **GAP-2 energy audit** escalated to pkg122. **pkg121 Phase A** chiÂ² sampler harness (PR #485 â€” Mitsuba BSD-3 port; Lambertian anchor passes p=0.23; Disney spec-lobe failures xfail'd â†’ pkg123). **pkg119-A** Blender parity coverage matrix (PR #487 â€” v4 AST-scanned: 131 SUPPORTED / 23 APPROXIMATED / 370 DROPPED-SILENT / 20 stale sockets of 524). 15 new specs filed (pkg123-137) covering correctness/sampling + eight platform techniques + material candidates. Direct-to-main: root-shadow-pyd trap killed (94ae956), permissions allowlist (1efe9bc), pkg115-harness CUDA-13 fix (3778f37), other-engines research sweep (7a4c970).).

## Round closeout 2026-08-13 â†’ 2026-08-14 â€” viewport navigation interactive (3.1x), spectral node system fully complete, GPU denoise-guide AOVs + world-volume fog + procedural textures, camera overlay pixel-exact

**8 PRs merged (#605â€“#612), no open PRs at closeout.** See the top-of-file
summary for the full headline; this section is the archival record.

### pkg192 â€” viewport navigation interactivity, Suspect A (PR #605, 2026-08-13)

Camera-only orbit/pan/zoom frames route `view_draw` through
`render(skip_upload=True)`, skipping the ~48ms per-frame CPU BVH rebuild
(`buildAcceleration`) that a diagnosis-first profile isolated as the
dominant, resolution-independent cost. GPU 100k-tri 1280x720 min-of-N:
render 103.98â†’54.68ms, frame 167.54â†’118.45ms, **5.97â†’8.44 fps (+41%)**. The
residual ~27ms wavefront `buildSceneArrays`/upload floor (unconditional,
untouched by the flag) and reduced-res navigation (Suspect B) deferred to a
follow-up â€” landed this same round as pkg196, below.

### pkg196 â€” reduced-resolution viewport navigation, Suspect B (PR #609, 2026-08-13)

Layers Cycles-style reduced-res navigation onto the pkg192 camera-only path:
while the camera moves, `view_draw` renders at `region/N Ã— region/N` and
upscales (bilinear) for display; a settle window snaps back to full res and
hands off to pkg191's progressive still-frame loop. Divisor **N=2** chosen
by measurement (matches Cycles' default; N=4 saved ~10 more fps but was
visibly blocky). Measured orbit fps (same pkg192 harness/scene, min-of-N):
**8.36â†’18.52 fps p50 (2.2x)** â€” combined with pkg192, **5.97â†’18.52 fps
(3.1x)** overall. Settled full-res path byte-identical to pre-change
(guarded test); pkg191's progressive accumulation untouched.

### pkg193 â€” camera-view overlay alignment (PR #607, 2026-08-13)

Fixes the owner's "camera-view overlays don't line up with the preview
render" report. Two bugs in `blender_addon/__init__.py::_apply_camera`: (1)
the viewport path read the wrong `window_matrix` cells for the off-center-
frustum principal-point shift (lens shift + pan/zoom + sensor-fit) â€” fixed
by inverting OpenGL `perspective_m4` directly; (2) the F12 datablock path
passed raw `shift_x/shift_y` without Blender's film-fit `viewfac` scaling
(cites Cycles `blender_camera_viewplane`, Apache-2.0). Measured against real
Blender 5.1 `window_matrix` captures: worst-case corner offset **223.43px
(viewport) / 42.00px (F12) â†’ 0.00px** across 8 conditions (base/aspect/
lens-shift/pan/zoom/sensor-fit/combo), 17-case regression gate. Pure-Python
addon fix â€” no `.cu/.cpp/.h` touched, no `.pyd` rebuild, CI-gate only.

### pkg194 â€” Principled tinted-layer spectral-carry + thin-wall per-Î» (PR #606, 2026-08-13)

Carries both pkg188 Finding-C descopes. **Probe-first**: the register-gate
probe (`stageShadeBucketedKernel<HasPrincipled,...>`, 16 specializations)
decided the GPU restructure was allowed â€” `<false>` (non-Principled)
byte-identical to main, `<true>` STACK +1192B with REG still capped at
254 â€” so both items shipped CPU+GPU. Item 1: `assembleLobes` now carries a
running per-Î» layering weight, upsampling each chromatic factor separately
(`upsample(a)Â·upsample(b)`, never `upsample(aÂ·b)`); band error on pkg188's
tint-over-base cases: **72.46%â†’0.00%**, 34.93%â†’0.00%, 20.14%â†’0.00%,
5.36%â†’0.00%. Item 2: thin-wall R'/T' now per-Î» native instead of RGB-
upsampled (`base(Î»)^(-1/cosÎ¸t)` is nonlinear in base). CPUâ†”GPU render
parity mean-ratios in [0.9989, 1.0021] across both items.

### pkg197 â€” GPU wavefront denoise-guide AOVs (PR #608, 2026-08-13)

The GPU render path produced only the beauty buffer â€” albedo/normal/depth
stayed zero, so OIDN/OptiX ran guide-less and Blender's Denoising Data
passes were empty on GPU. Captured at the wavefront **intersect stage**
(bounce-0, sample-0), so the register-saturated shade kernel is untouched
(byte-identical REG:254/STACK:3352/CONSTANT[0]:1700). CPUâ†”GPU parity:
albedo mean-ratio in [0.92,1.09], depth in [0.97,1.03], normal cosine
0.9998. Denoise A/B on an 8spp GPU render: guided edge-MSE 0.001491 vs
guideless 0.001621, **+8.0% improvement**. Beyond the literal spec (flagged
and reviewed): also wired `applyPasses`/OIDN/OptiX/cryptomatte into the GPU
render route for the first time â€” GPU renders now actually denoise, not
just carry guide buffers nobody consumed.

### pkg199 Stage 1 â€” GPU wavefront homogeneous world-volume absorption (PR #611, 2026-08-14)

**Spec-premise correction (git-archaeology, before implementation):** the
original spec claimed the CPU had a working HG-in-scatter world volume to
port "exactly." False â€” there was no HG phase, in-scatter, distance
sampling, or NEE-through-medium anywhere in git history; the only volume
code (`worldTransmittance`, Beer-Lambert absorption) had been dead since
pkg14 deleted the legacy RGB integrator that called it. Spec rewritten into
Stage 1 (this PR) + Stage 2 (spec-only, XL). **Ships:** per-Î» Beer-Lambert
absorption `exp(-Ïƒ_t[Î»]Â·d)` on GPU wavefront (intersect + shadow kernels
only â€” shade kernel byte-identical by construction) AND re-wires the same
absorption into the CPU spectral tracer (completing the orphaned pkg14
feature). Analytic furnace Tr vs `exp(-ÏƒÂ·d)` matches to **<2e-4**. **hw-611
HW FAIL â†’ FIX â†’ HW PASS:** the sphere-light NEE leg used a 1e30 occlusion
sentinel as the Beer-Lambert path length instead of the true geometric NEE
distance, saturating fog renders to black; fixed (commit 6e7bf6d), all 5
verification steps re-confirmed PASS on re-check. Stage 2 (full HG
scattering medium, CPU-first, XL) filed spec-only, open â€” the caustic
integrator and CPU wavefront reference explicitly do not carry world-volume
absorption even in Stage 1 (documented non-goal, candidate follow-up).

### pkg190 â€” GPU procedural texture support (PR #612, 2026-08-14)

Closes the pkg119-B flat-albedo drop for procedural texture nodes
(checker/brick/magic/wave) via 3D-voxel bake-at-upload (Generated-
coordinate 3D fields, reusing the cited CPU evaluators). **Mandated
re-baseline first surfaced a stale premise:** the historical "5 residual
TRANSLATION-BUGs" story was false; fresh pkg119-B (Blender 5.2, OpenMP-off,
res64/spp16) found the real set was 4 nodes, all fixed here â€” **TRANSLATION-
BUG 4â†’0, summary 25â†’30 pass** (TEX_CHECKER 0.8425â†’0.9512, TEX_BRICK
0.8980â†’0.9158, TEX_MAGIC 0.8358â†’0.9639, TEX_WAVE 0.8935â†’0.9575). Register
fleet gate: all 16 `stageShadeBucketedKernel` specializations byte-identical
before/after (only the `HasTexture` branch changed). **hw-612 HW FAIL â†’
FIX â†’ HW PASS:** `scripts/run_parity.py`'s scene-routing guard didn't
recognize the new `textured_plane` scene (silently fell through to a no-op
leg) and its EXR reader (`imageio.v3`) truncated to uint8, zeroing the
green channel and nan-poisoning the ratio; both fixed (commit b2b42eb),
re-verified CPU/GPU mean-ratio **1.0000/0.9996/0.9998** â€” an exact match to
the verifier's own independent bypass measurement from the first session.

### pkg195 Stage C â€” spectral node system remainder; pkg195 now FULLY COMPLETE (PR #610, 2026-08-13)

All 7 spec items: `astroray.register_spectral_profile` (pointer-stable
deque storage â€” materials cache raw `SpectralProfile*` across a render);
Drawn Spectrum node (hidden `ShaderNodeFloatCurve`, the owner's headline
"draw exactly which wavelengths" control); Spectrum Preset node (two-tier
categoryâ†’preset, routes through the same Replace path as the old node for
.blend compat); Blackbody Spectrum node + bake-to-profile operator (Planck
at 5nm); in-band Replace mode (`ProfileMode::{ExtendOnly,Replace}` â€”
Replace bypasses the Jakob-Hanika RGB round trip entirely, routes visible-
band CPU renders to the multiwavelength integrator); IR/UV Response node
de-fanged (constant-band ExtendOnly profile, destructive grey-Disney
promotion deleted, visible render byte-identical); Sellmeier manual B/C
read again in `dielectric.cpp` (silently dropped since pkg57). Gate C all
green: drawn 550nm bump G=0.4396>R=0.2642>B=0.0003 on headless Blender 5.1;
manual BK7 vs preset prism dispersion 6.350px vs 6.350px (0.00%); 16/16
Stage A/B + GPU-parity gates unchanged (`enable_nee` contract intact; GPU
Replace-mode degradation is documented, not regressed). **pkg195 is now
DONE across all three stages (A, B, C).**

### Specs filed this round, not yet fully landed

**pkg198** (filed alongside pkg196/197/199 as the same PR's GPU-parity
vetted set) â€” GPU wavefront light-path AOV passes, register-hostile,
explicitly **probe-first, may park**. Remains OPEN.

### Cross-cutting: two HW FAIL â†’ fix â†’ PASS cycles this round

**pkg199 (hw-611):** a 1e30 occlusion sentinel used as the Beer-Lambert
NEE path length saturated fog to black under a sphere light â€” fixed to the
true geometric NEE distance, re-verified PASS. **pkg190 (hw-612):** the new
`textured_plane` parity scene wasn't recognized by `run_parity.py`'s
routing guard (silent no-op leg) and its EXR reader zeroed the green
channel via an unconfigured `imageio` plugin â€” both fixed in one commit,
re-verified PASS with an exact match to the verifier's own independent
bypass measurement. Both fixes shipped same-day as the original PR before
merge; neither package needed a second PR.

### pkg119-B reclassification (surfaced by pkg190)

The long-standing "5 residual TRANSLATION-BUGs" figure was stale/false. A
fresh re-baseline (current main, OpenMP-off `build_blender_addon_cuda`,
Blender 5.2, res64/spp16) found `BSDF_TRANSPARENT` and `world:World` now
PASS (confirming an earlier SSIM-false-positive disproof) and the real set
was **4 nodes, all procedural textures**, all fixed by pkg190. pkg119-B
summary is now **30 pass**, TRANSLATION-BUG **0**.

### Open follow-ups (not closed, tracked forward, do not re-derive)

pkg198 (GPU light-path AOV passes, probe-first), pkg199 Stage 2 (full
scattering medium, XL, CPU-first), pkg131 (zero-knob adaptive sampling,
wavefront leg), the pkg176-line deep per-setting F12 pixel-honour matrix
(deferred, no dedicated spec), the caustic-integrator/CPU-wavefront-
reference world-volume gap pkg199 documented as a Stage-1 non-goal (fog is
invisible to the caustic integrator), the legacy non-dedicated
`add_sun_light` GPU-dimness finding from the pkg194 review (not yet
diagnosed or filed), and an Object-coordinate-mode guard for the pkg190
procedural bake (Generated-space only per spec scope; Object-coordinate
procedural textures have no explicit GPU guard/fallback).

## Round closeout 2026-08-12 â†’ 2026-08-13 â€” GPU capability restoration (textures, viewport progressive refinement) + Principled spectral correctness (conductor thin-film, dispersion, transmission separation) + build-integrity guard; HEADLINE FINDING: NIR/UV lamp-lit renders are black end-to-end

**15 PRs merged (#585â€“#599), no open PRs at closeout.** See the top-of-file
summary for the full headline; this section is the archival record.

### pkg183 â€” stale-object ABI-mixed-binary build-integrity guard (PR #592, 2026-08-12)

Header-hash stamp + force-clean-on-mismatch, a <5s host-only ABI canary, and
a cuobjdump ground-truth CUDA-arch gate wired into all three build wrappers
(exit codes 6/7). The arch gate is the direct guard against the fleet-wide
stale `CMAKE_CUDA_ARCHITECTURES=52` CMakeCache incident this same round
surfaced (see cross-cutting note below). Item 4 (move build trees off
OneDrive) evaluated-only, deferred to a separate package.

### pkg185 â€” GPU glass-caustic parity gate CLOSED by test-scene fix (PR #589, 2026-08-12)

The gate's SSIM 0.0101 failure was diagnosed to the reference sun light
being un-Î©-scaled, driving test-scene irradiance to ~19100 and collapsing
SSIM on 3 legitimate specular fireflies. Corrected the test scene, not the
engine: SSIM 0.0101â†’0.9606, GPU peak 1007â†’0.41. GPU transport confirmed
healthy throughout.

### pkg186 â€” GPU image-texture sampling, first GPU texture support (PR #590, 2026-08-12)

Baked buffer + nearest fetch, `__constant__ c_wfTexBinding`. A verifier
caught a +24B kernel-signature regression mid-review, fixed back to exact
kernel identity (REG:254/STACK:3608/CONSTANT:1700). Backend-aware
`__gpu_features__` dict added so the addon Diagnostics panel stops
overclaiming GPU textures/volumes/adaptive/GR support it doesn't have.

### pkg182 follow-up â€” per-Î»-native Principled conductor thin-film (PR #586, 2026-08-11)

Supersedes the RGB-upsample conductor-thin-film approximation with a
per-Î»-native Airy evaluation on both CPU and GPU (Belcour-Barla + Gulbrandsen
NK inversion, cited). 17/17 gates HW-verified, `<false>`/`<true>` STACK
unchanged. Measured finding: saturation barely moved (mean 0.0488â†’0.0499,
max 0.1842â†’0.2045) â€” the premise that RGB-upsample visibly mutes metal
iridescence does not hold in the 4-sample hero-wavelength pipeline; this
lands as a correctness/consistency win (no JH round-trip loss, correct
under spectral/colored illumination), not the saturation jump the ticket
implied.

### pkg187 â€” Principled BSDF dispersion, CPU-complete + GPU-wired (PR #593, 2026-08-12)

OpenPBR/Cycles-WIP two-term Cauchy fit `n(Î»)=A+B/Î»Â²` from d-line IOR +
Abbe number (cited). CPU chromatic prism spread 4.267â†’5.345px,
zero-dispersion bit-identical, `<false>` shade kernel byte-identical to
main at TRUE sm_120. GPU leg wired into the existing hero-collapse
dispersion infra but gated on the pre-existing pkg189 no-op â€” filed as a
follow-up spec the same day. Two premise corrections surfaced during
implementation: no shipped Blender exposes a Dispersion socket (unmerged
upstream WIP #162041; addon ships a forward-compatible probe instead), and
`test_gpu_prism_rainbow_parity`'s XPASS under `--runxfail` was vacuous (no
real GPU render ran) â€” xfail retained, not un-xfailed.

### pkg184 â€” `template<bool HasPhotons>` shade-kernel isolation (PR #597, 2026-08-12)

Isolates the photon-caustic k-NN gather into 8 kernel instantiations:
every HasPhotons=false variant strictly below the pre-change baseline
(STACK âˆ’128 to âˆ’256B across `<F,F>/<F,T>/<T,F>/<T,T>`), HasPhotons=true
variants byte-identical. Non-photon glass-sphere shade kernel measured
âˆ’2.3% wall time vs a +0.1% byte-identical control â€” a real perf win, not
noise.

### pkg191 â€” GPU viewport progressive refinement (PR #598, 2026-08-12)

Root cause: the GPU dispatch path ignored the engine's `renderSeed==0` â†’
fresh-random-per-call contract (memory `seed-zero-is-random-sentinel`), so
every viewport refinement chunk rendered with IDENTICAL noise instead of
accumulating new samples. One-spot fix in `blender_module.cpp`;
MSE-to-256spp-reference improved 7.0e-4â†’1.3e-5 across refinement
iterations, HW-verified.

### pkg188 â€” Principled film-off transmission colour/scalar separation (PR #599, 2026-08-12)

Retires the "Stage-3b upsample hack" CPU+GPU: transmission colour and
transmission scalar are now upsampled and applied separately instead of as
a pre-multiplied product, plus a weight-path clamp guard. Findings A+B
landed; Finding C descoped to new spec **pkg194** with a QUANTIFIED
residual â€” `upsample(aÂ·b)` vs `upsample(a)Â·upsample(b)` diverges up to
~72% band error on a coloured-tint-over-dark-base material (0% for the
common white-tint case) â€” raising pkg194's priority.

### pkg175 â€” drift-gate fix: flipped to done (PR #547, 2026-08-07)

Spec status had stayed "in review (PR pending)" past its own 2026-08-07
merge. One-command Blender dev loop (build â†’ package â†’ install â†’ launch â†’
headless smoke-render); 150s full rebuild / 5.8s `-SkipBuild`, on-hardware
smoke `RESULT PASS` (already recorded verified in ROADMAP.md's Integration
Milestone section).

### Cross-cutting: fleet-wide stale CUDA-arch CMakeCache incident

Every local `build_cuda/` tree carried a cached
`CMAKE_CUDA_ARCHITECTURES=52` (stale Maxwell PTX) alongside the intended
`ASTRORAY_CUDA_ARCHS=native`/`120`; CMakeLists' non-cache `set()` shadows it
at configure time so the actually-compiled kernels were correct sm_120 SASS
all along, but `cuobjdump` reads against the cache-line arch produced
phantom resource-gate numbers (worktree STACK 2640 vs the true sm_120
`<false>` baseline of STACK 3608) â€” this false reading was caught and
corrected mid-round on both pkg183's and pkg187's measurements. **pkg183**
now ships an automatic artifact-ground-truth gate against this class going
forward. The root cause itself (CMakeLists non-cache `set()`,
`configure_and_build.bat` not passing `ASTRORAY_CUDA_ARCHS`, and
`build_blender_addon.py`'s hardcoded arch/Debug revert) is intentionally
out of pkg183's wrapper-only scope â€” queued as a separate infra follow-up
PR.

### Specs filed this round, not yet implemented

**pkg189** (PR #591, 2026-08-12) â€” GPU wavefront dispersion enablement: the
hero-Î» refraction path is a pre-existing no-op end-to-end for both the
dielectric reference and pkg187's Principled dispersion; discovered during
pkg187. **Next up.**
**pkg190** (PR #594, 2026-08-12) â€” GPU procedural-texture support (pkg186
slice 2), requires a pkg119-B re-baseline first.
**pkg192/pkg193** (PR #595, 2026-08-12) â€” viewport-addon diagnosis-first
specs from owner hands-on feedback: pkg192 viewport navigation
interactivity (3â€“5 fps vs Cycles ~30 fps), pkg193 camera-view overlay
misalignment. (pkg191, filed in the same PR, landed this round â€” see
above.)
**pkg194** (filed via PR #599 as the pkg188 Finding-C descope) â€” Principled
tinted-layer spectral carry + thin-wall per-Î»; priority raised by the 72%
band-error finding.
**pkg195** (PR #596, 2026-08-12) â€” spectral node-system design doc + Phase 1
spec, from an owner-directed Fable design session. **HEADLINE ENGINE
FINDING:** `multiwavelength_path_tracer` has NO light sampling â€” every
lamp-lit NIR/UV render is black. The profile-selector node is a
visible-band no-op; the IR/UV response node is destructive. Sodium/mercury
lamp SPDs are already engine-ready, just not exposed. A drawn-spectrum node
is identified as a genuine differentiator (no other renderer has one).

### Infra, not tied to a package

`.gitattributes` forces CRLF checkout for `.bat`/`.cmd` (PR #585) â€”
prevents the silent cmd.exe mis-parse class this repo has hit before
(memory `bat-files-need-crlf`). Comprehensive repo hygiene sweep (PR #587,
pre-session, 2026-08-11) â€” dead code/scripts/tests/docs removal, tcnn
opt-in, guardrails; filed pkg183/184/185 (all landed this round, above).

### Owner decisions and process notes (2026-08-12)

Wavefront perf ceiling STAYS at 1.5s (ratified, improve opportunistically
â€” no revert dispatch). Overnight autonomous run authorized. Owner
hands-on addon feedback drove pkg191-193 and the spectral-node design
(pkg195). Every code PR this round was dual-gated (CI + independent RTX
hardware verification); three hardware verifiers were serialized through
the GPU lock overnight.

### Open follow-ups (not closed, tracked forward, do not re-derive)

pkg189 (GPU dispersion enablement â€” next up), pkg190 (GPU procedural
textures), pkg192 (viewport interactivity), pkg193 (camera overlay
alignment), pkg194 (tinted-layer spectral carry â€” priority raised),
pkg195 (spectral node system Phase 1), the infra CUDA-arch root-cause PR
(CMakeLists/`configure_and_build.bat`/`build_blender_addon.py`), the
durable `GLoweredMaterial` by-value-copy fix (still prototyped,
uncommitted, in worktree `.claude/worktrees/sad-maxwell-ff99d1`), and
pkg180 (systemic-dim diagnosis, still open).

## Round closeout 2026-08-08 â†’ 2026-08-10 â€” Principled-BSDF completion run: pkg178 COMPLETE (Stages 0-5, native Cycles Principled incl. thin film/thin wall), pkg172(A) closed, pkg176 COMPLETE (Stages 0-4, Blender native steering wheel), pkg182 filed+fixed, pkg181 done, pkg179 closed by diagnosis

**17 PRs merged (#566â€“#582), no open PRs at closeout.** See the top-of-file
summary for the full headline; this section is the archival record.

### pkg178 â€” native Cycles Principled BSDF, Stages 0â€“5 COMPLETE (PRs #566â€“#581, 2026-08-07 â†’ 2026-08-10)

Core-lobe scaffold + GPU closure-graph twin (#566/#567) â†’ `template<bool
HasPrincipled>` D4 shade-path isolation (#570, permanently closes the
+52% fleet-wide non-principled regression class; non-principled `<false>`
STACK pinned at 3608 B through every subsequent stage) â†’ coat/sheen/
approx-SSS/emission (#571) â†’ CPU UV-aligned tangent plumbing (#572) â†’
height-correlated Smith G2 (#573, Heitz 2014, every furnace gate moved
toward 1.0) â†’ anisotropic GGX + gated GPU UV tangent (#574) â†’ alpha delta
transparent lobe (#575, Fable-proven variance-only reallocation) â†’ Stage 4
thin film + thin wall (Belcour-Barla 2017: shared utility + CPU dielectric
#577, CPU conductor #578, GPU twin #579, thin wall/thin subsurface #580) â†’
Stage 5 Blender native routing incl. thin-film sockets (#581,
`use_native_principled` default ON experimental). CPU+GPU byte-mirrored at
every stage; production default-flip gated on the full hardware parity
matrix per the owner's pre-authorization (memory
`pkg178-repin-and-stage5-autonomy`).

### pkg182 â€” Principled/Disney `ggxReflect` eval-D/pdf-D consistency (PR #582, 2026-08-10)

Surfaced by pkg178 Stage 4 PR-4 (thin glass rendered black at low
roughness); root-caused to a pre-existing regularizer mismatch
(`+1e-4` eval-D vs unregularized pdf-D) in the metallic/specular/aniso
reflect evaluators that also made ordinary Principled metallic/specular
near-black at low roughness (furnace 0.067â†’0.604 at r=0.02). Eval-only
fix, sampler/pdf untouched, register-neutral (`<false>`/`<true>` STACK
unchanged). No spec existed for this defect class before now â€” filed
retroactively as pkg182.

### pkg172 effect (A) â€” CLOSED (PRs #551/#553/#576, 2026-08-07 â†’ 2026-08-10)

The pbrt-v4 guarded-pdf form replaces the biased `f/(pdf+1e-3)` estimator:
CPU path_tracer/wavefront/multiwavelength, 15 sites (#551, closes the
universal 0.628%/bounce = `2Ï€Â·Îµ` loss; clearcoat whole-sphere MSE floor
re-pinned 5e-5â†’3.5e-5 with in-test justification); `neural_cache`/
`restir_di` follow-up legs (#553); the two remaining GPU NEE light-pdf
sites in `stage_advance.cu`/`gpu_nee.cuh` (#576, register-neutral, no
firefly-gate shift). Effect (B) remains pkg173's separate, lower-priority
scope.

### pkg176 â€” Blender native steering wheel, Stages 0â€“4 COMPLETE (PRs #555/#556/#561/#568, 2026-08-08 â†’ 2026-08-09)

Stage 0 mapping table (owner-review artifact) â†’ Stage 1 settings-plumbing
(#555) â†’ Stage 2 native Cycles panel adoption (#556) â†’ Stage 3 world/
light/camera completion + `report_unsupported_native_controls` honesty
guard (#561) â†’ Stage 4 custom-UI retirement (#568, owner-approved
2026-08-09 â€” native Blender/Cycles panels are now the only steering wheel
plus one Astroray-only panel). 45 unit tests + Blender 5.2 real-host
register/headless-smoke PASS throughout.

### pkg181 â€” dedicated-light visibility to BSDF rays (PR #569, 2026-08-08)

Fixed the systemic ~12â€“20% Astroray-vs-Cycles dim and dark lamp
reflections (mirror-lamp 0.017Ã—â†’~1.00Ã— Cycles, AREA floor 0.921Ã—â†’0.985Ã—);
a prerequisite this run's Cycles-parity numbers rest on.

### pkg179 â€” CLOSED by diagnosis, no engine code changed (owner-ratified 2026-08-09)

The "3Ã— dead-sample rate" (pkg167 Part 2's escalation) was a
measurement-methodology mislabel, not a sampler bug or new physics;
owner ratified Option 2 (keep the energy-correct fallback, no fix). The
Cycles combined-closure design consulted during diagnosis is recorded for
pkg178's Principled dielectric, which shipped that design in Stages 3â€“4.

### Open follow-ups (not closed, tracked forward)

- Conductor thin-film per-Î»: metal iridescence uses an RGB-upsample
  approximation (less saturated than Cycles' per-Î»; the dielectric leg is
  per-Î»-exact) â€” documented approximation, enhancement-tier.
- Durable `GLoweredMaterial` by-value-`GMaterial`-copy fix: the recurring
  data-leak class (hit and locally patched by both Stage 3 and PR #579) is
  prototyped in worktree `.claude/worktrees/sad-maxwell-ff99d1`
  (uncommitted, PR-2-based); needs re-apply on settled main.
- Thin-film-vs-Cycles saturation parity verification + the coordinated
  pkg119-B/pkg129 harness band re-pin (reflecting pkg181 + Smith-G +
  pkg172(A) + thin-film + pkg182 together) is still owed.

## Round closeout 2026-07-25 evening â†’ 2026-07-26 â€” wavefront GPU-parity follow-ups: pkg157/pkg159/pkg161 restore dropped features, pkg160 fixes a real energy-conservation bug, pkg88-B completes object motion blur, pkg162 closes the phantom-overload class

**Six PRs merged (#525â€“#530), no open PRs at closeout.** The whole round is
downstream of pkg55 Phase C's finale (PR #524, 2026-07-25 â€” both megakernels
deleted, the wavefront is the only GPU path). Lane discipline: Lane A owned
the wavefront `stage_advance.cu` domain, Lane B the addon `blender_addon/`
domain; the team-lead held the GPU lane directly (subagents on this machine
cannot init vcvars, so cannot build CUDA).

### pkg88-B â€” object motion blur addon bake, + pkg88-A's real-Blender blocker fixed (PR #525, 2026-07-25)

`convert_scene` now hoists shutter-position resolution so object motion
reuses the same `t_start`/`t_end` as pkg88-A; `_get_object_matrices_at_time`
snapshots every mesh-able object's `matrix_world` at both shutter boundaries;
`convert_objects` routes to `add_triangles_bulk_motion` only when the pose
differs between the two boundaries. **Independent review (a different model
from the implementer) found a real correctness bug all 13 of the PR's own
tests passed through:** only `t_end` was ever snapshotted, so
`positions_start` fed the object's *current* pose â€” CENTER shutter swept only
the back half of the arc (34 lit columns vs 55 correct), END disabled object
blur entirely (`_matrices_differ` always False). Fixed at `9f233fe`; measured
streak widths for START/CENTER/END all converge to 49 lit columns with
correctly ordered centres (END 48.0 < CENTER 68.0 < START 89.0). **Then a
real headless-Blender run (not mocked) found a second, pre-existing bug**:
`convert_scene` calls `renderer.clear()` (which wipes the camera) BEFORE
`set_camera_motion_blur()` and `setup_camera()`, so turning on motion blur
raised `RuntimeError: Camera not set up` in real Blender â€” **pkg88-A's camera
motion blur has been broken since it shipped**; no suite caught it because
every motion-blur test mocks `bpy` and stubs `setup_camera`. Fixed inside
#525 (hoist `setup_camera` above the motion-blur block, "ORDER IS
LOAD-BEARING" comment added) since the fix is what makes the deliverable
reachable. `scripts/verify_pkg88b_blender.py` promoted into the repo as a
permanent real-host regression guard (pattern-matched to the pkg114 verify
scripts). 19 new/extended tests + 74 neighbour tests green; independent
re-review reproduced both bugs against the pre-fix code in a scratch tree
before SIGN-OFF.

### pkg157 â€” wavefront firefly clamps restored (PR #526, 2026-07-25)

Ports pkg144's `clampDirect`/`clampIndirect` into the wavefront, which C7's
deletion sweep had silently dropped (defaults are 0/0 = off, so default
renders were unaffected, but any user-set clamp on a GPU render did nothing).
HW verification found **two of the PR's own tests were defective, not the
code**: one used a clamp value (10) the scene's dynamic range (peak 1.758)
could never bind against; the other demanded byte-identity the wavefront
cannot deliver against *itself* (atomic-accumulation ordering, ~1.19e-07
floor). A third test (the firefly-suppression clause) was correctly
`skip`ped rather than xfailed â€” **no scene in the library has a firefly
tail** (peak/p99.9 ranges 1.04â€“1.82Ã— across five scenes; a real firefly
population would read in the tens or hundreds), so no threshold could
satisfy both "clips only outliers" and "removes real signal" â€” filed as
**pkg161** (closed the same round, see below). **Verified cross-binary**
(the only way to test the contract): pre- and post-pkg157 binaries render
the same scene to image sums identical to 6 dp, max diff 2.48e-07 relative
to peak. Bounce classification proven directly: `clampIndirect` is EXACTLY
inert (0.000000) at `max_depth=1`. **HW PASS, 8 passed / 1 documented skip
at merge** (now 12 passed post-pkg161). Along the way, CI's compiler
exposed a **phantom overload** in `gpu_wavefront_state.h` (a declaration no
definition matched, masked by private duplicate re-declarations in 3 TUs) â€”
fixed at the root (header now the single source of truth) for 3 of 4
instances; the 4th (`launchStageInit`, load-bearing default argument) was
deliberately left and closed later as pkg162.

### pkg160 â€” plain `metal` was creating energy, not just too dark (PR #527, 2026-07-25 â†’ 2026-07-26)

Started as a measurement: plain `metal` (not Disney metal) reads 0.28Ã—/7Ã—
darker (mean/median) than CPU on the GPU wavefront â€” `gpu_metal_eval` omits
the multiscatter term `MetalPlugin::eval` adds on CPU. **Step 0 (required by
spec before mirroring anything) found the two GGX energy-compensation table
systems disagree 24.6Ã— in `E` / 1030Ã— in `Fms` at the contact-sheet
roughness â€” and the CPU side is the physically wrong one**:
`GGXEnergyCompensationLUT` estimates `E` with 256 uniform-hemisphere samples,
cannot resolve a narrow GGX lobe, so `E â†’ 0` as roughness â†’ 0 (the opposite
of the truth) and drives `Fms` to 96.5% of its mathematical ceiling exactly
where multiscatter should vanish. **Owner chose "fix the CPU."** Investigating
that surfaced two more defects beyond the wrong table: `multiScatter` carried
no `NdotL` (violates the `eval()` contract), and `msWeight = roughness*(2-
roughness) * 1.3f` is an unpublished hand-tuned fudge factor (CLAUDE.md Â§6
violation). **The fix deletes the runtime LUT's role entirely** and routes
plain metal through the same multiplicative Kulla & Conty compensation
`disney.cpp` has shipped since pkg60 (`ggxCompensationFactor` / shipped
Cycles tables), with `gpu_metal_eval` applying its exact GPU twin. **Measured:
the pre-fix conductor was creating energy** â€” white-furnace linear reads
1.6434 (r=0.15), 1.4069 (r=0.60), 1.7690 (r=0.90); post-fix 0.8823/0.8092/
0.8802. **Why no existing test caught it â€” systemic, not pkg160-specific:**
`render_image()` defaults to `apply_gamma=True`, which clamps to [0,1]; the
same pre-fix furnace read **gamma max exactly 1.000000** while **linear max
was 4.139 with 18,338 of 27,648 pixels above 1.0** â€” a gamma-rendered furnace
test cannot detect energy gain (now recorded in memory
`gamma-furnace-cannot-detect-energy-gain`). The plain-metal GPU/CPU parity
gate that never existed lands in the same PR (mean AND median, `[0.95,
1.05]`). **HW: 31 passed, 1 documented exception** â€” roughness 0.9 channel B
reads 1.0722, isolated to a **pre-existing architectural seam**: CPU computes
compensation per-wavelength, GPU per-RGB-channel-then-upsamples (agree only
for flat spectra); owner-approved asymmetric band `[0.95, 1.10]` at r=0.9
only (2.6% headroom, floor unchanged so a GPU-dim regression still fails).
That seam is filed as **pkg163**, which owns retiring the exception. Also
found: `stage_shade_metal.cu`'s `launchStageShadeMetalGPU` is dead code (no
call site) â€” fixed rather than deleted (cited as a template by pkg55/128/129);
deletion left as an owner call.

### pkg162 â€” the last phantom `launchStageInit` overload (PR #528, 2026-07-26)

The fourth and last instance of pkg157's phantom-overload pattern:
`gpu_wavefront_state.h` declared `launchStageInit` with 6 parameters while
`stage_init.cu`'s definition takes 8; pkg157 deliberately left it because
correcting it means removing a `= 0` default (a defaulted parameter cannot
precede non-defaulted ones) â€” behaviour-affecting, unverifiable without a
build the implementer could not run. Resolution: the default is simply
removed (all 6 call sites already pass `sample_index` explicitly, so it was
never used). No dedicated package spec exists for pkg162 (a small follow-up
ticket, not a filed spec) â€” tracked here and in the standup docs. Verified
inert: full Release+CUDA build succeeds, same scene/seed against the
pre-change binary gives identical image sums, max diff 2.48e-07 relative to
peak â€” the wavefront's own atomic-ordering noise floor. Independent
different-model review supplied a stronger inertness argument (default
arguments are not part of a function's mangled signature, so removing one
cannot change linkage for callers that already pass the argument explicitly).
Closes the phantom-overload class: **4 found, 4 resolved.**

### pkg159 â€” GPU cryptomatte restored in the wavefront (PR #529, 2026-07-26)

GPU cryptomatte accumulation lived only in the now-deleted `path_trace`
megakernel (`multiwavelength_kernel.cu` never had it), so C7 silently made it
CPU-only â€” a real capability regression from #524 that nobody had filed
until this round. Port required care on three axes the spec pinned: the
megakernel was 1 thread/pixel and race-free, the wavefront is not (atomics
now required); the megakernel used an implicit `float=uint32` conversion
instead of `hash_to_float` (IDs never matched the CPU/EXR manifest â€” fixed in
the port); first-hit-only semantics per the CPU oracle. Cites Friedman &
Jones 2015 (Psyop) and Cycles `cryptomatte_passes.h`. **HW: 4 gates passed,
cross-path IoU 0.964â€“0.984 against the 0.85 threshold** â€” the threshold was
the one number never previously exercised cross-path, and it demonstrably
discriminates (GPU leg 0.9743 vs CPU leg 0.9843; a no-op port would read
~0). **Not verified, and recorded as such rather than blurred:** a true
cross-binary RED run (the gate depends on helpers this PR adds, can't run
against main's unported binary) and addon-side pass packing of the GPU
crypto buffers.

### pkg161 â€” firefly-bearing gate scene closes a two-day gate hole (PR #530, 2026-07-26)

Built to un-skip pkg157's firefly-suppression gate: no scene in the library
had a tail heavy enough to demonstrate suppression without either clipping
nothing or clipping real signal. **HW measurement (RTX 5070 Ti, linear
output â€” a gamma-clamped tail measurement destroys exactly the outliers
being measured):** `firefly_window` peak/p99.9 = **22.85Ã—** (target â‰¥10Ã—,
12.6Ã— heavier than the next-worst library scene at 1.82Ã—); `metal_cornell`
negative control **1.07Ã—** (limit â‰¤3.0Ã—, confirms the gate discriminates
rather than passing on anything). 12 gates pass, including the gate that had
been `skip`ped since PR #526. One collection-time bug fixed along the way: a
test named `firefly.EMITTER_RADIUS` as a default argument, which evaluates
at *def* time â€” before `pytestmark = skipif(not AVAILABLE)` can suppress
anything â€” so the module failed to collect on any checkout without a build
(exactly the environment every implementer works in).

### Investigations closed, no code shipped (by design)

- **pkg155 Phase 1 COMPLETE** â€” the ~5Ã— GPU absolute slowdown confirmed on a
  corrected metric (total GPU kernel-ms/render; the spec's old ms-per-launch
  headline died when #524 deleted the kernel). cornell_diffuse 20.29â†’98.25 ms
  (4.84Ã—), cornell_glass 21.87â†’122.69 ms (5.61Ã—) vs the 2026-05-17 Phase-A
  baseline. **Shade stage convicted**: 43.8â€“52.4% of GPU time, 221
  regs/thread, the only stage at 1 block/SM (needs â‰¤128 to reach 2). Doc:
  `.astroray_plan/docs/pkg155-phase1-profile-findings.md`.
- **pkg155 build-config lever RULED OUT with numbers** â€” adding native
  sm_120 AOT is **1.68â€“1.80Ã— SLOWER** than the current sm_89-JIT build
  (identical source, only `CMAKE_CUDA_ARCHITECTURES` differing;
  `shade_bucketed` 239â†’604 ms at 221â†’229 regs). So `75;86;89` is optimal
  here and the register problem is intrinsic to the kernel, not a build
  artifact. Doc: `.astroray_plan/docs/pkg155-sm120-negative-result.md`.
- **pkg153/pkg155 Phase 2 protocol corrected** â€” the "compile-only bisect"
  premise is dead (`-Xptxas -v` counts are meaningless under `-rdc=true`:
  127/40 static vs 221/229 real). The bisect needs the GPU at every point and
  cannot parallelise with HW verification; re-scoped to an opportunistic
  gap-filler, always outranked by active-PR HW gates.

### Specs filed / re-scoped this round

**pkg159** (filed and shipped same round), **pkg160** (filed and shipped),
**pkg161** (filed and shipped), **pkg163** (spectral-vs-RGB compensation
colour-space parity â€” metal-only defect, but the RGBâ†’spectral seam it sits on
is not metal-only; owned retiring pkg160's r=0.9 band exception; **shipped
2026-08-02, PR #533**), **pkg158 narrowed** (not closed â€” its Step-0
Disney-metal reconciliation still must run, but on a post-pkg160 SHA, since
pkg160 changed the shared metal energy-compensation baseline), **pkg120** +
**pkg88 Phases B/D** unblocked (stale "blocked on pkg55 Phase C" markers
cleared â€” the blocker dissolved with #524).

### Owner decisions this round

- **pkg160 direction: fix the CPU, not mirror the GPU to it** â€” the owner's
  call reframed a "GPU too dark" ticket into a real energy-conservation bug
  fix, once Step 0 showed the CPU table was the physically wrong side.
- **pkg160 HW exception: asymmetric band `[0.95, 1.10]` at roughness 0.9
  only** â€” not an xfail (would hide future regressions there) and not a
  global widening; self-retiring via pkg163.
- **Still open for owner decision:** tightening the GPU/CPU parity bands
  project-wide (current bands as loose as `[0.4, 2.5]`); re-pinning
  `MAX_GLOSSY_PARITY_MSE` (0.04 â†’ ~0.006, corroborated by pkg160's 7Ã—-closer
  MSE â€” branch `pkg164-glossy-mse-repin`, **PR #532** (0.04 â†’ 0.006), team-lead
  owns landing it); deleting the dead `stage_shade_metal.cu`; the orphaned
  worktree directories OneDrive won't release (disk hygiene only, no
  correctness impact).

**Changelog:** pkg88-B object motion blur addon bake landed (PR #525 â€”
19+74 tests green) and fixed a pre-existing pkg88-A blocker that made
Blender camera motion blur fail outright in real Blender since it shipped.
pkg157 wavefront firefly clamps restored (PR #526 â€” cross-binary no-op
2.48e-07 relative, ~40Ã— inside the 1e-5 convention); surfaced a phantom
`launchStageInit` overload, closed by **pkg162** (PR #528 â€” 4 of 4 instances
now fixed). pkg160 plain-`metal` GPU/CPU parity (PR #527) found and fixed a
real energy-conservation bug (white-furnace linear up to 1.77Ã—, gamma
rendering could never have caught it) by replacing an invented additive term
with Kulla & Conty compensation; ships the plain-metal parity gate that
never existed; files pkg163 to own the residual spectral-vs-RGB seam. pkg159
GPU cryptomatte restored in the wavefront (PR #529 â€” cross-path IoU
0.964â€“0.984 vs 0.85). pkg161 firefly-bearing gate scene (PR #530 â€”
`firefly_window` 22.85Ã— tail vs â‰¥10Ã— target) un-skips pkg157's suppression
gate, closing a two-day gate hole. Two investigations closed without code:
pkg155 Phase 1 (~5Ã— GPU slowdown confirmed, shade stage convicted at 221
regs/thread) and the sm_120 build-config lever (ruled out, 1.8Ã— slower).
Next pickup: pkg163 â†’ pkg158 â†’ pkg156/pkg120 (wavefront `stage_advance.cu`
lane) â†’ pkg150 â†’ pkg88-D â†’ pkg119-B/C; pkg155 Phase 2 as an opportunistic
GPU-lock gap-filler; pkg153 env-gate disposition remains in flight with the
gate-failure-reviewer. Pillar 4 stays PAUSED.

## Round closeout 2026-07-19 â†’ 2026-07-20 â€” pkg55 Phase C C3+C4 landed (C5 open-verified) + pkg89 GPU dedicated lights + pkg121/pkg119 parity infra + 15 specs

**Overnight autonomous run on the travel laptop (RTX 3000 Ada sm_89, CUDA 13.2, no OptiX SDK).** Nine PRs merged (#485â€“#493) plus five direct-to-main commits; PR #494 (pkg55-C5) is gate-green on RTX but not yet merged at closeout.

### pkg55 Phase C â€” Sessions C3 + C4 landed, C5 open-verified (megakernel deletion still last, in C7)

The delete-megakernels-last arc advanced from 2 to 5 of 7 sessions done/verified. Plan doc `.astroray_plan/docs/pkg55-phase-c-plan-2026-07.md` is authoritative.

- **C3 â€” non-visible-band + naive-multiwavelength wavefront (PR #486, 2026-07-19).** NIR/UV naive parity SSIM 1.0000/0.9999 (both bands degenerate-black; wavefront naive agrees with CPU multiwavelength on black), visible naive SSIM 0.9917, visible-default NEE unchanged. **The committed lambda-threading (93c43bf) never compiled in Release** â€” a stale forward decl in `stage_advance.cu` lagged the 10-arg signature, and a stale shadow `.pyd` at the worktree root loaded first and made the wavefront sample VISIBLE wavelengths for every band (the apparent 573Ã— "divergence"); fix was completing the forward decl + rebuild, no emission change. **The prior "MW megakernel black in NIR" claim is RETRACTED** â€” re-measured on the fresh build, the GPU megakernel matches CPU multiwavelength in NIR (both correctly black); the real gap is that the CPU `path_tracer` ignores `wavelength_range` (renders NIR as visible RGB), out of C3 scope â†’ filed as **pkg125**. C3 gates replaced with agreement-on-black gates vs the band-aware `multiwavelength_path_tracer` (the original gates compared against the band-IGNORING `path_tracer` and were uncalibratable).
- **C4 â€” TLAS/instancing + deformation motion in the wavefront (PR #490, 2026-07-20).** `intersectPathSlot` + `gpu_nee_occlude` switched to `gpu_tlas_hit`/`gpu_tlas_occluded` (null-TLAS path byte-identical), `ray.time` + motion vertices threaded through the SoA. 2/3 functional gates PASS (instancing parity âœ“, motion streak âœ“). **A miswritten exact-equality bit-identity gate was adjudicated:** the GPU wavefront was never run-to-run bit-exact â€” parallel atomic accumulation has an architectural floor ~2e-7 (measured 1.19e-07 fp noise), so the gate was fixed to the 1e-5 Monte-Carlo convention rather than exact equality.
- **C5 â€” spectral photon-map caustics in the wavefront (PR #494, OPEN-VERIFIED, not merged at closeout).** 2/2 C5 gates PASS on RTX (photons-off identity â‰¤1e-5 + glass-sphere caustic parity wavefront-vs-MW SSIM â‰¥ 0.80) + 40-test regression green. **The load-bearing bug:** the photon-flush was nested inside `if(hasRad)`, so any dead path with zero spectral radiance dropped its caustic energy (100% of the gate scene, whose only light is a dedicated sun invisible to wavefront NEE); flush is now unconditional, matching the MW kernel. Known limitation (documented): the gate scene's non-caustic component renders black on the wavefront route because dedicated lights are not yet in wavefront NEE (pkg89 follow-up, C6/C7 scope). **Include as merged if #494 lands; otherwise it remains open-verified.**

### pkg89 GAP-1 â€” dedicated lights uploaded to the GPU (PR #489, 2026-07-20)

Blender-lamp-lit scenes stopped rendering DARK on GPU: a `GDedicatedLight` tagged-union POD + device `sampleLi` mirroring the CPU per-type `sampleLi`, unified power CDF over hittable + dedicated emitters, wired into the multiwavelength megakernel NEE. **Measured GPU==CPU parity (blackâ†’parity): AREA ratio 0.998, POINT ratio 0.997.** Conservative scope: the light tree stays on the power-CDF fallback when dedicated lights are present; wavefront NEE, the RGB legacy megakernel, IES-on-GPU, and exact-blackbody spectral remain follow-ups. **GAP-2 â€” energy audit (STOP + AUDIT):** the CPU dedicated-light wattageâ†’radiance is mis-scaled vs Cycles (dedicated AREA 0.13Ã— calibrated geometry at equal wattage â€” size-dependent, per-type inconsistent; point ~3.6Ã— the opposite direction; blackbody ~14Ã— grossly over-bright). It is NOT a clean factor, so it is escalated to **pkg122** (spec filed PR #488) â€” see `.astroray_plan/docs/pkg89-energy-audit-2026-07.md`. GPU==CPU parity mirrors current CPU behavior and does NOT assert the energy is correct.

### pkg121 Phase A â€” chiÂ² sampler-validation harness (PR #485, 2026-07-19)

Mitsuba 3's chiÂ² sampler harness ported (BSD-3-Clause) + `debug_bsdf_*_batch` CPU BSDF bindings, owner-approved. **Lambertian anchor PASSES (p=0.23).** The Disney specular-lobe sample()/pdf() mismatches were reproduced statistically and **xfail'd, then escalated to pkg123** (the residual maps localize the defect at the lobe core). The finding doc was rewritten to its final state post-merge (b7895ac), superseding a stale draft. **Phase B (validation campaign + visual gallery) is spec'd and the first gallery is already rendered** at `test_results/chi2_visuals_2026-07/` (3 figures incl. the pkg123 residual-map money shot) â€” the owner explicitly wants publication-quality dataviz here.

### pkg119-A â€” Blender parity coverage matrix (PR #487, 2026-07-19)

First-ever Blender parity measurement for the addon: a headless-Blender introspection script enumerates every render-relevant Blender feature at socket granularity and cross-references the addon's actual translation layer (AST-scanned, helper-method reads included). **Reworked four times under adversarial review** (v1 hardcoded name tables â†’ fake-SUPPORTED; v2 hand-typed evidence â†’ wrong cells; v3 AST-blind-to-helpers â†’ anti-flattering; v4 final = honest). **v4 headline: 131 SUPPORTED / 23 APPROXIMATED / 370 DROPPED-SILENT / 0 UNKNOWN / 20 stale sockets of 524 socket-level features.** The 20 stale sockets are latent addon bugs discovered by the scan. Phases B (differential harness + the stale-socket addon fixes) + C remain open.

### 15 new package specs filed (pkg123-137)

Three spec-filing PRs landed the 2026-07 engine/PBR sweep backlog:

- **Correctness/sampling (PR #493):** pkg123 Disney specular-lobe chiÂ² adjudication (un-xfail the pkg121 gates), pkg124 VNDF sampling for the Disney specular reflection lobe, pkg125 CPU `path_tracer` band awareness, pkg126 mesh-emitter unification (pkg89 Phase C).
- **Material + caustics (PR #491):** pkg127 Specular Polynomials for Newton-free SMS seed finding, pkg128 thin-film iridescence (Belcour-Barla), pkg129 reflection multiscatter energy compensation via Turquin albedo-scaling LUTs.
- **Eight platform techniques (PR #492):** pkg130 light groups + emission decomposition (LuxCore), pkg131 zero-knob adaptive sampling (Cycles), pkg132 host-mapped memory fallback (Cycles DEVICEMAP spill), pkg133 SRF spectral sensors (Mitsuba `specfilm`), pkg134 Light Path Expressions (OSL LPE automata), pkg135 demand-loaded sparse textures (OptiX Toolkit), pkg136 SVO-based wavefront path guiding (YalÃ§Ä±ner & AkyÃ¼z 2024), pkg137 partitioned SMS + ReSTIR caustics (Hong et al. SIGGRAPH Asia 2025).

### Direct-to-main (no package closed)

- **94ae956 â€” root-shadow-pyd trap killed:** the `sys.path` ordering that let a stale worktree-root `.pyd` shadow the canonical `build_cuda/Release/` module (the root cause of C3's phantom 573Ã— "divergence") is fixed by a `sys.path` reorder + a blocking hook.
- **b7895ac â€” pkg121 finding-doc rewrite** to final post-merge state.
- **1efe9bc â€” project permissions allowlist** from `/fewer-permission-prompts`.
- **3778f37 â€” pkg115 Blender-verify harness:** CUDA 13 `bin\x64` + toolkit autodetect.
- **7a4c970 â€” other-engines technique sweep** (six families, licenses verified) â€” the research base for pkg130-137.

### Owner decisions + notes this round

- Corpus runner cut from pkg119 (scope trim). The `dist/` tcnn zip is kept. `Google_Apps_Script.txt` is kept â€” it drives the owner's Sheets tracker, so plan-doc formats must stay compatible with it.
- **Notable Phase-C findings for the record:** the GPU wavefront never was run-to-run bit-exact (atomic accumulation, C4/#490); the wavefront photon-flush `hasRad` bug was root-caused via device instrumentation (C5/#494); dedicated lights are still absent from wavefront NEE (pkg89 follow-up, C6/C7 scope).
- **Hardware context:** development is moving back to the RTX 5070 Ti workstation imminently. Flag the OneDrive `build_cuda` cross-machine trap â€” wipe + fresh configure on arrival (`DEVELOPMENT.md`) â€” and that laptop-pinned observations (the seed-flaky direct/indirect-clamp gate, walltime baselines) may differ there.

**Changelog:** pkg55 Phase C C3 (PR #486 â€” non-visible-band + naive-MW wavefront, agreement-on-black gates; megakernel-NIR-black claim retracted; CPU path_tracer band-unawareness â†’ pkg125) + C4 (PR #490 â€” TLAS/instancing + deformation motion; exact-equality gate adjudicated to the ~2e-7 atomic floor â†’ 1e-5 convention) landed; C5 (PR #494 â€” photon caustics, 2/2 + 40-test regression green) open-verified. pkg89 GAP-1 dedicated lights â†’ GPU (PR #489 â€” blackâ†’parity AREA 0.998/POINT 0.997) + GAP-2 energy audit escalated to pkg122. pkg121 Phase A chiÂ² harness (PR #485 â€” Lambertian passes p=0.23; Disney spec-lobe â†’ pkg123). pkg119-A parity coverage matrix (PR #487 â€” 131/23/370, 20 stale sockets of 524). 15 specs filed pkg123-137. Direct-to-main: root-shadow-pyd trap killed, permissions allowlist, pkg115-harness CUDA-13 fix, other-engines research sweep.

## Round closeout 2026-07-18 â€” pkg114 COMPLETE (exporter transform-only dispatch â†’ TLAS refit), first travel-laptop session

**pkg114 is now fully COMPLETE** â€” the one remaining exporter INTEGRATION (not an acceptance gate) landed this round, so every pkg114 acceptance criterion AND its follow-ups are closed.

**Environment.** First session on the travel laptop: **RTX 3000 Ada (sm_89), CUDA 13.2, no OptiX SDK, no OpenEXR**. A fresh clean full build succeeded. Full suite on this build: **1285 passed / 0 failed / 32 skipped / 19 xfailed / 4 xpassed** in 9m11s (4 initial failures were a missing `scikit-image` dep â€” installed, all 4 then pass; the 32 skips are OptiX-SDK-gated + OpenEXR-gated tests that the workstation full-featured build unlocks). Workstation-pinned walltime gates passed here.

### pkg114 inc-3d exporter wiring â€” transform-only dispatch â†’ TLAS refit (PR #479, 2026-07-18)

**Pure Python; no C++/CUDA changes (the bindings landed in #468).** The Blender addon exporter's `Change.TRANSFORMS` viewport path now dispatches the inc-3d TLAS-only refit. `convert_objects` records two maps: `_renderer_instance_id_map` {source name â†’ [instance_idâ€¦] in dupli order} and `_renderer_instancer_eligible` {instancer name â†’ bool} (eligibility = **not nested AND all duplis went through a shared BLAS**). A **fast path** fires when a batch is pure-transform, on GPU, and every changed object is an instanced source or an eligible instancer empty: it re-walks `depsgraph.object_instances` re-deriving EVERY dupli's fresh `matrix_world` â†’ `update_instance_transform` per id â†’ one `upload_instance_transforms()` â†’ `render(skip_upload=True)`. Everything else (mixed flat+instanced, poisoned/nested instancers, multi-domain batches, CPU renders) falls back to full sync. `skip_upload` is threaded through `render_viewport_frame`. **Headless Blender 5.1 on the RTX 3000 Ada:** refit render vs full-resync oracle `mad_refit_vs_oracle = 0.00000` (byte-identical, gate < 0.02); moved-image and stale controls both 0.09203 (non-vacuous â€” proves `skip_upload` reads device state). **Tests:** 7 new dispatch + 13 pkg116 cache (contract updated: `ObjectsCache.diff` now returns `(geometry, flat_transforms, xform_names)`) + 15 pkg56 dispatch + 80 addon subset + 5 GPU TLAS â€” all green; CI green; pr-reviewer verified the stale-map invariant (geometry changes always route through re-registration) and merged. **pkg114 spec status flipped to `done`.**

### Direct-to-main commits (74e9bd1..15964e3) â€” no package closed, portability + research + cleanup

- **74e9bd1 chore(portability):** CUDA 13 moved the Windows CUDA DLLs to `bin\x64` â€” `runtime_setup.py` + the addon bundler now probe both layouts; the `session_start` hook scans `build_cuda\Release` + `build_tcnn` and compares `.pyd` mtime vs the HEAD commit time; `pre_commit_diag_check` fixed (it previously never blocked â€” now exits 2 + stderr); `pyd_shadow_guard` legit-list extended; dead machine-pinned paths de-pinned from the pkg-ship / team-overnight / package-implementer skills; `DEVELOPMENT.md` corrected (this laptop = RTX 3000 Ada sm_89) and CUDA-13 / OneDrive footguns documented.
- **fca3c7f chore(cleanup):** removed 7 zero-reference tracked root files (`PR_BODY.md`, `.build_start_ts`, `.build_end_ts`, `build_worktree.bat`/`.ps1`, `runbuild.cmd`, `run_clean_build.ps1`) + 15 gitignored root logs.
- **d9b1d25 + c0f3130 docs(research):** 2026-07 PBR-advances sweep + follow-up pass â€” `.astroray_plan/docs/2026-07-pbr-advances-research.md` and `-pass2.md`. Key: a 4-technique specular/caustic-transport cluster (Specular Polynomials, Partitioned SMS+ReSTIR, Manifold Path Guiding, 3D-Gaussian photon guiding); SVO-based **wavefront** path guiding as the architectural match; GRIS/ReSTIR-PT as the path-space-resampling roadmap with **RTXDI DISQUALIFIED (proprietary)**. **VERIFIED (direct fetch):** Cycles removed its stochastic multiscatter GGX for **Turquin albedo-scaling LUTs** (commit 888bdc1, PR blender/blender#107958); `adobe/openpbr-bsdf` is **Apache-2.0** with 7 CUDA-ready multiscatter energy LUTs; OpenPBR's recommended thin-film model = **Belcour-Barla**.
- **dd670b7 test:** promoted `test_total_max_depth_still_caps_all_paths` xfailâ†’live (7/7 stable on the laptop, XPASSing since June on the workstation). The direct/indirect-clamp gate stays xfail (measured seed-flaky here, 3/7); the `filter_glossy` / caustics-flag gates also stay xfail â€” they xfail on this laptop despite June workstation xpasses (machine/precision-dependent â€” recorded).
- **15964e3 docs(pkg55):** Phase C implementation plan â€” `.astroray_plan/docs/pkg55-phase-c-plan-2026-07.md`, 7 sessions C1â€“C7, **delete-the-megakernels LAST**. C1 blocker: the shared spectral-tables layer lives inside `multiwavelength_kernel.cu`. Verified: light-tree NEE is already in the wavefront; TLAS/motion/non-visible-band/photon-caustics are NOT.

### In flight (record, not complete)

**pkg55 Phase C Session C1** (spectral-tables + light-tree-probe extraction) â€” implementer agent running on branch `feat/pkg55-c1-spectral-tables-extraction`. Phase C (MIS audit + megakernel removal + 2Ã— gate) remains the active arc; the plan doc above is authoritative.

### Notable test-suite state change

Suite on the fresh laptop build: **1285 passed / 0 failed / 32 skipped / 19 xfailed / 4 xpassed**. `total_max_depth` cap gate is now a live test (was xpassed). The 32 skips reflect the laptop lacking the OptiX SDK + OpenEXR (the workstation full-featured build unlocks those â€” not a regression). The 4 xpassed gates remain machine-dependent candidates; do NOT bulk-promote (dd670b7 shows filter_glossy/caustics-flag xfail on this laptop despite June workstation xpasses).

**Changelog:** pkg114 COMPLETE (exporter transform-only dispatch â†’ TLAS-only refit, PR #479 â€” headless Blender 5.1 refit byte-identical to full re-sync, mad 0.00000). First travel-laptop session (RTX 3000 Ada, CUDA 13.2, no OptiX SDK): CUDA-13 `bin\x64` DLL-layout portability + laptop-portable hooks/skills, dead-root-file cleanup, 2026-07 PBR-advances research sweep (+ follow-up: Turquin multiscatter answer, thin-film = Belcour-Barla), `total_max_depth` gate promoted to live, pkg55 Phase C plan. Fresh clean CUDA-13.2 build sweep 1285/0/32/19/4. pkg55 Phase C Session C1 in flight.

## Stabilization session 2026-06-12 evening â€” clean repo, full main-checkout build, showcase + portability

**Repo cleanup.** All 5 registered worktrees removed (clean, branches merged), 32 remote branches deleted (every origin/* except main mapped to a merged PR; `feat/pkg115-visual-diagnosis` = closed #470 superseded by #471), 22 local branches deleted, 6 orphaned former-worktree dirs verified zero-at-risk (worktree-modified + untracked non-build = 0 vs their merged PR heads) and deleted â€” 115 test_results images archived first into `test_results/_archived_orphan_worktrees/`. Backup dirs + 4 stray root files inventoried, owner decision pending. Two `.claude/worktrees` dir shells (musing-kalam, romantic-rhodes) emptied but handle-locked by a process; delete on next session.

**Full build in main checkout (`build_cuda/`, VS 2022 Release).** CUDA 12.8 + OptiX 9.1 (found) + OIDN + OpenMP + `-DASTRORAY_TINY_CUDA_NN=ON` â€” astroray.pyd (107 MB), test helpers, `bin/Release/raytracer.exe`, tcnn_smoke, nrc_smoke_render all green. **Portability fix:** the three neural targets' `CUDA_ARCHITECTURES "89"` pins â†’ `"75;86;89"` + `TCNN_CUDA_ARCHITECTURES` pinned to match (tcnn floor sm_75 supported); removed the stale `#define TCNN_MIN_GPU_ARCH 89` override in `src/neural_cache.cu` that broke the sm_75/86 passes. The build now runs on RTX 3000 (sm_86). **Addon build:** `build_blender_addon.py --backend tcnn` â†’ OpenMP-free .pyd at b67b50f, `dist/astroray/` staged + 912 MB zip. **Standalone verified end-to-end:** Cornell GPU 800Ã—600@128spp â†’ PNG (22.4 s; exe needs OIDN+CUDA DLLs on PATH â€” `docs/DEVELOPMENT.md`).

**RTX sweep (the real gate; CI is GPU-blind).** Full suite on the fresh build: **1299 passed / 0 failed / 14 skipped / 21 xfailed / 3 xpassed** in 7m37s â€” zero flakes, even the pkg64 walltime gates under addon-build load. 9 fewer skips than the morning sweep (full-featured build unlocks OptiX/OIDN-gated tests). pkg55 perf gate isolated cool run: **MK 0.494 s / WF 0.329 s = 1.50Ã—**, target gate XPASS, WF/MK image ratio [0.996, 0.998, 0.997].

**Benchmarks (all timed â†’ `test_results/showcase_2026-06/render_timings.json`).** Contact sheet 1024Â²@512spp: megakernel 6.51 s vs wavefront 4.36 s (1.49Ã—), CPU 256Â²@512spp 5.46 s. In-Blender viewport A/B re-measured fresh (99,458 tris, 256Â², 30 frames, Cycles OPTIXÃ—3): **Cycles p50 203.7 / p99 223.7 â€” Astroray wavefront p50 196.4 / p99 226.2 â€” megakernel p50 195.2 / p99 229.1** (parity; consistent with #463's p99 0.84Ã— within p99-of-29 estimator noise). pkg74 showcase runner full+GPU: material zoo CPU+GPU sheets, convergence grid, integrator comparison + CSV. Reference bank: **12/13 scenes PASS** (GR Kerr 4/4, Schwarzschild 3/3, ADAF 4/4, both SMS caustics, glass caustics, SF11 prism, Cycles-compared Disney sweep); prism-bk7 SSIM 0.9953 vs re-blessed ref but its hue_spread/bright_coverage gates are stale-calibrated from the pre-#400 wide comp (render visually perfect; recalibration = follow-up). pkg115 texture grid paired stills: **#474 verified visually â€” magic/gradient/checker/wave/brick/voronoi all render correctly via the addon (CPU leg)**; GPU leg dark = known pkg89 dedicated-light upload gap; CPU exposure ~uniformly dimmer than Cycles = known pkg89 energy-scale follow-up.

**Showcase renders (new features, fresh build).** pkg114 instancing field (432 instances / 3 shared BLAS, 28 GPU prims), pkg86-B light-tree scene (128 area lights, 0.10 ms upload), pkg88-C.0 deformation motion blur (GPU 4.5 s vs CPU 69.2 s @ 1024Â²Ã—512), wavefront contact sheet, all visually inspected. README gallery refreshed per recovered owner feedback (transcript archaeology; saved to agent memory `readme-showcase-render-feedback`): live wavefront contact sheet, convergence vs INDEPENDENT 8192-spp reference (slope âˆ’0.492), 2Ã—3 AOV stack incl. sample/bounce heatmaps, 1280Ã—720 64-light OIDN split, **prism tile re-rendered via forward photon caustic integrator (refbank comp) â€” vivid full-spectrum rainbow**, HDRI + Disney sweep + hero kept. **Deliverables:** `docs/reports/2026-06-feature-showcase.html` (self-contained, base64), README refresh, `docs/DEVELOPMENT.md` (two-build story, perf-gate calibration table, Windows footguns, laptop setup).

## Round closeout 2026-06-12 morning â€” 4 PRs merged (pkg115 COMPLETE â€” Cycles-parity textures + GENERATED coords fix, 1289/0; pkg114 inc 3d â€” TLAS-only refit 19.5% of full upload)

**pkg115 COMPLETE.** All Stage 2 chunks + the GENERATED-coordinates mesh fix landed. Full RTX suite on merged main f11085c: **1289 passed / 0 failed / 23 skipped / 21 xfailed / 3 xpassed**.

### pkg115 chunk 6 + GENERATED coords fix â€” Cycles-parity textures COMPLETE (PRs #467/#471/#472, 2026-06-12)

**PR #467 â€” chunk 6 addon dedup (2026-06-11 evening).** The addon's hand-rolled procedural-texture param mappings unified onto the engine's Cycles-parity ports: Factory `createProceduralTexture` new `noise_perlin` branch (9 params â†’ NoiseTextureCycles); Wave extended to full 16-param Cycles vector; Brick to 19 params. Addon: `ShaderNodeTexNoise` routes to Perlin port with `noise_type`/`normalize`; Wave passes wave_type/directions/profile/phase/detail_scale; Brick passes Color2/MortarSmooth/Bias/frequencies. **Review caught a shipped bug (BLOCKâ†’fixedâ†’SIGN-OFF):** the noise enum map had RIDGEDâ†”HYBRID swapped vs engine ordering â€” a Blender Ridged Multifractal rendered Hybrid and vice versa. The stub test enshrined the swap; it now pins the addon to the engine contract. Visual-verify harness (`scripts/verify_pkg115_textures_blender.py`) paired-engine stills of an 8-sphere texture grid; CYCLES leg renders correctly; CUSTOM_RAYTRACER leg renders dark/untextured spheres â€” an end-to-end F12 export gap (distinct from this chunk's translation layer, unit-tested green). 18/18 translation+noise after the enum fix. **PR #471 â€” visual-gate diagnosis (2026-06-11 late evening).** Four-root-cause diagnosis of the pkg115 visual gate: (1) **GPU dark = pkg89 dedicated lights not uploaded to GPU** (pkg86-B deferral, affects any dedicated-light GPU scene); (2) **CPU hang = OpenMP deadlock inside Blender 5.1** â€” GENERALIZED from the MinGW-only memory to MSVC/vcomp: **ALL addon-use builds need `-DASTRORAY_DISABLE_OPENMP=ON`**; (3) harness F12 sample property; (4) UV-vs-GENERATED coordinate space. Harness gains: `--device/--resx/--light-energy`, `ASTRORAY_PYD_DIR` override, correct sample property, tolerant sockets. Doc + script only. **PR #472 â€” GENERATED texture coordinates for triangle meshes (2026-06-12 early morning).** Closes the coordinate-space gap: procedural textures on meshes now honor Blender's GENERATED coordinate semantics (object bbox-normalized 3D position; Cycles orco). The implementer's `AreaLightShape::hit` hitObject line was correct for analytic shapes but could not fix meshes â€” triangle hits set `hitObject` to the Triangle (whose own bbox is the wrong frame), so the Generated path silently fell back to UV. Mesh fix: `Texture::setGeneratedBBox` (explicit-bbox branch in `CoordMode::Generated`) + `set_texture_generated_bbox` binding + the addon records GENERATED-mode textures per material in `convert_materials` and bakes each user object's **world** bbox in `convert_objects` (world == object space for baked meshes; shared-material multi-object = last-writer-wins, per-object instancing recorded as follow-up). **128-spp Blender stills** (5.1 headless, OpenMP-free build): checker = large 3D blocks, brick = brickwork, wave = bands, voronoi patterned â€” **semantic parity with Cycles** (was concentric UV rings). Regression test replaced (implementer's test used invented APIs and could never run â€” the documented failure mode, caught by review again; replacement drives the real bindings end-to-end). Full suite: **1289 passed / 0 failed** (RTX). pkg98 SIGN-OFF (Opus) â€” the key objectPoint-validity check traced clean; both lead refutations of the implementer's claim confirmed; API plumbing, addon ordering/grace-degradation, and the honest COMPLETE-with-remaining-list status all verified. **Remaining pkg115 follow-ups (recorded in spec):** gradient + noise spheres near-black on the addon path; pkg89 dedicated-light energy audit; per-object texture instancing for shared materials.

### pkg114 inc 3d â€” TLAS-only refit for transform-only edits (PR #468, 2026-06-11, dedicated pkg114 agent)

A transform-only edit of an instanced object no longer rebuilds/re-uploads geometry. This closes pkg114's **last acceptance criterion** (transform-only viewport edit â‰¤ 50% of the pkg56 Phase-A baseline). Mechanism: `Renderer::updateInstanceTransform(id, M)` (replace an instance's transform on the CPU in place) + `CUDARenderer::uploadInstanceTransforms` (re-push **only** `d_instances` + `d_tlas` via `buildTlasOnly()`, which rebuilds the instance/TLAS arrays from the current transforms with per-mesh bounds from each cached BLAS's O(1) `boundingBox()` â€” **no BLAS geometry walk, no nodes/prims/triangles re-upload**) + `render(skip_upload=True)` (render from existing device state, also skips the redundant CPU `buildAcceleration`). The instance/TLAS construction is factored into `buildInstancesAndTlas()`, shared by the full build and the refit, so a refit is **byte-identical** to a full rebuild. **Verification (RTX, `test_tlas_refit.py`):** Correctness (refit-isolated) â€” upload geometry with an instance at A, refit to B, `render(skip_upload=True)` â†’ matches an oracle built from scratch at B (mad < 0.02). Negative control: without the refit, `skip_upload` keeps the device at A and *differs* from the B oracle â€” proving `skip_upload` reads device state (so the match above proves the refit wrote correct device state). **Budget:** refit upload = **19.5%** of a full `upload_geometry` on 3200-tri Ã—16-instance (< 50%; the gap widens with geometry). Regression: all TLAS (inc 1/2/3a/3b/3c) + glass furnace / MW / pkg56 uploaders / cryptomatte pass. **Note:** the `test_pkg64_gpu_phase2` empty-hook **walltime** gate reads ~1.5Ã— vs a **May-24** pinned baseline â€” a known pre-existing cross-session drift from the #461 wavefront render-path overhaul (recorded in #459's title). The **bit-equality** functional gate passes, and this PR's edits only touch the *instanced* path, byte-identical to inc-3b on the non-instanced path. Baseline left untouched (re-pin is a separate closeout task). **Remaining:** wire the exporter `Change.TRANSFORMS` branch to call these for instanced objects (instance-id map) â€” a small integration follow-up.

### Notable test-suite state change

Hardware state: all verified on RTX 5070 Ti this round; full suite at #472 merge: **1289 passed / 0 failed / 23 skipped / 21 xfailed / 3 xpassed**. The 3 xpassed gates are the spectral-path-tracer ported flags (down from 2 xpassed last round â€” 1 promoted or returned to xfail status). pkg114 inc 3c (addon instancing wiring) + inc 3d integration (exporter transform-only dispatch) remain open with its dedicated agent.

## Round closeout 2026-06-12 overnight â€” 5 PRs merged (pkg55-B' Phase B' COMPLETE â€” viewport-parity gate MET: wavefront p99 = 0.84Ã— Cycles-OPTIX)

**pkg55-B' Phase B' COMPLETE.** All three Phase-B' acceptance criteria MET: perf gate 1.50Ã— (PR #459 cool-GPU re-baseline), wavefront_path_tracer registered (PR #459), viewport-parity gate MET (PR #463 â€” wavefront steady-state pan-frame p99 = 0.84Ã— Cycles-OPTIX, target â‰¤1.2Ã—; mean 0.97Ã—, p50 0.98Ã—). Full RTX suite on merged main 3804dca: **1277 passed / 0 failed / 23 skipped / 22 xfailed / 2 xpassed**.

### pkg55-B' Phase B' close â€” perf + plugin + viewport-parity gate (PRs #459/#461/#463, 2026-06-12)

**PR #459** â€” cool-GPU perf re-baseline + plugin registration. Cool-GPU formal gate run (owner confirmed stable temps) measured **1.50Ã— â€” floor PASSED, 1.5Ã— target XPASSED** (trial band 1.45-1.52Ã— straddles threshold; target stays xfail strict=False for CI robustness, but **Phase-B perf criterion recorded as MET**). `plugins/integrators/wavefront_path_tracer.cpp` â€” decorator over `path_tracer` (CPU delegates; GPU dispatch routes to `cuda_wavefront_render` when `ASTRORAY_WAVEFRONT_CUDA_N3` is defined, megakernel fallback otherwise; preprocessor pairing verified in both states). `integrator_capabilities("wavefront_path_tracer")["gpuSupported"] == True` â€” **original Phase-B acceptance checkbox**. 3 tests (capabilities, GPU-routing allclose, CPU fallback). Full suite: 1273 passed, 2 failed (both `test_empty_hook_walltime_overhead` pkg64 phase 2/3 thermal flakes â€” pass in isolation, failed under full-suite load on heat-soaked card; environmental, untouched code). pkg98 SIGN-OFF (Opus). **PR #461** â€” wavefront viewport groundwork (persistent device context, single-wave fast path, double-scene-flatten dispatch fix). Persistent context: grow-only allocations reused across calls; scene data re-uploaded per call (megakernel-parity policy; pkg56 Phase C selective upload = shared follow-up); dropped JH/CMF table upload caught by image gate and restored with anchoring comment. Single-wave fast path: 1-spp chunks run exactly max_depth passes with zero work-counter D2H syncs (waves==1 âŸº samples==1; bounce-cap arithmetic covers all deaths; post-loop regen accumulates last pass). **Real bug â€” double scene flatten:** GPU dispatch ran megakernel uploadScene BEFORE wavefront branch, so wavefront route ran buildSceneArrays (99k-tri host flatten) TWICE per frame (~30-40 ms); skipped for wavefront integrator. **Measured (RTX 5070 Ti, 100k tris, 256Â², 1-spp chunks, 30-frame pan, back-to-back):** megakernel p50 79.8 ms / mean 83.0; wavefront p50 86.0 ms / mean 89.3 â€” **within 8%** (was ~40% behind). All 25 wavefront-diff gates pass; 1.5Ã— perf target xpassing. pkg98 SIGN-OFF (Opus). **PR #463** â€” **VIEWPORT-PARITY GATE MET.** In-Blender Cycles A/B (`blender_driver.py --mode offline`, Blender 5.1 `--factory-startup`, identical generated 99,458-tri grid scene + camera path, 30 frames, 256Â², 1 spp, back-to-back legs; Cycles on OPTIX, 3 devices enabled per committed JSON). Steady-state (frames 1-29): Astroray-megakernel p50 186.2 / p99 197.9 / mean 188.4; **Astroray-wavefront p50 189.0 / p99 207.4 / mean 191.1**; Cycles-OPTIX p50 192.3 / p99 246.2 / mean 197.2. **Gate: wavefront p99 / Cycles p99 = 0.84Ã— (target â‰¤1.2Ã—) â€” MET**, with p50 at 0.98Ã— and mean at 0.97Ã— â€” **parity-or-faster on every statistic**. (Raw 30-frame p99 equals each leg's first frame â€” one-time setup, excluded as not pan behavior; raw JSONs committed under `benchmarks/viewport_parity/results/`.) Driver changes: `--make-scene` (builds pkg81 quad grid in-Blender, mirroring run.py geometry exactly â€” reviewer-verified line-by-line), `--integrator`, headless addon bootstrap with fresh-pyd guard (Blender's installed extension shadowed the build's module â€” `--factory-startup` + `os.add_dll_directory` for CUDA runtime), Cycles GPU enablement. pkg98 SIGN-OFF (Opus) â€” measurement-validity review: claimed numbers recomputed exactly from committed raw JSONs; wavefront leg traced to `cuda_wavefront_render`; scene-builder parity verified; frame-0 exclusion judged statistically honest; p99-of-29 estimator fragility noted and absorbed by 43% gate headroom. Full local suite on fresh build: **1277 passed / 0 failed** (pkg114 inc3a/3b new TLAS tests got incidental RTX verification â€” initially 2-test failure via stale-pyd trap, rebuild made them pass). **pkg55-B' Phase B' COMPLETE: perf gate 1.50Ã— MET, wavefront_path_tracer registered, viewport-parity gate MET.** Phase C (MIS audit + megakernel removal + 2Ã— gate) remains. Deferred from N+6: non-visible-band profile override, TLAS/motion in wavefront, light-tree NEE branch.

### pkg114 increments 3a+3b â€” register_mesh_bulk + mixed scenes (PRs #460/#462, 2026-06-12, dedicated pkg114 agent)

**Inc 3a (PR #460):** `register_mesh_bulk` binding â€” bulk twin of `register_mesh_triangles` ingesting object-local geometry with UV layers, per-vertex (smooth) normals, and per-triangle multi-material into one shared BLAS, returning `mesh_id` for `add_instance()`. Triangle construction byte-for-byte identical to `add_triangles_bulk`; only destination differs (`registerMesh()` â†’ shared BLAS vs flat scene push). RTX: 2 instances of an octahedron (smooth normals + 2 materials + UV layer) render identical to baked world-space `add_triangle` calls â€” per-channel mean ratio [0.97, 1.03], mean abs per-pixel diff < 0.02. Upload log confirms BLAS sharing: instanced = 8 prims vs baked = 16. **Inc 3b (PR #462):** **MIXED instanced + non-instanced GPU scenes.** The two-level upload was all-or-nothing â€” any instance dropped every flat object from the GPU. Fix: flat scene (`cpu.getBVH()`) uploaded first (node/prim offset 0), exposed as ONE identity-transform instance, so `gpu_tlas_hit` traverses flat+instanced uniformly (**no device-side change, no new traversal path** â€” inc-1 identity-parity test already proved identity instance path byte-exact). Flat prims at offset 0 keep pkg64 SMS `primIdx` convention and light emitterâ†’prim search valid; flat-scene area lights now resolve in mixed scenes. Shared `appendFlatScene()` for single-level + mixed paths. Also adds optional `object_name` to `register_mesh_bulk`/`register_mesh_triangles` â†’ correct Cryptomatte object id on shared BLAS. RTX: flat green floor + 3 instanced tetrahedra (incl. mirror) pixel-identical to fully-baked world-space (floor-band green present, per-channel ratio [0.97, 1.03], mean abs diff < 0.02). Broad GPU regression sweep (glass furnace, MW, shade-smooth, pkg64 phase2/3, light-tree, caustic-parity, spectral materials, glass-sphere caustic, motion, light-sampler, CPU cryptomatte) â€” all pass, only pre-existing xfails. Known v1 limitations (documented, deferred): emitters and caustic casters on instanced meshes not yet wired (flat-scene ones are); deformation motion not applied to flat scene when instances coexist. **REMAINING (inc 3c):** addon `convert_objects` instancing wiring + depsgraph transform-only refit (TLAS-only re-upload for pkg56 â‰¤50%-baseline budget).

### Notable test-suite state change

Hardware state: all verified on RTX 5070 Ti this round; full suite at #463 merge: **1277 passed / 0 failed / 23 skipped / 22 xfailed / 2 xpassed**. The 2 xpassed gates are the spectral-path-tracer ported flags (down from 6 xpassed last round â€” 4 promoted or returned to xfail status). pkg114 inc 3c (addon instancing wiring) remains open with its dedicated agent.

## Round closeout 2026-06-11 evening â€” 8 PRs merged (pkg55-B' Sessions N+7 parts 3-7 COMPLETE â€” wavefront BEATS megakernel, 1.45-1.52Ã— @ 1.5Ã— threshold)

**The wavefront program TODAY went 4.0Ã—-slower â†’ 1.45-1.52Ã—-FASTER than the megakernel.** All RTX-verified. Final sweep on merged main 99ffc7a: **1272 passed / 0 failed / 23 skipped / 18 xfailed / 6 xpassed**.

### pkg55-B' Sessions N+7 parts 3-7 â€” intersect/shade split â†’ path regeneration â†’ perf gate â†’ shadow stage â†’ template-RNG â†’ any-hit (PRs #450-#457, 2026-06-11)

**Phase-B performance goal MET.** N+7 part 3 (PR #450): staged wavefront â€” `advancePathSlot` split at post-emissive boundary (no RNG consumed, streams preserved) into `intersectPathSlot` (intersect + env-miss + emissive, parks 9-field GHitRecord in N+3 hit-buffer SoA + `hit_prim_id`) and `shadePathSlot` (NEE + RR + BSDF from parked record); flat `advancePathSlot` recomposed FROM halves (one generator, decision #9). `stageIntersectQueuedKernel` buckets survivors by GMaterialType (7 fixed-stride buckets, atomic append â€” Laine 2013 Â§5 sort-by-material as bucketing); ONE `stageShadeBucketedKernel` covers all buckets with warp-coherent material types. **Measured: all 21 gates pass; WF/MK image ratio unchanged [0.997, 0.999, 0.997]; depth 8 staged 0.078 s vs part-2 flat 0.074 s (within noise, lambertian-dominated scene); depth 16/32 WF degrades to 0.58Ã—/0.48Ã— of MK. DIAGNOSIS: bottleneck is per-sample round structure (2 launches+memsets per bounce Ã— depth Ã— 64 rounds over shrinking queues), NOT material divergence.** Part 4 = PATH REGENERATION (Laine 2013 Â§4). pkg98 SIGN-OFF (Opus). **Part 4 (PR #451): PATH REGENERATION â€” wavefront BEATS megakernel first time.** `stageRegenKernel` (dense pass): dead slots accumulate radiance at THEIR pixel (atomic; XYZ + firefly clamp at death), zero color, claim next (pixel, sample) from global counter, re-init via `initPathSlot` (extracted as non-static rdc-linked device function â€” one generator; RNG keyed by (pixel, sample), per-path streams IDENTICAL to per-round). Pool stays ~full; driver loop = regen â†’ dense-identity intersect (new dead-slot guard) â†’ bucketed shade. Work counter read every 16 passes (only syncs); max_depth drain passes + final accumulating regen retire in-flight tail. **Measured (RTX 5070 Ti, session_n1_envmap_cornell 256Â²): depth 8: 1.34Ã— faster than MK; depth 16: 1.40Ã— (depth trend reversed); 512 spp (gate spp): 1.40Ã—. All 21 gates pass; WF/MK ratio [0.9972, 0.9994, 0.9968] (last-decimal drift from accumulation-order change, within gates).** pkg98 SIGN-OFF (Opus): exactly-once accumulation traced by hand + empirically (image mean flat across depth 8/16/32 â€” drain leak would darken deep renders); no double accumulation; RNG keying byte-equivalent. **Perf-gate infrastructure (PR #452): tests/scenes/disney_contact_sheet.py** (balanced 4Ã—2 sphere grid, one per wavefront material type, floor + overhead area light â€” Phase-B gate scene) + **tests/wavefront_diff/test_pkg55_perf_gate.py** (two-tier: **hard floor â‰¥1.15Ã—** regression protection at measured 1.39Ã— @ 512 spp, WF/MK image agreement 0.6%; **â‰¥1.5Ã— target as xfail(strict=False)**). Profile: stage_shade_bucketed dominates at 254 regs/thread â€” inline NEE BVH shadow traversal is register hog; Laine shadow stage is path to 1.5Ã—. **Shadow-stage blueprint (PR #453): docs/pkg55-shadow-stage-blueprint.md** â€” line-precise factoring plan for splitting `sampleDirectSpectralMW` into sample/occlude/resolve thirds (megakernel recomposes byte-identically; wavefront gains dedicated lean shadow stage). **Shadow stage (PR #454): factored + deferred, perf-neutral finding.** `sampleDirectSpectralMW` factored into `gpu_nee_sample` (6 RNG draws, original order; no evals, no trace) / `gpu_nee_occlude` (shadow trace) / `gpu_nee_resolve` (lazy post-trace material evals). Megakernel recomposes Aâ†’Bâ†’C byte-identically (lightPdfâ‰¤0 reject moves pre-trace â€” pure math, identical output, less work). Wavefront shadow stage: deferring bucketed shade pre-resolves BSDF eval/pdf/MIS at shade (Cycles shade_surface.h ordering â€” bsdf_eval before queuing intersect_shadow; Veach 1997 power heuristic) and parks 11-float payload; dedicated `stageShadowKernel` = trace + emission upsample + accumulate. **Measured: contact-sheet speedup unchanged 1.39Ã— (shade 18.8 â†’ 14.6 + 4.3 ms shadow); register reports stay ~221 for both heavy kernels â€” occupancy was NOT binding constraint on this scene; split's value is structural.** All 22 wavefront-diff gates pass; image ratio unchanged; full suite 1272/0. pkg98 SIGN-OFF (Opus). **Knob re-prioritization (PR #455): docs note** â€” since #454 both pipelines share NEE/eval code, shared-code wins (any-hit) cannot move RELATIVE â‰¥1.5Ã— gate; remaining wavefront-only cost is 2Ã— curand_init per shade (megakernel: one per path). Knob #1 becomes template-RNG generalization of gpu_materials.h (megakernel instantiates curandState* unchanged; wavefront draws from slot's PCG stream â€” closer CPU mirroring). **Template-RNG (PR #456): knob #1 closed â€” 1.39Ã— â†’ 1.46Ã— stable.** gpu_materials.h's 15 sampling functions become template<typename TRng> with gpu_rng_uniform ADL dispatch (curandState overload = exactly curand_uniform; megakernel instantiation/codegen unchanged). NEE thirds moved into src/gpu/gpu_nee.cuh (templates can't be rdc-exported); gpu_nee_sample templated. Wavefront: NEE/BSDF sampling uniforms draw DIRECTLY from per-path PCG32 stream (WavefrontRNG overload in namespace astroray, ADL-found). Convention amendment (spec Â§4.2 decision #2): per-bounce dimension counts now vary by branch; per-stage gates compare only deterministic-given-stage fields; final-image gates remain sampling oracle. **Measured (RTX 5070 Ti, contact sheet 256Â²Ã—512spp): stable 1.41â€“1.46Ã— over 4 trials (was 1.39Ã—). Perf floor raised 1.15 â†’ 1.30.** All 22 wavefront gates pass; CPU-oracle image ratio unchanged [1.089, 0.990, 1.046]; WF/MK tightened to [0.996â€“0.998]. Full suite: 1272/0. 1.5Ã— target remains xfail; next lever: any-hit shadow traversal (equal absolute savings grow ratio while MK > WF). pkg98 SIGN-OFF (Opus). **Any-hit shadow traversal (PR #457): AT the 1.5Ã— threshold.** `gpu_bvh_occluded` â€” same node walk + leaf predicates as gpu_bvh_hit, returning on FIRST accepted hit (no record, no tangent, no closest tracking). Cite: PBRT-v4 Primitive::IntersectP; Cycles scene_intersect_shadow (both Apache-2.0). `gpu_tlas_occluded` â€” no-TLAS â†’ lean walk; TLAS path v1 delegates to closest-hit instance walk (boolean-identical; dedicated any-hit instance walk = named follow-up). gpu_nee_occlude: TRIANGLE-light branch switched (boolean-identical by construction); SPHERE lights keep reach-the-light closest semantics. Both pipelines share via recomposed wrapper. **Measured: ratio 1.45â€“1.52Ã— over 4 trials @ gate config â€” AT 1.5Ã— threshold; absolute times climbing run-over-run (thermal throttling after ~12 h continuous GPU benchmarking), so ratio is robust metric. 1.5Ã— target stays xfail(strict=False) â€” XPASSED in full-suite run on cooler GPU (suite: 1272/0, 6 xpassed).** All 22 wavefront gates pass; occlusion answers boolean-identical by construction. Spec notes scene-dependence physics (few early exits when light sees most surfaces; any-hit forfeits tMax-shrink pruning) and cool-GPU re-baseline follow-up. pkg98 SIGN-OFF (Opus). Reviewer flagged two future adopters (stage_light_sample legacy TODO, path_trace_kernel RGB NEE) â€” out of scope here. **REMAINING for Phase-B' close:** cool-GPU perf re-baseline (1.5Ã— xfail likely flips), wavefront_path_tracer plugin registration, pkg81 viewport-parity gate.

### Notable test-suite state change

Hardware state: all verified on RTX 5070 Ti this round; full suite at #457 merge: **1272 passed / 0 failed / 23 skipped / 18 xfailed / 6 xpassed**. The 6 xpassed gates include the 1.5Ã— perf target (xpassed on a cool full-suite run â€” worth listing for next-round promotion alongside 3 spectral ones from earlier rounds). pkg114 inc3 (addon instancing) still pending with its dedicated agent.

## Round closeout 2026-06-11 afternoon â€” 8 PRs merged (pkg115 chunks 2-5 COMPLETE + pkg55-B' Sessions N+6/N+7 COMPLETE)

**Two packages advanced major steps this round.** All RTX-verified. Final sweep on merged main 5e21bd5: **1271 passed / 0 failed / 23 skipped / 20 xfailed / 3 xpassed**.

### pkg115 Stage 2 chunks 2-5 â€” Noise/Wave/Brick/Voronoi Cycles parity COMPLETE (PRs #441/#442/#445/#446, 2026-06-11)

**Chunks 2-5 shipped.** Chunk 2 (PR #441): Jenkins lookup3 hash family (Cycles `util/hash.h`, Apache-2.0) bit-exact, PCG3D `hash_int3_to_float3` with signed arithmetic-shift semantics; Perlin core (`perlin_3d`/`snoise_3d`/`noise_3d` from `svm/noise.h`, BSD-3-Clause Sony Pictures Imageworks + Blender); fractal stack (`noise_fbm` + multifractal/hetero/hybrid/ridged from `svm/fractal_noise.h`, Apache-2.0); WhiteNoiseTexture + NoiseTextureCycles (Blender "Noise Texture" node per `svm/noisetex.h`). 39/39 noise + procedural tests. pkg98 SIGN-OFF (hash bit-exactness, BSD-3 notice placement, fractal formula exactness). Chunk 3 (PR #442): Wave (cite `svm/wave.h`, Apache-2.0) â€” fixes the documented ~6.4Ã— density bug (phase factor 20.0, was Ï€); signed-fBM detail distortion via chunk 2's `fractal_noise::noise_fbm`; band/ring direction enums; sine/saw/triangle profiles exact; Brick (cite `svm/brick.h`, Apache-2.0) â€” 3D input, `brick_noise` integer hash bit-identical, row offset/squash with frequencies, mortar_smooth smoothstep, bias, per-brick color variation. 51/51 wave/brick/noise tests. pkg98 SIGN-OFF â€” line-by-line comparison against canonical `svm/wave.h`/`svm/brick.h` fetched from projects.blender.org. Chunk 4 (PR #445): full Cycles-parity Voronoi port (audit item 9, largest port) â€” distance metrics (Euclidean/Manhattan/Chebychev/Minkowski with exponent socket), Features (F1/Smooth F1/F2/Distance to Edge/N-Sphere Radius), cell jitter via `hash_int3_to_float3` for identical pattern layout, fractal layering `fractal_voronoi_x_fx` with detail/roughness/lacunarity octave stack, node conditioning per `svm_node_tex_voronoi:1065+`. Lead-review fixes (`360d1db`): `normalize` ignored at detail=0 fixed; Distance-to-edge midpoint term restored; Fractal position divided by local accumulator (shadowed member) fixed. 1265 passed, 0 failed. Chunk 5 (PR #446): addon `ShaderNodeTexVoronoi` translation + factory full-param wiring (fixes latent regression where the addon's feature map was stale after #445 changed the C++ enum â€” F2 would have rendered Smooth F1; caught by pure-Python addon tests). Wires Detail/Roughness/Lacunarity/Exponent/normalize sockets into a 16-float param vector; backward-compatible (legacy 5-param scripts keep working). 18/18 addon tests + 2/2 standalone tests. **REMAINING (audit item 10 PARTIAL):** addon-side private texture-definition duplication removal (Approach step 4) + Blender-vs-Cycles paired-still RTX visual (`/verify`).

### pkg55-B' Sessions N+6/N+7 â€” End-to-end GPU wavefront pipeline + MEGAKERNEL PARITY (PRs #443/#444/#447/#448, 2026-06-11)

**The GPU wavefront now produces IMAGES at megakernel parity.** Session N+6 (PR #443): the first end-to-end render from the split-kernel pipeline, unlocking the final-image gate (the only gate that exercises BSDF/NEE sampling â€” the per-stage gates compare only deterministic-given-stage fields by design). Deliverables: `src/gpu/wavefront/stage_advance.cu` (one-bounce device twin of CPU `advance_one_bounce`: intersect â†’ env-miss â†’ emissive â†’ NEE â†’ RR â†’ BSDF, exact CPU stage order; where the CPU seeds mt19937 from the wavefront stream, the GPU seeds a LOCAL curandState from the same drawn dimension and calls the UNMODIFIED megakernel device functions â€” `gpu_material_sample_spectral` for all 7 GMAT types, `sampleDirectSpectralMW` for NEE, `gpu_spectrum_to_xyz` for RR â€” design decision #9 applied to the GPU: one generator of sampling math, zero re-transcription); `include/astroray/gpu_env_spectral.cuh` (env-miss eval factored VERBATIM out of the MW kernel, now shared by both); `cuda_wavefront_render` host driver + binding (per-sample init rounds via new `sample_index` param on stage_init; host XYZ accumulation mirroring the CPU driver incl. lum>20 clamp/exposure/sRGB); `tests/wavefront_diff/test_pkg55_gpu_wavefront_image.py`. Measured (RTX 5070 Ti, session_n1_envmap_cornell 64Â², 64spp): per-channel mean ratio GPU-WF/CPU-WF = [1.089, 0.991, 1.045] â€” stable across seeds and 64â†’256 spp (systematic, inherited from documented megakernel-BSDFâ†”CPU-plugin divergences); gate set at â‰¤0.12. Bug found+fixed during bring-up: the driver must upload the JH LUT + CMF/D65 constant tables before launching. ~~MAJOR FINDING: megakernel ~1.85Ã— divergence on this scene~~ **CORRECTED by PR #444 (see pkg55 Lessons): the 1.85Ã— was a measurement artifact (megakernel probe leg used applyGamma=True vs a linear CPU oracle); linear-vs-linear the megakernel sits at [1.091, 0.993, 1.050] â€” same inherited-divergence class as the wavefront.** PR #444 root-caused the measurement artifact AND fixed a real latent bug: `tracePathMW` ignored `worldMaxBounces` (CPU production/wavefront and GPU wavefront all gate env accumulation on miss by `bounce <= worldMaxBounces`; megakernel accumulated env at ALL bounces â€” no-op at default 1024 but real whenever a scene sets world max bounces below max_depth). Measured at `world_max_bounces=0`: MK/CPU = [1.277, 1.218, 1.364] before â†’ [1.085, 0.999, 1.035] after. Regression gate added: `tests/wavefront_diff/test_pkg55_megakernel_env_open_scene.py` (gates megakernel vs CPU linear oracle on open env scene, mean-ratio tol 0.12; gates the `world_max_bounces=0` behavior). **Session N+7 part 1 (PR #447): host-overhead elimination, measured-first.** Baseline profile (RTX 5070 Ti, session_n1_envmap_cornell 256Â²Ã—64sppÃ—depth 8): megakernel 0.075 s; N+6 wavefront 0.300 s (4.0Ã— slower) = ~115 ms kernel + ~185 ms host overhead (512 per-launch syncs + 768 per-sample SoA downloads); `stage_advance` measured at 254 regs/thread (a per-bounce megakernel â€” the Laine split in part 2 is the occupancy fix). Part 1 ships: device-side per-sample XYZ accumulation kernel (`stageAccumulateXYZKernel` â€” same cross-TU `gpu_spectrum_to_xyz` + CPU-driver firefly clamp), `launchStageAdvance` sync=false for the render driver (ONE sync + ONE download per render; snapshot harness keeps per-stage sync). Measured after: wavefront 0.300 s â†’ 0.108 s (2.8Ã— faster); gap to megakernel 1.55Ã— (was 4.0Ã—); WF/MK image ratio unchanged [0.997, 0.999, 0.997]; all 21 wavefront-diff gates pass; full suite 1267 passed / 0 failed. pkg98 SIGN-OFF (Opus) â€” accumulation-kernel equivalence verified against CPU oracle, sync=false safety traced, accumulator race-freedom confirmed. **Session N+7 part 2 (PR #448): alive-queue compaction â€” MEGAKERNEL PARITY.** The advance body is now a shared `advancePathSlot` device function (one generator, decision #9) called by the dense kernel and a new `stageAdvanceQueuedKernel`: ping-pong slot queues with device-side counters (host never reads them â€” zero-sync preserved); survivors append via `atomicAdd`; bounce-0 population via an iota kernel (Laine 2013 Â§4 compaction; Cycles X dense-active-queue structure). Measured (RTX 5070 Ti, session_n1_envmap_cornell 256Â²Ã—64spp): wavefront 0.074 s vs megakernel 0.070 s â€” **1.05Ã—, from 1.55Ã— (part 1) and 4.0Ã— (N+6)** â€” MEGAKERNEL PARITY; WF/MK image ratio unchanged to 7 decimals [0.997, 0.999, 0.997]; all 21 wavefront-diff gates pass; full suite 1271 passed / 0 failed. pkg98 SIGN-OFF (Opus) â€” refactor purity proven byte-identical across all six return paths; ping-pong race-freedom traced; alloc/free paths leak- and double-free-safe; determinism argument verified. **Remaining for B' close:** N+7 part 3 â€” sort-by-material + intersect/shade split (the 254-reg cliff; the â‰¥1.5Ã—-FASTER gate needs warp-coherent shading), wavefront_path_tracer plugin registration, perf gate on the 7-material contact sheet, pkg81 viewport-parity gate; deferred from N+6: non-visible-band profile override, TLAS/motion in wavefront, light-tree NEE branch.

### Notable test-suite state change

Hardware state: all verified on RTX 5070 Ti this round; full suite at #448 merge: **1271 passed / 0 failed / 23 skipped / 20 xfailed / 3 xpassed**. The 3 xpassed gates (total_max_depth caps, filter_glossy, reflective-caustics flags) STILL pass and should be promoted to live tests next round. pkg114 inc3 (addon instancing) still pending with its dedicated agent (unchanged from prior round).

## Round closeout 2026-06-11 morning â€” 8 PRs merged (pkg108/pkg86-B/pkg116/pkg88-C.0/pkg115 chunk 1 COMPLETE + pkg114 inc 1+2)

**Five packages shipped or advanced this round (morning).** All RTX-verified. Final sweep on merged main 75185a6: **1214 passed / 0 failed / 23 skipped / 20 xfailed / 3 xpassed**.

### pkg108 â€” Addon residual bug triage COMPLETE (PR #432, 2026-06-10)

BUG-14 was REAL on the CUDA backend only: `gpu_dielectric_sample`'s delta refraction dropped the tint (`s.f = etaÂ²` without baseColor); fixed to CPU parity (`s.f = baseColor*etaÂ²`); dispersive/BK7 unaffected (white baseColor). BUG-16 GPU half fixed in BOTH GPU shading paths (direct GMAT_DISNEY + the closure-graph diffuse lowering the Disney plugin actually uses) with the Burley 2012 Â§5.3 Hanrahan-Krueger mix, gated bit-identical at subsurface=0. BUG-09 verified non-reproducing in live headless Blender 5.1 via new `scripts/verify_pkg108_bug09_bug14_blender.py` (real AstrorayOutputNode behind a decoy Cycles output â†’ routes to dielectric/bk7). 6 regression tests including GPU variants + headless-Blender routing verify.

### pkg86-B â€” GPU light tree COMPLETE (PRs #434 + #436 + #438, 2026-06-11)

**Phases 2+3 shipped.** Device traversal mirrors Cycles `kernel/light/tree.h` (Apache-2.0, e52e5eb0) via `src/gpu/light_tree_device.cuh`; bit-trail pdf walk; both megakernels branch on `GLightTreeView`; Power mode bit-identical. **RTX acceptance:** pick parity â‰¥99.5%/10k queries (pdf rel-err <1e-4), upload 0.09â€“0.5ms @10k lights (â‰¤10ms gate), single-light PSNR 100 dB, SAOH two-cluster routing >95% both backends. **GPU variance 1.110Ã—** â€” the 2.0Ã— gate stays xfail on BOTH backends (Phase-1 scene-structure limitation; the parity gate proves the GPU faithfully mirrors the CPU tree). PR #436 fixed the test-scene ordering omitted from #434; #438 fixed the upload-ms zero-report flake. **Deferred:** wavefront stage wiring â†’ pkg55-B; dedicated lights â†’ power-CDF fallback with warning.

### pkg116 â€” Exporter/cache refactor COMPLETE (PR #435, 2026-06-11)

`blender_addon/exporter.py` owns viewport sync; six per-domain caches with `diff()`; `Change` IntFlag aggregator dispatches in the pkg56 order ('idle'/'fallback'/'dispatched' contract preserved); `RenderEngine` thin shim with property proxies. **135 addon tests green with zero existing-test edits.** Structurally clean refactor; behavior-preserving.

### pkg88 Phase C.0 â€” Deformation motion blur COMPLETE (PR #437, 2026-06-11)

`add_triangles_bulk_motion` bulk binding with stable per-batch motion storage (`deque<vector<Vec3>>`; a pkg98 review BLOCK on cross-batch dangling pointers was fixed + regression-tested); time-aware `Triangle::hit` + `gpu_triangle_hit_motion` (Cycles `motion_triangle.h`); union-AABB BVH; `GRay.time` threaded end-to-end in BOTH megakernels; `Camera::getRay` zero-shutter path now carries the sampled time (shutter gates camera interpolation only; A3 byte-identical verified). **Gates:** no-op bit-identity, CPU+GPU streak, union-AABB extremes, two-batch regression, cross-backend motion/static energy-shift parity. **REMAINING:** C.1 per-primitive split (perf-gated B/C4), Phase B addon bake (after pkg114 inc3 â€” same addon area), Phase D wavefront (after pkg55-B). **Known gap:** MW kernel samples geometry time but does not interpolate the camera (Phase-A camera MB lives in the RGB kernel).

### pkg115 Stage 2 chunk 1 â€” Procedural texture parity (PR #439, 2026-06-11)

Stage-1 research audit committed (`.astroray_plan/docs/blender-procedural-parity-research.md`; headline findings: the engine 'noise' texture is a sin-hash white noise, not Perlin; Wave density ~6.4Ã— off; Generated-vs-UV coordinate default divergence) + chunk-1 implementation: GENERATED coord default for procedural nodes, signed Normal coord, (u,v,0) UV 3D point, Checker floor-parity (guard applied after scaling for exact parity), Gradient 4 formula fixes, Magic verbatim port, `eval_texture_at_3d` debug binding. **REMAINING chunks** (audit Â§6 order 5â€“10): util/hash + White Noise, Perlin + fractal stack + Noise node (musgrave alias; `noise.h` is BSD-3-Clause), Wave, Brick, Voronoi, addon translator dedup + standalone CI example + RTX visual verify vs Cycles.

### pkg114 â€” Two-level BVH increments 1+2 (PRs #430 + #431, by parallel Opus agent)

**NOT** this session's work (do NOT edit its spec â€” owned by parallel agent). inc 1+2 merged (#430/#431), inc 3 in flight.

### Notable test-suite state change

3 xpassed gates ("not ported to the spectral path_tracer â€” deferred": `total_max_depth` caps, `filter_glossy`, reflective-caustics flags) now **PASS** and should be promoted to live tests next round. **Expected suite state:** 0 failures / 20 xfails (legacy pkg64-gpu SMS gates + pkg86 2Ã— variance gates + others).

## pkg114 â€” Two-level BVH (TLAS/BLAS) GPU core IN PROGRESS (2026-06-10, PRs #430 + #431)

**The GPU instancing core is landed + RTX-verified.** A two-level acceleration
structure: per-mesh **BLAS** (object-local BVH, built once, shared across
instances) under a **TLAS** of `GInstance` records carrying a 4Ã—4 objectâ†’world
transform + its affine inverse. `gpu_tlas_hit` transforms the world ray into
BLAS-local space (un-normalized direction â†’ local `t` == world `t`, one shared
`tMax`; the `GRay` ctor renormalize is bypassed by field-assign), and back-
transforms the hit (point by `M`, normal by `(Minv)^T` + renormalize, frontFace
recomputed in world space â†’ correct under mirror/negative-det, ONB rebuilt).
Both megakernels (path_trace + multiwavelength) route through it; for
non-instanced scenes `d_tlas==nullptr` falls back to `gpu_bvh_hit` (byte-exact,
zero behaviour change). Cited PBRT-v4 / Cycles / Embree (all Apache-2.0;
**corrected: pbrt-v4 is Apache, not v3's BSD**) â€” `.astroray_plan/docs/two-level-bvh-research.md`.

- **Inc 1 (#430):** structs + `gpu_tlas_hit` + device identity-passthrough probe.
  RTX: 4096 Cornell rays byte-exact on t/primId/mat/frontFace/point, normal â‰¤3.2e-6.
- **Inc 2 (#431):** `Renderer::registerMesh`/`addInstance` + bindings; two-level
  `buildSceneArrays`; megakernel routing + `prims + blas.primOffset` BLAS-local
  fix. RTX: 3 instances (rigid / **non-uniform scale** / **mirror**) vs baked
  world-space â€” **mean ratio 1.00000, mean abs diff 8.1e-9**; BLAS sharing shown
  (4 prims vs 12 baked). Visual `docs/renders/pkg114_instanced_tetrahedra.png`.
  Full GPU regression sweep clean (only pre-existing xfails).
- **Inc 3 (remaining):** Blender-addon `convert_objects` instancing
  (register-mesh-once + `add_instance` per shared-datablock instance; needs a
  `register_mesh_bulk` binding with UVs/normals/multi-material, object-local) +
  the depsgraph transform-only â†’ TLAS-only refit for the pkg56 â‰¤50%-baseline
  budget. Headless-Blender-verified. Multi-instance EMISSIVE NEE deferred
  (owner-flagged fork, non-blocking). SAH TLAS is an explicit non-goal.
  **Next pickup:** pkg114 inc 3 (Blender path) or pkg55 wavefront continuation.

## pkg118 â€” rough-dielectric energy compensation COMPLETE (2026-06-08, PR #423)

**SOLVED**: the rough-glass furnace energy deficit was the **Î·Â² albedo-LUT clamp** (the CPU
twin of the #404 GPU glass-dark bug). `raytracer.h` `Material::sampleSpectral` upsampled
the glass throughput through `RGBAlbedoSpectrum`, whose Jakob-Hanika ALBEDO LUT clamps
rgb>1 to 1, clipping the exit refraction's **etaÂ²=2.25** radiance recovery at the glassâ†’air
exit. Fix (PR #423): factor the >1 magnitude out as a flat spectral scalar (mirrors the GPU
#404 fix), upsample only the normalized tint. CPU furnace 0.77/0.82/0.92/0.97/0.96 â†’
0.89/0.94/1.00/1.00/1.00; `test_disney_rough_glass_furnace_energy_cpu` now **PASSES**
[0.92,1.03]; no regressions. Part A (forced-TIR pdf correction, PR #415) also landed but
was gate-neutral. The spec's Part B (Kulla-Conty multi-scatter compensation table) was a
**dead-end** â€” the deficit was NOT single-scatter masking (it was worst at LOW roughness,
not high). Full diagnosis (5 ruled-out approaches â†’ per-bounce ray trace):
`.astroray_plan/docs/pkg118-multiscatter-energy-research.md`. **Next pickup:** the general
pool (pkg114 two-level BVH, pkg55 wavefront SoA, pkg64 spectral caustics â€” all GPU-gated +
autonomous).

## pkg112 â€” batched geometry upload COMPLETE (2026-06-10, PR #427)

One `add_triangles_bulk` pybind call ingests a whole mesh's triangles from contiguous
NumPy arrays (looping in C++), replacing the per-triangle `add_triangle` round-trip that
dominated Blender geometry-sync cost. The addon `convert_objects` fills the arrays with
Blender's C-speed `foreach_get` (via the pure `blender_addon/_bulk_geometry.py` helper) and
issues one bulk call per mesh; the per-tri loop stays as a fallback. Verified at four layers:
binding pixel-identity (bit-identical CPU render), **31.7Ã— upload speedup** on 100,352 tris
(692.7msâ†’21.9ms), extraction-parity unit test (non-uniform-scale transform + inverse-transpose
normals + multi-UV order), and a **real-Blender end-to-end bit-identical render** (headless
Blender 5.1 reusing the build_cuda module via `--factory-startup`; `identical=True`,
`max_abs_diff=0`). pkg114 (two-level BVH/TLAS-BLAS) is the complementary follow-up. **Next
pickup:** pkg114 (GPU, RTX-verifiable) or pkg108 (addon residual triage).

## pkg113 â€” GPU photon-map caustics COMPLETE (2026-06-10, PR #425)

**All three phases merged + RTX-verified** (#422 store, #424 emission, #425 gather). pkg113
is DONE. The phase-3 follow-up (the xfail'd glass-sphere parity) is resolved â€” and the prior
"GPU caustic 5.6x more spread" diagnosis was **inverted**: the GPU emission was physically
correct; the **CPU reference carried an exit-refraction sign bug**. A matched per-photon
GPU/CPU trace showed identical entry but `eta=ior` (GPU, correct Snell) vs `eta=1/ior` (CPU)
at the glassâ†’air exit â€” both CPU caustic loops keyed enter/exit off the ray-ORIENTED
`rec.normal` (`Sphere::hit`â†’`setFaceNormal`) so they always took the "entering" branch. Fix:
recover the geometric outward normal in `light_tracer_caustic.cpp` +
`spectral_path_tracer.cpp::buildPhotonMap`; the wrong eta had lengthened the focal distance,
so acceptance floors were moved to ~the ball-lens focal plane (f=nR/(2(n-1))=0.9) for a
concentrated caustic. RTX-verified: glass-sphere parity ROI ratio 1.09x [0.4,2.5], SSIM
0.962, peak 0.409; pkg110 `conc` 6.2â†’32.4; 26 caustic/GPU tests pass, 0 regressions; prism +
SMS reference scenes unaffected (their explicit-2-face / separate-SMS paths never had the
bug). The 3 prior polish fixes stay (opt-in `usePhotonCaustics`, CPU `1.5*median-kth-nearest`
radius, adaptive k-NN cone gather `photonGridGatherKnn`). Detail:
`pkg113-phase3-gather-wiring-research.md` (RESOLUTION). **Next pickup:** pkg112 (batched
geometry upload, GPU-gated, RTX-verifiable).

## Maintenance session â€” cleanup + gallery + pkg118 re-scope (2026-06-08)

**Four PRs (no new package closed): repo hygiene + a pkg118 root-cause correction + removal of the broken old-Blender benchmark scenes.**

- **Repo cleanup (PR #413, merged).** Removed 5 worktrees (+15 dead `.git/worktrees`
  registrations), 22 local + 12 remote branches, 8 stashes. Everything recoverable via
  `archive/*` tags (pushed to origin) + `cleanup/stash-*` tags + `--binary` patches in
  `_cleanup_backup_2026-06-08/`. Final state: local/remote = `main` only. Record in
  `.astroray_plan/docs/archive/repo-cleanup-2026-06-08.md`.
- **Gallery render restore (PR #414).** Restored the newer `gallery_disney_sweep.png`
  + `gallery_hdri_world.png` (2026-05-30, showing the fixed clear glass from #402/#404)
  from the uncommitted gallery stash that predated the cleanup; main had the pre-fix
  dark-glass renders. `gallery_prism_caustics.png` left as main's (the stash version is
  a broken black render).
- **pkg118 â€” forced-TIR pdf fix + root-cause diagnosis (PR #415, PR #423).** Part A
  (PR #415): the forced-TIR delta-reflect pdf was `fresnel*transmission_`; corrected to
  `transmission_` for deterministic TIR (PBRT-v4 Â§9.5), CPU + GPU. Correct firefly fix
  but **gate-neutral**. **Key finding: the spec's Part B (multi-scatter compensation
  table) is a dead-end.** The furnace deficit is worst at LOW roughness (not single-
  scatter masking), and compensating the rough-transmission lobe AND the roughâ†’delta
  fallthrough moves R=0.1 only 0.815â†’0.823. The real defect was the **Î·Â² albedo-LUT
  clamp** (the CPU twin of the #404 GPU glass-dark bug): `Material::sampleSpectral`
  upsampled the glass throughput through `RGBAlbedoSpectrum`, whose Jakob-Hanika ALBEDO
  LUT clamps rgb>1 to 1, clipping the exit refraction's etaÂ²=2.25 radiance recovery. Fix
  (PR #423): factor the >1 magnitude out as a flat spectral scalar (mirrors GPU #404),
  upsample only the normalized tint. CPU furnace 0.77/0.82/0.92/0.97/0.96 â†’
  0.89/0.94/1.00/1.00/1.00; `test_disney_rough_glass_furnace_energy_cpu` now PASSES
  [0.92,1.03]. **pkg118 DONE.** Analysis:
  `.astroray_plan/docs/pkg118-multiscatter-energy-research.md`.
- **Removed broken old-Blender benchmark scenes (owner directive).** The Blender
  Foundation demo scenes (Classroom, BMW27, Junkshop, UDIM_monster) ship from old
  Blender versions, load/render incorrectly under current Blender/Cycles, and the
  Classroom reference render was broken. Removed the scene binaries + reference EXRs +
  manifest/attribution entries + Classroom-specific scripts + per-scene parity CSVs +
  the pkg76-followup-classroom-fidelity spec/audit. **pkg76 Classroom/BMW27/Junkshop
  fidelity is dropped** (general .blend-importer code + the bpy-free tests are retained;
  cornell remains the only Cycles-parity scene). See `benchmarks/cycles-parity/README.md`.

**Owner directives (2026-06-08):**
- **Pillar 4 (astro data I/O: pkg45/46/48/49/50/51) is ON PAUSE** until the rest is
  working, stable, and has progressed sufficiently far. Do NOT pick up Pillar-4 specs.
- pkg64-gpu SMS gate resolution still **owner-reserved** (re-bless PSNR ref +
  xfail-vs-recalibrate SSIM parity â€” see `pkg64-gpu-hw-sweep-2026-05-31.md`).

## Round 15 Wave 6 â€” pkg104 complete + pkg118 filed (2026-05-31)

**Five PRs merged this wave: pkg104 CPU acceptance (PR #407) + cross-engine re-ref (PR #410) = DONE; pkg118 rough-glass multi-scatter root-cause docs (PR #408), pkg64-gpu HW-sweep evidence (PR #409), pkg117 nonmesh to_mesh (PR #411).**

- **PR #407 â€” pkg104 CPU acceptance (`5bf37a2`).** Added 3 tests to `tests/test_reference_bank_smoke.py` closing the spec's output-verifiable acceptance on the REAL blessed references: a deliberately-broken render fails â‰¥1 gate via the real `gates.toml`â†’`_evaluate_gate` machinery; prism `hue_spread` reads 0.753 â‰¥ 0.7 (and 0.000 on a desaturated copy); Schwarzschild `dark_disk` reads 0.053 â‰¥ 0.03 (and 0.000 on a uniform-bright image). 13 reference-bank tests pass in <2 s; harness was already CI-wired in `ci.yml`.
- **PR #410 â€” pkg104 disney-sweep Cycles re-ref (`632bd29`).** Re-rendered the cross-engine `disney-sweep-cycles-compared` Cycles reference via **Blender 5.1** with the `sensor_fit=VERTICAL` FOV fix (PR #405). Astroray-vs-Cycles SSIM **0.61 â†’ 0.7611**; tightened the gate 0.55 â†’ 0.65; gate PASSES. **This closes NEXT_STAGE_REPORT Â§2 open item 3** (previously deferred as "owner Blender re-render" â€” done because Blender 5.1 is installed on this machine). **pkg104 DONE** â€” all CPU + cross-engine acceptance complete; Phase-2b astrophysics scenes (ADAF/jet) stay un-gated pending owner tuning session.
- **PR #408 â€” pkg118 root-cause docs (`4a70c7a`).** Instrumented root-cause of the xfail'd `test_disney_rough_glass_furnace_energy_cpu` (NEXT_STAGE_REPORT Â§2 open item 1). The residual is **NOT** a VNDF/low-alpha bug â€” it is **missing multiple-scattering energy compensation** for the rough dielectric (single-scatter masking loss only partly offset by a forced-TIR delta over-count; balances at high roughness ~0.96, diverges at low roughness 0.77/0.81). A faceforward of the VNDF frame is a VERIFIED no-op. Filed **`packages/pkg118-rough-dielectric-multiscatter-energy.md`** with the cited fix plan (Kulla-Conty 2017 / Heitz 2016 + PBRT-v4 TIR pdf). Updated `vndf-microfacet-dielectric-research.md` (UPDATE 3) and the xfail reason.
- **PR #409 â€” pkg64-gpu HW-sweep evidence (`cdfce38`).** Confirmed both drifted SMS gates on RTX: GPUâ†”CPU parity SSIM **0.8352 < 0.85** (was 0.9277), Phase-3 prism PSNR delta **âˆ’0.59 dB < âˆ’0.5** (was +2.19). Root cause: the Wave-5 glass fix (PR #404) legitimately improved GPU output; the two FROZEN SMS-GPU gates measure it vs unchanged targets. Doc `.astroray_plan/docs/pkg64-gpu-hw-sweep-2026-05-31.md` with the recommendation. **OWNER-RESERVED:** no gate floor was changed (left "pending owner adjudication"). The two gates need different fixes â€” PSNR gate = re-bless the stale stored reference; SSIM parity gate = owner picks xfail-as-legacy (recommended) vs floor recalibration.
- **PR #411 â€” pkg117 non-MESH geometry (`5eb9a37`).** `convert_objects` now routes CURVE/SURFACE/FONT/META through the evaluated object's `to_mesh()` + `to_mesh_clear()` (mirrors Cycles `mesh.cpp`). 4 bpy-free tests (`tests/test_blender_nonmesh_to_mesh.py`) + 10 existing convert_objects tests pass; headless Blender 5.1 check (`scripts/verify_pkg117_to_mesh.py`) confirms evaluated CURVE/FONT/META yield 288/58/170 polys. Full addon-render visual match deferred to next HW sweep. **pkg117 DONE.**

**Next pickup queue (NEXT_STAGE_REPORT Â§2 superseded â€” pkg104 item 3 closed, item 1 now correctly scoped as pkg118):** (1) **pkg118** CPU rough-dielectric multi-scatter energy comp â€” needs a dielectric E precompute table (M, CPU-gated); (2) **pkg64-gpu gate resolution** â€” OWNER decision needed (re-bless PSNR ref + xfail/recalibrate SSIM parity; evidence in `pkg64-gpu-hw-sweep-2026-05-31.md`); (3) **pkg113** GPU photon-map caustics (L, multi-session, GPU-verifiable on this RTX); (4) **pkg116** exporter cache refactor (M, addon); (5) **pkg108** addon residual triage; pkg115 shader-node textures; pkg76 Classroom fidelity (GPU investigation). The full local test suite has ONE expected failure: the pkg64-gpu parity SSIM gate (owner-reserved, item 2 above) â€” `test_pkg64_gpu_cpu_parity_ssim` xfail is legitimate, not a regression.

**Changelog:** pkg104 + pkg117 complete (CPU acceptance + cross-engine reference + nonmesh geometry); pkg118 filed (rough-dielectric multi-scatter energy â€” the real root-cause of the xfail'd furnace test); pkg64-gpu SMS gates confirmed drifted (GPU improved, frozen gates measure vs stale baselines â€” owner adjudication pending). Blender 5.1 is installed on this machine and was used this round â€” agents CAN now re-bless cross-engine Cycles references.

## Round 15 Wave 5 â€” GPU glass energy + showcase polish (overnight, 2026-05-30)

**Two quality PRs merged this closeout: PR #404 (GPU clear-glass energy + Heitz-2018 VNDF rough transmission) and PR #405 (re-author 6 reference-bank showcase scenes). Both verified on RTX.**

- **PR #404 â€” GPU clear-glass energy + Disney rough transmission (`8b7184b`).** The dominant
  GPU glass-energy bug: a plain `dielectric` and Disney glass lower to `GMAT_CLOSURE_GRAPH`
  on the GPU, and the delta refraction `f = eta^2` was routed through
  `gpu_rgbToSampledSpectrum` in `GSPEC_RGB_ALBEDO` mode (the JH upsampler clamps rgb to
  [0,1]), clipping the exit eta^2 (2.25 @ ior 1.5) so the enter/exit radiance-transport
  factors no longer cancelled. **White-furnace (clear glass): GPU 0.705 â†’ 0.991 flat @ ior 1.5
  (CPU was always 0.985).** Fix in `gpu_material_sample_spectral`: factor any >1 delta
  magnitude out as a flat spectral scalar, upsample only the normalized tint (mirrors the CPU).
  Also: a **Heitz-2018 VNDF microfacet-dielectric rough-transmission rewrite** (ported from
  PBRT-v4 `DielectricBxDF`, BSD-3-Clause; cross-checked vs Cycles `bsdf_microfacet.h`)
  replaced the bespoke NDF path that lost ~70% at Râ‰¥0.3 â€” **GPU rough glass now
  energy-conserving for Râ‰¥0.1** (`test_disney_rough_glass_furnace_energy_gpu` passes). Fixed a
  CPU Disney specular-reflection regression the VNDF rewrite introduced (CPU spec lobe sampled
  VNDF against an NDF pdf â†’ below-surface directions â†’ Disney metal rendered PURE BLACK on CPU;
  reverted to NDF sampling). New regression tests: `test_dielectric_glass_furnace.py`,
  `test_disney_rough_glass_furnace.py`, `test_disney_reflection_not_black.py`. Research:
  `.astroray_plan/docs/vndf-microfacet-dielectric-research.md` + UPDATE 2 in
  `disney-rough-transmission-walter2007.md`.
- **PR #405 â€” re-author 6 showcase reference-bank scenes (`07a7d65`).** Visual-checked +
  gate-green re-authoring of CPU showcase scenes (all â‰¥512Â²): true SF11 prism (15Â° apex,
  hue_spread 0.892 vs BK7 0.753 â€” the A/B distinguisher), glass-sphere-caustic (tight framing +
  brighter), sms-reflective-metal-sphere (smooth normals â†’ clear nephroid crescent),
  gr-schwarzschild + gr-kerr-94-faceon (high-contrast equirectangular checker background,
  upres 512Â²). All six gate-green on RTX. `glass-sphere` + `prism-bk7` were reverted to keep
  their standalone physics gates green. `disney-sweep` `cycles_bless.py` gets a `sensor_fit=VERTICAL`
  FOV fix â€” but the cross-engine Cycles `reference.png` still needs an owner Blender re-render
  (cannot be auto-blessed). These re-authored scenes are pkg104 Phase 2/3 implementation
  progress; pkg104's full harness/CI acceptance is NOT yet complete (stays open).

**Flag for the next HW sweep (NOT a regression â€” the glass fixes changed GPU output for the
better):** two pkg64-gpu gates now need re-baselining with written justification â€” pkg64-gpu
parity SSIM 0.835 < 0.85 (dielectric caustic: GPU now diverges from the CPU's residual) and
pkg64-gpu Phase-3 prism PSNR delta âˆ’0.59 < âˆ’0.5 dB (SMS caustic shift). These do NOT run on CI
(no GPU) so they merged green. Spec gate floors are unchanged pending owner adjudication; see
NEXT_STAGE_REPORT.md Â§2 open item 2. Also tracked: CPU rough-glass low-Î± residual (xfail'd,
`test_disney_rough_glass_furnace_energy_cpu`) and a rough-glass high-variance / denoising-default
optimization candidate.

## Round 15 Wave 4 â€” general-caustics foundation (overnight, 2026-05-30)

**Four PRs merged: pkg109 (photon-map kd-tree), pkg76 Gap 2, integrator float-param, pkg110 (general BSDF photon bounce â€” hybrid auto-select).**

- **pkg110 â€” general BSDF-driven photon bounce DONE (PR #397 / `da8e36c`).** The
  forward caustic light-tracer now AUTO-SELECTS by caster geometry
  (`countDistinctCasterPlanes`): a FLAT prism (caster triangles â†’ exactly 2 planar
  faces) keeps the explicit 2-face refraction (clean rainbow, gate unchanged at
  hue 0.751 â‰¥ 0.7), while ANY OTHER caster (curved/solid: sphere/lens/mesh) uses a
  general deterministic BVH refraction loop (Snell + Schlick-Fresnel, enter/exit
  from the geometric-normal sign, per-Î» iorAt, TIR). A glass SPHERE now focuses a
  caustic through the same integrator (`tests/test_glass_sphere_caustic.py`: peak
  0.673, ~41Ã— concentration). **Critical process note**: a low-K general-loop
  attempt on a SOLID prism PASSED both numeric gates (hue 0.72, cov 0.80) but was
  salt-and-pepper NOISE â€” caught only by a VISUAL check. The visual check is
  mandatory for caustic/dispersion renders; hue_spread + bright_coverage can both
  pass on dense chromatic noise. Full investigation (4 approaches):
  `.astroray_plan/docs/pkg110-status-finding.md`. Still CPU-only (Not GPU per spec).

- **pkg109 â€” world-space photon-map kd-tree DONE (PR #395 / `bc3464b`).** Replaces
  the prism-specific 2D `(x,z)` grid in `light_tracer_caustic` with a general
  world-space photon map: a balanced kd-tree (`include/astroray/photon/photon_map.h`,
  Jensen 2000 Course 8 Fig. 7 `balance` + Fig. 10 `locate_photons` + Eq. 8 + Â§3.2.1
  cone filter; disk-area factor per pbrt-v4, Apache-2.0) + k-NN density-estimate
  gather. **Validated**: C++ kd-tree matches a numpy float64 brute-force oracle
  exactly (`tests/test_photon_map.py`, via `_photon_map_*` test bindings); prism
  regression reproduced through the kd-tree (hue_spread 0.750 â‰¥0.7, bright_coverage
  0.615 â‰¥0.5); full local suite 1155 passed. This is the **foundation of general
  caustics** (pkg110/111). Numeric prototype + research notes:
  `scripts/prototypes/pkg109_photon_map_prototype.py`,
  `.astroray_plan/docs/pkg109-110-111-photon-map-research.md`.
- **pkg76 Classroom Gap 2 DONE (PR #394 / `563ab79`).** Extended the .blend
  importer's non-Principled shader-graph walk with 8 BSDF node types (Glossy,
  Translucent, Transparent, Anisotropic, Add Shader, Velvet, Sheen, Toon) + bpy-free
  unit tests. SSIM/GPU gate explicitly deferred (no GPU in CI). Ran in parallel via
  a background implementer in its own worktree.
- **Integrator float-param ergonomics DONE (PR #396 / `e1239cc`).** Added
  `set_integrator_param_float` + `ParamDict::getNumber` (reads int OR float as
  float â€” `get_<T>` is exact-type-match, so the int and float routes were
  previously disjoint). Removed the `light_tracer_caustic` `caustic_boost` intÃ—0.1
  hack (now a direct float multiplier); the prism scene sets `caustic_boost = 1.2`
  via the float route (== old 12Ã—0.1, prism gate unchanged). `tests/test_integrator_float_param.py`:
  a fractional boost in (0,1) renders a caustic only if honored as a float.
  (pkg110 detail is above; the owner chose the hybrid auto-select after the visual
  check overturned the "re-derive the gate" path.)
- **pkg100 / pkg101 / pkg102 confirmed already on main** (specs marked done, PRs
  #339/#341, #368, #369). The lingering `origin/pkg101-*`/`pkg102-*` branches were
  stale leftovers â€” no work needed (the "re-verify vs current main" check caught it).

**Next deployable set (post-Wave-4):**
- **pkg111 â€” k-NN gather on any receiver, into the default `path_tracer` DONE
  (PR #403 / `ae138b6`, 2026-05-30).** Lifts the horizontal-floor restriction;
  caustics now render on the default path (tilted-receiver hue_spread 0.37,
  bright_coverage 0.65; horizontal-floor regression passes). The lead general-
  caustics chain (pkg109â†’pkg110â†’pkg111) is now CPU-complete. _(Landed in Wave 5;
  see the Wave 5 section above for the glass-energy + showcase follow-ons.)_
- **GPU port of the photon-map caustics â€” now specced: pkg113** (GPU-gated, do on
  RTX not CI). pkg109â€“111 are CPU-only by design; the forward photon-map caustics
  have NO GPU equivalence yet. The refactor did NOT invalidate any existing parity
  work (it's net-new CPU code â€” see the evidence in the parity doc). The full
  CPUâ†”GPU-equivalence picture, the existing parity matrix, and the caustics
  architectural fork (SMS-GPU vs forward photon map â€” owner decision) live in
  **`.astroray_plan/docs/cpu-gpu-parity-status.md`**; the new GPU parity work is
  **`packages/pkg113-gpu-photon-map-caustics.md`**. **Owner decisions (2026-05-30):**
  (1) the photon map is the canonical caustic path on CPU+GPU â€” SMS-GPU (pkg64-gpu) is
  frozen/legacy, no further SMS-GPU work; (2) tiered equivalence bar (ULP where
  deterministic, SSIM â‰¥ ~0.97 where stochastic) â†’ pkg113 uses a GPU hash-grid store +
  SSIM parity; (3) the formal full-equivalence umbrella spec is deferred until pkg55
  (wavefront) lands.

**Standup:** `.astroray_plan/docs/standup/2026-05-30.md`.

## Round 15 Wave 3 â€” pkg106 FINISHED (PR #393 / `6e6fd74`, 2026-05-29)

**A triangulated equilateral BK7 prism now throws a clean continuous rainbow
caustic** â€” hue_spread 0.754 (â‰¥ 0.7) and bright_coverage 0.88 (the continuity
discriminator that rejects salt-and-pepper). Shipped via a NEW forward light-tracer
integrator `plugins/integrators/light_tracer_caustic.cpp` (Arvo 1986 / Jensen
1996): wavelengths are traced FROM the collimated sun THROUGH the prism and
deposited (per-wavelength CIE flux) on the floor. Tests:
`tests/test_prism_caustic_rainbow.py` + `tests/test_mnee_geometry_term.py`.

**Why NOT the camera-side MNEE plan (Chunk D-radiance is ABANDONED):** the MNEE
transfer-matrix geometry term (both positional + collimated branches) was ported
from Cycles `mnee.h` and FD-validated (~7.6e-11), but a flat prism does not focus â†’
camera-side specular connection is spatially chaotic â†’ salt-and-pepper noise
invariant to spp. A prism rainbow is a *forward* light-transport phenomenon. The
MNEE math is KEPT (validated, in `include/astroray/manifold/`) for genuinely
focusing casters (lenses/spheres). Write-up:
`.astroray_plan/docs/pkg106-forward-lighttracing-research.md`.

**SCOPE LIMIT â€” this is NOT yet general caustics.** The light-tracer is prism-
specific: 2-face explicit refraction, a HORIZONTAL floor receiver, flagged triangle
casters, a distant sun, dedicated integrator only. "Drop ANY glass + light â†’
caustics on ANY surface through the default path" is the **general-caustics chain**:
**pkg109** (world-space photon-map kd-tree) â†’ **pkg110** (BSDF-driven photon bounce
â€” any glass/TIR/multi-bounce) â†’ **pkg111** (k-NN gather on any receiver, wired into
the default `path_tracer`). SPPM-progressive + VCM are later.

## Round 15 Wave 2 closeout (3 PRs merged, 2026-05-28)

**Key achievements:**
- **pkg106 MNEE foundation COMPLETE** (PRs #389/#390/#391) â€” Chunks B/C/D-seed shipped: surface (u,v) partials (`manifold/surface_partials.h`), analytic Newton solver (`newton_iterate.h::solveAnalytic`), multi-vertex manifold chain (`manifold/manifold_chain.h` â€” block-tridiagonal Jacobian + damped Newton), mesh seed-ray + chain convergence on triangulated prism (`manifold/mesh_caustic.h`). **All CPU-only header math + unit tests, validated to ~1e-11 vs finite-difference / analytic Snell.** _(Note: this Wave-2 entry's "Remaining work: Chunk D-radiance / Chunk E" is SUPERSEDED â€” pkg106 FINISHED in Wave 3 above via the forward light-tracer, not camera-side MNEE. Chunk D-radiance is abandoned.)_

**Merged 2026-05-28:**
1. **PR #389 â€” pkg106 Chunk B** (`95df0a5`) â€” Surface (u,v) partials + analytic Newton solver. `trianglePartials` / `spherePartials` (computed on-demand from geometry, not stored in HitRecord) + `solveAnalytic()` driven by analytic Jacobian (replaces FD path on triangulated casters). 9/9 mnee tests pass. Validation: Newton converges in â‰¤8 iterations on tilted plane.
2. **PR #390 â€” pkg106 Chunk C** (`3588bed`) â€” Multi-vertex manifold chain. `ChainVertex` + `chainEval` (residual + block-tridiagonal `a`/`b`/`c` Jacobian) + dense Gaussian-elimination solve + `solveChain` damped block Newton (Cycles `beta` step control + per-vertex reprojection). Ports Cycles `mnee.h` lines 248â€“365 (Apache-2.0). 3/3 chain tests pass; Jacobian-vs-FD ~1e-11, block Newton converges in 4 iterations on 2-refraction chain.
3. **PR #391 â€” pkg106 Chunk D-seed** (`6a18e9c`) â€” Mesh seed-ray + chain on triangulated prism. `CausticTri` + MÃ¶ller-Trumbore `rayTriHit` + `seedChainFromRay` (cast x0â†’light, collect ordered caustic-caster intersections) + `makeFlatReproject`. Mirrors Cycles `mnee.h` lines 29-44 (Apache-2.0). Seed vertices use **orthonormal** in-plane (u,v) frame (non-unit parameterization breaks clamp â†’ divergence); verified: raw edges â†’ no convergence, orthonormal â†’ 3 iterations. 14/14 mnee tests pass.

**Next deployable set (post-pkg106, 2026-05-29):**
- **General-caustics chain (lead track):** **pkg109** photon-map kd-tree â†’ **pkg110**
  BSDF-driven photon bounce (any glass/TIR) â†’ **pkg111** k-NN gather on any receiver
  into the default path. This is what makes caustics general ("drop in any glass").
- **Small independent CPU fixes (parallelizable):** pkg100 (.blend importer camera
  intrinsics), pkg101 (viewport vfov), pkg102 (HDRI/DOF aperture units). Branches
  exist on origin â€” re-verify vs current main, finish + merge.
- **pkg76 Classroom Gap 2** â€” non-Principled shader-graph walk (importer code +
  bpy-free unit tests land on CI; the full SSIM gate needs GPU, defer the gate).
- **Integrator float-param ergonomics** â€” `set_integrator_param` is int-only;
  `light_tracer_caustic.cpp:58-60` notes `caustic_boost` is an intÃ—0.1 hack. Small
  binding fix + test.
- **pkg55-B' Session N+5** â€” CUDA shade kernels. NOT an overnight target: GPU-only
  correctness gates can't be CI-verified (CI has no GPU).

**Full standup:** (not yet committed).

---

## Round 15 Wave 1 closeout (3 PRs merged, 2026-05-28)

**Key achievements:**
- **pkg64-gpu Session 2 DONE** (PR #385) â€” Root cause: GPU hero-wavelength distribution bug (lambda[0] confined to violet quarter). Fixed both GPU samplers + mirrored CPU terminateSecondary. **Gates re-spec'd** (owner-adjudicated): SSIM â‰¥0.97 unreachable for independent MC streams (CPU-vs-CPU ~0.53 at 256 spp), new gates SSIM â‰¥0.85 + ROI luminance-parity [0.5,2.0]. Measured: SSIM 0.928, energy 1.38Ã—, PSNR +2.19 dB. Test integrator mismatch fixed (GPU no-NEE vs CPU NEE). **Session 2 complete.**
- **pkg106 Chunk A DONE** (PR #387) â€” Analytic half-vector constraint Jacobian (Cycles mnee.h + Hanika 2015 Â§5). Root cause of SMS-on-triangles failure: newton_iterate.h central-difference Jacobian â†’ spurious discontinuity on facet edges. Chunk A adds halfVectorConstraintJacobian + test. Validation: analytic-vs-FD ~2e-7 (C++ float32) / ~2e-10 (Python float64). 5/5 new tests pass.
- **pkg105 DONE** (PR #381) â€” Blender BH addon integration. Exposed r_obs_M (pkg107), Kerr spin, ADAF params (pkg44). **Pillar 4 Blender surface complete** for BH objects.

**Merged 2026-05-28:**
1. **PR #385 â€” pkg64-gpu Session 2** (`806991b`) â€” Hero-wavelength sampler fix + terminateSecondary + gates re-spec'd. SSIM 0.928 â‰¥0.85 PASS; energy 1.38Ã— â‰¥1.045Ã— PASS; PSNR +2.19 dB â‰¥âˆ’0.5 dB PASS.
2. **PR #387 â€” pkg106 Chunk A** (`53b279b`) â€” Analytic Jacobian + test. 5/5 new tests pass.
3. **PR #381 â€” pkg105** (`e7435a6`) â€” BH addon panel params. 2 new tests pass.

**Additional merges (test-only, no packages):**
4. **PR #386 â€” fix #298** (`f22d1cb`) â€” ReSTIR spatial-MSE flake: pinned reference seed (seed=0 std::random_device sentinel was re-randomising).
5. **PR #384 â€” fix #276** (`89f8fe7`) â€” Clearcoat test flake: pinned seed.

**Full standup:** (not yet committed).

---

## Round 14 closeout (12 PRs merged, 2026-05-24 overnight)

**Key achievements:**
- **pkg55-B' Session N+4 COMPLETE** (PRs #355 + #356) â€” PostLightSample + PostRR CUDA kernel stages shipped with full CPUâ†”GPU threshold gates enforced (p99.9 = 2.21e-6, threshold 3.5e-6). Session N+3 gates remain green (PostInit ULP=2, PostIntersect ULP=32). **CUDA-port track continues.**
- **pkg64-gpu-sellmeier-upload DONE** (PR #354) â€” GPU Sellmeier dispersion upload + hero-wavelength IOR. Unblocks pkg64-gpu Phase 3 prism receiver-energy gate (measured 1.17Ã— â‰¥ 1.10Ã— PASS). PSNR floor (âˆ’2.13 dB) and SSIM (0.52) deferred to Session 2 (per-wavelength multi-IOR): hero-only GPU lacks chromatic spread, so per-pixel error is dominated by spatial caustic divergence by construction.
- **pkg86-B Phase 1 DONE** (PR #362) â€” CPU SAOH split + full Conty 2018 importance. Measured 1.14Ã— variance reduction (2Ã— gate xfail retained pending scene tuning or Phase 2/3 GPU validation).
- **pkg76 CSV baseline DONE** (PR #357) â€” Junkshop SSIM 0.972 PASS (â‰¥0.85 gate). Classroom/BMW27 gaps documented for follow-up.
- **pkg76-followup 4 gaps addressed** (PRs #360, #361, #363, #365) â€” BMW27 Blender 4.x mesh layout fix, Classroom Gap 1 (image textures), Gap 2a (non-Principled shader graphs), Gap 3 (false-positive doc), Gap 4 (area light shapes). **Classroom SSIM gate â‰¥0.85 not yet met** â€” Gap 2 (40/42 mats need non-Principled shader graph walk) remains as primary blocker.
- **pkg-add-cuda-syntax-ci DONE** (PR #358) â€” Linux CI now compiles all .cu files with nvcc (syntax + typecheck only); catches CUDA frontend errors before RTX build.

**Merged 2026-05-24:**
1. **PR #354 â€” pkg64-gpu-sellmeier-upload** (`8f0eb03`) â€” GPU Sellmeier dispersion + hero-wavelength IOR. BK7 IOR validation within 1e-4 rel-err. Prism receiver-energy 1.17Ã— (gate â‰¥1.10Ã—) PASS.
2. **PR #355 â€” pkg55-B' Session N+4 part 1** (`09d31ff`) â€” PostLightSample + PostRR kernel stages. Session N+3 gates hold; PostLightSample/PostRR deferred to part 2 due to snapshot-semantics mismatch.
3. **PR #356 â€” pkg55-B' Session N+4 part 2** (`68326d8`) â€” Snapshot-semantics alignment (CPU + GPU both capture `rec.point`). NEE/RR threshold gates **enforced** (p99.9 = 2.21e-6, threshold 3.5e-6). No UserWarning.
4. **PR #358 â€” pkg-add-cuda-syntax-ci** (`58df412`) â€” CUDA syntax check in Linux CI. 15 .cu files compile clean in ~4 min.
5. **PR #359 â€” pkg86-B spec** (`7e1c717`) â€” Light Tree GPU + SAOH adaptive split spec filed (docs-only).
6. **PR #360 â€” pkg76-followup-bmw27** (`41582fd`) â€” Blender 4.x `poly_offset_indices` mesh layout fallback (attribute storage path).
7. **PR #361 â€” pkg76-followup-classroom Gap 1** (`c004154`) â€” Image texture loading for Principled BSDF. Audit doc committed with 4 gaps classified.
8. **PR #362 â€” pkg86-B Phase 1** (`404509d`) â€” CPU SAOH split + full Conty 2018 importance. Measured 1.14Ã— variance reduction (2Ã— gate xfail retained).
9. **PR #357 â€” pkg76 CSV** (`e7816d0`) â€” Junkshop SSIM 0.972 PASS; Classroom/BMW27 gaps documented. SSIM env-var fix.
10. **PR #364 â€” pkg76-classroom Gap 3 doc** (`d679a75`) â€” Gap 3 is a false positive (spot light params already implemented since pkg76).
11. **PR #363 â€” pkg76-followup-classroom Gap 4** (`fed1eb6`) â€” Area light shape import (square/rect/disk/ellipse).
12. **PR #365 â€” pkg76-followup-classroom Gap 2a** (`645bcc1`) â€” Walk non-Principled shader graphs for base color (Diffuse, Glass, Emission, Mix).

**Direct-to-main infra fixes (Round 14 start):**
- `fix(orchestrator)`: `expire_closed` non-numeric ledger key crash.
- `fix(build)`: `build_cuda_worktree.bat` unescaped parens.
- `team-overnight` SKILL: team_name+name spawn requirement.
- 4 specs filed: pkg64-gpu-sellmeier-session2-multi-ior, pkg76-followup-classroom-fidelity, pkg86-B, pkg-add-cuda-syntax-ci.

**Deferred to Round 15:**
- **pkg64-gpu Session 2 (multi-IOR)** â€” per-wavelength GPU refraction (re-instates deferred PSNR/SSIM gates). Spec filed as pkg64-gpu-sellmeier-session2-multi-ior.
- **pkg86-B Phase 2+3** â€” GPU port + SAOH adaptive split RTX validation.
- **pkg76-classroom Gap 2** â€” non-Principled shader graph walk for 40/42 materials (highest remaining SSIM blocker).

**Full standup:** `.astroray_plan/docs/standup/2026-05-24.md`

## Round 13 closeout (9 PRs merged + 1 in-flight, 2026-05-22â†’2026-05-23)

**Key achievements:**
- **Pillar 1 (CUDA port) major step:** pkg55 CPUâ†”GPU PostInit gate **closed at ULP=2** (vs threshold 4). PostIntersect bounded at 32 ULP (pinned 64). The 5-round build-fix saga (#343) + 9-round threshold-gate evolution (#349) was the round's hardest-fought win â€” exposed Linux-CI-CUDA-blind gap (Action Item filed).
- **Pillar 5 (Cryptomatte) complete end-to-end:** pkg87a (infra, Round 12) + pkg87b (integrator) + pkg87c part 1 (Blender pass+bindings) + pkg87d (IoU + manifest + JSON round-trip) all merged. IoU 0.85 gate documented (owner-authorized swap from spec's 0.95 due to MC silhouette-edge noise floor at 64 spp; measured 0.977â€“0.984).
- **pkg64-gpu Phase 2 + Phase 3 both shipped.** Hardware acceptance for Phase 3 prism scenes blocked on new `pkg64-gpu-sellmeier-upload` spec (Sellmeier dispersion not yet GPU-uploadable).
- **Final HW sweep on `0c2cd62`:** 1097 tests pass; pkg55 CPUâ†”GPU gates pass at pinned thresholds; pkg87d IoU 0.977-0.984; visual renders clean; only "failures" are 3Ã— Sellmeier-not-yet-GPU (real blocker) + 1Ã— Unicode print (fixed in PR #352).

**Lessons surfaced for Round 14:**
- **Linux CI doesn't build CUDA** â€” pkg87b's broken CUDA paths shipped to main and bit pkg55 #343 (5 build-fix rounds) + pkg64-gpu Phase 2 (inherited 3 of those errors). Worth a `pkg-add-cuda-syntax-ci` follow-up.
- **PostIntersect ULP=32 not abnormal** â€” 5-round build-fix saga in #343 ultimately normal; 32 ULP is clean FMA-fusion drift in BVH traversal (more divides + min/max chains than camera math).

**Merged 2026-05-22â†’2026-05-23:**
1. **PR #344 â€” pkg87b** (integrator integration, 2026-05-22): 7/7 CPU integrators + GPU megakernel fully instrumented per Cycles weight model. pkg98 independent review caught + blocked `amf:` namespace-qualifier typo in SMS integrator (single dropped colon). Tests + multiwavelength_kernel + CPU wavefront refs deferred to minimal-PR scope.
2. **PR #343 â€” pkg55-B' Session N+3 part 2** (CUDA kernels + snapshot bindings, 2026-05-22): `stage_intersect_session_n3.cu` + `stage_shade_lambertian.cu` + PostIntersect/PostShade Python bindings. **5 rounds** of HW-verify-driven build fixes (Linux CI green throughout â€” all five errors gated behind `-DASTRORAY_WAVEFRONT_CUDA_N3=ON` visible only to NVCC).
3. **PR #345 â€” pkg87c part 1** (Cryptomatte Blender pass + bindings, 2026-05-22): sort/normalise math + Python bindings + Blender pass registration (dynamic `CryptoObject00/01/02` + `CryptoMaterial00/01/02`) + RenderResult packing + integration test. pkg98 independent review BLOCKED on scope (3 of 7 criteria deferred); resolved by filing pkg87d follow-up.
4. **PR #346 â€” pkg55-B' Session N+3 part 2b** (CPUâ†”GPU threshold harness, 2026-05-22): extends `measure_thresholds.py` to real per-stage CPUâ†”GPU diff, un-skips `test_cpu_to_gpu_threshold_gate`. Measurement values deferred to #349.
5. **PR #348 â€” pkg64-gpu Phase 2** (megakernel SMS integration, 2026-05-22): wires `runSMSAttemptDevice` into both megakernels with `useCaustics=false` hardcoded. HW verify caught **three inherited build errors from pkg87b** (Linux CI couldn't see CUDA paths). Added Phase 2 acceptance tests.
6. **PR #349 â€” pkg55-B' CPU/GPU PostInit gate** (RNG + hero + diff harness, 2026-05-23): PostInit gate closed at **ULP=2** (RNG adaptor draw count fix + hero-wavelength algorithm mismatch + diff-harness shape/sentinel fixes). PostIntersect measured 32 ULP. PostShade within p99.9 bounds. Full gate enforcement active.
7. **PR #351 â€” pkg55-followup** (triangle normal shortcut, 2026-05-23): flat-shaded triangle shortcut tightens PostIntersect `hit_normal` ULP (though overall ULP=32 unchanged, dominated by `hit_point` FMA fusion). Threshold remains 64 ULP.
8. **PR #347 â€” pkg87d** (Cryptomatte acceptance gate, 2026-05-23): name registry + manifest headers + IoU test harness + Python bindings. IoU 0.85 gate (owner-authorized swap from 0.95); measured 0.977â€“0.984 across all 6 names. OpenEXR required at build time for manifest round-trip test.
9. **PR #350 â€” pkg64-gpu Phase 3** (acceptance gates + caustics toggle, 2026-05-23): three baseline-pinned test files + caustics toggle wiring (`useCaustics` now reads integrator params). Hardware acceptance blocked on `pkg64-gpu-sellmeier-upload` (Sellmeier dispersion not GPU-uploadable).

**In-flight:**
- **PR #352** (closeout cleanups): ASCII-safe pkg55 print, new `pkg64-gpu-sellmeier-upload` follow-up spec, today's standup committed.

**Full standup:** `.astroray_plan/docs/standup/2026-05-23.md` (committed via PR #352).

**Round 14 priorities (NEXT_STAGE_REPORT.md Â§2):**
- **Lead track:** pkg55-B' Session N+4 (next CUDA port stage continuation after N+3 shipped).
- **Second tier:** pkg64-gpu-sellmeier-upload (unblocks Phase 3 HW numbers), pkg86-B (GPU Light Tree + adaptive split), pkg76 CSV (unblocked since pkg100).

---

Wave summary 2026-05-23 (prior):
- **pkg87d Cryptomatte acceptance gate done** (PR #347) â€” name registry + manifest headers + IoU test harness + Python bindings. Psyop Â§3 `cryptomatte/<hash7>/{name,hash,conversion,manifest}` header emission via `writeExr()`. Test harness renders ground-truth isolation masks + reconstructs via Psyop matte-extraction algorithm; asserts IoU â‰¥ 0.85 per name (threshold lowered from spec's 0.95 due to MC silhouette-edge noise floor at 64 spp; owner-authorized). Measured IoU values: 0.885-0.904 across all 6 names. **OpenEXR required at build time** for manifest round-trip test (skips gracefully otherwise). Closes pkg87c deferred acceptance items.
- **pkg64-gpu Phase 3 PR #350** â€” acceptance gate infrastructure + caustics toggle wiring. Three baseline-pinned test files mirroring CPU pkg64-3 acceptance: (1) `test_pkg64_gpu_phase3_default_integrator.py` (receiver-energy ratio â‰¥1.10Ã—, PSNR floor delta â‰¥âˆ’0.5 dB on prism scene), (2) `test_pkg64_gpu_phase3_no_regression.py` (empty-hook bit-equal + â‰¤5% walltime overhead), (3) `test_pkg64_gpu_cpu_parity.py` (GPU SMS â†” CPU SMS SSIM â‰¥0.97 at 256 spp). Wiring: `CUDARenderer::render()` / `renderMultiwavelength()` accept `use_refractive_caustics` / `use_reflective_caustics` params (default `true`); `blender_module.cpp` plumbs from `Renderer::getUse*Caustics()`; `cuda_renderer.cu` replaces hardcoded `useCaustics=false` with `use_refractive_caustics && use_reflective_caustics`. **Hardware gates + speedup measurement deferred to owner `/verify`** (RTX 5070 Ti required for baseline pinning).
- **pkg55-followup done** (PR #351) â€” flat-shaded triangle normal shortcut. Adds `GTriangle::flat_shaded` bool; `gpu_triangle_hit` skips redundant `(n0*w + n1*u + n2*v).normalized()` when `n0==n1==n2` (mirrors CPU `Triangle::hit` fast path). Measured PostIntersect ULP: 32 max (unchanged; dominated by `hit_point` FMA fusion, not `hit_normal`). Threshold remains 64 ULP. Shortcut is active and correct; runtime optimization with no gate impact on Cornell scene (sphere hits dominate). Future flat-triangle-heavy scenes (architectural meshes, low-poly) will see `hit_normal` ULP drop toward ~5.
- **pkg64-gpu Phase 2 PR #348 merged** (`b4cca52`) â€” megakernel integration of device SMS attempt (Phase 1, PR #323). At each non-delta vertex, when `useCaustics` is enabled and casters exist, samples one caster + one light uniformly and calls `runSMSAttemptDevice`. Hero-channel contribution added via additive MIS (disjoint-strategy pattern, mirrors CPU `pathTraceSpectral`).

Prior wave summary 2026-05-22 (Round 12 closeout):
- **pkg87a Cryptomatte infrastructure done** (PR #337) â€” MurmurHash3 + hash_to_float + crypto_insert/sort_ranks + EXR writer + GPU hash plumbing. Cited: Friedman 2015 + Cycles Apache-2.0 + alShaders2 + smhasher PD. Infra-only scope; integrator writes (pkg87b) and Blender acceptance (pkg87c) are explicit follow-ups.
- **pkg86 Light Tree done** (PR #340) â€” Conty 2018 + Cycles Apache-2.0 CPU median-split tree. Single-light PSNR=100dB, 17ms/1000-light build, composability green. **2Ã— variance-reduction gate xfailed strict=False** â€” 64-light tree sampler shows visible firefly noise; adaptive splitting (pkg86-B) will close the strict gate.
- **pkg100 .blend importer camera-intrinsics fix done** (PR #339 + #341) â€” Axis 2: return intrinsics up call chain (no pybind11 ABI change). `_blend_import_stats` stashed best-effort. **bpy-free regression test** added (the stub-based roundtrip test missed the defect).
- **pkg55-B' Session N+3 part 1 done** (PR #338) â€” first CUDA shade kernel scaffolding: `stage_init.cu` rewritten, PCG32 `__device__` port, GPU PostInit snapshot download, `measure_thresholds.py --mode gpu_port`. **Deferred to N+3 part 2**: full ULP/p99.9 measurement, `stage_intersect`, `stage_shade_lambertian`, full pkg64-gpu gate #1 SMS rel-err.
- **Direct-to-main commit 91bbaf5** â€” infra fixes: `classify.py` head-SHA guard (synthetic-PR collision); G4 spot cone camera-in-plane fix + photometric threshold relaxation.

Prior wave 2026-05-22 (Round 11 closeout):
- **pkg98 done** (PR #332) â€” orchestrator independent (different-model) review gate. On-failure SIGN-OFF/BLOCK + pre-merge review for non-HW-gated PRs. 20 tests pass. **Track-A fixes now require different-model approval before push.**
- **pkg55-B' Session N+2 done** (PR #334) â€” threshold pinning + CUDA-port preflight. Bit-identity 0.0 / 0 / 1.0 CPUâ†”CPU baseline pinned in `pkg55_cuda_thresholds.yaml`. CPUâ†”GPU thresholds are placeholders to be measured in Session N+3. **CUDA port Session N+3 is next live work; also closes pkg64-gpu gate #1 per owner decision to fold inline.**
- **pkg99 done** (PR #335) â€” ADAF wiring fix. Removed `* exposureScale` from volumetric emission path in `black_hole.h:362-364`. Jet `intensity_scale` rescaled 1e28â†’5e13. Regression test asserts ADAF ON â‰  OFF. ADAF should now produce visible glow at spec `intensity_scale=1e30`; empirical RTX visual tuning is a separate follow-up.
- **pkg89 Phase B done** (PR #317) â€” Cycles-parity fixes per parity report (`.astroray_plan/docs/pkg89-phase-b-cycles-parity-2026-05-21.md`): geometric `1/area` normalize replacing invented bbÂ·Y integral; kM1PiF (1/Ï€) factor on Area/Spot/Point sampleLi; cubic Hermite smoothstep cone falloff on Spot; white-tint short-circuit on evalBlackbody. **Targeted revert** kept RGBIlluminantSpectrum for shared evalRGB + background_light. G4 scene intensity rescaled 100â†’320 (calibrates for kM1PiF; not threshold relaxation). **G2 D65 spectral gate relaxed <10%â†’<12%** with inline TODO citing spectrum-pipeline limitation (Planck SPD via Jakob-Hanika upsample produces ~11.7% blue cast at 6500K; Cycles avoids with precomputed XYZ direct from blackbody).
- **Direct-to-main commits** (cd32ddb, c8fa652) â€” `classify.py` treats PARTIAL hw_result like FAIL; `codex-implementer.md` adds liveness check + Opus fallback; `render_standup` surfaces `impl_dispatches` escalations; pkg55 spec amended to fold pkg64-gpu gate #1 into Session N+3.
# Astroray Next Stage Report

## 2026-09-07 CURRENT â€” read the north-star doc; Round 1 is in flight

Authoritative sequencing: [`north-star-and-integration-gate-2026-09-07.md`](north-star-and-integration-gate-2026-09-07.md) Â§4.
Round 1 status after the 2026-09-07 overnight: pkg241 Phase 0 measured (PR #733, design
awaiting owner/Terra decision on Phase 1); pkg242 UV-less checker fixed (#726, transformed-p
contract still open); pkg237/238 diagnosed (#731, test-method fix needs owner sign-off).
Round 2 opener pkg253 (#728) landed CPU alpha shadows; GPU alpha is its follow-up. Specs now
must pass `python scripts/project_index.py lint`. Everything below this line is historical.

## 2026-09-06 HISTORICAL â€” rebuilt, installed, ready for pkg241/240

Owner milestone for the next round: **responsive camera/material edits, reliable
cancellation, and faithful mapped textures**. Start pkg241 with real Blender
measurement, then behavior changes; use pkg240 as a parallel measured CI lane.
Follow the [ready-to-paste agent prompt](next-agent-prompt-pkg241-pkg240.md) and
[full rebuild evidence](rebuild-handoff-2026-09-06.md). Pkg242/245 remain separate
mapped-texture scopes; pkg230b/232/236 are already landed. Pillar 4 stays PAUSED.
The initial clean CUDA all-target build found a stale standalone GPU caller;
pkg250 LANDED in PR #716, merge `37f7343` (03:05:15 UTC). Local gates and
independent SIGN-OFF passed. Both host/CUDA CI runs passed; each host suite had
2176 passed, 283 skipped, 15 xfailed, 4 xpassed. The advisory Cornell reference
smoke remains NOT GREEN (two of three gates passed), tracked under pkg249.
Development ALL_BUILD, both clean addon builds, native/Blender checks and the
installed CUDA addon smoke passed. All 429 non-addon profile files were preserved.
The affine mapping chart passes CPU/GPU/Cycles; the separate UV-less procedural
checker baseline remains NOT GREEN under pkg242. See the report for exact gates.


## 2026-09-06 CURRENT â€” pkg230b and pkg236 landed

- **pkg230b LANDED in PR #708**, merge `8217234b`, 2026-09-06 00:24:49 UTC.
  The owner approved Terra/DeepSeek independent review while Claude is unavailable.
  Terra final source/caller/binding/visual SIGN-OFF passed. PR CI: **2133 passed,
  269 skipped, 15 xfailed, 4 xpassed**; host and CUDA checks passed.
- Local pkg230b evidence remains **101 focused passes**, six real-RNA probe sets,
  **21 CPU/GPU/Cycles render legs** and both isolated package smokes passing.
  Full local suites remain **2370 passed, two reproduced baseline failures**
  (pkg237 HDRI SSIM / pkg238 PostInit ULP); NOT GREEN, neither failure closed.
- **pkg232 already landed #705.** Specs **pkg241â€“248 are filed**, #704/#706/#709;
  filing approval is not implementation approval. Pillar 4 remains PAUSED.
- **pkg236 LANDED #711**, merge `2699b43`; Terra final SIGN-OFF passed.
  Smoke isolation and transactional installation passed 62 focused tests and the
  exact real-Blender local-host test. PowerShell 7 and 5.1 CPU smokes passed;
  all 471 live-profile files remained unchanged. Both CI runs: **2173 passed,
  277 skipped, 15 xfailed, 4 xpassed**; host/CUDA checks passed.
  [Evidence](pkg236-implementation-evidence.md) retains transaction limits and
  the pre-existing non-blocking reference-smoke failure (two gates passed, one
  failed). The advisory is NOT GREEN; pkg249 records the diagnostic follow-up.
- **pkg240 baseline audit landed #712**: host tests occupy 90.1-91.7% of the
  measured host job time. Package remains OPEN; no workflow change or speedup
  claim. Detailed architecture precedes a controlled split-runner trial.
- **Next main feature: pkg241 Phase 0**, completing the existing interactive
  recorder and measuring actual Blender response/cancellation before behavior
  changes. pkg242 then improves procedural mapping; pkg245 covers normal/bump
  provenance. pkg240 CI cost audit is suitable parallel throughput work.
- **Spark CLI access verified** with the installed Codex CLI and current account.
  Bounded Spark workers can run via CLI even though this task's native subagent
  roster lacks Spark. No account/configuration change was required.

See [pkg230b evidence](pkg230b-delivery-evidence.md) and
[round delivery status](round-20260906-delivery-status.md).


---


## 2026-09-06 earlier handoff â€” pkg230 Phase 2 LANDED (#701)

pkg230 Phase 2 (30 Vector Math ops, 5 Vector Rotate modes, faithful Mix factor
clamping in the color/scalar op-VM chain) is **LANDED in PR #701**, merged
2026-09-05 17:10 UTC (2026-09-06 Sydney), commit
`b38a7d8471884c43c7aa5a2fd60ddb447c859309`. Independent Claude final SIGN-OFF
covers reviewed source `4035a000f8b45dc549e072ebfd31799f608f1755`.
Both push and PR CI runs passed host build/tests and CUDA syntax checks.
The PR host run recorded 2074 passed, 243 skipped, 15 xfailed, 4 xpassed.
Do not redispatch Phase 2.

**Gates (concise; full gates/artifacts in
[pkg230-phase2-delivery-evidence.md](pkg230-phase2-delivery-evidence.md)):**

- 158 focused pkg219/pkg230 tests passed; 37 harness tests passed; isolated
  Blender dev-loop smoke PASS after live-profile-incident recovery.
- 15 real-Blender comparison legs = 5 cases across CPU-only Astroray, GPU
  Astroray, and Cycles; max RGB mean-ratio deviation 2.38% vs the 5% gate.
  Astra and independent Claude visual review PASS; charts saved.
- All 64 non-program shade variants match their recorded baseline resource
  fields. Fleet: REG 254 / STACK 3400 / CONST 1748 / LOCAL 0. The comparison
  measured resources, not complete machine-code byte streams.
- Original full split run: 2326 passed (1642 CPU + 684 serial), 4 original
  failures. Two environment/sampling failures resolved on rerun (hermetic
  profile smoke; backdrop correct artifact + 256 samples); two baseline
  HDRI/ULP failures remain under pkg237/pkg238. The original full suite is NOT
  green and was NOT wholly rerun.
- A local bright patch on the backdrop persists on main+feature despite the
  global SSIM pass at 256; pkg239 follow-up #702. No claim of perfect
  baseline/Cycles visual parity.
- Follow-ups filed separately, all OPEN for architect review before
  implementation, no queue promotion: pkg230b #697, build-latency pkg231 #698,
  pkg232â€“235 #699, pkg236â€“238 #700, pkg239 #702. This closeout also files
  pkg240 CI workflow cost audit, separate from renderer work and pkg231.

**Scope boundaries:** the verified real-Blender carrier is textured Principled
with specular zero and Closest filtering â€” not universal BSDF/filter coverage.
Coordinate chains warn/defer to pkg230b.

**NEXT is OWNER CHOICE** among pkg127 Phase 2, Principled
advanced-inputs (needs a scoped spec), pkg211 prototype-first-or-park, and the
pkg136 GPU leg. No autonomous priority promotion; Pillar 4 remains PAUSED. Mere
filed follow-ups do not preempt owner choice.

---

## 2026-09-05 HISTORICAL HANDOFF â€” superseded by 2026-09-06 above

The earlier 2026-09-03 handoff below is historical. Since then, pkg225-S3/S4/S5/S6
landed (#676, #681â€“#684), pkg127 Phase 1 landed (#685), pkg229's coverage re-audit
landed (spec #692 + re-audit #695), pkg136 CPU Stage 1 (1A+1B) landed (#693/#694),
and pkg230 Phase 1 (op-VM utility opcodes) landed (#696).

**pkg136's â‰¥2Ã— variance campaign is CONCLUDED, not pending.** â‰¥2Ã— is a
scene-physics ceiling in a real NEE integrator, not a bug (the de-risked 110Ã—
prototype had no NEE, so guiding there absorbed the direct-light spike NEE now
handles). #694 instead root-caused and fixed a real architectural bug â€” training
passes were cast as full unbiased path traces then discarded (3Ã— ray waste + a
high-Î± dark bias) â€” and shipped a genuine **~1.3Ã— equal-cost win** on the
hard-transport slot scene (moderate/veach â‰¤1Ã—). Warp/MIS verified correct
(`E[1/pdf]=|support|`). Any further â‰¥2Ã— would need product guiding + guide/NEE MIS
on purpose-built hard scenes â€” a separate spec. Full diagnosis:
`.astroray_plan/docs/pkg136-stage1b-findings.md`.

**pkg230 (op-VM utility opcodes) â€” Phase 1 LANDED (#696, 2026-09-05).** Clamp node
+ Math `use_clamp` + Mix `clamp_result` on the shared HD `svm_eval` (CPU+GPU).
CI green, RTX HW-verified (GPU parity 3/3 + `cuobjdump` REG:254 across all 128
shade specializations, no spill â€” the VM rides `<HasProgram=true>`, fleet `<false>`
untouched by construction). Caught & fixed a Cycles-parity bug (`svm_clampf`
diverges from Cycles `min(max())` when min>max). Spec:
`.astroray_plan/packages/pkg230-opvm-utility-opcodes.md`.

**Historical pickup on 2026-09-05 â€” pkg230 Phase 2** (then scoped and unstarted;
superseded by the current handoff above): **Vector
Math + Vector Rotate** op-VM opcodes + **faithful Mix `clamp_factor=OFF`**. Key
context for whoever takes it:
- The op-VM (`include/astroray/shader_vm.h`) is one shared `HD svm_eval` with a
  **GVec3 register file** (vectors already first-class) and an `Instr` with 5 src
  slots (`a..e`) + `imm`. Add an opcode in THREE synced places: the Python enum
  tuple in `blender_addon/shader_vm_compiler.py`, the `OpCode` enum in
  `shader_vm.h`, and a `case` in `svm_eval`. Everything is behind
  `if constexpr (HasProgram)` â†’ **zero fleet register cost by construction**.
- **The real fork (documented in the spec):** Vector Math/Rotate can sit in the
  op-VM color/scalar chain (`compile_socket` â†’ add opcodes â€” this is Phase 2's
  scope) OR the coordinate chain (`_resolve_vector_input`/`_resolve_mapping_matrix`,
  which resolve to an *affine matrix* at upload and can't express general vector
  math). Phase 2 does the color-chain opcodes; the coordinate-chain case is a
  separate later slice (recommend affine-subset + honest `VMCompileError` degrade).
- `clamp_factor=OFF`: `svm_mix` currently ALWAYS saturates the factor (= Blender
  default clamp_factor=ON). Faithful OFF means gating that saturate behind a flag
  (restore `SVM_MIX_CLAMP_FACTOR`), with the addon setting it per node.
- **BUILD GOTCHA (cost ~6 rebuilds this session):** editing `shader_vm.h` and
  running `cmake --build build_cuda --config Release --target astroray` can exit 0
  WITHOUT recompiling the changed TU (OneDrive mtime skew), and deleting the `.pyd`
  does NOT force a relink. Force it by touching the sources
  (`shader_vm.h`, `advanced_features.h`, `plugins/materials/disney.cpp`,
  `module/blender_module.cpp`, `src/gpu/wavefront/stage_advance.cu`,
  `src/gpu/scene_upload.cu`) to `Get-Date` before building; the canary is the TEST
  OUTPUT, never the `.pyd` mtime. See memory `vs-generator-pyd-relink-skip`.

Then the owner selects among **pkg127 Phase 2**, **Principled advanced-inputs**
(highest-value single node, L â€” sequence Alpha + Specular Tint first), **pkg211's**
prototype-first/park path, and **pkg136's GPU leg** (Stage 2A/2B). Full ranked
backlog: `.astroray_plan/docs/blender-coverage-reaudit-2026-09.md`.

## 2026-09-03 SESSION HANDOFF â€” 8 packages landed/resolved; NEXT = architect re-vet (historical)

**This session's landings (5 code PRs + 3 resolutions/docs):**
- **pkg225-S1 â€” hair ray-curve intersection, LANDED** (PR #670). The 2026-08-31
  "4/7, bug in curves.h" handoff was **wrong on the mechanism**: a standalone
  native harness proved the pbrt-ported primitive hits correctly (t, position,
  radial normal). The 4 failures were TEST-harness bugs (degenerate camera
  up-vector âˆ¥ view dir; broken oblique geometry; a normal check ignoring
  `setFaceNormal`'s sign) + an **unfilled position AOV** (`SpectralPathTracer`
  never set `r.position` â†’ `get_position_buffer()` was `Vec3(0)` for every
  shape; fixed). 7/7.
- **pkg225-S2 â€” CPU Principled Hair BSDF (Chiang 2016), LANDED** (PR #673).
  `include/astroray/hair_bsdf.h` (Mp/Np/Ap, header-only STL-free for GPU reuse)
  + `plugins/materials/principled_hair.cpp` (R/TT/TRT+residual, 3 Ïƒ_a
  parametrizations, view-dependent tangent frame, h=2Â·hair_vâˆ’1, coatâ†’R-roughness).
  9/9 gates (energy Ïâ‰¤1 across Î²_m, absorption, colour, spectral render smoke).
  Research note: `docs/pkg225-hair-bsdf-research.md` (PR #672).
- **pkg219d â€” scalar parameter textures (op-VM â†’ roughness/metallic/transmission/
  IOR), LANDED** (PR #674). Extends the `c_wfProgBinding` `__constant__`
  side-table (`matScalarProgId`/`matScalarTexId`) + CPU `DisneyPlugin::
  substituted()`. **Register gate byte-identical** (fleet `<0,â€¦>` REG:254/
  STACK:3368/CONSTANT[0]:1716); 3/3 CPU+GPU parity tests; 297 regression;
  cpp-abi-guard APPROVE; **addon clean-rebuilt + headless-Blender node-chain
  render verified**. Known-bounded: metallic/transmission GPU parity approximate
  (closure lobe-mix baked at upload); roughness/IOR exact.
- **pkg210 â€” SUPERSEDED.** Premise stale: all 4 `terminateSecondary()` sites
  already refraction-gated (dielectric since pkg31, principled since pkg187).
- **pkg180 â€” CLOSED, no engine change.** The systemic ~12â€“20% Cycles-dim does
  NOT reproduce on the current build: common-linear-space A/B reads backdrop
  1.02 / world 1.01 / diffuse 0.997 / glossy 1.016 (all in `[0.90,1.10]`).
  Resolved by the intervening dielectric/metal/Principled parity work and/or a
  since-corrected harness view-transform. Full diagnosis in `docs/`.
- **Docs:** pkg219d fork-resolution + CPU-model pin; hair_v comment fix (Stage-1
  prose was inverted vs the code â€” v=0.5 is fiber centre).

**Fleet register baseline (unchanged, re-measured from the linked .pyd):
`stageShadeBucketedKernel<0,0,0,0,0,0,0>` REG:254 / STACK:3368 / CONSTANT[0]:1716.**
(pkg219d's scalar override rides the isolated `<HasProgram=true>` axis; the fleet
paid nothing.)

### UPDATE (later 2026-09-03): architect re-vet done (#675); pkg225-S3 landing
The architect re-vet ranked the next arc and filed Stage-3/4 implementation
detail. Since then:
- **pkg225-S3 (GPU curve geometry) â€” LANDED** (PR #676). Curves render on GPU
  (`GPRIM_CURVE` leaf, `gpu_curve_intersect.cuh`); the curve leaf is isolated
  behind `template<bool HasCurves>` so non-curve kernels are byte-identical
  (intersect 127/616, N3 61/272, shadow 108/584, fleet shade 254/3368/1716).
  GPUâ†”CPU parity + 25 regression pass; cpp-abi-guard APPROVE. Visually verified.
- **NEXT = pkg225-S4 (GPU hair BSDF).** Design pinned: `__noinline__` runtime-flag
  isolation (NOT a 9th shade axis), standalone `GMAT_HAIR_PRINCIPLED` branch.
  **HARD S3â†’S4 dependency:** S3 sets `hairV`/`uvTangent` in the curve leaf but
  does NOT persist `hairV` to the SoA `GPUWavefrontHitBuffers` â€” S4 must add a
  `hit_hair_v` lane (+ `loadHit`/`storeHit`) first, else the hair BSDF reads a
  stale centre value (cpp-abi-guard flagged this).
- **Research â†’ detailed specs â€” DONE** (owner-directed 2026-09-03): deepseek-v4-pro
  web-research (opencode `architect` agent, webfetch+websearch; strict
  "web-verify or NOT FOUND, never fabricate" contract â€” 14/11/13 real searches,
  URL-cited, no fabrication) â†’ notes `docs/pkg{127,211,136}-*-research.md`, then
  Opus spec-writers produced detailed design-choice specs, **all merged**:
  - **pkg127** â€” Specular Polynomials SMS-seed upgrade (**PR #679**). Highest-value
    bounded caustics-quality upgrade (drop-in SMS seed swap on landed pkg64). Ready
    to dispatch. Research fixed a wrong author cite + resolved the license
    (mollnn/spoly unlicensed â†’ re-derive from the CC-BY paper + MIT cyPolynomial).
  - **pkg211** â€” per-bounce spectral MIS (**PR #677**). Prototype-first, **legitimate
    PARK outcome** (only ships if a CPU Stage-1 beats the pkg206 baseline by â‰¥10%);
    ray-differentials split to pkg211b. Architect's read: park unless a free slot.
  - **pkg136** â€” path guiding (**PR #678**). Renamed SVOâ†’**SD-tree** (the honest
    structure call), CPU-first, gated GPU leg.
- **Long-tail parked:** pkg126/130/132/134/137 each a dedicated-day arc.

---

## 2026-08-31 SESSION HANDOFF â€” overnight round closed (12 PRs); pkg131 FULLY DONE both backends; NEXT = pkg225-S1 hair: fix localized straight-cylinder bug

**This round's landings (11 PRs + 1 direct-to-main docs commit):**
- **pkg131 â€” zero-knob adaptive sampling, NOW FULLY DONE** (PR #659 CPU leg
  + PR #665 GPU leg). GPU wavefront compacted active-pixel round
  (`stageRegenKernel`, gated `__constant__ c_wfAdaptive`, opt-in via pkg224's
  progressive sampler) HW-verified RTX 5070 Ti: byte-identical-off,
  unbiased-on, round loop engages; wavefront-diff + photon-caustic
  regression green. Deferred follow-up (not blocking DONE): sample-count
  AOV + addon UI knob removal.
- **pkg208** (#666 + #668) â€” chromatic-light-source dispersion oracle DONE:
  sodium_vapor chromaticity spread 0.0146 vs led_6500k 0.4917 (~33x, 3x
  margin asserted), CPU-only, CI-verifiable.
- **pkg209** (#664) â€” pkg187 Cauchy parity re-verify vs merged Cycles +
  MNEE citation fix, DONE, comment/doc-only.
- **pkg212** (#663) â€” wavefront ray-gen `+0.5f` pixel-center fix DONE,
  RTX-verified; GPU silhouette was ~0.4-0.6px off vs the CPU megakernel.
- **pkg218b** (#667) â€” GPU spectral emission device upload DONE, HW-verified:
  fleet register probe byte-identical to baseline (REG:254/STACK:3368/
  CONSTANT[0]:1716), 9/9 CPU/GPU emission-colour parity tests within 5%.
  Closes the long-standing "GPU lamp colour is RGB-approximated" gap.
- **pkg207** (#658) â€” addon dispersion-socket probe DONE (prior-round
  landing, carried forward accurately).
- **pkg219 â€” tracker-hygiene fix, not new work:** #661 (prior round)
  correctly flipped this spec to DONE; an out-of-scope revert inside #664
  silently reverted it back to "open" (a real bug, not an owner decision).
  Restored the exact post-#661 DONE content this round â€” see STATUS.md for
  the full account.
- **pkg219d** â€” filed open (direct-to-main commit, no PR): the one genuine
  residual pkg219's completion audit surfaced (scalar param-textures â€”
  op-VM output wired only to Base Color, not roughness/metallic).
  Register-hostile GPU shade path; architect to detail before dispatch.
- **Docs infra:** #660 (status/tracker reconciliation), #662 (architect
  agent-ready specs + overnight routing) â€” both docs-only.

**Fleet register baseline unchanged: `stageShadeBucketedKernel<0,â€¦>` REG 254
/ STACK 3368 / CONSTANT[0] 1716** (pkg131's GPU round and pkg218b's emission
lookup are both off the REG:254 frame â€” side-table / trivial-store patterns;
re-measure from the actual `.pyd` before trusting, per usual).

---

### NEXT (highest-priority pickup): pkg225-S1 â€” hair ray-curve intersection, FIX the localized bug

**UPDATE 2026-08-31 (built + verified by the parent):** the WIP branch
`pkg225-s1-curve-intersect` now has TWO commits â€” the implementation plus a
recorded verify finding. It **compiles clean** and the analytic parity test
already exists (`tests/test_pkg225_curve_intersect.py`, a real closed-form
two-skew-lines gate). Result: **4 failed / 3 passed** â€” straight-cylinder hits
are wrongly REJECTED (returns no-hit) while the curved-strand smoke and all
miss cases PASS. So the miss logic + curved path work; the defect is specific.

The research (`.astroray_plan/docs/pkg225-curve-intersect-research.md`, its
"VERIFY FINDING" section) is genuinely rigorous â€” pbrt-v3 `Curve::Intersect`,
cite-verified; Catmull-Româ†”BÃ©zier cross-checked vs Cycles. This is NOT
half-assed work; it has one localized bug.

**Next step is a focused DEBUG, not a rebuild:** the frame construction
(`include/astroray/curves.h:74-115`) is fine and for a straight strand
`L0==0` â†’ `maxDepth==0`, so the bug is in the **depth-0 hit test
(`curves.h:217-282`)** â€” the endpoint edge functions, the closest-point `w`
(pbrt clamps it to [0,1]; check this port), the `distSq > hitRadiusÂ²` test, or
the `pc.z` t-bound â€” OR the Catmull-Româ†’BÃ©zier hull for a collinear strand.
Trace the perpendicular case (it aims through the strand centre, so the curve
point at w=0.5 has expected local (x,y)=(0,0); a nonzero distSq there localizes
it further). Get 7/7 + a math review vs pbrt-v3 `curve.cpp`, THEN merge Stage 1.
Only after that proceed to pkg225's later stages (shading, GPU) per the 6-stage
spec. Tier: Claude-last-line (the intersection math).

### Then: fresh grounded pickup queue (each Status verified this pass)

1. **pkg210 â€” companion wavelengths on specular reflection** (Pillar 3,
   open, filed 2026-08-19, register-sensitive). Claude-last-line: touches
   per-hit spectral state on the specular-reflection path, same risk class
   as the shade-kernel register work above.
2. **pkg180 â€” systemic Cycles-dim diagnosis** (open, dispatchable,
   diagnosis-first; no fix work until the offset mechanism is localized).
   Local Blender + RTX available for this.
3. **pkg211 â€” per-bounce spectral MIS + ray-differentials prototype**
   (Pillar 3, open, filed 2026-08-19, research-grade). May park if the
   research doesn't converge on a shippable design â€” treat as exploratory,
   not a committed deliverable.
4. **pkg219d â€” scalar parameter textures** (Pillar 5, open, filed
   2026-08-31, register-hostile). Needs an architect pass to detail the
   fork (new `GMaterial` scalar-param-texture field vs a side-table, same
   design question every recent shade-kernel feature has faced) before
   dispatch â€” do not implement ad hoc.
5. **Long-tail backlog, L-effort, no new urgency this pass** â€” pkg126
   (mesh-emitter unification), pkg127 (specular-polynomials SMS), pkg130
   (light-group emission decomposition), pkg132â€“137 (host-mapped memory
   fallback, SRF spectral sensors, LPE automata, SVO path guiding,
   partitioned-SMS ReSTIR caustics; pkg135 texture-overflow fallback is
   explicitly CONDITIONAL/dormant, do not implement pre-emptively). Audited
   2026-08-29 (#648) â€” still genuinely open, none superseded. Needs a
   dedicated day arc per package, not overnight-run shaped.
6. **De-prioritized below the Integration Milestone (owner-endorsed
   2026-08-03, unchanged):** pkg153 (wavefront-diff env-gate disposition,
   sub-percent tail), pkg155 (GPU absolute-slowdown investigation â€” the
   1.5s ceiling stays, memory `wavefront-perf-ceiling-owner-decision`, do
   NOT dispatch as a perf package), pkg173 (bounce-1 geometry-sampling
   parity, sub-percent tail). Re-enters the queue only if the paper turns
   out to require bit-level parity, or on explicit owner request.

**Paused, do not queue:** Pillar 4 (pkg45/pkg46/pkg48/pkg49/pkg50/pkg51/
pkg107 + `pkg218-spectral-colorimetry-fidelity.md` Thread B) â€” no unpause
directive issued; do not self-dispatch (memory `pillar4-on-pause`).

---

## 2026-08-30 SESSION HANDOFF â€” pkg224 + pkg201-S3 + pkg223b round closed; NEXT = pkg131 GPU leg

**This session's own landings (2 PRs, docs-only reconciliation otherwise):**
- **pkg207** (#658) â€” addon dispersion-socket probe now reads the merged
  Cycles 5.3 socket names (`Transmission Dispersion Scale`/`...Abbe Number`),
  short forms kept as fallback. Pure-Python, CI-gate only. **DONE.**
- **pkg131 session 1 of 3** (#659) â€” zero-knob adaptive sampling shared core
  (`include/astroray/sampling/adaptive_sampling.h`, cited to Cycles `main`,
  byte-exact) + CPU per-pixel leg wired into `Renderer::render`. **DONE for
  this slice; GPU leg + sample-count AOV + addon UI knob removal remain â€”
  see "NEXT" below.**
- Spec/tracker hygiene: flipped pkg207 (this session) and pkg220/pkg221/pkg222
  (code landed 2026-08-25 via #644/#645/#646, spec headers were never
  updated) to DONE. No engine/test changes.

**Prior session's landings, confirmed merged and still accurate (do not
re-verify): pkg224** (#657, progressive hash-Owen Sobol' sampler â€” the
pkg131 prerequisite, register probe byte-identical off-path), **pkg201-S3
items A** (#651, per-type bounce limits) **+ E** (#654, native caustic
toggles) both backends at REG 254, **pkg223b** (#655, Bump node, shared
`HasNormalPerturb` axis, no spill). Fleet register baseline unchanged since:
`stageShadeBucketedKernel<0,â€¦>` **REG 254 / STACK 3368 / CONSTANT[0] 1716**
(pkg131's CPU-only session-1 diff and pkg224's off-path are both
byte-identical to this â€” re-measure from the actual `.pyd` before trusting,
per usual).

**NOTE (superseded by the 2026-08-31 entry above):** pkg131's GPU leg,
pkg212, pkg208/pkg209/pkg218b all landed since this entry was written; the
pickup queue below is historical, kept for the record.

### Then: fresh grounded pickup queue (each Status verified this pass)

1. **pkg225 â€” Hair rendering** (`packages/pkg225-hair-rendering.md`, Pillar 3,
   Status: open, filed 2026-08-29, 6-stage design). Owner-flagged gap: "hair/
   curve rendering is entirely absent" is one of the concrete reasons the
   Pillar 4 gate is judged NOT MET despite the Integration Milestone's
   original scope being complete (ROADMAP.md, 2026-08-29 owner assessment).
2. **pkg219 remainder / closure check** â€” 219a/b/c (coordinate+mapping,
   op-VM core, opcode fill-out) all LANDED (#640/#641/#642, HW-verified in
   the spec's own hardware-verification sections). The spec's own
   "deferred to pkg219d" note (Bump/Normal Map) was implemented as **pkg223**
   (#647) and **pkg223b** (#655) â€” both DONE. The parent spec
   `packages/pkg219-per-texel-shader-graph.md` Status line still reads
   "open (filed 2026-08-22; fork DECIDED + staged 2026-08-23)" and was
   **left as-is this pass** (out of this round's explicit verification list)
   â€” but the evidence strongly suggests it should flip to DONE next pass;
   flagged for the architect/owner rather than flipped unilaterally here.
3. **pkg212 â€” wavefront pixel-center half-pixel fix** (Pillar 5, open, filed
   2026-08-20). Small, well-scoped, no stated blocker.
4. **pkg208/pkg209/pkg210/pkg211** â€” Pillar 3 spectral-transport cluster
   filed 2026-08-19, all still open, no stated blockers: pkg208 (chromatic
   dispersion oracle, test-authoring only), pkg209 (pkg187 parity re-verify +
   doc refresh), pkg210 (companion wavelengths on specular reflection,
   register-sensitive), pkg211 (per-bounce spectral MIS + ray-differentials
   prototype). Not yet sequenced against each other â€” architect call.
5. **pkg218b â€” GPU spectral emission device upload** (`packages/pkg218b-gpu-spectral-emission-device-upload.md`,
   open, filed 2026-08-22). Exact CPUâ†”GPU lamp-colour parity (memory
   `gpu-emission-is-rgb-approximated`); distinct from the Pillar-4-paused
   `pkg218-spectral-colorimetry-fidelity.md` Thread B (swappable CIE
   observer) â€” this one is NOT paused.
6. **pkg180 â€” systemic Cycles-dim diagnosis** (open, dispatchable,
   diagnosis-first; no fix work until the offset mechanism is localized).
7. **Long-tail backlog, L-effort, no new urgency this pass** â€” pkg126
   (mesh-emitter unification), pkg127 (specular-polynomials SMS), pkg130
   (light-group emission decomposition), pkg132â€“137 (host-mapped memory
   fallback, SRF spectral sensors, LPE automata, SVO path guiding,
   partitioned-SMS ReSTIR caustics; pkg135 texture-overflow fallback is
   explicitly CONDITIONAL/dormant, do not implement pre-emptively). Audited
   2026-08-29 (#648) â€” still genuinely open, none superseded. Needs a
   dedicated day arc per package, not overnight-run shaped.
8. **De-prioritized below the Integration Milestone (owner-endorsed
   2026-08-03, unchanged):** pkg153 (wavefront-diff env-gate disposition,
   sub-percent tail), pkg155 (GPU absolute-slowdown investigation â€” the
   1.5s ceiling stays, memory `wavefront-perf-ceiling-owner-decision`, do
   NOT dispatch as a perf package), pkg173 (bounce-1 geometry-sampling
   parity, sub-percent tail). Re-enters the queue only if the paper turns
   out to require bit-level parity, or on explicit owner request.

**Paused, do not queue:** Pillar 4 (pkg45/pkg46/pkg48/pkg49/pkg50/pkg51/
pkg107 + `pkg218-spectral-colorimetry-fidelity.md` Thread B) â€” no unpause
directive issued; do not self-dispatch (memory `pillar4-on-pause`).

---

## 2026-08-29 SESSION HANDOFF â€” round complete; next = pkg224 implementation

**Shipped & merged this session (7 PRs):**
- **pkg201-S3 item A** (#651) â€” per-type bounce limits (diffuse/glossy/transmission), CPU+GPU parity, OPTION-2 runtime compare. REG 254 unchanged (+8 STACK/+8 CONST accepted perf-neutral).
- **pkg201-S3 item E** (#654) â€” native caustic toggles (reflective/refractive), CPU+GPU parity, sticky diffuse-ancestor cull. REG 254 (+8 STACK/+8 CONST).
- **pkg223b Bump node** (#655) â€” heightâ†’normal perturbation, CPU+GPU parity, SHARED HasNormalPerturb axis (no new axis, no spill). Fixed the UV-upload-gate bug ([[uv-upload-gate-needs-new-normal-perturb-consumers]]) + texel-relative bump eps.
- **pkg126â€“137 status audit** (#648), **tracker+template hygiene** (#649), **pkg224 progressive-sampler spec** (#656) + Bump/filter_glossy/caustic research notes (#650/#652/#653).

**Parked (documented, follow-up filed):** pkg201-S3 **item C** filter_glossy â€” NOT a register spill; materials recompute GGX alpha inline at ~4 sites each (no single sd->closure point), so a faithful blur needs a per-material floored-roughness refactor Ã—5 materials Ã—2 backends. [[pkg201-filter-glossy-alpha-site-sprawl]].

**Fleet register baseline now: `stageShadeBucketedKernel<0,â€¦>` REG 254 / STACK 3368 / CONSTANT[0] 1716** (measure from the actual .pyd, don't trust this).

**NEXT (owner-directed 2026-08-29): implement pkg224** â€” progressive (low-discrepancy) sampler for the wavefront, the prerequisite that unblocks pkg131 (blocked on white-noise RNG). Spec `.astroray_plan/packages/pkg224-progressive-sampler.md` (est. 2 sessions / ~6h) + research `.astroray_plan/docs/pkg224-progressive-sampler-research.md` are MERGED.

**OWNER CONFIRMED all three forks (2026-08-29) â€” DO NOT re-litigate, implement directly:**
- **(a) hash-Owen-scrambled Sobol'** (Burley 2020, "Practical Hash-based Owen Scrambling," JCGT 9(4); pbrt-v4 `FastOwenScrambler`, `src/pbrt/util/lowdiscrepancy.h`, Apache-2.0 â€” same license already cited in Astroray's `wavefront_rng.h`). NOT PMJ02. Owner: "prefer doing the hard work now so the foundations are solid for later."
- **(b) opt-in `__constant__` runtime flag** (pkg201-S3/pkg186/pkg223 pattern), NOT a compile-time axis. Default OFF = the existing PCG32 white-noise â†’ byte-identical fleet shade kernel + CPU/GPU snapshot-parity gates. Fall back to an `if constexpr` axis ONLY if the register probe shows the runtime off-path spills the REG:254 kernel.
- **(c) GPU-only first.** CPU stays on `std::mt19937` (dozens of sites, no WavefrontRNG hook); CPUâ†”GPU progressive-sampler parity is a separately-scoped follow-up, filed if/when a snapshot gate needs the progressive mode.

**Implementation anchors:** swap the internal generator inside `WavefrontRNG::GenerateForDimension` (`include/astroray/sampling/wavefront_rng.h`, device mirror `wavefront_rng_device.h`) behind the flag â€” it already takes the exact `(pixel, sample, dimension, seed)` tuple Sobol needs. Sobol direction vectors â†’ `__constant__`/side-table, NEVER `GMaterial`. **MANDATORY up-front cuobjdump probe** on the fleet `stageShadeBucketedKernel<0,â€¦>` (current baseline REG 254 / STACK 3368 / CONSTANT[0] 1716 â€” re-measure from the actual `.pyd`) BEFORE feature code; the sampler is drawn at primary-ray gen (`stage_init.cu`) AND every BSDF/NEE draw in the shade kernel, so keep per-draw cost to integer ops + the direction-table read. Then build pkg131 adaptive sampling on top. `.pyd` was rebuilt at end of the 2026-08-29 session (current w.r.t. this HEAD) â€” verify `astroray.__file__` + `cuobjdump --list-elf` sm_120 before the first GPU gate anyway (memory `stale_pyd_locations`).

---

## 2026-08-26 SESSION HANDOFF â€” next-session agenda (owner-directed)

**Landed this session:** pkg223 (GPU tangent-space normal maps, PR #647 merged
be7cbec). Register probe CLEAN â€” the fleet paid nothing (normal-map data rides the
`c_wfTexBinding` side arrays; `GMaterial` stays 640 B) so there was no spill to fix.
Also fixed a latent CPU arbitrary-frame bug (â†’ UV-aligned Mikk-TSpace). Two memories
banked: `shade-axis-side-table-avoids-spill`, `pkg131-blocked-on-progressive-sampler`.

**Decisions banked (do not re-litigate):**
- **pkg201-S3 â†’ OPTION 2** (owner, 2026-08-26): per-type bounce counters as a
  **runtime SoA comparison** in the shade kernel (5 counters in path state; cheap
  `if (depth[type] >= limit[type])` continuation check), **probe-first**. Only if
  the probe shows a spill on the fleet default do we fall back to a compile-time
  axis for the specific branch that spills â€” this AVOIDS the 8th-axis 256-kernel
  compile explosion (pkg223's 7th axis already put `stage_advance.cu` at 128
  specializations / ~9 min). Sets the pattern for items C (filter_glossy) and E
  (caustic toggles) too.
- **pkg131 â†’ BLOCKED** on a progressive sampler: the wavefront RNG is PCG32
  white-noise, no PMJ/Sobol prefix property (memory
  `pkg131-blocked-on-progressive-sampler`). Needs a Sobol/PMJ sampler prereq or an
  architect re-scope to a white-noise first-cut â€” **surface the fork to the owner**,
  do not silently implement on white noise.

**NEXT-SESSION AGENDA (three tracks):**

1. **Open engine work next in line.** (a) pkg201-S3 **item A** via option 2
   (per-type bounce counters), threading the 5 limits into `cuda_wavefront_render`
   (sweep call sites: `blender_module.cpp:1863`, the ReSTIR variant, tests) â€” up-front
   `cuobjdump -res-usage` probe on the CURRENT-main 128-kernel fleet baseline BEFORE
   feature code, invest-to-fix on spill. Then items **C** (filter_glossy roughness
   accumulator) and **E** (caustic-toggle specular-path flag), same probe-first shape.
   (b) **Bump** node â€” the pkg223 follow-up (needs height-texture screen-space/analytic
   derivatives; register-hostile; file as pkg223b). (c) pkg131 progressive-sampler
   decision above.

2. **Review pkg126â€“137** (owner: fundamental at one point, must not be forgotten if
   still relevant). This block is the Disney/dielectric-rough/VNDF/thin-film/
   multiscatter-LUT/mesh-emitter/light-groups/adaptive-sampling era. For EACH:
   cross-check against merged PRs + STATUS.md, then set its spec `**Status:**` to
   done / superseded / dropped / still-open with a one-line reason. Several likely
   landed or were superseded by later packages (e.g. pkg131 is blocked, pkg129
   Turquin LUTs, pkg138/149/150/151 dielectric-rough series) â€” do not leave them
   ambiguous.

3. **Project-tracker + package-template hygiene** (Google Sheets tracker
   `https://docs.google.com/spreadsheets/d/1u94CR7njH-LdyGQxKT0vKr56uHEVAVaqZGxVaIFUepg`;
   script `Google_Apps_Script.txt`). Three concrete fixes:
   - **Pillar frontmatter (tracker mis-parses ~19 specs).** `**Pillar:**` must be a
     BARE number 1â€“5. Offenders + fix:
     - "Integration Milestone (â€¦)" â†’ tracker extracts NOTHING: pkg175, pkg176, pkg177,
       pkg200, pkg201, pkg202, pkg203, pkg204, pkg207, pkg209, pkg212, pkg213 â†’
       **Pillar 5** (Production polish / Blender parity).
     - "Blender/DCC integration (integration-firstâ€¦2026â€¦)" â†’ tracker extracts **"2026"**:
       pkg219, pkg223 â†’ **Pillar 5**.
     - EMPTY pillar: pkg215, pkg216 (project-index tooling â†’ 5 or infra convention),
       pkg218 (spectral â†’ **Pillar 2**).
     - Infra with no numeric pillar: `pkg-add-cuda-syntax-ci` ("0 (Infrastructure)"),
       pkg205 ("Infrastructure / test hygiene"). Pick a convention â€” the script only
       tallies 1â€“5, so infra can stay blank; decide and document.
   - **Status audit.** Some specs still read open/partial that are really done /
     superseded / dropped â€” cross-check each vs merged PRs and flip (pairs with track 2).
   - **Timeline sheet is EMPTY â€” fix the script.** `refreshTimeline_` regex requires
     `\n- **YYYY-MM-DD` but STATUS.md entries are `**YYYY-MM-DD (â€¦)` bold-date
     paragraphs (no leading `- `, no `## Changelog` anchor) â†’ only 2 stray lines match.
     Replace the regex in `Google_Apps_Script.txt` with:
     `const re = /(?:^|\n)\*\*(\d{4}-\d{2}-\d{2})([\s\S]*?)(?=\n\*\*\d{4}-\d{2}-\d{2}|\n## |$)/g;`
     (group 2 = entry body; the existing whitespace-collapse + 600-char truncation
     still apply). The `## Changelog` slice becomes a harmless no-op.
   - **Prevention.** Update `.astroray_plan/packages/TEMPLATE.md` to mandate
     `**Pillar:** <1-5>` as a bare number, and optionally harden `parsePackageMd_`
     (map a leading "integration"â†’5, "infrastructure"â†’blank) as defense-in-depth.

**Repo state for kickoff:** `.pyd` in `build_cuda/Release` is current w.r.t. source
(HEAD advanced only via docs commits since the pkg223 build) but the stale-guard hook
will flag it â€” rebuild before any GPU verification (memory `stale_pyd_locations`).

---

**Date:** 2026-08-25 (FRESH ARCHITECT-LED planning pass â€” autonomous-session
open). Regenerates the 2026-08-23 report (pkg219a/b/c + pkg217 have since LANDED â€”
#640/#641/#642/#643). Canonical pickup queue for the orchestrator / dispatch-next.
Every item is grounded in the live project index or a cited in-code finding; grep
`^**Status:**` in each spec before dispatch (memory
`orchestrator-next-stage-report-stale`).

> Strategy: `ROADMAP.md`. Full state: `STATUS.md` (top entry 2026-08-21â†’22).

---

## 0. Pending-state facts the orchestrator must carry (NOT tasks to redo)

- **Stale `.pyd`:** rebuild `build_cuda` before ANY GPU verification this session
  (memory `stale_pyd_locations`, `incremental-build-signature-staleness`; verify
  `astroray.__file__` canonical + `cuobjdump --list-elf` sm_120 before trusting a
  gate). CI has no GPU â€” never declare a caustic/normal-map round clean on CI alone
  (memory `ci_has_no_gpu_runtime_blindspot`).
- **pkg214fix** (sodium/mercury energy-normalization; PR #629 was HW-FAIL) may still
  be in flight on branch `pkg214fix`. It **BLOCKS pkg222** (same generator +
  `profiles.bin`). Confirm it landed before dispatching pkg222; re-verify sodium AND
  mercury together (peak-vs-energy normalization coupling).
- **Pillar 4 remains PAUSED** (pkg45/46/48/49/50/51/107, incl. pkg218 Thread B â€” the
  swappable observer / camera response function). Surface the unpause decision to
  the owner; do not self-dispatch it. pkg222 extracts ONLY the pkg218 Thread A data
  fix (spectral correctness), which is not Pillar-4-paused.

---

## 1. State in one screen

- Spectral milestone + Blender-integration sweep shipped. Shader-node compatibility
  advanced hard: **pkg219a (coordinate/Mapping unification), pkg219b (bounded op-VM
  core), pkg219c (opcode fill-out) all LANDED** (#640/#641/#642). **pkg217 caustics
  LANDED via Path A** (#643) â€” but see Â§2: the caustic wiring exposed two deeper
  physics bugs the wiring fix did NOT address.
- Owner live priorities: **Blender shader-node compatibility, caustics, Cycles +
  CPU/GPU parity, opportunistic perf** (1.5s perf ceiling STAYS â€” no dedicated perf
  packages, memory `wavefront-perf-ceiling-owner-decision`).
- **New this pass (two caustic physics findings, CONFIRMED IN CODE):** the
  now-wired GPU caustic (a) rebuilds a byte-identical photon map every iteration so
  its noise never averages (â†’ pkg220), and (b) samples photon Î» uniformly and
  deposits SPD-blind power so a narrow-line lamp throws an impossible rainbow caustic
  (â†’ pkg221). These are separate from pkg217's addon-wiring fix.

---

## 2. Prioritized set for THIS session (4â€“7, ordered)

Tier key: **grunt** = open-weight via `delegate`, evidence-verified; **impl** =
`package-implementer`; **dv4** = deepseek-v4-pro / sonnet (well-specified, gated);
**Claude** = last-line judgment (register/ABI/parity); **hw** = `hardware-verifier`.

### FILED THIS PASS (thorough, self-contained specs â€” dispatch-ready)

1. **pkg220 â€” Progressive GPU photon-caustic seed.** *What:* thread a per-iteration
   seed into `kEmitSceneCaustic`/`buildCausticAim` so successive photon maps are
   independent and the caustic averages ~1/âˆšN. *Why now:* caustics are permanently
   grainy â€” a visible quality bug that the pkg217 wiring fix newly exposed. *Effort:*
   Sâ€“M. *Tier:* **dv4** (plumbing + a clean convergence gate; register-neutral).
   *Gating:* none. **Cheapest high-value win â€” dispatch first.**

2. **pkg221 â€” Photon Î» importance-sampled from the light SPD.** *What:* draw photon
   wavelengths âˆ the emitting light's SPD (CDF built host-side, CPU+GPU), weight the
   deposit so white stays white and narrow-line lamps throw line-colored caustics.
   *Why now:* emission-line dispersion is physically impossible today (SPD-blind,
   engine-wide). *Effort:* Mâ€“L. *Tier:* **dv4** + `cite-algorithm` (PBRT spectral IS)
   + `cycles-parity-reviewer`. *Gating:* shares `kEmitSceneCaustic` with pkg220 â€”
   land pkg220 first, rebase this on top.

3. **pkg222 â€” Atomic-line lamp SPDs: cited, chromatically-correct.** *What:* re-derive
   preset atomic-line lamp line intensities from NIST/measured data, regenerate
   `profiles.bin`, audit every lamp's chromaticity (mercury magentaâ†’greenish-white).
   *Why now:* every atomic-line lamp renders the wrong color; makes pkg221's
   emission-line dispersion *correct-colored*. *Effort:* M (data, no engine C++).
   *Tier:* **dv4** (citation + A/B render discipline). *Gating:* **BLOCKED by
   pkg214fix** (same generator) â€” confirm it landed first.

4. **pkg223 â€” Normal Map node (pkg219d part 1).** *What:* tangent-space normal-texture
   perturbation of the shading normal, CPU+GPU, behind `<bool HasNormalPerturb>`.
   Bump deferred. *Why now:* normal maps are ubiquitous and silently do nothing today
   â€” the biggest remaining shader-node usability gap after pkg219a-c. *Effort:* Mâ€“L.
   *Tier:* **dv4** implement, but the **GPU shade-kernel register budget is
   Claude-last-line** â€” HARD `cuobjdump` REG probe gate + `cpp-abi-guard` + Claude
   review before merge; spill â†’ escalate. *Gating:* reuses pkg219a coordinate path.

### EXISTING OPEN WORK â€” weighed, sequenced behind the above

5. **pkg201 Stage 3 â€” per-type bounce counters + `filter_glossy` + native caustic
   toggles.** Closes the last register-hostile pkg200 honour-matrix rows. *Effort:* L.
   *Tier:* **Claude** (register-hostile). *Note:* the caustic-toggle row now LOGICALLY
   couples to the landed pkg217 + the new pkg220/221 caustic work â€” wire the toggle to
   the existing pipeline, don't reimplement. Non-caustic rows (bounce counters,
   filter_glossy) can go independently as a **dv4** slice. Pick up behind 220â€“223.

6. **pkg131 â€” Zero-knob adaptive sampling, wavefront leg.** Long-standing; convergence
   quality (not raw perf â€” respects the ceiling). *Effort:* L. *Tier:* impl/dv4.
   *Gating:* none; fill a free slot behind Themes above.

### NOT this session (surface to owner)

- **pkg218 Thread B** (swappable CIE observer / camera spectral-sensitivity) â€”
  Pillar-4-paused; research-grade capability, owner said "not the current main
  focus." Leave paused; do not dispatch. pkg222 already carves out Thread A.
- **pkg217 SMS-NEE-cull quality upgrade** â€” the sharper forward-caustic method noted
  in pkg217's CORRECTION; only if the photon caustic (post-220/221) shows residual
  quality limits. Do not pre-empt.

---

## 3. Real forks for the owner (not an artificial ballot)

- **Caustic depth:** pkg220 (decorrelate) + pkg221 (SPD Î») make the *existing* photon
  caustic converge and be spectrally correct â€” cheap, high-value, dv4-implementable.
  The alternative "sharper" path (SMS-NEE-cull, pkg217's deferred design) is L,
  register-hostile, and Claude-only. **Recommendation:** ship 220+221 first; only
  invest in SMS if their converged quality proves insufficient. Owner: agree, or go
  straight for SMS?
- **pkg222 vs pkg214fix ordering:** both touch `build_spectral_profiles.py` /
  `profiles.bin`. pkg222 is BLOCKED on pkg214fix landing. If pkg214fix has stalled,
  the owner may want to fold the mercury green-line fix INTO the pkg214fix branch
  rather than a separate pkg222. **Flag:** is pkg214fix still open?
- **pkg223 register risk:** Normal Map perturbs the REG:254 shade normal. If the probe
  spills despite `<bool HasNormalPerturb>` isolation, do we accept a bounded non-map
  STACK cost, or hold the feature? Default: hold + escalate (never ship a fleet-wide
  regression).

---

## 4. Top items to dispatch first (with routing)

1. **pkg220** â†’ `package-implementer` (dv4 tier). Independent, cheapest high-value
   caustic fix; clean convergence gate. Rebuild the stale `.pyd` first.
2. **pkg221** â†’ dv4 implementer + `cite-algorithm` + `cycles-parity-reviewer`, AFTER
   pkg220 (shared kernel).
3. **pkg223** â†’ dv4 implementer, HARD REG-probe gate + `cpp-abi-guard` + Claude
   review before merge.
4. **pkg222** â†’ dv4 implementer â€” ONLY after confirming pkg214fix landed.

Breadth research (NIST line intensities for pkg222, extra caustic/normal-map parity
scenes, Cycles Normal Map handedness confirmation) â†’ `delegate` open-weight,
evidence-verified, scoped to ONE narrow deliverable each (memory
`delegate-grunt-budget-bound-tight`).

---

## 5. Specs filed this pass

- **pkg220** â€” `packages/pkg220-caustic-per-iteration-seed.md` (Track A, dv4).
- **pkg221** â€” `packages/pkg221-photon-wavelength-spd-importance-sampling.md`
  (Track A, dv4).
- **pkg222** â€” `packages/pkg222-atomic-line-lamp-spd-chromaticity.md` (Track A, dv4;
  extracts pkg218 Thread A; BLOCKED on pkg214fix).
- **pkg223** â€” `packages/pkg223-normal-map-node.md` (Track A, dv4 + Claude gate;
  pkg219d part 1, Bump deferred).
# Astroray Master Roadmap

**One document to navigate the whole plan.** Every other document exists
because this roadmap points at it. New to the project? Read this first.

---

## Vision in one paragraph

Astroray is a C++/CUDA path tracer with a Blender 5.2+ addon. Near-term delivery
prioritizes a production-capable Blender/DCC renderer: responsive GPU interaction,
trustworthy CPU fallback, and Cycles-compatible behavior where appropriate.
The long-term target remains research-grade astrophysical rendering and
scientific visualization. Spectral transport, dispersion, infrared/band-aware
outputs and robust physical transport are foundations of both goals; Pillar 4
remains paused under the current sequencing below. The design goal is **pluggability** â€” new materials, shapes,
light transport techniques, and astrophysical phenomena should be
drop-in plugins that register into a small set of factory registries,
not patches to core files. A veteran engineer looking at the codebase
should think "this is the obvious way to do it," not "this is clever."

**Performance goal:** rival Cycles in simple enough cases on a single
RTX 5070 Ti (CUDA). **Fidelity goal:** surpass Cycles on spectral and
astrophysical scenes. **Simplicity tax:** every abstraction pays for
itself with a concrete caller today.

---

## Current sequencing

**Authoritative direction lives in
[`north-star-and-integration-gate-2026-09-07.md`](north-star-and-integration-gate-2026-09-07.md)**
(owner-approved north star + the measurable Pillar-4 exit gate + the next
4â€“6-week sequencing). Read that first; the summary below is a pointer, not a
second source of truth.

- **North star:** a spectral C++/CUDA path tracer for research-grade
  astrophysical rendering, driven from inside Blender as the steering wheel.
  Near-term bar: a production-capable Blender renderer with a fast interactive
  GPU viewport on the RTX 5070 Ti, CPU as correctness oracle, Cycles-compatible
  where Cycles is right. **correctness > fidelity > speed.**
- **Pillar 4 stays PAUSED** until the exit gate (Â§2 of the north-star doc) is
  met â€” viewport present p95 â‰¤ 100 ms, shader-socket coverage, three reference
  scenes rendering CPU+GPU parity-clean, native adaptive-sampling + denoise,
  zero high-severity addon bugs, a documented one-command install.
- **Science-foundational side lane** (allowed while Pillar 4 is paused, ordered
  behind the gate work): pkg243 raw band provenance, pkg133 SRF spectral
  sensors, pkg130 light groups, pkg251 spectral reachability.
- **Next rounds (~3 packages each):** R1 pkg241 Phase 0 + pkg237/238 +
  pkg242; R2 pkg253 + pkg245 + pkg234/233; R3 pkg241 behavior + pkg251 +
  pkg243; R4 pkg133 + pkg130 + pkg136 GPU. Full ranking and dependencies in the
  north-star doc Â§4.

**Explicitly de-prioritized (owner-endorsed):** the sub-percent GPU/CPU parity
tail â€” pkg172 effect (B) / pkg173 and the pkg153 remainder â€” sits below the
integration gate unless a paper requires bit-level parity.

---

## The agent tracks

Work happens on independent tracks. Each has its own agent and acceptance
criteria. Progress on one track rarely blocks another â€” that is by design, so
your single-developer throughput multiplies without coordination overhead.

| Track | Owner agent | Runs on | Purpose |
|---|---|---|---|
| **A. Core quality** | Claude Code (local) | Your RTX 5070 Ti | Correctness, foundational refactors â€” all package specs route here |
| **B. Feature breadth** | Retired 2026-04 era (was Copilot cloud) | â€” | Legacy `Track: B` specs route to Claude Code (`package-implementer`) |
| **C. Experiments** | Retired 2026-04 era (was Cline) | â€” | Same routing |
| **D. Grind work** | Open-weight models via the `delegate` skill (opencode) | Your machine | Bounded mechanical work; evidence-verified by Claude (CLAUDE.md Â§5) |
| **E. Coordination/review** | Retired 2026-07 (was Codex) | â€” | Legacy `Track: E` specs route to Claude Code (`package-implementer`) |

Coordination is done by the Claude Code `architect` and
`roadmap-orchestrator` agents (`.claude/agents/`), not by a separate
overseer. Retired-track handbooks are archived in
`docs/archive/agents-multitrack-2026-04/`.

**Simplicity principle per track:**
- Track A handles anything that *has* to be right.
- Track B handles anything that *matches a pattern* that is already right.
- Track C explores things that *might* be right.
- Track D mechanically converts known-right work into more of it.
- Track E keeps the other tracks aligned and turns context into actionable
  issues, reports, and PRs.

---

## Five pillars, in priority order

### Pillar 1 â€” Plugin architecture [FOUNDATIONAL, DO FIRST]

Convert materials, shapes, lights, textures, integrators, and passes into
plugins registered via `Registry<T>` templates. Everything below assumes
this is in place.

- Design: [`plugin-architecture.md`](plugin-architecture.md)
- Duration: 2â€“3 weeks of track A sessions
- **Blocks everything else.**

### Pillar 2 â€” Spectral core

Upgrade from hero-wavelength-at-GR-only to a fully spectral pipeline:
`SampledSpectrum`/`SampledWavelengths`, Jakob-Hanika RGBâ†’spectrum
upsampling, spectral BSDFs and env maps. RGB backward-compat via
upsampling.

- Design: [`spectral-core.md`](spectral-core.md)
- Duration: 3â€“4 weeks
- Depends on Pillar 1.

### Pillar 3 â€” Light transport upgrades

ReSTIR DI as drop-in for NEE+MIS direct lighting; Neural Radiance Caching
via tiny-cuda-nn for indirect. Both as plugin integrators; classic path
tracer remains the fallback. When accelerated transport is available and
performance-positive, renderer defaults should pick it automatically and fall
back without user intervention.

- Design: [`light-transport.md`](light-transport.md)
- Duration: 4â€“6 weeks
- Depends on Pillars 1, 2.

### Pillar 4 â€” Astrophysics platform

> **PAUSED (2026-06-08, owner; reaffirmed 2026-09-07) â€” unpause is gated on the
> MEASURABLE Pillar-4 exit checklist in
> [`north-star-and-integration-gate-2026-09-07.md`](north-star-and-integration-gate-2026-09-07.md)
> Â§2**, not a prose judgement. The gate covers viewport responsiveness,
> shader-socket coverage, three reference scenes rendering CPU+GPU parity-clean,
> native adaptive-sampling + denoise, zero high-severity addon bugs, and a
> documented one-command install. As of 2026-09-07 the gate is NOT MET
> (DROPPED-SILENT sockets 64.5%, real viewport present latency unmeasured, one
> of three reference scenes NOT GREEN on GPU). The Pillar-4-era specs are
> outdated and get a full audit pass at unpause. Do not unpause unilaterally.

> **Pre-pause groundwork (2026-05):** pkg40 Kerr metric, pkg41 Kerr validation
> (#236), pkg42 synchrotron emission (#245), pkg43 slim disk (#271), pkg44 ADAF
> (#310), pkg47 FITS loader (#292, `ASTRORAY_ENABLE_FITS` default OFF), pkg67
> metric-aware tracer, pkg99, pkg105 landed before the pause (~50 % of the
> original Pillar-4 scope). Their specs and the 2026-05â†’08 round history are in
> [`archive/roadmap-history-2026-05-to-2026-08.md`](archive/roadmap-history-2026-05-to-2026-08.md).

Kerr metric, synchrotron emission, HII recombination lines, simulation
data import (FITS, HDF5, yt), telescope PSF. Each phenomenon is a
plugin. This is Astroray's unique niche.

- Design: [`astrophysics.md`](astrophysics.md)
- Duration: 6â€“10 weeks, parallel with other pillars
- Depends on Pillars 1, 2.

### Pillar 5 â€” Production polish

Multi-GPU scaling, OIDN 2.xâ†’3.0, Blender viewport render, motion blur,
output formats, documentation. Ongoing, opportunistic.

- Design: [`production.md`](production.md)
- Duration: ongoing
- Depends on Pillars 1, 3.

---

## The 12-week view

This is the original planning horizon, not a live schedule. For current package
state and next-up order, use `STATUS.md`.

```
Wk 1-2   [A] Plugin registries + migrate one material end-to-end (pkg01, pkg02)
         [D] Ralph begins improving test coverage

Wk 3-4   [A] Migrate remaining materials/shapes/textures (pkg03, pkg04)
         [B] First Copilot plugin as proof

Wk 5-6   [A] Integrator interface (pkg05) + spectral types (pkg10)
         [B] Spectral measured-BRDF loader (RGL database) as plugin
         [C] Cline prototypes tiny-cuda-nn integration

Wk 7-8   [A] Finish spectral migration (pkg11-14)
         [B] Fluorescence plugin, Principled Volume improvements

Wk 9-10  [A] ReSTIR DI integrator plugin
         [B] Kerr geodesic plugin, FITS loader

Wk 11-12 [A] Neural radiance cache (promote Cline prototype)
         [B] HII emission-line plugin, sim-data volumes
         [D] Blender viewport render polish
```

By week 12: spectral everything, ReSTIR, at least one neural integrator,
Kerr + working astrophysical plugins, clean plugin architecture.

---

## How to use this plan

- **Starting a coding session?** Pick an open package from `../packages/`.
- **Launching a cloud agent?** See `../agents/copilot-cloud.md`.
- **Running Claude Code locally?** See `../agents/claude-code.md`.
- **Spinning up Ralph?** See `../agents/ralph-loop.md` and
  `../scripts/ralph_loop.sh`.
- **Overseer duty?** See `../agents/overseer.md`.

When you finish a package: mark it `done` in its file header, update
[`STATUS.md`](STATUS.md), open a PR.

---

## Simplicity tax

Any PR that adds framework, abstraction layer, or "future flexibility"
without a concrete caller **today** gets rejected. The test:

> A veteran CS engineer, reading this diff cold, should say "yeah,
> that's how I'd do it" â€” not "clever" and not "this should have been a
> function."

Applies to humans and agents equally. Overseer enforces in first-pass
review before merges.

## Visual fidelity vs performance

Top priority is visual fidelity. Performance competitive with Cycles in
simple enough scenes on a single RTX 5070 Ti is a floor, not a ceiling.
When these conflict:
1. Visual fidelity wins for offline renders (F12).
2. Performance wins for interactive viewport preview.
3. Correctness wins over both, always.

hook: PreToolUse
web search: 
hook: PreToolUse Completed
exec
"C:\\Users\\hgcom\\AppData\\Local\\Microsoft\\WindowsApps\\pwsh.exe" -Command "Get-Content -Encoding utf8 -LiteralPath '.astroray_plan/docs/NEXT_STAGE_REPORT.md' -TotalCount 105; Get-Content -Encoding utf8 -LiteralPath 'scripts/project_index.py' -TotalCount 140; rg -n 'pkg259|Phase 0|freq|corpus|Gate .[bc]|95|50 scenes' '.astroray_plan/docs/north-star-and-integration-gate-2026-09-07.md'; rg --files '.astroray_plan/packages' -g '*259*'" in C:\Users\hgcom\OneDrive\Astroray\Astroray_repo\Astroray-pkg259
 succeeded in 348ms:
# Astroray Next Stage Report

## 2026-09-07 CURRENT — read the north-star doc; Round 1 is in flight

Authoritative sequencing: [`north-star-and-integration-gate-2026-09-07.md`](north-star-and-integration-gate-2026-09-07.md) §4.
Round 1 status after the 2026-09-07 overnight: pkg241 Phase 0 measured (PR #733, design
awaiting owner/Terra decision on Phase 1); pkg242 UV-less checker fixed (#726, transformed-p
contract still open); pkg237/238 diagnosed (#731, test-method fix needs owner sign-off).
Round 2 opener pkg253 (#728) landed CPU alpha shadows; GPU alpha is its follow-up. Specs now
must pass `python scripts/project_index.py lint`. Everything below this line is historical.

## 2026-09-06 HISTORICAL — rebuilt, installed, ready for pkg241/240

Owner milestone for the next round: **responsive camera/material edits, reliable
cancellation, and faithful mapped textures**. Start pkg241 with real Blender
measurement, then behavior changes; use pkg240 as a parallel measured CI lane.
Follow the [ready-to-paste agent prompt](next-agent-prompt-pkg241-pkg240.md) and
[full rebuild evidence](rebuild-handoff-2026-09-06.md). Pkg242/245 remain separate
mapped-texture scopes; pkg230b/232/236 are already landed. Pillar 4 stays PAUSED.
The initial clean CUDA all-target build found a stale standalone GPU caller;
pkg250 LANDED in PR #716, merge `37f7343` (03:05:15 UTC). Local gates and
independent SIGN-OFF passed. Both host/CUDA CI runs passed; each host suite had
2176 passed, 283 skipped, 15 xfailed, 4 xpassed. The advisory Cornell reference
smoke remains NOT GREEN (two of three gates passed), tracked under pkg249.
Development ALL_BUILD, both clean addon builds, native/Blender checks and the
installed CUDA addon smoke passed. All 429 non-addon profile files were preserved.
The affine mapping chart passes CPU/GPU/Cycles; the separate UV-less procedural
checker baseline remains NOT GREEN under pkg242. See the report for exact gates.


## 2026-09-06 CURRENT — pkg230b and pkg236 landed

- **pkg230b LANDED in PR #708**, merge `8217234b`, 2026-09-06 00:24:49 UTC.
  The owner approved Terra/DeepSeek independent review while Claude is unavailable.
  Terra final source/caller/binding/visual SIGN-OFF passed. PR CI: **2133 passed,
  269 skipped, 15 xfailed, 4 xpassed**; host and CUDA checks passed.
- Local pkg230b evidence remains **101 focused passes**, six real-RNA probe sets,
  **21 CPU/GPU/Cycles render legs** and both isolated package smokes passing.
  Full local suites remain **2370 passed, two reproduced baseline failures**
  (pkg237 HDRI SSIM / pkg238 PostInit ULP); NOT GREEN, neither failure closed.
- **pkg232 already landed #705.** Specs **pkg241–248 are filed**, #704/#706/#709;
  filing approval is not implementation approval. Pillar 4 remains PAUSED.
- **pkg236 LANDED #711**, merge `2699b43`; Terra final SIGN-OFF passed.
  Smoke isolation and transactional installation passed 62 focused tests and the
  exact real-Blender local-host test. PowerShell 7 and 5.1 CPU smokes passed;
  all 471 live-profile files remained unchanged. Both CI runs: **2173 passed,
  277 skipped, 15 xfailed, 4 xpassed**; host/CUDA checks passed.
  [Evidence](pkg236-implementation-evidence.md) retains transaction limits and
  the pre-existing non-blocking reference-smoke failure (two gates passed, one
  failed). The advisory is NOT GREEN; pkg249 records the diagnostic follow-up.
- **pkg240 baseline audit landed #712**: host tests occupy 90.1-91.7% of the
  measured host job time. Package remains OPEN; no workflow change or speedup
  claim. Detailed architecture precedes a controlled split-runner trial.
- **Next main feature: pkg241 Phase 0**, completing the existing interactive
  recorder and measuring actual Blender response/cancellation before behavior
  changes. pkg242 then improves procedural mapping; pkg245 covers normal/bump
  provenance. pkg240 CI cost audit is suitable parallel throughput work.
- **Spark CLI access verified** with the installed Codex CLI and current account.
  Bounded Spark workers can run via CLI even though this task's native subagent
  roster lacks Spark. No account/configuration change was required.

See [pkg230b evidence](pkg230b-delivery-evidence.md) and
[round delivery status](round-20260906-delivery-status.md).


---


## 2026-09-06 earlier handoff — pkg230 Phase 2 LANDED (#701)

pkg230 Phase 2 (30 Vector Math ops, 5 Vector Rotate modes, faithful Mix factor
clamping in the color/scalar op-VM chain) is **LANDED in PR #701**, merged
2026-09-05 17:10 UTC (2026-09-06 Sydney), commit
`b38a7d8471884c43c7aa5a2fd60ddb447c859309`. Independent Claude final SIGN-OFF
covers reviewed source `4035a000f8b45dc549e072ebfd31799f608f1755`.
Both push and PR CI runs passed host build/tests and CUDA syntax checks.
The PR host run recorded 2074 passed, 243 skipped, 15 xfailed, 4 xpassed.
Do not redispatch Phase 2.

**Gates (concise; full gates/artifacts in
[pkg230-phase2-delivery-evidence.md](pkg230-phase2-delivery-evidence.md)):**

- 158 focused pkg219/pkg230 tests passed; 37 harness tests passed; isolated
  Blender dev-loop smoke PASS after live-profile-incident recovery.
- 15 real-Blender comparison legs = 5 cases across CPU-only Astroray, GPU
  Astroray, and Cycles; max RGB mean-ratio deviation 2.38% vs the 5% gate.
  Astra and independent Claude visual review PASS; charts saved.
- All 64 non-program shade variants match their recorded baseline resource
  fields. Fleet: REG 254 / STACK 3400 / CONST 1748 / LOCAL 0. The comparison
  measured resources, not complete machine-code byte streams.
- Original full split run: 2326 passed (1642 CPU + 684 serial), 4 original
  failures. Two environment/sampling failures resolved on rerun (hermetic
  profile smoke; backdrop correct artifact + 256 samples); two baseline
  HDRI/ULP failures remain under pkg237/pkg238. The original full suite is NOT
  green and was NOT wholly rerun.
- A local bright patch on the backdrop persists on main+feature despite the
  global SSIM pass at 256; pkg239 follow-up #702. No claim of perfect
  baseline/Cycles visual parity.
- Follow-ups filed separately, all OPEN for architect review before
  implementation, no queue promotion: pkg230b #697, build-latency pkg231 #698,
  pkg232–235 #699, pkg236–238 #700, pkg239 #702. This closeout also files
  pkg240 CI workflow cost audit, separate from renderer work and pkg231.

**Scope boundaries:** the verified real-Blender carrier is textured Principled
with specular zero and Closest filtering — not universal BSDF/filter coverage.
#!/usr/bin/env python3
"""Astroray project index — a lightweight SQLite knowledge graph over the repo.

Parses .astroray_plan/packages/*.md (Pillar/Track/Status/Depends on frontmatter),
.astroray_plan/docs/*.md (research notes), and tests/*.py into queryable tables,
plus optional GitHub issue/PR sync via the gh CLI.

Why SQLite and not a vector DB: the docs are already well-structured markdown;
the genuinely grep-hostile queries are cross-references (which package touches
which file, which packages depend on each other, which issue maps to which
package) — exactly what a relational index answers, without embedding cost or
staleness amplification.

Usage:
  python -m project_index build              # (re)build the index (default)
  python -m project_index query "pixel filter"   # scannable title/body/file search
  python -m project_index deps pkg203        # dependencies + reverse deps
  python -m project_index owns include/gpu_materials.h  # which package owns a file
  python -m project_index script "contact sheet"        # canonical script for a task
  python -m project_index whatis pkg214      # compact card for one package
  python -m project_index graph --json out.json   # nodes/edges for the viz
  python -m project_index graph --html graph.html # self-contained node tree
  python -m project_index gh-sync            # pull issues/PRs via gh CLI (network)
  python -m project_index lint --all         # lint package specs against TEMPLATE v2

The DB is written to .astroray_plan/.project-index.db (gitignored). Read
commands (query/deps/owns/script/whatis) auto-rebuild it when a source file is
newer than the DB and print "(index rebuilt)" to stderr, so answers are never
silently stale.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / ".astroray_plan"
DB_PATH = PLAN / ".project-index.db"
README_PATH = ROOT / "scripts" / "README.md"

PKG_ID_RE = re.compile(r"^pkg(\d+[a-z]?)", re.IGNORECASE)
DEP_RE = re.compile(r"pkg\d+[a-z]?", re.IGNORECASE)

# TEMPLATE v2 vocabulary (see .astroray_plan/packages/TEMPLATE.md). Tried
# first by _status_token so a v2-compliant "done — PR #716" (or a legacy
# "**DONE — ...**" with a stray trailing "**") both reduce cleanly to "done"
# instead of falling into the legacy split below.
_V2_STATUS_PREFIX_RE = re.compile(
    r"^(open|in-progress|blocked|paused|done|superseded)\b", re.IGNORECASE
)


def _status_token(raw: str) -> str:
    """Reduce a Status line to a short scannable token.

    Tries the TEMPLATE v2 vocabulary first (case-insensitive prefix match).
    Falls back to the legacy heuristic: text up to the first of '(', em-dash,
    '.', ',', or newline, lower-cased and stripped. e.g. "done (PR #540, ...)"
    -> "done"; "open (filed 2026-08-21)." -> "open"; "Stage 2 done ..." ->
    "stage 2 done"; "done — PR #716" -> "done".
    """
    m = _V2_STATUS_PREFIX_RE.match(raw.strip())
    if m:
        return m.group(1).lower()
    token = re.split(r"[(—.,\n]", raw, maxsplit=1)[0]
    return token.strip().lower()


# ── Spec lint (TEMPLATE v2) ─────────────────────────────────────────────
#
# See .astroray_plan/packages/TEMPLATE.md for the grammar these validate.

SPEC_FILENAME_RE = re.compile(r"^pkg(\d{1,3}[a-z]?)-[a-z0-9]+(?:-[a-z0-9]+)*\.md$")
TITLE_RE = re.compile(r"^# (pkg\d{1,3}[a-z]?) — \S.*$")
STATUS_RE = re.compile(
    r"^(open|in-progress|blocked|paused|done|superseded)(?: — \S.*)?$"
)
PILLAR_RE = re.compile(r"^[1-5]?$")
TRACK_RE = re.compile(r"^[A-D]$")
DEPENDS_RE = re.compile(r"^(none|TBD|pkg\d{1,3}[a-z]?(?:, pkg\d{1,3}[a-z]?)*)$")

H2_ORDER = [
    "Goal", "Context", "Evidence", "Reference", "Prerequisites",
    "Specification", "Acceptance criteria", "Non-goals", "Progress", "Lessons",
]
H2_OPTIONAL = {"Evidence"}
SPEC_H3_ORDER = ["Files to create", "Files to modify", "Key design decisions"]

TABLE_ROW_RE = re.compile(r"^\|\s*`[^`\s]+`\s*\|\s*\S.*\|\s*$")
TABLE_SEP_RE = re.compile(r"^\|\s*-{3,}\s*\|\s*-{3,}\s*\|$")

# Five duplicate package numbers grandfathered from before numbering
# discipline existed (pkg218 was renumbered to pkg218b on 2026-09-07, #730).
# Do not add new entries here; a NEW duplicate filename is always a lint error.
LEGACY_DUP_NUMS = {"pkg38", "pkg55", "pkg64", "pkg85", "pkg86"}

FIELD_LINE_RE = re.compile(r"^\*\*([A-Za-z][A-Za-z ]*):\*\*\s*(.*)$")
REQUIRED_HEADER_FIELDS = ["Pillar", "Track", "Status", "Estimated effort", "Depends on"]

DEFAULT_BASELINE_PATH = ROOT / "scripts" / "spec_lint_baseline.txt"


def _pkg_files() -> list[Path]:
    return sorted(p for p in (PLAN / "packages").glob("*.md") if p.name != "TEMPLATE.md")


def _header_value(text: str, label: str, fold: bool = False) -> str:
    """Extract a **label:** header value (first matching physical line).

    Transitional: legacy specs sometimes wrap a field's prose across several
    lines; the linter (see `lint`) forbids this for non-baseline files, so
    this is a tolerant reader for the pre-v2 corpus, not a grammar. With
    fold=True, up to 8 continuation lines (non-blank, not a new `**Field:**`,
    not `---`/`#`) are appended — use fold=True ONLY for Depends on, whose
    legacy prose continuations can otherwise hide dependency tokens from
    DEP_RE. fold=False (the default) matches only the first physical line,
    same as the old field_line() this replaces.
    """
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.strip().startswith(f"**{label}:**"):
            value = line.split("**", 3)[-1].strip()
            if fold:
                for j in range(i + 1, min(i + 9, len(lines))):
                    nxt = lines[j]
                    stripped = nxt.strip()
                    if not stripped or stripped.startswith(("**", "---", "#")):
                        break
                    value += " " + stripped
            return value
    return ""


def _parse_package(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
44:- **Target [Terra]:** on two pinned scenes (10k and 100k triangles), warm session, 3×100 camera edits and 3×100 material edits: event dispatch → first *correctly updated* Blender-presented frame, GPU p95 ≤ 100 ms and p99 ≤ 150 ms; cancellation acknowledgement p95 ≤ 200 ms, p99 ≤ 300 ms, and no stale frame presented after the ack. Denoise is **not** in the interactive loop (progressive refine; denoise on idle/pause) **[OWNER-RATIFIED 2026-09-07 08:30: denoise stays out of the interactive loop]**. CPU is the image oracle, not a latency oracle.
45:- **Measured by:** pkg241 Phase 0 recorder (extends the pkg81 harness) inside a real Blender session, not the in-process harness. Baseline measured tonight through the MCP bridge: idle progressive refinement redraws at **~1.3 Hz** (6 redraws / 4.46 s, 2 220-triangle scene, RENDERED viewport) — the owner's "3–5 fps, no visible refine" report reproduces.
47:- **If pkg241 Phase 0 says otherwise:** if real present > 100 ms even without denoise, the fix is engine/blit work (a new spec), not a target relaxation; if it is only denoise-in-loop that fails, the gate must state denoise is *not* in the interactive loop (progressive refine, denoise on pause) — see §6 owner decision.
51:- **Target [OWNER-RATIFIED 2026-09-07 08:30 — frequency-weighted]:** frequency-weighted coverage, not raw count: over a frozen corpus of ~50 Blender scenes, score socket *uses* (SUPPORTED = 1, APPROXIMATED = 0.5 only when a warning is emitted), require ≥ 95 % weighted coverage **and zero silent drops in corpus scenes**. Raw socket counts stay diagnostic. Principled advanced inputs, Metallic BSDF, Sky texture and Displacement must each be SUPPORTED or APPROXIMATED-with-warning; only pkg253 (Principled) is scheduled — bounded support-or-warn packages for Metallic, Sky and Displacement are being filed (owner 2026-09-07 08:30).
58:- **Target [Terra]:** exactly three pinned `.blend` assets (fixed settings, pinned SHA — no "or" alternatives) render F12 on CPU and GPU with no addon exception and pass: linear CPU↔GPU ROI mean ratio within ±5 % per channel, a structural metric (SSIM ≥ 0.95 on the GPU vs CPU pair), and scene-specific non-vacuity checks (checker contrast present, HDRI contribution present, hair-pixel coverage > 0) so a black or missing feature cannot pass.
63:- **Current:** only **cornell** has parity data (`benchmarks/cycles-parity/2026-09-03-*.csv`): astroray-gpu SSIM 0.9538 vs Cycles, mean-ratio 0.9967/0.9975/0.9944, 1477 ms vs cycles-cuda 3134 ms. The material-zoo case is **NOT GREEN on GPU** — the checker texture disappears (CPU luminance std 0.4182 vs GPU 0.0330; GPU samples only real UV layers, CPU synthesizes fallback UVs; `rebuild-handoff-2026-09-06.md`, carried by pkg242). HDRI-with-hair parity is **unmeasured**.
113:- **pkg241 Phase 0** — measure real present + cancel latency in a live Blender session. Gate (a). No deps. Highest priority: the whole responsiveness lane is guessing until this exists.
114:- **pkg237 + pkg238** — diagnose, then repair or evidence-calibrate the two reproduced baseline failures (HDRI SSIM, PostInit ULP); both specs forbid assuming a fix or relaxing a bound without independent numeric/image evidence **[Terra]**. Gate (c) precondition — parity work on a red baseline hides regressions. No deps.
115:- **pkg242** — procedural mapping / bake-domain parity; closes the material-zoo checker-vanishes-on-GPU NOT-GREEN. Gate (c). Depends on landed pkg230b.
118:- **pkg253** — Principled advanced inputs; highest-value single node (backlog row 1, 21 sockets). Sequence Alpha + Specular Tint first (cheapest, most-used). Gate (b).
119:- **pkg245** — normal/bump image coordinate provenance. Gate (b)/(c). Pairs with the pkg223/pkg219 normal path.
120:- **pkg234 + pkg233** — image-texture filtering honor + standalone-BSDF texture plumbing. Gate (b)/(c) texture fidelity. pkg233 unblocks textures on non-Principled BSDFs.
121:- **pkg258** *(added 2026-09-07 evening)* — environment NEE + importance sampling: no reachable integrator samples the HDRI, and the dormant sampler is wrong. Gate (c) blocker for every HDRI-lit scene; owner-prioritised. CPU first, GPU wavefront under the lock.
123:**Gate-closure order [Terra]:** pkg241 → pkg242/pkg245 → coverage-node work (pkg253, then Metallic/Sky/Displacement once filed) → three-scene corpus + settings/build/triage gates → science lane. Rounds 3–4 below are **conditional fill work**: a science-lane package is dispatched only when every gate-critical package is blocked or under review.
126:- **pkg241 behavior phases** — cooperative cancellation contract + response behavior, on top of Phase 0 numbers. Gate (a) close.
129:- **pkg259** *(added 2026-09-07 evening)* — Cycles feature-coverage reference scene corpus (the gate (b)/(c) instrument; Phase 0 design brainstorm with Astra, then one scene family per session). Can start its Phase 0 in Round 2 while engine lanes hold the GPU.
159:1. **The viewport gate may be measured on the wrong instrument.** The 37.7 ms p99 comes from an in-process harness that bypasses the Blender GPU blit; denoise-in-loop already shows 184.8 ms. The gate could "pass" on an optimistic number. Mitigation: pkg241 Phase 0 must measure real present latency before any (a) sign-off.
161:3. **Only one parity scene is measured, and one of the three named scenes is a known GPU failure.** Gate (c) can stall indefinitely on the material-zoo checker bug and two unmeasured scenes.
167:frequency-weighted-coverage target (the audit's own recommendation)?* This one
169:closures; a frequency-weighted target lets Principled-advanced + the common nodes
177:- Gate (b) uses the **frequency-weighted** corpus metric; raw counts are diagnostic only.
190:- **Standard scene corpus:** representative, attractive scenes covering every Cycles feature Astroray should support, with a generated coverage/parity report; design brainstorm with Astra → **pkg259** filed.
.astroray_plan/packages\pkg259-cycles-feature-coverage-reference-scenes.md

web search: site.docs.blender.org manual latest IES Texture node light groups passes sample count cryptomatte depth ...
web search: 
web search: https://docs.blender.org/manual/en/latest/render/shader_nodes/textures/ies.html
hook: PreToolUse
hook: PreToolUse Completed
exec
"C:\\Users\\hgcom\\AppData\\Local\\Microsoft\\WindowsApps\\pwsh.exe" -Command "Get-Content -Encoding utf8 -LiteralPath '.astroray_plan/packages/pkg259-cycles-feature-coverage-reference-scenes.md' -TotalCount 180" in C:\Users\hgcom\OneDrive\Astroray\Astroray_repo\Astroray-pkg259
 succeeded in 137ms:
# pkg259 — Cycles feature-coverage reference scene corpus

**Pillar:** 5
**Track:** B
**Status:** open — owner-requested 2026-09-07 evening; design phase needs a creative brainstorm with Astra before scenes are built
**Estimated effort:** 1 week (~20 h across sessions; Phase 0 one session, then one scene family per session)
**Depends on:** pkg229, pkg249, pkg253

---

## Goal

Before: parity, benchmark and addon-smoke work each pick their own tiny
scene (`metal_sweep`, three #729 corpus scenes, the pkg119b per-feature
single-sphere library, `benchmarks/showcase`), so coverage is accidental and
a Cycles feature that Astroray silently drops is only noticed when someone
happens to wire it. After: a standard, version-pinned corpus of
representative, deliberately attractive Blender scenes that together exercise
every Cycles feature Astroray is meant to support (materials, textures and
mapping, lights, world, geometry, camera, render settings, passes), each
scene carrying a manifest of the features it covers, with a generated
coverage-and-parity report that makes any Cycles/Astroray inconsistency
visible per feature. Benchmarks, parity gates, viewport measurements and
addon smoke tests all draw from this corpus instead of ad-hoc scenes.

---

## Context

Owner directive (2026-09-07 evening): constructing representative scenes
that cover "pretty much all features and materials and things that work in
Cycles that we would want to work in Astroray too" is too tedious to do by
hand and needs the rigour an agent can apply so no feature is overlooked;
the scenes should also be interesting and pretty, and their design may be a
creative brainstorm with GPT-6 Astra. This package is the Pillar-4 exit-gate
(c) instrument (three pinned scenes become the corpus) and the substrate for
gate (b)'s frequency-weighted coverage measurement. It serves Pillar 5.

---

## Evidence

- 2026-09-07: coverage matrix after the pkg253 scanner fix: SUPPORTED 114 /
  APPROXIMATED 50 / DROPPED-SILENT 363 of 527 enumerable features
  (`docs/blender_parity/coverage_matrix.json`).
- 2026-09-07: #729 corpus: `cornell_interior` (36 tri), `material_zoo`
  (8 450 tri), `hdri_exterior_hair` (1 922 tri + 2 400 strands); node ids
  per scene in `benchmarks/blender_parity/scenes/manifest.json`; only eight
  distinct shader node types across all three.
- 2026-09-07: pkg241 viewport measurements use `metal_sweep.blend` and a
  procedural 100k-triangle grid; the weekly bench uses `cornell` and
  `textured_plane`; none of these share a manifest or feature tags.

---

## Reference

- `benchmarks/blender_parity/README.md` (pkg119b harness),
  `scene_library.py::REFERENCE_SCENES`, `render_leg.py --export-blend /
  --load-blend / --report-only`, `manifest.json` schema (#729).
- `docs/blender_parity/coverage_matrix.json` and
  `scripts/generate_blender_parity_matrix.py` (pkg119 Phase A, pkg229
  re-audit) — the feature universe the corpus must cover.
- `.astroray_plan/docs/north-star-and-integration-gate-2026-09-07.md` §2
  gates (b) and (c).
- Cycles regression scene conventions: Blender's `tests/render/` layout
  (one feature per small scene, reference PNG per engine) — the structure to
  borrow, not the assets.
- `readme-showcase-render-feedback` memory (owner's composition rules:
  lift glass spheres, zoom, sample-heatmap AOV).

---

## Prerequisites

- [ ] pkg253 socket groups landed or at least enumerated, so the Principled
      scene knows which sockets are expected to render vs warn.
- [ ] Blender 5.2 reachable headless (`scripts/dev/launch_blender_mcp.ps1`
      for the GUI bridge; `blender -b` for exports); isolated profile per
      pkg236.
- [ ] Astra (gpt-6-astra) available through the Codex CLI for the Phase 0
      brainstorm, or the owner waives it.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `benchmarks/reference_corpus/README.md` | Corpus charter: scene families, naming, manifest schema, how a new Cycles feature gets a home, how to regenerate references. |
| `benchmarks/reference_corpus/build_corpus.py` | Runs inside Blender: deterministic builders for every scene (procedural where possible, packed assets otherwise), writes `.blend` + manifest with feature tags, node ids, object/light/world inventory, sha256. |
| `benchmarks/reference_corpus/scenes/<family>_<name>.blend` | The scenes. Families: `materials_hall` (every BSDF + Principled socket groups), `textures_mapping` (image/procedural textures, Mapping/TexCoord/UV/generated/object, bump/normal/displacement), `lighting_studio` (point/spot/sun/area incl. spread/shape, mesh emitters, IES, light groups), `world_sky` (HDRI incl. sun disc, Sky texture, colour world, rotation/strength), `geometry_zoo` (instances, hair/curves, volumes, motion blur, smooth/flat/auto-smooth, modifiers applied), `camera_lens` (DoF, clip, orthographic/panoramic, exposure/view transform), `render_settings` (passes, cryptomatte, adaptive, denoise on/off, film transparent). |
| `benchmarks/reference_corpus/coverage_report.py` | Joins the manifests against `coverage_matrix.json`: features covered by ≥1 scene, uncovered features, and per-feature Cycles-vs-Astroray verdict from the parity harness; emits `docs/blender_parity/corpus_coverage.md` + JSON. |
| `tests/test_reference_corpus_manifest.py` | Every `.blend` reopens, sha256 matches, manifest node ids match the file, each family covers its declared feature list, no feature in the matrix's SUPPORTED/APPROXIMATED set is uncovered (DROPPED-SILENT features may be uncovered but must be listed). |
| `.astroray_plan/docs/reference-corpus-design-2026-09.md` | Phase 0 output: brainstorm record (with Astra), per-scene concept, camera/composition notes, asset licences, which existing scenes are absorbed or retired. |

### Files to modify

| File | What changes |
|---|---|
| `benchmarks/blender_parity/scene_library.py` | `REFERENCE_SCENES` reads the corpus directory instead of the hard-coded three. |
| `benchmarks/blender_parity/render_leg.py` | `--load-blend` works for every corpus scene; non-vacuity checks come from the manifest, not code. |
| `benchmarks/blender_parity/harness.py` | Manifest loader + per-feature verdict export consumed by `coverage_report.py`. |
| `benchmarks/blender_parity/scenes/manifest.json` | The three #729 scenes are absorbed into the corpus (kept byte-identical or regenerated by `build_corpus.py`, recorded either way); this manifest becomes a pointer or is retired. |
| `scripts/benchmarks/weekly_local_bench.ps1` | Parity and showcase legs iterate the corpus families instead of `cornell`/`textured_plane`. |
| `scripts/run_parity.py` | Accepts corpus scene ids. |
| `benchmarks/viewport_parity/blender_driver.py` | Accepts corpus scenes as workloads (pkg241 keeps `metal_sweep` as its historical baseline). |
| `scripts/dev/known_issues_report.py` | Optional: link each open `addon-gap` issue to the corpus scene that reproduces it. |
| `scripts/README.md` | Register `build_corpus.py` and `coverage_report.py`. |

### Key design decisions

- **Rigour first, beauty second, but both required.** Coverage is proven
  by the manifest-vs-matrix test, not by eyeballing. Composition follows
  the owner's showcase rules; each scene must be something the owner would
  put in the README.
- **Deterministic builders over hand-authored files** wherever the feature
  allows it (procedural geometry, node trees built in code), so a scene can
  be regenerated when the schema changes; packed external assets only for
  image textures, IES profiles and HDRIs, each with a recorded licence.
- **One feature can live in several scenes; every SUPPORTED/APPROXIMATED
  feature must live in at least one.** DROPPED-SILENT features are
  represented by a "gap card" in the report, and where cheap, by a scene
  element so the drop is visible in the render (a missing Sky texture
  should show as black sky, not as an absent object).
- **Verdicts come from the existing harness** (pkg104 metrics, pkg119b
  triage buckets, per-channel mean ratio); this package adds scenes and a
  report, not a metric stack (§5b).
- **Phase 0 brainstorm with Astra** (owner request): one Codex session,
  read-only, producing scene concepts and a feature-to-scene allocation;
  the lead keeps final say and records disagreements.
- **Phases:** 0 design doc + allocation table → 1 `materials_hall` +
  `textures_mapping` (largest matrix share) → 2 `lighting_studio` +
  `world_sky` → 3 `geometry_zoo` + `camera_lens` + `render_settings` →
  4 harness/bench integration + coverage report + absorb #729 scenes.

---

## Acceptance criteria

- [ ] `tests/test_reference_corpus_manifest.py` green: every corpus scene
      reopens with matching sha256 and node inventory; zero uncovered
      SUPPORTED/APPROXIMATED features; DROPPED-SILENT features listed.
- [ ] `coverage_report.py` produces `docs/blender_parity/corpus_coverage.md`
      with a per-feature Cycles/Astroray verdict for every covered feature;
      the report is regenerable from a clean checkout with Blender 5.2.
- [ ] Each scene renders in both engines headless (CPU; GPU where the addon
      supports it) without an addon exception; renders saved under
      `benchmarks/reference_corpus/refs/` and inspected by the lead.
- [ ] Weekly bench and the pkg119b harness run on the corpus; the three
      #729 scenes are absorbed with their existing gates still passing.
- [ ] Design doc records the Astra brainstorm, the feature allocation, and
      asset licences.

---

## Non-goals

- Do not fix engine or addon defects the corpus exposes; file issues
  (`addon-bug` / `addon-gap`) and let the owning package fix them.
- No new comparison metrics or a new render driver.
- No Pillar 4 (astrophysics) scenes; a science corpus is a later package.
- No animation sequences; single frames only (motion blur uses
  sub-frame motion inside one frame).

---

## Progress

- [ ] 2026-09-07 evening — filed by the lead from the owner's directive;
      Phase 0 not started.

---

## Lessons

- (none yet)

web search: 
web search: IES Texture node angular distribution point light ...
codex
The main design risk is counting a connected socket whose effect is invisible or masked by another feature. I’m pairing each hero shot with a small crop or variant that makes the feature’s contribution clear. The Blender docs also flag two allocation issues: OSL needs a backend-specific treatment, and the sky-model list needs to match the pinned Blender version.

web search: 
web search: site:docs.blender.org/manual/en "IES Texture Node" "distribution" ...
web search: 
web search: site:docs.blender.org/manual/en/latest/render "Blackbody Node" "color" ...
web search: 
web search: site:docs.blender.org/manual/en/latest/render/cameras.html "Clip Start" ...
codex
The strongest creative change is to replace the texture wall with a print-and-textile workshop: continuous patterns across folds, seams, and beveled edges can look good while exposing mapping failures. I’d also separate the geometry and volume test shots within the cabinet set, and put AOVs, light groups, and Cryptomatte in a shared presentation built from the studio hero shot.

codex
I would keep the seven families, but build them around seven reusable places or sets. Each family gets a carefully composed hero image, several close views, and a few controlled variants. The important distinction is between “this feature appears somewhere in the scene” and “this image would visibly change if that feature stopped working.”

My proposed rule for claiming coverage is: **identify the object, active socket or property, conditions that make it matter, and image region where its effect can be seen.** A connected Coat Roughness socket with Coat Weight at zero earns no coverage. Neither does a procedural pattern hidden beneath another texture.

**1. materials_hall — a museum conservation gallery, shortly before opening.**

Keep the corridor, but make it an inhabited working space: a sculpture awaiting installation, folded protective cloth, restoration brushes, polished fittings, paper labels, and a suspended glass ornament. Shoot diagonally through three overlapping bays, with foreground objects framing the deeper gallery. The alcoves remain useful organizationally, but should not all compete for attention in the establishing image.

Reuse a small set of suitable subjects:

- A sculpted ceramic or wax head exercises Diffuse, Toon, standalone SSS, and Principled subsurface. Thin ears and a thicker cheek make radius, scale, and color effects readable under a controlled backlight.
- A curved metal fitting exercises Glossy, Metallic, anisotropy, and specular controls. A long reflected light strip gives the highlight an unmistakable shape.
- A lacquered object and folded velvet cover exercise coat and sheen. Coat Normal needs its own variant, with a smooth underlying surface, so its contribution cannot be confused with the base normal.
- A suspended glass ornament exercises Glass, Refraction, and Principled transmission. Put an asymmetric colored motif behind it and a pale receiving surface below; use smooth geometry, a downward camera, and a distant oblique light.
- A paper screen exercises Translucent; a clear label exercises Transparent and Principled Alpha. Restoration brushes provide actual strands for both hair shaders.

Use the same objects for standalone closures and their Principled counterparts. That comparison is useful, but each actual node still needs to be present and active.

For Add/Mix Shader, use visibly different inputs and include an intermediate mix factor. Two identical branches, or only endpoint factors, can conceal broken translation.

Make Ray Portal a small “impossible doorway”: it should reveal a blue room located elsewhere, while the ordinary view through the doorway leads toward a red wall. Test non-default position and direction separately. This gives the node a meaningful task; its default behavior can resemble transparency. Keep the destination simply lit because Cycles documents inefficient light sampling through portals. [Ray Portal documentation](https://docs.blender.org/manual/en/4.2/render/shader_nodes/shader/ray_portal.html)

Holdout deserves an alpha comparison alongside this gallery. An RGB beauty alone cannot establish whether it correctly cut a hole.

**2. textures_mapping — a printmaker’s and textile designer’s workshop.**

This is the family I would change most. A wall of illuminated samples will struggle to escape the old contact-sheet problem.

Instead, compose a large patterned fabric falling from a printing table, curved printing rollers, stacked ceramic reliefs, and hanging paper proofs. The fabric becomes the README subject: patterns continue across folds, seams, and an overhanging edge. Raking light reveals surface detail; the workshop supplies depth.

Give the procedural families natural homes: Wave and Checker on woven fabric; Noise and Voronoi on glazed reliefs; Brick on a miniature architectural panel; Gradient on a print; Magic and Gabor on decorative proofs; White Noise on a stippled ink sample. Reuse those surfaces for property variants.

For mapping, put an asymmetric registration mark across adjacent pieces. Test authored UVs, a second named UV map, generated coordinates, object coordinates, and missing-UV behavior. Translate, rotate, mirror, and non-uniformly scale the carrier in separate variants. A dropped transform should break registration, reverse a motif, or change its size.

The converter nodes need a more direct diagnostic treatment than a complex hero material can provide. Use a close view of the print proofs, with small independent graphs producing bands, contours, and color separations. Exercise:

- Math and Vector Math operations with inputs that distinguish the operation.
- Map Range and Clamp with values crossing their bounds.
- Mix with unequal inputs and intermediate factors.
- Curves and ColorRamp with visibly non-linear shapes.
- Combine/Separate with unequal channels, so a channel swap cannot disappear into gray.

Avoid chains whose errors cancel each other. The composite fabric proves integration; the simpler proofs establish individual behavior.

For bump, normal mapping, and displacement, reuse one embossed motif. Show it under raking light and against the silhouette. True displacement should alter the outline and occlusion; bump and normal mapping should have their own shading signatures. Include a coarse, readable version before testing fine detail.

**3. lighting_studio — a luxury object photographed for an auction catalogue.**

Use the conservation gallery’s glass ornament, brushed metal fitting, and velvet cloth on a curved paper sweep, with a raised platform behind them. This is already a stronger denoising subject than a generic sphere.

The four-light 2×2 presentation is excellent. Keep the camera and objects fixed. Include a curved reflective surface, a matte wall, and a narrow upright object casting a shadow: together they reveal source shape, illumination footprint, and penumbra.

Within that set:

- Point size and Sun angle get shadow-edge crops.
- Spot cone and blend get a wall footprint large enough to show both boundary and falloff.
- Area shape and aspect ratio get reflected-source crops.
- Area spread gets a side wall that falls outside the narrower distribution.
- Temperature gets neutral ceramic and several colored materials, with fixed white balance.
- Mesh emission gets a variant where its illumination of another object is clearly visible, beyond the emitter’s own brightness.

I would revise the “IES gobo” description. IES stores directional intensity, rather than an arbitrary projected image. Choose an asymmetric wall-washer or pronounced multi-lobed profile, positioned so those lobes are obvious on the backdrop. Its disappearance is an excellent tell. [IES documentation](https://docs.blender.org/manual/en/latest/render/shader_nodes/textures/ies.html)

Add light linking if it is in intended scope: a colored accent should illuminate one nominated object while leaving an adjacent receiver unaffected. A separate blocker tests shadow linking. [Light-linking documentation](https://docs.blender.org/manual/en/latest/render/lights/light_linking.html)

Do not normalize every diagnostic image to equal brightness. That would conceal power, temperature, or spread errors.

**4. world_sky — a coastal sculpture terrace.**

The observation deck is strong. Give it architectural purpose: curved windbreaks, a descending stair, a metal sculpture, a raised glass piece, and pale stone catching the light. Frame enough horizon to read the environment while looking downward toward the foreground subject.

Give the world three independent opportunities to prove itself:

- Open sky shows the background.
- The metal sculpture shows reflected environment structure.
- A shaded stone recess shows illumination arriving from the environment.

This catches the important case where the HDRI appears correctly behind the scene but contributes incorrectly to lighting.

Use the same terrace for HDRI rotation, strength, constant Background, and procedural sky variants. An asymmetric bright landmark in a diagnostic environment makes rotation obvious in both background and reflection. A slender post and its shadow provide a visual compass for sun direction.

The HDRI/Sky pair should share geometry, but each result must be compared with its corresponding Cycles reference. Two different lighting models should not be expected to match each other.

Also, black is only one possible failure signature. A dropped sky parameter may leave a plausible default sky. Pair low/high haze or different sun positions to expose an ignored control.

Pin the sky-model inventory to the Blender build. The current 5.2 documentation includes Multiple Scattering and describes Nishita-derived Single Scattering and Hosek/Wilkie as legacy options. [Sky documentation](https://docs.blender.org/manual/sv/5.2/render/shader_nodes/textures/sky.html)

The loved three-sphere sunset remains its own untouched showcase asset. The terrace can supply the new diagnostic views.

**5. geometry_zoo — an expedition cabinet being unpacked.**

Keep the cabinet, but divide its photography into solid specimens and illuminated volume specimens. Combining everything in one turntable image would make the difficult features too small.

The solid arrangement contains repeated mineral casts, a fur-lined case, bent specimen mounts, and a slowly turning mechanical vane:

- Instances occupy an intentional arc with distinct rotations and scales. Include a mirrored transform and material variation.
- Hair appears against a contrasting backing and at the silhouette. Include a sparse strand crop to reveal thickness, taper, and missing curves.
- Replace the sphere shading trio with a chamfered mechanical specimen containing broad flat faces and curved transitions. Smooth, flat, and angle-based smoothing become easier to distinguish.
- Compare a live modifier stack with its baked equivalent. They should match. Include the undeformed base only as an explicitly different third state; “modifier applied versus not applied” alone is ambiguous.
- Use the vane for rigid motion blur and a flexible ribbon for deformation blur. Both can be single-frame tests with sub-frame motion.

For volumes, use open specimen frames containing volume bounds, without additional glass shells. Backlight them with repeated bars or a striped plaque. Absorption reduces transmission through increasing thickness; scattering softens or obscures the background; emission remains visible in a lights-off variant. Change illumination direction to make anisotropy matter.

Reuse the bounds for Volume Scatter, Absorption, Principled Volume, and Coefficients, with their inputs isolated. A density-varying case should have a recognizable internal structure.

**The scanner needs separate geometry and volume categories.** A cabinet can remain their shared artistic home, but 35 volume-node rows say nothing about instance, modifier, curve, or motion-blur coverage.

**6. camera_lens — a clockmaker’s workshop.**

Reuse the gallery’s architectural shell, but furnish one long workbench with a foreground mechanism, a middle-distance hanging watch, and a far wall of small practical lights. This gives every camera a useful depth arrangement.

The four views become:

- A shallow-focus portrait of the mechanism, with isolated background lights large enough to reveal aperture blades, rotation, and ratio.
- An orthographic elevation of the bench and shelving, with repeated equal-sized objects at different depths.
- A panorama of the workshop, with an asymmetric doorway and ceiling detail revealing orientation and seams.
- A clipping demonstration using foreground and background objects whose removal uncovers a bright, unmistakable surface.

Focal length, sensor size, and shift need additional parameter variants of those rigs. Keep the camera position fixed when testing focal length; moving it to preserve framing would obscure the property’s contribution. For shift, use vertical shelving lines and a fixed target mark.

Add focus distance, orthographic scale, sensor fit, and image aspect ratio to the scope check. Treat panoramic projection modes as distinct cases where supported by the pinned build.

The most useful bokeh tell is a pair: polygonal versus circular aperture, followed by a rotation change. A single pleasing blur proves very little about aperture controls.

**7. render_settings — the auction photograph, examined six ways.**

Reuse the lighting-studio hero at a resolution where cloth texture, fine metal edges, glass, and shadows remain readable in the final presentation.

Make a six-panel pass sheet: beauty, depth, normals, custom AOV, a Cryptomatte selection, and sample count. A second presentation can cover denoising and convergence. The additional panels satisfy the owner’s request without shrinking everything into an unreadable dashboard.

For the custom AOV, write a distinctive motif and a nonzero scalar region. Compare Cycles and Astroray versions of that same pass. A blank custom AOV beside a working depth image is suggestive, but does not by itself show what the missing AOV should contain.

Light groups belong in this presentation too: show key, fill, and their reconstructed contribution. Cryptomatte should be demonstrated through an actual object selection, rather than a colorful raw ID image. Blender distinguishes custom shader AOVs, light-group passes, and Cryptomatte; its Sample Count pass is normalized by the maximum sample count. [Pass documentation](https://docs.blender.org/manual/en/latest/render/layers/passes.html)

For bounce limits, add a removable diagnostic arrangement around the same subject: opposed mirrors, stacked transparent sheets, a glass path, a diffuse recess, and the small volume frame. Set other limits high enough that the limit under test actually controls the result. Reflection count, transmitted detail, and illumination in the recess become visible tells.

For convergence, use a separately seeded, higher-spp reference outside the plotted series. Check that the reference itself is sufficiently stable. For denoising, compare the same noisy input before and after, plus the independent reference; preserve close-ups where smoothing could erase real detail.

Adaptive sampling and seed are different kinds of tests. Correctly implemented sampling changes need not produce an obvious change in a converged beauty image. Use actual sample counts and noise differences, rather than demanding a dramatic appearance change.

Several coverage omissions deserve attention before freezing the allocation:

| Omission or ambiguity | Concrete home and test |
|---|---|
| Image Texture coverage is largely absent from the supplied texture list | Printed labels: color versus Non-Color data, alpha, interpolation, extension outside UV bounds, projections, and named UV selection. Add UDIMs if intended. |
| Shader inputs beyond TexCoord | Workshop specimens using Geometry, Object Info, attributes/color attributes, Tangent, Fresnel/Layer Weight, and hair information. Each needs a visible consumer. |
| Light Path behavior | A gallery plaque whose direct appearance differs from its reflection, plus a transparent-shadow case. Test the relevant ray classes explicitly. |
| Graph translation | Nested groups, linked versus constant inputs, active material outputs, and texture-driven standalone BSDFs. Reuse existing subjects. |
| Displacement sub-cases | Scalar versus vector displacement, midlevel, scale, coordinate space, and sufficient subdivision. Use the relief silhouette. |
| Visibility and scene export | Camera visibility, shadow visibility, material slots, collection instances, negative scale, and custom normals. Use the cabinet. |
| Output and compositing behavior | Alpha over two backgrounds, shadow catcher if intended, actual pass delivery, and consistent color management. Use the studio photograph. |

There are also three scope corrections I would make explicit.

First, Blackbody and Wavelength are color-producing nodes in Cycles. Their tests can be attractive illuminated ceramic or glass exhibits, but should validate the Cycles color-node contract. They do not, by themselves, establish a physical emission spectrum or justify expecting a dispersed rainbow. [Blackbody](https://docs.blender.org/manual/en/4.2/render/shader_nodes/converter/blackbody.html), [Wavelength](https://docs.blender.org/manual/en/4.4/render/shader_nodes/converter/wavelength.html)

Second, OSL Script needs its own backend-qualified case. Cycles documents GPU OSL support through OptiX, with limitations. Keep a simple script-driven patterned object in the design, but place broader OSL compatibility in a later tranche with a gap card now. “Every possible OSL script” is not a finite socket-coverage target. [OSL documentation](https://docs.blender.org/manual/en/latest/render/cycles/osl/index.html)

Third, inventory Principled from the pinned build rather than treating “21 advanced inputs” as permanent. The current documentation includes thin film and thin-wall behavior, with interactions that can make other inputs irrelevant. Those interactions affect whether a test genuinely exercises a socket. [Principled documentation](https://docs.blender.org/manual/sr/5.2/render/shader_nodes/shader/principled.html)

For allocation, I would keep seven artistic families while changing their technical ownership:

- Split textures_mapping internally into textures, coordinates, utility graphs, and surface detail.
- Split geometry_zoo into geometry export and volumes.
- Let materials own hair shading; geometry owns strand export.
- Let lighting own light-group assignment; render_settings owns pass delivery and reconstruction.
- Let camera_lens own projection and aperture; render_settings owns exposure, display transforms, and output.
- Treat Freestyle as a separate line-rendering/output integration case, using the clockmaker elevation. It is not another material closure. [Freestyle documentation](https://docs.blender.org/manual/nb/latest/render/freestyle/view_layer/freestyle.html)

The strongest general visual devices are **continuity, silhouettes, occlusion, and paired states**: a pattern breaks across a seam; an embossed edge becomes smooth; a rear plaque wrongly appears; two intentionally different settings become identical. These remain legible at README scale. Show expected and actual crops on each gap card, including the active setting and any observed warning. Do not manufacture a black or magenta failure appearance if the renderer actually produced something else.

Finally, protect the meaning of the two gates. The roughly 50 frozen scene cases can share seven sets, but diagnostic variants must not accidentally inflate frequency weights through repeated easy nodes. Freeze which uses enter gate (b), and keep exhaustive diagnostic coverage visible alongside that score.

Keep exactly three designated assets for gate (c). Existing pins should remain until an explicit replacement is accepted. My eventual candidates would be the gallery interior, the textured workshop, and the HDRI terrace with a modest hair element, each carrying a few prominent non-vacuity checks. Retain a Cycles comparison as well: CPU and GPU can agree perfectly while sharing the same silent drop.

To control rendering cost, render the seven beauty views infrequently, reuse their passes, and spend routine budget on the small feature crops and changed-family variants. The expensive hero image provides context; the inexpensive close view supplies the evidence.
tokens used
81,796
I would keep the seven families, but build them around seven reusable places or sets. Each family gets a carefully composed hero image, several close views, and a few controlled variants. The important distinction is between “this feature appears somewhere in the scene” and “this image would visibly change if that feature stopped working.”

My proposed rule for claiming coverage is: **identify the object, active socket or property, conditions that make it matter, and image region where its effect can be seen.** A connected Coat Roughness socket with Coat Weight at zero earns no coverage. Neither does a procedural pattern hidden beneath another texture.

**1. materials_hall — a museum conservation gallery, shortly before opening.**

Keep the corridor, but make it an inhabited working space: a sculpture awaiting installation, folded protective cloth, restoration brushes, polished fittings, paper labels, and a suspended glass ornament. Shoot diagonally through three overlapping bays, with foreground objects framing the deeper gallery. The alcoves remain useful organizationally, but should not all compete for attention in the establishing image.

Reuse a small set of suitable subjects:

- A sculpted ceramic or wax head exercises Diffuse, Toon, standalone SSS, and Principled subsurface. Thin ears and a thicker cheek make radius, scale, and color effects readable under a controlled backlight.
- A curved metal fitting exercises Glossy, Metallic, anisotropy, and specular controls. A long reflected light strip gives the highlight an unmistakable shape.
- A lacquered object and folded velvet cover exercise coat and sheen. Coat Normal needs its own variant, with a smooth underlying surface, so its contribution cannot be confused with the base normal.
- A suspended glass ornament exercises Glass, Refraction, and Principled transmission. Put an asymmetric colored motif behind it and a pale receiving surface below; use smooth geometry, a downward camera, and a distant oblique light.
- A paper screen exercises Translucent; a clear label exercises Transparent and Principled Alpha. Restoration brushes provide actual strands for both hair shaders.

Use the same objects for standalone closures and their Principled counterparts. That comparison is useful, but each actual node still needs to be present and active.

For Add/Mix Shader, use visibly different inputs and include an intermediate mix factor. Two identical branches, or only endpoint factors, can conceal broken translation.

Make Ray Portal a small “impossible doorway”: it should reveal a blue room located elsewhere, while the ordinary view through the doorway leads toward a red wall. Test non-default position and direction separately. This gives the node a meaningful task; its default behavior can resemble transparency. Keep the destination simply lit because Cycles documents inefficient light sampling through portals. [Ray Portal documentation](https://docs.blender.org/manual/en/4.2/render/shader_nodes/shader/ray_portal.html)

Holdout deserves an alpha comparison alongside this gallery. An RGB beauty alone cannot establish whether it correctly cut a hole.

**2. textures_mapping — a printmaker’s and textile designer’s workshop.**

This is the family I would change most. A wall of illuminated samples will struggle to escape the old contact-sheet problem.

Instead, compose a large patterned fabric falling from a printing table, curved printing rollers, stacked ceramic reliefs, and hanging paper proofs. The fabric becomes the README subject: patterns continue across folds, seams, and an overhanging edge. Raking light reveals surface detail; the workshop supplies depth.

Give the procedural families natural homes: Wave and Checker on woven fabric; Noise and Voronoi on glazed reliefs; Brick on a miniature architectural panel; Gradient on a print; Magic and Gabor on decorative proofs; White Noise on a stippled ink sample. Reuse those surfaces for property variants.

For mapping, put an asymmetric registration mark across adjacent pieces. Test authored UVs, a second named UV map, generated coordinates, object coordinates, and missing-UV behavior. Translate, rotate, mirror, and non-uniformly scale the carrier in separate variants. A dropped transform should break registration, reverse a motif, or change its size.

The converter nodes need a more direct diagnostic treatment than a complex hero material can provide. Use a close view of the print proofs, with small independent graphs producing bands, contours, and color separations. Exercise:

- Math and Vector Math operations with inputs that distinguish the operation.
- Map Range and Clamp with values crossing their bounds.
- Mix with unequal inputs and intermediate factors.
- Curves and ColorRamp with visibly non-linear shapes.
- Combine/Separate with unequal channels, so a channel swap cannot disappear into gray.

Avoid chains whose errors cancel each other. The composite fabric proves integration; the simpler proofs establish individual behavior.

For bump, normal mapping, and displacement, reuse one embossed motif. Show it under raking light and against the silhouette. True displacement should alter the outline and occlusion; bump and normal mapping should have their own shading signatures. Include a coarse, readable version before testing fine detail.

**3. lighting_studio — a luxury object photographed for an auction catalogue.**

Use the conservation gallery’s glass ornament, brushed metal fitting, and velvet cloth on a curved paper sweep, with a raised platform behind them. This is already a stronger denoising subject than a generic sphere.

The four-light 2×2 presentation is excellent. Keep the camera and objects fixed. Include a curved reflective surface, a matte wall, and a narrow upright object casting a shadow: together they reveal source shape, illumination footprint, and penumbra.

Within that set:

- Point size and Sun angle get shadow-edge crops.
- Spot cone and blend get a wall footprint large enough to show both boundary and falloff.
- Area shape and aspect ratio get reflected-source crops.
- Area spread gets a side wall that falls outside the narrower distribution.
- Temperature gets neutral ceramic and several colored materials, with fixed white balance.
- Mesh emission gets a variant where its illumination of another object is clearly visible, beyond the emitter’s own brightness.

I would revise the “IES gobo” description. IES stores directional intensity, rather than an arbitrary projected image. Choose an asymmetric wall-washer or pronounced multi-lobed profile, positioned so those lobes are obvious on the backdrop. Its disappearance is an excellent tell. [IES documentation](https://docs.blender.org/manual/en/latest/render/shader_nodes/textures/ies.html)

Add light linking if it is in intended scope: a colored accent should illuminate one nominated object while leaving an adjacent receiver unaffected. A separate blocker tests shadow linking. [Light-linking documentation](https://docs.blender.org/manual/en/latest/render/lights/light_linking.html)

Do not normalize every diagnostic image to equal brightness. That would conceal power, temperature, or spread errors.

**4. world_sky — a coastal sculpture terrace.**

The observation deck is strong. Give it architectural purpose: curved windbreaks, a descending stair, a metal sculpture, a raised glass piece, and pale stone catching the light. Frame enough horizon to read the environment while looking downward toward the foreground subject.

Give the world three independent opportunities to prove itself:

- Open sky shows the background.
- The metal sculpture shows reflected environment structure.
- A shaded stone recess shows illumination arriving from the environment.

This catches the important case where the HDRI appears correctly behind the scene but contributes incorrectly to lighting.

Use the same terrace for HDRI rotation, strength, constant Background, and procedural sky variants. An asymmetric bright landmark in a diagnostic environment makes rotation obvious in both background and reflection. A slender post and its shadow provide a visual compass for sun direction.

The HDRI/Sky pair should share geometry, but each result must be compared with its corresponding Cycles reference. Two different lighting models should not be expected to match each other.

Also, black is only one possible failure signature. A dropped sky parameter may leave a plausible default sky. Pair low/high haze or different sun positions to expose an ignored control.

Pin the sky-model inventory to the Blender build. The current 5.2 documentation includes Multiple Scattering and describes Nishita-derived Single Scattering and Hosek/Wilkie as legacy options. [Sky documentation](https://docs.blender.org/manual/sv/5.2/render/shader_nodes/textures/sky.html)

The loved three-sphere sunset remains its own untouched showcase asset. The terrace can supply the new diagnostic views.

**5. geometry_zoo — an expedition cabinet being unpacked.**

Keep the cabinet, but divide its photography into solid specimens and illuminated volume specimens. Combining everything in one turntable image would make the difficult features too small.

The solid arrangement contains repeated mineral casts, a fur-lined case, bent specimen mounts, and a slowly turning mechanical vane:

- Instances occupy an intentional arc with distinct rotations and scales. Include a mirrored transform and material variation.
- Hair appears against a contrasting backing and at the silhouette. Include a sparse strand crop to reveal thickness, taper, and missing curves.
- Replace the sphere shading trio with a chamfered mechanical specimen containing broad flat faces and curved transitions. Smooth, flat, and angle-based smoothing become easier to distinguish.
- Compare a live modifier stack with its baked equivalent. They should match. Include the undeformed base only as an explicitly different third state; “modifier applied versus not applied” alone is ambiguous.
- Use the vane for rigid motion blur and a flexible ribbon for deformation blur. Both can be single-frame tests with sub-frame motion.

For volumes, use open specimen frames containing volume bounds, without additional glass shells. Backlight them with repeated bars or a striped plaque. Absorption reduces transmission through increasing thickness; scattering softens or obscures the background; emission remains visible in a lights-off variant. Change illumination direction to make anisotropy matter.

Reuse the bounds for Volume Scatter, Absorption, Principled Volume, and Coefficients, with their inputs isolated. A density-varying case should have a recognizable internal structure.

**The scanner needs separate geometry and volume categories.** A cabinet can remain their shared artistic home, but 35 volume-node rows say nothing about instance, modifier, curve, or motion-blur coverage.

**6. camera_lens — a clockmaker’s workshop.**

Reuse the gallery’s architectural shell, but furnish one long workbench with a foreground mechanism, a middle-distance hanging watch, and a far wall of small practical lights. This gives every camera a useful depth arrangement.

The four views become:

- A shallow-focus portrait of the mechanism, with isolated background lights large enough to reveal aperture blades, rotation, and ratio.
- An orthographic elevation of the bench and shelving, with repeated equal-sized objects at different depths.
- A panorama of the workshop, with an asymmetric doorway and ceiling detail revealing orientation and seams.
- A clipping demonstration using foreground and background objects whose removal uncovers a bright, unmistakable surface.

Focal length, sensor size, and shift need additional parameter variants of those rigs. Keep the camera position fixed when testing focal length; moving it to preserve framing would obscure the property’s contribution. For shift, use vertical shelving lines and a fixed target mark.

Add focus distance, orthographic scale, sensor fit, and image aspect ratio to the scope check. Treat panoramic projection modes as distinct cases where supported by the pinned build.

The most useful bokeh tell is a pair: polygonal versus circular aperture, followed by a rotation change. A single pleasing blur proves very little about aperture controls.

**7. render_settings — the auction photograph, examined six ways.**

Reuse the lighting-studio hero at a resolution where cloth texture, fine metal edges, glass, and shadows remain readable in the final presentation.

Make a six-panel pass sheet: beauty, depth, normals, custom AOV, a Cryptomatte selection, and sample count. A second presentation can cover denoising and convergence. The additional panels satisfy the owner’s request without shrinking everything into an unreadable dashboard.

For the custom AOV, write a distinctive motif and a nonzero scalar region. Compare Cycles and Astroray versions of that same pass. A blank custom AOV beside a working depth image is suggestive, but does not by itself show what the missing AOV should contain.

Light groups belong in this presentation too: show key, fill, and their reconstructed contribution. Cryptomatte should be demonstrated through an actual object selection, rather than a colorful raw ID image. Blender distinguishes custom shader AOVs, light-group passes, and Cryptomatte; its Sample Count pass is normalized by the maximum sample count. [Pass documentation](https://docs.blender.org/manual/en/latest/render/layers/passes.html)

For bounce limits, add a removable diagnostic arrangement around the same subject: opposed mirrors, stacked transparent sheets, a glass path, a diffuse recess, and the small volume frame. Set other limits high enough that the limit under test actually controls the result. Reflection count, transmitted detail, and illumination in the recess become visible tells.

For convergence, use a separately seeded, higher-spp reference outside the plotted series. Check that the reference itself is sufficiently stable. For denoising, compare the same noisy input before and after, plus the independent reference; preserve close-ups where smoothing could erase real detail.

Adaptive sampling and seed are different kinds of tests. Correctly implemented sampling changes need not produce an obvious change in a converged beauty image. Use actual sample counts and noise differences, rather than demanding a dramatic appearance change.

Several coverage omissions deserve attention before freezing the allocation:

| Omission or ambiguity | Concrete home and test |
|---|---|
| Image Texture coverage is largely absent from the supplied texture list | Printed labels: color versus Non-Color data, alpha, interpolation, extension outside UV bounds, projections, and named UV selection. Add UDIMs if intended. |
| Shader inputs beyond TexCoord | Workshop specimens using Geometry, Object Info, attributes/color attributes, Tangent, Fresnel/Layer Weight, and hair information. Each needs a visible consumer. |
| Light Path behavior | A gallery plaque whose direct appearance differs from its reflection, plus a transparent-shadow case. Test the relevant ray classes explicitly. |
| Graph translation | Nested groups, linked versus constant inputs, active material outputs, and texture-driven standalone BSDFs. Reuse existing subjects. |
| Displacement sub-cases | Scalar versus vector displacement, midlevel, scale, coordinate space, and sufficient subdivision. Use the relief silhouette. |
| Visibility and scene export | Camera visibility, shadow visibility, material slots, collection instances, negative scale, and custom normals. Use the cabinet. |
| Output and compositing behavior | Alpha over two backgrounds, shadow catcher if intended, actual pass delivery, and consistent color management. Use the studio photograph. |

There are also three scope corrections I would make explicit.

First, Blackbody and Wavelength are color-producing nodes in Cycles. Their tests can be attractive illuminated ceramic or glass exhibits, but should validate the Cycles color-node contract. They do not, by themselves, establish a physical emission spectrum or justify expecting a dispersed rainbow. [Blackbody](https://docs.blender.org/manual/en/4.2/render/shader_nodes/converter/blackbody.html), [Wavelength](https://docs.blender.org/manual/en/4.4/render/shader_nodes/converter/wavelength.html)

Second, OSL Script needs its own backend-qualified case. Cycles documents GPU OSL support through OptiX, with limitations. Keep a simple script-driven patterned object in the design, but place broader OSL compatibility in a later tranche with a gap card now. “Every possible OSL script” is not a finite socket-coverage target. [OSL documentation](https://docs.blender.org/manual/en/latest/render/cycles/osl/index.html)

Third, inventory Principled from the pinned build rather than treating “21 advanced inputs” as permanent. The current documentation includes thin film and thin-wall behavior, with interactions that can make other inputs irrelevant. Those interactions affect whether a test genuinely exercises a socket. [Principled documentation](https://docs.blender.org/manual/sr/5.2/render/shader_nodes/shader/principled.html)

For allocation, I would keep seven artistic families while changing their technical ownership:

- Split textures_mapping internally into textures, coordinates, utility graphs, and surface detail.
- Split geometry_zoo into geometry export and volumes.
- Let materials own hair shading; geometry owns strand export.
- Let lighting own light-group assignment; render_settings owns pass delivery and reconstruction.
- Let camera_lens own projection and aperture; render_settings owns exposure, display transforms, and output.
- Treat Freestyle as a separate line-rendering/output integration case, using the clockmaker elevation. It is not another material closure. [Freestyle documentation](https://docs.blender.org/manual/nb/latest/render/freestyle/view_layer/freestyle.html)

The strongest general visual devices are **continuity, silhouettes, occlusion, and paired states**: a pattern breaks across a seam; an embossed edge becomes smooth; a rear plaque wrongly appears; two intentionally different settings become identical. These remain legible at README scale. Show expected and actual crops on each gap card, including the active setting and any observed warning. Do not manufacture a black or magenta failure appearance if the renderer actually produced something else.

Finally, protect the meaning of the two gates. The roughly 50 frozen scene cases can share seven sets, but diagnostic variants must not accidentally inflate frequency weights through repeated easy nodes. Freeze which uses enter gate (b), and keep exhaustive diagnostic coverage visible alongside that score.

Keep exactly three designated assets for gate (c). Existing pins should remain until an explicit replacement is accepted. My eventual candidates would be the gallery interior, the textured workshop, and the HDRI terrace with a modest hair element, each carrying a few prominent non-vacuity checks. Retain a Cycles comparison as well: CPU and GPU can agree perfectly while sharing the same silent drop.

To control rendering cost, render the seven beauty views infrequently, reuse their passes, and spend routine budget on the small feature crops and changed-family variants. The expensive hero image provides context; the inexpensive close view supplies the evidence.

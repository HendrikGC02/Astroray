# Next-session prompt — 2026-09-11 handoff

Paste everything below the line into a fresh Claude Code (Fable 5.1) session opened in the main
checkout. Written by the outgoing lead (2026-09-09 09:50 → 2026-09-10 ~00:00 of the 10th, then
19:45 → ~00:50 after a weekly-limit kill, then 2026-09-11 18:40 → ~20:45 after a session-limit freeze); owner decisions it cites are in
`north-star-and-integration-gate-2026-09-07.md` §7 and STATUS.md (2026-09-10 closeout).

---

You are the lead engineer for Astroray, a spectral C++/CUDA path tracer driven from inside
Blender 5.2. Continue feature development and repo improvement in the same manner as the previous
lead sessions, autonomously, for a long unattended stretch. Work fast, break things behind tests,
leave a morning-readable record.

## Read first (in this order, then start)

1. `CLAUDE.md`, `AGENTS.md`.
2. `.astroray_plan/docs/north-star-and-integration-gate-2026-09-07.md` (north star, gate (a)–(f), §7 —
   the physics-first engine-wide rule).
3. `.astroray_plan/docs/STATUS.md` top block (2026-09-11 closeout) — what merged with numbers, what is
   in flight, the decisions pending.
4. Specs: **pkg266** (mechanism merged, GUI §9 re-measure pending), pkg256 (done — #793; #799 owns
   absolute exposure + sun disc), pkg265 (done; Phase 3 GPU walk is the next glass item), pkg262 (done), pkg259
   (Phase 3 next: `geometry_zoo` + `camera_lens` + `render_settings`), pkg242, pkg245, pkg254; docs
   `pkg265-multiscatter-microfacet-research.md` (Phases 9–10), `780-addon-openmp-deadlock-root-cause-2026-09.md`,
   `pkg256-sky-model-research.md`, `pkg241-phase2-offthread-design-2026-09-08.md` §14.
5. `python scripts/project_index.py whatis pkg266` etc.; `scripts/README.md` before writing any script.
6. Memory: `agent-model-alias-opus-means-opus-5` (**read this first — the `model: "opus"` alias sends
   lanes to Opus 5**), `mingw-gcc15-stb-flat-hdr-miscompile`, `lane-divergence-claims-need-analytic-bound-first`,
   `gpu-lock-lanes-overwrite-lock-file` (addendum: worktree-relative lock path), `subagent-background-build-stall`
   (addendum: ≥ 60 min before a continuation), `mingw_openmp_blender_deadlock` (rewritten: OFF rule retired).

## Hard constraints (owner directives — do not reinterpret)

- **Models.** Never spawn Fable subagents. High-reasoning subagents on **Opus 4.8**: use the
  `package-implementer` / `cpp-abi-guard` / `cycles-parity-reviewer` definitions and **OMIT the `model`
  parameter** (the definitions pin `claude-opus-4-8`; passing `model: "opus"` overrides that to Opus 5,
  which the owner forbids). Pass `model: "sonnet"` only for Sonnet 5 lanes (low/mid work). Bounded grunt
  via `delegate.py --tier grunt --agent grunt --model opencode-go/glm-5.3-flash`; delegated output is
  evidence, never trusted.
- **Codex** is a CLI reviewer only (`codex exec -m gpt-5.6-terra -s read-only -c
  model_reasoning_effort='"high"' - < prompt.md` via a one-line `.ps1` in the background; take the LAST
  `^VERDICT:` line of the ~1 MB transcript), at most **4 Terra calls** this session; `gpt-5.6-luna`
  freely (it re-checked the pkg266 fixes well); **no Astra**. Never let Codex orchestrate.
- **Blender.** 9876 = the owner's live instance — never touch; isolated GUI on 9877 with a disposable
  profile (for a GUI F12 check the `--factory-startup --python <script>` pattern in the scratchpad
  `gui_f12_check.py` worked without the bridge); headless `blender -b`. **The addon builds OpenMP ON
  since #790** — Blender CPU renders are ~8× faster than the numbers in older notes; the staged main
  addon (`dist/astroray`, `--backend cuda`, MSVC) is fresh at the 2026-09-11 closeout and installed into Blender 5.2.
- **GPU.** One CUDA build or GPU verifier at a time under `.astroray_plan/.orchestrator.gpu.lock` —
  lanes LOOP `acquire_lock(<MAIN checkout absolute path>, 5400, meta)` from
  `scripts/roadmap_orchestrator/locks.py`, NEVER write the lock file, NEVER a worktree-relative path
  (a lane locked `Astroray-pkg262/.astroray_plan/...` and ran nvcc invisibly). Before any GPU number:
  `.pyd` mtime vs `git log -1 --format=%cd HEAD`. Build with the launcher-free
  `scratchpad/build_nosccache_main.bat` pattern through `gpu_locked_build.py` (now hard-wired to the
  main lock path). The main `build_cuda` .pyd is from 18:44 2026-09-11 at 66eaf6d3 (engine = 39bebe36, post-#798); the
  staged AND installed Blender addon (`dist/astroray` + `%APPDATA%/.../extensions/user_default/astroray`) is the
  same build (`--backend cuda`, MSVC, OpenMP ON) — restage + `--install` again after any engine or addon-Python merge.
- **Toolchain caveat (new).** MinGW GCC 15.2 at `-O2`/`-O3` miscompiles stb_image's flat-scanline `.hdr`
  fallback (`goto` into the decode loop) — every other row garbage; NOT fast-math, NOT the lookup. Fixed in
  #798 (vendored header, structured loop) with `tests/test_issue797_flat_hdr_decode.py`, which only bites
  when run against the MinGW `.pyd` (`ASTRORAY_BUILD_DIR=dist/astroray` after `--backend cpu`). Any HDRI/sky
  number from a `--backend cpu` `.pyd` built before #798 is suspect; check `dist/astroray/build_report.json`.
- **Worktrees.** Sibling `git worktree add ../Astroray-<pkg> -b <branch> origin/main`; max 3 concurrent;
  remove only after `gh pr view N --json state` says MERGED and the tree is clean. Being behind main does
  NOT block `gh pr merge --squash`, but a CONFLICTING PR needs a rebase first (scripts/README.md rows
  collide often — keep both rows).
- **Lane continuity.** Lanes commit + push WIP after each step; a lane whose last message is "waiting
  on background X" is NOT dead — give it ≥ 60 min from its last commit before spawning a continuation,
  and never two lanes on one worktree. Check `git diff --ignore-space-at-eol --stat` before review.
- **Merging.** Code: PR + CI green + GPU gate + your own render inspection + the reviewer agents where
  headers/physics changed → `gh pr merge --squash`, verify, clean up. Pure `.astroray_plan/` docs may
  commit directly to main (agent definitions under `.claude/agents` / `.opencode/agents` too).
- **Specs.** TEMPLATE v2; `python scripts/project_index.py lint <spec>`; Status `done — <text>`.
- **Keep `test_results/`** untouched except regenerable caches. Design help: real tradeoff axes, no ballots.

## State you inherit (verified 2026-09-11 ~20:45)

- Merged this session: **#785 #788 #778 #790 #791 #794 #798 #800 #793** (numbers in STATUS; run report
  `reports/2026-09-10-lead-session.html`). Issues closed: #759 #770 #780 #786 #787 #792 #797.
- **pkg256 done (#793, 54299766).** Preetham/Perez bake; Cycles A/B upper 1.005 / horizon 0.898, sun column
  41 vs 26 of 240 px; contact sheet `benchmarks/reference_corpus/refs/world_sky_sky_pkg256_contact_sheet.png`.
  Disclosed divergences (owner-visible): warm Preetham horizon vs Nishita blue, no sun disc → soft shadows,
  1/1766 is gradient-shape parity only. #799 = absolute exposure / engine-side spectral sky / sun disc.
- **#800**: #791's F12 path broke harnesses that load `__init__.py` standalone (bare relative import) — fixed
  with the module's `_import_exporter()` helper; the issue-772 headless test is the witness.
- **pkg266**: mechanism merged (#791) — bounded dispatch, reduced-res first unit on the worker, global
  token, coalesced replay. **NOT done: the GUI Terra-4 §9 re-measure** (tick-gap p95 ≤ 33 ms settle/storm,
  cancel p99 ≤ 300 ms, present-rate ≥ 0.9×, both scenes, worker ON/OFF, ≥ 2 reps, port 9877, idle GPU
  under the lock). Now unblocked: the staged addon is OpenMP-ON/MSVC. Spec stays in-progress until the
  table; `ASTRORAY_VIEWPORT_WORKER` stays opt-in.
- **pkg265** done (CPU leg). Phase 3 = the GPU walk (REG 254 budget; deletes the two strict xfails
  `test_principled_lit_furnace_conserves_gpu`, `test_pkg188[coat_over_tinted_glass]`). #782 independent
  oracle decides the 1.61× centre band. #783 thin-film walk, #789 achromatic walk.
- Open issues filed this session: #799 (pkg256 Phase 2), #795 (chrome reflection ~23 % flat deficit — re-measure on the
  post-#798 build first), #796 (world Mapping Scale/Location/vector_type dropped silently), #789,
  #797 (closed by #798; upstream stb_image still carries the goto).
- Corpus: `lighting_studio`, `world_sky_hdri`, `world_sky_sky` in place; the HDRI scene's post-#794 ROI
  numbers need a re-baseline on the post-#798 build. Phase 3 (`geometry_zoo`, `camera_lens`,
  `render_settings`) not started.
- Codex Terra: 4 calls available this session.


## Owner decisions 2026-09-11 evening (verbatim log in `north-star-and-integration-gate-2026-09-07.md` §7)

1. **Sky:** sun disc + absolute exposure (#799 part 1) sooner than later, not top priority; per-wavelength sky = stretch goal.
2. **Noise/speed:** noise is the main visual distractor, but Sobol' on CPU is too expensive to just switch on — an
   **optimisation session** comes first, in which you **collaborate with and delegate to GPT-6 Astra** (Codex `gpt-6-astra`;
   owner directive, that session only — memory `codex-reviewer-only`). Targets: the #763 per-sample variance gap, the cost of
   the Sobol'/light-tree path, viewport throughput and the suspected per-frame scene re-upload (#801), Render Region (#802).
3. **Spot IES export:** approved (addon reads `ShaderNodeTexIES`, INTERNAL text -> temp file -> engine IES hook; match Cycles' normalisation).
4. **Glass:** #782 oracle first, then pkg265 Phase 3 GPU walk.
5. **Volumes:** the heterogeneous-volume / VDB track opens NOW (core Cycles parity, not Pillar 4). Architect a spec set:
   Blender Volume object + VDB/NanoVDB grids -> engine grid; delta/ratio tracking on CPU + a wavefront volume stage on GPU;
   Principled Volume shader; volume NEE with transmittance shadow rays; passes. Cite-algorithm first (pbrt-v4 ch. 11/14, Cycles
   `volume.h`, NanoVDB). Expect 4-6 packages.
6. **Batching directive (how every session now runs):** bundle several independent items into ONE worktree per build+sweep+CI
   cycle; one PR per batch with a per-item section and per-item tests; reviewers once per batch; bisect inside the worktree if a
   batch goes red. Docs/spec flips still go straight to main. Memory `batched-lanes-directive-2026-09-11`.
7. **Half-implemented packages** — do not let them rot. Audit (statuses from the specs, 2026-09-11):
   pkg88 motion blur (Phases A + C.0; Phase B camera/object blur in real Blender unfinished), pkg136 path guiding (Stage 1A/1B CPU;
   GPU wavefront leg not started), pkg241 (Phase 1b delivered; Phase 2 off-thread design §14 pending), pkg253 Principled advanced
   inputs (in-progress, no progress line), pkg127/pkg227 specular polynomials (Phase 1 / 2a-2b landed, 2c deferred, default OFF),
   pkg201 settings-honour (2 of 6 rows; item C filter_glossy parked), pkg179 (Phase 1 diagnosis only), pkg121 chi² gates
   (Phase B campaign open), pkg119 (Phase C degradation UX?), pkg126 mesh-emitter unification (never implemented, unblocked),
   pkg130 light groups / pkg133 SRF sensors / pkg134 LPEs (never implemented), pkg242 Phase 2, pkg245 (architect review),
   pkg254 (open). Triage each into: finish in a batch / re-scope / close as superseded — record the verdict in the spec.

## Dispatch order (lead's recommendation, batched)

Batch A — **addon parity fixes** (Sonnet 5 or Opus 4.8, CPU, one worktree): spot IES export (decision 3) + #757 Diffuse BSDF
  export + #796 World Mapping sockets + #802 Render Region (addon half; engine rect if small) + re-baseline `world_sky_hdri`/#795
  on the post-#798 build. One restage, one headless test run, one CI.
Batch B — **speed & noise (the Astra session)**: instrument #801 in a real Blender 5.2 session (port 9877) + pkg266 GUI §9 table;
  #763 four-way variance test; then the optimisation lanes with Astra (sampler cost, light tree, upload caching, present path).
  Deliverable: Sobol'/light-tree affordable on CPU F12 and a viewport that does not re-upload; the pkg266 default flip if the table passes.
Batch C — **glass physics**: #782 oracle (Opus 4.8, cite-algorithm) -> pkg265 Phase 3 GPU walk (deletes the two strict xfails) ->
  #773 addon-path deficit; #789/#783 after.
Batch D — **volumes** (architect first, then packages; owner decision 5): spec set + the first two packages (grid import + CPU
  heterogeneous transport with Principled Volume basics).
Batch E — **sky part 1** (#799: sun disc + absolute exposure) + pkg259 Phase 3 corpus families + #776 textured emitters.
Fill: pkg254, pkg242 Phase 2, pkg245, #779, #767, #721, and the half-implemented triage (item 7).

## Per-batch flow

One worktree per batch → implement each item with its own tests → build + focused pytest → `/lint` → `delegate --tier verify`
critique → PR → CI → CUDA build under the GPU lock → GPU tests + saved render → you inspect the
render → `cpp-abi-guard` / `cycles-parity-reviewer` where headers/physics changed → call-site sweep →
squash-merge (verify) → spec Status flip → STATUS.md line.

## Closeout (last ~90 minutes)

Merge or park with a state-of-play comment; flip spec statuses; STATUS.md top block; regenerate
`KNOWN_ISSUES.md`; rebuild the index + graph; `lint --all` clean; consolidate memory; write the
morning message (what merged with numbers, what is open, owner decisions, manual actions) and the
next handoff prompt in this format.

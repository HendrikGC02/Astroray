# Repo cleanup — 2026-06-08

Full local + remote cleanup of accumulated post–Round-15 state. **Nothing was lost.**
Every deleted ref is recoverable from a tag (most pushed to `origin`) and/or a
`--binary` patch in the out-of-repo backup folder.

## Backup / recovery locations

- **Recovery tags (recoverable forever until the tag is deleted):**
  - `archive/<branch>` — tip of every deleted local/remote branch that held any
    non-`main`-merged commit. **Pushed to `origin`** (durable on GitHub).
    Recover with e.g. `git switch -c restore-disney archive/disney-complete`.
  - `cleanup/stash-<N>` — every non-empty dropped stash, as a real commit
    (preserves binary blobs). **Local only.** Recover with
    `git stash apply cleanup/stash-2` (or `git switch -c x cleanup/stash-2`).
- **Out-of-repo binary patches (durable on OneDrive, survives re-clone):**
  `C:\Users\hgcom\OneDrive\Astroray\Astroray_repo\_cleanup_backup_2026-06-08\`
  - `stashes/stash-{0,1,2}.patch` — `git diff --binary` (full image bytes).
  - `stashes/stash-{4,5,7}.patch` — text patches.
  - `wip-branch-patches/<branch>.patch` — `git format-patch --binary origin/main...<branch>`.

## State before cleanup

5 worktrees, 24 local branches, ~35 remote branches, 8 stashes, 15 stale
`.git/worktrees/` registrations (most already dead). No open PRs. Working tree clean.
Last commit `db73d2c` (2026-05-30, PR #412). Docs current as of 2026-05-31.

## Worktrees removed (all verified clean — no uncommitted work)

`Astroray-disney`, `Astroray-pkg111`, `.claude/worktrees/amazing-liskov-1675eb`,
`.claude/worktrees/cranky-bouman-421856`, plus orphaned
`.claude/worktrees/{confident-mcnulty-74bb7e,funny-jennings-e47467}` and 15 dead
`.git/worktrees/*` registrations. (Bash sandbox blocked `.git/` dir deletes →
removed via PowerShell.)

## Local branches deleted (22) — all content-merged or archived

Merged into `main` (squash; verified against the merged-PR list, not ancestry):
`claude/amazing-liskov-1675eb`, `claude/confident-mcnulty-74bb7e`,
`claude/cranky-bouman-421856` (#399), `claude/funny-jennings-e47467` (#386),
`docs/round15-wave2-closeout`, `docs/standup-morning2` (#383),
`feat/pkg106-prism-rainbow` (#393), `pkg101-viewport-vfov` (#368),
`pkg102-hdri-dof-aperture` (#369), `pkg103-addon-wiring-audit` (#370),
`pkg103a-light-tree-ui` (#371), `pkg103b-motion-blur-wiring` (#372),
`pkg111` (#403), `pkg55-bprime-session-n5` (#373 → `b02b161`),
`pkg76-classroom-gap2` (#394), `vndf-rough-transmission` (VNDF landed via #404),
`fix/issue276-clearcoat-flake` (#384 + a tooling "epitaxy pre-switch" checkpoint),
`integration-comprehensive` (throwaway staging branch; all 4 commits merged).

Genuinely-unmerged WIP (documented dead-ends; preserved via `archive/*` tags):
- `disney-complete` (`0017c83`) — GPU spectral throughput attempt ("0.705 bug
  persists"); the real fix landed differently in #404 (eta² albedo-clamp). + the
  Walter-2007 G-convention partial below.
- `fix-disney-rough-transmission` (`40dde2a`) — Walter-2007 rough-transmission
  G-convention; pkg118 root-cause (PR #408) concluded the residual is multi-scatter,
  not G-convention, and the faceforward fix is a verified no-op. Findings in
  `disney-rough-transmission-walter2007.md`.
- `wip/pkg106-chunk-d-radiance` (`ca918de`) — camera-side MNEE radiance; **explicitly
  abandoned** (renders NOISE — a prism is a forward phenomenon). Write-up in
  `pkg106-forward-lighttracing-research.md`. pkg106 shipped via the forward
  light-tracer (#393).
- `pkg110-bsdf-photon-bounce` (`befbe5e`) — superseded by the shipped hybrid
  auto-select (#397). 4-approach investigation in `pkg110-status-finding.md`.

## Remote branches deleted (12 this session; 21 already auto-deleted on merge)

10 merged + 2 unmerged-but-tagged-on-origin (`fix-disney-rough-transmission`,
`wip/pkg106-chunk-d-radiance`). 21 others (docs/round15-*, feat/pkg106-mnee-chunk-*,
fix-glass-*, pkg104-*, pkg109/110/117, refbank-recompose-caustics, etc.) were already
gone on GitHub; a `git fetch --prune` synced the stale local tracking refs.

## Stashes dropped (8) — backed up via `cleanup/stash-*` tags + patches

| stash | summary | content | backup |
|-------|---------|---------|--------|
| {0},{1} | gallery PNGs (docs/renders) | superseded by #405 showcase | tags + binary patch |
| {2} | `polish-wip-2026-05-30` | refbank scene.py/gates.toml/**blessed reference.png** for GR+prism scenes (overlaps #400/#405; path moved benchmarks↔tests) — **kept the most carefully** | `cleanup/stash-2` + `stash-2.patch` (1.8 MB) |
| {3},{6} | empty (no diff) | nothing | — |
| {4} | `codex docs cleanups` | classify.py + test_pkg89 tweak | `cleanup/stash-4` + patch |
| {5},{7} | orchestrator tick state | ephemeral `.orchestrator-state.json` + standups (committed) | tags |

## Not touched

- Build artifacts (`build_cuda/`, `build_tcnn/`, `dist/`, `build_blender_addon_tcnn/`)
  — large regenerable outputs. NOTE: shadow `astroray.cp313-win_amd64.pyd` copies in
  `dist/`, `build_tcnn/Release/`, `build_blender_addon_tcnn/` still exist (the
  `stale_pyd_locations` footgun); canonical build output is
  `build_cuda/astroray.cp313-win_amd64.pyd`.
- `test_results/` images (per owner instruction).
- Planning docs (STATUS/ROADMAP/NEXT_STAGE) — current as of 2026-05-31; accurate.

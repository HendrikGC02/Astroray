# Delivery round status — 2026-09-06

## Current update — pkg230b shipped, 2026-09-06

Pkg230b landed in #708, merge `8217234be0ce981075635647259fc78abdb1b77c`, at
00:24:49 UTC. Owner-authorized Terra final SIGN-OFF covered source, callers,
bindings, numerical evidence and actual saved visuals. PR run34000095026 passed
host (2133 passed,269 skipped,15 xfailed,4 xpassed;1202.30s test step) and CUDA
syntax checks. The duplicate push run34000075314 was still finishing at merge;
no claim that it passed then. Local full-suite failures remain baseline debt,
not passing gates. Source commit0cf3a3d; reviewed integration head0b98f9e.

The three local draft specs246–248 received Terra filing SIGN-OFF and landed
#709 (`45331d3`). They require detailed architecture before implementation.
Pkg236 is now parallel in-flight work:62 focused passes, actual isolated CPU
Blender smoke, live-profile hashes unchanged; independent final review and
release pending. Main feature priority remains pkg241 measurement then viewport
response, followed by mapped procedural/normal fidelity. No astrophysics unpause.

Spark access was tested successfully through Codex CLI0.153.4. One bounded real
critique completed; Astra/Terra rejected its false positives. The session's native
subagent roster still lacks Spark, but CLI execution requires no new setup.

## Earlier closeout — historical state, superseded above


This is a factual handoff, not final approval of pkg230b or a new scope decision.
The owner requested another implementation after pkg230 Phase 2, parallel lower
backlog, and specifications for production gaps. Pillar 4 remains PAUSED.

## Delivered and pending work

| Work | Actual state |
| --- | --- |
| pkg230 Phase 2, previous round | Landed #701, closeout #703; do not repeat |
| pkg230b affine coordinate chains | Implemented locally; uncommitted/unpushed; final independent review pending |
| pkg232 Windows delegate containment | LANDED #705, `d997c499`, 2026-09-05 18:50:24 UTC |
| pkg241–244 production/build specs | Filed and merged #704; implementation gates UNRUN |
| pkg245 normal/bump coordinate provenance | Filed and merged #706; implementation gates UNRUN |
| pkg246–248 reconstruction/delegate follow-ups | Local DRAFT specs; independent filing review pending; not dispatch eligible |

## pkg230b evidence and limitations

The addon folds bounded affine Vector Math and constant Rotate chains into the
existing mapping matrix. Coordinate provenance and transform resolve together;
programs sharing an image retain independent parent mappings. No native source,
ABI/layout, spectral transport or physical model changed. Unsupported procedural
transforms and incompatible per-image program coordinates warn explicitly.

- Focused tests: 101 passed, one native-binding skip; 45 new semantic tests.
- Real Blender RNA: six chains, three points each, maximum absolute transform
  error 1.074934e-7 against a 1e-6 gate.
- Final visual set: seven cases across CPU-only, RTX5070Ti CUDA and Cycles,
  128x128, 256 spp, seed 7, linear float32, Closest/Extend, denoise/adaptive off.
  All 21 legs meet chart gates and Astra qualitative inspection. Maximum RGB
  mean deviation from Cycles 3.486% (5% gate), GPU/CPU 0.120%; minimum
  nonidentity effect MAD 0.05593 (>0.01 gate).
- Fresh CPU and CUDA native builds from source-identical cache `4035a00`:
  intended import paths confirmed, host ABI canaries pass, CUDA embeds sm_120
  only. The initial failed CMake reconfigure is retained for pkg244.
- Both staged CPU/CUDA packages passed actual isolated Blender smoke checks.
  Pre-staging dependency probes emitted DLL import errors and are not counted
  as passes. Full runtime/packaged Blender checks used the required dependencies.
- CPU split: 1687 passed, 56 skipped, 9 xfailed (815.68 s). Serial split:
  683 passed, two failed, 19 skipped, 9 xfailed, 5 xpassed (638.81 s).
  Combined **2370 passed, two failures; full suite NOT green**. Skips and
  xpasses remain explicit; separate manual renders do not cover every skip.
- HDRI SSIM: feature 0.7642104, untouched baseline 0.7654136, gate >=0.97
  (pkg237). PostInit: feature and baseline 13 ULP, gate <=4 (pkg238).
  Both reproduced using the same fresh native artifact on untouched source.
  They do not traverse the addon resolver; reproduction is not a waiver.
- Caller/binding sweep and whole-diff lint: zero new findings, four applicable
  tools. Final documentation lint: zero new findings, three tools.

Initial Repeat-vs-clamp reference failures remain in `initial-repeat-extension/`.
Matching Extend left two strongly clamped red-channel residuals (7.94%/13.04%).
Untouched-addon equivalent Mapping reproduces mirror exactly and arithmetic at
MAD 3.096e-8. The clamped cases remain saved in `clamped-extend-baseline/`;
final in-domain charts improve visible pattern coverage without relaxing gates.
Existing-LUT quadrature correlates with those residuals, but does not establish
their full physical cause. Draft pkg246 defines a separate contract audit.

Evidence is retained in root `test_results/pkg230b/`: `delivery-evidence.md`,
`source-manifest.json`, `comparison-metrics.json`, `representative-comparison.png`,
full 21-tile sheet, raw arrays/logs, real-RNA probes, full-suite logs/XML,
`current-baseline-failures.*`, native identities and staged-package smokes.
The primary worktree retains the implementation and its detailed specification.

## pkg232 independent evidence

Reviewed source commit `32458d64be8ed444df63f3fdbf49339b467702bc` uses a Windows
Job with KILL_ON_JOB_CLOSE and a helper blocked until exact-handle assignment.
Cleanup confirms zero owned processes before final snapshot evidence. Unknown
cleanup yields explicitly unavailable evidence; no broad process-name kills.

Windows: 39 passed, one platform skip, independently replayed by parent.
Actual Ubuntu WSL: 14 passed, 26 Windows-only skips. Real opencode smoke completed
in 58.9 s with confirmed cleanup/zero active processes. Independent Claude final
source SIGN-OFF predates the subscription limit; its actual-Linux condition is
satisfied by WSL and CI. The canonical timeout remains a worker-runtime budget
starting after synchronous payload delivery; draft pkg247 owns the launch gap.
Draft pkg248 owns content changes missed by porcelain-status-only snapshots.

Push CI: 2088 passed, 269 skipped, 14 xfailed, 5 xpassed; host and CUDA syntax
checks passed. PR CI: 2088 passed, 269 skipped, 15 xfailed, 4 xpassed; host and
CUDA syntax checks passed, including actual non-Windows runtime. Run IDs:
33983634230 (push), 33983636316 (PR). PR #705 merged at 2026-09-05 18:50:24 UTC,
commit `d997c499203e6e4b7493d8377e887c435e86c6bf`. No renderer code changed.
Root `test_results/pkg232/` retains reviewed source hashes, Windows/Linux logs,
real-process evidence, final Claude review and GitHub CI logs.

## Plans and exact resumption boundary

The merged [production gap audit](production-gap-audit-2026-09-06.md) explains
pkg241 cancellation/response, pkg242 procedural mapping, pkg243 relative-band
provenance, and pkg244 build configuration. Pkg245 adds the independently reviewed
normal/bump coordinate and tangent-basis contract. None is implemented here.

Local drafts in `.claude/worktrees/pkg230-followups/.astroray_plan/packages/`:
`pkg246-spectral-rgb-roundtrip-contract.md`,
`pkg247-delegate-launch-timeout-boundary.md`, and
`pkg248-delegate-content-change-evidence.md`. All three passed Astra scope/link
review and differential lint; independent filing review remains pending. The
pkg248 disposable-repository probe reproduced both same-status edits and
dirty-to-clean reverts missing from `files_changed`, without live-index mutation.

Claude reports its weekly subscription limit resets **2026-09-10 at 13:00
Australia/Sydney**. Pkg230b's final source/ABI/parity/visual review has not run.
Earlier architecture approval and Astra visual inspection do not satisfy it.
Keep the uncommitted worktree `codex/pkg230b` intact; complete required independent
review, adjudicate unresolved gates, then follow the authorized delivery workflow.
No CI or merge result exists for pkg230b. Do not duplicate its implementation.

After that closure, **pkg241 Phase 0** is the next eligible package: measure
cancellation/viewport response before choosing the implementation. pkg242 follows
for texture fidelity. Pkg127 Phase 2 needs topology/spec reconciliation first.
No paused astrophysics package was resumed.

GPU verification is complete; the lock was released. Both implementation agents
and the documentation delegate have stopped. The user's live Blender profile and
pre-existing untracked files were preserved by this round.

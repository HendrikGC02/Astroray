# Stage 0 gate scoring, 2026-10-05

Build: main b0564cb4 + #1059 (`132c974+20261004T124622Z`, staged addon `dist/astroray`,
module SHA-256 `93cc14f0…915aac`, addon `__init__.py` `f85da10f…8b3bfe`). RTX 5070 Ti, Blender 5.2.
Reducer: `scripts/gate_manifest.py` (statuses computed, never hand-set).

| Row | Status | Measured | Limit | Evidence |
|---|---|---|---|---|
| (a) viewport latency | **RED** (by 2.1 ms) | GPU p95 102.1 ms, p99 116.0 ms; cancel-ack p95 40.5 / p99 44.6 ms; stale frames 0 | p95 ≤ 100, p99 ≤ 150; cancel p95 ≤ 200, p99 ≤ 300; 0 stale | local only (10 GB frames) |
| (b) weighted coverage | unmeasured | — | b1–b6 | population unratified; v4 freeze not run |
| (c) trio parity | **RED** (SSIM only) | max ROI channel gap 0.61 %; SSIM min 0.783 (terrace), gallery 0.963, workshop 0.978; CPU+GPU exit 0, pins, non-vacuity all true | ±5 %, SSIM ≥ 0.95 | local only (40 MB npy) |
| (d) native panels | **GREEN** | CPU+GPU: all 10 checks; mean rel. error max 0.0049, detail preservation min 0.9996 | ≤ 0.02, ≥ 0.95 | committed |
| (e) triage | **RED** | high_count 10 of 79 (was 21) | 0 | committed; `gate-e-triage-2026-10-05.md` |
| (f) clean install | unmeasured | — | 5 checks | needs a clean host |
| (g) production node score | unmeasured (row added 2026-10-06) | — | pass >= 6/8 on CPU and on GPU; zero silent pairs | not yet run; see below |

Row (g) (owner 2026-09-29 exit-gate row, 2026-10-06 "becomes manifest row (g)"): the pkg310 eight-material
production score. `gate_manifest.py` recomputes it from raw per-leg renders + render logs (ROI bands via
`mc_tolerance.score_material`, silent drops via `silent_drop_audit.audit_scene`, both against hash-pinned
`gates_production.toml` / `manifest.json` / `node_uses.json` / `coverage_matrix.json`); PASS = in band and
no silent pair. Owner thresholds: >= 6/8 passing on BOTH CPU and GPU (2026-10-06) and zero silent pairs
(2026-09-29), frozen in `ROW_SPEC["g"]`. Evidence command:
`PKG310_WORK=<dir> python scripts/build/gpu_locked_run.py <lane> -- python -m pytest tests/test_production_corpus.py -k "parity or silent"`
then `python scripts/gate_manifest.py --adapt-g <dir> --out docs/blender_parity/evidence/g/instrument.json`.

The committed `acceptance_manifest.json` carries (d) and (e) only. (a) and (c) were measured and
validated on this machine (full manifest: VALID), but their evidence is too large for git, so the
committed manifest keeps them unmeasured (the Batch A precedent). The full manifest and evidence are in
`%LOCALAPPDATA%\astroray-evidence\2026-10-05\` (`acceptance_manifest.full.json`, `a\`, `c\evidence_c\`).
Owner decision: whether to commit (c)'s 40 MB of `.npy`, or move gate evidence to LFS / a release asset.

## Notes

- (a) Formal instrument, worker ON (`--mode gate_a`, isolated GUI Blender on 9877, staged addon),
  3×100 camera + 3×100 material edits on both pinned scenes, 13 min. The pkg291 table already
  showed 100k material at p95 101.4 ms; this run agrees. Command:
  `blender_driver.py --mode gate_a --gate-a-build-id <id> --gate-a-workload …/pkg278_10k.json
  --gate-a-workload …/pkg278_100k.json --out docs/blender_parity/evidence --port 9877`.
- (c) The RED is SSIM on world_sky terrace-with-hair (480×270, 128 spp, seed 278). CPU and GPU
  renders are visually identical (geometry, hair, reflections, shadows, colour); both carry heavy
  independent floor speckle, which windowed SSIM penalises (memory
  `ssim-wrong-gate-for-independent-rng`). Means agree within 0.6 %. Batch A (2026-09-24): gallery gap
  4.59 % / SSIM 0.75, checker gap 66 %; all ROI gaps are now < 1 %. The harness must run Blender 5.2
  (`BLENDER_EXE`); it defaults to 5.1, which the validator rejects.
- (d) Fix in this PR: `gate_manifest.py` put `tests/` on `sys.path` before loading the reducer
  (`results_layout` import), otherwise row (d) recomputes RED. `raw_aggregate.json` is the raw
  `legs_{cpu,gpu}.json` pair, not the evaluated `gate_native_panels.json`.
- (e) Two blind passes (Claude Sonnet 5.5: 5 high; Codex Terra: 21 high), lead reconciliation.
  High: #36, #895, #946, #947, #955, #1033, #1042, #1045, #1047, #1051. Eleven issues rated
  not-applicable (fixed on main or not a bug); they are the lead's to verify and close.

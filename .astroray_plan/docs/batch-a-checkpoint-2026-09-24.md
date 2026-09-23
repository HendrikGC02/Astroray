# Batch A checkpoint — 2026-09-24 (pkg278 exit-gate instrumentation)

**Status:** pkg278 remains **open**. Measured RED rows are permitted by the
package's exit contract; the blockers below are prerequisites, not package
failures. This is **not** a Pillar-4 unpause, not an owner population
ratification, and not a default-flip decision.

**Identity:** source `1286d345`; native baseline `2e058c730b244a751d86a37a47e937a71f78908f`;
baseline build `2e058c7+20260923T134350Z`; module SHA-256
`2c4b8db88e219838e79aa4313ee7aa0c639bb8224fa1494da0ab353786f16461`.

**All actual render results below are the native origin/main baseline, NOT a
final candidate.** Evidence root: `C:/Users/hgcom/OneDrive/Astroray/astra_run/`.

## Gate rows

- **Parent canonical manifest** — `batchA-baseline-checkpoint/acceptance_manifest.json`
  validates ok (`true`, 0 errors) with A, D, E measured RED and B, C, F unmeasured.
  The newer E38 snapshot (`batchA-gate-e-refresh38/acceptance_manifest.json`)
  validates RED separately; the prior consolidated E37 manifest is historical
  and needs a refresh at closeout.
- **(a) viewport latency — RED.** `batchA-a-baseline-full-v2/` (raw instrument
  `a/instrument.json`; all 12×100 captures + 2523 files, ~7.9 GB, retained
  externally; representative PNGs visually inspected). GPU latency p95 = 339.5443 ms
  (limit 100), p99 = 347.5281 (limit 150); cancel-ack p95 = 60.3778 (limit 200),
  p99 = 62.7352 (limit 300); stale-after-ack = 0.
- **(b) weighted coverage — instrumented, no coverage credit yet.** Synthetic
  3-scene scorer validation and the V4 corpus producer/adversarial checks are
  complete; the current 9-scene population is unratified, so no real coverage
  credit counts before #823 lands on origin/main. Fresh graph-only 9-scene run
  had no errors; V4 baseline freeze is diagnostic-only
  (`batchA-b-integrated-baseline-freeze-v4.json`).
- **(c) trio parity — still RUNNING.** Full-budget capture with frozen producer
  `4c3e5a46` in `batchA-c-full-baseline-4c3e5a46`. Do NOT claim completed. The
  low-4spp diagnostic CPU-checker witness PASSed / GPU checker FAILed (known
  #762); diagnostic only, not acceptance.
- **(d) native panels — RED (valid).** `batchA-native-panels-v5/instrument.json`
  with actual CPU/GPU receipts, EXRs/NPYs/previews: mean relative error max
  0.09520223436 (limit 0.02), detail preservation min 0.9149686075 (limit 0.95);
  native adaptive ignored (#866), AOV missing (#867).
- **(e) triage — RED.** E38 issues independently rated by Terra plus a live
  query delta that is empty: 14 high, 7 medium, 3 low, 14 N/A. RED on 14 high.
- **(f) clean install — UNMEASURED.** Instrument and fake adversarial tests
  accepted; the actual developer host is correctly ineligible; an eligible clean
  Windows host is missing.

## Parent verification (1286d345)

Expanded pure/graph suite 247 PASS / 4 hardware deselected in 48 s; canonical
differential lint 0 new findings across all 4 tools. A separate baseline CUDA
addon build passed earlier. Still PENDING: final-candidate CUDA/stage/import
build, full suite, RTX sweep, the actual gate-(b) path, gate-(c) completion,
final reviews and CI. #823 (scanner) passed an independent review and 54
focused tests earlier but is NOT merged; no PR/merge yet.

## Reproduction entrypoints

Existing CLIs only — check `--help`/source before use; no flags are invented
here:

- `python scripts/gate_manifest.py --help` (manifest assembly/validation)
- `python benchmarks/reference_corpus/coverage_report.py --collect/--freeze-v4/--score`
  (`--score` is blocked on #823 until it merges)
- `python benchmarks/blender_parity/harness.py --gate-c ...` and `--gate-b-cases ...`

See `scripts/README.md` for the registered commands rather than duplicating
them here.

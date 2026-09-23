# Batch A checkpoint — 2026-09-24 (pkg278 exit-gate instrumentation)

**Status:** pkg278 remains **open**. The RED renderer rows can ship this
instrumentation checkpoint, but that does **not** mean all pkg278 gates are
complete. This is **not** a Pillar-4 unpause, not an owner population
ratification, and not a default-flip decision; defaults are held.

**Identity:** source `75055df0`; native baseline
`2e058c730b244a751d86a37a47e937a71f78908f` (same existing build/hash);
baseline build `2e058c7+20260923T134350Z`; module SHA-256
`2c4b8db88e219838e79aa4313ee7aa0c639bb8224fa1494da0ab353786f16461`.

**All actual render results below are the native origin/main baseline, NOT a
final candidate.** Evidence root: `C:/Users/hgcom/OneDrive/Astroray/astra_run/`.

## Gate rows

- **Consolidated baseline manifest** —
  `batchA-baseline-checkpoint/acceptance_manifest_v3.json` validates ok (`true`,
  0 errors) with A, C, D, E measured RED and B, F unmeasured.
- **(a) viewport latency — RED.** Raw instrument
  `batchA-a-baseline-full-v2/2026-09-24-gate-a-instrument.json`; all 12×100
  captures + 2523 files, ~7.9 GB, retained externally; representative PNGs
  visually inspected. GPU latency p95 = 339.5443 ms (limit 100), p99 = 347.5281
  (limit 150); cancel-ack p95 = 60.3778 (limit 200), p99 = 62.7352 (limit 300);
  stale-after-ack = 0.
- **(b) weighted coverage — instrumented, no coverage credit yet.** The current
  population is unratified, so no real coverage credit counts before #823 lands
  on origin/main (it needs an origin/main ancestor before credit); there is no
  actual candidate-B run yet.
- **(c) trio parity — COMPLETE, RED.** Full-budget capture with frozen producer
  `4c3e5a46` in `batchA-c-full-baseline-4c3e5a46`; 12 legs, 6044 s. Budgets:
  gallery 960×176×256, workshop 960×540×192, terrace 480×270×128, seed 278.
  Gallery channel gap 4.5851767% SSIM 0.7508117557; checker 66.216111% SSIM
  0.5900333524; hair 0.350189% SSIM 0.678453684; background 0.142461% SSIM
  0.564208567; HDRI 0.047308% SSIM 0.570168495. GPU checker negative-witness
  coverage 0 FAIL; CPU positive 0.424933 / negative 0.419571 PASS. Hair and
  HDRI witnesses PASS both; black-HDRI off control valid. Parent visually
  inspected all 3 representative scenes: GPU checker flat colours vs CPU
  texture, gallery CPU grainier, terrace grainy with visible HDRI/hair. No
  reference or threshold change.
- **(d) native panels — RED (valid).** `batchA-native-panels-v5/instrument.json`
  with actual CPU/GPU receipts, EXRs/NPYs/previews: mean relative error max
  0.09520223436 (limit 0.02), detail preservation min 0.9149686075 (limit 0.95);
  native adaptive ignored (#866), AOV missing (#867).
- **(e) triage — RED.** E39 (`batchA-gate-e-refresh39/`) independently rated:
  14 high, 7 medium, 4 low, 14 N/A. RED on 14 high (addon).
- **(f) clean install — UNMEASURED.** Instrument and fake adversarial tests
  accepted; the actual developer host is correctly ineligible; an eligible clean
  Windows host is missing.

## Parent verification (75055df0)

259 focused + graph tests PASS / 4 hardware deselected in 54.17 s; canonical
differential lint 0 new findings across all 4 tools. The independent C adapter
review of 75055df0 ACCEPTed after actual CLI plus raw stdout/stderr, execution
and mask receipt checks; the original v1 generic VALID did not validate C.
Still PENDING: final-candidate CUDA build (currently running), stage/import,
full suite, RTX sweep, the actual gate-(b) path, runtime, final Opus review and
CI. #823 (scanner) passed an independent review and focused tests earlier but is
NOT merged; no PR/merge yet.

## Reproduction entrypoints

Existing CLIs only — check `--help`/source before use; no flags are invented
here:

- `python scripts/gate_manifest.py --help` (manifest assembly/validation)
- `python benchmarks/reference_corpus/coverage_report.py --collect/--freeze-v4/--score`
  (`--score` is blocked on #823 until it merges)
- `python benchmarks/blender_parity/harness.py --gate-c ...` and `--gate-b-cases ...`

See `scripts/README.md` for the registered commands rather than duplicating
them here.

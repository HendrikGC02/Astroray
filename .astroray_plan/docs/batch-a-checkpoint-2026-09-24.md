# Batch A checkpoint — 2026-09-24 (pkg278 exit-gate instrumentation)

**Status:** pkg278 remains **open**; this is a **partial** exit-gate
instrumentation delivery, not package completion. Pillar 4 stays **paused**,
defaults are **held**, and owner ratification of the nine-scene corpus
population is **pending**. An eligible clean Windows host for gate (f) is absent.

**Scope:** Batch A changes no production renderer C++ or addon implementation.
Baseline A/C rows are retained; candidate B/D runs and the full test runs are now
also retained.

**Identity:** native baseline
`2e058c730b244a751d86a37a47e937a71f78908f`. Candidate source `cd9ceac6` → build
ID `cd9ceac+20260923T201043Z`, pyd SHA-256
`56e686110dd7a87b5d5360f8514325093e3f669ae0298b72016be7f4652e6f9b`. After
Python-only mask/manifest repairs, source `17cc376c` → stage ID
`17cc376+20260923T204441Z`, pyd SHA-256
`da29f8de8a7437663135944299bbc54146b0d589a2ed6de301a60461f5a5fb11`. Evidence
root: `C:/Users/hgcom/OneDrive/Astroray/astra_run/`.

**Verification revisions:** the full-suite (`cd9ceac6`) and RTX (`17cc376`)
numbers below remain measured on those revisions, not on the later
scanner-proof Python repairs. The final scanner-proof/path source `8bc47b2a`
parent run: 162 passed, 1 skipped, 2 deselected, 13.46 s; canonical
differential lint found zero new findings across 4 tools; the independent
scanner-proof review ACCEPT clears the earlier external-CWD bug; aggregate v4
was revalidated with zero errors under `8bc`. Final Opus sign-off is received;
CI remains pending.

## Build & test

- Source `cd9ceac6` full suite: 3252 passed, 87 skipped, 19 xfailed, 1 known
  legacy XPASS, 6 warnings, 1695.61 s; native-panel opt-in enabled.
- Initial sccache CUDA build failed OS10054; canonical no-launcher retry passed
  (1692 s, sm120 + ABI).
- RTX17cc (`17cc376`): 883 passed, 24 skipped, 2449 deselected, 9 xfailed,
  1 legacy xpass, 3 warnings, 415.51 s.
- Module path/mtime/buildID/arch/canary verified; GPU lock released.

## Gate rows

- **Consolidated baseline manifest** —
  `batchA-baseline-checkpoint/acceptance_manifest_v4_subchecks.json` validates
  `true`, 0 errors; A/C/D/E RED, B/F unmeasured.
- **(a) viewport latency — baseline RED, numbers unchanged.** Raw instrument
  `batchA-a-baseline-full-v2/2026-09-24-gate-a-instrument.json`; all 12×100
  captures + 2523 files, ~7.9 GB, retained externally; representative PNGs
  visually inspected. GPU latency p95 = 339.5443 ms (limit 100), p99 = 347.5281
  (limit 150); cancel-ack p95 = 60.3778 (limit 200), p99 = 62.7352 (limit 300);
  stale-after-ack = 0.
- **(b) weighted coverage — instrumented, no formal coverage credit yet.**
  Diagnostic `batchA-b-17cc-staged-4spp/`: all 8 legs, 960×540, 4 spp, seed 7;
  all 24 artifact hashes verified. CPU canonical validator True, SSIM
  0.4960492551, dE 17.9594058; GPU False — only the genuine checker witness
  (negative coverage 0), SSIM 0.4365411699, dE 18.4865780. Both image comparisons
  FAIL, so no formal coverage credit. Eight raw image hashes are identical to the
  earlier cd9 run; parent visually inspected. The baseline/control mask-path
  defect was fixed independently with real runtime verification. #823 is
  implemented and tested but **not merged**; the actual landed scanner proof and
  the post-merge frozen B score remain pending, and the population is unratified.
- **(c) trio parity — COMPLETE, valid RED, numbers unchanged.** Full baseline
  capture with frozen producer `4c3e5a46` in
  `batchA-c-full-baseline-4c3e5a46`; 12 legs, 6044 s. Budgets: gallery
  960×176×256, workshop 960×540×192, terrace 480×270×128, seed 278. Gallery
  channel gap 4.5851767% SSIM 0.7508117557; checker 66.216111% SSIM 0.5900333524;
  hair 0.350189% SSIM 0.678453684; background 0.142461% SSIM 0.564208567; HDRI
  0.047308% SSIM 0.570168495. GPU checker negative-witness coverage 0 FAIL; CPU
  positive 0.424933 / negative 0.419571 PASS. Hair and HDRI witnesses PASS both;
  black-HDRI off control valid. Parent visually inspected all 3 representative
  scenes: GPU checker flat colours vs CPU texture, gallery CPU grainier, terrace
  grainy with visible HDRI/hair. No reference or threshold change. The typed C
  adapter 750 was accepted; the old generic v1 VALID did not validate C.
- **(d) native panels — valid RED.** Candidate `batchA-cd9-native-panels/`: real
  10 legs CPU/GPU. GPU mean relative error 0.0938045404 (limit 0.02) and denoise
  detail 0.9066895537 (limit 0.95); CPU adaptive detail relative error
  0.021277837 (limit 0.02). Adaptive-off ignored (#866) and AOV missing (#867) on
  both backends. Parent visually inspected. Prior baseline D numbers remain
  historical evidence.
- **(e) triage — RED.** E39 unchanged: 14 high, 7 medium, 4 low, 14 N/A (14 high
  = addon).
- **(f) clean install — UNMEASURED.** Instrument and fake adversarial tests
  accepted; the actual developer host is correctly ineligible and an eligible
  clean Windows host is absent.

## Reviews & audit

Independent reviews cover the scanner, the A/C/D/E/F producers/reducers, and the
repaired B controls. Evidence is a source/commit-bound hash-pinned structured
audit receipt — not a cryptographically signed proof. Final Opus sign-off is
received; CI is pending; no PR or merge yet.

## Reproduction entrypoints

Existing CLIs only — check `--help`/source before use; no flags are invented
here:

- Before a post-merge scanner proof, freeze, or score: `git fetch origin`.
- `python scripts/gate_manifest.py --help` (manifest assembly/validation)
- `python benchmarks/reference_corpus/coverage_report.py --collect/--freeze-v4/--score`
  (`--score` is blocked on #823 until it merges)
- `python benchmarks/blender_parity/harness.py --gate-c ...` and `--gate-b-cases ...`

See `scripts/README.md` for the registered commands rather than duplicating
them here.

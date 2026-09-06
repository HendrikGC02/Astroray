# pkg240 — CI workflow cost audit

**Pillar:** 5 (delivery tooling for Blender/DCC)
**Track:** A
**Status:** OPEN — detailed architect review required before implementation
**Estimated effort:** TBD at architect review
**Depends on:** none

## Goal

Audit CI workflow cost and trigger duplication in `.github/workflows/ci.yml`
before any deduplication or runner change. Produce a measured per-build /
per-test / per-queue / per-job walltime and supported-usage breakdown, and
assess whether the canonical split runner can be safely reused under CI
constraints. Detailed architect review selects the trigger policy and exact
implementation scope after the audit.

## Context / evidence

- `.github/workflows/ci.yml` triggers on **both `push` and `pull_request`**;
  the concurrency group `ci-${{ github.workflow }}-${{ github.ref }}`
  distinguishes their refs, so both events can run simultaneously.
- **PR #701** (head `4035a00`) produced simultaneous runs **33978571904 (push)**
  and **33978574168 (PR)**, each scheduling host + CUDA jobs. Both succeeded.
  Push host 16:40:13→17:08:46 = **28m33s**; PR host 16:40:13→17:06:02 =
  **25m49s**. Push CUDA 16:40:14→16:56:08 = **15m54s**; PR CUDA
  16:40:12→16:56:04 = **15m52s** (2026-09-05 UTC, check timestamps).
  These observed durations are neither billed-cost proof nor a speedup or
  new-regression claim; the prior successful PR is in the same broad range.
- **Historical successful PR #696 baseline** (statusCheckRollup timestamps,
  2026-09-05 UTC) — observed job durations, NOT a candidate speedup or billed
  cost proof: host 11:59:45→12:27:32 = **27m47s**; other host 11:59:32→12:28:45 =
  **29m13s**; CUDA 11:59:46→12:11:39 = **11m53s**; other CUDA 11:59:32→12:14:45 =
  **15m13s**.
- The Host Test step runs serial `python -m pytest tests/ -v`. Canonical
  `scripts/test/run_split.py` already exists: CPU-marked tests run through
  xdist; everything not positively CPU-classified stays serial. This round's
  local split measured CPU **342.08s** and serial **239.70s** on local hardware —
  these are **not** CI performance estimates.

## Investigation scope

1. Measure trigger duplication and per build/test/queue/job breakdown.
2. Inspect the tested head vs PR merge revisions before any deduplication.
3. Assess safe reuse of the canonical split runner under CI constraints.
4. Preserve: branch-only and PR/merge validation; full collected test coverage
   and skip/xfail/xpass semantics; serial/GPU/unclassified isolation;
   required-check names/reporting and docs-only skip behavior;
   trusted-context/fork permissions.

## Candidate existing scripts (extend, do not fork)

- `.github/workflows/ci.yml` and `scripts/test/run_split.py` (candidate
  extension points only). **No new parallel one-off runner.**

## Non-goals / risks

- No arbitrary test removal, timeout changes, threshold changes, CI
  secret/permission expansion, or unrelated engine optimization.
- No candidate speedup claim without measurements.
- Concurrent duplicate-job time must be accounted for separately from elapsed
  latency; local split timings are not CI estimates.
- No owner queue priority change; Pillar 4 remains PAUSED.
- Distinct from **pkg231** (LOCAL CUDA rebuild latency); coordinate only shared
  evidence, no priority promotion.

## Acceptance — all implementation gates UNRUN

- [ ] Capture baseline/candidate run IDs, source + event + toolchain/cache/
      hardware config, and queue/build/test/job/total walltime plus billed
      compute or supported usage data before any claim.
- [ ] Account for concurrent duplicate-job time separately from elapsed latency.
- [ ] Demonstrate collection/node-ID/marker and skip/xfail/xpass parity with the serial baseline.
- [ ] Prove safe CPU-parallel vs serial/GPU execution.
- [ ] Branch-only / internal-PR / fork-PR / docs-only matrix preserves
      required-check completion and trust boundaries.
- [ ] Measured benefit for the accepted change with no lost validation.
- [ ] Independent Astra/Claude review.

## Baseline audit recorded — 2026-09-06

See [CI baseline audit](../docs/pkg240-ci-baseline-audit.md) for four measured
push/PR runs, job/step latency and API billable fields. Host tests account for
90.1–91.7% of host job time in these samples. This is baseline evidence only;
no CI change or candidate speedup is claimed. Detailed architecture, candidate
collection/marker parity and event-matrix gates remain pending.

# pkg240 — CI baseline audit, 2026-09-06

Baseline evidence only. No CI/test strategy changed, no candidate speedup or
implementation completion is claimed. Measured while pkg236 PR711 runs.

## Actual run and step timings

Source: GitHub Actions run/job APIs via `gh run view --json` and per-run timing
API, captured under root `test_results/pkg240/`. Step timestamps have whole-second
resolution and include command startup/output overhead; pytest's own measured
seconds can differ. First-job gap is dispatch/wait/startup, not pure queue time.

All values below are seconds except the last column (API-reported milliseconds).

| Package/event/run | First-job gap | End-to-end | Host job | Build | Tests | CUDA job | CUDA setup | CUDA compile | Sum of job seconds | Billable Ubuntu ms |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| pkg232 push33983634230 | 3 | 1726 | 1712 | 105 | 1561 | 1020 | 126 | 888 | 2740 | 0 |
| pkg232 PR33983636316 | 3 | 1861 | 1847 | 104 | 1693 | 919 | 195 | 716 | 2774 | 0 |
| pkg230b push34000075314 | 3 | 1721 | 1708 | 102 | 1566 | 1221 | 229 | 985 | 2935 | 0 |
| pkg230b PR34000095026 | 40 | 1385 | 1335 | 86 | 1203 | 1014 | 130 | 877 | 2357 | 0 |

The host Test step occupies **90.1–91.7%** of its job. The two-event pairs sum
to 91.9 and 88.2 runner-job minutes respectively. These are sums of overlapping
job durations, not elapsed latency, CPU-seconds, billed charges or dollar costs.
The API reports zero billable Ubuntu milliseconds for all four samples; that
does not erase the observed runtime or establish a future pricing claim.

[Pkg232 push](https://github.com/HendrikGC02/Astroray/actions/runs/33983634230),
[pkg232 PR](https://github.com/HendrikGC02/Astroray/actions/runs/33983636316),
[pkg230b push](https://github.com/HendrikGC02/Astroray/actions/runs/34000075314),
[pkg230b PR](https://github.com/HendrikGC02/Astroray/actions/runs/34000095026).

## Revision, collection and hardware limits

The pkg232 pair reports head `32458d64`; pkg230b reports head `0b98f9e` in both APIs.
However, pkg230b PR Checkout logs show synthetic merge revision
`b74e9de9b23eb9a57dc09b9cb6c342aee11f038d`; push checkout is `0b98f9e`. Different
commit identity alone does not prove a different source tree. Branch-head and
merge-context validation are distinct obligations; matching API headSha is not
sufficient justification to delete either event wholesale.

The workflow requests ubuntu-latest, Python 3.13, host Release build with make -j4,
and CUDA 12.8 syntax checks for sm_75 with four compiler processes. Existing pip
and PractRand caches participate. Exact runner CPU/memory and equivalent cache
warmth are not established by this dataset, so these samples do not establish
performance stability. No per-test duration distribution is captured here.
Pkg230b push/PR each report 2133 passed, 269 skipped, 15 xfailed, 4 xpassed; pkg232's
xfail/xpass split varied despite the same passed count. No candidate parity claim.

## Next bounded experiment

After detailed architecture, run a non-gating matched-revision CI comparison:
existing serial command versus canonical `scripts/test/run_split.py`, initially
with a bounded worker count appropriate to recorded runner cores. Record actual
checkout/toolchain/cache/core/OpenMP settings, per-test durations and walltime.
Keep all existing required checks and trust permissions unchanged during trial.

Compare collected node IDs, effective markers, complete coverage and no overlap
between CPU/serial partitions, skips/xfails/xpasses and failures. The runner puts only
positively cpu-marked tests under xdist; unclassified/serial/GPU work must remain
serial. Evaluate oversubscription instead of assuming more workers are faster.
Do not adopt it unless a measured benefit survives equivalent validation.

Trigger deduplication is a separate decision after testing branch-only,
internal-PR, fork-PR and docs-only events and required-check completion. It may
reduce overlapping runner occupancy without reducing PR feedback latency.
CUDA-only change filtering also needs a complete dependency/trigger audit;
this report does not implement or approve it.

Astra checked raw timing arithmetic and rejected Spark draft overstatements
about differing commit contents, pure queue time and compute-seconds. Spark was
a bounded drafting worker. Package240 remains OPEN; collection-parity, candidate
benefit and event-matrix acceptance gates remain UNRUN.

Independent owner-authorized Terra review: SIGN-OFF to file the factual audit,
2026-09-06. Raw arithmetic and scope limits checked; no implementation approved.

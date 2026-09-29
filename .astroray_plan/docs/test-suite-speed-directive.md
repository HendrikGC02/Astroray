# Test-suite speed directive

Owner request 2026-09-29: find the slowest tests, make them cheaper, and chart
time per test area on every timed run. **Coverage must not drop:** every gate
still runs in the full profile, and no tolerance is loosened.

## 1. Baseline (measured 2026-09-29, RTX 5070 Ti, 8 cores, OMP_NUM_THREADS=8)

`pytest tests -q --durations=0 --junitxml` via `gpu_locked_run.py`, engine
built from `Astroray-al-293/build_cuda` (13:47). Result: 4587 cases, **45:11 wall**
(2700 s in test cases: call 2255 s, teardown 315 s, setup 128 s). There were 22
failures from a build/HEAD mismatch (the pkg296 and MetallicProg tests are newer
than that build). They don't affect the timings.

| Slice | Tests | Seconds |
| ----- | ----- | ------- |
| >= 10 s each | 46 | 1152 |
| >= 2 s each | 214 | 1901 |
| < 1 s each | 4209 | 564 |
| auto-class `cpu` / `gpu` / `serial` | 3224 / 1333 / 28 | 1346 / 1336 / 17 |

The heaviest 15 files take 55 % of the time. The machine has 8 physical cores,
so OpenMP CPU renders already use all of it. For the heavy cases, xdist only
helps the many small tests. The real lever is to **stop doing the same or
unneeded Monte Carlo work**.

Charts: `test_results/perf/test-suite-durations/` (before/after, by area, top-30
files, top-30 tests), made by `scripts/test/durations_report.py`.

## 2. Safety rules (every change must cite one)

- **R1 No gate removed, no tolerance loosened.** You may change a test's
  budget (spp, resolution, seeds). You may not change its threshold.
- **R2 Floor-governed tolerance** (`tol = max(floor, k*sigma)`): you may cut the
  budget only if the measured `k*sigma` at the new budget is <= 0.5*floor, over
  the test's own seeds. The tolerance then stays equal to the floor, so the
  detectable effect size is unchanged. Put the measured `k*sigma/floor` for the
  old and new budgets in a comment at the constant.
- **R3 Fixed threshold** (ratio/PSNR/RMSE gate): you may cut the budget only if,
  across >= 5 non-zero seeds at the new budget, `|mean - target| + 4*sd <= tol`
  and the new mean is within 1 sd of the old-budget mean. Record the numbers.
  If the test compares a noisy leg against a high-spp reference, don't touch
  the reference budget unless R2/R3 hold for the *combined* statistic.
- **R4 Sharing is free:** if a render with an identical (scene, backend, spp,
  seed, settings) runs more than once, compute it once. Use a module/session
  fixture or a dict cache keyed on those inputs. Never share a renderer that a
  test later mutates.
- **R5 Slow marker, never deletion.** `@pytest.mark.slow` removes a test from
  the fast profile only. A parametrized grid keeps a representative subset
  (corners / one per kind) unmarked, so the fast profile still covers it. No
  area may lose all of its fast tests.
- **R6** Seeds stay non-zero (seed 0 is the random sentinel). Adaptive sampling
  stays off where the test already disables it.
- **R7** A non-strict xfail test gets the same rules. It still runs in full.

## 3. Profiles

- **full** = every test, unchanged semantics: `python scripts/test/run_split.py`.
- **fast** = `-m "not slow"`: `python scripts/test/run_split.py --fast`. Target <= 5 min.
- Register the `slow` marker in `tests/conftest.py`. `run_split.py --fast` ANDs
  `not slow` into both passes. `--junit DIR` writes `cpu.xml`/`gpu.xml` and
  then calls `durations_report.py` on them, so every timed run regenerates the
  charts.
- CPU pass under xdist: use `-n 4` with `OMP_NUM_THREADS=2` (`-n auto` x all-core OpenMP
  would oversubscribe 8 cores 8x; memory `pc-hard-resets-under-combined-load`)
  and **`CUDA_VISIBLE_DEVICES=-1`** in that pass's env, so a misclassified test
  cannot launch concurrent CUDA (memory `cuda_verifier_concurrency`). Compare the
  pass/skip sets of that pass against the serial baseline junit. Any test that
  skips or changes outcome only under the hidden GPU is really a GPU test: tag
  it `@pytest.mark.gpu` (explicit marker wins), because otherwise it would run
  nowhere.
- CI (`.github/workflows/ci.yml`, no GPU, `pytest tests/ -v`) stays full. Only
  add `--durations=30`.

## 4. Offenders and fixes (before seconds)

| # | Test / file | s | Why slow | Fix | Rule |
| - | ----------- | - | -------- | --- | ---- |
| 1 | `test_issue883_nee_near_light.py::test_cpu_nee_on_off_match_analytic` x9 | 214 | NEE-off leg is 5 seeds x **8192 spp** per case; the tolerance is `max(1 %, k*sigma)` | Measure `k*hypot(sem_on, sem_off)/(0.01*on)` at 8192/4096/2048 spp for all 9 cases; take the lowest budget where it stays <= 0.5 | R2 |
| 2 | `test_corpus_v2_parity.py` (698 cases) | 259 | full corpus renders, 5-seed bands (a real long gate) | module `pytestmark = slow`; keep one cheap scene x backend unmarked if one renders in < 2 s | R5 |
| 3 | `test_pkg287_per_light_caustics.py` | 170 | 16384-spp PT reference per kind; the GPU test re-renders the CPU photon image the CPU test already made | cache `_caustic(kind, True, SPP_ON)` and `_reference(kind)` in a module dict; mark the 4 PT-reference cases slow | R4, R5 |
| 4 | `test_pkg265_nee_invariance.py` (15 cases) | 135 | 6 seeds x on/off per case; `tol = max(3 sigma, 3 % on)` | Measure `3*sigma/(0.03*on)`; cut spp where <= 0.5; mark slow except r0.5 principled of each family | R2, R5 |
| 5 | `test_pkg86_light_tree.py::test_variance_reduction_64_lights` (non-strict xfail) | 79 | 8 renders at 256x256x256 spp | Variance *ratio* is spp-independent: try 128x128 and 64 spp. Accept only if the ratio (1.41x today) moves < 10 %, otherwise keep; mark slow | R3, R7, R5 |
| 6 | `test_pkg227_raindrop_bow.py` (module fixture) | 67 | 240x200 @ 320 spp, depth 8 | measure the three gates' margins at half resolution / 160 spp; cut only if R3 holds; else mark slow | R3, R5 |
| 7 | `test_pkg127_reference_gates_poly.py` | 90 | the poly render is done in both tests | module fixture for the poly render (identical inputs) | R4, then R5 |
| 8 | `test_pkg277_coordinate_program.py::test_gpu_cpu_parity_{warped_checker,mapping_then_warp}` | 90 | 3 renders at 4096 spp, and the flip gate is noise-floor corrected (spp is load-bearing) | don't cut; share any unwarped-baseline renders between the two tests; mark slow | R4, R5 |
| 9 | `test_pkg258_env_nee_convergence.py::test_sun_disc_nee_convergence[cpu,gpu]` | 57 | a 65536-spp reference per backend (each backend's own ground truth, so the renders aren't identical and there's nothing to share) | mark slow | R5 |
| 10 | `test_issue840_lamp_radius.py` (15 cases) | 58 | ~4.7 s per case at 64 spp | profile render vs numpy `ref.radiance` first; fix whichever dominates without touching tolerances; slow except one POINT + one SPOT | R3/R4, R5 |
| 11 | `test_issue886_closed_emitter_mis.py` | 45 | 5 x 4096-spp NEE-off fixture; SEM 0.05 % against a 0.1 % gate (no headroom) | don't cut; mark slow | R5 |
| 12 | `test_pkg276_gpu_ies_parity.py` | 44 | a CPU+GPU render per profile/kind | mark slow except one profile | R5 |
| 13 | `test_pkg268_{heterogeneous_reference,volume_nee}.py`, `test_pkg227_mesh_*caustic.py`, `test_pkg89_wavefront_dedicated_nee.py`, `test_issue896_gr_exit_continuation.py` | ~150 | single 10-26 s statistical gates | R2/R3 budget check where the tolerance has a floor; otherwise mark slow | R2/R3, R5 |
| 14 | statistical chi2 grids (`test_chi2_bsdf.py`, `test_chi2_principled.py`) | 61 | 173+ tiny cases | mark slow except the grid corners | R5 |
| 15 | every other test >= 2 s after the fixes above | — | — | mark slow | R5 |

Also:

- `tests/statistical/test_engine_pdf_frame.py` calls `sys.exit(0)` at import
  when astroray is missing. That aborts the whole session with INTERNALERROR
  (it killed the first timed run). Use `pytest.importorskip("astroray")`.
- The teardown hook (`cuda_cleanup_and_error_check`, 315 s over 4569 items)
  should be measured on one GPU-heavy file with and without the probe. Only
  cheapen it (e.g. cache `gpu_available` and the cudart handle per session) if
  the probe itself costs > 5 % of the time. It stays a regression guard.

## 5. Durations report

`scripts/test/durations_report.py --junit before.xml [--junit after.xml]`
writes `durations_by_area_chart`, `durations_by_file_chart`, and
`durations_top_tests_chart` (PNG + JSON sidecar) under
`test_results/_runs/perf/test-suite-durations/`, and a before/after comparison
when given two files. Tune the area keywords until `other` is < 5 % of the time.
Add a `tooling` bucket (orchestrator, hooks, index, delegate, scripts) that
exists only in the chart; the test-results area taxonomy is unchanged. Promote
the before/after charts to the curated `test_results/perf/test-suite-durations/`.

## 6. Outcome (2026-09-30, am-962 build)

| Profile | Wall | Passes |
| ------- | ---- | ------ |
| before, serial `pytest tests` | 45.2 min | one serial run |
| full, `run_split.py` | **23.8 min (-47 %)** | CPU xdist 451 s + GPU serial 977 s |
| fast, `run_split.py --fast` | **7.2 min** | 143 s + 291 s; 3593 of 4646 tests |

- **Budget cuts (all measured, numbers in code comments):**
  - issue883 NEE-off: 8192 -> 2048/4096 spp in 5 of 9 cases (R2).
  - pkg265 furnace: 256 -> 64 spp (R2/R3).
  - pkg86 variance gate: 256² @ 256 -> 128² @ 64 (R3).
  - pkg227 bow: 320 -> 160 spp (R3). This makes it stricter: the fixed `sms_energy > 1` threshold is now 30 % of the signal, up from 15 %.
- **Caches (R4):** pkg287 CPU caustic, pkg127 poly render.
- **Slow marks:** 104 node ids in `tests/_slow_tests.py`, plus the marks in the file itself.
- **No threshold changed.**
- **Neither target was met:** the floor is the serial GPU pass. About 1130 sub-second tests account for ~200 s of it. Most are CPU-only tests in files that the file-level classifier tags `gpu`.
- **Next lever:** per-test `cpu` tags in mixed files, checked by the CUDA-hidden outcome diff, would move them into the parallel pass.

## 7. Done when

- The full profile runs every test that ran before (same pass/xfail/skip sets
  modulo build), and its wall time is measured and charted. Target <= 15 min.
  If that isn't reachable under R1-R7, report the measured floor and what would
  remain, and don't cheat the budget.
- The fast profile is <= 5 min, and every area still has fast tests.
- Every changed budget has its R2/R3 numbers in a code comment.

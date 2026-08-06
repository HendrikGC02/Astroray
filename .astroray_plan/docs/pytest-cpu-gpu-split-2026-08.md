# pytest CPU/GPU split + differential selection (latency lever 6)

Implements item 6 of the latency-lever ranking in
[`open-model-research-2026-08.md`](open-model-research-2026-08.md): a CPU/GPU
marker split so the CPU-only subset runs under `pytest-xdist -n auto` while
every test that touches CUDA stays strictly serial.

Baseline to beat: **407.5 s** full sweep (2026-08-06, Ninja/sm_120 build, 1563
passed).

## Why GPU tests must stay serial

`tests/conftest.py` has an autouse `cuda_cleanup_and_error_check` fixture that,
after each test, constructs a throwaway `CUDARenderer`, calls
`cudaDeviceSynchronize()` + `cudaGetLastError()`, and `pytest.fail`s on any
latent error (pkg85-B regression guard). It assumes **serialized, single-context
GPU access**. Memory `cuda_verifier_concurrency` documents false-positive
`illegal memory access` crashes when two CUDA-heavy workloads run at once on this
RTX. So the CPU-parallel pass must issue **no** concurrent CUDA work.

Two things guarantee that:

1. **Classification** (`tests/_gpu_classification.py`): a test module is `gpu`
   if its source or filename matches any real-CUDA trigger
   (`_gpu_*` bindings, `set_use_gpu(True)`, `upload_scene(`, `CUDARenderer`,
   `cudart*`, a `__features__`/`skipif` CUDA gate, or a
   `gpu|cuda|tlas|wavefront|optix|prewarm|sms_attempt` filename). Everything else
   is `cpu`. The split is deliberately **conservative** — a false positive
   (CPU test marked `gpu`) costs a few ms of serial time; a false negative (GPU
   test marked `cpu`) would run in parallel and reintroduce the exact flake this
   split prevents. When in doubt → `gpu`.

2. **Probe gating**: the fixture's CUDA probe now runs **only for `gpu`-marked
   tests**. `cpu` tests never launch CUDA, so there is nothing to check — and
   the parallel pass therefore issues zero concurrent CUDA driver calls.
   `gc.collect()` still runs for every test (cheap, parallel-safe).

## How the marker is applied

`conftest.pytest_collection_modifyitems` auto-tags every collected item `gpu` or
`cpu` from its module source (no per-file edits; new files are covered
automatically). An explicit `@pytest.mark.gpu` / `@pytest.mark.cpu` on a test
always wins. Audit the current split any time with:

```bash
python tests/_gpu_classification.py
```

Current split: **214 test files → 85 gpu (serial), 129 cpu (parallel)**.

## Running the suite

```bash
# Both passes, reports combined wall time:
python scripts/test/run_split.py

# Just the parallel CPU pass (fast inner loop; safe to run without a GPU):
python scripts/test/run_split.py --cpu-only

# Just the serial GPU pass:
python scripts/test/run_split.py --gpu-only

# Forward pytest args to both passes (after --):
python scripts/test/run_split.py -- -x -q
```

- CPU pass: `pytest -m cpu -n auto`. OpenMP is left at its default (all cores),
  **not** pinned to 1. The CPU subset is a handful of OpenMP-heavy reference
  renders (`reference_pt_production_parity`, `spectral_path_tracer`,
  `caustic_validation`, …) plus many fast tests. Pinning `OMP_NUM_THREADS=1`
  starves those renders of their threads and the slowest single-threaded test
  dominates the tail (measured: CPU pass alone >600 s, worse than the 407.5 s
  serial baseline). Since only a few tests spawn OMP threads, the transient
  8×N oversubscription costs far less than losing threads on the tail. Pin
  explicitly with `--omp N` / `ASTRORAY_TEST_OMP_THREADS` only after measuring
  your own hardware.
- GPU pass: `pytest -m "not cpu" -p no:xdist`. `not cpu` (rather than `gpu`)
  means anything left unclassified falls into the **serial** pass — the safe
  side.

## Differential test selection (testmon replacement)

`pytest-testmon` does **not** work here: it fingerprints Python bytecode and is
blind to changes inside the compiled `astroray.pyd`. `scripts/test/select_impacted.py`
maps changed source paths → impacted test files via an explicit keyword map,
with a broad "whole GPU suite" fallback when a widely-included core header
changes. It is a fix-loop accelerator, **not** a merge gate — the full split
suite still runs at closeout.

```bash
python scripts/test/select_impacted.py --base origin/main
git diff --name-only HEAD | python scripts/test/select_impacted.py --stdin
python scripts/test/run_split.py -- $(python scripts/test/select_impacted.py --base origin/main)
```

## Verification results

_(RTX 5070 Ti, Ninja/sm_120 build at HEAD 1245de3, 2026-08-06)_

Per-pass, per full run (CPU pass then GPU pass, sequential):

| run | CPU/parallel (`-m cpu -n auto`) | GPU/serial (`-m "not cpu"`) | total wall |
|-----|--------------------------------|-----------------------------|-----------|
| 1 | 1166 passed / 198.7 s | 424 passed (+2 env*) / 136.9 s | **335.6 s** |
| 2 | 1166 passed / 193.8 s | 424 passed (+2 env*) / 136.9 s | **331.5 s** |
| 3 | 1166 passed / 200.7 s | 424 passed (+2 env*) / 137.1 s | **337.9 s** |

**Mean total ≈ 335 s vs the 407.5 s serial baseline — ~18 % faster (−72 s).**
The CPU subset (1166 tests) now runs in ~197 s across 8 xdist workers; the GPU
subset (424 tests) runs serially in ~137 s.

**No CUDA illegal-access flakes in any of the 3 runs** — the concurrent-CUDA
hazard the serial pass exists to prevent did not occur. The gc-only teardown on
CPU tests plus the strictly-serial GPU pass held.

### The OMP pinning lesson

An initial `OMP_NUM_THREADS=1` CPU pass took **856 s** — worse than the serial
baseline — because the handful of OpenMP-heavy reference renders ran
single-threaded and the slowest one dominated the tail. Removing the pin (all
cores) dropped the CPU pass to **~197 s**. This is why the runner does not pin
OMP by default.

### *The 2 GPU-pass failures are pre-existing / environmental, not split-caused

Both were reproduced **in a plain serial run at this HEAD** (each run in
isolation, no xdist), so the split introduces no new failures:

1. `test_pkg55_perf_gate::test_wavefront_contact_sheet_ceiling` — asserts a
   1024spp wavefront render's median-of-3 wall time ≤ 1.0 s (warm pin
   0.57–0.71 s). Measured a **stable ~1.08–1.21 s** — in the split GPU pass, run
   standalone-serial, after a 4-min GPU idle, and across 5 back-to-back
   invocations (no downward trend). It does **not** recover, so it is not a
   transient the split creates.
   - The `.pyd` was verified native **sm_120 SASS** (`cuobjdump`; no sm_52/PTX
     fallback), so it is not a build-arch artifact.
   - The test's own header documents a **1.476–1.539× GPU clock-state spread**;
     0.71 s × 1.55 ≈ 1.10 s, matching the reading. The card is running this
     short (~1 s) render at a lower clock than when the 2026-07-25 pin was
     measured, and/or the wavefront path is genuinely slower at HEAD.
   - Either way it **fails in a plain serial `pytest` at this HEAD, in isolation**
     — so the CPU/GPU split does not cause it. It is flagged for the perf owner
     (repin vs real-regression bisect); repinning is out of scope here.
2. `test_blender_parity_matrix::test_blender_parity_matrix_generation` — spawns
   real headless Blender and `shutil.rmtree`s a shared `test_results/` dir under
   the OneDrive-synced worktree. Failed with `PermissionError [WinError 5]` on a
   **transient OneDrive file lock** of the leftover dir. Once the lock cleared,
   the test **passed standalone (1.6 s)** — so it is a flaky file-lock, not a
   real failure. It is classified `serial` (not `cpu`) precisely because it is
   file-fragile even before Blender starts, keeping it out of the parallel pass
   where the contention is worst.

Neither is fixed here: repinning the perf ceiling would mask a real regression
tripwire, and redirecting the Blender output dir is out of scope for the test
split. Both are flagged for the perf/CI owner.

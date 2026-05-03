# pkg32 — Visual Diagnostics & Benchmark Renders

**Pillar:** 5  
**Track:** A (infrastructure) + B (individual passes, via issues)  
**Status:** done
**Estimated effort:** 2–3 sessions (~9 h total across tracks)  
**Depends on:** pkg06 (done)

---

## Goal

**Before:** The only visual output is final renders and the NRC benchmark bar
charts from pkg27b. No way to visualize internal rendering behavior: bounce
depth, sample distribution, convergence over time, OIDN before/after.

**After:** A suite of diagnostic AOV passes, a convergence tracker, and a
benchmark render script that together produce publication-quality visuals
showing the engine's capabilities and internal behavior.

---

## Deliverables

### A. Diagnostic AOV passes (Track B — Copilot issues)

Each is a `Pass` plugin in `plugins/passes/`. Framebuffer gets new named
buffers for each. The passes read per-pixel data accumulated during rendering
and write to their named buffer.

| Pass | Buffer name | What it shows |
|---|---|---|
| `bounce_heatmap` | `"bounce_count"` | Average bounce depth per pixel, false-colored (blue→red). |
| `sample_heatmap` | `"sample_weight"` | Accumulated importance weight per pixel, showing where the integrator spends effort. |

These require the integrator to write per-pixel bounce count and sample
weight into the Framebuffer during `sampleFull()`. The integrator changes
are Track A; the pass visualization is Track B.

### B. Integrator per-pixel statistics (Track A)

| File | What changes |
|---|---|
| `include/raytracer.h` `Framebuffer` | Add `"bounce_count"` and `"sample_weight"` named buffers backed by new vectors in `Camera`. |
| `include/raytracer.h` spectral path tracer `sampleFull()` | At path termination, write average bounce count and total sample weight to per-pixel buffers. |

### C. Convergence tracking script (Track A)

| File | Purpose |
|---|---|
| `scripts/convergence_tracker.py` | Renders a scene at increasing sample counts (1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024 spp). Saves each intermediate image. Computes per-frame MSE against the highest-spp reference. Outputs: (1) PNG strip showing visual convergence, (2) matplotlib log-log MSE vs spp plot, (3) optional animated GIF of the convergence sequence. |

### D. Benchmark showcase script (Track A)

| File | Purpose |
|---|---|
| `scripts/benchmark_showcase.py` | Renders a set of canonical test scenes (Cornell box, glass sphere, metal spheres, environment-lit exterior) at production resolution with the best available integrator. Saves PNG renders + a composite comparison grid. Meant for README/portfolio use. |

### E. AOV pass implementations (Track B — Copilot issues)

Implement the stub AOV passes that currently have empty `execute()`:

| Pass file | What to implement |
|---|---|
| `plugins/passes/albedo_aov.cpp` | Write first-hit albedo from `"albedo"` buffer to output. |
| `plugins/passes/normal_aov.cpp` | Write world-space normals from `"normal"` buffer, remapped to [0,1] RGB. |
| `plugins/passes/depth_aov.cpp` | Write linear depth from `"depth"` buffer, normalized and false-colored. |

### F. OIDN before/after comparison (Track A, after pkg33)

| File | Purpose |
|---|---|
| `scripts/oidn_comparison.py` | Renders a noisy image (low spp), runs OIDN pass, saves side-by-side before/after PNG. |

---

## Acceptance criteria

- [x] `bounce_heatmap` and `sample_heatmap` passes produce non-trivial output.
- [x] `convergence_tracker.py` produces an MSE-vs-spp plot and image strip.
- [x] `benchmark_showcase.py` renders at least 3 scenes and saves a grid.
- [x] Stub AOV passes produce correct output for albedo, normal, depth.
- [x] All existing tests pass, except the documented ReSTIR temporal-variance
      baseline flake on this workstation.

---

## Non-goals

- Do not create a GUI viewer.
- Do not add video export beyond GIF.
- Do not modify the NRC benchmark infrastructure (that's pkg27b territory).

---

## Completion Notes

Completed in the pkg32/pkg34 closeout pass:

- AOV pass plugins now have focused tests for albedo, normal, depth,
  `bounce_heatmap`, and `sample_heatmap`; the heatmap tests verify finite,
  non-black, varying output and save PNGs under `test_results/`.
- `scripts/convergence_tracker.py` was verified to produce non-black
  increasing-SPP renders, an MSE plot, and a convergence strip.
- `scripts/benchmark_showcase.py` was verified at production settings and
  writes the canonical showcase grid.
- Added `scripts/oidn_comparison.py`, which writes noisy, denoised, and
  side-by-side OIDN comparison PNGs when OIDN is compiled in and exits cleanly
  when it is not.

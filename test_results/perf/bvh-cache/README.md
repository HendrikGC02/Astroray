# BVH cache, parallel BVH build, GPU path-pool floor

This change compared with main on an RTX 5070 Ti and a 7800X3D (OMP 8), 2026-09-30.
Each chart uses alternating rounds with burn-in, minimum of the warm calls.
Harness: `benchmarks/wavefront_baseline.py --cornell-pair`.
Raw record: `benchmarks/wavefront/pkg298_cornell_pair.json`.

- `repeat_render_chart.png`: unchanged 2M-triangle scene. CPU goes from 1.03 s to 0.017 s,
  GPU from 2.31 s to 0.71 s. The GPU remainder is `buildSceneArrays`, about 0.67 s per call.
- `bvh_build_chart.png`: first BVH build. Serial took 1.0 s; the new build takes 0.66 s on
  1 thread and 0.26 s on 8, with an identical tree.
- `render_time_chart.png`: 1024², 256 spp. Heavy 24.6 s to 23.6 s, simple unchanged at 12.0 s.
- `pool_throughput_chart.png`: 256² throughput rises from 88 % to 95 % of 1024².

# Stratified camera group: render cost

Tests: render time of v2_light_tree with the Sobol-Burley camera group vs the
white-noise camera; min of 3 after a burn-in, two interleaved rounds. CPU
16 spp (OpenMP-off addon build), GPU 256 spp (RTX 5070 Ti).

Verdict: CPU 12.59 s vs 12.66 s (-0.6 %), GPU 2.57 s vs 2.57 s; both inside the
+3 % gate. Shade kernels unchanged (REG 254, no spill); stageRegenKernel
REG 108 -> 102.

Provenance: pkg305, base main f0f8b5f6, `astra_run/AP/ap-305/timing`.

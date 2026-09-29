# Stratified camera group: render cost

Tests: render time of v2_light_tree (16 spp, CPU, OpenMP-off addon build) with
the Sobol-Burley camera group vs the white-noise camera; min of 3 after a
burn-in, two interleaved rounds.

Verdict (CPU): 12.59 s vs 12.66 s (-0.6 %), inside the +3 % gate. GPU leg
pending the CUDA build.

Provenance: pkg305, base main 16a9d288, `astra_run/AP/ap-305/timing`.

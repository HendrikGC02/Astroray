# Viewport edit latency (gate (a))
Edit dispatch to first correct Blender-presented frame, GPU, 2100x1221 region, 10k and 100k triangle grids,
camera (view_orbit) / material / object-move edits, 300 events per cell, 0 chain errors, 0 stale frames.
latency_chart: p95 per cell, worker ON vs worker OFF (synchronous); dashed line = gate (a) p95 100 ms.
Verdict: worker OFF wins five of six cells (10k camera 19.8 vs 99.7 ms, 100k move 23.5 vs 46.8 ms); 100k material
fails the gate in both modes (ON 101.4, OFF 137.2 ms). The worker default stays OFF.
before_during_after: orbit / material / move; "during" shows the coarse first frame, "after" the refined one.
Provenance: RTX 5070 Ti, Blender 5.2, quiet windows 2026-10-03 (CPU mean 30% ON / 20% OFF).

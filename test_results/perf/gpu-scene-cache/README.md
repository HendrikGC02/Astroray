# GPU device-scene cache between renders (#981)

Repeat `render()` of an unchanged scene, 16x16, 1 spp, RTX 5070 Ti, min of 6 warm calls after one cold call.
Harness: `benchmarks/wavefront_baseline.py --cornell-pair --devices gpu --skip-full --calls 7`.

- `repeat_render_chart.png`: heavy 2M-triangle Cornell 0.886 s -> 0.004 s; 12-triangle scene 0.004 s unchanged.
  The cold first call (1.6 s) is unchanged: it still flattens, uploads and builds the OptiX accel once.

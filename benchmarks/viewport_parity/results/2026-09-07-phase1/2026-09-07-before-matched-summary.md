# pkg241 Phase 0 — viewport / cancellation latency

Generated: 2026-09-07T08:41:28Z  
GPU: NVIDIA GeForce RTX 5070 Ti  
Bridge: 127.0.0.1:9876  
Protocol: 3x50 events/class, 5 warmup discarded, dispatch->present via POST_PIXEL draw handler.

Budgets (GPU): edit->present p95 <= 100 ms / p99 <= 150 ms; cancel-ack p95 <= 200 ms / p99 <= 300 ms.

Latency scales with viewport pixel count (region x nav-divisor) and the chunk/target sample budget; the region and preview_samples per config are recorded so numbers are interpretable.

## edit -> present (ms)

| scene | tris | region | prev_spp | device | class | n | p50 | p95 | p99 | max | rbp | start_div | trunc |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| metal_sweep | 2220 | 2112x829 | 1024 | gpu | camera | 150 | 107.63 | 429.89 | 440.98 | 441.65 | 1:150 | 1:34,2:116 |  |
| metal_sweep | 2220 | 2112x829 | 1024 | gpu | material | 150 | 942.87 | 964.01 | 1005.52 | 1010.06 | 2:150 | 1:150 |  |
| big | 101920 | 2100x1221 | 1024 | gpu | camera | 150 | 165.33 | 169.34 | 173.31 | 174.52 | 1:150 | 2:150 |  |
| big | 101920 | 2100x1221 | 1024 | gpu | material | 141 | 1388.7 | 1495.3 | 1538.23 | 1539.08 | 2:141 | 1:141 | Y |

## cancel full-stop floor (F12 render wall-time, ms)

| scene | device | samples | render_ms |
|---|---|---|---|

# pkg241 Phase 0 — viewport / cancellation latency

Generated: 2026-09-07T09:21:00Z  
GPU: NVIDIA GeForce RTX 5070 Ti  
Bridge: 127.0.0.1:9876  
Protocol: 3x50 events/class, 5 warmup discarded, dispatch->present via POST_PIXEL draw handler.

Budgets (GPU): edit->present p95 <= 100 ms / p99 <= 150 ms; cancel-ack p95 <= 200 ms / p99 <= 300 ms.

Latency scales with viewport pixel count (region x nav-divisor) and the chunk/target sample budget; the region and preview_samples per config are recorded so numbers are interpretable.

## edit -> present (ms)

| scene | tris | region | prev_spp | device | class | n | p50 | p95 | p99 | max | rbp | start_div | trunc |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| metal_sweep | 2220 | 2112x829 | 1024 | gpu | camera | 150 | 30.42 | 31.99 | 33.53 | 34.85 | 1:150 | 4:150 |  |
| big | 101920 | 2100x1221 | 1024 | gpu | camera | 150 | 61.3 | 63.49 | 69.92 | 83.45 | 1:150 | 4:150 |  |

## cancel full-stop floor (F12 render wall-time, ms)

| scene | device | samples | render_ms |
|---|---|---|---|

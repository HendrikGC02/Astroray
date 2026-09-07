# pkg241 Phase 0 — viewport / cancellation latency

Generated: 2026-09-06T22:54:19Z  
GPU: NVIDIA GeForce RTX 5070 Ti  
Bridge: 127.0.0.1:9876  
Protocol: 3x50 events/class, 5 warmup discarded, dispatch->present via POST_PIXEL draw handler.

Budgets (GPU): edit->present p95 <= 100 ms / p99 <= 150 ms; cancel-ack p95 <= 200 ms / p99 <= 300 ms.

Latency scales with viewport pixel count (region x nav-divisor) and the chunk/target sample budget; the region and preview_samples per config are recorded so numbers are interpretable.

## edit -> present (ms)

| scene | tris | region | prev_spp | device | class | n | p50 | p95 | p99 | max | rbp | start_div | trunc |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| metal_sweep | 2220 | 1583x603 | 1024 | gpu | camera | 150 | 235.92 | 242.29 | 260.29 | 278.49 | 1:150 | 1:150 |  |
| metal_sweep | 2220 | 1583x603 | 1024 | gpu | material | 150 | 348.97 | 369.81 | 408.06 | 427.57 | 1:150 | 1:150 |  |
| big | 101920 | 1574x888 | 1024 | gpu | camera | 150 | 44.91 | 46.93 | 65.25 | 66.14 | 1:150 | 4:150 |  |
| big | 101920 | 1574x888 | 1024 | gpu | material | 150 | 209.0 | 212.48 | 229.06 | 230.08 | 1:150 | 4:150 |  |

## cancel full-stop floor (F12 render wall-time, ms)

| scene | device | samples | render_ms |
|---|---|---|---|

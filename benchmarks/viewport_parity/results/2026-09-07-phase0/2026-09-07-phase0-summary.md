# pkg241 Phase 0 — viewport / cancellation latency

Generated: 2026-09-06T16:25:20Z  
GPU: NVIDIA GeForce RTX 5070 Ti  
Bridge: 127.0.0.1:9876  
Protocol: 3x50 events/class, 5 warmup discarded, dispatch->present via POST_PIXEL draw handler.

Budgets (GPU): edit->present p95 <= 100 ms / p99 <= 150 ms; cancel-ack p95 <= 200 ms / p99 <= 300 ms.

Latency scales with viewport pixel count (region x nav-divisor) and the chunk/target sample budget; the region and preview_samples per config are recorded so numbers are interpretable.

## edit -> present (ms)

| scene | tris | region | prev_spp | device | class | n | p50 | p95 | p99 | max | trunc |
|---|---|---|---|---|---|---|---|---|---|---|---|
| metal_sweep | 2220 | 2112x829 | 1024 | gpu | camera | 150 | 396.84 | 425.59 | 454.21 | 473.73 |  |
| metal_sweep | 2220 | 2112x829 | 1024 | gpu | material | 150 | 809.05 | 882.03 | 957.04 | 1001.45 |  |
| metal_sweep | 2220 | 2112x829 | 1024 | cpu | camera | 8 | 11422.4 | 11575.38 | 11575.38 | 11575.38 | Y |
| metal_sweep | 2220 | 2112x829 | 1024 | cpu | material | 4 | 22813.7 | 22835.96 | 22835.96 | 22835.96 | Y |
| big | 101920 | 2100x1221 | 1024 | gpu | camera | 150 | 162.06 | 165.01 | 169.48 | 174.96 |  |
| big | 101920 | 2100x1221 | 1024 | gpu | material | 145 | 1350.8 | 1378.45 | 1404.76 | 1426.59 | Y |
| big | 101920 | 2100x1221 | 1024 | cpu | camera | 25 | 1743.22 | 1756.64 | 1757.61 | 1757.61 |  |
| big | 101920 | 2100x1221 | 1024 | cpu | material | 10 | 13636.8 | 13666.73 | 13666.73 | 13666.73 | Y |

## cancel full-stop floor (F12 render wall-time, ms)

| scene | device | samples | render_ms |
|---|---|---|---|
| metal_sweep | gpu | 32 | 1106.9211000003634 |
| metal_sweep | cpu | 32 | 148511.38510000054 |
| big | gpu | 32 | 482.8612000001158 |
| big | cpu | 32 | 16147.954800000662 |

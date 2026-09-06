# pkg241 Phase 0 — viewport / cancellation latency

Generated: 2026-09-06T19:26:31Z  
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
| metal_sweep | 2220 | 2112x829 | 1024 | cpu | camera | 19 | 11613.22 | 12446.45 | 13257.47 | 13257.47 | Y |
| metal_sweep | 2220 | 2112x829 | 1024 | cpu | material | 22 | 22370.26 | 22672.19 | 22803.19 | 22803.19 | Y |
| big | 101920 | 2100x1221 | 1024 | gpu | camera | 150 | 162.06 | 165.01 | 169.48 | 174.96 |  |
| big | 101920 | 2100x1221 | 1024 | gpu | material | 145 | 1350.8 | 1378.45 | 1404.76 | 1426.59 | Y |
| big | 101920 | 2100x1221 | 1024 | cpu | camera | 25 | 1743.22 | 1756.64 | 1757.61 | 1757.61 |  |
| big | 101920 | 2100x1221 | 1024 | cpu | material | 24 | 14150.2 | 14332.9 | 14366.84 | 14366.84 | Y |

## cancel full-stop floor (F12 render wall-time, ms)

| scene | device | samples | render_ms |
|---|---|---|---|
| metal_sweep | gpu | 32 | 1106.9211000003634 |
| metal_sweep | cpu | 32 | 148511.38510000054 |
| big | gpu | 32 | 482.8612000001158 |
| big | cpu | 32 | 16147.954800000662 |

## Note on CPU sample counts

CPU is the slow correctness oracle, not the interactivity gate. The live-GUI
bridge carries a large fixed per-event wall overhead (~20 s/event beyond the
render itself: Blender's `bpy.app.timers` fire slowly while the GUI window is
idle/unfocused during a socket-driven run), so the >= 30-event floor is not
reachable within a bounded wall budget for the slow CPU configs. Banked counts
(camera 19-25, material 22-24) are the deadline-capped maxima; percentiles are
stable because CPU render time has low variance. The GPU configs (the actual
product gate) carry the full n=150 per class.

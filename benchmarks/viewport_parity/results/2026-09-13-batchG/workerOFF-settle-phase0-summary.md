# pkg241 Phase 2 — UI event latency while a viewport chunk renders

Generated: 2026-09-13T08:20:22Z  
Bridge: 127.0.0.1:9877  
Protocol: 2x10.0s per config, 2.0s warmup discarded, tick_s=0.005.

Budget: UI-latency-during-render p95 <= 33.0 ms (30 fps).

## tick-gap (ms) -- lower is more responsive; ~tick_s means fully decoupled

| scene | tris | region | engine | gpu | n_ticks | p50 | p95 | p99 | max | blocked_frac | render_frac | n_renders | n_presents | budget | trunc |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| metal_sweep | 2220 | 1583x603 | astroray | astroray-gpu | 1297 | 6.5 | 92.34 | 94.74 | 265.33 | 0.6754 | 0.5559 | 134 | 1297 | FAIL |  |
| metal_sweep | 2220 | 1583x603 | cycles | OPTIX x5 | 3132 | 6.5 | 6.66 | 7.57 | 9.81 | 0.2172 | 0.0 | 0 | 3132 | PASS |  |
| big | 101920 | 1574x888 | astroray | astroray-gpu | 328 | 6.53 | 140.16 | 164.97 | 352.48 | 0.9181 | 0.8766 | 136 | 328 | FAIL |  |
| big | 101920 | 1574x888 | cycles | OPTIX x5 | 3149 | 6.49 | 6.61 | 7.06 | 11.27 | 0.2131 | 0.0 | 0 | 3149 | PASS |  |

`render_frac` (Astroray only -- time inside `Exporter.render_viewport_frame` / total wall time) cross-checks `blocked_frac` (derived purely from tick gaps, so it applies to Cycles too, which has no Python view_update/view_draw hook to wrap): the two should track together on the Astroray rows, confirming the tick gaps are real render blocking and not a timer-throttling artifact. Cycles rows are expected to show `render_frac`=0/None (no Astroray render calls happened -- Cycles is native C++, no Python hook to wrap) alongside a low `blocked_frac` and a nonzero, growing `n_presents` (proving the viewport kept refining, not merely idling), demonstrating the decoupled reference the owner described.

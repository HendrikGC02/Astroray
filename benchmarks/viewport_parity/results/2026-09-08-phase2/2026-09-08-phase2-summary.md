# pkg241 Phase 2 — UI event latency while a viewport chunk renders

Generated: 2026-09-07T17:35:01Z  
Bridge: 127.0.0.1:9877  
Protocol: 3x10.0s per config, 2.0s warmup discarded, tick_s=0.005.

Budget: UI-latency-during-render p95 <= 33.0 ms (30 fps).

## tick-gap (ms) -- lower is more responsive; ~tick_s means fully decoupled

| scene | tris | region | engine | gpu | n_ticks | p50 | p95 | p99 | max | blocked_frac | render_frac | n_renders | n_presents | budget | trunc |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| metal_sweep | 2220 | 2112x829 | astroray | astroray-gpu | 275 | 157.82 | 179.48 | 194.42 | 208.31 | 0.9548 | 0.444 | 289 | 289 | FAIL |  |
| metal_sweep | 2220 | 2112x829 | cycles | OPTIX x3 | 4398 | 6.53 | 9.62 | 11.06 | 15.43 | 0.2673 | 0.0 | 0 | 2978 | PASS |  |
| big | 101920 | 2100x1221 | astroray | astroray-gpu | 188 | 232.62 | 274.21 | 283.41 | 284.83 | 0.9693 | 0.7451 | 197 | 197 | FAIL |  |
| big | 101920 | 2100x1221 | cycles | OPTIX x3 | 4578 | 6.52 | 8.13 | 9.4 | 11.07 | 0.2372 | 0.0 | 0 | 3137 | PASS |  |

`render_frac` (Astroray only -- time inside `Exporter.render_viewport_frame` / total wall time) cross-checks `blocked_frac` (derived purely from tick gaps, so it applies to Cycles too, which has no Python view_update/view_draw hook to wrap): the two should track together on the Astroray rows, confirming the tick gaps are real render blocking and not a timer-throttling artifact. Cycles rows are expected to show `render_frac`=0/None (no Astroray render calls happened -- Cycles is native C++, no Python hook to wrap) alongside a low `blocked_frac` and a nonzero, growing `n_presents` (proving the viewport kept refining, not merely idling), demonstrating the decoupled reference the owner described.

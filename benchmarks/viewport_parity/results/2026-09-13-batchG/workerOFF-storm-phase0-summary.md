# pkg241 Phase 2 — UI event latency while a viewport chunk renders

Generated: 2026-09-13T08:21:37Z  
Bridge: 127.0.0.1:9877  
Protocol: 2x10.0s per config, 2.0s warmup discarded, tick_s=0.005.

Budget: UI-latency-during-render p95 <= 33.0 ms (30 fps).

## tick-gap (ms) -- lower is more responsive; ~tick_s means fully decoupled

| scene | tris | region | engine | gpu | n_ticks | p50 | p95 | p99 | max | blocked_frac | render_frac | n_renders | n_presents | budget | trunc |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| metal_sweep | 2220 | 1583x603 | astroray | astroray-gpu | 160 | 218.34 | 229.75 | 231.28 | 235.43 | 0.9609 | 0.5436 | 178 | 178 | FAIL |  |
| big | 101920 | 1574x888 | astroray | astroray-gpu | 229 | 34.84 | 211.46 | 214.39 | 222.25 | 0.9431 | 0.5718 | 240 | 240 | FAIL |  |

`render_frac` (Astroray only -- time inside `Exporter.render_viewport_frame` / total wall time) cross-checks `blocked_frac` (derived purely from tick gaps, so it applies to Cycles too, which has no Python view_update/view_draw hook to wrap): the two should track together on the Astroray rows, confirming the tick gaps are real render blocking and not a timer-throttling artifact. Cycles rows are expected to show `render_frac`=0/None (no Astroray render calls happened -- Cycles is native C++, no Python hook to wrap) alongside a low `blocked_frac` and a nonzero, growing `n_presents` (proving the viewport kept refining, not merely idling), demonstrating the decoupled reference the owner described.

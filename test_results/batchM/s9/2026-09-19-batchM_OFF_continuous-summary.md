# pkg241 Phase 2 — UI event latency while a viewport chunk renders

Generated: 2026-09-19T00:29:37Z  
Bridge: 127.0.0.1:9877  
Protocol: 2x6.0s per config, 1.5s warmup discarded, tick_s=0.005.

Budget: UI-latency-during-render p95 <= 33.0 ms (30 fps).

## tick-gap (ms) -- lower is more responsive; ~tick_s means fully decoupled

| scene | tris | region | engine | gpu | n_ticks | p50 | p95 | p99 | max | blocked_frac | render_frac | n_renders | n_presents | budget | trunc |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| metal_sweep | 2220 | 2112x829 | astroray | astroray-gpu | 125 | 52.64 | 299.92 | 307.94 | 308.94 | 0.9492 | 0.5714 | 136 | 136 | FAIL |  |
| big | 101920 | 2100x1221 | astroray | astroray-gpu | 103 | 204.17 | 217.96 | 222.02 | 224.01 | 0.9583 | 0.5966 | 111 | 111 | FAIL |  |

`render_frac` (Astroray only -- time inside `Exporter.render_viewport_frame` / total wall time) cross-checks `blocked_frac` (derived purely from tick gaps, so it applies to Cycles too, which has no Python view_update/view_draw hook to wrap): the two should track together on the Astroray rows, confirming the tick gaps are real render blocking and not a timer-throttling artifact. Cycles rows are expected to show `render_frac`=0/None (no Astroray render calls happened -- Cycles is native C++, no Python hook to wrap) alongside a low `blocked_frac` and a nonzero, growing `n_presents` (proving the viewport kept refining, not merely idling), demonstrating the decoupled reference the owner described.

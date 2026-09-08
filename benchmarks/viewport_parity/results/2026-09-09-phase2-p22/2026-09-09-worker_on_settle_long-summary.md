# pkg241 Phase 2 — UI event latency while a viewport chunk renders

Generated: 2026-09-08T16:02:40Z  
Bridge: 127.0.0.1:9877  
Protocol: 2x20.0s per config, 2.0s warmup discarded, tick_s=0.005.

Budget: UI-latency-during-render p95 <= 33.0 ms (30 fps).

## tick-gap (ms) -- lower is more responsive; ~tick_s means fully decoupled

| scene | tris | region | engine | gpu | n_ticks | p50 | p95 | p99 | max | blocked_frac | render_frac | n_renders | n_presents | budget | trunc |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| metal_sweep | 2220 | 2112x829 | astroray | astroray-gpu | 3707 | 6.53 | 28.57 | 91.7 | 669.96 | 0.5379 | 0.0 | 0 | 3849 | PASS |  |
| big | 101920 | 2100x1221 | astroray | astroray-gpu | 3733 | 6.53 | 24.79 | 83.08 | 724.74 | 0.5344 | 0.0 | 0 | 3890 | PASS |  |

`render_frac` (Astroray only -- time inside `Exporter.render_viewport_frame` / total wall time) cross-checks `blocked_frac` (derived purely from tick gaps, so it applies to Cycles too, which has no Python view_update/view_draw hook to wrap): the two should track together on the Astroray rows, confirming the tick gaps are real render blocking and not a timer-throttling artifact. Cycles rows are expected to show `render_frac`=0/None (no Astroray render calls happened -- Cycles is native C++, no Python hook to wrap) alongside a low `blocked_frac` and a nonzero, growing `n_presents` (proving the viewport kept refining, not merely idling), demonstrating the decoupled reference the owner described.

## worker lifeline (ASTRORAY_VIEWPORT_WORKER=1) -- generation-tagged

| scene | engine | completed | presented | present_rate | commit p95 | cancel_ack p99 | cancel_ack_pump p99 | frame_age p95 | tex_tail p95 | mailbox_max | devices | cuda_err |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| metal_sweep | astroray | 0 | 0 | None | 345.81 | 569.42 | 572.39 | -5116.61 | 61.03 | 1 | [0] | 0 |
| big | astroray | 0 | 0 | None | 542.28 | 6378.22 | 775.49 | -4610.84 | 93.05 | 1 | [0] | 0 |

`commit p95` (P2.2 item 2) is the per-generation main-thread commit cost; a bounded commit is what lets `cancel_ack_pump p99` (P2.2 item 3 -- cancel_request to the pump draining the worker's idle) meet the <= 300 ms gate. `present_rate`/`frame_age` are only defined under `--ui-pattern settle` (item 4); the continuous stress ticker leaves `completed=0`.

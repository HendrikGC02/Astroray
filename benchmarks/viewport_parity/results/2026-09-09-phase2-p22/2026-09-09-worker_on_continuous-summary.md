# pkg241 Phase 2 — UI event latency while a viewport chunk renders

Generated: 2026-09-08T15:54:25Z  
Bridge: 127.0.0.1:9877  
Protocol: 3x10.0s per config, 2.0s warmup discarded, tick_s=0.005.

Budget: UI-latency-during-render p95 <= 33.0 ms (30 fps).

## tick-gap (ms) -- lower is more responsive; ~tick_s means fully decoupled

| scene | tris | region | engine | gpu | n_ticks | p50 | p95 | p99 | max | blocked_frac | render_frac | n_renders | n_presents | budget | trunc |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| metal_sweep | 2220 | 2112x829 | astroray | astroray-gpu | 865 | 7.69 | 259.3 | 329.45 | 384.39 | 0.8566 | 0.0 | 0 | 1014 | FAIL |  |
| big | 101920 | 2100x1221 | astroray | astroray-gpu | 1067 | 6.78 | 91.6 | 517.02 | 655.06 | 0.824 | 0.0 | 0 | 1184 | FAIL |  |

`render_frac` (Astroray only -- time inside `Exporter.render_viewport_frame` / total wall time) cross-checks `blocked_frac` (derived purely from tick gaps, so it applies to Cycles too, which has no Python view_update/view_draw hook to wrap): the two should track together on the Astroray rows, confirming the tick gaps are real render blocking and not a timer-throttling artifact. Cycles rows are expected to show `render_frac`=0/None (no Astroray render calls happened -- Cycles is native C++, no Python hook to wrap) alongside a low `blocked_frac` and a nonzero, growing `n_presents` (proving the viewport kept refining, not merely idling), demonstrating the decoupled reference the owner described.

## worker lifeline (ASTRORAY_VIEWPORT_WORKER=1) -- generation-tagged

| scene | engine | completed | presented | present_rate | commit p95 | cancel_ack p99 | cancel_ack_pump p99 | frame_age p95 | tex_tail p95 | mailbox_max | devices | cuda_err |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| metal_sweep | astroray | 0 | 0 | None | 244.81 | 509.3 | 442.71 | None | 21.48 | 1 | [0] | 0 |
| big | astroray | 0 | 0 | None | 440.79 | 799.72 | 785.21 | None | 96.9 | 1 | [0] | 0 |

`commit p95` (P2.2 item 2) is the per-generation main-thread commit cost; a bounded commit is what lets `cancel_ack_pump p99` (P2.2 item 3 -- cancel_request to the pump draining the worker's idle) meet the <= 300 ms gate. `present_rate`/`frame_age` are only defined under `--ui-pattern settle` (item 4); the continuous stress ticker leaves `completed=0`.

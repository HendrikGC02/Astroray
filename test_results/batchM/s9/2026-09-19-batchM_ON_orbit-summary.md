# pkg241 Phase 2 — UI event latency while a viewport chunk renders

Generated: 2026-09-19T00:27:39Z  
Bridge: 127.0.0.1:9877  
Protocol: 2x6.0s per config, 1.5s warmup discarded, tick_s=0.005.

Budget: UI-latency-during-render p95 <= 33.0 ms (30 fps).

## tick-gap (ms) -- lower is more responsive; ~tick_s means fully decoupled

| scene | tris | region | engine | gpu | n_ticks | p50 | p95 | p99 | max | blocked_frac | render_frac | n_renders | n_presents | budget | trunc |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| metal_sweep | 2220 | 2112x829 | astroray | astroray-gpu | 963 | 6.52 | 76.85 | 78.15 | 80.53 | 0.5993 | 0.0 | 0 | 1070 | FAIL |  |
| big | 101920 | 2100x1221 | astroray | astroray-gpu | 1388 | 6.51 | 13.41 | 13.58 | 29.93 | 0.4221 | 0.0 | 0 | 1544 | PASS |  |

`render_frac` (Astroray only -- time inside `Exporter.render_viewport_frame` / total wall time) cross-checks `blocked_frac` (derived purely from tick gaps, so it applies to Cycles too, which has no Python view_update/view_draw hook to wrap): the two should track together on the Astroray rows, confirming the tick gaps are real render blocking and not a timer-throttling artifact. Cycles rows are expected to show `render_frac`=0/None (no Astroray render calls happened -- Cycles is native C++, no Python hook to wrap) alongside a low `blocked_frac` and a nonzero, growing `n_presents` (proving the viewport kept refining, not merely idling), demonstrating the decoupled reference the owner described.

## worker lifeline (ASTRORAY_VIEWPORT_WORKER=1) -- generation-tagged

| scene | engine | completed | presented | present_rate | n_present | full_res_frac | final_full_res | commit p95 | cancel_ack p99 | cancel_ack_pump p99 | frame_age p95 | tex_tail p95 | mailbox_max | chunk_spp (p50/max) | samples/s | devices | cuda_err |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| metal_sweep | astroray | 0 | 0 | UNGRADEABLE | 8 | 1.0 | True | 70.84 | 79.18 | 82.48 | 21.48 | 15.92 | 1 | 3/4 | 0.46 | [0] | 0 |
| big | astroray | 464 | 464 | 1.0 | 469 | 0.0085 | True | 5.39 | None | None | 11.65 | 1.19 | 1 | 1/2 | 26.23 | [0] | 0 |

`commit p95` (P2.2 item 2) is the per-generation main-thread commit cost; a bounded commit is what lets `cancel_ack_pump p99` (P2.2 item 3/4 -- cancel_request(in-flight g) to the pump draining that gen's idle_drain(g)) meet the <= 300 ms gate. `present_rate` (terminal generations whose final publication blitted / eligible terminal generations) and `frame_age` (per-publication mailbox_enqueue -> first_blit, >= 0) are defined under `--ui-pattern settle`; when no eligible terminal generation exists (the continuous stress storm) `present_rate` is reported UNGRADEABLE, not 0. `chunk_spp` (p50/max) and `samples/s` (Batch G) are MEASURED: every presented chunk reports its accumulated spp, and `samples/s` is the sum of each generation's largest presented spp over the run wall — not inferred from a fixed chunk size.

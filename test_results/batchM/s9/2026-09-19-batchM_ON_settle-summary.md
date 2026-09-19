# pkg241 Phase 2 — UI event latency while a viewport chunk renders

Generated: 2026-09-19T00:25:47Z  
Bridge: 127.0.0.1:9877  
Protocol: 2x6.0s per config, 1.5s warmup discarded, tick_s=0.005.

Budget: UI-latency-during-render p95 <= 33.0 ms (30 fps).

## tick-gap (ms) -- lower is more responsive; ~tick_s means fully decoupled

| scene | tris | region | engine | gpu | n_ticks | p50 | p95 | p99 | max | blocked_frac | render_frac | n_renders | n_presents | budget | trunc |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| metal_sweep | 2220 | 2112x829 | astroray | astroray-gpu | 1494 | 6.52 | 17.11 | 18.35 | 195.18 | 0.3772 | 0.0 | 0 | 1575 | PASS |  |
| big | 101920 | 2100x1221 | astroray | astroray-gpu | 1278 | 6.51 | 21.45 | 105.35 | 190.5 | 0.4679 | 0.0 | 0 | 1524 | PASS |  |

`render_frac` (Astroray only -- time inside `Exporter.render_viewport_frame` / total wall time) cross-checks `blocked_frac` (derived purely from tick gaps, so it applies to Cycles too, which has no Python view_update/view_draw hook to wrap): the two should track together on the Astroray rows, confirming the tick gaps are real render blocking and not a timer-throttling artifact. Cycles rows are expected to show `render_frac`=0/None (no Astroray render calls happened -- Cycles is native C++, no Python hook to wrap) alongside a low `blocked_frac` and a nonzero, growing `n_presents` (proving the viewport kept refining, not merely idling), demonstrating the decoupled reference the owner described.

## worker lifeline (ASTRORAY_VIEWPORT_WORKER=1) -- generation-tagged

| scene | engine | completed | presented | present_rate | n_present | full_res_frac | final_full_res | commit p95 | cancel_ack p99 | cancel_ack_pump p99 | frame_age p95 | tex_tail p95 | mailbox_max | chunk_spp (p50/max) | samples/s | devices | cuda_err |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| metal_sweep | astroray | 5 | 5 | 1.0 | 132 | 0.9773 | True | 187.08 | 41.26 | 41.28 | 17.55 | 10.89 | 1 | 32/64 | 8.22 | [0] | 0 |
| big | astroray | 6 | 6 | 1.0 | 65 | 0.9077 | True | 125.5 | 87.12 | 90.08 | 100.42 | 22.91 | 1 | 5/11 | 3.57 | [0] | 0 |

`commit p95` (P2.2 item 2) is the per-generation main-thread commit cost; a bounded commit is what lets `cancel_ack_pump p99` (P2.2 item 3/4 -- cancel_request(in-flight g) to the pump draining that gen's idle_drain(g)) meet the <= 300 ms gate. `present_rate` (terminal generations whose final publication blitted / eligible terminal generations) and `frame_age` (per-publication mailbox_enqueue -> first_blit, >= 0) are defined under `--ui-pattern settle`; when no eligible terminal generation exists (the continuous stress storm) `present_rate` is reported UNGRADEABLE, not 0. `chunk_spp` (p50/max) and `samples/s` (Batch G) are MEASURED: every presented chunk reports its accumulated spp, and `samples/s` is the sum of each generation's largest presented spp over the run wall — not inferred from a fixed chunk size.

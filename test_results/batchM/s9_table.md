# pkg266 §9 table — Batch M (#817)

RTX 5070 Ti, isolated Blender 5.2 @9877 (StagedAddon, no profile install), idle GPU under the MAIN lock, 2 reps x 6 s, astroray engine, worker ON vs OFF (flag flipped live in-process).

Budget: settle tick-gap p95 <= 33 ms. For continuous(storm)/orbit the terminal-based present_rate is UNGR when the sweep continuously supersedes full-res generations; the orbit-row signal is spike_np>0 (presents DURING navigation) + final_full=True (reduced->full-res handoff). rec_np = recorder POST_PIXEL blits.

| state | pattern | scene | region | gap p95 | gap p99 | present_rate | spike_np | full_res_frac | final_full | commit p95 | samp/s | rec_np |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ON | settle | big | 2100x1221 | 21.45 | 105.35 | 1.0 | 65 | 0.9077 | True | 125.5 | 3.57 | 1524 |
| ON | settle | metal_sweep | 2112x829 | 17.11 | 18.35 | 1.0 | 132 | 0.9773 | True | 187.08 | 8.22 | 1575 |
| ON | continuous | big | 2100x1221 | 174.7 | 176.42 | 1.0 | 4 | 0.25 | True | 117.87 | 0.23 | 411 |
| ON | continuous | metal_sweep | 2112x829 | 196.68 | 228.63 | 1.0 | 33 | 0.4242 | True | 218.57 | 1.79 | 510 |
| ON | orbit | big | 2100x1221 | 13.41 | 13.58 | 1.0 | 469 | 0.0085 | True | 5.39 | 26.23 | 1544 |
| ON | orbit | metal_sweep | 2112x829 | 76.85 | 78.15 | UNGR | 8 | 1.0 | True | 70.84 | 0.46 | 1070 |
| OFF | settle | big | 2100x1221 | 280.23 | 344.72 | UNGR | None | None | None | None | None | 58 |
| OFF | settle | metal_sweep | 2112x829 | 184.7 | 291.21 | UNGR | None | None | None | None | None | 78 |
| OFF | continuous | big | 2100x1221 | 217.96 | 222.02 | UNGR | None | None | None | None | None | 111 |
| OFF | continuous | metal_sweep | 2112x829 | 299.92 | 307.94 | UNGR | None | None | None | None | None | 136 |
| OFF | orbit | big | 2100x1221 | 25.53 | 28.28 | UNGR | None | None | None | None | None | 493 |
| OFF | orbit | metal_sweep | 2112x829 | 44.56 | 45.58 | UNGR | None | None | None | None | None | 418 |

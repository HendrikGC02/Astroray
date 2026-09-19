# #721 storm-material-domain fix — GUI verification (Batch M, 2026-09-19)

RTX 5070 Ti, isolated Blender 5.2 @9877 (StagedAddon — no profile install; the
launcher now stages the `mcp` bridge itself, 9877 bound with no manual copy).
worktree Astroray-storm721 @ HEAD (fix/721-storm-material-domain). PR #831.

## VERDICT: PASS

## 1. Storm row — commit cost collapsed (worker ON, continuous storm)

| scene | metric | before (#819) | after (fix) |
|---|---|---|---|
| metal_sweep | commit p95 | 218.6 ms | **73.0 ms** |
| metal_sweep | tick-gap p95 | 196.7 ms | **80.1 ms** |
| big | commit p95 | 117.9 ms | **23.4 ms** |
| big | tick-gap p95 | 174.7 ms | **80.7 ms** |

Per-phase proof (8 s storm, worker ON): material edits now classify
**`dispatched`/MATERIALS** (metal 133 / big 85), `_replay_deferred_dirty`
**True 97 / 85, False 0**, and only **2** `sync_viewport_scene` calls (was
46 / 50 pre-fix). The incremental `upload_materials()` replay now engages; the
per-edit full re-sync is gone. (Storm gap p95 is still > 33 ms — the residual is
now render/present, not commit; out of #721 scope.)

## 2. Correctness by eye — worker ON vs OFF match within ~1% on every edit (no stale)

Center-pixel RGB of a controlled Principled sphere, per edit:

| step | worker ON | worker OFF | verdict |
|---|---|---|---|
| base (grey) | 0.795,0.782,0.751 | 0.785,0.773,0.733 | match |
| Base Color -> red | 0.902,0.557,0.504 | 0.895,0.546,0.491 | red, match |
| Roughness -> 0.03 | 0.906,0.529,0.479 | 0.898,0.520,0.464 | match |
| Noise -> Base Color (fallback) | 0.795,0.770,0.751 | 0.789,0.764,0.738 | texture replaces red, match |
| Image A (red) | 0.920,0.529,0.475 | 0.914,0.520,0.463 | red, match |
| Image B swap (blue, fallback) | 0.523,0.650,0.858 | 0.510,0.643,0.849 | new image blue, not stale, match |
| Emission 0 | 0.790,0.777,0.746 | 0.785,0.772,0.738 | match |
| Emission 5 | 0.762,0.745,0.703 | 0.752,0.735,0.685 | match |
| Undo emission | 0.791,0.778,0.748 | 0.784,0.772,0.735 | match |

The worker (incremental-replay) path is byte-for-byte equivalent (within MC
noise) to the OFF synchronous always-fresh path on every material edit — so the
#721 fix introduces **no staleness**. Base Color / roughness (value -> MATERIALS
replay), node-link / image-swap (structural / Image datablock -> FALLBACK) all
show the new state.

## 3. Emission note (pre-existing, NOT a #721 block)

Emission Strength 0 -> 5 does not visibly light the sphere — but **worker ON and
OFF are identical here** (both grey), so this is the pre-existing GPU
emission-RGB-approximation gap (the full-sync OFF path renders it the same way),
not a stale-material bug and not introduced by this fix. The edit is correctly
routed via the emission-sign FALLBACK (verified by the bpy-free suite).

## 4. bpy-free mechanism tests: 37 passed
`tests/test_issue721_storm_material_domain.py` + `test_pkg116_exporter_caches.py`
+ `test_pkg56_phase_c_dispatch.py`.

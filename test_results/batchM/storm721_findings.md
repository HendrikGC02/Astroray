# #721 storm commit-cost — per-phase measurement (Batch M, 2026-09-19)

RTX 5070 Ti, isolated Blender 5.2 @9877, worker ON, `--ui-pattern continuous`
(8 s), commit-path Exporter methods instrumented at the Python level (no rebuild;
wraps the class so it survives scene reopens).

## Per-phase commit breakdown (avg ms/call)

| phase | metal_sweep | big |
|---|---|---|
| `sync_viewport_scene` (full re-sync) | **119.7 ms × 46** | **111.5 ms × 50** |
| `_classify_depsgraph_domains` | 0.08 | 0.09 |
| `_record_deferred_dirty` | 0.08 | 0.09 |
| `apply_depsgraph_updates` | 0.07 | 0.07 |
| `_replay_deferred_dirty` | 0.00 | 0.00 |

The storm commit cost is **~100 % `sync_viewport_scene`** (~110–120 ms/commit,
~6 commits/s). Every other phase is sub-0.1 ms.

## Root cause (why the incremental replay never engages)

Instrumented the classification + replay outcomes over an 8 s storm (big scene):

```
classify status:  {'fallback': 48}        # 48/48 edits -> fallback
_replay_deferred_dirty returns:  {True: 0, False: 47}
_deferred_full_sync set:  47
```

Every material Base-Color edit in the storm is classified **`fallback`** by
`_classify_depsgraph_domains`, which sets `_deferred_full_sync = True`, so
`_replay_deferred_dirty` returns False and the commit falls through to a full
`sync_viewport_scene` (re-convert + re-upload the whole scene, ~115 ms) instead of
the incremental `renderer.upload_materials()` the pkg266 (#812) coalesced-replay
path was built to use (which is sub-millisecond).

The pkg266 replay optimisation is therefore **inert for the material storm** — the
edits never reach the safe MATERIALS domain because classification returns fallback
first.

## Recommended fix (scoped to #721, NOT #817)

Make the recorder's Principled `Base Color` `default_value` edit resolve to the
`MATERIALS` domain in `_classify_depsgraph_domains` (`MaterialsCache.diff`) so
`_replay_deferred_dirty` dispatches `upload_materials()` (sub-ms) instead of a full
sync. Then re-measure the storm row (target tick-gap p95 ≤ 33 ms). This is a
classification/cache change in the commit path — distinct from the #817 worker
present/refinement behaviour — and should land under #721 with its own correctness
check (confirm a genuinely unmappable edit still falls back to a full sync).

Not implemented here: it is out of #817 scope and a classification change carries
its own correctness risk; filing as the #721 fix.

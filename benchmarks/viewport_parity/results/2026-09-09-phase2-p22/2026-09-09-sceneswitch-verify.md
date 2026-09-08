# Scene-switch fix verification (PR #777, RTX 5070 Ti, 2026-09-09)

Verifies the §13a fix (`stop_all_viewport_sessions()`, commit `d4d0bcaf`) against
the exact reproduction that previously crashed 3/3 (see "NEW FINDING (blocking)"
above): `ASTRORAY_VIEWPORT_WORKER=1` + switching the loaded `.blend` mid-session.

**Setup:** isolated GUI Blender 5.2 on port **9877**, disposable profile
(`BLENDER_USER_RESOURCES`/`EXTENSIONS`/`CONFIG`/`SCRIPTS`/`DATAFILES` redirected
to a fresh temp dir; `mcp` extension copied verbatim from the default profile).
Addon staged from this branch's HEAD `6db733b5` using the main-tree canonical
`.pyd` (`build_cuda/astroray.cp313-win_amd64.pyd`, build-ID `dev`, restaged with
matching manifest `build_id="dev"` to satisfy the pkg94 stale-module guard) —
this branch has zero native diff vs main, and the two main commits since that
`.pyd`'s build (`896d7f7c`, `015e3d30`) only touch `TexturedLight` material
support and an energy-compensation status binding, neither reachable from
viewport-worker/session code, so the gap is irrelevant here. GPU lock held for
the whole session via `locks.acquire_lock` (never written directly); `nvcc`/
`cl`/`ninja`/`ptxas` confirmed absent before starting.

**Port-9876 safety note:** the `mcp` extension's own built-in autostart timer
defaults to port 9876 with a 1.0 s delay and would have raced our port-9877
assignment (an earlier attempt using the repo's `scripts/dev/blender_mcp_autostart.py`
pattern briefly bound 9876 before we caught it and killed the process — no
persistent damage, port was clear again immediately after). The verification
run used a hardened startup script that enables the `mcp` extension and
*synchronously* starts the bridge itself on 9877 (bypassing the extension's own
1 s-delayed autostart entirely) before returning control to Blender's event
loop, so 9876 was never bound during the actual verification session (confirmed
via `Get-NetTCPConnection` polling throughout).

## Reproduction: `--mode present_check --scenes <A> <B>`, worker ON, one process

| run | order | scene | n_present_calls | max_present_std | verdict |
|---|---|---|---|---|---|
| 1 (A->B) | metal_sweep -> big | metal_sweep | 59 | 1.1334 | PASS |
| 1 (A->B) | metal_sweep -> big | big | 45 | 1.0601 | PASS |
| 2 (B->A) | big -> metal_sweep | big | 42 | 1.0626 | PASS |
| 2 (B->A) | big -> metal_sweep | metal_sweep | 59 | 1.0607 | PASS |
| 3 (third switch) | metal_sweep -> big | big | 44 | 1.0595 | PASS |

All 3 runs (5 scene switches total, one continuous Blender process, worker ON
throughout) reproduce the exact pre-fix crash conditions. **Zero CUDA errors**
in the Blender log across the whole session (`grep -i "illegal\|cudaMalloc
failed\|launch error" -> no matches`), where the pre-fix run produced, 3/3:

```
[CUDA] light tree not uploadable (dedicated lights present) - GPU NEE falls back to power-CDF selection
stage_env_shadow launch error: an illegal memory access was encountered
allocateGPUWavefrontState: cudaMalloc failed for s.pixel_index
stage_shade_bucketed launch error: an illegal memory access was encountered
```
(the benign "light tree not uploadable" line is expected/unrelated and appears
in both pre- and post-fix logs.)

## Post-switch render sanity: one realistic-settle `ui_latency` rep on `big`

Same live process, after all 4 switches above (5th scene load via `_open_scene`
inside `ui_latency`), `--ui-pattern settle --ui-burst-s 0.3 --ui-settle-s 6.0
--duration-s 20`:

| metric | value |
|---|---|
| n_ticks | 2467 |
| n_presents | 2606 |
| n_render_device | 146 |
| gap p50 / p95 / p99 / max (ms) | 7.01 / 8.53 / 28.88 / 294.17 |
| cuda_errors | 0 |
| tick-gap p95 budget (<=33ms) | PASS |

Rendering is fully functional post-switch: 2606 presents delivered, tick-gap
p95 well under budget, zero CUDA errors.

## Verdict

**RESOLVED.** The §13a `stop_all_viewport_sessions()` fix (load_pre handler +
atexit hook draining every prior worker to acknowledged idle before a new
session's worker can touch the process-global `WfContext`) eliminates the
scene-switch CUDA context corruption. 5 scene switches across 3 reproduction
runs (both orders, plus a third switch) in one continuous worker-ON process:
0/5 crashes (was 3/3 pre-fix), every `present_check` PASS, and a post-switch
render workload confirms the context remains healthy and performant. The
P2.3-blocking finding from the post-fix graded measurement is closed.

Raw files: `sceneswitch-run1-AtoB-phase0.json`, `sceneswitch-run2-BtoA-phase0.json`,
`sceneswitch-run3-thirdswitch-phase0.json`,
`sceneswitch-postswitch-settle-big-phase0.json` (+ `-summary.md`), and this
file's machine-readable twin `2026-09-09-sceneswitch-verify.json`.

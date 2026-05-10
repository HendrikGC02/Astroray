# pkg81 — Viewport interactivity parity with Cycles

**Pillar:** 5
**Track:** A
**Status:** Phase 1+2 done (harness + diagnosis); Phase 3 routes to pkg55 Phase B
**Estimated effort:** 1–2 weeks (~30 h, multiple sessions)
**Depends on:** pkg52 (persistent viewport), pkg56 Phases A+B+C (incremental sync), pkg68 (OIDN persistent), pkg73 fix, pkg55 Phase A (baseline numbers exist)

---

## Goal

**Before:** Astroray's viewport rendered-view feels noticeably slower
than Cycles when panning/zooming/orbiting the camera at the same scene
complexity, on the same hardware. The project owner's lived experience
(2026-05-10): *"in Cycles I can move the camera nearly interactively
with good updating speed in rendered view, whereas with Astroray it's
a bit of a slog."*

This is a fitness-for-use gap, not a missing feature. pkg52, pkg56,
pkg68, pkg73, and pkg74 all individually closed; the pillar is 27/28
done by package count. But the user-facing competitive parity goal
that ROADMAP.md sets out — *"rival Cycles in simple enough cases on a
single RTX 5070 Ti"* — has never been measured against Cycles in a
viewport-interactivity scenario.

**After:** A reproducible viewport-interactivity benchmark exists with
matched-scene Astroray-vs-Cycles frame-time numbers across CPU + GPU,
across scene complexity from 10k to 1M tris. Astroray clears measured
acceptance gates: pan-frame p99 ≤ 1.2× Cycles-CUDA on the matched
99k-tri reference scene; 100k-tri pan-frame p99 ≤ 30 ms with
denoising on; idle-frame stays at the pkg56-C ≤ 5 ms gate.

---

## Context — why this matters now

ROADMAP.md's **performance goal** is "rival Cycles in simple enough
cases on a single RTX 5070 Ti". pkg71 measured that for **batched
offline rendering** (Cornell SSIM 0.9548 vs Cycles, **5.2× faster than
Cycles-CUDA**). That's a real, defensible parity win.

But the day-to-day Blender experience is dominated by viewport
rendered-view, not F12 batches. And there, Astroray has **never been
measured against Cycles**. The packages that should have produced
this number — pkg52 (persistent viewport), pkg56 (incremental sync) —
each closed against their own internal gates (idle frame, refresh
rate), but not against Cycles-CUDA on the same scene.

This package fills that gap. It's the *real* Pillar-5 closing gate for
the "Cycles parity / Blender integration" wave.

---

## Reference

### External

| Source | License | What to read |
|---|---|---|
| `intern/cycles/blender/session.cpp` — `BlenderSession::view_update` / `view_draw` / sample loop | Apache-2.0 | The reference for what "interactive" means: how Cycles staggers progressive samples, where it fences GPU work, when it triggers denoising. Mirror policy with citation, do not copy code. |
| `intern/cycles/blender/sync.cpp` (BlenderSync::sync_recalc) | Apache-2.0 | How Cycles routes depsgraph updates to per-domain uploaders. We mirrored this for pkg56-C; pkg81 is checking whether our routing actually exercises the same fast paths under live pan/zoom. |
| `intern/cycles/integrator/path_trace.cpp` — `PathTrace::path_trace_iteration` | Apache-2.0 | Cycles' progressive sample loop with partial denoising and adaptive sampling. The shape pkg81 measures against. |
| Laine, Karras, Aila — "Megakernels Considered Harmful" (HPG 2013) §6 — interactivity arguments | n/a (paper) | Why register pressure matters disproportionately for first-pixel latency. pkg55 Phase A measured 158 regs/thread / 1 active block/SM on Astroray's megakernel; this is the architectural root cause hypothesis we test. |

### Internal — our own measurements to compare against

- `benchmarks/wavefront/baseline.json` (pkg55 Phase A) — 89.37 ms /
  cornell_diffuse, 90.86 ms / cornell_glass at 64 spp, RTX 5070 Ti.
- pkg56 Phase A baseline — **129.92 ms / frame** on 100k-tri scene,
  pre-Phase-B uploadScene split.
- pkg56 Phase B — uploadGeometry / uploadMaterials / etc. split, no
  per-frame number recorded.
- pkg56 Phase C — **idle frame ≤ 5 ms p99** on 99k-tri scene, but
  no measurement of pan-frame, transform-frame, or shading-edit
  frame times.

The hole pkg81 fills: *what's the pan-frame number on the same
99k-tri scene?* Currently unknown.

---

## Specification

### Phase 1 — measurement harness (~3 days)

A scripted Blender benchmark that:
1. Loads a parameterised scene (10k / 100k / 1M tris; spheres or
   imported `.blend` from pkg76's importer).
2. Drives a deterministic camera pan/zoom/orbit sequence over N
   frames via `view_update` / `view_draw` calls (or via `bpy.ops`
   programmatic camera moves).
3. Records per-frame wall time at the `view_draw` callback level,
   plus a finer-grained breakdown (sync time vs render time vs
   denoise time) using the pkg56 Phase A ring buffer + pkg55 Phase A
   profiling.
4. Does the same harness for Cycles by switching `render_engine` and
   re-running. Same scene, same camera path.
5. Outputs `benchmarks/viewport_parity/{date}.json` and a
   `summary.html`.

Files to create:
- `benchmarks/viewport_parity/run.py` — harness CLI
- `benchmarks/viewport_parity/scenes/{cornell_99k.blend, sphere_grid_*.blend}` — fixture scenes (small, committed)
- `tests/test_viewport_parity_harness.py` — smoke test that the
  harness runs against a tiny scene without launching Blender (uses
  the pkg52 persistent viewport in-process)

### Phase 2 — diagnose (~3 days)

Run the harness, identify the gap. Hypotheses to verify in measured
order:

| H | Hypothesis | Verifier |
|---|---|---|
| H1 | pkg56-C dispatch fires too many uploaders during pan (transform-only edits trigger geometry uploads it shouldn't) | Per-domain uploader call count per frame in the pkg56 ring buffer |
| H2 | Progressive accumulation re-renders from sample 1 every pan tick (vs Cycles which continues progressive samples and only resets on real scene change) | Sample-counter trace; visual inspection at 1/2/4 spp |
| H3 | OIDN denoising blocks the frame loop (synchronous in pkg68's persistent-device design, even with the CUDA backend) | Frame-time delta with `add_pass("oidn_denoiser")` on vs off |
| H4 | Megakernel register pressure (158 regs/thread / 1 active block/SM, pkg55 Phase A finding) caps first-pixel latency. Cycles uses wavefront on CUDA. | A/B against Astroray-CPU which doesn't have this constraint |
| H5 | Setup overhead per `view_draw` is large (BVH state validation, Python→C++ marshalling) | Profile the first vs subsequent N draws |

Each hypothesis tested with a recorded measurement. The diagnosis
output is a `pkg81-diagnosis.md` note in `.astroray_plan/docs/` that
identifies the dominant gap with numbers.

### Phase 3 — targeted fix(es) (~1 week)

Whichever hypothesis dominates. Likely candidates:

- **H1 fix:** tighten the pkg56-C depsgraph filter so transform-only
  edits truly hit only `update_object_transform()` and not
  `uploadGeometry()`. Trivial if it's a regression.
- **H2 fix:** progressive sample continuation across `view_update`
  ticks, modelled on `BlenderSession::reset` in Cycles —
  invalidate the framebuffer only on real scene-graph mutations.
- **H3 fix:** async denoising — fire OIDN/OptiX on a separate CUDA
  stream, blit a "stale" denoised image into the viewport while the
  next sample accumulates. Cycles pattern.
- **H4 fix:** if H4 dominates, this becomes the **primary
  motivation for pkg55 Phase B** (per-material shade kernel split).
  Phase B's promise is exactly to break the regs/thread cliff. In
  that case pkg81 becomes a measurement-only package and the actual
  viewport win comes through pkg55 B+C.

### Acceptance criteria

- [x] Phase 1 harness merged; `benchmarks/viewport_parity/2026-05-10.json`
      committed with Astroray-CUDA + Astroray-CPU numbers for 10k and
      100k-tri scenes (256² × 1 spp × depth 4 × 30 frames). 1M-tri
      and Cycles-CUDA columns are filled in by re-running the harness
      and `blender_driver.py` on the project owner's RTX 5070 Ti
      station — the in-process runner is hardware-agnostic and the
      Cycles companion script is committed.
- [x] Phase 2 diagnosis note merged
      (`.astroray_plan/docs/pkg81-diagnosis.md`); dominant bottleneck
      named with measured numbers — **H4 (megakernel regs-per-thread
      cliff) compounded by H5 (cold CUDA context = 12 s first frame)**.
- [ ] Phase 3 fix(es) merged. Acceptance gates:
  - 99k-tri scene pan-frame p99 ≤ **1.2× Cycles-CUDA** on RTX 5070 Ti
    (parity within tolerance)
  - 100k-tri scene pan-frame p99 ≤ **30 ms** absolute with denoising
    on (the user's "feels interactive" threshold)
  - 1M-tri scene pan-frame p99 ≤ **2× Cycles-CUDA** (graceful at
    high complexity)
  - pkg56-C idle-frame ≤ 5 ms gate **preserved**
- [ ] If H4 dominates and the fix lands in pkg55 Phase B instead,
      pkg81 closes as "measurement complete; remediation tracked
      under pkg55 Phase B/C".

---

## Reference matrix

| Source | License | Mirror? | What we borrow | What we cite |
|---|---|---|---|---|
| `intern/cycles/blender/session.cpp` view_update / view_draw | Apache-2.0 | pattern only | progressive-continuation policy, denoise async pattern | yes, in code comment |
| `intern/cycles/integrator/path_trace.cpp` | Apache-2.0 | pattern only | sample-loop shape | yes |
| Laine et al. HPG 2013 | n/a | n/a | architectural argument | yes, in pkg55 spec |

No code is copied verbatim; reference reads only.

---

## Why this is filed now

The Astroray package counter currently reads "Pillar 5: 27/28 done,
96% complete, approaching feature-complete". The lived viewport
experience is "a slog compared to Cycles". Closing pkg81 collapses
that gap. **Pillar 5 is not actually feature-complete until pkg81
is closed**, regardless of what the counter says.

---

## Lessons (filled in on completion)

*(empty until done)*

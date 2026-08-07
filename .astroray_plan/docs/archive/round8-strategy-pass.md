# Round 8 Strategy Pass — Architect Assessment

**Date:** 2026-05-14
**Author:** Architect agent (Claude, Opus 4.7)
**Mode:** strategy-review / goal-capture
**Owner goal (verbatim):** "Good Cycles parity in Blender — across performance, UI, and features."
**Trigger:** pkg55 Phase B held on `origin/pkg55-phase-b` after three fix
attempts produced a regression spiral (2.5× brightness → 21× brightness).
Round 8 needs an architectural call before any more code lands.

---

## Executive summary

- **pkg55-B is in a debug spiral driven by structural opacity, not by a
  fundamentally wrong design.** The wavefront design (sort-by-material,
  per-material shade kernels, SoA state, separate shadow/miss/terminate
  stages) tracks Cycles + PBRT-v4 + Laine 2013 directly. The bugs are
  implementation-level: NEE-vs-throughput timing, accumulation
  semantics, per-material guards, emission-double-counting. Each fix
  has only been verified against one symptom because there is **no CPU
  reference implementation** of the wavefront pipeline to A/B against.
- **Recommendation: (b) revert pkg55-B from main path and restart from
  pkg55-A.1 baseline with a CPU reference implementation first.** Not
  (a) (more piecemeal), not (c) (waits for a Phase that doesn't exist
  yet), not (d) (gives up the user-facing viewport-parity gate).
- **Cycles parity for the user's goal is mostly a viewport-perf
  problem, not a feature problem.** The engine's offline SSIM already
  beats Cycles on Cornell (5.2× faster on CUDA, SSIM 0.9548). What
  doesn't match is interactive viewport feel — and that gap is owned
  by pkg55-B by spec.
- **Top non-pkg55 follow-ups: (1) light-tree sampling — biggest single
  remaining engine-side performance lever; (2) Cryptomatte +
  light-group AOVs — biggest single compositor-parity gap.** Both
  unblock Cycles-style production workflows.
- **One open question (for the owner):** is the user-experience
  promise "viewport pan feels like Cycles" the bar pkg55-B has to
  clear before Round 8 closes, or can we ship pkg55-B as a Round-9
  package and let Round 8 close on the smaller polish wins?

---

## 1. pkg55-B fork decision

### What's actually on the branch

`origin/pkg55-phase-b` is +2,853 / -138 LOC across 20 files: 7 shade
kernels, intersect_full (bounce variant), shadow, miss, terminate,
material sort, render loop, plugin registration, and a parity test.

Four commits in the bug-fix tail:

| Commit | Fix | Result |
|---|---|---|
| 9f79331 | 3 build errors (missing include, scope) | Builds clean |
| 8c6d9eb | Restore SoA cleanup in destructor | No leak |
| 6cc40c5 | Add launcher decl, fix accum_rgb size, parity test | Reaches output |
| 15d98f0 | Material-type guards on 7 shade kernels + NEE eval + emission guard | 2.5× brightness vs megakernel |
| cd26a87 | NEE×throughput timing + accumulation order | **21× brightness** |

### Why this is a spiral, structurally

Three properties of the current branch make incremental debugging hostile:

1. **No CPU oracle.** The CPU `path_tracer` and `multiwavelength_path_tracer`
   are AoS megakernel-shaped (loop over depth, single thread of control).
   There is nothing to A/B the wavefront's per-bounce SoA evolution against
   except the existing GPU megakernel. The megakernel is a 158-regs/thread
   monolith that is itself hard to read step-by-step.
2. **State carried across 11 kernels with disjoint authors.** Each shade
   kernel re-reads SoA, mutates throughput, queues NEE, and writes the next
   ray. The "did I update throughput at the right moment" question depends
   on subtle ordering across `shade_*` → `stage_shadow` → next-bounce
   `intersect_full` → `shade_*` again. The latest commit's claim is that
   NEE in `stage_shadow` was multiplying by post-BSDF throughput; the
   pre-fix said NEE was using a placeholder `(1,1,1)`. Both can be true,
   and "fixing" one without auditing the other six shade kernels for the
   same pattern is exactly what produces a 2.5× → 21× regression.
3. **The acceptance gate (SSIM ≥ 0.985 vs CPU path_tracer) is far away
   from the failure mode (21× brightness).** Any partial fix that
   improves brightness from 21× to 5× still fails the gate. There is no
   intermediate ratchet that says "we are 80% there."

### Wasted-work + opportunity-cost

If we continue (a):

- **Cost:** 3–6 more sessions of similar size to debug bugs 4/5/N. Each
  session creates a new commit that another session has to read to
  understand state. Calendar cost: 1–3 weeks at observed throughput,
  plus the integration cost of pkg64-gpu being blocked behind it.
- **Risk:** the next regression cycle (e.g. fixing emission double-count
  causes a different wavelength mis-bin) is just as likely as the last
  one. **Mean time between fixes that actually improve the gate has been
  zero so far.** Three attempts, three regressions.

If we revert + restart (b):

- **Sunk cost:** ~2,853 LOC of code. **But not lost** — the 7 shade
  kernels, sort, shadow, miss, terminate, render-loop scaffolding all
  remain valid reference for the restart. The architecture is right;
  the implementation needs a different *order of construction*.
- **New cost:** ~2 weeks to write a CPU wavefront reference
  (`plugins/integrators/wavefront_path_tracer_cpu.cpp`) that mirrors the
  GPU SoA stages on host arrays. Then ~2 weeks to port the CPU
  implementation to CUDA with stage-by-stage diff testing.
- **Net delta vs (a):** roughly even on calendar weeks, but the
  endpoint of (b) is **a tested, bit-comparable, mergeable** wavefront.
  The endpoint of (a) is "we think it's working now, let's run SSIM."

If we wait (c):

- **pkg55-C is not a real path forward.** Phase C *removes* the
  megakernel; it does not replace it independently of Phase B. Reading
  the spec again carefully: Phase C is "MIS/NEE parity + megakernel
  removal" on top of an already-working wavefront. There is no version
  of pkg55-C that skips Phase B.
- This option is incoherent and should be removed from consideration.

If we abandon (d):

- Gives up the viewport-parity gate. The user's stated goal includes
  "performance" parity; the pkg81 diagnosis says the megakernel's
  158-regs/thread is **the dominant gap** at viewport scale (~2× slower
  than CPU on 100k tris, ≥ 5× slower than Cycles-CUDA by reasonable
  estimate). pkg64-gpu and pkg83/84 do not close that gap. Megakernel
  alone is a known dead-end for general Cycles parity.
- Worth keeping (d) on the table only if the answer to the open
  question below is "viewport-parity isn't gating Round 8 closure."

### Recommendation: (b), with strict scope

**Revert pkg55-B from the integration plan; close PR if open; keep the
branch as reference.** Restart with:

1. **Phase B.0 (new, ~1 week): CPU wavefront reference.**
   `plugins/integrators/wavefront_path_tracer_cpu.cpp` — same SoA stages
   as the GPU spec, but on host `std::vector` arrays, single-threaded,
   instrumented with per-stage `printf` of throughput/radiance.
   Acceptance: bit-identical to `path_tracer` (CPU) on cornell at 1 spp
   with a fixed seed, no SSIM tolerance — exact.
2. **Phase B.1 (replaces current B, ~2-3 weeks): port CPU wavefront to
   CUDA, one stage at a time, with a per-stage diff test against the
   CPU reference.** Order: init → intersect → sort → shade × 7 →
   shadow → miss → terminate. Each stage merges only when its diff test
   passes.
3. **Phase B.2 (~1 week): acceptance gates from current spec** (SSIM ≥
   0.985 visible, ≥ 0.97 NIR, ≥ 1.5× speedup, viewport-parity gate).

The CPU reference is the missing oracle. With it, every cascading-radiance
bug becomes a `diff cpu_state.json gpu_state.json` at the offending stage,
not a "where in 11 kernels did the brightness double" hunt.

Rationale grounded in CLAUDE.md: §1 ("Don't hide confusion") — three
attempts producing regressions IS the confusion to surface. §6 — Cycles
itself developed wavefront *with a CPU reference path tracer already
working*, and PBRT-v4's wavefront integrator is shipped alongside its CPU
path tracer for exactly this reason.

---

## 2. Gap to Cycles, decomposed

### 2.1 Performance gap

Settled by pkg81 + Round 7 work:

| Gap | Owner | Status |
|---|---|---|
| 12 s CUDA cold start | pkg84 | **closed** (83 ms first frame, 145× win) |
| Accumulator reset per pan | pkg83 | **closed** (spp continues across camera moves) |
| SSIM gate variance | pkg82 | **closed** (0.999→0.998 re-baselined w/ methodology) |
| 104 ms CUDA vs 58 ms CPU steady state | **pkg55-B** | **open — the gap** |

That's it on performance. pkg55-B owns the only remaining substantial
performance gap on the user's actual hardware/workload. Pre-`view_draw`
texture-blit cost is small (pkg52 measurements); pkg56 two-level BVH
refit is queued and only matters for `transform_edit` paths, not pan.

### 2.2 UI gap

Reading `blender_addon/__init__.py` (4,257 LOC), the panels present are:

- Render: Sampling, Light Paths, Performance, Wavelength, Diagnostics
- Sampling sub-controls: render/viewport spp, viewport pass picker, OIDN
  toggle + backend, adaptive sampling + threshold
- Light Paths: max bounces + per-lobe (diffuse/glossy/transmission/volume/
  transparent), clamp_direct, clamp_indirect, filter_glossy, reflective +
  refractive caustics toggles
- World/Material/Object panels: surface shader, spectral profile preview,
  live material preview, object metadata (incl. caustic_caster), black-hole
  add operator
- Spectral: wavelength preset + custom range + colourmap

What Cycles has that Astroray's addon does not expose, ranked by user
visibility:

| Gap | Cycles equivalent | Effort | Notes |
|---|---|---|---|
| **Per-pass output (Cryptomatte, light groups, AOVs)** | Render Properties → Passes; View Layer | Medium pkg | We have AOVs internally (uv_debug, normals) but no Blender-side pass plumbing |
| **View Layers** | Properties → View Layer Properties | Small-medium pkg | Multiple render layers with independent integrator settings; compositor input |
| **Per-pass denoising granularity** | Cycles → Denoising panel | Small pkg | We have viewport OIDN on/off + backend; Cycles offers radius, prefilter, render-vs-viewport distinct settings |
| **Output settings parity** | Output Properties (formats, color management) | Small pkg | We rely on Blender's default; OCIO config plumbing through to engine is shallow |
| **Motion blur toggles** | Render Properties → Motion Blur | Engine work (no engine support yet); UI is small after engine ships | Camera/object/deformation; not in engine |
| **Light sampling controls** | Light Paths → Light Tree | Engine work first | Light tree is engine-side; UI is a single toggle once shipped |
| **Hair/curves render settings** | Curves panel | Engine work first | We render meshes; curves are missing |
| **Persistent data toggle** | Performance → Persistent Data | Tiny pkg | pkg52 ships persistent renderer but no addon toggle to disable for memory-constrained scenes |
| **Tile size / threading controls** | Performance → Threads + Tiles | Tiny pkg | Cycles exposes these; we don't |
| **Film transparent background** | Film panel | Tiny pkg | Cycles has it; we always composite onto background color |

UI gaps that genuinely require user-facing work and don't require deep
engine support: View Layers, output format parity, denoising granularity,
persistent-data toggle, tile/thread controls, film transparency. None of
these is a 2-week package; together they're maybe one focused 2-3 day
session each.

### 2.3 Features gap

Ranked by visible user value × inverse implementation cost:

| Feature | User value | Effort | Reference (license) | Recommendation |
|---|---|---|---|---|
| **Light tree sampling** | High — direct perf win on many-light scenes (Cycles' Many-Lights paper, 2-10× on common scenes) | M (~2-3 wk) | Conty Estevez & Kulla 2018 + Cycles `intern/cycles/scene/light_tree.cpp` (Apache-2.0) | **YES — pkg86 candidate** |
| **Cryptomatte** | High — production compositor parity | M (~2 wk) | Cycles `intern/cycles/kernel/film/cryptomatte_passes.h` (Apache-2.0); spec at psyop/Cryptomatte | **YES — pkg87 candidate** |
| **Light groups (AOVs)** | High — relight in comp | S (~1 wk) | Cycles `LightGroup` plumbing (Apache-2.0) | **YES — pkg88 candidate, after Cryptomatte** |
| **Camera motion blur** | Medium-High | M (~2 wk) | Cycles `intern/cycles/kernel/camera.h` `motion_camera_*` (Apache-2.0); textbook math | YES eventually |
| **Object/deformation motion blur** | Medium | L (~4 wk) | Cycles same area + `scene/object.cpp` motion samples (Apache-2.0) | Defer; camera MB first |
| **Hair / curves rendering** | Medium-High in studio workflows, Low in astrophysics | L (~6 wk) | Cycles `kernel/geom/curve_intersect.h` (Apache-2.0); embree curve primitives | Defer until astrophysics pillar matures |
| **Displacement maps (true displacement)** | Medium | M (~3 wk) | Cycles `geom/triangle_subdivide.h` (Apache-2.0); micro-displacement design | Defer; bump already works |
| **Principled BSDF v3 missing features** | Medium | S-M | Cycles `closure/bsdf_principled.h` (Apache-2.0); Burley 2015 | We have v2 + energy compensation (pkg60). Audit gap separately |
| **USD scene import** | Medium for studio interchange | L (~4 wk) | OpenUSD (Apache-2.0) | Defer; .blend reader (pkg76) covers Blender users |
| **OpenColorIO config end-to-end** | Medium | S (~1 wk) | OCIO (BSD-3) | Quick win if Blender Filmic isn't already matching |
| **Volume materials beyond synchrotron** | Low for general scenes, High for Pillar 4 | M | PBRT-v4 `media/homogeneous.h` (Apache-2.0) | On Pillar 4 track (pkg43/44) |
| **Render-layer compositor passes** | Subsumed by View Layers + Cryptomatte + LightGroups | — | — | Covered by combinations above |
| **Scene file format compat (Cycles XML)** | Low | M | Cycles `scene/scene.cpp` XML reader (Apache-2.0) | Defer; pkg76 covers .blend |

Headline: **light tree + Cryptomatte + light groups** is the
high-value triplet. Together they cover the "Cycles-parity for
production renders" complaint better than any single big feature.
Motion blur is the only big engine-feature gap remaining; it's a known
2–4-week port from Cycles' Apache-2.0 code with established math.

---

## 3. Top follow-up packages

### pkg86 — Light Tree sampling (post-pkg55-B)

**Sketch.** Port Cycles' light tree from `intern/cycles/scene/light_tree.cpp`
+ `kernel/light/tree.h` (Apache-2.0). Build a hierarchical bounding-cluster
tree over scene lights; at each shade vertex, traverse the tree using the
Conty Estevez & Kulla 2018 importance heuristic to pick a light proportional
to expected contribution. Replaces the current uniform-by-power
`sampleDirectGPU` light pick. Wire as a new sampler interface so the existing
NEE call sites change one line. Expected win: 2–5× variance reduction on
many-light scenes (e.g. Junkshop in pkg76 baseline). CLAUDE.md §6 reference:
Conty Estevez & Kulla 2018 (DOI [10.2312/sr.20181174](https://doi.org/10.2312/sr.20181174)).

### pkg87 — Cryptomatte passes

**Sketch.** Port Cycles' Cryptomatte from
`intern/cycles/kernel/film/cryptomatte_passes.h` (Apache-2.0). Add three
new AOVs (CryptoObject, CryptoMaterial, CryptoAsset) that store hashed
ID + coverage in a small fixed-size per-pixel histogram. Wire into the
existing Astroray AOV machinery (we already have uv_debug + normals
working through the pass system). Blender-addon side: register the
passes in `RenderEngine.bl_use_postprocess` and emit them with proper
metadata so the standard Cryptomatte compositor node picks them up.
Reference: psyop/Cryptomatte spec (BSD-3) + Cycles implementation
(Apache-2.0). Effort: ~2 weeks. **Highest leverage UI/feature win not
gated by pkg55.**

---

## Open question

The pkg55-B fork decision is mostly mechanical given the analysis
above (revert → CPU reference → port). But the *Round 8 scoping*
question requires owner input:

> **Does Round 8 have to close with viewport-parity met, or can pkg55-B
> (under recommendation b) slip to Round 9 while Round 8 closes on
> pkg85 + pkg86 (light tree) + pkg87 (Cryptomatte) + pkg43/pkg44
> (Pillar 4)?**

If Round 8 *must* close with viewport-parity: pkg55-B becomes the
critical path; pkg86/pkg87 wait. Calendar: ~4-5 weeks.

If Round 8 can close without viewport-parity (megakernel stays
production until Round 9): pkg86 + pkg87 give the user the most
*visible* Cycles-parity wins on the same calendar (~3-4 weeks), and
pkg55-B's restart can be properly sized as a Round-9 deliverable
without pressure to merge a half-debugged branch.

**Architect's lean** (do not adopt without owner confirmation):
**the latter.** Viewport-parity is a real gap, but "good Cycles
parity" reads to me as broader feature-and-workflow parity, where
Cryptomatte + light groups + light tree do more visible work per
engineering week than closing the 104→58 ms steady-state gap. Owner
may disagree — this is the call to make.

---

## Appendix — files reviewed

- `.astroray_plan/docs/STATUS.md` (Round 7 closeout, 2026-05-14)
- `.astroray_plan/docs/ROADMAP.md`
- `.astroray_plan/docs/NEXT_STAGE_REPORT.md`
- `.astroray_plan/docs/pkg81-diagnosis.md`
- `.astroray_plan/packages/pkg55-wavefront-soa-refactor.md`
- `.astroray_plan/packages/pkg64-gpu-spectral-caustics.md`
- `.astroray_plan/packages/pkg85-test-harness-cuda-state-leak.md`
- `git log origin/pkg55-phase-b` (commits 9ef59a5 → cd26a87)
- `git diff --stat origin/main...origin/pkg55-phase-b` (2,853 / 138 LOC)
- `src/gpu/wavefront/wavefront_render_loop.cu` (on branch)
- `src/gpu/wavefront/stage_shade_lambertian.cu` (on branch)
- `blender_addon/__init__.py` (panel + property inventory)
- `plugins/integrators/*.cpp` (current integrator set)

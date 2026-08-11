# Engine benchmark + visual showcase — research note (pkg74)

**Status:** signed off for Phase 1 implementation (this round).
**Author:** Claude Code, 2026-05-10.
**Pairs with:** `.astroray_plan/packages/pkg74-engine-benchmark-showcase.md`.
**Companion package:** pkg71 (Cycles parity benchmark) — pkg74 is *not*
a replacement for pkg71; the two cover complementary needs.

This note is the §6 "cite, borrow, verify" prerequisite for pkg74. It
identifies the canonical references for what an engine-benchmarking
framework should track and produce, audits the existing Astroray
benchmark/diagnostic surface, and recommends a starter scope.

---

## 1. What is comprehensive engine benchmarking — and why pkg74 is not pkg71

Astroray already has one benchmark package on the queue: pkg71
(`cycles-parity-benchmark`). pkg71 is **parity tracking** — it renders
3–5 fixed Blender Foundation demo scenes through Cycles and Astroray
on identical hardware, dumps a CSV with timing/memory/SSIM, and
opens a tracking issue when SSIM-vs-Cycles drops below 0.95. It is a
narrow, automatable, CI-gated regression detector. Its output is a
spreadsheet.

pkg74 is **engine showcase + visual diagnosis** — it renders a
deliberately *internal* scene set across every dimension Astroray
cares about (every registered material, every registered integrator,
geometric SPP series for convergence demonstration, edge cases like
glossy caustics) and produces *visual* artefacts: PNG contact sheets,
matplotlib graphs, and an HTML index that can be opened in a browser
or pasted into a paper or a release blog post.

The two packages exist in parallel for the same reason production
engines maintain both regression suites and tech demos: a single
number — "Astroray vs Cycles, SSIM=0.97, 1.4× slower" — does not
help a user choose between integrators, does not catch a Disney
multiscatter regression that only shows on rough metals, and does
not help the project owner write a release post. pkg71's CSV says
*whether* something regressed; pkg74's contact sheet shows *what*
regressed at a glance.

Cycles itself runs on this two-track model. Its
`tests/integration/` suite is image-diff regression
(parity-with-known-good, equivalent to pkg71). Its
`opendata.blender.org` benchmark is the public, hardware-comparison,
visual-result framework (equivalent to pkg74). They share neither
scene set nor output format because the audiences are different —
the integration suite reports to CI; opendata reports to humans.

PBRT v4 takes the same split. The book's figures use a curated
reference scene set (kroken, watercolor, ganesha, etc.) rendered
with the `--stats` flag dumping internal counters; the test suite is
a separate, smaller set of integration renders gated on numerical
equivalence to pinned reference EXRs. pkg74 is closer to the former,
pkg71 to the latter.

The constraint that follows: **pkg74 must not duplicate pkg71's
scene set or CSV layout.** Different artefacts under a different
directory tree (`benchmarks/showcase/` vs `benchmarks/cycles-parity/`)
keep the two from being silently merged-and-confused later.

## 2. Statistics catalog

The reference list below merges what PBRT v4 reports under `--stats`,
the Mitsuba 3 `ProfilerPhase` enum, and Cycles' `RenderStats` /
`SceneUpdateStats`. Anything Astroray cannot measure today is flagged
as such; pkg74 records what it can today and leaves the rest as
explicit `null` cells in the CSV so the gap is visible.

### 2.1 Geometry — what's in the scene

- **Object counts**: triangles, spheres, total primitives. Astroray:
  available via existing scene-API counts in C++; not currently
  surfaced to Python (Phase 1 records the count the harness adds, not
  the BVH node count).
- **BVH stats** (PBRT: `BVH/Interior nodes`, `BVH/Leaf nodes`, `BVH/Nodes
  visited`): not yet surfaced through the Python binding. Phase 1
  records primitive count only; Phase 2 may add a `bvh_stats()`
  binding.
- **Memory (peak, per-allocator)**: Cycles `Stats.mem_used` /
  `mem_peak`. Astroray: peak RSS of the Python process via
  `psutil.Process.memory_info().rss` is the cheapest portable proxy;
  good enough for showcase, not fine-grained enough for kernel-level
  optimisation.

### 2.2 Sampling — how rays are spent

- **Camera rays / shadow rays / scattered rays** (PBRT
  `STAT_COUNTER("Integrator/Camera rays traced", …)`). Astroray:
  `Renderer.get_integrator_stats()` already returns a `dict` of
  per-integrator counters (used by pkg27a NRC observability). pkg74
  records every key the dict returns so coverage grows automatically
  as integrators add stats.
- **Samples per pixel** (Cycles `RenderStats.kernel`): we set this
  per-render and it's recorded as part of the run config.
- **Russian-roulette termination rate**: not currently surfaced;
  recorded as `null` in Phase 1.

### 2.3 Memory — host + device

- **Host RSS peak**: psutil polling on a 50 ms cadence watcher
  thread (same shape as pkg71's plan). Recorded per-(scene,
  integrator).
- **Device VRAM** (`nvidia-smi --query-gpu=memory.used`): Phase 1
  skips this — pkg71 is the place that handles GPU benchmarks; pkg74
  Phase 1 is CPU-integrator-focused. Phase 2 picks it up if/when the
  showcase grows GPU integrator rows.

### 2.4 Timing — wall-clock breakdown

- **Total render time** (perf_counter around `r.render(...)` —
  the only timing we measure in Phase 1).
- **Per-stage timing** (Mitsuba `ProfilerPhase::InitScene`,
  `LoadGeometry`, `InitAccel`, `Render`, `SamplingIntegratorSample`,
  `SampleEmitter`, `RayIntersect`, `BSDFEvaluate`, `BSDFSample`):
  Astroray does not split scene-build from render at the Python
  layer today; Phase 1 records only the `r.render(...)` wall time.
  Phase 2 adds a scene-build vs render split if scene-build cost
  becomes interesting.
- **Per-integrator timing** is the headline of `integrator_compare.py`
  scene: same scene, every registered integrator, plotted as a bar
  chart.

### 2.5 Quality — does the image look right

- **MSE / PSNR / RMSE vs converged ground truth** at increasing SPP.
  This is the convergence curve. Reference: PBRT's standard
  "log-log RMSE vs sample count" figure. Astroray's existing
  `scripts/diagnostics/convergence_tracker.py` already implements this
  for one scene; pkg74 reuses the same MSE helper but standardises
  the scene set and the output location.
- **Variance decomposition (direct vs indirect)**: not currently
  separable — recorded as a single value in Phase 1.
- **Firefly count** (pixels above a luminance threshold): cheap to
  compute from the rendered buffer; recorded in Phase 1 as
  `firefly_count_4x_mean`.

### 2.6 Spectral — wavelength coverage

- **Hero-wavelength selection** distribution: not surfaced; Phase 1
  records the configured wavelength range (`Renderer.set_wavelength_range`)
  as scene metadata only.

### 2.7 Integrator-specific

- **NRC**: training loss, queued/trained sample counts, fallback
  events. Already in `get_integrator_stats()` from pkg27a.
- **ReSTIR**: reservoir-reuse rate, candidate counts. Surfaced via
  `get_integrator_stats()` since pkg23.

The pkg74 harness reads `get_integrator_stats()` and writes every
key/value to the CSV without a hardcoded schema, so integrator-
specific counters round-trip without a code change.

## 3. Visual outputs catalog

Three axes of visual output, in order of implementation cost:

### 3.1 Contact sheets (PIL/Pillow grid composites)

- **Material zoo** — one sphere per registered material, uniform
  HDRI-or-area-light lighting, labelled grid. Builds directly on
  the existing `scripts/diagnostics/material_contact_sheet.py`
  pattern; pkg74's version drives every entry from
  `astroray.material_registry_names()` rather than a hardcoded list,
  so newly-registered materials appear without a code change.
- **Integrator comparison** — one scene, every registered integrator,
  rendered side by side at a fixed SPP. Driven by
  `astroray.integrator_registry_names()`.
- **Scene gallery** — the 4 internal scenes (Cornell, glass sphere,
  metal trio, prism) rendered at production SPP, one row.
- **Convergence-vs-spp grid** — one scene at SPP = 1, 4, 16, 64, 256,
  1024 in a horizontal strip. Same shape as
  `convergence_tracker.py`'s output, but committed under
  `benchmarks/showcase/` so it lives next to the rest of the
  showcase artefacts.

### 3.2 Statistical graphs (matplotlib, Agg backend)

- **Convergence curve** — log-log RMSE vs SPP for one reference
  scene, gated against a converged ground-truth render at the
  highest SPP in the series.
- **Variance decomposition over SPP** — Phase 2 (needs the
  direct-vs-indirect split which Astroray does not surface yet).
- **Per-integrator timing bar chart** — total render time per
  integrator on the same scene at the same SPP.
- **Per-scene memory profile** — peak RSS vs scene complexity.
  Phase 2.

### 3.3 HTML index page

A static `index.html` written from a small Jinja-free string template:
links to every PNG, table from the CSV, and a header line carrying
the run's machine ID + git SHA + timestamp. No JavaScript, no
interactivity — just a way to open one file and see everything.
Phase 1 produces a minimal viable index; Phase 3 polishes it.

## 4. Reproducibility constraints

- **Fixed seeds.** Every `Renderer` instance gets `r.set_seed(seed)`
  before geometry is added. Default seed `pkg74_default = 0xCAFE`
  but the CLI accepts `--seed`.
- **Deterministic scene geometry.** Scene builders are pure Python
  functions; no use of `random`, no time-of-day-dependent
  randomness, no numpy RNG without a passed-in seed.
- **Machine tagging.** Output directory name follows the pkg71
  convention: `<YYYY-MM-DD>-<machine-id>/`. `machine-id` is
  `${hostname}-${cpu_model_short}` slugified — GPU model is
  appended later when GPU rows land in Phase 2.
- **Version tagging.** Every CSV row and the HTML index header
  carry: git commit SHA (via `git rev-parse HEAD`), Astroray
  module version (via `astroray.__version__` if exposed; otherwise
  the empty string), Python version, and the configured matplotlib +
  Pillow versions. Cycles/Blender/driver versions are explicitly
  *not* recorded — pkg74 never invokes Cycles. (That's pkg71's
  job; recording Cycles version in pkg74 would imply a comparison
  pkg74 does not make.)

## 5. Recommended starter scope (Phase 1 of pkg74)

The most-bang-for-buck starter is **the smallest set that produces
all three artefact types** (contact sheet, statistical graph,
HTML index), so the framework is exercised end-to-end and Phase 2
work is purely additive. Concretely:

1. **Material zoo contact sheet** — driven by
   `material_registry_names()`, uniform single-sphere preview from
   `_preview_helpers.add_preview_scene` (pkg74 imports the existing
   helper rather than reinventing it).
2. **Convergence grid contact sheet** — Cornell box at SPP 1, 4, 16,
   64, 256.
3. **Convergence curve PNG** — RMSE vs SPP log-log plot for the
   same Cornell render against the SPP=256 reference.
4. **stats_summary.csv** — one row per (scene, integrator), columns
   are the union of `get_integrator_stats()` keys + render time +
   peak RSS + image stats (mean luminance, p99 luminance, firefly
   count).
5. **index.html** — table from the CSV + thumbnails of every PNG.

Phase 2: integrator-comparison contact sheet, scene gallery, GPU
integrator rows, BVH/VRAM stats, variance decomposition.

Phase 3: HTML dashboard polish (plot embedding, sortable tables,
scene-vs-scene diff overlay), CI weekly hook (separate workflow
from pkg71's, runs on a non-CUDA self-hosted runner because pkg74
Phase 1 is CPU-only).

### Existing scripts pkg74 does not duplicate (and supersedes which)

| Script | pkg74's relation |
|---|---|
| `scripts/benchmarks/benchmark_showcase.py` | **Superseded** by `benchmarks/showcase/runner.py` once pkg74 lands. Three-scene composite is a strict subset of pkg74's scene gallery. Deletion is a separate PR per CLAUDE.md §3. |
| `scripts/benchmarks/benchmark_caustic_transport.py` | Not superseded — caustic-specific stats live there because they're caustic-integrator-specific. pkg74 may import its scene builders later. |
| `scripts/benchmarks/benchmark_light_transport.py` | Not superseded — NRC/path-tracer head-to-head, scoped narrower. |
| `scripts/diagnostics/material_contact_sheet.py` | **Deleted** (showcase consolidation round). Its curated per-material variant list (glass presets, disney_glass roughness sweep, metal roughness spread, etc.) was ported into `benchmarks/showcase/config.py`'s `MATERIAL_ZOO_VARIANTS`, consumed by `scenes/material_zoo.py` in addition to full registry coverage. `benchmarks/showcase/` is now the single canonical contact-sheet generator. |
| `scripts/diagnostics/convergence_tracker.py` | **Pattern reused, file untouched.** pkg74's `convergence_grid.py` reuses the SPP series and MSE helper; the existing tracker stays as the per-scene deep-dive tool. |
| `benchmarks/cycles-parity/` (pkg71) | Strictly orthogonal. Different directory, different CSV schema, no shared scenes. pkg74's runner *may* later import pkg71's `ssim.py` if pkg74 grows a "compare to pinned reference" mode in Phase 2/3. |

## 6. License + reference matrix

| Source | URL | License | How pkg74 uses it |
|---|---|---|---|
| PBRT v4 — `src/pbrt/util/stats.h` ([mmp/pbrt-v4](https://github.com/mmp/pbrt-v4)) | Apache-2.0 | Pattern for stats categories (counter / memory-counter / distribution / percent / ratio). Cite in `runner.py` header comment. No code copied — Astroray's `get_integrator_stats()` already returns a dict, and pkg74 records it untyped. |
| Mitsuba 3 — `include/mitsuba/core/profiler.h` ([mitsuba-renderer/mitsuba3](https://github.com/mitsuba-renderer/mitsuba3)) | BSD-3-Clause | `ProfilerPhase` enum is the reference list for "what stages a per-stage timing breakdown should distinguish". Phase 1 doesn't split — listed here so Phase 2 has a target. |
| Cycles — `src/util/stats.h`, `src/scene/stats.h` ([blender/cycles](https://github.com/blender/cycles)) | Apache-2.0 | Reference for scene-update categories (geometry, image, light, object, integrator, etc.). Mirrorable when/if pkg74 grows scene-update timing. Inspires the "per-component" decomposition pattern. |
| Blender Open Data benchmark | results data CC-0; web service public | Look-and-feel reference for the HTML index (scene gallery + hardware row + box plot). No code copied; we do not republish their dataset. |
| Blender benchmark scene set (Cycles `tests/integration/`) | Apache-2.0 | Not used by pkg74 — pkg74 uses Astroray-internal scenes only. Mentioned to clarify the boundary with pkg71. |
| matplotlib | PSF (BSD-compatible) | Dependency only; no code mirrored. Used for convergence + bar plots via the `Agg` backend. |
| Pillow (PIL) | HPND (permissive) | Dependency only; no code mirrored. Used for contact-sheet composition. |
| LuxMark | GPL-3.0 | **NOT USED** — incompatible with Astroray's MIT. Listed so future contributors know the boundary. |

All cited code is permissively-licensed and compatible with
Astroray's MIT. No code is mirrored verbatim in Phase 1; the
patterns are adapted with an inline citation in the file header
(format: `# pattern adapted from <repo>@<sha>:<path>`).

## 7. Open questions, deferred to Phase 2/3 owner sign-off

- Whether pkg74 should grow GPU integrator rows in Phase 2 or
  stay CPU-only by design (rationale either way: pkg71 is the
  GPU comparison; pkg74 may want CPU-only to keep the
  artefact set runnable on any developer laptop).
- Whether the HTML index should embed thumbnails or full-resolution
  PNGs (file-size implications for "open and share" use).
- Whether to wire pkg74 into a weekly CI artefact upload (Phase 3),
  or leave it as a developer-on-demand command.

These do not block Phase 1.

---

**Sources fetched 2026-05-10:**

- PBRT v4 stats header — [github.com/mmp/pbrt-v4/blob/master/src/pbrt/util/stats.h](https://github.com/mmp/pbrt-v4/blob/master/src/pbrt/util/stats.h)
- PBRT v4 sample report counters confirmed via search — [janwalter.org PBRT v4 Kroken scene report](https://www.janwalter.org/rnd/blog/rnd-pbrt-v4-001/)
- Mitsuba 3 profiler header — [github.com/mitsuba-renderer/mitsuba3/blob/master/include/mitsuba/core/profiler.h](https://github.com/mitsuba-renderer/mitsuba3/blob/master/include/mitsuba/core/profiler.h)
- Cycles util/stats — [github.com/blender/cycles/blob/main/src/util/stats.h](https://github.com/blender/cycles/blob/main/src/util/stats.h)
- Cycles scene/stats — [github.com/blender/cycles/blob/main/src/scene/stats.h](https://github.com/blender/cycles/blob/main/src/scene/stats.h)
- Blender Open Data — [opendata.blender.org](https://opendata.blender.org/) (403 on direct fetch; treated as look-and-feel-only, no code or data copied)

# pkg71 — Cycles Parity Benchmark Framework

**Pillar:** 5
**Track:** A (move to Codex once §6 acceptance, §7 metrics, and the
scene-fetch script are concrete enough to scope as a port).
**Status:** done (normalized from "implemented" — 2026-07-25 tracker audit; merged to main, see git history)
**Estimated effort:** 1 week (~25 h, multi-session)
**Depends on:** nothing hard — could run today against current `main`.
- pkg63 (HDRI/world parity) landing first makes the BMW and Pabellon
  Barcelona scenes meaningful targets (they both use HDRI environment
  lighting).
- pkg54c (Jakob–Hanika spectral upsampling on GPU) landing first
  makes the GPU spectral output stable enough that visible-band
  Astroray-GPU vs Cycles-CUDA SSIM gates are not contaminated by the
  3-Gaussian RGB→spectrum stand-in (see pkg54 lessons).

---

## Goal

**Before:** Every claim Astroray makes — "matches Cycles", "competitive
on a single RTX 5070 Ti", "render time within 2× of Cycles CUDA" — is
anecdotal. There is no reproducible scene set, no SSIM-vs-Cycles gate
on output quality, no cross-engine timing harness, no CSV history we
can plot. We cannot publish a parity number; we cannot regression-test
performance in CI; and when pkg55 (wavefront SoA) lands we will not be
able to tell honestly whether it helped or hurt versus Cycles' own
wavefront kernel.

**After:** A scripted, reproducible benchmark that renders 3–5 known
Blender Foundation demo scenes through both Cycles (CPU + CUDA) and
Astroray (CPU + GPU), records timing and memory to CSV, computes SSIM
against Cycles' published reference images from opendata.blender.org,
and emits a Markdown summary. First run produces a baseline; later
runs land in the same directory tagged with date and git SHA so we can
plot trend lines. SSIM ≥ 0.95 vs Cycles is the only correctness gate
this round; performance numbers are recorded but not gated until pkg55
and pkg56 land.

---

## Non-goals

- No benchmark of Cycles features Astroray does not support
  (volumetrics, hair/curves, subsurface scattering, displacement,
  light linking). Scene selection explicitly excludes these.
- No animation or motion-blur benchmarking — single-frame only.
- No GPU vendor comparison. NVIDIA only this round (RTX 5070 Ti
  reference machine + whatever the self-hosted CI runner has).
- No Cycles OptiX backend — its denoiser path muddles per-sample
  timing. Cycles CUDA only.
- No Astroray-vs-LuxCore or Astroray-vs-PBRT comparisons (those are
  separate packages if we ever want them).
- No new scenes authored by us. We use Blender Foundation demos
  exclusively so the comparison is against widely-cited reference
  numbers.
- No source-code changes to integrators, kernels, or material code.
  This package is harness + scenes + scripts only.

---

## Reference Implementations

The benchmark harness, scene format, sample counts, and reference
images are all derived from existing open-source work. We are not
inventing a benchmarking methodology — Blender opendata is the
canonical reference.

| Repo | Commit / Version | License | Mirror permitted | Files to study |
|------|------------------|---------|------------------|----------------|
| [blender-benchmark](https://projects.blender.org/blender/blender-benchmark) (Blender Foundation, the harness behind opendata.blender.org) | track `main` HEAD at the time of the first run; record the SHA in the first baseline CSV | Apache-2.0 | Yes — cite file + commit in our harness code | scene-runner pattern (how scenes are loaded, how device is selected, how samples-per-minute is normalised) |
| [blender (cycles)](https://github.com/blender/cycles) — `intern/cycles/test/integration/` and `tests/performance/` | track `main` HEAD; record SHA in baseline CSV | Apache-2.0 | Yes — Cycles' own perf framework is the closest precedent | per-test JSON output schema, "warm-up frame then N timed frames" pattern, how `--cycles-device` is wired |
| [blender Open Data](https://opendata.blender.org/) | n/a (web service) | results data CC0 | n/a — we consume their reference images and timings, we do not redistribute their dataset | published per-scene reference image at the canonical sample count |
| [LuxMark](https://github.com/LuxCoreRender/LuxMark) (closest third-party-engine precedent) | record SHA in baseline CSV | **GPL-3.0** | **No** — read for harness pattern only, do not mirror code | scene-loop driver, score normalisation idea (we will not adopt their score formula) |
| [LuxCoreTestScenes](https://github.com/LuxCoreRender/LuxCoreTestScenes) | n/a — read-only reference | mixed (per-scene README) | No — Blender Foundation scenes are a better match for "parity with Cycles" than LuxCore's own scenes | scene-folder layout convention only |

LuxMark is GPL-3.0 and Astroray is MIT — incompatible. We read
LuxMark's harness as a reference for the third-party-engine-benchmark
pattern (single binary, sequential scene loop, per-scene timeout,
deterministic seed) but copy no code. The blender-benchmark and
Cycles' own `tests/performance/` framework are both Apache-2.0, which
is compatible with MIT, so anything we mirror comes from those.

Cite both repo + commit SHA in any file we adapt from
(`benchmarks/cycles-parity/runner.py:12 # adapted from
blender/blender-benchmark <SHA>:scenes/runner.py`).

---

## Scene set and license audit

Per CLAUDE.md §6 and the user's explicit constraint, we must be
explicit about which scenes can live in our repo and which the user
must download. Five scenes recommended; the first three are the
minimum viable set, the last two extend coverage if/when we add
pkg63's HDRI work and material-richness coverage.

| # | Scene | Author | License | Stress | Resolution | Reference spp | Ship in repo? | Source URL |
|---|-------|--------|---------|--------|------------|---------------|---------------|-----------|
| 1 | **Cornell box (Astroray-internal)** | Astroray | MIT (ours) | trivial light transport, sanity gate | 512×512 | 64 | yes — already in `tests/scenes/` | n/a |
| 2 | **Classroom** | Christophe Seux | CC-0 | large geometry, complex indoor lighting (sun + sky + interior lamps) | 1920×1080 | 300 | **yes — CC-0 redistributable**, but ~70 MB → ship as a download script, not bytes-in-tree | `https://download.blender.org/demo/test/classroom.zip` |
| 3 | **Monster** | Blender Studio | CC-0 (per opendata.blender.org) | many materials, displacement-free hero render | 1024×1024 | 256 | **yes — CC-0**, but several hundred MB → download script | opendata.blender.org canonical asset |
| 4 | **Junkshop** | Alex Treviño | CC-BY 4.0 | dense props, glossy + textured materials, mixed direct/indirect | 2000×1000 | 240 | **no — CC-BY** can be redistributed with attribution but ~500 MB would balloon the repo. User downloads. | opendata.blender.org canonical asset |
| 5 | **BMW (BMW27)** | Mike Pan | CC-BY 3.0 | many materials, glossy car paint, studio HDRI lighting (pkg63) | 1920×1080 | 1024 | **no — CC-BY** + size. User downloads. | `https://download.blender.org/demo/test/BMW27.blend.zip` (~3 MB; small enough to ship, but we keep policy consistent: CC-BY scenes are user-downloaded so attribution stays on the original site) |

**Excluded by policy:**
- **Pabellon Barcelona** (Claudio Andres, CC-BY) — covered functionally
  by Junkshop + BMW; adds no new stress beyond size.
- **Victor** (Juan Pablo Bouza, CC-BY-NC) — non-commercial clause
  prohibits any inclusion in our repo or CI image. Cycles uses it on
  opendata; we explicitly do not. Document the exclusion in the
  benchmark README so future contributors do not "fix" the gap.

**License rules baked into the harness:**
- CC-0 scenes: download script may cache them under
  `benchmarks/cycles-parity/scenes/` (gitignored). Optionally a CI
  runner can mirror them on a Blender Foundation–approved host.
- CC-BY scenes: download script fetches to the same cache directory;
  the generated Markdown summary auto-includes the required
  attribution line per scene (author + license + source URL).
- CC-BY-NC scenes: never fetched, never referenced in CI, never
  rendered by this harness.

The download script must verify SHA-256 against a checked-in manifest
so a silently-replaced upstream cannot poison the baseline.

---

## Engine matrix

Four engines per scene, run sequentially in a single benchmark
invocation. Each engine is responsible for emitting a single output
EXR plus a JSON sidecar with timing and memory.

| Engine ID | Binary | Device flag | Notes |
|-----------|--------|-------------|-------|
| `cycles-cpu` | `blender --background --python-expr <runner>` | `cycles.device = 'CPU'` | reference for correctness |
| `cycles-cuda` | same as above | `cycles.device = 'GPU'`, `cycles.compute_device_type = 'CUDA'` | reference for performance — **OptiX excluded** (different denoiser path) |
| `astroray-cpu` | Astroray CLI (`apps/astroray_cli`) | `--device cpu` | matches the CPU reference path tracer |
| `astroray-gpu` | Astroray CLI | `--device cuda` | the headline number we want to defend |

Each engine renders the same scene at the same resolution, sample
count, and (where the API exposes it) the same RNG seed. Where seeds
cannot be matched (Cycles vs Astroray RNGs differ structurally), the
SSIM gate is computed against a dedicated reference render at the
target sample count rather than against same-seed output.

For Astroray, scene loading is via the existing Blender addon's
`.blend` → Astroray scene-graph translator (the same path the
viewport uses); no new translator is written for this package. If a
material or light type the demo scene relies on is unsupported by
Astroray today, the scene is skipped with a recorded "skip reason"
in the CSV and the harness continues — it does not abort the run.

---

## Metrics per scene per engine

Six numbers per (scene, engine) row. All collected by the harness so
results are comparable across machines.

1. **`time_first_sample_ms`** — wall time from process start to the
   first completed sample. Captures kernel JIT/PTX-load + scene-load
   + BVH-build cost. Cycles CUDA pays this on cold start; Astroray
   GPU pays a smaller version.
2. **`time_to_n_samples_ms`** — wall time for the engine to reach
   the scene's reference spp (column `Reference spp` in the table
   above), measured from the first sample boundary so scene-load
   cost is not double-counted.
3. **`peak_mem_mb`** — peak resident-set size of the engine
   process, sampled from `psutil.Process.memory_info().rss` at 50
   ms cadence on a watcher thread. On the GPU side, also record
   peak device memory via `nvidia-smi --query-gpu=memory.used`
   sampled at the same cadence — column `peak_vram_mb`.
4. **`ssim_to_cycles_ref`** — SSIM of this engine's output against
   the Cycles canonical reference image for the scene at the
   reference spp. Reference is Cycles-CPU output at reference spp,
   downloaded once and checked into `benchmarks/cycles-parity/refs/`
   with a SHA-256 manifest. We use Cycles-CPU rather than the
   opendata.blender.org PNG because we need EXR-precision input to
   SSIM and PNG quantisation pollutes the metric. (Use
   `skimage.metrics.structural_similarity` with `channel_axis=-1`
   on linear-light EXR data, no tone-map.)
5. **`viewport_ms_per_step`** *(Astroray only, optional)* — for the
   Astroray CPU + GPU rows on each scene, also record the median
   per-step time of the first 16 progressive accumulation steps.
   This is the number that drives the "interactive in viewport"
   claim. Cycles rows leave this column empty — apples-to-oranges.
6. **`engine_version`** + **`git_sha`** + **`device_id`** — recorded
   once per row so historical CSVs are interpretable when binaries
   evolve.

Timing methodology copies Cycles' `tests/performance/` pattern: one
discarded warm-up render per scene per engine to prime caches and
JIT, then the timed render. Three timed runs per (scene, engine);
report the **median** to the CSV. Standard deviation across the
three runs is recorded as `time_to_n_samples_stddev_ms` so we can
see when noise drowns the signal.

---

## Output format

### CSV — one row per (scene, engine) per run

`benchmarks/cycles-parity/<YYYY-MM-DD>-<machine-id>-<git-sha>.csv`

```
scene,engine,samples,time_first_sample_ms,time_to_n_samples_ms,time_to_n_samples_stddev_ms,peak_mem_mb,peak_vram_mb,ssim_to_cycles_ref,viewport_ms_per_step,engine_version,engine_git_sha,device_id,skip_reason
cornell,cycles-cpu,64,142,1830,12,512,,1.000,,4.2.1,abc123,Ryzen-7950X,
cornell,cycles-cuda,64,1240,210,4,623,1180,0.998,,4.2.1,abc123,RTX-5070-Ti,
cornell,astroray-cpu,64,89,2110,18,438,,0.971,,0.x.y,c80937e,Ryzen-7950X,
cornell,astroray-gpu,64,610,260,6,512,940,0.962,18.5,0.x.y,c80937e,RTX-5070-Ti,
classroom,cycles-cpu,300,...,...,...,...,...,1.000,,...,...,...,
classroom,astroray-gpu,300,...,...,...,...,...,...,...,...,...,...,unsupported_material:subsurface
```

`machine-id` is `${hostname}-${cpu_model_short}-${gpu_model_short}`
slugified, so multiple runners can write into the same directory
without collision.

### Markdown summary — auto-generated from the CSV

`benchmarks/cycles-parity/<YYYY-MM-DD>-<machine-id>-<git-sha>.md`

A pivot table per metric (rows = scenes, columns = engines), an
Astroray-vs-Cycles ratio column for `time_to_n_samples_ms` and
`peak_mem_mb`, the SSIM column highlighted red if any cell drops
below 0.95, and at the bottom the required CC-BY attribution block
listing every CC-BY scene rendered in this run.

The summary script lives at `benchmarks/cycles-parity/summarise.py`
and reads only the CSV — no scene re-rendering, no SSIM
re-computation. Anyone with the CSV can rebuild the Markdown.

### Reference image storage

`benchmarks/cycles-parity/refs/<scene>-<spp>.exr` plus
`benchmarks/cycles-parity/refs/MANIFEST.sha256`. Refs are
regenerated only when the Cycles version changes; the manifest
records `cycles_version` + `cycles_git_sha` + `seed` so the
provenance is auditable.

---

## CI integration

Two triggers, one runner, no perf gates this round:

1. **Weekly scheduled run** on a self-hosted runner with the RTX
   5070 Ti reference card. Workflow file
   `.github/workflows/cycles-parity-weekly.yml`. Runs the full
   matrix (4 engines × 3–5 scenes), commits the resulting CSV +
   Markdown to a dedicated branch (`benchmarks/cycles-parity-history`),
   and opens a tracking issue if any scene's `ssim_to_cycles_ref`
   drops below 0.95 vs the previous week's CSV.
2. **On-demand PR comment trigger.** A PR commenter writes
   `/benchmark cycles-parity` (or just the Cornell + Classroom subset
   for cheap PRs); the workflow picks it up, runs only the affected
   subset, and posts the Markdown summary back as a PR comment with
   a diff vs the most recent baseline. Pattern is the same as
   Cycles' `+test_gpu_cycles` PR-comment trigger
   ([Blender perf-test handbook](https://developer.blender.org/docs/handbook/testing/performance/)).

**No perf-regression gates.** SSIM ≥ 0.95 is the only failing
condition this round. Time-to-N-samples is recorded but never
breaks CI. Reason: pkg55 (wavefront SoA) and pkg56 (incremental
scene sync) are expected to move performance numbers significantly
in both directions during their landing windows; gating now would
produce constant false alarms. Perf gates are pkg72-or-later, after
pkg55 and pkg56 stabilise.

CSV history lives in `benchmarks/cycles-parity/`. We do not delete
old CSVs; trend plots are generated on demand from the directory.

---

## Files to create

| File | Purpose |
|---|---|
| `benchmarks/cycles-parity/README.md` | What the benchmark is, how to run it locally, scene-licensing rules, how to add a new scene, attribution block template |
| `benchmarks/cycles-parity/scenes/manifest.toml` | Per-scene: source URL, SHA-256, license, attribution string, reference-spp, resolution, "ship-in-repo" boolean |
| `benchmarks/cycles-parity/scenes/fetch.py` | Downloads scenes listed in `manifest.toml`, verifies SHA-256, refuses to fetch CC-BY-NC entries (defence in depth) |
| `benchmarks/cycles-parity/refs/MANIFEST.sha256` | SHA-256 of every reference EXR plus the Cycles version that produced it |
| `benchmarks/cycles-parity/runner.py` | Top-level orchestrator: iterates (scene × engine), spawns subprocesses, collects timing/memory, writes the CSV |
| `benchmarks/cycles-parity/runners/cycles_runner.py` | Spawns `blender --background --python <script>`, parses stdout for sample-tick events, returns a row dict |
| `benchmarks/cycles-parity/runners/astroray_runner.py` | Spawns the Astroray CLI with the same scene + spp, parses progress events, returns a row dict |
| `benchmarks/cycles-parity/ssim.py` | EXR-vs-EXR SSIM helper using `skimage.metrics.structural_similarity`, linear-light, channel-axis=-1, no tone-map |
| `benchmarks/cycles-parity/summarise.py` | CSV → Markdown pivot table + attribution block |
| `.github/workflows/cycles-parity-weekly.yml` | Weekly self-hosted run + threshold issue-opener |
| `.github/workflows/cycles-parity-on-demand.yml` | PR-comment-triggered subset run |

### Files to modify

| File | What changes |
|---|---|
| `.gitignore` | Add `benchmarks/cycles-parity/scenes/` (downloaded blobs) and `benchmarks/cycles-parity/refs/*.exr` (large binary artefacts; SHA-256 manifest stays) |
| `apps/astroray_cli/main.cpp` (only if needed) | Verify it accepts `--scene`, `--samples`, `--device`, `--output`, `--seed` and emits a one-line-per-sample progress signal the runner can parse. If the CLI already does this, no change. **Audit before assuming a change is needed.** |
| `.astroray_plan/docs/STATUS.md` | Add a "Pillar 5 — pkg71 benchmark framework" line under the Pillar 5 status block |
| `AGENTS.md` | One-liner under "Build & Test" pointing at `benchmarks/cycles-parity/README.md` |

---

## Key design decisions

1. **Cycles-CPU is the SSIM reference, not opendata.blender.org PNGs.**
   PNG quantisation eats the bottom ~3 SSIM points on noisy renders
   and makes the gate meaningless. Cycles-CPU EXR at the canonical
   spp + Sobol seed = a deterministic ground truth we control.
2. **Median of 3 timed runs.** Single-run timings on a desktop
   fluctuate enough to mask 10% changes; three runs + median is
   what Cycles' own `tests/performance/` does, and it is the
   cheapest robust estimator.
3. **Process-level timing, not in-engine instrumentation.** Cycles
   and Astroray will never agree on what counts as "frame start";
   wall-clock from process spawn (with one warm-up discarded) is the
   only fair comparison. This also means the harness does not need
   either engine to grow new APIs.
4. **Subprocess isolation per (scene, engine).** Catches PTX-cache
   contamination, GPU memory fragmentation, and OIDN model reloads.
   Slower than in-process, but the only way the numbers stay
   comparable across runs.
5. **CC-BY-NC defence in depth.** The `fetch.py` script holds an
   explicit deny-list including Victor; the manifest format does not
   even have a slot for a CC-BY-NC URL. A future contributor cannot
   accidentally add Victor without rewriting the schema.
6. **No new physics, no new integrators, no kernel changes.** This
   package is pure measurement infrastructure. CLAUDE.md §3 applies:
   surgical changes, do not "improve" Astroray's CLI flag parsing
   while you are there.

---

## Acceptance criteria

- [ ] `python benchmarks/cycles-parity/scenes/fetch.py` downloads
      Classroom (CC-0) and Monster (CC-0) into the cache directory,
      verifies SHA-256 against `manifest.toml`, and refuses to fetch
      anything tagged CC-BY-NC.
- [ ] `python benchmarks/cycles-parity/runner.py` runs the full
      matrix on the local box and writes a CSV with at least the
      Cornell + Classroom rows populated for all four engines.
      Failed/skipped engines record a `skip_reason` rather than
      crashing the run.
- [ ] `python benchmarks/cycles-parity/summarise.py <csv>` emits a
      Markdown pivot table with the CC-BY attribution block at the
      bottom.
- [ ] Cornell-box `ssim_to_cycles_ref` ≥ 0.95 for both Astroray-CPU
      and Astroray-GPU. (Cornell is our control; if this fails the
      harness or the SSIM helper is wrong, not Astroray.)
- [ ] Classroom `ssim_to_cycles_ref` ≥ 0.95 for Astroray-CPU. The
      Astroray-GPU number is recorded but only gated at 0.90 this
      round, since pkg54c is the prerequisite for visible-band
      parity ≥ 0.95.
- [ ] Weekly CI workflow runs once on the self-hosted runner without
      manual intervention; the run commits to the
      `benchmarks/cycles-parity-history` branch; the PR-comment
      trigger workflow exists and is documented in the README.
- [ ] `benchmarks/cycles-parity/README.md` documents the
      scene-licensing rules, including the explicit Victor exclusion
      and the CC-BY attribution requirement, and points new
      contributors at this spec for rationale.

---

## Risks and mitigations

| Risk | Mitigation |
|------|------------|
| Cycles version drift changes the reference EXRs out from under us | Pin Cycles version in `manifest.toml`; refs only regenerated by an explicit script bump; CI uses the pinned Blender |
| Astroray's `.blend` translator silently drops a feature (e.g. world HDRI rotation) and the SSIM degradation looks like a perf bug | Per-scene `skip_reason` column; SSIM regressions on a previously-passing scene open a tracking issue, not a CI fail |
| Self-hosted runner GPU thermals drift on long runs and inflate timing | Three timed runs + stddev column makes thermal drift visible; large stddev is a flag for the operator, not silent noise |
| CC-BY attribution forgotten in a downstream republish of the CSV | Markdown summary always carries the attribution block; CSV header carries a `# attribution: see <url>` comment line; README spells out republishing rules |

---

## Lessons

- Framework landed with the requested `benchmarks/cycles-parity/` scene
  metadata/cache layout, root `scripts/run_parity.py` and
  `scripts/summarize_parity.py`, and the self-hosted CUDA/Cycles workflow.
- First implementer-machine CSV:
  `benchmarks/cycles-parity/2026-05-10-local-smoke-d614e03.csv`. It is a local
  smoke baseline, not the canonical self-hosted Cycles 4.x/CUDA baseline:
  Cornell Cycles CPU `10843.458 ms`, Cycles CUDA `3634.148 ms`,
  Cycles CPU SSIM `1.000000`; local Astroray standalone rows skipped with
  process exit `3221225781`. The canonical full baseline remains pending CUDA
  hardware/runner setup.
- Victor remains excluded with defense in depth in `fetch_scenes.py`: the
  disallowed URL list is asserted non-empty and includes a sentinel entry.

# Architect plan — 2026-09-27

Owner-authorised Fable architect run (2026-09-25). Input: STATUS.md,
`next-session-prompt-2026-09-24.md`, `astra_run/progress.md`, the 2026-09-27
open-issue list, main 573fbce3. In flight, not re-specced: PR #916 (Batch AB:
#897, pkg283, #873, #877, #908, #909) and Batch AC (#912, #904, #906).

Specs written this run (all lint-clean): pkg284 corpus v2, pkg285 bank
re-bless (#898), pkg286 photon power (#914), pkg287 per-light photons (#910),
pkg288 lamp-hit continuation (#915), pkg289 medium chromatic noise (#913 +
#917 + #904 gaps), pkg290 clamp metric (#884), pkg291 viewport gate (a)
(#879 #875 #855 #721), pkg292 GPU/CPU ladders (#876 #862 #853), pkg293 GPU
Disney per-hit lobe weights (#889).

## 1. Direction (architect view)

1. Correctness before re-blessing. Every reference on disk was rendered on an
   engine that has since had five transport fixes; blessing now would encode
   whatever Batches AD/AE change. So: AD (lamp/clamp/MIS) → AE (photons) →
   references (pkg284 Phase 2, pkg285 Phase 2).
2. Gates become per-ROI per-channel mean ratios with MC-derived bands, fixed
   seed, adaptive off. SSIM/pHash stay only for Astroray-only silhouettes
   (GR). This is the single biggest lever against "visually identical, gate
   red" and against tests that lock in bugs.
3. GPU/CPU disagreement is the largest unexplained risk (Disney under a sun
   1.84×). It is an Opus-lane class of work; do not delegate it.
4. Viewport: fix the crash that the owner try-out would hit before asking
   the owner to try it out. The default flip stays the owner's.

## 2. Issue triage

### Batchable now (well-specified in the issue; one lane each)

| # | Item | Lane / backend | Files (conflict key) |
|---|---|---|---|
| #886 | closed-emitter back-face pdf in `LightSampler::pdfValue` | CPU, Opus | `raytracer.h` LightList |
| #888 | `sms_energy` unsynchronised float | CPU, Flash | `sms_caustic_path_tracer.cpp` |
| #861 | pkg268 visual test writes into tracked `test_results/batchF` | CPU, Flash | one test |
| #864 | pkg258 byte-identity baseline module resolution | CPU, Flash | one test |
| #868 | GPU lock: live holder expires at 90 min; atomic acquire | none, Flash | `locks.py`, `gpu_locked_run.py` |
| #869 | worktree build route without the CUDA sccache launcher | none, Flash | `build_cuda_worktree.bat` |
| #872 | coverage-matrix regen == committed | Blender, Flash | `settings_map.py`, generator |
| #895 | shape plugin forwards spin + r_obs_M | CPU, Flash | `plugins/shapes/black_hole.cpp` |
| #894 | Page-Thorne Kerr disk flux + Kerr orbit g | CPU, Opus (cite Page & Thorne 1974; GYOTO fixture) | `accretion_disk.h` |
| #881 | Noise Texture port from Cycles `svm/noise*.h` | CPU+GPU, Opus | `noise` texture CPU + pkg190 bake |
| #891 | Mapping after a non-affine warp as in-program affine op | addon+CPU+GPU, Flash with Opus review | `shader_vm_compiler.py` |
| #890 | GPU procedural bake: 128³ + trilinear (pick this; HD per-hit eval is register-risky) | GPU, Opus | `stage_advance.cu` texture fetch, bake |
| #848 | hero-λ logistic constants re-fit to 2° (CPU+GPU lockstep) | CPU+GPU, Flash | `spectrum.cpp`, `stage_init.cu` |
| #832 | env texel-centre `-0.5` in all four lookups | CPU+GPU, Flash; expect HDRI baseline churn → re-pin with attribution | `raytracer.h`, `gpu_bvh.h`, `gpu_env_spectral.cuh` |
| #878 | CPU restir-di colour cast under a sun | CPU, Opus (bounded: spectral target function) | `restir_di.cpp` |
| #773 | addon rough-glass limb −15 % vs in-process | addon, Sonnet (export-dict bisect) | `__init__.py` glass export |
| #866 | native adaptive toggle routed to the sampler | addon, Flash | `settings_map.py`, `__init__.py` |
| #867 | native Debug Sample Count pass | addon+engine, Opus | `blender_module.cpp`, `__init__.py` |
| #36 | indirect-only objects + GPU holdout (CPU holdout landed #830) | CPU+GPU, Opus | visibility flags, `stage_advance.cu` |
| #833 | minimum: DEGRADED report for mesh-volume-as-AABB (engine volume stack later) | addon, Flash | `volume_export.py` |

### Needs a spec (written)

pkg284 (corpus, folds #763 as the noise-vs-Cycles row), pkg285 (#898),
pkg286 (#914), pkg287 (#910), pkg288 (#915), pkg289 (#913 #917 #904-gaps),
pkg290 (#884), pkg291 (#879 #875 #855 #721), pkg292 (#876 #862 #853),
pkg293 (#889).

### Paused / owner decision

- #858 default flip of the viewport worker — owner, after pkg291 lands.
- Gate (c) trio remap onto corpus v2 (pkg284 decision) — owner.
- #789, #783 rough-glass chromatic / thin-film walk — paused enhancements
  (pkg265 follow-ups; no product pull yet).
- #865 delegate critic non-completion — tooling, paused until it recurs.
- #398 engine-agnostic core / Hydra, #39 persistent data, #38 tiled
  rendering — horizon items, Pillar 5 later.
- #144, #141 — Pillar 4 (paused).
- #833 engine-side volume stack — after the addon report; owner said low.

### Close-as-obsolete (do not close yourself; say why)

- #855 — superseded: #849 landed in-place material/light re-sync (#882);
  the re-measure is pkg291's table row. Close when pkg291 lands.
- #721 — close on pkg291's measured table (its static cause, synchronous
  `renderer.render` in `view_draw`, was removed by pkg241/pkg266).
- #763 — the named cause (light-tree bias, #851) landed in #893; the corpus
  noise row moves to pkg284 (`v2_light_tree` variance vs Cycles at 64 spp).
  Close when pkg284 lands with that row green.

## 3. Dispatch plan (batches of 3–5, ordered)

Lead runs every CUDA build; suite alone; ≤ 2 CPU lanes under the load
policy. "Shared" = same file region; sequence those within the batch.

### Batch AD — light-transport correctness (CPU first, one GPU build)
1. pkg288 lamp-hit continuation (#915) — CPU `raytracer.h` lamp block +
   `stage_advance.cu` intersect stage. GPU.
2. pkg290 clamp metric (#884) — `raytracer.h::clampContribSpectral` +
   `gpu_spectral_tables.h`. GPU. Shares `raytracer.h` with 1 (different
   region; merge 1 first).
3. #886 back-face emitter pdf — `raytracer.h` LightSampler. CPU only.
   Shares `raytracer.h`; merge after 1 and 2.
4. #888 sms_energy — CPU only, isolated file.
5. #878 restir-di colour cast — CPU only, isolated file.
Gates: pkg288/pkg290 tests + #883 near-light + pkg181 + #912 (all
channels) + full suite; corpus v1 geometry_zoo cabinet ≥ 0.97 of Cycles.

### Batch AE — caustics and media (GPU-heavy; ONE lane for 1→2)
1. pkg286 photon power (#914) — then in the same lane
2. pkg287 per-light photon emission (#910). Shared: `photon_caustic.cu`,
   `spectral_path_tracer.cpp`, `gpu_photon_caustic.h`. GPU.
3. pkg289 medium chromatic noise (#913 #917 #904 gaps) — `raytracer.h`
   medium blocks, `stage_advance.cu`, `stage_volume_hetero.cu`,
   `spectral_path_tracer.cpp` (guide/caustic walk: coordinate with lane 1
   on that file; rebase after 1). GPU.
4. #36 indirect-only + GPU holdout — `stage_advance.cu` visibility; rebase
   after 3.
Gates: pkg286 furnace, pkg287 four-light test, pkg289 variance ladder,
showcase glass (spot) + volumes re-render inspected by the lead.

### Batch AF — GPU/CPU divergence (Opus lanes, one GPU at a time)
1. pkg292-#876 Disney under a sun — `gpu_materials.h`.
2. pkg293 per-hit lobe weights (#889) — `gpu_materials.h`,
   `shader_vm_compiler.py`, `scene_upload.cu`. Shares `gpu_materials.h`
   with 1; merge 1 first, ptxas audit after both.
3. pkg292-#862 env-Cornell red — `gpu_env_spectral.cuh`/`gpu_bvh.h`; pair
   with #832 texel-centre (same functions, same lane, one re-pin).
4. pkg292-#853 hair lobes — `gpu_hair.cuh`, isolated.
5. #890 bake 128³ + trilinear — bake + fetch; isolated from 1–2 if the
   fetch helper is separate; else after 2.
Gates: per-spec ±5 % tests; pkg55/pkg123/pkg160/pkg225 at original bands;
SASS hash unchanged for `HasProgram=false`.

### Batch AG — references and parity infrastructure (after AD + AE)
1. pkg284 corpus v2 Phase 1–2 (scenes, `mc_tolerance.py`, references) —
   Blender + both backends; 3 legs per scene under the GPU lock.
2. pkg285 bank re-bless Phase 1 (GR, cornell, disney) can start with AD;
   Phase 2 (caustic scenes) after AE.
3. #872 matrix regen — Blender, no engine.
4. #861, #864 — test hygiene, no engine. Bundle as one Flash lane.
Gates: `test_corpus_v2_parity.py`, bank 13/13, `test_reference_corpus_manifest.py`.

### Batch AH — viewport (addon + one engine binding; isolated GUI)
1. pkg291 #879 crash (lifecycle) → #875 in-place transforms → gate (a)
   table. One Opus lane, sequential; GPU.
2. #866 native adaptive toggle, #867 Debug Sample Count pass — addon +
   `blender_module.cpp`; Flash for #866, Opus for #867. Share
   `__init__.py` with 1: merge 1 first.
Gates: lifecycle + transform tests; gate (a) table doc; pkg266 §9 rows
unchanged; addon file list.

### Batch AI — GR + textures (CPU, cheap; can interleave with AF)
1. #894 Page-Thorne Kerr disk (Opus, GYOTO fixture) + #895 plugin spin
   (Flash) — `accretion_disk.h`, `black_hole.cpp`; same lane.
2. #881 Noise port (Opus) — CPU noise + pkg190 bake path (touches the
   bake; rebase after AF-5).
3. #891 Mapping-after-warp (Flash + Opus review) — `shader_vm_compiler.py`
   (shares with AF-2; merge after it).
4. #848 hero-λ constants (Flash, lockstep CPU/GPU), #773 addon glass limb
   (Sonnet bisect), #833 DEGRADED report (Flash) — three small lanes.
Gates: GYOTO a=0.94 disk image; noise correlation ≥ 0.98; reversed-order
Mapping test CPU+GPU; pkg206 chromatic-noise benchmark.

### Batch AJ — tooling (no GPU, any idle window)
#868 lock, #869 build launcher, #865 (only if it recurs).

## 4. Owner decisions surfaced

1. Gate (c) trio remap onto v2 (`v2_light_tree` / `v2_textures_opvm` /
   `v2_camera_geometry`) — or keep the v1 trio on disk. pkg284 keeps v1
   files until answered.
2. Default flips after #858: viewport worker (pkg291 gives the numbers);
   also still OFF by default per memory `landed-features-off-by-default-audit`:
   pkg224 progressive sampler and pkg86 light tree on GPU (CPU tree is on
   via pkg262). Listed, not decided.
3. Caustic `boost` default becomes 1.0 (physical) in pkg286; the old 1.2
   was a display constant. Confirm or keep 1.2 as an artistic default.
4. #833 engine-side mesh-bounded volumes: owner said low; the plan only
   ships the DEGRADED report. Say if the icosphere case matters for the
   showcase.

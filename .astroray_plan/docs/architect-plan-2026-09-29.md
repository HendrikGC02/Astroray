# Architect plan — 2026-09-29

Owner-authorised short Fable architect run with Astra (Codex `gpt-6-astra`,
read-only, 3 turns: propose → critique → converge, final VERDICT: ACCEPT). Input: main 1a0cf783,
STATUS.md 2026-09-27 entries, `architect-plan-2026-09-27.md`,
`lane-rules.md`, `reports/2026-09-27-night-shift.html`, open issues (36).
Supersedes the 09-27 batches AG–AJ; AD, AE, AF, pkg292 #876/#862, #929/#932
landed.

New specs (lint-clean): **pkg294** area-lamp solid-angle pdf + tree at
volume points (#922; unblocks pkg290), **pkg295** Principled metal −15 %
(#934) + GPU partial-transmission Disney (#933). Amended: pkg290 (blocked on
pkg294; metric change dropped), pkg292 (#933/#934 → pkg295), pkg284 (#926
coplanar note; assertion-level provisional rows).

## 1. Direction

1. **Corpus v2 (pkg284) goes first, in parallel with the physics lanes**, not
   after them. It is the regression net; transport fixes move Astroray
   evidence, not the Cycles reference. Provisional rows are per (scene,
   backend, ROI, channel) tied to an issue, never a whole scene.
2. **pkg285 bank re-bless after Batch AK** (pkg294/pkg295 move media and
   metal references). Bless all 13; GR rows (gr-*, adaf, jet) get a second,
   limited re-bless after #894/#895 — do not promise one final blessing.
3. **#922 is the highest-value physics item** (media variance; pkg290 and
   `v2_media` hang on it). Verified 2026-09-29 in Cycles `kernel/light/area.h`:
   the in-volume-segment draw is area-uniform; the lamp-hit forward pdf and
   the post-distance `light_sample_update` are spherical-rectangle. pkg294
   mirrors exactly that and starts with a half-day attribution ablation
   (one-lamp vs three-lamp cube, hit-site pdf only, tree on/off, equal spp
   and equal time). Phase 2 (segment light tree, P/D/t) only if the ablation
   convicts selection.
4. **GPU/CPU + Cycles material gaps in one Opus lane** (pkg295 #934 → #933),
   then pkg293 on the same file. Register rule: no new per-hit live state in
   the shade kernel; spill → `__noinline__` runtime flag, never a wider band.
5. **Viewport: fix the crash before asking for the try-out** (pkg291 #879),
   #875 transforms are Opus work (BVH refit, partial upload, lifecycle); the
   gate (a) table is Sonnet 5.5 on a quiet machine.
6. **Model split.** Opus 5.5: pkg294, pkg295, pkg293, #879/#875, #894, #36,
   hair/noise diagnosis. Sonnet 5.5: corpus/bank construction and runs,
   bisects, bounded ports, tables, verification. Terra: independent review of
   every lane + bounded single-subsystem fixes (#868, #869, #895, #833,
   #920). Luna: lint/PR-body/closing-keyword checks. Flash: docs, test
   hygiene, status flips.

## 2. Load rules (binding)

≤3 implementing lanes at any time (AGENTS.md); ≤2 heavy CPU jobs counting
CUDA builds, Blender reference renders and suites; GPU suite never overlaps
a build; viewport timing on a quiet machine; keep the pre-batch binary for
attribution and budget one corrective build per batch.

## 3. Batches

"Conflict key" = files/subsystems; items sharing a key are sequenced in the
order listed. Lane model in brackets. Gates are numbers to hit.

### Batch AK0 — day 0, CPU diagnostic build only, no CUDA build (∥ all three)

| # | Item | Lane | Backend | Conflict key |
|---|---|---|---|---|
| 1 | #868 GPU lock: live holder expires at 90 min; atomic acquire | Terra | none | `scripts/build/locks.py`, `gpu_locked_run.py` |
| 2 | pkg294 Phase 0 attribution ablation (mean-preserving, paired-MIS variants only) | Opus | CPU MinGW build + Cycles headless (heavy; serialise build and render legs) | env switch, deleted before Phase 1 |
| 3 | pkg284 Phase 1: v2 scene builders, manifests, Cycles references | Sonnet 5.5 | Blender headless (heavy) | `benchmarks/reference_corpus/`, `blender_showcase/showcase.py` builders |

Gates: #868 test (holder survives 91 min; contended acquire never double-grants); Phase 0 table with the convicted term, every variant's means inside the baseline 3-seed MC band; 8 `v2_*.blend` + `gates_v2.toml` with seed 278, adaptive off, three-seed MC bands.

### Batch AK — from day 0/1; ONE CUDA build at the end (pkg294 Phase 1 + pkg295) + 1 corrective; pkg294 Phase 2, if convicted, is its own PR and build

| # | Item | Lane | Backend | Conflict key |
|---|---|---|---|---|
| 1 | pkg294 Phase 1 (+2 if convicted) — #922 | Opus | CPU then GPU | `src/lights/area_light.cpp`, `lamp_sampling.h`, `gpu_nee.cuh`, `stage_volume_hetero.cu`, `raytracer.h` medium NEE, `light_tree*` |
| 2 | pkg295 #934 → #933 | Opus | CPU + GPU | `plugins/materials/disney.cpp`, `gpu_materials.h` |
| 3 | pkg284 Phase 2: `test_corpus_v2_parity.py`, assertion-level provisional rows | Sonnet 5.5 | both (GPU legs under lock) | `benchmarks/reference_corpus/`, `tests/test_corpus_v2_parity.py` |
| 4 | pkg291 #879 worker-flip crash (when a slot frees) | Opus | GPU, isolated Blender 9877, quiet machine | `blender_addon/exporter.py`, `module/blender_module.cpp` |
| 5 | #921 + #773 addon export energy bisects (when a slot frees) | Sonnet 5.5 | addon, CPU | `blender_addon/__init__.py` lamp + glass export |

Gates: pkg294 clamp-off cube variance ≤ 1.5× Cycles at 64 spp (one- and three-lamp) with means unchanged inside the MC band, NEE on/off ≤ 1 %, `test_883`/`pkg288`/`925`/`929`/#852 booth unchanged; pkg295 metallic=1 sun rung within ±5 % of Cycles (was 0.846), partial-transmission GPU/CPU ±5 %, furnace linear mean in [0.98, 1.005] (`apply_gamma=False`), `pkg123` band kept, REG ≤ 254; pkg284 every non-provisional (scene, backend, ROI, channel) row in band, both backends; pkg291 0 crashes over 20 flips × 2 scenes; #921 addon vs engine-only ≤ 2 % (same for #773 limb, else escalate to Opus at the BSDF). Full RTX suite before the PR.

### Batch AL — after AK merge + rebuild (baseline binary kept)

| # | Item | Lane | Backend | Conflict key |
|---|---|---|---|---|
| 1 | pkg290 re-measure: close #884 or name the residual | Sonnet 5.5 | CPU + GPU | evidence only |
| 2 | pkg293 per-hit lobe weights (#889) | Opus | GPU | `gpu_materials.h` (after pkg295), `scene_upload.cu`, `shader_vm_compiler.py` |
| 3 | pkg285 interim bank re-bless: non-GR rows blessed with `blessed_on` commit; GR rows deferred to AN-1 (13/13 only then) | Sonnet 5.5 build + Terra attribution review + Opus visual sign-off | CPU bank (heavy), GPU legs under lock | `benchmarks/reference_bank/` |
| 4 | #924 lamp pass-through cap (Opus design note first) | Sonnet 5.5 | CPU + GPU | `raytracer.h` ~3480, `stage_advance.cu` intersect, `path_kernel.cpp`, MW tracer |

Gates: #884 loss within 2 points of Cycles at limit 10 (cabinet ≥ 0.97 clamp-on); pkg293 `test_issue846` xfail flipped, `HasProgram=false` SASS identical, REG ≤ 254; interim bank: every non-GR row green with `blessed_on` + `ATTRIBUTION-2026-09.md`; #924 six collinear lamps NEE on/off ≤ 1 %, zero-emission lamps consume no slot.

### Batch AM — ∥ AL where files allow

| # | Item | Lane | Backend | Conflict key |
|---|---|---|---|---|
| 1 | pkg291 #875 in-place transforms → gate (a) table (#855, #721) | Opus → Sonnet 5.5 (table, quiet machine) | GPU | `exporter.py`, `blender_module.cpp`, `scene_upload.cu` (after pkg293) |
| 2 | #853 hair ladder → fix (pkg292) | Sonnet 5.5 ladder → Opus fix | GPU | `gpu_hair.cuh`, `principled_hair.cpp` |
| 3 | #881 Noise port (literal, version-pinned Cycles `svm/noise*.h`) | Sonnet 5.5 + Terra | CPU + bake | `noise` texture, pkg190 bake |
| 4 | #890 bake 128³ + trilinear | Sonnet 5.5 + Opus review | GPU | bake + fetch; after #924 in `stage_advance.cu`, after 3 |
| 5 | #891 Mapping after a non-affine warp | Sonnet 5.5 | addon + CPU + GPU | `shader_vm_compiler.py` (after pkg293) |

Gates: transform edit ≤ 30 ms on 100k, gate (a) p95/p99 table worker ON/OFF × 2 scenes × 5 reps; hair per-lobe GPU/CPU ±5 % (pkg225 band unchanged); noise correlation ≥ 0.98 vs Cycles; warped-checker stripes resolved (SSIM vs CPU ≥ 0.95 on the card); reversed-order Mapping test CPU + GPU.

### Batch AN — CPU-cheap, any free slot

| # | Item | Lane | Backend | Conflict key |
|---|---|---|---|---|
| 1 | #894 Page-Thorne Kerr disk + #895 plugin spin → GR bank rows re-bless | Opus + Terra → Sonnet 5.5 | CPU | `accretion_disk.h`, `plugins/shapes/black_hole.cpp`, bank gr-*/adaf/jet |
| 2 | #866 native adaptive toggle | Flash | addon | `settings_map.py`, `__init__.py` |
| 3 | #867 Debug Sample Count pass (fixed AOV contract from the lead) | Sonnet 5.5 | addon + engine | `blender_module.cpp`, `__init__.py` (after 2) |
| 4 | #833 DEGRADED report (minimum; engine stack is an owner decision) | Terra | addon | `volume_export.py` |
| 5 | pkg284 Phase 3 harness/bench wiring + #926 parity-doc note | Flash | none | `benchmarks/blender_parity/` docs |

Gates: GYOTO a = 0.94 disk image; gate (d) smoke (sample-count AOV differs, flat-region noise falls); DEGRADED line in the report; `test_reference_corpus_manifest.py`.

### Batch AO — GPU queue tail and idle windows

#36 indirect-only + GPU holdout [Opus; `stage_advance.cu` visibility — GPU
queue, not CPU-cheap]; #869 build launcher [Terra]; #920 device SMS weight
port + CPU/GPU unit parity [Terra]; #872, #861, #864 [Flash]; #865 only if
it recurs.

## 4. Parallelism summary

AK0 ∥ (three lanes). AK follows as slots free (never > 3 implementing). AL
after AK's merge and rebuild. AM ∥ AL except the named file orders (pkg293
→ #875/#891; #924 → #890; #881 → #890). AN fills free CPU slots any time;
AN-1 before the GR bank re-bless. AO in the GPU tail / idle windows.

## 5. Closures expected

#855 and #721 close on the AM-1 table; #763 on pkg284 `v2_light_tree` green;
#884 on AL-1; #876-class #933 on pkg295; #922 on pkg294; #926 doc-only.

## 6. Owner decisions (listed, not made)

1. Caustic `boost` default 1.2 → 1.0 (1.0 is physical after pkg286; 1.2 is
   20 % hot).
2. Gate (c) trio remap onto corpus v2 (`v2_light_tree` / `v2_textures_opvm`
   / `v2_camera_geometry`) or keep the v1 trio on disk.
3. #858 default flips after the try-out: viewport worker (pkg291 gives the
   numbers), pkg224 progressive sampler, pkg86 GPU light tree.
4. #833: engine-side volume stack vs the DEGRADED report only (plan ships
   the report).
5. (minor) #926: keep physics (default) or mimic Cycles' coplanar-face
   darkening for look-parity.

## 7. Astra turn log

Turn 1 (critique): corpus-first confirmed; pkg294's assumed Cycles path was
wrong (segment draw is area-uniform, hit pdf spherical-rectangle) → spec
rewritten with a Phase 0 ablation; ≤3 implementing lanes; #875 → Opus;
#36 → GPU queue; #868 → opening slot; GR bank rows deferred; provisional
rows assertion-level. Turn 2 (REVISE): pkg294↔pkg290 dependency cycle
removed, pkg293 depends on pkg295; Phase 0 needs a CPU diagnostic build and
mean-preservation per variant (a pdf-only run that lowers variance while
moving a mean is not evidence); build budget reconciled (Phase 1 rides AK's
build, Phase 2 its own); pkg295 furnace `apply_gamma=False` with a ceiling;
pkg284 parametrised per (scene, backend, ROI, channel); pkg285 interim bank
in AL, 13/13 after the GR re-bless. All applied. Turn 3: **VERDICT: ACCEPT**
("no blocking defect remains"); highest-rated risk: a biased sampling
change blessed into references because it looked like a variance win —
hence the mean-preservation rule in pkg294 Phase 0.

## 8. Dispatch today

AK0 (three lanes, no CUDA build): #868 [Terra], pkg294 Phase 0 [Opus],
pkg284 Phase 1 [Sonnet 5.5]. Then AK as slots free: pkg294 Phase 1 [Opus],
pkg295 [Opus], pkg284 Phase 2 [Sonnet 5.5], pkg291 #879 [Opus], #921+#773
[Sonnet 5.5]. Every lane gets a Terra review; the lead runs the one CUDA
build and the RTX suite.

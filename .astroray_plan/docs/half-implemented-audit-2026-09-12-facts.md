# Half-implemented package audit — fact sheet (2026-09-12)

Scope: exactly the 17 package specs listed in the task, read from `.astroray_plan/packages/`.
No other files read; no code changed. All `Status:` lines are verbatim prefixes of the
spec's own `**Status:**` line, truncated to 200 chars. "Done / NOT done" counts are the
phases/items as listed in each spec's own Status/Progress sections. Quotes = the last two
entries of each spec's Progress section in file order (for newest-first lists, the top two);
where a spec has no Progress section, the last two dated status statements are quoted and
marked as such. Max 400 chars per quote. No judgment, no recommendations.

| id | title | Status (verbatim, ≤200 chars) | Done (count + names) | NOT done (count + names) | Last dated progress-log entry | Stated blocker / dependency | File path |
|---|---|---|---|---|---|---|---|
| pkg88 | Motion Blur (Cycles-shaped, STBVH-aware) | Phases A+C.0 done (A: PR #284 — but camera motion blur was UNREACHABLE in real Blender until the `convert_scene` ordering fix in PR #525, see the Phase B entry; C.0: PR #437, 2026-06-11 — deformation… | 3 — Phase A (camera, PR #284); Phase B (addon bake, PR #525, renderer-side HW verify pending); Phase C.0 (deformation, PR #437) | 2 — Phase C.1 (per-primitive split; perf-gated, ships only if C.0 >1.5× slower than Cycles); Phase D (wavefront motion; deferred below the Integration Milestone, owner directive 2026-08-03) | 2026-06-10 — C.0 implemented on branch `feat/pkg88-c0-deformation-mb`, PR pending (RTX-verified gates listed). | Depends on pkg55-A.1 (done), pkg72 (done). Phase D deferred by owner directive; C.1 perf-gated. | .astroray_plan/packages/pkg88-motion-blur.md |
| pkg136 | Path guiding (SD-tree core, CPU-first, GPU wavefront leg) | Stage 1A/1B LANDED (PRs #693/#694, merged 2026-09-04/05). The CPU SD-tree structures and path-tracer integration are in `origin/main`. **The ≥2× variance-win acceptance gate is CONCLUDED as a scene-phy… | 2 — Stage 1A (host SDTree build/refine + iteration driver, incl. DTree quadtree landed 2026-09-05); Stage 1B (CPU guided sampling + MIS in `pathTraceSpectral`, #694) | 3 — Stage 0 (`cite-algorithm` note + license decision; checkbox still unchecked); Stage 2A (device side-table + gated `__noinline__` guided draw); Stage 2B (between-iteration build, CPU↔GPU parity, RTX gates) | 2026-09-05 — Stage 1B integration LANDED (#694): full-SDTree + MIS in `pathTraceSpectral`; ≥2× variance gate concluded as a scene-physics ceiling; real discarded-training-samples bug fixed, ~1.3× equal-cost win. | Depends on pkg55 Phase C (Stage 2 GPU leg only; Stage 1 CPU has no such dependency). Composes with pkg131, pkg224. | .astroray_plan/packages/pkg136-svo-wavefront-path-guiding.md |
| pkg241 | Cooperative render cancellation and viewport-response contract | in-progress — Phase 1b code delivered (native + addon cooperative cancellation, PR pending 2026-09-08: bool-returning progress callback honoured by the CPU tile loop and the GPU wavefront host loop, `R… | 7 — Phase 0 budgets/measurements (PR #733); Phase 1a present-first (PR #739); Phase 1b cancellation (PR #748); Phase 2 UI-latency measurement (PR #750); A2 spike (PR #768); P2.2 items 1–5 + scene-switch CUDA-corruption fix (PR #777, RTX-verified); Phase 2 design Rev 2–4 | 3 — P2.3 residual gates (moved to pkg266: cancellation-bounded dispatch, global admission token + F12 pause gate, coalesced dirty-domain commit); acceptance criteria UNRUN (contract behaviors, no-mixed-accumulation, completion-unchanged, visual evidence, ABI review/sign-off); continuous-storm tick-gap p95 and big-scene cancel p99 still over budget | 2026-09-10 — P2.3 residual gates owned by pkg266 (branch `feat/pkg266-viewport-p23-bounded-dispatch`); GPU build + GUI re-measure under the lock in that lane. | Depends on pkg52, pkg81, pkg147, pkg191, pkg192, pkg196, pkg232, pkg236. Residual P2.3 gates reassigned to pkg266. | .astroray_plan/packages/pkg241-render-cancellation-viewport-response.md |
| pkg253 | Principled BSDF advanced inputs | in-progress | 6 — Step 1 (spec); Step 2 (G1 alpha shadow-ray fix, CPU, 5/5 tests); Step 2b (coverage-matrix scanner fix + regeneration); acceptance: G1 + regression sweep, G2/G3/G4 verified already-implemented, matrix regenerated, genuinely-dropped sockets named as non-goals, signature sweep | 2 — GPU verification of the G1 shadow-ray fix (pending the lead's CUDA build; GPU alpha NOT honoured — strict xfail, follow-up PR); Step 3 (G2 Specular Tint — open checkbox, "not needed as a code change") | 2026-09-07 — GPU verification: CPU alpha shadows green (8 passed); GPU alpha NOT honoured (deferred/bucketed shadow stage); `test_alpha0_casts_no_shadow_gpu` strict xfail; G1-GPU follow-up PR. | Depends on pkg229, pkg178. GPU verification blocked on the lead's CUDA build. | .astroray_plan/packages/pkg253-principled-advanced-inputs.md |
| pkg127 | Specular Polynomials for SMS seed finding (deterministic, Newton-free seeds) | Phase 1 LANDED (#685, 2026-09-04) — deterministic single-bounce sphere specular-polynomial seed finding, CPU, both integrators, behind `sms_specular_poly` (default OFF). Sphere-specialized exact deg… | 3 — Phase 0 (mollnn/spoly license recorded: UNLICENSED → paper re-derivation); Phase 1 (single-bounce sphere solver, CPU, flag-gated, #685); research note written | 3 — Phase 2 (two-bounce hidden-variable resultant on the pkg106 chain); Phase 3 (GPU/wavefront mirror); seed-failure-rate SF11 leg (partial [~]: glass-sphere measured, SF11 deferred to Phase 2) | 2026-09-04 — Phase 1 LANDED (#685); seed-failure rate measured on glass-sphere (poly enumerates all branches); SF11 is a two-bounce/triangle case → Phase 2. | Depends on pkg64 (done), pkg106; spec states "No hard blocker". Phase-1 note: "(pending HW gate run at closeout)". | .astroray_plan/packages/pkg127-specular-polynomials-sms.md |
| pkg227 | General Specular Polynomials (any-geometry deterministic caustics) | in-progress — owner-approved 2026-09-04; Phase 2a (#688), 2b-flat (#689), 2b-smooth (#691) landed; 2c deferred | 3 — Phase 2a (analytic-sphere multi-bounce / raindrop rainbow, #688); Phase 2b-flat (single-bounce mesh solver, landed 2026-09-05, #689); Phase 2b-smooth (interpolated shading normals, landed 2026-09-05, #691) | 3 — Phase 2c (triangle-tuple pruning / M-prune; GATED on owner Open Decision #1); Phase 2d (two-bounce mesh; deferred with 2c); Phase 3 (GPU mirror; RE-SCOPED 2026-09-05 to greenfield new wavefront caustic stage, deferred as its own scoped package) | 2026-09-07 — status header normalized to `in-progress` (previously: APPROVED owner 2026-09-04, order 2a → 2b-flat → 2b-smooth; 2c DEFERRED, 2d/3 follow). | Depends on pkg127 (landed #685), pkg106, pkg64; soft-coupled pkg226. Phase 2c gated on owner decision; Phase 3 deferred as its own package. | .astroray_plan/packages/pkg227-general-specular-polynomials.md |
| pkg201 | GPU wavefront settings-honour: flip the pkg200 HONEST-FAIL rows to PASS | Stage 1 done (PR #618, 2026-08-14 — `world_max_bounces` HONEST-FAIL→PASS ratio 5.24 on 5.1/5.2; `use_light_tree` KNOWN-GAP→NEEDS-VISUAL-confirmed honoured; also fixed a latent set_light_sampler cr… | 4 — Stage 1 (exporter fixes, PR #618); Stage 2 (F-alpha `film_transparent` + `filter_width`, PR #623); Stage 3 item A (per-type bounce counters, both backends, 2026-08-29); Stage 3 item E (native caustic toggles, both backends, 2026-08-29) | 6 — Stage 3 item C (`filter_glossy`, PARKED 2026-08-29, disproportionate surface); `transparent_max_bounces` (PARKED — needs lobe LABEL through sample APIs); `volume_bounces` (PARKED — pkg199 cross-ref); F-glass `film_transparent_glass` (reclassified out to a follow-up feature); `pixel_filter_type` row (HONEST-FAIL sub-threshold, σ-mapping filed as pkg203); whole-package closeout gate (verbatim pkg200 driver re-run on 5.1 AND 5.2) still pending | 2026-08-29 — Stage 3 item C (filter_glossy) PARKED: application site needs ~20 edits/backend across glossy materials; filed as a dedicated follow-up package. | Depends on pkg200, pkg176, pkg55. Hard ordering gate: Stage 3 must not start until pkg199 Stage 2 AND pkg198 Stage 2 land/settle (REG-254 shade-kernel register contention). Per-item cuobjdump probe gate; park-with-evidence is a valid outcome. | .astroray_plan/packages/pkg201-gpu-wavefront-settings-honour.md |
| pkg179 | Disney dielectric dead-sample fix, Part 2: diagnose the 3× dead-sample rate, then redistribute the masked energy into the TRANSMISSION lobe | Phase 1 DONE (2026-08-09, branch `pkg179-diag`; research note `.astroray_plan/docs/pkg179-dielectric-transmission-redistribution-research.md`). **Verdict: the 3× dead-sample rate was a MEASUREMENT-METH… | 1 — Phase 1 (diagnosis of the 3× dead-sample-rate discrepancy; verdict: measurement-methodology artifact, not a sampler bug) | 1 — Phase 2 (transmission-lobe energy redistribution) — never built; owner ratified OPTION 2 (2026-08-09): pkg179 CLOSED by diagnosis, no dead-sample fix ships, no engine code changed | 2026-08-09 — Phase 1 DONE; RESOLVED — owner ratified OPTION 2; pkg179 CLOSED by diagnosis (no dead-sample fix, no Phase 2; combined-closure design recorded for pkg178). | Depends on pkg167 Part 1 (landed, PR #562). No open blocker — package closed by owner ratification; Phase 2 was gated on Phase 1's finding, which resolved against building it. | .astroray_plan/packages/pkg179-dielectric-transmission-energy-redistribution.md |
| pkg121 | Chi-squared sampler-validation gates | Phase A done (PR #485, 2026-07-19 — Mitsuba 3 chi² harness ported BSD-3-Clause + `debug_bsdf_*_batch` CPU bindings; Lambertian anchor PASSES p=0.23; Disney spec-lobe failures xfail'd and escalated to… | 1 — Phase A (chi² harness port + batched CPU BSDF bindings + Lambertian anchor pass, PR #485, 2026-07-19) | 1 — Phase B (comprehensive validation campaign + visual HTML report; separate dispatch; first gallery already rendered at `test_results/chi2_visuals_2026-07/`) | 2026-07-19 — Phase A done (PR #485): harness ported, Lambertian anchor PASSES p=0.23; Disney spec-lobe failures xfail'd and escalated to pkg123; finding doc rewritten post-merge b7895ac. | Depends on: TBD (per spec). Disney spec-lobe chi² failures escalated to pkg123. | .astroray_plan/packages/pkg121-chi2-sampler-gates.md |
| pkg119 | Blender integration parity program (coverage matrix + differential harness + graceful degradation) | Phase A done (PR #487). **Phase B — differential harness — landed + HARDWARE-VALIDATED 2026-08-08** (PR #550): on RTX 5070 Ti + Blender 5.1 the sweep runs end-to-end (res64/spp16, 39 features) → **26… | 1 — Phase A (coverage matrix generator + regeneration target + checked-in artifacts, PR #487) | 2 — Phase B (partial [~]: harness authored + hardware-validated 2026-08-08, PR #550; 26 pass / 12 fail / 1 skip, triage 10 INTENTIONAL-DIVERGENCE + 2 TRANSLATION-BUG); Phase C (partial [~]: PR #564 pending review + on-hardware smoke; "zero DROPPED-SILENT in matrix" criterion a flagged follow-up) | 2026-08-08 — Phase C PR #564 (graceful-degradation policy, `blender_addon/degradation.py`) pending review + on-hardware smoke; Phase B hardware-validated same date (PR #550). | Depends on: none hard. RE-SCOPED INTO THE INTEGRATION MILESTONE (owner directive 2026-08-03): Phase B dispatches once pkg175's dev loop exists; Phase C lands with/behind pkg176 Stage 3. | .astroray_plan/packages/pkg119-blender-parity-program.md |
| pkg126 | Mesh-emitter unification (pkg89 Phase C: one sampling interface for dedicated + emissive-geometry lights) | still-open — no code landed (only the spec-filing PR #493); the L-effort re-architecture was unblocked but never queued or implemented. **UNBLOCKED 2026-07-24** (the pkg122 dependency is satisfied: PR #… | 0 — none (Progress items A–E all unchecked; only the spec-filing PR #493) | 5 — A (mesh-emitter `Light` wrapper); B (DiffuseLight/Emissive as thin shims); C (retire/minimize the seven `Hittable` light virtuals); D (unify `LightList::sample` + light tree + five integrator NEE sites); E (GPU mesh-emitter mirror + parity) | none in the Progress section; latest status note dated 2026-07-24 — UNBLOCKED (pkg122 satisfied, PR #500 merged 2026-07-21) but NOT queued for the overnight run. | Depended on pkg122 (satisfied 2026-07-24). Explicitly not queued: L-effort cross-cutting re-architecture (five integrators + `Hittable` virtuals + GPU mirror) with a no-visible-change outcome — needs a dedicated day arc. | .astroray_plan/packages/pkg126-mesh-emitter-unification.md |
| pkg130 | Light groups + emission-mechanism decomposition (LuxCore radiance-group model) | still-open — never implemented; no light-group/emission-decomposition code in the repo, only the spec-filing PR #492. | 0 — none (Progress items A–C all unchecked) | 3 — A (emitter `group_id` + scene/exporter/addon plumbing); B (per-group framebuffers CPU + wavefront, Σ-groups identity); C (multi-layer EXR + post rescale gate; 4-mechanism decomposition on a BH scene) | none — no dated progress entries. | Depends on: none hard. Composes after pkg55 Phase C; must land before pkg134 (pkg134 consumes its group ids). | .astroray_plan/packages/pkg130-light-groups-emission-decomposition.md |
| pkg133 | SRF spectral sensors (Mitsuba `specfilm` — detector QE × filter curves) | still-open — never implemented; no SRF spectral-sensor/specfilm code in the repo, only the spec-filing PR #492. | 0 — none (Progress items A–C all unchecked) | 3 — A (SRF channel representation + combined-distribution build); B (hero-aware wavelength importance sampling, CPU + wavefront); C (multichannel EXR + narrow-band variance-reduction gate) | none — no dated progress entries. | Pillar-4-adjacent: activates when the owner lifts the Pillar-4 pause OR ships standalone as a spectral-camera feature; sequence after pkg51 resumes, or fold in as pkg51-B. | .astroray_plan/packages/pkg133-srf-spectral-sensors.md |
| pkg134 | Light Path Expressions (OSL `liboslexec` LPE automata port) | still-open — never implemented; no LPE/light-path-expression automata in the repo, only the spec-filing PR #492. | 0 — none (Progress items A–C all unchecked) | 3 — A (host LPE compiler port: parse/automata/accum, OSL test cases); B (wavefront `uint16` DFA-state field + per-event transitions + AOV routing); C (emission-mechanism labels + photon-ring winding-number counter + presets) | none — no dated progress entries. | Depends on pkg130 (land order pkg130 → pkg134). Composes after pkg55 Phase C. | .astroray_plan/packages/pkg134-light-path-expressions.md |
| pkg242 | Procedural transformed-p and bake/cache-domain parity | in-progress — Phase 1 in review (PR #737, 2026-09-07; CPU analytic oracles green, GPU parity pending lead build); Phase 2 real-Blender parity still open | 2 — Phase 0 baseline + UV-less fallback contract (PR #726, 2026-09-07); Phase 1 transformed-p + bake/cache contract (LANDED on main in commit `fe1c95c`, GPU-verified 08:45; PR #737 carries the bake-dedup key fix) | 3 — Phase 2 (real-Blender parity) still open; GPU parity gate (gpu-marked twins pending the lead's RTX 5070 Ti CUDA build); pre-review follow-ups from PR #737 (scale-relative singular-Mapping check; `valueOffset` 3-D perturbation for p-reading procedurals) | 2026-09-07 — Phase 1 transformed-p contract LANDED on main in commit `fe1c95c` (lead error: swept into a docs commit while the PR #737 cherry-pick was applied for GPU verification; 16 contract tests incl. 3 GPU twins, 129 procedural regressions, cpp-abi-guard PASS). | Depends on pkg115, pkg190, pkg219, pkg230b. GPU verification pending the lead's CUDA build. | .astroray_plan/packages/pkg242-procedural-mapping-bake-parity.md |
| pkg245 | Normal/bump image coordinate provenance | open — detailed architect review required before implementation | 0 — none (Progress section: "(none yet)") | 3 — Phase 0 (baseline + audit; cite-algorithm before any numerical change); Phase 1 (provenance routing through `load_blender_image` in BOTH Principled paths); Phase 2 (matched CPU/GPU/Cycles verification) — all unstarted | none — Progress section says "(none yet)". | Depends on pkg219. Stated gate: "detailed architect review required before implementation"; all implementation and visual gates UNRUN. | .astroray_plan/packages/pkg245-normal-bump-coordinate-provenance.md |
| pkg254 | Spectral path_tracer feature parity (the deferred bindings xfails) | open | 1 — filing + removal of four XPASS markers (per-closure bounce limits, caustics flags; PR #720, 2026-09-07) | 6 — six xfails remain in `tests/test_python_bindings.py`: transparent alpha (2 tests), filter_glossy, cryptomatte/render passes, HDR/linear output pass, gamma toggle | 2026-09-07 — filed; four XPASS markers removed in PR #720; six remain. | Depends on pkg14, pkg87, pkg195. Prerequisite: pkg253 G1 decides whether transparent alpha is a closure or a shadow-only feature. | .astroray_plan/packages/pkg254-spectral-path-tracer-feature-parity.md |

---

## Quotes

### pkg88
1. "- **A done** (PR #284 + pkg103b addon wiring PR #372)."
2. "- **C.0 implemented** (branch `feat/pkg88-c0-deformation-mb`, 2026-06-10 — PR
  pending): per-triangle motion vertex buffer (`add_triangles_bulk_motion`
  bulk binding, K=2 pre/post-shutter steps, linear blend per Cycles
  `motion_triangle.h` Apache-2.0), time-aware `Triangle::hit` +
  `gpu_triangle_hit_motion`, union-AABB `boundingBox`, `GRay::time` +
  end-to-end time threading (primary/bounce/shadow rays, BOTH kernels"

### pkg136
1. "- [ ] Stage 2A — device directional side-table + gated `__noinline__` guided draw;
      fleet-kernel byte-identical probe."
2. "- [ ] Stage 2B — between-iteration build (copy-back first), CPU↔GPU parity, RTX
      variance + perf gates."

### pkg241
1. "- [~] 2026-09-10 — **P2.3 residual gates owned by pkg266** (branch
  `feat/pkg266-viewport-p23-bounded-dispatch`): the three §13 items land there —
  (1) cancellation-bounded GPU dispatch (`sub_pass_budget`: the native driver syncs
  + polls the cancel hook every N wavefront passes so an in-flight chunk stops
  within one bounded unit, numerically inert vs the async path), (2) one
  process-global admission token + F12 pause gate"
2. "- [x] 2026-09-09 — **P2.2 MERGED (#777).** Design §12 items 1–5 delivered + Codex Terra review 4 (BLOCK → all items fixed, design §13) + the scene-switch CUDA-corruption root cause and fix (§13a: per-worker token never serialised across sessions; `stop_all_viewport_sessions()` on `load_pre`/`atexit`; RTX-verified 5 switches, 0 CUDA errors). Present wiring PASS both scenes;"

### pkg253
1. "- [ ] 2026-09-07 — GPU verification (RTX 5070 Ti, lead): CPU alpha shadows green (8 passed); GPU alpha NOT honoured — wavefront NEE occlusion is resolved in the deferred/bucketed shadow stage, not `stage_light_sample.cu::traceShadowRay` (alpha 1.0/0.5/0.0 occluder all 0.2467 vs 0.4736 unoccluded). `test_alpha0_casts_no_shadow_gpu` is a strict xfail; G1-GPU is a follow-up PR"
2. "- [x] Step 1 — spec written, grounded in reading pkg178's status, the
  addon's native-param plumbing, and both engine backends first."

### pkg127
1. "- [~] Seed-failure-rate before/after measured on glass-sphere (poly enumerates all
      branches; instrumented via sms_attempts/sms_converged stats). SF11 is a
      two-bounce/triangle case → Phase 2."
2. "- [x] Research note `pkg127-specular-polynomials-research.md` written (paper +
      DOI/arXiv, license decision, the exact math reproduced + §7 design)."

### pkg227
1. "- [ ] Phase 2d — two-bounce mesh, supersede `runMeshSMSAttempt`."
2. "- [ ] Phase 3 — GPU / wavefront mirror; caustic parity RTX-verified.
      **RE-SCOPED 2026-09-05 — greenfield, not a mirror.** The GPU wavefront path
      has NO camera-side SMS/caustic stage (stages: intersect / shade_lambertian /
      light_sample / RR / restir); `src/gpu/pkg64_sms_probe.cu` landed only the
      caustic-caster flag round-trip and EXPLICITLY deferred the device SMS solve."

### pkg201
(no Progress section; last two dated entries are the Stage 3 item sections)
1. "### Stage 3 item E — DONE 2026-08-29 (native caustic toggles, BOTH backends). Closes Findings **E** (`caustics_reflective` / `caustics_refractive`). Cycles suppresses a specular/refractive closure once the path carries `PATH_RAY_DIFFUSE_ANCESTOR` and the matching toggle is off, so a diffuse→specular→light caustic path never forms. Astroray mirrors this with a **sticky `hadDiffuseAncestor` flag** (CPU local in `pathTraceSpectral`; GPU `had_diffuse_ancestor` SoA, zeroed at `initPathSlot`), set on a genuinely diffuse bounce"
2. "### Stage 3 item C — PARKED 2026-08-29 (filter_glossy — disproportionate surface). `filter_glossy` (`blur_glossy`) widens a path's glossy microfacet alpha by `blur_roughness = sqrt(1 − filter_glossy·min_ray_pdf)·0.5` (Cycles `surface_shader.h`; research note `.astroray_plan/docs/pkg201-item-c-filter-glossy-research.md`). The per-ray `min_ray_pdf` accumulator + a `HitRecord::glossyAlphaFloor`/GHitRecord threading is cheap and clean. The **blocker is the application site:**"

### pkg179
(no Progress section; last two dated status statements quoted)
1. "**RESOLVED — owner ratified OPTION 2 (2026-08-09). pkg179 CLOSED by diagnosis: no dead-sample fix ships, no Phase 2 built; the fallback's energy-correct transmission reroute stays; the chi² concern is the documented ires=4 quadrature artifact; the Cycles combined-closure design is recorded for pkg178's Principled dielectric to adopt when it gets there. No engine code changed.**"
2. "**Status:** Phase 1 DONE (2026-08-09, branch `pkg179-diag`; research note `.astroray_plan/docs/pkg179-dielectric-transmission-redistribution-research.md`). **Verdict: the 3× dead-sample rate was a MEASUREMENT-METHODOLOGY / definition artifact — NOT a sampler bug, NOT new physics.**"

### pkg121
(no Progress section; the two Status sentences quoted)
1. "Phase A done (PR #485, 2026-07-19 — Mitsuba 3 chi² harness ported BSD-3-Clause + `debug_bsdf_*_batch` CPU bindings; Lambertian anchor PASSES p=0.23; Disney spec-lobe failures xfail'd and escalated to pkg123; finding doc rewritten post-merge b7895ac)."
2. "Phase B (validation campaign + visual gallery) open — first gallery already rendered at `test_results/chi2_visuals_2026-07/` (3 figures incl. the pkg123 residual-map)."

### pkg119
1. "- [~] **Phase B — per-feature + composite differential harness; triage report.** Harness authored under `benchmarks/blender_parity/` (driver `harness.py`, in-Blender `render_leg.py`, `scene_library.py` scene builders, pure `triage.py`), reusing the pkg104 reference-bank metrics (`compute_ssim`, `compute_delta_e_2000`) and pkg175's dev-loop substrate — no new metric stack, no new render driver. Drives off Phase A's 36 SUPPORTED/APPROXIMATED cells + 3 composites;"
2. "- [~] **Phase C — graceful-degradation policy + per-render UI/log report.** (PR #564, 2026-08-08 — pending review + on-hardware smoke). New `blender_addon/degradation.py` (`DegradationReport`, Route-2 pure collector) unifies the three previously-parallel warning sources into ONE per-render report: shader-node fallbacks (`_warn_shader_fallback`, pkg115) → APPROXIMATED; native world/light/camera drops (pkg176 Stage 3"

### pkg126
1. "- [ ] D — unify `LightList::sample` + light tree + five integrator NEE sites."
2. "- [ ] E — GPU mesh-emitter mirror; GPU==CPU parity on a mixed scene."

### pkg130
1. "- [ ] B — per-group framebuffers (CPU + wavefront); Σ-groups identity verified."
2. "- [ ] C — multi-layer EXR + post rescale gate; 4-mechanism decomposition on a BH scene."

### pkg133
1. "- [ ] B — hero-aware wavelength importance sampling (CPU + wavefront)."
2. "- [ ] C — multichannel EXR + narrow-band variance-reduction gate."

### pkg134
1. "- [ ] B — wavefront `uint16` DFA-state field + per-event transitions + AOV routing."
2. "- [ ] C — emission-mechanism labels + photon-ring winding-number counter + presets."

### pkg242
1. "- **2026-09-07 -- Phase 0 baseline + UV-less fallback contract (PR #726).** Reproduced
  and root-caused the \"UV-less procedural checker disappears on GPU\" bug (the
  2026-09-06 baseline: CPU luminance std 0.4182 vs GPU 0.0330). Root cause:
  `scene_upload.cu` set `GTriangle.hasUV` only when `tri->hasUVLayers()`, so a
  UV-less textured material uploaded no UVs and the device base-colour fetch"
2. "- **2026-09-07 -- Phase 1 transformed-p + bake/cache contract (PR pending).**
  Implemented the single transformed-coordinate contract. CPU: the HitRecord
  overloads of `Texture::value/valueOffset/sampleSpectral`
  (`include/advanced_features.h`) now feed the procedural evaluator the
  Mapping-transformed point `mp = M*p` (previously only the 2-D image coord was"

### pkg245
Progress section contains only: "- (none yet)" — no progress-log bullets exist.

### pkg254
Only one progress-log bullet exists:
1. "- [x] 2026-09-07 — filed; four XPASS markers removed in PR #720; six remain."

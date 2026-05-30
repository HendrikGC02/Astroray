# pkg104 — Visual Reference Bank + Perceptual Gates

**Pillar:** 5 (Production polish — but with first-order effect on all of Pillars 2/3/4)
**Track:** A (the harness + first 2 scenes); Track D once the pattern is established (adding more scenes is mechanical)
**Status:** open — scene set + parameterization **DECIDED** 2026-05-30 (owner delegated the design; consensus in `.astroray_plan/docs/visual-reference-bank-design-2026-05-30.md`). Implementation pending (re-author/re-render scenes on RTX with visual bless). Blocker for the cross-engine scene: the FOV-mismatch bug (see the design doc).
**Estimated effort:** 2 weeks (~50 h) for the harness + first 4-6 pinned scenes; ongoing thereafter
**Depends on:** pkg71 (Cycles parity framework, already shipped — extends it, does not replace it)

---

## Goal

**Before:** The test suite proves architecture works (no NaN, deterministic, plugin contracts) but does not prove *the image looks right*. ~5–7% of ~1000 tests do visual-fidelity comparison; the rest are numeric contracts. There is no canonical reference-image set for Astroray's unique pillars (spectral dispersion, GR, astrophysics). When a render comes out, the owner is the visual oracle — manually inspecting 50+ PNGs per round at 1–2 hours each. Round-by-round velocity (12 PRs/night overnight in Round 14) now exceeds the rate the owner can visually verify, which means visual regressions can ship to main behind green CI. Specifically:

- pkg29 "dispersive prism" passes via `red_blue_centroid_separation` proxy but the rendered PNG shows no visible rainbow.
- pkg64-gpu Phase 3 prism receiver-energy passes 1.17× but PSNR/SSIM gates are deferred and there is no perceptual color-fidelity gate.
- pkg99 ADAF "should produce visible glow" — visual gate explicitly deferred to "owner empirical RTX tuning, a separate follow-up."
- pkg61 GPU shade-smooth SSIM gate marked xfail strict=True at 0.946 vs 0.97; no replacement gate exists.
- Cycles parity (pkg71) gates against Cycles but cannot test scenes Cycles itself cannot render — i.e., precisely Astroray's competitive niche (spectral, GR, astrophysics).

**After:** A reproducible reference bank of N ≥ 6 pinned scenes (chosen by the owner — §"Open question to owner" below) covering each pillar's vision-defining capability. Each scene has: (1) a scene-construction script (or .blend handle), (2) a pinned reference render produced by a known-good source (Cycles, Mitsuba, PBRT-v4, or an authoritative own-render fingerprinted to a specific commit + hardware), (3) a typed gate (`SSIM`, `ΔE2000`, `phenomenon-presence`, or composite) with a documented threshold. A `pytest`-collectable harness runs the bank, emits a one-page Markdown summary with image diffs, and writes a pass/fail row per scene per gate to a CSV history. The owner stops being the visual oracle for routine PRs and is only paged on a flagged regression. Every PR that touches an integrator, BSDF, light path, or render-side code now has a *visible* gate, not just a numeric one.

---

## Context

Why now, why this size, and why not just "extend pkg71":

1. **Velocity outpaces verification.** Round 14 closed 12 PRs overnight; owner cannot eyeball every output. Without an automated visual gate, the orchestrator is shipping faster than the project can prove the renders still look right. This is the single biggest reason owner reports feeling "lost on what's actually in main."

2. **pkg71 is a ceiling test, not a vision test.** Cycles cannot render dispersion-correct prism caustics (it uses MNEE for shadow caustics; SMS is not in stock Cycles), cannot render Kerr geodesics, cannot render ADAF emission. Astroray's *unique selling proposition* has no automated visual gate today because the only image-comparison gate compares against an engine that doesn't do these things.

3. **Numeric proxies are insufficient.** `red_blue_centroid_separation` can pass on a scene with no visible rainbow (any per-pixel chromatic shift will move the centroid). SSIM windowed on independent MC streams is architecturally unreachable at modest spp (project memory `ssim-wrong-gate-for-independent-rng`). A perceptual color metric (ΔE2000) is needed for color fidelity and a phenomenon-presence metric is needed for caustics/dispersion/glow.

4. **Failure mode is silent.** Today, a PR can drop a rainbow caustic to zero amplitude, pass all 1000+ tests, merge, and only get noticed at the next manual visual-review pass. Closing this loop is the highest-leverage thing in the project right now.

5. **This is not over-engineering.** PBRT-v4 ships `v4-scenes` with pinned renders. Cycles has the test scenes in `intern/cycles/test/integration/` + opendata.blender.org reference images. Mitsuba 3 has `mitsuba3-test-scenes`. Astroray being without one is the outlier. Following standard practice, not inventing.

---

## Reference Implementations

All cited per CLAUDE.md §6. Algorithm + harness sources, license-checked.

| Source | License | What we mirror | Where it goes |
|--------|---------|----------------|---------------|
| PBRT-v4 `v4-scenes` (`mmp/pbrt-v4-scenes`) | Apache-2.0 | scene-folder convention, `.exr` reference format, multi-resolution mip pattern | `benchmarks/reference-bank/scenes/<scene>/` layout |
| Mitsuba 3 `mitsuba3-test-scenes` | BSD-3-Clause | metric-tolerance schema (per-scene `tolerance.json`), CLI runner shape | `benchmarks/reference-bank/runner.py` shape; per-scene `gates.toml` |
| Blender Cycles `intern/cycles/test/integration/` | Apache-2.0 | "warm-up frame then N timed frames" pattern (already mirrored by pkg71); we reuse the same Cycles-CPU EXR generation path for the Cornell category | pkg71's existing runner extended, not rewritten |
| Sharma, Wu, Dalal 2005 "The CIEDE2000 Color-Difference Formula: Implementation Notes, Supplementary Test Data, and Mathematical Observations" DOI [10.1002/col.20070] | public-domain math | ΔE2000 formula with all corrections | `benchmarks/reference-bank/metrics/delta_e_2000.py` |
| Goyal et al. 2017 "Robust Image Hashing using Perceptual Hash" | algorithm in literature | pHash implementation (DCT-based 64-bit hash, Hamming distance gate) | `metrics/phash.py` (already a stdlib via `imagehash`) |
| OpenColorIO 2.x ACES 1.3 config | BSD-3-Clause | linear→display transform we apply before ΔE2000 (color difference must be computed in a perceptual space, not linear scene-referred) | `metrics/color_pipeline.py` |
| pkg71 (this repo) | MIT (ours) | SSIM-on-99.9-percentile-clipped EXR pattern, CSV row schema, per-engine sidecar JSON | extended, not rewritten |
| `pkg29a-scoped-caustic-validation.md` § "centroid metric" (this repo) | MIT | the existing centroid-separation gate — we KEEP this but add visible-rainbow-presence on top | new gate `metrics/hue_spread.py` |

**Algorithms (no inventions):**
- **SSIM** — Wang et al. 2004, already in pkg71.
- **CIEDE2000** — Sharma 2005 reference implementation; we use the public-domain Python port from the `colour-science/colour` library (BSD-3-Clause) as the source of truth, mirrored to a single file with license header.
- **pHash** — `imagehash.phash` is the documented Goyal 2017 implementation; permissive license.
- **Hue-spread** — circular variance of hue values within a thresholded bright region; this is an undergraduate-level statistic, not novel research, but cited from Hanbury 2003 "Circular Statistics Applied to Colour Images" for completeness.

**Multimodal AI review hook (optional, deferred — see §Non-goals):**
- Anthropic Claude multimodal API. *Not a gate.* Only used to emit a one-line qualitative description of the diff for owner-facing summary. Excluded from CI default; behind `--ai-review` flag.

---

## Prerequisites

- [x] pkg71 (Cycles parity framework) is shipped — `benchmarks/cycles-parity/` exists with `scripts/run_parity.py`, `refs/MANIFEST.sha256`, `scenes/cornell/`.
- [x] `tests/reference/` has Schwarzschild + Kerr baselines (limited; will be promoted to the new bank).
- [x] Owner has confirmed visual fidelity is top priority (CLAUDE.md ROADMAP §"Visual fidelity vs performance").
- [ ] Owner has selected the initial scene set per §"Open question to owner".
- [ ] Decision on reference-EXR storage: Git LFS in this repo vs sidecar bucket (defaults to Git LFS — see §Key design decisions).

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `benchmarks/reference-bank/README.md` | Inventory of pinned scenes + how to regenerate references |
| `benchmarks/reference-bank/runner.py` | CLI: `python -m benchmarks.reference_bank.runner [--scenes ...] [--gates ssim,deltae,phash,hue,custom]` |
| `benchmarks/reference-bank/metrics/__init__.py` | Public metric API: `compute_ssim`, `compute_delta_e_2000`, `compute_phash_distance`, `compute_hue_spread`, `compute_bright_coverage`, `compute_dark_disk_fraction` |
| `benchmarks/reference-bank/metrics/delta_e_2000.py` | CIEDE2000 (Sharma 2005); ported from `colour-science/colour` BSD-3-Clause, single file with attribution |
| `benchmarks/reference-bank/metrics/phash.py` | thin wrapper around `imagehash.phash`; gate is Hamming distance ≤ N (default N=8 of 64 bits) |
| `benchmarks/reference-bank/metrics/hue_spread.py` | "rainbow present" gate: thresholded bright region → circular variance of hue → must be > θ for chromatic scenes |
| `benchmarks/reference-bank/metrics/bright_coverage.py` | "caustic present" gate: fraction of pixels in defined ROI with luminance > L_min |
| `benchmarks/reference-bank/metrics/dark_disk.py` | "BH shadow present" gate: fraction of pixels in defined ROI with luminance < L_max |
| `benchmarks/reference-bank/metrics/color_pipeline.py` | scene-referred → display-referred (ACES 1.3) for ΔE2000 input |
| `benchmarks/reference-bank/scenes/<scene-name>/scene.py` | Python scene-construction script per scene |
| `benchmarks/reference-bank/scenes/<scene-name>/gates.toml` | `[[gate]]` entries: type, threshold, ROI, rationale |
| `benchmarks/reference-bank/scenes/<scene-name>/reference.exr.url` | If reference is too large for LFS, the canonical fetch URL + SHA-256 |
| `benchmarks/reference-bank/scenes/<scene-name>/notes.md` | What the scene is *supposed* to look like (the vision); used as input to optional AI-review path |
| `benchmarks/reference-bank/refs/MANIFEST.sha256` | extends pkg71's manifest; per-scene reference checksums |
| `benchmarks/reference-bank/refs/<scene>-<spp>.exr` | Git LFS (default) OR sidecar bucket; per §Key design decisions |
| `tests/test_reference_bank_smoke.py` | pytest collects the runner against a tiny subset (Cornell @ 16 spp) so every CI run sanity-checks the harness itself |

### Files to modify

| File | What changes |
|---|---|
| `benchmarks/cycles-parity/README.md` | Add header section "see also: `../reference-bank/` for vision-driven scenes (Cycles cannot render Astroray's unique pillars)" |
| `scripts/run_parity.py` | No change in behavior; optionally accept `--include-vision-bank` to also dispatch the new runner |
| `.github/workflows/<ci-yaml>` | Add a new job: `reference-bank-smoke` runs the Cornell-only subset on every PR; `reference-bank-full` runs nightly on the self-hosted RTX runner |
| `.astroray_plan/docs/STATUS.md` | Round closeout note when this lands |

### Key design decisions

**D1. Reference storage: Git LFS, not external bucket.**
- Rationale: Solo developer; external bucket adds operational burden (credentials, CDN, attribution-rot). LFS handles up to ~1–2 GB total comfortably. If the bank exceeds ~5 GB, revisit. CC-BY-licensed scenes (e.g., pkg71's Junkshop, BMW27) remain user-downloaded per pkg71's existing policy, but the *reference renders* go in LFS.
- Counter-option considered: HuggingFace dataset hosting (free, versioned, CC0-compatible). Defer unless LFS quota becomes an issue.

**D2. Gates are typed, not single-metric.**
- Every scene declares one or more gates in `gates.toml`. A scene may have, e.g.: `[SSIM ≥ 0.92 on full image]` + `[ΔE2000 ≤ 3.0 on ROI 'rainbow_band']` + `[hue_spread ≥ 0.6 on ROI 'rainbow_band']`. Failure of any gate flags the scene; all gates must pass for the scene to pass.
- Reason: SSIM alone cannot catch a missing rainbow (a flat gray image can have decent windowed SSIM against a noisy reference); ΔE2000 alone cannot detect MC-noise dominance; phenomenon-presence catches "did the iconic feature actually appear."

**D3. Reference renders are AUTHORED, not just captured. Default = owner-blessed Astroray.**
- A reference render is the *target*, not the *current Astroray output*. The default source for every category is **an Astroray render at a known-good commit + hardware, blessed by owner as "this is what I want it to look like," promoted via explicit `bless-reference` workflow.** That makes the bank's primary job *regression-catching*, which is exactly what the owner asked for ("tests don't capture the difference between the state the project is in vs what I envision").
- Optional cross-validation against PBRT-v4 (spectral prism, SMS sphere) or Mitsuba 3 is supported per-scene but is NOT required and is NOT a gate — it's an external sanity floor the owner can invoke when they want to spot-check that the blessed image is correct, not just stable.
- This is critical: the bank encodes *the owner's vision*, not just current implementation state. Promoting a current render to reference is a deliberate owner-blessed act, not automatic.
- Cycles is explicitly NOT the reference source. Astroray-unique pillars (GR, ADAF, SMS chromatic caustic) can't be Cycles-rendered, and the Cycles benchmark scenes' Blender 5.1 forward-compat issues are pkg71's problem, not pkg104's.

**D4. Three running modes:**
- `smoke` — Cornell + one fast spectral scene; ~30 s on RTX, runs on every PR.
- `full` — every scene at full spp; ~10–30 min on RTX, runs nightly on self-hosted runner.
- `manual` — `--scenes <name>` for owner-driven debugging.

**D5. Failure output is human-debuggable, not just pass/fail.**
- On failure, the harness writes to `benchmarks/reference-bank/results/<date>-<sha>/<scene>/`:
  - `actual.png` (the new render)
  - `reference.png` (the pinned target)
  - `diff.png` (per-pixel absolute difference, gamma-corrected)
  - `diff_heatmap.png` (ΔE2000 heatmap if ΔE gate failed; bright/dark region overlay if presence gate failed)
  - `report.md` (one-page: per-gate pass/fail with measured value, suggested next step)
- This is the artifact the orchestrator/architect/owner reads when triaging a regression.

**D6. AI-multimodal review is OPT-IN, not a gate.**
- A `--ai-review` flag invokes Claude multimodal with `(reference.png, actual.png, notes.md)` and emits a one-paragraph qualitative comment to `report.md`. *Never blocks merge.* Useful for "the gate passed but the image is subtly weird" — pre-flag for owner review.
- Cost-controlled: only on full nightly runs, and only on scenes where ≥1 gate has measured value within 25% of its threshold (the "yellow" band).

**D7. Existing assets are PROMOTED, not duplicated.**
- `tests/reference/schwarzschild_baseline_256.png` → promoted to `benchmarks/reference-bank/scenes/gr-schwarzschild/reference.png` with formal gate.
- `tests/reference/kerr/` → promoted to `benchmarks/reference-bank/scenes/gr-kerr-analytic/`.
- `tests/reference/pkg67_flat_baseline_256.png` → promoted to `benchmarks/reference-bank/scenes/regression-flat-space/`.
- Existing test files that referenced these are NOT broken; they continue to work via a thin shim until they can be cleaned up in a follow-up.

---

## Open question to owner — RESOLVED 2026-05-30

> The owner delegated the scene-set/parameterization design to Claude and gave
> per-render feedback. The consensus design + the captured feedback + the
> FOV-mismatch-bug analysis are in
> **`.astroray_plan/docs/visual-reference-bank-design-2026-05-30.md`**. The Q1/Q2
> below are retained for history; the design doc is authoritative.

## Open question to owner (HISTORICAL — superseded by the design doc above)

The harness, metrics, runner, CSV history, and CI plumbing can be built without knowing which scenes go in. But the **scene set** is the spec's crown jewel and must reflect *the owner's vision of what Astroray should look like*, not my best guess.

Two questions for the owner before I continue:

### Q1: Scene categories — confirm or amend

I propose 6 categories. For each, the owner picks how many scenes (0–3) to pin initially and may add/drop categories.

| # | Category | Why it's distinct | Suggested initial count |
|---|----------|-------------------|--------------------------|
| A | **Light-transport sanity** | Cornell-equivalent; the no-regression floor for the path tracer itself | 1 |
| B | **Spectral dispersion** | The Pink-Floyd-cover scene: collimated light → BK7 prism → spectrum cast on white screen. This is *the* scene the dispersion work exists to enable. | 1–2 (BK7 + maybe SF11 for stronger dispersion) |
| C | **SMS caustic** | Refractive (sphere on receiver) + reflective (concave mirror); pkg29a + pkg64 acceptance scenes promoted | 2 |
| D | **Material zoo** | Disney roughness/metallic sweep; already exists as `test_disney_brdf_grid.png` (322 KB renders weekly) | 1 |
| E | **GR geometry** | Schwarzschild shadow + Kerr (a/M = 0.94 ergosphere) at canonical view | 2 |
| F | **GR + emission** | ADAF Sgr A* (visible glow), synchrotron jet (M87-like bipolar), maybe slim-disk Novikov-Thorne | 2 |

**Initial bank if all defaults accepted:** 9 scenes (1+1+2+1+2+2). Estimated harness + first-9-scenes build-out: 2 weeks.

**All scenes are Python-constructed via the astroray API** — pkg104 has no dependency on Blender Foundation benchmark `.blend` files (Classroom, Junkshop, BMW27 etc., which forward-compat poorly into Blender 5.1 per owner 2026-05-27). The Cycles-parity category is intentionally NOT in this bank: pkg71 owns that fight, and pkg71's Classroom Gap 2 (non-Principled shader-graph walk for 40/42 materials) is a separate workstream. pkg104 is purely Astroray-internal: hand-built scenes + perceptual gates against owner-blessed Astroray renders.

### Q2: Per-category specifics — confirm or amend

For each category the owner ends up keeping, I need the answers below before writing scene scripts. None of these answers are blocking *the harness* — they're blocking *Scene set §below* only.

**B — Spectral dispersion:**
- B1. **Glass:** BK7 only, or BK7 + SF11 (high Abbe vs low Abbe — visibly different spread)?
- B2. **Light source:** Tight collimated spot (like the prism test you cared about), or D65 area light (like the canonical pkg29 test)?
- B3. **Reference source:** owner-blessed Astroray (default — bless once per-IOR on a known-good commit) — OR optionally a PBRT-v4 cross-check on the prism scene as a one-time external sanity floor? PBRT-v4 cross-check is a per-scene opt-in, not a recurring gate.

**C — SMS caustic:**
- C1. Refractive only (BK7 sphere over white floor — pkg64 acceptance) or both refractive + reflective (concave silver mirror)?
- C2. **Light:** Sun-like (small-solid-angle, sharp caustic) or area-emitter (softer caustic)?

**E — GR geometry:**
- E1. **Schwarzschild:** Use the existing 256² baseline (`tests/reference/schwarzschild_baseline_256.png`) as-is, or re-render at 1024² so the shadow edge is sharp?
- E2. **Kerr:** Spin parameter (suggest `a/M = 0.94`, near-maximal; or `a/M = 0.998` astrophysical limit; or owner-preferred)?
- E3. Camera: face-on accretion-disk view (Sgr A* EHT-like), or edge-on (M87-like), or both?

**F — GR + emission:**
- F1. **ADAF (Sgr A*-like):** Use pkg44's calibrated profile at `intensity_scale=1e30` (visible glow per spec but pkg99 visual gate was "deferred — owner empirical RTX tuning") — does owner want to bless an `intensity_scale` here, or wait for pkg99 follow-up?
- F2. **Synchrotron jet:** M87-like bipolar (already in pkg42 spec), or generic test geometry?
- F3. Resolution: pkg99 was concerned about RTX walltime — 512² nightly, 256² PR-gate?

Once the owner answers Q1+Q2, the remaining sections below get filled in concretely (currently stubbed) and implementation can begin.

---

## Scene set — Phase 2a (owner-approved 2026-05-27)

8 scenes. Owner directive: foundation first (B/C/D/E), astrophysics low priority for now.

| Scene ID | Category | What it shows | Reference source | Gate notes |
|----------|----------|---------------|-------------------|------------|
| `cornell-mini` | A | Cornell box, harness self-test | Owner-blessed Astroray (already captured) | SSIM ≥0.85, ΔE2000 ≤8, pHash ≤16 |
| `prism-bk7-collimated` | B | Visible spectrum on receiver; BK7 (Abbe 64) | Owner-blessed Astroray | SSIM + ΔE2000 in `rainbow_band` ROI + `hue_spread ≥ 0.5` |
| `prism-sf11-collimated` | B | Same setup, SF11 (Abbe 25) — visibly wider spread | Owner-blessed Astroray | Same metric set + `hue_spread ≥ 0.55` (wider expected) |
| `sms-refractive-glass-sphere` | C | BK7 sphere over white receiver, area emitter | Owner-blessed Astroray | SSIM + `bright_coverage` in caustic ROI |
| `sms-reflective-concave-mirror` | C | Concave silver mirror caustic on backdrop, area emitter | Owner-blessed Astroray | SSIM + `bright_coverage` in caustic ROI |
| `gr-schwarzschild` | E | Schwarzschild shadow + photon ring (256², promoted) | Existing `tests/reference/schwarzschild_baseline_256.png` | SSIM + `dark_disk ≥ 0.04` |
| `gr-kerr-94-faceon` | E | Kerr a/M=0.94, face-on accretion disk | Owner-blessed Astroray | SSIM + `dark_disk` + ergosphere asymmetry (manual review) |
| `disney-sweep-cycles-compared` | D | Disney roughness × metallic sphere grid | Cycles 5.1 render of same scene (Python-authored in Blender, not a BF asset) | SSIM Astroray vs Cycles ≥ 0.90 |

**Phase 2b — deferred per owner 2026-05-27 ("astrophysics low priority right now"):**
- `adaf-sgrA-faceon` (F): pkg44 ADAF profile; references captured but no gate yet — owner needs a tuning pass first.
- `synchrotron-jet-m87` (F): pkg42 bipolar jet; same — captured, not gated.
- Optional: slim-disk Novikov-Thorne (pkg43).

**Disney + Cycles comparison — special handling:**
The D-category scene is the one place Cycles enters pkg104, but it's not a BF benchmark — it's a *freshly Python-authored* sphere grid (roughness ∈ {0.0, 0.25, 0.5, 0.75, 1.0} × metallic ∈ {0.0, 0.5, 1.0}, plus a base albedo per row). The Cycles reference is captured via a Blender 5.1 subprocess that constructs the same grid and renders it once. No BF asset is touched. Forward-compat is therefore not a concern. Gate is SSIM Astroray-vs-Cycles ≥0.90; the threshold acknowledges Astroray's MC-noise floor and is loose enough to not trip on integrator-equivalent renders.

**Black-hole Blender integration — separate spec (filed alongside pkg104):**
Owner noted 2026-05-27 that BH support in the addon "still needs to be done." For the bank's purposes, BH scenes are rendered via Python (no addon dependency). The addon-side work is a separate ROADMAP item.

---

## Implementation phases

**Phase 1 — Harness skeleton** (~1.5 days, no owner input needed; doable now)
- Directory scaffolding under `benchmarks/reference-bank/`
- `runner.py` with --scenes, --gates flags and CSV/Markdown writer
- All 4 core metric implementations + 3 phenomenon-presence metrics
- pytest smoke test that runs against a dummy scene
- Stub `gates.toml` schema with one example
- *No actual scene scripts yet*

**Phase 2 — Scene selection + scene scripts** (BLOCKED on owner input)
- After Q1/Q2 answered, write 6–9 scene-construction scripts
- Each script is a pure Python function: `(astroray) -> astroray.Renderer` (the same shape `prism_reference.make_prism_scene` already uses)
- Each script + `gates.toml` lands as its own small PR (mechanical work, can be Track D once Phase 1 lands)

**Phase 3 — Reference render generation + LFS upload**
- For Cycles-renderable scenes (Cornell), reuse pkg71's existing reference EXRs.
- For spectral/caustic scenes, generate references with PBRT-v4 (preferred for SMS — `pbrt-v4` has SMS via its `manifold` integrator) or Mitsuba 3.
- For GR/astrophysics scenes, owner-blessed Astroray renders at a fingerprinted commit.
- Upload references to LFS; commit `MANIFEST.sha256`.

**Phase 4 — CI wiring**
- `reference-bank-smoke` job on every PR (Cornell-only, < 1 min).
- `reference-bank-full` nightly on self-hosted RTX runner.
- Failure → posts a comment on the offending PR with the diff artifact links.

**Phase 5 — Optional: AI-multimodal review path** (deferred / can be its own follow-up)
- `--ai-review` flag wires Claude multimodal into the report generator.
- Off by default. Owner-opt-in per round.

---

## Acceptance criteria

- [ ] **Machine-verifiable:** `python -m benchmarks.reference_bank.runner --scenes cornell --mode smoke` exits 0 and writes a `results/<date>-<sha>/<scene>/report.md`.
- [ ] **Machine-verifiable:** smoke job runs in < 60 s in CI; full nightly in < 30 min on RTX 5070 Ti.
- [ ] **Output-verifiable:** for a deliberately-broken PR (test perturbation: drop firefly clamp threshold by 5×), at least one gate on at least one scene FAILS with measurable signal in the diff artifacts.
- [ ] **Output-verifiable:** the prism dispersion scene's `hue_spread` gate reads > 0.6 on a known-good reference and < 0.2 on a same-scene render with dispersion disabled.
- [ ] **Output-verifiable:** Schwarzschild scene's `dark_disk` gate reads > 0.04 on a known-good reference and < 0.005 on a same-scene render with GR disabled.
- [ ] **Structure-verifiable:** adding a new scene requires creating exactly one directory under `scenes/`, two files (`scene.py` + `gates.toml`), and one LFS commit (`refs/<scene>-<spp>.exr`). No core harness changes.

---

## Non-goals

- **Not a benchmarking suite.** This bank is for *correctness*, not performance. pkg71 owns timing; this owns visual correctness. The two CSVs are deliberately separate.
- **Not a replacement for unit tests.** Existing test suite stays. This adds a visual layer on top.
- **Not AI-gated.** AI multimodal is at most a flag-for-human-review hint. It never blocks merge.
- **Not a Cycles-clone exercise.** For Astroray-unique scenes, references are PBRT-v4 / Mitsuba 3 / owner-blessed — not Cycles. Cycles cannot render most of what this bank exists to validate.
- **Not a UI.** Reports are Markdown + PNG; no web dashboard, no live viewer. (If the owner later wants a Pillar-5 dashboard, it consumes the CSV history from this bank.)
- **No new scenes outside the agreed category list.** Scope discipline: this is the bank, additions require an explicit follow-up.
- **No animation, no motion blur scenes.** Single-frame only, per pkg71 convention.

---

## Progress

- [x] Spec drafted (this file).
- [ ] **OWNER GATE: Answer Q1 + Q2.**
- [ ] Phase 1 harness skeleton (can begin in parallel — does not require Q1/Q2).
- [ ] Phase 2 scene scripts (post-Q1/Q2).
- [ ] Phase 3 reference renders generated + LFS upload.
- [ ] Phase 4 CI wiring.
- [ ] Phase 5 optional: AI-multimodal review path.

---

## Lessons

*(Fill in after the package is done.)*

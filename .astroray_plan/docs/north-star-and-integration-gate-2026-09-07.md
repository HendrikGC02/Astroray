# North star and Pillar-4 exit gate — 2026-09-07

Authoritative direction document. Supersedes the "Current sequencing" section of
`ROADMAP.md` (which now points here). Written state+refine; no new specs filed.
Every number below is sourced (file + command) or marked **unmeasured**.
Reviewed by Codex Terra (2026-09-07, `test_results/2026-09-07-setup/terra2_northstar_review.md`); adopted
items are marked **[Terra]**. Owner decisions still open are marked **[OWNER]**.

---

## 1. North star (owner-approved 2026-09-07, verbatim)

> Astroray is a spectral C++/CUDA path tracer whose destination is
> research-grade astrophysical rendering and science visualization (physically
> meaningful radiance, spectra, photon counts, instrument-like observables for
> nebulae, HMXBs, accretion flows, relativistic lensing), driven from inside
> Blender. Blender is the steering wheel: the engine reads Blender's own
> Cycles-shaped settings, node trees, lights and world. Near-term bar:
> production-capable Blender renderer — fast interactive GPU viewport on the
> RTX 5070 Ti, CPU as correctness oracle, Cycles-compatible where Cycles is
> right; correctness > fidelity > speed. Pillar 4 paused until integration is
> genuinely daily-usable; everything built future-aware; spectral / dispersion /
> band-aware / robust transport is foundation for both goals. Pluggable
> registries, no abstraction without a caller today.

### What this means we will NOT do

1. **No Pillar 4 astro-science implementation** (pkg45/46/48/49/50/51, pkg107) until the exit gate in §2 is met — no unilateral unpause.
2. **No sub-percent CPU/GPU parity-tail chasing** (pkg172-B / pkg173 / pkg153 remainder) unless a paper result demands bit-level parity.
3. **No new abstraction, registry, or "flexibility"** without a concrete caller in the same change (CLAUDE.md §2).
4. **No calibrated-SI / absolute-radiometric claims** — raw *relative* band output with honest provenance only (pkg243) until an instrument model exists.
5. **No parallel ground-up UI** — Blender's native Cycles-shaped panels are the only steering wheel; the custom UI was already retired to one Astroray panel (pkg176).

---

## 2. Pillar 4 exit gate — measurable checklist

The gate is MET when every row below is GREEN on the RTX 5070 Ti with a
CPU oracle cross-check. Refined from the lead's proposal with current evidence.
"Current" = last measured value on `main`; **unmeasured** = no artifact exists yet.

### (a) Viewport responsiveness

- **Target [Terra]:** on two pinned scenes (10k and 100k triangles), warm session, 3×100 camera edits and 3×100 material edits: event dispatch → first *correctly updated* Blender-presented frame, GPU p95 ≤ 100 ms and p99 ≤ 150 ms; cancellation acknowledgement p95 ≤ 200 ms, p99 ≤ 300 ms, and no stale frame presented after the ack. Denoise is **not** in the interactive loop (progressive refine; denoise on idle/pause) **[Terra recommendation, OWNER to confirm]**. CPU is the image oracle, not a latency oracle.
- **Measured by:** pkg241 Phase 0 recorder (extends the pkg81 harness) inside a real Blender session, not the in-process harness. Baseline measured tonight through the MCP bridge: idle progressive refinement redraws at **~1.3 Hz** (6 redraws / 4.46 s, 2 220-triangle scene, RENDERED viewport) — the owner's "3–5 fps, no visible refine" report reproduces.
- **Current:** the only artifact, `benchmarks/viewport_parity/2026-09-03.json`, is **in-process and explicitly bypasses the Blender GPU texture blit** (`harness_notes[0]`). Under that harness, GPU camera-only 10k-tri, no-denoise: frame p50 34.7 ms / p99 37.7 ms / max 48.4 ms (config 3); **with the OIDN pass in-loop it is p50 140.8 ms / p99 184.8 ms** (config 4) — already over 100 ms. Real end-to-end present latency is **unmeasured**.
- **If pkg241 Phase 0 says otherwise:** if real present > 100 ms even without denoise, the fix is engine/blit work (a new spec), not a target relaxation; if it is only denoise-in-loop that fails, the gate must state denoise is *not* in the interactive loop (progressive refine, denoise on pause) — see §6 owner decision.

### (b) Shader-socket coverage

- **Target [Terra, OWNER to confirm]:** frequency-weighted coverage, not raw count: over a frozen corpus of ~50 Blender scenes, score socket *uses* (SUPPORTED = 1, APPROXIMATED = 0.5 only when a warning is emitted), require ≥ 95 % weighted coverage **and zero silent drops in corpus scenes**. Raw socket counts stay diagnostic. Principled advanced inputs, Metallic BSDF, Sky texture and Displacement must each be SUPPORTED or APPROXIMATED-with-warning; only pkg253 (Principled) is scheduled — bounded support-or-warn packages for Metallic, Sky and Displacement are filed when the owner ratifies this gate, not before.
- **Measured by:** `blender.exe --background --factory-startup --python scripts/generate_blender_parity_matrix.py -- --out docs/blender_parity` → `coverage_matrix.json` (reproduce block in `blender-coverage-reaudit-2026-09.md`).
- **Current:** 152 SUPPORTED / 35 APPROXIMATED / **340 DROPPED-SILENT = 64.5%** of 527 (`blender-coverage-reaudit-2026-09.md` headline table). Target < 25% needs DROPPED ≤ 131 — a swing of ~209 sockets. pkg230 Ph1+Ph2 (Clamp, Math use_clamp, Mix clamp, Vector Math, Vector Rotate = backlog items 2/3/4/7) landed *after* that audit; their delta is **unmeasured** — re-run the generator first. The four named nodes are today all DROPPED-SILENT (BSDF_PRINCIPLED advanced 21 sockets, BSDF_METALLIC 13, TEX_SKY 14, DISPLACEMENT 5 — reaudit backlog rows 1/6/5/9).
- **Note:** the audit argues raw socket-count is the wrong metric; see §6.

### (c) Three reference scenes render CPU+GPU, no exception, parity-clean

- **Target [Terra]:** exactly three pinned `.blend` assets (fixed settings, pinned SHA — no "or" alternatives) render F12 on CPU and GPU with no addon exception and pass: linear CPU↔GPU ROI mean ratio within ±5 % per channel, a structural metric (SSIM ≥ 0.95 on the GPU vs CPU pair), and scene-specific non-vacuity checks (checker contrast present, HDRI contribution present, hair-pixel coverage > 0) so a black or missing feature cannot pass.
  1. Cornell-class interior — to be authored as a `.blend` from `tests/scenes/disney_cornell.py` (the `tests/scenes/*.py` files are native scene builders, not Blender assets).
  2. Material zoo — `blender_addon/scenes/metal_sweep.blend` (probe 2026-09-07: CPU/GPU whole-frame ratio 1.015/1.027/1.013, but floor-reflection blocks reach 1.06 — outside ±5 % locally).
  3. HDRI exterior with hair — **does not exist yet**: `ir_vegetation.blend`, `uv_skin.blend` and `metal_sweep.blend` are byte-identical placeholders (914 023 bytes, same SHA-256). Authoring the three assets is a prerequisite task for this gate.
- **Measured by:** `benchmarks/cycles-parity` harness + the addon F12 path; parity gate is the existing 5% RGB ROI mean-ratio.
- **Current:** only **cornell** has parity data (`benchmarks/cycles-parity/2026-09-03-*.csv`): astroray-gpu SSIM 0.9538 vs Cycles, mean-ratio 0.9967/0.9975/0.9944, 1477 ms vs cycles-cuda 3134 ms. The material-zoo case is **NOT GREEN on GPU** — the checker texture disappears (CPU luminance std 0.4182 vs GPU 0.0330; GPU samples only real UV layers, CPU synthesizes fallback UVs; `rebuild-handoff-2026-09-06.md`, carried by pkg242). HDRI-with-hair parity is **unmeasured**.

### (d) Adaptive sampling + denoise from native Cycles panels

- **Target:** both usable from Blender's own sampling/denoise panels.
- **Measured by [Terra]:** an output-effect test, not a reachability test: with adaptive sampling on vs off the sample-count AOV must differ and noise must fall in flat regions; with denoise on vs off the output must differ and residual noise must fall — both on CPU and GPU, driven only from native panel properties.
- **Current:** adaptive sampling landed both backends (pkg131, #659 CPU / #665 GPU, HW-verified); GPU denoise wired (pkg197). Panel-driven end-to-end usability is **unmeasured** as a single gate — needs one smoke test asserting native-panel → engine for both.

### (e) Zero open high-severity addon bugs

- **Target:** zero open GitHub issues labelled `addon-bug` with severity high.
- **Measured by [Terra]:** `gh issue list --label addon-bug --state open` against a published severity rubric (high = wrong image, crash, or a native setting silently ignored; medium = degraded but flagged; low = cosmetic) with an independent triage pass, so the gate cannot be met by relabeling.
- **Current:** the `addon-bug` label **does not exist** and no severity taxonomy is defined (`gh label list` shows only generic `bug`; 13 open issues total). This gate is currently **unmeasurable** — first action is to create the label + severity convention and triage the 13 open issues. Cheapest gate to make measurable.

### (f) Documented one-command build+install for a new user

- **Target:** a new user follows one documented command to get a working addon.
- **Measured by [Terra]:** a fresh-profile install of the release ZIP through Blender's own extension installer (distinct from `dev_addon.ps1`), followed by one F12 render, on a machine without the build toolchain.
- **Current:** `scripts/dev_addon.ps1` (build→install→smoke) and `scripts/build/build_blender_addon.py` exist; the transactional installer placed 42 files and passed an isolated smoke (`rebuild-handoff-2026-09-06.md`); `dist/astroray-4.0.0-cuda.zip` ships. The *developer* loop is one-command; the *end-user* (no build toolchain, install-zip-from-Blender) path is documented but **unverified on a clean machine**. Partially GREEN.

---

## 3. Science-foundational lane (side lane, allowed while Pillar 4 stays paused)

**Qualifies** — spectral / band / instrument / emission-mechanism / robust-transport
work that *both* the production renderer and the eventual astro platform need,
and that is exercisable today from Blender or the CPU oracle:

- **pkg243** — raw relative band output + honest provenance (Pillar 5+2).
- **pkg133** — SRF spectral sensors (detector QE × filter curves; Pillar 2, Pillar-4-adjacent instrument story).
- **pkg130** — light groups / emission-mechanism decomposition (per-group AOVs; production polish that also produces journal figures).
- **pkg251** — spectral band parameter reachability across callers (the contract debt that makes the above trustworthy).

**Does NOT qualify** — anything that only pays off once Pillar 4 unpauses: Kerr/GR
transport, accretion-flow emission models, FITS/HDF5 volume ingest, telescope PSF
(pkg45/46/48/49/50/51, pkg107). These stay frozen.

The lane runs **behind** the gate-critical work in §4, not ahead of it — it shares
one developer and the single RTX gate. Use it to fill slots only when a
gate-critical package is blocked or under review.

---

## 4. Sequencing — next 4–6 weeks, rounds of ~3 (existing IDs only)

Ranked by contribution to the exit gate first, then the science lane. IDs only —
no invented numbers. pkg253 (Principled advanced inputs) is being filed tonight
(lane L3, branch `feat/pkg253-principled-advanced-inputs`).

**Round 1 — measure truth + unblock a green baseline (gate a, c-precondition)**
- **pkg241 Phase 0** — measure real present + cancel latency in a live Blender session. Gate (a). No deps. Highest priority: the whole responsiveness lane is guessing until this exists.
- **pkg237 + pkg238** — diagnose, then repair or evidence-calibrate the two reproduced baseline failures (HDRI SSIM, PostInit ULP); both specs forbid assuming a fix or relaxing a bound without independent numeric/image evidence **[Terra]**. Gate (c) precondition — parity work on a red baseline hides regressions. No deps.
- **pkg242** — procedural mapping / bake-domain parity; closes the material-zoo checker-vanishes-on-GPU NOT-GREEN. Gate (c). Depends on landed pkg230b.

**Round 2 — coverage + texture fidelity (gate b, c)**
- **pkg253** — Principled advanced inputs; highest-value single node (backlog row 1, 21 sockets). Sequence Alpha + Specular Tint first (cheapest, most-used). Gate (b).
- **pkg245** — normal/bump image coordinate provenance. Gate (b)/(c). Pairs with the pkg223/pkg219 normal path.
- **pkg234 + pkg233** — image-texture filtering honor + standalone-BSDF texture plumbing. Gate (b)/(c) texture fidelity. pkg233 unblocks textures on non-Principled BSDFs.

**Gate-closure order [Terra]:** pkg241 → pkg242/pkg245 → coverage-node work (pkg253, then Metallic/Sky/Displacement once filed) → three-scene corpus + settings/build/triage gates → science lane. Rounds 3–4 below are **conditional fill work**: a science-lane package is dispatched only when every gate-critical package is blocked or under review.

**Round 3 — close responsiveness + open the science lane (gate a, science)**
- **pkg241 behavior phases** — cooperative cancellation contract + response behavior, on top of Phase 0 numbers. Gate (a) close.
- **pkg251** — spectral band parameter reachability; foundation that unblocks pkg243/pkg133. Science lane + parity contract debt (pkg251 already owns the rebuild luminance/checker contract debt).
- **pkg243** — raw relative band provenance. Science lane. Depends on pkg251 contract.

**Round 4 — science lane + kept foundation**
- **pkg133** — SRF spectral sensors. Science lane; depends on the spectral sampling contract (pkg251-adjacent).
- **pkg130** — light groups / emission decomposition. Science lane + AOV production value.
- **pkg136 GPU leg (Stage 2)** — wavefront path-guiding. Variance-reduction foundation for both goals. Depends on landed pkg136 CPU 1A/1B (#693/#694).

**Backlog lane (kept, lower gate contribution — fill when blocked, not scheduled)**
- **pkg124** VNDF reflection lobe — serialize behind the `disney.cpp` Lane-A chain; re-baseline chi² anchors first (spec note).
- **pkg126** mesh-emitter unification — L-effort, five integrators + GPU mirror, no visible change; needs a dedicated day arc, not a round slot.
- **pkg127 Phase 2** — needs topology/flag reconciliation (`sms_specular_poly`, not the obsolete `sms_polynomial_seed`) against pkg227; do the reconciliation before dispatch (`production-gap-audit-2026-09-06.md`).
- **pkg227 remaining phases** — general specular polynomials (approved, order 2a→2b-flat→…); XL, opportunistic.

---

## 5. ROADMAP.md deletions the lead should prune

The rewrite in this branch replaces "Current sequencing" (old lines 29–177) and
the gate paragraph under Pillar 4 (old lines 247–255). The following are stale and
should be cut or archived separately by the lead:

- **Old lines 257–268** — the "Thaw notice (2026-05-10) + shipping" block that says *"Pillar 4 now ~50% complete"* / *"actively shipping"*. **Directly contradicts the PAUSE two paragraphs above it** and the north star. Delete.
- **Old lines 278–346** — "Backend parity bridge" + the Round-6 Pillar-5 closeout with stale perf claims (pkg81 "CUDA 104 ms vs CPU 58 ms", denoiser multipliers, SSIM tables). Historical; belongs in `docs/archive/`, not the navigational roadmap.
- **Old lines 348–478** — the pasted round-closeout logs (2026-08-12 → 2026-08-31) under Pillar 4. This is STATUS.md material; the roadmap should link, not inline it.
- **Old lines 46–64** — Phase (a) "Engine settlement" closeout narrative. Fully historical; compress to one line or archive.
- **Old lines 22–25** — "rival Cycles in simple enough cases" performance box. Keep, but reframe under "correctness > fidelity > speed" so it does not read as a co-equal near-term promise.

## 6. Risks to the north star (max 5) + the one decision to make next

1. **The viewport gate may be measured on the wrong instrument.** The 37.7 ms p99 comes from an in-process harness that bypasses the Blender GPU blit; denoise-in-loop already shows 184.8 ms. The gate could "pass" on an optimistic number. Mitigation: pkg241 Phase 0 must measure real present latency before any (a) sign-off.
2. **The < 25% DROPPED-SILENT target may be structurally infeasible in 4–6 weeks.** Closing ~209 sockets is dominated by L-effort closures (Principled advanced, Metallic, Sky, SSS, volume). A raw-count target rewards cheap niche sockets over the nodes users actually wire.
3. **Only one parity scene is measured, and one of the three named scenes is a known GPU failure.** Gate (c) can stall indefinitely on the material-zoo checker bug and two unmeasured scenes.
4. **Science-lane creep.** pkg133/130/243/251 compete with gate-critical work for one developer and one RTX gate; running them in parallel risks slowing the integration the owner said comes first. The lane is explicitly ordered *behind* §4.
5. **The baseline is not green.** pkg237/pkg238 failures + the pkg249 Cornell reference smoke (2/3 gates) mean regressions can hide under direction-setting. Round 1 must restore green before feature parity claims.

**The single most important thing for the owner to decide next:** *Is the shader-socket
coverage gate (b) a raw socket-count target (< 25% DROPPED-SILENT of 527) or a
frequency-weighted-coverage target (the audit's own recommendation)?* This one
choice re-scopes multiple rounds of §4 — a raw count forces breadth across niche
closures; a frequency-weighted target lets Principled-advanced + the common nodes
carry the gate. (Close second, embedded in Risk 1: whether denoise is in the
interactive viewport loop, which decides an entire responsiveness work lane.)

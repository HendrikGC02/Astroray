# Blender Addon Remediation — First-Principles Plan (Next Stages)

**Date:** 2026-05-16
**Author:** Architect (next-stage planning pass — NO code changed)
**Inputs:** the PR #295 triage (`blender-addon-bug-triage-2026-05-15.md`,
17 symptoms → 9 root causes, the stale-loaded-module finding), STATUS.md /
ROADMAP.md / NEXT_STAGE_REPORT.md (current main; PR #299 round-9-close is
OPEN and *not* depended on here), pkg55-B' spec (Phase B' staged plan +
the two-tier-gate NOTE), and the pkg55-B' Session 2c technique review
(PR #296).
**Method:** Aristotelian first-principles decomposition. The 17 symptoms
and even the 9 RCs are *effects*. This doc reduces them to the small set
of irreducible defect-classes ("primitives") from which the symptoms
*necessarily follow*, then derives the staged plan **up from the
primitives** — not by enumerating symptoms.
**Status:** Planning + written deliverable. Nothing fixed.

> Validation note: the triage's load-bearing root-cause line references
> were re-checked against current `main` (HEAD `abc8716`): `__init__.py`
> `if False else ''` @ L1865, `CustomRaytracerRenderEngine()` @ L676,
> hardcoded `sensor_width = 32.0` @ L1549, the device-uploader-only
> dispatcher @ L1222–1225, and zero `renderPassBuffers/*Buffer` refs in
> `src/gpu/cuda_renderer.cu`, with the unconditional
> `buildAcceleration()+uploadScene()+uploadEnvironmentMap()` in the GPU
> `render()` branch @ `blender_module.cpp:871–874`. **The decomposition
> below is built on a verified triage, not a re-triage.**

---

## 1. Method: why decompose past the 9 root causes

The triage already did the first reduction: 17 symptoms → 9 shared root
causes (RC-1..RC-9). That is necessary but not yet *first-principles*. RC-2
and RC-4 are two faces of one deeper defect; RC-3 and RC-4 are the same
defect on two backends; RC-1 is not a code defect at all. Planning the
"next couple of stages" by walking RC-1..RC-9 in order would (a) interleave
a process artifact with real bugs, (b) split one architectural defect
across two stages, and (c) miss that two of the "addon" RCs are actually
the **pkg55-B' wavefront program** wearing an addon mask.

So we reduce once more. For each primitive we state, in the Aristotelian
frame:

- **Formal cause (essence):** what the defect *is*, stated as a violated
  invariant — not a symptom.
- **Efficient cause (what produces it):** the concrete mechanism in the
  code/process that generates it.
- **Final cause (correct end-state):** the invariant restored; what "this
  primitive no longer exists" looks like and how it is proven.

A correct primitive has the property that **resolving it provably
collapses an entire symptom group at once**, because every symptom in the
group is a logical consequence of the one violated invariant.

---

## 2. The irreducible primitives

Five primitives. Every one of the 17 symptoms is a necessary consequence
of exactly one of them (BUG-03 and BUG-13 sit on a boundary and are noted).

### P1 — Process/build integrity is not self-evident to the running engine

- **Formal cause:** the invariant *"the bytes Blender is executing are the
  bytes that were just built/installed"* is not enforced or even
  observable. A loaded module can silently be an older generation than the
  one on disk, and nothing in the system asserts otherwise.
- **Efficient cause:** Blender memory-maps `astroray.pyd` on addon load and
  holds the lock for the process lifetime; re-installing while Blender runs
  lands the new `.pyd` beside the old one (`.~stale~NNNN` shadow dirs are
  the OS telling us the overwrite was refused), but the running interpreter
  keeps the *old* class surface. There is no build-stamp the addon checks
  on `register()`, and the install script neither detects the lock nor GCs
  the shadow dirs.
- **Final cause:** on `register()` the addon compares its expected build
  identity (hash/stamp) against `astroray.__build__`; on mismatch it raises
  a single loud, unambiguous "RESTART BLENDER — stale module loaded"; the
  install path refuses-or-warns on a locked `.pyd` and GCs `.~stale~`.
  Proven by: deliberately re-installing under a running Blender and
  observing the guard fire (not an AttributeError), and a clean install
  producing no `.~stale~` and a matching stamp.
- **This is not a code-logic defect.** It is the *observability* of a
  process invariant. It is the cheapest primitive and it **gates the
  verifiability of every other primitive** (you cannot prove P2/P3 fixed if
  the tester might be running a stale module).

### P2 — The addon↔engine incremental-sync contract is "push device state," not "reconcile scene state"

- **Formal cause:** the invariant *"after any Blender edit, the engine's
  view of the scene equals Blender's current scene"* is violated for every
  edit whose new value lives in re-parsing, not in re-uploading. The
  incremental dispatcher's contract is *"re-push the device buffer for the
  changed domain"* — it has no step that *re-reads* Blender for that
  domain, and it has no domain at all for several change classes.
- **Efficient cause:** `_apply_depsgraph_updates`
  (`__init__.py:1158–1237`) maps a changed domain straight to a *device
  uploader* (`upload_environment/materials/lights/geometry`,
  L1222–1225). The functions that actually *re-parse Blender state*
  (`setup_world` re-reads the world node tree; `_configure_backend_for_context`
  applies `device_mode`) run **only** on the full-sync / fallback path
  (`_sync_viewport_scene`). A World color edit re-uploads already-parsed
  env state without re-reading the Background node; a `device_mode` change
  classifies as `accumulation_only` (L1143) → resets accumulation and
  returns `'idle'` (L1216–1220), never reconfiguring the backend.
- **Final cause:** the dispatcher's contract becomes *"reconcile, then
  upload"*: each domain first re-derives its state from Blender (re-walk
  world tree / re-evaluate backend selection / re-read the changed
  datablock) and only then pushes the device buffer; backend-affecting
  Scene props get a real domain that calls the reconfigure path. Proven
  by: edit world color in rendered viewport → image updates without any
  unrelated edit; switch CPU/GPU in rendered viewport → backend switches
  without exiting rendered mode.
- **Scope note:** the *crash* of BUG-03 is P1 (stale module). The
  *coarseness* of BUG-03's transform path (full BVH rebuild because no
  per-object id map) is an intentional Phase-C limitation, not this
  primitive — document, do not "fix."

### P3 — A class of UI-presented features is wired to a dead path (presented ≠ functional)

- **Formal cause:** the invariant *"a control the UI presents as
  functional actually feeds the engine"* is violated. Specific
  feature paths terminate in a no-op or a forbidden call before they ever
  reach the engine, even though the binary fully supports the feature.
- **Efficient cause:** three distinct dead-path mechanisms, same essence:
  (a) a hard `if False` gate drops the IR/UV node's spectral profile
  (`__init__.py:1865`) and the native-output path never calls
  `set_material_spectral_profile` for that kind — the feature is
  *unreachable by construction*; (b) the preview operator constructs a
  `RenderEngine()` directly (`__init__.py:676`), which Blender forbids,
  so the whole preview path dies with a `TypeError` before any conversion
  runs; (c) custom `ShaderNode` subclasses may not survive
  `inline_shader_nodes()` flattening, so the native-output / IR-UV /
  Sellmeier detection `next(...)` finds nothing and silently falls through
  to the standard path. Each is "the wire is cut between a presented
  control and the engine."
- **Final cause:** every UI-presented control has a live, tested wire to
  the engine, or it is not presented. Proven by: IR/UV node renders a
  non-visible-band material (profile actually uploaded); preview button
  runs without constructing a `RenderEngine`; a probe confirms custom
  nodes survive flattening (or the converter is fed pre-flatten).
- **Boundary note:** the *multi-band closure* half of BUG-13 (a full
  spectral response material) is genuinely pkg-future and stays
  documented-not-fixed; the *`if False` + missing call* half is this
  primitive and is the cleanest single defect in the report.

### P4 — Camera projection is re-derived from guessed intrinsics instead of taken from Blender

- **Formal cause:** the invariant *"the engine's camera frustum equals the
  frustum Blender is drawing"* is violated because the engine *reconstructs*
  a projection from sensor/lens guesses rather than *consuming* Blender's
  own projection matrix. Two independent reconstructions exist and disagree
  with each other and with Blender.
- **Efficient cause:** `_apply_camera` (`:1639`, F12 / scene-camera /
  CAMERA-view) derives vFOV from the real camera datablock (default 36 mm);
  the free-orbit path `_setup_viewport_camera` (`:1547–1554`) **hardcodes
  `sensor_width = 32.0`** (verified L1549) and derives hFOV from
  `space_data.lens`, ignoring lens shift and `view_camera_offset`. Any
  re-derivation that does not start from `rv3d.window_matrix` /
  `perspective_matrix` is a guess that cannot match Blender's overlay.
- **Final cause:** one projection path, taken from Blender's native
  matrices, so viewport == F12 == Blender's own overlay by construction.
  Proven by: object-mode camera gizmo and orbit align with the rendered
  framing in both PERSP/ORTHO and CAMERA view.

### P5 — The GPU backend is not feature-equivalent to the CPU backend; it is a single-framebuffer megakernel

- **Formal cause:** the invariant *"GPU and CPU produce the same image and
  the same auxiliary outputs for the same scene"* is violated structurally,
  not by a tunable. The CPU path runs the full plugin pipeline (Pass/AOV/
  denoise plugins, world-as-environment-light via NEE/indirect, incremental
  device state). The GPU path computes **one** combined `d_framebuffer`,
  copies it back, treats the world as a camera-ray *miss color* only, and
  re-uploads the entire scene every `render()` call.
- **Efficient cause:** `src/gpu/cuda_renderer.cu` `render()` /
  `renderMultiwavelength()` never touch `renderPassBuffers/depth/position/
  albedo` (verified: zero references) and run no `Pass` plugin — Pass
  plugins are CPU constructs the CPU integrator invokes. The world enters
  the GPU kernel as `backgroundColor`/`hasBackgroundColor` used only as the
  miss color, not as an env light contributing to BSDF illumination
  (corroborated by pkg85-D, the filed HDRI-world-only GPU/CPU SSIM bug).
  The GPU `render()` branch unconditionally
  `buildAcceleration()+uploadScene()+uploadEnvironmentMap()` every call
  (`blender_module.cpp:871–874`), so progressive viewport re-uploads the
  whole scene per sample-chunk while the pkg56-B incremental uploaders are
  bypassed.
- **Final cause:** the GPU path executes the same auxiliary outputs and the
  same environment-as-light model as CPU, and re-uploads only changed
  domains — i.e. the GPU is a *backend of the same pipeline*, not a
  separate reduced renderer. Proven by: GPU AOV/denoise/world-only-diffuse
  SSIM parity vs CPU, and one upload per changed domain (not per sample).
- **This is the pkg55-B' wavefront program wearing an addon mask.** The
  per-pass-buffer write and per-domain upload on GPU are *exactly* the
  infrastructure the wavefront shade/terminate stages and SoA state are
  being rebuilt to provide. Treating P5 as "an addon bug to fix now" would
  duplicate — and almost certainly conflict with — the pkg55-B' track. P5
  is real but its resolution is *scheduled into pkg55-B'*, with a cheap
  honesty guard in the addon meanwhile.

---

## 3. Primitive → symptom mapping (the collapse proof)

Resolving one primitive collapses its whole symptom group, because each
symptom is a logical consequence of the one violated invariant.

| Primitive | Triage RCs subsumed | Symptoms it eliminates | Why the group collapses together |
|---|---|---|---|
| **P1 — process/build integrity not observable** | RC-1 | BUG-01, BUG-07, BUG-03 *(crash only)* | All three are the *same* old in-memory class surface throwing `AttributeError: no attribute 'upload_*'`. One stale-module guard makes every one of them stop reproducing (and un-masks P2's BUG-04/05). |
| **P2 — sync contract pushes device state, never re-parses** | RC-3 | BUG-04, BUG-05, BUG-03 *(transform-coarseness is the documented-intent half)* | Every symptom is "edit X in rendered mode; nothing changes until a full re-sync." One contract change (reconcile-then-upload + a backend-affecting domain) fixes all of them; they share `_apply_depsgraph_updates`. |
| **P3 — UI-presented features wired to a dead path** | RC-5, RC-8, RC-6 | BUG-13 *(the `if False` half)*, BUG-15, BUG-09 | Each is a severed wire between a presented control and the engine. Cutting in the wire (remove `if False`+add the call; de-`RenderEngine()`; ensure custom nodes survive flatten) restores each feature; the binary already supports them. |
| **P4 — camera re-derived, not taken from Blender** | RC-7 | BUG-08 | Single defect, single symptom — but it is irreducible (a distinct invariant: engine frustum ≡ Blender frustum) and must be its own primitive, not folded into P2. |
| **P5 — GPU is a reduced single-framebuffer megakernel, not a CPU-equivalent backend** | RC-2, RC-4 | BUG-02, BUG-10, BUG-11, BUG-12 | All four follow from "GPU runs no pass plugins, treats world as miss-color, and full-uploads per call." They cannot be fixed piecemeal in the addon; they are resolved by the wavefront pipeline gaining per-pass buffers + env-as-light + incremental upload. One architectural change, one symptom group. |

**Not a primitive (correctly excluded):** BUG-06 (GPU *is* spectral;
perceptual), BUG-17 (docs), the IR/UV multi-band-closure half of BUG-13,
the transform-coarseness half of BUG-03 — these are *works-as-designed /
not-yet-implemented*, not violated invariants. They are documentation
deliverables, not remediation primitives.

**Needs a runtime probe before P3/“fidelity” can be fully scoped:**
BUG-09 (does `inline_shader_nodes()` keep custom nodes? — gates the
node half of P3), BUG-11 (CPU-vs-GPU world-only diffuse — confirms P5's
env-as-light face), BUG-14 / BUG-16 (glass absorption / subsurface —
RC-9 and the TBD; these are fidelity-model gaps, deliberately *outside*
the next 2–3 stages; see §6).

---

## 4. The staged plan, derived from the primitives

Each stage closes one primitive (or a coherent subset). Ordering is
forced by three facts: **P1 gates verifiability of everything**; **P3 and
P4 are cheap, independent, and real**; **P5 is expensive and entangled
with pkg55-B'** so it must not be opened as addon work in the next
stages. This yields two cheap stages now and one *scheduling/guard*
stage for P5 — not a P5 implementation stage.

### Stage 1 — Close P1 (process/build integrity guard). *No code-logic risk.*

- **Objective:** make a stale loaded module impossible to mistake for a
  code bug, and un-mask P2's real defects so Stage 2 is verifiable at all.
- **Primitive closed:** P1.
- **Symptoms collapsed:** BUG-01, BUG-07, BUG-03 (crash). The three
  loudest "crash" reports stop reproducing with **zero engine-logic
  change**.
- **Work:** (a) addon emits/embeds a build stamp; on `register()` it
  compares against `astroray.__build__` (or the staged `build_report.json`
  hash) and raises one loud "RESTART BLENDER — stale module loaded" on
  mismatch; (b) install script refuses-or-warns on a locked `.pyd`, GCs
  `.~stale~NNNN`, and prints "Quit Blender before reinstalling."
- **Effort:** ~½ day. Lowest risk in the whole plan (packaging/observability
  only; no integrator or kernel touched).
- **Dependencies:** none. Must be **first** — it is the verifiability
  multiplier for Stages 2–3.
- **Verification the primitive is gone:** (1) re-install under a running
  Blender → the guard fires with the restart message, *not* an
  `AttributeError`; (2) clean install on a quit Blender → matching stamp,
  no `.~stale~` left; (3) with the guard green, BUG-04/05 now reproduce
  *on a known-current module* (proving P1 was masking P2, and that Stage 2
  is now testable).
- **Sequencing vs pkg55-B':** fully independent. No GPU/wavefront overlap.
  Can land immediately, in parallel with any pkg55-B' session.

### Stage 2 — Close P3 + P4 (re-connect the dead UI wires + single camera projection). *Cheap, real, independent.*

- **Objective:** every UI-presented control either works or is not shown;
  the engine camera is Blender's camera. These are the highest
  fix-value-per-effort *real* defects and neither touches the GPU
  architecture.
- **Primitives closed:** P3 and P4 (grouped: both are small, independent,
  CPU-path, parallelizable once Stage 1 lands).
- **Symptoms collapsed:** BUG-15 (preview crash), BUG-13 `if False` half
  (IR/UV spectral profile), BUG-09 (native node survival — *gated by a
  quick probe*), BUG-08 (camera alignment).
- **Work (each independently shippable):**
  - **P3-a (BUG-15):** factor node-conversion off the `RenderEngine`
    subclass so the preview path calls it without constructing a
    `RenderEngine()`. Self-contained; crash → fixed.
  - **P3-b (BUG-13 wire):** remove the `if False`, thread the node
    profile through, call `set_material_spectral_profile` on the
    `astroray_ir_uv` / native-output path. *Depends on the P3-c probe* —
    if custom nodes don't survive flattening the profile still won't
    reach the converter.
  - **P3-c (BUG-09 probe + fix if needed):** confirm whether
    `inline_shader_nodes()` preserves `AstrorayOutputNode` /
    IR-UV / Sellmeier subclasses; if not, feed the converter the
    pre-flatten tree (or detect on the original). Gates P3-b and every
    native-node feature.
  - **P4 (BUG-08):** replace both FOV derivations with one
    Blender-native projection (`rv3d.window_matrix` /
    `perspective_matrix`) so viewport == F12 == Blender.
- **Effort:** ~1.5–2 days total; P3-a/P4 are independent and
  parallelizable; P3-b waits on the P3-c probe.
- **Dependencies:** Stage 1 (so fixes are verifiable on a known-current
  module). P3-b depends on the P3-c probe. None of it depends on P5.
- **Verification the primitives are gone:** preview button runs (no
  `TypeError`); an IR-band material renders non-black with a profile
  actually uploaded (C++ no longer logs "0 profiles"); the custom-node
  probe prints the node present post-flatten (or the fix makes the
  converter see it); object-mode camera + orbit align with the render in
  PERSP/ORTHO/CAMERA.
- **Sequencing vs pkg55-B':** fully independent — these are CPU-path /
  Python-addon defects. Zero overlap with the wavefront SoA/CUDA track.
  Can run concurrently with any pkg55-B' session.

### Stage 3 — Close P2 (sync contract: reconcile-then-upload) + the P5 honesty guard. *Real correctness; P5 deliberately NOT implemented here.*

- **Objective:** make the incremental viewport contract *reconcile state
  before uploading*; and add a cheap, honest GPU-limitation guard so P5's
  symptoms stop reading as bugs while the *real* P5 fix is sequenced into
  pkg55-B'.
- **Primitives closed:** P2 (fully). P5 is **not** closed here — it is
  *acknowledged and deferred* with a UX guard (see §5).
- **Symptoms collapsed:** BUG-04, BUG-05 (P2, fully fixed). For P5
  (BUG-02/10/11/12): not fixed, but converted from "silent wrong/black"
  to "explicitly gated/labelled," which is the correct interim per the
  owner's triage-only constraint and the pkg55-B' overlap.
- **Work:**
  - **P2:** in `_apply_depsgraph_updates`, give each domain a
    *reconcile* step before the device upload: a World update re-runs the
    world-tree parse (`setup_world` equivalent) before
    `upload_environment`; backend-affecting Scene props (`device_mode`)
    get a real domain that calls `_configure_backend_for_context`
    instead of classifying as `accumulation_only`. Both edits live in the
    one dispatcher — do them together (they share the function and the
    test surface).
  - **P5 guard (UX only, not the architecture):** when `device_mode`
    resolves to GPU and the scene requests AOV/denoise/compositor passes
    or is world-only-lit, surface a clear, non-crashing notice ("AOV /
    denoise / world-as-light passes are CPU-only pending the pkg55-B'
    wavefront pass pipeline"); optionally auto-route those passes to CPU.
    This is ~½ day and contains *no* GPU kernel work.
- **Effort:** P2 ~1–1.5 days; P5 guard ~½ day. ~2 days total.
- **Dependencies:** Stage 1 (P2 is unverifiable while P1 masks it — this
  is *the* reason P1 is Stage 1). Independent of Stage 2.
- **Verification the primitive is gone:** edit world color in rendered
  viewport → image updates with no unrelated edit; switch CPU/GPU in
  rendered viewport → backend switches without leaving rendered mode; with
  GPU selected, an AOV/denoise/world-only scene shows the guard notice (or
  silently renders correctly on CPU), never a black/wrong image presented
  as if correct.
- **Sequencing vs pkg55-B' (critical):** **P2 is independent of pkg55-B'**
  (CPU-path Python dispatcher). **P5 must NOT be implemented in this
  stage.** P5 (RC-2 GPU pass/AOV/denoise/env-light + RC-4 incremental GPU
  upload) is the *same infrastructure* pkg55-B' Sessions N+1 (shadow/miss/
  terminate) and N+2..M (CUDA port) build: per-pass-buffer writes and SoA
  per-domain state are wavefront-stage deliverables. Implementing a
  parallel GPU pass/upload path in the megakernel addon now would (a)
  duplicate work, (b) almost certainly conflict with the wavefront branch,
  and (c) be thrown away when the megakernel is deleted in Phase C. The
  honest guard is the correct interim. **P5's real close is folded into
  pkg55-B' — see §5.**

---

## 5. P5 and pkg55-B': the overlap, stated explicitly

P5 = RC-2 (GPU executes no Pass/AOV/denoise plugins; world is miss-color
not env-light) + RC-4 (GPU `render()` full-uploads every call). pkg55-B'
is rebuilding the GPU path as a wavefront pipeline with **per-stage SoA
state** and **per-material shade + shadow + miss + terminate stages**. The
infrastructure P5 needs is *exactly* what pkg55-B' is constructing:

- **Per-pass / AOV buffers on GPU (BUG-02/10):** the wavefront
  `stage_terminate` / shade stages are where per-pixel auxiliary outputs
  (albedo/normal/depth/denoise-guide) are naturally written — Cycles
  writes its passes from the wavefront shade/film stages, which is the
  reference pkg55-B' mirrors. Building a separate AOV path in the
  megakernel now is throwaway work deleted in Phase C.
- **World-as-environment-light on GPU (BUG-11):** this is the same
  env-as-light NEE/indirect contribution the wavefront `stage_miss` +
  shade-NEE must implement for spectral parity; pkg85-D (filed) is the
  CPU/GPU SSIM gate for exactly this. P5's BUG-11 *is* pkg85-D's defect.
- **Incremental GPU upload (BUG-12):** the wavefront SoA state model is
  inherently per-domain; "only re-upload changed domains" is co-designed
  with the SoA state lifecycle, not a megakernel patch.

**Recommended sequencing.** Stages 1–3 (P1, P3, P4, P2 + P5-guard) run
**now, independent of and concurrent with** the pkg55-B' Round-10 track —
they are CPU-path / Python / packaging and touch no GPU kernel. **P5's
real resolution is scheduled as explicit acceptance criteria inside
pkg55-B'**, not as a separate addon stage:

- Fold **BUG-11** into **pkg85-D** (already filed; it is the same GPU
  env-as-light SSIM gate) and make pkg85-D a named pkg55-B' Phase-B/C
  parity gate rather than a standalone megakernel patch.
- Add **BUG-02 / BUG-10** (GPU AOV + denoise pass execution) as an
  explicit pkg55-B' deliverable in the **shadow/miss/terminate** session
  (Phase B' staged-plan item N+1) and the **CUDA-port** sessions — the
  wavefront shade/terminate stages must write the pass buffers the addon's
  `get_render_pass_buffer` already reads on CPU.
- Add **BUG-12** (incremental GPU upload) as a co-design note on the SoA
  state lifecycle in pkg55-B' Phase B'/C — only changed domains
  re-uploaded, mirroring P2's CPU contract on the GPU side.

This is the answer to the triage's own focusing question (§7 there): the
correct posture is **"small UX guard now (Stage 3) + fold the real GPU
parity into pkg55-B' later"**, *not* "stand up a new GPU subsystem now."

---

## 6. Out of the next 2–3 stages (deliberately)

- **Fidelity-model gaps (RC-9 BUG-14 glass absorption, BUG-16
  subsurface):** real but distinct from the five primitives — they are
  *material-model fidelity*, not severed wires or backend asymmetry. They
  need the triage's runtime probes (thick cube vs thin pane vs Cycles;
  Subsurface 0 vs 1 diff) before scoping. **Recommend a follow-up package**
  after the probes (see §7), not a stage here.
- **Docs (BUG-17 caustics/dispersion node UX, BUG-06 "GPU spectral but
  perceptually close"):** pure documentation. Bundle into the addon user
  docs pass; not a remediation stage.
- **Transform-coarseness half of BUG-03 / IR-UV multi-band closure half
  of BUG-13:** works-as-designed / pkg-future. Document the limitation;
  do not "fix."

---

## 7. Proposed follow-up package specs (described, not filed)

These are recommended fillings; only the architect/owner should decide
whether to file. None are trivial enough to file inline here.

1. **pkg-addon-process-guard** — Stage 1 made concrete: build-stamp +
   `register()` assert + install-script lock/`.~stale~` handling. ~½ day.
   Closes P1. *Strongly recommend filing — it is the verifiability
   multiplier for all other addon work and is independent of everything.*
2. **pkg-addon-ui-wire-repair** — Stage 2: BUG-15 de-`RenderEngine()`,
   BUG-13 `if False`+missing-call, BUG-09 node-flatten probe+fix, BUG-08
   single Blender-native camera projection. ~2 days. Closes P3+P4. Could
   be one package or split P3/P4; recommend one (shared review surface,
   all CPU-path).
3. **pkg-addon-sync-reconcile** — Stage 3 P2 half: reconcile-then-upload
   dispatcher + backend-affecting Scene-prop domain + the P5 honesty
   guard. ~2 days. Closes P2; guards P5.
4. **pkg55-B' spec amendment (not a new package)** — fold BUG-02/10/11/12
   into pkg55-B' as named Phase-B/C parity gates (BUG-11 ⇒ make pkg85-D a
   pkg55-B' gate; BUG-02/10 ⇒ shade/terminate must write pass buffers;
   BUG-12 ⇒ SoA per-domain upload). This is the §5 sequencing made
   actionable. *This is also where the pkg55-B' Session-2c "two-tier
   gate" NOTE should be folded in the same amendment* (the spec already
   flags it for Round-closeout; the CPU↔CPU exact / CPU↔GPU bounded gate
   split and the §4.4 "shared-kernel, never re-transcribe" 9th design
   decision from the Session 2c technique review belong in the same edit).
5. **pkg-addon-fidelity-probe** — run the BUG-14/16 runtime experiments,
   then scope colored-glass Beer-Lambert / Subsurface plumbing. Gated by
   probes; out of the next 2–3 stages.

**Roadmap-recommendation note (do not edit NEXT_STAGE_REPORT now):** PR
#299 (round-9-close) is OPEN and owns NEXT_STAGE_REPORT.md / STATUS.md /
ROADMAP.md. To avoid a doc-PR conflict, the roadmap fold-in is recorded
here instead: **after #299 merges**, add to NEXT_STAGE_REPORT §2 a
"Blender addon remediation" track with Stage 1 (pkg-addon-process-guard)
as top priority alongside the existing pkg55-B' Round-10 work, and record
that P5/BUG-02/10/11/12 are pkg55-B' acceptance criteria, not a separate
GPU package.

---

## 8. Recommendation

**Do P1 first as its own ~½-day packaging stage (Stage 1); it is the
verifiability multiplier and has no code-logic risk.** Then run Stage 2
(P3+P4 — the cheap, real, independent UI-wire + camera defects) and Stage
3-P2 (the reconcile-then-upload sync contract) — all three are CPU-path /
Python / packaging and run concurrently with, and independent of, the
pkg55-B' Round-10 wavefront track. **Do not stand up a GPU pass/AOV/upload
subsystem in the addon (P5); add only the cheap honesty guard now and fold
the real GPU parity (BUG-02/10/11/12, and BUG-11≡pkg85-D) into pkg55-B' as
named acceptance gates** — the wavefront pipeline is already building
exactly that infrastructure, so a parallel megakernel implementation would
be duplicate work deleted in Phase C. Net: three cheap stages collapse 11
of the 17 symptoms (BUG-01/03/07 via P1; 13/15/09 via P3; 08 via P4;
04/05 via P2) with zero pkg55-B' contention; the remaining 4 GPU symptoms
become scheduled pkg55-B' gates; the rest are documentation.

## 9. One focusing question for the owner

For Stage 3's P5 guard: when the user has GPU selected and the scene needs
AOV / denoise / world-as-light passes, do you want the addon to **(a)
silently auto-route just those passes to CPU** (seamless image, hidden
backend switch, possible perf cliff the user can't see), or **(b) show an
explicit "these passes are CPU-only until the wavefront pass pipeline
lands" notice and let the user decide** (honest, but a visible limitation
in the UI)? This is the only behavioral fork in the next three stages that
is a product decision rather than an engineering one.

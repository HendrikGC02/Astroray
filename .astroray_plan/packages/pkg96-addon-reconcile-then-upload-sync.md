# pkg96 — Blender addon: reconcile-then-upload sync contract + P5 honesty guard

**Pillar:** 5
**Track:** A (core quality / correctness — addon Python)
**Status:** open — Stage 3 / P2 + P5-guard of the addon first-principles plan (PR #300). **Depends on pkg94; independent of pkg95.**
**Estimated effort:** ~2 days (P2 ~1–1.5 d; P5 honesty guard ~½ d)
**Depends on:** **pkg94** (build-integrity guard — P2 is unverifiable while P1 masks it; this is *the* reason pkg94 is first). Independent of pkg95.

---

## Goal

**Before:** The incremental viewport sync contract is *"push the device
buffer for the changed domain"* — it never *re-parses* Blender state for
that domain, and it has no domain at all for several change classes:

- **BUG-04 (P2):** a World node-tree edit →
  `_classify_depsgraph_update` returns `{'environment': True}` →
  `_apply_depsgraph_updates` calls `renderer.upload_environment()`
  (`__init__.py:1222`). But `upload_environment` is a *device re-upload
  of already-parsed env state* — it never re-walks the world node tree.
  Only `setup_world` (`:3352`) re-reads the Background node, and that
  runs only on full sync. The new background color is ignored until a
  fallback/full-sync is forced (e.g. an unrelated material edit).
- **BUG-05 (P2):** `device_mode` is a Scene property. A Scene update →
  `_classify_depsgraph_update` returns `{'accumulation_only': True}`
  (`:1142–1143`) → the dispatcher resets accumulation and returns
  `'idle'` (`:1216–1220`). It never calls
  `_configure_backend_for_context` (`renderer.set_use_gpu(...)`), which
  runs only in `_sync_viewport_scene` (`:1287`). The backend is not
  switched until a full re-sync (toggle out/in of rendered mode).
- **P5 symptoms (BUG-02 / BUG-10 / BUG-11 / BUG-12):** on GPU the
  Pass/AOV/denoise plugins never run, the world is treated as a
  camera-ray miss color (not an environment light), and `render()`
  re-uploads the whole scene every call. These present as
  silent-wrong/black images.

**After:** The dispatcher's contract is *"reconcile, then upload"*: each
domain first re-derives its state from Blender (re-walk the world tree /
re-evaluate backend selection) and only then pushes the device buffer;
backend-affecting Scene props get a real domain that calls the
reconfigure path. Editing world color in rendered viewport updates the
image with no unrelated edit; switching CPU/GPU in rendered viewport
switches the backend without leaving rendered mode. For P5, a cheap,
honest UX guard converts the GPU AOV/denoise/world-only symptoms from
"silent wrong/black" to "explicitly gated/labelled" — **P5's real
architecture is NOT implemented here; it is folded into pkg55-B' as
named acceptance gates** (see pkg55 spec edits + pkg85-D cross-ref).

---

## Context

This is **Stage 3 / primitive P2 + the P5 honesty guard** of the addon
remediation first-principles plan (PR #300 §4 Stage 3, §5).

- **P2 (PR #300 §2):** violated invariant — *"after any Blender edit, the
  engine's view of the scene equals Blender's current scene."* The
  efficient cause: `_apply_depsgraph_updates` (`__init__.py:1158–1237`)
  maps a changed domain straight to a *device uploader*; the functions
  that *re-parse Blender state* (`setup_world`,
  `_configure_backend_for_context`) run **only** on the full-sync path.
  The final cause: each domain re-derives its state from Blender, then
  pushes the device buffer; backend-affecting Scene props get a real
  domain. *Scope note:* the *crash* of BUG-03 is P1 (pkg94); the
  *coarseness* of BUG-03's transform path (full BVH rebuild — no
  per-object id map) is an intentional pkg56 Phase-C limitation —
  document, do not "fix."
- **P5 (PR #300 §2, §5):** violated invariant — *"GPU and CPU produce
  the same image and the same auxiliary outputs for the same scene."*
  This is **the pkg55-B' wavefront program wearing an addon mask.** The
  per-pass-buffer write, env-as-light, and per-domain upload that P5
  needs are *exactly* the infrastructure pkg55-B' is rebuilding
  (wavefront shade/terminate stages + SoA per-domain state). Standing up
  a parallel GPU pass/upload subsystem in the megakernel addon now would
  (a) duplicate work, (b) almost certainly conflict with the wavefront
  branch, and (c) be deleted in pkg55 Phase C. So **P5 is acknowledged
  and deferred** with a cheap honesty guard here; its real resolution is
  scheduled into pkg55-B' (BUG-11 ≡ pkg85-D; BUG-02/10 ⇒ shade/terminate
  must write the pass buffers `get_render_pass_buffer` reads on CPU;
  BUG-12 ⇒ SoA per-domain upload mirroring P2's CPU contract).

The collapse proof (PR #300 §3): closing P2 fully fixes BUG-04, BUG-05
(they share `_apply_depsgraph_updates` and the test surface — do them
together). For P5 the symptoms are not fixed but converted from "silent
wrong/black" to "explicitly gated/labelled," which is the correct interim
per the owner's triage-only constraint and the pkg55-B' overlap.

Per PR #300 §7 item 3, the P2 reconcile-then-upload work + the P5
honesty guard are recommended as one package. Filed here as pkg96. The
owner's Round-10 ruling makes this **concurrent with pkg95 and with
pkg55-B' Session 3**, depending only on pkg94.

---

## Reference

- First-principles plan: `.astroray_plan/docs/addon-remediation-first-principles-plan-2026-05-16.md`
  (PR #300) — §2 P2 & P5 (formal/efficient/final cause; P5's pkg55-B'
  overlap stated explicitly), §3 collapse table (P2, P5 rows), §4
  Stage 3 (P2 work + P5 guard, dependency on Stage 1, P2 independent of
  pkg55-B', P5 must NOT be implemented here), §5 the P5/pkg55-B' overlap
  and recommended sequencing, §9 the owner focusing question on the
  guard's behavior — **resolved (Round-10 review): notice, no
  auto-route** (see Key design decision 3).
- Triage: `.astroray_plan/docs/blender-addon-bug-triage-2026-05-15.md`
  (PR #295) — BUG-04 (RC-3, World re-parse only on full sync), BUG-05
  (RC-3, `device_mode` classified as `accumulation_only`, never
  reconfigures backend), Cluster B / BUG-02/10/11 (RC-2, GPU runs no
  Pass plugins, world as miss-color), BUG-12 (RC-4, GPU `render()`
  unconditional full re-upload), §7 the focusing question on whether GPU
  pass/AOV parity is a near-term release requirement.
- `blender_addon/__init__.py` — `_apply_depsgraph_updates`
  (L1158–1237); `_classify_depsgraph_update` (`environment` @ L1134,
  `accumulation_only` @ L1142–1143); device-uploader calls L1222–1225;
  the idle/accumulation-reset return L1216–1220;
  `_configure_backend_for_context` / `set_use_gpu` (L1287);
  `_sync_viewport_scene` (L1284/L1287); `setup_world` (L3352/L3429);
  `get_render_pass_buffer` consumers (L1117–1209 binding side).
- `module/blender_module.cpp` — `getRenderPassBuffer` (L1117–1209;
  reads CPU-populated `camera->*Buffer`); GPU `render()` branch
  (L867–874, unconditional `buildAcceleration()+uploadScene()
  +uploadEnvironmentMap()`).
- pkg55-B' spec: `.astroray_plan/packages/pkg55-wavefront-soa-refactor.md`
  — where P5's *real* close lands (Phase-B' named gates BUG-02/10/12 +
  BUG-11 ≡ pkg85-D), per the pkg55 spec edits filed alongside this
  package.
- pkg85-D spec: `.astroray_plan/packages/pkg85-D-hdri-world-only-ssim-parity.md`
  — pkg85-D's SSIM gate (done, PR #283, SSIM 0.9793) validates the
  world-as-light invariant only on an **env-map-only, no-geometry** scene;
  the geometry-bearing BUG-11 witness ("diffuse sphere, grey world, no
  lights, not-black") is **deferred** to a named pkg55-B' Phase-B/C parity
  gate and is **not** yet covered on main. Until that gate lands, **this
  package's (pkg96) world-only-on-GPU honesty guard is the only
  user-facing protection for BUG-11** — it is the safety net, not a
  redundant check.

## Prerequisites

- [ ] **pkg94 merged** — P2 is unverifiable while P1 masks it (a stale
      module throws before the dispatcher path is reached). This is *the*
      reason pkg94 is Round-10 first.
- [ ] Build passes on main.
- [ ] §9 P5-guard behavior — **decided (Round-10 review): show a clear,
      specific notice; do NOT auto-route to CPU.** Implement exactly the
      notice (Key design decision 3); the "auto-route / default if
      unspecified" option is removed.

## Specification

### Key design decisions

1. **P2: reconcile-then-upload, in the one dispatcher.** In
   `_apply_depsgraph_updates`, give each domain a *reconcile* step
   *before* the device upload: a World update re-runs the world-tree
   parse (`setup_world`-equivalent) before `upload_environment`;
   backend-affecting Scene props (`device_mode`) get a **real domain**
   that calls `_configure_backend_for_context` instead of classifying as
   `accumulation_only`. Both edits live in the one dispatcher and share
   the test surface — do them together. *Rationale:* PR #300 §4 Stage 3;
   the bug is the contract ("push device state") not a missing buffer.
2. **P2 is independent of pkg55-B'.** It is a CPU-path Python dispatcher
   change; zero overlap with the wavefront SoA/CUDA track. It can land
   concurrently with any pkg55-B' session.
3. **P5 guard is UX-only — the architecture is NOT built here; the
   behavior is a NOTICE, never a silent backend switch.** *Decided
   (Round-10 review, resolving the §9 fork):* when `device_mode` resolves
   to GPU and the scene requests AOV / denoise / compositor passes or is
   world-only-diffuse-lit, the addon shows a **clear, specific notice**
   that the feature is **CPU-only** and the GPU backend will **not**
   produce it (e.g. "AOV / denoise / world-as-light passes are CPU-only
   pending the pkg55-B' wavefront pass pipeline — switch the backend to
   CPU to get this output"). It does **NOT** silently auto-route the
   render to CPU and does **NOT** change the backend behind the user's
   back. An honest notice with no hidden behavior change is the simpler,
   non-surprising contract (CLAUDE.md Simplicity First); a silent
   auto-route would mask which backend actually ran. **No GPU kernel
   work. No parallel megakernel pass/upload path.** *Rationale:* PR #300
   §5 — the wavefront pipeline is already building exactly that
   infrastructure; a parallel implementation is duplicate work deleted in
   Phase C.
4. **P5's real close is scheduled into pkg55-B', not here.** BUG-11 ≡
   pkg85-D: pkg85-D validates the world-as-light invariant only on an
   **env-map-only, no-geometry** scene (done, PR #283); the
   geometry-bearing BUG-11 witness is a **deferred** named pkg55-B'
   Phase-B/C parity gate, **not** yet covered on main — this pkg96 notice
   is its only user-facing protection until that gate lands. BUG-02/10
   become
   pkg55-B' shade/terminate-stage deliverables (the wavefront stages must
   write the pass buffers `get_render_pass_buffer` already reads on CPU);
   BUG-12 becomes a pkg55-B' SoA-per-domain-upload co-design note. These
   are recorded as named gates by the pkg55 + pkg85-D spec edits filed
   alongside this package — pkg96 only *guards* P5, it does not own it.
5. **Surgical, CPU-path only.** No GPU kernel, no SoA, no megakernel.
   P2 + a UX guard. Nothing speculative.

### Files to modify

| File | What changes |
|---|---|
| `blender_addon/__init__.py` | **P2:** `_apply_depsgraph_updates` gains a per-domain *reconcile* step before the device upload — World update re-parses the world tree (`setup_world`-equivalent) before `upload_environment`; `device_mode` (and other backend-affecting Scene props) get a real domain in `_classify_depsgraph_update` that routes to `_configure_backend_for_context` instead of `accumulation_only`. **P5 guard:** when GPU is active and the scene requests AOV/denoise/compositor passes or is world-only-lit, surface the non-crashing notice (or auto-route to CPU per the owner's §9 decision). |

### Files to create

| File | Purpose |
|---|---|
| `tests/test_pkg96_reconcile_then_upload.py` | (1) **P2/BUG-04:** simulate a World node-tree edit → the dispatcher re-parses the world (background color reaches the engine) without an unrelated edit forcing a full sync; (2) **P2/BUG-05:** simulate a `device_mode` Scene change → the dispatcher routes to the backend-reconfigure path (not `accumulation_only`/`idle`), so the backend switches without a full re-sync; (3) **P5 guard:** with GPU active and an AOV/denoise/world-only scene, the guard notice is surfaced (or the pass is routed to CPU per the owner's choice) and no silent black/wrong image is presented as correct. |

## Acceptance criteria

- [ ] **P2/BUG-04:** editing world color in the rendered viewport updates
      the image with no unrelated edit (the World domain re-parses before
      `upload_environment`).
- [ ] **P2/BUG-05:** switching CPU/GPU in the rendered viewport switches
      the backend without leaving rendered mode (`device_mode` has a real
      domain calling `_configure_backend_for_context`).
- [ ] **P5 guard:** with GPU selected, an AOV/denoise/world-only-diffuse
      scene shows the specific CPU-only notice text, and the test asserts
      (a) the notice text appears and (b) **no silent backend switch
      occurs** (the render still runs on the GPU backend the user
      selected; it is not silently re-routed to CPU) — never a black/wrong
      image presented as if correct. **No GPU kernel code added.**
- [ ] All existing tests still pass; no regressions; the diff is the one
      dispatcher + the UX guard only (no GPU/SoA/megakernel lines).

## Non-goals

- Do **not** implement P5's GPU architecture (per-pass buffers on GPU,
  env-as-light NEE/indirect, incremental GPU upload). That is pkg55-B'
  Phase-B/C work; building it here is duplicate and deleted in Phase C.
  Only the cheap honesty guard ships in pkg96.
- Do **not** "fix" the *transform-coarseness* half of BUG-03 (full BVH
  rebuild — no per-object id map). Intentional pkg56 Phase-C limitation;
  document, do not fix.
- Do **not** touch the GPU `render()` branch, `cuda_renderer.cu`, or any
  CUDA kernel. P5's BUG-12 is a pkg55-B' SoA co-design item, not a
  megakernel patch.
- Do **not** generalize the dispatcher into a domain framework. Add the
  reconcile step + the `device_mode` domain; nothing speculative.
- Do **not** modify pkg85-D or the pkg55 spec from this package — those
  edits are filed as separate doc deliverables alongside pkg96 (the
  pkg55 named-gate cross-refs + the pkg85-D BUG-11 section).

## Progress

- [x] **pkg94 merged** (prerequisite).
- [x] P2: per-domain reconcile step added to `_apply_depsgraph_updates`
      (World re-parse before `upload_environment`).
- [x] P2: `device_mode` real domain → `_configure_backend_for_context`
      (no longer `accumulation_only`).
- [x] P5 guard implemented (decided behavior: specific CPU-only notice,
      no silent backend switch).
- [x] `tests/test_pkg96_reconcile_then_upload.py` written + passing.
- [ ] CI green; no regressions.

## Lessons

*(Fill in after the package is done.)*

P2 is the addon's real correctness defect once P1's noise is removed:
the incremental dispatcher was a *device-upload* contract masquerading
as a *scene-sync* contract. The cost of conflating P5 into this package
would have been a throwaway GPU subsystem deleted in pkg55 Phase C; the
correct posture (PR #300 §5) is a cheap honesty guard now and the real
GPU parity folded into pkg55-B' as named acceptance gates.

---

## Track routing / acceptance gate

- **Track A.** Addon Python; CPU-path only. No GPU / hardware-verifier
  pass required (the P5 guard adds **no** GPU code); acceptance gate is
  the pytest above plus a manual Blender smoke note in the PR (world
  color updates live; CPU/GPU switch is live; GPU AOV scene shows the
  guard).
- **Round-10 sequencing:** **depends on pkg94** (verifiability — P1
  masks P2). Runs **concurrently with pkg95** (independent — same file,
  different defect surfaces; coordinate edits, no logical dependency) and
  **concurrently with, and independent of, pkg55-B' Session 3** (zero
  file contention — addon Python vs CPU wavefront sources). P5's real
  close is tracked by the pkg55-B' spec edits, not by this package.
- **Acceptance gate (one line):** world-color and CPU/GPU-switch edits
  take effect live in the rendered viewport without a full re-sync, and a
  GPU AOV/denoise/world-only-diffuse scene shows the specific CPU-only
  notice text with **no silent backend switch** (the render stays on the
  user-selected GPU backend) instead of a silent black/wrong image — with
  zero GPU kernel code added.

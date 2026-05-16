# Blender Addon Bug Triage + Root-Cause Analysis

**Date:** 2026-05-15
**Author:** Architect (analysis-only pass — NO code changed)
**Scope:** 17 owner-reported symptoms against the installed addon at
`%APPDATA%\Blender Foundation\Blender\5.1\extensions\user_default\astroray\`.
**Status:** Triage + root-cause. Nothing fixed. Remediation is a *plan*.

> Read this top-to-bottom once. The single most important finding is in
> §1 (the upload_* cluster is **not** a stale install — it is a
> *stale-loaded-module* artifact, which changes the remediation). The
> second most important is §4: the highest-leverage *real* code defect.

---

## 0. Classification key

Each bug is tagged with one of:

- **(a)** addon Python logic bug
- **(b)** C++ binding / kernel bug
- **(c)** GPU-path-specific gap (CPU correct, GPU missing the feature)
- **(d)** build / packaging / stale-install / stale-loaded-module artifact
- **(e)** intended / not-yet-implemented (works as currently designed)
- **(f)** UX / docs gap

Severity: **crash** / **functional** / **cosmetic** / **UX**.

---

## 1. The decisive packaging finding (resolves the upload_* cluster)

The disambiguation that the brief asked for, settled with evidence.

**Hashes (SHA256), measured this session:**

| Artifact | Size | mtime | SHA256 (prefix) |
|---|---|---|---|
| `build_blender_addon_tcnn/astroray.cp313-win_amd64.pyd` | 46 079 488 | 2026-05-15 21:59 | `A59EAAAC…` |
| `dist/astroray/astroray.cp313-win_amd64.pyd` | 46 079 488 | 2026-05-15 21:59 | `A59EAAAC…` |
| **INSTALLED** `…\user_default\astroray\…pyd` | 46 079 488 | 2026-05-15 22:46 | `A59EAAAC…` |
| `…\user_default\.~stale~0002\…pyd` | 45 274 112 | 2026-05-10 17:22 | `86BF1DBA…` |
| `…\user_default\.~stale~0001\…pyd` | 2 411 520 | 2026-05-03 20:54 | `2D840117…` |

- The **installed `.pyd` is byte-identical** (full SHA256 match) to the
  freshly-built `build_blender_addon_tcnn` / staged `dist/` module.
- The **installed `__init__.py` is byte-identical** to the repo's current
  `blender_addon/__init__.py` (`9123C260…`).
- The installed file's `22:46` mtime is merely the *file-copy* timestamp
  of the install step, not a different build.

So the install on disk is **current and correct**. The upload_* methods
*do* exist in it (`module/blender_module.cpp:1684-1717` defines
`upload_geometry/upload_materials/upload_lights/upload_environment/
upload_scene/update_object_transform` on the single
`py::class_<PyRenderer>(m, "Renderer")` at L1556; there is exactly one
Renderer class).

**But there are two `.~stale~NNNN` shadow directories.** Blender's
extension installer creates `.~stale~NNNN` when it *cannot overwrite a
locked file* — i.e. when Blender still has the old `.pyd` memory-mapped
because the addon was loaded. Git history pins the timeline:

- `upload_environment`/`uploadEnvironment` etc. first appear in
  **pkg56-B (PR #229), 2026-05-10** (`git log -S "uploadEnvironment"`).
- `_apply_depsgraph_updates` (the caller at `__init__.py:1222-1225`)
  landed in **pkg56-C (PR #233), 2026-05-10**.
- `.~stale~0001` = a **2026-05-03** MinGW build (predates pkg56-B → has
  *no* upload_* symbols, only `upload_scene` + `load_environment_map`).
- `.~stale~0002` = a **2026-05-10** build (borderline pkg56-B day).

**Root cause of the upload_* AttributeError cluster (bugs 1, 3, 7):**
classification **(d)** — a *stale loaded module*, NOT a stale install and
NOT a missing symbol in the shipped binary. The owner re-installed the
addon while Blender was running; the new `.pyd` landed on disk but the
running Blender process kept the *old* (pre-pkg56-B) module mapped. Every
`AttributeError: 'astroray.Renderer' object has no attribute
'upload_environment'` (with the `Did you mean: load_environment_map?`
hint — exactly the pre-pkg56-B class surface) was emitted by that stale
in-memory module. A full Blender restart after install would clear all
three of these.

**Remediation is therefore packaging/process, not code:** the install
step must (1) refuse to stage over a `.pyd` while Blender holds it, or
(2) the owner must fully quit Blender before re-installing, or (3) the
build/install script should detect `.~stale~` directories and surface a
loud "RESTART BLENDER — old module still loaded" warning. Add a
build-stamp/version assert the addon prints on register so a stale module
is *immediately* visible (`astroray.__build__` vs the addon's expected
hash). The `.~stale~` dirs should also be garbage-collected.

> Caveat: bug 4 (world color) and bug 5 (device switch) have an
> *independent real defect* underneath. They only *appear* in the same
> cluster because the stale module throws first. On a correctly-loaded
> module they still misbehave. See §2.

---

## 2. Per-bug triage

### Cluster A — Stale-loaded-module AttributeErrors (d)

#### BUG-01 — HDRI World → `AttributeError: no attribute 'upload_environment'`
- **Symptom:** Image Texture → World Output, error at `__init__.py:1409
  view_update → :1222`.
- **Root cause:** §1. The incremental dispatcher
  `_apply_depsgraph_updates` (`:1222`) calls `renderer.upload_environment()`
  on a World update. That method exists in the shipped binary; the running
  Blender had the pre-pkg56-B module loaded. Note the *full-sync* path is
  correct — `setup_world` (`:3429`) calls `renderer.load_environment_map(...)`,
  which is why the hint says "Did you mean load_environment_map?".
- **Class:** (d). **Severity:** crash (per-feature). **Group:** Cluster A.

#### BUG-03 — Move object in render mode → `no attribute 'upload_geometry'` (`:1225`)
- **Root cause:** Same stale-module mechanism. `_apply_depsgraph_updates`
  routes a transform/geometry update to `renderer.upload_geometry()`
  (`:1225`). Secondary (real) effect once the binary is correct: a
  *transform-only* edit with no cached object-id map promotes to a full
  geometry rebuild (`:1196-1204`, `_renderer_object_id_for` returns None
  by design — Phase C ships without a per-object id tracker). So position
  *does* update on the correct binary, but via a full BVH rebuild, and
  "doesn't update until you toggle render mode" is the stale-module
  exception swallowing the dispatch.
- **Class:** (d) primary; (e) secondary (transform path intentionally
  coarse). **Severity:** crash. **Group:** Cluster A.

#### BUG-07 — Update materials in render mode → `no attribute 'upload_materials'` (`:1223`)
- **Root cause:** Same stale-module mechanism (`:1223`
  `renderer.upload_materials()`).
- **Class:** (d). **Severity:** crash. **Group:** Cluster A.

### Cluster B — GPU has no pass / AOV / denoise / env-light execution (c)

This is an **architectural gap**, not three separate bugs.
`src/gpu/cuda_renderer.cu` `render()` / `renderMultiwavelength()`
(L545-614) compute a single combined `d_framebuffer` and `cudaMemcpy` it
back. Grep proves the CUDA renderer **never touches**
`camera->renderPassBuffers`, `depthBuffer`, `positionBuffer`,
`albedoBuffer`, or runs any `Pass` plugin (zero matches for
`renderPassBuffers|depthBuffer|albedo|AOV` in `cuda_renderer.cu`). Pass
plugins are CPU constructs invoked by the CPU integrator;
`getRenderPassBuffer` (`blender_module.cpp:1117-1209`) reads
CPU-populated `camera->*Buffer` vectors.

#### BUG-02 — GPU render passes: albedo/normal/depth show Combined; compositor passes BLACK
- **Root cause:** On GPU the AOV pass plugin never runs, so `pixels`
  (`__init__.py:1359`) is just the combined framebuffer → albedo/normal/
  depth "show the combined image". For compositor passes,
  `get_render_pass_buffer(name)` reads `camera->renderPassBuffers[idx]`
  which the GPU never filled → all-zero → **black**. CPU works because the
  CPU integrator runs the pass plugins.
- **Class:** (c). **Severity:** functional. **Group:** Cluster B.

#### BUG-10 — Viewport denoise toggle no-op on GPU; works on CPU
- **Root cause:** `viewport_oidn` adds a denoiser *pass*
  (`__init__.py:1350-1353`). Same as BUG-02: GPU never executes pass
  plugins, so the denoise pass is silently inert. CPU integrator runs it.
- **Class:** (c). **Severity:** functional. **Group:** Cluster B.

#### BUG-11 — Principled diffuse renders black against world/background but reacts to light objects
- **Root cause (hypothesis, evidence-cited):** GPU kernel receives
  `backgroundColor`/`hasBackgroundColor` (`cuda_renderer.cu:48,115,241,
  551`) and uses it as the **camera-ray miss color** only. It does not
  appear to treat a solid world as an **environment light** contributing
  to BSDF illumination (NEE / indirect). So a diffuse surface lit only by
  the world goes black, while explicit light objects still illuminate it.
  Strongly corroborated by **pkg85-D** ("HDRI world-only SSIM parity bug")
  having been filed for exactly this GPU world-as-light gap.
- **Class:** (c) (GPU env-as-light), shares the world-lighting model with
  Cluster B. **Severity:** functional. **Group:** Cluster B.
- **Disambiguating experiment:** render a single diffuse sphere, solid
  grey world, no lights, CPU vs GPU. CPU lit / GPU black confirms.

### Cluster C — Incremental depsgraph dispatcher too narrow (a)

`_apply_depsgraph_updates` (`__init__.py:1158-1237`) only re-pushes the
*device upload* for a domain; it never re-*parses* the Blender state, and
it has no domain for several change types. `_configure_backend_for_context`
and `setup_world` run only on the **full-sync / fallback** path
(`_sync_viewport_scene`, `:1287/:1284`).

#### BUG-04 — Background color didn't update until a material was changed
- **Root cause:** A World node-tree edit → `_classify_depsgraph_update`
  returns `{'environment': True}` (`:1134`) → dispatcher calls
  `renderer.upload_environment()` (`:1222`). But `upload_environment` is a
  *device re-upload of already-parsed env state* — it never re-walks the
  world node tree. Only `setup_world` (`:3352`) re-reads the Background
  node, and that runs only on full sync. So the new color is ignored until
  a fallback/full-sync is forced (e.g. the material edit that the owner
  observed). On the stale module this is masked (upload_environment throws
  first), so it is a *real, independent* defect.
- **Class:** (a). **Severity:** functional. **Group:** Cluster C.

#### BUG-05 — Selecting CPU in render mode doesn't take effect until exit/re-enter
- **Root cause:** `device_mode` is a Scene property. A Scene update →
  `_classify_depsgraph_update` returns `{'accumulation_only': True}`
  (`:1142-1143`) → dispatcher resets accumulation and returns `'idle'`
  (`:1216-1220`). It never calls `_configure_backend_for_context`
  (`renderer.set_use_gpu(...)`), which runs only in `_sync_viewport_scene`
  (`:1287`). So the backend is not switched until a full re-sync (toggle
  out/in of rendered mode).
- **Class:** (a). **Severity:** functional. **Group:** Cluster C.

### Cluster D — GPU re-uploads the whole scene every viewport sample (c)

#### BUG-12 — "[CUDA] Scene uploaded" + "render complete at 1 spp" reprints every viewport sample
- **Root cause:** `blender_module.cpp:867-872` (the `render()` GPU branch)
  unconditionally runs `renderer.buildAcceleration()` +
  `cudaRenderer->uploadScene(...)` + `uploadEnvironmentMap(...)` **every
  call**. The progressive viewport calls `render()` once per sample-chunk
  (`__init__.py:1359`), so the entire scene is re-uploaded per sample →
  the repeated print. F12 calls `render()` once at full spp → one upload →
  "blazing fast". The pkg56-B incremental uploaders exist but the GPU
  `render()` path bypasses them and always full-uploads.
- **Class:** (c) (GPU-path inefficiency). **Severity:** functional/perf
  (owner not blocked, but it defeats the persistent-viewport design).
  **Group:** Cluster D (relates to Cluster C — both are "the incremental
  pipeline is bypassed").

### Cluster E — Material / node lowering

#### BUG-13 — IR/UV: profile nodes → Response → Output ⇒ "0 profiles uploaded" (CPU & GPU)
- **Root cause (definitive, from reading):** `__init__.py:1865`:
  ```python
  'profile': self._astroray_read_profile(node, mat) if False else '',
  ```
  The IR/UV Response node's spectral profile is **hard-disabled by
  `if False`**. `_astroray_ir_uv_spec` always emits `profile: ''`. Then
  `_create_astroray_material` `kind == 'astroray_ir_uv'` (`:1909-1915`)
  creates a *plain visible-range Disney* `[r,r,r]` and **never calls
  `set_material_spectral_profile`**. The only code that sets a profile
  (`_apply_spectral_profile`, `:1709`) reads the per-material *dropdown*
  `mat.custom_raytracer.spectral_profile`, not the node graph — and the
  Astroray-native output path (`:1742`) does wrap in
  `_apply_spectral_profile`, but with the node profile dropped and the
  dropdown unset there is nothing to upload. Outside the visible band the
  material renders black; the C++ logs "0 profiles" (the count comes from
  `cuda_renderer.cu:276`/`397`, but the CPU path is equally profile-less,
  hence "fails on CPU and GPU"). The L1853-1856 comment admits this is a
  deliberate stub ("a full multi-band response material is pkg-future
  work").
- **Class:** (e) intended-incomplete + (a) latent bug (the node is
  presented as functional in the UI but is wired to `if False`).
  **Severity:** functional. **Group:** Cluster E. *Cleanest single root
  cause in the report — one `if False` plus one missing
  `set_material_spectral_profile` call.*

#### BUG-14 — Glass color not applied at very low roughness (Principled glass & Glass BSDF)
- **Investigation:** `BSDF_GLASS` lowers to the *principled/disney* plugin
  with `base_color`→`albedo` (`__init__.py:2763-2767`; `createMaterial`
  `p.set("albedo", color)` `blender_module.cpp:274`; `disney.cpp:194`
  reads `albedo`). So the **key mapping is correct** — not the bug. In
  `disney.cpp::sample` the smooth/delta transmission branch
  (`disney.cpp:389-399`, gated by `roughness_ > kDeltaTransmissionRoughness`
  at L363) sets the transmitted `s.f = baseColor_ * (eta*eta)` — i.e. the
  color *is* applied, but as a **single-surface multiplicative tint** on
  the BTDF, not Beer-Lambert volume absorption through glass thickness.
  Cycles colored glass tints by absorption over path length; a thin, very
  smooth slab tinted once per crossing reads as "clear".
- **Root cause hypothesis:** colored glass is modelled as a weak
  single-surface BTDF tint instead of volumetric/Beer-Lambert absorption;
  the effect is perceptually negligible on thin low-roughness glass.
  Additionally the addon routes Glass through `principled` rather than the
  dedicated `dielectric`/`thin_glass` plugins that may carry absorption.
- **Class:** (a/b) material-model gap. **Severity:** functional (fidelity).
  **Group:** Cluster E.
- **Disambiguating experiment:** CPU render a colored glass *cube* (thick)
  vs a thin pane at roughness 0.0, compare to Cycles. If the thick cube
  tints but the pane doesn't, it confirms the single-surface-vs-absorption
  model gap rather than a dropped color.

#### BUG-16 — Principled Subsurface maybe not doing anything (owner unsure)
- **Status:** Could not root-cause from reading alone. Need to confirm
  whether `_principled_shader_spec` (`:2686+`) plumbs the Subsurface
  weight/radius into a closure the disney plugin consumes. Likely either
  unmapped or mapped to a no-op.
- **Class:** (a) or (e) — TBD. **Severity:** functional (subtle).
  **Group:** Cluster E.
- **Disambiguating experiment:** render a Suzanne with Subsurface 0 vs 1,
  diff the images; if identical, the param is dropped.

### Cluster F — Camera

#### BUG-08 — Object-mode camera not aligned with render camera (camera view & orbit)
- **Root cause:** Two divergent FOV derivations. `_apply_camera`
  (`:1639`, used by F12 / scene-camera / CAMERA-view) uses the real
  camera datablock via `_compute_vfov_degrees` (real `sensor_width`/
  `sensor_height`/`sensor_fit`, default 36 mm). But the free-orbit
  (PERSP/ORTHO) viewport path `_setup_viewport_camera` (`:1547-1554`)
  **hardcodes `sensor_width = 32.0`** and derives `hfov` from
  `space_data.lens`, ignoring lens shift and `view_camera_offset`. The
  32 mm-vs-datablock mismatch and the re-derived (rather than
  Blender-native) projection make the rendered framing disagree with
  Blender's own viewport/overlay in both modes.
- **Class:** (a). **Severity:** functional. **Group:** Cluster F.
- **Best fix direction:** derive the frustum from `rv3d.window_matrix` /
  `perspective_matrix` instead of re-deriving FOV from a guessed sensor.

### Cluster G — Custom node graph survival

#### BUG-09 — Astroray Output (shader) node doesn't seem to work
- **Root cause hypothesis:** `convert_node_material` runs over the
  **inlined/flattened** tree from `material.inline_shader_nodes()`
  (docstring at `:1698-1704`). Detection of the native output node
  (`:1737-1740`, `bl_idname == 'AstrorayOutputNode'`) and the IR/UV /
  Sellmeier / NRC nodes (`:1789-1804`) all key off custom
  `bpy.types.ShaderNode` subclasses (`blender_addon/nodes/__init__.py:163`).
  `inline_shader_nodes()` is a Cycles-oriented flattener; custom non-Cycles
  node types may be stripped or not survive inlining, so the `next(...)`
  finds nothing and the code falls through to the standard
  `OUTPUT_MATERIAL` path → the Astroray node "doesn't work".
- **Class:** (a) (likely) — needs runtime confirmation.
  **Severity:** functional. **Group:** Cluster G (also explains why
  BUG-13's node path is doubly dead — even if `if False` were fixed, the
  node may not survive flattening).
- **Disambiguating experiment:** in Blender, after building a tree with
  `AstrorayOutputNode`, print
  `[n.bl_idname for n in mat.inline_shader_nodes().nodes]` and check
  whether `AstrorayOutputNode` is present.

### Cluster H — Crash in preview operator

#### BUG-15 — Preview-render button → `TypeError: bpy_struct.__new__(struct): expected a single argument`
- **Root cause (definitive):** `_create_live_preview_material`
  (`__init__.py:674-678`) does `engine = CustomRaytracerRenderEngine()`
  at L676. `RenderEngine` is a C-backed `bpy_struct`; the class comment at
  L706-709 explicitly says they deliberately do **not** override
  `__init__` because Blender forbids constructing a `RenderEngine`
  directly — yet this code instantiates one with no args, which Blender
  rejects with exactly this `TypeError`. The engine instance is only
  wanted to reach `convert_node_material` / `convert_volume_node`.
- **Class:** (a). **Severity:** crash. **Group:** Cluster H (standalone).
- **Fix direction:** factor the node-conversion methods so the preview
  path can call them without constructing a `RenderEngine` (e.g. a
  module-level helper or a lightweight non-RenderEngine converter object).

### Cluster I — Expected / not-yet-implemented

#### BUG-06 — GPU render mode doesn't use spectral (owner unsure if intended)
- **Finding:** Not strictly true at the C++ level —
  `blender_module.cpp:880-896` routes `path_tracer` /
  `multiwavelength_path_tracer` on GPU to
  `cudaRenderer->renderMultiwavelength(...)` (the pkg54 spectral-band
  megakernel). In the **visible band** with `useLum=false` the spectral
  GPU output is close to the RGB look, so the difference is hard to
  perceive — likely why it "doesn't seem spectral". Whether the *viewport*
  selects a spectral integrator depends on `_effective_integrator_name`
  and `device_mode` gating (`__init__.py:342-389`).
- **Class:** (e) (works as designed; perceptual). **Severity:** UX / low.
  **Group:** Cluster I. **Experiment:** GPU render with an IR-band
  wavelength range vs visible; spectral effect should be obvious outside
  visible (and is gated by BUG-13 for IR materials).

#### BUG-17 — Unclear how to set up caustics & dispersion shader nodes (CPU)
- **Root cause:** Pure documentation / UX. pkg64 caustics is CPU-only
  (per NEXT_STAGE_REPORT). The node UX for the
  Sellmeier/dispersion/caustics path exists
  (`AstrorayShaderNodeSellmeierGlass`, `_astroray_sellmeier_spec`) but is
  undocumented for end users.
- **Class:** (f). **Severity:** UX. **Group:** Cluster I.

---

## 3. Shared root causes (the few defects behind the many symptoms)

| Root cause | Symptoms resolved | Class |
|---|---|---|
| **RC-1 — Stale *loaded* module (Blender held old `.pyd`; `.~stale~` proves the lock).** Not a stale install — install is byte-correct. | BUG-01, BUG-03 (primary), BUG-07 | (d) |
| **RC-2 — GPU render path executes no Pass/AOV/denoise plugins and treats world as miss-color, not env-light.** Single `d_framebuffer` copied back. | BUG-02, BUG-10, BUG-11 | (c) |
| **RC-3 — Incremental depsgraph dispatcher re-uploads device state but never re-parses Blender state and lacks domains for World re-read & device_mode.** | BUG-04, BUG-05 (and the BUG-03 transform-coarseness) | (a) |
| **RC-4 — GPU `render()` unconditionally rebuilds BVH + re-uploads the whole scene every call.** | BUG-12 | (c) |
| **RC-5 — IR/UV node profile hard-disabled (`if False`) + native-node path never calls `set_material_spectral_profile` for the IR/UV kind.** | BUG-13 (and the spectral half of BUG-06) | (e)+(a) |
| **RC-6 — Custom ShaderNode subclasses may not survive `inline_shader_nodes()` flattening.** | BUG-09 (and compounds BUG-13) | (a) |
| **RC-7 — Two divergent camera-FOV derivations (datablock 36 mm vs hardcoded 32 mm free-view), re-derived instead of Blender-native projection.** | BUG-08 | (a) |
| **RC-8 — Direct `RenderEngine()` construction in the preview path.** | BUG-15 | (a) |
| **RC-9 — Single-surface BTDF tint instead of volumetric absorption for colored glass.** | BUG-14 | (a/b) |

---

## 4. Separation: real bugs vs artifacts vs not-yet-implemented

**Stale-loaded-module / packaging artifacts (NOT code defects):**
BUG-01, BUG-07, and the *crash* of BUG-03. Fix = install/process +
restart-detection. A Blender restart after install would have prevented
all three. **Do not "fix" these in C++ or Python.**

**Real code bugs (fix these):**
- RC-8 / BUG-15 — crash, trivially isolated, highest fix-value-per-effort.
- RC-5 / BUG-13 — one `if False` + one missing call; cleanest real defect.
- RC-3 / BUG-04, BUG-05 — incremental dispatcher correctness.
- RC-7 / BUG-08 — camera alignment (Blender-native projection).
- RC-2 / BUG-02, BUG-10, BUG-11 — large GPU architectural gap (this is
  the pkg55-B'/pkg85-D territory; expensive).
- RC-4 / BUG-12 — GPU per-sample re-upload (overlaps RC-2/RC-3 work).
- RC-9 / BUG-14, RC-6 / BUG-09 — needs a runtime probe before scoping.

**Not-yet-implemented / works-as-designed (document, don't "fix"):**
BUG-06 (spectral GPU exists; perceptual), BUG-17 (docs), the
transform-coarseness half of BUG-03 (Phase C intentionally coarse),
the IR/UV multi-band closure half of BUG-13 (pkg-future).

**Need a runtime experiment before classification:**
BUG-09 (does `inline_shader_nodes()` keep custom nodes?), BUG-11
(CPU-vs-GPU world-only diffuse), BUG-14 (thick cube vs thin pane vs
Cycles), BUG-16 (Subsurface 0 vs 1 diff).

---

## 5. Recommended systematic remediation sequence (PLAN — not implemented)

Ordered for maximum leverage and respecting dependencies.

**Phase 0 — Eliminate the artifact noise (do first, ~½ day, no code-logic risk).**
1. Add a build-stamp the addon prints on `register()` and an assert that
   `astroray.__build__`/hash matches the staged `build_report.json`; if
   mismatch, raise a visible "RESTART BLENDER — stale module loaded".
2. Make the install script (a) refuse to overwrite a locked `.pyd` with a
   clear message, (b) GC `.~stale~NNNN`, (c) print "Quit Blender before
   reinstalling."
   → This makes BUG-01/03/07 stop reproducing and stops them masking
   BUG-04/05. **Without Phase 0, every later fix is unverifiable** because
   the owner may keep testing a stale module.

**Phase 1 — Cheap, high-value real bugs (independent, parallelizable).**
3. BUG-15 (RC-8): de-`RenderEngine()` the preview path. Self-contained,
   crash → fixed, no dependencies.
4. BUG-13 (RC-5): remove `if False`, thread the node profile through, and
   call `set_material_spectral_profile` in the `astroray_ir_uv` /
   native-output path. *Depends on a quick BUG-09 probe* (RC-6) — if
   custom nodes don't survive flattening, fix RC-6 first or the profile
   still won't reach the converter.
5. BUG-09 (RC-6) probe + fix if needed. Gates BUG-13 and any native-node
   feature.

**Phase 2 — Viewport correctness (RC-3 cluster).**
6. BUG-05 (RC-3): make `device_mode` (and other backend-affecting Scene
   props) force a backend reconfigure in the incremental path.
7. BUG-04 (RC-3): make a World update re-run `setup_world` (re-parse)
   before `upload_environment`, not just the device uploader.
   (6 and 7 share the dispatcher; do together.)

**Phase 3 — Camera (RC-7).**
8. BUG-08: replace both FOV derivations with a single Blender-native
   projection (`rv3d.window_matrix`) so viewport == F12 == Blender.

**Phase 4 — GPU architecture (RC-2 + RC-4) — largest, schedule with pkg55-B'/pkg85-D.**
9. GPU env-as-light (BUG-11) — overlaps the pkg85-D HDRI world-only
   parity work already filed; fold in.
10. GPU pass/AOV/denoise execution (BUG-02, BUG-10) — needs the GPU
    integrator to write `renderPassBuffers`/AOV buffers. Big.
11. GPU incremental upload (BUG-12) — only re-upload changed domains in
    the GPU `render()` path; naturally co-designed with #10 and RC-3.

**Phase 5 — Fidelity, after a runtime probe.**
12. BUG-14 (glass absorption), BUG-16 (subsurface) — scope after the
    experiments in §4. Likely route Glass to `dielectric`/`thin_glass`
    and add Beer-Lambert.

**Phase 6 — Docs.**
13. BUG-17, BUG-06 — user docs for caustics/dispersion node setup and a
    note that GPU is spectral but perceptually close in the visible band.

**Dependency summary:** Phase 0 gates *verification of everything*.
RC-6 (BUG-09) gates BUG-13. RC-2/RC-4 are co-designed and align with the
already-planned pkg55-B' / pkg85-D GPU work. Phases 1, 3 are independent
and parallelizable once Phase 0 lands.

---

## 6. Single highest-leverage recommendation

**Start with Phase 0 (stale-loaded-module guard), then BUG-13's `if False`
+ BUG-15's `RenderEngine()`.** Rationale: Phase 0 is the multiplier — it
removes the three loudest "crash" reports (BUG-01/03/07) *without code
risk*, and it un-masks the real BUG-04/05 so subsequent fixes are
verifiable at all. Right behind it, BUG-13 and BUG-15 are the two
*real* defects with the best fix-value-to-risk ratio: each is a one-to-few
line change, each currently presents as "feature totally broken / button
crashes", and neither depends on the expensive GPU-architecture work
(RC-2/RC-4) that should be sequenced with the already-planned
pkg55-B'/pkg85-D effort.

## 7. One focusing question for the owner

Before scoping Phase 4: is GPU pass/AOV/denoise parity (BUG-02/10/11) a
near-term release requirement, or is it acceptable to **gate AOV/denoise
to CPU and document the GPU limitation** until the pkg55-B' wavefront
shade-kernel work lands the infrastructure to write per-pass buffers on
GPU cheaply? The answer changes Phase 4 from "large new GPU subsystem
now" to "small UX guard now + fold into pkg55-B' later".

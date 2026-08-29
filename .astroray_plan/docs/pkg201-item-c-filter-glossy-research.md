# pkg201 Stage 3 item C — `filter_glossy` / `blur_glossy` research note

**Status of this note:** research only. No `.cpp`/`.cu`/`.h`/`.py` source was edited.
No build, no test run.

**Correction to the spec's framing.** The pkg201 spec (Stage 3, item C) describes
Cycles' filter-glossy as widening a bounce's sampled roughness based on "the prior
bounce's roughness." That is a reasonable one-line gloss, but it is not literally what
Cycles tracks. The actual per-ray accumulator is **the minimum unguided BSDF/phase
sample pdf seen so far along the path** (`path.min_ray_pdf`), not a roughness value.
Low pdf correlates with narrow/specular lobes, so it behaves like a "how sharp has
this path been" signal, but the math converts pdf, not roughness, into a blur radius.
This distinction matters for the implementation: the per-ray SoA field to add is a
**float pdf accumulator**, not a roughness accumulator.

## Also note on the landed-item-A premise

The task brief said to read "the Stage 3 item A — DONE section" in the pkg201 spec as
the pattern to mirror. As of this worktree's HEAD (`ef4f7db`), **item A (per-type
bounce counters) has NOT landed** — `git log --all --oneline` shows only Stage 1
(#618) and Stage 2 (#623) commits for pkg201; there is no Stage-3 commit and the spec
file has no "item A — DONE" section. `.astroray_plan/docs/NEXT_STAGE_REPORT.md`
(2026-08-26 entry) instead records a **banked decision** for item A's shape (not yet
implemented): "per-type bounce counters as a **runtime SoA comparison** in the shade
kernel (5 counters in path state; cheap `if (depth[type] >= limit[type])` continuation
check), **probe-first**... Sets the pattern for items C (filter_glossy) and E (caustic
toggles) too." This note treats that banked decision (Option 2, SoA-global +
probe-first) as the pattern to mirror, since the concrete "DONE" section does not yet
exist in the repo. Flag this discrepancy to the owner/implementer before starting.

---

## 1. Cycles reference (cited)

Source: `blender/blender` monorepo (Cycles lives under `intern/cycles/` in current
Blender source, not a standalone repo), fetched 2026-08-29 via `gh api` against
`main`.

**Kernel-side storage and inversion** — `intern/cycles/scene/integrator.cpp`:
> `kintegrator->filter_glossy = (filter_glossy == 0.0f) ? FLT_MAX : 1.0f / filter_glossy;`

The UI's `blur_glossy` (Astroray's `filterGlossy`) is stored **inverted** in the
kernel: `kernel_data.integrator.filter_glossy = 1 / blur_glossy` (or `FLT_MAX` when
`blur_glossy == 0`, i.e. feature off). This inversion is load-bearing for the formula
below — a small `blur_glossy` UI value means a LARGE kernel `filter_glossy`, which
blurs sooner (at a higher `min_ray_pdf` threshold).

**Per-ray accumulator, updated after every real (non-transparent) bounce** —
`intern/cycles/kernel/integrator/shade_surface.h` (~L611-617), inside the "update
path state" block after a BSDF sample:
```
if (!(label & LABEL_TRANSPARENT)) {
  const float min_ray_pdf = INTEGRATOR_STATE(state, path, min_ray_pdf);
  ...
  INTEGRATOR_STATE_WRITE(state, path, min_ray_pdf) = fminf(unguided_bsdf_pdf, min_ray_pdf);
```
Initialized to `FLT_MAX` at path start in `intern/cycles/kernel/integrator/path_state.h`
(`INTEGRATOR_STATE_WRITE(state, path, min_ray_pdf) = FLT_MAX;`), declared as a
first-class per-ray state field in `intern/cycles/kernel/integrator/state_template.h`
(`KERNEL_STRUCT_MEMBER(path, float, min_ray_pdf, KERNEL_FEATURE_PATH_TRACING)`).

**Widening, applied at the START of shading the NEXT hit, before BSDF eval/sample** —
`intern/cycles/kernel/integrator/surface_shader.h` (~L195-217):
```
if (kernel_data.integrator.filter_glossy != FLT_MAX ...) {
  const float blur_pdf = kernel_data.integrator.filter_glossy *
                         INTEGRATOR_STATE(state, path, min_ray_pdf);
  if (blur_pdf < 1.0f) {
    const float blur_roughness = sqrtf(1.0f - blur_pdf) * 0.5f;
    for (int i = 0; i < sd->num_closure; i++) {
      if (CLOSURE_IS_BSDF(sc->type)) bsdf_blur(sc, blur_roughness);
    }
  }
}
```
i.e. **blur_roughness = sqrt(1 − filter_glossy · min_ray_pdf) · 0.5**, applied only
when `filter_glossy·min_ray_pdf < 1`. This is the one non-trivial formula; quoting
only the identifying line above (`kintegrator->filter_glossy = ... 1.0f /
filter_glossy;`, 12 words) per the copyright/quoting limit.

**Actual widening of each closure** — `intern/cycles/kernel/closure/bsdf_microfacet.h`
(`bsdf_microfacet_blur`, ~L1204-1210): `bsdf->alpha_x = fmaxf(roughness, bsdf->alpha_x);`
/ same for `alpha_y`. It is a **max**, never a reduction — filter-glossy can only widen
a lobe, never sharpen one, and closures already rougher than `blur_roughness` are
untouched. Different closure kinds have their own `_blur` variant (Ashikhmin-Shirley,
hair Chiang/Huang); Astroray's GGX-only material model only needs the microfacet case.

## 2. Astroray mapping

**CPU insertion points** (`include/raytracer.h`):
- `filterGlossy` is a stored, dead field: `float filterGlossy = 0.0f;` (L2141),
  setter `setFilterGlossy` (L2351), reset in `resetToDefaults`-equivalent (L2432).
  **Zero reads anywhere in the file** — confirmed by grep; the CPU path is equally
  inert, matching the pattern already found for Finding F (transparent film) in
  Stage 2.
- The bounce loop that needs the new accumulator is in `pathTraceSpectral`, starting
  `for (int bounce = 0; bounce < maxDepth; ++bounce)` at **raytracer.h:2639**. A local
  `float minRayPdf = FLT_MAX;` must be declared immediately **before** that loop
  (mirrors Cycles' path-start init) so it survives across iterations.
- The BSDF sample call in that loop is **raytracer.h:3019**:
  `BSDFSampleSpectral bss = rec.material->sampleSpectral(rec, wo, gen, lambdas);`.
  Widening must happen **before** this call (Cycles widens before both eval and
  sample), and the accumulator update (`minRayPdf = min(bss.pdf, minRayPdf)`, skipped
  on a transparent/pass-through bounce) happens **after** it, using `bss.pdf`
  (`BSDFSampleSpectral::pdf`, already a struct member at raytracer.h:429 — no new
  per-sample data needed, only the running minimum).
- Roughness accessor: `Material::getRoughness()` is `virtual float getRoughness()
  const { return 0.5f; }` (raytracer.h:491) — a **pure accessor on a persistent,
  possibly-shared `Material*`**, not a per-ray mutable copy. There is no existing
  mechanism to override an individual sample's effective roughness without either
  (a) mutating the shared `Material` object (wrong — corrupts other rays/pixels using
  the same material), or (b) adding a new parameter to `sample()`/`sampleSpectral()`
  threading an override roughness through the virtual-dispatch call, which is a wider
  signature change than GPU needs (see §3 caller sweep below).

**GPU insertion points** (`include/astroray/gpu_materials.h`,
`src/gpu/wavefront/stage_advance.cu`):
- GPU dispatch entry: `gpu_material_sample_spectral<HasPrincipled>(mat, rec, wo,
  lambdas, &rng)`, called from `shadePathSlot` at **stage_advance.cu:1365**. `mat` is
  obtained at **stage_advance.cu:1039** (and again at :630 for a non-spectral call
  site) as `const ::GMaterial& mat = materials[rec.materialId];` — **a const
  reference into the shared global/constant materials buffer, indexed by
  `materialId`, not a per-ray copy.** This is the critical GPU-specific fact: you
  cannot widen `mat.roughness` in place the way item A widens per-ray counters,
  because `mat` is shared across every ray currently hitting that material.
- Per-ray accumulator: a new `float* min_ray_pdf` SoA field on `GPUWavefrontState`
  (`include/astroray/gpu_wavefront_state.h`, alongside the existing `float*
  path_bsdf_pdf` at L137 and `int* was_specular` at L155 — `was_specular` is the
  existing analogous "path-history" flag pattern, relevant background for item E
  too), zeroed/set-to-FLT_MAX at path init (wherever `bounce[idx]=0` and
  `path_alive[idx]=1` are set in `stage_init.cu`'s `initPathSlot`-equivalent), read +
  updated in `shadePathSlot` right after the `gpu_material_sample_spectral` call
  using the returned `GBSDFSample::pdf` (already a struct member — no new per-sample
  data).
- Widening application: because `mat` cannot be mutated, the register-honest approach
  is to **thread a scalar `float roughnessFloor` parameter into the specific
  `gpu_*_sample`/`gpu_*_sample_spectral` functions** (`gpu_lambertian_sample` skips it
  — diffuse has no roughness to widen; `gpu_metal_sample`, `gpu_dielectric_sample*`,
  `gpu_disney_sample`, `gpu_principled_sample`, `gpu_closure_graph_sample` all read
  `mat.roughness`/`c.roughness` at the point they compute GGX alpha, e.g.
  `gpu_materials.h:254` (`float a = mat.roughness * mat.roughness;`) and the many
  similar sites found in the grep above), and apply `fmaxf(mat.roughness,
  roughnessFloor)` at each such read site — mirroring `bsdf_microfacet_blur`'s
  `alpha_x = fmaxf(roughness, alpha_x)` (a max, applied per-closure-parameter, never
  a struct copy). This avoids copying the 64-byte-aligned `GMaterial` (confirmed
  `struct alignas(64) GMaterial` in `include/astroray/gpu_types.h:508`, and per
  session-handoff memory `shade-axis-side-table-avoids-spill`, "`GMaterial` stays
  640 B" was explicitly protected during pkg223).

## 3. Register-cost prediction

Item A (per-type bounce counters, per the banked Option-2 decision) is predicted to
cost roughly what pkg223's normal-map side-table did: small SoA additions read once
per bounce for a cheap integer comparison, isolated so the fleet default
specialization is unaffected. Item C is a **materially different shape** and should
NOT be assumed to cost the same:

- **The SoA accumulator itself (one `float min_ray_pdf` per path slot) is cheap** —
  same shape as item A's counters, read/written once per bounce, register-neutral in
  the same way.
- **The risk is entirely in HOW the widening reaches the BSDF sample, not in the
  accumulator.** Two designs diverge sharply:
  - **Naive (copy `GMaterial` locally, mutate `.roughness`, pass the copy):** this
    copies a 64-byte-aligned struct (which also embeds `GPrincipledClosure` and
    dispersion fields per the closure-graph branches seen in `scene_upload.cu`) onto
    the stack inside the megakernel's material dispatch, once per shaded bounce. This
    is exactly the shape CLAUDE.md's Stage-3 gate is worried about ("if the widening
    has to happen INSIDE the megakernel material dispatch... register-hostile") and
    is likely to spill given the shade kernel is already REG-254-pinned
    (`wavefront-shade-kernels-register-saturated` memory). **Do not do this.**
  - **Scalar-threading (pass `roughnessFloor` as an extra function parameter, apply
    `fmaxf` at each existing `mat.roughness` read site):** adds one float argument
    (likely register-resident, not stack) to ~6 already-existing device functions
    (`gpu_metal_sample`, `gpu_dielectric_sample`, `gpu_dielectric_sample_spectral`,
    `gpu_disney_sample`, `gpu_principled_sample`, `gpu_closure_graph_sample`, plus
    their `*_eval` siblings if filter-glossy is meant to affect NEE evaluation as well
    as BSDF sampling — Cycles blurs before BOTH). This is closer to item A's
    register-neutral shape but touches **more call sites than item A** (item A only
    touches the shade kernel's continuation check; item C touches every glossy
    sample/eval function's signature). Signature-fan-out itself is a register-cost
    unknown until measured — more live scalar arguments across more call sites can
    still push occupancy-limiting register count even without a struct copy.

**Prediction:** the accumulator (SoA field) alone should clear the probe like item A
did (+ a few registers/stack at most, not more). The scalar-threading widening
is *plausible* to clear the probe but is **not free like item A was** — it touches
materially more functions, and unlike item A (a single `if` in the shade continuation
logic) it sits inside the hot GGX-alpha computation of every glossy closure type. This
should be treated as **medium risk**, not "probably fine by analogy to item A."

**Probe-first discipline to follow exactly as spec'd:** `cuobjdump --dump-resource-usage`
(sm_120, confirmed via `--list-elf` first, never `ptxas -v`) on the FINAL linked `.pyd`
for the fleet default specialization `stageShadeBucketedKernel<0,0,0,0,0,0,0>`
(current baseline per the PR #647/pkg223 session state: **REG 254 / STACK 3352 /
CONSTANT[0] 1700→1708 after item A's own SoA additions land** — the item-C probe must
be re-taken AFTER item A lands, against whatever item A's numbers become, not against
the stale 3352/1700 pair quoted in the pkg201 Stage-3 acceptance text, which predates
item A). If item C's feature-off specialization moves off that post-item-A baseline,
STOP and park with the cuobjdump evidence per the Stage-3 "may-park" clause.

## 4. Open questions / risks for the implementer

1. **CPU is a genuinely separate, non-trivial change**, not a smaller mirror of GPU.
   `Material::sample()`/`sampleSpectral()` are virtual methods on a possibly-shared,
   possibly-const `Material*`; there is no existing "pass an override roughness"
   parameter. Either add a defaulted override-roughness argument to the virtual
   `sample`/`sampleSpectral` signatures (touches every `Material` subclass override —
   a real call-site sweep, CLAUDE.md pre-push rule) or restrict CPU filter-glossy to
   only the closure-graph/Principled path where a per-shade local closure copy
   already exists (need to verify whether `sampleSpectral` for `GMAT_CLOSURE_GRAPH`equivalent CPU materials already copies its closure params locally the way GPU's
   `GPrincipledClosure c` does in `scene_upload.cu` — **not yet confirmed by this
   research pass**, flag for verification before implementing).
2. **Does filter-glossy need to touch NEE/light-sampling BSDF *evaluation* too, or
   only the continuation *sample*?** Cycles blurs the closures in shading state
   before both are used (the blur happens once per shaded hit, mutating `sd->closure`
   in place, so every subsequent eval/sample in that hit sees the widened alpha). If
   Astroray widens only at the sample call site (§2 above) but NOT at the NEE-eval
   call site for the same hit, direct-light sampling on the same vertex would use the
   un-widened roughness — a partial-honour bug, not a full Cycles mirror. Needs an
   explicit decision, not a silent pick (CLAUDE.md §1).
3. **`FLT_MAX`/off-state byte-identity.** Cycles special-cases `filter_glossy ==
   FLT_MAX` (i.e. `blur_glossy == 0`) to skip the whole block. Astroray's port must
   preserve this short-circuit so `filterGlossy == 0` (the current always-zero
   default) costs nothing at runtime beyond the register overhead measured by the
   probe — matches the "byte-identical when off" bar Stage 2's F-alpha/`filter_width`
   items already met.
4. **pkg200 gate is `p_blur_glossy`** (`scripts/pkg200_honour_matrix.py:176-181`):
   PASS requires `b.lum_max < a.lum_max * 0.97` (B=`blur_glossy=10` must drop the
   glossy highlight peak vs A=`blur_glossy=0`). At `blur_glossy=10`,
   `filter_glossy_kernel = 1/10 = 0.1`; whether this converges to a visible highlight
   drop within the honour-matrix scene's low sample count is untested by this
   research pass — worth a cheap host-side sanity check of the formula's magnitude
   before committing to the full kernel plumbing.
5. **Item A must land first and be re-measured** (see §3) — this note's register
   prediction is provisional against a baseline that will shift once item A's SoA
   fields exist. Do not treat 3352/1700 as current truth when item C's probe runs;
   re-read whatever item A's PR records.
6. **Confirm whether Astroray's GGX BSDFs use a single scalar `roughness` (isotropic)
   or `alpha_x`/`alpha_y` (anisotropic)** before choosing the widen-site plumbing —
   this research pass only confirmed a single `mat.roughness`/`c.roughness` scalar
   field on `GMaterial`/`GPrincipledClosure`; if anisotropic GGX exists elsewhere,
   both axes need the `fmaxf` per Cycles' `bsdf_microfacet_blur`.

## Sources

- [`intern/cycles/scene/integrator.cpp`](https://github.com/blender/blender/blob/main/intern/cycles/scene/integrator.cpp) — `filter_glossy` UI→kernel inversion.
- [`intern/cycles/kernel/integrator/surface_shader.h`](https://github.com/blender/blender/blob/main/intern/cycles/kernel/integrator/surface_shader.h) — the blur_pdf/blur_roughness formula and closure loop.
- [`intern/cycles/kernel/integrator/shade_surface.h`](https://github.com/blender/blender/blob/main/intern/cycles/kernel/integrator/shade_surface.h) — `min_ray_pdf` per-bounce update.
- [`intern/cycles/kernel/integrator/path_state.h`](https://github.com/blender/blender/blob/main/intern/cycles/kernel/integrator/path_state.h) — `min_ray_pdf` init to `FLT_MAX`.
- [`intern/cycles/kernel/integrator/state_template.h`](https://github.com/blender/blender/blob/main/intern/cycles/kernel/integrator/state_template.h) — `min_ray_pdf` declared as path state.
- [`intern/cycles/kernel/closure/bsdf.h`](https://github.com/blender/blender/blob/main/intern/cycles/kernel/closure/bsdf.h) — `bsdf_blur` dispatch by closure type.
- [`intern/cycles/kernel/closure/bsdf_microfacet.h`](https://github.com/blender/blender/blob/main/intern/cycles/kernel/closure/bsdf_microfacet.h) — `bsdf_microfacet_blur`, the `fmaxf(roughness, alpha)` widening.

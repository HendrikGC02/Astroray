# pkg253 — Principled BSDF advanced inputs

**Pillar:** 5
**Track:** A
**Status:** in-progress
**Estimated effort:** 3 sessions (~9 h)
**Depends on:** pkg229, pkg178

---

## Goal

Before: the 2026-09 coverage re-audit (`blender-coverage-reaudit-2026-09.md`)
lists "BSDF_PRINCIPLED advanced inputs (21)" as the #1 ranked DROPPED-SILENT
gap — Subsurface Radius/Scale/IOR/Anisotropy, Coat IOR/Tint, Specular IOR
Level/Tint, Anisotropic Rotation, Tangent, Alpha, Thin Wall, Weight, Diffuse
Roughness — and the coverage matrix (`docs/blender_parity/coverage_matrix.json`)
shows all of them DROPPED-SILENT. After: the matrix correctly shows 15 of
those 21 as APPROXIMATED (they were never actually dropped — a scanner blind
spot hid an already-shipped implementation), the ONE genuine functional gap
found in the process (Principled `alpha` did not attenuate NEE shadow rays)
is fixed CPU-side with tests, and the true remaining gap (6 sockets/props
needing new engine machinery: Weight, Subsurface IOR, Tangent, Coat Normal,
`distribution`, `subsurface_method`) is documented as an explicit non-goal
instead of silently re-measured as "dropped" forever.

---

## Context

Filed as the #1 ROI item because the audit's numbers say 21 sockets of
Astroray's flagship BSDF are silently ignored. Reading the addon and engine
source before writing code (CLAUDE.md §1, "don't assume") shows that framing
is stale: pkg178 ("native Cycles-Principled BSDF", PRs #566–#581, **Status:
done**, RATIFIED to production 2026-08-11) already implements Alpha,
Specular Tint, Coat IOR/Tint, Sheen Roughness/Tint, Anisotropic Rotation,
Thin Wall, Diffuse Roughness, Subsurface Radius/Scale/Anisotropy and Thin
Film Thickness/IOR — CPU **and** GPU, addon-wired via
`_principled_native_params` (`blender_addon/__init__.py`), default-ON. The
coverage matrix never saw any of it: the scanner only opens
`_principled_shader_spec` (the Disney-fallback param reader), not
`_principled_native_params` (a separate helper it calls) — the *same
blind-spot class* pkg229 already fixed once for the op-VM. This package
fixes the recurrence and uses the corrected matrix to find what's actually
still missing, instead of re-implementing sockets that already work.

---

## Reference

- pkg178 spec: `.astroray_plan/packages/pkg178-native-cycles-principled-bsdf.md`
  (Status: done — read before assuming anything here is unimplemented).
- pkg229 spec / scanner-blind-spot precedent: `.astroray_plan/docs/blender-coverage-reaudit-2026-09.md`.
- Cycles reference (already cited in `plugins/materials/principled.cpp` and
  `include/astroray/gpu_materials.h`): `svm/closure.h` (alpha/transparent-first
  assembly), `bsdf_transparent.h` (delta wo=-wi sampling), Zeltner 2022 (sheen
  LTC), Belcour-Barla 2017 (thin-film). Blender 5.2 Principled BSDF manual page.
- Blender manual: "Transparent Shadows" (Cycles Alpha<1 lets (1-alpha) of a
  shadow ray's light through instead of unconditionally blocking it) — the
  behaviour G1 below closes for Astroray.

---

## Prerequisites

- [x] pkg178 is done and tests are green (`tests/test_pkg178_alpha.py`,
      `tests/test_pkg178_aniso.py`, `tests/test_pkg178_stage5_native_routing.py`
      — 30/30 pass on this branch).
- [x] Build passes on main (CPU-only MinGW build verified in this worktree).
- [x] `docs/blender_parity/coverage_matrix.json` exists (pkg229 output) and
      is regenerable headlessly (`blender --background --factory-startup
      --python scripts/generate_blender_parity_matrix.py -- --out
      docs/blender_parity`, `ASTRORAY_PYD_DIR` pointed at a built addon).

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `tests/test_pkg253_alpha_shadow.py` | TDD gate for G1: alpha=0 must cast no shadow, monotone in alpha, byte-identical to the pre-existing opaque-shadow behaviour at alpha=1. |

### Files to modify

| File | What changes |
|---|---|
| `scripts/generate_blender_parity_matrix.py` | `DedicatedHandlerScanner` gets a third branch scanning `_principled_native_params`'s local `put_float(dst, *names)` / `put_vec(dst, *names)` closures, crediting `args[1:]` (the actual Blender socket names) into the existing `BSDF_PRINCIPLED` evidence entry — mirrors the existing `_principled_shader_spec` / `_standalone_bsdf_spec` branches immediately above it. |
| `docs/blender_parity/coverage_matrix.json`, `docs/blender_parity/report.md` | Regenerated with the fixed scanner. |
| `include/raytracer.h` | New `Material::shadowAlpha(rec)` virtual (default `1.0`, opaque — every pre-existing material unaffected). The two surface-NEE occlusion blocks in `pathTraceSpectral` and `pathTraceSpectralCaustic` compute `shadowTransmittance = 1 - shadow.material->shadowAlpha(shadow)` at a hit (instead of an unconditional `occluded=true`) and scale `neeContrib` by it. |
| `plugins/materials/principled.cpp` | `PrincipledMaterial::shadowAlpha()` override returns `alpha_` (the same value the camera-ray delta-transparent lobe already reads, pkg178 PR-6). |

### Key design decisions

1. **Investigate before implementing (CLAUDE.md §1).** The task brief named
   6 socket groups (G1–G6) to implement from scratch. Reading pkg178's
   status first showed G2 (Specular Tint), G3 (Coat IOR/Tint), G4 (Sheen
   Roughness/Tint) and most of G6 are *already done* CPU+GPU — confirmed by
   grepping `gpu_materials.h` (`c.specularTint`/`c.coatIor`/`c.coatTint`/
   `c.sheenRoughness`/`c.sheenTint` all *consumed*, not just uploaded, in the
   GPU closure-graph eval/sample paths) and `principled.cpp` (same names,
   CPU-side, Cycles-cited). **G2/G3/G4 needed zero code changes** — only the
   matrix-scanner fix below so their status measures correctly.
2. **G1 (Alpha) had exactly one real gap: shadow rays.** BSDF sampling/eval
   for `alpha` is byte-complete (pkg178 PR-6). `include/raytracer.h`'s NEE
   blocks (the shadow-ray test every CPU render uses) did a **purely
   geometric** `bvh->hit(...)` occlusion test with no material query, so a
   Principled surface at `alpha=0` still fully blocked light to anything
   behind it. Fixed here.
3. **`Material::shadowAlpha()`** mirrors the existing extensibility pattern
   (`isTransmissive()`, `getSpecularTint()`: a virtual with a safe default,
   overridden only where it matters) instead of a call-site `dynamic_cast`.
   Safety-by-construction (matching PR-6): default `shadowAlpha()==1.0` for
   every pre-existing material, and Principled at `alpha=1` also returns
   `1.0`, so `shadowTransmittance` is provably `1.0` or `0.0` in every case
   that existed before this package — `neeContrib * shadowTransmittance` is
   exactly the old `occluded ? 0 : neeContrib`. Verified with 76 regression
   tests (pkg178 alpha/aniso/native-routing + a furnace/NEE-adjacent sweep),
   unchanged, all green.
4. **Scope cuts, each with a reason:** single-occluder only (Cycles-style
   multi-hit chaining through several stacked cutouts is separable
   follow-up); volume/medium-ray NEE untouched (different code path, phase
   function not surface BSDF); **GPU wavefront mirror not attempted** — the
   occlusion test is spread across three register-critical files
   (`stage_advance.cu`, `stage_light_sample.cu`, `stage_restir.cu`; memory
   `wavefront-shade-kernels-register-saturated`), and authoring a multi-file
   change there with zero ability to build/verify it (no CUDA build in this
   lane) is the speculative risk CLAUDE.md §2/§3 warn against — flagged as a
   follow-up instead, CPU stays the correctness oracle meanwhile.
5. **Scanner noise (`fallback_stale` 17→28) is a side effect, not a bug.**
   `_principled_native_params`'s fallback names include pkg187's intentional
   forward-compatible dispersion probes (sockets no shipped Blender exposes
   yet, by design — see `blender_addon/__init__.py:3848-3861`). The scanner
   now sees these for the first time and correctly reports them absent from
   the live node — true, not a regression; no scanner change made for it.

---

## Acceptance criteria

- [x] G1 (Alpha, shadow rays): `tests/test_pkg253_alpha_shadow.py` — 5/5
      pass, TDD-verified (built pre-fix, confirmed the bug empirically —
      opaque and alpha=0 occluders darkened a receiver identically at
      depth=1, 0.2477 vs 0.2477 — then rebuilt with the fix and confirmed
      alpha=0 recovers ~99.9% of unoccluded brightness). Rendered LINEAR
      (`apply_gamma=False`) with a floor and ceiling (energy-conservation
      per the existing `test_pkg178_alpha.py` white-furnace test).
- [x] G1 regression safety: pkg178 alpha/aniso/native-routing (30 tests) +
      a furnace/NEE-adjacent sweep (furnace, area-light orientation, delta
      light, firefly-clamp, light-path passes, volume scattering, guiding —
      46 tests) unchanged, all green. (Not run: the full ~305-file suite —
      out of turn budget; byte-identity is proven by construction, decision 3.)
- [x] G2/G3/G4 (Specular Tint, Coat IOR/Tint, Sheen Roughness/Tint): verified
      already implemented on both backends by direct source inspection — no
      code change required.
- [x] Coverage matrix regenerated (`docs/blender_parity/*`, headless
      Blender 5.2). BSDF_PRINCIPLED: 15 sockets (Alpha, Thin Wall, Diffuse
      Roughness, Subsurface Radius/Scale/Anisotropy, Specular IOR
      Level/Tint, Anisotropic Rotation, Coat IOR/Tint, Sheen Roughness/Tint,
      Thin Film Thickness/IOR) move DROPPED-SILENT → APPROXIMATED (matching
      the pre-existing overall BSDF_PRINCIPLED tier). Repo-wide:
      APPROXIMATED 35→50, DROPPED-SILENT 378→363, SUPPORTED unchanged at
      114 (checked against a from-scratch baseline with the scanner fix
      reverted, same commit, same session).
- [x] Genuinely-still-dropped sockets/props correctly identified and named
      as non-goals: `input:Weight`, `input:Subsurface IOR`, `input:Tangent`,
      `input:Coat Normal`, `prop:distribution`, `prop:subsurface_method` —
      confirmed absent from `_principled_native_params` AND present
      verbatim in the addon's own `_NATIVE_PRINCIPLED_UNMAPPED` comment.
- [ ] GPU verification of the G1 shadow-ray fix — **pending the lead's CUDA
      build** (no GPU code was written; this line tracks that CPU-only
      touches no GPU/CUDA file, checked once the lead confirms the fleet
      build is unaffected).
- [x] Signature sweep done before push: `Material::shadowAlpha` is a new
      virtual with a safe default — grepped every `Material` subclass and
      every call site of the two patched NEE blocks; no other caller needed
      updating.

---

## Non-goals

- Re-implementing Specular Tint / Coat IOR-Tint / Sheen Roughness-Tint —
  already done (pkg178). Do not add duplicate code paths.
- `input:Weight` (Blender 4.x+'s generic per-closure mix weight, present on
  every shader-closure node) — no native-material concept to route it to;
  needs a weighted-mix wrapper, separate package if ever prioritized.
- `Subsurface IOR`, `Coat Normal`, `Tangent` — per the addon's own
  `_NATIVE_PRINCIPLED_UNMAPPED`: no per-medium SSS IOR knob and no separate
  per-lobe normal/tangent input in the native material. Needs new engine
  machinery.
- `prop:distribution` / `prop:subsurface_method` — select an entirely
  different closure/transport model (Multiscatter GGX, random-walk SSS),
  not a value plug; Astroray only implements one model each. Future
  model-selection package, not a socket fix.
- Multi-hit / chained transparent shadows (several stacked alpha-cutouts) —
  the G1 fix handles the single-occluder case (the literal acceptance
  test); a Cycles-`transparent_max_bounce`-style chain is separable
  follow-up. Volume/medium-ray NEE alpha-awareness is likewise untouched.
- **GPU wavefront mirror of the G1 shadow-ray fix** — not implemented here
  (decision 4); filed as a follow-up rather than attempted blind.
- Fixing the pre-existing, unrelated op-VM scanner regression (`op-VM /
  vector-path handled node types` reports 6, not pkg229's stated 20 —
  reproduced with this package's scanner change reverted, so it predates
  this PR). Worth its own follow-up.

---

## Progress

- [x] Step 1 — spec written, grounded in reading pkg178's status, the
      addon's native-param plumbing, and both engine backends first.
- [x] Step 2 — G1 Alpha: found the real gap (shadow rays, not BSDF
      sampling), wrote the failing test, verified it fails pre-fix, fixed
      CPU-side, verified it passes, regression-swept (76 tests total).
- [x] Step 2b — coverage-matrix scanner blind-spot fix (mirrors pkg229),
      matrix regenerated, delta verified against a reverted-scanner
      baseline in the same session.
- [ ] Step 3 — G2 Specular Tint: not needed as a code change (decision 1);
      covered by the matrix fix. If a future audit finds a REAL GPU-vs-CPU
      divergence (not a scanner miscount), open a fresh package.

---

## Lessons

The task brief's socket-group framing was written against the coverage
matrix's *reported* numbers, not the engine's actual state — and the matrix
was wrong in exactly the way pkg229 already diagnosed once (a scanner blind
spot around a called-but-not-inlined helper), recurring for a different
helper. Generalizable lesson: **before implementing against a coverage/audit
artifact, re-derive at least one data point in it from source** (here: pkg178's
own spec status, and the CPU+GPU material source) rather than trusting the
headline number. This saved ~6-9 hours of reimplementing already-shipped BSDF
lobes, and surfaced one real, previously-invisible bug (shadow rays ignoring
alpha) the socket-coverage framing alone would never have found — coverage
matrices measure "is this input read," not "does every downstream ray
consult it."

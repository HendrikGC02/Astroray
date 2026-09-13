# pkg254 — Spectral path_tracer feature parity (the deferred bindings xfails)

**Pillar:** 5
**Track:** A
**Status:** in-progress — Triage 2026-09-12 (half-implemented audit, `half-implemented-triage-2026-09-12.md`): finish in a batch after the pkg253 GPU alpha item — six xfails in `tests/test_python_bindings.py`. Was: open
**Estimated effort:** 2 sessions (~6 h)
**Depends on:** pkg14, pkg87, pkg195

---

## Goal

Before: six features that the pre-pkg14 RGB path tracer supported are still
"not ported to the spectral path_tracer — deferred" and live as `strict=True`
xfails in `tests/test_python_bindings.py` with no owner. After: each feature
either works on the spectral `path_tracer` (CPU and GPU) with its xfail marker
removed, or is retired with a recorded owner decision; no unowned xfail remains.

---

## Context

pkg14 deleted the legacy RGB integrator and made `path_tracer` spectral-first.
Ten integration tests were parked as `strict=False` xfails, which silently
swallowed fixes: on 2026-09-07 four of them XPASSed (per-closure bounce limits
and caustics flags already work) and their markers were removed (PR #720). The
remaining six are real gaps a Blender user hits through native Cycles panels
(transparent alpha, filter glossy, cryptomatte passes, HDR/linear output,
gamma toggle). Owning them here keeps the coverage gate honest.

---

## Evidence

- 2026-09-07 — `python -m pytest tests/test_python_bindings.py -k "alpha or filter_glossy or cryptomatte or hdr or gamma"`: six xfails remain at lines ~516, ~546 (transparent alpha), ~1018 (filter_glossy), ~1279 (cryptomatte/render passes), ~1425 (HDR/linear output pass), ~1519 (gamma toggle); markers now `strict=True` (PR #720).
- 2026-09-07 — the four bounce-limit / caustics-flag tests XPASS on `build_cuda/Release` (main `bd59652`) and had their markers removed.

---

## Reference

- Design doc: `.astroray_plan/docs/light-transport.md §Spectral path tracer`
- pkg14 (legacy RGB path deletion), pkg87 (cryptomatte), pkg195 (spectral node system), pkg253 (Principled Alpha is the addon-side consumer of transparent alpha).

---

## Prerequisites

- [ ] pkg253 G1 (Principled Alpha) decides whether transparent alpha is a closure or a shadow-only feature.
- [ ] Build passes on main; `tests/test_python_bindings.py` collected with the six xfails present.

---

## Specification

### Files to create

None.

### Files to modify

| File | What changes |
|---|---|
| `tests/test_python_bindings.py` | remove each xfail marker as its feature lands; no test body changes |
| `plugins/integrators/path_tracer.cpp` | transparent alpha, filter_glossy, gamma toggle honoured on the spectral path |
| `module/blender_module.cpp` | expose/route the settings if a binding is missing |
| `src/gpu/wavefront/*.cu` | GPU twin of each honoured setting (register-neutral) |

### Key design decisions

- One feature per PR, CPU and GPU together, each removing exactly its xfail marker(s).
- Retirement is allowed only with an owner note in `## Progress` and the test deleted, never re-xfailed.
- Follow the Cycles semantics already mapped in `blender_addon/settings_map.py`.

---

## Acceptance criteria

- [ ] Zero `xfail` markers in `tests/test_python_bindings.py` whose reason contains "not ported to the spectral path_tracer".
- [ ] Each landed feature has a CPU/GPU parity assertion in its test.
- [ ] Full `tests/test_python_bindings.py` green on the RTX 5070 Ti.

---

## Non-goals

- Do not re-introduce an RGB integrator.
- Do not relax any test threshold to flip an xfail.

---

## Progress

- [x] 2026-09-07 — filed; four XPASS markers removed in PR #720; six remain.
- [x] 2026-09-13 (batch H) — transparent-film alpha PORTED to the spectral path
      (`Renderer::coverageAlpha`, ported from the deleted RGB `pathTrace` commit
      e763cd7f, applied integrator-agnostically in the render loop when
      `useTransparentFilm`). Retires the two transparent-alpha strict xfails
      (`test_transparent_film_alpha_masks_background`,
      `test_transparent_glass_keeps_rgb_but_zeroes_alpha`) — both pass; opaque-film
      default byte-identical (no extra RNG).
- [ ] 2026-09-13 (batch H) — the OTHER FOUR remain xfail after investigation
      (root-caused with `--runxfail` on the batch-H build, NOT stale markers):
      - **HDR/linear output** (`test_linear_output_preserves_hdr_values`): the
        solid background `[2.5,0.5,0.25]` round-trips through Jakob-Hanika spectral
        upsampling; green comes back 0.61 vs 0.5 (>0.05 band). Needs an exact-RGB
        (non-spectral) solid-background eval on the miss leg — a broad-impact
        change to background spectral sampling, out of this batch's scope.
      - **gamma toggle** (`test_render_apply_gamma_toggle`): gamma IS applied
        (mean check passes) but the per-pixel `allclose(gamma, pow(linear,1/2.2))`
        fails because the two renders use the seed-0 random sentinel (independent
        spectral MC noise on the background). Deterministic only if the solid
        background is noise-free (same fix as HDR above) — can't be met without
        weakening the test.
      - **cryptomatte** (`test_cryptomatte_buffers_exist_and_have_coverage`):
        `get_cryptomatte_object_buffer()` returns `(H,W,12)` (depth-6, 6 id/coverage
        pairs); the test asserts `(H,W,4)`. A buffer-format question (owner
        decision on the intended default cryptomatte channel layout), not a
        spectral port.
      - **filter_glossy** (`test_filter_glossy_blurs_secondary_glossy_paths`,
        non-strict): genuinely UNIMPLEMENTED — zero consumers of
        `Renderer::filterGlossy` anywhere. A faithful port is Cycles'
        `surface_shader_bsdf_blur` (min_ray_pdf tracking in `pathTraceSpectral`
        + a per-bounce roughness floor threaded into every glossy material's
        sample/eval), a large cross-material API change. Parked (owner-accepted).

---

## Lessons

*(Fill in after the package is done.)*

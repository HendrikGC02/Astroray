# pkg325 — Dielectric bounce-cap passthrough (no black dead spots in thick glass)

**Pillar:** 1
**Track:** A
**Status:** in-progress — CPU + addon + tests on lane/pkg325; GPU legs pending the lead's CUDA build
**Estimated effort:** 1 session (~4 h) + GPU legs via the lead
**Depends on:** none

---

## Goal

Before: when a path inside a dielectric hits the transmission (or total) bounce cap it terminates,
so thick or nested glass at low depth limits shows black dead regions, exactly as Cycles does.
After: an Astroray option `dielectric_bounce_cap: terminate | passthrough` (default `terminate`,
Cycles parity) where `passthrough` lets the capped path continue as a null transmission with the
current throughput so it can still reach lights; CPU and GPU agree; the tumbler scene at depth 4/8/12
has no dead region under `passthrough` and is pixel-identical to Cycles under `terminate`.

---

## Context

Redshift's refraction-limit behaviour and the Spectra thread's "Dielectric Graceful Exit" (post #9,
`docs/research/spectra-blenderartists-thread-2026-10-25.md`) show the same cheap, user-visible win.
Physics-over-look (owner 2026-09-29) means the default stays Cycles-faithful; the option is a
render-time convenience the owner asked about in `architect-plan-2026-10-25.md` question 1.

---

## Reference

- Cycles behaviour: `intern/cycles/kernel/integrator/shade_surface.h` bounce-limit termination (cite the 5.2 line in code)
- Astroray: CPU `pathTraceSpectral` bounce accounting; GPU wavefront `c_wfBounceLimit[3]` and the transparent-pass path (#1033, #1073, #1125)
- Related: pkg324 ships the tumbler scene

---

## Prerequisites

- [ ] #1125 merged (pass_count lane; the passthrough reuses the transparent-pass machinery).
- [ ] Build passes on main.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `tests/test_pkg325_bounce_cap_passthrough.py` | CPU + GPU: dead-pixel fraction at depth 4/8/12 under both modes; `terminate` equals the pre-change render to 1e-6; CPU/GPU agree within MC band |

### Files to modify

| File | What changes |
|---|---|
| `include/raytracer.h` | Renderer setting `dielectricBounceCapPassthrough` (default off = `terminate`); CPU in `pathTraceSpectral`: a transmission sample the total or transmission cap would end goes straight on (null interface, sampled weight kept), counted as a transparent pass |
| `module/blender_module.cpp` | `set_dielectric_bounce_cap` / `get_dielectric_bounce_cap` binding |
| `include/astroray/gpu_wavefront_state.h` | `setWavefrontDielectricCapPass` declaration |
| `src/gpu/wavefront/stage_advance.cu` | `__constant__ c_wfDielectricCapPass` + publish |
| `src/gpu/wavefront/gpu_wavefront_snapshot.cu` | publish per frame; the #1033 transparent block is switched on for passthrough |
| `blender_addon/exporter.py` | viewport wiring |
| `blender_addon/settings_map.py` | astroray-only settings row |
| `src/gpu/wavefront/stage_advance_device.cuh` | GPU shade/intersect: the same branch behind the existing transparent-pass path; no new template axis |
| `src/gpu/wavefront/shading_inputs_eval.cu` | the `__noinline__` helper that applies the pass, next to `gpu_countTransparentPass` |
| `blender_addon/__init__.py` | the setting under the Astroray panel (not a native Cycles property) |
| `docs/blender_parity/report.md` | a note that the option is Astroray-only; no matrix row changes |

### Key design decisions

- Null interface in direction; weight = the sampled BTDF weight, so a capped path inside a slab is not left at 1/eta^2
  (resetting throughput to 1 leaves it at 1/2.25 brightness; measured 0.46 vs 0.89, see the research note). The ray keeps
  its direction, so the result is a plausible "see-through" rather than a physically continued path; the panel tooltip says so.
- Register pressure: the branch lives next to the transparent-pass code; verify shade REG/STACK unchanged with cuobjdump.
- Off by default; the pkg324 tumbler A/B is the demo.

---

## Acceptance criteria

- [ ] `terminate` mode renders are byte/1e-6 identical to the pre-change build on CPU and GPU (regression test).
- [ ] `passthrough` mode: tumbler dead-pixel fraction (pixels < 1e-4 inside the glass silhouette) < 0.5 % at depth 4, 8, 12.
- [ ] CPU vs GPU `passthrough` renders agree within the pkg310 MC band on the tumbler ROIs.
- [ ] cuobjdump: shade kernels REG unchanged, STACK within ±16 B.

---

## Non-goals

- Do not change the default; do not touch Cycles native settings semantics.
- Do not implement Spectra's "release the ray to find lights" heuristics beyond the null pass-through.

---

## Progress

- [x] Setting + CPU branch (scene: benchmarks/showcase/spectral/pkg325; real files: `pathTraceSpectral` in include/raytracer.h, no render_settings.h / spectral_path_tracer.cpp)
- [ ] GPU branch + BUILD REQUEST
- [ ] Tests green, cuobjdump checked
- [x] Panel + docs (Sampling panel; research note `.astroray_plan/docs/pkg325-bounce-cap-passthrough-research.md`)

---

## Lessons

*(Fill in after the package is done.)*

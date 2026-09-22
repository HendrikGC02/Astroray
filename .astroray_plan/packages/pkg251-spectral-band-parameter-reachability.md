# pkg251 — Spectral band parameter reachability across callers

**Pillar:** 5
**Track:** A
**Status:** open — contract audit and architect review before implementation
**Estimated effort:** S/M, confirm after audit
**Depends on:** pkg250

---

## Goal

Before: wavelength-band defaults, parameter parsing, output-mode handling and
reused-renderer state differ across the standalone CLI, the production Python
GPU caller, Blender F12, both Blender viewport paths, and CPU and GPU dispatch,
so decimal and integer wavelength arguments may not reach the same band and
`output_mode` may be ignored, inferred inconsistently, or left stale. After: one
versioned band/output contract (v1) that names every public entrypoint and its
CPU/GPU target, coerces both bounds numerically in every backend, fixes a single
canonical omitted-band default, defines the accepted `output_mode` enum with
explicit-over-inferred precedence, validation and per-backend support, makes
band/mode configuration transactional across dispatches, and specifies the raw
band-radiance payload and provenance metadata — preserving visible-color
workflows and deliberate infrared/band-aware outputs, and proven by runtime
tests that parameter values reach the intended backend.

---

## Context

Pillar 5 covers renderer interoperability and spectral foundations. The package
depends on pkg250, the standalone dispatch repair, and on the existing spectral
core. The divergent band and parameter behaviors predate pkg250; that repair
mirrors the current GPU binding and does not establish a single band/output
contract. Current callers disagree on defaults (CPU 360–830 nm, GPU/CLI
380–780 nm), on numeric representation (integer CLI bounds are read back with
`getFloat`, so they silently fall through to the default), on mode handling (the
CPU `path_tracer` ignores `output_mode`, the GPU interprets only `luminance`,
and callers pass `xyz`/`rgb`/`srgb`), and on lifecycle (setting a band after
`set_integrator()` does not rebuild the CPU integrator). A contract audit and
detailed architect review are required before implementation.

---

## Evidence

- 2026-09-06: The full-rebuild investigation found differing default band
  contracts: CPU SpectralPathTracer uses 360–830 nm; the production Python GPU
  caller uses 380–780 nm and derives output mode from its band.
- 2026-09-06: The standalone CLI parses an integer literal as an integer
  ParamDict value, while getFloat accepts a float; decimal wavelength arguments
  and integer-looking arguments may not reach the same band.
- 2026-09-06: Additional gate investigation — the existing GPU luma path
  accumulates equal XYZ components and then converts XYZ to linear sRGB; equal
  XYZ (E-white) is not D65-neutral sRGB: matrix row sums produce
  (1.2048, 0.9484, 0.9087) times the scalar signal.
- 2026-09-06: Pkg250's first exact-gray PNG assertion therefore failed; Terra
  confirmed the caller was correct.
- 2026-09-22: Codex Terra review defects applied (planning session).

---

## Reference

- `tests/test_integrator_float_param.py` — existing ParamDict::getNumber
  contract to reuse where compatible (see Key design decisions).
- `tests/test_pkg125_cpu_path_tracer_band_awareness.py` — CPU band-default and
  explicit-range behavior.
- `gpu-focused.log` — the initial failed log, remains in the rebuild artifacts.

---

## Prerequisites

- [ ] pkg250 standalone dispatch repair is complete.

---

## Specification

### Files to create

None.

### Files to modify

None.

### Key design decisions

The bounded phases below are UNRUN. Phase 1 produces the versioned contract v1
described in the next subsection; Phase 2 accepts or amends it; Phases 3–5
implement only what is accepted. The implementation file list is assigned after
the Phase 2 gate, so no file is created or modified yet.

#### Band/output contract v1 (Phase 1 output)

**Entrypoints — the matrix names each with file:line and its CPU/GPU target:**

- Standalone CLI `raytracer` (`apps/main.cpp`): CPU via `Renderer::render`; GPU
  via `cuda_wavefront_render` when `--gpu` and the wavefront build is present.
- Python `Renderer.render()`: CPU integrator (`path_tracer` / spectral).
- Python `astroray.cuda_wavefront_render(...)`: GPU wavefront binding.
- Python `astroray.cuda_wavefront_render_restir(...)`: GPU ReSTIR.
- Python config routes `set_integrator`, `set_integrator_param*`,
  `set_wavelength_range`, `set_output_mode`: feed both CPU integrators and the
  next GPU dispatch.
- Blender F12 final render (`blender_addon/exporter.py`): CPU or GPU per backend
  policy.
- Blender viewport dispatch in `blender_addon/__init__.py`: GPU (CPU fallback).
- Blender viewport dispatch in `blender_addon/exporter.py`: GPU (CPU fallback).

The Phase 1 matrix pins the exact function names for the F12 and the two
viewport sites.

**Coercion:** both `lambda_min` and `lambda_max` MUST be read with a
numeric-coercing `ParamDict::getNumber`-equivalent at every receiver — CPU
`plugins/integrators/spectral_path_tracer.cpp`, the GPU `path_tracer` branch and
the CLI GPU dispatch in `apps/main.cpp`, and the bindings — never the exact-type
`getFloat`. `output_mode` is read as a string. Integer and decimal spellings of
the same bound MUST select the same band; tests assert integer-vs-decimal
equivalence on every backend.

**Defaults (frozen 2026-09-22, lead may adjust):** the single canonical
omitted-band default for every backend is `[kLambdaMin, kLambdaMax] = [360, 830]
nm` (`include/astroray/spectrum.h`; the existing CPU `SpectralPathTracer`
fallback) — not a new arbitrary default. The GPU binding's `380/780` and the
CLI's `380/780` defaults change to this. Unset-path CPU and GPU tests assert the
same band; an explicit caller-supplied range always overrides.

**Output modes:** the accepted v1 enum is `xyz`, `rgb`, `srgb`, `luminance`.
Explicit over inferred — a non-empty `output_mode` governs; when empty the
backend infers `luminance` iff `[lambda_min, lambda_max]` is not contained in
the visible band `[379.5, 780.5]` nm, else `xyz` (the existing GPU rule,
frozen). A mode outside the enum fails hard before rendering, never a silent
fallback. Each `(backend, mode)` pair is either implemented or rejected with an
explicit error; the CPU `path_tracer` currently ignores `output_mode` and must
implement or reject every accepted mode. The direct GPU binding's
`use_luminance_output` bool is its mode channel; a conflict between a
non-default bool and an explicit string mode is an error.

**Lifecycle:** band/mode configuration is transactional. `set_wavelength_range`
and `set_output_mode` must rebuild/re-create the active CPU integrator (today
they only stage params, so a range set after `set_integrator()` is silently
ignored) or be staged and applied atomically on the next dispatch. Every
dispatch sets an explicit mode and re-derives band/mode from current config; no
cached `useLum` and no Blender reused-renderer state may leak across
visible↔non-visible transitions. Tests drive sequential band changes
(visible→IR→visible) on a reused renderer on CPU, GPU and the Blender path.

**Raw output and provenance:** the band-radiance payload is raw linear values
(no display/gamma transform, no clamp). `luminance` is one channel of relative
luminance; `xyz` is 3-channel CIE XYZ 1931 2°; `rgb`/`srgb` follow the declared
transform. Every output carries versioned metadata `band_contract = 1`:
`lambda_min_nm`, `lambda_max_nm`, `output_mode`, observer/transform, `units`
(`relative spectral radiance`, dimensionless), backend id and seed. Matched
CPU/GPU outputs compare raw pixels and every metadata field; bounds, mode,
observer and units must match exactly, pixel values within the declared sampling
uncertainty.

#### Phase 1 — Trace callers and defaults

Trace all callers and defaults with the project index. Record the contract-v1
matrix: every entrypoint above with file:line and CPU/GPU target; omitted,
integer, decimal and invalid bounds; visible/IR bands; explicit and inferred
`output_mode`. Reuse existing spectral test/harness tools.

#### Phase 2 — Architecture and review gate

Astra architecture plus independent high-tier review accepts or amends the v1
contract — compatibility, validation, migration and file ownership — before
implementation. Cite the established spectral method for numerical changes; no
new transport algorithm is implied.

#### Phase 3 — Implement the accepted contract

Implement only the accepted contract: numeric-coercing bound reads, canonical
defaults, mode validation and support, transactional configuration, and raw
metadata. Add runtime tests proving values reach the intended backend —
integer-vs-decimal equivalence, invalid-mode failure, unset-path CPU/GPU
equality, and sequential band changes.

#### Phase 4 — Measurement and visual evidence

Save matched CPU/GPU raw outputs and metadata; compare every provenance field;
inspect visible renders and appropriate band-output visualizations. Measure
effects with declared units, sampling uncertainty and existing physical gates,
not a blanket RGB metric.

#### Phase 5 — Delivery gates

Caller/binding review, focused regressions, GPU lock, actual imported-module
identity, independent sign-off and evidence-backed docs are delivery gates.

---

## Acceptance criteria

- [ ] A contract-v1 matrix is recorded naming every public entrypoint with
      file:line and CPU/GPU target, for omitted, integer, decimal and invalid
      bounds; visible/IR bands; explicit and inferred `output_mode`.
- [ ] Both bounds are read with a numeric-coercing getNumber-equivalent in every
      backend; integer-vs-decimal equivalence tests pass on CPU and GPU.
- [ ] Unset-path CPU and GPU renders use the single canonical default
      `[360, 830] nm` and produce the same band.
- [ ] `output_mode` accepts only `xyz`/`rgb`/`srgb`/`luminance`; explicit
      overrides inference; an out-of-enum mode fails hard; every unsupported
      `(backend, mode)` pair is rejected, not silently ignored.
- [ ] Setting band/mode after `set_integrator()` takes effect, and sequential
      visible→IR→visible changes on a reused renderer never leave stale state.
- [ ] Matched CPU/GPU raw outputs carry `band_contract = 1` metadata (bounds,
      mode, observer/transform, units, backend id, seed) and agree on every
      field, with pixels within declared sampling uncertainty.
- [ ] Astra architecture plus independent high-tier review has decided
      compatibility, validation and any migration before implementation;
      numerical changes cite the established spectral method.
- [ ] Delivery gates pass: caller/binding review, focused regressions, GPU
      lock, actual imported-module identity, independent sign-off and
      evidence-backed docs.

---

## Non-goals

- No astrophysics activation.
- No spectral-core replacement.
- No new arbitrary band default.
- No output mode outside the v1 enum.
- No silent ignore of an unsupported `(backend, mode)` pair.
- No claim that current output is scientific instrument calibration.
- Do not choose new defaults merely to make a reference image pass.
- Filing does not preempt pkg241/240 or the mapped-texture sequence.
- Pkg251 preserves later research foundations while Pillar 4 stays PAUSED.

---

## Progress

- (none yet)

---

## Lessons

- (none yet)

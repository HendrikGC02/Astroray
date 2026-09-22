# pkg251 — Spectral band parameter reachability across callers

**Pillar:** 5
**Track:** A
**Status:** open — contract audit and architect review before implementation
**Estimated effort:** S/M, confirm after audit
**Depends on:** pkg250

---

## Goal

Before: band defaults, parameter parsing, output-mode handling and reused-renderer
state differ across the CLI, production GPU caller, Blender F12, both viewport
paths and CPU/GPU dispatch, so decimal/integer bounds may miss the same band and
`output_mode` may be ignored or stale. After: one versioned band/output contract
(v1) names every entrypoint/backend, coerces both bounds, fixes one canonical
default, defines the `output_mode` enum with explicit-over-inferred precedence,
makes configuration transactional, and pins the raw payload, provenance and
per-mode array contract — proven by runtime tests.

---

## Context

Pillar 5 covers renderer interoperability and spectral foundations; the package
depends on pkg250 (standalone dispatch repair) and the spectral core. The divergent
behavior predates pkg250, whose repair mirrors the current GPU binding and does not
establish one band/output contract. Callers disagree on defaults (CPU 360–830 nm,
GPU/CLI 380–780 nm), on numeric representation (integer CLI bounds read with
`getFloat` fall through), on mode handling (CPU `path_tracer` ignores `output_mode`;
the GPU interprets only `luminance`; callers pass `xyz`/`rgb`/`srgb`), and on
lifecycle (a band set after `set_integrator()` does not rebuild the CPU integrator).
Audit and architect review precede implementation.

---

## Evidence

- 2026-09-06: The full-rebuild investigation found differing default band
  contracts: CPU SpectralPathTracer uses 360–830 nm; the production Python GPU
  caller uses 380–780 nm and derives output mode from its band.
- 2026-09-06: The CLI parses an integer literal as an integer ParamDict value,
  while getFloat accepts a float; decimal and integer-looking bounds may differ.
- 2026-09-06: The existing GPU luma path accumulates equal XYZ then converts to
  linear sRGB; equal XYZ (E-white) is not D65-neutral sRGB — matrix row sums give
  (1.2048, 0.9484, 0.9087) times the scalar signal, so pkg250's first exact-gray
  PNG assertion failed; Terra confirmed the caller was correct.
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

**Entrypoints / route matrix — each row names its actual call path (file:line),
its CPU/GPU target, and the mode payload defined below:**

- Standalone CLI `raytracer` (`apps/main.cpp`): CPU via `Renderer::render`; GPU
  via `cuda_wavefront_render` when `--gpu` and the wavefront build is present.
- Python `Renderer.render()` (`module/blender_module.cpp`) — the production GPU
  caller: with GPU selected it reads `lambda_min`/`lambda_max` via `getFloat`
  (:2420–2421) and `output_mode` (:2422), then dispatches `restir-di` →
  `astroray::wavefront::cuda_wavefront_render_restir` (:2397) or any other GPU
  integrator → `cuda_wavefront_render`; with CPU selected it runs `path_tracer` /
  spectral. The ReSTIR driver has NO direct Python binding — this dispatch is its
  only Python route.
- Python `astroray.cuda_wavefront_render(...)` binding
  (`module/blender_module.cpp:5530`): direct GPU wavefront call; legacy
  `use_luminance_output` bool.
- Python config routes `set_integrator`, `set_integrator_param*`,
  `set_wavelength_range`, `set_output_mode`: stage `integratorParams_` for both
  CPU integrators and the next GPU dispatch; the last two only stage today
  (`setWavelengthRange`/`setOutputMode`, :3099–3106).
- Blender F12 final render (`blender_addon/exporter.py`): CPU or GPU per backend
  policy; Blender viewport dispatch in `blender_addon/__init__.py` and
  `blender_addon/exporter.py`: GPU (CPU fallback).

**Coercion:** both `lambda_min` and `lambda_max` MUST be read with a
numeric-coercing `ParamDict::getNumber`-equivalent at every receiver — CPU
`plugins/integrators/spectral_path_tracer.cpp`, the GPU `path_tracer` branch and
the CLI GPU dispatch in `apps/main.cpp`, and the bindings — never the exact-type
`getFloat`. `output_mode` is read as a string; integer and decimal spellings of
the same bound MUST select the same band, asserted on every backend.

**Defaults (frozen 2026-09-22, lead may adjust):** the single canonical
omitted-band default for every backend is `[kLambdaMin, kLambdaMax] = [360, 830]`
nm` (`include/astroray/spectrum.h`; the existing CPU `SpectralPathTracer` fallback)
— not a new arbitrary default. The GPU binding's and the CLI's `380/780` defaults
change to this; unset-path CPU and GPU tests assert the same band, and an explicit
caller range always overrides.

**Output modes:** the accepted v1 enum is `xyz`, `rgb`, `srgb`, `luminance`.
Explicit over inferred — a non-empty `output_mode` governs; when empty the backend
infers `luminance` iff `[lambda_min, lambda_max]` is not contained in the visible
band `[379.5, 780.5]` nm, else `xyz` (the existing GPU rule, frozen). A mode
outside the enum fails hard before rendering, never a silent fallback; every
`(backend, mode)` pair is implemented or rejected explicitly. The CPU `path_tracer`
ignores `output_mode` today and must implement or reject every mode; the ReSTIR
driver and the direct GPU binding share the same string contract (validate all
four, map each to its payload, reject the rest). The direct binding's legacy
`use_luminance_output` maps `true`→`luminance`, `false`→`xyz` when `output_mode`
is absent; passing both is an error.

**Lifecycle:** band/mode configuration is transactional. `set_wavelength_range`
and `set_output_mode` must rebuild/re-create the active CPU integrator (today they
only stage params, so a range set after `set_integrator()` is silently ignored) or
be staged and applied atomically on the next dispatch. Every dispatch sets an
explicit mode and re-derives band/mode from current config; no cached `useLum` or
Blender reused-renderer state may leak across visible↔non-visible transitions.
Tests drive sequential band changes (visible→IR→visible) on a reused renderer.

**Output-mode payload contract v1 (frozen 2026-09-22, lead may adjust):** every
mode emits a C-contiguous `float32` array shaped `(H, W, C)`, row 0 = top, column
0 = left, channels in the order named; matched CPU/GPU payloads compare shape,
channel order and transform, not just pixels. Values are raw linear (no display
transform, no clamp) unless the mode defines one; observer is CIE 1931 2° (CIE 15:2004).
- `xyz` — C=3, `(X, Y, Z)` in 1931 2° coordinates; identity transfer, no clamp.
- `rgb` — C=3, `(R, G, B)` linear sRGB primaries, D65 white (x=0.3127, y=0.3290);
  the XYZ→linear-sRGB matrix is the IEC 61966-2-1 / BT.709 D65 matrix
  `[3.2406, -1.5372, -0.4986; -0.9689, 1.8758, 0.0415; 0.0557, -0.2040, 1.0570]`
  (frozen), applied after XYZ; identity transfer, no clamp.
- `srgb` — C=3, same primaries/white/matrix as `rgb`, then the IEC 61966-2-1
  sRGB OETF (`12.92 v` for `v <= 0.0031308`, else `1.055 v^(1/2.4) - 0.055`);
  clamped to `[0, 1]` (the only clamping mode).
- `luminance` — C=1, relative luminance (the 1931 2° `ȳ` projection); identity
  transfer, no clamp.

**Provenance and carriers:** every output carries versioned metadata
`band_contract = 1`: `lambda_min_nm`, `lambda_max_nm`, `output_mode`,
`observer`/`transform`, `units` (`relative spectral radiance`, dimensionless),
backend id and seed. Carriers differ and each entrypoint declares its own: Python
bindings and `Renderer.render()` return a result record with `pixels` (raw
ndarray) and `metadata` (the mapping), never a bare array; the CLI writes a JSON
sidecar beside `--output` (same basename) and embeds the same fields as PNG text
chunks; Blender F12/viewport attach the mapping to result metadata and write the
same sidecar next to a saved image, re-emitting on every reused-renderer
dispatch. Matched CPU/GPU outputs compare raw pixels and every metadata field;
bounds, mode, observer and units must match exactly, pixels within declared
sampling uncertainty. Runtime tests assert each carrier exists and round-trips.

#### Phase 1 — Trace callers and defaults

Trace all callers/defaults with the project index; record the contract-v1 matrix
(every entrypoint above with file:line and target; omitted/integer/decimal/invalid
bounds; visible/IR bands; explicit/inferred `output_mode`). Reuse existing tools.

#### Phase 2 — Architecture and review gate

Astra architecture plus independent high-tier review accepts or amends v1
(compatibility, validation, migration, file ownership) before implementation;
numerical changes cite the established spectral method.

#### Phase 3 — Implement the accepted contract

Implement only the accepted contract: numeric-coercing bound reads, canonical
defaults, mode validation/support, transactional configuration, raw payload and
metadata, with runtime tests for integer-vs-decimal equivalence, invalid-mode
failure, unset-path CPU/GPU equality, sequential band changes and carrier
round-trip.

#### Phase 4 — Measurement and visual evidence

Save matched CPU/GPU raw outputs and metadata; compare provenance fields and
inspect visible/band-output renders. Measure with declared units, sampling
uncertainty and existing physical gates, not blanket RGB.

#### Phase 5 — Delivery gates

Caller/binding review, focused regressions, GPU lock, imported-module identity,
independent sign-off and evidence-backed docs.

---

## Acceptance criteria

- [ ] A contract-v1 matrix names every public entrypoint with file:line and
      target, for omitted/integer/decimal/invalid bounds, visible/IR bands, and
      explicit/inferred `output_mode`.
- [ ] Both bounds use a numeric-coercing getNumber-equivalent in every backend;
      integer-vs-decimal equivalence tests pass on CPU and GPU.
- [ ] Unset CPU and GPU renders use the canonical `[360, 830] nm` default/band.
- [ ] `output_mode` accepts only `xyz`/`rgb`/`srgb`/`luminance`; explicit
      overrides inference; an out-of-enum mode fails hard; every unsupported
      `(backend, mode)` is rejected, not ignored; the ReSTIR driver and the direct
      GPU binding share the enum (legacy bool `true`→`luminance`, `false`→`xyz`;
      both set is an error).
- [ ] Setting band/mode after `set_integrator()` takes effect; sequential
      visible→IR→visible on a reused renderer never leaves stale state.
- [ ] Matched CPU/GPU raw outputs carry `band_contract = 1` metadata (bounds,
      mode, observer/transform, units, backend id, seed), agree on every field,
      and match the per-mode shape/channel/transform contract within declared
      sampling uncertainty.
- [ ] Each entrypoint delivers its declared carrier (binding record, CLI
      sidecar/PNG chunks, Blender result metadata) and a test round-trips it.
- [ ] Astra architecture plus independent high-tier review decides compatibility,
      validation and any migration before implementation; numerical changes cite
      the established spectral method.
- [ ] Delivery gates pass: caller/binding review, focused regressions, GPU lock,
      imported-module identity, independent sign-off and evidence-backed docs.

---

## Non-goals

- No astrophysics activation.
- No spectral-core replacement.
- No new arbitrary band default.
- No output mode outside the v1 enum.
- No silent ignore of an unsupported `(backend, mode)` pair.
- No reachable backend, including ReSTIR, may bypass the v1 contract.
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

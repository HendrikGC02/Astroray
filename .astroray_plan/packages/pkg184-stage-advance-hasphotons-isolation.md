# pkg184 — `template<bool HasPhotons>` isolation of the photon-caustic KNN gather in the bucketed shade kernel

**Pillar:** 5 (GPU performance)
**Track:** A (register-pressure work; requires cuobjdump + perf gates)
**Status:** done (PR #597, 2026-08-12 — every HasPhotons=false shade variant strictly below baseline: STACK −256/−256/−128/−128 B across `<F,F>/<F,T>/<T,F>/<T,T>`; all HasPhotons=true variants byte-identical to baseline; REG:254 unchanged; non-photon glass-sphere shade kernel −2.76% wall vs +0.50% byte-identical control; base = current main e6b9f24 incl. pkg187 dispersion)
**Estimated effort:** M
**Depends on:** pkg157 `template<bool Deferred>` and pkg178 Stage-3b
`template<bool HasPrincipled>` — this is the third application of the same
isolation lever in `src/gpu/wavefront/stage_advance.cu`.

## Problem

`src/gpu/wavefront/stage_advance.cu` inlines the photon-map caustic KNN
gather (`photonGridGatherKnn(photonGrid, rec.point, 50, 1.1f, found)`) into
the shade half that `stageShadeBucketedKernel` compiles — behind a **runtime**
guard (`bounce == 0 && hasPhotonGrid && …`). ptxas must therefore allocate
registers/stack for the 50-neighbour gather's live set in every instantiation
of the REG:254-pinned shade kernel, for a feature that (a) only ever fires at
bounce 0 and (b) is inactive in the large majority of scenes.

## Why it's plausible-value

The identical pattern paid off twice in this file: pkg178 Stage-3b's
`HasPrincipled` isolation recovered a +52% regression on non-Principled
scenes. The shade kernel is register-saturated (see
`wavefront-shade-kernels-register-saturated` memory / pkg174 ledger), so any
live-state reduction either lowers spills or buys headroom for future lobes.

## Work

1. Add `template<bool HasPhotons>` (composing with the existing
   `<bool Deferred, bool HasPrincipled>`) with `if constexpr` around the
   gather; dispatch on `hasPhotonGrid` at launch.
2. Measure per-variant REG/STACK via `cuobjdump` post-link (NOT `ptxas -v`)
   and wall-clock on the standard gate scenes (min-of-N with GPU burn-in per
   `gpu-perf-ab-clock-drift` memory), photon and non-photon scenes.
3. Gates: photon-caustic parity tests unchanged
   (`tests/test_pkg55_c5_photon_wavefront.py`, `tests/test_gpu_caustic_parity.py`);
   no regression on non-photon scenes; cubin variant count doubles — confirm
   compile time stays acceptable.

Note: instantiation count doubles (2→4 kernel variants per templated axis
product). If compile time or cubin size becomes a concern, gate the
`HasPhotons=true` variants behind the same launch-side selection the
Principled split uses.

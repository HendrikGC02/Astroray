# pkg251 — Spectral band parameter reachability across callers

**Pillar:** 5 (renderer interoperability and spectral foundations)
**Track:** A
**Status:** OPEN — contract audit and detailed architect review before implementation
**Estimated effort:** S/M, confirm after audit
**Depends on:** pkg250 standalone dispatch repair; existing spectral core

## Evidence and goal

The 2026-09-06 full-rebuild investigation found differing default band contracts:
CPU SpectralPathTracer uses 360–830 nm; the production Python GPU caller uses
380–780 nm and derives output mode from its band. The standalone CLI parses an
integer literal as an integer ParamDict value, while getFloat accepts a float.
Thus decimal wavelength arguments and integer-looking arguments may not reach
the same band. These behaviors predate pkg250; that repair mirrors the current
GPU binding and does not establish complete band parity.

Audit explicit/default wavelength bounds and output_mode from CLI, Python and
Blender to CPU and GPU dispatch. Establish a documented contract that preserves
visible-color workflows and deliberate infrared/band-aware outputs. Separate a
parameter representation bug from an intentional spectral integration domain.
Do not choose new defaults merely to make a reference image pass. Reuse the
existing ParamDict::getNumber and tests/test_integrator_float_param.py contract
where compatible; do not add a parallel numeric parameter API.

Additional gate investigation: the existing GPU luma path accumulates equal
XYZ components and then converts XYZ to linear sRGB. Equal XYZ (E-white) is not
D65-neutral sRGB: matrix row sums produce (1.2048, 0.9484, 0.9087) times the
scalar signal. Pkg250's first exact-gray PNG assertion therefore failed; Terra
confirmed the caller was correct. The replacement reachability test compares
explicit RGB (zero CMF signal beyond 830nm) with positive band-radiance output
in the same 900–910nm scene. Decide scalar-output units and display/metadata
semantics in this audit; do not enshrine the tint as the desired scientific API.
The initial failed log remains `gpu-focused.log` in the rebuild artifacts.

## Bounded phases and acceptance — UNRUN

1. Trace all callers and defaults with the project index. Record a contract
   matrix for omitted, integer, decimal and invalid bounds; visible/IR bands;
   explicit and inferred output mode. Reuse existing spectral test/harness tools.
2. Astra architecture plus independent high-tier review decides compatibility,
   validation and any migration before implementation. Cite the established
   spectral method for numerical changes; no new transport algorithm is implied.
3. Implement only the accepted parameter/default contract. Add runtime tests
   proving values reach the intended backend, including invalid-input behavior.
4. Save matched CPU/GPU raw outputs and metadata; inspect visible renders and
   appropriate band-output visualizations. Measure effects with declared units,
   sampling uncertainty and existing physical gates, not a blanket RGB metric.
5. Caller/binding review, focused regressions, GPU lock, actual imported-module
   identity, independent sign-off and evidence-backed docs are delivery gates.

## Non-goals and routing

No astrophysics activation, spectral-core replacement, new arbitrary band default,
or claim that current output is scientific instrument calibration. Filing does
not preempt pkg241/240 or the mapped-texture sequence. Pkg251 preserves later
research foundations while Pillar 4 stays PAUSED.

# #822 — coordinate-side non-affine math: design note

Lane batchR, 2026-09-20. Decision input for pkg277.

## Problem
`Texture Coordinate -> Separate XYZ -> Math(Sin) -> Combine XYZ -> Noise` warps the
procedural's input coordinate non-affinely. The affine subset is handled by
`_resolve_affine_coordinates` (pkg230b). Non-affine chains are warned and dropped
on both backends: the CPU calls `child->value(uv, p)` with the resolved `p` and has
no hook to transform it per shade; the GPU pkg190 bake evaluates the texture at
grid points.

## Options

| | A: coordinate as VM input (`OP_LOAD_PROC`, HD procedural ports) | B: CPU coordinate-program wrapper, GPU bake |
|---|---|---|
| CPU | shade point becomes an `svm_eval` input; procedurals evaluated by new HD ports | `CoordProgramTexture` wraps the procedural child: `p' = svm_eval(coordProg, {p})`, then `child->value(p'.xy, p')`; existing evaluators |
| GPU | ports run in the shade kernel, `<HasProgram=true>` only | none: pkg190 `bakeProceduralTexId(wrapper)` bakes `wrapper->value()` like any procedural |
| New code | HD ports of ~1170 lines of CPU procedurals (`advanced_features.h` :489–1664: Gradient, Wave, Magic, Voronoi ~370, Brick, WhiteNoise, NoiseCycles, Musgrave) + a second CPU/HD parity surface | one ~40-line class, one binding, compiler leaf + 2 nodes, addon wiring |
| REG | code added to `svm_eval`, which is inlined into all 64 `HasProgram=true` kernels (REG 254, STACK 4512–8736 today). Needs `__noinline__` isolation; unmeasured | **0 device code**: fleet and `HasProgram=true` kernels byte-identical by construction |
| Fidelity | exact per shade; any coordinate source | exact on CPU; GPU = 64³ nearest bake of the warped field; UV / Generated bases only (Object/Camera: CPU-exact, GPU degraded + warning, as today) |

## Numbers
- REG/STACK today (build 0f4f62d1, sm_120): all 128 `stageShadeBucketedKernel` specializations REG 254; `HasProgram=true` STACK 4512–8736 B, unchanged vs main after #826's `__noinline__` second-input sampler (0 functions changed of 349). This is the kernel A would have to extend; B leaves it untouched.
- Bake fidelity for B, worst case (numpy model: Cycles `svm/checker.h` checker, scale 5, warp `x' = sin(k·g.x)` on the Generated plane g.z = 0.5, 320² shading points; bake = value at voxel centres, nearest fetch, as pkg190):

| k | 64³ pixel mismatch | 64³ \|mean err\| | 128³ mismatch | 128³ \|mean err\| |
|---|---|---|---|---|
| 2 | 3.98 % | 0.0037 | 1.86 % | 0.0054 |
| 6 | 9.39 % | 0.0004 | 4.62 % | 0.0002 |
| 12 | 14.21 % | 0.0006 | 7.07 % | 0.0028 |
| 24 | 25.64 % | 0.0017 | 15.04 % | 0.0026 |

  Region means stay within 0.6 %; per-pixel error is edge aliasing that grows with
  warp frequency. Smooth fields (Noise) err far less. Same accepted tradeoff as
  pkg190 for direct procedurals.
- Scalar `Math(Sin/Cos/Tan)` needs no evaluator change: a Separate XYZ output is a
  broadcast `GVec3`, so the compiler can emit the existing `OP_VEC_MATH`
  `SINE/COSINE/TANGENT` (Cycles `svm/math_util.h`, already cited in `shader_vm.h`).

## Decision
**B**, as pkg277. It fits the brief's REG constraint by construction and reuses the
Cycles-cited evaluators (no new algorithm, CLAUDE.md §6). A stays the route for
unbounded coordinate sources and high-frequency warps if real scenes need them.

Not implemented in batch R: B adds a new engine class and Python binding (ABI review),
compiler and addon changes, and its own build and GPU verification. #825/#826 were
already built and verified, so they ship without waiting for it.

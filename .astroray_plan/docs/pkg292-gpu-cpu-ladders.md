# pkg292 — GPU/CPU divergence ladders

## #876 — Disney under a dedicated sun (lane ah1, 2026-09-27)

Scene: 80×80 ground, `disney` base 0.5, one dedicated sun (0.526°, strength 1),
camera 20 up looking down, 48², 32 spp, mean over the [4:44] crop. Baseline
= main build 9330e5d7. Probe: `astra_run/batchU/ah1/ladder876.py`; Cycles
reference: `astra_run/batchU/ah1/cycles_ref.py` (Blender 5.2, Principled base
0.5 / roughness 0.5 / IOR 1.5, 256 spp).

| Rung (light: sun ↓) | CPU | GPU (baseline) | GPU/CPU | Cycles |
|---|---|---|---|---|
| lambertian control | 0.1591 | 0.1592 | 1.00 | — |
| disney default | 0.1853 | 0.3178 | **1.715** | 0.1965 |
| diffuse only (specular 0) | 0.1542 | 0.3178 | **2.06** | 0.1592 |
| metallic 1 | 0.4762 | 0.4768 | 1.00 | 0.5628 |
| roughness 1 | 0.1516 | 0.1121 | 0.74 | — |
| roughness 0.2 | 0.2430 | 0.3750 | 1.54 | — |

Light ladder (disney default): sun ↓ 1.715, sun oblique (0.3,−1,0.2) CPU
0.1634, area 0.1214 → 0.1604 = 1.32, env 0.1522 → 0.1460 = 0.96.

**Convicted term.** The GPU ignores `specular` (default == diffuse-only) and
the metallic rung is already exact. `DisneyPlugin::closureGraph()` lowered an
opaque Disney to diffuse(w=1) + GGX conductor(w=1, color = baseColor) and
`gpu_closure_graph_eval` normalises by W=2; the conductor lobe evaluates as
`gpu_disney_eval` with metallic forced to 1. So the GPU renders
0.5·Lambert + 0.5·base-tinted metal instead of Burley diffuse + F0=0.04
dielectric specular: predicted 0.5·0.1591 + 0.5·0.4762 = 0.3177, measured
0.3178. Under a near-delta sun the metal's GGX peak dominates (1.7×); under a
uniform env the two albedos are similar (0.96), which is why the furnace and
env gates never caught it.

**Which side is right.** CPU: Cycles says 0.1965 (default) / 0.1592 (diffuse
only); CPU 0.1853 / 0.1542 (−5.7 % / −3.1 %, Burley diffuse + Disney
compensation vs Cycles Lambert + multiscatter GGX); baseline GPU +62 % / +100 %.

**Fix.** Opaque Disney emits ONE conductor closure carrying the real metallic
(`plugins/materials/disney.cpp`); `gpu_closure_as_material` evaluates a
single-closure Disney graph as the monolithic `gpu_disney_eval` with the
parent's specular/sheen/clearcoat/subsurface params, which
`src/gpu/scene_upload.cu` now uploads. `gpu_disney_eval` is the term-for-term
twin of `DisneyPlugin::eval` (Burley 2012/2015; pkg141/pkg152 mirrors).
Mixed-transmission Disney (0 < t < 0.999) keeps the old multi-closure lowering
(same class of approximation; not in this rung set).

Gate: `tests/test_pkg292_disney_sun_parity.py` — 7 lobe rungs × {sun ↓, sun
oblique}, 3 seeds, GPU/CPU ±5 %; default/diffuse rungs ±8 % of Cycles.
Post-fix GPU numbers: pending the ah1 build.

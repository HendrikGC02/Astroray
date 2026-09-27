# pkg292 GPU/CPU divergence ladders

## #862 — session_n1_envmap_cornell red (lane ah2, 2026-09-27)

Setup: 64x64, 64 spp, max_depth 8, seed 424242, linear means. GPU = main
360ed6e3 CUDA build (wavefront and megakernel agree to 5 digits on every rung).
Rung = scene with the named materials kept, the rest swapped to the floor
lambertian; `no_bg` / `no_area` / `no_emit` remove the background, the ceiling
lamp, the emissive sphere; `dN` = max_depth N. Harness:
`astra_run\ah2\ladder862.py`.

| rung | CPU oracle (baseline) | GPU | GPU/CPU |
|---|---|---|---|
| full | 0.2113 / 0.2259 / 0.2670 | 0.2372 / 0.2285 / 0.2717 | 1.122 / 1.012 / 1.018 |
| all lambertian | 0.2591 / 0.3027 / 0.3357 | 0.2593 / 0.3028 / 0.3358 | 1.001 / 1.001 / 1.000 |
| d1 (camera + direct) | 0.1577 / 0.1749 / 0.1949 | 0.1589 / 0.1746 / 0.1946 | 1.008 / 0.998 / 0.998 |
| keep dielectric | 0.2473 / 0.3048 / 0.3532 | 0.2636 / 0.3193 / 0.3652 | 1.066 / 1.047 / 1.034 |
| keep dielectric, no_bg no_area | 0.0892 / 0.0714 / 0.0443 | 0.0974 / 0.0780 / 0.0482 | 1.092 / 1.092 / 1.087 |
| keep dielectric, env only, d2 | 0.0549 / 0.1098 / 0.1646 | 0.0550 / 0.1099 / 0.1647 | 1.000 |
| keep dielectric, emitter only, d2 | 0.0817 / 0.0655 / 0.0406 | 0.0869 / 0.0696 / 0.0431 | 1.063 |
| keep disney | 0.2542 / 0.2651 / 0.3034 | 0.2634 / 0.2639 / 0.3034 | 1.036 / 0.995 / 1.000 |
| keep metal / thin_glass / closure_matte | — | — | within 0.1 % |

Reading: env lookup, env miss, lamp NEE and emissive hits agree (all-lambertian,
env-only rungs). The dielectric rung carries ~2/3 of the red gap and is flat
across channels and lamp-only; its diff image is the glass wall itself, black on
the CPU oracle and lit (TIR reflection of the box) on the GPU.

**Convicted term: CPU wavefront oracle, `advance_one_bounce`
(`src/cpu/wavefront/path_kernel.cpp`).** The driver reuses one `HitRecord`
across bounces; delta BSDFs set `rec.isDelta` in `sampleSpectral`; `bvh->hit`
never clears it, so every vertex after a glass/mirror bounce skipped lamp NEE.
Independent reference: production `pathTraceSpectral` (separate integrator,
fresh `HitRecord` per bounce) — oracle/production on the dielectric rung
0.939 / 0.955 / 0.966 before, 0.994 / 0.997 / 0.997 after; full scene 0.994.
Fix: a fresh `HitRecord` per bounce (review: uvLayers, uvScaleU/V and hair_u/v leaked the same way; `test_pkg292_oracle_hitrecord_leak` guards the UV-layer leak, 0.975 -> 0.995).

After the fix (5 seeds): full-scene GPU−CPU gap R 0.0113–0.0129, G ≤ 0.0023,
B ≤ 0.0009 (red ratio 1.05–1.058); `world_max_bounces=0` R 0.0091; dielectric
rung GPU/CPU 1.006 / 1.003 / 1.002.

**Residual: GPU Disney** (red base 0.8/0.2/0.3): keep-disney rung red 1.036,
env-only back wall red 1.08, grows with depth (d1 +0.0014, d2 +0.0044, full
+0.009). Out of this lane's scope (Disney files owned by pkg293); the full-rung
red ≤ 1.05 test is xfail on it.

## #832 — env texel-centre lookup (lane ah2, 2026-09-27)

Cycles samples image textures at texel centres: `interp_bilinear` in
`intern/cycles/kernel/device/cpu/image.h` (Apache-2.0) does
`x = u*W - 0.5; ix = floor(x); tx = x - ix`, wrapping for EXTENSION_REPEAT
(environment textures). All four Astroray env lookups used `floor(u*W)` (texel
edges): CPU `EnvironmentMap::lookup` / `evalSpectral`, GPU `gpu_envmap_lookup` /
`gpu_env_miss_spectral`. Now one helper per backend
(`EnvironmentMap::bilinearTexels`, `gpu_envmap_bilinear_texels`): texel-centre,
u wraps, v clamps (Cycles also wraps v; the pole rows carry ~zero solid angle).
`pdf()` / `sample()` stay texel-footprint based (piecewise-constant density).
Not part of #862 (that scene uses a constant background colour). Probe:
1-px sawtooth, texel-edge vs Cycles differ by 0.59 rel; engine now 5e-6.

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

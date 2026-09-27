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
Fix: reset `rec.isDelta` per bounce.

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

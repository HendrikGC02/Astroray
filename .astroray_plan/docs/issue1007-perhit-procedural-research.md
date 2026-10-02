# #1007 GPU per-hit procedural textures: research note (2026-10-02)

Source: Blender Cycles (`blender/blender` main, `intern/cycles`, fetched 2026-10-02). These are the files the pkg115
CPU evaluators already ported; #1007 moves that port into one host + device header instead of writing a second one.

| Function | Cycles file | License |
|---|---|---|
| Jenkins lookup3 `hash_uint*`, `hash_float*_to_float`, PCG3D `hash_pcg3d_i` | `util/hash.h` | Apache-2.0 |
| `perlin_3d`, `snoise_3d` (fmod 100000 precision guard), `noise_scale3` | `kernel/svm/noise.h` | BSD-3-Clause (Sony Pictures Imageworks 2009-2010, adapted from OSL; Blender Foundation 2011-2022) |
| `noise_fbm`, multifractal, hybrid, ridged, hetero terrain | `kernel/svm/fractal_noise.h` | Apache-2.0 |
| `noise_texture_3d`, `random_float3_offset` | `kernel/svm/noisetex.h` | Apache-2.0 |
| `svm_wave` (bands / rings, sine / saw / triangle, fBM distortion) | `kernel/svm/wave.h` | Apache-2.0 |
| `voronoi_f1`, `voronoi_smooth_f1`, `voronoi_f2`, `voronoi_distance_to_edge`, `voronoi_n_sphere_radius`, `fractal_voronoi_x_fx` | `kernel/svm/voronoi.h` | Apache-2.0; smooth F1 and distance to edge after Inigo Quilez 2013 (MIT) |

All three licences are compatible with Astroray's. Code: `include/astroray/procedural_tex.h` (cited in its header).

## What changed

* The CPU classes (`NoiseTextureCycles`, `WaveTexture`, `VoronoiTexture`, `WhiteNoiseTexture` in
  `include/advanced_features.h`) now hold a parameter struct and call the header's HD functions. The bodies are the
  pkg115 code with the same operations in the same order: `std::` calls became the float C functions they resolve to,
  `Vec3 / s` became an explicit per-component division (`GVec3::operator/` multiplies by the reciprocal), and the
  Voronoi neighbour cell ids keep the int -> float -> int round trip the port had.
* `random_float3_offset` is a table of its five values (seeds 0..4) computed as a fused multiply-add. Whether a
  compiler fuses `100 + hash * 100` depends on inlining: the production MSVC build (`/arch:AVX2 /fp:fast`) of main
  fused it (four of the fifteen values differ by an ulp from the two-rounding result; found by comparing
  `eval_texture_at_3d` between the main and branch builds), g++ `-mfma` folded the constant-seed call unfused, nvcc
  fuses. The fractal octaves amplify one ulp of offset to ~1e-4 in the noise, so the table pins the MSVC value.
* GPU: `scene_upload.cu perHitTexId` lowers a Noise / Wave / Voronoi (and a pkg277 coordinate program over them) with
  Object or Generated coordinates on a surface consumer into a `GImageTexture` with `procId >= 0`; the
  `<HasProgram=true>` shade kernel evaluates it at the hit (`gpu_progInputEval` -> `gpu_procTexEval`,
  `src/gpu/wavefront/proc_tex_eval.cu`). The 64^3 bake stays for other texture types, UV coordinates and emitters, and
  prints `[#1007] DEGRADED` when used.

## Host bit-identity check

A scratch harness evaluated 112 parameter sets x 404 points (all noise types / detail / distortion, all wave
modes / profiles, Voronoi features 0-6 x 4 metrics x detail x normalize x output) through the old and new headers,
printing hex floats: identical with `g++ -O2` (and with `-O2 -mavx2 -mfma` for a two-rounding table). The production
MSVC build is compared with main through `eval_texture_at_3d` (75 parameter sets x 300 points) in the PR.
Under `-ffast-math` both the old and the new build differ from the exact build (old vs exact up to 1.5 at saw-profile
discontinuities), so a fast-math build is not bit-stable under any refactor; the production MSVC build is checked
empirically against the main build in the PR.

## Semantics kept from the CPU (the oracle)

* An op-VM input is evaluated at its parent ProgramTexture's resolved (and Mapped) point; the input's own coordinate
  mode and Mapping are not applied (`ProgramTexture::eval` calls `inputs_[i]->value(uv, p)`). The GPU bake applied the
  child's own Mapping instead; the per-hit path follows the CPU.
* Object coordinates are the world hit point (#1006 covers object-local); Generated is clamped to [0, 1].
* Voronoi exposes Distance (as a two-colour lerp) or Color; there is no Position output on the CPU.

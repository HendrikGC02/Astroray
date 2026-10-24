# #1160 - sp07 tumbler: CPU vs GPU dark wedge (root cause)

Lane pkg325, 2026-10-25. Baseline: main `9b5ab079` minus #1151 (`build_cuda` pyd, sha bd651551; no engine change in
between that touches this path). Scene: pkg324 `sp07_tumbler_bounce_cap.blend`. Evidence:
`%LOCALAPPDATA%\astroray-evidence\2026-10-24\pkg325\{s1..s5,tools}`.

## Cause
Not a nested-dielectric / wall-order / bounce-accounting bug. The scene has **exactly coincident faces**:

1. the tumbler base disk (z = z0 = 0.5) is coplanar with the plinth top (z = 0.5);
2. the profile's rim ring (r 0.48..0.5, then 0.5..0.4 at z = 1.8) overlaps itself with opposite winding;
3. the revolved solid is wound inward (signed volume -0.380; `recalc_face_normals` failed on the self-overlapping
   profile), so every "outside" hit reads as an exit (eta 1.5 -> 1.0), and Blender's smooth corner normals sit ~42 deg off the
   facet normals - the critical angle for that exit, so the wedge boundary is sharp.

At equal hit distance the software BVH (CPU, and the GPU `ASTRORAY_GPU_TRAVERSAL=software`) and OptiX hardware traversal
(GPU default, pkg299) pick different triangles. The `_gpu_optix_ray_ab` probe on 400k random in-tumbler rays: 0 hit/miss
mismatches, 2.4 % same-t / different-prim (plinth top vs glass base, pole fans). When the glass base wins the path exits
into the closed plinth and never reaches a light: a deterministic dead wedge on the GPU only.

## Attribution (replay of the addon's engine calls, 320x240, tumbler box, pixels < 0.02 on a white world, cap 12)
| variant | CPU dead | GPU dead | box mean CPU / GPU |
|---|---|---|---|
| as authored, OptiX | 0 % | 6.2 % | 0.2190 / 0.2194 |
| as authored, `ASTRORAY_GPU_TRAVERSAL=software` | 0 % | 0 % | 0.2190 / 0.2190 |
| tumbler lifted 2 mm | 0 % | 0 % | 0.2173 / 0.2173 |
| tumbler lifted 10 mm | 0 % | 0 % | 0.2187 / 0.2191 |
| flat normals / winding flipped to outward | agree | agree | (diffm 0.0036 / 0.0048 vs 0.0116 as authored) |

Dead fraction by cap, as authored (GPU): 4: 8.1 %, 6: 7.0 %, 12: 6.5 %, 64: 6.5 %; CPU 0 % from cap 4; caps 2/3 are
dead (~60 %) on both backends, identical (premise confirmed: terminate at low depth makes a dead region on CPU and GPU alike).

HDRI scene (the #1160 cells), 3 seeds x 256 spp: cell (1,2) CPU 0.219 / GPU 0.131 as authored -> 0.157 / 0.170 lifted. Cell
(1,1) CPU 0.115 vs GPU 0.059 lifted is sun-caustic fireflies (CPU pixels to 430, GPU 37): clamped at 3 the means are 0.057 / 0.056.

## Which backend is right
Neither: a tie between distinct coincident triangles is undefined in every tracer. Cycles has no tie rule either
(`intern/cycles/kernel/geom/triangle_intersect.h` accepts a hit by `tmin/tmax` + visibility only; Embree / OptiX /
BVH order decide). The CPU/GPU residual after the geometry is made well-posed (>= 1 mm gap, outward winding) is Monte-Carlo
noise only. No engine change; the defect is the scene (pkg324 builder `build_sp07`, profile `(ro, z0+h)` duplicated point and
z0 = plinth top). The pkg325 acceptance scene must keep a gap under the glass, build with outward winding (assert signed
volume > 0), and have no self-overlapping profile.

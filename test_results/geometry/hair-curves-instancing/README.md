# Hair curves under instancing (#963)

`hair_tuft_before_after.png`: corpus v2 `v2_camera_geometry` (perspective, ortho) hair tuft,
3x nearest-neighbour crops. Columns: Cycles 1024 spp reference, Astroray CPU, Astroray GPU on
main (bare scalp: the scene's collection instances put the flat scene under a TLAS and the GPU
skipped every curve), Astroray GPU with the fix. Hair-tuft ROI GPU/CPU after the fix:
1.014/1.012/1.002 (perspective), 0.984/0.991/0.994 (ortho). Astroray stays 0.80-0.97 of Cycles
on both backends (#1037).

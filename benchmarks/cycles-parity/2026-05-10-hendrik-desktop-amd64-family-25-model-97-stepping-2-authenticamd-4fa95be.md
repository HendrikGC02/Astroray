# Cycles Parity Summary: `2026-05-10-hendrik-desktop-amd64-family-25-model-97-stepping-2-authenticamd-4fa95be.csv`

## Time to Samples (ms)

| Scene | cycles-cpu | cycles-cuda | astroray-cpu | astroray-gpu |
|---|---|---|---|---|
| bmw27 | 138051.651 | 13444.425 | skip: astroray_blend_import_not_implemented | skip: astroray_blend_import_not_implemented |
| classroom | 486451.691 | 31167.653 | skip: astroray_blend_import_not_implemented | skip: astroray_blend_import_not_implemented |
| cornell | 10648.201 | 4182.948 | 15389.610 | 800.741 |
| junkshop | 225573.385 | 30576.592 | skip: astroray_blend_import_not_implemented | skip: astroray_blend_import_not_implemented |
| monster | skip: exit:1 00:01.594  blend            | Read blend: "C:\Users\hgcom\OneDrive\Astroray\Astroray_repo\Astroray\benchmarks\cycles-parity\scenes\cache\monster\UDIM_monster\udim-monster.blend" Traceback (most recent call last):   File "C:\Users\hgcom\OneDrive\Astroray\Astroray_repo\Astroray\benchmarks\cycles-parity\results\monster-cycles-cpu-tryop9cg\warmup.py", line 19, in <module>     bpy.ops.render.render(write_still=True)     ~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^ RuntimeError: Error: Cannot render, no camera  Custom Raytracer 3.0.0 loaded Astroray renderer addon registered Error: Cannot render, no camera Astroray renderer addon unregistered Blender 5.1.0 (hash adfe2921d5f3 built 2026-03-17 01:37:32)  Blender quit | skip: exit:1 00:01.625  blend            | Read blend: "C:\Users\hgcom\OneDrive\Astroray\Astroray_repo\Astroray\benchmarks\cycles-parity\scenes\cache\monster\UDIM_monster\udim-monster.blend" Traceback (most recent call last):   File "C:\Users\hgcom\OneDrive\Astroray\Astroray_repo\Astroray\benchmarks\cycles-parity\results\monster-cycles-cuda-gdcuxj3n\warmup.py", line 19, in <module>     bpy.ops.render.render(write_still=True)     ~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^ RuntimeError: Error: Cannot render, no camera  Custom Raytracer 3.0.0 loaded Astroray renderer addon registered Error: Cannot render, no camera Astroray renderer addon unregistered Blender 5.1.0 (hash adfe2921d5f3 built 2026-03-17 01:37:32)  Blender quit | skip: astroray_blend_import_not_implemented | skip: astroray_blend_import_not_implemented |

## Peak Resident Memory (MB)

| Scene | cycles-cpu | cycles-cuda | astroray-cpu | astroray-gpu |
|---|---|---|---|---|
| bmw27 | 582.5 | 704.9 | skip: astroray_blend_import_not_implemented | skip: astroray_blend_import_not_implemented |
| classroom | 1506.2 | 1587.0 | skip: astroray_blend_import_not_implemented | skip: astroray_blend_import_not_implemented |
| cornell | 595.3 | 673.8 | 134.9 | 244.5 |
| junkshop | 7096.2 | 8514.3 | skip: astroray_blend_import_not_implemented | skip: astroray_blend_import_not_implemented |
| monster | skip: exit:1 00:01.594  blend            | Read blend: "C:\Users\hgcom\OneDrive\Astroray\Astroray_repo\Astroray\benchmarks\cycles-parity\scenes\cache\monster\UDIM_monster\udim-monster.blend" Traceback (most recent call last):   File "C:\Users\hgcom\OneDrive\Astroray\Astroray_repo\Astroray\benchmarks\cycles-parity\results\monster-cycles-cpu-tryop9cg\warmup.py", line 19, in <module>     bpy.ops.render.render(write_still=True)     ~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^ RuntimeError: Error: Cannot render, no camera  Custom Raytracer 3.0.0 loaded Astroray renderer addon registered Error: Cannot render, no camera Astroray renderer addon unregistered Blender 5.1.0 (hash adfe2921d5f3 built 2026-03-17 01:37:32)  Blender quit | skip: exit:1 00:01.625  blend            | Read blend: "C:\Users\hgcom\OneDrive\Astroray\Astroray_repo\Astroray\benchmarks\cycles-parity\scenes\cache\monster\UDIM_monster\udim-monster.blend" Traceback (most recent call last):   File "C:\Users\hgcom\OneDrive\Astroray\Astroray_repo\Astroray\benchmarks\cycles-parity\results\monster-cycles-cuda-gdcuxj3n\warmup.py", line 19, in <module>     bpy.ops.render.render(write_still=True)     ~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^ RuntimeError: Error: Cannot render, no camera  Custom Raytracer 3.0.0 loaded Astroray renderer addon registered Error: Cannot render, no camera Astroray renderer addon unregistered Blender 5.1.0 (hash adfe2921d5f3 built 2026-03-17 01:37:32)  Blender quit | skip: astroray_blend_import_not_implemented | skip: astroray_blend_import_not_implemented |

## SSIM to Cycles CPU Reference

| Scene | cycles-cpu | cycles-cuda | astroray-cpu | astroray-gpu |
|---|---|---|---|---|
| bmw27 | 1.000000 | 0.999570 | skip: astroray_blend_import_not_implemented | skip: astroray_blend_import_not_implemented |
| classroom | 1.000000 | 0.998390 | skip: astroray_blend_import_not_implemented | skip: astroray_blend_import_not_implemented |
| cornell | 1.000000 | 0.999963 | 0.953596 | 0.954770 |
| junkshop | 1.000000 | 0.999686 | skip: astroray_blend_import_not_implemented | skip: astroray_blend_import_not_implemented |
| monster | skip: exit:1 00:01.594  blend            | Read blend: "C:\Users\hgcom\OneDrive\Astroray\Astroray_repo\Astroray\benchmarks\cycles-parity\scenes\cache\monster\UDIM_monster\udim-monster.blend" Traceback (most recent call last):   File "C:\Users\hgcom\OneDrive\Astroray\Astroray_repo\Astroray\benchmarks\cycles-parity\results\monster-cycles-cpu-tryop9cg\warmup.py", line 19, in <module>     bpy.ops.render.render(write_still=True)     ~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^ RuntimeError: Error: Cannot render, no camera  Custom Raytracer 3.0.0 loaded Astroray renderer addon registered Error: Cannot render, no camera Astroray renderer addon unregistered Blender 5.1.0 (hash adfe2921d5f3 built 2026-03-17 01:37:32)  Blender quit | skip: exit:1 00:01.625  blend            | Read blend: "C:\Users\hgcom\OneDrive\Astroray\Astroray_repo\Astroray\benchmarks\cycles-parity\scenes\cache\monster\UDIM_monster\udim-monster.blend" Traceback (most recent call last):   File "C:\Users\hgcom\OneDrive\Astroray\Astroray_repo\Astroray\benchmarks\cycles-parity\results\monster-cycles-cuda-gdcuxj3n\warmup.py", line 19, in <module>     bpy.ops.render.render(write_still=True)     ~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^ RuntimeError: Error: Cannot render, no camera  Custom Raytracer 3.0.0 loaded Astroray renderer addon registered Error: Cannot render, no camera Astroray renderer addon unregistered Blender 5.1.0 (hash adfe2921d5f3 built 2026-03-17 01:37:32)  Blender quit | skip: astroray_blend_import_not_implemented | skip: astroray_blend_import_not_implemented |

## Scene Attribution

- Junkshop by Alex Trevino, CC-BY-4.0, Blender Foundation demo files
- BMW27 by Mike Pan, CC-BY-3.0, https://download.blender.org/demo/test/BMW27.blend.zip

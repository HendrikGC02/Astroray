import bpy
cycles = bpy.context.scene.cycles
settings = bpy.context.scene.custom_raytracer

cycles.samples = 16
cycles.preview_samples = 8
settings.use_adaptive_sampling = True

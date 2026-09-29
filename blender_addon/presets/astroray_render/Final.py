import bpy
cycles = bpy.context.scene.cycles
settings = bpy.context.scene.custom_raytracer

cycles.samples = 1024
cycles.preview_samples = 64
settings.use_adaptive_sampling = True

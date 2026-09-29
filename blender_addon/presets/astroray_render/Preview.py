import bpy
cycles = bpy.context.scene.cycles
settings = bpy.context.scene.custom_raytracer

cycles.samples = 128
cycles.preview_samples = 32
settings.use_adaptive_sampling = True

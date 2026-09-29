# Stellar-mass HMXB: Cygnus X-1.
# Mass 21.2 Msun, inclination 27.5 deg (orbital): Miller-Jones et al. 2021,
#   Science 371, 1046, doi:10.1126/science.abb3363.
# Spin 0.998: Zhao et al. 2021, ApJ 908, 117, doi:10.3847/1538-4357/abbcd6
#   report a* > 0.9985; clipped to the addon's 0.998 maximum.
# Model Novikov-Thorne: thin disk (soft state).
import bpy
bh = bpy.context.object.astroray_black_hole

bh.mass = 21.2
bh.spin = 0.998
bh.inclination = 27.5
bh.accretion_model = 'NOVIKOV_THORNE'
bh.show_disk = True
bh.enable_jet = False

# M87*: central black hole of M87.
# Mass 6.5e9 Msun: EHT Collaboration 2019, ApJL 875, L6 (Paper VI),
#   doi:10.3847/2041-8213/ab1141.
# Inclination 17 deg: jet axis angle to the line of sight, EHT Paper V
#   (2019, ApJL 875, L5, doi:10.3847/2041-8213/ab0f43), after Walker et al. 2018.
# Spin 0.94: highest |a*| in the EHT GRMHD library (Paper V); EHT does not
#   measure spin, so this is a library reference value.
# Model ADAF + jet: low-luminosity, jet-launching flow.
# Distance is not a preset value: the addon has no physical-distance property
# (r_obs_M is a world-to-GR scale, not a distance), so it is left untouched.
import bpy
bh = bpy.context.object.astroray_black_hole

bh.mass = 6.5e9
bh.spin = 0.94
bh.inclination = 17.0
bh.accretion_model = 'ADAF'
bh.show_disk = True
bh.enable_jet = True

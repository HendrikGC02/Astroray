# Sgr A*: Milky Way central black hole.
# Mass 4.297e6 Msun: GRAVITY Collaboration 2022, A&A 657, L12,
#   doi:10.1051/0004-6361/202243716 (R0 = 8.277 kpc).
# Inclination 30 deg: EHT Sgr A* Paper V (2022, ApJL 930, L16,
#   doi:10.3847/2041-8213/ac6672): favoured models are MAD with i <= 30 deg.
# Spin 0.94: the highest |a*| in the EHT GRMHD library (Paper V); spin is NOT
#   measured by EHT, so this is a library reference value, not a measurement.
# Model ADAF: Sgr A* is a radiatively inefficient flow (Narayan & Yi 1995).
import bpy
bh = bpy.context.object.astroray_black_hole

bh.mass = 4.297e6
bh.spin = 0.94
bh.inclination = 30.0
bh.accretion_model = 'ADAF'
bh.show_disk = True
bh.enable_jet = False

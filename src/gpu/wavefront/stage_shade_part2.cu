// stage_shade_part2.cu - stageShadeBucketedKernel<HasPrincipled=false, HasTexture=true,
// HasPhotons=false, HasDispersion=both, LP, Program, NormalPerturb>. See the
// "Build-speed split" note near the end of stage_advance_device.cuh.
#include "shade_force_inline.cuh"  // pkg300: must precede every other include
#include "stage_advance_device.cuh"

ASTRORAY_DEFINE_SHADE_PART(2, false, true, false, 0)

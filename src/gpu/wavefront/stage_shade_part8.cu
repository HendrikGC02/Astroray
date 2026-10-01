// stage_shade_part8.cu - stageShadeBucketedKernel<HasPrincipled=true, HasTexture=true,
// HasPhotons=false, HasDispersion=false, LP, Program, NormalPerturb>. See the
// "Build-speed split" note near the end of stage_advance_device.cuh.
#include "shade_force_inline.cuh"  // pkg300: must precede every other include
#include "stage_advance_device.cuh"

ASTRORAY_DEFINE_SHADE_PART(8, true, true, false, 1)

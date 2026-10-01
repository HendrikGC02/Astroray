// stage_shade_part6.cu - stageShadeBucketedKernel<HasPrincipled=true, HasTexture=false,
// HasPhotons=true, HasDispersion=false, LP, Program, NormalPerturb>. See the
// "Build-speed split" note near the end of stage_advance_device.cuh.
#include "shade_force_inline.cuh"  // pkg300: must precede every other include
#include "stage_advance_device.cuh"

ASTRORAY_DEFINE_SHADE_PART(6, true, false, true, 1)

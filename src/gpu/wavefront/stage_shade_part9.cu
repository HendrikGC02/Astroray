// stage_shade_part9.cu - stageShadeBucketedKernel<HasPrincipled=true, HasTexture=true,
// HasPhotons=false, HasDispersion=true, LP, Program, NormalPerturb>. See the
// "Build-speed split" note near the end of stage_advance_device.cuh.
#include "stage_advance_device.cuh"

ASTRORAY_DEFINE_SHADE_PART(9, true, true, false, 2)

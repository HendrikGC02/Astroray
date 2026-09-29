// stage_shade_part4.cu - stageShadeBucketedKernel<HasPrincipled=true, HasTexture=false,
// HasPhotons=false, HasDispersion=false, LP, Program, NormalPerturb>. See the
// "Build-speed split" note near the end of stage_advance_device.cuh.
#include "stage_advance_device.cuh"

ASTRORAY_DEFINE_SHADE_PART(4, true, false, false, 1)

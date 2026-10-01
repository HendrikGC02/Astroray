// stage_shade_part5.cu - stageShadeBucketedKernel<HasPrincipled=true, HasTexture=false,
// HasPhotons=false, HasDispersion=true, LP, Program, NormalPerturb>. See the
// "Build-speed split" note near the end of stage_advance_device.cuh.
#include "stage_advance_device.cuh"

ASTRORAY_DEFINE_SHADE_PART(5, true, false, false, 2)

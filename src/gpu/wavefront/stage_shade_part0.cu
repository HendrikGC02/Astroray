// stage_shade_part0.cu - stageShadeBucketedKernel<HasPrincipled=false, HasTexture=false,
// HasPhotons=false, HasDispersion=both, LP, Program, NormalPerturb>. See the
// "Build-speed split" note near the end of stage_advance_device.cuh.
#include "stage_advance_device.cuh"

ASTRORAY_DEFINE_SHADE_PART(0, false, false, false, 0)

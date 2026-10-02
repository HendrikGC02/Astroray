// stage_shade_fleet_p0.cu - pkg300 fleet shade kernel, HasPrincipled=false.
// See stage_shade_fleet.cuh.
#include "shade_force_inline.cuh"  // must precede every other include
#include "stage_shade_fleet.cuh"

ASTRORAY_DEFINE_SHADE_FLEET(0, __maxnreg__(128))

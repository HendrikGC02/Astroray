// stage_shade_exp_2.cu - pkg300 sweep-only: fully inlined + __maxnreg__(128)
// fleet shade kernel, -Xptxas -O2 (CMakeLists.txt). See stage_shade_exp.cuh.
#include "shade_force_inline.cuh"  // must precede every other include
#include "stage_shade_exp.cuh"

ASTRORAY_DEFINE_SHADE_EXP(2)

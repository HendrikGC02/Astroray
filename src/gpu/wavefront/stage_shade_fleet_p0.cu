// stage_shade_fleet_p0.cu - pkg300 fleet shade kernel, HasPrincipled=false.
// See stage_shade_fleet.cuh.
#include "shade_force_inline.cuh"  // must precede every other include
#include "stage_shade_fleet.cuh"

// Register budget: -maxrregcount=128 on this TU (CMakeLists.txt), not __maxnreg__.
// ptxas makes a kernel __maxnreg__/__launch_bounds__ fatal when any callee stays out
// of line above the cap, and which callees nvcc inlines differs by arch (sm_120
// inlines the whole tree; sm_75/86/89 keep gpu_material_eval_spectral,
// gpu_material_pdf, gpu_closure_graph_sample out of line). -maxrregcount caps every
// function compiled in the TU, so the build never fails; an out-of-line callee only
// costs occupancy.
ASTRORAY_DEFINE_SHADE_FLEET(0, )

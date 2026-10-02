// proc_tex_eval.cu - #1007: the GPU per-hit procedural texture evaluator.
//
// Evaluates a GProcTexture (Noise / Wave / Voronoi, optionally behind a pkg277
// coordinate-program warp) at an already resolved texture point. The math is the
// shared host+device code in astroray/procedural_tex.h, i.e. the CPU evaluator
// itself (Cycles kernel/svm/noise.h, fractal_noise.h, noisetex.h, wave.h,
// voronoi.h; Apache-2.0 / BSD-3-Clause, see that header).
//
// One out-of-line definition with external linkage (-rdc), called from
// gpu_progInputEval in the <HasProgram=true> shade kernels only. Compiling it
// once here rather than in each of the 12 shade part TUs keeps the build time
// flat, and as a separate callee its registers never enter the fleet, intersect
// or shadow kernels.
#include "astroray/procedural_tex.h"
#include "astroray/shader_vm.h"

namespace astroray::wavefront {

extern __constant__ GWavefrontProgramBinding c_wfProgBinding;  // stage_advance.cu

// CoordProgramTexture::value (include/advanced_features.h): every VM input reads
// the point p, input 1 is the warp texture sampled at p, and the child is
// evaluated at the warped point svm_eval(program, inputs).
__device__ __noinline__ GVec3 gpu_procTexEval(int procId, GVec3 p)
{
    const astroray::proc::GProcTexture& t = c_wfProgBinding.procs[procId];
    if (t.warpProg >= 0) {
        GVec3 in[astroray::svm::VM_MAX_TEX];
        for (int i = 0; i < astroray::svm::VM_MAX_TEX; ++i) in[i] = p;
        if (t.warpInputput >= 0)
            in[1] = astroray::proc::proc_texture_eval(c_wfProgBinding.procs[t.warpInput], p);
        p = astroray::svm::svm_eval(c_wfProgBinding.programs[t.warpProg], in);
    }
    return astroray::proc::proc_texture_eval(t, p);
}

}  // namespace astroray::wavefront

// stage_shade_add.cu - #1072 Add Shader shade variants:
// stageShadeBucketedKernel<HasPrincipled=true, HasTexture=T, HasPhotons=false,
// HasDispersion=false, HasLightPassAOVs=false, HasProgram=PR, HasNormalPerturb=NP,
// HasAdd=true> (8 instantiations). Only an Add-partner scene launches them, so no other
// shade kernel carries the partner call frames. See stage_advance_device.cuh.
#include "stage_advance_device.cuh"

namespace astroray::wavefront {

#define ASTRORAY_ADD_SEL(FN, ...) \
    (T ? (PR ? (NP ? FN<true, true,  true >(__VA_ARGS__) : FN<true, true,  false>(__VA_ARGS__)) \
             : (NP ? FN<true, false, true >(__VA_ARGS__) : FN<true, false, false>(__VA_ARGS__))) \
       : (PR ? (NP ? FN<false, true,  true >(__VA_ARGS__) : FN<false, true,  false>(__VA_ARGS__)) \
             : (NP ? FN<false, false, true >(__VA_ARGS__) : FN<false, false, false>(__VA_ARGS__))))

template<bool T, bool PR, bool NP>
static const void* addKptr() { return shadeKptr<true, T, false, false, false, PR, NP, true>(); }

template<bool T, bool PR, bool NP>
static void addLaunch(int blocks, int threads, const StageShadeArgs& a) {
    shadeLaunch<true, T, false, false, false, PR, NP, true>(blocks, threads, a);
}

const void* stageShadeAddKernelPtr(bool T, bool PR, bool NP)
{
    return ASTRORAY_ADD_SEL(addKptr);
}

void stageShadeAddLaunch(bool T, bool PR, bool NP, int blocks, int threads,
                         const StageShadeArgs& a)
{
    if (T) {
        if (PR) { if (NP) addLaunch<true, true, true>(blocks, threads, a);
                  else    addLaunch<true, true, false>(blocks, threads, a); }
        else    { if (NP) addLaunch<true, false, true>(blocks, threads, a);
                  else    addLaunch<true, false, false>(blocks, threads, a); }
    } else {
        if (PR) { if (NP) addLaunch<false, true, true>(blocks, threads, a);
                  else    addLaunch<false, true, false>(blocks, threads, a); }
        else    { if (NP) addLaunch<false, false, true>(blocks, threads, a);
                  else    addLaunch<false, false, false>(blocks, threads, a); }
    }
}

#undef ASTRORAY_ADD_SEL
}  // namespace astroray::wavefront

#include "raytracer.h"
#include "astroray/light_sampler.h"

// pkg86: LightList::setSampler implementation.

void LightList::setSampler(SamplerMode mode) {
    switch (mode) {
        case SamplerMode::Power:
            sampler_ = std::make_unique<astroray::PowerLightSampler>(this);
            break;
        case SamplerMode::Tree:
            sampler_ = std::make_unique<astroray::TreeLightSampler>(this);
            break;
    }
}

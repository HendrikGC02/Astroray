#include "raytracer.h"
#include "astroray/light_sampler.h"

// pkg86: LightList ctor/dtor + setSampler. The ctor eagerly creates a
// PowerLightSampler so OpenMP-parallel render workers never race on a lazy
// first-use init. Defined out-of-line because the header forward-declares
// `astroray::LightSampler`; the ctor body needs the complete type.

LightList::LightList()
    : sampler_(std::make_unique<astroray::PowerLightSampler>(this)) {}

LightList::~LightList() = default;

LightList::LightList(LightList&& other) noexcept
    : lights(std::move(other.lights))
    , dedicatedLights(std::move(other.dedicatedLights))
    , powerDist(std::move(other.powerDist))
    , dedicatedPowers(std::move(other.dedicatedPowers))
    , totalPower(other.totalPower)
    , sampler_(std::move(other.sampler_))
{
    // Rebind the sampler's lightList_ pointer from `&other` to `this`, since
    // PowerLightSampler / TreeLightSampler hold a raw const LightList*.
    if (sampler_) sampler_ = std::make_unique<astroray::PowerLightSampler>(this);
    other.totalPower = 0;
}

LightList& LightList::operator=(LightList&& other) noexcept {
    if (this == &other) return *this;
    lights = std::move(other.lights);
    dedicatedLights = std::move(other.dedicatedLights);
    powerDist = std::move(other.powerDist);
    dedicatedPowers = std::move(other.dedicatedPowers);
    totalPower = other.totalPower;
    other.totalPower = 0;
    // Rebuild sampler bound to `this` (see ctor rationale).
    sampler_ = std::make_unique<astroray::PowerLightSampler>(this);
    samplerMode_ = SamplerMode::Power;  // pkg86-B: keep mode in sync with the rebuilt sampler
    return *this;
}

void LightList::setSampler(SamplerMode mode) {
    switch (mode) {
        case SamplerMode::Power:
            sampler_ = std::make_unique<astroray::PowerLightSampler>(this);
            break;
        case SamplerMode::Tree:
            sampler_ = std::make_unique<astroray::TreeLightSampler>(this);
            break;
    }
    samplerMode_ = mode;  // pkg86-B: queried by the GPU scene upload
}

// pkg86-B: defined out-of-line because raytracer.h forward-declares
// astroray::LightSampler. Returns nullptr for the Power sampler.
const astroray::LightTree* LightList::lightTree() const {
    return sampler_ ? sampler_->tree() : nullptr;
}

// #925: see LightList::resample (raytracer.h).
bool LightList::resample(LightSample& out, const LightSample& picked, const Vec3& pt,
                         const Vec3& normal, const astroray::SampledWavelengths& lambdas,
                         std::mt19937& gen) const {
    return sampler_ && sampler_->resample(out, picked, pt, normal, lambdas, gen);
}

// #961: see LightSampler::pickSegment / pdfValueSegment.
bool LightList::pickSegment(LightSample& picked, const Vec3& o, const Vec3& d, float t,
                            std::mt19937& gen) const {
    return sampler_ && sampler_->pickSegment(picked, o, d, t, gen);
}

float LightList::pdfValueSegment(const Vec3& o, const Vec3& d, float t, const Vec3& pt,
                                 const Vec3& dir, const Hittable* hitEmitter,
                                 const astroray::Light* hitLamp) const {
    return sampler_ ? sampler_->pdfValueSegment(o, d, t, pt, dir, hitEmitter, hitLamp) : 0.0f;
}

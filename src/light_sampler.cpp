#include "raytracer.h"
#include "astroray/light_sampler.h"
#include "astroray/light_tree.h"
#include "astroray/light.h"
#include <algorithm>

namespace astroray {

// ============================================================================
// PowerLightSampler — power-weighted CDF (current LightList behavior)
// ============================================================================

void PowerLightSampler::sample(LightSample& out, const Vec3& point, const Vec3& normal,
                               const SampledWavelengths& lambdas,
                               std::mt19937& gen) const {
    // Delegate to LightList's original implementation.
    // This is a bit circular, but we need to extract the logic here.
    // For now, we'll inline the original LightList::sample logic.

    // Initialize to zero in case no valid sample is found.
    out.position = Vec3(0);
    out.normal = Vec3(0);
    out.emission = Vec3(0);
    out.emission_spec = SampledSpectrum(0.0f);
    out.pdf = 0;
    out.distance = 0;
    out.isDelta = false;  // pkg140

    const auto& lights = lightList_->getLights();
    const auto& dedicatedLights = lightList_->getDedicatedLights();
    const auto& powerDist = lightList_->getPowerDist();
    float totalPower = lightList_->getTotalPower();

    size_t numHittableLights = lights.size();
    size_t numDedicatedLights = dedicatedLights.size();
    size_t totalLights = numHittableLights + numDedicatedLights;

    if (totalLights == 0) {
        return;
    }

    // Sample light index from unified power CDF.
    std::uniform_real_distribution<float> dist(0, 1);
    size_t idx = 0;
    float selPdf;
    if (totalPower > 0.0f) {
        float u = dist(gen) * totalPower;
        for (size_t i = 0; i < powerDist.size(); ++i) {
            if (u < powerDist[i]) {
                idx = i;
                break;
            }
        }
        selPdf = (idx > 0 ? powerDist[idx] - powerDist[idx - 1] : powerDist[0]) / totalPower;
    } else {
        // pkg195: degenerate power CDF (totalPower == 0). This happens when every
        // light's single-stratification power() luminance estimate misses a narrow
        // emission line -- e.g. a sodium-vapor lamp whose SPD is a ~589 nm spike, so
        // the u=0.5 hero wavelengths {380,480,580,680} all read ~0. Without a guard,
        // selPdf = 0/0 = NaN propagates into out.pdf and the integrator's `pdf > 0`
        // NEE test silently drops the lamp (renders black). Fall back to uniform
        // light selection (PBRT UniformLightSampler, Apache-2.0) so the lamp is still
        // sampled; MIS remains valid because pdfValue() mirrors this same fallback.
        idx = static_cast<size_t>(dist(gen) * static_cast<float>(totalLights));
        if (idx >= totalLights) idx = totalLights - 1;
        selPdf = 1.0f / static_cast<float>(totalLights);
    }

    // Dispatch: first numHittableLights indices are legacy Hittables, rest are dedicated.
    if (idx < numHittableLights) {
        // Legacy Hittable path (emissive geometry).
        Vec3 dir = lights[idx]->random(point, gen);
        HitRecord rec;
        if (lights[idx]->hit(Ray(point, dir), 0.001f, std::numeric_limits<float>::max(), rec)) {
            out.position = rec.point;
            out.normal = rec.normal;
            Vec3 toPoint = (point - rec.point).normalized();
            Vec3 lightNormal = rec.frontFace ? rec.normal : -rec.normal;
            // #776: evaluate the emission at the SAMPLED light point so NEE and
            // BSDF-sampled hits integrate the SAME emitter (previously NEE saw a
            // flat getEmission()). `flat` keeps the mesh-light spread cone
            // (emittedRadiance(lightNormal,toPoint) is base-or-0) and the
            // spot/IES directionFalloff; when it is non-zero (inside cone) we
            // use the material's per-hit emittedSpectral — the same function the
            // BSDF-sampled emission add uses — so MIS combines matching
            // integrands. Illuminant upsampling is scale-linear, so untextured
            // lights stay byte-identical (falloff outside == inside).
            float falloff = lights[idx]->directionFalloff(toPoint);
            Vec3 flat = lights[idx]->emittedRadiance(lightNormal, toPoint) * falloff;
            // RGB out.emission carries the texture MEAN (getEmission()==mean×intensity,
            // #776); out.emission_spec below is the per-hit textured value and is the
            // production path — the spectral tracer consumes emission_spec.
            out.emission = flat;
            out.distance = rec.t;
            out.pdf = lights[idx]->pdfValue(point, dir) * selPdf;
            out.emission_spec = (rec.material && flat != Vec3(0))
                ? rec.material->emittedSpectral(rec, lambdas) * falloff
                : RGBIlluminantSpectrum({flat.x, flat.y, flat.z}).sample(lambdas);
        }
    } else {
        // Dedicated Light path (pkg89 Phase A).
        size_t dedicatedIdx = idx - numHittableLights;
        const Light* light = dedicatedLights[dedicatedIdx].get();
        Light::LiSample liSample;
        std::memset(&liSample, 0, sizeof(liSample));  // Zero-fill defensively
        light->sampleLi(liSample, point, normal, lambdas, gen);

        out.position = liSample.position;
        out.normal = liSample.normal;
        out.emission = liSample.emission_rgb;
        out.emission_spec = liSample.emission_spec;
        out.distance = liSample.distance;
        out.pdf = liSample.pdf * selPdf;
        out.isDelta = liSample.isDelta;  // pkg140
    }
}

// #912: index of the hit emitter in the hittable light list, or -1. The hit
// emitter's pdf alone is the reverse NEE pdf: summing every light the
// direction line crosses also counted emitters occluded by the hit one (a
// light behind a light), inflating lp and darkening w_B. Cycles:
// light_sample_mis_weight_forward_surface (kernel/light/sample.h, Apache-2.0);
// GPU twin gpu_reconstruct_light_pdf (src/gpu/gpu_nee.cuh).
static int hitEmitterIndex(const std::vector<std::shared_ptr<Hittable>>& lights,
                           const Hittable* hitEmitter) {
    if (!hitEmitter) return -1;
    for (size_t i = 0; i < lights.size(); ++i)
        if (lights[i].get() == hitEmitter) return static_cast<int>(i);
    return -1;
}

// #912: same for a hit dedicated lamp (Cycles light_sample_mis_weight_forward_lamp).
static int hitLampIndex(const std::vector<std::unique_ptr<Light>>& lamps, const Light* hitLamp) {
    if (!hitLamp) return -1;
    for (size_t i = 0; i < lamps.size(); ++i)
        if (lamps[i].get() == hitLamp) return static_cast<int>(i);
    return -1;
}

float PowerLightSampler::pdfValue(const Vec3& point, const Vec3& dir,
                                   const Vec3& /*normal*/,
                                   const Hittable* hitEmitter,
                                   const Light* hitLamp) const {
    const auto& lights = lightList_->getLights();
    const auto& dedicatedLights = lightList_->getDedicatedLights();
    const auto& powerDist = lightList_->getPowerDist();
    float totalPower = lightList_->getTotalPower();

    if (lights.empty() && dedicatedLights.empty()) return 0;

    // pkg195: mirror sample()'s uniform fallback for a degenerate power CDF
    // (totalPower == 0, e.g. a narrow-line lamp). Uniform selPdf = 1/N.
    const size_t totalLights = lights.size() + dedicatedLights.size();
    const bool uniformFallback = (totalPower <= 0.0f);

    const int hit = hitEmitterIndex(lights, hitEmitter);
    if (hit >= 0) {
        float selPdf = uniformFallback
            ? 1.0f / static_cast<float>(totalLights)
            : (hit > 0 ? powerDist[hit] - powerDist[hit - 1] : powerDist[0]) / totalPower;
        return selPdf * lights[hit]->pdfValue(point, dir);
    }
    const int lamp = hitLampIndex(dedicatedLights, hitLamp);
    if (lamp >= 0) {
        const size_t k = lights.size() + static_cast<size_t>(lamp);
        float selPdf = uniformFallback
            ? 1.0f / static_cast<float>(totalLights)
            : (k > 0 ? powerDist[k] - powerDist[k - 1] : powerDist[0]) / totalPower;
        return selPdf * dedicatedLights[lamp]->pdfLi(point, dir);
    }
    // A known hit light that NEE cannot sample has pdf 0 (w_B = 1), as on GPU.
    if (hitEmitter || hitLamp) return 0;

    float pdf = 0;
    size_t idx = 0;

    // Legacy Hittables.
    for (size_t i = 0; i < lights.size(); ++i, ++idx) {
        float selPdf = uniformFallback
            ? 1.0f / static_cast<float>(totalLights)
            : (idx > 0 ? powerDist[idx] - powerDist[idx - 1] : powerDist[0]) / totalPower;
        pdf += selPdf * lights[i]->pdfValue(point, dir);
    }

    // Dedicated Lights.
    for (size_t i = 0; i < dedicatedLights.size(); ++i, ++idx) {
        float selPdf = uniformFallback
            ? 1.0f / static_cast<float>(totalLights)
            : (idx > 0 ? powerDist[idx] - powerDist[idx - 1] : powerDist[0]) / totalPower;
        pdf += selPdf * dedicatedLights[i]->pdfLi(point, dir);
    }

    return pdf;
}

bool PowerLightSampler::empty() const {
    return lightList_->empty();
}

// ============================================================================
// TreeLightSampler — light tree (Conty 2018 + Cycles)
// ============================================================================

TreeLightSampler::TreeLightSampler(const LightList* lightList)
    : lightList_(lightList), tree_(std::make_unique<LightTree>()) {
    tree_->build(*lightList);
}

TreeLightSampler::~TreeLightSampler() = default;

void TreeLightSampler::sample(LightSample& out, const Vec3& point, const Vec3& normal,
                              const SampledWavelengths& lambdas,
                              std::mt19937& gen) const {
    // Initialize to zero in case no valid sample is found.
    out.position = Vec3(0);
    out.normal = Vec3(0);
    out.emission = Vec3(0);
    out.emission_spec = SampledSpectrum(0.0f);
    out.pdf = 0;
    out.distance = 0;
    out.isDelta = false;  // pkg140

    if (tree_->empty()) {
        return;
    }

    // Pick a light from the tree.
    std::uniform_real_distribution<float> dist(0, 1);
    float u = dist(gen);
    LightTree::PickResult pick = tree_->pick(point, normal, u, gen);

    if (pick.lightIndex < 0) {
        return;
    }

    // Sample the chosen light.
    float treePdf = pick.pdf;

    if (!pick.isDedicated) {
        // Legacy Hittable path.
        const auto& lights = lightList_->getLights();
        Vec3 dir = lights[pick.lightIndex]->random(point, gen);
        HitRecord rec;
        if (lights[pick.lightIndex]->hit(Ray(point, dir), 0.001f, std::numeric_limits<float>::max(), rec)) {
            out.position = rec.point;
            out.normal = rec.normal;
            Vec3 toPoint = (point - rec.point).normalized();
            Vec3 lightNormal = rec.frontFace ? rec.normal : -rec.normal;
            // #776: texture-aware NEE emission at the sampled light point (see
            // the matching comment in the uniform-sampler path above).
            float falloff = lights[pick.lightIndex]->directionFalloff(toPoint);
            Vec3 flat = lights[pick.lightIndex]->emittedRadiance(lightNormal, toPoint) * falloff;
            // RGB out.emission carries the texture MEAN (getEmission()==mean×intensity,
            // #776); out.emission_spec below is the per-hit textured value and is the
            // production path — the spectral tracer consumes emission_spec.
            out.emission = flat;
            out.distance = rec.t;
            out.pdf = lights[pick.lightIndex]->pdfValue(point, dir) * treePdf;
            out.emission_spec = (rec.material && flat != Vec3(0))
                ? rec.material->emittedSpectral(rec, lambdas) * falloff
                : RGBIlluminantSpectrum({flat.x, flat.y, flat.z}).sample(lambdas);
        }
    } else {
        // Dedicated Light path.
        const auto& dedicatedLights = lightList_->getDedicatedLights();
        const Light* light = dedicatedLights[pick.lightIndex].get();
        Light::LiSample liSample;
        std::memset(&liSample, 0, sizeof(liSample));  // Zero-fill defensively
        light->sampleLi(liSample, point, normal, lambdas, gen);

        out.position = liSample.position;
        out.normal = liSample.normal;
        out.emission = liSample.emission_rgb;
        out.emission_spec = liSample.emission_spec;
        out.distance = liSample.distance;
        out.pdf = liSample.pdf * treePdf;
        out.isDelta = liSample.isDelta;  // pkg140
    }
}

float TreeLightSampler::pdfValue(const Vec3& point, const Vec3& dir,
                                  const Vec3& normal,
                                  const Hittable* hitEmitter,
                                  const Light* hitLamp) const {
    // For MIS, we compute the pdf of sampling direction `dir` from `point`.
    // This requires summing over all lights that could be sampled in that direction:
    //   pdf = sum_i [ tree_pdf(i) * light_i.pdfValue(point, dir) ]
    // This mirrors PowerLightSampler::pdfValue but uses tree selection probabilities.

    if (tree_->empty()) return 0.0f;

    const auto& lights = lightList_->getLights();
    const auto& dedicatedLights = lightList_->getDedicatedLights();

    // #851: re-walk the tree with the SAME shading normal sample() used at this
    // point, so the MIS pdf equals the pick pdf (Cycles light_tree_pdf takes the
    // stored mis_origin_n, kernel/light/tree.h). The old -dir proxy pruned the
    // emitter's own cluster as "behind the surface", so pdf≈0 and w_B≈1.

    const int hit = hitEmitterIndex(lights, hitEmitter);  // #912
    if (hit >= 0) {
        float lightPdf = lights[hit]->pdfValue(point, dir);
        return (lightPdf > 0.0f) ? tree_->pdf(point, normal, hit, false) * lightPdf : 0.0f;
    }
    const int lamp = hitLampIndex(dedicatedLights, hitLamp);
    if (lamp >= 0) {
        float lightPdf = dedicatedLights[lamp]->pdfLi(point, dir);
        return (lightPdf > 0.0f) ? tree_->pdf(point, normal, lamp, true) * lightPdf : 0.0f;
    }
    if (hitEmitter || hitLamp) return 0.0f;  // unsampleable hit light: w_B = 1, as on GPU

    float pdf = 0.0f;

    // Legacy Hittables. The tree walk is costly; only do it for lights the
    // direction can reach (same sum, skipping zero terms).
    for (size_t i = 0; i < lights.size(); ++i) {
        float lightPdf = lights[i]->pdfValue(point, dir);
        if (lightPdf > 0.0f) {
            float treePdf = tree_->pdf(point, normal, static_cast<int>(i), false);
            if (treePdf > 0.0f) pdf += treePdf * lightPdf;
        }
    }

    // Dedicated Lights.
    for (size_t i = 0; i < dedicatedLights.size(); ++i) {
        float lightPdf = dedicatedLights[i]->pdfLi(point, dir);
        if (lightPdf > 0.0f) {
            float treePdf = tree_->pdf(point, normal, static_cast<int>(i), true);
            if (treePdf > 0.0f) pdf += treePdf * lightPdf;
        }
    }

    return pdf;
}

bool TreeLightSampler::empty() const {
    return tree_->empty();
}

} // namespace astroray

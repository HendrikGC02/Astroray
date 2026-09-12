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

float PowerLightSampler::pdfValue(const Vec3& point, const Vec3& dir) const {
    const auto& lights = lightList_->getLights();
    const auto& dedicatedLights = lightList_->getDedicatedLights();
    const auto& powerDist = lightList_->getPowerDist();
    float totalPower = lightList_->getTotalPower();

    if (lights.empty() && dedicatedLights.empty()) return 0;

    // pkg195: mirror sample()'s uniform fallback for a degenerate power CDF
    // (totalPower == 0, e.g. a narrow-line lamp). Uniform selPdf = 1/N.
    const size_t totalLights = lights.size() + dedicatedLights.size();
    const bool uniformFallback = (totalPower <= 0.0f);

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

float TreeLightSampler::pdfValue(const Vec3& point, const Vec3& dir) const {
    // For MIS, we compute the pdf of sampling direction `dir` from `point`.
    // This requires summing over all lights that could be sampled in that direction:
    //   pdf = sum_i [ tree_pdf(i) * light_i.pdfValue(point, dir) ]
    // This mirrors PowerLightSampler::pdfValue but uses tree selection probabilities.

    if (tree_->empty()) return 0.0f;

    const auto& lights = lightList_->getLights();
    const auto& dedicatedLights = lightList_->getDedicatedLights();

    // We need a normal for tree traversal. Since we don't have the actual surface normal here,
    // use the direction as a proxy (assume normal ≈ -dir for backfacing logic).
    // This is a heuristic; proper MIS would cache the shading normal from the hit point.
    Vec3 normal = -dir.normalized();

    float pdf = 0.0f;

    // Legacy Hittables.
    for (size_t i = 0; i < lights.size(); ++i) {
        float treePdf = tree_->pdf(point, normal, static_cast<int>(i), false);
        if (treePdf > 0.0f) {
            pdf += treePdf * lights[i]->pdfValue(point, dir);
        }
    }

    // Dedicated Lights.
    for (size_t i = 0; i < dedicatedLights.size(); ++i) {
        float treePdf = tree_->pdf(point, normal, static_cast<int>(i), true);
        if (treePdf > 0.0f) {
            pdf += treePdf * dedicatedLights[i]->pdfLi(point, dir);
        }
    }

    return pdf;
}

bool TreeLightSampler::empty() const {
    return tree_->empty();
}

} // namespace astroray

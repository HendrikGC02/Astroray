#include "astroray/register.h"
#include "advanced_features.h"

class NormalMappedPlugin : public Material {
    std::shared_ptr<Material> baseMaterial_;
    std::shared_ptr<Texture> normalTexture_;
    std::shared_ptr<Texture> bumpTexture_;
    float normalStrength_;
    float bumpStrength_;
    float bumpDistance_;

    static float heightValue(const Vec3& c) {
        return 0.2126f * c.x + 0.7152f * c.y + 0.0722f * c.z;
    }

    HitRecord perturbNormal(const HitRecord& rec) const {
        HitRecord out = rec;
        Vec3 n = rec.normal;

        if (normalTexture_) {
            Vec3 rgb = normalTexture_->value(rec, Vec3(0));
            Vec3 nTS = (rgb * 2.0f) - Vec3(1.0f);
            // pkg223 — tangent-space normal mapping REQUIRES the UV-aligned
            // (Mikk-TSpace / Lengyel) frame, NOT the arbitrary
            // buildOrthonormalBasis `tangent`/`bitangent`: the map's X/Y axes
            // must track the texture's UV parameterization, else the relief tilts
            // to an arbitrary compass direction (highlight moves the wrong way vs
            // Cycles). rec.uvTangent is the Gram-Schmidt-orthonormalized UV
            // tangent (Triangle::hit via manifold::uvAlignedTangent); the
            // bitangent handedness rides rec.uvBitangentSign as
            // B = sign * cross(N, T). The GPU shade path (HasNormalPerturb)
            // recomputes the identical frame (gpu_pr_uvAlignedTangent) for parity.
            Vec3 T = rec.uvTangent;
            Vec3 B = rec.normal.cross(T) * rec.uvBitangentSign;
            Vec3 mapped = (T * nTS.x + B * nTS.y + rec.normal * nTS.z).normalized();
            float t = std::clamp(normalStrength_, 0.0f, 1.0f);
            n = (rec.normal * (1.0f - t) + mapped * t).normalized();
        }

        if (bumpTexture_) {
            float eps = std::max(1e-4f, bumpDistance_);
            float h0 = heightValue(bumpTexture_->value(rec, Vec3(0)));
            float hU = heightValue(bumpTexture_->valueOffset(rec, Vec3(0), eps, 0.0f));
            float hV = heightValue(bumpTexture_->valueOffset(rec, Vec3(0), 0.0f, eps));
            float dU = (hU - h0) / eps;
            float dV = (hV - h0) / eps;
            Vec3 dp = rec.tangent * dU + rec.bitangent * dV;
            n = (n - dp * bumpStrength_).normalized();
        }

        out.normal = n;
        buildOrthonormalBasis(out.normal, out.tangent, out.bitangent);
        return out;
    }

public:
    NormalMappedPlugin(std::shared_ptr<Material> base,
                       std::shared_ptr<Texture> normalTex,
                       std::shared_ptr<Texture> bumpTex,
                       float normalStr, float bumpStr, float bumpDist)
        : baseMaterial_(std::move(base)),
          normalTexture_(std::move(normalTex)),
          bumpTexture_(std::move(bumpTex)),
          normalStrength_(normalStr),
          bumpStrength_(bumpStr),
          bumpDistance_(bumpDist) {}

    explicit NormalMappedPlugin(const astroray::ParamDict& p)
        : baseMaterial_(astroray::MaterialRegistry::instance().create(
              p.getString("inner_type", "lambertian"), p)),
          normalTexture_(nullptr),
          bumpTexture_(nullptr),
          normalStrength_(p.getFloat("normal_strength", 1.0f)),
          bumpStrength_(p.getFloat("bump_strength", 1.0f)),
          bumpDistance_(p.getFloat("bump_distance", 0.01f)) {}

    astroray::SampledSpectrum evalSpectral(
            const HitRecord& rec, const Vec3& wo, const Vec3& wi,
            const astroray::SampledWavelengths& lambdas) const override {
        return baseMaterial_->evalSpectral(perturbNormal(rec), wo, wi, lambdas);
    }

    BSDFSample sample(const HitRecord& rec, const Vec3& wo, std::mt19937& gen) const override {
        return baseMaterial_->sample(perturbNormal(rec), wo, gen);
    }

    float pdf(const HitRecord& rec, const Vec3& wo, const Vec3& wi) const override {
        return baseMaterial_->pdf(perturbNormal(rec), wo, wi);
    }

    // pkg223 — GPU-upload unwrap. scene_upload converts the INNER material to the
    // GMaterial (BSDF + base-colour texture) and rides the tangent-space normal
    // texture + Strength on the parallel c_wfTexBinding side arrays. Only the
    // normal texture is exposed (bump is CPU-only / deferred, memory pkg223).
    std::shared_ptr<Material> normalMapInner() const override { return baseMaterial_; }
    std::shared_ptr<Texture>  normalMapTexture() const override { return normalTexture_; }
    float                     normalMapStrength() const override { return normalStrength_; }
};

ASTRORAY_REGISTER_MATERIAL("normal_mapped", NormalMappedPlugin)

namespace astroray {
std::shared_ptr<Material> makeNormalMapped(
        std::shared_ptr<Material> base,
        std::shared_ptr<Texture> normalTex,
        std::shared_ptr<Texture> bumpTex,
        float normalStr, float bumpStr, float bumpDist) {
    return std::make_shared<NormalMappedPlugin>(
        std::move(base), std::move(normalTex), std::move(bumpTex),
        normalStr, bumpStr, bumpDist);
}
} // namespace astroray

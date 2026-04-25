#include "astroray/register.h"
#include "advanced_features.h"

class DisneyPlugin : public Material {
    Vec3 baseColor_;
    float metallic_, roughness_, anisotropic_, anisotropicRotation_;
    float subsurface_, specular_, specularTint_;
    float clearcoat_, clearcoatGloss_;
    float sheen_, sheenTint_;
    float transmission_, ior_;

    float D_GTR2(float NdotH, float a) const {
        float a2 = a * a;
        float t = 1 + (a2 - 1) * NdotH * NdotH;
        return a2 / (float(M_PI) * t * t + 0.001f);
    }

    float smithG_GGX(float NdotV, float alphaG) const {
        float a = alphaG * alphaG;
        float b = NdotV * NdotV;
        return 1 / (NdotV + std::sqrt(a + b - a * b) + 0.001f);
    }

    Vec3 fresnelSchlick(float cosTheta, const Vec3& F0) const {
        float c = std::clamp(1 - cosTheta, 0.0f, 1.0f);
        return F0 + (Vec3(1) - F0) * std::pow(c, 5) * 0.8f;
    }

public:
    explicit DisneyPlugin(const astroray::ParamDict& p)
        : baseColor_(p.getVec3("albedo", Vec3(0.8f))),
          metallic_(p.getFloat("metallic", 0.0f)),
          roughness_(std::max(0.001f, p.getFloat("roughness", 0.5f))),
          anisotropic_(p.getFloat("anisotropic", 0.0f)),
          anisotropicRotation_(p.getFloat("anisotropic_rotation", 0.0f)),
          subsurface_(p.getFloat("subsurface", 0.0f)),
          specular_(p.getFloat("specular", 0.5f)),
          specularTint_(p.getFloat("specular_tint", 0.0f)),
          clearcoat_(p.getFloat("clearcoat", 0.0f)),
          clearcoatGloss_(p.getFloat("clearcoat_gloss", 1.0f)),
          sheen_(p.getFloat("sheen", 0.0f)),
          sheenTint_(p.getFloat("sheen_tint", 0.5f)),
          transmission_(p.getFloat("transmission", 0.0f)),
          ior_(p.getFloat("ior", 1.5f)) {}

    Vec3 eval(const HitRecord& rec, const Vec3& wo, const Vec3& wi) const override {
        Vec3 N = rec.normal;
        float NdotL = N.dot(wi);
        float NdotV = N.dot(wo);
        if (NdotL <= 0 || NdotV <= 0) return Vec3(0);

        Vec3 H = (wi + wo).normalized();
        float NdotH = N.dot(H);
        float LdotH = wi.dot(H);

        Vec3 Cdlin = baseColor_;
        float Cdlum = luminance(Cdlin);
        Vec3 Ctint = Cdlum > 0 ? Cdlin / Cdlum : Vec3(1);
        Vec3 Cspec0 = Vec3(specular_ * 0.08f) * (Vec3(1) * (1 - specularTint_) + Ctint * specularTint_);
        Vec3 F0 = Cspec0 * (1 - metallic_) + Cdlin * metallic_;
        F0 = Vec3::min(F0, Vec3(1));

        float FL = std::pow(1 - NdotL, 5);
        float FV = std::pow(1 - NdotV, 5);
        float Fd90 = 0.5f + 2 * LdotH * LdotH * roughness_;
        float Fd = (1 + (Fd90 - 1) * FL) * (1 + (Fd90 - 1) * FV);
        Vec3 diffuse = (1 / float(M_PI)) * Cdlin * Fd;

        float a = std::max(roughness_ * roughness_, 0.0064f);
        float Ds = D_GTR2(NdotH, a);
        Vec3 F = fresnelSchlick(LdotH, F0);
        float Gs = smithG_GGX(NdotL, a) * smithG_GGX(NdotV, a);
        Vec3 spec = Ds * F * Gs / (4 * NdotL * NdotV + 0.001f);

        Vec3 Csheen = Vec3(1) * (1 - sheenTint_) + Ctint * sheenTint_;
        Vec3 Fsheen = sheen_ * Csheen * std::pow(1 - LdotH, 5) * 0.5f;

        float Dr = D_GTR2(NdotH, clearcoatGloss_ * clearcoatGloss_);
        float Fr = 0.04f + (1 - 0.04f) * std::pow(1 - LdotH, 5);
        float Gr = smithG_GGX(NdotL, 0.25f) * smithG_GGX(NdotV, 0.25f);
        Vec3 clearcoatTerm = Vec3(clearcoat_ * Dr * Fr * Gr / (4 * NdotL * NdotV + 0.001f)) * 0.5f;

        Vec3 result = ((1 - metallic_) * (1 - transmission_) * diffuse + spec +
                      (1 - metallic_) * Fsheen + clearcoatTerm) * NdotL;
        float Fms = ggxMultiScatterCompensation(NdotV, NdotL, roughness_);
        float msWeight = roughness_ * (2.0f - roughness_);
        result += F0 * (Fms * msWeight * 1.3f);

        result.x = std::min(result.x, 10.0f);
        result.y = std::min(result.y, 10.0f);
        result.z = std::min(result.z, 10.0f);
        return result;
    }

    astroray::SampledSpectrum evalSpectral(
            const HitRecord& rec, const Vec3& wo, const Vec3& wi,
            const astroray::SampledWavelengths& lambdas) const override {
        // Keep Disney on final-RGB spectral upsampling to stay within the perf budget.
        Vec3 rgb = eval(rec, wo, wi);
        return astroray::RGBAlbedoSpectrum({rgb.x, rgb.y, rgb.z}).sample(lambdas);
    }

    BSDFSample sample(const HitRecord& rec, const Vec3& wo, std::mt19937& gen) const override {
        BSDFSample s;
        s.wi = rec.normal;
        s.f = Vec3(0);
        s.pdf = 0.0f;
        s.isDelta = false;
        std::uniform_real_distribution<float> dist(0, 1);

        if (transmission_ > 0 && dist(gen) < transmission_) {
            float etaI = rec.frontFace ? 1.0f : ior_;
            float etaT = rec.frontFace ? ior_ : 1.0f;
            float eta = etaI / etaT;
            Vec3 n = rec.normal;
            float cosTheta = wo.dot(n);
            if (cosTheta < 0) { cosTheta = -cosTheta; n = -n; }

            float sinTheta = std::sqrt(std::max(0.0f, 1 - cosTheta * cosTheta));
            bool cannotRefract = eta * sinTheta > 1;

            float f0 = ((etaI - etaT) / (etaI + etaT));
            f0 = f0 * f0;
            float fresnel = f0 + (1 - f0) * std::pow(1 - cosTheta, 5);

            if (cannotRefract || dist(gen) < fresnel) {
                s.wi = n * (2 * wo.dot(n)) - wo;
                s.f = Vec3(1);
                s.pdf = fresnel * transmission_;
            } else {
                Vec3 perp = (wo - n * cosTheta) * (-eta);
                Vec3 para = n * (-std::sqrt(std::abs(1 - perp.length2())));
                s.wi = (perp + para).normalized();
                s.f = baseColor_ * (eta * eta);
                s.pdf = (1 - fresnel) * transmission_;
            }
            s.isDelta = roughness_ < 0.1f;
            if (s.isDelta) const_cast<HitRecord&>(rec).isDelta = true;
            return s;
        }

        float diffWeight = (1 - metallic_) * (1 - transmission_);
        float specWeight = 1;
        float total = diffWeight + specWeight;

        if (dist(gen) * total < diffWeight) {
            Vec3 localWi = Vec3::randomCosineDirection(gen);
            s.wi = rec.tangent * localWi.x + rec.bitangent * localWi.y + rec.normal * localWi.z;
            s.f = eval(rec, wo, s.wi);
            s.pdf = rec.normal.dot(s.wi) / float(M_PI) * (diffWeight / total);
        } else {
            float a = std::max(roughness_ * roughness_, 0.0064f);
            float r1 = dist(gen), r2 = dist(gen);
            float phi = 2 * float(M_PI) * r1;
            float cosTheta = std::sqrt((1 - r2) / (1 + (a * a - 1) * r2));
            float sinTheta = std::sqrt(1 - cosTheta * cosTheta);
            Vec3 h(std::cos(phi) * sinTheta, std::sin(phi) * sinTheta, cosTheta);
            h = rec.tangent * h.x + rec.bitangent * h.y + rec.normal * h.z;
            s.wi = (h * (2 * wo.dot(h)) - wo).normalized();
            if (rec.normal.dot(s.wi) > 0) {
                s.f = eval(rec, wo, s.wi);
                float NdotH = rec.normal.dot(h);
                float HdotV = h.dot(wo);
                float D = D_GTR2(NdotH, a);
                if (HdotV > 0.0f) {
                    s.pdf = D * NdotH / (4 * HdotV + 0.001f) * (specWeight / total);
                }
            }
        }
        return s;
    }

    float pdf(const HitRecord& rec, const Vec3& wo, const Vec3& wi) const override {
        Vec3 H = (wo + wi).normalized();
        float diffWeight = (1 - metallic_) * (1 - transmission_);
        float specWeight = 1;
        float total = diffWeight + specWeight;
        float p = 0;
        if (diffWeight > 0) p += (rec.normal.dot(wi) / float(M_PI)) * (diffWeight / total);
        if (specWeight > 0) {
            float a = roughness_ * roughness_;
            float NdotH = rec.normal.dot(H);
            float HdotV = H.dot(wo);
            float D = D_GTR2(NdotH, a);
            p += (D * NdotH / (4 * HdotV + 0.001f)) * (specWeight / total);
        }
        return p;
    }
};

ASTRORAY_REGISTER_MATERIAL("disney", DisneyPlugin)

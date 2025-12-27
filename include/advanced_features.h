#pragma once

#include "raytracer.h"
#include <fstream>
#include <sstream>
#include <unordered_map>

// ============================================================================
// COMPLETE DISNEY PRINCIPLED BRDF
// ============================================================================

class DisneyBRDF : public Material {
    Vec3 baseColor;
    float metallic, roughness, anisotropic, anisotropicRotation;
    float subsurface, specular, specularTint;
    float clearcoat, clearcoatGloss;
    float sheen, sheenTint;
    float transmission, transmissionRoughness, ior;
    
    // GGX/Trowbridge-Reitz distribution
    float D_GTR(float NdotH, float a) const {
        if (a >= 1) return 1 / M_PI;
        float a2 = a * a;
        float t = 1 + (a2 - 1) * NdotH * NdotH;
        return (a2 - 1) / (M_PI * std::log(a2) * t);
    }
    
    float D_GTR2(float NdotH, float a) const {
        float a2 = a * a;
        float t = 1 + (a2 - 1) * NdotH * NdotH;
        return a2 / (M_PI * t * t);
    }
    
    float D_GTR2_aniso(float NdotH, float HdotX, float HdotY, float ax, float ay) const {
        return 1 / (M_PI * ax * ay * std::pow(
            (HdotX * HdotX) / (ax * ax) + 
            (HdotY * HdotY) / (ay * ay) + 
            NdotH * NdotH, 2));
    }
    
    float smithG_GGX(float NdotV, float alphaG) const {
        float a = alphaG * alphaG;
        float b = NdotV * NdotV;
        return 1 / (NdotV + std::sqrt(a + b - a * b));
    }
    
    float smithG_GGX_aniso(float NdotV, float VdotX, float VdotY, float ax, float ay) const {
        return 1 / (NdotV + std::sqrt(
            (VdotX * ax) * (VdotX * ax) + 
            (VdotY * ay) * (VdotY * ay) + 
            NdotV * NdotV));
    }
    
    Vec3 fresnelSchlick(float cosTheta, const Vec3& F0) const {
        return F0 + (Vec3(1) - F0) * std::pow(std::clamp(1 - cosTheta, 0.0f, 1.0f), 5);
    }
    
    Vec3 fresnelSchlickRoughness(float cosTheta, const Vec3& F0, float roughness) const {
        return F0 + (Vec3(std::max(1 - roughness, F0.x)) - F0) * 
               std::pow(std::clamp(1 - cosTheta, 0.0f, 1.0f), 5);
    }
    
    float fresnelDielectric(float cosThetaI, float etaI, float etaT) const {
        cosThetaI = std::clamp(cosThetaI, -1.0f, 1.0f);
        bool entering = cosThetaI > 0;
        if (!entering) {
            std::swap(etaI, etaT);
            cosThetaI = std::abs(cosThetaI);
        }
        
        float sinThetaI = std::sqrt(std::max(0.0f, 1 - cosThetaI * cosThetaI));
        float sinThetaT = etaI / etaT * sinThetaI;
        
        if (sinThetaT >= 1) return 1;
        
        float cosThetaT = std::sqrt(std::max(0.0f, 1 - sinThetaT * sinThetaT));
        
        float Rparl = ((etaT * cosThetaI) - (etaI * cosThetaT)) /
                      ((etaT * cosThetaI) + (etaI * cosThetaT));
        float Rperp = ((etaI * cosThetaI) - (etaT * cosThetaT)) /
                      ((etaI * cosThetaI) + (etaT * cosThetaT));
        
        return (Rparl * Rparl + Rperp * Rperp) / 2;
    }
    
public:
    DisneyBRDF(const Vec3& color, float metal = 0, float rough = 0.5f,
               float trans = 0, float iorVal = 1.5f)
        : baseColor(color), metallic(metal), roughness(rough), 
          anisotropic(0), anisotropicRotation(0),
          subsurface(0), specular(0.5f), specularTint(0),
          clearcoat(0), clearcoatGloss(1),
          sheen(0), sheenTint(0.5f),
          transmission(trans), transmissionRoughness(rough), ior(iorVal) {}
    
    void setAnisotropic(float aniso, float rotation) {
        anisotropic = aniso;
        anisotropicRotation = rotation;
    }
    
    void setClearcoat(float coat, float gloss) {
        clearcoat = coat;
        clearcoatGloss = gloss;
    }
    
    void setSheen(float s, float tint) {
        sheen = s;
        sheenTint = tint;
    }
    
    void setSubsurface(float ss) {
        subsurface = ss;
    }
    
    Vec3 eval(const HitRecord& rec, const Vec3& wo, const Vec3& wi) const override {
        Vec3 N = rec.normal;
        Vec3 X = rec.tangent;
        Vec3 Y = rec.bitangent;
        
        float NdotL = N.dot(wi);
        float NdotV = N.dot(wo);
        
        if (NdotL <= 0 || NdotV <= 0) return Vec3(0);
        
        Vec3 H = (wi + wo).normalized();
        float NdotH = N.dot(H);
        float LdotH = wi.dot(H);
        
        Vec3 Cdlin = baseColor;
        float Cdlum = luminance(Cdlin);
        Vec3 Ctint = Cdlum > 0 ? Cdlin / Cdlum : Vec3(1);
        Vec3 Cspec0 = Vec3(specular * 0.08f) * (Vec3(1) * (1 - specularTint) + Ctint * specularTint);
        Vec3 Csheen = Vec3(1) * (1 - sheenTint) + Ctint * sheenTint;
        
        // Metallic workflow
        Vec3 F0 = Vec3::min(Cspec0 * (1 - metallic) + Cdlin * metallic, Vec3(1));
        
        // Diffuse
        float FL = std::pow(1 - NdotL, 5);
        float FV = std::pow(1 - NdotV, 5);
        float Fd90 = 0.5f + 2 * LdotH * LdotH * roughness;
        float Fd = (1 + (Fd90 - 1) * FL) * (1 + (Fd90 - 1) * FV);
        
        // Subsurface
        float Fss90 = LdotH * LdotH * roughness;
        float Fss = (1 + (Fss90 - 1) * FL) * (1 + (Fss90 - 1) * FV);
        float ss = 1.25f * (Fss * (1 / (NdotL + NdotV) - 0.5f) + 0.5f);
        
        Vec3 diffuse = (1 / M_PI) * Cdlin * ((1 - subsurface) * Fd + subsurface * ss);
        
        // Specular
        float aspect = std::sqrt(1 - anisotropic * 0.9f);
        float ax = std::max(0.001f, roughness * roughness / aspect);
        float ay = std::max(0.001f, roughness * roughness * aspect);
        
        float Ds;
        if (anisotropic > 0) {
            float HdotX = H.dot(X);
            float HdotY = H.dot(Y);
            Ds = D_GTR2_aniso(NdotH, HdotX, HdotY, ax, ay);
        } else {
            Ds = D_GTR2(NdotH, roughness * roughness);
        }
        
        Vec3 F = fresnelSchlickRoughness(LdotH, F0, roughness);
        
        float Gs;
        if (anisotropic > 0) {
            float VdotX = wo.dot(X);
            float VdotY = wo.dot(Y);
            float LdotX = wi.dot(X);
            float LdotY = wi.dot(Y);
            Gs = smithG_GGX_aniso(NdotL, LdotX, LdotY, ax, ay) * 
                 smithG_GGX_aniso(NdotV, VdotX, VdotY, ax, ay);
        } else {
            Gs = smithG_GGX(NdotL, roughness * roughness) * 
                 smithG_GGX(NdotV, roughness * roughness);
        }
        
        Vec3 specular = Ds * F * Gs / (4 * NdotL * NdotV);
        
        // Sheen
        Vec3 Fsheen = sheen * Csheen * std::pow(1 - LdotH, 5);
        
        // Clearcoat
        float Dr = D_GTR2(NdotH, clearcoatGloss * clearcoatGloss);
        float Fr = 0.04f + (1 - 0.04f) * std::pow(1 - LdotH, 5);
        float Gr = smithG_GGX(NdotL, 0.25f) * smithG_GGX(NdotV, 0.25f);
        Vec3 clearcoatTerm = Vec3(clearcoat * Dr * Fr * Gr / (4 * NdotL * NdotV));
        
        Vec3 result = ((1 - metallic) * (1 - transmission) * diffuse + 
                      specular + 
                      (1 - metallic) * Fsheen + 
                      clearcoatTerm) * NdotL;
        
        return result;
    }
    
    BSDFSample sample(const HitRecord& rec, const Vec3& wo, std::mt19937& gen) const override {
        BSDFSample s;
        std::uniform_real_distribution<float> dist(0, 1);
        
        // Choose between transmission and reflection
        if (transmission > 0 && dist(gen) < transmission) {
            // Handle transmission
            float etaI = rec.frontFace ? 1.0f : ior;
            float etaT = rec.frontFace ? ior : 1.0f;
            float eta = etaI / etaT;
            
            Vec3 N = rec.normal;
            float cosTheta = wo.dot(N);
            float sinTheta = std::sqrt(std::max(0.0f, 1 - cosTheta * cosTheta));
            
            // Check for total internal reflection
            bool cannotRefract = eta * sinTheta > 1;
            float fresnel = fresnelDielectric(cosTheta, etaI, etaT);
            
            if (cannotRefract || dist(gen) < fresnel) {
                // Reflect
                s.wi = wo - N * (2 * wo.dot(N));
                s.f = Vec3(1);
                s.pdf = fresnel;
            } else {
                // Refract
                Vec3 wt_perp = (wo - N * cosTheta) * (-eta);
                Vec3 wt_parallel = N * (-std::sqrt(std::abs(1 - wt_perp.length2())));
                s.wi = (wt_perp + wt_parallel).normalized();
                s.f = baseColor * (1 - fresnel) * (eta * eta);
                s.pdf = (1 - fresnel) * transmission;
            }
            s.isDelta = transmissionRoughness < 0.01f;
            return s;
        }
        
        // Sample between diffuse, specular, and clearcoat
        float diffuseWeight = (1 - metallic) * (1 - transmission);
        float specularWeight = 1;
        float clearcoatWeight = clearcoat * 0.25f;
        float totalWeight = diffuseWeight + specularWeight + clearcoatWeight;
        
        float u = dist(gen) * totalWeight;
        
        if (u < diffuseWeight) {
            // Sample diffuse
            Vec3 localWi = Vec3::randomCosineDirection(gen);
            s.wi = rec.tangent * localWi.x + rec.bitangent * localWi.y + rec.normal * localWi.z;
            s.f = eval(rec, wo, s.wi);
            s.pdf = rec.normal.dot(s.wi) / M_PI * (diffuseWeight / totalWeight);
        } else if (u < diffuseWeight + specularWeight) {
            // Sample specular (GGX)
            float r1 = dist(gen);
            float r2 = dist(gen);
            
            float a = roughness * roughness;
            float phi = 2 * M_PI * r1;
            float cosTheta = std::sqrt((1 - r2) / (1 + (a * a - 1) * r2));
            float sinTheta = std::sqrt(1 - cosTheta * cosTheta);
            
            Vec3 h(std::cos(phi) * sinTheta, std::sin(phi) * sinTheta, cosTheta);
            
            if (anisotropic > 0) {
                // Apply anisotropic rotation
                float cos_r = std::cos(anisotropicRotation * 2 * M_PI);
                float sin_r = std::sin(anisotropicRotation * 2 * M_PI);
                Vec3 X_rot = rec.tangent * cos_r - rec.bitangent * sin_r;
                Vec3 Y_rot = rec.tangent * sin_r + rec.bitangent * cos_r;
                h = X_rot * h.x + Y_rot * h.y + rec.normal * h.z;
            } else {
                h = rec.tangent * h.x + rec.bitangent * h.y + rec.normal * h.z;
            }
            
            s.wi = (h * (2 * wo.dot(h)) - wo).normalized();
            
            if (rec.normal.dot(s.wi) > 0) {
                s.f = eval(rec, wo, s.wi);
                float NdotH = rec.normal.dot(h);
                float HdotV = h.dot(wo);
                float D = D_GTR2(NdotH, a);
                s.pdf = D * NdotH / (4 * HdotV) * (specularWeight / totalWeight);
            }
        } else {
            // Sample clearcoat
            float r1 = dist(gen);
            float r2 = dist(gen);
            
            float a = clearcoatGloss * clearcoatGloss;
            float phi = 2 * M_PI * r1;
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
                s.pdf = D * NdotH / (4 * HdotV) * (clearcoatWeight / totalWeight);
            }
        }
        
        s.isDelta = false;
        return s;
    }
    
    float pdf(const HitRecord& rec, const Vec3& wo, const Vec3& wi) const override {
        Vec3 N = rec.normal;
        Vec3 H = (wo + wi).normalized();
        
        float diffuseWeight = (1 - metallic) * (1 - transmission);
        float specularWeight = 1;
        float clearcoatWeight = clearcoat * 0.25f;
        float totalWeight = diffuseWeight + specularWeight + clearcoatWeight;
        
        float pdf = 0;
        
        // Diffuse PDF
        if (diffuseWeight > 0) {
            float cosTheta = N.dot(wi);
            pdf += (cosTheta / M_PI) * (diffuseWeight / totalWeight);
        }
        
        // Specular PDF
        if (specularWeight > 0) {
            float NdotH = N.dot(H);
            float HdotV = H.dot(wo);
            float a = roughness * roughness;
            float D = D_GTR2(NdotH, a);
            pdf += (D * NdotH / (4 * HdotV)) * (specularWeight / totalWeight);
        }
        
        // Clearcoat PDF
        if (clearcoatWeight > 0) {
            float NdotH = N.dot(H);
            float HdotV = H.dot(wo);
            float a = clearcoatGloss * clearcoatGloss;
            float D = D_GTR2(NdotH, a);
            pdf += (D * NdotH / (4 * HdotV)) * (clearcoatWeight / totalWeight);
        }
        
        return pdf;
    }
};

// ============================================================================
// TEXTURE SYSTEM
// ============================================================================

class Texture {
public:
    virtual ~Texture() = default;
    virtual Vec3 value(const Vec2& uv, const Vec3& p) const = 0;
};

class SolidColor : public Texture {
    Vec3 color;
public:
    SolidColor(const Vec3& c) : color(c) {}
    Vec3 value(const Vec2& uv, const Vec3& p) const override {
        return color;
    }
};

class CheckerTexture : public Texture {
    std::shared_ptr<Texture> odd, even;
    float scale;
public:
    CheckerTexture(std::shared_ptr<Texture> o, std::shared_ptr<Texture> e, float s = 10)
        : odd(o), even(e), scale(s) {}
    
    CheckerTexture(const Vec3& c1, const Vec3& c2, float s = 10)
        : odd(std::make_shared<SolidColor>(c1)),
          even(std::make_shared<SolidColor>(c2)),
          scale(s) {}
    
    Vec3 value(const Vec2& uv, const Vec3& p) const override {
        float sines = std::sin(scale * p.x) * std::sin(scale * p.y) * std::sin(scale * p.z);
        if (sines < 0)
            return odd->value(uv, p);
        else
            return even->value(uv, p);
    }
};

class ImageTexture : public Texture {
    std::vector<Vec3> data;
    int width, height;
    
public:
    ImageTexture() : width(0), height(0) {}
    
    bool loadPPM(const std::string& filename) {
        std::ifstream file(filename);
        if (!file.is_open()) return false;
        
        std::string magic;
        file >> magic;
        if (magic != "P3" && magic != "P6") return false;
        
        file >> width >> height;
        int maxval;
        file >> maxval;
        
        data.resize(width * height);
        
        if (magic == "P3") {
            for (int i = 0; i < width * height; i++) {
                int r, g, b;
                file >> r >> g >> b;
                data[i] = Vec3(r / 255.0f, g / 255.0f, b / 255.0f);
            }
        } else {
            file.read((char*)&data[0], width * height * 3);
        }
        
        return true;
    }
    
    Vec3 value(const Vec2& uv, const Vec3& p) const override {
        if (data.empty()) return Vec3(1, 0, 1);
        
        // Clamp UV coordinates
        float u = std::clamp(uv.u, 0.0f, 1.0f);
        float v = 1 - std::clamp(uv.v, 0.0f, 1.0f); // Flip V
        
        int i = static_cast<int>(u * width);
        int j = static_cast<int>(v * height);
        
        if (i >= width) i = width - 1;
        if (j >= height) j = height - 1;
        
        return data[j * width + i];
    }
};

class NoiseTexture : public Texture {
    float scale;

public:
    // Make noise() public and static so other classes can use it
    static float noise(const Vec3& p) {
        // Simple value noise - should be replaced with Perlin noise
        float n = std::sin(p.dot(Vec3(12.9898f, 78.233f, 37.719f))) * 43758.5453f;
        return n - std::floor(n);
    }
    
    NoiseTexture(float s = 1) : scale(s) {}
    
    Vec3 value(const Vec2& uv, const Vec3& p) const override {
        float n = noise(p * scale);
        return Vec3(n);
    }
};

// ============================================================================
// TEXTURED MATERIALS
// ============================================================================

class TexturedLambertian : public Material {
    std::shared_ptr<Texture> albedo;
public:
    TexturedLambertian(std::shared_ptr<Texture> a) : albedo(a) {}
    
    Vec3 eval(const HitRecord& rec, const Vec3& wo, const Vec3& wi) const override {
        if (wi.dot(rec.normal) <= 0) return Vec3(0);
        return albedo->value(rec.uv, rec.point) / M_PI * wi.dot(rec.normal);
    }
    
    BSDFSample sample(const HitRecord& rec, const Vec3& wo, std::mt19937& gen) const override {
        BSDFSample s;
        Vec3 localWi = Vec3::randomCosineDirection(gen);
        s.wi = rec.tangent * localWi.x + rec.bitangent * localWi.y + rec.normal * localWi.z;
        s.f = albedo->value(rec.uv, rec.point) / M_PI * s.wi.dot(rec.normal);
        s.pdf = s.wi.dot(rec.normal) / M_PI;
        s.isDelta = false;
        return s;
    }
    
    float pdf(const HitRecord& rec, const Vec3& wo, const Vec3& wi) const override {
        float cosTheta = wi.dot(rec.normal);
        return cosTheta > 0 ? cosTheta / M_PI : 0;
    }
};

// ============================================================================
// SUBSURFACE SCATTERING
// ============================================================================

class SubsurfaceMaterial : public Material {
    Vec3 albedo, scatterDistance;
    float scale;
    
public:
    SubsurfaceMaterial(const Vec3& a, const Vec3& scatter, float s = 1.0f)
        : albedo(a), scatterDistance(scatter), scale(s) {}
    
    Vec3 eval(const HitRecord& rec, const Vec3& wo, const Vec3& wi) const override {
        // Simplified - real SSS requires more complex evaluation
        float cosTheta = std::abs(wi.dot(rec.normal));
        Vec3 transmission(1);
        
        // Very rough approximation
        float distance = 1.0f / (cosTheta + 0.1f);
        transmission.x = std::exp(-distance / scatterDistance.x);
        transmission.y = std::exp(-distance / scatterDistance.y);
        transmission.z = std::exp(-distance / scatterDistance.z);
        
        return albedo * transmission * cosTheta / M_PI;
    }
    
    BSDFSample sample(const HitRecord& rec, const Vec3& wo, std::mt19937& gen) const override {
        BSDFSample s;
        std::uniform_real_distribution<float> dist(0, 1);
        
        // Sample hemisphere with subsurface weighting
        Vec3 localWi = Vec3::randomCosineDirection(gen);
        
        // Randomly decide between front and back scattering
        if (dist(gen) < 0.5f) {
            localWi.z = -localWi.z; // Back scattering
        }
        
        s.wi = rec.tangent * localWi.x + rec.bitangent * localWi.y + rec.normal * localWi.z;
        
        // Simplified evaluation
        float r = -std::log(dist(gen)) * scale;
        Vec3 transmission(
            std::exp(-r / scatterDistance.x),
            std::exp(-r / scatterDistance.y),
            std::exp(-r / scatterDistance.z)
        );
        
        s.f = albedo * transmission;
        s.pdf = std::abs(rec.normal.dot(s.wi)) / M_PI;
        s.isDelta = false;
        
        return s;
    }
    
    float pdf(const HitRecord& rec, const Vec3& wo, const Vec3& wi) const override {
        return std::abs(rec.normal.dot(wi)) / M_PI;
    }
};

// ============================================================================
// VOLUME RENDERING
// ============================================================================

class ConstantMedium : public Hittable {
    std::shared_ptr<Hittable> boundary;
    float negInvDensity;
    Vec3 albedo;
    float g; // Anisotropy parameter for Henyey-Greenstein
    
    float henyeyGreenstein(float cosTheta) const {
        float g2 = g * g;
        float denom = 1 + g2 - 2 * g * cosTheta;
        return (1 - g2) / (4 * M_PI * denom * std::sqrt(denom));
    }
    
public:
    ConstantMedium(std::shared_ptr<Hittable> b, float density, const Vec3& a, float aniso = 0)
        : boundary(b), negInvDensity(-1 / density), albedo(a), g(aniso) {}
    
    bool hit(const Ray& r, float tMin, float tMax, HitRecord& rec) const override {
        HitRecord rec1, rec2;
        
        if (!boundary->hit(r, -std::numeric_limits<float>::max(), 
                          std::numeric_limits<float>::max(), rec1))
            return false;
        
        if (!boundary->hit(r, rec1.t + 0.0001f, 
                          std::numeric_limits<float>::max(), rec2))
            return false;
        
        if (rec1.t < tMin) rec1.t = tMin;
        if (rec2.t > tMax) rec2.t = tMax;
        if (rec1.t >= rec2.t) return false;
        if (rec1.t < 0) rec1.t = 0;
        
        float rayLength = r.direction.length();
        float distanceInsideBoundary = (rec2.t - rec1.t) * rayLength;
        
        std::mt19937 gen(std::random_device{}());
        std::uniform_real_distribution<float> dist(0, 1);
        float hitDistance = negInvDensity * std::log(dist(gen));
        
        if (hitDistance > distanceInsideBoundary)
            return false;
        
        rec.t = rec1.t + hitDistance / rayLength;
        rec.point = r.at(rec.t);
        rec.normal = Vec3(1, 0, 0);  // Arbitrary
        rec.frontFace = true;
        
        // Create isotropic phase function material
        rec.material = std::make_shared<Lambertian>(albedo);
        
        return true;
    }
    
    bool boundingBox(AABB& box) const override {
        return boundary->boundingBox(box);
    }
};

// ============================================================================
// MESH LOADING WITH UV SUPPORT
// ============================================================================

class Mesh : public Hittable {
public:
    struct Vertex {
        Vec3 position, normal;
        Vec2 uv;
    };
    
private:
    std::vector<Vertex> vertices;
    std::vector<int> indices;
    std::shared_ptr<Material> material;
    std::vector<std::shared_ptr<Triangle>> triangles;
    std::shared_ptr<BVHAccel> bvh;
    AABB bbox;
    
    Vec3 parseVec3(const std::string& line) {
        std::istringstream iss(line);
        std::string prefix;
        float x, y, z;
        iss >> prefix >> x >> y >> z;
        return Vec3(x, y, z);
    }
    
    Vec2 parseVec2(const std::string& line) {
        std::istringstream iss(line);
        std::string prefix;
        float u, v;
        iss >> prefix >> u >> v;
        return Vec2(u, v);
    }
    
public:
    Mesh(std::shared_ptr<Material> mat) : material(mat) {}
    
    bool loadOBJ(const std::string& filename) {
        std::ifstream file(filename);
        if (!file.is_open()) return false;
        
        std::vector<Vec3> positions;
        std::vector<Vec3> normals;
        std::vector<Vec2> uvs;
        
        std::string line;
        while (std::getline(file, line)) {
            if (line.substr(0, 2) == "v ") {
                positions.push_back(parseVec3(line));
            } else if (line.substr(0, 3) == "vn ") {
                normals.push_back(parseVec3(line).normalized());
            } else if (line.substr(0, 3) == "vt ") {
                uvs.push_back(parseVec2(line));
            } else if (line.substr(0, 2) == "f ") {
                std::istringstream iss(line.substr(2));
                std::string vertex;
                std::vector<int> faceIndices;
                std::vector<int> uvIndices;
                std::vector<int> normalIndices;
                
                while (iss >> vertex) {
                    std::replace(vertex.begin(), vertex.end(), '/', ' ');
                    std::istringstream viss(vertex);
                    int vIdx, uvIdx = 0, nIdx = 0;
                    viss >> vIdx;
                    if (viss >> uvIdx) {
                        if (viss >> nIdx) {
                            // v/vt/vn format
                        }
                    }
                    
                    faceIndices.push_back(vIdx - 1);
                    if (uvIdx > 0) uvIndices.push_back(uvIdx - 1);
                    if (nIdx > 0) normalIndices.push_back(nIdx - 1);
                }
                
                // Triangulate face
                for (size_t i = 1; i < faceIndices.size() - 1; ++i) {
                    Vec3 p0 = positions[faceIndices[0]];
                    Vec3 p1 = positions[faceIndices[i]];
                    Vec3 p2 = positions[faceIndices[i + 1]];
                    
                    Vec2 uv0 = uvIndices.size() > 0 ? uvs[uvIndices[0]] : Vec2(0, 0);
                    Vec2 uv1 = uvIndices.size() > i ? uvs[uvIndices[i]] : Vec2(1, 0);
                    Vec2 uv2 = uvIndices.size() > i + 1 ? uvs[uvIndices[i + 1]] : Vec2(0, 1);
                    
                    triangles.push_back(std::make_shared<Triangle>(p0, p1, p2, uv0, uv1, uv2, material));
                }
            }
        }
        
        return buildBVH();
    }
    
    bool buildBVH() {
        if (triangles.empty()) return false;
        
        std::vector<std::shared_ptr<Hittable>> hittables;
        for (auto& tri : triangles) {
            hittables.push_back(tri);
        }
        
        bvh = std::make_shared<BVHAccel>(hittables);
        bvh->boundingBox(bbox);
        return true;
    }
    
    bool hit(const Ray& r, float tMin, float tMax, HitRecord& rec) const override {
        return bvh ? bvh->hit(r, tMin, tMax, rec) : false;
    }
    
    bool boundingBox(AABB& box) const override {
        box = bbox;
        return true;
    }
};

// ============================================================================
// PROCEDURAL TEXTURES
// ============================================================================

class MarbleTexture : public Texture {
    float scale;
    Vec3 color1, color2;
    
    float turbulence(const Vec3& p, int depth = 7) const {
        float accum = 0;
        Vec3 tempP = p;
        float weight = 1.0f;
        
        for (int i = 0; i < depth; i++) {
            accum += weight * NoiseTexture::noise(tempP);
            weight *= 0.5f;
            tempP *= 2;
        }
        
        return std::abs(accum);
    }
    
public:
    MarbleTexture(float s = 1, const Vec3& c1 = Vec3(0.8f), const Vec3& c2 = Vec3(0.2f))
        : scale(s), color1(c1), color2(c2) {}
    
    Vec3 value(const Vec2& uv, const Vec3& p) const override {
        float n = 0.5f * (1 + std::sin(scale * p.z + 10 * turbulence(p)));
        return color1 * n + color2 * (1 - n);
    }
};

class WoodTexture : public Texture {
    float scale;
    Vec3 color1, color2;
    
    float noise(const Vec3& p) const {
        float n = std::sin(p.dot(Vec3(12.9898f, 78.233f, 37.719f))) * 43758.5453f;
        return n - std::floor(n);
    }
    
public:
    WoodTexture(float s = 1, const Vec3& c1 = Vec3(0.6f, 0.3f, 0.1f), 
                const Vec3& c2 = Vec3(0.4f, 0.2f, 0.05f))
        : scale(s), color1(c1), color2(c2) {}
    
    Vec3 value(const Vec2& uv, const Vec3& p) const override {
        float r = std::sqrt(p.x * p.x + p.z * p.z);
        float n = noise(Vec3(r * scale, p.y * scale, 0));
        n = (n + 1) * 0.5f;
        n = std::pow(n, 3);
        return color1 * n + color2 * (1 - n);
    }
};

// ============================================================================
// ENVIRONMENT MAPPING
// ============================================================================

class EnvironmentLight : public Material {
    std::shared_ptr<Texture> envMap;
    float intensity;
    
public:
    EnvironmentLight(std::shared_ptr<Texture> tex, float i = 1)
        : envMap(tex), intensity(i) {}
    
    Vec3 emitted(const HitRecord& rec) const override {
        // Convert direction to spherical coordinates
        Vec3 dir = rec.normal;  // For environment, normal is the ray direction
        float theta = std::acos(std::clamp(dir.y, -1.0f, 1.0f));
        float phi = std::atan2(dir.z, dir.x);
        
        Vec2 uv(phi / (2 * M_PI) + 0.5f, theta / M_PI);
        
        return envMap->value(uv, rec.point) * intensity;
    }
};

// ============================================================================
// INSTANCING AND TRANSFORMATIONS
// ============================================================================

class Transform : public Hittable {
protected:
    std::shared_ptr<Hittable> object;
    
public:
    Transform(std::shared_ptr<Hittable> obj) : object(obj) {}
    
    virtual Vec3 transformPoint(const Vec3& p) const = 0;
    virtual Vec3 transformVector(const Vec3& v) const = 0;
    virtual Vec3 inverseTransformPoint(const Vec3& p) const = 0;
    virtual Vec3 inverseTransformVector(const Vec3& v) const = 0;
    
    bool hit(const Ray& r, float tMin, float tMax, HitRecord& rec) const override {
        Vec3 origin = inverseTransformPoint(r.origin);
        Vec3 direction = inverseTransformVector(r.direction);
        Ray transformedRay(origin, direction, r.time);
        
        if (!object->hit(transformedRay, tMin, tMax, rec))
            return false;
        
        rec.point = transformPoint(rec.point);
        rec.normal = transformVector(rec.normal).normalized();
        rec.setFaceNormal(r, rec.normal);
        
        return true;
    }
    
    bool boundingBox(AABB& box) const override {
        AABB objBox;
        if (!object->boundingBox(objBox))
            return false;
        
        // Transform all 8 corners of the bounding box
        Vec3 corners[8] = {
            Vec3(objBox.min.x, objBox.min.y, objBox.min.z),
            Vec3(objBox.max.x, objBox.min.y, objBox.min.z),
            Vec3(objBox.min.x, objBox.max.y, objBox.min.z),
            Vec3(objBox.min.x, objBox.min.y, objBox.max.z),
            Vec3(objBox.max.x, objBox.max.y, objBox.min.z),
            Vec3(objBox.max.x, objBox.min.y, objBox.max.z),
            Vec3(objBox.min.x, objBox.max.y, objBox.max.z),
            Vec3(objBox.max.x, objBox.max.y, objBox.max.z)
        };
        
        Vec3 min(std::numeric_limits<float>::max());
        Vec3 max(std::numeric_limits<float>::lowest());
        
        for (const auto& corner : corners) {
            Vec3 transformed = transformPoint(corner);
            min = Vec3::min(min, transformed);
            max = Vec3::max(max, transformed);
        }
        
        box = AABB(min, max);
        return true;
    }
};

class Translate : public Transform {
    Vec3 offset;
    
public:
    Translate(std::shared_ptr<Hittable> obj, const Vec3& displacement)
        : Transform(obj), offset(displacement) {}
    
    Vec3 transformPoint(const Vec3& p) const override { return p + offset; }
    Vec3 transformVector(const Vec3& v) const override { return v; }
    Vec3 inverseTransformPoint(const Vec3& p) const override { return p - offset; }
    Vec3 inverseTransformVector(const Vec3& v) const override { return v; }
};

class Scale : public Transform {
    Vec3 scale;
    
public:
    Scale(std::shared_ptr<Hittable> obj, const Vec3& s)
        : Transform(obj), scale(s) {}
    
    Vec3 transformPoint(const Vec3& p) const override { 
        return Vec3(p.x * scale.x, p.y * scale.y, p.z * scale.z); 
    }
    Vec3 transformVector(const Vec3& v) const override { 
        return Vec3(v.x * scale.x, v.y * scale.y, v.z * scale.z); 
    }
    Vec3 inverseTransformPoint(const Vec3& p) const override { 
        return Vec3(p.x / scale.x, p.y / scale.y, p.z / scale.z); 
    }
    Vec3 inverseTransformVector(const Vec3& v) const override { 
        return Vec3(v.x / scale.x, v.y / scale.y, v.z / scale.z); 
    }
};

class RotateY : public Transform {
    float sinTheta, cosTheta;
    
public:
    RotateY(std::shared_ptr<Hittable> obj, float angle)
        : Transform(obj) {
        float radians = angle * M_PI / 180.0f;
        sinTheta = std::sin(radians);
        cosTheta = std::cos(radians);
    }
    
    Vec3 transformPoint(const Vec3& p) const override {
        return Vec3(cosTheta * p.x - sinTheta * p.z, p.y, sinTheta * p.x + cosTheta * p.z);
    }
    Vec3 transformVector(const Vec3& v) const override {
        return Vec3(cosTheta * v.x - sinTheta * v.z, v.y, sinTheta * v.x + cosTheta * v.z);
    }
    Vec3 inverseTransformPoint(const Vec3& p) const override {
        return Vec3(cosTheta * p.x + sinTheta * p.z, p.y, -sinTheta * p.x + cosTheta * p.z);
    }
    Vec3 inverseTransformVector(const Vec3& v) const override {
        return Vec3(cosTheta * v.x + sinTheta * v.z, v.y, -sinTheta * v.x + cosTheta * v.z);
    }
};
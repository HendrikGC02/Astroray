#pragma once
#include "raytracer.h"
#include <fstream>
#include <sstream>

// ============================================================================
// DISNEY PRINCIPLED BRDF (Fixed Fresnel)
// ============================================================================

class DisneyBRDF : public Material {
    Vec3 baseColor;
    float metallic, roughness, anisotropic, anisotropicRotation;
    float subsurface, specular, specularTint;
    float clearcoat, clearcoatGloss;
    float sheen, sheenTint;
    float transmission, ior;
    
    float D_GTR2(float NdotH, float a) const {
        float a2 = a * a;
        float t = 1 + (a2 - 1) * NdotH * NdotH;
        return a2 / (M_PI * t * t + 0.001f);
    }
    
    float smithG_GGX(float NdotV, float alphaG) const {
        float a = alphaG * alphaG;
        float b = NdotV * NdotV;
        return 1 / (NdotV + std::sqrt(a + b - a * b) + 0.001f);
    }
    
    Vec3 fresnelSchlick(float cosTheta, const Vec3& F0) const {
        float c = std::clamp(1 - cosTheta, 0.0f, 1.0f);
        // Reduced Fresnel: multiply by 0.8 + baseline 0.04
        return F0 + (Vec3(1) - F0) * std::pow(c, 5) * 0.8f;
    }
    
public:
    DisneyBRDF(const Vec3& color, float metal = 0, float rough = 0.5f,
               float trans = 0, float iorVal = 1.5f)
        : baseColor(color), metallic(metal), roughness(std::max(0.001f, rough)), 
          anisotropic(0), anisotropicRotation(0), subsurface(0), specular(0.5f),
          specularTint(0), clearcoat(0), clearcoatGloss(1), sheen(0), sheenTint(0.5f),
          transmission(trans), ior(iorVal) {}
    
    void setAnisotropic(float aniso, float rotation) { anisotropic = aniso; anisotropicRotation = rotation; }
    void setClearcoat(float coat, float gloss) { clearcoat = coat; clearcoatGloss = gloss; }
    void setSheen(float s, float tint) { sheen = s; sheenTint = tint; }
    void setSubsurface(float ss) { subsurface = ss; }

    // Accessors for GPU upload
    Vec3  getBaseColor()          const { return baseColor; }
    float getRoughness()          const { return roughness; }
    float getMetallic()           const { return metallic; }
    float getIOR()                const { return ior; }
    float getTransmission()       const { return transmission; }
    float getClearcoat()          const { return clearcoat; }
    float getClearcoatGloss()     const { return clearcoatGloss; }
    float getSpecular()           const { return specular; }
    float getSpecularTint()       const { return specularTint; }
    float getSheen()              const { return sheen; }
    float getSheenTint()          const { return sheenTint; }
    float getSubsurface()         const { return subsurface; }
    float getAnisotropic()        const { return anisotropic; }
    float getAnisotropicRotation() const { return anisotropicRotation; }
    
    Vec3 eval(const HitRecord& rec, const Vec3& wo, const Vec3& wi) const override {
        Vec3 N = rec.normal;
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
        Vec3 F0 = Cspec0 * (1 - metallic) + Cdlin * metallic;
        F0 = Vec3::min(F0, Vec3(1));
        
        // Diffuse
        float FL = std::pow(1 - NdotL, 5);
        float FV = std::pow(1 - NdotV, 5);
        float Fd90 = 0.5f + 2 * LdotH * LdotH * roughness;
        float Fd = (1 + (Fd90 - 1) * FL) * (1 + (Fd90 - 1) * FV);
        Vec3 diffuse = (1 / M_PI) * Cdlin * Fd;
        
        // Specular — clamp alpha to 0.0064 (roughness 0.08) so near-mirror Disney materials
        // don't collapse to black due to the +0.001 epsilon guard in D_GTR2
        float a = std::max(roughness * roughness, 0.0064f);
        float Ds = D_GTR2(NdotH, a);
        Vec3 F = fresnelSchlick(LdotH, F0);
        float Gs = smithG_GGX(NdotL, a) * smithG_GGX(NdotV, a);
        Vec3 spec = Ds * F * Gs / (4 * NdotL * NdotV + 0.001f);
        
        // Sheen (reduced by 0.5)
        Vec3 Csheen = Vec3(1) * (1 - sheenTint) + Ctint * sheenTint;
        Vec3 Fsheen = sheen * Csheen * std::pow(1 - LdotH, 5) * 0.5f;
        
        // Clearcoat (reduced by 0.5)
        float Dr = D_GTR2(NdotH, clearcoatGloss * clearcoatGloss);
        float Fr = 0.04f + (1 - 0.04f) * std::pow(1 - LdotH, 5);
        float Gr = smithG_GGX(NdotL, 0.25f) * smithG_GGX(NdotV, 0.25f);
        Vec3 clearcoatTerm = Vec3(clearcoat * Dr * Fr * Gr / (4 * NdotL * NdotV + 0.001f)) * 0.5f;
        
        Vec3 result = ((1 - metallic) * (1 - transmission) * diffuse + spec +
                      (1 - metallic) * Fsheen + clearcoatTerm) * NdotL;
        float Fms = ggxMultiScatterCompensation(NdotV, NdotL, roughness);
        float msWeight = roughness * (2.0f - roughness);
        result += F0 * (Fms * msWeight * 1.3f);
        
        // Clamp to prevent fireflies
        result.x = std::min(result.x, 10.0f);
        result.y = std::min(result.y, 10.0f);
        result.z = std::min(result.z, 10.0f);
        return result;
    }
    
    BSDFSample sample(const HitRecord& rec, const Vec3& wo, std::mt19937& gen) const override {
        BSDFSample s;
        std::uniform_real_distribution<float> dist(0, 1);
        
        // Handle transmission (glass-like behavior)
        if (transmission > 0 && dist(gen) < transmission) {
            float etaI = rec.frontFace ? 1.0f : ior;
            float etaT = rec.frontFace ? ior : 1.0f;
            float eta = etaI / etaT;
            Vec3 n = rec.normal;
            float cosTheta = wo.dot(n);
            if (cosTheta < 0) { cosTheta = -cosTheta; n = -n; }
            
            float sinTheta = std::sqrt(std::max(0.0f, 1 - cosTheta * cosTheta));
            bool cannotRefract = eta * sinTheta > 1;
            
            // Fresnel
            float f0 = ((etaI - etaT) / (etaI + etaT));
            f0 = f0 * f0;
            float fresnel = f0 + (1 - f0) * std::pow(1 - cosTheta, 5);
            
            if (cannotRefract || dist(gen) < fresnel) {
                // Reflect
                s.wi = n * (2 * wo.dot(n)) - wo;
                s.f = Vec3(1);
                s.pdf = fresnel * transmission;
            } else {
                // Refract
                Vec3 perp = (wo - n * cosTheta) * (-eta);
                Vec3 para = n * (-std::sqrt(std::abs(1 - perp.length2())));
                s.wi = (perp + para).normalized();
                s.f = baseColor * (eta * eta);
                s.pdf = (1 - fresnel) * transmission;
            }
            s.isDelta = roughness < 0.1f;
            if (s.isDelta) const_cast<HitRecord&>(rec).isDelta = true;
            return s;
        }
        
        // Sample between diffuse and specular for non-transmissive
        float diffWeight = (1 - metallic) * (1 - transmission);
        float specWeight = 1;
        float total = diffWeight + specWeight;
        
        if (dist(gen) * total < diffWeight) {
            Vec3 localWi = Vec3::randomCosineDirection(gen);
            s.wi = rec.tangent * localWi.x + rec.bitangent * localWi.y + rec.normal * localWi.z;
            s.f = eval(rec, wo, s.wi);
            s.pdf = rec.normal.dot(s.wi) / M_PI * (diffWeight / total);
        } else {
            float a = std::max(roughness * roughness, 0.0064f); // min alpha = roughness 0.08, below which GGX collapses numerically
            float r1 = dist(gen), r2 = dist(gen);
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
                s.pdf = D * NdotH / (4 * HdotV + 0.001f) * (specWeight / total);
            }
        }
        s.isDelta = false;
        return s;
    }
    
    float pdf(const HitRecord& rec, const Vec3& wo, const Vec3& wi) const override {
        Vec3 H = (wo + wi).normalized();
        float diffWeight = (1 - metallic) * (1 - transmission);
        float specWeight = 1;
        float total = diffWeight + specWeight;
        float p = 0;
        if (diffWeight > 0) p += (rec.normal.dot(wi) / M_PI) * (diffWeight / total);
        if (specWeight > 0) {
            float a = roughness * roughness;
            float NdotH = rec.normal.dot(H);
            float HdotV = H.dot(wo);
            float D = D_GTR2(NdotH, a);
            p += (D * NdotH / (4 * HdotV + 0.001f)) * (specWeight / total);
        }
        return p;
    }
};

// ============================================================================
// TEXTURES
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
    Vec3 value(const Vec2&, const Vec3&) const override { return color; }
};

class CheckerTexture : public Texture {
    std::shared_ptr<Texture> odd, even;
    float scale;
public:
    CheckerTexture(const Vec3& c1, const Vec3& c2, float s = 10)
        : odd(std::make_shared<SolidColor>(c1)), even(std::make_shared<SolidColor>(c2)), scale(s) {}
    Vec3 value(const Vec2& uv, const Vec3& p) const override {
        float sines = std::sin(scale*p.x) * std::sin(scale*p.y) * std::sin(scale*p.z);
        return sines < 0 ? odd->value(uv, p) : even->value(uv, p);
    }
};

class NoiseTexture : public Texture {
    float scale;
public:
    static float noise(const Vec3& p) {
        float n = std::sin(p.dot(Vec3(12.9898f, 78.233f, 37.719f))) * 43758.5453f;
        return n - std::floor(n);
    }
    NoiseTexture(float s = 1) : scale(s) {}
    Vec3 value(const Vec2&, const Vec3& p) const override { return Vec3(noise(p * scale)); }
};

class ImageTexture : public Texture {
    std::vector<Vec3> data;
    int width = 0, height = 0;
public:
    void setData(const std::vector<Vec3>& d, int w, int h) { data = d; width = w; height = h; }
    Vec3 value(const Vec2& uv, const Vec3&) const override {
        if (data.empty()) return Vec3(1, 0, 1);
        float u = std::clamp(uv.u, 0.0f, 1.0f);
        float v = 1 - std::clamp(uv.v, 0.0f, 1.0f);
        int i = std::min((int)(u * width), width - 1);
        int j = std::min((int)(v * height), height - 1);
        return data[j * width + i];
    }
};

class MarbleTexture : public Texture {
    float scale;
    float turbulence(const Vec3& p, int depth = 7) const {
        float accum = 0, weight = 1.0f;
        Vec3 temp = p;
        for (int i = 0; i < depth; i++) { accum += weight * NoiseTexture::noise(temp); weight *= 0.5f; temp *= 2; }
        return std::abs(accum);
    }
public:
    MarbleTexture(float s = 1) : scale(s) {}
    Vec3 value(const Vec2&, const Vec3& p) const override {
        float n = 0.5f * (1 + std::sin(scale * p.z + 10 * turbulence(p)));
        return Vec3(0.8f) * n + Vec3(0.2f) * (1 - n);
    }
};

class WoodTexture : public Texture {
    float scale;
public:
    WoodTexture(float s = 1) : scale(s) {}
    Vec3 value(const Vec2&, const Vec3& p) const override {
        float r = std::sqrt(p.x*p.x + p.z*p.z);
        float n = NoiseTexture::noise(Vec3(r * scale, p.y * scale, 0));
        n = std::pow((n + 1) * 0.5f, 3);
        return Vec3(0.6f, 0.3f, 0.1f) * n + Vec3(0.4f, 0.2f, 0.05f) * (1 - n);
    }
};

// ============================================================================
// PROCEDURAL TEXTURES — issue #19
// ============================================================================

// --- Gradient texture ---
class GradientTexture : public Texture {
    // type: 0=linear, 1=quadratic, 2=easing, 3=diagonal, 4=spherical, 5=quadratic sphere, 6=radial
    int gradType;
    Vec3 color1, color2;
    float scale;
public:
    GradientTexture(int type = 0, const Vec3& c1 = Vec3(0), const Vec3& c2 = Vec3(1), float s = 1.0f)
        : gradType(type), color1(c1), color2(c2), scale(s) {}
    Vec3 value(const Vec2& uv, const Vec3& p) const override {
        Vec3 sp = p * scale;
        float t = 0;
        switch (gradType) {
            case 1: t = std::clamp(sp.x * sp.x, 0.0f, 1.0f); break;          // quadratic
            case 2: { float x = std::clamp(sp.x, 0.0f, 1.0f); t = x*x*(3-2*x); break; } // easing
            case 3: t = std::clamp((sp.x + sp.y) * 0.5f, 0.0f, 1.0f); break; // diagonal
            case 4: t = std::clamp(std::sqrt(sp.x*sp.x + sp.y*sp.y + sp.z*sp.z), 0.0f, 1.0f); break; // spherical
            case 5: { float r = std::sqrt(sp.x*sp.x + sp.y*sp.y + sp.z*sp.z); t = 1.0f - std::clamp(r*r, 0.0f, 1.0f); break; } // quadratic sphere
            case 6: t = std::fmod(std::atan2(sp.y, sp.x) / (2.0f * float(M_PI)) + 1.0f, 1.0f); break; // radial
            default: t = std::clamp(sp.x, 0.0f, 1.0f); break;                // linear
        }
        return color1 * (1.0f - t) + color2 * t;
    }
};

// --- Wave texture ---
// bandDir: 0=bands, 1=rings; profile: 0=sine, 1=saw, 2=triangle
class WaveTexture : public Texture {
    int bandDir;   // 0=bands (X), 1=rings (radial)
    int profile;   // 0=sine, 1=saw, 2=triangle
    float scale, distortion, detail, roughness, lacunarity;
    Vec3 colorLow, colorHigh;
public:
    WaveTexture(int bd = 0, int prof = 0, float sc = 5.0f, float dist = 0.0f,
                float det = 2.0f, float rough = 0.5f, float lac = 2.0f,
                const Vec3& c1 = Vec3(0), const Vec3& c2 = Vec3(1))
        : bandDir(bd), profile(prof), scale(sc), distortion(dist),
          detail(det), roughness(rough), lacunarity(lac), colorLow(c1), colorHigh(c2) {}

    static float turbulence(const Vec3& p, float det, float rough, float lac) {
        float accum = 0, w = 1.0f;
        Vec3 pp = p;
        int steps = std::max(1, (int)det);
        for (int i = 0; i < steps; ++i) {
            accum += w * NoiseTexture::noise(pp);
            w *= rough;
            pp = pp * lac;
        }
        return accum;
    }

    Vec3 value(const Vec2&, const Vec3& p) const override {
        Vec3 sp = p * scale;
        float d = distortion > 0.0f ? distortion * turbulence(sp, detail, roughness, lacunarity) : 0.0f;
        float phase;
        if (bandDir == 1) {
            float r = std::sqrt(sp.x*sp.x + sp.y*sp.y + sp.z*sp.z);
            phase = (r + d) * float(M_PI);
        } else {
            phase = (sp.x + d) * float(M_PI);
        }
        float t;
        if (profile == 1) { // saw
            t = 1.0f - std::fmod(phase / float(M_PI), 1.0f);
        } else if (profile == 2) { // triangle
            float x = std::fmod(phase / float(M_PI), 1.0f);
            t = x < 0.5f ? 2.0f * x : 2.0f - 2.0f * x;
        } else { // sine
            t = 0.5f + 0.5f * std::sin(phase);
        }
        return colorLow * (1.0f - t) + colorHigh * t;
    }
};

// --- Magic texture ---
class MagicTexture : public Texture {
    int turbDepth;
    float scale, distortion;
    Vec3 color1, color2;
public:
    MagicTexture(int depth = 2, float sc = 5.0f, float dist = 1.0f,
                 const Vec3& c1 = Vec3(0), const Vec3& c2 = Vec3(1))
        : turbDepth(depth), scale(sc), distortion(dist), color1(c1), color2(c2) {}
    Vec3 value(const Vec2&, const Vec3& p) const override {
        float x = std::sin((p.x * scale + p.y * scale + p.z * scale) * float(M_PI));
        float y = std::cos((-p.x * scale + p.y * scale - p.z * scale) * float(M_PI));
        float z = -std::cos((-p.x * scale - p.y * scale + p.z * scale) * float(M_PI));
        if (turbDepth > 1) {
            float d = distortion * 0.25f;
            x *= d; y *= d; z *= d;
            y = -std::cos(x - y + z) * d;
            if (turbDepth > 2) {
                x = std::cos(x - y - z) * d;
                if (turbDepth > 3) {
                    z = std::sin(-x - y + z) * d;
                    if (turbDepth > 4) y = -std::cos(x + y - z) * d;
                }
            }
        }
        float t = std::clamp(0.5f + 0.5f * (x + y + z) / 3.0f, 0.0f, 1.0f);
        return color1 * (1.0f - t) + color2 * t;
    }
};

// --- Voronoi texture ---
// distMetric: 0=Euclidean, 1=Manhattan, 2=Chebychev, 3=Minkowski(p=2.5)
// feature: 0=F1, 1=F2, 2=F1+F2, 3=F2-F1, 4=smooth_F1
class VoronoiTexture : public Texture {
    float scale, randomness, smoothness;
    int distMetric, feature;
    Vec3 colorLow, colorHigh;
public:
    VoronoiTexture(float sc = 5.0f, float rand = 1.0f, int dm = 0, int feat = 0,
                   float smooth = 1.0f, const Vec3& c1 = Vec3(0), const Vec3& c2 = Vec3(1))
        : scale(sc), randomness(rand), smoothness(smooth), distMetric(dm), feature(feat),
          colorLow(c1), colorHigh(c2) {}

    static float hash1(float n) {
        float x = std::sin(n) * 43758.5453f;
        return x - std::floor(x);
    }
    static Vec3 hash3(Vec3 p) {
        Vec3 q(p.dot(Vec3(127.1f, 311.7f, 74.7f)),
               p.dot(Vec3(269.5f, 183.3f, 246.1f)),
               p.dot(Vec3(113.5f, 271.9f, 124.6f)));
        return Vec3(hash1(q.x), hash1(q.y), hash1(q.z));
    }
    float dist(const Vec3& a, const Vec3& b) const {
        Vec3 d = a - b;
        switch (distMetric) {
            case 1: return std::abs(d.x) + std::abs(d.y) + std::abs(d.z);
            case 2: return std::max({std::abs(d.x), std::abs(d.y), std::abs(d.z)});
            case 3: { float p = 2.5f; return std::pow(std::pow(std::abs(d.x),p)+std::pow(std::abs(d.y),p)+std::pow(std::abs(d.z),p), 1.0f/p); }
            default: return std::sqrt(d.dot(d));
        }
    }
    Vec3 value(const Vec2&, const Vec3& p) const override {
        Vec3 sp = p * scale;
        Vec3 ip(std::floor(sp.x), std::floor(sp.y), std::floor(sp.z));
        float f1 = 1e9f, f2 = 1e9f;
        float smoothF1 = 0.0f;
        for (int dz = -1; dz <= 1; ++dz)
        for (int dy = -1; dy <= 1; ++dy)
        for (int dx = -1; dx <= 1; ++dx) {
            Vec3 nb(ip.x+dx, ip.y+dy, ip.z+dz);
            Vec3 r = nb + hash3(nb) * randomness;
            float d = dist(sp, r);
            if (d < f1) { f2 = f1; f1 = d; }
            else if (d < f2) { f2 = d; }
            if (smoothness > 0.0f && smoothness < 1e9f) {
                float h = std::max(smoothness - d, 0.0f) / smoothness;
                smoothF1 += h * h * h;
            }
        }
        float val;
        switch (feature) {
            case 1: val = f2; break;
            case 2: val = (f1 + f2) * 0.5f; break;
            case 3: val = f2 - f1; break;
            case 4: val = smoothness > 0.0f ? -std::log(smoothF1) / 3.0f : f1; break;
            default: val = f1; break;
        }
        float t = std::clamp(val, 0.0f, 1.0f);
        return colorLow * (1.0f - t) + colorHigh * t;
    }
};

// --- Brick texture ---
class BrickTexture : public Texture {
    Vec3 colorBrick, colorMortar;
    float brickWidth, brickHeight, mortarSize, offset, scale;
public:
    BrickTexture(const Vec3& brick = Vec3(0.7f, 0.35f, 0.2f),
                 const Vec3& mortar = Vec3(0.9f),
                 float bw = 0.5f, float bh = 0.25f, float mort = 0.02f,
                 float off = 0.5f, float sc = 5.0f)
        : colorBrick(brick), colorMortar(mortar),
          brickWidth(std::max(0.001f, bw)), brickHeight(std::max(0.001f, bh)),
          mortarSize(mort), offset(off), scale(sc) {}
    Vec3 value(const Vec2& uv, const Vec3&) const override {
        float u = uv.u * scale;
        float v = uv.v * scale;
        int row = (int)std::floor(v / brickHeight);
        float rowOffset = (row % 2 == 0) ? 0.0f : offset * brickWidth;
        float uu = std::fmod(u - rowOffset, brickWidth);
        if (uu < 0) uu += brickWidth;
        float vv = std::fmod(v, brickHeight);
        float half = mortarSize * 0.5f;
        if (uu < half || uu > brickWidth - half || vv < half || vv > brickHeight - half)
            return colorMortar;
        return colorBrick;
    }
};

// --- Musgrave (fBm) texture ---
class MusgraveTexture : public Texture {
    // type: 0=fBm, 1=multifractal, 2=ridged, 3=hybrid
    int musType;
    float scale, detail, dimension, lacunarity, gain;
    Vec3 colorLow, colorHigh;
public:
    MusgraveTexture(int type = 0, float sc = 5.0f, float det = 2.0f,
                   float dim = 2.0f, float lac = 2.0f, float g = 1.0f,
                   const Vec3& c1 = Vec3(0), const Vec3& c2 = Vec3(1))
        : musType(type), scale(sc), detail(det), dimension(dim),
          lacunarity(lac), gain(g), colorLow(c1), colorHigh(c2) {}
    Vec3 value(const Vec2&, const Vec3& p) const override {
        Vec3 sp = p * scale;
        float val = 0.0f;
        float amp = 1.0f, freq = 1.0f;
        float H = std::max(0.001f, dimension - 1.0f);
        int steps = std::max(1, (int)detail);
        if (musType == 2) { // ridged
            float signal = NoiseTexture::noise(sp);
            signal = std::abs(signal - 0.5f) * 2.0f; // ridge
            val = signal;
            float weight = 1.0f;
            for (int i = 1; i < steps; ++i) {
                sp = sp * lacunarity;
                amp *= gain;
                weight = std::clamp(signal * gain, 0.0f, 1.0f);
                signal = NoiseTexture::noise(sp);
                signal = (1.0f - std::abs(signal - 0.5f) * 2.0f);
                val += weight * std::pow(freq, -H) * signal;
                freq *= lacunarity;
                signal = val;
            }
        } else { // fBm / multifractal / hybrid
            for (int i = 0; i < steps; ++i) {
                val += amp * (NoiseTexture::noise(sp * freq) - 0.5f);
                freq *= lacunarity;
                amp *= std::pow(lacunarity, -H);
            }
        }
        float t = std::clamp(0.5f + 0.5f * val, 0.0f, 1.0f);
        return colorLow * (1.0f - t) + colorHigh * t;
    }
};

// ============================================================================
// TEXTURED MATERIAL
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
        float c = wi.dot(rec.normal);
        return c > 0 ? c / M_PI : 0;
    }
};

class NormalMappedMaterial : public Material {
    std::shared_ptr<Material> baseMaterial;
    std::shared_ptr<Texture> normalTexture;
    std::shared_ptr<Texture> bumpTexture;
    float normalStrength = 1.0f;
    float bumpStrength = 1.0f;
    float bumpDistance = 0.01f;

    static float heightValue(const Vec3& c) {
        return 0.2126f * c.x + 0.7152f * c.y + 0.0722f * c.z;
    }

    HitRecord perturbNormal(const HitRecord& rec) const {
        HitRecord out = rec;
        Vec3 n = rec.normal;

        if (normalTexture) {
            Vec3 rgb = normalTexture->value(rec.uv, rec.point);
            Vec3 nTS = (rgb * 2.0f) - Vec3(1.0f);
            Vec3 mapped = (rec.tangent * nTS.x + rec.bitangent * nTS.y + rec.normal * nTS.z).normalized();
            float t = std::clamp(normalStrength, 0.0f, 1.0f);
            n = (rec.normal * (1.0f - t) + mapped * t).normalized();
        }

        if (bumpTexture) {
            float eps = std::max(1e-4f, bumpDistance);
            float h0 = heightValue(bumpTexture->value(rec.uv, rec.point));
            float hU = heightValue(bumpTexture->value(Vec2(rec.uv.u + eps, rec.uv.v), rec.point));
            float hV = heightValue(bumpTexture->value(Vec2(rec.uv.u, rec.uv.v + eps), rec.point));
            float dU = (hU - h0) / eps;
            float dV = (hV - h0) / eps;
            Vec3 dp = rec.tangent * dU + rec.bitangent * dV;
            n = (n - dp * bumpStrength).normalized();
        }

        out.normal = n;
        buildOrthonormalBasis(out.normal, out.tangent, out.bitangent);
        return out;
    }

public:
    NormalMappedMaterial(std::shared_ptr<Material> base,
                         std::shared_ptr<Texture> normalTex,
                         std::shared_ptr<Texture> bumpTex,
                         float normalStr,
                         float bumpStr,
                         float bumpDist)
        : baseMaterial(std::move(base)),
          normalTexture(std::move(normalTex)),
          bumpTexture(std::move(bumpTex)),
          normalStrength(normalStr),
          bumpStrength(bumpStr),
          bumpDistance(bumpDist) {}

    Vec3 eval(const HitRecord& rec, const Vec3& wo, const Vec3& wi) const override {
        HitRecord pr = perturbNormal(rec);
        return baseMaterial->eval(pr, wo, wi);
    }

    BSDFSample sample(const HitRecord& rec, const Vec3& wo, std::mt19937& gen) const override {
        HitRecord pr = perturbNormal(rec);
        return baseMaterial->sample(pr, wo, gen);
    }

    float pdf(const HitRecord& rec, const Vec3& wo, const Vec3& wi) const override {
        HitRecord pr = perturbNormal(rec);
        return baseMaterial->pdf(pr, wo, wi);
    }

};

// ============================================================================
// SUBSURFACE SCATTERING (Fixed - scattering, not emissive)
// ============================================================================

class SubsurfaceMaterial : public Material {
    Vec3 albedo, scatterDistance;
    float scale;
public:
    SubsurfaceMaterial(const Vec3& a, const Vec3& scatter, float s = 1.0f)
        : albedo(a), scatterDistance(scatter), scale(s) {}
    
    Vec3 eval(const HitRecord& rec, const Vec3& wo, const Vec3& wi) const override {
        float cosTheta = std::abs(wi.dot(rec.normal));
        float distance = 1.0f / (cosTheta + 0.1f);
        Vec3 transmission(
            std::exp(-distance * scale / scatterDistance.x),
            std::exp(-distance * scale / scatterDistance.y),
            std::exp(-distance * scale / scatterDistance.z)
        );
        return albedo * transmission * cosTheta / M_PI;
    }
    
    BSDFSample sample(const HitRecord& rec, const Vec3& wo, std::mt19937& gen) const override {
        BSDFSample s;
        std::uniform_real_distribution<float> dist(0, 1);
        Vec3 localWi = Vec3::randomCosineDirection(gen);
        if (dist(gen) < 0.5f) localWi.z = -localWi.z;
        s.wi = rec.tangent * localWi.x + rec.bitangent * localWi.y + rec.normal * localWi.z;
        float r = -std::log(dist(gen) + 0.001f) * scale;
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
public:
    ConstantMedium(std::shared_ptr<Hittable> b, float density, const Vec3& a, float = 0)
        : boundary(b), negInvDensity(-1 / density), albedo(a) {}
    
    bool hit(const Ray& r, float tMin, float tMax, HitRecord& rec) const override {
        HitRecord rec1, rec2;
        if (!boundary->hit(r, -1e10f, 1e10f, rec1)) return false;
        if (!boundary->hit(r, rec1.t + 0.0001f, 1e10f, rec2)) return false;
        if (rec1.t < tMin) rec1.t = tMin;
        if (rec2.t > tMax) rec2.t = tMax;
        if (rec1.t >= rec2.t) return false;
        if (rec1.t < 0) rec1.t = 0;
        
        float rayLen = r.direction.length();
        float distInside = (rec2.t - rec1.t) * rayLen;
        std::mt19937 gen(std::random_device{}());
        std::uniform_real_distribution<float> dist(0, 1);
        float hitDist = negInvDensity * std::log(dist(gen) + 0.001f);
        if (hitDist > distInside) return false;
        
        rec.t = rec1.t + hitDist / rayLen;
        rec.point = r.at(rec.t);
        rec.normal = Vec3(1, 0, 0);
        rec.frontFace = true;
        rec.material = std::make_shared<Lambertian>(albedo);
        return true;
    }
    bool boundingBox(AABB& box) const override { return boundary->boundingBox(box); }
};

// ============================================================================
// TRANSFORMS
// ============================================================================

class Translate : public Hittable {
    std::shared_ptr<Hittable> object;
    Vec3 offset;
public:
    Translate(std::shared_ptr<Hittable> obj, const Vec3& d) : object(obj), offset(d) {}
    bool hit(const Ray& r, float tMin, float tMax, HitRecord& rec) const override {
        Ray moved(r.origin - offset, r.direction, r.time);
        if (!object->hit(moved, tMin, tMax, rec)) return false;
        rec.point += offset;
        rec.setFaceNormal(moved, rec.normal);
        return true;
    }
    bool boundingBox(AABB& box) const override {
        if (!object->boundingBox(box)) return false;
        box = AABB(box.min + offset, box.max + offset);
        return true;
    }
};

class Scale : public Hittable {
    std::shared_ptr<Hittable> object;
    Vec3 scale;
public:
    Scale(std::shared_ptr<Hittable> obj, const Vec3& s) : object(obj), scale(s) {}
    bool hit(const Ray& r, float tMin, float tMax, HitRecord& rec) const override {
        Vec3 o(r.origin.x/scale.x, r.origin.y/scale.y, r.origin.z/scale.z);
        Vec3 d(r.direction.x/scale.x, r.direction.y/scale.y, r.direction.z/scale.z);
        Ray scaled(o, d, r.time);
        if (!object->hit(scaled, tMin, tMax, rec)) return false;
        rec.point = Vec3(rec.point.x*scale.x, rec.point.y*scale.y, rec.point.z*scale.z);
        Vec3 n(rec.normal.x/scale.x, rec.normal.y/scale.y, rec.normal.z/scale.z);
        rec.setFaceNormal(r, n.normalized());
        return true;
    }
    bool boundingBox(AABB& box) const override {
        if (!object->boundingBox(box)) return false;
        box = AABB(Vec3(box.min.x*scale.x, box.min.y*scale.y, box.min.z*scale.z),
                   Vec3(box.max.x*scale.x, box.max.y*scale.y, box.max.z*scale.z));
        return true;
    }
};

class RotateY : public Hittable {
    std::shared_ptr<Hittable> object;
    float sinT, cosT;
public:
    RotateY(std::shared_ptr<Hittable> obj, float angle) : object(obj) {
        float rad = angle * M_PI / 180.0f;
        sinT = std::sin(rad); cosT = std::cos(rad);
    }
    bool hit(const Ray& r, float tMin, float tMax, HitRecord& rec) const override {
        Vec3 o(cosT*r.origin.x + sinT*r.origin.z, r.origin.y, -sinT*r.origin.x + cosT*r.origin.z);
        Vec3 d(cosT*r.direction.x + sinT*r.direction.z, r.direction.y, -sinT*r.direction.x + cosT*r.direction.z);
        Ray rot(o, d, r.time);
        if (!object->hit(rot, tMin, tMax, rec)) return false;
        Vec3 p = rec.point;
        rec.point = Vec3(cosT*p.x - sinT*p.z, p.y, sinT*p.x + cosT*p.z);
        Vec3 n = rec.normal;
        rec.setFaceNormal(r, Vec3(cosT*n.x - sinT*n.z, n.y, sinT*n.x + cosT*n.z));
        return true;
    }
    bool boundingBox(AABB& box) const override { return object->boundingBox(box); }
};

// ============================================================================
// MESH LOADING
// ============================================================================

class Mesh : public Hittable {
    std::shared_ptr<Material> material;
    std::vector<std::shared_ptr<Triangle>> triangles;
    std::shared_ptr<BVHAccel> bvh;
    AABB bbox;
public:
    Mesh(std::shared_ptr<Material> mat) : material(mat) {}
    
    bool loadOBJ(const std::string& filename) {
        std::ifstream file(filename);
        if (!file.is_open()) return false;
        std::vector<Vec3> positions;
        std::vector<Vec2> uvs;
        std::string line;
        while (std::getline(file, line)) {
            std::istringstream iss(line);
            std::string prefix;
            iss >> prefix;
            if (prefix == "v") {
                float x, y, z; iss >> x >> y >> z;
                positions.push_back(Vec3(x, y, z));
            } else if (prefix == "vt") {
                float u, v; iss >> u >> v;
                uvs.push_back(Vec2(u, v));
            } else if (prefix == "f") {
                std::vector<int> vi, ti;
                std::string vert;
                while (iss >> vert) {
                    size_t s1 = vert.find('/');
                    int v = std::stoi(vert.substr(0, s1)) - 1;
                    vi.push_back(v);
                    if (s1 != std::string::npos) {
                        size_t s2 = vert.find('/', s1 + 1);
                        std::string uvStr = vert.substr(s1 + 1, s2 - s1 - 1);
                        if (!uvStr.empty()) ti.push_back(std::stoi(uvStr) - 1);
                    }
                }
                for (size_t i = 1; i + 1 < vi.size(); ++i) {
                    Vec2 t0 = ti.size() > 0 ? uvs[ti[0]] : Vec2(0, 0);
                    Vec2 t1 = ti.size() > i ? uvs[ti[i]] : Vec2(1, 0);
                    Vec2 t2 = ti.size() > i + 1 ? uvs[ti[i + 1]] : Vec2(0, 1);
                    triangles.push_back(std::make_shared<Triangle>(
                        positions[vi[0]], positions[vi[i]], positions[vi[i + 1]], t0, t1, t2, material));
                }
            }
        }
        if (triangles.empty()) return false;
        std::vector<std::shared_ptr<Hittable>> hits;
        for (auto& t : triangles) hits.push_back(t);
        bvh = std::make_shared<BVHAccel>(hits);
        bvh->boundingBox(bbox);
        return true;
    }
    bool hit(const Ray& r, float tMin, float tMax, HitRecord& rec) const override {
        return bvh ? bvh->hit(r, tMin, tMax, rec) : false;
    }
    bool boundingBox(AABB& box) const override { box = bbox; return true; }
};

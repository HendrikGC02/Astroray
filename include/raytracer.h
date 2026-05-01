#pragma once

#include <cmath>
#include <vector>
#include <memory>
#include <random>
#include <limits>
#include <algorithm>
#include <atomic>
#include <functional>
#include <array>
#include <cstdint>
#include <cstddef>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <sstream>
#include <string>
#include <unordered_map>
#include "stb_image.h"
#include "astroray/gr_types.h"
#include "astroray/spectrum.h"

// Forward declaration needed by HitRecord
class Hittable;
class Integrator;

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

// ============================================================================
// CORE MATH TYPES
// ============================================================================

struct Vec3 {
    float x, y, z;

    Vec3() : x(0), y(0), z(0) {}
    Vec3(float v) : x(v), y(v), z(v) {}
    Vec3(float x, float y, float z) : x(x), y(y), z(z) {}

    Vec3 operator+(const Vec3& o) const { return Vec3(x+o.x, y+o.y, z+o.z); }
    Vec3 operator-(const Vec3& o) const { return Vec3(x-o.x, y-o.y, z-o.z); }
    Vec3 operator*(float s) const { return Vec3(x*s, y*s, z*s); }
    Vec3 operator*(const Vec3& o) const { return Vec3(x*o.x, y*o.y, z*o.z); }
    Vec3 operator/(float s) const { return Vec3(x/s, y/s, z/s); }
    Vec3 operator-() const { return Vec3(-x, -y, -z); }

    Vec3& operator+=(const Vec3& o) { x+=o.x; y+=o.y; z+=o.z; return *this; }
    Vec3& operator*=(float s) { x*=s; y*=s; z*=s; return *this; }
    Vec3& operator*=(const Vec3& o) { x*=o.x; y*=o.y; z*=o.z; return *this; }
    Vec3& operator/=(float s) { x/=s; y/=s; z/=s; return *this; }

    float dot(const Vec3& o) const { return x*o.x + y*o.y + z*o.z; }
    Vec3 cross(const Vec3& o) const { return Vec3(y*o.z - z*o.y, z*o.x - x*o.z, x*o.y - y*o.x); }

    float length2() const { return dot(*this); }
    float length() const { return std::sqrt(length2()); }
    Vec3 normalized() const { float len = length(); return len > 0 ? *this / len : Vec3(0); }

    float& operator[](int i) { return (&x)[i]; }
    const float& operator[](int i) const { return (&x)[i]; }
    float maxComponent() const { return std::max({x, y, z}); }
    bool operator!=(const Vec3& o) const { return x != o.x || y != o.y || z != o.z; }

    static Vec3 min(const Vec3& a, const Vec3& b) { return Vec3(std::min(a.x, b.x), std::min(a.y, b.y), std::min(a.z, b.z)); }
    static Vec3 max(const Vec3& a, const Vec3& b) { return Vec3(std::max(a.x, b.x), std::max(a.y, b.y), std::max(a.z, b.z)); }

    static Vec3 randomCosineDirection(std::mt19937& gen) {
        std::uniform_real_distribution<float> dist(0, 1);
        float r1 = dist(gen), r2 = dist(gen);
        float z = std::sqrt(1 - r2);
        float phi = 2 * M_PI * r1;
        return Vec3(std::cos(phi) * std::sqrt(r2), std::sin(phi) * std::sqrt(r2), z);
    }

    static Vec3 randomInUnitDisk(std::mt19937& gen) {
        std::uniform_real_distribution<float> dist(-1, 1);
        Vec3 p;
        do { p = Vec3(dist(gen), dist(gen), 0); } while (p.length2() >= 1);
        return p;
    }
};

inline Vec3 operator*(float s, const Vec3& v) { return v * s; }
inline float luminance(const Vec3& c) { return 0.2126f * c.x + 0.7152f * c.y + 0.0722f * c.z; }
inline float smoothstep(float edge0, float edge1, float x) {
    float t = (x - edge0) / (edge1 - edge0 + 1e-8f);
    t = std::clamp(t, 0.0f, 1.0f);
    return t * t * (3.0f - 2.0f * t);
}

inline void buildOrthonormalBasis(const Vec3& n, Vec3& u, Vec3& v) {
    u = (std::abs(n.x) > 0.9f) ? Vec3(0, 1, 0) : Vec3(1, 0, 0);
    u = (u - n * n.dot(u)).normalized();
    v = n.cross(u);
}

class IESProfile {
    std::vector<float> verticalAngles;
    std::vector<float> horizontalAngles;
    std::vector<float> candelaTable; // [h * verticalCount + v]
    int verticalCount = 0;
    int horizontalCount = 0;
    static constexpr float kDirectionEpsilon2 = 1e-12f;

    static bool parseFloat(const std::string& token, float& out) {
        char* end = nullptr;
        out = std::strtof(token.c_str(), &end);
        return end && *end == '\0';
    }

    static float lerp(float a, float b, float t) {
        return a + (b - a) * t;
    }

    static void findBracket(const std::vector<float>& values, float x, int& i0, int& i1, float& t) {
        if (values.empty()) {
            i0 = i1 = 0;
            t = 0.0f;
            return;
        }
        if (values.size() == 1 || x <= values.front()) {
            i0 = i1 = 0;
            t = 0.0f;
            return;
        }
        if (x >= values.back()) {
            i0 = i1 = static_cast<int>(values.size()) - 1;
            t = 0.0f;
            return;
        }
        auto it = std::upper_bound(values.begin(), values.end(), x);
        i1 = static_cast<int>(std::distance(values.begin(), it));
        i0 = std::max(0, i1 - 1);
        float denom = std::max(values[i1] - values[i0], 1e-6f);
        t = std::clamp((x - values[i0]) / denom, 0.0f, 1.0f);
    }

    float sampleVertical(int hIndex, float verticalDeg) const {
        int v0 = 0, v1 = 0;
        float vt = 0.0f;
        findBracket(verticalAngles, verticalDeg, v0, v1, vt);
        float a = candelaTable[hIndex * verticalCount + v0];
        float b = candelaTable[hIndex * verticalCount + v1];
        return lerp(a, b, vt);
    }

public:
    static std::shared_ptr<IESProfile> loadFromFile(const std::string& path) {
        if (path.empty()) return nullptr;
        std::ifstream file(path);
        if (!file) return nullptr;

        std::stringstream buffer;
        buffer << file.rdbuf();
        std::string text = buffer.str();
        for (char& ch : text) {
            if (ch == ',' || ch == ';') ch = ' ';
        }

        std::vector<std::string> tokens;
        {
            std::istringstream iss(text);
            std::string token;
            while (iss >> token) tokens.push_back(token);
        }
        if (tokens.empty()) return nullptr;

        size_t numericStart = 0;
        bool foundTilt = false;
        for (size_t i = 0; i < tokens.size(); ++i) {
            const std::string& tok = tokens[i];
            if (tok.rfind("TILT=", 0) == 0) {
                foundTilt = true;
                if (tok == "TILT=") numericStart = i + 2;
                else numericStart = i + 1;
                break;
            }
        }
        if (!foundTilt || numericStart >= tokens.size()) return nullptr;

        std::vector<float> nums;
        nums.reserve(tokens.size() - numericStart);
        for (size_t i = numericStart; i < tokens.size(); ++i) {
            float value = 0.0f;
            if (parseFloat(tokens[i], value)) nums.push_back(value);
        }
        if (nums.size() < 13) return nullptr;

        // LM-63 numeric header:
        // [2]=candela multiplier, [3]=vertical angle count, [4]=horizontal angle count
        const float candelaMultiplier = nums[2];
        const int vCount = std::max(0, static_cast<int>(std::lround(nums[3])));
        const int hCount = std::max(0, static_cast<int>(std::lround(nums[4])));
        if (vCount <= 0 || hCount <= 0) return nullptr;

        size_t offset = 13;
        size_t required = offset + static_cast<size_t>(vCount) + static_cast<size_t>(hCount)
                        + static_cast<size_t>(vCount) * static_cast<size_t>(hCount);
        if (nums.size() < required) return nullptr;

        auto profile = std::make_shared<IESProfile>();
        profile->verticalCount = vCount;
        profile->horizontalCount = hCount;
        profile->verticalAngles.assign(nums.begin() + static_cast<std::ptrdiff_t>(offset),
                                       nums.begin() + static_cast<std::ptrdiff_t>(offset + vCount));
        offset += static_cast<size_t>(vCount);
        profile->horizontalAngles.assign(nums.begin() + static_cast<std::ptrdiff_t>(offset),
                                         nums.begin() + static_cast<std::ptrdiff_t>(offset + hCount));
        offset += static_cast<size_t>(hCount);

        profile->candelaTable.resize(static_cast<size_t>(vCount) * static_cast<size_t>(hCount));
        float maxCandela = 0.0f;
        float scale = std::max(candelaMultiplier, 0.0f);
        for (size_t i = 0; i < profile->candelaTable.size(); ++i) {
            float c = nums[offset + i] * scale;
            profile->candelaTable[i] = c;
            maxCandela = std::max(maxCandela, c);
        }

        if (maxCandela > 0.0f) {
            for (float& c : profile->candelaTable) c /= maxCandela;
        } else {
            std::fill(profile->candelaTable.begin(), profile->candelaTable.end(), 1.0f);
        }
        return profile;
    }

    float sample(const Vec3& axis, const Vec3& directionFromLight) const {
        if (verticalCount <= 0 || horizontalCount <= 0 || candelaTable.empty()) return 1.0f;

        Vec3 nAxis = axis.length2() > kDirectionEpsilon2 ? axis.normalized() : Vec3(0, -1, 0);
        Vec3 dir = directionFromLight.normalized();
        if (dir.length2() <= kDirectionEpsilon2) return 1.0f;

        float cosVertical = std::clamp(nAxis.dot(dir), -1.0f, 1.0f);
        float verticalDeg = std::acos(cosVertical) * (180.0f / static_cast<float>(M_PI));

        float horizontalDeg = 0.0f;
        Vec3 tangent, bitangent;
        buildOrthonormalBasis(nAxis, tangent, bitangent);
        Vec3 planar = dir - nAxis * cosVertical;
        if (planar.length2() > kDirectionEpsilon2) {
            planar = planar.normalized();
            float x = planar.dot(tangent);
            float y = planar.dot(bitangent);
            horizontalDeg = std::atan2(y, x) * (180.0f / static_cast<float>(M_PI));
            if (horizontalDeg < 0.0f) horizontalDeg += 360.0f;
        }

        if (horizontalCount == 1) return sampleVertical(0, verticalDeg);

        float h = horizontalDeg;
        const float hStart = horizontalAngles.front();
        const float hEnd = horizontalAngles.back();
        const float hSpan = hEnd - hStart;
        if (hSpan >= 359.0f) {
            h = std::fmod(h, 360.0f);
            if (h < 0.0f) h += 360.0f;
            if (h < hStart) h += 360.0f;
        } else {
            h = std::clamp(h, hStart, hEnd);
        }

        int h0 = 0, h1 = 0;
        float ht = 0.0f;
        findBracket(horizontalAngles, h, h0, h1, ht);
        float a = sampleVertical(h0, verticalDeg);
        float b = sampleVertical(h1, verticalDeg);
        return std::max(0.0f, lerp(a, b, ht));
    }
};

struct GGXEnergyCompensationLUT {
    static constexpr int RES = 32;
    std::array<float, RES * RES> E{};
    std::array<float, RES> Eavg{};

    static float radicalInverseVdC(uint32_t bits) {
        bits = (bits << 16u) | (bits >> 16u);
        bits = ((bits & 0x55555555u) << 1u) | ((bits & 0xAAAAAAAAu) >> 1u);
        bits = ((bits & 0x33333333u) << 2u) | ((bits & 0xCCCCCCCCu) >> 2u);
        bits = ((bits & 0x0F0F0F0Fu) << 4u) | ((bits & 0xF0F0F0F0u) >> 4u);
        bits = ((bits & 0x00FF00FFu) << 8u) | ((bits & 0xFF00FF00u) >> 8u);
        return float(bits) * 2.3283064365386963e-10f;
    }

    static float singleScatterEval(float NdotV, float NdotL, float NdotH, float roughness) {
        if (NdotL <= 0.0f || NdotV <= 0.0f) return 0.0f;
        const float a = roughness * roughness;
        const float a2 = a * a;
        const float denom = NdotH * NdotH * (a2 - 1.0f) + 1.0f;
        const float D = a2 / (M_PI * denom * denom + 0.001f);
        const float k = (roughness + 1.0f) * (roughness + 1.0f) / 8.0f;
        const float G = (NdotL / (NdotL * (1.0f - k) + k)) * (NdotV / (NdotV * (1.0f - k) + k));
        return D * G / (4.0f * NdotV + 0.001f);
    }

    GGXEnergyCompensationLUT() {
        constexpr int samples = 256;
        constexpr float invHemispherePdf = 2.0f * M_PI;

        for (int r = 0; r < RES; ++r) {
            float roughness = std::max(0.001f, (r + 0.5f) / float(RES));
            for (int m = 0; m < RES; ++m) {
                float mu = (m + 0.5f) / float(RES);
                float sinTheta = std::sqrt(std::max(0.0f, 1.0f - mu * mu));
                Vec3 wo(sinTheta, 0.0f, mu);
                float sum = 0.0f;

                for (int i = 0; i < samples; ++i) {
                    float u1 = (i + 0.5f) / float(samples);
                    float u2 = radicalInverseVdC(uint32_t(i));
                    float z = u1;
                    float phi = 2.0f * M_PI * u2;
                    float xy = std::sqrt(std::max(0.0f, 1.0f - z * z));
                    Vec3 wi(std::cos(phi) * xy, std::sin(phi) * xy, z);
                    Vec3 h = (wo + wi).normalized();
                    float NdotH = std::max(h.z, 0.001f);
                    float f = singleScatterEval(mu, z, NdotH, roughness);
                    sum += f * invHemispherePdf;
                }

                E[r * RES + m] = std::clamp(sum / float(samples), 0.0f, 1.0f);
            }

            float weightedSum = 0.0f;
            float weightNorm = 0.0f;
            for (int m = 0; m < RES; ++m) {
                float mu = (m + 0.5f) / float(RES);
                float w = 2.0f * mu;
                weightedSum += E[r * RES + m] * w;
                weightNorm += w;
            }
            Eavg[r] = std::clamp(weightedSum / std::max(weightNorm, 1e-6f), 0.0f, 1.0f);
        }
    }

    float lookupE(float mu, float roughness) const {
        float x = std::clamp(mu, 0.0f, 1.0f) * (RES - 1);
        float y = std::clamp(roughness, 0.0f, 1.0f) * (RES - 1);
        int x0 = int(x), y0 = int(y);
        int x1 = std::min(x0 + 1, RES - 1), y1 = std::min(y0 + 1, RES - 1);
        float tx = x - x0, ty = y - y0;
        float e00 = E[y0 * RES + x0], e10 = E[y0 * RES + x1];
        float e01 = E[y1 * RES + x0], e11 = E[y1 * RES + x1];
        float ex0 = e00 * (1 - tx) + e10 * tx;
        float ex1 = e01 * (1 - tx) + e11 * tx;
        return ex0 * (1 - ty) + ex1 * ty;
    }

    float lookupEavg(float roughness) const {
        float y = std::clamp(roughness, 0.0f, 1.0f) * (RES - 1);
        int y0 = int(y), y1 = std::min(y0 + 1, RES - 1);
        float ty = y - y0;
        return Eavg[y0] * (1 - ty) + Eavg[y1] * ty;
    }
};

inline const GGXEnergyCompensationLUT& ggxEnergyCompensationLUT() {
    static const GGXEnergyCompensationLUT lut;
    return lut;
}

inline float ggxMultiScatterCompensation(float NdotV, float NdotL, float roughness) {
    const auto& lut = ggxEnergyCompensationLUT();
    float Ewo = lut.lookupE(NdotV, roughness);
    float Ewi = lut.lookupE(NdotL, roughness);
    float Eavg = lut.lookupEavg(roughness);
    float denom = M_PI * std::max(1.0f - Eavg, 1e-4f);
    return std::max((1.0f - Ewo) * (1.0f - Ewi) / denom, 0.0f);
}

struct Vec2 {
    float u, v;
    Vec2(float u = 0, float v = 0) : u(u), v(v) {}
    Vec2 operator+(const Vec2& o) const { return Vec2(u + o.u, v + o.v); }
    Vec2 operator*(float s) const { return Vec2(u * s, v * s); }
};

// ============================================================================
// RAY AND INTERSECTION
// ============================================================================

struct Ray {
    Vec3 origin, direction;
    float time;
    float screenU = 0.5f, screenV = 0.5f;  // [0,1] camera-window coordinates
    bool hasCameraFrame = false;
    Vec3 cameraOrigin, cameraU, cameraV, cameraW;
    Ray() : time(0) {}
    Ray(const Vec3& o, const Vec3& d, float t = 0, float su = 0.5f, float sv = 0.5f)
        : origin(o), direction(d.normalized()), time(t), screenU(su), screenV(sv) {}
    Vec3 at(float t) const { return origin + direction * t; }
};

class Material;

struct HitRecord {
    Vec3 point, normal, tangent, bitangent;
    Vec3 objectPoint, incomingDirection;
    Vec3 cameraOrigin, cameraU, cameraV, cameraW;
    float t;
    bool frontFace;
    bool hasCameraFrame = false;
    Vec2 uv;
    Vec2 windowUV;
    std::shared_ptr<Material> material;
    bool isDelta;
    const Hittable* hitObject = nullptr;  // set by hit() for GR dispatch

    HitRecord() : t(std::numeric_limits<float>::max()), frontFace(true), isDelta(false), hitObject(nullptr) {}

    void setRayContext(const Ray& r) {
        incomingDirection = r.direction;
        windowUV = Vec2(r.screenU, r.screenV);
        hasCameraFrame = r.hasCameraFrame;
        cameraOrigin = r.cameraOrigin;
        cameraU = r.cameraU;
        cameraV = r.cameraV;
        cameraW = r.cameraW;
    }

    void setFaceNormal(const Ray& r, const Vec3& outwardNormal) {
        setRayContext(r);
        frontFace = r.direction.dot(outwardNormal) < 0;
        normal = frontFace ? outwardNormal : -outwardNormal;
        buildOrthonormalBasis(normal, tangent, bitangent);
    }
};

// ============================================================================
// AABB
// ============================================================================

class AABB {
public:
    Vec3 min, max;

    AABB() : min(Vec3(std::numeric_limits<float>::max())), max(Vec3(std::numeric_limits<float>::lowest())) {}
    AABB(const Vec3& a, const Vec3& b) : min(a), max(b) {}

    bool hit(const Ray& r, float tMin, float tMax) const {
        for (int a = 0; a < 3; a++) {
            float invD = 1.0f / r.direction[a];
            float t0 = (min[a] - r.origin[a]) * invD;
            float t1 = (max[a] - r.origin[a]) * invD;
            if (invD < 0) std::swap(t0, t1);
            tMin = t0 > tMin ? t0 : tMin;
            tMax = t1 < tMax ? t1 : tMax;
            if (tMax <= tMin) return false;
        }
        return true;
    }

    AABB merge(const AABB& box) const { return AABB(Vec3::min(min, box.min), Vec3::max(max, box.max)); }
    float area() const { Vec3 d = max - min; return 2 * (d.x * d.y + d.y * d.z + d.z * d.x); }
    int maxExtent() const { Vec3 d = max - min; return (d.x > d.y && d.x > d.z) ? 0 : (d.y > d.z ? 1 : 2); }
    Vec3 centroid() const { return (min + max) * 0.5f; }
};

// ============================================================================
// SAMPLING STRUCTURES
// ============================================================================

struct LightSample { Vec3 position, normal, emission; float pdf, distance; };
struct BSDFSample { Vec3 wi, f; float pdf; bool isDelta; };

// ============================================================================
// MATERIALS - ALL FIXES APPLIED
// ============================================================================

class Material {
public:
    virtual ~Material() = default;
    virtual BSDFSample sample(const HitRecord& rec, const Vec3& wo, std::mt19937& gen) const { return BSDFSample{Vec3(0,1,0), Vec3(0), 0, false}; }
    virtual float pdf(const HitRecord& rec, const Vec3& wo, const Vec3& wi) const { return 0; }
    virtual Vec3 emitted(const HitRecord& rec) const { return Vec3(0); }
    virtual Vec3 getEmission() const { return Vec3(0); }
    virtual bool isEmissive() const { return false; }
    virtual bool isTransmissive() const { return false; }
    virtual bool isGlossy() const { return false; }
    virtual Vec3 getAlbedo() const { return Vec3(0.5f); }

    virtual astroray::SampledSpectrum evalSpectral(
            const HitRecord& rec, const Vec3& wo, const Vec3& wi,
            const astroray::SampledWavelengths& lambdas) const = 0;
    virtual astroray::SampledSpectrum emittedSpectral(
            const HitRecord& rec,
            const astroray::SampledWavelengths& lambdas) const {
        return astroray::SampledSpectrum(0.0f);
    }
};

class Lambertian : public Material {
    Vec3 albedo;
    astroray::RGBAlbedoSpectrum albedoSpec_;
public:
    Lambertian(const Vec3& a) : albedo(a), albedoSpec_({a.x, a.y, a.z}) {}
    Vec3 getAlbedo() const { return albedo; }

    BSDFSample sample(const HitRecord& rec, const Vec3& wo, std::mt19937& gen) const override {
        BSDFSample s;
        Vec3 localWi = Vec3::randomCosineDirection(gen);
        s.wi = rec.tangent * localWi.x + rec.bitangent * localWi.y + rec.normal * localWi.z;
        s.f = albedo / M_PI * s.wi.dot(rec.normal);
        s.pdf = s.wi.dot(rec.normal) / M_PI;
        s.isDelta = false;
        return s;
    }

    float pdf(const HitRecord& rec, const Vec3& wo, const Vec3& wi) const override {
        float cosTheta = wi.dot(rec.normal);
        return cosTheta > 0 ? cosTheta / M_PI : 0;
    }

    astroray::SampledSpectrum evalSpectral(
            const HitRecord& rec, const Vec3& wo, const Vec3& wi,
            const astroray::SampledWavelengths& lambdas) const override {
        float cosTheta = wi.dot(rec.normal);
        if (cosTheta <= 0.0f) return astroray::SampledSpectrum(0.0f);
        return albedoSpec_.sample(lambdas) * (cosTheta / float(M_PI));
    }
};

// ============================================================================
// GEOMETRY
// ============================================================================

class Hittable {
    int objectPassIndex = 0;
    int materialPassIndex = 0;
public:
    // Result type used by GR objects (BlackHole). Defined here so that
    // pathTraceSpectral() can use it without needing a full BlackHole definition.
    struct GRResult {
        Vec3 color;            // accumulated spectral emission (linear RGB)
        Vec3 exitDirection;    // world-space exit direction
        bool captured;         // absorbed by horizon
        bool hasEmission;      // disk was hit
    };

    struct GRSpectralResult {
        astroray::SampledSpectrum emission;  // disk emission at carried wavelengths
        Vec3 exitDirection;                  // world-space exit direction
        bool captured;                       // absorbed by horizon
        bool hasEmission;                    // disk was hit
    };

    virtual ~Hittable() = default;
    virtual bool hit(const Ray& r, float tMin, float tMax, HitRecord& rec) const = 0;
    virtual bool boundingBox(AABB& box) const = 0;
    virtual float pdfValue(const Vec3& origin, const Vec3& direction) const { return 0; }
    virtual Vec3 random(const Vec3& origin, std::mt19937& gen) const { return Vec3(0, 1, 0); }
    virtual bool isLight() const { return false; }
    virtual bool isInfiniteLight() const { return false; }
    virtual Vec3 emittedRadiance() const { return Vec3(0); }
    virtual float directionFalloff(const Vec3& /*directionFromLight*/) const { return 1.0f; }
    virtual Vec3 emittedRadiance(const Vec3& /*lightNormal*/, const Vec3& /*toPointDir*/) const { return emittedRadiance(); }
    // GR dispatch â€” BlackHole overrides both
    virtual bool isGRObject() const { return false; }
    virtual GRResult traceGR(const Ray& /*r*/, std::mt19937& /*gen*/) const {
        return {Vec3(0), Vec3(0, 0, 1), true, false};
    }
    virtual GRSpectralResult traceGRSpectral(
            const Ray& r,
            const astroray::SampledWavelengths& lambdas,
            std::mt19937& gen) const {
        GRResult rgb = traceGR(r, gen);
        astroray::SampledSpectrum emission(0.0f);
        if (rgb.hasEmission) {
            emission = astroray::RGBIlluminantSpectrum(
                {rgb.color.x, rgb.color.y, rgb.color.z}).sample(lambdas);
        }
        return {emission, rgb.exitDirection, rgb.captured, rgb.hasEmission};
    }
    void setObjectPassIndex(int value) { objectPassIndex = std::max(0, value); }
    void setMaterialPassIndex(int value) { materialPassIndex = std::max(0, value); }
    int getObjectPassIndex() const { return objectPassIndex; }
    int getMaterialPassIndex() const { return materialPassIndex; }
};

// Sphere class body moved to include/astroray/shapes.h (pkg04).
class Sphere;

class DistantLight : public Hittable {
    Vec3 direction;
    Vec3 toLightDir;
    float angularDiameter;
    float cosThetaMax;
    std::shared_ptr<Material> material;
    static constexpr float kDistantT = 1e8f;

    void updateCone() {
        float halfAngle = std::max(0.0f, angularDiameter * 0.5f);
        cosThetaMax = (halfAngle <= 0.0f) ? (1.0f - 1e-3f) : std::cos(halfAngle);
    }

public:
    DistantLight(const Vec3& dir, float angle, std::shared_ptr<Material> m)
        : direction(dir.normalized()),
          toLightDir((-dir).normalized()),
          angularDiameter(std::max(0.0f, angle)),
          cosThetaMax(1.0f),
          material(m) {
        updateCone();
    }

    bool hit(const Ray& r, float tMin, float tMax, HitRecord& rec) const override {
        Vec3 rayDir = r.direction.normalized();
        if (rayDir.dot(toLightDir) < cosThetaMax) return false;
        const float t = kDistantT;
        if (t < tMin || t > tMax) return false;
        rec.t = t;
        rec.point = r.at(t);
        rec.objectPoint = rec.point;
        rec.setFaceNormal(r, direction);
        rec.material = material;
        rec.hitObject = this;
        rec.uv = Vec2(0.0f, 0.0f);
        return true;
    }

    bool boundingBox(AABB& box) const override {
        constexpr float kWorld = 1e6f;
        box = AABB(Vec3(-kWorld), Vec3(kWorld));
        return true;
    }

    float pdfValue(const Vec3& /*origin*/, const Vec3& sampleDir) const override {
        Vec3 d = sampleDir.normalized();
        float cosTheta = d.dot(toLightDir);
        if (angularDiameter <= 0.0f)
            return cosTheta > (1.0f - 1e-3f) ? 1.0f : 0.0f;
        if (cosTheta < cosThetaMax) return 0.0f;
        // Uniform cone sampling: PDF = 1 / solidAngle = 1 / (2Ï€(1 âˆ’ cosÎ¸_max))
        float solidAngle = 2.0f * float(M_PI) * (1.0f - cosThetaMax);
        return solidAngle > 1e-10f ? 1.0f / solidAngle : 1.0f;
    }

    Vec3 random(const Vec3& /*origin*/, std::mt19937& gen) const override {
        if (angularDiameter <= 0.0f) return toLightDir;
        static thread_local std::uniform_real_distribution<float> dist(0.0f, 1.0f);
        float z = 1.0f + dist(gen) * (cosThetaMax - 1.0f);
        float phi = 2.0f * M_PI * dist(gen);
        float sinTheta = std::sqrt(std::max(0.0f, 1.0f - z * z));
        Vec3 u, v;
        buildOrthonormalBasis(toLightDir, u, v);
        return (u * std::cos(phi) * sinTheta + v * std::sin(phi) * sinTheta + toLightDir * z).normalized();
    }

    bool isLight() const override { return true; }
    bool isInfiniteLight() const override { return true; }
    Vec3 emittedRadiance() const override {
        HitRecord rec;
        rec.frontFace = true;
        return material ? material->emitted(rec) : Vec3(0);
    }
    // Scale emitted radiance by 1/solidAngle so that contribution = (I/Î©) / (1/Î©) = I
    // regardless of the cone angular size.  Both the NEE path and the BSDF MIS path
    // multiply material emission by directionFalloff before dividing by pdf,
    // so the irradiance seen by the surface stays constant as the sun disk size changes.
    float directionFalloff(const Vec3& /*dir*/) const override {
        if (angularDiameter <= 0.0f) return 1.0f;
        float solidAngle = 2.0f * float(M_PI) * (1.0f - cosThetaMax);
        return solidAngle > 1e-10f ? 1.0f / solidAngle : 1.0f;
    }
};

class SpotLightSphere : public Hittable {
    Vec3 center;
    float radius;
    Vec3 axis;
    float outerAngle;
    float innerAngle;
    std::shared_ptr<IESProfile> iesProfile;
    std::shared_ptr<Material> material;
    bool emissive;
public:
    SpotLightSphere(const Vec3& c, float r, std::shared_ptr<Material> m, const Vec3& direction,
                    float spotAngle, float spotSmooth, std::shared_ptr<IESProfile> ies = nullptr)
        : center(c), radius(std::max(r, 0.001f)),
          axis(direction.length2() > 1e-12f ? direction.normalized() : Vec3(0, -1, 0)),
          outerAngle(std::max(spotAngle * 0.5f, 1e-4f)),
          // Blender/Cycles convention: spot_smooth=0 -> hard edge (inner=outer),
          // spot_smooth=1 -> smooth falloff from axis to outer cone (inner=0).
          innerAngle(std::max((1.0f - std::clamp(spotSmooth, 0.0f, 1.0f)) * spotAngle * 0.5f, 0.0f)),
          iesProfile(std::move(ies)),
          material(m), emissive(m->isEmissive()) {}

    bool hit(const Ray& r, float tMin, float tMax, HitRecord& rec) const override {
        Vec3 oc = r.origin - center;
        float a = r.direction.length2(), half_b = oc.dot(r.direction);
        float c = oc.length2() - radius * radius;
        float discriminant = half_b * half_b - a * c;
        if (discriminant < 0) return false;
        float sqrtd = std::sqrt(discriminant);
        float root = (-half_b - sqrtd) / a;
        if (root < tMin || root > tMax) { root = (-half_b + sqrtd) / a; if (root < tMin || root > tMax) return false; }
        rec.t = root;
        rec.point = r.at(root);
        rec.objectPoint = rec.point;
        Vec3 outwardNormal = (rec.point - center) / radius;
        rec.setFaceNormal(r, outwardNormal);
        rec.material = material;
        rec.hitObject = this;
        float theta = std::acos(-outwardNormal.y), phi = std::atan2(-outwardNormal.z, outwardNormal.x) + M_PI;
        rec.uv = Vec2(phi / (2 * M_PI), theta / M_PI);
        return true;
    }

    bool boundingBox(AABB& box) const override { box = AABB(center - Vec3(radius), center + Vec3(radius)); return true; }

    float pdfValue(const Vec3& origin, const Vec3& direction) const override {
        HitRecord rec;
        if (!hit(Ray(origin, direction), 0.001f, std::numeric_limits<float>::max(), rec)) return 0;
        float cosThetaMax = std::sqrt(1 - radius * radius / (center - origin).length2());
        return 1 / (2 * M_PI * (1 - cosThetaMax));
    }

    Vec3 random(const Vec3& origin, std::mt19937& gen) const override {
        Vec3 dir = (center - origin).normalized();
        float distSq = (center - origin).length2();
        float cosThetaMax = std::sqrt(1 - radius * radius / distSq);
        std::uniform_real_distribution<float> dist(0, 1);
        float z = 1 + dist(gen) * (cosThetaMax - 1);
        float phi = 2 * M_PI * dist(gen);
        Vec3 u, v;
        buildOrthonormalBasis(dir, u, v);
        return (u * std::cos(phi) * std::sqrt(1 - z*z) + v * std::sin(phi) * std::sqrt(1 - z*z) + dir * z).normalized();
    }

    bool isLight() const override { return emissive; }
    Vec3 emittedRadiance() const override {
        return material->getEmission();
    }
    float directionFalloff(const Vec3& directionFromLight) const override {
        float cosAng = std::clamp(axis.dot(directionFromLight.normalized()), -1.0f, 1.0f);
        float angle = std::acos(cosAng);
        if (angle >= outerAngle) return 0.0f;
        float spot = (innerAngle >= outerAngle - 1e-6f) ? 1.0f : smoothstep(outerAngle, innerAngle, angle);
        if (!iesProfile) return spot;
        return spot * iesProfile->sample(axis, directionFromLight);
    }
};

class AreaLightShape : public Hittable {
public:
    enum class Shape { Rectangle, Disk, Ellipse };

private:
    Vec3 center;
    Vec3 axisU;
    Vec3 axisV;
    Vec3 normal;
    float halfU;
    float halfV;
    Shape shape;
    float spread;
    std::shared_ptr<Material> material;
    bool emissive;

    float area() const {
        if (shape == Shape::Rectangle) return 4.0f * halfU * halfV;
        if (shape == Shape::Disk) return M_PI * halfU * halfU;
        return M_PI * halfU * halfV;
    }

    bool pointInside(const Vec3& p) const {
        Vec3 d = p - center;
        float u = d.dot(axisU);
        float v = d.dot(axisV);
        if (shape == Shape::Rectangle) {
            return std::abs(u) <= halfU && std::abs(v) <= halfV;
        }
        if (shape == Shape::Disk) {
            float r2 = u * u + v * v;
            return r2 <= halfU * halfU;
        }
        float su = u / std::max(halfU, 1e-6f);
        float sv = v / std::max(halfV, 1e-6f);
        return su * su + sv * sv <= 1.0f;
    }

    Vec3 samplePoint(std::mt19937& gen) const {
        std::uniform_real_distribution<float> dist(0, 1);
        if (shape == Shape::Rectangle) {
            float su = 2.0f * dist(gen) - 1.0f;
            float sv = 2.0f * dist(gen) - 1.0f;
            return center + axisU * (halfU * su) + axisV * (halfV * sv);
        }
        float r = std::sqrt(dist(gen));
        float phi = 2.0f * M_PI * dist(gen);
        float x = r * std::cos(phi);
        float y = r * std::sin(phi);
        if (shape == Shape::Disk) {
            return center + axisU * (halfU * x) + axisV * (halfU * y);
        }
        return center + axisU * (halfU * x) + axisV * (halfV * y);
    }

public:
    AreaLightShape(const Vec3& c, const Vec3& u, const Vec3& v,
                   float fullSizeU, float fullSizeV, Shape s, float spreadValue,
                   std::shared_ptr<Material> m)
        : center(c), halfU(std::max(0.001f, fullSizeU * 0.5f)),
          halfV(std::max(0.001f, fullSizeV * 0.5f)), shape(s),
          spread(std::clamp(spreadValue, 0.0f, 1.0f)), material(std::move(m)),
          emissive(material->isEmissive()) {
        axisU = u.normalized();
        Vec3 vProj = v - axisU * axisU.dot(v);
        if (vProj.length2() < 1e-8f) {
            Vec3 temp;
            buildOrthonormalBasis(axisU, axisV, temp);
            normal = axisU.cross(axisV).normalized();
        } else {
            axisV = vProj.normalized();
            normal = axisU.cross(axisV).normalized();
        }
    }

    bool hit(const Ray& r, float tMin, float tMax, HitRecord& rec) const override {
        float denom = normal.dot(r.direction);
        if (std::abs(denom) < 1e-6f) return false;
        float t = (center - r.origin).dot(normal) / denom;
        if (t < tMin || t > tMax) return false;
        Vec3 p = r.at(t);
        if (!pointInside(p)) return false;
        rec.t = t;
        rec.point = p;
        rec.objectPoint = rec.point;
        rec.setFaceNormal(r, normal);
        rec.material = material;
        Vec3 d = p - center;
        float u = d.dot(axisU);
        float v = d.dot(axisV);
        rec.uv = Vec2(0.5f + 0.5f * (u / std::max(halfU, 1e-6f)),
                      0.5f + 0.5f * (v / std::max(halfV, 1e-6f)));
        return true;
    }

    bool boundingBox(AABB& box) const override {
        Vec3 ext = Vec3(std::abs(axisU.x), std::abs(axisU.y), std::abs(axisU.z)) * halfU +
                   Vec3(std::abs(axisV.x), std::abs(axisV.y), std::abs(axisV.z)) * halfV +
                   Vec3(std::abs(normal.x), std::abs(normal.y), std::abs(normal.z)) * 0.0001f;
        box = AABB(center - ext, center + ext);
        return true;
    }

    float pdfValue(const Vec3& origin, const Vec3& direction) const override {
        HitRecord rec;
        if (!hit(Ray(origin, direction), 0.001f, std::numeric_limits<float>::max(), rec)) return 0;
        return rec.t * rec.t / (std::abs(direction.dot(rec.normal)) * area() + 0.001f);
    }

    Vec3 random(const Vec3& origin, std::mt19937& gen) const override {
        return (samplePoint(gen) - origin).normalized();
    }

    bool isLight() const override { return emissive; }

    Vec3 emittedRadiance() const override {
        return material->getEmission();
    }

    Vec3 emittedRadiance(const Vec3& lightNormal, const Vec3& toPointDir) const override {
        Vec3 base = emittedRadiance();
        if (base != Vec3(0)) {
            static constexpr float MIN_CONE_ANGLE_RADIANS = float(M_PI) / 180.0f;
            float coneAngle = std::max(spread * 0.5f * float(M_PI), MIN_CONE_ANGLE_RADIANS);
            float cosLimit = std::cos(coneAngle);
            float cosTheta = lightNormal.normalized().dot(toPointDir.normalized());
            return cosTheta >= cosLimit ? base : Vec3(0);
        }
        return base;
    }
};

// Triangle class body moved to include/astroray/shapes.h (pkg04).
class Triangle;

// ============================================================================
// BVH WITH SAH
// ============================================================================

struct BVHPrimitiveInfo {
    size_t primitiveIndex;
    Vec3 centroid;
    AABB bounds;
    BVHPrimitiveInfo(size_t idx, const AABB& b) : primitiveIndex(idx), bounds(b), centroid(b.centroid()) {}
};

struct LinearBVHNode {
    AABB bounds;
    union { int primitivesOffset; int secondChildOffset; };
    uint16_t nPrimitives;
    uint8_t axis;
    uint8_t pad[1];
};

class BVHAccel : public Hittable {
    std::vector<std::shared_ptr<Hittable>> primitives;
    std::vector<LinearBVHNode> nodes;

    struct BVHBuildNode {
        AABB bounds;
        BVHBuildNode* children[2] = {nullptr, nullptr};
        int splitAxis, firstPrimOffset, nPrimitives;
    };

    BVHBuildNode* build(std::vector<BVHPrimitiveInfo>& info, int start, int end, size_t* total, std::vector<std::shared_ptr<Hittable>>& ord) {
        BVHBuildNode* node = new BVHBuildNode;
        (*total)++;
        AABB bounds;
        for (int i = start; i < end; ++i) bounds = bounds.merge(info[i].bounds);
        int n = end - start;
        if (n == 1) {
            node->firstPrimOffset = ord.size(); node->nPrimitives = n; node->bounds = bounds;
            for (int i = start; i < end; ++i) ord.push_back(primitives[info[i].primitiveIndex]);
            return node;
        }
        AABB cb;
        for (int i = start; i < end; ++i) cb = cb.merge(AABB(info[i].centroid, info[i].centroid));
        int dim = cb.maxExtent(), mid = (start + end) / 2;
        if (cb.max[dim] == cb.min[dim]) {
            node->firstPrimOffset = ord.size(); node->nPrimitives = n; node->bounds = bounds;
            for (int i = start; i < end; ++i) ord.push_back(primitives[info[i].primitiveIndex]);
            return node;
        }
        if (n <= 4) {
            std::nth_element(&info[start], &info[mid], &info[end-1]+1, [dim](auto& a, auto& b){ return a.centroid[dim] < b.centroid[dim]; });
        } else {
            const int NB = 12;
            struct Bucket { int count = 0; AABB bounds; } buckets[NB];
            for (int i = start; i < end; ++i) {
                int b = NB * ((info[i].centroid[dim] - cb.min[dim]) / (cb.max[dim] - cb.min[dim]));
                if (b == NB) b = NB - 1;
                buckets[b].count++; buckets[b].bounds = buckets[b].bounds.merge(info[i].bounds);
            }
            float minCost = std::numeric_limits<float>::max(); int minB = 0;
            for (int i = 0; i < NB-1; ++i) {
                AABB b0, b1; int c0 = 0, c1 = 0;
                for (int j = 0; j <= i; ++j) { b0 = b0.merge(buckets[j].bounds); c0 += buckets[j].count; }
                for (int j = i+1; j < NB; ++j) { b1 = b1.merge(buckets[j].bounds); c1 += buckets[j].count; }
                float cost = 0.125f + (c0 * b0.area() + c1 * b1.area()) / bounds.area();
                if (cost < minCost) { minCost = cost; minB = i; }
            }
            if (n > 4 && minCost < n) {
                auto pmid = std::partition(&info[start], &info[end-1]+1, [=](auto& pi) {
                    int b = NB * ((pi.centroid[dim] - cb.min[dim]) / (cb.max[dim] - cb.min[dim]));
                    if (b == NB) b = NB - 1;
                    return b <= minB;
                });
                mid = pmid - &info[0];
            }
        }
        node->splitAxis = dim; node->nPrimitives = 0; node->bounds = bounds;
        node->children[0] = build(info, start, mid, total, ord);
        node->children[1] = build(info, mid, end, total, ord);
        return node;
    }

    int flatten(BVHBuildNode* node, int* off) {
        LinearBVHNode& ln = nodes[*off]; ln.bounds = node->bounds; int my = (*off)++;
        if (node->nPrimitives > 0) { ln.primitivesOffset = node->firstPrimOffset; ln.nPrimitives = node->nPrimitives; }
        else { ln.axis = node->splitAxis; ln.nPrimitives = 0; flatten(node->children[0], off); ln.secondChildOffset = flatten(node->children[1], off); }
        delete node;
        return my;
    }

public:
    BVHAccel(const std::vector<std::shared_ptr<Hittable>>& p) : primitives(p) {
        if (primitives.empty()) return;
        std::vector<BVHPrimitiveInfo> info;
        for (size_t i = 0; i < primitives.size(); ++i) { AABB b; primitives[i]->boundingBox(b); info.push_back(BVHPrimitiveInfo(i, b)); }
        size_t total = 0;
        std::vector<std::shared_ptr<Hittable>> ord;
        BVHBuildNode* root = build(info, 0, primitives.size(), &total, ord);
        primitives.swap(ord);
        nodes.resize(total);
        int off = 0;
        flatten(root, &off);
    }

    bool hit(const Ray& r, float tMin, float tMax, HitRecord& rec) const override {
        if (nodes.empty()) return false;
        bool h = false;
        Vec3 invDir(1/r.direction.x, 1/r.direction.y, 1/r.direction.z);
        int dirIsNeg[3] = {invDir.x < 0, invDir.y < 0, invDir.z < 0};
        int toVisit = 0, curr = 0, stack[64];
        while (true) {
            const LinearBVHNode& n = nodes[curr];
            if (n.bounds.hit(r, tMin, tMax)) {
                if (n.nPrimitives > 0) {
                    for (int i = 0; i < n.nPrimitives; ++i) if (primitives[n.primitivesOffset + i]->hit(r, tMin, tMax, rec)) { h = true; tMax = rec.t; }
                    if (toVisit == 0) break;
                    curr = stack[--toVisit];
                } else {
                    if (dirIsNeg[n.axis]) { stack[toVisit++] = curr + 1; curr = n.secondChildOffset; }
                    else { stack[toVisit++] = n.secondChildOffset; curr = curr + 1; }
                }
            } else {
                if (toVisit == 0) break;
                curr = stack[--toVisit];
            }
        }
        return h;
    }

    bool boundingBox(AABB& box) const override { if (!nodes.empty()) box = nodes[0].bounds; return !nodes.empty(); }

    // Accessors for scene_upload.cu â€” read the flat BVH and ordered primitive list
    const std::vector<LinearBVHNode>& getNodes() const { return nodes; }
    const std::vector<std::shared_ptr<Hittable>>& getPrimitives() const { return primitives; }
};

// ============================================================================
// LIGHT MANAGEMENT
// ============================================================================

class LightList {
    std::vector<std::shared_ptr<Hittable>> lights;
    std::vector<float> powerDist;
    float totalPower = 0;
public:
    void add(std::shared_ptr<Hittable> l) {
        lights.push_back(l);
        float power = luminance(l->emittedRadiance());
        if (!l->isInfiniteLight()) {
            AABB b; l->boundingBox(b);
            power *= b.area();
        }
        totalPower += power;
        powerDist.push_back(totalPower);
    }

    LightSample sample(const Vec3& pt, std::mt19937& gen) const {
        if (lights.empty()) return LightSample{Vec3(0), Vec3(0), Vec3(0), 0, 0};
        std::uniform_real_distribution<float> dist(0, 1);
        float u = dist(gen) * totalPower;
        size_t idx = 0;
        for (size_t i = 0; i < powerDist.size(); ++i) if (u < powerDist[i]) { idx = i; break; }
        Vec3 dir = lights[idx]->random(pt, gen);
        HitRecord rec;
        LightSample s;
        if (lights[idx]->hit(Ray(pt, dir), 0.001f, std::numeric_limits<float>::max(), rec)) {
            s.position = rec.point; s.normal = rec.normal;
            Vec3 toPoint = (pt - rec.point).normalized();
            Vec3 lightNormal = rec.frontFace ? rec.normal : -rec.normal;
            s.emission = lights[idx]->emittedRadiance(lightNormal, toPoint) * lights[idx]->directionFalloff(toPoint);
            s.distance = rec.t; s.pdf = lights[idx]->pdfValue(pt, dir);
            float selPdf = (idx > 0 ? powerDist[idx] - powerDist[idx-1] : powerDist[0]) / totalPower;
            s.pdf *= selPdf;
        }
        return s;
    }

    float pdfValue(const Vec3& pt, const Vec3& dir) const {
        if (lights.empty()) return 0;
        float pdf = 0;
        for (size_t i = 0; i < lights.size(); ++i) {
            float selPdf = (i > 0 ? powerDist[i] - powerDist[i-1] : powerDist[0]) / totalPower;
            pdf += selPdf * lights[i]->pdfValue(pt, dir);
        }
        return pdf;
    }

    bool empty() const { return lights.empty(); }

    // Accessors for scene_upload.cu
    const std::vector<std::shared_ptr<Hittable>>& getLights() const { return lights; }
    const std::vector<float>& getPowerDist() const { return powerDist; }
    float getTotalPower() const { return totalPower; }
};

class EnvironmentMap {
    std::vector<float> data;     // RGB interleaved: data[3*(y*width+x) + channel]
    int width = 0, height = 0;
    float strength = 1.0f;       // radiance multiplier
    float rotation = 0.0f;       // horizontal rotation in radians
    bool applyBlenderXRotation = false;

    // CDF data for importance sampling
    std::vector<float> conditionalCdf;  // size: width * height (CDF per row)
    std::vector<float> conditionalFunc; // size: width * height (un-normalized PDF per row)
    std::vector<float> marginalCdf;     // size: height
    std::vector<float> marginalFunc;    // size: height (row totals)
    float totalPower = 0.0f;
    std::vector<astroray::RGBIlluminantSpectrum> spectralAtlas_; // width*height, pre-strength

public:
    bool loaded() const { return !data.empty(); }

    bool load(const std::string& path, float str = 1.0f, float rot = 0.0f, bool blenderXRotation = false) {
        int channels = 0;
        float* rawData = (float*)stbi_loadf(path.c_str(), &width, &height, &channels, 3);
        if (!rawData) {
            printf("Failed to load environment map: %s\n", path.c_str());
            return false;
        }

        data.resize(static_cast<size_t>(width) * height * 3);
        for (int y = 0; y < height; ++y) {
            for (int x = 0; x < width; ++x) {
                int srcIdx = (y * width + x) * 3;
                int dstIdx = ((height - 1 - y) * width + x) * 3;  // Flip vertically
                data[dstIdx + 0] = rawData[srcIdx + 0];
                data[dstIdx + 1] = rawData[srcIdx + 1];
                data[dstIdx + 2] = rawData[srcIdx + 2];
            }
        }

        stbi_image_free(rawData);
        strength = str;
        rotation = rot;
        applyBlenderXRotation = blenderXRotation;
        printf("Loaded environment map: %s (%dx%d)\n", path.c_str(), width, height);
        buildCdf();
        spectralAtlas_.clear();
        spectralAtlas_.reserve(static_cast<size_t>(width) * height);
        for (int i = 0; i < width * height; ++i)
            spectralAtlas_.emplace_back(std::array<float,3>{data[3*i], data[3*i+1], data[3*i+2]});
        return true;
    }

    Vec3 lookup(const Vec3& direction) const {
        if (width == 0 || height == 0) return Vec3(0);

        Vec3 mappedDir = direction;
        if (applyBlenderXRotation) {
            mappedDir = Vec3(direction.x, direction.z, -direction.y);
        }

        // Convert direction to equirectangular (u, v) coordinates:
        float theta = std::acos(std::clamp(mappedDir.y, -1.0f, 1.0f)); // polar, 0=up
        float phi = std::atan2(mappedDir.z, mappedDir.x);                // azimuthal
        phi += rotation;  // apply horizontal rotation
        float u = 0.5f + phi / (2.0f * M_PI);  // [0, 1]
        float v = 1.0f - theta / M_PI;          // [0, 1], flipped: y=+1 (up) â†’ row height-1

        // Wrap u to [0,1] range
        if (u < 0) u += 1.0f;
        if (u >= 1.0f) u -= 1.0f;

        // Convert to pixel coordinates
        float uPixel = u * width;
        float vPixel = v * height;

        // Get integer coordinates
        int x0 = static_cast<int>(uPixel);
        int x1 = x0 + 1;
        int y0 = static_cast<int>(vPixel);
        int y1 = y0 + 1;

        // Clamp coordinates
        x0 = std::max(0, std::min(width - 1, x0));
        x1 = std::max(0, std::min(width - 1, x1));
        y0 = std::max(0, std::min(height - 1, y0));
        y1 = std::max(0, std::min(height - 1, y1));

        // Calculate fractional parts
        float uFract = uPixel - x0;
        float vFract = vPixel - y0;

        // Get pixel colors
        auto getPixel = [&](int x, int y) -> Vec3 {
            return Vec3(data[(y * width + x) * 3 + 0],
                       data[(y * width + x) * 3 + 1],
                       data[(y * width + x) * 3 + 2]);
        };

        Vec3 c00 = getPixel(x0, y0);
        Vec3 c10 = getPixel(x1, y0);
        Vec3 c01 = getPixel(x0, y1);
        Vec3 c11 = getPixel(x1, y1);

        // Bilinear interpolation
        Vec3 c0 = c00 * (1 - uFract) + c10 * uFract;
        Vec3 c1 = c01 * (1 - uFract) + c11 * uFract;
        Vec3 color = c0 * (1 - vFract) + c1 * vFract;

        return color * strength;
    }

    astroray::SampledSpectrum evalSpectral(const Vec3& direction,
                                            const astroray::SampledWavelengths& lambdas) const {
        if (width == 0 || height == 0) return astroray::SampledSpectrum(0.0f);

        Vec3 mappedDir = direction;
        if (applyBlenderXRotation)
            mappedDir = Vec3(direction.x, direction.z, -direction.y);

        float theta = std::acos(std::clamp(mappedDir.y, -1.0f, 1.0f));
        float phi = std::atan2(mappedDir.z, mappedDir.x);
        phi += rotation;
        float u = 0.5f + phi / (2.0f * M_PI);
        float v = 1.0f - theta / M_PI;

        if (u < 0) u += 1.0f;
        if (u >= 1.0f) u -= 1.0f;

        float uPixel = u * width;
        float vPixel = v * height;

        int x0 = std::max(0, std::min(width  - 1, static_cast<int>(uPixel)));
        int x1 = std::max(0, std::min(width  - 1, x0 + 1));
        int y0 = std::max(0, std::min(height - 1, static_cast<int>(vPixel)));
        int y1 = std::max(0, std::min(height - 1, y0 + 1));

        float uFract = uPixel - x0;
        float vFract = vPixel - y0;

        astroray::SampledSpectrum s00 = spectralAtlas_[y0 * width + x0].sample(lambdas);
        astroray::SampledSpectrum s10 = spectralAtlas_[y0 * width + x1].sample(lambdas);
        astroray::SampledSpectrum s01 = spectralAtlas_[y1 * width + x0].sample(lambdas);
        astroray::SampledSpectrum s11 = spectralAtlas_[y1 * width + x1].sample(lambdas);

        astroray::SampledSpectrum s0 = s00 * (1.0f - uFract) + s10 * uFract;
        astroray::SampledSpectrum s1 = s01 * (1.0f - uFract) + s11 * uFract;
        return (s0 * (1.0f - vFract) + s1 * vFract) * strength;
    }

private:
    void buildCdf() {
        if (width == 0 || height == 0) return;

        // Resize CDF arrays
        conditionalFunc.resize(width * height);
        conditionalCdf.resize(width * height);
        marginalFunc.resize(height);
        marginalCdf.resize(height);

        // Step 1: Compute un-normalized PDF for each pixel
        // and marginal function (row totals)
        totalPower = 0.0f;
        for (int v = 0; v < height; ++v) {
            float sinTheta = std::sin(M_PI * (v + 0.5f) / height);
            float rowTotal = 0.0f;

            for (int u = 0; u < width; ++u) {
                int idx = v * width + u;
                Vec3 pixel(data[idx * 3 + 0], data[idx * 3 + 1], data[idx * 3 + 2]);
                float funcValue = luminance(pixel) * sinTheta;
                conditionalFunc[idx] = funcValue;
                rowTotal += funcValue;
            }
            marginalFunc[v] = rowTotal;
            totalPower += rowTotal;
        }

        // Step 2: Build conditional CDFs for each row
        for (int v = 0; v < height; ++v) {
            float rowTotal = marginalFunc[v];
            if (rowTotal <= 0) continue;

            float cumulative = 0.0f;
            for (int u = 0; u < width; ++u) {
                int idx = v * width + u;
                cumulative += conditionalFunc[idx];
                conditionalCdf[idx] = cumulative / rowTotal;  // Normalize
            }
        }

        // Step 3: Build marginal CDF
        float cumulative = 0.0f;
        for (int v = 0; v < height; ++v) {
            cumulative += marginalFunc[v];
            marginalCdf[v] = cumulative / totalPower;  // Normalize
        }
    }

public:
    struct EnvSample {
        Vec3 direction;
        Vec3 radiance;
        float pdf;
    };

    EnvSample sample(std::mt19937& gen) const {
        if (width == 0 || height == 0 || totalPower <= 0) {
            return {Vec3(0, 1, 0), Vec3(0), 0.0f};
        }

        // Draw uniform random numbers
        std::uniform_real_distribution<float> dist(0, 1);
        float xi1 = dist(gen);
        float xi2 = dist(gen);

        // Binary search in marginal CDF to find row
        int v = 0;
        if (marginalCdf.size() > 0) {
            auto it = std::lower_bound(marginalCdf.begin(), marginalCdf.end(), xi1);
            v = std::distance(marginalCdf.begin(), it);
            if (v >= height) v = height - 1;
        }

        // Binary search in conditional CDF to find column
        int u = 0;
        if (conditionalCdf.size() > 0) {
            int start = v * width;
            int end = start + width;
            auto it = std::lower_bound(conditionalCdf.begin() + start, conditionalCdf.begin() + end, xi2);
            u = std::distance(conditionalCdf.begin() + start, it);
            if (u >= width) u = width - 1;
        }

        // Convert u, v to continuous coordinates for interpolation
        float uCont = u + 0.5f;
        float vCont = v + 0.5f;

        // Convert (u_cont, v_cont) to direction (v is flipped: row 0 = nadir)
        float theta = (1.0f - vCont / height) * M_PI;  // [0, pi]
        float phi = (uCont - 0.5f) * 2.0f * M_PI - rotation;  // [0, 2pi] offset by rotation

        Vec3 dir(std::sin(theta) * std::cos(phi),
                 std::cos(theta),
                 std::sin(theta) * std::sin(phi));
        if (applyBlenderXRotation) {
            dir = Vec3(dir.x, -dir.z, dir.y);
        }

        // Compute PDF in solid angle measure
        float sinTheta = std::sin(theta);
        if (sinTheta < 1e-6f) sinTheta = 1e-6f;

        // Find the PDF value for the pixel
        int pixelIdx = v * width + u;
        float funcValue = conditionalFunc[pixelIdx];
        float mapPdf = funcValue * width * height / (totalPower + 1e-10f);
        float solidAnglePdf = mapPdf / (2.0f * M_PI * M_PI * sinTheta);

        // Look up radiance
        Vec3 radiance = Vec3(data[pixelIdx * 3 + 0],
                            data[pixelIdx * 3 + 1],
                            data[pixelIdx * 3 + 2]);

        return {dir, radiance * strength, solidAnglePdf};
    }

    float pdf(const Vec3& direction) const {
        if (width == 0 || height == 0 || totalPower <= 0) return 0.0f;

        Vec3 mappedDir = direction;
        if (applyBlenderXRotation) {
            mappedDir = Vec3(direction.x, direction.z, -direction.y);
        }

        // Convert direction to equirectangular coordinates
        float theta = std::acos(std::clamp(mappedDir.y, -1.0f, 1.0f));
        float phi = std::atan2(mappedDir.z, mappedDir.x);
        phi += rotation;  // apply horizontal rotation

        // Convert to u, v coordinates [0, 1]
        float u = 0.5f + phi / (2.0f * M_PI);
        float v = 1.0f - theta / M_PI;  // flipped to match lookup() convention

        // Wrap u
        if (u < 0) u += 1.0f;
        if (u >= 1.0f) u -= 1.0f;

        // Convert to pixel coordinates
        float uPixel = u * width;
        float vPixel = v * height;

        // Get integer coordinates
        int x = static_cast<int>(uPixel);
        int y = static_cast<int>(vPixel);

        // Clamp coordinates
        x = std::max(0, std::min(width - 1, x));
        y = std::max(0, std::min(height - 1, y));

        // Get PDF value for the pixel
        int pixelIdx = y * width + x;
        float funcValue = conditionalFunc[pixelIdx];

        // Compute PDF in solid angle measure
        float sinTheta = std::sin(theta);
        if (sinTheta < 1e-6f) sinTheta = 1e-6f;

        float pdfUV = funcValue * width * height / (totalPower + 1e-10f);
        float solidAnglePdf = pdfUV / (2.0f * M_PI * M_PI * sinTheta);

        return solidAnglePdf;
    }

    // Accessors for CUDARenderer / scene_upload.cu
    const std::vector<float>& getData()            const { return data; }
    const std::vector<float>& getConditionalCdf()  const { return conditionalCdf; }
    const std::vector<float>& getConditionalFunc() const { return conditionalFunc; }
    const std::vector<float>& getMarginalCdf()     const { return marginalCdf; }
    const std::vector<float>& getMarginalFunc()    const { return marginalFunc; }
    int   getWidth()      const { return width; }
    int   getHeight()     const { return height; }
    float getStrength()   const { return strength; }
    float getRotation()   const { return rotation; }
    float getTotalPower() const { return totalPower; }
};

// ============================================================================
// CAMERA
// ============================================================================

enum RenderPassIndex {
    PASS_DIFFUSE_DIRECT = 0,
    PASS_DIFFUSE_INDIRECT,
    PASS_DIFFUSE_COLOR,
    PASS_GLOSSY_DIRECT,
    PASS_GLOSSY_INDIRECT,
    PASS_GLOSSY_COLOR,
    PASS_TRANSMISSION_DIRECT,
    PASS_TRANSMISSION_INDIRECT,
    PASS_TRANSMISSION_COLOR,
    PASS_VOLUME_DIRECT,
    PASS_VOLUME_INDIRECT,
    PASS_EMISSION,
    PASS_ENVIRONMENT,
    PASS_AO,
    PASS_SHADOW,
    PASS_COUNT
};

// Result type for integrator sampleFull(): color + first-hit AOV data + render passes.
struct SampleResult {
    Vec3 color{0};
    Vec3 albedo{0}, normal{0}, position{0}, uv{0};
    float alpha = 1.0f, depth = 0.0f;
    int objectIndex = 0, materialIndex = 0;
    std::array<Vec3, PASS_COUNT> passes;
    SampleResult() { passes.fill(Vec3(0)); }
};

class Camera {
    Vec3 origin, lowerLeft, horizontal, vertical, u, v, w_axis;
    float lensRadius;
public:
    int width, height;
    std::vector<Vec3> pixels, albedoBuffer, normalBuffer, positionBuffer, uvBuffer;
    std::vector<float> alphaBuffer, depthBuffer, objectIndexBuffer, materialIndexBuffer;
    std::vector<Vec3> cryptomatteObjectBuffer, cryptomatteMaterialBuffer;
    std::vector<float> cryptomatteObjectCoverageBuffer, cryptomatteMaterialCoverageBuffer;
    std::array<std::vector<Vec3>, PASS_COUNT> renderPassBuffers;

    Camera(Vec3 lookFrom, Vec3 lookAt, Vec3 vup, float vfov, float aspectRatio, float aperture, float focusDist, int w, int h)
        : width(w), height(h) {
        float theta = vfov * M_PI / 180.0f;
        float vh = 2.0f * std::tan(theta / 2) * focusDist;
        float vw = aspectRatio * vh;
        w_axis = (lookFrom - lookAt).normalized();
        u = vup.cross(w_axis).normalized();
        v = w_axis.cross(u);
        origin = lookFrom;
        horizontal = u * vw;
        vertical = v * vh;
        lowerLeft = origin - horizontal * 0.5f - vertical * 0.5f - w_axis * focusDist;
        lensRadius = aperture / 2;
        pixels.resize(width * height, Vec3(0));
        albedoBuffer.resize(width * height, Vec3(0));
        normalBuffer.resize(width * height, Vec3(0));
        alphaBuffer.resize(width * height, 1.0f);
        depthBuffer.resize(width * height, 0.0f);
        positionBuffer.resize(width * height, Vec3(0));
        uvBuffer.resize(width * height, Vec3(0));
        objectIndexBuffer.resize(width * height, 0.0f);
        materialIndexBuffer.resize(width * height, 0.0f);
        cryptomatteObjectBuffer.resize(width * height, Vec3(0));
        cryptomatteMaterialBuffer.resize(width * height, Vec3(0));
        cryptomatteObjectCoverageBuffer.resize(width * height, 0.0f);
        cryptomatteMaterialCoverageBuffer.resize(width * height, 0.0f);
        for (auto& passBuffer : renderPassBuffers) {
            passBuffer.resize(width * height, Vec3(0));
        }
    }

    Ray getRay(float s, float t, std::mt19937& gen) const {
        Vec3 rd = Vec3::randomInUnitDisk(gen) * lensRadius;
        Vec3 offset = u * rd.x + v * rd.y;
        Ray ray(origin + offset, lowerLeft + horizontal * s + vertical * t - origin - offset, 0.0f, s, t);
        ray.hasCameraFrame = true;
        ray.cameraOrigin = origin;
        ray.cameraU = u;
        ray.cameraV = v;
        ray.cameraW = w_axis;
        return ray;
    }

    // Accessors for CUDARenderer / scene_upload.cu
    Vec3 getOrigin()     const { return origin; }
    Vec3 getLowerLeft()  const { return lowerLeft; }
    Vec3 getHorizontal() const { return horizontal; }
    Vec3 getVertical()   const { return vertical; }
    Vec3 getU()          const { return u; }
    Vec3 getV()          const { return v; }
    float getLensRadius() const { return lensRadius; }
};

// Named-buffer view over Camera's pixel data, passed to Pass::execute().
class Framebuffer {
    Camera* cam_;
public:
    explicit Framebuffer(Camera& cam) : cam_(&cam) {}
    int width()  const { return cam_->width; }
    int height() const { return cam_->height; }

    float* buffer(const std::string& name) {
        if (name == "color")  return reinterpret_cast<float*>(cam_->pixels.data());
        if (name == "albedo") return reinterpret_cast<float*>(cam_->albedoBuffer.data());
        if (name == "normal") return reinterpret_cast<float*>(cam_->normalBuffer.data());
        if (name == "depth")  return cam_->depthBuffer.data();
        return nullptr;
    }
    const float* buffer(const std::string& name) const {
        return const_cast<Framebuffer*>(this)->buffer(name);
    }
    bool hasBuffer(const std::string& name) const {
        return buffer(name) != nullptr;
    }
};

// ============================================================================
// RENDERER WITH NEE AND MIS - FIX: Proper emission handling
// ============================================================================

class Pass; // defined in astroray/pass.h, included below

class Renderer {
    std::vector<std::shared_ptr<Hittable>> scene;
    std::shared_ptr<BVHAccel> bvh;
    LightList lights;
    std::shared_ptr<EnvironmentMap> envMap;
    Vec3 backgroundColor = Vec3(-1);  // negative = use default sky gradient
    float filmExposure = 1.0f;
    bool useTransparentFilm = false;
    bool transparentGlass = false;
    float clampDirect = 0.0f;   // 0 = disabled
    float clampIndirect = 0.0f; // 0 = disabled
    float filterGlossy = 0.0f;
    bool useReflectiveCaustics = true;
    bool useRefractiveCaustics = true;
    int renderSeed = 0;  // 0 = random (non-deterministic), non-zero = deterministic seed
    // Pixel reconstruction filter (0=Box, 1=Gaussian, 2=Blackman-Harris)
    int pixelFilterType = 0;
    float pixelFilterWidth = 1.5f;
    // World/environment max bounces: env contribution is skipped for bounce > worldMaxBounces
    // Default 1024 = effectively unlimited. Set to 0 for camera-only, 1 for one indirect bounce.
    int worldMaxBounces = 1024;
    bool hasWorldVolume = false;
    float worldVolumeDensity = 0.0f;
    Vec3 worldVolumeColor = Vec3(1.0f);
    float worldVolumeAnisotropy = 0.0f;
    std::shared_ptr<Integrator> integrator_;
    std::vector<std::shared_ptr<Pass>> passes_;

    Vec3 clampLuminance(const Vec3& c, float maxLum) const {
        if (maxLum <= 0.0f) return c;
        float lum = luminance(c);
        if (lum > maxLum && lum > 0.0f) return c * (maxLum / lum);
        return c;
    }

    Vec3 worldTransmittance(float distance) const {
        if (!hasWorldVolume || worldVolumeDensity <= 0.0f || distance <= 0.0f) return Vec3(1.0f);
        float d = std::max(0.0f, distance);
        Vec3 sigmaT = worldVolumeColor * worldVolumeDensity;
        return Vec3(
            std::exp(-std::max(0.0f, sigmaT.x) * d),
            std::exp(-std::max(0.0f, sigmaT.y) * d),
            std::exp(-std::max(0.0f, sigmaT.z) * d)
        );
    }

public:
    // Definitions deferred until Integrator is fully defined below.
    void setIntegrator(std::shared_ptr<Integrator> i);
    void ensureDefaultIntegrator();
    std::unordered_map<std::string, float> integratorDebugStats() const;
    void addPass(std::shared_ptr<Pass> p)  { passes_.push_back(std::move(p)); }
    void clearPasses()                      { passes_.clear(); }

    void setEnvironmentMap(std::shared_ptr<EnvironmentMap> map) { envMap = map; }
    void setBackgroundColor(const Vec3& color) { backgroundColor = color; }
    void setFilmExposure(float exposure) { filmExposure = exposure; }
    void setUseTransparentFilm(bool use) { useTransparentFilm = use; }
    void setTransparentGlass(bool use) { transparentGlass = use; }
    void setClampDirect(float value) { clampDirect = std::max(0.0f, value); }
    void setClampIndirect(float value) { clampIndirect = std::max(0.0f, value); }
    void setFilterGlossy(float value) { filterGlossy = std::max(0.0f, value); }
    void setUseReflectiveCaustics(bool use) { useReflectiveCaustics = use; }
    void setUseRefractiveCaustics(bool use) { useRefractiveCaustics = use; }
    void setSeed(int s) { renderSeed = s; }
    void setPixelFilter(int type, float width) {
        pixelFilterType = std::clamp(type, 0, 2);
        pixelFilterWidth = std::max(0.01f, width);
    }
    void setWorldMaxBounces(int maxB) { worldMaxBounces = std::max(0, maxB); }
    void setWorldVolume(float density, const Vec3& color, float anisotropy = 0.0f) {
        worldVolumeDensity = std::max(0.0f, density);
        worldVolumeColor = Vec3(
            std::max(0.0f, color.x),
            std::max(0.0f, color.y),
            std::max(0.0f, color.z)
        );
        worldVolumeAnisotropy = std::clamp(anisotropy, -0.99f, 0.99f);
        hasWorldVolume = worldVolumeDensity > 0.0f;
    }

    void clear() {
        scene.clear(); bvh.reset(); lights = LightList();
        envMap.reset();
        backgroundColor = Vec3(-1);
        filmExposure = 1.0f;
        useTransparentFilm = false;
        transparentGlass = false;
        clampDirect = 0.0f;
        clampIndirect = 0.0f;
        filterGlossy = 0.0f;
        useReflectiveCaustics = true;
        useRefractiveCaustics = true;
        renderSeed = 0;
        pixelFilterType = 0;
        pixelFilterWidth = 1.5f;
        worldMaxBounces = 1024;
        hasWorldVolume = false;
        worldVolumeDensity = 0.0f;
        worldVolumeColor = Vec3(1.0f);
        worldVolumeAnisotropy = 0.0f;
        integrator_.reset();
        passes_.clear();
    }

    // Returns a sub-pixel jitter offset in [0,1) shaped by the reconstruction filter.
    float filterSample(std::mt19937& gen, std::uniform_real_distribution<float>& dist) const {
        if (pixelFilterType == 1) {
            // Gaussian: Box-Muller centered at 0.5, sigma = filterWidth/6
            float sigma = pixelFilterWidth / 6.0f;
            float u1 = dist(gen);
            float u2 = dist(gen);
            if (u1 < 1e-7f) u1 = 1e-7f;
            float z = std::sqrt(-2.0f * std::log(u1)) * std::cos(2.0f * float(M_PI) * u2);
            return std::clamp(0.5f + z * sigma, 0.0f, 1.0f);
        } else if (pixelFilterType == 2) {
            // Blackman-Harris: rejection sampling within pixel
            for (int attempt = 0; attempt < 20; ++attempt) {
                float x = dist(gen);
                float w = 0.35875f - 0.48829f * std::cos(2.0f * float(M_PI) * x)
                                   + 0.14128f * std::cos(4.0f * float(M_PI) * x)
                                   - 0.01168f * std::cos(6.0f * float(M_PI) * x);
                if (dist(gen) < w) return x;
            }
            return dist(gen);
        }
        // Box filter: uniform jitter (default)
        return dist(gen);
    }

    float powerHeuristic(float a, float b) const {
        float a2 = a*a, b2 = b*b;
        float denom = a2 + b2;
        if (denom < 1e-8f) return 0.5f;
        return a2 / denom;
    }

    float envSelectProb() const {
        bool hasEnv = (envMap && envMap->loaded()) || (backgroundColor.x >= 0.0f);
        if (!hasEnv) return 0.0f;
        if (lights.empty()) return 1.0f;
        // Heuristic: environment gets 50% selection probability
        return 0.5f;
    }

    static bool isTransmissionMaterial(const Material* material) {
        return material && material->isTransmissive();
    }

    static bool isGlossyMaterial(const Material* material) {
        return material && material->isGlossy();
    }

    static Vec3 getMaterialColor(const Material* material) {
        if (!material) return Vec3(0.5f);
        if (auto lambert = dynamic_cast<const Lambertian*>(material)) return lambert->getAlbedo();
        return material->getAlbedo();
    }

    enum class ClosureType {
        Diffuse,
        Glossy,
        Transmission,
        Volume
    };

    static ClosureType classifyMaterial(const Material* material) {
        if (isTransmissionMaterial(material)) return ClosureType::Transmission;
        if (isGlossyMaterial(material)) return ClosureType::Glossy;
        return ClosureType::Diffuse;
    }

    static uint32_t cryptomatteHash(uint32_t value) {
        uint32_t x = value + 0x9e3779b9u;
        x ^= x >> 16;
        x *= 0x7feb352du;
        x ^= x >> 15;
        x *= 0x846ca68bu;
        x ^= x >> 16;
        return x;
    }

    static Vec3 cryptomatteColorFromId(int id) {
        if (id <= 0) return Vec3(0.0f);
        uint32_t h = cryptomatteHash(static_cast<uint32_t>(id));
        return Vec3(
            float((h >> 16) & 0xFF) / 255.0f,
            float((h >> 8) & 0xFF) / 255.0f,
            float(h & 0xFF) / 255.0f
        );
    }

    static bool finiteFloat(float v) {
        return gr_isfinite(static_cast<double>(v));
    }

    static float finiteOrZero(float v) {
        return finiteFloat(v) ? v : 0.0f;
    }

    static float finiteClamped(float v, float lo, float hi) {
        return finiteFloat(v) ? std::clamp(v, lo, hi) : 0.0f;
    }

    static Vec3 finiteVecOrZero(const Vec3& v) {
        return Vec3(finiteOrZero(v.x), finiteOrZero(v.y), finiteOrZero(v.z));
    }


    // Spectral path tracer kernel (Pillar 2, sole render path since pkg14).
    // Uses SampledSpectrum for radiance and throughput; material lookups via
    // evalSpectral / emittedSpectral. Covers BVH traversal, GR-object dispatch,
    // area-light NEE with MIS, emission gating, Russian roulette, and BSDF
    // sampling. AOV passes and per-closure bounce limits are not yet replicated;
    // those are future-package scope.
    astroray::SampledSpectrum pathTraceSpectral(
            const Ray& r, int maxDepth,
            const astroray::SampledWavelengths& lambdas,
            std::mt19937& gen) {
        const int rrDepth = 3;
        astroray::SampledSpectrum color(0.0f);
        astroray::SampledSpectrum throughput(1.0f);
        Ray ray = r;
        bool wasSpecular = true;
        std::uniform_real_distribution<float> dist01(0.0f, 1.0f);

        for (int bounce = 0; bounce < maxDepth; ++bounce) {
            HitRecord rec;
            if (!bvh->hit(ray, 0.001f, std::numeric_limits<float>::max(), rec)) {
                // No env NEE in pathTraceSpectral, so env always contributes on miss
                // (the wasSpecular gate would suppress diffuse-to-background paths).
                if (bounce <= worldMaxBounces) {
                    astroray::SampledSpectrum envSpec(0.0f);
                    if (envMap && envMap->loaded()) {
                        envSpec = envMap->evalSpectral(ray.direction.normalized(), lambdas);
                    } else if (backgroundColor.x >= 0) {
                        envSpec = astroray::RGBIlluminantSpectrum(
                            {backgroundColor.x, backgroundColor.y, backgroundColor.z}).sample(lambdas);
                    } else {
                        float t = 0.5f * (ray.direction.normalized().y + 1.0f);
                        Vec3 bg = (Vec3(1) * (1 - t) + Vec3(0.5f, 0.7f, 1.0f) * t) * 0.2f;
                        envSpec = astroray::RGBIlluminantSpectrum({bg.x, bg.y, bg.z}).sample(lambdas);
                    }
                    color += throughput * envSpec;
                }
                break;
            }
            if (rec.hitObject && rec.hitObject->isGRObject()) {
                auto grResult = rec.hitObject->traceGRSpectral(ray, lambdas, gen);

                if (grResult.hasEmission) {
                    astroray::SampledSpectrum grEmission(0.0f);
                    for (int i = 0; i < astroray::kSpectrumSamples; ++i) {
                        grEmission[i] = finiteClamped(grResult.emission[i], 0.0f, 20.0f);
                    }
                    if (!grEmission.isZero()) {
                        color += throughput * grEmission;
                    }
                }
                if (grResult.captured) {
                    break;
                }

                Vec3 exitDir = grResult.exitDirection;
                float exitLen2 = exitDir.length2();
                if (!finiteFloat(exitDir.x) || !finiteFloat(exitDir.y) ||
                    !finiteFloat(exitDir.z) || !finiteFloat(exitLen2) || exitLen2 < 1e-10f) {
                    break;
                }

                Ray next(rec.point, exitDir, ray.time, ray.screenU, ray.screenV);
                next.hasCameraFrame = ray.hasCameraFrame;
                next.cameraOrigin = ray.cameraOrigin;
                next.cameraU = ray.cameraU;
                next.cameraV = ray.cameraV;
                next.cameraW = ray.cameraW;
                ray = next;
                wasSpecular = true;
                continue;
            }
            if (!rec.material) break;

            // Emission (gated on camera ray or post-specular bounce).
            astroray::SampledSpectrum Le_spec =
                rec.material->emittedSpectral(rec, lambdas);
            if (!Le_spec.isZero()) {
                if (bounce == 0 || wasSpecular) {
                    color += throughput * Le_spec;
                }
                break;
            }

            Vec3 wo = -ray.direction.normalized();

            // Area-light NEE (MIS via power heuristic). Skipped on delta lobes.
            if (!rec.isDelta && !lights.empty()) {
                LightSample ls = lights.sample(rec.point, gen);
                if (ls.pdf > 0) {
                    Vec3 wi = (ls.position - rec.point).normalized();
                    HitRecord shadow;
                    bool hitOccluder = bvh->hit(Ray(rec.point, wi), 0.001f, ls.distance - 0.001f, shadow);
                    bool occluded = hitOccluder && !(shadow.hitObject && shadow.hitObject->isInfiniteLight());
                    if (!occluded) {
                        astroray::SampledSpectrum f_spec =
                            rec.material->evalSpectral(rec, wo, wi, lambdas);
                        astroray::SampledSpectrum L_spec =
                            astroray::RGBIlluminantSpectrum({ls.emission.x, ls.emission.y, ls.emission.z}).sample(lambdas);
                        float bsdfPdf = rec.material->pdf(rec, wo, wi);
                        float a = ls.pdf, b = bsdfPdf;
                        float wt = (a * a) / (a * a + b * b + 1e-8f);
                        color += throughput * f_spec * L_spec * (wt / (ls.pdf + 0.001f));
                    }
                }
            }

            // Russian roulette on luminance of throughput's XYZ.
            if (bounce > rrDepth) {
                astroray::XYZ thrXYZ = throughput.toXYZ(lambdas);
                float p = std::min(0.95f, std::max(0.0f, thrXYZ.Y));
                if (dist01(gen) > p) break;
                if (p > 0.0f) throughput = throughput * (1.0f / p);
            }

            // BSDF sample (direction + pdf are wavelength-independent in pkg11;
            // pkg13 introduces sampleSpectral on dispersive materials).
            BSDFSample bs = rec.material->sample(rec, wo, gen);
            if (bs.pdf <= 0.0f) break;
            astroray::SampledSpectrum f_bs =
                rec.material->evalSpectral(rec, wo, bs.wi, lambdas);
            wasSpecular = bs.isDelta;
            // For delta lobes evalSpectral returns zero (RGB eval is zero on
            // deltas); fall back to upsampling bs.f so specular materials
            // still propagate radiance until pkg13 overrides.
            if (bs.isDelta && f_bs.isZero()) {
                f_bs = astroray::RGBAlbedoSpectrum({bs.f.x, bs.f.y, bs.f.z}).sample(lambdas);
            }
            throughput *= f_bs * (1.0f / (bs.pdf + 0.001f));

            Ray next(rec.point, bs.wi, ray.time, ray.screenU, ray.screenV);
            next.hasCameraFrame = ray.hasCameraFrame;
            next.cameraOrigin = ray.cameraOrigin;
            next.cameraU = ray.cameraU;
            next.cameraV = ray.cameraV;
            next.cameraW = ray.cameraW;
            ray = next;

            float maxC = throughput.maxValue();
            if (maxC > 10.0f) throughput = throughput * (10.0f / maxC);
        }
        return color;
    }

public:
    void addObject(std::shared_ptr<Hittable> obj) {
        scene.push_back(obj);
        if (obj->isLight()) lights.add(obj);
    }

    void buildAcceleration() { bvh = std::make_shared<BVHAccel>(scene); }

    // Accessors for CUDARenderer (scene_upload.cu reads these to upload scene to GPU)
    const std::vector<std::shared_ptr<Hittable>>& getScene() const { return scene; }
    const std::shared_ptr<BVHAccel>& getBVH() const { return bvh; }
    const LightList& getLights() const { return lights; }
    const std::shared_ptr<EnvironmentMap>& getEnvironmentMap() const { return envMap; }
    const Vec3& getBackgroundColor() const { return backgroundColor; }
    float getFilmExposure() const { return filmExposure; }
    bool getUseTransparentFilm() const { return useTransparentFilm; }
    bool getTransparentGlass() const { return transparentGlass; }
    int getWorldMaxBounces() const { return worldMaxBounces; }

void render(Camera& cam, int maxSamples, int maxDepth,
            std::function<void(float)> progress = nullptr, bool adaptive = true, bool applyGamma = false,
            int maxDiffuseBounces = -1, int maxGlossyBounces = -1, int maxTransmissionBounces = -1,
            int maxVolumeBounces = -1, int maxTransparentBounces = -1);
};

// BlackHole class body moved to plugins/shapes/black_hole.cpp (pkg04).
// Include "astroray/black_hole.h" directly where BlackHole is instantiated.

// Include integrator interface AFTER all core types are defined to break the
// circular dependency: integrator.h includes raytracer.h (no-op here), and
// Integrator is fully defined before Renderer::render() is compiled below.
#include "astroray/integrator.h"
// Same pattern for pass.h: Framebuffer wraps Camera which must be defined first.
#include "astroray/pass.h"

inline void Renderer::render(Camera& cam, int maxSamples, int maxDepth,
            std::function<void(float)> progress, bool adaptive, bool applyGamma,
            int maxDiffuseBounces, int maxGlossyBounces, int maxTransmissionBounces,
            int maxVolumeBounces, int maxTransparentBounces) {
        (void)maxDiffuseBounces; (void)maxGlossyBounces; (void)maxTransmissionBounces;
        (void)maxVolumeBounces; (void)maxTransparentBounces;
        ensureDefaultIntegrator();
        buildAcceleration();
        if (integrator_) integrator_->beginFrame(*this, cam);
        std::atomic<int> tilesCompleted{0};
        const int tileSize = 16;
        int tilesX = (cam.width + tileSize - 1) / tileSize;
        int tilesY = (cam.height + tileSize - 1) / tileSize;
        int totalTiles = tilesX * tilesY;

        #pragma omp parallel for schedule(dynamic) collapse(2)
        for (int tileY = 0; tileY < tilesY; ++tileY) {
            for (int tileX = 0; tileX < tilesX; ++tileX) {
                uint32_t baseSeed = (renderSeed == 0)
                    ? static_cast<uint32_t>(std::random_device{}())
                    : static_cast<uint32_t>(renderSeed);
                std::mt19937 gen(baseSeed + static_cast<uint32_t>(tileY * tilesX + tileX));
                std::uniform_real_distribution<float> dist(0, 1);
                int x0 = tileX * tileSize, x1 = std::min(x0 + tileSize, cam.width);
                int y0 = tileY * tileSize, y1 = std::min(y0 + tileSize, cam.height);

                for (int y = y0; y < y1; ++y) {
                    for (int x = x0; x < x1; ++x) {
                        int idx = y * cam.width + x;
                        Vec3 color(0), albedo(0), normal(0), position(0), uv(0);
                        std::array<Vec3, PASS_COUNT> passColor;
                        passColor.fill(Vec3(0));
                        float alpha = 0.0f;
                        float depth = 0.0f;
                        float objectIndex = 0.0f;
                        float materialIndex = 0.0f;
                        std::unordered_map<int, int> objectSampleCounts;
                        std::unordered_map<int, int> materialSampleCounts;
                        float sumL = 0, sumL2 = 0;
                        int samples = 0;

                        for (int s = 0; s < maxSamples; ++s) {
                            float u = (x + filterSample(gen, dist)) / (cam.width - 1);
                            float v = 1.0f - (y + filterSample(gen, dist)) / (cam.height - 1);
                            Vec3 sAlb, sNorm, sPosition(0), sUv(0);
                            std::array<Vec3, PASS_COUNT> sPass;
                            sPass.fill(Vec3(0));
                            float sAlpha = 1.0f;
                            float sDepth = 0.0f;
                            int sObjectIndex = 0;
                            int sMaterialIndex = 0;
                            Vec3 sCol;
                            if (integrator_) {
                                SampleResult ir = integrator_->sampleFull(cam.getRay(u, v, gen), gen);
                                sCol = ir.color;
                                sAlb = ir.albedo;
                                sNorm = ir.normal;
                                sAlpha = ir.alpha;
                                sDepth = ir.depth;
                                sPosition = ir.position;
                                sUv = ir.uv;
                                sObjectIndex = ir.objectIndex;
                                sMaterialIndex = ir.materialIndex;
                                sPass = ir.passes;
                            }
                            sCol = finiteVecOrZero(sCol);
                            // Per-sample firefly suppression: sCol is XYZ, Y is photometric luminance.
                            float sLum = sCol.y;
                            if (sLum > 20.0f) sCol = sCol * (20.0f / sLum);
                            color += sCol;
                            for (int passIndex = 0; passIndex < PASS_COUNT; ++passIndex) {
                                passColor[passIndex] += sPass[passIndex];
                            }
                            alpha += sAlpha;
                            samples++;
                            objectSampleCounts[sObjectIndex]++;
                            materialSampleCounts[sMaterialIndex]++;
                            if (s == 0) { albedo = sAlb; normal = sNorm; }
                            if (s == 0) {
                                depth = sDepth;
                                position = sPosition;
                                uv = sUv;
                                objectIndex = static_cast<float>(sObjectIndex);
                                materialIndex = static_cast<float>(sMaterialIndex);
                            }
                            if (adaptive && s >= 16 && (s + 1) % 8 == 0) {
                                float l = luminance(sCol);
                                sumL += l; sumL2 += l * l;
                                float mean = sumL / (s - 15);
                                float var = (sumL2 / (s - 15)) - mean * mean;
                                if (std::sqrt(std::max(0.0f, var)) / (mean + 0.01f) < 0.01f) break;
                            }
                        }

                        color = color / float(samples);
                        color *= filmExposure;
                        alpha = alpha / float(samples);
                        for (int passIndex = 0; passIndex < PASS_COUNT; ++passIndex) {
                            passColor[passIndex] /= float(samples);
                        }
                        passColor[PASS_DIFFUSE_DIRECT] *= filmExposure;
                        passColor[PASS_DIFFUSE_INDIRECT] *= filmExposure;
                        passColor[PASS_GLOSSY_DIRECT] *= filmExposure;
                        passColor[PASS_GLOSSY_INDIRECT] *= filmExposure;
                        passColor[PASS_TRANSMISSION_DIRECT] *= filmExposure;
                        passColor[PASS_TRANSMISSION_INDIRECT] *= filmExposure;
                        passColor[PASS_VOLUME_DIRECT] *= filmExposure;
                        passColor[PASS_VOLUME_INDIRECT] *= filmExposure;
                        passColor[PASS_EMISSION] *= filmExposure;
                        passColor[PASS_ENVIRONMENT] *= filmExposure;
                        color = xyzToLinearSRGB(color);
                        if (applyGamma) {
                            color.x = std::pow(finiteClamped(color.x, 0.0f, 1.0f), 1.0f / 2.2f);
                            color.y = std::pow(finiteClamped(color.y, 0.0f, 1.0f), 1.0f / 2.2f);
                            color.z = std::pow(finiteClamped(color.z, 0.0f, 1.0f), 1.0f / 2.2f);
                        } else {
                            color.x = std::max(finiteOrZero(color.x), 0.0f);
                            color.y = std::max(finiteOrZero(color.y), 0.0f);
                            color.z = std::max(finiteOrZero(color.z), 0.0f);
                        }
                        cam.pixels[idx] = color;
                        cam.albedoBuffer[idx] = albedo;
                        cam.normalBuffer[idx] = normal;
                        cam.depthBuffer[idx] = depth;
                        cam.positionBuffer[idx] = position;
                        cam.uvBuffer[idx] = uv;
                        cam.objectIndexBuffer[idx] = objectIndex;
                        cam.materialIndexBuffer[idx] = materialIndex;
                        cam.alphaBuffer[idx] = std::clamp(alpha, 0.0f, 1.0f);
                        auto dominantIdAndCoverage = [samples](const std::unordered_map<int, int>& counts) {
                            int bestId = 0;
                            int bestCount = 0;
                            for (const auto& kv : counts) {
                                if (kv.second > bestCount) {
                                    bestId = kv.first;
                                    bestCount = kv.second;
                                }
                            }
                            float coverage = (samples > 0 && bestId > 0) ? float(bestCount) / float(samples) : 0.0f;
                            return std::pair<int, float>(bestId, coverage);
                        };
                        auto objectCrypto = dominantIdAndCoverage(objectSampleCounts);
                        auto materialCrypto = dominantIdAndCoverage(materialSampleCounts);
                        cam.cryptomatteObjectBuffer[idx] = cryptomatteColorFromId(objectCrypto.first);
                        cam.cryptomatteObjectCoverageBuffer[idx] = objectCrypto.second;
                        cam.cryptomatteMaterialBuffer[idx] = cryptomatteColorFromId(materialCrypto.first);
                        cam.cryptomatteMaterialCoverageBuffer[idx] = materialCrypto.second;
                        for (int passIndex = 0; passIndex < PASS_COUNT; ++passIndex) {
                            cam.renderPassBuffers[passIndex][idx] = Vec3(
                                std::max(passColor[passIndex].x, 0.0f),
                                std::max(passColor[passIndex].y, 0.0f),
                                std::max(passColor[passIndex].z, 0.0f)
                            );
                        }
                    }
                }

                if (progress) progress(float(++tilesCompleted) / totalTiles);
            }
        }
        if (integrator_) integrator_->endFrame();
        if (!passes_.empty()) {
            Framebuffer fb(cam);
            for (auto& pass : passes_)
                pass->execute(fb);
        }
}

inline void Renderer::setIntegrator(std::shared_ptr<Integrator> i) {
    integrator_ = std::move(i);
}

inline std::unordered_map<std::string, float> Renderer::integratorDebugStats() const {
    return integrator_ ? integrator_->debugStats() : std::unordered_map<std::string, float>{};
}

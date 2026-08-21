#pragma once

#include <cmath>
#include <vector>
#include <deque>
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
#include "astroray/material_closure.h"
#include "astroray/spectrum.h"
#include "astroray/spectral_profile.h"
#include "astroray/light_sampler.h"
#include "astroray/cryptomatte.h"

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

// pkg160: `GGXEnergyCompensationLUT`, `ggxEnergyCompensationLUT()` and
// `ggxMultiScatterCompensation()` lived here and were deleted. They existed
// SOLELY for plugins/materials/metal.cpp's additive multiscatter term (grep
// confirmed: no other caller in the repo), and that term was wrong three ways
// at once — a runtime-MC table whose 256 uniform-hemisphere samples could not
// resolve a narrow GGX lobe (E -> 0 as roughness -> 0, pinning Fms at its
// 1/pi ceiling exactly where multiple scattering should vanish, measured 24.6x
// below the shipped Cycles table at roughness 0.15), no NdotL (violating the
// eval() brdf*NdotL contract, AGENTS.md:87), and an unpublished
// `roughness*(2-roughness) * 1.3f` weight. metal.cpp now uses the same
// shipped-table, multiplicative Kulla & Conty compensation as disney.cpp
// (astroray::ggxDarkeningChannel, include/astroray/energy_compensation.h),
// which is also what the GPU serves (g_ggxE, src/gpu/gpu_ggx_tables.cu).

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
    // pkg178 Stage-3b PR-3 — UV-aligned shading tangent for anisotropy (PR-4).
    // `tangent`/`bitangent` above are an ARBITRARY buildOrthonormalBasis frame
    // (rotationally unstable across a surface); anisotropic GGX needs a stable
    // tangent locked to the surface's UV parameterization (Blender's default is
    // the active-UV tangent). This is a NEW field — existing isotropic shading
    // keeps reading `tangent`/`bitangent` and is bit-identical. Nothing consumes
    // uvTangent until PR-4. `uvBitangentSign` (+/-1) carries the UV handedness so
    // the consumer reconstructs the bitangent as sign * cross(normal, uvTangent).
    // Populated by Triangle::hit from the active UV layer via the Lengyel
    // inverse-UV-Jacobian; falls back to the arbitrary `tangent` (sign +1) for
    // spheres, untextured meshes, and degenerate UVs (see setFaceNormal default).
    // GPU counterpart (GHitRecord + device UV upload) is deferred to PR-4, where
    // it is gated behind the anisotropy path so non-aniso scenes pay nothing.
    Vec3 uvTangent;
    float uvBitangentSign = 1.0f;
    Vec3 objectPoint, incomingDirection;
    Vec3 cameraOrigin, cameraU, cameraV, cameraW;
    float t;
    bool frontFace;
    bool hasCameraFrame = false;
    Vec2 uv;
    std::vector<Vec2> uvLayers;
    std::vector<std::string> uvLayerNames;
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
        // pkg178 PR-3 — default UV tangent = arbitrary frame. Geometry with a
        // real UV parameterization (textured triangles) overwrites this after
        // setFaceNormal (Triangle::hit); spheres and untextured meshes keep this
        // fallback. uvBitangentSign stays +1 so the fallback frame is right-handed.
        uvTangent = tangent;
        uvBitangentSign = 1.0f;
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

// Include EmissionSpectrum BEFORE Light to resolve circular dependency (pkg89).
// emission_spectrum.h needs Vec3 (defined above), and light.h needs EmissionSpectrum.
#include "astroray/emission_spectrum.h"

// Include astroray::Light after Vec3/AABB/EmissionSpectrum are defined.
#include "astroray/light.h"

// ============================================================================
// SAMPLING STRUCTURES
// ============================================================================

struct LightSample {
    Vec3 position, normal, emission;
    astroray::SampledSpectrum emission_spec;  // pkg89 Q6: extend (not replace) RGB
    float pdf, distance;
    // pkg140: propagated from astroray::Light::LiSample::isDelta (dedicated
    // lights only; legacy Hittable emitters are never delta). Forces the NEE
    // MIS weight to 1 instead of a power heuristic against bsdfPdf -- see
    // pathTraceSpectral / pathTraceSpectralCaustic.
    bool isDelta = false;
};
struct BSDFSample { Vec3 wi, f; float pdf; bool isDelta; };
struct BSDFSampleSpectral { Vec3 wi; astroray::SampledSpectrum f_spectral; float pdf; bool isDelta; };

struct MaterialBackendCapabilities {
    bool cpu = true;
    bool spectral = true;
    bool gpu = false;
    bool gpuSpectral = false;
    bool gpuApproximate = false;
    bool closureGraph = false;
    std::string gpuType;
    std::string notes = "no GPU lowering declared";
};

// ============================================================================
// MATERIALS - ALL FIXES APPLIED
// ============================================================================

class Material {
public:
    virtual ~Material() = default;
    virtual BSDFSample sample(const HitRecord& rec, const Vec3& wo, std::mt19937& gen) const { return BSDFSample{Vec3(0,1,0), Vec3(0), 0, false}; }
    virtual Vec3 eval(const HitRecord& rec, const Vec3& wo, const Vec3& wi) const { return Vec3(0); }
    virtual float pdf(const HitRecord& rec, const Vec3& wo, const Vec3& wi) const { return 0; }
    virtual Vec3 emitted(const HitRecord& rec) const { return Vec3(0); }
    virtual Vec3 getEmission() const { return Vec3(0); }
    virtual bool isEmissive() const { return false; }
    virtual bool isTransmissive() const { return false; }
    virtual bool isGlossy() const { return false; }
    virtual Vec3 getAlbedo() const { return Vec3(0.5f); }
    virtual std::string getGPUTypeName() const { return ""; }
    virtual astroray::MaterialClosureGraph closureGraph() const { return {}; }
    virtual MaterialBackendCapabilities backendCapabilities() const {
        MaterialBackendCapabilities caps;
        auto graph = closureGraph();
        std::string validationReason;
        caps.closureGraph = !graph.empty() &&
            astroray::validateClosureGraph(graph, &validationReason);
        if (caps.closureGraph) {
            caps.gpu = true;
            caps.gpuSpectral = true;
            caps.gpuType = "closure_graph";
            caps.notes = "spectral closure-graph GPU lowering";
        } else {
            caps.gpuType = getGPUTypeName();
            if (!caps.gpuType.empty()) {
                caps.gpu = true;
                caps.gpuSpectral = true;
                caps.notes = "spectral RGB-derived GPU lowering";
            }
        }
        return caps;
    }
    virtual float getRoughness() const { return 0.5f; }
    virtual float getMetallic() const { return 0.0f; }
    virtual float getIOR() const { return 1.5f; }
    // Wavelength-dependent IOR. Default returns the scalar IOR; dispersive
    // materials (Sellmeier dielectric) override this. Used by the SMS
    // wavelength-Newton path (pkg64 Phase 2, Hanika 2015 §4) to evaluate
    // the half-vector residual at the hero wavelength of the current
    // SampledWavelengths bundle.
    virtual float iorAt(float /*lambda_nm*/) const { return getIOR(); }
    // pkg64-gpu-sellmeier-upload: Sellmeier dispersion queries for GPU upload.
    // Non-dispersive materials return false; DielectricPlugin with Sellmeier
    // preset returns true and populates the coefficients.
    virtual bool isDispersive() const { return false; }
    virtual Vec3 getSellmeierB() const { return Vec3(0.0f); }
    virtual Vec3 getSellmeierC() const { return Vec3(0.0f); }
    // pkg187 — Principled dispersion carries a Cauchy (A,B) fit rather than
    // Sellmeier coefficients: n(λ)=A+B/λ² (λ in μm). Returns {A,B,0}. The
    // closure-graph GPU upload packs these into GDispersion.b1/b2 and the
    // dispersive-Principled sampler reads them via gpu_cauchy_ior (NOT
    // gpu_sellmeier_ior). Non-dispersive / non-Principled materials return 0.
    virtual Vec3 getCauchyAB() const { return Vec3(0.0f); }
    virtual float getTransmission() const { return 0.0f; }
    virtual float getClearcoat() const { return 0.0f; }
    virtual float getClearcoatGloss() const { return 1.0f; }
    virtual float getSpecular() const { return 0.5f; }
    virtual float getSpecularTint() const { return 0.0f; }
    virtual float getSheen() const { return 0.0f; }
    virtual float getSheenTint() const { return 0.5f; }
    virtual float getSubsurface() const { return 0.0f; }
    virtual float getAnisotropic() const { return 0.0f; }
    virtual float getAnisotropicRotation() const { return 0.0f; }

    virtual astroray::SampledSpectrum evalSpectral(
            const HitRecord& rec, const Vec3& wo, const Vec3& wi,
            const astroray::SampledWavelengths& lambdas) const = 0;
    virtual astroray::SampledSpectrum emittedSpectral(
            const HitRecord& rec,
            const astroray::SampledWavelengths& lambdas) const {
        return astroray::SampledSpectrum(0.0f);
    }

    virtual BSDFSampleSpectral sampleSpectral(
            const HitRecord& rec, const Vec3& wo,
            std::mt19937& gen,
            astroray::SampledWavelengths& lambdas) const {
        BSDFSample bs = sample(rec, wo, gen);
        BSDFSampleSpectral bss;
        bss.wi = bs.wi;
        bss.pdf = bs.pdf;
        bss.isDelta = bs.isDelta;
        if (bs.isDelta) {
            // pkg118 / #404 (CPU analog): the exit refraction carries eta^2=2.25, but the
            // Jakob-Hanika ALBEDO LUT in RGBAlbedoSpectrum clamps rgb>1 to 1, clipping that
            // radiance recovery and darkening transmissive glass. Factor the >1 magnitude
            // out as a flat spectral scalar; upsample only the normalized [0,1] tint.
            float maxc = std::max(std::max(bs.f.x, bs.f.y), std::max(bs.f.z, 1.0f));
            Vec3 tint = bs.f * (1.0f / maxc);
            bss.f_spectral = astroray::RGBAlbedoSpectrum(
                {tint.x, tint.y, tint.z}).sample(lambdas) * maxc;
        } else {
            // Same eta^2-clamp guard for the rough (non-delta) glass lobe: the rough
            // transmission eval also exceeds 1 on exit, and the albedo LUT would clip it.
            float maxc = std::max(std::max(bs.f.x, bs.f.y), bs.f.z);
            if (maxc > 1.0f) {
                Vec3 tint = bs.f * (1.0f / maxc);
                bss.f_spectral = astroray::RGBAlbedoSpectrum(
                    {tint.x, tint.y, tint.z}).sample(lambdas) * maxc;
            } else {
                bss.f_spectral = evalSpectral(rec, wo, bs.wi, lambdas);
            }
        }
        return bss;
    }

    // pkg39: Spectral profile for outside-visible multi-wavelength rendering.
    // pkg195 Stage C: `mode` selects ExtendOnly (default; out-of-band only) vs
    // Replace (profile drives all λ, bypassing the JH upsample).
    void setSpectralProfile(const astroray::SpectralProfile* p,
                            astroray::ProfileMode mode = astroray::ProfileMode::ExtendOnly) {
        spectralProfile_ = p;
        profileMode_ = mode;
    }
    const astroray::SpectralProfile* getSpectralProfile() const  { return spectralProfile_; }
    astroray::ProfileMode getSpectralProfileMode() const { return profileMode_; }

    // evalSpectral with profile override for outside-visible wavelengths (pkg39).
    // Wavelengths in [380, 780]: use the existing Jakob-Hanika sigmoid path (no change).
    // Wavelengths outside [380, 780] with profile: use profile reflectance x cosTheta/pi.
    // Wavelengths outside [380, 780] without profile: return 0 (physically honest).
    // pkg195 Stage C: in Replace mode the profile drives ALL λ (visible included),
    // never constructing an RGBAlbedoSpectrum (design doc §3.1 principle 2).
    astroray::SampledSpectrum evalSpectralExt(
            const HitRecord& rec, const Vec3& wo, const Vec3& wi,
            const astroray::SampledWavelengths& lambdas) const {
        if (!spectralProfile_) {
            // No profile: return 0 for outside-visible samples, normal eval for visible.
            float cosTheta = wi.dot(rec.normal);
            if (cosTheta <= 0.0f) return astroray::SampledSpectrum(0.0f);
            astroray::SampledSpectrum base = evalSpectral(rec, wo, wi, lambdas);
            for (int i = 0; i < astroray::kSpectrumSamples; ++i) {
                float lam = lambdas.lambda(i);
                if (lam < 380.0f || lam > 780.0f) base[i] = 0.0f;
            }
            return base;
        }
        float cosTheta = wi.dot(rec.normal);
        if (cosTheta <= 0.0f) return astroray::SampledSpectrum(0.0f);
        if (profileMode_ == astroray::ProfileMode::Replace) {
            // Authored SPD drives every wavelength; pure Lambertian transport with
            // per-λ reflectance = profile(λ). No JH round-trip.
            astroray::SampledSpectrum result;
            for (int i = 0; i < astroray::kSpectrumSamples; ++i) {
                result[i] = spectralProfile_->reflectance(lambdas.lambda(i))
                          * cosTheta / float(M_PI);
            }
            return result;
        }
        astroray::SampledSpectrum base = evalSpectral(rec, wo, wi, lambdas);
        astroray::SampledSpectrum result;
        for (int i = 0; i < astroray::kSpectrumSamples; ++i) {
            float lam = lambdas.lambda(i);
            result[i] = (lam >= 380.0f && lam <= 780.0f)
                ? base[i]
                : spectralProfile_->reflectance(lam) * cosTheta / float(M_PI);
        }
        return result;
    }

    BSDFSampleSpectral sampleSpectralExt(
            const HitRecord& rec, const Vec3& wo,
            std::mt19937& gen,
            astroray::SampledWavelengths& lambdas) const {
        BSDFSample bs = sample(rec, wo, gen);
        BSDFSampleSpectral bss;
        bss.wi = bs.wi;
        bss.pdf = bs.pdf;
        bss.isDelta = bs.isDelta;
        // pkg195 Stage C: in Replace mode the authored SPD is the reflectance for
        // every λ — route the non-delta BSDF factor straight through evalSpectralExt
        // so it never passes through the RGB-upsample branch below.
        if (spectralProfile_ && profileMode_ == astroray::ProfileMode::Replace
                && !bs.isDelta) {
            bss.f_spectral = evalSpectralExt(rec, wo, bs.wi, lambdas);
            return bss;
        }
        // pkg118 / #404: factor the exit eta^2 (>1) out so the albedo LUT clamp does not
        // clip it (see sampleSpectral above for the full rationale).
        if (bs.isDelta) {
            float maxc = std::max(std::max(bs.f.x, bs.f.y), std::max(bs.f.z, 1.0f));
            Vec3 tint = bs.f * (1.0f / maxc);
            bss.f_spectral = astroray::RGBAlbedoSpectrum(
                {tint.x, tint.y, tint.z}).sample(lambdas) * maxc;
        } else {
            float maxc = std::max(std::max(bs.f.x, bs.f.y), bs.f.z);
            if (maxc > 1.0f) {
                Vec3 tint = bs.f * (1.0f / maxc);
                bss.f_spectral = astroray::RGBAlbedoSpectrum(
                    {tint.x, tint.y, tint.z}).sample(lambdas) * maxc;
            } else {
                bss.f_spectral = evalSpectralExt(rec, wo, bs.wi, lambdas);
            }
        }
        return bss;
    }

    // pkg87a — Cryptomatte name plumbing
    void setName(const std::string& name) { name_ = name; }
    std::string getName() const { return name_; }

private:
    const astroray::SpectralProfile* spectralProfile_ = nullptr;
    astroray::ProfileMode profileMode_ = astroray::ProfileMode::ExtendOnly;  // pkg195 Stage C
    std::string name_;  // pkg87a — for Cryptomatte material ID
};

class Lambertian : public Material {
    Vec3 albedo;
    astroray::RGBAlbedoSpectrum albedoSpec_;
public:
    Lambertian(const Vec3& a) : albedo(a), albedoSpec_({a.x, a.y, a.z}) {}
    Vec3 getAlbedo() const { return albedo; }
    astroray::MaterialClosureGraph closureGraph() const override {
        astroray::MaterialClosureGraph graph;
        graph.add(astroray::makeDiffuseClosure({albedo.x, albedo.y, albedo.z}));
        return graph;
    }
    std::string getGPUTypeName() const override { return "lambertian"; }

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
    // pkg64 Phase 3 — Cycles-style "caustic caster" opt-in. Default false.
    // When true (and Renderer::useRefractiveCaustics is on), the default
    // path_tracer attempts an SMS connection through this object.
    // Behavior pattern (not source code) inspired by Cycles' shadow-caustics
    // caster flag (intern/cycles/scene/object.h `is_caustics_caster`); the
    // actual SMS sampling is the BSD-3 Mitsuba-2 / Hanika 2015 chain in
    // include/astroray/manifold/. CLAUDE.md §6.
    bool isCausticCaster_ = false;
    std::string name_;  // pkg87a — for Cryptomatte object ID
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
        // pkg67: net frequency shift g = ν_obs / ν_emit accumulated along the
        // null geodesic from observer to escape. The caller is expected to
        // apply this to the exiting ray's carried wavelengths via
        // SampledWavelengths::redshift(g). For Schwarzschild p_t is conserved
        // and the escape g is 1.0; pkg40 Kerr will produce non-trivial values.
        // Defaults to 1.0 (no shift) so the field is safe to read on the
        // captured/non-emitting paths.
        double frequencyShift = 1.0;
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
    void setCausticCaster(bool v) { isCausticCaster_ = v; }
    bool isCausticCaster() const { return isCausticCaster_; }
    // pkg87a — Cryptomatte name plumbing
    void setName(const std::string& name) { name_ = name; }
    std::string getName() const { return name_; }
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

    // pkg202: read-only accessors used by GPU scene upload to convert this
    // legacy hittable sun into the dedicated distant-light device path
    // (scene_upload.cu). Const/additive — no member state changes and the CPU
    // render path is byte-identical (these are never called on CPU).
    const Vec3& getDirection() const { return direction; }
    float getAngularDiameter() const { return angularDiameter; }
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
        rec.hitObject = this;
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

// Forward-declare LightSampler for pkg86.
namespace astroray {
    class LightSampler;
}

class LightList {
    std::vector<std::shared_ptr<Hittable>> lights;              // emissive Hittables (legacy)
    std::vector<std::unique_ptr<astroray::Light>> dedicatedLights;  // pkg89 dedicated Light objects
    std::vector<float> powerDist;                               // unified CDF over both kinds
    float totalPower = 0;

    // pkg86: Light sampler (Power or Tree). Eagerly constructed in the
    // default ctor so OpenMP-parallel render workers don't race on a lazy
    // first-use init. (The original lazy pattern crashed under SIGSEGV on
    // Linux/GCC when two threads entered sample() simultaneously.)
    std::unique_ptr<astroray::LightSampler> sampler_;

public:
    // Defined in src/light_list.cpp because LightSampler is forward-declared
    // here; the eager PowerLightSampler ctor body needs the complete type.
    LightList();
    ~LightList();
    LightList(LightList&&) noexcept;
    LightList& operator=(LightList&&) noexcept;
    LightList(const LightList&) = delete;
    LightList& operator=(const LightList&) = delete;

    // Add an emissive Hittable (legacy path for DiffuseLight / EmissivePlugin).
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

    // Add a dedicated Light (pkg89 Phase A). Takes ownership.
    void addLight(std::unique_ptr<astroray::Light> l) {
        float power = l->power();
        dedicatedLights.push_back(std::move(l));
        totalPower += power;
        powerDist.push_back(totalPower);
    }

    // pkg86: Set the light sampling strategy.
    enum class SamplerMode { Power, Tree };
    void setSampler(SamplerMode mode);

    // pkg86-B: which sampler is active, and its tree (nullptr for Power).
    // Used by the GPU scene upload to flatten the tree onto the device.
    // lightTree() is defined in src/light_list.cpp (LightSampler is
    // forward-declared here).
    SamplerMode samplerMode() const { return samplerMode_; }
    const astroray::LightTree* lightTree() const;

    // Sample a light. Signature widened per pkg89 Q7: now requires lambdas + normal.
    // The normal parameter is unused by most light types but required by anisotropic
    // area lights (future extension).
    // pkg86: Delegates to sampler_ (defaults to PowerLightSampler).
    // Passing by reference avoids MinGW large-struct-by-value corruption (memory/mingw_large_struct_byval.md).
    void sample(LightSample& out, const Vec3& pt, const Vec3& normal,
                const astroray::SampledWavelengths& lambdas,
                std::mt19937& gen) const {
        sampler_->sample(out, pt, normal, lambdas, gen);
    }

    float pdfValue(const Vec3& pt, const Vec3& dir) const {
        return sampler_->pdfValue(pt, dir);
    }

    // pkg181: intersect a BSDF-sampled ray against the dedicated (non-hittable)
    // lights, returning the closest hit within (tMin, tMax]. This is the lamp-
    // intersection pass that makes dedicated lamps visible to BSDF rays (Cycles
    // lights_intersect parity); the emission it returns feeds the EXISTING
    // pkg120 two-sided-MIS term in pathTraceSpectral. Only Area/Distant (finite
    // measure) are hittable; true-delta and Point/Spot lights return false (see
    // pkg181 research note). Returns false when no lamp is hit.
    bool intersectDedicated(const Vec3& origin, const Vec3& dir,
                            float tMin, float tMax,
                            const astroray::SampledWavelengths& lambdas,
                            astroray::Light::Intersection& out) const {
        bool anyHit = false;
        float closest = tMax;
        for (const auto& l : dedicatedLights) {
            astroray::Light::Intersection tmp;
            if (l->intersect(origin, dir, tMin, closest, lambdas, tmp)) {
                closest = tmp.t;
                out = tmp;
                anyHit = true;
            }
        }
        return anyHit;
    }

    bool empty() const { return lights.empty() && dedicatedLights.empty(); }

    // Accessors for scene_upload.cu and pkg86.
    const std::vector<std::shared_ptr<Hittable>>& getLights() const { return lights; }
    const std::vector<std::unique_ptr<astroray::Light>>& getDedicatedLights() const { return dedicatedLights; }
    const std::vector<float>& getPowerDist() const { return powerDist; }
    float getTotalPower() const { return totalPower; }

private:
    // pkg86-B: tracks the mode set by setSampler (move ops reset to Power,
    // matching the existing move semantics that rebuild a PowerLightSampler).
    SamplerMode samplerMode_ = SamplerMode::Power;
};

class EnvironmentMap {
    std::vector<float> data;     // RGB interleaved: data[3*(y*width+x) + channel]
    int width = 0, height = 0;
    float strength = 1.0f;       // radiance multiplier
    // Baked 3x3 rotation matrix (row-major). Forward: world dir → env-map lookup dir.
    // Encodes optional Blender coord-swap + XYZ Euler from Mapping node.
    // Cycles blender/shader.cpp: XYZ extrinsic Euler = Rz*Ry*Rx (Apache-2.0 ref).
    float rotMat[9] = {1,0,0, 0,1,0, 0,0,1};
    float colorTint[3] = {1.0f, 1.0f, 1.0f};  // multiplicative tint pre-MIS

    // CDF data for importance sampling
    std::vector<float> conditionalCdf;  // size: width * height (CDF per row)
    std::vector<float> conditionalFunc; // size: width * height (un-normalized PDF per row)
    std::vector<float> marginalCdf;     // size: height
    std::vector<float> marginalFunc;    // size: height (row totals)
    float totalPower = 0.0f;
    std::vector<astroray::RGBIlluminantSpectrum> spectralAtlas_; // width*height, pre-strength

    // Compute and store the baked rotation matrix.
    // Cycles cycles/blender/shader.cpp: XYZ extrinsic Euler order (Apache-2.0).
    // When blender_conv=true, right-multiplies by R_cswap that maps Astroray
    // world dir to the equirectangular env-map's Y-polar-axis space.
    static void buildRotMat(float* M, float rx, float ry, float rz, bool blender_conv) {
        float cx = std::cos(rx), sx = std::sin(rx);
        float cy = std::cos(ry), sy = std::sin(ry);
        float cz = std::cos(rz), sz = std::sin(rz);
        // R = Rz(rz) * Ry(ry) * Rx(rx), row-major
        M[0] = cz*cy;               M[1] = cz*sy*sx - sz*cx;  M[2] = cz*sy*cx + sz*sx;
        M[3] = sz*cy;               M[4] = sz*sy*sx + cz*cx;  M[5] = sz*sy*cx - cz*sx;
        M[6] = -sy;                 M[7] = cy*sx;              M[8] = cy*cx;
        if (blender_conv) {
            // Right-multiply by R_cswap [[1,0,0],[0,0,1],[0,-1,0]].
            // New col1 = -old col2, new col2 = old col1.
            for (int row = 0; row < 3; ++row) {
                float c1 = M[row*3 + 1];
                float c2 = M[row*3 + 2];
                M[row*3 + 1] = -c2;
                M[row*3 + 2] =  c1;
            }
        }
    }

    Vec3 applyRotMat(const Vec3& d) const {
        return Vec3(rotMat[0]*d.x + rotMat[1]*d.y + rotMat[2]*d.z,
                    rotMat[3]*d.x + rotMat[4]*d.y + rotMat[5]*d.z,
                    rotMat[6]*d.x + rotMat[7]*d.y + rotMat[8]*d.z);
    }

    // Inverse transform (M^T, since M is orthogonal)
    Vec3 applyRotMatT(const Vec3& d) const {
        return Vec3(rotMat[0]*d.x + rotMat[3]*d.y + rotMat[6]*d.z,
                    rotMat[1]*d.x + rotMat[4]*d.y + rotMat[7]*d.z,
                    rotMat[2]*d.x + rotMat[5]*d.y + rotMat[8]*d.z);
    }

public:
    bool loaded() const { return !data.empty(); }

    // rx/ry/rz: Blender Mapping node XYZ Euler rotation in radians.
    // tr/tg/tb: multiplicative color tint from Background node Color input.
    // blender_convention: when true, bakes the Astroray→Blender coord-swap into rotMat.
    bool load(const std::string& path, float str = 1.0f,
              float rx = 0.f, float ry = 0.f, float rz = 0.f,
              float tr = 1.f, float tg = 1.f, float tb = 1.f,
              bool blender_convention = false) {
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
        colorTint[0] = tr; colorTint[1] = tg; colorTint[2] = tb;
        buildRotMat(rotMat, rx, ry, rz, blender_convention);
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

        Vec3 mappedDir = applyRotMat(direction);

        // Convert direction to equirectangular (u, v) coordinates:
        float theta = std::acos(std::clamp(mappedDir.y, -1.0f, 1.0f)); // polar, 0=up
        float phi = std::atan2(mappedDir.z, mappedDir.x);
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

        // pkg63: apply color tint multiplicatively (Cycles parity).
        return Vec3(color.x * colorTint[0], color.y * colorTint[1], color.z * colorTint[2]) * strength;
    }

    astroray::SampledSpectrum evalSpectral(const Vec3& direction,
                                            const astroray::SampledWavelengths& lambdas) const {
        if (width == 0 || height == 0) return astroray::SampledSpectrum(0.0f);

        Vec3 mappedDir = applyRotMat(direction);

        float theta = std::acos(std::clamp(mappedDir.y, -1.0f, 1.0f));
        float phi = std::atan2(mappedDir.z, mappedDir.x);
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
        astroray::SampledSpectrum out = (s0 * (1.0f - vFract) + s1 * vFract) * strength;
        // pkg63: apply RGB color tint as a reflectance-style (no D65 weighting)
        // multiplicative filter on the env-map spectrum. RGBUnboundedSpectrum
        // collapses to a flat scalar for grayscale tints (e.g. (0.5,0.5,0.5)
        // halves the radiance per wavelength), matching Cycles parity:
        //   L = env_sample * background_color * strength.
        //
        // Note (chromatic tints): for non-grayscale tints this differs from
        // the RGB path (lookup() / sample()), which does a direct per-channel
        // multiply on RGB. The two are physically inequivalent: spectral
        // multiplies upsampled spectra, RGB multiplies tristimulus values.
        // For grayscale tints the test gate in tests/test_world_hdri_parity.py
        // confirms agreement to 1% rtol; chromatic-tint cross-path parity is
        // out of scope for pkg63.
        if (colorTint[0] != 1.f || colorTint[1] != 1.f || colorTint[2] != 1.f) {
            astroray::RGBUnboundedSpectrum tintSpec(
                std::array<float,3>{colorTint[0], colorTint[1], colorTint[2]});
            out = out * tintSpec.sample(lambdas);
        }
        return out;
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

        // Convert (u_cont, v_cont) to direction in env-map space (Y is the polar axis).
        float theta = (1.0f - vCont / height) * M_PI;  // [0, pi]
        float phi = (uCont - 0.5f) * 2.0f * M_PI;      // [-pi, pi]

        Vec3 dir_env(std::sin(theta) * std::cos(phi),
                     std::cos(theta),
                     std::sin(theta) * std::sin(phi));
        // Inverse-transform back to world space (M^T applied to env-space direction).
        Vec3 dir = applyRotMatT(dir_env);

        // Compute PDF in solid angle measure
        float sinTheta = std::sin(theta);
        if (sinTheta < 1e-6f) sinTheta = 1e-6f;

        // Find the PDF value for the pixel
        int pixelIdx = v * width + u;
        float funcValue = conditionalFunc[pixelIdx];
        float mapPdf = funcValue * width * height / (totalPower + 1e-10f);
        float solidAnglePdf = mapPdf / (2.0f * M_PI * M_PI * sinTheta);

        // Look up radiance with color tint applied (pkg63 Cycles parity).
        Vec3 radiance(data[pixelIdx * 3 + 0] * colorTint[0],
                      data[pixelIdx * 3 + 1] * colorTint[1],
                      data[pixelIdx * 3 + 2] * colorTint[2]);

        return {dir, radiance * strength, solidAnglePdf};
    }

    float pdf(const Vec3& direction) const {
        if (width == 0 || height == 0 || totalPower <= 0) return 0.0f;

        Vec3 mappedDir = applyRotMat(direction);

        // Convert direction to equirectangular coordinates
        float theta = std::acos(std::clamp(mappedDir.y, -1.0f, 1.0f));
        float phi = std::atan2(mappedDir.z, mappedDir.x);

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
    float getTotalPower() const { return totalPower; }
    // pkg63: baked rotation matrix (3x3 row-major) and color tint accessors
    const float* getRotationMatrix() const { return rotMat; }
    const float* getColorTint()      const { return colorTint; }
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
    float bounceCount = 0.0f, sampleWeight = 0.0f;
    int objectIndex = 0, materialIndex = 0;
    std::array<Vec3, PASS_COUNT> passes;
    SampleResult() { passes.fill(Vec3(0)); }
};

// pkg88-A: Quaternion for camera rotation interpolation (spherical linear interpolation).
// Mirrored from PBRT-v4 src/pbrt/util/quaternion.h (Apache-2.0).
// Shoemake 1985, "Animating Rotation with Quaternion Curves", SIGGRAPH.
struct Quaternion {
    float w, x, y, z;

    Quaternion() : w(1), x(0), y(0), z(0) {}
    Quaternion(float w, float x, float y, float z) : w(w), x(x), y(y), z(z) {}

    float dot(const Quaternion& q) const {
        return w * q.w + x * q.x + y * q.y + z * q.z;
    }

    float length2() const {
        return w*w + x*x + y*y + z*z;
    }

    float length() const {
        return std::sqrt(length2());
    }

    Quaternion normalized() const {
        float len = length();
        return (len > 0) ? Quaternion(w/len, x/len, y/len, z/len) : Quaternion();
    }

    Quaternion operator+(const Quaternion& q) const {
        return Quaternion(w + q.w, x + q.x, y + q.y, z + q.z);
    }

    Quaternion operator-(const Quaternion& q) const {
        return Quaternion(w - q.w, x - q.x, y - q.y, z - q.z);
    }

    Quaternion operator*(float s) const {
        return Quaternion(w * s, x * s, y * s, z * s);
    }

    // Spherical linear interpolation (Shoemake 1985).
    // Mirrored from PBRT-v3 src/core/quaternion.cpp Slerp() (Apache-2.0).
    static Quaternion slerp(float t, const Quaternion& q1, const Quaternion& q2) {
        float cosTheta = q1.dot(q2);
        // Near-parallel quaternions: use linear interpolation
        if (cosTheta > 0.9995f) {
            return ((q1 * (1 - t)) + (q2 * t)).normalized();
        }
        // Spherical interpolation
        float theta = std::acos(std::clamp(cosTheta, -1.0f, 1.0f));
        float thetap = theta * t;
        Quaternion qperp = (q2 - (q1 * cosTheta)).normalized();
        return (q1 * std::cos(thetap)) + (qperp * std::sin(thetap));
    }

    // Convert to 3x3 rotation matrix (returns basis vectors u, v, w).
    // Mirrored from PBRT-v4 Quaternion::ToMatrix() approach (Apache-2.0).
    void toMatrix(Vec3& outU, Vec3& outV, Vec3& outW) const {
        float xx = x * x, yy = y * y, zz = z * z;
        float xy = x * y, xz = x * z, yz = y * z;
        float wx = w * x, wy = w * y, wz = w * z;

        outU = Vec3(1 - 2*(yy + zz), 2*(xy + wz), 2*(xz - wy));
        outV = Vec3(2*(xy - wz), 1 - 2*(xx + zz), 2*(yz + wx));
        outW = Vec3(2*(xz + wy), 2*(yz - wx), 1 - 2*(xx + yy));
    }

    // Construct quaternion from 3x3 rotation matrix (u, v, w basis vectors).
    // Mirrored from PBRT-v4 Quaternion(Transform) constructor logic (Apache-2.0).
    static Quaternion fromMatrix(const Vec3& u, const Vec3& v, const Vec3& w) {
        float trace = u.x + v.y + w.z;
        Quaternion q;
        if (trace > 0.0f) {
            // High-trace path
            float s = std::sqrt(trace + 1.0f);
            q.w = s / 2.0f;
            s = 0.5f / s;
            q.x = (w.y - v.z) * s;
            q.y = (u.z - w.x) * s;
            q.z = (v.x - u.y) * s;
        } else {
            // Low-trace path: find largest diagonal element
            const float* diag[3] = { &u.x, &v.y, &w.z };
            int i = 0;
            if (v.y > u.x) i = 1;
            if (w.z > *diag[i]) i = 2;

            int j = (i + 1) % 3;
            int k = (j + 1) % 3;
            float s = std::sqrt(*diag[i] - *diag[j] - *diag[k] + 1.0f);
            float* qv[3] = { &q.x, &q.y, &q.z };
            *qv[i] = s * 0.5f;
            if (s != 0.0f) s = 0.5f / s;

            // Extract remaining components
            const Vec3* rows[3] = { &u, &v, &w };
            q.w = ((*rows[k])[j] - (*rows[j])[k]) * s;
            *qv[j] = ((*rows[j])[i] + (*rows[i])[j]) * s;
            *qv[k] = ((*rows[k])[i] + (*rows[i])[k]) * s;
        }
        return q.normalized();
    }
};

class Camera {
    Vec3 origin, lowerLeft, horizontal, vertical, u, v, w_axis;
    float lensRadius;
    // pkg72: projection scalars retained so snapshotForMotion() can replay the
    // previous frame's pixel mapping without re-deriving from lowerLeft.
    float vw_ = 0, vh_ = 0, focusDist_ = 0, shiftX_ = 0, shiftY_ = 0;
public:
    int width, height;
    std::vector<Vec3> pixels, albedoBuffer, normalBuffer, positionBuffer, uvBuffer;
    // pkg72: per-pixel previous->current screen-space flow (float2/pixel,
    // OptiX convention). Sized unconditionally to match albedoBuffer/normalBuffer.
    // Mirrors Cycles intern/cycles/integrator/pass.cpp PASS_MOTION (Apache-2.0)
    // but stores only the previous->current half (OptiX consumes this only).
    std::vector<float> motionBuffer;
    std::vector<float> alphaBuffer, depthBuffer, objectIndexBuffer, materialIndexBuffer;
    std::vector<float> bounceCountBuffer, sampleWeightBuffer;
    // pkg87a — Cryptomatte ranked histograms (flat arrays of [id0,weight0,id1,weight1,...])
    std::vector<float> cryptoObjectBuffer, cryptoMaterialBuffer;
    int cryptomatteDepth = 6;  // number of (id, weight) pairs per pixel (default 6 ranks = 3 EXR layers)
    std::array<std::vector<Vec3>, PASS_COUNT> renderPassBuffers;

    // pkg72: snapshot of previous-frame projection state. Populated by
    // snapshotForMotion() at the end of each renderFrame(); read by the
    // render loop to compute motion vectors. Camera-only motion (animated
    // geometry is out of scope per pkg72 spec).
    Vec3 prevOrigin{0}, prevU{0}, prevV{0}, prevW{0};
    float prevVw = 0, prevVh = 0, prevFocusDist = 0, prevShiftX = 0, prevShiftY = 0;
    bool hasPrevCamera = false;

    // pkg88-A: camera motion blur shutter keyframes (T/R/S decomposed).
    // Mirrored from PBRT-v4 AnimatedTransform (Apache-2.0) and Cycles
    // DecomposedTransform (Apache-2.0). Populated by Blender addon when
    // scene.render.use_motion_blur is enabled; consumed by getRay() to
    // interpolate camera basis at sampled time.
    Vec3 shutterStartT{0}, shutterEndT{0};                     // Translation
    Quaternion shutterStartR{}, shutterEndR{};                 // Rotation
    Vec3 shutterStartS{1,1,1}, shutterEndS{1,1,1};             // Scale (uniform for camera)
    float shutter = 0.0f;  // Shutter duration in frames (0 = off, 0.5 = Cycles default)
    enum class ShutterPosition { Start = 0, Center = 1, End = 2 };
    ShutterPosition shutterPosition = ShutterPosition::Center;

    Camera(Vec3 lookFrom, Vec3 lookAt, Vec3 vup, float vfov, float aspectRatio,
           float aperture, float focusDist, int w, int h,
           float shiftX = 0.0f, float shiftY = 0.0f)
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
        lowerLeft = origin - horizontal * (0.5f - shiftX) - vertical * (0.5f - shiftY) - w_axis * focusDist;
        lensRadius = aperture / 2;
        vw_ = vw; vh_ = vh; focusDist_ = focusDist;
        shiftX_ = shiftX; shiftY_ = shiftY;
        pixels.resize(width * height, Vec3(0));
        albedoBuffer.resize(width * height, Vec3(0));
        normalBuffer.resize(width * height, Vec3(0));
        motionBuffer.resize(static_cast<size_t>(width) * height * 2, 0.0f);
        alphaBuffer.resize(width * height, 1.0f);
        depthBuffer.resize(width * height, 0.0f);
        positionBuffer.resize(width * height, Vec3(0));
        uvBuffer.resize(width * height, Vec3(0));
        objectIndexBuffer.resize(width * height, 0.0f);
        materialIndexBuffer.resize(width * height, 0.0f);
        bounceCountBuffer.resize(width * height, 0.0f);
        sampleWeightBuffer.resize(width * height, 0.0f);
        // pkg87a — Cryptomatte buffers: width*height*depth*2 floats (depth pairs of [id, weight])
        cryptoObjectBuffer.resize(static_cast<size_t>(width) * height * cryptomatteDepth * 2, 0.0f);
        cryptoMaterialBuffer.resize(static_cast<size_t>(width) * height * cryptomatteDepth * 2, 0.0f);
        for (auto& passBuffer : renderPassBuffers) {
            passBuffer.resize(width * height, Vec3(0));
        }
    }

    // pkg88-A: getRay now requires explicit time parameter (no default).
    // time ∈ [0, 1] within the shutter window; mapped to actual shutter
    // subframe by shutterPosition. Signature change per spec Q10.
    Ray getRay(float s, float t, float time, std::mt19937& gen) const {
        // pkg88-A: if shutter is off, use current camera basis (pre-pkg88 path).
        // This gates acceptance criterion A3 (zero-shutter regression).
        // pkg88-C.0: the sampled time still rides on the ray — the shutter
        // flag gates CAMERA interpolation only. Deformation motion (geometry
        // with motion data) blurs whenever motion steps exist, mirroring the
        // GPU kernels; static scenes have no time consumers so A3 holds.
        if (shutter <= 0.0f) {
            Vec3 rd = Vec3::randomInUnitDisk(gen) * lensRadius;
            Vec3 offset = u * rd.x + v * rd.y;
            Ray ray(origin + offset, lowerLeft + horizontal * s + vertical * t - origin - offset, time, s, t);
            ray.hasCameraFrame = true;
            ray.cameraOrigin = origin;
            ray.cameraU = u;
            ray.cameraV = v;
            ray.cameraW = w_axis;
            return ray;
        }

        // pkg88-A: interpolate camera transform at sampled time using T/R/S decomposition.
        // Mirrored from PBRT-v4 AnimatedTransform::Interpolate (Apache-2.0).
        // T and S use linear interpolation; R uses quaternion slerp (Shoemake 1985).
        Vec3 T_interp = shutterStartT * (1 - time) + shutterEndT * time;
        Quaternion R_interp = Quaternion::slerp(time, shutterStartR, shutterEndR);
        Vec3 S_interp = shutterStartS * (1 - time) + shutterEndS * time;

        // Convert interpolated rotation quaternion to basis vectors
        Vec3 u_interp, v_interp, w_interp;
        R_interp.toMatrix(u_interp, v_interp, w_interp);

        // Apply scale (for camera, scale is typically uniform (1,1,1), but we store it anyway)
        u_interp = u_interp * S_interp.x;
        v_interp = v_interp * S_interp.y;
        w_interp = w_interp * S_interp.z;

        // Reconstruct camera projection using interpolated transform
        Vec3 origin_interp = T_interp;
        Vec3 horizontal_interp = u_interp * vw_;
        Vec3 vertical_interp = v_interp * vh_;
        Vec3 lowerLeft_interp = origin_interp - horizontal_interp * (0.5f - shiftX_)
                                               - vertical_interp * (0.5f - shiftY_)
                                               - w_interp * focusDist_;

        // Generate ray from interpolated camera
        Vec3 rd = Vec3::randomInUnitDisk(gen) * lensRadius;
        Vec3 offset = u_interp * rd.x + v_interp * rd.y;
        Ray ray(origin_interp + offset,
                lowerLeft_interp + horizontal_interp * s + vertical_interp * t - origin_interp - offset,
                time, s, t);
        ray.hasCameraFrame = true;
        ray.cameraOrigin = origin_interp;
        ray.cameraU = u_interp;
        ray.cameraV = v_interp;
        ray.cameraW = w_interp;
        return ray;
    }

    // pkg72: capture the current frame's projection state as the "previous"
    // camera for the next render call. Mirrors Cycles' approach in
    // intern/cycles/integrator/pass.cpp where motion-pass writes consume the
    // previous-frame camera transform. Called once per frame by the renderer
    // at the end of renderFrame().
    void snapshotForMotion() {
        prevOrigin = origin;
        prevU = u; prevV = v; prevW = w_axis;
        prevVw = vw_; prevVh = vh_; prevFocusDist = focusDist_;
        prevShiftX = shiftX_; prevShiftY = shiftY_;
        hasPrevCamera = true;
    }

    // pkg72: project a world-space point P through the *previous* frame's
    // camera and return its (sub-pixel) screen coordinates. Returns false if
    // P is behind the previous camera (caller stores motion=(0,0) in that
    // case, per the OptiX flow contract documented in
    // .astroray_plan/docs/motion-vectors-research.md).
    bool projectToPrevPixel(const Vec3& P, float& px, float& py) const {
        if (!hasPrevCamera) return false;
        const Vec3 d = P - prevOrigin;
        const float depth = -d.dot(prevW);    // +ve when in front of prev cam
        if (depth <= 1e-6f) return false;
        const float alpha = prevFocusDist / depth;
        const float s = alpha * d.dot(prevU) / prevVw + (0.5f - prevShiftX);
        const float t = alpha * d.dot(prevV) / prevVh + (0.5f - prevShiftY);
        // Render loop maps pixel(x,y) -> u=x/(W-1), v=1-y/(H-1); invert that.
        px = s * float(width - 1);
        py = (1.0f - t) * float(height - 1);
        return true;
    }

    // Accessors for CUDARenderer / scene_upload.cu
    Vec3 getOrigin()     const { return origin; }
    Vec3 getLowerLeft()  const { return lowerLeft; }
    Vec3 getHorizontal() const { return horizontal; }
    Vec3 getVertical()   const { return vertical; }
    Vec3 getU()          const { return u; }
    Vec3 getV()          const { return v; }
    float getLensRadius() const { return lensRadius; }

    // pkg88-A: motion blur accessors for GPU upload
    Vec3 getShutterStartT() const { return shutterStartT; }
    Vec3 getShutterEndT()   const { return shutterEndT; }
    Quaternion getShutterStartR() const { return shutterStartR; }
    Quaternion getShutterEndR()   const { return shutterEndR; }
    Vec3 getShutterStartS() const { return shutterStartS; }
    Vec3 getShutterEndS()   const { return shutterEndS; }
    float getShutter()      const { return shutter; }
    ShutterPosition getShutterPosition() const { return shutterPosition; }
    float getVw()           const { return vw_; }
    float getVh()           const { return vh_; }
    float getFocusDist()    const { return focusDist_; }
    float getShiftX()       const { return shiftX_; }
    float getShiftY()       const { return shiftY_; }
};

// Named-buffer view over Camera's pixel data, passed to Pass::execute().
class Framebuffer {
    Camera* cam_;
public:
    explicit Framebuffer(Camera& cam) : cam_(&cam) {}
    int width()  const { return cam_->width; }
    int height() const { return cam_->height; }
    // pkg87c: Cryptomatte depth accessor for pass plugin
    int cryptomatteDepth() const { return cam_->cryptomatteDepth; }

    float* buffer(const std::string& name) {
        if (name == "color")  return reinterpret_cast<float*>(cam_->pixels.data());
        if (name == "albedo") return reinterpret_cast<float*>(cam_->albedoBuffer.data());
        if (name == "normal") return reinterpret_cast<float*>(cam_->normalBuffer.data());
        if (name == "depth")  return cam_->depthBuffer.data();
        if (name == "bounce_count")  return cam_->bounceCountBuffer.data();
        if (name == "sample_weight") return cam_->sampleWeightBuffer.data();
        // pkg59: UV debug AOV reads first-hit UVs (already populated by the
        // renderer at line ~2392). Stored Vec3-per-pixel; first two channels
        // are the (u,v) sampled by the shader after coord-mode + transform.
        if (name == "uv") return reinterpret_cast<float*>(cam_->uvBuffer.data());
        // pkg72: per-pixel previous->current screen-space motion (float2/pixel,
        // OptiX flow convention). See Camera::motionBuffer.
        if (name == "motion") return cam_->motionBuffer.data();
        // pkg87a: Cryptomatte ranked histograms
        if (name == "crypto_object") return cam_->cryptoObjectBuffer.data();
        if (name == "crypto_material") return cam_->cryptoMaterialBuffer.data();
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
// HALTON SAMPLER (pkg88-A)
// ============================================================================

// pkg88-A: Halton low-discrepancy sampler for time dimension.
// Mirrored from PBRT §8.2 "Halton Sampler" (Apache-2.0).
// Used for stratified time sampling in motion blur.
inline float halton(int index, int base) {
    float result = 0.0f;
    float f = 1.0f;
    int i = index;
    while (i > 0) {
        f = f / base;
        result += f * (i % base);
        i = i / base;
    }
    return result;
}

// ============================================================================
// RENDERER WITH NEE AND MIS - FIX: Proper emission handling
// ============================================================================

class Pass; // defined in astroray/pass.h, included below

class Renderer {
    std::vector<std::shared_ptr<Hittable>> scene;
    std::shared_ptr<BVHAccel> bvh;
    // pkg114 — two-level BVH instancing. A registered mesh keeps its prims in
    // OBJECT-LOCAL space and is built into one BLAS (shared across instances).
    // Instances carry a row-major 4x4 object->world transform. Empty unless a
    // caller uses registerMesh()/addInstance(); the GPU upload only emits a
    // TLAS when instances exist (otherwise the single-level path is unchanged).
    struct InstanceRecord { int meshId; std::array<float, 16> transform; };
    std::vector<std::vector<std::shared_ptr<Hittable>>> meshPrims_;  // local-space prims per mesh
    std::vector<std::shared_ptr<BVHAccel>> meshBlas_;                 // per-mesh BLAS
    std::vector<InstanceRecord> instances_;
    // pkg88-C.0 — scene-wide motion vertex storage for deformation motion blur.
    // Per Cycles motion_triangle.h (Apache-2.0): center step reuses static
    // vertices; additional steps stored here. Linear blend only (K ≤ 3 typical).
    // ONE inner vector per add_triangles_bulk_motion batch: deque growth never
    // moves existing batches and each inner vector is immutable after append,
    // so Triangle::motionVertexBuffer pointers stay valid for the renderer's
    // lifetime. (pkg98 review: a prior single-vector design dangled every
    // earlier batch's pointers when the next batch reallocated it.)
    std::deque<std::vector<Vec3>> motionVertexBatches_;
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
    // pkg113 Phase-3: opt-in GPU photon-map caustic pre-pass. Default FALSE so existing GPU
    // caustic renders (incl. the legacy SMS-GPU path) are unchanged; the photon-map scene
    // pre-pass + gather only runs when a caller explicitly opts in (set_use_photon_caustics).
    bool usePhotonCaustics = false;
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
    // pkg199 Stage 2 — single-scattering albedo α ∈ [0,1] of the homogeneous
    // world medium. σ_t = upsample(color)·density (Stage 1, unchanged);
    // σ_s = α·σ_t; σ_a = (1-α)·σ_t. Default 0 ⇒ σ_s=0 ⇒ the scattering
    // estimator is not engaged (pathTraceSpectral falls back to the exact
    // Stage-1 Beer-Lambert absorption path, byte-identical, same RNG stream).
    // α>0 turns on HG in-scatter / god-rays and makes worldVolumeAnisotropy live.
    float worldVolumeScatter = 0.0f;
    // pkg87b — Cryptomatte per-shade-point accumulation gate
    bool cryptomatteEnabled = false;
    // pkg197 — GPU wavefront first-hit denoise-guide AOV capture gate. On by
    // default (parity with the CPU loop, which always fills the guide buffers).
    // The GPU render path honors it: when off, cuda_wavefront_render is called
    // with null guide out-params, so the intersect stage skips the bounce-0
    // write and the Camera albedo/normal/depth buffers stay zero — the pre-pkg197
    // guide-less state, kept as a control so denoise A/B (guided vs guide-less)
    // is expressible on one build, and as a viewport lever to skip the copy-back.
    bool gpuGuideAOVs = true;
    // pkg198 Stage 2: gate for GPU light-path render passes (diffuse/glossy/
    // transmission direct+indirect, emission, environment). Default OFF — the pass
    // partition allocates per-slot spectral accumulators + per-pixel XYZ buffers and
    // adds copy-back cost, so it is opt-in (the addon/tests enable it when a
    // light-path pass is requested). When off, cuda_wavefront_render receives a null
    // passesOut and every wavefront kernel runs its byte-identical <…,false> path.
    bool gpuLightPathPasses = false;
    std::shared_ptr<Integrator> integrator_;
    std::vector<std::shared_ptr<Pass>> passes_;

    Vec3 clampLuminance(const Vec3& c, float maxLum) const {
        if (maxLum <= 0.0f) return c;
        float lum = luminance(c);
        if (lum > maxLum && lum > 0.0f) return c * (maxLum / lum);
        return c;
    }

    // pkg144 — Cycles-style per-contribution firefly clamp, selected by bounce
    // depth. Ports `film_clamp_light` (src/kernel/film/light_passes.h, Cycles,
    // Apache-2.0):
    //   const float limit = (bounce > 0) ? sample_clamp_indirect : sample_clamp_direct;
    //   const float sum = reduce_add(fabs(*L));
    //   if (sum > limit) *L *= limit / sum;
    // Cycles compares against sum(|RGB|); Astroray's existing brightness metric
    // (the pre-pkg144 always-on `sLum > 20` cap this replaces) is XYZ photometric
    // luminance (Y), so this clamps on toXYZ(lambdas).Y instead — same bounce-
    // indexed limit selection and 0-disables semantics, different (but
    // already-established in this codebase) brightness metric. Applied to each
    // contribution BEFORE it is summed into the path color, so direct (bounce==0,
    // including delta-light NEE) and indirect (bounce>0) contributions are
    // clamped independently rather than the old top-level clamp on the whole
    // summed path.
    astroray::SampledSpectrum clampContribSpectral(const astroray::SampledSpectrum& contrib,
                                                    const astroray::SampledWavelengths& lambdas,
                                                    int bounce) const {
        float limit = (bounce > 0) ? clampIndirect : clampDirect;
        if (limit <= 0.0f) return contrib;
        astroray::XYZ xyz = contrib.toXYZ(lambdas);
        float lum = xyz.Y;
        if (lum > limit && lum > 0.0f) return contrib * (limit / lum);
        return contrib;
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

    // pkg199 Stage 1 — spectral Beer-Lambert transmittance through the
    // homogeneous world medium, `exp(-sigma_t·d)` per wavelength (PBRT-v4 §11.3
    // Beer's law; Cycles kernel/integrator/volume.h). Spectral discipline
    // ([[spectral-upsample-nonlinearity-scaled-bsdf]]): worldVolumeColor is a
    // reflectance-like colour, so upsample the COLOUR through the JH albedo LUT,
    // then apply Beer-Lambert per-λ — never upsample the product. The GPU twin
    // (gpu_worldTransmittanceMW, stage_advance.cu) runs the identical math with
    // GSPEC_RGB_ALBEDO, so CPU↔GPU parity holds by construction. This is the
    // spectral successor to the RGB `worldTransmittance` above (dead since pkg14
    // deleted the legacy RGB integrator that called it; see
    // .astroray_plan/docs/pkg199-world-volume-research.md).
    astroray::SampledSpectrum worldTransmittanceSpectral(
            float distance, const astroray::SampledWavelengths& lambdas) const {
        // pkg199: distance <= 0 OR a distant/infinite light's sentinel distance
        // (DistantLight sets ls.distance = FLT_MAX) is treated like an env-miss —
        // NON-attenuated (Stage-1 infinite-segment convention). The 1e18 cut is
        // far above any real scene extent and far below FLT_MAX, so it flags only
        // genuinely-infinite sources; finite lights (sphere/triangle/point/spot/
        // area) keep their true geometric Beer-Lambert falloff. Mirrors the GPU
        // gpu_worldTransmittanceMW guard so CPU↔GPU distant-light fog agrees.
        if (!hasWorldVolume || worldVolumeDensity <= 0.0f ||
            distance <= 0.0f || distance >= 1e18f)
            return astroray::SampledSpectrum(1.0f);
        float d = std::max(0.0f, distance);
        astroray::SampledSpectrum sigmaColor =
            astroray::RGBAlbedoSpectrum({worldVolumeColor.x, worldVolumeColor.y,
                                         worldVolumeColor.z}).sample(lambdas);
        astroray::SampledSpectrum tr;
        for (int i = 0; i < astroray::kSpectrumSamples; ++i) {
            float sigmaT = std::max(0.0f, sigmaColor[i]) * worldVolumeDensity;
            tr[i] = std::exp(-sigmaT * d);
        }
        return tr;
    }

    // pkg199 Stage 2 — per-λ extinction σ_t[λ] = upsample_reflectance(color)[λ]·
    // density (the SAME quantity worldTransmittanceSpectral exponentiates; factored
    // out so the medium-interaction sampler and the transmittance term share one
    // definition). Spectral discipline: upsample the COLOUR, then scale by density.
    astroray::SampledSpectrum worldSigmaT(
            const astroray::SampledWavelengths& lambdas) const {
        astroray::SampledSpectrum sigmaColor =
            astroray::RGBAlbedoSpectrum({worldVolumeColor.x, worldVolumeColor.y,
                                         worldVolumeColor.z}).sample(lambdas);
        astroray::SampledSpectrum s;
        for (int i = 0; i < astroray::kSpectrumSamples; ++i)
            s[i] = std::max(0.0f, sigmaColor[i]) * worldVolumeDensity;
        return s;
    }

    // pkg199 Stage 2 — Henyey-Greenstein phase function (Henyey & Greenstein
    // 1941; PBRT-v3 `PhaseHG`, src/core/medium.cpp, BSD). cosTheta = dot(wo, wi)
    // with wo pointing back along the incoming ray. Normalised over the sphere
    // (integrates to 1); Inv4Pi = 1/(4π).
    static float phaseHG(float cosTheta, float g) {
        float denom = 1.0f + g * g + 2.0f * g * cosTheta;
        denom = std::max(denom, 1e-6f);
        return (0.25f / float(M_PI)) * (1.0f - g * g) / (denom * std::sqrt(denom));
    }

    // pkg199 Stage 2 — orthonormal basis from a unit vector (PBRT-v3
    // `CoordinateSystem`, src/core/geometry.h, BSD).
    static void coordinateSystem(const Vec3& v1, Vec3& v2, Vec3& v3) {
        if (std::abs(v1.x) > std::abs(v1.y))
            v2 = Vec3(-v1.z, 0.0f, v1.x) / std::sqrt(v1.x * v1.x + v1.z * v1.z);
        else
            v2 = Vec3(0.0f, v1.z, -v1.y) / std::sqrt(v1.y * v1.y + v1.z * v1.z);
        v3 = v1.cross(v2);
    }

    // pkg199 Stage 2 — importance-sample the HG phase function (PBRT-v3
    // `HenyeyGreenstein::Sample_p`, BSD). `wo` points back along the incoming ray
    // (= -ray.direction). Returns the sampled continuation direction wi; outPdf is
    // the phase value (HG is perfectly importance-sampled, so pdf == value, and the
    // throughput factor value/pdf = 1). g>0 forward-scatters (peak at wi = -wo).
    static Vec3 sampleHG(const Vec3& wo, float g, float u1, float u2, float& outPdf) {
        float cosTheta;
        if (std::abs(g) < 1e-3f) {
            cosTheta = 1.0f - 2.0f * u1;
        } else {
            float sqrTerm = (1.0f - g * g) / (1.0f + g - 2.0f * g * u1);
            cosTheta = -(1.0f + g * g - sqrTerm * sqrTerm) / (2.0f * g);
        }
        cosTheta = std::clamp(cosTheta, -1.0f, 1.0f);
        float sinTheta = std::sqrt(std::max(0.0f, 1.0f - cosTheta * cosTheta));
        float phi = 2.0f * float(M_PI) * u2;
        Vec3 v2, v3;
        coordinateSystem(wo, v2, v3);
        Vec3 wi = v2 * (sinTheta * std::cos(phi)) +
                  v3 * (sinTheta * std::sin(phi)) +
                  wo * cosTheta;
        outPdf = phaseHG(cosTheta, g);
        return wi.normalized();
    }

public:
    // Definitions deferred until Integrator is fully defined below.
    void setIntegrator(std::shared_ptr<Integrator> i);
    void ensureDefaultIntegrator();
    std::unordered_map<std::string, float> integratorDebugStats() const;
    void addPass(std::shared_ptr<Pass> p)  { passes_.push_back(std::move(p)); }
    void clearPasses()                      { passes_.clear(); }
    // pkg197: run the registered pass pipeline over a Camera's buffers. The CPU
    // render() already runs this internally (see the passes_ loop at the end of
    // render()); the GPU render route in blender_module.cpp bypasses render() and
    // so must call this explicitly after the wavefront copy-back, otherwise the
    // shipped OIDN/OptiX denoiser passes (added by the addon's use_denoising) and
    // the cryptomatte pass never execute on GPU renders — leaving pkg197's
    // first-hit guides with no consumer on the default backend. Defined
    // out-of-line below render() where Pass/Framebuffer are complete types.
    void applyPasses(Camera& cam);

    void setEnvironmentMap(std::shared_ptr<EnvironmentMap> map) { envMap = map; }
    void setBackgroundColor(const Vec3& color) { backgroundColor = color; }
    void setFilmExposure(float exposure) { filmExposure = exposure; }
    void setUseTransparentFilm(bool use) { useTransparentFilm = use; }
    void setTransparentGlass(bool use) { transparentGlass = use; }
    void setClampDirect(float value) { clampDirect = std::max(0.0f, value); }
    void setClampIndirect(float value) { clampIndirect = std::max(0.0f, value); }
    float getClampDirect() const { return clampDirect; }
    float getClampIndirect() const { return clampIndirect; }
    void setFilterGlossy(float value) { filterGlossy = std::max(0.0f, value); }
    void setUseReflectiveCaustics(bool use) { useReflectiveCaustics = use; }
    void setUseRefractiveCaustics(bool use) { useRefractiveCaustics = use; }
    void setUsePhotonCaustics(bool use) { usePhotonCaustics = use; }
    bool getUseReflectiveCaustics() const { return useReflectiveCaustics; }
    bool getUseRefractiveCaustics() const { return useRefractiveCaustics; }
    bool getUsePhotonCaustics() const { return usePhotonCaustics; }
    // pkg64 Phase 3 — per-object opt-in for SMS connection attempts. The
    // index is the order in which `addObject` was called (same order as
    // `getScene()`). Returns true on success.
    bool setObjectCausticCaster(int objectIndex, bool enabled) {
        if (objectIndex < 0 || static_cast<size_t>(objectIndex) >= scene.size())
            return false;
        scene[objectIndex]->setCausticCaster(enabled);
        return true;
    }
    // pkg87c — Cryptomatte object name setter
    bool setObjectName(int objectIndex, const std::string& name) {
        if (objectIndex < 0 || static_cast<size_t>(objectIndex) >= scene.size())
            return false;
        scene[objectIndex]->setName(name);
        return true;
    }
    int getCausticCasterCount() const {
        int n = 0;
        for (const auto& o : scene) if (o && o->isCausticCaster()) ++n;
        return n;
    }
    int getSceneObjectCount() const { return static_cast<int>(scene.size()); }
    void setSeed(int s) { renderSeed = s; }
    int getSeed() const { return renderSeed; }
    void setPixelFilter(int type, float width) {
        pixelFilterType = std::clamp(type, 0, 2);
        pixelFilterWidth = std::max(0.01f, width);
    }
    void setWorldMaxBounces(int maxB) { worldMaxBounces = std::max(0, maxB); }
    void setWorldVolume(float density, const Vec3& color, float anisotropy = 0.0f,
                        float scatter = 0.0f) {
        worldVolumeDensity = std::max(0.0f, density);
        worldVolumeColor = Vec3(
            std::max(0.0f, color.x),
            std::max(0.0f, color.y),
            std::max(0.0f, color.z)
        );
        worldVolumeAnisotropy = std::clamp(anisotropy, -0.99f, 0.99f);
        // pkg199 Stage 2 — single-scattering albedo (default 0 = Stage-1 absorption).
        worldVolumeScatter = std::clamp(scatter, 0.0f, 1.0f);
        hasWorldVolume = worldVolumeDensity > 0.0f;
    }
    // pkg199 Stage 1 — world-volume accessors (read by cuda_wavefront_render to
    // publish the medium into the GPU wavefront's __constant__ c_worldVolume).
    bool getHasWorldVolume() const { return hasWorldVolume; }
    float getWorldVolumeDensity() const { return worldVolumeDensity; }
    Vec3 getWorldVolumeColor() const { return worldVolumeColor; }
    float getWorldVolumeAnisotropy() const { return worldVolumeAnisotropy; }
    float getWorldVolumeScatter() const { return worldVolumeScatter; }

    // pkg86: Set light sampling strategy (Power or Tree).
    void setLightSampler(LightList::SamplerMode mode) {
        lights.setSampler(mode);
    }

    // pkg87b: Enable/disable Cryptomatte per-shade-point accumulation
    void setCryptomatteEnabled(bool enabled) { cryptomatteEnabled = enabled; }
    bool getCryptomatteEnabled() const { return cryptomatteEnabled; }

    // pkg197: Enable/disable GPU wavefront first-hit denoise-guide AOV capture.
    void setGpuGuideAOVs(bool enabled) { gpuGuideAOVs = enabled; }
    bool getGpuGuideAOVs() const { return gpuGuideAOVs; }
    void setGpuLightPathPasses(bool enabled) { gpuLightPathPasses = enabled; }  // pkg198 Stage 2
    bool getGpuLightPathPasses() const { return gpuLightPathPasses; }           // pkg198 Stage 2

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
        usePhotonCaustics = false;
        renderSeed = 0;
        pixelFilterType = 0;
        pixelFilterWidth = 1.5f;
        worldMaxBounces = 1024;
        hasWorldVolume = false;
        worldVolumeDensity = 0.0f;
        worldVolumeColor = Vec3(1.0f);
        worldVolumeAnisotropy = 0.0f;
        worldVolumeScatter = 0.0f;
        cryptomatteEnabled = false;
        integrator_.reset();
        passes_.clear();
    }

    // Returns a sub-pixel jitter, added to the pixel index by the caller. Box stays
    // within-pixel [0,1); Gaussian/Blackman-Harris emit a pixel-centred (0.5-based)
    // offset over the Cycles reconstruction-filter support and may cross pixel
    // boundaries (filter importance sampling, unit weight — each sample still
    // accumulates to its originating pixel).
    //
    // pkg203 — Cycles-accurate width->sigma mapping (was sigma = width/6).
    // Source: Blender Cycles scene/film.cpp filter_func_gaussian /
    // filter_func_blackman_harris + filter_table per-kernel width pre-scale
    // (Gaussian width*=3 -> exp(-8 v^2/w^2) == sigma=width/4, support +-1.5*width;
    //  BH width*=2 -> support +-1.0*width). License: Apache-2.0. Corroborated by
    // PBRT-v4 section 8.8 (truncated GaussianFilter / windowed BlackmanHarrisFilter).
    // BYTE-MIRROR of src/gpu/wavefront/stage_init.cu::filterSample (same constants).
    // See .astroray_plan/docs/pkg203-filter-sigma-research.md.
    float filterSample(std::mt19937& gen, std::uniform_real_distribution<float>& dist) const {
        if (pixelFilterType == 1) {
            // Gaussian: Box-Muller normal z; Cycles sigma = width/4, support +-1.5*width.
            float sigma = 0.25f * pixelFilterWidth;
            float half  = 1.5f * pixelFilterWidth;
            float u1 = dist(gen);
            float u2 = dist(gen);
            if (u1 < 1e-7f) u1 = 1e-7f;
            float z = std::sqrt(-2.0f * std::log(u1)) * std::cos(2.0f * float(M_PI) * u2);
            float off = std::clamp(z * sigma, -half, half);
            return 0.5f + off;
        } else if (pixelFilterType == 2) {
            // Blackman-Harris: rejection-sample normalised position p in [0,1), then
            // map to a centred offset over the Cycles support +-1.0*width
            // (offset = (p-0.5)*2*width). <=20 attempts, uniform fallback.
            for (int attempt = 0; attempt < 20; ++attempt) {
                float x = dist(gen);
                float w = 0.35875f - 0.48829f * std::cos(2.0f * float(M_PI) * x)
                                   + 0.14128f * std::cos(4.0f * float(M_PI) * x)
                                   - 0.01168f * std::cos(6.0f * float(M_PI) * x);
                if (dist(gen) < w) return 0.5f + (x - 0.5f) * 2.0f * pixelFilterWidth;
            }
            return 0.5f + (dist(gen) - 0.5f) * 2.0f * pixelFilterWidth;
        }
        // Box filter: uniform within-pixel jitter (default; width-ignored).
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
    // pkg64 Phase 3 — optional SMS connection hook called at each
    // non-delta vertex. Receives the vertex hit, the outgoing direction
    // wo (pointing back toward the camera-side), the wavelength bundle,
    // and the rng; returns a spectral contribution to add into `color`
    // already weighted by the integrator's MIS combine. The hook is
    // null by default; the default `path_tracer` integrator passes a
    // lambda only when use_refractive_caustics is on AND at least one
    // object is flagged is_caustic_caster. Keeping the hook empty by
    // default means no behaviour change for caustic-free scenes (the
    // sole added cost is one std::function null-check per vertex).
    using SMSHook = std::function<astroray::SampledSpectrum(
        const HitRecord&, const Vec3& /*wo*/,
        const astroray::SampledSpectrum& /*throughput*/,
        const astroray::SampledWavelengths&, std::mt19937&)>;

    astroray::SampledSpectrum pathTraceSpectral(
            const Ray& r, int maxDepth,
            astroray::SampledWavelengths& lambdas,
            std::mt19937& gen,
            int* outBounces = nullptr,
            float* outWeight = nullptr,
            const SMSHook& smsHook = SMSHook(),
            float* cryptoObjectRanks = nullptr,    // pkg87b: per-pixel crypto object ranks
            float* cryptoMaterialRanks = nullptr,  // pkg87b: per-pixel crypto material ranks
            int cryptoDepth = 6,                    // pkg87b: number of (id, weight) pairs
            // pkg198 Stage 1: optional per-pass spectral accumulators (light-path
            // AOVs). When non-null, every radiance contribution added to `color`
            // is ALSO splatted to exactly one pass (total partition → Σpasses ==
            // beauty). Classification mirrors Cycles kernel/film/light_passes.h +
            // integrator/shade_surface.h (Apache-2.0); see
            // .astroray_plan/docs/pkg198-lightpath-pass-classification-research.md.
            std::array<astroray::SampledSpectrum, PASS_COUNT>* outPasses = nullptr) {
        const int rrDepth = 3;
        astroray::SampledSpectrum color(0.0f);
        astroray::SampledSpectrum throughput(1.0f);
        Ray ray = r;
        bool wasSpecular = true;
        // pkg198 Stage 1: light-path pass category, locked at the first BSDF
        // interaction (Cycles locks pass_diffuse/glossy_weight at bounce 0).
        // -1 = not yet set (DIRECT regime); 0=diffuse, 1=glossy, 2=transmission.
        // DIRECT-pass index = cat*3, INDIRECT-pass index = cat*3+1 (see the
        // RenderPassIndex enum layout). Emission/environment seen before the
        // first bounce go to PASS_EMISSION / PASS_ENVIRONMENT; after a bounce
        // they fold into <firstCat>_INDIRECT.
        int firstCat = -1;
        auto addPass = [&](int passIdx, const astroray::SampledSpectrum& contrib) {
            if (outPasses) (*outPasses)[passIdx] += contrib;
        };
        // pkg120: BSDF pdf that generated the CURRENT continuation ray (the
        // previous bounce's sample). Parked next to wasSpecular so the
        // two-sided MIS emissive-hit term can weight this leg by the power
        // heuristic against the light-sampling pdf of the emitter it lands on.
        float bsdfPdfPrev = 0.0f;
        std::uniform_real_distribution<float> dist01(0.0f, 1.0f);
        int lastBounce = 0;
        float weightSum = 0.0f;
        // pkg199 Stage 2 — engage the scattering estimator only when the medium
        // has nonzero single-scattering albedo. α==0 (default) keeps the exact
        // Stage-1 Beer-Lambert absorption path (byte-identical, same RNG stream).
        const bool mediumScatters = hasWorldVolume && worldVolumeDensity > 0.0f &&
                                    worldVolumeScatter > 0.0f;

        for (int bounce = 0; bounce < maxDepth; ++bounce) {
            lastBounce = bounce;
            HitRecord rec;
            bool didHit = bvh->hit(ray, 0.001f, std::numeric_limits<float>::max(), rec);

            // pkg199 Stage 2 — homogeneous medium free-flight sampling. Engaged
            // ONLY when mediumScatters; otherwise the Stage-1 absorption path below
            // runs untouched. PBRT-v3 HomogeneousMedium::Sample (BSD): per-channel
            // selection distance sampling, balance-heuristic pdf averaged over the
            // spectral channels (unbiased for coloured media). See
            // .astroray_plan/docs/pkg199-stage2-scattering-research.md.
            if (mediumScatters) {
                float surfaceT = didHit ? rec.t : std::numeric_limits<float>::max();
                // Nearest terminating event: surface, or a hittable dedicated lamp
                // closer than it (bounce>0). Env => FLT_MAX.
                float termT = surfaceT;
                if (bounce > 0 && !lights.getDedicatedLights().empty()) {
                    astroray::Light::Intersection lhBound;
                    if (lights.intersectDedicated(ray.origin, ray.direction, 0.001f,
                                                  surfaceT, lambdas, lhBound))
                        termT = lhBound.t;
                }
                astroray::SampledSpectrum sigmaT = worldSigmaT(lambdas);
                int ch = std::min((int)(dist01(gen) * astroray::kSpectrumSamples),
                                  astroray::kSpectrumSamples - 1);
                float sigTc = sigmaT[ch];
                float fdist = (sigTc > 0.0f)
                    ? -std::log(1.0f - dist01(gen)) / sigTc
                    : std::numeric_limits<float>::infinity();
                bool sampledMedium = fdist < termT;
                float tHit = sampledMedium ? fdist : termT;
                astroray::SampledSpectrum Tr;
                for (int i = 0; i < astroray::kSpectrumSamples; ++i)
                    Tr[i] = std::exp(-sigmaT[i] * std::min(tHit, 1e18f));
                if (sampledMedium) {
                    // Scatter: throughput *= Tr * σ_s / pdf,
                    // pdf = avg_ch( σ_t[ch]·Tr[ch] ).
                    float pdf = 0.0f;
                    for (int i = 0; i < astroray::kSpectrumSamples; ++i)
                        pdf += sigmaT[i] * Tr[i];
                    pdf /= float(astroray::kSpectrumSamples);
                    if (pdf <= 0.0f) break;
                    astroray::SampledSpectrum sigmaS = sigmaT * worldVolumeScatter;
                    throughput *= Tr;
                    throughput *= sigmaS;
                    throughput *= (1.0f / pdf);
                    // Scatter point P — the snapshot moment the GPU volume-scatter
                    // stage mirrors byte-for-byte (captured from the PRE-update ray,
                    // before the continuation overwrites ray.origin/direction).
                    Vec3 P = ray.origin + ray.direction * fdist;
                    Vec3 woMedium = -ray.direction.normalized();
                    float g = worldVolumeAnisotropy;
                    // Volume pass routing (pkg198 sum-to-beauty): first interaction
                    // => PASS_VOLUME_DIRECT + lock firstCat=3 (3*3+1=VOLUME_INDIRECT
                    // for everything downstream); a deeper scatter => VOLUME_INDIRECT.
                    bool firstInteraction = (firstCat < 0);
                    int volPass = firstInteraction ? PASS_VOLUME_DIRECT : PASS_VOLUME_INDIRECT;
                    if (firstInteraction) firstCat = 3;
                    // --- Medium NEE (phase / light MIS) ---
                    if (!lights.empty()) {
                        LightSample ls;
                        lights.sample(ls, P, Vec3(0.0f), lambdas, gen);
                        if (ls.pdf > 0.0f) {
                            Vec3 wi = (ls.position - P).normalized();
                            HitRecord shadow;
                            bool hitOcc = bvh->hit(Ray(P, wi, ray.time), 0.001f,
                                                   ls.distance - 0.001f, shadow);
                            bool occluded = hitOcc && !(shadow.hitObject &&
                                                        shadow.hitObject->isInfiniteLight());
                            if (!occluded) {
                                float ph = phaseHG(woMedium.dot(wi), g);
                                float a = ls.pdf, b = ph;  // HG pdf == phase value
                                float wt = ls.isDelta ? 1.0f
                                                      : (a * a) / (a * a + b * b + 1e-8f);
                                astroray::SampledSpectrum neeContrib =
                                    throughput * ls.emission_spec * ph *
                                    (ls.pdf > 1e-8f ? wt / ls.pdf : 0.0f);
                                // Shadow-segment transmittance through the medium
                                // (full σ_t; ls.distance is geometric, distant lights
                                // guarded to Tr=1) — the role-2 analog at a scatter vertex.
                                neeContrib *= worldTransmittanceSpectral(ls.distance, lambdas);
                                astroray::SampledSpectrum c =
                                    clampContribSpectral(neeContrib, lambdas, bounce);
                                color += c; addPass(volPass, c);
                            }
                        }
                    }
                    // --- HG phase-sampled continuation from P ---
                    float phasePdf;
                    Vec3 wiCont = sampleHG(woMedium, g, dist01(gen), dist01(gen), phasePdf);
                    // throughput *= phase/pdf = 1 (HG perfectly importance-sampled).
                    Ray next(P, wiCont, ray.time, ray.screenU, ray.screenV);
                    next.hasCameraFrame = ray.hasCameraFrame;
                    next.cameraOrigin = ray.cameraOrigin;
                    next.cameraU = ray.cameraU;
                    next.cameraV = ray.cameraV;
                    next.cameraW = ray.cameraW;
                    ray = next;
                    wasSpecular = false;
                    bsdfPdfPrev = phasePdf;
                    // Russian roulette (mirror the surface RR below).
                    if (bounce > rrDepth) {
                        astroray::XYZ thrXYZ = throughput.toXYZ(lambdas);
                        float p = std::min(0.95f, std::max(0.0f, thrXYZ.Y));
                        if (dist01(gen) > p) break;
                        if (p > 0.0f) throughput = throughput * (1.0f / p);
                    }
                    weightSum += throughput.maxValue();
                    continue;
                } else {
                    // Reached the terminating event (surface / lamp / env): apply
                    // Tr/pdf, pdf = avg_ch(Tr[ch]); the Stage-1 role-1 multiply below
                    // is then skipped (transmittance is already in throughput).
                    float pdf = 0.0f;
                    for (int i = 0; i < astroray::kSpectrumSamples; ++i)
                        pdf += Tr[i];
                    pdf /= float(astroray::kSpectrumSamples);
                    if (pdf <= 0.0f) break;
                    throughput *= Tr;
                    throughput *= (1.0f / pdf);
                }
            }

            // pkg181: dedicated-light visibility to BSDF rays (Cycles
            // lights_intersect parity). Lamps are invisible to camera rays
            // (bounce == 0) — only indirect/BSDF continuation rays see them. A
            // lamp closer than the surface terminates the path; its emission
            // feeds the SAME pkg120 two-sided-MIS term the emissive-Hittable
            // path uses below (wB = 1 after a specular/delta bounce, where no
            // NEE leg competes; power-heuristic otherwise). Fixes the systemic
            // dim + dark lamp-reflections localized by pkg180 Phase 2.
            if (bounce > 0 && !lights.getDedicatedLights().empty()) {
                float surfaceT = didHit ? rec.t : std::numeric_limits<float>::max();
                astroray::Light::Intersection lh;
                if (lights.intersectDedicated(ray.origin, ray.direction, 0.001f,
                                              surfaceT, lambdas, lh)) {
                    if (!lh.emission.isZero()) {
                        // pkg199 Stage 1 (role 3): the lamp is closer than the
                        // surface, so throughput is not yet segment-attenuated;
                        // attenuate the lamp's emission over the camera→lamp
                        // segment (lh.t). Vacuum: Tr==1 (guarded), unchanged.
                        // pkg199 Stage 2: in scatter mode the free-flight estimator
                        // already applied Tr(termT=lh.t)/pdf to throughput, so the
                        // lamp emission must NOT be re-attenuated here.
                        astroray::SampledSpectrum lampEmission =
                            (hasWorldVolume && !mediumScatters)
                                ? lh.emission * worldTransmittanceSpectral(lh.t, lambdas)
                                : lh.emission;
                        // pkg198: a lamp hit by a continuation ray is indirect light
                        // (bounce > 0), folded into the first-bounce category's INDIRECT
                        // pass (Cycles film_write_indirect_light).
                        int lampPass = (firstCat < 0 ? 0 : firstCat) * 3 + 1;
                        if (wasSpecular) {
                            astroray::SampledSpectrum c =
                                clampContribSpectral(throughput * lampEmission, lambdas, bounce);
                            color += c; addPass(lampPass, c);
                        } else {
                            float lp = lights.pdfValue(ray.origin, ray.direction);
                            float bp = bsdfPdfPrev;
                            float wB = (bp * bp) / (bp * bp + lp * lp + 1e-8f);
                            astroray::SampledSpectrum c =
                                clampContribSpectral(throughput * lampEmission * wB, lambdas, bounce);
                            color += c; addPass(lampPass, c);
                        }
                    }
                    break;  // path terminates on the lamp
                }
            }

            if (!didHit) {
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
                    // pkg198: directly-visible background → PASS_ENVIRONMENT; background
                    // reached after a bounce → <firstCat>_INDIRECT (Cycles
                    // film_write_emission_or_background_pass / film_write_background).
                    int envPass = (firstCat < 0) ? PASS_ENVIRONMENT : (firstCat * 3 + 1);
                    astroray::SampledSpectrum c =
                        clampContribSpectral(throughput * envSpec, lambdas, bounce);
                    color += c; addPass(envPass, c);
                }
                break;
            }
            // pkg199 Stage 1 (role 1): Beer-Lambert free-flight attenuation over
            // the camera/continuation segment just traversed (rec.t), applied on
            // a confirmed surface hit BEFORE this vertex is shaded. This one
            // multiply attenuates the hit's emission (throughput·Le below),
            // carries the fog into this vertex's NEE (via throughput), and
            // propagates it to every later bounce — the spectral successor to the
            // legacy `throughput *= worldTransmittance(rec.t)` (pkg25, deleted by
            // pkg14). The GPU twin does the identical multiply + SoA write-back in
            // intersectPathSlot. Vacuum: guarded, throughput unchanged.
            // pkg199 Stage 2: in scatter mode the free-flight estimator above
            // already applied Tr(termT)/pdf, so skip this deterministic multiply.
            if (hasWorldVolume && worldVolumeDensity > 0.0f && !mediumScatters) {
                throughput *= worldTransmittanceSpectral(rec.t, lambdas);
            }
            if (rec.hitObject && rec.hitObject->isGRObject()) {
                auto grResult = rec.hitObject->traceGRSpectral(ray, lambdas, gen);

                if (grResult.hasEmission) {
                    astroray::SampledSpectrum grEmission(0.0f);
                    for (int i = 0; i < astroray::kSpectrumSamples; ++i) {
                        grEmission[i] = finiteClamped(grResult.emission[i], 0.0f, 20.0f);
                    }
                    if (!grEmission.isZero()) {
                        // pkg198: GR/black-hole emission — treat like surface emission
                        // (PASS_EMISSION when directly visible, else indirect).
                        int grPass = (firstCat < 0) ? PASS_EMISSION : (firstCat * 3 + 1);
                        astroray::SampledSpectrum c =
                            clampContribSpectral(throughput * grEmission, lambdas, bounce);
                        color += c; addPass(grPass, c);
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
                // pkg198: directly-visible surface emission → PASS_EMISSION; emission
                // reached after a non-specular bounce → <firstCat>_INDIRECT (Cycles
                // film_write_emission_or_background_pass).
                int emitPass = (firstCat < 0) ? PASS_EMISSION : (firstCat * 3 + 1);
                if (bounce == 0 || wasSpecular) {
                    // Camera / post-specular ray: no NEE leg competes for this
                    // direction, so the whole emission is taken (w_B = 1).
                    astroray::SampledSpectrum c =
                        clampContribSpectral(throughput * Le_spec, lambdas, bounce);
                    color += c; addPass(emitPass, c);
                } else {
                    // pkg120: two-sided MIS. A BSDF-sampled continuation ray hit
                    // an emitter at a diffuse bounce. Add the BSDF-sampled leg
                    // weighted by the power heuristic against the light-sampling
                    // pdf that would have generated this same hit — the
                    // complement of the NEE leg's w_L. Without this the estimator
                    // is biased dark by exactly the BSDF-weighted portion of the
                    // light (Veach 1997 §9.2; Cycles light_sample_from_intersection
                    // + kernel/light/sample.h::light_sample_mis_weight, Apache-2.0).
                    // lightPdf_hit = selection × solid-angle (× light-tree pdf when
                    // resident) reconstructed by LightList::pdfValue from the
                    // PREVIOUS shading point (ray.origin) toward this emitter — the
                    // same selection probabilities the NEE leg uses.
                    float lightPdfHit = lights.empty()
                        ? 0.0f
                        : lights.pdfValue(ray.origin, ray.direction);
                    float bp = bsdfPdfPrev, lp = lightPdfHit;
                    // Same power-heuristic form as the NEE leg above and the GPU
                    // gpu_mw_powerHeuristic, so w_L + w_B ≈ 1 per direction.
                    float wB = (bp * bp) / (bp * bp + lp * lp + 1e-8f);
                    astroray::SampledSpectrum c =
                        clampContribSpectral(throughput * Le_spec * wB, lambdas, bounce);
                    color += c; addPass(emitPass, c);
                }
                break;
            }

            Vec3 wo = -ray.direction.normalized();

            // Area-light NEE (MIS via power heuristic). Skipped on delta lobes.
            // pkg144: NEE fires at the CURRENT vertex's bounce depth, so a
            // bounce==0 NEE sample (first-hit direct lighting, including
            // delta-light NEE) is clamped by clampDirect (default 0/off) — this
            // is the fix for the delta-sun energy-linearity bug this package
            // exists to close (never silently cap deterministic delta-light NEE).
            if (!rec.isDelta && !lights.empty()) {
                LightSample ls;
                lights.sample(ls, rec.point, rec.normal, lambdas, gen);
                if (ls.pdf > 0) {
                    Vec3 wi = (ls.position - rec.point).normalized();
                    HitRecord shadow;
                    // pkg88-C.0: shadow rays carry the path's shutter time so
                    // moving geometry occludes at the sampled instant.
                    bool hitOccluder = bvh->hit(Ray(rec.point, wi, ray.time), 0.001f, ls.distance - 0.001f, shadow);
                    bool occluded = hitOccluder && !(shadow.hitObject && shadow.hitObject->isInfiniteLight());
                    if (!occluded) {
                        astroray::SampledSpectrum f_spec =
                            rec.material->evalSpectral(rec, wo, wi, lambdas);
                        // pkg89: use emission_spec directly (fixes RGB-collapse bug).
                        astroray::SampledSpectrum L_spec = ls.emission_spec;
                        float bsdfPdf = rec.material->pdf(rec, wo, wi);
                        float a = ls.pdf, b = bsdfPdf;
                        // pkg140: a delta light sample (e.g. DistantLight with
                        // angular_diameter == 0) can never be reproduced by
                        // BSDF sampling (probability 0), so it always gets
                        // full MIS weight rather than a power heuristic
                        // against bsdfPdf. Without this, ls.pdf drops
                        // discontinuously from ~1/solidAngle (huge, wt->1 in
                        // the finite-angle limit) to selPdf (O(1)) right at
                        // angle == 0, undercounting the delta sun's energy.
                        float wt = ls.isDelta ? 1.0f : (a * a) / (a * a + b * b + 1e-8f);
                        astroray::SampledSpectrum neeContrib =
                            throughput * f_spec * L_spec * (ls.pdf > 1e-8f ? wt / ls.pdf : 0.0f);
                        // pkg199 Stage 1 (role 2): attenuate the NEE contribution
                        // over the shadow-ray segment (vertex→lamp, ls.distance).
                        // throughput already carries the camera→vertex fog (role
                        // 1), so this adds the vertex→light leg — total Tr =
                        // Tr(rec.t)·Tr(ls.distance). GPU twin: stageShadowKernel
                        // multiplies the parked NEE lanes by Tr(s.maxDist).
                        if (hasWorldVolume && worldVolumeDensity > 0.0f) {
                            neeContrib *= worldTransmittanceSpectral(ls.distance, lambdas);
                        }
                        // pkg198: NEE at the first (camera-visible) surface is DIRECT
                        // light, tagged by that surface's reflect lobe (diffuse/glossy);
                        // NEE at a deeper vertex is INDIRECT, tagged by firstCat. NEE
                        // only fires on non-delta lobes, so a shadow connection is always
                        // a reflection-side event → diffuse or glossy (never transmission).
                        int neePass = (firstCat < 0)
                            ? (rec.material->isGlossy() ? 1 : 0) * 3 + 0
                            : firstCat * 3 + 1;
                        astroray::SampledSpectrum c =
                            clampContribSpectral(neeContrib, lambdas, bounce);
                        color += c; addPass(neePass, c);
                    }
                }
            }

            // pkg64 Phase 3 — optional SMS strategy. Disjoint from NEE in
            // direction space (NEE samples a straight shadow ray, SMS
            // samples a direction that refracts through a caster and
            // *then* reaches the light), so a balance heuristic with the
            // disjoint-strategy assumption gives w_sms ≈ 1 / w_nee ≈ 1
            // for their respective sample sets — additive combination is
            // the balance heuristic's reduction in this regime. The hook
            // is responsible for any internal MIS weighting.
            if (smsHook && !rec.isDelta) {
                astroray::SampledSpectrum smsContribution =
                    smsHook(rec, wo, throughput, lambdas, gen);
                if (!smsContribution.isZero()) {
                    // pkg198: SMS caustic gathered at this receiver vertex — same
                    // direct/indirect tagging as NEE (light arriving at the surface).
                    int smsPass = (firstCat < 0)
                        ? (rec.material->isGlossy() ? 1 : 0) * 3 + 0
                        : firstCat * 3 + 1;
                    astroray::SampledSpectrum c =
                        clampContribSpectral(throughput * smsContribution, lambdas, bounce);
                    color += c; addPass(smsPass, c);
                }
            }

            // Russian roulette on luminance of throughput's XYZ.
            if (bounce > rrDepth) {
                astroray::XYZ thrXYZ = throughput.toXYZ(lambdas);
                float p = std::min(0.95f, std::max(0.0f, thrXYZ.Y));
                if (dist01(gen) > p) break;
                if (p > 0.0f) throughput = throughput * (1.0f / p);
            }

            BSDFSampleSpectral bss = rec.material->sampleSpectral(rec, wo, gen, lambdas);
            if (bss.pdf <= 0.0f) break;
            wasSpecular = bss.isDelta;
            // pkg120: carry this bounce's BSDF pdf so the next iteration's
            // emissive-hit two-sided MIS can weight the BSDF leg (see above).
            bsdfPdfPrev = bss.pdf;

            // pkg198 Stage 1: lock the light-path category at the FIRST BSDF
            // interaction (Cycles locks pass_diffuse/glossy_weight at bounce 0).
            // TRANSMISSION if the sampled continuation crossed the surface (a
            // geometric sign test on rec.normal — no distance/sentinel consumed);
            // else GLOSSY for a delta/mirror reflection or a glossy material; else
            // DIFFUSE. All indirect light through this vertex inherits firstCat.
            if (firstCat < 0) {
                float sWo = wo.dot(rec.normal);
                float sWi = bss.wi.dot(rec.normal);
                bool transmitted = (sWo * sWi) < 0.0f;
                firstCat = transmitted ? 2
                         : ((bss.isDelta || rec.material->isGlossy()) ? 1 : 0);
            }

            // pkg87b: Cryptomatte per-shade-point accumulation.
            // Weight = average(throughput · bsdf_eval), per Cycles film_write_cryptomatte_slots (Apache-2.0).
            // Accumulated *before* throughput is updated for the next bounce.
            // cryptoObjectRanks/cryptoMaterialRanks point to this pixel's rank array (already offset).
            // Cryptomatte records only the first hit (bounce == 0), not indirect bounces.
            if (cryptomatteEnabled && cryptoObjectRanks && cryptoMaterialRanks && bounce == 0) {
                astroray::SampledSpectrum contrib = throughput * bss.f_spectral;
                astroray::XYZ contribXYZ = contrib.toXYZ(lambdas);
                // Inline XYZ→sRGB (avoiding spectral.h circular dependency).
                // Matrix from spectral.h xyzToLinearSRGB (CIE XYZ D65 → linear sRGB).
                float r =  3.2406f * contribXYZ.X - 1.5372f * contribXYZ.Y - 0.4986f * contribXYZ.Z;
                float g = -0.9689f * contribXYZ.X + 1.8758f * contribXYZ.Y + 0.0415f * contribXYZ.Z;
                float b =  0.0557f * contribXYZ.X - 0.2040f * contribXYZ.Y + 1.0570f * contribXYZ.Z;
                float weight = (r + g + b) / 3.0f;

                float objectId = CRYPTO_ID_NONE, materialId = CRYPTO_ID_NONE;
                if (rec.hitObject && !rec.hitObject->getName().empty()) {
                    objectId = crypto_hash_name(rec.hitObject->getName());
                }
                if (rec.material && !rec.material->getName().empty()) {
                    materialId = crypto_hash_name(rec.material->getName());
                }

                // Pass pixelIndex=0 since cryptoObjectRanks/cryptoMaterialRanks already point to this pixel's data
                crypto_accumulate_shade_point(cryptoObjectRanks, cryptoMaterialRanks,
                                               0, cryptoDepth, objectId, materialId, weight);
            }

            // pkg172(A): guarded-pdf throughput update (pbrt-v4 convention —
            // reject the sample when pdf is degenerate, else divide by the
            // EXACT pdf). The former `1/(pdf+1e-3)` additive epsilon was a
            // universal 2π·ε=0.628%/bounce energy loss. See
            // .astroray_plan/docs/pkg172a-guarded-pdf.md.
            throughput *= bss.f_spectral * (bss.pdf > 1e-8f ? 1.0f / bss.pdf : 0.0f);

            Ray next(rec.point, bss.wi, ray.time, ray.screenU, ray.screenV);
            next.hasCameraFrame = ray.hasCameraFrame;
            next.cameraOrigin = ray.cameraOrigin;
            next.cameraU = ray.cameraU;
            next.cameraV = ray.cameraV;
            next.cameraW = ray.cameraW;
            ray = next;

            weightSum += throughput.maxValue();
            float maxC = throughput.maxValue();
            if (maxC > 10.0f) throughput = throughput * (10.0f / maxC);
        }
        if (outBounces) *outBounces = lastBounce;
        if (outWeight) *outWeight = weightSum;
        return color;
    }

    // Opt-in caustic validation kernel for pkg29a. The base path tracer remains
    // the default/reference; this variant adds a small specular-chain connection
    // attempt immediately after delta BSDF events so prism/glass diagnostics can
    // measure whether structured caustic energy is improving.
    astroray::SampledSpectrum pathTraceSpectralCaustic(
            const Ray& r, int maxDepth, int chainIters,
            astroray::SampledWavelengths& lambdas,
            std::mt19937& gen,
            int* outBounces = nullptr,
            float* outWeight = nullptr,
            int* outCausticConnections = nullptr,
            float* outCausticEnergy = nullptr,
            float* cryptoObjectRanks = nullptr,    // pkg87b
            float* cryptoMaterialRanks = nullptr,  // pkg87b
            int cryptoDepth = 6) {                  // pkg87b
        if (lights.empty() || chainIters <= 0) {
            return pathTraceSpectral(r, maxDepth, lambdas, gen, outBounces, outWeight,
                                     SMSHook(), cryptoObjectRanks, cryptoMaterialRanks, cryptoDepth);
        }

        const int rrDepth = 3;
        astroray::SampledSpectrum color(0.0f);
        astroray::SampledSpectrum throughput(1.0f);
        Ray ray = r;
        bool wasSpecular = true;
        std::uniform_real_distribution<float> dist01(0.0f, 1.0f);
        int lastBounce = 0;
        float weightSum = 0.0f;
        int causticConnections = 0;
        float causticEnergy = 0.0f;

        for (int bounce = 0; bounce < maxDepth; ++bounce) {
            lastBounce = bounce;
            HitRecord rec;
            bool didHit = bvh->hit(ray, 0.001f, std::numeric_limits<float>::max(), rec);

            // pkg181: dedicated-lamp visibility (Cycles lights_intersect). This
            // opt-in caustic kernel carries no pkg120 two-sided-MIS state
            // (no bsdfPdfPrev), so — exactly like its emissive-Hittable handling
            // below — a lamp only contributes after a specular/delta bounce
            // (wasSpecular, wB = 1). Non-specular diffuse lamp hits stay NEE-only
            // here (unchanged); the production pathTraceSpectral does the full MIS.
            if (bounce > 0 && wasSpecular && !lights.getDedicatedLights().empty()) {
                float surfaceT = didHit ? rec.t : std::numeric_limits<float>::max();
                astroray::Light::Intersection lh;
                if (lights.intersectDedicated(ray.origin, ray.direction, 0.001f,
                                              surfaceT, lambdas, lh)) {
                    if (!lh.emission.isZero()) {
                        color += clampContribSpectral(throughput * lh.emission, lambdas, bounce);
                    }
                    break;
                }
            }

            if (!didHit) {
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
                    color += clampContribSpectral(throughput * envSpec, lambdas, bounce);
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
                    color += clampContribSpectral(throughput * grEmission, lambdas, bounce);
                }
                if (grResult.captured) break;
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

            astroray::SampledSpectrum Le_spec = rec.material->emittedSpectral(rec, lambdas);
            if (!Le_spec.isZero()) {
                if (bounce == 0 || wasSpecular)
                    color += clampContribSpectral(throughput * Le_spec, lambdas, bounce);
                break;
            }

            Vec3 wo = -ray.direction.normalized();

            if (!rec.isDelta && !lights.empty()) {
                LightSample ls;
                lights.sample(ls, rec.point, rec.normal, lambdas, gen);
                if (ls.pdf > 0) {
                    Vec3 wi = (ls.position - rec.point).normalized();
                    HitRecord shadow;
                    // pkg88-C.0: shadow rays carry the path's shutter time so
                    // moving geometry occludes at the sampled instant.
                    bool hitOccluder = bvh->hit(Ray(rec.point, wi, ray.time), 0.001f, ls.distance - 0.001f, shadow);
                    bool occluded = hitOccluder && !(shadow.hitObject && shadow.hitObject->isInfiniteLight());
                    if (!occluded) {
                        astroray::SampledSpectrum f_spec =
                            rec.material->evalSpectral(rec, wo, wi, lambdas);
                        // pkg89: use emission_spec directly (fixes RGB-collapse bug).
                        astroray::SampledSpectrum L_spec = ls.emission_spec;
                        float bsdfPdf = rec.material->pdf(rec, wo, wi);
                        float a = ls.pdf, b = bsdfPdf;
                        // pkg140: see pathTraceSpectral's identical comment --
                        // delta-light NEE samples always get full MIS weight.
                        float wt = ls.isDelta ? 1.0f : (a * a) / (a * a + b * b + 1e-8f);
                        astroray::SampledSpectrum neeContrib =
                            throughput * f_spec * L_spec * (ls.pdf > 1e-8f ? wt / ls.pdf : 0.0f);
                        color += clampContribSpectral(neeContrib, lambdas, bounce);
                    }
                }
            }

            if (bounce > rrDepth) {
                astroray::XYZ thrXYZ = throughput.toXYZ(lambdas);
                float p = std::min(0.95f, std::max(0.0f, thrXYZ.Y));
                if (dist01(gen) > p) break;
                if (p > 0.0f) throughput = throughput * (1.0f / p);
            }

            BSDFSampleSpectral bss = rec.material->sampleSpectral(rec, wo, gen, lambdas);
            if (bss.pdf <= 0.0f) break;

            // pkg87b: Cryptomatte accumulation at shade point (before throughput update).
            if (cryptomatteEnabled && cryptoObjectRanks && cryptoMaterialRanks) {
                astroray::SampledSpectrum contrib = throughput * bss.f_spectral;
                astroray::XYZ contribXYZ = contrib.toXYZ(lambdas);
                float r =  3.2406f * contribXYZ.X - 1.5372f * contribXYZ.Y - 0.4986f * contribXYZ.Z;
                float g = -0.9689f * contribXYZ.X + 1.8758f * contribXYZ.Y + 0.0415f * contribXYZ.Z;
                float b =  0.0557f * contribXYZ.X - 0.2040f * contribXYZ.Y + 1.0570f * contribXYZ.Z;
                float weight = (r + g + b) / 3.0f;

                float objectId = CRYPTO_ID_NONE, materialId = CRYPTO_ID_NONE;
                if (rec.hitObject && !rec.hitObject->getName().empty()) {
                    objectId = crypto_hash_name(rec.hitObject->getName());
                }
                if (rec.material && !rec.material->getName().empty()) {
                    materialId = crypto_hash_name(rec.material->getName());
                }
                crypto_accumulate_shade_point(cryptoObjectRanks, cryptoMaterialRanks,
                                               0, cryptoDepth, objectId, materialId, weight);
            }

            astroray::SampledSpectrum nextThroughput =
                throughput * bss.f_spectral * (bss.pdf > 1e-8f ? 1.0f / bss.pdf : 0.0f);

            if (bss.isDelta) {
                LightSample ls;
                lights.sample(ls, rec.point, rec.normal, lambdas, gen);
                if (ls.pdf > 0.0f) {
                    Ray walkRay(rec.point, bss.wi, ray.time, ray.screenU, ray.screenV);
                    walkRay.hasCameraFrame = ray.hasCameraFrame;
                    walkRay.cameraOrigin = ray.cameraOrigin;
                    walkRay.cameraU = ray.cameraU;
                    walkRay.cameraV = ray.cameraV;
                    walkRay.cameraW = ray.cameraW;

                    astroray::SampledSpectrum walkThroughput = nextThroughput;
                    astroray::SampledWavelengths walkLambdas = lambdas;
                    for (int stepIndex = 0; stepIndex < chainIters; ++stepIndex) {
                        HitRecord wrec;
                        if (!bvh->hit(walkRay, 0.001f, std::numeric_limits<float>::max(), wrec) ||
                            !wrec.material) {
                            break;
                        }

                        astroray::SampledSpectrum Le = wrec.material->emittedSpectral(wrec, walkLambdas);
                        if (!Le.isZero()) {
                            astroray::SampledSpectrum contribution = walkThroughput * Le;
                            causticConnections += 1;
                            causticEnergy += contribution.maxValue();
                            // pkg144: this specular-chain vertex is always at least
                            // one bounce past the primary hit (only entered after a
                            // delta BSDF sample), so it is always "indirect" for the
                            // clamp split regardless of the outer `bounce` value.
                            color += clampContribSpectral(contribution, walkLambdas, bounce + 1);
                            break;
                        }

                        Vec3 toLight = ls.position - wrec.point;
                        float dist2 = toLight.length2();
                        if (dist2 <= 1e-10f) break;
                        float dist = std::sqrt(dist2);
                        Vec3 wiToLight = toLight * (1.0f / dist);
                        HitRecord occ;
                        bool blocked = bvh->hit(Ray(wrec.point, wiToLight), 0.001f, dist - 0.001f, occ);
                        if (!blocked) {
                            Vec3 wwo = -walkRay.direction.normalized();
                            astroray::SampledSpectrum f_spec =
                                wrec.material->evalSpectral(wrec, wwo, wiToLight, walkLambdas);
                            if (!f_spec.isZero()) {
                                astroray::SampledSpectrum Li =
                                    astroray::RGBIlluminantSpectrum({ls.emission.x, ls.emission.y, ls.emission.z}).sample(walkLambdas);
                                float geom = std::max(0.0f, std::abs(ls.normal.dot(-wiToLight))) /
                                             std::max(dist2, 1e-4f);
                                astroray::SampledSpectrum contribution =
                                    walkThroughput * f_spec * Li * (ls.pdf > 1e-8f ? geom / ls.pdf : 0.0f);
                                causticConnections += 1;
                                causticEnergy += contribution.maxValue();
                                // pkg144: same indirect classification as the emissive
                                // walk-vertex case above.
                                color += clampContribSpectral(contribution, walkLambdas, bounce + 1);
                                break;
                            }
                        }

                        Vec3 wwo = -walkRay.direction.normalized();
                        BSDFSampleSpectral step = wrec.material->sampleSpectral(wrec, wwo, gen, walkLambdas);
                        if (!step.isDelta || step.pdf <= 0.0f) break;
                        walkThroughput *= step.f_spectral * (step.pdf > 1e-8f ? 1.0f / step.pdf : 0.0f);
                        Ray next(wrec.point, step.wi, walkRay.time, walkRay.screenU, walkRay.screenV);
                        next.hasCameraFrame = walkRay.hasCameraFrame;
                        next.cameraOrigin = walkRay.cameraOrigin;
                        next.cameraU = walkRay.cameraU;
                        next.cameraV = walkRay.cameraV;
                        next.cameraW = walkRay.cameraW;
                        walkRay = next;
                    }
                }
            }

            wasSpecular = bss.isDelta;
            throughput = nextThroughput;

            Ray next(rec.point, bss.wi, ray.time, ray.screenU, ray.screenV);
            next.hasCameraFrame = ray.hasCameraFrame;
            next.cameraOrigin = ray.cameraOrigin;
            next.cameraU = ray.cameraU;
            next.cameraV = ray.cameraV;
            next.cameraW = ray.cameraW;
            ray = next;

            weightSum += throughput.maxValue();
            float maxC = throughput.maxValue();
            if (maxC > 10.0f) throughput = throughput * (10.0f / maxC);
        }

        if (outBounces) *outBounces = lastBounce;
        if (outWeight) *outWeight = weightSum;
        if (outCausticConnections) *outCausticConnections = causticConnections;
        if (outCausticEnergy) *outCausticEnergy = causticEnergy;
        return color;
    }

public:
    void addObject(std::shared_ptr<Hittable> obj) {
        scene.push_back(obj);
        if (obj->isLight()) lights.add(obj);
    }

    // pkg89 Phase B: add dedicated Light (not a Hittable).
    void addDedicatedLight(std::unique_ptr<astroray::Light> light) {
        lights.addLight(std::move(light));
    }

    void buildAcceleration() {
        bvh = std::make_shared<BVHAccel>(scene);
        // The Tree light sampler builds and CACHES its light tree in
        // TreeLightSampler's constructor, over whatever lights exist when
        // setLightSampler() is called. Callers routinely select the sampler
        // before adding lights (the Blender addon does this in convert_scene:
        // set_light_sampler('tree') runs before every add_*_light), which would
        // otherwise leave the tree built over an empty light list — pick()
        // returns index -1 / pdf 0, NEE is skipped for every pixel, and the
        // scene renders fully black on the CPU integrator. Rebuild the sampler
        // here (single-threaded, after the full light list is known and before
        // the OpenMP render workers read it) so the tree reflects every light.
        // Power mode reads the light list live, so this rebuild is a no-op cost.
        lights.setSampler(lights.samplerMode());
    }

    // pkg114 — two-level BVH instancing API.
    // Register a mesh's OBJECT-LOCAL primitives once; returns its mesh id. The
    // BLAS is built immediately and reused by every instance of this mesh.
    int registerMesh(const std::vector<std::shared_ptr<Hittable>>& localPrims) {
        int id = static_cast<int>(meshBlas_.size());
        meshPrims_.push_back(localPrims);
        meshBlas_.push_back(std::make_shared<BVHAccel>(localPrims));
        return id;
    }
    // Add an instance of a registered mesh with a row-major 4x4 object->world
    // transform; returns its instance id. Throws if meshId is out of range.
    int addInstance(int meshId, const std::array<float, 16>& transform) {
        if (meshId < 0 || static_cast<size_t>(meshId) >= meshBlas_.size())
            throw std::runtime_error("addInstance: mesh id out of range");
        int id = static_cast<int>(instances_.size());
        instances_.push_back(InstanceRecord{meshId, transform});
        return id;
    }
    // pkg114 inc 3d — replace an existing instance's object->world transform in
    // place (for the transform-only TLAS refit). Geometry/BLAS are untouched.
    void updateInstanceTransform(int instanceId, const std::array<float, 16>& transform) {
        if (instanceId < 0 || static_cast<size_t>(instanceId) >= instances_.size())
            throw std::runtime_error("updateInstanceTransform: instance id out of range");
        instances_[instanceId].transform = transform;
    }
    bool hasInstances() const { return !instances_.empty(); }
    const std::vector<std::shared_ptr<BVHAccel>>& getMeshBlas() const { return meshBlas_; }
    const std::vector<std::vector<std::shared_ptr<Hittable>>>& getMeshPrims() const { return meshPrims_; }
    const std::vector<InstanceRecord>& getInstances() const { return instances_; }

    // pkg88-C.0 — motion blur API. Stores one BATCH of motion vertices and
    // returns a stable pointer to its first element (valid for the renderer's
    // lifetime — see motionVertexBatches_). Triangles index into the batch
    // with motionVertexBuffer + tri*3 arithmetic, so contiguity holds within
    // a batch. Layout per batch: [v0_end, v1_end, v2_end, ...] for 2 steps.
    const Vec3* appendMotionVertices(std::vector<Vec3> motionVerts) {
        motionVertexBatches_.push_back(std::move(motionVerts));
        return motionVertexBatches_.back().data();
    }
    const std::deque<std::vector<Vec3>>& getMotionVertexBatches() const {
        return motionVertexBatches_;
    }

    // Accessors for CUDARenderer (scene_upload.cu reads these to upload scene to GPU)
    const std::vector<std::shared_ptr<Hittable>>& getScene() const { return scene; }
    // pkg56 Phase B: mutable variant used by update_object_transform to mutate
    // an existing primitive in place. Single-level BVH limitation applies —
    // see pkg56 spec "Key design decisions". Direct external mutation requires
    // the caller to rebuild the BVH afterwards (buildAcceleration()).
    std::vector<std::shared_ptr<Hittable>>& getSceneMutable() { return scene; }
    const std::shared_ptr<BVHAccel>& getBVH() const { return bvh; }
    const LightList& getLights() const { return lights; }
    const std::shared_ptr<EnvironmentMap>& getEnvironmentMap() const { return envMap; }
    const Vec3& getBackgroundColor() const { return backgroundColor; }
    float getFilmExposure() const { return filmExposure; }
    bool getUseTransparentFilm() const { return useTransparentFilm; }
    bool getTransparentGlass() const { return transparentGlass; }
    // pkg201 Stage 2 (Finding D) — the GPU wavefront reads these to shape the
    // primary-ray sub-pixel jitter via filter importance sampling at splat time
    // (stage_init.cu::filterSample). 0=Box, 1=Gaussian, 2=Blackman-Harris.
    int getPixelFilterType() const { return pixelFilterType; }
    float getPixelFilterWidth() const { return pixelFilterWidth; }
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
        if (integrator_) {
            integrator_->setMaxDepth(maxDepth);
            integrator_->beginFrame(*this, cam);
        }
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
                        float bounceCountAccum = 0.0f;
                        float sampleWeightAccum = 0.0f;
                        float objectIndex = 0.0f;
                        float materialIndex = 0.0f;
                        // pkg87a: objectSampleCounts/materialSampleCounts removed — old placeholder
                        // cryptomatte logic deleted; pkg87b will add per-shade-point accumulation.
                        float sumL = 0, sumL2 = 0;
                        int samples = 0;
                        // pkg72: remember the s==0 primary ray so we can recover
                        // the world-space hit point for the motion-vector write
                        // below. Mirrors Cycles intern/cycles/integrator/pass.cpp
                        // PASS_MOTION (Apache-2.0) which uses the first-sample
                        // primary ray's hit position.
                        Ray firstPrimaryRay;
                        float firstPixelCurrX = 0.0f, firstPixelCurrY = 0.0f;
                        bool firstRayCaptured = false;

                        for (int s = 0; s < maxSamples; ++s) {
                            float u = (x + filterSample(gen, dist)) / (cam.width - 1);
                            float v = 1.0f - (y + filterSample(gen, dist)) / (cam.height - 1);

                            // pkg88-A: sample time from Halton dimension 8 (independent per spp).
                            // Per spec Q-Owner-4, we use independent Halton (not stratified)
                            // for consistency between megakernel and wavefront paths.
                            float time = halton(s + 1, 2);  // base-2 Halton for dim 8

                            Vec3 sAlb, sNorm, sPosition(0), sUv(0);
                            std::array<Vec3, PASS_COUNT> sPass;
                            sPass.fill(Vec3(0));
                            float sAlpha = 1.0f;
                            float sDepth = 0.0f;
                            float sBounceCount = 0.0f;
                            float sSampleWeight = 0.0f;
                            int sObjectIndex = 0;
                            int sMaterialIndex = 0;
                            Vec3 sCol;
                            // pkg72: materialise the primary ray so the motion-vector write
                            // below can recover the world-space hit point (origin + dir*depth)
                            // even for integrators that don't populate SampleResult.position.
                            // pkg88-A: pass sampled time to getRay (signature change per spec Q10).
                            Ray primaryRay = cam.getRay(u, v, time, gen);
                            if (s == 0) {
                                firstPrimaryRay = primaryRay;
                                // pkg72: use the jittered pixel coordinate as
                                // pixel_curr so static-camera motion is exactly
                                // zero (the projected hit point lands back on
                                // the same sub-pixel). The render loop maps
                                // pixel(x,y) -> u=x/(W-1), v=1-y/(H-1).
                                firstPixelCurrX = u * float(cam.width - 1);
                                firstPixelCurrY = (1.0f - v) * float(cam.height - 1);
                                firstRayCaptured = true;
                            }
                            if (integrator_) {
                                SampleResult ir = integrator_->sampleFull(primaryRay, gen);
                                sCol = ir.color;
                                sAlb = ir.albedo;
                                sNorm = ir.normal;
                                sAlpha = ir.alpha;
                                sDepth = ir.depth;
                                sBounceCount = ir.bounceCount;
                                sSampleWeight = ir.sampleWeight;
                                sPosition = ir.position;
                                sUv = ir.uv;
                                sObjectIndex = ir.objectIndex;
                                sMaterialIndex = ir.materialIndex;
                                sPass = ir.passes;
                            }
                            sCol = finiteVecOrZero(sCol);
                            // pkg144: the always-on, direct+indirect-combined `sLum > 20`
                            // top-level clamp that used to live here has been REMOVED. It
                            // biased delta-light NEE (deterministic, zero-variance contributions
                            // have no fireflies to suppress) and could not distinguish direct
                            // from indirect contributions. Firefly control is now applied
                            // per-contribution, by bounce depth, inside the integrator itself
                            // (Renderer::clampContribSpectral, wired into pathTraceSpectral /
                            // pathTraceSpectralCaustic) — see clampDirect/clampIndirect.
                            color += sCol;
                            for (int passIndex = 0; passIndex < PASS_COUNT; ++passIndex) {
                                passColor[passIndex] += sPass[passIndex];
                            }
                            alpha += sAlpha;
                            bounceCountAccum += sBounceCount;
                            sampleWeightAccum += sSampleWeight;
                            samples++;
                            // pkg87a: objectSampleCounts/materialSampleCounts removed (see above)
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
                        // pkg198 Stage 1: the light-path passes carry XYZ radiance (same
                        // convention as beauty pre-conversion). Convert them to linear
                        // sRGB with the SAME matrix as beauty (below) so the sum-to-beauty
                        // invariant Σpasses == beauty holds in linear sRGB. pkg199 Stage 2:
                        // the volume passes now carry in-scatter radiance and join the
                        // conversion; COLOR/AO/SHADOW stay zero.
                        for (int passIndex : {PASS_DIFFUSE_DIRECT, PASS_DIFFUSE_INDIRECT,
                                              PASS_GLOSSY_DIRECT, PASS_GLOSSY_INDIRECT,
                                              PASS_TRANSMISSION_DIRECT, PASS_TRANSMISSION_INDIRECT,
                                              PASS_VOLUME_DIRECT, PASS_VOLUME_INDIRECT,
                                              PASS_EMISSION, PASS_ENVIRONMENT}) {
                            passColor[passIndex] = xyzToLinearSRGB(passColor[passIndex]);
                        }
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
                        cam.bounceCountBuffer[idx] = bounceCountAccum / float(samples);
                        cam.sampleWeightBuffer[idx] = sampleWeightAccum / float(samples);
                        cam.alphaBuffer[idx] = std::clamp(alpha, 0.0f, 1.0f);
                        // pkg72: motion vector (previous->current screen-space pixel
                        // offset, OptiX flow convention: motion = prev - curr).
                        // Camera-only motion: animated geometry is out of scope per
                        // the pkg72 spec. See Cycles intern/cycles/integrator/pass.cpp
                        // PASS_MOTION (Apache-2.0) for the buffer-shape we mirror.
                        // Sky pixels (depth==0), behind-prev-camera, and the first
                        // frame (no previous camera) all store (0, 0).
                        float motionX = 0.0f, motionY = 0.0f;
                        if (cam.hasPrevCamera && firstRayCaptured && depth > 0.0f) {
                            const Vec3 P = firstPrimaryRay.origin + firstPrimaryRay.direction * depth;
                            float pxPrev = 0.0f, pyPrev = 0.0f;
                            if (cam.projectToPrevPixel(P, pxPrev, pyPrev)) {
                                motionX = pxPrev - firstPixelCurrX;
                                motionY = pyPrev - firstPixelCurrY;
                                if (!std::isfinite(motionX) || !std::isfinite(motionY)) {
                                    motionX = 0.0f; motionY = 0.0f;
                                }
                            }
                        }
                        cam.motionBuffer[2 * idx + 0] = motionX;
                        cam.motionBuffer[2 * idx + 1] = motionY;
                        // pkg87a: old cryptomatte write code removed — buffers refactored to
                        // flat float arrays. pkg87b will add per-shade-point accumulation.
                        // Crypto buffers remain zero-filled until then.
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
        // pkg72: capture this frame's projection state for the next render
        // call's motion-vector computation. See Camera::snapshotForMotion().
        cam.snapshotForMotion();
}

inline void Renderer::applyPasses(Camera& cam) {
    if (passes_.empty()) return;
    Framebuffer fb(cam);
    for (auto& pass : passes_)
        pass->execute(fb);
}

inline void Renderer::setIntegrator(std::shared_ptr<Integrator> i) {
    integrator_ = std::move(i);
}

inline std::unordered_map<std::string, float> Renderer::integratorDebugStats() const {
    return integrator_ ? integrator_->debugStats() : std::unordered_map<std::string, float>{};
}

#pragma once

#include <cmath>
#include <vector>
#include <memory>
#include <random>
#include <limits>
#include <algorithm>
#include <atomic>
#include <functional>
#include "stb_image.h"

// Forward declaration needed by HitRecord
class Hittable;

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

inline void buildOrthonormalBasis(const Vec3& n, Vec3& u, Vec3& v) {
    u = (std::abs(n.x) > 0.9f) ? Vec3(0, 1, 0) : Vec3(1, 0, 0);
    u = (u - n * n.dot(u)).normalized();
    v = n.cross(u);
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
    Ray() : time(0) {}
    Ray(const Vec3& o, const Vec3& d, float t = 0) : origin(o), direction(d.normalized()), time(t) {}
    Vec3 at(float t) const { return origin + direction * t; }
};

class Material;

struct HitRecord {
    Vec3 point, normal, tangent, bitangent;
    float t;
    bool frontFace;
    Vec2 uv;
    std::shared_ptr<Material> material;
    bool isDelta;
    const Hittable* hitObject = nullptr;  // set by hit() for GR dispatch

    HitRecord() : t(std::numeric_limits<float>::max()), frontFace(true), isDelta(false), hitObject(nullptr) {}
    
    void setFaceNormal(const Ray& r, const Vec3& outwardNormal) {
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
    virtual Vec3 eval(const HitRecord& rec, const Vec3& wo, const Vec3& wi) const { return Vec3(0); }
    virtual BSDFSample sample(const HitRecord& rec, const Vec3& wo, std::mt19937& gen) const { return BSDFSample{Vec3(0,1,0), Vec3(0), 0, false}; }
    virtual float pdf(const HitRecord& rec, const Vec3& wo, const Vec3& wi) const { return 0; }
    virtual Vec3 emitted(const HitRecord& rec) const { return Vec3(0); }
};

class Lambertian : public Material {
    Vec3 albedo;
public:
    Lambertian(const Vec3& a) : albedo(a) {}
    Vec3  getAlbedo()    const { return albedo; }
    
    Vec3 eval(const HitRecord& rec, const Vec3& wo, const Vec3& wi) const override {
        return (wi.dot(rec.normal) <= 0) ? Vec3(0) : albedo / M_PI * wi.dot(rec.normal);
    }
    
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
};

// FIX: Metal - minimum roughness 0.001f to prevent black appearance
class Metal : public Material {
    Vec3 albedo;
    float roughness;
    
    Vec3 fresnelSchlick(float cosTheta, const Vec3& F0) const {
        float c = std::clamp(cosTheta, 0.0f, 1.0f);
        return F0 + (Vec3(1) - F0) * std::pow(1 - c, 5);
    }
    
public:
    Metal(const Vec3& a, float r = 0) : albedo(a), roughness(std::clamp(r, 0.001f, 1.0f)) {}
    Vec3  getAlbedo()    const { return albedo; }
    float getRoughness() const { return roughness; }
    
    Vec3 eval(const HitRecord& rec, const Vec3& wo, const Vec3& wi) const override {
        if (roughness < 0.08f) {
            Vec3 perfectRefl = rec.normal * (2 * wo.dot(rec.normal)) - wo;
            float deviation = (wi - perfectRefl).length();
            return (deviation < 0.1f) ? albedo * std::exp(-deviation * 100.0f) : Vec3(0);
        }

        float rawNdotL = rec.normal.dot(wi);
        float rawNdotV = rec.normal.dot(wo);
        if (rawNdotL <= 0 || rawNdotV <= 0) return Vec3(0);

        Vec3 h = (wo + wi).normalized();
        float NdotH = std::max(rec.normal.dot(h), 0.001f);
        float NdotL = rawNdotL;
        float NdotV = rawNdotV;

        float a = roughness * roughness, a2 = a * a;
        float denom = NdotH * NdotH * (a2 - 1) + 1;
        float D = a2 / (M_PI * denom * denom + 0.001f);
        Vec3 F = fresnelSchlick(wo.dot(h), albedo);
        float k = (roughness + 1) * (roughness + 1) / 8;
        float G = (NdotL / (NdotL * (1 - k) + k)) * (NdotV / (NdotV * (1 - k) + k));
        return F * D * G / (4 * NdotV + 0.001f);
    }
    
    BSDFSample sample(const HitRecord& rec, const Vec3& wo, std::mt19937& gen) const override {
        BSDFSample s;
        if (roughness < 0.08f) {
            // Correct reflection: wi = 2*(wo·n)*n - wo
            s.wi = rec.normal * (2 * wo.dot(rec.normal)) - wo;
            s.f = albedo;
            s.pdf = 1;
            s.isDelta = true;
            const_cast<HitRecord&>(rec).isDelta = true;
        } else {
            std::uniform_real_distribution<float> dist(0, 1);
            float a = roughness * roughness;
            float phi = 2 * M_PI * dist(gen);
            float cosTheta = std::sqrt((1 - dist(gen)) / (1 + (a*a - 1) * dist(gen)));
            float sinTheta = std::sqrt(1 - cosTheta * cosTheta);
            Vec3 h(std::cos(phi) * sinTheta, std::sin(phi) * sinTheta, cosTheta);
            h = rec.tangent * h.x + rec.bitangent * h.y + rec.normal * h.z;
            s.wi = (h * (2 * wo.dot(h)) - wo).normalized();
            s.f = Vec3(0);
            s.pdf = 0.0f;
            if (s.wi.dot(rec.normal) > 0) {
                s.f = eval(rec, wo, s.wi);
                float NdotH = std::max(rec.normal.dot(h), 0.001f);
                float HdotV = std::max(h.dot(wo), 0.001f);
                float a2 = a * a, denom = NdotH * NdotH * (a2 - 1) + 1;
                // Use same D formula as eval() so f/pdf = F*G*HdotV/(NdotV*NdotH)
                float D = a2 / (M_PI * denom * denom + 0.001f);
                s.pdf = D * NdotH / (4.0f * HdotV);
            }
            s.isDelta = false;
        }
        return s;
    }
    
    float pdf(const HitRecord& rec, const Vec3& wo, const Vec3& wi) const override {
        if (roughness < 0.08f) return 0;
        Vec3 h = (wo + wi).normalized();
        float NdotH = std::max(rec.normal.dot(h), 0.001f);
        float HdotV = std::max(h.dot(wo), 0.001f);
        float a = roughness * roughness, a2 = a * a;
        float denom = NdotH * NdotH * (a2 - 1) + 1;
        float D = a2 / (M_PI * denom * denom + 0.001f);
        return D * NdotH / (4.0f * HdotV);
    }
};

class Dielectric : public Material {
    float ior;
    
    float fresnelDielectric(float cosThetaI, float etaI, float etaT) const {
        cosThetaI = std::clamp(cosThetaI, -1.0f, 1.0f);
        bool entering = cosThetaI > 0;
        if (!entering) { std::swap(etaI, etaT); cosThetaI = std::abs(cosThetaI); }
        float sinThetaI = std::sqrt(std::max(0.0f, 1 - cosThetaI * cosThetaI));
        float sinThetaT = etaI / etaT * sinThetaI;
        if (sinThetaT >= 1) return 1;
        float cosThetaT = std::sqrt(std::max(0.0f, 1 - sinThetaT * sinThetaT));
        float Rparl = ((etaT * cosThetaI) - (etaI * cosThetaT)) / ((etaT * cosThetaI) + (etaI * cosThetaT));
        float Rperp = ((etaI * cosThetaI) - (etaT * cosThetaT)) / ((etaI * cosThetaI) + (etaT * cosThetaT));
        return (Rparl * Rparl + Rperp * Rperp) / 2;
    }
    
public:
    Dielectric(float indexOfRefraction) : ior(indexOfRefraction) {}
    float getIOR() const { return ior; }
    
    BSDFSample sample(const HitRecord& rec, const Vec3& wo, std::mt19937& gen) const override {
        BSDFSample s;
        s.isDelta = true;
        const_cast<HitRecord&>(rec).isDelta = true;
        
        float cosTheta = wo.dot(rec.normal);
        float etaI = 1, etaT = ior;
        Vec3 n = rec.normal;
        if (cosTheta < 0) { cosTheta = -cosTheta; std::swap(etaI, etaT); n = -n; }
        
        float eta = etaI / etaT;
        float sinTheta = std::sqrt(std::max(0.0f, 1 - cosTheta * cosTheta));
        bool cannotRefract = eta * sinTheta > 1;
        
        std::uniform_real_distribution<float> dist(0, 1);
        float fresnel = fresnelDielectric(cosTheta, etaI, etaT);
        
        if (cannotRefract || dist(gen) < fresnel) {
            // Correct reflection: wi = 2*(wo·n)*n - wo
            s.wi = n * (2 * wo.dot(n)) - wo;
            s.f = Vec3(1);
            s.pdf = 1.0f;  // stochastic selection already weights by fresnel
        } else {
            Vec3 wt_perp = (wo - n * cosTheta) * (-eta);
            Vec3 wt_parallel = n * (-std::sqrt(std::abs(1 - wt_perp.length2())));
            s.wi = (wt_perp + wt_parallel).normalized();
            s.f = Vec3(eta * eta);
            s.pdf = 1.0f;  // stochastic selection already weights by (1-fresnel)
        }
        return s;
    }
};

class DiffuseLight : public Material {
    Vec3 color;
    float intensity;
public:
    DiffuseLight(const Vec3& c, float i = 1.0f) : color(c), intensity(i) {}
    Vec3 emitted(const HitRecord& rec) const override { return rec.frontFace ? color * intensity : Vec3(0); }
    Vec3  getEmission()  const { return color * intensity; }
    Vec3  getColor()     const { return color; }
    float getIntensity() const { return intensity; }
};

// ============================================================================
// GEOMETRY
// ============================================================================

class Hittable {
public:
    // Result type used by GR objects (BlackHole).  Defined here so that
    // pathTrace() can use it without needing a full BlackHole definition.
    struct GRResult {
        Vec3 color;            // accumulated spectral emission (linear RGB)
        Vec3 exitDirection;    // world-space exit direction
        bool captured;         // absorbed by horizon
        bool hasEmission;      // disk was hit
    };

    virtual ~Hittable() = default;
    virtual bool hit(const Ray& r, float tMin, float tMax, HitRecord& rec) const = 0;
    virtual bool boundingBox(AABB& box) const = 0;
    virtual float pdfValue(const Vec3& origin, const Vec3& direction) const { return 0; }
    virtual Vec3 random(const Vec3& origin, std::mt19937& gen) const { return Vec3(0, 1, 0); }
    virtual bool isLight() const { return false; }
    virtual Vec3 emittedRadiance() const { return Vec3(0); }
    // GR dispatch — BlackHole overrides both
    virtual bool isGRObject() const { return false; }
    virtual GRResult traceGR(const Ray& /*r*/, std::mt19937& /*gen*/) const {
        return {Vec3(0), Vec3(0, 0, 1), true, false};
    }
};

class Sphere : public Hittable {
    Vec3 center;
    float radius;
    std::shared_ptr<Material> material;
    bool emissive;
public:
    Sphere(const Vec3& c, float r, std::shared_ptr<Material> m) 
        : center(c), radius(r), material(m), emissive(dynamic_cast<DiffuseLight*>(m.get()) != nullptr) {}
    
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
        Vec3 outwardNormal = (rec.point - center) / radius;
        rec.setFaceNormal(r, outwardNormal);
        rec.material = material;
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
        if (auto l = dynamic_cast<DiffuseLight*>(material.get())) return l->getEmission();
        return Vec3(0);
    }
    // Accessors for GPU upload
    Vec3  getCenter()   const { return center; }
    float getRadius()   const { return radius; }
    const std::shared_ptr<Material>& getMaterial() const { return material; }
};

class Triangle : public Hittable {
    Vec3 v0, v1, v2, normal;
    Vec2 uv0, uv1, uv2;
    std::shared_ptr<Material> material;
    bool emissive;
public:
    Triangle(const Vec3& a, const Vec3& b, const Vec3& c, std::shared_ptr<Material> m)
        : v0(a), v1(b), v2(c), material(m), uv0(0,0), uv1(1,0), uv2(0,1),
          emissive(dynamic_cast<DiffuseLight*>(m.get()) != nullptr) {
        normal = (v1 - v0).cross(v2 - v0).normalized();
    }
    
    Triangle(const Vec3& a, const Vec3& b, const Vec3& c, const Vec2& t0, const Vec2& t1, const Vec2& t2, std::shared_ptr<Material> m)
        : v0(a), v1(b), v2(c), uv0(t0), uv1(t1), uv2(t2), material(m),
          emissive(dynamic_cast<DiffuseLight*>(m.get()) != nullptr) {
        normal = (v1 - v0).cross(v2 - v0).normalized();
    }
    
    bool hit(const Ray& r, float tMin, float tMax, HitRecord& rec) const override {
        const float EPS = 1e-6f;
        Vec3 e1 = v1 - v0, e2 = v2 - v0;
        Vec3 h = r.direction.cross(e2);
        float a = e1.dot(h);
        if (std::fabs(a) < EPS) return false;
        float f = 1.0f / a;
        Vec3 s = r.origin - v0;
        float u = f * s.dot(h);
        if (u < 0 || u > 1) return false;
        Vec3 q = s.cross(e1);
        float v = f * r.direction.dot(q);
        if (v < 0 || u + v > 1) return false;
        float t = f * e2.dot(q);
        if (t < tMin || t > tMax) return false;
        rec.t = t;
        rec.point = r.at(t);
        rec.setFaceNormal(r, normal);
        rec.material = material;
        float w = 1 - u - v;
        rec.uv = uv0 * w + uv1 * u + uv2 * v;
        return true;
    }
    
    bool boundingBox(AABB& box) const override {
        Vec3 minP = Vec3::min(Vec3::min(v0, v1), v2);
        Vec3 maxP = Vec3::max(Vec3::max(v0, v1), v2);
        box = AABB(minP - Vec3(0.0001f), maxP + Vec3(0.0001f));
        return true;
    }
    
    float pdfValue(const Vec3& origin, const Vec3& direction) const override {
        HitRecord rec;
        if (!hit(Ray(origin, direction), 0.001f, std::numeric_limits<float>::max(), rec)) return 0;
        float area = (v1 - v0).cross(v2 - v0).length() * 0.5f;
        return rec.t * rec.t / (std::abs(direction.dot(rec.normal)) * area + 0.001f);
    }
    
    Vec3 random(const Vec3& origin, std::mt19937& gen) const override {
        std::uniform_real_distribution<float> dist(0, 1);
        float r1 = dist(gen), r2 = dist(gen);
        if (r1 + r2 > 1) { r1 = 1 - r1; r2 = 1 - r2; }
        return ((v0 + (v1 - v0) * r1 + (v2 - v0) * r2) - origin).normalized();
    }
    
    bool isLight() const override { return emissive; }
    Vec3 emittedRadiance() const override {
        if (auto l = dynamic_cast<DiffuseLight*>(material.get())) return l->getEmission();
        return Vec3(0);
    }
    // Accessors for GPU upload
    Vec3 getV0() const { return v0; }
    Vec3 getV1() const { return v1; }
    Vec3 getV2() const { return v2; }
    Vec3 getFaceNormal() const { return normal; }
    const std::shared_ptr<Material>& getMaterial() const { return material; }
};

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

    // Accessors for scene_upload.cu — read the flat BVH and ordered primitive list
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
        AABB b; l->boundingBox(b);
        power *= b.area();
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
            s.position = rec.point; s.normal = rec.normal; s.emission = lights[idx]->emittedRadiance();
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
    
    // CDF data for importance sampling
    std::vector<float> conditionalCdf;  // size: width * height (CDF per row)
    std::vector<float> conditionalFunc; // size: width * height (un-normalized PDF per row)
    std::vector<float> marginalCdf;     // size: height
    std::vector<float> marginalFunc;    // size: height (row totals)
    float totalPower = 0.0f;

public:
    bool loaded() const { return !data.empty(); }

    bool load(const std::string& path, float str = 1.0f, float rot = 0.0f) {
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
        printf("Loaded environment map: %s (%dx%d)\n", path.c_str(), width, height);
        buildCdf();
        return true;
    }
    
    Vec3 lookup(const Vec3& direction) const {
        if (width == 0 || height == 0) return Vec3(0);
        
        // Convert direction to equirectangular (u, v) coordinates:
        float theta = std::acos(std::clamp(direction.y, -1.0f, 1.0f)); // polar, 0=up
        float phi = std::atan2(direction.z, direction.x);                // azimuthal
        phi += rotation;  // apply horizontal rotation
        float u = 0.5f + phi / (2.0f * M_PI);  // [0, 1]
        float v = 1.0f - theta / M_PI;          // [0, 1], flipped: y=+1 (up) → row height-1

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
        
        // Convert direction to equirectangular coordinates
        float theta = std::acos(std::clamp(direction.y, -1.0f, 1.0f));
        float phi = std::atan2(direction.z, direction.x);
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

class Camera {
    Vec3 origin, lowerLeft, horizontal, vertical, u, v, w_axis;
    float lensRadius;
public:
    int width, height;
    std::vector<Vec3> pixels, albedoBuffer, normalBuffer;

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
    }
    
    Ray getRay(float s, float t, std::mt19937& gen) const {
        Vec3 rd = Vec3::randomInUnitDisk(gen) * lensRadius;
        Vec3 offset = u * rd.x + v * rd.y;
        return Ray(origin + offset, lowerLeft + horizontal * s + vertical * t - origin - offset);
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

// ============================================================================
// RENDERER WITH NEE AND MIS - FIX: Proper emission handling
// ============================================================================

class Renderer {
    std::vector<std::shared_ptr<Hittable>> scene;
    std::shared_ptr<BVHAccel> bvh;
    LightList lights;
    std::shared_ptr<EnvironmentMap> envMap;
    Vec3 backgroundColor = Vec3(-1);  // negative = use default sky gradient
    
public:
    void setEnvironmentMap(std::shared_ptr<EnvironmentMap> map) { envMap = map; }
    void setBackgroundColor(const Vec3& color) { backgroundColor = color; }
    
    void clear() {
        scene.clear(); bvh.reset(); lights = LightList();
        envMap.reset();
        backgroundColor = Vec3(-1);
    }
    
    float powerHeuristic(float a, float b) const {
        float a2 = a*a, b2 = b*b;
        float denom = a2 + b2;
        if (denom < 1e-8f) return 0.5f;
        return a2 / denom;
    }

    float envSelectProb() const {
        if (!envMap || !envMap->loaded()) return 0.0f;
        if (lights.empty()) return 1.0f;
        // Heuristic: environment gets 50% selection probability
        return 0.5f;
    }

    Vec3 sampleDirect(const HitRecord& rec, const Ray& ray, std::mt19937& gen) {
        if ((lights.empty() && (!envMap || !envMap->loaded())) || rec.isDelta) return Vec3(0);
        Vec3 wo = -ray.direction.normalized(), direct(0);
        std::uniform_real_distribution<float> dist01(0, 1);

        float pEnv = envSelectProb();
        bool sampleEnv = dist01(gen) < pEnv;

        if (sampleEnv && envMap && envMap->loaded()) {
            // === Environment map light sampling ===
            auto es = envMap->sample(gen);
            if (es.pdf > 0) {
                Vec3 wi = es.direction;
                HitRecord shadow;
                // Shadow ray: must NOT hit any geometry (ray escapes to infinity)
                if (!bvh->hit(Ray(rec.point, wi), 0.001f, 1e30f, shadow)) {
                    Vec3 f = rec.material->eval(rec, wo, wi);
                    float bsdfPdf = rec.material->pdf(rec, wo, wi);
                    float combinedLightPdf = pEnv * es.pdf;
                    float wt = powerHeuristic(combinedLightPdf, bsdfPdf);
                    direct += f * es.radiance * wt / (combinedLightPdf + 0.001f);
                }
            }
        } else if (!lights.empty()) {
            // === Existing area light sampling ===
            float pArea = 1.0f - pEnv;
            LightSample ls = lights.sample(rec.point, gen);
            if (ls.pdf > 0) {
                Vec3 wi = (ls.position - rec.point).normalized();
                HitRecord shadow;
                if (!bvh->hit(Ray(rec.point, wi), 0.001f, ls.distance - 0.001f, shadow)) {
                    Vec3 f = rec.material->eval(rec, wo, wi);
                    float bsdfPdf = rec.material->pdf(rec, wo, wi);
                    float combinedLightPdf = pArea * ls.pdf;
                    float wt = powerHeuristic(combinedLightPdf, bsdfPdf);
                    direct += f * ls.emission * wt / (combinedLightPdf + 0.001f);
                }
            }
        }

        // === BSDF sampling (check both area lights AND environment) ===
        BSDFSample bs = rec.material->sample(rec, wo, gen);
        if (bs.pdf > 0 && !bs.isDelta) {
            HitRecord bRec;
            if (bvh->hit(Ray(rec.point, bs.wi), 0.001f, 1e30f, bRec)) {
                // Hit geometry — check if it's an emissive light.
                // GR objects (BlackHole) do not set rec.material in hit(); they
                // are handled by the path-tracer's GR branch, never as NEE
                // light targets, so skip them safely here to avoid a NULL deref.
                if (bRec.material) {
                    Vec3 Le = bRec.material->emitted(bRec);
                    if (Le != Vec3(0)) {
                        float lightPdf = (1.0f - pEnv) * lights.pdfValue(rec.point, bs.wi);
                        direct += bs.f * Le * powerHeuristic(bs.pdf, lightPdf) / (bs.pdf + 0.001f);
                    }
                }
            } else {
                // Miss — hit the environment map
                if (envMap && envMap->loaded()) {
                    Vec3 Le = envMap->lookup(bs.wi.normalized());
                    float lightPdf = pEnv * envMap->pdf(bs.wi.normalized());
                    direct += bs.f * Le * powerHeuristic(bs.pdf, lightPdf) / (bs.pdf + 0.001f);
                }
            }
        }

        return direct;
    }
    
Vec3 pathTrace(const Ray& r, int maxDepth, std::mt19937& gen,
                   Vec3* albOut = nullptr, Vec3* normOut = nullptr) {
        const int rrDepth = 3;
        Vec3 color(0), throughput(1);
        Ray ray = r;
        bool wasSpecular = true;

        for (int bounce = 0; bounce < maxDepth; ++bounce) {
            HitRecord rec;
            if (!bvh->hit(ray, 0.001f, std::numeric_limits<float>::max(), rec)) {
                Vec3 envColor;
                if (envMap && envMap->loaded()) {
                    envColor = envMap->lookup(ray.direction.normalized());
                } else if (backgroundColor.x >= 0) {
                    envColor = backgroundColor;
                } else {
                    float t = 0.5f * (ray.direction.normalized().y + 1.0f);
                    envColor = (Vec3(1) * (1 - t) + Vec3(0.5f, 0.7f, 1.0f) * t) * 0.2f;
                }
                if (bounce == 0 || wasSpecular) {
                    color += throughput * envColor;
                }
                break;
            }

            // --- GR dispatch via virtual call (no RTTI needed) ---
            if (rec.hitObject && rec.hitObject->isGRObject()) {
                auto grResult = rec.hitObject->traceGR(ray, gen);

                if (bounce == 0 && normOut) *normOut = rec.normal * 0.5f + Vec3(0.5f);

                if (grResult.hasEmission) {
                    color += throughput * grResult.color;
                }
                if (grResult.captured) {
                    break;
                }
                // Sanitize exit direction: any NaN/Inf or zero-length vector
                // collapses the geodesic into a "captured" outcome rather than
                // poisoning BVH traversal with a malformed ray.
                Vec3 exitDir = grResult.exitDirection;
                float exitLen2 = exitDir.length2();
                if (!std::isfinite(exitDir.x) || !std::isfinite(exitDir.y) ||
                    !std::isfinite(exitDir.z) || !std::isfinite(exitLen2) ||
                    exitLen2 < 1e-10f) {
                    break;
                }
                ray = Ray(rec.point, exitDir, ray.time);
                wasSpecular = true;
                continue;
            }

            // --- Normal path tracing ---
            if (!rec.material) break;  // safety guard
            if (bounce == 0) {
                if (albOut) { if (auto l = dynamic_cast<Lambertian*>(rec.material.get())) *albOut = l->getAlbedo(); else *albOut = Vec3(0.5f); }
                if (normOut) *normOut = rec.normal * 0.5f + Vec3(0.5f);
            }
            Vec3 emitted = rec.material->emitted(rec);
            if (emitted != Vec3(0)) {
                if (bounce == 0 || wasSpecular) color += throughput * emitted;
                break;
            }
            if (!rec.isDelta) color += throughput * sampleDirect(rec, ray, gen);
            if (bounce > rrDepth) {
                float p = std::min(0.95f, luminance(throughput));
                if (std::uniform_real_distribution<float>(0, 1)(gen) > p) break;
                throughput /= p;
            }
            Vec3 wo = -ray.direction.normalized();
            BSDFSample bs = rec.material->sample(rec, wo, gen);
            if (bs.pdf <= 0) break;
            wasSpecular = bs.isDelta;
            throughput *= bs.f / (bs.pdf + 0.001f);
            ray = Ray(rec.point, bs.wi, ray.time);
            float maxC = throughput.maxComponent();
            if (maxC > 10.0f) throughput *= 10.0f / maxC;
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

void render(Camera& cam, int maxSamples, int maxDepth, std::function<void(float)> progress = nullptr, bool adaptive = true) {
        buildAcceleration();
        std::atomic<int> tilesCompleted{0};
        const int tileSize = 16;
        int tilesX = (cam.width + tileSize - 1) / tileSize;
        int tilesY = (cam.height + tileSize - 1) / tileSize;
        int totalTiles = tilesX * tilesY;
        
        #pragma omp parallel for schedule(dynamic) collapse(2)
        for (int tileY = 0; tileY < tilesY; ++tileY) {
            for (int tileX = 0; tileX < tilesX; ++tileX) {
                std::mt19937 gen(std::random_device{}() + tileY * tilesX + tileX);
                std::uniform_real_distribution<float> dist(0, 1);
                int x0 = tileX * tileSize, x1 = std::min(x0 + tileSize, cam.width);
                int y0 = tileY * tileSize, y1 = std::min(y0 + tileSize, cam.height);
                
                for (int y = y0; y < y1; ++y) {
                    for (int x = x0; x < x1; ++x) {
                        int idx = y * cam.width + x;
                        Vec3 color(0), albedo(0), normal(0);
                        float sumL = 0, sumL2 = 0;
                        int samples = 0;
                        
                        for (int s = 0; s < maxSamples; ++s) {
                            float u = (x + dist(gen)) / (cam.width - 1);
                            float v = 1.0f - (y + dist(gen)) / (cam.height - 1);
                            Vec3 sAlb, sNorm;
                            Vec3 sCol = pathTrace(cam.getRay(u, v, gen), maxDepth, gen, s == 0 ? &sAlb : nullptr, s == 0 ? &sNorm : nullptr);
                            // Per-sample contribution clamp: prevents a single caustic spike from
                            // dominating a pixel when sample count is low (firefly suppression)
                            float sLum = luminance(sCol);
                            if (sLum > 20.0f) sCol = sCol * (20.0f / sLum);
                            color += sCol;
                            samples++;
                            if (s == 0) { albedo = sAlb; normal = sNorm; }
                            if (adaptive && s >= 16 && (s + 1) % 8 == 0) {
                                float l = luminance(sCol);
                                sumL += l; sumL2 += l * l;
                                float mean = sumL / (s - 15);
                                float var = (sumL2 / (s - 15)) - mean * mean;
                                if (std::sqrt(std::max(0.0f, var)) / (mean + 0.01f) < 0.01f) break;
                            }
                        }
                        
                        color = color / float(samples);
                        color.x = std::pow(std::clamp(color.x, 0.0f, 1.0f), 1.0f / 2.2f);
                        color.y = std::pow(std::clamp(color.y, 0.0f, 1.0f), 1.0f / 2.2f);
                        color.z = std::pow(std::clamp(color.z, 0.0f, 1.0f), 1.0f / 2.2f);
                        cam.pixels[idx] = color;
                        cam.albedoBuffer[idx] = albedo;
                        cam.normalBuffer[idx] = normal;
                    }
                }
                
                if (progress) progress(float(++tilesCompleted) / totalTiles);
            }
        }
    }
};

// ============================================================================
// BlackHole definition — included after Renderer so Hittable::GRResult is defined.
// black_hole.h overrides Hittable::traceGR() using virtual dispatch — no cast needed.
// ============================================================================
#include "astroray/black_hole.h"

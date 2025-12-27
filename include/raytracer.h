#pragma once

#include <cmath>
#include <vector>
#include <memory>
#include <random>
#include <limits>
#include <algorithm>
#include <atomic>
#include <functional>
#include <mutex>
#include <immintrin.h> // For SIMD

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
    
    float dot(const Vec3& o) const { return x*o.x + y*o.y + z*o.z; }
    Vec3 cross(const Vec3& o) const { 
        return Vec3(y*o.z - z*o.y, z*o.x - x*o.z, x*o.y - y*o.x); 
    }
    
    float length2() const { return dot(*this); }
    float length() const { return std::sqrt(length2()); }
    Vec3 normalized() const { 
        float len = length(); 
        return len > 0 ? *this / len : Vec3(0); 
    }
    
    float& operator[](int i) { return (&x)[i]; }
    const float& operator[](int i) const { return (&x)[i]; }
    
    float maxComponent() const { return std::max({x, y, z}); }
    float minComponent() const { return std::min({x, y, z}); }
    
    static Vec3 min(const Vec3& a, const Vec3& b) {
        return Vec3(std::min(a.x, b.x), std::min(a.y, b.y), std::min(a.z, b.z));
    }
    
    static Vec3 max(const Vec3& a, const Vec3& b) {
        return Vec3(std::max(a.x, b.x), std::max(a.y, b.y), std::max(a.z, b.z));
    }
    
    static Vec3 randomUnit(std::mt19937& gen) {
        std::uniform_real_distribution<float> dist(0, 1);
        float z = 2 * dist(gen) - 1;
        float r = std::sqrt(std::max(0.0f, 1.0f - z * z));
        float phi = 2 * M_PI * dist(gen);
        return Vec3(r * std::cos(phi), r * std::sin(phi), z);
    }
    
    static Vec3 randomUnitSphere(std::mt19937& gen) {
        std::uniform_real_distribution<float> dist(-1.0f, 1.0f);
        Vec3 p;
        do {
            p = Vec3(dist(gen), dist(gen), dist(gen));
        } while (p.length2() >= 1.0f);
        return p.normalized();
    }
    
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
        do {
            p = Vec3(dist(gen), dist(gen), 0);
        } while (p.length2() >= 1);
        return p;
    }
    
    // Inequality operator
    bool operator!=(const Vec3& other) const {
        return x != other.x || y != other.y || z != other.z;
    }
    
    // Division assignment operator
    Vec3& operator/=(float scalar) {
        x /= scalar;
        y /= scalar;
        z /= scalar;
        return *this;
    }
};

inline Vec3 operator*(float s, const Vec3& v) { return v * s; }

inline float luminance(const Vec3& color) {
    return 0.2126f * color.x + 0.7152f * color.y + 0.0722f * color.z;
}

// Coordinate system from normal
inline void buildOrthonormalBasis(const Vec3& n, Vec3& u, Vec3& v) {
    if (std::abs(n.x) > 0.9f) {
        u = Vec3(0, 1, 0);
    } else {
        u = Vec3(1, 0, 0);
    }
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
    Ray(const Vec3& o, const Vec3& d, float t = 0) 
        : origin(o), direction(d.normalized()), time(t) {}
    
    Vec3 at(float t) const { return origin + direction * t; }
};

class Material;

struct HitRecord {
    Vec3 point, normal;
    Vec3 tangent, bitangent; // For anisotropic materials
    float t;
    bool frontFace;
    Vec2 uv;
    std::shared_ptr<Material> material;
    bool isDelta; // True for perfect specular/transmission
    
    HitRecord() : t(std::numeric_limits<float>::max()), frontFace(true), isDelta(false) {}
    
    void setFaceNormal(const Ray& r, const Vec3& outwardNormal) {
        frontFace = r.direction.dot(outwardNormal) < 0;
        normal = frontFace ? outwardNormal : -outwardNormal;
        
        // Build tangent frame
        buildOrthonormalBasis(normal, tangent, bitangent);
    }
};

// ============================================================================
// AABB AND SPATIAL STRUCTURES
// ============================================================================

class AABB {
public:
    Vec3 min, max;
    
    AABB() : min(Vec3(std::numeric_limits<float>::max())), 
             max(Vec3(std::numeric_limits<float>::lowest())) {}
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
    
    AABB merge(const AABB& box) const {
        return AABB(Vec3::min(min, box.min), Vec3::max(max, box.max));
    }
    
    AABB expand(float delta) const {
        return AABB(min - Vec3(delta), max + Vec3(delta));
    }
    
    float area() const {
        Vec3 d = max - min;
        return 2 * (d.x * d.y + d.y * d.z + d.z * d.x);
    }
    
    int maxExtent() const {
        Vec3 d = max - min;
        if (d.x > d.y && d.x > d.z) return 0;
        else if (d.y > d.z) return 1;
        else return 2;
    }
    
    Vec3 centroid() const { return (min + max) * 0.5f; }
};

// ============================================================================
// SAMPLING STRUCTURES
// ============================================================================

struct LightSample {
    Vec3 position;
    Vec3 normal;
    Vec3 emission;
    float pdf;
    float distance;
};

struct BSDFSample {
    Vec3 wi;  // Incident direction (towards light)
    Vec3 f;   // BSDF value
    float pdf;
    bool isDelta;
};

// ============================================================================
// MATERIALS WITH MIS SUPPORT
// ============================================================================

class Material {
public:
    virtual ~Material() = default;
    
    // Evaluate BSDF * cos(theta)
    virtual Vec3 eval(const HitRecord& rec, const Vec3& wo, const Vec3& wi) const {
        return Vec3(0);
    }
    
    // Sample BSDF
    virtual BSDFSample sample(const HitRecord& rec, const Vec3& wo, 
                             std::mt19937& gen) const {
        BSDFSample s;
        s.wi = Vec3(0, 1, 0);
        s.f = Vec3(0);
        s.pdf = 0;
        s.isDelta = false;
        return s;
    }
    
    // PDF for sampling direction wi
    virtual float pdf(const HitRecord& rec, const Vec3& wo, const Vec3& wi) const {
        return 0;
    }
    
    // Emission
    virtual Vec3 emitted(const HitRecord& rec) const { 
        return Vec3(0); 
    }
    
    // Legacy scatter interface (will be deprecated)
    virtual bool scatter(const Ray& rIn, const HitRecord& rec, Vec3& attenuation, 
                        Ray& scattered, float& pdf, std::mt19937& gen) const {
        Vec3 wo = -rIn.direction.normalized();
        BSDFSample s = sample(rec, wo, gen);
        if (s.pdf <= 0) return false;
        
        scattered = Ray(rec.point, s.wi, rIn.time);
        attenuation = s.f / s.pdf;
        pdf = s.pdf;
        return true;
    }
};

class Lambertian : public Material {
    Vec3 albedo;
public:
    Lambertian(const Vec3& a) : albedo(a) {}
    
    Vec3 eval(const HitRecord& rec, const Vec3& wo, const Vec3& wi) const override {
        if (wi.dot(rec.normal) <= 0) return Vec3(0);
        return albedo / M_PI * wi.dot(rec.normal);
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

class Metal : public Material {
    Vec3 albedo;
    float roughness;
    
    Vec3 fresnelSchlick(float cosTheta, const Vec3& F0) const {
        return F0 + (Vec3(1) - F0) * std::pow(1 - cosTheta, 5);
    }
    
public:
    Metal(const Vec3& a, float r = 0) : albedo(a), roughness(std::clamp(r, 0.0f, 1.0f)) {}
    
    Vec3 eval(const HitRecord& rec, const Vec3& wo, const Vec3& wi) const override {
        if (roughness > 0.01f) {
            // Rough metal - use microfacet model
            Vec3 h = (wo + wi).normalized();
            float NdotH = rec.normal.dot(h);
            float NdotL = rec.normal.dot(wi);
            float NdotV = rec.normal.dot(wo);
            
            if (NdotL <= 0 || NdotV <= 0) return Vec3(0);
            
            // GGX distribution
            float a = roughness * roughness;
            float a2 = a * a;
            float NdotH2 = NdotH * NdotH;
            float denom = NdotH2 * (a2 - 1) + 1;
            float D = a2 / (M_PI * denom * denom);
            
            // Fresnel
            Vec3 F = fresnelSchlick(wo.dot(h), albedo);
            
            // Geometry
            float k = (roughness + 1) * (roughness + 1) / 8;
            float G1L = NdotL / (NdotL * (1 - k) + k);
            float G1V = NdotV / (NdotV * (1 - k) + k);
            float G = G1L * G1V;
            
            return F * D * G / (4 * NdotV);
        }
        return Vec3(0); // Perfect mirror handled by sample()
    }
    
    BSDFSample sample(const HitRecord& rec, const Vec3& wo, std::mt19937& gen) const override {
        BSDFSample s;
        
        if (roughness < 0.01f) {
            // Perfect reflection
            s.wi = wo - rec.normal * (2 * wo.dot(rec.normal));
            s.f = albedo;
            s.pdf = 1;
            s.isDelta = true;
            const_cast<HitRecord&>(rec).isDelta = true;
        } else {
            // Sample GGX distribution
            std::uniform_real_distribution<float> dist(0, 1);
            float r1 = dist(gen);
            float r2 = dist(gen);
            
            float a = roughness * roughness;
            float phi = 2 * M_PI * r1;
            float cosTheta = std::sqrt((1 - r2) / (1 + (a*a - 1) * r2));
            float sinTheta = std::sqrt(1 - cosTheta * cosTheta);
            
            Vec3 h(std::cos(phi) * sinTheta, std::sin(phi) * sinTheta, cosTheta);
            h = rec.tangent * h.x + rec.bitangent * h.y + rec.normal * h.z;
            
            s.wi = (h * (2 * wo.dot(h)) - wo).normalized();
            
            if (s.wi.dot(rec.normal) > 0) {
                s.f = eval(rec, wo, s.wi);
                
                // PDF for GGX distribution
                float NdotH = rec.normal.dot(h);
                float HdotV = h.dot(wo);
                float a2 = a * a;
                float denom = NdotH * NdotH * (a2 - 1) + 1;
                s.pdf = a2 * NdotH / (M_PI * denom * denom * 4 * HdotV);
            }
            s.isDelta = false;
        }
        
        return s;
    }
    
    float pdf(const HitRecord& rec, const Vec3& wo, const Vec3& wi) const override {
        if (roughness < 0.01f) return 0;
        
        Vec3 h = (wo + wi).normalized();
        float NdotH = rec.normal.dot(h);
        float HdotV = h.dot(wo);
        float a = roughness * roughness;
        float a2 = a * a;
        float denom = NdotH * NdotH * (a2 - 1) + 1;
        return a2 * NdotH / (M_PI * denom * denom * 4 * HdotV);
    }
};

class Dielectric : public Material {
    float ior;
    
    float fresnelDielectric(float cosThetaI, float etaI, float etaT) const {
        cosThetaI = std::clamp(cosThetaI, -1.0f, 1.0f);
        bool entering = cosThetaI > 0;
        if (!entering) {
            std::swap(etaI, etaT);
            cosThetaI = std::abs(cosThetaI);
        }
        
        float sinThetaI = std::sqrt(std::max(0.0f, 1 - cosThetaI * cosThetaI));
        float sinThetaT = etaI / etaT * sinThetaI;
        
        if (sinThetaT >= 1) return 1; // Total internal reflection
        
        float cosThetaT = std::sqrt(std::max(0.0f, 1 - sinThetaT * sinThetaT));
        
        float Rparl = ((etaT * cosThetaI) - (etaI * cosThetaT)) /
                      ((etaT * cosThetaI) + (etaI * cosThetaT));
        float Rperp = ((etaI * cosThetaI) - (etaT * cosThetaT)) /
                      ((etaI * cosThetaI) + (etaT * cosThetaT));
        
        return (Rparl * Rparl + Rperp * Rperp) / 2;
    }
    
public:
    Dielectric(float indexOfRefraction) : ior(indexOfRefraction) {}
    
    BSDFSample sample(const HitRecord& rec, const Vec3& wo, std::mt19937& gen) const override {
        BSDFSample s;
        s.isDelta = true;
        const_cast<HitRecord&>(rec).isDelta = true;
        
        float cosTheta = wo.dot(rec.normal);
        float etaI = 1, etaT = ior;
        Vec3 n = rec.normal;
        
        if (cosTheta < 0) {
            // Inside object
            cosTheta = -cosTheta;
            std::swap(etaI, etaT);
            n = -n;
        }
        
        float eta = etaI / etaT;
        float sinTheta = std::sqrt(std::max(0.0f, 1 - cosTheta * cosTheta));
        
        // Check for total internal reflection
        bool cannotRefract = eta * sinTheta > 1;
        
        std::uniform_real_distribution<float> dist(0, 1);
        float fresnel = fresnelDielectric(cosTheta, etaI, etaT);
        
        if (cannotRefract || dist(gen) < fresnel) {
            // Reflection
            s.wi = wo - n * (2 * wo.dot(n));
            s.f = Vec3(1);
            s.pdf = fresnel;
        } else {
            // Refraction
            Vec3 wt_perp = (wo - n * cosTheta) * (-eta);
            Vec3 wt_parallel = n * (-std::sqrt(std::abs(1 - wt_perp.length2())));
            s.wi = (wt_perp + wt_parallel).normalized();
            s.f = Vec3(1) * (eta * eta);
            s.pdf = 1 - fresnel;
        }
        
        return s;
    }
};

class DiffuseLight : public Material {
    Vec3 color;
    float intensity;
public:
    DiffuseLight(const Vec3& c, float i = 1.0f) : color(c), intensity(i) {}
    
    Vec3 emitted(const HitRecord& rec) const override {
        return rec.frontFace ? color * intensity : Vec3(0);
    }
    
    BSDFSample sample(const HitRecord& rec, const Vec3& wo, std::mt19937& gen) const override {
        return BSDFSample{Vec3(0), Vec3(0), 0, false};
    }
};

// ============================================================================
// GEOMETRY
// ============================================================================

class Hittable {
public:
    virtual ~Hittable() = default;
    virtual bool hit(const Ray& r, float tMin, float tMax, HitRecord& rec) const = 0;
    virtual bool boundingBox(AABB& box) const = 0;
    virtual float pdfValue(const Vec3& origin, const Vec3& direction) const { return 0; }
    virtual Vec3 random(const Vec3& origin, std::mt19937& gen) const { return Vec3(0, 1, 0); }
    virtual bool isLight() const { return false; }
    virtual Vec3 emittedRadiance() const { return Vec3(0); }
};

class Sphere : public Hittable {
    Vec3 center;
    float radius;
    std::shared_ptr<Material> material;
    bool emissive;
    
public:
    Sphere(const Vec3& c, float r, std::shared_ptr<Material> m) 
        : center(c), radius(r), material(m) {
        emissive = dynamic_cast<DiffuseLight*>(m.get()) != nullptr;
    }
    
    bool hit(const Ray& r, float tMin, float tMax, HitRecord& rec) const override {
        Vec3 oc = r.origin - center;
        float a = r.direction.length2();
        float half_b = oc.dot(r.direction);
        float c = oc.length2() - radius * radius;
        float discriminant = half_b * half_b - a * c;
        
        if (discriminant < 0) return false;
        
        float sqrtd = std::sqrt(discriminant);
        float root = (-half_b - sqrtd) / a;
        if (root < tMin || root > tMax) {
            root = (-half_b + sqrtd) / a;
            if (root < tMin || root > tMax) return false;
        }
        
        rec.t = root;
        rec.point = r.at(root);
        Vec3 outwardNormal = (rec.point - center) / radius;
        rec.setFaceNormal(r, outwardNormal);
        rec.material = material;
        
        float theta = std::acos(-outwardNormal.y);
        float phi = std::atan2(-outwardNormal.z, outwardNormal.x) + M_PI;
        rec.uv = Vec2(phi / (2 * M_PI), theta / M_PI);
        
        return true;
    }
    
    bool boundingBox(AABB& box) const override {
        box = AABB(center - Vec3(radius), center + Vec3(radius));
        return true;
    }
    
    float pdfValue(const Vec3& origin, const Vec3& direction) const override {
        HitRecord rec;
        if (!hit(Ray(origin, direction), 0.001f, std::numeric_limits<float>::max(), rec))
            return 0;
        
        float cosThetaMax = std::sqrt(1 - radius * radius / (center - origin).length2());
        float solidAngle = 2 * M_PI * (1 - cosThetaMax);
        return 1 / solidAngle;
    }
    
    Vec3 random(const Vec3& origin, std::mt19937& gen) const override {
        Vec3 direction = center - origin;
        float distanceSq = direction.length2();
        direction = direction.normalized();
        
        float cosThetaMax = std::sqrt(1 - radius * radius / distanceSq);
        
        std::uniform_real_distribution<float> dist(0, 1);
        float r1 = dist(gen), r2 = dist(gen);
        float z = 1 + r2 * (cosThetaMax - 1);
        float phi = 2 * M_PI * r1;
        float x = std::cos(phi) * std::sqrt(1 - z * z);
        float y = std::sin(phi) * std::sqrt(1 - z * z);
        
        Vec3 u, v;
        buildOrthonormalBasis(direction, u, v);
        
        return (u * x + v * y + direction * z).normalized();
    }
    
    bool isLight() const override { return emissive; }
    
    Vec3 emittedRadiance() const override {
        if (emissive) {
            auto light = dynamic_cast<DiffuseLight*>(material.get());
            if (light) {
                HitRecord dummy;
                dummy.frontFace = true;
                return light->emitted(dummy);
            }
        }
        return Vec3(0);
    }
};

class Triangle : public Hittable {
    Vec3 v0, v1, v2, normal;
    Vec2 uv0, uv1, uv2;
    std::shared_ptr<Material> material;
    bool emissive;
    
public:
    Triangle(const Vec3& a, const Vec3& b, const Vec3& c, std::shared_ptr<Material> m)
        : v0(a), v1(b), v2(c), material(m), uv0(0, 0), uv1(1, 0), uv2(0, 1) {
        normal = (v1 - v0).cross(v2 - v0).normalized();
        emissive = dynamic_cast<DiffuseLight*>(m.get()) != nullptr;
    }
    
    Triangle(const Vec3& a, const Vec3& b, const Vec3& c,
            const Vec2& t0, const Vec2& t1, const Vec2& t2,
            std::shared_ptr<Material> m)
        : v0(a), v1(b), v2(c), uv0(t0), uv1(t1), uv2(t2), material(m) {
        normal = (v1 - v0).cross(v2 - v0).normalized();
        emissive = dynamic_cast<DiffuseLight*>(m.get()) != nullptr;
    }
    
    bool hit(const Ray& r, float tMin, float tMax, HitRecord& rec) const override {
        const float EPSILON = 1e-6f;
        Vec3 edge1 = v1 - v0;
        Vec3 edge2 = v2 - v0;
        Vec3 h = r.direction.cross(edge2);
        float a = edge1.dot(h);
        
        if (std::fabs(a) < EPSILON) return false;
        
        float f = 1.0f / a;
        Vec3 s = r.origin - v0;
        float u = f * s.dot(h);
        if (u < 0.0f || u > 1.0f) return false;
        
        Vec3 q = s.cross(edge1);
        float v = f * r.direction.dot(q);
        if (v < 0.0f || u + v > 1.0f) return false;
        
        float t = f * edge2.dot(q);
        if (t < tMin || t > tMax) return false;
        
        rec.t = t;
        rec.point = r.at(t);
        rec.setFaceNormal(r, normal);
        rec.material = material;
        
        // Interpolate UV coordinates
        float w = 1 - u - v;
        rec.uv = uv0 * w + uv1 * u + uv2 * v;
        
        return true;
    }
    
    bool boundingBox(AABB& box) const override {
        Vec3 min = Vec3::min(Vec3::min(v0, v1), v2);
        Vec3 max = Vec3::max(Vec3::max(v0, v1), v2);
        const float PAD = 0.0001f;
        box = AABB(min - Vec3(PAD), max + Vec3(PAD));
        return true;
    }
    
    float pdfValue(const Vec3& origin, const Vec3& direction) const override {
        HitRecord rec;
        if (!hit(Ray(origin, direction), 0.001f, std::numeric_limits<float>::max(), rec))
            return 0;
        
        float area = (v1 - v0).cross(v2 - v0).length() * 0.5f;
        float distanceSq = rec.t * rec.t;
        float cosine = std::abs(direction.dot(rec.normal));
        
        return distanceSq / (cosine * area);
    }
    
    Vec3 random(const Vec3& origin, std::mt19937& gen) const override {
        std::uniform_real_distribution<float> dist(0, 1);
        float r1 = dist(gen);
        float r2 = dist(gen);
        
        if (r1 + r2 > 1) {
            r1 = 1 - r1;
            r2 = 1 - r2;
        }
        
        Vec3 randomPoint = v0 + (v1 - v0) * r1 + (v2 - v0) * r2;
        return (randomPoint - origin).normalized();
    }
    
    bool isLight() const override { return emissive; }
    
    Vec3 emittedRadiance() const override {
        if (emissive) {
            auto light = dynamic_cast<DiffuseLight*>(material.get());
            if (light) {
                HitRecord dummy;
                dummy.frontFace = true;
                return light->emitted(dummy);
            }
        }
        return Vec3(0);
    }
};

// ============================================================================
// BVH WITH SAH CONSTRUCTION
// ============================================================================

struct BVHPrimitiveInfo {
    size_t primitiveIndex;
    Vec3 centroid;
    AABB bounds;
    
    BVHPrimitiveInfo(size_t idx, const AABB& b) 
        : primitiveIndex(idx), bounds(b), centroid(b.centroid()) {}
};

struct BVHBuildNode {
    AABB bounds;
    BVHBuildNode* children[2];
    int splitAxis, firstPrimOffset, nPrimitives;
    
    void initLeaf(int first, int n, const AABB& b) {
        firstPrimOffset = first;
        nPrimitives = n;
        bounds = b;
        children[0] = children[1] = nullptr;
    }
    
    void initInterior(int axis, BVHBuildNode* c0, BVHBuildNode* c1) {
        children[0] = c0;
        children[1] = c1;
        bounds = c0->bounds.merge(c1->bounds);
        splitAxis = axis;
        nPrimitives = 0;
    }
};

struct LinearBVHNode {
    AABB bounds;
    union {
        int primitivesOffset;   // Leaf
        int secondChildOffset;  // Interior
    };
    uint16_t nPrimitives;  // 0 -> interior node
    uint8_t axis;          // Interior node: xyz
    uint8_t pad[1];        // Ensure 32 byte total size
};

class BVHAccel : public Hittable {
    std::vector<std::shared_ptr<Hittable>> primitives;
    LinearBVHNode* nodes = nullptr;
    
    struct BucketInfo {
        int count = 0;
        AABB bounds;
    };
    
    static constexpr int nBuckets = 16;
    
    BVHBuildNode* recursiveBuild(std::vector<BVHPrimitiveInfo>& primitiveInfo,
                                 int start, int end, size_t* totalNodes,
                                 std::vector<std::shared_ptr<Hittable>>& orderedPrims) {
        BVHBuildNode* node = new BVHBuildNode;
        (*totalNodes)++;
        
        AABB bounds;
        for (int i = start; i < end; ++i)
            bounds = bounds.merge(primitiveInfo[i].bounds);
        
        int nPrimitives = end - start;
        
        if (nPrimitives == 1) {
            // Create leaf node
            int firstPrimOffset = orderedPrims.size();
            for (int i = start; i < end; ++i) {
                int primNum = primitiveInfo[i].primitiveIndex;
                orderedPrims.push_back(primitives[primNum]);
            }
            node->initLeaf(firstPrimOffset, nPrimitives, bounds);
            return node;
        }
        
        // Compute bound of primitive centroids
        AABB centroidBounds;
        for (int i = start; i < end; ++i)
            centroidBounds = centroidBounds.merge(AABB(primitiveInfo[i].centroid, 
                                                       primitiveInfo[i].centroid));
        
        int dim = centroidBounds.maxExtent();
        
        // Partition primitives
        int mid = (start + end) / 2;
        
        if (centroidBounds.max[dim] == centroidBounds.min[dim]) {
            // Create leaf if cannot split
            int firstPrimOffset = orderedPrims.size();
            for (int i = start; i < end; ++i) {
                int primNum = primitiveInfo[i].primitiveIndex;
                orderedPrims.push_back(primitives[primNum]);
            }
            node->initLeaf(firstPrimOffset, nPrimitives, bounds);
            return node;
        }
        
        // SAH partition
        if (nPrimitives <= 2) {
            // Too few primitives for SAH
            mid = (start + end) / 2;
            std::nth_element(&primitiveInfo[start], &primitiveInfo[mid],
                           &primitiveInfo[end - 1] + 1,
                           [dim](const BVHPrimitiveInfo& a, const BVHPrimitiveInfo& b) {
                               return a.centroid[dim] < b.centroid[dim];
                           });
        } else {
            // Allocate BucketInfo for SAH partition buckets
            BucketInfo buckets[nBuckets];
            
            // Initialize bucket info
            for (int i = start; i < end; ++i) {
                int b = nBuckets * ((primitiveInfo[i].centroid[dim] - centroidBounds.min[dim]) /
                                   (centroidBounds.max[dim] - centroidBounds.min[dim]));
                if (b == nBuckets) b = nBuckets - 1;
                buckets[b].count++;
                buckets[b].bounds = buckets[b].bounds.merge(primitiveInfo[i].bounds);
            }
            
            // Compute costs for splitting after each bucket
            float cost[nBuckets - 1];
            for (int i = 0; i < nBuckets - 1; ++i) {
                AABB b0, b1;
                int count0 = 0, count1 = 0;
                
                for (int j = 0; j <= i; ++j) {
                    b0 = b0.merge(buckets[j].bounds);
                    count0 += buckets[j].count;
                }
                for (int j = i + 1; j < nBuckets; ++j) {
                    b1 = b1.merge(buckets[j].bounds);
                    count1 += buckets[j].count;
                }
                
                cost[i] = 0.125f + (count0 * b0.area() + count1 * b1.area()) / bounds.area();
            }
            
            // Find bucket to split at that minimizes SAH metric
            float minCost = cost[0];
            int minCostSplitBucket = 0;
            for (int i = 1; i < nBuckets - 1; ++i) {
                if (cost[i] < minCost) {
                    minCost = cost[i];
                    minCostSplitBucket = i;
                }
            }
            
            // Either create leaf or split at selected SAH bucket
            float leafCost = nPrimitives;
            if (nPrimitives > 4 && minCost < leafCost) {
                BVHPrimitiveInfo* pmid = std::partition(&primitiveInfo[start],
                                                       &primitiveInfo[end - 1] + 1,
                    [=](const BVHPrimitiveInfo& pi) {
                        int b = nBuckets * ((pi.centroid[dim] - centroidBounds.min[dim]) /
                                          (centroidBounds.max[dim] - centroidBounds.min[dim]));
                        if (b == nBuckets) b = nBuckets - 1;
                        return b <= minCostSplitBucket;
                    });
                mid = pmid - &primitiveInfo[0];
            } else {
                // Create leaf
                int firstPrimOffset = orderedPrims.size();
                for (int i = start; i < end; ++i) {
                    int primNum = primitiveInfo[i].primitiveIndex;
                    orderedPrims.push_back(primitives[primNum]);
                }
                node->initLeaf(firstPrimOffset, nPrimitives, bounds);
                return node;
            }
        }
        
        node->initInterior(dim,
                          recursiveBuild(primitiveInfo, start, mid, totalNodes, orderedPrims),
                          recursiveBuild(primitiveInfo, mid, end, totalNodes, orderedPrims));
        return node;
    }
    
    int flattenBVHTree(BVHBuildNode* node, int* offset) {
        LinearBVHNode* linearNode = &nodes[*offset];
        linearNode->bounds = node->bounds;
        int myOffset = (*offset)++;
        
        if (node->nPrimitives > 0) {
            linearNode->primitivesOffset = node->firstPrimOffset;
            linearNode->nPrimitives = node->nPrimitives;
        } else {
            linearNode->axis = node->splitAxis;
            linearNode->nPrimitives = 0;
            flattenBVHTree(node->children[0], offset);
            linearNode->secondChildOffset = flattenBVHTree(node->children[1], offset);
        }
        return myOffset;
    }
    
public:
    BVHAccel(const std::vector<std::shared_ptr<Hittable>>& p) : primitives(p) {
        if (primitives.empty()) return;
        
        // Build BVH from primitives
        std::vector<BVHPrimitiveInfo> primitiveInfo;
        for (size_t i = 0; i < primitives.size(); ++i) {
            AABB bounds;
            primitives[i]->boundingBox(bounds);
            primitiveInfo.push_back(BVHPrimitiveInfo(i, bounds));
        }
        
        size_t totalNodes = 0;
        std::vector<std::shared_ptr<Hittable>> orderedPrims;
        BVHBuildNode* root = recursiveBuild(primitiveInfo, 0, primitives.size(),
                                           &totalNodes, orderedPrims);
        primitives.swap(orderedPrims);
        
        // Flatten BVH tree to linear representation
        nodes = new LinearBVHNode[totalNodes];
        int offset = 0;
        flattenBVHTree(root, &offset);
    }
    
    ~BVHAccel() { delete[] nodes; }
    
    bool hit(const Ray& r, float tMin, float tMax, HitRecord& rec) const override {
        if (!nodes) return false;
        
        bool hit = false;
        Vec3 invDir(1 / r.direction.x, 1 / r.direction.y, 1 / r.direction.z);
        int dirIsNeg[3] = {invDir.x < 0, invDir.y < 0, invDir.z < 0};
        
        // Stack for traversal
        int toVisitOffset = 0, currentNodeIndex = 0;
        int nodesToVisit[64];
        
        while (true) {
            const LinearBVHNode* node = &nodes[currentNodeIndex];
            
            if (node->bounds.hit(r, tMin, tMax)) {
                if (node->nPrimitives > 0) {
                    // Leaf node
                    for (int i = 0; i < node->nPrimitives; ++i) {
                        if (primitives[node->primitivesOffset + i]->hit(r, tMin, tMax, rec)) {
                            hit = true;
                            tMax = rec.t;
                        }
                    }
                    if (toVisitOffset == 0) break;
                    currentNodeIndex = nodesToVisit[--toVisitOffset];
                } else {
                    // Interior node
                    if (dirIsNeg[node->axis]) {
                        nodesToVisit[toVisitOffset++] = currentNodeIndex + 1;
                        currentNodeIndex = node->secondChildOffset;
                    } else {
                        nodesToVisit[toVisitOffset++] = node->secondChildOffset;
                        currentNodeIndex = currentNodeIndex + 1;
                    }
                }
            } else {
                if (toVisitOffset == 0) break;
                currentNodeIndex = nodesToVisit[--toVisitOffset];
            }
        }
        
        return hit;
    }
    
    bool boundingBox(AABB& box) const override {
        if (nodes) box = nodes[0].bounds;
        return nodes != nullptr;
    }
};

// ============================================================================
// LIGHT MANAGEMENT
// ============================================================================

class LightList {
    std::vector<std::shared_ptr<Hittable>> lights;
    std::vector<float> powerDistribution;
    float totalPower = 0;
    
public:
    void add(std::shared_ptr<Hittable> light) {
        lights.push_back(light);
        
        // Estimate light power (simplified - should be more sophisticated)
        Vec3 emission = light->emittedRadiance();
        float power = luminance(emission);
        
        AABB bounds;
        light->boundingBox(bounds);
        power *= bounds.area();  // Rough estimate
        
        totalPower += power;
        powerDistribution.push_back(totalPower);
    }
    
    LightSample sampleLight(const Vec3& point, std::mt19937& gen) const {
        if (lights.empty()) return LightSample{Vec3(0), Vec3(0), Vec3(0), 0, 0};
        
        std::uniform_real_distribution<float> dist(0, 1);
        
        // Sample light based on power distribution
        float u = dist(gen) * totalPower;
        size_t lightIdx = 0;
        for (size_t i = 0; i < powerDistribution.size(); ++i) {
            if (u < powerDistribution[i]) {
                lightIdx = i;
                break;
            }
        }
        
        // Sample point on selected light
        Vec3 direction = lights[lightIdx]->random(point, gen);
        Ray testRay(point, direction);
        HitRecord rec;
        
        LightSample sample;
        if (lights[lightIdx]->hit(testRay, 0.001f, std::numeric_limits<float>::max(), rec)) {
            sample.position = rec.point;
            sample.normal = rec.normal;
            sample.emission = lights[lightIdx]->emittedRadiance();
            sample.distance = rec.t;
            sample.pdf = lights[lightIdx]->pdfValue(point, direction);
            
            // Adjust PDF for power-based selection
            float selectionPdf = (lightIdx > 0 ? powerDistribution[lightIdx] - powerDistribution[lightIdx-1] : powerDistribution[0]) / totalPower;
            sample.pdf *= selectionPdf;
        }
        
        return sample;
    }
    
    float pdfValue(const Vec3& point, const Vec3& direction) const {
        if (lights.empty()) return 0;
        
        float pdf = 0;
        for (size_t i = 0; i < lights.size(); ++i) {
            float selectionPdf = (i > 0 ? powerDistribution[i] - powerDistribution[i-1] : powerDistribution[0]) / totalPower;
            pdf += selectionPdf * lights[i]->pdfValue(point, direction);
        }
        return pdf;
    }
    
    size_t size() const { return lights.size(); }
    bool empty() const { return lights.empty(); }
};

// ============================================================================
// CAMERA
// ============================================================================

class Camera {
    Vec3 origin, lowerLeft, horizontal, vertical;
    Vec3 u, v, w_axis;
    float lensRadius;

public:
    int width, height;
    std::vector<Vec3> pixels;
    std::vector<Vec3> albedoBuffer;  // For denoising
    std::vector<Vec3> normalBuffer;  // For denoising

    Camera(Vec3 lookFrom, Vec3 lookAt, Vec3 vup, float vfov, float aspectRatio,
        float aperture, float focusDist, int w, int h)
        : width(w), height(h) {

        float theta = vfov * M_PI / 180.0f;
        float viewportHeight = 2.0f * std::tan(theta / 2) * focusDist;
        float viewportWidth = aspectRatio * viewportHeight;

        w_axis = (lookFrom - lookAt).normalized();
        u = vup.cross(w_axis).normalized();
        v = w_axis.cross(u);

        origin = lookFrom;
        horizontal = u * viewportWidth;
        vertical = v * viewportHeight;
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
};

// ============================================================================
// RENDERER WITH NEXT EVENT ESTIMATION AND MIS
// ============================================================================

class Renderer {
    std::vector<std::shared_ptr<Hittable>> scene;
    std::shared_ptr<BVHAccel> bvh;
    LightList lights;
    
    // Adaptive sampling statistics
    struct PixelStats {
        float sumLuminance = 0;
        float sumLuminanceSq = 0;
        int sampleCount = 0;
        
        bool hasConverged(float threshold = 0.01f) const {
            if (sampleCount < 16) return false;
            float mean = sumLuminance / sampleCount;
            float variance = (sumLuminanceSq / sampleCount) - (mean * mean);
            float stddev = std::sqrt(std::max(0.0f, variance));
            return stddev / (mean + 0.01f) < threshold;
        }
        
        void addSample(const Vec3& color) {
            float lum = luminance(color);
            sumLuminance += lum;
            sumLuminanceSq += lum * lum;
            sampleCount++;
        }
    };
    
    float powerHeuristic(float pdfA, float pdfB, float beta = 2) const {
        float termA = std::pow(pdfA, beta);
        float termB = std::pow(pdfB, beta);
        return termA / (termA + termB + 1e-8f);
    }
    
    Vec3 sampleDirectLighting(const HitRecord& rec, const Ray& ray, std::mt19937& gen) {
        if (lights.empty() || rec.isDelta) return Vec3(0);
        
        Vec3 wo = -ray.direction.normalized();
        Vec3 directLight(0);
        
        // Light sampling
        LightSample lightSample = lights.sampleLight(rec.point, gen);
        if (lightSample.pdf > 0) {
            Vec3 wi = (lightSample.position - rec.point).normalized();
            
            // Check visibility
            Ray shadowRay(rec.point, wi);
            HitRecord shadowRec;
            bool visible = !bvh->hit(shadowRay, 0.001f, lightSample.distance - 0.001f, shadowRec);
            
            if (visible) {
                Vec3 f = rec.material->eval(rec, wo, wi);
                float bsdfPdf = rec.material->pdf(rec, wo, wi);
                float weight = powerHeuristic(lightSample.pdf, bsdfPdf);
                
                float cosTheta = std::abs(wi.dot(rec.normal));
                directLight += f * lightSample.emission * cosTheta * weight / lightSample.pdf;
            }
        }
        
        // BSDF sampling
        BSDFSample bsdfSample = rec.material->sample(rec, wo, gen);
        if (bsdfSample.pdf > 0 && !bsdfSample.isDelta) {
            Ray bsdfRay(rec.point, bsdfSample.wi);
            HitRecord bsdfRec;
            
            if (bvh->hit(bsdfRay, 0.001f, std::numeric_limits<float>::max(), bsdfRec)) {
                if (bsdfRec.material->emitted(bsdfRec) != Vec3(0)) {
                    Vec3 Le = bsdfRec.material->emitted(bsdfRec);
                    float lightPdf = lights.pdfValue(rec.point, bsdfSample.wi);
                    float weight = powerHeuristic(bsdfSample.pdf, lightPdf);
                    
                    directLight += bsdfSample.f * Le * weight / bsdfSample.pdf;
                }
            }
        }
        
        return directLight;
    }
    
    Vec3 pathTrace(const Ray& r, int depth, std::mt19937& gen, bool collectGBuffer = false,
                  Vec3* albedoOut = nullptr, Vec3* normalOut = nullptr) {
        const int russianRouletteDepth = 3;
        const int maxDepth = 50;
        
        Vec3 color(0);
        Vec3 throughput(1);
        Ray ray = r;
        
        for (int bounces = 0; bounces < maxDepth; ++bounces) {
            HitRecord rec;
            
            if (!bvh->hit(ray, 0.001f, std::numeric_limits<float>::max(), rec)) {
                // Sky gradient
                float t = 0.5f * (ray.direction.normalized().y + 1.0f);
                color += throughput * (Vec3(1) * (1.0f - t) + Vec3(0.5f, 0.7f, 1.0f) * t * 0.5f);
                break;
            }
            
            // Collect G-buffer on first hit
            if (collectGBuffer && bounces == 0) {
                if (albedoOut) {
                    if (auto lamb = dynamic_cast<Lambertian*>(rec.material.get())) {
                        *albedoOut = lamb->eval(rec, Vec3(0, 1, 0), Vec3(0, 1, 0)) * M_PI;
                    }
                }
                if (normalOut) {
                    *normalOut = rec.normal * 0.5f + Vec3(0.5f);
                }
            }
            
            // Add emitted light
            Vec3 emitted = rec.material->emitted(rec);
            if (emitted != Vec3(0)) {
                if (bounces == 0 || rec.isDelta) {
                    color += throughput * emitted;
                }
                break;
            }
            
            // Direct lighting (NEE + MIS)
            if (!rec.isDelta) {
                color += throughput * sampleDirectLighting(rec, ray, gen);
            }
            
            // Russian roulette
            if (bounces > russianRouletteDepth) {
                float continueProbability = std::min(0.95f, luminance(throughput));
                if (std::uniform_real_distribution<float>(0, 1)(gen) > continueProbability)
                    break;
                throughput /= continueProbability;
            }
            
            // Sample BSDF for next bounce
            Vec3 wo = -ray.direction.normalized();
            BSDFSample bsdfSample = rec.material->sample(rec, wo, gen);
            
            if (bsdfSample.pdf <= 0) break;
            
            throughput *= bsdfSample.f / bsdfSample.pdf;
            ray = Ray(rec.point, bsdfSample.wi, ray.time);
            
            // Prevent fireflies
            float maxComponent = throughput.maxComponent();
            if (maxComponent > 10.0f) {
                throughput *= 10.0f / maxComponent;
            }
        }
        
        return color;
    }
    
public:
    void addObject(std::shared_ptr<Hittable> obj) {
        scene.push_back(obj);
        if (obj->isLight()) {
            lights.add(obj);
        }
    }
    
    void buildAcceleration() {
        bvh = std::make_shared<BVHAccel>(scene);
    }
    
    void render(Camera& cam, int maxSamplesPerPixel, int maxDepth, 
                std::function<void(float)> progressCallback = nullptr,
                bool useAdaptiveSampling = true) {
        buildAcceleration();
        
        std::vector<PixelStats> pixelStats;
        if (useAdaptiveSampling) {
            pixelStats.resize(cam.width * cam.height);
        }
        
        std::atomic<int> tilesCompleted{0};
        const int tileSize = 16;
        const int tilesX = (cam.width + tileSize - 1) / tileSize;
        const int tilesY = (cam.height + tileSize - 1) / tileSize;
        const int totalTiles = tilesX * tilesY;
        
        #pragma omp parallel for schedule(dynamic) collapse(2)
        for (int tileY = 0; tileY < tilesY; ++tileY) {
            for (int tileX = 0; tileX < tilesX; ++tileX) {
                std::mt19937 gen(std::random_device{}() + tileY * tilesX + tileX);
                std::uniform_real_distribution<float> dist(0, 1);
                
                int xStart = tileX * tileSize;
                int xEnd = std::min(xStart + tileSize, cam.width);
                int yStart = tileY * tileSize;
                int yEnd = std::min(yStart + tileSize, cam.height);
                
                for (int y = yStart; y < yEnd; ++y) {
                    for (int x = xStart; x < xEnd; ++x) {
                        int pixelIdx = y * cam.width + x;
                        Vec3 color(0);
                        Vec3 albedo(0);
                        Vec3 normal(0);
                        
                        int samples = 0;
                        for (int s = 0; s < maxSamplesPerPixel; ++s) {
                            float u = (x + dist(gen)) / (cam.width - 1);
                            float v = (y + dist(gen)) / (cam.height - 1);
                            Ray r = cam.getRay(u, v, gen);
                            
                            Vec3 sampleAlbedo, sampleNormal;
                            Vec3 sampleColor = pathTrace(r, maxDepth, gen, s == 0, 
                                                        &sampleAlbedo, &sampleNormal);
                            color += sampleColor;
                            samples++;
                            
                            if (s == 0) {
                                albedo = sampleAlbedo;
                                normal = sampleNormal;
                            }
                            
                            // Adaptive sampling
                            if (useAdaptiveSampling && s > 0 && (s + 1) % 16 == 0) {
                                pixelStats[pixelIdx].addSample(sampleColor);
                                if (pixelStats[pixelIdx].hasConverged()) {
                                    break;
                                }
                            }
                        }
                        
                        color = color / float(samples);
                        
                        // Gamma correction and clamp
                        color.x = std::sqrt(std::clamp(color.x, 0.0f, 1.0f));
                        color.y = std::sqrt(std::clamp(color.y, 0.0f, 1.0f));
                        color.z = std::sqrt(std::clamp(color.z, 0.0f, 1.0f));
                        
                        cam.pixels[pixelIdx] = color;
                        cam.albedoBuffer[pixelIdx] = albedo;
                        cam.normalBuffer[pixelIdx] = normal;
                    }
                }
                
                if (progressCallback) {
                    int completed = ++tilesCompleted;
                    progressCallback(float(completed) / totalTiles);
                }
            }
        }
    }
};
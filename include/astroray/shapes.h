#pragma once
// Shape class definitions moved from raytracer.h and advanced_features.h (pkg04).
// Include this header wherever Sphere, Triangle, Mesh, or ConstantMedium are
// instantiated directly (blender_module.cpp, shape plugins).
#include "raytracer.h"
#include <fstream>
#include <sstream>

// ============================================================================
// SPHERE
// ============================================================================

class Sphere : public Hittable {
    Vec3 center;
    float radius;
    Vec3 iesAxis;
    std::shared_ptr<IESProfile> iesProfile;
    std::shared_ptr<Material> material;
    bool emissive;
public:
    Sphere(const Vec3& c, float r, std::shared_ptr<Material> m,
           const Vec3& iesDirection = Vec3(0, -1, 0),
           std::shared_ptr<IESProfile> ies = nullptr)
        : center(c), radius(r), iesAxis(iesDirection), iesProfile(std::move(ies)),
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
    Vec3 emittedRadiance() const override { return material->getEmission(); }
    float directionFalloff(const Vec3& directionFromLight) const override {
        if (!emissive || !iesProfile) return 1.0f;
        return iesProfile->sample(iesAxis, directionFromLight);
    }
    Vec3  getCenter()   const { return center; }
    float getRadius()   const { return radius; }
    const std::shared_ptr<Material>& getMaterial() const { return material; }
};

// ============================================================================
// TRIANGLE
// ============================================================================

class Triangle : public Hittable {
    Vec3 v0, v1, v2, normal;
    Vec2 uv0, uv1, uv2;
    std::shared_ptr<Material> material;
    bool emissive;
    Vec3 vn0, vn1, vn2;
    bool hasVertexNormals = false;
public:
    Triangle(const Vec3& a, const Vec3& b, const Vec3& c, std::shared_ptr<Material> m)
        : v0(a), v1(b), v2(c), material(m), uv0(0,0), uv1(1,0), uv2(0,1),
          emissive(m->isEmissive()) {
        normal = (v1 - v0).cross(v2 - v0).normalized();
    }

    Triangle(const Vec3& a, const Vec3& b, const Vec3& c,
             const Vec2& t0, const Vec2& t1, const Vec2& t2,
             std::shared_ptr<Material> m)
        : v0(a), v1(b), v2(c), uv0(t0), uv1(t1), uv2(t2), material(m),
          emissive(m->isEmissive()) {
        normal = (v1 - v0).cross(v2 - v0).normalized();
    }

    void setVertexNormals(const Vec3& a, const Vec3& b, const Vec3& c) {
        vn0 = a; vn1 = b; vn2 = c;
        hasVertexNormals = true;
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
        rec.objectPoint = rec.point;
        float w = 1 - u - v;
        if (hasVertexNormals) {
            Vec3 nInterp = (vn0 * w + vn1 * u + vn2 * v).normalized();
            rec.setFaceNormal(r, nInterp);
        } else {
            rec.setFaceNormal(r, normal);
        }
        rec.material = material;
        rec.hitObject = this;
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
    Vec3 emittedRadiance() const override { return material->getEmission(); }
    Vec3 getV0() const { return v0; }
    Vec3 getV1() const { return v1; }
    Vec3 getV2() const { return v2; }
    Vec3 getFaceNormal() const { return normal; }
    const std::shared_ptr<Material>& getMaterial() const { return material; }
};

// ============================================================================
// CONSTANT MEDIUM
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
        rec.objectPoint = rec.point;
        rec.setRayContext(r);
        rec.normal = Vec3(1, 0, 0);
        rec.frontFace = true;
        rec.material = std::make_shared<Lambertian>(albedo);
        return true;
    }
    bool boundingBox(AABB& box) const override { return boundary->boundingBox(box); }
};

// ============================================================================
// MESH (OBJ loader with BVH)
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

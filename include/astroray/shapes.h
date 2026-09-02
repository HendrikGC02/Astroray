#pragma once
// Shape class definitions moved from raytracer.h and advanced_features.h (pkg04).
// Include this header wherever Sphere, Triangle, Mesh, or ConstantMedium are
// instantiated directly (blender_module.cpp, shape plugins).
//
// Shapes: Sphere, Triangle, ConstantMedium, Mesh (all below, this file) —
// plus CurveSegment / CurveStrip (pkg225 Stage 1, "astroray/curves.h" —
// ray-thick-curve/hair-strand primitive; not defined here since it needs no
// manifold/surface_partials dependency, but forward-declared below so headers
// that only need the type name don't have to pull in the full curve-math header).
class CurveSegment;
#include "raytracer.h"
#include "manifold/surface_partials.h"  // pkg178 PR-3 — trianglePartials (dp_du/dp_dv)
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
    // pkg56 Phase B: in-place mutators used by Renderer::update_object_transform.
    // Single-level BVH limitation per pkg56 spec §"Key design decisions" — the
    // caller must rebuild the BVH (Renderer::buildAcceleration) after mutating.
    void  setCenter(const Vec3& c) { center = c; }
};

// ============================================================================
// TRIANGLE
// ============================================================================

class Triangle : public Hittable {
    Vec3 v0, v1, v2, normal;
    Vec2 uv0, uv1, uv2;
    std::vector<std::array<Vec2, 3>> uvLayers;
    std::vector<std::string> uvLayerNames;
    std::shared_ptr<Material> material;
    bool emissive;
    Vec3 vn0, vn1, vn2;
    bool hasVertexNormals = false;
    // pkg88-C.0 — deformation motion blur. Per Cycles motion_triangle.h (Apache-2.0):
    // motionVertexBuffer is a pointer into the Renderer's motionVertices_ array.
    // If non-null, contains (K-1) additional time steps per vertex (center step = v0/v1/v2).
    // motionSteps=2 → 1 extra step at shutter close. Linear interpolation only (K ≤ 3 typical).
    const Vec3* motionVertexBuffer = nullptr;  // points to [v0_end, v1_end, v2_end, ...] for each step
    int motionSteps = 1;  // 1 = no motion (static), 2 = pre+post shutter, 3+ = keyframes
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
        uvLayerNames = {"UVMap"};
        uvLayers = {{{uv0, uv1, uv2}}};
        normal = (v1 - v0).cross(v2 - v0).normalized();
    }

    Triangle(const Vec3& a, const Vec3& b, const Vec3& c,
             const std::vector<std::array<Vec2, 3>>& layers,
             const std::vector<std::string>& layerNames,
             std::shared_ptr<Material> m)
        : v0(a), v1(b), v2(c), material(m), uvLayers(layers), uvLayerNames(layerNames),
          emissive(m->isEmissive()) {
        if (!uvLayers.empty()) {
            uv0 = uvLayers[0][0];
            uv1 = uvLayers[0][1];
            uv2 = uvLayers[0][2];
        } else {
            uv0 = Vec2(0,0); uv1 = Vec2(1,0); uv2 = Vec2(0,1);
        }
        if (uvLayerNames.size() < uvLayers.size()) {
            uvLayerNames.resize(uvLayers.size());
        }
        for (size_t i = 0; i < uvLayerNames.size(); ++i) {
            if (uvLayerNames[i].empty()) {
                uvLayerNames[i] = (i == 0) ? "UVMap" : ("UVMap" + std::to_string(i + 1));
            }
        }
        normal = (v1 - v0).cross(v2 - v0).normalized();
    }

    void setVertexNormals(const Vec3& a, const Vec3& b, const Vec3& c) {
        vn0 = a; vn1 = b; vn2 = c;
        hasVertexNormals = true;
    }

    bool hit(const Ray& r, float tMin, float tMax, HitRecord& rec) const override {
        const float EPS = 1e-6f;
        // pkg88-C.0 — time-aware vertex interpolation. Per Cycles motion_triangle.h (Apache-2.0):
        // bracket ray.time into [step, step+1], then linear blend: v = (1-t)*v[step] + t*v[step+1].
        Vec3 p0 = v0, p1 = v1, p2 = v2;
        if (motionVertexBuffer != nullptr && motionSteps > 1) {
            float time = r.time;  // Phase A already samples and carries time in Ray
            int maxStep = motionSteps - 1;
            int step = std::min(static_cast<int>(time * maxStep), maxStep - 1);
            float t = time * maxStep - step;
            // Center step (step=0) uses v0/v1/v2; additional steps read motionVertexBuffer.
            // Buffer layout: [v0_step1, v1_step1, v2_step1, v0_step2, v1_step2, v2_step2, ...]
            if (step == 0) {
                // Blend between center (v0/v1/v2) and first motion step
                const Vec3* nextVerts = motionVertexBuffer;  // step 1 starts at offset 0
                p0 = v0 * (1.0f - t) + nextVerts[0] * t;
                p1 = v1 * (1.0f - t) + nextVerts[1] * t;
                p2 = v2 * (1.0f - t) + nextVerts[2] * t;
            } else {
                // Blend between two motion steps
                const Vec3* currVerts = motionVertexBuffer + (step - 1) * 3;
                const Vec3* nextVerts = motionVertexBuffer + step * 3;
                p0 = currVerts[0] * (1.0f - t) + nextVerts[0] * t;
                p1 = currVerts[1] * (1.0f - t) + nextVerts[1] * t;
                p2 = currVerts[2] * (1.0f - t) + nextVerts[2] * t;
            }
        }
        Vec3 e1 = p1 - p0, e2 = p2 - p0;
        Vec3 h = r.direction.cross(e2);
        float a = e1.dot(h);
        if (std::fabs(a) < EPS) return false;
        float f = 1.0f / a;
        Vec3 s = r.origin - p0;
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
        rec.uvLayers.clear();
        rec.uvLayerNames = uvLayerNames;
        for (const auto& layer : uvLayers) {
            rec.uvLayers.push_back(layer[0] * w + layer[1] * u + layer[2] * v);
        }

        // pkg178 Stage-3b PR-3 — UV-aligned shading tangent (prereq for the PR-4
        // anisotropy lobe). Only meshes carrying a real UV parameterization get a
        // UV-locked tangent; untextured triangles (uvLayers empty) keep the
        // arbitrary frame setFaceNormal already stored in rec.uvTangent. This is a
        // NEW field — rec.tangent/rec.bitangent are untouched, so isotropic shading
        // is bit-identical. uvAlignedTangent reuses manifold::trianglePartials for
        // dp_du/dp_dv, fed the SAME motion-interpolated verts p0/p1/p2 used for
        // this hit; on degenerate UV/projection it returns false and the fallback
        // in rec.uvTangent stands. The GPU counterpart lands in PR-4 (needs a
        // device UV upload) gated behind the anisotropy path.
        if (!uvLayers.empty()) {
            Vec3 uvT;
            float uvSign;
            if (astroray::manifold::uvAlignedTangent(p0, p1, p2, uv0, uv1, uv2,
                                                     rec.normal, uvT, uvSign)) {
                rec.uvTangent = uvT;
                rec.uvBitangentSign = uvSign;
            }
        }
        return true;
    }

    bool boundingBox(AABB& box) const override {
        // pkg88-C.0 — union-AABB static BVH. If motion exists, compute AABB union across all time steps.
        Vec3 minP = Vec3::min(Vec3::min(v0, v1), v2);
        Vec3 maxP = Vec3::max(Vec3::max(v0, v1), v2);
        if (motionVertexBuffer != nullptr && motionSteps > 1) {
            // Expand to include all motion steps
            for (int step = 1; step < motionSteps; ++step) {
                const Vec3* stepVerts = motionVertexBuffer + (step - 1) * 3;
                minP = Vec3::min(minP, Vec3::min(Vec3::min(stepVerts[0], stepVerts[1]), stepVerts[2]));
                maxP = Vec3::max(maxP, Vec3::max(Vec3::max(stepVerts[0], stepVerts[1]), stepVerts[2]));
            }
        }
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
    bool getVertexNormals(Vec3& out0, Vec3& out1, Vec3& out2) const {
        if (!hasVertexNormals) return false;
        out0 = vn0; out1 = vn1; out2 = vn2;
        return true;
    }
    const std::shared_ptr<Material>& getMaterial() const { return material; }
    // pkg178 Stage-3b PR-4b — active-UV-layer texcoords for the GPU aniso tangent.
    Vec2 getUV0() const { return uv0; }
    Vec2 getUV1() const { return uv1; }
    Vec2 getUV2() const { return uv2; }
    bool hasUVLayers() const { return !uvLayers.empty(); }
    // pkg56 Phase B: in-place mutator used by Renderer::update_object_transform.
    // Recomputes the face normal; vertex normals (if present) must be
    // re-supplied separately when the transform isn't a rigid motion.
    void setVertices(const Vec3& a, const Vec3& b, const Vec3& c) {
        v0 = a; v1 = b; v2 = c;
        normal = (v1 - v0).cross(v2 - v0).normalized();
    }
    // pkg88-C.0 — attach motion data to this triangle. The buffer pointer must
    // remain valid for the triangle's lifetime (typically points into Renderer::motionVertices_).
    // steps = 2 means buffer has 3 Vec3s [v0_end, v1_end, v2_end] for shutter close.
    void setMotionData(const Vec3* buffer, int steps) {
        motionVertexBuffer = buffer;
        motionSteps = steps;
    }
    // pkg88-C.0 — accessor for GPU scene upload to read motion data.
    const Vec3* getMotionVertexBuffer() const { return motionVertexBuffer; }
    int getMotionSteps() const { return motionSteps; }
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

    bool loadOBJ(const std::string& filename, bool smoothNormals = false) {
        std::ifstream file(filename);
        if (!file.is_open()) return false;
        std::vector<Vec3> positions;
        std::vector<Vec2> uvs;
        struct Face { int v[3]; int t[3]; };          // triangulated faces
        std::vector<Face> faces;
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
                    Face f;
                    f.v[0] = vi[0]; f.v[1] = vi[i]; f.v[2] = vi[i + 1];
                    f.t[0] = ti.size() > 0     ? ti[0]     : -1;
                    f.t[1] = ti.size() > i     ? ti[i]     : -1;
                    f.t[2] = ti.size() > i + 1 ? ti[i + 1] : -1;
                    faces.push_back(f);
                }
            }
        }
        if (faces.empty()) return false;

        // Optional smooth shading: area-weighted per-vertex normals. The
        // (un-normalized) face normal cross(e1,e2) has magnitude 2*area, so
        // accumulating it into each vertex gives the standard area-weighted
        // average. A finely-tessellated smooth surface (e.g. a cut-glass mesh
        // with no vertex normals in the .obj) then refracts continuously instead
        // of per-facet, which is essential for clean dielectric caustics.
        std::vector<Vec3> vnormals;
        if (smoothNormals) {
            vnormals.assign(positions.size(), Vec3(0, 0, 0));
            for (const auto& f : faces) {
                Vec3 fn = (positions[f.v[1]] - positions[f.v[0]])
                              .cross(positions[f.v[2]] - positions[f.v[0]]);
                vnormals[f.v[0]] = vnormals[f.v[0]] + fn;
                vnormals[f.v[1]] = vnormals[f.v[1]] + fn;
                vnormals[f.v[2]] = vnormals[f.v[2]] + fn;
            }
            for (auto& n : vnormals) if (n.length2() > 0.0f) n = n.normalized();
        }

        auto uvAt = [&](int idx, Vec2 dflt) {
            return (idx >= 0 && idx < static_cast<int>(uvs.size())) ? uvs[idx] : dflt;
        };
        for (const auto& f : faces) {
            auto tri = std::make_shared<Triangle>(
                positions[f.v[0]], positions[f.v[1]], positions[f.v[2]],
                uvAt(f.t[0], Vec2(0, 0)), uvAt(f.t[1], Vec2(1, 0)), uvAt(f.t[2], Vec2(0, 1)),
                material);
            if (smoothNormals)
                tri->setVertexNormals(vnormals[f.v[0]], vnormals[f.v[1]], vnormals[f.v[2]]);
            triangles.push_back(tri);
        }
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

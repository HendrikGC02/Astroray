#pragma once
// pkg225 Stage 1 — CPU ray-curve (swept-circle "thick" cross-section) intersection.
//
// ALGORITHM (cited, not invented — CLAUDE.md §6; full research note at
// .astroray_plan/docs/pkg225-curve-intersect-research.md):
//
//   pbrt-v3 Curve::Intersect / Curve::recursiveIntersect, CurveType::Cylinder
//   branch. Source: mmp/pbrt-v3, src/shapes/curve.cpp
//   (https://github.com/mmp/pbrt-v3/blob/master/src/shapes/curve.cpp),
//   copyright Matt Pharr / Greg Humphreys / Wenzel Jakob, BSD-2-Clause.
//   Fetched and diffed verbatim against the upstream source 2026-08-31.
//
// SUMMARY: build a ray-local orthonormal frame (z = ray direction, x/y chosen
// so the curve's control hull has minimal y-extent — pbrt's LookAt trick);
// project the curve's cubic-Bezier control hull into that frame; recursively
// split the Bezier hull (de Casteljau) to an adaptively-chosen depth; at the
// leaf, treat the now-near-flat sub-segment as a 2D "distance to chord" width
// test (perpendicular distance in the local x/y plane vs. the interpolated
// radius). The "Cylinder" (a.k.a. thick / swept-circle, per the pkg225 spec)
// curve type additionally reconstructs a genuinely-round shading normal by
// rotating the flat perpendicular derivative around the true curve tangent by
// an angle proportional to which side of the ray-facing plane the true curve
// point falls on (theta = lerp(v, -90deg, +90deg) — a single ray intersection
// can only ever see the near hemisphere of a round fiber, so v spans a half
// turn, not a full 0-360 azimuth; see the HitRecord::hair_v comment in
// raytracer.h).
//
// Astroray stores curves directly in WORLD SPACE (like Triangle/Sphere — no
// object-to-world Transform step, unlike pbrt's general Shape), so the
// WorldToObject/ObjectToWorld transform steps in pbrt's algorithm are
// dropped; the ray-local frame is built directly from world-space points.
// Astroray's Ray direction is always normalized (Ray ctor), so pbrt's
// `rayLength` scaling is always 1 and drops out.
//
// pbrt's algorithm is parametrized by WIDTH (diameter). The pkg225 spec's
// CurveSegment stores per-endpoint RADIUS ("One segment = 4 control points +
// per-endpoint radius"), so every pbrt `width`/`hitWidth` term below is
// substituted 1:1 with `2*radius` (hitWidth*hitWidth*0.25 == radius*radius).
//
// CATMULL-ROM -> BEZIER: Blender's `Curves` data-block (and Cycles) use
// uniform Catmull-Rom (tension 1/2); pbrt's algorithm consumes a Bezier
// control hull. The bridge is the standard cubic-Hermite -> Bezier identity
// (CLAUDE.md §6 "trivial textbook math"), cross-checked against Cycles'
// `catmull_rom_basis_eval` (kernel/geom/curve_intersect.h, Apache-2.0) in the
// research note.
//
// PHANTOM ENDPOINTS: `CurveStrip::buildCurveSegments()` follows Cycles'
// convention exactly — Cycles' curve_intersect.h clamps the adjacent-key
// index to the segment's own endpoint (`ka = max(k0-1, first_key)`,
// `kb = min(k1+1, last_key)`), i.e. the phantom point is a DUPLICATE of the
// nearest real endpoint, not a mirrored extrapolation.
#include "raytracer.h"
#include <algorithm>
#include <cmath>
#include <vector>

class CurveSegment : public Hittable {
public:
    // p0..p3: Catmull-Rom control window (on-curve span is p1 -> p2, per the
    // strand's parent-strip phantom-endpoint handling). radius0/radius1: the
    // swept-circle radius at p1 (u=0) and p2 (u=1), linearly interpolated.
    CurveSegment(const Vec3& p0, const Vec3& p1, const Vec3& p2, const Vec3& p3,
                 float radius0, float radius1, std::shared_ptr<Material> material)
        : radius0_(radius0), radius1_(radius1), material_(material),
          emissive_(material ? material->isEmissive() : false) {
        // Uniform (tension 1/2) Catmull-Rom -> cubic Bezier hull:
        // B0=P1, B1=P1+(P2-P0)/6, B2=P2-(P3-P1)/6, B3=P2.
        bezier_[0] = p1;
        bezier_[1] = p1 + (p2 - p0) * (1.0f / 6.0f);
        bezier_[2] = p2 - (p3 - p1) * (1.0f / 6.0f);
        bezier_[3] = p2;
    }

    bool hit(const Ray& r, float tMin, float tMax, HitRecord& rec) const override {
        Vec3 zAxis = r.direction;  // already normalized (Ray ctor)
        Vec3 chord = bezier_[3] - bezier_[0];
        Vec3 dxHint = zAxis.cross(chord);
        Vec3 xAxis, yAxis;
        if (dxHint.length2() < 1e-12f) {
            // Ray parallel to the chord (or degenerate zero-length hull) — pbrt
            // falls back to an arbitrary orthonormal frame (CoordinateSystem()).
            buildOrthonormalBasis(zAxis, xAxis, yAxis);
        } else {
            Vec3 up = dxHint.normalized();
            xAxis = up.cross(zAxis).normalized();
            yAxis = zAxis.cross(xAxis);
        }

        Vec3 cp[4];
        for (int i = 0; i < 4; ++i) {
            Vec3 d = bezier_[i] - r.origin;
            cp[i] = Vec3(d.dot(xAxis), d.dot(yAxis), d.dot(zAxis));
        }

        float maxRadius = std::max(radius0_, radius1_);
        if (!boundsOverlapRay(cp, maxRadius, tMin, tMax)) return false;

        // Adaptive max recursion depth (pbrt's L0/eps flatness heuristic).
        float L0 = 0.0f;
        for (int i = 0; i < 2; ++i) {
            L0 = std::max(L0, std::abs(cp[i].x - 2 * cp[i + 1].x + cp[i + 2].x));
            L0 = std::max(L0, std::abs(cp[i].y - 2 * cp[i + 1].y + cp[i + 2].y));
            L0 = std::max(L0, std::abs(cp[i].z - 2 * cp[i + 1].z + cp[i + 2].z));
        }
        float eps = maxRadius * 0.1f;  // pbrt: max(width)*0.05, width = 2*radius
        int maxDepth = 0;
        if (L0 > 0.0f && eps > 0.0f) {
            float val = 1.41421356f * 6.0f * L0 / (8.0f * eps);
            if (val >= 1.0f) {
                int log2v = static_cast<int>(std::floor(std::log2(val) + 0.5f));  // round-to-nearest
                maxDepth = std::clamp(log2v / 2, 0, 10);
            }
        }

        return recursiveIntersect(r, tMin, tMax, cp, xAxis, yAxis, zAxis, 0.0f, 1.0f, maxDepth, rec);
    }

    bool boundingBox(AABB& box) const override {
        Vec3 minP = bezier_[0], maxP = bezier_[0];
        for (int i = 1; i < 4; ++i) {
            minP = Vec3::min(minP, bezier_[i]);
            maxP = Vec3::max(maxP, bezier_[i]);
        }
        float maxRadius = std::max(radius0_, radius1_);
        box = AABB(minP - Vec3(maxRadius), maxP + Vec3(maxRadius));
        return true;
    }

    bool isLight() const override { return emissive_; }
    Vec3 emittedRadiance() const override { return material_->getEmission(); }

    const Vec3* bezierHull() const { return bezier_; }
    float getRadius0() const { return radius0_; }
    float getRadius1() const { return radius1_; }
    // pkg225 Stage 3 — GPU scene upload reads the material to dedup into the
    // GMaterial table (mirrors Triangle::getMaterial / Sphere::getMaterial).
    std::shared_ptr<Material> getMaterial() const { return material_; }

private:
    Vec3 bezier_[4];
    float radius0_, radius1_;
    std::shared_ptr<Material> material_;
    bool emissive_;

    float lerpRadius(float u) const { return radius0_ + (radius1_ - radius0_) * u; }

    static Vec3 lerp3(float t, const Vec3& a, const Vec3& b) { return a + (b - a) * t; }

    // pbrt SubdivideBezier — de Casteljau midpoint split, 4 -> 7 control points.
    static void subdivideBezier(const Vec3 cp[4], Vec3 out[7]) {
        out[0] = cp[0];
        out[1] = (cp[0] + cp[1]) * 0.5f;
        out[2] = (cp[0] + cp[1] * 2.0f + cp[2]) * 0.25f;
        out[3] = (cp[0] + cp[1] * 3.0f + cp[2] * 3.0f + cp[3]) * 0.125f;
        out[4] = (cp[1] + cp[2] * 2.0f + cp[3]) * 0.25f;
        out[5] = (cp[2] + cp[3]) * 0.5f;
        out[6] = cp[3];
    }

    // pbrt EvalBezier — de Casteljau evaluation + derivative.
    static Vec3 evalBezier(const Vec3 cp[4], float u, Vec3* deriv = nullptr) {
        Vec3 cp1[3] = { lerp3(u, cp[0], cp[1]), lerp3(u, cp[1], cp[2]), lerp3(u, cp[2], cp[3]) };
        Vec3 cp2[2] = { lerp3(u, cp1[0], cp1[1]), lerp3(u, cp1[1], cp1[2]) };
        if (deriv) {
            if ((cp2[1] - cp2[0]).length2() > 0.0f) *deriv = (cp2[1] - cp2[0]) * 3.0f;
            else *deriv = cp[3] - cp[0];  // degenerate: punt to chord (pbrt's own comment)
        }
        return lerp3(u, cp2[0], cp2[1]);
    }

    // Rodrigues' rotation formula (standard; rotates vector v by angleRad
    // around unit axis axisUnit).
    static Vec3 rotateAroundAxis(const Vec3& v, const Vec3& axisUnit, float angleRad) {
        float c = std::cos(angleRad), s = std::sin(angleRad);
        return v * c + axisUnit.cross(v) * s + axisUnit * (axisUnit.dot(v) * (1.0f - c));
    }

    // pbrt's y-then-x-then-z ray-local-frame AABB reject, shared by the top
    // level and each recursion step's per-half-segment prune.
    static bool boundsOverlapRay(const Vec3 cp[4], float radius, float tMin, float tMax) {
        float yMax = std::max({cp[0].y, cp[1].y, cp[2].y, cp[3].y});
        float yMin = std::min({cp[0].y, cp[1].y, cp[2].y, cp[3].y});
        if (yMax + radius < 0 || yMin - radius > 0) return false;
        float xMax = std::max({cp[0].x, cp[1].x, cp[2].x, cp[3].x});
        float xMin = std::min({cp[0].x, cp[1].x, cp[2].x, cp[3].x});
        if (xMax + radius < 0 || xMin - radius > 0) return false;
        float zMax = std::max({cp[0].z, cp[1].z, cp[2].z, cp[3].z});
        float zMin = std::min({cp[0].z, cp[1].z, cp[2].z, cp[3].z});
        if (zMax + radius < tMin || zMin - radius > tMax) return false;
        return true;
    }

    // pbrt Curve::recursiveIntersect, ported to Astroray's Vec3/HitRecord.
    // tMax is narrowed as closer hits are found (both half-segments are still
    // tested — a curve segment isn't guaranteed front-to-back split — so the
    // nearer of the two candidate hits wins, matching a normal Hittable::hit
    // tMax-narrowing contract).
    bool recursiveIntersect(const Ray& r, float tMin, float tMax, const Vec3 cp[4],
                             const Vec3& xAxis, const Vec3& yAxis, const Vec3& zAxis,
                             float u0, float u1, int depth, HitRecord& rec) const {
        if (depth > 0) {
            Vec3 split[7];
            subdivideBezier(cp, split);
            float uMid = (u0 + u1) * 0.5f;
            float uArr[3] = {u0, uMid, u1};
            bool hitAny = false;
            const Vec3* segCp = split;
            for (int seg = 0; seg < 2; ++seg, segCp += 3) {
                float rMax = std::max(lerpRadius(uArr[seg]), lerpRadius(uArr[seg + 1]));
                if (!boundsOverlapRay(segCp, rMax, tMin, tMax)) continue;
                HitRecord sub;
                if (recursiveIntersect(r, tMin, tMax, segCp, xAxis, yAxis, zAxis,
                                        uArr[seg], uArr[seg + 1], depth - 1, sub)) {
                    hitAny = true;
                    tMax = sub.t;   // tighten so the other half can't report a farther hit
                    rec = sub;
                }
            }
            return hitAny;
        }

        // Leaf: flat 2D "distance to chord" width test (pbrt's flattened
        // ray-curve test).
        float edge0 = (cp[1].y - cp[0].y) * -cp[0].y + cp[0].x * (cp[0].x - cp[1].x);
        if (edge0 < 0) return false;
        float edge1 = (cp[2].y - cp[3].y) * -cp[3].y + cp[3].x * (cp[3].x - cp[2].x);
        if (edge1 < 0) return false;

        float segDirX = cp[3].x - cp[0].x, segDirY = cp[3].y - cp[0].y;
        float denom = segDirX * segDirX + segDirY * segDirY;
        if (denom == 0.0f) return false;
        float w = (-cp[0].x * segDirX + -cp[0].y * segDirY) / denom;

        float u = std::clamp(u0 + (u1 - u0) * w, u0, u1);
        float hitRadius = lerpRadius(u);
        if (hitRadius <= 0.0f) return false;

        Vec3 dpcdw;
        Vec3 pc = evalBezier(cp, std::clamp(w, 0.0f, 1.0f), &dpcdw);
        float distSq = pc.x * pc.x + pc.y * pc.y;
        if (distSq > hitRadius * hitRadius) return false;
        if (pc.z < tMin || pc.z > tMax) return false;

        float dist = std::sqrt(distSq);
        float edgeFunc = dpcdw.x * -pc.y + pc.x * dpcdw.y;
        float v = (edgeFunc > 0.0f) ? 0.5f + dist / (2.0f * hitRadius)
                                     : 0.5f - dist / (2.0f * hitRadius);

        Vec3 dpdu;
        evalBezier(bezier_, u, &dpdu);  // full-hull (world-space) tangent at global u
        if (dpdu.length2() == 0.0f) return false;  // degenerate curve; pbrt CHECK_NE's, we bail

        // Cylinder (swept-circle) shading frame: rotate the flat perpendicular
        // around the true tangent by theta = lerp(v, -90deg, +90deg).
        Vec3 dpduPlane(dpdu.dot(xAxis), dpdu.dot(yAxis), dpdu.dot(zAxis));
        Vec3 dpduPlaneAxis = dpduPlane.normalized();
        Vec3 dpdvPlane = Vec3(-dpduPlane.y, dpduPlane.x, 0.0f);
        dpdvPlane = (dpdvPlane.length2() > 0.0f) ? dpdvPlane.normalized() * (2.0f * hitRadius)
                                                  : Vec3(2.0f * hitRadius, 0, 0);
        float theta = (v - 0.5f) * static_cast<float>(M_PI);  // lerp(v,-90,90) in radians
        Vec3 dpdvPlaneRot = rotateAroundAxis(dpdvPlane, dpduPlaneAxis, -theta);
        Vec3 dpdv = dpdvPlaneRot.x * xAxis + dpdvPlaneRot.y * yAxis + dpdvPlaneRot.z * zAxis;

        rec.t = pc.z;
        rec.point = r.at(rec.t);
        rec.objectPoint = rec.point;
        Vec3 outwardNormal = dpdu.cross(dpdv).normalized();
        // setFaceNormal (raytracer.h) flips outwardNormal to face the incoming
        // ray and derives frontFace/tangent/bitangent — the same convention
        // Sphere/Triangle use, so downstream materials (Lambertian etc.) see a
        // consistently-oriented normal regardless of which side of the fiber
        // the ray approached from.
        rec.setFaceNormal(r, outwardNormal);
        // pkg178-style override: the curve's own tangent (dpdu, along the
        // strand) is the physically meaningful shading tangent, replacing
        // setFaceNormal's arbitrary buildOrthonormalBasis fallback — needed by
        // the Stage-2 hair BSDF for its longitudinal/azimuthal frame.
        rec.uvTangent = dpdu.normalized();
        rec.uvBitangentSign = 1.0f;
        rec.uv = Vec2(u, v);
        rec.hair_u = u;
        rec.hair_v = v;
        rec.material = material_;
        rec.hitObject = this;
        return true;
    }
};

// CurveStrip — an ordered strand of positions + per-point radii. Splits into
// CurveSegment objects, one per consecutive point pair, using Cycles'
// clamped-duplicate phantom-endpoint convention (see file-header comment).
class CurveStrip {
public:
    std::vector<Vec3> points;
    std::vector<float> radii;  // same length as points

    std::vector<std::shared_ptr<CurveSegment>> buildCurveSegments(
            std::shared_ptr<Material> material) const {
        std::vector<std::shared_ptr<CurveSegment>> segments;
        int n = static_cast<int>(points.size());
        if (n < 2 || static_cast<int>(radii.size()) != n) return segments;
        segments.reserve(n - 1);
        for (int i = 0; i < n - 1; ++i) {
            const Vec3& p1 = points[i];
            const Vec3& p2 = points[i + 1];
            const Vec3& p0 = (i == 0) ? points[i] : points[i - 1];
            const Vec3& p3 = (i == n - 2) ? points[i + 1] : points[i + 2];
            segments.push_back(std::make_shared<CurveSegment>(
                p0, p1, p2, p3, radii[i], radii[i + 1], material));
        }
        return segments;
    }
};

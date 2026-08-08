#pragma once
// pkg106 Chunk B — surface (u,v) parameterization partials for the analytic
// manifold constraint Jacobian (half_vector_constraint.h).
//
// The analytic Jacobian (Cycles mnee.h / Hanika 2015 §5) needs the position and
// normal partials dp_du, dp_dv, dn_du, dn_dv at the manifold vertex. Astroray's
// HitRecord only carries an arbitrary buildOrthonormalBasis tangent frame, not
// the true surface partials — and bloating that hot struct with 4 extra Vec3
// for a caustic-caster-only feature is wasteful (CLAUDE.md §2). These helpers
// compute the partials on demand from the primitive geometry; the manifold
// reprojection (which already has the primitive at the vertex) calls them.
//
// dn_du / dn_dv are derivatives of the UNIT normal and are therefore always
// perpendicular to n (a requirement of halfVectorConstraintJacobian).

#include "../../raytracer.h"
#include <cmath>

namespace astroray::manifold {

// Triangle barycentric parameterization p(u,v) = v0 + u*(v1-v0) + v*(v2-v0):
//   dp_du = v1 - v0,  dp_dv = v2 - v0.
// Flat-shaded facet => the geometric normal is constant across the face, so
// dn_du = dn_dv = 0 (no edge-crossing discontinuity, unlike a finite-difference
// step — this is the whole point of the analytic Jacobian on triangle meshes).
inline void trianglePartials(const Vec3& v0, const Vec3& v1, const Vec3& v2,
                             Vec3& dp_du, Vec3& dp_dv,
                             Vec3& dn_du, Vec3& dn_dv) {
    dp_du = v1 - v0;
    dp_dv = v2 - v0;
    dn_du = Vec3(0.0f);
    dn_dv = Vec3(0.0f);
}

// Smooth-shaded triangle: interpolated shading normal n(u,v) =
// normalize(n0 + u*(n1-n0) + v*(n2-n0)). The unit-normal partials are the
// derivative of that normalization, projected perpendicular to n.
// (Chunk B targets flat facets; this overload is provided for completeness and
// future smooth-prism support — Cycles mnee.h uses the analogous shading-normal
// interpolation.)
inline void trianglePartialsSmooth(const Vec3& v0, const Vec3& v1, const Vec3& v2,
                                   const Vec3& n0, const Vec3& n1, const Vec3& n2,
                                   float u, float v,
                                   Vec3& dp_du, Vec3& dp_dv,
                                   Vec3& dn_du, Vec3& dn_dv) {
    dp_du = v1 - v0;
    dp_dv = v2 - v0;
    Vec3 ni = n0 + (n1 - n0) * u + (n2 - n0) * v;
    float len = std::sqrt(ni.length2());
    if (len < 1e-12f) { dn_du = Vec3(0.0f); dn_dv = Vec3(0.0f); return; }
    float invLen = 1.0f / len;
    Vec3 nhat = ni * invLen;
    // d/du normalize(ni) = (I - nhat nhat^T) (dni/du) / |ni|
    Vec3 dni_du = n1 - n0;
    Vec3 dni_dv = n2 - n0;
    dn_du = (dni_du - nhat * nhat.dot(dni_du)) * invLen;
    dn_dv = (dni_dv - nhat * nhat.dot(dni_dv)) * invLen;
}

// Sphere of radius r centred at `center`, evaluated at surface point p
// (n = (p-center)/r). Build an orthonormal tangent pair; the unit normal
// rotates with the tangent step at rate 1/r, so dn = dp / r (perpendicular to n,
// as required).
inline void spherePartials(const Vec3& center, const Vec3& p, float radius,
                           Vec3& dp_du, Vec3& dp_dv,
                           Vec3& dn_du, Vec3& dn_dv) {
    float invR = (radius > 1e-12f) ? (1.0f / radius) : 0.0f;
    Vec3 n = (p - center) * invR;
    Vec3 a = (std::fabs(n.x) > 0.9f) ? Vec3(0.0f, 1.0f, 0.0f) : Vec3(1.0f, 0.0f, 0.0f);
    Vec3 s = a - n * a.dot(n);
    float ls = std::sqrt(s.length2());
    s = (ls > 1e-12f) ? s * (1.0f / ls) : Vec3(1.0f, 0.0f, 0.0f);
    Vec3 t = n.cross(s);
    dp_du = s;
    dp_dv = t;
    dn_du = s * invR;
    dn_dv = t * invR;
}

// pkg178 Stage-3b PR-3 — UV-aligned shading tangent for anisotropy (PR-4).
// Maps the barycentric position partials (dp_du/dp_dv from trianglePartials) into
// the texture-U world direction by inverting the 2x2 UV Jacobian:
//   [dP/dU_tex  dP/dV_tex] = [dp_du  dp_dv] * inv([[du1 du2],[dv1 dv2]])
// then Gram-Schmidt against the shading normal N and normalize.
// Reference: Lengyel, "Computing Tangent Space Basis Vectors for an Arbitrary
// Mesh" (Terathon, 2001). CPU twin of Cycles' dPdu tangent
// (intern/cycles/kernel/geom/triangle.h, Apache-2.0), which Blender's Principled
// BSDF uses as the default anisotropy tangent.
//
// Returns true and fills outTangent (unit-length, perpendicular to N) plus
// outSign (+/-1 UV handedness, so the consumer forms bitangent =
// outSign * cross(N, outTangent)). Returns false on a degenerate UV mapping
// (zero UV-space area) or a degenerate projection (dP/dU parallel to N); the
// caller then keeps its arbitrary-frame fallback.
//
// (w0,w1,w2) are the active-layer UVs at the triangle's three vertices; pass the
// SAME (motion-interpolated) positions p0/p1/p2 used for the intersection.
inline bool uvAlignedTangent(const Vec3& p0, const Vec3& p1, const Vec3& p2,
                             const Vec2& w0, const Vec2& w1, const Vec2& w2,
                             const Vec3& N, Vec3& outTangent, float& outSign) {
    Vec3 dp_du, dp_dv, dn_du, dn_dv;
    trianglePartials(p0, p1, p2, dp_du, dp_dv, dn_du, dn_dv);  // dp_du=p1-p0, dp_dv=p2-p0
    float du1 = w1.u - w0.u, dv1 = w1.v - w0.v;
    float du2 = w2.u - w0.u, dv2 = w2.v - w0.v;
    float det = du1 * dv2 - du2 * dv1;
    if (std::fabs(det) <= 1e-12f) return false;  // degenerate UV mapping
    float invDet = 1.0f / det;
    Vec3 T  = (dp_du * dv2 - dp_dv * dv1) * invDet;  // dP/dU_tex
    Vec3 Bt = (dp_dv * du1 - dp_du * du2) * invDet;  // dP/dV_tex (handedness only)
    Vec3 Tortho = T - N * N.dot(T);
    float tlen2 = Tortho.length2();
    if (tlen2 <= 1e-12f) return false;  // T parallel to N
    outTangent = Tortho * (1.0f / std::sqrt(tlen2));
    outSign = (N.cross(outTangent).dot(Bt) < 0.0f) ? -1.0f : 1.0f;
    return true;
}

}  // namespace astroray::manifold

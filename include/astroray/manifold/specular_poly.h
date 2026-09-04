#pragma once
// pkg127 — Specular Polynomials for the SMS seed stage (sphere caster).
//
// Deterministic, seed-free enumeration of every admissible single-vertex
// specular path on an analytic sphere caster, replacing the stochastic
// uniform-seed + Newton search of sms_attempt.h. The polynomial's real roots
// are ALL the manifold vertices for the (x0, light, sphere) configuration — no
// convergence basin, no "one solution per seed" miss.
//
// Method — re-derived from the open-access paper (CLAUDE.md §6, no invented
// algorithm):
//   Fan, Guo, Wang, Xiao, Zhang, Zhou, Chen, Hong, Guo, Yan,
//     "Specular Polynomials", ACM TOG 43(4) (SIGGRAPH 2024), article 126,
//     DOI 10.1145/3658132, arXiv:2405.13409. Paper text is CC BY 4.0.
//     §3.2 generalized half-vector constraint h_i x n_i = 0 with
//     h = w_i + eta*w_o (identical to Hanika 2015 / half_vector_constraint.h);
//     §3.3 "square form" removes the norm denominators of the angularity
//     condition; §4.1-4.2 univariate real-root solving.
//   Reference implementation github.com/mollnn/spoly is UNLICENSED (GitHub API
//     reports license=null) — NOT ported. Only the CC BY 4.0 paper math is used.
//   Real-root finder follows the derivative-subdivision method of
//     Yuksel, "High-Performance Polynomial Root Finding for Graphics",
//     Proc. ACM CGIT 5(3) (HPG 2022), which the paper cites (§2) and which
//     cyCodeBase/cyPolynomial (MIT) implements — re-expressed here, no source
//     copied.
//
// SPHERE SPECIALIZATION (exact, not the paper's approximate triangle mapping).
// For a single specular vertex on a sphere the normal passes through the
// centre, so Snell/reflection keep w_i, w_o, n coplanar: the vertex lies
// exactly in the plane through (x0, x2, centre). Parameterising the great
// circle in that plane by one angle theta collapses the constraint to a single
// variable. Squaring the angularity condition (paper §3.3) and substituting the
// Weierstrass half-angle t = tan(theta/2) gives a degree-6 polynomial in t
// whose real roots enumerate every candidate vertex. This is the sphere form of
// the paper's "collapse every coordinate to u_1", and it is EXACT — the
// 6-piece rational sqrt fit the paper needs for triangle refraction (§3.5, error
// < 1e-3) is unnecessary here, removing the biggest correctness risk for the
// spectral caustic path. Validated numerically against a brute-force angular
// scan (scratchpad/proto_specpoly_sphere.py) across refraction / reflection /
// dispersive-eta cases: poly real roots == brute-force roots to < 1e-4 rad.
//
// This header is original Astroray code (MIT). Sphere path only; the triangle /
// two-bounce cases are later pkg127 phases.

#include "../../raytracer.h"
#include <cmath>

namespace astroray::manifold {
namespace specpoly {

// Sphere single-vertex square form is degree 6 in t = tan(theta/2).
inline constexpr int kSpherePolyDeg = 6;
inline constexpr int kMaxRoots      = 8;  // headroom over the 6 real roots

// ---------------------------------------------------------------------------
// Tiny fixed-degree real-polynomial helpers (coeff c[i] multiplies t^i).
// ---------------------------------------------------------------------------
inline float polyEval(const float* c, int deg, float t) {
    float r = c[deg];
    for (int i = deg - 1; i >= 0; --i) r = r * t + c[i];
    return r;
}

// out[0..na+nb-2] = a * b. Caller sizes out to at least na+nb-1.
inline int polyMul(const float* a, int na, const float* b, int nb, float* out) {
    const int no = na + nb - 1;
    for (int i = 0; i < no; ++i) out[i] = 0.0f;
    for (int i = 0; i < na; ++i)
        for (int j = 0; j < nb; ++j) out[i + j] += a[i] * b[j];
    return no;
}

// ---------------------------------------------------------------------------
// Real-root finder (Yuksel 2022 derivative subdivision). Roots of p' partition
// the axis into monotone intervals; each sign change brackets exactly one root,
// found by bisection. Recursion depth == polynomial degree (<= 6 here).
// ---------------------------------------------------------------------------
inline bool bracketRoot(const float* c, int deg, float a, float b, float& root) {
    float fa = polyEval(c, deg, a);
    float fb = polyEval(c, deg, b);
    if (fa == 0.0f) { root = a; return true; }
    if (fb == 0.0f) { root = b; return true; }
    if (fa * fb > 0.0f) return false;
    for (int it = 0; it < 80; ++it) {
        const float m = 0.5f * (a + b);
        if ((b - a) < 1e-9f * (1.0f + std::fabs(m))) { root = m; return true; }
        const float fm = polyEval(c, deg, m);
        if (fm == 0.0f) { root = m; return true; }
        if (fa * fm < 0.0f) { b = m; fb = fm; }
        else               { a = m; fa = fm; }
    }
    root = 0.5f * (a + b);
    return true;
}

// Fills out[] with the real roots of c[0..deg]; returns the count (<= deg).
inline int realRoots(const float* c, int deg, float* out) {
    while (deg > 0 && std::fabs(c[deg]) < 1e-30f) --deg;  // drop ~0 leading terms
    if (deg <= 0) return 0;
    if (deg == 1) {
        if (std::fabs(c[1]) < 1e-30f) return 0;
        out[0] = -c[0] / c[1];
        return 1;
    }
    float d[kSpherePolyDeg + 1];
    for (int i = 1; i <= deg; ++i) d[i - 1] = c[i] * static_cast<float>(i);
    float crit[kSpherePolyDeg + 1];
    int nc = realRoots(d, deg - 1, crit);
    for (int i = 1; i < nc; ++i) {  // insertion sort (nc <= 5)
        const float k = crit[i];
        int j = i - 1;
        while (j >= 0 && crit[j] > k) { crit[j + 1] = crit[j]; --j; }
        crit[j + 1] = k;
    }
    // Lagrange/Cauchy bound: all real roots lie in [-B, B].
    float B = 0.0f;
    const float invLead = 1.0f / c[deg];
    for (int i = 0; i < deg; ++i) {
        const float v = std::fabs(c[i] * invLead);
        if (v > B) B = v;
    }
    B += 1.0f;
    float pts[kSpherePolyDeg + 3];
    int np = 0;
    pts[np++] = -B;
    for (int i = 0; i < nc; ++i)
        if (crit[i] > -B && crit[i] < B) pts[np++] = crit[i];
    pts[np++] = B;
    int n = 0;
    for (int i = 0; i + 1 < np; ++i) {
        float root;
        if (bracketRoot(c, deg, pts[i], pts[i + 1], root)) out[n++] = root;
    }
    return n;
}

// ---------------------------------------------------------------------------
// Sphere single-vertex specular polynomial.
//
// Working in the plane through (x0, x2, centre) with in-plane coords
//   a = (a0, a1) = proj(x0 - centre),  b = (b0, b1) = proj(x2 - centre),
// the vertex is p(theta) = r*(cos, sin), normal n = (cos, sin). With
//   Ci = n x (a - p) = a1*cos - a0*sin,   Ro^2 = |b - p|^2, etc.,
// the signed angularity residual is  g = Ci/Ri + eta*Co/Ro. Squaring
//   g = 0  <=>  Ci^2 Ro^2 - eta^2 Co^2 Ri^2 = 0,
// and the Weierstrass substitution turns the LHS into the degree-6 t-poly built
// below (validated in proto_specpoly_sphere.py). Squaring admits superfluous
// (sign-flipped) roots; the caller filters them with signedResidual().
// ---------------------------------------------------------------------------
inline void buildSpherePolyCoeffs(float a0, float a1, float b0, float b1,
                                  float r, float eta, float outC[7]) {
    // Numerators over the common Weierstrass denominator D = 1 + t^2:
    //   Ci = a1*cos - a0*sin  ->  {a1, -2a0, -a1}
    //   adotn = a0*cos + a1*sin -> {a0, 2a1, -a0}
    const float Ci[3] = { a1, -2.0f * a0, -a1 };
    const float Co[3] = { b1, -2.0f * b0, -b1 };
    const float r2 = r * r;
    const float a2 = a0 * a0 + a1 * a1;
    const float b2 = b0 * b0 + b1 * b1;
    // Ri^2 * D = (|a|^2 + r^2) D - 2r*adotn ; D = {1,0,1}
    const float Ri2[3] = { a2 + r2 - 2.0f * r * a0, -4.0f * r * a1,
                           a2 + r2 + 2.0f * r * a0 };
    const float Ro2[3] = { b2 + r2 - 2.0f * r * b0, -4.0f * r * b1,
                           b2 + r2 + 2.0f * r * b0 };
    float Ci2[5], Co2[5], term1[7], term2[7];
    polyMul(Ci, 3, Ci, 3, Ci2);          // deg 4
    polyMul(Co, 3, Co, 3, Co2);          // deg 4
    polyMul(Ci2, 5, Ro2, 3, term1);      // deg 6
    polyMul(Co2, 5, Ri2, 3, term2);      // deg 6
    const float e2 = eta * eta;
    for (int i = 0; i < 7; ++i) outC[i] = term1[i] - e2 * term2[i];
}

// Signed angularity residual g(theta) at (cos, sin) — zero on a true solution,
// O(1) on a superfluous (squared) root.
inline float signedResidual(float a0, float a1, float b0, float b1,
                            float r, float eta, float ct, float st) {
    const float px = r * ct, py = r * st;
    const float Ci = a1 * ct - a0 * st;
    const float Co = b1 * ct - b0 * st;
    const float dax = a0 - px, day = a1 - py;
    const float dbx = b0 - px, dby = b1 - py;
    const float Ri = std::sqrt(dax * dax + day * day);
    const float Ro = std::sqrt(dbx * dbx + dby * dby);
    if (Ri < 1e-12f || Ro < 1e-12f) return 1e9f;
    return Ci / Ri + eta * Co / Ro;
}

struct SphereSolution {
    Vec3 x1;   // specular vertex on the sphere
    Vec3 n1;   // outward unit normal at x1
};

// Enumerate all admissible single-vertex specular solutions on the sphere for
// the configuration (x0 -> vertex -> x2). `eta` and `refraction` match
// half_vector_constraint.h's generalizedHalfVector convention (h = w_i +
// eta*w_o, eta = 1 for reflection). Returns the number of solutions written to
// out[] (up to maxOut), or -1 for the degenerate axial case (x0, x2, centre
// collinear) where the plane is undefined and the caller must fall back to
// Newton. Each solution still needs the caller's downstream physical validation
// (refraction side / TIR / visibility) exactly as the Newton path does.
inline int solveSphereSpecular(const Vec3& x0, const Vec3& x2,
                               const Vec3& center, float radius,
                               float eta, bool refraction,
                               SphereSolution* out, int maxOut) {
    const Vec3 av = x0 - center;
    const Vec3 bv = x2 - center;
    const Vec3 nplane = av.cross(bv);
    const float nl2 = nplane.length2();
    if (nl2 < 1e-12f) return -1;  // axial ring case -> Newton fallback
    const float al2 = av.length2();
    if (al2 < 1e-12f) return -1;
    const Vec3 e1 = av * (1.0f / std::sqrt(al2));
    const Vec3 nrm = nplane * (1.0f / std::sqrt(nl2));
    const Vec3 e2 = nrm.cross(e1);
    const float a0 = av.dot(e1), a1 = av.dot(e2);
    const float b0 = bv.dot(e1), b1 = bv.dot(e2);
    const float etaEff = refraction ? eta : 1.0f;

    float c[7];
    buildSpherePolyCoeffs(a0, a1, b0, b1, radius, etaEff, c);
    float troots[kMaxRoots];
    const int nr = realRoots(c, kSpherePolyDeg, troots);

    // Superfluous-root filter tolerance: true roots give |g| ~ 0; squared
    // spurious roots give |g| ~ 2*eta*|Co|/Ro = O(1). A loose bound separates
    // them cleanly while tolerating float root error.
    const float kResidualTol = 1e-3f;

    int n = 0;
    for (int i = 0; i < nr && n < maxOut; ++i) {
        float theta = 2.0f * std::atan(troots[i]);
        // One Newton polish on g(theta) to clean Weierstrass/root float error
        // (paper §4: root-finding gives the basin, a Newton polish the digits).
        for (int k = 0; k < 2; ++k) {
            const float ct = std::cos(theta), st = std::sin(theta);
            const float g = signedResidual(a0, a1, b0, b1, radius, etaEff, ct, st);
            const float h = 1e-4f;
            const float gp = signedResidual(a0, a1, b0, b1, radius, etaEff,
                                            std::cos(theta + h), std::sin(theta + h));
            const float gm = signedResidual(a0, a1, b0, b1, radius, etaEff,
                                            std::cos(theta - h), std::sin(theta - h));
            const float dg = (gp - gm) * (0.5f / h);
            if (std::fabs(dg) < 1e-9f) break;
            theta -= g / dg;
        }
        const float ct = std::cos(theta), st = std::sin(theta);
        if (std::fabs(signedResidual(a0, a1, b0, b1, radius, etaEff, ct, st)) >
            kResidualTol)
            continue;  // superfluous root
        const Vec3 nloc = (e1 * ct + e2 * st).normalized();
        // Dedup: a near-double root of the squared polynomial (a caustic, where
        // the Jacobian is near-singular) can be bracketed twice as two very
        // close roots. Merge solutions whose normals coincide (< ~1e-3 rad).
        bool dup = false;
        for (int i = 0; i < n; ++i)
            if ((out[i].n1 - nloc).length2() < 1e-6f) { dup = true; break; }
        if (dup) continue;
        out[n].n1 = nloc;
        out[n].x1 = center + nloc * radius;
        ++n;
    }

    // theta = pi (t -> +/-inf) is unreachable by the Weierstrass poly; test it.
    if (n < maxOut) {
        const float ct = -1.0f, st = 0.0f;
        if (std::fabs(signedResidual(a0, a1, b0, b1, radius, etaEff, ct, st)) <=
            kResidualTol) {
            const Vec3 nloc = (e1 * ct + e2 * st).normalized();
            bool dup = false;
            for (int i = 0; i < n; ++i)
                if ((out[i].n1 - nloc).length2() < 1e-8f) { dup = true; break; }
            if (!dup) { out[n].n1 = nloc; out[n].x1 = center + nloc * radius; ++n; }
        }
    }
    return n;
}

// ---------------------------------------------------------------------------
// pkg227 Phase 2a — analytic-sphere MULTI-BOUNCE chain (the raindrop rainbow).
//
// A specular chain on ONE sphere: refract-in -> k internal reflections ->
// refract-out (primary rainbow k=1 => 3 vertices; secondary k=2 => 4). Because
// every surface normal passes through the centre, the incidence angle is equal
// at every interaction and the whole path stays in the plane through
// (x0, light, centre) — so the exit ray is a deterministic function of a SINGLE
// parameter, the entry-point angle on the great circle. Given fixed x0 and
// light, the chains connecting them are the roots of
//   g(theta) = signed miss of the exit ray to the light,
// a UNIVARIATE, EXACT residual (real Snell, no rational sqrt-fit).
//
// This is the sphere form of the paper's variable reduction: the concentric-
// normal symmetry makes the residual directly univariate in the entry angle, so
// no hidden-variable resultant elimination is needed — equally exact, simpler
// (CLAUDE.md §2). Enumerating ALL sign changes of g captures the two branches
// that straddle the rainbow caustic fold, which a Newton-from-one-seed search
// misses. The classical deviation D(i)=2(i-t)+k(pi-2t), sin t = sin i / n
// (Descartes 1637 / Newton) is the analytic cross-check; validated to <1e-8 rad
// in scratchpad/proto_sphere_chain.py and locked by tests/test_pkg227_sphere_
// chain_unit.py.
// ---------------------------------------------------------------------------

inline constexpr int kMaxChainVerts = 4;   // entry + up to 2 reflections + exit
inline constexpr int kMaxChains     = 8;   // distinct branches per attempt

struct SphereChainSolution {
    Vec3 x[kMaxChainVerts];   // vertices in order: entry, reflections..., exit
    Vec3 n[kMaxChainVerts];   // outward unit normals at each vertex
    int  count = 0;           // number of vertices = k + 2
};

// 2D refraction (GLSL convention): d incident unit dir toward the surface, N
// unit normal facing the incident medium, eta = n_from/n_to. Writes the unit
// transmitted dir to (ox,oy); returns false on total internal reflection.
inline bool refract2(float dx, float dy, float nx, float ny, float eta,
                     float& ox, float& oy) {
    const float cosi = -(dx * nx + dy * ny);
    const float k = 1.0f - eta * eta * (1.0f - cosi * cosi);
    if (k < 0.0f) return false;
    const float f = eta * cosi - std::sqrt(k);
    float tx = eta * dx + f * nx, ty = eta * dy + f * ny;
    const float il = 1.0f / std::sqrt(tx * tx + ty * ty);
    ox = tx * il; oy = ty * il;
    return true;
}

// Far intersection of the ray (p + s*d, s>0) with the origin-centred circle of
// radius r, for p strictly inside. Writes the hit point to (ox,oy).
inline void circleExit2(float px, float py, float dx, float dy, float r,
                        float& ox, float& oy) {
    const float b = 2.0f * (px * dx + py * dy);
    const float c = px * px + py * py - r * r;
    float disc = b * b - 4.0f * c;
    if (disc < 0.0f) disc = 0.0f;
    const float s = 0.5f * (-b + std::sqrt(disc));
    ox = px + s * dx; oy = py + s * dy;
}

// Forward-trace one entry angle theta through k internal reflections, in the 2D
// plane coords (a=x0, everything relative to the sphere centre at the origin).
// On success fills the k+2 vertex angles vAng[] and the final exit dir
// (edx,edy) and exit point (epx,epy); returns false on back-face / TIR.
inline bool traceSphereChain2(float theta, float ax, float ay, float r,
                              float eta, int k, float* vAng, int& nv,
                              float& epx, float& epy, float& edx, float& edy) {
    float px = r * std::cos(theta), py = r * std::sin(theta);
    float nx = px / r, ny = py / r;                 // outward normal
    float dx = px - ax, dy = py - ay;               // incoming ray dir
    const float il0 = 1.0f / std::sqrt(dx * dx + dy * dy);
    dx *= il0; dy *= il0;
    if (dx * nx + dy * ny >= 0.0f) return false;    // must hit the front face
    nv = 0;
    vAng[nv++] = theta;                             // entry vertex
    float rx, ry;
    if (!refract2(dx, dy, nx, ny, 1.0f / eta, rx, ry)) return false;  // air->glass
    dx = rx; dy = ry;
    for (int b = 0; b < k; ++b) {                   // internal reflections
        circleExit2(px, py, dx, dy, r, px, py);
        nx = px / r; ny = py / r;
        const float dn = dx * nx + dy * ny;
        dx = dx - 2.0f * dn * nx; dy = dy - 2.0f * dn * ny;
        vAng[nv++] = std::atan2(py, px);
    }
    circleExit2(px, py, dx, dy, r, px, py);         // to the exit point
    nx = px / r; ny = py / r;
    if (!refract2(dx, dy, -nx, -ny, eta, rx, ry)) return false;       // glass->air (TIR?)
    vAng[nv++] = std::atan2(py, px);                // exit vertex
    epx = px; epy = py; edx = rx; edy = ry;
    return true;
}

// Signed perpendicular miss (2D cross product) of the chain's exit ray to the
// light at (lx,ly). NaN sentinel (returned as the large `miss` via `ok=false`)
// where the entry ray is invalid, so the sign-change scan skips that interval.
inline float sphereChainMiss2(float theta, float ax, float ay, float lx, float ly,
                              float r, float eta, int k, bool& ok) {
    float vAng[kMaxChainVerts]; int nv;
    float epx, epy, edx, edy;
    ok = traceSphereChain2(theta, ax, ay, r, eta, k, vAng, nv, epx, epy, edx, edy);
    if (!ok) return 0.0f;
    const float vx = lx - epx, vy = ly - epy;
    return edx * vy - edy * vx;
}

// Enumerate every k-reflection specular chain on the sphere connecting x0 to the
// light, by bracketing all sign changes of the univariate exit-miss residual.
// `refraction` is implied (a chain always refracts in and out); `eta` is the
// hero-wavelength IOR ratio (glass/air). Returns the number of chains written
// (<= maxOut). `nSamples` sets the residual scan resolution (default catches the
// two caustic-straddling branches; raise for very high-IOR narrow bows).
inline int solveSphereChain(const Vec3& x0, const Vec3& light,
                            const Vec3& center, float radius, float eta,
                            int reflections, SphereChainSolution* out,
                            int maxOut, int nSamples = 512) {
    const Vec3 av = x0 - center;
    const Vec3 bv = light - center;
    const Vec3 nplane = av.cross(bv);
    const float nl2 = nplane.length2();
    if (nl2 < 1e-12f) return -1;              // axial degenerate -> caller Newton
    const float al2 = av.length2();
    if (al2 < 1e-12f) return -1;
    const Vec3 e1 = av * (1.0f / std::sqrt(al2));
    const Vec3 nrm = nplane * (1.0f / std::sqrt(nl2));
    const Vec3 e2 = nrm.cross(e1);
    const float ax = av.dot(e1), ay = av.dot(e2);
    const float lx = bv.dot(e1), ly = bv.dot(e2);

    const float twoPi = 6.2831853071795864769f;
    const float dTheta = twoPi / static_cast<float>(nSamples);
    int n = 0;
    bool okPrev = false;
    float gPrev = 0.0f, thPrev = -3.14159265358979323846f;
    for (int i = 0; i <= nSamples && n < maxOut; ++i) {
        const float th = -3.14159265358979323846f + dTheta * static_cast<float>(i);
        bool ok;
        const float g = sphereChainMiss2(th, ax, ay, lx, ly, radius, eta,
                                         reflections, ok);
        if (ok && okPrev && gPrev * g < 0.0f) {
            // Bisect [thPrev, th] for the exact root.
            float a = thPrev, b = th, fa = gPrev;
            for (int it = 0; it < 60; ++it) {
                const float m = 0.5f * (a + b);
                bool okm;
                const float fm = sphereChainMiss2(m, ax, ay, lx, ly, radius, eta,
                                                  reflections, okm);
                if (!okm) break;
                if (fa * fm <= 0.0f) { b = m; }
                else { a = m; fa = fm; }
            }
            const float root = 0.5f * (a + b);
            float vAng[kMaxChainVerts]; int nv;
            float epx, epy, edx, edy;
            if (traceSphereChain2(root, ax, ay, radius, eta, reflections,
                                  vAng, nv, epx, epy, edx, edy)) {
                SphereChainSolution& sc = out[n];
                sc.count = nv;
                for (int v = 0; v < nv; ++v) {
                    const float ct = std::cos(vAng[v]), st = std::sin(vAng[v]);
                    const Vec3 nloc = (e1 * ct + e2 * st).normalized();
                    sc.n[v] = nloc;
                    sc.x[v] = center + nloc * radius;
                }
                ++n;
            }
        }
        okPrev = ok; gPrev = g; thPrev = th;
    }
    return n;
}

}  // namespace specpoly
}  // namespace astroray::manifold

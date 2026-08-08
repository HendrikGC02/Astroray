// ============================================================================
// pkg178 Stage-3b PR-3 — UV-aligned shading tangent plumbing.
//
// Standalone CPU test (NO CUDA, NO pybind, NO engine link). Exercises the real
// algorithm: manifold::uvAlignedTangent — the Lengyel inverse-UV-Jacobian helper
// that Triangle::hit calls to populate HitRecord::uvTangent. (The thin
// Triangle::hit / Sphere::hit wiring around it — call the helper when the mesh
// has UVs, else keep setFaceNormal's arbitrary-frame fallback — is validated by
// the lead's full-build bit-identity + smoke render, since constructing a
// Triangle here would drag in the engine's spectral/closure .cpp symbols.)
//
// Verifies:
//   A. axis-aligned UVs: tangent is unit, perpendicular to N, points along the
//      texture-U world direction, handedness sign correct.
//   B. rotated UVs: the tangent TRACKS the UVs (proving it is UV-derived, not the
//      arbitrary buildOrthonormalBasis frame).
//   C. tilted plane: Gram-Schmidt keeps the tangent perpendicular to N and unit.
//   D. degenerate UV mapping: returns false -> caller keeps the arbitrary-frame
//      fallback (this is the exact fallback trigger Triangle::hit relies on).
//   E. non-unit / skewed UV scale: still returns a UNIT tangent (normalization).
//
// Build & run (from the worktree root):
//   g++ -std=c++17 -O2 -I include tests/cpp/test_uv_tangent.cpp -o build_uvtan_test \
//       && ./build_uvtan_test
//   (MSVC: cl /std:c++17 /O2 /I include tests\cpp\test_uv_tangent.cpp)
//
// Exit code 0 = all assertions pass.
// ============================================================================
#include "astroray/manifold/surface_partials.h"

#include <cstdio>
#include <cmath>

static int g_fail = 0;
static void check(bool ok, const char* msg) {
    std::printf("  [%s] %s\n", ok ? "PASS" : "FAIL", msg);
    if (!ok) ++g_fail;
}
static bool approx(float a, float b, float eps = 1e-4f) { return std::fabs(a - b) < eps; }
static bool vApprox(const Vec3& a, const Vec3& b, float eps = 1e-4f) {
    return approx(a.x, b.x, eps) && approx(a.y, b.y, eps) && approx(a.z, b.z, eps);
}

int main() {
    using astroray::manifold::uvAlignedTangent;
    std::printf("pkg178 PR-3 UV-aligned tangent test\n");

    // ---- A. Axis-aligned quad, U->+X, V->+Y ----------------------------------
    std::printf("\n[A] axis-aligned UVs\n");
    {
        Vec3 p0(0,0,0), p1(1,0,0), p2(0,1,0);
        Vec2 w0(0,0), w1(1,0), w2(0,1);
        Vec3 N(0,0,1), T; float sign = 0.0f;
        bool ok = uvAlignedTangent(p0, p1, p2, w0, w1, w2, N, T, sign);
        check(ok, "succeeds");
        check(approx(T.length2(), 1.0f), "tangent is unit length");
        check(approx(T.dot(N), 0.0f), "tangent perpendicular to N");
        check(vApprox(T, Vec3(1,0,0)), "U-axis tangent points along world +X");
        check(sign > 0.0f, "handedness sign +1 (right-handed UVs)");
    }

    // ---- B. Rotated UVs: texture-U maps to world +Y (tracks UVs) --------------
    std::printf("\n[B] rotated UVs track the parameterization\n");
    {
        Vec3 p0(0,0,0), p1(1,0,0), p2(0,1,0);
        Vec2 w0(0,0), w1(0,1), w2(1,0);   // U increases toward v2(+Y), V toward v1(+X)
        Vec3 N(0,0,1), T; float sign = 0.0f;
        bool ok = uvAlignedTangent(p0, p1, p2, w0, w1, w2, N, T, sign);
        check(ok && vApprox(T, Vec3(0,1,0)), "tangent points along world +Y");
        check(sign < 0.0f, "handedness sign -1 (mirrored UVs)");
    }

    // ---- C. Tilted plane: Gram-Schmidt keeps T perpendicular & unit ----------
    std::printf("\n[C] tilted plane (Gram-Schmidt vs N)\n");
    {
        Vec3 p0(0,0,0), p1(1,0,1), p2(0,1,0);
        Vec3 N = (p1 - p0).cross(p2 - p0).normalized();
        Vec2 w0(0,0), w1(1,0), w2(0,1);
        Vec3 T; float sign = 0.0f;
        bool ok = uvAlignedTangent(p0, p1, p2, w0, w1, w2, N, T, sign);
        check(ok, "succeeds");
        check(approx(T.length2(), 1.0f), "tangent unit length");
        check(approx(T.dot(N), 0.0f), "tangent perpendicular to N");
    }

    // ---- D. Degenerate UV mapping returns false (fallback trigger) -----------
    std::printf("\n[D] degenerate UV mapping -> fallback\n");
    {
        Vec3 p0(0,0,0), p1(1,0,0), p2(0,1,0);
        Vec2 w0(0.5f,0.5f), w1(0.5f,0.5f), w2(0.5f,0.5f);  // zero UV-space area
        Vec3 N(0,0,1), T(9,9,9); float sign = 7.0f;
        bool ok = uvAlignedTangent(p0, p1, p2, w0, w1, w2, N, T, sign);
        check(!ok, "returns false -> caller keeps arbitrary-frame fallback");
    }

    // ---- E. Non-unit / skewed UV scale still yields a UNIT tangent -----------
    std::printf("\n[E] scaled UVs still normalize\n");
    {
        Vec3 p0(0,0,0), p1(2,0,0), p2(0,3,0);
        Vec2 w0(0,0), w1(4,0), w2(0,0.5f);   // anisotropic UV scale
        Vec3 N(0,0,1), T; float sign = 0.0f;
        bool ok = uvAlignedTangent(p0, p1, p2, w0, w1, w2, N, T, sign);
        check(ok, "succeeds");
        check(approx(T.length2(), 1.0f), "tangent still unit length after normalization");
        check(vApprox(T, Vec3(1,0,0)), "tangent direction along +X (U runs along the wide edge)");
    }

    std::printf("\n%s (%d failures)\n", g_fail == 0 ? "ALL PASS" : "FAILURES", g_fail);
    return g_fail == 0 ? 0 : 1;
}

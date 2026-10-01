// #1000 — watertight ray/triangle (Woop, Benthin, Wald 2013). Standalone CPU test.
// The old Moller-Trumbore |det| < 1e-6 rejection misses tiny/grazing triangles;
// the watertight test must hit them, return correct (t,u,v), and never leak
// through a shared edge.
//   g++ -std=c++17 -O2 -I include tests/cpp/test_watertight_triangle.cpp -o wt_test && ./wt_test
#include "astroray/watertight_triangle.h"
#include <cstdio>
#include <random>

static int g_fail = 0;
static void check(bool ok, const char* msg) {
    std::printf("  [%s] %s\n", ok ? "PASS" : "FAIL", msg);
    if (!ok) ++g_fail;
}

// The pre-#1000 test, kept as the "fails before" oracle.
static bool oldMT(const Vec3& p0, const Vec3& p1, const Vec3& p2, const Ray& r, float tMin, float tMax) {
    Vec3 e1 = p1 - p0, e2 = p2 - p0, h = r.direction.cross(e2);
    float a = e1.dot(h);
    if (std::fabs(a) < 1e-6f) return false;
    float f = 1.0f / a; Vec3 s = r.origin - p0;
    float u = f * s.dot(h); if (u < 0 || u > 1) return false;
    Vec3 q = s.cross(e1);
    float v = f * r.direction.dot(q); if (v < 0 || u + v > 1) return false;
    float t = f * e2.dot(q);
    return t >= tMin && t <= tMax;
}

int main() {
    using astroray::watertightTriangle;
    float t, u, v;
    {   // tiny triangle: legs 5e-4 -> |det| = 2*area = 2.5e-7 < 1e-6
        Vec3 p0(0, 0, 0), p1(5e-4f, 0, 0), p2(0, 5e-4f, 0);
        Ray r(Vec3(1e-4f, 1e-4f, 1), Vec3(0, 0, -1));
        check(!oldMT(p0, p1, p2, r, 1e-4f, 1e30f), "old MT misses the tiny triangle");
        bool h = watertightTriangle(p0, p1, p2, r, 1e-4f, 1e30f, t, u, v);
        check(h, "watertight hits the tiny triangle");
        check(std::fabs(t - 1.f) < 1e-5f && std::fabs(u - 0.2f) < 1e-4f && std::fabs(v - 0.2f) < 1e-4f,
              "t,u,v = 1, 0.2, 0.2 (u,v weight p1,p2)");
    }
    {   // grazing: big triangle, ray ~1e-6 rad off the plane
        Vec3 p0(-1, 0, -1), p1(1, 0, -1), p2(0, 0, 1);
        Vec3 d = Vec3(1, -2e-7f, 0).normalized();
        Ray r(Vec3(-0.5f, 1e-7f, 0.0f), d);
        check(!oldMT(p0, p1, p2, r, 0.f, 1e30f), "old MT misses the grazing hit");
        bool h = watertightTriangle(p0, p1, p2, r, 0.f, 1e30f, t, u, v);
        check(h, "watertight hits the grazing triangle");
    }
    {   // watertight: random rays at a quad's shared diagonal never leak
        std::mt19937 g(5); std::uniform_real_distribution<float> U(-1.f, 1.f);
        Vec3 a(-1, -1, 0), b(1, -1, 0), c(1, 1, 0), d4(-1, 1, 0);
        int leaks = 0;
        for (int i = 0; i < 200000; ++i) {
            float s = 0.9f * U(g);
            Vec3 o(s, s, 1);  // on the diagonal a-c
            Vec3 dir = Vec3(U(g) * 0.01f, U(g) * 0.01f, -1).normalized();
            Ray r(o, dir);
            bool h = watertightTriangle(a, b, c, r, 0.f, 1e30f, t, u, v) ||
                     watertightTriangle(a, c, d4, r, 0.f, 1e30f, t, u, v);
            if (!h) ++leaks;
        }
        std::printf("  leaks = %d / 200000\n", leaks);
        check(leaks == 0, "no ray leaks through the shared edge");
    }
    return g_fail ? 1 : 0;
}

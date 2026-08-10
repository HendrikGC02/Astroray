// ============================================================================
// pkg178 Stage 4 PR-1 — standalone unit test for the shared thin-film Fresnel
// utility (include/astroray/thin_film_fresnel.h). NO CUDA, NO pybind, NO engine
// link — the header is self-contained.
//
// Verifies:
//   A. Analytic-phase check: the truncated (m≤3) Airy series with the analytic
//      per-λ sensitivity matches an INDEPENDENT exact closed-form single-film
//      Airy reflectance (std::complex geometric series) at known thickness/IOR/
//      angle, per polarization — within the O(r123⁴) truncation residual.
//   B. Single-interface reduction: film IOR == substrate IOR ⇒ the film-substrate
//      interface vanishes ⇒ R == bare dielectric Fresnel(air→film), for ANY
//      thickness (no interference).
//   C. Sub-cutoff / thin-film blend continuity: at d = 0.1nm the smoothstep blend
//      collapses the film ⇒ R ≈ bare dielectric Fresnel(air→substrate).
//   D. Furnace bound: R ∈ [0,1] across a (thickness × filmIOR × substrateIOR ×
//      angle) grid — the film creates no energy.
//   E. TIR early-out: past the critical angle into a lower-index substrate the
//      bottom interface returns R = 1.
//
// Build & run (from the worktree root):
//   g++ -std=c++17 -O2 -I include tests/cpp/test_thin_film_fresnel.cpp \
//       -o build_tf_test && ./build_tf_test
//   (MSVC: cl /std:c++17 /O2 /I include tests\cpp\test_thin_film_fresnel.cpp)
// Exit code 0 = all assertions pass.
// ============================================================================
#include "astroray/thin_film_fresnel.h"
#include "astroray/thin_film_cie_table.h"

#include <cmath>
#include <complex>
#include <cstdio>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

namespace tf = astroray::thinfilm;

static int g_fail = 0;
static void check(bool ok, const char* msg) {
    std::printf("  [%s] %s\n", ok ? "PASS" : "FAIL", msg);
    if (!ok) ++g_fail;
}
static bool approx(float a, float b, float eps) { return std::fabs(a - b) < eps; }

// Dielectric single-λ iridescence via our utility (analytic spectral sensitivity).
static float utilityR(float thickness, float filmIor, float substrateN, float cosI,
                      float lambda) {
    auto S = [lambda](float argOPD) { return tf::sensitivitySpectral(argOPD, lambda); };
    return tf::fresnelIridescenceChannel<false>(1.0f, thickness, filmIor, substrateN, 0.0f,
                                                -1.0f, cosI, nullptr, S);
}

// -----------------------------------------------------------------------------
// Independent EXACT single-film Airy reflectance (Born & Wolf / Airy formula),
// double precision, infinite geometric series in closed form. Amplitude form:
//   r = (r_ab + r_bc·e^{2iβ}) / (1 + r_ab·r_bc·e^{2iβ}),  β = 2π·n1·d·cosθ2/λ.
// -----------------------------------------------------------------------------
static double amplRs(double na, double nb, double cosa, double cosb) {
    return (na * cosa - nb * cosb) / (na * cosa + nb * cosb);
}
static double amplRp(double na, double nb, double cosa, double cosb) {
    return (nb * cosa - na * cosb) / (nb * cosa + na * cosb);
}
static double exactAiryR(double thickness, double filmIor, double substrateN, double cosI,
                         double lambda) {
    // Sub-1nm blend, mirroring the utility (keeps the comparison honest at d<1).
    double n1 = filmIor;
    if (thickness < 1.0) {
        double t = thickness < 0.0 ? 0.0 : (thickness > 1.0 ? 1.0 : thickness);
        double ss = t * t * (3.0 - 2.0 * t);
        n1 = 1.0 + (filmIor - 1.0) * ss;
    }
    const double sin1 = std::sqrt(std::max(0.0, 1.0 - cosI * cosI));
    const double sin2 = sin1 / n1;                 // Snell air→film
    if (sin2 >= 1.0) return 1.0;                    // TIR at top
    const double cos2 = std::sqrt(1.0 - sin2 * sin2);
    const double sin3 = n1 * sin2 / substrateN;    // Snell film→substrate
    if (sin3 >= 1.0) return 1.0;                    // TIR at bottom
    const double cos3 = std::sqrt(1.0 - sin3 * sin3);

    const double beta = 2.0 * M_PI * n1 * thickness * cos2 / lambda;
    const std::complex<double> ph(std::cos(2.0 * beta), std::sin(2.0 * beta));

    double R = 0.0;
    for (int pol = 0; pol < 2; ++pol) {
        double r12 = pol == 0 ? amplRs(1.0, n1, cosI, cos2) : amplRp(1.0, n1, cosI, cos2);
        double r23 = pol == 0 ? amplRs(n1, substrateN, cos2, cos3)
                              : amplRp(n1, substrateN, cos2, cos3);
        std::complex<double> num = r12 + r23 * ph;
        std::complex<double> den = 1.0 + r12 * r23 * ph;
        R += std::norm(num / den);
    }
    return 0.5 * R;
}

static float bareDielectric(float cosI, float eta) {
    // average of the polarized squared amplitudes (unpolarized F).
    tf::TFDielectric d = tf::fresnelDielectricPolarized(cosI, eta);
    return 0.5f * (d.Rs + d.Rp);
}

int main() {
    std::printf("pkg178 Stage 4 PR-1 thin-film Fresnel utility tests\n");

    // ---- A. analytic-phase check vs exact closed-form Airy ----
    std::printf("A. analytic phase (truncated Airy == exact closed-form):\n");
    struct Cfg { float d, n1, n2, cos, lam; };
    const Cfg cfgs[] = {
        {300.f, 1.33f, 1.5f, 1.0f, 550.f}, {300.f, 1.33f, 1.5f, 0.7f, 550.f},
        {500.f, 1.4f, 1.8f, 0.9f, 450.f},  {200.f, 1.2f, 1.5f, 0.6f, 650.f},
        {800.f, 1.5f, 1.5f, 0.85f, 500.f}, {120.f, 1.3f, 2.0f, 0.75f, 600.f},
    };
    for (const Cfg& c : cfgs) {
        float got = utilityR(c.d, c.n1, c.n2, c.cos, c.lam);
        double ref = exactAiryR(c.d, c.n1, c.n2, c.cos, c.lam);
        char msg[192];
        std::snprintf(msg, sizeof(msg),
                      "d=%.0f n1=%.2f n2=%.2f cos=%.2f λ=%.0f: util=%.5f exact=%.5f Δ=%.2e",
                      c.d, c.n1, c.n2, c.cos, c.lam, got, ref, std::fabs(got - (float)ref));
        check(approx(got, (float)ref, 2e-3f), msg);
    }

    // ---- B. single-interface reduction (film IOR == substrate IOR) ----
    std::printf("B. film IOR == substrate IOR ⇒ bare Fresnel(air→film):\n");
    for (float d : {150.f, 500.f, 1200.f}) {
        for (float cos : {1.0f, 0.8f, 0.5f}) {
            float got = utilityR(d, 1.5f, 1.5f, cos, 550.f);
            float bare = bareDielectric(cos, 1.5f);
            char msg[160];
            std::snprintf(msg, sizeof(msg), "d=%.0f cos=%.2f: R=%.5f bare=%.5f", d, cos, got, bare);
            check(approx(got, bare, 1e-4f), msg);
        }
    }

    // ---- C. sub-cutoff blend ⇒ bare substrate Fresnel ----
    std::printf("C. d=0.1nm blend ⇒ ≈ bare Fresnel(air→substrate):\n");
    for (float cos : {1.0f, 0.7f}) {
        float got = utilityR(0.1f, 1.33f, 1.5f, cos, 550.f);
        float bare = bareDielectric(cos, 1.5f);
        char msg[160];
        std::snprintf(msg, sizeof(msg), "cos=%.2f: R=%.5f bareSubstrate=%.5f", cos, got, bare);
        check(approx(got, bare, 5e-3f), msg);
    }

    // ---- D. furnace bound over a grid (RGB leg too) ----
    std::printf("D. furnace: R ∈ [0,1] over the grid (spectral + RGB legs):\n");
    int viol = 0, cnt = 0;
    for (float d : {50.f, 150.f, 300.f, 600.f, 1500.f, 3000.f})
        for (float n1 : {1.2f, 1.5f, 1.8f})
            for (float n2 : {1.33f, 1.5f, 2.0f})
                for (float cos : {1.0f, 0.9f, 0.6f, 0.3f, 0.05f})
                    for (float lam : {440.f, 550.f, 650.f}) {
                        float rs = utilityR(d, n1, n2, cos, lam);
                        if (!(rs >= 0.0f && rs <= 1.0f)) ++viol;
                        // RGB leg
                        for (int ch = 0; ch < 3; ++ch) {
                            auto S = [ch](float a) {
                                return tf::sensitivityRGB(a, ch, tf::kThinFilmCieTable);
                            };
                            float rr = tf::fresnelIridescenceChannel<false>(
                                1.0f, d, n1, n2, 0.0f, -1.0f, cos, nullptr, S);
                            if (!(rr >= 0.0f && rr <= 1.0f)) ++viol;
                        }
                        cnt += 4;
                    }
    char msg[128];
    std::snprintf(msg, sizeof(msg), "%d samples, %d out-of-[0,1] violations", cnt, viol);
    check(viol == 0, msg);

    // ---- E. TIR early-out ⇒ R = 1 ----
    // (For an air-incident film, refraction into the denser film bounds the in-film
    // angle so the BOTTOM interface can never TIR; the reachable early-out is the
    // TOP interface with a low-index film — exercise that code path directly.)
    std::printf("E. TIR early-out ⇒ R = 1:\n");
    tf::TFDielectric dtir = tf::fresnelDielectricPolarized(0.3f, 0.6f);
    check(dtir.tir && dtir.Rs == 1.0f && dtir.Rp == 1.0f, "polarized dielectric TIR ⇒ (1,1)");
    float tir = utilityR(400.f, 0.6f, 1.5f, 0.3f, 550.f);  // top-interface TIR (film<ambient)
    char tmsg[96];
    std::snprintf(tmsg, sizeof(tmsg), "top-interface TIR: R=%.5f (expect 1.0)", tir);
    check(approx(tir, 1.0f, 1e-5f), tmsg);

    std::printf(g_fail == 0 ? "\nALL PASS\n" : "\n%d FAILURES\n", g_fail);
    return g_fail == 0 ? 0 : 1;
}

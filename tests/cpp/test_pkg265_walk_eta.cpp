// ============================================================================
// pkg265 — unit test for the Heitz-2016 dielectric random walk's radiance
// (eta^2) accounting in include/astroray/microsurface_dielectric.h.
//
// The Fig-11 vertical flip swaps the interface iors on every TRANSMISSION micro
// event and multiplies the carried radiance by (n1/n2)^2 BEFORE the swap. The
// product therefore TELESCOPES: it depends only on the PARITY of transmission
// events (= the macroscopic final side), never on the number of micro events.
// This test asserts, over many walks and many micro-bounce counts:
//   * every REFLECTED walk (even flips)      -> radianceScale == 1 exactly;
//   * every TRANSMITTED walk entering glass  -> radianceScale == 1/ior^2;
//   * every TRANSMITTED walk exiting glass   -> radianceScale == ior^2;
// regardless of how many internal reflections / re-refractions the walk took.
// A bug that applied eta^2 per micro-refraction (hypothesis (1): a triple micro
// refraction carrying eta^6) would fail this immediately.
//
// Build & run (from the worktree root, MSVC in a vcvars shell):
//   cl /std:c++17 /O2 /EHsc /I include tests\cpp\test_pkg265_walk_eta.cpp \
//      /Fe:build_walk_eta_test.exe && build_walk_eta_test.exe
// Exit code 0 = all assertions pass.
// ============================================================================
#include "astroray/microsurface_dielectric.h"

#include <cstdio>
#include <cmath>
#include <random>

using astroray::msdiel::WalkSample;
using astroray::msdiel::sampleWalk;

static int runIor(float ior, std::mt19937& gen) {
    std::uniform_real_distribution<float> dist(0.0f, 1.0f);
    auto rng = [&]() { return dist(gen); };

    const float inv2 = 1.0f / (ior * ior);
    const float fwd2 = ior * ior;
    const float tol = 1e-4f;   // exact up to float round-off of the telescoped product

    int fails = 0;
    long nRefl = 0, nTransIn = 0, nTransOut = 0, nDead = 0, nTotal = 0;
    float maxErrRefl = 0.0f, maxErrTransIn = 0.0f, maxErrTransOut = 0.0f;

    // Sweep roughness (drives the mean micro-bounce count: high alpha => many
    // internal events) and both interface sides.
    for (float rough : {0.2f, 0.5f, 0.85f, 1.0f}) {
        float alpha = std::max(rough * rough, 0.0064f);
        for (int side = 0; side < 2; ++side) {
            bool entering = (side == 0);
            for (int i = 0; i < 200000; ++i) {
                // random near-normal-to-grazing incidence in the +z hemisphere
                float u = dist(gen), v = dist(gen);
                float cz = 0.05f + 0.94f * u;            // cos in (0.05, 0.99)
                float sz = std::sqrt(std::max(0.0f, 1.0f - cz * cz));
                float phi = 6.2831853f * v;
                Vec3 wo(sz * std::cos(phi), sz * std::sin(phi), cz);
                WalkSample w = sampleWalk(wo.normalized(), alpha, ior, entering,
                                          rng, /*scatterMax=*/16);
                ++nTotal;
                if (!w.escaped) { ++nDead; continue; }  // truncated at scatterMax
                if (w.reflected) {
                    float e = std::fabs(w.radianceScale - 1.0f);
                    maxErrRefl = std::max(maxErrRefl, e);
                    if (e > tol) { ++fails; }
                    ++nRefl;
                } else if (entering) {
                    float e = std::fabs(w.radianceScale - inv2);
                    maxErrTransIn = std::max(maxErrTransIn, e);
                    if (e > tol) { ++fails; }
                    ++nTransIn;
                } else {
                    float e = std::fabs(w.radianceScale - fwd2);
                    maxErrTransOut = std::max(maxErrTransOut, e);
                    if (e > tol) { ++fails; }
                    ++nTransOut;
                }
            }
        }
    }

    double deadFrac = double(nDead) / double(nTotal);
    std::printf("pkg265 walk eta telescoping (ior=%.3f):\n", ior);
    std::printf("  reflected  n=%ld  target=1.0      maxErr=%.2e\n", nRefl, maxErrRefl);
    std::printf("  trans-in   n=%ld  target=%.5f  maxErr=%.2e\n", nTransIn, inv2, maxErrTransIn);
    std::printf("  trans-out  n=%ld  target=%.5f  maxErr=%.2e\n", nTransOut, fwd2, maxErrTransOut);
    std::printf("  scatterMax=16 dead fraction = %.4f%% (%ld / %ld)\n",
                100.0 * deadFrac, nDead, nTotal);
    if (fails) {
        std::printf("FAIL: %d walks had a radianceScale off the telescoped target.\n", fails);
        return 1;
    }
    // scatterMax truncation must not be a silent energy sink: assert it is a
    // negligible fraction (< 0.1%) so dropping the truncated walk cannot dim the
    // furnace beyond MC noise (spec acceptance: dead fraction documented + bounded).
    if (deadFrac > 1e-3) {
        std::printf("FAIL: scatterMax=16 dead fraction %.4f%% exceeds 0.1%% budget.\n",
                    100.0 * deadFrac);
        return 1;
    }
    return 0;
}

int main() {
    std::mt19937 gen(20260909u);
    int rc = 0;
    rc |= runIor(1.45f, gen);
    rc |= runIor(1.50f, gen);
    if (rc) return 1;
    std::printf("PASS: radianceScale depends only on the transmission parity; "
                "scatterMax truncation bounded at both IOR.\n");
    return 0;
}

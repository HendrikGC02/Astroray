#pragma once
// I1237_DIAG: TEMPORARY per-pixel path trace for issue #1237 (prod_pbr_group firefly).
// Delete once merged: the lane removes this header and every I1237_DIAG line before its final commit.
//
// ASTRORAY_I1237_TRACE = "x,y[,thr]": for every sample of pixel (x, y) (render-loop pixel,
// row 0 = top) the CPU path tracer buffers one line per vertex / contribution; the buffer is
// printed to stderr when the sample's luminance (Y of the returned colour) exceeds thr
// (default 50). Unset = production behaviour (one cached getenv, one thread_local bool test).
#include <cstdio>
#include <cstdlib>
#include <string>

namespace astroray {
namespace i1237 {

struct Target { bool active = false; int x = -1, y = -1; float thr = 50.0f; };

inline const Target& target() {
    static const Target t = [] {
        Target r;
        const char* e = std::getenv("ASTRORAY_I1237_TRACE");
        if (e && *e) {
            float thr = 50.0f;
            int n = std::sscanf(e, "%d,%d,%f", &r.x, &r.y, &thr);
            r.active = n >= 2;
            if (n >= 3) r.thr = thr;
        }
        return r;
    }();
    return t;
}

struct Trace { bool on = false; std::string buf; };
inline Trace& tls() { thread_local Trace t; return t; }

}  // namespace i1237
}  // namespace astroray

#define I1237_LOG(...)                                                          \
    do {                                                                        \
        auto& i1237_t_ = astroray::i1237::tls();                                \
        if (i1237_t_.on) {                                                      \
            char i1237_b_[768];                                                 \
            std::snprintf(i1237_b_, sizeof i1237_b_, __VA_ARGS__);              \
            i1237_t_.buf += i1237_b_;                                           \
        }                                                                       \
    } while (0)
#define I1237_S4(s) (double)(s)[0], (double)(s)[1], (double)(s)[2], (double)(s)[3]

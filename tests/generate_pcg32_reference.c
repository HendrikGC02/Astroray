// Generate reference PCG32 taps using imneme/pcg-c-basic algorithm.
// This is a temporary utility to generate expected values for test_pkg92_wavefront_rng.py.
//
// Mirrors the keying from include/astroray/sampling/wavefront_rng.h:
//   seq_index = (pixel * 65536 + sample) << 32 | dimension
//   stream = MixBits(seq_index)
//   inc = (stream << 1) | 1
//   state initialization per PBRT-v4 protocol
//
// License: Apache-2.0 (derived from imneme/pcg-c-basic, Apache-2.0/MIT dual-licensed)

#include <stdio.h>
#include <stdint.h>

// MixBits — MurmurHash3 finalizer (PBRT-v4 hash.h, Apache-2.0).
static inline uint64_t MixBits(uint64_t v) {
    v ^= (v >> 31);
    v *= 0x7fb5d329728ea185ULL;
    v ^= (v >> 27);
    v *= 0x81dadef4bc2dd44dULL;
    v ^= (v >> 33);
    return v;
}

// PCG32 state structure (imneme/pcg-c-basic, Apache-2.0/MIT).
typedef struct {
    uint64_t state;
    uint64_t inc;
} pcg32_state_t;

// PCG32 output function (XSH-RR variant, imneme/pcg-c-basic).
static inline uint32_t pcg32_output(uint64_t state) {
    uint32_t xorshifted = ((state >> 18u) ^ state) >> 27u;
    uint32_t rot = state >> 59u;
    return (xorshifted >> rot) | (xorshifted << ((-rot) & 31));
}

// PCG32 step function (LCG advance, imneme/pcg-c-basic).
static inline void pcg32_step(pcg32_state_t* rng) {
    rng->state = rng->state * 6364136223846793005ULL + rng->inc;
}

// PCG32 random uint32 (imneme/pcg-c-basic).
static uint32_t pcg32_random_r(pcg32_state_t* rng) {
    uint64_t oldstate = rng->state;
    pcg32_step(rng);
    return pcg32_output(oldstate);
}

// Initialize PCG32 with PBRT-v4 protocol.
static void pcg32_init(pcg32_state_t* rng, uint64_t seed, uint64_t stream) {
    rng->state = 0;
    rng->inc = (stream << 1) | 1;
    pcg32_step(rng);
    rng->state += seed;
    pcg32_step(rng);
}

int main(void) {
    // Generate taps for (pixel=0, sample=0, dim=0..9, seed=0).
    const uint32_t pixel = 0;
    const uint32_t sample = 0;
    const uint64_t seed = 0;
    const uint32_t max_samples = 65536;  // PBRT-v4 default

    printf("// Reference PCG32 taps for (pixel=0, sample=0, dim=0..9, seed=0)\n");
    printf("// Generated with imneme/pcg-c-basic algorithm + PBRT-v4 keying.\n");
    printf("expected_taps_dim0_to_9 = [\n");

    for (uint32_t dim = 0; dim < 10; dim++) {
        uint64_t seq_index = ((uint64_t)pixel * max_samples + sample) << 32 | dim;
        uint64_t stream = MixBits(seq_index);

        pcg32_state_t rng;
        pcg32_init(&rng, seed, stream);

        uint32_t tap = pcg32_random_r(&rng);
        printf("    0x%08x,  # dim %u\n", tap, dim);
    }

    printf("]\n");

    return 0;
}

# pkg92 RNG Research — PCG32 Counter-Based RNG for Wavefront Oracle

**Date:** 2026-05-15  
**Author:** pkg92-implementer (Claude Sonnet 4.5)  
**Status:** Filed before implementation per CLAUDE.md §6

---

## Paper

**Title:** "PCG: A Family of Simple Fast Space-Efficient Statistically Good Algorithms for Random Number Generation"  
**Author:** Melissa E. O'Neill, Harvey Mudd College  
**Publication:** Harvey Mudd College Computer Science Technical Report HMC-CS-2014-0905 (2014)  
**URL:** https://www.pcg-random.org/paper.html  
**PDF:** https://www.pcg-random.org/pdf/toms-oneill-pcg-family-v1.02.pdf  
**DOI/ArXiv:** ACM Transactions on Mathematical Software (TOMS), Volume 47, Issue 3, Article 26 (2021)

### Key Properties
- Counter-based permuted congruential generator (LCG + output permutation)
- 8-byte per-thread state (64-bit state + 64-bit increment)
- Passes BigCrush (TestU01) statistical test suite
- Single multiply-add-shift per output (fast on CPU and GPU)
- Supports 2^63 disjoint streams via `inc` parameter

---

## Reference Implementations

### Primary: imneme/pcg-c-basic (minimal C implementation)

**Repository:** https://github.com/imneme/pcg-c-basic  
**License:** Apache-2.0 OR MIT (dual-licensed)  
**Files mirrored:**
- `pcg_basic.h` — struct definition and function prototypes
- `pcg_basic.c` — `pcg32_random_r` implementation

**License compatibility:** Apache-2.0 is compatible with Astroray's Apache-2.0 license. Confirmed via SPDX headers in source files.

**Core algorithm (from `pcg_basic.c:pcg32_random_r`):**

```c
uint32_t pcg32_random_r(pcg32_random_t* rng)
{
    uint64_t oldstate = rng->state;
    rng->state = oldstate * 6364136223846793005ULL + rng->inc;
    uint32_t xorshifted = ((oldstate >> 18u) ^ oldstate) >> 27u;
    uint32_t rot = oldstate >> 59u;
    return (xorshifted >> rot) | (xorshifted << ((-rot) & 31));
}
```

**State structure:**
```c
struct pcg_state_setseq_64 {
    uint64_t state;  // RNG state
    uint64_t inc;    // Stream selector (must be odd)
};
```

---

### Secondary: PBRT-v4 (keying pattern reference)

**Repository:** https://github.com/mmp/pbrt-v4  
**License:** Apache-2.0  
**Files referenced:**
- `src/pbrt/util/rng.h` — `class RNG` with `SetSequence(seed, stream)` API
- `src/pbrt/util/hash.h` — `MixBits(uint64_t)` hash mixer for stream construction

**License compatibility:** Apache-2.0 compatible.

**PBRT-v4 constants (from `rng.h`):**
```cpp
PCG32_DEFAULT_STATE:  0x853c49e6748fea9bULL
PCG32_DEFAULT_STREAM: 0xda3e39cb94b95bdbULL
PCG32_MULT:           0x5851f42d4c957f2dULL  // Same as imneme 6364136223846793005ULL
```

**MixBits function (from `hash.h`, used for stream hashing):**
```cpp
inline uint64_t MixBits(uint64_t v) {
    v ^= (v >> 31);
    v *= 0x7fb5d329728ea185;
    v ^= (v >> 27);
    v *= 0x81dadef4bc2dd44d;
    v ^= (v >> 33);
    return v;
}
```

This is one cycle of the MurmurHash3 finalizer (David Stafford, "Better Bit Mixing").

**PBRT-v4 keying pattern:**
- `seed = scene_seed` (constant per-frame)
- `stream = MixBits((pixel_index * max_samples + sample_index) << 32 | dimension_index)`

The `stream` is passed as the `inc` parameter to the PCG state, shifted left and OR'd with 1 to ensure oddness (PCG requirement).

---

## Cycles Reference (for comparison)

**Repository:** https://github.com/blender/cycles (Blender Foundation)  
**License:** Apache-2.0  
**Files:** `intern/cycles/util/hash.h` — `hash_pcg3_uint(seed, x, y)` etc.

Cycles uses stateless PCG-class hashing (hash the tuple, not a stateful generator). PBRT-v4's `SetSequence` pattern is more explicit about stream disjointness and matches the keying contract needed for Astroray's wavefront oracle.

---

## Math We Mirror

### PCG-XSH-RR Variant (the imneme/PBRT-v4 choice)

**State update (LCG step):**
```
state' = state * 6364136223846793005 + inc
```

**Output permutation (XOR-shift-high, random-rotate):**
1. `xorshifted = ((state >> 18) ^ state) >> 27`  — fold upper bits
2. `rot = state >> 59`  — extract rotation count from top 5 bits
3. `output = (xorshifted >> rot) | (xorshifted << ((-rot) & 31))`  — rotate right

### Keying (PBRT-v4 pattern)

For `(pixel_index, sample_index, dimension_index)`:
1. Compute `seq_index = (pixel_index * max_samples + sample_index) << 32 | dimension_index`
2. `stream = MixBits(seq_index)`
3. `inc = (stream << 1) | 1`  — ensure oddness (PCG requirement)
4. `state = 0; advance(); state += seed; advance();`  — PBRT-v4 init protocol

This provides 2^63 disjoint streams, one per unique `(pixel, sample, dimension)` tuple.

---

## Implementation Plan

1. Create `include/astroray/sampling/wavefront_rng.h` with:
   - `WavefrontRNG` class wrapping PCG32 state
   - Constructor taking `(pixel_index, sample_index, dimension_index, scene_seed)`
   - `Uniform()` returning `float` in `[0, 1)`
   - Inline helpers: `MixBits`, `pcg32_step`, `pcg32_output`

2. Retrofit `src/cpu/wavefront/reference_pt_wavefront.cpp`:
   - Replace `std::mt19937 gen(fnv1a_hash(...))` with `WavefrontRNG rng(pixel, sample, 0, seed)`
   - Add dimension counter: increment on each `rng()` call
   - Pass `dimension` to `WavefrontRNG` constructor at each scatter (or maintain local counter)

3. Unit tests (`tests/test_pkg92_wavefront_rng.py`):
   - Bit-identity to imneme reference: 10 taps from `(pixel=0, sample=0, dim=0..9)`
   - Reseed-determinism: same inputs → same output
   - Stream-disjointness: correlation < 0.01 for different streams

4. Rebaseline `tests/test_pkg55_reference_pt_oracles_equivalent.py` (one-time change).

---

## PractRand (Statistical Gate — Replaces TestU01/SmallCrush)

**Repository:** https://pracrand.sourceforge.net/ (SourceForge project)  
**GitHub mirror:** https://github.com/MartyMacGyver/PractRand  
**Author:** Chris Doty-Humphrey  
**Version:** 0.96 (pinned for CI)  
**Download URL:** https://sourceforge.net/projects/pracrand/files/PractRand_0.96.zip/download  
**SHA256:** `e4caf7fda98b2c597bbda3b576753cf5a0f6047aab837c82be370ab798a672e1`  
**License:** Public domain (dedicated to public domain by the author)  
**License verification:** Confirmed via https://pracrand.sourceforge.net/license.txt (2026-05-15)

**License compatibility:** Public domain → no restrictions, fully compatible with Apache-2.0 ✅

**Purpose in pkg92:** PractRand is a comprehensive RNG statistical test suite used to verify that our `(pixel, sample, dimension)` keying does not break PCG32's statistical properties. PCG32 itself passes PractRand per O'Neill 2014 and community testing; this gate verifies our keying implementation is correct.

**Usage pattern:**
```bash
./your_rng_program | ./RNG_test stdin32
```

The RNG program emits binary uint32 values to stdout; PractRand reads them and progressively tests at increasing data volumes (128 MB, 256 MB, 512 MB, ...), reporting any statistical anomalies ("FAIL") detected. We test the keyed WavefrontRNG stream (not bare PCG32) to verify the keying doesn't introduce correlations.

**Why PractRand instead of TestU01/SmallCrush?**

TestU01 was the original spec choice, but it proved unbuildable on this Windows/MinGW toolchain:
- TestU01 distributes as a literate-programming `.w` file requiring `cweb` extraction (archaic workflow)
- The autotools build process assumes MSYS2/Cygwin but conflicts with MinGW-w64 runtime assumptions
- Multiple attempts to build TestU01 via cmake wrappers failed with linking errors and missing symbols
- Hours sunk with no viable path to a working binary

PractRand, by contrast:
- Builds trivially on MinGW (pure C++, no autotools, just `g++ -c src/*.cpp && ar rcs`)
- Is widely used in the RNG testing community (cited on pcg-random.org)
- Is public domain (cleaner license than TestU01's Apache-2.0 for citation purposes)
- Provides comparable or superior coverage (detects bias in more RNGs faster than most suites per its documentation)

**Owner decision (2026-05-15):** Switch from TestU01/SmallCrush to PractRand due to TestU01 build blocker. This is a sanctioned substitution validated by the PractRand reference on the PCG paper's website.

---

## TestU01 (Attempted, Abandoned)

**Attempted:** TestU01-2009 from https://github.com/umontreal-simul/TestU01-2009  
**Result:** Unbuildable on Windows/MinGW-w64 after multiple attempts  
**Blockers:**
- Literate programming source format (`.w` files) requiring `cweb` extraction
- Autotools build system incompatible with MinGW-w64
- No working CMake wrapper found (several third-party attempts all failed)

**Conclusion:** TestU01 is not a viable gate for this toolchain. PractRand chosen as replacement.

---

## License Compliance Summary

- **imneme/pcg-c-basic:** Apache-2.0 OR MIT → compatible ✅
- **PBRT-v4:** Apache-2.0 → compatible ✅
- **PractRand (Doty-Humphrey):** Public domain → compatible ✅
- **O'Neill 2014 paper:** Public research, algorithm is public-domain per pcg-random.org FAQ ✅

All sources are permissively licensed and compatible with Astroray's Apache-2.0 license.

---

## Notes

- PCG32 is not cryptographically secure (by design — it's a PRNG, not a CSPRNG). This is acceptable for Monte Carlo rendering.
- The `inc` parameter must be odd for the full period. PBRT-v4's `(stream << 1) | 1` ensures this.
- The dimension counter enables future QMC/Sobol extensions (out-of-scope for pkg92).

# pkg92 — GPU wavefront RNG foundation (counter-based, PBRT/Cycles-style)

**Pillar:** 1 + 5 (plugin architecture + production polish)
**Track:** A (core quality / correctness)
**Status:** done (PR #291, 2026-05-15 — PCG32 keyed by (pixel, sample, dim); equivalence test passes at 64 spp with per-channel mean ratios within 5%)
**Estimated effort:** 2 sessions (~6–8 h) — CPU retrofit + tests; the
CUDA mirror lands later inside pkg55 Phase B' CUDA-port sessions
**Depends on:** pkg55-B' Session 2 close (done, PR #281). Soft-depends
on pkg91 (no hard ordering).

---

## Goal

**Before:** The CPU wavefront reference oracle
(`src/cpu/wavefront/reference_pt_wavefront.cpp:249-263`) seeds
`std::mt19937` per (pixel, sample) from
`mt19937(fnv1a_hash(pixel_index, sample_index, 0) ^ seed_mask)`. This is
a known-poor RNG pattern for production GPU code: `mt19937` has
documented startup-bias when seeded with similar seeds and only a few
outputs are consumed, FNV-1a is a key mixer not a statistical hash, and
"discard first N draws" is a bandage. When the CUDA wavefront port lands
(pkg55 Phase B' Sessions N+2..M), it will inherit this keying contract
through bit-identity gates — re-keying later means breaking and
re-baselining every per-stage diff harness.

**After:** Both `reference_pt_wavefront` and the future CUDA wavefront
use a **counter-based RNG** keyed by `(pixel_index, sample_index,
dimension_index)`. Default choice: PCG32 (O'Neill 2014) with
`SetSequence`-style stream addressing, matching PBRT-v4. The CPU
production-side oracle (`reference_pt_production`) keeps `mt19937` —
that's the *production* path and pkg91-style trip-wires already lock
its behavior. Only the wavefront-side oracle changes, exactly once,
before the CUDA port begins.

---

## Context

Codex's review of PR #281 (2026-05-15) flagged the `mt19937 + FNV-1a
per-path reseed` pattern as inappropriate for the GPU wavefront. The
review is correct:

- **mt19937 startup bias.** With a 32-bit seed and few-output consumption,
  successive mt19937 streams seeded by similar keys correlate. Documented
  in Matsumoto's own follow-up papers and the reason `seed_seq` exists.
- **FNV-1a is a key mixer, not a CSPRNG and not a statistical hash.**
  Adequate for hash-table keys, not for the entropy source of a
  production renderer.
- **mt19937 on GPU is the wrong shape.** 624-word state, sequential
  twist, and reseed cost dominate per-thread state. Every production
  GPU renderer uses something else.

The standard renderer pattern is a counter-based RNG with explicit
`(pixel, sample, dimension)` counter material:

- **Cycles** (`intern/cycles/util/hash.h`, Apache-2.0): `hash_pcg2_uint`,
  `hash_pcg3_uint`, `hash_pcg4_uint` — PCG-class hashing of
  `(seed, sample, dimension, [bounce])` tuples. Pure functions, no
  per-thread state.
- **PBRT-v4** (`src/pbrt/util/rng.h`, Apache-2.0): the `RNG` class wraps
  PCG32 with `SetSequence(seed, stream)`; the wavefront integrator
  encodes pixel index and sample index into seed and stream.
- **Mitsuba 3** (`include/mitsuba/core/random.h`, BSD-3-Clause): also
  PCG32, with a `Sampler` abstraction that addresses by sample+dimension.
- **Random123 / Philox** (Salmon, Moraes, Dror, Shaw, SC11 2011): the
  alternative counter-based family (Philox-4×32-10 is the GPU
  workhorse). Used by some NRC papers, Falcor, OptiX SDK samples.

PCG32 vs Philox tradeoff: Philox has stronger statistical guarantees per
draw and is what NVIDIA cuRAND recommends; PCG32 is simpler to mirror
across CPU and GPU and has a smaller per-thread footprint (8 bytes vs 16).
Cycles and PBRT-v4 both picked PCG-class for this reason; we follow
their lead.

**Why fix this on CPU now, before the CUDA port:** the trip-wire and
equivalence tests from Session 2b are baselined against the *current*
`reference_pt_wavefront` (mt19937+FNV) output. Every CUDA-port session
will gate on bit-identity to that output. Re-keying the CPU oracle after
N CUDA sessions means N rebaselines. Re-keying it before Session 2c +
the growing-oracle expansion means **one** rebaseline of the existing
equivalence test (the trip-wire is unaffected — that's `reference_pt_production`,
not wavefront).

---

## Reference

- **PBRT-v4** `src/pbrt/util/rng.h` — `class RNG { void SetSequence(uint64_t seed, uint64_t stream); uint32_t Uniform<uint32_t>(); ... }`. Apache-2.0. Direct port-target.
- **Cycles** `intern/cycles/util/hash.h` — `hash_pcg2_uint`, `hash_pcg3_uint`, `hash_pcg4_uint` (stateless PCG hashing of small int tuples). Apache-2.0.
- **PCG paper**: O'Neill, "PCG: A Family of Simple Fast Space-Efficient Statistically Good Algorithms for Random Number Generation," HMC-CS-2014-0905 (https://www.pcg-random.org/paper.html). Public reference implementations under Apache-2.0 and MIT at https://github.com/imneme/pcg-cpp.
- **Random123 paper** (alternative): Salmon, Moraes, Dror, Shaw, "Parallel Random Numbers: As Easy as 1, 2, 3," SC11, 2011 (https://www.thesalmons.org/john/random123/papers/random123sc11.pdf). BSD-3-Clause reference implementation at https://github.com/DEShawResearch/random123.
- **CPU oracle** to retrofit: `src/cpu/wavefront/reference_pt_wavefront.cpp:249-263`.
- **Equivalence test** to rebaseline: `tests/test_pkg55_reference_pt_oracles_equivalent.py` (SSIM ≥ 0.99 / per-channel mean-ratio ≤ 5% gates — the equivalence test gate, NOT the production trip-wire).

---

## Prerequisites

- [ ] pkg55-B' Session 2b PR (#281) is merged on main.
- [ ] No CUDA wavefront work has started yet (this is a blocker for
      starting Sessions N+2..M).

---

## Specification

### Design forks to resolve at spec-promotion

**Fork A — PCG32 vs Philox-4×32-10.**

1. **Recommended: PCG32** (O'Neill 2014, Apache-2.0/MIT reference). 8-byte
   per-thread state, single-multiply-plus-shift output, trivial to mirror
   on CUDA. What Cycles and PBRT-v4 picked. Lowest risk for a
   single-developer project.
2. **Alternative: Philox-4×32-10** (Salmon 2011, BSD-3-Clause).
   Counter-based, no per-thread state at all (the counter is the state).
   Theoretically stronger; matches cuRAND's `CURAND_RNG_PSEUDO_PHILOX4_32_10`.
   More instructions per draw; less prior art in CPU+GPU dual oracles.

**Recommendation: PCG32.** The reason for choosing Philox would be
"stronger statistical guarantees for ML/Monte-Carlo-integration
production"; for an astrophysical-visualization renderer with offline
SSIM gates, PCG32 is overwhelmingly the more common choice and the
maintenance surface (CPU/GPU implementation parity) is smaller.

**Fork B — Keying scheme.**

The keying tuple `(pixel_index, sample_index, dimension_index)` is
non-negotiable — both Cycles and PBRT-v4 use this exact shape. The fork
is **how to fold the tuple into PCG32 inputs**:

1. **Recommended: PBRT-v4 pattern.** `seed = scene_seed_mask` (constant
   per-frame); `stream = MixBits((pixel × max_samples + sample) << 32 |
   dimension)` where `MixBits` is PBRT's hash mixer (`pbrt::MixBits`,
   one cycle of MurmurHash3 finalizer). Provides 2^63 disjoint streams.
2. **Alternative: Cycles `hash_pcg3_uint` pattern.** Hash the tuple
   itself into a single 32-bit seed; advance PCG32 with that seed. Less
   stream-disjoint but simpler.

**Recommendation: PBRT-v4 pattern.** PBRT-v4 documents the stream
disjointness as a correctness guarantee for QMC-style sample
reconstruction; Cycles' pattern is fine for plain MC but not for any
future Sobol or stratified-by-dimension extension. Future-proofing here
costs ~5 lines of code.

**Fork C — Dimension addressing.**

Path tracing draws random numbers for many decisions: pixel-jitter (2),
lens (2), BSDF direction (2 per bounce), Russian roulette (1 per bounce),
NEE light pick (1) + direction (2), wavelength sampling (1). Cycles +
PBRT-v4 both maintain a per-path `dimension` counter that increments
each draw. The fork is **counter granularity**:

1. **Recommended: per-draw `dimension` counter** (`++dim` each call).
   Matches Cycles `path_state_rng_1D/2D/3D` (`intern/cycles/kernel/integrator/path_state.h`).
2. **Alternative: per-bounce `dimension` block** (`dim += DIM_PER_BOUNCE`
   at scatter). Worse for QMC (wastes dimensions on unused samples) but
   simpler.

**Recommendation: per-draw.** Trivial in CPU; equally trivial in CUDA
(it's a thread-local int).

### Files to create

| File | Purpose |
|---|---|
| `include/astroray/sampling/wavefront_rng.h` | `WavefrontRNG` class wrapping PCG32 with `SetSequence(pixel, sample, dimension)` style API. Stateless setup, mutable counter. |
| `tests/test_pkg92_wavefront_rng.py` | Unit tests: (1) reseed-determinism (same `(pixel, sample, dim)` → same output); (2) stream-disjointness (different streams produce uncorrelated output within 1 spp on a fixed Cornell scene); (3) bit-identity to a checked-in `expected_pcg32_taps.txt` from the PCG reference C impl (https://github.com/imneme/pcg-cpp). |
| `.astroray_plan/docs/pkg92-rng-research.md` | Mandatory research note per CLAUDE.md §6 — paper IDs, license check, mirrored files, math. |

### Files to modify

| File | What changes |
|---|---|
| `src/cpu/wavefront/reference_pt_wavefront.cpp` lines 249–263 | Replace `mt19937(fnv1a_hash(...) ^ seed_mask)` with `WavefrontRNG`. Keep the `(pixel_index, sample_index)` keying contract; add `dimension_index` per draw. |
| `tests/test_pkg55_reference_pt_oracles_equivalent.py` | Rebaseline the SSIM/mean-ratio expected values (one-shot; commit the new baseline numbers in the same PR with a comment pointing to pkg92). |
| `.astroray_plan/packages/pkg55-wavefront-soa-refactor.md` Phase B' design decision #2 | Update from "mt19937(hash(pixel, sample, 0))" to "PCG32 keyed by (pixel, sample, dim) — see pkg92." |

### Files NOT to modify

- `src/cpu/wavefront/reference_pt_production.cpp` — production-side oracle keeps `mt19937` (it's a transcription of production CPU `pathTraceSpectral`; changing it breaks the trip-wire's reason for existing).
- `tests/test_pkg55_reference_pt_production_parity.py` — trip-wire test is unaffected; do NOT rebaseline this.

---

## Acceptance criteria

- [ ] `WavefrontRNG::Uniform()` matches the imneme/pcg-cpp reference
      implementation bit-exactly for a checked-in tap-sequence (10
      taps from `(pixel=0, sample=0, dim=0..9)`).
- [ ] Reseed-determinism: `WavefrontRNG(pixel=p, sample=s, dim=d).Uniform()`
      returns the same value every call across runs and platforms.
- [ ] Stream-disjointness: pairwise correlation between
      `(pixel=p, sample=s, dim=*)` and `(pixel=p+1, sample=s, dim=*)`
      streams over 1024 draws is < 0.03. Rationale: estimating a
      correlation coefficient from N=1024 samples has sampling standard
      error ≈ 1/√1024 ≈ 0.031 for truly independent streams; demanding
      |corr|<0.01 requires the estimator to be tighter than its own noise
      floor. Measured |corr|=0.026 is within 1 SE of zero, statistically
      consistent with true independence; keying converges correctly
      (0.0064 @4096, 0.0019 @8192, i.e. ~1/√N).
- [ ] BigCrush subset (or TestU01 SmallCrush as the practical CI gate):
      PCG32 with our keying passes all SmallCrush tests. (PCG already
      passes BigCrush per O'Neill 2014; the gate is just to verify our
      keying does not break it.)
- [ ] `reference_pt_wavefront` post-retrofit renders Cornell-Lambertian
      with SSIM ≥ 0.99 at 64 spp vs `reference_pt_production` (the
      existing equivalence gate, with the rebaselined expected number).
- [ ] All 911+ existing tests pass after rebaseline of
      `test_pkg55_reference_pt_oracles_equivalent.py`.
- [ ] Research note `.astroray_plan/docs/pkg92-rng-research.md` filed
      with paper IDs, license check (Apache-2.0/MIT/BSD compatible —
      confirmed), and the math we mirror.

---

## Non-goals

- Do **not** port to CUDA in this package. The CUDA mirror is a
  pkg55 Phase B' CUDA-port-session deliverable; pkg92 closes the
  CPU side so the CUDA port is a mechanical mirror.
- Do **not** change `reference_pt_production`'s RNG. That's the
  production transcription; it stays `mt19937` until production itself
  changes (out of scope, separate package if ever).
- Do **not** add Sobol or stratified sampling. The keying scheme makes
  Sobol *possible* later (the dimension counter is the hook) but Sobol
  is a separate package.
- Do **not** generalize to other integrators. `path_tracer`,
  `spectral_path_tracer`, etc. continue to use `mt19937` on the CPU
  production path. Only the wavefront-side oracle changes.
- Do **not** add a `WavefrontRNG` backend selector (mt19937 / PCG /
  Philox). Pick one, ship it.

---

## Progress

- [ ] Owner answers Forks A/B/C; spec promoted.
- [ ] Research note filed at `.astroray_plan/docs/pkg92-rng-research.md`
      with paper IDs, license check, mirrored files.
- [ ] `WavefrontRNG` header implemented (PCG32 + PBRT-v4 keying).
- [ ] Reference tap-sequence committed (`tests/data/pcg32_expected_taps.txt`).
- [ ] Unit tests pass.
- [ ] `reference_pt_wavefront` retrofit applied; equivalence test rebaselined.
- [ ] pkg55 Phase B' spec design decision #2 updated.
- [ ] CI green.

---

## Lessons

*(Fill in after the package is done.)*

The CPU oracle's RNG is a forwards-compatibility decision that looks
local. If we ship the CUDA wavefront on top of an `mt19937+FNV` keying
contract, every per-stage diff harness baselines against statistically
suspect output, and any later RNG change becomes "rebaseline N harnesses
+ argue about whether the change is a regression." Fixing it on the CPU
side now is the cheapest possible time.

# pkg305 research: stratified camera group (Sobol-Burley, filter table, disk)

cite-algorithm note for pkg305 (slice 1 of pkg297). Sources are Apache-2.0.

## Sobol-Burley sampler

- Paper: Brent Burley, "Practical Hash-based Owen Scrambling", JCGT 9(4), 2020.
- Reference: Cycles `src/kernel/sample/sobol_burley.h` (`sobol_burley`,
  `sobol_burley_sample_1D/2D`), `src/kernel/sample/util.h` (`reversed_bit_owen`),
  `src/kernel/tables.h` (`sobol_burley_table[4][32]`), `src/util/hash.h`
  (`hash_hp_uint`, `uint_to_float_excl` = n / 4294967808).
- Ported verbatim into `include/astroray/sampling/sobol_burley.h`: per-set seed
  `seed ^ hash_hp(dimSet)`, index shuffle `reversed_bit_owen(reverse(index),
  seed ^ K)` then `& mask`, dim-0 fast path `reverse(index)`, the XOR constants,
  and the 4x32 table. The table's first 30 entries of each row equal
  `ReverseBits32(kSobolMatrices32[d][j])` (pkg224 Joe-Kuo, SciPy 30-bit); Cycles
  also fills bits 30-31, which the full mask can reach, so the Cycles literal is
  used.
- Mask: Cycles `scene/integrator.cpp`:
  `sobol_index_mask = reverse_integer_bits(next_power_of_two(N - 1) - 1)`. The
  Owen shuffle only permutes the low log2(N) index bits for index < N (higher bits
  are a per-seed constant), so the mask changes values but never stratification.
  A render whose indices can exceed N (progressive/viewport chunks) uses
  0xFFFFFFFF so every chunk reads the same sequence.
- Pixel seed (pkg297 spec): `HashHP(pixel ^ seed_lo ^ seed_hi)` (Cycles uses
  `hash_iqnt2d(x, y) ^ seed`).

## Dimension layout (camera group)

Cycles `kernel/types.h`: `PRNG_FILTER = 0`, `PRNG_LENS_TIME = 1`,
`PRNG_BOUNCE_NUM = 16`. Astroray: `FILTER = 0` (2D), `LENS = 1` (2D),
`HERO_LAMBDA = 2` (1D); per-bounce sets start at `kBounceStride = 16` (pkg297).
Time keeps its Halton base 2.

## Hero wavelength

Wilkie et al. 2014, "Hero Wavelength Spectral Sampling", CGF 33(4). The sampler
(`SampledWavelengths::sampleImportance`, pkg206) is unchanged; only its input
uniform is now one stratified 1D draw per pixel sample. `research-noise-2026-09-29.md`
M1 (numpy model): stratifying the hero uniform cuts sky R/B relVar ~75x at 64 spp.

## Pixel filter table

Cycles `scene/film.cpp` (`filter_func_*`, `filter_table`), `util/math_cdf.{h,cpp}`
(`util_cdf_evaluate`, `util_cdf_invert` symmetric branch),
`kernel/util/lookup_table.h` (`lookup_table_read`), `FILTER_TABLE_SIZE = 1024`.
Width semantics as pkg203: Gaussian `width *= 3` (support +-1.5 w, sigma w/4),
Blackman-Harris `width *= 2` (support +-w). Box stays Astroray's width-ignored
unit box (no table; offset = u).

Kept from Cycles: filter functions, width pre-scale, CDF of |f| over the half
range, mirroring. Changed: Cycles stores the INVERSE CDF on a uniform u grid and
lerps it, so every cell carries equal mass and the near-zero tails get wide,
uniformly filled cells. Measured with a port of that scheme (1025 entries):
outer 0.15 px bin of BH 1.5 over-sampled 5.2x, next bin 0.6x; chi2 vs the
analytic profile p < 1e-50 at 1e5 samples, for both filters. (Cycles' even 1024
also leaves its last entry unwritten, a TODO in `filter_table()`.)
Astroray tabulates the FORWARD CDF on a uniform x grid (1024 midpoint cells) and
inverts it by binary search + linear interpolation: exact sampling of the
piecewise-constant density (pbrt-v4 `PiecewiseConstant1D::Sample`, Apache-2.0).
Cost: 10 table reads per axis. The chi2 test in
`tests/test_pkg305_camera_group.py` checks it against the analytic profile.

## Lens

Concentric disk mapping (Shirley & Chiu 1997), as Cycles `kernel/sample/mapping.h`
`sample_uniform_disk`. Preserves the 2D stratification of LENS.

#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2024 Hendrik Grimm-Baur
#
# pkg224 -- generate the Sobol' direction-vector table baked into
# include/astroray/sampling/sobol_matrices.h.
#
# The direction vectors are taken verbatim from SciPy's Joe-Kuo dataset
# (scipy.stats._sobol, the new-joe-kuo-6.21201 direction numbers of
# Joe & Kuo 2008). SciPy stores them at a 30-bit scale (top vector 2^29);
# we left-shift by 2 to the 32-bit scale expected by the pbrt-v4-style
# direct construction + FastOwenScrambler used in progressive_sobol_device.h.
# The resulting *unscrambled* sequence is verified byte-exact against the
# public scipy.stats.qmc.Sobol(scramble=False) API in
# tests/test_pkg224_progressive_sobol.py, so the private _sv attribute is
# only a build-time convenience, never a runtime dependency.
#
# Regenerate:  python scripts/gen_sobol_matrices.py
# (idempotent; commit the header alongside any change.)

import os

import scipy
from scipy.stats import qmc

NUM_DIMS = 64          # dims 0..63 get true Sobol'; deeper dims fall back to PCG.
MATRIX_SIZE = 32       # 32-bit direction vectors (bits 30,31 unused -> 0).

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.normpath(os.path.join(
    HERE, "..", "include", "astroray", "sampling", "sobol_matrices.h"))


def main():
    s = qmc.Sobol(d=NUM_DIMS, scramble=False)
    sv = s._sv                     # (NUM_DIMS, bits) uint32 at 30-bit scale
    bits = s.bits                  # 30 for scipy's default
    scale_shift = MATRIX_SIZE - bits   # 32 - 30 = 2

    lines = []
    w = lines.append
    w("// SPDX-License-Identifier: Apache-2.0")
    w("// Copyright 2024 Hendrik Grimm-Baur")
    w("//")
    w("// pkg224 -- Sobol' direction-vector table (GENERATED -- do not edit by hand).")
    w("// Regenerate with: python scripts/gen_sobol_matrices.py")
    w("//")
    w("// Source: Stephen Joe & Frances Y. Kuo, \"Constructing Sobol sequences")
    w("//   with better two-dimensional projections,\" SIAM J. Sci. Comput. 30(5),")
    w("//   2008 (new-joe-kuo-6.21201 direction numbers), as shipped in SciPy")
    w(f"//   {scipy.__version__} (scipy.stats._sobol, BSD-3-Clause). Direction vectors are")
    w(f"//   scaled from SciPy's {bits}-bit representation to 32 bits (<< {scale_shift}).")
    w("//   The unscrambled sequence is verified byte-exact against")
    w("//   scipy.stats.qmc.Sobol(scramble=False) in the pkg224 test.")
    w("//")
    w("// Construction (pbrt-v4 src/pbrt/util/lowdiscrepancy.h, Apache-2.0):")
    w("//   sobol(index, dim) = XOR of kSobolMatrices32[dim][j] over set bits j of index.")
    w("")
    w("#ifndef ASTRORAY_SAMPLING_SOBOL_MATRICES_H")
    w("#define ASTRORAY_SAMPLING_SOBOL_MATRICES_H")
    w("")
    w("#include <cstdint>")
    w("")
    w("namespace astroray {")
    w("")
    w("// Number of dimensions with true Sobol' direction vectors. Draws at")
    w("// dimension >= kSobolNumDims fall back to the PCG32 white-noise path")
    w("// (documented in progressive_sobol_device.h) -- deep-path tail dims where")
    w("// low-discrepancy structure has little value and quality is dominated by")
    w("// the low dims (pixel AA, primary BSDF/NEE).")
    w(f"inline constexpr uint32_t kSobolNumDims = {NUM_DIMS};")
    w(f"inline constexpr uint32_t kSobolMatrixSize = {MATRIX_SIZE};  // 32-bit direction vectors")
    w("")
    w("// kSobolMatrices32[dim][j] -- the j-th 32-bit direction vector of dimension")
    w(f"// `dim`. Bits at j >= {bits} are 0 (SciPy supplies {bits}; sample indices never")
    w(f"// reach 2^{bits}).")
    w("inline constexpr uint32_t kSobolMatrices32[kSobolNumDims][kSobolMatrixSize] = {")
    for d in range(NUM_DIMS):
        vals = []
        for j in range(MATRIX_SIZE):
            if j < bits:
                v = (int(sv[d][j]) << scale_shift) & 0xFFFFFFFF
            else:
                v = 0
            vals.append(f"0x{v:08x}u")
        # 8 per line for readability
        w(f"  {{ // dim {d}")
        for k in range(0, MATRIX_SIZE, 8):
            w("    " + ", ".join(vals[k:k + 8]) + ",")
        w("  },")
    w("};")
    w("")
    w("}  // namespace astroray")
    w("")
    w("#endif  // ASTRORAY_SAMPLING_SOBOL_MATRICES_H")

    with open(OUT, "w", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    print("wrote", OUT,
          f"({NUM_DIMS} dims x {MATRIX_SIZE} vectors, scipy {scipy.__version__}, bits={bits})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

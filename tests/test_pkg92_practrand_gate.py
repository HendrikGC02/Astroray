"""
pkg92 acceptance test: PractRand statistical gate for WavefrontRNG.

Tests that the keyed (pixel,sample,dimension) stream from WavefrontRNG
passes PractRand's standard battery of statistical tests, verifying that
our keying implementation doesn't introduce detectable bias.

PCG32 itself passes PractRand (and BigCrush) per O'Neill 2014. This gate
verifies our stream-keying code is correct.

References:
- O'Neill 2014 PCG paper: https://www.pcg-random.org/paper.html
- PractRand: https://pracrand.sourceforge.net/ (public domain, Doty-Humphrey)
- Research notes: .astroray_plan/docs/pkg92-rng-research.md
"""

import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest


def test_wavefront_rng_practrand_gate():
    """
    WavefrontRNG keyed stream passes PractRand without failures.

    We feed 32 MB (2^25 bytes = 8M uint32s) from the keyed
    (pixel=42, sample=13, dim=*) stream into PractRand's RNG_test
    tool and assert no "FAIL" appears in the output.

    32 MB is a lightweight gate suitable for CI. Full testing would
    run to 1 TB+ (PractRand default stopping point), but that's
    impractical for local testing. The 32 MB gate catches blatant
    keying bugs (wrong bit-mixing, broken LCG state update, etc.)
    without requiring hours of runtime.
    """
    import astroray_test_helpers

    # Locate PractRand RNG_test executable
    # Cross-platform: RNG_test on Linux, RNG_test.exe on Windows
    repo_root = Path(__file__).parent.parent
    practrand_dir = repo_root / "third_party" / "PractRand"

    # Try both names (Linux first for CI, then Windows for local dev)
    rng_test_exe = practrand_dir / "RNG_test"
    if not rng_test_exe.exists():
        rng_test_exe = practrand_dir / "RNG_test.exe"

    if not rng_test_exe.exists():
        pytest.skip(
            f"PractRand RNG_test not found in {practrand_dir}. "
            "Build it with: cd third_party/PractRand && "
            "g++ -c src/*.cpp src/RNGs/*.cpp src/RNGs/other/*.cpp -O3 -Iinclude && "
            "ar rcs PractRand.a *.o && "
            "g++ -o RNG_test tools/RNG_test.cpp PractRand.a -O3 -Iinclude -Itools -pthread"
        )

    # Generate 8M uint32s (32 MB) from WavefrontRNG
    # Using (pixel=42, sample=13) as a fixed stream ID; dimension increments
    pixel = 42
    sample = 13
    seed = 0xDEADBEEF
    num_values = 8 * 1024 * 1024  # 8M uint32s = 32 MB

    print(f"\n[pkg92-practrand] Generating {num_values} uint32s from WavefrontRNG...")

    # Create one RNG instance for the (pixel, sample) stream
    # Each call to UniformUInt32() auto-increments the dimension counter
    # This tests the actual usage pattern: one RNG instance per (pixel,sample),
    # dimension increments on each draw.
    rng = astroray_test_helpers.WavefrontRNG(pixel, sample, seed)

    values = np.empty(num_values, dtype=np.uint32)
    for i in range(num_values):
        values[i] = rng.UniformUInt32()

    # Convert to binary bytes (little-endian)
    binary_data = values.tobytes()

    print(f"[pkg92-practrand] Feeding {len(binary_data)} bytes to PractRand...")

    # Run PractRand's RNG_test with stdin32 input format
    # PractRand will test progressively: 128MB, 256MB, etc.
    # We provide 32MB total. PractRand will test at 32MB and stop.
    # Use "-tlmax 32MB" to explicitly cap at 32 MB
    try:
        proc = subprocess.Popen(
            [str(rng_test_exe), "stdin32", "-tlmax", "32MB"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=False,  # Binary mode for stdin
        )
        stdout_data, _ = proc.communicate(input=binary_data, timeout=120)
        output = stdout_data.decode("utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        proc.kill()
        pytest.fail("PractRand RNG_test timed out after 120 seconds")
    except Exception as e:
        pytest.fail(f"Failed to run PractRand RNG_test: {e}")

    print("[pkg92-practrand] PractRand output:\n" + output)

    # Assert no "FAIL" in output
    # PractRand reports failures as lines containing "FAIL"
    if "FAIL" in output:
        # Extract failure lines for clarity
        fail_lines = [line for line in output.split("\n") if "FAIL" in line]
        pytest.fail(
            f"PractRand detected statistical failures:\n" + "\n".join(fail_lines)
        )

    # Also check that PractRand actually ran (not an error)
    if "using PractRand" not in output:
        pytest.fail(f"PractRand did not start correctly. Output:\n{output}")

    print("[pkg92-practrand] PractRand gate passed: no failures detected.")


if __name__ == "__main__":
    # Allow running as a standalone script for manual testing
    test_wavefront_rng_practrand_gate()

#!/usr/bin/env python3
"""pkg261 — extract Cycles' `table_ggx_gen_schlick_ior_s` LUT to an Astroray .bin.

Cycles estimates the directional-hemispherical albedo of a rough generalized-
Schlick / dielectric microfacet reflection lobe (the value fed to
`closure_layering_weight` to attenuate the diffuse layer beneath the specular)
with a precomputed 16x16x16 lobe-averaged Schlick blend factor `s`:

    intern/cycles/kernel/closure/bsdf_microfacet.h  (BSD-3-Clause)
    `bsdf_microfacet_estimate_albedo`, GENERALIZED_SCHLICK exponent<0 branch
    (lines 423-445 at blender/blender@eaa5f63b):
        rough = sqrt(sqrt(alpha_x*alpha_y))          # perceptual roughness
        z     = sqrt(|ior-1| / (ior+1))
        s     = lookup_table_read_3D(rough, cos_NI, z, ggx_gen_schlick_ior_s, 16,16,16)
        albedo = mix(f0, f90=1, s) * reflection_tint

The `s` table itself is baked, Apache-2.0 data shipped verbatim in
`intern/cycles/scene/shader.tables` as `static const float
table_ggx_gen_schlick_ior_s[4096]`. This script parses that C initializer and
writes the 4096 floats as IEEE-754 float32 little-endian, in the file's own
element order (x=rough fastest, then y=cos_NI, then z), which is exactly the
axis order Cycles' `lookup_table_read_3D` and Astroray's
`DisneyEnergyCompensationTables::sample3D` consume (no transpose) — the same
extraction convention as the shipped `ggx_E.bin` / `ggx_glass_E.bin`
(see data/disney_compensation/README.md).

Pinned source (matches the pkg151 glass-table extraction commit):
    https://raw.githubusercontent.com/blender/blender/
        eaa5f63ba20e64a439af48a1600cb9ed7bf9bdf0/intern/cycles/scene/shader.tables
  License: Apache-2.0 (SPDX-FileCopyrightText: 2011-2022 Blender Foundation).

Usage:
    # from a local checkout of shader.tables:
    python scripts/data/extract_ggx_gen_schlick_ior_s.py <path/to/shader.tables>
    # or fetch the pinned commit directly:
    python scripts/data/extract_ggx_gen_schlick_ior_s.py --fetch
    # default --out is data/disney_compensation/ggx_gen_schlick_ior_s.bin
"""
import argparse
import re
import struct
import sys
import urllib.request

TABLE_NAME = "table_ggx_gen_schlick_ior_s"
TABLE_LEN = 4096  # 16 * 16 * 16
PINNED_COMMIT = "eaa5f63ba20e64a439af48a1600cb9ed7bf9bdf0"
PINNED_URL = (
    "https://raw.githubusercontent.com/blender/blender/"
    f"{PINNED_COMMIT}/intern/cycles/scene/shader.tables"
)
DEFAULT_OUT = "data/disney_compensation/ggx_gen_schlick_ior_s.bin"

# Matches C float literals like "0.000000f", "0.999398f", "1.2e-05f".
_FLOAT_RE = re.compile(r"[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?f?")


def parse_table(text):
    m = re.search(
        rf"{TABLE_NAME}\[{TABLE_LEN}\]\s*=\s*\{{(.*?)\}};", text, re.S
    )
    if not m:
        raise SystemExit(f"could not find {TABLE_NAME}[{TABLE_LEN}] in input")
    vals = [float(tok.rstrip("f")) for tok in _FLOAT_RE.findall(m.group(1))]
    if len(vals) != TABLE_LEN:
        raise SystemExit(
            f"expected {TABLE_LEN} floats, parsed {len(vals)} — refusing to write"
        )
    return vals


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "shader_tables",
        nargs="?",
        help="path to a local intern/cycles/scene/shader.tables",
    )
    ap.add_argument(
        "--fetch",
        action="store_true",
        help=f"download shader.tables from the pinned commit {PINNED_COMMIT}",
    )
    ap.add_argument("--out", default=DEFAULT_OUT, help=f"output .bin (default {DEFAULT_OUT})")
    args = ap.parse_args()

    if args.fetch:
        with urllib.request.urlopen(PINNED_URL) as resp:
            text = resp.read().decode("utf-8")
    elif args.shader_tables:
        with open(args.shader_tables, "r", encoding="utf-8") as fh:
            text = fh.read()
    else:
        ap.error("provide a shader_tables path or --fetch")

    vals = parse_table(text)
    with open(args.out, "wb") as fh:
        fh.write(struct.pack("<%df" % TABLE_LEN, *vals))
    print(
        f"wrote {args.out}: {TABLE_LEN} float32 LE "
        f"(min {min(vals):.6f}, max {max(vals):.6f})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

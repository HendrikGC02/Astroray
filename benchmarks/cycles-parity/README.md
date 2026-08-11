# Cycles Parity Benchmark

> **2026-06-08:** the Blender Foundation demo scenes (Classroom, BMW27, Junkshop,
> UDIM_monster) were **removed** — they ship from old Blender versions, load/render
> incorrectly under current Blender/Cycles, and the Classroom reference render was
> broken. Only the self-authored `cornell` control scene remains. The harness below
> is retained (it runs cornell); re-introduce a demo scene by adding a pinned
> `[[scene]]` block to `scenes/manifest.toml` with a current-Blender reference EXR.

pkg71 provides a reproducible harness for comparing Astroray CPU/GPU output
against Cycles CPU/CUDA on a small Blender demo scene matrix. It records
quality as SSIM against a Cycles-CPU EXR reference and records timing/memory
for trend tracking. SSIM is the only correctness gate in this package;
performance is recorded but not gated until the later wavefront/sync work.
SSIM is computed on linear EXR values with both images clipped to their shared
99.9th percentile, which keeps isolated firefly outliers from dominating the
structural comparison.

## Layout

- `scenes/cornell/` contains the repo-shipped MIT Cornell control scene
  descriptor. The harness builds the same triangle scene for Cycles and
  Astroray so Cornell compares matching camera, geometry, materials, and light.
- `scenes/cache/` is gitignored and holds downloaded Blender Foundation scene
  archives.
- `scenes/scripts/fetch_scenes.py` downloads Classroom, Junkshop, and BMW27
  into the cache, verifies SHA-256 when pinned, and writes attribution for
  CC-BY assets. Monster was dropped in pkg76 (the file ships without a render
  camera and Cycles itself errors on it; see `manifest.toml` header).
- Astroray-side `.blend` ingestion is handled by `tools/blend_import` (pkg76)
  in parity scope: Principled BSDF base colour, point/sun/spot/area lights,
  background colour, perspective camera. Anything else is logged and skipped.
  The harness gates Cornell rows at SSIM ≥ 0.95 and `.blend`-imported rows at
  SSIM ≥ 0.85, the relaxed threshold reflecting parity-scope shader-graph
  fidelity loss.
- `refs/` stores `MANIFEST.sha256`; large `*.exr` references are gitignored.
- `scripts/run_parity.py` runs the matrix and writes a CSV.
- `scripts/summarize_parity.py` converts a CSV into a Markdown summary.

## Scene Licensing

Only MIT/CC0 metadata is committed to this repository. Large CC0 scenes are
downloaded into the local cache. CC-BY scenes are also downloaded locally and
the fetch script generates `scenes/cache/ATTRIBUTION.md`; keep that attribution
with any published summary or CSV bundle.

Victor is explicitly excluded because it is CC-BY-NC. The fetch script has a
non-empty deny-list with a sentinel and asserts before download if any URL
matches the blocked Victor/CC-BY-NC patterns.

## Quick Start

```powershell
python benchmarks\cycles-parity\scenes\scripts\fetch_scenes.py --dry-run
python scripts\run_parity.py --scenes cornell --engines astroray-cpu
python scripts\summarize_parity.py benchmarks\cycles-parity\<date-machine>.csv
```

Set `--blender` to a Blender 5.x executable (5.1+ pinned project-wide) for Cycles rows. Set
`--astroray` to the standalone Astroray binary if it is outside the default
build locations.

## References

The process-isolated runner pattern follows the Apache-2.0 Blender/Cycles
benchmark precedents:

- Blender Cycles `intern/cycles/test/integration/`
- Blender benchmark project: `https://projects.blender.org/blender/blender-benchmark`
- LuxCore benchmark suites were read for comparison only; no GPL code is
  mirrored here.

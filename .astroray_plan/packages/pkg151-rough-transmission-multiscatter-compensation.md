# pkg151 — Rough-transmission multi-scatter energy compensation (unmasked by the pkg149 sampler fix)

**Pillar:** 2 (materials / BSDF energy conservation)
**Track:** A
**Codex-paste-ready:** no (an energy-compensation port with an ior-dimensioned table and a furnace calibration loop)
**Status:** implemented, PR #519 — **✅ ADJUDICATED 2026-07-25 (architect): MERGEABLE STANDALONE as groundwork**, conditional on (a) CI green on the final head, and (b) HW verification covering the three items in the adjudication block below. **The furnace-restoration gate is REMOVED from this package's scope — the stack premise is FALSIFIED** (the honestly pre-registered magnitude probe `.astroray_plan/docs/pkg151-glass-multiscatter-magnitude-notes.md` shows the Cycles glass compensation ceiling is ~1.03× at ior=1.5 vs the 1.2×–11× the deficit requires; with `670e583` stacked the furnace is statistically unchanged at 0.11–0.82). The deficit's true root cause is now owned by **pkg154** (investigation-first); the chi² glass[0.3-45] un-xfail stays with pkg149, which stays HELD behind pkg154. What this package still delivers: the faithful cited port (CPU `roughTransmissionEval` + GPU twin), the glass LUT extraction, the GPU table-upload infrastructure, and the 9/9-tested trilinear sampler — all needed regardless of the root cause, all additive, main-sampler furnace unchanged-green (0.937–1.0). (Research confirmation record: `.astroray_plan/docs/pkg151-cycles-glass-tables-research.md`.)

> **✅ ADJUDICATION (2026-07-25, architect — PR #519):** Merge standalone as groundwork, **conditional on**: (1) CI green; (2) HW verification confirming — (i) the new GPU table-upload path actually loads the glass LUTs on RTX (new infra, never HW-exercised), (ii) CPU==GPU per-channel mean-ratio parity on a rough-transmission scene, (iii) main-sampler rough-glass furnace unchanged in its 0.937–1.0 band; wavefront_diff/perf failures during that run are dispositioned per the pkg153 interim attribution protocol, not against this PR; (3) the gate transfer to pkg154 recorded (this commit). Rationale: the port is faithful and cited, everything is additive with green suites, and the negative result was flagged BEFORE measurement — exactly the pkg146 discipline; holding correct groundwork hostage to a falsified premise would waste it. **Merge-conflict note:** the PR branch also edits this Status line — main's version (this one) wins; union the docs.
**Estimated effort:** M
**Depends on:** pkg149's worktree fix (`Astroray-pkg149`, local commit `670e583` — the corrected `sampleGgxVNDF`). Distinct from **pkg129** (Turquin *reflection* LUTs for metals + the GPU placeholder) — same technique family, different lobe, different table dimensionality (transmission needs an **ior axis**); do NOT fold them: pkg129 is coupled to the metal/GPU-placeholder work and would drag pkg149's ship date.

**Origin:** pkg149 root-cause session (2026-07-24). The azimuth-swapped
`sampleGgxVNDF` (pbrt-v4 `Lerp` args transposed) was inflating apparent
rough-transmission energy; with the corrected sampler the rough-glass furnace
drops to **0.09–0.82** (was 0.94–1.0), and the single-scatter estimator median
matches **`G1(wi)/ior²` theory almost exactly** — the textbook signature of
missing multiple-scattering energy, not a sampler or radiometry bug. Three
alternative hypotheses were ruled out by rebuild-and-measure; full trail:
`.astroray_plan/docs/pkg149-disney-rough-transmission-research.md` (worktree,
lands with the pkg149 PR).

---

## ⚠️ Supersession — pkg118 Part B is confounded

pkg118 (DONE, PR #423) concluded "the deficit was NOT missing multi-scatter
(Part B Kulla-Conty correctly REJECTED)" — but that measurement ran on the
**azimuth-swapped sampler**, which was over-delivering transmission energy.
The rejection is therefore confounded and is **superseded for the
corrected-sampler world**: re-measure on `670e583` before assuming anything
from pkg118 Part B. (pkg118's actual fix — the Jakob-Hanika albedo-LUT eta²
clamp — remains valid and untouched.)

## Fix contract (port, don't invent — CLAUDE.md §6)

Add a Turquin-style multiple-scattering energy compensation for the rough
**transmission** lobe, applied to the single-scatter GGX BTDF throughput,
matching what production engines ship:

1. **Canonical references:**
   - **Turquin 2019, "Practical multiple scattering compensation for
     microfacet models"** (Imageworks tech report) — the albedo-scaling
     formulation for dielectrics **including transmission**, with `E_ss`
     parameterized by (roughness, cos_theta, **ior**) — the ior axis is what
     distinguishes this from the reflection-only pkg60/pkg129 tables; both
     eta and 1/eta directions are needed.
   - **Cycles** `intern/cycles/kernel/closure/bsdf_microfacet.h`
     `microfacet_ggx_preserve_energy` + the **glass** E/Eavg albedo tables it
     consumes for `CLOSURE_BSDF_MICROFACET_GGX_GLASS` (**BSD-3-Clause** for
     `bsdf_microfacet.h`, **Apache-2.0** for the `shader.tables` data — both
     allow-listed; Blender replaced stochastic multiscatter-GGX with exactly
     this in commit `888bdc1` / PR blender/blender#107958).
     **✅ CONFIRMED against live source 2026-07-24** (architect pre-dispatch;
     full record `.astroray_plan/docs/pkg151-cycles-glass-tables-research.md`):
     tables `table_ggx_glass_E[4096]` (16×16×16 rough×mu×z),
     `table_ggx_glass_Eavg[256]` (16×16), plus `_inv_` variants used when
     `ior < 1`; ior axis `z = sqrtf(fabsf((ior - 1)/(ior + 1)))`; lookups
     `lookup_table_read_3D(kg, rough, mu, z, ofs, 16, 16, 16)` /
     `lookup_table_read_2D(kg, rough, z, avg_ofs, 16, 16)`; commits pinned in
     the research note. Port Cycles' pre-baked glass tables outright into
     `data/disney_compensation/` beside the existing `ggx_E.bin`/`ggx_Eavg.bin`
     (which are already the Cycles reflection tables — pkg60/pkg145 precedent);
     extend `DisneyEnergyCompensationTables` with a trilinear `sample3D` +
     the `z(ior)` remap + the `inv` swap (the glass tables are 16-res, not
     kGgxSize=32).
   - **adobe/openpbr-bsdf** (Apache-2.0) — carries 7 CUDA-ready multiscatter
     energy LUTs incl. dielectric transmission (verified in
     `2026-07-pbr-advances-research-pass2.md`); a second license-clean table
     source if the Cycles extraction is awkward.
2. Apply on the CPU Disney rough-transmission path first (where the furnace
   gate lives); mirror on the GPU dielectric/closure-graph path (memory
   `gpu-dielectric-lowers-to-closure-graph`) with RTX parity.
3. Validate the estimator identity the research doc establishes: post-fix,
   single-scatter + compensation should integrate the furnace to ~1.0 where
   the theory predicted `G1(wi)/ior²` for single-scatter alone.
4. Table provenance + license recorded in `data/` README per the pkg60/pkg145
   precedent.

## Gates

- ~~**Rough-glass furnace restored:** [0.92, 1.03] (the pkg118 gate band) across
  R ∈ {0.05, 0.1, 0.3, 0.6, 1.0} **on the corrected sampler** (`670e583`
  stacked) — the 0.09–0.82 regression is the package's reason to exist.~~
  **TRANSFERRED to pkg154 (2026-07-25 adjudication):** measured unreachable
  from this package — the compensation ceiling is ~1.03× (see magnitude-notes
  doc). This package's furnace obligation reduces to: main-sampler furnace
  UNCHANGED (0.937–1.0 band).
- **pkg149's peak-alignment stays green** (<2°, N≥100k) — compensation scales
  throughput magnitude, it must not touch sampled direction shape.
- chi² glass[0.3-45]: report the number on the stacked pair; the un-xfail is
  owned by pkg149 and may only flip with both packages' gates green
  (`--runxfail` verified).
- White-furnace + smooth-glass + caustic/prism refbank unchanged; **visual
  check mandatory** on the rough-glass and caustic renders (memory
  `general-photon-loop-needs-solid-glass`).
- CPU==GPU parity per-channel mean-ratio on a rough-glass scene; build
  evidence per CLAUDE.md.

## Non-goals

- Reflection multiscatter LUTs / GPU metal placeholder (pkg129).
- Re-opening pkg118's albedo-LUT clamp fix (valid, untouched).
- Any further sampler-shape changes (pkg149/pkg150 own those).

## Hardware verification 2026-07-25

**Hardware:** RTX 5070 Ti, Windows 11 Enterprise 10.0.26200, CUDA 12.8 (nvcc, v12.6 also
present), MSVC VS2022 BuildTools 14.44.35207. Bound to PR #519 head SHA `e2c4d5cd33d0b05d79521bc928add04f849ae3ae`. Verdict: **PASS** (conditions i/ii/iii + no new
test failures, per the architect's 2026-07-25 adjudication scope — furnace-restoration
magnitude is explicitly out of scope, owned by pkg154).

**Build note:** `build_cuda_worktree.bat` hit the known pre-existing Debug-config footgun
(memory `build-cuda-worktree-debug-config.md`) on this VS17-2022 multi-config worktree —
omits `--config Release`, defaults to Debug, `cl D8016 '/RTC1'+'/O2'` clash, exit 5. Not a
pkg151 regression. Remediated with `cmake --build build_cuda --config Release --target
astroray --target astroray_test_helpers` under the same `vcvars64.bat` env → exit 0. HEAD
SHA verified throughout.

**Pass/fail table:**

| Check | Result |
|---|---|
| (i) GPU glass-LUT upload infra | PASS — fresh-process probe render, mean=0.994448, center-patch=0.999856, 0 NaN, 0 negative, max=1.0, no CUDA upload errors |
| (ii) CPU==GPU per-channel parity (rough glass, R=0.45, ior=1.5, 256x256, seed=151519) | PASS w/ flagged pre-existing caveat — R ratio 0.9798 (marginally below ~0.98 floor), G 0.9915, B 0.9906; 0 NaN either side; **R ratio reproduces byte-identically on main pre-pkg151 (0.978025 vs 0.977974)** — pre-existing baseline divergence, Δ≈0.00005, unmoved by this PR |
| (iii) Main-sampler furnace unchanged | PASS — 5/5 passed; CPU R=0.1/0.3/0.6/1.0 = 0.9374/0.9997/0.9999/0.9996 (exact match to implementer's claimed values); GPU 0.9510/0.9989/1.0000/1.0000; all within [0.92,1.03] |
| tests/test_pkg151_glass_table_lookup.py | 9/9 passed |
| tests/test_disney_energy_conservation.py | 271 passed |
| tests/statistical/test_chi2_bsdf.py -m "not slow" | 7 passed, 165 deselected, 1 xfailed (test_chi2_disney_glass[0.3-45] correctly stays XFAIL, owned by pkg149) |
| wavefront_diff/ suite | Skipped per pkg153 interim-attribution protocol — diff touches no wavefront/spectral-table/light files |
| Full tests/ (excl. wavefront_diff) | 3 failed, 1465 passed, 69 skipped, 24 xfailed, 6 xpassed, 6 warnings, 420.89s — all 3 failures (2 cp1252 console-encoding artifacts + 1 SSIM assertion) confirmed byte-identical on main pre-pkg151, not new regressions |

**Visual inspection:** CPU/GPU parity renders (rough disney glass, colored floor+light)
show qualitative match — same caustic-speckle ring, same two light-reflection highlights,
no NaN/magenta/black pixels, no banding. Pre-existing `tests/test_rough_glass.py`
red/green-split renders (regenerated during the run) show expected progressive blur with
increasing roughness, speckle character consistent with other rough-transmission renders
in this codebase — not new fireflies. Caustic/prism refbank (pkg113 glass sphere, pkg29
prism, pkg31 dispersive glass) regenerated with no visual anomalies.

**Anomalies worth watching:** the condition-(ii) R-channel GPU/CPU ratio (~0.978-0.980)
sits just below the nominal 0.98 floor and is stable across spp (512/2048) and seeds — a
real, small, pre-existing structural GPU/CPU divergence at this scene/roughness, present
identically on main. Not introduced or moved by pkg151. Root cause not investigated here
(out of this verifier's scope) but flagged for whoever eventually owns general CPU/GPU
rough-dielectric parity tightening.

Full numbers: `test_results/overnight_report_2026-07-24/pkg151_hw_numbers.json` (main
repo). PR comment with the full measured table:
https://github.com/HendrikGC02/Astroray/pull/519#issuecomment-5071518905

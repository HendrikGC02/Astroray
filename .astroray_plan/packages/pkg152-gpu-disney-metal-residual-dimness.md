# pkg152 — GPU Disney twin divergence: metal residual dimness + the low-roughness rough-transmission furnace deficit (blocks PR #522)

**Pillar:** 3 (GPU/CPU parity)
**Track:** A (GPU lane; RTX-gated — CI is blind to it)
**Codex-paste-ready:** no (measure-first parity investigation; the fix is chosen by instrumentation, not in advance)
**Status:** partially done (PR #523, merged 2026-07-25 — spectral eta² guard widened [THE #522 furnace blocker, verified 0.9987-1.0000 on-stack], mid/high-roughness metal compensation mirrored, clearcoat double-divide fixed; near-delta metal residual measured ~1.0 by verifier vs 0.60-0.77 in research doc — **reconciliation now owned by pkg158** (filed 2026-07-25, the split-out follow-up; its Step 0 is the scene-controlled re-measure of both setups — until it reports, neither number is citable)). **RECONCILED 2026-08-02 (pkg158 Step 0, PR #TBD): Outcome A** — the 0.60-0.77 Symptom-(a) near-delta table below is SUPERSEDED (it was carried forward from pkg141 post-#518, not re-measured on the #523 build); re-measured on one build b036ac93 the near-delta reads 0.924-0.949 linear with no near-delta cliff, confirming the #523 verifier's ~1.0. Only a uniform ~5-8% GPU-dim (within [0.90,1.10], not near-delta-specific) remains. No code.
**Status (original, superseded above):** ~~open — dispatchable. PROMOTED 2026-07-25 (last-call): HEADS the next run's queue.~~ #518 is merged, so the original wait condition is satisfied; and this package's scope is **WIDENED** (architect decomposition call) to absorb the **pkg149-GPU remainder** — the low-roughness GPU-only rough-transmission furnace deficit that blocks draft PR #522 (see "2026-07-25 evidence" below). Rationale for one package, not two: both symptoms are stable, deterministic, GPU-dim divergences of the same `gpu_materials.h` Disney twin; one CPU-vs-GPU per-event instrumentation harness convicts both; the candidate mechanism list overlaps (missing CPU-side compensation terms never mirrored to the GPU). **Split-clause:** if instrumentation proves the two symptoms have unrelated mechanisms, fix the #522 blocker here and split the metal remainder back out as its own package — do not let either finding stall the other's fix. **CONFIRMED FIRED** — see Status above.
**Estimated effort:** S–M (the pkg141 instrumentation pattern is reusable; likely one or a few missing terms to mirror)
**Depends on:** pkg141/PR #518 merged (this package's baseline IS that PR's post-fix state). Related: pkg129 (Turquin reflection multiscatter LUTs) may be the fix vehicle if the missing term turns out to be the CPU-side reflection compensation — do not implement pkg129 from here; hand over if convicted.

**Origin:** pkg141 hardware verification (2026-07-25, PR #518, RTX 5070 Ti). After the closure-dispatch fix, GPU/CPU per-channel mean ratios are a stable, bit-deterministic 0.60–0.77 at near-delta (roughness ≤ 0.1), 0.86–0.94 at mid roughness, and 0.64–0.89 at roughness 0.9 — inside pkg141's deliberately wide [0.4, 2.5] acceptance band (the package closed on its contract), but structurally dim, channel-ordered R < G < B, and the opposite sign of the original 2.7–4.0× defect.

---

## 2026-07-25 evidence — the #522 low-roughness GPU furnace deficit (this package's second symptom, and the merge blocker)

HW re-verify of PR #522 @ `e0fe9d8` (verdict comment
https://github.com/HendrikGC02/Astroray/pull/522#issuecomment-5073008663;
numbers `test_results/overnight_report_2026-07-24/pkg149_hw_numbers.json` key
`reverify_e0fe9d8`): on the #522 stack the **CPU** rough-glass furnace is
0.997–0.999 (contract met), but the **GPU** furnace reads, vs gate band
[0.90, 1.06]:

| Roughness | pre-fix `19d4e9f` | post-frontFace/TIR-fix `e0fe9d8` |
|---|---|---|
| 0.1 | 0.12953 | **0.12953 (byte-unchanged)** |
| 0.3 | 0.26903 | 0.28330 |
| 0.6 | 0.57117 | 0.89628 |
| 1.0 | 0.97060 | 1.0 |

The signed-off frontFace/TIR fix (`gpu_disney_roughReflectionEval`) recovered
the high-roughness regime and left R=0.1 bit-identical — the reviewer's
**compounding-masking analysis** holds: the fixed sub-lobe
(internal/TIR-adjacent reflection) is sampled in proportion to roughness, so
its recovery scales with roughness, and a SECOND, low-roughness-dominant,
GPU-only term dominates R≤0.3. That residual is quite possibly exactly the
missing `gpu_disney_eval` compensation terms hypothesis 1 below tracks (the
CPU-side pkg60/118/145/154 energy terms have no GPU mirror), or another
un-audited twin divergence in the same region. Both this deficit and the
metal dimness below are stable deterministic GPU-dim ratios in the same twin
— the shared instrumentation harness should dump both material configs in one
pass.

## Defect

GPU renders Disney metal consistently dimmer than the canonical CPU (pkg123-adjudicated) reference. The ratio is stable across seeds and channel-ordered — per memory `mc-noise-vs-deterministic`, a stable per-channel ratio that does not decrease with √SPP is a structural (matrix/units/term) divergence, NOT sampler noise.

## Leading hypotheses (measure first — pkg141's discipline)

1. **Un-mirrored CPU-side energy terms (the pkg141 Lessons hypothesis).** The pkg60/pkg118/pkg138/pkg145 energy-fix series touched `plugins/materials/disney.cpp` only; `gpu_disney_eval` (`include/astroray/gpu_materials.h`) may lack the CPU's reflection multiscatter compensation (`1 + Fms·(1−E)/E`, `disney.cpp:384` region, fed by `table_ggx_E`/`table_ggx_Eavg`) and/or the pkg145 diffuse-under-specular coupling. A missing `≥1` compensation factor on the GPU predicts GPU-dim with the deficit growing where (1−E)/E grows — check against the measured roughness/channel profile. Note pkg151/PR #519 just added GPU-side table-upload infrastructure for the glass LUTs — the same mechanism can carry `table_ggx_E`/`Eavg` to the GPU if this hypothesis convicts.
2. **Channel ordering R < G < B suggests a Fresnel/F0 spectral term difference** (conductor F0 color path diverging between `disney.cpp` and the GPU twin) — dump `F` per channel for identical `(wo, wi)`.
3. The pkg141 fix's second stacked bug (`/(4·NdotL·NdotV+0.001f)` stale divide) was removed — verify no OTHER stale denominator/epsilon remains in the newly-reachable `gpu_disney_eval` path (the function was dead weight pre-#518 and never previously audited live).

## Fix contract

1. Reuse the pkg141 instrumentation: per-event `(f, pdf, throughput)` dump CPU-vs-GPU for identical `(wo, wi)` grids at roughness {0.0, 0.1, 0.3, 0.9}; convict the term(s) before editing.
2. Mirror the convicted CPU term(s) into `gpu_materials.h` with the same citations the CPU code carries (CLAUDE.md §6); CPU stays untouched (canonical).
3. If the convicted term is the full pkg129 reflection-LUT scope, STOP and hand over to pkg129 rather than partially duplicating it.

## Gates

- **The #522 blocker:** `test_disney_rough_glass_furnace_energy_gpu` measured
  on the PR #522 stack after this package's convicted fix — the R=0.1/0.3
  rows are the target (band [0.90, 1.06]); report the measured values, do not
  pre-assert them. #522's merge decision then re-runs its own checklist.
- GPU/CPU per-channel mean ratio within [0.90, 1.10] across the pkg123 parity grid (near-delta AND mid/high roughness rows — tighten from pkg141's [0.4, 2.5] band; propose the tightened band in the PR for architect sign-off).
- pkg141's promoted (un-xfail'd) rows stay green; furnace/energy suites green; wavefront-diff attribution per the pkg153 protocol while that package is open.
- Build evidence per CLAUDE.md; RTX verification serialized (memory `cuda_verifier_concurrency`).

## Non-goals

- The CPU implementation (canonical post-#498; do not touch `disney.cpp`).
- pkg129's LUT port itself (hand over if convicted).
- The dielectric/transmission lobes (pkg149/pkg151/pkg154 territory).

## Provenance

Filed by the architect from the PR #518 adjudication (2026-07-25) — measured ratios in the pkg141 spec's "Hardware verification 2026-07-25" section; the un-mirrored-twin hypothesis is the pkg141 implementer's own Lessons entry.

---

## Hardware verification 2026-07-25 (PR #523, RTX 5070 Ti)

**Hardware:** NVIDIA GeForce RTX 5070 Ti, driver 610.47, CUDA 12.8.61 (nvcc build cuda_12.8.r12.8/compiler.35404655_0), Windows 11 Enterprise 10.0.26200, Python 3.13.12. Bound to commit 6dc83d401fa714900b0f69c013451c6697943169 (verified via `git rev-parse HEAD` before build).

**Verdict: PASS.**

### Claim 1 -- the decisive #522-stack furnace gate (reconstructed measurement branch)

Reconstructed the implementer's local throwaway measurement branch exactly as described: a fresh worktree at this package's HEAD (6dc83d4) with `git diff origin/main origin/pkg149-rough-transmission-sample-pdf -- plugins/materials/disney.cpp include/astroray/gpu_materials.h` applied cleanly on top, rebuilt Release+CUDA from a clean configure, never pushed, and never touching the actual PR worktree. Measured:

| roughness | GPU (measured) | GPU (claimed) | CPU (measured) | CPU (claimed) | gate [0.90,1.06] |
|---|---|---|---|---|---|
| 0.05 | 0.998757 | 0.998757 | 0.998624 | 0.998624 | PASS |
| 0.10 | 0.998741 | 0.998741 | 0.998593 | 0.998593 | PASS |
| 0.30 | 0.999264 | 0.999264 | 0.998739 | 0.998739 | PASS |
| 0.60 | 1.000000 | 1.000000 | 0.998513 | 0.998513 | PASS |
| 1.00 | 1.000000 | 1.000000 | 0.996989 | 0.996989 | PASS |

Exact reproduction at all six decimal places. `test_disney_rough_glass_furnace.py` 5/5 passed, `test_pkg123_disney_metal_gpu_cpu_parity.py` 7/7 passed, `test_gpu_caustic_parity.py` 1 passed + 1 xfailed (pre-existing prism-rainbow xfail) -- 13 passed, 1 xfailed total, matching the implementer's claimed numbers exactly.

### Claim 2 -- this PR alone (main-based, no #522 stack): no regressions

Ran on the unmodified PR worktree (main + this PR only): furnace suites (`test_disney_rough_glass_furnace.py` 5/5, `test_dielectric_glass_furnace.py` 2/2), energy conservation (`test_disney_energy_conservation.py`, plus the clearcoat-parametrized cases in `test_material_plugins.py`/`test_material_properties.py`), chi2 not-slow (`tests/statistical/test_chi2_bsdf.py -m "not slow"`, all disney metallic/diffuse cases passed, one pre-existing `test_chi2_disney_glass[0.3-45]` xfail unrelated to this PR's GPU-only diff), Disney metal GPU/CPU parity (`test_pkg123_disney_metal_gpu_cpu_parity.py`, all 7 rows), caustic parity (`test_gpu_caustic_parity.py`, 1 passed + 1 pre-existing xfail), and clearcoat (`test_disney_clearcoat_adds_gloss`). Combined single pytest invocation: **296 passed, 165 deselected, 2 xfailed, 1 warning in 17.31s.**

Disney metal GPU/CPU parity numbers (gate [0.4,2.5]):

| roughness | R ratio | G ratio | B ratio |
|---|---|---|---|
| 0.00 | 1.0112 | 0.9969 | 0.9969 |
| 0.03 | 1.0112 | 0.9969 | 0.9969 |
| 0.05 | 1.0112 | 0.9969 | 0.9969 |
| 0.10 | 1.0063 | 0.9974 | 0.9930 |
| 0.30 | 0.9981 | 1.0033 | 0.9977 |
| 0.60 | 0.9990 | 0.9966 | 0.9907 |
| 0.90 | 1.0025 | 1.0008 | 0.9985 |

**Anomaly worth flagging:** this package's own research doc claims near-delta (roughness <= 0.10) is "UNCHANGED/unresolved" at ratio 0.60-0.77 on this exact test file and scene. The hardware measurement above shows near-delta ratios of 0.9930-1.0112 -- effectively 1.0, i.e. RESOLVED, not unresolved. Reproduced twice (full-suite run and an isolated `-p no:cacheprovider` rerun), byte-identical both times. This does not change the PASS verdict (the gate band [0.4,2.5] accepts both the claimed and the measured numbers), but the spec's own split-clause status ("symptom (a) partially fixed, near-delta unresolved, split out as follow-up") appears stale relative to the shipped code on this hardware. Flagged for architect review; not adjudicated here per the verifier's charter.

wavefront_diff: skipped -- this PR's diff (`gpu_ggx_tables.cuh/.cu`, `gpu_materials.h`, `energy_compensation.h`, `cuda_renderer.cu`, `CMakeLists.txt`) touches no wavefront kernel files, per the pkg153 quarantine protocol.

### Claim 3 -- new GPU table infra (`gpu_ggx_tables.cuh`/`.cu`)

Probe render (metallic Disney sphere, roughness=0.4, clearcoat=0.5, GPU) exercised the new table upload/lookup path: no CUDA errors, `astroray.__features__["cuda"]` True, `gpu_available` True, output fully finite, mean 0.6435.

### Claim 4 -- clearcoat

`test_disney_clearcoat_adds_gloss` PASSED -- direct regression coverage for the claimed stale double-divide + wrong-constant fix (`0.5` -> `0.25`, removed spurious `/(4*NdotL*NdotV+0.001f)`). Visual p99.5 luminance 0.21 (no coat) vs 0.22 (coat) -- present, physically modest, not overblown. `test_no_material_is_overexposed`'s `disney_clearcoat` case and `test_material_plugins.py::test_disney_energy_conservation`'s `clearcoat=1.0` case both PASSED.

### Claim 5 -- visual: rough-glass GPU render at R=0.1

Rendered on the reconstructed measurement branch (200x200, 128spp). Full-frame mean 0.9961, sphere-center-patch mean 0.9988 (matches the decisive-gate numeric R=0.10 GPU=0.998741). Read the PNG directly: the sphere now blends almost invisibly into the white furnace background -- consistent with the "previously-black, now near-invisible" claim. No fireflies, no magenta/black NaN pixels, no banding observed. Also inspected: `pkg113_gpu_glass_sphere.png`/`pkg113_cpu_glass_sphere.png` (clean focused caustic on the floor, GPU/CPU visually identical, no salt-and-pepper chromatic noise), `mat_disney_clearcoat.png` (subtle but present gloss increase, no artifacts), `mat_overexposure_disney_{glass,metallic,plastic,clearcoat}.png` (normal MC noise on glass, no NaN/degenerate patches), `pkg152_gpu_table_probe.png` (normal noisy metallic-clearcoat render, no anomalies).

### Anomalies worth watching

1. **Git-Bash `cmd /c` MSYS path-mangling**: `/c` gets silently expanded to a drive-letter path by MSYS's automatic path conversion, causing `cmd /c <script>` to launch an interactive nested shell instead of running the target (banner-only output, false-positive exit 0). Workaround: `MSYS_NO_PATHCONV=1 cmd.exe /c ...`. Worth fixing at the tooling level so future verifier runs don't silently no-op.
2. **`build_cuda_worktree.bat` Debug-config footgun reproduced again** on this VS-generator `build_cuda` tree (matches existing memory `build-cuda-worktree-debug-config`): the wrapper's `cmake --build build_cuda --target astroray` (no `--config`) resolved to Debug, `/RTC1`+`/O2` clash, D8016, exit 5. Worked around manually with `--config Release`; recommend fixing the wrapper script itself.
3. Near-delta Disney-metal dimness anomaly above (measured resolved, documented as unresolved) -- flag for architect, not a gate failure.

Full test logs: `test_results/verifier_run_pkg152_stepA.txt` (PR-alone), and the reconstructed-branch run in `Astroray-pkg152-measure/test_results/verifier_run_pkg152_measure_branch.txt`. Numbers JSON and PNGs copied to `test_results/overnight_report_2026-07-24/` with `pkg152_` prefix in the main repo.

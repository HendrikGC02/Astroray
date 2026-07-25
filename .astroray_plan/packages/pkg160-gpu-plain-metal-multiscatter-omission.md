# pkg160 — Plain `metal` is ~3.5× (median ~7×) too dark on the GPU: `gpu_metal_eval` omits the CPU's multiscatter energy term (wavefront-only path)

**Pillar:** 3 (GPU/CPU parity — the only GPU path we now ship)
**Track:** A (RTX-gated; CI is blind — see why nothing caught it)
**Status:** open — dispatchable. NEW, narrow, convicted finding (team-lead scene-controlled GPU scan, 2026-07-26, main @ `727a211`). Mechanism grounded in code below; the fix is a verbatim CPU-term mirror.
**Estimated effort:** S–M (the missing term already exists on the CPU; mirror it into `gpu_metal_eval` + add the parity gate that never existed).
**Depends on:** none. **Sibling, NOT parent:** pkg158/pkg152 (Disney metal, `gpu_disney_eval`) — a DIFFERENT function; see §Novelty for why this is filed separately and how to co-verify without conflating them.

---

## Defect / Motivation

Scene-controlled per-material patches on `disney_contact_sheet` (512², 512 spp,
seed 424242, **linear** output), GPU (wavefront) / CPU per-channel mean ratio:

| material | R | G | B | verdict |
|---|---|---|---|---|
| **metal** | **0.2787** | **0.2857** | **0.3159** | **GPU ~28% of CPU — a 3.5× deficit** |
| dielectric | 0.9987 | 0.9998 | 0.9999 | parity |
| diffuse_light | 0.9987 | 1.0007 | 1.0005 | parity |
| closure_matte | 0.9657 | 1.0059 | 0.9970 | near parity |

The earlier "broad 8–25% divergence across many scenes" reading was the aggregate
shadow of THIS one defect: dielectric and diffuse_light are at parity when
isolated; the whole-scene numbers were just proportional to how much metal each
scene contained. This is the narrow true thing.

**Robustness — it is the bulk of the distribution, not fireflies, and it is
worse than the mean says.** Metal patch, R channel, GPU/CPU ratio:

| spp | mean | median | p99-clipped mean | cpu_max | gpu_max |
|---|---|---|---|---|---|
| 128 | 0.2787 | 0.1414 | 0.2785 | 1.138 | 0.414 |
| 512 | 0.2787 | 0.1415 | 0.2786 | 0.822 | 0.339 |
| 2048 | 0.2795 | 0.1408 | 0.2796 | 1.118 | 0.336 |

- **p99 clipping moves the ratio by 0.0002** → fireflies are not the mechanism;
  the deficit lives in the bulk, killing the "just noise/outliers" objection.
- **Median (0.141) is worse than mean (0.279)** → the TYPICAL metal pixel is ~7×
  darker on GPU; a minority of brighter pixels prop the mean up. Prefer the
  median when stating severity.
- **`gpu_max` never approaches `cpu_max`** (0.34–0.41 vs 0.82–1.14) → the GPU
  never reaches the CPU's peak radiance at all. That is a **missing/incorrect
  additive term in the BSDF**, not a sampling or clamping difference.

Stable across a 16× spp range (32→2048) on every estimator — structural, not MC
noise (memory `mc-noise-vs-deterministic`).

**Visual (inspected, per house discipline).** In
`test_results/overnight_report_2026-07-25/contact_sheet_{cpu,wavefront}.png`, the
gold metal sphere (top row, 2nd from left) is bright warm gold on CPU and a
**dark muted olive** on GPU with a dark patch low-centre — unmistakable side by
side. (Incidental: the CPU metal sphere shows coloured firefly speckle the GPU
lacks — consistent with the GPU simply carrying less energy; noted next to
pkg157's clamp port, no established connection.)

Artifacts: `per_material_parity.json`, `metal_robustness_check.json`,
`scene_scan_parity.json`, `contact_sheet_spp_scan.json`,
`contact_sheet_{cpu,wavefront}.png`, `contact_sheet_diff_x10.png` (all under
`test_results/overnight_report_2026-07-25/`).

---

## Convicted mechanism (grounded in code — this is not a hunch)

Plain `metal` shades through `gpu_metal_eval` / `gpu_metal_sample`
(`include/astroray/gpu_materials.h:206` / `:234`; reached via `GMAT_METAL` at
`:1307/:1340/:1364`, and via the closure-graph conductor lobe when
`disneyMetalConductor` is false, `:1185`). The CPU oracle is `MetalPlugin`
(`plugins/materials/metal.cpp`), called natively from `pathTraceSpectral`.

**The rough path (roughness > 0.1) diverges structurally.** The CPU rough eval:

```
// metal.cpp:54-58 (eval) and :85-89 (evalSpectral)
singleScatter = F * D * G / (4*NdotV)
Fms          = ggxMultiScatterCompensation(NdotV, NdotL, roughness)
msWeight     = roughness * (2 - roughness)
multiScatter = albedo * (Fms * msWeight * 1.3f)
return singleScatter + multiScatter
```

The GPU rough eval returns **single-scattering only** — there is NO multiscatter
term:

```
// gpu_materials.h:230
return F * D * G / (4.f * NdotV + 0.001f);   // singleScatter, and that's it
```

For a rough conductor the single-scattering GGX lobe is spread thin and
integrates to well under `albedo` (the classic Kulla–Conty energy loss), so at a
typical (wo, wi) the CPU's near-view-independent `multiScatter` term is the
**dominant** energy contributor while the GPU has none of it. That predicts,
precisely, the observed signature: typical (median) pixels ~7× dark (almost all
their CPU energy is the missing term), highlight pixels less dark (single-scatter
dominates there on both), and `gpu_max` structurally below `cpu_max` (no
multiscatter floor lifting the GPU). The near-delta path (roughness ≤ 0.1) is
byte-identical on both sides (mirror, `s.f = albedo`, `gpu_materials.h:238-245`
vs `metal.cpp:94-99`), so the defect is confined to the rough path — which is
exactly what the contact-sheet's rough gold sphere exercises.

**The pkg141 comment is now falsified for the rough path.** `gpu_materials.h:1156`
asserts `gpu_metal_eval` is "correct for MetalPlugin (its own CPU eval()/sample()
has the identical shortcut, metal.cpp:33,94)". That is true ONLY for the ≤0.1
mirror shortcut; the rough branch is NOT identical — CPU adds multiScatter, GPU
does not. The claim went unchecked because **plain `metal` has no GPU/CPU parity
gate at all** (see §Gate deliverable).

---

## Novelty — filed NEW, not folded into pkg158 (with reasoning, as requested)

I considered folding this into pkg158 Step 0 (its charter is a scene-controlled
metal re-measure) and decided **against**. They are genuinely different defects:

| | pkg152 / pkg158 | **pkg160 (this)** |
|---|---|---|
| GPU function | `gpu_disney_eval` (Disney conductor lobe) | `gpu_metal_eval` (plain MetalPlugin) |
| CPU oracle | Disney plugin | `MetalPlugin` (`metal.cpp`) |
| Defect | reconcile 0.60–0.77 (pkg152 doc) vs ~1.0 (verifier) near-delta; #523 already mirrored compensation INTO Disney | `gpu_metal_eval` **never had** a multiscatter term at all — a categorical omission, not a reconciliation |
| Magnitude | near-delta, band-passing | 3.5× mean / **7× median**, fails even `[0.4, 2.5]` |
| Measured on | `test_pkg123_disney_metal_gpu_cpu_parity.py`, **pre-#524 megakernel** | **wavefront**, post-#524, scene-controlled |

pkg141 fixed *Disney* metal routing; nobody ever audited *plain* metal.
pkg158's Step 0 reconciles two **Disney** numbers — dropping a plain-metal
0.279 into it would make it "reconcile" three numbers from two code paths and
mis-scope the package. Keeping them separate keeps each conviction clean.

**Efficiency, honored without conflation:** pkg160 and pkg158 are both metal
twins and should be **instrumented and HW-verified in ONE GPU-lock session with
the shared pkg141/pkg152 per-event `(f, pdf, throughput)` harness** — run the
plain-metal and Disney-metal dumps back to back. Cross-referenced in both specs;
neither absorbs the other.

---

## Fix contract (measure-first, then mirror the CPU verbatim)

1. **Confirm the term is the whole story.** Per-event `(f, pdf, throughput)` dump,
   CPU `MetalPlugin::evalSpectral` vs `gpu_metal_eval`, for the contact-sheet gold
   sphere config and a roughness sweep {0.1, 0.3, 0.6, 0.9}. Expect the residual
   to be exactly `albedo * Fms * msWeight * 1.3` (metal.cpp:86-88). If a residual
   survives after adding it, dump D/G/F per channel (the olive shift may also
   implicate the Fresnel/F0 spectral path) before adding anything else.
2. **Mirror the CPU multiscatter term into `gpu_metal_eval`** (and thus the
   `s.f` returned by `gpu_metal_sample`) **verbatim** — same
   `ggxMultiScatterCompensation`, same `msWeight = roughness*(2-roughness)`, same
   `1.3f`. Do NOT re-derive; the CPU term is canonical and carries its own
   citation (Kulla & Conty 2017, "Revisiting Physically Based Shading at
   Imageworks" — the GGX multiscatter energy compensation). Confirm
   `ggxMultiScatterCompensation` is available (or portable) to device code;
   provide a `__host__ __device__` form if it is CPU-only.
3. CPU stays canonical (do not touch `metal.cpp`). Verify GPU==CPU per-channel
   within the new tightened band across the roughness sweep, mean AND median.
4. If the convicted term turns out to be the full pkg129 reflection-multiscatter
   LUT scope rather than this closed-form compensation, hand over to pkg129 — do
   not partially duplicate it.

## Gate deliverable — plain `metal` gets a real parity gate (first-class)

The reason a 3.5× defect shipped invisibly is that **plain `metal` has NO
GPU/CPU parity gate** — the only metal parity test (`test_pkg123_disney_metal_
gpu_cpu_parity.py`) is *Disney* metal, and even its band `[0.4, 2.5]` would fail
0.279. This package must, with OWNER SIGN-OFF (never a silent re-pin, cf. pkg156):

- Add a **plain-`metal` GPU/CPU parity gate** on the wavefront over a roughness
  sweep {0.1, 0.3, 0.6, 0.9}, asserting **both mean and median** per-channel
  ratio (the median catches exactly this bulk-of-distribution defect that a
  mean-only gate near a bright highlight could mask).
- Propose a tightened band matching post-fix parity — opening proposal
  **[0.95, 1.05]** per channel; state explicitly it will be RED until the fix
  lands, and land the gate + fix in the same PR so the suite is never
  knowingly-green-on-a-3.5×-error.

## Non-goals

- Not `gpu_disney_eval` / Disney metal (pkg152/pkg158; co-verify, don't merge).
- Not the CPU `MetalPlugin` (canonical; do not touch `metal.cpp`).
- Not pkg129's LUT port (hand over only if the closed-form mirror proves
  insufficient).
- Not perf (pkg155) — but the fix lands in `gpu_materials.h`, included by the
  register-constrained wavefront shade stage; keep the added term's live state
  minimal.

## Provenance

Filed by the architect from the team-lead's scene-controlled GPU scan
(2026-07-26, RTX 5070 Ti, main @ `727a211`, serialized GPU lock), which narrowed
an initial broad whole-scene divergence to a single convicted defect via
per-material patch isolation + a mean/median/p99/max robustness check across
32→2048 spp, plus side-by-side PNG inspection (memory
`general-photon-loop-needs-solid-glass`). Mechanism grounded by architect diff of
`gpu_metal_eval` (`include/astroray/gpu_materials.h:206-231`) against
`MetalPlugin::eval`/`evalSpectral` (`plugins/materials/metal.cpp:32-90`). Fix
mirrors the existing CPU term (Kulla & Conty 2017); CPU stays canonical.

# pkg160 — Plain `metal` is ~3.5× (median ~7×) too dark on the GPU: `gpu_metal_eval` omits the CPU's multiscatter energy term (wavefront-only path)

**Pillar:** 3 (GPU/CPU parity — the only GPU path we now ship)
**Track:** A (RTX-gated; CI is blind — see why nothing caught it)
**Status:** **BLOCKED on a team-lead/owner decision** (2026-07-26) — Step 0 was executed and the two E-table systems **disagree catastrophically** (24.6× in `E`, **1030× in the downstream `Fms`** at the roughness the defect was actually measured at). Per this spec's own "Implementation hazard" instruction, the implementer stopped before choosing between the two fixes. **Landed:** Step-0 instrumentation, the pin test, the corrected `gpu_materials.h:230` comment. **NOT landed:** the mirror itself and the plain-metal parity gate (the spec requires them in one PR). See "Step 0 RESULT" at the end of this file. Original conviction (team-lead scene-controlled GPU scan, main @ `727a211`) stands and is unchallenged.
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

---

## Implementation hazard — WHICH E table? (team-lead, verified 2026-07-26)

The mirror is not quite a copy-paste, because **there are two independent GGX
energy-compensation table systems in this repo and the CPU metal path uses the
one the GPU does not have.**

1. **`GGXEnergyCompensationLUT`** — `include/raytracer.h:340-379`. Computed at
   runtime by MC integration in its constructor. Stored `E[r * RES + m]`
   (roughness major, mu minor) and read by `lookupE(mu, roughness)`, which sets
   `x = mu`, `y = roughness`. Internally consistent. **This is what the CPU
   `ggxMultiScatterCompensation` — and therefore `MetalPlugin::eval` — actually
   uses.**
2. **`DisneyEnergyCompensationTables`** — `include/astroray/energy_compensation.h`
   + `src/energy_compensation.cpp`, loaded from `data/disney_compensation/*.bin`
   (present and git-tracked; `ggx_E.bin` is 4096 B = 32×32 float32). Read by
   `sample2D(table, size, roughness, mu)`, which sets `x = roughness`, `y = mu`
   — **the opposite index convention to (1)**, and internally consistent with how
   the `.bin` is stored. **This is the only one uploaded to the GPU**
   (`src/gpu/gpu_ggx_tables.cu:67` → `g_ggxE`), and `gpu_ggx_sample2D`
   (`include/astroray/gpu_ggx_tables.cuh:54`) mirrors `sample2D`'s convention
   exactly. Verified line by line — **there is no transposition bug here**; the
   two conventions belong to two different tables, each self-consistent.

So the implementer must not blindly write `gpu_ggxE(roughness, NdotV)` in place
of `lut.lookupE(NdotV, roughness)` and assume parity. The index conventions are
mirror images *and* the underlying data has different provenance (runtime MC vs
shipped `.bin`).

**Required first step, before writing the mirror:** dump both tables over the
same (roughness, mu) grid and compare. Two outcomes:

- **They agree numerically** → mirror using `gpu_ggxE`/`gpu_ggxEavg` with the
  argument order the GPU helper expects, and add an assertion/test pinning the
  agreement so it cannot silently drift.
- **They disagree** → say so and stop before choosing. Making the GPU match the
  CPU's *runtime* LUT and making it match the *shipped* tables are different
  fixes with different blast radius, and picking one silently would bury a
  second discrepancy under this one. Escalate for a decision.

Also note `gpu_ggxCompensationFactor` / `gpu_ggxDirectionalAlbedo`
(`gpu_ggx_tables.cuh:119/134`) already exist and both early-out to identity when
`g_ggxE`/`g_ggxEavg` are null. Whatever helper you add must have the same
null-table guard — but choose its fallback deliberately: returning identity
(1.0) is right for a *multiplicative* compensation factor, whereas this metal
term is **additive**, so its correct no-table fallback is **0.0** (i.e. degrade
to today's single-scatter-only behaviour), not 1.0. Getting that backwards would
add a full-strength albedo term whenever the tables fail to load.

### Sub-question already resolved (team-lead, 2026-07-26)

The shipped tables **do** load with real data on this machine, so the fix will have
populated tables to work with and the null-table path is not the common case:

- `astroray_test_helpers.disney_compensation_tables_loaded()` → `True`
- `data/disney_compensation/ggx_E.bin` — 1024 float32 = 32×32, range `[0.3069, 1.0000]`,
  mean `0.8298`; **not** the all-ones unloaded fallback
- `data/disney_compensation/ggx_Eavg.bin` — 32 float32, range `[0.4091, 1.0000]`

What remains open is the comparison against `raytracer.h`'s *runtime-computed*
`GGXEnergyCompensationLUT` — the table the CPU metal path actually uses. That one is not
reachable from Python today (`astroray_test_helpers` exposes only
`disney_ggx_glass_e`/`disney_ggx_glass_eavg`, i.e. the glass tables). Dumping it needs a
small addition to the test-helpers module, which is the natural first commit of this
package. Note that a new *public* binding needs owner approval, but a `test_helpers`
addition does not — that module exists precisely for internal introspection like this.

---

## Step 0 RESULT (implementer, 2026-07-26, main @ `3800759`) — THEY DISAGREE. STOPPED.

**Method.** Both table systems were compiled from the *real repo code* (no
transcription) with MinGW `g++ -O2 -static`, linking `src/energy_compensation.cpp` and
including `raytracer.h`, and dumped over a common grid. The shipped-table side was then
independently re-derived in NumPy straight from `data/disney_compensation/ggx_E.bin`;
the two agree to 5e-7, so the numbers below are not a lookup-convention mistake.
`disney_compensation_tables_loaded() == True` (not the all-ones fallback).

**`E` at mu = 0.5.** `runtime` = `lut.lookupE(0.5, r)`; `shipped` = `tab.ggxE(r, 0.5)`:

| roughness | runtime LUT `E` | shipped `ggx_E.bin` | shipped/runtime |
|---|---|---|---|
| 0.05 | 0.001399 | 0.999975 | **715×** |
| **0.15** (contact-sheet metal) | **0.040669** | **0.998543** | **24.6×** |
| 0.30 | 0.353788 | 0.974699 | 2.76× |
| 0.60 | 0.549046 | 0.782171 | 1.42× |
| 0.90 | 0.457155 | 0.535442 | 1.17× |

**Downstream `Fms` (what the metal term actually multiplies), NdotV = NdotL = 0.5:**

| roughness | `Fms` runtime (= CPU) | `Fms` from shipped tables | runtime/shipped |
|---|---|---|---|
| **0.15** | **0.307206** | **2.98e-4** | **1030×** |
| 0.90 | 0.168839 | 0.138047 | 1.22× |

**Consequence — Option B is dead.** Cosine-weighted-hemisphere integration of the full
green-channel eval at the contact-sheet metal config (albedo `[0.92,0.78,0.35]`,
roughness 0.15) gives a GPU/CPU single-bounce eval ratio of **0.0291 today** and
**0.0328** if `gpu_metal_eval` were mirrored using `gpu_ggxE`. Writing
`gpu_ggxE(roughness, mu)` in place of `lut.lookupE(mu, roughness)` **closes ~1% of the
gap** at the roughness the defect was measured at, and cannot reach the spec's proposed
`[0.95, 1.05]` band. It only converges near roughness 0.9 (0.26 → 0.98).

**Root cause of the divergence, and an uncomfortable finding the decision must weigh.**
`GGXEnergyCompensationLUT`'s constructor estimates `E` with 256 *uniform-hemisphere*
samples per cell (`raytracer.h:306-331`). That cannot resolve a narrow GGX lobe, so
`E → 0` as roughness → 0 — the opposite of the truth (a smooth conductor's directional
albedo → 1, which is what the converged Cycles table correctly reports). Because
`Fms = (1-Ewo)(1-Ewi) / (π·max(1-Eavg, 1e-4))`, `E → 0` drives `Fms → 1/π = 0.3183`, its
**maximum**, exactly where multiple scattering should vanish. Measured `Fms` at
roughness 0.15 is 0.3072 = **96.5% of the ceiling**.

So at roughness 0.15 the CPU is adding `albedo × 0.3072 × 0.2775 × 1.3 = 0.111 × albedo`
— a large, nearly view-independent, **cosine-free** ambient floor (note it carries no
`NdotL`, unlike everything else `eval()` returns per `AGENTS.md`). That floor is the
bulk of the CPU's metal radiance at this roughness, which is exactly why the median
GPU/CPU ratio is 0.141 rather than something near 1.

**This does not overturn the package's conviction** — `gpu_metal_eval` really does omit a
term `MetalPlugin` really does add, and the two really are 3.5×/7× apart. It changes
*which side is physically wrong at low roughness*: at roughness 0.15 the GPU's
single-scatter-only answer is closer to physically correct, and the CPU is bright because
of a table artifact. "Mirror the CPU verbatim" therefore means **canonicalising a bug for
the sake of parity**. That may still be the right call (parity now, correctness via
pkg129 later) but it must be made knowingly, and it is not the implementer's call.

**The two fixes, with blast radius:**

- **Option A — upload the runtime LUT to the GPU (exact parity by construction).**
  Add a second, separate pair of device globals mirroring `GGXEnergyCompensationLUT.E/Eavg`
  and a `gpu_ggxMultiScatterCompensation` that reproduces `raytracer.h:372-379` with the
  CPU's `(mu, roughness)` index convention. Does **not** touch `g_ggxE`, so pkg152/#523's
  Disney compensation is untouched. **But it needs files outside the assigned scope:**
  `include/astroray/gpu_ggx_tables.cuh` and `src/gpu/gpu_ggx_tables.cu` (the upload can
  be folded into the existing `uploadGgxTables()` body, so the call sites in
  `src/gpu/wavefront/gpu_wavefront_snapshot.cu:1489,1779` need **no** edit — important,
  that file is another implementer's tonight). `gpu_ggx_tables.cu` would need to reach
  `raytracer.h`'s LUT; five `.cu` files already include `raytracer.h`
  (`cuda_renderer.cu`, `scene_upload.cu`, `tlas_parity.cu`, `pkg64_sms_probe.cu`,
  `gpu_wavefront_snapshot.cu`) so it is feasible, but it is a new heavyweight include in
  a currently-light `.cu`, **and the implementer cannot build CUDA to verify it.**
- **Option B — mirror using the existing `gpu_ggxE`.** Zero new plumbing, stays inside
  `gpu_materials.h`, physically more defensible. **Measured to close ~1% of the gap at
  roughness 0.15 and fail the spec's own acceptance band.** Not a fix.
- (Option C — fix the runtime LUT itself — is `metal.cpp`/`raytracer.h` territory, i.e.
  explicitly a non-goal here and arguably pkg129's.)

**Why the existing "metal parity" test never saw this.**
`tests/wavefront_diff/test_cpu_wavefront_metal_bit_identity.py` compares the **CPU
wavefront** against the **CPU reference path tracer** — both call `MetalPlugin`, so it is
bit-identical *by construction* and structurally blind to `gpu_metal_eval`. The gate this
package still owes must be **GPU wavefront vs CPU**, and must sweep roughness on both
sides of the 0.1 threshold: sampling only 0.9 would have shown the tables "agreeing".

# Reflection multiscatter energy compensation — heritage supersession note (pkg129)

**Scope:** GGX **metal reflection** multiscatter energy compensation. Records the
table lineage, establishes that the table DATA in the repo is already Cycles'
own, isolates what actually remains open (the compensation *application form*),
and leaves a marked placeholder for the live-Cycles A/B verdict.

Filed by pkg129 (narrowed, 2026-08-02 architect refresh). The original pkg129
body ("port `adobe/openpbr-bsdf` Turquin LUTs to converge on Cycles") is a
CONVICTION-PATH plan only — see "What the A/B decides" below.

---

## 1. Why this note supersedes the original pkg129 port premise

The original spec (2026-07-19) assumed the repo needed to *acquire* Cycles-grade
multiscatter tables by porting `adobe/openpbr-bsdf`'s LUTs. That premise is stale
on main: **the repo already loads Cycles' own tables.**

- `include/astroray/energy_compensation.h:29` loads `table_ggx_E` /
  `table_ggx_Eavg` — the GGX directional / cosine-averaged energy tables from
  Cycles `intern/cycles/scene/shader.tables` — i.e. the exact post-#107958
  production data the original spec wanted to converge on. The header comment
  (`:14`) names the reference form as Cycles' `microfacet_ggx_preserve_energy`.

Porting `adobe/openpbr-bsdf`'s LUTs now would **add** a heritage, not remove one
— the opposite of this package's single-source-of-truth goal. So the table-DATA
question is closed; what remains is purely the **application form**.

---

## 2. Table + compensation lineage (metal reflection)

| Stage | PR / pkg | What it did | Heritage |
|-------|----------|-------------|----------|
| pkg60 | (CPU) | Added Kulla & Conty reflection compensation on CPU (`disney.cpp` `ggxCompensationFactor`), off the `ggxE` LUT. Non-goal: "do not port to GPU". | K&C 2017 layering over the pkg60 `ggxE` table |
| #523 | GPU mirror | Mirrored the CPU compensation term onto the GPU metal shade path. | same term, device side |
| pkg160 (#527) | CPU+GPU | Deleted the invented additive `roughness·(2-roughness)·1.3` hack from the live path; routed plain metal through the SAME Kulla & Conty compensation `disney.cpp` ships, with an exact GPU twin. | K&C over Cycles `table_ggx_E`/`Eavg` |
| pkg163 (#533) | GPU per-λ | Made the GPU leg per-wavelength (`gpu_metal_eval_spectral`), retiring the r=0.9 band exception and closing the RGB-vs-per-wavelength colour-space seam. | same table, per-λ application |

Current live state on main (grep-verified, refresh `7be3245`):

- **CPU:** `disney.cpp` applies **Kulla & Conty 2017 Eq. 6-9 layering** over the
  Cycles tables (`disney.cpp:609`, `:659-663`, via `ggxCompensationFactor`
  `:97`). This is a working, physically-based term.
- **GPU:** the pkg160/pkg163 twin — the same tables, per-wavelength — replacing
  the old placeholder-returns-0 + `1.3f` hack. The `1.3f` hack survives only in
  explanatory comments (`metal.cpp:92-98`); `stage_shade_metal.cu` is dead code
  (no call site; pkg160 audit note at `stage_shade_metal.cu:120`). Its deletion
  is a standing owner call, not pkg129's scope.

**Both backends now consume the same Cycles table data.** The only remaining
distinction is HOW that data is applied.

---

## 3. The residual open question — application form (what the A/B tests)

Two application forms exist over the identical `table_ggx_E`/`Eavg` data:

- **In-repo:** Kulla & Conty 2017 Eq. 6-9 **layering** of a second energy lobe
  (`ggxCompensationFactor`).
- **Cycles (post-#107958):** **Turquin-style albedo scaling** of the
  single-scatter lobe (`energy_scale` applied in-kernel; `darkening` on the
  closure) — commit `888bdc1`, on the rationale that "having the exact correct
  directional distribution is not that important as long as the overall albedo is
  correct."

These agree to first order (both drive directional albedo toward unity) but can
differ at high roughness. The **live-Cycles rough-metal A/B** (this package's
harness, `benchmarks/cycles-parity/metal_ab/`) is the strongest external check:
same Blender scene, three legs (Cycles oracle / Astroray CPU / Astroray GPU),
image-plane linear radiance parity with a both-bounds per-channel ratio band
(pkg166 rules). Because the table data is now shared, a residual divergence — if
any — is attributable to the application form and to nothing else.

---

## 4. What the A/B decides (conviction clause)

- **If the A/B shows parity within band** across the sweep: the K&C layering form
  is confirmed equivalent-in-furnace to Cycles' Turquin scaling for metals; the
  openpbr LUT port does **not** fire, and pkg129 closes on the harness + this
  note.
- **If the A/B shows a real, scene-controlled, direction-consistent divergence
  attributable to the application form:** the original Fix plan (openpbr LUT port
  / switch CPU+GPU to Turquin albedo scaling) becomes a follow-up sizing **with
  architect sign-off** — not a silent expansion of pkg129.

---

## 5. A/B verdict — RUN 2026-08-08 (lead HW lane, RTX 5070 Ti + Blender 5.1)

> **STATUS: A/B CLEAN — no divergence convicted. Conviction-path LUT port does NOT fire.**
>
> Run: `--res 64 --samples 128`, ShaderNodeBsdfPrincipled Metallic=1 (→ Astroray
> Disney metal path), r ∈ {0.3,0.6,0.9} × {chromatic, neutral}, CPU + GPU.
> **All 12 legs PASS the [0.85,1.15] per-channel ratio band.** Table:
>
> | r | albedo | CPU R/G/B | GPU R/G/B |
> |---|--------|-----------|-----------|
> | 0.3 | chromatic | 1.016/0.958/0.944 | 1.018/0.960/0.946 |
> | 0.6 | chromatic | 1.011/0.940/0.927 | 1.017/0.947/0.934 |
> | 0.9 | chromatic | 0.987/0.902/0.892 | 0.991/0.908/0.895 |
> | 0.3 | neutral | 0.997/0.999/0.980 | 0.998/0.999/0.980 |
> | 0.6 | neutral | 0.977/0.978/0.958 | 0.985/0.987/0.968 |
> | 0.9 | neutral | 0.936/0.939/0.923 | 0.946/0.948/0.930 |
>
> Findings:
> 1. **No application-form divergence.** Both engines consume the same Cycles
>    tables and land within band at every roughness; the K&C-layering-vs-Turquin
>    application-form question raises no measurable, scene-controlled divergence.
>    The conviction-path openpbr LUT port does NOT fire.
> 2. **GPU ≈ CPU** (GPU marginally *brighter*, not dimmer, ≤~1%). This
>    **contradicts pkg165's "uniform ~5–8% GPU-dim" premise** (measured on old
>    SHA `b036ac93`); it does not reproduce on current main — likely resolved by
>    pkg170 (opaque-Disney 2× gain) + intervening fixes. pkg165 → verify-and-close.
> 3. **Mild roughness-dependent dim vs Cycles** (neutral ~1.0 at r0.3 → ~0.93 at
>    r0.9), consistent with the known systemic parity-band offset, not a metal-
>    specific defect. GPU SSIM is low (independent-RNG MC noise, the ratio gate
>    is the correct statistic — see [[ssim-wrong-gate-for-independent-rng]]).
>
> (Original invocation note preserved below for reproducibility.)
>
> The A/B requires headless Cycles (Blender 5.1) + a built OpenMP-OFF Astroray
> addon + the RTX box; the package-implementer cannot render (no vcvars / GPU is
> the lead's HW lane). The implementer built and unit-tested the harness only.
>
> Invoke:
> ```
> python benchmarks/cycles-parity/metal_ab/harness.py \
>     --out test_results/pkg129_metal_ab --res 128 --samples 256
> ```
> Then paste the per-channel ratio / SSIM / dE table (or point at
> `test_results/pkg129_metal_ab/metal_ab_report.md`) here and record the verdict
> (parity within band → close; divergence → conviction-path sizing).
>
> _(verdict recorded above, 2026-08-08: A/B CLEAN — no divergence; pkg129 closes on the harness + this note; pkg165 → verify-and-close.)_

---

## 6. Citations (CLAUDE.md §6)

- **Kulla & Conty 2017**, "Revisiting Physically Based Shading at Imageworks" —
  the in-repo CPU+GPU compensation layering (`disney.cpp:60`, `:609`).
- **Turquin 2019**, "Practical multiple scattering compensation for microfacet
  models" (blog.selfshadow.com/publications/turquin/ms_comp_final.pdf) — the
  albedo-scaling form Cycles adopted.
- **Blender/Cycles PR #107958, commit `888bdc1`** — replaced Heitz-2016
  stochastic multiscatter GGX with Turquin albedo scaling; generator
  `intern/cycles/app/cycles_precompute.cpp`, tables
  `intern/cycles/scene/shader.tables` (Apache-2.0). This is the exact data
  `energy_compensation.h` loads.
- **`adobe/openpbr-bsdf` (Apache-2.0)** — the conviction-path LUT + CUDA-backend
  source, to be used ONLY if the A/B convicts the application form.

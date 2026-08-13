# pkg189 — GPU wavefront dispersion enablement (hero-λ refraction is a no-op end-to-end)

**Pillar:** 3/5 (spectral light transport / CPU-GPU parity)
**Track:** A
**Status:** done (PR #603, 2026-08-13 — GPU wavefront hero-λ dispersion now LIVE
for both material families: GPU dielectric BK7 disp/flat **0.5508** and Principled
disp/flat **0.5507** (were ~1.00 no-op), matching the CPU reference ~0.55; CPU/GPU
per-channel mean-ratio within 4% (dielectric [1.038, 0.982, 0.972], Principled
[1.038, 0.983, 0.979]); **visually-confirmed spectral rainbow** on a closed glass
sphere (full ROYGBIV ring for Principled). Register gate: the `HasDispersion` 4th
axis adds **zero** REG/STACK — fleet kernel `<0,0,0,0>` REG:254 STACK:3352, and
`<*,*,*,0>`≡`<*,*,*,1>` byte-identical across all 8 base specializations
(cuobjdump, native sm_120). Work item 3 finding: the flat-prism dispersive
*photon* caustic is unchanged (still sparse noise) — a separate 2-face-GPU-photon
follow-up, orthogonal to this wavefront fix.)

**Status (original):** open (found 2026-08-12 during pkg187 Principled-dispersion
implementation; the implementer empirically established that GPU wavefront
hero-wavelength dispersion is a **no-op for ALL materials** — a pre-existing
frozen gap, not a pkg187 defect).
**Estimated effort:** L
**Depends on:** pkg64 (GPU Sellmeier/hero-λ upload, PR #354 — scene-upload side
is correct); pkg187 (Principled per-λ IOR wired into
`gpu_material_sample_spectral`); pkg55 (wavefront SoA integrator); pkg113/#589
(GPU photon-caustic pre-pass).

---

## Symptom

Dispersive refraction is **silently achromatic on the GPU wavefront path for
every material**. The scene-upload side works; the wavefront integrator never
acts on it.

Evidence measured on RTX 5070 Ti (2026-08-12, during pkg187):

- **Dielectric BK7 prism, GPU wavefront:** renders **identically to flat-IOR
  glass** — mean **0.2131 flat vs 0.2139 BK7**; chromatic spread unchanged.
- **CPU dispersion works** for both material families on the same scenes:
  dielectric **0.2144 → 0.1183**, Principled **0.2053 → 0.1138** (dispersion
  on vs off produces a real, large delta).
- The only end-to-end GPU dispersion test, `test_pkg64_gpu_cpu_parity`, has
  been **xfail since 2026-06-08** ("SMS-GPU is frozen";
  `tests/test_pkg64_gpu_cpu_parity.py:179-181`).
- `test_gpu_prism_rainbow_parity`'s recent **XPASS is vacuous** (0.80s, no
  render output produced). **Do NOT treat it as evidence of working GPU
  dispersion** — it is a green light on an empty scene.

Net: pkg64 Session-2 explicitly deferred "GPU per-wavelength multi-IOR
refraction" to an increment that **never ran** on the canonical (wavefront /
photon) path; pkg187 correctly wired Principled per-λ IOR into
`gpu_material_sample_spectral` mirroring dielectric — but the **wavefront
integrator's hero-λ collapse / per-λ IOR refraction never takes effect end to
end**, so both material families collapse to flat IOR on GPU.

## What is and isn't already in place

- **Upload side is correct (do not re-do):** `src/gpu/scene_upload.cu`
  (pkg64 / PR #354) uploads the Sellmeier/Cauchy coefficients + `isDispersive`
  flag correctly for dielectric, and pkg187 extends this to Principled.
- **Sampler side is wired (do not re-do):** pkg187 wires Principled per-λ IOR
  into `gpu_material_sample_spectral` mirroring the dielectric path.
- **Missing piece:** the **wavefront integrator** step
  (`stageAdvance` / `stageShadeBucketed`) does not collapse to a hero
  wavelength on a dispersive refraction event and does not thread the sampled
  hero-λ into the per-λ IOR lookup — so the correct per-λ IOR is computed
  against a fixed (achromatic) λ and the ray refracts as if flat.
- **Photon-caustic caster gap:** the pkg113 photon-caustic path is
  **dielectric-oriented** and may not accept closure-graph / Principled
  casters (see pkg113 / #589) — so even once wavefront refraction is
  chromatic, Principled-glass caustics may still be achromatic through the
  photon map.

---

## Frozen-path constraint — read before choosing an approach

`test_pkg64_gpu_cpu_parity` targets the **SMS-GPU** path, which the owner
**deliberately froze** (2026-05-30: "the photon map is the canonical caustic
path on CPU+GPU"; `pkg64-gpu-spectral-caustics.md:5,38` — "Do NOT add further
SMS-GPU surface area"). Therefore:

- **Do not revive or extend SMS-GPU** to close this. The enablement must land
  on the **canonical** surfaces: the wavefront integrator (primary/secondary
  refraction) and the **photon-caustic** pre-pass.
- Converting `test_pkg64_gpu_cpu_parity` from xfail to a real gate (Work item
  2) most likely means **re-targeting the test** at the wavefront/photon path
  rather than un-freezing SMS-GPU. If the test cannot be re-pointed without
  touching frozen SMS-GPU surface area, escalate to the owner rather than
  reopening SMS-GPU.

## Register-pressure constraint — read before touching the shade kernels

`stageAdvance` / `stageShadeBucketed` are **pinned at REG:254**
([[wavefront-shade-kernels-register-saturated]]); any per-hit live state
spills ~2KB and tanks perf. Adding per-λ IOR / hero-λ state to the wavefront
path **must not add spill to the non-dispersive (and non-principled)
specializations**. Follow the [[closure-graph-lobe-count-spills-fused-kernel]]
pattern: isolate the dispersive branch under a compile-time specialization
(`template<bool HasDispersion>` / if-constexpr) so the flat-IOR fast path
carries zero extra live state. Verify with cuobjdump post-link + ASTRORAY_PROFILE
(NOT `ptxas -v`), and A/B the non-dispersive perf before/after.

---

## Work

1. **Make hero-λ dispersive refraction live on the wavefront path** for
   dielectric **and** Principled (closure-graph) materials: on a dispersive
   refraction event, collapse the ray to a sampled hero wavelength and thread
   that λ into the per-λ IOR lookup (`gpu_material_sample_spectral` already
   computes per-λ IOR once given a λ). Guard behind a compile-time
   specialization so the flat-IOR path is bit-unchanged and spill-free.
2. **Convert `test_pkg64_gpu_cpu_parity` from xfail to a real gate** — re-point
   it at the canonical wavefront/photon path (NOT frozen SMS-GPU; see the
   frozen-path constraint) and remove the xfail marker; verify with
   `--runxfail` ([[xfail-gated-features-must-unxfail]]). **Make
   `test_gpu_prism_rainbow_parity` a genuine render-level check** — its current
   XPASS is vacuous (no render output); it must actually render and assert on
   pixels.
3. **Evaluate whether the photon-caustic path needs closure-graph caster
   support** for chromatic caustics (pkg113 / #589 is dielectric-oriented). If
   Principled/closure-graph glass casters are silently dropped or refracted
   achromatically by the photon pre-pass, either extend caster gathering to
   accept them per-λ or record the finding and scope a follow-up — decide based
   on measurement, do not assume.
4. Re-run the dispersion + caustic family gates
   (pkg29a/64/106/109/110/111/113, pkg187) after the fix; A/B the
   non-dispersive wavefront perf to confirm no regression.

## Acceptance oracle

Metrics pass on garbage ([[general-photon-loop-needs-solid-glass]]) — **require
LOOKING at the render**, not just numbers.

- [ ] A dielectric BK7 prism on the GPU wavefront path produces a **chromatic**
      result distinct from flat-IOR glass (the 0.2131-vs-0.2139 collapse is
      broken) — measurable chromatic spread, **visually confirmed rainbow**.
- [ ] A Principled (closure-graph) glass prism with nonzero dispersion produces
      **chromatic** GPU output — visually confirmed rainbow, not just a hue
      metric.
- [ ] **CPU/GPU chromatic parity** on both prisms via **per-channel
      mean-ratio** (NOT SSIM — independent MC streams;
      [[ssim-wrong-gate-for-independent-rng]]).
- [ ] `test_pkg64_gpu_cpu_parity` is a **real gate** (xfail removed, passes
      under `--runxfail`) on the canonical path; `test_gpu_prism_rainbow_parity`
      renders and asserts on actual pixels (no more 0.80s vacuous XPASS).
- [ ] Zero-dispersion / flat-IOR wavefront output is **bit-unchanged** and
      **no perf regression** on the non-dispersive specialization
      (cuobjdump + ASTRORAY_PROFILE A/B).

## Hard non-goals

- **No new dispersion model** — the Sellmeier/Cauchy machinery and Abbe mapping
  (pkg64, pkg187) already exist; this is enablement of the existing per-λ IOR
  on the GPU wavefront/photon path, not a new spectral model.
- **No SMS-GPU revival** — owner froze it (2026-05-30); the photon map is
  canonical. Do not add SMS-GPU surface area.
- **No spill on the flat-IOR fast path** — the dispersive branch must be a
  compile-time specialization; non-dispersive REG:254 kernels stay pinned and
  bit-unchanged.

---

## Implementation notes (PR #603, 2026-08-13)

**Root cause (one bug, both material families).** The GPU wavefront `shadePathSlot`
reconstructs `lambdas` as a **stack local** from the per-path SoA each bounce. The
dispersive sampler (`gpu_material_sample_spectral`) already computed the hero IOR
against `wl.lambda[0]` and called `wl.terminateSecondary()` on a refraction event
(zeroing the secondary pdfs) — but the shade kernel's SoA write-back never persisted
the mutated `lambda[]`/`pdf[]`. So the collapse evaporated the instant the bounce
returned: the next bounce re-read the un-collapsed pdfs and `stageRegenKernel`'s
`spectrumToXYZ` (which skips `pdf==0`) still summed all four wavelengths — every
dispersive path deposited a broadband spectrum at a hero-bent location, washing out
to flat-IOR glass. The CPU wavefront mirror (`advance_one_bounce`) never had this bug
because its `ps.lambdas` is a member of the persistent `PathState`. Confirmed for BOTH
the Sellmeier dielectric (`GMAT_DIELECTRIC`, `gpu_dielectric_sample_spectral`) and the
Cauchy Principled glass (`GMAT_CLOSURE_GRAPH`, `gpu_principled_sample`).

**Fix.** `shadePathSlot` now writes the (collapsed) `lambdas.lambda[]`/`pdf[]` back to
SoA after the BSDF sample, gated by a new compile-time `HasDispersion` (4th) template
axis; selected off a host-side `SceneUploadResult.hasDispersive` flag (any uploaded
material `isDispersive`). A **4th axis** (not hung off `HasPrincipled`) is required
because the dielectric-dispersive path runs with `HasPrincipled=false` — a plain
Sellmeier dielectric returns an empty closure graph and uploads as `GMAT_DIELECTRIC`,
never setting the principled flag.

**Register gate (cuobjdump, native sm_120, post-link `.pyd`).** The write-back is 8
stores of already-live values; it adds **zero** REG/STACK even when compiled in:
`<*,*,*,0>` ≡ `<*,*,*,1>` byte-identical for all 8 base specializations. Fleet kernel
`stageShadeBucketedKernel<false,false,false,false>` = REG:254 STACK:3352 (matches the
documented pre-pkg189 `<F,F,F>` baseline). Non-dispersive scenes launch `<*,*,*,0>`,
so their output is bit-unchanged and perf cannot regress.

**Work item 2 (test conversions).** `test_pkg64_gpu_cpu_parity`: xfail removed,
re-pointed to a real per-channel mean-ratio + ROI-energy parity gate on the canonical
wavefront path (no SMS-GPU surface touched; the caustic-caster flags are harmless
public-API settings on the wavefront route). `test_gpu_prism_rainbow_parity`: hardened
with a bright-coverage floor so it is a **genuine** render-level check that honestly
XFAILS on the flat-prism photon noise (~0.009% bright coverage) instead of vacuously
XPASSing — see Work item 3. New `test_pkg189_gpu_wavefront_dispersion.py` is the
primary oracle (control-flip + CPU/GPU parity + visual rainbow). The pre-existing
`test_pkg187_...gpu_parity::test_gpu_dispersion_wired_mirrors_dielectric_reference`
asserted the no-op (`0.95 ≤ disp/flat ≤ 1.05`); it was flipped to assert the now-live
behavior (its own docstring predicted "enabling it lights up BOTH... through this same
wiring").

**Work item 3 (photon-caustic evaluation — measured).** The flat-prism dispersive
**photon** caustic is a forward-transport phenomenon on the pkg113 photon pre-pass,
which is dielectric-oriented and uses only the general BVH loop; a flat 2-quad caster
scatters into sparse chromatic noise (measured: ~0.009% bright coverage, no caustic
band). pkg189's wavefront fix is **orthogonal** — it enables the camera/closed-solid
REFRACTION path (verified by a real spectral rainbow on a glass sphere in
`test_pkg189`), not the forward photon caustic. Extending the photon pre-pass to a
2-face flat-prism (or closure-graph Principled) caster is the pre-existing follow-up
(`general-photon-loop-needs-solid-glass`); per the Non-goals this PR does not touch
the photon path. Recorded for a follow-up spec, not addressed here.

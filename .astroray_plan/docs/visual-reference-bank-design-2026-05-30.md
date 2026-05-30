# Visual Reference Bank — consensus design + owner feedback (2026-05-30)

**Context:** pkg104 ("Visual Reference Bank + Perceptual Gates") asked the owner to
pick the scene set. The owner delegated the design back to Claude ("come to a
consensus on what to put in there and how to parameterize it") and gave specific
feedback on the *current* reference renders. This doc is that consensus + the
captured feedback. It supersedes pkg104's "Open question to owner" section.

The bank already physically exists at `benchmarks/reference_bank/scenes/` (12
scenes) + the metrics in `benchmarks/reference_bank/metrics/`. This is a **refine +
re-parameterize + fix**, not a from-scratch design.

---

## Design principle (from the owner's feedback)

Every reference scene must be **detail-rich, high-contrast, and well-composed** so
that (1) a small regression actually moves the gate (the owner's BH critique: "the
black hole ones don't show a lot of detail and so small changes might get lost"),
and (2) the render is showcase-quality. A flat, low-detail, or badly-framed scene
is a bad reference twice over — it hides regressions *and* looks bad. So the bank
optimizes for **catchability + composition**, and each scene pairs an SSIM gate
(sensitive structural check) with a domain metric (hue_spread, concentration,
dark_disk, ΔE…).

---

## Scene set + parameterization (consensus)

Organized by what each scene **gates**. "Gate ref" = owner-blessed Astroray PNG/EXR
on a known-good commit (self-reference), except the one cross-engine Cycles scene.

| # | Scene | Gates | Reference | Parameterization notes |
|---|---|---|---|---|
| 1 | `cornell-mini` | path-tracer GI / soft shadow / color bleed (no-regression floor) | Astroray self | bump to ≥512² @ ≥1024 spp ref; add one glossy + a small caustic element so it exercises more than diffuse GI; SSIM ≥ ~0.97 |
| 2 | `prism-bk7-collimated` + `prism-sf11-collimated` | spectral dispersion (rainbow) | Astroray self | **via the pkg110 forward light-tracer** (not SMS); zoom the camera onto the band; SF11 = wider spread (distinguisher); gates: hue_spread + bright_coverage (exist) + SSIM. **REDO** (see fixes). |
| 3 | `glass-sphere-caustic` (pkg110) | refractive focusing caustic | Astroray self | **canonical** refractive caustic (photon map). LIFT the sphere off the floor + reposition light + zoom (see fixes). Gate: concentration (peak/median) + SSIM. Retire/legacy the old SMS `sms-refractive-glass-sphere`. |
| 4 | `sms-reflective-metal-sphere` (coffee-cup) | reflective caustic crescent | Astroray self | **STAYS on SMS** (the forward photon map doesn't do reflective casters yet — see §"caustic-path alignment"). SMOOTH-shade the cylinder + camera looking down the axis + light farther away (see fixes). Gate: SSIM + bright-crescent presence. |
| 5 | `disney-sweep-cycles-compared` (+ a material contact sheet) | material/BSDF parity vs Cycles | **Cycles** EXR (`cycles_bless.py`) | better lighting + composition; **BLOCKED on the FOV-mismatch bug** (§below) — fix before trusting SSIM ≥ 0.85. |
| 6 | `gr-schwarzschild` + `gr-kerr-94-faceon` | GR lensing / shadow / photon ring | Astroray self | **add a structured background** (checkered grid or starfield) so lensing + the photon ring + shadow edge are crisp and high-contrast; higher res so the shadow edge is sharp; gates: dark_disk (shadow) + SSIM + (optional) photon-ring-radius. **Detail fix — see below.** |
| 7 | `adaf-sgrA-faceon` + `synchrotron-jet-m87` (hero) | GR + emission (ADAF glow, jet) | Astroray self | the jet is the headline hero; keep detail-rich; gates: SSIM + emission-structure/dark-disk. |

**Parameterization knobs (uniform policy):**
- **Resolution:** heroes (jet, prism) ≥ 1280×720; gate scenes ≥ 512² (the current
  384×256 is too small — it's why the denoise/OIDN tile looked low-res). Reference
  is pinned at the chosen res; CI may render a smaller proxy only if the SSIM gate
  is re-tuned for it.
- **SPP:** reference pinned at a clean spp (≥1024, heroes higher). The gate render
  uses a fixed seed so the comparison is deterministic; threshold accounts for the
  residual MC noise.
- **Gate file:** each scene's `gates.toml` declares its SSIM threshold + domain
  metric. SSIM must be tight enough (on a high-contrast scene) that a subtle
  regression registers — pair with a structural metric (phash / edge) where SSIM
  alone is too forgiving (the BH "small changes get lost" risk).
- **Provenance:** deliberate owner re-bless per scene on a known-good commit; never
  auto-bless. Cross-engine (Cycles) reference only for scene 5.

---

## Owner feedback on the current renders → fixes (actionable)

1. **Black holes lack detail (scenes 6/7).** `gr-schwarzschild`, `gr-kerr-94-faceon`:
   the frame is too uniform, so small changes are lost. **Fix:** add a high-contrast
   structured background (checkerboard / starfield / textured accretion disk) so the
   lensed image has fine structure; raise resolution; tighten the gate with a
   structural metric. The shadow edge + photon ring should be crisp.
2. **Reflective caustic is a mess (scene 4).** `sms-reflective-metal-sphere`: the
   cup is a 32-segment triangulated cylinder with **flat (per-face) normals** — it
   reads as jagged, "not a proper cylinder" (`scene.py` even notes the
   "per-segment normal discontinuities"). **Fix:** (a) give the cylinder **smooth
   per-vertex normals** (proper cylinder shading — also helps the SMS Newton find
   the reflective manifold), or raise segment count + smooth-shade; (b) move the
   **camera to look straight down the cup axis** (or steeper) so the inside-wall
   caustic crescent is centered and readable; (c) move the **light farther away**
   (it currently sits at the rim, `light_y ≈ 0.75` of a 1.6-tall cup) so it's not
   on top of the cup and the crescent is the hero, not the lamp.
3. **Glass sphere obscures its own caustic (scene 3).** Don't put the sphere
   **exactly on the floor** — it hides the focused caustic. **Fix:** lift the sphere
   slightly off the plane (and/or reposition the light), and **zoom the camera onto
   the caustic** (the important part of the frame), not the whole scene.
4. **Redo all refractive-caustic + dispersion scenes (2 & 3).** Re-author the prism
   (bk7 + sf11) and the glass sphere using the **forward light-tracer** (pkg110),
   with the composition fixes above (zoom to the band / caustic).
5. **Cycles sweep needs better lighting + composition (scene 5).** `disney-sweep-…`:
   a single flat overhead area light is dull. **Fix:** use 3-point or an HDRI so the
   roughness gradient + specular highlights read clearly; recompose the grid; then
   re-bless the Cycles reference. **Fix the FOV bug first.**

---

## The FOV-mismatch bug (prerequisite for scene 5's gate)

Owner: *"the actual and reference renders have differing camera FOVs so they don't
line up — is this the old Blender/Astroray frustum-divergence bug?"*

**Finding:** on paper the two cameras are set up to **match** —
- Astroray (`disney-sweep-cycles-compared/scene.py`): `setup_camera(look_from=[0,0.3,7], look_at=[0,-0.6,0], vfov=30°, aspect=384/256)`.
- Cycles (`cycles_bless.py`): `cam_pos=(0,-7,0.3)`, `cam_target=(0,0,-0.6)` (the correct Y-up→Z-up conversion), `cam.data.angle=0.5236` (30°), `sensor_fit="VERTICAL"`.

Both are vertical-FOV 30° with matching positions/targets, so they *should* align.
**This is therefore NOT the pkg100/pkg101 bugs** — those were in the addon/importer
(`perspective_matrix` vfov extraction; `.blend` intrinsics), not these direct
`setup_camera` calls. The remaining suspects, in order:
1. A **stale blessed `reference.png`** rendered before a camera/scene edit (the
   scripts "drift independently" by design — `cycles_bless.py` header). Re-render the
   reference and re-compare first; this is the cheapest check.
2. A subtle **sensor-fit / aspect convention** difference: Astroray's `setup_camera`
   maps `(vfov, aspect)` to a frustum (`vh = 2·tan(vfov/2)·focus`, `vw = vh·aspect` —
   vertical-driven) vs Cycles `sensor_fit="VERTICAL"`. If the *vertical* extents
   match but the *horizontal* don't, it's an aspect/sensor-fit mismatch; if vertical
   also differs, it's a vfov-interpretation mismatch.
**Diagnostic:** render both, overlay at 50% opacity, and measure whether the floor
line + grid extents coincide vertically vs horizontally. That isolates (1) vs (2)
vs vfov. Until resolved, scene 5's cross-engine SSIM gate is not trustworthy.

---

## Caustic-path alignment with the 2026-05-30 fork decision

The owner chose the **forward photon map as the canonical caustic path** (see
`cpu-gpu-parity-status.md`). So:
- **Refractive** caustics (scenes 2, 3) use the pkg110 forward light-tracer — done;
  retire the SMS `sms-refractive-glass-sphere` to legacy.
- **Reflective** caustic (scene 4) **stays on SMS for now**: the forward loop only
  deposits after a *transmissive* caster, so it can't yet do a metal concave
  reflector. Migrating scene 4 to the photon map needs the forward loop to handle
  **reflective casters** (deposit after a reflective bounce) — a pkg111/pkg113-era
  follow-up. Until then SMS is the retained mechanism for this one case.

---

## Status / next step

This design **resolves pkg104's owner-input gate** (scene set + parameterization
chosen). **Implementation is a follow-up** (re-authoring + re-rendering the scenes
with RTX + a mandatory visual check per the pkg110 lesson — the caustic numeric
gates pass on noise). Recommended order: (1) fix the FOV bug + re-bless the Cycles
sweep; (2) redo the refractive + dispersion scenes (composition); (3) smooth-shade +
re-frame the reflective cup; (4) add BH background detail; (5) bump resolutions +
re-bless. Each is owner-visual-blessed before pinning.

---

## Appendix — README gallery feedback (separate from the reference bank)

The owner clarified the earlier feedback was about the **README gallery**
(`scripts/diagnostics/render_readme_gallery.py` + `render_readme_hero.py`), NOT the
reference bank. Noted here for whenever those tiles are regenerated:
- **Hero** (Kerr synchrotron jet, `render_readme_hero.py`): keep; "whatever looks good."
- **Prism rainbow tile** (`tile_prism_caustic`): "might need tweaking to get a good
  comp"; also re-render via the pkg110 forward light-tracer for a clean band.
- **Material contact sheet** (`tile_material_contact_sheet`): "flat and boring, needs
  redoing."
- **Convergence tile** (`tile_convergence_cornell` ← `scripts/diagnostics/convergence_tracker.py`):
  **BUG** — the MSE plot uses the **highest-spp image as its own reference**
  (`convergence_tracker.py:201 reference = renders[spp_levels[-1]]`), so the last
  point (1024 spp) has MSE→0 and the curve shows a spurious cliff instead of a
  smooth decay. **Fix:** render a separate higher-spp reference (e.g. 4096/8192) and
  MSE every plotted level against *that*, or drop the last level from the series.
- **AOV 2×2 tile** (`tile_aov_stack`: beauty/normal/depth/albedo): owner likes it;
  **expand** with more passes that already exist — a **sample-count heatmap** and
  (e.g.) motion-vector / cryptomatte (pkg87) — i.e. a 2×3 or 3×3.
- **Denoise tile** (`tile_oidn_before_after`): "great showcase but very low
  resolution" (it 2×-upscales a small test render) — re-render at higher res on a
  more interesting scene.
- **Disney sweep tile** (`tile_disney_sweep`): "fine as is, kind of boring."
- **HDRI 3-sphere MIS tile**: "beautiful with the sunset background, doesn't need to change."

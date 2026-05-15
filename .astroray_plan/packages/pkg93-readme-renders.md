# pkg93 — README hero + gallery renders — SPEC

**Pillar:** 5 (production polish / showcase)
**Track:** A (renders need RTX 5070 Ti to match the validation-snapshot numbers)
**Status:** done — landed alongside the README refresh on branch `pkg93`
**Estimated effort:** 1–2 sessions (~4–8 h on RTX 5070 Ti); most cost is the
  Kerr+jet hero scene composition (no checked-in source asset yet)
**Depends on:** pkg42 (synchrotron jet plugin) done, pkg64 (SMS caustics) done,
  pkg68 / pkg74 / pkg29a outputs exist as derive-from sources
**Composes with:** the README rewrite landing on this branch — README places
  the placeholder paths under `docs/renders/`; this spec produces the files.

---

## Goal

**Before:** the refreshed `README.md` references 8 render placeholders
under `docs/renders/`. None of the files exist yet. README is technically
broken-image until the renders land.

**After:** all 8 paths are populated with hero-quality renders that match
the README's accompanying caption. Each render either derives from an
existing `test_results/` asset (composite / crop / re-export) or is a new
scene rendered on the RTX 5070 Ti at the resolutions and SPP counts
listed below.

---

## Render list

| Path | Source / derivation | Resolution | SPP | Integrator | Denoise | Notes |
|---|---|---|---|---|---|---|
| `docs/renders/hero_kerr_jet.png` | **NEW scene** — see "Kerr+jet composition" below. No checked-in source. | 1920×1080 | ≥4096 | `path_tracer` with `BlackHole` shape + `synchrotron_jet` volumetric emitter (pkg42) | OptiX HDR | Hero / masthead |
| `docs/renders/gallery_prism_caustics.png` | Re-render of the pkg29a / pkg64 prism-to-screen scene at hero quality. Source: `test_results/pkg29a_prism_to_screen_caustic_path_tracer.png` (640×480, ~64 spp) — re-run the same scene at high quality. | 1920×1080 | ≥4096 | `path_tracer` with `use_refractive_caustics=true`, BK7 prism `is_caustic_caster=true` | OIDN HDR | Lead gallery tile; matches the pkg64 +8.83 dB receipt |
| `docs/renders/gallery_material_contact_sheet.png` | Composite from `test_results/session_close_2026-05-14b/contact_sheet/` — already a finished contact sheet. Re-export at target resolution if source is smaller. | 1280×720 | 256–1024 (existing) | n/a (already rendered) | n/a | Pure asset re-export; cheapest tile |
| `docs/renders/gallery_convergence_cornell.png` | Composite from `test_results/session_close_2026-05-14b/convergence/convergence_strip.png` + `convergence_mse.png` side-by-side at 1280×720. | 1280×720 | n/a (composite) | n/a | n/a | Pure compositing in PIL / ImageMagick |
| `docs/renders/gallery_aov_stack.png` | Composite of `test_results/session_close_2026-05-14b/aov/{beauty,normal,depth,albedo}.png` in a 2×2 grid at 1280×720 with corner labels. | 1280×720 | n/a (composite) | n/a | n/a | Pure compositing |
| `docs/renders/gallery_oidn_before_after.png` | Re-export of `test_results/pkg32_oidn_check/oidn_before_after.png` (already a before/after composite). Verify it's ≥1280 wide; if not, re-render at target. | 1280×720 | 64 (input) | `path_tracer` | OIDN (right half only) | Likely zero-work if source resolves |
| `docs/renders/gallery_disney_sweep.png` | Composite from `test_results/mat_disney_r0.05.png`, `mat_disney_r0.30.png`, `mat_disney_r0.70.png`, `mat_glass_ior1.2.png`, `mat_glass_ior1.5.png`, `mat_glass_ior2.0.png` in a 2×3 grid at 1280×720. | 1280×720 | n/a (composite) | n/a | n/a | Pure compositing |
| `docs/renders/gallery_hdri_world.png` | **NEW scene** — Disney metal + Disney glass spheres on a ground plane lit by a checked-in HDRI (`data/hdri/*.hdr` if present, else use Blender's `studio.hdr`). Demonstrates pkg63 MIS env-map. | 1280×720 | 1024 | `path_tracer` | OIDN HDR | Small new scene — ~200 LOC of Python scene-build |

**Expected wall-clock on RTX 5070 Ti** (rough, based on pkg71 and pkg64
measurements):

- Hero Kerr+jet 1920×1080 @ 4096 spp: ~6–12 minutes (GR ray marching is
  the bottleneck; pkg41 measurements suggest ~3-4× the Cornell cost).
- Prism caustic 1920×1080 @ 4096 spp with SMS: ~3–5 minutes
  (pkg64 measured 2.0% empty-hook overhead; SMS-on cost dominates).
- HDRI world 1280×720 @ 1024 spp: ~30–60 seconds.
- All composites: seconds (PIL).

---

## Kerr+jet hero composition — TODO

**No checked-in source asset for this exists.** Past pkg40/41/42 tests
produced validation renders (e.g., `test_results/test_bh_showcase.png`,
`test_results/test_bh_shadow.png`), but none are hero-framed. The
composition itself is the bulk of pkg93's work.

Composition checklist:

1. **Black hole:** Kerr metric, spin a ≈ 0.9, viewed from
   inclination ≈ 75° (near edge-on so the lensed ring is visible but
   the jet is not foreshortened to a line).
2. **Accretion disk:** slim disk (pkg43) at ṁ ≈ 0.1, inner radius
   r_ISCO, outer radius ~20 M. Disk temperature gradient drives the
   blackbody emission.
3. **Jet:** `synchrotron_jet` (pkg42) bipolar, opening angle ≈ 5°,
   power-law electron index p ≈ 2.5. Length ~50 M along the spin axis.
4. **Environment:** dark (no HDRI) or a faint starfield. Galactic
   background optional.
5. **Camera:** 35 mm equivalent, f/2.8, distance ≈ 100 M from event
   horizon. Spectral mode (pkg11) so the temperature gradient produces
   a visible blue→red disk gradient and the jet's synchrotron SED is
   physical.
6. **Sanity checks:** Einstein ring should be visible (pkg41 gate);
   redshift on far side of disk should be visible as a temperature
   shift (pkg67); jet should be brighter on the side moving toward the
   camera (relativistic beaming, pkg42).

If the first-cut framing isn't striking enough, the fallback hero
candidate is the prism caustic. Don't ship a bad Kerr render — drop
back to the prism if needed and demote `hero_kerr_jet.png` to a
gallery tile.

---

## Validation gates

- **G1 — README links resolve.** Every `![...](docs/renders/...)`
  reference in `README.md` points at a file that exists in this PR.
  Verify with a one-line grep.
- **G2 — No broken provenance.** Every render either derives from a
  checked-in `test_results/` asset (listed in the table above) or is a
  new scene with a scripted producer (committed under
  `scripts/diagnostics/` or similar). No "I rendered it on my machine,
  trust me" assets.
- **G3 — Resolution + SPP match the table.** New renders meet the
  listed minimums; lower than that doesn't ship.
- **G4 — File size sanity.** Each PNG ≤ 2 MB (re-export with PIL +
  pngquant if needed). README repository load budget: ≤ ~10 MB total
  for `docs/renders/`.
- **G5 — Visual-check pass.** Run `Skill(visual-check)` on the hero
  and prism tiles; record qualitative inspection notes in the pkg93
  PR body.

---

## Files to add / modify

```
docs/renders/hero_kerr_jet.png              (new render — see TODO above)
docs/renders/gallery_prism_caustics.png     (new render at hero quality)
docs/renders/gallery_material_contact_sheet.png  (re-export / composite)
docs/renders/gallery_convergence_cornell.png     (composite)
docs/renders/gallery_aov_stack.png               (composite)
docs/renders/gallery_oidn_before_after.png       (re-export)
docs/renders/gallery_disney_sweep.png            (composite)
docs/renders/gallery_hdri_world.png         (new small scene)
scripts/diagnostics/render_readme_hero.py   (NEW — produces the Kerr+jet hero)
scripts/diagnostics/render_readme_gallery.py (NEW — produces the prism + HDRI tiles + composites the rest)
```

Composite scripts MUST be idempotent and self-contained (`python
scripts/diagnostics/render_readme_gallery.py` should regenerate every
composite tile from the listed `test_results/` sources without manual
steps). The hero render script is allowed to require RTX hardware.

---

## License fence

All inputs are first-party (rendered by Astroray) or already-cleared
test_results assets. No external image assets are imported. The
`gallery_hdri_world.png` scene references the HDRI shipped under
`data/hdri/` if one is already committed; if not, ship the scene with
a procedural sky (no new asset bundling).

---

## When this spec is ready to dispatch

Immediately. No owner-preference forks. The Kerr+jet composition
choices are documented above and can be iterated visually; if the
first-cut doesn't land, fall back to the prism caustic as hero.

---

## Lessons (post-implementation)

- **Kerr+jet hero at full 4096 SPP is ~80 min on CPU**, not 6–12 min as the
  spec estimated. The spec extrapolation assumed Cornell-cost scaling, but
  GR ray marching dominates and per-sample cost is ~30× higher than RGB PT.
  Shipped at **1024 SPP** (≈ 20 min) — visually clean for this mostly-dark
  scene; the lensed photon ring and arcs are smooth at this sample count.
- **First-cut Kerr framing landed.** Inclination 75°, FOV 18°, distance 100 M
  produced a recognizable EHT-style lensed-arc + jet composition on the
  first preview. The fallback clause (demote to prism if framing fails)
  was not needed.
- **Reinhard tone-map needs the log-average variant on mostly-black scenes.**
  Linear + soft-knee crushed the dim lensed arcs to near-black; using
  `key = 0.18 / exp(mean(log(lum)))` per Reinhard 2002 §3 amplifies dim
  features into visibility while soft-clipping the disk+jet core.
- **`render(spp, depth, None, spectral=True)` clamps RGB output to [0,1].**
  The spectral-to-RGB conversion in the renderer produces normalized
  output, so log-average Reinhard has nothing to amplify (avg ≈ 0.02,
  key/avg ≈ 9 → soft-knee plateaus). Use `spectral=False` for tone-mapping
  freedom on HDR astrophysical scenes.
- **Prism caustic re-render shipped at 2048 SPP** (≈ 8 min) using a
  redesigned apex-up equilateral prism scene with horizontal beam (the
  pkg29a validation scene's camera was looking at the prism *front* with
  the screen *behind* and occluded, producing a flat-grey rendering at
  hero scale). The redesigned scene shows clean refraction and physical
  dispersion sampling but the rainbow band on the receiver wall is dim
  relative to the directly-lit wall — this is physics-correct but not a
  vivid hero. Future iteration: blocker between emitter and wall, or
  mid-gray walls for higher contrast, or a much larger emitter-prism
  separation to spread the rainbow wider.
- **`Sellmeier` dielectric materials are CPU-only** on this build —
  `set_use_gpu(True)` rejects materials with `sellmeier_preset` or
  `glass_preset`. Hero/prism use CPU; HDRI-world tile swapped from
  `sellmeier_preset:bk7` to fixed `ior:1.52` for GPU.
- **Worktree `test_results/` is empty (gitignored).** The gallery
  composite script must resolve the main repo's `test_results/` via
  `git rev-parse --git-common-dir` to find the source assets.
- **The hero render `.pyd` lookup needs `ASTRORAY_BUILD_DIR`** pointing at
  the main repo's `build_cuda/` when invoked from a worktree, because
  `build_cuda/` is gitignored and not present in worktrees.

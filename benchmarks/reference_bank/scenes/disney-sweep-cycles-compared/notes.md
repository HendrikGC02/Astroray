# disney-sweep-cycles-compared

**Vision:** A 3×3 grid of Disney-BSDF spheres (roughness × metallic) rendered
in both Astroray and Cycles 5.1 against a freshly-authored sphere grid (no
Blender Foundation benchmark assets). Gate the Astroray render against the
Cycles output to catch gross BSDF regressions.

**This scene is *the* Cycles comparison hook in pkg104.** Other scenes use
owner-blessed Astroray references; only this one cross-compares against
Cycles, because:
1. The Disney BSDF is the place an Astroray-vs-Cycles delta is most actionable
   (both engines implement the same Burley 2012 closure family).
2. The remaining bank scenes either can't be rendered in Cycles (SMS, GR) or
   would be confused by Cycles' shader-graph forward-compat issues.

**Re-blessing the Cycles reference:**

```powershell
"C:/Program Files/Blender Foundation/Blender 5.1/blender.exe" --background `
    --python benchmarks/reference_bank/scenes/disney-sweep-cycles-compared/cycles_bless.py
```

This writes `reference.png` directly. Do NOT use the regular `--bless` flag
(which would replace the reference with Astroray's own output and defeat
the gate's purpose).

**Known calibration gap 2026-05-27:** Current Astroray-vs-Cycles SSIM is
**0.48**, not the ≥0.85 the spec aspires to. Sources of difference:
1. Cycles uses watts for area-light energy; Astroray uses an opaque
   `intensity` scalar. The 200 W / 14-intensity mapping is approximate.
2. Cycles' "Standard" view transform may still apply a subtle film
   response curve in Blender 5.1 that Astroray's tonemap doesn't.
3. Cycles' Principled BSDF and Astroray's Disney implementation share
   conceptual parameters but their closure decomposition (sheen/clearcoat
   slots, IOR↔specular mapping) differs in detail.
4. Camera-FOV / lens / sensor-fit translation between Astroray's
   `setup_camera(vfov, aspect_ratio)` and Blender's `cam.data.angle` +
   `sensor_fit='VERTICAL'` produced visually-similar but not framing-
   identical renders.

**To narrow the gap (follow-up calibration pass):**
- Use Blender's "Raw" view transform (no film curve at all).
- Tune Cycles area-light watts until mean image luminance matches Astroray's.
- Move from a 3×3 grid to a smaller, simpler scene (single material chip)
  to isolate BSDF differences from light-unit differences.

**For now,** the gate at SSIM ≥ 0.40 catches further regressions from this
baseline. The gate's *purpose* is "detect Disney BSDF regressions in
Astroray," and at SSIM ~0.48 a major BSDF break would clearly drop it
below 0.40.

**Reference notes:** 384×256, Astroray 256 spp / Cycles 256 spp.
Both files in this directory must stay synchronized — if you change
`scene.py`, mirror the change in `cycles_bless.py` AND re-run the
Cycles bless command.

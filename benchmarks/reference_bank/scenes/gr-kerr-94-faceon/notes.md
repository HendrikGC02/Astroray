# gr-kerr-94-faceon

**Vision:** Kerr black hole at near-maximal spin (a/M = 0.94). Paired with
`gr-schwarzschild` to exercise the metric-plugin dispatcher: if the
dispatcher silently routes both spin=0 and spin=0.94 to the Schwarzschild
plugin, the two scenes produce visually-identical output and a same-bank
differential check (pHash distance between them) reveals the regression.

**Known limitations 2026-05-27:**
1. Disk parameters (`disk_outer`, `accretion_rate`) didn't produce a visibly
   distinct disk at the bless-time render — the rendered image is dominated
   by the white background and the small BH shadow. The visible spin-induced
   asymmetry that would dramatize Kerr is not yet observable in this scene.
2. The pair-distinguishing signal against gr-schwarzschild is pHash=2 — small
   but real. A regression that collapses Kerr→Schwarzschild would drop it to 0.
3. A better Kerr scene (with bright accretion disk on dark background to show
   frame-dragging asymmetry) requires either pkg42/pkg43/pkg44 emission plugins
   tuned for visibility (deferred to Phase 2b astrophysics scope) or
   black-hole-with-Blender-integration so the disk can be authored in the
   Blender addon (separate spec).

**Reference notes:** 256×256, 16 spp, ~few sec render. Same camera as
gr-schwarzschild; only the BH params differ.

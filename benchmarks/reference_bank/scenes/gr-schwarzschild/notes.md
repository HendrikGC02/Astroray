# gr-schwarzschild

**Vision:** A non-rotating black hole produces a sharp circular shadow against
a uniform background. The shadow is the boundary of trapped geodesics; outside
the boundary, light reaches the camera; inside, light is captured.

**Limitation noted 2026-05-27:** With the current `add_black_hole` parameter
mapping, the visible shadow renders quite small (~0.4% of frame at the chosen
camera distance). Achieving the larger, iconic shadow shown in the older
`tests/reference/schwarzschild_baseline_256.png` would require either:
1. A different parameter combination I haven't found (the parameter mapping
   between `M`, `influence_radius`, and visible horizon radius isn't fully
   documented in the API surface).
2. Addon-side BH geometry placement (referenced as a separate
   follow-up spec — black-hole Blender integration).

For the bank's purposes (regression catching) this is acceptable: the
`dark_disk` gate registers the GR-dispatch signature and would catch any
regression that removes the shadow entirely.

**Reference notes:** 256×256, 16 spp, ~few sec render. spin=0 hardcoded.

# pkg325 - Cycles bounce-cap termination (research note)

Source: Blender v5.2.0 (Apache-2.0), read from the tag; line numbers are that tag's.

## How Cycles ends a path at the bounce cap
- `intern/cycles/scene/integrator.cpp:222,226`: the kernel gets `max_bounce = max_bounces + 1` and
  `max_transmission_bounce = max_transmission_bounces + 1`; `:233` `transparent_max_bounce` is NOT incremented.
- `kernel/integrator/path_state.h:143-146`: in `path_state_next` (called from `shade_surface.h:621`) a non-transparent
  scatter with `bounce >= max_bounce` sets `PATH_RAY_TERMINATE_AFTER_TRANSPARENT`; `:205-208` the same for
  `transmission_bounce >= max_transmission_bounce`.
- `kernel/integrator/surface_shader.h:1265-1268`: a path with a `PATH_RAY_TERMINATE` bit stores no closures at the next
  surface (`max_closures = 0`), so `shade_surface.h:497-499` (`!(sd->flag & (SD_BSDF | SD_BSSRDF))` -> `LABEL_NONE`) ends it
  there; only emission and Transparent BSDF closures survive (`closure/bsdf_transparent.h:43-58`).
- Transparent passes (`path_state.h:120-135`) count only in `transparent_bounce`; no bounce / per-type spend.

So Cycles "terminate" = the next glass surface has no BSDF. A path through k glass interfaces needs `max_bounces >= k-1`
(measured on the pkg325 scene: 2 / 4 / 6 interfaces pass at caps 1 / 3 / 5).

## Astroray terminate
Before #1165 `pathTraceSpectral` ended a path whose continuation would be vertex `maxDepth` (`bounce + 1 >= maxDepth`) or
whose lobe type counter reached its limit, so k interfaces needed `maxDepth >= k+1` (2 fewer glass bounces than Cycles).
#1165 adopts the Cycles rule above on CPU and GPU: the scatter with `bounce >= maxDepth`, or the one whose per-type count
reaches its limit, sets a sticky terminate-after; its continuation is traced and the next surface adds emission only. k
interfaces now need `max_bounces >= k-1` (pkg325 stack ROI means match the Cycles s7 renders within 0.004 at caps 1..64).
Transparent and volume caps already followed Cycles and are unchanged.

## passthrough
Where terminate would end the path after a TRANSMISSION sample (since #1165: where the sample sets terminate-after), the sample keeps its weight f/pdf but goes straight on
(`wi = -wo`) as a transparent pass. The weight is kept because it carries the 1/eta^2 radiance scaling of entering glass:
resetting the throughput to 1 (the literal "unchanged throughput") leaves a path that is capped inside a slab at 1/2.25 of
the white world (measured: stack ROI mean 0.46 at cap 4 vs 0.89 with the weight kept; 1.0 uncapped). Reflection samples at a
capped vertex still end the path. Opaque surfaces reached at the cap depth stay dark by construction (no continuation ray to
gather the world). Passes are bounded by `transparent_max_bounces` (the addon passes `min(8, max_bounces)`).

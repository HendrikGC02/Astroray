# sms-reflective-metal-sphere

**Note on naming:** This scene's directory name (`sms-reflective-metal-sphere`)
preserves the original ID for the bank; the actual geometry was replaced
2026-05-27 from a convex metal sphere to a **concave coffee-cup interior**
per owner feedback ("a convex sphere doesn't focus light — caustics need
a concave reflector"). Renaming the directory was deferred to avoid
breaking history / gate-config links; will rename to
`sms-reflective-cup-interior` in a follow-up PR.

**Vision:** A polished metal cup (triangulated cylinder, 32 segments,
closed bottom, open top), lit by an area emitter sitting at the rim on
one side. The curved inside walls reflect the side light and focus it
into a visible caustic crescent on the opposite inside wall — the
classical "coffee-cup caustic" you see in real life when light from a
window falls on the inside of a mug.

**Why this works where the previous sphere didn't:**
A convex mirror (sphere exterior) disperses light: each incoming ray
reflects to a divergent direction. There's no focal point, so no
caustic. A concave mirror (cup interior, half a sphere from inside, etc.)
converges incoming parallel-or-near-parallel rays toward a focal region,
producing a measurable bright region — the caustic.

**Reference notes:** 384×256, 1024 spp CPU, ~55 s. SMS reflective branch
+ caustic_caster flag on every cup triangle. The triangulated cylinder
(32 segments) is dense enough that the SMS Newton iteration finds the
reflective manifold despite per-segment normal discontinuities; if you
drop the segment count below ~16 the caustic-finding starts to fail.

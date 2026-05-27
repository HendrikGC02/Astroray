# sms-reflective-metal-sphere

**Vision:** A polished metal sphere (roughness 0.02) reflects an area emitter
onto a diffuse floor, producing a soft luminous caustic ring at the sphere's
base. Tests the SMS reflective-caustic branch (`set_use_reflective_caustics(True)`).

**Why brighter light than the refractive scene:** A convex mirror disperses
incoming flux (virtual focal point behind the sphere), so the reflected caustic
is naturally less concentrated than a refractive focus. The light intensity
is bumped to 30 to keep the caustic ring visible at 1024 spp.

**Reference notes:** 384×256, 1024 spp CPU, ~30 s.

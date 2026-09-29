# Principled Emission on GPU (worker ON / OFF, main vs fix)
Viewport edit sequence: base, base colour red, Emission Strength 5 / 10, emission green, emission 0.
Verdict: on main the GPU ignores Principled Emission (spheres go dark); after the fix it emits as an
illuminant (GPU/CPU 0.994-1.003) with worker ON and OFF identical.
Provenance: issue #835 / #843, Batch S, 2026-09-20.

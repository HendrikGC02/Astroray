# Viewport edits refresh the render (material and object)
Sphere on a floor: material edits (base colour red, emission 5/10, green, 0) and object edits (move sphere, light x4),
worker ON and OFF, before (pre) and after (post) the fix. Each sheet: rows pre OFF / pre ON / post OFF / post ON.
Verdict: before, base colour / move / light edits were not reflected (stale frames); after, all steps update on
CPU and GPU. apply_cost_chart: the GPU edit apply cost fell from 60-130 ms (light, object) to ~0.1 ms.
Provenance: hotfix S (viewport stale-edit fix), RTX 5070 Ti, 2026-09-19.

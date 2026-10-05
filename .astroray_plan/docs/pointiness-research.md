# Geometry Pointiness research (pkg322)

- Source: Blender `intern/cycles/blender/mesh.cpp` `attr_create_pointiness` (SPDX Apache-2.0, main, 2026-10-06).
  Compatible licence; no GPL candidate involved.
- Algorithm: (1) weld colocated vertices (sort by float32 coordinate sum, descending index on ties; scan
  forward inside a 3*FLT_EPSILON sum window; duplicate if |dp|^2 < FLT_EPSILON; chain to the first);
  (2) welded vertex normal = normalise(sum of Blender vertex normals); (3) over the welded unique edges
  accumulate unit directions to the neighbour; `raw = acos(clamp(dot(n, accum/count))) / pi`;
  (4) one blur pass `data = (raw + sum raw[neighbours]) / (count + 1)`; copy to duplicates.
  Vertex attribute (ATTR_ELEMENT_VERTEX) -> linear over the triangle; Geometry node reads it as a float.
- Port: `blender_addon/pointiness.py` (numpy). Vertex normals = `Mesh.vertex_normals`, edges = `Mesh.edges`.
- Reference values: Cycles 5.2 bake of Geometry > Pointiness through Emission into a FLOAT_COLOR POINT
  attribute (`bake.target = VERTEX_COLORS`); max |diff| ~1e-5 on four meshes (tests/test_pkg322_pointiness.py).
- Difference noted: Cycles `normalize` of a zero welded normal gives NaN; the port yields 0 (safe).

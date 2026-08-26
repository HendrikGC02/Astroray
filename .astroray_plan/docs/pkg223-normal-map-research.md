# pkg223 — Tangent-space normal-map decode convention (Blender/Cycles) — research note

**Date:** 2026-08-26
**Package:** pkg223 — Normal Map node (pkg219d part 1), spec
`.astroray_plan/packages/pkg223-normal-map-node.md`.
**Policy:** CLAUDE.md §6 — no invented algorithms. Reference = Blender/Cycles
Normal Map node semantics (Apache-2.0) + Mikkelsen Mikk-TSpace (BSD-3-Clause).

## References

- **Cycles:** `intern/cycles/kernel/svm/svm_tex_coord.h` — `svm_node_normal_map`
  (Blender main, Apache-2.0). The local vendored copy `external/cycles_light_tree/`
  is a light-tree-only snapshot and does NOT contain this file — cite upstream.
- **Mikkelsen, M. S., "Simulation of Wrinkled Surfaces Revisited", Master's
  thesis, University of Copenhagen (DIKU), 2008.**
  PDF: http://image.diku.dk/projects/media/morten.mikkelsen.08.pdf
- **Mikk-TSpace impl:** `https://github.com/mmikk/MikkTSpace` — `mikktspace.h`/
  `mikktspace.c` (BSD-3-Clause); Blender vendors it at `extern/mikktspace/`
  (`BKE_mesh_calc_loop_tangents` → `ATTR_STD_UV_TANGENT`/`_SIGN`).
- **Lengyel, E., "Computing Tangent Space Basis Vectors for an Arbitrary Mesh",
  Terathon Software, 2001.** https://terathon.com/code/tangent.html

## 1. Decode: n_ts = 2·rgb − 1

Cycles `svm_node_normal_map` (svm_tex_coord.h):

```c
float3 color = stack_load_float3(stack, color_offset);
color = 2.0f * make_float3(color.x - 0.5f, color.y - 0.5f, color.z - 0.5f);
```

i.e. `n_ts = 2·rgb − 1`: unpack [0,1] texture RGB into a [-1,1] tangent-space
vector. The flat/identity texel (0.5, 0.5, 1.0) → (0, 0, 1) = the geometric
normal. Cycles skips the node when the decoded vector is exactly zero (a
mid-gray texel (0.5,0.5,0.5)), leaving `sd->N` untouched.

## 2. The tangent frame MUST be UV-aligned — not an arbitrary ONB

A tangent-space normal map is an *encoding* relative to the baker's frame: the
perturbation azimuth (the compass direction the relief leans) is locked to the
texture's UV parameterization. Decoding requires the exact inverse of the frame
the baker used — Mikkelsen 2008 / mikktspace.com: "the transformation used to
decode would have to be the exact inverse of that which was used to encode".
Mikk-TSpace computes per-vertex tangents consistent with the UVs
(order-independent, welded); the pixel-shader decode is:

```c
vB = sign * cross(vN, vT);
vNout = normalize(vNt.x * vT + vNt.y * vB + vNt.z * vN);
```

(mikktspace.h `m_setTSpaceBasic` docs). The per-triangle fallback is the Lengyel
inverse-UV-Jacobian: Q1=P1−P0, Q2=P2−P0, (s1,t1)=uv1−uv0, (s2,t2)=uv2−uv0,
`r = 1/(s1·t2 − s2·t1)`, `T = r·(t2·Q1 − t1·Q2)`, `B = r·(s1·Q2 − s2·Q1)` — T
along +U, B along +V (Lengyel 2001).

An arbitrary ONB (e.g. `make_orthonormals(N)`) has NO relation to the UVs: the
same texel decodes to a different world direction per surface, rotating the
relief to a random compass direction and breaking parity with any Cycles-baked
map. The frame must come from the UV parameterization.

## 3. Green channel / handedness: OpenGL-style +Y-up green; B = sign·cross(N, T)

Cycles tangent-space branch (svm_tex_coord.h):

```c
float3 tangent = primitive_attribute_float3(kg, sd, desc);  // ATTR_STD_UV_TANGENT
float sign = primitive_attribute_float(kg, sd, sign_desc);  // ATTR_STD_UV_TANGENT_SIGN
float3 N_geom = sd->N;
float3 B = sign * cross(N_geom, tangent);
N = safe_normalize(tangent * color.x + B * color.y + N_geom * color.z);
```

- The green channel (color.y) multiplies the **bitangent B** with **no
  negation** → Blender/Cycles use the **OpenGL convention: +Y (green) points
  "up" along +B**. DirectX-style maps store green flipped (−Y down); feeding
  one unflipped inverts the relief (Mikkelsen 2008 discusses the mismatch).
- `sign` is the **UV-winding handedness** from Mikk-TSpace
  (`fSign = bIsOrientationPreserving ? 1.0f : -1.0f` in mikktspace.h): +1 for
  orientation-preserving UVs, −1 for mirrored UVs. It keeps `B = sign·cross(N,T)`
  continuous across mirrored UV islands — without it, islands get inverted relief.

## 4. Strength: n = normalize(lerp(N_geom, mapped, clamp(strength, 0, 1)))

Cycles applies Strength after the space transform (svm_tex_coord.h):

```c
float3 strength = stack_load_float3(stack, strength_offset);
strength.x = saturatef(strength.x);   // clamp to [0,1]
...
N = safe_normalize(sd->N + (N - sd->N) * strength);
```

`sd->N + (N − sd->N)·s = (1−s)·sd->N + s·N` — a lerp between the geometric
normal and the mapped normal, renormalized:
`n = normalize(lerp(N_geom, mapped, clamp(strength, 0, 1)))`. Strength 0 →
geometric normal (flat); Strength 1 → full perturbation; monotone in between.
(OSL twin: `node_normal_map.osl` — `Normal = normalize(NormalIn + (Normal -
NormalIn) * max(Strength, 0.0))`.)

## What we reproduce / differences

- Reproduce: decode, UV-aligned TBN rotate, handedness, Strength lerp —
  byte-mirrored CPU/GPU (GPU shade path behind `template<bool HasNormalPerturb>`).
- Difference: Cycles' `ensure_valid_reflection` reflection-fix (D2574) runs
  downstream at closure setup; pkg223 does not port it — file a follow-up if
  grazing-angle black speculars appear.
- Difference: Cycles falls back to `primitive_tangent` (derivative-based) when
  no tangent attribute exists; pkg223's fallback is the UV-gradient Lengyel
  tangent (same family).

## Integration plan in Astroray

- Package: pkg223 (`pkg223-normal-map-node.md`). CPU shade path + GPU wavefront
  shade path; addon emits the normal-map spec (texture handle, Strength, space).
- Parity check: Cycles-baked normal map on a quad/sphere — lighting direction
  must match (not inverted); Strength 0 ≈ flat render.
# #990 Attribute / Color Attribute / Object Info: research note (2026-10-03, lane N1)

## Sources (Apache-2.0, Blender Cycles `main`)

* `kernel/svm/attribute.h` `svm_node_attr_surface_eval`: output conversion by data type. FLOAT:
  Color/Vector = (v,v,v), Fac = v, Alpha = 1. FLOAT2: Color = (x,y,0), Fac = x, Alpha = 1. FLOAT3:
  Fac = average(xyz), Alpha = 1. FLOAT4 / RGBA: Fac = average(rgb), Alpha = w. Missing attribute: the
  node's `missing` values (0). Surface values are `primitive_surface_attribute`: POINT and CORNER
  interpolate linearly over the triangle, FACE is constant.
* `kernel/svm/geometry.h` `NODE_INFO_OB_*`: Location = object translation, Color / Alpha = object
  colour, Object Index = pass index, Material Index = the shader's (material) pass index, Random =
  `object_random_number`.
* `scene/object.cpp`: `random_number = random_id * (1 / 0xFFFFFFFF)`; `blender/object.cpp`: a
  non-instanced object gets `random_id = hash_uint2(hash_string(name), 0)` (`util/hash.h`: lookup3
  `final`, `hash_string` = `i * 37 + c`). Verified against a Cycles 5.2 render of Object Info > Random
  (objects Inst0..2: 0.2948239, 0.1035135, 0.8790834, exact).

## Astroray mapping

* Engine service `include/astroray/attribute_layers.h`: a layer is a named Vec3 per triangle corner,
  interpolated with barycentrics recomputed from the hit point (Ericson §3.4, the #847 Generated form),
  shared by CPU (`Triangle::attributeValue`, `AttributeTexture`) and GPU (`gpu_attrTexel`,
  `shading_inputs_eval.cu`). Names are interned to ids (`attr::layer_id`).
* The addon decides what a layer holds: `shader_vm_compiler.attribute_layer_key` names one layer per
  (node, output) (`attr:<name>|rgb|fac|alpha`, `color:<layer>|...`, `objinfo:<Output>`), and
  `_bulk_geometry.mesh_attribute_layers` fills it per corner with Cycles' output value, so the op-VM
  only sees a texture input. Object Info constants are per object, filled on flattened triangles;
  objects whose materials read layers are excluded from the two-level instancing path.
* GPU: one descriptor per layer (`GImageTexture::attrLayer`) whose texels are three corners per
  uploaded triangle, appended after the geometry walk. Path state / hit buffer unchanged.
* Reported, not silent: Attribute types other than Geometry (Object / Instancer / View Layer), EDGE
  domain and unsupported data types (quaternion, int2, matrix), motion-blurred objects, the non-bulk
  geometry path, attribute-driven Emission Color on GPU (stderr DEGRADED), attributes read only by a
  Light Path switch child on GPU.
* Not in this lane: the `prod_attributes` base-colour chain (Color Attribute -> Hue/Saturation <- Map
  Range <- Object Info Random) needs 10 VM slots (`VM_MAX_SLOTS` = 8): #993 (lane N2).

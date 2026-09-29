# pkg293 (#889) research note — per-hit lobe weights, Mix Shader programs, Fac vs Color

## Sources (all Apache-2.0, Blender `intern/cycles/kernel/svm/`)

- `closure.h` `svm_node_closure_bsdf` (Principled): metallic / transmission are read
  from the SVM stack per shading point and the diffuse / specular / glass closure
  weights derived there. Burley 2015 §3: `(1-m)(1-t)` diffuse, `(1-m)t` glass, metal `m`.
- `closure.h` `svm_node_mix_closure`: Mix Shader weight is `saturatef(fac)`, then the
  two branch closures are weighted `1-w` / `w`.
- `checker.h`: Fac = cell parity (1/0); Color = Color1 when Fac = 1 else Color2.
- `brick.h`: Fac = mortar factor; Color = mix(brick tint, mortar colour, Fac).
- `noisetex.h`: Color = (value, noise(p+off3), noise(p+off4)); Fac = value = Color.x.
- `magic.h`: Fac = average(Color).
- Wave / Gradient / Musgrave: Color is the Fac broadcast; Voronoi Distance is the
  addon's 0→1 colour lerp (Astroray loads these with colours 0/1).

## What Astroray does

1. **Per-hit lobe mix.** #876 (pkg292) and #933 (pkg295) already lowered opaque and
   partial-transmission Disney to one closure, and `gpu_disney_*` derives the lobe
   mix from the per-hit `closure.metallic/transmission` that the pkg219d override
   writes. Disney glass (constant transmission >= 0.999) still used the
   diffuse + dielectric split, with weights baked at upload and no metallic lobe.
   pkg293 routes it to the single closure when a Metallic or Transmission program
   exists (`DisneyPlugin::closureGraph`). The GPU kernel is unchanged. Principled was
   already monolithic.
2. **Mix Shader.** The addon lowers Mix(Principled, Principled) to one Principled
   with lerped parameters (`shader_blending.py`, existing approximation). pkg293
   composes per-texel scalar sockets as the op-VM chain
   `MixRGB(MIX, Fac, A, B)`, which saturates Fac like `svm_node_mix_closure`. This
   happens when a branch has a program or when Fac is textured. A lerp of Roughness
   is not a closure mix, so sharp and blurred highlights average. This is the same
   approximation class as before and is visible on the corpus MixShaderProg sphere.
3. **Fac vs Color.** The op-VM compiler reads the wired output name. Blender 5
   labels it `Factor`. Checker and Brick load a Fac variant. Noise Fac is broadcast
   as Color.x for colour consumers. Magic Fac is the average.

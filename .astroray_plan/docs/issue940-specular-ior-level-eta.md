# #940 — tilted area-lamp floor footprint = Principled specular_ior_level eta

Root cause: not the area lamp. The addon lowers Diffuse BSDF to Principled with
`specular_ior_level = 0`. Astroray scaled f0 to 0 but kept the specular layer's Fresnel
exponent / `L.ior` / layering-albedo IOR at `ior` (1.5). The generalized-Schlick term
`s = (F_real(cos, 1.5) - F0) / (1 - F0)` still rises to 1 at grazing, so a grazing camera
saw a mirror image of the lamp (tilted: sharp bright rectangle, 1.2-2.0x Cycles on the
floor) and the layer albedo dimmed the diffuse (downward lamp 0.82x).

Reference (Blender Cycles, Apache-2.0):
- `kernel/svm/closure.h` principled, "Apply IOR adjustment": `f0 = F0_from_ior(ior)`;
  if `specular_ior_level != 0.5`: `f0 *= 2 * level; eta = ior_from_F0(f0)` (inverted
  when `ior < 1`). Specular layer: `fresnel->exponent = -eta`, `bsdf->ior = eta`.
- `kernel/closure/bsdf_util.h` `ior_from_F0(f0) = (1 + sqrt f0) / (1 - sqrt f0)`,
  f0 clamped to [0, 0.99].

Fix: CPU `plugins/materials/principled.cpp` and GPU twin `include/astroray/gpu_materials.h`
derive `specEta` and use it for `sView`, `L.ior` and `ggxLayeringAlbedo`. Transmission
keeps `ior` (Cycles does the same).

Evidence: `astra_run/AK/ak-940/` (gate_table.md, gate_cycles_left_astroray_right.png,
principled_variants_{before,after}.png). Test: `tests/test_issue940_specular_ior_level_eta.py`.

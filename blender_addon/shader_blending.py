"""Helpers for Mix Shader / Add Shader material blending."""

from copy import deepcopy


def _clamp01(v):
    return max(0.0, min(1.0, float(v)))


def _lerp_float(a, b, fac):
    return (1.0 - fac) * float(a) + fac * float(b)


def _lerp_vec3(a, b, fac):
    return [_lerp_float(a[0], b[0], fac), _lerp_float(a[1], b[1], fac), _lerp_float(a[2], b[2], fac)]


def _blend_params(pa, pb, fac):
    """Lerp two Principled param dicts key-wise. Scalars lerp; 3-vectors
    (colours such as coat_tint / sheen_tint / subsurface_radius) lerp
    component-wise. A key set on only one side survives (blended against the
    other side's value, which falls back to its own)."""
    keys = set(pa.keys()) | set(pb.keys())
    out = {}
    for k in keys:
        va = pa.get(k)
        vb = pb.get(k)
        if isinstance(va, (list, tuple)) or isinstance(vb, (list, tuple)):
            va = va if isinstance(va, (list, tuple)) else vb
            vb = vb if isinstance(vb, (list, tuple)) else va
            out[k] = _lerp_vec3(va, vb, fac)
        else:
            out[k] = _lerp_float(va if va is not None else 0.0,
                                 vb if vb is not None else 0.0, fac)
    return out


def _normalized_principled(spec):
    out = deepcopy(spec)
    out.setdefault("kind", "principled")
    out.setdefault("base_color", [0.8, 0.8, 0.8])
    out.setdefault("params", {})
    out["params"].setdefault("metallic", 0.0)
    out["params"].setdefault("roughness", 0.5)
    out["params"].setdefault("transmission", 0.0)
    out["params"].setdefault("ior", 1.45)
    out["params"].setdefault("clearcoat", 0.0)
    out["params"].setdefault("clearcoat_gloss", 1.0)
    out["params"].setdefault("anisotropic", 0.0)
    out["params"].setdefault("sheen", 0.0)
    out["params"].setdefault("subsurface", 0.0)
    # pkg178 Stage 5: the native 'principled' routing reads native_params; carry
    # it through blending so a Mix/Add of Principled nodes still drives the native
    # material. native_gaps (pkg119-C report lines) are unioned.
    out.setdefault("native_params", {})
    out.setdefault("native_gaps", [])
    out.setdefault("emission_color", [0.0, 0.0, 0.0])
    out.setdefault("emission_strength", 0.0)
    return out


def blend_shader_specs(fac, a, b):
    """Mix Shader(fac, A, B) → blended shader spec."""
    fac = _clamp01(fac)
    if a is None:
        return deepcopy(b)
    if b is None:
        return deepcopy(a)

    ka = a.get("kind")
    kb = b.get("kind")

    if ka == "principled" and kb == "principled":
        pa = _normalized_principled(a)
        pb = _normalized_principled(b)
        keys = set(pa["params"].keys()) | set(pb["params"].keys())
        params = {k: _lerp_float(pa["params"].get(k, 0.0), pb["params"].get(k, 0.0), fac) for k in keys}
        return {
            "kind": "principled",
            "base_color": _lerp_vec3(pa["base_color"], pb["base_color"], fac),
            "params": params,
            "native_params": _blend_params(pa["native_params"], pb["native_params"], fac),
            "native_gaps": list(dict.fromkeys(pa["native_gaps"] + pb["native_gaps"])),
            "emission_color": _lerp_vec3(pa["emission_color"], pb["emission_color"], fac),
            "emission_strength": _lerp_float(pa["emission_strength"], pb["emission_strength"], fac),
        }

    if ka == "principled" and kb == "transparent":
        out = _normalized_principled(a)
        out["params"]["alpha"] = 1.0 - fac
        out["native_params"]["alpha"] = 1.0 - fac
        return out
    if ka == "transparent" and kb == "principled":
        out = _normalized_principled(b)
        out["params"]["alpha"] = fac
        out["native_params"]["alpha"] = fac
        return out

    if ka == "principled" and kb == "emission":
        out = _normalized_principled(a)
        out["emission_color"] = _lerp_vec3(out["emission_color"], b.get("base_color", [1, 1, 1]), fac)
        out["emission_strength"] = out.get("emission_strength", 0.0) + fac * float(b.get("emission_strength", 1.0))
        return out
    if ka == "emission" and kb == "principled":
        out = _normalized_principled(b)
        w = 1.0 - fac
        out["emission_color"] = _lerp_vec3(out["emission_color"], a.get("base_color", [1, 1, 1]), w)
        out["emission_strength"] = out.get("emission_strength", 0.0) + w * float(a.get("emission_strength", 1.0))
        return out

    # Unsupported: dominant shader (higher factor)
    return deepcopy(b if fac >= 0.5 else a)


def _pure_diffuse(spec):
    """True for a plain constant-colour Lambertian-equivalent Principled spec
    (no spec lobe, metal, transmission, texture, program or emission)."""
    if spec.get("kind") != "principled":
        return False
    p = spec.get("params", {})
    if (p.get("metallic", 0.0) or p.get("transmission", 0.0) or p.get("specular_ior_level", 0.5)
            or p.get("specular", 0.5) or p.get("roughness", 0.5) or p.get("alpha", 1.0) != 1.0
            or p.get("clearcoat", 0.0) or p.get("sheen", 0.0) or p.get("subsurface", 0.0)):
        return False
    if spec.get("emission_strength", 0.0):
        return False
    return not any(k in spec for k in ("base_color_texture", "scalar_programs", "native_params",
                                       "normal_texture", "bump_strength"))


def _add_emission(spec, color, strength):
    """Add `color * strength` radiance to a Principled spec's emission term."""
    out = _normalized_principled(spec)
    e0, s0 = out["emission_color"], float(out.get("emission_strength", 0.0))
    s1 = float(strength)
    total = s0 + s1
    if total > 0.0:
        out["emission_color"] = [(e0[i] * s0 + float(color[i]) * s1) / total for i in range(3)]
    out["emission_strength"] = total
    return out


def add_shader_specs(a, b):
    """Add Shader(A, B) -> additive shader spec. Cycles adds the closures
    (weights are not normalised): Emission folds into the other shader's emission
    radiance; two plain Diffuse closures fold into one with the summed albedo
    (exact, while it stays <= 1); every other pair becomes an {'kind': 'add'}
    spec the exporter lowers to a closure-sum material (#955)."""
    if a is None:
        return deepcopy(b)
    if b is None:
        return deepcopy(a)

    ka = a.get("kind")
    kb = b.get("kind")

    if ka == "principled" and kb == "emission":
        return _add_emission(a, b.get("base_color", [1, 1, 1]), b.get("emission_strength", 1.0))
    if ka == "emission" and kb == "principled":
        return _add_emission(b, a.get("base_color", [1, 1, 1]), a.get("emission_strength", 1.0))

    if ka == "emission" and kb == "emission":
        strength_a = float(a.get("emission_strength", 1.0))
        strength_b = float(b.get("emission_strength", 1.0))
        total = max(1e-8, strength_a + strength_b)
        return {
            "kind": "emission",
            "base_color": _lerp_vec3(a.get("base_color", [1, 1, 1]), b.get("base_color", [1, 1, 1]), strength_b / total),
            "emission_strength": strength_a + strength_b,
        }

    if _pure_diffuse(a) and _pure_diffuse(b):
        ca = a.get("base_color", [0.8, 0.8, 0.8])
        cb = b.get("base_color", [0.8, 0.8, 0.8])
        summed = [float(ca[i]) + float(cb[i]) for i in range(3)]
        if max(summed) <= 1.0:
            out = deepcopy(a)
            out["base_color"] = summed
            return out

    return {"kind": "add", "a": deepcopy(a), "b": deepcopy(b)}

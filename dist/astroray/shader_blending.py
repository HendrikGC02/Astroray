"""Helpers for Mix Shader / Add Shader material blending."""

from copy import deepcopy


def _clamp01(v):
    return max(0.0, min(1.0, float(v)))


def _lerp_float(a, b, fac):
    return (1.0 - fac) * float(a) + fac * float(b)


def _lerp_vec3(a, b, fac):
    return [_lerp_float(a[0], b[0], fac), _lerp_float(a[1], b[1], fac), _lerp_float(a[2], b[2], fac)]


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
            "emission_color": _lerp_vec3(pa["emission_color"], pb["emission_color"], fac),
            "emission_strength": _lerp_float(pa["emission_strength"], pb["emission_strength"], fac),
        }

    if ka == "principled" and kb == "transparent":
        out = _normalized_principled(a)
        out["params"]["alpha"] = 1.0 - fac
        return out
    if ka == "transparent" and kb == "principled":
        out = _normalized_principled(b)
        out["params"]["alpha"] = fac
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


def add_shader_specs(a, b):
    """Add Shader(A, B) → additive shader spec."""
    if a is None:
        return deepcopy(b)
    if b is None:
        return deepcopy(a)

    ka = a.get("kind")
    kb = b.get("kind")

    if ka == "principled" and kb == "emission":
        out = _normalized_principled(a)
        out["emission_color"] = _lerp_vec3(out["emission_color"], b.get("base_color", [1, 1, 1]), 0.5)
        out["emission_strength"] = out.get("emission_strength", 0.0) + float(b.get("emission_strength", 1.0))
        return out
    if ka == "emission" and kb == "principled":
        out = _normalized_principled(b)
        out["emission_color"] = _lerp_vec3(out["emission_color"], a.get("base_color", [1, 1, 1]), 0.5)
        out["emission_strength"] = out.get("emission_strength", 0.0) + float(a.get("emission_strength", 1.0))
        return out

    if ka == "emission" and kb == "emission":
        strength_a = float(a.get("emission_strength", 1.0))
        strength_b = float(b.get("emission_strength", 1.0))
        total = max(1e-8, strength_a + strength_b)
        return {
            "kind": "emission",
            "base_color": _lerp_vec3(a.get("base_color", [1, 1, 1]), b.get("base_color", [1, 1, 1]), strength_b / total),
            "emission_strength": strength_a + strength_b,
        }

    # Unsupported additive combo: fallback to first
    return deepcopy(a)

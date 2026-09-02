#pragma once
// ============================================================================
// pkg219b — Bounded per-texel shader op-VM (host + device shared core).
//
// A minimal bytecode VM that evaluates the scalar/colour node chains that live
// DOWNSTREAM of a texture in a Blender material (Color Ramp, Mix, Math, Map
// Range) per shading point, instead of the addon constant-folding them to a
// single grey value (memory `addon-constant-folds-shader-graph`).
//
// Architecture ported from the Cycles SVM kernel (intern/cycles/kernel/svm/*,
// Apache-2.0); per-opcode math cited inline below and enumerated in
// .astroray_plan/docs/pkg219c-blender-node-opcode-semantics.md. The two
// deliberate divergences from Cycles SVM (research note
// pkg219b-op-vm-core-research.md):
//   1. STATIC compile-time stack bound (Cycles' 255-float dynamic stack spills
//      the REG:254 wavefront shade kernel). Graphs exceeding the bound are
//      rejected host-side -> constant-fold + visible degradation, never grey.
//   2. The VM does NOT fetch textures; the caller pre-samples the material's
//      input textures into `inputs[]`. Keeps `svm_eval` a pure HD function that
//      is BYTE-IDENTICAL on CPU and GPU -> parity by construction.
//
// SPDX-License-Identifier: Apache-2.0 (opcode math derived from Cycles).
// ============================================================================

#include "astroray/gpu_types.h"   // GVec3, HD

namespace astroray {
namespace svm {

// ---- static bounds (see research note §"Static limits") --------------------
constexpr int VM_MAX_INSTR      = 32;
constexpr int VM_MAX_SLOTS      = 8;    // GVec3 register file (scalars use .x)
constexpr int VM_MAX_CONST      = 16;   // vec3 constant pool
constexpr int VM_MAX_TEX        = 2;    // pre-sampled input textures
constexpr int RAMP_TABLE_SIZE   = 256;  // baked ramp resolution (Cycles: 256)
constexpr int VM_MAX_RAMPS      = 2;
// pkg219d — scalar BSDF-parameter program slots. A fixed small K per material;
// each slot binds an op-VM program (+ its own source image) that per-texel drives
// one scalar Disney input. Order is load-bearing (host upload, GPU shade loop,
// and CPU DisneyPlugin all index by it): {0:ROUGHNESS,1:METALLIC,2:TRANSMISSION,3:IOR}.
constexpr int VM_SCALAR_SLOTS   = 4;
enum ScalarSlot : int { SCALAR_ROUGHNESS = 0, SCALAR_METALLIC = 1,
                        SCALAR_TRANSMISSION = 2, SCALAR_IOR = 3 };

enum OpCode : unsigned char {
    OP_END        = 0,
    OP_LOAD_TEX   = 1,  // reg[out] = inputs[imm]                    (input plumbing)
    OP_LOAD_CONST = 2,  // reg[out] = consts[imm]        Cycles svm/value.h
    OP_MATH       = 3,  // reg[out].x = math(imm, a.x, b.x, c.x)  svm/math_util.h
    OP_MIX        = 4,  // reg[out] = mix(imm, fac=a.x, c1=b, c2=c) svm/color_util.h
    OP_RAMP       = 5,  // reg[out] = ramp[imm].lookup(a.x)       svm/ramp.h
    OP_MAP_RANGE  = 6,  // reg[out].x = map_range(imm, a.x,b.x,c.x,d.x,e.x) svm/map_range.h
    // pkg219c — opcode coverage fill-out (per-texel colour/scalar ops).
    OP_HSV        = 7,  // reg[out] = hsv(hue=a.x,sat=b.x,val=c.x,fac=d.x,col=e) svm/hsv.h
    OP_INVERT     = 8,  // reg[out] = invert(fac=a.x, col=b)      svm/invert.h
    OP_GAMMA      = 9,  // reg[out] = gamma(col=a, gamma=b.x)     svm/math_util.h
    OP_BRIGHT_CONTRAST = 10, // reg[out] = bc(col=a, bright=b.x, contrast=c.x) svm/color_util.h
    OP_SEP_COLOR  = 11, // reg[out].xyz = separate(col=a, imm=space*4+comp).broadcast svm/color_util.h
    OP_COMBINE_COLOR = 12, // reg[out] = combine(r=a.x,g=b.x,b=c.x, imm=space) svm/color_util.h
    OP_RGB_TO_BW  = 13, // reg[out] = luma(col=a).broadcast        svm/convert.h
};

// Colour-space enum for Separate/Combine Color (Cycles NodeCombSepColorType).
// pkg219c ships RGB + HSV (HSL deferred).
enum ColorSpace : unsigned char { CS_RGB = 0, CS_HSV = 1 };

// NodeMathType subset (Cycles svm/types.h). pkg219b ships the common subset;
// pkg219c fills the rest. Values are the addon compiler's own enum, NOT the
// Cycles numeric enum (the compiler maps Blender op strings -> these).
enum MathOp : unsigned char {
    MATH_ADD = 0, MATH_SUB, MATH_MUL, MATH_DIV, MATH_MULADD, MATH_POW,
    MATH_SQRT, MATH_ABS, MATH_MIN, MATH_MAX, MATH_FLOOR, MATH_CEIL,
    MATH_FRACT, MATH_MOD, MATH_SNAP, MATH_LESS, MATH_GREATER, MATH_SIGN,
};

// NodeMix blend subset (Cycles svm/color_util.h svm_mix).
enum MixOp : unsigned char {
    MIX_BLEND = 0, MIX_ADD, MIX_MUL, MIX_SUB, MIX_SCREEN, MIX_DIFF,
    MIX_DARKEN, MIX_LIGHTEN, MIX_OVERLAY,
};

// NodeMapRangeType subset (Cycles svm/map_range.h).
enum MapRangeOp : unsigned char {
    MR_LINEAR = 0, MR_STEPPED, MR_SMOOTHSTEP, MR_SMOOTHERSTEP,
};

// One VM instruction (6 bytes, padded to 8). Slot indices are into the
// register file; `imm` is the op-sub-enum or the const/tex/ramp index.
struct Instr {
    unsigned char op;
    unsigned char out;   // dest slot
    unsigned char a;     // src slot 0
    unsigned char b;     // src slot 1
    unsigned char c;     // src slot 2 (unused ops read a harmless slot)
    unsigned char d;     // src slot 3 (Map Range to_min)
    unsigned char e;     // src slot 4 (Map Range to_max)
    unsigned char imm;   // sub-op enum OR const/tex/ramp index
};

// A complete program (POD, trivially copyable to a device global buffer).
struct ShaderVMProgram {
    int    numInstr = 0;
    int    outSlot  = 0;              // slot holding the final RGB result
    int    numTex   = 0;             // how many input textures the caller samples
    int    numRamps = 0;
    Instr  code[VM_MAX_INSTR];
    GVec3  consts[VM_MAX_CONST];
    // Baked ramp tables, RGB only (base-colour scope). Row r = ramp r.
    GVec3  ramp[VM_MAX_RAMPS][RAMP_TABLE_SIZE];
};

// ---- HD safe-math helpers (Cycles svm/../util/math_base.h) ------------------
HD inline float svm_clampf(float x, float lo, float hi) {
    return x < lo ? lo : (x > hi ? hi : x);
}
HD inline float svm_saturatef(float x) { return svm_clampf(x, 0.f, 1.f); }
HD inline float svm_safe_divf(float a, float b) { return b != 0.f ? a / b : 0.f; }
HD inline float svm_safe_powf(float a, float b) {
    if (a < 0.f && b != floorf(b)) return 0.f;
    return powf(a, b);
}

// ---- Color Ramp baked-table lookup (Cycles svm/ramp.h rgb_ramp_lookup) ------
HD inline GVec3 svm_ramp_lookup(const GVec3* table, float fac) {
    float f = svm_saturatef(fac) * (float)(RAMP_TABLE_SIZE - 1);
    int   i = (int)f;
    if (i < 0) i = 0;
    if (i > RAMP_TABLE_SIZE - 1) i = RAMP_TABLE_SIZE - 1;
    float t = f - (float)i;
    GVec3 c = table[i];
    if (t > 0.f && i < RAMP_TABLE_SIZE - 1) {
        c = c * (1.f - t) + table[i + 1] * t;
    }
    return c;
}

// ---- scalar Math (Cycles svm/math_util.h svm_math) -------------------------
HD inline float svm_math(unsigned char op, float a, float b, float c) {
    switch (op) {
        case MATH_ADD:    return a + b;
        case MATH_SUB:    return a - b;
        case MATH_MUL:    return a * b;
        case MATH_DIV:    return svm_safe_divf(a, b);
        case MATH_MULADD: return a * b + c;
        case MATH_POW:    return svm_safe_powf(a, b);
        case MATH_SQRT:   return sqrtf(a > 0.f ? a : 0.f);
        case MATH_ABS:    return fabsf(a);
        case MATH_MIN:    return a < b ? a : b;
        case MATH_MAX:    return a > b ? a : b;
        case MATH_FLOOR:  return floorf(a);
        case MATH_CEIL:   return ceilf(a);
        case MATH_FRACT:  return a - floorf(a);
        case MATH_MOD:    return b != 0.f ? fmodf(a, b) : 0.f;
        case MATH_SNAP:   return b != 0.f ? floorf(svm_safe_divf(a, b)) * b : 0.f;
        case MATH_LESS:   return a < b ? 1.f : 0.f;
        case MATH_GREATER:return a > b ? 1.f : 0.f;
        case MATH_SIGN:   return a > 0.f ? 1.f : (a < 0.f ? -1.f : 0.f);
        default:          return a;
    }
}

// ---- colour Mix (Cycles svm/color_util.h svm_mix) --------------------------
HD inline GVec3 svm_mix(unsigned char op, float t, GVec3 c1, GVec3 c2) {
    // factor clamp mirrors legacy NODE_MIX (svm_mix_clamped_factor).
    t = svm_saturatef(t);
    float mt = 1.f - t;
    switch (op) {
        case MIX_BLEND:   return c1 * mt + c2 * t;
        case MIX_ADD:     return c1 + c2 * t;
        case MIX_MUL:     return c1 * (GVec3(mt) + c2 * t);
        case MIX_SUB:     return c1 - c2 * t;
        case MIX_SCREEN: {
            GVec3 one(1.f);
            return one - (GVec3(mt) + (one - c2) * t) * (one - c1);
        }
        case MIX_DIFF: {
            GVec3 d(fabsf(c1.x - c2.x), fabsf(c1.y - c2.y), fabsf(c1.z - c2.z));
            return c1 * mt + d * t;
        }
        case MIX_DARKEN:
            return c1 * mt + GVec3(c1.x<c2.x?c1.x:c2.x, c1.y<c2.y?c1.y:c2.y, c1.z<c2.z?c1.z:c2.z) * t;
        case MIX_LIGHTEN:
            return c1 * mt + GVec3(c1.x>c2.x?c1.x:c2.x, c1.y>c2.y?c1.y:c2.y, c1.z>c2.z?c1.z:c2.z) * t;
        case MIX_OVERLAY: {
            GVec3 o;
            for (int i = 0; i < 3; ++i) {
                float x = c1[i], y = c2[i];
                float ov = x < 0.5f ? 2.f*x*y : 1.f - 2.f*(1.f-x)*(1.f-y);
                o[i] = x * mt + ov * t;   // legacy MixRGB folds fac after blend
            }
            return o;
        }
        default:          return c1 * mt + c2 * t;
    }
}

// ---- scalar Map Range (Cycles svm/map_range.h svm_node_map_range) -----------
HD inline float svm_map_range(unsigned char op, float value, float from_min,
                              float from_max, float to_min, float to_max) {
    float denom = from_max - from_min;
    if (denom == 0.f) return to_min;
    float factor = (value - from_min) / denom;
    switch (op) {
        case MR_SMOOTHSTEP: {
            float f = svm_saturatef(factor);
            factor = (3.f - 2.f*f) * f * f;
            break;
        }
        case MR_SMOOTHERSTEP: {
            float f = svm_saturatef(factor);
            factor = f*f*f*(f*(f*6.f - 15.f) + 10.f);
            break;
        }
        default: break;  // MR_LINEAR / MR_STEPPED (steps handled host-side)
    }
    return to_min + factor * (to_max - to_min);
}

// ---- HSV colour-space conversions (Cycles util/color.h) --------------------
HD inline float svm_fractf(float x) { return x - floorf(x); }

HD inline GVec3 svm_rgb_to_hsv(GVec3 rgb) {
    float cmax = rgb.x > rgb.y ? (rgb.x > rgb.z ? rgb.x : rgb.z)
                               : (rgb.y > rgb.z ? rgb.y : rgb.z);
    float cmin = rgb.x < rgb.y ? (rgb.x < rgb.z ? rgb.x : rgb.z)
                               : (rgb.y < rgb.z ? rgb.y : rgb.z);
    float cdelta = cmax - cmin;
    float v = cmax;
    float s, h;
    if (cmax != 0.f) s = cdelta / cmax; else { s = 0.f; h = 0.f; }
    if (s != 0.f) {
        GVec3 c = (GVec3(cmax) - rgb) / cdelta;
        if (rgb.x == cmax)      h = c.z - c.y;
        else if (rgb.y == cmax) h = 2.f + c.x - c.z;
        else                    h = 4.f + c.y - c.x;
        h /= 6.f;
        if (h < 0.f) h += 1.f;
    } else {
        h = 0.f;
    }
    return GVec3(h, s, v);
}

HD inline GVec3 svm_hsv_to_rgb(GVec3 hsv) {
    float h = hsv.x, s = hsv.y, v = hsv.z;
    if (s != 0.f) {
        if (h == 1.f) h = 0.f;
        h *= 6.f;
        float i = floorf(h);
        float f = h - i;
        float p = v * (1.f - s);
        float q = v * (1.f - (s * f));
        float t = v * (1.f - (s * (1.f - f)));
        if (i == 0.f)      return GVec3(v, t, p);
        else if (i == 1.f) return GVec3(q, v, p);
        else if (i == 2.f) return GVec3(p, v, t);
        else if (i == 3.f) return GVec3(p, q, v);
        else if (i == 4.f) return GVec3(t, p, v);
        else               return GVec3(v, p, q);
    }
    return GVec3(v, v, v);
}

// ---- Hue/Saturation/Value node (Cycles svm/hsv.h svm_node_hsv) --------------
HD inline GVec3 svm_hsv(float hue, float sat, float val, float fac, GVec3 color) {
    GVec3 c = svm_rgb_to_hsv(color);
    c.x = svm_fractf(c.x + hue + 0.5f);
    c.y = svm_saturatef(c.y * sat);
    c.z = c.z * val;
    GVec3 out = svm_hsv_to_rgb(c);
    out = out * fac + color * (1.f - fac);
    // Clamp negatives from over-saturation (Cycles svm_node_hsv).
    out.x = out.x > 0.f ? out.x : 0.f;
    out.y = out.y > 0.f ? out.y : 0.f;
    out.z = out.z > 0.f ? out.z : 0.f;
    return out;
}

// ---- Invert node (Cycles svm/invert.h) -------------------------------------
// interp(color, 1-color, fac) = (1-fac)*color + fac*(1-color), per channel.
HD inline GVec3 svm_invert(float fac, GVec3 color) {
    return color * (1.f - fac) + (GVec3(1.f) - color) * fac;
}

// ---- Gamma node (Cycles svm/math_util.h svm_math_gamma_color) ---------------
HD inline GVec3 svm_gamma(GVec3 color, float gamma) {
    if (gamma == 0.f) return GVec3(1.f, 1.f, 1.f);
    if (color.x > 0.f) color.x = powf(color.x, gamma);
    if (color.y > 0.f) color.y = powf(color.y, gamma);
    if (color.z > 0.f) color.z = powf(color.z, gamma);
    return color;
}

// ---- Bright/Contrast node (Cycles svm/color_util.h svm_brightness_contrast) -
HD inline GVec3 svm_bright_contrast(GVec3 color, float bright, float contrast) {
    float a = 1.f + contrast;
    float b = bright - contrast * 0.5f;
    GVec3 o;
    o.x = a * color.x + b; o.x = o.x > 0.f ? o.x : 0.f;
    o.y = a * color.y + b; o.y = o.y > 0.f ? o.y : 0.f;
    o.z = a * color.z + b; o.z = o.z > 0.f ? o.z : 0.f;
    return o;
}

// ---- RGB to BW (Cycles svm/convert.h; Rec.709 luma) ------------------------
HD inline float svm_rgb_to_bw(GVec3 c) {
    return c.x * 0.2126729f + c.y * 0.7151522f + c.z * 0.0721750f;
}

// ============================================================================
// The evaluator. Pure, HD, byte-identical CPU<->GPU. `inputs` holds the
// pre-sampled child-texture RGBs. Returns the program's output slot RGB.
// A bounded fixed-size register file (VM_MAX_SLOTS GVec3) — small enough that
// the <true> GPU shade specialization pays only a few slots of local memory,
// while the <false> fleet specialization compiles this out entirely.
// ============================================================================
HD inline GVec3 svm_eval(const ShaderVMProgram& p, const GVec3* inputs) {
    GVec3 reg[VM_MAX_SLOTS];
    int n = p.numInstr < VM_MAX_INSTR ? p.numInstr : VM_MAX_INSTR;
    for (int pc = 0; pc < n; ++pc) {
        const Instr& in = p.code[pc];
        switch (in.op) {
            case OP_LOAD_TEX:
                reg[in.out] = inputs[in.imm < VM_MAX_TEX ? in.imm : 0];
                break;
            case OP_LOAD_CONST:
                reg[in.out] = p.consts[in.imm < VM_MAX_CONST ? in.imm : 0];
                break;
            case OP_MATH: {
                float r = svm_math(in.imm, reg[in.a].x, reg[in.b].x, reg[in.c].x);
                reg[in.out] = GVec3(r);
                break;
            }
            case OP_MIX:
                reg[in.out] = svm_mix(in.imm, reg[in.a].x, reg[in.b], reg[in.c]);
                break;
            case OP_RAMP:
                reg[in.out] = svm_ramp_lookup(p.ramp[in.imm < VM_MAX_RAMPS ? in.imm : 0],
                                              reg[in.a].x);
                break;
            case OP_MAP_RANGE: {
                float r = svm_map_range(in.imm, reg[in.a].x, reg[in.b].x,
                                        reg[in.c].x, reg[in.d].x, reg[in.e].x);
                reg[in.out] = GVec3(r);
                break;
            }
            case OP_HSV:
                reg[in.out] = svm_hsv(reg[in.a].x, reg[in.b].x, reg[in.c].x,
                                      reg[in.d].x, reg[in.e]);
                break;
            case OP_INVERT:
                reg[in.out] = svm_invert(reg[in.a].x, reg[in.b]);
                break;
            case OP_GAMMA:
                reg[in.out] = svm_gamma(reg[in.a], reg[in.b].x);
                break;
            case OP_BRIGHT_CONTRAST:
                reg[in.out] = svm_bright_contrast(reg[in.a], reg[in.b].x, reg[in.c].x);
                break;
            case OP_SEP_COLOR: {
                // imm = space*4 + component. RGB is identity; HSV converts.
                unsigned char space = in.imm >> 2;
                unsigned char comp  = in.imm & 3u;
                GVec3 conv = (space == CS_HSV) ? svm_rgb_to_hsv(reg[in.a]) : reg[in.a];
                reg[in.out] = GVec3(conv[comp < 3 ? comp : 0]);
                break;
            }
            case OP_COMBINE_COLOR: {
                GVec3 v(reg[in.a].x, reg[in.b].x, reg[in.c].x);
                reg[in.out] = (in.imm == CS_HSV) ? svm_hsv_to_rgb(v) : v;
                break;
            }
            case OP_RGB_TO_BW:
                reg[in.out] = GVec3(svm_rgb_to_bw(reg[in.a]));
                break;
            case OP_END:
            default:
                pc = n;  // halt
                break;
        }
    }
    return reg[p.outSlot < VM_MAX_SLOTS ? p.outSlot : 0];
}

}  // namespace svm
}  // namespace astroray

// pkg219b — wavefront op-VM binding, published ONCE per frame into a
// __constant__ symbol (setWavefrontProgramBinding), mirroring the pkg186/197/
// 198/199 pattern so the register-saturated shade kernel reads the program array
// from constant memory rather than growing its per-launch signature. The
// programs themselves live in a device GLOBAL buffer (each ShaderVMProgram is
// several KB; too large for constant memory) pointed to here. `matProgId[mat]`
// == -1 for every non-program material, so the <HasProgram=false> shade
// specialization (the entire fleet) compiles the VM out and never reads the
// symbol — byte-identical to main.
struct GWavefrontProgramBinding {
    const astroray::svm::ShaderVMProgram* programs;  // device global array
    const int*                            matProgId; // per-material index (-1=none)
    // pkg219d — scalar BSDF-param programs. Both indexed [mat*VM_SCALAR_SLOTS + slot]
    // (slots per astroray::svm::ScalarSlot). matScalarProgId[..] = index into the
    // SAME `programs` array (-1 = no program on that slot); matScalarTexId[..] =
    // index into c_wfTexBinding.textures for that slot's OWN source image (a scalar
    // program feeds its own map, NOT the base-colour texel). Read ONLY inside the
    // shade kernel's `if constexpr (HasProgram)` block, so the <false> fleet never
    // touches these and stays byte-identical.
    const int*                            matScalarProgId;
    const int*                            matScalarTexId;
};

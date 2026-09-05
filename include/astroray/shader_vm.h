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
    // pkg230 — utility opcodes.
    OP_CLAMP      = 14, // reg[out].x = clamp(imm=type, v=a.x, min=b.x, max=c.x) svm/clamp
    // pkg230 Phase 2 — vector opcodes (Cycles svm/math_util.h + svm/vector_rotate.h).
    OP_VEC_MATH   = 15, // reg[out] = vec_math(imm=op, a, b, c, scale=d.x)  svm/math_util.h
    OP_VEC_ROTATE = 16, // reg[out] = vec_rotate(imm=type|invert, a=vec, b=center,
                        //                      c=axis|rotation, d=angle) svm/vector_rotate.h
};

// pkg230 — Clamp node type (Cycles NodeClampType, svm_clamp / node_clamp.osl).
enum ClampType : unsigned char { CLAMP_MINMAX = 0, CLAMP_RANGE = 1 };

// pkg230 — clamp FLAG bits packed into the free high bits of an op's `imm`
// (the sub-op enums are small: MathOp <= 17 uses bits 0..6; MixOp <= 8 uses
// bits 0..3). OP_MATH honours use_clamp; OP_MIX honours clamp_result (the mix
// factor is already saturated in svm_mix = Blender's default clamp_factor).
// The addon compiler sets these bits; both sides MUST agree.
static const unsigned char SVM_MATH_CLAMP        = 0x80u; // OP_MATH: clamp result to [0,1]
static const unsigned char SVM_MIX_CLAMP_RESULT  = 0x80u; // OP_MIX:  clamp result to [0,1]
// pkg230 Phase 2 — negative-polarity Mix factor flag (bit 6 = SKIP the factor
// saturation svm_mix otherwise applies). Existing/default bytecode keeps the bit
// clear and saturates the factor EXACTLY as before (legacy MixRGB + modern Mix
// clamp_factor=true); modern clamp_factor=false sets it. The existing OP_MIX
// sub-op mask `imm & 0x3F` already excludes this bit (and bit 7 stays CLAMP_RESULT).
static const unsigned char SVM_MIX_UNCLAMP_FACTOR = 0x40u;
// pkg230 Phase 2 — Vector Rotate invert bit (packed in OP_VEC_ROTATE imm bit 3,
// above the low 3 bits carrying VecRotateType). Set = invert the rotation.
static const unsigned char VEC_ROTATE_INVERT = 0x08u;

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

// Vector Math — 30 operations from Cycles svm/math_util.h. Dot/Distance/Length
// write a scalar result broadcast across xyz. Values are the addon
// compiler's own enum (the compiler maps Blender `operation` strings -> these).
// Adapted from Cycles intern/cycles/kernel/svm/math_util.h, Apache-2.0, commit
// adfe2921d5f3c0fe699149bcd9bc347543bbd82e.
enum VecMathOp : unsigned char {
    VECMATH_ADD = 0, VECMATH_SUBTRACT, VECMATH_MULTIPLY, VECMATH_DIVIDE,
    VECMATH_CROSS_PRODUCT, VECMATH_PROJECT, VECMATH_REFLECT, VECMATH_REFRACT,
    VECMATH_FACEFORWARD, VECMATH_MULTIPLY_ADD, VECMATH_DOT_PRODUCT,
    VECMATH_DISTANCE, VECMATH_LENGTH, VECMATH_SCALE, VECMATH_NORMALIZE,
    VECMATH_SNAP, VECMATH_ROUND, VECMATH_FLOOR, VECMATH_CEIL, VECMATH_MODULO,
    VECMATH_WRAP, VECMATH_FRACTION, VECMATH_ABSOLUTE, VECMATH_POWER,
    VECMATH_SIGN, VECMATH_MINIMUM, VECMATH_MAXIMUM, VECMATH_SINE,
    VECMATH_COSINE, VECMATH_TANGENT,
};

// NodeVectorRotateType (Cycles svm/vector_rotate.h) — 5 modes. The op's `imm`
// low 3 bits carry the type; bit 3 (0x08) is the invert flag.
enum VecRotateType : unsigned char {
    VECROT_AXIS_ANGLE = 0, VECROT_X_AXIS, VECROT_Y_AXIS, VECROT_Z_AXIS,
    VECROT_EULER_XYZ,
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
HD inline GVec3 svm_mix(unsigned char op, float t, GVec3 c1, GVec3 c2,
                        bool unclamp_factor = false) {
    // factor saturation is the DEFAULT (legacy MixRGB + modern clamp_factor=true);
    // SVM_MIX_UNCLAMP_FACTOR (pkg230 P2) skips it for modern clamp_factor=false.
    if (!unclamp_factor) t = svm_saturatef(t);
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

// ---- Clamp node (pkg230) ---------------------------------------------------
// Cycles svm_clamp (svm/svm_clamp.h) uses clamp(v,lo,hi) = min(max(v,lo),hi).
// MINMAX passes min/max literally (so min>max collapses to max, matching
// Cycles); RANGE first orders the bounds. NOTE: this deliberately does NOT use
// svm_clampf's `v<lo?lo:...` form, which diverges from Cycles when lo>hi.
HD inline float svm_clamp(unsigned char type, float v, float lo, float hi) {
    if (type == CLAMP_RANGE && lo > hi) { float t = lo; lo = hi; hi = t; }
    float mx = v > lo ? v : lo;   // max(v, lo)
    return mx < hi ? mx : hi;     // min(max(v,lo), hi)
}

// ---- Vector Math (pkg230 P2) — Cycles svm/math_util.h svm_vector_math -------
// Copyright 2011-2022 Blender Foundation. Component-wise helpers mirror Cycles util/math_float3.h + util/math_base.h
// (Apache-2.0, commit adfe2921d5f3c0fe699149bcd9bc347543bbd82e).
HD inline GVec3 svm_safe_normalize(GVec3 a) {
    float t = a.length();
    return t != 0.f ? a * (1.f / t) : a;   // zero vector stays itself (Cycles safe_normalize)
}
HD inline GVec3 svm_safe_divide3(GVec3 a, GVec3 b) {
    return GVec3(b.x != 0.f ? a.x / b.x : 0.f,
                 b.y != 0.f ? a.y / b.y : 0.f,
                 b.z != 0.f ? a.z / b.z : 0.f);
}
HD inline GVec3 svm_floor3(GVec3 a) { return GVec3(floorf(a.x), floorf(a.y), floorf(a.z)); }
HD inline GVec3 svm_ceil3(GVec3 a)  { return GVec3(ceilf(a.x), ceilf(a.y), ceilf(a.z)); }
HD inline GVec3 svm_fabs3(GVec3 a)  { return GVec3(fabsf(a.x), fabsf(a.y), fabsf(a.z)); }
HD inline GVec3 svm_sin3(GVec3 a)   { return GVec3(sinf(a.x), sinf(a.y), sinf(a.z)); }
HD inline GVec3 svm_cos3(GVec3 a)   { return GVec3(cosf(a.x), cosf(a.y), cosf(a.z)); }
HD inline GVec3 svm_tan3(GVec3 a)   { return GVec3(tanf(a.x), tanf(a.y), tanf(a.z)); }
HD inline GVec3 svm_safe_fmod3(GVec3 a, GVec3 b) {
    return GVec3(b.x != 0.f ? fmodf(a.x, b.x) : 0.f,
                 b.y != 0.f ? fmodf(a.y, b.y) : 0.f,
                 b.z != 0.f ? fmodf(a.z, b.z) : 0.f);
}
HD inline float svm_vec_wrapf(float value, float mx, float mn) {
    float range = mx - mn;
    return range != 0.f ? value - range * floorf((value - mn) / range) : mn;
}
HD inline GVec3 svm_wrap3(GVec3 value, GVec3 mx, GVec3 mn) {
    return GVec3(svm_vec_wrapf(value.x, mx.x, mn.x),
                 svm_vec_wrapf(value.y, mx.y, mn.y),
                 svm_vec_wrapf(value.z, mx.z, mn.z));
}
HD inline float svm_vec_safe_powf(float a, float b) {
    if (b == 0.f) return 1.f; // Cycles compatible_powf includes 0^0.
    if (a == 0.f || (a < 0.f && b != floorf(b))) return 0.f;
    // CUDA powf does not accept a negative base, even for integer exponents.
    if (a < 0.f) return fmodf(b, 2.f) == 0.f ? powf(-a, b) : -powf(-a, b);
    return powf(a, b);
}
HD inline GVec3 svm_safe_pow3(GVec3 a, GVec3 b) {
    return GVec3(svm_vec_safe_powf(a.x, b.x), svm_vec_safe_powf(a.y, b.y),
                 svm_vec_safe_powf(a.z, b.z));
}
HD inline GVec3 svm_sign3(GVec3 a) {
    // Cycles compatible_sign: +1 / -1 / 0 (zero maps to zero).
    float sx = a.x == 0.f ? 0.f : (a.x < 0.f ? -1.f : 1.f);
    float sy = a.y == 0.f ? 0.f : (a.y < 0.f ? -1.f : 1.f);
    float sz = a.z == 0.f ? 0.f : (a.z < 0.f ? -1.f : 1.f);
    return GVec3(sx, sy, sz);
}
HD inline GVec3 svm_project(GVec3 v, GVec3 v_proj) {
    float len2 = v_proj.length2();
    return len2 != 0.f ? v_proj * (v.dot(v_proj) / len2) : GVec3(0.f);
}
HD inline GVec3 svm_reflect(GVec3 incident, GVec3 unit_normal) {
    return incident - unit_normal * (2.f * incident.dot(unit_normal));
}
HD inline GVec3 svm_refract(GVec3 incident, GVec3 normal, float eta) {
    float d = normal.dot(incident);
    float k = 1.f - eta * eta * (1.f - d * d);
    if (k < 0.f) return GVec3(0.f);   // total internal reflection
    return incident * eta - normal * (eta * d + sqrtf(k));
}

HD inline GVec3 svm_vec_math(unsigned char op, GVec3 a, GVec3 b, GVec3 c, float param1) {
    switch (op) {
        case VECMATH_ADD:           return a + b;
        case VECMATH_SUBTRACT:      return a - b;
        case VECMATH_MULTIPLY:      return a * b;
        case VECMATH_DIVIDE:        return svm_safe_divide3(a, b);
        case VECMATH_CROSS_PRODUCT: return a.cross(b);
        case VECMATH_PROJECT:       return svm_project(a, b);
        case VECMATH_REFLECT:       return svm_reflect(a, svm_safe_normalize(b));
        case VECMATH_REFRACT:       return svm_refract(a, svm_safe_normalize(b), param1);
        case VECMATH_FACEFORWARD:   return c.dot(b) < 0.f ? a : -a;
        case VECMATH_MULTIPLY_ADD:  return a * b + c;
        case VECMATH_DOT_PRODUCT:   return GVec3(a.dot(b));
        case VECMATH_DISTANCE:      return GVec3((a - b).length());
        case VECMATH_LENGTH:        return GVec3(a.length());
        case VECMATH_SCALE:         return a * param1;
        case VECMATH_NORMALIZE:     return svm_safe_normalize(a);
        case VECMATH_SNAP:          return svm_floor3(svm_safe_divide3(a, b)) * b;
        case VECMATH_ROUND:         return svm_floor3(a + GVec3(0.5f));
        case VECMATH_FLOOR:         return svm_floor3(a);
        case VECMATH_CEIL:          return svm_ceil3(a);
        case VECMATH_MODULO:        return svm_safe_fmod3(a, b);
        case VECMATH_WRAP:          return svm_wrap3(a, b, c);
        case VECMATH_FRACTION:      return a - svm_floor3(a);
        case VECMATH_ABSOLUTE:      return svm_fabs3(a);
        case VECMATH_POWER:         return svm_safe_pow3(a, b);
        case VECMATH_SIGN:          return svm_sign3(a);
        case VECMATH_MINIMUM:       return gvec3_min(a, b);
        case VECMATH_MAXIMUM:       return gvec3_max(a, b);
        case VECMATH_SINE:          return svm_sin3(a);
        case VECMATH_COSINE:        return svm_cos3(a);
        case VECMATH_TANGENT:       return svm_tan3(a);
        default:                    return GVec3(0.f);
    }
}

// ---- Vector Rotate (pkg230 P2) — Cycles svm/vector_rotate.h -----------------
// Copyright 2011-2022 Blender Foundation. Adapted from
// Cycles intern/cycles/kernel/svm/vector_rotate.h and
// util/transform.h (Apache-2.0, commit adfe2921d5f3c0fe699149bcd9bc347543bbd82e).
HD inline GVec3 svm_rotate_around_axis(GVec3 p, GVec3 axis, float angle) {
    float ct = cosf(angle), st = sinf(angle), u = 1.f - ct;
    GVec3 r;
    r.x = (ct + u * axis.x * axis.x) * p.x
        + (u * axis.x * axis.y - axis.z * st) * p.y
        + (u * axis.x * axis.z + axis.y * st) * p.z;
    r.y = (u * axis.x * axis.y + axis.z * st) * p.x
        + (ct + u * axis.y * axis.y) * p.y
        + (u * axis.y * axis.z - axis.x * st) * p.z;
    r.z = (u * axis.x * axis.z - axis.y * st) * p.x
        + (u * axis.y * axis.z + axis.x * st) * p.y
        + (ct + u * axis.z * axis.z) * p.z;
    return r;
}

HD inline GVec3 svm_vec_rotate(unsigned char type, bool invert, GVec3 vector,
                               GVec3 center, GVec3 axis_or_rot, float angle) {
    if (type == VECROT_EULER_XYZ) {
        // Cycles euler_to_transform (XYZ order) + transform_direction; INVERT uses
        // transform_direction_transposed (== the rotation inverse), NOT negating
        // the same-order angles.
        GVec3 e = axis_or_rot;
        float cx = cosf(e.x), cy = cosf(e.y), cz = cosf(e.z);
        float sx = sinf(e.x), sy = sinf(e.y), sz = sinf(e.z);
        GVec3 v = vector - center;
        if (invert) {
            GVec3 c0(cy * cz, cy * sz, -sy);
            GVec3 c1(sy * sx * cz - cx * sz, sy * sx * sz + cx * cz, cy * sx);
            GVec3 c2(sy * cx * cz + sx * sz, sy * cx * sz - sx * cz, cy * cx);
            return GVec3(c0.dot(v), c1.dot(v), c2.dot(v)) + center;
        }
        GVec3 r0(cy * cz, sy * sx * cz - cx * sz, sy * cx * cz + sx * sz);
        GVec3 r1(cy * sz, sy * sx * sz + cx * cz, sy * cx * sz - sx * cz);
        GVec3 r2(-sy, cy * sx, cy * cx);
        return GVec3(r0.dot(v), r1.dot(v), r2.dot(v)) + center;
    }
    // Axis-angle / single-axis: INVERT negates the angle (not a transpose).
    GVec3 axis = axis_or_rot;
    float axis_len = axis.length();
    if (type == VECROT_X_AXIS)      { axis = GVec3(1.f, 0.f, 0.f); axis_len = 1.f; }
    else if (type == VECROT_Y_AXIS) { axis = GVec3(0.f, 1.f, 0.f); axis_len = 1.f; }
    else if (type == VECROT_Z_AXIS) { axis = GVec3(0.f, 0.f, 1.f); axis_len = 1.f; }
    if (axis_len == 0.f) return vector;   // zero axis -> input unchanged
    float a = invert ? -angle : angle;
    return svm_rotate_around_axis(vector - center, axis / axis_len, a) + center;
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
                // low 7 bits = MathOp; bit 7 = use_clamp (pkg230)
                float r = svm_math(in.imm & 0x7Fu, reg[in.a].x, reg[in.b].x, reg[in.c].x);
                if (in.imm & SVM_MATH_CLAMP) r = svm_saturatef(r);
                reg[in.out] = GVec3(r);
                break;
            }
            case OP_MIX: {
                // low 6 bits = MixOp; bit 6 = unclamp_factor (pkg230 P2); bit 7 =
                // clamp_result (pkg230). The factor is saturated inside svm_mix
                // unless the unclamp bit is set (modern Mix clamp_factor=false).
                GVec3 m = svm_mix(in.imm & 0x3Fu, reg[in.a].x, reg[in.b], reg[in.c],
                                  (in.imm & SVM_MIX_UNCLAMP_FACTOR) != 0);
                if (in.imm & SVM_MIX_CLAMP_RESULT)
                    m = GVec3(svm_saturatef(m.x), svm_saturatef(m.y), svm_saturatef(m.z));
                reg[in.out] = m;
                break;
            }
            case OP_CLAMP:
                reg[in.out] = GVec3(svm_clamp(in.imm, reg[in.a].x, reg[in.b].x,
                                              reg[in.c].x));
                break;
            case OP_VEC_MATH:
                reg[in.out] = svm_vec_math(in.imm, reg[in.a], reg[in.b], reg[in.c],
                                           reg[in.d].x);
                break;
            case OP_VEC_ROTATE: {
                unsigned char type = in.imm & 7u;
                bool invert = (in.imm & 8u) != 0;
                reg[in.out] = svm_vec_rotate(type, invert, reg[in.a], reg[in.b],
                                             reg[in.c], reg[in.d].x);
                break;
            }
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

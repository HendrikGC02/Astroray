#pragma once
// ============================================================================
// pkg314 — dynamic value programs: graph-program format + shared interpreter.
//
// Plan of record: .astroray_plan/docs/shader-graph-architecture-2026-10-03.md
// (option B, Phases 1-2). The addon compiles a node chain into a typed IR
// (blender_addon/shader_graph_ir.py: CSE, last-use slot reuse) and serialises it
// as GRAPH_IR_VERSION programs. A program is a descriptor of 32-bit offsets into
// immutable arenas (instructions, constants, tables, texture references); slots
// are 16-bit and live in caller-provided scratch (CPU: a per-call buffer; GPU:
// batched global scratch of the dedicated graph-evaluation kernel,
// src/gpu/wavefront/stage_graph_eval.cu). Budgets are checked host-side
// (validateGraphProgram) and fail loudly, never truncate.
//
// Opcodes 0..17 are the op-VM opcodes and run the SAME per-op functions as
// svm_eval (shader_vm.h svm_math / svm_mix / ...; Cycles SVM, Apache-2.0), so
// opcode semantics are single-source. New here: texture instructions that sample
// in-program (a service supplies the sample), the UV geometry input, and
// Float/RGB/Vector curve LUTs (Cycles kernel/svm/ramp.h svm_node_curve(s),
// Apache-2.0; .astroray_plan/docs/pkg314-curves-research.md).
//
// SPDX-License-Identifier: Apache-2.0 (opcode math derived from Cycles).
// ============================================================================

#include <cstdint>
#include "astroray/shader_vm.h"

#ifndef __CUDACC_RTC__
#include <string>
#include <vector>
#endif

namespace astroray {
namespace sgraph {

constexpr int GRAPH_IR_VERSION = 1;

// ---- checked budgets (mirrored in blender_addon/shader_graph_ir.py) ---------
constexpr int GRAPH_MAX_SLOTS      = 255;
constexpr int GRAPH_MAX_INSTR      = 4096;
constexpr int GRAPH_MAX_CONST      = 4096;
constexpr int GRAPH_MAX_TABLES     = 64;
constexpr int GRAPH_MAX_TABLE_SIZE = 4096;
constexpr int GRAPH_MAX_TEX        = 32;

// Per-material program slots: the four scalar BSDF inputs (svm::ScalarSlot order)
// and the base colour. The GPU output buffer holds 4 scalars + RGB per hit.
constexpr int GRAPH_MAT_SLOTS = 5;
constexpr int GRAPH_SLOT_BASE_COLOR = 4;
constexpr int GRAPH_OUT_FLOATS = 7;   // [0..3] scalars, [4..6] base colour

enum GraphOp : unsigned char {
    // 0..17: astroray::svm::OpCode (OP_LOAD_TEX is not emitted; OP_RAMP reads a table)
    GOP_TEX_NATIVE = 32,  // reg[dst] = texture[res] at its own coordinate contract
    GOP_TEX_COORD  = 33,  // reg[dst] = image[res] sampled at uv = reg[a].xy
    GOP_GEOM       = 34,  // reg[dst] = geometry input `sub` (GEOM_UV)
    GOP_CURVE      = 35,  // reg[dst] = curve(table[res], fac = reg[a].x, in = reg[b]), sub = mode
};

enum GeomInput : unsigned char { GEOM_UV = 0 };
enum CurveMode : unsigned char { CURVE_FLOAT = 0, CURVE_RGB = 1 };

// 20 bytes. Slot fields index the program's scratch; `res` is a program-relative
// resource index (constant / table / texture).
struct GraphInstr {
    uint8_t  op;
    uint8_t  sub;    // op-VM imm byte (sub-op + flag bits) or graph sub-op
    uint16_t dst;
    uint16_t a, b, c, d, e;
    uint16_t pad;
    uint32_t res;
};

struct GraphTable {
    uint32_t offset;     // into the table-data arena (GVec3 entries)
    uint32_t size;       // >= 2 entries
    float    minX;       // Cycles curve min_x (ramps: 0)
    float    rangeX;     // Cycles curve max_x - min_x (ramps: 1)
    uint32_t extrapolate;
    uint32_t pad;
};

struct GraphProgramDesc {
    uint32_t instrOffset, numInstr;
    uint32_t constOffset, numConst;
    uint32_t tableOffset, numTables;   // into the GraphTable arena
    uint32_t texOffset,   numTex;      // into the texture-reference arena
    uint32_t numSlots,    outSlot;
};

// ---- Cycles float/rgb_ramp_lookup (kernel/svm/ramp.h, Apache-2.0) ----------
// One lookup for Color Ramp (extrapolate = false, [0,1]; identical to
// svm::svm_ramp_lookup at 256 entries) and the curve LUTs.
HD inline GVec3 svm_table_lookup(const GVec3* t, int size, float f, bool extrapolate) {
    if (extrapolate && (f < 0.0f || f > 1.0f)) {
        GVec3 t0, dy;
        if (f < 0.0f) {
            t0 = t[0];
            dy = t0 - t[1];
            f = -f;
        } else {
            t0 = t[size - 1];
            dy = t0 - t[size - 2];
            f = f - 1.0f;
        }
        return t0 + dy * (f * (float)(size - 1));
    }
    f = svm::svm_saturatef(f) * (float)(size - 1);
    int i = (int)f;
    if (i < 0) i = 0;
    if (i > size - 1) i = size - 1;
    const float tt = f - (float)i;
    GVec3 a = t[i];
    if (tt > 0.0f) a = a * (1.0f - tt) + t[i + 1] * tt;
    return a;
}

// Cycles svm_node_curve (Float Curve) / svm_node_curves (RGB + Vector Curves).
HD inline GVec3 svm_curve(unsigned char mode, const GraphTable& tab, const GVec3* data,
                          float fac, GVec3 in) {
    const GVec3* t = data + tab.offset;
    const int n = (int)tab.size;
    const bool ex = tab.extrapolate != 0;
    if (mode == CURVE_FLOAT) {
        const float v = svm_table_lookup(t, n, (in.x - tab.minX) / tab.rangeX, ex).x;
        return GVec3((1.0f - fac) * in.x + fac * v);
    }
    GVec3 c;
    for (int k = 0; k < 3; ++k)
        c[k] = svm_table_lookup(t, n, (in[k] - tab.minX) / tab.rangeX, ex)[k];
    return in * (1.0f - fac) + c * fac;
}

// Pure op-VM opcodes over operand VALUES: the same functions and flag decoding as
// svm::svm_eval (shader_vm.h). Returns false for an opcode that is not pure.
HD inline bool svm_apply_pure(unsigned char op, unsigned char imm, GVec3 a, GVec3 b,
                              GVec3 c, GVec3 d, GVec3 e, const svm::SvmShading& sh,
                              GVec3& out) {
    using namespace astroray::svm;
    switch (op) {
        case OP_MATH: {
            float r = svm_math(imm & 0x7Fu, a.x, b.x, c.x);
            if (imm & SVM_MATH_CLAMP) r = svm_saturatef(r);
            out = GVec3(r);
            return true;
        }
        case OP_MIX: {
            GVec3 m = svm_mix(imm & 0x3Fu, a.x, b, c, (imm & SVM_MIX_UNCLAMP_FACTOR) != 0);
            if (imm & SVM_MIX_CLAMP_RESULT)
                m = GVec3(svm_saturatef(m.x), svm_saturatef(m.y), svm_saturatef(m.z));
            out = m;
            return true;
        }
        case OP_CLAMP:        out = GVec3(svm_clamp(imm, a.x, b.x, c.x)); return true;
        case OP_VEC_MATH:     out = svm_vec_math(imm, a, b, c, d.x); return true;
        case OP_VEC_ROTATE:   out = svm_vec_rotate(imm & 7u, (imm & 8u) != 0, a, b, c, d.x);
                              return true;
        case OP_MAP_RANGE:    out = GVec3(svm_map_range(imm, a.x, b.x, c.x, d.x, e.x));
                              return true;
        case OP_HSV:          out = svm_hsv(a.x, b.x, c.x, d.x, e); return true;
        case OP_INVERT:       out = svm_invert(a.x, b); return true;
        case OP_GAMMA:        out = svm_gamma(a, b.x); return true;
        case OP_BRIGHT_CONTRAST: out = svm_bright_contrast(a, b.x, c.x); return true;
        case OP_SEP_COLOR: {
            const unsigned char space = imm >> 2, comp = imm & 3u;
            GVec3 conv = (space == CS_HSV) ? svm_rgb_to_hsv(a) : a;
            out = GVec3(conv[comp < 3 ? comp : 0]);
            return true;
        }
        case OP_COMBINE_COLOR: {
            GVec3 v(a.x, b.x, c.x);
            out = (imm == CS_HSV) ? svm_hsv_to_rgb(v) : v;
            return true;
        }
        case OP_RGB_TO_BW:    out = GVec3(svm_rgb_to_bw(a)); return true;
        case OP_SHADING:      out = GVec3(svm_shading(imm, a.x, sh)); return true;
        default:              return false;
    }
}

// Read-only view of the arenas a program indexes.
struct GraphArenas {
    const GraphInstr*       instrs;
    const GVec3*            consts;
    const GraphTable*       tables;
    const GVec3*            tableData;
};

// The interpreter. `Regs` is the slot scratch: reg s lives at regs[s * stride]
// (CPU stride 1; GPU stride = batch width, so a warp's accesses coalesce). `Svc`
// supplies texture samples and geometry inputs:
//   bool tex_native(uint32_t tex, GVec3& out)              — tex = absolute ref index
//   bool tex_coord (uint32_t tex, const GVec3& c, GVec3& out)
//   bool geom      (unsigned char which, GVec3& out)
//   const svm::SvmShading& shading()
// A service miss (e.g. a UV-less hit on the GPU) aborts with false; the caller
// keeps the material's constant value, as the op-VM path does.
template <class Svc>
HD inline bool graph_eval(const GraphProgramDesc& p, const GraphArenas& ar,
                          GVec3* regs, int stride, Svc& svc, GVec3& result) {
    for (uint32_t pc = 0; pc < p.numInstr; ++pc) {
        const GraphInstr in = ar.instrs[p.instrOffset + pc];
        GVec3 r;
        switch (in.op) {
            case svm::OP_LOAD_CONST:
                r = ar.consts[p.constOffset + in.res];
                break;
            case svm::OP_RAMP: {
                const GraphTable tab = ar.tables[p.tableOffset + in.res];
                r = svm_table_lookup(ar.tableData + tab.offset, (int)tab.size,
                                     regs[in.a * stride].x, false);
                break;
            }
            case GOP_CURVE:
                r = svm_curve(in.sub, ar.tables[p.tableOffset + in.res], ar.tableData,
                              regs[in.a * stride].x, regs[in.b * stride]);
                break;
            case GOP_TEX_NATIVE:
                if (!svc.tex_native(p.texOffset + in.res, r)) return false;
                break;
            case GOP_TEX_COORD:
                if (!svc.tex_coord(p.texOffset + in.res, regs[in.a * stride], r)) return false;
                break;
            case GOP_GEOM:
                if (!svc.geom(in.sub, r)) return false;
                break;
            default: {
                // Operands read before the write: dst may alias an operand slot
                // (the IR allocator reuses a slot at its last use).
                const GVec3 a = regs[in.a * stride], b = regs[in.b * stride],
                            c = regs[in.c * stride], d = regs[in.d * stride],
                            e = regs[in.e * stride];
                if (!svm_apply_pure(in.op, in.sub, a, b, c, d, e, svc.shading(), r))
                    return false;   // unknown opcode (validated host-side)
                break;
            }
        }
        regs[in.dst * stride] = r;
    }
    result = regs[p.outSlot * stride];
    return true;
}

#ifndef __CUDACC_RTC__
// Operand fields an instruction actually reads (bit 0 = a .. bit 4 = e). Mirrors
// blender_addon/shader_graph_ir.py operand_fields and the per-op decoding of
// svm_apply_pure / graph_eval; the validator uses it for def-before-use checks.
inline unsigned graphOperandReads(unsigned char op, unsigned char sub) {
    using namespace astroray::svm;
    constexpr unsigned A = 1, B = 2, C = 4, D = 8, E = 16;
    switch (op) {
        case OP_MATH:    return A | B | (((sub & 0x7Fu) == MATH_MULADD) ? C : 0u);
        case OP_MIX: case OP_CLAMP: case OP_BRIGHT_CONTRAST: case OP_COMBINE_COLOR:
            return A | B | C;
        case OP_MAP_RANGE: case OP_HSV: return A | B | C | D | E;
        case OP_INVERT: case OP_GAMMA: case GOP_CURVE: return A | B;
        case OP_RAMP: case OP_SEP_COLOR: case OP_RGB_TO_BW: case GOP_TEX_COORD: return A;
        case OP_VEC_MATH: {
            unsigned m = A;
            switch (sub) {  // VecMathOp operands (Cycles svm_vector_math)
                case VECMATH_ADD: case VECMATH_SUBTRACT: case VECMATH_MULTIPLY:
                case VECMATH_DIVIDE: case VECMATH_CROSS_PRODUCT: case VECMATH_PROJECT:
                case VECMATH_REFLECT: case VECMATH_DOT_PRODUCT: case VECMATH_DISTANCE:
                case VECMATH_SNAP: case VECMATH_MODULO: case VECMATH_POWER:
                case VECMATH_MINIMUM: case VECMATH_MAXIMUM:
                    m |= B; break;
                case VECMATH_REFRACT: m |= B | D; break;
                case VECMATH_FACEFORWARD: case VECMATH_MULTIPLY_ADD: case VECMATH_WRAP:
                    m |= B | C; break;
                case VECMATH_SCALE: m |= D; break;
                default: break;
            }
            return m;
        }
        case OP_VEC_ROTATE: {
            const unsigned t = sub & 7u;
            return A | B | ((t == VECROT_AXIS_ANGLE || t == VECROT_EULER_XYZ) ? C : 0u) |
                   ((t != VECROT_EULER_XYZ) ? D : 0u);
        }
        case OP_SHADING:
            return (sub == SH_LAYER_FRESNEL || sub == SH_LAYER_FACING || sub == SH_FRESNEL) ? A : 0u;
        default: return 0u;   // constants, texture samples, geometry inputs
    }
}

// ---- host-side program (one per GraphProgramTexture; arenas start at 0) -----
struct GraphProgramData {
    GraphProgramDesc        desc{};
    std::vector<GraphInstr> instrs;
    std::vector<GVec3>      consts;
    std::vector<GraphTable> tables;
    std::vector<GVec3>      tableData;
};

// Returns "" when the program is well-formed and within budget, else the reason.
// Every operand / resource index is checked, so the interpreter never reads out
// of bounds; exceeding a budget is an explicit failure, never a truncation.
inline std::string validateGraphProgram(const GraphProgramData& g, int numTex) {
    const GraphProgramDesc& d = g.desc;
    if (d.numSlots < 1 || d.numSlots > (uint32_t)GRAPH_MAX_SLOTS)
        return "slot count " + std::to_string(d.numSlots) + " outside [1, " +
               std::to_string(GRAPH_MAX_SLOTS) + "]";
    if (d.numInstr != g.instrs.size() || d.numInstr > (uint32_t)GRAPH_MAX_INSTR)
        return "instruction count " + std::to_string(g.instrs.size()) + " over budget";
    if (d.numConst != g.consts.size() || d.numConst > (uint32_t)GRAPH_MAX_CONST)
        return "constant count over budget";
    if (d.numTables != g.tables.size() || d.numTables > (uint32_t)GRAPH_MAX_TABLES)
        return "table count over budget";
    if (numTex < 0 || numTex > GRAPH_MAX_TEX || d.numTex != (uint32_t)numTex)
        return "texture count over budget";
    if (d.outSlot >= d.numSlots) return "output slot out of range";
    if (d.numInstr == 0) return "empty program";
    for (const GraphTable& t : g.tables) {
        if (t.size < 2 || t.size > (uint32_t)GRAPH_MAX_TABLE_SIZE ||
            (size_t)t.offset + t.size > g.tableData.size())
            return "table out of range";
        if (!(t.rangeX != 0.0f)) return "table with zero x range";
    }
    for (size_t i = 0; i < g.instrs.size(); ++i) {
        const GraphInstr& in = g.instrs[i];
        const std::string at = " at instruction " + std::to_string(i);
        if (in.dst >= d.numSlots || in.a >= d.numSlots || in.b >= d.numSlots ||
            in.c >= d.numSlots || in.d >= d.numSlots || in.e >= d.numSlots)
            return "slot index out of range" + at;
        switch (in.op) {
            case svm::OP_LOAD_CONST:
                if (in.res >= d.numConst) return "constant index out of range" + at;
                break;
            case svm::OP_RAMP: case GOP_CURVE:
                if (in.res >= d.numTables) return "table index out of range" + at;
                if (in.op == GOP_CURVE && in.sub > CURVE_RGB) return "bad curve mode" + at;
                break;
            case GOP_TEX_NATIVE: case GOP_TEX_COORD:
                if (in.res >= d.numTex) return "texture index out of range" + at;
                break;
            case GOP_GEOM:
                if (in.sub != GEOM_UV) return "bad geometry input" + at;
                break;
            case svm::OP_MATH: case svm::OP_MIX: case svm::OP_CLAMP: case svm::OP_VEC_MATH:
            case svm::OP_VEC_ROTATE: case svm::OP_MAP_RANGE: case svm::OP_HSV:
            case svm::OP_INVERT: case svm::OP_GAMMA: case svm::OP_BRIGHT_CONTRAST:
            case svm::OP_SEP_COLOR: case svm::OP_COMBINE_COLOR: case svm::OP_RGB_TO_BW:
            case svm::OP_SHADING:
                break;
            default:
                return "unknown opcode " + std::to_string(in.op) + at;
        }
    }
    // Dataflow: every operand an instruction reads, and the output, must have
    // been written earlier in the program (no read of uninitialised CPU registers
    // or of the GPU kernel's persistent scratch).
    std::vector<unsigned char> defined(d.numSlots, 0);
    for (size_t i = 0; i < g.instrs.size(); ++i) {
        const GraphInstr& in = g.instrs[i];
        const unsigned reads = graphOperandReads(in.op, in.sub);
        const uint16_t ops[5] = {in.a, in.b, in.c, in.d, in.e};
        for (int f = 0; f < 5; ++f)
            if ((reads >> f) & 1u && !defined[ops[f]])
                return "read of an undefined slot at instruction " + std::to_string(i);
        defined[in.dst] = 1;
    }
    if (!defined[d.outSlot]) return "output slot never written";
    return "";
}
#endif

}  // namespace sgraph
}  // namespace astroray

// pkg314 — device binding of the dedicated graph-evaluation kernel
// (src/gpu/wavefront/stage_graph_eval.cu, __constant__ c_wfGraphBinding), set once
// per frame when the scene carries graph programs. The shade kernel never reads
// it: it reads the kernel's per-path outputs through GWavefrontProgramBinding
// (matGraphProg / graphOut), only in the <HasProgram=true> variants.
struct GWavefrontGraphBinding {
    const astroray::sgraph::GraphInstr*       instrs;
    const GVec3*                              consts;
    const astroray::sgraph::GraphTable*       tables;
    const GVec3*                              tableData;
    const int*                                texRefs;      // -> c_wfTexBinding.textures
    const astroray::sgraph::GraphProgramDesc* programs;
    const int*                                matGraphProg; // [mat*GRAPH_MAT_SLOTS+slot], -1 none
    float*                                    out;          // [k*outStride + pathIdx]
    int                                       outStride;
    GVec3*                                    scratch;      // [slot*batch + thread]
    int                                       batch;        // threads of the eval launch
};

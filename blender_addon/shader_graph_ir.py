"""pkg314 — typed shader-graph IR and dynamic value programs (architecture Phases 1-2).

Plan of record: .astroray_plan/docs/shader-graph-architecture-2026-10-03.md (option B).

The IR reuses the op-VM node handlers in shader_vm_compiler.py: `IRBuilder` exposes
the same builder interface (alloc_slot / emit / push_const / push_tex / add_ramp /
add_input / release), but `alloc_slot` returns an unbounded SSA value id instead of
a register. After the handlers have walked the chain, the IR is optimised (common
subexpression elimination, dead-code elimination) and registers are assigned by a
linear scan that frees a register after its last use. The result is a graph
program (format version GRAPH_IR_VERSION, include/astroray/shader_graph.h):
instructions with 16-bit slots and 32-bit resource indices, constants, tables
(Color Ramp and curve LUTs) and texture references, plus per-program stats.

Texture leaves become texture instructions sampled inside the program:
  * OP_TEX_NATIVE k   — input k at its own coordinate contract (the texture is
    loaded with its own coordinates + Mapping, as if wired straight to a socket);
  * OP_TEX_COORD k, c — image k sampled at the computed coordinate c (uv = c.xy),
    used when the image's Vector chain is non-affine (a warp the per-texture
    Mapping cannot express); the coordinate chain is compiled into the program
    from OP_GEOM UV.
Budgets mirror shader_graph.h; exceeding one raises VMCompileError (the addon
reports DEGRADED), never truncates.

Opcode / enum values MUST match include/astroray/shader_graph.h.
"""

try:
    from . import shader_vm_compiler as svm
except ImportError:  # unit tests import the module top-level
    import shader_vm_compiler as svm

GRAPH_IR_VERSION = 1

# Graph-only opcodes (shared op-VM opcodes 0..17 keep their numbers).
OP_TEX_NATIVE = 32
OP_TEX_COORD = 33
OP_GEOM = 34
OP_CURVE = 35

GEOM_UV = 0

CURVE_FLOAT = 0   # Float Curve: scalar LUT
CURVE_RGB = 1     # RGB / Vector Curves: channel k of the LUT at relpos[k]

# Checked budgets (shader_graph.h GRAPH_MAX_*).
GRAPH_MAX_SLOTS = 255
GRAPH_MAX_INSTR = 4096
GRAPH_MAX_CONST = 4096
GRAPH_MAX_TABLES = 64
GRAPH_MAX_TABLE_SIZE = 4096
GRAPH_MAX_TEX = 32

# Instructions whose `imm` is a resource index (-> `res`); every other op's imm is
# its sub-op/flag byte (-> `sub`).
_RES_OPS = {svm.OP_LOAD_CONST: 'const', svm.OP_LOAD_TEX: 'tex', svm.OP_RAMP: 'table'}

_VECMATH_USE_B = {svm.VEC_MATH_OPS[k] for k in svm._VECMATH_USE_B}
_VECMATH_USE_C = {svm.VEC_MATH_OPS[k] for k in svm._VECMATH_USE_C}
_VECMATH_USE_SCALE = {svm.VEC_MATH_OPS[k] for k in svm._VECMATH_USE_SCALE}
_VECMATH_SCALAR = {svm.VEC_MATH_OPS[k] for k in ('DOT_PRODUCT', 'DISTANCE', 'LENGTH')}
_MATH_MULADD = svm.MATH_OPS['MULTIPLY_ADD']


def operand_fields(op, sub):
    """The operand fields an instruction actually reads (exact liveness).

    The op-VM handlers pass a harmless 0 for unused operands; those must not
    extend a value's lifetime, so reads are decoded per opcode exactly as the
    evaluators decode them (include/astroray/shader_vm.h svm_eval)."""
    if op in (svm.OP_LOAD_CONST, svm.OP_LOAD_TEX, OP_TEX_NATIVE, OP_GEOM):
        return ()
    if op == svm.OP_MATH:
        return ('a', 'b', 'c') if (sub & 0x7F) == _MATH_MULADD else ('a', 'b')
    if op in (svm.OP_MAP_RANGE, svm.OP_HSV):
        return ('a', 'b', 'c', 'd', 'e')
    if op in (svm.OP_MIX, svm.OP_BRIGHT_CONTRAST, svm.OP_COMBINE_COLOR, svm.OP_CLAMP):
        return ('a', 'b', 'c')
    if op in (svm.OP_INVERT, svm.OP_GAMMA, OP_CURVE):
        return ('a', 'b')
    if op in (svm.OP_RAMP, svm.OP_SEP_COLOR, svm.OP_RGB_TO_BW, OP_TEX_COORD):
        return ('a',)
    if op == svm.OP_VEC_MATH:
        f = ['a']
        if sub in _VECMATH_USE_B:
            f.append('b')
        if sub in _VECMATH_USE_C:
            f.append('c')
        if sub in _VECMATH_USE_SCALE:
            f.append('d')
        return tuple(f)
    if op == svm.OP_VEC_ROTATE:
        rtype = sub & 7
        f = ['a', 'b']
        if rtype in (svm.VEC_ROTATE_TYPES['AXIS_ANGLE'], svm.VEC_ROTATE_TYPES['EULER_XYZ']):
            f.append('c')
        if rtype != svm.VEC_ROTATE_TYPES['EULER_XYZ']:
            f.append('d')
        return tuple(f)
    if op == svm.OP_SHADING:
        # Only Layer Weight / Fresnel read an argument; Backfacing and the #991
        # Light Path outputs (sub >= 4, lane at-n1) take none.
        return ('a',) if sub in (svm.SH_LAYER_FRESNEL, svm.SH_LAYER_FACING,
                                 svm.SH_FRESNEL) else ()
    raise svm.VMCompileError("graph IR: unknown opcode %d" % op)


def result_type(op, sub):
    """IR value type of an instruction's result: 'float' (broadcast scalar),
    'vector', 'color' or 'any' (a constant: the consumer decides)."""
    if op in (svm.OP_MATH, svm.OP_MAP_RANGE, svm.OP_CLAMP, svm.OP_RGB_TO_BW,
              svm.OP_SEP_COLOR, svm.OP_SHADING):
        return 'float'
    if op == OP_CURVE:
        return 'float' if sub == CURVE_FLOAT else 'color'
    if op == svm.OP_VEC_MATH:
        return 'float' if sub in _VECMATH_SCALAR else 'vector'
    if op in (svm.OP_VEC_ROTATE, OP_GEOM):
        return 'vector'
    if op == svm.OP_LOAD_CONST:
        return 'any'
    return 'color'


class IRInstr:
    __slots__ = ('op', 'dst', 'a', 'b', 'c', 'd', 'e', 'sub', 'res')

    def __init__(self, op, dst, a, b, c, d, e, sub, res):
        self.op, self.dst, self.sub, self.res = op, dst, sub, res
        self.a, self.b, self.c, self.d, self.e = a, b, c, d, e

    def reads(self):
        return [getattr(self, f) for f in operand_fields(self.op, self.sub)]


class IRBuilder:
    """Builder interface of shader_vm_compiler.ProgramBuilder over SSA values."""

    supports_curves = True
    max_depth = 64

    def __init__(self):
        self.instrs = []
        self.consts = []            # (r, g, b) tuples, deduplicated by value
        self._const_idx = {}
        self.tables = []            # dicts: data [(r,g,b)], min_x, range_x, extrapolate
        self.inputs = []            # texture nodes, OP_TEX_* order
        self.input_variants = []
        self.input_kinds = []       # 'native' | 'coord'
        self._next = 0
        self.per_hit = False
        # Handler-interface fields (coordinate-program mode is not routed here).
        self.coord_mode = False
        self.coord_sockets = []
        self.memo = {}
        self.free_slots = []
        self.consumers = {}

    # -- builder interface used by the op-VM handlers -------------------------
    def alloc_slot(self):
        v = self._next
        self._next += 1
        return v

    def release(self, *slots):
        pass  # lifetimes come from the last-use scan, not the handlers

    def emit(self, op, out, a=0, b=0, c=0, d=0, e=0, imm=0):
        kind = _RES_OPS.get(op)
        sub, res = (0, imm) if kind else (imm, 0)
        if op == svm.OP_LOAD_TEX:   # op-VM input load == native texture sample
            op = OP_TEX_NATIVE
        self.instrs.append(IRInstr(op, out, a, b, c, d, e, sub, res))

    def emit_res(self, op, out, a=0, b=0, sub=0, res=0):
        self.instrs.append(IRInstr(op, out, a, b, 0, 0, 0, sub, res))

    def add_const(self, rgb):
        key = (float(rgb[0]), float(rgb[1]), float(rgb[2]))
        idx = self._const_idx.get(key)
        if idx is None:
            idx = self._const_idx[key] = len(self.consts)
            self.consts.append(key)
        return idx

    def add_ramp(self, table):
        return self.add_table(table, 0.0, 1.0, False)

    def add_table(self, table, min_x, range_x, extrapolate):
        data = [(float(c[0]), float(c[1]), float(c[2])) for c in table]
        key = (tuple(data), float(min_x), float(range_x), bool(extrapolate))
        for i, t in enumerate(self.tables):
            if t['key'] == key:
                return i
        self.tables.append({'key': key, 'data': data, 'min_x': float(min_x),
                            'range_x': float(range_x), 'extrapolate': bool(extrapolate)})
        return len(self.tables) - 1

    def add_input(self, tex_node, variant=None, kind='native'):
        for i, n in enumerate(self.inputs):
            if (n is tex_node and self.input_variants[i] == variant
                    and self.input_kinds[i] == kind):
                return i
        self.inputs.append(tex_node)
        self.input_variants.append(variant)
        self.input_kinds.append(kind)
        return len(self.inputs) - 1

    def push_const(self, rgb):
        s = self.alloc_slot()
        self.emit(svm.OP_LOAD_CONST, s, imm=self.add_const(rgb))
        return s

    def push_tex(self, tex_node, variant=None):
        vec = svm._get_input(tex_node, 'Vector')
        if (svm._is_image_texture(tex_node) and vec is not None
                and getattr(vec, 'is_linked', False) and not svm._coord_chain_affine(vec)):
            # A warped image coordinate: compile the chain, sample at the result.
            coord = svm.compile_socket(vec, self, 1)
            s = self.alloc_slot()
            self.emit_res(OP_TEX_COORD, s, a=coord,
                          res=self.add_input(tex_node, variant, 'coord'))
            return s
        s = self.alloc_slot()
        self.emit_res(OP_TEX_NATIVE, s, res=self.add_input(tex_node, variant, 'native'))
        return s

    def geom_input(self, node, out_name):
        """Coordinate sources inside a compiled image-coordinate chain."""
        ntype = getattr(node, 'type', None)
        if ntype == 'UVMAP':
            if getattr(node, 'uv_map', '') or getattr(node, 'from_instancer', False):
                raise svm.VMCompileError("UV Map node with a named/instancer layer is "
                                         "unsupported in a graph program coordinate")
        elif out_name != 'UV':
            raise svm.VMCompileError("Texture Coordinate '%s' is unsupported in a graph "
                                     "program image coordinate (only UV)" % out_name)
        s = self.alloc_slot()
        self.emit_res(OP_GEOM, s, sub=GEOM_UV)
        return s

    def curve(self, mode, fac_slot, value_slot, table, min_x, range_x, extrapolate):
        s = self.alloc_slot()
        self.emit_res(OP_CURVE, s, a=fac_slot, b=value_slot, sub=mode,
                      res=self.add_table(table, min_x, range_x, extrapolate))
        return s


# ---- optimisation + register allocation -------------------------------------
def _cse_dce(instrs, out):
    """Common-subexpression elimination + dead-code elimination.

    Every op is pure (texture reads included: same input, same hit), so two
    instructions with the same opcode, sub-op, resource and (canonical) operands
    compute the same value. Returns (instructions, canonical output id)."""
    canon = {}
    seen = {}
    kept = []
    for ins in instrs:
        fields = operand_fields(ins.op, ins.sub)
        for f in fields:
            v = getattr(ins, f)
            setattr(ins, f, canon.get(v, v))
        key = (ins.op, ins.sub, ins.res) + tuple(getattr(ins, f) for f in fields)
        prev = seen.get(key)
        if prev is not None:
            canon[ins.dst] = prev
            continue
        seen[key] = ins.dst
        kept.append(ins)
    out = canon.get(out, out)
    live = {out}
    result = []
    for ins in reversed(kept):
        if ins.dst in live:
            result.append(ins)
            live.update(ins.reads())
    result.reverse()
    return result, out


def allocate(instrs, out):
    """Linear-scan slot assignment with release at last use.

    A destination may reuse a slot freed by one of its own operands at the same
    instruction: the interpreters read every operand before writing the result.
    Returns (renamed instructions, output slot, peak live slots)."""
    last = {}
    for i, ins in enumerate(instrs):
        for v in ins.reads():
            last[v] = i
    last[out] = len(instrs)
    slot_of = {}
    free = []
    peak = 0
    renamed = []
    for i, ins in enumerate(instrs):
        reads = ins.reads()
        new = IRInstr(ins.op, 0, 0, 0, 0, 0, 0, ins.sub, ins.res)
        for f in operand_fields(ins.op, ins.sub):
            setattr(new, f, slot_of[getattr(ins, f)])
        for v in sorted(set(reads)):
            if last[v] == i:
                free.append(slot_of[v])
        if free:
            free.sort()
            s = free.pop(0)
        else:
            s = peak
            peak += 1
        slot_of[ins.dst] = s
        new.dst = s
        renamed.append(new)
    return renamed, slot_of[out], peak


def finalize(builder, out, check_budgets=True):
    """Optimise + allocate the builder's IR; return the program dict."""
    pre = len(builder.instrs)
    instrs, out = _cse_dce(builder.instrs, out)
    instrs, out_slot, peak = allocate(instrs, out)
    num_slots = max(peak, 1)
    types = {}
    for ins in instrs:
        t = result_type(ins.op, ins.sub)
        types[t] = types.get(t, 0) + 1
    stats = {
        'version': GRAPH_IR_VERSION,
        'instr_pre_opt': pre,
        'instr': len(instrs),
        'slots': num_slots,
        'consts': len(builder.consts),
        'tables': len(builder.tables),
        'textures': len(builder.inputs),
        'coord_textures': sum(1 for k in builder.input_kinds if k == 'coord'),
        'per_hit': builder.per_hit,
        'closures': 0,   # value program: emits no closure (Phase 4 contract)
        'types': types,
    }
    if check_budgets:
        for name, val, lim in (('slots', num_slots, GRAPH_MAX_SLOTS),
                               ('instructions', len(instrs), GRAPH_MAX_INSTR),
                               ('constants', len(builder.consts), GRAPH_MAX_CONST),
                               ('tables', len(builder.tables), GRAPH_MAX_TABLES),
                               ('textures', len(builder.inputs), GRAPH_MAX_TEX)):
            if val > lim:
                raise svm.VMCompileError("graph program budget exceeded: %s %d > %d"
                                         % (name, val, lim))
        for t in builder.tables:
            if not 2 <= len(t['data']) <= GRAPH_MAX_TABLE_SIZE:
                raise svm.VMCompileError("graph program table size %d out of range"
                                         % len(t['data']))
    code = []
    for ins in instrs:
        code.extend([ins.op, ins.sub, ins.dst, ins.a, ins.b, ins.c, ins.d, ins.e, ins.res])
    consts = [v for c in builder.consts for v in c]
    tables = []
    table_data = []
    for t in builder.tables:
        tables.append([len(t['data']), t['min_x'], t['range_x'], 1 if t['extrapolate'] else 0])
        table_data.extend(v for c in t['data'] for v in c)
    return {
        'version': GRAPH_IR_VERSION,
        'num_slots': num_slots,
        'out_slot': out_slot,
        'code': code,
        'consts': consts,
        'tables': tables,
        'table_data': table_data,
        'inputs': builder.inputs,
        'input_variants': builder.input_variants,
        'input_kinds': builder.input_kinds,
        'per_hit': builder.per_hit,
        'stats': stats,
    }


def compile_value_program(socket, allow_leaf=False, check_budgets=True):
    """Compile the chain feeding `socket` into a graph value program.

    Same contract as shader_vm_compiler.compile_chain: None for an unlinked or
    constant-foldable chain, or (allow_leaf=False) a bare texture; raises
    VMCompileError for an unsupported node or an exceeded budget."""
    src = svm._linked_source(socket)
    if src is None:
        return None
    if svm._is_texture_leaf(src[0]) and not allow_leaf:
        return None
    b = IRBuilder()
    out = svm.compile_socket(socket, b, 0)
    if not b.inputs and not b.per_hit:
        return None
    return finalize(b, out, check_budgets)

"""pkg219b — Blender node-chain -> bounded op-VM bytecode compiler.

Compiles a per-texel shader-node chain that lives DOWNSTREAM of an image texture
(Color Ramp / Mix / Math / Map Range) into the bytecode consumed by the engine's
ShaderVMProgram (include/astroray/shader_vm.h). Emits a strict prefix of the
Cycles SVM op set (research note pkg219c-blender-node-opcode-semantics.md).

Design (research note pkg219b-op-vm-core-research.md):
  * The compiler is invoked when the addon's constant-folder returns None for a
    socket (a texture is upstream). It walks the chain; any node it cannot
    represent, or a program that exceeds the static bounds, raises
    `VMCompileError` -> the caller falls back to constant-fold + a visible
    degradation entry (never a silent grey).
  * Duck-typed over the Blender node API so it is unit-testable without bpy.

Opcode / sub-op enums MUST match include/astroray/shader_vm.h exactly.
"""

# ---- opcode / sub-op enums (mirror include/astroray/shader_vm.h) -----------
(OP_END, OP_LOAD_TEX, OP_LOAD_CONST, OP_MATH, OP_MIX, OP_RAMP, OP_MAP_RANGE,
 OP_HSV, OP_INVERT, OP_GAMMA, OP_BRIGHT_CONTRAST, OP_SEP_COLOR,
 OP_COMBINE_COLOR, OP_RGB_TO_BW, OP_CLAMP) = range(15)

# pkg230 — Clamp node type (Cycles NodeClampType) + clamp FLAG bits packed into
# the free high bits of an op's imm (mirror include/astroray/shader_vm.h).
CLAMP_MINMAX, CLAMP_RANGE = 0, 1
CLAMP_TYPES = {'MINMAX': CLAMP_MINMAX, 'RANGE': CLAMP_RANGE}
SVM_MATH_CLAMP = 0x80        # OP_MATH: clamp result to [0,1]
SVM_MIX_CLAMP_RESULT = 0x80  # OP_MIX:  clamp result to [0,1] (factor always
#                              saturated in svm_mix = Blender default clamp_factor)

# Colour-space enum for Separate/Combine Color (Cycles NodeCombSepColorType).
CS_RGB, CS_HSV = 0, 1
_COLOR_SPACE = {'RGB': CS_RGB, 'HSV': CS_HSV}  # HSL deferred (pkg219c non-goal)
_SEP_COMPONENT = {'Red': 0, 'Green': 1, 'Blue': 2}

MATH_OPS = {
    'ADD': 0, 'SUBTRACT': 1, 'MULTIPLY': 2, 'DIVIDE': 3, 'MULTIPLY_ADD': 4,
    'POWER': 5, 'SQRT': 6, 'ABSOLUTE': 7, 'MINIMUM': 8, 'MAXIMUM': 9,
    'FLOOR': 10, 'CEIL': 11, 'FRACT': 12, 'MODULO': 13, 'SNAP': 14,
    'LESS_THAN': 15, 'GREATER_THAN': 16, 'SIGN': 17,
}
MATH_TERNARY = {'MULTIPLY_ADD'}  # ops that read the 3rd (c) input

MIX_OPS = {
    'MIX': 0, 'ADD': 1, 'MULTIPLY': 2, 'SUBTRACT': 3, 'SCREEN': 4,
    'DIFFERENCE': 5, 'DARKEN': 6, 'LIGHTEN': 7, 'OVERLAY': 8,
}
MAP_RANGE_OPS = {'LINEAR': 0, 'STEPPED': 1, 'SMOOTHSTEP': 2, 'SMOOTHERSTEP': 3}

VM_MAX_INSTR = 32
VM_MAX_SLOTS = 8
VM_MAX_CONST = 16
VM_MAX_TEX = 2
RAMP_TABLE_SIZE = 256


class VMCompileError(Exception):
    """Raised when a chain cannot be represented within the static bounds."""


def _socket_default_rgb(socket):
    val = socket.default_value
    if hasattr(val, '__iter__'):
        return [float(val[0]), float(val[1]), float(val[2])]
    f = float(val)
    return [f, f, f]


class ProgramBuilder:
    def __init__(self):
        self.code = []          # list of 8-int instrs
        self.consts = []        # flat floats, 3 per const
        self.ramps = []         # flat floats, RAMP_TABLE_SIZE*3 per ramp
        self.inputs = []        # input texture nodes, in OP_LOAD_TEX order
        self._next_slot = 0

    # -- resource allocation --------------------------------------------------
    def alloc_slot(self):
        s = self._next_slot
        self._next_slot += 1
        if s >= VM_MAX_SLOTS:
            raise VMCompileError("op-VM stack bound (VM_MAX_SLOTS) exceeded")
        return s

    def emit(self, op, out, a=0, b=0, c=0, d=0, e=0, imm=0):
        if len(self.code) >= VM_MAX_INSTR:
            raise VMCompileError("op-VM program length (VM_MAX_INSTR) exceeded")
        self.code.append([op, out, a, b, c, d, e, imm])

    def add_const(self, rgb):
        idx = len(self.consts) // 3
        if idx >= VM_MAX_CONST:
            raise VMCompileError("op-VM constant pool (VM_MAX_CONST) exceeded")
        self.consts.extend([float(rgb[0]), float(rgb[1]), float(rgb[2])])
        return idx

    def add_ramp(self, table):
        idx = len(self.ramps) // (RAMP_TABLE_SIZE * 3)
        if idx >= 2:
            raise VMCompileError("op-VM ramp pool exceeded")
        for rgb in table:
            self.ramps.extend([float(rgb[0]), float(rgb[1]), float(rgb[2])])
        return idx

    def add_input(self, tex_node):
        # dedup identical texture nodes so Mix(tex, tex) uses one input slot.
        for i, n in enumerate(self.inputs):
            if n is tex_node:
                return i
        if len(self.inputs) >= VM_MAX_TEX:
            raise VMCompileError("op-VM input-texture bound (VM_MAX_TEX) exceeded")
        self.inputs.append(tex_node)
        return len(self.inputs) - 1

    # -- helpers --------------------------------------------------------------
    def push_const(self, rgb):
        s = self.alloc_slot()
        self.emit(OP_LOAD_CONST, s, imm=self.add_const(rgb))
        return s

    def push_tex(self, tex_node):
        s = self.alloc_slot()
        self.emit(OP_LOAD_TEX, s, imm=self.add_input(tex_node))
        return s


def _is_image_texture(node):
    return getattr(node, 'type', None) == 'TEX_IMAGE'


def _linked_source(socket):
    """Return (from_node, from_socket_name) for a linked socket, else None."""
    if socket is None or not getattr(socket, 'is_linked', False):
        return None
    try:
        link = socket.links[0]
        return link.from_node, link.from_socket.name
    except (IndexError, AttributeError):
        return None


def _get_input(node, *names):
    inp = getattr(node, 'inputs', None)
    if inp is None:
        return None
    for n in names:
        try:
            s = inp.get(n)
        except AttributeError:
            s = None
        if s is not None:
            return s
    return None


def compile_socket(socket, builder, depth=0):
    """Compile the node feeding `socket` into the VM; return its result slot.

    Any value that is constant-foldable becomes an OP_LOAD_CONST; a texture
    becomes OP_LOAD_TEX; a supported node emits its opcode. Unsupported input ->
    VMCompileError (caller falls back to constant-fold).
    """
    if depth > 8:
        raise VMCompileError("op-VM chain too deep")
    src = _linked_source(socket)
    if src is None:
        # unlinked -> constant
        return builder.push_const(_socket_default_rgb(socket))

    node, out_name = src
    ntype = getattr(node, 'type', None)

    if _is_image_texture(node):
        return builder.push_tex(node)

    if ntype == 'VALTORGB':  # Color Ramp
        fac_slot = compile_socket(_get_input(node, 'Fac'), builder, depth + 1)
        table = _bake_ramp(node)
        out = builder.alloc_slot()
        builder.emit(OP_RAMP, out, a=fac_slot, imm=builder.add_ramp(table))
        return out

    if ntype in ('MIX_RGB', 'MIX'):
        blend = getattr(node, 'blend_type', 'MIX')
        if blend not in MIX_OPS:
            raise VMCompileError("unsupported Mix blend: %s" % blend)
        fac_s = compile_socket(_get_input(node, 'Fac', 'Factor'), builder, depth + 1)
        c1_in = _get_input(node, 'Color1', 'A')
        c2_in = _get_input(node, 'Color2', 'B')
        # positional fallback for the modern Mix node (Factor, A, B / …)
        if c1_in is None or c2_in is None:
            ins = list(getattr(node, 'inputs', []))
            if len(ins) >= 3:
                c1_in = c1_in or ins[-2]
                c2_in = c2_in or ins[-1]
        c1_s = compile_socket(c1_in, builder, depth + 1)
        c2_s = compile_socket(c2_in, builder, depth + 1)
        imm = MIX_OPS[blend]
        # pkg230 — clamp the result: modern Mix node clamp_result, or legacy
        # MixRGB use_clamp. (The factor is always saturated in svm_mix, matching
        # Blender's default clamp_factor; faithful clamp_factor=OFF is Phase 2.)
        if getattr(node, 'clamp_result', False) or getattr(node, 'use_clamp', False):
            imm |= SVM_MIX_CLAMP_RESULT
        out = builder.alloc_slot()
        builder.emit(OP_MIX, out, a=fac_s, b=c1_s, c=c2_s, imm=imm)
        return out

    if ntype == 'MATH':
        op = node.operation
        if op not in MATH_OPS:
            raise VMCompileError("unsupported Math op: %s" % op)
        a_s = compile_socket(node.inputs[0], builder, depth + 1)
        b_s = compile_socket(node.inputs[1], builder, depth + 1) \
            if len(node.inputs) > 1 else builder.push_const([0, 0, 0])
        c_s = 0
        if op in MATH_TERNARY and len(node.inputs) > 2:
            c_s = compile_socket(node.inputs[2], builder, depth + 1)
        imm = MATH_OPS[op]
        if getattr(node, 'use_clamp', False):  # pkg230
            imm |= SVM_MATH_CLAMP
        out = builder.alloc_slot()
        builder.emit(OP_MATH, out, a=a_s, b=b_s, c=c_s, imm=imm)
        return out

    if ntype == 'CLAMP':  # pkg230
        ctype = getattr(node, 'clamp_type', 'MINMAX')
        if ctype not in CLAMP_TYPES:
            raise VMCompileError("unsupported Clamp type: %s" % ctype)
        v_s = compile_socket(_get_input(node, 'Value'), builder, depth + 1)
        mn_s = compile_socket(_get_input(node, 'Min'), builder, depth + 1)
        mx_s = compile_socket(_get_input(node, 'Max'), builder, depth + 1)
        out = builder.alloc_slot()
        builder.emit(OP_CLAMP, out, a=v_s, b=mn_s, c=mx_s, imm=CLAMP_TYPES[ctype])
        return out

    if ntype == 'MAP_RANGE':
        interp = getattr(node, 'interpolation_type', 'LINEAR')
        if interp not in MAP_RANGE_OPS:
            raise VMCompileError("unsupported Map Range interp: %s" % interp)
        v_s = compile_socket(_get_input(node, 'Value'), builder, depth + 1)
        fmn = compile_socket(_get_input(node, 'From Min'), builder, depth + 1)
        fmx = compile_socket(_get_input(node, 'From Max'), builder, depth + 1)
        tmn = compile_socket(_get_input(node, 'To Min'), builder, depth + 1)
        tmx = compile_socket(_get_input(node, 'To Max'), builder, depth + 1)
        out = builder.alloc_slot()
        builder.emit(OP_MAP_RANGE, out, a=v_s, b=fmn, c=fmx, d=tmn, e=tmx,
                     imm=MAP_RANGE_OPS[interp])
        return out

    if ntype == 'HUE_SAT':  # Hue/Saturation/Value
        hue_s = compile_socket(_get_input(node, 'Hue'), builder, depth + 1)
        sat_s = compile_socket(_get_input(node, 'Saturation'), builder, depth + 1)
        val_s = compile_socket(_get_input(node, 'Value'), builder, depth + 1)
        fac_s = compile_socket(_get_input(node, 'Fac'), builder, depth + 1)
        col_s = compile_socket(_get_input(node, 'Color'), builder, depth + 1)
        out = builder.alloc_slot()
        builder.emit(OP_HSV, out, a=hue_s, b=sat_s, c=val_s, d=fac_s, e=col_s)
        return out

    if ntype == 'INVERT':
        fac_s = compile_socket(_get_input(node, 'Fac'), builder, depth + 1)
        col_s = compile_socket(_get_input(node, 'Color'), builder, depth + 1)
        out = builder.alloc_slot()
        builder.emit(OP_INVERT, out, a=fac_s, b=col_s)
        return out

    if ntype == 'GAMMA':
        col_s = compile_socket(_get_input(node, 'Color'), builder, depth + 1)
        gam_s = compile_socket(_get_input(node, 'Gamma'), builder, depth + 1)
        out = builder.alloc_slot()
        builder.emit(OP_GAMMA, out, a=col_s, b=gam_s)
        return out

    if ntype == 'BRIGHTCONTRAST':
        col_s = compile_socket(_get_input(node, 'Color'), builder, depth + 1)
        br_s = compile_socket(_get_input(node, 'Bright'), builder, depth + 1)
        ct_s = compile_socket(_get_input(node, 'Contrast'), builder, depth + 1)
        out = builder.alloc_slot()
        builder.emit(OP_BRIGHT_CONTRAST, out, a=col_s, b=br_s, c=ct_s)
        return out

    if ntype == 'SEPARATE_COLOR':
        mode = getattr(node, 'mode', 'RGB')
        if mode not in _COLOR_SPACE:
            raise VMCompileError("unsupported Separate Color mode: %s" % mode)
        comp = _SEP_COMPONENT.get(out_name)
        if comp is None:
            raise VMCompileError("unsupported Separate Color output: %s" % out_name)
        col_s = compile_socket(_get_input(node, 'Color'), builder, depth + 1)
        out = builder.alloc_slot()
        builder.emit(OP_SEP_COLOR, out, a=col_s,
                     imm=_COLOR_SPACE[mode] * 4 + comp)
        return out

    if ntype == 'COMBINE_COLOR':
        mode = getattr(node, 'mode', 'RGB')
        if mode not in _COLOR_SPACE:
            raise VMCompileError("unsupported Combine Color mode: %s" % mode)
        r_s = compile_socket(_get_input(node, 'Red'), builder, depth + 1)
        g_s = compile_socket(_get_input(node, 'Green'), builder, depth + 1)
        b_s = compile_socket(_get_input(node, 'Blue'), builder, depth + 1)
        out = builder.alloc_slot()
        builder.emit(OP_COMBINE_COLOR, out, a=r_s, b=g_s, c=b_s,
                     imm=_COLOR_SPACE[mode])
        return out

    if ntype == 'RGB_TO_BW':
        col_s = compile_socket(_get_input(node, 'Color'), builder, depth + 1)
        out = builder.alloc_slot()
        builder.emit(OP_RGB_TO_BW, out, a=col_s)
        return out

    if ntype == 'RGB':
        return builder.push_const(list(node.outputs[0].default_value[:3]))
    if ntype == 'VALUE':
        f = float(node.outputs[0].default_value)
        return builder.push_const([f, f, f])

    raise VMCompileError("unsupported node type in op-VM chain: %s" % ntype)


def _bake_ramp(node):
    """Bake a Color Ramp to RAMP_TABLE_SIZE RGB samples (Cycles colorramp_to_array)."""
    ramp = node.color_ramp
    table = []
    for i in range(RAMP_TABLE_SIZE):
        f = i / (RAMP_TABLE_SIZE - 1)
        col = ramp.evaluate(f)
        table.append((float(col[0]), float(col[1]), float(col[2])))
    return table


def compile_chain(socket):
    """Compile the chain feeding `socket`. Returns None if it is purely a single
    image texture (no per-texel op — the existing pkg186 texture path handles it)
    or purely constant; raises VMCompileError if unrepresentable.

    On success returns a dict:
      {num_tex, out_slot, code_flat, consts_flat, ramps_flat, inputs}
    where `inputs` is the ordered list of Blender image-texture nodes.
    """
    src = _linked_source(socket)
    if src is None:
        return None
    node, _ = src
    # A bare image texture needs no VM (pkg186 path). A per-texel op is required
    # only when there is a node BETWEEN the texture and the socket.
    if _is_image_texture(node):
        return None

    builder = ProgramBuilder()
    out_slot = compile_socket(socket, builder, 0)
    if not builder.inputs:
        # no texture in the chain -> constant-foldable, no VM needed
        return None
    code_flat = []
    for ins in builder.code:
        code_flat.extend(ins)
    return {
        'num_tex': len(builder.inputs),
        'out_slot': out_slot,
        'code_flat': code_flat,
        'consts_flat': builder.consts,
        'ramps_flat': builder.ramps,
        'inputs': builder.inputs,
    }

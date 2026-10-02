"""pkg314 — graph-IR resource stats for every shader graph of a set of .blend files.

Runs INSIDE Blender (no render, no engine). For every material of every file it
walks the active Material Output's Surface tree (node groups inlined with
Material.inline_shader_nodes(), as the addon does) and, for every linked
non-shader input socket of every reachable node that consumes one, compiles the
chain feeding it with blender_addon/shader_graph_ir.py. It records the route the
addon takes (op-VM if the bounded op-VM represents it, else graph program; bare
texture / constant otherwise), instruction count before/after CSE, peak live
slots, constants, tables, textures and per-hit inputs, plus the material's maximum
emitted closures (leaf BSDFs reachable through Mix/Add Shader).

Usage:
  blender --background --factory-startup --python scripts/dev/shader_graph_ir_stats.py -- \
      --out stats.md file1.blend [file2.blend ...]
"""
import argparse
import os
import sys

import bpy

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "blender_addon"))
import shader_graph_ir as G  # noqa: E402
import shader_vm_compiler as C  # noqa: E402

_SHADER_COMBINE = {'MIX_SHADER', 'ADD_SHADER'}


def _closures(socket, seen=0):
    """Maximum number of leaf closures a Surface socket can emit."""
    src = C._linked_source(socket)
    if src is None:
        return 0
    node = src[0]
    if node.type in _SHADER_COMBINE:
        return sum(_closures(s) for s in node.inputs if s.type == 'SHADER')
    return 1


def _reachable(socket, out):
    src = C._linked_source(socket)
    if src is None or src[0] in out:
        return
    out.append(src[0])
    for s in src[0].inputs:
        if s.is_linked:
            _reachable(s, out)


def _route(sock):
    try:
        legacy = C.compile_chain(sock, allow_leaf=False)
    except C.VMCompileError as e:
        legacy = e
    try:
        prog = G.compile_value_program(sock, allow_leaf=True, check_budgets=False)
    except C.VMCompileError as e:
        return 'unsupported', None, str(e)
    if prog is None:
        return 'constant', None, ''
    if legacy is None:
        return 'texture', prog['stats'], ''
    if isinstance(legacy, Exception):
        return 'graph', prog['stats'], str(legacy)
    return 'op-VM', prog['stats'], ''


def _material_rows(scene_name, mat):
    rows = []
    inlined = mat.inline_shader_nodes() if hasattr(mat, 'inline_shader_nodes') else None
    tree = inlined.node_tree if inlined is not None else mat.node_tree
    if tree is None:
        return rows
    outs = [n for n in tree.nodes if n.type == 'OUTPUT_MATERIAL']
    out = next((n for n in outs if n.is_active_output), outs[0] if outs else None)
    if out is None:
        return rows
    surf = out.inputs.get('Surface')
    closures = _closures(surf)
    nodes = []
    _reachable(surf, nodes)
    for node in nodes:
        for sock in node.inputs:
            if sock.type == 'SHADER' or not sock.is_linked:
                continue
            src = C._linked_source(sock)
            # Only sockets of shader-consuming nodes (BSDFs, Mix Shader Fac, Bump...)
            # are program roots; inner sockets are part of their parents' chains.
            if any(o.type == 'SHADER' for o in node.outputs) or node.type == 'BUMP':
                route, st, why = _route(sock)
                rows.append((scene_name, mat.name, closures, '%s.%s' % (node.name, sock.name),
                             route, st, why))
    if not rows:  # every input constant: still record the material's closure count
        rows.append((scene_name, mat.name, closures, '-', 'constant', None, ''))
    del inlined
    return rows


def main():
    argv = sys.argv[sys.argv.index('--') + 1:]
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('files', nargs='+')
    a = ap.parse_args(argv)
    rows = []
    for f in a.files:
        bpy.ops.wm.open_mainfile(filepath=f)
        scene = os.path.splitext(os.path.basename(f))[0]
        for mat in bpy.data.materials:
            if mat.use_nodes and mat.users:
                rows.extend(_material_rows(scene, mat))
    lines = ['| Scene | Material | Max closures | Socket | Route | Instr (pre-CSE) | Peak slots '
             '| Consts | Tables | Textures | Per-hit | Note |',
             '|---|---|---|---|---|---|---|---|---|---|---|---|']
    for scene, mname, clo, sock, route, st, why in rows:
        if st:
            cells = ['%d (%d)' % (st['instr'], st['instr_pre_opt']), str(st['slots']),
                     str(st['consts']), str(st['tables']),
                     '%d%s' % (st['textures'], ' (%d uv)' % st['coord_textures']
                               if st['coord_textures'] else ''),
                     'yes' if st['per_hit'] else '']
        else:
            cells = [''] * 6
        lines.append('| %s | %s | %d | %s | %s | %s | %s |' % (
            scene, mname, clo, sock.replace('|', '/'), route, ' | '.join(cells),
            why.replace('|', '/')[:90]))
    with open(a.out, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write('\n'.join(lines) + '\n')
    print('IR_STATS_DONE %d rows -> %s' % (len(rows), a.out))


main()

# Astroray UI conventions (pkg311)

Owner 2026-09-29: Astroray's UI is native Blender surfaces that follow Cycles'
conventions, plus a shipped asset library later. No custom N-panel/sidebar app,
no custom workspace.

1. **Native surfaces only.** Properties-editor panels, Add-menu categories,
   preset menus, node `draw_buttons`, the asset browser. Do not duplicate a
   Cycles/Blender control; adopt the native one (see `ADOPTED_NATIVE_PANELS`).
2. **Panel naming and parenting.** `<CONTEXT>_PT_astroray_<thing>` for top-level
   panels, `..._<sub>` for children with `bl_parent_id`. Children repeat the
   parent's `poll`. Advanced groups use `DEFAULT_CLOSED`; on/off features put
   their checkbox in `draw_header`.
3. **Units in labels.** Every physical property carries its unit in `name`
   (`Mass (M☉)`, `Jet Magnetic Field (G)`); dimensionless ones say so or use a
   plain-language name.
4. **Tooltips are mandatory.** Every `bpy.props` property on an addon
   `PropertyGroup`, preferences class or node has a non-empty `description`
   (enforced by `tests/test_pkg311_ui_conformance.py`).
5. **Presets go through `PresetPanel` + `script.execute_preset`.** Files live in
   `blender_addon/presets/<subdir>/`, the addon registers that directory with
   `bpy.utils.register_preset_path`, and each file cites its source (DOI) for any
   physical value. Pair every preset menu with an `AddPresetBase` operator.
6. **Mark un-honoured controls.** If a control is drawn but the engine ignores
   it, grey it (`enabled = False`) and add a one-line `INFO` label; never leave
   it live and silent. Prefer removing it once nothing depends on it.
7. **Node status lines.** A node the converter will not use shows an
   `INFO` (unwired) or `ERROR` (wired but ignored) line. The UI must reuse the
   converter's own rule; a test asserts the two idname sets agree.
8. **No behaviour change.** UI work must not change renders.

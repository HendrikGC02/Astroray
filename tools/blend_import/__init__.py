# pkg76 — Astroray .blend importer (parity scope).
#
# This package reads .blend files offline (no bpy dependency) and populates an
# astroray.Renderer with the parity-scope subset described in
# .astroray_plan/packages/pkg76-blend-importer-parity-scope.md.
#
# Format references (see file headers in each submodule):
#   - https://wiki.blender.org/wiki/Source/File_Format (canonical SDNA spec)
#   - https://www.atmind.nl/blender/mystery_ot_blend.html (block-walk walkthrough)
#
# The Cycles source (`source/blender/blenkernel/intern/readfile.c`) is read for
# semantic understanding only; it is GPL-2.0-or-later and is not mirrored here.

from .blend_to_astroray import import_blend, BlendImportWarning

__all__ = ["import_blend", "BlendImportWarning"]

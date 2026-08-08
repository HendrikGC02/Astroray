# -*- coding: utf-8 -*-
"""pkg129 (narrowed) — live-Cycles rough-metal A/B parity harness.

Three-leg A/B on a rough-metal sweep (r in {0.3, 0.6, 0.9}, metallic=1, one
chromatic + one neutral albedo): headless Cycles (oracle, Blender 5.1), Astroray
CPU, Astroray GPU. Compares image-plane radiance parity in LINEAR with a
per-channel mean-ratio band asserting BOTH floor and ceiling (pkg166 rules).

Since both engines now consume the SAME Cycles energy-compensation table data
(pkg129 refresh premise 2: ``energy_compensation.h`` loads Cycles'
``table_ggx_E`` / ``table_ggx_Eavg``), this A/B isolates the compensation
APPLICATION-FORM difference (in-repo Kulla-Conty layering vs Cycles' in-kernel
Turquin albedo scaling), not the table data.

The pure parts (sweep construction, per-channel ratio, band logic) are
import-safe and unit-tested without Blender or a GPU; only ``harness.run`` needs
Blender + a built Astroray addon .pyd.
"""

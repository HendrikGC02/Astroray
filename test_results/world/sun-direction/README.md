# Sun direction convention
Addon sun_rotation 0 / 90 / 225: Cycles (top) vs Astroray (bottom), yellow = measured shadow azimuth.
Verdict: Astroray shadows match Cycles within 4 deg at every rotation after the #814 fix
(Cycles az 92/2/222 vs Astroray 88/2/222). roi_rot0_sheet shows the matched irradiance ROIs.
samescene_strip_sheet is the earlier same-camera check (issue #813 azimuth follow-up).
Provenance: issue #814, Batch L (PR #824), Batch J, 2026-09-13..18.

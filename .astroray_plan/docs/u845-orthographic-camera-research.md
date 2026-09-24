# #845 orthographic camera — sources

- Ray model: PBRT v4 `OrthographicCamera::GenerateRay` (Apache-2.0),
  https://www.pbr-book.org/4ed/Cameras_and_Film/Orthographic_Camera. Origin on
  the image plane, constant direction; thin lens aims at the point `focusDistance`
  along the view axis from the unperturbed plane point. Implemented in
  `Camera::orthoRay` (CPU) and `generatePrimaryRay` (GPU), same RNG draws as PERSP.
- Blender viewplane (behaviour oracle, not copied): the ortho plane spans
  `ortho_scale` along the sensor-fit axis (AUTO = larger image dimension); shift
  is `shift * ortho_scale` world units. Cycles `blender/camera.cpp` (Apache-2.0):
  ortho aperture radius = `1 / (2 * fstop)`.
- Acceptance: `tests/data/pkg845_blender_ortho_reference.json` holds Blender 5.2
  `world_to_camera_view` pixel positions and `calc_matrix_camera` for the
  `ORTHO_GRID` fixture (landscape + portrait).

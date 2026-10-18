"""#1145: run_parity needs cv2 OpenEXR read/write; opencv 5.0 wheels lack it (requirements pins <5)."""
import os

os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")


def test_cv2_exr_roundtrip(tmp_path):
    img = np.arange(12, dtype=np.float32).reshape(2, 2, 3) / 7.0
    path = tmp_path / "t.exr"
    assert cv2.imwrite(str(path), img)
    back = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    assert back is not None
    np.testing.assert_allclose(back, img, rtol=0, atol=1e-3)

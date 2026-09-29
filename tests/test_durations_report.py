import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "durations_report", Path(__file__).resolve().parent.parent / "scripts" / "test" / "durations_report.py")
dr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dr)

XML = """<testsuites><testsuite>
<testcase classname="tests.test_volume_smoke.TestA" name="a" time="5.0"/>
<testcase classname="tests.test_volume_smoke.TestA" name="b" time="3.0"/>
<testcase classname="test_glass" name="c" time="10.0"><skipped/></testcase>
<testcase classname="tests.test_zzz" name="d" time="1.0"><failure/></testcase>
</testsuite></testsuites>"""


@pytest.mark.cpu
def test_aggregate(tmp_path):
    p = tmp_path / "j.xml"
    p.write_text(XML)
    tests, counts = dr.load(p)
    assert counts == {"passed": 2, "skipped": 1, "failed": 1}
    agg = dr.aggregate(tests)
    assert agg["file"]["tests/test_volume_smoke.py"] == 8.0
    assert agg["area"] == {"volumes": 8.0, "materials": 10.0, "other": 1.0}
    assert list(agg["test"])[0] == "tests/test_glass.py::c"


@pytest.mark.cpu
@pytest.mark.parametrize("n", [1, 2])
def test_outputs(tmp_path, n):
    p = tmp_path / "j.xml"
    p.write_text(XML)
    out = tmp_path / "out"
    dr.main(sum([["--junit", str(p)] for _ in range(n)], []) + ["--out", str(out)])
    for stem in ("by_area", "by_file", "top_tests"):
        assert (out / f"durations_{stem}_chart.png").exists()
        assert (out / f"durations_{stem}_chart.json").exists()


@pytest.mark.cpu
def test_file_of_keeps_subdirectories():
    assert dr.file_of("tests.statistical.test_chi2_bsdf.TestX") == "tests/statistical/test_chi2_bsdf.py"
    assert dr.file_of("test_glass") == "tests/test_glass.py"

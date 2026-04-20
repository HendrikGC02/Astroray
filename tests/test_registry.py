"""
Tests for astroray::Registry<T> and astroray::ParamDict.

These tests compile and run small C++ snippets against the headers to verify
the registry skeleton introduced in pkg01.
"""
import os
import subprocess
import sys
import tempfile

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INCLUDE_DIR = os.path.join(PROJECT_ROOT, "include")


def _find_compiler():
    cxx = os.environ.get("CXX")
    if cxx and _cmd_exists(cxx):
        return cxx
    for candidate in ("g++", "c++", "clang++"):
        if _cmd_exists(candidate):
            return candidate
    pytest.skip("No C++ compiler found; set CXX env var")


def _cmd_exists(name):
    try:
        subprocess.run([name, "--version"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def _compile_run(src: str) -> str:
    """Compile src, run the resulting binary, return stdout. Fails test on error."""
    compiler = _find_compiler()
    with tempfile.TemporaryDirectory() as tmp:
        src_path = os.path.join(tmp, "test.cpp")
        exe_path = os.path.join(tmp, "test.exe" if sys.platform == "win32" else "test")
        with open(src_path, "w") as f:
            f.write(src)
        result = subprocess.run(
            [compiler, "-std=c++17", f"-I{INCLUDE_DIR}", src_path, "-o", exe_path],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            pytest.fail(f"Compilation failed:\n{result.stderr}")
        result = subprocess.run([exe_path], capture_output=True, text=True)
        if result.returncode != 0:
            pytest.fail(f"Runtime error:\n{result.stderr}")
        return result.stdout.strip()


_REGISTRY_TEST_SRC = r"""
#include "astroray/registry.h"
#include "astroray/param_dict.h"
#include <cassert>
#include <cstdio>

namespace astroray {
    struct DummyProduct {
        explicit DummyProduct(const ParamDict&) {}
    };
}

int main() {
    using namespace astroray;
    auto& reg = Registry<DummyProduct>::instance();
    reg.add("dummy", [](const ParamDict& p) {
        return std::make_shared<DummyProduct>(p);
    });

    // create by name
    auto obj = reg.create("dummy", ParamDict{});
    assert(obj != nullptr);

    // names() returns the registered entry
    auto names = reg.names();
    assert(names.size() == 1);
    assert(names[0] == "dummy");

    // unknown name throws
    bool threw = false;
    try { reg.create("nonexistent", ParamDict{}); }
    catch (const std::exception&) { threw = true; }
    assert(threw);

    std::puts("registry_ok");
    return 0;
}
"""

_PARAM_DICT_TEST_SRC = r"""
#include "astroray/param_dict.h"
#include <cassert>
#include <cstdio>
#include <cmath>

int main() {
    using astroray::ParamDict;

    ParamDict p;

    // float round-trip
    p.set("f", 3.14f);
    assert(p.getFloat("f") == 3.14f);

    // unknown key returns default
    assert(p.getFloat("missing") == 0.0f);
    assert(p.getFloat("missing", 7.0f) == 7.0f);

    // int round-trip
    p.set("i", 42);
    assert(p.getInt("i") == 42);
    assert(p.getInt("nope", 99) == 99);

    // bool round-trip
    p.set("b", true);
    assert(p.getBool("b") == true);
    assert(p.getBool("nope") == false);

    // string round-trip
    p.set("s", std::string("hello"));
    assert(p.getString("s") == "hello");

    // Vec3 round-trip
    p.set("v", Vec3(1.0f, 2.0f, 3.0f));
    Vec3 v = p.getVec3("v");
    assert(v.x == 1.0f && v.y == 2.0f && v.z == 3.0f);

    // Vec3 default
    Vec3 dflt = p.getVec3("no_vec");
    assert(dflt.x == 0.0f && dflt.y == 0.0f && dflt.z == 0.0f);

    // float array round-trip
    p.set("fa", std::vector<float>{1.0f, 2.0f, 3.0f});
    auto fa = p.getFloatArray("fa");
    assert(fa.size() == 3 && fa[0] == 1.0f && fa[2] == 3.0f);

    // chained set
    ParamDict p2;
    p2.set("a", 1.0f).set("b", 2.0f);
    assert(p2.getFloat("a") == 1.0f && p2.getFloat("b") == 2.0f);

    std::puts("param_dict_ok");
    return 0;
}
"""


def test_registry_basic():
    output = _compile_run(_REGISTRY_TEST_SRC)
    assert output == "registry_ok"


def test_param_dict():
    output = _compile_run(_PARAM_DICT_TEST_SRC)
    assert output == "param_dict_ok"

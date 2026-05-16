import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from roadmap_orchestrator.priority import parse_priority

SAMPLE = """
## 1. Something
pkg00 should be ignored (before section 2)

## 2. Recommended next deployable set
1. pkg94 — addon build-integrity guard (first)
2. pkg95 ∥ pkg96 — concurrent after pkg94
3. pkg55-B-prime-cuda-gate-derivation — doc-only

## 3. Drop-in prompts
pkg99 ignored (after section 2)
"""

def test_extracts_section2_packages_in_order():
    assert parse_priority(SAMPLE) == ["pkg94", "pkg95", "pkg96", "pkg55-B-prime-cuda-gate-derivation"]

def test_missing_section_returns_empty():
    assert parse_priority("no sections here") == []

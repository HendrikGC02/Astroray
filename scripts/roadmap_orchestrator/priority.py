"""Best-effort ordered package hint from NEXT_STAGE_REPORT.md section 2.

SCOPE / ASSUMPTION: this is a permissive token scan over the whole §2 body.
It deliberately does NOT distinguish the actionable "recommended deployable
set" from packages merely mentioned in §2 prose (e.g. "Round 9 complete:
pkgNN", "BUG-11 ≡ pkgNN", closed packages, fragments). That is acceptable
because the only consumer is the hardware-queue *tiebreak ordering*
(`queue.order_hw_queue`): relative order of real candidates is preserved,
and phantom/closed tokens never match an open PR so they are never queued.
The authoritative eligible/dispatch set is computed by SKILL.md via the
dispatch-next eligibility logic, NOT from this function. Do not repurpose
this as an authoritative dispatch list.
"""
import re

_PKG = re.compile(r"pkg[0-9]+[A-Za-z0-9\-]*")


def parse_priority(text: str) -> list:
    lines = text.splitlines()
    start = end = None
    for i, ln in enumerate(lines):
        if start is None and re.match(r"^##\s*2[.)]", ln.strip()):
            start = i + 1
        elif start is not None and re.match(r"^##\s*3[.)]", ln.strip()):
            end = i
            break
    if start is None:
        return []
    body = "\n".join(lines[start:end if end is not None else len(lines)])
    seen, out = set(), []
    for m in _PKG.findall(body):
        if m not in seen:
            seen.add(m); out.append(m)
    return out

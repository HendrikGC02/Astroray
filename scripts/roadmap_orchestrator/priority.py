"""Parse the ordered package list from NEXT_STAGE_REPORT.md section 2."""
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

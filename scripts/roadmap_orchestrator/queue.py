"""Order the HW-untested queue: NEXT_STAGE_REPORT priority, then oldest PR."""
import re


def pkg_of(pr: dict, priority: list):
    hay = f"{pr.get('title', '')} {pr.get('headRefName', '')}"
    for pkg in priority:
        if re.search(r'(?<![A-Za-z0-9\-])' + re.escape(pkg) + r'(?![A-Za-z0-9\-])', hay):
            return pkg
    return None


def order_hw_queue(numbers: list, prs_by_number: dict, priority: list) -> list:
    idx = {p: i for i, p in enumerate(priority)}

    def key(n):
        pr = prs_by_number[n]
        pkg = pkg_of(pr, priority)
        prio = idx.get(pkg, len(priority))  # unknown sorts last
        return (prio, pr.get("createdAt", ""), n)

    return sorted(numbers, key=key)

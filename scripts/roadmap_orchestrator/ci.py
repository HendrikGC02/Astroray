"""Reduce a GitHub statusCheckRollup to pass | fail | pending."""

_CR_FAIL = {"FAILURE", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED"}
_CR_OK = {"SUCCESS", "NEUTRAL", "SKIPPED"}
_SC_FAIL = {"FAILURE", "ERROR"}


def ci_state(pr: dict) -> str:
    rollup = pr.get("statusCheckRollup") or []
    if not rollup:
        return "pending"
    any_nonterminal = False
    saw_ok = False
    for e in rollup:
        if e.get("__typename") == "CheckRun":
            concl = e.get("conclusion")
            if e.get("status") != "COMPLETED" or concl is None:
                any_nonterminal = True
            elif concl in _CR_FAIL:
                return "fail"
            elif concl in _CR_OK:
                saw_ok = True
            else:
                any_nonterminal = True
        else:  # StatusContext
            state = e.get("state")
            if state in _SC_FAIL:
                return "fail"
            elif state == "SUCCESS":
                saw_ok = True
            else:
                any_nonterminal = True
    if any_nonterminal:
        return "pending"
    return "pass" if saw_ok else "pending"

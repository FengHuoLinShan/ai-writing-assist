from __future__ import annotations

import json

from .models import ContractIssue, PromptContract

BLOCKING_SEVERITIES = {"P0", "P1"}


def has_blocking_issues(
    issues: list[ContractIssue], *, strict_docs: bool = False
) -> bool:
    blocking = set(BLOCKING_SEVERITIES)
    if strict_docs:
        blocking.add("P2")
    return any(issue.severity in blocking for issue in issues)


def format_text(contracts: list[PromptContract], issues: list[ContractIssue]) -> str:
    if not issues:
        return f"Prompt contracts passed ({len(contracts)} contracts)."
    lines = [
        f"Prompt contracts found {len(issues)} issue(s) "
        f"across {len(contracts)} contract(s):"
    ]
    for issue in sorted(issues, key=lambda item: (item.severity, item.contract_id)):
        location = f" [{issue.path}]" if issue.path else ""
        lines.append(
            f"- {issue.severity} {issue.contract_id} {issue.code}{location}: "
            f"{issue.message}"
        )
    return "\n".join(lines)


def format_json(contracts: list[PromptContract], issues: list[ContractIssue]) -> str:
    payload = {
        "contracts": [contract.id for contract in contracts],
        "issue_count": len(issues),
        "issues": [issue.as_dict() for issue in issues],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)

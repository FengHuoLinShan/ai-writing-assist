from __future__ import annotations

import argparse
import sys

from .models import ContractIssue
from .registry import ContractRegistryError, load_contract, load_contracts
from .report import format_json, format_text, has_blocking_issues
from .validators import validate_contracts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.prompt_contracts")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check_parser = subparsers.add_parser("check")
    check_parser.add_argument("--contract")
    check_parser.add_argument("--json", action="store_true")
    check_parser.add_argument("--strict-docs", action="store_true")
    check_parser.add_argument("--fixtures", action="store_true")

    explain_parser = subparsers.add_parser("explain")
    explain_parser.add_argument("contract")

    args = parser.parse_args(argv)
    if args.command == "explain":
        return _explain(args.contract)
    if args.command == "check":
        return _check(
            contract_id=args.contract,
            json_output=args.json,
            strict_docs=args.strict_docs,
            include_fixtures=args.fixtures,
        )
    return 2


def _check(
    *,
    contract_id: str | None,
    json_output: bool,
    strict_docs: bool,
    include_fixtures: bool,
) -> int:
    try:
        contracts = [load_contract(contract_id)] if contract_id else load_contracts()
        issues = validate_contracts(contracts, include_fixtures=include_fixtures)
    except ContractRegistryError as exc:
        contracts = []
        issues = [
            ContractIssue(
                severity="P1",
                contract_id="registry",
                code="registry.invalid",
                message=str(exc),
            )
        ]
    output = (
        format_json(contracts, issues) if json_output else format_text(contracts, issues)
    )
    print(output)
    return 1 if has_blocking_issues(issues, strict_docs=strict_docs) else 0


def _explain(contract_id: str) -> int:
    try:
        contract = load_contract(contract_id)
    except ContractRegistryError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"{contract.id} v{contract.version}")
    print(f"owner: {contract.owner}")
    print(f"schema_model: {contract.schema_model}")
    print(f"declared_prompt_fields: {', '.join(contract.declared_prompt_fields)}")
    print(f"required_mappings: {len(contract.required_mappings)}")
    print(f"observed_fields: {len(contract.observed_fields)}")
    print(f"ignored_fields: {len(contract.ignored_fields)}")
    print(f"probes: {', '.join(contract.probes) if contract.probes else '-'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

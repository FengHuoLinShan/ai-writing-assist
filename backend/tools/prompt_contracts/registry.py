from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

from .models import PromptContract
from .probes import PROBES

CONTRACT_DIR = Path(__file__).resolve().parent / "contracts"
ALLOWED_SCHEMA_PREFIXES = (
    "modules.imports.",
    "modules.story.outline_state.",
    "modules.world.",
    "modules.story.continuity.",
    "modules.evidence.",
)


class ContractRegistryError(ValueError):
    pass


def import_schema_model(path: str) -> type[Any]:
    if not path.startswith(ALLOWED_SCHEMA_PREFIXES):
        raise ContractRegistryError(f"illegal schema_model prefix: {path}")
    module_name, _, attr = path.rpartition(".")
    if not module_name or not attr:
        raise ContractRegistryError(f"invalid schema_model path: {path}")
    module = importlib.import_module(module_name)
    return getattr(module, attr)


def load_contracts(contract_dir: Path = CONTRACT_DIR) -> list[PromptContract]:
    contracts: list[PromptContract] = []
    seen: set[str] = set()
    for path in sorted(contract_dir.glob("*.json")):
        with path.open(encoding="utf-8") as file:
            raw = json.load(file)
        contract = PromptContract.from_dict(raw)
        if not contract.id:
            raise ContractRegistryError(f"{path.name}: missing contract id")
        if contract.id in seen:
            raise ContractRegistryError(f"duplicate contract id: {contract.id}")
        seen.add(contract.id)
        if not contract.schema_model.startswith(ALLOWED_SCHEMA_PREFIXES):
            raise ContractRegistryError(
                f"{contract.id}: illegal schema_model prefix: {contract.schema_model}"
            )
        for probe in contract.probes:
            if probe not in PROBES:
                raise ContractRegistryError(f"{contract.id}: unknown probe: {probe}")
        contracts.append(contract)
    return contracts


def load_contract(contract_id: str, contract_dir: Path = CONTRACT_DIR) -> PromptContract:
    contracts = load_contracts(contract_dir)
    for contract in contracts:
        if contract.id == contract_id:
            return contract
    raise ContractRegistryError(f"unknown contract id: {contract_id}")

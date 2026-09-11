"""Release qualification is specific to prompt, provider profile and model.

Add entries only from held-out human review meeting the documented criteria;
changing a model or prompt cannot silently inherit another run's qualification.
"""

QUALIFIED_RUNS: dict[tuple[str, str, str], frozenset[str]] = {}


def qualified(category: str, *, prompt_hash: str, profile_hash: str, model: str) -> bool:
    if not prompt_hash or not profile_hash or not model:
        return False
    return category in QUALIFIED_RUNS.get((prompt_hash, profile_hash, model), frozenset())

"""Guardrails for the deprecated prefetch/reinforcement Scene pipeline."""

from __future__ import annotations

from modules.imports.env_helpers import bool_env

LEGACY_SCENE_PIPELINE_ENV = "DEEP_IMPORT_LEGACY_SCENE_PIPELINE_ENABLED"


def legacy_scene_pipeline_enabled() -> bool:
    """Return whether deprecated Scene prefetch/reinforcement may run."""

    return bool_env(LEGACY_SCENE_PIPELINE_ENV, False)


def require_legacy_scene_pipeline_enabled(component: str) -> None:
    """Fail fast when deprecated Scene components are called by default."""

    if legacy_scene_pipeline_enabled():
        return
    raise RuntimeError(
        f"{component} is a deprecated legacy Scene pipeline component. "
        "The current Scene auto extraction path is "
        "phase0_plan -> phase1a_scene_slicing -> phase1b_enrichment -> scene_commit. "
        f"Set {LEGACY_SCENE_PIPELINE_ENV}=1 only for explicit legacy repair "
        "or historical artifact acceptance."
    )

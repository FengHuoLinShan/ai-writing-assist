"""Exact, deduplicated World transfer choices from one frozen Director output."""

from __future__ import annotations

from hashlib import sha256

from pydantic import ValidationError

from modules.story.director_schemas import DirectorCandidateEvent
from modules.story.simulation_v3 import SimulationReference


def _key(kind: str, source_id: str) -> str:
    return sha256(f"{kind}:{source_id}".encode()).hexdigest()


def transfer_choices(output: dict) -> list[dict]:
    """Only typed candidate refs and explicit events can be transferred.

    Event prose never becomes a person, place, or object name. A reference's
    frozen label is its proposed name; its type is chosen by the author.
    """
    choices: dict[str, dict] = {}

    def add_reference(raw: object) -> None:
        if not isinstance(raw, dict) or raw.get("kind") != "candidate":
            return
        try:
            ref = SimulationReference.model_validate(raw)
        except ValidationError:
            return
        candidate_id = _key("reference", str(ref.id))
        previous = choices.get(candidate_id)
        if previous is not None:
            if previous["label"] != ref.label:
                previous["conflict"] = True
            return
        choices[candidate_id] = {
            "candidate_id": candidate_id,
            "source_kind": "reference",
            "source_id": ref.id,
            "label": ref.label,
            "description": "",
            "conflict": not bool(ref.label.strip()) or len(ref.label) > 255,
        }

    for material in output.get("materials") or []:
        if isinstance(material, dict):
            for raw in material.get("object_refs") or []:
                add_reference(raw)
    for raw_event in output.get("candidate_events") or []:
        if not isinstance(raw_event, dict):
            continue
        try:
            event = DirectorCandidateEvent.model_validate(raw_event)
        except ValidationError:
            continue
        for raw in event.references:
            add_reference(raw)
        candidate_id = _key("event", event.candidate_id)
        previous = choices.get(candidate_id)
        if previous is not None:
            previous["conflict"] = True
            continue
        choices[candidate_id] = {
            "candidate_id": candidate_id,
            "source_kind": "event",
            "source_id": event.candidate_id,
            "label": event.label,
            "description": event.description,
            "conflict": False,
        }
    return list(choices.values())

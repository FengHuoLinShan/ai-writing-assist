"""Exact consumed-input proofs for selective recomputation; old proofs fail closed."""

from copy import deepcopy

from infrastructure.llm.collaboration import content_hash
from modules.evolution.llm_sampler import (
    SYSTEM_PROMPT,
    SceneSample,
    build_scene_messages,
    prepare_scene_call_request,
    registered_scene_request,
)

VERSION = "evolution.consumer_read_set.v1"


def sample_inputs(scene_text, manifest, *, scene_id, versions):
    # Receipt IDs change on re-extraction; all consumed facts and Scene anchors stay.
    manifest = deepcopy(manifest)
    manifest.pop("run_key", None)
    manifest.pop("source_manifest_hash", None)
    parent = manifest.pop("previous_scene_attempt_id", None)
    if parent:
        manifest["previous_scene_attempt_id"] = "committed-parent"
    for item in manifest.get("previous_observations", []):
        item.pop("observation_id", None)
    return {
        "scene_text": scene_text,
        "scene_id": scene_id,
        "input_manifest": manifest,
        "versions": versions,
        "prompt": SYSTEM_PROMPT,
        "schema": SceneSample.model_json_schema(),
        "messages": [
            message.model_dump(mode="json")
            for message in build_scene_messages(
                scene_text=scene_text, input_manifest=manifest
            )
        ],
        "transport": {
            "temperature": 0.1,
            "flash_max_tokens": 16384,
            "flash_thinking": "disabled",
            "repair_attempts": 0,
            "transport_retries": False,
        },
    }


def observation_tokens(payload):
    """Alpha-renaming only for fully qualified observations present in actual inputs."""
    records = (payload.get("discovery_preparation") or {}).get("observations", {})
    tokens = {}
    for oid, record in records.items():
        body = deepcopy(
            {
                key: value
                for key, value in record.items()
                if key not in {"observation_id", "event_occurrence_id", "dependency"}
            }
        )
        for mention in body.get("mentions", []):
            mention.pop("mention_id", None)
            if mention.get("resolution"):
                mention["resolution"].pop("mention_id", None)
        attribution = body.get("utterance_attribution") or {}
        if attribution.get("speaker_resolution"):
            attribution["speaker_resolution"].pop("mention_id", None)
        # Dependency run identities are host provenance, not evidence semantics.
        token = "observation:" + content_hash(body)
        tokens[oid] = token
    if len(set(tokens.values())) != len(tokens):
        return {}  # Ambiguous matches cannot rebind model references.
    return tokens


def rename(value, tokens):
    if isinstance(value, dict):
        return {key: rename(item, tokens) for key, item in value.items()}
    if isinstance(value, list):
        return [rename(item, tokens) for item in value]
    if isinstance(value, str):
        return tokens.get(value, value)
    return value


def request_contract(consumer, consumed, profile):
    registered = registered_scene_request(consumer, consumed, model=profile.get("model"))
    if registered is None:
        return None
    request, schema, method = registered
    options = {}
    if consumer != "scene_sample":
        request, options = prepare_scene_call_request(
            request,
            method,
            model=profile.get("model"),
            provider_id=profile.get("provider_id"),
        )
    return {
        "request": request.model_dump(mode="json"),
        "schema": schema.model_json_schema(),
        "options": {
            key: sorted(value) if isinstance(value, set) else value
            for key, value in options.items()
        },
        "max_fix_attempts": 0,
        "transport_retries": False,
    }


def read_set(run, consumer, inputs, *, tokens=None):
    consumed = rename(inputs, tokens or {})
    profile = (run.llm_snapshot_json or {}).get("profile") or {}
    fields = {key: content_hash(value) for key, value in consumed.items()}
    contract = request_contract(consumer, consumed, profile)
    fields["request_contract"] = content_hash(contract)
    return {
        "version": VERSION,
        "consumer": consumer,
        "reusable": contract is not None,
        "model_fingerprint": content_hash(run.llm_snapshot_json or {}),
        "fields": fields,
        "fingerprint": content_hash(fields),
    }


def consumer_kind(key):
    if key.startswith("scene_world_review_group_"):
        return "scene_world_review_group"
    for prefix in (
        "scene_discovery_review_",
        "scene_discovery_identity_",
        "scene_discovery_",
    ):
        if key.startswith(prefix):
            return prefix.rstrip("_")
    return key


async def find_reusable(store, run, scene_index, scene_id, proof, *, tokens=None):
    if not proof.get("reusable"):
        return None
    baseline = (run.reading_plan_json or {}).get("recompute_baseline") or {}
    reference = next(
        (
            item
            for item in baseline.get("receipts", [])
            if item.get("scene_index") == scene_index
        ),
        None,
    )
    if not reference:
        return None
    old = await store.load_frozen(reference["run_key"], reference["attempt_id"])
    if (
        not old
        or old.novel_id != str(store.novel_id)
        or old.payload.get("scene_id") != scene_id
    ):
        return None
    reverse = {token: oid for oid, token in (tokens or {}).items()}
    old_tokens = observation_tokens(old.payload)
    for key, journal in old.payload.items():
        if not isinstance(journal, dict) or journal.get("stage") != "sampled":
            continue
        if journal.get("read_set") != proof or "result" not in journal:
            continue
        canonical = rename(journal["result"], old_tokens)

        # Every old observation reference must have an unambiguous current binding.
        def unmapped(value):
            if isinstance(value, dict):
                return any(unmapped(item) for item in value.values())
            if isinstance(value, list):
                return any(unmapped(item) for item in value)
            return (
                isinstance(value, str)
                and value.startswith("observation:")
                and value not in reverse
            )

        if unmapped(canonical):
            continue
        return {
            "result": rename(canonical, reverse),
            "reused_from": {
                "run_key": old.run_id,
                "attempt_id": old.attempt_id,
                "consumer": key,
            },
        }
    return None

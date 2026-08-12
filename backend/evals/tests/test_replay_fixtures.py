"""Structural guard tests for the R01-R14 redacted replay fixtures.

These tests only inspect fixture structure. They deliberately do not resolve
the pytest references inside ``assertion_map``: that mapping is maintained
manually in ``datasets/replays/README.md`` and points into product test
suites that live outside this eval package.
"""

import hashlib
import json
import re
from pathlib import Path

REPLAYS_DIR = Path(__file__).resolve().parents[1] / "datasets" / "replays"

SCHEMA_VERSION = "replay-v1"
NOVEL_ID = "novel-replay"
TIERS = {"deterministic", "model_diagnostic", "usability"}
REF_KINDS = {
    "page",
    "object",
    "manuscript",
    "suggestion",
    "draft",
    "checkpoint",
    "character",
    "knowledge",
}
REF_STATES = {"current", "superseded", "pending", "candidate"}
REF_VISIBILITIES = {"author", "reader", "role"}
METRIC_VALUE_TYPES = (int, float, bool, str)

SCENARIO_RE = re.compile(r"^r[0-9]{2}-[a-z0-9-]+$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
METRIC_KEY_RE = re.compile(r"^[a-z_]+$")

# Shared with the ask-world dataset: any of these substrings is a redaction
# failure. The blocklist lives here on purpose so the README never has to
# repeat the vault-specific terms.
FORBIDDEN_TERMS = (
    "真名回响",
    "/Users/",
    "白堤",
    "折光塔",
    "三河根桥",
    "远誓塔",
    "千阶城",
    "淤泥",
    "太一",
    "理法之环",
)

EXPECTED_PREFIXES = {f"r{n:02d}" for n in range(1, 15)}


def _fixture_paths() -> list[Path]:
    paths = sorted(REPLAYS_DIR.glob("r[0-9][0-9]-*.json"))
    assert len(paths) == 14, f"expected 14 replay fixtures, found {len(paths)}"
    prefixes = {path.stem[:3] for path in paths}
    assert prefixes == EXPECTED_PREFIXES, prefixes
    return paths


def _fixtures() -> dict[str, dict]:
    return {
        path.stem: json.loads(path.read_text(encoding="utf-8"))
        for path in _fixture_paths()
    }


def _recompute_rule_digest(derivation: dict, ref: dict) -> str:
    template = derivation["template"]
    text = template.format(ref_id=ref["ref_id"], synthetic_title=ref["synthetic_title"])
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _evaluate_digest_expression(expr: str, ref: dict) -> str:
    assert expr.startswith("sha256(") and expr.endswith(")")
    inner = expr[len("sha256(") : -1]
    parts: list[str] = []
    for token in inner.split(" + "):
        if token.startswith("'") and token.endswith("'"):
            parts.append(token[1:-1])
        elif token == "ref_id":
            parts.append(ref["ref_id"])
        elif token == "synthetic_title":
            parts.append(ref["synthetic_title"])
        else:
            raise AssertionError(f"unsupported digest expression token: {token}")
    return hashlib.sha256("".join(parts).encode("utf-8")).hexdigest()


def _rule_covers_ref(rule: dict, ref_id: str) -> bool:
    for index in range(rule["ids_from"], rule["ids_to"] + 1):
        if rule["id_pattern"].format(index) == ref_id:
            return True
    return False


def test_fixture_count_and_single_document_json() -> None:
    for path in _fixture_paths():
        raw = path.read_bytes()
        text = raw.decode("utf-8")
        assert not raw.startswith(b"\xef\xbb\xbf"), f"{path.name} has a BOM"
        data = json.loads(text)
        assert isinstance(data, dict)
        assert data["schema_version"] == SCHEMA_VERSION
        assert path.suffix == ".json"


def test_fixture_files_are_utf8_without_control_characters() -> None:
    for path in _fixture_paths():
        text = path.read_text(encoding="utf-8")
        assert all(ord(ch) >= 0x20 or ch in "\n\r\t" for ch in text), path.name


def test_scenario_ids_are_unique_and_match_file_prefix() -> None:
    seen: set[str] = set()
    for stem, data in _fixtures().items():
        sid = data["scenario_id"]
        assert SCENARIO_RE.match(sid), sid
        assert sid.startswith(stem[:3]), (sid, stem)
        assert sid not in seen, sid
        seen.add(sid)


def test_novel_id_tier_and_initial_ref_fields() -> None:
    for data in _fixtures().values():
        assert data["novel_id"] == NOVEL_ID
        assert data["tier"] in TIERS, data["tier"]
        refs = data["initial_state_refs"]
        assert isinstance(refs, list) and refs
        for ref in refs:
            assert ref["kind"] in REF_KINDS, ref["kind"]
            assert ref["state"] in REF_STATES, ref["state"]
            assert ref["visibility"] in REF_VISIBILITIES, ref["visibility"]
            assert isinstance(ref["synthetic_title"], str)
            assert ref["synthetic_title"].strip()


def test_source_manifest_rules_are_internally_consistent() -> None:
    for data in _fixtures().values():
        rule = data.get("source_manifest_rule")
        if rule is None:
            continue
        derivation = rule["digest_derivation"]
        assert derivation["scheme"] == "sha256"
        assert "{ref_id}" in derivation["template"]
        assert "{synthetic_title}" in derivation["template"]
        if rule["kind"] == "counted_ids":
            count = rule["count"]
            assert rule["ids_to"] - rule["ids_from"] + 1 == count
            assert rule.get("block_count", 1) * rule.get("block_size", count) == count
        elif rule["kind"] == "packets":
            sizes = rule["declared_bytes"]
            assert len(sizes) == rule["count"]
            assert all(size <= rule["per_packet_byte_cap"] for size in sizes)
            assert sum(sizes) == rule["declared_total_bytes"]
            valid_ids = {
                rule["id_pattern"].format(i)
                for i in range(rule["ids_from"], rule["ids_to"] + 1)
            }
            for pair in rule.get("exact_duplicate_pairs", []):
                assert all(pid in valid_ids for pid in pair)
        else:
            raise AssertionError(f"unknown source_manifest_rule kind: {rule['kind']}")


def test_content_digests_are_hex_or_recomputable_derivations() -> None:
    for data in _fixtures().values():
        rule = data.get("source_manifest_rule")
        derivation = (rule or {}).get("digest_derivation")
        for ref in data["initial_state_refs"]:
            digest = ref["content_digest"]
            covered = derivation is not None and _rule_covers_ref(rule, ref["ref_id"])
            if HEX64_RE.match(digest):
                if covered:
                    assert digest == _recompute_rule_digest(derivation, ref)
                continue
            recomputed = _evaluate_digest_expression(digest, ref)
            assert HEX64_RE.match(recomputed), f"bad result for {ref['ref_id']}"
            assert covered, f"expression digest outside a covered rule: {ref['ref_id']}"
            assert recomputed == _recompute_rule_digest(derivation, ref)


def test_author_events_seq_is_contiguous_from_one() -> None:
    for data in _fixtures().values():
        events = data["author_events"]
        assert events, data["scenario_id"]
        seqs = [event["seq"] for event in events]
        assert seqs == list(range(1, len(seqs) + 1)), seqs
        for event in events:
            assert isinstance(event["action"], str) and event["action"].strip()


def test_forbidden_outcomes_and_metrics_shape() -> None:
    for data in _fixtures().values():
        forbidden = data["forbidden_outcomes"]
        assert isinstance(forbidden, list) and len(forbidden) >= 1
        assert all(isinstance(item, str) and item.strip() for item in forbidden)
        metrics = data["metrics"]
        assert 3 <= len(metrics) <= 6, metrics.keys()
        for key, value in metrics.items():
            assert METRIC_KEY_RE.match(key), key
            assert type(value) in METRIC_VALUE_TYPES, (key, type(value).__name__)
            if isinstance(value, str):
                assert len(value) <= 80


def test_assertion_map_entries_have_exactly_one_target() -> None:
    for data in _fixtures().values():
        mapping = data["assertion_map"]
        assert isinstance(mapping, list) and mapping
        for entry in mapping:
            keys = [key for key in ("pytest", "manual") if key in entry]
            assert len(keys) == 1, entry
            assert set(entry) == {keys[0]}, entry
            assert isinstance(entry[keys[0]], str) and entry[keys[0]].strip()


def test_blocklist_covers_every_file_in_replays_dir() -> None:
    files = [path for path in REPLAYS_DIR.glob("*") if path.suffix in {".json", ".md"}]
    assert files
    for path in files:
        text = path.read_text(encoding="utf-8")
        for term in FORBIDDEN_TERMS:
            assert term not in text, f"{path.name} contains {term!r}"

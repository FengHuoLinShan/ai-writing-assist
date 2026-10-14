"""Golden bytes protect frozen RP revisions and planning contracts."""

from uuid import UUID

from modules.interaction.agent_runtime import _hash
from modules.interaction.source_service import _fingerprint


def test_legacy_rp_fingerprints_keep_unicode_spacing_and_uuid_serialization():
    value = {
        "章": "雾港",
        "refs": [UUID("12345678-1234-5678-1234-567812345678"), None],
        "count": 2,
    }
    expected = "468e48c680dad3a85c0af42cdeb94c6b12549a874a5c4673a541dd89bde3cce1"
    assert _fingerprint(value) == expected
    assert _hash(value) == expected

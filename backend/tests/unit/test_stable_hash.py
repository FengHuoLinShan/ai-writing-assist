from __future__ import annotations

import uuid

import pytest

from infrastructure.stable_hash import stable_hash


def test_stable_hash_preserves_majority_bytes() -> None:
    value = {
        "z": 1,
        "text": "雾",
        "id": uuid.UUID("11111111-1111-1111-1111-111111111111"),
    }
    assert stable_hash(value) == (
        "8b3ffbdf872fcbc681ac5cadf520a58652e0e7f43393fff087996f32998e389a"
    )


def test_stable_hash_preserves_strict_and_string_passthrough_variants() -> None:
    with pytest.raises(TypeError):
        stable_hash({"id": uuid.uuid4()}, stringify_unknown=False)
    assert stable_hash("alpha") == (
        "902cf2b465fb076229183b408aad4014266eb9eb72d448754227adc1eeac49b9"
    )
    assert stable_hash("alpha", passthrough_str=True) == (
        "8ed3f6ad685b959ead7022518e1af76cd816f8e8ec7ccdda1ed4018e8f2223f8"
    )

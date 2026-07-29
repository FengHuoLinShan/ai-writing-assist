from __future__ import annotations

from unittest.mock import patch

import pytest

from scripts import dev_schema_guard


def test_schema_is_current_requires_exact_applied_head_set() -> None:
    with patch.object(
        dev_schema_guard,
        "_read_schema_revisions",
        autospec=True,
        return_value=(
            frozenset({"head_revision"}),
            frozenset({"head_revision"}),
        ),
    ) as read_revisions:
        assert dev_schema_guard._schema_is_current() is True

    read_revisions.assert_called_once_with()


@pytest.mark.parametrize(
    ("current", "expected"),
    [
        (frozenset({"old_revision"}), frozenset({"head_revision"})),
        (frozenset(), frozenset({"head_revision"})),
        (frozenset(), frozenset()),
    ],
)
def test_schema_is_current_fails_closed_for_incomplete_or_unknown_state(
    current: frozenset[str],
    expected: frozenset[str],
) -> None:
    with patch.object(
        dev_schema_guard,
        "_read_schema_revisions",
        autospec=True,
        return_value=(current, expected),
    ):
        assert dev_schema_guard._schema_is_current() is False


def test_require_schema_current_fails_with_migration_guidance(capsys) -> None:
    with patch.object(
        dev_schema_guard,
        "_read_schema_revisions",
        autospec=True,
        return_value=(
            frozenset({"old_revision"}),
            frozenset({"head_revision"}),
        ),
    ):
        assert dev_schema_guard.require_schema_current() is False

    captured = capsys.readouterr()
    assert "not at the current Alembic head" in captured.err
    assert "make migrate" in captured.err
    assert "upgrade" not in captured.err


def test_wait_for_schema_current_resumes_after_external_migration(capsys) -> None:
    with (
        patch.object(
            dev_schema_guard,
            "_schema_is_current",
            autospec=True,
            side_effect=[False, True],
        ) as schema_is_current,
        patch.object(dev_schema_guard.time, "sleep", autospec=True) as sleep,
    ):
        dev_schema_guard.wait_for_schema_current(interval_seconds=0.25)

    assert schema_is_current.call_count == 2
    sleep.assert_called_once_with(0.25)
    captured = capsys.readouterr()
    assert "startup is paused" in captured.err
    assert "resuming startup" in captured.out


def test_wait_for_schema_current_rejects_non_positive_interval() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        dev_schema_guard.wait_for_schema_current(interval_seconds=0)

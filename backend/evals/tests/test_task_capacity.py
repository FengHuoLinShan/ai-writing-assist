import pytest

from evals.task_capacity import percentile, require_probe_database


def test_probe_rejects_real_or_remote_database_targets():
    for value in (
        "postgresql://u:p@127.0.0.1/ai_novel_acceptance_guimi",
        "postgresql://u:p@remote/novelcraft_technical_coverage_test",
        "sqlite:///test.db",
    ):
        with pytest.raises(ValueError):
            require_probe_database(value)
    assert require_probe_database(
        "postgresql+asyncpg://u:p@localhost/novelcraft_technical_coverage_test"
    )
    assert percentile([1, 2, 100]) == 100
    assert percentile([]) is None

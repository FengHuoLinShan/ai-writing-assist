from copy import deepcopy

import pytest

from evals.g7_review.calibration import synthetic_case
from evals.g7_review.review_bindings import validate_snapshot_units
from evals.g7_review.reviewer import review_case


@pytest.mark.parametrize("debug", [False, True])
def test_synthetic_fields_bind_actual_rows_sources_and_cutoff(debug):
    case, snapshot, inventory, projects, labels = synthetic_case(debug=debug)
    checked = validate_snapshot_units(case, snapshot, inventory, projects=projects)
    assert checked["actual_rows_bound"] == len(labels)
    future = deepcopy(case)
    future["units"][0]["as_of"]["end_offset"] -= 1
    with pytest.raises(ValueError, match="future_source_attached"):
        validate_snapshot_units(future, snapshot, inventory, projects=projects)
    drift = deepcopy(case)
    drift["units"][0]["fields"][0]["value"] = "forged"
    with pytest.raises(ValueError, match="review_field_value_drift"):
        validate_snapshot_units(drift, snapshot, inventory, projects=projects)


@pytest.mark.asyncio
async def test_review_does_not_accept_unrestricted_executor():
    case, snapshot, inventory, projects, _ = synthetic_case()
    with pytest.raises(ValueError, match="restricted review scope"):
        await review_case(
            executor=None,
            case=case,
            snapshot=snapshot,
            inventory=inventory,
            projects=projects,
        )

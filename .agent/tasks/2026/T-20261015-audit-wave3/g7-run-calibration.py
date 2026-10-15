"""One seeded and one debug review, exclusive markers and complete private ledger."""

import asyncio
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from app.bootstrap import register_container_services
from core.config import get_settings
from core.database import DatabaseManager
from evals.codex_executor import CodexStructuredExecutor, G7ReviewScope
from evals.g7_review.calibration import synthetic_case
from evals.g7_review.reviewer import review_case

PRIVATE = Path("/Users/tywww/.codex/private/g7-review-calibration-20261015")
ROOT = Path(__file__).resolve().parents[4]
CAPTURE = Path(__file__).with_name("g7-native-capture.py")


def save(path, value):
    temporary = path.with_suffix(".tmp")
    with temporary.open("w") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


async def main(stage):
    os.umask(0o077)
    assert stage in {"seeded", "debug"}
    assert get_settings().database_url.endswith(":65196/agent_e2e_g7_review")
    freeze = json.loads((PRIVATE / "freeze.json").read_text())
    for file, digest in freeze["files"].items():
        assert hashlib.sha256((ROOT / file).read_bytes()).hexdigest() == digest, file
    if stage == "debug":
        assert json.loads((PRIVATE / "seeded-result.json").read_text())["all_matched"]
    with (PRIVATE / f"{stage}.started").open("x") as marker:
        marker.write(datetime.now(UTC).isoformat())
        marker.flush()
        os.fsync(marker.fileno())
    setup = json.loads((PRIVATE / "setup-result.json").read_text())
    case, snapshot, inventory, projects, labels = synthetic_case(debug=stage == "debug")
    register_container_services()
    manager = DatabaseManager()
    manager.init()
    record = {
        "stage": stage,
        "status": "started",
        "human_validated": False,
        "input_hash": hashlib.sha256(json.dumps(case).encode()).hexdigest(),
    }
    receipt = PRIVATE / f"{stage}-result.json"
    save(receipt, record)
    try:
        async with manager.session_factory() as db:
            executor = CodexStructuredExecutor(
                command=str(CAPTURE),
                attempts=1,
                timeout_seconds=1200,
                calibration=G7ReviewScope(db, setup["project_id"], setup["snapshot"]),
            )
            response, checked = await review_case(
                executor=executor,
                case=case,
                snapshot=snapshot,
                inventory=inventory,
                projects=projects,
            )
            rows = [
                {
                    "unit_id": unit["id"],
                    "path": field["path"],
                    "expected": labels[unit["id"]][field["path"]],
                    "actual": field["verdict"],
                    "matched": labels[unit["id"]][field["path"]] == field["verdict"],
                }
                for unit in response["reviews"]
                for field in unit["fields"]
            ]
            record.update(
                status="settled",
                rows=rows,
                checked=checked,
                matched=sum(r["matched"] for r in rows),
                total=len(rows),
                all_matched=all(r["matched"] for r in rows),
            )
            save(PRIVATE / f"{stage}-response.json", response)
            save(receipt, record)
            print(
                json.dumps(
                    {
                        k: record[k]
                        for k in ("stage", "status", "matched", "total", "all_matched")
                    }
                ),
                flush=True,
            )
            if not record["all_matched"]:
                raise RuntimeError(
                    "Calibration disagreement; preserve and inspect, never rerun"
                )
    except BaseException as error:
        if record["status"] == "started":
            record.update(status="unknown", error_type=type(error).__name__)
        save(receipt, record)
        raise
    finally:
        await manager.close()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))

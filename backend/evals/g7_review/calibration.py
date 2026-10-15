"""Synthetic cases with fixed labels; no manuscript or historical project data."""

import hashlib

from evals.g7_review.review_bindings import snapshot_hash

DOMAINS = ("人物", "物品", "地点", "组织", "关系", "故事线", "知识", "台账")


def synthetic_case(*, debug=False):
    projects = {"synthetic": "g7-debug" if debug else "g7-seeded"}
    snapshot = {"captured_at": 1, "synthetic": {"facts": [], "writing_drafts": []}}
    units, labels = [], {}
    for index, domain in enumerate(DOMAINS[:3] if debug else DOMAINS):
        identity = f"u{index}"
        subject = f"{domain}记录{index}"
        fact = "钟楼位于北岸" if debug else "石桥位于东岸"
        wrong = "钟楼位于南岸" if debug else "石桥位于西岸"
        text = f"{subject}明确记载：{fact}。"
        content = "开篇。" + text + "本段以外未提供。"
        digest = hashlib.sha256(content.encode()).hexdigest()
        row = {
            "id": identity,
            "novel_id": projects["synthetic"],
            "correct": fact,
            "incorrect": wrong,
            "insufficient": "记录用紫墨书写",
            "empty": None,
        }
        snapshot["synthetic"]["facts"].append(row)
        snapshot["synthetic"]["writing_drafts"].append(
            {
                "id": identity,
                "novel_id": projects["synthetic"],
                "chapter_index": index + 1,
                "version_number": 1,
                "content": content,
                "content_hash": digest,
            }
        )
        units.append(
            {
                "id": identity,
                "arm": "synthetic",
                "table": "facts",
                "row_key": {"id": identity},
                "holder_id": None,
                "as_of": {"chapter_index": index + 1, "end_offset": 3 + len(text)},
                "full_source_scope": False,
                "sources": [
                    {
                        "id": identity,
                        "draft_id": identity,
                        "version_number": 1,
                        "content_hash": digest,
                        "chapter_index": index + 1,
                        "start_offset": 3,
                        "end_offset": 3 + len(text),
                        "text": text,
                        "range_hash": hashlib.sha256(text.encode()).hexdigest(),
                    }
                ],
                "fields": [
                    {"path": key, "value": row[key], "kind": "semantic"}
                    for key in ("correct", "incorrect", "insufficient", "empty")
                ],
            }
        )
        labels[identity] = {
            "correct": "supported",
            "incorrect": "unsupported",
            "insufficient": "uncertain",
            "empty": "not_populated",
        }
    inventory = {
        "tables": {
            "facts": {
                "columns": [
                    {
                        "column_name": key,
                        "data_type": "text",
                        "constraints": ["PRIMARY KEY"] if key == "id" else [],
                    }
                    for key in snapshot["synthetic"]["facts"][0]
                ]
            }
        }
    }
    return (
        {"snapshot_hash": snapshot_hash(snapshot), "units": units},
        snapshot,
        inventory,
        projects,
        labels,
    )

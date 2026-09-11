"""Separate optional interpretation from source/structure decisions."""

OPTIONAL_FIELDS = frozenset({"narrative_tag", "narrative_function", "emotional_beat"})


def needs_scene_decision(*, source, status, meta):
    if meta.get("review_issues_version") == 1:
        return any(
            issue.get("required") is True for issue in meta.get("review_issues", [])
        )
    if meta.get("needs_review"):
        return True  # Legacy free text is not sufficient to clear an unresolved problem.
    auto_verified = (
        source == "deep_import"
        and meta.get("auto_ingested") is True
        and bool(meta.get("phase1b_source_fingerprint"))
        and not meta.get("phase1a_fallback")
    )
    return (
        source in {"deep_import", "ai_generated"}
        and status in {"draft", "candidate"}
        and not meta.get("reviewed_at")
        and not auto_verified
    )

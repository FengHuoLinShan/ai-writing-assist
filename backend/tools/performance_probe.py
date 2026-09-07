"""Local-only synthetic performance fixture and runtime (never a production entrypoint).

Run from backend: uv run --locked --extra ci -- python -m tools.performance_probe seed
The exact loopback database is intentional. This tool never falls back to .env.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import secrets
import subprocess
import sys
import time
import uuid
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".test-artifacts" / "performance"
DATABASE = (
    "postgresql+asyncpg://perf_test:synthetic_perf_only@127.0.0.1:55439/e448_perf_test"
)
NAMESPACE = uuid.UUID("5d88b607-8710-4ed4-b5cb-7b53b42fd606")


def provenance() -> dict:
    root = ROOT.parent
    diff = subprocess.check_output(["git", "diff", "HEAD"], cwd=root)
    files = [
        "backend/modules/world/repositories.py",
        "backend/modules/world/services/core/entity_alias_service.py",
        "backend/tools/performance_probe.py",
        "frontend-console/scripts/performance-probe.mjs",
    ]
    return {
        "sha": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True
        ).strip(),
        "tracked_diff_sha256": hashlib.sha256(diff).hexdigest(),
        "source_hashes": {
            name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in files
        },
    }


async def seed_aliases() -> None:
    """Separate, immutable synthetic projects; never alter the original S/L data."""
    from sqlalchemy import select

    from app.bootstrap import _register_orm_models
    from core.database import get_manager
    from modules.project.models import Project
    from modules.world.models import CoreEntity

    _register_orm_models()
    manager = get_manager()
    manifest = {"provenance": provenance(), "profiles": {}}
    try:
        async with manager.session() as db:
            for tier, count in [("AS", 300), ("AL", 3000)]:
                pid = ident(f"{tier}-aliases")
                existing = await db.get(Project, pid)
                if existing is not None:
                    assert existing.owner_id == ident("owner"), "Fixture owner drift"
                else:
                    db.add(
                        Project(
                            id=pid, owner_id=ident("owner"), title=f"性能诊断 {tier} 别名"
                        )
                    )
                    await db.flush()
                    for i in range(count):
                        db.add(
                            CoreEntity(
                                id=ident(f"{tier}-entity-{i}"),
                                novel_id=pid,
                                entity_type="location",
                                name=f"河港地点{i:04d}",
                                summary=f"航路上的第{i}处地点。" * 8,
                                status="canonical",
                                importance=(i % 10) / 10,
                                content_json={
                                    "aliases": [
                                        f"旧港{i:04d}",
                                        {
                                            "alias": f"河港别称{i:04d}",
                                            "type": "name",
                                            "kind": "name",
                                            "status": "active",
                                        },
                                        {
                                            "alias": f"待核港{i:04d}",
                                            "type": "name",
                                            "kind": "name",
                                            "status": "candidate",
                                            "needs_review": True,
                                            "confidence": 0.0,
                                        },
                                    ]
                                },
                            )
                        )
                await db.flush()
                rows = (
                    await db.execute(
                        select(
                            CoreEntity.id,
                            CoreEntity.name,
                            CoreEntity.status,
                            CoreEntity.importance,
                            CoreEntity.content_json,
                        )
                        .where(CoreEntity.novel_id == pid)
                        .order_by(CoreEntity.id)
                    )
                ).all()
                payload = json.dumps(
                    [list(row) for row in rows],
                    default=str,
                    ensure_ascii=False,
                    sort_keys=True,
                ).encode()
                assert len(rows) == count
                assert all(len(row.content_json["aliases"]) == 3 for row in rows)
                manifest["profiles"][tier] = {
                    "project_id": str(pid),
                    "entities": len(rows),
                    "aliases": count * 3,
                    "review_aliases": count,
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "bytes": len(payload),
                }
        target = OUT / "round2" / "alias-fixture.json"
        target.parent.mkdir(mode=0o700, exist_ok=True)
        if target.exists():
            assert json.loads(target.read_text())["profiles"] == manifest["profiles"], (
                "Alias fixture drift"
            )
        else:
            target.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
        print(json.dumps(manifest, ensure_ascii=False))
    finally:
        await manager.close()


def ident(name: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, name)


def configure() -> None:
    # core.config loads backend/.env at import time; never inherit operator config.
    if (ROOT / ".env").exists():
        raise RuntimeError("Run diagnostics in an isolated checkout without backend/.env")
    OUT.mkdir(parents=True, exist_ok=True, mode=0o700)
    OUT.chmod(0o700)
    config = OUT / "runtime-private.json"
    if not config.exists():
        values = {
            "DATABASE_URL": DATABASE,
            "E2E_DATABASE_URL": DATABASE,
            "APP_ENV": "test",
            "AUTH_MODE": "public",
            "DEBUG": "false",
            "AUTH_SECRET_KEY": secrets.token_hex(32),
            "LLM_SETTINGS_ENCRYPTION_KEY": "",
            "PUBLIC_BASE_URL": "http://127.0.0.1:18080",
            "ALLOWED_ORIGINS": "http://127.0.0.1:18080",
            "SMTP_HOST": "127.0.0.1",
            "SMTP_USERNAME": "synthetic",
            "SMTP_PASSWORD": "synthetic-unused",
            "SMTP_FROM": "diagnostic@example.invalid",
            "SUPPORT_EMAIL": "diagnostic@example.invalid",
            "LLM_HEALTH_REQUIRED": "false",
            "LLM_RATE_LIMIT_PER_MINUTE": "0",
            "LLM_RETRY_MAX_ATTEMPTS": "1",
            "LLM_TRUST_ENV": "false",
            "LLM_PROXY_URL": "",
            "EMBEDDING_PROVIDER": "openai",
            "EMBEDDING_BASE_URL": "http://127.0.0.1:9/v1",
            "EMBEDDING_API_KEY": "synthetic-unavailable",
            "RAG_PREWARM_ON_STARTUP": "false",
            "RAG_QUERY_PLANNER_ENABLED": "false",
            "RERANKER_ENABLED": "false",
            "TASK_WORKER_MAX_CONCURRENT_TASKS": "1",
            "POOL_SIZE": "10",
            "MAX_OVERFLOW": "20",
            "HTTP_RATE_LIMIT_PER_MINUTE": "6000",
            "HTTP_RATE_LIMIT_BURST": "200",
            "LOG_LEVEL": "INFO",
        }
        with config.open("x") as stream:
            json.dump(values, stream)
        config.chmod(0o600)
    values = json.loads(config.read_text())
    if (
        values.get("DATABASE_URL") != DATABASE
        or values.get("E2E_DATABASE_URL") != DATABASE
    ):
        raise RuntimeError("Refusing a changed diagnostic database target")
    # Ignore credentials inherited from an operator's shell.
    for key in list(os.environ):
        if key.startswith(
            (
                "LLM_",
                "OPENAI_",
                "DEEPSEEK_",
                "KIMI_",
                "MINIO_",
                "MAP_ATLAS_",
                "WORLD_OBJECT_S3_",
            )
        ):
            os.environ.pop(key)
    os.environ.update(values)


def prose(chapter: int, size: int) -> str:
    paragraph = (
        f"第{chapter}章。旅人在河边整理航行记录，确认城门、桥梁与仓库的位置。"
        "风从山口吹来，守桥人交还昨日保存的地图。\n"
    )
    return (paragraph * (size // len(paragraph) + 1))[:size]


async def seed() -> None:
    from sqlalchemy import func, select, text

    from app.bootstrap import _register_orm_models
    from core.config import get_settings
    from core.database import get_manager
    from modules.account.contracts import BOOTSTRAP_ACCOUNT_ID
    from modules.account.models import Account
    from modules.account.services import service
    from modules.interaction.models import (
        InteractionBranchSelection,
        InteractionJourney,
        InteractionMessageNode,
    )
    from modules.project.models import Project
    from modules.world.models import CoreEntity, EntityRelation
    from modules.writing.models import WritingDraft

    _register_orm_models()
    manager = get_manager()
    manager.init()
    manifest = {
        "seed": str(NAMESPACE),
        "sha": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "profiles": {},
    }
    now = datetime.now(UTC)
    try:
        async with manager.session() as db:
            if await db.scalar(text("SELECT current_database()")) != "e448_perf_test":
                raise RuntimeError("Wrong database")
            bootstrap = await db.get(Account, BOOTSTRAP_ACCOUNT_ID)
            if bootstrap is None:
                bootstrap = Account(
                    id=BOOTSTRAP_ACCOUNT_ID, support_code="PERF-BOOTSTRAP"
                )
                db.add(bootstrap)
            bootstrap.legacy_claimed_at = now
            account = await db.get(Account, ident("owner"))
            if account is None:
                account = Account(id=ident("owner"), support_code="PERF-SYNTHETIC")
                db.add(account)
            await db.flush()
            for tier, chapters, entities, nodes in [
                ("S", 30, 300, 40),
                ("L", 300, 3000, 400),
            ]:
                pid, jid, rpid = (
                    ident(f"{tier}-author"),
                    ident(f"{tier}-journey"),
                    ident(f"{tier}-rp"),
                )
                if await db.get(Project, pid) is None:
                    db.add_all(
                        [
                            Project(
                                id=pid,
                                owner_id=account.id,
                                title=f"性能诊断 {tier} 合成作品",
                            ),
                            Project(
                                id=rpid,
                                owner_id=account.id,
                                project_kind="interaction",
                                title=f"性能诊断 {tier} 合成旅程",
                            ),
                        ]
                    )
                    await db.flush()
                    db.add_all(
                        [
                            WritingDraft(
                                id=ident(f"{tier}-draft-{chapter}-{version}"),
                                novel_id=pid,
                                chapter_index=chapter,
                                version_number=version,
                                status="draft" if version == 3 else "published",
                                title=f"第 {chapter} 章 航行记录",
                                content=prose(chapter, 3000),
                                content_hash=hashlib.sha256(
                                    prose(chapter, 3000).encode()
                                ).hexdigest(),
                            )
                            for chapter in range(1, chapters + 1)
                            for version in range(1, 4)
                        ]
                    )
                    db.add_all(
                        [
                            CoreEntity(
                                id=ident(f"{tier}-entity-{i}"),
                                novel_id=pid,
                                entity_type="location",
                                name=f"河港地点{i:04d}",
                                summary=f"航路上的第{i}处地点。" * 8,
                                status="canonical",
                                importance=(i % 10) / 10,
                            )
                            for i in range(entities)
                        ]
                    )
                    await db.flush()
                    db.add_all(
                        [
                            EntityRelation(
                                id=ident(f"{tier}-relation-{i}-{jump}"),
                                novel_id=pid,
                                source_id=ident(f"{tier}-entity-{i}"),
                                target_id=ident(f"{tier}-entity-{(i + jump) % entities}"),
                                relation_type="connected_to",
                                relation_kind="spatial",
                                status="canonical",
                            )
                            for i in range(entities)
                            for jump in (1, 2, 3)
                        ]
                    )
                    journey = InteractionJourney(
                        id=jid,
                        novel_id=rpid,
                        owner_id=account.id,
                        title=f"性能诊断 {tier} 合成旅程",
                        opening_text="从河港开始一段航行。",
                        latest_activity_at=now,
                    )
                    db.add(journey)
                    await db.flush()
                    parent = None
                    for i in range(nodes):
                        nid = ident(f"{tier}-node-{i}")
                        db.add(
                            InteractionMessageNode(
                                id=nid,
                                novel_id=rpid,
                                journey_id=jid,
                                parent_node_id=parent,
                                role="user" if i % 2 == 0 else "assistant",
                                content=prose(i + 1, 1000),
                                token_estimate=1000,
                                created_at=now - timedelta(seconds=nodes - i),
                            )
                        )
                        await db.flush()
                        db.add(
                            InteractionBranchSelection(
                                novel_id=rpid,
                                journey_id=jid,
                                parent_node_id=parent,
                                parent_key=str(parent) if parent else "__root__",
                                selected_child_node_id=nid,
                            )
                        )
                        parent = nid
                    journey.selected_leaf_node_id = parent
                manifest["profiles"][tier] = {
                    "project_id": str(pid),
                    "journey_id": str(jid),
                    "chapters": chapters,
                    "characters_per_chapter": 3000,
                    "versions_per_chapter": 3,
                    "entities": entities,
                    "relations": entities * 3,
                    "selected_nodes": nodes,
                    "first_draft_id": str(ident(f"{tier}-draft-1-3")),
                    "text_sha256": hashlib.sha256(
                        "".join(prose(i, 3000) for i in range(1, chapters + 1)).encode()
                    ).hexdigest(),
                    "text_bytes": sum(
                        len(prose(i, 3000).encode()) for i in range(1, chapters + 1)
                    ),
                }
            await db.flush()
            login = await service.create_session(
                db, account=account, identity_type="email", settings=get_settings()
            )
            cookies = [
                {
                    "name": name,
                    "value": value,
                    "domain": "127.0.0.1",
                    "path": "/",
                    "httpOnly": name == "aaw_session",
                    "secure": False,
                    "sameSite": "Lax",
                }
                for name, value in [
                    ("aaw_session", login.session_token),
                    ("aaw_csrf", login.csrf_token),
                ]
            ]
            (OUT / "browser-private.json").write_text(
                json.dumps({"cookies": cookies, "origins": []})
            )
            (OUT / "browser-private.json").chmod(0o600)
            manifest["counts"] = {
                model.__tablename__: await db.scalar(
                    select(func.count()).select_from(model)
                )
                for model in [
                    Project,
                    WritingDraft,
                    CoreEntity,
                    EntityRelation,
                    InteractionJourney,
                    InteractionMessageNode,
                ]
            }
        (OUT / "fixture.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2)
        )
        (OUT / "synthetic-S.txt").write_text(
            "\n\n".join(f"第{i}章 航行\n{prose(i, 3000)}" for i in range(1, 31))
        )
        (OUT / "synthetic-L.txt").write_text(
            "\n\n".join(f"第{i}章 航行\n{prose(i, 3000)}" for i in range(1, 301))
        )
        print(json.dumps(manifest, ensure_ascii=False))
    finally:
        await manager.close()


async def observe(seconds: int) -> None:
    """Metadata-only snapshots; no SQL text, task metadata, result, or content."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(DATABASE, pool_size=1, max_overflow=0)
    deadline = time.monotonic() + seconds
    iteration = 0
    try:
        with (OUT / "database-samples.jsonl").open("a") as output:
            while time.monotonic() < deadline:
                async with engine.connect() as db:
                    activity = [
                        dict(row)
                        for row in (
                            await db.execute(
                                text(
                                    "SELECT pid,state,wait_event_type,wait_event,"
                                    "extract(epoch from now()-xact_start) "
                                    "AS transaction_seconds,pg_blocking_pids(pid) "
                                    "AS blockers FROM pg_stat_activity "
                                    "WHERE datname=current_database() "
                                    "AND pid<>pg_backend_pid()"
                                )
                            )
                        ).mappings()
                    ]
                    tasks = [
                        dict(row)
                        for row in (
                            await db.execute(
                                text(
                                    "SELECT id,task_type,status,created_at,started_at,"
                                    "finished_at,heartbeat_at,attempt "
                                    "FROM async_tasks ORDER BY created_at DESC LIMIT 100"
                                )
                            )
                        ).mappings()
                    ]
                processes = None
                pid_file = OUT / "processes.json"
                if iteration % 5 == 0 and pid_file.exists():
                    pids = json.loads(pid_file.read_text())
                    processes = subprocess.run(
                        [
                            "ps",
                            "-p",
                            ",".join(str(pid) for pid in pids.values()),
                            "-o",
                            "pid=,pcpu=,rss=,etime=",
                        ],
                        capture_output=True,
                        text=True,
                        check=False,
                    ).stdout.strip()
                output.write(
                    json.dumps(
                        {
                            "time": datetime.now(UTC).isoformat(),
                            "activity": activity,
                            "tasks": tasks,
                            "processes_pid_cpu_rss_kib_elapsed": processes,
                        },
                        default=str,
                    )
                    + "\n"
                )
                output.flush()
                iteration += 1
                await asyncio.sleep(2)
    finally:
        await engine.dispose()


async def reset_fixture() -> None:
    from sqlalchemy import select

    from app.bootstrap import _register_orm_models
    from core.database import get_manager
    from modules.writing.models import WritingDraft

    _register_orm_models()
    manager = get_manager()
    try:
        async with manager.session() as db:
            for tier in ("S", "L"):
                for chapter in (1, 2):
                    draft = (
                        await db.execute(
                            select(WritingDraft).where(
                                WritingDraft.id == ident(f"{tier}-draft-{chapter}-3"),
                                WritingDraft.novel_id == ident(f"{tier}-author"),
                            )
                        )
                    ).scalar_one()
                    draft.content = prose(chapter, 3000)
                    draft.content_hash = hashlib.sha256(
                        draft.content.encode()
                    ).hexdigest()
    finally:
        await manager.close()


def epub() -> None:
    for tier, count in [("S", 30), ("L", 300)]:
        # Only title lines may match the application's chapter heading parser.
        bodies = {
            i: prose(i, 3000).replace(f"第{i}章。", "旅途记录。")
            for i in range(1, count + 1)
        }
        (OUT / f"synthetic-{tier}.txt").write_text(
            "\n\n".join(f"第{i}章 航行\n{bodies[i]}" for i in bodies)
        )
        with zipfile.ZipFile(OUT / f"synthetic-{tier}.epub", "w") as book:
            book.writestr("mimetype", "application/epub+zip")
            book.writestr(
                "META-INF/container.xml",
                '<?xml version="1.0"?><container version="1.0" '
                'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                '<rootfiles><rootfile full-path="content.opf" '
                'media-type="application/oebps-package+xml"/></rootfiles></container>',
            )
            items, spine = [], []
            for i in range(1, count + 1):
                items.append(
                    f'<item id="c{i}" href="c{i}.xhtml" '
                    'media-type="application/xhtml+xml"/>'
                )
                spine.append(f'<itemref idref="c{i}"/>')
                book.writestr(
                    f"c{i}.xhtml",
                    '<html xmlns="http://www.w3.org/1999/xhtml"><head>'
                    f"<title>第{i}章 航行</title></head><body>"
                    f"<h1>第{i}章 航行</h1><p>{bodies[i]}</p></body></html>",
                )
            book.writestr(
                "content.opf",
                '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" '
                'unique-identifier="uid" version="3.0"><metadata '
                'xmlns:dc="http://purl.org/dc/elements/1.1/">'
                '<dc:identifier id="uid">synthetic</dc:identifier>'
                "<dc:title>合成诊断</dc:title><dc:language>zh</dc:language>"
                "</metadata><manifest>"
                + "".join(items)
                + "</manifest><spine>"
                + "".join(spine)
                + "</spine></package>",
            )


async def queries(label: str) -> None:
    """Instrumented ASGI pass, separate from uninstrumented HTTP/browser runs."""
    import contextvars

    import httpx
    from sqlalchemy import event, text

    from app.main import app
    from core.database import get_manager
    from modules.world.repositories import CoreEntityRepository
    from modules.world.services.core import entity_service

    current = contextvars.ContextVar("diagnostic_queries", default=None)
    private = json.loads((OUT / "browser-private.json").read_text())
    cookies = {item["name"]: item["value"] for item in private["cookies"]}
    profiles = json.loads((OUT / "fixture.json").read_text())["profiles"]
    alias_file = OUT / "round2" / "alias-fixture.json"
    if alias_file.exists():
        profiles.update(json.loads(alias_file.read_text())["profiles"])
    result = {
        "provenance": provenance(),
        "label": label,
        "instrumented": True,
        "samples": [],
    }
    slowest = {"ms": 0.0}

    def timed(name, function):
        async def call(*args, **kwargs):
            start = time.perf_counter()
            try:
                return await function(*args, **kwargs)
            finally:
                frame = current.get()
                if frame is not None:
                    frame["stages"][name] = [start, time.perf_counter()]

        return call

    originals = [
        (CoreEntityRepository, "list_ranking_candidates"),
        (CoreEntityRepository, "get_by_ids"),
        (entity_service.WorldEntityService, "_list_hot"),
    ]
    originals = [(owner, name, getattr(owner, name)) for owner, name in originals]
    original_get = entity_service._container_get

    def get_port(name):
        port = original_get(name)
        return (
            timed("activity", port) if name == "rag.get_entity_activity_stats" else port
        )

    target = OUT / "round2" / f"queries-{label}-{time.time_ns()}.json"
    target.parent.mkdir(mode=0o700, exist_ok=True)
    try:
        async with app.router.lifespan_context(app):
            engine = get_manager().engine.sync_engine

            def before(_conn, _cursor, _statement, _parameters, context, _many):
                context.diagnostic_start = time.perf_counter()

            def after(_conn, _cursor, statement, parameters, context, _many):
                frame = current.get()
                if frame is None:
                    return
                elapsed = (time.perf_counter() - context.diagnostic_start) * 1000
                frame["queries"].append(
                    {
                        "ms": elapsed,
                        "statement_hash": hashlib.sha256(statement.encode()).hexdigest(),
                        "kind": statement.split(None, 1)[0],
                    }
                )
                if (
                    tier in {"L", "AL"}
                    and view == "review-aliases"
                    and statement.lstrip().startswith("SELECT")
                    and "FROM core_entities" in statement
                    and "FOR UPDATE" not in statement
                    and "FOR SHARE" not in statement
                    and elapsed > slowest["ms"]
                ):
                    slowest.update(ms=elapsed, sql=statement, params=parameters)

            event.listen(engine, "before_cursor_execute", before)
            event.listen(engine, "after_cursor_execute", after)
            for owner, name, function in originals:
                setattr(owner, name, timed(name, function))
            entity_service._container_get = get_port
            try:
                async with get_manager().engine.connect() as connection:
                    result["queue_before"] = [
                        dict(row)
                        for row in (
                            await connection.execute(
                                text(
                                    "SELECT status,count(*) FROM async_tasks "
                                    "GROUP BY status"
                                )
                            )
                        ).mappings()
                    ]
                assert not any(
                    row["status"] in {"pending", "running"}
                    for row in result["queue_before"]
                ), "Queue must be idle"
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app),
                    base_url="http://127.0.0.1:18080",
                    cookies=cookies,
                ) as client:
                    for tier, profile in profiles.items():
                        for view in ("normal", "hot", "review-aliases"):
                            route = "/api/world/entities"
                            params = {
                                "novel_id": profile["project_id"],
                                "view_mode": view,
                                "q": "河港",
                                "limit": 20,
                            }
                            if view == "review-aliases":
                                route = "/api/world/aliases"
                                params = {
                                    "novel_id": profile["project_id"],
                                    "display_state": "review",
                                    "limit": 1,
                                    "skip": 0,
                                }
                            warm = await client.get(route, params=params)
                            assert warm.status_code == 200, warm.status_code
                            for i in range(30):
                                if i % 10 == 0:
                                    await asyncio.sleep(0.1)
                                frame = {"queries": [], "stages": {}}
                                token = current.set(frame)
                                start = time.perf_counter()
                                try:
                                    response = await client.get(route, params=params)
                                    payload = response.json()
                                    sample = {
                                        "tier": tier,
                                        "view": view,
                                        "batch": i // 10,
                                        "iteration": i,
                                        "status": response.status_code,
                                        "ms": (time.perf_counter() - start) * 1000,
                                        "bytes": len(response.content),
                                        "total": payload.get("total"),
                                        "response_sha256": hashlib.sha256(
                                            json.dumps(
                                                payload,
                                                sort_keys=True,
                                                ensure_ascii=False,
                                            ).encode()
                                        ).hexdigest(),
                                        "queries": frame["queries"],
                                        "stages_ms": {
                                            name: (stop - begin) * 1000
                                            for name, (begin, stop) in frame[
                                                "stages"
                                            ].items()
                                        },
                                    }
                                    bounds = frame["stages"]
                                    if {
                                        "activity",
                                        "get_by_ids",
                                        "_list_hot",
                                    } <= bounds.keys():
                                        sample["stages_ms"][
                                            "ranking_between_activity_and_page"
                                        ] = (
                                            bounds["get_by_ids"][0]
                                            - bounds["activity"][1]
                                        ) * 1000
                                        sample["stages_ms"]["response_after_page"] = (
                                            bounds["_list_hot"][1]
                                            - bounds["get_by_ids"][1]
                                        ) * 1000
                                    result["samples"].append(sample)
                                    assert response.status_code == 200, (
                                        response.status_code
                                    )
                                    expected = (
                                        profile.get("review_aliases", 0)
                                        if view == "review-aliases"
                                        else profile["entities"]
                                    )
                                    assert payload["total"] == expected, (
                                        tier,
                                        view,
                                        payload["total"],
                                        expected,
                                    )
                                finally:
                                    current.reset(token)
            finally:
                for owner, name, function in originals:
                    setattr(owner, name, function)
                entity_service._container_get = original_get
                event.remove(engine, "before_cursor_execute", before)
                event.remove(engine, "after_cursor_execute", after)
            if "sql" in slowest:
                async with get_manager().engine.connect() as connection:
                    await connection.exec_driver_sql("SET TRANSACTION READ ONLY")
                    await connection.exec_driver_sql("SET LOCAL statement_timeout='5s'")
                    result["alias_plan"] = {
                        "observed_driver_ms": slowest["ms"],
                        "statement_hash": hashlib.sha256(
                            slowest["sql"].encode()
                        ).hexdigest(),
                        "plan": (
                            await connection.exec_driver_sql(
                                "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) "
                                + slowest["sql"],
                                slowest["params"],
                            )
                        ).scalar_one(),
                    }
        result["status"] = "ok"
    except BaseException as exc:
        result.update(status="failed", error_type=type(exc).__name__)
        raise
    finally:
        target.write_text(json.dumps(result, indent=2))
        print(target)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=[
            "migrate",
            "seed",
            "alias-seed",
            "reset",
            "epub",
            "api",
            "worker",
            "observe",
            "queries",
        ],
    )
    parser.add_argument("--seconds", type=int, default=1800)
    parser.add_argument(
        "--label", choices=["before", "after", "repeat"], default="repeat"
    )
    args = parser.parse_args()
    configure()
    os.chdir(ROOT)
    if args.command == "migrate":
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)
    elif args.command == "seed":
        asyncio.run(seed())
    elif args.command == "alias-seed":
        asyncio.run(seed_aliases())
    elif args.command == "reset":
        asyncio.run(reset_fixture())
    elif args.command == "epub":
        epub()
    elif args.command == "queries":
        asyncio.run(queries(args.label))
    elif args.command == "api":
        os.execv(
            sys.executable,
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                "18000",
            ],
        )
    elif args.command == "worker":
        os.execv(sys.executable, [sys.executable, "run_worker.py"])
    else:
        asyncio.run(observe(args.seconds))


if __name__ == "__main__":
    main()

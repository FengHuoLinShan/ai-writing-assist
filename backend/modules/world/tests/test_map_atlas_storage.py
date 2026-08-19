from __future__ import annotations

import base64
import hashlib
import struct
import uuid
import zlib
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from botocore.exceptions import ClientError
from PIL import Image

from modules.world.map_atlas_models import MapAtlasNode, MapAtlasPage, MapAtlasRun
from modules.world.map_atlas_storage import (
    MapAtlasStorage,
    normalize_map_upload,
    page_object_key,
    project_object_prefix,
    require_owned_page_object_key,
    require_page_object_key,
    require_project_object_prefix,
    validate_png,
)
from modules.world.map_atlas_tasks import handle_map_atlas_storage_cleanup

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC"
)


def _storage_settings(endpoint_url: str) -> SimpleNamespace:
    return SimpleNamespace(
        map_atlas_s3_bucket="private",
        map_atlas_s3_region="us-east-1",
        map_atlas_s3_endpoint_url=endpoint_url,
        map_atlas_s3_access_key_id="fixture-key",
        map_atlas_s3_secret_access_key="fixture-secret",
        map_atlas_s3_force_path_style=False,
    )


@pytest.mark.parametrize(
    "endpoint_url",
    [
        "http://169.254.169.254",
        "http://localhost.evil.example",
        "https://user:secret@s3.example.com",
        "https://s3.example.com?bucket=other",
        "https://s3.example.com?",
        "https://s3.example.com#fragment",
        "https://s3.example.com#",
    ],
)
def test_storage_rejects_unsafe_s3_endpoint_before_client_creation(
    endpoint_url: str,
) -> None:
    with (
        patch(
            "modules.world.map_atlas_storage.get_settings",
            autospec=True,
            return_value=_storage_settings(endpoint_url),
        ),
        patch(
            "modules.world.map_atlas_storage.boto3.client",
            autospec=True,
        ) as client_factory,
        pytest.raises(RuntimeError, match="MAP_ATLAS_S3_ENDPOINT_URL"),
    ):
        MapAtlasStorage()

    client_factory.assert_not_called()


@pytest.mark.parametrize(
    ("endpoint_url", "expected"),
    [
        ("", None),
        ("http://localhost:9000", "http://localhost:9000"),
        ("http://127.0.0.1:9000", "http://127.0.0.1:9000"),
        ("http://[::1]:9000", "http://[::1]:9000"),
        ("https://s3.example.com", "https://s3.example.com"),
    ],
)
def test_storage_accepts_aws_https_and_local_development_endpoints(
    endpoint_url: str,
    expected: str | None,
) -> None:
    with (
        patch(
            "modules.world.map_atlas_storage.get_settings",
            autospec=True,
            return_value=_storage_settings(endpoint_url),
        ),
        patch(
            "modules.world.map_atlas_storage.boto3.client",
            autospec=True,
        ) as client_factory,
    ):
        MapAtlasStorage()

    assert client_factory.call_args.kwargs["endpoint_url"] == expected
    config = client_factory.call_args.kwargs["config"]
    assert config.proxies == ({} if expected and expected.startswith("http://") else None)


@pytest.mark.parametrize(
    "payload",
    [
        PNG[:-1],
        PNG + b"trailing",
        bytes(bytearray(PNG[:40]) + bytearray([PNG[40] ^ 1]) + bytearray(PNG[41:])),
    ],
    ids=["truncated", "after-iend", "bad-crc"],
)
def test_png_validator_rejects_incomplete_or_corrupted_files(payload: bytes) -> None:
    with pytest.raises(ValueError):
        validate_png(payload)


def test_map_upload_normalizes_jpeg_to_metadata_free_png() -> None:
    source = BytesIO()
    Image.new("RGB", (2, 3), "red").save(
        source, format="JPEG", exif=b"Exif\x00\x00metadata"
    )

    payload, metadata = normalize_map_upload(source.getvalue())

    assert payload.startswith(b"\x89PNG")
    assert (metadata.width, metadata.height) == (2, 3)
    with Image.open(BytesIO(payload)) as image:
        assert image.info == {}


def test_map_upload_rejects_disguised_image() -> None:
    with pytest.raises(ValueError, match="PNG 或 JPEG"):
        normalize_map_upload(b"GIF89a" + b"\x00" * 100)


def test_cleanup_targets_accept_only_canonical_project_and_page_paths() -> None:
    novel_id, page_id = uuid.uuid4(), uuid.uuid4()
    prefix = project_object_prefix(str(novel_id))
    key = page_object_key(str(novel_id), str(page_id))
    attempt_key = page_object_key(
        str(novel_id),
        str(page_id),
        attempt_token=f"{uuid.uuid4()}-2",
    )
    assert require_project_object_prefix(prefix) == prefix
    assert require_page_object_key(key) == key
    assert require_page_object_key(attempt_key) == attempt_key
    for invalid in ("map-atlas/", f"map-atlas/{novel_id}/pages/", "other/"):
        with pytest.raises(ValueError):
            require_project_object_prefix(invalid)
    with pytest.raises(ValueError):
        require_page_object_key(f"map-atlas/{novel_id}/pages/{page_id}/other.png")


def test_page_object_key_must_belong_to_expected_project_and_page() -> None:
    novel_id, page_id = uuid.uuid4(), uuid.uuid4()
    key = page_object_key(str(novel_id), str(page_id))

    assert require_owned_page_object_key(key, str(novel_id), str(page_id)) == key
    with pytest.raises(ValueError, match="owner mismatch"):
        require_owned_page_object_key(key, str(uuid.uuid4()), str(page_id))
    with pytest.raises(ValueError, match="owner mismatch"):
        require_owned_page_object_key(key, str(novel_id), str(uuid.uuid4()))


@pytest.mark.asyncio
async def test_storage_streams_chunks_and_closes_s3_body() -> None:
    chunks = [PNG[:11], PNG[11:], b""]
    body = MagicMock()
    body.read.side_effect = lambda _size: chunks.pop(0)
    client = MagicMock()
    client.get_object.return_value = {
        "Body": body,
        "ContentLength": len(PNG),
    }
    storage = MapAtlasStorage(client=client, bucket="private")

    streamed = [chunk async for chunk in storage.iter_png_chunks("private-key")]

    assert b"".join(streamed) == PNG
    body.close.assert_called_once_with()


@pytest.mark.asyncio
async def test_optional_png_read_returns_none_only_for_missing_object() -> None:
    client = MagicMock()
    client.get_object.side_effect = ClientError(
        {
            "Error": {"Code": "NoSuchKey"},
            "ResponseMetadata": {"HTTPStatusCode": 404},
        },
        "GetObject",
    )
    storage = MapAtlasStorage(client=client, bucket="private")

    assert await storage.get_png_if_exists("missing") is None


@pytest.mark.asyncio
async def test_prefix_cleanup_fails_on_partial_delete_response() -> None:
    client = MagicMock()
    client.list_objects_v2.return_value = {
        "Contents": [{"Key": "map-atlas/n/pages/a/image.png"}]
    }
    client.delete_objects.return_value = {
        "Errors": [{"Key": "redacted", "Code": "AccessDenied"}]
    }
    storage = MapAtlasStorage(client=client, bucket="private")

    with pytest.raises(RuntimeError, match="1 object"):
        await storage.delete_prefix("map-atlas/n/")


@pytest.mark.asyncio
async def test_exact_cleanup_removes_all_versions_and_delete_markers() -> None:
    key = f"map-atlas/{uuid.uuid4()}/pages/{uuid.uuid4()}/image.png"
    client = MagicMock()
    client.list_object_versions.side_effect = [
        {
            "Versions": [
                {"Key": key, "VersionId": "v2"},
                {"Key": f"{key}.other", "VersionId": "ignored"},
            ],
            "DeleteMarkers": [{"Key": key, "VersionId": "marker-1"}],
        },
        {"Versions": [], "DeleteMarkers": []},
    ]
    client.list_objects_v2.return_value = {"Contents": []}
    client.delete_objects.return_value = {}
    storage = MapAtlasStorage(client=client, bucket="private")

    await storage.delete_object(key)

    deleted = client.delete_objects.call_args.kwargs["Delete"]["Objects"]
    assert deleted == [
        {"Key": key, "VersionId": "v2"},
        {"Key": key, "VersionId": "marker-1"},
    ]
    client.delete_object.assert_not_called()


@pytest.mark.asyncio
async def test_prefix_cleanup_removes_versions_markers_and_confirms_empty() -> None:
    prefix = f"map-atlas/{uuid.uuid4()}/"
    first_key = f"{prefix}pages/{uuid.uuid4()}/image.png"
    second_key = f"{prefix}pages/{uuid.uuid4()}/mask.png"
    client = MagicMock()
    client.list_object_versions.side_effect = [
        {
            "Versions": [{"Key": first_key, "VersionId": "v1"}],
            "DeleteMarkers": [{"Key": second_key, "VersionId": "marker-1"}],
        },
        {"Versions": [], "DeleteMarkers": []},
    ]
    client.list_objects_v2.return_value = {"Contents": []}
    client.delete_objects.return_value = {}
    storage = MapAtlasStorage(client=client, bucket="private")

    assert await storage.delete_prefix(prefix) == 2
    assert client.delete_objects.call_args.kwargs["Delete"]["Objects"] == [
        {"Key": first_key, "VersionId": "v1"},
        {"Key": second_key, "VersionId": "marker-1"},
    ]


@pytest.mark.asyncio
async def test_cleanup_falls_back_to_current_objects_without_version_api() -> None:
    prefix = f"map-atlas/{uuid.uuid4()}/"
    key = f"{prefix}pages/{uuid.uuid4()}/image.png"
    unsupported = ClientError(
        {
            "Error": {"Code": "NotImplemented"},
            "ResponseMetadata": {"HTTPStatusCode": 501},
        },
        "ListObjectVersions",
    )
    client = MagicMock()
    client.list_object_versions.side_effect = unsupported
    client.list_objects_v2.side_effect = [
        {"Contents": [{"Key": key}]},
        {"Contents": []},
        {"Contents": []},
    ]
    client.delete_objects.return_value = {}
    storage = MapAtlasStorage(client=client, bucket="private")

    assert await storage.delete_prefix(prefix) == 1
    assert client.delete_objects.call_args.kwargs["Delete"]["Objects"] == [{"Key": key}]


@pytest.mark.asyncio
async def test_cleanup_handler_dispatches_exact_object_and_project_prefix(
    db_session,
) -> None:
    novel_id, page_id = uuid.uuid4(), uuid.uuid4()
    key = page_object_key(str(novel_id), str(page_id), mask=True)
    prefix = project_object_prefix(str(novel_id))
    storage = MagicMock(spec=MapAtlasStorage)
    storage.delete_object = AsyncMock()
    storage.delete_prefix = AsyncMock(return_value=3)

    with patch(
        "modules.world.map_atlas_tasks.MapAtlasStorage",
        autospec=True,
        return_value=storage,
    ):
        object_result = await handle_map_atlas_storage_cleanup(
            db_session,
            SimpleNamespace(meta={"cleanup_kind": "object", "object_key": key}),
        )
        prefix_result = await handle_map_atlas_storage_cleanup(
            db_session,
            SimpleNamespace(
                meta={"cleanup_kind": "project_prefix", "object_prefix": prefix}
            ),
        )

    storage.delete_object.assert_awaited_once_with(key)
    storage.delete_prefix.assert_awaited_once_with(prefix)
    assert object_result["deleted_objects"] == 1
    assert prefix_result["deleted_objects"] == 3


@pytest.mark.asyncio
async def test_cleanup_handler_keeps_an_object_referenced_by_a_page(
    db_session,
    test_project_id,
) -> None:
    novel_id = uuid.UUID(test_project_id)
    run = MapAtlasRun(novel_id=novel_id, run_kind="edit", status="generating")
    db_session.add(run)
    await db_session.flush()
    node = MapAtlasNode(
        novel_id=novel_id,
        created_by_run_id=run.id,
        semantic_key="world",
        title="世界",
        level="world",
    )
    db_session.add(node)
    await db_session.flush()
    page_id = uuid.uuid4()
    key = page_object_key(test_project_id, str(page_id), mask=True)
    db_session.add(
        MapAtlasPage(
            id=page_id,
            novel_id=novel_id,
            run_id=run.id,
            node_id=node.id,
            title="世界",
            visual_brief="世界地图",
            prompt="no text",
            mask_object_key=key,
        )
    )
    await db_session.commit()
    storage = MagicMock(spec=MapAtlasStorage)
    storage.delete_object = AsyncMock()

    with patch(
        "modules.world.map_atlas_tasks.MapAtlasStorage",
        autospec=True,
        return_value=storage,
    ):
        result = await handle_map_atlas_storage_cleanup(
            db_session,
            SimpleNamespace(meta={"cleanup_kind": "object", "object_key": key}),
        )

    assert result["deleted_objects"] == 0
    storage.delete_object.assert_not_awaited()


@pytest.mark.asyncio
async def test_cleanup_handler_rejects_atlas_root_before_s3_call() -> None:
    storage = MagicMock(spec=MapAtlasStorage)
    with (
        patch(
            "modules.world.map_atlas_tasks.MapAtlasStorage",
            autospec=True,
            return_value=storage,
        ),
        pytest.raises(ValueError),
    ):
        await handle_map_atlas_storage_cleanup(
            None,
            SimpleNamespace(
                meta={
                    "cleanup_kind": "project_prefix",
                    "object_prefix": "map-atlas/",
                }
            ),
        )
    storage.delete_prefix.assert_not_called()


def test_map_upload_strips_png_text_metadata_chunks() -> None:
    # 构造带 tEXt/eXIf/tIME 辅助 chunk 的 PNG
    base = bytearray(PNG)
    insert_at = len(base) - 12  # IEND 之前

    def chunk(chunk_type: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + chunk_type
            + data
            + struct.pack(">I", zlib.crc32(chunk_type + data) & 0xFFFFFFFF)
        )

    base[insert_at:insert_at] = (
        chunk(b"tEXt", b"Author\x00someone")
        + chunk(b"eXIf", b"Exif\x00\x00GPS")
        + chunk(b"tIME", b"\x07\xe8\x01\x01\x00\x00\x00")
    )
    crafted = bytes(base)

    normalized, metadata = normalize_map_upload(crafted)

    assert normalized != crafted
    assert b"someone" not in normalized
    assert b"Exif" not in normalized
    assert b"\x07\xe8" not in normalized
    assert metadata.byte_size == len(normalized)
    validate_png(normalized)


def test_map_upload_keeps_clean_png_byte_identical() -> None:
    normalized, metadata = normalize_map_upload(PNG)
    assert normalized == PNG
    assert metadata.sha256 == hashlib.sha256(PNG).hexdigest()

from __future__ import annotations

from dataclasses import replace
from io import BytesIO

import pytest
from PIL import Image

from core.config import get_settings
from modules.world.local_image_store import LocalImageClient
from modules.world.map_atlas_storage import MapAtlasStorage


@pytest.fixture
def local_storage(monkeypatch, tmp_path):
    settings = replace(
        get_settings(),
        app_env="local",
        auth_mode="local",
        world_images_directory=str(tmp_path / "images"),
        map_atlas_s3_bucket="map-atlas",
    )
    monkeypatch.setattr("modules.world.map_atlas_storage.get_settings", lambda: settings)
    return MapAtlasStorage()


@pytest.mark.asyncio
async def test_roundtrip_stream_missing_and_project_cleanup(local_storage):
    image = BytesIO()
    Image.new("RGB", (2, 2), "blue").save(image, "PNG")
    payload = image.getvalue()
    await local_storage.put_png("project-a/one.png", payload)
    await local_storage.put_png("project-b/one.png", payload)
    assert await local_storage.get_png("project-a/one.png") == payload
    chunks = [
        chunk
        async for chunk in local_storage.iter_png_chunks(
            "project-a/one.png", chunk_size=7
        )
    ]
    assert b"".join(chunks) == payload
    assert len(chunks) > 1
    assert await local_storage.get_png_if_exists("project-a/missing.png") is None
    assert await local_storage.delete_prefix("project-a/") == 1
    assert await local_storage.get_png_if_exists("project-a/one.png") is None
    assert await local_storage.get_png("project-b/one.png") == payload


@pytest.mark.parametrize(
    "key", ["../out", "/out", "one/../../out", "a\\out", "C:/out", "a//out", "a/./out"]
)
def test_paths_cannot_escape(tmp_path, key):
    store = LocalImageClient(tmp_path / "images")
    with pytest.raises(ValueError):
        store.get_object(Bucket="map-atlas", Key=key)


def test_symlink_is_not_followed(tmp_path):
    store = LocalImageClient(tmp_path / "images")
    bucket = store._bucket("map-atlas")
    (bucket / "linked").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError):
        store.delete_object(Bucket="map-atlas", Key="linked/sensitive")


@pytest.mark.asyncio
async def test_cleanup_covers_more_than_one_page(local_storage):
    client = local_storage._client
    for index in range(1002):
        client.put_object(
            Bucket="map-atlas",
            Key=f"project-a/{index}.png",
            Body=b"test",
            ContentType="image/png",
            Metadata={},
        )
    assert await local_storage.delete_prefix("project-a/") == 1002


def test_local_storage_is_not_enabled_for_public_server(monkeypatch, tmp_path):
    settings = replace(
        get_settings(),
        app_env="production",
        auth_mode="public",
        world_images_directory=str(tmp_path / "images"),
        map_atlas_s3_bucket="map-atlas",
    )
    monkeypatch.setattr("modules.world.map_atlas_storage.get_settings", lambda: settings)
    with pytest.raises(ValueError, match="local single-user"):
        MapAtlasStorage()

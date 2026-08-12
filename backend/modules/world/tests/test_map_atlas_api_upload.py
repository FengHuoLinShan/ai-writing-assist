from io import BytesIO

import pytest
from fastapi import HTTPException, UploadFile

from modules.world import map_atlas_api


async def test_mask_upload_rejects_payload_at_size_limit(monkeypatch) -> None:
    monkeypatch.setattr(map_atlas_api, "MAX_IMAGE_BYTES", 4)
    upload = UploadFile(file=BytesIO(b"1234"), filename="mask.png")

    with pytest.raises(HTTPException) as exc_info:
        await map_atlas_api._read_bounded_png(upload)

    assert exc_info.value.status_code == 413

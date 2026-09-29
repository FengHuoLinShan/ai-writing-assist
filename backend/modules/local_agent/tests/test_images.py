"""Pure review-layer tests: no DB, no network."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from core.errors import ValidationError
from modules.local_agent.images import (
    ReviewedImage,
    fit_cover,
    limit_edge,
    review_generated_image,
)


def _png_bytes(size: tuple[int, int] = (64, 48), color=(200, 30, 30)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


def _jpeg_bytes_with_exif(size: tuple[int, int] = (80, 40)) -> bytes:
    buffer = io.BytesIO()
    image = Image.new("RGB", size, (10, 200, 10))
    exif = image.getexif()
    exif[0x0112] = 3  # Orientation: rotate 180
    image.save(buffer, format="JPEG", exif=exif)
    return buffer.getvalue()


def _gif_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32), (1, 2, 3)).save(buffer, format="GIF")
    return buffer.getvalue()


def _webp_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32), (1, 2, 3)).save(buffer, format="WEBP")
    return buffer.getvalue()


def _animated_png_bytes() -> bytes:
    buffer = io.BytesIO()
    frames = [Image.new("RGBA", (24, 24), (i * 10, 0, 0, 255)) for i in range(3)]
    frames[0].save(
        buffer,
        format="PNG",
        save_all=True,
        append_images=frames[1:],
        duration=100,
        loop=0,
    )
    return buffer.getvalue()


class TestReviewGeneratedImage:
    def test_valid_png_is_reencoded_without_metadata(self):
        payload = _png_bytes((64, 48))
        result = review_generated_image(payload)
        assert isinstance(result, ReviewedImage)
        assert (result.width, result.height) == (64, 48)
        with Image.open(io.BytesIO(result.data)) as reencoded:
            assert reencoded.format == "PNG"
            assert not reencoded.info.get("exif")
        assert len(result.sha256) == 64

    def test_valid_jpeg_with_exif_normalizes_orientation_and_strips_metadata(self):
        payload = _jpeg_bytes_with_exif((80, 40))
        result = review_generated_image(payload)
        with Image.open(io.BytesIO(result.data)) as reencoded:
            assert reencoded.format == "PNG"
            assert reencoded.getexif() == {}
        assert result.width > 0 and result.height > 0

    def test_rejects_empty_payload(self):
        with pytest.raises(ValidationError):
            review_generated_image(b"")

    def test_rejects_gif(self):
        with pytest.raises(ValidationError):
            review_generated_image(_gif_bytes())

    def test_rejects_webp(self):
        with pytest.raises(ValidationError):
            review_generated_image(_webp_bytes())

    def test_rejects_garbage_bytes(self):
        with pytest.raises(ValidationError):
            review_generated_image(b"not an image" * 10)

    def test_rejects_truncated_png(self):
        payload = _png_bytes((64, 64))
        with pytest.raises(ValidationError):
            review_generated_image(payload[: len(payload) // 2])

    def test_rejects_animated_png(self):
        with pytest.raises(ValidationError):
            review_generated_image(_animated_png_bytes())

    def test_rejects_oversize_bytes(self):
        payload = _png_bytes((16, 16))
        with pytest.raises(ValidationError):
            review_generated_image(payload, max_bytes=len(payload) - 1)

    def test_rejects_edge_larger_than_max(self):
        payload = _png_bytes((4100, 16))
        with pytest.raises(ValidationError):
            review_generated_image(payload, max_edge=4096)

    def test_rejects_tiny_image(self):
        payload = _png_bytes((8, 8))
        with pytest.raises(ValidationError):
            review_generated_image(payload)

    def test_preserves_alpha_channel(self):
        buffer = io.BytesIO()
        Image.new("RGBA", (32, 32), (10, 20, 30, 128)).save(buffer, format="PNG")
        result = review_generated_image(buffer.getvalue())
        with Image.open(io.BytesIO(result.data)) as reencoded:
            assert "A" in reencoded.getbands()


class TestFitCover:
    def test_produces_exact_target_size(self):
        source = review_generated_image(_png_bytes((200, 100)))
        fitted = fit_cover(source, 50, 50)
        assert (fitted.width, fitted.height) == (50, 50)
        with Image.open(io.BytesIO(fitted.data)) as reencoded:
            assert reencoded.size == (50, 50)
            assert reencoded.format == "PNG"


class TestLimitEdge:
    def test_downscales_when_over_limit(self):
        source = review_generated_image(_png_bytes((200, 100)))
        limited = limit_edge(source, 100)
        assert max(limited.width, limited.height) <= 100
        assert limited.width / limited.height == pytest.approx(200 / 100, rel=0.05)

    def test_no_op_when_within_limit(self):
        source = review_generated_image(_png_bytes((60, 40)))
        limited = limit_edge(source, 100)
        assert limited is source

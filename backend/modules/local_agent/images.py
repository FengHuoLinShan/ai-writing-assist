"""Server-side review and re-encode of images the local CLI generated.

Nothing here trusts the companion. Every image is re-decoded, stripped of
metadata, and re-saved as a clean PNG before the product ever stores or
serves it. This module is pure (no DB, no network) so it stays trivially
testable and reusable from both the companion-facing endpoint and any
downstream fit/limit helper (map atlas tiling, world object thumbnails).
"""

from __future__ import annotations

import hashlib
import io
import warnings
from dataclasses import dataclass

from PIL import Image, ImageOps

from core.errors import ValidationError

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"
_MIN_EDGE = 16


@dataclass(frozen=True)
class ReviewedImage:
    """A PNG re-encoded by the server; never the CLI's raw bytes."""

    data: bytes
    width: int
    height: int
    sha256: str


def _reject(message: str) -> ValidationError:
    return ValidationError(message)


def review_generated_image(
    data: bytes,
    *,
    max_bytes: int = 20 * 1024 * 1024,
    max_edge: int = 4096,
) -> ReviewedImage:
    """Validate, decompression-bomb-guard, strip metadata, and re-encode as PNG."""
    if not data:
        raise _reject("图片内容为空")
    if len(data) > max_bytes:
        raise _reject("图片文件过大")
    if not (data.startswith(_PNG_MAGIC) or data.startswith(_JPEG_MAGIC)):
        raise _reject("仅支持 PNG 或 JPEG 图片")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as probe:
                if probe.format not in {"PNG", "JPEG"}:
                    raise _reject("仅支持 PNG 或 JPEG 图片")
                if getattr(probe, "n_frames", 1) != 1:
                    raise _reject("不支持动图或多帧图片")
                width, height = probe.size
                if (
                    width < _MIN_EDGE
                    or height < _MIN_EDGE
                    or width > max_edge
                    or height > max_edge
                ):
                    raise _reject(f"图片尺寸需在 {_MIN_EDGE}~{max_edge} 像素之间")
                probe.verify()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise _reject(f"图片尺寸需在 {_MIN_EDGE}~{max_edge} 像素之间") from exc
    except (OSError, SyntaxError, ValueError) as exc:
        raise _reject("图片内容已损坏，无法读取") from exc

    try:
        with Image.open(io.BytesIO(data)) as source:
            transposed = ImageOps.exif_transpose(source)
            has_alpha = "A" in transposed.getbands() or "transparency" in source.info
            image = transposed.convert("RGBA" if has_alpha else "RGB")
    except (OSError, SyntaxError, ValueError) as exc:
        raise _reject("图片内容已损坏，无法读取") from exc

    return _encode(image)


def _encode(image: Image.Image) -> ReviewedImage:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    payload = buffer.getvalue()
    width, height = image.size
    return ReviewedImage(
        data=payload,
        width=width,
        height=height,
        sha256=hashlib.sha256(payload).hexdigest(),
    )


def fit_cover(image: ReviewedImage, width: int, height: int) -> ReviewedImage:
    """Resize to cover the target box, then center-crop to exactly width x height."""
    if width < 1 or height < 1:
        raise ValueError("target size must be positive")
    with Image.open(io.BytesIO(image.data)) as source:
        source.load()
        fitted = ImageOps.fit(source, (width, height), method=Image.Resampling.LANCZOS)
        return _encode(fitted)


def limit_edge(image: ReviewedImage, max_edge: int) -> ReviewedImage:
    """Downscale proportionally when either edge exceeds max_edge; else no-op."""
    if max_edge < 1:
        raise ValueError("max_edge must be positive")
    if image.width <= max_edge and image.height <= max_edge:
        return image
    with Image.open(io.BytesIO(image.data)) as source:
        source.load()
        resized = source.copy()
        resized.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
        return _encode(resized)

"""Pad/fit a product image to a 9:16 canvas for image-to-video providers.

Kling's image2video has no aspect-ratio field — the output video inherits the
input image's ratio. So to get a vertical 1080x1920 TikTok clip we transform the
product image (any ratio) onto a 9:16 canvas here and send that.

Strategy: scale the image to *contain* it on the canvas (no cropping of the
product), with a blurred, zoomed copy of the same image as the background fill
(the familiar "blurred bars" look — far better than black bars). If the source
is already ~9:16 the foreground fills the frame and the blur is invisible.

Returns RAW base64 (no ``data:`` prefix, per Kling's spec) or None if Pillow is
unavailable or the image can't be fetched — callers fall back to the URL.
"""
from __future__ import annotations

import base64
import io
import logging

import requests

logger = logging.getLogger("service.image_prep")


def _resize_cover(img, w: int, h: int):
    """Scale to fill w x h then center-crop (for the background)."""
    from PIL import Image

    src_ratio = img.width / img.height
    if src_ratio > w / h:
        new_h = h
        new_w = max(w, round(h * src_ratio))
    else:
        new_w = w
        new_h = max(h, round(w / src_ratio))
    img = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - w) // 2
    top = (new_h - h) // 2
    return img.crop((left, top, left + w, top + h))


def _resize_contain(img, w: int, h: int):
    """Scale to fit entirely within w x h (no cropping; for the foreground)."""
    from PIL import Image

    scale = min(w / img.width, h / img.height)
    return img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.LANCZOS)


def image_bytes_to_vertical_b64(data: bytes, width: int = 1080, height: int = 1920) -> str | None:
    """Transform raw image bytes into a width x height JPEG, returned as base64."""
    try:
        from PIL import Image, ImageFilter
    except ImportError:
        logger.warning("Pillow not installed; cannot pad image to 9:16 (pip install Pillow)")
        return None
    try:
        src = Image.open(io.BytesIO(data)).convert("RGB")
        background = _resize_cover(src, width, height).filter(ImageFilter.GaussianBlur(40))
        foreground = _resize_contain(src, width, height)
        canvas = background.copy()
        canvas.paste(foreground, ((width - foreground.width) // 2, (height - foreground.height) // 2))
        buf = io.BytesIO()
        canvas.save(buf, format="JPEG", quality=90)
        return base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:  # malformed image, etc.
        logger.warning("Failed to transform image to 9:16", exc_info=True)
        return None


def url_to_vertical_b64(url: str, *, width: int = 1080, height: int = 1920, timeout: int = 60) -> str | None:
    """Download an image and return a width x height JPEG base64 (or None)."""
    try:
        resp = requests.get(url, timeout=timeout)
    except requests.RequestException:
        logger.warning("Could not download image for 9:16 prep: %s", url)
        return None
    if resp.status_code >= 400 or not resp.content:
        logger.warning("Image fetch failed (%s) for %s", resp.status_code, url)
        return None
    return image_bytes_to_vertical_b64(resp.content, width, height)

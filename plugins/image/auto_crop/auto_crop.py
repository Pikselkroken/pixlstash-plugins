"""Auto Crop plugin for PixlStash.

Trims the uniform border off an image: letterbox bars, white margins, the
padding a batch export left behind. The scan walks in from every edge while the
pixels stay within a tolerance of the corner colour, then crops to what is
left.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

import numpy as np
from PIL import Image
from pixlstash.image_plugins.base import ImagePlugin

DEFAULT_TOLERANCE = 12
DEFAULT_PADDING = 0
MAX_TOLERANCE = 255
MAX_PADDING = 512


class AutoCrop(ImagePlugin):
    """Crops the uniform border off every image in the batch."""

    name = "auto_crop"
    display_name = "Auto Crop"
    description = "Trims letterboxing, margins and padding off the edges."
    # The header a tool reads to describe this plugin. Keep the values literal:
    # they are meant to be readable without importing the plugin.
    author = "Gaute Lindkvist <lindkvis@gmail.com>"
    license = "MIT"
    models = []  # no model to declare; a real one lists {"name", "license"}

    supports_images = True
    supports_videos = False

    def parameter_schema(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "tolerance",
                "label": "Tolerance",
                "type": "number",
                "default": DEFAULT_TOLERANCE,
                "description": (
                    "How far a pixel may differ from the corner colour, per "
                    "channel, and still count as border. 0 is an exact match."
                ),
            },
            {
                "name": "padding",
                "label": "Border to keep",
                "type": "number",
                "default": DEFAULT_PADDING,
                "description": (
                    "Pixels of border left in place on every side. The edge "
                    "with the least to spare sets the amount for all four, so "
                    "the border stays uniform."
                ),
            },
        ]

    def run(
        self,
        images: list[Image.Image],
        parameters: dict[str, Any] | None = None,
        progress_callback=None,
        error_callback=None,
        captions: list[str] | None = None,
    ) -> list[Image.Image]:
        """Return one cropped image per input, in the same order."""
        params = parameters or {}
        # Parameters arrive off a JSON payload and are not type-checked, so
        # read them defensively. (The base class has private helpers for this;
        # do not reach for them: they are not part of the plugin API and are
        # not in every PixlStash version.)
        try:
            tolerance = int(float(params.get("tolerance", DEFAULT_TOLERANCE)))
        except (TypeError, ValueError):
            tolerance = DEFAULT_TOLERANCE
        tolerance = max(0, min(MAX_TOLERANCE, tolerance))
        try:
            padding = int(float(params.get("padding", DEFAULT_PADDING)))
        except (TypeError, ValueError):
            padding = DEFAULT_PADDING
        padding = max(0, min(MAX_PADDING, padding))

        out: list[Image.Image] = []
        total = len(images)
        for index, image in enumerate(images):
            try:
                out.append(_crop(image, tolerance, padding))
                self.report_progress(
                    progress_callback,
                    current=index + 1,
                    total=total,
                    message=f"Cropped image {index + 1}/{total}",
                )
            except Exception as exc:
                self.report_error(
                    error_callback,
                    index=index,
                    message="Failed to crop the image",
                    details={"error": str(exc)},
                )
                # The untransformed original, not `image.copy()`: whatever made
                # the transform fail can make the copy fail too, and raising
                # inside the handler abandons the batch after all. The list must
                # stay the same length as the input.
                out.append(image)
        return out


def _crop(image: Image.Image, tolerance: int, padding: int) -> Image.Image:
    """Return *image* with its uniform border trimmed to *padding* pixels."""
    # Compare in RGB, or RGBA where there is an alpha channel, so a palette,
    # greyscale or CMYK source cannot confuse the match. Alpha earns its place
    # in the comparison: transparent padding differs from opaque content in
    # that channel alone. The crop is applied to the original, which keeps its
    # mode.
    probe = image.convert("RGBA" if "A" in image.getbands() else "RGB")
    width, height = probe.size
    corners = [
        probe.getpixel(point)
        for point in ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1))
    ]
    # The colour most corners agree on. Counter keeps insertion order for a
    # tie, so four different corners fall back to the top-left one, and an
    # image whose corners disagree simply fails to match and is left alone.
    background = Counter(corners).most_common(1)[0][0]

    pixels = np.asarray(probe, dtype=np.int16)
    difference = np.abs(pixels - np.array(background, dtype=np.int16))
    is_border = np.all(difference <= tolerance, axis=2)
    rows = np.flatnonzero(~is_border.all(axis=1))
    columns = np.flatnonzero(~is_border.all(axis=0))
    if rows.size == 0 or columns.size == 0:
        return image.copy()  # every pixel is border, so there is nothing to keep

    top, bottom = int(rows[0]), int(rows[-1]) + 1
    left, right = int(columns[0]), int(columns[-1]) + 1
    # Border is kept, never invented: the edge with the least to spare sets the
    # amount for all four, which is what keeps the result evenly framed.
    keep = min(padding, top, left, height - bottom, width - right)
    box = (left - keep, top - keep, right + keep, bottom + keep)
    if box == (0, 0, width, height):
        return image.copy()
    return image.crop(box)


if __name__ == "__main__":
    # Enough of a check to catch the crop arithmetic going wrong.
    canvas = Image.new("RGB", (20, 10), (255, 255, 255))
    canvas.paste(Image.new("RGB", (6, 4), (10, 20, 30)), (5, 3))
    assert _crop(canvas, 0, 0).size == (6, 4)
    assert _crop(canvas, 0, 2).size == (10, 8)
    # Three pixels of white above the subject, so every side keeps three.
    assert _crop(canvas, 0, 9).size == (12, 10)
    # An off-white pixel in the corner holds the top and left edges where
    # they are until the tolerance covers it.
    noisy = canvas.copy()
    noisy.putpixel((0, 0), (250, 250, 250))
    assert _crop(noisy, 0, 0).size == (11, 7)
    assert _crop(noisy, 8, 0).size == (6, 4)
    # A letterboxed frame, and a picture that is border all the way through.
    bars = Image.new("RGB", (16, 12), (0, 0, 0))
    bars.paste(Image.new("RGB", (16, 6), (90, 120, 200)), (0, 3))
    assert _crop(bars, 0, 0).size == (16, 6)
    assert _crop(Image.new("L", (5, 5), 128), 0, 0).size == (5, 5)
    print("ok")

"""Hello-world image plugin for PixlStash: stamps "Hello World" on the image.

Draws text in magenta in a corner of each picture. It loads no model and needs
nothing but Pillow, so it is the quickest way to prove your user image plugin
directory is in the right place: if the text appears, PixlStash found the file.

It is also the smallest complete image plugin: a parameter schema, the batch
loop, progress reporting, and a per-image failure that costs one picture instead
of the batch. Replace ``_stamp`` with your own transform and you have a plugin.

Copy *this file*, not its folder, into your user image plugin directory. No
restart needed: image plugins are re-scanned on every menu listing and run. See
the repository README.
"""

from __future__ import annotations

from typing import Any

from PIL import Image, ImageDraw, ImageFont
from pixlstash.image_plugins.base import ImagePlugin

DEFAULT_TEXT = "Hello World"
MAGENTA = (255, 0, 255)
MARGIN = 8

POSITIONS = ["top-left", "top-right", "bottom-left", "bottom-right", "centre"]


class HelloWorldStamp(ImagePlugin):
    """Draws a line of magenta text onto every image in the batch."""

    name = "hello_world_stamp"
    display_name = "Hello World Stamp"
    description = 'Stamps "Hello World" onto the image in magenta. Example plugin.'

    supports_images = True
    supports_videos = False

    def parameter_schema(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "text",
                "label": "Text",
                "type": "string",
                "default": DEFAULT_TEXT,
                "description": "What to draw. Empty leaves the image alone.",
            },
            {
                "name": "size",
                "label": "Text size",
                "type": "number",
                "default": 24,
                "description": "Height of the text in pixels.",
            },
            {
                "name": "position",
                "label": "Position",
                "type": "select",
                "default": "bottom-right",
                # Image plugins declare select options as a plain list of
                # values, unlike captioning plugins, which use dicts.
                "options": POSITIONS,
                "description": "Where on the image the text goes.",
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
        """Return one stamped image per input, in the same order."""
        params = parameters or {}
        # Parameters arrive off a JSON payload and are not type-checked, so
        # read them defensively. (The base class has private helpers for this;
        # do not reach for them: they are not part of the plugin API and are
        # not in every PixlStash version.)
        text = params.get("text", DEFAULT_TEXT)
        text = text if isinstance(text, str) else DEFAULT_TEXT
        try:
            size = int(float(params.get("size", 24)))
        except (TypeError, ValueError):
            size = 24
        size = max(1, min(512, size))
        position = params.get("position")
        if position not in POSITIONS:
            position = "bottom-right"

        out: list[Image.Image] = []
        total = len(images)
        for index, image in enumerate(images):
            try:
                out.append(self._stamp(image, text, size, position))
                self.report_progress(
                    progress_callback,
                    current=index + 1,
                    total=total,
                    message=f"Stamped image {index + 1}/{total}",
                )
            except Exception as exc:
                self.report_error(
                    error_callback,
                    index=index,
                    message="Failed to stamp the image",
                    details={"error": str(exc)},
                )
                # The untransformed original, not `image.copy()`: whatever made
                # the transform fail can make the copy fail too, and raising
                # inside the handler abandons the batch after all. The list must
                # stay the same length as the input.
                out.append(image)
        return out

    @staticmethod
    def _stamp(image: Image.Image, text: str, size: int, position: str) -> Image.Image:
        """Draw *text* onto a copy of *image* and return it."""
        if not text.strip():
            return image.copy()

        # Draw in RGB so a palette, greyscale or 1-bit source cannot swallow
        # the colour, then restore the alpha channel if there was one.
        alpha = image.getchannel("A") if "A" in image.getbands() else None
        result = image.convert("RGB")

        draw = ImageDraw.Draw(result)
        font = _load_font(size)
        left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
        x, y = _place(
            position,
            image_size=result.size,
            text_size=(right - left, bottom - top),
        )
        # textbbox is measured from the anchor, and for some fonts starts at a
        # non-zero offset; subtracting it puts the ink where we asked.
        draw.text((x - left, y - top), text, font=font, fill=MAGENTA)

        if alpha is not None:
            result.putalpha(alpha)
        return result


def _load_font(size: int) -> ImageFont.ImageFont:
    """Return the built-in font at *size*, whatever the Pillow version.

    ``load_default`` only takes a size from Pillow 10.1; older versions return a
    fixed-size bitmap font, and the stamp is simply small there. Falling back
    beats requiring a font file the host may not have.
    """
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _place(
    position: str, image_size: tuple[int, int], text_size: tuple[int, int]
) -> tuple[int, int]:
    """Return the top-left pixel for *text_size* placed at *position*."""
    image_width, image_height = image_size
    text_width, text_height = text_size
    right = max(MARGIN, image_width - text_width - MARGIN)
    bottom = max(MARGIN, image_height - text_height - MARGIN)
    return {
        "top-left": (MARGIN, MARGIN),
        "top-right": (right, MARGIN),
        "bottom-left": (MARGIN, bottom),
        "bottom-right": (right, bottom),
        "centre": (
            max(0, (image_width - text_width) // 2),
            max(0, (image_height - text_height) // 2),
        ),
    }[position]

# Hello World Stamp

Draws "Hello World" onto every picture, in magenta.

It loads no model and needs nothing but Pillow, so it is the quickest way to
prove your user image plugin directory is in the right place: if the text
appears, PixlStash found the file.

It is also the smallest complete image plugin: a parameter schema, the batch
loop, progress reporting, and a per-image failure that costs one picture instead
of the batch. Replace `_stamp` with your own transform and you have a plugin.

## Install

Copy **`hello_world_stamp.py`**, the file and not this folder, into your user
image plugin directory; the image plugin loader only scans for `.py` files. It
appears in the Filters menu the next time that menu is listed, since image
plugins are re-scanned per request, so no restart is needed.

## Dependencies

None beyond PixlStash itself (Pillow ships with it).

## Parameters

| Parameter | Type | Default | Meaning |
|-----------|------|---------|---------|
| `text` | string | `Hello World` | What to draw. Empty or blank leaves the image alone. |
| `size` | number | `24` | Height of the text in pixels, clamped to 1–512. |
| `position` | select | `bottom-right` | `top-left`, `top-right`, `bottom-left`, `bottom-right` or `centre`. |

The colour is a constant, `MAGENTA` at the top of the file.

Images with an alpha channel keep it, and a greyscale, palette or CMYK source is
converted to RGB so the colour survives. Video is not supported
(`supports_videos = False`).

Text is drawn with Pillow's built-in font. On Pillow older than 10.1 that font
cannot be scaled, so `size` has no effect there and the stamp is small.

## License

MIT, see the [LICENSE](../../../LICENSE) at the repository root.

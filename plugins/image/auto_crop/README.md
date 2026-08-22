# Auto Crop

Trims the uniform border off a picture: letterbox bars, the white margin round
a scan, the padding a batch export left behind.

It reads the colour the picture's four corners agree on, walks in from every
edge while the pixels stay within a tolerance of that colour, and crops to what
is left. Nothing is configured per image, so a whole folder of differently
padded exports comes back trimmed in one pass.

Border is kept, never invented. Ask for a border and the edge with the least to
spare sets the amount for all four sides, so the result stays evenly framed and
never gains a strip of colour that was not in the original.

## Install

Copy **`auto_crop.py`**, the file and not this folder, into your user image
plugin directory; the image plugin loader only scans for `.py` files. It appears
in the Filters menu the next time that menu is listed, since image plugins are
re-scanned per request, so no restart is needed.

## Dependencies

None beyond PixlStash itself. Pillow and numpy ship with it, and this plugin
imports nothing else, so there is no `requirements.txt` beside it.

## Parameters

| Parameter | Type | Default | Meaning |
|-----------|------|---------|---------|
| `tolerance` | number | `12` | How far a pixel may differ from the corner colour, per channel, and still count as border. `0` demands an exact match; clamped to 0–255. |
| `padding` | number | `0` | Pixels of border left in place on every side, the same on all four. Clamped to 0–512, and further to the border the picture actually has. |

A photograph's white surround is rarely one exact value, so the default
tolerance of 12 is there to absorb JPEG noise and paper texture. Raise it when a
margin survives the crop, lower it when the crop eats into the picture.

Corner disagreement is the safe case, not an error: when no two corners share a
colour the top-left one is used, and a picture whose corners genuinely differ
simply fails to match and comes back untouched. So does a picture that is
border all the way through, which would otherwise crop to nothing.

Transparency counts. An RGBA source is matched on all four channels, so
transparent padding is trimmed even where its colour matches the picture. The
crop is applied to the original, so palette, greyscale and CMYK images keep
their mode.

Video is not supported (`supports_videos = False`).

Running `auto_crop.py` directly executes a handful of assertions over the crop
arithmetic and prints `ok`.

## Models

None. This plugin loads no model and contacts no remote service.

## License

MIT, see the [LICENSE](LICENSE) in this folder.

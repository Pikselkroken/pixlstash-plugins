# Hello World Tagger

Applies a fixed list of tags — `hello world` by default — to every image.

It runs no model, so it is the quickest way to prove your user plugin folder is
in the right place: if the tags appear after a tagging run, PixlStash found your
plugin.

## Install

Copy this whole folder into your user tagger plugin directory (take the exact
path from **Settings → Auto-tagging**) and restart PixlStash Server. Then enable
**Hello World Tagger** in **Settings → Auto-tagging → Tag plugins**.

## Dependencies

None beyond PixlStash itself.

## Parameters

| Parameter | Type | Default | Meaning |
|-----------|------|---------|---------|
| `tags` | string | `hello world` | Comma-separated tags applied to every image. |
| `confidence` | number | `1.0` | Confidence reported for each tag, clamped to 0–1. |

## License

MIT — see the [LICENSE](../../../LICENSE) at the repository root.

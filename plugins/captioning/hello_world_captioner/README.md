# Hello World Captioner

Writes a short description from a template instead of from a model, so it runs
anywhere and uses no GPU.

It is the smallest complete captioner: a parameter schema, a batch loop, and the
`None` return that reports a single failed image without losing the rest of the
batch. Replace `generate_descriptions` with real inference and you have a plugin.

## Install

Copy this whole folder into your user captioning plugin directory (take the
exact path from **Settings → Auto-tagging**) and restart PixlStash Server. Then
pick **Hello World Captioner** as the description plugin in
**Settings → Auto-tagging**.

## Dependencies

None beyond PixlStash itself.

## Parameters

| Parameter | Type | Default | Meaning |
|-----------|------|---------|---------|
| `template` | textarea | `Hello world. A picture named {filename}.` | Caption text. `{filename}`, `{stem}` and `{extension}` are replaced per image. |
| `max_length` | integer | `200` | Captions longer than this are truncated. 0 or less means no truncation. |

A template PixlStash cannot fill (an unknown `{placeholder}`, an attribute
access, a bad format spec) fails that image, leaving its caption unset, rather
than the whole batch.

## License

MIT, see the [LICENSE](LICENSE) in this folder.

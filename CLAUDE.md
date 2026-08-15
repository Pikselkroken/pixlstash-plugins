# Writing a PixlStash plugin as an agent

Instructions for an AI agent asked to produce a plugin for this repository.
A human reading this is not the target audience; they want the
[README](README.md) and the two guides in [`docs/`](docs/).

> `AGENTS.md` and `CLAUDE.md` are byte-identical, and `pytest` fails if they
> drift. Edit one, copy it over the other.

## The task you were probably given

> Write me a PixlStash captioning plugin based on the repo at
> `https://github.com/Pikselkroken/pixlstash-captioning-plugins` for the XXX
> captioning system at `https://...`

Deliver **one new folder** under `plugins/captioning/` or `plugins/image/`,
holding the plugin, a `README.md`, and a `requirements.txt` if it needs
third-party packages. Change nothing else. Do not edit other plugins, the
guides, the tests or CI.

## Before writing code

1. **Pick the kind.** Image in, text out (tags or a description) is a
   **captioning** plugin. Picture in, picture out is an **image** plugin.
2. **Read the contract** for that kind:
   [`docs/writing-captioning-plugins.md`](docs/writing-captioning-plugins.md)
   or [`docs/writing-image-plugins.md`](docs/writing-image-plugins.md). They
   describe what PixlStash does today, gaps included, and they beat anything
   you remember about plugin systems in general.
3. **Read the matching example** (`hello_world_captioner`,
   `hello_world_tagger`, `hello_world_stamp`) and follow its shape.
4. **Read the upstream documentation of the system you are wrapping.** Do not
   guess method names, argument names, model identifiers or defaults. If you
   cannot verify a call, say so in the plugin README instead of inventing it,
   and leave the uncertain line commented with what you could not confirm.

## Rules a reviewer will check

- **Import only the base class**, `pixlstash.tagger_plugins.base` or
  `pixlstash.image_plugins.base`. Everything else in `pixlstash` is GPL-3.0 and
  puts the plugin under the GPL. Underscore-prefixed helpers on the base
  classes are not API and are missing from some versions.
- **A failure costs one item, never the batch.** Captioning plugins map that
  path to `None`; image plugins call `report_error` and append the untouched
  original. Catch `Exception` around inference, since model code raises
  anything.
- **Parameters are not type-checked.** Read them with
  `parameters.get(key, default)` inside a `try`, never
  `parameters.get(key) or default`, which turns a deliberate `0` into the
  default.
- **Load the model in `init()`**, never at module level, and return early when
  it is already loaded. For image plugins this is critical: the registry
  re-executes the module on every Filters listing and every run.
- **Pin any model revision you download.** An unpinned HuggingFace ref is a
  silent supply-chain change.
- **Pick a free name.** Built-in captioning names are `wd14`,
  `pixlstash_tagger`, `florence2` and `joycaption`; built-in image names are
  `blur_sharpen`, `brightness_contrast`, `colour_filter`, `pixelate`, `rotate`
  and `scaling`. A captioning collision drops your plugin; an image collision
  silently replaces the built-in, which is worse.
- **Shape.** A captioning plugin is a folder with `__init__.py`. An image
  plugin folder holds exactly one `.py` file named after the folder, defining
  exactly one concrete `ImagePlugin` subclass. Folder names are `snake_case`.
- **No network beyond the model or API you were asked to wrap.** No telemetry,
  no reads or writes outside the paths you are given.

Also assume, because the host does not do these yet: `unload()` is never
called on a third-party plugin, `estimated_vram_mb()` is ignored, and
`stop_event` is always `None` on the description path. Implement them
correctly anyway, and guard the `stop_event` access.

## Captioning plugin skeleton

```python
from __future__ import annotations

from typing import Any

from pixlstash.tagger_plugins.base import TaggerPlugin


class MyCaptioner(TaggerPlugin):
    name = "my_captioner"
    display_name = "My Captioner"
    description = "One sentence, shown in the settings table."

    supports_descriptions = True
    supports_tags = False
    requires_download = False

    def __init__(self) -> None:
        self._model = None
        self._device = "cpu"

    def parameter_schema(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "max_tokens",
                "label": "Max tokens",
                "type": "integer",
                "default": 128,
                "min": 16,
                "max": 1024,
                "step": 16,
                "description": "Upper bound on caption length.",
            },
        ]

    def setup(self, device: str) -> None:
        # The only way to learn the device. Called just before init().
        self._device = device

    def needs_download(self, parameters: dict[str, Any] | None = None) -> bool:
        return False

    def init(self, parameters: dict[str, Any]) -> None:
        if self._model is not None:
            return
        # Load here, never at import, and pin the revision.
        self._model = load_the_model(revision="PIN_ME", device=self._device)

    def unload(self) -> None:
        self._model = None

    def is_loaded(self) -> bool:
        return self._model is not None

    def generate_descriptions(self, image_paths, parameters, stop_event=None):
        try:
            max_tokens = int(parameters.get("max_tokens", 128))
        except (TypeError, ValueError):
            max_tokens = 128

        results: dict[str, str | None] = {}
        for path in image_paths:
            if stop_event is not None and stop_event.is_set():
                break
            try:
                results[path] = self._model.caption(path, max_tokens=max_tokens)
            except Exception:
                results[path] = None  # this image only, never the batch
        return results
```

A tagger is the same shape with `supports_tags = True` and `tag_images`,
returning `{path: [TagResult(tag=..., confidence=...)]}`. An image plugin is
`parameter_schema` plus `run(images, parameters, progress_callback,
error_callback, captions)`, returning a list of the same length in the same
order; see §2 and §4 of the image guide.

## The plugin README

Copy the layout from an example plugin. It needs: what the plugin does, an
**Install** section, **Dependencies** (matching `requirements.txt` exactly),
a **Parameters** table with one row per schema entry, and **License**. If you
wrap a model with its own license or usage terms, say so, and if the model
sends images to a remote service, say that first and plainly.

## Before you call it done

```bash
pip install -r requirements-dev.txt
pip install --no-deps pixlstash
ruff format . && ruff check . && pytest
```

The contract tests are the bar. **A plugin whose dependencies are not
installed is skipped entirely**, so a green run proves nothing about a plugin
that needs a model: say what you actually ran it against, which model version,
and on what hardware.

Note that captioning plugins load only on PixlStash `develop`, targeted at
1.10.0. Repeat that callout in the plugin README. Image plugins work on 1.9.0.

## House style

No em dashes anywhere, in prose or code comments. Wrap Markdown and comments
at about 80 characters. Match the spelling of the file you are editing. Say
what the code does and why a caveat exists, without restating it in three
places.

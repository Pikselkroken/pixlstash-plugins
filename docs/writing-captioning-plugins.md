# Writing a captioning / tagging plugin

> Adapted from `docs/writing-tagger-plugins.md` in the
> [PixlStash repository](https://github.com/Pikselkroken/pixlstash), which is
> the upstream copy and wins any disagreement with this one.

PixlStash loads user-supplied captioning and tagging engines from a folder on
your machine, so anything that turns an image path into a caption can be plugged
in without touching PixlStash: a VLM, a GGUF model through `llama-cpp-python`, a
remote API, a rule of your own.

Start from
[`plugins/captioning/hello_world_captioner/`](../plugins/captioning/hello_world_captioner/),
or `pixlstash/tagger_plugins/plugin_template.py` in a PixlStash checkout; this
is the contract behind both.

**You need a PixlStash build that loads user captioning plugins.** Discovery
landed in [PR #937](https://github.com/Pikselkroken/pixlstash/pull/937), is on
`develop`, and is targeted at 1.10.0. No release has it yet, v1.9.0 included.

## 1. Where plugins live

| OS | Folder |
|----|--------|
| Linux | `~/.local/share/pixlstash/tagger-plugins/user/` |
| macOS | `~/Library/Application Support/pixlstash/tagger-plugins/user/` |
| Windows | `%LOCALAPPDATA%\pixlstash\pixlstash\tagger-plugins\user\` |

(The doubled `pixlstash` on Windows is `platformdirs` inserting the app author,
which defaults to the app name. It is not a typo.)

**The folder does not exist until you create it, and a folder in the wrong place
is skipped in silence.** Take the exact path from **Settings → Auto-tagging**,
where it is displayed; it is also logged at start-up. That path, and the list of
plugins that failed to load, is shown only to a local owner, never to a share
link.

Two shapes are accepted: a single `.py` file, or a folder containing
`__init__.py` for a plugin that ships helper modules and imports them relatively
(`from . import helper`). Plugins here use the second shape, so each carries its
own README and `requirements.txt`. Entries starting with `.` or `_` are skipped,
as is any other file type.

**Discovery runs once, at start-up. Restart the server after adding or editing a
plugin.** There is deliberately no reload button: re-instantiating a plugin
whose model is resident would orphan that model in VRAM.

Plugin code runs unsandboxed, in the server process, with your permissions. Only
install plugins you trust.

## 2. The minimum plugin

Subclass `TaggerPlugin` and set the capability flags. The class must be
*defined* in the module you drop in, since a subclass merely imported into it is
ignored. A module may define several plugins; all are registered.

```python
from pixlstash.tagger_plugins.base import TaggerPlugin


class MyCaptioner(TaggerPlugin):
    name = "my_captioner"  # unique snake_case id
    display_name = "My Captioner"  # label in the settings table
    description = "What it does."
    author = "Your Name <your.name@example.com>"  # name and one contact
    license = "MIT"  # the plugin's own code
    models = [  # every model or service it uses, and their terms
        {"name": "acme/tiny-vlm", "license": "Apache-2.0"},
    ]
    supports_descriptions = True  # appears in the Description plugin table
    supports_tags = False  # ...and/or the Tag plugin table
    requires_download = False  # True offers a download button
    default_enabled = False  # tag plugins only: on by default?
```

That is not loadable on its own: `parameter_schema`, `needs_download`, `init`,
`unload` and `is_loaded` are abstract, and a class missing any of them cannot be
instantiated, so the registry skips it.

`name` must be non-empty and must not collide. **Built-in plugins load first and
win a collision**, so a user plugin named `wd14`, `pixlstash_tagger`,
`florence2` or `joycaption` is dropped with a visible load error rather than
silently replacing the built-in.

A plugin that raises on import, on construction, or from `parameter_schema()`
does not stop the others: the failure is logged, listed under
**Settings → Auto-tagging** with its message (to a local owner only, since
exception text can name any host path), and the server boots normally. The
schema is exercised once at load precisely so a later failure cannot take the
settings screen down with it.

### The header

`name`, `display_name`, `description`, `author`, `license` and `models` are the
plugin header: what a tool needs to tell a user what this plugin is before
running it.

| Field | Contents |
|-------|----------|
| `name` | the unique `snake_case` id above |
| `display_name` | the human-readable name, and what a tool shows instead of the id |
| `description` | one sentence, shown in the settings table |
| `author` | `Your Name <your.name@example.com>`, one name and one contact; the contact is an email address or an `http(s)` URL, so a plugin with nobody to email gives its project page |
| `license` | the license of the plugin's own code, an SPDX identifier where there is one |
| `models` | one entry per model or remote service the plugin uses, each `{"name": ..., "license": ...}`, empty when it uses none |

`models` is the field that matters most to whoever installs the plugin: your MIT
license says nothing about the weights the plugin downloads or the API it posts
images to. Name them and name their terms. An entry may carry more, and a
`"revision"` naming the ref you pinned (§6) is worth adding, since the license
of a model is only the license of the weights you actually fetch.

Keep the values literal: string, number and list literals in the class body,
inherited from a base class you ship beside them, but nothing computed and
nothing assigned in `__init__`. The point of the header is that it can be read
with `ast.literal_eval`, without importing the plugin, and importing a plugin
runs its module body on the reader's machine. What the source says and what the
object carries must be the same thing.

**PixlStash reads half the header.** `plugin_schema()` forwards `name`,
`display_name` and `description` to the frontend, and nothing forwards
`author`, `license` or `models`, so today those three are read by tooling
around the plugin;
[issue #961](https://github.com/Pikselkroken/pixlstash/issues/961) tracks the
host side. The contract tests in this repository require all six regardless,
and a plugin that ships them now needs no edit when the host catches up.

## 3. `parameter_schema()`, the settings UI

Return a list of parameter definitions; PixlStash builds the settings dialog
straight from it, so there is nothing else to write for the UI.

Required keys: `name` (snake_case), `label`, `type`, `default`.
Optional: `description` (tooltip), `min` / `max` / `step` (numeric types),
`options` (required for `select`, as `[{"value": ..., "label": ...}]`).

| `type` | Control |
|--------|---------|
| `number` | Numeric input / slider (float) |
| `integer` | Numeric input (int) |
| `boolean` | Checkbox |
| `select` | Dropdown, needs `options` |
| `string` | Single-line text field |
| `textarea` | Multi-line text field |
| `csv-int` | Comma-separated integers |

```python
def parameter_schema(self):
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
```

Saved values live in the user's `tagger_settings` JSON under your plugin's name.
They are validated against the parameter *names* you declare but never
type-checked, so read them defensively, preferring
`parameters.get(key, default)` to `parameters.get(key) or default`, which turns
a deliberate `0` or `""` into the default. A parameter you add later is filled
in from its `default`, so schema changes need no migration, but **renaming a
parameter loses its saved value**.

## 4. Lifecycle

`init()` is called before every batch and must be idempotent. `is_loaded()` must
tell the truth between calls, because the settings table polls it.

| Method | Required | Called by PixlStash today |
|--------|----------|---------------------------|
| `setup(device)` | optional | **Yes**, via `hasattr`, just before `init()`. The only way to learn the device (`"cuda"`, `"cpu"`, …), so implement it if you use a GPU. |
| `init(parameters)` | yes | **Yes**, before every batch. Return early when already loaded. |
| `is_loaded()` | yes | **Yes**: the settings table, and `plugin_schema()`. |
| `unload()` | yes (abstract) | **No.** See below. |
| `estimated_vram_mb(image_count, parameters)` | no | **No.** See below. |
| `effective_batch_size(parameters)` | no | **No** (for description plugins). |

Three honest gaps in the API, to know about rather than design around:

- **Nothing calls `unload()` on a third-party plugin.** The idle-unload path
  (`ModelLifecycleManager`) knows the four built-in *services* by name and does
  not walk the plugin registry. Implement `unload()` anyway, but your model
  stays resident for the life of the process and "Keep models in memory = off"
  will not free it. Manage it inside `generate_descriptions` if that matters.
- **Nothing calls `estimated_vram_mb()` on a third-party plugin.**
  `DescriptionWorkflow` charges the VRAM budget for Florence-2 only. Overriding
  it is forward-looking but will not stop PixlStash scheduling another model
  alongside yours, so keep your footprint modest.
- **`stop_event` is always `None` for `generate_descriptions`.** The tag path
  passes one; `DescriptionWorkflow` does not. Honour it if present, since the
  signature is the contract, but do not rely on it to cancel a long batch.

## 5. Inference

```python
def generate_descriptions(self, image_paths, parameters, stop_event=None):
    return {path: "a caption" for path in image_paths}

def tag_images(self, image_paths, parameters, preloaded=None, stop_event=None):
    return {path: [TagResult(tag="cat", confidence=0.91)] for path in image_paths}
```

- `image_paths` are absolute, and may include video files, so check the
  extension if you cannot handle them.
- `parameters` arrives already merged over your `default_params()`.
- **Map a path to `None` to report a per-image failure.** The rest of the batch
  is still stored; raising loses all of it. Catch broadly around your inference
  call, since third-party model code raises whatever it likes and a template or
  a tokenizer can fail in ways `except ValueError` will not see.
- `TagResult.confidence` may be `None` for models without probabilities.

## 6. Downloads

A plugin that fetches weights implements the quartet. `JoyCaptionPlugin`
(`pixlstash/tagger_plugins/joycaption.py`) is the reference implementation.

| Method | Contract |
|--------|----------|
| `needs_download(parameters)` | `True` when the files are absent. Drives the download button. |
| `download(parameters, progress_callback)` | Fetch the files. Runs on a background thread. |
| `list_downloaded_artifacts()` | List of dicts, each with **`"name"`** and `"size_bytes"`; `"label"` is shown if present. |
| `delete_artifact(name)` | Remove one artifact by that `"name"`. Raise `ValueError` for an unknown one. |

**Use `"name"` as the artifact key**, because
`DELETE /taggers/{name}/artifacts/{id}` matches on it. The built-in JoyCaption
plugin emits `"id"` instead, so copy the route's expectation rather than that
plugin's dict.

Pin your revisions. An unpinned HuggingFace ref is a silent supply-chain change.

## 7. Dependencies

Whatever your plugin imports must already be installed in the environment
PixlStash runs in. PixlStash reads no manifest and installs nothing for you; a
missing import shows up as that plugin's load error. Say what you need in your
plugin's README, and list it in a `requirements.txt` beside its `__init__.py`.

Import only `pixlstash.tagger_plugins.base`. Anything else in `pixlstash` is GPL
(see §8), and private helpers (leading underscore) are not part of the plugin
API and differ between versions.

## 8. Licensing

`pixlstash/tagger_plugins/base.py` and `plugin_template.py` are MIT-licensed, as
an explicit exception to the GPL-3.0 backend, so your plugin can carry whatever
license you like. Importing anything else from `pixlstash` puts you back under
the GPL. Plugins contributed to this repository are MIT, like the repository.

Whichever you pick, say so in the `license` field of the header (§2), and list
the terms of every model you wrap in `models`. That is the user's decision to
make, and they can only make it if the plugin tells them.

## 9. Known limitations

- **The model shelf will not label your model.** Weights in the HuggingFace
  cache appear on the shelf via the cache scan, but the repo-to-capability map
  is hand-maintained (`pixlstash/services/model_features.py`), so a third-party
  model shows up without a capability tag.
- **`florence2` is special-cased.** `DescriptionWorkflow` routes that name down
  a native fast path, and it is also the fallback when the configured
  description plugin fails to initialise. You cannot override it by taking the
  name.
- **No reload.** Restart after every edit.

# Writing a captioning / tagging plugin

> Adapted from `docs/writing-tagger-plugins.md` in the
> [PixlStash repository](https://github.com/Pikselkroken/pixlstash), which is
> the upstream copy and wins any disagreement with this one. It is reproduced
> here so this repository stands on its own, and because the version of the
> guide that matches a given PixlStash build is the one in that build.

PixlStash loads user-supplied captioning and tagging engines from a folder on your
machine. Anything that can turn an image path into a caption — Qwen-VL, Moondream2, a
Florence-2 promptgen fine-tune, a GGUF model through `llama-cpp-python`, a remote API —
can be plugged in without touching PixlStash itself.

Start from [`plugins/captioning/hello_world_captioner/`](../plugins/captioning/hello_world_captioner/)
in this repository, or `pixlstash/tagger_plugins/plugin_template.py` in a PixlStash
checkout; this document is the contract behind both.

**You need a PixlStash build that loads user captioning plugins.** Discovery landed in
[PR #937](https://github.com/Pikselkroken/pixlstash/pull/937), is on the `develop`
branch, and is targeted at 1.10.0. No release has it yet, v1.9.0 included.

## 1. Where plugins live

| OS | Folder |
|----|--------|
| Linux | `~/.local/share/pixlstash/tagger-plugins/user/` |
| macOS | `~/Library/Application Support/pixlstash/tagger-plugins/user/` |
| Windows | `%LOCALAPPDATA%\pixlstash\pixlstash\tagger-plugins\user\` |

(The doubled `pixlstash` on Windows is `platformdirs` inserting the app author, which
defaults to the app name. It is not a typo.)

**The folder does not exist until you create it, and a folder in the wrong place is
skipped in silence.** So take the exact path for your install from **Settings →
Auto-tagging**, where it is displayed, rather than from the table above; it is also
logged at start-up. The path — and the list of plugins that failed to load — is shown
only to the owner, on the machine running the server or on its LAN (or from anywhere if
the server sets `allow_remote_host_ops`, the same flag that governs every other
host-filesystem operation). A share link never sees either. Installing a plugin means
writing a file into that folder, so there is nothing to do remotely anyway.

Two shapes are accepted:

- a single `.py` file — `my_captioner.py`
- a folder containing `__init__.py` — for a plugin that ships helper modules, which it
  imports relatively (`from . import helper`)

Plugins in this repository use the second shape, so that each one can carry its own
README and `requirements.txt` in the same folder.

Entries whose name starts with `.` or `_` are skipped, as is any other file type.

**Discovery runs once, at start-up. Restart the server after adding or editing a
plugin.** There is deliberately no reload button: re-instantiating a plugin whose model
is resident would orphan that model in VRAM.

Plugin code runs unsandboxed, in the server process, with your permissions. Only install
plugins you trust — the same caveat as the image plugins.

## 2. The minimum plugin

Subclass `TaggerPlugin` and set the capability flags. The class must be *defined* in the
module you drop in (a subclass merely imported into it is ignored, so importing another
plugin does not register it twice). A module may define several plugins; all of them are
registered.

```python
from pixlstash.tagger_plugins.base import TaggerPlugin


class MyCaptioner(TaggerPlugin):
    name = "my_captioner"  # unique snake_case id
    display_name = "My Captioner"  # label in the settings table
    description = "What it does."
    supports_descriptions = True  # appears in the Description plugin table
    supports_tags = False  # ...and/or the Tag plugin table
    requires_download = False  # True offers a download button
    default_enabled = False  # tag plugins only: on by default?
```

That declaration is not yet loadable on its own: `parameter_schema`,
`needs_download`, `init`, `unload` and `is_loaded` are abstract, and a class
missing any of them cannot be instantiated — the registry skips it. §3 onwards
fills them in; the example plugins in this repository are complete.

`name` must be non-empty and must not collide with an existing plugin. **Built-in plugins
are loaded first and win a collision** — a user plugin named `wd14`, `pixlstash_tagger`,
`florence2` or `joycaption` is skipped and shown as a load error rather than silently
replacing (or being silently bypassed by) the built-in.

A plugin that raises on import, that raises on construction, or whose
`parameter_schema()` raises does not stop the others: the failure is logged, listed under
**Settings → Auto-tagging** with its message (to a local owner — the message is exception
text and can name any path on the host), and the server boots normally. (The schema
is exercised once at load precisely so a later failure cannot take the settings screen —
or the boot — down with it.)

## 3. `parameter_schema()` — this JSON *is* the settings UI

Return a list of parameter definitions. PixlStash builds the plugin's settings dialog
straight from it, so there is nothing else to write for the UI. Saved settings are
validated against the parameter *names* you declare; values are not type-checked, so read
them defensively (`int(parameters.get("max_tokens") or 128)`).

Required keys: `name` (snake_case), `label`, `type`, `default`.
Optional: `description` (tooltip), `min` / `max` / `step` (numeric types),
`options` (required for `select`, as `[{"value": ..., "label": ...}]`).

| `type` | Control |
|--------|---------|
| `number` | Numeric input / slider (float) |
| `integer` | Numeric input (int) |
| `boolean` | Checkbox |
| `select` | Dropdown — needs `options` |
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

Saved values live in the user's `tagger_settings` JSON under your plugin's name. A
parameter you add later is filled in from its `default` for existing users, so schema
changes need no migration — but **renaming a parameter loses its saved value**.

One caveat on the defensive-read idiom above: `parameters.get(key) or default` turns a
deliberate `0` or `""` into the default. Prefer `parameters.get(key, default)` and
handle the wrong type explicitly when zero is a meaningful value.

## 4. Lifecycle

`init()` is called before every batch and must be idempotent. `is_loaded()` must tell the
truth between calls — the settings table polls it.

| Method | Required | Called by PixlStash today |
|--------|----------|---------------------------|
| `setup(device)` | optional | **Yes** — via `hasattr`, just before `init()`. The only way to learn the device (`"cuda"`, `"cpu"`, …), so implement it if you use a GPU. |
| `init(parameters)` | yes | **Yes**, before every batch. Return early when already loaded. |
| `is_loaded()` | yes | **Yes** — the settings table, and `plugin_schema()`. |
| `unload()` | yes (abstract) | **No.** See below. |
| `estimated_vram_mb(image_count, parameters)` | no | **No.** See below. |
| `effective_batch_size(parameters)` | no | **No** (for description plugins). |

**Know what the host does not yet do for you.** These are honest gaps in the plugin API
as it stands, not things to design around:

- **Nothing calls `unload()` on a third-party plugin.** The idle-unload path
  (`ModelLifecycleManager`) knows the four built-in *services* by name and does not walk
  the plugin registry. `unload()` is still abstract, so implement it — but a model your
  plugin loads stays resident for the life of the process, and "Keep models in memory =
  off" will not free it. If that matters for your model, manage it yourself inside
  `generate_descriptions`.
- **Nothing calls `estimated_vram_mb()` on a third-party plugin.** `DescriptionWorkflow`
  charges the VRAM budget for Florence-2 only. Overriding it is harmless and forward-
  looking, but it will not currently stop PixlStash scheduling another model alongside
  yours, so keep your own footprint modest.
- **`stop_event` is always `None` for `generate_descriptions`.** `DescriptionWorkflow`
  does not pass one (the tag path does). Honour it if present — the signature is the
  contract — but do not rely on it to cancel a long batch today.

## 5. Inference

```python
def generate_descriptions(self, image_paths, parameters, stop_event=None):
    return {path: "a caption" for path in image_paths}

def tag_images(self, image_paths, parameters, preloaded=None, stop_event=None):
    return {path: [TagResult(tag="cat", confidence=0.91)] for path in image_paths}
```

- `image_paths` are absolute paths, and may include video files — check the extension if
  you cannot handle them.
- `parameters` arrives already merged over your `default_params()`.
- **Map a path to `None` to report a per-image failure.** That is the documented signal;
  the rest of the batch is still stored. Raising instead loses the whole batch. Catch
  broadly around your inference call — third-party model code raises whatever it likes,
  and a template or a tokenizer can fail in ways `except ValueError` will not see.
- `stop_event` is a `threading.Event` set when the user cancels — but see §4: it is
  currently always `None` on the description path. Guard the access.
- `TagResult.confidence` may be `None` for models that do not produce probabilities.

## 6. Downloads

A plugin that fetches weights implements the quartet. `JoyCaptionPlugin`
(`pixlstash/tagger_plugins/joycaption.py`) is the reference implementation.

| Method | Contract |
|--------|----------|
| `needs_download(parameters)` | `True` when the files are absent. Drives the download button. |
| `download(parameters, progress_callback)` | Fetch the files. Runs on a background thread. |
| `list_downloaded_artifacts()` | List of dicts, each with **`"name"`** and `"size_bytes"`; `"label"` is shown if present. |
| `delete_artifact(name)` | Remove one artifact by that `"name"`. Raise `ValueError` for an unknown one. |

**Use `"name"` as the artifact key.** `DELETE /taggers/{name}/artifacts/{id}` matches on
`"name"`. The built-in JoyCaption plugin emits `"id"` instead, so copy the route's
expectation rather than that plugin's dict.

Pin your revisions. An unpinned HuggingFace ref is a silent supply-chain change.

## 7. Dependencies

Whatever your plugin imports must already be installed in the environment PixlStash runs
in — `pip install llama-cpp-python`, and so on. PixlStash does not read a manifest and
will not install anything for you; a missing import simply shows up as that plugin's load
error. Say what you need in your plugin's own README, and list it in a `requirements.txt`
beside its `__init__.py`.

Import only `pixlstash.tagger_plugins.base`. Anything else in `pixlstash` is GPL (see
§8), and private helpers — anything with a leading underscore — are not part of the
plugin API and differ between versions.

## 8. Licensing

`pixlstash/tagger_plugins/base.py` and `plugin_template.py` are MIT-licensed, as an
explicit exception to the GPL-3.0 backend, so your plugin can carry whatever license you
like. Importing anything else from `pixlstash` puts you back under the GPL. Plugins
contributed to this repository are MIT, like the repository.

## 9. Known limitations

- **The model shelf will not label your model.** Weights in the HuggingFace cache appear
  on the shelf via the cache scan, but the repo → capability map is hand-maintained
  (`pixlstash/services/model_features.py`), so a third-party model shows up without a
  capability tag.
- **`florence2` is special-cased.** `DescriptionWorkflow` routes that name down a native
  fast path, and it is also the fallback when the configured description plugin fails to
  initialise. You cannot override it by taking the name.
- **No reload.** Restart after every edit.

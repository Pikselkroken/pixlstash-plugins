# Writing an image plugin

Image plugins are the Filters menu: a batch of pictures in, a batch of pictures
out. Anything you can express as a PIL transform can be one, from a colour grade
or a crop to an upscaler or a diffusion pass.

There is no upstream prose guide for these, so this contract is read off
`pixlstash/image_plugins/base.py` and `registry.py`. Start from
[`plugins/image/hello_world_stamp/`](../plugins/image/hello_world_stamp/), or
`pixlstash/image_plugins/built-in/plugin_template.py` in a PixlStash checkout.

**Image plugins are not captioning plugins.** The two look alike and differ in
ways that will bite you if you carry assumptions across; §6 lists them.

## 1. Where plugins live

| OS | Folder |
|----|--------|
| Linux | `~/.local/share/pixlstash/image-plugins/user/` |
| macOS | `~/Library/Application Support/pixlstash/image-plugins/user/` |
| Windows | `%LOCALAPPDATA%\pixlstash\pixlstash\image-plugins\user\` |

PixlStash logs the path at start-up. The folder does not exist until you create
it, and a folder in the wrong place is skipped in silence. (The doubled
`pixlstash` on Windows is `platformdirs` inserting the app author. PixlStash's
own `plugin_template.py` shows a single `pixlstash` and is wrong; the registry
calls `user_data_dir("pixlstash")`, which doubles it.)

**Only single `.py` files are loaded.** The registry scans for `*.py`, so unlike
a captioning plugin, a folder is not a plugin and a helper module beside it will
not be found. One file, everything in it. That is why a plugin folder here holds
a `.py` file named after the folder: you copy the file, not the folder.
`plugin_template.py` is excluded from discovery by name, so rename your copy.

**Discovery is not a start-up event, and this is the single most important thing
on this page.** `plugin_service.list_plugins()` and `run_plugin_on_pictures()`
both call `manager.reload()`, so the registry re-scans the folder and
re-executes every plugin file **on every Filters listing and every run**. So no
restart is needed after an edit, and **anything at module level is paid on every
request**: load models and weights lazily inside `run()`, cached on the instance
or in a module global, remembering that the instance is replaced on every
reload.

`pixlstash-cli plugins install <file|zip|folder>` copies a plugin into the
right directory for you, `pixlstash-cli plugins list` prints both directories
and what is in them, marking with `*` a plugin that replaces a built-in, and
`pixlstash-cli plugins remove <name>` deletes one, which brings the built-in
back. **`pixlstash-cli plugins test` checks captioning plugins only**, so there
is no equivalent one-command check here; the loop is the Filters menu, which
needs no restart.

Plugin code runs unsandboxed, in the server process, with your permissions, and
is re-executed constantly. Only install plugins you trust.

## 2. The minimum plugin

`parameter_schema` and `run` are both abstract, so a class that declares only the
attributes cannot be instantiated and is recorded as a load error. The smallest
thing that actually loads is:

```python
from pixlstash.image_plugins.base import ImagePlugin


class MyFilter(ImagePlugin):
    name = "my_filter"  # unique snake_case id
    display_name = "My Filter"  # label in the Filters menu
    description = "What it does."
    author = "Your Name <your.name@example.com>"  # name and one contact
    license = "MIT"  # the plugin's own code
    models = []  # every model or service it uses, and their terms
    supports_images = True  # handles stills via run()
    supports_videos = False  # True also requires run_video()

    def parameter_schema(self):
        return []

    def run(self, images, parameters=None, progress_callback=None,
            error_callback=None, captions=None):
        return [image.copy() for image in images]
```

**Define exactly one `ImagePlugin` subclass per file, and make it concrete.**
`_find_plugin_class` returns the first `ImagePlugin` subclass in the module
namespace, checking neither where it was defined nor whether it is abstract. A
subclass you merely **imported** can therefore be shipped instead of yours (and
since a user plugin wins a name collision, importing a built-in silently
replaces it), and an **abstract** base defined above your class can be picked up
and then fail to instantiate. The captioning registry has neither trap.

`name` must be non-empty and unique. **The user directory is scanned before the
built-in one, and the first plugin to claim a name keeps it**, so a user plugin
named `blur_sharpen`, `brightness_contrast`, `colour_filter`, `pixelate`,
`rotate` or `scaling` silently *replaces* the built-in. This is the opposite of
the captioning registry, where the built-in wins and the user plugin is dropped
with a visible error. Pick a name nobody else has.

A plugin that fails to import or construct is recorded as a load error and
skipped; the rest still load.

### The header

`name`, `display_name`, `description`, `author`, `license` and `models` are the
plugin header: what a tool needs to tell a user what this plugin is before
running it. It is the same on both kinds of plugin.

| Field | Contents |
|-------|----------|
| `name` | the unique `snake_case` id above |
| `display_name` | the human-readable name, and what a tool shows instead of the id |
| `description` | one sentence, shown in the Filters menu |
| `author` | `Your Name <your.name@example.com>`, one name and one contact; the contact is an email address or an `http(s)` URL, so a plugin with nobody to email gives its project page |
| `license` | the license of the plugin's own code, an SPDX identifier where there is one |
| `models` | one entry per model or remote service the plugin uses, each `{"name": ..., "license": ...}`, empty when it uses none |

`models` is the field that matters most to whoever installs the plugin: your MIT
license says nothing about the weights an upscaler or a diffusion pass
downloads. Name them and name their terms. An entry may carry more, and a
`"revision"` naming the ref you pinned is worth adding, since the license of a
model is only the license of the weights you actually fetch.

Keep the values literal: string, number and list literals in the class body,
inherited from a base class you ship beside them, but nothing computed and
nothing assigned in `__init__`. The point of the header is that it can be read
with `ast.literal_eval`, without importing the plugin, and importing a plugin
runs its module body on the reader's machine, here on every Filters listing.
What the source says and what the object carries must be the same thing.

**`ImagePlugin` on `develop` declares all six**, `author` and `license`
defaulting to `""` and `models` to `[]`, and `plugin_schema()` forwards them
([issue #961](https://github.com/Pikselkroken/pixlstash/issues/961)). It also
raises `TypeError` when `models` is not a list of dicts, rather than letting
the shape reach a caller. On 1.9.0 the base class has none of this, and the
three attributes sit there unread, which costs nothing: write them anyway and
they start being shown the day the host is upgraded. The contract tests in
this repository require all six and reject an empty one.

## 3. `parameter_schema()`, the settings UI

Required keys: `name` (snake_case), `label`, `type`, `default`.
Optional: `description`, and `options` for a `select`.

| `type` | Control |
|--------|---------|
| `number` | Numeric input |
| `string` | Text field |
| `boolean` | Checkbox |
| `select` | Dropdown, needs `options` |

```python
def parameter_schema(self):
    return [
        {
            "name": "strength",
            "label": "Strength",
            "type": "number",
            "default": 1.0,
            "description": "Effect strength.",
        },
        {
            "name": "mode",
            "label": "Mode",
            "type": "select",
            "default": "soft",
            "options": ["soft", "hard"],  # a plain list, not dicts
            "description": "Which mode to use.",
        },
    ]
```

**`options` is a plain list of values here**, where a captioning plugin uses
`[{"value": ..., "label": ...}]`.

Values arrive off a JSON payload and are not type-checked. Read them
defensively, inside a `try`, and note that `params.get(key) or default` turns a
deliberate `0` into the default; use `params.get(key, default)`.

## 4. `run()`, the batch

```python
def run(self, images, parameters=None, progress_callback=None,
        error_callback=None, captions=None):
    ...
```

- **Return a list of the same length, in the same order.** Callers pair outputs
  with inputs positionally, so dropping an entry misaligns everything after it.
  Changing the output size is fine.
- `parameters` may be `None`. Missing keys fall back to your defaults.
- `captions[i]` is picture *i*'s stored description, or `""`; the whole argument
  is `None` if the caller passed none.
- Call `self.report_progress(progress_callback, current=…, total=…, message=…)`
  after each image to drive the progress bar.
- **On a per-image failure, call `self.report_error(error_callback, index=…,
  message=…, details=…)` and append the untransformed original** rather than
  raising, which abandons every image still to come. Append the original object,
  not `image.copy()`: whatever broke the transform can break the copy too, and
  an exception raised inside the handler loses the batch anyway.

## 5. Video

Set `supports_videos = True` and override `run_video(source_path, parameters,
progress_callback, error_callback)`, returning encoded bytes or a
`(bytes, extension)` tuple.

`self.transform_video(source_path, transform, …)` on the base class runs the
decode, transform and encode loop and picks a container/codec your OpenCV build
can open. It hands your callable one RGB PIL frame at a time and sizes the
writer from the first transformed frame, so a size-changing transform needs no
arithmetic, but it **must return the same size for every frame**.

**`transform_video` is only on `develop`, not on any release.** On 1.9.0 a
plugin calling it dies with `AttributeError`, so write the decode/encode loop
yourself or guard with `hasattr(self, "transform_video")`. It is a public
method, so the "only underscore-prefixed helpers move between versions" rule of
thumb in §7 does not save you.

`get_bbox_transform()` exists on the base class and is currently unused;
overriding it has no effect today.

## 6. Differences from captioning plugins

| | Image plugins | Captioning plugins |
|---|---|---|
| Folder | `image-plugins/user/` | `tagger-plugins/user/` |
| Shape | one `.py` file only | a `.py` file **or** a package folder |
| Discovery | re-scanned on every list **and** every run | once, at start-up |
| Editing a plugin | picked up on the next menu open | restart the server |
| Module-level work | paid on every request | paid once |
| Classes per module | exactly one, first found wins, imported or abstract | all concrete classes the module defines |
| Name collision | **user plugin wins**, replacing the built-in | built-in wins, user plugin dropped |
| `select` options | `["a", "b"]` | `[{"value": "a", "label": "A"}]` |
| Parameter types | `number`, `string`, `boolean`, `select` | those plus `integer`, `textarea`, `csv-int` |
| Per-item failure | `report_error(...)` + append the original | map the path to `None` |
| Base class imports | Pillow, numpy, OpenCV | standard library only |

## 7. Dependencies

Whatever you import must already be installed in the environment PixlStash runs
in. PixlStash reads no manifest and installs nothing for you; a missing import
shows up as a load error. Say what you need in your plugin's README and list it
in a `requirements.txt` beside it. Pillow, numpy and OpenCV are always
available, since the base class imports them. This repository's CI does read
that file, installing it on its own to check the plugin's structure, so a
`requirements.txt` that will not install fails the build.

Import only `pixlstash.image_plugins.base`, and only its public surface. The
underscore-prefixed helpers on `ImagePlugin` (`_coerce_number` and friends) are
not part of the plugin API and are not in every PixlStash version. Check what
your target version actually has rather than what the source you are reading
has: `transform_video` and `_coerce_number` are both on `develop` and neither is
in 1.9.0. `hasattr` is cheap.

## 8. Licensing

`pixlstash/image_plugins/base.py` and `plugin_template.py` are MIT-licensed as an
explicit exception to the GPL-3.0 backend, so your plugin can carry whatever
license you like. Importing anything else from `pixlstash` puts you back under
the GPL. A plugin contributed to this repository may carry any OSI-approved
license; the repository itself is MIT.

Whichever you pick, say so in the `license` field of the header (§2), and list
the terms of every model you wrap in `models`. That is the user's decision to
make, and they can only make it if the plugin tells them.

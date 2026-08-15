# Writing an image plugin

Image plugins are the Filters menu: they take a batch of pictures and return a
batch of pictures. Anything you can express as a PIL transform — a colour grade,
a crop, a watermark, an upscaler, a diffusion pass — can be one.

There is no upstream prose guide for these the way there is for captioning
plugins; the contract below is read off `pixlstash/image_plugins/base.py` and
`registry.py`, with `pixlstash/image_plugins/built-in/plugin_template.py` as the
starter. Start from
[`plugins/image/hello_world_stamp/`](../plugins/image/hello_world_stamp/)
in this repository.

**Image plugins are not captioning plugins.** The two systems look alike and
differ in ways that will bite you if you carry assumptions across; §6 lists them.

## 1. Where plugins live

| OS | Folder |
|----|--------|
| Linux | `~/.local/share/pixlstash/image-plugins/user/` |
| macOS | `~/Library/Application Support/pixlstash/image-plugins/user/` |
| Windows | `%LOCALAPPDATA%\pixlstash\pixlstash\image-plugins\user\` |

PixlStash logs the path at start-up. The folder does not exist until you create
it, and a folder in the wrong place is skipped in silence.

(The doubled `pixlstash` on Windows is `platformdirs` inserting the app author,
which defaults to the app name. PixlStash's own `plugin_template.py` gives this
path with a single `pixlstash` and is wrong; the registry calls
`user_data_dir("pixlstash")`, which doubles it.)

**Only single `.py` files are loaded.** The image registry scans for `*.py` and
skips everything else, so — unlike a captioning plugin — a folder is not a
plugin and a helper module beside it will not be found. One file, everything in
it. That is why a plugin folder in this repository holds a `.py` file named
after the folder: you copy the file, not the folder.

`plugin_template.py` is excluded from discovery by name. Rename your copy.

**Discovery is not a start-up event — and this is the single most important
thing on this page.** `plugin_service.list_plugins()` and
`run_plugin_on_pictures()` both call `manager.reload()`, so the registry
re-scans the folder and re-executes every plugin file **every time the Filters
menu is listed and every time a plugin is run**. Two consequences:

- You do not have to restart the server after adding or editing a plugin. It is
  picked up the next time the menu is opened. (Captioning plugins are the
  opposite — they are discovered once, at start-up.)
- **Anything at module level is paid on every request.** Loading a model, or a
  weights file, in your module body means loading it again on each menu open.
  Do that work lazily inside `run()`, cached on the instance or in a module
  global, and remember the instance itself is replaced on every reload.

Plugin code runs unsandboxed, in the server process, with your permissions. It
is also re-executed constantly, per the above. Only install plugins you trust.

## 2. The minimum plugin

`parameter_schema` and `run` are both abstract, so a class that declares only
the attributes cannot be instantiated and is recorded as a load error. The
smallest thing that actually loads is:

```python
from pixlstash.image_plugins.base import ImagePlugin


class MyFilter(ImagePlugin):
    name = "my_filter"  # unique snake_case id
    display_name = "My Filter"  # label in the Filters menu
    description = "What it does."
    supports_images = True  # handles stills via run()
    supports_videos = False  # True also requires run_video()

    def parameter_schema(self):
        return []

    def run(self, images, parameters=None, progress_callback=None,
            error_callback=None, captions=None):
        return [image.copy() for image in images]
```

**Define exactly one `ImagePlugin` subclass per file, and make it concrete.**
`_find_plugin_class` returns the first `ImagePlugin` subclass it finds in the
module namespace, and it checks neither where that class was defined nor
whether it is abstract. So:

- A subclass you merely **imported** can be picked up instead of yours — and
  since a user plugin wins a name collision (below), importing a built-in is
  enough to silently replace it.
- An **abstract** intermediate base defined above your concrete class can be
  picked up instead, and then fails to instantiate.

The captioning registry does not have either trap: it filters on `__module__`
and skips abstract classes. Do not carry the assumption across.

`name` must be non-empty and unique. **The user directory is scanned before the
built-in one, and the first plugin to claim a name keeps it**, so a user plugin
named `blur_sharpen`, `brightness_contrast`, `colour_filter`, `pixelate`,
`rotate` or `scaling` silently *replaces* the built-in. This is the opposite of
the captioning registry, where the built-in wins and the user plugin is dropped
with a visible error. Pick a name nobody else has.

A plugin that fails to import or construct is recorded as a load error and
skipped; the rest still load.

## 3. `parameter_schema()` — this JSON *is* the settings UI

Required keys: `name` (snake_case), `label`, `type`, `default`.
Optional: `description`, and `options` for a `select`.

| `type` | Control |
|--------|---------|
| `number` | Numeric input |
| `string` | Text field |
| `boolean` | Checkbox |
| `select` | Dropdown — needs `options` |

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
defensively, and note that `params.get(key) or default` turns a deliberate `0`
into the default — use `params.get(key, default)` inside a `try`.

## 4. `run()` — the batch

```python
def run(self, images, parameters=None, progress_callback=None,
        error_callback=None, captions=None):
    ...
```

- **Return a list of the same length, in the same order.** Callers pair outputs
  with inputs positionally. Dropping an entry misaligns everything after it.
- `parameters` may be `None`. Missing keys fall back to your defaults.
- `captions[i]` is picture *i*'s stored description, or `""`. Use it for
  caption-conditioned transforms; it is `None` if the caller passed none.
- Call `self.report_progress(progress_callback, current=…, total=…, message=…)`
  after each image to drive the progress bar.
- **On a per-image failure, call `self.report_error(error_callback, index=…,
  message=…, details=…)` and append a fallback** — the untransformed original —
  rather than raising. Raising abandons every image still to come.

  Append the original object rather than `image.copy()`: whatever broke the
  transform can break the copy too, and an exception raised inside the handler
  loses the batch anyway.

Transforms that change the output size are fine; just return the transformed
image and keep the ordering.

## 5. Video

Set `supports_videos = True` and override `run_video(source_path, parameters,
progress_callback, error_callback)`, returning encoded bytes or a
`(bytes, extension)` tuple.

`self.transform_video(source_path, transform, …)` on the base class does the
decode → transform → encode loop for you and picks a container/codec your
OpenCV build can actually open. It hands your callable one RGB PIL frame at a
time and sizes the writer from the first transformed frame, so a transform that
changes frame size needs no size arithmetic — but it **must return the same size
for every frame**.

**`transform_video` is only on `develop`, not on any release.** PixlStash 1.9.0
has no such method, so a plugin calling it dies with `AttributeError` on the
current release. Either write the decode/encode loop yourself, or guard with
`hasattr(self, "transform_video")` and fall back. This is a public method, so
the "only underscore-prefixed helpers move between versions" rule of thumb in §7
does not save you here — check before you lean on it.

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
| Classes per module | exactly one — first found wins, imported or abstract | all concrete classes the module defines |
| Name collision | **user plugin wins**, replacing the built-in | built-in wins, user plugin dropped |
| `select` options | `["a", "b"]` | `[{"value": "a", "label": "A"}]` |
| Parameter types | `number`, `string`, `boolean`, `select` | those plus `integer`, `textarea`, `csv-int` |
| Per-item failure | `report_error(...)` + append the original | map the path to `None` |
| Base class imports | Pillow, numpy, OpenCV | standard library only |

## 7. Dependencies

Whatever you import must already be installed in the environment PixlStash runs
in. PixlStash reads no manifest and installs nothing for you; a missing import
shows up as a load error. Say what you need in your plugin's README and list it
in a `requirements.txt` beside it.

Pillow, numpy and OpenCV are always available — the base class itself imports
them.

Import only `pixlstash.image_plugins.base`, and only its public surface. The
underscore-prefixed helpers on `ImagePlugin` (`_coerce_number` and friends) are
not part of the plugin API and are not present in every PixlStash version.

Check what your target version actually has, rather than what the source you are
reading has: `transform_video` and `_coerce_number` are both on `develop` and
neither is in 1.9.0. `hasattr` is cheap.

## 8. Licensing

`pixlstash/image_plugins/base.py` and `plugin_template.py` are MIT-licensed as
an explicit exception to the GPL-3.0 backend, so your plugin can carry whatever
license you like. Importing anything else from `pixlstash` puts you back under
the GPL. Plugins contributed to this repository are MIT, like the repository.

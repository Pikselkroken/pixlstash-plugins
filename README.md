# PixlStash plugins

Community plugins for [PixlStash](https://github.com/Pikselkroken/pixlstash) —
both kinds, in one repository:

- **Captioning plugins** turn an image into tags or a description. A VLM, a GGUF
  model through `llama-cpp-python`, a remote API, a rule you wrote yourself.
- **Image plugins** turn a picture into another picture. They are the Filters
  menu: colour grades, crops, watermarks, upscalers, diffusion passes.

PixlStash loads both from folders on your machine, so neither needs a change to
PixlStash itself. This repository is a place to keep them: one self-contained
folder per plugin, ready to copy into the right directory. Nothing here is built
or installed as a package — a plugin is plain Python source that PixlStash
imports and runs in its own process.

> **Captioning plugins need a PixlStash build that loads them, and no release
> has one yet.** Discovery landed in
> [PR #937](https://github.com/Pikselkroken/pixlstash/pull/937), is on the
> `develop` branch, and is targeted at **1.10.0**; the current release, v1.9.0,
> cannot load anything from `plugins/captioning/`. Run PixlStash from `develop`
> until 1.10.0 ships. **Image plugins work on released PixlStash today.**

## Repository layout

```
plugins/
  captioning/                     copy the whole FOLDER into tagger-plugins/user/
    hello_world_tagger/
      __init__.py                 the plugin itself
      README.md                   what it does, what it needs, what it takes
    hello_world_captioner/
      __init__.py
      README.md
  image/                          copy the .py FILE into image-plugins/user/
    hello_world_stamp/
      hello_world_stamp.py        the plugin itself, named after its folder
      README.md
docs/
  writing-captioning-plugins.md   the captioning contract
  writing-image-plugins.md        the image contract
tests/
  test_captioning_plugins.py      contract tests every captioning plugin must pass
  test_image_plugins.py           ...and every image plugin
  plugin_loader.py                imports plugins the way PixlStash does
requirements-dev.txt              what those tests need
ruff.toml                         lint rules, pinned so CI does not drift
.github/workflows/ci.yml          runs the tests on every pull request
```

Every plugin is one folder holding everything it needs: the code, its own
README, and a `requirements.txt` if it depends on packages PixlStash does not
already ship. Nothing is shared between plugins, so copying one folder out gives
you a working plugin and copying one in is a self-contained pull request.

**The two kinds are installed differently**, which is why the folders are
separate. A captioning plugin is a Python package and you copy the whole folder.
An image plugin is a single file — the loader scans for `.py` and cannot see a
folder — so you copy the file out of its folder and leave the README behind.

## Installing a plugin

1. Find the right user plugin directory. **Take the exact path from PixlStash**
   rather than from this table — a folder in the wrong place is skipped in
   silence. Captioning plugin paths are printed in **Settings → Auto-tagging**;
   both are logged at start-up.

   | OS | Captioning plugins | Image plugins |
   |----|--------------------|---------------|
   | Linux | `~/.local/share/pixlstash/tagger-plugins/user/` | `~/.local/share/pixlstash/image-plugins/user/` |
   | macOS | `~/Library/Application Support/pixlstash/tagger-plugins/user/` | `~/Library/Application Support/pixlstash/image-plugins/user/` |
   | Windows | `%LOCALAPPDATA%\pixlstash\pixlstash\tagger-plugins\user\` | `%LOCALAPPDATA%\pixlstash\pixlstash\image-plugins\user\` |

   (The doubled `pixlstash` on Windows is not a typo — `platformdirs` inserts
   the app author, which defaults to the app name.)

2. Create the folder if it does not exist. PixlStash does not create it for you.

3. Copy the plugin in:
   - **captioning** — the whole folder, e.g.
     `plugins/captioning/hello_world_tagger/` →
     `.../tagger-plugins/user/hello_world_tagger/`
   - **image** — the `.py` file only, e.g.
     `plugins/image/hello_world_stamp/hello_world_stamp.py` →
     `.../image-plugins/user/hello_world_stamp.py`

4. Install whatever the plugin's README lists under **Dependencies**, into the
   environment PixlStash runs in. PixlStash reads no manifest and installs
   nothing for you; a missing import shows up as that plugin's load error.

5. Make PixlStash notice it. **The two kinds differ here as well:**
   - **captioning** — **restart PixlStash Server.** Discovery runs once, at
     start-up, and there is deliberately no reload button: re-instantiating a
     plugin whose model is resident would orphan that model in VRAM.
   - **image** — nothing to do. The registry re-scans the folder every time the
     Filters menu is listed and every time a plugin runs, so an added or edited
     plugin is picked up on the next use. (The flip side, if you are writing
     one: your module body is re-executed that often too.)

6. Use it. Tag plugins get a checkbox under **Settings → Auto-tagging**,
   captioners are picked there as the active description plugin, and image
   plugins appear in the Filters menu.

Plugin code runs unsandboxed, in the server process, with your permissions.
**Only install plugins you trust**, from this repository or anywhere else. Read
the source first — every plugin here is one short file, so that is a realistic
thing to ask.

## The example plugins

Three plugins that load no model, so they run anywhere and prove the wiring
works. All three are meant to be copied and edited: rename the folder, rename
the class, give it a new `name`, and replace the transform.

| Plugin | Kind | What it does |
|--------|------|--------------|
| [`hello_world_tagger`](plugins/captioning/hello_world_tagger/) | captioning | Tags every image `hello world`. If those tags appear after a tagging run, your plugin folder is in the right place. |
| [`hello_world_captioner`](plugins/captioning/hello_world_captioner/) | captioning | Writes a short templated description. The smallest complete captioner: a parameter schema, a batch loop, and the per-image failure signal. |
| [`hello_world_stamp`](plugins/image/hello_world_stamp/) | image | Draws "Hello World" onto the picture in magenta. The smallest complete image plugin: schema, batch loop, progress reporting, and a failure that costs one picture rather than the batch. |

## Writing a plugin

The contracts are in `docs/`, and they are worth reading before you start —
each documents what PixlStash actually does today, including the parts that do
not work the way you would assume:

- **[Writing a captioning / tagging plugin](docs/writing-captioning-plugins.md)**
- **[Writing an image plugin](docs/writing-image-plugins.md)**

The two systems look alike and differ in ways that will bite you if you carry
assumptions across — name collisions resolve in opposite directions, `select`
options have different shapes, a folder is a plugin in one and not the other.
There is a table of the differences at the end of the image guide.

Four things that apply to both:

- **`parameter_schema()` *is* the settings UI.** PixlStash builds the plugin's
  settings dialog from the JSON you return, so there is no UI to write.
- **Values are not type-checked.** Read them defensively — and prefer
  `params.get(key, default)` over `params.get(key) or default`, which quietly
  turns a deliberate `0` into the default.
- **A failure must cost one picture, not the batch.** Captioning plugins map
  that path to `None`; image plugins call `report_error` and pass the original
  through. Catch broadly around your inference call: third-party model code
  raises whatever it likes.
- **Import only the base class.** `pixlstash.tagger_plugins.base` and
  `pixlstash.image_plugins.base` are MIT-licensed exceptions to PixlStash's
  GPL-3.0 backend. Anything else in `pixlstash` puts your plugin under the GPL,
  and private helpers (leading underscore) differ between versions.

To start from an example:

```bash
git clone https://github.com/Pikselkroken/pixlstash-captioning-plugins.git
cd pixlstash-captioning-plugins

# a captioning plugin — copy the folder, edit __init__.py
cp -r plugins/captioning/hello_world_captioner plugins/captioning/my_captioner

# an image plugin — copy the folder, then rename the .py to match it
cp -r plugins/image/hello_world_stamp plugins/image/my_filter
mv plugins/image/my_filter/hello_world_stamp.py plugins/image/my_filter/my_filter.py
```

Then edit the plugin file, give the class a new `name`, and rewrite the folder's
`README.md`. Run `pytest` — the contract tests will tell you what you missed.

### Dependencies and build

There is no build step. A plugin is source that PixlStash imports; nothing is
compiled, packaged or published from this repository.

Dependencies are the plugin's own business. List them in the plugin's
`README.md` under **Dependencies**, and, if there are any, in a
`requirements.txt` in its folder. That file is documentation for the person
installing your plugin — PixlStash does not read it, and neither does CI.

Prefer what PixlStash already ships (`torch`, `transformers`, `numpy`,
`pillow`, `opencv-python`, `requests`, …) over a new dependency, and pin any
model revision you download — an unpinned HuggingFace ref is a silent
supply-chain change.

### Running the tests

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
pip install --no-deps pixlstash    # the base classes; a full install pulls torch
pytest
```

The two suites check every plugin folder against its contract: it imports, it
defines the right kind of class, its name is unique and not a built-in's, its
parameter schema is well-formed, and its inference call returns the documented
shape — one entry per input batch, in order, and a broken picture that does not
take the batch down with it.

They check shapes and contracts, not behaviour: whether your model is any good
is not something CI can tell you.

`--no-deps` is deliberate. A full `pip install pixlstash` pulls torch and
friends for nothing: the only things imported here are the two base classes, and
`requirements-dev.txt` carries the handful of packages they actually need.

**A plugin whose dependencies are not installed is skipped entirely**, and CI
installs nothing from a plugin's `requirements.txt`. Every check needs the
plugin class, and the class needs the import, so there is no half-checked
middle ground — skipped means unchecked. CI is therefore a real bar only for
plugins that run on a bare runner; for anything wrapping a model, human review
is the bar, and the pytest output names what was skipped.

That is also why the workflow does not install those requirements: `pytest`
already imports and runs a pull request's plugin code, so CI is not a security
boundary and should not pretend to be one. Read a plugin before you merge it.

## Contributing a plugin

Plugins are welcome. Open a pull request against `main`:

1. **Fork this repository** and branch from `main`.
2. **Add one folder**, under `plugins/captioning/` or `plugins/image/`, named in
   `snake_case`. One plugin per pull request.
   - A captioning plugin folder holds `__init__.py`.
   - An image plugin folder holds one `.py` file named after the folder.
3. **Include a `README.md` in that folder** covering what the plugin does, its
   dependencies, its parameters and its license. Copy the layout from an
   example plugin's README.
4. **Add a `requirements.txt`** in the folder if it needs anything PixlStash
   does not already ship.
5. **Run `pytest`, `ruff check .` and `ruff format .`** before you push. CI runs
   all three; the contract tests are the bar.
6. **Say what you tested it against** in the pull request description — which
   model, which PixlStash version, on what hardware. A reviewer cannot download
   every model, and CI skips any plugin with a dependency, so this is what makes
   a plugin reviewable.
7. **Only contribute code you may license under MIT** (see below). If your
   plugin wraps a model with its own license or usage terms, say so in its
   README — that is the user's decision to make, and they need the facts to
   make it.

What gets a pull request turned down: a plugin that phones home, that reads or
writes outside the paths it is given, that pulls in a dependency it does not
need, or that duplicates an existing plugin here without doing something
meaningfully different. If you are unsure whether an idea fits,
[open an issue](https://github.com/Pikselkroken/pixlstash-captioning-plugins/issues)
before you write it.

Bug reports and fixes for the plugins already here are just as welcome as new
ones.

## License

MIT — see [LICENSE](LICENSE). Contributions are accepted under the same license.

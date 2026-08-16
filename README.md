# PixlStash plugins

Community plugins for [PixlStash](https://github.com/Pikselkroken/pixlstash),
both kinds, in one repository:

- **Captioning plugins** turn an image into tags or a description.
- **Image plugins** turn a picture into another picture. They are the Filters
  menu: colour grades, crops, watermarks, upscalers, diffusion passes.

PixlStash loads both from folders on your machine. There is no build step: a
plugin is plain Python source that PixlStash imports and runs in its own
process, unsandboxed, with your permissions. **Only install plugins you trust**,
and read the source first.

> **Captioning plugins need a PixlStash build that loads them, and no release
> has one yet.** Discovery landed in
> [PR #937](https://github.com/Pikselkroken/pixlstash/pull/937), is on
> `develop`, and is targeted at **1.10.0**; v1.9.0 cannot load anything from
> `plugins/captioning/`. **Image plugins work on released PixlStash today.**

## Layout

```
plugins/captioning/<name>/    __init__.py + README.md  (copy the FOLDER)
plugins/image/<name>/         <name>.py  + README.md   (copy the .PY FILE)
docs/                         the two contracts
tests/                        contract tests every plugin must pass
AGENTS.md, CLAUDE.md          the same instructions, for coding agents
```

One folder per plugin, holding its code, its README, and a `requirements.txt` if
it needs packages PixlStash does not ship. Nothing is shared, so copying a
folder out gives a working plugin and copying one in is a self-contained pull
request. The folders are separate because the two kinds install differently: a
captioning plugin is a Python package, while an image plugin must be a single
file, since that loader scans for `.py` and cannot see a folder.

## Installing a plugin

### With `pixlstash-cli`

PixlStash's own CLI installs from this repository by name, so there is nothing
to copy and no path to get wrong:

```bash
pixlstash-cli plugins install hello_world_captioner   # a folder name under plugins/
pixlstash-cli plugins install ./my_captioner/         # or a local folder, .py or .zip
pixlstash-cli plugins list                            # what is installed, and where
pixlstash-cli plugins remove hello_world_captioner
```

`pixlstash-cli` comes with PixlStash rather than with this repository; the
[PixlStash README](https://github.com/Pikselkroken/pixlstash#installing-plugins)
says how to reach it from a Docker or desktop install, where it is not on your
`PATH`.

`install` reads the source without importing it, works out from the base class
whether it is a captioning plugin or an image filter, and copies it into the
matching directory under the plugin's own `name`. It prints the plan and asks
before writing: `--yes` skips the question, `--dry-run` stops after the plan,
`--force` replaces a plugin of that name, and `--strict` turns every warning
into a refusal. `--ref` takes a branch, tag or commit of this repository and
defaults to `main`; it cannot be pointed at a different repository.

**A plugin's `requirements.txt` is not installed unless you pass
`--with-deps`**, so a plugin with dependencies loads only once you have
installed them into the environment PixlStash runs in.

`plugins list` prints both plugin directories and what is in them, marking a
plugin that will not load as it stands with `!` and one that replaces a
built-in with `*`. It imports nothing, so a failure that only happens at import
(a missing dependency, say) does not show up there. `plugins remove` prints the
exact path and asks before deleting; `--kind captioning|image` picks the
directory when both hold the name, and removing an image plugin that replaced a
built-in brings the built-in back.

Restart PixlStash Server after installing or removing a captioning plugin.
Image filters are re-scanned on the next Filters listing.

### Testing a plugin you are writing

```bash
pixlstash-cli plugins test ./plugins/captioning/my_captioner/
pixlstash-cli plugins test ./plugins/captioning/my_captioner/ --image ~/Pictures/one.jpg
```

`plugins test` loads the plugin the way the server does at start-up, registers
every plugin class it defines, and checks that the parameter schema is one the
settings screen can render, which the server does not check and which fails
quietly when it is wrong. A `problem:` means it will not work and exits 1; a
`warning:` means it works and could be tidier, and exits 0. `--image` runs one
picture through it as well, which loads the model.

Two limits worth knowing: it checks captioning plugins only, not image filters,
and **it is a development aid rather than a security scanner**. It *runs* the
plugin, unsandboxed, with your permissions, exactly as the server would. Only
test a plugin you would have installed anyway.

### By hand

1. Find the user plugin directory. **Take the exact path from PixlStash**, not
   from this table, because a folder in the wrong place is skipped in silence.
   `pixlstash-cli plugins list` prints both, captioning paths are shown in
   **Settings → Auto-tagging**, and both are logged at start-up.

   | OS | Captioning plugins | Image plugins |
   |----|--------------------|---------------|
   | Linux | `~/.local/share/pixlstash/tagger-plugins/user/` | `~/.local/share/pixlstash/image-plugins/user/` |
   | macOS | `~/Library/Application Support/pixlstash/tagger-plugins/user/` | `~/Library/Application Support/pixlstash/image-plugins/user/` |
   | Windows | `%LOCALAPPDATA%\pixlstash\pixlstash\tagger-plugins\user\` | `%LOCALAPPDATA%\pixlstash\pixlstash\image-plugins\user\` |

   (The doubled `pixlstash` on Windows is not a typo: `platformdirs` inserts the
   app author, which defaults to the app name.)

2. Create the folder. PixlStash does not create it for you.

3. Copy the plugin in: the whole folder for captioning, the `.py` file alone for
   image.

4. Install whatever its README lists under **Dependencies**, into the
   environment PixlStash runs in. PixlStash reads no manifest and installs
   nothing; a missing import shows up as that plugin's load error.

5. **Restart PixlStash Server** for a captioning plugin. Discovery runs once, at
   start-up, and there is deliberately no reload button, because
   re-instantiating a plugin whose model is resident would orphan that model in
   VRAM. An image plugin needs no restart: the registry re-scans on every
   Filters listing and every run. (The flip side, if you are writing one: your
   module body is re-executed that often too.)

6. Use it. Tag plugins get a checkbox under **Settings → Auto-tagging**,
   captioners are picked there as the description plugin, and image plugins
   appear in the Filters menu.

## The example plugins

Three plugins that load no model, so they run anywhere and prove the wiring
works. Copy one, rename the folder and class, give it a new `name`, and replace
the transform.

| Plugin | Kind | What it does |
|--------|------|--------------|
| [`hello_world_tagger`](plugins/captioning/hello_world_tagger/) | captioning | Tags every image `hello world`. If those tags appear after a tagging run, your plugin folder is in the right place. |
| [`hello_world_captioner`](plugins/captioning/hello_world_captioner/) | captioning | Writes a short templated description. A parameter schema, a batch loop, and the per-image failure signal. |
| [`hello_world_stamp`](plugins/image/hello_world_stamp/) | image | Draws "Hello World" onto the picture in magenta. Schema, batch loop, progress reporting, and a failure that costs one picture rather than the batch. |

## Writing a plugin

- **[Writing a captioning / tagging plugin](docs/writing-captioning-plugins.md)**
- **[Writing an image plugin](docs/writing-image-plugins.md)**

Read the relevant one first. The two look alike but differ in ways that will
bite you if you carry assumptions across: name collisions resolve in opposite
directions, `select` options have different shapes, a folder is a plugin in one
and not the other. The image guide ends with a table of the differences.

Asking a coding agent to write one works too. Point it at this repository and
at the documentation of the model or API you want wrapped, for example:

> Write me a PixlStash captioning plugin based on the repo at
> https://github.com/Pikselkroken/PixlStash-plugins for the XXX
> captioning system at https://...

[`AGENTS.md`](AGENTS.md) (and its identical twin [`CLAUDE.md`](CLAUDE.md)) is
the brief it should follow: the rules, a skeleton, and the traps. Review what
comes back against the contract, and remember that once a plugin needs a model,
CI checks its shape and never the model behind it.

Five things apply to both:

- **Both kinds carry the same header.** `name`, `display_name`, `description`,
  `author`, `license` and `models` on the class, as plain literals, so a tool
  can say what a plugin is and what it pulls in without importing it. `models`
  is the one people care about: your MIT license says nothing about the weights
  the plugin downloads.
- **`parameter_schema()` *is* the settings UI.** PixlStash builds the dialog
  from the JSON you return.
- **Values are not type-checked.** Prefer `params.get(key, default)` over
  `params.get(key) or default`, which turns a deliberate `0` into the default.
- **A failure must cost one picture, not the batch.** Captioning plugins map
  that path to `None`; image plugins call `report_error` and pass the original
  through. Catch broadly, since third-party model code raises whatever it likes.
- **Import only the base class.** `pixlstash.tagger_plugins.base` and
  `pixlstash.image_plugins.base` are MIT-licensed exceptions to PixlStash's
  GPL-3.0 backend. Anything else puts your plugin under the GPL, and private
  helpers (leading underscore) differ between versions.

To start from an example:

```bash
git clone https://github.com/Pikselkroken/PixlStash-plugins.git
cd PixlStash-plugins

# captioning: copy the folder, edit __init__.py
cp -r plugins/captioning/hello_world_captioner plugins/captioning/my_captioner

# image: copy the folder, then rename the .py to match it
cp -r plugins/image/hello_world_stamp plugins/image/my_filter
mv plugins/image/my_filter/hello_world_stamp.py plugins/image/my_filter/my_filter.py
```

Then give the class a new `name` and `display_name`, put your own `author`,
`license` and `models` in the header (an example plugin's say the example
plugin's, and no test can know that is wrong), rewrite the folder's
`README.md`, and run `pytest`; the contract tests will tell you what else you
missed.

List dependencies in the plugin's README and in a `requirements.txt` beside it.
PixlStash never reads that file, so it is documentation for whoever installs the
plugin, but CI does: it installs each plugin's `requirements.txt` on its own to
run the structure checks, so a file that does not install turns the build red.
Prefer what PixlStash already ships (`torch`, `transformers`, `numpy`,
`pillow`, `opencv-python`, `requests`, …), and pin any model revision you
download, because an unpinned HuggingFace ref is a silent supply-chain change.

### Running the tests

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
pip install --no-deps pixlstash    # the base classes; a full install pulls torch
pytest
```

The suites check shapes, not behaviour: that a plugin imports, defines the right
kind of class, has a unique name that is not a built-in's, carries the header,
has a well-formed parameter schema, and returns the documented shape from its
inference call (one entry per input, in order, and a broken picture that does
not take the batch down with it).

**A plugin whose dependencies are not installed is skipped entirely**: every
check needs the plugin class, and the class needs the import, so skipped means
unchecked rather than half-checked. The pytest output names what was skipped.

### What CI checks, and what it cannot

Two jobs, and the split matters if you are contributing a plugin that wraps a
model:

- **Lint and the full suite**, on a bare runner. `ruff check`,
  `ruff format --check`, and `pytest`. No plugin's `requirements.txt` is
  installed here, so a plugin with dependencies is skipped in this job.
- **Structure, per plugin.** For every plugin that ships a `requirements.txt`,
  CI builds a throwaway virtualenv, installs *that* plugin's requirements into
  it, and runs `test_plugin_structure` for it. One environment per plugin
  rather than the union of all of them, because the union takes longer with
  every plugin added and goes red when two plugins that never meet disagree on
  a version.

What that second job checks is the class and the schema: a `select` with no
`options`, a `type` the settings dialog cannot render, a module that defines no
plugin class, a `parameter_schema()` that raises. What it does not check is
`init()`, any download, or inference. A runner has no GPU and pulling a
multi-GB checkpoint per job is not a sensible use of anyone's minutes, and a
mocked model would only prove the mock works. So **for anything wrapping a
model, human review and your own testing are the bar**, which is why a pull
request has to say what it was run against.

Neither job is a security boundary: both `pip install` and `pytest` run code
out of the pull request, one from its `requirements.txt` and one from the
plugin itself. Read a plugin before you merge it.

## Contributing a plugin

Plugins are welcome. Open a pull request against `main`:

1. **One plugin per pull request**, as one `snake_case` folder under
   `plugins/captioning/` or `plugins/image/`. A captioning folder holds
   `__init__.py`; an image folder holds one `.py` file named after it.
2. **Fill in the header** on the plugin class: `name`, `display_name`,
   `description`, `author`, `license` and `models`, as plain literals. The
   contract tests require all six.
3. **Include a `README.md`** covering what the plugin does, its dependencies,
   its parameters and its license, plus a `requirements.txt` if it needs
   anything PixlStash does not ship. Copy the layout from an example, and keep
   its License section and the header saying the same thing.
4. **Run `pytest`, `ruff check .` and `ruff format .`** before you push.
5. **Say what you tested it against**: which model, which PixlStash version, on
   what hardware. A reviewer cannot download every model, and CI checks the
   structure of a model-backed plugin but never runs the model, so this is what
   makes a plugin reviewable.
6. **Only contribute code you may license under an OSI-approved open source
   license.** If your plugin wraps a model with its own license or usage terms,
   say so in its README; that is the user's decision to make and the license
   should be clearly marked in the header, following the pattern in the example
   plugins.

Turned down: a plugin that phones home, that reads or writes outside the paths
it is given, that pulls in a dependency it does not need, or that duplicates an
existing one without doing something meaningfully different. Unsure whether an
idea fits?
[Open an issue](https://github.com/Pikselkroken/PixlStash-plugins/issues)
first. Bug reports and fixes for the plugins already here are just as welcome.

## License

MIT, see [LICENSE](LICENSE). Contributions are accepted under the same license or OSI-approved licenses.

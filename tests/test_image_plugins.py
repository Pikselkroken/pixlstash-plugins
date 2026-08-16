"""Contract tests every plugin in ``plugins/image/`` must pass.

Image plugins are loaded from a single ``.py`` file, so each folder here holds
exactly one, named after the folder. The checks mirror what
``ImagePluginManager`` does at load, plus what ``run`` promises: one output per
input, same order, and a per-image failure that does not abort the batch.

They split in two the same way the captioning suite does, and for the same
reason: ``test_plugin_structure`` needs the class and nothing else, while the
rest push pictures through ``run``.

A plugin whose dependencies are not installed is skipped entirely rather than
half-checked.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest
from PIL import Image
from pixlstash.image_plugins.base import ImagePlugin
from plugin_loader import (
    IMAGE_DIR,
    check_parameter_schema,
    import_from_path,
    plugin_dirs,
    skip_if_dependency_missing,
)

# Built-in image plugin names. Unlike the captioning registry, the user
# directory is scanned FIRST here, so a user plugin taking one of these names
# silently replaces the built-in rather than being dropped. Worse, not better.
BUILT_IN_NAMES = {
    "blur_sharpen",
    "brightness_contrast",
    "colour_filter",
    "pixelate",
    "rotate",
    "scaling",
}

VALID_TYPES = {"number", "string", "boolean", "select"}

IMAGE_PLUGINS = plugin_dirs(IMAGE_DIR)


def plugin_file(directory: Path) -> Path:
    """Return the single ``.py`` file a plugin folder is expected to hold."""
    return directory / f"{directory.name}.py"


def load_plugin_class(directory: Path) -> type[ImagePlugin]:
    """Import the plugin file and return the class PixlStash would load.

    This is ``ImagePluginManager._find_plugin_class`` verbatim: the *first*
    ``ImagePlugin`` subclass in the module namespace, whether it was defined
    here, merely imported, or abstract. Reimplementing it any more carefully
    than the host does would hide exactly the mistakes it exists to catch: a
    plugin file that imports a built-in ships that built-in instead of its own
    class, and the user directory wins the name, so the built-in is silently
    replaced.
    """
    module_name = "pixlstash_dynamic_plugin_" + plugin_file(directory).name.replace(
        ".", "_"
    )
    try:
        module = import_from_path(module_name, plugin_file(directory))
    except ModuleNotFoundError as exc:
        skip_if_dependency_missing(exc, directory.name)

    candidates = [
        value
        for value in vars(module).values()
        # `is not` rather than a name check: the base class itself is imported
        # into every plugin module.
        if isinstance(value, type)
        and issubclass(value, ImagePlugin)
        and value is not ImagePlugin
    ]
    assert candidates, f"{directory.name}: no ImagePlugin subclass found"
    assert len(candidates) == 1, (
        f"{directory.name}: exactly one ImagePlugin subclass per file. The "
        f"loader takes the first it finds and would ship "
        f"{candidates[0].__name__}, found {[c.__name__ for c in candidates]}"
    )

    found = candidates[0]
    assert found.__module__ == module.__name__, (
        f"{directory.name}: the loader would ship {found.__name__}, which this "
        f"file imported from {found.__module__} rather than defined"
    )
    assert not inspect.isabstract(found), (
        f"{directory.name}: {found.__name__} is abstract. The image loader "
        "does not skip abstract classes, so it would be picked and then fail "
        f"to instantiate. Missing: {sorted(found.__abstractmethods__)}"
    )
    return found


@pytest.fixture
def images() -> list[Image.Image]:
    return [
        Image.new("RGB", (4, 4), (200, 100, 50)),
        Image.new("RGBA", (3, 5), (10, 220, 30, 128)),
    ]


def test_there_are_image_plugins():
    assert IMAGE_PLUGINS, "no plugin folders found under plugins/image/"


def test_every_plugin_is_one_py_file_named_after_its_folder():
    for directory in IMAGE_PLUGINS:
        assert plugin_file(directory).is_file(), (
            f"{directory.name}: expected {directory.name}.py in this folder. "
            "the image plugin loader copies a file, not a folder, and the name "
            "is what keeps two plugins from colliding in the user directory"
        )
        assert (directory / "README.md").is_file(), (
            f"{directory.name}: every plugin needs a README naming its "
            "dependencies and parameters"
        )
        strays = [
            p.name
            for p in directory.glob("*.py")
            if p.name != plugin_file(directory).name
        ]
        assert not strays, (
            f"{directory.name}: {strays} would not be copied with the plugin. "
            "the loader imports one file and cannot see its siblings"
        )


@pytest.mark.parametrize("directory", IMAGE_PLUGINS, ids=lambda p: p.name)
def test_plugin_structure(directory: Path):
    """Everything checkable from the class alone, with no picture touched."""
    plugin = load_plugin_class(directory)()

    name = (plugin.name or "").strip()
    assert name, f"{directory.name}: name must not be empty"
    assert name not in BUILT_IN_NAMES, (
        f"{name}: collides with a built-in image plugin. The user directory is "
        "scanned first, so this would silently replace it"
    )
    assert plugin.supports_images or plugin.supports_videos, (
        f"{name}: set supports_images and/or supports_videos"
    )

    check_parameter_schema(
        name,
        plugin.parameter_schema(),
        VALID_TYPES,
        select_options_are_dicts=False,
    )
    assert plugin.plugin_schema()["name"] == name

    if plugin.supports_videos:
        assert type(plugin).run_video is not ImagePlugin.run_video, (
            f"{name}: supports_videos is True but run_video is not overridden"
        )


@pytest.mark.parametrize("directory", IMAGE_PLUGINS, ids=lambda p: p.name)
def test_plugin_runtime(directory: Path, images: list[Image.Image]):
    """One batch of pictures through ``run``."""
    plugin = load_plugin_class(directory)()
    name = (plugin.name or "").strip()

    # Skipped rather than passed: run() takes pictures, so a video-only plugin
    # has nothing to answer for here, and a silent pass would read as one.
    if not plugin.supports_images:
        pytest.skip(f"{name}: video only, so run() is not exercised")

    defaults = {f["name"]: f["default"] for f in plugin.parameter_schema()}
    out = plugin.run(list(images), defaults)
    assert isinstance(out, list)
    assert len(out) == len(images), (
        f"{name}: run() must return one image per input, in the same order"
    )
    assert all(isinstance(item, Image.Image) for item in out)
    # Output size is deliberately NOT asserted: a crop, a scaler or an
    # upscaler changes it, and the contract is the length and the order.


def test_image_plugin_names_are_unique():
    """Trivially true with one plugin; it is here for the second one."""
    names: dict[str, str] = {}
    for directory in IMAGE_PLUGINS:
        try:
            cls = load_plugin_class(directory)
        except pytest.skip.Exception:
            continue
        assert cls.name not in names, (
            f"{cls.name} is claimed by both {names[cls.name]} and {directory.name}"
        )
        names[cls.name] = directory.name


@pytest.mark.parametrize("directory", IMAGE_PLUGINS, ids=lambda p: p.name)
def test_a_broken_image_does_not_abort_the_batch(directory: Path):
    """A picture that cannot be processed must cost its own slot, not the rest.

    Asserted for every plugin, because it is the contract: ``run`` reports a
    per-image failure through ``error_callback`` and appends a fallback rather
    than raising. Whether a given plugin *notices* this particular breakage
    depends on whether it touches pixels, so the shape is what is checked here
    and the error itself in the plugin's own tests below.
    """
    plugin = load_plugin_class(directory)()
    good = Image.new("RGB", (16, 16), (200, 100, 50))
    broken = Image.new("RGB", (16, 16), (0, 0, 0))
    broken.close()  # any later pixel access raises

    out = plugin.run([good, broken, good], None, error_callback=lambda _: None)

    assert len(out) == 3, f"{directory.name}: the batch lost an entry to a failure"


# ----------------------------------------------------------------------
# hello_world_stamp
# ----------------------------------------------------------------------

BLACK = (0, 0, 0)


def stamp():
    return load_plugin_class(IMAGE_DIR / "hello_world_stamp")()


def ink(image: Image.Image) -> list[tuple[int, int]]:
    """Return the coordinates of every pixel the stamp changed."""
    return [
        (x, y)
        for y in range(image.height)
        for x in range(image.width)
        if image.getpixel((x, y))[:3] != BLACK
    ]


def test_stamp_writes_magenta_text():
    (out,) = stamp().run([Image.new("RGB", (200, 60), BLACK)], {})

    marked = ink(out)
    assert marked, "nothing was drawn"
    assert any(out.getpixel(xy) == (255, 0, 255) for xy in marked), (
        "the text was drawn, but not in magenta"
    )


def bounds(position: str) -> tuple[int, int, int, int]:
    """Return (min_x, min_y, max_x, max_y) of the ink for one placement."""
    (out,) = stamp().run([Image.new("RGB", (400, 200), BLACK)], {"position": position})
    marked = ink(out)
    assert marked, f"{position}: nothing was drawn"
    xs = [x for x, _ in marked]
    ys = [y for _, y in marked]
    return min(xs), min(ys), max(xs), max(ys)


def test_stamp_position():
    """Placements are compared against each other, not against pixel counts.

    Asserting "the ink is in the left half" would depend on how wide Pillow's
    bundled font happens to be, and Pillow is not pinned, so a font metric
    changing by a few percent would turn CI red on code nobody touched. The
    relative ordering holds for any font.
    """
    top_left = bounds("top-left")
    top_right = bounds("top-right")
    bottom_left = bounds("bottom-left")
    bottom_right = bounds("bottom-right")
    centre = bounds("centre")

    # Right-hand placements start further right than left-hand ones.
    assert top_left[0] < top_right[0]
    assert bottom_left[0] < bottom_right[0]
    # Bottom placements start further down than top ones.
    assert top_left[1] < bottom_left[1]
    assert top_right[1] < bottom_right[1]
    # The centre sits between the two on both axes.
    assert top_left[0] < centre[0] < top_right[0]
    assert top_left[1] < centre[1] < bottom_left[1]
    # And every placement stays inside the image.
    for name, (min_x, min_y, max_x, max_y) in [
        ("top-left", top_left),
        ("top-right", top_right),
        ("bottom-left", bottom_left),
        ("bottom-right", bottom_right),
        ("centre", centre),
    ]:
        assert 0 <= min_x and max_x < 400, f"{name}: ink outside the image"
        assert 0 <= min_y and max_y < 200, f"{name}: ink outside the image"


@pytest.mark.parametrize("text", ["", "   ", None, 42])
def test_stamp_empty_or_junk_text_leaves_the_image_alone(text):
    """Empty means "do nothing"; a non-string falls back to the default."""
    (out,) = stamp().run([Image.new("RGB", (200, 60), BLACK)], {"text": text})

    if isinstance(text, str):
        assert not ink(out), "an empty text should leave the image untouched"
    else:
        assert ink(out), "a non-string text should fall back to the default"


@pytest.mark.parametrize("size", [None, "junk", -5, 0, 10**9])
def test_stamp_survives_junk_settings(size, images: list[Image.Image]):
    """Values arrive off a JSON payload and are not type-checked."""
    out = stamp().run(list(images), {"size": size, "position": "nonsense"})

    assert len(out) == len(images)
    assert all(isinstance(item, Image.Image) for item in out)


def test_stamp_keeps_the_alpha_channel():
    (out,) = stamp().run([Image.new("RGBA", (200, 60), (10, 220, 30, 128))], {})

    assert out.mode == "RGBA"
    assert out.getpixel((0, 0))[3] == 128


@pytest.mark.parametrize("mode", ["L", "P", "1", "RGBA", "CMYK"])
def test_stamp_handles_any_source_mode(mode: str):
    """A library holds more than RGB JPEGs."""
    (out,) = stamp().run([Image.new(mode, (200, 60))], {})

    assert isinstance(out, Image.Image)
    assert out.size == (200, 60)


def test_stamp_reports_a_failure_instead_of_raising():
    good = Image.new("RGB", (200, 60), BLACK)
    broken = Image.new("RGB", (200, 60), BLACK)
    broken.close()

    errors: list[dict] = []
    out = stamp().run([good, broken, good], {}, error_callback=errors.append)

    assert len(out) == 3
    assert len(errors) == 1, "the failing image should report exactly one error"
    assert errors[0]["index"] == 1
    assert ink(out[0]), "the images either side of the failure were still stamped"

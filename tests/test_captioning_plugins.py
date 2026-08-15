"""Contract tests every plugin in ``plugins/captioning/`` must pass.

They import each plugin folder the way PixlStash does and check it against the
``TaggerPlugin`` contract: capability flags, a well-formed parameter schema, a
name that does not collide with a built-in, and an inference call that returns
the documented shape.

A plugin whose third-party dependencies are not installed is skipped *entirely*:
CI installs nothing from a plugin's ``requirements.txt``, and every check here
needs the plugin class, which needs the import. So CI is a real bar only for
plugins that run on a bare runner; for anything wrapping a model, human review
is the bar. Skipped plugins are named in the pytest output.
"""

from __future__ import annotations

import base64
import inspect
from pathlib import Path

import pytest
from pixlstash.tagger_plugins.base import TaggerPlugin, TagResult
from plugin_loader import (
    CAPTIONING_DIR,
    check_parameter_schema,
    import_from_path,
    plugin_dirs,
    skip_if_dependency_missing,
)

# Built-in plugin names. The captioning registry loads built-ins first and they
# win a collision, so a user plugin claiming one of these is dropped.
BUILT_IN_NAMES = {"wd14", "pixlstash_tagger", "florence2", "joycaption"}

VALID_TYPES = {
    "number",
    "integer",
    "boolean",
    "select",
    "string",
    "textarea",
    "csv-int",
}

# A 1x1 PNG. No plugin here opens the file, but a plugin that wraps a real model
# will, and this suite is what runs contributed plugins.
_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4"
    "2mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

CAPTIONING_PLUGINS = plugin_dirs(CAPTIONING_DIR)


def load_plugin_classes(directory: Path) -> list[type[TaggerPlugin]]:
    """Import *directory* and return the plugin classes it defines.

    Mirrors the registry: only classes the module itself defines count, so a
    class merely imported into it is not registered twice.
    """
    module_name = "pixlstash_user_tagger_" + directory.name.replace(".", "_")
    try:
        module = import_from_path(module_name, directory)
    except ModuleNotFoundError as exc:
        skip_if_dependency_missing(exc, directory.name)

    return [
        value
        for value in vars(module).values()
        if isinstance(value, type)
        and issubclass(value, TaggerPlugin)
        and value is not TaggerPlugin
        and not inspect.isabstract(value)
        and (
            value.__module__ == module.__name__
            or value.__module__.startswith(module.__name__ + ".")
        )
    ]


def load_one(directory_name: str) -> TaggerPlugin:
    """Return the single plugin instance defined by *directory_name*, ready to run."""
    classes = load_plugin_classes(CAPTIONING_DIR / directory_name)
    assert len(classes) == 1
    plugin = classes[0]()
    plugin.init(plugin.default_params())
    return plugin


@pytest.fixture
def image_paths(tmp_path: Path) -> list[str]:
    paths = []
    for i in range(2):
        path = tmp_path / f"image_{i}.png"
        path.write_bytes(_PNG_1X1)
        paths.append(str(path))
    return paths


def test_there_are_captioning_plugins():
    assert CAPTIONING_PLUGINS, "no plugin folders found under plugins/captioning/"


def test_every_plugin_is_a_package_with_a_readme():
    for directory in CAPTIONING_PLUGINS:
        assert (directory / "__init__.py").is_file(), (
            f"{directory.name}: a captioning plugin folder needs an __init__.py "
            "(PixlStash skips a folder without one)"
        )
        assert (directory / "README.md").is_file(), (
            f"{directory.name}: every plugin needs a README naming its "
            "dependencies and parameters"
        )


@pytest.mark.parametrize("directory", CAPTIONING_PLUGINS, ids=lambda p: p.name)
def test_plugin_contract(directory: Path, image_paths: list[str]):
    classes = load_plugin_classes(directory)
    assert classes, f"{directory.name} defines no concrete TaggerPlugin subclass"

    for cls in classes:
        plugin = cls()
        name = (plugin.name or "").strip()
        assert name, f"{cls.__name__}: name must not be empty"
        assert name not in BUILT_IN_NAMES, (
            f"{name}: collides with a built-in plugin and would be dropped"
        )
        assert plugin.supports_tags or plugin.supports_descriptions, (
            f"{name}: set supports_tags and/or supports_descriptions, or the "
            "plugin appears in no table"
        )

        check_parameter_schema(
            name,
            plugin.parameter_schema(),
            VALID_TYPES,
            select_options_are_dicts=True,
        )
        # The registry exercises this once at load; a raise here takes down the
        # settings screen, so it is worth asserting.
        assert plugin.plugin_schema()["name"] == name

        # PixlStash calls setup() via hasattr before init(), so a plugin whose
        # init depends on it must not be exercised without it.
        if hasattr(plugin, "setup"):
            plugin.setup("cpu")
        plugin.init(plugin.default_params())
        assert plugin.is_loaded() is True, f"{name}: is_loaded() must be truthful"

        # Equality, not subset: with no stop_event a plugin must account for
        # every path it was given. A per-image failure is reported by mapping
        # that path to None, not by dropping the key, and a plugin returning
        # {} would sail through a subset check having done nothing.
        if plugin.supports_tags:
            result = plugin.tag_images(image_paths, plugin.default_params())
            assert set(result) == set(image_paths), (
                f"{name}: tag_images must return an entry for every path"
            )
            for tags in result.values():
                assert isinstance(tags, list)
                assert all(isinstance(tag, TagResult) for tag in tags)

        if plugin.supports_descriptions:
            result = plugin.generate_descriptions(image_paths, plugin.default_params())
            assert set(result) == set(image_paths), (
                f"{name}: generate_descriptions must return an entry for every path"
            )
            for caption in result.values():
                assert caption is None or isinstance(caption, str)

        plugin.unload()


def test_plugin_names_are_unique_across_the_repository():
    names: dict[str, str] = {}
    for directory in CAPTIONING_PLUGINS:
        try:
            classes = load_plugin_classes(directory)
        except pytest.skip.Exception:
            continue
        for cls in classes:
            assert cls.name not in names, (
                f"{cls.name} is claimed by both {names[cls.name]} and {directory.name}"
            )
            names[cls.name] = directory.name


# ----------------------------------------------------------------------
# hello_world_tagger
# ----------------------------------------------------------------------


def test_hello_world_tagger_tags_every_image(image_paths: list[str]):
    result = load_one("hello_world_tagger").tag_images(
        image_paths, {"tags": "hello world, example", "confidence": 0.5}
    )

    assert set(result) == set(image_paths)
    for tags in result.values():
        assert [t.tag for t in tags] == ["hello world", "example"]
        assert all(t.confidence == 0.5 for t in tags)


@pytest.mark.parametrize("tags", [None, "", "   ", " , , ", 42])
def test_hello_world_tagger_survives_junk_settings(tags, image_paths: list[str]):
    """Saved values are validated by name, not by type, and never tag nothing."""
    result = load_one("hello_world_tagger").tag_images(
        image_paths, {"tags": tags, "confidence": "not a number"}
    )

    assert set(result) == set(image_paths)
    for tag_list in result.values():
        assert tag_list, "a tagger that emits no tags at all has silently failed"
        assert all(t.tag != "None" for t in tag_list)
        assert all(t.confidence == 1.0 for t in tag_list)


def test_hello_world_tagger_clamps_confidence(image_paths: list[str]):
    result = load_one("hello_world_tagger").tag_images(
        image_paths, {"tags": "a", "confidence": 7.5}
    )

    assert all(t.confidence == 1.0 for tags in result.values() for t in tags)


# ----------------------------------------------------------------------
# hello_world_captioner
# ----------------------------------------------------------------------


def test_hello_world_captioner_fills_the_template(image_paths: list[str]):
    plugin = load_one("hello_world_captioner")
    result = plugin.generate_descriptions(image_paths, plugin.default_params())

    assert set(result) == set(image_paths)
    for path, caption in result.items():
        assert caption == f"Hello world. A picture named {Path(path).name}."


@pytest.mark.parametrize(
    "template",
    [
        "{nope}",  # KeyError
        "{filename.nope}",  # AttributeError, undocumented by str.format
        "{0}",  # IndexError
        "{filename:d}",  # ValueError
    ],
)
def test_hello_world_captioner_fails_one_image_not_the_batch(
    template: str, image_paths: list[str]
):
    """A broken template must fail its image, never raise out of the batch."""
    result = load_one("hello_world_captioner").generate_descriptions(
        image_paths, {"template": template}
    )

    assert set(result) == set(image_paths)
    assert all(caption is None for caption in result.values())


@pytest.mark.parametrize(
    ("max_length", "expected"),
    [(10, 10), (0, 300), (-1, 300), ("junk", 200), (None, 200)],
)
def test_hello_world_captioner_max_length(
    max_length, expected: int, image_paths: list[str]
):
    """0 or less means no truncation; junk falls back to the 200 default."""
    result = load_one("hello_world_captioner").generate_descriptions(
        image_paths, {"template": "x" * 300, "max_length": max_length}
    )

    assert all(len(caption) == expected for caption in result.values())

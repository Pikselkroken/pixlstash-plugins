"""Import a plugin the way PixlStash does, so the tests exercise the real path.

Both PixlStash registries load a plugin with ``spec_from_file_location`` rather
than from ``sys.path``, and the captioning registry passes
``submodule_search_locations`` so a package plugin's ``from . import helper``
resolves. Copying that here means a plugin that imports cleanly under pytest
imports cleanly under PixlStash, and the folder-naming rules are the host's
rather than an artefact of how the tests happen to import.
"""

from __future__ import annotations

import ast
import importlib.util
import inspect
import re
import sys
from pathlib import Path
from textwrap import dedent
from types import ModuleType
from typing import Any

import pytest

PLUGINS_DIR = Path(__file__).resolve().parent.parent / "plugins"
CAPTIONING_DIR = PLUGINS_DIR / "captioning"
IMAGE_DIR = PLUGINS_DIR / "image"

# The header: what a tool needs to tell a user what a plugin is before running
# it. Both plugin systems carry the same six.
HEADER_FIELDS = (
    "name",
    "display_name",
    "description",
    "author",
    "license",
    "models",
)

# "Your Name <your.name@example.com>", or an http(s) URL between the brackets
# when there is nobody to email. One name and one contact, so neither half may
# hold a bracket, and the string is nothing but those two.
AUTHOR = re.compile(
    r"\S[^<>\n]* <(?:[^@<>\s]+@[^@<>\s]+\.[^@<>\s]+|https?://[^<>\s]+)>"
)


def plugin_dirs(root: Path) -> list[Path]:
    """Return every plugin folder under *root*, in name order."""
    if not root.is_dir():
        return []
    return sorted(
        p
        for p in root.iterdir()
        if p.is_dir() and not p.name.startswith((".", "_", "__"))
    )


def import_from_path(module_name: str, path: Path) -> ModuleType:
    """Import *path*, a ``.py`` file or a package directory, as *module_name*."""
    if path.is_dir():
        spec = importlib.util.spec_from_file_location(
            module_name,
            path / "__init__.py",
            submodule_search_locations=[str(path)],
        )
    else:
        spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not create an import spec for {path}")

    module = importlib.util.module_from_spec(spec)
    # Registered before exec so relative imports inside a package resolve.
    displaced = sys.modules.get(module_name)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        if displaced is not None:
            sys.modules[module_name] = displaced
        elif sys.modules.get(module_name) is module:
            del sys.modules[module_name]
        raise
    return module


def skip_if_dependency_missing(exc: ModuleNotFoundError, plugin: str) -> None:
    """Skip the test when *exc* is a plugin dependency CI does not install.

    A missing ``pixlstash`` is never skipped: that is the harness being wrong,
    not the plugin.
    """
    if exc.name and exc.name.split(".")[0] != "pixlstash":
        pytest.skip(f"{plugin}: dependency '{exc.name}' is not installed")
    raise exc


def read_class_header(cls: type) -> dict[str, Any]:
    """Return the header fields *cls* declares as literals, in its source.

    ``ast.literal_eval`` over the class bodies rather than ``getattr`` over the
    object, because that is the promise the header makes: a tool can say what a
    plugin is without importing it, and importing a plugin runs its module body
    on the reader's machine. A field computed at import, or assigned in
    ``__init__``, is not in the header however good it looks at runtime; it
    comes back missing, and the caller says so.

    Inherited fields count, since a reader can follow a base class in the same
    way, so the walk is over the MRO with the first declaration winning. It
    stops short of PixlStash's own base classes, which declare the header's
    empty defaults: three of the six on a release, and on ``develop`` all six.
    Inheriting those would pass a plugin that declares nothing at all, and
    report a field set in ``__init__`` as ``''`` when its source plainly says
    otherwise.
    """
    header: dict[str, Any] = {}
    for klass in cls.__mro__:
        if klass.__module__.split(".")[0] == "pixlstash":
            continue
        try:
            statements = ast.parse(dedent(inspect.getsource(klass))).body[0].body
        except (OSError, TypeError, SyntaxError, IndexError, AttributeError):
            # No source to read: a builtin, or a class defined in a REPL.
            continue
        # Backwards through the class body, so that within one class the last
        # assignment wins, as it does when Python executes it. `setdefault`
        # then keeps the first class in the MRO, which is the other half of
        # the same rule: a subclass shadows its base.
        for statement in reversed(statements):
            if isinstance(statement, ast.Assign):
                targets = statement.targets
            elif isinstance(statement, ast.AnnAssign):
                targets = [statement.target]
            else:
                continue
            fields = [
                t.id
                for t in targets
                if isinstance(t, ast.Name) and t.id in HEADER_FIELDS
            ]
            if not fields or statement.value is None:
                continue
            try:
                value = ast.literal_eval(statement.value)
            except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
                continue  # not a literal, so not readable without running it
            for field in fields:
                header.setdefault(field, value)
    return header


def check_header_values(name: str, header: dict[str, Any]) -> None:
    """Assert the header *values* are shapes a tool can put in front of a user."""
    for field in ("name", "display_name", "description"):
        value = header.get(field)
        assert isinstance(value, str) and value.strip(), (
            f"{name}: {field} must be a non-empty string, since a tool has "
            f"nothing else to put in front of a user, got {value!r}"
        )

    author = header.get("author")
    assert isinstance(author, str) and AUTHOR.fullmatch(author), (
        f"{name}: author must be 'Your Name <your.name@example.com>', one name "
        "and one contact, the contact an email address or an http(s) URL, got "
        f"{author!r}"
    )

    plugin_license = header.get("license")
    assert isinstance(plugin_license, str) and plugin_license.strip(), (
        f"{name}: license must name the license of the plugin's own code, as "
        f"an SPDX identifier where there is one, got {plugin_license!r}"
    )

    models = header.get("models")
    assert isinstance(models, list), (
        f"{name}: models must be a list, empty when the plugin uses no model, "
        f"got {models!r}"
    )
    for model in models:
        assert isinstance(model, dict), (
            f"{name}: each models entry must be a dict, got {type(model).__name__!r}"
        )
        for key in ("name", "license"):
            value = model.get(key)
            assert isinstance(value, str) and value.strip(), (
                f'{name}: each models entry needs a non-empty "{key}"; a user '
                f"deciding whether to run this needs both, got {model!r}"
            )


def check_plugin_header(name: str, plugin: object) -> None:
    """Assert *plugin* carries the header a tool can present to a user.

    Six class attributes, the same on both kinds of plugin: ``name`` (whose
    collision rules belong to the caller), ``display_name``, ``description``,
    ``author``, ``license`` and ``models``. Nothing in PixlStash reads them
    today, so this suite is what keeps them on the plugins in this repository.
    """
    cls = type(plugin)
    header = read_class_header(cls)

    missing = [field for field in HEADER_FIELDS if field not in header]
    assert not missing, (
        f"{name}: {missing} must be declared in the body of {cls.__name__} (or "
        "a base class) as literals. The header is read off the source without "
        "importing the plugin, so a value computed at import or set in "
        "__init__ is not there to be read."
    )

    check_header_values(name, header)

    for field in HEADER_FIELDS:
        runtime = getattr(plugin, field, None)
        assert runtime == header[field], (
            f"{name}: {field} is {runtime!r} on the object but {header[field]!r} "
            "in the source. A tool reads the source and PixlStash runs the "
            "object, so the two must not disagree."
        )


def check_parameter_schema(
    name: str, schema: list[dict], valid_types: set[str], select_options_are_dicts: bool
) -> None:
    """Assert *schema* is a well-formed parameter schema.

    The two plugin systems differ on ``select``: captioning plugins declare
    ``options`` as ``[{"value": ..., "label": ...}]``, image plugins as a plain
    list of allowed values.
    """
    assert isinstance(schema, list), f"{name}: parameter_schema() must return a list"
    seen = set()
    for field in schema:
        assert isinstance(field, dict), (
            f"{name}: each parameter schema entry must be a dict, got "
            f"{type(field).__name__!r}"
        )
        for key in ("name", "label", "type", "default"):
            assert key in field, f"{name}: parameter is missing '{key}': {field}"
        assert field["name"] not in seen, f"{name}: duplicate parameter {field['name']}"
        seen.add(field["name"])
        assert field["type"] in valid_types, (
            f"{name}: unknown parameter type {field['type']!r} "
            f"(allowed: {sorted(valid_types)})"
        )
        if field["type"] == "select":
            options = field.get("options")
            assert options, f"{name}: a select parameter needs options"
            if select_options_are_dicts:
                for option in options:
                    assert isinstance(option, dict), (
                        f"{name}: each select option must be a dict, got "
                        f"{type(option).__name__!r}"
                    )
                    assert "value" in option and "label" in option, (
                        f"{name}: select options must be "
                        '[{"value": ..., "label": ...}]'
                    )
            else:
                assert all(not isinstance(o, dict) for o in options), (
                    f"{name}: image plugin select options are a plain list of "
                    "values, not dicts"
                )
            assert field["default"] in [
                o["value"] if select_options_are_dicts else o for o in options
            ], f"{name}: the default of {field['name']} is not one of its options"

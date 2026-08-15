"""Import a plugin the way PixlStash does, so the tests exercise the real path.

Both PixlStash registries load a plugin with ``spec_from_file_location`` rather
than from ``sys.path``, and the captioning registry passes
``submodule_search_locations`` so a package plugin's ``from . import helper``
resolves. Copying that here means a plugin that imports cleanly under pytest
imports cleanly under PixlStash, and the folder-naming rules are the host's
rather than an artefact of how the tests happen to import.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

PLUGINS_DIR = Path(__file__).resolve().parent.parent / "plugins"
CAPTIONING_DIR = PLUGINS_DIR / "captioning"
IMAGE_DIR = PLUGINS_DIR / "image"


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

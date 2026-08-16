"""Tests for the shared validators in ``plugin_loader``.

They are the thing that tells a contributor what is wrong with their plugin, so
they have to fail with a message that names the problem rather than dying on a
``TypeError`` several lines later.
"""

from __future__ import annotations

import pytest
from pixlstash.tagger_plugins.base import TaggerPlugin
from plugin_loader import (
    check_header_values,
    check_parameter_schema,
    check_plugin_header,
    read_class_header,
)

CAPTIONING_TYPES = {"string", "integer", "select"}
IMAGE_TYPES = {"string", "number", "select"}


def check(schema, *, dicts: bool = True) -> None:
    check_parameter_schema(
        "plugin_under_test",
        schema,
        CAPTIONING_TYPES if dicts else IMAGE_TYPES,
        select_options_are_dicts=dicts,
    )


def test_a_valid_schema_passes():
    check(
        [
            {"name": "text", "label": "Text", "type": "string", "default": ""},
            {
                "name": "mode",
                "label": "Mode",
                "type": "select",
                "default": "a",
                "options": [{"value": "a", "label": "A"}],
            },
        ]
    )


@pytest.mark.parametrize(
    ("schema", "expected"),
    [
        ("not a list", "must return a list"),
        # "name" in "names" is True, so a bare string used to slip past the
        # key checks and fail later on an unhelpful TypeError.
        ([["name", "label", "type", "default"]], "must be a dict"),
        (["names"], "must be a dict"),
        ([{"label": "L", "type": "string", "default": ""}], "missing 'name'"),
        (
            [{"name": "n", "label": "L", "type": "nope", "default": ""}],
            "unknown parameter type",
        ),
        (
            [
                {"name": "n", "label": "L", "type": "string", "default": ""},
                {"name": "n", "label": "L", "type": "string", "default": ""},
            ],
            "duplicate parameter",
        ),
        (
            [{"name": "n", "label": "L", "type": "select", "default": "a"}],
            "needs options",
        ),
        # A bare string is truthy and iterable, so it gets walked one character
        # at a time; each character then fails the option check by name.
        (
            [
                {
                    "name": "n",
                    "label": "L",
                    "type": "select",
                    "default": "a",
                    "options": "ab",
                }
            ],
            "select option must be a dict",
        ),
        (
            [
                {
                    "name": "n",
                    "label": "L",
                    "type": "select",
                    "default": "a",
                    "options": ["a", "b"],
                }
            ],
            "select option must be a dict",
        ),
        (
            [
                {
                    "name": "n",
                    "label": "L",
                    "type": "select",
                    "default": "z",
                    "options": [{"value": "a", "label": "A"}],
                }
            ],
            "not one of its options",
        ),
    ],
)
def test_a_malformed_schema_says_what_is_wrong(schema, expected: str):
    with pytest.raises(AssertionError, match=expected):
        check(schema)


HEADER = {
    "name": "plugin_under_test",
    "display_name": "Plugin Under Test",
    "description": "What it does.",
    "author": "Your Name <your.name@example.com>",
    "license": "MIT",
    "models": [{"name": "acme/tiny-vlm", "license": "Apache-2.0"}],
}


def check_values(**overrides) -> None:
    check_header_values("plugin_under_test", {**HEADER, **overrides})


def test_a_valid_header_passes():
    check_values()
    check_values(models=[])
    # A URL is a contact too, for a plugin with nobody to email.
    check_values(author="PixlStash plugins <https://example.com/plugins>")


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"name": 42}, "name must be"),
        ({"description": "  "}, "description must be"),
        ({"display_name": ""}, "display_name must be"),
        ({"author": "Your Name"}, "author must be"),
        ({"author": "your.name@example.com"}, "author must be"),
        # An unclosed bracket, two contacts, and a contact that is neither an
        # address nor a URL are all somebody's problem downstream.
        ({"author": "Your Name <your.name@example.com"}, "author must be"),
        ({"author": "Me <me@example.com> and You <you@example.com>"}, "author must be"),
        ({"author": "Your Name <your.name@example.com>\n"}, "author must be"),
        ({"author": "Your Name <@>"}, "author must be"),
        ({"author": "Your Name <javascript:alert(1)>"}, "author must be"),
        ({"license": ""}, "license must name"),
        ({"license": None}, "license must name"),
        ({"models": {"name": "n", "license": "MIT"}}, "models must be a list"),
        ({"models": ["acme/tiny-vlm"]}, "entry must be a dict"),
        ({"models": [{"name": "acme/tiny-vlm"}]}, 'needs a non-empty "license"'),
        ({"models": [{"license": "MIT"}]}, 'needs a non-empty "name"'),
    ],
)
def test_a_malformed_header_says_what_is_wrong(overrides: dict, expected: str):
    with pytest.raises(AssertionError, match=expected):
        check_values(**overrides)


class LiteralHeader:
    """A header the way a plugin declares it: six literals in the class body."""

    name = "plugin_under_test"
    display_name = "Plugin Under Test"
    description = "What it does."
    author = "Your Name <your.name@example.com>"
    license = "MIT"
    models = [{"name": "acme/tiny-vlm", "license": "Apache-2.0"}]


_LICENSE = "MIT"
_MODEL = {"name": "acme/tiny-vlm", "license": "Apache-2.0"}


class ComputedHeader:
    """The same values, lifted out of the class body into module constants.

    Innocent, and the way the example plugins hold their defaults, but a reader
    that will not execute the module cannot resolve a name into a value.
    """

    name = "plugin_under_test"
    display_name = "Plugin Under Test"
    description = "What it does."
    author = "Your Name <your.name@example.com>"
    license = _LICENSE
    models = [_MODEL]


class DisagreeingHeader(LiteralHeader):
    """Says MIT to a reader of the source and something else at runtime."""

    def __init__(self) -> None:
        self.license = "Proprietary, all rights reserved"


def test_a_literal_header_is_read_off_the_source():
    assert read_class_header(LiteralHeader) == HEADER
    check_plugin_header("plugin_under_test", LiteralHeader())


def test_an_inherited_header_counts():
    """A reader can follow a base class, so a plugin need not repeat itself."""

    class Subclass(LiteralHeader):
        name = "subclass"

    assert read_class_header(Subclass) == {**HEADER, "name": "subclass"}


def test_the_hosts_own_defaults_are_not_a_header():
    """``TaggerPlugin`` declares three of the six as ``""``.

    Inheriting those would leave the literal check dead for exactly the fields
    a user reads, and tell a plugin that sets ``display_name`` in ``__init__``
    that its value is empty when its source says otherwise.
    """

    class Inheriting(TaggerPlugin):
        name = "inheriting"

    assert set(read_class_header(Inheriting)) == {"name"}


@pytest.mark.parametrize("field", ["license", "models"])
def test_a_computed_header_is_not_a_header(field: str):
    """The point of the header is that nobody has to run the plugin to read it."""
    assert field not in read_class_header(ComputedHeader)
    with pytest.raises(AssertionError, match=f"'{field}'.* must be declared"):
        check_plugin_header("plugin_under_test", ComputedHeader())


def test_the_source_and_the_object_must_agree():
    """A tool reads the class body; PixlStash runs the instance."""
    with pytest.raises(AssertionError, match="license is 'Proprietary"):
        check_plugin_header("plugin_under_test", DisagreeingHeader())


def test_a_plugin_without_a_header_at_all_says_so():
    class Bare:
        pass

    with pytest.raises(AssertionError, match="must be declared"):
        check_plugin_header("plugin_under_test", Bare())


def test_image_select_options_must_not_be_dicts():
    schema = [
        {
            "name": "n",
            "label": "L",
            "type": "select",
            "default": "a",
            "options": [{"value": "a", "label": "A"}],
        }
    ]
    with pytest.raises(AssertionError, match="plain list of"):
        check(schema, dicts=False)

"""Tests for the shared schema validator in ``plugin_loader``.

It is the thing that tells a contributor what is wrong with their plugin, so it
has to fail with a message that names the problem rather than dying on a
``TypeError`` several lines later.
"""

from __future__ import annotations

import pytest
from plugin_loader import check_parameter_schema

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

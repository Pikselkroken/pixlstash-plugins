"""Hello-world captioner plugin for PixlStash.

Writes a short description built from a template rather than from a model, so
it runs anywhere and takes no GPU.  It exists to show the shape of a captioner:
the parameter schema, the batch loop, and how a single image reports failure
without losing the rest of the batch.

Copy the whole ``hello_world_captioner`` folder into your user tagger plugin
directory and restart PixlStash Server.  See the repository README.
"""

from __future__ import annotations

import os
from typing import Any

from pixlstash.tagger_plugins.base import TaggerPlugin

DEFAULT_TEMPLATE = "Hello world. A picture named {filename}."


class HelloWorldCaptioner(TaggerPlugin):
    """Captions every image from a template, with no model involved."""

    name = "hello_world_captioner"
    display_name = "Hello World Captioner"
    description = "Writes a short templated description. Example plugin."

    supports_tags = False
    supports_descriptions = True
    requires_download = False

    def __init__(self) -> None:
        self._loaded = False
        self._device = "cpu"

    # ------------------------------------------------------------------
    # Schema — this JSON *is* the settings UI
    # ------------------------------------------------------------------

    def parameter_schema(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "template",
                "label": "Caption template",
                "type": "textarea",
                "default": DEFAULT_TEMPLATE,
                "description": (
                    "Caption text. {filename}, {stem} and {extension} are "
                    "replaced per image."
                ),
            },
            {
                "name": "max_length",
                "label": "Max length",
                "type": "integer",
                "default": 200,
                "min": 10,
                "max": 2000,
                "step": 10,
                "description": (
                    "Captions longer than this are truncated. 0 or less means "
                    "no truncation."
                ),
            },
        ]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def setup(self, device: str) -> None:
        """Receive the inference device. A real captioner loads onto it."""
        self._device = device

    def needs_download(self, parameters: dict[str, Any] | None = None) -> bool:
        return False

    def init(self, parameters: dict[str, Any]) -> None:
        self._loaded = True

    def unload(self) -> None:
        self._loaded = False

    def is_loaded(self) -> bool:
        return self._loaded

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def generate_descriptions(
        self,
        image_paths: list[str],
        parameters: dict[str, Any],
        stop_event=None,
    ) -> dict[str, str | None]:
        """Return one caption per path. ``None`` marks a per-image failure."""
        # Saved settings are validated by name but not by type, so read them
        # defensively. Note `.get(key, default)` rather than `.get(key) or
        # default`: the second turns a deliberate 0 into the default.
        template = parameters.get("template", DEFAULT_TEMPLATE)
        if not isinstance(template, str) or not template:
            template = DEFAULT_TEMPLATE
        try:
            max_length = int(parameters.get("max_length", 200))
        except (TypeError, ValueError):
            max_length = 200

        results: dict[str, str | None] = {}
        for path in image_paths:
            # stop_event is always None on the description path today; guard
            # the access rather than assume it stays that way.
            if stop_event is not None and stop_event.is_set():
                break
            filename = os.path.basename(path)
            stem, extension = os.path.splitext(filename)
            try:
                caption = template.format(
                    filename=filename,
                    stem=stem,
                    extension=extension.lstrip("."),
                )
            except Exception:
                # A template the user typed can fail in more ways than one:
                # {nope} raises KeyError, {filename.nope} raises AttributeError,
                # {0} raises IndexError. Catch broadly and fail this image
                # only — raising would lose the whole batch. This is the shape
                # a real captioner's inference call should have too.
                results[path] = None
                continue
            # max_length <= 0 means "do not truncate".
            results[path] = caption[:max_length] if max_length > 0 else caption
        return results

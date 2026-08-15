"""Hello-world tagger plugin for PixlStash.

Applies a fixed set of tags to every image.  Useful as a starting point and as
a way to prove the plugin folder is wired up correctly: if these tags show up
after a tagging run, PixlStash found and ran your plugin.

Copy the whole ``hello_world_tagger`` folder into your user tagger plugin
directory and restart PixlStash Server.  See the repository README.
"""

from __future__ import annotations

from typing import Any

from pixlstash.tagger_plugins.base import TaggerPlugin, TagResult

DEFAULT_TAGS = "hello world"


class HelloWorldTagger(TaggerPlugin):
    """Tags every image with a fixed, user-configurable list of tags."""

    name = "hello_world_tagger"
    display_name = "Hello World Tagger"
    description = "Applies a fixed list of tags to every image. Example plugin."

    supports_tags = True
    supports_descriptions = False
    requires_download = False
    default_enabled = False

    def __init__(self) -> None:
        self._loaded = False

    # ------------------------------------------------------------------
    # Schema — this JSON *is* the settings UI
    # ------------------------------------------------------------------

    def parameter_schema(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "tags",
                "label": "Tags",
                "type": "string",
                "default": DEFAULT_TAGS,
                "description": "Comma-separated tags applied to every image.",
            },
            {
                "name": "confidence",
                "label": "Confidence",
                "type": "number",
                "default": 1.0,
                "min": 0.0,
                "max": 1.0,
                "step": 0.05,
                "description": "Confidence reported for each tag.",
            },
        ]

    # ------------------------------------------------------------------
    # Lifecycle — no model, so there is nothing to load or free
    # ------------------------------------------------------------------

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

    def tag_images(
        self,
        image_paths: list[str],
        parameters: dict[str, Any],
        preloaded: dict | None = None,
        stop_event=None,
    ) -> dict[str, list[TagResult]]:
        """Return the configured tags for every path in the batch."""
        # Saved settings are validated by name but not by type, so read them
        # defensively — a string where a number was expected is a real case.
        raw = parameters.get("tags", DEFAULT_TAGS)
        tags = [t.strip() for t in str(raw or "").split(",") if t.strip()]
        if not tags:
            # None, "", or "  ,  ". Tagging nothing at all is never what the
            # user meant by installing a tagger. (`raw or ""` rather than
            # str(raw): str(None) would tag every image "None".)
            tags = [DEFAULT_TAGS]
        try:
            confidence = float(parameters.get("confidence", 1.0))
        except (TypeError, ValueError):
            confidence = 1.0
        confidence = min(1.0, max(0.0, confidence))

        results: dict[str, list[TagResult]] = {}
        for path in image_paths:
            if stop_event is not None and stop_event.is_set():
                break
            results[path] = [TagResult(tag=tag, confidence=confidence) for tag in tags]
        return results
